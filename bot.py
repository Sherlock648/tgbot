import sqlite3
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, CallbackContext
import pytz
from datetime import datetime, timedelta
from telegram.ext import CommandHandler
from telegram.ext import ContextTypes
from config import TOKEN
import asyncio
from asyncio import Lock
import os
import re
import sys
from telegram import Bot
import undetected_chromedriver as uc
from selenium.webdriver.common.action_chains import ActionChains
import time
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, NoSuchElementException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from selenium.webdriver.chrome.service import Service
from glob import glob

bot = Bot(token=TOKEN)

event_queue = asyncio.Queue()

scheduler = AsyncIOScheduler()

user_roles = {
    "owner": "sherlock_cole",  
    "head_admins": {"IlyaLoco", "masonishka"},  
    "admins": {}  
}

pending_groups = {}
user_time_slots = {}

db_connection = sqlite3.connect("database.db", check_same_thread=False)
cursor = db_connection.cursor()

conn = sqlite3.connect("chat_logs.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    username TEXT,
    message_text TEXT,
    file_path TEXT,
    message_id INTEGER,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS employee_time_slots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE,
    start_time TIME,
    end_time TIME,
    sender_chat_id TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS shift_totals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT,
    entry_number INTEGER,
    exit_number INTEGER,
    total INTEGER,
    entry_time DATETIME,
    exit_time DATETIME
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS onlymonster_credentials (
    telegram_id INTEGER PRIMARY KEY,
    username TEXT,
    email TEXT,
    password TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

def get_chat_id_from_db(username):
    try:
        cursor.execute("SELECT chat_id FROM user_settings WHERE username = ?", (username,))
        result = cursor.fetchone()
        if result:
            return result[0]
        else:
            print(f"Chat ID для пользователя @{username} не найден.")
            return None
    except Exception as e:
        print(f"Ошибка при извлечении chat_id: {e}")
        return None

class OnlyMonsterManager:
    def __init__(self):
        self.driver = None 

    def setup_driver(self):
        if self.driver is None:
            options = uc.ChromeOptions()
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--window-size=1920,1080')
            options.add_argument('--disable-blink-features=AutomationControlled')
            options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36')

            chromedriver_path = r"C:\Users\sasha\Downloads\chromedriver.exe"
            service = Service(chromedriver_path)

            self.driver = uc.Chrome(service=service, options=options)


    async def login_to_onlymonster(self, update: Update, email: str, password: str) -> bool:
        username = update.message.from_user.username
        if username != user_roles["owner"] and username not in user_roles["head_admins"]:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return False
        try:
            self.setup_driver()
            self.driver.get("https://onlymonster.ai/auth/signin")

            wait = WebDriverWait(self.driver, 60)

            print("Авторизация...")
            email_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[name='identifier']")))
            password_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[name='password']")))

            email_field.send_keys(email)
            password_field.send_keys(password)

            await self.find_and_click_button(wait, css_selector=".cl-formButtonPrimary")

            
            try:
                wait.until(lambda d: "/panel/creators" in d.current_url)
                print("✅ Успешный вход")
                
                
                if self.driver:
                    self.driver.quit()
                    self.driver = None
                    
                return True
            except Exception as e:
                print(f"❌ Ошибка при проверке URL после входа: {str(e)}")
                return False

        except Exception as e:
            print(f"❌ Ошибка при попытке входа: {str(e)}")
            return False
        finally:
            
            if self.driver:
                self.driver.quit()
                self.driver = None

    async def wait_for_page_load(self, timeout=120):  
        """Ждет полной загрузки страницы с дополнительными проверками"""
        print("Ожидание полной загрузки страницы...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                page_state = self.driver.execute_script('return document.readyState;')
                jquery_state = self.driver.execute_script('''return (typeof jQuery !== "undefined") ? jQuery.active == 0 : true;''')
                loading_elements = self.driver.find_elements(By.CSS_SELECTOR, '.loading-indicator, .loader, .spinner')
                no_loaders = len(loading_elements) == 0
                
                xhr_complete = self.driver.execute_script('''return window.performance
                        .getEntriesByType('resource')
                        .filter(e => e.initiatorType === 'xmlhttprequest')
                        .every(e => e.responseEnd > 0);''')
                
                if page_state == 'complete' and jquery_state and no_loaders and xhr_complete:
                    print("✅ Страница полностью загружена")
                    await asyncio.sleep(2)
                    return True
            
            except Exception as e:
                print(f"Ошибка при проверке загрузки страницы: {str(e)}")
            
            await asyncio.sleep(1)
        
        print("❌ Timeout при ожидании загрузки страницы")
        return False

    async def find_and_click_button(self, wait, css_selector=None, xpath=None, button_text=None, retries=3):
        """Улучшенная функция для поиска и клика по кнопке"""
        for attempt in range(retries):
            try:
                if button_text == "Export":
                    possible_locators = [
                        (By.XPATH, "//button[normalize-space()='Export']"),
                        (By.XPATH, "//button[contains(., 'Export') and not(contains(., 'Excel'))]"),
                        (By.CSS_SELECTOR, "button:has(svg) span:contains('Export')"),
                        (By.XPATH, "//button[.//svg and contains(normalize-space(), 'Export')]"),
                    ]
                    
                    for locator in possible_locators:
                        try:
                            button = wait.until(EC.element_to_be_clickable(locator))
                            if button:
                                break
                        except:
                            continue
                else:
                    button = None
                    if css_selector:
                        button = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, css_selector)))
                    elif xpath:
                        button = wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                    elif button_text:
                        button = wait.until(EC.element_to_be_clickable(
                            (By.XPATH, f"//button[contains(normalize-space(), '{button_text}')]")
                        ))

                if button:
                    print(f"Найдена кнопка: {button.text}")
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center', behavior: 'smooth'});", button)
                    await asyncio.sleep(2)
                    try:
                        button.click()
                    except:
                        try:
                            self.driver.execute_script(
                                "arguments[0].dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));", 
                                button
                            )
                        except:
                            actions = ActionChains(self.driver)
                            actions.move_to_element(button)
                            actions.click()
                            actions.perform()
                    
                    print(f"Успешный клик по кнопке: {button_text or 'Unknown'}")
                    return True
                
            except Exception as e:
                print(f"Попытка {attempt + 1}/{retries} не удалась: {str(e)}")
                await asyncio.sleep(2)
        
        print(f"❌ Не удалось кликнуть по кнопке после {retries} попыток")
        return False

    async def click_export_buttons(self):
        """Функция для клика по кнопкам Export и Export to Excel"""
        try:
            
            export_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Export')]"))
            )
            print("Кнопка 'Export' найдена.")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", export_button)
            export_button.click()
            print("Клик по кнопке 'Export' выполнен.")

            
            export_to_excel_button = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Export to Excel')]"))
            )
            print("Кнопка 'Export to Excel' найдена.")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", export_to_excel_button)
            export_to_excel_button.click()
            print("Клик по кнопке 'Export to Excel' выполнен.")
        except Exception as e:
            print(f"Ошибка при клике по кнопкам Export: {e}")
            
            
            downloaded_file = None
            download_folder = r"C:\Users\sasha\Downloads"
            
            
            while not downloaded_file:
                downloaded_file = next(
                    (fname for fname in os.listdir(download_folder) if fname.endswith(".xlsx")), 
                    None
                )

                if downloaded_file:
                    file_path = os.path.join(download_folder, downloaded_file)
                    return file_path

                
                time.sleep(1)

            print("Файл не найден в папке загрузок.")
            return None

        except Exception as e:
            print(f"Ошибка при клике по кнопкам Export или скачивании файла: {e}")
            return None


    
    def format_date(self, date_str):
        date_obj = datetime.strptime(date_str, "%d.%m.%Y")
        return date_obj.strftime("%m-%d-%Y %I:%M %p")  

    
    async def check_stat(self, update: Update, email: str, password: str, start_date: str, end_date: str) -> str:
            self.setup_driver()
            self.driver.get("https://onlymonster.ai/auth/signin")

            wait = WebDriverWait(self.driver, 60)

            print("Авторизация...")
            email_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[name='identifier']")))
            password_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "[name='password']")))

            email_field.send_keys(email)
            password_field.send_keys(password)

            await self.find_and_click_button(wait, css_selector=".cl-formButtonPrimary")

            wait.until(lambda d: "/panel/creators" in d.current_url)
            print("✅ Успешный вход")

            self.driver.get("https://onlymonster.ai/panel/chatter-metrics/")
            if not await self.wait_for_page_load():
                return None

            print("✅ Страница статистики загружена")

            
            checkbox = wait.until(EC.presence_of_element_located((By.ID, "likeOnlyfans")))
            checkbox.click()

            
            time.sleep(5)

            
            start_date_formatted = self.format_date(start_date)
            end_date_formatted = self.format_date(end_date)

            
            date_input = self.driver.find_element(By.NAME, "date")

            
            date_input.click()

            
            date_input.click()  
            time.sleep(1)  
            date_input.clear()  


            
            time.sleep(2)

            
            print(f"Start Date: {start_date_formatted}, End Date: {end_date_formatted}")
            date_input.send_keys(f"{start_date_formatted} ~ {end_date_formatted}")

            
            select_time_button = self.driver.find_element(By.XPATH, "//button[contains(text(),'Select time')]")
            
            select_time_button.click()

            
            time.sleep(3)

            
            try:
                
                WebDriverWait(self.driver, 5).until(
                    EC.presence_of_element_located(
                        (By.XPATH, "//button[contains(@class, 'primary-btn') and contains(., 'Select date')]")
                    )
                )
                print("Окно с выбором даты найдено. Повторный ввод времени...")
                
                date_input.click()
                date_input.send_keys(Keys.CONTROL + "a")
                time.sleep(1)
                date_input.send_keys(Keys.BACKSPACE)
                time.sleep(0.5)
                date_input.send_keys(f"{start_date_formatted} ~ {end_date_formatted}")
                self.driver.find_element(By.TAG_NAME, "body").click()
            except:
                print("Окно с выбором даты не появилось.")

            
            time.sleep(5)

            
            export_button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[normalize-space()='Export']")))
            if export_button.is_displayed() and export_button.is_enabled():
                print("Найдена кнопка: Export")
                
                self.driver.execute_script("arguments[0].scrollIntoView(true);", export_button)
                await asyncio.sleep(1)  
                self.driver.execute_script("arguments[0].click();", export_button)
                print("Успешный клик по кнопке Export")
                await asyncio.sleep(2)
            else:
                print("Кнопка Export не видна или недоступна.")
                return None

            
            export_to_excel_button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[normalize-space()='Export to Excel']")))

            if export_to_excel_button.is_displayed() and export_to_excel_button.is_enabled():
                print("Найдена кнопка: Export to Excel")
                
                self.driver.execute_script("arguments[0].scrollIntoView(true);", export_to_excel_button)
                await asyncio.sleep(1)  
                self.driver.execute_script("arguments[0].click();", export_to_excel_button)
                print("Успешный клик по кнопке Export to Excel")
                await asyncio.sleep(2)
            else:
                print("Кнопка Export to Excel не видна или недоступна.")
                return None

            
            download_folder = r"C:\Users\sasha\Downloads"

            
            if not os.path.exists(download_folder):
                print(f"❌ Папка {download_folder} не существует.")
                return None

            
            print("Ожидаем завершение скачивания файла...")
            await asyncio.sleep(5)  

            
            downloaded_file = None
            for _ in range(10):  
                files = [f for f in os.listdir(download_folder) if f.endswith(".xlsx")]
                if files:
                    downloaded_file = os.path.join(download_folder, files[0])
                    print(f"Файл найден: {downloaded_file}")
                    break
                await asyncio.sleep(1)

            if downloaded_file:
                return downloaded_file
            else:
                print("❌ Файл не был загружен.")
                return None


def find_latest_file(directory: str, extension: str = "*.xlsx") -> str:
    
    files = glob(os.path.join(directory, extension))
    
    if not files:
        return None  

    
    latest_file = max(files, key=os.path.getmtime)
    return latest_file


manager = OnlyMonsterManager()  

async def check_stat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        username = update.message.from_user.username
        if username != user_roles["owner"] and username not in user_roles["head_admins"]:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return

        telegram_id = update.message.from_user.id
        cursor.execute("""SELECT email, password FROM onlymonster_credentials WHERE telegram_id = ?""", (telegram_id,))
        credentials = cursor.fetchone()

        if not credentials:
            await update.message.reply_text("❌ Учетные данные не найдены. Используйте команду /login для входа.")
            return

        email, password = credentials

        message_parts = update.message.text.split()
        if len(message_parts) != 3:
            await update.message.reply_text("❌ Неверный формат команды. Используйте: /check_stat <start_date> <end_date>.")
            return
        
        start_date = message_parts[1]
        end_date = message_parts[2]

        status_message = await update.message.reply_text("🔄 Выполняем экспорт данных...")
        await manager.check_stat(update, email, password, start_date, end_date)

        downloads_dir = r"C:\Users\sasha\Downloads"
        file_path = find_latest_file(downloads_dir)

        if file_path:
            print(f"Файл найден: {file_path}")
            await status_message.edit_text("✅ Данные успешно экспортированы!")
            await update.message.reply_document(document=open(file_path, "rb"))
        else:
            await status_message.edit_text("❌ Не удалось найти экспортированный файл.")

    except Exception as e:
        print(f"Ошибка в check_stat_command: {str(e)}")
        await update.message.reply_text("❌ Произошла ошибка при выполнении команды.")

    finally:
        
        if manager.driver:
            manager.driver.quit()

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        
        username = update.message.from_user.username
        if username != user_roles["owner"] and username not in user_roles["head_admins"]:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return

        
        if len(context.args) != 2:
            await update.message.reply_text(
                "❌ Неверный формат команды.\n"
                "Используйте: /login email password"
            )
            return

        email = context.args[0]
        password = context.args[1]

        
        manager = OnlyMonsterManager()
        
        
        status_message = await update.message.reply_text("🔄 Выполняется вход в OnlyMonster...")

        
        success = await manager.login_to_onlymonster(update, email, password)

        if success:
            
            telegram_id = update.message.from_user.id
            cursor.execute("""
                INSERT OR REPLACE INTO onlymonster_credentials 
                (telegram_id, username, email, password) 
                VALUES (?, ?, ?, ?)
            """, (telegram_id, username, email, password))
            conn.commit()

            await status_message.edit_text("✅ Успешный вход в OnlyMonster!")
        else:
            await status_message.edit_text("❌ Не удалось войти в OnlyMonster. Проверьте учетные данные.")

    except Exception as e:
        print(f"Ошибка в login_command: {str(e)}")
        await update.message.reply_text(f"❌ Произошла ошибка: {str(e)}")



def escape_markdown(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return ''.join(f"\\{char}" if char in escape_chars else char for char in text)

TARGET_THREAD_IDS = [4]  
TARGET_CHAT_IDS = [-1002298054169]  
TARGET_KEYWORDS = [
    "вышла", "вышел", "зашел", "зашёл", "зашла", "вход", "выход"
    "Зашла", "Вышла", "Зашел", "Вышел", "Зашёл", "Вход", "Выход"
]


entry_events_lock = asyncio.Lock()  
entry_events = {}
entry_logs = {}


async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat  
    chat_id = chat.id  
    thread_id = update.effective_message.message_thread_id  

    
    response = f"ID чата (chat_id): {chat_id}"
    if thread_id:
        response += f"\nID топика (message_thread_id): {thread_id}"

    
    await update.message.reply_text(response)



from asyncio import Event

async def monitor_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        message = update.message
        if not message or not message.text:
            print("monitor_messages: Сообщение отсутствует или не содержит текст.")
            return

        chat_id = message.chat.id
        thread_id = message.message_thread_id
        username = message.from_user.username
        if username:
            username = username.lstrip("@")
        else:
            username = "Unknown"

        print("\n=== MONITOR MESSAGES DEBUG ===")
        print(f"Получено сообщение от @{username}")
        print(f"Текст: '{message.text}'")
        print(f"Chat ID: {chat_id}")
        print(f"Thread ID: {thread_id}")

        if chat_id not in TARGET_CHAT_IDS:
            print("❌ Сообщение из нецелевого чата")
            return

        if thread_id not in TARGET_THREAD_IDS:
            print("❌ Сообщение из нецелевой темы")
            return

        message_text = message.text.strip()
        
        
        entry_match = re.match(r"(зашел|Зашел|зашла|Зашла|зашёл|Зашёл|вход|Вход)\s+(\d+)", message_text)
        exit_match = re.match(r"(вышел|Вышел|вышла|Вышла|Выход|выход)\s+(\d+)", message_text)
        
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        current_time = datetime.now(kyiv_tz)

        if entry_match:
            entry_number = entry_match.group(2)  
            cursor.execute("""
                INSERT INTO shift_totals (username, entry_number, entry_time)
                VALUES (?, ?, ?)
            """, (username, int(entry_number), current_time))
            conn.commit()
            print(f"✅ Зафиксирован вход с числом {entry_number}")
        
        elif exit_match:
            exit_number = exit_match.group(2)  
            
            
            cursor.execute("""
                SELECT id, entry_number FROM shift_totals
                WHERE username = ? AND exit_number IS NULL
                ORDER BY entry_time DESC LIMIT 1
            """, (username,))
            
            last_entry = cursor.fetchone()
            if last_entry:
                shift_id, entry_number = last_entry
                total = int(exit_number) - entry_number
                
                cursor.execute("""
                    UPDATE shift_totals
                    SET exit_number = ?, exit_time = ?, total = ?
                    WHERE id = ?
                """, (int(exit_number), current_time, total, shift_id))
                conn.commit()
                print(f"✅ Зафиксирован выход с числом {exit_number}, итого за смену: {total}")
            else:
                print("❌ Не найдена открытая смена для этого пользователя.")
        
        else:
            
            print("❌ Не удалось определить сумму в сообщении")
            await message.reply_text("❌ Не удалось определить сумму в сообщении")
            return

        
        found_keywords = [kw for kw in TARGET_KEYWORDS if kw.lower() in message_text.lower()]
        if found_keywords:
            print(f"✅ Найдены ключевые слова: {found_keywords}")
            entry_logs[username] = {
                "message": message_text,
                "timestamp": current_time.strftime('%Y-%m-%d %H:%M:%S')
            }
            await event_queue.put(username)

    except Exception as e:
        print(f"❌ Ошибка в monitor_messages: {e}")
        import traceback
        traceback.print_exc()



async def log_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        message = update.message
        if not message:
            print("log_messages: Сообщение отсутствует.")
            return

        print("\n=== LOG MESSAGES DEBUG ===")
        chat_id = message.chat.id
        thread_id = message.message_thread_id
        username = message.from_user.username or "Unknown"
        user_id = message.from_user.id

        
        message_text = message.text or message.caption or ""
        file_path = None

        print(f"Попытка логирования сообщения:")
        print(f"От: @{username}")
        print(f"Текст: '{message_text}'")
        print(f"Chat ID: {chat_id}")
        print(f"Thread ID: {thread_id}")

        if chat_id not in TARGET_CHAT_IDS:
            print("❌ Сообщение из нецелевого чата")
            return

        if thread_id not in TARGET_THREAD_IDS:
            print("❌ Сообщение из нецелевой темы")
            return

        
        if message.photo:
            photo = message.photo[-1]  
            file = await context.bot.get_file(photo.file_id)
            
            
            os.makedirs('photos', exist_ok=True)
            
            
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_path = f'photos/{username}_{timestamp}.jpg'
            
            
            await file.download_to_drive(file_path)
            print(f"✅ Фото сохранено: {file_path}")

        
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        timestamp = datetime.now(kyiv_tz).strftime('%Y-%m-%d %H:%M:%S')

        
        cursor.execute("""
        INSERT INTO chat_logs (
            chat_id, user_id, username, message_text, file_path, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?)
        """, (chat_id, user_id, username, message_text, file_path, timestamp))
        conn.commit()

        print(f"✅ Сообщение успешно сохранено в базу данных")

    except Exception as e:
        print(f"❌ Ошибка в log_messages: {e}")
        import traceback
        traceback.print_exc()

import sqlite3

def get_sender_chat_id_from_db(sender_username):
    
    db_path = 'chat_logs.db'  
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        query = "SELECT username, sender_chat_id FROM employee_time_slots WHERE username = ?"
        cursor.execute(query, (sender_username,))
        result = cursor.fetchone()

        if result:
            sender_chat_id = result[1]  
            print(f"Найден chat_id: {sender_chat_id}")
        else:
            sender_chat_id = None  
            print(f"Не найден chat_id для пользователя {sender_username}")
        
        cursor.close()
        conn.close()

        return sender_chat_id

    except sqlite3.Error as e:
        print(f"Ошибка при подключении к базе данных: {e}")
        return None



async def schedule_user_check_with_entry(target_username, start_time, end_time, sender_chat_id, bot: Bot):
    application = Application.builder().token(TOKEN).build()
    bot = application.bot

    try:
        print(f"\nDEBUG schedule_user_check_with_entry:")
        print(f"- Target username: {target_username}")
        print(f"- Start time: {start_time}")
        print(f"- End time: {end_time}")
        print(f"- Sender Chat ID: {sender_chat_id}")

        kyiv_tz = pytz.timezone('Europe/Kyiv') #замените на собственный чп
        now = datetime.now(kyiv_tz)

        current_date = now.date()
        start_time_only = start_time.time()
        end_time_only = end_time.time()

        start_time_today = kyiv_tz.localize(datetime.combine(current_date, start_time_only))
        end_time_today = kyiv_tz.localize(datetime.combine(current_date, end_time_only))

        if end_time_today <= start_time_today:
            end_time_today += timedelta(days=1)

        print(f"Текущее время: {now}")
        print(f"Установленное время начала: {start_time_today}")
        print(f"Установленное время конца: {end_time_today}")

        if now < start_time_today:
            wait_time = (start_time_today - now).total_seconds()
            print(f"- Ожидание до начала: {wait_time} секунд")
            await asyncio.sleep(wait_time)

        now = datetime.now(kyiv_tz)
        print(f"- Текущее время после первого ожидания: {now}")

        if now < end_time_today:
            wait_time = (end_time_today - now).total_seconds()
            print(f"- Ожидание до конца: {wait_time} секунд")
            await asyncio.sleep(wait_time)

        print(f"- Текущее состояние entry_logs: {entry_logs}")
        print(f"- Размер очереди перед проверкой: {event_queue.qsize()}")

        timeout = 0
        while True:
            if timeout > 20:
                print("- ОШИБКА: Превышено время ожидания")
                break

            try:
                print("- Ожидание события из очереди...")
                username_in_queue = await asyncio.wait_for(event_queue.get(), timeout=2)
                print(f"- Получено из очереди: {username_in_queue}")
                
                if username_in_queue == target_username:
                    print("- УСПЕХ: Найдено соответствие в очереди")
                    break
                else:
                    print(f"- Несоответствие username: ожидали {target_username}, получили {username_in_queue}")
            except asyncio.TimeoutError:
                timeout += 1
                print(f"- Таймаут #{timeout}")
                continue

        try:
            if target_username in entry_logs:
                log_entry = entry_logs[target_username]
                await bot.send_message(
                    chat_id=sender_chat_id,
                    text=f"✅ Сотрудник @{target_username} зашёл вовремя.\nСообщение: '{log_entry['message']}' (в {log_entry['timestamp']})"
                )
                entry_logs.pop(target_username, None)
            else:
                await bot.send_message(
                    chat_id=sender_chat_id,
                    text=f"❌ Сотрудник @{target_username} не зашёл в указанный промежуток времени."
                )
        except Exception as e:
            print(f"Ошибка при отправке сообщения: {e}")


    except Exception as e:
        print(f"- ОШИБКА в schedule_user_check_with_entry: {e}")
        import traceback
        traceback.print_exc()

async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    try:
        message = update.message
        if not message:
            print("show_balance: Сообщение отсутствует.")
            return
        args = context.args
        username = None
        start_date = None
        end_date = None
        
        if args:
            
            if args[0].startswith("@"):
                username = args[0].lstrip("@")
                args = args[1:]  
            else:
                username = message.from_user.username or "Unknown"
                username = username.lstrip("@")
            
            
            if len(args) == 1:
                start_date = end_date = datetime.strptime(args[0], '%d.%m.%Y').date()
            elif len(args) == 2:
                start_date = datetime.strptime(args[0], '%d.%m.%Y').date()
                end_date = datetime.strptime(args[1], '%d.%m.%Y').date()
        else:
            
            username = message.from_user.username or "Unknown"
            username = username.lstrip("@")

        print(f"Запрос баланса для пользователя @{username} за период: {start_date} - {end_date}")

        
        cursor.execute("SELECT COUNT(*) FROM shift_totals WHERE username = ?", (username,))
        user_exists = cursor.fetchone()[0] > 0

        if not user_exists:
            await message.reply_text(f"❌ Пользователь @{username} не найден в базе.")
            print(f"❌ Пользователь @{username} не найден.")
            return

        
        query = """
            SELECT entry_number, exit_number, DATE(entry_time)
            FROM shift_totals
            WHERE username = ? AND exit_number IS NOT NULL
        """
        params = [username]

        if start_date:
            query += " AND DATE(entry_time) >= ?"
            params.append(start_date)

        if end_date:
            query += " AND DATE(entry_time) <= ?"
            params.append(end_date)

        cursor.execute(query, tuple(params))
        shifts = cursor.fetchall()

        if not shifts:
            await message.reply_text(f"❌ У пользователя @{username} нет завершённых смен за указанный период.")
            print(f"❌ У пользователя @{username} нет завершённых смен за выбранный период.")
            return

        
        balance = 0
        shift_details = []
        for entry_number, exit_number, shift_date in shifts:
            shift_balance = exit_number - entry_number
            balance += shift_balance
            shift_details.append(f"{shift_date}: {entry_number} ➡ {exit_number} = {shift_balance}")

        balance = round(balance, 2)  
        payouts = round(balance * 0.2, 2)  

        
        shift_details_text = "\n".join(shift_details)
        response_text = (
            f"💼 Расчёт баланса для пользователя @{username} за период:\n"
            f"{shift_details_text}\n"
            f"\n💼 Итоговый баланс: {balance}\n"
            f"💵 Итоговые выплаты: {payouts}"
        )

        await message.reply_text(response_text)
        print(f"✅ Баланс для @{username} отправлен.")

    except Exception as e:
        print(f"❌ Ошибка в show_balance: {e}")
        await message.reply_text("❌ Произошла ошибка при расчёте баланса.")
        import traceback
        traceback.print_exc()


async def clear_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    
    try:
        message = update.message
        if not message:
            print("clear_balance: Сообщение отсутствует.")
            return

        args = context.args
        username = None

        if args:
            if args[0].startswith("@"):
                username = args[0].lstrip("@")
            else:
                username = message.from_user.username or "Unknown"
                username = username.lstrip("@")
        else:
            
            username = message.from_user.username or "Unknown"
            username = username.lstrip("@")

        print(f"Сброс баланса для пользователя @{username}")


        cursor.execute("SELECT COUNT(*) FROM shift_totals WHERE username = ?", (username,))
        user_exists = cursor.fetchone()[0] > 0

        if not user_exists:
            await message.reply_text(f"❌ Пользователь @{username} не найден в базе.")
            print(f"❌ Пользователь @{username} не найден.")
            return
        
        cursor.execute("DELETE FROM shift_totals WHERE username = ?", (username,))
        db_connection.commit()  

        await message.reply_text(f"✅ Баланс пользователя @{username} успешно очищен.")
        print(f"✅ Баланс пользователя @{username} очищен.")

    except Exception as e:
        print(f"❌ Ошибка в clear_balance: {e}")
        await message.reply_text("❌ Произошла ошибка при очистке баланса.")
        import traceback
        traceback.print_exc()


async def set_time_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sender_username = update.message.from_user.username
    sender_chat_id = update.message.chat.id  
    print(f"DEBUG: sender_chat_id из update.message.chat.id: {sender_chat_id}")

    if sender_username != user_roles["owner"] and sender_username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    bot = context.bot

    try:
        args = context.args
        if len(args) < 3:
            await update.message.reply_text(
                "Использование: /set_time_slot <username> <start_time> <end_time>.\n"
                "Пример: /set_time_slot @user 07:30 08:30"
            )
            return

        target_username = args[0].lstrip("@")
        print(f"DEBUG: target_username: {target_username}")
        
        start_time_str = args[1]
        end_time_str = args[2]

        try:
            datetime.strptime(start_time_str, "%H:%M")
            datetime.strptime(end_time_str, "%H:%M")
        except ValueError:
            await update.message.reply_text("Неверный формат времени. Используйте ЧЧ:ММ, например 07:30")
            return

        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(kyiv_tz)

        start_time = kyiv_tz.localize(datetime.combine(now.date(), datetime.strptime(start_time_str, "%H:%M").time()))
        end_time = kyiv_tz.localize(datetime.combine(now.date(), datetime.strptime(end_time_str, "%H:%M").time()))

        if end_time <= start_time:
            end_time += timedelta(days=1)

        
        cursor.execute(""" 
            INSERT OR REPLACE INTO employee_time_slots (username, start_time, end_time, sender_chat_id, created_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (target_username, start_time_str, end_time_str, sender_chat_id))
        print(f"DEBUG: Данные для {target_username} успешно добавлены в базу.")
        conn.commit()
        cursor.execute("SELECT * FROM employee_time_slots WHERE username = ?", (target_username,))
        result = cursor.fetchone()
        if result:
            print(f"DEBUG: Данные успешно сохранены: {result}")
        else:
            print(f"DEBUG: Данные для {target_username} не найдены после INSERT.")

        scheduler.add_job(
            schedule_user_check_with_entry,
            CronTrigger(hour=start_time.hour, minute=start_time.minute),
            kwargs={
                "target_username": target_username,
                "start_time": start_time,
                "end_time": end_time,
                "sender_chat_id": sender_chat_id,  
                "bot": bot  
            },
            id=f"check_{target_username}",
            replace_existing=True
        )

        await update.message.reply_text(
            f"Время для @{target_username} установлено:\n"
            f"Начало: {start_time_str}\n"
            f"Конец: {end_time_str}"
        )
        print(f"DEBUG: Планирование задачи: target_username={target_username}, sender_chat_id={sender_chat_id}")
        print(f"Задача для @{target_username} запланирована: {start_time} - {end_time}")

    except Exception as e:
        print(f"Ошибка в set_time_slot: {e}")
        await update.message.reply_text("Произошла ошибка при установке времени.")


async def check_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    try:
        if not context.args:
            
            cursor.execute("""
                SELECT username, start_time, end_time, updated_at
                FROM employee_time_slots
                ORDER BY username
            """)
            time_slots = cursor.fetchall()

            if not time_slots:
                await update.message.reply_text("Нет установленного времени ни для одного сотрудника.")
                return

            response = "Установленное время сотрудников:\n\n"
            for username, start_time, end_time, updated_at in time_slots:
                updated_at_str = updated_at if updated_at else "не обновлялось"
                response += (f"@{username}\n"
                            f"├ Время: {start_time} - {end_time}\n"
                            f"└ Обновлено: {updated_at_str}\n\n")

            await update.message.reply_text(response)

            
        else:
            
            target_username = context.args[0].lstrip("@")
            
            cursor.execute("""
                SELECT username, start_time, end_time, updated_at
                FROM employee_time_slots
                WHERE username = ?
            """, (target_username,))
            
            result = cursor.fetchone()
            
            if result:
                username, start_time, end_time, updated_at = result
                updated_at_str = updated_at if updated_at else "не обновлялось"
                response = (f"Время для @{username}:\n"
                          f"├ Начало: {start_time}\n"
                          f"├ Конец: {end_time}\n"
                          f"└ Обновлено: {updated_at_str}")
                await update.message.reply_text(response)
            else:
                await update.message.reply_text(f"Для сотрудника @{target_username} не установлено время.")

    except Exception as e:
        print(f"Ошибка в check_time: {e}")
        await update.message.reply_text("Произошла ошибка при проверке времени.")


def load_saved_time_slots():
    try:
        cursor.execute("SELECT username, start_time, end_time, sender_chat_id FROM employee_time_slots")
        saved_slots = cursor.fetchall()
        
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(kyiv_tz)
        
        messages = []  

        for username, start_time_str, end_time_str, sender_chat_id in saved_slots:
            start_time = kyiv_tz.localize(datetime.combine(now.date(), datetime.strptime(start_time_str, "%H:%M").time()))
            end_time = kyiv_tz.localize(datetime.combine(now.date(), datetime.strptime(end_time_str, "%H:%M").time()))
            
            if end_time <= start_time:
                end_time += timedelta(days=1)
                
            user_time_slots[username] = {
                "start_time": start_time,
                "end_time": end_time
            }

            scheduler.add_job(
                schedule_user_check_with_entry,
                CronTrigger(hour=start_time.hour, minute=start_time.minute),
                kwargs={
                    "target_username": username,
                    "start_time": start_time,
                    "end_time": end_time,
                    "sender_chat_id": sender_chat_id,  
                    "bot": bot  
                },
                id=f"check_{username}",
                replace_existing=True
            )
            print(f"DEBUG: Задача восстановлена для {username}: {start_time} - {end_time}, sender_chat_id={sender_chat_id}")
            print(f"DEBUG: Загружено из базы: username={username}, start_time={start_time_str}, end_time={end_time_str}, sender_chat_id={sender_chat_id}")

            
            messages.append(
                f"Пользователь @{username}: временной интервал {start_time_str} - {end_time_str} успешно загружен и анализируется."
            )
        
        print(f"Загружено {len(saved_slots)} временных слотов из базы данных")
        
        
        if messages:
            print("\n".join(messages))

    except Exception as e:
        print(f"Ошибка при загрузке временных слотов: {e}")



async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    try:
        if len(context.args) == 1:
            start_date = datetime.strptime(context.args[0], "%d.%m.%Y")
            end_date = start_date + timedelta(days=1)
        elif len(context.args) == 2:
            start_date = datetime.strptime(context.args[0], "%d.%m.%Y")
            end_date = datetime.strptime(context.args[1], "%d.%m.%Y") + timedelta(days=1)
        else:
            await update.message.reply_text(
                "Пожалуйста, укажите дату или период в формате: "
                "/show_logs 13.12.2024 или /show_logs 10.12.2024 13.12.2024"
            )
            return

        if username != user_roles["owner"] and username not in user_roles["head_admins"]:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return

        start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')

        
        cursor.execute("""
            SELECT user_id, username, message_text, file_path, timestamp 
            FROM chat_logs 
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp ASC
        """, (start_date_str, end_date_str))
        logs = cursor.fetchall()

        if not logs:
            await update.message.reply_text("Нет доступных логов за указанный период.")
            return

        
        logs_by_date = {}
        for log in logs:
            user_id, username, message_text, file_path, timestamp = log
            date = timestamp.split()[0]
            if date not in logs_by_date:
                logs_by_date[date] = []
            logs_by_date[date].append((username, message_text, file_path, timestamp))

        
        for date, day_logs in logs_by_date.items():
            response = f"Логи за {date}:\n\n"
            
            for username, message_text, file_path, timestamp in day_logs:
                time = timestamp.split()[1]
                if file_path:
                    try:
                        
                        await update.message.reply_photo(
                            photo=open(file_path, 'rb'),
                            caption=f"@{username} ({time}):\n{message_text}"
                        )
                    except FileNotFoundError:
                        response += f"@{username} ({time}):\n{message_text} [Фото недоступно]\n\n"
                else:
                    response += f"@{username} ({time}):\n{message_text}\n\n"
            
            if response.strip() != f"Логи за {date}:":
                await update.message.reply_text(response)

        
        cursor.execute("""
            SELECT username, entry_number, exit_number, total, entry_time, exit_time
            FROM shift_totals
            WHERE entry_time BETWEEN ? AND ?
            AND exit_number IS NOT NULL
            ORDER BY entry_time ASC
        """, (start_date_str, end_date_str))
        shift_logs = cursor.fetchall()

        if shift_logs:
            response = "\nИтоги смен:\n"
            for shift in shift_logs:
                username, entry_num, exit_num, total, entry_time, exit_time = shift
                response += (f"@{username}: вход {entry_num} ({entry_time}), "
                           f"выход {exit_num} ({exit_time}), итого: {total}\n")
            await update.message.reply_text(response)

    except Exception as e:
        print(f"Ошибка в show_logs: {e}")
        await update.message.reply_text(f"Произошла ошибка: {e}")


async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /set_role <username> <role>. Роли: admin, head_admin.")
        return

    target_username = args[0].lstrip("@")  
    role = args[1].lower()

    
    if role not in ["admin", "head_admin"]:
        await update.message.reply_text("Неверная роль. Доступные роли: admin, head_admin.")
        return

    
    if role == "admin":
        user_roles["admins"][target_username] = {}
        await update.message.reply_text(f"Пользователю @{target_username} назначена роль 'Админ'.")
    elif role == "head_admin":
        
        if username != user_roles["owner"]:
            await update.message.reply_text("Только владелец может назначить роль 'Главный админ'.")
            return
        user_roles["head_admins"].add(target_username)
        await update.message.reply_text(f"Пользователю @{target_username} назначена роль 'Главный админ'.")


async def remove_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    
    if username not in user_roles["head_admins"] and username != user_roles["owner"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Использование: /remove_role <username>. Укажите имя пользователя.")
        return

    target_username = args[0].lstrip("@")  

    
    if target_username in user_roles["admins"]:
        del user_roles["admins"][target_username]
        await update.message.reply_text(f"Роль админа у @{target_username} снята.")
    elif target_username in user_roles["head_admins"]:
        user_roles["head_admins"].remove(target_username)
        await update.message.reply_text(f"Роль главного админа у @{target_username} снята.")
    else:
        await update.message.reply_text(f"Пользователь @{target_username} не имеет роли.")


admin_surveys = {
    
}


available_surveys = ["ML016", "ML046", "ML066", "ML076", "FM09", "ML19", "ML19/3", "ML045"]  


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    if username is None:
        await update.message.reply_text("У вас нет username в Telegram. Пожалуйста, установите его в настройках.")
        return

    
    if username == user_roles["owner"]:
        await update.message.reply_text(f"Привет, @{username}! Вы являетесь владельцем бота.")
        return

    
    if username in user_roles["head_admins"]:
        await update.message.reply_text(f"Привет, @{username}! Владелец назначил вас главным админом.")
        return

    
    if username in user_roles["admins"]:
        await update.message.reply_text(f"Привет, @{username}! Владелец или главный админ назначил вас админом.")
        return

    
    await update.message.reply_text(f"Привет, @{username}! У вас нет роли в этом боте.")


async def manage_surveys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return

    
    buttons = []
    for admin_username in user_roles["admins"]:
        buttons.append([InlineKeyboardButton(f"Админ: @{admin_username}", callback_data=f"select_admin:{admin_username}")])
    for head_admin_username in user_roles["head_admins"]:
        buttons.append([InlineKeyboardButton(f"Главный админ: @{head_admin_username}", callback_data=f"select_admin:{head_admin_username}")])

    if not buttons:
        await update.message.reply_text("Нет доступных админов или главных админов для назначения анкет.")
        return

    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("Выберите админа или главного админа для назначения анкет:", reply_markup=reply_markup)


async def select_surveys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    
    _, admin_username = query.data.split(":")
    context.user_data["selected_admin"] = admin_username  

    
    surveys_for_admin = admin_surveys.get(admin_username, [])

    
    buttons = []
    for survey in available_surveys:
        
        button_label = f"✅ {survey}" if survey in surveys_for_admin else survey
        buttons.append([InlineKeyboardButton(button_label, callback_data=f"assign_survey:{survey}")])

    buttons.append([InlineKeyboardButton("Готово", callback_data="assign_done")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await query.edit_message_text(
        f"Какие анкеты вы желаете выбрать для @{admin_username}? Выберите из списка ниже:",
        reply_markup=reply_markup
    )


async def assign_surveys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if "selected_admin" not in context.user_data:
        await query.edit_message_text("Произошла ошибка. Пожалуйста, начните заново.")
        return

    admin_username = context.user_data["selected_admin"]
    if admin_username not in admin_surveys:
        admin_surveys[admin_username] = []

    if query.data.startswith("assign_survey:"):
        
        _, survey = query.data.split(":")
        if survey not in admin_surveys[admin_username]:
            admin_surveys[admin_username].append(survey)

        
        surveys_for_admin = admin_surveys.get(admin_username, [])

        buttons = []
        for survey in available_surveys:
            
            button_label = f"✅ {survey}" if survey in surveys_for_admin else survey
            buttons.append([InlineKeyboardButton(button_label, callback_data=f"assign_survey:{survey}")])

        buttons.append([InlineKeyboardButton("Готово", callback_data="assign_done")])
        reply_markup = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            f"Анкета {survey} добавлена для @{admin_username}. Вы можете выбрать ещё или нажать 'Готово'.",
            reply_markup=reply_markup
        )

    elif query.data == "assign_done":
        
        surveys = ", ".join(admin_surveys[admin_username]) or "нет анкет"
        await query.edit_message_text(f"Анкеты для @{admin_username} сохранены: {surveys}.")


async def add_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  

    if not context.args:  
        await update.message.reply_text("Пожалуйста, укажите название группы. Например: /add_to_chat buni")
        return

    
    group_name = " ".join(context.args).strip()

    
    pending_groups[username] = group_name
    await update.message.reply_text(
        f"Вы запросили добавление бота в группу: '{group_name}'. "
        "Теперь добавьте бота в эту группу, а затем используйте команду /verify_chat."
    )




async def verify_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username not in pending_groups:
        await update.message.reply_text("Вы не запрашивали добавление в супергруппу.")
        return

    
    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите название группы. Например: /verify_chat ML046")
        return

    
    group_name = " ".join(context.args).strip().lower()
    expected_group_name = pending_groups[username].strip().lower()

    
    print(f"Пользователь: @{username}, Введенное название: '{group_name}', Ожидаемое название: '{expected_group_name}'")

    
    if group_name == expected_group_name:
        await update.message.reply_text("Спасибо, что добавили в группу! В дальнейшем буду анализировать чаты и операторов")
        del pending_groups[username]  
    else:
        await update.message.reply_text("Названия не идентичны. Пожалуйста, перепроверьте.")


async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    try:
        
        if len(context.args) == 1:
            try:
                single_date = datetime.strptime(context.args[0], "%d.%m.%Y")
                start_date = single_date
                end_date = single_date + timedelta(days=1)  
            except ValueError:
                await update.message.reply_text("Неверный формат даты. Используйте: /show_logs 13.12.2024")
                return
        elif len(context.args) == 2:
            
            try:
                start_date = datetime.strptime(context.args[0], "%d.%m.%Y")
                end_date = datetime.strptime(context.args[1], "%d.%m.%Y") + timedelta(days=1)  
            except ValueError:
                await update.message.reply_text("Неверный формат дат. Используйте: /show_logs 10.12.2024 13.12.2024")
                return
        else:
            
            await update.message.reply_text("Пожалуйста, укажите одну дату или период в формате: /show_logs 13.12.2024 или /show_logs 10.12.2024 13.12.2024")
            return

        
        start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')

        
        cursor.execute("""
            SELECT user_id, username, message_text, file_path, timestamp 
            FROM chat_logs 
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
        """, (start_date_str, end_date_str))
        rows = cursor.fetchall()

        if not rows:
            await update.message.reply_text("Нет доступных логов за указанный период.")
            return

        
        for row in rows:
            user_id, username, message_text, file_path, timestamp = row
            log_message = f"@{username} (ID: {user_id}) at {timestamp}:\n{message_text}"

            if file_path:  
                await update.message.reply_photo(photo=open(file_path, 'rb'), caption=log_message)
            else:
                await update.message.reply_text(log_message)
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {e}")


async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    try:
        
        if context.args:
            try:
                num_logs = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Пожалуйста, укажите корректное число.")
                return
        else:
            await update.message.reply_text("Укажите количество логов для удаления, например: /clear_logs 5")
            return
            

        
        cursor.execute("DELETE FROM chat_logs WHERE id IN (SELECT id FROM chat_logs ORDER BY id DESC LIMIT ?)", (num_logs,))
        conn.commit()

        await update.message.reply_text(f"Удалено {num_logs} последних логов.")
        print(f"clear_logs: Deleted {num_logs} logs.")

    except Exception as e:
        print(f"Ошибка в clear_logs: {e}")
        await update.message.reply_text("Произошла ошибка при очистке логов.")

async def del_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        
        username = update.message.from_user.username
        if username != user_roles["owner"] and username not in user_roles["head_admins"]:
            await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
            return

        
        if not context.args:
            await update.message.reply_text(
                "Пожалуйста, укажите пользователя.\n"
                "Пример: /del_time @username"
            )
            return

        target_username = context.args[0].lstrip("@")

        
        cursor.execute("""
            DELETE FROM employee_time_slots
            WHERE username = ?
        """, (target_username,))
        
        
        if cursor.rowcount > 0:
            conn.commit()
            
            if target_username in user_time_slots:
                del user_time_slots[target_username]
            await update.message.reply_text(f"✅ Время для пользователя @{target_username} успешно удалено.")
        else:
            await update.message.reply_text(f"❌ Для пользователя @{target_username} не было установлено время.")

    except Exception as e:
        print(f"Ошибка в del_time: {e}")
        await update.message.reply_text("Произошла ошибка при удалении времени.")


async def help(update, context):
    help_text = (
        "Вот доступные команды:\n"
        "/start - Начать взаимодействие с ботом\n"
        "/set_role - Установить роль пользователю\n"
        "/remove_role - Удалить роль пользователю\n"
        "/manage_surveys - Управлять анкетами\n"
        "/add_to_chat - Добавить бота в супергруппу\n"
        "/verify_chat - Проверить, добавлен ли бот в супергруппу\n"
        "/show_logs - Показать логи\n"
        "/clear_logs - Очистить определенное количество логов\n"
        "/set_time_slot - Установить время входа на смену пользователю\n"
        "/check_time - Проверить установленное время сотрудников\n"
        "/get_chat_id - Определить ID чата и группы\n"
        "/show_balance - Проверить баланс сотрудника\n"
        "/deL_time - Удалить временной промежуток захода для сотрудника\n"
        "/login - Авторизоваться на сайте OnlyMonster\n"
        "/check_stat - Загрузить статистику сотрудников с сайта OnlyMonster\n"
        "/restart_bot - Перезагрузить бота\n"
        "/clear_balance - Очищает баланс сотрудника\n"
    )
    await update.message.reply_text(help_text)

async def notify_on_startup(context: ContextTypes.DEFAULT_TYPE):
    try:
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(kyiv_tz).strftime("%Y-%m-%d %H:%M:%S")
        
        message = f"🤖 Бот успешно запущен!\nВремя сервера: {now}\n\n"
        message += "🕒 Временные промежутки сотрудников:\n"

        for username, slot in user_time_slots.items():
            start_time = slot["start_time"].strftime("%H:%M")
            end_time = slot["end_time"].strftime("%H:%M")
            message += f"@{username}: {start_time} - {end_time}\n"

        await context.bot.send_message(chat_id=7118479382, text=message)

    except Exception as e:
        print(f"Ошибка при отправке уведомления: {e}")



async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    
    username = update.message.from_user.username
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("❌ У вас нет прав для выполнения этой команды.")
        return  
    
    await update.message.reply_text("Бот будет перезапущен...")

    
    time.sleep(2)

    
    os.execv(sys.executable, ['python'] + sys.argv)

def main():
    print("Запуск бота...")
    application = Application.builder().token(TOKEN).build()

    
    load_saved_time_slots()
    print("Временные слоты загружены")

    scheduler.start()

    application.job_queue.run_once(notify_on_startup, when=0)

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("set_role", set_role))
    application.add_handler(CommandHandler("remove_role", remove_role))
    application.add_handler(CommandHandler("manage_surveys", manage_surveys))
    application.add_handler(CommandHandler("add_to_chat", add_to_chat))
    application.add_handler(CommandHandler("verify_chat", verify_chat))
    application.add_handler(CommandHandler("show_logs", show_logs))
    application.add_handler(CommandHandler("clear_logs", clear_logs))
    application.add_handler(CommandHandler("set_time_slot", set_time_slot))
    application.add_handler(CommandHandler("check_time", check_time))
    application.add_handler(CommandHandler("help", help))
    application.add_handler(CommandHandler("get_chat_id", get_chat_id))
    application.add_handler(CommandHandler("show_balance", show_balance))
    application.add_handler(CommandHandler("del_time", del_time))
    application.add_handler(CommandHandler("login", login_command))
    application.add_handler(CommandHandler("check_stat", check_stat_command))
    application.add_handler(CommandHandler("restart_bot", restart_bot))
    application.add_handler(CommandHandler("clear_balance", clear_balance))
    print("Команды зарегистрированы")

    application.add_handler(CallbackQueryHandler(select_surveys, pattern="^select_admin:"))
    application.add_handler(CallbackQueryHandler(assign_surveys, pattern="^assign_survey:|^assign_done$"))
    print("Callback обработчики зарегистрированы")

    application.add_handler(MessageHandler(
        filters.ChatType.SUPERGROUP & 
        filters.TEXT & 
        ~filters.COMMAND,
        monitor_messages
    ), group=1)
    print("Monitor messages handler зарегистрирован")

    application.add_handler(MessageHandler(
        filters.ChatType.SUPERGROUP & 
        ~filters.COMMAND,
        log_messages
    ), group=2)
    print("Log messages handler зарегистрирован")

    print("Бот запущен и готов к работе!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

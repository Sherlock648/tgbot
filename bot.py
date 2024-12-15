# СРАЗУ НАПИШУ: ТАЙМ-ЗОНА УСТАНОВЛЕНА ПОД КИЕВ (НА НЫНЕШНИЙ МОМЕНТ ДЕКАБРЬ 2024 - ЭТО UTC +2, КОГДА В МСК UTC +3 ИЗ-ЗА ПЕРЕВОДА ВРЕМЕНИ, ПОЭТОМУ МЕНЯЙТЕ ПОД СЕБЯ, НАХОДЯ ПО КЛЮЧЕВЫМ СЛОВАМ "Europe/Kyiv" И Т.П.

import sqlite3
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import pytz
from datetime import datetime, timedelta
from telegram.ext import CommandHandler
from telegram.ext import ContextTypes
from config import TOKEN  # Импортируем токен из config.py
import asyncio
from asyncio import Lock

# Глобальная очередь для синхронизации
event_queue = asyncio.Queue()

# Хранилище ролей пользователей
user_roles = {
    "owner": "sherlock_cole",  # Владелец
    "head_admins": {"masonishka"},  # Главные админы
    "admins": {}  # Админы
}

# Хранилище для супергрупп и их проверок
pending_groups = {}

# Хранилище для времени, в который пользователь должен отписывать сообщение
user_time_slots = {}

# Подключение к бд SQLite
conn = sqlite3.connect("chat_logs.db")
cursor = conn.cursor()

# Создание таблицы для хранения логов чата
cursor.execute("""
CREATE TABLE IF NOT EXISTS chat_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    user_id INTEGER,
    username TEXT,
    message_text TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")
conn.commit()

# Функция экранирования символов MarkdownV2
def escape_markdown(text: str) -> str:
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return ''.join(f"\\{char}" if char in escape_chars else char for char in text)

TARGET_THREAD_IDS = [1, 51]  # ID тем в супергруппе
TARGET_CHAT_IDS = [-0987654321, -1234567890]  # ID супергрупп для лога
TARGET_KEYWORDS = [
    "вышла", "вышел", "зашел", "зашёл", "зашла", 
    "Зашла", "Вышла", "Зашел", "Вышел", "Зашёл"
]

# Хранилище для отслеживания сообщений о входе
entry_events_lock = asyncio.Lock()  # Синхронизация для entry_events
entry_events = {}
entry_logs = {}


# Monitor messages
from asyncio import Event
async def monitor_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        print("monitor_messages: Сообщение отсутствует.")
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    username = message.from_user.username.lstrip("@") or "Unknown"  # Убираем '@'

    print(f"Monitor: Получен username = {username}")
    print(f"Monitor: Обработка сообщения от {username} в {datetime.now(pytz.timezone('Europe/Kyiv')).strftime('%H:%M:%S')}")

    if chat_id not in TARGET_CHAT_IDS:
        print(f"Сообщение из нецелевого чата. chat_id: {chat_id}")
        return

    if thread_id not in TARGET_THREAD_IDS:
        print(f"Сообщение из нецелевой темы. thread_id: {thread_id}")
        return

    message_text = (message.text or "").lower().strip()
    if any(keyword.lower() in message_text for keyword in TARGET_KEYWORDS):
        print(f"Monitor: Сообщение '{message_text}' содержит ключевое слово. Обновляем entry_logs.")
        entry_logs[username] = {
            "message": message_text,
            "timestamp": datetime.now(pytz.timezone('Europe/Kyiv')).strftime('%Y-%m-%d %H:%M:%S')
        }

        # Добавляем сигнал в очередь
        await event_queue.put(username)
        print(f"Monitor: Сигнал для {username} отправлен в очередь. Текущее состояние очереди: {event_queue.qsize()}")
    else:
        print(f"Monitor: Сообщение '{message_text}' не содержит ключевого слова.")

# Schedule user check
async def schedule_user_check_with_entry(target_username, start_time, end_time, update, context):
    try:
        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(kyiv_tz)

        target_username = target_username.lstrip("@")  # Убираем '@'
        print(f"Scheduler: target_username = {target_username}")
        print(f"Scheduler: Начало ожидания записи для {target_username} в {datetime.now(pytz.timezone('Europe/Kyiv')).strftime('%H:%M:%S')}")

        if now < start_time:
            wait_time = (start_time - now).total_seconds()
            print(f"Ожидание до начала для {target_username}: {wait_time} секунд.")
            await asyncio.sleep(wait_time)

        now = datetime.now(kyiv_tz)

        if now < end_time:
            wait_time = (end_time - now).total_seconds()
            print(f"Ожидание до конца для {target_username}: {wait_time} секунд.")
            await asyncio.sleep(wait_time)

        print(f"Scheduler: Ожидание записи в entry_logs для {target_username}. Текущее состояние entry_events: {entry_events}")
        print(f"Scheduler: Состояние очереди перед ожиданием: {event_queue.qsize()}")

        # Ожидаем события с циклом
        timeout = 0  # Порог для проверки события
        while True:
            if timeout > 20:  # количество попыток до 20
                print(f"Scheduler: Превышено время ожидания события для {target_username}. Возможно, событие не было установлено вовремя.")
                break

            try:
                username_in_queue = await asyncio.wait_for(event_queue.get(), timeout=2)  # Тайм-аут до 2 секунд
            except asyncio.TimeoutError:
                timeout += 1
                print(f"Scheduler: Тайм-аут ожидания события для {target_username}, попытка {timeout + 1}")
                continue

            print(f"Scheduler: Получен сигнал для {username_in_queue} из очереди.")

            if username_in_queue == target_username:
                print(f"Scheduler: Событие для {target_username} установлено.")
                break

        if target_username in entry_logs:
            log_entry = entry_logs[target_username]
            await context.bot.send_message(
                chat_id=update.message.chat.id,
                text=f"✅ Сотрудник @{target_username} зашёл вовремя.\nСообщение: '{log_entry['message']}' (в {log_entry['timestamp']})"
            )
            entry_logs.pop(target_username, None)
        else:
            await context.bot.send_message(
                chat_id=update.message.chat.id,
                text=f"❌ Сотрудник @{target_username} не зашёл в указанный промежуток времени."
            )

    except Exception as e:
        print(f"Ошибка в schedule_user_check_with_entry для {target_username}: {e}")
        import traceback
        traceback.print_exc()  # Полный стек ошибки

# командОчка
async def set_time_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        username = update.message.from_user.username

        if username != user_roles["owner"] and username not in user_roles["head_admins"]:
            await update.message.reply_text("У вас нет прав для выполнения этой команды.")
            return

        args = context.args
        if len(args) < 3:
            await update.message.reply_text("Использование: /set_time_slot <username> <start_time> <end_time>.\nПример: /set_time_slot @user 07:30 08:30")
            return

        target_username = args[0].lstrip("@")
        start_time_str = args[1]
        end_time_str = args[2]

        kyiv_tz = pytz.timezone('Europe/Kyiv')
        now = datetime.now(kyiv_tz)

        start_time = kyiv_tz.localize(datetime.combine(now.date(), datetime.strptime(start_time_str, "%H:%M").time()))
        end_time = kyiv_tz.localize(datetime.combine(now.date(), datetime.strptime(end_time_str, "%H:%M").time()))

        if end_time <= start_time:
            end_time += timedelta(days=1)

        user_time_slots[target_username] = {"start_time": start_time, "end_time": end_time}
        await update.message.reply_text(f"Время для @{target_username} установлено с {start_time.strftime('%H:%M')} до {end_time.strftime('%H:%M')}.")

        # Запускаем проверку
        print(f"Создание задачи для пользователя @{target_username}.")
        task = asyncio.create_task(schedule_user_check_with_entry(target_username, start_time, end_time, update, context))
        print(f"Задача для @{target_username} запущена: {task}")
    except Exception as e:
        print(f"Ошибка в set_time_slot: {e}")



# командОчка для проверки времени
async def check_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    args = context.args

    if len(args) < 1:
        await update.message.reply_text("Использование: /check_time <username>\nПример: /check_time @user")
        return

    target_username = args[0].lstrip("@")

    # Проверка, есть ли в системе время для этого пользователя
    if target_username not in user_time_slots:
        await update.message.reply_text(f"Для пользователя @{target_username} не установлено время.")
        return

    # Получаем данные о времени для пользователя
    time_slot = user_time_slots[target_username]
    start_time = time_slot["start_time"]
    end_time = time_slot["end_time"]

    # Проверяем текущее время
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    current_time = datetime.now(kyiv_tz)

    if start_time <= current_time <= end_time:
        await update.message.reply_text(f"✅ @{target_username} зашёл вовремя с {start_time.strftime('%H:%M')} до {end_time.strftime('%H:%M')}.")
    else:
        await update.message.reply_text(f"❌ @{target_username} не зашёл вовремя. Ожидаемый промежуток времени: {start_time.strftime('%H:%M')} - {end_time.strftime('%H:%M')}.")

async def log_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    if not message:
        print("log_messages: Сообщение отсутствует.")
        return

    chat_id = message.chat.id
    thread_id = message.message_thread_id
    username = message.from_user.username or "Unknown"
    user_id = message.from_user.id

    # Проверяем, что сообщение из целевой супергруппы и темы
    if chat_id not in TARGET_CHAT_IDS:
        print(f"log_messages: Сообщение из нецелевого чата. chat_id: {chat_id}")
        return

    if thread_id not in TARGET_THREAD_IDS:
        print(f"log_messages: Сообщение из нецелевой темы. thread_id: {thread_id}")
        return

    # Проверяем текст сообщения
    message_text = (message.text or "").lower().strip()
    if any(keyword.lower() in message_text for keyword in TARGET_KEYWORDS):
        print(f"✅ log_messages: @{username} отправил корректное сообщение: '{message_text}'")
    else:
        print(f"❌ log_messages: Ключевые слова отсутствуют в сообщении: '{message_text}'")

    # Получаем текущую дату и время по Киеву
    kyiv_tz = pytz.timezone('Europe/Kyiv')
    current_time = datetime.now(kyiv_tz)
    timestamp = current_time.strftime('%Y-%m-%d %H:%M:%S')  # Форматируем время

    # Проверка времени
    if username in user_time_slots:
        start_time = user_time_slots[username]["start_time"]
        end_time = user_time_slots[username]["end_time"]

        # Сравниваем время (проверьте, что это дата или время)
        if not (start_time.time() <= current_time.time() <= end_time.time()):
            await context.bot.send_message(
                chat_id=user_roles["owner"],  # Вы можете отправить админу или главному админу
                text=f"❗ @{username} отправил сообщение вне установленного времени (с {start_time.strftime('%H:%M')} до {end_time.strftime('%H:%M')})."
            )
            return

    # Прочая логика обработки сообщений
    print(f"Логирование сообщения пользователя @{username}...")

    # Формируем ссылку на сообщение
    if message.chat.username:  # Для публичного чата
        chat_identifier = message.chat.username
    else:  # Для приватного чата
        chat_identifier = str(chat_id)

    message_link = f"https://t.me/{chat_identifier}/{message.message_id}"

    file_path = None

    # Обработка фотографий
    if message.photo:
        photo = message.photo[-1]  # Берём фото с наибольшим разрешением
        file_id = photo.file_id
        file_path = f"{file_id}.jpg"

        # Сохраняем фото локально
        file = await context.bot.get_file(file_id)
        await file.download_to_drive(file_path)

    # Сохраняем данные в бд
    cursor.execute(""" 
    INSERT INTO chat_logs (chat_id, user_id, username, message_text, file_path, timestamp, message_id)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (chat_id, user_id, username, message_text, file_path, timestamp, message.message_id))
    conn.commit()

    print(f"log_messages: Logged message from @{username} with text '{message_text}' and photo '{file_path}'.")



async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Извлекаем дату из команды (например, 10.12.2024 - 13.12.2024)
        if len(context.args) == 1:
            start_date = context.args[0]  # В формате 'dd.mm.yyyy'
            end_date = start_date  # Если указана только одна дата, она становится и начальной, и конечной
        elif len(context.args) == 2:
            start_date, end_date = context.args  # В формате 'dd.mm.yyyy'

        # Преобразуем строки в объекты datetime
        start_date = datetime.strptime(start_date, "%d.%m.%Y")
        end_date = datetime.strptime(end_date, "%d.%m.%Y")

        # Форматируем дату в строку для использования в запросах
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        # Выполняем SQL-запрос для извлечения логов по диапазону дат
        cursor.execute("""
            SELECT user_id, username, message_text, file_path, timestamp 
            FROM chat_logs 
            WHERE timestamp BETWEEN ? AND ?
            ORDER BY timestamp DESC
        """, (start_str, end_str))

        rows = cursor.fetchall()

        if not rows:
            await update.message.reply_text("Нет доступных логов.")
            return

        # Группируем логи по датам
        logs_by_date = {}
        for row in rows:
            user_id, username, message_text, file_path, timestamp = row
            date = timestamp.split(" ")[0]  # Получаем только дату (yyyy-mm-dd)
            if date not in logs_by_date:
                logs_by_date[date] = []
            log_message = f"@{username} (ID: {user_id}) at {timestamp}:\n{message_text}"
            logs_by_date[date].append(log_message)

        # Отправляем сообщения по дням, объединяя логи за один день в одно сообщение
        for date, logs in logs_by_date.items():
            day_message = f"Логи за {date}:\n\n" + "\n\n".join(logs)
            await update.message.reply_text(day_message)

    except Exception as e:
        await update.message.reply_text(f"Ошибка: {e}")

# командОчка для назначение роли
async def set_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    # Проверяем, имеет ли пользователь права для выполнения команды
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Получаем аргументы команды
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("Использование: /set_role <username> <role>. Роли: admin, head_admin.")
        return

    target_username = args[0].lstrip("@")  # Убираем "@" перед юзером пользователя
    role = args[1].lower()

    # Проверяем корректность роли
    if role not in ["admin", "head_admin"]:
        await update.message.reply_text("Неверная роль. Доступные роли: admin, head_admin.")
        return

    # Назначаем роль
    if role == "admin":
        user_roles["admins"][target_username] = {}
        await update.message.reply_text(f"Пользователю @{target_username} назначена роль 'Админ'.")
    elif role == "head_admin":
        # Только владелец может назначить главного админа
        if username != user_roles["owner"]:
            await update.message.reply_text("Только владелец может назначить роль 'Главный админ'.")
            return
        user_roles["head_admins"].add(target_username)
        await update.message.reply_text(f"Пользователю @{target_username} назначена роль 'Главный админ'.")

# Функция для удаления роли
async def remove_role(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    # Проверяем, кто выполняет команду
    if username not in user_roles["head_admins"] and username != user_roles["owner"]:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Получаем аргументы команды
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("Использование: /remove_role <username>. Укажите имя пользователя.")
        return

    target_username = args[0].lstrip("@")  # Убираем "@" перед username

    # Снимаем роль
    if target_username in user_roles["admins"]:
        del user_roles["admins"][target_username]
        await update.message.reply_text(f"Роль админа у @{target_username} снята.")
    elif target_username in user_roles["head_admins"]:
        user_roles["head_admins"].remove(target_username)
        await update.message.reply_text(f"Роль главного админа у @{target_username} снята.")
    else:
        await update.message.reply_text(f"Пользователь @{target_username} не имеет роли.")

# Хранилище анкет, привязанных к админам
admin_surveys = {
    # Пример: "admin_username": ["ML016", "ML046"]
}

# Список доступных анкет
available_surveys = ["ML016", "ML046", "ML066", "ML076", "FM09", "ML19", "ML19/3", "ML045"]  # Можно дополнить

# Функция start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    if username is None:
        await update.message.reply_text("У вас нет username в Telegram. Пожалуйста, установите его в настройках.")
        return

    # Проверка на владельца
    if username == user_roles["owner"]:
        await update.message.reply_text(f"Привет, @{username}! Вы являетесь владельцем бота.")
        return

    # Проверка на главного админа
    if username in user_roles["head_admins"]:
        await update.message.reply_text(f"Привет, @{username}! Владелец назначил вас главным админом.")
        return

    # Проверка на админа
    if username in user_roles["admins"]:
        await update.message.reply_text(f"Привет, @{username}! Владелец или главный админ назначил вас админом.")
        return

    # Сообщение для всех остальных
    await update.message.reply_text(f"Привет, @{username}! У вас нет роли в этом боте.")

# Функция для выдачи списка текущих админов/главных админов и добавления анкет
async def manage_surveys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username

    # Проверяем права пользователя
    if username != user_roles["owner"] and username not in user_roles["head_admins"]:
        await update.message.reply_text("У вас нет прав для выполнения этой команды.")
        return

    # Формируем список админов и главных админов
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

# Callback для выбора анкет
async def select_surveys(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    # Извлекаем юзер выбранного администратора
    _, admin_username = query.data.split(":")
    context.user_data["selected_admin"] = admin_username  # Сохраняем выбранного админа в контексте

    # Получаем список анкет для выбранного администратора
    surveys_for_admin = admin_surveys.get(admin_username, [])

    # Формируем кнопки для выбора анкет
    buttons = []
    for survey in available_surveys:
        # Если анкета уже выдана этому админу, добавляем галочку
        button_label = f"✅ {survey}" if survey in surveys_for_admin else survey
        buttons.append([InlineKeyboardButton(button_label, callback_data=f"assign_survey:{survey}")])

    buttons.append([InlineKeyboardButton("Готово", callback_data="assign_done")])
    reply_markup = InlineKeyboardMarkup(buttons)

    await query.edit_message_text(
        f"Какие анкеты вы желаете выбрать для @{admin_username}? Выберите из списка ниже:",
        reply_markup=reply_markup
    )

# Callback для назначения анкет
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
        # Назначаем анкету
        _, survey = query.data.split(":")
        if survey not in admin_surveys[admin_username]:
            admin_surveys[admin_username].append(survey)

        # Повторный рендеринг кнопок
        surveys_for_admin = admin_surveys.get(admin_username, [])

        buttons = []
        for survey in available_surveys:
            # Если анкета уже выдана этому админу, добавляем галочку
            button_label = f"✅ {survey}" if survey in surveys_for_admin else survey
            buttons.append([InlineKeyboardButton(button_label, callback_data=f"assign_survey:{survey}")])

        buttons.append([InlineKeyboardButton("Готово", callback_data="assign_done")])
        reply_markup = InlineKeyboardMarkup(buttons)

        await query.edit_message_text(
            f"Анкета {survey} добавлена для @{admin_username}. Вы можете выбрать ещё или нажать 'Готово'.",
            reply_markup=reply_markup
        )

    elif query.data == "assign_done":
        # Завершаем выбор анкет
        surveys = ", ".join(admin_surveys[admin_username]) or "нет анкет"
        await query.edit_message_text(f"Анкеты для @{admin_username} сохранены: {surveys}.")

# Команда для добавления в супергруппу
async def add_to_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if not context.args:  # Проверка, переданы ли аргументы
        await update.message.reply_text("Пожалуйста, укажите название группы. Например: /add_to_chat buni")
        return

    # Получаем название группы из аргументов
    group_name = " ".join(context.args).strip()

    # Сохраняем название группы для пользователя
    pending_groups[username] = group_name
    await update.message.reply_text(
        f"Вы запросили добавление бота в группу: '{group_name}'. "
        "Теперь добавьте бота в эту группу, а затем используйте команду /verify_chat."
    )


# Команда для проверки правильности добавления в супергруппу
async def verify_chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = update.message.from_user.username
    if username not in pending_groups:
        await update.message.reply_text("Вы не запрашивали добавление в супергруппу.")
        return

    # Проверяем аргументы команды
    if not context.args:
        await update.message.reply_text("Пожалуйста, укажите название группы. Например: /verify_chat buni")
        return

    # Получаем название группы и приводим к единому формату
    group_name = " ".join(context.args).strip().lower()
    expected_group_name = pending_groups[username].strip().lower()

    # Отладочные сообщения
    print(f"Пользователь: @{username}, Введенное название: '{group_name}', Ожидаемое название: '{expected_group_name}'")

    # Сравнение названий
    if group_name == expected_group_name:
        await update.message.reply_text("Спасибо, что добавили в группу! В дальнейшем буду анализировать чаты и операторов")
        del pending_groups[username]  # Удаляем запись о запросе
    else:
        await update.message.reply_text("Названия не идентичны. Пожалуйста, перепроверьте.")

# Команда для отображения логов
async def show_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Проверяем количество аргументов
        if len(context.args) == 1:
            # Один аргумент — берем логи за эту дату
            try:
                single_date = datetime.strptime(context.args[0], "%d.%m.%Y")
                start_date = single_date
                end_date = single_date + timedelta(days=1)  # Конец дня
            except ValueError:
                await update.message.reply_text("Неверный формат даты. Используйте: /show_logs 13.12.2024")
                return
        elif len(context.args) == 2:
            # Два аргумента — диапазон дат
            try:
                start_date = datetime.strptime(context.args[0], "%d.%m.%Y")
                end_date = datetime.strptime(context.args[1], "%d.%m.%Y") + timedelta(days=1)  # Конец дня
            except ValueError:
                await update.message.reply_text("Неверный формат дат. Используйте: /show_logs 10.12.2024 13.12.2024")
                return
        else:
            # Неверное количество аргументов
            await update.message.reply_text("Пожалуйста, укажите одну дату или период в формате: /show_logs 13.12.2024 или /show_logs 10.12.2024 13.12.2024")
            return

        # Преобразуем даты в строковый формат
        start_date_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_date_str = end_date.strftime('%Y-%m-%d %H:%M:%S')

        # Запрос к базе данных с фильтрацией по дате
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

        # Формируем и отправляем логи
        for row in rows:
            user_id, username, message_text, file_path, timestamp = row
            log_message = f"@{username} (ID: {user_id}) at {timestamp}:\n{message_text}"

            if file_path:  # Если есть фотография
                await update.message.reply_photo(photo=open(file_path, 'rb'), caption=log_message)
            else:
                await update.message.reply_text(log_message)
    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {e}")

# Команда для очистки логов
async def clear_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        # Получаем аргумент команды (количество логов для удаления)
        if context.args:
            try:
                num_logs = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Пожалуйста, укажите корректное число.")
                return
        else:
            await update.message.reply_text("Укажите количество логов для удаления, например: /clear_logs 5")
            return

        # Удаляем последние N логов
        cursor.execute("DELETE FROM chat_logs WHERE id IN (SELECT id FROM chat_logs ORDER BY id DESC LIMIT ?)", (num_logs,))
        conn.commit()

        await update.message.reply_text(f"Удалено {num_logs} последних логов.")
        print(f"clear_logs: Deleted {num_logs} logs.")

    except Exception as e:
        print(f"Ошибка в clear_logs: {e}")
        await update.message.reply_text("Произошла ошибка при очистке логов.")



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
        "Для получения помощи используйте команду /help"
    )
    await update.message.reply_text(help_text)

def main(): 
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start)) # Я не ебу, она нихуя не делает. Просто покажет, что вы админ/владелец/гл. админ (не факт, не помню)
    application.add_handler(CommandHandler("set_role", set_role))  # Команда для выдачи ролей
    application.add_handler(CommandHandler("remove_role", remove_role))  # Команда для снятия ролей
    application.add_handler(CommandHandler("manage_surveys", manage_surveys))  # Команда для назначения анкет
    application.add_handler(CallbackQueryHandler(select_surveys, pattern="^select_admin:"))
    application.add_handler(CallbackQueryHandler(assign_surveys, pattern="^assign_survey:|^assign_done$"))
    application.add_handler(CommandHandler("add_to_chat", add_to_chat))  # Команда для добавления в супергруппу
    application.add_handler(CommandHandler("verify_chat", verify_chat))  # Команда для проверки добавления в супергруппу
    application.add_handler(CommandHandler("show_logs", show_logs))  # Команда для вывода логов
    application.add_handler(CommandHandler("clear_logs", clear_logs)) # Команда для очистки логов
    application.add_handler(CommandHandler("set_time_slot", set_time_slot)) # Установить время входа на смену пользователю
    application.add_handler(CommandHandler("check_time", check_time)) # Проверить все входы пользователя на смену
    application.add_handler(CommandHandler("help", help))  # Помощница 007

    application.add_handler(MessageHandler(filters.ALL, log_messages))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, monitor_messages))

    application.run_polling()

if __name__ == "__main__":
    main()

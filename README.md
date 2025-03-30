First (1) - Russian
Second (2) - English

Russian:
# Telegram Bot для Администраторов

Этот бот предназначен для администраторов компании для автоматизации задач, таких как проверка сотрудников, учет рабочего времени, хранение логов и взаимодействие с сайтом компании.

#Основные функции:
- **Проверка сотрудников**: Бот может заходить на сайт компании, вводить необходимые данные и отправлять ответ пользователю в виде файла.
- **Учёт времени входа и выхода сотрудников**: Бот позволяет назначать время входа/выхода для каждого сотрудника. Если сотрудник не зашел на смену, бот уведомит администратора. При успешном входе на смену бот также отправит уведомление админу.
- **Подсчёт баланса сотрудников**: Возможность подсчета баланса всех сотрудников.
- **Логи работы бота**: Все действия, происходящие в супергруппе Telegram, записываются в базу данных и могут быть выведены по запросу.
- **Хранение данных для входа на сайт компании**: Логины и пароли для входа на сайт компании сохраняются в базе данных.

#Требования:
- Python 3.13.0
- Библиотеки:
  - `sqlite3` (для работы с базой данных)
  - `python-telegram-bot` (для взаимодействия с API Telegram)

#Настройка проекта:
1. Склонируйте репозиторий:
   ```bash
   git clone https://github.com/yourusername/yourrepo.git
   cd yourrepo
   
2. Установите необходимые зависимости: Если у вас нет необходимых библиотек, установите их с помощью pip:
   pip install -r requirements.txt
3. Создайте нового бота в Telegram через BotFather и получите токен.
4. В config.py впишите свой TOKEN бота.
   TOKEN = 'ЗАМЕНИТЕ_НА_ВАШ_ТОКЕН'
5. Запустите проект:

В командной строке:

1. Перейдите в папку с проектом:
   ```bash
   cd путь:папка
2. Перейдите в нужную подпапку:
   cd папка
3. Запустите бота:
  python bot.py

## Команды:
- **/start** — Начать взаимодействие с ботом
- **/set_role** — Установить роль пользователю
- **/remove_role** — Удалить роль пользователю
- **/manage_surveys** — Управлять анкетами
- **/add_to_chat** — Добавить бота в супергруппу
- **/verify_chat** — Проверить, добавлен ли бот в супергруппу
- **/show_logs** — Показать логи
- **/clear_logs** — Очистить определенное количество логов
- **/set_time_slot** — Установить время входа на смену пользователю
- **/check_time** — Проверить установленное время сотрудников
- **/get_chat_id** — Определить ID чата и группы
- **/show_balance** — Проверить баланс сотрудника
- **/deL_time** — Удалить временной промежуток захода для сотрудника
- **/login** — Авторизоваться на сайте OnlyMonster
- **/check_stat** — Загрузить статистику сотрудников с сайта OnlyMonster
- **/restart_bot** — Перезагрузить бота
- **/clear_balance** — Очищает баланс сотрудника


Работа с базой данных:
База данных sqlite хранит информацию о сотрудниках, их сменах, балансе и логах. После запуска бота база данных будет автоматически создана, если её нет.

Логи:
Все действия в супергруппе Telegram, связанные с ботом, записываются в базу данных. Вы можете просматривать эти логи через команду /show_logs.

Примечания:
Для хранения конфиденциальной информации, такой как логины и пароли, используется база данных SQLite.
Бот автоматически уведомляет администратора о проблемах с сотрудниками (например, если они не вошли на смену).


Этот README будет полезен пользователю для быстрого старта с твоим ботом и понятия, что он может ожидать от этого проекта.

__________________________________________________________________________________________________________________________________________________________________________________________________________________________________________________________________________________________
English:
# Telegram Bot for Administrators

This bot is designed for company administrators to automate tasks such as employee verification, time tracking, log storage, and interaction with the company website.

#Basic Functions:
- **Employee Verification**: The bot can log into the company website, enter the required data and send a response to the user in the form of a file.
- **Employee log-in and log-out time**: The bot allows you to assign in/out time for each employee. If an employee has not logged in for a shift, the bot will notify the administrator. The bot will also send a notification to the admin if the shift is successfully logged in.
- **Employee balance calculation**: Ability to calculate the balance of all employees.
- **Bot Activity Logs**: All activities that take place in the Telegram supergroup are recorded in the database and can be displayed on request.
- **Storage of data for logging in to the company's website**: Logins and passwords for logging into the company website are stored in a database.

#Requirements:
- Python 3.13.0
- Libraries:
  - `sqlite3` (for working with the database)
  - `python-telegram-bot` (for interaction with Telegram API)

#Project Setup:
1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/yourrepo.git
   cd yourrepo
   
2. Install the required dependencies: If you don't have the required libraries, install them using pip:
   pip install -r requirements.txt
3. Create a new bot in Telegram via BotFather and get the token.
4. In config.py, write your bot's TOKEN.
   TOKEN = 'REPLACE_WITH_YOUR_TOKEN'
5. Start the project:

At the command line:

1. Navigate to the project folder:
   ```bash
   cd path:folder
2. Navigate to the desired subfolder:
   cd folder
3. Run the bot:
  python bot.py


## Commands:
- **/start** - Start interaction with the bot
- **/set_role** - Set a role for a user
- **/remove_role** - Remove a role for a user
- **/manage_surveys** - Manage profiles
- **/add_to_chat** - Add bot to supergroup
- **/verify_chat** - Check if a bot has been added to a supergroup
- **/show_logs** - Show logs
- **/clear_logs** - Clear a certain amount of logs
- **/set_time_slot** - Set the login time for a user's shift
- **/check_time** - Check the set time of employees
- **/get_chat_id** - Determine chat ID and group ID
- **/show_balance** - Check employee balance
- **/deL_time** - Delete the time period for an employee to log in
- **/login** - Authorize on the OnlyMonster site
- **/check_stat** - Download employee statistics from the OnlyMonster website
- **/restart_bot** - Reload the bot
- **/clear_balance** - Clears employee balance

Database operation:
The sqlite database stores information about employees, their shifts, balance and logs. After starting the bot, the database will be automatically created if it doesn't exist.

Logs:
All activities in the Telegram supergroup related to the bot are logged in the database. You can view these logs via the /show_logs command.

Notes:
A SQLite database is used to store sensitive information such as logins and passwords.
The bot automatically notifies the administrator if there are problems with employees (for example, if they are not logged in for a shift).


This README will be useful for the user to get a quick start with your bot and an idea of what they can expect from this project.

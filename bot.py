import telebot
from telebot import types
from math import floor
from datetime import datetime, timedelta
import time
import random
import re
import config
import threading
import crypto_pay
import requests
import sqlite3
import db as db_module

bot = telebot.TeleBot(config.BOT_TOKEN)

treasury_lock = threading.Lock()
active_treasury_admins = {}

with sqlite3.connect('database.db') as conn:
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS requests (
        ID INTEGER PRIMARY KEY,
        LAST_REQUEST TIMESTAMP,
        STATUS TEXT DEFAULT 'pending'
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        ID INTEGER PRIMARY KEY,
        BALANCE REAL DEFAULT 0,
        REG_DATE TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS numbers (
        NUMBER TEXT PRIMARY KEY,
        ID_OWNER INTEGER,
        TAKE_DATE TEXT,
        SHUTDOWN_DATE TEXT,
        MODERATOR_ID INTEGER,
        CONFIRMED_BY_MODERATOR_ID INTEGER,
        VERIFICATION_CODE TEXT,
        STATUS TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS personal (
        ID INTEGER PRIMARY KEY,
        TYPE TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdraws (
        ID INTEGER,
        AMOUNT REAL,
        DATE TEXT,
        STATUS TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        PRICE REAL  -- Цена за номер
    )''')
    
    cursor.execute("PRAGMA table_info(settings)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'HOLD_TIME' not in columns:
        cursor.execute('ALTER TABLE settings ADD COLUMN HOLD_TIME INTEGER')
    
    cursor.execute('SELECT COUNT(*) FROM settings')
    count = cursor.fetchone()[0]
    
    if count == 0:
        cursor.execute('INSERT INTO settings (PRICE, HOLD_TIME) VALUES (?, ?)', (2.0, 5))
    else:
        cursor.execute('UPDATE settings SET HOLD_TIME = ? WHERE HOLD_TIME IS NULL', (5,))
    
    conn.commit()

class Database:
    def get_db(self):
        return sqlite3.connect('database.db')

    def is_moderator(self, user_id):
        with self.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM personal WHERE ID = ? AND TYPE = ?', (user_id, 'moder'))
            return cursor.fetchone() is not None

    def update_balance(self, user_id, amount):
        with self.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, user_id))
            conn.commit()

db = Database()

@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # Добавляем определение current_date
    
    # Проверяем, находится ли пользователь в группе
    chat_type = bot.get_chat(message.chat.id).type
    is_group = chat_type in ["group", "supergroup"]
    
    # Проверяем, заблокирован ли пользователь
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BLOCKED FROM requests WHERE ID = ?', (user_id,))
        user = cursor.fetchone()
        if user and user[0] == 1:
            bot.send_message(message.chat.id, "🚫 Вас заблокировали в боте!")
            return
    
    # Если пользователь — админ, сразу даём доступ
    if user_id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT OR REPLACE INTO requests (ID, LAST_REQUEST, STATUS, BLOCKED, CAN_SUBMIT_NUMBERS) VALUES (?, ?, ?, ?, ?)',
                          (user_id, current_date, 'approved', 0, 1))
            conn.commit()
        if is_group:
            # Проверяем, является ли пользователь модератором
            is_moderator = db.is_moderator(user_id)
            markup = types.InlineKeyboardMarkup()
            if is_moderator:
                markup.add(
                    types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
                    types.InlineKeyboardButton("📋 Мои номера", callback_data="moderator_numbers")
                )
                bot.send_message(
                    message.chat.id,
                    "Заявки",  # Убираем "Выберите действие:" и ставим просто "Заявки"
                    reply_markup=markup
                )
            else:
                # Для админов, которые не модераторы, показываем стандартное меню
                markup.row(
                    types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
                    types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
                )
                markup.add(types.InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel"))
                bot.send_message(
                    message.chat.id,
                    f"<b>📢 Добро пожаловать в {config.SERVICE_NAME}</b>\n\n"
                    f"<b>⏳ График работы:</b> <code>{config.WORK_TIME}</code>\n\n"
                    "<b>💼 Как это работает?</b>\n"
                    "• <i>Вы продаёте номер</i> – <b>мы предоставляем стабильные выплаты.</b>\n"
                    f"• <i>Моментальные выплаты</i> – <b>после 5 минут работы.</b>\n\n"
                    "<b>💰 Тарифы на сдачу номеров:</b>\n"
                    f"▪️ <code>2.0$</code> за номер (холд 5 минут)\n"
                    f"<b>📍 Почему выбирают {config.SERVICE_NAME} ?</b>\n"
                    "✅ <i>Прозрачные условия сотрудничества</i>\n"
                    "✅ <i>Выгодные тарифы и моментальные выплаты</i>\n"
                    "✅ <i>Оперативная поддержка 24/7</i>\n\n"
                    "<b>🔹 Начните зарабатывать прямо сейчас!</b>",
                    reply_markup=markup,
                    parse_mode='HTML'
                )
        else:
            # В личном чате вызываем show_main_menu
            show_main_menu(message)
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT LAST_REQUEST, STATUS FROM requests WHERE ID = ?', (user_id,))
        request = cursor.fetchone()
        if request and request[1] == 'approved':
            if is_group:
                # Проверяем, является ли пользователь модератором
                is_moderator = db.is_moderator(user_id)
                markup = types.InlineKeyboardMarkup()
                if is_moderator:
                    markup.add(
                        types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
                        types.InlineKeyboardButton("📋 Мои номера", callback_data="moderator_numbers")
                    )
                    bot.send_message(
                        message.chat.id,
                        "Заявки",  # Убираем "Выберите действие:" и ставим просто "Заявки"
                        reply_markup=markup
                    )
                else:
                    # Для обычных пользователей в группе показываем стандартное меню
                    markup.row(
                        types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
                        types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
                    )
                    bot.send_message(
                        message.chat.id,
                        f"<b>📢 Добро пожаловать в {config.SERVICE_NAME}</b>\n\n"
                        f"<b>⏳ График работы:</b> <code>{config.WORK_TIME}</code>\n\n"
                        "<b>💼 Как это работает?</b>\n"
                        "• <i>Вы продаёте номер</i> – <b>мы предоставляем стабильные выплаты.</b>\n"
                        f"• <i>Моментальные выплаты</i> – <b>после 5 минут работы.</b>\n\n"
                        "<b>💰 Тарифы на сдачу номеров:</b>\n"
                        f"▪️ <code>2.0$</code> за номер (холд 5 минут)\n"
                        f"<b>📍 Почему выбирают {config.SERVICE_NAME} ?</b>\n"
                        "✅ <i>Прозрачные условия сотрудничества</i>\n"
                        "✅ <i>Выгодные тарифы и моментальные выплаты</i>\n"
                        "✅ <i>Оперативная поддержка 24/7</i>\n\n"
                        "<b>🔹 Начните зарабатывать прямо сейчас!</b>",
                        reply_markup=markup,
                        parse_mode='HTML'
                    )
            else:
                # В личном чате вызываем show_main_menu
                show_main_menu(message)
            return
        if request:
            last_request_time = datetime.strptime(request[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_request_time < timedelta(minutes=15):
                time_left = 15 - ((datetime.now() - last_request_time).seconds // 60)
                bot.send_message(message.chat.id, 
                                f"⏳ Ожидайте подтверждения. Вы сможете отправить новый запрос через {time_left} минут.")
                return
        cursor.execute('INSERT OR REPLACE INTO requests (ID, LAST_REQUEST, STATUS, BLOCKED, CAN_SUBMIT_NUMBERS) VALUES (?, ?, ?, ?, ?)',
                      (user_id, current_date, 'pending', 0, 1))
        conn.commit()
        bot.send_message(message.chat.id, 
                        "👋 Здравствуйте! Ожидайте, пока вас впустят в бота.")
                         
@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_user_"))
def approve_user_callback(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS FROM requests WHERE ID = ?', (user_id,))
        request = cursor.fetchone()
        
        if request:
            cursor.execute('UPDATE requests SET STATUS = "approved" WHERE ID = ?', (user_id,))
        else:
            cursor.execute('INSERT INTO requests (ID, LAST_REQUEST, STATUS) VALUES (?, ?, ?)',
                          (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'approved'))
        conn.commit()
        
        try:
            bot.send_message(user_id, "✅ Вас впустили в бота! Напишите /start")
            text = f"✅ Пользователь {user_id} одобрен"
        except:
            text = f"✅ Пользователь {user_id} одобрен, но уведомление не доставлено"
        
        # Добавляем кнопку "Вернуться в заявки на вступление"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Вернуться в заявки на вступление", callback_data="pending_requests"))
        
        bot.edit_message_text(text,
                             call.message.chat.id,
                             call.message.message_id,
                             parse_mode='HTML',
                             reply_markup=markup)
        

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_user_"))
def reject_user_callback(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('UPDATE requests SET STATUS = "rejected", LAST_REQUEST = ? WHERE ID = ?',
                      (current_date, user_id))
        conn.commit()
        
        try:
            bot.send_message(user_id, "❌ Вам отказано в доступе. Вы сможете отправить новый запрос через 15 минут.")
            text = f"❌ Пользователь {user_id} отклонён"
        except:
            text = f"❌ Пользователь {user_id} отклонён, но уведомление не доставлено"
        
        # Добавляем кнопку "Вернуться в заявки на вступление"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📝 Вернуться в заявки на вступление", callback_data="pending_requests"))
        
        bot.edit_message_text(text,
                             call.message.chat.id,
                             call.message.message_id,
                             parse_mode='HTML',
                             reply_markup=markup)
                                      
def show_main_menu(message):
    user_id = message.from_user.id
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Проверяем, есть ли пользователь в базе
        cursor.execute('SELECT REG_DATE FROM users WHERE ID = ?', (user_id,))
        existing_user = cursor.fetchone()
        
        if not existing_user:
            # Логируем только если пользователь действительно новый
            print(f"[+] Новый пользователь зарегистрировался:")
            print(f"🆔 ID: {user_id}")
            print(f"👤 Имя: {message.from_user.first_name} {message.from_user.last_name or ''}")
            print(f"🔗 Username: @{message.from_user.username or 'нет'}")
            print(f"📅 Дата регистрации: {current_date}")
            print("-" * 40)
        
        cursor.execute('INSERT OR IGNORE INTO users (ID, BALANCE, REG_DATE) VALUES (?, ?, ?)',
                      (user_id, 0, current_date))
        
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
        
        conn.commit()

    is_admin = user_id in config.ADMINS_ID
    is_moderator = db.is_moderator(user_id)

    if is_moderator and not is_admin:
        welcome_text = "📝 <b>Заявки</b>"
    else:
        welcome_text = (
            f"<b>📢 Добро пожаловать в {config.SERVICE_NAME}</b>\n\n"
            f"<b>⏳ График работы:</b> <code>{config.WORK_TIME}</code>\n\n"
            "<b>💼 Как это работает?</b>\n"
            "• <i>Вы продаёте номер</i> – <b>мы предоставляем стабильные выплаты.</b>\n"
            f"• <i>Моментальные выплаты</i> – <b>после {hold_time} минут работы.</b>\n\n"
            "<b>💰 Тарифы на сдачу номеров:</b>\n"
            f"▪️ <code>{price}$</code> за номер (холд {hold_time} минут)\n"
            f"<b>📍 Почему выбирают {config.SERVICE_NAME} ?</b>\n"
            "✅ <i>Прозрачные условия сотрудничества</i>\n"
            "✅ <i>Выгодные тарифы и моментальные выплаты</i>\n"
            "✅ <i>Оперативная поддержка 24/7</i>\n\n"
            "<b>🔹 Начните зарабатывать прямо сейчас!</b>"
        )
    
    markup = types.InlineKeyboardMarkup()
    
    if not is_moderator or is_admin:
        markup.row(
            types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
            types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
        )
    
    if is_admin:
        markup.add(types.InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel"))
    
    if is_moderator:
        markup.add(
            types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
            types.InlineKeyboardButton("📋 Мои номера", callback_data="moderator_numbers")
        )

    if hasattr(message, 'chat'):
         bot.send_message(message.chat.id, welcome_text, parse_mode='HTML', reply_markup=markup)
    else:
        bot.edit_message_text(welcome_text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=markup)


#===========================================================================
#======================ВЕРНУТЬСЯ=====================НАЗАД==================
#===========================================================================

@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    
    # Проверяем, является ли пользователь модератором или админом
    is_admin = user_id in config.ADMINS_ID
    is_moderator = db.is_moderator(user_id)
    
    # Проверяем, находится ли пользователь в группе
    chat_type = bot.get_chat(chat_id).type
    is_group = chat_type in ["group", "supergroup"]
    
    # Получаем настройки
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
    
    # Формируем текст сообщения
    if is_moderator:  # Условие для всех модераторов (включая тех, кто админ)
        welcome_text = "Заявки"  # Просто "Заявки" без форматирования
    else:
        welcome_text = (
            f"<b>📢 Добро пожаловать в {config.SERVICE_NAME}</b>\n\n"
            f"<b>⏳ График работы:</b> <code>{config.WORK_TIME}</code>\n\n"
            "<b>💼 Как это работает?</b>\n"
            "• <i>Вы продаёте номер</i> – <b>мы предоставляем стабильные выплаты.</b>\n"
            f"• <i>Моментальные выплаты</i> – <b>после {hold_time} минут работы.</b>\n\n"
            "<b>💰 Тарифы на сдачу номеров:</b>\n"
            f"▪️ <code>{price}$</code> за номер (холд {hold_time} минут)\n"
            f"<b>📍 Почему выбирают {config.SERVICE_NAME} ?</b>\n"
            "✅ <i>Прозрачные условия сотрудничества</i>\n"
            "✅ <i>Выгодные тарифы и моментальные выплаты</i>\n"
            "✅ <i>Оперативная поддержка 24/7</i>\n\n"
            "<b>🔹 Начните зарабатывать прямо сейчас!</b>"
        )
    
    # Формируем клавиатуру
    markup = types.InlineKeyboardMarkup()
    
    if is_group:
        if is_moderator:
            # Панель для модераторов в группе
            markup.add(
                types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
                types.InlineKeyboardButton("📋 Мои номера", callback_data="moderator_numbers")
            )
        else:
            # Стандартное меню для обычных пользователей в группе
            markup.row(
                types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
                types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
            )
            if is_admin:
                markup.add(types.InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel"))
    else:
        # Личный чат: текущее поведение
        if not is_moderator or is_admin:
            markup.row(
                types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
                types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
            )
        
        if is_admin:
            markup.add(types.InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel"))
        
        if is_moderator:
            markup.add(
                types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
                types.InlineKeyboardButton("📋 Мои номера", callback_data="moderator_numbers")
            )
    
    bot.edit_message_text(
        welcome_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML' if not is_moderator else None,  # Для модераторов убираем parse_mode
        reply_markup=markup
    )

#===========================================================================
#======================ПРОФИЛЬ=====================ПРОФИЛЬ==================
#===========================================================================





@bot.callback_query_handler(func=lambda call: call.data == "profile")
def show_profile(call):
    user_id = call.from_user.id
    check_balance_and_fix(user_id)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE ID = ?', (user_id,))
        user = cursor.fetchone()
        
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
        
        if user:
            cursor.execute('SELECT COUNT(*) FROM numbers WHERE ID_OWNER = ? AND SHUTDOWN_DATE = "0"', (user_id,))
            active_numbers = cursor.fetchone()[0]
            
            roles = []
            if user_id in config.ADMINS_ID:
                roles.append("👑 Администратор")
            if db.is_moderator(user_id):
                roles.append("🛡 Модератор")
            if not roles:
                roles.append("👤 Пользователь")
            
            profile_text = (f"👤 <b>Ваш профиль:</b>\n\n"
                          f"🆔ID ссылкой: <code>https://t.me/@id{user_id}</code>\n"
                          f"🆔 ID: <code>{user[0]}</code>\n"
                          f"💰 Баланс: {user[1]} $\n"
                          f"📱 Активных номеров: {active_numbers}\n"
                          f"🎭 Роль: {' | '.join(roles)}\n"
                          f"📅 Дата регистрации: {user[2]}\n"
                          f"💵 Текущая ставка: {price}$ за номер\n"
                          f"⏱ Время холда: {hold_time} минут")

            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("💳 Вывести", callback_data="withdraw"),
                types.InlineKeyboardButton("📱 Мои номера", callback_data="my_numbers")
            )
            
            if user_id in config.ADMINS_ID:
                cursor.execute('SELECT COUNT(*) FROM users')
                total_users = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM numbers WHERE SHUTDOWN_DATE = "0"')
                active_total = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM numbers')
                total_numbers = cursor.fetchone()[0]
                
                profile_text += (f"\n\n📊 <b>Статистика бота:</b>\n"
                               f"👥 Всего пользователей: {total_users}\n"
                               f"📱 Активных номеров: {active_total}\n"
                               f"📊 Всего номеров: {total_numbers}")
            
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            bot.send_message(call.message.chat.id, profile_text, reply_markup=markup, parse_mode='HTML')















@bot.callback_query_handler(func=lambda call: call.data == "withdraw")
def start_withdrawal_request(call):
    user_id = call.from_user.id
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BALANCE FROM users WHERE ID = ?', (user_id,))
        balance = cursor.fetchone()[0]
        
        if balance > 0:
            msg = bot.edit_message_text(f"💰 Ваш баланс: {balance}$\n💳 Введите сумму для вывода или нажмите 'Да' для вывода всего баланса:",
                                      call.message.chat.id,
                                      call.message.message_id)
            bot.register_next_step_handler(msg, handle_withdrawal_request, balance)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("👤 Связаться с менеджером", url=f"https://t.me/{config.PAYOUT_MANAGER}"))
            markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text(f"❌ На вашем балансе недостаточно средств для вывода.\n\n"
                               f"Если вы считаете, что произошла ошибка или у вас есть вопросы по выводу, "
                               f"свяжитесь с ответственным за выплаты: @{config.PAYOUT_MANAGER}",
                                call.message.chat.id,
                                call.message.message_id,
                                reply_markup=markup)

def handle_withdrawal_request(message, amount):
    user_id = message.from_user.id
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BALANCE FROM users WHERE ID = ?', (user_id,))
        user = cursor.fetchone()

        if not user or user[0] <= 0:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ У вас нет средств на балансе для вывода.", reply_markup=markup)
            return
        withdrawal_amount = user[0]
        
        try:
            if message.text != "Да" and message.text != "да":
                try:
                    requested_amount = float(message.text)
                    if requested_amount <= 0:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
                        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                        bot.send_message(message.chat.id, "❌ Введите положительное число.", reply_markup=markup)
                        return
                        
                    if requested_amount > withdrawal_amount:
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
                        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                        bot.send_message(message.chat.id, 
                                      f"❌ Запрошенная сумма ({requested_amount}$) превышает ваш баланс ({withdrawal_amount}$).", 
                                      reply_markup=markup)
                        return
                        
                    withdrawal_amount = requested_amount
                except ValueError:
                    pass
            
            processing_message = bot.send_message(message.chat.id, 
                                        f"⏳ <b>Обработка запроса на вывод {withdrawal_amount}$...</b>\n\n"
                                        f"Пожалуйста, подождите, мы формируем ваш чек.",
                                        parse_mode='HTML')
            
            treasury_balance = db_module.get_treasury_balance()
            
            if withdrawal_amount > treasury_balance:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                bot.edit_message_text(
                    f"❌ <b>В данный момент вывод недоступен</b>\n\n"
                    f"Пожалуйста, попробуйте позже или обратитесь к администратору.",
                    message.chat.id, 
                    processing_message.message_id,
                    parse_mode='HTML',
                    reply_markup=markup
                )
                
                admin_message = (
                    f"⚠️ <b>Попытка вывода при недостаточных средствах</b>\n\n"
                    f"👤 ID: {user_id}\n"
                    f"💵 Запрошенная сумма: {withdrawal_amount}$\n"
                    f"💰 Баланс казны: {treasury_balance}$\n\n"
                    f"⛔️ Вывод был заблокирован из-за нехватки средств в казне."
                )
                for admin_id in config.ADMINS_ID:
                    try:
                        bot.send_message(admin_id, admin_message, parse_mode='HTML')
                    except:
                        continue
                return
            
            auto_input_status = db_module.get_auto_input_status()
            
            if not auto_input_status:
                cursor.execute('INSERT INTO withdraws (ID, AMOUNT, DATE, STATUS) VALUES (?, ?, ?, ?)', 
                             (user_id, withdrawal_amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "pending"))
                conn.commit()
                new_balance = user[0] - withdrawal_amount
                cursor.execute('UPDATE users SET BALANCE = ? WHERE ID = ?', (new_balance, user_id))
                conn.commit()
                treasury_new_balance = db_module.update_treasury_balance(-withdrawal_amount)
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                
                bot.edit_message_text(
                    f"✅ <b>Запрос на вывод средств принят!</b>\n\n"
                    f"Сумма: <code>{withdrawal_amount}$</code>\n"
                    f"Новый баланс: <code>{new_balance}$</code>\n\n"
                    f"⚠️ Авто-вывод отключен. Средства будут выведены вручную администратором.",
                    message.chat.id, 
                    processing_message.message_id,
                    parse_mode='HTML',
                    reply_markup=markup
                )
                
                admin_message = (
                    f"💰 <b>Новая заявка на выплату</b>\n\n"
                    f"👤 ID: {user_id}\n"
                    f"💵 Сумма: {withdrawal_amount}$\n"
                    f"💰 Баланс казны: {treasury_new_balance}$\n\n"
                    f"📱 Вечная ссылка ANDROID: tg://openmessage?user_id={user_id}\n"
                    f"📱 Вечная ссылка IOS: https://t.me/@id{user_id}"
                )
                admin_markup = types.InlineKeyboardMarkup()
                admin_markup.add(
                    types.InlineKeyboardButton("✅ Отправить чек", callback_data=f"send_check_{user_id}_{withdrawal_amount}"),
                    types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_withdraw_{user_id}_{withdrawal_amount}")
                )
                for admin_id in config.ADMINS_ID:
                    try:
                        bot.send_message(admin_id, admin_message, reply_markup=admin_markup, parse_mode='HTML')
                    except:
                        continue
                return
            
            try:
                crypto_api = crypto_pay.CryptoPay()
                cheque_result = crypto_api.create_check(
                    amount=withdrawal_amount,
                    asset="USDT",
                    description=f"Выплата для пользователя {user_id}"
                )
                
                if cheque_result.get("ok", False):
                    cheque = cheque_result.get("result", {})
                    cheque_link = cheque.get("bot_check_url", "")
                    
                    if cheque_link:
                        new_balance = user[0] - withdrawal_amount
                        cursor.execute('UPDATE users SET BALANCE = ? WHERE ID = ?', (new_balance, user_id))
                        conn.commit()
                        treasury_new_balance = db_module.update_treasury_balance(-withdrawal_amount)
                        db_module.log_treasury_operation("Автоматический вывод", withdrawal_amount, treasury_new_balance)
                        
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("💳 Активировать чек", url=cheque_link))
                        markup.add(types.InlineKeyboardButton("👤 Профиль", callback_data="profile"))
                        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                        
                        bot.edit_message_text(
                            f"✅ <b>Ваш вывод средств обработан!</b>\n\n"
                            f"Сумма: <code>{withdrawal_amount}$</code>\n"
                            f"Новый баланс: <code>{new_balance}$</code>\n\n"
                            f"Нажмите на кнопку ниже, чтобы активировать чек:",
                            message.chat.id, 
                            processing_message.message_id,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        
                        log_entry = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] | Автоматический вывод | Пользователь {user_id} | Сумма {withdrawal_amount}$"
                        with open("withdrawals_log.txt", "a", encoding="utf-8") as log_file:
                            log_file.write(log_entry + "\n")
                        
                        admin_message = (
                            f"💰 <b>Автоматический вывод средств</b>\n\n"
                            f"👤 ID: {user_id}\n"
                            f"💵 Сумма: {withdrawal_amount}$\n"
                            f"📅 Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"💰 Баланс казны: {treasury_new_balance}$\n\n"
                            f"✅ Чек успешно отправлен пользователю"
                        )
                        
                        for admin_id in config.ADMINS_ID:
                            try:
                                bot.send_message(admin_id, admin_message, parse_mode='HTML')
                            except:
                                continue
                        
                        return
                
                raise Exception("Не удалось создать чек автоматически")
                
            except Exception as e:
                print(f"Error creating automatic check: {e}")
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                
                bot.edit_message_text(
                    f"⚠️ <b>Автоматический вывод временно недоступен</b>\n\n"
                    f"Пожалуйста, попробуйте позже.",
                    message.chat.id, 
                    processing_message.message_id,
                    parse_mode='HTML',
                    reply_markup=markup
                )
                
                admin_message = (
                    f"❌ <b>Ошибка автоматического вывода</b>\n\n"
                    f"👤 ID: {user_id}\n"
                    f"💵 Сумма: {withdrawal_amount}$\n"
                    f"⚠️ Ошибка: {str(e)}\n\n"
                    f"Пользователю отправлено сообщение о недоступности вывода."
                )
                for admin_id in config.ADMINS_ID:
                    try:
                        bot.send_message(admin_id, admin_message, parse_mode='HTML')
                    except:
                        continue
            
        except Exception as e:
            print(f"Error processing withdrawal: {e}")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, 
                           "❌ Произошла ошибка при обработке запроса. Пожалуйста, попробуйте позже.", 
                           reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("send_check_"))
def request_check_link(call):
    if call.from_user.id in config.ADMINS_ID:
        try:
            _, _, user_id, amount = call.data.split("_")
            amount = float(amount)
            crypto_api = crypto_pay.CryptoPay()
            check_result = crypto_api.create_check(
                amount=amount,
                asset="USDT",
                description=f"Выплата для пользователя {user_id}"
            )
            
            if check_result.get("ok", False):
                check = check_result.get("result", {})
                check_link = check.get("bot_check_url", "")
                
                if check_link:
                    process_check_link_success(call, user_id, amount, check_link)
                    return
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✏️ Ввести ссылку вручную", callback_data=f"manual_check_{user_id}_{amount}"))
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
            bot.edit_message_text(
                f"❌ Не удалось автоматически создать чек для пользователя {user_id} на сумму {amount}$.\n\n"
                f"Возможные причины:\n"
                f"1. Недостаточно средств в CryptoBot\n"
                f"2. Проблемы с API CryptoBot\n"
                f"3. Неверный токен API\n\n"
                f"Что вы хотите сделать?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error creating check: {e}")
            _, _, user_id, amount = call.data.split("_")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✏️ Ввести ссылку вручную", callback_data=f"manual_check_{user_id}_{amount}"))
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
            bot.edit_message_text(
                f"❌ Произошла ошибка при создании чека: {str(e)}\n\nЧто вы хотите сделать?",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )


@bot.callback_query_handler(func=lambda call: call.data.startswith("manual_check_"))
def manual_check_request(call):
    if call.from_user.id in config.ADMINS_ID:
        _, _, user_id, amount = call.data.split("_")
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        msg = bot.edit_message_text(
            f"📤 Введите ссылку на чек для пользователя {user_id} на сумму {amount}$:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_check_link, user_id, amount)

def process_check_link_success(call, user_id, amount, check_link):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM withdraws WHERE ID = ? AND AMOUNT = ?', (int(user_id), float(amount)))
        conn.commit()
    
    markup_admin = types.InlineKeyboardMarkup()
    markup_admin.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup_admin.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(
        f"✅ Чек на сумму {amount}$ успешно создан и отправлен пользователю {user_id}",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup_admin
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("💳 Активировать чек", url=check_link))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    try:
        bot.send_message(int(user_id),
                       f"✅ Ваша выплата {amount}$ готова!\n💳 Нажмите кнопку ниже для активации чека",
                       reply_markup=markup)
    except Exception as e:
        print(f"Error sending message to user {user_id}: {e}")

def process_check_link(message, user_id, amount):
    if message.from_user.id in config.ADMINS_ID:
        check_link = message.text.strip()
        
        if not check_link.startswith("https://") or "t.me/" not in check_link:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔄 Попробовать снова", callback_data=f"manual_check_{user_id}_{amount}"))
            markup.add(types.InlineKeyboardButton("🔙 Админ-панель", callback_data="admin_panel"))
            bot.send_message(message.chat.id, 
                           "❌ Неверный формат ссылки на чек. Пожалуйста, убедитесь, что вы скопировали полную ссылку.",
                           reply_markup=markup)
            return
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM withdraws WHERE ID = ? AND AMOUNT = ?', (int(user_id), float(amount)))
            conn.commit()
        
        markup_admin = types.InlineKeyboardMarkup()
        markup_admin.add(types.InlineKeyboardButton("🔙 Админ-панель", callback_data="admin_panel"))
        markup_admin.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id,
                       f"✅ Чек на сумму {amount}$ успешно отправлен пользователю {user_id}",
                       reply_markup=markup_admin)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Активировать чек", url=check_link))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.send_message(int(user_id),
                           f"✅ Ваша выплата {amount}$ готова!\n💳 Нажмите кнопку ниже для активации чека",
                           reply_markup=markup)
        except Exception as e:
            print(f"Error sending message to user {user_id}: {e}")


@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_withdraw_"))
def reject_withdraw(call):
    if call.from_user.id in config.ADMINS_ID:
        _, _, user_id, amount = call.data.split("_")
        amount = float(amount)
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, int(user_id)))
            cursor.execute('DELETE FROM withdraws WHERE ID = ? AND AMOUNT = ?', (int(user_id), amount))
            conn.commit()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Попробовать снова", callback_data="withdraw"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.send_message(int(user_id),
                           f"❌ Ваша заявка на вывод {amount}$ отклонена\n💰 Средства возвращены на баланс",
                           reply_markup=markup)
        except:
            pass
        
        markup_admin = types.InlineKeyboardMarkup()
        markup_admin.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup_admin.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("✅ Выплата отклонена, средства возвращены",
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup_admin)


#===========================================================================
#=======================КАЗНА====================КАЗНА======================
#===========================================================================

@bot.callback_query_handler(func=lambda call: call.data == "treasury")
def show_treasury(call):
    if call.from_user.id in config.dostup:
        
        balance = db_module.get_treasury_balance()
        auto_input_status = db_module.get_auto_input_status()
        
        treasury_text = f"💰 <b>Привет, это казна!</b>\n\nВ ней лежит: <code>{balance}</code> USDT"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📤 Вывести", callback_data="treasury_withdraw"))
        markup.add(types.InlineKeyboardButton("📥 Пополнить", callback_data="treasury_deposit"))
        auto_input_text = "🔴 Включить авто-ввод" if not auto_input_status else "🟢 Выключить авто-ввод"
        markup.add(types.InlineKeyboardButton(auto_input_text, callback_data="treasury_toggle_auto"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(treasury_text,
                             call.message.chat.id,
                             call.message.message_id,
                             parse_mode='HTML',
                             reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "treasury_withdraw")
def treasury_withdraw_request(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id

        balance = db_module.get_treasury_balance()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        msg = bot.edit_message_text(f"📤 <b>Вывод средств из казны</b>\n\nТекущий баланс: <code>{balance}</code> USDT\n\nВведите сумму для вывода:",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode='HTML',
                                  reply_markup=markup)
        
        bot.register_next_step_handler(msg, process_treasury_withdraw)

def process_treasury_withdraw(message):
    if message.from_user.id in config.ADMINS_ID:
        admin_id = message.from_user.id
        

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        try:
            amount = float(message.text)
            
            if amount <= 0:
                bot.send_message(message.chat.id, "❌ <b>Ошибка!</b> Введите корректную сумму (больше нуля).", 
                                parse_mode='HTML', reply_markup=markup)
                return
            
            with treasury_lock:
                current_balance = db_module.get_treasury_balance()
                if amount > current_balance:
                    bot.send_message(message.chat.id, 
                                    f"❌ <b>Недостаточно средств в казне!</b>\nТекущий баланс: <code>{current_balance}</code> USDT", 
                                    parse_mode='HTML', reply_markup=markup)
                    return
                
                try:
                    crypto_api = crypto_pay.CryptoPay()
                    balance_result = crypto_api.get_balance()
                    crypto_balance = 0
                    
                    if balance_result.get("ok", False):
                        for currency in balance_result.get("result", []):
                            if currency.get("currency_code") == "USDT":
                                crypto_balance = float(currency.get("available", "0"))
                                break
                    
                    if crypto_balance >= amount:
                        check_result = crypto_api.create_check(
                            amount=amount,
                            asset="USDT",
                            description=f"Вывод из казны от {admin_id}"
                        )
                        
                        if check_result.get("ok", False):
                            check = check_result.get("result", {})
                            check_link = check.get("bot_check_url", "")
                            
                            if check_link:
                                new_balance = db_module.update_treasury_balance(-amount)
                                
                                db_module.log_treasury_operation("Автовывод через чек", amount, new_balance)
                                
                                markup = types.InlineKeyboardMarkup()
                                markup.add(types.InlineKeyboardButton("💸 Активировать чек", url=check_link))
                                markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                                
                                bot.send_message(message.chat.id, 
                                              f"✅ <b>Средства успешно выведены с помощью чека!</b>\n\n"
                                              f"Сумма: <code>{amount}</code> USDT\n"
                                              f"Остаток в казне: <code>{new_balance}</code> USDT\n\n"
                                              f"Для получения средств активируйте чек по кнопке ниже:", 
                                              parse_mode='HTML', reply_markup=markup)
                                return
                        else:
                            error_details = check_result.get("error_details", "Неизвестная ошибка")
                            raise Exception(f"Ошибка при создании чека: {error_details}")
                    else:
                        raise Exception(f"Недостаточно средств на балансе CryptoBot! Баланс: {crypto_balance} USDT, требуется: {amount} USDT.")
                
                except Exception as e:
                    bot.send_message(message.chat.id, 
                                   f"⚠️ <b>Ошибка при автовыводе средств:</b> {str(e)}", 
                                   parse_mode='HTML', reply_markup=markup)
        
        except ValueError:
            bot.send_message(message.chat.id, "❌ <b>Ошибка!</b> Введите числовое значение.", 
                            parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "treasury_deposit")
def treasury_deposit_request(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id
        

        balance = db_module.get_treasury_balance()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        msg = bot.edit_message_text(f"📥 <b>Пополнение казны</b>\n\nТекущий баланс: <code>{balance}</code> USDT\n\nВведите сумму для пополнения:",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  parse_mode='HTML',
                                  reply_markup=markup)
        
        bot.register_next_step_handler(msg, process_treasury_deposit)


def process_treasury_deposit(message):
    if message.from_user.id in config.ADMINS_ID:
        admin_id = message.from_user.id

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        try:
            amount = float(message.text)
            
            if amount <= 0:
                bot.send_message(message.chat.id, "❌ <b>Ошибка!</b> Введите корректную сумму (больше нуля).", 
                                parse_mode='HTML', reply_markup=markup)
                return
            
            markup_crypto = types.InlineKeyboardMarkup()
            markup_crypto.add(types.InlineKeyboardButton("💳 Пополнить через CryptoBot", callback_data=f"treasury_deposit_crypto_{amount}"))
            markup_crypto.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
            markup_crypto.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
            markup_crypto.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            
            bot.send_message(message.chat.id, 
                           f"💰 <b>Способ пополнения казны на {amount}$</b>\n\n"
                           f"Выберите способ пополнения:", 
                           parse_mode='HTML', reply_markup=markup_crypto)
                        
        except ValueError:
            bot.send_message(message.chat.id, "❌ <b>Ошибка!</b> Введите числовое значение.", 
                            parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("treasury_deposit_crypto_"))
def treasury_deposit_crypto(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id

        amount = float(call.data.split("_")[-1])
        
        try:
            crypto_api = crypto_pay.CryptoPay()
            
            amount_with_fee = calculate_amount_to_send(amount)
            
            invoice_result = crypto_api.create_invoice(
                amount=amount_with_fee,
                asset="USDT",
                description=f"Пополнение казны от {admin_id}",
                hidden_message="Спасибо за пополнение казны!",
                paid_btn_name="callback",
                paid_btn_url=f"https://t.me/{bot.get_me().username}",
                expires_in=300
            )
            
            if invoice_result.get("ok", False):
                invoice = invoice_result.get("result", {})
                invoice_link = invoice.get("pay_url", "")
                invoice_id = invoice.get("invoice_id")
                
                if invoice_link and invoice_id:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💸 Оплатить инвойс", url=invoice_link))
                    markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                    
                    message = bot.edit_message_text(
                        f"💰 <b>Инвойс на пополнение казны создан</b>\n\n"
                        f"Сумма: <code>{amount}</code> USDT\n\n"
                        f"1. Нажмите на кнопку 'Оплатить инвойс'\n"
                        f"2. Оплатите созданный инвойс\n\n"
                        f"⚠️ <i>Инвойс действует 5 минут</i>\n\n"
                        f"⏳ <b>Ожидание оплаты...</b>",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='HTML',
                        reply_markup=markup
                    )
                    
                    check_payment_thread = threading.Thread(
                        target=check_invoice_payment, 
                        args=(invoice_id, amount, admin_id, call.message.chat.id, call.message.message_id)
                    )
                    check_payment_thread.daemon = True
                    check_payment_thread.start()
                    return
            
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
            markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            
            error_message = invoice_result.get("error", {}).get("message", "Неизвестная ошибка")
            bot.edit_message_text(
                f"❌ <b>Ошибка при создании инвойса</b>\n\n"
                f"Не удалось создать инвойс через CryptoBot.\n"
                f"Ошибка: {error_message}\n"
                f"Попробуйте пополнить казну вручную.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error creating invoice for treasury deposit: {e}")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
            markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            
            bot.edit_message_text(
                f"❌ <b>Ошибка при работе с CryptoBot</b>\n\n"
                f"Произошла ошибка: {str(e)}\n"
                f"Попробуйте пополнить казну вручную.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=markup
            )

def check_invoice_payment(invoice_id, amount, admin_id, chat_id, message_id):
    crypto_api = crypto_pay.CryptoPay()
    start_time = datetime.now()
    timeout = timedelta(minutes=5)  # Время ожидания 5 минут
    check_interval = 5  # Проверяем каждые 5 секунд
    check_counter = 0
    
    try:
        while datetime.now() - start_time < timeout:
            print(f"Checking invoice {invoice_id} (attempt {check_counter + 1})...")
            invoices_result = crypto_api.get_invoices(invoice_ids=[invoice_id])
            print(f"Invoice API response: {invoices_result}")
            
            if invoices_result.get("ok", False):
                invoices = invoices_result.get("result", {}).get("items", [])
                
                if not invoices:
                    print(f"No invoices found for ID {invoice_id}")
                    time.sleep(check_interval)
                    check_counter += 1
                    continue
                
                status = invoices[0].get("status", "")
                print(f"Invoice {invoice_id} status: {status}")
                
                # Если инвойс оплачен
                if status in ["paid", "completed"]:  # Учитываем возможные статусы
                    print(f"Invoice {invoice_id} paid successfully!")
                    try:
                        # Обновляем баланс казны
                        new_balance = db_module.update_treasury_balance(amount)
                        print(f"Updated treasury balance: {new_balance}")
                        db_module.log_treasury_operation("Пополнение через Crypto Pay", amount, new_balance)
                        print(f"Logged treasury operation: amount={amount}, new_balance={new_balance}")
                    except Exception as db_error:
                        print(f"Error updating treasury balance or logging operation: {db_error}")
                        # Если не удалось обновить баланс, всё равно продолжаем, чтобы сообщить пользователю
                        new_balance = "не удалось обновить"
                    
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                    
                    try:
                        bot.edit_message_text(
                            f"✅ <b>Казна успешно пополнена!</b>\n\n"
                            f"Сумма: <code>{amount}</code> USDT\n"
                            f"Текущий баланс: <code>{new_balance}</code> USDT",
                            chat_id,
                            message_id,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        print(f"Payment confirmation message updated for invoice {invoice_id}")
                    except Exception as e:
                        print(f"Error updating payment confirmation message: {e}")
                        # Если не удалось обновить сообщение, отправляем новое
                        bot.send_message(
                            chat_id,
                            f"✅ <b>Казна успешно пополнена!</b>\n\n"
                            f"Сумма: <code>{amount}</code> USDT\n"
                            f"Текущий баланс: <code>{new_balance}</code> USDT",
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        print(f"Sent new payment confirmation message for invoice {invoice_id}")
                    return
                
                # Если инвойс просрочен
                elif status == "expired":
                    print(f"Invoice {invoice_id} expired.")
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔄 Создать новый инвойс", callback_data=f"treasury_deposit_crypto_{amount}"))
                    markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
                    markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                    
                    try:
                        bot.edit_message_text(
                            f"⏱ <b>Время ожидания оплаты истекло</b>\n\n"
                            f"Инвойс на сумму {amount} USDT не был оплачен в течение 5 минут.\n"
                            f"Вы можете создать новый инвойс или пополнить казну вручную.",
                            chat_id,
                            message_id,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                    except Exception as e:
                        print(f"Error updating expired invoice message: {e}")
                        bot.send_message(
                            chat_id,
                            f"⏱ <b>Время ожидания оплаты истекло</b>\n\n"
                            f"Инвойс на сумму {amount} USDT не был оплачен в течение 5 минут.\n"
                            f"Вы можете создать новый инвойс или пополнить казну вручную.",
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                    return
                
                # Обновляем сообщение каждые 5 проверок (примерно каждые 25 секунд)
                check_counter += 1
                if check_counter % 5 == 0:
                    elapsed = datetime.now() - start_time
                    remaining_seconds = int(timeout.total_seconds() - elapsed.total_seconds())
                    minutes = remaining_seconds // 60
                    seconds = remaining_seconds % 60
                    
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("💸 Оплатить инвойс", url=invoices[0].get("pay_url", "")))
                    markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                    
                    try:
                        bot.edit_message_text(
                            f"💰 <b>Инвойс на пополнение казны создан</b>\n\n"
                            f"Сумма: <code>{amount}</code> USDT\n\n"
                            f"1. Нажмите на кнопку 'Оплатить инвойс'\n"
                            f"2. Оплатите созданный инвойс\n\n"
                            f"⏱ <b>Оставшееся время:</b> {minutes}:{seconds:02d}\n"
                            f"⏳ <b>Ожидание оплаты...</b>",
                            chat_id,
                            message_id,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                        print(f"Waiting message updated: {minutes}:{seconds:02d} remaining")
                    except Exception as e:
                        print(f"Error updating waiting message: {e}")
            
            else:
                print(f"API request failed: {invoices_result}")
            
            time.sleep(check_interval)
        
        # Если время истекло и оплата не подтверждена
        print(f"Invoice {invoice_id} not paid after timeout.")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Создать новый инвойс", callback_data=f"treasury_deposit_crypto_{amount}"))
        markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        
        try:
            bot.edit_message_text(
                f"⏱ <b>Время ожидания оплаты истекло</b>\n\n"
                f"Инвойс на сумму {amount} USDT не был оплачен в течение 5 минут.\n"
                f"Вы можете создать новый инвойс или пополнить казну вручную.",
                chat_id,
                message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error updating final timeout message: {e}")
            bot.send_message(
                chat_id,
                f"⏱ <b>Время ожидания оплаты истекло</b>\n\n"
                f"Инвойс на сумму {amount} USDT не был оплачен в течение 5 минут.\n"
                f"Вы можете создать новый инвойс или пополнить казну вручную.",
                parse_mode='HTML',
                reply_markup=markup
            )
        
    except Exception as e:
        print(f"Error in check_invoice_payment thread: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        try:
            bot.edit_message_text(
                f"❌ <b>Ошибка при проверке оплаты</b>\n\n"
                f"Проacjęла ошибка: {str(e)}\n"
                f"Пожалуйста, пополните казну вручную, если вы уже произвели оплату.",
                chat_id,
                message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        except Exception as edit_error:
            print(f"Error sending error message: {edit_error}")
            bot.send_message(
                chat_id,
                f"❌ <b>Ошибка при проверке оплаты</b>\n\n"
                f"Произошла ошибка: {str(e)}\n"
                f"Пожалуйста, пополните казну вручную, если вы уже произвели оплату.",
                parse_mode='HTML',
                reply_markup=markup
            )
            

@bot.callback_query_handler(func=lambda call: call.data.startswith("treasury_deposit_manual_"))
def treasury_deposit_manual(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id
        

        amount = float(call.data.split("_")[-1])
        
        with treasury_lock:
            new_balance = db_module.update_treasury_balance(amount)
            
            db_module.log_treasury_operation("Пополнение вручную", amount, new_balance)
        
        amount_with_fee = calculate_amount_to_send(amount)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        bot.edit_message_text(
            f"✅ <b>Казна успешно пополнена!</b>\n\n"
            f"Сумма: <code>{amount}</code> USDT\n"
            f"Текущий баланс: <code>{new_balance}</code> USDT",
            call.message.chat.id,
            call.message.message_id,
            parse_mode='HTML',
            reply_markup=markup
        )

@bot.callback_query_handler(func=lambda call: call.data == "treasury_toggle_auto")
def treasury_toggle_auto_input(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id
        
        new_status = db_module.toggle_auto_input()
        
        balance = db_module.get_treasury_balance()
        
        status_text = "включен" if new_status else "выключен"
        operation = f"Авто-ввод {status_text}"
        db_module.log_treasury_operation(operation, 0, balance)
        
        status_emoji = "🟢" if new_status else "🔴"
        auto_message = f"{status_emoji} <b>Авто-ввод {status_text}!</b>\n"
        if new_status:
            auto_message += "Средства будут автоматически поступать в казну."
        else:
            auto_message += "Средства больше не будут автоматически поступать в казну."
        
        treasury_text = f"💰 <b>Привет, это казна!</b>\n\nВ ней лежит: <code>{balance}</code> USDT\n\n{auto_message}"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📤 Вывести", callback_data="treasury_withdraw"))
        markup.add(types.InlineKeyboardButton("📥 Пополнить", callback_data="treasury_deposit"))
        
        auto_input_text = "🔴 Включить авто-ввод" if not new_status else "🟢 Выключить авто-ввод"
        markup.add(types.InlineKeyboardButton(auto_input_text, callback_data="treasury_toggle_auto"))
        
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        bot.edit_message_text(treasury_text,
                             call.message.chat.id,
                             call.message.message_id,
                             parse_mode='HTML',
                             reply_markup=markup)
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("treasury_withdraw_all_"))
def treasury_withdraw_all(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id

        amount = float(call.data.split("_")[-1])
        
        if amount <= 0:
            bot.answer_callback_query(call.id, "⚠️ Баланс казны пуст. Нечего выводить.", show_alert=True)
            return
        
        with treasury_lock:
            operation_success = False
            
            try:
                crypto_api = crypto_pay.CryptoPay()
                
                balance_result = crypto_api.get_balance()
                crypto_balance = 0
                
                if balance_result.get("ok", False):
                    for currency in balance_result.get("result", []):
                        if currency.get("currency_code") == "USDT":
                            crypto_balance = float(currency.get("available", "0"))
                            break
                
                if crypto_balance >= amount:
                    check_result = crypto_api.create_check(
                        amount=amount,
                        asset="USDT",
                        description=f"Вывод всей казны от {admin_id}"
                    )
                    
                    if check_result.get("ok", False):
                        check = check_result.get("result", {})
                        check_link = check.get("bot_check_url", "")
                        
                        if check_link:
                            new_balance = db_module.update_treasury_balance(-amount)
                            
                            db_module.log_treasury_operation("Вывод всей казны через чек", amount, new_balance)
                            
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton("💸 Активировать чек", url=check_link))
                            markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                            
                            bot.edit_message_text(
                                f"✅ <b>Все средства успешно выведены с помощью чека!</b>\n\n"
                                f"Сумма: <code>{amount}</code> USDT\n"
                                f"Остаток в казне: <code>{new_balance}</code> USDT\n\n"
                                f"Для получения средств активируйте чек по кнопке ниже:", 
                                call.message.chat.id,
                                call.message.message_id,
                                parse_mode='HTML', 
                                reply_markup=markup
                            )
                            operation_success = True
                            return
                    else:
                        error_details = check_result.get("error_details", "Неизвестная ошибка")
                        markup = types.InlineKeyboardMarkup()
                        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                        
                        bot.edit_message_text(
                            f"⚠️ <b>Ошибка при создании чека:</b>\n{error_details}\n\n"
                            f"Будет выполнен стандартный вывод из казны.", 
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                
            except Exception as e:
                print(f"Error in Crypto Pay API: {e}")
                
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                
                bot.edit_message_text(
                    f"⚠️ <b>Ошибка при работе с CryptoBot:</b> {str(e)}\n"
                    f"Будет выполнен стандартный вывод из казны.", 
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML',
                    reply_markup=markup
                )
            
            if not operation_success:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))

                new_balance = db_module.update_treasury_balance(-amount)
                
                db_module.log_treasury_operation("Вывод всей казны", amount, new_balance)
                
                bot.edit_message_text(
                    f"✅ <b>Все средства успешно выведены!</b>\n\n"
                    f"Сумма: <code>{amount}</code> USDT\n"
                    f"Остаток в казне: <code>{new_balance}</code> USDT", 
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML', 
                    reply_markup=markup
                )

def calculate_amount_to_send(target_amount):
    amount_with_fee = target_amount / 0.97
    rounded_amount = round(amount_with_fee, 2)
    received_amount = rounded_amount * 0.97
    if received_amount < target_amount:
        rounded_amount += 0.01
    return round(rounded_amount, 2)




#================================================
#=======================РАССЫЛКА=================
#================================================

@bot.callback_query_handler(func=lambda call: call.data == "broadcast")
def request_broadcast_message(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("📢 Введите текст для рассылки:",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  reply_markup=markup)
        bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    if message.from_user.id in config.ADMINS_ID:
        broadcast_text = message.text
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ID FROM users')
            users = cursor.fetchall()
        
        success = 0
        failed = 0
        for user in users:
            try:
                bot.send_message(user[0], broadcast_text)
                success += 1
            except Exception:
                failed += 1
        
        stats_text = (f"📊 <b>Статистика рассылки:</b>\n\n"
                     f"✅ Успешно отправлено: {success}\n"
                     f"❌ Не удалось отправить: {failed}\n"
                     f"👥 Всего пользователей: {len(users)}")
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Новая рассылка", callback_data="broadcast"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, stats_text, reply_markup=markup, parse_mode='HTML')


#=================================================================================
#===============================НАСТРОЙКИ=========================================
#=================================================================================



@bot.callback_query_handler(func=lambda call: call.data == "settings")
def show_settings(call):
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
            result = cursor.fetchone()
            price, hold_time = result if result else (2.0, 5)
        
        settings_text = (
            "<b>⚙️ Настройки оплаты</b>\n\n"
            f"Текущая ставка: <code>{price}$</code> за номер\n"
            f"Время холда: <code>{hold_time}</code> минут\n\n"
            "Выберите параметр для изменения:"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Изменить сумму", callback_data="change_amount"))
        markup.add(types.InlineKeyboardButton("⏱ Изменить время холда", callback_data="change_hold_time"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        bot.edit_message_text(settings_text,
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "change_amount")
def change_amount_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("💰 Введите новую сумму оплаты (в долларах, например: 2):",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_change_amount)


def process_change_amount(message):
    if message.from_user.id in config.ADMINS_ID:
        try:
            new_amount = float(message.text)
            if new_amount <= 0:
                raise ValueError
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE settings SET PRICE = ?', (new_amount,))
                conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, f"✅ Сумма оплаты изменена на {new_amount}$", reply_markup=markup)
        except ValueError:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ Введите корректное положительное число!", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "change_hold_time")
def change_hold_time_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("⏱ Введите новое время холда (в минутах, например: 5):",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_change_hold_time)

def process_change_hold_time(message):
    if message.from_user.id in config.ADMINS_ID:
        try:
            new_time = int(message.text)
            if new_time <= 0:
                raise ValueError
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE settings SET HOLD_TIME = ?', (new_time,))
                conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, f"✅ Время холда изменено на {new_time} минут", reply_markup=markup)
        except ValueError:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ Введите корректное положительное целое число!", reply_markup=markup)


#===============================================================
#==========================МОДЕРАТОРЫ===========================
#===============================================================

@bot.callback_query_handler(func=lambda call: call.data == "moderators")
def moderators(call):
    if call.from_user.id in config.ADMINS_ID:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("➕ Добавить", callback_data="add_moder"),
            types.InlineKeyboardButton("➖ Удалить", callback_data="remove_moder")
        )
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(call.message.chat.id, "👥 Управление модераторами:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_moder")
def add_moder_request(call):
    if call.from_user.id in config.ADMINS_ID:
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        msg = bot.send_message(call.message.chat.id, "👤 Введите ID пользователя для назначения модератором:")
        bot.register_next_step_handler(msg, process_add_moder, msg.message_id)  # Передаём message_id

def process_add_moder(message, initial_message_id):
    try:
        new_moder_id = int(message.text)
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM personal WHERE ID = ? AND TYPE = ?', (new_moder_id, 'moder'))
            if cursor.fetchone() is not None:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
                try:
                    bot.delete_message(message.chat.id, message.message_id)
                    bot.delete_message(message.chat.id, initial_message_id)
                except Exception as e:
                    print(f"Ошибка удаления сообщения: {e}")
                bot.send_message(message.chat.id, "⚠️ Этот пользователь уже является модератором!", reply_markup=markup)
                return

            cursor.execute('SELECT COUNT(*) FROM groups')
            if cursor.fetchone()[0] == 0:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("➕ Создать группу", callback_data="create_group"))
                markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
                try:
                    bot.delete_message(message.chat.id, message.message_id)
                    bot.delete_message(message.chat.id, initial_message_id)
                except Exception as e:
                    print(f"Ошибка удаления сообщения: {e}")
                bot.send_message(message.chat.id, "❌ Нет созданных групп! Сначала создайте группу.", reply_markup=markup)
                return

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, initial_message_id)
        except Exception as e:
            print(f"Ошибка удаления сообщения: {e}")
        msg = bot.send_message(
            message.chat.id,
            f"👤 ID модератора: {new_moder_id}\n📝 Введите название группы для назначения:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_assign_group, new_moder_id, msg.message_id)  # Передаём message_id

    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, initial_message_id)
        except Exception as e:
            print(f"Ошибка удаления сообщения: {e}")
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID пользователя (только цифры)", reply_markup=markup)

def process_assign_group(message, new_moder_id, group_message_id):
    group_name = message.text.strip()
    
    if not group_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            print(f"Ошибка удаления сообщения (ввод названия группы): {e}")
        bot.send_message(message.chat.id, "❌ Название группы не может быть пустым!", reply_markup=markup)
        return

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID FROM groups WHERE NAME = ?', (group_name,))
        group = cursor.fetchone()

        if not group:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("👥 Группы", callback_data="groups"))
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except Exception as e:
                print(f"Ошибка удаления сообщения (ввод названия группы): {e}")
            bot.send_message(message.chat.id, f"❌ Группа '{group_name}' не найдена! Создайте её или выберите существующую.", 
                            reply_markup=markup)
            return

        group_id = group[0]

        try:
            # Удаляем сообщение с названием группы и предыдущее сообщение с запросом
            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.delete_message(message.chat.id, group_message_id)
            except Exception as e:
                print(f"Ошибка удаления сообщения (запрос названия группы): {e}")
                # Если удаление не удалось, редактируем сообщение
                bot.edit_message_text(
                    f"✅ Пользователь {new_moder_id} успешно назначен модератором в группу '{group_name}'!",
                    message.chat.id,
                    group_message_id,
                    reply_markup=None
                )
            
            # Назначаем модератора
            cursor.execute('INSERT INTO personal (ID, TYPE, GROUP_ID) VALUES (?, ?, ?)', 
                          (new_moder_id, 'moder', group_id))
            conn.commit()
            
            # Отправляем подтверждение модератору и планируем удаление
            moder_msg = bot.send_message(new_moder_id, f"🎉 Вам выданы права модератора в группе '{group_name}'! Напишите /start, чтобы начать работу.")
            threading.Timer(30.0, lambda: bot.delete_message(new_moder_id, moder_msg.message_id)).start()

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            bot.send_message(message.chat.id, f"✅ Пользователь {new_moder_id} успешно назначен модератором в группу '{group_name}'!", 
                            reply_markup=markup)

        except telebot.apihelper.ApiTelegramException:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            bot.send_message(message.chat.id, f"❌ Ошибка: Пользователь {new_moder_id} не начал диалог с ботом!", 
                            reply_markup=markup)
        except Exception as e:
            print(f"Ошибка в process_assign_group: {e}")
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            bot.send_message(message.chat.id, "❌ Произошла ошибка при назначении модератора!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "remove_moder")
def remove_moder_request(call):
    if call.from_user.id in config.ADMINS_ID:
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        msg = bot.send_message(call.message.chat.id, "👤 Введите ID пользователя для удаления из модераторов:")
        bot.register_next_step_handler(msg, process_remove_moder)

def process_remove_moder(message):
    try:
        moder_id = int(message.text)
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM personal WHERE ID = ? AND TYPE = ?', (moder_id, 'moder'))
            conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            if cursor.rowcount > 0:
                try:
                    msg = bot.send_message(moder_id, "⚠️ У вас были отозваны права модератора.")
                    # Планируем удаление через 30 секунд
                    threading.Timer(30.0, lambda: bot.delete_message(moder_id, msg.message_id)).start()
                except:
                    pass
                bot.send_message(message.chat.id, f"✅ Пользователь {moder_id} успешно удален из модераторов!", reply_markup=markup)
            else:
                bot.send_message(message.chat.id, "⚠️ Этот пользователь не является модератором!", reply_markup=markup)
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID пользователя (только цифры)", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "delete_moderator")
def delete_moderator_request(call):
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ID FROM personal WHERE TYPE = 'moder'")
            moderators = cursor.fetchall()
        
        if not moderators:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            try:
                bot.delete_message(call.message.chat.id, call.message.message_id)
            except:
                pass
            bot.send_message(call.message.chat.id, "❌ Нет модераторов для удаления", reply_markup=markup)
            return

        text = "👥 Выберите модератора для удаления:\n\n"
        markup = types.InlineKeyboardMarkup()
        for moder in moderators:
            text += f"ID: {moder[0]}\n"
            markup.add(types.InlineKeyboardButton(f"Удалить {moder[0]}", callback_data=f"confirm_delete_moder_{moder[0]}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(call.message.chat.id, text, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_moder_"))
def confirm_delete_moderator(call):
    if call.from_user.id in config.ADMINS_ID:
        moder_id = int(call.data.split("_")[3])
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM personal WHERE ID = ? AND TYPE = 'moder'", (moder_id,))
            affected_rows = cursor.rowcount
            conn.commit()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        if affected_rows > 0:
            try:
                msg = bot.send_message(moder_id, "⚠️ Ваши права модератора были отозваны администратором.")
                # Планируем удаление через 30 секунд
                threading.Timer(30.0, lambda: bot.delete_message(moder_id, msg.message_id)).start()
            except:
                pass
            bot.send_message(call.message.chat.id, f"✅ Модератор с ID {moder_id} успешно удален", reply_markup=markup)
        else:
            bot.send_message(call.message.chat.id, f"❌ Модератор с ID {moder_id} не найден", reply_markup=markup)

#=======================================================================================
#=======================================================================================
#===================================ГРУППЫ==============================================
#=======================================================================================
#=======================================================================================
#=======================================================================================




@bot.callback_query_handler(func=lambda call: call.data == "groups")
def groups_menu(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для управления группами!")
        return
    
    text = "<b>👥 Управление группами</b>"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("➕ Создать группу", callback_data="create_group"))
    markup.add(types.InlineKeyboardButton("➖ Удалить группу", callback_data="delete_group"))
    markup.add(types.InlineKeyboardButton("📋 Посмотреть все группы", callback_data="view_groups"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "create_group")
def create_group_request(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для создания группы!")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    msg = bot.send_message(call.message.chat.id, "📝 Введите название новой группы:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_create_group, msg.message_id)

def process_create_group(message, initial_message_id):
    if message.from_user.id not in config.ADMINS_ID:
        return
    
    group_name = message.text.strip()
    if not group_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            print(f"Ошибка удаления сообщения: {e}")
        bot.send_message(message.chat.id, "❌ Название группы не может быть пустым!", reply_markup=markup)
        return
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO groups (NAME) VALUES (?)', (group_name,))
            conn.commit()
        
        try:
            bot.delete_message(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, initial_message_id)
        except Exception as e:
            print(f"Ошибка удаления сообщения: {e}")
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👥 Группы", callback_data="groups"))
        markup.add(types.InlineKeyboardButton("🔙 Админ-панель", callback_data="admin_panel"))
        bot.send_message(message.chat.id, f"✅ Группа '{group_name}' успешно создана!", reply_markup=markup)

    except sqlite3.IntegrityError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            print(f"Ошибка удаления сообщения: {e}")
        bot.send_message(message.chat.id, f"❌ Группа с названием '{group_name}' уже существует!", reply_markup=markup)

def process_create_group(message, initial_message_id):
    if message.from_user.id not in config.ADMINS_ID:
        return
    
    group_name = message.text.strip()
    if not group_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        bot.send_message(message.chat.id, "❌ Название группы не может быть пустым!", reply_markup=markup)
        return
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('INSERT INTO groups (NAME) VALUES (?)', (group_name,))
            conn.commit()
        
        # Удаляем введённое сообщение и начальное сообщение
        try:
            bot.delete_message(message.chat.id, message.message_id)
            bot.delete_message(message.chat.id, initial_message_id)
        except:
            pass
        
        # Показываем сообщение об успехе с кнопками
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👥 Группы", callback_data="groups"))
        markup.add(types.InlineKeyboardButton("🔙 Админ-панель", callback_data="admin_panel"))
        success_msg = bot.send_message(message.chat.id, f"✅ Группа '{group_name}' успешно создана!", reply_markup=markup)
        
        # Планируем удаление сообщения об успехе и переход в админ-панель через 2 секунды
        def show_admin_panel():
            try:
                bot.delete_message(message.chat.id, success_msg.message_id)
                admin_panel(types.CallbackQuery(id=success_msg.message_id, from_user=message.from_user, 
                                               chat_instance=message.chat.id, message=success_msg, data="admin_panel"))
            except:
                pass
        
        threading.Timer(2.0, show_admin_panel).start()
        
    except sqlite3.IntegrityError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        bot.send_message(message.chat.id, f"❌ Группа с названием '{group_name}' уже существует!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "delete_group")
def delete_group_request(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для удаления группы!")
        return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    msg = bot.send_message(call.message.chat.id, "📝 Введите название группы для удаления:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_delete_group)

def process_delete_group(message):
    if message.from_user.id not in config.ADMINS_ID:
        return
    
    group_name = message.text.strip()
    if not group_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        bot.send_message(message.chat.id, "❌ Название группы не может быть пустым!", reply_markup=markup)
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID FROM groups WHERE NAME = ?', (group_name,))
        group = cursor.fetchone()
        
        if group:
            group_id = group[0]
            cursor.execute('UPDATE personal SET GROUP_ID = NULL WHERE GROUP_ID = ?', (group_id,))
            cursor.execute('DELETE FROM groups WHERE ID = ?', (group_id,))
            conn.commit()
            
            # Удаляем введенное сообщение
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            
            # Показываем сообщение об успехе временно
            success_msg = bot.send_message(message.chat.id, f"✅ Группа '{group_name}' успешно удалена!")
            
            # Планируем удаление сообщения об успехе и показ админ-панели через 2 секунды
            def show_admin_panel():
                try:
                    bot.delete_message(message.chat.id, success_msg.message_id)
                    admin_panel(types.CallbackQuery(id=success_msg.message_id, from_user=message.from_user, 
                                                   chat_instance=message.chat.id, message=success_msg, data="admin_panel"))
                except:
                    pass
            
            threading.Timer(2.0, show_admin_panel).start()
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            bot.send_message(message.chat.id, f"❌ Группа с названием '{group_name}' не найдена!", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "view_groups")
def admin_view_groups(call):
    user_id = call.from_user.id


    with db.get_db() as conn:
        cursor = conn.cursor()
        # Получаем все группы и их модераторов
        cursor.execute('''
            SELECT DISTINCT p.GROUP_ID, p.ID
            FROM personal p
            WHERE p.TYPE = 'moder' AND p.GROUP_ID IS NOT NULL
        ''')
        groups = cursor.fetchall()

    if not groups:
        bot.edit_message_text(
            "❌ Нет групп для отображения!",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=create_back_to_main_markup()
        )
        return

    text = "👥 <b>Список групп:</b>\n\n"
    markup = types.InlineKeyboardMarkup()
    for group_id, moderator_id in groups:
        cursor.execute('SELECT COUNT(*) FROM numbers n LEFT JOIN personal p ON p.ID = n.ID_OWNER WHERE n.STATUS = "отстоял" AND (p.GROUP_ID = ? OR p.GROUP_ID IS NULL)', (group_id,))
        successful_count = cursor.fetchone()[0]
        text += f"📊 Группа {group_id} (Модератор: {moderator_id})\n"
        text += f"✅ Успешных номеров: {successful_count}\n"
        markup.add(types.InlineKeyboardButton(f"📋 Статистика группы {group_id}", callback_data=f"view_group_stats_{group_id}"))
        text += "—\n"

    markup.add(types.InlineKeyboardButton("🔙 Админ-панель", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )





@bot.callback_query_handler(func=lambda call: call.data.startswith("view_group_stats_"))
def view_group_stats(call):
    user_id = call.from_user.id
    if user_id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра статистики!")
        return

    try:
        _, _, group_id, page = call.data.split("_")
        group_id = int(group_id)
        page = int(page)
        if page < 1:
            page = 1
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
        return

    with db.get_db() as conn:
        cursor = conn.cursor()
        # Подсчитываем участников (модераторов) группы
        cursor.execute('SELECT COUNT(*) FROM personal WHERE GROUP_ID = ? AND TYPE = "moder"', (group_id,))
        member_count = cursor.fetchone()[0]

        # Получаем номера с статусом "отстоял" для конкретной группы
        cursor.execute('''
            SELECT n.NUMBER, n.TAKE_DATE, n.SHUTDOWN_DATE
            FROM numbers n
            LEFT JOIN personal p ON p.ID = n.ID_OWNER
            WHERE n.STATUS = 'отстоял'
            AND (p.GROUP_ID = ? OR p.GROUP_ID IS NULL)
            ORDER BY n.SHUTDOWN_DATE DESC
        ''', (group_id,))
        numbers = cursor.fetchall()

    # Пагинация
    items_per_page = 20
    total_pages = max(1, (len(numbers) + items_per_page - 1) // items_per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_numbers = numbers[start_idx:end_idx]

    # Формируем текст статистики
    text = (
        f"<b>📊 Статистика группы {group_id}:</b>\n\n"
        f"👤 Участников: {member_count}\n"
        f"📱 Успешных номеров: {len(numbers)}\n"
        f"────────────────────\n"
        f"<b>📱 Список номеров (страница {page}/{total_pages}):</b>\n\n"
    )

    if not page_numbers:
        text += "📭 Нет успешных номеров в этой группе."
    else:
        for number, take_date, shutdown_date in page_numbers:
            text += f"Номер: {number}\n"
            text += f"🟢 Встал: {take_date}\n"
            text += f"🟢 Отстоял: {shutdown_date}\n"
            text += "───────────────────\n"

    # Проверяем лимит символов
    TELEGRAM_MESSAGE_LIMIT = 4096
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[:TELEGRAM_MESSAGE_LIMIT - 100] + "\n... (Сообщение обрезано, используйте пагинацию)"

    # Формируем разметку
    markup = types.InlineKeyboardMarkup()

    # Кнопки пагинации
    if total_pages > 1:
        row = []
        if page > 1:
            row.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"view_group_stats_{group_id}_{page-1}"))
        row.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            row.append(types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"view_group_stats_{group_id}_{page+1}"))
        if row:
            markup.row(*row)

    markup.add(types.InlineKeyboardButton("👥 Все группы", callback_data="admin_view_groups"))
    markup.add(types.InlineKeyboardButton("🔙 Админ-панель", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))

    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )















#ВСЕ ПОЛЬЗОВАТЕЛИ КНОПКА

@bot.callback_query_handler(func=lambda call: call.data.startswith("all_users_"))
def show_all_users(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра пользователей!")
        return
    
    try:
        page = int(call.data.split("_")[2])
    except (IndexError, ValueError):
        page = 1  # Если что-то пошло не так, открываем первую страницу
    
    # Получаем всех пользователей из таблицы requests
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID FROM requests')
        all_users = cursor.fetchall()
    
    if not all_users:
        text = "📭 Нет пользователей в боте."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
    else:
        # Пагинация
        users_per_page = 8
        total_pages = (len(all_users) + users_per_page - 1) // users_per_page
        page = max(1, min(page, total_pages))  # Ограничиваем страницу допустимым диапазоном
        
        start_idx = (page - 1) * users_per_page
        end_idx = start_idx + users_per_page
        page_users = all_users[start_idx:end_idx]
        
        # Формируем текст
        text = f"<b>Управляйте людьми:</b>\n({page} страница)\n\n"
        markup = types.InlineKeyboardMarkup()
        
        # Добавляем кнопки для каждого пользователя
        for user_data in page_users:
            user_id = user_data[0]
            try:
                user = bot.get_chat_member(user_id, user_id).user
                username = f"@{user.username}" if user.username else "Нет username"
            except:
                username = "Неизвестный пользователь"
            
            markup.add(types.InlineKeyboardButton(f"{user_id} {username}", callback_data=f"user_details_{user_id}"))
        
        # Кнопки пагинации
        if total_pages > 1:
            row = []
            if page > 1:
                row.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"all_users_{page-1}"))
            row.append(types.InlineKeyboardButton(f"{page}", callback_data=f"all_users_{page}"))
            if page < total_pages:
                row.append(types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"all_users_{page+1}"))
            markup.row(*row)
        
        # Кнопка "Найти по username или userid"
        markup.add(types.InlineKeyboardButton("🔍 Найти по username или userid", callback_data="find_user"))
        
        # Кнопка "Вернуться в админ-панель"
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)

#поиск пользователя по юзерид или юзернейм
@bot.callback_query_handler(func=lambda call: call.data == "find_user")
def find_user(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для поиска пользователей!")
        return
    
    # Запрашиваем у админа username или userid
    text = "🔍 Введите @username или userid пользователя для поиска:"
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Отмена", callback_data="all_users_1"))
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    msg = bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)
    
    # Регистрируем следующий шаг для обработки введённых данных
    bot.register_next_step_handler(msg, process_user_search, call.message.chat.id)

def process_user_search(message, original_chat_id):
    if message.chat.id != original_chat_id or message.from_user.id not in config.ADMINS_ID:
        bot.send_message(message.chat.id, "❌ Ошибка: действие доступно только администратору!")
        return
    
    search_query = message.text.strip()
    
    # Удаляем сообщение с введёнными данными
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except:
        pass
    
    # Проверяем, что ввёл пользователь
    user_id = None
    username = None
    
    if search_query.startswith('@'):
        username = search_query[1:]  # Убираем @ из username
    else:
        try:
            user_id = int(search_query)  # Пробуем преобразовать в число (userid)
        except ValueError:
            bot.send_message(message.chat.id, "❌ Неверный формат! Введите @username или userid (число).")
            return
    
    # Ищем пользователя в базе
    with db.get_db() as conn:
        cursor = conn.cursor()
        if user_id:
            cursor.execute('SELECT ID FROM requests WHERE ID = ?', (user_id,))
        else:
            cursor.execute('SELECT ID FROM requests')
        
        users = cursor.fetchall()
    
    found_user_id = None
    if user_id:
        if users:
            found_user_id = users[0][0]  # Нашли по user_id
    else:
        # Ищем по username
        for uid in users:
            try:
                user = bot.get_chat_member(uid[0], uid[0]).user
                if user.username and user.username.lower() == username.lower():
                    found_user_id = uid[0]
                    break
            except:
                continue
    
    # Формируем ответ
    if found_user_id:
        try:
            user = bot.get_chat_member(found_user_id, found_user_id).user
            username_display = f"@{user.username}" if user.username else "Нет username"
        except:
            username_display = "Неизвестный пользователь"
        
        text = (
            f"<b>Найденный пользователь:</b>\n\n"
            f"🆔 ID: <code>{found_user_id}</code>\n"
            f"👤 Username: {username_display}\n"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(f"{found_user_id} {username_display}", callback_data=f"user_details_{found_user_id}"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться к списку пользователей", callback_data="all_users_1"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
    else:
        text = "❌ Пользователь не найден!"
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться к списку пользователей", callback_data="all_users_1"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
    
    # Отправляем новое сообщение (заменяем старое)
    bot.send_message(message.chat.id, text, parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("user_details_"))
def user_details(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для управления пользователями!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    # Получаем информацию о пользователе
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        # Проверяем, есть ли пользователь в базе
        cursor.execute('SELECT BLOCKED, CAN_SUBMIT_NUMBERS FROM requests WHERE ID = ?', (user_id,))
        user_data = cursor.fetchone()
        if not user_data:
            text = f"❌ Пользователь с ID {user_id} не найден!"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Вернуться к списку пользователей", callback_data="all_users_1"))
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
            return
        
        is_blocked = user_data[0]
        can_submit_numbers = user_data[1]
        
        # Статистика по номерам
        cursor.execute('SELECT STATUS, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE ID_OWNER = ?', (user_id,))
        numbers = cursor.fetchall()
        
        total_numbers = len(numbers)
        active_numbers = sum(1 for num in numbers if num[0] == 'активен')
        invalid_numbers = sum(1 for num in numbers if num[0] == 'не валид')
        not_sustained = sum(1 for num in numbers if num[2] != "0" and num[0] != 'активен')  # Слетевшие номера
        
    # Получаем username через Telegram API
    try:
        user = bot.get_chat_member(user_id, user_id).user
        username = f"@{user.username}" if user.username else "Нет username"
    except:
        username = "Неизвестный пользователь"
    
    # Формируем текст
    text = (
        f"<b>Пользователь {user_id} {username}</b>\n\n"
        f"📱 Принял номеров: {total_numbers}\n"
        f"✅ Которые на данный момент работают: {active_numbers}\n"
        f"❌ Не валидные: {invalid_numbers}\n"
        f"⏳ Сколько не отстояло: {not_sustained}\n"
    )
    
    # Формируем кнопки
    markup = types.InlineKeyboardMarkup()
    
    # Кнопка блокировки/разблокировки
    if is_blocked:
        markup.add(types.InlineKeyboardButton("✅ Разблокировать в боте", callback_data=f"unblock_user_{user_id}"))
    else:
        markup.add(types.InlineKeyboardButton("❌ Заблокировать в боте", callback_data=f"block_user_{user_id}"))
    
    # Кнопка "Выгнать из бота"
    markup.add(types.InlineKeyboardButton("🚪 Выгнать из бота", callback_data=f"kick_user_{user_id}"))
    
    # Кнопка запрета/разрешения сдачи номеров
    if can_submit_numbers:
        markup.add(types.InlineKeyboardButton("🚫 Запретить сдавание номеров", callback_data=f"disable_numbers_{user_id}"))
    else:
        markup.add(types.InlineKeyboardButton("✅ Разрешить сдавание номеров", callback_data=f"enable_numbers_{user_id}"))
    
    # Кнопки навигации
    markup.add(types.InlineKeyboardButton("🔙 Вернуться к списку пользователей", callback_data="all_users_1"))
    markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data.startswith("block_user_"))
def block_user(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])  # Убедимся, что user_id определён
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE requests SET BLOCKED = 1 WHERE ID = ?', (user_id,))
        conn.commit()
    
    try:
        bot.send_message(user_id, "🚫 Вас заблокировали в боте!")
    except:
        pass
    
    bot.answer_callback_query(call.id, f"Пользователь {user_id} заблокирован!")
    user_details(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("unblock_user_"))
def unblock_user(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE requests SET BLOCKED = 0 WHERE ID = ?', (user_id,))
        conn.commit()
    
    try:
        bot.send_message(user_id, "✅ Вас разблокировали в боте! Напишите /start")
    except:
        pass
    
    bot.answer_callback_query(call.id, f"Пользователь {user_id} разблокирован!")
    # Обновляем информацию о пользователе
    user_details(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("kick_user_"))
def kick_user(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE requests SET STATUS = "pending", LAST_REQUEST = ? WHERE ID = ?', (current_date, user_id))
        conn.commit()
    
    try:
        bot.send_message(user_id, "🚪 Вас выгнали из бота! Вам нужно снова подать заявку на вступление. Напишите /start")
    except:
        pass
    
    bot.answer_callback_query(call.id, f"Пользователь {user_id} выгнан из бота!")
    # Возвращаемся к списку пользователей
    call.data = "all_users_1"  # Возвращаемся на первую страницу
    show_all_users(call)


@bot.callback_query_handler(func=lambda call: call.data.startswith("disable_numbers_"))
def disable_numbers(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE requests SET CAN_SUBMIT_NUMBERS = 0 WHERE ID = ?', (user_id,))
        conn.commit()
    
    try:
        bot.send_message(user_id, "🚫 Вам запретили сдавать номера!")
    except:
        pass
    
    bot.answer_callback_query(call.id, f"Пользователю {user_id} запрещено сдавать номера!")
    # Обновляем информацию о пользователе
    user_details(call)

@bot.callback_query_handler(func=lambda call: call.data.startswith("enable_numbers_"))
def enable_numbers(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE requests SET CAN_SUBMIT_NUMBERS = 1 WHERE ID = ?', (user_id,))
        conn.commit()
    
    try:
        bot.send_message(user_id, "✅ Вам разрешили сдавать номера!")
    except:
        pass
    
    bot.answer_callback_query(call.id, f"Пользователю {user_id} разрешено сдавать номера!")
    # Обновляем информацию о пользователе
    user_details(call)


#=======================================================================================
#=======================================================================================
#===================================АДМИНКА=====================================
#=======================================================================================
#=======================================================================================
#=======================================================================================


@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    with treasury_lock:
        if call.from_user.id in active_treasury_admins:
            del active_treasury_admins[call.from_user.id]
    
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")

            cursor.execute('''
                SELECT TAKE_DATE, SHUTDOWN_DATE 
                FROM numbers 
                WHERE SHUTDOWN_DATE LIKE ? || "%" 
                AND TAKE_DATE != "0" 
                AND TAKE_DATE != "1"
            ''', (today,))
            
            total_numbers = 0
            numbers_count = 0
            
            for take_date, shutdown_date in cursor.fetchall():
                numbers_count += 1
                total_numbers += 1

        admin_text = (
            "<b>⚙️ Панель администратора</b>\n\n"
            f"📱 Слетевших номеров: <code>{numbers_count}</code>\n"
            f"📊 Всего обработанных номеров: <code>{total_numbers}</code>"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👥 Модераторы", callback_data="moderators"))
        markup.add(types.InlineKeyboardButton("👥 Группы", callback_data="groups"))  # Новая кнопка
        markup.add(types.InlineKeyboardButton("➖ Удалить модератора", callback_data="delete_moderator"))
        markup.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="broadcast"))
        markup.add(types.InlineKeyboardButton("💰 Казна", callback_data="treasury"))
        markup.add(types.InlineKeyboardButton("⚙️ Настройки", callback_data="settings"))
        markup.add(types.InlineKeyboardButton("📱 Все номера", callback_data="all_numbers"))
        markup.add(types.InlineKeyboardButton("📊 Статистика", callback_data="group_statistics"))
        markup.add(types.InlineKeyboardButton("📝 Заявки на вступление", callback_data="pending_requests"))    
        markup.add(types.InlineKeyboardButton("👤 Все пользователи", callback_data="all_users_1"))  # Новая кнопка
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except:
            pass
        bot.send_message(call.message.chat.id, admin_text, parse_mode='HTML', reply_markup=markup)

def check_time():
    while True:
        current_time = datetime.now().strftime("%H:%M")
        if current_time == config.CLEAR_TIME:
            clear_database()
            time.sleep(61)
        time.sleep(30)

def check_numbers_for_payment():
    while True:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
            result = cursor.fetchone()
            price, hold_time = result if result else (2.0, 5)
            
            cursor.execute('SELECT NUMBER, ID_OWNER, TAKE_DATE FROM numbers WHERE SHUTDOWN_DATE = "0" AND STATUS = "активен" AND TAKE_DATE NOT IN ("0", "1")')
            active_numbers = cursor.fetchall()
            
            current_time = datetime.now()
            for number, owner_id, take_date in active_numbers:
                try:
                    take_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                    time_diff = (current_time - take_time).total_seconds() / 60
                    
                    if time_diff >= hold_time:
                        db.update_balance(owner_id, price)
                        bot.send_message(owner_id, 
                                       f"✅ Ваш номер {number} проработал {hold_time} минут!\n"
                                       f"💵 Вам начислено: ${price}")
                        shutdown_date = current_time.strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute('UPDATE numbers SET SHUTDOWN_DATE = ? WHERE NUMBER = ?', (shutdown_date, number))
                        conn.commit()
                except ValueError as e:
                    print(f"Ошибка при обработке номера {number}: {e}")
                    continue
        time.sleep(60)
        
def clear_database():
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT ID_OWNER FROM numbers WHERE ID_OWNER NOT IN (SELECT ID FROM personal WHERE TYPE = "ADMIN" OR TYPE = "moder")')
        users = cursor.fetchall()
        
        cursor.execute('DELETE FROM numbers')
        conn.commit()
        
        for user in users:
            try:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number"))
                bot.send_message(user[0], "🔄 Очередь очищена.\n📱 Пожалуйста, поставьте свои номера снова.", reply_markup=markup)
            except:
                continue
        
        for admin_id in config.ADMINS_ID:
            try:
                bot.send_message(admin_id, "🔄 Очередь очищена, пользователи предупреждены.")
            except:
                continue

def run_bot():
    time_checker = threading.Thread(target=check_time)
    time_checker.daemon = True
    time_checker.start()
    
    payment_checker = threading.Thread(target=check_numbers_for_payment)
    payment_checker.daemon = True
    payment_checker.start()
    
    
    bot.polling(none_stop=True)

def check_balance_and_fix(user_id):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BALANCE FROM users WHERE ID = ?', (user_id,))
        user = cursor.fetchone()
        if user and user[0] < 0:
            cursor.execute('UPDATE users SET BALANCE = 0 WHERE ID = ?', (user_id,))
            conn.commit()





#СТАТИСТИКА ГРУПП

@bot.callback_query_handler(func=lambda call: call.data.startswith("group_statistics"))
def group_statistics(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра статистики!")
        return
    
    page = 1
    if "_" in call.data:
        try:
            page = int(call.data.split("_")[1])
            if page < 1:
                page = 1
        except (IndexError, ValueError):
            page = 1
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID, NAME FROM groups ORDER BY NAME')
        groups = cursor.fetchall()
    
    if not groups:
        text = "📭 Нет доступных групп."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        return
    
    # Пагинация
    items_per_page = 20
    total_pages = (len(groups) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_groups = groups[start_idx:end_idx]
    
    text = f"<b>📊 Список групп (страница {page}/{total_pages}):</b>\n\n"
    markup = types.InlineKeyboardMarkup()
    
    for group_id, group_name in page_groups:
        text += f"🏠 {group_name}\n"
        text += f"🆔 ID: {group_id}\n"
        text += "────────────────────\n"
        markup.add(types.InlineKeyboardButton(f"📊 {group_name}", callback_data=f"group_stats_{group_id}_1"))
    
    # Проверяем лимит символов
    TELEGRAM_MESSAGE_LIMIT = 4096
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[:TELEGRAM_MESSAGE_LIMIT - 100] + "\n... (Сообщение обрезано, используйте пагинацию)"
    
    # Кнопки пагинации
    if total_pages > 1:
        row = []
        if page > 1:
            row.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"group_statistics_{page-1}"))
        row.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            row.append(types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"group_statistics_{page+1}"))
        if row:
            markup.row(*row)
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)

      


@bot.callback_query_handler(func=lambda call: call.data.startswith("group_stats_"))
def show_group_details(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра статистики!")
        return
    
    try:
        _, _, group_id, page = call.data.split("_")
        group_id = int(group_id)
        page = int(page)
        if page < 1:
            page = 1
    except (IndexError, ValueError):
        bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Получаем название группы
        cursor.execute('SELECT NAME FROM groups WHERE ID = ?', (group_id,))
        group = cursor.fetchone()
        if not group:
            text = "❌ Группа не найдена!"
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 К списку групп", callback_data="group_statistics_1"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
            return
        
        group_name = group[0]
        
        # Подсчитываем участников (модераторов)
        cursor.execute('SELECT COUNT(*) FROM personal WHERE GROUP_ID = ? AND TYPE = "moder"', (group_id,))
        member_count = cursor.fetchone()[0]
        
        # Подсчитываем успешные номера (статус "отстоял")
        cursor.execute('''
            SELECT COUNT(*) 
            FROM numbers n
            JOIN personal p ON n.CONFIRMED_BY_MODERATOR_ID = p.ID
            WHERE p.GROUP_ID = ? AND n.STATUS = 'отстоял'
        ''', (group_id,))
        successful_numbers = cursor.fetchone()[0]
        
        # Получаем номера группы, подтверждённые модераторами (убрали STATUS из SELECT)
        cursor.execute('''
            SELECT n.NUMBER, n.TAKE_DATE, n.SHUTDOWN_DATE
            FROM numbers n
            JOIN personal p ON n.CONFIRMED_BY_MODERATOR_ID = p.ID
            WHERE p.GROUP_ID = ? AND n.STATUS = 'отстоял'
            ORDER BY n.SHUTDOWN_DATE DESC
        ''', (group_id,))
        numbers = cursor.fetchall()
    
    # Пагинация
    items_per_page = 20
    total_pages = max(1, (len(numbers) + items_per_page - 1) // items_per_page)
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_numbers = numbers[start_idx:end_idx]
    
    # Формируем текст статистики
    text = (
        f"<b>📊 Статистика группы: {group_name}</b>\n\n"
        f"👤 Участников: {member_count}\n"
        f"📱 Успешных номеров: {successful_numbers}\n"
        f"────────────────────\n"
        f"<b>📱 Список номеров (страница {page}/{total_pages}):</b>\n\n"
    )
    
    if not page_numbers:
        text += "📭 Нет успешных номеров в этой группе."
    else:
        for number, take_date, shutdown_date in page_numbers:
            text += f"Номер: {number}\n"
            text += f"🟢 Встал: {take_date}\n"
            text += f"🟢 Отстоял: {shutdown_date}\n"
            text += "────────────────────\n"
    
    # Проверяем лимит символов
    TELEGRAM_MESSAGE_LIMIT = 4096
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[:TELEGRAM_MESSAGE_LIMIT - 100] + "\n... (Сообщение обрезано, используйте пагинацию)"
    
    # Формируем разметку
    markup = types.InlineKeyboardMarkup()
    
    # Кнопки пагинации
    if total_pages > 1:
        row = []
        if page > 1:
            row.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"group_stats_{group_id}_{page-1}"))
        row.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            row.append(types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"group_stats_{group_id}_{page+1}"))
        if row:
            markup.row(*row)
    
    markup.add(types.InlineKeyboardButton("🔙 К списку групп", callback_data="group_statistics_1"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)



# ОБЫЧНОГО ПОЛЬЗОВАТЕЛЯ НОМЕРА:


@bot.callback_query_handler(func=lambda call: call.data == "my_numbers")
def show_my_numbers(call):
    user_id = call.from_user.id
    is_moderator = db.is_moderator(user_id)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT NUMBER, STATUS, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE ID_OWNER = ?', (user_id,))
        numbers = cursor.fetchall()
    
    if not numbers:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("📭 У вас нет номеров.", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return
    
    text = "📋 <b>Ваши номера:</b>\n\n"
    for number, status, take_date, shutdown_date in numbers:
        text += f"📱 Номер: <code>{number}</code>\n"
        text += f"📊 Статус: {status}\n"
        if take_date not in ("0", "1"):
            text += f"🟢 Встал: {take_date}\n"
        if shutdown_date and shutdown_date != "0":
            if status == "отстоял":
                text += f"🟢 Отстоял: {shutdown_date}\n"
            else:
                text += f"🔴 Слетел: {shutdown_date}\n"
        text += "────────────────────\n"
    
    markup = types.InlineKeyboardMarkup()
    for number, status, take_date, shutdown_date in numbers:
        if status == "отстоял":
            markup.add(types.InlineKeyboardButton(f"🟢 {number}", callback_data=f"view_stood_number_{number}"))
        elif shutdown_date and shutdown_date != "0":
            markup.add(types.InlineKeyboardButton(f"🔴 {number}", callback_data=f"view_failed_number_{number}"))
        else:
            markup.add(types.InlineKeyboardButton(f"⚪ {number}", callback_data=f"view_number_details_{number}"))
    
    markup.add(types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)


# НОМЕРА КОТОРЫЕ ПОКАЗЫВАЮТСЯ У  МОДЕРАТОРОВ:
@bot.callback_query_handler(func=lambda call: call.data == "moderator_numbers")
def handle_moderator_numbers(call):
    user_id = call.from_user.id
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT n.NUMBER, n.STATUS, n.TAKE_DATE, n.SHUTDOWN_DATE, n.MODERATOR_ID, n.CONFIRMED_BY_MODERATOR_ID
            FROM numbers n
            WHERE n.MODERATOR_ID = ? OR n.CONFIRMED_BY_MODERATOR_ID = ?
        ''', (user_id, user_id))
        numbers = cursor.fetchall()
    
    if not numbers:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("📭 У вас нет номеров.", call.message.chat.id, call.message.message_id, reply_markup=markup)
        return
    
    text = "📋 <b>Ваши номера:</b>\n\n"
    
    markup = types.InlineKeyboardMarkup()
    for number, status, take_date, shutdown_date, moderator_id, confirmed_by in numbers:
        if confirmed_by == user_id and shutdown_date == "0" and status == "активен":
            markup.add(types.InlineKeyboardButton(f"ℹ️ {number}", callback_data=f"view_number_details_{number}"))
        elif status == "отстоял":
            markup.add(types.InlineKeyboardButton(f"🟢 {number}", callback_data=f"view_stood_number_{number}"))
        elif status == "слетел":
            markup.add(types.InlineKeyboardButton(f"🔴 {number}", callback_data=f"view_failed_number_{number}"))
        elif status == "на проверке" and moderator_id == user_id:
            markup.add(types.InlineKeyboardButton(f"❓ {number}", callback_data=f"view_number_details_{number}"))
    
    markup.add(types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)

def view_active_number(call):
    number = call.data.split("_")[3]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT TAKE_DATE FROM numbers WHERE NUMBER = ?', (number,))
        take_date = cursor.fetchone()[0]
        print(f"Active number {number} details: take_date={take_date}")  # Отладка
    
    text = (
        f"📲 Номер: {number}\n"
        f"📊 Статус: активен\n"
        f"🟢 Встал: {take_date}\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔴 Слетел", callback_data=f"mark_failed_{number}"))
    markup.add(types.InlineKeyboardButton("Вернуться в номера", callback_data="moderator_numbers"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("mark_failed_"))
def mark_failed(call):
    number = call.data.split("_")[2]
    user_id = call.from_user.id
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT TAKE_DATE, ID_OWNER, CONFIRMED_BY_MODERATOR_ID, STATUS FROM numbers WHERE NUMBER = ?', (number,))
            data = cursor.fetchone()
            if not data:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            
            take_date, owner_id, confirmed_by_moderator_id, status = data
            
            if status == "отстоял":
                bot.answer_callback_query(call.id, "✅ Номер уже отстоял своё время!")
                return
            
            if confirmed_by_moderator_id != user_id:
                bot.answer_callback_query(call.id, "❌ Вы не можете пометить этот номер как слетевший!")
                return
            
            cursor.execute('SELECT HOLD_TIME FROM settings')
            result = cursor.fetchone()
            hold_time = result[0] if result else 5
            
            end_time = datetime.now()
            if take_date in ("0", "1"):
                work_time = 0
                worked_enough = False
            else:
                start_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                work_time = (end_time - start_time).total_seconds() / 60
                worked_enough = work_time >= hold_time
            
            shutdown_date = end_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('UPDATE numbers SET SHUTDOWN_DATE = ?, STATUS = "слетел" WHERE NUMBER = ?', 
                          (shutdown_date, number))
            conn.commit()
        
        mod_message = (
            f"📱 Номер: <code>{number}</code>\n"
            f"📊 Статус: слетел\n"
        )
        if take_date not in ("0", "1"):
            mod_message += f"🟢 Встал: {take_date}\n"
        mod_message += f"🔴 Слетел: {shutdown_date}\n"
        if not worked_enough:
            mod_message += f"⚠️ Номер не отработал минимальное время ({hold_time} минут)!\n"
        mod_message += f"⏳ Время работы: {work_time:.2f} минут"
        
        owner_message = (
            f"❌ Ваш номер {number} слетел.\n"
            f"📱 Номер: <code>{number}</code>\n"
            f"📊 Статус: слетел\n"
        )
        if take_date not in ("0", "1"):
            owner_message += f"🟢 Встал: {take_date}\n"
        owner_message += f"🔴 Слетел: {shutdown_date}\n"
        if not worked_enough:
            owner_message += f"⏳ Время работы: {work_time:.2f} минут"
        
        bot.send_message(owner_id, owner_message, parse_mode='HTML')
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 В номера", callback_data="moderator_numbers"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(mod_message, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')
    
    except Exception as e:
        print(f"[ERROR] Ошибка в mark_failed: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке номера.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_failed_number_"))
def view_failed_number(call):
    number = call.data.split("_")[3]
    user_id = call.from_user.id
    is_moderator = db.is_moderator(user_id)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE NUMBER = ?', (number,))
        data = cursor.fetchone()
    
    if not data:
        bot.answer_callback_query(call.id, "❌ Номер не найден!")
        return
    
    status, take_date, shutdown_date = data
    text = (
        f"📱 Номер: <code>{number}</code>\n"
        f"📊 Статус: {status}\n"
        f"🟢 Встал: {take_date}\n"
        f"🔴 Слетел: {shutdown_date}\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    back_callback = "my_numbers" if not is_moderator else "moderator_numbers"
    markup.add(types.InlineKeyboardButton("🔙 В номера", callback_data=back_callback))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_stood_number_"))
def view_stood_number(call):
    number = call.data.split("_")[3]
    user_id = call.from_user.id
    is_moderator = db.is_moderator(user_id)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE NUMBER = ?', (number,))
        data = cursor.fetchone()
    
    if not data:
        bot.answer_callback_query(call.id, "❌ Номер не найден!")
        return
    
    status, take_date, shutdown_date = data
    text = (
        f"📱 Номер: <code>{number}</code>\n"
        f"📊 Статус: {status}\n"
        f"🟢 Встал: {take_date}\n"
        f"🟢 Отстоял: {shutdown_date}\n"
    )
    
    markup = types.InlineKeyboardMarkup()
    back_callback = "my_numbers" if not is_moderator else "moderator_numbers"
    markup.add(types.InlineKeyboardButton("🔙 В номера", callback_data=back_callback))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("view_number_details_"))
def view_number_details(call):
    number = call.data.split("_")[3]
    user_id = call.from_user.id
    is_moderator = db.is_moderator(user_id)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS, TAKE_DATE, SHUTDOWN_DATE, MODERATOR_ID, CONFIRMED_BY_MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        data = cursor.fetchone()
    
    if not data:
        bot.answer_callback_query(call.id, "❌ Номер не найден!")
        return
    
    status, take_date, shutdown_date, moderator_id, confirmed_by_moderator_id = data
    text = (
        f"📱 Номер: <code>{number}</code>\n"
        f"📊 Статус: {status}\n"
    )
    if take_date not in ("0", "1"):
        text += f"🟢 Встал: {take_date}\n"
    if shutdown_date and shutdown_date != "0":
        text += f"{'🟢 Отстоял' if status == 'отстоял' else '🔴 Слетел'}: {shutdown_date}\n"
    
    markup = types.InlineKeyboardMarkup()
    if is_moderator and shutdown_date == "0" and status == "активен" and confirmed_by_moderator_id == user_id:
        markup.add(types.InlineKeyboardButton("🔴 Слетел", callback_data=f"mark_failed_{number}"))
    
    back_callback = "my_numbers" if not is_moderator else "moderator_numbers"
    markup.add(types.InlineKeyboardButton("🔙 В номера", callback_data=back_callback))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)

def confirm_number(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET CONFIRMED_BY_MODERATOR_ID = ? WHERE NUMBER = ?', (call.from_user.id, number))
        conn.commit()
        print(f"Confirmed number {number} with moderator_id {call.from_user.id}")  # Отладка
    
    # Обновляем интерфейс модератора
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT NUMBER, STATUS, TAKE_DATE, SHUTDOWN_DATE, CONFIRMED_BY_MODERATOR_ID, MODERATOR_ID FROM numbers WHERE MODERATOR_ID = ? OR CONFIRMED_BY_MODERATOR_ID = ?', (call.from_user.id, call.from_user.id))
        numbers = cursor.fetchall()
        print("Updated numbers after confirmation:", numbers)  # Отладка
    
    text = "📋 <b>Ваши номера для проверки:</b>\n\n"
    markup = types.InlineKeyboardMarkup()
    for number, status, take_date, shutdown_date, confirmed_by, moderator_id in numbers:
        if confirmed_by and confirmed_by != 0 and not shutdown_date:
            markup.add(types.InlineKeyboardButton(f"⚪{number}", callback_data=f"view_active_number_{number}"))
        elif status == "отстоял":
            markup.add(types.InlineKeyboardButton(f"🟢 {number}", callback_data=f"view_stood_number_{number}"))
        elif shutdown_date and shutdown_date != "0":
            markup.add(types.InlineKeyboardButton(f"🔴 {number}", callback_data=f"view_failed_number_{number}"))
        elif moderator_id == call.from_user.id and (not confirmed_by or confirmed_by == 0):
            markup.add(types.InlineKeyboardButton(f"⏳{number}", callback_data=f"confirm_number_{number}"))
    
    markup.add(types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
    bot.answer_callback_query(call.id, f"✅ Номер {number} подтверждён.")
#ВСЕ НОМЕРА КОТОРЫЕ ПОКАЗЫВАЮТСЯ У АДМИНИСТАТОРА + СТАТИТСИКА ГРУПП

# Глобальная переменная для хранения данных номеров (можно заменить на временное хранилище в будущем)
numbers_data_cache = {}

@bot.callback_query_handler(func=lambda call: call.data == "all_numbers")
def show_all_numbers(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра всех номеров!")
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT n.NUMBER, n.STATUS, n.TAKE_DATE, n.SHUTDOWN_DATE, n.MODERATOR_ID, n.CONFIRMED_BY_MODERATOR_ID, p.GROUP_ID
            FROM numbers n
            LEFT JOIN personal p ON p.ID = n.CONFIRMED_BY_MODERATOR_ID
        ''')
        numbers = cursor.fetchall()
    
    if not numbers:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        bot.edit_message_text(
            "📭 Нет номеров в системе.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return

    text = "<b>📱 Все номера:</b>\n\n"
    for number, status, take_date, shutdown_date, moderator_id, confirmed_by_moderator_id, group_id in numbers:
        group_name = db_module.get_group_name(group_id) if group_id else "Без группы"
        mod_id = confirmed_by_moderator_id or moderator_id or "Не указан"
        text += f"📱 Номер: {number}\n"
        text += f"Группа: {group_name} | Модератор ID: {mod_id}\n"
        text += f"📊 Статус: {status}\n"
        if take_date not in ("0", "1"):
            text += f"🟢 Встал: {take_date}\n"
        if shutdown_date != "0" and status == "отстоял":
            text += f"🟢 Отстоял: {shutdown_date}\n"
        text += "────────────────────\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )

def show_numbers_page(call, page):
    user_id = call.from_user.id
    if user_id not in numbers_data_cache:
        bot.answer_callback_query(call.id, "❌ Данные устарели, пожалуйста, запросите список заново!")
        return
    
    numbers = numbers_data_cache[user_id]
    items_per_page = 5  # По 5 номеров на страницу
    total_items = len(numbers)
    total_pages = (total_items + items_per_page - 1) // items_per_page
    
    if page < 0 or page >= total_pages:
        bot.answer_callback_query(call.id, "❌ Страница недоступна!")
        return
    
    start_idx = page * items_per_page
    end_idx = min(start_idx + items_per_page, total_items)
    page_numbers = numbers[start_idx:end_idx]
    
    # Формируем текст для текущей страницы
    text = f"<b>📱 Список всех номеров (Страница {page + 1} из {total_pages}):</b>\n\n"
    for number, take_date, shutdown_date, user_id, group_name in page_numbers:
        group_info = f"👥 Группа: {group_name}" if group_name else "👥 Группа: Не указана"
        user_info = f"🆔 Пользователь: {user_id}" if user_id else "🆔 Пользователь: Не указан"
        text += (
            f"📞 <code>{number}</code>\n"
            f"{user_info}\n"
            f"{group_info}\n"
            f"📅 Взят: {take_date}\n"
            f"📴 Отключён: {shutdown_date or 'Ещё активен'}\n\n"
        )
    
    # Создаём кнопки для навигации
    markup = types.InlineKeyboardMarkup()
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"numbers_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"numbers_page_{page+1}"))
    if nav_buttons:
        markup.row(*nav_buttons)
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    # Отправляем или редактируем сообщение
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
        print(f"Удалено старое сообщение {call.message.message_id} в чате {call.message.chat.id}")
    except Exception as e:
        print(f"Ошибка при удалении старого сообщения: {e}")
    
    bot.send_message(
        call.message.chat.id,
        text,
        parse_mode='HTML',
        reply_markup=markup
    )
    print(f"Страница {page + 1} отправлена успешно")

@bot.callback_query_handler(func=lambda call: call.data.startswith("numbers_page_"))
def numbers_page_callback(call):
    page = int(call.data.split("_")[2])
    show_numbers_page(call, page)



@bot.callback_query_handler(func=lambda call: call.data == "settings")
def show_settings(call):
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
            result = cursor.fetchone()
            price, hold_time = result if result else (2.0, 5)
        
        settings_text = (
            "<b>⚙️ Настройки оплаты</b>\n\n"
            f"Текущая ставка: <code>{price}$</code> за номер\n"
            f"Время холда: <code>{hold_time}</code> минут\n\n"
            "Выберите параметр для изменения:"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Изменить сумму", callback_data="change_amount"))
        markup.add(types.InlineKeyboardButton("⏱ Изменить время холда", callback_data="change_hold_time"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        bot.edit_message_text(settings_text,
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "change_amount")
def change_amount_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("💰 Введите новую сумму оплаты (в долларах, например: 2):",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_change_amount)


def process_change_amount(message):
    if message.from_user.id in config.ADMINS_ID:
        try:
            new_amount = float(message.text)
            if new_amount <= 0:
                raise ValueError
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE settings SET PRICE = ?', (new_amount,))
                conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, f"✅ Сумма оплаты изменена на {new_amount}$", reply_markup=markup)
        except ValueError:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ Введите корректное положительное число!", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data == "change_hold_time")
def change_hold_time_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("⏱ Введите новое время холда (в минутах, например: 5):",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_change_hold_time)

def process_change_hold_time(message):
    if message.from_user.id in config.ADMINS_ID:
        try:
            new_time = int(message.text)
            if new_time <= 0:
                raise ValueError
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE settings SET HOLD_TIME = ?', (new_time,))
                conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, f"✅ Время холда изменено на {new_time} минут", reply_markup=markup)
        except ValueError:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ Введите корректное положительное целое число!", reply_markup=markup)






#  КОД ДЛЯ ПРИНЯТИЕ ОТКАЗА ЗАЯВОК В БОТА

@bot.callback_query_handler(func=lambda call: call.data.startswith("pending_requests"))
def show_pending_requests(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра заявок!")
        return
    
    page = 1
    if "_" in call.data:
        try:
            page = int(call.data.split("_")[1])
            if page < 1:
                page = 1
        except (IndexError, ValueError):
            page = 1

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID, LAST_REQUEST FROM requests WHERE STATUS = "pending"')
        requests = cursor.fetchall()
    
    if not requests:
        text = "📭 Нет заявок на вступление."
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
        return
    
    # Пагинация
    items_per_page = 20
    total_pages = (len(requests) + items_per_page - 1) // items_per_page
    page = max(1, min(page, total_pages))
    start_idx = (page - 1) * items_per_page
    end_idx = start_idx + items_per_page
    page_requests = requests[start_idx:end_idx]
    
    text = f"<b>📝 Заявки на вступление (страница {page}/{total_pages}):</b>\n\n"
    markup = types.InlineKeyboardMarkup()
    
    for user_id, last_request in page_requests:
        try:
            user = bot.get_chat_member(user_id, user_id).user
            username = f"@{user.username}" if user.username else "Нет username"
        except:
            username = "Неизвестный пользователь"
        
        text += (
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Username: {username}\n"
            f"📅 Дата заявки: {last_request}\n"
            f"────────────────────\n"
        )
        
        markup.row(
            types.InlineKeyboardButton(f"✅ Одобрить {user_id}", callback_data=f"approve_user_{user_id}"),
            types.InlineKeyboardButton(f"❌ Отклонить {user_id}", callback_data=f"reject_user_{user_id}")
        )
    
    # Проверяем лимит символов
    TELEGRAM_MESSAGE_LIMIT = 4096
    if len(text) > TELEGRAM_MESSAGE_LIMIT:
        text = text[:TELEGRAM_MESSAGE_LIMIT - 100] + "\n... (Сообщение обрезано, используйте пагинацию)"
    
    # Кнопки пагинации
    if total_pages > 1:
        row = []
        if page > 1:
            row.append(types.InlineKeyboardButton("⬅️ Назад", callback_data=f"pending_requests_{page-1}"))
        row.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
        if page < total_pages:
            row.append(types.InlineKeyboardButton("Вперёд ➡️", callback_data=f"pending_requests_{page+1}"))
        if row:
            markup.row(*row)
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    try:
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=markup)
    except:
        bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)














#=============================================================================================================

def check_number_timeout():
    while True:
        try:
            with db.get_db() as conn:
                cursor = conn.cursor()
                # Ищем номера, которые взяты модератором (TAKE_DATE не "0" и не "1"),
                # но не имеют статуса "активен" или "отстоял"
                cursor.execute('''
                    SELECT NUMBER, ID_OWNER, TAKE_DATE, MODERATOR_ID, GROUP_CHAT_ID
                    FROM numbers
                    WHERE TAKE_DATE NOT IN ("0", "1")
                    AND STATUS NOT IN ("активен", "отстоял")
                ''')
                numbers = cursor.fetchall()

                current_time = datetime.now()
                for number, owner_id, take_date, moderator_id, group_chat_id in numbers:
                    try:
                        take_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                        time_diff = (current_time - take_time).total_seconds() / 60  # Разница в минутах

                        if time_diff >= 10:  # Если прошло 10 минут или больше
                            # Сбрасываем номер в очередь
                            cursor.execute('''
                                UPDATE numbers
                                SET TAKE_DATE = "0",
                                    MODERATOR_ID = NULL,
                                    GROUP_CHAT_ID = NULL,
                                    VERIFICATION_CODE = NULL
                                WHERE NUMBER = ?
                            ''', (number,))
                            conn.commit()

                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton("📱 Сдать номер снова", callback_data="submit_number"))
                            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                            try:
                                bot.send_message(
                                    owner_id,
                                    f"❌ Ваш номер {number} был не обработан модератором в течение 10 минут.\n"
                                    "📱 Он снова в очереди.",
                                    reply_markup=markup
                                )
                                print(f"Сообщение отправлено владельцу {owner_id}")
                            except Exception as e:
                                print(f"Ошибка при отправке сообщения владельцу {owner_id}: {e}")

                            # Уведомляем модератора
                            if moderator_id:
                                markup_mod = types.InlineKeyboardMarkup()
                                markup_mod.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
                                markup_mod.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                                try:
                                    target_chat_id = group_chat_id if group_chat_id else moderator_id
                                    bot.send_message(
                                        target_chat_id,
                                        f"❌ Номер {number} был возвращён в очередь, так как вы не обработали его в течение 10 минут.",
                                        reply_markup=markup_mod
                                    )
                                except Exception as e:
                                    print(f"Ошибка при отправке сообщения модератору {moderator_id}: {e}")

                    except Exception as e:
                        print(f"Ошибка при обработке номера {number}: {e}")
                        continue

        except Exception as e:
            print(f"Ошибка в check_number_timeout: {e}")

        time.sleep(30)  # Проверяем каждые 30 секунд


# Запускаем фоновую задачу
timeout_thread = threading.Thread(target=check_number_timeout, daemon=True)
timeout_thread.start()

















def check_number_hold_time():
    while True:
        try:
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT HOLD_TIME FROM settings')
                result = cursor.fetchone()
                hold_time = result[0] if result else 5  # Устанавливаем значение по умолчанию, если пусто

                cursor.execute('SELECT PRICE FROM settings')
                result = cursor.fetchone()
                price = result[0] if result else 2.0  # Устанавливаем значение по умолчанию, если пусто

                # Ищем номера со статусом "активен" и валидной датой активации
                cursor.execute('''
                    SELECT NUMBER, ID_OWNER, TAKE_DATE, MODERATOR_ID, GROUP_CHAT_ID
                    FROM numbers
                    WHERE STATUS = "активен" AND TAKE_DATE NOT IN ("0", "1")
                ''')
                numbers = cursor.fetchall()

                current_time = datetime.now()
                for number, owner_id, take_date, moderator_id, group_chat_id in numbers:
                    try:
                        take_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                        work_time = (current_time - take_time).total_seconds() / 60  # Время работы в минутах

                        if work_time >= hold_time:
                            # Номер отстоял своё время
                            shutdown_date = current_time.strftime("%Y-%m-%d %H:%M:%S")
                            cursor.execute('''
                                UPDATE numbers
                                SET STATUS = "отстоял",
                                    SHUTDOWN_DATE = ?
                                WHERE NUMBER = ?
                            ''', (shutdown_date, number))
                            conn.commit()

                            # Начисляем оплату владельцу
                            db.update_balance(owner_id, price)
                            markup = types.InlineKeyboardMarkup()
                            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                            bot.send_message(
                                owner_id,
                                f"✅ Ваш номер {number} проработал {work_time:.1f} минут!\n"
                                f"💵 Вам начислено: ${price}\n"
                                f"🟢 Статус: отстоял",
                                reply_markup=markup
                            )

                            # Уведомляем модератора
                            if moderator_id:
                                markup_mod = types.InlineKeyboardMarkup()
                                markup_mod.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
                                markup_mod.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                                try:
                                    target_chat_id = group_chat_id if group_chat_id else moderator_id
                                    bot.send_message(
                                        target_chat_id,
                                        f"✅ Номер {number} успешно отстоял {hold_time} минут.\n"
                                        f"🟢 Статус: отстоял",
                                        reply_markup=markup_mod
                                    )
                                except Exception as e:
                                    print(f"Ошибка при отправке сообщения модератору {moderator_id}: {e}")

                    except Exception as e:
                        print(f"Ошибка при обработке номера {number}: {e}")
                        continue

        except Exception as e:
            print(f"Ошибка в check_number_hold_time: {e}")

        time.sleep(30)  # Проверяем каждые 30 секунд







































































#КОД ДЛЯ РЕАГИРОВАНИЙ НУ ну Тг тг
@bot.message_handler(content_types=['text'], func=lambda message: message.chat.type in ['group', 'supergroup'])
def handle_group_commands(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.lower().strip()

    if chat_id not in config.GROUP_IDS:
        return

    tg_pattern = r'^тг(\d{1,2})$'
    match = re.match(tg_pattern, text)
    if match:
        tg_number = int(match.group(1))
        if 1 <= tg_number <= 70:
            get_number_in_group(user_id, chat_id, message.message_id, tg_number)
            

def get_number_in_group(user_id, chat_id, message_id, tg_number):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT n.NUMBER 
            FROM numbers n
            LEFT JOIN personal p ON p.ID = n.ID_OWNER
            WHERE n.TAKE_DATE = "0" 
            AND (p.GROUP_ID = (SELECT GROUP_ID FROM personal WHERE ID = ?) OR p.GROUP_ID IS NULL)
            LIMIT 1
        ''', (user_id,))
        number = cursor.fetchone()
        
        if number:
            number = number[0]
            cursor.execute('UPDATE numbers SET TAKE_DATE = ?, MODERATOR_ID = ?, GROUP_CHAT_ID = ? WHERE NUMBER = ?',
                          (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id, chat_id, number))
            conn.commit()
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✉️ Отправить код", callback_data=f"send_code_{number}_{chat_id}_{tg_number}"),
                types.InlineKeyboardButton("❌ Номер невалидный", callback_data=f"invalid_{number}")
            )
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            
            bot.send_message(
                chat_id,
                f"📱 <b>ТГ {tg_number}</b>\n"
                f"📱 Новый номер для проверки: <code>{number}</code>\n"
                "Ожидайте код от владельца или отметьте номер как невалидный.",
                parse_mode='HTML',
                reply_markup=markup,
                reply_to_message_id=message_id
            )
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(
                chat_id,
                f"📭 Нет доступных номеров для проверки (ТГ {tg_number}).",
                parse_mode='HTML',
                reply_markup=markup,
                reply_to_message_id=message_id
            )


@bot.callback_query_handler(func=lambda call: call.data.startswith("send_code_"))
def send_verification_code(call):
    try:
        parts = call.data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
            return
        number = parts[2]
        group_chat_id = int(parts[3])
        tg_number = int(parts[4]) if len(parts) > 4 else 1
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
            owner = cursor.fetchone()
        
        if owner:
            owner_id = owner[0]
            try:
                markup = types.ReplyKeyboardRemove()
                msg = bot.send_message(
                    owner_id,
                    "=================\n"
                    f"📱 Введите код для номера {number}, который будет отправлен модератору: (Используйте ответить на сообщение)",
                    reply_markup=markup
                )
                bot.edit_message_text(
                    f"📱 <b>ТГ {tg_number}</b>\n"
                    f"📱 Номер: {number}\n✉️ Запрос кода отправлен владельцу.",
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='HTML'
                )
                
                with db.get_db() as conn:
                    cursor = conn.cursor()
                    cursor.execute('UPDATE numbers SET VERIFICATION_CODE = "" WHERE NUMBER = ?', (number,))
                    cursor.execute('UPDATE numbers SET MODERATOR_ID = ?, GROUP_CHAT_ID = ? WHERE NUMBER = ?', 
                                  (call.from_user.id, group_chat_id, number))
                    conn.commit()
                
                # Регистрируем запрос кода
                if owner_id not in active_code_requests:
                    active_code_requests[owner_id] = {}
                active_code_requests[owner_id][number] = msg.message_id
                
                bot.register_next_step_handler(
                    msg,
                    process_verification_code_input,
                    number,
                    call.from_user.id,
                    group_chat_id,
                    msg.chat.id,
                    msg.message_id,
                    tg_number
                )
            except telebot.apihelper.ApiTelegramException as e:
                if e.error_code == 403 and "user is deactivated" in e.description:
                    bot.answer_callback_query(call.id, "❌ Пользователь деактивирован, невозможно отправить сообщение!")
                    with db.get_db() as conn:
                        cursor = conn.cursor()
                        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
                        conn.commit()
                    # Удаляем запрос из active_code_requests
                    if owner_id in active_code_requests and number in active_code_requests[owner_id]:
                        del active_code_requests[owner_id][number]
                        if not active_code_requests[owner_id]:
                            del active_code_requests[owner_id]
                else:
                    raise e
        else:
            bot.answer_callback_query(call.id, "❌ Владелец номера не найден!")
    
    except Exception as e:
        print(f"Ошибка в send_verification_code: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка!")

# Глобальный словарь для отслеживания активных запросов кодов по user_id
active_code_requests = {}

def process_verification_code_input(message, number, moderator_id, group_chat_id, original_chat_id, original_message_id, tg_number):
    try:
        user_id = message.from_user.id

        # Проверяем, что сообщение является ответом на запрос кода
        if not message.reply_to_message or \
           message.reply_to_message.chat.id != original_chat_id or \
           message.reply_to_message.message_id != original_message_id:
            # Если не ответ, просто запрашиваем код заново
            markup = types.ReplyKeyboardRemove()
            msg = bot.send_message(
                message.chat.id,
                "=================\n"
                f"📱 Введите 5-значный код для номера {number} (например, 12345): (Ответьте на это сообщение)",
                reply_markup=markup
            )
            bot.register_next_step_handler(
                msg,
                process_verification_code_input,
                number,
                moderator_id,
                group_chat_id,
                msg.chat.id,
                msg.message_id,
                tg_number
            )
            return

        user_input = message.text.strip()

        # Проверяем, что код — это ровно 5 цифр
        if not re.match(r'^\d{5}$', user_input):
            # Если код не 5 цифр, запрашиваем заново
            markup = types.ReplyKeyboardRemove()
            msg = bot.send_message(
                message.chat.id,
                "=================\n"
                f"📱 Введите 5-значный код для номера {number} (например, 12345): (Ответьте на это сообщение)",
                reply_markup=markup
            )
            bot.register_next_step_handler(
                msg,
                process_verification_code_input,
                number,
                moderator_id,
                group_chat_id,
                msg.chat.id,
                msg.message_id,
                tg_number
            )
            return

        # Успешный ввод кода
        # Удаляем сообщения
        try:
            bot.delete_message(original_chat_id, original_message_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения бота: {e}")

        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения пользователя: {e}")

        # Сохраняем код в базе
        with db.get_db() as conn:
            cursor = conn.cursor()
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('UPDATE numbers SET VERIFICATION_CODE = ?, TAKE_DATE = ? WHERE NUMBER = ?', 
                          (user_input, current_date, number))
            conn.commit()

        # Отправляем подтверждение владельцу
        markup = types.InlineKeyboardMarkup()
        confirmation_msg = bot.send_message(
            message.chat.id,
            f"Вы ввели код: {user_input} для номера {number}\nЭто правильный код?",
            reply_markup=markup
        )
        markup.add(
            types.InlineKeyboardButton(
                "✅ Да, код верный",
                callback_data=f"confirm_code_{number}_{user_input}_{group_chat_id}_{message.chat.id}_{confirmation_msg.message_id}_{tg_number}"
            ),
            types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"change_code_{number}_{group_chat_id}_{tg_number}")
        )
        bot.edit_message_reply_markup(
            message.chat.id,
            confirmation_msg.message_id,
            reply_markup=markup
        )

        # После успешного ввода кода отменяем все остальные запросы для этого пользователя
        if user_id in active_code_requests:
            for other_number in active_code_requests[user_id].copy():
                if other_number != number:
                    try:
                        # Удаляем сообщения других запросов
                        other_msg_id = active_code_requests[user_id][other_number]
                        bot.delete_message(user_id, other_msg_id)
                    except Exception as e:
                        print(f"Ошибка при удалении сообщения для номера {other_number}: {e}")
            # Очищаем все запросы для пользователя
            active_code_requests[user_id] = {}

    except Exception as e:
        print(f"Ошибка в process_verification_code_input: {e}")
        # Если ошибка, не отправляем повторные запросы для других номеров
        bot.send_message(
            message.chat.id,
            f"📱 Произошла ошибка при обработке кода для номера {number}. Попробуйте снова.",
            parse_mode='HTML'
        )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_code_"))
def confirm_code(call):
    try:    
        parts = call.data.split("_")
        if len(parts) < 7:
            bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
            return
        
        number = parts[2]
        code = parts[3]
        group_chat_id = int(parts[4])
        confirmation_chat_id = int(parts[5])
        confirmation_message_id = int(parts[6])
        tg_number = int(parts[7])
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT MODERATOR_ID, GROUP_CHAT_ID FROM numbers WHERE NUMBER = ?', (number,))
            result = cursor.fetchone()
            if not result:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            moderator_id, stored_chat_id = result
        
        try:    
            bot.edit_message_text(
                f"✅ Код '{code}' для номера {number}   (ТГ {tg_number}) отправлен модератору.",
                confirmation_chat_id,
                confirmation_message_id,
                parse_mode='HTML'
            )
        except Exception as e:
            print(f"Ошибка при редактировании сообщения: {e}")
            bot.answer_callback_query(call.id, "❌ Не удалось обновить сообщение!")
            return
        
        bot.answer_callback_query(call.id)
        
        if moderator_id:
            target_chat_id = stored_chat_id if stored_chat_id else moderator_id
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Да, встал", callback_data=f"number_active_{number}_{tg_number}"),
                types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"number_invalid_{number}_{tg_number}")
            )
            bot.send_message(
                target_chat_id,
                f"📱 <b>ТГ {tg_number}</b>\n"
                f"📱 Код по номеру {number}\nКод: {code}\n\nВстал ли номер?",
                reply_markup=markup,
                parse_mode='HTML'
            )
    
    except Exception as e:
        print(f"Ошибка в confirm_code: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при подтверждении кода!")






@bot.callback_query_handler(func=lambda call: call.data == "get_number")
def get_number(call):
    user_id = call.from_user.id
    if not db.is_moderator(user_id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав для получения номера!")
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT n.NUMBER 
            FROM numbers n
            LEFT JOIN personal p ON p.ID = n.ID_OWNER
            WHERE n.TAKE_DATE = "0" 
            AND (p.GROUP_ID = (SELECT GROUP_ID FROM personal WHERE ID = ?) OR p.GROUP_ID IS NULL)
            LIMIT 1
        ''', (user_id,))
        number = cursor.fetchone()
        
        if number:
            number = number[0]
            cursor.execute('UPDATE numbers SET TAKE_DATE = ?, MODERATOR_ID = ?, GROUP_CHAT_ID = ? WHERE NUMBER = ?',
                          (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id, call.message.chat.id, number))
            conn.commit()
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✉️ Отправить код", callback_data=f"send_code_{number}_{call.message.chat.id}"),
                types.InlineKeyboardButton("❌ Номер невалидный", callback_data=f"invalid_{number}")
            )
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            
            bot.edit_message_text(
                f"📱 Новый номер для проверки: <code>{number}</code>\n"
                "Ожидайте код от владельца или отметьте номер как невалидный.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text(
                "📭 Нет доступных номеров для проверки.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=markup
            )


@bot.callback_query_handler(func=lambda call: call.data.startswith("change_code_"))
def change_code(call):
    try:
        parts = call.data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
            return
        
        number = parts[2]
        group_chat_id = int(parts[3])
        tg_number = int(parts[4])
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
            result = cursor.fetchone()
            if not result:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            moderator_id = result[0] if result else call.from_user.id

        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")

        markup = types.ReplyKeyboardRemove()
        msg = bot.send_message(
            call.from_user.id,
            "=================\n"
            f"📱 Введите новый код для номера {number} , который будет отправлен модератору: (Используйте ответить на сообщение)",
            reply_markup=markup
        )
        
        bot.register_next_step_handler(
            msg,
            process_verification_code_input,
            number,
            moderator_id,
            group_chat_id,
            msg.chat.id,
            msg.message_id,
            tg_number
        )
    
    except Exception as e:
        print(f"Ошибка в change_code: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при изменении кода!")

def create_back_to_main_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("code_entered_"))
def confirm_verification_code(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET VERIFICATION_CODE = NULL WHERE NUMBER = ?', (number,))
        cursor.execute('SELECT MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        moderator_id = cursor.fetchone()[0]
        conn.commit()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    bot.edit_message_text(f"✅ Код для номера {number}  отправлен модератору.", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

    if moderator_id:
        markup_mod = types.InlineKeyboardMarkup()
        markup_mod.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"moderator_confirm_{number}"),
            types.InlineKeyboardButton("❌ Не встал", callback_data=f"moderator_reject_{number}")
        )
        try:
            bot.send_message(moderator_id, 
                           f"📱 Номер {number} готов к подтверждению.\nПожалуйста, подтвердите или отклоните.", 
                           reply_markup=markup_mod)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("code_error_"))
def handle_verification_error(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        moderator_id = cursor.fetchone()[0]
        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
        conn.commit()
    
    bot.edit_message_text(f"❌ Номер {number} удалён из системы из-за ошибки в коде.", 
                         call.message.chat.id, 
                         call.message.message_id)

    for admin_id in config.ADMINS_ID:
        try:
            bot.send_message(admin_id, f"❌ Код был неправильный, номер {number} из очереди удалён.")
        except:
            pass

    if moderator_id:
        markup_mod = types.InlineKeyboardMarkup()
        markup_mod.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
        markup_mod.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        try:
            bot.send_message(moderator_id, 
                           f"❌ Номер {number} был удалён владельцем из-за ошибки в коде.", 
                           reply_markup=markup_mod)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("moderator_reject_"))
def handle_number_rejection(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
        conn.commit()

        if owner:
            markup_owner = types.InlineKeyboardMarkup()
            markup_owner.add(types.InlineKeyboardButton("📱 Сдать номер снова", callback_data="submit_number"))
            markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            try:
                bot.send_message(owner[0], 
                               f"❌ Ваш номер {number} был отклонен модератором.\n📱 Проверьте номер и сдайте заново.", 
                               reply_markup=markup_owner)
            except:
                pass

    markup_mod = types.InlineKeyboardMarkup()
    markup_mod.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
    markup_mod.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    bot.edit_message_text(f"📱 Номер {number} отклонен и удалён из очереди.\n❌ Номер не встал.", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup_mod)

@bot.callback_query_handler(func=lambda call: call.data.startswith("moderator_confirm_"))
def moderator_confirm_number(call):
    number = call.data.split("_")[2]
    user_id = call.from_user.id
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET STATUS = "активен", MODERATOR_ID = NULL, CONFIRMED_BY_MODERATOR_ID = ?, TAKE_DATE = ? WHERE NUMBER = ?', 
                      (user_id, current_date, number))
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        conn.commit()
        print(f"[DEBUG] Подтверждён номер: {number}, CONFIRMED_BY_MODERATOR_ID = {user_id}, TAKE_DATE = {current_date}")
    
    if owner:
        markup_owner = types.InlineKeyboardMarkup()
        markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(owner[0], 
                        f"✅ Ваш номер {number} подтвержден и поставлен в работу. Оплата будет начислена через 5 минут, если номер не слетит.",
                        reply_markup=markup_owner, parse_mode='HTML')
    
    # Обновляем сообщение модератора
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📋 Мои номера", callback_data="moderator_numbers"))
    bot.edit_message_text(
        f"📱 Номер {number} поставлен в работу. Оплата будет начислена через 5 минут, если номер не слетит.\nНажмите 'Мои номера' для обновления списка.",
        call.message.chat.id, 
        call.message.message_id, 
        reply_markup=markup, 
        parse_mode='HTML'
    )
    
    # Вызываем handle_moderator_numbers для немедленного обновления интерфейса
    try:
        new_call = types.CallbackQuery(
            id=call.id,
            from_user=call.from_user,
            message=call.message,
            chat_instance=call.chat_instance,
            data="moderator_numbers"
        )
        handle_moderator_numbers(new_call)
    except Exception as e:
        print(f"[ERROR] Не удалось обновить интерфейс: {e}")
        bot.answer_callback_query(call.id, "⚠️ Ошибка при обновлении списка номеров.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("number_active_"))
def number_active(call):
    try:
        number = call.data.split("_")[2]
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
            owner = cursor.fetchone()
            cursor.execute('UPDATE numbers SET STATUS = ?, CONFIRMED_BY_MODERATOR_ID = ? WHERE NUMBER = ?', 
                          ('активен', call.from_user.id, number))
            conn.commit()
        
        if owner:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(
                owner[0],
                f"✅ Ваш номер {number} подтверждён и теперь активен.\n⏳ Отсчёт времени начался.",
                reply_markup=markup,
                parse_mode='HTML'
            )
        
        bot.edit_message_text(
            f"✅ Номер {number} подтверждён.",
            call.message.chat.id,
            call.message.message_id
        )
        bot.answer_callback_query(call.id)
    
    except Exception as e:
        print(f"Ошибка в number_active: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при подтверждении номера!")
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("number_invalid_"))
def number_invalid(call):
    try:
        parts = call.data.split("_")
        if len(parts) < 4:
            bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
            return
        number = parts[2]
        tg_number = int(parts[3])
        
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("✉️ Отправить код заново", callback_data=f"send_code_{number}_{call.message.chat.id}_{tg_number}"),
            types.InlineKeyboardButton("❌ Не валидный", callback_data=f"invalid_{number}")
        )
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_confirm_{number}"))
        
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception as e:
            print(f"Ошибка при удалении сообщения: {e}")
        
        bot.send_message(
            call.message.chat.id,
            f"📱 <b>ТГ {tg_number}</b>\n"
            f"📱 Номер: {number}\nПожалуйста, выберите действие:",
            reply_markup=markup,
            parse_mode='HTML'
        )
    
    except Exception as e:
        print(f"Ошибка в number_invalid: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке номера.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("back_to_confirm_"))
def back_to_confirm(call):
    try:
        print(f"Callback data received: {call.data}")  # Отладочный вывод
        # Извлекаем номер, взяв всё после "back_to_confirm_"
        prefix = "back_to_confirm_"
        if not call.data.startswith(prefix):
            bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
            return
        
        number = call.data[len(prefix):]  # Берем всё после префикса
        print(f"Extracted number: {number}")  # Отладочный вывод
        
        # Проверяем, существует ли номер в базе данных
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ID_OWNER, VERIFICATION_CODE, TAKE_DATE FROM numbers WHERE NUMBER = ?', (number,))
            result = cursor.fetchone()
            
            # Если номер не найден в базе данных
            if not result:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception as e:
                    print(f"Ошибка при удалении сообщения: {e}")
                
                bot.send_message(
                    call.message.chat.id,
                    f"❌ Номер {number} больше недоступен (возможно, он был удалён или отклонён).\nПожалуйста, получите новый номер.",
                    reply_markup=markup
                )
                return
            
            owner_id, code, take_date = result
            
            # Если код уже отправлен владельцем
            if code and take_date != "0":
                # Формируем сообщение "Встал ли номер?"
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    types.InlineKeyboardButton("✅ Да, встал", callback_data=f"number_active_{number}"),
                    types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"number_invalid_{number}")
                )
                
                # Удаляем старое сообщение
                try:
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                except Exception as e:
                    print(f"Ошибка при удалении сообщения: {e}")
                
                # Отправляем сообщение заново
                bot.send_message(
                    call.message.chat.id,
                    f"📱 Код по номеру {number}\nКод: {code}\n\nВстал ли номер?",
                    reply_markup=markup
                )
            else:
                # Если код ещё не отправлен или номер в состоянии ожидания
                if owner_id:
                    if take_date == "0":
                        # Если модератор ещё не запросил код
                        markup = types.InlineKeyboardMarkup()
                        markup.add(
                            types.InlineKeyboardButton("✉️ Отправить код", callback_data=f"send_code_{number}_{call.message.chat.id}"),
                            types.InlineKeyboardButton("❌ Номер невалидный", callback_data=f"invalid_{number}")
                        )
                        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                        
                        try:
                            bot.delete_message(call.message.chat.id, call.message.message_id)
                        except Exception as e:
                            print(f"Ошибка при удалении сообщения: {e}")
                        
                        bot.send_message(
                            call.message.chat.id,
                            f"📱 Новый номер для проверки: <code>{number}</code>\n"
                            "Ожидайте код от владельца или отметьте номер как невалидный.",
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                    else:
                        # Если код уже запрошен, но ещё не получен
                        try:
                            markup = types.ReplyKeyboardRemove()
                            msg = bot.send_message(
                                owner_id,
                                "=================\n"
                                f"📱 Введите код для номера {number}, который будет отправлен модератору: (Используйте ответить на сообщение)",
                                reply_markup=markup
                            )
                            
                            try:
                                bot.delete_message(call.message.chat.id, call.message.message_id)
                            except Exception as e:
                                print(f"Ошибка при удалении сообщения: {e}")
                            
                            bot.send_message(
                                call.message.chat.id,
                                f"📱 Номер: {number}\n✉️ Запрос кода отправлен владельцу.",
                                parse_mode='HTML'
                            )
                            
                            with db.get_db() as conn:
                                cursor = conn.cursor()
                                cursor.execute('UPDATE numbers SET VERIFICATION_CODE = "" WHERE NUMBER = ?', (number,))
                                cursor.execute('UPDATE numbers SET MODERATOR_ID = ?, GROUP_CHAT_ID = ? WHERE NUMBER = ?', 
                                            (call.from_user.id, call.message.chat.id, number))
                                conn.commit()
                            
                            bot.register_next_step_handler(
                                msg,
                                process_verification_code_input,
                                number,
                                call.from_user.id,
                                call.message.chat.id,
                                msg.chat.id,
                                msg.message_id
                            )
                        except telebot.apihelper.ApiTelegramException as e:
                            if e.error_code == 403 and "user is deactivated" in e.description:
                                bot.answer_callback_query(call.id, "❌ Пользователь деактивирован, невозможно отправить сообщение!")
                                # Удаляем номер из базы
                                with db.get_db() as conn:
                                    cursor = conn.cursor()
                                    cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
                                    conn.commit()
                            else:
                                raise e
                else:
                    # Если владелец не найден, но номер существует
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
                    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                    
                    try:
                        bot.delete_message(call.message.chat.id, call.message.message_id)
                    except Exception as e:
                        print(f"Ошибка при удалении сообщения: {e}")
                    
                    bot.send_message(
                        call.message.chat.id,
                        f"❌ Владелец номера {number} не найден. Номер больше недоступен.\nПожалуйста, получите новый номер.",
                        reply_markup=markup
                    )
    
    except Exception as e:
        print(f"Ошибка в back_to_confirm: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при возврате к подтверждению!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("moderator_number_"))
def show_number_details(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS, TAKE_DATE, SHUTDOWN_DATE, MODERATOR_ID, CONFIRMED_BY_MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        data = cursor.fetchone()

    if data:
        status, take_date, shutdown_date, moderator_id, confirmed_by_moderator_id = data
        text = (f"📱 <b>Статус номера:</b> {status}\n"
                f"📱 <b>Номер:</b> {number}\n")
        if take_date not in ("0", "1"):
            text += f"🟢 <b>Встал:</b> {take_date}\n"
        if shutdown_date != "0":
            if status == "отстоял":
                text += f"🟢 <b>Отстоял:</b> {shutdown_date}\n"
            else:
                text += f"❌ <b>Слетел:</b> {shutdown_date}\n"

        markup = types.InlineKeyboardMarkup()
        if shutdown_date == "0" and (moderator_id == call.from_user.id or confirmed_by_moderator_id == call.from_user.id):
            markup.add(types.InlineKeyboardButton("🔴 Слетел", callback_data=f"number_failed_{number}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="moderator_numbers"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("number_failed_"))
def handle_number_failed(call):
    number = call.data.split("_")[2]
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT TAKE_DATE, ID_OWNER, CONFIRMED_BY_MODERATOR_ID, STATUS FROM numbers WHERE NUMBER = ?', (number,))
            data = cursor.fetchone()
            if not data:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            
            take_date, owner_id, confirmed_by_moderator_id, status = data
            
            if status == "отстоял":
                bot.answer_callback_query(call.id, "✅ Номер уже отстоял своё время!")
                return

            cursor.execute('SELECT HOLD_TIME FROM settings')
            result = cursor.fetchone()
            hold_time = result[0] if result else 5
            
            end_time = datetime.now()
            if take_date in ("0", "1"):
                work_time = 0
                worked_enough = False
            else:
                start_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                work_time = (end_time - start_time).total_seconds() / 60
                worked_enough = work_time >= hold_time
            
            shutdown_date = end_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('UPDATE numbers SET SHUTDOWN_DATE = ?, STATUS = "слетел" WHERE NUMBER = ?', 
                          (shutdown_date, number))
            conn.commit()
        
        mod_message = (
            f"📱 Номер: {number}\n"
            f"📊 Статус: слетел\n"
        )
        if take_date not in ("0", "1"):
            mod_message += f"🟢 Встал: {take_date}\n"
        mod_message += f"🔴 Слетел: {shutdown_date}\n"
        if not worked_enough:
            mod_message += f"⚠️ Номер не отработал минимальное время ({hold_time} минут)!\n"
        mod_message += f"⏳ Время работы: {work_time:.2f} минут"
        
        owner_message = (
            f"❌ Ваш номер {number} слетел.\n"
            f"📱 Номер: {number}\n"
            f"📊 Статус: слетел\n"
        )
        if take_date not in ("0", "1"):
            owner_message += f"🟢 Встал: {take_date}\n"
        owner_message += f"🔴 Слетел: {shutdown_date}\n"
        if not worked_enough:
            owner_message += f"⏳ Время работы: {work_time:.2f} минут"
        
        bot.send_message(owner_id, owner_message, parse_mode='HTML')
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="moderator_numbers"))
        bot.edit_message_text(mod_message, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')
    
    except Exception as e:
        print(f"Ошибка в handle_number_failed: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке номера.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("invalid_"))
def handle_invalid_number(call):
    number = call.data.split("_")[1]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
        conn.commit()

        if owner:
            markup_owner = types.InlineKeyboardMarkup()
            markup_owner.add(types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number"))
            markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            try:
                bot.send_message(owner[0], 
                               f"❌ Ваш номер был отклонен модератором.\n📱 Проверьте номер и сдайте заново.", 
                               reply_markup=markup_owner)
            except:
                pass

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"))
    types.InlineKeyboardButton("📱 Мои номера", callback_data="moderator_numbers")
    bot.edit_message_text("✅ Номер успешно удален из системы", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

def is_russian_number(phone_number):
    phone_number = phone_number.strip()
    if phone_number.startswith("7") or phone_number.startswith("8"):
        phone_number = "+7" + phone_number[1:]
    if not phone_number.startswith("+"):
        phone_number = "+" + phone_number
    pattern = r'^\+7\d{10}$'
    return phone_number if bool(re.match(pattern, phone_number)) else None


@bot.callback_query_handler(func=lambda call: call.data == "submit_number")
def submit_number(call):
    user_id = call.from_user.id 
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT CAN_SUBMIT_NUMBERS FROM requests WHERE ID = ?', (user_id,))
        user = cursor.fetchone()
        if user and user[0] == 0:
            bot.answer_callback_query(call.id, "🚫 Вам запрещено сдавать номера!")
            return
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    msg = bot.send_message(
        call.message.chat.id,
        f"📱 Введите ваши номера телефона (по одному в строке):\nПример:\n+79991234567\n+79001234567\n+79021234567\n💵 Текущая цена: {price}$ за номер\n⏱ Холд: {hold_time} минут",
        reply_markup=markup,
        parse_mode='HTML'
    )
    bot.register_next_step_handler(msg, process_numbers)
def process_numbers(message):
    if not message or not message.text:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Попробовать снова", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, "❌ Пожалуйста, отправьте номера текстом!", reply_markup=markup)
        return

    numbers = message.text.strip().split('\n')
    if not numbers or all(not num.strip() for num in numbers):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Попробовать снова", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, "❌ Вы не указали ни одного номера!", reply_markup=markup)
        return

    valid_numbers = []
    invalid_numbers = []
    
    for number in numbers:
        number = number.strip()
        if not number:
            continue
        corrected_number = is_russian_number(number)
        if corrected_number:
            valid_numbers.append(corrected_number)
        else:
            invalid_numbers.append(number)

    if not valid_numbers:
        response_text = "❌ Все введённые номера некорректны!\nПожалуйста, вводите номера в формате +79991234567."
        if invalid_numbers:
            response_text += "\n\n❌ Неверный формат:\n" + "\n".join(invalid_numbers)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Попробовать снова", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, response_text, reply_markup=markup, parse_mode='HTML')
        return

    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            success_count = 0
            already_exists = 0
            successfully_added = []

            for number in valid_numbers:
                try:
                    cursor.execute('SELECT NUMBER, SHUTDOWN_DATE FROM numbers WHERE NUMBER = ?', (number,))
                    existing_number = cursor.fetchone()

                    if existing_number:
                        if existing_number[1] == "0":
                            already_exists += 1
                            continue
                        else:
                            cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))

                    cursor.execute('INSERT INTO numbers (NUMBER, ID_OWNER, TAKE_DATE, SHUTDOWN_DATE, STATUS) VALUES (?, ?, ?, ?, ?)',
                                  (number, message.from_user.id, '0', '0', 'ожидает'))
                    success_count += 1
                    successfully_added.append(number)
                except sqlite3.IntegrityError:
                    already_exists += 1
                    continue
            conn.commit()

        response_text = "<b>📊 Результат добавления номеров:</b>\n\n"
        if success_count > 0:
            response_text += f"✅ Успешно добавлено: {success_count} номеров\n"
            response_text += "📱 Добавленные номера:\n" + "\n".join(successfully_added) + "\n"
        if already_exists > 0:
            response_text += f"⚠️ Уже существуют: {already_exists} номеров\n"
        if invalid_numbers:
            response_text += f"❌ Неверный формат:\n" + "\n".join(invalid_numbers) + "\n"

    except Exception as e:
        print(f"Ошибка в process_numbers: {e}")
        response_text = "❌ Произошла ошибка при добавлении номеров. Попробуйте снова."

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📱 Добавить ещё", callback_data="submit_number"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.send_message(message.chat.id, response_text, reply_markup=markup, parse_mode='HTML')


def init_db():
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Проверяем, существует ли столбец GROUP_CHAT_ID
        cursor.execute("PRAGMA table_info(numbers)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'GROUP_CHAT_ID' not in columns:
            try:
                cursor.execute("ALTER TABLE numbers ADD COLUMN GROUP_CHAT_ID INTEGER")
                conn.commit()
                print("Столбец GROUP_CHAT_ID успешно добавлен.")
            except sqlite3.OperationalError as e:
                print(f"Не удалось добавить столбец GROUP_CHAT_ID: {e}")
        else:
            print("Столбец GROUP_CHAT_ID уже существует.")

if __name__ == "__main__":
    init_db()
    timeout_thread = threading.Thread(target=check_number_timeout, daemon=True)
    timeout_thread.start()
    hold_time_thread = threading.Thread(target=check_number_hold_time, daemon=True)
    hold_time_thread.start()
    run_bot()
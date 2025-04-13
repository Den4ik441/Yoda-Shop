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
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        cursor.execute('SELECT LAST_REQUEST, STATUS FROM requests WHERE ID = ?', (user_id,))
        request = cursor.fetchone()
        
        if request and request[1] == 'approved':
            show_main_menu(message)
            return
        
        if request:
            last_request_time = datetime.strptime(request[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_request_time < timedelta(minutes=15):
                time_left = 15 - ((datetime.now() - last_request_time).seconds // 60)
                bot.send_message(message.chat.id, 
                                f"⏳ Ожидайте подтверждения. Вы сможете отправить новый запрос через {time_left} минут.")
                return
        
        cursor.execute('INSERT OR REPLACE INTO requests (ID, LAST_REQUEST, STATUS) VALUES (?, ?, ?)',
                      (user_id, current_date, 'pending'))
        conn.commit()
        
        bot.send_message(message.chat.id, 
                        "👋 Здравствуйте! Ожидайте, пока вас впустят в бота.")
        
        username = f"@{message.from_user.username}" if message.from_user.username else "Нет username"
        admin_text = f"📝 Пользователь {user_id} {username} пытается зарегистрироваться в боте"
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Впустить в бота", callback_data=f"approve_user_{user_id}"),
            types.InlineKeyboardButton("❌ Отказать в доступе", callback_data=f"reject_user_{user_id}")
        )
        
        for admin_id in config.ADMINS_ID:
            try:
                bot.send_message(admin_id, admin_text, reply_markup=markup)
            except:
                continue


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
        except:
            bot.edit_message_text(f"✅ Пользователь {user_id} одобрен, но уведомление не доставлено",
                                 call.message.chat.id,
                                 call.message.message_id)
        bot.edit_message_text(f"✅ Пользователь {user_id} одобрен",
                             call.message.chat.id,
                             call.message.message_id)

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
        except:
            bot.edit_message_text(f"❌ Пользователь {user_id} отклонён, но уведомление не доставлено",
                                 call.message.chat.id,
                                 call.message.message_id)
        bot.edit_message_text(f"❌ Пользователь {user_id} отклонён",
                             call.message.chat.id,
                             call.message.message_id)
                             
def show_main_menu(message):
    user_id = message.from_user.id
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"[+] Новый пользователь зарегистрировался:")
    print(f"🆔 ID: {user_id}")
    print(f"👤 Имя: {message.from_user.first_name} {message.from_user.last_name or ''}")
    print(f"🔗 Username: @{message.from_user.username or 'нет'}")
    print(f"📅 Дата регистрации: {current_date}")
    print("-" * 40)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
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
            types.InlineKeyboardButton("📱 Мои номера", callback_data="moderator_numbers")
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
    with treasury_lock:
        if call.from_user.id in active_treasury_admins:
            del active_treasury_admins[call.from_user.id]
    
    user_id = call.from_user.id

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
    
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
            types.InlineKeyboardButton("📱 Мои номера", callback_data="moderator_numbers")
        )
    
    bot.edit_message_text(
        welcome_text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
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
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id
        
        with treasury_lock:
            current_time = datetime.now()
            inactive_admins = [aid for aid, time_accessed in active_treasury_admins.items() 
                              if (current_time - time_accessed).total_seconds() > 300]
            for inactive_admin in inactive_admins:
                if inactive_admin in active_treasury_admins:
                    del active_treasury_admins[inactive_admin]
            for aid, time_accessed in active_treasury_admins.items():
                if aid != admin_id and (current_time - time_accessed).total_seconds() < 300:
                    bot.answer_callback_query(call.id, "⚠️ Казна занята другим администратором! Попробуйте позже.", show_alert=True)
                    return
            
            active_treasury_admins[admin_id] = current_time
        
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
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                bot.answer_callback_query(call.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню казны.", show_alert=True)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
        
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                bot.send_message(message.chat.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню.", 
                                reply_markup=markup)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
        
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                bot.answer_callback_query(call.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню казны.", show_alert=True)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                bot.send_message(message.chat.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню.", 
                                reply_markup=markup)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                bot.answer_callback_query(call.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню казны.", show_alert=True)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
    timeout = timedelta(minutes=5)
    check_interval = 3
    check_counter = 0
    
    try:
        while datetime.now() - start_time < timeout:
            invoices_result = crypto_api.get_invoices(invoice_ids=[invoice_id])
            
            if invoices_result.get("ok", False):
                invoices = invoices_result.get("result", {}).get("items", [])
                
                if invoices and invoices[0].get("status") == "paid":
                    with treasury_lock:
                        if admin_id in active_treasury_admins:
                            new_balance = db_module.update_treasury_balance(amount)
                            
                            db_module.log_treasury_operation("Пополнение через Crypto Pay", amount, new_balance)
                            
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
                            except Exception as e:
                                print(f"Error updating payment confirmation message: {e}")
                    return
                
                elif invoices and invoices[0].get("status") == "expired":
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔄 Создать новый инвойс", callback_data=f"treasury_deposit_crypto_{amount}"))
                    markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
                    markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
                    
                    try:
                        bot.edit_message_text(
                            f"⏱ <b>Время ожидания оплаты истекло</b>\n\n"
                            f"Инвойс на сумму {amount}$ не был оплачен в течение 5 минут.\n"
                            f"Вы можете создать новый инвойс или пополнить казну вручную.",
                            chat_id,
                            message_id,
                            parse_mode='HTML',
                            reply_markup=markup
                        )
                    except Exception as e:
                        print(f"Error updating expired invoice message: {e}")
                    return
                
                check_counter += 1
                if check_counter % 10 == 0:
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
                    except Exception as e:
                        print(f"Error updating waiting message: {e}")
            
            time.sleep(check_interval)
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔄 Создать новый инвойс", callback_data=f"treasury_deposit_crypto_{amount}"))
        markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
        
        try:
            bot.edit_message_text(
                f"⏱ <b>Время ожидания оплаты истекло</b>\n\n"
                f"Инвойс на сумму {amount}$ не был оплачен в течение 5 минут.\n"
                f"Вы можете создать новый инвойс или пополнить казну вручную.",
                chat_id,
                message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        except Exception as e:
            print(f"Error updating final timeout message: {e}")
        
    except Exception as e:
        print(f"Error in check_invoice_payment thread: {e}")
        try:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("💵 Пополнить вручную", callback_data=f"treasury_deposit_manual_{amount}"))
            markup.add(types.InlineKeyboardButton("🔙 Назад к казне", callback_data="treasury"))
            
            bot.edit_message_text(
                f"❌ <b>Ошибка при проверке оплаты</b>\n\n"
                f"Произошла ошибка при проверке статуса оплаты.\n"
                f"Пожалуйста, пополните казну вручную, если вы уже произвели оплату.",
                chat_id,
                message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("treasury_deposit_manual_"))
def treasury_deposit_manual(call):
    if call.from_user.id in config.ADMINS_ID:
        admin_id = call.from_user.id
        
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                bot.answer_callback_query(call.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню казны.", show_alert=True)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
        
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                bot.answer_callback_query(call.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню казны.", show_alert=True)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
            
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
        
        with treasury_lock:
            if admin_id not in active_treasury_admins:
                bot.answer_callback_query(call.id, "⚠️ Ваша сессия работы с казной истекла. Пожалуйста, вернитесь в главное меню казны.", show_alert=True)
                return
            
            active_treasury_admins[admin_id] = datetime.now()
        
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
        bot.register_next_step_handler(msg, process_add_moder)
    else:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для назначения модератора!")

def process_add_moder(message):
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
                except:
                    pass
                bot.send_message(message.chat.id, "⚠️ Этот пользователь уже является модератором!", reply_markup=markup)
                return

            cursor.execute('SELECT COUNT(*) FROM groups')
            if cursor.fetchone()[0] == 0:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("➕ Создать группу", callback_data="create_group"))
                markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
                try:
                    bot.delete_message(message.chat.id, message.message_id)
                except:
                    pass
                bot.send_message(message.chat.id, "❌ Нет созданных групп! Сначала создайте группу.", reply_markup=markup)
                return

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        msg = bot.send_message(
            message.chat.id,
            f"👤 ID модератора: {new_moder_id}\n📝 Введите название группы для назначения:",
            reply_markup=markup
        )
        bot.register_next_step_handler(msg, process_assign_group, new_moder_id)

    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID пользователя (только цифры)", reply_markup=markup)

def process_assign_group(message, new_moder_id):
    group_name = message.text.strip()
    
    if not group_name:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
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

        if not group:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("➕ Создать группу", callback_data="create_group"))
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            try:
                bot.delete_message(message.chat.id, message.message_id)
            except:
                pass
            bot.send_message(message.chat.id, f"❌ Группа '{group_name}' не найдена! Создайте её или выберите существующую.", 
                            reply_markup=markup)
            return

        group_id = group[0]

        try:
            # Отправляем начальное сообщение админу
            initial_msg = bot.send_message(message.chat.id, f"👤 ID модератора: {new_moder_id}\n📝 Введите название группы для назначения:")
            # Удаляем начальное сообщение
            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.delete_message(message.chat.id, initial_msg.message_id)
            except:
                pass
            
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
    bot.register_next_step_handler(msg, process_create_group)

def process_create_group(message):
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
        
        # Удаляем введенное сообщение
        try:
            bot.delete_message(message.chat.id, message.message_id)
        except:
            pass
        
        # Показываем сообщение об успехе временно
        success_msg = bot.send_message(message.chat.id, f"✅ Группа '{group_name}' успешно создана!")
        
        # Планируем удаление сообщения об успехе и показ админ-панели через 2 секунды
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
def view_groups(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра групп!")
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT NAME FROM groups')
        groups = cursor.fetchall()
    
    if not groups:
        text = "📭 Нет созданных групп."
    else:
        text = "<b>📋 Список всех групп:</b>\n\n"
        for group in groups:
            text += f"👥 {group[0]}\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="groups"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except:
        pass
    bot.send_message(call.message.chat.id, text, parse_mode='HTML', reply_markup=markup)

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









#ВСЕ НОМЕРА КОТОРЫЕ ПОКАЗЫВАЮТСЯ У АДМИНИСТАТОРА 
@bot.callback_query_handler(func=lambda call: call.data == "all_numbers")
def all_numbers(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра номеров!")
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT n.NUMBER, n.TAKE_DATE, n.SHUTDOWN_DATE, n.ID_OWNER, g.NAME
            FROM numbers n
            LEFT JOIN personal p ON n.ID_OWNER = p.ID
            LEFT JOIN groups g ON p.GROUP_ID = g.ID
            WHERE n.TAKE_DATE != "0" AND n.TAKE_DATE != "1"
            ORDER BY n.TAKE_DATE DESC
        ''')
        numbers = cursor.fetchall()
    
    if not numbers:
        text = "📭 Нет обработанных номеров."
    else:
        text = "<b>📱 Список всех номеров:</b>\n\n"
        for number, take_date, shutdown_date, user_id, group_name in numbers:
            group_info = f"👥 Группа: {group_name}" if group_name else "👥 Группа: Не указана"
            user_info = f"🆔 Пользователь: {user_id}" if user_id else "🆔 Пользователь: Не указан"
            text += (
                f"📞 <code>{number}</code>\n"
                f"{user_info}\n"
                f"{group_info}\n"
                f"📅 Взят: {take_date}\n"
                f"📴 Отключён: {shutdown_date or 'Ещё активен'}\n\n"
            )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )

    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра номеров!")
        return
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT n.NUMBER, n.TAKE_DATE, n.SHUTDOWN_DATE, n.ID_OWNER, g.NAME
            FROM numbers n
            LEFT JOIN personal p ON n.ID_OWNER = p.ID
            LEFT JOIN groups g ON p.GROUP_ID = g.ID
            WHERE n.TAKE_DATE != "0" AND n.TAKE_DATE != "1"
            ORDER BY n.TAKE_DATE DESC
        ''')
        numbers = cursor.fetchall()
    
    if not numbers:
        text = "📭 Нет обработанных номеров."
    else:
        text = "<b>📱 Список всех номеров:</b>\n\n"
        for number, take_date, shutdown_date, user_id, group_name in numbers:
            group_info = f"👥 Группа: {group_name}" if group_name else "👥 Группа: Не указана"
            user_info = f"🆔 Пользователь: {user_id}" if user_id else "🆔 Пользователь: Не указан"
            text += (
                f"📞 <code>{number}</code>\n"
                f"{user_info}\n"
                f"{group_info}\n"
                f"📅 Взят: {take_date}\n"
                f"📴 Отключён: {shutdown_date or 'Ещё активен'}\n\n"
            )
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    
    bot.edit_message_text(
        text,
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML',
        reply_markup=markup
    )
@bot.callback_query_handler(func=lambda call: call.data == "my_numbers")
def show_my_numbers(call):
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE, STATUS FROM numbers WHERE ID_OWNER = ?', 
                          (call.from_user.id,))
            numbers = cursor.fetchall()

        if not numbers:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text("📭 У вас нет номеров.", 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup)
            return

        text = "<b>📋 Список твоих номеров:</b>\n\n"
        for number, take_date, shutdown_date, status in numbers:
            text += f"📱 Номер: {number}\n"
            text += f"📊 Статус: {status if status else 'Не указан'}\n"
            if take_date == "0":
                text += "⏳ Ожидает подтверждения\n"
            elif take_date == "1":
                text += "⏳ Ожидает код\n"
            else:
                text += f"🟢 Встал: {take_date}\n"
            if shutdown_date != "0":
                text += f"❌ Слетел: {shutdown_date}\n"
            text += "────────────────────\n"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')

    except Exception as e:
        print(f"Ошибка в show_my_numbers: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("❌ Произошла ошибка при получении списка номеров.", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)
        

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


























#КОД ДЛЯ РЕАГИРОВАНИЙ НУ ну Тг тг
@bot.message_handler(content_types=['text'], func=lambda message: message.chat.type in ['group', 'supergroup'])
def handle_group_commands(message):
    user_id = message.from_user.id
    chat_id = message.chat.id
    text = message.text.lower().strip()

    # Проверяем, является ли пользователь модератором


    # Проверяем, что сообщение отправлено в разрешённую группу
    if chat_id not in config.GROUP_IDS:
        return

    # Проверяем ключевые слова
    if text in ["тг", "номер", "tg", "number", "номера", "num", "н" "Тг", "тГ", "Номер", ]:
        # Запускаем процесс получения номера
        get_number_in_group(user_id, chat_id, message.message_id)


def get_number_in_group(user_id, chat_id, message_id):
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
                types.InlineKeyboardButton("✉️ Отправить код", callback_data=f"send_code_{number}_{chat_id}"),
                types.InlineKeyboardButton("❌ Номер невалидный", callback_data=f"invalid_{number}")
            )
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            
            bot.send_message(
                chat_id,
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
                "📭 Нет доступных номеров для проверки.",
                parse_mode='HTML',
                reply_markup=markup,
                reply_to_message_id=message_id
            )

@bot.callback_query_handler(func=lambda call: call.data.startswith("send_code_"))
def send_verification_code(call):
    try:
        parts = call.data.split("_")
        number = parts[2]
        group_chat_id = int(parts[3]) if len(parts) > 3 else call.message.chat.id
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
            owner = cursor.fetchone()
        
        if owner:
            markup = types.ReplyKeyboardRemove()
            msg = bot.send_message(
                owner[0],
                f"📱 Введите код для номера {number}, который будет отправлен модератору: (Используйте ответить на сообщение)",
                reply_markup=markup
            )
            bot.edit_message_text(
                f"📱 Номер: {number}\n✉️ Запрос кода отправлен владельцу.",
                call.message.chat.id,
                call.message.message_id
            )
                    
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE numbers SET VERIFICATION_CODE = "" WHERE NUMBER = ?', (number,))
                cursor.execute('UPDATE numbers SET MODERATOR_ID = ?, GROUP_CHAT_ID = ? WHERE NUMBER = ?', 
                              (call.from_user.id, group_chat_id, number))
                conn.commit()
            
            bot.register_next_step_handler(
                msg,
                process_verification_code_input,
                number,
                call.from_user.id,
                group_chat_id,
                msg.chat.id,
                msg.message_id
            )
        else:
            bot.answer_callback_query(call.id, "❌ Владелец номера не найден!")
    
    except Exception as e:
        print(f"Ошибка в send_verification_code: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка!")

import threading

def process_verification_code_input(message, number, moderator_id, group_chat_id, original_chat_id, original_message_id):
    try:
        # Проверяем, является ли сообщение реплаем на оригинальное
        if not message.reply_to_message or \
           message.reply_to_message.chat.id != original_chat_id or \
           message.reply_to_message.message_id != original_message_id:
            markup = types.ReplyKeyboardRemove()
            # Повторяем запрос, если пользователь не ответил через "Ответить"
            msg = bot.send_message(
                message.chat.id,
                f"📱 Введите код для номера {number}, который будет отправлен модератору: (Используйте ответить на сообщение)",
                reply_markup=markup
            )
            bot.register_next_step_handler(
                msg,
                process_verification_code_input,
                number,
                moderator_id,
                group_chat_id,
                msg.chat.id,
                msg.message_id
            )
            return

        user_input = message.text.strip()
        
        if not user_input:
            markup = types.ReplyKeyboardRemove()
            msg = bot.send_message(
                message.chat.id,
                "❌ Код не может быть пустым! Введите код (ответьте на исходное сообщение):",
                reply_markup=markup
            )
            # Удаляем сообщение об ошибке через 15 секунд
            def delete_error_message():
                try:
                    bot.delete_message(msg.chat.id, msg.message_id)
                    print(f"Deleted error message {msg.message_id} in chat {msg.chat.id}")
                except Exception as e:
                    print(f"Ошибка при удалении сообщения об ошибке: {e}")
            
            threading.Timer(15.0, delete_error_message).start()
            
            bot.register_next_step_handler(
                msg,
                process_verification_code_input,
                number,
                moderator_id,
                group_chat_id,
                original_chat_id,
                original_message_id
            )
            return

        # Удаляем сообщение бота и ответ пользователя
        try:
            bot.delete_message(original_chat_id, original_message_id)
            print(f"Deleted bot message {original_message_id} in chat {original_chat_id}")
        except Exception as e:
            print(f"Ошибка при удалении сообщения бота: {e}")

        try:
            bot.delete_message(message.chat.id, message.message_id)
            print(f"Deleted user message {message.message_id} in chat {message.chat.id}")
        except Exception as e:
            print(f"Ошибка при удалении сообщения пользователя: {e}")

        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE numbers SET VERIFICATION_CODE = ? WHERE NUMBER = ?', (user_input, number))
            conn.commit()

        markup = types.InlineKeyboardMarkup()
        # Передаем ID сообщения подтверждения
        confirmation_msg = bot.send_message(
            message.chat.id,
            f"Вы ввели код: {user_input} для номера {number}\nЭто правильный код?",
            reply_markup=markup
        )
        markup.add(
            types.InlineKeyboardButton(
                "✅ Да, код верный",
                callback_data=f"confirm_code_{number}_{user_input}_{group_chat_id}_{message.chat.id}_{confirmation_msg.message_id}"
            ),
            types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"change_code_{number}")
        )
        # Обновляем сообщение с кнопками
        bot.edit_message_reply_markup(
            message.chat.id,
            confirmation_msg.message_id,
            reply_markup=markup
        )
        print(f"Sent confirmation message {confirmation_msg.message_id} in chat {message.chat.id}")

    except Exception as e:
        print(f"Ошибка в process_verification_code_input: {e}")
        markup = types.ReplyKeyboardRemove()
        msg = bot.send_message(
            message.chat.id,
            "❌ Произошла ошибка! Попробуйте ответить на сообщение еще раз:",
            reply_markup=markup
        )
        # Удаляем сообщение об ошибке через 15 секунд
        def delete_error_message():
            try:
                bot.delete_message(msg.chat.id, msg.message_id)
                print(f"Deleted error message {msg.message_id} in chat {msg.chat.id}")
            except Exception as e:
                print(f"Ошибка при удалении сообщения об ошибке: {e}")
        
        threading.Timer(15.0, delete_error_message).start()
        
        bot.register_next_step_handler(
            msg,
            process_verification_code_input,
            number,
            moderator_id,
            group_chat_id,
            original_chat_id,
            original_message_id
        )



@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_code_"))
def confirm_code(call):
    try:
        print(f"Callback received: {call.data}")
        parts = call.data.split("_")
        if len(parts) < 6:
            print(f"Invalid callback_data format: {call.data}")
            bot.answer_callback_query(call.id, "❌ Неверный формат данных!")
            return
        
        number = parts[2]
        code = parts[3]
        group_chat_id = int(parts[4])
        confirmation_chat_id = int(parts[5])
        confirmation_message_id = int(parts[6])
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT MODERATOR_ID, GROUP_CHAT_ID FROM numbers WHERE NUMBER = ?', (number,))
            result = cursor.fetchone()
            if not result:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            moderator_id, stored_chat_id = result
        
        # Редактируем сообщение с подтверждением
        try:
            bot.edit_message_text(
                f"✅ Код '{code}' для номера {number} отправлен модератору.",
                confirmation_chat_id,
                confirmation_message_id,
                parse_mode='HTML'
            )
            print(f"Edited message {confirmation_message_id} in chat {confirmation_chat_id}")
        except Exception as e:
            print(f"Ошибка при редактировании сообщения: {e}")
            bot.answer_callback_query(call.id, "❌ Не удалось обновить сообщение!")
            return
        
        bot.answer_callback_query(call.id)  # Подтверждаем callback
        
        if moderator_id:
            # Определяем, куда отправлять сообщение: в ЛС модератору или в группу
            target_chat_id = stored_chat_id if stored_chat_id else moderator_id
            
            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("✅ Да, встал", callback_data=f"number_active_{number}"),
                types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"number_invalid_{number}")
            )
            bot.send_message(
                target_chat_id,
                f"📱 Код по номеру {number}\nКод: {code}\n\nВстал ли номер?",
                reply_markup=markup
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
    parts = call.data.split("_")
    number = parts[2]
    group_chat_id = int(parts[3]) if len(parts) > 3 else call.message.chat.id
    
    markup = types.ReplyKeyboardRemove()
    msg = bot.send_message(call.from_user.id, "Введите новый код:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_verification_code_input, number, call.from_user.id, group_chat_id)

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET VERIFICATION_CODE = "" WHERE NUMBER = ?', (number,))
        conn.commit()

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
    bot.edit_message_text(f"✅ Код для номера {number} отправлен модератору.", 
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
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET STATUS = "активен", MODERATOR_ID = NULL, CONFIRMED_BY_MODERATOR_ID = ?, TAKE_DATE = ? WHERE NUMBER = ?', 
                      (call.from_user.id, current_date, number))
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        conn.commit()

    if owner:
        markup_owner = types.InlineKeyboardMarkup()
        markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(owner[0], 
                        "✅ Ваш номер подтвержден и поставлен в работу. Оплата будет начислена через 5 минут, если номер не слетит.",
                        reply_markup=markup_owner)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    bot.edit_message_text(f"📱 Номер {number} поставлен в работу. Оплата будет начислена через 5 минут, если номер не слетит.", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "moderator_numbers")
def moderator_numbers(call):
    if not db.is_moderator(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав модератора!")
        return

    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE, STATUS FROM numbers WHERE MODERATOR_ID = ?', 
                          (call.from_user.id,))
            active_numbers = cursor.fetchall()
            
            cursor.execute('SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE, STATUS FROM numbers WHERE CONFIRMED_BY_MODERATOR_ID = ?', 
                          (call.from_user.id,))
            confirmed_numbers = cursor.fetchall()

        response = "📱 <b>Список ваших арендованных номеров:</b>\n\n"
        markup = types.InlineKeyboardMarkup()
        has_numbers = False

        if active_numbers:
            has_numbers = True
            response += "🔧 Номера в обработке:\n\n"
            for number, take_date, shutdown_date, status in active_numbers:
                response += f"📱 Номер: {number}\n"
                response += f"📊 Статус: {status if status else 'Не указан'}\n"
                if take_date == "0":
                    response += "⏳ Ожидает подтверждения\n"
                elif take_date == "1":
                    response += "⏳ Ожидает код\n"
                else:
                    response += f"🟢 Встал: {take_date}\n"
                if shutdown_date != "0":
                    response += f"❌ Слетел: {shutdown_date}\n"
                response += "────────────────────\n"
                markup.add(types.InlineKeyboardButton(f"📱 {number}", callback_data=f"moderator_number_{number}"))

        if confirmed_numbers:
            has_numbers = True
            response += "✅ Подтверждённые номера:\n\n"
            for number, take_date, shutdown_date, status in confirmed_numbers:
                response += f"📱 Номер: {number}\n"
                response += f"📊 Статус: {status if status else 'Не указан'}\n"
                if take_date == "0":
                    response += "⏳ Ожидает подтверждения\n"
                elif take_date == "1":
                    response += "⏳ Ожидает код\n"
                else:
                    response += f"🟢 Встал: {take_date}\n"
                if shutdown_date != "0":
                    response += f"❌ Слетел: {shutdown_date}\n"
                response += "────────────────────\n"
                markup.add(types.InlineKeyboardButton(f"📱 {number}", callback_data=f"moderator_number_{number}"))

        if not has_numbers:
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            bot.edit_message_text("📱 У вас нет арендованных номеров.", 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup)
        else:
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            bot.edit_message_text(response, 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup,
                                parse_mode='HTML')

    except Exception as e:
        print(f"Ошибка в moderator_numbers: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        bot.edit_message_text("❌ Произошла ошибка при получении списка номеров.", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)
        
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
    number = call.data.split("_")[2]
    
    try:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✉️ Отправить код заново", callback_data=f"send_code_{number}"))
        markup.add(types.InlineKeyboardButton("❌ Не валидный", callback_data=f"invalid_{number}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        bot.edit_message_text(f"📱 Номер: {number}\n"
                             "Пожалуйста, выберите действие:", 
                             call.message.chat.id, 
                             call.message.message_id, 
                             reply_markup=markup)
    
    except Exception as e:
        print(f"Ошибка в number_invalid: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке номера.")


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
            cursor.execute('SELECT TAKE_DATE, ID_OWNER, CONFIRMED_BY_MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
            data = cursor.fetchone()
            if not data:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            
            take_date, owner_id, confirmed_by_moderator_id = data
            
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
        
        mod_message = (f"❌ Номер {number} отмечен как слетевший.\n"
                      f"⏳ Время работы: {work_time:.2f} минут\n")
        if take_date not in ("0", "1"):
            mod_message += f"🟢 Встал: {take_date}\n"
        mod_message += f"❌ Слетел: {shutdown_date}\n"
        if not worked_enough:
            mod_message += f"⚠️ Номер не отработал минимальное время ({hold_time} минут)!"
        
        owner_message = (f"❌ Ваш номер {number} слетел.\n"
                        f"⏳ Время работы: {work_time:.2f} минут")
        if not worked_enough:
            owner_message += f"\n⚠️ Номер не отработал минимальное время ({hold_time} минут)!"
        bot.send_message(owner_id, owner_message)
        
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
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
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
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
    
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

        print(f"Пользователь {message.from_user.id} добавил номера: {successfully_added}")

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
        try:
            cursor.execute("ALTER TABLE numbers ADD COLUMN GROUP_CHAT_ID INTEGER")
            conn.commit()
            print("Столбец GROUP_CHAT_ID успешно добавлен.")
        except sqlite3.OperationalError as e:
            print(f"Не удалось добавить столбец GROUP_CHAT_ID: {e}")    


if __name__ == "__main__":
    init_db()
    run_bot()
import sqlite3
from datetime import datetime

def get_db():
    """Создаёт и возвращает подключение к базе данных."""
    return sqlite3.connect('database.db', check_same_thread=False)

def create_tables():
    """Создаёт все необходимые таблицы в базе данных."""
    with get_db() as conn:
        cursor = conn.cursor()
        # Таблица requests
        cursor.execute('''CREATE TABLE IF NOT EXISTS requests (
            ID INTEGER PRIMARY KEY,
            LAST_REQUEST TIMESTAMP,
            STATUS TEXT DEFAULT 'pending',
            BLOCKED INTEGER DEFAULT 0,
            CAN_SUBMIT_NUMBERS INTEGER DEFAULT 1
        )''')
        # Таблица withdraws
        cursor.execute('''CREATE TABLE IF NOT EXISTS withdraws (
            ID INTEGER,
            AMOUNT REAL,
            DATE TEXT,
            STATUS TEXT DEFAULT 'pending'
        )''')
        # Таблица users
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
            STATUS TEXT,
            GROUP_CHAT_ID INTEGER,
            TG_NUMBER INTEGER DEFAULT 1,  -- Новый столбец
            TG_GROUP TEXT
        )''')
        try:
            cursor.execute('ALTER TABLE numbers ADD COLUMN TG_NUMBER INTEGER DEFAULT 1')
            conn.commit()
        except sqlite3.OperationalError as e:
            if "duplicate column name" not in str(e).lower():
                raise e
            print("Столбец TG_NUMBER уже существует.")
        # Таблица settings
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
            PRICE REAL DEFAULT 2.0,
            HOLD_TIME INTEGER DEFAULT 5
        )''')
        # Таблица personal
        cursor.execute('''CREATE TABLE IF NOT EXISTS personal (
            ID INTEGER PRIMARY KEY,
            TYPE TEXT NOT NULL,
            GROUP_ID INTEGER
        )''')
        # Таблица groups
        cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            NAME TEXT UNIQUE NOT NULL
        )''')
        # Таблица treasury
        cursor.execute('''CREATE TABLE IF NOT EXISTS treasury (
            ID INTEGER PRIMARY KEY CHECK (ID = 1),
            BALANCE REAL DEFAULT 0,
            AUTO_INPUT INTEGER DEFAULT 0,
            CURRENCY TEXT DEFAULT 'USDT'
        )''')
        # Инициализация settings
        cursor.execute('SELECT COUNT(*) FROM settings')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO settings (PRICE, HOLD_TIME) VALUES (?, ?)', (2.0, 5))
        # Инициализация treasury
        cursor.execute('SELECT COUNT(*) FROM treasury')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO treasury (ID, BALANCE, AUTO_INPUT, CURRENCY) VALUES (?, ?, ?, ?)',
                          (1, 0, 0, 'USDT'))
        conn.commit()



def add_user(user_id, balance=0.0, reg_date=None):
    """Добавляет нового пользователя в таблицу users."""
    if reg_date is None:
        reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (ID, BALANCE, REG_DATE) VALUES (?, ?, ?)', 
                       (user_id, balance, reg_date))
        conn.commit()

def update_balance(user_id, amount):
    """Обновляет баланс пользователя."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, user_id))
        conn.commit()

def add_number(number, user_id):
    """Добавляет номер, связанный с пользователем."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID FROM users WHERE ID = ?', (user_id,))
        if not cursor.fetchone():
            add_user(user_id)
        cursor.execute('''
            INSERT INTO numbers (NUMBER, ID_OWNER, TAKE_DATE, SHUTDOWN_DATE, STATUS) 
            VALUES (?, ?, ?, ?, ?)
        ''', (number, user_id, '0', '0', 'ожидает'))
        conn.commit()
        print(f"[DEBUG] Добавлен номер: {number}, ID_OWNER: {user_id}, STATUS: ожидает")

def update_number_status(number, status, moderator_id=None):
    """Обновляет статус номера."""
    with get_db() as conn:
        cursor = conn.cursor()
        shutdown_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status != 'ожидает' else '0'
        cursor.execute('''
            UPDATE numbers 
            SET STATUS = ?, MODERATOR_ID = ?, SHUTDOWN_DATE = ? 
            WHERE NUMBER = ?
        ''', (status, moderator_id, shutdown_date, number))
        conn.commit()
        print(f"[DEBUG] Обновлён номер: {number}, STATUS: {status}, MODERATOR_ID: {moderator_id}")

def get_available_number(moderator_id):
    """Возвращает доступный номер для модератора."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT GROUP_ID FROM personal WHERE ID = ? AND TYPE = ?', (moderator_id, 'moder'))
        group_id = cursor.fetchone()
        group_id = group_id[0] if group_id else None
        
        query = '''
            SELECT n.NUMBER 
            FROM numbers n
            LEFT JOIN personal p ON n.ID_OWNER = p.ID
            WHERE n.TAKE_DATE = "0" 
            AND n.STATUS = "ожидает"
        '''
        params = []
        if group_id:
            query += ' AND (p.GROUP_ID = ? OR p.GROUP_ID IS NULL)'
            params.append(group_id)
        
        query += ' LIMIT 1'
        cursor.execute(query, params)
        number = cursor.fetchone()
        
        cursor.execute('SELECT NUMBER, ID_OWNER, STATUS, TAKE_DATE FROM numbers WHERE TAKE_DATE = "0" AND STATUS = "ожидает"')
        all_available = cursor.fetchall()
        print(f"[DEBUG] Модератор {moderator_id} (GROUP_ID={group_id}) запросил номер. Доступные номера: {all_available}")
        
        return number[0] if number else None

def get_group_name(group_id):
    """Возвращает имя группы по её ID."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT NAME FROM groups WHERE ID = ?', (group_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def migrate_db():
    """Миграция базы данных: добавляет новые столбцы, если их нет."""
    with get_db() as conn:
        cursor = conn.cursor()
        # Проверка таблицы requests
        cursor.execute('PRAGMA table_info(requests)')
        columns = [col[1] for col in cursor.fetchall()]
        if not columns:
            cursor.execute('''CREATE TABLE requests (
                ID INTEGER PRIMARY KEY,
                LAST_REQUEST TIMESTAMP,
                STATUS TEXT DEFAULT 'pending',
                BLOCKED INTEGER DEFAULT 0,
                CAN_SUBMIT_NUMBERS INTEGER DEFAULT 1
            )''')
        else:
            if 'BLOCKED' not in columns:
                cursor.execute('ALTER TABLE requests ADD COLUMN BLOCKED INTEGER DEFAULT 0')
            if 'CAN_SUBMIT_NUMBERS' not in columns:
                cursor.execute('ALTER TABLE requests ADD COLUMN CAN_SUBMIT_NUMBERS INTEGER DEFAULT 1')
        
        # Проверка таблицы numbers
        cursor.execute('PRAGMA table_info(numbers)')
        columns = [col[1] for col in cursor.fetchall()]
        if 'MODERATOR_ID' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN MODERATOR_ID INTEGER')
        if 'CONFIRMED_BY_MODERATOR_ID' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN CONFIRMED_BY_MODERATOR_ID INTEGER')
        if 'STATUS' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN STATUS TEXT DEFAULT "ожидает"')
        if 'GROUP_CHAT_ID' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN GROUP_CHAT_ID INTEGER')
        else:
            cursor.execute('UPDATE numbers SET STATUS = "ожидает" WHERE STATUS = "активен" AND TAKE_DATE = "0"')
        
        # Проверка таблицы personal
        cursor.execute('PRAGMA table_info(personal)')
        columns = [col[1] for col in cursor.fetchall()]
        if 'GROUP_ID' not in columns:
            cursor.execute('ALTER TABLE personal ADD COLUMN GROUP_ID INTEGER')
        
        # Проверка таблицы users
        cursor.execute('PRAGMA table_info(users)')
        columns = [col[1] for col in cursor.fetchall()]
        if 'BALANCE' in columns:
            cursor.execute('ALTER TABLE users RENAME TO users_old')
            cursor.execute('''CREATE TABLE users (
                ID INTEGER PRIMARY KEY,
                BALANCE REAL DEFAULT 0,
                REG_DATE TEXT
            )''')
            cursor.execute('INSERT INTO users (ID, BALANCE, REG_DATE) SELECT ID, BALANCE, REG_DATE FROM users_old')
            cursor.execute('DROP TABLE users_old')
        
        # Проверка таблицы settings
        cursor.execute('PRAGMA table_info(settings)')
        columns = [col[1] for col in cursor.fetchall()]
        if 'PRICE' in columns and 'HOLD_TIME' not in columns:
            cursor.execute('ALTER TABLE settings RENAME TO settings_old')
            cursor.execute('''CREATE TABLE settings (
                PRICE REAL DEFAULT 2.0,
                HOLD_TIME INTEGER DEFAULT 5
            )''')
            cursor.execute('INSERT INTO settings (PRICE, HOLD_TIME) SELECT CAST(PRICE AS REAL), MIN_TIME FROM settings_old')
            cursor.execute('DROP TABLE settings_old')
        
        # Проверка таблицы groups
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                NAME TEXT UNIQUE NOT NULL
            )
        ''')
        conn.commit()

def get_user_numbers(user_id):
    """Возвращает все номера пользователя."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE ID_OWNER = ?''', (user_id,))
        numbers = cursor.fetchall()
    return numbers

def is_moderator(user_id):
    """Проверяет, является ли пользователь модератором."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID FROM personal WHERE ID = ? AND TYPE = 'moder'", (user_id,))
        return cursor.fetchone() is not None

def get_treasury_balance():
    """Возвращает баланс казны."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT BALANCE FROM treasury WHERE ID = 1")
        result = cursor.fetchone()
        return result[0] if result else 0

def update_treasury_balance(amount):
    """Обновляет баланс казны."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE treasury SET BALANCE = BALANCE + ? WHERE ID = 1", (amount,))
        conn.commit()
        cursor.execute("SELECT BALANCE FROM treasury WHERE ID = 1")
        return cursor.fetchone()[0]

def set_treasury_balance(amount):
    """Устанавливает новый баланс казны."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE treasury SET BALANCE = ? WHERE ID = 1", (amount,))
        conn.commit()
        return amount

def get_auto_input_status():
    """Возвращает статус автоматического ввода."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT AUTO_INPUT FROM treasury WHERE ID = 1")
        result = cursor.fetchone()
        return bool(result[0]) if result else False

def toggle_auto_input():
    """Переключает статус автоматического ввода."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT AUTO_INPUT FROM treasury WHERE ID = 1")
        current_status = cursor.fetchone()[0]
        new_status = 1 if current_status == 0 else 0
        cursor.execute("UPDATE treasury SET AUTO_INPUT = ? WHERE ID = 1", (new_status,))
        conn.commit()
        return bool(new_status)

def log_treasury_operation(operation, amount, balance):
    """Логирует операции с казной."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] | Операция {operation} | Сумма {amount} | Остаток {balance}"
    with open("treasury_log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(log_entry + "\n")

# Вызов функций создания таблиц и миграции
create_tables()
migrate_db()
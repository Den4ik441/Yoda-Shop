import sqlite3
from datetime import datetime

def get_db():
    return sqlite3.connect('database.db', check_same_thread=False)

def create_tables():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS withdraws (
            ID INTEGER PRIMARY KEY,
            AMOUNT REAL,
            DATE TEXT,
            STATUS TEXT DEFAULT 'pending'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            USER_ID INTEGER PRIMARY KEY,
            ID INTEGER PRIMARY KEY,
            BALANCE INTEGER DEFAULT 0,
            REG_DATE TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS numbers (
            NUMBER TEXT PRIMARY KEY,
            ID_OWNER INTEGER,
            TAKE_DATE TEXT DEFAULT "0",
            SHUTDOWN_DATE TEXT DEFAULT "0",
            MODERATOR_ID INTEGER,
            VERIFICATION_CODE TEXT,
            STATUS TEXT DEFAULT 'ожидает',
            CONFIRMED_BY_MODERATOR_ID INTEGER
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
            CRYPTO_PAY TEXT,
            PRICE TEXT,
            MIN_TIME INTEGER DEFAULT 30
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS personal (
            ID INTEGER PRIMARY KEY,
            TYPE TEXT NOT NULL,
            GROUP_ID INTEGER
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS groups (
            ID INTEGER PRIMARY KEY AUTOINCREMENT,
            NAME TEXT UNIQUE NOT NULL
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS treasury (
            ID INTEGER PRIMARY KEY CHECK (ID = 1),
            BALANCE REAL DEFAULT 0,
            AUTO_INPUT INTEGER DEFAULT 0,
            CURRENCY TEXT DEFAULT 'USDT'
        )''')
        cursor.execute('SELECT COUNT(*) FROM settings')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO settings (PRICE, MIN_TIME) VALUES (?, ?)', ("4/30", 30))
        cursor.execute('SELECT COUNT(*) FROM treasury')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO treasury (ID, BALANCE, AUTO_INPUT, CURRENCY) VALUES (?, ?, ?, ?)',
                         (1, 0, 0, 'USDT'))
        conn.commit()

def add_user(user_id, balance=0, reg_date=None):
    if reg_date is None:
        reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (ID, BALANCE, REG_DATE) VALUES (?, ?, ?)', 
                       (user_id, balance, reg_date))
        conn.commit()

def update_balance(user_id, amount):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, user_id))
        conn.commit()

def add_number(number, user_id):
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
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE numbers 
            SET STATUS = ?, MODERATOR_ID = ?, SHUTDOWN_DATE = ? 
            WHERE NUMBER = ?
        ''', (status, moderator_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status != 'ожидает' else '0', number))
        conn.commit()
        print(f"[DEBUG] Обновлён номер: {number}, STATUS: {status}, MODERATOR_ID: {moderator_id}")

def get_available_number(moderator_id):
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
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT NAME FROM groups WHERE ID = ?', (group_id,))
        result = cursor.fetchone()
        return result[0] if result else None

def migrate_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('PRAGMA table_info(numbers)')
        columns = [col[1] for col in cursor.fetchall()]
        if 'MODERATOR_ID' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN MODERATOR_ID INTEGER')
        if 'CONFIRMED_BY_MODERATOR_ID' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN CONFIRMED_BY_MODERATOR_ID INTEGER')
        if 'STATUS' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN STATUS TEXT DEFAULT "ожидает"')
        else:
            cursor.execute('UPDATE numbers SET STATUS = "ожидает" WHERE STATUS = "активен" AND TAKE_DATE = "0"')
        
        cursor.execute('PRAGMA table_info(personal)')
        columns = [col[1] for col in cursor.fetchall()]
        if 'GROUP_ID' not in columns:
            cursor.execute('ALTER TABLE personal ADD COLUMN GROUP_ID INTEGER')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS groups (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                NAME TEXT UNIQUE NOT NULL
            )
        ''')
        conn.commit()

def get_user_numbers(user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE ID_OWNER = ?''', (user_id,))
        numbers = cursor.fetchall()
    return numbers

def is_moderator(user_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID FROM personal WHERE ID = ? AND TYPE = 'moder'", (user_id,))
        return cursor.fetchone() is not None

def get_treasury_balance():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT BALANCE FROM treasury WHERE ID = 1")
        result = cursor.fetchone()
        return result[0] if result else 0

def update_treasury_balance(amount):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE treasury SET BALANCE = BALANCE + ? WHERE ID = 1", (amount,))
        conn.commit()
        cursor.execute("SELECT BALANCE FROM treasury WHERE ID = 1")
        return cursor.fetchone()[0]

def set_treasury_balance(amount):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE treasury SET BALANCE = ? WHERE ID = 1", (amount,))
        conn.commit()
        return amount

def get_auto_input_status():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT AUTO_INPUT FROM treasury WHERE ID = 1")
        result = cursor.fetchone()
        return bool(result[0]) if result else False

def toggle_auto_input():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT AUTO_INPUT FROM treasury WHERE ID = 1")
        current_status = cursor.fetchone()[0]
        new_status = 1 if current_status == 0 else 0
        cursor.execute("UPDATE treasury SET AUTO_INPUT = ? WHERE ID = 1", (new_status,))
        conn.commit()
        return bool(new_status)

def log_treasury_operation(operation, amount, balance):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] | Операция {operation} | Сумма {amount} | Остаток {balance}"
    with open("treasury_log.txt", "a", encoding="utf-8") as log_file:
        log_file.write(log_entry + "\n")

def get_available_number(moderator_id):
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
    
create_tables()
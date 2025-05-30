import sqlite3
from datetime import datetime, timedelta

DB_FILE = "auth.db"

# 初始化資料庫
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS subscriptions (
            user_id TEXT PRIMARY KEY,
            start_date TEXT,
            end_date TEXT
        )
    ''')
    conn.commit()
    conn.close()

def add_user_subscription(user_id: str, days: int = 30):
    today = datetime.today().date()
    end_date = today + timedelta(days=days)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('REPLACE INTO subscriptions (user_id, start_date, end_date) VALUES (?, ?, ?)',
              (user_id, str(today), str(end_date)))
    conn.commit()
    conn.close()
    return today, end_date

def check_user_subscription(user_id: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT start_date, end_date FROM subscriptions WHERE user_id = ?', (str(user_id),))
    row = c.fetchone()
    conn.close()
    if row:
        start = datetime.strptime(row[0], "%Y-%m-%d").date()
        end = datetime.strptime(row[1], "%Y-%m-%d").date()
        return datetime.today().date() <= end, start, end
    return False, None, None

def get_all_subscriptions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT user_id, start_date, end_date FROM subscriptions')
    rows = c.fetchall()
    conn.close()
    return rows

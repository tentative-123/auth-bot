import sqlite3
from datetime import datetime, timedelta
from google_sheet_helper import get_auth_dates_from_sheet

DB_FILE = "auth.db"

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

def add_user_subscription(discord_id: int, days=30):
    today = datetime.today().date()
    data = load_auth_data()

    if str(discord_id) in data:
        old_end = datetime.strptime(data[str(discord_id)]["end"], "%Y-%m-%d").date()
        base = max(today, old_end)
    else:
        # 若 SQLite 沒資料 → 查 Google Sheet fallback
        valid, start, end = get_auth_dates_from_sheet(discord_id)
        base = max(today, end) if valid else today

    new_end = base + timedelta(days=days)
    data[str(discord_id)] = {
        "start": str(today),
        "end": str(new_end)
    }
    save_auth_data(data)
    return today, new_end

def add_user_subscription_new(user_id, days=30):
    today = datetime.today().date()
    end = today + timedelta(days=days)
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('REPLACE INTO subscriptions (user_id, start_date, end_date) VALUES (?, ?, ?)',
              (str(user_id), str(today), str(end)))
    conn.commit()
    conn.close()
    return today, end

def check_user_subscription(discord_id: int):
    # 1. 查 SQLite
    data = load_auth_data()
    record = data.get(str(discord_id))
    if record:
        start = datetime.strptime(record["start"], "%Y-%m-%d").date()
        end = datetime.strptime(record["end"], "%Y-%m-%d").date()
        return datetime.today().date() <= end, start, end

    # 2. Fallback to Google Sheet
    valid, start, end = get_auth_dates_from_sheet(discord_id)
    return valid, start, end

def get_all_subscriptions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT user_id, start_date, end_date FROM subscriptions')
    result = c.fetchall()
    conn.close()
    return result

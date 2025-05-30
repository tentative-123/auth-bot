import sqlite3
from datetime import datetime, timedelta
from google_sheet_helper import get_auth_dates_from_sheet
import json
import os

DB_FILE = "auth.db"
AUTH_JSON = "auth.json"


def load_auth_data():
    try:
        if os.path.exists(AUTH_JSON):
            with open(AUTH_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                print(f"[DEBUG] 成功讀取 auth.json：{len(data)} 筆")
                return data
        else:
            print("[DEBUG] 找不到 auth.json，回傳空 dict")
            return {}
    except Exception as e:
        print(f"❌ 讀取 auth.json 發生錯誤：{e}")
        return {}


def save_auth_data(data):
    try:
        with open(AUTH_JSON, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"[DEBUG] 成功儲存 auth.json，共 {len(data)} 筆")
    except Exception as e:
        print(f"❌ 寫入 auth.json 發生錯誤：{e}")


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
    print(f"[DEBUG] check_user_subscription: 查詢 {discord_id}...")

    # 1. 查 SQLite
    data = load_auth_data()
    record = data.get(str(discord_id))
    if record:
        start = datetime.strptime(record["start"], "%Y-%m-%d").date()
        end = datetime.strptime(record["end"], "%Y-%m-%d").date()
        print(f"[DEBUG] 找到本地授權：{start} ～ {end}")
        return datetime.today().date() <= end, start, end

    print("[DEBUG] 本地查無資料，改查 Google Sheet...")
    # 2. Fallback to Google Sheet
    valid, start, end = get_auth_dates_from_sheet(discord_id)
    print(f"[DEBUG] Sheet 回傳：valid={valid}, start={start}, end={end}")
    return valid, start, end


def get_all_subscriptions():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('SELECT user_id, start_date, end_date FROM subscriptions')
    result = c.fetchall()
    conn.close()
    return result

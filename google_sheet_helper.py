import json
import os
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials

# 取得環境變數內的 JSON 金鑰字串
SERVICE_JSON = os.getenv("GOOGLE_SERVICE_JSON")

def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    info = json.loads(SERVICE_JSON)
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key("1iYnuIVKSvqk-OkyhPtiZJnKmg4WGMFKtL4yd_mco1kM")  # 你的 Sheet ID
    worksheet = sheet.sheet1  # 預設第一個工作表
    return worksheet

def update_auth_date(discord_id: str, start_date: datetime, end_date: datetime):
    try:
        ws = get_sheet()
        values = ws.get_all_values()

        for idx, row in enumerate(values[1:], start=2):  # 🟢 從第2列開始, row編號從2起
            if len(row) > 1 and row[1].strip() == str(discord_id):
                ws.update_cell(idx, 7, start_date.strftime("%Y-%m-%d"))  # G欄
                ws.update_cell(idx, 8, end_date.strftime("%Y-%m-%d"))    # H欄
                print(f"✅ 寫入成功，第{idx}列 Discord ID: {discord_id}")
                return True

        print(f"❌ 找不到 Discord ID: {discord_id} 在 Google Sheet 中")
        return False
    except Exception as e:
        print(f"❌ 寫入 Google Sheet 時發生錯誤：{e}")
        return False
print(f"[DEBUG] 尋找寫入 Discord ID: {discord_id} | {start_date} ~ {end_date}")


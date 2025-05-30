import os
import json
import codecs
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials

# === Google Sheet 設定 ===
SPREADSHEET_ID = "1iYnuIVKSvqk-OkyhPtiZJnKmg4WGMFKtL4yd_mco1kM"  # 你的 Google Sheet ID
WORKSHEET_NAME = "001"  # 實際工作表名稱（不是 sheet1）

# === 從 Railway 環境變數中讀取金鑰（經過 escape） ===
SERVICE_JSON_ESCAPED = os.getenv("GOOGLE_SERVICE_JSON")

def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    # 將 escape 字串轉回正常 JSON 結構
    info = json.loads(codecs.decode(SERVICE_JSON_ESCAPED, 'unicode_escape'))

    # 建立 Google 認證並取得工作表
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID)
    worksheet = sheet.worksheet(WORKSHEET_NAME)
    return worksheet

# === 寫入授權資料到指定用戶行 ===
def update_auth_date(discord_id: str, start_date: datetime, end_date: datetime):
    try:
        ws = get_sheet()
        values = ws.get_all_values()

        # 跳過表頭，從第2列開始找
        for idx, row in enumerate(values[1:], start=2):
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

def get_auth_dates_from_sheet(discord_id: str):
    try:
        ws = get_sheet()
        values = ws.get_all_values()

        for row in values[1:]:
            if len(row) > 1 and row[1].strip() == str(discord_id):
                start_str = row[6] if len(row) >= 7 else ""
                end_str = row[7] if len(row) >= 8 else ""
                if start_str and end_str:
                    start = datetime.strptime(start_str.strip(), "%Y-%m-%d").date()
                    end = datetime.strptime(end_str.strip(), "%Y-%m-%d").date()
                    return True, start, end
        return False, None, None
    except Exception as e:
        print(f"❌ 從 Google Sheet 查詢授權日期失敗：{e}")
        return False, None, None

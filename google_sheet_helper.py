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
    ws = get_sheet()
    values = ws.get_all_values()
    for idx, row in enumerate(values):
        if len(row) > 1 and row[1].strip() == str(discord_id):  # B欄 = Discord ID
            ws.update_cell(idx + 1, 7, start_date.strftime("%Y-%m-%d"))  # G欄 = 第7欄
            ws.update_cell(idx + 1, 8, end_date.strftime("%Y-%m-%d"))    # H欄 = 第8欄
            return True
    return False

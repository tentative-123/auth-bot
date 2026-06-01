import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


@dataclass
class SubscriptionRow:
    row_number: int
    values: dict[str, Any]


class SubscriptionSheet:
    def __init__(self):
        self.sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
        self.worksheet_name = os.getenv("GOOGLE_WORKSHEET_NAME", "Form_Responses").strip()
        self.review_col = os.getenv("SHEET_COL_REVIEW", "後台核對").strip()
        self.discord_name_col = os.getenv("SHEET_COL_DISCORD_NAME", "您的 Discord (DC) 帳號名稱").strip()
        self.discord_id_col = os.getenv("SHEET_COL_DISCORD_ID", "Discord User ID").strip()
        self.notify_status_col = os.getenv("SHEET_COL_NOTIFY_STATUS", "Bot 通知狀態").strip()
        self.notify_message_col = os.getenv("SHEET_COL_NOTIFY_MESSAGE_ID", "Bot 通知訊息 ID").strip()
        self.confirmed_at_col = os.getenv("SHEET_COL_CONFIRMED_AT", "Discord 確認時間").strip()
        self.subscribed_at_col = os.getenv("SHEET_COL_SUBSCRIBED_AT", "訂閱時間").strip()
        self.expires_at_col = os.getenv("SHEET_COL_EXPIRES_AT", "到期日").strip()
        self.error_col = os.getenv("SHEET_COL_ERROR", "開通錯誤訊息").strip()
        self.approved_values = {
            v.strip().lower()
            for v in os.getenv("SHEET_APPROVED_VALUES", "OK,ok,通過,已核對").split(",")
            if v.strip()
        }

        if not self.sheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID is required for subscription sheet sync")

        self.worksheet = self._open_worksheet()
        self.headers = self._ensure_headers()

    def _open_worksheet(self):
        credentials_info_raw = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        credentials_file = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if credentials_info_raw:
            credentials_info = json.loads(credentials_info_raw)
            credentials = Credentials.from_service_account_info(credentials_info, scopes=[SHEETS_SCOPE])
        elif credentials_file:
            credentials = Credentials.from_service_account_file(credentials_file, scopes=[SHEETS_SCOPE])
        else:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON or GOOGLE_APPLICATION_CREDENTIALS is required")

        client = gspread.authorize(credentials)
        return client.open_by_key(self.sheet_id).worksheet(self.worksheet_name)

    def _ensure_headers(self) -> list[str]:
        headers = self.worksheet.row_values(1)
        required_headers = [
            self.discord_id_col,
            self.notify_status_col,
            self.notify_message_col,
            self.confirmed_at_col,
            self.subscribed_at_col,
            self.expires_at_col,
            self.error_col,
        ]
        changed = False
        for header in required_headers:
            if header not in headers:
                headers.append(header)
                changed = True
        if changed:
            self.worksheet.update("1:1", [headers])
        return headers

    def _col_index(self, header: str) -> int:
        if header not in self.headers:
            self.headers = self._ensure_headers()
        return self.headers.index(header) + 1

    def _get_row(self, row_number: int) -> SubscriptionRow:
        row_values = self.worksheet.row_values(row_number)
        values = {
            header: row_values[idx] if idx < len(row_values) else ""
            for idx, header in enumerate(self.headers)
        }
        return SubscriptionRow(row_number=row_number, values=values)

    def pending_rows(self) -> list[SubscriptionRow]:
        records = self.worksheet.get_all_records(head=1, default_blank="")
        rows = []
        for offset, record in enumerate(records, start=2):
            review_value = str(record.get(self.review_col, "")).strip().lower()
            notify_status = str(record.get(self.notify_status_col, "")).strip()
            subscribed_at = str(record.get(self.subscribed_at_col, "")).strip()
            if review_value in self.approved_values and not subscribed_at and notify_status in ("", "未通知"):
                rows.append(SubscriptionRow(row_number=offset, values=record))
        return rows

    def get_row(self, row_number: int) -> SubscriptionRow:
        return self._get_row(row_number)

    def mark_notified(self, row_number: int, message_id: int):
        self.worksheet.update_cell(row_number, self._col_index(self.notify_status_col), "已通知")
        self.worksheet.update_cell(row_number, self._col_index(self.notify_message_col), str(message_id))
        self.worksheet.update_cell(row_number, self._col_index(self.error_col), "")

    def mark_active(self, row_number: int, discord_user_id: int, subscribed_at: datetime, expires_at: datetime):
        updates = [
            (self.discord_id_col, str(discord_user_id)),
            (self.notify_status_col, "已開通"),
            (self.confirmed_at_col, subscribed_at.strftime("%Y-%m-%d %H:%M:%S")),
            (self.subscribed_at_col, subscribed_at.strftime("%Y-%m-%d %H:%M:%S")),
            (self.expires_at_col, expires_at.strftime("%Y-%m-%d")),
            (self.error_col, ""),
        ]
        for header, value in updates:
            self.worksheet.update_cell(row_number, self._col_index(header), value)

    def mark_error(self, row_number: int, message: str):
        self.worksheet.update_cell(row_number, self._col_index(self.notify_status_col), "錯誤")
        self.worksheet.update_cell(row_number, self._col_index(self.error_col), message[:500])

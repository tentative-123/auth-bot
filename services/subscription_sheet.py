import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import WorksheetNotFound

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


@dataclass
class SubscriptionRow:
    row_number: int
    values: dict[str, Any]


@dataclass
class RenewalReminder:
    row: SubscriptionRow
    days_left: int
    reminder_col: str
    expires_at: date


@dataclass
class ExpiredSubscription:
    row: SubscriptionRow
    days_overdue: int
    expires_at: date


def _normalize_text(value: str) -> str:
    normalized = str(value).strip().lower().removeprefix("@")
    return re.sub(r"\s+", "", normalized)


def _parse_sheet_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


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
        self.reminder_14_col = os.getenv("SHEET_COL_REMINDER_14", "到期前14天提醒").strip()
        self.reminder_7_col = os.getenv("SHEET_COL_REMINDER_7", "到期前7天提醒").strip()
        self.reminder_3_col = os.getenv("SHEET_COL_REMINDER_3", "到期前3天提醒").strip()
        self.expiry_status_col = os.getenv("SHEET_COL_EXPIRY_STATUS", "到期處理狀態").strip()
        self.expiry_removed_at_col = os.getenv("SHEET_COL_EXPIRY_REMOVED_AT", "到期移除時間").strip()
        self.expiry_whitelist_values = {
            v.strip().lower()
            for v in os.getenv("SHEET_EXPIRY_WHITELIST_VALUES", "保留,白名單,不移除,手動延長").split(",")
            if v.strip()
        }
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
        spreadsheet = client.open_by_key(self.sheet_id)
        worksheets = spreadsheet.worksheets()
        if not self.worksheet_name:
            if not worksheets:
                raise RuntimeError("Spreadsheet has no worksheets")
            return worksheets[0]
        try:
            return spreadsheet.worksheet(self.worksheet_name)
        except WorksheetNotFound as exc:
            available = ", ".join(ws.title for ws in worksheets) or "<none>"
            raise RuntimeError(
                f"Worksheet '{self.worksheet_name}' was not found. "
                f"Set GOOGLE_WORKSHEET_NAME to the exact sheet tab name. "
                f"Available worksheets: {available}"
            ) from exc

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
            self.reminder_14_col,
            self.reminder_7_col,
            self.reminder_3_col,
            self.expiry_status_col,
            self.expiry_removed_at_col,
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

    def _records_with_rows(self) -> list[SubscriptionRow]:
        records = self.worksheet.get_all_records(head=1, default_blank="")
        return [SubscriptionRow(row_number=offset, values=record) for offset, record in enumerate(records, start=2)]

    def pending_rows(self) -> list[SubscriptionRow]:
        rows = []
        for row in self._records_with_rows():
            review_value = str(row.values.get(self.review_col, "")).strip().lower()
            notify_status = str(row.values.get(self.notify_status_col, "")).strip()
            subscribed_at = str(row.values.get(self.subscribed_at_col, "")).strip()
            if review_value in self.approved_values and not subscribed_at and notify_status in ("", "未通知"):
                rows.append(row)
        return rows

    def renewal_reminder_rows(self, today: date | None = None) -> list[RenewalReminder]:
        today = today or date.today()
        records = self._records_with_rows()
        latest_expiry_by_user_id: dict[str, date] = {}
        for row in records:
            status = str(row.values.get(self.notify_status_col, "")).strip()
            discord_id = str(row.values.get(self.discord_id_col, "")).strip()
            expires_at = _parse_sheet_date(row.values.get(self.expires_at_col))
            if status != "已開通" or not discord_id or expires_at is None:
                continue
            latest = latest_expiry_by_user_id.get(discord_id)
            if latest is None or expires_at > latest:
                latest_expiry_by_user_id[discord_id] = expires_at

        reminders = []
        for row in records:
            status = str(row.values.get(self.notify_status_col, "")).strip()
            discord_id = str(row.values.get(self.discord_id_col, "")).strip()
            expires_at = _parse_sheet_date(row.values.get(self.expires_at_col))
            if status != "已開通" or not discord_id or expires_at is None:
                continue
            if expires_at != latest_expiry_by_user_id.get(discord_id):
                continue
            days_left = (expires_at - today).days
            if days_left < 0:
                continue
            if days_left <= 3 and not str(row.values.get(self.reminder_3_col, "")).strip():
                reminders.append(RenewalReminder(row, days_left, self.reminder_3_col, expires_at))
            elif days_left <= 7 and not str(row.values.get(self.reminder_7_col, "")).strip():
                reminders.append(RenewalReminder(row, days_left, self.reminder_7_col, expires_at))
            elif days_left <= 14 and not str(row.values.get(self.reminder_14_col, "")).strip():
                reminders.append(RenewalReminder(row, days_left, self.reminder_14_col, expires_at))
        return reminders

    def latest_expiry_for_user(self, discord_user_id: int | str, discord_name: str = "", exclude_row_number: int | None = None) -> date | None:
        user_id = str(discord_user_id or "").strip()
        target_name = _normalize_text(discord_name)
        latest = None
        for row in self._records_with_rows():
            if exclude_row_number and row.row_number == exclude_row_number:
                continue
            row_user_id = str(row.values.get(self.discord_id_col, "")).strip()
            row_name = _normalize_text(row.values.get(self.discord_name_col, ""))
            if user_id and row_user_id == user_id:
                pass
            elif target_name and row_name == target_name:
                pass
            else:
                continue
            expires_at = _parse_sheet_date(row.values.get(self.expires_at_col))
            if expires_at and (latest is None or expires_at > latest):
                latest = expires_at
        return latest

    def expired_subscription_rows(self, today: date | None = None, grace_days: int = 3) -> list[ExpiredSubscription]:
        today = today or date.today()
        records = self._records_with_rows()
        latest_expiry_by_user_id: dict[str, date] = {}
        for row in records:
            status = str(row.values.get(self.notify_status_col, "")).strip()
            discord_id = str(row.values.get(self.discord_id_col, "")).strip()
            expires_at = _parse_sheet_date(row.values.get(self.expires_at_col))
            if status != "已開通" or not discord_id or expires_at is None:
                continue
            latest = latest_expiry_by_user_id.get(discord_id)
            if latest is None or expires_at > latest:
                latest_expiry_by_user_id[discord_id] = expires_at

        expired = []
        for row in records:
            status = str(row.values.get(self.notify_status_col, "")).strip()
            discord_id = str(row.values.get(self.discord_id_col, "")).strip()
            expires_at = _parse_sheet_date(row.values.get(self.expires_at_col))
            expiry_status = str(row.values.get(self.expiry_status_col, "")).strip()
            if status != "已開通" or not discord_id or expires_at is None:
                continue
            if expires_at != latest_expiry_by_user_id.get(discord_id):
                continue
            if expiry_status == "已移除" or expiry_status.lower() in self.expiry_whitelist_values:
                continue
            days_overdue = (today - expires_at).days
            if days_overdue >= grace_days:
                expired.append(ExpiredSubscription(row, days_overdue, expires_at))
        return expired

    def get_row(self, row_number: int) -> SubscriptionRow:
        return self._get_row(row_number)

    def mark_notified(self, row_number: int, message_id: int):
        self.worksheet.update_cell(row_number, self._col_index(self.notify_status_col), "已通知")
        self.worksheet.update_cell(row_number, self._col_index(self.notify_message_col), str(message_id))
        self.worksheet.update_cell(row_number, self._col_index(self.error_col), "")

    def mark_active(self, row_number: int, discord_user_id: int, subscribed_at: datetime, expires_at: datetime | date):
        expires_text = expires_at.strftime("%Y-%m-%d")
        updates = [
            (self.discord_id_col, str(discord_user_id)),
            (self.notify_status_col, "已開通"),
            (self.confirmed_at_col, subscribed_at.strftime("%Y-%m-%d %H:%M:%S")),
            (self.subscribed_at_col, subscribed_at.strftime("%Y-%m-%d %H:%M:%S")),
            (self.expires_at_col, expires_text),
            (self.error_col, ""),
        ]
        for header, value in updates:
            self.worksheet.update_cell(row_number, self._col_index(header), value)

    def mark_reminder_sent(self, row_number: int, reminder_col: str, sent_at: datetime):
        self.worksheet.update_cell(row_number, self._col_index(reminder_col), sent_at.strftime("%Y-%m-%d %H:%M:%S"))

    def mark_expired_removed(self, row_number: int, removed_at: datetime):
        self.worksheet.update_cell(row_number, self._col_index(self.expiry_status_col), "已移除")
        self.worksheet.update_cell(row_number, self._col_index(self.expiry_removed_at_col), removed_at.strftime("%Y-%m-%d %H:%M:%S"))

    def mark_error(self, row_number: int, message: str):
        self.worksheet.update_cell(row_number, self._col_index(self.notify_status_col), "錯誤")
        self.worksheet.update_cell(row_number, self._col_index(self.error_col), message[:500])

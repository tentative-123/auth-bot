import asyncio
import logging
import os
import re
from datetime import datetime, time
from zoneinfo import ZoneInfo

import discord
from dateutil.relativedelta import relativedelta
from discord.ext import tasks

from services.subscription_sheet import ExpiredSubscription, RenewalReminder, SubscriptionSheet

logger = logging.getLogger("auth-bot.subscription")
CONFIRM_PREFIX = "sub_confirm:"
TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def _normalize_discord_name(value: str) -> str:
    normalized = value.strip().lower()
    normalized = normalized.removeprefix("@")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def _member_name_candidates(member: discord.Member | discord.User) -> set[str]:
    candidates = {member.name, member.display_name, str(member)}
    global_name = getattr(member, "global_name", None)
    if global_name:
        candidates.add(global_name)
    return {_normalize_discord_name(candidate) for candidate in candidates if candidate}


class SubscriptionManager:
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self.enabled = os.getenv("SUBSCRIPTION_SYNC_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        self.guild_id = int(os.getenv("DISCORD_GUILD_ID", "0") or 0)
        self.channel_id = int(os.getenv("DISCORD_NOTIFY_CHANNEL_ID", "0") or 0)
        self.role_id = int(os.getenv("DISCORD_SUBSCRIBER_ROLE_ID", "0") or 0)
        self.role_id_2 = int(os.getenv("DISCORD_SUBSCRIBER_ROLE_ID_2", "0") or 0)
        self.check_interval = int(os.getenv("SHEET_CHECK_INTERVAL_SECONDS", "60") or 60)
        self.discord_name_col = os.getenv("SHEET_COL_DISCORD_NAME", "您的 Discord (DC) 帳號名稱").strip()
        self.notify_mode = os.getenv("SUBSCRIPTION_NOTIFY_MODE", "channel").strip().lower()
        self.expiry_grace_days = int(os.getenv("SUBSCRIPTION_EXPIRY_GRACE_DAYS", "3") or 3)
        self.sheet: SubscriptionSheet | None = None

    def start(self):
        if not self.enabled:
            logger.info("[subscription] disabled; set SUBSCRIPTION_SYNC_ENABLED=true to enable")
            return
        missing = [
            name
            for name, value in (
                ("DISCORD_GUILD_ID", self.guild_id),
                ("DISCORD_NOTIFY_CHANNEL_ID", self.channel_id),
                ("DISCORD_SUBSCRIBER_ROLE_ID", self.role_id),
            )
            if not value
        ]
        if missing:
            logger.error("[subscription] missing required env vars: %s", ", ".join(missing))
            return
        if not self.sync_sheet_loop.is_running():
            self.sync_sheet_loop.change_interval(seconds=self.check_interval)
            self.sync_sheet_loop.start()

    async def close(self):
        if self.sync_sheet_loop.is_running():
            self.sync_sheet_loop.cancel()

    def _sheet(self) -> SubscriptionSheet:
        if self.sheet is None:
            self.sheet = SubscriptionSheet()
        return self.sheet

    def _pending_rows_sync(self):
        return self._sheet().pending_rows()

    def _get_row_sync(self, row_number: int):
        return self._sheet().get_row(row_number)

    def _mark_notified_sync(self, row_number: int, message_id: int):
        self._sheet().mark_notified(row_number, message_id)

    def _mark_error_sync(self, row_number: int, message: str):
        self._sheet().mark_error(row_number, message)

    def _mark_active_sync(self, row_number: int, discord_user_id: int, subscribed_at: datetime, expires_at: datetime):
        self._sheet().mark_active(row_number, discord_user_id, subscribed_at, expires_at)

    def _mark_reminder_sent_sync(self, row_number: int, reminder_col: str, sent_at: datetime):
        self._sheet().mark_reminder_sent(row_number, reminder_col, sent_at)

    def _renewal_reminder_rows_sync(self):
        return self._sheet().renewal_reminder_rows(datetime.now(TAIPEI_TZ).date())

    def _latest_expiry_for_user_sync(self, discord_user_id: int, discord_name: str, exclude_row_number: int):
        return self._sheet().latest_expiry_for_user(discord_user_id, discord_name, exclude_row_number)

    def _expired_subscription_rows_sync(self):
        return self._sheet().expired_subscription_rows(datetime.now(TAIPEI_TZ).date(), self.expiry_grace_days)

    def _mark_expired_removed_sync(self, row_number: int, removed_at: datetime):
        self._sheet().mark_expired_removed(row_number, removed_at)

    def _role_id_for_row(self, row) -> int:
        review_value = str(row.values.get(self._sheet().review_col, "")).strip().lower()
        return self.role_id_2 if review_value == "ok2" else self.role_id

    def _build_confirm_view(self, row_number: int) -> discord.ui.View:
        view = discord.ui.View(timeout=None)
        button = discord.ui.Button(
            label="✅ 我是本人，開通權限",
            style=discord.ButtonStyle.green,
            custom_id=f"{CONFIRM_PREFIX}{row_number}",
        )
        view.add_item(button)
        return view

    def _user_matches_sheet_name(self, user: discord.Member | discord.User, discord_name: str) -> bool:
        target = _normalize_discord_name(discord_name)
        return bool(target and target in _member_name_candidates(user))

    async def _find_member_by_sheet_name(self, guild: discord.Guild, discord_name: str) -> discord.Member | None:
        target = _normalize_discord_name(discord_name)
        if not target:
            return None
        for member in guild.members:
            if target in _member_name_candidates(member):
                return member
        queried = await guild.query_members(discord_name, limit=5)
        for member in queried:
            if target in _member_name_candidates(member):
                return member
        return None

    async def _send_notification(self, row_number: int, discord_name: str):
        guild = self.bot.get_guild(self.guild_id)
        channel = self.bot.get_channel(self.channel_id)
        if guild is None or channel is None:
            raise RuntimeError("Discord guild/channel not found; check DISCORD_GUILD_ID and DISCORD_NOTIFY_CHANNEL_ID")
        member = await self._find_member_by_sheet_name(guild, discord_name)
        view = self._build_confirm_view(row_number)
        note = (
            "【股市艾斯權證系統】你的訂閱資料已完成後台核對，請點擊下方按鈕完成 Discord 權限開通。\n"
            "本系統是以波段籌碼為主的輔助策略工具；使用上有任何問題，都歡迎在討論區詢問艾斯~"
        )

        message = None
        if self.notify_mode == "dm" and member:
            try:
                message = await member.send(note, view=view)
            except discord.Forbidden:
                logger.info("[subscription] dm disabled, falling back to notify channel: member=%s row=%s", member.id, row_number)

        if message is None:
            mention = member.mention if member else f"@{discord_name}"
            if member is None:
                note += "\n（Bot 目前無法用名稱精準標記你；請本人點擊，系統會比對你填寫的 Discord 名稱並記錄你的 Discord ID。）"
            elif self.notify_mode == "dm":
                note += "\n（因為無法私訊此使用者，改在此頻道發送確認按鈕。）"
            message = await channel.send(
                f"{mention} {note}",
                view=view,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        await asyncio.to_thread(self._mark_notified_sync, row_number, message.id)

    async def _send_renewal_reminder(self, reminder: RenewalReminder):
        discord_id = str(reminder.row.values.get(self._sheet().discord_id_col, "")).strip()
        if not discord_id:
            await asyncio.to_thread(self._mark_error_sync, reminder.row.row_number, "缺少 Discord User ID，無法寄送續約提醒")
            return

        try:
            user = await self.bot.fetch_user(int(discord_id))
            await user.send(
                f"你的訂閱將於 {reminder.expires_at:%Y-%m-%d} 到期（剩 {reminder.days_left} 天）。\n"
                "若要續約，請填寫同一份表單並完成付款/後台核對；核對完成後我會再傳開通確認按鈕給你。"
            )
        except discord.Forbidden:
            guild = self.bot.get_guild(self.guild_id)
            channel = self.bot.get_channel(self.channel_id)
            member = guild.get_member(int(discord_id)) if guild else None
            mention = member.mention if member else f"<@{discord_id}>"
            if channel is None:
                raise RuntimeError("Discord notify channel not found for renewal reminder fallback")
            await channel.send(
                f"{mention} 你的訂閱將於 {reminder.expires_at:%Y-%m-%d} 到期（剩 {reminder.days_left} 天）。請留意續約。",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )

        await asyncio.to_thread(self._mark_reminder_sent_sync, reminder.row.row_number, reminder.reminder_col, datetime.now(TAIPEI_TZ))

    async def _remove_expired_subscription_role(self, expired: ExpiredSubscription):
        discord_id = str(expired.row.values.get(self._sheet().discord_id_col, "")).strip()
        if not discord_id:
            await asyncio.to_thread(self._mark_error_sync, expired.row.row_number, "缺少 Discord User ID，無法移除到期身分組")
            return

        guild = self.bot.get_guild(self.guild_id)
        if guild is None:
            raise RuntimeError("Discord guild not found for expiry removal")
        role_id = self._role_id_for_row(expired.row)
        if not role_id:
            await asyncio.to_thread(self._mark_error_sync, expired.row.row_number, "缺少對應的訂閱身分組 ID，無法移除到期身分組")
            return
        role = guild.get_role(role_id)
        if role is None:
            raise RuntimeError("Subscriber role not found for expiry removal")
        member = guild.get_member(int(discord_id))
        if member is None:
            try:
                member = await guild.fetch_member(int(discord_id))
            except discord.NotFound:
                member = None

        if member and role in member.roles:
            await member.remove_roles(role, reason=f"Subscription expired from Google Sheet row {expired.row.row_number}")
        await asyncio.to_thread(self._mark_expired_removed_sync, expired.row.row_number, datetime.now(TAIPEI_TZ))

    @tasks.loop(seconds=60)
    async def sync_sheet_loop(self):
        try:
            rows = await asyncio.to_thread(self._pending_rows_sync)
            for row in rows:
                discord_name = str(row.values.get(self.discord_name_col, "")).strip()
                if not discord_name:
                    await asyncio.to_thread(self._mark_error_sync, row.row_number, "Discord 名稱空白，無法通知")
                    continue
                await self._send_notification(row.row_number, discord_name)

            reminders = await asyncio.to_thread(self._renewal_reminder_rows_sync)
            for reminder in reminders:
                await self._send_renewal_reminder(reminder)

            expired_rows = await asyncio.to_thread(self._expired_subscription_rows_sync)
            for expired in expired_rows:
                await self._remove_expired_subscription_role(expired)
        except Exception:
            logger.exception("[subscription] sheet sync failed")

    @sync_sheet_loop.before_loop
    async def before_sync_sheet_loop(self):
        await self.bot.wait_until_ready()

    async def handle_interaction(self, interaction: discord.Interaction) -> bool:
        custom_id = interaction.data.get("custom_id") if isinstance(interaction.data, dict) else None
        if not custom_id or not custom_id.startswith(CONFIRM_PREFIX):
            return False
        row_number = int(custom_id.removeprefix(CONFIRM_PREFIX))
        await interaction.response.defer(ephemeral=True)

        try:
            row = await asyncio.to_thread(self._get_row_sync, row_number)
            existing_discord_id = str(row.values.get(self._sheet().discord_id_col, "")).strip()
            if existing_discord_id and existing_discord_id != str(interaction.user.id):
                await interaction.followup.send("❌ 這筆訂閱資料已綁定其他 Discord 帳號，請聯絡管理員。", ephemeral=True)
                return True

            discord_name = str(row.values.get(self.discord_name_col, "")).strip()
            if not existing_discord_id and not self._user_matches_sheet_name(interaction.user, discord_name):
                await interaction.followup.send("❌ 你的 Discord 名稱與表單填寫資料不一致，請聯絡管理員協助確認。", ephemeral=True)
                return True

            guild = self.bot.get_guild(self.guild_id)
            if guild is None:
                raise RuntimeError("Discord guild not found")
            role_id = self._role_id_for_row(row)
            if not role_id:
                raise RuntimeError("Subscriber role ID is missing for this review value")
            role = guild.get_role(role_id)
            if role is None:
                raise RuntimeError("Subscriber role not found")
            member = guild.get_member(interaction.user.id)
            if member is None:
                member = await guild.fetch_member(interaction.user.id)
            await member.add_roles(role, reason=f"Subscription confirmed from Google Sheet row {row_number}")

            subscribed_at = datetime.now(TAIPEI_TZ)
            latest_expiry = await asyncio.to_thread(
                self._latest_expiry_for_user_sync,
                interaction.user.id,
                discord_name,
                row_number,
            )
            if latest_expiry and latest_expiry >= subscribed_at.date():
                base_expiry = datetime.combine(latest_expiry, time.min, tzinfo=TAIPEI_TZ)
                expires_at = base_expiry + relativedelta(months=3)
            else:
                expires_at = subscribed_at + relativedelta(months=3)
            await asyncio.to_thread(self._mark_active_sync, row_number, interaction.user.id, subscribed_at, expires_at)
            await interaction.followup.send(f"✅ 權限已開通，到期日：{expires_at:%Y-%m-%d}", ephemeral=True)
            return True
        except Exception as exc:
            logger.exception("[subscription] confirmation failed: row=%s user=%s", row_number, interaction.user.id)
            await asyncio.to_thread(self._mark_error_sync, row_number, str(exc))
            await interaction.followup.send(f"❌ 開通失敗：{exc}", ephemeral=True)
            return True

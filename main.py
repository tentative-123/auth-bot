import os
import discord
from discord.ext import commands
import asyncio
from datetime import datetime, timedelta
from auth_db import init_db, add_user_subscription, check_user_subscription, get_all_subscriptions
from google_sheet_helper import update_auth_date

TOKEN = os.getenv("AUTH_BOT_TOKEN")
ROLE_NAME = "已訂閱"

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="-", intents=intents)

@bot.command()
@commands.has_permissions(manage_roles=True)
async def auth(ctx, member: discord.Member, days: int = 30):
    start, end = add_user_subscription(member.id, days)

    # 🧠 非同步安全方式呼叫 Google Sheet 寫入
    loop = asyncio.get_event_loop()
    try:
        success = await loop.run_in_executor(None, update_auth_date, str(member.id), start, end)
        if success:
            print(f"✅ Google Sheet 更新成功 {member.id} → {start} ~ {end}")
        else:
            print(f"❌ Google Sheet 找不到 ID：{member.id}")
    except Exception as e:
        print(f"❌ 寫入 Google Sheet 發生錯誤：{e}")

    # ✅ 加身分組
    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    if role:
        try:
            await member.add_roles(role)
            await ctx.send(f"✅ {member.mention} 授權成功！有效期 {start} ～ {end}")
        except discord.Forbidden:
            await ctx.send("❌ 無法給身分組，請檢查機器人角色順序與權限")
    else:
        await ctx.send(f"⚠️ 未找到身分組 `{ROLE_NAME}`，請先建立該角色")

    print(f"[DEBUG] 給予角色與同步完成：{member.name} ID: {member.id}")


@bot.command()
@commands.has_permissions(manage_roles=True)
async def authnew(ctx, member: discord.Member, days: int = 30):
    from auth_db import load_auth_data, save_auth_data
    from google_sheet_helper import update_auth_date
    import sqlite3

    today = datetime.today().date()
    end = today + timedelta(days=days)

    # --- 更新 SQLite ---
    conn = sqlite3.connect("auth.db")
    c = conn.cursor()
    c.execute('REPLACE INTO subscriptions (user_id, start_date, end_date) VALUES (?, ?, ?)',
              (str(member.id), str(today), str(end)))
    conn.commit()
    conn.close()

    # --- 更新本地 auth.json 快取 ---
    data = load_auth_data()
    data[str(member.id)] = {
        "start": str(today),
        "end": str(end)
    }
    save_auth_data(data)

    # --- 更新 Google Sheet ---
    print(f"[DEBUG] 強制寫入 Google Sheet：{member.id} | {today} ~ {end}")
    update_auth_date(str(member.id), today, end)

    # --- 加上 Discord 角色 ---
    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    if role:
        await member.add_roles(role)
        await ctx.send(f"✅ {member.mention} 授權成功！（覆蓋）有效期 {today} ～ {end}")
    else:
        await ctx.send(f"⚠️ 未找到身分組 `{ROLE_NAME}`，請先建立該角色")

    print(f"[DEBUG] authnew 完成：{member.display_name} ID: {member.id}")



@bot.command()
@commands.has_permissions(administrator=True)
async def checkauth(ctx, member: discord.Member):
    valid, start, end = check_user_subscription(member.id)
    if not start:
        await ctx.send(f"❌ {member.mention} 尚未授權")
    elif valid:
        await ctx.send(f"🟢 {member.mention} 有效，授權期間：{start} ～ {end}")
    else:
        await ctx.send(f"🔴 {member.mention} 已過期，授權期間：{start} ～ {end}")

async def check_and_update_subscriptions(guild: discord.Guild):
    today = datetime.today().date()
    all_subs = get_all_subscriptions()

    for user_id, start_str, end_str in all_subs:
        try:
            member = guild.get_member(int(user_id))
            if not member:
                print(f"⚠️ 找不到用戶 ID: {user_id}")
                continue

            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()
            days_left = (end - today).days

            role_sub = discord.utils.get(guild.roles, name="已訂閱")
            role_guest = discord.utils.get(guild.roles, name="遊客")

            # 授權已過期：移除訂閱身分，轉為遊客
            if today > end:
                if role_sub and role_sub in member.roles:
                    await member.remove_roles(role_sub)
                    print(f"🔁 已移除 {member} 的訂閱身分")

                if role_guest and role_guest not in member.roles:
                    await member.add_roles(role_guest)
                    print(f"🟡 已轉為遊客 {member}")

                continue

            # 即將到期：5天內提醒
            if 0 < days_left <= 5:
                # 私訊提醒
                try:
                    await member.send(
                        f"📢 嗨 {member.display_name}，你的訂閱即將在 {days_left} 天後（{end}）到期，如要續訂請填寫表單並通知管理員哦！"
                    )
                    print(f"📨 已提醒 {member} 訂閱即將到期")
                except discord.Forbidden:
                    print(f"❌ 無法私訊 {member.display_name}，可能關閉私訊")

                # 私人頻道同步提醒
                try:
                    private_channel = guild.get_channel(1377957354397761536)
                    if private_channel:
                        await private_channel.send(
                            f"📋 用戶 {member.display_name}（ID: {member.id}）的訂閱將在 {days_left} 天後（{end}）到期。"
                        )
                        print(f"📤 已同步發送私人提醒：{member.display_name}")
                    else:
                        print("❌ 找不到私人頻道 ID: 1377957354397761536")
                except Exception as e:
                    print(f"❌ 發送私人頻道提醒失敗：{e}")

        except Exception as e:
            print(f"❌ 處理用戶 {user_id} 時發生錯誤：{e}")

#-------------------------------------------------------------------------------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def authall(ctx):
    from google_sheet_helper import get_sheet
    try:
        ws = get_sheet()
        values = ws.get_all_values()[1:]  # 跳過表頭

        total = 0
        near_expiry = []
        today = datetime.today().date()

        for row in values:
            if len(row) >= 8:
                user_id = row[1].strip()
                start_str = row[6].strip()
                end_str = row[7].strip()

                try:
                    start = datetime.strptime(start_str, "%Y-%m-%d").date()
                    end = datetime.strptime(end_str, "%Y-%m-%d").date()
                    total += 1
                    days_left = (end - today).days
                    if 0 < days_left <= 5:
                        near_expiry.append((user_id, days_left))
                except Exception as e:
                    print(f"⚠️ 無法解析日期：{user_id} | {start_str} ~ {end_str}")

        near_expiry.sort(key=lambda x: x[1])

        msg = f"📊 總訂閱用戶數：{total} 位\n"
        if near_expiry:
            msg += "⏰ 近 5 天即將過期的用戶 ID：\n"
            for uid, d in near_expiry:
                msg += f"- ID: `{uid}`（剩 {d} 天）\n"
        else:
            msg += "✅ 目前沒有用戶即將過期！"

        await ctx.send(msg)

    except Exception as e:
        await ctx.send(f"❌ 無法讀取 Google Sheet：{e}")

#----------------------------------------------------------------------------------------------------------------


async def init_tasks():
    await bot.wait_until_ready()
    init_db()
    print(f"✅ 授權機器人已啟動：{bot.user}")

    async def daily_check():
        while not bot.is_closed():
            for guild in bot.guilds:
                await check_and_update_subscriptions(guild)
            await asyncio.sleep(86400)

    bot.loop.create_task(daily_check())

async def main():
    async with bot:
        bot.loop.create_task(init_tasks())
        await bot.start(TOKEN)

if __name__ == '__main__':
    if not TOKEN:
        print("❌ 請設定 AUTH_BOT_TOKEN 環境變數")
    else:
        asyncio.run(main())

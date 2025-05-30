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
    start, end = add_user_subscription(member.id, days)  # ✅ 先產生日期
    update_auth_date(member.id, start, end) # ✅ 再寫入 Google Sheet
    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    print(f"找到身分組：{role}")  # ← debug log

    if role:
        await member.add_roles(role)
        await ctx.send(f"✅ {member.mention} 授權成功！有效期 {start} ～ {end}")
    else:
        await ctx.send(f"⚠️ 未找到身分組 `{ROLE_NAME}`，請先建立該角色")
    print(f"[DEBUG] Member: {member}, ID: {member.id}")
    print(f"[DEBUG] Found Role: {role}, ID: {role.id if role else 'None'}")
    print(f"[DEBUG] Member Roles Before: {[r.name for r in member.roles]}")

@bot.command()
@commands.has_permissions(manage_roles=True)
async def authnew(ctx, member: discord.Member, days: int = 30):
    start, end = add_user_subscription_new(member.id, days)
    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    if role:
        await member.add_roles(role)
        await ctx.send(f"✅ {member.mention} 授權成功！（覆蓋）有效期 {start} ～ {end}")
    else:
        await ctx.send(f"⚠️ 未找到身分組 `{ROLE_NAME}`，請先建立該角色")


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
                continue

            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()
            days_left = (end - today).days

            role_sub = discord.utils.get(guild.roles, name="已訂閱")
            role_guest = discord.utils.get(guild.roles, name="遊客")

            if today > end:
                if role_sub in member.roles:
                    await member.remove_roles(role_sub)
                if role_guest and role_guest not in member.roles:
                    await member.add_roles(role_guest)
                print(f"🔁 已移除 {member} 訂閱身分，轉為遊客")
                continue

            if 0 < days_left <= 5:
                try:
                    await member.send(
                        f"📢 嗨 {member.display_name}，你的訂閱即將在 {days_left} 天後（{end}）到期，如要續訂請填寫表單並通知管理員哦！"
                    )
                    print(f"📨 已提醒 {member} 訂閱即將到期")
                except discord.Forbidden:
                    print(f"❌ 無法私訊 {member}")
        except Exception as e:
            print(f"❌ 錯誤處理用戶 {user_id}：{e}")

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

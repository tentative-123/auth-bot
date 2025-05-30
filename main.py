import os
import discord
from discord.ext import commands
import json
from datetime import datetime, timedelta

TOKEN = os.getenv("AUTH_BOT_TOKEN")
AUTH_FILE = "subs.json"
ROLE_NAME = "已訂閱"  # 改成你的身份組名稱

# === 授權資料操作 ===
def load_auth_data():
    try:
        with open(AUTH_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_auth_data(data):
    with open(AUTH_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_user_subscription(user_id, days=30):
    data = load_auth_data()
    today = datetime.today().date()
    end_date = today + timedelta(days=days)
    data[str(user_id)] = {
        "start": str(today),
        "end": str(end_date)
    }
    save_auth_data(data)
    return today, end_date

def check_user_subscription(user_id):
    data = load_auth_data()
    record = data.get(str(user_id))
    if not record:
        return False, None, None
    start = datetime.strptime(record["start"], "%Y-%m-%d").date()
    end = datetime.strptime(record["end"], "%Y-%m-%d").date()
    now = datetime.today().date()
    return now <= end, start, end

# === Discord Bot 設定 ===
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ 授權機器人已啟動：{bot.user}")

# !auth @user 30
@bot.command()
@commands.has_permissions(manage_roles=True)
async def auth(ctx, member: discord.Member, days: int = 30):
    start, end = add_user_subscription(member.id, days)
    role = discord.utils.get(ctx.guild.roles, name=ROLE_NAME)
    if role:
        await member.add_roles(role)
        await ctx.send(f"✅ {member.mention} 授權成功！有效期 {start} ～ {end}")
    else:
        await ctx.send(f"⚠️ 未找到身分組 `{ROLE_NAME}`，請先建立該角色")

# !checkauth @user
@bot.command()
async def checkauth(ctx, member: discord.Member):
    valid, start, end = check_user_subscription(member.id)
    if not start:
        await ctx.send(f"❌ {member.mention} 尚未授權")
    elif valid:
        await ctx.send(f"🟢 {member.mention} 有效，授權期間：{start} ～ {end}")
    else:
        await ctx.send(f"🔴 {member.mention} 已過期，授權期間：{start} ～ {end}")

# 啟動 bot
if __name__ == '__main__':
    if not TOKEN:
        print("❌ 請設定 AUTH_BOT_TOKEN 環境變數")
    else:
        bot.run(TOKEN)

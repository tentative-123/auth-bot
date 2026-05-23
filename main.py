import os
import re
import json
import logging
import discord
from discord.ext import commands
from discord.ui import Button, View
from openai import AsyncOpenAI

import analysis
from services.warrant_screener import fetch_warrant_results
from services.warrant_card_renderer import render_warrant_card_image

DISCORD_TOKEN = (
    os.getenv("DISCORD_TOKEN")
    or os.getenv("DISCORD_BOT_TOKEN")
    or os.getenv("discord_token")
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ENABLE_HEALTH_FLOW = False

if OPENAI_API_KEY:
    openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)
else:
    print("⚠️ 警告: 未檢測到 OPENAI_API_KEY")
    openai_client = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="$", intents=intents)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("auth-bot")


class ConfirmView(View):
    def __init__(self, original_author, asset_data, user_input_raw):
        super().__init__(timeout=180)
        self.original_author = original_author
        self.asset_data = asset_data
        self.user_input_raw = user_input_raw

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user != self.original_author:
            await interaction.response.send_message("這不是你的資產配置喔！", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="✅ 確認正確", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        await interaction.response.defer()
        status_msg = await interaction.followup.send("🔍 正在調取市場數據並進行風險運算 (這可能需要 15-20 秒)...")
        self.stop()
        await interaction.message.edit(view=None)
        try:
            user_risk_pref = "未知"
            raw_text = self.user_input_raw
            if "保守" in raw_text or "低風險" in raw_text:
                user_risk_pref = "保守"
            elif "激進" in raw_text or "高風險" in raw_text:
                user_risk_pref = "激進"
            elif "穩健" in raw_text:
                user_risk_pref = "穩健"

            assets = self.asset_data['assets']
            metrics, total_score = analysis.fetch_market_data(assets)
            chart_buffer = analysis.generate_charts(assets, total_score)
            chart_file = discord.File(chart_buffer, filename="analysis.png")

            system_prompt = f"""
            你是一個專業的資產配置顧問。
            數據：風險分 {total_score:.1f}/100。
            用戶偏好：{user_risk_pref}。

            請給出兩段簡短評語：
            1. 風險等級與預期波動
            2. 優化建議
            """

            response = await openai_client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(assets, ensure_ascii=False)}
                ],
                max_tokens=1000
            )
            critique = response.choices[0].message.content
            await status_msg.edit(content=critique, attachments=[chart_file])
        except Exception as e:
            await status_msg.edit(content=f"❌ 分析錯誤: {str(e)}")

    @discord.ui.button(label="❌ 修改", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_message("已取消。", ephemeral=True)
        self.stop()
        await interaction.message.edit(view=None)


@bot.command(name="health")
async def health_check(ctx, *, user_input: str = None):
    if not ENABLE_HEALTH_FLOW:
        await ctx.send("⚠️ 目前 `$health` 功能已暫停啟用。")
        return

    if not openai_client:
        await ctx.send("❌ 錯誤：Bot 尚未設定 OpenAI API Key。")
        return

    if not user_input:
        await ctx.send("請輸入您的配置，例如：`$health 50% VOO, 50% 現金`")
        return


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip().lower()
    if not content:
        logger.warning("[discord] empty message content received (check MESSAGE CONTENT INTENT in Discord Developer Portal): guild=%s channel=%s user=%s", getattr(message.guild, "id", "dm"), message.channel.id, message.author.id)
        await bot.process_commands(message)
        return
    m = re.fullmatch(r"a(\d{4,6})", content)
    if m:
        stock_code = m.group(1)
        logger.info("[warrant-cmd] trigger received: user=%s stock=%s channel=%s", message.author.id, stock_code, message.channel.id)
        loading = await message.channel.send("最佳權證查詢中⏳ ~")
        try:
            logger.info("[warrant-cmd] start fetching: stock=%s", stock_code)
            result = fetch_warrant_results(stock_code)
            logger.info("[warrant-cmd] fetch done: stock=%s source=%s total_found=%s", stock_code, result.get("source"), result.get("total_found"))
            warrants = result.get("warrants", [])
            if not warrants:
                logger.info("[warrant-cmd] no result: stock=%s source=%s", stock_code, result.get("source", "none"))
                await loading.edit(content=f"找不到 `{stock_code}` 可用權證資料（來源：{result.get('source', 'none')}）。")
                return

            image_path = render_warrant_card_image(stock_code, result)
            card_file = discord.File(image_path, filename=f"warrant_{stock_code}.png")
            await loading.edit(content="")
            await message.channel.send(file=card_file)
            logger.info("[warrant-cmd] response sent as image: stock=%s count=%d", stock_code, len(warrants[:10]))
        except Exception as e:
            logger.exception("[warrant-cmd] failed: stock=%s", stock_code)
            await loading.edit(content=f"❌ 指令執行失敗：{e}")
        return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    logger.info("[startup] Bot is ready: %s (id=%s)", bot.user, bot.user.id if bot.user else "unknown")


if __name__ == "__main__":
    logger.info("[startup] booting auth-bot")
    if not DISCORD_TOKEN:
        present_keys = [k for k in ("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "discord_token") if os.getenv(k)]
        logger.error("[startup] DISCORD_TOKEN is missing. Bot will not start. Checked keys=DISCORD_TOKEN/DISCORD_BOT_TOKEN/discord_token, present=%s", present_keys)
        raise SystemExit(1)
    logger.info("[startup] DISCORD_TOKEN detected, starting Discord client")
    bot.run(DISCORD_TOKEN)

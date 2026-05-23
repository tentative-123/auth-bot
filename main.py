import os
import re
import json
import discord
from discord.ext import commands
from discord.ui import Button, View
from openai import AsyncOpenAI

import analysis
from services.warrant_screener import fetch_warrant_results

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
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
    m = re.fullmatch(r"a(\d{4,6})", content)
    if m:
        stock_code = m.group(1)
        loading = await message.channel.send(f"🔎 正在篩選 {stock_code} 的認購權證，請稍候...")
        try:
            result = fetch_warrant_results(stock_code)
            warrants = result.get("warrants", [])
            if not warrants:
                await loading.edit(content=f"找不到 `{stock_code}` 可用權證資料（來源：{result.get('source', 'none')}）。")
                return

            embed = discord.Embed(
                title=f"{stock_code} 認購權證清單",
                description=(
                    f"來源：{result.get('source', 'N/A')}｜"
                    f"母股價：{result.get('stock_price') or 'N/A'}｜"
                    f"符合筆數：{result.get('total_found', 0)}"
                ),
                color=discord.Color.blue(),
            )
            for idx, w in enumerate(warrants[:10], start=1):
                embed.add_field(
                    name=f"#{idx} {w.get('code', 'N/A')} {w.get('name', '')}",
                    value=(
                        f"天數: {w.get('days', 'N/A')}｜OTM: {w.get('otm_str', 'N/A')}\n"
                        f"價: {w.get('price', 0)}｜量: {w.get('volume', 0)}\n"
                        f"槓桿: {w.get('lev', 'N/A')}｜分數: {w.get('_score', 'N/A')}"
                    ),
                    inline=False,
                )
            await loading.edit(content="", embed=embed)
        except Exception as e:
            await loading.edit(content=f"❌ 指令執行失敗：{e}")
        return

    await bot.process_commands(message)


@bot.event
async def on_ready():
    print(f"Bot is ready: {bot.user}")


if __name__ == "__main__":
    if DISCORD_TOKEN:
        bot.run(DISCORD_TOKEN)

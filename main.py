import os
import asyncio
import re
import logging
import discord
from discord.ext import commands

from services.subscription_manager import SubscriptionManager
from services.warrant_screener import fetch_warrant_results
from services.warrant_card_renderer import render_warrant_card_image

DISCORD_TOKEN = (
    os.getenv("DISCORD_TOKEN")
    or os.getenv("DISCORD_BOT_TOKEN")
    or os.getenv("discord_token")
)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="$", intents=intents)
subscription_manager = SubscriptionManager(bot)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("auth-bot")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip().lower()
    if not content:
        logger.warning(
            "[discord] empty message content received (check MESSAGE CONTENT INTENT in Discord Developer Portal): guild=%s channel=%s user=%s",
            getattr(message.guild, "id", "dm"),
            message.channel.id,
            message.author.id,
        )
        await bot.process_commands(message)
        return

    m = re.fullmatch(r"a(\d{4,6})", content)
    if m:
        stock_code = m.group(1)
        logger.info("[warrant-cmd] trigger received: user=%s stock=%s channel=%s", message.author.id, stock_code, message.channel.id)
        loading = await message.channel.send("最佳權證查詢中⏳ ~")
        try:
            logger.info("[warrant-cmd] start fetching: stock=%s", stock_code)
            result = await asyncio.to_thread(fetch_warrant_results, stock_code)
            logger.info(
                "[warrant-cmd] fetch done: stock=%s source=%s total_found=%s",
                stock_code,
                result.get("source"),
                result.get("total_found"),
            )
            warrants = result.get("warrants", [])
            if not warrants:
                logger.info("[warrant-cmd] no result: stock=%s source=%s", stock_code, result.get("source", "none"))
                await loading.edit(content=f"找不到 `{stock_code}` 可用權證資料（來源：{result.get('source', 'none')}）。")
                return

            try:
                image_path = await asyncio.to_thread(render_warrant_card_image, stock_code, result)
                card_file = discord.File(image_path, filename=f"warrant_{stock_code}.png")
                await loading.edit(content="✅ 查詢完成，正在送出圖卡…")
                await message.channel.send(content="📊 最佳權證一頁式圖卡", file=card_file)
                await loading.edit(content="✅ 圖卡已送出")
                logger.info("[warrant-cmd] response sent as image: stock=%s count=%d", stock_code, len(warrants[:10]))
            except Exception as render_err:
                logger.exception("[warrant-cmd] image render failed, fallback to embed: stock=%s", stock_code)
                embed = discord.Embed(
                    title=f"{stock_code} 認購權證清單",
                    description=(
                        f"來源：{result.get('source', 'N/A')}｜"
                        f"母股價：{result.get('stock_price') or 'N/A'}｜"
                        f"符合筆數：{result.get('total_found', 0)}\n"
                        f"⚠️ 圖卡渲染失敗，改用文字卡（{type(render_err).__name__}）"
                    ),
                    color=discord.Color.orange(),
                )
                for idx, w in enumerate(warrants[:10], start=1):
                    embed.add_field(
                        name=f"#{idx} {w.get('code', 'N/A')} {w.get('name', '')}",
                        value=(
                            f"天數: {w.get('days', 'N/A')}｜OTM: {w.get('otm_str', 'N/A')}\n"
                            f"昨收: {w.get('price', 0)}｜今價: {w.get('price_today', 'N/A')}｜量: {w.get('volume', 0)}\n"
                            f"槓桿: {w.get('lev', 'N/A')}｜分數: {w.get('_score', 'N/A')}"
                        ),
                        inline=False,
                    )
                await loading.edit(content="⚠️ 圖卡渲染失敗，改用文字卡", embed=embed)
        except Exception as e:
            logger.exception("[warrant-cmd] failed: stock=%s", stock_code)
            await loading.edit(content=f"❌ 指令執行失敗：{e}")
        return

    await bot.process_commands(message)


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if await subscription_manager.handle_interaction(interaction):
        return


@bot.event
async def on_ready():
    logger.info("[startup] Bot is ready: %s (id=%s)", bot.user, bot.user.id if bot.user else "unknown")
    subscription_manager.start()


if __name__ == "__main__":
    logger.info("[startup] booting auth-bot")
    if not DISCORD_TOKEN:
        present_keys = [k for k in ("DISCORD_TOKEN", "DISCORD_BOT_TOKEN", "discord_token") if os.getenv(k)]
        logger.error(
            "[startup] DISCORD_TOKEN is missing. Bot will not start. Checked keys=DISCORD_TOKEN/DISCORD_BOT_TOKEN/discord_token, present=%s",
            present_keys,
        )
        raise SystemExit(1)
    logger.info("[startup] DISCORD_TOKEN detected, starting Discord client")
    bot.run(DISCORD_TOKEN)

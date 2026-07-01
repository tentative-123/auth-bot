import os
import asyncio
import re
import logging
import time
import discord
from discord.ext import commands

from services.subscription_manager import SubscriptionManager
from services.warrant_screener import fetch_single_warrant_detail, fetch_warrant_results
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

WARRANT_CACHE_TTL_SECONDS = int(os.getenv("WARRANT_CACHE_TTL_SECONDS", "3600") or 3600)
warrant_query_queue: asyncio.Queue[dict] = asyncio.Queue()
warrant_cache: dict[str, tuple[float, dict]] = {}
warrant_worker_task: asyncio.Task | None = None
warrant_query_active = False

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
logger = logging.getLogger("auth-bot")

def _warrant_allowed_channel_ids() -> set[int]:
    raw = os.getenv("WARRANT_ALLOWED_CHANNEL_IDS", "").strip()
    return {int(item.strip()) for item in raw.split(",") if item.strip().isdigit()}


def _is_warrant_channel_allowed(channel_id: int) -> bool:
    allowed_ids = _warrant_allowed_channel_ids()
    return not allowed_ids or channel_id in allowed_ids


def _get_cached_warrant_result(stock_code: str) -> dict | None:
    cached = warrant_cache.get(stock_code)
    if not cached:
        return None
    cached_at, result = cached
    if time.monotonic() - cached_at > WARRANT_CACHE_TTL_SECONDS:
        warrant_cache.pop(stock_code, None)
        return None
    return result


async def _warrant_query_worker():
    global warrant_query_active
    while True:
        job = await warrant_query_queue.get()
        warrant_query_active = True
        stock_code = job["stock_code"]
        future = job["future"]
        try:
            result = _get_cached_warrant_result(stock_code)
            from_cache = result is not None
            if from_cache:
                logger.info("[warrant-cmd] cache hit: stock=%s", stock_code)
            else:
                logger.info("[warrant-cmd] start fetching: stock=%s", stock_code)
                result = await asyncio.to_thread(fetch_warrant_results, stock_code)
                warrant_cache[stock_code] = (time.monotonic(), result)
            if not future.done():
                future.set_result((result, from_cache))
        except Exception as exc:
            if not future.done():
                future.set_exception(exc)
        finally:
            warrant_query_active = False
            warrant_query_queue.task_done()



def _fmt_value(value, suffix: str = "") -> str:
    if value is None or value == "":
        return "N/A"
    return f"{value}{suffix}"


def _build_warrant_detail_embed(detail: dict) -> discord.Embed:
    code = detail.get("code", "N/A")
    name = detail.get("name") or "N/A"
    sigma = detail.get("sigma")
    sigma_text = f"{sigma:.1%}" if isinstance(sigma, (int, float)) else "N/A"
    outstanding_ratio = detail.get("outstanding_ratio")
    outstanding_text = f"{outstanding_ratio:.2f}%" if isinstance(outstanding_ratio, (int, float)) else "N/A"
    lev = detail.get("lev")
    lev_text = f"{lev}x" if lev is not None else "N/A"
    dj = detail.get("dj_ratio")
    dj_text = f"{dj:.2f}%" if isinstance(dj, (int, float)) else "N/A"
    description = (
        f"**標的代號**：{_fmt_value(detail.get('underlying_code'))}\n"
        f"**權證昨收 / 現價**：{_fmt_value(detail.get('price_prev'))} / {_fmt_value(detail.get('price_today'))}\n"
        f"**買一 / 賣一**：{_fmt_value(detail.get('bid_px'))} / {_fmt_value(detail.get('ask_px'))}\n"
        f"**剩餘天數**：{_fmt_value(detail.get('days'), '天')}　"
        f"**履約價**：{_fmt_value(detail.get('strike'))}\n"
        f"**行使比例**：{_fmt_value(detail.get('exercise_ratio'))}　"
        f"**近日成交量**：{_fmt_value(detail.get('volume'))}\n"
        f"**隱波 / 在外流通率**：{sigma_text} / {outstanding_text}\n"
        f"**槓桿 / 差槓比**：{lev_text} / {dj_text}"
    )
    embed = discord.Embed(
        title=f"{code} / {name}",
        description=description,
        color=discord.Color.blue(),
    )
    embed.set_footer(text="股市艾斯權證小工具")
    return embed

def _start_warrant_query_worker():
    global warrant_worker_task
    if warrant_worker_task is None or warrant_worker_task.done():
        warrant_worker_task = asyncio.create_task(_warrant_query_worker())
        logger.info("[warrant-cmd] queue worker started")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()
    if not content:
        logger.warning(
            "[discord] empty message content received (check MESSAGE CONTENT INTENT in Discord Developer Portal): guild=%s channel=%s user=%s",
            getattr(message.guild, "id", "dm"),
            message.channel.id,
            message.author.id,
        )
        await bot.process_commands(message)
        return

    m = re.fullmatch(r"a((?:\d{4,6}|\d{5}[a-z])(?:\.tw)?)", content, re.IGNORECASE)
    if m:
        if not _is_warrant_channel_allowed(message.channel.id):
            logger.info("[warrant-cmd] ignored outside allowed channel: user=%s channel=%s", message.author.id, message.channel.id)
            return
        stock_code = m.group(1).upper().removesuffix(".TW")
        logger.info("[warrant-cmd] trigger received: user=%s stock=%s channel=%s", message.author.id, stock_code, message.channel.id)
        if re.fullmatch(r"\d{6}", stock_code):
            loading = await message.channel.send("權證參數查詢中⏳ ~")
            try:
                detail = await asyncio.to_thread(fetch_single_warrant_detail, stock_code)
                if detail.get("source") == "none":
                    await loading.edit(content=f"`{stock_code}` 無符合or可用的權證資料。")
                    return
                await loading.edit(content="✅ 權證參數查詢完成", embed=_build_warrant_detail_embed(detail))
            except Exception as e:
                logger.exception("[warrant-detail] failed: warrant=%s", stock_code)
                await loading.edit(content=f"❌ 權證參數查詢失敗：{e}")
            return

        queue_position = warrant_query_queue.qsize() + (1 if warrant_query_active else 0) + 1
        loading = await message.channel.send(f"最佳權證查詢排隊中⏳（目前第 {queue_position} 位）")
        try:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            await warrant_query_queue.put({"stock_code": stock_code, "future": future})
            result, from_cache = await future
            logger.info(
                "[warrant-cmd] fetch done: stock=%s source=%s total_found=%s cache=%s",
                stock_code,
                result.get("source"),
                result.get("total_found"),
                from_cache,
            )
            warrants = result.get("warrants", [])
            if not warrants:
                logger.info("[warrant-cmd] no result: stock=%s source=%s", stock_code, result.get("source", "none"))
                await loading.edit(content=f"`{stock_code}` 無符合or可用的權證資料。")
                return

            try:
                image_path = await asyncio.to_thread(render_warrant_card_image, stock_code, result)
                card_file = discord.File(image_path, filename=f"warrant_{stock_code}.png")
                done_prefix = "✅ 使用一小時內快取結果" if from_cache else "✅ 查詢完成"
                await loading.edit(content=f"{done_prefix}，正在送出圖卡…")
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
    _start_warrant_query_worker()
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

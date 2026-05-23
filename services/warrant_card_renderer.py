import os
import tempfile
from pathlib import Path
from glob import glob
import subprocess
import requests

from PIL import Image, ImageDraw, ImageFont

FONT_LOCAL = Path("NotoSansTC-Regular.ttf")
FONT_URL = "https://github.com/googlefonts/noto-cjk/raw/main/Sans/OTF/TraditionalChinese/NotoSansCJKtc-Regular.otf"


def _ensure_cjk_font_file() -> str | None:
    if FONT_LOCAL.exists() and FONT_LOCAL.stat().st_size > 0:
        return str(FONT_LOCAL)
    try:
        r = requests.get(FONT_URL, timeout=20)
        r.raise_for_status()
        FONT_LOCAL.write_bytes(r.content)
        return str(FONT_LOCAL)
    except Exception:
        return None


def _pick_font(size: int):
    candidates = []
    ensured = _ensure_cjk_font_file()
    if ensured:
        candidates.append(ensured)

    candidates.extend([
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ])
    candidates.extend(glob('/nix/store/*noto-fonts-cjk*/share/fonts/opentype/noto/*.ttc'))
    candidates.extend(glob('/nix/store/*noto-fonts-cjk*/share/fonts/opentype/noto/*.otf'))

    try:
        out = subprocess.check_output(['fc-list', ':lang=zh', 'file'], text=True, stderr=subprocess.DEVNULL)
        for line in out.splitlines():
            fp = line.strip().split(':', 1)[0]
            if fp:
                candidates.append(fp)
    except Exception:
        pass

    seen = set()
    for fp in candidates:
        if not fp or fp in seen:
            continue
        seen.add(fp)
        if os.path.isfile(fp):
            try:
                return ImageFont.truetype(fp, size), fp
            except Exception:
                continue
    return ImageFont.load_default(), 'PIL_DEFAULT'


def _dot(draw: ImageDraw.ImageDraw, x: int, y: int, color: str):
    cmap = {"green": (8, 184, 63), "yellow": (243, 195, 0), "red": (227, 54, 54)}
    c = cmap.get(color, (120, 120, 120))
    draw.ellipse((x, y, x + 26, y + 26), fill=c)


def _vol_color(v: float) -> str:
    return "green" if v >= 500 else "yellow" if v >= 100 else "red"


def _day_color(days: int) -> str:
    return "green" if 90 <= days <= 180 else "yellow"


def _otm_color(otm: str) -> str:
    return "green" if isinstance(otm, str) and otm.startswith("外") else "yellow"


def _dj_color(dj) -> str:
    if isinstance(dj, (int, float)):
        if dj <= 0.3:
            return "green"
        if dj <= 0.6:
            return "yellow"
    return "red"


def _lev_color(lev) -> str:
    if isinstance(lev, (int, float)) and lev <= 2.5:
        return "yellow"
    return "red"


def render_warrant_card_image(stock_code: str, result: dict) -> str:
    warrants = result.get("warrants", [])[:10]
    stock_price = result.get("stock_price")
    source = result.get("source", "N/A")
    total_found = result.get("total_found", 0)

    W, H = 1600, 2200
    img = Image.new("RGB", (W, H), (219, 230, 235))
    draw = ImageDraw.Draw(img)

    f_title, _ = _pick_font(82)
    f_meta, _ = _pick_font(56)
    f_sub, _ = _pick_font(34)
    f_notice, _ = _pick_font(30)
    f_th, _ = _pick_font(38)
    f_row1, _ = _pick_font(44)
    f_row2, _ = _pick_font(36)
    f_foot, _ = _pick_font(34)

    card_x, card_y = 20, 20
    card_w, card_h = W - 40, H - 40
    draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), radius=16, fill=(229, 242, 247), outline=(150, 179, 192), width=2)
    header_bottom = card_y + 300
    draw.rectangle((card_x + 1, card_y + 1, card_x + card_w - 1, header_bottom), fill=(211, 236, 246))
    draw.rectangle((card_x + 1, header_bottom, card_x + card_w - 1, card_y + card_h - 1), fill=(255, 255, 255))

    draw.text((46, 38), "認購權證篩選", font=f_title, fill=(13, 77, 123))
    px = "N/A" if stock_price is None else f"{float(stock_price):.2f}"
    draw.text((46, 130), f"{stock_code}  現價 {px}", font=f_meta, fill=(59, 120, 165))
    draw.text((46, 222), f"{source}・依筆數排序・共 {total_found} 筆", font=f_sub, fill=(78, 140, 176))
    notice = "股市艾斯出品，請勿轉傳"
    notice_bbox = draw.textbbox((0, 0), notice, font=f_notice)
    notice_w = notice_bbox[2] - notice_bbox[0]
    draw.text((card_x + card_w - notice_w - 16, card_y + 8), notice, font=f_notice, fill=(77, 109, 126))

    col_x = [46, 700, 900, 1080, 1260, 1410]
    headers = ["量", "現價", "天數", "價外 %", "差槓比", "槓桿"]
    y0 = 334
    for i, h in enumerate(headers):
        draw.text((col_x[i], y0), h, font=f_th, fill=(60, 60, 60))

    y = 394
    row_h = 175
    for w in warrants:
        draw.line((card_x + 12, y - 8, card_x + card_w - 12, y - 8), fill=(199, 220, 229), width=1)
        code = str(w.get("code", ""))
        name = str(w.get("name", ""))
        vol = float(w.get("volume", 0) or 0)
        price = w.get("price")
        days = int(w.get("days", 0) or 0)
        otm = str(w.get("otm_str", "-"))
        dj = w.get("dj_ratio")
        lev = w.get("lev")

        draw.text((col_x[0], y), f"{code} {name}", font=f_row1, fill=(18, 30, 42))
        _dot(draw, col_x[0], y + 64, _vol_color(vol))
        draw.text((col_x[0] + 34, y + 56), f"{int(vol):,}張", font=f_row2, fill=(35, 35, 35))

        price_text = "-" if price is None else f"{float(price):.2f}"
        draw.text((col_x[1], y + 8), price_text, font=f_row2, fill=(35, 35, 35))
        _dot(draw, col_x[2], y + 18, _day_color(days)); draw.text((col_x[2] + 32, y + 8), f"{days}天", font=f_row2, fill=(35, 35, 35))
        _dot(draw, col_x[3], y + 18, _otm_color(otm)); draw.text((col_x[3] + 32, y + 8), otm, font=f_row2, fill=(35, 35, 35))
        dj_text = "-" if dj is None else f"{dj:.2f}%"
        _dot(draw, col_x[4], y + 18, _dj_color(dj)); draw.text((col_x[4] + 32, y + 8), dj_text, font=f_row2, fill=(35, 35, 35))
        lev_text = "-" if lev is None else f"{lev}x"
        _dot(draw, col_x[5], y + 18, _lev_color(lev)); draw.text((col_x[5] + 32, y + 8), lev_text, font=f_row2, fill=(35, 35, 35))
        y += row_h

    draw.line((card_x + 12, card_y + card_h - 105, card_x + card_w - 12, card_y + card_h - 105), fill=(188, 211, 221), width=2)
    foot = ["量≥500", "90-180天", "外≤10%", "槓≤5x"]
    x = 40
    for t in foot:
        draw.text((x, card_y + card_h - 78), t, font=f_foot, fill=(35, 35, 35))
        x += 370

    tmp = tempfile.mkdtemp(prefix='warrant-card-')
    out = Path(tmp) / f"warrant_{stock_code}.png"
    img.save(out)
    return str(out)

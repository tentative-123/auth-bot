import os
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _pick_font(size: int):
    candidates = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for fp in candidates:
        if os.path.isfile(fp):
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _dot(draw: ImageDraw.ImageDraw, x: int, y: int, color: str):
    cmap = {"green": (8, 184, 63), "yellow": (243, 195, 0), "red": (227, 54, 54)}
    c = cmap.get(color, (120, 120, 120))
    draw.ellipse((x, y, x + 24, y + 24), fill=c)


def _vol_color(v: float) -> str:
    if v >= 500:
        return "green"
    if v >= 100:
        return "yellow"
    return "red"


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

    W, H = 1800, 2400
    img = Image.new("RGB", (W, H), (219, 230, 235))
    draw = ImageDraw.Draw(img)

    f_title = _pick_font(96)
    f_meta = _pick_font(72)
    f_sub = _pick_font(50)
    f_th = _pick_font(42)
    f_row1 = _pick_font(48)
    f_row2 = _pick_font(42)
    f_foot = _pick_font(42)

    card_x, card_y = 20, 20
    card_w, card_h = W - 28, H - 28
    draw.rounded_rectangle((card_x, card_y, card_x + card_w, card_y + card_h), radius=14, fill=(229, 242, 247), outline=(150, 179, 192), width=2)
    draw.rectangle((card_x + 1, card_y + 1, card_x + card_w - 1, card_y + 270), fill=(211, 236, 246))

    draw.text((50, 48), "🎯 認購權證篩選", font=f_title, fill=(13, 77, 123))
    px = "N/A" if stock_price is None else f"{float(stock_price):.2f}"
    draw.text((50, 134), f"{stock_code}  現價 {px}", font=f_meta, fill=(59, 120, 165))
    draw.text((50, 210), f"⚡ {source}・依筆數排序・共 {total_found} 筆", font=f_sub, fill=(78, 140, 176))

    col_x = [50, 820, 1080, 1310, 1540]
    headers = ["量", "天數", "價外 %", "差槓比", "槓桿"]
    y0 = 315
    for i,h in enumerate(headers):
        draw.text((col_x[i], y0), h, font=f_th, fill=(122, 138, 147))

    y = 380
    row_h = 180
    for w in warrants:
        draw.line((card_x+12, y-8, card_x+card_w-12, y-8), fill=(199,220,229), width=1)
        code = str(w.get("code", ""))
        name = str(w.get("name", ""))
        vol = float(w.get("volume", 0) or 0)
        days = int(w.get("days", 0) or 0)
        otm = str(w.get("otm_str", "-"))
        dj = w.get("dj_ratio")
        lev = w.get("lev")

        draw.text((col_x[0], y), f"{code} {name}", font=f_row1, fill=(36, 63, 119))
        _dot(draw, col_x[0], y+72, _vol_color(vol))
        draw.text((col_x[0]+34, y+58), f"{int(vol):,}張", font=f_row2, fill=(47, 159, 83))

        _dot(draw, col_x[1], y+100, _day_color(days)); draw.text((col_x[1]+24, y+10), f"{days}天", font=f_row2, fill=(29, 53, 80))
        _dot(draw, col_x[2], y+100, _otm_color(otm)); draw.text((col_x[2]+24, y+10), otm, font=f_row2, fill=(29, 53, 80))
        dj_text = "-" if dj is None else f"{dj:.2f}%"
        _dot(draw, col_x[3], y+100, _dj_color(dj)); draw.text((col_x[3]+24, y+10), dj_text, font=f_row2, fill=(29, 53, 80))
        lev_text = "-" if lev is None else f"{lev}x"
        _dot(draw, col_x[4], y+100, _lev_color(lev)); draw.text((col_x[4]+24, y+10), lev_text, font=f_row2, fill=(29, 53, 80))
        y += row_h

    draw.line((card_x+12, card_y+card_h-95, card_x+card_w-12, card_y+card_h-95), fill=(188,211,221), width=2)
    foot = ["量≥500", "90-180天", "外≤10%", "槓≤5x"]
    x = 40
    for t in foot:
        draw.text((x, card_y+card_h-78), t, font=f_foot, fill=(90, 165, 112))
        x += 420

    tmp = tempfile.mkdtemp(prefix='warrant-card-')
    out = Path(tmp) / f"warrant_{stock_code}.png"
    img.save(out)
    return str(out)

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
    ])
    candidates.extend(glob('/nix/store/*noto-fonts-cjk*/share/fonts/opentype/noto/*.ttc'))
    try:
        out = subprocess.check_output(['fc-list', ':lang=zh', 'file'], text=True, stderr=subprocess.DEVNULL)
        candidates.extend([ln.split(':',1)[0].strip() for ln in out.splitlines() if ':' in ln])
    except Exception:
        pass

    seen = set()
    for fp in candidates:
        if fp and fp not in seen and os.path.isfile(fp):
            seen.add(fp)
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _dot(draw, x, y, color):
    cmap = {"green": (8,184,63), "yellow": (243,195,0), "red": (227,54,54)}
    draw.ellipse((x, y, x+22, y+22), fill=cmap.get(color, (120,120,120)))


def render_warrant_card_image(stock_code: str, result: dict) -> str:
    warrants = result.get("warrants", [])[:10]
    stock_price = result.get("stock_price")
    source = result.get("source", "N/A")
    total_found = result.get("total_found", 0)

    W, H = 1600, 2200
    img = Image.new("RGB", (W, H), (231, 241, 246))
    draw = ImageDraw.Draw(img)

    f_title = _pick_font(84)
    f_meta = _pick_font(62)
    f_sub = _pick_font(42)
    f_warn = _pick_font(24)
    f_th = _pick_font(40)
    f_row1 = _pick_font(44)
    f_row2 = _pick_font(38)
    f_foot = _pick_font(34)

    cx, cy = 20, 20
    cw, ch = W-40, H-40
    draw.rounded_rectangle((cx, cy, cx+cw, cy+ch), radius=16, fill=(231,241,246), outline=(150,179,192), width=2)

    # header (blue)
    draw.rectangle((cx+1, cy+1, cx+cw-1, cy+300), fill=(206,231,243))
    draw.text((48, 36), "🎯 認購權證篩選", font=f_title, fill=(16,76,122))
    px = "N/A" if stock_price is None else f"{float(stock_price):.2f}"
    draw.text((48, 126), f"{stock_code}  現價 {px}", font=f_meta, fill=(62,124,169))
    draw.text((48, 206), f"⚡ {source}・依筆數排序・共 {total_found} 筆", font=f_sub, fill=(84,142,176))
    draw.text((cx+cw-420, 28), "股市艾斯出品，請勿轉傳", font=f_warn, fill=(95,105,115))

    # data panel (white + black text)
    draw.rectangle((cx+1, cy+301, cx+cw-1, cy+ch-1), fill=(255,255,255))

    col_x = [48, 760, 985, 1200, 1380]
    headers = ["量", "天數", "價外 %", "差槓比", "槓桿"]
    hy = 344
    for i,hh in enumerate(headers):
        draw.text((col_x[i], hy), hh, font=f_th, fill=(25,25,25))

    y = 408
    row_h = 172
    for w in warrants:
        draw.line((cx+12, y-8, cx+cw-12, y-8), fill=(226,226,226), width=1)
        code = str(w.get("code", ""))
        name = str(w.get("name", ""))
        vol = int(float(w.get("volume",0) or 0))
        days = int(w.get("days",0) or 0)
        otm = str(w.get("otm_str","-"))
        dj = w.get("dj_ratio")
        lev = w.get("lev")

        draw.text((col_x[0], y), f"{code} {name}", font=f_row1, fill=(20,20,20))
        _dot(draw, col_x[0], y+62, "green" if vol>=500 else "yellow" if vol>=100 else "red")
        draw.text((col_x[0]+32, y+54), f"{vol:,}張", font=f_row2, fill=(20,20,20))

        _dot(draw, col_x[1], y+20, "green" if 90<=days<=180 else "yellow")
        draw.text((col_x[1]+30, y+10), f"{days}天", font=f_row2, fill=(20,20,20))

        _dot(draw, col_x[2], y+20, "green" if otm.startswith("外") else "yellow")
        draw.text((col_x[2]+30, y+10), otm, font=f_row2, fill=(20,20,20))

        dj_text = "-" if dj is None else f"{dj:.2f}%"
        dj_color = "green" if isinstance(dj,(int,float)) and dj<=0.3 else "yellow" if isinstance(dj,(int,float)) and dj<=0.6 else "red"
        _dot(draw, col_x[3], y+20, dj_color)
        draw.text((col_x[3]+30, y+10), dj_text, font=f_row2, fill=(20,20,20))

        lev_text = "-" if lev is None else f"{lev}x"
        _dot(draw, col_x[4], y+20, "yellow" if isinstance(lev,(int,float)) and lev<=2.5 else "red")
        draw.text((col_x[4]+30, y+10), lev_text, font=f_row2, fill=(20,20,20))
        y += row_h

    draw.line((cx+12, cy+ch-105, cx+cw-12, cy+ch-105), fill=(226,226,226), width=2)
    for i,t in enumerate(["量≥500","90-180天","外≤10%","槓≤5x"]):
        draw.text((42+i*370, cy+ch-78), t, font=f_foot, fill=(70,150,95))

    tmp = tempfile.mkdtemp(prefix='warrant-card-')
    out = Path(tmp)/f"warrant_{stock_code}.png"
    img.save(out)
    return str(out)

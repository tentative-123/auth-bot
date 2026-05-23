import html
import os
import tempfile
from pathlib import Path
from typing import Any


def _dot(value: str, color: str) -> str:
    return f"<span class='dot {color}'></span>{html.escape(value)}"


def _fmt_pct(v: Any) -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v) * 100:.1f}%"
    except Exception:
        return str(v)


def build_warrant_html(stock_code: str, result: dict) -> str:
    stock_price = result.get("stock_price")
    source = result.get("source", "N/A")
    total_found = result.get("total_found", 0)
    warrants = result.get("warrants", [])[:10]

    rows = []
    for w in warrants:
        vol = w.get("volume", 0)
        days = w.get("days", "-")
        otm = w.get("otm_str", "-")
        dj = w.get("dj_ratio")
        lev = w.get("lev")

        vol_color = "green" if isinstance(vol, (int, float)) and vol >= 500 else ("yellow" if isinstance(vol, (int, float)) and vol >= 100 else "red")
        day_color = "green" if isinstance(days, (int, float)) and 90 <= days <= 180 else "yellow"
        otm_color = "green" if isinstance(otm, str) and "外" in otm else "yellow"
        dj_color = "green" if isinstance(dj, (int, float)) and dj <= 0.3 else ("yellow" if isinstance(dj, (int, float)) and dj <= 0.6 else "red")
        lev_color = "green" if isinstance(lev, (int, float)) and lev <= 5 else "red"

        rows.append(
            f"""
            <tr>
              <td><div class='code'>{html.escape(str(w.get('code', '')))} {html.escape(str(w.get('name', '')))}</div><div class='sub'>{_dot(f'{vol} 張', vol_color)}</div></td>
              <td>{_dot(f'{days} 天', day_color)}</td>
              <td>{_dot(str(otm), otm_color)}</td>
              <td>{_dot('-' if dj is None else f'{dj:.2f}%', dj_color)}</td>
              <td>{_dot('-' if lev is None else f'{lev}x', lev_color)}</td>
            </tr>
            """
        )

    return f"""
<!doctype html>
<html>
<head>
<meta charset='utf-8'>
<style>
  body {{ margin: 0; padding: 12px; background: #edf5f7; font-family: 'Noto Sans TC', 'Microsoft JhengHei', sans-serif; }}
  .card {{ background:#e5f2f7; border:1px solid #b8d2dc; border-radius:10px; padding:14px; width:760px; }}
  .title {{ font-size:34px; font-weight:800; color:#0f4f7d; }}
  .meta {{ font-size:38px; color:#2f6fa0; font-weight:700; margin-top:8px; }}
  .submeta {{ margin-top:6px; font-size:24px; color:#4b88ad; font-weight:700; }}
  table {{ width:100%; border-collapse:collapse; margin-top:14px; font-size:28px; }}
  th {{ text-align:left; color:#6f7f87; font-weight:700; padding:6px 4px; border-bottom:1px solid #c8dbe3; }}
  td {{ padding:8px 4px; border-bottom:1px solid #d8e8ee; color:#244459; font-weight:700; }}
  .code {{ color:#233a73; font-weight:800; }}
  .sub {{ color:#2f9e44; font-size:24px; margin-top:3px; }}
  .dot {{ display:inline-block; width:18px; height:18px; border-radius:50%; margin-right:8px; vertical-align:middle; }}
  .green {{ background:#1dbf4f; }}
  .yellow {{ background:#ffcc00; }}
  .red {{ background:#e53935; }}
  .foot {{ margin-top:10px; font-size:22px; color:#4fa56e; font-weight:700; display:flex; gap:32px; }}
</style>
</head>
<body>
  <div class='card'>
    <div class='title'>🎯 認購權證篩選</div>
    <div class='meta'>{html.escape(stock_code)}  現價 {stock_price if stock_price is not None else 'N/A'}</div>
    <div class='submeta'>⚡ 來源：{html.escape(str(source))}・符合條件/樣本排序・共 {total_found} 筆</div>
    <table>
      <thead><tr><th>標的</th><th>天數</th><th>價外 %</th><th>差槓比</th><th>槓桿</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <div class='foot'><span>量 ≥ 500</span><span>90-180 天</span><span>外 ≤ 10%</span><span>槓 ≤ 5x</span></div>
  </div>
</body>
</html>
"""


def render_warrant_card_image(stock_code: str, result: dict) -> str:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    html_content = build_warrant_html(stock_code, result)
    tmp_dir = tempfile.mkdtemp(prefix="warrant-card-")
    html_path = Path(tmp_dir) / "card.html"
    png_path = Path(tmp_dir) / f"warrant_{stock_code}.png"
    html_path.write_text(html_content, encoding="utf-8")

    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=840,1500")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.get(f"file://{os.path.abspath(html_path)}")
        driver.save_screenshot(str(png_path))
    finally:
        driver.quit()

    return str(png_path)

import html
import os
import shutil
import tempfile
from pathlib import Path


def _dot(color: str) -> str:
    return f"<span class='dot {color}'></span>"


def _level_color_by_volume(v: float) -> str:
    if v >= 500:
        return "green"
    if v >= 100:
        return "yellow"
    return "red"


def _level_color_by_days(days: int) -> str:
    if 90 <= days <= 180:
        return "green"
    if 60 <= days <= 220:
        return "yellow"
    return "red"


def _level_color_by_otm(otm: str) -> str:
    # otm like 外9.1% / 內2.4%
    if not isinstance(otm, str):
        return "yellow"
    if otm.startswith("外"):
        return "green"
    if otm.startswith("內"):
        return "yellow"
    return "yellow"


def _level_color_by_dj(dj) -> str:
    if isinstance(dj, (int, float)):
        if dj <= 0.3:
            return "green"
        if dj <= 0.6:
            return "yellow"
    return "red"


def _level_color_by_lev(lev) -> str:
    if isinstance(lev, (int, float)):
        return "red" if lev > 5 else "red" if lev > 2.5 else "yellow"
    return "red"


def build_warrant_html(stock_code: str, result: dict) -> str:
    stock_price = result.get("stock_price")
    source = result.get("source", "N/A")
    total_found = result.get("total_found", 0)
    warrants = result.get("warrants", [])[:10]

    rows = []
    for w in warrants:
        code = str(w.get("code", ""))
        name = str(w.get("name", ""))
        vol = float(w.get("volume", 0) or 0)
        days = int(w.get("days", 0) or 0)
        otm_str = str(w.get("otm_str", "-"))
        dj = w.get("dj_ratio")
        lev = w.get("lev")
        price = w.get("price", "-")

        vol_color = _level_color_by_volume(vol)
        day_color = _level_color_by_days(days)
        otm_color = _level_color_by_otm(otm_str)
        dj_color = _level_color_by_dj(dj)
        lev_color = _level_color_by_lev(lev)

        dj_text = "-" if dj is None else f"{dj:.2f}%"
        lev_text = "-" if lev is None else f"{lev}x"

        rows.append(f"""
        <tr>
          <td class='wname'>
            <div class='line1'><span class='txt' style='color:#243f77;font-weight:900;'>{html.escape(code)} {html.escape(name)}</span></div>
            <div class='line2'>{_dot(vol_color)}<span class='txt' style='color:#2f9f53;font-weight:900;'>{int(vol):,}張</span></div>
          </td>
          <td class='cell'>{_dot(day_color)}<span class='txt' style='color:#1d3550;font-weight:800;'>{days}天</span></td>
          <td class='cell'>{_dot(otm_color)}<span class='txt' style='color:#1d3550;font-weight:800;'>{html.escape(otm_str)}</span></td>
          <td class='cell'>{_dot(dj_color)}<span class='txt' style='color:#1d3550;font-weight:800;'>{html.escape(dj_text)}</span></td>
          <td class='cell'>{_dot(lev_color)}<span class='txt' style='color:#1d3550;font-weight:800;'>{html.escape(lev_text)}</span></td>
        </tr>
        """)

    px = "N/A" if stock_price is None else f"{float(stock_price):.2f}"

    return f"""
<!doctype html>
<html lang='zh-TW'>
<head>
<meta charset='utf-8'>
<style>
  body {{ margin:0; padding:14px; background:#dbe6eb; font-family:'Arial','Noto Sans TC','Microsoft JhengHei',sans-serif; }}
  .card {{ width:760px; background:#e5f2f7; border:1px solid #96b3c0; border-radius:10px; overflow:hidden; }}
  .head {{ padding:14px 16px 8px; background:linear-gradient(#d7eef7,#d0e9f5); }}
  .title {{ font-size:42px; font-weight:900; color:#0d4d7b; line-height:1.05; }}
  .meta {{ margin-top:6px; font-size:40px; font-weight:800; color:#3b78a5; }}
  .sub {{ margin-top:4px; font-size:30px; color:#4e8cb0; font-weight:700; }}
  .table-wrap {{ padding:8px 12px 6px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; color:#8a99a2; font-weight:800; font-size:30px; padding:6px 4px; }}
  td {{ border-top:1px solid #c7dce5; padding:8px 4px; vertical-align:middle; font-size:34px; color:#2d4d62; font-weight:800; }}
  .wname .line1 {{ color:#243f77; font-size:38px; font-weight:900; }}
  .wname .line2 {{ color:#2f9f53; font-size:38px; font-weight:900; margin-top:2px; }}
  .cell {{ white-space:nowrap; }}
  .dot {{ display:inline-block; width:20px; height:20px; border-radius:50%; margin-right:8px; vertical-align:middle; }}
  .green {{ background:#08b83f; }}
  .yellow {{ background:#f3c300; }}
  .red {{ background:#e33636; }}
  .foot {{ border-top:1px solid #bcd3dd; padding:10px 14px 12px; color:#5aa570; font-size:34px; font-weight:800; display:flex; justify-content:space-between; }}
</style>
</head>
<body>
  <div class='card'>
    <div class='head'>
      <div class='title'><span style='color:#0d4d7b;font-weight:900;'>🎯 認購權證篩選</span></div>
      <div class='meta'><span style='color:#3b78a5;font-weight:800;'>{html.escape(stock_code)} 現價 {px}</span></div>
      <div class='sub'><span style='color:#4e8cb0;font-weight:700;'>⚡ {html.escape(str(source))}・依筆數排序・共 {total_found} 筆</span></div>
    </div>
    <div class='table-wrap'>
      <table>
        <thead><tr><th><span style='color:#7a8a93'>量</span></th><th><span style='color:#7a8a93'>天數</span></th><th><span style='color:#7a8a93'>價外 %</span></th><th><span style='color:#7a8a93'>差槓比</span></th><th><span style='color:#7a8a93'>槓桿</span></th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    <div class='foot'><span style='color:#5aa570'>量≥500</span><span style='color:#5aa570'>90-180天</span><span style='color:#5aa570'>外≤10%</span><span style='color:#5aa570'>槓≤5x</span></div>
  </div>
</body>
</html>
"""


def _resolve_exec(env_key: str, candidates: list[str]) -> str | None:
    env_path = os.getenv(env_key)
    if env_path and os.path.isfile(env_path):
        return env_path
    for name in candidates:
        found = shutil.which(name)
        if found:
            return found
    return None


def render_warrant_card_image(stock_code: str, result: dict) -> str:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    import time

    html_content = build_warrant_html(stock_code, result)
    tmp_dir = tempfile.mkdtemp(prefix="warrant-card-")
    html_path = Path(tmp_dir) / "card.html"
    png_path = Path(tmp_dir) / f"warrant_{stock_code}.png"
    html_path.write_text(html_content, encoding="utf-8")

    opts = Options()
    chrome_bin = _resolve_exec("CHROME_BIN", ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"])
    if chrome_bin:
        opts.binary_location = chrome_bin
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--hide-scrollbars")
    opts.add_argument("--window-size=1200,2200")
    driver_path = _resolve_exec("CHROMEDRIVER_PATH", ["chromedriver"])
    service = Service(executable_path=driver_path) if driver_path else Service()

    driver = webdriver.Chrome(service=service, options=opts)
    try:
        driver.get(f"file://{os.path.abspath(html_path)}")
        wait = WebDriverWait(driver, 10)
        card = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".card")))
        time.sleep(0.4)
        Path(png_path).write_bytes(card.screenshot_as_png)
    finally:
        driver.quit()

    return str(png_path)

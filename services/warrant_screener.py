import math
import re
import time
import logging
import warnings
from datetime import date, datetime, timedelta, timezone, time as _dtime

import requests

warnings.filterwarnings("ignore")
logger = logging.getLogger(__name__)

RISK_FREE_RATE = 0.015
MIN_DAYS = 90
MAX_DAYS = 180
MAX_OTM_PCT = 0.10
MIN_OTM_PCT = -0.15
TOP_N = 10
MIS_BATCH_LIMIT = 60

_BASE_HDR = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "zh-TW,zh;q=0.9",
}

_CAPITAL_HDR = {
    **_BASE_HDR,
    "Referer": (
        "https://extweb.capital.com.tw/Extproduct/Program/"
        "Warrant/IndexWarrant/WarrantSearch.html"
    ),
}

_CAPITAL_PARAMS = {
    "flag1": "9100", "flag2": "0", "flag2_value": "",
    "flag3": "C",
    "flag4": "0", "flag4_1": "0", "flag5": "0", "flag5_1": "0",
    "flag6": "0", "flag6_1": "0", "flag7": "0", "flag7_1": "0",
    "flag8": "0", "flag8_1": "0", "flag9": "0", "flag9_1": "0",
    "flag10": "0", "flag10_1": "0", "flag11": "60", "flag11_value": "0",
    "flag12": "0", "flag12_1": "0", "flag13": "0", "flag13_1": "0",
    "flag14": "0", "flag15": "0", "flag15_value": "0",
    "flag16": "2", "flag16_value": "1",
    "flag17": "0", "flag17_1": "0", "flag18": "0", "flag18_1": "0",
    "flag19": "0", "flag20": "0", "flag21": "0",
}


def _sf(v, default=None):
    try:
        return float(str(v).replace(",", "").replace("%", "").replace("▲", "").replace("▼", "").strip())
    except Exception:
        return default


def _si(v, default=0):
    try:
        return int(float(str(v).replace(",", "").strip()))
    except Exception:
        return default


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _bs_delta(S: float, K: float, T: float, r: float, sigma: float) -> float | None:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        return _norm_cdf(d1)
    except Exception:
        return None


def _parse_expiry(s: str) -> int:
    s = s.strip()
    today = date.today()
    try:
        if len(s) == 8 and s.isdigit():
            exp = date(int(s[:4]), int(s[4:6]), int(s[6:8]))
        elif "/" in s:
            p = s.split("/")
            exp = date(int(p[0]), int(p[1]), int(p[2]))
        elif "-" in s:
            p = s.split("-")
            exp = date(int(p[0]), int(p[1]), int(p[2]))
        else:
            return 0
        return max(0, (exp - today).days)
    except Exception:
        return 0


def _get_realtime(code: str, market: str = "tse") -> dict | None:
    try:
        ts = int(time.time() * 1000)
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={market}_{code}.tw&json=1&delay=0&_={ts}"
        item = requests.get(url, headers=_BASE_HDR, timeout=8).json()["msgArray"][0]
        z_raw = item.get("z", "-")
        y_raw = item.get("y", "0")
        last_price = _sf(z_raw) or 0
        prev_close = _sf(y_raw) or 0
        price = last_price or prev_close or 0

        def _pl(s): return [float(x) for x in s.split("_") if x not in ("-", "")]
        def _il(s): return [int(float(x)) for x in s.split("_") if x not in ("-", "")]

        return {
            "price": price,
            "last_price": last_price,
            "prev_close": prev_close,
            "volume": _si(item.get("v", "0")),
            "bid_prices": _pl(item.get("b", ""))[:5],
            "bid_sizes": _il(item.get("g", ""))[:5],
            "ask_prices": _pl(item.get("a", ""))[:5],
            "ask_sizes": _il(item.get("f", ""))[:5],
        }
    except Exception:
        return None


def get_stock_price(code: str) -> tuple[float | None, str, float | None]:
    for mkt in ("tse", "otc"):
        rt = _get_realtime(code, mkt)
        if rt and rt.get("price"):
            return rt["price"], mkt, rt.get("prev_close")
    return None, "tse", None


def _get_warrant_rt(code: str) -> dict | None:
    for mkt in ("tse", "otc"):
        rt = _get_realtime(code, mkt)
        if rt and (rt.get("price") or rt.get("bid_prices")):
            return rt
    return None


def _fetch_hv(stock_code: str, n_days: int = 60) -> float:
    prices = []
    try:
        for i in range(2):
            dt = (datetime.now() - timedelta(days=35 * i)).strftime("%Y%m%d")
            url = f"https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date={dt}&stockNo={stock_code}"
            data = requests.get(url, headers=_BASE_HDR, timeout=10).json()
            for row in data.get("data", []):
                c = _sf(row[6])
                if c and c > 0:
                    prices.append(c)
            time.sleep(0.3)
        if len(prices) < 10:
            return 0.35
        prices = prices[-n_days:]
        log_r = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        n = len(log_r)
        mean = sum(log_r) / n
        var = sum((r - mean) ** 2 for r in log_r) / max(n - 1, 1)
        hv = math.sqrt(var) * math.sqrt(252)
        return max(0.15, min(1.20, hv))
    except Exception:
        return 0.35


_TWSE_WARRANT_URLS = [
    "https://www.twse.com.tw/rwd/zh/warrant/TWG4W",
    "https://www.twse.com.tw/exchangeReport/TWG4W",
]

_TWSE_WARRANT_HDR = {
    **_BASE_HDR,
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://www.twse.com.tw/zh/warrant/TWG4W.html",
    "X-Requested-With": "XMLHttpRequest",
}


def _parse_twse_warrant_json(data: dict, stock_code: str) -> list[dict]:
    fields = [str(f) for f in data.get("fields", [])]
    rows = data.get("data", [])

    def _fi(*keywords) -> int:
        for kw in keywords:
            for i, f in enumerate(fields):
                if kw in f:
                    return i
        return -1

    i_code = _fi("代號")
    i_name = _fi("名稱")
    i_type = _fi("類別")
    i_strike = _fi("履約")
    i_expiry = _fi("到期")
    i_ratio = _fi("行使比例", "行使")
    i_und = _fi("標的")

    def _get(row, i, fallback=""):
        return str(row[i]).strip() if 0 <= i < len(row) else fallback

    warrants = []
    for row in rows:
        if not row:
            continue
        code = _get(row, i_code, str(row[0])).strip()
        name = _get(row, i_name, str(row[1]) if len(row) > 1 else "")
        type_s = _get(row, i_type, "")
        if "售" in type_s or "put" in type_s.lower():
            continue
        if not type_s and "售" in name:
            continue
        days = _parse_expiry(_get(row, i_expiry))
        strike = _sf(_get(row, i_strike)) or 0
        ratio = _sf(_get(row, i_ratio)) or 0.1
        und = _get(row, i_und, stock_code).split()[0] or stock_code
        if not code:
            continue
        warrants.append({"code": code, "name": name, "und_code": und, "strike": strike, "days": days,
                         "exercise_ratio": ratio, "sigma": 0.0, "volume": 0, "price": 0.0,
                         "bid_px": 0.0, "bid_sz": 0, "ask_px": 0.0, "ask_sz": 0})
    return warrants


def _fetch_from_twse(stock_code: str) -> list[dict]:
    params = {"response": "json", "stk_no": stock_code, "type": "C"}
    for url in _TWSE_WARRANT_URLS:
        try:
            resp = requests.get(url, params=params, headers=_TWSE_WARRANT_HDR, timeout=15)
            data = resp.json()
            if data.get("stat") != "OK":
                continue
            warrants = _parse_twse_warrant_json(data, stock_code)
            if warrants:
                return warrants
        except Exception:
            continue
    return []


def _parse_capital(text: str) -> list[dict]:
    if not (text.startswith("M") and "#" in text):
        return []
    warrants = []
    for rec in text.split("#")[1:]:
        rec = rec.strip()
        if not rec:
            continue
        fields: dict[str, str] = {}
        for kv in rec.split(","):
            if "=" in kv:
                k, v = kv.split("=", 1)
                fields[k.strip()] = v.strip()
        if fields.get("26", "C") != "C":
            continue
        code = fields.get("1", "").strip()
        name = fields.get("2", "").strip()
        und_code = fields.get("3", "").strip()
        if not code or not re.match(r"^\d{4,6}$", und_code):
            continue
        sigma_60 = 0.0
        for seg in fields.get("10", "").split(";"):
            if seg.startswith("60:"):
                sigma_60 = (_sf(seg[3:]) or 0) / 100.0
        warrants.append({
            "code": code, "name": name, "und_code": und_code,
            "strike": _sf(fields.get("32", "0")) or 0,
            "days": _si(fields.get("22", "0")),
            "exercise_ratio": _sf(fields.get("24", "0")) or 0.1,
            "sigma": sigma_60, "volume": _si(fields.get("15", "0")), "vol_from_api": True,
            "price": 0.0, "bid_px": 0.0, "bid_sz": 0, "ask_px": 0.0, "ask_sz": 0,
        })
    return warrants


def _fetch_from_capital(stock_code: str) -> list[dict]:
    try:
        sess = requests.Session()
        sess.get("https://extweb.capital.com.tw/Extproduct/Program/Warrant/IndexWarrant/WarrantSearch.html", headers=_BASE_HDR, timeout=12)
        time.sleep(0.5)
    except Exception:
        return []
    best: list[dict] = []
    for flag1 in ("0", "9100"):
        try:
            params = {**_CAPITAL_PARAMS, "flag1": flag1, "flag2_value": stock_code}
            resp = sess.get("https://srvsolgw.capital.com.tw/info/warrant.aspx", params=params, headers=_CAPITAL_HDR, timeout=20)
            text = resp.text.strip()
            if resp.status_code == 200 and text.startswith("M") and "#" in text:
                result = _parse_capital(text)
                if len(result) > len(best):
                    best = result
        except Exception:
            pass
    return best


def _is_market_hours() -> bool:
    tw_now = datetime.now(timezone(timedelta(hours=8)))
    if tw_now.weekday() >= 5:
        return False
    t = tw_now.time()
    return _dtime(9, 0) <= t <= _dtime(13, 35)


def _warrant_score(w: dict, use_volume: bool = True) -> float:
    vol = w.get("volume", 0) or 0
    dj = w.get("dj_ratio")
    lev = w.get("lev")
    otm = w.get("otm")
    vol_score = min(35.0, math.log10(max(1, vol)) / math.log10(1000) * 35) if use_volume else 0.0
    dj_score = max(0.0, 30.0 * (1.0 - dj / 0.6)) if dj is not None else 10.0
    if lev is not None:
        if lev <= 0:
            lev_score = 0.0
        elif lev <= 5:
            lev_score = lev / 5.0 * 20.0
        else:
            lev_score = max(0.0, 20.0 - (lev - 5.0) * 2.0)
    else:
        lev_score = 8.0
    if otm is not None:
        dist = abs(otm - 0.025)
        otm_score = max(0.0, 15.0 * (1.0 - dist / 0.125))
    else:
        otm_score = 5.0
    return round(vol_score + dj_score + lev_score + otm_score, 2)


def fetch_warrant_results(stock_code: str) -> dict:
    intraday = _is_market_hours()
    S, _, S_prev = get_stock_price(stock_code)
    S_calc = (S_prev or S) if intraday else S
    hv = _fetch_hv(stock_code)

    warrants = _fetch_from_twse(stock_code)
    source = "TWSE" if warrants else "none"
    if not warrants:
        warrants = _fetch_from_capital(stock_code)
        source = "Capital" if warrants else "none"

    if not warrants:
        return {"stock_price": S, "warrants": [], "total_found": 0, "source": source, "hv": hv, "intraday": intraday}

    candidates = []
    for w in warrants:
        days = w["days"]
        if not (MIN_DAYS <= days <= MAX_DAYS):
            continue
        otm = w.get("otm")
        if otm is None and S_calc and S_calc > 0 and w["strike"] > 0:
            otm = (w["strike"] - S_calc) / S_calc
        if otm is not None and (otm > MAX_OTM_PCT or otm < MIN_OTM_PCT):
            continue
        w["otm"] = otm
        if not w.get("sigma"):
            w["sigma"] = hv
        candidates.append(w)

    n_fetch = min(len(candidates), MIS_BATCH_LIMIT)
    for w in candidates[:n_fetch]:
        rt = _get_warrant_rt(w["code"])
        if rt:
            if rt.get("volume"):
                w["volume"] = rt["volume"]
            today_px = rt.get("last_price") or 0
            prev_px = rt.get("prev_close") or 0
            if intraday and prev_px:
                w["price"] = prev_px
                if today_px > 0:
                    w["price_today"] = today_px
                elif rt.get("bid_prices") and rt.get("ask_prices"):
                    w["price_today"] = round((rt["bid_prices"][0] + rt["ask_prices"][0]) / 2, 2)
                elif rt.get("bid_prices"):
                    w["price_today"] = rt["bid_prices"][0]
                elif rt.get("ask_prices"):
                    w["price_today"] = rt["ask_prices"][0]
                else:
                    w["price_today"] = None
            else:
                w["price"] = today_px or prev_px
                if today_px > 0:
                    w["price_today"] = today_px
                elif rt.get("bid_prices") and rt.get("ask_prices"):
                    w["price_today"] = round((rt["bid_prices"][0] + rt["ask_prices"][0]) / 2, 2)
                elif rt.get("bid_prices"):
                    w["price_today"] = rt["bid_prices"][0]
                elif rt.get("ask_prices"):
                    w["price_today"] = rt["ask_prices"][0]
                else:
                    w["price_today"] = None
            w["bid_px"] = rt["bid_prices"][0] if rt["bid_prices"] else w.get("bid_px", 0)
            w["ask_px"] = rt["ask_prices"][0] if rt["ask_prices"] else w.get("ask_px", 0)
        time.sleep(0.15)

    for w in candidates[:n_fetch]:
        T = w["days"] / 365.0
        wp = w.get("price", 0) or 0
        sigma = w.get("sigma") or hv
        delta = _bs_delta(S_calc, w["strike"], T, RISK_FREE_RATE, sigma) if S_calc and w["strike"] > 0 else None
        lev = None
        ex_rt = w.get("exercise_ratio", 0.1)
        if delta is not None and S_calc and wp > 0 and ex_rt > 0:
            lev = abs(delta) * S_calc * ex_rt / wp
            if lev < 0.5:
                lev = (S_calc * ex_rt) / wp
        otm = (w["strike"] - S_calc) / S_calc if S_calc and w["strike"] else w.get("otm")
        w["otm"] = otm
        w["otm_str"] = f"{'外' if otm > 0 else '內'}{abs(otm):.1%}" if otm is not None else "N/A"
        w["delta"] = round(abs(delta), 2) if delta is not None else None
        w["lev"] = round(lev, 1) if lev is not None else None
        bid_px = w.get("bid_px", 0) or 0
        ask_px = w.get("ask_px", 0) or 0
        spread_pct = (ask_px - bid_px) / bid_px * 100 if bid_px > 0 and ask_px > bid_px else None
        w["spread_pct"] = round(spread_pct, 2) if spread_pct is not None else None
        w["dj_ratio"] = round(spread_pct / lev, 3) if spread_pct is not None and lev and lev > 0 else None
        use_vol = w.get("vol_from_api", False) or not intraday
        w["_score"] = _warrant_score(w, use_volume=use_vol)

    scored = sorted(candidates[:n_fetch], key=lambda x: x.get("_score", 0), reverse=True)
    top = scored[:TOP_N]
    return {"stock_price": S, "warrants": top, "total_found": len(candidates), "source": source, "hv": hv, "intraday": intraday}

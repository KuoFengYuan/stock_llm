from __future__ import annotations

import logging
import ssl
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

logger = logging.getLogger(__name__)

TWSE_LISTED_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"
TWSE_T86_URL = "https://www.twse.com.tw/rwd/zh/fund/T86"

_LISTED_COLUMN_MAP = {
    "公司代號": "stock_code",
    "公司名稱": "name",
    "公司簡稱": "short_name",
    "產業別": "industry_code",
}

TWSE_INDUSTRY_MAP: dict[str, str] = {
    "01": "水泥工業", "02": "食品工業", "03": "塑膠工業", "04": "紡織纖維",
    "05": "電機機械", "06": "電器電纜", "08": "玻璃陶瓷", "09": "造紙工業",
    "10": "鋼鐵工業", "11": "橡膠工業", "12": "汽車工業", "14": "建材營造",
    "15": "航運業", "16": "觀光餐旅", "17": "金融保險業", "18": "貿易百貨",
    "19": "綜合", "20": "其他", "21": "化學工業", "22": "生技醫療業",
    "23": "油電燃氣業", "24": "半導體業", "25": "電腦及週邊設備業",
    "26": "光電業", "27": "通信網路業", "28": "電子零組件業", "29": "電子通路業",
    "30": "資訊服務業", "31": "其他電子業", "32": "文化創意業", "33": "農業科技業",
    "34": "電子商務", "35": "綠能環保", "36": "數位雲端", "37": "運動休閒",
    "38": "居家生活", "80": "管理股票", "9299": "存託憑證",
}


class _TWSETLSAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        ctx = ssl.create_default_context()
        ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=ctx,
        )


def _session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", _TWSETLSAdapter())
    s.headers.update({"User-Agent": "stock-llm/0.1 (research)"})
    return s


def fetch_listed_stocks(timeout: int = 30) -> pd.DataFrame:
    logger.info("Fetching TWSE listed companies from %s", TWSE_LISTED_URL)
    with _session() as s:
        response = s.get(TWSE_LISTED_URL, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not payload:
        raise RuntimeError("TWSE returned empty payload")

    raw = pd.DataFrame(payload)
    missing = [c for c in _LISTED_COLUMN_MAP if c not in raw.columns]
    if missing:
        raise RuntimeError(
            f"TWSE response missing expected columns: {missing}. Got: {list(raw.columns)}"
        )

    df = raw[list(_LISTED_COLUMN_MAP.keys())].rename(columns=_LISTED_COLUMN_MAP).copy()
    df["stock_code"] = df["stock_code"].astype(str).str.strip()
    df["name"] = df["name"].astype(str).str.strip()
    df["short_name"] = df["short_name"].astype(str).str.strip()
    df["industry_code"] = df["industry_code"].astype(str).str.strip()
    df["industry"] = df["industry_code"].map(TWSE_INDUSTRY_MAP).fillna(df["industry_code"])
    df["market"] = "TWSE"

    df = df[df["stock_code"].str.match(r"^\d{4,6}$", na=False)].reset_index(drop=True)
    return df[["stock_code", "name", "short_name", "industry", "market"]]


def _to_int(val) -> int:
    if val is None:
        return 0
    s = str(val).replace(",", "").replace(" ", "").strip()
    if not s or s in ("-", "--"):
        return 0
    try:
        return int(float(s))
    except ValueError:
        return 0


def fetch_institutional_day(target_date: date, session: requests.Session | None = None, timeout: int = 30) -> pd.DataFrame:
    """Fetch 三大法人 for a single trading day from TWSE T86."""
    params = {
        "response": "json",
        "date": target_date.strftime("%Y%m%d"),
        "selectType": "ALL",
    }
    s = session or _session()
    r = s.get(TWSE_T86_URL, params=params, timeout=timeout)
    r.raise_for_status()
    payload = r.json()

    if payload.get("stat") != "OK":
        logger.debug("TWSE T86 %s: %s", target_date, payload.get("stat"))
        return pd.DataFrame()

    fields = payload.get("fields", [])
    data = payload.get("data", [])
    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=fields)
    code_col = next((c for c in df.columns if "證券代號" in c), None)
    if not code_col:
        return pd.DataFrame()

    foreign_cols = [c for c in df.columns if "外" in c and "買賣超" in c]
    invest_cols = [c for c in df.columns if "投信" in c and "買賣超" in c]
    dealer_sub = [
        c for c in df.columns
        if "自營" in c and "買賣超" in c and ("自行買賣" in c or "避險" in c)
    ]
    dealer_cols = dealer_sub if dealer_sub else [
        c for c in df.columns if "自營" in c and "買賣超" in c
    ]

    out = pd.DataFrame()
    out["stock_code"] = df[code_col].astype(str).str.strip()
    out["trade_date"] = target_date
    out["foreign_net"] = sum(df[c].map(_to_int) for c in foreign_cols) if foreign_cols else 0
    out["invest_net"] = sum(df[c].map(_to_int) for c in invest_cols) if invest_cols else 0
    out["dealer_net"] = sum(df[c].map(_to_int) for c in dealer_cols) if dealer_cols else 0

    out = out[out["stock_code"].str.match(r"^\d{4}$", na=False)].reset_index(drop=True)
    return out


def fetch_institutional_range(days: int = 90, sleep: float = 1.0) -> pd.DataFrame:
    today = datetime.now().date()
    frames: list[pd.DataFrame] = []
    s = _session()
    for i in range(days):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            df = fetch_institutional_day(d, session=s)
        except Exception as exc:
            logger.warning("T86 %s failed: %s", d, exc)
            df = pd.DataFrame()
        if not df.empty:
            logger.info("T86 %s: %d stocks", d, len(df))
            frames.append(df)
        time.sleep(sleep)

    if not frames:
        return pd.DataFrame(columns=["stock_code", "trade_date", "foreign_net", "invest_net", "dealer_net"])
    return pd.concat(frames, ignore_index=True)

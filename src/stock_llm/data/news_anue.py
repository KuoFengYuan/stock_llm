"""鉅亨網 (Anue) 台股新聞擷取。

用公開 JSON API:
    https://api.cnyes.com/media/api/v1/newslist/category/tw_stocks
回傳每則新聞的 newsId / title / summary / publishAt / stockKeyword,
其中 stockKeyword 已含對應的台股代號,不必自己用 regex 抓。
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import pandas as pd
import requests

from stock_llm.data.store import connect

logger = logging.getLogger(__name__)

# 公司名後綴詞 — 出現在標題裡可忽略 (例: 台積電(股) / 台塑公司 等)
_SUFFIX_STRIP = ("股份有限公司", "股份", "公司", "集團", "(股)", "(KY)", "-KY")


def _strip_suffix(name: str) -> str:
    s = name.strip()
    for suf in _SUFFIX_STRIP:
        s = s.replace(suf, "")
    return s.strip()


def _load_stock_names() -> dict[str, set[str]]:
    """回傳 {stock_code: {短名, 全名, 去除後綴變體, 代號}}。
    僅保留長度 >= 2 的字串以避免偽匹配。
    """
    try:
        with connect() as con:
            df = con.execute("SELECT stock_code, name, short_name FROM stocks").fetchdf()
    except Exception as exc:
        logger.warning("Failed to load stock names: %s", exc)
        return {}

    out: dict[str, set[str]] = {}
    for _, r in df.iterrows():
        code = r["stock_code"]
        names = {code}
        for field in (r.get("short_name"), r.get("name")):
            if isinstance(field, str) and field.strip():
                n = field.strip()
                if len(n) >= 2:
                    names.add(n)
                stripped = _strip_suffix(n)
                if len(stripped) >= 2:
                    names.add(stripped)
        out[code] = names
    return out


def _mentioned(names: set[str], text: str) -> bool:
    if not text or not names:
        return False
    return any(n in text for n in names)

ANUE_LIST_URL = "https://api.cnyes.com/media/api/v1/newslist/category/tw_stock_news"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
    "Accept": "application/json",
}

_TW_CODE_RE = re.compile(r"\b([1-9]\d{3})\b")


def _codes_from_item(item: dict) -> list[str]:
    """Anue 提供 `stock` list + `market` list,合併後去重。只保留 4 位純數字。"""
    codes: list[str] = []
    for c in item.get("stock") or []:
        if isinstance(c, str) and _TW_CODE_RE.match(c):
            codes.append(c)
    for m in item.get("market") or []:
        if isinstance(m, dict):
            c = m.get("code")
            if isinstance(c, str) and _TW_CODE_RE.match(c):
                codes.append(c)
    return list(dict.fromkeys(codes))


def fetch_anue_news(
    pages: int = 3, limit_per_page: int = 30, sleep: float = 1.5,
    max_age_days: int = 7,
) -> pd.DataFrame:
    """抓鉅亨台股新聞清單。回傳每則新聞 × 每個提到的股票 一列。

    Columns: url, stock_code, title, content, published_at, source
    """
    now = datetime.now(timezone.utc)
    cutoff_ts = now.timestamp() - max_age_days * 86400
    rows: list[dict] = []
    seen_ids: set[str] = set()
    stock_names = _load_stock_names()
    skipped = 0

    for page in range(1, pages + 1):
        try:
            r = requests.get(
                ANUE_LIST_URL,
                params={"page": page, "limit": limit_per_page},
                headers=HEADERS, timeout=15,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as exc:
            logger.warning("Anue page %d failed: %s", page, exc)
            continue

        items = (payload.get("items") or {}).get("data") or []
        if not items:
            break

        for item in items:
            news_id = str(item.get("newsId") or item.get("id") or "")
            if not news_id or news_id in seen_ids:
                continue
            seen_ids.add(news_id)

            publish_ts = item.get("publishAt") or item.get("publish_at") or 0
            if publish_ts and publish_ts < cutoff_ts:
                continue

            published = datetime.fromtimestamp(publish_ts, tz=timezone.utc) if publish_ts else now
            title = (item.get("title") or "").strip()
            summary = (item.get("summary") or "").strip()

            codes = _codes_from_item(item)
            if not codes:
                continue

            haystack = f"{title} {summary}"
            if len(codes) == 1:
                kept = codes
            else:
                # 放寬: 只要任一檔的名字/代號在 title+summary 被提到, 視為「台股主題相關」,
                # 保留整則新聞的所有標籤 (誤標交由 LLM 主題辨識 prompt 給 0 分)。
                any_hit = any(_mentioned(stock_names.get(c, {c}), haystack) for c in codes)
                if not any_hit:
                    skipped += len(codes)
                    continue
                kept = codes

            url = f"https://news.cnyes.com/news/id/{news_id}"
            for code in kept:
                rows.append({
                    "url": url,
                    "stock_code": code,
                    "title": title,
                    "content": summary,
                    "published_at": published.replace(tzinfo=None),
                    "source": "anue",
                })

        logger.info("Anue page %d: %d unique news (skipped %d off-topic pairs)", page, len(items), skipped)
        time.sleep(sleep)

    if not rows:
        return pd.DataFrame(columns=["url", "stock_code", "title", "content", "published_at", "source"])
    return pd.DataFrame(rows)

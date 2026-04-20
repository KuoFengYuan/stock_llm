"""Google News RSS 台股新聞擷取 — 對 top-N 股票逐檔查詢。

Anue 對中小型股覆蓋稀疏, 這個 fetcher 補洞。Google News 會聚合 CMoney/工商/經濟/
鉅亨/MoneyDJ 等來源, 對小型股也常有報導。

Query format: `"{short_name}" {code} 股價`
    - 加上 code 避免同名公司干擾 (例如「台塑」有台塑/台塑化)
    - 加上「股價」避開公司本身的非財經新聞
"""
from __future__ import annotations

import logging
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Iterable

import feedparser
import pandas as pd

from stock_llm.data.store import connect

logger = logging.getLogger(__name__)

GOOGLE_RSS_BASE = "https://news.google.com/rss/search"


def _query_url(name: str, code: str) -> str:
    q = f'"{name}" {code} 股價'
    return (
        f"{GOOGLE_RSS_BASE}?q={urllib.parse.quote(q)}"
        f"&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    )


def _load_stock_name_map() -> dict[str, str]:
    """回傳 {stock_code: short_name (or name)}。"""
    try:
        with connect() as con:
            df = con.execute(
                "SELECT stock_code, name, short_name FROM stocks"
            ).fetchdf()
    except Exception as exc:
        logger.warning("Failed to load stock names: %s", exc)
        return {}
    out: dict[str, str] = {}
    for _, r in df.iterrows():
        for field in ("short_name", "name"):
            v = r.get(field)
            if isinstance(v, str) and len(v.strip()) >= 2:
                out[r["stock_code"]] = v.strip()
                break
    return out


def fetch_google_news(
    stock_codes: Iterable[str],
    sleep: float = 0.5,
    max_age_days: int = 7,
    max_per_stock: int = 20,
) -> pd.DataFrame:
    """對每檔 stock 查 Google News RSS, 回傳 news × stock 長表。

    Columns: url, stock_code, title, content, published_at, source
    """
    codes = list(dict.fromkeys(stock_codes))
    if not codes:
        return pd.DataFrame(
            columns=["url", "stock_code", "title", "content", "published_at", "source"]
        )

    name_map = _load_stock_name_map()
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    rows: list[dict] = []
    fail = 0
    no_name = 0

    for i, code in enumerate(codes, 1):
        name = name_map.get(code)
        if not name:
            no_name += 1
            continue
        url = _query_url(name, code)
        try:
            feed = feedparser.parse(url)
        except Exception as exc:
            logger.warning("Google RSS %s failed: %s", code, exc)
            fail += 1
            time.sleep(sleep)
            continue

        if feed.bozo and not feed.entries:
            fail += 1
            time.sleep(sleep)
            continue

        for e in feed.entries[:max_per_stock]:
            link = e.get("link") or ""
            title = (e.get("title") or "").strip()
            summary = (e.get("summary") or "").strip()
            if not link or not title:
                continue

            pub_struct = e.get("published_parsed") or e.get("updated_parsed")
            pub = (
                datetime(*pub_struct[:6], tzinfo=timezone.utc)
                if pub_struct
                else datetime.now(timezone.utc)
            )
            if pub < cutoff:
                continue

            rows.append({
                "url": link,
                "stock_code": code,
                "title": title,
                "content": summary,
                "published_at": pub.replace(tzinfo=None),
                "source": "google",
            })

        if i % 50 == 0 or i == len(codes):
            logger.info(
                "Google RSS: %d/%d stocks (kept=%d rows, fail=%d, no_name=%d)",
                i, len(codes), len(rows), fail, no_name,
            )
        time.sleep(sleep)

    if not rows:
        return pd.DataFrame(
            columns=["url", "stock_code", "title", "content", "published_at", "source"]
        )
    return pd.DataFrame(rows)

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Iterable

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

PRICE_COLUMNS = ["stock_code", "trade_date", "open", "high", "low", "close", "volume"]


def twse_to_yf_ticker(stock_code: str) -> str:
    return f"{stock_code}.TW"


def _normalize(df: pd.DataFrame, stock_code: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    df = df.dropna(how="all").reset_index()
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    rename = {
        "Date": "trade_date",
        "Datetime": "trade_date",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename)

    needed = {"trade_date", "open", "high", "low", "close", "volume"}
    if not needed.issubset(df.columns):
        return pd.DataFrame(columns=PRICE_COLUMNS)

    df["stock_code"] = stock_code
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    # yfinance 盤中/partial response 偶爾會回傳 close=NaN 但 volume 有值的廢 row,
    # 若寫入會覆蓋 DB 正確資料 (upsert)。在這裡丟掉。
    df = df.dropna(subset=["close"])
    if df.empty:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    df["volume"] = df["volume"].fillna(0).astype("int64")
    return df[PRICE_COLUMNS]


def _fetch_batch(codes: list[str], start: str, end: str) -> pd.DataFrame:
    tickers = [twse_to_yf_ticker(c) for c in codes]
    raw = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        group_by="ticker",
        auto_adjust=True,
        progress=False,
        threads=True,
    )

    frames: list[pd.DataFrame] = []
    for ticker, code in zip(tickers, codes):
        try:
            if len(tickers) == 1:
                sub = raw
            elif ticker in raw.columns.get_level_values(0):
                sub = raw[ticker]
            else:
                logger.warning("No data for %s", ticker)
                continue
            normalized = _normalize(sub, code)
            if not normalized.empty:
                frames.append(normalized)
        except Exception as exc:
            logger.warning("Failed parsing %s: %s", ticker, exc)

    if not frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def fetch_prices(
    codes: Iterable[str],
    days: int = 730,
    batch_size: int = 50,
) -> pd.DataFrame:
    codes = list(codes)
    if not codes:
        return pd.DataFrame(columns=PRICE_COLUMNS)

    end: date = datetime.now().date()
    start: date = end - timedelta(days=days)
    start_s, end_s = start.isoformat(), (end + timedelta(days=1)).isoformat()

    total_batches = (len(codes) + batch_size - 1) // batch_size
    all_frames: list[pd.DataFrame] = []
    for batch_idx, i in enumerate(range(0, len(codes), batch_size), start=1):
        batch = codes[i : i + batch_size]
        logger.info(
            "Batch %d/%d (%d tickers): %s...",
            batch_idx,
            total_batches,
            len(batch),
            batch[0],
        )
        df = _fetch_batch(batch, start_s, end_s)
        if not df.empty:
            all_frames.append(df)

    if not all_frames:
        return pd.DataFrame(columns=PRICE_COLUMNS)
    return pd.concat(all_frames, ignore_index=True)

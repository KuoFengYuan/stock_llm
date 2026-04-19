from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
import requests

from stock_llm.config import get_finmind_token

logger = logging.getLogger(__name__)

FINMIND_URL = "https://api.finmindtrade.com/api/v4/data"

DATASET_MONTHLY_REVENUE = "TaiwanStockMonthRevenue"
DATASET_FINANCIALS = "TaiwanStockFinancialStatements"


def _seconds_until_next_hour(buffer_seconds: int = 30) -> float:
    now = datetime.now()
    nxt = (now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
    return max((nxt - now).total_seconds() + buffer_seconds, 60)


def _get(
    params: dict[str, Any],
    timeout: int = 60,
    quota_retries: int = 24,
    quota_wait: float | None = None,
) -> list[dict]:
    """GET FinMind. On HTTP 402 (quota), sleep until next hour and retry up to quota_retries."""
    token = get_finmind_token()
    if token:
        params = {**params, "token": token}

    safe_params = {k: v for k, v in params.items() if k != "token"}
    attempt = 0
    while True:
        response = requests.get(FINMIND_URL, params=params, timeout=timeout)

        if response.status_code == 402 and attempt < quota_retries:
            wait = quota_wait if quota_wait is not None else _seconds_until_next_hour()
            logger.warning(
                "FinMind quota exhausted (HTTP 402) on dataset=%s data_id=%s. "
                "Sleeping %.0f s (attempt %d/%d) until quota refills...",
                safe_params.get("dataset"), safe_params.get("data_id"),
                wait, attempt + 1, quota_retries,
            )
            time.sleep(wait)
            attempt += 1
            continue

        if not response.ok:
            raise RuntimeError(
                f"FinMind HTTP {response.status_code} ({response.reason}) "
                f"dataset={safe_params.get('dataset')} data_id={safe_params.get('data_id')}"
            )

        body = response.json()
        status = body.get("status")
        if status == 402 and attempt < quota_retries:
            wait = quota_wait if quota_wait is not None else _seconds_until_next_hour()
            logger.warning(
                "FinMind quota in body (status 402) on dataset=%s data_id=%s. "
                "Sleeping %.0f s (attempt %d/%d)...",
                safe_params.get("dataset"), safe_params.get("data_id"),
                wait, attempt + 1, quota_retries,
            )
            time.sleep(wait)
            attempt += 1
            continue

        if status and status != 200:
            raise RuntimeError(f"FinMind error {status}: {body.get('msg', body)}")
        return body.get("data", []) or []


def _fetch_per_stock(
    dataset: str,
    stock_codes: list[str],
    start: str,
    end: str | None = None,
    sleep: float = 0.3,
    log_every: int = 50,
    flush_every: int = 0,
    on_flush=None,
) -> list[dict]:
    """Fetch a FinMind dataset per stock_code.

    If `flush_every > 0` and `on_flush` callable is given, it is invoked with
    the accumulated rows every `flush_every` stocks, then the buffer is reset.
    This lets callers persist partial progress if the loop is interrupted.
    """
    total = len(stock_codes)
    all_rows: list[dict] = []
    buffer: list[dict] = []
    for idx, code in enumerate(stock_codes, start=1):
        params: dict[str, Any] = {
            "dataset": dataset,
            "data_id": code,
            "start_date": start,
        }
        if end:
            params["end_date"] = end
        try:
            rows = _get(params)
        except Exception as exc:
            logger.warning("Skip %s [%s]: %s", code, dataset, exc)
            rows = []
        all_rows.extend(rows)
        buffer.extend(rows)
        if idx % log_every == 0:
            logger.info("%s progress: %d/%d", dataset, idx, total)
        if flush_every and on_flush and idx % flush_every == 0 and buffer:
            on_flush(buffer)
            buffer = []
        if sleep:
            time.sleep(sleep)
    if flush_every and on_flush and buffer:
        on_flush(buffer)
    return all_rows


def fetch_monthly_revenue(
    stock_codes: list[str], start: str, end: str | None = None, sleep: float = 0.3
) -> pd.DataFrame:
    rows = _fetch_per_stock(DATASET_MONTHLY_REVENUE, stock_codes, start, end, sleep=sleep)
    if not rows:
        return pd.DataFrame(
            columns=["stock_code", "year_month", "revenue", "revenue_yoy", "revenue_mom"]
        )
    df = pd.DataFrame(rows)
    df["stock_code"] = df["stock_id"].astype(str).str.strip()
    df["year_month"] = (
        df["revenue_year"].astype(int).astype(str).str.zfill(4)
        + "-"
        + df["revenue_month"].astype(int).astype(str).str.zfill(2)
    )
    df["revenue"] = pd.to_numeric(df["revenue"], errors="coerce").fillna(0).astype("int64")

    df = df.sort_values(["stock_code", "year_month"]).reset_index(drop=True)
    df["revenue_mom"] = df.groupby("stock_code")["revenue"].pct_change()
    df["revenue_yoy"] = df.groupby("stock_code")["revenue"].pct_change(periods=12)
    return df[["stock_code", "year_month", "revenue", "revenue_yoy", "revenue_mom"]]


def _date_to_quarter(date_str: str) -> str:
    d = pd.to_datetime(date_str, errors="coerce")
    if pd.isna(d):
        return date_str
    q = (d.month - 1) // 3 + 1
    return f"{d.year}Q{q}"


def _pivot_financials(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["stock_code"] = df["stock_id"].astype(str).str.strip()
    df["year_quarter"] = df["date"].astype(str).map(_date_to_quarter)
    wanted = {
        "Revenue": "revenue",
        "GrossProfit": "gross_profit",
        "OperatingIncome": "operating_income",
        "IncomeAfterTaxes": "net_income",
        "EPS": "eps",
    }
    df = df[df["type"].isin(wanted.keys())]
    if df.empty:
        return pd.DataFrame()
    df["metric"] = df["type"].map(wanted)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    pivot = (
        df.pivot_table(
            index=["stock_code", "year_quarter"],
            columns="metric",
            values="value",
            aggfunc="last",
        )
        .reset_index()
    )
    for col in wanted.values():
        if col not in pivot.columns:
            pivot[col] = pd.NA
    pivot["gross_margin"] = pivot["gross_profit"] / pivot["revenue"].replace(0, pd.NA)
    pivot["operating_margin"] = pivot["operating_income"] / pivot["revenue"].replace(0, pd.NA)
    pivot["net_margin"] = pivot["net_income"] / pivot["revenue"].replace(0, pd.NA)
    return pivot[
        [
            "stock_code",
            "year_quarter",
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "eps",
            "gross_margin",
            "operating_margin",
            "net_margin",
        ]
    ]


def fetch_financials_quarterly(
    stock_codes: list[str], start: str, end: str | None = None, sleep: float = 0.3
) -> pd.DataFrame:
    rows = _fetch_per_stock(DATASET_FINANCIALS, stock_codes, start, end, sleep=sleep)
    return _pivot_financials(rows)

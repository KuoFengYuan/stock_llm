"""Build a filtered stock universe (e.g. top-N by liquidity) for use across fetchers and scoring."""
from __future__ import annotations

from stock_llm.data.store import connect


def top_by_turnover(n: int = 500, lookback_days: int = 30) -> list[str]:
    """Return top-N stock codes by average daily turnover (close * volume) over lookback window.

    Used to focus FinMind fetches and scoring on liquid stocks where recommendations
    are actually actionable.
    """
    with connect() as con:
        df = con.execute(
            f"""
            SELECT stock_code, AVG(close * volume) AS turnover
            FROM prices_daily
            WHERE trade_date > CURRENT_DATE - INTERVAL {lookback_days} DAY
              AND volume > 0
            GROUP BY stock_code
            ORDER BY turnover DESC
            LIMIT {n}
            """
        ).fetchdf()
    return df["stock_code"].tolist()


def top_by_volume(n: int = 500, lookback_days: int = 30) -> list[str]:
    with connect() as con:
        df = con.execute(
            f"""
            SELECT stock_code, AVG(volume) AS vol
            FROM prices_daily
            WHERE trade_date > CURRENT_DATE - INTERVAL {lookback_days} DAY
            GROUP BY stock_code
            ORDER BY vol DESC
            LIMIT {n}
            """
        ).fetchdf()
    return df["stock_code"].tolist()

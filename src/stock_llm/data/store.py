from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

import duckdb
import pandas as pd

from stock_llm.config import DATA_DIR, DB_PATH
from stock_llm.data.schema import ALL_SCHEMAS


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def init_db(db_path: Path = DB_PATH) -> None:
    _ensure_data_dir()
    with duckdb.connect(str(db_path)) as con:
        for ddl in ALL_SCHEMAS:
            con.execute(ddl)


@contextmanager
def connect(db_path: Path = DB_PATH) -> Iterator[duckdb.DuckDBPyConnection]:
    _ensure_data_dir()
    con = duckdb.connect(str(db_path))
    try:
        for ddl in ALL_SCHEMAS:
            con.execute(ddl)
        yield con
    finally:
        con.close()


def upsert_stocks(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    expected = {"stock_code", "name", "short_name", "industry", "market"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_stocks missing columns: {missing}")

    now = datetime.now()
    with connect(db_path) as con:
        con.register("df_stocks", df)
        con.execute(
            """
            INSERT INTO stocks (stock_code, name, short_name, industry, market, updated_at)
            SELECT stock_code, name, short_name, industry, market, ? AS ts
            FROM df_stocks
            ON CONFLICT (stock_code) DO UPDATE SET
                name       = EXCLUDED.name,
                short_name = EXCLUDED.short_name,
                industry   = EXCLUDED.industry,
                market     = EXCLUDED.market,
                updated_at = EXCLUDED.updated_at
            """,
            [now],
        )
        (total,) = con.execute("SELECT COUNT(*) FROM stocks").fetchone()
        return int(total)


def upsert_prices(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    expected = {"stock_code", "trade_date", "open", "high", "low", "close", "volume"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_prices missing columns: {missing}")
    if df.empty:
        return 0

    with connect(db_path) as con:
        con.register("df_prices", df)
        con.execute(
            """
            INSERT INTO prices_daily
                (stock_code, trade_date, open, high, low, close, volume)
            SELECT stock_code, trade_date, open, high, low, close, volume
            FROM df_prices
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                open   = EXCLUDED.open,
                high   = EXCLUDED.high,
                low    = EXCLUDED.low,
                close  = EXCLUDED.close,
                volume = EXCLUDED.volume
            """
        )
        (total,) = con.execute("SELECT COUNT(*) FROM prices_daily").fetchone()
        return int(total)


def upsert_institutional(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    expected = {"stock_code", "trade_date", "foreign_net", "invest_net", "dealer_net"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_institutional missing columns: {missing}")
    if df.empty:
        return 0

    with connect(db_path) as con:
        con.register("df_inst", df)
        con.execute(
            """
            INSERT INTO institutional_daily
                (stock_code, trade_date, foreign_net, invest_net, dealer_net)
            SELECT stock_code, trade_date, foreign_net, invest_net, dealer_net
            FROM df_inst
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                foreign_net = EXCLUDED.foreign_net,
                invest_net  = EXCLUDED.invest_net,
                dealer_net  = EXCLUDED.dealer_net
            """
        )
        (total,) = con.execute("SELECT COUNT(*) FROM institutional_daily").fetchone()
        return int(total)


def upsert_monthly_revenue(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    expected = {"stock_code", "year_month", "revenue", "revenue_yoy", "revenue_mom"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_monthly_revenue missing columns: {missing}")
    if df.empty:
        return 0

    with connect(db_path) as con:
        con.register("df_rev", df)
        con.execute(
            """
            INSERT INTO monthly_revenue
                (stock_code, year_month, revenue, revenue_yoy, revenue_mom)
            SELECT stock_code, year_month, revenue, revenue_yoy, revenue_mom
            FROM df_rev
            ON CONFLICT (stock_code, year_month) DO UPDATE SET
                revenue     = EXCLUDED.revenue,
                revenue_yoy = EXCLUDED.revenue_yoy,
                revenue_mom = EXCLUDED.revenue_mom
            """
        )
        (total,) = con.execute("SELECT COUNT(*) FROM monthly_revenue").fetchone()
        return int(total)


def upsert_indicators(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    expected = {
        "stock_code", "trade_date",
        "ma5", "ma20", "ma60", "rsi14",
        "macd", "macd_signal", "macd_hist",
        "k9", "d9", "bb_upper", "bb_lower",
        "volume_ma5", "volume_ratio",
    }
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_indicators missing columns: {missing}")
    if df.empty:
        return 0

    with connect(db_path) as con:
        con.register("df_ind", df)
        con.execute(
            """
            INSERT INTO indicators_daily
                (stock_code, trade_date, ma5, ma20, ma60, rsi14,
                 macd, macd_signal, macd_hist, k9, d9,
                 bb_upper, bb_lower, volume_ma5, volume_ratio)
            SELECT stock_code, trade_date, ma5, ma20, ma60, rsi14,
                   macd, macd_signal, macd_hist, k9, d9,
                   bb_upper, bb_lower, volume_ma5, volume_ratio
            FROM df_ind
            ON CONFLICT (stock_code, trade_date) DO UPDATE SET
                ma5=EXCLUDED.ma5, ma20=EXCLUDED.ma20, ma60=EXCLUDED.ma60,
                rsi14=EXCLUDED.rsi14,
                macd=EXCLUDED.macd, macd_signal=EXCLUDED.macd_signal, macd_hist=EXCLUDED.macd_hist,
                k9=EXCLUDED.k9, d9=EXCLUDED.d9,
                bb_upper=EXCLUDED.bb_upper, bb_lower=EXCLUDED.bb_lower,
                volume_ma5=EXCLUDED.volume_ma5, volume_ratio=EXCLUDED.volume_ratio
            """
        )
        (total,) = con.execute("SELECT COUNT(*) FROM indicators_daily").fetchone()
        return int(total)


def upsert_news(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    """Insert news items. Columns: url, stock_code, title, content, published_at, source.
    Sentiment columns are filled later by score_news.py.
    """
    expected = {"url", "stock_code", "title", "published_at", "source"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_news missing columns: {missing}")
    if df.empty:
        return 0

    if "content" not in df.columns:
        df = df.assign(content=None)

    with connect(db_path) as con:
        con.register("df_news", df)
        con.execute(
            """
            INSERT INTO news
                (url, stock_code, title, content, published_at, source)
            SELECT url, stock_code, title, content, published_at, source
            FROM df_news
            ON CONFLICT (url, stock_code) DO UPDATE SET
                title        = EXCLUDED.title,
                content      = EXCLUDED.content,
                published_at = EXCLUDED.published_at,
                source       = EXCLUDED.source
            """
        )
        (total,) = con.execute("SELECT COUNT(*) FROM news").fetchone()
        return int(total)


def update_news_sentiment(
    url: str, stock_code: str,
    score: float, impact: str, summary: str, model: str,
    db_path: Path = DB_PATH,
) -> None:
    now = datetime.now()
    with connect(db_path) as con:
        con.execute(
            """
            UPDATE news SET
                sentiment_score   = ?,
                sentiment_impact  = ?,
                sentiment_summary = ?,
                scored_at         = ?,
                scored_model      = ?
            WHERE url = ? AND stock_code = ?
            """,
            [score, impact, summary, now, model, url, stock_code],
        )


def upsert_financials(df: pd.DataFrame, db_path: Path = DB_PATH) -> int:
    expected = {
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
    }
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"upsert_financials missing columns: {missing}")
    if df.empty:
        return 0

    with connect(db_path) as con:
        con.register("df_fin", df)
        con.execute(
            """
            INSERT INTO financials_quarterly
                (stock_code, year_quarter, revenue, gross_profit, operating_income,
                 net_income, eps, gross_margin, operating_margin, net_margin)
            SELECT stock_code, year_quarter, revenue, gross_profit, operating_income,
                   net_income, eps, gross_margin, operating_margin, net_margin
            FROM df_fin
            ON CONFLICT (stock_code, year_quarter) DO UPDATE SET
                revenue          = EXCLUDED.revenue,
                gross_profit     = EXCLUDED.gross_profit,
                operating_income = EXCLUDED.operating_income,
                net_income       = EXCLUDED.net_income,
                eps              = EXCLUDED.eps,
                gross_margin     = EXCLUDED.gross_margin,
                operating_margin = EXCLUDED.operating_margin,
                net_margin       = EXCLUDED.net_margin
            """
        )
        (total,) = con.execute("SELECT COUNT(*) FROM financials_quarterly").fetchone()
        return int(total)

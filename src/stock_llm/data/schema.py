from __future__ import annotations

SCHEMA_STOCKS = """
CREATE TABLE IF NOT EXISTS stocks (
    stock_code   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    short_name   TEXT,
    industry     TEXT,
    market       TEXT NOT NULL,
    updated_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

SCHEMA_PRICES_DAILY = """
CREATE TABLE IF NOT EXISTS prices_daily (
    stock_code  TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open        DOUBLE,
    high        DOUBLE,
    low         DOUBLE,
    close       DOUBLE,
    volume      BIGINT,
    PRIMARY KEY (stock_code, trade_date)
);
"""

SCHEMA_INSTITUTIONAL = """
CREATE TABLE IF NOT EXISTS institutional_daily (
    stock_code   TEXT NOT NULL,
    trade_date   DATE NOT NULL,
    foreign_net  BIGINT,
    invest_net   BIGINT,
    dealer_net   BIGINT,
    PRIMARY KEY (stock_code, trade_date)
);
"""

SCHEMA_MONTHLY_REVENUE = """
CREATE TABLE IF NOT EXISTS monthly_revenue (
    stock_code   TEXT NOT NULL,
    year_month   TEXT NOT NULL,
    revenue      BIGINT,
    revenue_yoy  DOUBLE,
    revenue_mom  DOUBLE,
    PRIMARY KEY (stock_code, year_month)
);
"""

SCHEMA_FINANCIALS = """
CREATE TABLE IF NOT EXISTS financials_quarterly (
    stock_code        TEXT NOT NULL,
    year_quarter      TEXT NOT NULL,
    revenue           DOUBLE,
    gross_profit      DOUBLE,
    operating_income  DOUBLE,
    net_income        DOUBLE,
    eps               DOUBLE,
    gross_margin      DOUBLE,
    operating_margin  DOUBLE,
    net_margin        DOUBLE,
    PRIMARY KEY (stock_code, year_quarter)
);
"""

SCHEMA_INDICATORS = """
CREATE TABLE IF NOT EXISTS indicators_daily (
    stock_code     TEXT NOT NULL,
    trade_date     DATE NOT NULL,
    ma5            DOUBLE,
    ma20           DOUBLE,
    ma60           DOUBLE,
    rsi14          DOUBLE,
    macd           DOUBLE,
    macd_signal    DOUBLE,
    macd_hist      DOUBLE,
    k9             DOUBLE,
    d9             DOUBLE,
    bb_upper       DOUBLE,
    bb_lower       DOUBLE,
    volume_ma5     DOUBLE,
    volume_ratio   DOUBLE,
    PRIMARY KEY (stock_code, trade_date)
);
"""

SCHEMA_LLM_USAGE = """
CREATE TABLE IF NOT EXISTS llm_usage (
    id              BIGINT PRIMARY KEY,
    called_at       TIMESTAMP NOT NULL,
    model           TEXT NOT NULL,
    purpose         TEXT,
    stock_code      TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER,
    latency_ms      INTEGER,
    success         BOOLEAN NOT NULL,
    error           TEXT
);
CREATE SEQUENCE IF NOT EXISTS llm_usage_id_seq;
"""

SCHEMA_NEWS = """
CREATE TABLE IF NOT EXISTS news (
    url               TEXT NOT NULL,
    stock_code        TEXT NOT NULL,
    title             TEXT NOT NULL,
    content           TEXT,
    published_at      TIMESTAMP NOT NULL,
    source            TEXT,
    sentiment_score   DOUBLE,
    sentiment_impact  TEXT,
    sentiment_summary TEXT,
    scored_at         TIMESTAMP,
    scored_model      TEXT,
    PRIMARY KEY (url, stock_code)
);
"""

ALL_SCHEMAS: list[str] = [
    SCHEMA_STOCKS,
    SCHEMA_PRICES_DAILY,
    SCHEMA_INSTITUTIONAL,
    SCHEMA_MONTHLY_REVENUE,
    SCHEMA_FINANCIALS,
    SCHEMA_INDICATORS,
    SCHEMA_LLM_USAGE,
    SCHEMA_NEWS,
]

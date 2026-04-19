"""從 news 表聚合出每檔 7 日情緒分數 (0-100)。

公式:
    weighted_avg = Σ (score × impact_weight × time_decay) / Σ (impact_weight × time_decay)
    sentiment_score_0_100 = (weighted_avg + 1) / 2 × 100   # -1..+1 → 0..100

不存在新聞/未打分的股票給 50 (中性)。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from stock_llm.data.store import connect

IMPACT_WEIGHT = {"high": 2.0, "medium": 1.0, "low": 0.5}
DECAY_HALF_LIFE_DAYS = 1.5

SENTIMENT_FEATURE_COLUMNS = [
    "stock_code",
    "news_count_7d",
    "news_sentiment_raw",       # -1..+1
    "news_sentiment_score",     # 0..100
]


def compute_sentiment_features(
    as_of: date,
    stock_codes: list[str],
    lookback_days: int = 5,
) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame(columns=SENTIMENT_FEATURE_COLUMNS)

    cutoff = datetime.combine(as_of, datetime.min.time()) - timedelta(days=lookback_days)
    placeholders = ",".join("?" for _ in stock_codes)
    with connect() as con:
        df = con.execute(
            f"""
            SELECT stock_code, published_at, sentiment_score, sentiment_impact
            FROM news
            WHERE stock_code IN ({placeholders})
              AND published_at >= ?
              AND sentiment_score IS NOT NULL
            """,
            [*stock_codes, cutoff],
        ).fetchdf()

    rows = []
    as_of_ts = datetime.combine(as_of, datetime.min.time())
    for code in stock_codes:
        sub = df[df["stock_code"] == code] if not df.empty else df
        if sub.empty:
            rows.append({
                "stock_code": code,
                "news_count_7d": 0,
                "news_sentiment_raw": 0.0,
                "news_sentiment_score": 50.0,
            })
            continue

        weights = []
        scores = []
        for _, r in sub.iterrows():
            impact_w = IMPACT_WEIGHT.get(r["sentiment_impact"], 0.5)
            delta_days = max(0.0, (as_of_ts - pd.to_datetime(r["published_at"])).total_seconds() / 86400)
            decay = 0.5 ** (delta_days / DECAY_HALF_LIFE_DAYS)
            w = impact_w * decay
            weights.append(w)
            scores.append(float(r["sentiment_score"]) * w)

        total_w = sum(weights)
        raw = (sum(scores) / total_w) if total_w > 0 else 0.0
        raw = max(-1.0, min(1.0, raw))
        rows.append({
            "stock_code": code,
            "news_count_7d": int(len(sub)),
            "news_sentiment_raw": raw,
            "news_sentiment_score": (raw + 1) / 2 * 100,
        })

    return pd.DataFrame(rows, columns=SENTIMENT_FEATURE_COLUMNS)

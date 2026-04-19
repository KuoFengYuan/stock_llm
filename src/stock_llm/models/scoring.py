from __future__ import annotations

import numpy as np
import pandas as pd

from stock_llm.features.tags import ai_bonus, get_tags, has_ai_concept

SCORE_COLUMNS = [
    "stock_code",
    "tech_score", "chip_score", "sentiment_score", "fund_score",
    "ai_bonus", "is_ai_concept", "tags",
    "short_score", "long_score",
    "rank_short", "rank_long",
]


def _safe(v, default=0.0):
    return default if v is None or pd.isna(v) else float(v)


def _technical_subscore(row) -> float:
    s = 0.0
    if bool(row.get("ma_bullish", False)):
        s += 25
    rsi = _safe(row.get("rsi14"), default=50)
    if 30 < rsi < 70:
        s += 15
    elif rsi <= 30:
        s += 10
    if bool(row.get("macd_golden_cross", False)):
        s += 20
    if bool(row.get("kd_golden_cross", False)):
        s += 15
    vol_ratio = _safe(row.get("volume_ratio"))
    if vol_ratio > 1.3:
        s += 15
    elif vol_ratio > 1.0:
        s += 8
    price_vs_ma20 = _safe(row.get("price_vs_ma20_pct"))
    if 0 < price_vs_ma20 < 0.1:
        s += 10
    return min(s, 100)


def _chip_subscore(row) -> float:
    s = 0.0
    intensity = _safe(row.get("inst_intensity"))
    s += min(max(intensity, 0) * 1000, 40)
    consec = _safe(row.get("foreign_consecutive_buy_days"))
    s += min(consec * 10, 30)
    foreign_5d = _safe(row.get("foreign_net_5d_cum"))
    if foreign_5d > 0:
        s += 30
    return min(s, 100)


def _sentiment_subscore(row) -> float:
    # Placeholder — will come from news LLM (Phase 3)
    return 50.0


def _fundamental_subscore(row) -> float:
    if not bool(row.get("has_fundamental_data", False)):
        return np.nan
    s = 0.0
    yoy = _safe(row.get("revenue_yoy_latest"))
    if yoy > 0.2:
        s += 25
    elif yoy > 0.05:
        s += 15
    elif yoy > 0:
        s += 5
    yoy_3m = _safe(row.get("revenue_yoy_3m_avg"))
    if yoy_3m > 0.1:
        s += 15
    pos_6m = _safe(row.get("revenue_months_positive_yoy_6m"))
    s += min(pos_6m * 3, 15)
    gm = _safe(row.get("gross_margin_latest"))
    if gm > 0.35:
        s += 15
    elif gm > 0.2:
        s += 10
    elif gm > 0.1:
        s += 5
    gm_trend = _safe(row.get("gross_margin_trend"))
    if gm_trend > 0.02:
        s += 15
    elif gm_trend > 0:
        s += 8
    nm = _safe(row.get("net_margin_latest"))
    if nm > 0.15:
        s += 15
    elif nm > 0.05:
        s += 8
    return min(s, 100)


def score_snapshot(features: pd.DataFrame, ai_boost: float = 6.0) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame(columns=SCORE_COLUMNS)

    f = features.copy()
    f["tech_score"] = f.apply(_technical_subscore, axis=1)
    f["chip_score"] = f.apply(_chip_subscore, axis=1)
    f["sentiment_score"] = f.apply(_sentiment_subscore, axis=1)
    f["fund_score"] = f.apply(_fundamental_subscore, axis=1)

    f["is_ai_concept"] = f["stock_code"].map(has_ai_concept)
    f["tags"] = f["stock_code"].map(get_tags)
    f["ai_bonus"] = f["stock_code"].map(lambda c: ai_bonus(c, weight=ai_boost))

    f["short_score"] = (
        0.5 * f["tech_score"]
        + 0.3 * f["chip_score"]
        + 0.2 * f["sentiment_score"]
        + f["ai_bonus"]
    ).clip(upper=100)

    def _long(r):
        if pd.isna(r.fund_score):
            return np.nan
        base = 0.6 * r.fund_score + 0.25 * r.tech_score + 0.15 * r.chip_score
        return min(base + r.ai_bonus, 100)

    f["long_score"] = f.apply(_long, axis=1)

    f["rank_short"] = f["short_score"].rank(ascending=False, method="min")
    f["rank_long"] = f["long_score"].rank(ascending=False, method="min")

    return f

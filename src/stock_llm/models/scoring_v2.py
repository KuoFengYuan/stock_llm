"""V2 scoring inspired by Mark Minervini's SEPA and William O'Neil's CAN SLIM.

Key principles:
1. Trend-following only — Stage 2 uptrend (Minervini)
2. Relative strength matters more than absolute price
3. 52-week high position is critical
4. EPS acceleration (CAN SLIM C + A)
5. Volume confirms breakout
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from stock_llm.features.tags import ai_bonus, get_tags, has_ai_concept

V2_SCORE_COLUMNS = [
    "stock_code",
    "tech_score", "chip_score", "sentiment_score", "fund_score",
    "ai_bonus", "is_ai_concept", "tags",
    "short_score", "long_score",
    "rank_short", "rank_long",
    "scoring_version",
]


def _safe(v, default=0.0):
    return default if v is None or pd.isna(v) else float(v)


def _technical_subscore_v2(row) -> float:
    """SEPA-inspired technical score."""
    s = 0.0

    s += float(_safe(row.get("stage2_score"))) * 5

    rs90 = _safe(row.get("rs_90d_pct"))
    rs20 = _safe(row.get("rs_20d_pct"))
    if rs90 > 0.20:    s += 10
    elif rs90 > 0.05:  s += 6
    elif rs90 > 0:     s += 3
    if rs20 > 0.10:    s += 10
    elif rs20 > 0.03:  s += 6
    elif rs20 > 0:     s += 3

    pct_from_high = _safe(row.get("pct_from_52w_high"), default=-1)
    if pct_from_high >= -0.05:    s += 15
    elif pct_from_high >= -0.15:  s += 10
    elif pct_from_high >= -0.30:  s += 4

    if bool(row.get("breakout_20d", False)):
        s += 10

    if bool(row.get("macd_golden_cross", False)):
        s += 5
    rsi = _safe(row.get("rsi14"), default=50)
    if 40 < rsi < 75:
        s += 5

    return min(s, 100)


def _chip_subscore_v2(row) -> float:
    """Institutional flow — rewards foreign + invest buying (incl. independent),
    volume surges, and streaks; penalises sustained selling.

    Starts at a neutral baseline of 40 so that stocks with no institutional
    flow don't get punished to zero like before.
    """
    s = 40.0

    foreign_5d = _safe(row.get("foreign_net_5d_cum"))
    invest_5d = _safe(row.get("invest_net_5d_cum"))
    if foreign_5d > 0:
        s += 15
    if invest_5d > 0:
        s += 15
    if foreign_5d > 0 and invest_5d > 0:
        s += 10

    if foreign_5d < 0:
        s -= 10
    if invest_5d < 0:
        s -= 5

    f_buy = _safe(row.get("foreign_consecutive_buy_days"))
    f_sell = _safe(row.get("foreign_consecutive_sell_days"))
    i_buy = _safe(row.get("invest_consecutive_buy_days"))
    i_sell = _safe(row.get("invest_consecutive_sell_days"))
    s += min(f_buy * 2, 12)
    s += min(i_buy * 2, 10)
    s -= min(f_sell * 2, 12)
    s -= min(i_sell * 1.5, 8)

    intensity = _safe(row.get("inst_intensity"))
    if intensity > 0:
        s += min(intensity * 1200, 20)
    elif intensity < 0:
        s += max(intensity * 800, -15)

    vol_ratio = _safe(row.get("volume_ratio"), default=1.0)
    if vol_ratio > 1.5:
        s += 10
    elif vol_ratio > 1.2:
        s += 5

    return max(0.0, min(s, 100.0))


def _sentiment_subscore_v2(row) -> float:
    """Read news-driven sentiment (0-100) from features.
    Defaults to 50 (neutral) when no scored news exists for the stock.
    """
    v = row.get("news_sentiment_score")
    if v is None or pd.isna(v):
        return 50.0
    return float(v)


def _fundamental_subscore_v2(row) -> float:
    """CAN SLIM-inspired fundamental score."""
    if not bool(row.get("has_fundamental_data", False)):
        return np.nan
    s = 0.0

    if bool(row.get("canslim_c_pass", False)):
        s += 25
    else:
        eps_yoy_q = _safe(row.get("eps_yoy_quarterly"))
        if eps_yoy_q > 0.10:
            s += 12
        elif eps_yoy_q > 0:
            s += 5

    if bool(row.get("canslim_a_pass", False)):
        s += 20
    else:
        eps_yoy_a = _safe(row.get("eps_yoy_annual"))
        if eps_yoy_a > 0.10:
            s += 10

    rev_accel = _safe(row.get("revenue_acceleration"))
    if rev_accel > 0.05:
        s += 15
    elif rev_accel > 0:
        s += 8

    rev_yoy_3m = _safe(row.get("revenue_yoy_3m_avg"))
    if rev_yoy_3m > 0.20:
        s += 10
    elif rev_yoy_3m > 0.05:
        s += 5

    gm = _safe(row.get("gross_margin_latest"))
    if gm > 0.35:    s += 10
    elif gm > 0.20:  s += 5

    gm_trend = _safe(row.get("gross_margin_trend"))
    if gm_trend > 0.02:  s += 10
    elif gm_trend > 0:   s += 5

    if bool(row.get("near_52w_high", False)):
        s += 10

    return min(s, 100)


def score_snapshot_v2(features: pd.DataFrame, ai_boost: float = 6.0) -> pd.DataFrame:
    if features.empty:
        return pd.DataFrame(columns=V2_SCORE_COLUMNS)

    f = features.copy()
    f["tech_score"] = f.apply(_technical_subscore_v2, axis=1)
    f["chip_score"] = f.apply(_chip_subscore_v2, axis=1)
    f["sentiment_score"] = f.apply(_sentiment_subscore_v2, axis=1)
    f["fund_score"] = f.apply(_fundamental_subscore_v2, axis=1)

    f["is_ai_concept"] = f["stock_code"].map(has_ai_concept)
    f["tags"] = f["stock_code"].map(get_tags)
    f["ai_bonus"] = f["stock_code"].map(lambda c: ai_bonus(c, weight=ai_boost))

    f["short_score"] = (
        0.55 * f["tech_score"]
        + 0.30 * f["chip_score"]
        + 0.15 * f["sentiment_score"]
        + f["ai_bonus"]
    ).clip(upper=100)

    def _long(r):
        if pd.isna(r.fund_score):
            return np.nan
        base = 0.55 * r.fund_score + 0.30 * r.tech_score + 0.15 * r.chip_score
        return min(base + r.ai_bonus, 100)

    f["long_score"] = f.apply(_long, axis=1)
    f["scoring_version"] = "v2"

    f["rank_short"] = f["short_score"].rank(ascending=False, method="min")
    f["rank_long"] = f["long_score"].rank(ascending=False, method="min")

    return f

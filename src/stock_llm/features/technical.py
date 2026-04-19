from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from stock_llm.data.store import connect

TECHNICAL_FEATURE_COLUMNS = [
    "stock_code",
    "close", "avg_volume_5d",
    "ma5", "ma20", "ma60",
    "ma50", "ma150", "ma200",
    "ma_bullish",
    "ma_short_bullish",
    "price_above_all_ma",
    "stage2_uptrend",
    "stage2_score",
    "week52_high", "week52_low",
    "pct_from_52w_high", "pct_above_52w_low",
    "near_52w_high",
    "breakout_20d",
    "rs_90d_pct", "rs_20d_pct",
    "price_vs_ma20_pct",
    "rsi14", "rsi_zone",
    "macd_hist", "macd_golden_cross",
    "k9", "d9", "kd_golden_cross",
    "bb_position",
    "volume_ratio",
    "consecutive_up_days", "consecutive_down_days",
]


def _rsi_zone(val: float) -> str:
    if pd.isna(val):
        return "na"
    if val < 30:
        return "oversold"
    if val > 70:
        return "overbought"
    return "normal"


def _consecutive_days(series: pd.Series, sign: int) -> int:
    count = 0
    for v in reversed(series.tolist()):
        if pd.isna(v):
            break
        if (sign > 0 and v > 0) or (sign < 0 and v < 0):
            count += 1
        else:
            break
    return count


def _stage2_check(close: float, ma50: float, ma150: float, ma200: float,
                  ma200_old: float, w52_high: float, w52_low: float) -> tuple[bool, int]:
    """Mark Minervini's Stage 2 trend criteria. Returns (is_full_stage2, partial_score 0-8)."""
    if any(pd.isna(v) for v in [close, ma50, ma150, ma200, w52_high, w52_low]):
        return (False, 0)

    checks = [
        close > ma150,
        close > ma200,
        ma150 > ma200,
        (not pd.isna(ma200_old)) and ma200 > ma200_old,
        close > ma50,
        ma50 > ma150 > ma200,
        w52_low > 0 and close >= w52_low * 1.30,
        w52_high > 0 and close >= w52_high * 0.75,
    ]
    passed = sum(1 for c in checks if c)
    return (all(checks), passed)


def compute_technical_features(
    as_of: date,
    stock_codes: list[str],
    lookback_days: int = 320,
) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame(columns=TECHNICAL_FEATURE_COLUMNS)

    placeholders = ",".join("?" for _ in stock_codes)
    with connect() as con:
        df = con.execute(
            f"""
            SELECT p.stock_code, p.trade_date, p.close, p.high, p.low, p.volume,
                   i.ma5, i.ma20, i.ma60, i.rsi14,
                   i.macd, i.macd_signal, i.macd_hist,
                   i.k9, i.d9, i.bb_upper, i.bb_lower, i.volume_ratio
            FROM prices_daily p
            LEFT JOIN indicators_daily i USING (stock_code, trade_date)
            WHERE p.stock_code IN ({placeholders})
              AND p.trade_date BETWEEN ? AND ?
            ORDER BY p.stock_code, p.trade_date
            """,
            [*stock_codes, as_of - timedelta(days=lookback_days), as_of],
        ).fetchdf()

    if df.empty:
        return pd.DataFrame(columns=TECHNICAL_FEATURE_COLUMNS)

    rows: list[dict] = []
    for code, g in df.groupby("stock_code"):
        if g.empty or len(g) < 5:
            continue
        g = g.sort_values("trade_date").reset_index(drop=True)
        last = g.iloc[-1]
        prev = g.iloc[-2] if len(g) > 1 else last

        ma50 = g["close"].tail(50).mean() if len(g) >= 50 else np.nan
        ma150 = g["close"].tail(150).mean() if len(g) >= 150 else np.nan
        ma200 = g["close"].tail(200).mean() if len(g) >= 200 else np.nan
        if len(g) >= 220:
            ma200_old = g["close"].iloc[-220:-20].mean()
        else:
            ma200_old = np.nan

        w52 = g.tail(252)
        w52_high = w52["high"].max() if not w52.empty else np.nan
        w52_low = w52["low"].min() if not w52.empty else np.nan
        pct_from_high = (last.close / w52_high - 1) if pd.notna(w52_high) and w52_high > 0 else np.nan
        pct_above_low = (last.close / w52_low - 1) if pd.notna(w52_low) and w52_low > 0 else np.nan
        near_52w_high = bool(pd.notna(pct_from_high) and pct_from_high >= -0.15)

        stage2_full, stage2_partial = _stage2_check(
            last.close, ma50, ma150, ma200, ma200_old, w52_high, w52_low
        )

        h20 = g["close"].tail(20).max() if len(g) >= 20 else np.nan
        breakout_20d = bool(
            pd.notna(h20) and last.close >= h20 * 0.999
            and pd.notna(last.volume_ratio) and last.volume_ratio >= 1.4
        )

        if len(g) >= 91:
            rs_90d = last.close / g["close"].iloc[-91] - 1
        else:
            rs_90d = np.nan
        if len(g) >= 21:
            rs_20d = last.close / g["close"].iloc[-21] - 1
        else:
            rs_20d = np.nan

        ma_bullish = bool(
            pd.notna(last.ma5) and pd.notna(last.ma20) and pd.notna(last.ma60)
            and last.ma5 > last.ma20 > last.ma60
        )
        ma_short_bullish = bool(
            pd.notna(last.ma5) and pd.notna(last.ma20)
            and last.ma5 > last.ma20
        )
        price_above_all_ma = bool(
            pd.notna(last.ma5) and pd.notna(last.ma20) and pd.notna(last.ma60)
            and last.close > last.ma5
            and last.close > last.ma20
            and last.close > last.ma60
        )
        price_vs_ma20 = (
            (last.close / last.ma20 - 1) if pd.notna(last.ma20) and last.ma20 > 0 else np.nan
        )
        macd_golden = bool(
            pd.notna(last.macd_hist) and pd.notna(prev.macd_hist)
            and prev.macd_hist <= 0 and last.macd_hist > 0
        )
        kd_golden = bool(
            pd.notna(last.k9) and pd.notna(last.d9) and pd.notna(prev.k9) and pd.notna(prev.d9)
            and prev.k9 <= prev.d9 and last.k9 > last.d9
        )
        bb_range = last.bb_upper - last.bb_lower if pd.notna(last.bb_upper) else np.nan
        bb_pos = (
            (last.close - last.bb_lower) / bb_range
            if pd.notna(bb_range) and bb_range > 0 else np.nan
        )
        daily_chg = g["close"].diff()
        up_days = _consecutive_days(daily_chg, sign=1)
        down_days = _consecutive_days(daily_chg, sign=-1)

        rows.append({
            "stock_code": code,
            "close": last.close,
            "avg_volume_5d": g["volume"].tail(5).mean(),
            "ma5": last.ma5, "ma20": last.ma20, "ma60": last.ma60,
            "ma50": ma50, "ma150": ma150, "ma200": ma200,
            "ma_bullish": ma_bullish,
            "ma_short_bullish": ma_short_bullish,
            "price_above_all_ma": price_above_all_ma,
            "stage2_uptrend": stage2_full,
            "stage2_score": stage2_partial,
            "week52_high": w52_high, "week52_low": w52_low,
            "pct_from_52w_high": pct_from_high, "pct_above_52w_low": pct_above_low,
            "near_52w_high": near_52w_high,
            "breakout_20d": breakout_20d,
            "rs_90d_pct": rs_90d, "rs_20d_pct": rs_20d,
            "price_vs_ma20_pct": price_vs_ma20,
            "rsi14": last.rsi14,
            "rsi_zone": _rsi_zone(last.rsi14),
            "macd_hist": last.macd_hist,
            "macd_golden_cross": macd_golden,
            "k9": last.k9, "d9": last.d9,
            "kd_golden_cross": kd_golden,
            "bb_position": bb_pos,
            "volume_ratio": last.volume_ratio,
            "consecutive_up_days": up_days,
            "consecutive_down_days": down_days,
        })

    return pd.DataFrame(rows, columns=TECHNICAL_FEATURE_COLUMNS)

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from stock_llm.data.store import connect

CHIP_FEATURE_COLUMNS = [
    "stock_code",
    "foreign_net_1d", "foreign_net_5d_cum", "foreign_net_20d_cum",
    "foreign_consecutive_buy_days", "foreign_consecutive_sell_days",
    "invest_net_5d_cum",
    "invest_consecutive_buy_days", "invest_consecutive_sell_days",
    "dealer_net_5d_cum",
    "total_inst_net_5d_cum",
    "inst_intensity",
]


def _consecutive_streak(values: list[float], sign: int) -> int:
    """Count trailing days where sign(value) matches `sign` (+1 buy, -1 sell)."""
    count = 0
    for v in reversed(values):
        if pd.isna(v):
            break
        if (sign > 0 and v > 0) or (sign < 0 and v < 0):
            count += 1
        else:
            break
    return count


def compute_chip_features(
    as_of: date,
    stock_codes: list[str],
    lookback_days: int = 30,
) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame(columns=CHIP_FEATURE_COLUMNS)

    placeholders = ",".join("?" for _ in stock_codes)
    with connect() as con:
        inst = con.execute(
            f"""
            SELECT stock_code, trade_date, foreign_net, invest_net, dealer_net
            FROM institutional_daily
            WHERE stock_code IN ({placeholders})
              AND trade_date BETWEEN ? AND ?
            ORDER BY stock_code, trade_date
            """,
            [*stock_codes, as_of - timedelta(days=lookback_days), as_of],
        ).fetchdf()

        volume = con.execute(
            f"""
            SELECT stock_code, AVG(volume) AS avg_vol_5d
            FROM (
                SELECT stock_code, volume,
                       ROW_NUMBER() OVER (PARTITION BY stock_code ORDER BY trade_date DESC) AS rn
                FROM prices_daily
                WHERE stock_code IN ({placeholders}) AND trade_date <= ?
            ) WHERE rn <= 5
            GROUP BY stock_code
            """,
            [*stock_codes, as_of],
        ).fetchdf()

    if inst.empty:
        return pd.DataFrame(columns=CHIP_FEATURE_COLUMNS)

    vol_map = dict(zip(volume["stock_code"], volume["avg_vol_5d"]))

    rows: list[dict] = []
    for code, g in inst.groupby("stock_code"):
        if g.empty:
            continue
        g = g.sort_values("trade_date")
        foreign = g["foreign_net"].tolist()
        invest = g["invest_net"].tolist()
        dealer = g["dealer_net"].tolist()

        foreign_5 = sum(foreign[-5:]) if foreign else 0
        foreign_20 = sum(foreign[-20:]) if foreign else 0
        invest_5 = sum(invest[-5:]) if invest else 0
        dealer_5 = sum(dealer[-5:]) if dealer else 0
        total_5 = foreign_5 + invest_5 + dealer_5

        f_buy = _consecutive_streak(foreign, +1)
        f_sell = _consecutive_streak(foreign, -1)
        i_buy = _consecutive_streak(invest, +1)
        i_sell = _consecutive_streak(invest, -1)
        avg_vol = vol_map.get(code, np.nan)
        intensity = (total_5 / avg_vol / 5) if avg_vol and avg_vol > 0 else np.nan

        rows.append({
            "stock_code": code,
            "foreign_net_1d": foreign[-1] if foreign else np.nan,
            "foreign_net_5d_cum": foreign_5,
            "foreign_net_20d_cum": foreign_20,
            "foreign_consecutive_buy_days": f_buy,
            "foreign_consecutive_sell_days": f_sell,
            "invest_net_5d_cum": invest_5,
            "invest_consecutive_buy_days": i_buy,
            "invest_consecutive_sell_days": i_sell,
            "dealer_net_5d_cum": dealer_5,
            "total_inst_net_5d_cum": total_5,
            "inst_intensity": intensity,
        })

    return pd.DataFrame(rows, columns=CHIP_FEATURE_COLUMNS)

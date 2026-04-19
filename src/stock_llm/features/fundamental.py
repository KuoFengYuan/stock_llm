from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd

from stock_llm.data.store import connect

FUNDAMENTAL_FEATURE_COLUMNS = [
    "stock_code",
    "revenue_yoy_latest", "revenue_yoy_3m_avg",
    "revenue_mom_latest",
    "revenue_months_positive_yoy_6m",
    "revenue_acceleration",
    "eps_latest", "eps_yoy_latest",
    "eps_yoy_quarterly", "eps_yoy_annual",
    "canslim_c_pass", "canslim_a_pass",
    "gross_margin_latest", "gross_margin_trend",
    "net_margin_latest",
    "has_fundamental_data",
]


def _yoy(cur: float, prev: float) -> float:
    if pd.isna(cur) or pd.isna(prev) or prev == 0:
        return np.nan
    return cur / prev - 1


def compute_fundamental_features(
    as_of: date,
    stock_codes: list[str],
) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame(columns=FUNDAMENTAL_FEATURE_COLUMNS)

    placeholders = ",".join("?" for _ in stock_codes)
    with connect() as con:
        rev = con.execute(
            f"""
            SELECT stock_code, year_month, revenue, revenue_yoy, revenue_mom
            FROM monthly_revenue
            WHERE stock_code IN ({placeholders})
              AND year_month <= ?
            ORDER BY stock_code, year_month
            """,
            [*stock_codes, as_of.strftime("%Y-%m")],
        ).fetchdf()

        fin = con.execute(
            f"""
            SELECT stock_code, year_quarter, eps, gross_margin, net_margin
            FROM financials_quarterly
            WHERE stock_code IN ({placeholders})
            ORDER BY stock_code, year_quarter
            """,
            [*stock_codes],
        ).fetchdf()

    rows: list[dict] = []
    for code in stock_codes:
        r = rev[rev["stock_code"] == code].sort_values("year_month") if not rev.empty else rev
        f = fin[fin["stock_code"] == code].sort_values("year_quarter") if not fin.empty else fin

        rev_yoy_last = r["revenue_yoy"].iloc[-1] if not r.empty else np.nan
        rev_yoy_3m = r["revenue_yoy"].tail(3).mean() if len(r) >= 3 else np.nan
        rev_mom_last = r["revenue_mom"].iloc[-1] if not r.empty else np.nan
        rev_pos_6m = int((r["revenue_yoy"].tail(6) > 0).sum()) if len(r) >= 1 else 0

        if len(r) >= 6:
            recent_3 = r["revenue_yoy"].tail(3).mean()
            older_3 = r["revenue_yoy"].iloc[-6:-3].mean()
            rev_accel = recent_3 - older_3 if pd.notna(recent_3) and pd.notna(older_3) else np.nan
        else:
            rev_accel = np.nan

        eps_last = f["eps"].iloc[-1] if not f.empty else np.nan
        if len(f) >= 5:
            eps_yoy = _yoy(f["eps"].iloc[-1], f["eps"].iloc[-5])
        else:
            eps_yoy = np.nan
        eps_yoy_q = eps_yoy

        if len(f) >= 8:
            eps_ttm = f["eps"].iloc[-4:].sum()
            eps_ttm_prev = f["eps"].iloc[-8:-4].sum()
            eps_yoy_a = _yoy(eps_ttm, eps_ttm_prev)
        else:
            eps_yoy_a = np.nan

        canslim_c = bool(pd.notna(eps_yoy_q) and eps_yoy_q >= 0.25)
        canslim_a = bool(pd.notna(eps_yoy_a) and eps_yoy_a >= 0.25)

        gm_last = f["gross_margin"].iloc[-1] if not f.empty else np.nan
        if len(f) >= 4:
            recent = f["gross_margin"].tail(4).mean()
            older = f["gross_margin"].tail(8).head(4).mean() if len(f) >= 8 else recent
            gm_trend = recent - older
        else:
            gm_trend = np.nan
        nm_last = f["net_margin"].iloc[-1] if not f.empty else np.nan

        has_data = (not r.empty) or (not f.empty)

        rows.append({
            "stock_code": code,
            "revenue_yoy_latest": rev_yoy_last,
            "revenue_yoy_3m_avg": rev_yoy_3m,
            "revenue_mom_latest": rev_mom_last,
            "revenue_months_positive_yoy_6m": rev_pos_6m,
            "revenue_acceleration": rev_accel,
            "eps_latest": eps_last,
            "eps_yoy_latest": eps_yoy,
            "eps_yoy_quarterly": eps_yoy_q,
            "eps_yoy_annual": eps_yoy_a,
            "canslim_c_pass": canslim_c,
            "canslim_a_pass": canslim_a,
            "gross_margin_latest": gm_last,
            "gross_margin_trend": gm_trend,
            "net_margin_latest": nm_last,
            "has_fundamental_data": has_data,
        })

    return pd.DataFrame(rows, columns=FUNDAMENTAL_FEATURE_COLUMNS)

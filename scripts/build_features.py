"""Build a feature snapshot for the top-N universe as of latest trade date."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.store import connect
from stock_llm.data.universe import top_by_turnover
from stock_llm.features.snapshot import build_feature_snapshot


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=500, help="Top-N stocks by turnover")
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD (default: latest price date)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.as_of:
        from datetime import date
        as_of = date.fromisoformat(args.as_of)
    else:
        with connect() as con:
            as_of = con.execute(
                "SELECT MAX(trade_date) FROM prices_daily"
            ).fetchone()[0]

    print(f">> Building features as of {as_of}")
    codes = top_by_turnover(args.top_n)
    print(f">> Universe: {len(codes)} stocks")

    df = build_feature_snapshot(as_of, codes)
    print(f">> Snapshot: {len(df)} rows, {len(df.columns)} columns")

    have_fund = df["has_fundamental_data"].sum() if "has_fundamental_data" in df.columns else 0
    print(f">> Fundamentals available: {have_fund}/{len(df)}")

    print("\n=== Sample (head 5) ===")
    cols = [
        "stock_code", "close", "ma_bullish", "rsi14", "macd_golden_cross",
        "foreign_net_5d_cum", "foreign_consecutive_buy_days",
        "revenue_yoy_latest", "gross_margin_latest", "has_fundamental_data",
    ]
    show_cols = [c for c in cols if c in df.columns]
    print(df[show_cols].head(5).to_string(index=False))

    print("\n=== Signal summary (top universe) ===")
    summary = {
        "MA 多頭排列": int(df["ma_bullish"].sum()),
        "MACD 黃金交叉": int(df["macd_golden_cross"].sum()),
        "KD 黃金交叉": int(df["kd_golden_cross"].sum()),
        "外資連買 ≥3 日": int((df["foreign_consecutive_buy_days"] >= 3).sum()),
        "RSI 超賣 (<30)": int((df["rsi_zone"] == "oversold").sum()),
        "RSI 超買 (>70)": int((df["rsi_zone"] == "overbought").sum()),
    }
    for k, v in summary.items():
        print(f"  {k:20s}: {v}")

    print("\n[OK] Features built.")


if __name__ == "__main__":
    main()

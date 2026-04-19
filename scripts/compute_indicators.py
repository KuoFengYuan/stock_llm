"""Compute technical indicators from prices_daily and persist to indicators_daily."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.store import connect, upsert_indicators
from stock_llm.features.indicators import compute_indicators


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Only N stocks (testing)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect() as con:
        where = ""
        if args.limit:
            codes = con.execute(
                f"SELECT stock_code FROM stocks ORDER BY stock_code LIMIT {args.limit}"
            ).fetchdf()["stock_code"].tolist()
            placeholders = ",".join(f"'{c}'" for c in codes)
            where = f" WHERE stock_code IN ({placeholders})"
        prices = con.execute(
            f"SELECT stock_code, trade_date, open, high, low, close, volume "
            f"FROM prices_daily{where}"
        ).fetchdf()

    if prices.empty:
        print("[WARN] No prices in DB. Run fetch_prices.py first.")
        return

    print(f">> Loaded {len(prices)} price rows for "
          f"{prices['stock_code'].nunique()} stocks")

    print(">> Computing indicators...")
    df = compute_indicators(prices)
    print(f">> Computed {len(df)} indicator rows")

    print(">> Upserting to DuckDB...")
    total = upsert_indicators(df)
    print(f">> Total rows in indicators_daily: {total}")

    with connect() as con:
        sample = con.execute(
            """
            SELECT stock_code, trade_date, close, ma5, ma20, ma60,
                   rsi14, macd, k9, d9, volume_ratio
            FROM indicators_daily i
            JOIN prices_daily p USING (stock_code, trade_date)
            WHERE stock_code = '2330'
            ORDER BY trade_date DESC
            LIMIT 5
            """
        ).fetchdf()
    print("\n=== Sample (2330 台積電 latest 5 days) ===")
    print(sample.to_string(index=False))
    print("\n[OK] Indicators computed.")


if __name__ == "__main__":
    main()

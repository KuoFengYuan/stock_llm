"""Fetch daily OHLCV via yfinance for TWSE listed stocks and persist to DuckDB."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.prices import fetch_prices
from stock_llm.data.store import connect, upsert_prices


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch TWSE daily prices via yfinance.")
    parser.add_argument("--days", type=int, default=730, help="History window in days (default: 730 = 2y)")
    parser.add_argument("--limit", type=int, default=None, help="Only fetch first N stocks (for testing)")
    parser.add_argument("--batch-size", type=int, default=50, help="yfinance batch size")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    with connect() as con:
        query = "SELECT stock_code FROM stocks ORDER BY stock_code"
        if args.limit:
            query += f" LIMIT {args.limit}"
        codes = con.execute(query).fetchdf()["stock_code"].tolist()

    if not codes:
        print("[WARN] No stocks in DB. Run fetch_stock_list.py first.")
        return

    print(f">> Fetching {len(codes)} stocks, last {args.days} days, batch={args.batch_size}")
    df = fetch_prices(codes, days=args.days, batch_size=args.batch_size)
    print(f">> Fetched {len(df)} price rows")

    if df.empty:
        print("[WARN] No prices returned from yfinance.")
        return

    print("\n=== Sample (first 5) ===")
    print(df.head(5).to_string(index=False))

    print("\n>> Upserting to DuckDB...")
    total = upsert_prices(df)
    print(f">> Total price rows in DB: {total}")

    with connect() as con:
        stats = con.execute(
            """
            SELECT
                COUNT(DISTINCT stock_code)       AS stocks,
                MIN(trade_date)                  AS earliest,
                MAX(trade_date)                  AS latest,
                COUNT(*)                         AS rows
            FROM prices_daily
            """
        ).fetchdf()

    print("\n=== DB Stats ===")
    print(stats.to_string(index=False))
    print("\n[OK] Prices refreshed.")


if __name__ == "__main__":
    main()

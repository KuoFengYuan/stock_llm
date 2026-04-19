"""Fetch three-institutional-investors daily net buys from FinMind."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.store import connect, upsert_institutional
from stock_llm.data.twse import fetch_institutional_range


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=90, help="Days back to fetch (default 90)")
    parser.add_argument("--sleep", type=float, default=1.0, help="Sleep between TWSE calls (sec)")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print(f">> Fetching institutional data (last {args.days} days)")
    df = fetch_institutional_range(days=args.days, sleep=args.sleep)
    print(f">> Got {len(df)} rows for {df['stock_code'].nunique() if not df.empty else 0} stocks")

    if df.empty:
        print("[WARN] No data returned.")
        return

    print("\n=== Sample (top 5 by |foreign_net|) ===")
    sample = df.reindex(df["foreign_net"].abs().sort_values(ascending=False).index).head(5)
    print(sample.to_string(index=False))

    total = upsert_institutional(df)
    print(f"\n>> DB rows in institutional_daily: {total}")

    with connect() as con:
        stats = con.execute(
            """
            SELECT COUNT(DISTINCT stock_code) AS stocks,
                   MIN(trade_date)            AS earliest,
                   MAX(trade_date)            AS latest,
                   COUNT(*)                   AS rows
            FROM institutional_daily
            """
        ).fetchdf()
    print("\n=== DB Stats ===")
    print(stats.to_string(index=False))
    print("\n[OK] Institutional data refreshed.")


if __name__ == "__main__":
    main()

"""Fetch TWSE listed stocks and persist to DuckDB."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.store import connect, init_db, upsert_stocks
from stock_llm.data.twse import fetch_listed_stocks


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    print(">> Initializing DuckDB schema...")
    init_db()

    print(">> Fetching TWSE listed stocks...")
    df = fetch_listed_stocks()
    print(f">> Fetched {len(df)} rows")
    print("\n=== Sample (first 10) ===")
    print(df.head(10).to_string(index=False))

    print("\n>> Upserting to DuckDB...")
    total = upsert_stocks(df)
    print(f">> Total stocks in DB: {total}")

    with connect() as con:
        industries = con.execute(
            """
            SELECT industry, COUNT(*) AS cnt
            FROM stocks
            GROUP BY industry
            ORDER BY cnt DESC
            LIMIT 10
            """
        ).fetchdf()

    print("\n=== Top 10 Industries ===")
    print(industries.to_string(index=False))
    print("\n[OK] Stock list refreshed.")


if __name__ == "__main__":
    main()

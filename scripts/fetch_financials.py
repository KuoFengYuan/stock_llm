"""Fetch quarterly financials from FinMind in chunks, saving progress incrementally.

Supports --resume to skip stocks already in DB.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.finmind import fetch_financials_quarterly
from stock_llm.data.store import connect, upsert_financials
from stock_llm.data.universe import top_by_turnover


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=3, help="Years of history (default 3)")
    parser.add_argument("--limit", type=int, default=None, help="Only first N stocks (testing)")
    parser.add_argument("--top-n", type=int, default=None, help="Only top-N by turnover")
    parser.add_argument("--sleep", type=float, default=0.3, help="Sleep between FinMind calls")
    parser.add_argument("--chunk-size", type=int, default=50, help="Stocks per flush")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip stocks already present in financials_quarterly table",
    )
    parser.add_argument(
        "--min-quarters",
        type=int,
        default=4,
        help="In --resume mode, only skip stocks with >= N quarters",
    )
    return parser.parse_args()


def _done_stocks(min_quarters: int) -> set[str]:
    with connect() as con:
        df = con.execute(
            """
            SELECT stock_code, COUNT(*) AS n
            FROM financials_quarterly
            GROUP BY stock_code
            HAVING COUNT(*) >= ?
            """,
            [min_quarters],
        ).fetchdf()
    return set(df["stock_code"].tolist())


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = datetime.now().date()
    start = end - timedelta(days=365 * args.years + 30)

    if args.top_n and args.top_n > 0:
        all_codes = top_by_turnover(n=args.top_n)
        print(f">> Universe: top {args.top_n} stocks by 30-day turnover")
    else:
        with connect() as con:
            query = "SELECT stock_code FROM stocks ORDER BY stock_code"
            if args.limit:
                query += f" LIMIT {args.limit}"
            all_codes = con.execute(query).fetchdf()["stock_code"].tolist()
        print(f">> Universe: ALL {len(all_codes)} listed stocks")

    if args.resume:
        done = _done_stocks(args.min_quarters)
        codes = [c for c in all_codes if c not in done]
        print(f">> Resume mode: {len(done)} already done, {len(codes)} remaining")
    else:
        codes = all_codes

    if not codes:
        print(">> Nothing to fetch.")
        return

    print(f">> Target: {len(codes)} stocks, {start} -> {end}, chunk={args.chunk_size}")

    total_chunks = (len(codes) + args.chunk_size - 1) // args.chunk_size
    for idx, i in enumerate(range(0, len(codes), args.chunk_size), start=1):
        chunk = codes[i : i + args.chunk_size]
        print(f">> Chunk {idx}/{total_chunks} ({len(chunk)} stocks starting {chunk[0]})")
        df = fetch_financials_quarterly(chunk, start.isoformat(), end.isoformat(), sleep=args.sleep)
        if not df.empty:
            upsert_financials(df)
            print(f"   +{len(df)} rows flushed")
        else:
            print(f"   [WARN] chunk returned empty — likely rate-limited")

    with connect() as con:
        stats = con.execute(
            """
            SELECT COUNT(DISTINCT stock_code) AS stocks,
                   MIN(year_quarter)          AS earliest,
                   MAX(year_quarter)          AS latest,
                   COUNT(*)                   AS rows
            FROM financials_quarterly
            """
        ).fetchdf()
    print("\n=== DB Stats ===")
    print(stats.to_string(index=False))
    print("\n[OK] Financials refreshed.")


if __name__ == "__main__":
    main()

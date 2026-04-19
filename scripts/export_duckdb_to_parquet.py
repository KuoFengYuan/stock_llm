"""把 DuckDB 所有資料表 export 成 parquet,用於 git push (避免 DB 檔太大)。

輸出到 data/snapshot/<table>.parquet (zstd 壓縮率高於 DuckDB)。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.config import DATA_DIR
from stock_llm.data.store import connect

SNAPSHOT_DIR = DATA_DIR / "snapshot"

TABLES = [
    "stocks",
    "prices_daily",
    "institutional_daily",
    "indicators_daily",
    "monthly_revenue",
    "financials_quarterly",
    "news",
    "llm_usage",
]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    total_rows = 0
    total_bytes = 0
    with connect() as con:
        tables_present = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        for tbl in TABLES:
            if tbl not in tables_present:
                print(f"  [skip] {tbl} (不存在)")
                continue
            out = SNAPSHOT_DIR / f"{tbl}.parquet"
            (rows,) = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
            if rows == 0:
                print(f"  [skip] {tbl} (空表)")
                continue
            con.execute(
                f"COPY (SELECT * FROM {tbl}) TO '{out.as_posix()}' "
                f"(FORMAT PARQUET, COMPRESSION ZSTD, COMPRESSION_LEVEL 9)"
            )
            size = out.stat().st_size
            print(f"  [OK]   {tbl:28s} {rows:>10,} rows  →  {size / 1024:>8,.0f} KB")
            total_rows += rows
            total_bytes += size

    print(f"\n=== 合計: {total_rows:,} rows / {total_bytes / 1024 / 1024:.1f} MB ===")
    print(f"輸出目錄: {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()

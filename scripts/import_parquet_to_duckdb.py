"""從 data/snapshot/*.parquet 重建 DuckDB。

使用時機:
  1. 剛 git clone 完
  2. 想跳過所有 fetch (TWSE/yfinance/FinMind/Anue/LLM) 直接開始用
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.config import DATA_DIR
from stock_llm.data.store import connect

SNAPSHOT_DIR = DATA_DIR / "snapshot"

# Import order matters for FK/PK (stocks 要先)
IMPORT_ORDER = [
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

    if not SNAPSHOT_DIR.exists():
        print(f"[ERROR] 找不到 {SNAPSHOT_DIR}")
        print("先在另一端跑 python scripts/export_duckdb_to_parquet.py")
        sys.exit(1)

    total_rows = 0
    with connect() as con:
        for tbl in IMPORT_ORDER:
            f = SNAPSHOT_DIR / f"{tbl}.parquet"
            if not f.exists():
                print(f"  [skip] {tbl} (無 parquet 檔)")
                continue

            existing = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            if existing > 0:
                print(f"  [skip] {tbl} 已有 {existing:,} 筆 (為避免覆寫,請手動 DELETE 再跑)")
                continue

            con.execute(
                f"INSERT INTO {tbl} SELECT * FROM read_parquet('{f.as_posix()}')"
            )
            rows = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            print(f"  [OK]   {tbl:28s} {rows:>10,} rows")
            total_rows += rows

    print(f"\n=== 完成: 匯入 {total_rows:,} rows ===")
    print("下一步: streamlit run src/stock_llm/app/main.py")


if __name__ == "__main__":
    main()

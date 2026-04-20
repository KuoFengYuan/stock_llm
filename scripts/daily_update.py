"""一鍵每日更新 — 股價、法人、技術指標、新聞、打分、snapshot。

用法:
    python scripts/daily_update.py                   # 預設全跑
    python scripts/daily_update.py --days 3          # 指定回抓天數
    python scripts/daily_update.py --no-news         # 跳過新聞
    python scripts/daily_update.py --no-llm          # 跳過 LLM 打分
    python scripts/daily_update.py --snapshot        # 跑完 export parquet
    python scripts/daily_update.py --push            # 跑完 git add + commit + push (先 --snapshot)
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable  # 用同一個 Python (conda env)

logger = logging.getLogger("daily")


def run(cmd: list[str], label: str) -> tuple[bool, float]:
    """執行 subprocess,回傳 (是否成功, 耗時秒)。"""
    print(f"\n{'=' * 60}\n▶ {label}\n   {' '.join(cmd)}\n{'=' * 60}")
    t0 = time.time()
    try:
        res = subprocess.run(cmd, cwd=ROOT, check=False)
        ok = res.returncode == 0
    except Exception as exc:
        print(f"!! {label} 爆炸: {exc}")
        ok = False
    elapsed = time.time() - t0
    status = "OK" if ok else "FAIL"
    print(f"← [{status}] {label} ({elapsed:.1f}s)")
    return ok, elapsed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=7, help="回抓多少日曆天 (股價/法人,預設 7)")
    p.add_argument("--news-pages", type=int, default=5, help="Anue 抓幾頁 (每頁 30 則)")
    p.add_argument("--news-limit", type=int, default=300, help="LLM 打分上限")
    p.add_argument("--no-news", action="store_true", help="跳過新聞抓取與打分")
    p.add_argument("--no-llm", action="store_true", help="只抓新聞不打分")
    p.add_argument("--snapshot", action="store_true", help="跑完 export parquet")
    p.add_argument("--push", action="store_true", help="跑完 git commit + push (隱含 --snapshot)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.push:
        args.snapshot = True

    t_start = datetime.now()
    print(f"\n🚀 daily_update 開始  {t_start:%Y-%m-%d %H:%M:%S}\n")

    results: list[tuple[str, bool, float]] = []

    steps = [
        ("股價 (yfinance)",   [PYTHON, "scripts/fetch_prices.py", "--days", str(args.days)]),
        ("三大法人 (TWSE T86)", [PYTHON, "scripts/fetch_institutional.py", "--days", str(args.days)]),
        ("技術指標 (本機算)",   [PYTHON, "scripts/compute_indicators.py"]),
    ]

    if not args.no_news:
        steps.append((
            "新聞抓取 (Anue)",
            [PYTHON, "scripts/fetch_news.py", "--pages", str(args.news_pages), "--max-age-days", "7"],
        ))
        if not args.no_llm:
            steps.append((
                "新聞情緒打分 (Flash Lite)",
                [PYTHON, "scripts/score_news.py", "--limit", str(args.news_limit)],
            ))

    if args.snapshot:
        steps.append(("Snapshot (parquet)", [PYTHON, "scripts/export_duckdb_to_parquet.py"]))

    for label, cmd in steps:
        ok, elapsed = run(cmd, label)
        results.append((label, ok, elapsed))

    if args.push:
        today = datetime.now().strftime("%Y-%m-%d")
        run(["git", "add", "data/snapshot/"], "git add snapshot")
        # commit 允許失敗 (沒變化就 skip)
        run(
            ["git", "commit", "-m", f"snapshot: {today}"],
            "git commit snapshot",
        )
        ok_push, elapsed = run(["git", "push", "origin", "main"], "git push")
        results.append(("git push", ok_push, elapsed))

    # summary
    total = sum(r[2] for r in results)
    fail = [r for r in results if not r[1]]
    t_end = datetime.now()

    print(f"\n{'=' * 60}\n📊 摘要  {t_end:%H:%M:%S}  總耗時 {total:.0f} 秒")
    print(f"{'=' * 60}")
    for label, ok, elapsed in results:
        mark = "✅" if ok else "❌"
        print(f"  {mark}  {label:<32s} {elapsed:6.1f}s")

    if fail:
        print(f"\n⚠️  {len(fail)} 步失敗: {', '.join(r[0] for r in fail)}")
        sys.exit(1)
    print("\n✨ 全部成功")


if __name__ == "__main__":
    main()

"""Fetch Anue 台股新聞到 DB (尚未打分)。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.news_anue import fetch_anue_news
from stock_llm.data.store import connect, upsert_news


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=5, help="Anue 翻幾頁 (每頁 30 則,預設 5)")
    p.add_argument("--max-age-days", type=int, default=7, help="只抓 N 天內的新聞")
    p.add_argument("--sleep", type=float, default=1.5)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print(f">> 抓取 Anue 新聞 (pages={args.pages}, 最近 {args.max_age_days} 天)")
    df = fetch_anue_news(
        pages=args.pages,
        sleep=args.sleep,
        max_age_days=args.max_age_days,
    )
    if df.empty:
        print("[WARN] 無新聞。")
        return

    print(f">> 得到 {df['url'].nunique()} 則新聞 / {len(df)} 筆 (news × stock)")
    total = upsert_news(df)
    print(f">> news 表目前 {total:,} 筆")

    with connect() as con:
        r = con.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN sentiment_score IS NULL THEN 1 ELSE 0 END) pending,
                   MIN(published_at) earliest, MAX(published_at) latest
            FROM news
            """
        ).fetchone()
        print(f"=== DB stats ===")
        print(f"  總共: {r[0]:,}  待打分: {r[1]:,}  期間: {r[2]} → {r[3]}")

    print("\n[OK] 完成。下一步: python scripts/score_news.py")


if __name__ == "__main__":
    main()

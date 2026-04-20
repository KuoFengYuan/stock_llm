"""Fetch 台股新聞到 DB (尚未打分)。支援 Anue + Google News RSS。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.news_anue import fetch_anue_news
from stock_llm.data.news_google import fetch_google_news
from stock_llm.data.store import connect, upsert_news
from stock_llm.data.universe import top_by_turnover


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--sources",
        default="anue,google",
        help="來源 (逗號分隔): anue,google (預設全跑)",
    )
    p.add_argument("--pages", type=int, default=5, help="Anue 翻幾頁 (每頁 30 則)")
    p.add_argument("--max-age-days", type=int, default=7, help="只抓 N 天內的新聞")
    p.add_argument("--sleep", type=float, default=1.5, help="Anue 每頁間隔")
    p.add_argument(
        "--google-top-n", type=int, default=500,
        help="Google News 對 top-N 成交值股票查詢 (0 = 跳過)",
    )
    p.add_argument("--google-sleep", type=float, default=0.5, help="Google RSS 每檔間隔")
    p.add_argument("--google-max-per-stock", type=int, default=20)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    sources = {s.strip().lower() for s in args.sources.split(",") if s.strip()}
    frames: list[pd.DataFrame] = []

    if "anue" in sources:
        print(f">> Anue (pages={args.pages}, 最近 {args.max_age_days} 天)")
        df = fetch_anue_news(
            pages=args.pages, sleep=args.sleep, max_age_days=args.max_age_days,
        )
        print(f"   Anue: {df['url'].nunique() if not df.empty else 0} 則 / {len(df)} 筆 (news × stock)")
        if not df.empty:
            frames.append(df)

    if "google" in sources and args.google_top_n > 0:
        codes = top_by_turnover(n=args.google_top_n)
        print(f">> Google News RSS (top {len(codes)} 檔, 每檔最多 {args.google_max_per_stock} 則)")
        df = fetch_google_news(
            codes,
            sleep=args.google_sleep,
            max_age_days=args.max_age_days,
            max_per_stock=args.google_max_per_stock,
        )
        print(f"   Google: {df['url'].nunique() if not df.empty else 0} 則 / {len(df)} 筆")
        if not df.empty:
            frames.append(df)

    if not frames:
        print("[WARN] 無新聞。")
        return

    all_df = pd.concat(frames, ignore_index=True)
    # (url, stock_code) 去重;Anue 優先 (先 concat 在前)
    all_df = all_df.drop_duplicates(subset=["url", "stock_code"], keep="first")
    print(f">> 合併後 {all_df['url'].nunique()} 則 / {len(all_df)} 筆")

    total = upsert_news(all_df)
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
        by_src = con.execute(
            "SELECT source, COUNT(*) FROM news GROUP BY source ORDER BY 2 DESC"
        ).fetchall()
        print("=== DB stats ===")
        print(f"  總共: {r[0]:,}  待打分: {r[1]:,}  期間: {r[2]} → {r[3]}")
        print(f"  來源: {', '.join(f'{s}={c}' for s, c in by_src)}")

    print("\n[OK] 完成。下一步: python scripts/score_news.py")


if __name__ == "__main__":
    main()

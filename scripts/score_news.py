"""對 news 表中尚未打分的新聞用 LLM 打 sentiment score。"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.data.store import connect, update_news_sentiment
from stock_llm.llm.gemini import MODEL_FLASH_LITE
from stock_llm.llm.news_scorer import BATCH_SIZE, score_news_batch


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--model", default=MODEL_FLASH_LITE, help="LLM 模型 (預設 Flash Lite)")
    p.add_argument("--limit", type=int, default=200, help="最多處理幾筆 (保護配額,預設 200)")
    p.add_argument("--sleep", type=float, default=1.0, help="批次間隔秒數")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    with connect() as con:
        pending = con.execute(
            """
            SELECT url, stock_code, title, content
            FROM news WHERE sentiment_score IS NULL
            ORDER BY published_at DESC LIMIT ?
            """,
            [args.limit],
        ).fetchdf()

    if pending.empty:
        print(">> 沒有待打分的新聞。")
        return

    rows = pending.to_dict(orient="records")
    print(f">> 待打分 {len(rows)} 筆,model={args.model},batch={BATCH_SIZE}")

    ok = 0
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        print(f"  batch {i // BATCH_SIZE + 1}/{(len(rows) + BATCH_SIZE - 1) // BATCH_SIZE} ({len(batch)} 筆)...", end=" ", flush=True)
        scored = score_news_batch(batch, model=args.model)
        batch_ok = 0
        for s in scored:
            if s.get("score") is None:
                continue
            update_news_sentiment(
                url=s["url"], stock_code=s["stock_code"],
                score=s["score"], impact=s["impact"],
                summary=s["summary"], model=args.model,
            )
            ok += 1
            batch_ok += 1
        print(f"{batch_ok}/{len(batch)} OK")
        if i + BATCH_SIZE < len(rows):
            import time
            time.sleep(args.sleep)

    print(f"\n[OK] 完成 {ok}/{len(rows)} 筆。")
    with connect() as con:
        r = con.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN sentiment_score IS NOT NULL THEN 1 ELSE 0 END) scored
            FROM news
            """
        ).fetchone()
        print(f"  DB: {r[1]:,}/{r[0]:,} 已打分")


if __name__ == "__main__":
    main()

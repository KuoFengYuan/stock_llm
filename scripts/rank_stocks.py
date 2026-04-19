"""Build features + scores + print Top-N short-term and long-term picks."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd

from stock_llm.data.store import connect
from stock_llm.data.universe import top_by_turnover
from stock_llm.features.snapshot import build_feature_snapshot
from stock_llm.models.scoring import score_snapshot


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-n", type=int, default=500, help="Universe size (by turnover)")
    parser.add_argument("--show", type=int, default=10, help="How many to print per track")
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--min-volume", type=int, default=500_000, help="Filter: min avg 5d volume")
    return parser.parse_args()


def _key_signals(row) -> str:
    tags = []
    if row.get("ma_bullish"): tags.append("MA多頭")
    if row.get("macd_golden_cross"): tags.append("MACD黃金")
    if row.get("kd_golden_cross"): tags.append("KD黃金")
    consec = row.get("foreign_consecutive_buy_days") or 0
    if consec >= 3: tags.append(f"外資連買{int(consec)}")
    rsi = row.get("rsi14")
    if rsi and rsi < 30: tags.append(f"RSI{rsi:.0f}超賣")
    if rsi and rsi > 70: tags.append(f"RSI{rsi:.0f}超買")
    return " / ".join(tags) if tags else "-"


def main() -> None:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.as_of:
        from datetime import date
        as_of = date.fromisoformat(args.as_of)
    else:
        with connect() as con:
            as_of = con.execute("SELECT MAX(trade_date) FROM prices_daily").fetchone()[0]

    print(f">> Ranking as of {as_of}")
    codes = top_by_turnover(args.top_n)
    print(f">> Universe: {len(codes)} stocks")

    features = build_feature_snapshot(as_of, codes)
    scored = score_snapshot(features)

    if args.min_volume:
        before = len(scored)
        scored = scored[scored["avg_volume_5d"].fillna(0) >= args.min_volume]
        print(f">> Liquidity filter: {before} -> {len(scored)} stocks")

    with connect() as con:
        meta = con.execute(
            f"SELECT stock_code, name, short_name, industry FROM stocks "
            f"WHERE stock_code IN ({','.join('?' for _ in scored['stock_code'])})",
            scored["stock_code"].tolist(),
        ).fetchdf()
    merged = scored.merge(meta, on="stock_code", how="left")

    print(f"\n{'=' * 80}")
    print(f"  🚀 Top {args.show} 短線波段 (持有 5-20 日)")
    print(f"{'=' * 80}")
    cols = ["rank_short", "stock_code", "short_name", "industry", "close",
            "short_score", "tech_score", "chip_score"]
    top_short = merged.sort_values("rank_short").head(args.show)
    rows = []
    for _, r in top_short.iterrows():
        rows.append({
            "排名": int(r.rank_short),
            "代號": r.stock_code,
            "名稱": (r.short_name or "-")[:8],
            "產業": (r.industry or "-")[:8],
            "收盤": f"{r.close:.2f}",
            "短線分": f"{r.short_score:.1f}",
            "技術": f"{r.tech_score:.0f}",
            "籌碼": f"{r.chip_score:.0f}",
            "訊號": _key_signals(r),
        })
    print(pd.DataFrame(rows).to_string(index=False))

    print(f"\n{'=' * 80}")
    print(f"  💎 Top {args.show} 中長線價值 (持有 3-12 月,限有基本面)")
    print(f"{'=' * 80}")
    long_eligible = merged.dropna(subset=["long_score"])
    if long_eligible.empty:
        print("(無足夠基本面資料)")
    else:
        top_long = long_eligible.sort_values("rank_long").head(args.show)
        rows = []
        for _, r in top_long.iterrows():
            rows.append({
                "排名": int(r.rank_long),
                "代號": r.stock_code,
                "名稱": (r.short_name or "-")[:8],
                "產業": (r.industry or "-")[:8],
                "收盤": f"{r.close:.2f}",
                "長線分": f"{r.long_score:.1f}",
                "基本": f"{r.fund_score:.0f}",
                "營收YoY": f"{(r.revenue_yoy_latest or 0)*100:.1f}%",
                "毛利率": f"{(r.gross_margin_latest or 0)*100:.1f}%",
            })
        print(pd.DataFrame(rows).to_string(index=False))

    print("\n[OK] Ranking complete. (Sentiment feature will be added in Phase 3.)")


if __name__ == "__main__":
    main()

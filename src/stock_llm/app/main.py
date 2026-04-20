from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from stock_llm.data.store import connect
from stock_llm.data.universe import top_by_turnover
from stock_llm.features.snapshot import build_feature_snapshot
from stock_llm.llm.recommendation import generate_recommendation
from stock_llm.llm.gemini import (
    DEFAULT_BATCH_MODEL,
    MODEL_FLASH,
    MODEL_FLASH_LITE,
    MODEL_PRO,
)

MODEL_OPTIONS = {
    "Flash Lite ⭐ 快 · 穩定": MODEL_FLASH_LITE,
    "Flash (更聰明 · 慢)":    MODEL_FLASH,
    "Pro (最強 · 日限 100)":  MODEL_PRO,
}
MODEL_LABEL_BY_ID = {v: k for k, v in MODEL_OPTIONS.items()}
from stock_llm.models.scoring import score_snapshot
from stock_llm.models.scoring_v2 import score_snapshot_v2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

st.set_page_config(page_title="台股推薦系統", page_icon="📈", layout="wide", initial_sidebar_state="expanded")

st.markdown(
    """
    <style>
      :root {
        --c-accent: #00D4FF;
        --c-bg: #0E1117;
        --c-surface: #161B22;
        --c-surface-hover: #1C232E;
        --c-text: #E8F0FF;
        --c-dim: #8A9BC1;
        --c-border: rgba(255,255,255,0.06);
        --c-border-hover: rgba(255,255,255,0.12);
      }

      /* layout - generous padding, narrower column like Claude */
      .block-container {
        padding: 2rem 3rem 4rem 3rem !important;
        max-width: 1100px !important;
      }

      /* typography */
      h1, h2, h3, h4, .page-title {
        font-family: -apple-system, "Inter", "PingFang TC", "Microsoft JhengHei", sans-serif !important;
        letter-spacing: -0.01em;
      }
      .page-title {
        font-size: 1.6rem;
        font-weight: 600;
        color: var(--c-text);
        padding: 0.5rem 0 1.5rem 0;
        line-height: 2;
        overflow: visible;
        display: block;
      }
      h2 { font-size: 1.15rem !important; font-weight: 600 !important; color: var(--c-text) !important; }
      h3 { font-size: 1rem !important; font-weight: 500 !important; color: var(--c-text) !important; }

      /* metrics - flat, minimal */
      [data-testid="stMetric"] {
        background: transparent;
        border: 1px solid var(--c-border);
        border-radius: 12px;
        padding: 0.9rem 1.1rem !important;
      }
      [data-testid="stMetricValue"] {
        font-size: 1.25rem;
        font-weight: 600 !important;
        color: var(--c-text) !important;
      }
      [data-testid="stMetricLabel"] {
        font-size: 0.72rem;
        color: var(--c-dim) !important;
        font-weight: 400;
      }

      /* expanders - clean Claude-like cards */
      [data-testid="stExpander"] {
        border: 1px solid var(--c-border) !important;
        border-radius: 12px;
        margin-bottom: 0.5rem;
        background: transparent !important;
        transition: border-color 0.12s ease, background 0.12s ease;
        overflow: hidden;
      }
      [data-testid="stExpander"]:hover {
        border-color: var(--c-border-hover) !important;
        background: var(--c-surface) !important;
      }
      [data-testid="stExpander"] details summary {
        padding: 0.85rem 1.2rem;
        color: var(--c-text) !important;
        font-weight: 400;
      }
      [data-testid="stExpander"] details summary strong {
        color: var(--c-text);
        font-weight: 600;
      }

      /* buttons - rounded pill style */
      .stButton > button {
        border-radius: 10px !important;
        font-weight: 500 !important;
        transition: all 0.12s ease;
      }
      .stButton > button[kind="primary"] {
        background: var(--c-accent) !important;
        border: none !important;
        color: #0E1117 !important;
        font-weight: 600 !important;
      }
      .stButton > button[kind="primary"]:hover { filter: brightness(1.08); }
      .stButton > button[kind="secondary"] {
        background: transparent !important;
        border: 1px solid var(--c-border) !important;
        color: var(--c-text) !important;
      }
      .stButton > button[kind="secondary"]:hover {
        border-color: var(--c-border-hover) !important;
        background: var(--c-surface) !important;
      }

      /* tabs - minimal underline */
      [data-baseweb="tab-list"] {
        border-bottom: 1px solid var(--c-border) !important;
        gap: 0.5rem;
      }
      [data-baseweb="tab-list"] button {
        color: var(--c-dim) !important;
        font-weight: 500 !important;
      }
      [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: var(--c-text) !important;
        border-bottom: 2px solid var(--c-accent) !important;
      }

      /* charts */
      .stPlotlyChart {
        margin: 0.75rem 0;
        border: 1px solid var(--c-border);
        border-radius: 12px;
        background: var(--c-bg);
        padding: 8px;
      }

      /* sidebar */
      [data-testid="stSidebar"] {
        border-right: 1px solid var(--c-border);
        background: #0B0E13 !important;
      }
      [data-testid="stSidebar"] .block-container { padding: 1.5rem 1rem !important; }

      /* caption */
      [data-testid="stCaptionContainer"] { color: var(--c-dim) !important; }

      /* signal tags */
      .signal-tags { font-size: 0.85rem; padding: 0.5rem 0; color: var(--c-dim); }

      /* institutional row */
      .inst-row { display: flex; gap: 0.6rem; flex-wrap: wrap; padding: 0.5rem 0; }
      .inst-cell {
        flex: 1; min-width: 110px;
        padding: 0.7rem 0.9rem;
        background: transparent;
        border: 1px solid var(--c-border);
        border-radius: 10px;
      }
      .inst-label {
        color: var(--c-dim); font-size: 0.68rem;
        font-weight: 500;
        margin-bottom: 4px;
      }
      .inst-value {
        font-weight: 600; font-size: 1.05rem;
      }
      .pos { color: #FF7B7B; }
      .neg { color: #4ADE80; }

      /* progress bar */
      [data-testid="stProgress"] > div > div > div {
        background: var(--c-accent) !important;
      }

      /* mobile */
      @media (max-width: 768px) {
        .block-container { padding: 1rem 1rem 2rem 1rem !important; }
        .page-title { font-size: 1.3rem; }
        [data-testid="stMetricValue"] { font-size: 1rem; }
        [data-testid="stExpander"] details summary { font-size: 0.88rem; padding: 0.7rem 0.9rem; }
        .inst-cell { min-width: 90px; padding: 0.5rem 0.7rem; }
        .inst-value { font-size: 0.95rem; }
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=3600, show_spinner=False)
def _latest_date() -> date | None:
    with connect() as con:
        row = con.execute("SELECT MAX(trade_date) FROM prices_daily").fetchone()
    return row[0] if row and row[0] else None


@st.cache_data(ttl=3600, show_spinner=False)
def _data_stats() -> dict:
    with connect() as con:
        stats = {}
        for tbl, label in [
            ("stocks", "股票清單"),
            ("prices_daily", "日 K"),
            ("institutional_daily", "三大法人"),
            ("indicators_daily", "技術指標"),
            ("monthly_revenue", "月營收"),
            ("financials_quarterly", "季財報"),
        ]:
            cnt = con.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()[0]
            stocks = con.execute(f"SELECT COUNT(DISTINCT stock_code) FROM {tbl}").fetchone()[0]
            stats[label] = f"{cnt:,} 筆 / {stocks} 檔"
    return stats


@st.cache_data(ttl=3600, show_spinner="計算中...")
def _build_ranking(top_n: int, as_of: date, min_volume: int, ai_boost: float, version: str) -> pd.DataFrame:
    codes = top_by_turnover(top_n)
    features = build_feature_snapshot(as_of, codes)
    if version == "v2":
        scored = score_snapshot_v2(features, ai_boost=ai_boost)
    else:
        scored = score_snapshot(features, ai_boost=ai_boost)
    scored = scored[scored["avg_volume_5d"].fillna(0) >= min_volume]
    with connect() as con:
        meta = con.execute(
            f"SELECT stock_code, name, short_name, industry FROM stocks "
            f"WHERE stock_code IN ({','.join('?' for _ in scored['stock_code'])})",
            scored["stock_code"].tolist(),
        ).fetchdf()
    return scored.merge(meta, on="stock_code", how="left")


@st.cache_data(ttl=3600, show_spinner=False)
def _load_recent_news(stock_code: str, days: int, data_date: str) -> pd.DataFrame:
    with connect() as con:
        return con.execute(
            """
            SELECT published_at, title, sentiment_score, sentiment_impact, sentiment_summary, url
            FROM news
            WHERE stock_code = ?
              AND published_at >= CURRENT_TIMESTAMP - CAST(? AS INTEGER) * INTERVAL 1 DAY
            ORDER BY published_at DESC
            """,
            [stock_code, days],
        ).fetchdf()


@st.cache_data(ttl=3600, show_spinner=False)
def _load_charts_data(stock_code: str, trading_days: int, data_date: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """data_date 放在 key 裡,DB 更新後自動失效。
    若 institutional 起始日晚於 price 起始日,把 price/indicator 也截到同一天起,
    避免 K 線跟法人圖左右不對齊。
    """
    with connect() as con:
        prices = con.execute(
            """
            SELECT * FROM (
                SELECT trade_date, open, high, low, close, volume
                FROM prices_daily WHERE stock_code = ?
                ORDER BY trade_date DESC LIMIT ?
            ) ORDER BY trade_date
            """,
            [stock_code, trading_days],
        ).fetchdf()

        if prices.empty:
            return prices, pd.DataFrame(), pd.DataFrame()

        start_date = prices["trade_date"].min()
        inst = con.execute(
            """
            SELECT trade_date, foreign_net, invest_net, dealer_net
            FROM institutional_daily
            WHERE stock_code = ? AND trade_date >= ?
            ORDER BY trade_date
            """,
            [stock_code, start_date],
        ).fetchdf()

        if not inst.empty:
            inst_start = inst["trade_date"].min()
            if inst_start > start_date:
                prices = prices[prices["trade_date"] >= inst_start].reset_index(drop=True)
                start_date = inst_start

        ind = con.execute(
            """
            SELECT trade_date, ma5, ma20, ma60
            FROM indicators_daily
            WHERE stock_code = ? AND trade_date >= ?
            ORDER BY trade_date
            """,
            [stock_code, start_date],
        ).fetchdf()
    return prices, inst, ind


def _make_chart(prices: pd.DataFrame, inst: pd.DataFrame, ind: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=[0.55, 0.18, 0.27],
    )

    fig.add_trace(
        go.Candlestick(
            x=prices["trade_date"],
            open=prices["open"], high=prices["high"],
            low=prices["low"], close=prices["close"],
            increasing_line_color="#FF5C5C", decreasing_line_color="#2ECC71",
            increasing_fillcolor="#FF5C5C", decreasing_fillcolor="#2ECC71",
            name="K 線",
        ),
        row=1, col=1,
    )

    if not ind.empty:
        for col, color, name in [
            ("ma5", "#3498DB", "MA5"),
            ("ma20", "#F39C12", "MA20"),
            ("ma60", "#9B59B6", "MA60"),
        ]:
            fig.add_trace(
                go.Scatter(
                    x=ind["trade_date"], y=ind[col],
                    mode="lines", line=dict(color=color, width=1),
                    name=name,
                ),
                row=1, col=1,
            )

    vol_colors = [
        "#FF5C5C" if c >= o else "#2ECC71"
        for o, c in zip(prices["open"], prices["close"])
    ]
    fig.add_trace(
        go.Bar(
            x=prices["trade_date"], y=prices["volume"] / 1000,
            marker_color=vol_colors, name="成交量 (張)",
            showlegend=False,
        ),
        row=2, col=1,
    )

    if not inst.empty:
        for col, color, name in [
            ("foreign_net", "#FF5C5C", "外資"),
            ("invest_net", "#3498DB", "投信"),
            ("dealer_net", "#F39C12", "自營"),
        ]:
            fig.add_trace(
                go.Bar(
                    x=inst["trade_date"],
                    y=inst[col] / 1000,
                    marker_color=color, name=name, opacity=0.85,
                ),
                row=3, col=1,
            )

    fig.update_layout(
        height=300,
        xaxis_rangeslider_visible=False,
        barmode="relative",
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom", y=1.02,
            xanchor="left", x=0,
            font=dict(size=10, color="#8A9BC1"),
            bgcolor="rgba(0,0,0,0)",
        ),
        margin=dict(l=40, r=80, t=40, b=20),
        plot_bgcolor="#0E1117",
        paper_bgcolor="#0E1117",
        font=dict(size=10, color="#E8F0FF"),
    )

    if not prices.empty:
        all_days = pd.date_range(
            start=prices["trade_date"].min(),
            end=prices["trade_date"].max(),
            freq="D",
        )
        trade_set = set(pd.to_datetime(prices["trade_date"]))
        non_trading = [d for d in all_days if d not in trade_set]
        fig.update_xaxes(rangebreaks=[dict(values=non_trading)])

    fig.update_xaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)", showline=True, linecolor="rgba(255,255,255,0.15)", color="#8A9BC1")
    fig.update_yaxes(showgrid=True, gridcolor="rgba(255,255,255,0.05)", showline=True, linecolor="rgba(255,255,255,0.15)", color="#8A9BC1")
    fig.update_yaxes(title_text="價格", row=1, col=1, title_font=dict(size=10, color="#8A9BC1"))
    fig.update_yaxes(title_text="量(張)", row=2, col=1, title_font=dict(size=10, color="#8A9BC1"))
    fig.update_yaxes(title_text="法人(張)", row=3, col=1, title_font=dict(size=10, color="#8A9BC1"))
    return fig


@st.cache_data(ttl=86400, show_spinner=False)
def _get_recommendation(
    stock_code: str, name: str, industry: str, track: str,
    features_tuple, tags_tuple, model: str,
):
    features = dict(features_tuple)
    tags = list(tags_tuple) if tags_tuple else []
    rec = generate_recommendation(
        stock_code, name or "", industry or "", features,
        track=track, tags=tags, model=model,
    )
    return rec.as_dict()


def _features_to_tuple(row: pd.Series) -> tuple:
    keys = [
        "close", "short_score", "long_score", "tech_score", "chip_score", "fund_score",
        "ma5", "ma20", "ma60",
        "ma_bullish", "ma_short_bullish", "price_above_all_ma",
        "macd_hist", "macd_golden_cross",
        "kd_golden_cross", "k9", "d9",
        "rsi14", "bb_position", "volume_ratio",
        "consecutive_up_days", "consecutive_down_days",
        "foreign_consecutive_buy_days", "foreign_consecutive_sell_days",
        "invest_consecutive_buy_days", "invest_consecutive_sell_days",
        "foreign_net_5d_cum", "foreign_net_20d_cum",
        "invest_net_5d_cum", "dealer_net_5d_cum",
        "inst_intensity",
        "has_fundamental_data",
        "revenue_yoy_latest", "revenue_yoy_3m_avg", "revenue_mom_latest",
        "revenue_months_positive_yoy_6m",
        "gross_margin_latest", "gross_margin_trend",
        "net_margin_latest", "eps_latest",
    ]
    items = []
    for k in keys:
        v = row.get(k)
        if isinstance(v, bool):
            items.append((k, bool(v)))
        elif v is None or pd.isna(v):
            items.append((k, None))
        else:
            items.append((k, float(v)))
    return tuple(items)


def _rank_table(df: pd.DataFrame, rank_col: str, score_col: str, show: int) -> pd.DataFrame:
    sub = df.dropna(subset=[score_col]).sort_values(rank_col).head(show).copy()
    out = pd.DataFrame({
        "排名": sub[rank_col].astype(int),
        "代號": sub["stock_code"],
        "名稱": sub["short_name"].fillna("-"),
        "AI": sub["is_ai_concept"].map(lambda v: "🤖" if v else ""),
        "產業": sub["industry"].fillna("-"),
        "收盤": sub["close"].map(lambda v: f"{v:.2f}" if pd.notna(v) else "-"),
        "綜合分": sub[score_col].map(lambda v: f"{v:.1f}" if pd.notna(v) else "-"),
        "技術": sub["tech_score"].map(lambda v: f"{v:.0f}" if pd.notna(v) else "-"),
        "籌碼": sub["chip_score"].map(lambda v: f"{v:.0f}" if pd.notna(v) else "-"),
    })
    if "fund_score" in sub.columns:
        out["基本面"] = sub["fund_score"].map(lambda v: f"{v:.0f}" if pd.notna(v) else "-")
    return out


def _inst_html(label: str, value: float, suffix: str = "張", small: str = "") -> str:
    cls = "pos" if value > 0 else ("neg" if value < 0 else "")
    sign = "+" if value > 0 else ""
    val = f"{sign}{value:,.0f} {suffix}"
    extra = f"<div style='font-size:0.7rem;color:#888'>{small}</div>" if small else ""
    return (
        f"<div class='inst-cell'><div class='inst-label'>{label}</div>"
        f"<div class='inst-value {cls}'>{val}</div>{extra}</div>"
    )


DAY_PRESETS = {"30 天": 30, "60 天": 60, "90 天": 90, "180 天": 180, "365 天": 365, "2 年": 730}


def _render_stock_card(row: pd.Series, track: str, idx: int = 0, llm_model: str = DEFAULT_BATCH_MODEL) -> None:
    code = row["stock_code"]
    name = row.get("short_name") or row.get("name") or "-"
    industry = row.get("industry") or "-"
    score = row.get("short_score") if track == "short" else row.get("long_score")

    tags = row.get("tags") or []
    rank_col = "rank_short" if track == "short" else "rank_long"
    rank = int(row.get(rank_col, 0))
    ai_badge = " 🤖" if tags else ""
    label = f"**#{rank:>2}　{name}**　{code}　﹒　{industry}　﹒　**{score:.1f}**{ai_badge}"

    with st.expander(label):
        if tags:
            chips = "".join(
                f"<span style='display:inline-block;padding:2px 10px;margin:0 4px 4px 0;"
                f"background:linear-gradient(135deg,rgba(0,212,255,0.18),rgba(176,123,255,0.18));"
                f"border:1px solid rgba(0,212,255,0.45);border-radius:10px;"
                f"font-size:0.72rem;color:#00D4FF;font-weight:600;letter-spacing:0.02em'>{t}</span>"
                for t in tags
            )
            st.markdown(f"<div style='margin-bottom:0.4rem'>{chips}</div>", unsafe_allow_html=True)
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("收盤", f"{row['close']:.2f}")
        c2.metric("技術", f"{row.get('tech_score', 0):.0f}")
        c3.metric("籌碼", f"{row.get('chip_score', 0):.0f}")
        fund = row.get("fund_score")
        c4.metric("基本面", "—" if pd.isna(fund) else f"{fund:.0f}")
        sent = row.get("news_sentiment_score")
        news_n = int(row.get("news_count_7d") or 0)
        if sent is None or pd.isna(sent) or news_n == 0:
            c5.metric("情緒", "—", help="近 5 天無新聞")
        else:
            delta = float(sent) - 50
            c5.metric(
                "情緒", f"{float(sent):.0f}",
                delta=f"{delta:+.0f}" if abs(delta) >= 1 else None,
                help=f"近 5 天 {news_n} 則新聞 (基準 50)",
            )

        signals = []
        if row.get("ma_bullish"):
            signals.append("📈 完全多頭")
        elif row.get("ma_short_bullish") and row.get("price_above_all_ma"):
            signals.append("📈 短多 (站上均線)")
        elif row.get("price_above_all_ma"):
            signals.append("✅ 站上均線")
        if row.get("macd_golden_cross"): signals.append("✨ MACD")
        if row.get("kd_golden_cross"): signals.append("✨ KD")
        consec = row.get("foreign_consecutive_buy_days") or 0
        if consec >= 3: signals.append(f"💰 外資連買 {int(consec)}")
        if row.get("rsi14") and row["rsi14"] > 70: signals.append(f"⚠️ RSI{row['rsi14']:.0f}")
        if row.get("rsi14") and row["rsi14"] < 30: signals.append(f"🔍 RSI{row['rsi14']:.0f}")
        if signals:
            st.markdown(f"<div class='signal-tags'>{' · '.join(signals)}</div>", unsafe_allow_html=True)

        days_key = f"days_{track}_{idx}_{code}"
        day_label = st.radio(
            "K 線天數",
            options=list(DAY_PRESETS.keys()),
            index=2,  # default 90 天
            horizontal=True,
            key=days_key,
            label_visibility="collapsed",
        )
        chart_days = DAY_PRESETS[day_label]

        prices, inst, ind = _load_charts_data(code, chart_days, str(latest))
        if not prices.empty:
            actual = len(prices)
            truncated = actual < chart_days - 2  # tolerance for holidays
            caption = f"📊 {name} ({code}) · 近 {actual} 個交易日"
            if truncated:
                caption += f"  ⚠️ 選了 {chart_days} 天,但法人資料只有 {actual} 天 — 需要 backfill:`fetch_institutional.py --days {max(chart_days + 40, 365)}`"
            st.caption(caption)
            fig = _make_chart(prices, inst, ind)
            st.plotly_chart(fig, width="stretch", key=f"chart_{track}_{idx}_{code}")

        news_df = _load_recent_news(code, 7, str(latest))
        if not news_df.empty:
            with st.expander(f"📰 近期新聞 ({len(news_df)} 則)"):
                for _, n in news_df.iterrows():
                    s = n.get("sentiment_score")
                    imp = n.get("sentiment_impact") or ""
                    if s is None or pd.isna(s):
                        badge = "⚪ 未打分"
                        color = "#8A9BC1"
                    elif s > 0.2:
                        badge = f"📈 +{float(s):.1f} {imp}"
                        color = "#4ADE80"
                    elif s < -0.2:
                        badge = f"📉 {float(s):.1f} {imp}"
                        color = "#FF7B7B"
                    else:
                        badge = f"➖ {float(s):+.1f} {imp}"
                        color = "#8A9BC1"
                    dt = pd.to_datetime(n["published_at"]).strftime("%m/%d %H:%M")
                    st.markdown(
                        f"<div style='padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.04)'>"
                        f"<span style='color:{color};font-weight:600;font-size:0.8rem'>{badge}</span>"
                        f"  <span style='color:#8A9BC1;font-size:0.75rem'>{dt}</span><br>"
                        f"<a href='{n['url']}' target='_blank' style='color:#E8F0FF;text-decoration:none'>{n['title']}</a>"
                        + (f"<br><span style='color:#8A9BC1;font-size:0.75rem;font-style:italic'>{n['sentiment_summary']}</span>" if n.get('sentiment_summary') else "")
                        + "</div>",
                        unsafe_allow_html=True,
                    )

        f5 = (row.get("foreign_net_5d_cum") or 0) / 1000
        f20 = (row.get("foreign_net_20d_cum") or 0) / 1000
        i5 = (row.get("invest_net_5d_cum") or 0) / 1000
        d5 = (row.get("dealer_net_5d_cum") or 0) / 1000
        st.markdown(
            "<div class='inst-row'>"
            + _inst_html("外資 5 日", f5, small=f"20 日 {f20:+,.0f}")
            + _inst_html("投信 5 日", i5)
            + _inst_html("自營 5 日", d5)
            + "</div>",
            unsafe_allow_html=True,
        )

        btn_key = f"llm_{track}_{idx}_{code}"
        if st.button("🤖 LLM 深入分析", key=btn_key, type="primary"):
            import time as _time
            t0 = _time.time()
            stock_label = f"{name} ({code})" if name else code
            status = st.status(f"LLM 分析中 · {stock_label}...", expanded=False)
            try:
                label_short = MODEL_LABEL_BY_ID.get(llm_model, llm_model)
                status.update(label=f"呼叫 {label_short} 分析 {stock_label}...", state="running")
                rec = _get_recommendation(
                    code, name, industry, track,
                    _features_to_tuple(row),
                    tuple(tags),
                    llm_model,
                )
                elapsed = _time.time() - t0
                fb = rec.get("fallback_used")
                used = rec.get("model_used", "?")
                status.update(
                    label=f"完成 · {stock_label} · {used} · {elapsed:.1f}s" + (" (fallback)" if fb else ""),
                    state="complete",
                )
                att = rec.get("attempts") or []
                if len(att) > 1 or (att and att[0].get("status") != "success"):
                    with status:
                        st.caption("**嘗試歷程:**")
                        icons = {
                            "success": "✅", "quota": "🚫",
                            "timeout": "⏱️", "parse_fail": "⚠️", "error": "❌",
                        }
                        for a in att:
                            ic = icons.get(a["status"], "•")
                            line = f"{ic} `{a['model']}` — {a['status']} ({a['latency_ms']}ms)"
                            if a.get("detail"):
                                line += f"  \n　　_{a['detail']}_"
                            st.caption(line)
            except Exception as exc:
                elapsed = _time.time() - t0
                status.update(label=f"失敗 · {stock_label} · {type(exc).__name__}", state="error")
                st.error(f"LLM 失敗: {type(exc).__name__}: {exc}")
                rec = None
            if rec:
                conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(rec["confidence"], "⚪")
                # 固定小標題, 方便捲到下面時仍能看到是哪檔股票
                industry_suffix = f" · {industry}" if industry else ""
                st.markdown(f"##### 🤖 {stock_label}{industry_suffix} — LLM 分析")
                tab_t, tab_c, tab_f, tab_i, tab_s = st.tabs(
                    ["📊 技術面", "💰 籌碼面", "📈 基本面", "🔗 產業鏈", "🎯 結論 + 風險"]
                )
                with tab_t:
                    st.markdown(rec.get("technical_analysis") or "—")
                with tab_c:
                    st.markdown(rec.get("chip_analysis") or "—")
                with tab_f:
                    st.markdown(rec.get("fundamental_analysis") or "—")
                with tab_i:
                    st.markdown(rec.get("industry_analysis") or "—")
                with tab_s:
                    if rec.get("summary"):
                        st.info(rec["summary"])
                    if rec.get("risk"):
                        st.warning(rec["risk"])
                    used = rec.get("model_used", "?")
                    fallback_note = " ⚠️ (主模型配額用完,自動切換)" if rec.get("fallback_used") else ""
                    st.caption(
                        f"信心度 {conf_emoji} {rec['confidence']} · "
                        f"模型 {used} · 耗時 {elapsed:.1f}s{fallback_note}"
                    )


# ========= MAIN =========
st.markdown(
    "<div class='page-title'>📈 台股推薦系統</div>",
    unsafe_allow_html=True,
)

latest = _latest_date()
if latest is None:
    st.error("資料庫為空,請先執行 scripts/fetch_stock_list.py 等資料擷取。")
    st.stop()

def _qp_int(key: str, default: int) -> int:
    try:
        return int(st.query_params.get(key, default))
    except (ValueError, TypeError):
        return default


def _qp_bool(key: str, default: bool) -> bool:
    return str(st.query_params.get(key, str(default))).lower() in ("true", "1", "yes")


with st.sidebar:
    st.header("⚙️ 設定")

    top_n = st.slider(
        "選股池大小",
        100, 1000, _qp_int("top_n", 500), step=100,
        help=(
            "從台股 1081 檔中,只看「成交最熱」的前 N 檔。"
            "數字小 → 聚焦大型股 / 流動性好;"
            "數字大 → 涵蓋更多中小型股,但可能流動性較差。"
        ),
    )

    min_vol_lots = st.number_input(
        "最小日均成交量 (張)",
        min_value=0, value=_qp_int("min_vol", 2000), step=500,
        help=(
            "過濾掉成交量太小的股票 (1 張 = 1000 股)。"
            "預設 2000 張 — 只看龍頭、流動性足。"
            "想看中小型股調到 500-1000。"
        ),
    )
    min_vol = int(min_vol_lots * 1000)

    show_n = st.slider(
        "每張清單顯示幾檔",
        5, 30, _qp_int("show_n", 10),
        help="短線、長線兩張清單各顯示前 N 名。"
    )

    only_ai = st.checkbox(
        "只看 AI 概念股",
        value=_qp_bool("only_ai", False),
        help="勾選後只顯示有 AI / 半導體 / HBM / 載板等概念標籤的股票。",
    )

    ai_boost = st.slider(
        "AI 加分幅度",
        0, 15, _qp_int("ai_boost", 6),
        help="AI 概念股的綜合分自動加 N 分,讓 AI 標的優先排在前面。設 0 = 關閉。",
    )

    scoring_version = st.radio(
        "📐 評分版本",
        options=["v1", "v2"],
        index=0 if str(st.query_params.get("ver", "v2")) == "v1" else 1,
        horizontal=True,
        help=(
            "**v1**: 規則式 (MA 多頭/MACD/KD/外資連買)\n\n"
            "**v2**: Mark Minervini SEPA + William O'Neil CAN SLIM 啟發\n"
            "  - Stage 2 嚴格趨勢檢查 (8 項全過才算)\n"
            "  - 52 週高點位置 (近高才強)\n"
            "  - 量價突破 (Breakout 20D)\n"
            "  - CAN SLIM 季 EPS YoY ≥ 25%\n"
            "  - 營收加速度"
        ),
    )

    st.query_params.update({
        "top_n": str(top_n),
        "min_vol": str(min_vol_lots),
        "show_n": str(show_n),
        "only_ai": str(only_ai),
        "ai_boost": str(ai_boost),
        "ver": scoring_version,
    })

    st.divider()
    st.caption(f"📅 最新資料日期: **{latest}**")

    if st.button("🔄 重建 Snapshot", help="清除所有快取,從最新 DB 資料重算排名與特徵 (同步新月營收/財報後請按)"):
        st.cache_data.clear()
        st.success("已清除快取,重新載入...")
        st.rerun()

    with st.expander("📊 資料庫狀態"):
        for k, v in _data_stats().items():
            st.caption(f"{k}: {v}")

    st.markdown("**🧠 LLM 模型**")
    default_label = MODEL_LABEL_BY_ID.get(DEFAULT_BATCH_MODEL, list(MODEL_OPTIONS.keys())[0])
    qp_model = st.query_params.get("model", default_label)
    if qp_model not in MODEL_OPTIONS:
        qp_model = default_label
    selected_label = st.selectbox(
        "呼叫分析時用",
        options=list(MODEL_OPTIONS.keys()),
        index=list(MODEL_OPTIONS.keys()).index(qp_model),
        label_visibility="collapsed",
        help="手動指定主模型。若此模型配額用完,自動切換到其他可用模型 (fallback)。",
    )
    selected_model = MODEL_OPTIONS[selected_label]
    st.query_params.update({"model": selected_label})
    st.caption("配額用完時自動 fallback 到其他模型")

    st.divider()
    st.caption("⚠️ 本系統僅供研究,不構成投資建議。")

ranked = _build_ranking(top_n, latest, min_vol, ai_boost, scoring_version)
if only_ai:
    ranked = ranked[ranked["is_ai_concept"] == True].copy()
    ranked["rank_short"] = ranked["short_score"].rank(ascending=False, method="min")
    ranked["rank_long"] = ranked["long_score"].rank(ascending=False, method="min")

with st.expander("❓ 怎麼用這個系統?", expanded=False):
    st.markdown(
        """
        **三個分頁:**
        - 🚀 **短線波段** — 持有 5–20 日的進場機會,看技術面 + 籌碼面
        - 💎 **中長線價值** — 持有 3–12 月,看基本面 + 成長動能
        - 📋 **原始資料** — 全特徵表,可下載分析用

        **怎麼看推薦?**
        1. 上方表格是 Top N 排名,**綜合分** 越高越值得關注
        2. 下方每檔可**點開展開**,看 K 線圖、三大法人動向
        3. 點 **🤖 LLM 深入分析** 按鈕,LLM 會用四個面向幫你解讀

        **左側設定可以做什麼?**
        - **選股池大小**:從 1081 檔中只看成交最熱的前 N 檔 (預設 500)
        - **最小日均成交量**:過濾掉太冷門、進出沒人接的股票
        - **顯示檔數**:每張清單看幾名

        **限制:** 系統還沒爬新聞,所以情緒面暫用中性分;部分股票還缺財報資料 (FinMind 配額限制)。
        """
    )

tab_short, tab_long, tab_raw = st.tabs(["🚀 短線波段", "💎 中長線價值", "📋 原始資料"])

with tab_short:
    st.subheader(f"短線波段 Top {show_n} (持有 5–20 日)")
    if scoring_version == "v2":
        st.caption("📐 v2 (SEPA + CAN SLIM):技術 55% (Stage 2/RS/52W/Breakout) + 籌碼 30% + 情緒 15% + AI 加分")
    else:
        st.caption("📐 v1 (規則式):技術 50% + 籌碼 30% + 情緒 20% + AI 加分")
    top_short = ranked.dropna(subset=["short_score"]).sort_values("rank_short").head(show_n)
    for i, (_, r) in enumerate(top_short.iterrows()):
        _render_stock_card(r, "short", idx=i, llm_model=selected_model)

with tab_long:
    st.subheader(f"中長線價值 Top {show_n} (持有 3–12 月)")
    if scoring_version == "v2":
        st.caption("📐 v2 (CAN SLIM):基本面 55% (季 EPS/年 EPS/營收加速) + 技術 30% + 籌碼 15%")
    else:
        st.caption("📐 v1:基本面 60% + 技術面 25% + 籌碼 15%")
    eligible = ranked.dropna(subset=["long_score"]).sort_values("rank_long").head(show_n)
    if eligible.empty:
        st.warning("⚠️ 目前基本面資料不足,請跑 `python scripts/fetch_financials.py --top-n 500 --resume` 補齊。")
    else:
        for i, (_, r) in enumerate(eligible.iterrows()):
            _render_stock_card(r, "long", idx=i, llm_model=selected_model)

with tab_raw:
    st.subheader("全部特徵 (前 100 名)")
    display = ranked.dropna(subset=["short_score"]).sort_values("rank_short").head(100)
    st.dataframe(display, hide_index=True, width="stretch")

# SKILL.md

系統目前能做什麼 (Phase 1 + 2 + 4 已完成,3/5/6/7 部分)。

## 1. 資料擷取

| 指令 | 做什麼 | 寫入 |
|---|---|---|
| `fetch_stock_list.py` | TWSE 上市 1081 檔基本資料 | `stocks` |
| `fetch_prices.py [--days N] [--limit N]` | yfinance 日 K OHLCV | `prices_daily` |
| `fetch_institutional.py [--days N]` | TWSE T86 三大法人 | `institutional_daily` |
| `fetch_monthly_revenue.py [--top-n -1] [--resume] [--sleep N]` | FinMind 月營收 + YoY/MoM,撞 402 會自動 sleep 到整點 | `monthly_revenue` |
| `fetch_financials.py [--top-n -1] [--resume] [--sleep N]` | FinMind 季報 EPS/毛利率/淨利率 | `financials_quarterly` |
| `compute_indicators.py [--limit N]` | 本機計算 MA/RSI/MACD/KD/BB | `indicators_daily` |

⚠️ **只涵蓋上市 (TWSE)**，上櫃 (TPEx) 還沒做。上櫃強勢股 (6274 台表科、6415 矽力、8299 群聯等) 目前在系統裡缺席。

## 2. 技術指標 (本機計算)

| 指標 | 欄位 | 週期 |
|---|---|---|
| 移動平均 | `ma5`, `ma20`, `ma60` | 5/20/60 日 |
| RSI | `rsi14` | 14 日 |
| MACD | `macd`, `macd_signal`, `macd_hist` | 12/26/9 |
| 隨機指標 KD | `k9`, `d9` | 9 日 |
| 布林通道 | `bb_upper`, `bb_lower`, `bb_position` | 20 日 ± 2σ |
| 量能 | `volume_ma5`, `volume_ratio` | 5 日均量 + 當日 / 均量 |

## 3. 特徵層 (`src/stock_llm/features/`)

| 模組 | 產出特徵 |
|---|---|
| `technical.py` | MA 多頭/短多/站上均線、MACD/KD 金叉、RSI 區位、Stage 2 檢查 (8 項)、52 週高位置、Breakout 20D |
| `chip.py` | 外資/投信 5/20 日淨額、**4 個連買/連賣日數**、dealer_net、inst_intensity |
| `fundamental.py` | 營收 YoY 1/3/6 個月、營收加速度、MoM、CAN SLIM C/A、毛利率/淨利率/趨勢、EPS |
| `tags.py` | AI 概念股 100 檔 18 分類 + `has_ai_concept / ai_bonus / get_tags` |
| `snapshot.py` | `build_feature_snapshot(as_of, codes)` 一次合併上述 |

## 4. 評分模型 (`src/stock_llm/models/`)

### v1 (`scoring.py`) — 規則式
- 短線: 0.5×技術 + 0.3×籌碼 + 0.2×情緒 + AI 加分
- 長線: 0.6×基本面 + 0.25×技術 + 0.15×籌碼 + AI 加分

### v2 (`scoring_v2.py`) — SEPA + CAN SLIM
- **技術 (Minervini SEPA)**: Stage 2 × 5、20/90 日 RS、pct_from_52w_high、Breakout 20D、MACD/RSI
- **基本面 (CAN SLIM)**: 季/年 EPS YoY ≥ 25%、營收加速度、毛利率趨勢、near 52w high bonus
- **籌碼 (2026-04 改版,雙向計分)**:
  - 基準 40 分 (避免無資料歸零)
  - 外資 5 日 >0 +15 / <0 −10
  - 投信 5 日 >0 +15 / <0 −5  (投信獨買也給分,過去只獎勵外資)
  - 雙買 bonus +10
  - 外資連買 × 2 (cap 12) / 連賣 × −2
  - 投信連買 × 2 (cap 10) / 連賣 × −1.5
  - inst_intensity 雙向 (±15~20)
  - volume_ratio > 1.5 → +10 / > 1.2 → +5
  - 夾 [0, 100]
- 短線 = 0.55×tech + 0.30×chip + 0.15×sentiment + AI 加分
- 長線 = 0.55×fund + 0.30×tech + 0.15×chip + AI 加分 (無 fund_score 則 NaN)

## 5. LLM 推理 (`src/stock_llm/llm/`)

### 模型目錄 (`gemini.py`)

| 常數 | ID | TPM | RPD |
|---|---|---|---|
| `MODEL_FLASH_LITE` ⭐ 預設 | `gemini-3.1-flash-lite-preview` | 300k | 14400 |
| `MODEL_FLASH` | `gemini-3-flash-preview` | 250k | 1500 |
| `MODEL_PRO` | `gemini-3.1-pro-preview` | 250k | 100 |
| `MODEL_GEMMA_MOE` | `gemma-4-26b-a4b-it` | 30k | 14400 |
| `MODEL_GEMMA_DENSE` | `gemma-4-31b-it` | 10k | 3600 |

`DEFAULT_FALLBACK_CHAIN = [Flash Lite → Flash → Gemma MoE → Gemma Dense]`

### 推薦分析 (`recommendation.py`)

`generate_recommendation(code, name, industry, features, track, tags, model=...)`:
- 主 model 自動插到 fallback chain 最前面
- 每個 model **25 秒 timeout** (用 `concurrent.futures`)
- 全鏈 **90 秒總預算**
- JSON schema 強制 7 個欄位:technical_analysis / chip_analysis / fundamental_analysis / industry_analysis / summary / risk / confidence
- **文字清理**: 砍 `\`\`\``、`jsonstring`、`<thought>`、`ext{}`、連續重複短語 (>=3 次)、泰/阿/俄文字元 (Gemma 幻覺常見)
- JSON 截斷救援:`_repair_truncated_json` 用 brace-depth 補齊
- 回傳 `Recommendation.attempts`:完整的「試了哪幾個 model / 每個的 status / latency / detail」

### 用量追蹤 (`usage.py`)

- 每次 `log_call(...)` 寫 `llm_usage` 表 (DuckDB)
- `recent_calls(limit=N)` / `usage_today_by_model()` / `usage_with_limits(primary=...)` 查詢
- 配額數字是**寫死的估計**,真實值看 Cloud Console

## 6. Streamlit Dashboard (`app/main.py`)

### 功能
- 3 個 tab: 短線波段 / 中長線價值 / 原始資料
- 每張個股卡片: K 線圖 (90 日) + 法人 5 日 + LLM 分析按鈕
- **LLM 狀態 widget**: 顯示耗時、模型、fallback 歷程 (✅🚫⏱️⚠️❌)
- Sidebar: top_n / min_vol / show_n / only_ai / ai_boost / v1-v2 / **LLM 模型下拉** / **🔄 重建 Snapshot**
- 設定存在 URL `?top_n=...&model=...`,重新開啟沿用
- 所有資料快取 `@st.cache_data(ttl=3600)`,cache key 含 DB 最新日期 (更新後自動失效)

## 7. 尚未做

- 🔲 **Phase 3**: 新聞爬取 (鉅亨 / 工商 RSS) + Gemma 情緒打分 → `news` 表
- 🔲 **Phase 5**: 回測引擎 (vectorbt)
- 🔲 **Phase 6**: 上櫃 TPEx 資料源整合
- 🔲 **Phase 7**: 部署 GCP VM + 每日排程

## 8. 範例查詢 (DuckDB)

```python
from stock_llm.data.store import connect

with connect() as con:
    # 今日外資大買前 10 檔
    con.execute("""
        SELECT i.stock_code, s.name, i.foreign_net
        FROM institutional_daily i JOIN stocks s USING (stock_code)
        WHERE i.trade_date = (SELECT MAX(trade_date) FROM institutional_daily)
        ORDER BY i.foreign_net DESC LIMIT 10
    """).fetchdf()

    # LLM 今日呼叫成功/失敗統計
    con.execute("""
        SELECT model,
               COUNT(*) total,
               SUM(CASE WHEN success THEN 1 ELSE 0 END) ok,
               AVG(latency_ms) avg_ms
        FROM llm_usage
        WHERE called_at >= CURRENT_DATE
        GROUP BY model
    """).fetchdf()
```

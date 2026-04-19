# stock_llm

台股推薦系統 — 結合**技術面、基本面、籌碼面**與 **LLM 分析**,輸出短線波段 (5–20 日) 與中長線價值 (3–12 月) 雙軌推薦。

提供 v1 (規則式) 與 **v2 (Mark Minervini SEPA + William O'Neil CAN SLIM)** 兩套評分,Streamlit Dashboard 即時瀏覽。

---

## ✨ 核心能力

| 面向 | 資料源 | 用途 |
|---|---|---|
| 上市股票清單 (1081 檔) | TWSE OpenAPI | 過濾候選池、產業分類 |
| 日 K OHLCV (2 年) | yfinance | 技術指標、回測 |
| 三大法人買賣超 | TWSE T86 | 短線籌碼訊號 |
| 月營收 + YoY/MoM | FinMind | 中長線成長動能 |
| 季財報 (EPS/毛利率) | FinMind | CAN SLIM 評分 |
| 技術指標 (MA/RSI/MACD/KD/BB) | 本機計算 | 進出場訊號 |
| **AI 概念股 tag (100 檔/18 類)** | 內建 | AI 加分 + 篩選 |
| **新聞情緒** (近 5 天加權) | 鉅亨網 Anue + Gemini Flash Lite 打分 | v2 短線分 15% |
| **LLM 深入分析** (技術/籌碼/基本面/產業鏈) | Gemini 3.1 Flash Lite (+ 4 個備援) | 中文研究報告 |

---

## 🚀 快速開始

### 1. 安裝環境

```bash
conda create -n stock python=3.11 -y
conda activate stock
pip install -e .
```

### 2. 設定 API Key

```bash
cp .env.example .env
```

編輯 `.env`,填入:
```
GEMINI_API_KEY=...    # 從 https://aistudio.google.com/apikey
FINMIND_TOKEN=...     # 從 https://finmindtrade.com/ (選填,用於月營收/財報)
```

### 3. 建立資料庫

#### 方式 A:從 parquet 快速匯入 (30 秒,推薦)
Repo 已附 `data/snapshot/*.parquet` (1.5M rows, 約 57MB),直接匯入重建 DB:
```bash
python scripts/import_parquet_to_duckdb.py
```
想要更新到最新資料 → 直接跑一次「情境 B:每日盤後增量」。

#### 方式 B:從頭抓 (約 30–60 分鐘)
```bash
python scripts/fetch_stock_list.py                                # 股票清單 (5 秒)
python scripts/fetch_prices.py                                    # 2 年日 K (30 秒)
python scripts/fetch_institutional.py --days 730                  # 2 年三大法人 (~25 分)
python scripts/compute_indicators.py                              # 技術指標 (1 分)
python scripts/fetch_monthly_revenue.py --top-n -1 --resume --sleep 1.0  # 月營收 (配額用完會自動等)
python scripts/fetch_financials.py --top-n -1 --resume --sleep 1.0       # 季財報 (同上)
python scripts/fetch_news.py --pages 5 --max-age-days 7                  # 近 7 天新聞 (~1 分)
python scripts/score_news.py --limit 300                                 # LLM 打分 (~3 分)
```

`--resume` 會跳過已有資料的股票、`--top-n -1` = 全部 1081 檔。撞到 FinMind 402 會自動 sleep 到下一小時整點重試,可以放背景跑。

### 4. 啟動 Dashboard

```bash
streamlit run src/stock_llm/app/main.py
```

預設 http://localhost:8501

---

## 📊 Dashboard 功能

### 三個分頁
- **🚀 短線波段** — Top N 短線推薦 (5–20 日持有)
- **💎 中長線價值** — Top N 長線推薦 (3–12 月,需基本面)
- **📋 原始資料** — 全特徵表

### 每張個股卡片
- **5 個核心指標** (收盤 / 技術 / 籌碼 / 基本面 / **情緒**)
  - 情緒 = 近 5 天新聞 Flash Lite 打分,0-100,中性 50;沒新聞顯示「—」
- 訊號標籤 (MA 多頭、MACD 黃金、外資連買 N 日…)
- AI 產業鏈 chip (AI 伺服器代工、HBM、ABF 載板…)
- **K 線圖 + 切換天數 (卡片內)** — 30/60/90(預設)/180/365/730,**每張卡獨立選擇**
  - 若 institutional 資料短於 K 線,會自動對齊並提示
  - MA5/20/60 + 量能 + 三大法人三個子圖
- 三大法人 5/20 日累計
- **📰 近期新聞 expander** — 7 天內所有關聯新聞
  - 📈 綠色正向 / 📉 紅色負向 / ➖ 灰色中性
  - LLM 一句話 summary + 點標題連到 Anue 原文
- **🤖 LLM 深入分析** — 5 個分頁:技術 / 籌碼 / 基本面 / 產業鏈 / 結論+風險
  - 顯示耗時、使用的模型、是否 fallback
  - 展開 status 看「**嘗試歷程**」:哪個模型先試、為什麼切換

### 側邊欄設定 (URL 持久化)
- 選股池大小 (top N by 成交值,預設 **500**)
- 最小日均量 (張,預設 **2000** — 只看龍頭)
- 顯示檔數 (5–30,預設 10)
- 只看 AI 概念股
- AI 加分幅度 (0–15)
- **📐 評分版本** — v1 / **v2 (預設)**
- **🧠 LLM 模型**下拉 (5 選 1)
- **🔄 重建 Snapshot** (清 Streamlit cache,同步新進 DB 資料後點一次)

---

## 🧠 LLM 模型選擇 + Fallback

### 可選模型 (從 sidebar 下拉切換)

| 顯示名 | ID | 免費 TPM | 免費 RPD | 特性 |
|---|---|---|---|---|
| **Flash Lite ⭐ 快·穩定** (預設) | `gemini-3.1-flash-lite-preview` | 300k | 14400 | 中文輸出穩定,3–8 秒 |
| Flash (更聰明 · 慢) | `gemini-3-flash-preview` | 250k | 1500 | 理解力強,10–20 秒 |
| Pro (最強 · 日限 100) | `gemini-3.1-pro-preview` | 250k | 100 | 深入分析,30 秒起 |
| Gemma 26B MoE | `gemma-4-26b-a4b-it` | 30k | 14400 | 開源 MoE,輸出偶有格式外洩 |
| Gemma 31B Dense | `gemma-4-31b-it` | 10k | 3600 | 開源 Dense,RPD 少 |

### 自動 Fallback 鏈

撞到 429/402 配額錯誤 或 25 秒 timeout,會**自動切換**到下一個模型:

```
你選的主模型 → Flash Lite → Flash → Gemma MoE → Gemma Dense
（失敗的跳過,繼續下一個,整鏈總上限 90 秒）
```

每次呼叫在 DuckDB `llm_usage` 表留紀錄 (model / tokens / latency / success / error)。

### 怎麼看自動切換的 log?

**Terminal** (跑 streamlit 的視窗):
```
[INFO] LLM call start: gemini-3.1-flash-lite-preview for 2345 (attempt 1/4)
[WARNING] Quota error on gemini-3.1-flash-lite-preview, trying next model (3 remaining)
[INFO] LLM call start: gemini-3-flash-preview for 2345 (attempt 2/4)
[INFO] LLM gemini-3-flash-preview returned in 15234ms for 2345
```

**UI** (點 LLM 深入分析按鈕):
```
✓ 完成 · gemini-3-flash-preview · 16.3s (fallback)
  嘗試歷程:
  🚫 gemini-3.1-flash-lite-preview — quota (1032ms)
  ✅ gemini-3-flash-preview — success (15234ms)
```

---

## 📐 評分版本

### v1 — 規則式
| 軌 | 公式 |
|---|---|
| 短線 | 0.5×技術 + 0.3×籌碼 + 0.2×情緒 + AI 加分 |
| 長線 | 0.6×基本面 + 0.25×技術 + 0.15×籌碼 + AI 加分 |

### v2 — SEPA + CAN SLIM (預設)
參考 Mark Minervini (3 屆 USIC 冠軍) + William O'Neil (IBD):

**短線技術**:
- Stage 2 趨勢 (MA50/150/200 共 8 項檢查)
- 90 日 / 20 日相對強度
- 距 52 週高點 < 15%
- 量價突破 (Breakout 20D)

**長線基本面**:
- CAN SLIM C: 季 EPS YoY ≥ 25%
- CAN SLIM A: 年 EPS YoY ≥ 25%
- 營收加速度
- 毛利率擴張

**籌碼 (雙向計分,v2 2026-04 改版):**
- 外資 5 日淨買/賣 ± (不再只獎勵買)
- 投信獨買也給分 (過去只看外資)
- 外資/投信連買加分、**連賣扣分**
- 量能放大 (volume_ratio > 1.2/1.5) 加分
- `inst_intensity` 用絕對值 (賣方倒貨也反映)
- 基準 40 分,避免沒法人資料直接歸零

**情緒 (Phase 3 接上,2026-04):**
- 來源: Anue 鉅亨網 → Flash Lite 批次打分 → 5 天加權平均
- 每則新聞 LLM 給 score (-1~+1) + impact (high/med/low) + 一句話 summary
- **擷取層 off-topic 過濾**: 新聞 title+summary 沒提到該股票名稱就不配對 (Anue 常把多檔股票亂掛,過濾後誤標率 < 1%)
- Prompt 強制**前瞻性視角**:已反映的宏觀議題 (關稅/Fed) 給 0 分,只抓**個股增量事件**
- Prompt 強制**主題辨識**:若新聞主要關於其他公司,這檔只是順帶提及 → score=0
- 衰減: 半衰期 **1.5 天** (3 天前就降到 25%)
- impact 權重: high=2.0 / medium=1.0 / low=0.5
- 沒新聞的股票維持中性 50

短線分 = `0.55×tech + 0.30×chip + 0.15×sentiment + AI 加分`

側邊欄切換版本即可。

---

## 📅 我的資料庫目前覆蓋到什麼時候?

目前 repo 內建的 parquet snapshot 覆蓋範圍 (約 1.55M rows / 57MB zstd):

| 表 | 起始 | 最新 | 期間 | 檔數 |
|---|---|---|---|---|
| 日 K `prices_daily` | 2024-04-19 | 2026-04-17 | **2 年** | 1,081 |
| 技術指標 `indicators_daily` | 2024-04-19 | 2026-04-17 | 2 年 | 1,081 |
| 三大法人 `institutional_daily` | 2024-04-22 | 2026-04-17 | **2 年** | 1,128 |
| 月營收 `monthly_revenue` | 2023-03 | 2026-03 | **3 年** | 1,073 |
| 季財報 `financials_quarterly` | 2023Q1 | 2026Q1 | 3 年 | 1,071 |
| 新聞 `news` | 最近 7 日 | — | 滾動 | 100+ 則 |

自己查當下狀況:
```python
from stock_llm.data.store import connect
with connect() as con:
    for tbl, col in [('prices_daily','trade_date'), ('institutional_daily','trade_date'),
                     ('monthly_revenue','year_month'), ('financials_quarterly','year_quarter')]:
        r = con.execute(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {tbl}").fetchone()
        print(f"{tbl}: {r[0]} -> {r[1]} ({r[2]:,} 筆)")
```

---

## 🔄 資料同步

### ⚠️ 先了解:`--days` 是**日曆天**不是交易天
- `--days 90` ≈ 54 個交易日 (扣掉週末 + 春節 + 228 + 清明…)
- 想看 60 交易日 → 指定 **`--days 120`** 比較保險
- 想看 2 年 → `--days 730`

### 情境 A:第一次建庫 (約 30–60 分)
見上方「快速開始 → 3. 建立資料庫」章節。

### 情境 B:每日盤後增量 (約 5–8 分)
```bash
# --days 7 保險覆蓋上次跑之後的所有交易日
python scripts/fetch_prices.py --days 7
python scripts/fetch_institutional.py --days 7
python scripts/compute_indicators.py
python scripts/fetch_news.py --pages 5 --max-age-days 7       # 今日新聞
python scripts/score_news.py --limit 300                       # LLM 打分
```

### 情境 C:每月 10 日 (當月營收公布)
```bash
python scripts/fetch_monthly_revenue.py --top-n -1 --resume --sleep 1.0
```
- `--resume` 跳過已有 ≥12 月資料的股票
- 撞 FinMind 402 會自動 sleep 到下一小時整點重試

### 情境 D:每季末 + 45 天 (財報截止)
```bash
python scripts/fetch_financials.py --top-n -1 --resume --sleep 1.0
```

### 情境 E:更新 git snapshot (其他裝置想同步)
在主機跑完 fetch 後,把最新 DB 重新 export 成 parquet 並 push:
```bash
python scripts/export_duckdb_to_parquet.py       # DB → data/snapshot/*.parquet
git add data/snapshot/
git commit -m "snapshot: $(date +%Y-%m-%d)"
git push
```
其他裝置:
```bash
git pull && python scripts/import_parquet_to_duckdb.py
```

---

### 同步完,dashboard 怎麼看到新資料?

| 動作 | 用途 |
|---|---|
| Sidebar → **🔄 重建 Snapshot** | 清 Streamlit `@st.cache_data` 所有 cache,重算排名/特徵/圖表 |
| `Ctrl+C` 重啟 streamlit | **改過 `.py` 程式碼**時必用 (熱更新抓不到依賴模組變動) |
| 瀏覽器按 R | 只重跑主 script,不清 cache,多數情況沒用 |

**規則:**
- 只是跑資料擷取 → 重建 Snapshot 就夠
- 改過 python 程式 → 一定要 Ctrl+C 重啟
- 以為沒吃到最新東西 → 先試 🔄,不行再重啟

---

## 📁 專案結構

```
stock_llm/
├── src/stock_llm/
│   ├── config.py                環境變數 / 路徑
│   ├── data/
│   │   ├── schema.py            DuckDB 表 (含 llm_usage + news)
│   │   ├── store.py             連線 + upsert + update_news_sentiment
│   │   ├── twse.py              TWSE OpenAPI + T86
│   │   ├── finmind.py           FinMind (含 402 自動重試)
│   │   ├── prices.py            yfinance 批次擷取
│   │   ├── universe.py          Top-N 熱門股
│   │   ├── news_anue.py         鉅亨網 Anue 新聞爬蟲 + off-topic filter
│   │   └── mops.py              (備案) MOPS 爬蟲 stub
│   ├── features/
│   │   ├── technical.py         技術指標 + Stage 2 + 52W
│   │   ├── chip.py              籌碼特徵 (4 個連買/連賣日數)
│   │   ├── fundamental.py       基本面 + CAN SLIM
│   │   ├── sentiment.py         新聞情緒 5 天加權 (半衰期 1.5 天)
│   │   ├── tags.py              AI 概念股 100 檔/18 類
│   │   └── snapshot.py          特徵彙整 (tech + chip + fund + sentiment)
│   ├── llm/
│   │   ├── gemini.py            5 模型 + fallback chain + quota/503 偵測
│   │   ├── recommendation.py    LLM 分析 + timeout + attempt tracking
│   │   ├── news_scorer.py       新聞批次情緒打分 + fallback
│   │   └── usage.py             DuckDB 用量記錄 + 限額估算
│   ├── models/
│   │   ├── scoring.py           v1 規則式評分
│   │   └── scoring_v2.py        v2 SEPA + CAN SLIM (籌碼雙向, 情緒接上)
│   └── app/
│       └── main.py              Streamlit Dashboard
├── scripts/
│   ├── fetch_stock_list.py
│   ├── fetch_prices.py / fetch_institutional.py
│   ├── fetch_monthly_revenue.py / fetch_financials.py
│   ├── fetch_news.py / score_news.py                            (Phase 3)
│   ├── compute_indicators.py / build_features.py / rank_stocks.py
│   ├── export_duckdb_to_parquet.py / import_parquet_to_duckdb.py   (snapshot)
│   └── test_gemini.py
├── data/
│   ├── stock_llm.duckdb         DuckDB 檔 (gitignored)
│   └── snapshot/*.parquet       git-tracked, clone 後 import 快速建 DB
├── .streamlit/config.toml       深色主題
├── .env.example
├── CLAUDE.md                    Claude Code 專案指引
├── SKILL.md                     系統能力說明
├── RULE.md                      開發規範
├── RUNBOOK.md                   故障處理手冊
└── pyproject.toml
```

---

## 🆘 故障排除

詳見 [RUNBOOK.md](RUNBOOK.md):
- FinMind 402 配額耗盡 → 自動 sleep 重試 / `--resume` / 升等贊助者
- LLM 撞 429/402 配額 → 自動 fallback 到 chain 下個模型
- LLM 撞 503 UNAVAILABLE / overloaded → 同樣自動 fallback (retriable error)
- LLM 呼叫超過 25 秒 → 自動 timeout 並 fallback
- LLM 輸出含亂碼 (泰文/thought/重複句) → 已內建清理,或換模型
- Anue 新聞多股誤標 → 擷取層 off-topic filter + LLM prompt 主題辨識
- TWSE SSL CERTIFICATE_VERIFY_FAILED → 已內建修正
- DuckDB 鎖定 → 關 Streamlit / Jupyter
- Streamlit 改 src/ 沒生效 → **完整重啟 Streamlit** (Ctrl+C 再跑)
- Dashboard 資料沒更新 → Sidebar 點「🔄 重建 Snapshot」清 cache

---

## ⚖️ 免責

**本系統僅供學術研究與個人使用,不構成投資建議。** 投資有風險,盈虧自負。

LLM 輸出可能有錯,評分為規則式 + 簡單模型,**未經回測驗證勝率**(Phase 5 待實作)。

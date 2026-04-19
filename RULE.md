# RULE.md

本專案的開發規範與底線。

## 安全

- 🔒 **API Key 永遠只在 `.env`**,不在 `.env.example` / 訊息 / commit
- 🔒 `.gitignore` 已保護 `.env`、DuckDB 檔、logs
- 🔒 Key 若不慎外洩 (包含貼對話、截圖、推錯 repo),**立刻 revoke 並重發**
- 🔒 `FINMIND_TOKEN` 同等對待,不進公開範本

## 程式規範

- Python 3.11+ (type hints、`from __future__ import annotations`)
- 路徑一律 `pathlib.Path`,**不**寫死 `\` 或 `/`
- 模組採 src-layout (`src/stock_llm/...`),scripts 放 `scripts/` 底下
- SQL 都走 DuckDB,schema 集中在 [src/stock_llm/data/schema.py](src/stock_llm/data/schema.py)
- 入口 script 必須 `sys.path.insert` 確保能匯入 `stock_llm.*`

## 資料規範

- **primary key 不可變動**:`stocks.stock_code`、`prices_daily.(stock_code, trade_date)` 等
- 所有 upsert 都用 `INSERT ... ON CONFLICT DO UPDATE`,不 TRUNCATE + INSERT
- 日期欄位用 `DATE` 型別;若來源是字串,統一轉 `pd.to_datetime(...).dt.date`
- 金額單位:股數 = 股、營收 = 元、EPS = 元、margin = 小數 (0.58 = 58%)
- 只保留 **4 碼個股代碼**,排除權證 (5–6 碼)、外資 DR (9 開頭)、指數

## API 使用底線

| 服務 | Rate limit 做法 |
|---|---|
| TWSE OpenAPI / T86 | 每次呼叫 `time.sleep(1.0)` 以上 |
| FinMind (免費) | 每檔 `time.sleep(0.3)`,設 token 後可以降到 0.1 |
| yfinance | 批次 50 檔一次打,不必 sleep (官方無嚴格 limit) |
| Gemini / Gemma API | 批次任務用 Flash/Gemma,高品質用 Pro;需要 JSON 時指定 `response_schema` 省重試 |

## 回測與訊號

- ⚠️ **絕對避免 look-ahead bias**:T 日訊號只能用 T-1 (含) 以前的資料
- ⚠️ 除權息必定用 `auto_adjust=True` 的 yfinance 數字
- 回測必報指標:年化報酬、最大回撤、Sharpe、勝率、換手率
- 單檔部位上限 10%,同產業上限 30%

## LLM 使用原則

- ❌ 不叫 LLM 預測股價、給目標價、下交易決策
- ✅ 叫 LLM 做**質化判斷**:情緒分數、事件分類、風險提示、人話總結
- ✅ 所有 LLM 輸出都要**結構化** (JSON schema),不靠後處理文字解析
- ✅ 對 LLM 的分數要**正規化到 [-1, +1]** 再餵入數值模型

## 測試

- 新寫 fetcher 先用 `--limit 5` 試再放大
- 新寫 scoring 先用單一產業試,避免大量錯誤浪費 API 額度
- DB 寫入前先在 logger 印 shape 與 head(5)

## 版本控管

- `data/` 與 `.env` 不進 git
- Commit 訊息首行 50 字內,必要時加說明段
- 大範圍重構前先 branch,通過本機測試才 merge

## 法律

- Dashboard 必帶免責聲明,本系統僅供研究
- 爬新聞遵守 robots.txt;未經授權**不**轉載全文
- 若要公開 / 收費提供選股,涉及《證券投資顧問事業管理規則》,需先諮詢

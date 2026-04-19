# CLAUDE.md

Claude Code 在此專案工作的指引。

## 專案定位

台股推薦系統,同時做**短線波段** (5–20 日) 與**中長線價值** (3–12 月) 雙軌推薦。LLM 負責質化判斷(新聞情緒、推薦理由),**不做數值預測**。

## 技術棧

- Python 3.11+ (conda env: `stock`)
- **DuckDB** (本機單檔資料庫)
- pandas / yfinance / requests
- **google-genai** SDK → Gemma 4 (批次) + Gemini 3 (品質)
- Streamlit (Dashboard)

部署目標:GCP VM Linux (n1-standard-2, 無 GPU)。目前階段**先本機開發**。

## 指令速查

```bash
# 啟動環境
conda activate stock

# 用 conda env 的 python 跑 (Windows bash 預設 python 是系統 Python 3.13)
/c/Users/Will/miniconda3/envs/stock/python.exe scripts/xxx.py

# 或 PowerShell
python scripts/xxx.py
```

## 關鍵設計決策

1. **價量走 yfinance、籌碼走 TWSE、基本面走 FinMind** — 各司其職,不重複
2. **FinMind 免費版不允許批次查詢**,所有歷史資料逐檔 loop + sleep 0.3s
3. **TWSE OpenAPI 憑證少 Subject Key Identifier**,Python 3.13 需關 `VERIFY_X509_STRICT` (見 [twse.py](src/stock_llm/data/twse.py))
4. **Industry 代碼對照表** 寫在 [twse.py](src/stock_llm/data/twse.py) `TWSE_INDUSTRY_MAP`
5. **DuckDB 的 `ON CONFLICT DO UPDATE SET col = CURRENT_TIMESTAMP` 會誤判為欄位名**,所以用 Python `datetime.now()` 當參數帶入
6. **LLM 不做數值預測**,只做質化判斷 (情緒分數、推薦理由、風險提示)

## 新增資料源時的 SOP

1. 在 [data/schema.py](src/stock_llm/data/schema.py) 加 table DDL + 加入 `ALL_SCHEMAS`
2. 在對應 fetcher (例 [data/finmind.py](src/stock_llm/data/finmind.py)) 加函式
3. 在 [data/store.py](src/stock_llm/data/store.py) 加 `upsert_xxx()`
4. 在 [scripts/](scripts/) 加執行入口
5. 更新 [README.md](README.md) 的建庫步驟

## 避免

- ❌ 把 API Key 寫進 .env.example (範本會上 git)
- ❌ LLM 直接預測股價或給目標價
- ❌ 抓新聞不 sleep 就狂打對方
- ❌ 沒 sleep 狂打 FinMind/TWSE
- ❌ 在 regex 濾股票代號時漏掉 (權證/ETF 大量混入)

## 處理 Windows / Linux 跨平台

- 路徑:用 `pathlib.Path`,不寫死 `\` 或 `/`
- 終端亂碼:Windows CP950 console 顯示繁中常亂碼,資料本身 OK
- Python 版本:本機 Windows conda env (3.11+) ↔ 部署 GCP Ubuntu (3.11+)

## Memory 位置

- 使用者設定、專案記憶:`C:\Users\Will\.claude\projects\c--Users-Will-Desktop-stock-llm\memory\`
- 永遠用繁體中文回覆使用者

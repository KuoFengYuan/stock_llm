# RUNBOOK.md

系統異常時的處理手冊。

## FinMind 配額耗盡 (HTTP 402)

### 症狀
```
FinMind HTTP 402 (Payment Required) dataset=TaiwanStockMonthRevenue data_id=xxxx
```

### 分層處理

#### 層級 1:等待配額重置 (首選)
- FinMind 免費會員 (有 token):**300/hr、每日數千**
- **每小時整點**重置。`fetch_monthly_revenue.py` / `fetch_financials.py` 內建**自動 sleep 到下一整點**並重試 (最多 24 次),所以配額撞到時:
  ```bash
  python scripts/fetch_monthly_revenue.py --top-n -1 --resume --sleep 1.0
  ```
  放背景跑就好,會自己等。
- `--resume` 會自動跳過 DB 已有 ≥12 個月 / ≥4 季資料的股票。

#### 層級 2:縮小宇宙 (中型股優先)
```bash
python scripts/fetch_monthly_revenue.py --top-n 500 --resume
```
只抓成交最熱的前 500 檔,約 5~10 分完成。

#### 層級 3:MOPS 爬蟲 (最後手段,尚未實作)
**公開資訊觀測站** https://mops.twse.com.tw/
- 月營收 `/mops/web/ajax_t05st10_ifrs`、季財報 `/mops/web/t164sb03`
- 必加 `time.sleep(3)`、User-Agent、先看 robots.txt
- 規劃位置:[src/stock_llm/data/mops.py](src/stock_llm/data/mops.py)

#### 層級 4:贊助者方案
- **FinMind 贊助者 NT$99/月** → 無限額度
- 要上 production 最划算的升級路徑

### 優先順序
```
等 1 小時 --resume → 縮小宇宙 --top-n 500 → MOPS → 贊助
   ↑ 最省                                       最貴 ↑
```

---

## LLM 相關問題

### 症狀 A:LLM 分析跑很久 (> 25 秒)
**正常行為** — 系統會自動切下一個模型 (fallback):
```
[INFO] LLM call start: gemini-3.1-flash-lite-preview for 8210 (attempt 1/4)
[WARNING] LLM timeout on gemini-3.1-flash-lite-preview after 25.0s
[INFO] LLM call start: gemini-3-flash-preview for 8210 (attempt 2/4)
[INFO] LLM gemini-3-flash-preview returned in 15234ms for 8210
```
- 每個模型 **25 秒 timeout**
- 全鏈總上限 **90 秒**
- UI 的「LLM 深入分析」status widget 展開後可看到完整嘗試歷程 (✅🚫⏱️⚠️❌)

### 症狀 B:撞到 429 / 402 配額錯誤
```
[WARNING] Quota error on gemini-3.1-flash-lite-preview, trying next model (3 remaining)
```
自動切下一個 model (chain: Flash Lite → Flash → Gemma MoE → Gemma Dense)。

手動處理:
1. Sidebar 下拉改選**未撞額度**的模型
2. 或等配額重置 (RPM/TPM 每分鐘、RPD 每日 UTC 00:00)
3. 看 [Cloud Console](https://console.cloud.google.com/iam-admin/quotas?service=generativelanguage.googleapis.com) 真實剩餘配額

### 症狀 B2:503 UNAVAILABLE / Overloaded (伺服器忙)
```
503 UNAVAILABLE: This model is currently experiencing high demand
```
系統自動把 503/500/502/504 視為可 fallback 的暫時錯誤 (`is_retriable_error`),
UI 嘗試歷程顯示:
```
🔌 gemini-3.1-flash-lite-preview — unavailable (892ms)
✅ gemini-3-flash-preview — success (17108ms)
```
無需人工介入,系統會自動切換。若所有 model 都 503,等幾分鐘後重試。

### 症狀 C:LLM 輸出有亂碼
例如:
- 中文裡夾泰文 `ทั้งสอง` / 阿拉伯 / 俄文
- 結尾有 `thought}{` / `jsonstring{` / `ext{}`
- 同一句話重複 3–5 次

**原因**: Gemma 4 小模型格式外洩 + 幻覺 (training token 跑出來、語言漂移)。

**已內建自動清理** ([recommendation.py](src/stock_llm/llm/recommendation.py) `_clean_text`):
- 砍 markdown code fence / `jsonstring` / `<thought>` / `ext{}`
- 偵測連續重複短語 (>= 3 次) 並截斷
- 移除非 CJK 的幻覺語系 (泰/阿/俄)

如果清理後還是爛 → **Sidebar 切到 Gemini Flash Lite / Flash** (預設就是 Flash Lite)。Gemma 模型在中文 task 穩定度明顯較差。

### 症狀 D:全部 fallback 都失敗
```
LLM 失敗: TimeoutError: Overall budget 90s exceeded
```
或
```
summary: 全部 fallback 模型都失敗: ...
```

逐一排除:
1. **網路**: `curl https://generativelanguage.googleapis.com` 是否通
2. **API Key**: `.env` 的 `GEMINI_API_KEY` 是否有效 (到 AI Studio 測)
3. **所有 model 配額都滿** (罕見,除非一天打爆 RPD):等重置

### 症狀 E:UI 看不到按鈕變化 / status widget 異常
Streamlit 熱更新抓不到依賴模組 (`llm/recommendation.py` 等) 的變動。
**`Ctrl+C` 重啟 streamlit**。

---

## Streamlit Dashboard 資料沒更新

### 症狀
- 跑完 fetch script,dashboard 還顯示舊數字
- K 線最後一根不是最新交易日
- 新抓的月營收沒反映在 v2 長線分數

### 原因
`@st.cache_data(ttl=3600)` 以參數為 key。資料 fetch 完 DB 更新了,但 cache 還在。

### 處理
1. **Sidebar 點 🔄 重建 Snapshot** (最快)
2. 或 `Ctrl+C` 重啟 streamlit (連依賴模組也會重載)
3. 瀏覽器按 R 通常沒用 — 只重跑主 script 不清 cache

---

## K 線 / 法人圖範圍不一致

### 症狀
- K 線從 Dec 1 開始,下方法人圖從 Jan 20 才有資料
- 切換股票後發現只顯示 54 個交易日 (不是預設 60)

### 原因
`institutional_daily` 表的歷史比 `prices_daily` 短 (你當初只跑 `--days 90` 抓法人)。
系統會**自動把 K 線截到 institutional 起始日**,讓圖左右對齊。

### 處理
想看到完整 60 / 90 / 730 天:
```bash
python scripts/fetch_institutional.py --days 120   # 60 交易日
python scripts/fetch_institutional.py --days 730   # 2 年
```
跑完 → 🔄 重建 Snapshot。

---

## API Key / Token 外洩

### 檢查清單
- `.env` 內容不要貼在對話、email、截圖
- `git log` 確認沒 commit 進 `.env`
- 錯誤訊息不能印出完整 URL (已在 [finmind.py](src/stock_llm/data/finmind.py) `_get()` 做遮罩)

### 發現外洩
1. 立即到對應後台 **Delete / Revoke** 舊 Key
2. 產新 Key,更新 `.env`
3. 若 Key 曾出現在 git commit,rewrite history 或新 repo
4. 若出現在 log 檔,刪除 `C:\Users\Will\AppData\Local\Temp\claude\` 相關 output

---

## DuckDB 鎖定 / 斷開

### 症狀
```
duckdb.duckdb.IOException: Could not set lock on file "stock_llm.duckdb"
```

### 原因
- 另一個 Python 程序還開著 DB (Streamlit 跑著同時又跑 script)
- Windows 檔案系統偶爾延遲釋放

### 處理
1. 關掉 Streamlit / Jupyter
2. 重開終端,重試
3. 嚴重時:`rm data/stock_llm.duckdb.wal` (只有 `.wal` 未合併時)

---

## yfinance 抓不到

### 症狀
- 某些股票連續失敗
- `No data for 2330.TW`

### 處理
1. 單檔試:`yf.download("2330.TW", period="5d")`
2. yfinance 整體不穩 → 改 TWSE `/v1/exchangeReport/STOCK_DAY`
3. 或切 FinMind `TaiwanStockPrice` dataset

---

## TWSE SSL / CERTIFICATE 錯誤

Python 3.13 嚴格檢查憑證,TWSE 憑證缺 Subject Key Identifier。
已在 [twse.py](src/stock_llm/data/twse.py) `_TWSETLSAdapter` 解決 (關掉 `VERIFY_X509_STRICT`)。
若部署其他環境遇到 → 確認 Python 版本,或更新 `certifi`。

---

## 增量更新排程 (未來規劃)

詳細指令見 [README.md](README.md) 「🔄 資料同步」章節。

### 未來部署 GCP
- Cloud Scheduler + Cloud Run Jobs (daily 14:30 台北時間觸發)
- 或 VM 上 cron

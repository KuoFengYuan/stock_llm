"""批次 LLM 新聞情緒打分。

輸入: (url, stock_code, title, content) 列表
輸出: 每筆的 sentiment_score (-1~+1) / impact (high/medium/low) / 一句話摘要

用 Flash Lite 當預設,JSON schema 強制結構化輸出,批次 10 筆/call。
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import time
from typing import Any

from stock_llm.llm.gemini import (
    DEFAULT_FALLBACK_CHAIN,
    MODEL_FLASH_LITE,
    get_client,
    is_quota_error,
    is_retriable_error,
)
from stock_llm.llm.usage import extract_token_counts, log_call

logger = logging.getLogger(__name__)

BATCH_SIZE = 10
PER_CALL_TIMEOUT_S = 25.0

_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "score": {"type": "number"},
                    "impact": {"type": "string", "enum": ["high", "medium", "low"]},
                    "summary": {"type": "string"},
                },
                "required": ["index", "score", "impact", "summary"],
            },
        }
    },
    "required": ["results"],
}


def _build_prompt(batch: list[dict]) -> str:
    lines = [
        "你是台股新聞情緒分析師。評估每則新聞對該檔股票**未來 1-5 個交易日**股價的「增量」影響。",
        "",
        "**極重要 — 避免以下錯誤:**",
        "1. 已被市場 pricing in 的宏觀議題 (例:美中關稅戰、Fed 利率、地緣衝突) 除非有**新進展**否則給 0 分",
        "2. 純大盤走勢分析 / 大盤點評 / 技術面回顧 → 一律 impact=low 且 score=0",
        "3. 已過時的舊聞重發 → 0 分",
        "4. 評估「增量資訊價值」,不是評估新聞描述的事件本身是好是壞",
        "5. **[重要] 若新聞主要關於其他公司,[] 內股票只是順帶提及** → score=0, impact=low,",
        "   summary 說明「本新聞主要關於 XXX,對此股無直接影響」",
        "   例:新聞關於大立光法說,但 [2330] 只是列於相關個股 → 對 2330 給 0 分",
        "",
        "**真正應該給非零分的:**",
        "- 該公司的**個股事件**: 獲利公告、大單、併購、高層變動、法說、意外事故、產能變化",
        "- 該公司的**訂單/產品/客戶**具體進展 (如: XX 獲 NVIDIA 下單)",
        "- 該公司特定的**利多利空** (法人調降目標價、某分析師推薦)",
        "",
        "評分規則:",
        "- score: -1.0 (極負) ~ +1.0 (極正),0 = 資訊性新聞或已被消化",
        "- impact: high=可能推動 > 3% 日波動 (限個股重大事件); medium=1~3%; low=<1%",
        "- summary: 一句話中文 (15-30 字) 說明**為何給這個分數** (包括「已反映」「無增量」的判斷)",
        "",
        "輸入新聞:",
    ]
    for i, row in enumerate(batch, 1):
        content = (row.get("content") or "").replace("<p>", "").replace("</p>", " ")[:300]
        lines.append(f"{i}. [{row['stock_code']}] {row['title']}")
        if content:
            lines.append(f"   摘要: {content}")
    lines += [
        "",
        "回 JSON: {\"results\": [{\"index\": 1..N, \"score\": float, \"impact\": str, \"summary\": str}, ...]}",
        "每一筆輸入都要對應一個輸出,index 從 1 開始。",
    ]
    return "\n".join(lines)


def _call_model(client, model: str, prompt: str):
    return client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": _SCHEMA,
            "temperature": 0.1,
            "max_output_tokens": 2000,
        },
    )


def score_news_batch(
    batch: list[dict],
    model: str = MODEL_FLASH_LITE,
) -> list[dict]:
    """對一批新聞打分。撞配額/503 自動 fallback 到 chain 下一個模型。
    全部失敗時回傳原 batch (score=None)。
    """
    if not batch:
        return []

    client = get_client()
    prompt = _build_prompt(batch)

    chain = [model] + [m for m in DEFAULT_FALLBACK_CHAIN if m != model]
    response = None
    used_model = model

    for idx, current in enumerate(chain):
        t0 = time.time()
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                response = pool.submit(_call_model, client, current, prompt).result(timeout=PER_CALL_TIMEOUT_S)
            used_model = current
            break
        except concurrent.futures.TimeoutError:
            latency = int((time.time() - t0) * 1000)
            logger.warning("news_scorer timeout on %s (%ds, batch=%d)", current, PER_CALL_TIMEOUT_S, len(batch))
            log_call(
                model=current, purpose="news_sentiment", stock_code=None,
                input_tokens=None, output_tokens=None,
                latency_ms=latency, success=False, error=f"[TIMEOUT] {PER_CALL_TIMEOUT_S}s",
            )
            continue
        except Exception as exc:
            latency = int((time.time() - t0) * 1000)
            quota = is_quota_error(exc)
            retriable = not quota and is_retriable_error(exc)
            tag = "[QUOTA] " if quota else ("[RETRY] " if retriable else "")
            logger.warning("news_scorer %s on %s: %s", tag.strip() or "error", current, str(exc)[:120])
            log_call(
                model=current, purpose="news_sentiment", stock_code=None,
                input_tokens=None, output_tokens=None,
                latency_ms=latency, success=False, error=tag + str(exc)[:200],
            )
            if quota or retriable:
                continue
            return [dict(r, score=None, impact=None, summary=None) for r in batch]

    if response is None:
        return [dict(r, score=None, impact=None, summary=None) for r in batch]

    latency = 0  # overall latency not tracked here
    in_tok, out_tok = extract_token_counts(response)
    model = used_model
    try:
        obj = json.loads(response.text)
        results: list[dict[str, Any]] = obj.get("results", [])
    except Exception as exc:
        logger.warning("news_scorer parse fail: %s", exc)
        log_call(
            model=model, purpose="news_sentiment", stock_code=None,
            input_tokens=in_tok, output_tokens=out_tok,
            latency_ms=latency, success=False, error="[PARSE_FAIL]",
        )
        return [dict(r, score=None, impact=None, summary=None) for r in batch]

    log_call(
        model=model, purpose="news_sentiment", stock_code=None,
        input_tokens=in_tok, output_tokens=out_tok,
        latency_ms=latency, success=True,
    )

    scored = [dict(r) for r in batch]
    for res in results:
        idx = res.get("index", 0) - 1
        if 0 <= idx < len(scored):
            scored[idx]["score"] = max(-1.0, min(1.0, float(res.get("score", 0))))
            scored[idx]["impact"] = res.get("impact", "low")
            scored[idx]["summary"] = res.get("summary", "")
    for s in scored:
        s.setdefault("score", None)
        s.setdefault("impact", None)
        s.setdefault("summary", None)
    return scored


def score_all(rows: list[dict], model: str = MODEL_FLASH_LITE, sleep_between: float = 1.0) -> list[dict]:
    """將 rows 切成 BATCH_SIZE 一組,依序打分。回傳所有結果。"""
    out: list[dict] = []
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i:i + BATCH_SIZE]
        logger.info("Scoring batch %d (rows %d-%d)", i // BATCH_SIZE + 1, i + 1, i + len(batch))
        out.extend(score_news_batch(batch, model=model))
        if i + BATCH_SIZE < len(rows):
            time.sleep(sleep_between)
    return out

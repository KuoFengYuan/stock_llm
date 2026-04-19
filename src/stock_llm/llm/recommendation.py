from __future__ import annotations

import concurrent.futures
import json
import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

PER_MODEL_TIMEOUT_S = 25.0
TOTAL_BUDGET_S = 90.0

from stock_llm.llm.gemini import (
    DEFAULT_FALLBACK_CHAIN,
    MODEL_FLASH_LITE,
    get_client,
    is_quota_error,
    is_retriable_error,
)
from stock_llm.llm.usage import extract_token_counts, log_call

logger = logging.getLogger(__name__)


@dataclass
class Recommendation:
    stock_code: str
    track: str
    technical_analysis: str
    chip_analysis: str
    fundamental_analysis: str
    industry_analysis: str
    summary: str
    risk: str
    confidence: str
    model_used: str = ""
    fallback_used: bool = False
    attempts: list[dict] = None  # type: ignore[assignment]

    def as_dict(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "track": self.track,
            "technical_analysis": self.technical_analysis,
            "chip_analysis": self.chip_analysis,
            "fundamental_analysis": self.fundamental_analysis,
            "industry_analysis": self.industry_analysis,
            "summary": self.summary,
            "risk": self.risk,
            "confidence": self.confidence,
            "model_used": self.model_used,
            "fallback_used": self.fallback_used,
            "attempts": self.attempts or [],
        }


def _fmt_pct(v) -> str:
    if v is None or pd.isna(v):
        return "N/A"
    return f"{float(v) * 100:.1f}%"


def _fmt_int(v) -> str:
    if v is None or pd.isna(v):
        return "N/A"
    return f"{int(float(v)):,}"


def _summarize_features(row: dict, track: str) -> str:
    tech: list[str] = []
    chip: list[str] = []
    fund: list[str] = []

    if row.get("ma_bullish"):
        tech.append("- 均線排列: 完全多頭 (MA5 > MA20 > MA60)")
    elif row.get("ma_short_bullish") and row.get("price_above_all_ma"):
        tech.append("- 均線排列: 短多 — MA5 > MA20,且收盤站上 MA5/MA20/MA60 (反彈中,MA20 尚未追上 MA60)")
    elif row.get("price_above_all_ma"):
        tech.append("- 均線排列: 收盤站上所有均線,但短中期均線排列尚未完全多頭")
    else:
        tech.append("- 均線排列: 未形成多頭")
    close = row.get("close")
    ma5 = row.get("ma5"); ma20 = row.get("ma20"); ma60 = row.get("ma60")
    if close is not None and not pd.isna(close):
        if ma5 and not pd.isna(ma5): tech.append(f"- 收盤 {float(close):.2f}, MA5 {float(ma5):.2f}")
        if ma20 and not pd.isna(ma20): tech.append(f"- MA20 {float(ma20):.2f}, MA60 {float(ma60 or 0):.2f}")
    if row.get("macd_golden_cross"):
        tech.append("- MACD 柱狀體當日由負轉正 (黃金交叉)")
    macd_h = row.get("macd_hist")
    if macd_h is not None and not pd.isna(macd_h):
        tech.append(f"- MACD 柱狀體 = {float(macd_h):+.2f}")
    if row.get("kd_golden_cross"):
        tech.append("- KD 指標當日黃金交叉")
    k9 = row.get("k9"); d9 = row.get("d9")
    if k9 is not None and not pd.isna(k9):
        tech.append(f"- K9 = {float(k9):.1f}, D9 = {float(d9 or 0):.1f}")
    rsi = row.get("rsi14")
    if rsi is not None and not pd.isna(rsi):
        zone = "超買區" if rsi > 70 else "超賣區" if rsi < 30 else "中性"
        tech.append(f"- RSI14 = {float(rsi):.1f} ({zone})")
    bbp = row.get("bb_position")
    if bbp is not None and not pd.isna(bbp):
        tech.append(f"- 布林帶位置 = {float(bbp)*100:.0f}% (0=下軌, 100=上軌)")
    vol_ratio = row.get("volume_ratio")
    if vol_ratio and not pd.isna(vol_ratio):
        tech.append(f"- 當日量 / 5 日均量 = {float(vol_ratio):.2f}")
    up = row.get("consecutive_up_days"); down = row.get("consecutive_down_days")
    if up and up > 0: tech.append(f"- 連漲 {int(up)} 日")
    if down and down > 0: tech.append(f"- 連跌 {int(down)} 日")

    f5d = row.get("foreign_net_5d_cum"); f20d = row.get("foreign_net_20d_cum")
    i5d = row.get("invest_net_5d_cum"); d5d = row.get("dealer_net_5d_cum")
    if f5d is not None and not pd.isna(f5d):
        chip.append(f"- 外資 5 日累計: {int(f5d)/1000:+,.0f} 張")
    if f20d is not None and not pd.isna(f20d):
        chip.append(f"- 外資 20 日累計: {int(f20d)/1000:+,.0f} 張")
    if i5d is not None and not pd.isna(i5d):
        chip.append(f"- 投信 5 日累計: {int(i5d)/1000:+,.0f} 張")
    if d5d is not None and not pd.isna(d5d):
        chip.append(f"- 自營商 5 日累計: {int(d5d)/1000:+,.0f} 張")
    f_buy = row.get("foreign_consecutive_buy_days")
    f_sell = row.get("foreign_consecutive_sell_days")
    i_buy = row.get("invest_consecutive_buy_days")
    i_sell = row.get("invest_consecutive_sell_days")
    if f_buy and f_buy >= 1:
        chip.append(f"- 外資連買 {int(f_buy)} 日")
    if f_sell and f_sell >= 1:
        chip.append(f"- 外資連賣 {int(f_sell)} 日")
    if i_buy and i_buy >= 1:
        chip.append(f"- 投信連買 {int(i_buy)} 日")
    if i_sell and i_sell >= 1:
        chip.append(f"- 投信連賣 {int(i_sell)} 日")
    intensity = row.get("inst_intensity")
    if intensity is not None and not pd.isna(intensity):
        chip.append(f"- 法人買超強度 (5日累計/5日均量) = {float(intensity)*100:+.1f}%")

    if row.get("has_fundamental_data"):
        fund.append(f"- 最新月營收 YoY = {_fmt_pct(row.get('revenue_yoy_latest'))}")
        fund.append(f"- 近 3 月 YoY 平均 = {_fmt_pct(row.get('revenue_yoy_3m_avg'))}")
        mom = row.get("revenue_mom_latest")
        if mom is not None and not pd.isna(mom):
            fund.append(f"- 最新月營收 MoM = {_fmt_pct(mom)}")
        pos_6m = row.get("revenue_months_positive_yoy_6m")
        if pos_6m is not None and not pd.isna(pos_6m):
            fund.append(f"- 近 6 個月 YoY 為正的月數 = {int(pos_6m)}")
        gm = row.get("gross_margin_latest")
        if gm is not None and not pd.isna(gm):
            fund.append(f"- 最新毛利率 = {_fmt_pct(gm)}")
        trend = row.get("gross_margin_trend")
        if trend and not pd.isna(trend):
            direction = "上升" if trend > 0 else "下滑"
            fund.append(f"- 毛利率近 4 季 vs 前 4 季 {direction} {abs(float(trend))*100:.1f} pp")
        nm = row.get("net_margin_latest")
        if nm is not None and not pd.isna(nm):
            fund.append(f"- 最新淨利率 = {_fmt_pct(nm)}")
        eps = row.get("eps_latest")
        if eps is not None and not pd.isna(eps):
            fund.append(f"- 最新季 EPS = {float(eps):.2f} 元")
    else:
        fund.append("- (尚無基本面資料)")

    return (
        "【技術面】\n" + ("\n".join(tech) if tech else "(無)")
        + "\n\n【籌碼面】\n" + ("\n".join(chip) if chip else "(無)")
        + "\n\n【基本面】\n" + ("\n".join(fund) if fund else "(無)")
    )


_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "technical_analysis": {"type": "string"},
        "chip_analysis": {"type": "string"},
        "fundamental_analysis": {"type": "string"},
        "industry_analysis": {"type": "string"},
        "summary": {"type": "string"},
        "risk": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
    "required": [
        "technical_analysis", "chip_analysis", "fundamental_analysis",
        "industry_analysis", "summary", "risk", "confidence",
    ],
}


import re as _re

_JUNK_MARKERS = (
    "```",
    "jsonstring",
    "<end_of_turn>",
    "<start_of_turn>",
    "<thought>",
    "</thought>",
    "<|endoftext|>",
    "ext{}",
    "ext{",
)

_BAD_TOKEN_PATTERNS = (
    _re.compile(r"\d*thought\}?\{?"),
    _re.compile(r"<\|?[a-z_]+\|?>"),
    _re.compile(r"[\u0E00-\u0E7F]+"),
    _re.compile(r"[\u0600-\u06FF]+"),
    _re.compile(r"[\u0400-\u04FF]+"),
)


def _strip_repetitions(text: str) -> str:
    """Cut the text just before a phrase starts repeating >=3 times in a row.
    Scans for 8..40-char windows that recur 3+ times consecutively.
    """
    if len(text) < 40:
        return text
    for window in (12, 18, 24, 32):
        for i in range(len(text) - window * 3):
            chunk = text[i:i + window]
            if text[i + window:i + window * 2] == chunk and text[i + window * 2:i + window * 3] == chunk:
                return text[:i].rstrip()
    return text


def _clean_text(text: str) -> str:
    """Remove LLM format-leak artifacts, foreign-script hallucinations, and
    consecutive phrase repetitions typical of small-model degradation.
    """
    if not text:
        return text
    for marker in _JUNK_MARKERS:
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx]
    for pat in _BAD_TOKEN_PATTERNS:
        text = pat.sub("", text)
    text = _strip_repetitions(text)
    text = _re.sub(r"[ \t]{2,}", " ", text)
    text = _re.sub(r",\s*,+", ",", text)
    return text.rstrip("` \n\t{}\"'、，").strip()


def _parse_json_lenient(text: str, stock_code: str) -> dict | None:
    """Extract a JSON object from text, tolerating code fences and truncation.
    Returns None if no usable structure could be recovered (caller may retry/fallback).
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`").lstrip("json").strip()

    try:
        obj, _ = json.JSONDecoder().raw_decode(s)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    start = s.find("{")
    if start < 0:
        return None
    body = s[start:]

    try:
        obj, _ = json.JSONDecoder().raw_decode(body)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass

    repaired = _repair_truncated_json(body)
    if repaired is not None:
        try:
            obj = json.loads(repaired)
            if isinstance(obj, dict):
                logger.info("Recovered truncated JSON for %s", stock_code)
                return obj
        except json.JSONDecodeError:
            pass

    logger.warning("JSON parse failed for %s (text len=%d)", stock_code, len(s))
    return None


def _repair_truncated_json(s: str) -> str | None:
    """Best-effort recovery of a JSON object that was truncated mid-string.
    Strategy: walk the string tracking brace/bracket/quote state; when input ends,
    close the open string (if any), then close all open braces/brackets.
    """
    depth_brace = depth_bracket = 0
    in_str = False
    escape = False
    last_complete = -1
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            depth_brace += 1
        elif ch == "}":
            depth_brace -= 1
            if depth_brace == 0 and depth_bracket == 0:
                last_complete = i
        elif ch == "[":
            depth_bracket += 1
        elif ch == "]":
            depth_bracket -= 1

    if last_complete >= 0:
        return s[: last_complete + 1]

    tail = ""
    if in_str:
        tail += '"'
    tail += "]" * max(depth_bracket, 0)
    tail += "}" * max(depth_brace, 0)
    if not tail:
        return None
    return s + tail


def generate_recommendation(
    stock_code: str,
    name: str,
    industry: str,
    features: dict,
    track: str = "short",
    model: str = MODEL_FLASH_LITE,
    tags: list[str] | None = None,
    fallback_chain: list[str] | None = None,
) -> Recommendation:
    client = get_client()
    horizon = "短線波段 (持有 5–20 日)" if track == "short" else "中長線價值 (持有 3–12 月)"
    summary = _summarize_features(features, track)
    tag_line = "AI 產業鏈標籤:" + (" / ".join(tags) if tags else "無 (非 AI 概念股或未列入清單)")

    def _fmt(v, suffix="") -> str:
        if v is None or pd.isna(v):
            return "N/A"
        try:
            return f"{float(v):.1f}{suffix}"
        except (TypeError, ValueError):
            return str(v)

    score_key = "short_score" if track == "short" else "long_score"
    overall = _fmt(features.get(score_key))
    tech_s = _fmt(features.get("tech_score"))
    chip_s = _fmt(features.get("chip_score"))
    fund_s = _fmt(features.get("fund_score"))

    prompt = f"""你是資深台股研究分析師。依據下方量化特徵,為單一標的產出**深入的中文分析**。

標的:{name} ({stock_code})
產業:{industry}
{tag_line}
時間框架:{horizon}
綜合評分:{overall}/100
 ├ 技術分:{tech_s}
 ├ 籌碼分:{chip_s}
 └ 基本面分:{fund_s}

{summary}

請以 JSON 格式回覆,包含以下欄位 (每段都要具體引用上方數字,不要空話):
- technical_analysis: 【技術面分析】約 100 字,說明均線排列、MACD/KD 動能、RSI 位階與量能配合狀況
- chip_analysis: 【籌碼面分析】約 100 字,具體說明外資 / 投信 / 自營商的動作,引用買超張數與連買天數
- fundamental_analysis: 【基本面分析】約 100 字,引用營收 YoY/MoM、毛利率趨勢、EPS;若無資料請直接說明
- industry_analysis: 【產業鏈分析】約 120 字,根據 AI 產業鏈標籤與產業別,說明:
    (a) 公司在該產業鏈的位置 (上/中/下游、客戶/供應商角色)
    (b) 主要產品與技術競爭力
    (c) 目前產業趨勢 (例 AI 伺服器需求、CoWoS 產能、HBM 缺口、CSP CapEx 等)
    (d) 受惠程度與潛在威脅
  若該標的非 AI 概念,改述其所在產業 (如金融、傳產) 的近期動能與展望
- summary: 【綜合結論】約 60 字,給出是否適合{horizon}的投資判斷
- risk: 【風險提示】列出 2-3 項具體風險 (例:個股技術面風險 + 大盤系統性風險 + 產業風險),60-80 字
- confidence: 信心度,填 "high" / "medium" / "low"

規則:
1. 語氣專業中立,不誇大、不保證獲利
2. 每段都要引用具體數字
3. 不給目標價、不預測明日走勢
4. 若某面向資料缺失,明確說「資料不足」
5. 產業鏈分析要引用具體客戶 / 供應鏈節點 (例:CoWoS、HBM3e、北美 CSP、AMD/NVIDIA、特斯拉等)"""

    import time as _time

    chain = fallback_chain if fallback_chain is not None else list(DEFAULT_FALLBACK_CHAIN)
    if model not in chain:
        chain = [model] + [m for m in chain if m != model]
    elif chain[0] != model:
        chain = [model] + [m for m in chain if m != model]

    data: dict | None = None
    used_model = ""
    fallback = False
    last_exc: BaseException | None = None
    attempts: list[dict] = []

    t_overall = _time.time()

    def _call(current: str):
        return client.models.generate_content(
            model=current,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": _JSON_SCHEMA,
                "max_output_tokens": 6000,
                "temperature": 0.3,
            },
        )

    for attempt_idx, current_model in enumerate(chain):
        if _time.time() - t_overall > TOTAL_BUDGET_S:
            logger.warning("Total LLM budget (%ds) exceeded for %s; aborting chain.", TOTAL_BUDGET_S, stock_code)
            last_exc = TimeoutError(f"Overall budget {TOTAL_BUDGET_S:.0f}s exceeded")
            break

        t0 = _time.time()
        logger.info("LLM call start: %s for %s (attempt %d/%d)", current_model, stock_code, attempt_idx+1, len(chain))
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_call, current_model)
                try:
                    response = future.result(timeout=PER_MODEL_TIMEOUT_S)
                except concurrent.futures.TimeoutError:
                    latency_ms = int((_time.time() - t0) * 1000)
                    logger.warning("LLM timeout on %s for %s after %.1fs", current_model, stock_code, PER_MODEL_TIMEOUT_S)
                    log_call(
                        model=current_model, purpose="recommendation", stock_code=stock_code,
                        input_tokens=None, output_tokens=None,
                        latency_ms=latency_ms, success=False,
                        error=f"[TIMEOUT] >{PER_MODEL_TIMEOUT_S:.0f}s",
                    )
                    attempts.append({
                        "model": current_model, "status": "timeout",
                        "latency_ms": latency_ms, "detail": f">{PER_MODEL_TIMEOUT_S:.0f}s",
                    })
                    last_exc = TimeoutError(f"{current_model} timed out after {PER_MODEL_TIMEOUT_S:.0f}s")
                    continue
            latency_ms = int((_time.time() - t0) * 1000)
            logger.info("LLM %s returned in %dms for %s", current_model, latency_ms, stock_code)
            in_tok, out_tok = extract_token_counts(response)
            parsed = _parse_json_lenient(response.text, stock_code)
            success_log = parsed is not None
            log_call(
                model=current_model, purpose="recommendation", stock_code=stock_code,
                input_tokens=in_tok, output_tokens=out_tok,
                latency_ms=latency_ms, success=success_log,
                error=None if success_log else "[PARSE_FAIL] truncated/invalid JSON",
            )
            if parsed is None:
                logger.warning(
                    "Parse failure on %s for %s; trying next model.",
                    current_model, stock_code,
                )
                attempts.append({
                    "model": current_model, "status": "parse_fail",
                    "latency_ms": latency_ms, "detail": "truncated/invalid JSON",
                })
                last_exc = RuntimeError("Truncated/invalid JSON from " + current_model)
                continue
            data = parsed
            used_model = current_model
            fallback = attempt_idx > 0
            attempts.append({
                "model": current_model, "status": "success",
                "latency_ms": latency_ms, "detail": "",
            })
            break
        except Exception as exc:
            latency_ms = int((_time.time() - t0) * 1000)
            quota = is_quota_error(exc)
            retriable = not quota and is_retriable_error(exc)
            tag = "[QUOTA] " if quota else ("[RETRY] " if retriable else "")
            log_call(
                model=current_model, purpose="recommendation", stock_code=stock_code,
                input_tokens=None, output_tokens=None,
                latency_ms=latency_ms, success=False,
                error=tag + str(exc)[:200],
            )
            attempts.append({
                "model": current_model,
                "status": "quota" if quota else ("unavailable" if retriable else "error"),
                "latency_ms": latency_ms,
                "detail": str(exc)[:120],
            })
            last_exc = exc
            if quota or retriable:
                logger.warning(
                    "%s on %s for %s, trying next model (%d remaining)",
                    "Quota" if quota else "Transient error (503/5xx)",
                    current_model, stock_code, len(chain) - attempt_idx - 1,
                )
                continue
            logger.exception("Fatal LLM error on %s for %s", current_model, stock_code)
            break

    if data is None:
        msg = f"{type(last_exc).__name__}: {str(last_exc)[:120]}" if last_exc else "no response"
        data = {
            "technical_analysis": "",
            "chip_analysis": "",
            "fundamental_analysis": "",
            "industry_analysis": "",
            "summary": f"全部 fallback 模型都失敗: {msg}",
            "risk": "可能配額全用完或網路問題,稍後重試。",
            "confidence": "low",
        }
        used_model = "(none)"

    return Recommendation(
        stock_code=stock_code,
        track=track,
        technical_analysis=_clean_text(data.get("technical_analysis", "")),
        chip_analysis=_clean_text(data.get("chip_analysis", "")),
        fundamental_analysis=_clean_text(data.get("fundamental_analysis", "")),
        industry_analysis=_clean_text(data.get("industry_analysis", "")),
        summary=_clean_text(data.get("summary", data.get("reason", ""))),
        risk=_clean_text(data.get("risk", "")),
        confidence=data.get("confidence", "medium"),
        model_used=used_model,
        fallback_used=fallback,
        attempts=attempts,
    )

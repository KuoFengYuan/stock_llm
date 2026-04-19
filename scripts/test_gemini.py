"""Smoke test: verify Gemini API connectivity with a Taiwan stock news sample."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stock_llm.llm.gemini import DEFAULT_BATCH_MODEL, get_client


SAMPLE_NEWS = """台積電(2330)今日公布第一季財報,合併營收新台幣8,392億元,
年增41.6%,毛利率58.8%,EPS 13.94元,均優於市場預期。公司看好 AI 需求
持續強勁,上調全年營收展望至中高雙位數成長,並維持先進製程擴廠計畫。"""

PROMPT = f"""你是台股研究分析師。請分析以下新聞的投資情緒與重點。

新聞內容:
{SAMPLE_NEWS}

請嚴格用以下 JSON 格式回覆 (不要加任何說明文字或 markdown):
{{
  "sentiment_score": <-1 到 +1 的浮點數>,
  "summary": "<50 字以內重點摘要>",
  "key_factors": ["<利多/利空因子 1>", "<因子 2>", ...]
}}"""


def main() -> None:
    print(">> 建立 Gemini client...")
    client = get_client()

    print(f">> 呼叫模型 {DEFAULT_BATCH_MODEL}...")
    response = client.models.generate_content(
        model=DEFAULT_BATCH_MODEL,
        contents=PROMPT,
    )

    text = response.text.strip()
    if text.startswith("```"):
        text = text.strip("`").lstrip("json").strip()

    print("\n=== 原始回應 ===")
    print(response.text)

    try:
        parsed = json.loads(text)
        print("\n=== 解析後 ===")
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        print("\n[OK] Gemini 連線成功,可以進入下一階段。")
    except json.JSONDecodeError as e:
        print(f"\n[WARN] JSON 解析失敗: {e}")
        print("連線本身 OK,只是模型沒回純 JSON。程式會再調整 prompt。")


if __name__ == "__main__":
    main()

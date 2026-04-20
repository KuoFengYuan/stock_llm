from __future__ import annotations

from google import genai

from stock_llm.config import get_gemini_api_key

MODEL_GEMMA_MOE = "gemma-4-26b-a4b-it"
MODEL_GEMMA_DENSE = "gemma-4-31b-it"

MODEL_FLASH_LITE = "gemini-3.1-flash-lite-preview"
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"

DEFAULT_BATCH_MODEL = MODEL_FLASH_LITE
DEFAULT_QUALITY_MODEL = MODEL_FLASH

DEFAULT_FALLBACK_CHAIN: list[str] = [
    MODEL_FLASH_LITE,
    MODEL_FLASH,
]


def get_client() -> genai.Client:
    return genai.Client(api_key=get_gemini_api_key())


def is_quota_error(exc: BaseException) -> bool:
    """Detect rate-limit / quota errors across HTTP 429, 402, and various SDK messages."""
    msg = str(exc).lower()
    return any(
        k in msg for k in (
            "429", "402", "quota", "rate limit", "rate_limit", "ratelimit",
            "resource has been exhausted", "too many requests",
            "exceeded your current quota", "payment required",
        )
    )


def is_retriable_error(exc: BaseException) -> bool:
    """Detect server-side transient errors that are worth falling back to another model.
    Covers 503 (overloaded), 500 (internal), 504 (gateway timeout), deadline exceeded.
    """
    msg = str(exc).lower()
    return any(
        k in msg for k in (
            "503", "500", "502", "504",
            "unavailable", "overloaded", "deadline exceeded",
            "internal error", "bad gateway",
        )
    )

"""LLM API usage tracking — logs each call to DuckDB for monitoring."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

from stock_llm.data.store import connect

logger = logging.getLogger(__name__)


MODEL_LIMITS: dict[str, dict[str, int]] = {
    "gemma-4-26b-a4b-it":              {"rpm": 30, "tpm": 30_000,  "rpd": 14_400},
    "gemma-4-31b-it":                  {"rpm": 10, "tpm": 10_000,  "rpd": 3_600},
    "gemini-3-flash-preview":          {"rpm": 10, "tpm": 250_000, "rpd": 1_500},
    "gemini-3.1-flash-lite-preview":   {"rpm": 30, "tpm": 300_000, "rpd": 14_400},
    "gemini-3.1-pro-preview":          {"rpm": 5,  "tpm": 250_000, "rpd": 100},
}


def log_call(
    model: str,
    purpose: str,
    stock_code: str | None,
    input_tokens: int | None,
    output_tokens: int | None,
    latency_ms: int,
    success: bool,
    error: str | None = None,
) -> None:
    """Insert one row into llm_usage. Errors are swallowed to never break the caller."""
    try:
        total = (input_tokens or 0) + (output_tokens or 0)
        with connect() as con:
            con.execute(
                """
                INSERT INTO llm_usage
                    (id, called_at, model, purpose, stock_code,
                     input_tokens, output_tokens, total_tokens,
                     latency_ms, success, error)
                VALUES (nextval('llm_usage_id_seq'), ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    datetime.now(), model, purpose, stock_code,
                    input_tokens, output_tokens, total,
                    latency_ms, success, error,
                ],
            )
    except Exception as exc:
        logger.warning("Failed to log LLM usage: %s", exc)


def usage_today_by_model() -> pd.DataFrame:
    with connect() as con:
        return con.execute(
            """
            SELECT model,
                   COUNT(*)                AS calls,
                   SUM(input_tokens)       AS in_tokens,
                   SUM(output_tokens)      AS out_tokens,
                   SUM(total_tokens)       AS total_tokens,
                   AVG(latency_ms)         AS avg_latency_ms,
                   SUM(CASE WHEN success THEN 0 ELSE 1 END) AS errors
            FROM llm_usage
            WHERE called_at >= CURRENT_DATE
            GROUP BY model
            ORDER BY calls DESC
            """
        ).fetchdf()


def usage_last_n_minutes(minutes: int = 60) -> pd.DataFrame:
    cutoff = datetime.now() - timedelta(minutes=minutes)
    with connect() as con:
        return con.execute(
            """
            SELECT model,
                   COUNT(*)               AS calls,
                   SUM(total_tokens)      AS total_tokens
            FROM llm_usage
            WHERE called_at >= ?
            GROUP BY model
            """,
            [cutoff],
        ).fetchdf()


def recent_calls(limit: int = 30) -> pd.DataFrame:
    with connect() as con:
        return con.execute(
            """
            SELECT called_at, model, purpose, stock_code,
                   total_tokens, latency_ms, success
            FROM llm_usage
            ORDER BY called_at DESC
            LIMIT ?
            """,
            [limit],
        ).fetchdf()


def usage_with_limits(
    only_used: bool = True,
    always_include: list[str] | None = None,
    primary: str | None = None,
) -> list[dict]:
    """Per-model usage vs estimated free-tier limits.

    Args:
        only_used: if True, hide models with zero calls today.
        always_include: models to force-include even if unused (e.g. current default).
        primary: model flagged as the current default — gets `is_primary=True` and
            is sorted to the top.
    """
    one_min_ago = datetime.now() - timedelta(minutes=1)
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

    with connect() as con:
        per_min = con.execute(
            """
            SELECT model, COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens
            FROM llm_usage WHERE called_at >= ? AND success = TRUE
            GROUP BY model
            """,
            [one_min_ago],
        ).fetchdf()
        per_day = con.execute(
            """
            SELECT model, COUNT(*) AS calls, COALESCE(SUM(total_tokens),0) AS tokens
            FROM llm_usage WHERE called_at >= ? AND success = TRUE
            GROUP BY model
            """,
            [today_start],
        ).fetchdf()

    used_models = set(per_day["model"].tolist()) | set(per_min["model"].tolist())
    force = set(always_include or [])
    if primary:
        force.add(primary)

    rows: list[dict] = []
    for model, limits in MODEL_LIMITS.items():
        if only_used and model not in used_models and model not in force:
            continue
        m = per_min[per_min["model"] == model]
        d = per_day[per_day["model"] == model]
        rpm = int(m["calls"].iloc[0]) if not m.empty else 0
        tpm = int(m["tokens"].iloc[0]) if not m.empty else 0
        rpd = int(d["calls"].iloc[0]) if not d.empty else 0
        rows.append({
            "model": model,
            "is_primary": model == primary,
            "rpm_used": rpm, "rpm_limit": limits["rpm"],
            "rpm_pct": min(rpm / limits["rpm"] * 100, 100) if limits["rpm"] else 0,
            "tpm_used": tpm, "tpm_limit": limits["tpm"],
            "tpm_pct": min(tpm / limits["tpm"] * 100, 100) if limits["tpm"] else 0,
            "rpd_used": rpd, "rpd_limit": limits["rpd"],
            "rpd_pct": min(rpd / limits["rpd"] * 100, 100) if limits["rpd"] else 0,
        })
    rows.sort(key=lambda r: (not r["is_primary"], -r["rpd_used"]))
    return rows


def extract_token_counts(response: Any) -> tuple[int | None, int | None]:
    """Pull (input_tokens, output_tokens) from a google-genai response object.

    The SDK exposes them under `usage_metadata` with fields
    `prompt_token_count` and `candidates_token_count`.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return None, None
    return (
        getattr(meta, "prompt_token_count", None),
        getattr(meta, "candidates_token_count", None),
    )

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
DB_PATH = DATA_DIR / "stock_llm.duckdb"

load_dotenv(PROJECT_ROOT / ".env")


def get_gemini_api_key() -> str:
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key or key == "your-gemini-api-key-here":
        raise RuntimeError(
            "GEMINI_API_KEY 未設定。\n"
            "  1. 複製 .env.example 為 .env\n"
            "  2. 填入從 https://aistudio.google.com/apikey 取得的 Key"
        )
    return key


def get_finmind_token() -> str:
    return os.getenv("FINMIND_TOKEN", "").strip()

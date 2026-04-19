from __future__ import annotations

from datetime import date

import pandas as pd

from stock_llm.features.chip import compute_chip_features
from stock_llm.features.fundamental import compute_fundamental_features
from stock_llm.features.sentiment import compute_sentiment_features
from stock_llm.features.technical import compute_technical_features


def build_feature_snapshot(
    as_of: date,
    stock_codes: list[str],
) -> pd.DataFrame:
    """Join technical, chip, fundamental and sentiment features into one row per stock.

    Fundamental features may be NaN for stocks not yet in FinMind.
    Sentiment defaults to 50 (neutral) for stocks with no scored news.
    """
    tech = compute_technical_features(as_of, stock_codes)
    chip = compute_chip_features(as_of, stock_codes)
    fund = compute_fundamental_features(as_of, stock_codes)
    sent = compute_sentiment_features(as_of, stock_codes)

    df = tech.merge(chip, on="stock_code", how="left")
    df = df.merge(fund, on="stock_code", how="left")
    df = df.merge(sent, on="stock_code", how="left")
    df["as_of_date"] = as_of
    return df

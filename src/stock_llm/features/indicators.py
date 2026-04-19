from __future__ import annotations

import numpy as np
import pandas as pd

INDICATOR_COLUMNS = [
    "stock_code", "trade_date",
    "ma5", "ma20", "ma60",
    "rsi14",
    "macd", "macd_signal", "macd_hist",
    "k9", "d9",
    "bb_upper", "bb_lower",
    "volume_ma5", "volume_ratio",
]


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_one(sub: pd.DataFrame) -> pd.DataFrame:
    close, high, low, volume = sub["close"], sub["high"], sub["low"], sub["volume"]

    ma5 = close.rolling(5).mean()
    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()

    rsi14 = _rsi(close)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    macd_signal = macd_line.ewm(span=9, adjust=False).mean()
    macd_hist = macd_line - macd_signal

    lowest = low.rolling(window=9, min_periods=1).min()
    highest = high.rolling(window=9, min_periods=1).max()
    rsv = (close - lowest) / (highest - lowest).replace(0, np.nan) * 100
    k9 = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d9 = k9.ewm(alpha=1 / 3, adjust=False).mean()

    mid = close.rolling(window=20).mean()
    std = close.rolling(window=20).std()
    bb_upper = mid + 2.0 * std
    bb_lower = mid - 2.0 * std

    volume_ma5 = volume.rolling(5).mean()
    volume_ratio = volume / volume_ma5.replace(0, np.nan)

    return pd.DataFrame({
        "stock_code": sub["stock_code"].values,
        "trade_date": sub["trade_date"].values,
        "ma5": ma5.values, "ma20": ma20.values, "ma60": ma60.values,
        "rsi14": rsi14.values,
        "macd": macd_line.values, "macd_signal": macd_signal.values, "macd_hist": macd_hist.values,
        "k9": k9.values, "d9": d9.values,
        "bb_upper": bb_upper.values, "bb_lower": bb_lower.values,
        "volume_ma5": volume_ma5.values, "volume_ratio": volume_ratio.values,
    })


def compute_indicators(prices: pd.DataFrame) -> pd.DataFrame:
    """Compute technical indicators grouped per stock.
    Input columns required: stock_code, trade_date, open, high, low, close, volume.
    """
    if prices.empty:
        return pd.DataFrame(columns=INDICATOR_COLUMNS)

    sorted_df = prices.sort_values(["stock_code", "trade_date"])
    out = [_compute_one(sub) for _, sub in sorted_df.groupby("stock_code", sort=False)]
    return pd.concat(out, ignore_index=True)[INDICATOR_COLUMNS]

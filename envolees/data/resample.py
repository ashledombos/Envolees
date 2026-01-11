"""
Resampling des données OHLCV.
"""

from __future__ import annotations

import pandas as pd


def resample_to_4h(df_1h: pd.DataFrame) -> pd.DataFrame:
    """
    Resample des données 1H vers 4H.

    Args:
        df_1h: DataFrame OHLCV en 1H

    Returns:
        DataFrame OHLCV en 4H
    """
    ohlcv = pd.DataFrame({
        "Open": df_1h["Open"].resample("4h").first(),
        "High": df_1h["High"].resample("4h").max(),
        "Low": df_1h["Low"].resample("4h").min(),
        "Close": df_1h["Close"].resample("4h").last(),
        "Volume": df_1h["Volume"].resample("4h").sum(),
    })
    return ohlcv.dropna()


def resample_to_timeframe(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """
    Resample générique vers un timeframe donné.

    Args:
        df: DataFrame OHLCV source
        timeframe: Timeframe cible (ex: "4h", "1d", "1w")

    Returns:
        DataFrame OHLCV resampleé
    """
    ohlcv = pd.DataFrame({
        "Open": df["Open"].resample(timeframe).first(),
        "High": df["High"].resample(timeframe).max(),
        "Low": df["Low"].resample(timeframe).min(),
        "Close": df["Close"].resample(timeframe).last(),
        "Volume": df["Volume"].resample(timeframe).sum(),
    })
    return ohlcv.dropna()

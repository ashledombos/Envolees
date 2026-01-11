"""
Average True Range (ATR) indicator.
"""

from __future__ import annotations

import pandas as pd


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calcule l'Average True Range (ATR).

    Args:
        df: DataFrame avec colonnes High, Low, Close
        period: Période de lissage (défaut: 14)

    Returns:
        Series ATR
    """
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    return tr.rolling(period, min_periods=period).mean()


def compute_atr_relative(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Calcule l'ATR relatif (ATR / Close).

    Args:
        df: DataFrame avec colonnes High, Low, Close
        period: Période de lissage (défaut: 14)

    Returns:
        Series ATR relatif (en pourcentage du prix)
    """
    atr = compute_atr(df, period)
    return atr / df["Close"]

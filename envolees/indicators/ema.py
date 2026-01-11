"""
Exponential Moving Average (EMA) indicator.
"""

from __future__ import annotations

import pandas as pd


def compute_ema(series: pd.Series, period: int = 200) -> pd.Series:
    """
    Calcule l'Exponential Moving Average (EMA).

    Args:
        series: Série de prix (typiquement Close)
        period: Période de l'EMA (défaut: 200)

    Returns:
        Series EMA
    """
    return series.ewm(span=period, adjust=False).mean()


def compute_sma(series: pd.Series, period: int = 200) -> pd.Series:
    """
    Calcule la Simple Moving Average (SMA).

    Args:
        series: Série de prix
        period: Période de la SMA (défaut: 200)

    Returns:
        Series SMA
    """
    return series.rolling(period, min_periods=period).mean()

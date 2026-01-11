"""
Donchian Channel indicator.
"""

from __future__ import annotations

import pandas as pd


def compute_donchian(df: pd.DataFrame, period: int = 20, shift: int = 1) -> tuple[pd.Series, pd.Series]:
    """
    Calcule le canal de Donchian.

    Args:
        df: DataFrame avec colonnes High, Low
        period: Période du canal (défaut: 20)
        shift: Décalage pour éviter le look-ahead bias (défaut: 1)

    Returns:
        Tuple (donchian_high, donchian_low)
    """
    d_high = df["High"].rolling(period, min_periods=period).max().shift(shift)
    d_low = df["Low"].rolling(period, min_periods=period).min().shift(shift)
    return d_high, d_low


def compute_donchian_mid(df: pd.DataFrame, period: int = 20, shift: int = 1) -> pd.Series:
    """
    Calcule la ligne médiane du canal de Donchian.

    Args:
        df: DataFrame avec colonnes High, Low
        period: Période du canal (défaut: 20)
        shift: Décalage (défaut: 1)

    Returns:
        Series médiane Donchian
    """
    d_high, d_low = compute_donchian(df, period, shift)
    return (d_high + d_low) / 2

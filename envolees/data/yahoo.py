"""
Téléchargement des données depuis Yahoo Finance.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

from envolees.config import Config

PARIS = ZoneInfo("Europe/Paris")


def download_1h(ticker: str, cfg: Config) -> pd.DataFrame:
    """
    Télécharge les données 1H depuis Yahoo Finance.

    Args:
        ticker: Symbole Yahoo Finance (ex: "EURUSD=X", "BTC-USD")
        cfg: Configuration du backtest

    Returns:
        DataFrame avec colonnes OHLCV, index tz-aware (Europe/Paris)

    Raises:
        RuntimeError: Si les données sont vides ou colonnes manquantes
    """
    df = yf.download(
        ticker,
        period=cfg.yf_period,
        interval=cfg.yf_interval,
        auto_adjust=False,
        progress=False,
    )

    if df.empty:
        raise RuntimeError(f"Yahoo Finance: aucune donnée pour {ticker}")

    # Gestion MultiIndex (yfinance peut retourner des colonnes multi-niveau)
    if isinstance(df.columns, pd.MultiIndex):
        if len(df.columns.get_level_values(-1).unique()) == 1:
            df.columns = df.columns.get_level_values(0)
        else:
            df = df.xs(ticker, axis=1, level=-1)

    # Timezone
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    df = df.tz_convert(PARIS)

    # Validation colonnes
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"Colonnes manquantes pour {ticker}: {sorted(missing)}")

    return df[["Open", "High", "Low", "Close", "Volume"]]

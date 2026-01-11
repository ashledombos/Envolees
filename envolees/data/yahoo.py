"""
Téléchargement des données depuis Yahoo Finance avec cache et alias.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf
from zoneinfo import ZoneInfo

from envolees.config import Config
from envolees.data.aliases import resolve_ticker
from envolees.data.cache import (
    get_cache_path,
    is_cache_valid,
    load_from_cache,
    save_to_cache,
)

PARIS = ZoneInfo("Europe/Paris")


def _download_raw(ticker: str, period: str, interval: str) -> pd.DataFrame:
    """Télécharge les données brutes depuis Yahoo Finance."""
    df = yf.download(
        ticker,
        period=period,
        interval=interval,
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

    return df


def _normalize_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Normalise le DataFrame (timezone, colonnes)."""
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


def download_1h(
    ticker: str,
    cfg: Config,
    use_cache: bool = True,
    cache_max_age_hours: float = 24.0,
    verbose: bool = False,
) -> pd.DataFrame:
    """
    Télécharge les données 1H depuis Yahoo Finance.

    Utilise le cache local si disponible et gère les alias de tickers.

    Args:
        ticker: Symbole ou alias (ex: "EURUSD", "GOLD", "BTC")
        cfg: Configuration du backtest
        use_cache: Utiliser le cache local (défaut: True)
        cache_max_age_hours: Durée de validité du cache en heures (défaut: 24)
        verbose: Afficher les messages de debug

    Returns:
        DataFrame avec colonnes OHLCV, index tz-aware (Europe/Paris)

    Raises:
        RuntimeError: Si aucune donnée disponible pour aucun alias
    """
    # Résoudre les alias
    candidates = resolve_ticker(ticker)
    
    last_error = None
    
    for candidate in candidates:
        cache_path = get_cache_path(candidate, cfg.yf_period, cfg.yf_interval, cfg)
        
        # Essayer le cache d'abord
        if use_cache and is_cache_valid(cache_path, cache_max_age_hours):
            df = load_from_cache(cache_path)
            if df is not None:
                if verbose:
                    print(f"[cache] {ticker} → {candidate} (depuis cache)")
                return _normalize_df(df, candidate)
        
        # Télécharger depuis Yahoo
        try:
            if verbose:
                print(f"[yahoo] {ticker} → {candidate} (téléchargement...)")
            
            df = _download_raw(candidate, cfg.yf_period, cfg.yf_interval)
            
            # Sauvegarder dans le cache
            if use_cache:
                save_to_cache(df, cache_path, candidate, cfg.yf_period, cfg.yf_interval)
            
            return _normalize_df(df, candidate)
            
        except Exception as e:
            last_error = e
            if verbose:
                print(f"[yahoo] {candidate} échoué: {e}")
            continue
    
    # Aucun candidat n'a fonctionné
    tried = ", ".join(candidates)
    raise RuntimeError(f"Yahoo Finance: aucune donnée pour {ticker} (essayé: {tried}). Dernière erreur: {last_error}")


def download_1h_no_cache(ticker: str, cfg: Config) -> pd.DataFrame:
    """
    Télécharge les données 1H sans utiliser le cache.
    
    Utile pour forcer le rafraîchissement des données.
    """
    return download_1h(ticker, cfg, use_cache=False)

"""
Pré-filtrage intelligent des tickers avant backtest complet.

Évite de backtester des instruments avec :
- Pas assez de données
- Volatilité nulle
- Pas assez de signaux potentiels
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import numpy as np

if TYPE_CHECKING:
    from envolees.config import Config


@dataclass
class PrefilterConfig:
    """Configuration du pré-filtre."""
    
    # Minimum de barres 4H
    min_bars_4h: int = 1500
    
    # ATR relatif minimum (éviter les tickers sans volatilité)
    min_atr_ratio: float = 0.001  # 0.1%
    
    # Signaux bruts minimum sur IS
    min_raw_signals_is: int = 30
    
    # Spread maximum (si disponible)
    max_spread_ratio: float = 0.01  # 1%
    
    @classmethod
    def from_env(cls) -> PrefilterConfig:
        """Charge depuis l'environnement."""
        return cls(
            min_bars_4h=int(os.getenv("PREFILTER_MIN_BARS", "1500")),
            min_atr_ratio=float(os.getenv("PREFILTER_MIN_ATR", "0.001")),
            min_raw_signals_is=int(os.getenv("PREFILTER_MIN_SIGNALS", "30")),
            max_spread_ratio=float(os.getenv("PREFILTER_MAX_SPREAD", "0.01")),
        )


@dataclass
class PrefilterResult:
    """Résultat du pré-filtre pour un ticker."""
    
    ticker: str
    passed: bool
    reason: str
    
    # Métriques
    bars_4h: int = 0
    atr_ratio: float = 0.0
    raw_signals: int = 0
    
    def __str__(self) -> str:
        status = "✓" if self.passed else "✗"
        return f"{status} {self.ticker}: {self.reason} (bars={self.bars_4h}, signals={self.raw_signals})"


# Blacklist de tickers problématiques
TICKER_BLACKLIST = {
    # Yahoo Finance problématiques
    "XAUUSD",  # Utiliser GC=F
    "XAGUSD",  # Utiliser SI=F
    # Tickers douteux
    "TEST", "DEMO", "SANDBOX",
}


# Whitelist par classe d'actifs (optionnel)
ASSET_WHITELISTS = {
    "fx": {
        "EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X", "USDCAD=X",
        "USDCHF=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X",
        "AUDJPY=X", "AUDNZD=X", "CADJPY=X", "CHFJPY=X", "EURAUD=X",
        "EURCHF=X", "EURCAD=X", "EURNZD=X", "GBPAUD=X", "GBPCHF=X",
        "GBPCAD=X", "GBPNZD=X", "NZDJPY=X", "AUDCAD=X", "CADCHF=X",
    },
    "crypto": {
        "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD",
        "DOGE-USD", "LTC-USD", "DOT-USD", "AVAX-USD", "MATIC-USD",
    },
    "index_us": {
        "^GSPC", "^NDX", "^DJI", "^RUT", "^VIX",
    },
    "index_eu": {
        "^GDAXI", "^FTSE", "^FCHI", "^STOXX50E", "^AEX",
    },
    "index_asia": {
        "^N225", "^HSI", "^SSEC", "^KS11", "^TWII",
    },
    "commodity": {
        "GC=F", "SI=F", "CL=F", "BZ=F", "NG=F",
        "HG=F", "PL=F", "PA=F", "ZW=F", "ZC=F",
    },
}


def is_blacklisted(ticker: str) -> bool:
    """Vérifie si un ticker est blacklisté."""
    ticker_upper = ticker.upper()
    
    for bl in TICKER_BLACKLIST:
        if bl in ticker_upper:
            return True
    
    return False


def count_raw_signals(
    df: pd.DataFrame,
    cfg: Config,
    split_ratio: float = 0.7,
) -> int:
    """
    Compte les signaux bruts potentiels sur l'IS.
    
    Signaux bruts = breakouts Donchian sans filtre EMA ni volatilité.
    C'est une estimation rapide, pas le nombre exact de trades.
    
    Args:
        df: DataFrame 4H avec OHLCV
        cfg: Configuration
        split_ratio: Ratio IS
    
    Returns:
        Nombre de signaux bruts
    """
    if len(df) < 100:
        return 0
    
    # Prendre uniquement IS
    cut = int(len(df) * split_ratio)
    df_is = df.iloc[:cut].copy()
    
    if len(df_is) < 50:
        return 0
    
    # Donchian simple
    n = cfg.donchian_n if hasattr(cfg, "donchian_n") else 20
    
    high_max = df_is["High"].rolling(n).max().shift(1)
    low_min = df_is["Low"].rolling(n).min().shift(1)
    
    # Breakouts
    breakout_up = df_is["Close"] > high_max
    breakout_down = df_is["Close"] < low_min
    
    return int(breakout_up.sum() + breakout_down.sum())


def compute_atr_ratio(df: pd.DataFrame, period: int = 14) -> float:
    """
    Calcule l'ATR ratio moyen (ATR / Close).
    
    Args:
        df: DataFrame avec OHLCV
        period: Période ATR
    
    Returns:
        ATR ratio moyen
    """
    if len(df) < period + 10:
        return 0.0
    
    high = df["High"]
    low = df["Low"]
    close = df["Close"]
    
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs(),
    ], axis=1).max(axis=1)
    
    atr = tr.rolling(period).mean()
    atr_ratio = (atr / close).dropna()
    
    return float(atr_ratio.mean()) if len(atr_ratio) > 0 else 0.0


def prefilter_ticker(
    ticker: str,
    df_4h: pd.DataFrame,
    cfg: Config,
    prefilter_cfg: PrefilterConfig | None = None,
) -> PrefilterResult:
    """
    Applique le pré-filtre sur un ticker.
    
    Args:
        ticker: Symbole
        df_4h: DataFrame 4H
        cfg: Configuration backtest
        prefilter_cfg: Configuration pré-filtre
    
    Returns:
        PrefilterResult
    """
    if prefilter_cfg is None:
        prefilter_cfg = PrefilterConfig.from_env()
    
    # 1. Blacklist
    if is_blacklisted(ticker):
        return PrefilterResult(
            ticker=ticker,
            passed=False,
            reason="blacklisted",
        )
    
    # 2. Données vides
    if df_4h is None or len(df_4h) == 0:
        return PrefilterResult(
            ticker=ticker,
            passed=False,
            reason="no data",
        )
    
    bars = len(df_4h)
    
    # 3. Minimum de barres
    if bars < prefilter_cfg.min_bars_4h:
        return PrefilterResult(
            ticker=ticker,
            passed=False,
            reason=f"insufficient bars ({bars} < {prefilter_cfg.min_bars_4h})",
            bars_4h=bars,
        )
    
    # 4. ATR ratio
    atr_ratio = compute_atr_ratio(df_4h)
    
    if atr_ratio < prefilter_cfg.min_atr_ratio:
        return PrefilterResult(
            ticker=ticker,
            passed=False,
            reason=f"low volatility (ATR {atr_ratio*100:.3f}% < {prefilter_cfg.min_atr_ratio*100:.2f}%)",
            bars_4h=bars,
            atr_ratio=atr_ratio,
        )
    
    # 5. Signaux bruts
    raw_signals = count_raw_signals(df_4h, cfg)
    
    if raw_signals < prefilter_cfg.min_raw_signals_is:
        return PrefilterResult(
            ticker=ticker,
            passed=False,
            reason=f"insufficient signals ({raw_signals} < {prefilter_cfg.min_raw_signals_is})",
            bars_4h=bars,
            atr_ratio=atr_ratio,
            raw_signals=raw_signals,
        )
    
    # Passé !
    return PrefilterResult(
        ticker=ticker,
        passed=True,
        reason="OK",
        bars_4h=bars,
        atr_ratio=atr_ratio,
        raw_signals=raw_signals,
    )


def prefilter_batch(
    tickers: list[str],
    data_loader: callable,
    cfg: Config,
    prefilter_cfg: PrefilterConfig | None = None,
    verbose: bool = False,
) -> tuple[list[str], list[PrefilterResult]]:
    """
    Applique le pré-filtre sur une liste de tickers.
    
    Args:
        tickers: Liste de tickers
        data_loader: Fonction (ticker) -> DataFrame 4H
        cfg: Configuration
        prefilter_cfg: Configuration pré-filtre
        verbose: Afficher les détails
    
    Returns:
        Tuple (tickers_passés, tous_résultats)
    """
    if prefilter_cfg is None:
        prefilter_cfg = PrefilterConfig.from_env()
    
    results = []
    passed = []
    
    for ticker in tickers:
        try:
            df_4h = data_loader(ticker)
            result = prefilter_ticker(ticker, df_4h, cfg, prefilter_cfg)
        except Exception as e:
            result = PrefilterResult(
                ticker=ticker,
                passed=False,
                reason=f"error: {e}",
            )
        
        results.append(result)
        
        if result.passed:
            passed.append(ticker)
        
        if verbose:
            print(result)
    
    return passed, results


def export_prefilter_results(
    results: list[PrefilterResult],
    output_path: Path | str,
) -> None:
    """
    Exporte les résultats du pré-filtre.
    
    Args:
        results: Liste de PrefilterResult
        output_path: Chemin de sortie (CSV)
    """
    data = [
        {
            "ticker": r.ticker,
            "passed": r.passed,
            "reason": r.reason,
            "bars_4h": r.bars_4h,
            "atr_ratio": r.atr_ratio,
            "raw_signals": r.raw_signals,
        }
        for r in results
    ]
    
    df = pd.DataFrame(data)
    df.to_csv(output_path, index=False)

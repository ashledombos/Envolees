"""
Split temporel des données pour validation In-Sample / Out-of-Sample.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from envolees.config import Config


SplitMode = Literal["", "none", "time"]
SplitTarget = Literal["", "is", "oos"]


@dataclass
class SplitInfo:
    """Information sur le split appliqué."""
    
    mode: str
    target: str
    ratio: float
    original_bars: int
    split_bars: int
    date_start: str
    date_end: str
    
    def __str__(self) -> str:
        if self.mode in ("", "none"):
            return f"No split ({self.original_bars} bars)"
        return (
            f"Split {self.mode} {self.ratio:.0%} → {self.target.upper()} "
            f"({self.split_bars}/{self.original_bars} bars, "
            f"{self.date_start} → {self.date_end})"
        )


def split_df_time(
    df: pd.DataFrame,
    ratio: float,
    target: SplitTarget,
) -> tuple[pd.DataFrame, SplitInfo]:
    """
    Split temporel sur l'index du DataFrame.
    
    Args:
        df: DataFrame avec index DatetimeIndex (trié croissant)
        ratio: Proportion pour l'in-sample (ex: 0.7 = 70% IS, 30% OOS)
        target: "is" pour in-sample, "oos" pour out-of-sample
    
    Returns:
        Tuple (DataFrame splitté, SplitInfo)
    """
    if df is None or len(df) == 0:
        return df, SplitInfo(
            mode="none",
            target="",
            ratio=ratio,
            original_bars=0,
            split_bars=0,
            date_start="",
            date_end="",
        )
    
    # S'assurer que l'index est trié
    df = df.sort_index()
    original_bars = len(df)
    
    # Point de coupure
    cut = int(len(df) * ratio)
    
    if cut <= 0 or cut >= len(df):
        # Ratio trop extrême, retourner tout
        return df, SplitInfo(
            mode="time",
            target=target or "all",
            ratio=ratio,
            original_bars=original_bars,
            split_bars=original_bars,
            date_start=str(df.index.min()),
            date_end=str(df.index.max()),
        )
    
    # Appliquer le split
    if target == "oos":
        result = df.iloc[cut:].copy()
    else:  # "is" ou défaut
        result = df.iloc[:cut].copy()
    
    return result, SplitInfo(
        mode="time",
        target=target or "is",
        ratio=ratio,
        original_bars=original_bars,
        split_bars=len(result),
        date_start=str(result.index.min()),
        date_end=str(result.index.max()),
    )


def apply_split(
    df: pd.DataFrame,
    cfg: Config,
) -> tuple[pd.DataFrame, SplitInfo | None]:
    """
    Applique le split selon la configuration.
    
    Args:
        df: DataFrame avec données OHLCV
        cfg: Configuration contenant split_mode, split_ratio, split_target
    
    Returns:
        Tuple (DataFrame splitté ou original, SplitInfo ou None)
    """
    mode = getattr(cfg, "split_mode", "").strip().lower()
    target = getattr(cfg, "split_target", "").strip().lower()
    
    # Si split_target est défini mais pas split_mode, inférer "time"
    if target in ("is", "oos") and mode in ("", "none"):
        mode = "time"
    
    if mode in ("", "none"):
        return df, None
    
    if mode == "time":
        ratio = getattr(cfg, "split_ratio", 0.7)
        
        # Valider le target
        if target not in ("is", "oos"):
            target = "is"
        
        return split_df_time(df, ratio, target)
    
    # Mode non reconnu
    return df, None


def get_split_boundaries(
    df: pd.DataFrame,
    ratio: float,
) -> dict:
    """
    Retourne les frontières du split sans l'appliquer.
    
    Utile pour afficher les dates IS/OOS avant de choisir.
    
    Args:
        df: DataFrame avec données
        ratio: Proportion IS (ex: 0.7)
    
    Returns:
        Dict avec dates de début/fin pour IS et OOS
    """
    if df is None or len(df) == 0:
        return {"is": None, "oos": None}
    
    df = df.sort_index()
    cut = int(len(df) * ratio)
    
    return {
        "is": {
            "start": str(df.index[0]),
            "end": str(df.index[cut - 1]) if cut > 0 else None,
            "bars": cut,
        },
        "oos": {
            "start": str(df.index[cut]) if cut < len(df) else None,
            "end": str(df.index[-1]),
            "bars": len(df) - cut,
        },
        "total_bars": len(df),
        "ratio": ratio,
    }

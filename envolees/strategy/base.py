"""
Base class for trading strategies.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from envolees.config import Config


Direction = Literal["LONG", "SHORT"]


@dataclass
class Signal:
    """Signal de trading généré par une stratégie."""

    direction: Direction
    entry_level: float
    atr_at_signal: float
    timestamp: pd.Timestamp
    expiry_bars: int = 1


@dataclass
class Position:
    """Position ouverte."""

    direction: Direction
    entry: float
    sl: float
    tp: float
    ts_signal: pd.Timestamp
    ts_entry: pd.Timestamp
    atr_signal: float
    entry_bar_idx: int
    risk_cash: float


class Strategy(ABC):
    """Classe abstraite pour les stratégies de trading."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    @abstractmethod
    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Ajoute les indicateurs nécessaires au DataFrame.

        Args:
            df: DataFrame OHLCV

        Returns:
            DataFrame enrichi avec les indicateurs
        """
        ...

    @abstractmethod
    def generate_signal(
        self,
        df: pd.DataFrame,
        bar_idx: int,
        current_position: Position | None,
        pending_signal: Signal | None,
    ) -> Signal | None:
        """
        Génère un signal de trading pour la barre courante.

        Args:
            df: DataFrame avec indicateurs
            bar_idx: Index de la barre courante
            current_position: Position ouverte (ou None)
            pending_signal: Signal en attente (ou None)

        Returns:
            Signal si conditions remplies, None sinon
        """
        ...

    @abstractmethod
    def compute_entry_sl_tp(
        self,
        signal: Signal,
        exec_penalty_atr: float,
    ) -> tuple[float, float, float]:
        """
        Calcule les niveaux d'entrée, SL et TP.

        Args:
            signal: Signal de trading
            exec_penalty_atr: Pénalité d'exécution en multiples d'ATR

        Returns:
            Tuple (entry, sl, tp)
        """
        ...

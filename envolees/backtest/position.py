"""
Gestion des positions et ordres en attente.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import pandas as pd

if TYPE_CHECKING:
    from envolees.config import Config
    from envolees.strategy.base import Direction, Signal


ExitReason = Literal["SL", "TP"]


@dataclass
class OpenPosition:
    """Position ouverte."""

    direction: Literal["LONG", "SHORT"]
    entry: float
    sl: float
    tp: float
    ts_signal: pd.Timestamp
    ts_entry: pd.Timestamp
    atr_signal: float
    entry_bar_idx: int
    risk_cash: float

    @property
    def risk_points(self) -> float:
        """Distance entry → SL en points."""
        return abs(self.entry - self.sl)

    def compute_pnl_r(self, exit_price: float) -> float:
        """Calcule le P&L en R-multiples."""
        if self.risk_points <= 0:
            return 0.0

        if self.direction == "LONG":
            pnl_points = exit_price - self.entry
        else:
            pnl_points = self.entry - exit_price

        return pnl_points / self.risk_points

    def compute_unrealized_r(self, current_price: float) -> float:
        """Calcule le P&L non réalisé en R."""
        return self.compute_pnl_r(current_price)

    def check_exit(
        self,
        high: float,
        low: float,
        conservative_same_bar: bool = True,
    ) -> tuple[ExitReason | None, float | None]:
        """
        Vérifie si SL ou TP est touché.

        Args:
            high: High de la bougie
            low: Low de la bougie
            conservative_same_bar: Si True, SL prioritaire si les deux sont touchés

        Returns:
            Tuple (exit_reason, exit_price) ou (None, None)
        """
        if self.direction == "LONG":
            hit_sl = low <= self.sl
            hit_tp = high >= self.tp
        else:
            hit_sl = high >= self.sl
            hit_tp = low <= self.tp

        # Convention conservative
        if hit_sl and hit_tp and conservative_same_bar:
            hit_tp = False

        if hit_sl:
            return "SL", self.sl
        if hit_tp:
            return "TP", self.tp

        return None, None


@dataclass
class PendingOrder:
    """Ordre en attente de déclenchement."""

    direction: Literal["LONG", "SHORT"]
    entry_level: float
    ts_signal: pd.Timestamp
    atr_signal: float
    expiry_bar_idx: int

    def is_expired(self, current_bar_idx: int) -> bool:
        """L'ordre a-t-il expiré ?"""
        return current_bar_idx > self.expiry_bar_idx

    def is_triggered(self, high: float, low: float) -> bool:
        """L'ordre est-il déclenché ?"""
        if self.direction == "LONG":
            return high >= self.entry_level
        return low <= self.entry_level

    @classmethod
    def from_signal(cls, signal: Signal, current_bar_idx: int) -> PendingOrder:
        """Crée un ordre en attente depuis un signal."""
        return cls(
            direction=signal.direction,
            entry_level=signal.entry_level,
            ts_signal=signal.timestamp,
            atr_signal=signal.atr_at_signal,
            expiry_bar_idx=current_bar_idx + signal.expiry_bars,
        )


@dataclass
class TradeRecord:
    """Enregistrement d'un trade clôturé."""

    ticker: str
    penalty_atr: float
    direction: Literal["LONG", "SHORT"]
    ts_signal: pd.Timestamp
    ts_entry: pd.Timestamp
    ts_exit: pd.Timestamp
    entry: float
    sl: float
    tp: float
    exit_price: float
    exit_reason: ExitReason
    atr_signal: float
    result_r: float
    result_cash: float
    balance_after: float
    duration_bars: int

    def to_dict(self) -> dict:
        """Convertit en dictionnaire pour export."""
        return {
            "ticker": self.ticker,
            "penalty_atr": self.penalty_atr,
            "direction": self.direction,
            "ts_signal": self.ts_signal,
            "ts_entry": self.ts_entry,
            "ts_exit": self.ts_exit,
            "entry": self.entry,
            "sl": self.sl,
            "tp": self.tp,
            "exit": self.exit_price,
            "exit_reason": self.exit_reason,
            "atr_signal": self.atr_signal,
            "result_r": self.result_r,
            "result_cash": self.result_cash,
            "balance_after": self.balance_after,
            "duration_bars": self.duration_bars,
        }

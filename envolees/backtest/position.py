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


ExitReason = Literal["SL", "TP", "TRAIL"]


@dataclass
class OpenPosition:
    """Position ouverte avec support trailing stop."""

    direction: Literal["LONG", "SHORT"]
    entry: float
    sl: float          # SL initial (filet de sécurité, ne bouge jamais)
    tp: float          # TP fixe (0 = désactivé)
    ts_signal: pd.Timestamp
    ts_entry: pd.Timestamp
    atr_signal: float
    entry_bar_idx: int
    risk_cash: float

    # Trailing stop
    best_price: float = 0.0          # Meilleur prix atteint (high pour LONG, low pour SHORT)
    trailing_sl: float = 0.0         # SL trailing courant (0 = pas encore actif)
    trailing_atr_dist: float = 0.0   # Distance trailing en points (trailing_atr × ATR)
    trailing_activation_price: float = 0.0  # Prix d'activation du trailing

    def __post_init__(self):
        if self.best_price == 0.0:
            self.best_price = self.entry
        if self.trailing_sl == 0.0:
            self.trailing_sl = self.sl  # Commence au SL initial

    @property
    def risk_points(self) -> float:
        """Distance entry → SL initial en points."""
        return abs(self.entry - self.sl)

    @property
    def effective_sl(self) -> float:
        """SL effectif : le plus protecteur entre initial et trailing."""
        if self.direction == "LONG":
            return max(self.sl, self.trailing_sl)
        else:
            if self.trailing_sl == 0.0:
                return self.sl
            return min(self.sl, self.trailing_sl)

    def update_trailing(self, high: float, low: float) -> None:
        """Met à jour le trailing stop avec les nouvelles données de prix.
        
        Le trailing ne bouge que dans la direction favorable (jamais en arrière).
        """
        if self.trailing_atr_dist <= 0:
            return  # Trailing désactivé

        if self.direction == "LONG":
            # Tracker le plus haut
            if high > self.best_price:
                self.best_price = high
            # Vérifier activation
            if self.trailing_activation_price > 0 and self.best_price < self.trailing_activation_price:
                return  # Pas encore activé
            # Nouveau trailing SL = best_price - distance
            new_trailing = self.best_price - self.trailing_atr_dist
            if new_trailing > self.trailing_sl:
                self.trailing_sl = new_trailing
        else:
            # Tracker le plus bas
            if self.best_price == 0.0 or low < self.best_price:
                self.best_price = low
            # Vérifier activation
            if self.trailing_activation_price > 0 and self.best_price > self.trailing_activation_price:
                return
            # Nouveau trailing SL = best_price + distance
            new_trailing = self.best_price + self.trailing_atr_dist
            if self.trailing_sl == 0.0 or new_trailing < self.trailing_sl:
                self.trailing_sl = new_trailing

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
        open_price: float | None = None,
    ) -> tuple[ExitReason | None, float | None]:
        """
        Vérifie si SL, TP ou trailing stop est touché.

        Séquence :
        1. Met à jour le trailing stop avec high/low
        2. Vérifie SL effectif (max du SL initial et trailing)
        3. Vérifie TP (si > 0)
        4. Si les deux touchés : heuristique ou conservateur

        Args:
            high: High de la bougie
            low: Low de la bougie
            conservative_same_bar: Si True et pas d'heuristique, SL prioritaire
            open_price: Open de la bougie (active l'heuristique de chemin)

        Returns:
            Tuple (exit_reason, exit_price) ou (None, None)
        """
        # 1. Mettre à jour le trailing
        self.update_trailing(high, low)

        eff_sl = self.effective_sl
        tp_active = self.tp != 0

        # Déterminer le type d'exit SL
        is_trailing_exit = (
            self.trailing_atr_dist > 0
            and eff_sl != self.sl
        )
        sl_reason: ExitReason = "TRAIL" if is_trailing_exit else "SL"

        # 2. Vérifier les hits
        if self.direction == "LONG":
            hit_sl = low <= eff_sl
            hit_tp = tp_active and high >= self.tp
        else:
            hit_sl = high >= eff_sl
            hit_tp = tp_active and low <= self.tp

        if hit_sl and hit_tp:
            if open_price is not None:
                # Heuristique de plausibilité du chemin (mode 4H)
                bar_range = high - low
                if bar_range > 0:
                    if self.direction == "LONG":
                        path_sl_first = max(0, open_price - eff_sl) + (self.tp - eff_sl)
                    else:
                        path_sl_first = max(0, eff_sl - open_price) + (eff_sl - self.tp)

                    if path_sl_first > 1.5 * bar_range:
                        hit_sl = False
                    else:
                        hit_tp = False
                else:
                    hit_tp = False
            elif conservative_same_bar:
                hit_tp = False

        if hit_sl:
            return sl_reason, eff_sl
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

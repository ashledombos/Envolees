"""
Simulation des règles prop firm (FTMO, GFT, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from envolees.config import Config


@dataclass
class DailyState:
    """État quotidien pour le tracking du drawdown."""

    current_day: date | None = None
    start_equity: float = 0.0
    min_equity: float = 0.0
    losses_closed: int = 0
    halted: bool = False

    def reset(self, day: date, equity: float) -> None:
        """Reset pour un nouveau jour."""
        self.current_day = day
        self.start_equity = equity
        self.min_equity = equity
        self.losses_closed = 0
        self.halted = False

    def update_min_equity(self, equity: float) -> None:
        """Met à jour le minimum equity du jour."""
        if equity < self.min_equity:
            self.min_equity = equity

    @property
    def daily_dd(self) -> float:
        """Drawdown quotidien en pourcentage."""
        if self.start_equity <= 0:
            return 0.0
        return (self.start_equity - self.min_equity) / self.start_equity


@dataclass
class PropSimulator:
    """
    Simulateur des règles prop firm.

    Gère :
    - Daily drawdown (mode close ou worst-case intrabar)
    - Kill-switch journalier
    - Limite de pertes consécutives
    - Tracking des violations FTMO/GFT
    """

    cfg: Config
    daily: DailyState = field(default_factory=DailyState)
    peak_equity: float = 0.0

    # Compteurs de violations (informatif)
    n_violate_ftmo_bars: int = 0
    n_violate_gft_bars: int = 0
    n_violate_total_bars: int = 0

    def __post_init__(self) -> None:
        self.peak_equity = self.cfg.start_balance

    def on_new_day(self, day: date, equity: float) -> None:
        """Appelé au changement de jour."""
        self.daily.reset(day, equity)

    def update_equity(self, equity: float, day: date) -> None:
        """
        Met à jour l'equity et vérifie les règles.

        Args:
            equity: Equity actuelle (mark-to-market)
            day: Date courante
        """
        # Changement de jour ?
        if self.daily.current_day is None or day != self.daily.current_day:
            self.on_new_day(day, equity)
            return

        # Update min equity
        self.daily.update_min_equity(equity)

        # Update peak
        if equity > self.peak_equity:
            self.peak_equity = equity

        # Check violations
        daily_dd = self.daily.daily_dd
        global_dd = self.global_dd(equity)

        if daily_dd > self.cfg.daily_dd_ftmo:
            self.n_violate_ftmo_bars += 1
        if daily_dd > self.cfg.daily_dd_gft:
            self.n_violate_gft_bars += 1
        if global_dd > self.cfg.max_loss:
            self.n_violate_total_bars += 1

        # Kill-switch
        if daily_dd >= self.cfg.daily_kill_switch:
            self.daily.halted = True

    def global_dd(self, equity: float) -> float:
        """Drawdown global depuis le peak."""
        if self.peak_equity <= 0:
            return 0.0
        return (self.peak_equity - equity) / self.peak_equity

    def on_trade_closed(self, result_r: float, balance: float) -> None:
        """Appelé à la clôture d'un trade."""
        if result_r < 0:
            self.daily.losses_closed += 1
            if self.daily.losses_closed >= self.cfg.stop_after_n_losses:
                self.daily.halted = True

        # Re-check daily DD après clôture
        self.daily.update_min_equity(balance)
        if self.daily.daily_dd >= self.cfg.daily_kill_switch:
            self.daily.halted = True

    @property
    def is_halted(self) -> bool:
        """Trading arrêté pour la journée ?"""
        return self.daily.halted

    def get_stats(self) -> dict:
        """Retourne les statistiques prop."""
        return {
            "n_violate_ftmo_bars": self.n_violate_ftmo_bars,
            "n_violate_gft_bars": self.n_violate_gft_bars,
            "n_violate_total_bars": self.n_violate_total_bars,
        }

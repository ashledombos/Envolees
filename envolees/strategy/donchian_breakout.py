"""
Stratégie Donchian Breakout avec filtre EMA et volatilité.
"""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from envolees.indicators import compute_atr, compute_donchian, compute_ema
from envolees.strategy.base import Direction, Position, Signal, Strategy

if TYPE_CHECKING:
    from envolees.config import Config


class DonchianBreakoutStrategy(Strategy):
    """
    Stratégie de breakout Donchian.

    - Filtre tendance : EMA200
    - Signal : breakout Donchian(N=20) + buffer 0.10×ATR
    - Filtre volatilité : ATR relatif < quantile 90%
    - Fenêtre sans trading : 22:30 - 06:30 Paris
    """

    def __init__(self, cfg: Config) -> None:
        super().__init__(cfg)

    def prepare_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ajoute EMA, ATR, Donchian et filtre volatilité."""
        df = df.copy()

        # EMA tendance
        df["EMA"] = compute_ema(df["Close"], self.cfg.ema_period)

        # ATR
        df["ATR"] = compute_atr(df, self.cfg.atr_period)
        df["ATR_rel"] = df["ATR"] / df["Close"]

        # Donchian channels (shifted pour éviter look-ahead)
        df["D_high"], df["D_low"] = compute_donchian(df, self.cfg.donchian_n, shift=1)

        # Filtre volatilité : quantile glissant
        df["ATR_rel_q"] = df["ATR_rel"].rolling(
            self.cfg.vol_window_bars,
            min_periods=self.cfg.vol_window_bars,
        ).quantile(self.cfg.vol_quantile)

        df["VOL_ok"] = df["ATR_rel"] <= df["ATR_rel_q"]

        return df

    def _in_no_trade_window(self, ts: pd.Timestamp) -> bool:
        """Vérifie si on est dans la fenêtre sans trading."""
        t = ts.time()
        start = self.cfg.no_trade_start
        end = self.cfg.no_trade_end

        if start <= end:
            return start <= t < end
        # Fenêtre à cheval sur minuit
        return t >= start or t < end

    def _indicators_ready(self, row: pd.Series) -> bool:
        """Vérifie que tous les indicateurs sont calculés."""
        return not any(
            np.isnan(row[col])
            for col in ["ATR", "D_high", "D_low", "ATR_rel_q", "EMA"]
        )

    def generate_signal(
        self,
        df: pd.DataFrame,
        bar_idx: int,
        current_position: Position | None,
        pending_signal: Signal | None,
    ) -> Signal | None:
        """Génère un signal de breakout si conditions remplies."""
        # Pas de nouveau signal si position ouverte ou signal en attente
        if current_position is not None or pending_signal is not None:
            return None

        row = df.iloc[bar_idx]
        ts = df.index[bar_idx]

        # Indicateurs prêts ?
        if not self._indicators_ready(row):
            return None

        # Fenêtre sans trading ?
        if self._in_no_trade_window(ts):
            return None

        # Filtre volatilité
        if not bool(row["VOL_ok"]):
            return None

        close = float(row["Close"])
        ema = float(row["EMA"])
        atr = float(row["ATR"])
        buffer = self.cfg.buffer_atr * atr
        d_high = float(row["D_high"])
        d_low = float(row["D_low"])

        # Signal LONG
        if close > ema and close > (d_high + buffer):
            return Signal(
                direction="LONG",
                entry_level=d_high + buffer,
                atr_at_signal=atr,
                timestamp=ts,
                expiry_bars=self.cfg.order_valid_bars,
            )

        # Signal SHORT
        if close < ema and close < (d_low - buffer):
            return Signal(
                direction="SHORT",
                entry_level=d_low - buffer,
                atr_at_signal=atr,
                timestamp=ts,
                expiry_bars=self.cfg.order_valid_bars,
            )

        return None

    def compute_entry_sl_tp(
        self,
        signal: Signal,
        exec_penalty_atr: float,
    ) -> tuple[float, float, float]:
        """Calcule entry, SL, TP avec pénalité d'exécution."""
        penalty = exec_penalty_atr * signal.atr_at_signal

        if signal.direction == "LONG":
            entry = signal.entry_level + penalty
            sl = entry - self.cfg.sl_atr * signal.atr_at_signal
            risk_points = entry - sl
            tp = entry + self.cfg.tp_r * risk_points
        else:
            entry = signal.entry_level - penalty
            sl = entry + self.cfg.sl_atr * signal.atr_at_signal
            risk_points = sl - entry
            tp = entry - self.cfg.tp_r * risk_points

        return entry, sl, tp

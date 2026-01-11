"""
Configuration du backtest — chargement .env et dataclasses.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import time
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv

# Charger .env depuis la racine du projet
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


DailyEquityMode = Literal["close", "worst"]


def _parse_time(s: str) -> time:
    """Parse 'HH:MM' → time."""
    h, m = map(int, s.split(":"))
    return time(h, m)


def _parse_bool(s: str) -> bool:
    return s.lower() in ("true", "1", "yes", "on")


def _parse_list(s: str) -> list[str]:
    """Parse 'a,b,c' → ['a', 'b', 'c']."""
    return [x.strip() for x in s.split(",") if x.strip()]


def _parse_float_list(s: str) -> list[float]:
    return [float(x.strip()) for x in s.split(",") if x.strip()]


@dataclass(frozen=True)
class Config:
    """Configuration complète du backtest."""

    # Capital / risque
    start_balance: float = 100_000.0
    risk_per_trade: float = 0.0025

    # Indicateurs
    ema_period: int = 200
    atr_period: int = 14
    donchian_n: int = 20
    buffer_atr: float = 0.10

    # Stops / objectifs
    sl_atr: float = 1.00
    tp_r: float = 1.00

    # Filtre volatilité
    vol_quantile: float = 0.90
    vol_window_bars: int = 1000

    # Fenêtre sans nouvelles décisions (Paris)
    no_trade_start: time = field(default_factory=lambda: time(22, 30))
    no_trade_end: time = field(default_factory=lambda: time(6, 30))

    # Ordre en attente : valable sur N bougies 4H
    order_valid_bars: int = 1

    # Convention conservative
    conservative_same_bar: bool = True

    # Prop simulation
    daily_dd_ftmo: float = 0.05
    daily_dd_gft: float = 0.04
    max_loss: float = 0.10
    stop_after_n_losses: int = 2
    daily_kill_switch: float = 0.04

    # Estimation daily DD
    daily_equity_mode: DailyEquityMode = "worst"

    # Yahoo Finance
    yf_period: str = "730d"
    yf_interval: str = "1h"

    # Output
    output_dir: str = "out"

    @classmethod
    def from_env(cls) -> Config:
        """Charge la config depuis les variables d'environnement."""
        return cls(
            start_balance=float(os.getenv("START_BALANCE", "100000")),
            risk_per_trade=float(os.getenv("RISK_PER_TRADE", "0.0025")),
            ema_period=int(os.getenv("EMA_PERIOD", "200")),
            atr_period=int(os.getenv("ATR_PERIOD", "14")),
            donchian_n=int(os.getenv("DONCHIAN_N", "20")),
            buffer_atr=float(os.getenv("BUFFER_ATR", "0.10")),
            sl_atr=float(os.getenv("SL_ATR", "1.00")),
            tp_r=float(os.getenv("TP_R", "1.00")),
            vol_quantile=float(os.getenv("VOL_QUANTILE", "0.90")),
            vol_window_bars=int(os.getenv("VOL_WINDOW_BARS", "1000")),
            no_trade_start=_parse_time(os.getenv("NO_TRADE_START", "22:30")),
            no_trade_end=_parse_time(os.getenv("NO_TRADE_END", "06:30")),
            order_valid_bars=int(os.getenv("ORDER_VALID_BARS", "1")),
            conservative_same_bar=_parse_bool(os.getenv("CONSERVATIVE_SAME_BAR", "true")),
            daily_dd_ftmo=float(os.getenv("DAILY_DD_FTMO", "0.05")),
            daily_dd_gft=float(os.getenv("DAILY_DD_GFT", "0.04")),
            max_loss=float(os.getenv("MAX_LOSS", "0.10")),
            stop_after_n_losses=int(os.getenv("STOP_AFTER_N_LOSSES", "2")),
            daily_kill_switch=float(os.getenv("DAILY_KILL_SWITCH", "0.04")),
            daily_equity_mode=os.getenv("DAILY_EQUITY_MODE", "worst"),  # type: ignore[arg-type]
            yf_period=os.getenv("YF_PERIOD", "730d"),
            yf_interval=os.getenv("YF_INTERVAL", "1h"),
            output_dir=os.getenv("OUTPUT_DIR", "out"),
        )


@dataclass(frozen=True)
class RunSpec:
    """Spécification d'un run de backtest."""

    ticker: str
    exec_penalty_atr: float


def get_tickers() -> list[str]:
    """Récupère la liste des tickers depuis .env."""
    raw = os.getenv("TICKERS", "")
    if not raw:
        # Fallback : portefeuille par défaut
        return [
            "EURUSD=X", "GBPUSD=X", "USDJPY=X",
            "BTC-USD", "ETH-USD",
            "^GSPC", "^NDX",
            "GC=F", "CL=F", "BZ=F",
        ]
    return _parse_list(raw)


def get_penalties() -> list[float]:
    """Récupère la liste des pénalités depuis .env."""
    raw = os.getenv("EXEC_PENALTIES", "")
    if not raw:
        return [0.05, 0.10, 0.15, 0.20, 0.25]
    return _parse_float_list(raw)

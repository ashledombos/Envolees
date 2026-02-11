"""
Configuration du backtest — chargement .env, secrets et profils.

VERSION MODIFIÉE: Ajout du support timeframe (1h/4h)
- Nouveau champ: timeframe
- Nouvelle variable .env: TIMEFRAME
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

# Charger les secrets (après .env, pour override)
try:
    from envolees.secrets import load_secrets
    load_secrets(_PROJECT_ROOT, strict=False)
except Exception:
    pass  # Secrets optionnels


DailyEquityMode = Literal["close", "worst"]
SplitMode = Literal["", "none", "time"]
SplitTarget = Literal["", "is", "oos"]
ProfileMode = Literal["default", "challenge", "funded", "conservative", "aggressive"]
Timeframe = Literal["1h", "4h"]  # ← NOUVEAU


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


def _get_profile_value(profile_name: str, key: str, env_key: str, default: float) -> float:
    """Récupère une valeur avec fallback sur le profil."""
    env_val = os.getenv(env_key, "")
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    
    try:
        from envolees.profiles import get_profile
        profile = get_profile(profile_name)
        return getattr(profile, key, default)
    except Exception:
        return default


def _parse_weights(prefix: str = "WEIGHT_") -> dict[str, float]:
    """
    Parse les variables WEIGHT_* depuis l'environnement.
    
    Supporte les alias (WEIGHT_BTC, WEIGHT_GOLD) qui seront mappés aux tickers réels.
    Les caractères spéciaux (=, -, ^) sont remplacés par _ dans les noms de variables.
    
    Exemples:
        WEIGHT_BTC=0.8         → {"BTC": 0.8}
        WEIGHT_EURUSD=1.0      → {"EURUSD": 1.0}
        WEIGHT_GSPC=0.9        → {"GSPC": 0.9}  (pour ^GSPC)
    """
    weights = {}
    for key, value in os.environ.items():
        if key.startswith(prefix):
            # Extraire l'alias (tout après WEIGHT_)
            alias = key[len(prefix):]
            try:
                weights[alias] = float(value)
            except ValueError:
                pass
    return weights


@dataclass(frozen=True)
class Config:
    """Configuration complète du backtest."""

    # Profil actif
    profile: ProfileMode = "default"

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

    # Proximité canal pour stop proactif (en multiples ATR)
    # Le signal est généré si le prix est à moins de proximity_atr × ATR
    # du bord du canal, AVANT le breakout (stop pré-placé)
    proximity_atr: float = 1.5

    # Filtre volatilité
    vol_quantile: float = 0.90
    vol_window_bars: int = 1000

    # Fenêtre sans nouvelles décisions (Paris)
    no_trade_start: time = field(default_factory=lambda: time(22, 30))
    no_trade_end: time = field(default_factory=lambda: time(6, 30))

    # Ordre en attente : valable sur N bougies
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

    # Split temporel (IS/OOS)
    split_mode: SplitMode = ""
    split_ratio: float = 0.70
    split_target: SplitTarget = ""

    # Yahoo Finance
    yf_period: str = "730d"
    yf_interval: str = "1h"
    
    # ══════════════════════════════════════════════════════════════════════════
    # NOUVEAU: Timeframe de trading
    # ══════════════════════════════════════════════════════════════════════════
    # Les données sont téléchargées en 1h (yf_interval) puis resampleées vers
    # ce timeframe. 
    # - "4h" = mode funded (conservateur, ~1-6 trades/jour par instrument)
    # - "1h" = mode challenge (plus agressif, ~4-24 trades/jour par instrument)
    timeframe: Timeframe = "4h"
    # ══════════════════════════════════════════════════════════════════════════

    # Cache
    cache_enabled: bool = True
    cache_dir: str = ""
    cache_max_age_hours: float = 24.0

    # Output
    output_dir: str = "out"

    # Pondérations par ticker (optionnel)
    weights: dict[str, float] = field(default_factory=dict)
    
    # Paramètres avancés de risque
    risk_mode: str = ""  # Alias pour profile (rétro-compatibilité)
    max_concurrent_trades: int = 0  # 0 = illimité
    daily_risk_budget: float = 0.0  # 0 = pas de limite
    
    # Shortlist
    shortlist_min_score: float = 0.0
    shortlist_max_tickers: int = 10
    min_trades_oos: int = 15
    dd_cap: float = 0.012

    @classmethod
    def from_env(cls) -> Config:
        """
        Charge la config depuis les variables d'environnement.
        
        Ordre de priorité :
        1. Variables d'environnement explicites
        2. Valeurs par défaut du profil (PROFILE ou RISK_MODE)
        3. Valeurs par défaut globales
        """
        # Déterminer le profil actif
        profile_name = os.getenv("PROFILE", os.getenv("RISK_MODE", "default")).strip().lower()
        
        return cls(
            profile=profile_name,  # type: ignore[arg-type]
            start_balance=float(os.getenv("START_BALANCE", "100000")),
            risk_per_trade=_get_profile_value(profile_name, "risk_per_trade", "RISK_PER_TRADE", 0.0025),
            ema_period=int(os.getenv("EMA_PERIOD", "200")),
            atr_period=int(os.getenv("ATR_PERIOD", "14")),
            donchian_n=int(os.getenv("DONCHIAN_N", "20")),
            buffer_atr=float(os.getenv("BUFFER_ATR", "0.10")),
            sl_atr=float(os.getenv("SL_ATR", "1.00")),
            tp_r=float(os.getenv("TP_R", "1.00")),
            proximity_atr=float(os.getenv("PROXIMITY_ATR", "1.5")),
            vol_quantile=float(os.getenv("VOL_QUANTILE", "0.90")),
            vol_window_bars=int(os.getenv("VOL_WINDOW_BARS", "1000")),
            no_trade_start=_parse_time(os.getenv("NO_TRADE_START", "22:30")),
            no_trade_end=_parse_time(os.getenv("NO_TRADE_END", "06:30")),
            order_valid_bars=int(os.getenv("ORDER_VALID_BARS", "1")),
            conservative_same_bar=_parse_bool(os.getenv("CONSERVATIVE_SAME_BAR", "true")),
            daily_dd_ftmo=float(os.getenv("DAILY_DD_FTMO", "0.05")),
            daily_dd_gft=float(os.getenv("DAILY_DD_GFT", "0.04")),
            max_loss=float(os.getenv("MAX_LOSS", "0.10")),
            stop_after_n_losses=int(_get_profile_value(profile_name, "stop_after_n_losses", "STOP_AFTER_N_LOSSES", 2)),
            daily_kill_switch=float(os.getenv("DAILY_KILL_SWITCH", "0.04")),
            daily_equity_mode=os.getenv("DAILY_EQUITY_MODE", os.getenv("MODE", "worst")),  # type: ignore[arg-type]
            split_mode=os.getenv("SPLIT_MODE", "").strip().lower(),  # type: ignore[arg-type]
            split_ratio=float(os.getenv("SPLIT_RATIO", "0.70")),
            split_target=os.getenv("SPLIT_TARGET", "").strip().lower(),  # type: ignore[arg-type]
            yf_period=os.getenv("YF_PERIOD", "730d"),
            yf_interval=os.getenv("YF_INTERVAL", "1h"),
            # ══════════════════════════════════════════════════════════════════
            # NOUVEAU: Charger le timeframe depuis .env
            # ══════════════════════════════════════════════════════════════════
            timeframe=os.getenv("TIMEFRAME", "4h").lower(),  # type: ignore[arg-type]
            # ══════════════════════════════════════════════════════════════════
            cache_enabled=_parse_bool(os.getenv("CACHE_ENABLED", "true")),
            cache_dir=os.getenv("CACHE_DIR", ""),
            cache_max_age_hours=_get_profile_value(profile_name, "cache_max_age_hours", "CACHE_MAX_AGE_HOURS", 24.0),
            output_dir=os.getenv("OUTPUT_DIR", "out"),
            weights=_parse_weights(),
            risk_mode=profile_name,
            max_concurrent_trades=int(_get_profile_value(profile_name, "max_concurrent_trades", "MAX_CONCURRENT_TRADES", 0)),
            daily_risk_budget=_get_profile_value(profile_name, "daily_risk_budget", "DAILY_RISK_BUDGET", 0.0),
            shortlist_min_score=_get_profile_value(profile_name, "shortlist_min_score", "SHORTLIST_MIN_SCORE", 0.0),
            shortlist_max_tickers=int(_get_profile_value(profile_name, "shortlist_max_tickers", "SHORTLIST_MAX_TICKERS", 10)),
            min_trades_oos=int(_get_profile_value(profile_name, "min_trades_oos", "MIN_TRADES_OOS", 15)),
            dd_cap=_get_profile_value(profile_name, "dd_cap", "DD_CAP", 0.012),
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
    # Supporter les deux noms : PENALTIES et EXEC_PENALTIES
    raw = os.getenv("PENALTIES", os.getenv("EXEC_PENALTIES", ""))
    if not raw:
        return [0.05, 0.10, 0.15, 0.20, 0.25]
    return _parse_float_list(raw)


def get_ticker_weight(ticker: str, cfg: Config) -> float:
    """
    Récupère le poids d'un ticker.
    
    Les poids sont définis via WEIGHT_<ALIAS>=<poids> dans .env.
    L'alias doit correspondre au ticker normalisé (sans =X, -USD, ^, =F).
    
    Exemples:
        WEIGHT_BTC=0.8     → s'applique à BTC-USD
        WEIGHT_EURUSD=1.0  → s'applique à EURUSD=X
        WEIGHT_GSPC=0.9    → s'applique à ^GSPC
        WEIGHT_GC=0.75     → s'applique à GC=F
    
    Args:
        ticker: Ticker Yahoo (ex: BTC-USD, ^GSPC, EURUSD=X)
        cfg: Configuration avec les poids
    
    Returns:
        Poids (défaut: 1.0)
    """
    if not cfg.weights:
        return 1.0
    
    # Normaliser le ticker pour matcher les clés de weights
    # BTC-USD → BTC, EURUSD=X → EURUSD, ^GSPC → GSPC, GC=F → GC
    normalized = ticker.replace("=X", "").replace("-USD", "").replace("=F", "").replace("^", "")
    
    # Essayer plusieurs variantes
    variants = [
        normalized,
        normalized.upper(),
        ticker,
        ticker.upper(),
    ]
    
    for v in variants:
        if v in cfg.weights:
            return cfg.weights[v]
    
    return 1.0

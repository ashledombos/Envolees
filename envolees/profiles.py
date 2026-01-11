"""
Profils de trading (challenge, funded, etc.).

Un profil définit les paramètres de risque et de sélection par défaut.
Les variables d'environnement peuvent surcharger ces valeurs.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal


ProfileName = Literal["challenge", "funded", "conservative", "aggressive", "default"]


@dataclass
class Profile:
    """Profil de trading avec paramètres de risque."""
    
    name: ProfileName
    description: str
    
    # Risque par trade
    risk_per_trade: float = 0.0025  # 0.25%
    
    # Budget risque journalier
    daily_risk_budget: float = 0.015  # 1.5%
    
    # Limites
    max_concurrent_trades: int = 4
    stop_after_n_losses: int = 3
    
    # Shortlist
    shortlist_min_score: float = 0.0
    shortlist_max_tickers: int = 10
    min_trades_oos: int = 15
    dd_cap: float = 0.012  # 1.2%
    
    # Pénalités préférées
    preferred_penalties: tuple[float, ...] = (0.15, 0.20, 0.25)
    
    # Cache
    cache_max_age_hours: float = 24.0


# Profils prédéfinis
PROFILES: dict[ProfileName, Profile] = {
    "challenge": Profile(
        name="challenge",
        description="Challenge prop firm (vitesse 5-10%)",
        risk_per_trade=0.006,  # 0.6%
        daily_risk_budget=0.015,  # 1.5%
        max_concurrent_trades=4,
        stop_after_n_losses=3,
        shortlist_min_score=0.62,
        shortlist_max_tickers=5,
        min_trades_oos=15,
        dd_cap=0.012,
        preferred_penalties=(0.15, 0.20, 0.25),
        cache_max_age_hours=12.0,
    ),
    "funded": Profile(
        name="funded",
        description="Compte funded (robustesse)",
        risk_per_trade=0.003,  # 0.3%
        daily_risk_budget=0.006,  # 0.6%
        max_concurrent_trades=2,
        stop_after_n_losses=2,
        shortlist_min_score=0.66,
        shortlist_max_tickers=4,
        min_trades_oos=15,
        dd_cap=0.010,
        preferred_penalties=(0.20, 0.25),
        cache_max_age_hours=24.0,
    ),
    "conservative": Profile(
        name="conservative",
        description="Ultra-conservateur",
        risk_per_trade=0.002,  # 0.2%
        daily_risk_budget=0.004,  # 0.4%
        max_concurrent_trades=1,
        stop_after_n_losses=1,
        shortlist_min_score=0.70,
        shortlist_max_tickers=3,
        min_trades_oos=20,
        dd_cap=0.008,
        preferred_penalties=(0.25,),
        cache_max_age_hours=24.0,
    ),
    "aggressive": Profile(
        name="aggressive",
        description="Agressif (casino)",
        risk_per_trade=0.010,  # 1%
        daily_risk_budget=0.030,  # 3%
        max_concurrent_trades=6,
        stop_after_n_losses=5,
        shortlist_min_score=0.50,
        shortlist_max_tickers=8,
        min_trades_oos=10,
        dd_cap=0.020,
        preferred_penalties=(0.10, 0.15, 0.20),
        cache_max_age_hours=12.0,
    ),
    "default": Profile(
        name="default",
        description="Profil par défaut (équilibré)",
        risk_per_trade=0.0025,
        daily_risk_budget=0.010,
        max_concurrent_trades=3,
        stop_after_n_losses=2,
        shortlist_min_score=0.0,
        shortlist_max_tickers=10,
        min_trades_oos=15,
        dd_cap=0.012,
        preferred_penalties=(0.15, 0.20, 0.25),
        cache_max_age_hours=24.0,
    ),
}


def get_profile(name: str | None = None) -> Profile:
    """
    Retourne un profil par son nom.
    
    Args:
        name: Nom du profil (challenge, funded, etc.)
              Si None, lit PROFILE depuis l'environnement
    
    Returns:
        Profile correspondant (ou default si non trouvé)
    """
    if name is None:
        name = os.getenv("PROFILE", "default").lower().strip()
    
    return PROFILES.get(name, PROFILES["default"])


def get_effective_value(
    env_var: str,
    profile_attr: str,
    profile: Profile | None = None,
    type_cast: type = float,
) -> float | int | str:
    """
    Retourne la valeur effective (env override ou profil).
    
    Ordre de priorité :
    1. Variable d'environnement si définie
    2. Valeur du profil
    
    Args:
        env_var: Nom de la variable d'environnement
        profile_attr: Attribut du profil
        profile: Profil à utiliser (ou auto-détecté)
        type_cast: Type de la valeur (float, int, str)
    
    Returns:
        Valeur effective
    """
    if profile is None:
        profile = get_profile()
    
    env_value = os.getenv(env_var)
    
    if env_value is not None:
        return type_cast(env_value)
    
    return getattr(profile, profile_attr, None)


def get_profile_summary(profile: Profile | None = None) -> dict:
    """
    Retourne un résumé du profil actif avec les valeurs effectives.
    
    Utile pour les logs et alertes.
    """
    if profile is None:
        profile = get_profile()
    
    return {
        "name": profile.name,
        "description": profile.description,
        "risk_per_trade": get_effective_value("RISK_PER_TRADE", "risk_per_trade", profile),
        "daily_risk_budget": get_effective_value("DAILY_RISK_BUDGET", "daily_risk_budget", profile),
        "max_concurrent_trades": get_effective_value("MAX_CONCURRENT_TRADES", "max_concurrent_trades", profile, int),
        "stop_after_n_losses": get_effective_value("STOP_AFTER_N_LOSSES", "stop_after_n_losses", profile, int),
        "shortlist_min_score": get_effective_value("SHORTLIST_MIN_SCORE", "shortlist_min_score", profile),
        "shortlist_max_tickers": get_effective_value("SHORTLIST_MAX_TICKERS", "shortlist_max_tickers", profile, int),
        "min_trades_oos": get_effective_value("MIN_TRADES_OOS", "min_trades_oos", profile, int),
        "dd_cap": get_effective_value("DD_CAP", "dd_cap", profile),
    }


def format_profile_for_alert(profile: Profile | None = None) -> str:
    """Formate le profil pour inclusion dans une alerte."""
    summary = get_profile_summary(profile)
    
    return (
        f"Profil: {summary['name']} ({summary['description']})\n"
        f"Risque/trade: {summary['risk_per_trade']*100:.2f}%\n"
        f"Budget/jour: {summary['daily_risk_budget']*100:.2f}%\n"
        f"Max trades: {summary['max_concurrent_trades']}\n"
        f"Stop après: {summary['stop_after_n_losses']} pertes"
    )

"""
Calendrier des heures de marché par classe d'actifs.

Utilisé pour distinguer les gaps normaux (fermeture marché) des vrais problèmes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum
from typing import Callable, TYPE_CHECKING
from zoneinfo import ZoneInfo

if TYPE_CHECKING:
    import pandas as pd


class AssetClass(Enum):
    """Classes d'actifs avec leurs règles de trading."""
    
    FX = "fx"
    CRYPTO = "crypto"
    INDEX_US = "index_us"
    INDEX_EU = "index_eu"
    INDEX_ASIA = "index_asia"
    COMMODITY = "commodity"
    UNKNOWN = "unknown"


# Timezones de référence
UTC = ZoneInfo("UTC")
NEW_YORK = ZoneInfo("America/New_York")
PARIS = ZoneInfo("Europe/Paris")
TOKYO = ZoneInfo("Asia/Tokyo")


@dataclass
class MarketHours:
    """Heures de marché pour une classe d'actifs."""
    
    asset_class: AssetClass
    
    # Heures d'ouverture/fermeture (heure locale du marché)
    open_time: time | None = None
    close_time: time | None = None
    timezone: ZoneInfo = UTC
    
    # Jours de fermeture (0=lundi, 6=dimanche)
    closed_days: tuple[int, ...] = ()
    
    # Tolérance pour les gaps (en heures)
    max_expected_gap_hours: float = 6.0
    
    # 24/7 ?
    is_24_7: bool = False


# Configuration par classe d'actifs
MARKET_HOURS: dict[AssetClass, MarketHours] = {
    AssetClass.FX: MarketHours(
        asset_class=AssetClass.FX,
        # FX : 24h du dimanche 22h UTC au vendredi 22h UTC
        # Fermé samedi et dimanche (sauf ouverture dimanche soir)
        closed_days=(5, 6),  # Samedi, Dimanche (partiellement)
        max_expected_gap_hours=60,  # Week-end = ~48h + marge
        timezone=UTC,
    ),
    AssetClass.CRYPTO: MarketHours(
        asset_class=AssetClass.CRYPTO,
        is_24_7=True,
        max_expected_gap_hours=4,  # Crypto devrait être quasi-continu
        timezone=UTC,
    ),
    AssetClass.INDEX_US: MarketHours(
        asset_class=AssetClass.INDEX_US,
        open_time=time(9, 30),
        close_time=time(16, 0),
        timezone=NEW_YORK,
        closed_days=(5, 6),
        max_expected_gap_hours=18,  # Nuit + possible jour férié
    ),
    AssetClass.INDEX_EU: MarketHours(
        asset_class=AssetClass.INDEX_EU,
        open_time=time(9, 0),
        close_time=time(17, 30),
        timezone=PARIS,
        closed_days=(5, 6),
        max_expected_gap_hours=18,
    ),
    AssetClass.INDEX_ASIA: MarketHours(
        asset_class=AssetClass.INDEX_ASIA,
        open_time=time(9, 0),
        close_time=time(15, 0),
        timezone=TOKYO,
        closed_days=(5, 6),
        max_expected_gap_hours=20,
    ),
    AssetClass.COMMODITY: MarketHours(
        asset_class=AssetClass.COMMODITY,
        # Futures : sessions avec pauses
        closed_days=(5, 6),
        max_expected_gap_hours=60,  # Week-end + sessions
        timezone=NEW_YORK,
    ),
    AssetClass.UNKNOWN: MarketHours(
        asset_class=AssetClass.UNKNOWN,
        max_expected_gap_hours=72,  # Tolérant par défaut
    ),
}


def classify_ticker(ticker: str) -> AssetClass:
    """
    Détermine la classe d'actifs d'un ticker.
    
    Args:
        ticker: Symbole Yahoo Finance
    
    Returns:
        AssetClass correspondante
    """
    ticker_upper = ticker.upper()
    
    # Crypto
    if "-USD" in ticker_upper or "-EUR" in ticker_upper:
        if any(c in ticker_upper for c in ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC"]):
            return AssetClass.CRYPTO
    
    # FX (forex)
    if "=X" in ticker_upper:
        return AssetClass.FX
    
    # Indices US
    if ticker_upper in ("^GSPC", "^NDX", "^DJI", "^VIX", "^RUT"):
        return AssetClass.INDEX_US
    
    # Indices EU
    if ticker_upper in ("^GDAXI", "^FTSE", "^FCHI", "^STOXX50E", "^AEX"):
        return AssetClass.INDEX_EU
    
    # Indices Asie
    if ticker_upper in ("^N225", "^HSI", "^SSEC", "^KS11", "^TWII"):
        return AssetClass.INDEX_ASIA
    
    # Commodities (futures)
    if "=F" in ticker_upper:
        return AssetClass.COMMODITY
    
    # Par défaut : inconnu (tolérant)
    return AssetClass.UNKNOWN


def get_market_hours(ticker: str) -> MarketHours:
    """Retourne les heures de marché pour un ticker."""
    asset_class = classify_ticker(ticker)
    return MARKET_HOURS.get(asset_class, MARKET_HOURS[AssetClass.UNKNOWN])


def is_gap_expected(
    ticker: str,
    gap_start: datetime,
    gap_end: datetime,
    gap_hours: float,
) -> tuple[bool, str]:
    """
    Détermine si un gap est attendu (normal) ou anormal.
    
    Args:
        ticker: Symbole
        gap_start: Début du gap
        gap_end: Fin du gap
        gap_hours: Durée du gap en heures
    
    Returns:
        Tuple (is_expected, reason)
    """
    market = get_market_hours(ticker)
    
    # Crypto 24/7 : tout gap > seuil est suspect
    if market.is_24_7:
        if gap_hours > market.max_expected_gap_hours:
            return False, f"crypto gap {gap_hours:.0f}h > {market.max_expected_gap_hours}h"
        return True, "crypto normal"
    
    # Vérifier si le gap chevauche un jour de fermeture
    current = gap_start
    while current < gap_end:
        if current.weekday() in market.closed_days:
            return True, "market closed (weekend/holiday)"
        current += timedelta(hours=1)
    
    # Gap pendant les heures de marché ?
    if market.open_time and market.close_time:
        gap_start_local = gap_start.astimezone(market.timezone)
        
        # Si le gap commence après la fermeture, c'est normal
        if gap_start_local.time() >= market.close_time:
            return True, "after market close"
        
        # Si le gap se termine avant l'ouverture, c'est normal
        if gap_start_local.time() < market.open_time:
            return True, "before market open"
    
    # Gap trop long dans tous les cas ?
    if gap_hours > market.max_expected_gap_hours:
        return False, f"gap {gap_hours:.0f}h > max {market.max_expected_gap_hours}h"
    
    return True, "within expected range"


def get_max_staleness_hours(ticker: str) -> float:
    """
    Retourne l'âge maximum acceptable pour la dernière bougie.
    
    Args:
        ticker: Symbole
    
    Returns:
        Heures maximum avant alerte "stale"
    """
    market = get_market_hours(ticker)
    
    if market.is_24_7:
        return 4  # Crypto : 4h max
    
    # Autres : dépend du marché
    # Week-end : jusqu'à 72h
    # Jour normal : 24h
    return 72 if datetime.now().weekday() in (5, 6) else 24


@dataclass
class GapAnalysis:
    """Résultat de l'analyse des gaps."""
    
    ticker: str
    total_gaps: int
    expected_gaps: int
    unexpected_gaps: int
    max_gap_hours: float
    issues: list[str]
    
    @property
    def has_issues(self) -> bool:
        return self.unexpected_gaps > 0


@dataclass
class StalenessCheck:
    """Résultat de la vérification de fraîcheur."""
    
    ticker: str
    last_bar: datetime | None
    age_hours: float  # Âge brut (pour affichage)
    max_age_hours: float
    is_stale: bool
    trading_hours_missed: float = 0.0  # Heures de trading réellement manquées
    
    @property
    def status(self) -> str:
        if self.is_stale:
            if self.trading_hours_missed > 0:
                return f"stale ({self.trading_hours_missed:.0f}h trading manquées)"
            return f"stale ({self.age_hours:.0f}h ago)"
        return f"fresh ({self.age_hours:.1f}h ago, {self.trading_hours_missed:.0f}h trading)"


def analyze_gaps(
    df: "pd.DataFrame",
    ticker: str,
    expected_interval_hours: float = 1.0,
) -> GapAnalysis:
    """
    Analyse les gaps dans les données en tenant compte du calendrier.
    
    Args:
        df: DataFrame avec index DatetimeIndex
        ticker: Symbole pour le calendrier
        expected_interval_hours: Intervalle attendu entre les barres
    
    Returns:
        GapAnalysis avec les détails
    """
    import pandas as pd
    
    if df is None or len(df) < 2:
        return GapAnalysis(
            ticker=ticker,
            total_gaps=0,
            expected_gaps=0,
            unexpected_gaps=0,
            max_gap_hours=0,
            issues=[],
        )
    
    # Calculer les gaps
    df = df.sort_index()
    gaps = df.index.to_series().diff().dropna()
    expected_td = pd.Timedelta(hours=expected_interval_hours)
    
    # Gaps > intervalle attendu
    significant_gaps = gaps[gaps > expected_td * 1.5]
    
    total_gaps = len(significant_gaps)
    expected_count = 0
    unexpected_count = 0
    max_gap_hours = 0.0
    issues = []
    
    for i, (idx, gap) in enumerate(significant_gaps.items()):
        gap_hours = gap.total_seconds() / 3600
        max_gap_hours = max(max_gap_hours, gap_hours)
        
        # Trouver le début du gap
        gap_start = df.index[df.index.get_loc(idx) - 1]
        gap_end = idx
        
        is_expected, reason = is_gap_expected(ticker, gap_start, gap_end, gap_hours)
        
        if is_expected:
            expected_count += 1
        else:
            unexpected_count += 1
            issues.append(f"{gap_start.strftime('%Y-%m-%d %H:%M')} - {gap_hours:.0f}h - {reason}")
    
    return GapAnalysis(
        ticker=ticker,
        total_gaps=total_gaps,
        expected_gaps=expected_count,
        unexpected_gaps=unexpected_count,
        max_gap_hours=max_gap_hours,
        issues=issues[:5],  # Limiter à 5 issues
    )


def check_staleness(df: "pd.DataFrame", ticker: str) -> StalenessCheck:
    """
    Vérifie la fraîcheur des données de manière calendar-aware.
    
    Pour FX le week-end, on ne considère pas les données comme stale
    car le marché est fermé. On calcule plutôt le retard par rapport
    à la dernière bougie attendue.
    
    Args:
        df: DataFrame avec index DatetimeIndex
        ticker: Symbole pour le calendrier
    
    Returns:
        StalenessCheck avec les détails
    """
    if df is None or len(df) == 0:
        return StalenessCheck(
            ticker=ticker,
            last_bar=None,
            age_hours=float("inf"),
            max_age_hours=24,
            is_stale=True,
        )
    
    last_bar = df.index.max()
    market = get_market_hours(ticker)
    
    # Calculer l'âge brut
    now = datetime.now(last_bar.tzinfo) if last_bar.tzinfo else datetime.now()
    raw_age = now - last_bar
    raw_age_hours = raw_age.total_seconds() / 3600
    
    # Crypto : simple, le marché est 24/7
    if market.is_24_7:
        max_age = 4  # 4h max pour crypto
        return StalenessCheck(
            ticker=ticker,
            last_bar=last_bar,
            age_hours=raw_age_hours,
            max_age_hours=max_age,
            is_stale=raw_age_hours > max_age,
        )
    
    # Pour les autres marchés : calculer les heures de marché ouvert manquées
    # au lieu de l'âge brut
    trading_hours_missed = _calculate_trading_hours_missed(last_bar, now, market)
    
    # Seuils selon la classe d'actif
    if market.asset_class == AssetClass.FX:
        max_age = 6  # FX : 6h de trading manquées max
    elif market.asset_class == AssetClass.COMMODITY:
        max_age = 8  # Commodities : un peu plus tolérant
    else:
        max_age = 12  # Indices : 12h
    
    return StalenessCheck(
        ticker=ticker,
        last_bar=last_bar,
        age_hours=raw_age_hours,  # On garde l'âge brut pour l'affichage
        max_age_hours=max_age,
        is_stale=trading_hours_missed > max_age,
        trading_hours_missed=trading_hours_missed,
    )


def _calculate_trading_hours_missed(
    last_bar: datetime,
    now: datetime,
    market: MarketHours,
) -> float:
    """
    Calcule le nombre d'heures de trading manquées entre last_bar et now.
    
    Pour FX le week-end, retourne 0 (pas d'heures de trading manquées).
    
    Returns:
        Heures de trading manquées
    """
    # Si le delta est petit, pas besoin de calcul complexe
    delta_hours = (now - last_bar).total_seconds() / 3600
    if delta_hours < 2:
        return delta_hours
    
    # FX : fermé du vendredi 22h UTC au dimanche 22h UTC
    if market.asset_class == AssetClass.FX:
        # Jours fermés = samedi et dimanche (partiellement)
        # On compte les heures de trading entre last_bar et now
        
        trading_hours = 0.0
        current = last_bar
        
        # Simplification : on compte heure par heure
        while current < now:
            weekday = current.weekday()
            hour = current.hour
            
            # FX ouvert : dimanche 22h → vendredi 22h (UTC)
            # Fermé : vendredi 22h → dimanche 22h
            is_open = True
            
            if weekday == 5:  # Samedi
                is_open = False
            elif weekday == 6:  # Dimanche
                is_open = hour >= 22  # Ouvert à partir de 22h
            elif weekday == 4:  # Vendredi
                is_open = hour < 22  # Fermé à partir de 22h
            
            if is_open:
                trading_hours += 1.0
            
            current += timedelta(hours=1)
        
        return trading_hours
    
    # Commodities : fermeture quotidienne + week-end
    if market.asset_class == AssetClass.COMMODITY:
        trading_hours = 0.0
        current = last_bar
        
        while current < now:
            weekday = current.weekday()
            hour = current.hour
            
            # GC=F (Gold) : ~23h/jour, fermé samedi + dimanche matin
            is_open = True
            
            if weekday == 5:  # Samedi
                is_open = False
            elif weekday == 6:  # Dimanche
                is_open = hour >= 18  # Ouverture vers 18h UTC
            
            if is_open:
                trading_hours += 1.0
            
            current += timedelta(hours=1)
        
        return trading_hours
    
    # Pour les indices : approximation simple
    # On retire les week-ends et compte 8h/jour
    full_days = int(delta_hours / 24)
    weekend_days = sum(
        1 for i in range(full_days)
        if (last_bar + timedelta(days=i)).weekday() >= 5
    )
    trading_days = full_days - weekend_days
    return trading_days * 8 + (delta_hours % 24) * (8/24)

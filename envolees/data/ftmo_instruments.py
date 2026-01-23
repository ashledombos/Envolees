"""
Mapping des instruments FTMO/GFT vers Yahoo Finance.

Ce fichier centralise :
- La liste complète des instruments tradables chez FTMO et Goat Funded Trader
- Le mapping vers les symboles Yahoo Finance équivalents
- La classification par classe d'actifs
- Les caractéristiques spécifiques (horaires, gaps tolérés, etc.)

Priorité d'usage :
1. Forex → Yahoo (qualité OK)
2. Crypto → Yahoo ou Binance (Yahoo a des gaps)
3. Métaux/Énergie → Yahoo futures (GC=F, CL=F)
4. Indices → Yahoo indices (^GSPC) - attention aux jours fériés
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class AssetType(Enum):
    """Types d'actifs pour la classification."""
    
    FOREX_MAJOR = "forex_major"
    FOREX_MINOR = "forex_minor"
    FOREX_EXOTIC = "forex_exotic"
    CRYPTO_MAJOR = "crypto_major"
    CRYPTO_ALTCOIN = "crypto_altcoin"
    METAL = "metal"
    ENERGY = "energy"
    AGRI = "agri"  # Commodités agricoles
    INDEX_US = "index_us"
    INDEX_EU = "index_eu"
    INDEX_ASIA = "index_asia"
    STOCK_US = "stock_us"
    STOCK_EU = "stock_eu"
    OTHER = "other"


@dataclass
class FTMOInstrument:
    """Définition d'un instrument FTMO."""
    
    # Nom FTMO (tel qu'affiché dans cTrader/MT5)
    ftmo_symbol: str
    
    # Symbole(s) Yahoo Finance à essayer (dans l'ordre de priorité)
    yahoo_symbols: list[str]
    
    # Classification
    asset_type: AssetType
    
    # Disponibilité
    available_ftmo: bool = True
    available_gft: bool = True
    
    # Trading 24/7 ? (crypto)
    is_24_7: bool = False
    
    # Gaps tolérés (au-delà du calendrier standard)
    max_extra_gaps: int = 0
    
    # Priorité pour la sélection (1=haute, 5=basse)
    priority: int = 3
    
    # Notes
    notes: str = ""


# =============================================================================
# FOREX - Paires majeures
# =============================================================================
FOREX_MAJORS: list[FTMOInstrument] = [
    FTMOInstrument("EURUSD", ["EURUSD=X"], AssetType.FOREX_MAJOR, priority=1),
    FTMOInstrument("GBPUSD", ["GBPUSD=X"], AssetType.FOREX_MAJOR, priority=1),
    FTMOInstrument("USDJPY", ["USDJPY=X"], AssetType.FOREX_MAJOR, priority=1),
    FTMOInstrument("USDCHF", ["USDCHF=X"], AssetType.FOREX_MAJOR, priority=1),
    FTMOInstrument("USDCAD", ["USDCAD=X"], AssetType.FOREX_MAJOR, priority=1),
    FTMOInstrument("AUDUSD", ["AUDUSD=X"], AssetType.FOREX_MAJOR, priority=1),
    FTMOInstrument("NZDUSD", ["NZDUSD=X"], AssetType.FOREX_MAJOR, priority=1),
]

# =============================================================================
# FOREX - Paires mineures (crosses)
# =============================================================================
FOREX_MINORS: list[FTMOInstrument] = [
    # EUR crosses
    FTMOInstrument("EURGBP", ["EURGBP=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("EURJPY", ["EURJPY=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("EURCHF", ["EURCHF=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("EURCAD", ["EURCAD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("EURAUD", ["EURAUD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("EURNZD", ["EURNZD=X"], AssetType.FOREX_MINOR, priority=2),
    
    # GBP crosses
    FTMOInstrument("GBPJPY", ["GBPJPY=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("GBPCHF", ["GBPCHF=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("GBPCAD", ["GBPCAD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("GBPAUD", ["GBPAUD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("GBPNZD", ["GBPNZD=X"], AssetType.FOREX_MINOR, priority=2),
    
    # JPY crosses
    FTMOInstrument("AUDJPY", ["AUDJPY=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("NZDJPY", ["NZDJPY=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("CADJPY", ["CADJPY=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("CHFJPY", ["CHFJPY=X"], AssetType.FOREX_MINOR, priority=2),
    
    # Autres crosses
    FTMOInstrument("AUDCAD", ["AUDCAD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("AUDCHF", ["AUDCHF=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("AUDNZD", ["AUDNZD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("CADCHF", ["CADCHF=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("NZDCAD", ["NZDCAD=X"], AssetType.FOREX_MINOR, priority=2),
    FTMOInstrument("NZDCHF", ["NZDCHF=X"], AssetType.FOREX_MINOR, priority=2),
]

# =============================================================================
# FOREX - Paires exotiques
# =============================================================================
FOREX_EXOTICS: list[FTMOInstrument] = [
    FTMOInstrument("USDCNH", ["USDCNH=X", "CNH=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDCZK", ["USDCZK=X", "CZK=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDHKD", ["USDHKD=X", "HKD=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDHUF", ["USDHUF=X", "HUF=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDMXN", ["USDMXN=X", "MXN=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDNOK", ["USDNOK=X", "NOK=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDPLN", ["USDPLN=X", "PLN=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDSEK", ["USDSEK=X", "SEK=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDSGD", ["USDSGD=X", "SGD=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDZAR", ["USDZAR=X", "ZAR=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("USDILS", ["USDILS=X", "ILS=X"], AssetType.FOREX_EXOTIC, priority=4),
    
    # EUR exotiques
    FTMOInstrument("EURCZK", ["EURCZK=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("EURHUF", ["EURHUF=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("EURNOK", ["EURNOK=X"], AssetType.FOREX_EXOTIC, priority=3),
    FTMOInstrument("EURPLN", ["EURPLN=X"], AssetType.FOREX_EXOTIC, priority=3),
]

# =============================================================================
# CRYPTO - Majeures
# =============================================================================
CRYPTO_MAJORS: list[FTMOInstrument] = [
    FTMOInstrument("BTCUSD", ["BTC-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=1, max_extra_gaps=3),
    FTMOInstrument("ETHUSD", ["ETH-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=1, max_extra_gaps=3),
    FTMOInstrument("LTCUSD", ["LTC-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("SOLUSD", ["SOL-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("XRPUSD", ["XRP-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("ADAUSD", ["ADA-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("DOGEUSD", ["DOGE-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("BNBUSD", ["BNB-USD"], AssetType.CRYPTO_MAJOR, is_24_7=True, priority=2, max_extra_gaps=3),
]

# =============================================================================
# CRYPTO - Altcoins
# =============================================================================
CRYPTO_ALTCOINS: list[FTMOInstrument] = [
    FTMOInstrument("XMRUSD", ["XMR-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("DASHUSD", ["DASH-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("NEOUSD", ["NEO-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("DOTUSD", ["DOT-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("UNIUSD", ["UNI-USD", "UNI1-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("XLMUSD", ["XLM-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("AAVEUSD", ["AAVE-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("MANAUSD", ["MANA-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("IMXUSD", ["IMX-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=4, max_extra_gaps=3),
    FTMOInstrument("GRTUSD", ["GRT-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=4, max_extra_gaps=3),
    FTMOInstrument("ETCUSD", ["ETC-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("ALGOUSD", ["ALGO-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("NEARUSD", ["NEAR-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("LNKUSD", ["LINK-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("AVAUSD", ["AVAX-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=2, max_extra_gaps=3),
    FTMOInstrument("XTZUSD", ["XTZ-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("FETUSD", ["FET-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("ICPUSD", ["ICP-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("SANDUSD", ["SAND-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("GALUSD", ["GAL-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=4, max_extra_gaps=3),
    FTMOInstrument("VETUSD", ["VET-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    FTMOInstrument("BCHUSD", ["BCH-USD"], AssetType.CRYPTO_ALTCOIN, is_24_7=True, priority=3, max_extra_gaps=3),
    # Note: BARUSD et SANUSD pas sur Yahoo
]

# =============================================================================
# MÉTAUX PRÉCIEUX
# =============================================================================
METALS: list[FTMOInstrument] = [
    FTMOInstrument("XAUUSD", ["GC=F", "XAUUSD=X"], AssetType.METAL, priority=1, notes="Gold - utiliser GC=F"),
    FTMOInstrument("XAGUSD", ["SI=F", "XAGUSD=X"], AssetType.METAL, priority=2, notes="Silver"),
    FTMOInstrument("XPDUSD", ["PA=F"], AssetType.METAL, priority=3, notes="Palladium"),
    FTMOInstrument("XPTUSD", ["PL=F"], AssetType.METAL, priority=3, notes="Platinum"),
    FTMOInstrument("XCUUSD", ["HG=F"], AssetType.METAL, priority=3, notes="Copper"),
    # Métaux en EUR - pas d'équivalent Yahoo direct
    FTMOInstrument("XAUEUR", ["GC=F"], AssetType.METAL, priority=4, notes="Gold EUR - approximation via GC=F"),
    FTMOInstrument("XAGEUR", ["SI=F"], AssetType.METAL, priority=4, notes="Silver EUR - approximation"),
    FTMOInstrument("XAGAUD", ["SI=F"], AssetType.METAL, priority=5, notes="Silver AUD - approximation"),
]

# =============================================================================
# ÉNERGIE
# =============================================================================
ENERGY: list[FTMOInstrument] = [
    FTMOInstrument("USOIL.cash", ["CL=F"], AssetType.ENERGY, priority=1, notes="WTI Crude"),
    FTMOInstrument("UKOIL.cash", ["BZ=F"], AssetType.ENERGY, priority=2, notes="Brent Crude"),
    FTMOInstrument("NATGAS.cash", ["NG=F"], AssetType.ENERGY, priority=2, notes="Natural Gas"),
    FTMOInstrument("HEATOIL.c", ["HO=F"], AssetType.ENERGY, priority=3, notes="Heating Oil"),
]

# =============================================================================
# COMMODITÉS AGRICOLES
# =============================================================================
AGRI: list[FTMOInstrument] = [
    FTMOInstrument("COCOA.c", ["CC=F"], AssetType.AGRI, priority=3),
    FTMOInstrument("COFFEE.c", ["KC=F"], AssetType.AGRI, priority=3),
    FTMOInstrument("CORN.c", ["ZC=F"], AssetType.AGRI, priority=3),
    FTMOInstrument("COTTON.c", ["CT=F"], AssetType.AGRI, priority=3),
    FTMOInstrument("SOYBEAN.c", ["ZS=F"], AssetType.AGRI, priority=3),
    FTMOInstrument("WHEAT.c", ["ZW=F"], AssetType.AGRI, priority=3),
    FTMOInstrument("SUGAR.c", ["SB=F"], AssetType.AGRI, priority=3),
]

# =============================================================================
# INDICES US
# =============================================================================
INDICES_US: list[FTMOInstrument] = [
    FTMOInstrument("US500.cash", ["^GSPC", "ES=F"], AssetType.INDEX_US, priority=2, max_extra_gaps=15, 
                   notes="S&P 500 - jours fériés US créent des gaps"),
    FTMOInstrument("US100.cash", ["^NDX", "NQ=F"], AssetType.INDEX_US, priority=2, max_extra_gaps=15,
                   notes="Nasdaq 100"),
    FTMOInstrument("US30.cash", ["^DJI", "YM=F"], AssetType.INDEX_US, priority=2, max_extra_gaps=15,
                   notes="Dow Jones"),
    FTMOInstrument("US2000.cash", ["^RUT"], AssetType.INDEX_US, priority=3, max_extra_gaps=15,
                   notes="Russell 2000"),
]

# =============================================================================
# INDICES EU
# =============================================================================
INDICES_EU: list[FTMOInstrument] = [
    FTMOInstrument("GER40.cash", ["^GDAXI"], AssetType.INDEX_EU, priority=2, max_extra_gaps=10),
    FTMOInstrument("UK100.cash", ["^FTSE"], AssetType.INDEX_EU, priority=2, max_extra_gaps=10),
    FTMOInstrument("FRA40.cash", ["^FCHI"], AssetType.INDEX_EU, priority=2, max_extra_gaps=10),
    FTMOInstrument("EU50.cash", ["^STOXX50E"], AssetType.INDEX_EU, priority=2, max_extra_gaps=10),
    FTMOInstrument("SPN35.cash", ["^IBEX"], AssetType.INDEX_EU, priority=3, max_extra_gaps=10),
    FTMOInstrument("N25.cash", ["^AEX"], AssetType.INDEX_EU, priority=3, max_extra_gaps=10),
]

# =============================================================================
# INDICES ASIE
# =============================================================================
INDICES_ASIA: list[FTMOInstrument] = [
    FTMOInstrument("JP225.cash", ["^N225"], AssetType.INDEX_ASIA, priority=2, max_extra_gaps=8),
    FTMOInstrument("HK50.cash", ["^HSI"], AssetType.INDEX_ASIA, priority=3, max_extra_gaps=8),
    FTMOInstrument("AUS200.cash", ["^AXJO"], AssetType.INDEX_ASIA, priority=3, max_extra_gaps=15),
]

# =============================================================================
# DOLLAR INDEX
# =============================================================================
OTHER: list[FTMOInstrument] = [
    FTMOInstrument("DXY.cash", ["DX-Y.NYB", "DX=F"], AssetType.OTHER, priority=2, notes="Dollar Index"),
]

# =============================================================================
# ACTIONS US (pour info - pas recommandé pour les prop firms)
# =============================================================================
STOCKS_US: list[FTMOInstrument] = [
    FTMOInstrument("AAPL", ["AAPL"], AssetType.STOCK_US, priority=4, max_extra_gaps=20,
                   notes="Actions = gaps fréquents, horaires limités"),
    FTMOInstrument("AMZN", ["AMZN"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("GOOG", ["GOOG"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("MSFT", ["MSFT"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("NFLX", ["NFLX"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("NVDA", ["NVDA"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("META", ["META"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("TSLA", ["TSLA"], AssetType.STOCK_US, priority=4, max_extra_gaps=20),
    FTMOInstrument("BAC", ["BAC"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("V", ["V"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("WMT", ["WMT"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("PFE", ["PFE"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("T", ["T"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("ZM", ["ZM"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("BABA", ["BABA"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
    FTMOInstrument("RACE", ["RACE"], AssetType.STOCK_US, priority=5, max_extra_gaps=20),
]

# =============================================================================
# ACTIONS EU (pour info - pas recommandé)
# =============================================================================
STOCKS_EU: list[FTMOInstrument] = [
    FTMOInstrument("LVMH", ["MC.PA"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
    FTMOInstrument("AIRF", ["AF.PA"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
    FTMOInstrument("ALVG", ["ALV.DE"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
    FTMOInstrument("BAYGn", ["BAYN.DE"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
    FTMOInstrument("DBKGn", ["DBK.DE"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
    FTMOInstrument("VOWG_p", ["VOW3.DE"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
    FTMOInstrument("IBE", ["IBE.MC"], AssetType.STOCK_EU, priority=5, max_extra_gaps=20),
]


# =============================================================================
# AGRÉGATION
# =============================================================================

ALL_INSTRUMENTS: list[FTMOInstrument] = (
    FOREX_MAJORS + FOREX_MINORS + FOREX_EXOTICS +
    CRYPTO_MAJORS + CRYPTO_ALTCOINS +
    METALS + ENERGY + AGRI +
    INDICES_US + INDICES_EU + INDICES_ASIA +
    OTHER +
    STOCKS_US + STOCKS_EU
)

# Index par symbole FTMO
_BY_FTMO_SYMBOL: dict[str, FTMOInstrument] = {}
# Index par symbole Yahoo
_BY_YAHOO_SYMBOL: dict[str, FTMOInstrument] = {}

def _build_indexes():
    """Construit les index de recherche."""
    global _BY_FTMO_SYMBOL, _BY_YAHOO_SYMBOL
    
    for inst in ALL_INSTRUMENTS:
        # Normaliser le nom FTMO (sans .cash, etc.)
        ftmo_clean = inst.ftmo_symbol.replace(".cash", "").replace(".c", "").upper()
        _BY_FTMO_SYMBOL[ftmo_clean] = inst
        _BY_FTMO_SYMBOL[inst.ftmo_symbol.upper()] = inst
        
        # Index par Yahoo
        for yahoo in inst.yahoo_symbols:
            _BY_YAHOO_SYMBOL[yahoo.upper()] = inst

_build_indexes()


def get_instrument_by_ftmo(ftmo_symbol: str) -> FTMOInstrument | None:
    """Retrouve un instrument par son symbole FTMO."""
    return _BY_FTMO_SYMBOL.get(ftmo_symbol.upper())


def get_instrument_by_yahoo(yahoo_symbol: str) -> FTMOInstrument | None:
    """Retrouve un instrument par son symbole Yahoo."""
    return _BY_YAHOO_SYMBOL.get(yahoo_symbol.upper())


def get_yahoo_symbols(ftmo_symbol: str) -> list[str]:
    """Retourne les symboles Yahoo pour un symbole FTMO."""
    inst = get_instrument_by_ftmo(ftmo_symbol)
    if inst:
        return inst.yahoo_symbols
    return [ftmo_symbol]  # Fallback: essayer tel quel


def get_max_extra_gaps(ticker: str) -> int:
    """Retourne le nombre de gaps supplémentaires tolérés pour un ticker."""
    # Essayer par Yahoo d'abord
    inst = get_instrument_by_yahoo(ticker)
    if inst:
        return inst.max_extra_gaps
    
    # Essayer par FTMO
    inst = get_instrument_by_ftmo(ticker)
    if inst:
        return inst.max_extra_gaps
    
    return 0  # Par défaut: strict


def get_recommended_instruments(
    include_crypto: bool = True,
    include_indices: bool = True,
    include_stocks: bool = False,
    max_priority: int = 3,
    gft_compatible: bool = False,
) -> list[FTMOInstrument]:
    """
    Retourne une liste d'instruments recommandés.
    
    Args:
        include_crypto: Inclure les crypto (attention aux gaps Yahoo)
        include_indices: Inclure les indices (attention aux jours fériés)
        include_stocks: Inclure les actions (pas recommandé)
        max_priority: Priorité maximum (1=core, 5=marginal)
        gft_compatible: Filtrer uniquement ceux dispo chez GFT
    
    Returns:
        Liste d'instruments triés par priorité
    """
    result = []
    
    for inst in ALL_INSTRUMENTS:
        # Filtre priorité
        if inst.priority > max_priority:
            continue
        
        # Filtre GFT
        if gft_compatible and not inst.available_gft:
            continue
        
        # Filtre par type
        if not include_crypto and inst.asset_type in (AssetType.CRYPTO_MAJOR, AssetType.CRYPTO_ALTCOIN):
            continue
        
        if not include_indices and inst.asset_type in (AssetType.INDEX_US, AssetType.INDEX_EU, AssetType.INDEX_ASIA):
            continue
        
        if not include_stocks and inst.asset_type in (AssetType.STOCK_US, AssetType.STOCK_EU):
            continue
        
        result.append(inst)
    
    # Trier par priorité
    return sorted(result, key=lambda x: x.priority)


def get_yahoo_ticker_list(
    include_crypto: bool = True,
    include_indices: bool = True,
    include_stocks: bool = False,
    max_priority: int = 3,
) -> list[str]:
    """
    Retourne la liste des symboles Yahoo à utiliser.
    
    Utilise le premier symbole Yahoo de chaque instrument.
    """
    instruments = get_recommended_instruments(
        include_crypto=include_crypto,
        include_indices=include_indices,
        include_stocks=include_stocks,
        max_priority=max_priority,
    )
    
    return [inst.yahoo_symbols[0] for inst in instruments if inst.yahoo_symbols]

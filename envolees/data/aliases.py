"""
Mapping d'alias pour les tickers Yahoo Finance.

Permet d'utiliser des noms plus intuitifs et gère les fallbacks automatiques.
"""

from __future__ import annotations

# Mapping alias → liste de tickers Yahoo à essayer (dans l'ordre)
TICKER_ALIASES: dict[str, list[str]] = {
    # Métaux précieux
    "XAUUSD": ["XAUUSD=X", "GC=F"],
    "GOLD": ["GC=F", "XAUUSD=X"],
    "XAGUSD": ["XAGUSD=X", "SI=F"],
    "SILVER": ["SI=F", "XAGUSD=X"],
    
    # Pétrole
    "WTI": ["CL=F"],
    "CRUDE": ["CL=F"],
    "BRENT": ["BZ=F"],
    "BCO": ["BZ=F"],
    
    # Forex (alias courts)
    "EURUSD": ["EURUSD=X"],
    "GBPUSD": ["GBPUSD=X"],
    "USDJPY": ["USDJPY=X"],
    "AUDUSD": ["AUDUSD=X"],
    "USDCAD": ["USDCAD=X"],
    "USDCHF": ["USDCHF=X"],
    "NZDUSD": ["NZDUSD=X"],
    "EURGBP": ["EURGBP=X"],
    "EURJPY": ["EURJPY=X"],
    "GBPJPY": ["GBPJPY=X"],
    
    # Crypto (alias courts)
    "BTC": ["BTC-USD"],
    "ETH": ["ETH-USD"],
    "SOL": ["SOL-USD"],
    "XRP": ["XRP-USD"],
    "ADA": ["ADA-USD"],
    
    # Indices (alias lisibles)
    "SP500": ["^GSPC"],
    "SPX": ["^GSPC"],
    "NASDAQ": ["^NDX"],
    "NDX": ["^NDX"],
    "DOW": ["^DJI"],
    "DJI": ["^DJI"],
    "DAX": ["^GDAXI"],
    "FTSE": ["^FTSE"],
    "NIKKEI": ["^N225"],
    "N225": ["^N225"],
    "JAP225": ["^N225"],
    "CAC40": ["^FCHI"],
}


def resolve_ticker(ticker: str) -> list[str]:
    """
    Résout un ticker en liste de tickers Yahoo à essayer.
    
    Args:
        ticker: Ticker ou alias (ex: "GOLD", "BTC", "EURUSD")
    
    Returns:
        Liste de tickers Yahoo à essayer dans l'ordre
    """
    # Normaliser (majuscules, sans espaces)
    normalized = ticker.strip().upper()
    
    # Si c'est un alias connu, retourner les alternatives
    if normalized in TICKER_ALIASES:
        return TICKER_ALIASES[normalized]
    
    # Sinon, essayer le ticker tel quel + quelques variantes
    candidates = [ticker]
    
    # Si pas de suffixe, essayer avec =X (forex)
    if "=" not in ticker and "-" not in ticker and "^" not in ticker:
        candidates.append(f"{ticker}=X")
    
    return candidates


def get_canonical_name(ticker: str) -> str:
    """
    Retourne un nom canonique pour le ticker (pour les fichiers de sortie).
    
    Args:
        ticker: Ticker Yahoo (ex: "EURUSD=X", "^GSPC")
    
    Returns:
        Nom nettoyé (ex: "EURUSD", "SP500")
    """
    # Mapping inverse pour les noms lisibles
    CANONICAL_NAMES = {
        "^GSPC": "SP500",
        "^NDX": "NASDAQ",
        "^DJI": "DOW",
        "^GDAXI": "DAX",
        "^FTSE": "FTSE",
        "^N225": "NIKKEI",
        "^FCHI": "CAC40",
        "GC=F": "GOLD",
        "SI=F": "SILVER",
        "CL=F": "WTI",
        "BZ=F": "BRENT",
    }
    
    if ticker in CANONICAL_NAMES:
        return CANONICAL_NAMES[ticker]
    
    # Nettoyer les suffixes
    clean = ticker.replace("=X", "").replace("-USD", "").replace("=F", "")
    return clean

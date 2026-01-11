"""
Cache local pour les données Yahoo Finance.

Évite de retélécharger les données à chaque exécution.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from envolees.config import Config

# Répertoire de cache par défaut
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "envolees"


def get_cache_dir(cfg: Config | None = None) -> Path:
    """Retourne le répertoire de cache."""
    if cfg and hasattr(cfg, "cache_dir") and cfg.cache_dir:
        cache_dir = Path(cfg.cache_dir)
    else:
        cache_dir = DEFAULT_CACHE_DIR
    
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_cache_key(ticker: str, period: str, interval: str) -> str:
    """Génère une clé de cache unique."""
    key_str = f"{ticker}_{period}_{interval}"
    return hashlib.md5(key_str.encode()).hexdigest()[:12]


def get_cache_path(ticker: str, period: str, interval: str, cfg: Config | None = None) -> Path:
    """Retourne le chemin du fichier cache."""
    cache_dir = get_cache_dir(cfg)
    key = get_cache_key(ticker, period, interval)
    # Nom lisible + hash pour unicité
    safe_ticker = ticker.replace("=", "_").replace("^", "_").replace("-", "_")
    return cache_dir / f"{safe_ticker}_{key}.parquet"


def get_metadata_path(cache_path: Path) -> Path:
    """Retourne le chemin du fichier de métadonnées."""
    return cache_path.with_suffix(".json")


def is_cache_valid(cache_path: Path, max_age_hours: float = 24.0) -> bool:
    """
    Vérifie si le cache est valide.
    
    Args:
        cache_path: Chemin du fichier cache
        max_age_hours: Âge maximum en heures (défaut: 24h)
    
    Returns:
        True si le cache existe et n'est pas expiré
    """
    if not cache_path.exists():
        return False
    
    meta_path = get_metadata_path(cache_path)
    if not meta_path.exists():
        return False
    
    try:
        with open(meta_path, "r") as f:
            meta = json.load(f)
        
        cached_at = datetime.fromisoformat(meta["cached_at"])
        age = datetime.now() - cached_at
        
        return age < timedelta(hours=max_age_hours)
    except (json.JSONDecodeError, KeyError, ValueError):
        return False


def load_from_cache(cache_path: Path) -> pd.DataFrame | None:
    """
    Charge les données depuis le cache.
    
    Args:
        cache_path: Chemin du fichier cache
    
    Returns:
        DataFrame ou None si échec
    """
    try:
        df = pd.read_parquet(cache_path)
        return df
    except Exception:
        return None


def save_to_cache(df: pd.DataFrame, cache_path: Path, ticker: str, period: str, interval: str) -> None:
    """
    Sauvegarde les données dans le cache.
    
    Args:
        df: DataFrame à sauvegarder
        cache_path: Chemin du fichier cache
        ticker: Ticker original
        period: Période demandée
        interval: Intervalle demandé
    """
    try:
        # Sauvegarder les données
        df.to_parquet(cache_path)
        
        # Sauvegarder les métadonnées
        meta = {
            "ticker": ticker,
            "period": period,
            "interval": interval,
            "cached_at": datetime.now().isoformat(),
            "rows": len(df),
            "date_range": {
                "start": str(df.index.min()) if len(df) > 0 else None,
                "end": str(df.index.max()) if len(df) > 0 else None,
            },
        }
        
        meta_path = get_metadata_path(cache_path)
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)
            
    except Exception as e:
        # Le cache est optionnel, on ne fait pas échouer l'exécution
        print(f"[cache] Warning: impossible de sauvegarder le cache: {e}")


def clear_cache(cfg: Config | None = None) -> int:
    """
    Vide le cache.
    
    Returns:
        Nombre de fichiers supprimés
    """
    cache_dir = get_cache_dir(cfg)
    count = 0
    
    for f in cache_dir.glob("*.parquet"):
        f.unlink()
        count += 1
    
    for f in cache_dir.glob("*.json"):
        f.unlink()
        count += 1
    
    return count


def cache_stats(cfg: Config | None = None) -> dict:
    """
    Retourne des statistiques sur le cache.
    
    Returns:
        Dict avec nb fichiers, taille totale, etc.
    """
    cache_dir = get_cache_dir(cfg)
    
    parquet_files = list(cache_dir.glob("*.parquet"))
    total_size = sum(f.stat().st_size for f in parquet_files)
    
    tickers = []
    for f in parquet_files:
        meta_path = get_metadata_path(f)
        if meta_path.exists():
            try:
                with open(meta_path, "r") as mf:
                    meta = json.load(mf)
                    tickers.append(meta.get("ticker", "?"))
            except Exception:
                pass
    
    return {
        "cache_dir": str(cache_dir),
        "n_files": len(parquet_files),
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "tickers": tickers,
    }

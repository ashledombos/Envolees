"""
Basket scoring et génération de shortlist.

Calcule un score agrégé par ticker et génère une shortlist des meilleurs candidats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from envolees.config import Config


@dataclass
class ScoringConfig:
    """Configuration du scoring."""
    
    # Poids des métriques dans le score final
    weight_expectancy: float = 0.35
    weight_pf: float = 0.25
    weight_stability: float = 0.20
    weight_dd: float = 0.20
    
    # Seuils pour la shortlist
    min_expectancy: float = 0.10  # ExpR minimum à la pénalité de référence
    min_pf: float = 1.2
    max_dd: float = 0.045  # 4.5%
    min_trades: int = 30
    
    # Pénalité de référence pour la shortlist
    reference_penalty: float = 0.25
    
    # Normalisation
    expectancy_cap: float = 0.50  # Plafonner pour éviter les outliers
    pf_cap: float = 3.0
    dd_floor: float = 0.01  # Minimum DD pour éviter division par 0


def compute_ticker_score(
    df: pd.DataFrame,
    ticker: str,
    scoring_cfg: ScoringConfig | None = None,
) -> dict:
    """
    Calcule un score agrégé pour un ticker sur toutes les pénalités.
    
    Le score combine :
    - Expectancy moyenne (pondérée vers les hautes pénalités)
    - Profit Factor moyen
    - Stabilité (faible variance de l'expectancy selon la pénalité)
    - Inverse du DDmax
    
    Args:
        df: DataFrame results.csv filtré pour ce ticker
        ticker: Nom du ticker
        scoring_cfg: Configuration du scoring
    
    Returns:
        Dict avec scores détaillés et score final
    """
    if scoring_cfg is None:
        scoring_cfg = ScoringConfig()
    
    if df.empty:
        return {
            "ticker": ticker,
            "score": 0.0,
            "expectancy_score": 0.0,
            "pf_score": 0.0,
            "stability_score": 0.0,
            "dd_score": 0.0,
            "avg_expectancy": 0.0,
            "avg_pf": 0.0,
            "max_dd": 0.0,
            "total_trades": 0,
            "penalties_tested": 0,
        }
    
    # Métriques de base
    avg_exp = df["expectancy_r"].mean()
    avg_pf = df["profit_factor"].mean()
    max_dd = df["max_daily_dd_pct"].max()
    total_trades = int(df["n_trades"].sum())
    
    # Score Expectancy (0-1, normalisé)
    exp_capped = min(avg_exp, scoring_cfg.expectancy_cap)
    expectancy_score = max(0, exp_capped / scoring_cfg.expectancy_cap)
    
    # Score PF (0-1, normalisé)
    pf_capped = min(avg_pf, scoring_cfg.pf_cap)
    pf_score = max(0, (pf_capped - 1) / (scoring_cfg.pf_cap - 1)) if pf_capped > 1 else 0
    
    # Score Stabilité (variance de l'expectancy selon pénalité)
    # Plus c'est stable, mieux c'est
    exp_std = df["expectancy_r"].std()
    if pd.isna(exp_std) or avg_exp <= 0:
        stability_score = 0.0
    else:
        # Coefficient de variation inversé
        cv = exp_std / max(abs(avg_exp), 0.01)
        stability_score = max(0, 1 - min(cv, 1))
    
    # Score DD (inverse, plafonné)
    dd_safe = max(max_dd, scoring_cfg.dd_floor)
    # 1% DD = score 1.0, 5% DD = score ~0.2
    dd_score = min(1.0, scoring_cfg.dd_floor / dd_safe)
    
    # Score final pondéré
    final_score = (
        scoring_cfg.weight_expectancy * expectancy_score +
        scoring_cfg.weight_pf * pf_score +
        scoring_cfg.weight_stability * stability_score +
        scoring_cfg.weight_dd * dd_score
    )
    
    return {
        "ticker": ticker,
        "score": round(final_score, 4),
        "expectancy_score": round(expectancy_score, 4),
        "pf_score": round(pf_score, 4),
        "stability_score": round(stability_score, 4),
        "dd_score": round(dd_score, 4),
        "avg_expectancy": round(avg_exp, 4),
        "avg_pf": round(avg_pf, 4),
        "max_dd": round(max_dd, 4),
        "total_trades": total_trades,
        "penalties_tested": len(df),
    }


def compute_all_scores(
    results_df: pd.DataFrame,
    scoring_cfg: ScoringConfig | None = None,
) -> pd.DataFrame:
    """
    Calcule les scores pour tous les tickers.
    
    Args:
        results_df: DataFrame complet de results.csv
        scoring_cfg: Configuration du scoring
    
    Returns:
        DataFrame avec un score par ticker, trié par score décroissant
    """
    if scoring_cfg is None:
        scoring_cfg = ScoringConfig()
    
    # Filtrer les erreurs
    df = results_df[results_df["status"] == "ok"].copy()
    
    scores = []
    for ticker in df["ticker"].unique():
        ticker_df = df[df["ticker"] == ticker]
        score = compute_ticker_score(ticker_df, ticker, scoring_cfg)
        scores.append(score)
    
    scores_df = pd.DataFrame(scores)
    
    if not scores_df.empty:
        scores_df = scores_df.sort_values("score", ascending=False).reset_index(drop=True)
    
    return scores_df


def generate_shortlist(
    results_df: pd.DataFrame,
    scoring_cfg: ScoringConfig | None = None,
) -> pd.DataFrame:
    """
    Génère une shortlist des meilleurs candidats pour production.
    
    Critères :
    - Expectancy > seuil à la pénalité de référence
    - PF > seuil
    - DDmax < seuil
    - Nombre de trades minimum
    
    Args:
        results_df: DataFrame complet de results.csv
        scoring_cfg: Configuration du scoring
    
    Returns:
        DataFrame shortlist avec les candidats prod
    """
    if scoring_cfg is None:
        scoring_cfg = ScoringConfig()
    
    # Filtrer les erreurs
    df = results_df[results_df["status"] == "ok"].copy()
    
    # Filtrer à la pénalité de référence
    ref_pen = scoring_cfg.reference_penalty
    df_ref = df[df["penalty_atr"] == ref_pen].copy()
    
    if df_ref.empty:
        # Fallback : prendre la pénalité la plus élevée disponible
        max_pen = df["penalty_atr"].max()
        df_ref = df[df["penalty_atr"] == max_pen].copy()
    
    # Appliquer les filtres
    shortlist = df_ref[
        (df_ref["expectancy_r"] >= scoring_cfg.min_expectancy) &
        (df_ref["profit_factor"] >= scoring_cfg.min_pf) &
        (df_ref["max_daily_dd_pct"] <= scoring_cfg.max_dd) &
        (df_ref["n_trades"] >= scoring_cfg.min_trades)
    ].copy()
    
    # Ajouter le score
    scores_df = compute_all_scores(results_df, scoring_cfg)
    if not scores_df.empty:
        score_map = dict(zip(scores_df["ticker"], scores_df["score"]))
        shortlist["score"] = shortlist["ticker"].map(score_map)
        shortlist = shortlist.sort_values("score", ascending=False)
    
    # Colonnes à garder
    cols = [
        "ticker", "score", "expectancy_r", "profit_factor", "win_rate",
        "max_daily_dd_pct", "n_trades", "penalty_atr",
    ]
    
    return shortlist[[c for c in cols if c in shortlist.columns]].reset_index(drop=True)


def export_scoring(
    results_df: pd.DataFrame,
    output_dir: str = "out",
    scoring_cfg: ScoringConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Exporte les scores et la shortlist.
    
    Crée :
    - {output_dir}/scores.csv : Score par ticker
    - {output_dir}/shortlist.csv : Candidats prod
    
    Args:
        results_df: DataFrame complet de results.csv
        output_dir: Répertoire de sortie
        scoring_cfg: Configuration du scoring
    
    Returns:
        Tuple (scores_df, shortlist_df)
    """
    from pathlib import Path
    
    if scoring_cfg is None:
        scoring_cfg = ScoringConfig()
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Scores
    scores_df = compute_all_scores(results_df, scoring_cfg)
    scores_df.to_csv(output_path / "scores.csv", index=False)
    
    # Shortlist
    shortlist_df = generate_shortlist(results_df, scoring_cfg)
    shortlist_df.to_csv(output_path / "shortlist.csv", index=False)
    
    return scores_df, shortlist_df

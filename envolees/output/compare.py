"""
Comparaison IS vs OOS et validation croisée.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pandas as pd


@dataclass
class OOSEligibility:
    """Critères d'éligibilité OOS."""
    
    min_trades: int = 15
    min_expectancy: float = 0.0
    min_pf: float = 1.2
    max_dd: float = 0.05
    
    # Dégradation acceptable IS → OOS
    max_expectancy_drop: float = 0.50  # 50% de drop max
    max_pf_drop: float = 0.40  # 40% de drop max


@dataclass
class TickerComparison:
    """Comparaison IS/OOS pour un ticker."""
    
    ticker: str
    penalty: float
    
    # IS metrics
    is_trades: int
    is_expectancy: float
    is_pf: float
    is_wr: float
    is_dd: float
    is_bars: int
    
    # OOS metrics
    oos_trades: int
    oos_expectancy: float
    oos_pf: float
    oos_wr: float
    oos_dd: float
    oos_bars: int
    
    # Status
    oos_status: str  # "valid", "insufficient_trades", "degraded", "failed"
    oos_notes: str
    
    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "penalty": self.penalty,
            "is_trades": self.is_trades,
            "is_expectancy": self.is_expectancy,
            "is_pf": self.is_pf,
            "is_wr": self.is_wr,
            "is_dd": self.is_dd,
            "is_bars": self.is_bars,
            "oos_trades": self.oos_trades,
            "oos_expectancy": self.oos_expectancy,
            "oos_pf": self.oos_pf,
            "oos_wr": self.oos_wr,
            "oos_dd": self.oos_dd,
            "oos_bars": self.oos_bars,
            "exp_delta": self.oos_expectancy - self.is_expectancy,
            "pf_delta": self.oos_pf - self.is_pf,
            "oos_status": self.oos_status,
            "oos_notes": self.oos_notes,
        }


def evaluate_oos_eligibility(
    is_row: pd.Series,
    oos_row: pd.Series,
    criteria: OOSEligibility | None = None,
) -> tuple[str, str]:
    """
    Évalue l'éligibilité OOS d'un ticker.
    
    Args:
        is_row: Ligne IS de results.csv
        oos_row: Ligne OOS de results.csv
        criteria: Critères d'éligibilité
    
    Returns:
        Tuple (status, notes)
    """
    if criteria is None:
        criteria = OOSEligibility()
    
    notes = []
    
    # 1. Nombre de trades suffisant ?
    if oos_row["n_trades"] < criteria.min_trades:
        return "insufficient_trades", f"OOS trades ({oos_row['n_trades']}) < {criteria.min_trades}"
    
    # 2. Expectancy positive ?
    if oos_row["expectancy_r"] < criteria.min_expectancy:
        notes.append(f"ExpR {oos_row['expectancy_r']:.3f} < {criteria.min_expectancy}")
    
    # 3. PF suffisant ?
    if oos_row["profit_factor"] < criteria.min_pf:
        notes.append(f"PF {oos_row['profit_factor']:.2f} < {criteria.min_pf}")
    
    # 4. DD acceptable ?
    if oos_row["max_daily_dd_pct"] > criteria.max_dd:
        notes.append(f"DD {oos_row['max_daily_dd_pct']*100:.1f}% > {criteria.max_dd*100:.0f}%")
    
    # 5. Dégradation IS → OOS acceptable ?
    if is_row["expectancy_r"] > 0:
        exp_drop = 1 - (oos_row["expectancy_r"] / is_row["expectancy_r"])
        if exp_drop > criteria.max_expectancy_drop:
            notes.append(f"ExpR drop {exp_drop*100:.0f}% > {criteria.max_expectancy_drop*100:.0f}%")
    
    if is_row["profit_factor"] > 1:
        pf_drop = 1 - ((oos_row["profit_factor"] - 1) / (is_row["profit_factor"] - 1))
        if pf_drop > criteria.max_pf_drop and oos_row["profit_factor"] < is_row["profit_factor"]:
            notes.append(f"PF drop significant")
    
    # Verdict
    if not notes:
        return "valid", "OOS validation passed"
    
    # Distinguer "degraded" (partiel) de "failed" (critique)
    critical = any(
        "ExpR" in n and "< 0" in n or
        "PF" in n and "< 1" in n
        for n in notes
    )
    
    if critical or len(notes) >= 3:
        return "failed", "; ".join(notes)
    
    return "degraded", "; ".join(notes)


def compare_is_oos(
    is_results_path: str | Path,
    oos_results_path: str | Path,
    criteria: OOSEligibility | None = None,
    penalty_filter: float | None = None,
) -> pd.DataFrame:
    """
    Compare les résultats IS et OOS.
    
    Args:
        is_results_path: Chemin vers results.csv IS
        oos_results_path: Chemin vers results.csv OOS
        criteria: Critères d'éligibilité OOS
        penalty_filter: Filtrer sur une pénalité spécifique
    
    Returns:
        DataFrame de comparaison
    """
    if criteria is None:
        criteria = OOSEligibility()
    
    is_df = pd.read_csv(is_results_path)
    oos_df = pd.read_csv(oos_results_path)
    
    # Filtrer les erreurs
    is_df = is_df[is_df["status"] == "ok"].copy()
    oos_df = oos_df[oos_df["status"] == "ok"].copy()
    
    # Filtrer par pénalité si demandé
    if penalty_filter is not None:
        is_df = is_df[is_df["penalty_atr"] == penalty_filter]
        oos_df = oos_df[oos_df["penalty_atr"] == penalty_filter]
    
    comparisons = []
    
    # Merger sur ticker + penalty
    for _, is_row in is_df.iterrows():
        ticker = is_row["ticker"]
        penalty = is_row["penalty_atr"]
        
        oos_match = oos_df[
            (oos_df["ticker"] == ticker) & 
            (oos_df["penalty_atr"] == penalty)
        ]
        
        if oos_match.empty:
            continue
        
        oos_row = oos_match.iloc[0]
        
        status, notes = evaluate_oos_eligibility(is_row, oos_row, criteria)
        
        comp = TickerComparison(
            ticker=ticker,
            penalty=penalty,
            is_trades=int(is_row["n_trades"]),
            is_expectancy=float(is_row["expectancy_r"]),
            is_pf=float(is_row["profit_factor"]),
            is_wr=float(is_row["win_rate"]),
            is_dd=float(is_row["max_daily_dd_pct"]),
            is_bars=int(is_row["bars_4h"]),
            oos_trades=int(oos_row["n_trades"]),
            oos_expectancy=float(oos_row["expectancy_r"]),
            oos_pf=float(oos_row["profit_factor"]),
            oos_wr=float(oos_row["win_rate"]),
            oos_dd=float(oos_row["max_daily_dd_pct"]),
            oos_bars=int(oos_row["bars_4h"]),
            oos_status=status,
            oos_notes=notes,
        )
        comparisons.append(comp.to_dict())
    
    return pd.DataFrame(comparisons)


def export_comparison(
    is_results_path: str | Path,
    oos_results_path: str | Path,
    output_path: str | Path,
    criteria: OOSEligibility | None = None,
    reference_penalty: float = 0.25,
) -> pd.DataFrame:
    """
    Exporte un rapport de comparaison IS/OOS.
    
    Crée:
    - comparison_full.csv : Toutes les pénalités
    - comparison_ref.csv : Pénalité de référence uniquement
    - validated.csv : Tickers validés OOS
    
    Args:
        is_results_path: Chemin vers results.csv IS
        oos_results_path: Chemin vers results.csv OOS
        output_path: Répertoire de sortie
        criteria: Critères d'éligibilité
        reference_penalty: Pénalité de référence
    
    Returns:
        DataFrame des tickers validés
    """
    output_path = Path(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Comparaison complète
    full_df = compare_is_oos(is_results_path, oos_results_path, criteria)
    full_df.to_csv(output_path / "comparison_full.csv", index=False)
    
    # Comparaison à la pénalité de référence
    ref_df = compare_is_oos(is_results_path, oos_results_path, criteria, reference_penalty)
    ref_df.to_csv(output_path / "comparison_ref.csv", index=False)
    
    # Tickers validés
    validated = ref_df[ref_df["oos_status"] == "valid"].copy()
    validated.to_csv(output_path / "validated.csv", index=False)
    
    return validated


def print_comparison_summary(comparison_df: pd.DataFrame) -> None:
    """Affiche un résumé de la comparaison."""
    if comparison_df.empty:
        print("Aucune comparaison disponible.")
        return
    
    total = len(comparison_df)
    valid = len(comparison_df[comparison_df["oos_status"] == "valid"])
    insufficient = len(comparison_df[comparison_df["oos_status"] == "insufficient_trades"])
    degraded = len(comparison_df[comparison_df["oos_status"] == "degraded"])
    failed = len(comparison_df[comparison_df["oos_status"] == "failed"])
    
    print(f"\n{'='*60}")
    print(f"COMPARAISON IS/OOS - {total} ticker×penalty")
    print(f"{'='*60}")
    print(f"  ✓ Valid:              {valid:>3} ({valid/total*100:.0f}%)")
    print(f"  ⚠ Insufficient trades: {insufficient:>3} ({insufficient/total*100:.0f}%)")
    print(f"  ~ Degraded:           {degraded:>3} ({degraded/total*100:.0f}%)")
    print(f"  ✗ Failed:             {failed:>3} ({failed/total*100:.0f}%)")
    print(f"{'='*60}")
    
    if valid > 0:
        print("\nTickers validés OOS:")
        for _, row in comparison_df[comparison_df["oos_status"] == "valid"].iterrows():
            print(
                f"  • {row['ticker']:>12} PEN {row['penalty']:.2f} │ "
                f"IS: {row['is_trades']:>3}t ExpR {row['is_expectancy']:+.3f} │ "
                f"OOS: {row['oos_trades']:>3}t ExpR {row['oos_expectancy']:+.3f}"
            )


@dataclass
class ShortlistConfig:
    """Configuration pour la génération de shortlist."""
    
    min_trades_oos: int = 15
    min_pf_oos: float = 1.2
    min_expectancy_oos: float = 0.0
    dd_cap: float = 0.012  # 1.2%
    
    # Poids du scoring
    weight_expectancy: float = 0.55
    weight_pf: float = 0.30
    weight_dd: float = 0.15
    
    # Limites
    min_score: float = 0.0
    max_tickers: int = 20
    
    @classmethod
    def from_env(cls) -> ShortlistConfig:
        """Charge depuis l'environnement."""
        import os
        return cls(
            min_trades_oos=int(os.getenv("MIN_TRADES_OOS", "15")),
            dd_cap=float(os.getenv("DD_CAP", "0.012")),
            min_score=float(os.getenv("SHORTLIST_MIN_SCORE", "0.0")),
            max_tickers=int(os.getenv("SHORTLIST_MAX_TICKERS", "20")),
        )


@dataclass
class TieredShortlistConfig:
    """Configuration pour la génération de shortlists par tier."""
    
    # Tier 1 (Funded) - critères stricts
    tier1_min_trades: int = 15
    
    # Tier 2 (Challenge) - critères assouplis
    tier2_min_trades: int = 10
    
    # Critères communs
    min_pf_oos: float = 1.2
    min_expectancy_oos: float = 0.0
    dd_cap: float = 0.012  # 1.2%
    
    # Poids du scoring
    weight_expectancy: float = 0.55
    weight_pf: float = 0.30
    weight_dd: float = 0.15
    
    # Limites
    min_score: float = 0.0
    max_tickers: int = 20
    
    @classmethod
    def from_env(cls) -> TieredShortlistConfig:
        """Charge depuis l'environnement."""
        import os
        return cls(
            tier1_min_trades=int(os.getenv("MIN_TRADES_TIER1", "15")),
            tier2_min_trades=int(os.getenv("MIN_TRADES_TIER2", "10")),
            dd_cap=float(os.getenv("DD_CAP", "0.012")),
            min_score=float(os.getenv("SHORTLIST_MIN_SCORE", "0.0")),
            max_tickers=int(os.getenv("SHORTLIST_MAX_TICKERS", "20")),
        )


def compute_oos_score(row: pd.Series, cfg: ShortlistConfig | TieredShortlistConfig) -> float:
    """
    Calcule le score OOS d'un ticker.
    
    score = w_exp * oos_expectancy + w_pf * log(oos_pf) - w_dd * oos_dd
    """
    import math
    
    exp_score = cfg.weight_expectancy * row["oos_expectancy"]
    pf_score = cfg.weight_pf * math.log(max(row["oos_pf"], 1e-9))
    dd_penalty = cfg.weight_dd * row["oos_dd"]
    
    return exp_score + pf_score - dd_penalty


def shortlist_from_compare(
    comparison_path: str | Path,
    cfg: ShortlistConfig | None = None,
) -> pd.DataFrame:
    """
    Génère une shortlist tradable depuis les résultats de comparaison.
    
    Règle (OOS-first, robuste) :
    1. filter: oos_trades >= min_trades
    2. filter: oos_pf >= 1.2 et oos_expectancy > 0
    3. filter: oos_dd <= dd_cap
    4. score: 0.55*exp + 0.30*log(pf) - 0.15*dd
    5. tri décroissant, top N
    
    Args:
        comparison_path: Chemin vers comparison_ref.csv
        cfg: Configuration de shortlist
    
    Returns:
        DataFrame trié par score décroissant
    """
    if cfg is None:
        cfg = ShortlistConfig.from_env()
    
    df = pd.read_csv(comparison_path)
    
    # Filtres
    df = df[df["oos_trades"] >= cfg.min_trades_oos].copy()
    df = df[df["oos_pf"] >= cfg.min_pf_oos].copy()
    df = df[df["oos_expectancy"] > cfg.min_expectancy_oos].copy()
    df = df[df["oos_dd"] <= cfg.dd_cap].copy()
    
    if df.empty:
        return pd.DataFrame()
    
    # Scoring
    df["oos_score"] = df.apply(lambda r: compute_oos_score(r, cfg), axis=1)
    
    # Filtre score minimum
    if cfg.min_score > 0:
        df = df[df["oos_score"] >= cfg.min_score].copy()
    
    # Tri et limite
    df = df.sort_values("oos_score", ascending=False)
    df = df.head(cfg.max_tickers)
    
    return df.reset_index(drop=True)


def export_shortlist(
    comparison_path: str | Path,
    output_path: str | Path,
    cfg: ShortlistConfig | None = None,
) -> pd.DataFrame:
    """
    Exporte la shortlist tradable.
    
    Args:
        comparison_path: Chemin vers comparison_ref.csv
        output_path: Chemin de sortie
        cfg: Configuration
    
    Returns:
        DataFrame de la shortlist
    """
    shortlist = shortlist_from_compare(comparison_path, cfg)
    
    if not shortlist.empty:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Colonnes à exporter
        cols = [
            "ticker", "penalty", "oos_score",
            "oos_trades", "oos_expectancy", "oos_pf", "oos_wr", "oos_dd",
            "is_trades", "is_expectancy", "is_pf",
        ]
        shortlist[[c for c in cols if c in shortlist.columns]].to_csv(output_path, index=False)
    
    return shortlist


def _generate_shortlist_for_tier(
    df: pd.DataFrame,
    min_trades: int,
    cfg: TieredShortlistConfig,
    exclude_tickers: list[str] | None = None,
) -> pd.DataFrame:
    """
    Génère une shortlist pour un tier spécifique.
    
    Args:
        df: DataFrame de comparaison
        min_trades: Minimum de trades OOS requis
        cfg: Configuration
        exclude_tickers: Tickers à exclure (déjà dans un tier supérieur)
    
    Returns:
        DataFrame trié par score décroissant
    """
    filtered = df.copy()
    
    # Exclure les tickers déjà sélectionnés
    if exclude_tickers:
        filtered = filtered[~filtered["ticker"].isin(exclude_tickers)]
    
    # Filtres
    filtered = filtered[filtered["oos_trades"] >= min_trades]
    filtered = filtered[filtered["oos_pf"] >= cfg.min_pf_oos]
    filtered = filtered[filtered["oos_expectancy"] > cfg.min_expectancy_oos]
    filtered = filtered[filtered["oos_dd"] <= cfg.dd_cap]
    
    # Aussi vérifier le DD sur IS (sinon on risque l'overfitting)
    filtered = filtered[filtered["is_dd"] <= cfg.dd_cap]
    
    if filtered.empty:
        return pd.DataFrame()
    
    # Scoring
    filtered["oos_score"] = filtered.apply(lambda r: compute_oos_score(r, cfg), axis=1)
    
    # Filtre score minimum
    if cfg.min_score > 0:
        filtered = filtered[filtered["oos_score"] >= cfg.min_score]
    
    # Tri
    filtered = filtered.sort_values("oos_score", ascending=False)
    filtered = filtered.head(cfg.max_tickers)
    
    return filtered.reset_index(drop=True)


def export_tiered_shortlists(
    comparison_path: str | Path,
    output_dir: str | Path,
    cfg: TieredShortlistConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Exporte les shortlists par tier.
    
    Tier 1 (Funded): MIN_TRADES=15, critères stricts
    Tier 2 (Challenge): MIN_TRADES=10, HORS Tier 1
    
    Args:
        comparison_path: Chemin vers comparison_ref.csv
        output_dir: Répertoire de sortie
        cfg: Configuration
    
    Returns:
        Tuple (tier1_df, tier2_df)
    """
    if cfg is None:
        cfg = TieredShortlistConfig.from_env()
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    df = pd.read_csv(comparison_path)
    
    # Colonnes à exporter
    export_cols = [
        "ticker", "penalty", "oos_score",
        "oos_trades", "oos_expectancy", "oos_pf", "oos_wr", "oos_dd",
        "is_trades", "is_expectancy", "is_pf",
    ]
    
    # Tier 1: critères stricts (≥15 trades)
    tier1 = _generate_shortlist_for_tier(df, cfg.tier1_min_trades, cfg)
    tier1_tickers = tier1["ticker"].tolist() if not tier1.empty else []
    
    if not tier1.empty:
        tier1[[c for c in export_cols if c in tier1.columns]].to_csv(
            output_dir / "shortlist_tier1.csv", index=False
        )
    else:
        # Créer fichier vide avec headers
        pd.DataFrame(columns=export_cols).to_csv(
            output_dir / "shortlist_tier1.csv", index=False
        )
    
    # Tier 2: critères assouplis (≥10 trades), HORS tier 1
    tier2 = _generate_shortlist_for_tier(df, cfg.tier2_min_trades, cfg, exclude_tickers=tier1_tickers)
    
    if not tier2.empty:
        tier2[[c for c in export_cols if c in tier2.columns]].to_csv(
            output_dir / "shortlist_tier2.csv", index=False
        )
    else:
        pd.DataFrame(columns=export_cols).to_csv(
            output_dir / "shortlist_tier2.csv", index=False
        )
    
    # Shortlist combinée pour rétrocompatibilité (tier1 + tier2)
    combined = pd.concat([tier1, tier2], ignore_index=True) if not tier1.empty or not tier2.empty else pd.DataFrame()
    if not combined.empty:
        combined[[c for c in export_cols if c in combined.columns]].to_csv(
            output_dir / "shortlist_tradable.csv", index=False
        )
    else:
        pd.DataFrame(columns=export_cols).to_csv(
            output_dir / "shortlist_tradable.csv", index=False
        )
    
    return tier1, tier2


def print_tiered_shortlists(tier1: pd.DataFrame, tier2: pd.DataFrame) -> None:
    """Affiche les shortlists par tier."""
    from rich.console import Console
    console = Console()
    
    if not tier1.empty:
        console.print(f"\n[bold green]🎯 Tier 1 - Funded ({len(tier1)} tickers, ≥15 trades):[/bold green]")
        for _, row in tier1.iterrows():
            console.print(
                f"  • {row['ticker']:>12} │ "
                f"score {row['oos_score']:.3f} │ "
                f"OOS: {row['oos_trades']:>2}t ExpR {row['oos_expectancy']:+.3f} "
                f"PF {row['oos_pf']:.2f} DD {row['oos_dd']*100:.2f}%"
            )
    else:
        console.print(f"\n[yellow]⚠ Tier 1 - Funded: aucun ticker[/yellow]")
    
    if not tier2.empty:
        console.print(f"\n[bold cyan]🎯 Tier 2 - Challenge bonus ({len(tier2)} tickers, ≥10 trades):[/bold cyan]")
        for _, row in tier2.iterrows():
            console.print(
                f"  • {row['ticker']:>12} │ "
                f"score {row['oos_score']:.3f} │ "
                f"OOS: {row['oos_trades']:>2}t ExpR {row['oos_expectancy']:+.3f} "
                f"PF {row['oos_pf']:.2f} DD {row['oos_dd']*100:.2f}%"
            )
    else:
        console.print(f"\n[dim]Tier 2 - Challenge bonus: aucun ticker additionnel[/dim]")
    
    # Résumé
    total = len(tier1) + len(tier2)
    if total > 0:
        console.print(f"\n[bold]Résumé:[/bold]")
        console.print(f"  • Funded (Tier 1 seul): {len(tier1)} instruments")
        console.print(f"  • Challenge (Tier 1 + 2): {total} instruments")

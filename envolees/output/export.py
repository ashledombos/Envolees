"""
Export des résultats de backtest.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from envolees.backtest.engine import BacktestResult


def sanitize_path(s: str, max_len: int = 120) -> str:
    """Nettoie une chaîne pour l'utiliser dans un chemin de fichier."""
    clean = re.sub(r"[^A-Za-z0-9._=-]+", "_", s.strip())
    return clean[:max_len] if len(clean) > max_len else clean


def export_result(result: BacktestResult, base_dir: str = "out") -> Path:
    """
    Exporte un résultat de backtest.

    Crée :
    - trades.csv
    - equity_curve.csv
    - daily_stats.csv
    - summary.json

    Args:
        result: Résultat du backtest
        base_dir: Répertoire de sortie racine

    Returns:
        Chemin du dossier créé
    """
    # Chemin : out/<ticker>/PEN_<penalty>/
    ticker_dir = sanitize_path(result.ticker)
    pen_dir = f"PEN_{result.exec_penalty_atr:.2f}"
    out_path = Path(base_dir) / ticker_dir / pen_dir
    out_path.mkdir(parents=True, exist_ok=True)

    # Trades
    trades_df = result.trades_df()
    if not trades_df.empty:
        trades_df.to_csv(out_path / "trades.csv", index=False)

    # Equity curve
    equity_df = result.equity_df()
    if not equity_df.empty:
        equity_df.to_csv(out_path / "equity_curve.csv")

    # Daily stats
    daily_df = result.daily_df()
    if not daily_df.empty:
        daily_df.to_csv(out_path / "daily_stats.csv", index=False)

    # Summary JSON
    with open(out_path / "summary.json", "w", encoding="utf-8") as f:
        json.dump(result.summary, f, ensure_ascii=False, indent=2, default=str)

    return out_path


def export_batch_summary(
    results: list[BacktestResult],
    base_dir: str = "out",
) -> pd.DataFrame:
    """
    Exporte un résumé de tous les backtests.

    Args:
        results: Liste des résultats
        base_dir: Répertoire de sortie

    Returns:
        DataFrame avec une ligne par backtest
    """
    rows = []
    for r in results:
        s = r.summary
        rows.append({
            "ticker": s["ticker"],
            "penalty_atr": s["exec_penalty_atr"],
            "bars_4h": s["bars_4h"],
            "n_trades": s["n_trades"],
            "win_rate": s["win_rate"],
            "profit_factor": s["profit_factor"],
            "expectancy_r": s["expectancy_r"],
            "end_balance": s["end_balance"],
            "max_daily_dd_pct": s["prop"]["max_daily_dd_pct"],
            "p99_daily_dd_pct": s["prop"]["p99_daily_dd_pct"],
            "viol_ftmo_bars": s["prop"]["n_daily_violate_ftmo_bars"],
            "viol_gft_bars": s["prop"]["n_daily_violate_gft_bars"],
            "viol_total_bars": s["prop"]["n_total_violate_bars"],
            "status": "ok",
            "error": "",
        })

    df = pd.DataFrame(rows)
    out_path = Path(base_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path / "results.csv", index=False)

    return df


def format_summary_line(result: BacktestResult) -> str:
    """Formate une ligne de résumé pour affichage console."""
    s = result.summary
    return (
        f"{s['ticker']:>12} │ PEN {s['exec_penalty_atr']:.2f} │ "
        f"trades {s['n_trades']:>4} │ WR {s['win_rate']:.3f} │ "
        f"PF {s['profit_factor']:.3f} │ ExpR {s['expectancy_r']:+.3f} │ "
        f"DDmax {s['prop']['max_daily_dd_pct']*100:.2f}%"
    )

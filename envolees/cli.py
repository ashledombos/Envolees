"""
CLI pour Envolées.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from envolees import __version__
from envolees.backtest import BacktestEngine, BacktestResult
from envolees.config import Config, get_penalties, get_tickers
from envolees.data import download_1h, resample_to_4h, cache_stats, clear_cache
from envolees.output import export_batch_summary, export_result, format_summary_line, export_scoring
from envolees.split import apply_split, SplitInfo
from envolees.strategy import DonchianBreakoutStrategy

console = Console()


def run_single_backtest(
    ticker: str,
    penalty: float,
    cfg: Config,
    verbose: bool = False,
) -> tuple[BacktestResult | None, SplitInfo | None]:
    """Exécute un backtest pour un ticker et une pénalité."""
    try:
        # Téléchargement (avec cache)
        df_1h = download_1h(
            ticker,
            cfg,
            use_cache=cfg.cache_enabled,
            cache_max_age_hours=cfg.cache_max_age_hours,
            verbose=verbose,
        )
        df_4h = resample_to_4h(df_1h)

        # Split temporel si configuré
        df_4h, split_info = apply_split(df_4h, cfg)
        
        if split_info and verbose:
            console.print(f"[dim]   {split_info}[/dim]")

        strategy = DonchianBreakoutStrategy(cfg)
        engine = BacktestEngine(cfg, strategy, ticker, penalty)

        result = engine.run(df_4h)
        return result, split_info
        
    except Exception as e:
        console.print(f"[red]✗[/red] {ticker} PEN {penalty:.2f}: {e}")
        return None, None


@click.group()
@click.version_option(__version__, prog_name="envolees")
def main() -> None:
    """🚀 Envolées - Backtest engine for Donchian breakout strategy."""
    pass


@main.command()
@click.option(
    "--tickers", "-t",
    help="Tickers (comma-separated). Uses .env if not specified.",
)
@click.option(
    "--penalties", "-p",
    help="Execution penalties as ATR multiples (comma-separated). Uses .env if not specified.",
)
@click.option(
    "--output", "-o",
    default=None,
    help="Output directory (default: from .env or 'out').",
)
@click.option(
    "--mode",
    type=click.Choice(["close", "worst"]),
    default=None,
    help="Daily equity mode (default: from .env or 'worst').",
)
@click.option(
    "--split",
    type=click.Choice(["is", "oos", "none"]),
    default=None,
    help="Split mode: is=in-sample, oos=out-of-sample, none=all data.",
)
@click.option(
    "--no-cache",
    is_flag=True,
    help="Disable data cache (force re-download).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Verbose output.",
)
def run(
    tickers: str | None,
    penalties: str | None,
    output: str | None,
    mode: str | None,
    split: str | None,
    no_cache: bool,
    verbose: bool,
) -> None:
    """Run backtest on tickers with specified penalties."""
    cfg = Config.from_env()

    # Override depuis CLI
    overrides = {}
    if output:
        overrides["output_dir"] = output
    if mode:
        overrides["daily_equity_mode"] = mode
    if split:
        if split == "none":
            overrides["split_mode"] = ""
        else:
            overrides["split_mode"] = "time"
            overrides["split_target"] = split
    if no_cache:
        overrides["cache_enabled"] = False
    
    if overrides:
        # Recréer la config avec les overrides
        cfg_dict = {
            "start_balance": cfg.start_balance,
            "risk_per_trade": cfg.risk_per_trade,
            "ema_period": cfg.ema_period,
            "atr_period": cfg.atr_period,
            "donchian_n": cfg.donchian_n,
            "buffer_atr": cfg.buffer_atr,
            "sl_atr": cfg.sl_atr,
            "tp_r": cfg.tp_r,
            "vol_quantile": cfg.vol_quantile,
            "vol_window_bars": cfg.vol_window_bars,
            "no_trade_start": cfg.no_trade_start,
            "no_trade_end": cfg.no_trade_end,
            "order_valid_bars": cfg.order_valid_bars,
            "conservative_same_bar": cfg.conservative_same_bar,
            "daily_dd_ftmo": cfg.daily_dd_ftmo,
            "daily_dd_gft": cfg.daily_dd_gft,
            "max_loss": cfg.max_loss,
            "stop_after_n_losses": cfg.stop_after_n_losses,
            "daily_kill_switch": cfg.daily_kill_switch,
            "daily_equity_mode": cfg.daily_equity_mode,
            "split_mode": cfg.split_mode,
            "split_ratio": cfg.split_ratio,
            "split_target": cfg.split_target,
            "yf_period": cfg.yf_period,
            "yf_interval": cfg.yf_interval,
            "cache_enabled": cfg.cache_enabled,
            "cache_dir": cfg.cache_dir,
            "cache_max_age_hours": cfg.cache_max_age_hours,
            "output_dir": cfg.output_dir,
            "weights": cfg.weights,
        }
        cfg_dict.update(overrides)
        cfg = Config(**cfg_dict)

    # Tickers
    ticker_list = (
        [t.strip() for t in tickers.split(",") if t.strip()]
        if tickers
        else get_tickers()
    )

    # Penalties
    penalty_list = (
        [float(p.strip()) for p in penalties.split(",") if p.strip()]
        if penalties
        else get_penalties()
    )

    # Header
    console.print(f"\n[bold cyan]🚀 Envolées v{__version__}[/bold cyan]")
    console.print(f"   Tickers: {len(ticker_list)} │ Penalties: {len(penalty_list)}")
    console.print(f"   Mode: {cfg.daily_equity_mode} │ Output: {cfg.output_dir}")
    
    # Afficher le split de manière très visible
    if cfg.split_mode == "time" or cfg.split_target in ("is", "oos"):
        target = cfg.split_target or "is"
        console.print(f"   [bold yellow]Split: {cfg.split_ratio:.0%} → {target.upper()}[/bold yellow]")
    elif cfg.split_target:
        console.print(f"   [bold yellow]Split: {cfg.split_target.upper()}[/bold yellow]")
    
    if not cfg.cache_enabled:
        console.print("   [yellow]Cache: disabled[/yellow]")
    
    console.print()

    results: list[BacktestResult] = []
    errors: list[tuple[str, float, str]] = []
    first_split_logged = False

    total = len(ticker_list) * len(penalty_list)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running backtests...", total=total)

        for ticker in ticker_list:
            for penalty in penalty_list:
                progress.update(task, description=f"{ticker} PEN {penalty:.2f}")

                result, split_info = run_single_backtest(ticker, penalty, cfg, verbose)

                if result is not None:
                    results.append(result)
                    export_result(result, cfg.output_dir)
                    
                    # Log split info une fois (pour le premier ticker/penalty)
                    if split_info and not first_split_logged:
                        console.print(f"[dim]   {split_info}[/dim]")
                        first_split_logged = True
                    
                    console.print(f"[green]✓[/green] {format_summary_line(result)}")
                else:
                    errors.append((ticker, penalty, "Download or backtest failed"))

                progress.advance(task)

    # Export summary
    if results:
        summary_df = export_batch_summary(results, cfg.output_dir)
        
        # Export scores et shortlist
        scores_df, shortlist_df = export_scoring(summary_df, cfg.output_dir)

        # Affichage synthèse par pénalité
        console.print("\n[bold]Synthèse par pénalité:[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Penalty")
        table.add_column("Trades", justify="right")
        table.add_column("Avg WR", justify="right")
        table.add_column("Avg PF", justify="right")
        table.add_column("Avg ExpR", justify="right")
        table.add_column("Max DD%", justify="right")

        grp = summary_df.groupby("penalty_atr").agg({
            "n_trades": "sum",
            "win_rate": "mean",
            "profit_factor": "mean",
            "expectancy_r": "mean",
            "max_daily_dd_pct": "max",
        }).reset_index()

        for _, row in grp.iterrows():
            table.add_row(
                f"{row['penalty_atr']:.2f}",
                str(int(row["n_trades"])),
                f"{row['win_rate']:.3f}",
                f"{row['profit_factor']:.3f}",
                f"{row['expectancy_r']:+.3f}",
                f"{row['max_daily_dd_pct']*100:.2f}%",
            )

        console.print(table)
        
        # Afficher la shortlist si non vide
        if len(shortlist_df) > 0:
            console.print(f"\n[bold green]Shortlist prod ({len(shortlist_df)} tickers):[/bold green]")
            for _, row in shortlist_df.iterrows():
                console.print(
                    f"  [green]•[/green] {row['ticker']:>12} │ "
                    f"Score {row.get('score', 0):.3f} │ "
                    f"ExpR {row['expectancy_r']:+.3f} │ "
                    f"PF {row['profit_factor']:.2f} │ "
                    f"DD {row['max_daily_dd_pct']*100:.2f}%"
                )

    # Erreurs
    if errors:
        console.print(f"\n[yellow]⚠ {len(errors)} erreur(s)[/yellow]")
        for t, p, e in errors:
            console.print(f"  - {t} PEN {p:.2f}: {e}")

    console.print(f"\n[dim]Résultats: {cfg.output_dir}/[/dim]")
    console.print(f"[dim]  • results.csv   (détails)[/dim]")
    console.print(f"[dim]  • scores.csv    (scores par ticker)[/dim]")
    console.print(f"[dim]  • shortlist.csv (candidats prod)[/dim]")


@main.command()
@click.argument("ticker")
@click.option("--penalty", "-p", default=0.10, help="Execution penalty (ATR multiple).")
@click.option("--output", "-o", default=None, help="Output directory.")
@click.option("--no-cache", is_flag=True, help="Disable data cache.")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output.")
def single(ticker: str, penalty: float, output: str | None, no_cache: bool, verbose: bool) -> None:
    """Run backtest on a single ticker."""
    cfg = Config.from_env()
    
    if output:
        cfg = Config(**{**_cfg_to_dict(cfg), "output_dir": output})
    if no_cache:
        cfg = Config(**{**_cfg_to_dict(cfg), "cache_enabled": False})

    console.print(f"\n[cyan]Running {ticker} with penalty {penalty:.2f}...[/cyan]")

    result, split_info = run_single_backtest(ticker, penalty, cfg, verbose)

    if result is None:
        console.print("[red]Backtest failed.[/red]")
        sys.exit(1)

    export_result(result, cfg.output_dir)
    console.print(f"\n[green]✓[/green] {format_summary_line(result)}")
    
    if split_info:
        console.print(f"[dim]   {split_info}[/dim]")

    # Détail
    s = result.summary
    console.print(f"\n[bold]Détails:[/bold]")
    console.print(f"  Barres 4H: {s['bars_4h']}")
    console.print(f"  Balance: {s['start_balance']:,.0f} → {s['end_balance']:,.0f}")
    console.print(f"  Trades: {s['n_trades']}")
    console.print(f"  Win Rate: {s['win_rate']:.1%}")
    console.print(f"  Profit Factor: {s['profit_factor']:.2f}")
    console.print(f"  Expectancy: {s['expectancy_r']:+.3f} R")
    console.print(f"  Max Daily DD: {s['prop']['max_daily_dd_pct']*100:.2f}%")
    console.print(f"  P99 Daily DD: {s['prop']['p99_daily_dd_pct']*100:.2f}%")


@main.command()
def config() -> None:
    """Show current configuration."""
    cfg = Config.from_env()
    tickers = get_tickers()
    penalties = get_penalties()

    console.print("\n[bold cyan]Configuration actuelle:[/bold cyan]\n")

    table = Table(show_header=False, box=None)
    table.add_column(style="dim")
    table.add_column()

    table.add_row("Tickers", ", ".join(tickers))
    table.add_row("Penalties", ", ".join(f"{p:.2f}" for p in penalties))
    table.add_row("Start Balance", f"{cfg.start_balance:,.0f}")
    table.add_row("Risk/Trade", f"{cfg.risk_per_trade:.2%}")
    table.add_row("EMA Period", str(cfg.ema_period))
    table.add_row("ATR Period", str(cfg.atr_period))
    table.add_row("Donchian N", str(cfg.donchian_n))
    table.add_row("Buffer ATR", f"{cfg.buffer_atr:.2f}")
    table.add_row("SL ATR", f"{cfg.sl_atr:.2f}")
    table.add_row("TP R", f"{cfg.tp_r:.2f}")
    table.add_row("Daily Equity Mode", cfg.daily_equity_mode)
    table.add_row("Daily Kill Switch", f"{cfg.daily_kill_switch:.0%}")
    table.add_row("Stop After N Losses", str(cfg.stop_after_n_losses))
    table.add_row("", "")
    table.add_row("Split Mode", cfg.split_mode or "(none)")
    if cfg.split_mode:
        table.add_row("Split Ratio", f"{cfg.split_ratio:.0%}")
        table.add_row("Split Target", cfg.split_target or "is")
    table.add_row("", "")
    table.add_row("Cache Enabled", "Yes" if cfg.cache_enabled else "No")
    table.add_row("Cache Max Age", f"{cfg.cache_max_age_hours}h")
    table.add_row("Output Dir", cfg.output_dir)
    
    if cfg.weights:
        table.add_row("", "")
        table.add_row("Weights", ", ".join(f"{k}={v}" for k, v in cfg.weights.items()))

    console.print(table)


@main.command()
def cache() -> None:
    """Show cache statistics."""
    stats = cache_stats()
    
    console.print("\n[bold cyan]Cache Statistics:[/bold cyan]\n")
    console.print(f"  Directory: {stats['cache_dir']}")
    console.print(f"  Files: {stats['n_files']}")
    console.print(f"  Size: {stats['total_size_mb']} MB")
    
    if stats['tickers']:
        console.print(f"  Tickers: {', '.join(stats['tickers'])}")


@main.command("cache-clear")
@click.confirmation_option(prompt="Are you sure you want to clear the cache?")
def cache_clear() -> None:
    """Clear the data cache."""
    n = clear_cache()
    console.print(f"[green]✓[/green] Cleared {n} files from cache.")


@main.command("cache-warm")
@click.option(
    "--tickers", "-t",
    default=None,
    help="Tickers to warm (comma-separated). Uses .env if not specified.",
)
def cache_warm(tickers: str | None) -> None:
    """Pre-fetch data into cache for faster runs."""
    from envolees.data import download_1h, resample_to_4h
    
    cfg = Config.from_env()
    ticker_list = (
        [t.strip() for t in tickers.split(",") if t.strip()]
        if tickers
        else get_tickers()
    )
    
    console.print(f"\n[cyan]Warming cache for {len(ticker_list)} tickers...[/cyan]\n")
    
    success = 0
    errors = []
    
    for ticker in ticker_list:
        try:
            df = download_1h(ticker, cfg, use_cache=False, verbose=True)
            console.print(f"[green]✓[/green] {ticker}: {len(df)} bars 1H")
            success += 1
        except Exception as e:
            console.print(f"[red]✗[/red] {ticker}: {e}")
            errors.append((ticker, str(e)))
    
    console.print(f"\n[bold]Résultat:[/bold] {success}/{len(ticker_list)} tickers mis en cache")
    
    if errors:
        console.print(f"[yellow]⚠ {len(errors)} erreur(s)[/yellow]")


@main.command("cache-verify")
@click.option(
    "--tickers", "-t",
    default=None,
    help="Tickers to verify (comma-separated). Uses .env if not specified.",
)
@click.option(
    "--fail-on-gaps",
    is_flag=True,
    help="Exit with error if gaps are detected.",
)
def cache_verify(tickers: str | None, fail_on_gaps: bool) -> None:
    """Verify cache integrity and detect data gaps."""
    from envolees.data import download_1h, resample_to_4h
    from envolees.data.cache import get_cache_path, is_cache_valid, get_metadata_path
    from datetime import datetime, timedelta
    import json
    
    cfg = Config.from_env()
    ticker_list = (
        [t.strip() for t in tickers.split(",") if t.strip()]
        if tickers
        else get_tickers()
    )
    
    console.print(f"\n[cyan]Verifying cache for {len(ticker_list)} tickers...[/cyan]\n")
    
    issues = []
    
    for ticker in ticker_list:
        cache_path = get_cache_path(ticker, cfg.yf_period, cfg.yf_interval, cfg)
        meta_path = get_metadata_path(cache_path)
        
        # Vérifier existence
        if not cache_path.exists():
            console.print(f"[yellow]⚠[/yellow] {ticker}: not in cache")
            issues.append((ticker, "not_cached"))
            continue
        
        # Vérifier validité
        if not is_cache_valid(cache_path, cfg.cache_max_age_hours):
            console.print(f"[yellow]⚠[/yellow] {ticker}: cache expired")
            issues.append((ticker, "expired"))
            continue
        
        # Charger et vérifier les données
        try:
            import pandas as pd
            df = pd.read_parquet(cache_path)
            
            # Vérifier les trous
            if len(df) > 1:
                expected_gap = pd.Timedelta(hours=1)  # 1H data
                actual_gaps = df.index.to_series().diff().dropna()
                large_gaps = actual_gaps[actual_gaps > expected_gap * 6]  # >6h = suspect
                
                if len(large_gaps) > 0:
                    max_gap = large_gaps.max()
                    gap_hours = max_gap.total_seconds() / 3600
                    console.print(
                        f"[yellow]⚠[/yellow] {ticker}: {len(large_gaps)} gap(s), "
                        f"max {gap_hours:.0f}h"
                    )
                    issues.append((ticker, f"gaps:{len(large_gaps)}"))
                else:
                    # Vérifier fraîcheur
                    last_bar = df.index.max()
                    age = datetime.now(last_bar.tzinfo) - last_bar
                    age_hours = age.total_seconds() / 3600
                    
                    if age_hours > 24:
                        console.print(
                            f"[yellow]⚠[/yellow] {ticker}: last bar {age_hours:.0f}h ago"
                        )
                        issues.append((ticker, f"stale:{age_hours:.0f}h"))
                    else:
                        console.print(
                            f"[green]✓[/green] {ticker}: {len(df)} bars, "
                            f"last {age_hours:.1f}h ago"
                        )
            
        except Exception as e:
            console.print(f"[red]✗[/red] {ticker}: read error - {e}")
            issues.append((ticker, "read_error"))
    
    # Résumé
    console.print(f"\n[bold]Résultat:[/bold] {len(ticker_list) - len(issues)}/{len(ticker_list)} OK")
    
    if issues:
        console.print(f"[yellow]⚠ {len(issues)} problème(s) détecté(s)[/yellow]")
        if fail_on_gaps:
            sys.exit(1)


@main.command()
@click.argument("is_dir")
@click.argument("oos_dir")
@click.option(
    "--output", "-o",
    default="out_compare",
    help="Output directory for comparison report.",
)
@click.option(
    "--penalty", "-p",
    default=0.25,
    type=float,
    help="Reference penalty for validation (default: 0.25).",
)
@click.option(
    "--min-trades",
    default=15,
    type=int,
    help="Minimum OOS trades for eligibility (default: 15).",
)
@click.option(
    "--dd-cap",
    default=0.012,
    type=float,
    help="Maximum DD for shortlist (default: 0.012 = 1.2%).",
)
@click.option(
    "--max-tickers",
    default=5,
    type=int,
    help="Maximum tickers in shortlist (default: 5).",
)
@click.option(
    "--alert/--no-alert",
    default=False,
    help="Send alert with results.",
)
def compare(
    is_dir: str,
    oos_dir: str,
    output: str,
    penalty: float,
    min_trades: int,
    dd_cap: float,
    max_tickers: int,
    alert: bool,
) -> None:
    """Compare IS and OOS results for validation.
    
    Example:
        python main.py compare out_is out_oos -o out_compare
    """
    from pathlib import Path
    from envolees.output.compare import (
        OOSEligibility,
        ShortlistConfig,
        export_comparison,
        print_comparison_summary,
        compare_is_oos,
        shortlist_from_compare,
        export_shortlist,
    )
    
    is_path = Path(is_dir) / "results.csv"
    oos_path = Path(oos_dir) / "results.csv"
    
    if not is_path.exists():
        console.print(f"[red]Error:[/red] {is_path} not found")
        sys.exit(1)
    if not oos_path.exists():
        console.print(f"[red]Error:[/red] {oos_path} not found")
        sys.exit(1)
    
    console.print(f"\n[bold cyan]📊 Comparing IS vs OOS[/bold cyan]")
    console.print(f"   IS:  {is_dir}")
    console.print(f"   OOS: {oos_dir}")
    console.print(f"   Reference penalty: {penalty}")
    console.print(f"   Min OOS trades: {min_trades}")
    console.print(f"   DD cap: {dd_cap*100:.1f}%\n")
    
    criteria = OOSEligibility(min_trades=min_trades)
    
    # Export complet
    validated = export_comparison(
        is_path, oos_path, output,
        criteria=criteria,
        reference_penalty=penalty,
    )
    
    # Afficher le résumé
    comparison_df = compare_is_oos(is_path, oos_path, criteria, penalty)
    print_comparison_summary(comparison_df)
    
    # Générer la shortlist
    shortlist_cfg = ShortlistConfig(
        min_trades_oos=min_trades,
        dd_cap=dd_cap,
        max_tickers=max_tickers,
    )
    
    comparison_ref_path = Path(output) / "comparison_ref.csv"
    shortlist = export_shortlist(
        comparison_ref_path,
        Path(output) / "shortlist_tradable.csv",
        shortlist_cfg,
    )
    
    if not shortlist.empty:
        console.print(f"\n[bold green]🎯 Shortlist tradable ({len(shortlist)} tickers):[/bold green]")
        for _, row in shortlist.iterrows():
            console.print(
                f"  • {row['ticker']:>12} │ "
                f"score {row['oos_score']:.3f} │ "
                f"OOS: {row['oos_trades']:>2}t ExpR {row['oos_expectancy']:+.3f} "
                f"PF {row['oos_pf']:.2f} DD {row['oos_dd']*100:.2f}%"
            )
    else:
        console.print(f"\n[yellow]⚠ Aucun ticker ne passe les critères shortlist[/yellow]")
    
    console.print(f"\n[dim]Rapports exportés dans {output}/[/dim]")
    console.print(f"[dim]  • comparison_full.csv    (toutes pénalités)[/dim]")
    console.print(f"[dim]  • comparison_ref.csv     (PEN {penalty})[/dim]")
    console.print(f"[dim]  • validated.csv          (tickers validés)[/dim]")
    console.print(f"[dim]  • shortlist_tradable.csv (shortlist finale)[/dim]")
    
    # Alertes
    if alert:
        try:
            from envolees.alerts import send_backtest_summary
            
            cfg = Config.from_env()
            n_tickers = len(comparison_df["ticker"].unique()) if not comparison_df.empty else 0
            n_trades = int(comparison_df["oos_trades"].sum()) if not comparison_df.empty else 0
            
            best_ticker = shortlist.iloc[0]["ticker"] if not shortlist.empty else "N/A"
            best_score = float(shortlist.iloc[0]["oos_score"]) if not shortlist.empty else 0.0
            validated_count = len(validated) if validated is not None else 0
            
            results = send_backtest_summary(
                profile=cfg.risk_mode or "default",
                n_tickers=n_tickers,
                n_trades=n_trades,
                best_ticker=best_ticker,
                best_score=best_score,
                validated_count=validated_count,
            )
            
            if any(results.values()):
                console.print(f"[green]✓[/green] Alerte envoyée")
            else:
                console.print(f"[dim]Alertes non configurées[/dim]")
                
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Alerte échouée: {e}")


def _cfg_to_dict(cfg: Config) -> dict:
    """Convertit une Config en dict pour recréation."""
    return {
        "start_balance": cfg.start_balance,
        "risk_per_trade": cfg.risk_per_trade,
        "ema_period": cfg.ema_period,
        "atr_period": cfg.atr_period,
        "donchian_n": cfg.donchian_n,
        "buffer_atr": cfg.buffer_atr,
        "sl_atr": cfg.sl_atr,
        "tp_r": cfg.tp_r,
        "vol_quantile": cfg.vol_quantile,
        "vol_window_bars": cfg.vol_window_bars,
        "no_trade_start": cfg.no_trade_start,
        "no_trade_end": cfg.no_trade_end,
        "order_valid_bars": cfg.order_valid_bars,
        "conservative_same_bar": cfg.conservative_same_bar,
        "daily_dd_ftmo": cfg.daily_dd_ftmo,
        "daily_dd_gft": cfg.daily_dd_gft,
        "max_loss": cfg.max_loss,
        "stop_after_n_losses": cfg.stop_after_n_losses,
        "daily_kill_switch": cfg.daily_kill_switch,
        "daily_equity_mode": cfg.daily_equity_mode,
        "split_mode": cfg.split_mode,
        "split_ratio": cfg.split_ratio,
        "split_target": cfg.split_target,
        "yf_period": cfg.yf_period,
        "yf_interval": cfg.yf_interval,
        "cache_enabled": cfg.cache_enabled,
        "cache_dir": cfg.cache_dir,
        "cache_max_age_hours": cfg.cache_max_age_hours,
        "output_dir": cfg.output_dir,
        "weights": cfg.weights,
        "risk_mode": cfg.risk_mode,
        "max_concurrent_trades": cfg.max_concurrent_trades,
        "daily_risk_budget": cfg.daily_risk_budget,
    }


if __name__ == "__main__":
    main()

"""
CLI pour Envolées.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click
import pandas as pd
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from envolees import __version__
from envolees.backtest import BacktestEngine, BacktestResult
from envolees.config import Config, get_penalties, get_tickers
from envolees.data import download_1h, resample_to_timeframe, cache_stats, clear_cache
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
        df = resample_to_timeframe(df_1h, cfg.timeframe)

        # Split temporel si configuré
        df, split_info = apply_split(df, cfg)
        
        if split_info and verbose:
            console.print(f"[dim]   {split_info}[/dim]")

        strategy = DonchianBreakoutStrategy(cfg)
        engine = BacktestEngine(cfg, strategy, ticker, penalty)

        result = engine.run(df)
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
@click.option( 
    "--timeframe", "-tf",
    type=click.Choice(["1h", "4h"]),
    default=None,
    help="Trading timeframe: 1h=challenge, 4h=funded (default: from .env or '4h').",
)       
def run(
    tickers: str | None,
    penalties: str | None,
    output: str | None,
    mode: str | None,
    split: str | None,
    no_cache: bool,
    verbose: bool,
    timeframe: str | None,
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
    if timeframe:
        overrides["timeframe"] = timeframe 
    
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
            "timeframe": cfg.timeframe,
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
    console.print(f"   Tickers: {len(ticker_list)} │ Penalties: {len(penalty_list)} │ TF: {cfg.timeframe.upper()}")
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
            # Indiquer clairement que c'est IS (pas la shortlist finale)
            split_label = cfg.split_target.upper() if cfg.split_target else "IS"
            console.print(f"\n[bold green]Shortlist {split_label} ({len(shortlist_df)} tickers):[/bold green]")
            if cfg.split_target == "is":
                console.print(f"[dim]  ⚠ Cette shortlist est basée sur IS. Utiliser 'compare' pour la validation OOS.[/dim]")
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
    console.print(f"[dim]  • shortlist.csv (candidats {split_label if 'split_label' in dir() else 'IS'})[/dim]")


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
    console.print(f"  Barres 4H: {s['bars']}")
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
@click.option(
    "--force", "-f",
    is_flag=True,
    help="Force refresh even if cache is valid (ignore CACHE_MAX_AGE_HOURS).",
)
def cache_warm(tickers: str | None, force: bool) -> None:
    """Pre-fetch data into cache for faster runs.
    
    By default, respects CACHE_MAX_AGE_HOURS from .env (skips valid cache).
    Use --force to re-download everything.
    """
    from envolees.data import download_1h, resample_to_timeframe
    
    cfg = Config.from_env()
    ticker_list = (
        [t.strip() for t in tickers.split(",") if t.strip()]
        if tickers
        else get_tickers()
    )
    
    # Déterminer l'âge max du cache
    max_age = 0 if force else cfg.cache_max_age_hours
    mode = "FORCE refresh" if force else f"respecting cache ({cfg.cache_max_age_hours}h max age)"
    
    console.print(f"\n[cyan]Warming cache for {len(ticker_list)} tickers — {mode}[/cyan]\n")
    
    success = 0
    errors = []
    
    for ticker in ticker_list:
        try:
            df = download_1h(ticker, cfg, use_cache=True, cache_max_age_hours=max_age, verbose=True)
            console.print(f"[green]✓[/green] {ticker}: {len(df)} bars 1H")
            success += 1
        except Exception as e:
            console.print(f"[red]✗[/red] {ticker}: {e}")
            errors.append((ticker, str(e)))
    
    console.print(f"\n[bold]Résultat:[/bold] {success}/{len(ticker_list)} tickers OK")
    
    if errors:
        console.print(f"[yellow]⚠ {len(errors)} erreur(s):[/yellow]")
        for ticker, err in errors[:5]:
            console.print(f"  • {ticker}: {err}")
        if len(errors) > 5:
            console.print(f"  • ... et {len(errors) - 5} autres")


@main.command("cache-verify")
@click.option(
    "--tickers", "-t",
    default=None,
    help="Tickers to verify (comma-separated). Uses .env if not specified.",
)
@click.option(
    "--fail-on-gaps",
    is_flag=True,
    help="Exit with error if unexpected gaps are detected.",
)
@click.option(
    "--fail-on-stale",
    is_flag=True,
    help="Exit with error if stale data is detected.",
)
@click.option(
    "--export-eligible",
    type=click.Path(),
    default=None,
    help="Export eligible tickers to file (for pipeline use).",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Show detailed gap analysis.",
)
def cache_verify(
    tickers: str | None,
    fail_on_gaps: bool,
    fail_on_stale: bool,
    export_eligible: str | None,
    verbose: bool,
) -> None:
    """Verify cache integrity and detect data gaps (calendar-aware).
    
    Distinguishes between:
    - gaps: missing data within expected trading hours (blocking)
    - stale: data not recent enough (warning by default)
    
    Use --export-eligible to generate a list of valid tickers for pipeline.
    """
    from envolees.data.cache import get_cache_path, is_cache_valid
    from envolees.data.calendar import analyze_gaps, check_staleness, classify_ticker
    import pandas as pd
    import json
    
    cfg = Config.from_env()
    ticker_list = (
        [t.strip() for t in tickers.split(",") if t.strip()]
        if tickers
        else get_tickers()
    )
    
    console.print(f"\n[cyan]Verifying cache for {len(ticker_list)} tickers (calendar-aware)...[/cyan]\n")
    
    # Résultats détaillés
    results = {
        "eligible": [],      # Tickers OK pour backtest
        "excluded": [],      # Tickers exclus
        "gaps": [],          # Tickers avec gaps (bloquant)
        "stale": [],         # Tickers stale (warning)
        "missing": [],       # Tickers sans cache
        "errors": [],        # Erreurs de lecture
    }
    
    for ticker in ticker_list:
        cache_path = get_cache_path(ticker, cfg.yf_period, cfg.yf_interval, cfg)
        
        # Vérifier existence
        if not cache_path.exists():
            console.print(f"[yellow]⚠[/yellow] {ticker}: not in cache")
            results["missing"].append(ticker)
            results["excluded"].append((ticker, "not_cached"))
            continue
        
        # Vérifier validité TTL
        if not is_cache_valid(cache_path, cfg.cache_max_age_hours):
            console.print(f"[yellow]⚠[/yellow] {ticker}: cache expired")
            results["missing"].append(ticker)
            results["excluded"].append((ticker, "expired"))
            continue
        
        # Charger et analyser
        try:
            df = pd.read_parquet(cache_path)
            asset_class = classify_ticker(ticker)
            gap_analysis = analyze_gaps(df, ticker, expected_interval_hours=1.0)
            staleness = check_staleness(df, ticker)
            
            # Construire l'affichage
            status_parts = [f"{len(df)} bars", f"{asset_class.value}"]
            
            # Utiliser is_acceptable() qui tient compte du max_extra_gaps par instrument
            has_unacceptable_gaps = not gap_analysis.is_acceptable()
            is_stale = staleness.is_stale
            
            # Affichage de la fraîcheur (calendar-aware)
            if staleness.trading_hours_missed > 0:
                status_parts.append(f"{staleness.trading_hours_missed:.0f}h trading manquées")
            elif staleness.age_hours > 2:
                # Âge brut pour info, mais pas de trading manqué = marché fermé
                status_parts.append(f"last {staleness.age_hours:.0f}h ago (marché fermé)")
            
            if gap_analysis.unexpected_gaps > 0:
                # Toujours afficher les gaps, même s'ils sont tolérés
                if has_unacceptable_gaps:
                    status_parts.append(f"{gap_analysis.unexpected_gaps} unexpected gaps")
                    results["gaps"].append(ticker)
                else:
                    # Gaps tolérés pour cet instrument
                    status_parts.append(f"{gap_analysis.unexpected_gaps} gaps (tolérés)")
            
            if is_stale:
                status_parts.append("stale")
                results["stale"].append(ticker)
            
            # Décision d'éligibilité
            # Gaps = bloquant seulement si au-dessus du seuil toléré
            # Stale = bloquant seulement si --fail-on-stale
            is_eligible = not has_unacceptable_gaps and (not is_stale or not fail_on_stale)
            
            if is_eligible:
                results["eligible"].append(ticker)
                if is_stale:
                    # Éligible mais stale = warning
                    console.print(f"[yellow]~[/yellow] {ticker}: {' │ '.join(status_parts)} [dim](stale but included)[/dim]")
                else:
                    console.print(f"[green]✓[/green] {ticker}: {' │ '.join(status_parts)}")
            else:
                reason = "gaps" if has_unacceptable_gaps else "stale"
                results["excluded"].append((ticker, reason))
                console.print(f"[yellow]⚠[/yellow] {ticker}: {' │ '.join(status_parts)}")
            
            # Détails si verbose
            if verbose:
                # Infos de debug pour staleness
                now = datetime.now(staleness.last_bar.tzinfo) if staleness.last_bar and staleness.last_bar.tzinfo else datetime.now()
                console.print(f"    [dim]now: {now.strftime('%Y-%m-%d %H:%M %Z')}[/dim]")
                if staleness.last_bar:
                    console.print(f"    [dim]last_bar: {staleness.last_bar.strftime('%Y-%m-%d %H:%M %Z')}[/dim]")
                console.print(f"    [dim]age_hours: {staleness.age_hours:.1f}h │ trading_missed: {staleness.trading_hours_missed:.1f}h │ max_age: {staleness.max_age_hours}h[/dim]")
                
                # Gaps (avec info sur le seuil)
                try:
                    from envolees.data.ftmo_instruments import get_max_extra_gaps
                    max_gaps = get_max_extra_gaps(ticker)
                    console.print(f"    [dim]gaps: {gap_analysis.unexpected_gaps} unexpected (max tolérés: {max_gaps})[/dim]")
                except ImportError:
                    pass
                
                if gap_analysis.issues:
                    console.print(f"    [dim]gap issues ({len(gap_analysis.issues)}):[/dim]")
                    for issue in gap_analysis.issues[:3]:
                        console.print(f"      [dim]{issue}[/dim]")
            
        except Exception as e:
            console.print(f"[red]✗[/red] {ticker}: read error - {e}")
            results["errors"].append(ticker)
            results["excluded"].append((ticker, f"error:{e}"))
    
    # Résumé
    n_eligible = len(results["eligible"])
    n_total = len(ticker_list)
    n_excluded = len(results["excluded"])
    
    console.print(f"\n[bold]Résultat:[/bold] {n_eligible}/{n_total} éligibles")
    
    if results["gaps"]:
        console.print(f"[red]  • Gaps bloquants: {', '.join(results['gaps'])}[/red]")
    if results["stale"]:
        stale_in_eligible = [t for t in results["stale"] if t in results["eligible"]]
        stale_excluded = [t for t in results["stale"] if t not in results["eligible"]]
        if stale_in_eligible:
            console.print(f"[yellow]  • Stale (inclus): {', '.join(stale_in_eligible)}[/yellow]")
        if stale_excluded:
            console.print(f"[yellow]  • Stale (exclus): {', '.join(stale_excluded)}[/yellow]")
    if results["missing"]:
        console.print(f"[dim]  • Manquants: {', '.join(results['missing'])}[/dim]")
    
    # Exporter les tickers éligibles
    if export_eligible:
        export_path = Path(export_eligible)
        export_path.parent.mkdir(parents=True, exist_ok=True)
        
        export_data = {
            "eligible": results["eligible"],
            "excluded": [{"ticker": t, "reason": r} for t, r in results["excluded"]],
            "timestamp": datetime.now().isoformat(),
        }
        
        if export_path.suffix == ".json":
            export_path.write_text(json.dumps(export_data, indent=2))
        else:
            # Format simple : un ticker par ligne
            export_path.write_text("\n".join(results["eligible"]))
        
        console.print(f"\n[dim]Tickers éligibles exportés: {export_path}[/dim]")
    
    # Code de sortie
    should_fail = False
    if fail_on_gaps and results["gaps"]:
        should_fail = True
    if fail_on_stale and results["stale"]:
        should_fail = True
    
    if should_fail:
        console.print(f"\n[red]⚠ Échec de vérification (--fail-on-gaps={fail_on_gaps}, --fail-on-stale={fail_on_stale})[/red]")
        sys.exit(1)
    
    # Retourner le nombre d'éligibles pour usage programmatique
    return n_eligible


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
    default=50,
    type=int,
    help="Maximum tickers in shortlist (default: 20).",
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
    
    Generates tiered shortlists:
    - Tier 1 (Funded): ≥15 trades OOS, strict criteria
    - Tier 2 (Challenge): ≥10 trades OOS, excludes Tier 1
    
    Example:
        python main.py compare out_is out_oos -o out_compare
    """
    from pathlib import Path
    from envolees.output.compare import (
        OOSEligibility,
        TieredShortlistConfig,
        export_comparison,
        print_comparison_summary,
        compare_is_oos,
        export_tiered_shortlists,
        print_tiered_shortlists,
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
    console.print(f"   Tier 1 min trades: 15 (Funded)")
    console.print(f"   Tier 2 min trades: 10 (Challenge)")
    console.print(f"   DD cap: {dd_cap*100:.1f}%\n")
    
    # Utiliser min_trades=10 pour voir tous les candidats potentiels
    criteria = OOSEligibility(min_trades=10)
    
    # Export complet
    validated = export_comparison(
        is_path, oos_path, output,
        criteria=criteria,
        reference_penalty=penalty,
    )
    
    # Afficher le résumé
    comparison_df = compare_is_oos(is_path, oos_path, criteria, penalty)
    print_comparison_summary(comparison_df)
    
    # Générer les shortlists par tier
    tiered_cfg = TieredShortlistConfig(
        tier1_min_trades=15,
        tier2_min_trades=10,
        dd_cap=dd_cap,
        max_tickers=max_tickers,
    )
    
    comparison_ref_path = Path(output) / "comparison_ref.csv"
    tier1, tier2 = export_tiered_shortlists(
        comparison_ref_path,
        output,
        tiered_cfg,
    )
    
    # Analyser les motifs de rejet
    import pandas as pd
    if comparison_ref_path.exists():
        all_tickers_df = pd.read_csv(comparison_ref_path)
        
        # Tickers dans les shortlists
        shortlisted = set()
        if not tier1.empty:
            shortlisted.update(tier1["ticker"].tolist())
        if not tier2.empty:
            shortlisted.update(tier2["ticker"].tolist())
        
        rejected = []
        for _, row in all_tickers_df.iterrows():
            ticker = row["ticker"]
            
            # Si dans une shortlist, pas rejeté
            if ticker in shortlisted:
                continue
            
            # Déterminer le motif
            reasons = []
            
            oos_trades = row.get("oos_trades", 0)
            if pd.isna(oos_trades) or oos_trades < 10:
                reasons.append(f"trades OOS ({int(oos_trades) if not pd.isna(oos_trades) else 0} < 10)")
            
            oos_dd = row.get("oos_dd", 0)
            if not pd.isna(oos_dd) and oos_dd > dd_cap:
                reasons.append(f"DD OOS ({oos_dd*100:.2f}% > {dd_cap*100:.1f}%)")
            
            is_dd = row.get("is_dd", 0)
            if not pd.isna(is_dd) and is_dd > dd_cap:
                reasons.append(f"DD IS ({is_dd*100:.2f}% > {dd_cap*100:.1f}%)")
            
            oos_pf = row.get("oos_pf", 0)
            if not pd.isna(oos_pf) and oos_pf < 1.2:
                reasons.append(f"PF OOS ({oos_pf:.2f} < 1.2)")
            
            oos_exp = row.get("oos_expectancy", 0)
            if not pd.isna(oos_exp) and oos_exp <= 0:
                reasons.append(f"ExpR OOS ({oos_exp:.3f} ≤ 0)")
            
            if not reasons:
                reasons.append("score insuffisant")
            
            rejected.append((ticker, reasons))
        
        if rejected:
            console.print(f"\n[yellow]📋 Motifs de rejet ({len(rejected)} tickers):[/yellow]")
            for ticker, reasons in rejected:
                console.print(f"  [dim]• {ticker}: {', '.join(reasons)}[/dim]")
    
    # Afficher les shortlists par tier
    print_tiered_shortlists(tier1, tier2)
    
    console.print(f"\n[dim]Rapports exportés dans {output}/[/dim]")
    console.print(f"[dim]  • comparison_full.csv    (toutes pénalités)[/dim]")
    console.print(f"[dim]  • comparison_ref.csv     (PEN {penalty})[/dim]")
    console.print(f"[dim]  • shortlist_tier1.csv    (Funded, ≥15 trades)[/dim]")
    console.print(f"[dim]  • shortlist_tier2.csv    (Challenge bonus, ≥10 trades)[/dim]")
    console.print(f"[dim]  • shortlist_tradable.csv (combiné Tier 1 + 2)[/dim]")
    
    # Alertes enrichies
    if alert:
        try:
            from envolees.alerts import send_backtest_summary
            from envolees.profiles import get_profile
            import json as json_mod
            
            profile = get_profile()
            n_tickers = len(comparison_df["ticker"].unique()) if not comparison_df.empty else 0
            n_trades = int(comparison_df["oos_trades"].sum()) if not comparison_df.empty else 0
            
            # Best ticker from tier1, or tier2 if tier1 empty
            if not tier1.empty:
                best_ticker = tier1.iloc[0]["ticker"]
                best_score = float(tier1.iloc[0]["oos_score"])
            elif not tier2.empty:
                best_ticker = tier2.iloc[0]["ticker"]
                best_score = float(tier2.iloc[0]["oos_score"])
            else:
                best_ticker = "N/A"
                best_score = 0.0
            
            validated_count = len(validated) if validated is not None else 0
            
            # Collecter les motifs de rejet par catégorie
            rejection_reasons = {}
            if not comparison_df.empty and "oos_status" in comparison_df.columns:
                for status in ["insufficient_trades", "degraded", "failed"]:
                    count = len(comparison_df[comparison_df["oos_status"] == status])
                    if count > 0:
                        rejection_reasons[status] = count
            
            # Compter les DD exceeded côté IS
            if not comparison_df.empty and "is_dd" in comparison_df.columns:
                dd_exceeded = len(comparison_df[comparison_df["is_dd"] > dd_cap])
                if dd_exceeded > 0:
                    rejection_reasons["dd_exceeded"] = dd_exceeded
            
            # Préparer les deux tiers pour l'alerte
            tier1_for_alert = []
            if not tier1.empty:
                for _, row in tier1.iterrows():
                    tier1_for_alert.append((row["ticker"], float(row["oos_score"])))
            
            tier2_for_alert = []
            if not tier2.empty:
                for _, row in tier2.iterrows():
                    tier2_for_alert.append((row["ticker"], float(row["oos_score"])))
            
            # Lire les exclusions cache si disponibles
            excluded_tickers = []
            eligible_file = Path("out_pipeline/eligible_tickers.json")
            if eligible_file.exists():
                try:
                    data = json_mod.loads(eligible_file.read_text())
                    excluded_tickers = data.get("excluded", [])
                except Exception:
                    pass
            
            results = send_backtest_summary(
                profile=profile.name,
                n_tickers=n_tickers,
                n_trades=n_trades,
                best_ticker=best_ticker,
                best_score=best_score,
                validated_count=validated_count,
                excluded_tickers=excluded_tickers if excluded_tickers else None,
                rejection_reasons=rejection_reasons if rejection_reasons else None,
                shortlist=tier1_for_alert if tier1_for_alert else None,
                tier2=tier2_for_alert if tier2_for_alert else None,
            )
            
            if any(results.values()):
                console.print(f"[green]✓[/green] Alerte envoyée")
            else:
                console.print(f"[dim]Alertes non configurées[/dim]")
                
        except Exception as e:
            console.print(f"[yellow]⚠[/yellow] Alerte échouée: {e}")


@main.command()
def heartbeat() -> None:
    """Send a heartbeat (alive signal)."""
    from envolees.alerts import send_heartbeat
    from envolees.profiles import get_profile
    
    profile = get_profile()
    console.print(f"\n[cyan]Sending heartbeat for profile: {profile.name}[/cyan]")
    
    results = send_heartbeat()
    
    if not results:
        console.print("[yellow]No alert channels configured[/yellow]")
        console.print("[dim]Set NTFY_TOPIC or TELEGRAM_BOT_TOKEN in .env.secret[/dim]")
        return
    
    for channel, success in results.items():
        if success:
            console.print(f"[green]✓[/green] {channel}: sent")
        else:
            console.print(f"[red]✗[/red] {channel}: failed")


@main.command()
@click.option(
    "--skip-cache",
    is_flag=True,
    help="Skip cache warm/verify steps.",
)
@click.option(
    "--strict",
    is_flag=True,
    help="Fail if any ticker has gaps OR stale data.",
)
@click.option(
    "--strict-gaps",
    is_flag=True,
    help="Fail only if any ticker has gaps (stale = warning but continue).",
)
@click.option(
    "--alert/--no-alert",
    default=True,
    help="Send alert after compare (default: yes).",
)
@click.pass_context
def pipeline(ctx, skip_cache: bool, strict: bool, strict_gaps: bool, alert: bool) -> None:
    """Run the complete validation pipeline.
    
    Steps: cache-warm → cache-verify → IS run → OOS run → compare
    
    Modes:
    - Default: continue with eligible tickers (gaps excluded, stale tolerated)
    - --strict-gaps: fail if ANY ticker has gaps (recommended for prod)
    - --strict: fail if ANY ticker has gaps OR stale data
    """
    import subprocess
    import json
    from pathlib import Path
    import os
    
    console.print("\n[bold cyan]🚀 Envolées - Pipeline complet[/bold cyan]\n")
    
    # Afficher le mode
    if strict:
        console.print("[dim]Mode: strict (gaps + stale bloquants)[/dim]")
    elif strict_gaps:
        console.print("[dim]Mode: strict-gaps (gaps bloquants, stale = warning)[/dim]")
    else:
        console.print("[dim]Mode: tolérant (gaps exclus, stale tolérés)[/dim]")
    
    # Répertoire de travail
    work_dir = Path("out_pipeline")
    work_dir.mkdir(exist_ok=True)
    eligible_file = work_dir / "eligible_tickers.json"
    
    original_tickers = get_tickers()
    eligible_tickers = original_tickers.copy()
    excluded_tickers = []
    stale_warning = False
    
    # Step 1: Cache warm
    if not skip_cache:
        console.print(f"\n[bold]Step 1: Cache warm[/bold]")
        result = subprocess.run(["python", "main.py", "cache-warm"])
        if result.returncode != 0:
            console.print(f"[red]✗ Cache warm failed[/red]")
            sys.exit(1)
        
        # Step 2: Cache verify (avec export des tickers éligibles)
        console.print(f"\n[bold]Step 2: Cache verify[/bold]")
        
        verify_cmd = [
            "python", "main.py", "cache-verify",
            "--export-eligible", str(eligible_file),
        ]
        
        # Options selon le mode
        if strict:
            verify_cmd.append("--fail-on-gaps")
            verify_cmd.append("--fail-on-stale")
        elif strict_gaps:
            verify_cmd.append("--fail-on-gaps")
        
        result = subprocess.run(verify_cmd)
        
        # En mode strict ou strict_gaps, vérifier le code de retour
        if (strict or strict_gaps) and result.returncode != 0:
            mode_name = "strict" if strict else "strict-gaps"
            console.print(f"\n[red]✗ Cache verify failed ({mode_name} mode)[/red]")
            sys.exit(1)
        
        # Lire les tickers éligibles (si le fichier existe)
        if eligible_file.exists():
            try:
                data = json.loads(eligible_file.read_text())
                eligible_tickers = data.get("eligible", [])
                excluded_tickers = data.get("excluded", [])
                
                # Vérifier si des tickers stale sont inclus (pour warning)
                stale_tickers = [
                    exc for exc in data.get("excluded", [])
                    if exc.get("reason") == "stale"
                ]
                # Note: les stale sont inclus dans eligible si pas --fail-on-stale
                # On veut détecter les stale pour le warning même s'ils sont éligibles
            except Exception as e:
                console.print(f"[yellow]⚠ Erreur lecture {eligible_file}: {e}[/yellow]")
        else:
            # Si le fichier n'existe pas (crash de cache-verify), continuer avec tous les tickers
            console.print(f"[yellow]⚠ Fichier éligibles non créé, utilisation de tous les tickers[/yellow]")
        
        if not eligible_tickers:
            console.print(f"\n[red]✗ Aucun ticker éligible après vérification du cache[/red]")
            sys.exit(1)
        
        if excluded_tickers:
            console.print(f"\n[yellow]⚠ {len(excluded_tickers)} ticker(s) exclus:[/yellow]")
            for exc in excluded_tickers:
                console.print(f"    [dim]• {exc['ticker']}: {exc['reason']}[/dim]")
            console.print(f"[cyan]→ Continue avec {len(eligible_tickers)} ticker(s): {', '.join(eligible_tickers)}[/cyan]\n")
    
    # Préparer l'environnement avec les tickers éligibles
    env = os.environ.copy()
    env["TICKERS"] = ",".join(eligible_tickers)
    
    # Step 3: Backtest IS
    step_n = 3 if not skip_cache else 1
    console.print(f"\n[bold]Step {step_n}: Backtest IS[/bold]")
    env_is = env.copy()
    env_is["SPLIT_TARGET"] = "is"
    env_is["OUTPUT_DIR"] = "out_is"
    
    result = subprocess.run(["python", "main.py", "run"], env=env_is)
    if result.returncode != 0:
        console.print(f"[red]✗ Backtest IS failed[/red]")
        sys.exit(1)
    
    # Step 4: Backtest OOS
    step_n += 1
    console.print(f"\n[bold]Step {step_n}: Backtest OOS[/bold]")
    env_oos = env.copy()
    env_oos["SPLIT_TARGET"] = "oos"
    env_oos["OUTPUT_DIR"] = "out_oos"
    
    result = subprocess.run(["python", "main.py", "run"], env=env_oos)
    if result.returncode != 0:
        console.print(f"[red]✗ Backtest OOS failed[/red]")
        sys.exit(1)
    
    # Step 5: Compare
    step_n += 1
    console.print(f"\n[bold]Step {step_n}: Compare IS/OOS[/bold]")
    compare_cmd = ["python", "main.py", "compare", "out_is", "out_oos"]
    if alert:
        compare_cmd.append("--alert")
    
    result = subprocess.run(compare_cmd, env=env)
    if result.returncode != 0:
        console.print(f"[red]✗ Compare failed[/red]")
        sys.exit(1)
    
    # Résumé final
    console.print(f"\n[bold green]{'─' * 60}[/bold green]")
    console.print(f"[bold green]✓ Pipeline terminé avec succès[/bold green]")
    console.print(f"[bold green]{'─' * 60}[/bold green]")
    
    console.print(f"\n[dim]Tickers analysés: {len(eligible_tickers)}/{len(original_tickers)}[/dim]")
    if excluded_tickers:
        console.print(f"[dim]Tickers exclus: {len(excluded_tickers)} ({', '.join(e['ticker'] for e in excluded_tickers)})[/dim]")
    console.print(f"[dim]Shortlist finale: out_compare/shortlist_tradable.csv[/dim]")


@main.command()
@click.option(
    "--output", "-o",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format.",
)
def status(output: str) -> None:
    """Show current trading status (and optionally send to Telegram)."""
    from envolees.profiles import get_profile, get_profile_summary
    from envolees.data.cache import cache_stats
    from pathlib import Path
    import json as json_module
    
    profile = get_profile()
    summary = get_profile_summary(profile)
    cache = cache_stats()
    
    # Lire la shortlist si elle existe
    shortlist_path = Path("out_compare/shortlist_tradable.csv")
    shortlist = []
    if shortlist_path.exists():
        import pandas as pd
        try:
            df = pd.read_csv(shortlist_path)
            shortlist = [(row["ticker"], row.get("oos_score", 0)) for _, row in df.iterrows()]
        except Exception:
            pass
    
    if output == "json":
        data = {
            "profile": summary,
            "cache": cache,
            "shortlist": [{"ticker": t, "score": s} for t, s in shortlist],
        }
        console.print(json_module.dumps(data, indent=2, default=str))
    else:
        console.print(f"\n[bold cyan]📊 Envolées Status[/bold cyan]\n")
        
        # Profil
        console.print(f"[bold]Profil:[/bold] {summary['name']} ({profile.description})")
        console.print(f"  Risque/trade: {summary['risk_per_trade']*100:.2f}%")
        console.print(f"  Budget/jour: {summary['daily_risk_budget']*100:.2f}%")
        console.print(f"  Max trades: {summary['max_concurrent_trades']}")
        console.print(f"  Stop après: {summary['stop_after_n_losses']} pertes")
        console.print()
        
        # Cache
        console.print(f"[bold]Cache:[/bold]")
        console.print(f"  Fichiers: {cache['n_files']}")
        console.print(f"  Taille: {cache['total_size_mb']} MB")
        console.print()
        
        # Shortlist
        if shortlist:
            console.print(f"[bold]Shortlist ({len(shortlist)} tickers):[/bold]")
            for ticker, score in shortlist:
                console.print(f"  • {ticker}: score {score:.3f}")
        else:
            console.print("[dim]Shortlist: (pas de fichier shortlist_tradable.csv)[/dim]")


@main.command()
@click.argument("message")
@click.option(
    "--level", "-l",
    type=click.Choice(["info", "warning", "critical"]),
    default="warning",
    help="Alert level (default: warning).",
)
def alert(message: str, level: str) -> None:
    """Send a manual alert."""
    from envolees.alerts import AlertSender
    
    console.print(f"\n[cyan]Sending alert (level: {level})...[/cyan]")
    
    sender = AlertSender()
    results = sender.send_alert(
        title="Alerte manuelle",
        message=message,
        level=level,
    )
    
    if not results:
        console.print("[yellow]No alert channels configured[/yellow]")
        return
    
    for channel, success in results.items():
        if success:
            console.print(f"[green]✓[/green] {channel}: sent")
        else:
            console.print(f"[red]✗[/red] {channel}: failed")


@main.command()
@click.option("--crypto/--no-crypto", default=True, help="Inclure les crypto")
@click.option("--indices/--no-indices", default=True, help="Inclure les indices")
@click.option("--stocks/--no-stocks", default=False, help="Inclure les actions")
@click.option("--max-priority", "-p", default=3, help="Priorité max (1=core, 5=marginal)")
@click.option("--gft-only", is_flag=True, help="Uniquement les instruments GFT")
@click.option("--output", "-o", default="", help="Fichier de sortie (vide = stdout)")
@click.option("--format", "-f", type=click.Choice(["list", "env", "json", "table"]), default="list", help="Format de sortie")
def instruments(
    crypto: bool,
    indices: bool,
    stocks: bool,
    max_priority: int,
    gft_only: bool,
    output: str,
    format: str,
) -> None:
    """
    Liste les instruments FTMO recommandés avec leur mapping Yahoo.
    
    Génère une liste de tickers compatible avec TICKERS= dans .env.
    
    Exemples:
    
        envolees instruments                     # Liste par défaut (forex + crypto + métaux)
        
        envolees instruments --no-crypto         # Sans crypto
        
        envolees instruments --format env        # Format TICKERS=... pour .env
        
        envolees instruments -p 2                # Seulement priorité 1-2 (core instruments)
    """
    from envolees.data.ftmo_instruments import (
        get_recommended_instruments,
        AssetType,
    )
    
    instruments_list = get_recommended_instruments(
        include_crypto=crypto,
        include_indices=indices,
        include_stocks=stocks,
        max_priority=max_priority,
        gft_compatible=gft_only,
    )
    
    # Grouper par type d'actif pour l'affichage
    by_type: dict[AssetType, list] = {}
    for inst in instruments_list:
        if inst.asset_type not in by_type:
            by_type[inst.asset_type] = []
        by_type[inst.asset_type].append(inst)
    
    # Générer la sortie selon le format
    if format == "table":
        table = Table(title="Instruments FTMO recommandés")
        table.add_column("Type", style="cyan")
        table.add_column("FTMO", style="green")
        table.add_column("Yahoo", style="yellow")
        table.add_column("Pri", justify="center")
        table.add_column("Gaps", justify="center")
        table.add_column("Notes", style="dim")
        
        for asset_type, insts in sorted(by_type.items(), key=lambda x: x[0].value):
            for inst in insts:
                table.add_row(
                    asset_type.value,
                    inst.ftmo_symbol,
                    inst.yahoo_symbols[0] if inst.yahoo_symbols else "-",
                    str(inst.priority),
                    str(inst.max_extra_gaps) if inst.max_extra_gaps else "-",
                    inst.notes or "",
                )
        
        console.print(table)
        console.print(f"\n[green]{len(instruments_list)}[/green] instruments")
        
    elif format == "env":
        # Format pour .env
        yahoo_tickers = [inst.yahoo_symbols[0] for inst in instruments_list if inst.yahoo_symbols]
        env_line = f"TICKERS={','.join(yahoo_tickers)}"
        
        if output:
            Path(output).write_text(env_line + "\n")
            console.print(f"[green]✓[/green] Écrit dans {output}")
        else:
            console.print(env_line)
    
    elif format == "json":
        import json
        
        data = [
            {
                "ftmo": inst.ftmo_symbol,
                "yahoo": inst.yahoo_symbols,
                "type": inst.asset_type.value,
                "priority": inst.priority,
                "max_gaps": inst.max_extra_gaps,
                "is_24_7": inst.is_24_7,
            }
            for inst in instruments_list
        ]
        
        json_str = json.dumps(data, indent=2)
        
        if output:
            Path(output).write_text(json_str)
            console.print(f"[green]✓[/green] Écrit dans {output}")
        else:
            console.print(json_str)
    
    else:  # list (défaut)
        yahoo_tickers = [inst.yahoo_symbols[0] for inst in instruments_list if inst.yahoo_symbols]
        
        if output:
            Path(output).write_text("\n".join(yahoo_tickers) + "\n")
            console.print(f"[green]✓[/green] {len(yahoo_tickers)} tickers écrits dans {output}")
        else:
            # Afficher par catégorie
            for asset_type, insts in sorted(by_type.items(), key=lambda x: x[0].value):
                console.print(f"\n[cyan]{asset_type.value}[/cyan] ({len(insts)}):")
                for inst in insts:
                    yahoo = inst.yahoo_symbols[0] if inst.yahoo_symbols else "?"
                    gaps_info = f" [dim](gaps tolérés: {inst.max_extra_gaps})[/dim]" if inst.max_extra_gaps else ""
                    console.print(f"  {inst.ftmo_symbol:15} → {yahoo:15}{gaps_info}")
            
            console.print(f"\n[green]Total: {len(instruments_list)} instruments[/green]")
            console.print("\n[dim]Pour générer un .env:[/dim]")
            console.print("[dim]  envolees instruments --format env > .env.tickers[/dim]")


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

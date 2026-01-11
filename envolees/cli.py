"""
CLI pour Envolées.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from envolees import __version__
from envolees.backtest import BacktestEngine, BacktestResult
from envolees.config import Config, get_penalties, get_tickers
from envolees.data import download_1h, resample_to_4h
from envolees.output import export_batch_summary, export_result, format_summary_line
from envolees.strategy import DonchianBreakoutStrategy

console = Console()


def run_single_backtest(
    ticker: str,
    penalty: float,
    cfg: Config,
) -> BacktestResult | None:
    """Exécute un backtest pour un ticker et une pénalité."""
    try:
        df_1h = download_1h(ticker, cfg)
        df_4h = resample_to_4h(df_1h)

        strategy = DonchianBreakoutStrategy(cfg)
        engine = BacktestEngine(cfg, strategy, ticker, penalty)

        return engine.run(df_4h)
    except Exception as e:
        console.print(f"[red]✗[/red] {ticker} PEN {penalty:.2f}: {e}")
        return None


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
def run(
    tickers: str | None,
    penalties: str | None,
    output: str | None,
    mode: str | None,
) -> None:
    """Run backtest on tickers with specified penalties."""
    cfg = Config.from_env()

    # Override depuis CLI
    if output:
        cfg = Config(
            **{**cfg.__dict__, "output_dir": output}
        )
    if mode:
        cfg = Config(
            **{**cfg.__dict__, "daily_equity_mode": mode}
        )

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

    console.print(f"\n[bold cyan]🚀 Envolées v{__version__}[/bold cyan]")
    console.print(f"   Tickers: {len(ticker_list)} │ Penalties: {len(penalty_list)}")
    console.print(f"   Mode: {cfg.daily_equity_mode} │ Output: {cfg.output_dir}\n")

    results: list[BacktestResult] = []
    errors: list[tuple[str, float, str]] = []

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

                result = run_single_backtest(ticker, penalty, cfg)

                if result is not None:
                    results.append(result)
                    export_result(result, cfg.output_dir)
                    console.print(f"[green]✓[/green] {format_summary_line(result)}")
                else:
                    errors.append((ticker, penalty, "Download or backtest failed"))

                progress.advance(task)

    # Export summary
    if results:
        summary_df = export_batch_summary(results, cfg.output_dir)

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

    # Erreurs
    if errors:
        console.print(f"\n[yellow]⚠ {len(errors)} erreur(s)[/yellow]")
        for t, p, e in errors:
            console.print(f"  - {t} PEN {p:.2f}: {e}")

    console.print(f"\n[dim]Résultats: {cfg.output_dir}/results.csv[/dim]")


@main.command()
@click.argument("ticker")
@click.option("--penalty", "-p", default=0.10, help="Execution penalty (ATR multiple).")
@click.option("--output", "-o", default=None, help="Output directory.")
def single(ticker: str, penalty: float, output: str | None) -> None:
    """Run backtest on a single ticker."""
    cfg = Config.from_env()
    if output:
        cfg = Config(**{**cfg.__dict__, "output_dir": output})

    console.print(f"\n[cyan]Running {ticker} with penalty {penalty:.2f}...[/cyan]")

    result = run_single_backtest(ticker, penalty, cfg)

    if result is None:
        console.print("[red]Backtest failed.[/red]")
        sys.exit(1)

    export_result(result, cfg.output_dir)
    console.print(f"\n[green]✓[/green] {format_summary_line(result)}")

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
    table.add_row("Output Dir", cfg.output_dir)

    console.print(table)


if __name__ == "__main__":
    main()

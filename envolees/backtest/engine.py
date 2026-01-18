"""
Moteur de backtest principal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import pandas as pd

from envolees.backtest.position import OpenPosition, PendingOrder, TradeRecord
from envolees.backtest.prop_sim import DailyState, PropSimulator

if TYPE_CHECKING:
    from envolees.config import Config
    from envolees.strategy.base import Strategy


@dataclass
class EquityRow:
    """Ligne de la courbe d'equity."""

    time: pd.Timestamp
    balance: float
    equity: float
    dd_global: float
    dd_daily: float
    halt_today: bool

    def to_dict(self) -> dict:
        return {
            "time": self.time,
            "balance": self.balance,
            "equity": self.equity,
            "dd_global": self.dd_global,
            "dd_daily": self.dd_daily,
            "halt_today": self.halt_today,
        }


@dataclass
class BacktestResult:
    """Résultat d'un backtest."""

    ticker: str
    exec_penalty_atr: float
    trades: list[TradeRecord]
    equity_curve: list[EquityRow]
    daily_stats: list[dict]
    summary: dict

    def trades_df(self) -> pd.DataFrame:
        """Retourne les trades en DataFrame."""
        if not self.trades:
            return pd.DataFrame()
        return pd.DataFrame([t.to_dict() for t in self.trades])

    def equity_df(self) -> pd.DataFrame:
        """Retourne la courbe d'equity en DataFrame."""
        if not self.equity_curve:
            return pd.DataFrame()
        df = pd.DataFrame([e.to_dict() for e in self.equity_curve])
        return df.set_index("time")

    def daily_df(self) -> pd.DataFrame:
        """Retourne les stats journalières en DataFrame."""
        return pd.DataFrame(self.daily_stats)


class BacktestEngine:
    """
    Moteur de backtest générique.

    Exécute une stratégie sur des données OHLCV avec :
    - Gestion des ordres stop en attente
    - Simulation des règles prop firm
    - Tracking de l'equity et du drawdown
    """

    def __init__(
        self,
        cfg: Config,
        strategy: Strategy,
        ticker: str,
        exec_penalty_atr: float,
    ) -> None:
        self.cfg = cfg
        self.strategy = strategy
        self.ticker = ticker
        self.exec_penalty_atr = exec_penalty_atr

        # État
        self.balance = cfg.start_balance
        self.open_position: OpenPosition | None = None
        self.pending_order: PendingOrder | None = None

        # Prop simulation
        self.prop_sim = PropSimulator(cfg)

        # Daily tracking
        self.daily_state = DailyState()
        self.daily_stats: list[dict] = []

        # Résultats
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[EquityRow] = []

    def _compute_equity(self, row: pd.Series) -> float:
        """Calcule l'equity mark-to-market."""
        if self.open_position is None:
            return self.balance

        if self.cfg.daily_equity_mode == "close":
            ref_price = float(row["Close"])
        else:
            # Worst-case intrabar
            if self.open_position.direction == "LONG":
                ref_price = float(row["Low"])
            else:
                ref_price = float(row["High"])

        unreal_r = self.open_position.compute_unrealized_r(ref_price)
        return self.balance + unreal_r * self.open_position.risk_cash

    def _handle_day_change(self, day, equity: float) -> None:
        """Gère le changement de jour."""
        # Flush stats du jour précédent
        if self.daily_state.current_day is not None:
            self.daily_stats.append({
                "date": str(self.daily_state.current_day),
                "start_equity": self.daily_state.start_equity,
                "min_equity": self.daily_state.min_equity,
                "max_daily_dd_pct": self.daily_state.daily_dd,
                "losses_closed": self.daily_state.losses_closed,
                "halted": self.daily_state.halted,
            })

        # Reset pour nouveau jour
        self.daily_state.reset(day, equity)
        self.prop_sim.on_new_day(day, equity)

    def _process_open_position(self, row: pd.Series, bar_idx: int, ts: pd.Timestamp) -> None:
        """Gère les sorties SL/TP d'une position ouverte."""
        if self.open_position is None:
            return

        exit_reason, exit_price = self.open_position.check_exit(
            float(row["High"]),
            float(row["Low"]),
            self.cfg.conservative_same_bar,
        )

        if exit_reason is None:
            return

        # Calcul P&L
        result_r = self.open_position.compute_pnl_r(exit_price)
        ## ajouut pànalité supplémentaire, à commmenter si problèmatique
        SLIP_PENALTY = 0.05  # 5% du R
        
        if exit_reason == "SL":
            result_r = result_r * (1 + SLIP_PENALTY)  # Perte aggravée
        elif exit_reason == "TP":
            result_r = result_r * (1 - SLIP_PENALTY)  # Gain réduit
        ## fin de la pénalité supplémentaire
        result_cash = result_r * self.open_position.risk_cash
        self.balance += result_cash

        # Enregistrement
        trade = TradeRecord(
            ticker=self.ticker,
            penalty_atr=self.exec_penalty_atr,
            direction=self.open_position.direction,
            ts_signal=self.open_position.ts_signal,
            ts_entry=self.open_position.ts_entry,
            ts_exit=ts,
            entry=self.open_position.entry,
            sl=self.open_position.sl,
            tp=self.open_position.tp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            atr_signal=self.open_position.atr_signal,
            result_r=result_r,
            result_cash=result_cash,
            balance_after=self.balance,
            duration_bars=bar_idx - self.open_position.entry_bar_idx,
        )
        self.trades.append(trade)

        # Update prop sim
        self.prop_sim.on_trade_closed(result_r, self.balance)

        # Reset
        self.open_position = None
        self.pending_order = None

        # Update daily min
        self.daily_state.update_min_equity(self.balance)

    def _process_pending_order(self, row: pd.Series, bar_idx: int, ts: pd.Timestamp) -> None:
        """Gère le déclenchement d'un ordre en attente."""
        if self.open_position is not None or self.pending_order is None:
            return

        # Expiration ?
        if self.pending_order.is_expired(bar_idx):
            self.pending_order = None
            return

        # Déclenchement ?
        if not self.pending_order.is_triggered(float(row["High"]), float(row["Low"])):
            return

        # Halted ?
        if self.prop_sim.is_halted:
            return

        # Calcul entry/SL/TP avec pénalité
        from envolees.strategy.base import Signal

        signal = Signal(
            direction=self.pending_order.direction,
            entry_level=self.pending_order.entry_level,
            atr_at_signal=self.pending_order.atr_signal,
            timestamp=self.pending_order.ts_signal,
        )
        entry, sl, tp = self.strategy.compute_entry_sl_tp(signal, self.exec_penalty_atr)

        # Ouverture position
        self.open_position = OpenPosition(
            direction=self.pending_order.direction,
            entry=entry,
            sl=sl,
            tp=tp,
            ts_signal=self.pending_order.ts_signal,
            ts_entry=ts,
            atr_signal=self.pending_order.atr_signal,
            entry_bar_idx=bar_idx,
            risk_cash=self.balance * self.cfg.risk_per_trade,
        )
        self.pending_order = None

    def _generate_new_signal(self, df: pd.DataFrame, bar_idx: int) -> None:
        """Génère un nouveau signal si conditions remplies."""
        if self.open_position is not None or self.pending_order is not None:
            return

        if self.prop_sim.is_halted:
            return

        # Demande à la stratégie
        signal = self.strategy.generate_signal(df, bar_idx, None, None)
        if signal is not None:
            self.pending_order = PendingOrder.from_signal(signal, bar_idx)

    def run(self, df: pd.DataFrame) -> BacktestResult:
        """
        Exécute le backtest.

        Args:
            df: DataFrame OHLCV (sera enrichi avec les indicateurs)

        Returns:
            BacktestResult avec trades, equity, stats
        """
        # Préparation indicateurs
        df = self.strategy.prepare_indicators(df)
        idx = df.index.to_list()

        for bar_idx in range(len(df)):
            ts = idx[bar_idx]
            row = df.iloc[bar_idx]
            day = ts.date()

            # Equity mark-to-market
            equity = self._compute_equity(row)

            # Changement de jour ?
            if self.daily_state.current_day is None or day != self.daily_state.current_day:
                self._handle_day_change(day, equity)

            # Update equity tracking
            self.daily_state.update_min_equity(equity)
            self.prop_sim.update_equity(equity, day)

            # Enregistrement equity
            self.equity_curve.append(EquityRow(
                time=ts,
                balance=self.balance,
                equity=equity,
                dd_global=self.prop_sim.global_dd(equity),
                dd_daily=self.daily_state.daily_dd,
                halt_today=self.prop_sim.is_halted,
            ))

            # 1. Gestion position ouverte (SL/TP)
            self._process_open_position(row, bar_idx, ts)

            # 2. Gestion ordre en attente
            self._process_pending_order(row, bar_idx, ts)

            # 3. Génération nouveau signal
            self._generate_new_signal(df, bar_idx)

        # Flush dernière journée
        if self.daily_state.current_day is not None:
            self.daily_stats.append({
                "date": str(self.daily_state.current_day),
                "start_equity": self.daily_state.start_equity,
                "min_equity": self.daily_state.min_equity,
                "max_daily_dd_pct": self.daily_state.daily_dd,
                "losses_closed": self.daily_state.losses_closed,
                "halted": self.daily_state.halted,
            })

        # Construction summary
        summary = self._build_summary(len(df))

        return BacktestResult(
            ticker=self.ticker,
            exec_penalty_atr=self.exec_penalty_atr,
            trades=self.trades,
            equity_curve=self.equity_curve,
            daily_stats=self.daily_stats,
            summary=summary,
        )

    def _build_summary(self, n_bars: int) -> dict:
        """Construit le dictionnaire de résumé."""
        trades_df = pd.DataFrame([t.to_dict() for t in self.trades]) if self.trades else pd.DataFrame()
        daily_df = pd.DataFrame(self.daily_stats) if self.daily_stats else pd.DataFrame()

        if len(trades_df):
            win_rate = float((trades_df["result_r"] > 0).mean())
            exp_r = float(trades_df["result_r"].mean())
            gross_win = trades_df.loc[trades_df["result_r"] > 0, "result_r"].sum()
            gross_loss = abs(trades_df.loc[trades_df["result_r"] < 0, "result_r"].sum())
            pf = float(gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
        else:
            win_rate, exp_r, pf = 0.0, 0.0, 0.0

        prop_stats = self.prop_sim.get_stats()

        return {
            "ticker": self.ticker,
            "exec_penalty_atr": self.exec_penalty_atr,
            "bars_4h": n_bars,
            "start_balance": self.cfg.start_balance,
            "end_balance": self.balance,
            "risk_per_trade": self.cfg.risk_per_trade,
            "n_trades": len(self.trades),
            "win_rate": win_rate,
            "profit_factor": pf,
            "expectancy_r": exp_r,
            "prop": {
                "daily_equity_mode": self.cfg.daily_equity_mode,
                "max_daily_dd_pct": float(daily_df["max_daily_dd_pct"].max()) if len(daily_df) else 0.0,
                "p99_daily_dd_pct": float(daily_df["max_daily_dd_pct"].quantile(0.99)) if len(daily_df) else 0.0,
                "n_daily_violate_ftmo_bars": prop_stats["n_violate_ftmo_bars"],
                "n_daily_violate_gft_bars": prop_stats["n_violate_gft_bars"],
                "n_total_violate_bars": prop_stats["n_violate_total_bars"],
            },
            "params": {
                "ema_period": self.cfg.ema_period,
                "atr_period": self.cfg.atr_period,
                "donchian_n": self.cfg.donchian_n,
                "buffer_atr": self.cfg.buffer_atr,
                "sl_atr": self.cfg.sl_atr,
                "tp_r": self.cfg.tp_r,
                "vol_quantile": self.cfg.vol_quantile,
                "vol_window_bars": self.cfg.vol_window_bars,
                "order_valid_bars": self.cfg.order_valid_bars,
                "conservative_same_bar": self.cfg.conservative_same_bar,
                "daily_dd_ftmo": self.cfg.daily_dd_ftmo,
                "daily_dd_gft": self.cfg.daily_dd_gft,
                "daily_kill_switch": self.cfg.daily_kill_switch,
                "stop_after_n_losses": self.cfg.stop_after_n_losses,
            },
            "notes": [
                "Backtest bar-based 4H ; déclenchement STOP via High/Low.",
                "Si SL et TP touchés même bougie, SL prioritaire (conservateur).",
                "Pénalité d'exécution appliquée à l'entrée (k×ATR au signal), SL/TP recalculés.",
                "Daily DD simulé avec mark-to-market (close ou worst).",
                "Reset daily à minuit (Europe/Paris).",
            ],
        }

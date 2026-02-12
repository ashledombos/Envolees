"""
Moteur de backtest principal.

Supporte deux modes d'exécution :
- Mode 4H seul (df_1h=None) : exécution sur OHLC 4H avec heuristique SL+TP
- Mode intrabar (df_1h fourni) : exécution sur bougies 1H chronologiques,
  élimine toute ambiguïté d'ordre des extrêmes
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
    - Positions multiples simultanées par instrument (empilage momentum)
    - Un seul ordre stop en attente à la fois (recalculé chaque barre)
    - Simulation des règles prop firm
    - Tracking de l'equity et du drawdown
    - Exécution intrabar 1H optionnelle (élimine les ambiguïtés OHLC)
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
        self.open_positions: list[OpenPosition] = []
        self.pending_order: PendingOrder | None = None

        # Prop simulation
        self.prop_sim = PropSimulator(cfg)

        # Daily tracking
        self.daily_state = DailyState()
        self.daily_stats: list[dict] = []

        # Résultats
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[EquityRow] = []

    # ── Helpers ───────────────────────────────────────────────────────

    def _compute_equity(self, row: pd.Series) -> float:
        """Calcule l'equity mark-to-market (somme de toutes les positions)."""
        if not self.open_positions:
            return self.balance

        total_unrealized = 0.0
        for pos in self.open_positions:
            if self.cfg.daily_equity_mode == "close":
                ref_price = float(row["Close"])
            else:
                # Worst-case intrabar
                if pos.direction == "LONG":
                    ref_price = float(row["Low"])
                else:
                    ref_price = float(row["High"])

            unreal_r = pos.compute_unrealized_r(ref_price)
            total_unrealized += unreal_r * pos.risk_cash

        return self.balance + total_unrealized

    def _handle_day_change(self, day, equity: float) -> None:
        """Gère le changement de jour."""
        if self.daily_state.current_day is not None:
            self.daily_stats.append({
                "date": str(self.daily_state.current_day),
                "start_equity": self.daily_state.start_equity,
                "min_equity": self.daily_state.min_equity,
                "max_daily_dd_pct": self.daily_state.daily_dd,
                "losses_closed": self.daily_state.losses_closed,
                "halted": self.daily_state.halted,
            })

        self.daily_state.reset(day, equity)
        self.prop_sim.on_new_day(day, equity)

    def _close_position(
        self, pos: OpenPosition, exit_price: float, exit_reason: str,
        bar_idx: int, ts: pd.Timestamp,
    ) -> None:
        """Ferme une position et enregistre le trade."""
        result_r = pos.compute_pnl_r(exit_price)
        result_cash = result_r * pos.risk_cash
        self.balance += result_cash

        self.trades.append(TradeRecord(
            ticker=self.ticker,
            penalty_atr=self.exec_penalty_atr,
            direction=pos.direction,
            ts_signal=pos.ts_signal,
            ts_entry=pos.ts_entry,
            ts_exit=ts,
            entry=pos.entry,
            sl=pos.sl,
            tp=pos.tp,
            exit_price=exit_price,
            exit_reason=exit_reason,
            atr_signal=pos.atr_signal,
            result_r=result_r,
            result_cash=result_cash,
            balance_after=self.balance,
            duration_bars=bar_idx - pos.entry_bar_idx,
        ))

        self.prop_sim.on_trade_closed(result_r, self.balance)
        self.daily_state.update_min_equity(self.balance)

    def _try_trigger_pending(
        self, high: float, low: float, bar_idx: int, ts: pd.Timestamp,
    ) -> OpenPosition | None:
        """Tente de déclencher le pending order. Retourne la position créée ou None."""
        if self.pending_order is None:
            return None
        if not self.pending_order.is_triggered(high, low):
            return None
        if self.prop_sim.is_halted:
            return None

        from envolees.strategy.base import Signal

        signal = Signal(
            direction=self.pending_order.direction,
            entry_level=self.pending_order.entry_level,
            atr_at_signal=self.pending_order.atr_signal,
            timestamp=self.pending_order.ts_signal,
        )
        entry, sl, tp = self.strategy.compute_entry_sl_tp(signal, self.exec_penalty_atr)

        new_pos = OpenPosition(
            direction=self.pending_order.direction,
            entry=entry, sl=sl, tp=tp,
            ts_signal=self.pending_order.ts_signal,
            ts_entry=ts,
            atr_signal=self.pending_order.atr_signal,
            entry_bar_idx=bar_idx,
            risk_cash=self.balance * self.cfg.risk_per_trade,
        )

        # Configurer le trailing stop si activé
        if self.cfg.exit_mode == "trailing_atr":
            new_pos.trailing_atr_dist = self.cfg.trailing_atr * signal.atr_at_signal
            # TP à 0 si tp_r=0 (laisser courir, seul le trailing ferme)
            if self.cfg.tp_r == 0:
                new_pos.tp = 0.0
            # Activation : prix doit atteindre entry + activation_r × risk
            if self.cfg.trailing_activation_r > 0:
                risk = abs(entry - sl)
                if self.pending_order.direction == "LONG":
                    new_pos.trailing_activation_price = entry + self.cfg.trailing_activation_r * risk
                else:
                    new_pos.trailing_activation_price = entry - self.cfg.trailing_activation_r * risk
        self.open_positions.append(new_pos)
        self.pending_order = None
        return new_pos

    # ── Mode 4H (fallback, avec heuristique SL+TP) ──────────────────

    def _process_open_positions_4h(self, row: pd.Series, bar_idx: int, ts: pd.Timestamp) -> None:
        """Gère les sorties SL/TP sur OHLC 4H (avec heuristique same-bar)."""
        closed_indices = []

        for i, pos in enumerate(self.open_positions):
            exit_reason, exit_price = pos.check_exit(
                float(row["High"]),
                float(row["Low"]),
                self.cfg.conservative_same_bar,
                open_price=float(row["Open"]),
            )

            if exit_reason is None:
                continue

            self._close_position(pos, exit_price, exit_reason, bar_idx, ts)
            closed_indices.append(i)

        for i in reversed(closed_indices):
            self.open_positions.pop(i)

    def _process_pending_order_4h(self, row: pd.Series, bar_idx: int, ts: pd.Timestamp) -> None:
        """Déclenchement pending order sur OHLC 4H (position survit la barre d'entrée)."""
        self._try_trigger_pending(float(row["High"]), float(row["Low"]), bar_idx, ts)

    # ── Mode intrabar 1H ─────────────────────────────────────────────

    @staticmethod
    def _build_sub_bar_map(
        df_4h: pd.DataFrame, df_1h: pd.DataFrame,
    ) -> dict[pd.Timestamp, pd.DataFrame]:
        """Associe chaque barre 4H à ses sous-barres 1H.

        La barre 4H à timestamp T contient les 1H dans [T, T+4h).
        """
        freq = pd.Timedelta("4h")
        result = {}
        df_1h_sorted = df_1h.sort_index()
        for ts_4h in df_4h.index:
            mask = (df_1h_sorted.index >= ts_4h) & (df_1h_sorted.index < ts_4h + freq)
            sub = df_1h_sorted.loc[mask]
            if not sub.empty:
                result[ts_4h] = sub
        return result

    def _execute_intrabar(
        self, sub_bars: pd.DataFrame, bar_idx_4h: int, ts_4h: pd.Timestamp,
    ) -> None:
        """Exécute l'entry et les sorties sur les sous-barres 1H.

        Pour chaque bougie 1H chronologique :
        1. Vérifie SL/TP des positions ouvertes (conservateur : SL gagne si ambigu)
        2. Vérifie déclenchement pending order
        3. Si pending déclenché, vérifie immédiatement SL/TP sur cette même 1H

        Pas d'heuristique : l'ordre chronologique 1H résout les ambiguïtés.
        """
        for ts_1h, row_1h in sub_bars.iterrows():
            high = float(row_1h["High"])
            low = float(row_1h["Low"])

            # ── 1. Sorties des positions ouvertes ──
            closed_indices = []
            for i, pos in enumerate(self.open_positions):
                # Pas d'heuristique (open_price=None), conservateur (SL gagne)
                exit_reason, exit_price = pos.check_exit(
                    high, low,
                    conservative_same_bar=True,
                    open_price=None,
                )
                if exit_reason is None:
                    continue
                self._close_position(pos, exit_price, exit_reason, bar_idx_4h, ts_1h)
                closed_indices.append(i)

            for i in reversed(closed_indices):
                self.open_positions.pop(i)

            # ── 2. Déclenchement pending order ──
            new_pos = self._try_trigger_pending(high, low, bar_idx_4h, ts_1h)

            # ── 3. Si position vient d'ouvrir, vérifier SL/TP immédiatement ──
            # Sur cette même bougie 1H, le prix a pu toucher l'entry ET le SL.
            # À 1H de granularité, conservateur = SL gagne.
            if new_pos is not None:
                exit_reason, exit_price = new_pos.check_exit(
                    high, low,
                    conservative_same_bar=True,
                    open_price=None,
                )
                if exit_reason is not None:
                    self._close_position(
                        new_pos, exit_price, exit_reason, bar_idx_4h, ts_1h,
                    )
                    self.open_positions.remove(new_pos)

    # ── Recalcul signal (toujours sur 4H) ────────────────────────────

    def _update_signal(self, df: pd.DataFrame, bar_idx: int) -> None:
        """Recalcule le signal à chaque barre 4H.

        - Si conditions remplies → place ou remplace le pending order
        - Si conditions plus remplies → annule le pending order
        - Respect du plafond de positions simultanées
        """
        if self.prop_sim.is_halted:
            self.pending_order = None
            return

        if (
            self.cfg.max_concurrent_trades > 0
            and len(self.open_positions) >= self.cfg.max_concurrent_trades
        ):
            self.pending_order = None
            return

        signal = self.strategy.generate_signal(df, bar_idx, None, None)

        if signal is not None:
            self.pending_order = PendingOrder.from_signal(signal, bar_idx)
        else:
            self.pending_order = None

    # ── Boucle principale ────────────────────────────────────────────

    def run(
        self,
        df: pd.DataFrame,
        df_1h: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """
        Exécute le backtest.

        Args:
            df: DataFrame OHLCV 4H (sera enrichi avec les indicateurs)
            df_1h: DataFrame OHLCV 1H optionnel. Si fourni, l'exécution
                   (entry, SL, TP) utilise les bougies 1H chronologiques
                   au lieu des OHLC 4H. Élimine les ambiguïtés intrabar.

        Returns:
            BacktestResult avec trades, equity, stats
        """
        intrabar = df_1h is not None and len(df_1h) > 0

        # Préparation indicateurs (sur 4H)
        df = self.strategy.prepare_indicators(df)
        idx = df.index.to_list()

        # Mapping 4H → 1H
        sub_bar_map = self._build_sub_bar_map(df, df_1h) if intrabar else {}

        for bar_idx in range(len(df)):
            ts = idx[bar_idx]
            row = df.iloc[bar_idx]
            day = ts.date()

            # Equity mark-to-market (sur la barre 4H pour le tracking)
            equity = self._compute_equity(row)

            # Changement de jour ?
            if self.daily_state.current_day is None or day != self.daily_state.current_day:
                self._handle_day_change(day, equity)

            # Update equity tracking
            self.daily_state.update_min_equity(equity)
            self.prop_sim.update_equity(equity, day)

            # Enregistrement equity (1 point par barre 4H)
            self.equity_curve.append(EquityRow(
                time=ts,
                balance=self.balance,
                equity=equity,
                dd_global=self.prop_sim.global_dd(equity),
                dd_daily=self.daily_state.daily_dd,
                halt_today=self.prop_sim.is_halted,
            ))

            # ── Exécution ──
            if intrabar and ts in sub_bar_map:
                self._execute_intrabar(sub_bar_map[ts], bar_idx, ts)
            else:
                self._process_open_positions_4h(row, bar_idx, ts)
                self._process_pending_order_4h(row, bar_idx, ts)

            # Recalcul signal (toujours sur 4H)
            self._update_signal(df, bar_idx)

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

        summary = self._build_summary(len(df), intrabar)

        return BacktestResult(
            ticker=self.ticker,
            exec_penalty_atr=self.exec_penalty_atr,
            trades=self.trades,
            equity_curve=self.equity_curve,
            daily_stats=self.daily_stats,
            summary=summary,
        )

    def _build_summary(self, n_bars: int, intrabar: bool = False) -> dict:
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

        exec_mode = "intrabar_1h" if intrabar else "ohlc_4h"

        return {
            "ticker": self.ticker,
            "exec_penalty_atr": self.exec_penalty_atr,
            "bars": n_bars,
            "timeframe": self.cfg.timeframe if hasattr(self.cfg, 'timeframe') else "4h",
            "execution_mode": exec_mode,
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
                "proximity_atr": self.cfg.proximity_atr,
                "sl_atr": self.cfg.sl_atr,
                "tp_r": self.cfg.tp_r,
                "exit_mode": self.cfg.exit_mode,
                "trailing_atr": self.cfg.trailing_atr if self.cfg.exit_mode == "trailing_atr" else None,
                "trailing_activation_r": self.cfg.trailing_activation_r if self.cfg.exit_mode == "trailing_atr" else None,
                "vol_quantile": self.cfg.vol_quantile,
                "vol_window_bars": self.cfg.vol_window_bars,
                "conservative_same_bar": self.cfg.conservative_same_bar,
                "daily_dd_ftmo": self.cfg.daily_dd_ftmo,
                "daily_dd_gft": self.cfg.daily_dd_gft,
                "daily_kill_switch": self.cfg.daily_kill_switch,
                "stop_after_n_losses": self.cfg.stop_after_n_losses,
            },
            "notes": [
                f"Exécution : {exec_mode}.",
                "Signaux calculés sur 4H ; stop proactif pré-placé sur le bord du canal.",
                "Signal recalculé à chaque barre 4H (le canal bouge, le stop suit).",
                "Positions multiples autorisées (empilage momentum), 1 seul pending order.",
                "Intrabar 1H : ordre chronologique élimine les ambiguïtés OHLC."
                if intrabar else
                "4H fallback : heuristique SL+TP par plausibilité du chemin.",
                "Pénalité d'exécution appliquée à l'entrée (k×ATR au signal), SL/TP recalculés.",
                "Daily DD simulé avec mark-to-market (close ou worst).",
                "Reset daily à minuit (Europe/Paris).",
            ],
        }

"""
Diagnostic : isole l'impact de chaque changement v2 sur un ticker.

Usage:
    python diagnostic.py EURUSD=X
    python diagnostic.py GBPUSD=X --penalty 0.10

Compare 4 configurations :
  A. Legacy   : signal confirmé (close > canal), 1 position max, pas d'heuristique
  B. Proactif : signal proactif,                 1 position max, pas d'heuristique
  C. Stacking : signal proactif,                 3 positions max, pas d'heuristique
  D. Full v2  : signal proactif,                 3 positions max, heuristiques same-bar
"""

import sys
import os
from copy import deepcopy
from dataclasses import replace

# Ajouter le répertoire courant au path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

from envolees.config import Config
from envolees.data import download_1h, resample_to_timeframe
from envolees.strategy.donchian_breakout import DonchianBreakoutStrategy
from envolees.strategy.base import Signal, Position
from envolees.backtest.engine import BacktestEngine
from envolees.backtest.position import OpenPosition, PendingOrder, TradeRecord


# ─── Stratégie legacy (signal confirmé par le close) ────────────────────────

class LegacyDonchianStrategy(DonchianBreakoutStrategy):
    """Version originale : signal quand close > canal (post-breakout)."""

    def generate_signal(self, df, bar_idx, current_position, pending_signal):
        if current_position is not None or pending_signal is not None:
            return None

        row = df.iloc[bar_idx]
        ts = df.index[bar_idx]

        if not self._indicators_ready(row):
            return None
        if self._in_no_trade_window(ts):
            return None
        if not bool(row["VOL_ok"]):
            return None

        close = float(row["Close"])
        ema = float(row["EMA"])
        atr = float(row["ATR"])
        buffer = self.cfg.buffer_atr * atr
        d_high = float(row["D_high"])
        d_low = float(row["D_low"])

        if close > ema and close > (d_high + buffer):
            return Signal(
                direction="LONG",
                entry_level=d_high + buffer,
                atr_at_signal=atr,
                timestamp=ts,
                expiry_bars=self.cfg.order_valid_bars,
            )
        if close < ema and close < (d_low - buffer):
            return Signal(
                direction="SHORT",
                entry_level=d_low - buffer,
                atr_at_signal=atr,
                timestamp=ts,
                expiry_bars=self.cfg.order_valid_bars,
            )
        return None


# ─── Moteur legacy (1 position, pas d'heuristique, avec expiry) ─────────────

class LegacyEngine(BacktestEngine):
    """Version originale : 1 position, pas d'heuristique same-bar."""

    def __init__(self, cfg, strategy, ticker, exec_penalty_atr):
        super().__init__(cfg, strategy, ticker, exec_penalty_atr)

    def _process_open_positions(self, row, bar_idx, ts):
        """1 seule position, check_exit sans open_price (pas d'heuristique)."""
        closed_indices = []
        for i, pos in enumerate(self.open_positions):
            exit_reason, exit_price = pos.check_exit(
                float(row["High"]),
                float(row["Low"]),
                self.cfg.conservative_same_bar,
                open_price=None,  # ← pas d'heuristique
            )
            if exit_reason is None:
                continue

            result_r = pos.compute_pnl_r(exit_price)
            result_cash = result_r * pos.risk_cash
            self.balance += result_cash

            self.trades.append(TradeRecord(
                ticker=self.ticker, penalty_atr=self.exec_penalty_atr,
                direction=pos.direction, ts_signal=pos.ts_signal,
                ts_entry=pos.ts_entry, ts_exit=ts,
                entry=pos.entry, sl=pos.sl, tp=pos.tp,
                exit_price=exit_price, exit_reason=exit_reason,
                atr_signal=pos.atr_signal, result_r=result_r,
                result_cash=result_cash, balance_after=self.balance,
                duration_bars=bar_idx - pos.entry_bar_idx,
            ))
            self.prop_sim.on_trade_closed(result_r, self.balance)
            closed_indices.append(i)

        for i in reversed(closed_indices):
            self.open_positions.pop(i)
        if closed_indices:
            self.daily_state.update_min_equity(self.balance)

    def _process_pending_order(self, row, bar_idx, ts):
        """Déclenchement simple, pas de same-bar entry+SL check."""
        if self.pending_order is None:
            return
        if not self.pending_order.is_triggered(float(row["High"]), float(row["Low"])):
            return
        if self.prop_sim.is_halted:
            return

        signal = Signal(
            direction=self.pending_order.direction,
            entry_level=self.pending_order.entry_level,
            atr_at_signal=self.pending_order.atr_signal,
            timestamp=self.pending_order.ts_signal,
        )
        entry, sl, tp = self.strategy.compute_entry_sl_tp(signal, self.exec_penalty_atr)

        new_pos = OpenPosition(
            direction=self.pending_order.direction, entry=entry, sl=sl, tp=tp,
            ts_signal=self.pending_order.ts_signal, ts_entry=ts,
            atr_signal=self.pending_order.atr_signal, entry_bar_idx=bar_idx,
            risk_cash=self.balance * self.cfg.risk_per_trade,
        )
        self.open_positions.append(new_pos)
        self.pending_order = None

    def _update_signal(self, df, bar_idx):
        """Version legacy : 1 position max, pas de recalcul si position ouverte."""
        if self.prop_sim.is_halted:
            self.pending_order = None
            return

        # Guard legacy : pas de signal si position ouverte OU pending
        if self.open_positions or self.pending_order is not None:
            return

        signal = self.strategy.generate_signal(df, bar_idx, None, None)
        if signal is not None:
            self.pending_order = PendingOrder.from_signal(signal, bar_idx)
        else:
            self.pending_order = None


# ─── Moteur single (1 position, recalcul continu, pas d'heuristique) ────────

class SingleNoHeuristicEngine(BacktestEngine):
    """Signal proactif + recalcul continu, mais 1 position et pas d'heuristique."""

    def _process_open_positions(self, row, bar_idx, ts):
        closed_indices = []
        for i, pos in enumerate(self.open_positions):
            exit_reason, exit_price = pos.check_exit(
                float(row["High"]), float(row["Low"]),
                self.cfg.conservative_same_bar,
                open_price=None,  # pas d'heuristique SL+TP
            )
            if exit_reason is None:
                continue
            result_r = pos.compute_pnl_r(exit_price)
            result_cash = result_r * pos.risk_cash
            self.balance += result_cash
            self.trades.append(TradeRecord(
                ticker=self.ticker, penalty_atr=self.exec_penalty_atr,
                direction=pos.direction, ts_signal=pos.ts_signal,
                ts_entry=pos.ts_entry, ts_exit=ts,
                entry=pos.entry, sl=pos.sl, tp=pos.tp,
                exit_price=exit_price, exit_reason=exit_reason,
                atr_signal=pos.atr_signal, result_r=result_r,
                result_cash=result_cash, balance_after=self.balance,
                duration_bars=bar_idx - pos.entry_bar_idx,
            ))
            self.prop_sim.on_trade_closed(result_r, self.balance)
            closed_indices.append(i)
        for i in reversed(closed_indices):
            self.open_positions.pop(i)
        if closed_indices:
            self.daily_state.update_min_equity(self.balance)

    def _process_pending_order(self, row, bar_idx, ts):
        """Pas de same-bar entry+SL check."""
        if self.pending_order is None:
            return
        if not self.pending_order.is_triggered(float(row["High"]), float(row["Low"])):
            return
        if self.prop_sim.is_halted:
            return
        signal = Signal(
            direction=self.pending_order.direction,
            entry_level=self.pending_order.entry_level,
            atr_at_signal=self.pending_order.atr_signal,
            timestamp=self.pending_order.ts_signal,
        )
        entry, sl, tp = self.strategy.compute_entry_sl_tp(signal, self.exec_penalty_atr)
        new_pos = OpenPosition(
            direction=self.pending_order.direction, entry=entry, sl=sl, tp=tp,
            ts_signal=self.pending_order.ts_signal, ts_entry=ts,
            atr_signal=self.pending_order.atr_signal, entry_bar_idx=bar_idx,
            risk_cash=self.balance * self.cfg.risk_per_trade,
        )
        self.open_positions.append(new_pos)
        self.pending_order = None

    def _update_signal(self, df, bar_idx):
        """Recalcul continu mais 1 position max."""
        if self.prop_sim.is_halted:
            self.pending_order = None
            return
        if self.open_positions:
            self.pending_order = None
            return
        signal = self.strategy.generate_signal(df, bar_idx, None, None)
        if signal is not None:
            self.pending_order = PendingOrder.from_signal(signal, bar_idx)
        else:
            self.pending_order = None


# ─── Main ────────────────────────────────────────────────────────────────────

def run_config(label, engine_cls, strategy_cls, cfg, df_4h, ticker, penalty):
    """Lance un backtest et retourne un résumé."""
    strategy = strategy_cls(cfg)
    engine = engine_cls(cfg, strategy, ticker, penalty)
    result = engine.run(df_4h.copy())
    s = result.summary
    return {
        "label": label,
        "trades": s["n_trades"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
        "exp_r": s["expectancy_r"],
        "balance": s["end_balance"],
        "dd_max": s["prop"]["max_daily_dd_pct"],
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diagnostic v2 performance")
    parser.add_argument("ticker", help="Ticker Yahoo (ex: EURUSD=X)")
    parser.add_argument("--penalty", "-p", type=float, default=0.10)
    args = parser.parse_args()

    cfg = Config.from_env()
    ticker = args.ticker
    penalty = args.penalty

    print(f"\n{'='*72}")
    print(f"  DIAGNOSTIC — {ticker} @ penalty {penalty}")
    print(f"{'='*72}\n")

    # Données
    print("Téléchargement données...")
    df_1h = download_1h(ticker, cfg)
    df_4h = resample_to_timeframe(df_1h, cfg.timeframe)
    print(f"  {len(df_4h)} barres 4H\n")

    configs = [
        ("A. Legacy (close confirmé, 1 pos)",
         LegacyEngine, LegacyDonchianStrategy,
         replace(cfg, max_concurrent_trades=1)),

        ("B. Proactif seul (1 pos, pas heuristique)",
         SingleNoHeuristicEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=1)),

        ("C. Proactif + stacking (3 pos)",
         SingleNoHeuristicEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=3)),

        ("D. Full v2 (3 pos + heuristiques)",
         BacktestEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=3)),

        ("E. Proactif + heuristiques (1 pos)",
         BacktestEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=1)),
    ]

    results = []
    for label, eng_cls, strat_cls, c in configs:
        print(f"  Running {label}...")
        r = run_config(label, eng_cls, strat_cls, c, df_4h, ticker, penalty)
        results.append(r)

    # Affichage
    print(f"\n{'─'*72}")
    print(f"  {'Config':<45} {'Trades':>6} {'WR':>7} {'PF':>6} {'ExpR':>7} {'Balance':>10}")
    print(f"{'─'*72}")
    for r in results:
        wr = f"{r['win_rate']:.1%}"
        pf = f"{r['pf']:.2f}"
        exp = f"{r['exp_r']:.3f}"
        bal = f"{r['balance']:,.0f}"
        print(f"  {r['label']:<45} {r['trades']:>6} {wr:>7} {pf:>6} {exp:>7} {bal:>10}")

    # Analyse
    print(f"\n{'─'*72}")
    print("  ANALYSE DES ÉCARTS")
    print(f"{'─'*72}")

    a, b, c, d, e = results

    delta_ab = b["exp_r"] - a["exp_r"]
    delta_bc = c["exp_r"] - b["exp_r"]
    delta_cd = d["exp_r"] - c["exp_r"]
    delta_be = e["exp_r"] - b["exp_r"]

    print(f"\n  A→B  Signal proactif vs legacy :    {delta_ab:+.3f} R")
    print(f"       (impact du changement de logique de signal)")
    print(f"\n  B→C  Empilage 3 positions :         {delta_bc:+.3f} R")
    print(f"       (impact du multi-position)")
    print(f"\n  C→D  Heuristiques same-bar :         {delta_cd:+.3f} R")
    print(f"       (impact entry+SL et SL+TP)")
    print(f"\n  B→E  Heuristiques sans stacking :    {delta_be:+.3f} R")
    print(f"       (impact heuristiques isolé)")

    # Verdict
    impacts = [
        ("Signal proactif", abs(delta_ab)),
        ("Empilage", abs(delta_bc)),
        ("Heuristiques", abs(delta_cd)),
    ]
    impacts.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  → Principal responsable : {impacts[0][0]} (|Δ| = {impacts[0][1]:.3f} R)")

    if a["exp_r"] > 0 and b["exp_r"] < 0:
        print(f"\n  ⚠️  Le legacy est profitable, le proactif ne l'est pas.")
        print(f"      L'ancien biais d'exécution GONFLAIT les résultats.")
        print(f"      Le signal proactif est plus honnête mais attrape des faux breakouts.")
        print(f"      → Piste : ajouter un filtre momentum (close > prev_close, ou")
        print(f"        close dans le tiers supérieur du range pour un long).")


if __name__ == "__main__":
    main()

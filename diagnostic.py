"""
Diagnostic : isole l'impact de chaque changement v2 sur un ticker.

Usage:
    python diagnostic.py EURUSD=X
    python diagnostic.py GBPUSD=X --penalty 0.10

Compare 5 configurations :
  A. Legacy   : signal confirmé (close > canal), 1 pos, OHLC 4H
  B. Proactif : signal proactif, 1 pos, OHLC 4H
  C. Proactif : signal proactif, 1 pos, intrabar 1H  <- la correction
  D. Proactif : signal proactif, 3 pos, intrabar 1H
  E. Legacy   : signal confirmé, 1 pos, intrabar 1H  <- référence honnête
"""

import sys
import os
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import numpy as np

from envolees.config import Config
from envolees.data import download_1h, resample_to_timeframe
from envolees.strategy.donchian_breakout import DonchianBreakoutStrategy
from envolees.strategy.base import Signal
from envolees.backtest.engine import BacktestEngine
from envolees.backtest.position import PendingOrder


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
            return Signal(direction="LONG", entry_level=d_high + buffer,
                          atr_at_signal=atr, timestamp=ts,
                          expiry_bars=self.cfg.order_valid_bars)
        if close < ema and close < (d_low - buffer):
            return Signal(direction="SHORT", entry_level=d_low - buffer,
                          atr_at_signal=atr, timestamp=ts,
                          expiry_bars=self.cfg.order_valid_bars)
        return None


class LegacyEngine(BacktestEngine):
    """1 position, pas de recalcul continu."""

    def _update_signal(self, df, bar_idx):
        if self.prop_sim.is_halted:
            self.pending_order = None
            return
        if self.open_positions or self.pending_order is not None:
            return
        signal = self.strategy.generate_signal(df, bar_idx, None, None)
        if signal is not None:
            self.pending_order = PendingOrder.from_signal(signal, bar_idx)
        else:
            self.pending_order = None


class SingleEngine(BacktestEngine):
    """Proactif + recalcul continu, 1 position max."""

    def _update_signal(self, df, bar_idx):
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


def run_config(label, engine_cls, strategy_cls, cfg, df_4h, df_1h, ticker, penalty):
    strategy = strategy_cls(cfg)
    engine = engine_cls(cfg, strategy, ticker, penalty)
    result = engine.run(df_4h.copy(), df_1h=df_1h)
    s = result.summary
    return {
        "label": label,
        "trades": s["n_trades"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
        "exp_r": s["expectancy_r"],
        "balance": s["end_balance"],
        "dd_max": s["prop"]["max_daily_dd_pct"],
        "exec": s.get("execution_mode", "?"),
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

    print(f"\n{'='*78}")
    print(f"  DIAGNOSTIC — {ticker} @ penalty {penalty}")
    print(f"{'='*78}\n")

    print("Téléchargement données...")
    df_1h = download_1h(ticker, cfg)
    df_4h = resample_to_timeframe(df_1h, cfg.timeframe)
    print(f"  {len(df_4h)} barres 4H, {len(df_1h)} barres 1H\n")

    configs = [
        ("A. Legacy, 1 pos, OHLC 4H",
         LegacyEngine, LegacyDonchianStrategy,
         replace(cfg, max_concurrent_trades=1), None),

        ("B. Proactif, 1 pos, OHLC 4H",
         SingleEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=1), None),

        ("C. Proactif, 1 pos, intrabar 1H",
         SingleEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=1), df_1h),

        ("D. Proactif, 3 pos, intrabar 1H",
         BacktestEngine, DonchianBreakoutStrategy,
         replace(cfg, max_concurrent_trades=3), df_1h),

        ("E. Legacy, 1 pos, intrabar 1H",
         LegacyEngine, LegacyDonchianStrategy,
         replace(cfg, max_concurrent_trades=1), df_1h),
    ]

    results = []
    for label, eng_cls, strat_cls, c, df1h in configs:
        print(f"  Running {label}...")
        r = run_config(label, eng_cls, strat_cls, c, df_4h, df1h, ticker, penalty)
        results.append(r)

    print(f"\n{'─'*78}")
    print(f"  {'Config':<40} {'Trades':>6} {'WR':>7} {'PF':>6} {'ExpR':>7} {'Balance':>10} {'Exec':>12}")
    print(f"{'─'*78}")
    for r in results:
        wr = f"{r['win_rate']:.1%}"
        pf = f"{r['pf']:.2f}"
        exp = f"{r['exp_r']:.3f}"
        bal = f"{r['balance']:,.0f}"
        print(f"  {r['label']:<40} {r['trades']:>6} {wr:>7} {pf:>6} {exp:>7} {bal:>10} {r['exec']:>12}")

    print(f"\n{'─'*78}")
    print("  ANALYSE DES ÉCARTS")
    print(f"{'─'*78}")

    a, b, c, d, e = results

    delta_ab = b["exp_r"] - a["exp_r"]
    delta_bc = c["exp_r"] - b["exp_r"]
    delta_cd = d["exp_r"] - c["exp_r"]
    delta_ae = e["exp_r"] - a["exp_r"]

    print(f"\n  A→B  Signal proactif (même exec 4H) :       {delta_ab:+.3f} R")
    print(f"       (impact du changement de signal)")
    print(f"\n  B→C  Intrabar 1H (même signal proactif) :   {delta_bc:+.3f} R")
    print(f"       (impact de l'exécution 1H vs heuristiques 4H)")
    print(f"\n  C→D  Empilage 3 positions :                  {delta_cd:+.3f} R")
    print(f"       (impact du multi-position)")
    print(f"\n  A→E  Legacy + intrabar 1H :                  {delta_ae:+.3f} R")
    print(f"       (combien le legacy profitait du biais 4H)")

    print(f"\n{'─'*78}")
    print("  INTERPRÉTATION")
    print(f"{'─'*78}")

    if c["exp_r"] > b["exp_r"]:
        print(f"\n  ✓ L'intrabar 1H AMÉLIORE le proactif 4H ({delta_bc:+.3f} R)")
        print(f"    → Les heuristiques 4H étaient trop pessimistes.")
    elif c["exp_r"] > b["exp_r"] - 0.02:
        print(f"\n  ~ L'intrabar 1H est neutre vs 4H ({delta_bc:+.3f} R)")
        print(f"    → Les heuristiques 4H étaient raisonnables.")
    else:
        print(f"\n  ⚠  L'intrabar 1H DÉGRADE vs 4H ({delta_bc:+.3f} R)")
        print(f"    → Le mode 4H laissait survivre des positions qui perdent.")

    if e["exp_r"] < a["exp_r"]:
        gap = a["exp_r"] - e["exp_r"]
        print(f"\n  Le legacy perdait {gap:.3f} R de son edge apparent (biais OHLC 4H)")
        if e["exp_r"] > 0:
            print(f"  Mais E reste profitable ({e['exp_r']:+.3f} R) → l'edge est réel.")
        else:
            print(f"  Et E n'est plus profitable ({e['exp_r']:+.3f} R) → edge = artefact.")


if __name__ == "__main__":
    main()

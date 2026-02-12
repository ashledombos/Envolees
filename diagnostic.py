"""
Diagnostic v3 : compare signal × exit × exécution.

Usage:
    python diagnostic.py EURUSD=X
    python diagnostic.py GBPUSD=X --penalty 0.10

Configs testées :
  A. Legacy,   TP=1R fixe,        intrabar 1H   (référence rentable)
  B. Proactif, TP=1R fixe,        intrabar 1H   (problème actuel)
  C. Proactif, trailing 2ATR,     intrabar 1H   (trailing serré)
  D. Proactif, trailing 3ATR,     intrabar 1H   (trailing standard)
  E. Proactif, trailing 3ATR+0.5R act, intra 1H (trailing avec activation)
  F. Legacy,   trailing 3ATR,     intrabar 1H   (legacy + trailing)
"""

import sys
import os
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd

from envolees.config import Config
from envolees.data import download_1h, resample_to_timeframe
from envolees.strategy.donchian_breakout import DonchianBreakoutStrategy
from envolees.strategy.base import Signal
from envolees.backtest.engine import BacktestEngine
from envolees.backtest.position import PendingOrder


# ── Stratégie legacy ─────────────────────────────────────────────────

class LegacyDonchianStrategy(DonchianBreakoutStrategy):
    """Signal quand close > canal (post-breakout, l'ancien mode)."""

    def generate_signal(self, df, bar_idx, current_position, pending_signal):
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
                direction="LONG", entry_level=d_high + buffer,
                atr_at_signal=atr, timestamp=ts,
                expiry_bars=self.cfg.order_valid_bars,
            )
        if close < ema and close < (d_low - buffer):
            return Signal(
                direction="SHORT", entry_level=d_low - buffer,
                atr_at_signal=atr, timestamp=ts,
                expiry_bars=self.cfg.order_valid_bars,
            )
        return None


# ── Moteurs ──────────────────────────────────────────────────────────

class SingleShotEngine(BacktestEngine):
    """Legacy : bloque signaux si position OU pending actif."""

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


class SinglePositionEngine(BacktestEngine):
    """Proactif : recalcul continu, 1 position max."""

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


# ── Runner ───────────────────────────────────────────────────────────

def run_config(label, engine_cls, strategy_cls, cfg, df_4h, df_1h, ticker, penalty):
    strategy = strategy_cls(cfg)
    engine = engine_cls(cfg, strategy, ticker, penalty)
    result = engine.run(df_4h.copy(), df_1h=df_1h)
    s = result.summary
    tdf = result.trades_df()
    exits = tdf["exit_reason"].value_counts().to_dict() if len(tdf) else {}

    # Stats supplémentaires pour trailing
    if len(tdf) and (tdf["result_r"] > 0).any():
        winners = tdf.loc[tdf["result_r"] > 0, "result_r"]
        avg_win_r = float(winners.mean())
        max_win_r = float(winners.max())
        avg_dur = float(tdf["duration_bars"].mean())
    else:
        avg_win_r, max_win_r, avg_dur = 0.0, 0.0, 0.0

    return {
        "label": label,
        "trades": s["n_trades"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
        "exp_r": s["expectancy_r"],
        "balance": s["end_balance"],
        "dd_max": s["prop"]["max_daily_dd_pct"],
        "exits": exits,
        "avg_win_r": avg_win_r,
        "max_win_r": max_win_r,
        "avg_dur": avg_dur,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diagnostic v3 — trailing stop")
    parser.add_argument("ticker", help="Ticker Yahoo (ex: EURUSD=X)")
    parser.add_argument("--penalty", "-p", type=float, default=0.10)
    args = parser.parse_args()

    cfg = Config.from_env()
    ticker = args.ticker
    penalty = args.penalty

    print(f"\n{'═'*80}")
    print(f"  DIAGNOSTIC v3 — {ticker} @ penalty {penalty}")
    print(f"{'═'*80}\n")

    print("Téléchargement données...")
    df_1h = download_1h(ticker, cfg)
    df_4h = resample_to_timeframe(df_1h, cfg.timeframe)
    print(f"  {len(df_4h)} barres 4H, {len(df_1h)} barres 1H\n")

    cfg1 = replace(cfg, max_concurrent_trades=1)

    configs = [
        # A. Legacy + TP fixe (référence)
        ("A. Legacy, TP=1R",
         SingleShotEngine, LegacyDonchianStrategy,
         replace(cfg1, exit_mode="fixed", tp_r=1.0)),

        # B. Proactif + TP fixe (le problème)
        ("B. Proactif, TP=1R",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="fixed", tp_r=1.0)),

        # C. Proactif + trailing 2ATR (serré)
        ("C. Proactif, trail 2ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="trailing_atr", trailing_atr=2.0, tp_r=0)),

        # D. Proactif + trailing 3ATR (standard)
        ("D. Proactif, trail 3ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="trailing_atr", trailing_atr=3.0, tp_r=0)),

        # E. Proactif + trailing 3ATR + activation à 0.5R
        ("E. Proactif, trail 3ATR, act=0.5R",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="trailing_atr", trailing_atr=3.0, tp_r=0,
                 trailing_activation_r=0.5)),

        # F. Legacy + trailing 3ATR (best signal + best exit ?)
        ("F. Legacy, trail 3ATR",
         SingleShotEngine, LegacyDonchianStrategy,
         replace(cfg1, exit_mode="trailing_atr", trailing_atr=3.0, tp_r=0)),
    ]

    results = []
    for label, eng_cls, strat_cls, c in configs:
        print(f"  Running {label}...")
        r = run_config(label, eng_cls, strat_cls, c, df_4h, df_1h, ticker, penalty)
        results.append(r)

    # ── Tableau principal ──
    print(f"\n{'─'*80}")
    print(f"  {'Config':<30} {'Trades':>6} {'WR':>7} {'PF':>6} {'ExpR':>7} "
          f"{'AvgWin':>7} {'MaxWin':>7} {'Balance':>10}")
    print(f"{'─'*80}")
    for r in results:
        wr = f"{r['win_rate']:.1%}"
        pf = f"{r['pf']:.2f}"
        exp = f"{r['exp_r']:+.3f}"
        aw = f"{r['avg_win_r']:.1f}R"
        mw = f"{r['max_win_r']:.1f}R"
        bal = f"{r['balance']:,.0f}"
        print(f"  {r['label']:<30} {r['trades']:>6} {wr:>7} {pf:>6} {exp:>7} "
              f"{aw:>7} {mw:>7} {bal:>10}")

    # ── Tableau des exits ──
    print(f"\n{'─'*80}")
    print(f"  {'Config':<30} {'SL':>5} {'TP':>5} {'TRAIL':>5} {'AvgDur':>8}")
    print(f"{'─'*80}")
    for r in results:
        sl = r["exits"].get("SL", 0)
        tp = r["exits"].get("TP", 0)
        tr = r["exits"].get("TRAIL", 0)
        dur = f"{r['avg_dur']:.1f}"
        print(f"  {r['label']:<30} {sl:>5} {tp:>5} {tr:>5} {dur:>8}")

    # ── Analyse ──
    a, b, c, d, e, f = results

    print(f"\n{'─'*80}")
    print("  ANALYSE")
    print(f"{'─'*80}\n")

    # Signal proactif vs legacy (même exit)
    delta_ab = b["exp_r"] - a["exp_r"]
    print(f"  Signal proactif vs legacy (TP=1R) :  {delta_ab:+.3f} R")

    # Trailing vs TP fixe (même signal proactif)
    delta_bd = d["exp_r"] - b["exp_r"]
    print(f"  Trailing 3ATR vs TP=1R (proactif) :  {delta_bd:+.3f} R")

    # Trailing 2ATR vs 3ATR
    delta_cd = d["exp_r"] - c["exp_r"]
    print(f"  Trail 3ATR vs 2ATR :                 {delta_cd:+.3f} R")

    # Activation trailing
    delta_de = e["exp_r"] - d["exp_r"]
    print(f"  Activation 0.5R vs immédiat :        {delta_de:+.3f} R")

    # Legacy + trailing
    delta_af = f["exp_r"] - a["exp_r"]
    print(f"  Legacy trail 3ATR vs Legacy TP=1R :  {delta_af:+.3f} R")

    # ── Verdicts ──
    print(f"\n{'─'*80}")
    print("  VERDICTS")
    print(f"{'─'*80}\n")

    if delta_bd > 0.05:
        print(f"  ★ Le trailing améliore le proactif de {delta_bd:+.3f} R")
        print(f"    Le TP à 1R coupait les gros gains. Le profil trend-following")
        print(f"    est restauré : avg win {d['avg_win_r']:.1f}R vs {b['avg_win_r']:.1f}R.")
    elif delta_bd > 0:
        print(f"  ↑ Légère amélioration avec trailing ({delta_bd:+.3f} R).")
    else:
        print(f"  ~ Le trailing n'améliore pas le proactif ({delta_bd:+.3f} R).")

    if delta_af > 0.05:
        print(f"\n  ★ Le trailing améliore aussi le legacy de {delta_af:+.3f} R !")
        print(f"    → Le trailing est bénéfique indépendamment du signal.")
    elif delta_af > 0:
        print(f"\n  ↑ Légère amélioration legacy + trailing ({delta_af:+.3f} R).")
    else:
        print(f"\n  ~ Le trailing n'améliore pas le legacy ({delta_af:+.3f} R).")

    best = max(results, key=lambda r: r["exp_r"])
    print(f"\n  MEILLEURE CONFIG : {best['label']}")
    print(f"  ExpR={best['exp_r']:+.3f}  WR={best['win_rate']:.1%}  PF={best['pf']:.2f}"
          f"  MaxWin={best['max_win_r']:.1f}R  Balance={best['balance']:,.0f}")
    print()


if __name__ == "__main__":
    main()

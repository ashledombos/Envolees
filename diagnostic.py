"""
Diagnostic v4 : filtres d'entrée × modes de sortie.

Usage:
    python diagnostic.py EURUSD=X
    python diagnostic.py GBPUSD=X --penalty 0.10

Le legacy signal ne peut pas exister en live (il faut le close 4H). On
teste des filtres sur le signal proactif qui reproduisent l'effet du
close-confirms, mais à résolution 1H (vérifiable en live).

Configs :
  A. Legacy,   TP=1R                   (référence non-live)
  B. Proactif, pas de filtre, TP=1R    (le problème actuel)
  C. Proactif, close_1h, TP=1R         (filtre : close 1H > entry)
  D. Proactif, body_ratio 30%, TP=1R   (filtre : close dans top 30%)
  E. Proactif, close_1h, trail 3ATR    (best filter + best exit ?)
  F. Legacy,   trail 3ATR              (max théorique)
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
    """Legacy : pas de signal si position OU pending actif."""

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

    if len(tdf) and (tdf["result_r"] > 0).any():
        winners = tdf.loc[tdf["result_r"] > 0, "result_r"]
        avg_win_r = float(winners.mean())
        max_win_r = float(winners.max())
    else:
        avg_win_r, max_win_r = 0.0, 0.0

    avg_dur = float(tdf["duration_bars"].mean()) if len(tdf) else 0.0

    return {
        "label": label,
        "trades": s["n_trades"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
        "exp_r": s["expectancy_r"],
        "balance": s["end_balance"],
        "exits": exits,
        "avg_win_r": avg_win_r,
        "max_win_r": max_win_r,
        "avg_dur": avg_dur,
    }


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Diagnostic v4 — entry filters")
    parser.add_argument("ticker", help="Ticker Yahoo (ex: EURUSD=X)")
    parser.add_argument("--penalty", "-p", type=float, default=0.10)
    args = parser.parse_args()

    cfg = Config.from_env()
    ticker = args.ticker
    penalty = args.penalty

    print(f"\n{'═'*82}")
    print(f"  DIAGNOSTIC v4 — {ticker} @ penalty {penalty}")
    print(f"{'═'*82}\n")

    print("Téléchargement données...")
    df_1h = download_1h(ticker, cfg)
    df_4h = resample_to_timeframe(df_1h, cfg.timeframe)
    print(f"  {len(df_4h)} barres 4H, {len(df_1h)} barres 1H\n")

    cfg1 = replace(cfg, max_concurrent_trades=1)

    configs = [
        # A. Legacy + TP fixe (référence non-live)
        ("A. Legacy, TP=1R",
         SingleShotEngine, LegacyDonchianStrategy,
         replace(cfg1, exit_mode="fixed", tp_r=1.0, entry_filter="none")),

        # B. Proactif sans filtre, TP=1R (le problème)
        ("B. Proactif, no filter, TP=1R",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="fixed", tp_r=1.0, entry_filter="none")),

        # C. Proactif + close_confirms_1h, TP=1R
        ("C. Proactif, close_1h, TP=1R",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="fixed", tp_r=1.0, entry_filter="close_confirms_1h")),

        # D. Proactif + body_ratio 30%, TP=1R
        ("D. Proactif, body_30%, TP=1R",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="fixed", tp_r=1.0, entry_filter="body_ratio",
                 entry_body_pct=0.3)),

        # E. Proactif + close_1h + trailing 3ATR (le combo)
        ("E. Proactif, close_1h, trail 3ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         replace(cfg1, exit_mode="trailing_atr", trailing_atr=3.0, tp_r=0,
                 entry_filter="close_confirms_1h")),

        # F. Legacy + trailing 3ATR (max théorique)
        ("F. Legacy, trail 3ATR",
         SingleShotEngine, LegacyDonchianStrategy,
         replace(cfg1, exit_mode="trailing_atr", trailing_atr=3.0, tp_r=0,
                 entry_filter="none")),
    ]

    results = []
    for label, eng_cls, strat_cls, c in configs:
        print(f"  Running {label}...")
        r = run_config(label, eng_cls, strat_cls, c, df_4h, df_1h, ticker, penalty)
        results.append(r)

    # ── Tableau principal ──
    print(f"\n{'─'*82}")
    print(f"  {'Config':<34} {'Trades':>6} {'WR':>7} {'PF':>6} {'ExpR':>7} "
          f"{'AvgWin':>7} {'MaxWin':>7} {'Balance':>10}")
    print(f"{'─'*82}")
    for r in results:
        wr = f"{r['win_rate']:.1%}"
        pf = f"{r['pf']:.2f}"
        exp = f"{r['exp_r']:+.3f}"
        aw = f"{r['avg_win_r']:.1f}R"
        mw = f"{r['max_win_r']:.1f}R"
        bal = f"{r['balance']:,.0f}"
        print(f"  {r['label']:<34} {r['trades']:>6} {wr:>7} {pf:>6} {exp:>7} "
              f"{aw:>7} {mw:>7} {bal:>10}")

    # ── Tableau des exits ──
    print(f"\n{'─'*82}")
    print(f"  {'Config':<34} {'SL':>5} {'TP':>5} {'TRAIL':>5} {'AvgDur':>8}")
    print(f"{'─'*82}")
    for r in results:
        sl = r["exits"].get("SL", 0)
        tp = r["exits"].get("TP", 0)
        tr = r["exits"].get("TRAIL", 0)
        dur = f"{r['avg_dur']:.1f}"
        print(f"  {r['label']:<34} {sl:>5} {tp:>5} {tr:>5} {dur:>8}")

    # ── Analyse ──
    a, b, c, d, e, f = results

    print(f"\n{'─'*82}")
    print("  ANALYSE")
    print(f"{'─'*82}\n")

    print(f"  Le problème : signal proactif sans filtre")
    print(f"  A→B (legacy→proactif, TP=1R) :         {b['exp_r']-a['exp_r']:+.3f} R\n")

    print(f"  Impact du filtre close_1h (même TP=1R) :")
    print(f"  B→C (no filter→close_1h) :             {c['exp_r']-b['exp_r']:+.3f} R")
    trades_filtered = b["trades"] - c["trades"]
    print(f"       ({trades_filtered} trades filtrés, {c['trades']} restants)\n")

    print(f"  Impact du filtre body_ratio 30% :")
    print(f"  B→D (no filter→body_30%) :             {d['exp_r']-b['exp_r']:+.3f} R")
    trades_filtered_d = b["trades"] - d["trades"]
    print(f"       ({trades_filtered_d} trades filtrés, {d['trades']} restants)\n")

    print(f"  Combo close_1h + trailing 3ATR :")
    print(f"  B→E (proactif brut → filtered+trailing): {e['exp_r']-b['exp_r']:+.3f} R")
    print(f"  C→E (close_1h TP=1R → close_1h+trail) : {e['exp_r']-c['exp_r']:+.3f} R\n")

    print(f"  Référence maximale :")
    print(f"  A (Legacy TP=1R) :                     {a['exp_r']:+.3f} R")
    print(f"  F (Legacy trail 3ATR) :                {f['exp_r']:+.3f} R\n")

    # ── Verdicts ──
    print(f"{'─'*82}")
    print("  VERDICTS")
    print(f"{'─'*82}\n")

    # Qualité du filtre close_1h
    gap_to_legacy = abs(c["exp_r"] - a["exp_r"])
    gap_original = abs(b["exp_r"] - a["exp_r"])
    recovery_pct = (1 - gap_to_legacy / gap_original) * 100 if gap_original > 0 else 0

    if c["exp_r"] > b["exp_r"] + 0.05:
        print(f"  ★ Le filtre close_1h récupère {recovery_pct:.0f}% du gap legacy→proactif.")
        print(f"    WR passe de {b['win_rate']:.1%} à {c['win_rate']:.1%} "
              f"(legacy: {a['win_rate']:.1%}).")
    elif c["exp_r"] > b["exp_r"]:
        print(f"  ↑ Le filtre close_1h améliore modestement ({c['exp_r']-b['exp_r']:+.3f} R).")
    else:
        print(f"  ~ Le filtre close_1h n'aide pas sur cet instrument.")

    # Combo filter + trailing
    if e["exp_r"] > c["exp_r"] + 0.05:
        print(f"\n  ★ Le trailing ajoute {e['exp_r']-c['exp_r']:+.3f} R au-dessus du filtre seul.")
    elif e["exp_r"] > c["exp_r"]:
        print(f"\n  ↑ Le trailing ajoute modestement ({e['exp_r']-c['exp_r']:+.3f} R).")
    else:
        print(f"\n  ~ Le trailing n'ajoute rien au filtre sur cet instrument.")

    # Best live-able config
    live_configs = [b, c, d, e]  # Exclure A et F (non-live)
    best_live = max(live_configs, key=lambda r: r["exp_r"])
    print(f"\n  MEILLEURE CONFIG LIVE : {best_live['label']}")
    print(f"  ExpR={best_live['exp_r']:+.3f}  WR={best_live['win_rate']:.1%}  "
          f"PF={best_live['pf']:.2f}  Balance={best_live['balance']:,.0f}")

    # vs legacy
    gap = best_live["exp_r"] - a["exp_r"]
    print(f"  Gap vs legacy : {gap:+.3f} R")
    if gap > -0.05:
        print(f"  → Comble le gap ! Viable en live.")
    else:
        print(f"  → Reste un écart de {-gap:.3f} R vs legacy.")
    print()


if __name__ == "__main__":
    main()

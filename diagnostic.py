"""
Diagnostic v5 : grille complète filtres d'entrée × modes de sortie.

Usage:
    python diagnostic.py EURUSD=X
    python diagnostic.py GBPUSD=X --penalty 0.10

Grille testée (12 configs) :

  Signal       Filtre d'entrée              Sortie       Code
  ──────────── ──────────────────────────── ──────────── ────
  Legacy       aucun                        TP=1R         A
  Proactif     aucun                        TP=1R         B
  Proactif     close_1h (marge 0)           TP=1R         C1
  Proactif     close_1h (marge 0.05 ATR)    TP=1R         C2
  Proactif     close_1h (marge 0.10 ATR)    TP=1R         C3
  Proactif     close_1h (marge 0.20 ATR)    TP=1R         C4
  Proactif     body_ratio 30%               TP=1R         D1
  Proactif     body_ratio 20%               TP=1R         D2
  Proactif     close_1h (marge 0)           trail 3ATR    E1
  Proactif     close_1h (marge 0.10 ATR)    trail 3ATR    E2
  Proactif     body_ratio 30%               trail 3ATR    E3
  Legacy       aucun                        trail 3ATR    F

Biais corrigés dans cette version :
- sizing_mode="fixed" (position sizing sur start_balance, pas sur balance courant)
- Positions ouvertes fermées au close de la dernière barre (CLOSE_END)
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
    """Signal quand close > canal (post-breakout)."""

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
    parser = argparse.ArgumentParser(description="Diagnostic v5 — grille complète")
    parser.add_argument("ticker", help="Ticker Yahoo (ex: EURUSD=X)")
    parser.add_argument("--penalty", "-p", type=float, default=0.10)
    args = parser.parse_args()

    cfg = Config.from_env()
    ticker = args.ticker
    penalty = args.penalty

    print(f"\n{'═'*90}")
    print(f"  DIAGNOSTIC v5 — {ticker} @ penalty {penalty}")
    print(f"  sizing_mode=fixed (prop firm), positions fermées en fin de backtest")
    print(f"{'═'*90}\n")

    print("Téléchargement données...")
    df_1h = download_1h(ticker, cfg)
    df_4h = resample_to_timeframe(df_1h, cfg.timeframe)
    print(f"  {len(df_4h)} barres 4H, {len(df_1h)} barres 1H\n")

    # Base config : 1 position, sizing fixe
    cfg1 = replace(cfg, max_concurrent_trades=1, sizing_mode="fixed")

    # Helper pour créer les configs
    def fixed_tp(entry_filter="none", entry_body_pct=0.0):
        return replace(cfg1, exit_mode="fixed", tp_r=1.0,
                       entry_filter=entry_filter, entry_body_pct=entry_body_pct)

    def trail_3atr(entry_filter="none", entry_body_pct=0.0):
        return replace(cfg1, exit_mode="trailing_atr", trailing_atr=3.0, tp_r=0,
                       entry_filter=entry_filter, entry_body_pct=entry_body_pct)

    configs = [
        # ── Références ──
        ("A.  Legacy, TP=1R",
         SingleShotEngine, LegacyDonchianStrategy, fixed_tp()),

        ("B.  Proactif, no filter, TP=1R",
         SinglePositionEngine, DonchianBreakoutStrategy, fixed_tp()),

        # ── Grille close_1h avec marge croissante ──
        ("C1. close_1h, marge=0",
         SinglePositionEngine, DonchianBreakoutStrategy,
         fixed_tp("close_confirms_1h", 0.0)),

        ("C2. close_1h, marge=0.05ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         fixed_tp("close_confirms_1h", 0.05)),

        ("C3. close_1h, marge=0.10ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         fixed_tp("close_confirms_1h", 0.10)),

        ("C4. close_1h, marge=0.20ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         fixed_tp("close_confirms_1h", 0.20)),

        # ── Grille body_ratio ──
        ("D1. body_ratio 30%",
         SinglePositionEngine, DonchianBreakoutStrategy,
         fixed_tp("body_ratio", 0.30)),

        ("D2. body_ratio 20%",
         SinglePositionEngine, DonchianBreakoutStrategy,
         fixed_tp("body_ratio", 0.20)),

        # ── Combos filtre + trailing ──
        ("E1. close_1h+trail 3ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         trail_3atr("close_confirms_1h", 0.0)),

        ("E2. close_1h m=0.10+trail",
         SinglePositionEngine, DonchianBreakoutStrategy,
         trail_3atr("close_confirms_1h", 0.10)),

        ("E3. body_30%+trail 3ATR",
         SinglePositionEngine, DonchianBreakoutStrategy,
         trail_3atr("body_ratio", 0.30)),

        # ── Max théorique ──
        ("F.  Legacy, trail 3ATR",
         SingleShotEngine, LegacyDonchianStrategy, trail_3atr()),
    ]

    results = []
    for label, eng_cls, strat_cls, c in configs:
        print(f"  Running {label}...")
        r = run_config(label, eng_cls, strat_cls, c, df_4h, df_1h, ticker, penalty)
        results.append(r)

    # ── Tableau principal ──
    print(f"\n{'─'*90}")
    print(f"  {'Config':<30} {'Trades':>6} {'WR':>7} {'PF':>6} {'ExpR':>7} "
          f"{'AvgWin':>7} {'MaxWin':>7} {'Balance':>10}")
    print(f"{'─'*90}")
    for r in results:
        wr = f"{r['win_rate']:.1%}"
        pf = f"{r['pf']:.2f}"
        exp = f"{r['exp_r']:+.3f}"
        aw = f"{r['avg_win_r']:.1f}R"
        mw = f"{r['max_win_r']:.1f}R"
        bal = f"{r['balance']:,.0f}"
        print(f"  {r['label']:<30} {r['trades']:>6} {wr:>7} {pf:>6} {exp:>7} "
              f"{aw:>7} {mw:>7} {bal:>10}")

    # ── Tableau exits ──
    print(f"\n{'─'*90}")
    print(f"  {'Config':<30} {'SL':>5} {'TP':>5} {'TRAIL':>5} {'END':>5} {'AvgDur':>8}")
    print(f"{'─'*90}")
    for r in results:
        sl = r["exits"].get("SL", 0)
        tp = r["exits"].get("TP", 0)
        tr = r["exits"].get("TRAIL", 0)
        end = r["exits"].get("CLOSE_END", 0)
        dur = f"{r['avg_dur']:.1f}"
        print(f"  {r['label']:<30} {sl:>5} {tp:>5} {tr:>5} {end:>5} {dur:>8}")

    # ── Analyse ──
    a = results[0]   # Legacy TP=1R
    b = results[1]   # Proactif no filter
    f = results[-1]  # Legacy trail

    print(f"\n{'─'*90}")
    print("  ANALYSE COMPARATIVE")
    print(f"{'─'*90}\n")

    print(f"  Références :")
    print(f"    A. Legacy TP=1R :     ExpR={a['exp_r']:+.3f}  (non-live)")
    print(f"    B. Proactif brut :    ExpR={b['exp_r']:+.3f}  (le problème)")
    print(f"    F. Legacy trail :     ExpR={f['exp_r']:+.3f}  (max théorique)")
    print(f"    Gap A→B :             {b['exp_r']-a['exp_r']:+.3f} R\n")

    # Classement des configs live (exclure A et F)
    live_results = results[1:-1]  # B through E3
    live_sorted = sorted(live_results, key=lambda r: r["exp_r"], reverse=True)

    print(f"  CLASSEMENT DES CONFIGS LIVE (par ExpR) :")
    print(f"  {'Rank':>4} {'Config':<30} {'ExpR':>7} {'WR':>7} {'PF':>6} {'Trades':>6}  vs Legacy")
    for i, r in enumerate(live_sorted):
        gap = r["exp_r"] - a["exp_r"]
        marker = "★" if gap > -0.05 else "↑" if gap > -0.15 else " "
        print(f"  {i+1:>4} {r['label']:<30} {r['exp_r']:+.3f} {r['win_rate']:.1%} "
              f"{r['pf']:.2f}  {r['trades']:>5}  {gap:+.3f} {marker}")

    # ── Meilleures configs ──
    best_tp1r = max([r for r in live_results if r["exits"].get("TRAIL", 0) == 0],
                    key=lambda r: r["exp_r"])
    best_trail = max([r for r in live_results if r["exits"].get("TRAIL", 0) > 0],
                     key=lambda r: r["exp_r"], default=None)
    best_overall = live_sorted[0]

    print(f"\n{'─'*90}")
    print("  RECOMMANDATIONS")
    print(f"{'─'*90}\n")

    print(f"  Meilleur filtre TP=1R :  {best_tp1r['label']}")
    print(f"    ExpR={best_tp1r['exp_r']:+.3f}  WR={best_tp1r['win_rate']:.1%}  "
          f"PF={best_tp1r['pf']:.2f}  {best_tp1r['trades']} trades")

    if best_trail:
        print(f"\n  Meilleur filtre+trail :  {best_trail['label']}")
        print(f"    ExpR={best_trail['exp_r']:+.3f}  WR={best_trail['win_rate']:.1%}  "
              f"PF={best_trail['pf']:.2f}  {best_trail['trades']} trades")

    print(f"\n  Meilleur global :        {best_overall['label']}")
    gap = best_overall["exp_r"] - a["exp_r"]
    print(f"    ExpR={best_overall['exp_r']:+.3f}  Gap vs legacy={gap:+.3f} R")

    if gap > -0.05:
        print(f"    ✓ Gap quasi comblé ! Config viable en live.")
    elif gap > -0.15:
        print(f"    ~ Gap réduit mais significatif. Acceptable pour un challenge.")
    else:
        print(f"    ⚠ Gap important. Le signal proactif reste sous-optimal sur cet instrument.")
    print()


if __name__ == "__main__":
    main()

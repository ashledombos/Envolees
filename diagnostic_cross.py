"""
Diagnostic v6 : grille croisée instruments × stratégies.

Usage:
    python diagnostic_cross.py
    python diagnostic_cross.py --penalty 0.10
    python diagnostic_cross.py --instruments EURUSD=X GBPUSD=X BTC-USD

Produit un tableau croisé instruments × configs pour identifier :
1. La meilleure config UNIQUE (si elle existe)
2. Ou la règle adaptative la plus simple (TP fixe vs trailing selon l'instrument)

Configs testées (réduites aux plus pertinentes) :
  B.  Proactif, no filter, TP=1R           (baseline)
  C1. close_1h marge=0, TP=1R              (filtre minimal)
  C3. close_1h marge=0.10ATR, TP=1R        (filtre modéré)
  C4. close_1h marge=0.20ATR, TP=1R        (filtre fort)
  E1. close_1h marge=0 + trail 3ATR        (filtre minimal + trail)
  E2. close_1h marge=0.10ATR + trail 3ATR  (filtre modéré + trail)
  A.  Legacy, TP=1R                         (référence non-live)
  F.  Legacy, trail 3ATR                    (max théorique)
"""

import sys
import os
import argparse
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


# ── Configs ──────────────────────────────────────────────────────────

def build_configs(base_cfg):
    """Retourne la liste des configs à tester."""
    cfg = replace(base_cfg, max_concurrent_trades=1, sizing_mode="fixed")

    def fixed_tp(filt="none", margin=0.0):
        return replace(cfg, exit_mode="fixed", tp_r=1.0,
                       entry_filter=filt, entry_body_pct=margin)

    def trail(filt="none", margin=0.0, atr_mult=3.0):
        return replace(cfg, exit_mode="trailing_atr", trailing_atr=atr_mult, tp_r=0,
                       entry_filter=filt, entry_body_pct=margin)

    return [
        # label, engine_cls, strategy_cls, config, is_live
        ("B  no_filter TP1R",    SinglePositionEngine, DonchianBreakoutStrategy, fixed_tp(), True),
        ("C1 close0 TP1R",       SinglePositionEngine, DonchianBreakoutStrategy, fixed_tp("close_confirms_1h", 0.0), True),
        ("C3 close.10 TP1R",     SinglePositionEngine, DonchianBreakoutStrategy, fixed_tp("close_confirms_1h", 0.10), True),
        ("C4 close.20 TP1R",     SinglePositionEngine, DonchianBreakoutStrategy, fixed_tp("close_confirms_1h", 0.20), True),
        ("E1 close0 trail3",     SinglePositionEngine, DonchianBreakoutStrategy, trail("close_confirms_1h", 0.0), True),
        ("E2 close.10 trail3",   SinglePositionEngine, DonchianBreakoutStrategy, trail("close_confirms_1h", 0.10), True),
        ("A  legacy TP1R",       SingleShotEngine, LegacyDonchianStrategy, fixed_tp(), False),
        ("F  legacy trail3",     SingleShotEngine, LegacyDonchianStrategy, trail(), False),
    ]


# ── Runner ───────────────────────────────────────────────────────────

def run_one(label, engine_cls, strategy_cls, cfg, df_4h, df_1h, ticker, penalty):
    strategy = strategy_cls(cfg)
    engine = engine_cls(cfg, strategy, ticker, penalty)
    result = engine.run(df_4h.copy(), df_1h=df_1h)
    s = result.summary
    tdf = result.trades_df()

    max_win = 0.0
    if len(tdf) and (tdf["result_r"] > 0).any():
        max_win = float(tdf.loc[tdf["result_r"] > 0, "result_r"].max())

    return {
        "trades": s["n_trades"],
        "win_rate": s["win_rate"],
        "pf": s["profit_factor"],
        "exp_r": s["expectancy_r"],
        "max_win": max_win,
        "balance": s["end_balance"],
    }


def main():
    parser = argparse.ArgumentParser(description="Diagnostic croisé instruments × configs")
    parser.add_argument("--instruments", "-i", nargs="+",
                        default=["EURUSD=X", "GBPUSD=X", "USDJPY=X", "AUDUSD=X",
                                 "GC=F", "BTC-USD", "ETH-USD"])
    parser.add_argument("--penalty", "-p", type=float, default=0.10)
    args = parser.parse_args()

    cfg = Config.from_env()
    penalty = args.penalty
    instruments = args.instruments

    print(f"\n{'═'*100}")
    print(f"  DIAGNOSTIC CROISÉ v6 — {len(instruments)} instruments × 8 configs")
    print(f"  penalty={penalty}, sizing=fixed, entry_price=close_1h quand filtre actif")
    print(f"{'═'*100}\n")

    configs = build_configs(cfg)
    config_labels = [c[0] for c in configs]

    # Résultats : {instrument: {config_label: {metrics}}}
    all_results = {}

    for ticker in instruments:
        print(f"\n{'─'*60}")
        print(f"  {ticker}")
        print(f"{'─'*60}")

        try:
            df_1h = download_1h(ticker, cfg)
            df_4h = resample_to_timeframe(df_1h, cfg.timeframe)
            print(f"  {len(df_4h)} barres 4H, {len(df_1h)} barres 1H")
        except Exception as e:
            print(f"  ⚠ Erreur données : {e}")
            continue

        inst_results = {}
        for label, eng_cls, strat_cls, c, is_live in configs:
            try:
                r = run_one(label, eng_cls, strat_cls, c, df_4h, df_1h, ticker, penalty)
                inst_results[label] = r
                marker = " " if is_live else "†"
                print(f"    {label:<22} {r['trades']:>4}t  WR={r['win_rate']:.0%}  "
                      f"PF={r['pf']:.2f}  ExpR={r['exp_r']:+.3f}{marker}")
            except Exception as e:
                print(f"    {label:<22} ERREUR: {e}")
                inst_results[label] = None

        all_results[ticker] = inst_results

    # ══════════════════════════════════════════════════════════════════
    # TABLEAUX CROISÉS
    # ══════════════════════════════════════════════════════════════════

    valid_instruments = [t for t in instruments if t in all_results]

    # ── 1. Tableau ExpR ──
    print(f"\n\n{'═'*100}")
    print(f"  TABLEAU CROISÉ — ExpR (R par trade)")
    print(f"{'═'*100}")

    # Header
    col_w = 10
    header = f"  {'Config':<22}"
    for t in valid_instruments:
        short = t.replace("=X", "").replace("-USD", "")[:8]
        header += f" {short:>{col_w}}"
    header += f" {'MOYENNE':>{col_w}} {'MIN':>{col_w}}"
    print(header)
    print(f"  {'─'*22}" + f" {'─'*col_w}" * (len(valid_instruments) + 2))

    config_averages = {}
    for label, _, _, _, is_live in configs:
        row = f"  {label:<22}"
        values = []
        for t in valid_instruments:
            r = all_results[t].get(label)
            if r is not None:
                row += f" {r['exp_r']:>{col_w}.3f}"
                values.append(r["exp_r"])
            else:
                row += f" {'N/A':>{col_w}}"

        if values:
            avg = sum(values) / len(values)
            mn = min(values)
            row += f" {avg:>{col_w}.3f} {mn:>{col_w}.3f}"
            config_averages[label] = {"avg": avg, "min": mn, "values": values, "is_live": is_live}
        else:
            row += f" {'N/A':>{col_w}} {'N/A':>{col_w}}"

        marker = " " if is_live else " †"
        print(row + marker)

    # ── 2. Tableau WR ──
    print(f"\n{'═'*100}")
    print(f"  TABLEAU CROISÉ — Win Rate")
    print(f"{'═'*100}")

    header = f"  {'Config':<22}"
    for t in valid_instruments:
        short = t.replace("=X", "").replace("-USD", "")[:8]
        header += f" {short:>{col_w}}"
    print(header)
    print(f"  {'─'*22}" + f" {'─'*col_w}" * len(valid_instruments))

    for label, _, _, _, is_live in configs:
        row = f"  {label:<22}"
        for t in valid_instruments:
            r = all_results[t].get(label)
            if r is not None:
                row += f" {r['win_rate']:>{col_w}.0%}"
            else:
                row += f" {'N/A':>{col_w}}"
        marker = " " if is_live else " †"
        print(row + marker)

    # ── 3. Tableau Trades ──
    print(f"\n{'═'*100}")
    print(f"  TABLEAU CROISÉ — Nombre de trades")
    print(f"{'═'*100}")

    header = f"  {'Config':<22}"
    for t in valid_instruments:
        short = t.replace("=X", "").replace("-USD", "")[:8]
        header += f" {short:>{col_w}}"
    header += f" {'TOTAL':>{col_w}}"
    print(header)
    print(f"  {'─'*22}" + f" {'─'*col_w}" * (len(valid_instruments) + 1))

    for label, _, _, _, is_live in configs:
        row = f"  {label:<22}"
        total = 0
        for t in valid_instruments:
            r = all_results[t].get(label)
            if r is not None:
                row += f" {r['trades']:>{col_w}}"
                total += r["trades"]
            else:
                row += f" {'N/A':>{col_w}}"
        row += f" {total:>{col_w}}"
        marker = " " if is_live else " †"
        print(row + marker)

    # ══════════════════════════════════════════════════════════════════
    # ANALYSE
    # ══════════════════════════════════════════════════════════════════

    print(f"\n\n{'═'*100}")
    print(f"  ANALYSE & RECOMMANDATIONS")
    print(f"{'═'*100}\n")

    # Meilleure config live par instrument
    print(f"  MEILLEURE CONFIG LIVE PAR INSTRUMENT :")
    best_per_inst = {}
    for t in valid_instruments:
        short = t.replace("=X", "").replace("-USD", "")[:8]
        live_configs = [(label, all_results[t][label])
                        for label, _, _, _, is_live in configs
                        if is_live and all_results[t].get(label) is not None]
        if live_configs:
            best_label, best_r = max(live_configs, key=lambda x: x[1]["exp_r"])
            best_per_inst[t] = best_label
            # Also get legacy reference
            legacy_r = all_results[t].get("A  legacy TP1R")
            gap = best_r["exp_r"] - legacy_r["exp_r"] if legacy_r else 0
            print(f"    {short:<10} → {best_label:<22}  ExpR={best_r['exp_r']:+.3f}  "
                  f"WR={best_r['win_rate']:.0%}  PF={best_r['pf']:.2f}  "
                  f"gap_legacy={gap:+.3f}")

    # Meilleure config unique (par moyenne)
    live_averages = {k: v for k, v in config_averages.items() if v["is_live"]}
    if live_averages:
        print(f"\n  MEILLEURE CONFIG UNIQUE (par ExpR moyen sur tous instruments) :")
        sorted_avg = sorted(live_averages.items(), key=lambda x: x[1]["avg"], reverse=True)
        for i, (label, stats) in enumerate(sorted_avg[:5]):
            marker = "★" if i == 0 else " "
            print(f"    {marker} {label:<22}  avg={stats['avg']:+.3f}  "
                  f"min={stats['min']:+.3f}  "
                  f"[{', '.join(f'{v:+.3f}' for v in stats['values'])}]")

    # Config adaptative simple : TP fixe vs trailing
    print(f"\n  ANALYSE ADAPTATIVE (TP fixe vs trailing par instrument) :")
    for t in valid_instruments:
        short = t.replace("=X", "").replace("-USD", "")[:8]
        # Best TP fixe
        tp_configs = [(l, all_results[t][l]) for l, _, _, _, live in configs
                      if live and "trail" not in l and all_results[t].get(l)]
        trail_configs = [(l, all_results[t][l]) for l, _, _, _, live in configs
                         if live and "trail" in l and all_results[t].get(l)]

        best_tp = max(tp_configs, key=lambda x: x[1]["exp_r"]) if tp_configs else None
        best_tr = max(trail_configs, key=lambda x: x[1]["exp_r"]) if trail_configs else None

        if best_tp and best_tr:
            tp_exp = best_tp[1]["exp_r"]
            tr_exp = best_tr[1]["exp_r"]
            winner = "TRAIL" if tr_exp > tp_exp + 0.05 else "TP=1R" if tp_exp > tr_exp + 0.05 else "≈ÉGAL"
            print(f"    {short:<10}  TP1R={tp_exp:+.3f} ({best_tp[0].strip()})  "
                  f"TRAIL={tr_exp:+.3f} ({best_tr[0].strip()})  → {winner}")

    # Synthèse
    print(f"\n{'─'*100}")
    print(f"  SYNTHÈSE")
    print(f"{'─'*100}\n")

    # Check if one config dominates
    if live_averages:
        best_label, best_stats = sorted_avg[0]
        second_label, second_stats = sorted_avg[1]
        gap = best_stats["avg"] - second_stats["avg"]

        if best_stats["min"] > 0:
            print(f"  ✓ {best_label} est profitable sur TOUS les instruments "
                  f"(min={best_stats['min']:+.3f})")
        elif best_stats["min"] > -0.05:
            print(f"  ~ {best_label} est rentable en moyenne mais marginal sur certains instruments")
        else:
            print(f"  ⚠ Aucune config n'est profitable sur tous les instruments")

        if gap > 0.05:
            print(f"  ✓ {best_label} domine clairement (+{gap:.3f} vs #2)")
        else:
            print(f"  ~ Pas de dominance claire entre {best_label} et {second_label}")

    # Count which exit mode wins per instrument
    tp_wins = sum(1 for t in valid_instruments
                  if best_per_inst.get(t, "").find("trail") == -1)
    trail_wins = sum(1 for t in valid_instruments
                     if best_per_inst.get(t, "").find("trail") != -1)

    print(f"\n  Sortie TP=1R préférée sur {tp_wins}/{len(valid_instruments)} instruments")
    print(f"  Sortie trailing préférée sur {trail_wins}/{len(valid_instruments)} instruments")

    if trail_wins > tp_wins:
        print(f"\n  → Le trailing domine. Config recommandée : close_confirms_1h + trailing 3ATR")
    elif tp_wins > trail_wins:
        print(f"\n  → Le TP=1R domine. Config recommandée : close_confirms_1h marge=0.20ATR + TP=1R")
    else:
        print(f"\n  → Mix. Config adaptative recommandée :")
        print(f"    - Instruments trending (GBP, JPY, crypto) : trailing 3ATR")
        print(f"    - Instruments mean-reverting (EUR) : TP=1R avec marge forte")

    print(f"\n  † = configs non-live (legacy), pour référence uniquement\n")


if __name__ == "__main__":
    main()

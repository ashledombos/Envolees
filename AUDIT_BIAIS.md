# Audit des biais du backtester Envolées
# Date: 2026-02-12

## ✅ BIAIS VÉRIFIÉS ET ABSENTS

### 1. Look-ahead sur les indicateurs
- **Donchian** : `shift=1` ✓ → canal à bar N = max(bars N-20..N-1), n'inclut pas bar N
- **EMA** : `ewm(span=200, adjust=False)` ✓ → récursif backward-looking
- **ATR** : `rolling(14).mean()` sur True Range ✓ → backward-looking
- **VOL_ok** : `rolling(1000).quantile(0.90)` ✓ → backward-looking
  → Aucun look-ahead dans les indicateurs.

### 2. Ordre signal → exécution
- Signal à bar N utilise df.iloc[N] (OHLC complet de la barre 4H)
- En live : signal émis à la CLÔTURE de la barre 4H → même information
- Pending order actif à partir de bar N+1
- _update_signal() appelé APRÈS _execute_intrabar() → correct
  → Pas de look-ahead sur le flux signal/exécution.

### 3. Donchian channel shift
- Le canal n'inclut PAS la barre courante
- En live (TradingView) : la fonction ta.highest(high, 20)[1] fait pareil
  → Cohérent avec le live.

### 4. SL/TP calculés avec ATR du signal
- atr_at_signal figé au moment du signal (bar N-1)
- Utilisé pour compute_entry_sl_tp quand le pending trigger (bar N+1 ou après)
- En live : on utilise l'ATR au moment de l'alerte, pas au moment du fill
  → Cohérent.


## ⚠️ BIAIS IDENTIFIÉ #1 : COMPOUNDING DU POSITION SIZING

**Ligne 213 :** `risk_cash = self.balance * self.cfg.risk_per_trade`

Le risque par trade est calculé sur le **balance courant**, pas sur le balance initial.

**Conséquence :**
- Après des gains, les positions grossissent → les prochains gains sont amplifiés
- Après des pertes, les positions rétrécissent → les prochaines pertes sont amorties
- Cet effet est **symétriquement flatteur** : il fait paraître les stratégies
  gagnantes PLUS gagnantes et les stratégies perdantes MOINS perdantes

**En prop firm** : le compte est à taille fixe (100k). On ne réinvestit pas
les profits intraday dans des positions plus grosses. Le sizing devrait être
sur `start_balance`, pas `self.balance`.

**Impact estimé :** Sur 2 ans avec ExpR=+0.3R et risk=0.25%, le compounding
ajoute ~5-10% de profit fictif. L'impact sur ExpR est faible car c'est mesuré
en R, mais le P&L en cash et la balance finale sont gonflés.

**Fix :** Ajouter un flag `sizing_mode = "fixed" | "compound"`.
- "fixed" : risk_cash = start_balance × risk_per_trade (mode prop firm)
- "compound" : risk_cash = balance × risk_per_trade (mode personnel)


## ⚠️ BIAIS IDENTIFIÉ #2 : GAP RISK SUR SL

**Position.check_exit()** suppose que le SL est toujours exécuté au prix exact :
`return "SL", self.sl`

En réalité, les gaps overnight et weekend peuvent faire ouvrir le prix
BIEN AU-DELÀ du SL. Exemples :
- Vendredi close 1.0850, SL à 1.0830 → Lundi open 1.0780 → perte = -1.7R
- Annonce macro surprenante → gap de 50 pips en 1 seconde

**Impact :** Sous-estime les pertes réelles sur les SL, surtout pour :
- Les trades tenus sur le weekend
- Les paires exotiques à faible liquidité nocturne
- Autour des annonces (NFP, ECB, etc.)

**Fix possible :**
- Pour les SL : exit_price = min(row["Open"], self.sl) pour LONG (slippage gap)
- Filtre optionnel : ne pas ouvrir de trade le vendredi après 18h UTC
- Modéliser le slippage SL comme SL - gap_risk × ATR


## ⚠️ BIAIS IDENTIFIÉ #3 : POSITIONS NON FERMÉES EN FIN DE BACKTEST

Le backtest se termine sans fermer les positions ouvertes. Celles-ci sont
simplement ignorées. Ceci peut flatter les résultats si des positions perdantes
sont ouvertes à la fin, ou les sous-estimer si des positions gagnantes courent.

**Impact :** Faible si beaucoup de trades (effet marginal), mais peut biaiser
les résultats sur de courtes fenêtres ou avec le trailing (positions longues).

**Fix :** Fermer toutes les positions au close de la dernière barre avec
exit_reason="CLOSE_END".


## 🔍 BIAIS POTENTIEL #4 : QUALITÉ DONNÉES YAHOO 1H

Yahoo Finance 1H est gratuit mais notoirement imprécis :
- Mèches fantômes (spikes qui n'ont pas existé)
- Barres manquantes (surtout la nuit)
- Arrondis de prix incohérents entre 1H et 4H resamplé

**Impact :** Peut créer des déclenchements/SL/TP parasites. Impossible à
quantifier sans cross-validation avec une source payante.

**Mitigation :** Comparer un échantillon (1 mois) avec données Dukascopy ou
TradingView export pour vérifier la cohérence.


## 🔍 BIAIS POTENTIEL #5 : FENÊTRE DE DONNÉES UNIQUE

730 jours = 2 ans de données. Le backtest couvre un seul régime de marché.
Les résultats pourraient être spécifiques à cette période.

**Impact :** Non quantifiable sans extension des données.

**Mitigation :** Le split IS/OOS aide, mais 2 ans reste court pour une
stratégie 4H. L'académique (Moskowitz 2012) teste sur 25 ans.


## RÉSUMÉ DES PRIORITÉS

| # | Biais | Impact sur ExpR | Fixable ? | Priorité |
|---|-------|----------------|-----------|----------|
| 1 | Compounding sizing | Balance gonflée, ExpR neutre | Oui (flag) | HAUTE |
| 2 | Gap risk sur SL | Sous-estime pertes | Moyen (heuristique) | MOYENNE |
| 3 | Positions non fermées | Marginal | Oui (trivial) | BASSE |
| 4 | Données Yahoo | Inconnu | Cross-validation | BASSE |
| 5 | Fenêtre 2 ans | Inconnu | Plus de données | FUTURE |

**Bonne nouvelle :** Aucun de ces biais n'invalide la COMPARAISON entre configs
(A vs B vs C...) car ils affectent toutes les configs de la même manière.
Les écarts relatifs restent fiables. Seule la valeur absolue de ExpR et du
balance final sont potentiellement gonflés.

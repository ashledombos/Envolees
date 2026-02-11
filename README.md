# Envolées — Backtest Engine

Moteur de backtest pour stratégie de breakout Donchian avec filtre EMA et volatilité, conçu pour les prop firms (FTMO, Goat Funded Trader).

---

## Quickstart

```bash
# 1. Copier et adapter la config
cp .env.example .env

# 2. Lancer un backtest rapide sur un ticker
python main.py single "EURUSD=X" -v

# 3. Lancer le backtest complet
python main.py run

# 4. Pipeline complet (IS → OOS → compare)
python main.py pipeline
```

### Exemple `.env`

```env
# Tickers et pénalités
TICKERS=EURUSD=X,GBPUSD=X,USDJPY=X,BTC-USD,ETH-USD,GC=F,^GSPC,^NDX
PENALTIES=0.00,0.10,0.20,0.25

# Stratégie
TIMEFRAME=4h
EMA_PERIOD=200
DONCHIAN_N=20
BUFFER_ATR=0.10
PROXIMITY_ATR=1.5
SL_ATR=1.00
TP_R=1.00

# Risque
START_BALANCE=100000
RISK_PER_TRADE=0.0025
MAX_CONCURRENT_TRADES=3

# Prop firm
DAILY_DD_FTMO=0.05
DAILY_DD_GFT=0.04
DAILY_EQUITY_MODE=worst
STOP_AFTER_N_LOSSES=2

# Volatilité
VOL_QUANTILE=0.95
VOL_WINDOW_BARS=1000

# Fenêtre sans trading (heure Paris)
# Mettre un intervalle d'1 min pour désactiver (ex: 23:30 / 23:31)
NO_TRADE_START=23:30
NO_TRADE_END=23:31

# Données
YF_PERIOD=730d
YF_INTERVAL=1h
TIMEZONE=Europe/Paris

# Split IS/OOS
SPLIT_MODE=time
SPLIT_RATIO=0.70

# Cache
CACHE_ENABLED=true
CACHE_MAX_AGE_HOURS=24
OUTPUT_DIR=out
```

> **Note** : `ORDER_VALID_BARS` est obsolète depuis la v2 (recalcul continu).
> Le champ existe toujours dans Config pour rétrocompatibilité mais n'est plus utilisé.

---

## Architecture générale

```
Données Yahoo (1H) → Resample (4H) → Indicateurs → Stratégie → Moteur de backtest → Résultats
```

Le système se décompose en trois couches :

1. **Stratégie** (`strategy/donchian_breakout.py`) — Décide *quand* et *où* placer un ordre stop.
2. **Moteur** (`backtest/engine.py`) — Simule l'exécution : déclenchement des stops, ouverture/fermeture des positions, gestion du P&L.
3. **Positions** (`backtest/position.py`) — Logique de chaque position individuelle : calcul du P&L, vérification des sorties SL/TP.


---

## Logique de signal : le stop proactif

### Le problème de l'ancienne approche

L'ancienne version détectait un breakout *après coup* :

```
Bar N : close = 105, canal haut = 103
→ Le prix a DÉJÀ traversé le canal
→ On place un "stop" à 103... mais le prix est à 105
→ Le backtest simule un fill à 103, ce qui est fictif
```

En live, on aurait obtenu un fill à ~105 (le prix courant), pas à 103.

### La correction : stop pré-placé

Le signal est maintenant émis *avant* le breakout. À chaque barre, on vérifie :

```
LONG : close > EMA                         (tendance OK)
       close < D_high + buffer              (PAS encore cassé)
       (D_high + buffer) - close < 1.5×ATR  (assez proche)
       → Buy-stop placé à D_high + buffer
```

Si le prix casse le canal sur la barre suivante, le stop est déclenché au bon prix. Si le prix s'éloigne ou que les conditions changent, l'ordre est annulé et recalculé.

### Recalcul continu

Le canal Donchian bouge à chaque barre (le plus haut des 20 dernières barres change). L'ordre stop doit suivre. À chaque barre, le moteur :

1. Demande à la stratégie un signal (peut être le même niveau, un niveau différent, ou rien)
2. Si signal → place ou **remplace** le pending order
3. Si pas de signal → **annule** le pending order existant

Il n'y a plus de notion d'expiration — l'ordre vit tant que les conditions sont remplies.


---

## Positions multiples (empilage momentum)

Le moteur autorise plusieurs positions ouvertes simultanément sur le même instrument. La contrainte est uniquement sur les ordres : **un seul pending order à la fois** (pas d'ordres contradictoires).

Scénario typique lors d'un fort mouvement haussier :

```
Bar 1 : stop placé à 103.0 → déclenché → Position A ouverte
Bar 2 : canal monte à 103.5 → nouveau stop à 103.6
Bar 3 : stop déclenché → Position B ouverte (A toujours active)
Bar 4 : canal monte encore → nouveau stop → Position C
...
```

Cela permet de profiter du momentum avec un risque fractionné (`risk_per_trade` par position).

Le paramètre `MAX_CONCURRENT_TRADES` (défaut 0 = illimité) plafonne le nombre de positions ouvertes. Quand le plafond est atteint, aucun nouvel ordre n'est placé jusqu'à ce qu'une position se ferme.


---

## Exécution intrabar 1H (mode par défaut)

Le moteur supporte deux modes d'exécution. Le mode **intrabar 1H** (par défaut quand les données 1H sont disponibles) élimine toutes les ambiguïtés OHLC en parcourant les bougies 1H chronologiquement.

### Le problème des OHLC 4H

Sur une bougie 4H, on dispose de 4 valeurs : Open, High, Low, Close. Quand le High touche le TP et le Low touche le SL, on ne sait pas lequel a été touché en premier. De même, quand l'entry et le SL sont touchés sur la même barre, l'ordre des événements est inconnu.

Toute résolution basée sur des heuristiques (chemin de prix, conservatisme, etc.) est un **choix de modélisation** non vérifiable — pas une vérité.

### La solution : parcourir les bougies 1H

Les données 1H sont déjà disponibles (c'est la source avant resampling). Au lieu de deviner l'ordre des événements sur 4H, le moteur parcourt les 4 bougies 1H de chaque fenêtre 4H dans l'ordre chronologique :

```
Barre 4H : 08:00-12:00 (OHLC ambigu)
  ├── 1H 08:00 : check SL/TP → pending trigger ?
  ├── 1H 09:00 : check SL/TP → pending trigger ?
  ├── 1H 10:00 : check SL/TP → pending trigger → entry ! check SL immédiat
  └── 1H 11:00 : check SL/TP sur la position ouverte
```

Règles simples à 1H :
- **SL et TP touchés sur même 1H** : conservateur (SL gagne). Très rare à 1H.
- **Entry et SL sur même 1H** : SL gagne (conservateur). Le "dip avant breakout" de 4H ne s'applique pas à 1H.
- **Pas d'heuristique** : l'ordre chronologique résout tout.

### Mode 4H fallback

Si `df_1h=None` est passé au moteur (ou pour les barres sans données 1H), le moteur utilise l'heuristique SL+TP par plausibilité du chemin (identique à la version précédente). Ceci permet de garder la compatibilité avec le diagnostic et les tests.

<details>
<summary>Détail de l'heuristique 4H (mode fallback)</summary>

### L'intuition

Prenons un LONG avec entry à 100, SL à 98.5, TP à 103.

Pour que le résultat soit un SL *suivi* d'un TP (le scénario où le mode conservateur se trompe), il faudrait que le prix fasse :

```
Open (102.5) → descend jusqu'au SL (98.5) → remonte jusqu'au TP (103)
```

Calculons le chemin minimum de ce scénario :

```
Descente : 102.5 → 98.5 = 4.0 points
Remontée : 98.5  → 103   = 4.5 points
Total    :                  8.5 points
```

Or la bougie a un range de `High - Low = 103.1 - 98.4 = 4.7 points`.

Le prix aurait dû parcourir 8.5 points de chemin dans une bougie qui n'a que 4.7 points d'amplitude. C'est physiquement impossible : le chemin minimum dépasse largement le range réel.

### La règle

```python
chemin_SL_first = |Open → SL| + |SL → TP|

if chemin_SL_first > 1.5 × range_bar:
    → TP  (le scénario SL-first ne tient pas dans cette bougie)
else:
    → SL  (le scénario est plausible, on reste conservateur)
```

Le facteur 1.5 (plutôt que 1.0) donne une marge : même si le chemin est légèrement supérieur au range, on ne bascule pas immédiatement en TP. Il faut que l'implausibilité soit franche.

### Exemples visuels

**Cas 1 — TP attribué** (open haut, range serré)

```
TP  ─────── 103.0   ···· High = 103.1
            102.5   ← Open
Entry ───── 100.0
SL  ─────── 98.5    ···· Low = 98.4

Range = 4.7 | Chemin SL-first = 8.5 | 8.5 > 7.05 (1.5×4.7) → TP ✓
```

Le prix a probablement ouvert à 102.5, fait une mèche basse à 98.4 (touchant le SL sur le papier) puis monté à 103.1 (TP). Mais pour atteindre le SL en premier il aurait fallu un aller-retour de 8.5 points dans un range de 4.7. Impossible. Le plus probable : la mèche basse s'est produite *avant* ou indépendamment de la montée vers le TP.

**Cas 2 — SL attribué** (open bas, gros range)

```
TP  ─────── 103.0   ···· High = 104
            
Entry ───── 100.0
            99.5    ← Open
SL  ─────── 98.5    ···· Low = 98.0

Range = 6.0 | Chemin SL-first = 5.5 | 5.5 < 9.0 (1.5×6.0) → SL (conservateur)
```

Ici le range est large (6 points) et l'open est près de l'entry. Le scénario open → SL → TP ne demande que 5.5 points de chemin, ce qui tient dans le range. On ne peut pas exclure un SL → on reste conservateur.

</details>


---

## Commandes CLI

Le point d'entrée est `python main.py <commande>`.

### `run` — Backtest multi-ticker

Lance le backtest sur tous les tickers et toutes les pénalités configurés.

```bash
# Utilise les tickers et pénalités du .env
python main.py run

# Override depuis la CLI
python main.py run -t "EURUSD=X,BTC-USD" -p "0.05,0.10,0.15"

# Mode in-sample ou out-of-sample
python main.py run --split is
python main.py run --split oos

# Timeframe 1H (mode challenge)
python main.py run --timeframe 1h

# Equity mode close (moins conservateur que worst)
python main.py run --mode close
```

Options principales :

| Option | Court | Description |
|--------|-------|-------------|
| `--tickers` | `-t` | Tickers séparés par virgule (défaut : `.env`) |
| `--penalties` | `-p` | Pénalités ATR séparées par virgule (défaut : `.env`) |
| `--output` | `-o` | Répertoire de sortie (défaut : `out`) |
| `--mode` | | `close` ou `worst` (equity daily DD) |
| `--split` | | `is` / `oos` / `none` (split temporel) |
| `--timeframe` | `-tf` | `1h` ou `4h` |
| `--no-cache` | | Force le re-téléchargement des données |
| `--verbose` | `-v` | Sortie détaillée |


### `single` — Backtest mono-ticker

Backtest rapide sur un seul instrument, utile pour le debug.

```bash
python main.py single "EURUSD=X"
python main.py single "BTC-USD" -p 0.15 -v
```


### `pipeline` — Pipeline complet de validation

Enchaîne automatiquement : cache-warm → cache-verify → IS run → OOS run → compare.

```bash
# Mode par défaut (tolérant : gaps exclus, stale tolérés)
python main.py pipeline

# Mode strict (bloque si gaps OU données périmées)
python main.py pipeline --strict

# Mode strict-gaps (bloque si gaps, tolère le stale)
python main.py pipeline --strict-gaps

# Sans étape cache (données déjà prêtes)
python main.py pipeline --skip-cache
```


### `compare` — Comparaison IS / OOS

Compare les résultats in-sample et out-of-sample pour valider les instruments.

```bash
python main.py compare out_is/ out_oos/
python main.py compare out_is/ out_oos/ --min-trades 10 --dd-cap 0.015 --alert
```

Options : `--output`, `--ref-penalty`, `--min-trades`, `--dd-cap`, `--max-tickers`, `--alert`.


### Commandes cache

```bash
# Voir les stats du cache
python main.py cache

# Préchauffer le cache (télécharge les données)
python main.py cache-warm
python main.py cache-warm --tickers "EURUSD=X,GBPUSD=X" --force

# Vérifier l'intégrité (gaps, données périmées)
python main.py cache-verify
python main.py cache-verify --fail-on-gaps --detailed

# Vider le cache
python main.py cache-clear
```


### Commandes utilitaires

```bash
# Afficher la configuration active
python main.py config

# Voir le statut courant (positions, signaux)
python main.py status
python main.py status --output telegram

# Envoyer un heartbeat
python main.py heartbeat

# Envoyer une alerte manuelle
python main.py alert "Test message" --level warning

# Lister les instruments FTMO disponibles
python main.py instruments
python main.py instruments --gft-only --format env
python main.py instruments --no-crypto --max-priority 2
```


---

## Paramètres clés

| Paramètre | Défaut | Description |
|-----------|--------|-------------|
| `PROXIMITY_ATR` | 1.5 | Distance max au canal pour placer un stop (en multiples ATR). Plus haut = plus de signaux mais plus de faux départs. |
| `BUFFER_ATR` | 0.10 | Buffer ajouté au bord du canal pour éviter le bruit. Entry LONG = D_high + 0.10×ATR. |
| `SL_ATR` | 1.00 | Distance du SL par rapport à l'entry (en multiples ATR). |
| `TP_R` | 1.00 | Ratio risque/récompense. TP = entry + TP_R × (entry − SL). |
| `RISK_PER_TRADE` | 0.0025 | Risque par position (0.25% du capital). |
| `MAX_CONCURRENT_TRADES` | 0 | Plafond de positions simultanées (0 = illimité). |
| `EXEC_PENALTY_ATR` | variable | Slippage modélisé sur l'entry (décale l'entry contre nous). |
| `DONCHIAN_N` | 20 | Période du canal Donchian (plus haut/bas des N dernières barres). |
| `EMA_PERIOD` | 200 | Période EMA pour le filtre de tendance. |
| `VOL_QUANTILE` | 0.90 | Filtre volatilité : ATR relatif doit être sous le quantile 90%. |
| `NO_TRADE_START/END` | 22:30 / 06:30 | Fenêtre sans nouvelles décisions (heure Paris). |


---

## Flux d'une barre dans le moteur

```
Pour chaque barre (4H) :
│
├── 1. Calcul equity mark-to-market (toutes positions)
├── 2. Gestion changement de jour (reset daily DD)
├── 3. Mise à jour equity tracking + prop sim
│
├── 4. EXÉCUTION (mode intrabar 1H ou fallback 4H) :
│
│      Mode intrabar 1H (par défaut) :
│      ├── Pour chaque sous-barre 1H chronologique :
│      │   ├── Check SL/TP des positions ouvertes
│      │   │   (conservateur : SL gagne si les deux touchés)
│      │   ├── Pending order déclenché ?
│      │   │   └── Oui → position ouverte
│      │   │       └── Check SL/TP immédiat sur cette même 1H
│      │   └── (pas d'heuristique : l'ordre chrono résout tout)
│      │
│      Mode 4H fallback (si pas de données 1H) :
│      ├── Check SL/TP (heuristique chemin si ambigu)
│      └── Pending order déclenché ? → position ouverte
│
└── 5. Recalcul du signal (sur indicateurs 4H) :
       ├── Conditions remplies → place/remplace le pending order
       ├── Conditions non remplies → annule le pending order
       └── Plafond positions atteint → pas de nouvel ordre
```


---

## Structure des fichiers

```
envolees/
├── strategy/
│   ├── base.py                 # Classes abstraites (Signal, Strategy)
│   └── donchian_breakout.py    # Stratégie Donchian + EMA + volatilité
├── backtest/
│   ├── engine.py               # Moteur principal (boucle bar-by-bar)
│   ├── position.py             # OpenPosition, PendingOrder, TradeRecord
│   └── prop_sim.py             # Simulation règles prop firm (DD limits)
├── indicators/
│   ├── atr.py, donchian.py, ema.py
├── data/
│   ├── yahoo.py                # Téléchargement Yahoo Finance
│   ├── cache.py                # Cache local des données
│   └── calendar.py, aliases.py, ftmo_instruments.py
├── output/
│   ├── scoring.py              # Métriques de performance
│   ├── compare.py              # Comparaison multi-ticker/multi-penalty
│   └── export.py               # Export résultats
├── config.py                   # Configuration (.env → dataclass)
├── cli.py                      # Interface ligne de commande
├── prefilter.py                # Pré-sélection instruments
├── alerts.py                   # Alertes TradingView / webhook
└── profiles.py                 # Profils de risque (challenge/funded)
```

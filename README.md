# 🚀 Envolées

**Backtest engine for Donchian breakout strategy with prop firm simulation**

## Features

- **Stratégie Donchian Breakout** : EMA200 + Donchian(20) + buffer ATR
- **Simulation Prop Firm** : Daily DD (FTMO/GFT), kill-switch, limite de pertes
- **Modèle de coûts** : Pénalité d'exécution en multiples d'ATR
- **Multi-assets** : FX, Crypto, Indices, Commodities
- **Split temporel IS/OOS** : Validation croisée in-sample / out-of-sample
- **Cache local** : Évite de retélécharger les données Yahoo
- **Alias tickers** : Utilise `GOLD` au lieu de `GC=F`, `BTC` au lieu de `BTC-USD`
- **Scoring automatique** : Score agrégé par ticker + génération shortlist
- **Export complet** : CSV trades, equity curve, stats journalières, scores, shortlist

## Installation

```bash
# Clone
git clone git@github.com:ashledombos/envolees.git && cd envolees

# Environnement virtuel (recommandé)
python -m venv .venv
source .venv/bin/activate  # Linux/Mac

# Installation
pip install -e .

# Ou avec dépendances dev
pip install -e ".[dev]"
```

## Configuration

```bash
# Copier le template
cp .env.example .env

# Ou utiliser une config spécialisée
cp .env.challenge.example .env   # Pour challenge prop firm
cp .env.funded.example .env      # Pour compte funded
```

### Fichiers de configuration

| Fichier | Usage |
|---------|-------|
| `.env.example` | Template de base |
| `.env.full.example` | Validation complète avec split IS/OOS |
| `.env.best.example` | Production candidate (panier validé) |
| `.env.challenge.example` | Challenge prop firm (risque modéré) |
| `.env.funded.example` | Compte funded (ultra-conservateur) |

### Variables principales

| Variable | Description | Défaut |
|----------|-------------|--------|
| `TICKERS` | Liste des tickers | Portfolio multi-asset |
| `PENALTIES` | Pénalités ATR | 0.05 à 0.25 |
| `RISK_PER_TRADE` | Risque par trade | 0.25% |
| `MODE` | Daily DD mode | worst |
| `SPLIT_MODE` | Split temporel | (désactivé) |
| `SPLIT_TARGET` | is ou oos | is |

## Usage

### CLI

```bash
# Backtest complet
python main.py run

# Tickers spécifiques (supporte les alias)
python main.py run -t BTC,ETH,GOLD,SP500

# Split out-of-sample
python main.py run --split oos -o out_oos

# Un seul ticker
python main.py single BTC-USD --penalty 0.10

# Comparer IS vs OOS (avec shortlist)
python main.py compare out_is out_oos -o out_compare --alert

# Gestion du cache
python main.py cache           # Stats cache
python main.py cache-warm      # Pré-charger les données
python main.py cache-verify    # Vérifier intégrité
python main.py cache-clear     # Vider le cache

# Configuration
python main.py config
```

### Workflow complet (recherche)

```bash
# 1. Pré-charger le cache
python main.py cache-warm

# 2. Vérifier les données
python main.py cache-verify --fail-on-gaps

# 3. In-sample
SPLIT_TARGET=is OUTPUT_DIR=out_is python main.py run

# 4. Out-of-sample
SPLIT_TARGET=oos OUTPUT_DIR=out_oos python main.py run

# 5. Comparer et générer shortlist
python main.py compare out_is out_oos --dd-cap 0.012 --max-tickers 5 --alert
```

### Workflow validation IS/OOS

```bash
# 1. In-sample (70% des données)
SPLIT_TARGET=is OUTPUT_DIR=out_is python main.py run

# 2. Out-of-sample (30% des données)
SPLIT_TARGET=oos OUTPUT_DIR=out_oos python main.py run

# 3. Comparer les résultats
head out_is/results.csv
head out_oos/results.csv
```

### Alias de tickers

Plus besoin de retenir les symboles Yahoo. Les alias sont définis dans `envolees/data/aliases.py`.

| Alias | Yahoo Symbol | Classe |
|-------|-------------|--------|
| `GOLD`, `XAUUSD` | `GC=F` | Metals |
| `SILVER`, `XAGUSD` | `SI=F` | Metals |
| `WTI`, `CRUDE` | `CL=F` | Energy |
| `BRENT`, `BCO` | `BZ=F` | Energy |
| `BTC` | `BTC-USD` | Crypto |
| `ETH` | `ETH-USD` | Crypto |
| `SOL` | `SOL-USD` | Crypto |
| `SP500`, `SPX` | `^GSPC` | Index |
| `NASDAQ`, `NDX` | `^NDX` | Index |
| `DOW`, `DJI` | `^DJI` | Index |
| `DAX` | `^GDAXI` | Index |
| `FTSE` | `^FTSE` | Index |
| `NIKKEI`, `N225`, `JAP225` | `^N225` | Index |
| `CAC40` | `^FCHI` | Index |
| `EURUSD` | `EURUSD=X` | FX |
| `GBPUSD` | `GBPUSD=X` | FX |
| `USDJPY` | `USDJPY=X` | FX |
| `AUDUSD` | `AUDUSD=X` | FX |
| `NZDUSD` | `NZDUSD=X` | FX |

### Syntaxe WEIGHT_*

Les pondérations utilisent des **alias normalisés** (sans caractères spéciaux) :

```bash
# ✅ Correct
WEIGHT_BTC=0.8       # pour BTC-USD
WEIGHT_EURUSD=1.0    # pour EURUSD=X
WEIGHT_GSPC=0.9      # pour ^GSPC
WEIGHT_GC=0.75       # pour GC=F
WEIGHT_USDJPY=0.5    # pour USDJPY=X

# ❌ Incorrect (caractères spéciaux non supportés dans les noms de variables)
WEIGHT_BTC-USD=0.8
WEIGHT_^GSPC=0.9
WEIGHT_GC=F=0.75
```

## Validation IS/OOS

### Workflow complet

```bash
# 1. In-sample (70% des données)
SPLIT_TARGET=is OUTPUT_DIR=out_is python main.py run

# 2. Out-of-sample (30% des données)
SPLIT_TARGET=oos OUTPUT_DIR=out_oos python main.py run

# 3. Comparer et valider
python main.py compare out_is out_oos -o out_compare
```

### Critères d'éligibilité OOS

Un ticker est validé si (à la pénalité de référence, défaut 0.25) :

| Critère | Seuil | Description |
|---------|-------|-------------|
| `n_trades` | ≥ 15 | Assez de trades pour être significatif |
| `expectancy_r` | > 0 | Expectancy positive |
| `profit_factor` | ≥ 1.2 | PF minimum |
| `max_daily_dd` | < 5% | Drawdown journalier acceptable |
| `exp_drop` | < 50% | Dégradation IS→OOS limitée |

### Rapports générés

```
out_compare/
├── comparison_full.csv   # Toutes les pénalités
├── comparison_ref.csv    # Pénalité de référence uniquement
└── validated.csv         # Tickers validés OOS
```

## Output

```
out/
├── results.csv              # Détails tous backtests
├── scores.csv               # Score agrégé par ticker
├── shortlist.csv            # Candidats production
├── BTC-USD/
│   ├── PEN_0.05/
│   │   ├── trades.csv
│   │   ├── equity_curve.csv
│   │   ├── daily_stats.csv
│   │   └── summary.json
│   └── ...
└── ...
```

### Shortlist automatique

Le fichier `shortlist.csv` contient les tickers qui passent les critères :
- Expectancy > 0.10 à PEN 0.25
- Profit Factor > 1.2
- Max Daily DD < 4.5%
- Minimum 30 trades

## Stratégie

### Règles d'entrée

1. **Filtre tendance** : Close > EMA200 (long) ou Close < EMA200 (short)
2. **Signal** : Breakout Donchian(20) + buffer 0.10×ATR
3. **Filtre volatilité** : ATR relatif < quantile 90%
4. **Fenêtre** : Pas de signaux 22:30 - 06:30 Paris

### Exécution

- Ordre stop valable 1 bougie 4H
- Pénalité d'exécution appliquée à l'entrée
- SL = Entry - 1×ATR
- TP = Entry + 1×ATR (RR 1:1)

### Convention conservative

Si SL et TP touchés même bougie → SL prioritaire

## Simulation Prop Firm

- **Daily DD mode "worst"** : Mark-to-market sur Low (long) / High (short)
- **Kill-switch** : Trading arrêté si daily DD ≥ 4%
- **Limite pertes** : Trading arrêté après 2 pertes clôturées/jour
- **Métriques** : Max daily DD, P99, violations FTMO/GFT

## Alertes

### Configuration

```bash
# .env
# ntfy (notifications push légères)
NTFY_TOPIC=envolees-trading
NTFY_SERVER=https://ntfy.sh

# Telegram (notifications détaillées)
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=123456789
```

### Usage

```bash
# Envoyer une alerte après compare
python main.py compare out_is out_oos --alert
```

### Format des alertes

**ntfy** (une ligne) :
```
CHALLENGE │ open:2 │ exp:0.9R │ budget:0.7% │ E1/TP1/SL0
```

**Telegram** (détaillé) :
```
🚀 Envolées — challenge
📅 2026-01-11 19:00

💰 Budget jour: 1.5% │ consommé: 0.8% │ restant: 0.7%
📊 Ouverts: 2 │ exposition: 0.9R │ max: 0.5R (NZDUSD)
📝 Événements: 1 entrée │ 1 TP

🎯 Shortlist: NZDUSD(1.2), GBPUSD(1.1), USDJPY(0.8)
```

## Services Systemd

Pour automatiser la recherche 2x/jour :

```bash
# Copier les fichiers
cp systemd/envolees-research.service ~/.config/systemd/user/
cp systemd/envolees-research.timer ~/.config/systemd/user/

# Activer
systemctl --user daemon-reload
systemctl --user enable --now envolees-research.timer

# Logs
journalctl --user -u envolees-research.service -f
```

Voir `systemd/README.md` pour plus de détails.

## Development

```bash
# Tests
pytest

# Lint
ruff check envolees/

# Type check
mypy envolees/
```

## License

MIT

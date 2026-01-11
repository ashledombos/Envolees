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

# Gestion du cache
python main.py cache          # Stats cache
python main.py cache-clear    # Vider le cache

# Configuration
python main.py config
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

Plus besoin de retenir les symboles Yahoo :

| Alias | Yahoo Symbol |
|-------|-------------|
| `GOLD` | `GC=F` |
| `SILVER` | `SI=F` |
| `WTI`, `CRUDE` | `CL=F` |
| `BRENT` | `BZ=F` |
| `BTC` | `BTC-USD` |
| `ETH` | `ETH-USD` |
| `SP500`, `SPX` | `^GSPC` |
| `NASDAQ`, `NDX` | `^NDX` |
| `DAX` | `^GDAXI` |
| `EURUSD` | `EURUSD=X` |

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

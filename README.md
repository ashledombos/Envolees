# 🚀 Envolées

**Backtest engine for Donchian breakout strategy with prop firm simulation**

## Features

- **Stratégie Donchian Breakout** : EMA200 + Donchian(20) + buffer ATR
- **Simulation Prop Firm** : Daily DD (FTMO/GFT), kill-switch, limite de pertes
- **Modèle de coûts** : Pénalité d'exécution en multiples d'ATR
- **Multi-assets** : FX, Crypto, Indices, Commodities
- **Export complet** : CSV trades, equity curve, stats journalières, JSON summary

## Installation

```bash
# Clone
git clone <repo> && cd envolees

# Environnement virtuel (recommandé)
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Installation
pip install -e .

# Ou avec dépendances dev
pip install -e ".[dev]"
```

## Configuration

```bash
# Copier le template
cp .env.example .env

# Éditer selon vos besoins
nano .env
```

### Variables principales

| Variable | Description | Défaut |
|----------|-------------|--------|
| `TICKERS` | Liste des tickers | FX + Crypto + Indices |
| `EXEC_PENALTIES` | Pénalités ATR | 0.05, 0.10, 0.15, 0.20, 0.25 |
| `RISK_PER_TRADE` | Risque par trade | 0.25% |
| `DAILY_KILL_SWITCH` | Seuil DD journalier | 4% (GFT) |
| `DAILY_EQUITY_MODE` | Mode DD: `close` ou `worst` | worst |

## Usage

### CLI

```bash
# Backtest complet (tous tickers × toutes pénalités)
python main.py run

# Tickers spécifiques
python main.py run -t BTC-USD,ETH-USD,EURUSD=X

# Pénalités spécifiques
python main.py run -p 0.10,0.15

# Un seul ticker
python main.py single BTC-USD --penalty 0.10

# Afficher la configuration
python main.py config
```

### Programmatique

```python
from envolees import Config
from envolees.backtest import BacktestEngine
from envolees.data import download_1h, resample_to_4h
from envolees.strategy import DonchianBreakoutStrategy

# Config
cfg = Config.from_env()

# Data
df_1h = download_1h("BTC-USD", cfg)
df_4h = resample_to_4h(df_1h)

# Backtest
strategy = DonchianBreakoutStrategy(cfg)
engine = BacktestEngine(cfg, strategy, "BTC-USD", exec_penalty_atr=0.10)
result = engine.run(df_4h)

# Résultats
print(f"Trades: {result.summary['n_trades']}")
print(f"Win Rate: {result.summary['win_rate']:.1%}")
print(f"Profit Factor: {result.summary['profit_factor']:.2f}")
```

## Output

```
out/
├── results.csv              # Synthèse tous backtests
├── BTC-USD/
│   ├── PEN_0.05/
│   │   ├── trades.csv
│   │   ├── equity_curve.csv
│   │   ├── daily_stats.csv
│   │   └── summary.json
│   ├── PEN_0.10/
│   │   └── ...
│   └── ...
└── EURUSD_X/
    └── ...
```

## Stratégie

### Règles d'entrée

1. **Filtre tendance** : Close > EMA200 (long) ou Close < EMA200 (short)
2. **Signal** : Breakout Donchian(20) + buffer 0.10×ATR
3. **Filtre volatilité** : ATR relatif < quantile 90%
4. **Fenêtre** : Pas de nouveaux signaux 22:30 - 06:30 Paris

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

GPL

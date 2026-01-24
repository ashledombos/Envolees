# 🚀 Envolées

Moteur de backtest pour stratégie Donchian Breakout, optimisé pour les challenges FTMO et Goat Funded Trader.

## Installation

```bash
# Cloner le repo
git clone <repo_url>
cd envolees

# Créer l'environnement virtuel
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# ou .venv\Scripts\activate  # Windows

# Installer
pip install -e .
```

## Configuration

Créer un fichier `.env` à la racine :

```bash
# Tickers à backtester (générer avec: envolees instruments --format env)
TICKERS=EURUSD=X,GBPUSD=X,USDJPY=X,BTC-USD,ETH-USD,GC=F

# Pénalités d'exécution (multiples ATR)
PENALTIES=0.00,0.10,0.20,0.25

# Capital et risque
START_BALANCE=100000
RISK_PER_TRADE=0.0025

# Profil de risque: default, challenge, funded, conservative, aggressive
PROFILE=challenge

# Cache
CACHE_ENABLED=true
CACHE_MAX_AGE_HOURS=24

# Split IS/OOS
SPLIT_MODE=time
SPLIT_RATIO=0.70

# Alertes Telegram (optionnel)
TELEGRAM_BOT_TOKEN=xxx
TELEGRAM_CHAT_ID=xxx
```

---

## Commandes CLI

### `envolees instruments`

Liste les instruments FTMO avec leur mapping Yahoo Finance.

```bash
# Afficher tous les instruments recommandés
envolees instruments

# Format tableau détaillé
envolees instruments --format table

# Générer la variable TICKERS pour .env
envolees instruments --format env
envolees instruments --format env > .env.tickers

# Exclure les crypto
envolees instruments --no-crypto

# Exclure les indices (Yahoo n'a que ~7 mois d'historique)
envolees instruments --no-indices

# Seulement les instruments priorité 1-2 (core)
envolees instruments -p 2

# Format JSON
envolees instruments --format json -o instruments.json

# Uniquement compatibles GFT (Goat Funded Trader)
envolees instruments --gft-only
```

**Options :**
| Option | Description |
|--------|-------------|
| `--crypto/--no-crypto` | Inclure/exclure les crypto |
| `--indices/--no-indices` | Inclure/exclure les indices |
| `--stocks/--no-stocks` | Inclure/exclure les actions |
| `-p, --max-priority` | Priorité max (1=core, 5=marginal) |
| `--gft-only` | Uniquement instruments GFT |
| `-f, --format` | `list`, `env`, `json`, `table` |
| `-o, --output` | Fichier de sortie |

---

### `envolees pipeline`

Exécute le pipeline complet de validation : cache → IS → OOS → compare.

```bash
# Pipeline standard (gaps bloquants, stale toléré)
envolees pipeline

# Mode strict : gaps ET stale bloquants
envolees pipeline --strict

# Strict sur les gaps uniquement
envolees pipeline --strict-gaps

# Sans alerte Telegram
envolees pipeline --no-alert

# Sauter l'étape de cache
envolees pipeline --skip-cache
```

**Options :**
| Option | Description |
|--------|-------------|
| `--skip-cache` | Sauter cache-warm et cache-verify |
| `--strict` | Échouer si gaps OU données stale |
| `--strict-gaps` | Échouer si gaps (stale = warning) |
| `--alert/--no-alert` | Envoyer alerte Telegram après compare |

---

### `envolees run`

Lance le backtest sur plusieurs tickers et pénalités.

```bash
# Utiliser les tickers du .env
envolees run

# Spécifier les tickers
envolees run -t "EURUSD=X,GBPUSD=X,BTC-USD"

# Spécifier les pénalités
envolees run -p "0.10,0.20,0.25"

# Mode IS (in-sample)
envolees run --split is -o out_is

# Mode OOS (out-of-sample)
envolees run --split oos -o out_oos

# Forcer le re-téléchargement
envolees run --no-cache

# Mode verbeux
envolees run -v
```

**Options :**
| Option | Description |
|--------|-------------|
| `-t, --tickers` | Tickers (séparés par virgule) |
| `-p, --penalties` | Pénalités ATR (séparées par virgule) |
| `-o, --output` | Dossier de sortie |
| `--mode` | `close` ou `worst` (équité journalière) |
| `--split` | `is`, `oos`, ou `none` |
| `--no-cache` | Forcer re-téléchargement |
| `-v, --verbose` | Sortie détaillée |

---

### `envolees single`

Lance le backtest sur un seul ticker.

```bash
# Backtest simple
envolees single EURUSD=X

# Avec pénalité spécifique
envolees single EURUSD=X -p 0.25

# Sortie personnalisée
envolees single BTC-USD -o results/btc -v
```

**Options :**
| Option | Description |
|--------|-------------|
| `-p, --penalty` | Pénalité d'exécution (défaut: 0.10) |
| `-o, --output` | Dossier de sortie |
| `--no-cache` | Forcer re-téléchargement |
| `-v, --verbose` | Sortie détaillée |

---

### `envolees compare`

Compare les résultats IS et OOS pour validation.

```bash
# Comparaison standard
envolees compare out_is out_oos -o out_compare

# Pénalité de référence différente
envolees compare out_is out_oos -p 0.20

# Critères personnalisés
envolees compare out_is out_oos --min-trades 20 --dd-cap 0.01

# Sans alerte
envolees compare out_is out_oos --no-alert
```

**Options :**
| Option | Description |
|--------|-------------|
| `-o, --output` | Dossier pour le rapport |
| `-p, --penalty` | Pénalité de référence (défaut: 0.25) |
| `--min-trades` | Trades minimum OOS (défaut: 15) |
| `--dd-cap` | DD maximum (défaut: 0.012 = 1.2%) |
| `--max-tickers` | Max tickers shortlist (défaut: 20) |
| `--alert/--no-alert` | Envoyer alerte avec résultats |

**Tiers de sortie :**
- **Tier 1 (Funded)** : ≥15 trades OOS, critères stricts
- **Tier 2 (Challenge)** : ≥10 trades OOS, critères plus souples

---

### `envolees cache-warm`

Pré-télécharge les données dans le cache.

```bash
# Réchauffer le cache (respecte CACHE_MAX_AGE_HOURS)
envolees cache-warm

# Forcer le re-téléchargement de tout
envolees cache-warm --force

# Tickers spécifiques
envolees cache-warm -t "EURUSD=X,BTC-USD"
```

**Options :**
| Option | Description |
|--------|-------------|
| `-t, --tickers` | Tickers spécifiques |
| `-f, --force` | Ignorer le cache existant |

---

### `envolees cache-verify`

Vérifie l'intégrité du cache et détecte les gaps.

```bash
# Vérification standard
envolees cache-verify

# Mode verbeux (détail des gaps)
envolees cache-verify -v

# Exporter les tickers éligibles
envolees cache-verify --export-eligible eligible.txt

# Échouer si gaps détectés
envolees cache-verify --fail-on-gaps

# Échouer si données stale
envolees cache-verify --fail-on-stale
```

**Options :**
| Option | Description |
|--------|-------------|
| `-t, --tickers` | Tickers à vérifier |
| `--fail-on-gaps` | Exit code erreur si gaps |
| `--fail-on-stale` | Exit code erreur si stale |
| `--export-eligible` | Exporter tickers valides |
| `-v, --verbose` | Analyse détaillée des gaps |

---

### `envolees cache`

Affiche les statistiques du cache.

```bash
envolees cache
```

---

### `envolees cache-clear`

Vide le cache de données.

```bash
# Avec confirmation
envolees cache-clear

# Sans confirmation
envolees cache-clear --yes
```

---

### `envolees config`

Affiche la configuration actuelle.

```bash
envolees config
```

---

### `envolees status`

Affiche le statut de trading actuel.

```bash
# Format texte
envolees status

# Format JSON
envolees status -o json
```

---

### `envolees heartbeat`

Envoie un signal de vie (pour monitoring).

```bash
envolees heartbeat
```

---

### `envolees alert`

Envoie une alerte manuelle (Telegram).

```bash
# Alerte warning (défaut)
envolees alert "Pipeline terminé avec succès"

# Alerte info
envolees alert "Test de connexion" -l info

# Alerte critique
envolees alert "Erreur détectée!" -l critical
```

**Options :**
| Option | Description |
|--------|-------------|
| `-l, --level` | `info`, `warning`, `critical` |

---

## Workflow typique

### 1. Générer la liste d'instruments

```bash
# Voir les instruments disponibles
envolees instruments --format table

# Générer pour .env (sans actions ni indices problématiques)
envolees instruments --no-stocks --no-indices --format env
```

### 2. Configurer `.env`

```bash
# Copier la sortie dans .env
TICKERS=EURUSD=X,GBPUSD=X,...
```

### 3. Lancer le pipeline

```bash
# Pipeline complet
envolees pipeline

# Ou étape par étape:
envolees cache-warm --force
envolees cache-verify -v
envolees run --split is -o out_is
envolees run --split oos -o out_oos
envolees compare out_is out_oos -o out_compare
```

### 4. Analyser les résultats

Les fichiers de sortie sont dans `out_compare/` :
- `shortlist_tier1.csv` : Instruments pour compte Funded (≥15 trades)
- `shortlist_tier2.csv` : Instruments pour Challenge (≥10 trades)
- `shortlist_tradable.csv` : Liste combinée
- `comparison_ref.csv` : Détails complets

---

## Gestion des gaps

Le système distingue 3 types de gaps :

| Type | Description | Comportement |
|------|-------------|--------------|
| **Expected** | Week-end, jours fériés | Ignoré ✅ |
| **Tolerated** | Gaps ≤ seuil par instrument | Warning ⚠️ |
| **Unexpected** | Gaps > seuil | Bloquant ❌ |

Seuils par classe d'actif :
- **Forex** : 0 gaps tolérés (strict)
- **Crypto** : 3 gaps tolérés (maintenance Yahoo)
- **Indices US** : 15 gaps tolérés (jours fériés)
- **Indices EU** : 10 gaps tolérés

---

## Mapping FTMO → Yahoo

Certains instruments FTMO ont des noms différents sur Yahoo Finance :

| FTMO | Yahoo | Notes |
|------|-------|-------|
| NERUSD | NEAR-USD | Near Protocol |
| LNKUSD | LINK-USD | Chainlink |
| AVAUSD | AVAX-USD | Avalanche |
| AAVUSD | AAVE-USD | Aave |
| XAUUSD | GC=F | Gold futures |
| XAGUSD | SI=F | Silver futures |
| US500.cash | ^GSPC | S&P 500 |
| US100.cash | ^NDX | Nasdaq 100 |
| GER40.cash | ^GDAXI | DAX |

Voir `envolees/data/ftmo_instruments.py` pour la liste complète.

---

## Fichiers de sortie

```
out_compare/
├── comparison_full.csv     # Toutes pénalités
├── comparison_ref.csv      # Pénalité de référence (0.25)
├── shortlist_tier1.csv     # Tier 1 - Funded (≥15 trades)
├── shortlist_tier2.csv     # Tier 2 - Challenge (≥10 trades)
└── shortlist_tradable.csv  # Combiné Tier 1 + 2
```

---

## Automatisation (systemd)

Des fichiers systemd sont fournis dans `systemd/` pour :
- `envolees-cache.timer` : Mise à jour quotidienne du cache
- `envolees-validation.timer` : Pipeline hebdomadaire
- `envolees-heartbeat.timer` : Signal de vie

Voir `systemd/README.md` pour l'installation.

---

## Dépannage

### "Yahoo Finance: aucune donnée pour X"

Certaines crypto sont delisted sur Yahoo (UNI-USD, IMX-USD, GRT-USD). 
Utiliser `envolees instruments` pour voir les instruments disponibles.

### Indices avec 0 trades OOS

Yahoo ne fournit que ~7 mois d'historique pour les indices (^GSPC, ^NDX...).
Avec un split 70/30, l'OOS n'a pas assez de données.
Solution : exclure les indices (`--no-indices`) ou réduire `SPLIT_RATIO`.

### Gaps inattendus sur crypto

Yahoo agrège parfois mal les données crypto 24/7.
Le système tolère maintenant 3 gaps par crypto.

---

## Licence

MIT

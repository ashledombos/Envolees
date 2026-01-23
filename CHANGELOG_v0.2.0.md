# Changelog - Améliorations Envolées v0.2.0

## Nouvelles fonctionnalités

### 1. Mapping complet des instruments FTMO (`envolees/data/ftmo_instruments.py`)

Nouveau fichier qui centralise :
- **90+ instruments FTMO** avec leur symbole Yahoo équivalent
- Classification par type d'actif (forex, crypto, métaux, énergie, indices, etc.)
- Priorité de trading (1=core, 5=marginal)
- **Tolérance aux gaps** configurable par instrument (`max_extra_gaps`)

Exemples :
```python
from envolees.data import get_max_extra_gaps, get_recommended_instruments

# Les crypto tolèrent 3 gaps inattendus (maintenance Yahoo)
get_max_extra_gaps("BTC-USD")  # → 3

# Les indices US tolèrent 15 gaps (jours fériés)
get_max_extra_gaps("^GSPC")  # → 15

# Le forex ne tolère aucun gap
get_max_extra_gaps("EURUSD=X")  # → 0
```

### 2. Calendrier amélioré avec jours fériés (`envolees/data/calendar.py`)

- **Classification crypto étendue** : 30+ crypto reconnues (avant: seulement 7)
- **Jours fériés US** : MLK Day, Presidents Day, Good Friday, Memorial Day, Juneteenth, Labor Day, Thanksgiving, Christmas, etc.
- **Jours fériés EU** : principaux jours fériés européens
- **Fonction `is_us_holiday()` et `is_eu_holiday()`** pour vérifier les dates

### 3. Validation des gaps flexible

Avant : tout gap inattendu bloquait l'instrument.

Maintenant : chaque instrument a un seuil de tolérance (`max_extra_gaps`) :
- **Forex** : 0 (strict)
- **Crypto** : 3 (Yahoo a des gaps de maintenance)
- **Indices US** : 15 (jours fériés)
- **Indices EU** : 10 (jours fériés)

### 4. Nouvelle commande CLI `instruments`

```bash
# Lister tous les instruments recommandés
envolees instruments

# Format tableau détaillé
envolees instruments --format table

# Générer un .env
envolees instruments --format env > .env.tickers

# Sans crypto ni indices (forex + commodities seulement)
envolees instruments --no-crypto --no-indices

# Seulement les instruments priorité 1-2
envolees instruments -p 2

# Uniquement compatibles GFT
envolees instruments --gft-only
```

## Fichiers modifiés

1. **`envolees/data/ftmo_instruments.py`** (nouveau)
   - Définition complète des instruments FTMO
   - Mapping Yahoo Finance
   - Fonctions d'accès

2. **`envolees/data/calendar.py`**
   - Classification crypto étendue
   - Jours fériés US/EU
   - `analyze_gaps()` avec `max_unexpected_gaps`
   - `GapAnalysis.is_acceptable()`

3. **`envolees/data/__init__.py`**
   - Export des nouvelles fonctions

4. **`envolees/cli.py`**
   - Validation des gaps utilise `is_acceptable()`
   - Nouvelle commande `instruments`

## Migration

### Avant

```bash
# .env avec liste manuelle
TICKERS=EURUSD=X,GBPUSD=X,BTC-USD,...
```

### Après

```bash
# Générer automatiquement la liste optimisée
envolees instruments --format env > .env.tickers

# Ou utiliser les instruments recommandés sans crypto
envolees instruments --no-crypto --format env
```

## Compatibilité

- Compatible avec la configuration existante
- Les gaps sont maintenant plus tolérants pour les indices et crypto
- Le comportement par défaut pour le forex reste strict

## À venir (suggestions)

1. **Source cTrader** : télécharger les données directement depuis cTrader Open API pour une cohérence parfaite avec FTMO
2. **Source Binance** : pour les crypto avec qualité 24/7
3. **Cache multi-sources** : combiner Yahoo + cTrader + Binance

# Envolées - Automatisation systemd

## Architecture

Trois timers indépendants :

| Timer | Fréquence | Fonction |
|-------|-----------|----------|
| `envolees-cache` | 6h | Maintient le cache à jour |
| `envolees-validation` | 1x/jour (07:00) | Pipeline complet IS/OOS |
| `envolees-heartbeat` | 1x/jour (08:30) | Signal de vie "tout va bien" |

## Installation rapide

```bash
# 1. Copier les fichiers
mkdir -p ~/.config/systemd/user
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/

# 2. Recharger systemd
systemctl --user daemon-reload

# 3. Activer les timers
systemctl --user enable --now envolees-cache.timer
systemctl --user enable --now envolees-validation.timer
systemctl --user enable --now envolees-heartbeat.timer
```

## Vérification

```bash
# Voir les timers actifs
systemctl --user list-timers

# Statut d'un timer
systemctl --user status envolees-validation.timer

# Logs d'un service
journalctl --user -u envolees-validation.service -f

# Exécuter manuellement
systemctl --user start envolees-validation.service
```

## Comportement du pipeline

### Mode tolérant (par défaut)

Le pipeline est **tolérant par ticker** :

1. **Cache verify** identifie les tickers avec problèmes (gaps, stale)
2. Les tickers KO sont **exclus** mais le pipeline **continue**
3. Les backtests IS/OOS tournent sur les tickers éligibles
4. L'alerte finale liste les exclusions et motifs de rejet

Exemple :
```
Tickers: NZDUSD=X, GBPUSD=X, BTC-USD
BTC-USD a des gaps → exclu
Pipeline continue avec NZDUSD=X, GBPUSD=X
Alerte: "2/3 analysés, 1 exclu (BTC-USD: gaps)"
```

### Mode strict (optionnel)

Pour forcer l'échec si un ticker a des problèmes :

```bash
python main.py pipeline --strict
```

### Séparation gaps vs stale

- **gaps** : données manquantes = ticker exclu (backtest faussé)
- **stale** : données pas récentes = warning mais éligible (backtest historique OK)

## Workflow détaillé

### Cache (toutes les 6h)
1. `cache-warm` : télécharge/rafraîchit les données
2. `cache-verify` : vérifie l'intégrité, envoie alerte si problème

### Validation (1x/jour à 07:00)
Le service appelle `python main.py pipeline` qui :
1. `cache-warm` : données fraîches
2. `cache-verify --export-eligible` : liste les tickers OK
3. `run` IS : backtest in-sample (tickers éligibles uniquement)
4. `run` OOS : backtest out-of-sample
5. `compare --alert` : validation + shortlist + alerte enrichie

### Heartbeat (1x/jour à 08:30)
- Envoie un signal de vie après la validation
- Contenu minimal : "ok", cache status, shortlist size

## Alertes

Le pipeline envoie une alerte enrichie avec :
- Profil actif (challenge/funded)
- Tickers analysés vs exclus (avec raisons)
- Motifs de rejet OOS (trades insuffisants, DD trop élevé, etc.)
- Shortlist finale (top 5)
- Meilleur ticker et score

## Personnalisation

### Changer les horaires

Éditer les fichiers `.timer` :

```ini
# Validation à 19:00 au lieu de 07:00
OnCalendar=*-*-* 19:00:00
```

Puis recharger :
```bash
systemctl --user daemon-reload
```

### Désactiver un timer

```bash
systemctl --user disable envolees-heartbeat.timer
systemctl --user stop envolees-heartbeat.timer
```

## Dépannage

### Le service ne démarre pas

```bash
# Vérifier les erreurs
journalctl --user -u envolees-validation.service --no-pager -n 50

# Vérifier que .env et .env.secret existent
ls -la ~/dev/envolees/.env*
```

### Permission denied sur .env.secret

```bash
chmod 600 ~/dev/envolees/.env.secret
```

### Le timer ne se déclenche pas

```bash
# Vérifier que le timer est actif
systemctl --user is-enabled envolees-validation.timer

# Vérifier l'heure du prochain déclenchement
systemctl --user list-timers --all | grep envolees
```

### Alertes non reçues

```bash
# Vérifier la config
cat ~/dev/envolees/.env.secret

# Tester manuellement
python main.py alert "Test" --level info
```

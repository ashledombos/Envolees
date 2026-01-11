# Envolées - Automatisation systemd

## Architecture

Trois timers indépendants :

| Timer | Fréquence | Fonction |
|-------|-----------|----------|
| `envolees-cache` | 6h | Maintient le cache à jour |
| `envolees-validation` | 1x/jour (07:00) | Pipeline complet IS/OOS + compare |
| `envolees-heartbeat` | 1x/jour (08:30) | Signal de vie "tout va bien" |

## Installation

```bash
# Copier les fichiers
mkdir -p ~/.config/systemd/user
cp systemd/*.service systemd/*.timer ~/.config/systemd/user/

# Recharger systemd
systemctl --user daemon-reload

# Activer les timers
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

## Workflow

### Cache (toutes les 6h)
1. `cache-warm` : télécharge/rafraîchit les données
2. `cache-verify` : vérifie l'intégrité
3. Si erreur → alerte warning

### Validation (1x/jour à 07:00)
1. `cache-warm` : données fraîches
2. `cache-verify --fail-on-gaps` : bloquant si problème
3. `run` IS : backtest in-sample
4. `run` OOS : backtest out-of-sample
5. `compare --alert` : validation + shortlist + alerte

### Heartbeat (1x/jour à 08:30)
- Envoie un signal de vie après la validation
- Pas de chiffres anxiogènes, juste "tout va bien"

## Personnalisation

### Changer les horaires

Éditer les fichiers `.timer` :

```ini
# Validation à 19:00 au lieu de 07:00
OnCalendar=*-*-* 19:00:00
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

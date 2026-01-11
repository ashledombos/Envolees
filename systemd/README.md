# Services Systemd pour Envolées

## Installation

```bash
# Créer le répertoire utilisateur si nécessaire
mkdir -p ~/.config/systemd/user

# Copier les fichiers
cp systemd/envolees-research.service ~/.config/systemd/user/
cp systemd/envolees-research.timer ~/.config/systemd/user/

# Recharger systemd
systemctl --user daemon-reload

# Activer et démarrer le timer
systemctl --user enable --now envolees-research.timer
```

## Vérification

```bash
# Statut du timer
systemctl --user status envolees-research.timer

# Liste des timers actifs
systemctl --user list-timers

# Prochaine exécution
systemctl --user list-timers envolees-research.timer

# Logs
journalctl --user -u envolees-research.service -n 100 -f
```

## Exécution manuelle

```bash
# Lancer immédiatement (sans attendre le timer)
systemctl --user start envolees-research.service

# Suivre les logs en direct
journalctl --user -u envolees-research.service -f
```

## Personnalisation

### Modifier les horaires

Éditer `~/.config/systemd/user/envolees-research.timer` :

```ini
[Timer]
# Une seule fois par jour à 07:00
OnCalendar=*-*-* 07:00:00

# Ou toutes les 6 heures
OnCalendar=*-*-* 00,06,12,18:00:00
```

Puis recharger :

```bash
systemctl --user daemon-reload
```

### Changer de profil

Éditer `~/.config/systemd/user/envolees-research.service` :

```ini
# Ligne ExecStart : remplacer .env.challenge.example par .env.funded.example
source %h/dev/envolees/.env.funded.example
```

## Désactivation

```bash
# Désactiver le timer
systemctl --user disable --now envolees-research.timer

# Supprimer les fichiers
rm ~/.config/systemd/user/envolees-research.*
systemctl --user daemon-reload
```

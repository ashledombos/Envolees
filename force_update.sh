#! /bin/bash
# Voir les nouveaux instruments disponibles
envolees instruments --format table

# Regénérer le cache (optionnel si déjà récent)
envolees cache-warm --force

# Puis pipeline
envolees pipeline

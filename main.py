#!/usr/bin/env python3
"""
Envolées - Point d'entrée principal.

Usage:
    python main.py run                      # Backtest tous les tickers/.env
    python main.py run -t BTC-USD,ETH-USD   # Tickers spécifiques
    python main.py single BTC-USD           # Un seul ticker
    python main.py config                   # Afficher la config

Voir `python main.py --help` pour plus d'options.
"""

from envolees.cli import main

if __name__ == "__main__":
    main()

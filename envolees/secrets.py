"""
Gestion sécurisée des secrets.

Charge les secrets depuis .env.secret (prioritaire sur .env).
Vérifie que les variables sensibles ne sont pas dans .env (committé).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


# Variables considérées comme sensibles (ne doivent pas être dans .env)
SENSITIVE_VARIABLES = {
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "NTFY_TOPIC",  # Peut être sensible si public
    "API_KEY",
    "API_SECRET",
    "CTRADER_CLIENT_ID",
    "CTRADER_CLIENT_SECRET",
    "CTRADER_ACCESS_TOKEN",
    "TRADELOCKER_API_KEY",
    "TRADELOCKER_SECRET",
    "DATABASE_PASSWORD",
    "DB_PASSWORD",
}

# Fichiers de secrets possibles (ordre de priorité)
SECRET_FILES = [
    ".env.secret",
    ".secrets",
    ".env.local",
]


class SecretsManager:
    """Gestionnaire de secrets sécurisé."""
    
    def __init__(self, project_root: Path | None = None) -> None:
        """
        Initialise le gestionnaire.
        
        Args:
            project_root: Racine du projet (détectée auto si None)
        """
        if project_root is None:
            project_root = Path(__file__).resolve().parent.parent
        
        self.project_root = project_root
        self.env_path = project_root / ".env"
        self.secret_path = self._find_secret_file()
        self.secrets: dict[str, str] = {}
        self.warnings: list[str] = []
        
        self._load_secrets()
        self._check_security()
    
    def _find_secret_file(self) -> Path | None:
        """Trouve le fichier de secrets."""
        for name in SECRET_FILES:
            path = self.project_root / name
            if path.exists():
                return path
        return None
    
    def _load_secrets(self) -> None:
        """Charge les secrets depuis le fichier."""
        if self.secret_path and self.secret_path.exists():
            self.secrets = dotenv_values(self.secret_path)
    
    def _check_security(self) -> None:
        """Vérifie la sécurité de la configuration."""
        # 1. Vérifier les permissions du fichier secret
        if self.secret_path and self.secret_path.exists():
            mode = self.secret_path.stat().st_mode
            
            # Devrait être 600 (lecture/écriture uniquement pour le propriétaire)
            if mode & stat.S_IRWXG or mode & stat.S_IRWXO:
                self.warnings.append(
                    f"⚠️ {self.secret_path.name} a des permissions trop permissives. "
                    f"Exécuter: chmod 600 {self.secret_path.name}"
                )
        
        # 2. Vérifier que les variables sensibles ne sont pas dans .env
        if self.env_path.exists():
            env_values = dotenv_values(self.env_path)
            
            for var in SENSITIVE_VARIABLES:
                if var in env_values and env_values[var]:
                    self.warnings.append(
                        f"🔴 SÉCURITÉ: {var} est défini dans .env ! "
                        f"Déplacer vers .env.secret"
                    )
    
    def get(self, key: str, default: str | None = None) -> str | None:
        """
        Récupère une valeur (secret > env > default).
        
        Args:
            key: Nom de la variable
            default: Valeur par défaut
        
        Returns:
            Valeur ou default
        """
        # 1. Secret (prioritaire)
        if key in self.secrets:
            return self.secrets[key]
        
        # 2. Environnement
        env_value = os.getenv(key)
        if env_value is not None:
            return env_value
        
        # 3. Default
        return default
    
    def has_warnings(self) -> bool:
        """Retourne True si des warnings de sécurité existent."""
        return len(self.warnings) > 0
    
    def get_warnings(self) -> list[str]:
        """Retourne la liste des warnings."""
        return self.warnings.copy()
    
    def print_warnings(self) -> None:
        """Affiche les warnings."""
        for w in self.warnings:
            print(w)
    
    def check_critical(self, fail_on_warnings: bool = False) -> bool:
        """
        Vérifie les problèmes critiques.
        
        Args:
            fail_on_warnings: Si True, considère les warnings comme critiques
        
        Returns:
            True si OK, False sinon
        """
        # Vérifier les variables sensibles dans .env
        if self.env_path.exists():
            env_values = dotenv_values(self.env_path)
            
            for var in SENSITIVE_VARIABLES:
                if var in env_values and env_values[var]:
                    return False
        
        if fail_on_warnings and self.has_warnings():
            return False
        
        return True


def load_secrets(project_root: Path | None = None) -> SecretsManager:
    """
    Charge les secrets et retourne le manager.
    
    Usage:
        secrets = load_secrets()
        token = secrets.get("TELEGRAM_BOT_TOKEN")
        
        if secrets.has_warnings():
            secrets.print_warnings()
    """
    return SecretsManager(project_root)


def check_env_security(project_root: Path | None = None, strict: bool = False) -> bool:
    """
    Vérifie la sécurité de la configuration.
    
    Args:
        project_root: Racine du projet
        strict: Si True, échoue sur tout warning
    
    Returns:
        True si OK
    
    Raises:
        SecurityError: Si problème critique en mode strict
    """
    secrets = load_secrets(project_root)
    
    if not secrets.check_critical(fail_on_warnings=strict):
        secrets.print_warnings()
        if strict:
            raise SecurityError("Configuration non sécurisée")
        return False
    
    if secrets.has_warnings():
        secrets.print_warnings()
    
    return True


class SecurityError(Exception):
    """Erreur de sécurité de configuration."""
    pass


# Template pour .env.secret.example
ENV_SECRET_TEMPLATE = """# =============================================================================
# SECRETS - NE PAS COMMITER CE FICHIER
# =============================================================================
# Copier vers .env.secret et remplir les valeurs
# chmod 600 .env.secret

# -----------------------------------------------------------------------------
# Alertes
# -----------------------------------------------------------------------------
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
NTFY_TOPIC=

# -----------------------------------------------------------------------------
# API Trading (pour plus tard)
# -----------------------------------------------------------------------------
# CTRADER_CLIENT_ID=
# CTRADER_CLIENT_SECRET=
# CTRADER_ACCESS_TOKEN=

# TRADELOCKER_API_KEY=
# TRADELOCKER_SECRET=
"""


def create_secret_template(project_root: Path | None = None) -> Path:
    """
    Crée un template .env.secret.example.
    
    Returns:
        Chemin du fichier créé
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    
    path = project_root / ".env.secret.example"
    path.write_text(ENV_SECRET_TEMPLATE)
    
    return path

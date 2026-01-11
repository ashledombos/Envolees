"""
Système d'alertes pour Envolées.

Trois niveaux :
- Heartbeat : signal de vie sobre (1x/jour max)
- Status : infos consultables sur demande
- Alert : vraies alertes rares mais importantes

Canaux :
- ntfy : heartbeat + alertes (push léger)
- Telegram : status + alertes (détaillé)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


@dataclass
class AlertConfig:
    """Configuration des alertes."""
    
    # ntfy (léger, push)
    ntfy_enabled: bool = False
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""  # Optionnel, pour serveurs authentifiés
    
    # Telegram (détaillé)
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    # Profil
    profile: str = "default"
    
    # Heartbeat
    heartbeat_enabled: bool = True
    
    @classmethod
    def from_env(cls) -> AlertConfig:
        """Charge la config depuis l'environnement."""
        ntfy_topic = os.getenv("NTFY_TOPIC", "")
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        return cls(
            ntfy_enabled=bool(ntfy_topic),
            ntfy_server=os.getenv("NTFY_SERVER", "https://ntfy.sh"),
            ntfy_topic=ntfy_topic,
            ntfy_token=os.getenv("NTFY_TOKEN", ""),
            telegram_enabled=bool(telegram_token),
            telegram_bot_token=telegram_token,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            profile=os.getenv("PROFILE", os.getenv("RISK_MODE", "default")),
            heartbeat_enabled=os.getenv("HEARTBEAT", "on").lower() not in ("off", "false", "0", "no"),
        )


@dataclass
class SystemStatus:
    """État du système pour status/heartbeat."""
    
    profile: str = "default"
    timestamp: datetime = field(default_factory=datetime.now)
    
    # État cache
    cache_ok: bool = True
    cache_issues: list[str] = field(default_factory=list)
    last_data_update: str = ""
    
    # Shortlist
    shortlist: list[tuple[str, float]] = field(default_factory=list)  # [(ticker, score), ...]
    tickers_active: int = 0
    
    # Risque
    daily_budget: float = 0.0
    daily_consumed: float = 0.0
    
    # Performance
    last_execution_ok: bool = True
    last_execution_time: str = ""


@dataclass
class TradingStatus:
    """État courant du trading pour les alertes."""
    
    profile: str = "default"
    timestamp: datetime = field(default_factory=datetime.now)
    
    # Budget risque
    daily_budget: float = 0.0
    daily_consumed: float = 0.0
    
    # Positions
    open_trades: int = 0
    total_exposure_r: float = 0.0
    max_position_r: float = 0.0
    max_position_ticker: str = ""
    
    # Ordres
    pending_orders: int = 0
    
    # Événements session
    entries: int = 0
    exits_tp: int = 0
    exits_sl: int = 0
    cancellations: int = 0
    
    # Performance
    pnl_day: float = 0.0
    dd_day: float = 0.0
    dd_max: float = 0.0
    
    # Anomalies
    anomalies: list[str] = field(default_factory=list)
    
    # Shortlist active
    shortlist: list[tuple[str, float]] = field(default_factory=list)


class AlertSender:
    """Envoi d'alertes multi-canal avec niveaux séparés."""
    
    def __init__(self, config: AlertConfig | None = None) -> None:
        self.config = config or AlertConfig.from_env()
    
    def _send_ntfy(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: list[str] | None = None,
    ) -> bool:
        """Envoie via ntfy."""
        if not HAS_REQUESTS or not self.config.ntfy_enabled:
            return False
        
        try:
            url = f"{self.config.ntfy_server}/{self.config.ntfy_topic}"
            headers = {
                "Title": title,
                "Priority": str(priority),
            }
            
            if tags:
                headers["Tags"] = ",".join(tags)
            
            if self.config.ntfy_token:
                headers["Authorization"] = f"Bearer {self.config.ntfy_token}"
            
            response = requests.post(
                url,
                data=message.encode("utf-8"),
                headers=headers,
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[alert] ntfy error: {e}")
            return False
    
    def _send_telegram(self, message: str, parse_mode: str = "Markdown") -> bool:
        """Envoie via Telegram."""
        if not HAS_REQUESTS or not self.config.telegram_enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            response = requests.post(
                url,
                json={
                    "chat_id": self.config.telegram_chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                    "disable_notification": True,  # Silencieux par défaut
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[alert] telegram error: {e}")
            return False
    
    # =========================================================================
    # HEARTBEAT (signal de vie)
    # =========================================================================
    
    def send_heartbeat(self, status: SystemStatus) -> dict[str, bool]:
        """
        Envoie un heartbeat sobre (1x/jour max).
        
        Ne contient PAS de chiffres anxiogènes.
        """
        if not self.config.heartbeat_enabled:
            return {}
        
        results = {}
        
        # Message court pour ntfy
        if self.config.ntfy_enabled:
            message = f"Envolées — tout va bien\nCache OK, dernière exécution OK"
            if not status.cache_ok:
                message = f"Envolées — attention cache\n{len(status.cache_issues)} problème(s)"
            
            results["ntfy"] = self._send_ntfy(
                title=f"💚 Envolées {status.profile}",
                message=message,
                priority=1,  # Très basse priorité
                tags=["white_check_mark"] if status.cache_ok else ["warning"],
            )
        
        return results
    
    # =========================================================================
    # STATUS (info consultable)
    # =========================================================================
    
    def send_status(self, status: SystemStatus) -> dict[str, bool]:
        """
        Envoie un status détaillé (sur demande ou 1x/jour).
        
        Telegram silencieux.
        """
        results = {}
        
        if self.config.telegram_enabled:
            lines = [
                f"📊 *Envolées — état*",
                f"Mode: {status.profile}",
                "",
            ]
            
            # Shortlist
            if status.shortlist:
                lines.append(f"Tickers actifs: {status.tickers_active}")
                sl_str = ", ".join(f"{t}" for t, _ in status.shortlist[:5])
                lines.append(f"Shortlist: {sl_str}")
            else:
                lines.append("Aucun ticker actif")
            
            lines.append("")
            
            # Risque
            budget_remaining = status.daily_budget - status.daily_consumed
            lines.append(
                f"Budget jour: {status.daily_consumed*100:.1f}% / {status.daily_budget*100:.1f}%"
            )
            
            # Cache
            lines.append("")
            if status.cache_ok:
                lines.append("✓ Cache OK")
            else:
                lines.append(f"⚠ Cache: {len(status.cache_issues)} problème(s)")
            
            if status.last_data_update:
                lines.append(f"Dernières données: {status.last_data_update}")
            
            # Dernière exécution
            if status.last_execution_time:
                emoji = "✓" if status.last_execution_ok else "✗"
                lines.append(f"{emoji} Dernière exécution: {status.last_execution_time}")
            
            results["telegram"] = self._send_telegram("\n".join(lines))
        
        return results
    
    # =========================================================================
    # ALERTES (vraies alertes, rares)
    # =========================================================================
    
    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",  # info, warning, critical
        telegram_message: str | None = None,
    ) -> dict[str, bool]:
        """
        Envoie une vraie alerte (rare mais importante).
        
        Args:
            title: Titre
            message: Message court (ntfy)
            level: info, warning, critical
            telegram_message: Message long (telegram)
        """
        results = {}
        
        # Priorité ntfy selon level
        priority_map = {"info": 2, "warning": 4, "critical": 5}
        priority = priority_map.get(level, 3)
        
        # Tags ntfy
        tags_map = {
            "info": ["information_source"],
            "warning": ["warning"],
            "critical": ["rotating_light", "warning"],
        }
        tags = tags_map.get(level, [])
        
        if self.config.ntfy_enabled:
            results["ntfy"] = self._send_ntfy(
                title=title,
                message=message,
                priority=priority,
                tags=tags,
            )
        
        if self.config.telegram_enabled:
            # Pour Telegram, activer la notification si critical
            if level == "critical":
                # Re-envoyer avec notification activée
                try:
                    url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
                    requests.post(
                        url,
                        json={
                            "chat_id": self.config.telegram_chat_id,
                            "text": telegram_message or message,
                            "parse_mode": "Markdown",
                            "disable_notification": False,
                        },
                        timeout=10,
                    )
                    results["telegram"] = True
                except Exception:
                    results["telegram"] = False
            else:
                results["telegram"] = self._send_telegram(telegram_message or message)
        
        return results
    
    # =========================================================================
    # ALERTES SPÉCIFIQUES
    # =========================================================================
    
    def alert_dd_warning(self, current_dd: float, limit: float, profile: str) -> dict[str, bool]:
        """Alerte dépassement DD."""
        pct_used = (current_dd / limit) * 100 if limit > 0 else 0
        
        return self.send_alert(
            title=f"⚠ Envolées {profile} — DD",
            message=f"Budget risque {pct_used:.0f}% utilisé ({current_dd*100:.2f}% / {limit*100:.1f}%)",
            level="warning" if pct_used < 90 else "critical",
            telegram_message=(
                f"⚠️ *Envolées — alerte DD*\n\n"
                f"Profil: {profile}\n"
                f"Budget jour: {current_dd*100:.2f}% / {limit*100:.1f}%\n"
                f"Utilisation: {pct_used:.0f}%\n\n"
                f"{'Trading suspendu pour la journée' if pct_used >= 100 else 'Attention au risque'}"
            ),
        )
    
    def alert_cache_error(self, issues: list[str], profile: str) -> dict[str, bool]:
        """Alerte erreur cache."""
        return self.send_alert(
            title=f"⚠ Envolées {profile} — Cache",
            message=f"{len(issues)} problème(s) de données",
            level="warning",
            telegram_message=(
                f"⚠️ *Envolées — alerte cache*\n\n"
                f"Profil: {profile}\n"
                f"Problèmes:\n" + "\n".join(f"  • {i}" for i in issues[:5])
            ),
        )
    
    def alert_shortlist_change(
        self,
        removed: list[str],
        added: list[str],
        profile: str,
    ) -> dict[str, bool]:
        """Alerte changement de shortlist."""
        if not removed and not added:
            return {}
        
        parts = []
        if removed:
            parts.append(f"Retirés: {', '.join(removed)}")
        if added:
            parts.append(f"Ajoutés: {', '.join(added)}")
        
        return self.send_alert(
            title=f"📋 Envolées {profile} — Shortlist",
            message=" | ".join(parts),
            level="info",
            telegram_message=(
                f"📋 *Envolées — shortlist mise à jour*\n\n"
                f"Profil: {profile}\n"
                + (f"➖ Retirés: {', '.join(removed)}\n" if removed else "")
                + (f"➕ Ajoutés: {', '.join(added)}" if added else "")
            ),
        )
    
    def alert_no_execution(self, hours: int, profile: str) -> dict[str, bool]:
        """Alerte aucune exécution depuis N heures."""
        return self.send_alert(
            title=f"⚠ Envolées {profile} — Inactif",
            message=f"Aucune exécution depuis {hours}h",
            level="warning",
            telegram_message=(
                f"⚠️ *Envolées — système inactif*\n\n"
                f"Profil: {profile}\n"
                f"Aucune exécution depuis {hours} heures\n\n"
                f"Vérifier : cache, données, état du système"
            ),
        )


# =============================================================================
# FONCTIONS UTILITAIRES
# =============================================================================

def send_heartbeat_simple(profile: str = "default") -> dict[str, bool]:
    """Envoie un heartbeat simple."""
    sender = AlertSender()
    status = SystemStatus(
        profile=profile,
        cache_ok=True,
        last_execution_ok=True,
        last_execution_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return sender.send_heartbeat(status)


def send_status_simple(
    profile: str,
    shortlist: list[tuple[str, float]],
    daily_consumed: float = 0.0,
    daily_budget: float = 0.015,
) -> dict[str, bool]:
    """Envoie un status simple."""
    sender = AlertSender()
    status = SystemStatus(
        profile=profile,
        shortlist=shortlist,
        tickers_active=len(shortlist),
        daily_consumed=daily_consumed,
        daily_budget=daily_budget,
        cache_ok=True,
        last_execution_ok=True,
        last_execution_time=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    return sender.send_status(status)


def send_backtest_summary(
    profile: str,
    n_tickers: int,
    n_trades: int,
    best_ticker: str,
    best_score: float,
    validated_count: int,
) -> dict[str, bool]:
    """Envoie un résumé de backtest."""
    sender = AlertSender()
    
    return sender.send_alert(
        title=f"🔬 Envolées {profile}",
        message=f"{n_tickers} tickers | {validated_count} validés | best: {best_ticker}",
        level="info",
        telegram_message=(
            f"🔬 *Backtest terminé — {profile}*\n\n"
            f"📊 Résultats:\n"
            f"  • Tickers testés: {n_tickers}\n"
            f"  • Trades totaux: {n_trades}\n"
            f"  • Validés OOS: {validated_count}\n\n"
            f"🏆 Meilleur: {best_ticker} (score {best_score:.3f})"
        ),
    )


def send_error_alert(profile: str, error: str) -> dict[str, bool]:
    """Envoie une alerte d'erreur."""
    sender = AlertSender()
    return sender.send_alert(
        title=f"❌ Envolées {profile} — Erreur",
        message=error[:100],
        level="critical",
        telegram_message=f"❌ *Envolées — erreur*\n\nProfil: {profile}\n\n```\n{error}\n```",
    )


# Alias pour compatibilité CLI
send_heartbeat = send_heartbeat_simple


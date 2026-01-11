"""
Système d'alertes pour Envolées.

Supporte :
- ntfy (notifications push légères)
- Telegram (notifications détaillées)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests


@dataclass
class AlertConfig:
    """Configuration des alertes."""
    
    # ntfy (léger, push)
    ntfy_enabled: bool = False
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    
    # Telegram (détaillé)
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    
    # Profil
    profile: str = "default"  # challenge, funded, etc.
    
    @classmethod
    def from_env(cls) -> AlertConfig:
        """Charge la config depuis l'environnement."""
        ntfy_topic = os.getenv("NTFY_TOPIC", "")
        telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        
        return cls(
            ntfy_enabled=bool(ntfy_topic),
            ntfy_server=os.getenv("NTFY_SERVER", "https://ntfy.sh"),
            ntfy_topic=ntfy_topic,
            telegram_enabled=bool(telegram_token),
            telegram_bot_token=telegram_token,
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            profile=os.getenv("RISK_MODE", "default"),
        )


@dataclass
class TradingStatus:
    """État courant du trading pour les alertes."""
    
    # Identité
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
    shortlist: list[tuple[str, float]] = field(default_factory=list)  # [(ticker, weight), ...]
    
    def format_ntfy(self) -> str:
        """Format court pour ntfy (une ligne)."""
        budget_remaining = self.daily_budget - self.daily_consumed
        
        parts = [
            f"{self.profile.upper()}",
            f"open:{self.open_trades}",
            f"exp:{self.total_exposure_r:.1f}R",
            f"budget:{budget_remaining*100:.1f}%",
        ]
        
        if self.entries > 0 or self.exits_tp > 0 or self.exits_sl > 0:
            parts.append(f"E{self.entries}/TP{self.exits_tp}/SL{self.exits_sl}")
        
        if self.anomalies:
            parts.append(f"⚠{len(self.anomalies)}")
        
        return " │ ".join(parts)
    
    def format_telegram(self) -> str:
        """Format détaillé pour Telegram."""
        lines = [
            f"🚀 *Envolées — {self.profile}*",
            f"📅 {self.timestamp.strftime('%Y-%m-%d %H:%M')}",
            "",
        ]
        
        # Budget
        budget_remaining = self.daily_budget - self.daily_consumed
        lines.append(
            f"💰 Budget jour: {self.daily_budget*100:.1f}% │ "
            f"consommé: {self.daily_consumed*100:.1f}% │ "
            f"restant: {budget_remaining*100:.1f}%"
        )
        
        # Positions
        if self.open_trades > 0:
            lines.append(
                f"📊 Ouverts: {self.open_trades} │ "
                f"exposition: {self.total_exposure_r:.1f}R │ "
                f"max: {self.max_position_r:.1f}R ({self.max_position_ticker})"
            )
        else:
            lines.append("📊 Aucune position ouverte")
        
        # Ordres
        if self.pending_orders > 0:
            lines.append(f"⏳ Ordres en attente: {self.pending_orders}")
        
        # Événements
        events = []
        if self.entries > 0:
            events.append(f"{self.entries} entrée(s)")
        if self.exits_tp > 0:
            events.append(f"{self.exits_tp} TP")
        if self.exits_sl > 0:
            events.append(f"{self.exits_sl} SL")
        if self.cancellations > 0:
            events.append(f"{self.cancellations} annulation(s)")
        
        if events:
            lines.append(f"📝 Événements: {' │ '.join(events)}")
        
        # Anomalies
        if self.anomalies:
            lines.append("")
            lines.append("⚠️ *Alertes:*")
            for a in self.anomalies:
                lines.append(f"  • {a}")
        
        # Performance
        lines.append("")
        lines.append(
            f"📈 PnL jour: {self.pnl_day:+.2f}% │ "
            f"DD jour: {self.dd_day:.2f}% │ "
            f"DD max: {self.dd_max:.2f}%"
        )
        
        # Shortlist
        if self.shortlist:
            lines.append("")
            sl_str = ", ".join(f"{t}({w:.1f})" for t, w in self.shortlist[:5])
            lines.append(f"🎯 Shortlist: {sl_str}")
        
        return "\n".join(lines)


class AlertSender:
    """Envoi d'alertes multi-canal."""
    
    def __init__(self, config: AlertConfig | None = None) -> None:
        self.config = config or AlertConfig.from_env()
    
    def send_ntfy(self, title: str, message: str, priority: int = 3) -> bool:
        """
        Envoie une alerte via ntfy.
        
        Args:
            title: Titre de la notification
            message: Corps du message
            priority: 1-5 (1=min, 3=default, 5=urgent)
        
        Returns:
            True si envoyé avec succès
        """
        if not self.config.ntfy_enabled:
            return False
        
        try:
            url = f"{self.config.ntfy_server}/{self.config.ntfy_topic}"
            response = requests.post(
                url,
                data=message.encode("utf-8"),
                headers={
                    "Title": title,
                    "Priority": str(priority),
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[alert] ntfy error: {e}")
            return False
    
    def send_telegram(self, message: str, parse_mode: str = "Markdown") -> bool:
        """
        Envoie une alerte via Telegram.
        
        Args:
            message: Message (supporte Markdown)
            parse_mode: "Markdown" ou "HTML"
        
        Returns:
            True si envoyé avec succès
        """
        if not self.config.telegram_enabled:
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
            response = requests.post(
                url,
                json={
                    "chat_id": self.config.telegram_chat_id,
                    "text": message,
                    "parse_mode": parse_mode,
                },
                timeout=10,
            )
            return response.status_code == 200
        except Exception as e:
            print(f"[alert] telegram error: {e}")
            return False
    
    def send_status(self, status: TradingStatus) -> dict[str, bool]:
        """
        Envoie un statut sur tous les canaux configurés.
        
        Args:
            status: État du trading
        
        Returns:
            Dict {channel: success}
        """
        results = {}
        
        # ntfy : message court
        if self.config.ntfy_enabled:
            priority = 3
            if status.anomalies:
                priority = 4
            if status.exits_sl > 0:
                priority = 4
            
            results["ntfy"] = self.send_ntfy(
                title=f"Envolées {status.profile}",
                message=status.format_ntfy(),
                priority=priority,
            )
        
        # Telegram : message détaillé
        if self.config.telegram_enabled:
            results["telegram"] = self.send_telegram(status.format_telegram())
        
        return results
    
    def send_alert(
        self,
        title: str,
        message: str,
        priority: int = 3,
        telegram_message: str | None = None,
    ) -> dict[str, bool]:
        """
        Envoie une alerte personnalisée.
        
        Args:
            title: Titre (ntfy)
            message: Message court (ntfy)
            priority: Priorité ntfy
            telegram_message: Message long (telegram), si différent
        
        Returns:
            Dict {channel: success}
        """
        results = {}
        
        if self.config.ntfy_enabled:
            results["ntfy"] = self.send_ntfy(title, message, priority)
        
        if self.config.telegram_enabled:
            results["telegram"] = self.send_telegram(telegram_message or message)
        
        return results


# Fonctions utilitaires

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
    
    title = f"Envolées {profile} - Backtest"
    short = f"{n_tickers} tickers │ {n_trades} trades │ validés: {validated_count} │ best: {best_ticker}({best_score:.2f})"
    
    long = f"""🔬 *Backtest terminé — {profile}*

📊 Résultats:
  • Tickers testés: {n_tickers}
  • Trades totaux: {n_trades}
  • Validés OOS: {validated_count}

🏆 Meilleur: {best_ticker} (score {best_score:.3f})
"""
    
    return sender.send_alert(title, short, telegram_message=long)


def send_error_alert(profile: str, error: str) -> dict[str, bool]:
    """Envoie une alerte d'erreur."""
    sender = AlertSender()
    
    return sender.send_alert(
        title=f"⚠️ Envolées {profile} - Erreur",
        message=error,
        priority=5,
    )

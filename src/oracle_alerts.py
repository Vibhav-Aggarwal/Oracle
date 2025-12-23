#!/usr/bin/env python3
"""
ORACLE BOT ALERTS - Production Alerting System
Real-time notifications for critical events

Features:
- Telegram alerts with severity levels
- Rate limiting to prevent spam
- Alert deduplication
- Escalation for repeated failures
"""

import os
import time
import logging
import requests
from enum import Enum
from typing import Dict, Optional
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

logger = logging.getLogger("OracleAlerts")


class AlertSeverity(Enum):
    """Alert severity levels"""
    INFO = "ℹ️"
    WARNING = "⚠️"
    ERROR = "🔴"
    CRITICAL = "🚨"


@dataclass
class AlertConfig:
    """Alert configuration"""
    telegram_token: str = ""
    telegram_chat_id: str = ""
    rate_limit_seconds: int = 60  # Min time between same alerts
    escalation_threshold: int = 3  # Escalate after N occurrences
    enabled: bool = True


class AlertManager:
    """Production-grade alerting system"""
    
    def __init__(self, config: Optional[AlertConfig] = None):
        self.config = config or AlertConfig(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "")
        )
        self.enabled = bool(self.config.telegram_token and self.config.telegram_chat_id)
        
        # Rate limiting
        self._last_alert_time: Dict[str, float] = {}
        self._alert_counts: Dict[str, int] = defaultdict(int)
        self._suppressed_count: Dict[str, int] = defaultdict(int)
        
        # Alert history
        self._history: list = []
        self._max_history = 100
    
    def _should_send(self, alert_key: str) -> bool:
        """Check rate limiting"""
        now = time.time()
        last_time = self._last_alert_time.get(alert_key, 0)
        
        if now - last_time < self.config.rate_limit_seconds:
            self._suppressed_count[alert_key] += 1
            return False
        
        return True
    
    def _send_telegram(self, message: str) -> bool:
        """Send message via Telegram"""
        if not self.enabled:
            logger.debug(f"Alert (Telegram disabled): {message[:100]}")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendMessage"
            response = requests.post(url, data={
                "chat_id": self.config.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }, timeout=10)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False
    
    def alert(self, 
              severity: AlertSeverity,
              title: str,
              message: str,
              context: Optional[Dict] = None,
              alert_key: Optional[str] = None) -> bool:
        """
        Send an alert with rate limiting and deduplication
        
        Args:
            severity: Alert severity level
            title: Short alert title
            message: Detailed message
            context: Additional context data
            alert_key: Key for deduplication (defaults to title)
        
        Returns:
            True if alert was sent
        """
        key = alert_key or title
        
        # Rate limiting
        if not self._should_send(key):
            return False
        
        # Track occurrence
        self._alert_counts[key] += 1
        count = self._alert_counts[key]
        suppressed = self._suppressed_count.get(key, 0)
        
        # Build message
        emoji = severity.value
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        text = f"{emoji} <b>{title}</b>\n"
        text += f"<code>{timestamp}</code>\n\n"
        text += message
        
        # Add occurrence info if repeated
        if count > 1:
            text += f"\n\n<i>Occurrence #{count}"
            if suppressed > 0:
                text += f" ({suppressed} suppressed)"
            text += "</i>"
        
        # Add context
        if context:
            text += "\n\n<b>Context:</b>\n"
            for k, v in context.items():
                text += f"• {k}: <code>{v}</code>\n"
        
        # Escalate if threshold reached
        if count == self.config.escalation_threshold:
            text = f"🚨 <b>ESCALATION</b> 🚨\n\n" + text
        
        # Send
        success = self._send_telegram(text)
        
        if success:
            self._last_alert_time[key] = time.time()
            self._suppressed_count[key] = 0
            
            # Record history
            self._history.append({
                "time": datetime.now().isoformat(),
                "severity": severity.name,
                "title": title,
                "count": count
            })
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]
        
        return success
    
    # Convenience methods
    def info(self, title: str, message: str, **kwargs):
        return self.alert(AlertSeverity.INFO, title, message, **kwargs)
    
    def warning(self, title: str, message: str, **kwargs):
        return self.alert(AlertSeverity.WARNING, title, message, **kwargs)
    
    def error(self, title: str, message: str, **kwargs):
        return self.alert(AlertSeverity.ERROR, title, message, **kwargs)
    
    def critical(self, title: str, message: str, **kwargs):
        return self.alert(AlertSeverity.CRITICAL, title, message, **kwargs)
    
    # Trading-specific alerts
    def trade_opened(self, symbol: str, direction: str, size: float, price: float):
        emoji = "🟢" if direction == "LONG" else "🔴"
        return self.info(
            f"{emoji} Trade Opened",
            f"<b>{direction}</b> {symbol}\nSize: ${size:.0f} @ ${price:.2f}",
            alert_key=f"trade_open_{symbol}"
        )
    
    def trade_closed(self, symbol: str, direction: str, pnl: float, reason: str):
        emoji = "💰" if pnl >= 0 else "💸"
        return self.info(
            f"{emoji} Trade Closed",
            f"<b>{direction}</b> {symbol}\nP&L: ${pnl:+.2f}\nReason: {reason}",
            alert_key=f"trade_close_{symbol}"
        )
    
    def drawdown_warning(self, current_dd: float, max_dd: float):
        return self.warning(
            "Drawdown Warning",
            f"Current: {current_dd:.1f}%\nMax allowed: {max_dd:.1f}%",
            alert_key="drawdown"
        )
    
    def consecutive_losses(self, count: int, max_allowed: int):
        return self.warning(
            "Consecutive Losses",
            f"Losses in a row: {count}/{max_allowed}\nTrading paused until recovery.",
            alert_key="consecutive_losses"
        )
    
    def api_failure(self, exchange: str, endpoint: str, error: str):
        return self.error(
            f"API Failure: {exchange}",
            f"Endpoint: {endpoint}\nError: {error}",
            alert_key=f"api_{exchange}_{endpoint}"
        )
    
    def bot_started(self, mode: str, balance: float):
        return self.info(
            "🤖 Oracle Bot Started",
            f"Mode: <b>{mode}</b>\nBalance: ${balance:.2f}",
            alert_key="bot_start"
        )
    
    def bot_stopped(self, reason: str):
        return self.critical(
            "🛑 Oracle Bot Stopped",
            f"Reason: {reason}",
            alert_key="bot_stop"
        )
    
    def daily_summary(self, balance: float, pnl: float, trades: int, win_rate: float):
        emoji = "📈" if pnl >= 0 else "📉"
        return self.info(
            f"{emoji} Daily Summary",
            f"Balance: ${balance:.2f}\n"
            f"P&L: ${pnl:+.2f}\n"
            f"Trades: {trades}\n"
            f"Win Rate: {win_rate:.1f}%",
            alert_key="daily_summary"
        )
    
    def get_stats(self) -> dict:
        """Get alerting statistics"""
        return {
            "enabled": self.enabled,
            "total_alerts": len(self._history),
            "alert_counts": dict(self._alert_counts),
            "suppressed": dict(self._suppressed_count),
            "recent": self._history[-10:]
        }


# Global alert manager instance
alerts = AlertManager()


if __name__ == "__main__":
    # Test alerts
    print("Testing alert system...")
    alerts.info("Test Alert", "This is a test message")
    alerts.trade_opened("BTCUSDT", "LONG", 100, 50000)
    alerts.trade_closed("BTCUSDT", "LONG", 25.50, "TAKE_PROFIT")
    alerts.drawdown_warning(8.5, 10.0)
    print(f"Stats: {alerts.get_stats()}")

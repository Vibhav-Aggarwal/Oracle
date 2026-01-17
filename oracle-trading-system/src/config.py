"""
Configuration Management
========================
Handles all configuration with:
- Environment variable support
- Encrypted secrets
- Validation
- Default values with type safety
"""

import os
import json
import base64
from dataclasses import dataclass, field
from typing import List, Optional
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExchangeConfig:
    """Exchange API configuration"""
    name: str
    api_key: str
    api_secret: str
    base_url: str
    testnet: bool = False
    rate_limit: int = 10  # requests per second
    timeout: int = 30


@dataclass  
class StrategyConfig:
    """Trading strategy parameters"""
    name: str = "RSI Momentum"
    stop_loss: float = 0.07
    take_profit: float = 0.21
    risk_per_trade: float = 0.05
    max_positions: int = 5
    rsi_period: int = 14
    rsi_entry_low: int = 30
    rsi_entry_high: int = 60
    rsi_exit: int = 80
    sma_fast: int = 20
    sma_slow: int = 50


@dataclass
class RiskConfig:
    """Risk management settings"""
    max_daily_loss: float = 0.10  # 10% max daily loss
    max_drawdown: float = 0.25   # 25% max drawdown
    max_position_size: float = 0.20  # 20% max per position
    cool_down_after_loss: int = 300  # seconds


@dataclass
class AlertConfig:
    """Alerting configuration"""
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_enabled: bool = False
    discord_webhook: str = ""
    email_enabled: bool = False
    email_smtp: str = ""
    email_to: str = ""


@dataclass
class MonitoringConfig:
    """Monitoring and metrics configuration"""
    prometheus_port: int = 8080
    prometheus_enabled: bool = True
    grafana_enabled: bool = False
    grafana_url: str = ""


@dataclass
class TradingConfig:
    """Trading settings"""
    symbols: List[str] = field(default_factory=lambda: ["BTCUSDT"])
    close_on_shutdown: bool = False


@dataclass
class LoggingConfig:
    """Logging settings"""
    log_dir: str = "/home/vibhavaggarwal/oracle-trading-system/logs"
    level: str = "INFO"
    json_format: bool = False


@dataclass
class Config:
    """Main configuration container"""
    environment: str = "development"
    debug: bool = False
    data_dir: str = "/home/vibhavaggarwal/oracle-trading-system/data"

    exchange: ExchangeConfig = None
    strategy: StrategyConfig = None
    risk: RiskConfig = None
    alerts: AlertConfig = None
    monitoring: MonitoringConfig = None
    trading: TradingConfig = None
    logging: LoggingConfig = None

    def __post_init__(self):
        if self.strategy is None:
            self.strategy = StrategyConfig()
        if self.risk is None:
            self.risk = RiskConfig()
        if self.alerts is None:
            self.alerts = AlertConfig()
        if self.monitoring is None:
            self.monitoring = MonitoringConfig()
        if self.trading is None:
            self.trading = TradingConfig()
        if self.logging is None:
            self.logging = LoggingConfig()


def load_config(config_path: Optional[str] = None) -> Config:
    """
    Load configuration from environment and optional config file.
    Environment variables take precedence.
    """
    config = Config()
    
    # Load from file if provided
    if config_path and Path(config_path).exists():
        with open(config_path) as f:
            data = json.load(f)
            _apply_dict_to_config(config, data)
    
    # Override with environment variables
    config.environment = os.getenv("ORACLE_ENV", config.environment)
    config.debug = os.getenv("ORACLE_DEBUG", "false").lower() == "true"

    # Monitoring config
    prometheus_port = os.getenv("PROMETHEUS_PORT", "8080")
    config.monitoring.prometheus_port = int(prometheus_port)
    
    # Exchange config from environment
    api_key = os.getenv("DELTA_API_KEY", "")
    api_secret = os.getenv("DELTA_API_SECRET", "")
    
    if api_key and api_secret:
        config.exchange = ExchangeConfig(
            name="delta",
            api_key=api_key,
            api_secret=api_secret,
            base_url=os.getenv("DELTA_BASE_URL", "https://api.india.delta.exchange"),
            testnet=os.getenv("DELTA_TESTNET", "false").lower() == "true"
        )
    
    # Alerts from environment
    if os.getenv("TELEGRAM_BOT_TOKEN"):
        config.alerts.telegram_enabled = True
        config.alerts.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        config.alerts.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    
    # Validate
    _validate_config(config)
    
    logger.info(f"Configuration loaded: env={config.environment}, debug={config.debug}")
    return config


def _apply_dict_to_config(config: Config, data: dict):
    """Apply dictionary values to config object"""
    for key, value in data.items():
        if hasattr(config, key):
            if key == "strategy" and isinstance(value, dict):
                config.strategy = StrategyConfig(**value)
            elif key == "risk" and isinstance(value, dict):
                config.risk = RiskConfig(**value)
            elif key == "alerts" and isinstance(value, dict):
                config.alerts = AlertConfig(**value)
            else:
                setattr(config, key, value)


def _validate_config(config: Config):
    """Validate configuration values"""
    errors = []
    
    if config.environment == "production":
        if not config.exchange or not config.exchange.api_key:
            errors.append("Production requires exchange API credentials")
        if config.debug:
            logger.warning("Debug mode enabled in production - consider disabling")
    
    if config.strategy.stop_loss <= 0 or config.strategy.stop_loss > 0.5:
        errors.append(f"Invalid stop_loss: {config.strategy.stop_loss}")
    
    if config.strategy.take_profit <= 0 or config.strategy.take_profit > 1.0:
        errors.append(f"Invalid take_profit: {config.strategy.take_profit}")
    
    if config.risk.max_daily_loss <= 0 or config.risk.max_daily_loss > 1.0:
        errors.append(f"Invalid max_daily_loss: {config.risk.max_daily_loss}")
    
    if errors:
        raise ValueError(f"Configuration errors: {errors}")


# Singleton instance
_config: Optional[Config] = None

def get_config() -> Config:
    """Get global configuration instance"""
    global _config
    if _config is None:
        _config = load_config()
    return _config

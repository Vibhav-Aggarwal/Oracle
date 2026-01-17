"""
Structured Logging System
=========================
Professional logging with:
- JSON structured logs for production
- Console output for development
- Log rotation
- Trade-specific logging
- Performance metrics
"""

import logging
import logging.handlers
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
import traceback


class StructuredFormatter(logging.Formatter):
    """JSON structured log formatter for production"""
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        
        # Add extra fields
        if hasattr(record, "trade_id"):
            log_data["trade_id"] = record.trade_id
        if hasattr(record, "symbol"):
            log_data["symbol"] = record.symbol
        if hasattr(record, "action"):
            log_data["action"] = record.action
        if hasattr(record, "pnl"):
            log_data["pnl"] = record.pnl
        if hasattr(record, "metrics"):
            log_data["metrics"] = record.metrics
            
        # Add exception info
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None
            }
        
        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """Colored console formatter for development"""
    
    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    
    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        
        # Build message
        timestamp = datetime.now().strftime("%H:%M:%S")
        level = f"{color}{record.levelname:8}{self.RESET}"
        
        msg = f"[{timestamp}] {level} | {record.name}: {record.getMessage()}"
        
        # Add trade info if present
        if hasattr(record, "symbol"):
            msg += f" | {record.symbol}"
        if hasattr(record, "action"):
            msg += f" | {record.action}"
        if hasattr(record, "pnl"):
            pnl_color = "\033[32m" if record.pnl >= 0 else "\033[31m"
            msg += f" | PnL: {pnl_color}${record.pnl:+.2f}{self.RESET}"
        
        return msg


class TradeLogger:
    """Specialized logger for trade events"""
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.trade_count = 0
    
    def log_entry(self, symbol: str, side: str, price: float, size: float, 
                  reason: str, trade_id: Optional[str] = None):
        """Log trade entry"""
        self.trade_count += 1
        trade_id = trade_id or f"T{self.trade_count:05d}"
        
        self.logger.info(
            f"ENTRY: {side} {size} {symbol} @ ${price:.2f} - {reason}",
            extra={
                "trade_id": trade_id,
                "symbol": symbol,
                "action": "ENTRY",
                "metrics": {
                    "side": side,
                    "price": price,
                    "size": size,
                    "reason": reason
                }
            }
        )
        return trade_id
    
    def log_exit(self, symbol: str, trade_id: str, exit_price: float, 
                 entry_price: float, pnl: float, reason: str):
        """Log trade exit"""
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        
        self.logger.info(
            f"EXIT: {symbol} @ ${exit_price:.2f} - PnL: ${pnl:+.2f} ({pnl_pct:+.1f}%) - {reason}",
            extra={
                "trade_id": trade_id,
                "symbol": symbol,
                "action": "EXIT",
                "pnl": pnl,
                "metrics": {
                    "exit_price": exit_price,
                    "entry_price": entry_price,
                    "pnl_percent": pnl_pct,
                    "reason": reason
                }
            }
        )
    
    def log_signal(self, symbol: str, signal: str, indicators: Dict[str, Any]):
        """Log trading signal"""
        self.logger.debug(
            f"SIGNAL: {symbol} - {signal}",
            extra={
                "symbol": symbol,
                "action": "SIGNAL",
                "metrics": indicators
            }
        )


def setup_logging(
    log_dir: str = "/home/vibhavaggarwal/oracle-trading-system/logs",
    log_level: str = "INFO",
    json_logs: bool = True,
    console: bool = True
) -> logging.Logger:
    """
    Setup production logging with rotation and structured output.
    
    Args:
        log_dir: Directory for log files
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        json_logs: Use JSON structured logging
        console: Also log to console
    
    Returns:
        Configured root logger
    """
    # Create log directory
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers = []
    
    # File handler with rotation (10MB max, keep 5 files)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path / "oracle.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    
    if json_logs:
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        ))
    
    root_logger.addHandler(file_handler)
    
    # Trade-specific log file
    trade_handler = logging.handlers.RotatingFileHandler(
        log_path / "trades.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8"
    )
    trade_handler.setLevel(logging.INFO)
    trade_handler.setFormatter(StructuredFormatter())
    trade_handler.addFilter(lambda r: hasattr(r, "trade_id") or hasattr(r, "action"))
    root_logger.addHandler(trade_handler)
    
    # Error log file
    error_handler = logging.handlers.RotatingFileHandler(
        log_path / "errors.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(StructuredFormatter())
    root_logger.addHandler(error_handler)
    
    # Console handler for development
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(ConsoleFormatter())
        root_logger.addHandler(console_handler)
    
    # Suppress noisy libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    
    root_logger.info("Logging system initialized", extra={"action": "STARTUP"})
    
    return root_logger


def get_trade_logger(name: str = "oracle.trades") -> TradeLogger:
    """Get specialized trade logger"""
    return TradeLogger(logging.getLogger(name))

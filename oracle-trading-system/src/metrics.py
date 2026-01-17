#!/usr/bin/env python3
"""
Prometheus Metrics - Production Monitoring
Exposes trading metrics for Prometheus scraping
"""

import logging
from typing import Optional
from prometheus_client import (
    Counter, Gauge, Histogram, Summary,
    start_http_server, REGISTRY
)
import threading
import time

logger = logging.getLogger(__name__)


class TradingMetrics:
    """
    Prometheus metrics for Oracle Trading Engine
    
    Metrics exposed:
    - oracle_trades_total: Total trades executed
    - oracle_balance_usdt: Current USDT balance
    - oracle_pnl_daily: Daily realized PnL
    - oracle_positions_open: Number of open positions
    - oracle_drawdown_current: Current drawdown percentage
    - oracle_signal_latency: Signal processing latency
    - oracle_api_requests_total: API request counter
    - oracle_api_errors_total: API error counter
    """
    
    def __init__(self, port: int = 8080):
        self.port = port
        self._server_started = False
        
        # Trade metrics
        self.trades_total = Counter(
            "oracle_trades_total",
            "Total number of trades executed",
            ["symbol", "side", "result"]
        )
        
        self.balance = Gauge(
            "oracle_balance_usdt",
            "Current USDT balance"
        )
        
        self.pnl_daily = Gauge(
            "oracle_pnl_daily",
            "Daily realized profit/loss"
        )
        
        self.pnl_total = Gauge(
            "oracle_pnl_total",
            "Total realized profit/loss"
        )
        
        self.positions_open = Gauge(
            "oracle_positions_open",
            "Number of open positions"
        )
        
        self.drawdown = Gauge(
            "oracle_drawdown_current",
            "Current drawdown percentage"
        )
        
        self.max_drawdown = Gauge(
            "oracle_drawdown_max",
            "Maximum drawdown percentage"
        )
        
        # Performance metrics
        self.win_rate = Gauge(
            "oracle_win_rate",
            "Current win rate percentage"
        )
        
        self.consecutive_losses = Gauge(
            "oracle_consecutive_losses",
            "Current consecutive losing trades"
        )
        
        # Signal metrics
        self.signal_latency = Histogram(
            "oracle_signal_latency_seconds",
            "Signal processing latency",
            buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0]
        )
        
        self.signals_generated = Counter(
            "oracle_signals_total",
            "Total signals generated",
            ["symbol", "signal_type"]
        )
        
        # API metrics
        self.api_requests = Counter(
            "oracle_api_requests_total",
            "Total API requests",
            ["endpoint", "method"]
        )
        
        self.api_errors = Counter(
            "oracle_api_errors_total",
            "Total API errors",
            ["endpoint", "error_type"]
        )
        
        self.api_latency = Histogram(
            "oracle_api_latency_seconds",
            "API request latency",
            ["endpoint"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
        )
        
        # System metrics
        self.uptime = Gauge(
            "oracle_uptime_seconds",
            "Bot uptime in seconds"
        )
        
        self.last_heartbeat = Gauge(
            "oracle_last_heartbeat_timestamp",
            "Timestamp of last successful heartbeat"
        )
        
        self.healthy = Gauge(
            "oracle_healthy",
            "Bot health status (1=healthy, 0=unhealthy)"
        )
        
        logger.info(f"TradingMetrics initialized on port {port}")
    
    def start_server(self) -> None:
        """Start Prometheus HTTP server"""
        if self._server_started:
            return
        try:
            start_http_server(self.port)
            self._server_started = True
            logger.info(f"Prometheus metrics server started on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start metrics server: {e}")
    
    def record_trade(self, symbol: str, side: str, pnl: float) -> None:
        """Record a completed trade"""
        result = "win" if pnl > 0 else "loss"
        self.trades_total.labels(symbol=symbol, side=side, result=result).inc()
        logger.debug(f"Recorded trade: {symbol} {side} {result}")
    
    def record_signal(self, symbol: str, signal_type: str) -> None:
        """Record a generated signal"""
        self.signals_generated.labels(symbol=symbol, signal_type=signal_type).inc()
    
    def record_api_request(self, endpoint: str, method: str, 
                           latency: float, error: Optional[str] = None) -> None:
        """Record an API request"""
        self.api_requests.labels(endpoint=endpoint, method=method).inc()
        self.api_latency.labels(endpoint=endpoint).observe(latency)
        if error:
            self.api_errors.labels(endpoint=endpoint, error_type=error).inc()
    
    def update_balance(self, balance: float) -> None:
        """Update current balance"""
        self.balance.set(balance)
    
    def update_pnl(self, daily: float, total: float) -> None:
        """Update PnL metrics"""
        self.pnl_daily.set(daily)
        self.pnl_total.set(total)
    
    def update_positions(self, count: int) -> None:
        """Update open positions count"""
        self.positions_open.set(count)
    
    def update_drawdown(self, current: float, maximum: float) -> None:
        """Update drawdown metrics"""
        self.drawdown.set(current * 100)
        self.max_drawdown.set(maximum * 100)
    
    def update_performance(self, win_rate: float, consecutive_losses: int) -> None:
        """Update performance metrics"""
        self.win_rate.set(win_rate * 100)
        self.consecutive_losses.set(consecutive_losses)
    
    def update_health(self, healthy: bool, uptime_seconds: float) -> None:
        """Update health metrics"""
        self.healthy.set(1 if healthy else 0)
        self.uptime.set(uptime_seconds)
        self.last_heartbeat.set(time.time())


# Global metrics instance
_metrics: Optional[TradingMetrics] = None


def get_metrics(port: int = 8080) -> TradingMetrics:
    """Get or create global metrics instance"""
    global _metrics
    if _metrics is None:
        _metrics = TradingMetrics(port=port)
    return _metrics


def init_metrics(port: int = 8080) -> TradingMetrics:
    """Initialize and start metrics server"""
    metrics = get_metrics(port)
    metrics.start_server()
    return metrics

#!/usr/bin/env python3
"""
ORACLE BOT METRICS - Production-Grade Performance Tracking
Author: Senior Dev
Date: 2025-12-23

Features:
- Trade performance metrics (win rate, profit factor, expectancy)
- API latency tracking
- Error rate monitoring
- Real-time dashboard stats
"""

import json
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional
from collections import deque
from datetime import datetime, timedelta
import statistics

logger = logging.getLogger("OracleMetrics")

@dataclass
class TradeMetrics:
    """Comprehensive trade performance metrics"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_profit: float = 0.0
    total_loss: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0
    total_fees: float = 0.0
    max_drawdown: float = 0.0
    peak_balance: float = 0.0
    current_drawdown: float = 0.0
    
    # Calculated metrics
    win_rate: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    expectancy: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_hold_time_mins: float = 0.0
    
    # Streaks
    current_streak: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    
    def calculate(self):
        """Recalculate derived metrics"""
        if self.total_trades > 0:
            self.win_rate = (self.winning_trades / self.total_trades) * 100
            
        if self.total_loss != 0:
            self.profit_factor = abs(self.total_profit / self.total_loss) if self.total_loss != 0 else 0
        
        if self.winning_trades > 0:
            self.avg_win = self.total_profit / self.winning_trades
        
        if self.losing_trades > 0:
            self.avg_loss = self.total_loss / self.losing_trades
        
        # Expectancy = (Win% * Avg Win) - (Loss% * Avg Loss)
        if self.total_trades > 0:
            win_pct = self.winning_trades / self.total_trades
            loss_pct = self.losing_trades / self.total_trades
            self.expectancy = (win_pct * self.avg_win) + (loss_pct * self.avg_loss)
    
    def to_dict(self) -> dict:
        self.calculate()
        return asdict(self)


@dataclass 
class APIMetrics:
    """Track API performance"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_latency_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)
    
    # Keep last 100 latencies for percentile calc
    max_latencies: int = 100
    
    def record_call(self, latency_ms: float, success: bool):
        self.total_calls += 1
        if success:
            self.successful_calls += 1
        else:
            self.failed_calls += 1
        
        self.total_latency_ms += latency_ms
        self.latencies.append(latency_ms)
        
        # Keep only last N latencies
        if len(self.latencies) > self.max_latencies:
            self.latencies = self.latencies[-self.max_latencies:]
    
    @property
    def avg_latency(self) -> float:
        if self.total_calls == 0:
            return 0
        return self.total_latency_ms / self.total_calls
    
    @property
    def p95_latency(self) -> float:
        if len(self.latencies) < 5:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[idx]
    
    @property
    def success_rate(self) -> float:
        if self.total_calls == 0:
            return 100.0
        return (self.successful_calls / self.total_calls) * 100
    
    def to_dict(self) -> dict:
        return {
            "total_calls": self.total_calls,
            "success_rate": round(self.success_rate, 2),
            "avg_latency_ms": round(self.avg_latency, 2),
            "p95_latency_ms": round(self.p95_latency, 2),
            "failed_calls": self.failed_calls
        }


class MetricsCollector:
    """Central metrics collection and reporting"""
    
    def __init__(self, state_file: str = "/home/vibhavaggarwal/oracle_metrics.json"):
        self.state_file = state_file
        self.trade_metrics = TradeMetrics()
        self.api_metrics: Dict[str, APIMetrics] = {}
        self.error_counts: Dict[str, int] = {}
        self.hourly_pnl: deque = deque(maxlen=168)  # 7 days of hourly data
        self.start_time = time.time()
        self._load()
    
    def _load(self):
        """Load metrics from disk"""
        try:
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                # Restore trade metrics
                for k, v in data.get('trade_metrics', {}).items():
                    if hasattr(self.trade_metrics, k):
                        setattr(self.trade_metrics, k, v)
                self.error_counts = data.get('error_counts', {})
        except (FileNotFoundError, json.JSONDecodeError):
            pass
    
    def save(self):
        """Persist metrics to disk"""
        try:
            data = {
                'trade_metrics': self.trade_metrics.to_dict(),
                'error_counts': self.error_counts,
                'api_metrics': {k: v.to_dict() for k, v in self.api_metrics.items()},
                'last_updated': datetime.now().isoformat()
            }
            with open(self.state_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Metrics save failed: {e}")
    
    def record_trade(self, net_pnl: float, fees: float, hold_time_mins: int, is_win: bool):
        """Record a completed trade"""
        tm = self.trade_metrics
        tm.total_trades += 1
        tm.net_pnl += net_pnl
        tm.total_fees += fees
        
        if is_win:
            tm.winning_trades += 1
            tm.total_profit += net_pnl
            tm.largest_win = max(tm.largest_win, net_pnl)
            tm.current_streak = max(1, tm.current_streak + 1)
            tm.max_win_streak = max(tm.max_win_streak, tm.current_streak)
        else:
            tm.losing_trades += 1
            tm.total_loss += net_pnl  # Will be negative
            tm.largest_loss = min(tm.largest_loss, net_pnl)
            tm.current_streak = min(-1, tm.current_streak - 1)
            tm.max_loss_streak = max(tm.max_loss_streak, abs(tm.current_streak))
        
        # Update average hold time (rolling average)
        if tm.total_trades == 1:
            tm.avg_hold_time_mins = hold_time_mins
        else:
            tm.avg_hold_time_mins = (tm.avg_hold_time_mins * (tm.total_trades - 1) + hold_time_mins) / tm.total_trades
        
        tm.calculate()
        self.save()
    
    def update_balance(self, balance: float):
        """Update peak balance and drawdown tracking"""
        tm = self.trade_metrics
        if balance > tm.peak_balance:
            tm.peak_balance = balance
        
        if tm.peak_balance > 0:
            tm.current_drawdown = ((tm.peak_balance - balance) / tm.peak_balance) * 100
            tm.max_drawdown = max(tm.max_drawdown, tm.current_drawdown)
    
    def record_api_call(self, exchange: str, latency_ms: float, success: bool):
        """Record API call metrics"""
        if exchange not in self.api_metrics:
            self.api_metrics[exchange] = APIMetrics()
        self.api_metrics[exchange].record_call(latency_ms, success)
    
    def record_error(self, error_type: str):
        """Record error by type"""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
    
    def get_summary(self) -> dict:
        """Get comprehensive metrics summary"""
        tm = self.trade_metrics
        tm.calculate()
        
        uptime_hours = (time.time() - self.start_time) / 3600
        trades_per_day = (tm.total_trades / uptime_hours * 24) if uptime_hours > 0 else 0
        
        return {
            "uptime_hours": round(uptime_hours, 2),
            "trades_per_day": round(trades_per_day, 1),
            "performance": {
                "total_trades": tm.total_trades,
                "win_rate": round(tm.win_rate, 2),
                "profit_factor": round(tm.profit_factor, 2),
                "expectancy": round(tm.expectancy, 2),
                "net_pnl": round(tm.net_pnl, 2),
                "total_fees": round(tm.total_fees, 2),
                "avg_win": round(tm.avg_win, 2),
                "avg_loss": round(tm.avg_loss, 2),
                "largest_win": round(tm.largest_win, 2),
                "largest_loss": round(tm.largest_loss, 2)
            },
            "risk": {
                "max_drawdown_pct": round(tm.max_drawdown, 2),
                "current_drawdown_pct": round(tm.current_drawdown, 2),
                "max_win_streak": tm.max_win_streak,
                "max_loss_streak": tm.max_loss_streak,
                "current_streak": tm.current_streak
            },
            "api_health": {k: v.to_dict() for k, v in self.api_metrics.items()},
            "errors": self.error_counts
        }
    
    def print_summary(self):
        """Pretty print metrics summary"""
        summary = self.get_summary()
        perf = summary['performance']
        risk = summary['risk']
        
        print("\n" + "="*60)
        print("📊 ORACLE BOT METRICS SUMMARY")
        print("="*60)
        print(f"⏱️  Uptime: {summary['uptime_hours']:.1f}h | Trades/day: {summary['trades_per_day']:.1f}")
        print("-"*60)
        print(f"📈 Win Rate: {perf['win_rate']:.1f}% | Profit Factor: {perf['profit_factor']:.2f}")
        print(f"💰 Net P&L: ${perf['net_pnl']:+.2f} | Fees: ${perf['total_fees']:.2f}")
        print(f"📊 Avg Win: ${perf['avg_win']:+.2f} | Avg Loss: ${perf['avg_loss']:.2f}")
        print(f"🎯 Expectancy: ${perf['expectancy']:+.2f} per trade")
        print("-"*60)
        print(f"⚠️  Max Drawdown: {risk['max_drawdown_pct']:.1f}% | Current: {risk['current_drawdown_pct']:.1f}%")
        print(f"🔥 Streaks: Win {risk['max_win_streak']} | Loss {risk['max_loss_streak']} | Current {risk['current_streak']:+d}")
        print("="*60)


# Global metrics collector instance
metrics = MetricsCollector()

if __name__ == "__main__":
    # Test metrics
    metrics.record_trade(50.0, 2.0, 45, True)
    metrics.record_trade(-20.0, 2.0, 30, False)
    metrics.record_trade(75.0, 3.0, 60, True)
    metrics.record_api_call("Delta", 150, True)
    metrics.record_api_call("Delta", 200, True)
    metrics.record_api_call("Delta", 5000, False)
    metrics.print_summary()

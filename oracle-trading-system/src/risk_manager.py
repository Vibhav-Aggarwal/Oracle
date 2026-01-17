"""
Risk Manager - Production Risk Management System
Implements position sizing, drawdown limits, and risk controls
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
import threading

logger = logging.getLogger(__name__)


class RiskAction(Enum):
    """Risk manager action recommendations"""
    ALLOW = "allow"
    REDUCE_SIZE = "reduce_size"
    BLOCK = "block"
    CLOSE_ALL = "close_all"


@dataclass
class RiskMetrics:
    """Current risk metrics snapshot"""
    total_equity: float
    unrealized_pnl: float
    realized_pnl_today: float
    daily_drawdown: float
    max_drawdown: float
    open_positions: int
    daily_trades: int
    win_rate: float
    consecutive_losses: int
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_equity": self.total_equity,
            "unrealized_pnl": self.unrealized_pnl,
            "realized_pnl_today": self.realized_pnl_today,
            "daily_drawdown": f"{self.daily_drawdown*100:.2f}%",
            "max_drawdown": f"{self.max_drawdown*100:.2f}%",
            "open_positions": self.open_positions,
            "daily_trades": self.daily_trades,
            "win_rate": f"{self.win_rate*100:.1f}%",
            "consecutive_losses": self.consecutive_losses
        }


@dataclass
class Position:
    """Track individual position"""
    symbol: str
    side: str
    entry_price: float
    size: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    trade_id: str
    
    @property
    def unrealized_pnl(self) -> float:
        return 0.0  # Calculated externally with current price


class RiskManager:
    """
    Production Risk Management System
    
    Features:
    - Daily drawdown limits
    - Maximum drawdown circuit breaker
    - Position size limits
    - Concurrent position limits
    - Cooldown after consecutive losses
    - Trade frequency limits
    """
    
    def __init__(self, config):
        self.config = config.risk
        self.strategy_config = config.strategy
        
        # State tracking
        self._positions: Dict[str, Position] = {}
        self._daily_pnl: float = 0.0
        self._peak_equity: float = 0.0
        self._current_drawdown: float = 0.0
        self._consecutive_losses: int = 0
        self._trade_history: List[Dict] = []
        self._last_loss_time: Optional[datetime] = None
        self._daily_trade_count: int = 0
        self._last_reset: datetime = datetime.utcnow().date()
        
        # Thread safety
        self._lock = threading.RLock()
        
        logger.info(f"RiskManager initialized: "
                   f"MaxDailyLoss={self.config.max_daily_loss*100:.1f}% "
                   f"MaxDrawdown={self.config.max_drawdown*100:.1f}% "
                   f"MaxPositions={self.config.max_concurrent_trades}")
    
    def _reset_daily_metrics(self) -> None:
        """Reset daily metrics at start of new day"""
        today = datetime.utcnow().date()
        if today > self._last_reset:
            logger.info(f"Resetting daily metrics for {today}")
            self._daily_pnl = 0.0
            self._daily_trade_count = 0
            self._last_reset = today
    
    def update_equity(self, equity: float) -> None:
        """Update equity and recalculate drawdown"""
        with self._lock:
            self._reset_daily_metrics()
            
            if equity > self._peak_equity:
                self._peak_equity = equity
            
            if self._peak_equity > 0:
                self._current_drawdown = (self._peak_equity - equity) / self._peak_equity
            
            logger.debug(f"Equity: {equity:.2f}, Peak: {self._peak_equity:.2f}, "
                        f"Drawdown: {self._current_drawdown*100:.2f}%")
    
    def check_trade_allowed(self, symbol: str, size: float, 
                           side: str) -> tuple[RiskAction, str]:
        """
        Check if a new trade is allowed based on risk parameters
        
        Returns:
            Tuple of (RiskAction, reason_string)
        """
        with self._lock:
            self._reset_daily_metrics()
            
            # Check maximum drawdown
            if self._current_drawdown >= self.config.max_drawdown:
                reason = f"Max drawdown exceeded: {self._current_drawdown*100:.2f}% >= {self.config.max_drawdown*100:.1f}%"
                logger.warning(f"BLOCK: {reason}")
                return (RiskAction.CLOSE_ALL, reason)
            
            # Check daily loss limit
            if self._daily_pnl < 0 and abs(self._daily_pnl / self._peak_equity) >= self.config.max_daily_loss:
                reason = f"Daily loss limit reached: {abs(self._daily_pnl):.2f}"
                logger.warning(f"BLOCK: {reason}")
                return (RiskAction.BLOCK, reason)
            
            # Check cooldown after losses
            if self._last_loss_time and self._consecutive_losses >= 3:
                cooldown_end = self._last_loss_time + timedelta(seconds=self.config.cool_down_after_loss)
                if datetime.utcnow() < cooldown_end:
                    remaining = (cooldown_end - datetime.utcnow()).seconds
                    reason = f"Cooldown active after {self._consecutive_losses} consecutive losses. {remaining}s remaining"
                    logger.info(f"BLOCK: {reason}")
                    return (RiskAction.BLOCK, reason)
            
            # Check concurrent positions limit
            if len(self._positions) >= self.config.max_concurrent_trades:
                reason = f"Max concurrent positions reached: {len(self._positions)}/{self.config.max_concurrent_trades}"
                logger.info(f"BLOCK: {reason}")
                return (RiskAction.BLOCK, reason)
            
            # Check if symbol already has a position
            if symbol in self._positions:
                reason = f"Position already exists for {symbol}"
                logger.info(f"BLOCK: {reason}")
                return (RiskAction.BLOCK, reason)
            
            # Check drawdown warning zone (reduce size)
            if self._current_drawdown >= self.config.max_drawdown * 0.7:
                reason = f"Drawdown in warning zone: {self._current_drawdown*100:.2f}%"
                logger.info(f"REDUCE_SIZE: {reason}")
                return (RiskAction.REDUCE_SIZE, reason)
            
            return (RiskAction.ALLOW, "Trade allowed")
    
    def register_position(self, position: Position) -> None:
        """Register a new position"""
        with self._lock:
            self._positions[position.symbol] = position
            self._daily_trade_count += 1
            logger.info(f"Position registered: {position.symbol} {position.side} "
                       f"@ {position.entry_price:.4f} x {position.size:.6f}")
    
    def close_position(self, symbol: str, exit_price: float, 
                       pnl: float, reason: str) -> None:
        """Record position close and update metrics"""
        with self._lock:
            if symbol not in self._positions:
                logger.warning(f"Attempted to close non-existent position: {symbol}")
                return
            
            position = self._positions.pop(symbol)
            self._daily_pnl += pnl
            
            # Track wins/losses
            if pnl < 0:
                self._consecutive_losses += 1
                self._last_loss_time = datetime.utcnow()
            else:
                self._consecutive_losses = 0
            
            # Store trade history
            self._trade_history.append({
                "symbol": symbol,
                "side": position.side,
                "entry_price": position.entry_price,
                "exit_price": exit_price,
                "size": position.size,
                "pnl": pnl,
                "pnl_percent": (pnl / (position.entry_price * position.size)) * 100,
                "entry_time": position.entry_time.isoformat(),
                "exit_time": datetime.utcnow().isoformat(),
                "reason": reason
            })
            
            # Keep last 100 trades
            if len(self._trade_history) > 100:
                self._trade_history = self._trade_history[-100:]
            
            logger.info(f"Position closed: {symbol} PnL: {pnl:+.2f} "
                       f"({(pnl / (position.entry_price * position.size)) * 100:+.2f}%)")
    
    def get_adjusted_size(self, base_size: float) -> float:
        """Adjust position size based on current risk state"""
        with self._lock:
            # Reduce size if in drawdown warning zone
            if self._current_drawdown >= self.config.max_drawdown * 0.7:
                reduction = 0.5
                logger.info(f"Reducing position size by {(1-reduction)*100:.0f}% due to drawdown")
                return base_size * reduction
            
            # Reduce size after consecutive losses
            if self._consecutive_losses >= 2:
                reduction = max(0.3, 1 - (self._consecutive_losses * 0.15))
                logger.info(f"Reducing position size by {(1-reduction)*100:.0f}% "
                           f"after {self._consecutive_losses} losses")
                return base_size * reduction
            
            return base_size
    
    def get_positions(self) -> Dict[str, Position]:
        """Get current open positions"""
        with self._lock:
            return self._positions.copy()
    
    def get_metrics(self) -> RiskMetrics:
        """Get current risk metrics"""
        with self._lock:
            self._reset_daily_metrics()
            
            # Calculate win rate from history
            if self._trade_history:
                wins = sum(1 for t in self._trade_history if t["pnl"] > 0)
                win_rate = wins / len(self._trade_history)
            else:
                win_rate = 0.0
            
            return RiskMetrics(
                total_equity=self._peak_equity,
                unrealized_pnl=0.0,  # Calculate with current prices
                realized_pnl_today=self._daily_pnl,
                daily_drawdown=abs(self._daily_pnl / self._peak_equity) if self._peak_equity > 0 else 0,
                max_drawdown=self._current_drawdown,
                open_positions=len(self._positions),
                daily_trades=self._daily_trade_count,
                win_rate=win_rate,
                consecutive_losses=self._consecutive_losses
            )
    
    def get_status(self) -> Dict[str, Any]:
        """Get full risk manager status"""
        metrics = self.get_metrics()
        return {
            "metrics": metrics.to_dict(),
            "positions": {
                sym: {
                    "side": pos.side,
                    "entry": pos.entry_price,
                    "size": pos.size,
                    "sl": pos.stop_loss,
                    "tp": pos.take_profit
                }
                for sym, pos in self._positions.items()
            },
            "recent_trades": self._trade_history[-5:],
            "config": {
                "max_daily_loss": f"{self.config.max_daily_loss*100:.1f}%",
                "max_drawdown": f"{self.config.max_drawdown*100:.1f}%",
                "max_positions": self.config.max_concurrent_trades,
                "cooldown_seconds": self.config.cool_down_after_loss
            }
        }

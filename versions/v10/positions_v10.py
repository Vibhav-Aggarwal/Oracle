#!/usr/bin/env python3
"""
V10 Position Management - With Experience Tracking
Created: December 20, 2025

Enhancements over V9:
- Entry context (signals, score, features) stored in Position
- Integration with ExperienceBuffer for self-learning
- Full trade lifecycle captured
"""

import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from datetime import datetime


@dataclass
class Position:
    """Individual position with full context for ML training"""
    symbol: str
    product_id: int
    entry_price: float
    size: int
    original_size: int
    leverage: int
    stop_loss_pct: float
    take_profit_pct: float
    entry_time: float = field(default_factory=time.time)
    
    # Entry Context (NEW for V10)
    entry_score: int = 0
    entry_signals: List[str] = field(default_factory=list)
    entry_features: Dict = field(default_factory=dict)
    market_context: Dict = field(default_factory=dict)
    
    # Tracking
    peak_pnl: float = 0.0
    min_pnl: float = 0.0  # NEW: Track lowest point
    current_pnl: float = 0.0
    last_price: float = 0.0
    
    # Scale-out tracking
    scaled_out_10: bool = False
    scaled_out_15: bool = False
    scale_out_profit: float = 0.0
    
    # State
    is_active: bool = True
    exit_reason: Optional[str] = None
    exit_time: Optional[float] = None
    monitor_thread: Optional[threading.Thread] = None
    
    def calculate_pnl(self, current_price: float) -> float:
        """Calculate current PnL percentage"""
        if self.entry_price <= 0:
            return 0.0
        pnl = ((current_price - self.entry_price) / self.entry_price) * 100 * self.leverage
        self.current_pnl = pnl
        self.last_price = current_price
        return pnl
    
    def update_peak(self, pnl: float):
        """Update peak and min PnL for tracking"""
        if pnl > self.peak_pnl:
            self.peak_pnl = pnl
        if pnl < self.min_pnl:
            self.min_pnl = pnl
    
    def get_trail_stop(self) -> float:
        """Get trailing stop level (Chandelier exit)"""
        if self.peak_pnl > 3.0:
            return self.peak_pnl - 1.5
        return self.stop_loss_pct
    
    def to_experience(self) -> dict:
        """Convert to experience format for ML training"""
        duration = (self.exit_time or time.time()) - self.entry_time
        return {
            'symbol': self.symbol,
            'timestamp': datetime.fromtimestamp(self.entry_time).isoformat(),
            
            # Entry Context
            'entry_price': self.entry_price,
            'entry_score': self.entry_score,
            'entry_signals': self.entry_signals.copy() if self.entry_signals else [],
            'entry_features': self.entry_features.copy() if self.entry_features else {},
            
            # Market Context
            'market_context': self.market_context.copy() if self.market_context else {},
            
            # Trade Outcome
            'exit_price': self.last_price,
            'exit_reason': self.exit_reason or 'UNKNOWN',
            'pnl_pct': self.current_pnl,
            'duration_seconds': duration,
            'peak_pnl': self.peak_pnl,
            'min_pnl': self.min_pnl,
            
            # For ML Training
            'label': 1 if self.current_pnl > 0 else 0,
            'reward': self.current_pnl + self.scale_out_profit
        }
    
    def to_dict(self) -> dict:
        """Serialize for state persistence"""
        return {
            'symbol': self.symbol,
            'product_id': self.product_id,
            'entry_price': self.entry_price,
            'size': self.size,
            'original_size': self.original_size,
            'leverage': self.leverage,
            'stop_loss_pct': self.stop_loss_pct,
            'take_profit_pct': self.take_profit_pct,
            'entry_time': self.entry_time,
            'entry_score': self.entry_score,
            'entry_signals': self.entry_signals,
            'entry_features': self.entry_features,
            'market_context': self.market_context,
            'peak_pnl': self.peak_pnl,
            'min_pnl': self.min_pnl,
            'scaled_out_10': self.scaled_out_10,
            'scaled_out_15': self.scaled_out_15,
            'scale_out_profit': self.scale_out_profit,
            'is_active': self.is_active
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> 'Position':
        """Deserialize from state"""
        pos = cls(
            symbol=data['symbol'],
            product_id=data['product_id'],
            entry_price=data['entry_price'],
            size=data['size'],
            original_size=data.get('original_size', data['size']),
            leverage=data['leverage'],
            stop_loss_pct=data['stop_loss_pct'],
            take_profit_pct=data['take_profit_pct'],
        )
        pos.entry_time = data.get('entry_time', time.time())
        pos.entry_score = data.get('entry_score', 0)
        pos.entry_signals = data.get('entry_signals', [])
        pos.entry_features = data.get('entry_features', {})
        pos.market_context = data.get('market_context', {})
        pos.peak_pnl = data.get('peak_pnl', 0)
        pos.min_pnl = data.get('min_pnl', 0)
        pos.scaled_out_10 = data.get('scaled_out_10', False)
        pos.scaled_out_15 = data.get('scaled_out_15', False)
        pos.scale_out_profit = data.get('scale_out_profit', 0)
        pos.is_active = data.get('is_active', True)
        return pos


class PositionManager:
    """
    Manages up to 3 simultaneous positions.
    Uses position allocation: 40% first, 30% second, 20% third
    """
    MAX_POSITIONS = 3
    
    def __init__(self, api, state, on_close_callback=None, experience_buffer=None):
        self.api = api
        self.state = state
        self.positions: Dict[str, Position] = {}
        self.position_lock = threading.Lock()
        self.on_close_callback = on_close_callback
        self.experience_buffer = experience_buffer
    
    def get_allocation(self) -> float:
        """Get allocation percentage for next position"""
        n = len(self.positions)
        if n == 0: return 0.40
        if n == 1: return 0.30
        if n == 2: return 0.20
        return 0
    
    def has_room(self) -> bool:
        """Check if there's room for any new position"""
        return len(self.positions) < self.MAX_POSITIONS
    
    def can_open_position(self, symbol: str = None) -> bool:
        """Check if we can open a new position for specific symbol"""
        if len(self.positions) >= self.MAX_POSITIONS:
            return False
        if symbol and symbol in self.positions:
            return False
        return True
    
    def open_position(self, symbol: str, product_id: int, entry_price: float,
                      size: int, leverage: int, stop_loss_pct: float,
                      take_profit_pct: float,
                      entry_score: int = 0,
                      entry_signals: List[str] = None,
                      entry_features: Dict = None,
                      market_context: Dict = None):
        """Open new position with full context"""
        with self.position_lock:
            if not self.can_open_position(symbol):
                return None
            
            position = Position(
                symbol=symbol,
                product_id=product_id,
                entry_price=entry_price,
                size=size,
                original_size=size,
                leverage=leverage,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
                entry_score=entry_score,
                entry_signals=entry_signals or [],
                entry_features=entry_features or {},
                market_context=market_context or {}
            )
            
            self.positions[symbol] = position
            
            # Start monitor thread
            monitor = PositionMonitor(
                position=position,
                api=self.api,
                on_close=lambda p, reason: self._handle_close(p, reason)
            )
            position.monitor_thread = monitor
            monitor.start()
            
            # Save state
            self.state.state['positions'][symbol] = position.to_dict()
            self.state.save()
            
            logging.info(f'[POSITION] Opened {symbol} (Score={entry_score})')
            logging.info(f'  Signals: {entry_signals}')
            return position
    
    def _handle_close(self, position: Position, reason: str):
        """Handle position close"""
        position.exit_reason = reason
        position.exit_time = time.time()
        pnl = position.current_pnl + position.scale_out_profit
        
        # Record in experience buffer
        if self.experience_buffer:
            experience = position.to_experience()
            self.experience_buffer.add_experience(experience)
            logging.info(f'[BUFFER] Recorded experience: {position.symbol} -> {pnl:.2f}%')
        
        # Record trade
        self.state.record_trade(position.symbol, pnl, reason)
        
        # Remove from active
        with self.position_lock:
            if position.symbol in self.positions:
                del self.positions[position.symbol]
            if position.symbol in self.state.state['positions']:
                del self.state.state['positions'][position.symbol]
            self.state.save()
        
        logging.info(f'[CLOSE] {position.symbol} {reason} -> {pnl:.2f}%')
        
        # Callback to main bot
        if self.on_close_callback:
            self.on_close_callback(position, reason, pnl)
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position by symbol"""
        return self.positions.get(symbol)
    
    def sync_from_exchange(self, api_positions: List[dict]):
        """Sync with actual API positions"""
        api_symbols = {p.get('product_symbol', p.get('symbol', '')) for p in api_positions}
        
        # Check for positions we don't have locally
        for pos_data in api_positions:
            symbol = pos_data.get('product_symbol', pos_data.get('symbol', ''))
            if symbol and symbol not in self.positions:
                # Create minimal position for tracking
                logging.info(f'[SYNC] Found untracked position: {symbol}')
                try:
                    size = abs(int(pos_data.get('size', 0) or 0))
                    entry_price = float(pos_data.get('entry_price', 0) or 0)
                except (TypeError, ValueError):
                    continue
                if entry_price > 0 and size > 0:
                    product_id = int(pos_data.get('product_id', 0))
                    self.open_position(
                        symbol=symbol,
                        product_id=product_id,
                        entry_price=entry_price,
                        size=size,
                        leverage=LEVERAGE,
                        stop_loss_pct=-5.0,
                        take_profit_pct=15.0
                    )


class PositionMonitor(threading.Thread):
    """
    Dedicated monitoring thread per position.
    Polls at 25ms for fast exit detection.
    """
    
    def __init__(self, position: Position, api, on_close: Callable):
        super().__init__(daemon=True)
        self.position = position
        self.api = api
        self.on_close = on_close
        self.running = True
        self.poll_interval = 0.025  # 25ms
    
    def run(self):
        """Main monitoring loop"""
        while self.running and self.position.is_active:
            try:
                ticker = self.api.get_ticker(self.position.symbol)
                if ticker:
                    mark_price = float(ticker.get('mark_price', 0))
                    if mark_price > 0:
                        pnl = self.position.calculate_pnl(mark_price)
                        self.position.update_peak(pnl)
                        
                        # Log every 3 seconds
                        if int(time.time() * 1000) % 3000 < 50:
                            logging.info(f'[{self.position.symbol}] PnL: {pnl:+.2f}% | Peak: {self.position.peak_pnl:.2f}% | Size: {self.position.size}')
                        
                        # Check exits
                        exit_reason = self._check_exits(pnl)
                        if exit_reason:
                            self._execute_exit(exit_reason)
                            return
                
                time.sleep(self.poll_interval)
            except Exception as e:
                logging.error(f'[MONITOR] {self.position.symbol} error: {e}')
                time.sleep(1)
    
    def _check_exits(self, pnl: float) -> Optional[str]:
        """Check all exit conditions"""
        pos = self.position
        
        # Take profit
        if pnl >= pos.take_profit_pct:
            return 'TAKE_PROFIT'
        
        # Stop loss
        if pnl <= pos.stop_loss_pct:
            return 'STOP_LOSS'
        
        # Trailing stop (Chandelier)
        trail_stop = pos.get_trail_stop()
        if pos.peak_pnl > 3.0 and pnl <= trail_stop:
            return 'TRAIL_STOP'
        
        # Scale-out at +10%
        if pnl >= 10.0 and not pos.scaled_out_10:
            self._scale_out(0.33, 'SCALE_10%')
        
        # Scale-out at +15%
        if pnl >= 15.0 and not pos.scaled_out_15:
            self._scale_out(0.33, 'SCALE_15%')
        
        return None
    
    def _scale_out(self, fraction: float, reason: str):
        """Partial close"""
        pos = self.position
        close_size = max(1, int(pos.size * fraction))
        
        if close_size >= pos.size:
            return
        
        # Execute partial close
        result = self.api.close_position(pos.product_id, size=close_size)
        if result:
            profit_locked = pos.current_pnl * (close_size / pos.original_size)
            pos.scale_out_profit += profit_locked
            pos.size -= close_size
            
            if reason == 'SCALE_10%':
                pos.scaled_out_10 = True
            elif reason == 'SCALE_15%':
                pos.scaled_out_15 = True
            
            logging.info(f'[SCALE] {pos.symbol} {reason}: Closed {close_size}, remaining {pos.size}, locked +{profit_locked:.2f}%')
    
    def _execute_exit(self, reason: str):
        """Execute full exit"""
        pos = self.position
        pos.is_active = False
        pos.exit_reason = reason
        
        result = self.api.close_position(pos.product_id)
        logging.info(f'[EXIT] {pos.symbol} {reason} @ {pos.current_pnl:+.2f}%')
        
        self.on_close(pos, reason)
        self.running = False
    
    def stop(self):
        """Stop monitoring"""
        self.running = False


# Constants for when imported
LEVERAGE = 10

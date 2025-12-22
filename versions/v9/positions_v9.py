#!/usr/bin/env python3
"""
V9 Position Management - Multi-Position with Scale-Out
Created: December 20, 2025

Features:
- Position class for individual position tracking
- PositionManager for up to 3 simultaneous positions
- PositionMonitor thread for 25ms polling per position
- Scale-out at +10% and +15%
- Limit order exits with IOC
"""

import threading
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Callable
from datetime import datetime


@dataclass
class Position:
    """Individual position with all tracking data"""
    symbol: str
    product_id: int
    entry_price: float
    size: int
    original_size: int
    leverage: int
    stop_loss_pct: float  # Negative, e.g., -3.5
    take_profit_pct: float  # Positive, e.g., +15.0
    entry_time: float = field(default_factory=time.time)
    
    # Tracking
    peak_pnl: float = 0.0
    current_pnl: float = 0.0
    last_price: float = 0.0
    
    # Scale-out tracking
    scaled_out_10: bool = False
    scaled_out_15: bool = False
    scale_out_profit: float = 0.0
    
    # State
    is_active: bool = True
    exit_reason: Optional[str] = None
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
        """Update peak PnL for trailing stop"""
        if pnl > self.peak_pnl:
            self.peak_pnl = pnl
    
    def get_trail_stop(self) -> float:
        """Get trailing stop level (Chandelier exit)"""
        if self.peak_pnl > 3.0:
            return self.peak_pnl - 1.5
        return self.stop_loss_pct
    
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
            'peak_pnl': self.peak_pnl,
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
            original_size=data['original_size'],
            leverage=data['leverage'],
            stop_loss_pct=data['stop_loss_pct'],
            take_profit_pct=data['take_profit_pct'],
            entry_time=data.get('entry_time', time.time())
        )
        pos.peak_pnl = data.get('peak_pnl', 0)
        pos.scaled_out_10 = data.get('scaled_out_10', False)
        pos.scaled_out_15 = data.get('scaled_out_15', False)
        pos.scale_out_profit = data.get('scale_out_profit', 0)
        pos.is_active = data.get('is_active', True)
        return pos


class PositionMonitor(threading.Thread):
    """Dedicated thread for monitoring a single position at 25ms intervals"""
    
    def __init__(self, position: Position, api, on_close: Callable, on_scale_out: Callable):
        super().__init__(daemon=True)
        self.position = position
        self.api = api
        self.on_close = on_close
        self.on_scale_out = on_scale_out
        self.running = True
        self.last_log_time = 0
        self.name = f"Monitor-{position.symbol}"
    
    def run(self):
        """Main monitoring loop - 25ms polling"""
        logging.info(f"[MONITOR] {self.position.symbol} STARTED - Entry: ${self.position.entry_price}")
        logging.info(f"[MONITOR] {self.position.symbol} SL: {self.position.stop_loss_pct}% TP: {self.position.take_profit_pct}%")
        
        while self.running and self.position.is_active:
            try:
                ticker = self.api.get_ticker(self.position.symbol)
                if not ticker:
                    time.sleep(0.1)
                    continue
                
                current_price = float(ticker.get('mark_price', 0))
                if current_price <= 0:
                    time.sleep(0.1)
                    continue
                
                pnl = self.position.calculate_pnl(current_price)
                self.position.update_peak(pnl)
                
                # Log every 3 seconds
                now = time.time()
                if now - self.last_log_time >= 3.0:
                    self.last_log_time = now
                    logging.info(f"[{self.position.symbol}] PnL: {pnl:+.2f}% | Peak: {self.position.peak_pnl:.2f}% | Size: {self.position.size}")
                
                # Scale-out at +10%
                if pnl >= 10.0 and not self.position.scaled_out_10 and self.position.size > 1:
                    close_size = max(1, int(self.position.original_size * 0.33))
                    if close_size > 0 and close_size < self.position.size:
                        logging.info(f"[{self.position.symbol}] SCALE-OUT +10%: Closing {close_size}")
                        self.on_scale_out(self.position, close_size, "SCALE_10%", pnl)
                        self.position.scaled_out_10 = True
                        self.position.scale_out_profit += pnl * (close_size / self.position.original_size)
                
                # Scale-out at +15%
                if pnl >= 15.0 and not self.position.scaled_out_15 and self.position.size > 1:
                    close_size = max(1, int(self.position.original_size * 0.33))
                    if close_size > 0 and close_size < self.position.size:
                        logging.info(f"[{self.position.symbol}] SCALE-OUT +15%: Closing {close_size}")
                        self.on_scale_out(self.position, close_size, "SCALE_15%", pnl)
                        self.position.scaled_out_15 = True
                        self.position.scale_out_profit += pnl * (close_size / self.position.original_size)
                
                # Stop Loss
                if pnl <= self.position.stop_loss_pct:
                    logging.warning(f"[{self.position.symbol}] STOP LOSS at {pnl:.2f}%")
                    self.on_close(self.position, "STOP_LOSS", pnl)
                    break
                
                # Take Profit
                if pnl >= self.position.take_profit_pct:
                    logging.info(f"[{self.position.symbol}] TAKE PROFIT at {pnl:.2f}%")
                    self.on_close(self.position, "TAKE_PROFIT", pnl)
                    break
                
                # Trailing Stop
                trail_stop = self.position.get_trail_stop()
                if self.position.peak_pnl > 3.0 and pnl < trail_stop:
                    logging.info(f"[{self.position.symbol}] TRAILING STOP at {pnl:.2f}%")
                    self.on_close(self.position, "TRAIL_STOP", pnl)
                    break
                
                time.sleep(0.025)
                
            except Exception as e:
                logging.error(f"[{self.position.symbol}] Monitor error: {e}")
                time.sleep(0.5)
        
        logging.info(f"[{self.position.symbol}] Monitor stopped")
    
    def stop(self):
        self.running = False


class PositionManager:
    """Manages up to MAX_POSITIONS simultaneous positions"""
    
    MAX_POSITIONS = 3
    ALLOCATIONS = {0: 0.40, 1: 0.30, 2: 0.20}
    
    def __init__(self, api, on_position_closed: Optional[Callable] = None):
        self.api = api
        self.positions: Dict[str, Position] = {}
        self.position_lock = threading.RLock()  # Re-entrant lock to prevent deadlock
        self.on_position_closed = on_position_closed
        self.closed_positions: list = []
    
    def can_open_position(self, symbol: str = None) -> bool:
        with self.position_lock:
            if len(self.positions) >= self.MAX_POSITIONS:
                return False
            if symbol and symbol in self.positions:
                return False
            return True
    
    def get_allocation(self) -> float:
        n = len(self.positions)
        return self.ALLOCATIONS.get(n, 0)
    
    def open_position(self, symbol: str, product_id: int, entry_price: float,
                      size: int, leverage: int, stop_loss_pct: float,
                      take_profit_pct: float) -> Optional[Position]:
        with self.position_lock:
            if not self.can_open_position(symbol):
                return None
            
            position = Position(
                symbol=symbol, product_id=product_id, entry_price=entry_price,
                size=size, original_size=size, leverage=leverage,
                stop_loss_pct=stop_loss_pct, take_profit_pct=take_profit_pct
            )
            
            monitor = PositionMonitor(position, self.api, self._handle_close, self._handle_scale_out)
            position.monitor_thread = monitor
            monitor.start()
            
            self.positions[symbol] = position
            logging.info(f"[POSITION] Opened {symbol} @ \${entry_price:.4f} | Size: {size}")
            logging.info(f"[POSITION] Active: {len(self.positions)}/{self.MAX_POSITIONS}")
            
            return position
    
    def _handle_close(self, position: Position, reason: str, final_pnl: float):
        with self.position_lock:
            position.is_active = False
            position.exit_reason = reason
            
            if position.symbol in self.positions:
                del self.positions[position.symbol]
            
            if position.monitor_thread:
                position.monitor_thread.stop()
            
            self.closed_positions.append({
                'symbol': position.symbol,
                'entry_price': position.entry_price,
                'exit_price': position.last_price,
                'pnl': final_pnl,
                'total_pnl': final_pnl + position.scale_out_profit,
                'reason': reason,
                'closed_at': datetime.now().isoformat()
            })
            
            logging.info(f"[CLOSED] {position.symbol} | PnL: {final_pnl:+.2f}% | {reason}")
            
            if self.on_position_closed:
                self.on_position_closed(position, reason, final_pnl)
    
    def _handle_scale_out(self, position: Position, close_size: int, reason: str, pnl: float):
        try:
            product = self.api.get_product_by_symbol(position.symbol)
            if not product:
                return
            
            tick_size = float(product.get('tick_size', 0.01))
            current_price = position.last_price
            limit_price = round((current_price * 0.998) / tick_size) * tick_size
            
            self.api.place_order(
                product_id=position.product_id,
                size=close_size, side="sell",
                order_type="limit_order",
                limit_price=str(limit_price),
                time_in_force="ioc"
            )
            position.size -= close_size
            logging.info(f"[SCALE-OUT] {position.symbol} closed {close_size} @ \${limit_price:.4f}")
        except Exception as e:
            logging.error(f"Scale-out error: {e}")
    
    def close_all(self, reason: str = "SHUTDOWN"):
        for symbol in list(self.positions.keys()):
            pos = self.positions.get(symbol)
            if pos:
                self._handle_close(pos, reason, pos.current_pnl)
    
    def get_positions_dict(self) -> dict:
        with self.position_lock:
            return {sym: pos.to_dict() for sym, pos in self.positions.items()}
    
    def get_statistics(self) -> dict:
        if not self.closed_positions:
            return {'trades': 0, 'win_rate': 0}
        wins = [p for p in self.closed_positions if p['total_pnl'] > 0]
        return {
            'trades': len(self.closed_positions),
            'wins': len(wins),
            'win_rate': len(wins) / len(self.closed_positions)
        }



    def sync_from_exchange(self, positions_data: list):
        """Sync positions from exchange on startup"""
        logging.info(f"[SYNC] sync_from_exchange called with {len(positions_data)} positions")
        synced = 0
        for p in positions_data:
            if int(p.get("size", 0)) == 0:
                continue
            
            symbol = p.get("product_symbol", "")
            logging.info(f"[SYNC] Processing: {symbol} size={p.get("size")} entry={p.get("entry_price")}")
            if not symbol or symbol in self.positions:
                continue
            
            entry_price = float(p.get("entry_price", 0))
            size = int(p.get("size", 0))
            product_id = int(p.get("product_id", 0))
            
            if entry_price <= 0 or size <= 0:
                continue
            
            position = Position(
                symbol=symbol, product_id=product_id, entry_price=entry_price,
                size=size, original_size=size, leverage=10,
                stop_loss_pct=-5.0, take_profit_pct=15.0
            )
            
            monitor = PositionMonitor(position, self.api, self._handle_close, self._handle_scale_out)
            position.monitor_thread = monitor
            monitor.start()
            
            self.positions[symbol] = position
            synced += 1
            logging.info(f"[SYNC] {symbol} @ ${entry_price:.4f} | Size: {size}")
        
        if synced > 0:
            logging.info(f"[SYNC] Synced {synced} positions from exchange")
        return synced


if __name__ == "__main__":
    print("V9 Position Management Module - OK")

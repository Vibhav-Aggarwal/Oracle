#!/usr/bin/env python3
"""
Oracle Paper Trading v2 - Aggressive Mode with Real Fees
Target: Maximum returns through continuous optimization
"""

import requests
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import os

# === CONFIGURATION ===
INITIAL_BALANCE = 1000.0
MAX_POSITIONS = 5  # More positions for diversification
LEVERAGE = 20
POSITION_SIZE_PCT = 0.30  # 30% per position (aggressive)

# === DELTA EXCHANGE FEES (INDIA) ===
TAKER_FEE = 0.0005  # 0.05%
MAKER_FEE = 0.0002  # 0.02%
GST_RATE = 0.18     # 18% GST on fees
FUNDING_RATE_AVG = 0.0001  # 0.01% per 8 hours (average)

# Effective fees
ENTRY_FEE = TAKER_FEE * (1 + GST_RATE)  # 0.059%
EXIT_FEE = TAKER_FEE * (1 + GST_RATE)   # 0.059%
TOTAL_ROUND_TRIP_FEE = ENTRY_FEE + EXIT_FEE  # ~0.118%

# === API ===
API_URL = "https://api.delta.exchange"
PPO_URL = "http://10.0.0.74:5002"

# === LOGGING ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [PAPER] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler('/home/vibhavaggarwal/paper_v2.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# === STATE ===
STATE_FILE = '/home/vibhavaggarwal/paper_v2_state.json'

class PaperTradingV2:
    def __init__(self):
        self.balance = INITIAL_BALANCE
        self.positions: Dict[str, dict] = {}
        self.trades_history: List[dict] = []
        self.total_fees_paid = 0.0
        self.total_pnl = 0.0
        self.wins = 0
        self.losses = 0
        self.peak_balance = INITIAL_BALANCE
        self.max_drawdown = 0.0
        
        # Performance tracking
        self.hourly_pnl = []
        self.best_symbols = {}  # Track best performing symbols
        
        # Load existing state
        self.load_state()
        
    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                self.balance = state.get('balance', INITIAL_BALANCE)
                self.positions = state.get('positions', {})
                self.trades_history = state.get('trades_history', [])
                self.total_fees_paid = state.get('total_fees_paid', 0.0)
                self.total_pnl = state.get('total_pnl', 0.0)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.peak_balance = state.get('peak_balance', INITIAL_BALANCE)
                self.best_symbols = state.get('best_symbols', {})
                logger.info(f"Loaded state: ${self.balance:.2f}, {len(self.positions)} positions")
            except Exception as e:
                logger.error(f"Failed to load state: {e}")
                
    def save_state(self):
        state = {
            'balance': self.balance,
            'positions': self.positions,
            'trades_history': self.trades_history[-100:],  # Keep last 100
            'total_fees_paid': self.total_fees_paid,
            'total_pnl': self.total_pnl,
            'wins': self.wins,
            'losses': self.losses,
            'peak_balance': self.peak_balance,
            'best_symbols': self.best_symbols,
            'updated': datetime.now().isoformat()
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
            
    def get_ticker(self, symbol: str) -> Optional[dict]:
        try:
            resp = requests.get(f"{API_URL}/v2/tickers/{symbol}", timeout=5)
            if resp.status_code == 200:
                return resp.json().get('result', {})
        except:
            pass
        return None
        
    def get_candles(self, symbol: str, resolution: str = "5m", limit: int = 30) -> List:
        try:
            now = int(time.time())
            res_seconds = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600}.get(resolution, 300)
            start = now - (limit * res_seconds)
            resp = requests.get(
                f"{API_URL}/v2/history/candles",
                params={'resolution': resolution, 'symbol': symbol, 'start': start, 'end': now},
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json().get('result', [])
        except:
            pass
        return []
        
    def get_ppo_recommendation(self, symbol: str) -> Optional[dict]:
        """Get PPO model recommendation"""
        try:
            candles = self.get_candles(symbol, '1h', 25)
            if len(candles) < 20:
                return None
                
            # Format for PPO
            candle_data = [[c['open'], c['high'], c['low'], c['close'], c['volume']] for c in candles[-20:]]
            
            resp = requests.post(
                f"{PPO_URL}/predict/candles",
                json={
                    'candles': candle_data,
                    'balance': self.balance,
                    'position': len(self.positions),
                    'unrealized_pnl': self.get_unrealized_pnl()
                },
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"PPO error for {symbol}: {e}")
        return None
        
    def get_unrealized_pnl(self) -> float:
        """Calculate total unrealized PnL"""
        total = 0.0
        for symbol, pos in self.positions.items():
            ticker = self.get_ticker(symbol)
            if ticker:
                current = float(ticker.get('mark_price', pos['entry_price']))
                pnl = self.calculate_position_pnl(pos, current)
                total += pnl
        return total
        
    def calculate_position_pnl(self, pos: dict, current_price: float) -> float:
        """Calculate PnL for a position including fees"""
        entry = pos['entry_price']
        size = pos['size_usd']
        direction = pos['direction']
        
        if direction == 'LONG':
            pnl_pct = (current_price - entry) / entry
        else:  # SHORT
            pnl_pct = (entry - current_price) / entry
            
        gross_pnl = pnl_pct * size * LEVERAGE
        
        # Subtract entry fee (exit fee added on close)
        net_pnl = gross_pnl - pos.get('entry_fee', 0)
        
        return net_pnl
        
    def should_open_position(self, symbol: str, ppo: dict) -> Tuple[bool, str, float, float, float]:
        """Determine if we should open a position"""
        position_size = ppo.get('position_size', 0)
        sl_pct = ppo.get('stop_loss', 0.05)
        tp_pct = ppo.get('take_profit', 0.10)
        
        # Skip weak signals
        if abs(position_size) < 0.3:
            return False, '', 0, 0, 0
            
        direction = 'LONG' if position_size > 0 else 'SHORT'
        
        # Adjust based on symbol performance history
        if symbol in self.best_symbols:
            perf = self.best_symbols[symbol]
            if perf.get('win_rate', 0) > 0.6:
                position_size = min(abs(position_size) * 1.2, 1.0)  # Boost good symbols
            elif perf.get('win_rate', 0) < 0.3:
                position_size = abs(position_size) * 0.5  # Reduce bad symbols
                
        return True, direction, abs(position_size), sl_pct, tp_pct
        
    def open_position(self, symbol: str, direction: str, size_mult: float, sl_pct: float, tp_pct: float):
        """Open a new position with fees"""
        ticker = self.get_ticker(symbol)
        if not ticker:
            return False
            
        price = float(ticker.get('mark_price', 0))
        if price <= 0:
            return False
            
        # Calculate position size
        available = self.balance * POSITION_SIZE_PCT
        size_usd = available * size_mult
        
        if size_usd < 10:  # Minimum 
            return False
            
        # Calculate fees
        notional = size_usd * LEVERAGE
        entry_fee = notional * ENTRY_FEE
        
        # Deduct fee from balance
        if self.balance < entry_fee:
            return False
            
        self.balance -= entry_fee
        self.total_fees_paid += entry_fee
        
        self.positions[symbol] = {
            'direction': direction,
            'entry_price': price,
            'size_usd': size_usd,
            'stop_loss': sl_pct,
            'take_profit': tp_pct,
            'entry_fee': entry_fee,
            'entry_time': datetime.now().isoformat()
        }
        
        logger.info(f"[OPEN] {direction} {symbol} @ ${price:.2f} | Size: ${size_usd:.2f} | Fee: ${entry_fee:.4f} | SL:{sl_pct*100:.1f}% TP:{tp_pct*100:.1f}%")
        self.save_state()
        return True
        
    def close_position(self, symbol: str, reason: str):
        """Close a position with fees"""
        if symbol not in self.positions:
            return
            
        pos = self.positions[symbol]
        ticker = self.get_ticker(symbol)
        if not ticker:
            return
            
        current_price = float(ticker.get('mark_price', pos['entry_price']))
        
        # Calculate PnL
        gross_pnl = self.calculate_position_pnl(pos, current_price)
        
        # Calculate exit fee
        notional = pos['size_usd'] * LEVERAGE
        exit_fee = notional * EXIT_FEE
        
        # Net PnL after exit fee
        net_pnl = gross_pnl - exit_fee
        
        # Update balance
        self.balance += pos['size_usd'] + net_pnl
        self.total_fees_paid += exit_fee
        self.total_pnl += net_pnl
        
        # Track win/loss
        if net_pnl > 0:
            self.wins += 1
            result = 'WIN'
        else:
            self.losses += 1
            result = 'LOSS'
            
        # Update peak and drawdown
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        current_dd = (self.peak_balance - self.balance) / self.peak_balance
        if current_dd > self.max_drawdown:
            self.max_drawdown = current_dd
            
        # Update symbol performance
        if symbol not in self.best_symbols:
            self.best_symbols[symbol] = {'wins': 0, 'losses': 0, 'total_pnl': 0}
        if net_pnl > 0:
            self.best_symbols[symbol]['wins'] += 1
        else:
            self.best_symbols[symbol]['losses'] += 1
        self.best_symbols[symbol]['total_pnl'] += net_pnl
        total_trades = self.best_symbols[symbol]['wins'] + self.best_symbols[symbol]['losses']
        self.best_symbols[symbol]['win_rate'] = self.best_symbols[symbol]['wins'] / total_trades if total_trades > 0 else 0
        
        # Log trade
        pnl_pct = (net_pnl / pos['size_usd']) * 100
        logger.info(f"[CLOSE] {result} {symbol} | PnL: ${net_pnl:+.2f} ({pnl_pct:+.1f}%) | Fee: ${exit_fee:.4f} | Reason: {reason}")
        
        # Record trade
        self.trades_history.append({
            'symbol': symbol,
            'direction': pos['direction'],
            'entry_price': pos['entry_price'],
            'exit_price': current_price,
            'size_usd': pos['size_usd'],
            'pnl': net_pnl,
            'fees': pos['entry_fee'] + exit_fee,
            'reason': reason,
            'time': datetime.now().isoformat()
        })
        
        del self.positions[symbol]
        self.save_state()
        
    def check_sl_tp(self):
        """Check stop loss and take profit for all positions"""
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            ticker = self.get_ticker(symbol)
            if not ticker:
                continue
                
            current = float(ticker.get('mark_price', 0))
            entry = pos['entry_price']
            direction = pos['direction']
            
            if direction == 'LONG':
                pnl_pct = (current - entry) / entry
            else:
                pnl_pct = (entry - current) / entry
                
            # Check SL/TP
            if pnl_pct <= -pos['stop_loss']:
                self.close_position(symbol, f"SL hit ({pnl_pct*100:.1f}%)")
            elif pnl_pct >= pos['take_profit']:
                self.close_position(symbol, f"TP hit ({pnl_pct*100:.1f}%)")
            # Trailing stop - lock in 50% of profits if up > 3%
            elif pnl_pct > 0.03:
                new_sl = pnl_pct * 0.5  # Move SL to lock 50% profit
                if new_sl > pos['stop_loss']:
                    pos['stop_loss'] = new_sl
                    logger.debug(f"{symbol}: Trailing SL moved to {new_sl*100:.1f}%")
                    
    def get_tradeable_symbols(self) -> List[str]:
        """Get list of symbols to trade"""
        # Focus on high-volume pairs
        symbols = [
            'BTCUSD', 'ETHUSD', 'SOLUSD', 'XRPUSD', 'DOGEUSD',
            'LINKUSD', 'AVAXUSD', 'ADAUSD', 'DOTUSD', 'MATICUSD',
            'LTCUSD', 'BCHUSD', 'ATOMUSD', 'NEARUSD', 'FILUSD',
            'APTUSD', 'ARBUSD', 'OPUSD', 'SUIUSD', 'INJUSD'
        ]
        # Exclude already held
        return [s for s in symbols if s not in self.positions]
        
    def scan_and_trade(self):
        """Main trading logic"""
        # First check existing positions
        self.check_sl_tp()
        
        # If we have max positions, don't look for new ones
        if len(self.positions) >= MAX_POSITIONS:
            return
            
        symbols = self.get_tradeable_symbols()
        
        for symbol in symbols:
            if len(self.positions) >= MAX_POSITIONS:
                break
                
            ppo = self.get_ppo_recommendation(symbol)
            if not ppo:
                continue
                
            should_trade, direction, size_mult, sl_pct, tp_pct = self.should_open_position(symbol, ppo)
            
            if should_trade:
                self.open_position(symbol, direction, size_mult, sl_pct, tp_pct)
                time.sleep(0.5)  # Rate limit
                
    def print_status(self):
        """Print current status"""
        unrealized = self.get_unrealized_pnl()
        total_balance = self.balance + unrealized
        returns = ((total_balance - INITIAL_BALANCE) / INITIAL_BALANCE) * 100
        win_rate = (self.wins / (self.wins + self.losses) * 100) if (self.wins + self.losses) > 0 else 0
        
        logger.info("=" * 60)
        logger.info(f"[STATUS] Balance: ${self.balance:.2f} | Unrealized: ${unrealized:+.2f}")
        logger.info(f"[STATUS] Total: ${total_balance:.2f} | Returns: {returns:+.1f}%")
        logger.info(f"[STATUS] Trades: {self.wins}W/{self.losses}L (WR:{win_rate:.0f}%) | Fees: ${self.total_fees_paid:.2f}")
        logger.info(f"[STATUS] Positions: {list(self.positions.keys())}")
        logger.info(f"[STATUS] Peak: ${self.peak_balance:.2f} | Max DD: {self.max_drawdown*100:.1f}%")
        logger.info("=" * 60)
        
    def run(self):
        """Main loop"""
        logger.info("=" * 60)
        logger.info(f"PAPER TRADING V2 STARTED - ${self.balance:.2f}")
        logger.info(f"Fees: Entry {ENTRY_FEE*100:.3f}% + Exit {EXIT_FEE*100:.3f}% = {TOTAL_ROUND_TRIP_FEE*100:.3f}%")
        logger.info(f"Leverage: {LEVERAGE}x | Max Positions: {MAX_POSITIONS}")
        logger.info("=" * 60)
        
        iteration = 0
        while True:
            try:
                self.scan_and_trade()
                
                iteration += 1
                if iteration % 12 == 0:  # Every minute (5s * 12)
                    self.print_status()
                    
                time.sleep(5)  # Scan every 5 seconds
                
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.print_status()
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(10)
                
if __name__ == '__main__':
    trader = PaperTradingV2()
    trader.run()

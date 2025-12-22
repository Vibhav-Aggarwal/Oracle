#!/usr/bin/env python3
"""
Oracle Unified Trader v3
Switch between PAPER and LIVE with one config change

PAPER MODE: Uses simulated balance, no real trades
LIVE MODE:  Uses Delta Exchange API for real trades
"""

import requests
import json
import time
import hmac
import hashlib
import logging
import os
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# ============================================================
#                    CONFIGURATION
# ============================================================

# === TRADING MODE ===
# Change this to 'LIVE' when ready for real money!
TRADING_MODE = 'PAPER'  # 'PAPER' or 'LIVE'

# === PAPER MODE SETTINGS ===
PAPER_INITIAL_BALANCE = 1000.0

# === LIVE MODE SETTINGS (Delta Exchange) ===
DELTA_API_KEY = os.environ.get('DELTA_API_KEY', '')
DELTA_API_SECRET = os.environ.get('DELTA_API_SECRET', '')

# === COMMON SETTINGS ===
LEVERAGE = 20
MAX_POSITIONS = 5
POSITION_SIZE_PCT = 0.25  # 25% of balance per position

# === DELTA EXCHANGE FEES ===
TAKER_FEE = 0.0005  # 0.05%
MAKER_FEE = 0.0002  # 0.02%
GST_RATE = 0.18     # 18% GST (India)
ENTRY_FEE = TAKER_FEE * (1 + GST_RATE)  # ~0.059%
EXIT_FEE = TAKER_FEE * (1 + GST_RATE)

# === API ENDPOINTS ===
DELTA_API = "https://api.delta.exchange"
PPO_URL = "http://10.0.0.74:5002"

# === FILES ===
STATE_FILE = '/home/vibhavaggarwal/oracle_state.json'
LOG_FILE = '/home/vibhavaggarwal/oracle_trader.log'
CONFIG_FILE = '/home/vibhavaggarwal/optimizer_config.json'

# ============================================================
#                    LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ORACLE] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# ============================================================
#                    DELTA API CLIENT
# ============================================================

class DeltaAPI:
    """Delta Exchange API client for LIVE trading"""
    
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()
        self.products = {}
        
    def _sign(self, method: str, path: str, payload: str = '') -> Dict:
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + path + payload
        signature = hmac.new(
            self.api_secret.encode('utf-8'),
            signature_data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return {
            'api-key': self.api_key,
            'timestamp': timestamp,
            'signature': signature,
            'Content-Type': 'application/json'
        }
        
    def get(self, path: str, auth: bool = True) -> Optional[dict]:
        try:
            headers = self._sign('GET', path) if auth else {}
            resp = self.session.get(DELTA_API + path, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('result')
        except Exception as e:
            logger.error(f"API GET error: {e}")
        return None
        
    def post(self, path: str, data: dict) -> Optional[dict]:
        try:
            payload = json.dumps(data)
            headers = self._sign('POST', path, payload)
            resp = self.session.post(DELTA_API + path, headers=headers, data=payload, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('result')
            else:
                logger.error(f"API POST error: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"API POST exception: {e}")
        return None
        
    def get_wallet(self) -> Optional[dict]:
        return self.get('/v2/wallet/balances')
        
    def get_positions(self) -> Optional[list]:
        return self.get('/v2/positions')
        
    def place_order(self, product_id: int, size: int, side: str, 
                    order_type: str = 'market_order') -> Optional[dict]:
        data = {
            'product_id': product_id,
            'size': size,
            'side': side,
            'order_type': order_type
        }
        return self.post('/v2/orders', data)
        
    def close_position(self, product_id: int) -> Optional[dict]:
        data = {'product_id': product_id, 'close_all_on_reconnect': True}
        return self.post('/v2/positions/close_all', data)

# ============================================================
#                    ORACLE TRADER
# ============================================================

class OracleTrader:
    def __init__(self):
        self.mode = TRADING_MODE
        self.delta_api = None
        
        if self.mode == 'LIVE':
            if not DELTA_API_KEY or not DELTA_API_SECRET:
                raise ValueError("LIVE mode requires DELTA_API_KEY and DELTA_API_SECRET")
            self.delta_api = DeltaAPI(DELTA_API_KEY, DELTA_API_SECRET)
            logger.info("=== LIVE TRADING MODE ===")
        else:
            logger.info("=== PAPER TRADING MODE ===")
            
        # State
        self.balance = PAPER_INITIAL_BALANCE
        self.positions: Dict[str, dict] = {}
        self.trades_history: List[dict] = []
        self.total_pnl = 0.0
        self.total_fees = 0.0
        self.wins = 0
        self.losses = 0
        self.peak_balance = PAPER_INITIAL_BALANCE
        
        # Load optimizer config
        self.config = self.load_optimizer_config()
        
        # Load state
        self.load_state()
        
    def load_optimizer_config(self) -> Dict:
        default = {
            'position_size_pct': POSITION_SIZE_PCT,
            'max_positions': MAX_POSITIONS,
            'min_signal_strength': 0.3,
            'symbols_blacklist': [],
            'symbols_boost': []
        }
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    saved = json.load(f)
                    default.update(saved)
            except:
                pass
        return default
        
    def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
                    
                # Only load paper state in paper mode
                if self.mode == 'PAPER':
                    self.balance = state.get('balance', PAPER_INITIAL_BALANCE)
                    self.positions = state.get('positions', {})
                    
                self.trades_history = state.get('trades_history', [])[-100:]
                self.total_pnl = state.get('total_pnl', 0)
                self.total_fees = state.get('total_fees', 0)
                self.wins = state.get('wins', 0)
                self.losses = state.get('losses', 0)
                self.peak_balance = state.get('peak_balance', PAPER_INITIAL_BALANCE)
                
                logger.info(f"Loaded state: ${self.balance:.2f}, {len(self.positions)} positions")
            except Exception as e:
                logger.error(f"Load state error: {e}")
                
    def save_state(self):
        state = {
            'mode': self.mode,
            'balance': self.balance,
            'positions': self.positions,
            'trades_history': self.trades_history[-100:],
            'total_pnl': self.total_pnl,
            'total_fees': self.total_fees,
            'wins': self.wins,
            'losses': self.losses,
            'peak_balance': self.peak_balance,
            'updated': datetime.now().isoformat()
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
            
    def get_balance(self) -> float:
        if self.mode == 'LIVE':
            wallet = self.delta_api.get_wallet()
            if wallet:
                for asset in wallet:
                    if asset.get('asset_symbol') == 'USDT':
                        return float(asset.get('available_balance', 0))
            return 0
        return self.balance
        
    def get_ticker(self, symbol: str) -> Optional[dict]:
        try:
            resp = requests.get(f"{DELTA_API}/v2/tickers/{symbol}", timeout=5)
            if resp.status_code == 200:
                return resp.json().get('result')
        except:
            pass
        return None
        
    def get_candles(self, symbol: str, resolution: str = '5m', limit: int = 30) -> List:
        try:
            now = int(time.time())
            res_sec = {'1m': 60, '5m': 300, '15m': 900, '1h': 3600}.get(resolution, 300)
            start = now - (limit * res_sec)
            resp = requests.get(
                f"{DELTA_API}/v2/history/candles",
                params={'resolution': resolution, 'symbol': symbol, 'start': start, 'end': now},
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json().get('result', [])
        except:
            pass
        return []
        
    def get_ppo_signal(self, symbol: str) -> Optional[dict]:
        try:
            candles = self.get_candles(symbol, '1h', 25)
            if len(candles) < 20:
                return None
                
            candle_data = [[c['open'], c['high'], c['low'], c['close'], c['volume']] 
                          for c in candles[-20:]]
            
            resp = requests.post(
                f"{PPO_URL}/predict/candles",
                json={
                    'candles': candle_data,
                    'balance': self.get_balance(),
                    'position': len(self.positions),
                    'unrealized_pnl': 0
                },
                timeout=10
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.debug(f"PPO error {symbol}: {e}")
        return None
        
    def open_position_paper(self, symbol: str, direction: str, size_usd: float, 
                           price: float, sl_pct: float, tp_pct: float) -> bool:
        """Open position in paper mode"""
        notional = size_usd * LEVERAGE
        entry_fee = notional * ENTRY_FEE
        
        if self.balance < entry_fee + size_usd:
            return False
            
        self.balance -= entry_fee
        self.total_fees += entry_fee
        
        self.positions[symbol] = {
            'direction': direction,
            'entry_price': price,
            'size_usd': size_usd,
            'stop_loss': sl_pct,
            'take_profit': tp_pct,
            'entry_fee': entry_fee,
            'entry_time': datetime.now().isoformat()
        }
        
        logger.info(f"[OPEN] {direction} {symbol} @ ${price:.2f} | ${size_usd:.2f} | SL:{sl_pct*100:.1f}% TP:{tp_pct*100:.1f}%")
        self.save_state()
        return True
        
    def open_position_live(self, symbol: str, direction: str, size_usd: float,
                          sl_pct: float, tp_pct: float) -> bool:
        """Open position in live mode"""
        # TODO: Implement live order placement
        # This will use self.delta_api.place_order()
        logger.warning(f"[LIVE] Would open {direction} {symbol} ${size_usd:.2f}")
        return False
        
    def open_position(self, symbol: str, direction: str, size_mult: float,
                     sl_pct: float, tp_pct: float) -> bool:
        ticker = self.get_ticker(symbol)
        if not ticker:
            return False
            
        price = float(ticker.get('mark_price', 0))
        if price <= 0:
            return False
            
        balance = self.get_balance()
        size_usd = balance * self.config['position_size_pct'] * size_mult
        
        if size_usd < 10:
            return False
            
        if self.mode == 'PAPER':
            return self.open_position_paper(symbol, direction, size_usd, price, sl_pct, tp_pct)
        else:
            return self.open_position_live(symbol, direction, size_usd, sl_pct, tp_pct)
            
    def close_position_paper(self, symbol: str, reason: str):
        """Close position in paper mode"""
        if symbol not in self.positions:
            return
            
        pos = self.positions[symbol]
        ticker = self.get_ticker(symbol)
        if not ticker:
            return
            
        current = float(ticker.get('mark_price', pos['entry_price']))
        entry = pos['entry_price']
        size = pos['size_usd']
        direction = pos['direction']
        
        # Calculate PnL
        if direction == 'LONG':
            pnl_pct = (current - entry) / entry
        else:
            pnl_pct = (entry - current) / entry
            
        gross_pnl = pnl_pct * size * LEVERAGE
        
        # Exit fee
        notional = size * LEVERAGE
        exit_fee = notional * EXIT_FEE
        
        net_pnl = gross_pnl - exit_fee - pos.get('entry_fee', 0)
        
        # Update state
        self.balance += size + net_pnl
        self.total_fees += exit_fee
        self.total_pnl += net_pnl
        
        if net_pnl > 0:
            self.wins += 1
            result = 'WIN'
        else:
            self.losses += 1
            result = 'LOSS'
            
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
            
        logger.info(f"[CLOSE] {result} {symbol} | PnL: ${net_pnl:+.2f} ({pnl_pct*100:+.1f}%) | {reason}")
        
        # Record trade
        self.trades_history.append({
            'symbol': symbol,
            'direction': direction,
            'entry': entry,
            'exit': current,
            'size': size,
            'pnl': net_pnl,
            'reason': reason,
            'time': datetime.now().isoformat()
        })
        
        del self.positions[symbol]
        self.save_state()
        
    def close_position(self, symbol: str, reason: str):
        if self.mode == 'PAPER':
            self.close_position_paper(symbol, reason)
        else:
            # TODO: Live close
            logger.warning(f"[LIVE] Would close {symbol}")
            
    def check_positions(self):
        """Check SL/TP for all positions"""
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
                
            if pnl_pct <= -pos['stop_loss']:
                self.close_position(symbol, f"SL ({pnl_pct*100:.1f}%)")
            elif pnl_pct >= pos['take_profit']:
                self.close_position(symbol, f"TP ({pnl_pct*100:.1f}%)")
            # Trailing stop
            elif pnl_pct > 0.03:
                new_sl = pnl_pct * 0.5
                if new_sl > pos['stop_loss']:
                    pos['stop_loss'] = new_sl
                    
    def get_symbols(self) -> List[str]:
        # BTCUSD and ETHUSD use USD format, others use USDT
        symbols = [
            'BTCUSD', 'ETHUSD',  # USD format
            'SOLUSDT', 'XRPUSDT', 'DOGEUSDT', 'LINKUSDT', 'AVAXUSDT',
            'ADAUSDT', 'MATICUSDT', 'LTCUSDT', 'ATOMUSDT', 'NEARUSDT',
            'ARBUSDT', 'OPUSDT', 'SUIUSDT'
        ]
        # Filter blacklist
        blacklist = self.config.get('symbols_blacklist', [])
        return [s for s in symbols if s not in self.positions and s not in blacklist]
        
    def scan_and_trade(self):
        self.check_positions()
        
        # Reload optimizer config
        self.config = self.load_optimizer_config()
        
        max_pos = self.config.get('max_positions', MAX_POSITIONS)
        if len(self.positions) >= max_pos:
            return
            
        min_signal = self.config.get('min_signal_strength', 0.3)
        
        for symbol in self.get_symbols():
            if len(self.positions) >= max_pos:
                break
                
            ppo = self.get_ppo_signal(symbol)
            if not ppo:
                continue
                
            pos_size = ppo.get('position_size', 0)
            
            if abs(pos_size) < min_signal:
                continue
                
            direction = 'LONG' if pos_size > 0 else 'SHORT'
            sl = ppo.get('stop_loss', 0.05)
            tp = ppo.get('take_profit', 0.10)
            
            # Boost for good symbols
            boost_symbols = self.config.get('symbols_boost', [])
            if symbol in boost_symbols:
                pos_size = min(abs(pos_size) * 1.2, 1.0)
                
            self.open_position(symbol, direction, abs(pos_size), sl, tp)
            time.sleep(0.5)
            
    def print_status(self):
        balance = self.get_balance()
        returns = ((balance - PAPER_INITIAL_BALANCE) / PAPER_INITIAL_BALANCE) * 100
        wr = self.wins / max(self.wins + self.losses, 1) * 100
        
        logger.info("=" * 60)
        logger.info(f"[{self.mode}] Balance: ${balance:.2f} | Returns: {returns:+.1f}%")
        logger.info(f"[{self.mode}] W/L: {self.wins}/{self.losses} ({wr:.0f}%) | Fees: ${self.total_fees:.2f}")
        logger.info(f"[{self.mode}] Positions: {list(self.positions.keys())}")
        logger.info("=" * 60)
        
    def run(self):
        logger.info("=" * 60)
        logger.info(f"ORACLE TRADER STARTED - {self.mode} MODE")
        logger.info(f"Balance: ${self.get_balance():.2f}")
        logger.info(f"Fees: Entry {ENTRY_FEE*100:.3f}% + Exit {EXIT_FEE*100:.3f}%")
        logger.info("=" * 60)
        
        iteration = 0
        while True:
            try:
                iteration += 1
                
                # Verbose: Show position P&L each iteration
                if self.positions:
                    for sym, pos in list(self.positions.items())[:2]:
                        ticker = self.get_ticker(sym)
                        if ticker:
                            curr = float(ticker.get("mark_price", pos["entry_price"]))
                            entry = pos["entry_price"]
                            d = pos["direction"]
                            pnl_pct = (curr - entry) / entry if d == "LONG" else (entry - curr) / entry
                            pnl_usd = pnl_pct * pos["size_usd"] * LEVERAGE
                            logger.info(f"[{iteration}] {sym} {d}: {pnl_pct*100:+.2f}% = ${pnl_usd:+.2f} | SL:{pos["stop_loss"]*100:.1f}% TP:{pos["take_profit"]*100:.1f}%")
                
                self.scan_and_trade()
                
                if iteration % 12 == 0:
                    self.print_status()
                    
                time.sleep(5)
                
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                self.print_status()
                break
            except Exception as e:
                logger.error(f"Error in iteration {iteration}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                time.sleep(10)

if __name__ == '__main__':
    trader = OracleTrader()
    trader.run()

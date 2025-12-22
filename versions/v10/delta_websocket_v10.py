#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V10 - Self-Learning Oracle Edition
Created: December 20, 2025

Features:
- Up to 3 simultaneous positions (PositionManager)
- Dedicated monitor thread per position (25ms polling)
- Scale-out at +10% and +15%
- Fear & Greed Index integration
- Enhanced order flow (delta divergence, absorption, whale detection)
- State persistence across restarts
- Limit order exits with IOC
"""

import json
import time
import hmac
import hashlib
import logging
import threading
import requests
import websocket
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

# Import V9 modules
from positions_v10 import Position, PositionManager, PositionMonitor
from experience_buffer import ExperienceBuffer
from sentiment_v9 import get_fear_greed, get_sentiment_adjustment
from indicators_v9 import (
    calculate_rsi, calculate_macd, calculate_atr, calculate_vwap,
    calculate_bollinger_bands, detect_rsi_divergence, detect_bb_squeeze,
    calculate_orderbook_imbalance, detect_delta_divergence,
    detect_absorption, detect_whale_trades, calculate_v9_indicators, estimate_delta_from_candles
)
from ml_predictor import get_ml_prediction
from social_sentiment import get_social_adjustment
from finbert_client import get_finbert_adjustment
from ppo_client import get_ppo_recommendation
from telegram_alerts import get_bot as get_telegram_bot
from self_learning import auto_train as run_auto_training

# ============================================
# CONFIGURATION
# ============================================

API_KEY = "KMLkcDcajSQWPmVcgNuAd3KWqf7OzM"
API_SECRET = "ltJaGy3GErRluET1e7FaYOklFx1u7pGwCsiCqCO774ndLdPzcnZzmHYscT5W"
BASE_URL = "https://api.india.delta.exchange"
WS_URL = "wss://socket.india.delta.exchange"

# WARP Proxy
WARP_PROXY = "socks5h://127.0.0.1:40000"

# Trading parameters
LEVERAGE = 20  # Higher leverage for small account
MIN_SCORE = 40  # Base threshold
MAX_POSITIONS = 1  # Single position for small account
MIN_TURNOVER_USD = 10_000  # Lowered for small account  # $1M minimum volume
MAX_VOLATILITY = 20.0
COOLDOWN_SECONDS = 30
BLACKLIST_SECONDS = 180
MAX_CONSECUTIVE_LOSSES = 3
MAX_DAILY_DRAWDOWN = 0.10

# Logging
LOG_FILE = "/home/vibhavaggarwal/delta_websocket_v10.log"
STATE_FILE = "/home/vibhavaggarwal/bot_state_v10.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)


# ============================================
# STATE PERSISTENCE
# ============================================

class StatePersistence:
    def __init__(self, filepath: str = STATE_FILE):
        self.filepath = filepath
        self.state = self.load()
    
    def load(self) -> dict:
        if Path(self.filepath).exists():
            try:
                with open(self.filepath, 'r') as f:
                    return json.load(f)
            except:
                pass
        return {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_win_pct': 0,
            'total_loss_pct': 0,
            'peak_equity': 0,
            'positions': {},
            'last_update': None
        }
    
    def save(self):
        self.state['last_update'] = datetime.now().isoformat()
        with open(self.filepath, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def record_trade(self, symbol: str, pnl: float, reason: str):
        trade = {
            'symbol': symbol,
            'pnl': pnl,
            'reason': reason,
            'timestamp': datetime.now().isoformat()
        }
        self.state['trades'].append(trade)
        if pnl > 0:
            self.state['wins'] += 1
            self.state['total_win_pct'] += pnl
        else:
            self.state['losses'] += 1
            self.state['total_loss_pct'] += pnl
        self.save()
    
    def get_win_rate(self) -> float:
        total = self.state['wins'] + self.state['losses']
        return self.state['wins'] / total if total > 0 else 0.5


# ============================================
# DELTA API
# ============================================

class DeltaAPI:
    def __init__(self):
        self.session = requests.Session()
        self.session.proxies = {"https": WARP_PROXY, "http": WARP_PROXY}
        self.products = {}
        self.products_by_symbol = {}
    
    def _sign(self, method: str, path: str, payload: str = "") -> dict:
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + path + payload
        signature = hmac.new(
            API_SECRET.encode('utf-8'),
            signature_data.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return {
            "api-key": API_KEY,
            "signature": signature,
            "timestamp": timestamp,
            "Content-Type": "application/json"
        }
    
    def get(self, path: str) -> Optional[dict]:
        try:
            headers = self._sign("GET", path)
            response = self.session.get(BASE_URL + path, headers=headers, timeout=10)
            if 'candles' in path and 'BTCUSD' in path:
                logging.info(f"[API] Candles response: status={response.status_code}")
            if response.status_code == 200:
                result = response.json().get('result')
                if 'candles' in path and 'BTCUSD' in path:
                    logging.info(f"[API] BTCUSD candles result: {len(result) if result else 'None'}")
                return result
        except Exception as e:
            logging.info(f"API GET error: {path} - {e}")
        return None
    
    def post(self, path: str, data: dict) -> Optional[dict]:
        try:
            payload = json.dumps(data)
            headers = self._sign("POST", path, payload)
            response = self.session.post(BASE_URL + path, headers=headers, data=payload, timeout=10)
            if response.status_code == 200:
                return response.json().get('result')
            else:
                logging.error(f"API POST error: {response.status_code} - {response.text}")
        except Exception as e:
            logging.error(f"API POST exception: {e}")
        return None
    
    def load_products(self):
        products = self.get("/v2/products")
        if products:
            for p in products:
                if p.get('contract_type') == 'perpetual_futures':
                    symbol = p.get('symbol', '')
                    self.products[p['id']] = p
                    self.products_by_symbol[symbol] = p
            logging.info(f"Loaded {len(self.products_by_symbol)} perpetual futures")
    
    def get_product_by_symbol(self, symbol: str) -> Optional[dict]:
        return self.products_by_symbol.get(symbol)
    
    def get_ticker(self, symbol: str) -> Optional[dict]:
        product = self.products_by_symbol.get(symbol)
        if not product:
            return None
        return self.get(f"/v2/tickers/{product['id']}")
    
    def get_candles(self, symbol: str, resolution: str = "5m", limit: int = 50) -> List[dict]:
        product = self.products_by_symbol.get(symbol)
        if not product:
            return []
        
        # Calculate time range
        resolution_seconds = 300  # 5m default
        if resolution == "1m":
            resolution_seconds = 60
        elif resolution == "15m":
            resolution_seconds = 900
        elif resolution == "1h":
            resolution_seconds = 3600
        
        end_time = int(time.time())
        start_time = end_time - (limit * resolution_seconds)
        
        # Candles is a PUBLIC endpoint - no auth needed
        try:
            url = f"{BASE_URL}/v2/history/candles?resolution={resolution}&symbol={symbol}&start={start_time}&end={end_time}"
            response = self.session.get(url, timeout=10)  # No auth headers
            if response.status_code == 200:
                result = response.json().get('result', [])
                if symbol in ['BTCUSD', 'ETHUSD']:
                    logging.info(f"[CANDLES] {symbol}: Got {len(result)} candles")
                return result
        except Exception as e:
            logging.debug(f"Candles API error: {e}")
        return []
    
    def get_orderbook(self, symbol: str) -> Optional[dict]:
        product = self.products_by_symbol.get(symbol)
        if not product:
            return None
        return self.get(f"/v2/l2orderbook/{product['id']}")
    
    def get_wallet(self) -> Optional[dict]:
        wallets = self.get("/v2/wallet/balances")
        if wallets:
            for w in wallets:
                if w.get('asset_symbol') == 'USD':
                    return w
        return None
    
    def get_positions(self) -> Optional[list]:
        """Get all open positions"""
        result = self.get("/v2/positions/margined")
        if result:
            return [p for p in result if int(p.get("size", 0)) != 0]
        return None

    def place_order(self, product_id: int, size: int, side: str, 
                    order_type: str = "market_order", limit_price: str = None,
                    time_in_force: str = "gtc") -> Optional[dict]:
        data = {
            "product_id": product_id,
            "size": size,
            "side": side,
            "order_type": order_type
        }
        if limit_price:
            data["limit_price"] = limit_price
        if time_in_force:
            data["time_in_force"] = time_in_force
        return self.post("/v2/orders", data)
    
    def close_position(self, product_id: int, size: int = None) -> Optional[dict]:
        """Close position fully or partially"""
        if size:
            # Partial close via market sell order
            return self.post("/v2/orders", {
                "product_id": product_id,
                "size": size,
                "side": "sell",
                "order_type": "market_order",
                "reduce_only": True
            })
        else:
            # Full close
            return self.post("/v2/positions/close", {"product_id": product_id})
    
    def get_recent_trades(self, symbol: str, limit: int = 100) -> List[dict]:
        """Get recent trades for whale detection"""
        product = self.products_by_symbol.get(symbol)
        if not product:
            return []
        try:
            result = self.get(f"/v2/trades/{product['id']}?limit={limit}")
            return result if result else []
        except:
            return []




# ============================================
# TICKER CACHE (Background Thread)
# ============================================

class TickerCache:
    """
    Background thread that caches ticker data for fast access.
    Updated by WebSocket + periodic refresh for critical symbols.
    """
    
    def __init__(self, api, max_age_ms: float = 500):
        self.api = api
        self.max_age_ms = max_age_ms
        self.cache = {}
        self.lock = threading.Lock()
        self.refresh_thread = None
        self.running = False
        self.top_symbols = []
    
    def start(self, symbols):
        self.top_symbols = symbols[:30]
        self.running = True
        self.refresh_thread = threading.Thread(target=self._refresh_loop, daemon=True)
        self.refresh_thread.start()
        logging.info(f"[CACHE] Started ticker cache for {len(self.top_symbols)} symbols")
    
    def stop(self):
        self.running = False
        if self.refresh_thread:
            self.refresh_thread.join(timeout=2)
    
    def _refresh_loop(self):
        while self.running:
            for symbol in self.top_symbols[:10]:
                try:
                    ticker = self.api.get_ticker(symbol)
                    if ticker:
                        self.update(symbol, ticker)
                except:
                    pass
            time.sleep(0.2)
    
    def update(self, symbol: str, ticker: dict):
        with self.lock:
            self.cache[symbol] = (ticker, time.time() * 1000)
    
    def get(self, symbol: str):
        with self.lock:
            if symbol in self.cache:
                ticker, ts = self.cache[symbol]
                age = time.time() * 1000 - ts
                if age < self.max_age_ms:
                    return ticker
        ticker = self.api.get_ticker(symbol)
        if ticker:
            self.update(symbol, ticker)
        return ticker
    
    def get_cached(self, symbol: str):
        with self.lock:
            if symbol in self.cache:
                return self.cache[symbol][0]
        return None

# ============================================
# WEBSOCKET
# ============================================

class DeltaWebSocket:
    def __init__(self, on_ticker):
        self.on_ticker = on_ticker
        self.ws = None
        self.running = False
        self.tickers = {}
    
    def connect(self, symbols: List[str]):
        def on_message(ws, message):
            try:
                data = json.loads(message)
                if data.get('type') == 'v2/ticker':
                    symbol = data.get('symbol')
                    if symbol:
                        self.tickers[symbol] = data
                        self.on_ticker(symbol, data)
            except:
                pass
        
        def on_open(ws):
            logging.info("[WS] Connected")
            subscribe = {
                "type": "subscribe",
                "payload": {
                    "channels": [{"name": "v2/ticker", "symbols": symbols}]
                }
            }
            ws.send(json.dumps(subscribe))
        
        def on_error(ws, error):
            logging.error(f"[WS] Error: {error}")
        
        def on_close(ws, code, msg):
            logging.warning(f"[WS] Closed: {code}")
            if self.running:
                time.sleep(5)
                self.connect(symbols)
        
        self.running = True
        self.ws = websocket.WebSocketApp(
            WS_URL,
            on_message=on_message,
            on_open=on_open,
            on_error=on_error,
            on_close=on_close
        )
        
        thread = threading.Thread(target=self.ws.run_forever, daemon=True)
        thread.start()
    
    def get_ticker(self, symbol: str) -> Optional[dict]:
        return self.tickers.get(symbol)
    
    def stop(self):
        self.running = False
        if self.ws:
            self.ws.close()


# ============================================
# MAIN BOT
# ============================================

class DeltaBotV10:
    def __init__(self):
        self.api = DeltaAPI()
        self.ws = None
        self.state = StatePersistence()
        self.experience_buffer = ExperienceBuffer()
        self.position_mgr = PositionManager(
            api=self.api,
            state=self.state,
            on_close_callback=self.on_position_closed,
            experience_buffer=self.experience_buffer
        )
        self.ticker_cache = TickerCache(self.api, max_age_ms=500)
        
        self.blacklist = {}  # symbol -> expiry time
        self.last_trade_time = 0
        self.consecutive_losses = 0
        self.start_equity = 0
        self.running = False
        
        # Delta tracking for order flow
        self.delta_values = {}  # symbol -> [delta values]
    
    def on_position_closed(self, position: Position, reason: str, pnl: float):
        """Callback when position is closed"""
        self.state.record_trade(position.symbol, pnl, reason)
        
        if pnl > 0:
            self.consecutive_losses = 0
        else:
            self.consecutive_losses += 1
        
        # Blacklist symbol
        self.blacklist[position.symbol] = time.time() + BLACKLIST_SECONDS
        
        logging.info(f"[TRADE] {position.symbol} closed: {pnl:+.2f}% ({reason})")
        # Telegram alert
        try:
            get_telegram_bot().notify_exit(position.symbol, pnl, reason, (time.time() - position.entry_time) / 60 if hasattr(position, "entry_time") else 0)
        except Exception as e:
            logging.debug(f"[TELEGRAM] Exit notification failed: {e}")
        logging.info(f"[STATS] Wins: {self.state.state['wins']} | Losses: {self.state.state['losses']} | Win Rate: {self.state.get_win_rate():.0%}")
    
    def on_ticker(self, symbol: str, ticker: dict):
        """WebSocket ticker callback - update cache"""
        self.ticker_cache.update(symbol, ticker)
    
    def get_adaptive_threshold(self) -> int:
        """Adjust entry threshold based on performance"""
        base = MIN_SCORE
        win_rate = self.state.get_win_rate()
        
        if win_rate < 0.5:
            return base + 15  # Stricter when losing
        elif win_rate > 0.75:
            return base - 5   # Looser when winning
        return base
    
    def calculate_score(self, symbol: str, ticker: dict, candles: List[dict], 
                        orderbook: dict = None, trades: List[dict] = None) -> Tuple[int, List[str]]:
        """Calculate V9 entry score"""
        score = 0
        signals = []
        
        if len(candles) < 20:
            return 0, []
        
        # === SENTIMENT (V9 NEW) ===
        sent_adj, sent_signals = get_sentiment_adjustment(symbol)
        score += sent_adj
        signals.extend(sent_signals)
        
        # === TECHNICAL INDICATORS ===
        result = calculate_v9_indicators(
            symbol, candles, orderbook,
            delta_values=estimate_delta_from_candles(candles),
            trades=trades
        )
        
        score += result['score']
        signals.extend(result['signals'])
        
        # === FUNDING RATE ===
        funding = float(ticker.get('funding_rate', 0))
        if funding < -0.01:
            score += 15
            signals.append(f"FUND({funding*100:.2f}%)")
        
        # === MOMENTUM ===
        change_24h = float(ticker.get('price_change_percent_24h', 0))
        if 5 < change_24h < 15:
            score += 10
            signals.append(f"MOM({change_24h:.1f}%)")
        
        # === VOLUME ===
        turnover = float(ticker.get('turnover_usd', 0))
        if turnover > 10_000_000:
            score += 10
            signals.append("VOL+")
        
        # === SOCIAL SENTIMENT ===
        try:
            social_adj, social_sig = get_social_adjustment(symbol)
            if social_adj != 0:
                score += social_adj
                if social_sig:
                    signals.append(social_sig)
        except Exception as e:
            logging.debug(f"[SOCIAL] Error: {e}")
        
        # === FINBERT NLP SENTIMENT ===
        try:
            finbert_adj, finbert_sig = get_finbert_adjustment(symbol)
            logging.info(f"[FINBERT] {symbol}: adj={finbert_adj:+d}, sig={finbert_sig}")
            if finbert_adj != 0:
                score += finbert_adj
                if finbert_sig:
                    signals.append(finbert_sig)
        except Exception as e:
            logging.info(f"[FINBERT] {symbol} Error: {e}")
        
        # === ML PREDICTION (V10 Oracle) ===
        try:
            ml_prob, ml_signal, ml_adj = get_ml_prediction(candles, ticker, orderbook)
            if ml_adj != 0:
                score += ml_adj
                signals.append(f"{ml_signal}({ml_prob:.0%})")
        except Exception as e:
            logging.debug(f"[ML] Prediction error: {e}")
        
        return score, signals
    
    def analyze_symbol(self, symbol: str) -> Tuple[str, int, List[str], dict]:
        """Analyze a single symbol (for parallel execution)"""
        try:
            ticker = self.ticker_cache.get(symbol)
            if not ticker:
                if symbol in ['BTCUSD', 'ETHUSD']:
                    logging.info(f"[DEBUG] {symbol}: No ticker")
                return symbol, 0, [], {}
            
            # Skip low volume
            turnover = float(ticker.get('turnover_usd', 0))
            if turnover < MIN_TURNOVER_USD:
                if symbol in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
                    logging.info(f"[FILTER] {symbol}: Low turnover {turnover:.0f} < {MIN_TURNOVER_USD}")
                return symbol, 0, [], {}
            
            # Skip unaffordable coins (DISABLED for testing - FinBERT)
            # product = self.api.get_product_by_symbol(symbol)
            # if product:
            #     mark_price = float(ticker.get('mark_price', 0))
            #     contract_value = float(product.get('contract_value', 1))
            #     contract_cost = mark_price * contract_value
            #     min_buying_power = 0.001
            #     if contract_cost > min_buying_power:
            #         return symbol, 0, [], {}
            pass  # Affordability check disabled
            
            # Skip high volatility
            high = float(ticker.get('high', 0))
            low = float(ticker.get('low', 0))
            if low > 0:
                volatility = ((high - low) / low) * 100
                if volatility > MAX_VOLATILITY:
                    if symbol in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
                        logging.info(f"[FILTER] {symbol}: High volatility {volatility:.1f}% > {MAX_VOLATILITY}")
                    return symbol, 0, [], {}
            
            candles = self.api.get_candles(symbol, "5m", 50)
            if len(candles) < 20:
                if symbol in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
                    logging.info(f"[FILTER] {symbol}: Not enough candles ({len(candles)} < 20)")
                return symbol, 0, [], {}
            
            orderbook = self.api.get_orderbook(symbol)
            trades = self.api.get_recent_trades(symbol, limit=50)  # For whale detection
            score, signals = self.calculate_score(symbol, ticker, candles, orderbook, trades)
            
            if symbol in ['BTCUSD', 'ETHUSD', 'SOLUSD']:
                logging.info(f"[DEBUG] {symbol}: Score={score}, Signals={signals}")
            
            return symbol, score, signals, {
                'ticker': ticker,
                'candles': candles,
                'orderbook': orderbook
            }
        except Exception as e:
            logging.debug(f"Error analyzing {symbol}: {e}")
            return symbol, 0, [], {}
    
    def scan_markets(self) -> List[Tuple[str, int, List[str], dict]]:
        """Parallel scan of all markets"""
        symbols = list(self.api.products_by_symbol.keys())
        
        # Filter out blacklisted and already-held symbols
        now = time.time()
        active_symbols = set(self.position_mgr.positions.keys())
        
        symbols = [s for s in symbols 
                   if s not in active_symbols 
                   and self.blacklist.get(s, 0) < now]
        
        results = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(self.analyze_symbol, sym): sym for sym in symbols}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result[1] > 0:  # Has score
                        results.append(result)
                except:
                    pass
        
        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results
    
    def open_trade(self, symbol: str, score: int, signals: List[str], data: dict):
        """Open a new position"""
        logging.info(f"[TRADE] Attempting to open {symbol} score={score}")
        
        # Check available margin first
        wallet = self.api.get_wallet()
        if wallet:
            available = float(wallet.get("available_balance", 0))
            if available < 0.01:  # Lower threshold for small account  # Less than $0.10 available
                logging.warning(f"[TRADE] {symbol}: Insufficient margin (${available:.4f} available)")
                return False
        product = self.api.get_product_by_symbol(symbol)
        if not product:
            logging.warning(f"[TRADE] {symbol}: No product found")
            return False
        
        ticker = data['ticker']
        candles = data['candles']
        
        # Get wallet and calculate position size
        wallet = self.api.get_wallet()
        if not wallet:
            logging.warning(f"[TRADE] {symbol}: No wallet")
            return False
        
        equity = float(wallet.get('balance', 0))
        logging.info(f"[TRADE] {symbol}: Equity={equity}, Allocation={self.position_mgr.get_allocation()}")
        allocation = self.position_mgr.get_allocation()
        position_value = equity * allocation
        
        mark_price = float(ticker.get('mark_price', 0))
        if mark_price <= 0:
            logging.warning(f"[TRADE] {symbol}: Invalid mark price")
            return
        
        # Calculate ATR for stops
        atr = calculate_atr(candles)
        atr_pct = (atr / mark_price) * 100 if mark_price > 0 else 2
        
        # Position sizing
        contract_value = float(product.get('contract_value', 1))
        size = int((position_value * LEVERAGE) / (mark_price * contract_value))
        
        if size < 1:
            logging.warning(f"[TRADE] {symbol}: Size too small ({size})")
            return False
        
        logging.info(f"[TRADE] {symbol}: Placing order size={size}")
        
        # Dynamic stops based on ATR
        stop_loss = -2 * atr_pct * LEVERAGE
        take_profit = 3 * abs(stop_loss)  # 3:1 R:R
        
        # === PPO RL Position Sizing ===
        try:
            # Get last 20 candles for PPO observation
            ppo_candles = self.candle_cache.get(symbol, [])[-20:]
            if len(ppo_candles) >= 20:
                ppo_rec = get_ppo_recommendation(
                    candles=[[c["open"], c["high"], c["low"], c["close"], c.get("volume", 0)] for c in ppo_candles],
                    balance=self.balance,
                    position=0
                )
                if ppo_rec:
                    # Blend PPO recommendations with ATR-based values
                    ppo_sl = ppo_rec["stop_loss"] * 100 * LEVERAGE
                    ppo_tp = ppo_rec["take_profit"] * 100 * LEVERAGE
                    stop_loss = (stop_loss + ppo_sl) / 2  # Average
                    take_profit = (take_profit + ppo_tp) / 2
                    logging.debug(f"[PPO] Adjusted SL={stop_loss:.1f}% TP={take_profit:.1f}%")
        except Exception as e:
            logging.debug(f"[PPO] Adjustment error: {e}")
        
        # Limit order slightly above mark
        tick_size = float(product.get('tick_size', 0.01))
        limit_price = round((mark_price * 1.002) / tick_size) * tick_size
        
        # Place order
        order = self.api.place_order(
            product_id=product['id'],
            size=size,
            side="buy",
            order_type="limit_order",
            limit_price=str(limit_price),
            time_in_force="gtc"
        )
        
        logging.info(f"[TRADE] {symbol}: Order response received: {bool(order)}")
        if order:
            logging.info(f"[TRADE] {symbol}: Order ID: {order.get('id')}, State: {order.get('state')}")
        
        if order and order.get('id'):
            # Open position with manager (starts monitor thread)
            logging.info(f"[TRADE] {symbol}: Opening position in manager...")
            try:
                self.position_mgr.open_position(
                    symbol=symbol,
                    product_id=product['id'],
                    entry_price=limit_price,
                    size=size,
                    leverage=LEVERAGE,
                    stop_loss_pct=stop_loss,
                    take_profit_pct=take_profit,
                    entry_score=score,
                    entry_signals=signals,
                    entry_features=self._get_entry_features(symbol, ticker, candles),
                    market_context=self._get_market_context()
                )
                logging.info(f"[TRADE] {symbol}: Position manager completed")
            except Exception as e:
                logging.error(f"[TRADE] {symbol}: Position manager error: {e}")
                import traceback
                logging.error(traceback.format_exc())
                return False
            
            self.last_trade_time = time.time()
            
            logging.info(f"[ENTRY] {symbol} Score={score}")
            # Telegram alert
            try:
                get_telegram_bot().notify_entry(symbol, "buy", size, limit_price, score, signals)
            except Exception as e:
                logging.debug(f"[TELEGRAM] Entry notification failed: {e}")
            logging.info(f"  Signals: {signals}")
            logging.info(f"  Size: {size} @ ${limit_price:.4f}")
            logging.info(f"  SL: {stop_loss:.1f}% | TP: {take_profit:.1f}%")
            return True
        else:
            logging.warning(f"[TRADE] {symbol}: Order failed")
            return False
    
    def _get_entry_features(self, symbol: str, ticker: dict, candles: list) -> dict:
        """Extract features for ML training"""
        try:
            rsi = calculate_rsi(candles) if candles else 50
            macd_line, signal, hist = calculate_macd(candles) if candles else (0, 0, 0)
            bb_upper, bb_middle, bb_lower = calculate_bollinger_bands(candles) if candles else (0, 0, 0)
            close = float(candles[-1]['close']) if candles else 0
            bb_pos = (close - bb_lower) / (bb_upper - bb_lower) if bb_upper > bb_lower else 0.5
            
            return {
                'rsi': rsi,
                'macd_hist': hist,
                'bb_position': bb_pos,
                'volume_ratio': float(ticker.get('turnover_usd', 0)) / 1_000_000,
                'fear_greed': get_fear_greed()[0],
                'funding_rate': float(ticker.get('funding_rate', 0)) * 100,
                'bid_ask_imbalance': 0  # Would need orderbook
            }
        except:
            return {}
    
    def _get_market_context(self) -> dict:
        """Get market context for ML training"""
        try:
            btc = self.ticker_cache.get('BTCUSD')
            eth = self.ticker_cache.get('ETHUSD')
            fg_value, fg_class = get_fear_greed()
            return {
                'btc_pnl_24h': float(btc.get('mark_change_24h', 0)) if btc else 0,
                'eth_pnl_24h': float(eth.get('mark_change_24h', 0)) if eth else 0,
                'fear_greed_index': fg_value,
                'fear_greed_class': fg_class
            }
        except:
            return {}
    
    def run(self):
        """Main bot loop"""
        logging.info("=" * 60)
        logging.info("DELTA BOT V10 - MULTI-POSITION ULTIMATE EDITION")
        logging.info("=" * 60)
        
        # Load products
        self.api.load_products()
        if not self.api.products_by_symbol:
            logging.error("No products loaded!")
            return
        
        # Get initial equity
        wallet = self.api.get_wallet()
        if wallet:
            self.start_equity = float(wallet.get('balance', 0))
            logging.info(f"Starting Equity: ${self.start_equity:.2f}")
        
        # Start Ticker Cache (background refresh)
        symbols = list(self.api.products_by_symbol.keys())[:50]  # Top 50
        self.ticker_cache.start(symbols)
        
        # Start WebSocket
        self.ws = DeltaWebSocket(self.on_ticker)
        self.ws.connect(symbols)
        
        # Load state
        logging.info(f"Loaded state: {self.state.state['wins']}W / {self.state.state['losses']}L")
        
        self.running = True
        scan_interval = 30  # seconds
        last_scan = 0
        last_status = 0
        
        # Sync existing positions from exchange
        logging.info("[SYNC] Starting position sync from exchange...")
        try:
            positions_data = self.api.get_positions()
            logging.info(f"[SYNC] Got {len(positions_data) if positions_data else 0} positions from API")
            if positions_data:
                synced = self.position_mgr.sync_from_exchange(positions_data)
                if synced > 0:
                    logging.info(f"Synced {synced} existing positions")
        except Exception as e:
            logging.error(f"Position sync error: {e}")

        logging.info("Bot started. Scanning markets...")
        
        while self.running:
            try:
                now = time.time()
                
                # DEBUG: Log every loop iteration
                if not hasattr(self, '_loop_count'):
                    self._loop_count = 0
                    self._last_debug = time.time()
                self._loop_count += 1
                if time.time() - self._last_debug >= 30:
                    logging.info(f"[DEBUG] Loop iterations: {self._loop_count}")
                    self._last_debug = time.time()
                
                # === STATUS LOG ===
                if now - last_status >= 60:
                    last_status = now
                    wallet = self.api.get_wallet()
                    if wallet:
                        equity = float(wallet.get('balance', 0))
                        positions = len(self.position_mgr.positions)
                        threshold = self.get_adaptive_threshold()
                        logging.info(f"[STATUS] Equity: ${equity:.2f} | Positions: {positions}/{MAX_POSITIONS} | Threshold: {threshold}")
                        # Auto-training (runs hourly)
                        try:
                            train_result = run_auto_training()
                            if train_result and train_result.get("status") == "trained":
                                logging.info(f"[LEARN] Trained on {train_result.get("samples")} samples, WR={train_result.get("win_rate", 0):.0%}")
                        except Exception as e:
                            logging.debug(f"[LEARN] Auto-train error: {e}")
                    else:
                        logging.warning("[DEBUG] Wallet API returned None")
                
                # === SAFETY CHECKS ===
                if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
                    logging.warning(f"Max consecutive losses ({MAX_CONSECUTIVE_LOSSES}). Pausing...")
                    time.sleep(300)
                    self.consecutive_losses = 0
                    continue
                
                # === SCAN MARKETS ===
                if now - last_scan >= scan_interval:
                    last_scan = now
                    
                    # Can we open more positions?
                    if not self.position_mgr.can_open_position():
                        continue
                    
                    # Cooldown check
                    if now - self.last_trade_time < COOLDOWN_SECONDS:
                        continue
                    
                    # Scan
                    results = self.scan_markets()
                    threshold = self.get_adaptive_threshold()
                    
                    # Debug: Log top 3 scores
                    if results:
                        top3 = sorted(results, key=lambda x: x[1], reverse=True)[:3]
                        for sym, score, sigs, _ in top3:
                            if score > 30:
                                logging.info(f"[SCAN] {sym}: Score={score} {sigs}")
                    else:
                        logging.info("[SCAN] No results from scan_markets")
                    
                    # Find best opportunity - try all until one succeeds
                    for symbol, score, signals, data in results:
                        logging.debug(f"[LOOP] Checking {symbol}: score={score}, threshold={threshold}")
                        if score >= threshold:
                            can_open = self.position_mgr.can_open_position(symbol)
                            logging.debug(f"[LOOP] {symbol}: can_open={can_open}")
                            if can_open:
                                success = self.open_trade(symbol, score, signals, data)
                                logging.info(f"[LOOP] {symbol}: trade result={success}")
                                if success:
                                    break  # One trade per scan
                                # If trade failed, continue to next symbol
                
                time.sleep(0.1)
                
            except KeyboardInterrupt:
                logging.info("Shutdown requested...")
                break
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(5)
        
        # Cleanup
        self.running = False
        if self.ws:
            self.ws.stop()
        self.position_mgr.close_all("SHUTDOWN")
        self.state.save()
        logging.info("Bot stopped.")


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    bot = DeltaBotV10()
    bot.run()

#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V7 - Ultimate Edition
=================================================
Research-backed trading with advanced indicators and risk management.

Features:
- 10 indicator categories (Divergence, BB Squeeze, VWAP, etc.)
- V7RiskManager with Kelly Criterion and Chandelier Exits
- Hybrid Momentum + Mean Reversion strategy
- Whale detection and BTC/ETH correlation
- Cloudflare WARP proxy for stable IP

Author: Vibhav Aggarwal
Date: December 20, 2025
"""

import requests
import json
import hmac
import hashlib
import time
import threading
import socket
import logging
import socks
import websocket
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Import V7 indicators
from indicators_v7 import (
    calculate_rsi, calculate_rsi_series, calculate_macd, calculate_atr,
    calculate_vwap, detect_bb_squeeze, detect_divergence,
    detect_market_regime, hybrid_strategy, kelly_position_size,
    chandelier_exit, dynamic_take_profit, analyze_funding_rate,
    analyze_orderbook, detect_whale_activity, btc_eth_lead_signal,
    calculate_volatility, get_price_from_ticker, get_24h_change, get_volume
)

# ============================================
# CONFIGURATION
# ============================================

API_KEY = "KMLkcDcajSQWPmVcgNuAd3KWqf7OzM"
API_SECRET = "ltJaGy3GErRluET1e7FaYOklFx1u7pGwCsiCqCO774ndLdPzcnZzmHYscT5W"
BASE_URL = "https://api.india.delta.exchange"
WS_URL = "wss://socket.india.delta.exchange"

# WARP Proxy
WARP_PROXY_HOST = "127.0.0.1"
WARP_PROXY_PORT = 40000

# Trading Parameters
LEVERAGE = 10
MIN_SCORE = 65  # Increased from 55 for higher quality
MAX_VOLATILITY = 20.0
LIMIT_ORDER_BUFFER = 0.002
COOLDOWN_SECONDS = 30
BLACKLIST_SECONDS = 180
MAX_CONSECUTIVE_LOSSES = 3
MAX_DAILY_DRAWDOWN = 0.10
MAX_IMMEDIATE_LOSS = -3.0
SLIPPAGE_CHECK_DELAY = 2.0

# Timeframes for multi-TF confirmation
TIMEFRAMES = ["5m", "15m", "1h"]

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/home/vibhavaggarwal/delta_websocket_v7.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ============================================
# V7 RISK MANAGER
# ============================================

class V7RiskManager:
    """
    Comprehensive risk management with Kelly sizing and Chandelier exits.
    """
    def __init__(self):
        self.trade_history = []
        self.wins = 0
        self.losses = 0
        self.total_win_pct = 0.0
        self.total_loss_pct = 0.0
        self.start_equity = None
        self.peak_equity = None
        self.consecutive_losses = 0
        self.last_trade_time = 0
        self.blacklist = {}  # symbol -> expiry timestamp
        
    def initialize(self, equity: float):
        """Initialize with starting equity."""
        self.start_equity = equity
        self.peak_equity = equity
        log.info(f"RiskManager initialized with equity: ${equity:.2f}")
        
    def can_trade(self, current_equity: float) -> Tuple[bool, str]:
        """Check if trading is allowed."""
        # Cooldown
        if time.time() - self.last_trade_time < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (time.time() - self.last_trade_time)
            return False, f"Cooldown: {remaining:.0f}s"
        
        # Max consecutive losses
        if self.consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
            return False, f"Max losses reached: {self.consecutive_losses}"
        
        # Daily drawdown
        if self.start_equity and current_equity < self.start_equity * (1 - MAX_DAILY_DRAWDOWN):
            drawdown = ((self.start_equity - current_equity) / self.start_equity) * 100
            return False, f"Daily drawdown: {drawdown:.1f}%"
        
        return True, "OK"
    
    def is_blacklisted(self, symbol: str) -> bool:
        """Check if symbol is blacklisted."""
        if symbol in self.blacklist:
            if time.time() < self.blacklist[symbol]:
                return True
            del self.blacklist[symbol]
        return False
    
    def blacklist_symbol(self, symbol: str):
        """Add symbol to blacklist."""
        self.blacklist[symbol] = time.time() + BLACKLIST_SECONDS
        log.info(f"Blacklisted {symbol} for {BLACKLIST_SECONDS}s")
    
    def calculate_position_size(self, equity: float, data: Dict) -> float:
        """
        Calculate position size using Kelly Criterion with volatility adjustment.
        """
        total_trades = self.wins + self.losses
        
        if total_trades < 5:
            base_size = 0.15  # Conservative 15% without history
        else:
            win_rate = self.wins / total_trades
            avg_win = self.total_win_pct / self.wins if self.wins > 0 else 5
            avg_loss = abs(self.total_loss_pct / self.losses) if self.losses > 0 else 5
            base_size = kelly_position_size(win_rate, avg_win, avg_loss, equity, 0.25)
        
        # Volatility adjustment
        volatility = data.get("volatility", 10)
        if volatility < 5:
            adj = 1.2
        elif volatility < 10:
            adj = 1.0
        elif volatility < 15:
            adj = 0.75
        else:
            adj = 0.5
        
        final_size = min(base_size * adj, 0.50)
        log.info(f"Position size: {final_size:.1%} (base={base_size:.1%}, vol_adj={adj})")
        return final_size
    
    def calculate_stops(self, entry_price: float, data: Dict) -> Dict:
        """
        Calculate ATR-based dynamic stops with Chandelier exit.
        """
        atr = data.get("atr", entry_price * 0.02)
        
        # Initial stop: 2x ATR
        stop_distance = atr * 2
        stop_pct = (stop_distance / entry_price) * 100 * LEVERAGE
        stop_loss = max(-10, -stop_pct)
        
        # Take profit: 3:1 R:R ratio
        tp = dynamic_take_profit(entry_price, atr, LEVERAGE, risk_reward=3.0)
        
        # Trailing: start at +3%, trail at 1.5x ATR
        trail_start = 3.0
        trail_distance = max(1.5, (atr / entry_price) * 100 * LEVERAGE * 1.5)
        
        stops = {
            "stop_loss": stop_loss,
            "take_profit": tp["tp_percent"],
            "trail_start": trail_start,
            "trail_distance": trail_distance
        }
        log.info(f"Stops: SL={stop_loss:.1f}%, TP={tp['tp_percent']:.1f}%, Trail@{trail_start}%/{trail_distance:.1f}%")
        return stops
    
    def record_trade(self, pnl_percent: float, win: bool):
        """Record trade result for Kelly calculation."""
        if win:
            self.wins += 1
            self.total_win_pct += pnl_percent
            self.consecutive_losses = 0
        else:
            self.losses += 1
            self.total_loss_pct += pnl_percent
            self.consecutive_losses += 1
        
        self.last_trade_time = time.time()
        self.trade_history.append({
            "pnl": pnl_percent,
            "win": win,
            "timestamp": time.time()
        })
        
        total = self.wins + self.losses
        win_rate = (self.wins / total) * 100 if total > 0 else 0
        log.info(f"Trade recorded: {'WIN' if win else 'LOSS'} {pnl_percent:.2f}% | W/L: {self.wins}/{self.losses} ({win_rate:.0f}%)")


# ============================================
# API CLIENT
# ============================================

class DeltaAPI:
    """Delta Exchange API client with WARP proxy support."""
    
    def __init__(self, use_proxy: bool = True):
        self.session = requests.Session()
        self.use_proxy = use_proxy
        
        # Connection pooling
        adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30)
        self.session.mount("https://", adapter)
        
        if use_proxy:
            self.session.proxies = {
                "http": f"socks5h://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}",
                "https": f"socks5h://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}"
            }
            log.info(f"Using WARP proxy: {WARP_PROXY_HOST}:{WARP_PROXY_PORT}")
        
        # Force IPv4
        self._force_ipv4()
        
        # Cache products
        self.products = {}
        self.load_products()
    
    def _force_ipv4(self):
        """Force IPv4 connections."""
        _orig = socket.getaddrinfo
        def _ipv4_only(*args, **kwargs):
            return [r for r in _orig(*args, **kwargs) if r[0] == socket.AF_INET]
        socket.getaddrinfo = _ipv4_only
    
    def _sign(self, method: str, path: str, body: Dict = None) -> Dict:
        """Generate authentication headers."""
        timestamp = str(int(time.time()))
        data = method + timestamp + path
        if body:
            data += json.dumps(body, separators=(",", ":"))
        
        signature = hmac.new(
            API_SECRET.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return {
            "api-key": API_KEY,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json"
        }
    
    def get(self, path: str, auth: bool = False) -> Dict:
        """GET request."""
        headers = self._sign("GET", path) if auth else {}
        try:
            resp = self.session.get(BASE_URL + path, headers=headers, timeout=10)
            return resp.json()
        except Exception as e:
            log.error(f"GET {path} failed: {e}")
            return {}
    
    def post(self, path: str, body: Dict) -> Dict:
        """POST request."""
        headers = self._sign("POST", path, body)
        try:
            resp = self.session.post(
                BASE_URL + path,
                headers=headers,
                data=json.dumps(body, separators=(",", ":")),
                timeout=10
            )
            return resp.json()
        except Exception as e:
            log.error(f"POST {path} failed: {e}")
            return {}
    
    def load_products(self):
        """Load tradeable products."""
        resp = self.get("/v2/products")
        for p in resp.get("result", []):
            if p.get("contract_type") == "perpetual_futures" and p.get("state") == "live":
                symbol = p.get("symbol", "")
                if symbol.endswith("USD"):
                    self.products[symbol] = {
                        "id": p.get("id"),
                        "tick_size": float(p.get("tick_size", 0.0001)),
                        "contract_value": float(p.get("contract_value", 1)),
                        "impact_size": int(p.get("impact_size", 10))
                    }
        log.info(f"Loaded {len(self.products)} USD perpetual products")
    
    def get_equity(self) -> float:
        """Get account equity."""
        resp = self.get("/v2/wallet/balances", auth=True)
        return float(resp.get("meta", {}).get("net_equity", 0))
    
    def get_positions(self) -> List[Dict]:
        """Get open positions."""
        resp = self.get("/v2/positions/margined", auth=True)
        return [p for p in resp.get("result", []) if float(p.get("size", 0)) != 0]
    
    def get_candles(self, symbol: str, resolution: str = "5m", count: int = 50) -> List[Dict]:
        """Get historical candles."""
        end = int(time.time())
        minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(resolution, 5)
        start = end - (count * minutes * 60)
        
        resp = self.get(f"/v2/history/candles?resolution={resolution}&symbol={symbol}&start={start}&end={end}")
        return resp.get("result", [])
    
    def get_orderbook(self, symbol: str) -> Dict:
        """Get order book."""
        product = self.products.get(symbol, {})
        if not product:
            return {}
        
        resp = self.get(f"/v2/l2orderbook/{product['id']}")
        return resp.get("result", {})
    
    def place_limit_order(self, symbol: str, side: str, size: int, price: float) -> Dict:
        """Place limit order with buffer."""
        product = self.products.get(symbol)
        if not product:
            return {"error": f"Unknown product: {symbol}"}
        
        tick_size = product["tick_size"]
        limit_price = price * (1 + LIMIT_ORDER_BUFFER) if side == "buy" else price * (1 - LIMIT_ORDER_BUFFER)
        rounded_price = round(limit_price / tick_size) * tick_size
        
        order = {
            "product_id": product["id"],
            "size": size,
            "side": side,
            "order_type": "limit_order",
            "limit_price": str(rounded_price),
            "time_in_force": "gtc"
        }
        
        log.info(f"Placing {side.upper()} {size} {symbol} @ {rounded_price}")
        return self.post("/v2/orders", order)
    
    def place_market_order(self, symbol: str, side: str, size: int) -> Dict:
        """Place market order (for exits)."""
        product = self.products.get(symbol)
        if not product:
            return {"error": f"Unknown product: {symbol}"}
        
        order = {
            "product_id": product["id"],
            "size": size,
            "side": side,
            "order_type": "market_order"
        }
        
        log.info(f"Market {side.upper()} {size} {symbol}")
        return self.post("/v2/orders", order)


# ============================================
# V7 SCORING ENGINE
# ============================================

def calculate_v7_score(symbol: str, ticker: Dict, candles: List[Dict], 
                       orderbook: Dict, btc_ticker: Dict, eth_ticker: Dict) -> Tuple[int, List[str], Dict]:
    """
    Ultimate V7 scoring algorithm with tiered signals.
    Max score: 150+ points, Entry threshold: 65 points
    """
    score = 0
    signals = []
    data = {}
    
    if len(candles) < 30:
        return 0, ["INSUFFICIENT_DATA"], {}
    
    # Core calculations
    rsi = calculate_rsi(candles)
    rsi_series = calculate_rsi_series(candles)
    macd_line, macd_signal, macd_hist = calculate_macd(candles)
    atr = calculate_atr(candles)
    volatility = calculate_volatility(ticker)
    
    data["rsi"] = rsi
    data["atr"] = atr
    data["volatility"] = volatility
    data["macd_hist"] = macd_hist
    
    # Skip if too volatile
    if volatility > MAX_VOLATILITY:
        return 0, [f"HIGH_VOL({volatility:.0f}%)"], data
    
    # ============================================
    # TIER 1: STRONGEST SIGNALS (30 pts max)
    # ============================================
    
    # 1. RSI Divergence (30 pts - STRONGEST)
    divergence = detect_divergence(candles, rsi_series)
    score += divergence["score"]
    if divergence["type"] == "BULLISH":
        signals.append(f"DIV_BULL")
    elif divergence["type"] == "BEARISH":
        signals.append(f"DIV_BEAR")
    data["divergence"] = divergence
    
    # 2. Bollinger Band Squeeze + Breakout (25 pts)
    bb = detect_bb_squeeze(candles)
    score += bb["score"]
    if bb["is_squeeze"]:
        signals.append(f"SQUEEZE({bb['bandwidth']:.1f}%)")
    data["bb"] = bb
    
    # ============================================
    # TIER 2: STRONG SIGNALS (20 pts max)
    # ============================================
    
    # 3. Real RSI Oversold (20 pts)
    if rsi < 25:
        score += 20
        signals.append(f"RSI({rsi:.0f})")
    elif rsi < 35:
        score += 15
    elif rsi < 45:
        score += 8
    
    # 4. MACD Bullish (20 pts)
    if macd_hist > 0:
        score += 20
        signals.append("MACD+")
    
    # 5. Hybrid Strategy (20 pts)
    regime = detect_market_regime(candles, atr)
    hybrid = hybrid_strategy(regime, rsi, bb["position"])
    score += hybrid["score"]
    if hybrid["action"] == "BUY":
        signals.append(f"{regime['strategy']}")
    data["regime"] = regime
    
    # ============================================
    # TIER 3: MEDIUM SIGNALS (15 pts max)
    # ============================================
    
    # 6. Order Book Imbalance (15 pts)
    ob_signal, ob_imbalance = analyze_orderbook(orderbook)
    if ob_signal == "BUY_PRESSURE":
        score += 15
        signals.append(f"OB({ob_imbalance:.0%})")
    elif ob_signal == "SELL_PRESSURE":
        score -= 10
    else:
        score += 5
    
    # 7. VWAP Analysis (15 pts)
    vwap = calculate_vwap(candles)
    score += vwap["score"]
    if vwap["above_vwap"]:
        signals.append("VWAP+")
    data["vwap"] = vwap
    
    # 8. Funding Rate Strategy (15 pts)
    funding = analyze_funding_rate(ticker)
    score += funding["score"]
    if funding["signal"] == "CONTRARIAN_LONG":
        signals.append(f"FUND({funding['funding']:.2f}%)")
    data["funding"] = funding
    
    # 9. Whale Detection (15 pts)
    whale = detect_whale_activity(orderbook)
    score += whale["score"]
    if whale["signal"] == "WHALE_BUYING":
        signals.append("WHALE+")
    
    # ============================================
    # TIER 4: CONFIRMATION SIGNALS (10 pts max)
    # ============================================
    
    # 10. 24h Momentum (10 pts)
    chg = get_24h_change(ticker)
    if 5 <= chg <= 15:
        score += 10
        signals.append(f"MOM({chg:.1f}%)")
    elif 2 <= chg < 5:
        score += 7
    elif 0 < chg < 2:
        score += 3
    
    # 11. Volume (10 pts)
    vol = get_volume(ticker)
    if vol > 10_000_000:
        score += 10
        signals.append(f"VOL(${vol/1e6:.0f}M)")
    elif vol > 5_000_000:
        score += 5
    
    # 12. BTC/ETH Lead Signal (10 pts)
    lead = btc_eth_lead_signal(btc_ticker, eth_ticker, ticker)
    score += lead["score"]
    if lead["signal"] == "CATCH_UP_POTENTIAL":
        signals.append("LEAD+")
    
    return score, signals, data


# ============================================
# WEBSOCKET HANDLER
# ============================================

class DeltaWebSocket:
    """WebSocket handler for real-time ticker data."""
    
    def __init__(self, api: DeltaAPI):
        self.api = api
        self.ws = None
        self.running = False
        self.tickers = {}
        self.lock = threading.Lock()
        self.connected = False
        
    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            
            if msg_type == "v2/ticker":
                symbol = data.get("symbol")
                with self.lock:
                    self.tickers[symbol] = data
            elif msg_type == "subscriptions":
                channels = data.get("channels", [])
                log.info(f"[WS] Subscribed to {len(channels)} channels")
                self.connected = True
        except Exception as e:
            log.error(f"[WS] Message error: {e}")
    
    def on_error(self, ws, error):
        log.error(f"[WS] Error: {error}")
        self.connected = False
    
    def on_close(self, ws, code, msg):
        log.warning(f"[WS] Closed: {code}")
        self.connected = False
    
    def on_open(self, ws):
        log.info("[WS] Connected!")
        
        # Subscribe to all USD tickers
        symbols = list(self.api.products.keys())
        ws.send(json.dumps({
            "type": "subscribe",
            "payload": {
                "channels": [{
                    "name": "v2/ticker",
                    "symbols": symbols
                }]
            }
        }))
    
    def start(self):
        """Start WebSocket connection with WARP proxy."""
        self.running = True
        
        def run():
            while self.running:
                try:
                    # Configure SOCKS proxy for WebSocket
                    socks.set_default_proxy(socks.SOCKS5, WARP_PROXY_HOST, WARP_PROXY_PORT)
                    socket.socket = socks.socksocket
                    
                    self.ws = websocket.WebSocketApp(
                        WS_URL,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                        on_open=self.on_open
                    )
                    self.ws.run_forever(ping_interval=30, ping_timeout=10)
                except Exception as e:
                    log.error(f"[WS] Connection error: {e}")
                
                if self.running:
                    log.info("[WS] Reconnecting in 5s...")
                    time.sleep(5)
        
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread
    
    def get_ticker(self, symbol: str) -> Dict:
        with self.lock:
            return self.tickers.get(symbol, {})
    
    def get_all_tickers(self) -> Dict:
        with self.lock:
            return dict(self.tickers)


# ============================================
# MAIN TRADING BOT
# ============================================

class DeltaBotV7:
    """Main trading bot with V7 scoring and risk management."""
    
    def __init__(self):
        self.api = DeltaAPI(use_proxy=True)
        self.ws = DeltaWebSocket(self.api)
        self.risk_mgr = V7RiskManager()
        
        # Position tracking
        self.in_position = False
        self.position_symbol = None
        self.position_size = 0
        self.entry_price = 0
        self.entry_time = 0
        self.peak_pnl = 0
        self.slippage_checked = False
        self.stops = {}
        
    def start(self):
        """Start the trading bot."""
        log.info("="*60)
        log.info("Delta Exchange Trading Bot V7 - STARTING")
        log.info("="*60)
        
        # Initialize
        equity = self.api.get_equity()
        self.risk_mgr.initialize(equity)
        log.info(f"Starting equity: ${equity:.2f} (Rs.{equity * 85:.0f})")
        
        # Check for existing positions
        positions = self.api.get_positions()
        if positions:
            pos = positions[0]
            self.in_position = True
            self.position_symbol = pos["product"]["symbol"]
            self.position_size = int(abs(float(pos["size"])))
            self.entry_price = float(pos["entry_price"])
            self.entry_time = time.time()
            
            # Initialize stops for existing position
            candles = self.api.get_candles(self.position_symbol, "5m", 50)
            atr = calculate_atr(candles) if candles else self.entry_price * 0.02
            data = {"atr": atr, "volatility": 10}
            self.stops = self.risk_mgr.calculate_stops(self.entry_price, data)
            self.slippage_checked = True  # Skip slippage check for existing
            
            log.info(f"Existing position: {self.position_symbol} x{self.position_size} @ {self.entry_price}")
        
        # Start WebSocket
        self.ws.start()
        time.sleep(5)  # Wait for connection
        
        # Main loop
        self.run()
    
    def run(self):
        """Main trading loop."""
        last_scan = 0
        scan_interval = 10  # seconds
        
        while True:
            try:
                # Check WebSocket connection
                if not self.ws.connected:
                    log.warning("WebSocket not connected, waiting...")
                    time.sleep(5)
                    continue
                
                # Position management
                if self.in_position:
                    self.manage_position()
                else:
                    # Scan for opportunities
                    if time.time() - last_scan >= scan_interval:
                        self.scan_for_entries()
                        last_scan = time.time()
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                log.info("Shutting down...")
                break
            except Exception as e:
                log.error(f"Main loop error: {e}")
                time.sleep(5)
    
    def scan_for_entries(self):
        """Scan all tickers for entry opportunities."""
        equity = self.api.get_equity()
        
        can_trade, reason = self.risk_mgr.can_trade(equity)
        if not can_trade:
            return
        
        tickers = self.ws.get_all_tickers()
        if not tickers:
            return
        
        # Get BTC and ETH tickers for correlation
        btc_ticker = tickers.get("BTCUSD", {})
        eth_ticker = tickers.get("ETHUSD", {})
        
        best_score = 0
        best_symbol = None
        best_signals = []
        best_data = {}
        
        for symbol, ticker in tickers.items():
            # Skip non-USD, majors, and blacklisted
            if not symbol.endswith("USD"):
                continue
            if symbol in ["BTCUSD", "ETHUSD"]:
                continue
            if self.risk_mgr.is_blacklisted(symbol):
                continue
            if symbol not in self.api.products:
                continue
            
            # Get candles and orderbook
            candles = self.api.get_candles(symbol, "5m", 50)
            orderbook = self.api.get_orderbook(symbol)
            
            if not candles or len(candles) < 30:
                continue
            
            # Calculate V7 score
            score, signals, data = calculate_v7_score(
                symbol, ticker, candles, orderbook, btc_ticker, eth_ticker
            )
            
            if score > best_score and score >= MIN_SCORE:
                best_score = score
                best_symbol = symbol
                best_signals = signals
                best_data = data
        
        # Enter best opportunity
        if best_symbol and best_score >= MIN_SCORE:
            ticker = tickers[best_symbol]
            self.enter_position(best_symbol, ticker, best_score, best_signals, best_data, equity)
    
    def enter_position(self, symbol: str, ticker: Dict, score: int, 
                       signals: List[str], data: Dict, equity: float):
        """Enter a new position."""
        price = get_price_from_ticker(ticker)
        if price <= 0:
            return
        
        product = self.api.products[symbol]
        
        # Calculate position size using V7 risk manager
        size_pct = self.risk_mgr.calculate_position_size(equity, data)
        notional = equity * LEVERAGE * size_pct
        size = int(notional / (price * product["contract_value"]))
        size = max(1, size)
        
        # Calculate stops
        self.stops = self.risk_mgr.calculate_stops(price, data)
        
        log.info("="*50)
        log.info(f"ENTRY: {symbol} Score={score} Signals={signals}")
        log.info(f"Price: {price} | Size: {size} | Notional: ${notional:.2f}")
        log.info("="*50)
        
        # Place limit order
        resp = self.api.place_limit_order(symbol, "buy", size, price)
        
        if resp.get("success"):
            self.in_position = True
            self.position_symbol = symbol
            self.position_size = size
            self.entry_price = price
            self.entry_time = time.time()
            self.peak_pnl = 0
            self.slippage_checked = False
            self.risk_mgr.blacklist_symbol(symbol)
            log.info(f"Order placed: {resp.get('result', {}).get('id', 'unknown')}")
        else:
            log.error(f"Order failed: {resp}")
    
    def manage_position(self):
        """Manage open position - exits and trailing."""
        ticker = self.ws.get_ticker(self.position_symbol)
        if not ticker:
            return
        
        price = get_price_from_ticker(ticker)
        if price <= 0:
            return
        
        pnl = ((price - self.entry_price) / self.entry_price) * 100 * LEVERAGE
        self.peak_pnl = max(self.peak_pnl, pnl)
        
        time_in_trade = time.time() - self.entry_time
        
        # Slippage check (2s after entry)
        if time_in_trade >= SLIPPAGE_CHECK_DELAY and not self.slippage_checked:
            self.slippage_checked = True
            if pnl < MAX_IMMEDIATE_LOSS:
                log.warning(f"Slippage exit! P&L={pnl:.2f}%")
                self.close_position("SLIPPAGE_EXIT", pnl)
                return
        
        # 1. Stop Loss
        if pnl <= self.stops["stop_loss"]:
            self.close_position("STOP", pnl)
            return
        
        # 2. Take Profit
        if pnl >= self.stops["take_profit"]:
            self.close_position("PROFIT", pnl)
            return
        
        # 3. Trailing Stop
        if self.peak_pnl >= self.stops["trail_start"]:
            trail_level = self.peak_pnl - self.stops["trail_distance"]
            if pnl <= trail_level:
                self.close_position(f"TRAIL({self.peak_pnl:.1f}%)", pnl)
                return
        
        # Log status every 30s
        if int(time_in_trade) % 30 == 0:
            log.info(f"[{self.position_symbol}] P&L={pnl:.2f}% Peak={self.peak_pnl:.2f}%")
    
    def close_position(self, reason: str, pnl: float):
        """Close the current position."""
        log.info("="*50)
        log.info(f"EXIT: {self.position_symbol} | {reason} | P&L={pnl:.2f}%")
        log.info("="*50)
        
        # Place market sell order
        resp = self.api.place_market_order(self.position_symbol, "sell", self.position_size)
        
        # Record trade
        is_win = pnl > 0
        self.risk_mgr.record_trade(pnl, is_win)
        
        # Log equity
        equity = self.api.get_equity()
        log.info(f"Equity: ${equity:.2f} (Rs.{equity * 85:.0f})")
        
        # Reset state
        self.in_position = False
        self.position_symbol = None
        self.position_size = 0
        self.entry_price = 0
        self.peak_pnl = 0


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    bot = DeltaBotV7()
    bot.start()

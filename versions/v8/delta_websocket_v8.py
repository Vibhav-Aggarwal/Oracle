#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V8 - Ultimate Edition
=================================================
Next-generation trading with parallel processing, caching, and state persistence.

NEW in V8:
- Parallel symbol scanning (10x faster)
- Indicator caching with incremental updates
- Volume-based pre-filtering (reduces 164 -> ~30 symbols)
- State persistence (no data loss on restart)
- Order flow analysis (delta volume, absorption)
- Adaptive threshold based on win rate
- Telegram notifications (optional)

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
import os
from datetime import datetime
from typing import Dict, List, Tuple, Optional
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Import V8 indicators (enhanced with caching)
from indicators_v8 import (
    IndicatorCache, calculate_rsi, calculate_rsi_series, calculate_macd, calculate_atr,
    calculate_vwap, detect_bb_squeeze, detect_divergence,
    detect_market_regime, hybrid_strategy, kelly_position_size,
    chandelier_exit, dynamic_take_profit, analyze_funding_rate,
    analyze_orderbook, detect_whale_activity, btc_eth_lead_signal,
    calculate_volatility, get_price_from_ticker, get_24h_change, get_volume,
    calculate_delta_volume, detect_delta_divergence, detect_absorption,
    detect_large_trades
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
MIN_SCORE_BASE = 70  # Adaptive threshold base (increased from 65)
MAX_VOLATILITY = 20.0
LIMIT_ORDER_BUFFER = 0.002
COOLDOWN_SECONDS = 30
BLACKLIST_SECONDS = 180
MAX_CONSECUTIVE_LOSSES = 3
MAX_DAILY_DRAWDOWN = 0.10
MAX_IMMEDIATE_LOSS = -3.0
SLIPPAGE_CHECK_DELAY = 2.0

# V8 New: Parallel processing and filtering
PARALLEL_WORKERS = 10  # Number of parallel threads for symbol analysis
MIN_TURNOVER_USD = 1_000_000  # $1M minimum daily volume (filter low-liq symbols)
SCAN_INTERVAL = 5  # Reduced from 10s to 5s (faster scans)
# LIGHTNING SPEED SETTINGS (Best of all worlds)
POSITION_CHECK_MS = 25   # 25ms = 40 checks/sec (from delta_lightning)
EXIT_ORDER_TYPE = "limit"  # Use limit orders for exits (no slippage)
EXIT_LIMIT_BUFFER = 0.003  # 0.3% buffer for limit exit orders

# V8 New: State persistence
STATE_FILE = "/home/vibhavaggarwal/bot_state.json"

# Telegram (optional)
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("/home/vibhavaggarwal/delta_websocket_v8.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ============================================
# STATE PERSISTENCE
# ============================================

class StatePersistence:
    """
    Persist trade history and statistics across restarts.
    V8 NEW: No data loss on restart!
    """
    def __init__(self, filepath: str = STATE_FILE):
        self.filepath = filepath
        self.state = self.load()
        log.info(f"State loaded: {self.state['wins']}W/{self.state['losses']}L")
    
    def load(self) -> Dict:
        """Load state from file or create default."""
        if Path(self.filepath).exists():
            try:
                with open(self.filepath) as f:
                    state = json.load(f)
                    # Ensure all keys exist
                    defaults = self._default_state()
                    for key, value in defaults.items():
                        if key not in state:
                            state[key] = value
                    return state
            except Exception as e:
                log.error(f"Failed to load state: {e}")
        return self._default_state()
    
    def _default_state(self) -> Dict:
        return {
            "trades": [],
            "wins": 0,
            "losses": 0,
            "total_win_pct": 0.0,
            "total_loss_pct": 0.0,
            "peak_equity": 0.0,
            "start_equity": 0.0,
            "last_position": None,
            "consecutive_losses": 0,
            "session_start": time.time(),
            "version": "v8"
        }
    
    def save(self):
        """Save state to file."""
        try:
            with open(self.filepath, 'w') as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            log.error(f"Failed to save state: {e}")
    
    def record_trade(self, trade_data: Dict):
        """Record a completed trade."""
        self.state["trades"].append({
            **trade_data,
            "timestamp": time.time(),
            "datetime": datetime.now().isoformat()
        })
        
        if trade_data["pnl"] > 0:
            self.state["wins"] += 1
            self.state["total_win_pct"] += trade_data["pnl"]
            self.state["consecutive_losses"] = 0
        else:
            self.state["losses"] += 1
            self.state["total_loss_pct"] += trade_data["pnl"]
            self.state["consecutive_losses"] += 1
        
        self.save()
    
    def get_win_rate(self) -> float:
        """Get current win rate."""
        total = self.state["wins"] + self.state["losses"]
        return self.state["wins"] / total if total > 0 else 0.5
    
    def get_avg_win(self) -> float:
        """Get average winning trade percentage."""
        return self.state["total_win_pct"] / self.state["wins"] if self.state["wins"] > 0 else 5.0
    
    def get_avg_loss(self) -> float:
        """Get average losing trade percentage."""
        return abs(self.state["total_loss_pct"] / self.state["losses"]) if self.state["losses"] > 0 else 5.0


# ============================================
# TELEGRAM NOTIFIER (Optional)
# ============================================

class TelegramNotifier:
    """Send trade notifications via Telegram."""
    
    def __init__(self, token: str, chat_id: str):
        self.enabled = bool(token and chat_id)
        self.token = token
        self.chat_id = chat_id
        if self.enabled:
            log.info("Telegram notifications enabled")
    
    def send(self, message: str):
        """Send message to Telegram."""
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(url, json={"chat_id": self.chat_id, "text": message}, timeout=5)
        except Exception as e:
            log.debug(f"Telegram send failed: {e}")
    
    def notify_entry(self, symbol: str, price: float, score: int, signals: List[str]):
        """Notify on position entry."""
        msg = f"🟢 ENTRY: {symbol}\n"
        msg += f"Price: ${price:.4f}\n"
        msg += f"Score: {score}\n"
        msg += f"Signals: {', '.join(signals)}"
        self.send(msg)
    
    def notify_exit(self, symbol: str, pnl: float, reason: str):
        """Notify on position exit."""
        emoji = "✅" if pnl > 0 else "❌"
        msg = f"{emoji} EXIT: {symbol}\n"
        msg += f"P&L: {pnl:+.2f}%\n"
        msg += f"Reason: {reason}"
        self.send(msg)


# ============================================
# V8 RISK MANAGER (Enhanced)
# ============================================

class V8RiskManager:
    """
    Enhanced risk management with Kelly sizing, Chandelier exits, and persistence.
    V8 NEW: Loads history from state file, adaptive thresholds.
    """
    def __init__(self, state: StatePersistence):
        self.state = state
        self.start_equity = state.state.get("start_equity", 0)
        self.peak_equity = state.state.get("peak_equity", 0)
        self.last_trade_time = 0
        self.blacklist = {}
        
    def initialize(self, equity: float):
        """Initialize with starting equity."""
        if self.start_equity == 0:
            self.start_equity = equity
            self.state.state["start_equity"] = equity
        if self.peak_equity == 0 or equity > self.peak_equity:
            self.peak_equity = equity
            self.state.state["peak_equity"] = equity
        self.state.save()
        log.info(f"RiskManager: equity=${equity:.2f}, W/L={self.state.state['wins']}/{self.state.state['losses']}")
        
    def can_trade(self, current_equity: float) -> Tuple[bool, str]:
        """Check if trading is allowed."""
        # Cooldown
        if time.time() - self.last_trade_time < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (time.time() - self.last_trade_time)
            return False, f"Cooldown: {remaining:.0f}s"
        
        # Max consecutive losses
        if self.state.state["consecutive_losses"] >= MAX_CONSECUTIVE_LOSSES:
            return False, f"Max losses: {self.state.state['consecutive_losses']}"
        
        # Daily drawdown
        if self.start_equity > 0 and current_equity < self.start_equity * (1 - MAX_DAILY_DRAWDOWN):
            drawdown = ((self.start_equity - current_equity) / self.start_equity) * 100
            return False, f"Drawdown: {drawdown:.1f}%"
        
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
    
    def get_adaptive_threshold(self) -> int:
        """
        V8 NEW: Adaptive entry threshold based on win rate.
        - Losing streak: Stricter (higher threshold)
        - Winning streak: Slightly looser
        """
        win_rate = self.state.get_win_rate()
        
        if win_rate < 0.5:
            return MIN_SCORE_BASE + 15  # Stricter when losing
        elif win_rate > 0.75:
            return MIN_SCORE_BASE - 5   # Slightly looser when winning
        else:
            return MIN_SCORE_BASE
    
    def calculate_position_size(self, equity: float, data: Dict) -> float:
        """Calculate position size using Kelly Criterion with volatility adjustment."""
        total_trades = self.state.state["wins"] + self.state.state["losses"]
        
        if total_trades < 5:
            base_size = 0.15
        else:
            win_rate = self.state.get_win_rate()
            avg_win = self.state.get_avg_win()
            avg_loss = self.state.get_avg_loss()
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
        """Calculate ATR-based dynamic stops with Chandelier exit."""
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
    
    def record_trade(self, pnl_percent: float, symbol: str, signals: List[str]):
        """Record trade result for Kelly calculation and state persistence."""
        self.last_trade_time = time.time()
        self.state.record_trade({
            "symbol": symbol,
            "pnl": pnl_percent,
            "signals": signals
        })
        
        total = self.state.state["wins"] + self.state.state["losses"]
        win_rate = self.state.get_win_rate() * 100
        log.info(f"Trade: {'WIN' if pnl_percent > 0 else 'LOSS'} {pnl_percent:.2f}% | W/L: {self.state.state['wins']}/{self.state.state['losses']} ({win_rate:.0f}%)")


# ============================================
# API CLIENT
# ============================================

class DeltaAPI:
    """Delta Exchange API client with WARP proxy support."""
    
    def __init__(self, use_proxy: bool = True):
        self.session = requests.Session()
        self.use_proxy = use_proxy
        
        # Connection pooling (increased for parallel requests)
        adapter = HTTPAdapter(pool_connections=50, pool_maxsize=50)
        self.session.mount("https://", adapter)
        
        if use_proxy:
            self.session.proxies = {
                "http": f"socks5h://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}",
                "https": f"socks5h://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}"
            }
            log.info(f"Using WARP proxy: {WARP_PROXY_HOST}:{WARP_PROXY_PORT}")
        
        self._force_ipv4()
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
    
    def get_recent_trades(self, symbol: str, count: int = 100) -> List[Dict]:
        """V8 NEW: Get recent trades for order flow analysis with graceful fallback."""
        product = self.products.get(symbol, {})
        if not product:
            return []
        
        try:
            resp = self.get(f"/v2/products/{product['id']}/trades?limit={count}")
            result = resp.get("result", [])
            # V8 FIX: Graceful fallback for empty/invalid responses
            if not isinstance(result, list):
                return []
            return result
        except Exception:
            # V8 FIX: Silently handle API errors (many symbols have no trades)
            return []
    
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
    
    def place_limit_exit(self, symbol: str, side: str, size: int, current_price: float) -> Dict:
        """LIGHTNING: Place limit order for exits (reduces slippage)."""
        product = self.products.get(symbol)
        if not product:
            return {"error": f"Unknown product: {symbol}"}
        
        tick_size = product["tick_size"]
        # For sell exit, price slightly below current (aggressive fill)
        if side == "sell":
            limit_price = current_price * (1 - EXIT_LIMIT_BUFFER)
        else:
            limit_price = current_price * (1 + EXIT_LIMIT_BUFFER)
        
        rounded_price = round(limit_price / tick_size) * tick_size
        
        order = {
            "product_id": product["id"],
            "size": size,
            "side": side,
            "order_type": "limit_order",
            "limit_price": str(rounded_price),
            "time_in_force": "ioc"  # Immediate-or-cancel for fast fill
        }
        
        log.info(f"Limit EXIT {side.upper()} {size} {symbol} @ {rounded_price}")
        return self.post("/v2/orders", order)


# ============================================
# V8 SCORING ENGINE (Enhanced)
# ============================================

def calculate_v8_score(symbol: str, ticker: Dict, candles: List[Dict], 
                       orderbook: Dict, btc_ticker: Dict, eth_ticker: Dict,
                       recent_trades: List[Dict] = None,
                       indicator_cache: 'IndicatorCache' = None) -> Tuple[int, List[str], Dict]:
    """
    V8 Ultimate scoring with Order Flow Analysis.
    Max score: 200+ points
    Entry threshold: 70 points (adaptive)
    
    NEW in V8:
    - Order flow (delta volume, absorption)
    - Large trade detection
    - Indicator caching support
    """
    score = 0
    signals = []
    data = {}
    
    if len(candles) < 30:
        return 0, ["INSUFFICIENT_DATA"], {}
    
    # Core calculations (use cache if available)
    if indicator_cache:
        rsi = indicator_cache.get_rsi(symbol, candles)
        rsi_series = indicator_cache.get_rsi_series(symbol, candles)
        macd_line, macd_signal, macd_hist = indicator_cache.get_macd(symbol, candles)
        atr = indicator_cache.get_atr(symbol, candles)
    else:
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
    # TIER 0: ORDER FLOW ANALYSIS (NEW in V8 - 25 pts max)
    # ============================================
    
    if recent_trades and len(recent_trades) > 10:
        # Delta volume
        delta = calculate_delta_volume(recent_trades)
        if delta > 0:
            score += 10
            signals.append(f"DELTA+({delta:.0f})")
        
        # Delta divergence
        price_trend = float(candles[-1]["close"]) - float(candles[-5]["close"])
        delta_div = detect_delta_divergence(price_trend, delta)
        if delta_div == "BULLISH_DIVERGENCE":
            score += 25
            signals.append("DELTA_DIV+")
        elif delta_div == "BEARISH_DIVERGENCE":
            score -= 15
        data["delta"] = delta
        data["delta_divergence"] = delta_div
        
        # Large trade detection
        large_signal, large_score = detect_large_trades(recent_trades)
        score += large_score
        if large_signal != "NEUTRAL":
            signals.append(f"INST_{large_signal}")
        
        # Absorption
        if len(candles) > 0:
            absorb_signal, absorb_score = detect_absorption(
                candles[-1], 
                float(candles[-1].get("volume", 0)),
                delta,
                atr
            )
            score += absorb_score
            if absorb_signal != "NEUTRAL":
                signals.append(f"ABSORB_{absorb_signal}")
    
    # ============================================
    # TIER 1: STRONGEST SIGNALS (30 pts max)
    # ============================================
    
    # RSI Divergence (30 pts - STRONGEST)
    divergence = detect_divergence(candles, rsi_series)
    score += divergence["score"]
    if divergence["type"] == "BULLISH":
        signals.append("DIV_BULL")
    elif divergence["type"] == "BEARISH":
        signals.append("DIV_BEAR")
    data["divergence"] = divergence
    
    # Bollinger Band Squeeze + Breakout (25 pts)
    bb = detect_bb_squeeze(candles)
    score += bb["score"]
    if bb["is_squeeze"]:
        signals.append(f"SQUEEZE({bb['bandwidth']:.1f}%)")
    data["bb"] = bb
    
    # ============================================
    # TIER 2: STRONG SIGNALS (20 pts max)
    # ============================================
    
    # Real RSI Oversold (20 pts)
    if rsi < 25:
        score += 20
        signals.append(f"RSI({rsi:.0f})")
    elif rsi < 35:
        score += 15
    elif rsi < 45:
        score += 8
    
    # MACD Bullish (20 pts)
    if macd_hist > 0:
        score += 20
        signals.append("MACD+")
    
    # Hybrid Strategy (20 pts)
    regime = detect_market_regime(candles, atr)
    hybrid = hybrid_strategy(regime, rsi, bb["position"])
    score += hybrid["score"]
    if hybrid["action"] == "BUY":
        signals.append(f"{regime['strategy']}")
    data["regime"] = regime
    
    # ============================================
    # TIER 3: MEDIUM SIGNALS (15 pts max)
    # ============================================
    
    # Order Book Imbalance (15 pts)
    ob_signal, ob_imbalance = analyze_orderbook(orderbook)
    if ob_signal == "BUY_PRESSURE":
        score += 15
        signals.append(f"OB({ob_imbalance:.0%})")
    elif ob_signal == "SELL_PRESSURE":
        score -= 10
    else:
        score += 5
    
    # VWAP Analysis (15 pts)
    vwap = calculate_vwap(candles)
    score += vwap["score"]
    if vwap["above_vwap"]:
        signals.append("VWAP+")
    data["vwap"] = vwap
    
    # Funding Rate Strategy (15 pts)
    funding = analyze_funding_rate(ticker)
    score += funding["score"]
    if funding["signal"] == "CONTRARIAN_LONG":
        signals.append(f"FUND({funding['funding']:.2f}%)")
    data["funding"] = funding
    
    # Whale Detection (15 pts)
    whale = detect_whale_activity(orderbook)
    score += whale["score"]
    if whale["signal"] == "WHALE_BUYING":
        signals.append("WHALE+")
    
    # ============================================
    # TIER 4: CONFIRMATION SIGNALS (10 pts max)
    # ============================================
    
    # 24h Momentum (10 pts)
    chg = get_24h_change(ticker)
    if 5 <= chg <= 15:
        score += 10
        signals.append(f"MOM({chg:.1f}%)")
    elif 2 <= chg < 5:
        score += 7
    elif 0 < chg < 2:
        score += 3
    
    # Volume (10 pts)
    vol = get_volume(ticker)
    if vol > 10_000_000:
        score += 10
        signals.append(f"VOL(${vol/1e6:.0f}M)")
    elif vol > 5_000_000:
        score += 5
    
    # BTC/ETH Lead Signal (10 pts)
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
# MAIN TRADING BOT V8
# ============================================

class DeltaBotV8:
    """
    Main trading bot with V8 features:
    - Parallel symbol scanning
    - Indicator caching
    - State persistence
    - Order flow analysis
    """
    
    def __init__(self):
        self.api = DeltaAPI(use_proxy=True)
        self.ws = DeltaWebSocket(self.api)
        self.state = StatePersistence()
        self.risk_mgr = V8RiskManager(self.state)
        self.telegram = TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)
        self.indicator_cache = IndicatorCache()
        
        # Position tracking
        self.in_position = False
        self.position_symbol = None
        self.position_size = 0
        self.entry_price = 0
        self.entry_time = 0
        self.entry_signals = []
        self.peak_pnl = 0
        self.slippage_checked = False
        self.stops = {}
        self.last_log_time = 0  # V8 FIX: Track last log time for 100ms loop
        
    def start(self):
        """Start the trading bot."""
        log.info("="*60)
        log.info("Delta Exchange Trading Bot V8 - STARTING")
        log.info("="*60)
        log.info("NEW: Parallel scanning, caching, order flow, persistence")
        
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
            self.slippage_checked = True
            
            log.info(f"Existing position: {self.position_symbol} x{self.position_size} @ {self.entry_price}")
            
            # V8 FIX: Initialize peak_pnl from current price (not 0!)
            # Wait for WebSocket and get current ticker
            init_ticker = None
            for _retry in range(5):  # Wait up to 5s for ticker
                time.sleep(1)
                if self.ws.connected:
                    init_ticker = self.ws.get_ticker(self.position_symbol)
                    if init_ticker:
                        break
            if not init_ticker:
                # Fallback to REST API
                init_resp = self.api.get(f"/v2/tickers/{self.position_symbol}")
                init_ticker = init_resp.get("result", {})
            
            if init_ticker:
                init_price = get_price_from_ticker(init_ticker)
                if init_price > 0:
                    current_pnl = ((init_price - self.entry_price) / self.entry_price) * 100 * LEVERAGE
                    # Try to recover historical peak from state first
                    saved_peak = 0
                    if self.state.state.get("last_position"):
                        saved_peak = self.state.state["last_position"].get("peak_pnl", 0)
                    
                    # Use max of saved peak and current pnl
                    self.peak_pnl = max(saved_peak, current_pnl, 0)
                    log.info(f"V8 FIX: Initialized peak_pnl={self.peak_pnl:.2f}% (saved={saved_peak:.2f}%, current={current_pnl:.2f}%)")
        
        # Start WebSocket
        self.ws.start()
        time.sleep(5)
        
        # Main loop
        self.run()
    
    def run(self):
        """Main trading loop."""
        last_scan = 0
        
        while True:
            try:
                if not self.ws.connected:
                    log.warning("WebSocket not connected, waiting...")
                    time.sleep(5)
                    continue
                
                if self.in_position:
                    self.manage_position()
                else:
                    if time.time() - last_scan >= SCAN_INTERVAL:
                        self.scan_for_entries_parallel()
                        last_scan = time.time()
                
                time.sleep(0.025)  # LIGHTNING: 25ms loop (40 checks/sec)
                
            except KeyboardInterrupt:
                log.info("Shutting down...")
                self.state.save()
                break
            except Exception as e:
                log.error(f"Main loop error: {e}")
                time.sleep(5)
    
    def filter_active_symbols(self, tickers: Dict) -> List[str]:
        """
        V8 NEW: Pre-filter symbols by volume to reduce from 164 to ~30.
        """
        active = []
        for symbol, ticker in tickers.items():
            if not symbol.endswith("USD"):
                continue
            if symbol in ["BTCUSD", "ETHUSD"]:
                continue
            if symbol not in self.api.products:
                continue
            
            turnover = float(ticker.get("turnover_usd", 0))
            if turnover >= MIN_TURNOVER_USD:
                active.append(symbol)
        
        return active
    
    def analyze_symbol(self, symbol: str, ticker: Dict, btc_ticker: Dict, eth_ticker: Dict) -> Tuple[str, int, List[str], Dict]:
        """Analyze a single symbol (for parallel execution)."""
        try:
            if self.risk_mgr.is_blacklisted(symbol):
                return (symbol, 0, ["BLACKLISTED"], {})
            
            # Fetch data (REST calls)
            candles = self.api.get_candles(symbol, "5m", 50)
            orderbook = self.api.get_orderbook(symbol)
            recent_trades = self.api.get_recent_trades(symbol, 100)
            
            if not candles or len(candles) < 30:
                return (symbol, 0, ["NO_CANDLES"], {})
            
            # Calculate V8 score with order flow
            score, signals, data = calculate_v8_score(
                symbol, ticker, candles, orderbook, btc_ticker, eth_ticker,
                recent_trades, self.indicator_cache
            )
            
            return (symbol, score, signals, data)
        except Exception as e:
            log.debug(f"Error analyzing {symbol}: {e}")
            return (symbol, 0, [f"ERROR:{e}"], {})
    
    def scan_for_entries_parallel(self):
        """
        V8 NEW: Parallel symbol scanning using ThreadPoolExecutor.
        10x faster than sequential!
        """
        equity = self.api.get_equity()
        
        can_trade, reason = self.risk_mgr.can_trade(equity)
        if not can_trade:
            return
        
        tickers = self.ws.get_all_tickers()
        if not tickers:
            return
        
        btc_ticker = tickers.get("BTCUSD", {})
        eth_ticker = tickers.get("ETHUSD", {})
        
        # Pre-filter by volume (reduces 164 -> ~30)
        active_symbols = self.filter_active_symbols(tickers)
        log.debug(f"Scanning {len(active_symbols)} active symbols (volume > ${MIN_TURNOVER_USD/1e6}M)")
        
        # Parallel analysis
        best_score = 0
        best_symbol = None
        best_signals = []
        best_data = {}
        
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as executor:
            futures = {
                executor.submit(
                    self.analyze_symbol, 
                    symbol, 
                    tickers[symbol], 
                    btc_ticker, 
                    eth_ticker
                ): symbol 
                for symbol in active_symbols
            }
            
            for future in as_completed(futures):
                symbol, score, signals, data = future.result()
                
                if score > best_score:
                    threshold = self.risk_mgr.get_adaptive_threshold()
                    if score >= threshold:
                        best_score = score
                        best_symbol = symbol
                        best_signals = signals
                        best_data = data
        
        # Enter best opportunity
        if best_symbol:
            ticker = tickers[best_symbol]
            self.enter_position(best_symbol, ticker, best_score, best_signals, best_data, equity)
    
    def enter_position(self, symbol: str, ticker: Dict, score: int, 
                       signals: List[str], data: Dict, equity: float):
        """Enter a new position."""
        price = get_price_from_ticker(ticker)
        if price <= 0:
            return
        
        product = self.api.products[symbol]
        
        # Calculate position size
        size_pct = self.risk_mgr.calculate_position_size(equity, data)
        notional = equity * LEVERAGE * size_pct
        size = int(notional / (price * product["contract_value"]))
        size = max(1, size)
        
        # Calculate stops
        self.stops = self.risk_mgr.calculate_stops(price, data)
        
        threshold = self.risk_mgr.get_adaptive_threshold()
        log.info("="*50)
        log.info(f"ENTRY: {symbol} Score={score} (Threshold={threshold})")
        log.info(f"Signals: {signals}")
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
            self.entry_signals = signals
            self.peak_pnl = 0
            self.slippage_checked = False
            self.risk_mgr.blacklist_symbol(symbol)
            
            # Telegram notification
            self.telegram.notify_entry(symbol, price, score, signals)
            
            # V8 FIX: Persist position info for restart recovery
            self.state.state["last_position"] = {
                "symbol": symbol,
                "entry_price": price,
                "peak_pnl": 0,
                "entry_time": time.time()
            }
            self.state.save()
            
            log.info(f"Order placed: {resp.get('result', {}).get('id', 'unknown')}")
        else:
            log.error(f"Order failed: {resp}")
    
    def manage_position(self):
        """Manage open position."""
        ticker = self.ws.get_ticker(self.position_symbol)
        if not ticker:
            return
        
        price = get_price_from_ticker(ticker)
        if price <= 0:
            return
        
        pnl = ((price - self.entry_price) / self.entry_price) * 100 * LEVERAGE
        self.peak_pnl = max(self.peak_pnl, pnl)
        
        # V8 FIX: Persist peak_pnl for restart recovery
        if self.state.state.get("last_position"):
            if self.peak_pnl > self.state.state["last_position"].get("peak_pnl", 0):
                self.state.state["last_position"]["peak_pnl"] = self.peak_pnl
                self.state.save()
        
        time_in_trade = time.time() - self.entry_time
        
        # Slippage check
        if time_in_trade >= SLIPPAGE_CHECK_DELAY and not self.slippage_checked:
            self.slippage_checked = True
            if pnl < MAX_IMMEDIATE_LOSS:
                log.warning(f"Slippage exit! P&L={pnl:.2f}%")
                self.close_position("SLIPPAGE", pnl)
                return
        
        # Stop Loss
        if pnl <= self.stops["stop_loss"]:
            self.close_position("STOP", pnl)
            return
        
        # Take Profit
        if pnl >= self.stops["take_profit"]:
            self.close_position("PROFIT", pnl)
            return
        
        # Trailing Stop
        if self.peak_pnl >= self.stops["trail_start"]:
            trail_level = self.peak_pnl - self.stops["trail_distance"]
            if pnl <= trail_level:
                self.close_position(f"TRAIL({self.peak_pnl:.1f}%)", pnl)
                return
        
        # Status log (V8 FIX: Time-based 5s logging for 100ms loop)
        now = time.time()
        if now - self.last_log_time >= 3:  # LIGHTNING: 3s logging
            self.last_log_time = now
            log.info(f"[{self.position_symbol}] P&L={pnl:.2f}% Peak={self.peak_pnl:.2f}%")
    
    def close_position(self, reason: str, pnl: float):
        """Close the current position."""
        log.info("="*50)
        log.info(f"EXIT: {self.position_symbol} | {reason} | P&L={pnl:.2f}%")
        log.info("="*50)
        
        # LIGHTNING: Try limit order first (less slippage), fallback to market
        ticker = self.ws.get_ticker(self.position_symbol)
        current_price = get_price_from_ticker(ticker) if ticker else 0
        
        if current_price > 0 and EXIT_ORDER_TYPE == "limit":
            resp = self.api.place_limit_exit(self.position_symbol, "sell", self.position_size, current_price)
            if not resp.get("success"):
                log.warning("Limit exit failed, using market order")
                self.api.place_market_order(self.position_symbol, "sell", self.position_size)
        else:
            self.api.place_market_order(self.position_symbol, "sell", self.position_size)
        
        # Record trade with persistence
        self.risk_mgr.record_trade(pnl, self.position_symbol, self.entry_signals)
        
        # Telegram notification
        self.telegram.notify_exit(self.position_symbol, pnl, reason)
        
        # Log equity
        equity = self.api.get_equity()
        log.info(f"Equity: ${equity:.2f} (Rs.{equity * 85:.0f})")
        
        # V8 FIX: Clear persisted position
        self.state.state["last_position"] = None
        self.state.save()
        
        # Reset state
        self.in_position = False
        self.position_symbol = None
        self.position_size = 0
        self.entry_price = 0
        self.entry_signals = []
        self.peak_pnl = 0


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    bot = DeltaBotV8()
    bot.start()

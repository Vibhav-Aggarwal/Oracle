#!/usr/bin/env python3
"""
ORACLE BOT V2 - Complete Multi-Exchange Trading System
ALL 90+ Features from V1-V10 Implemented
"""

import os
import sys
import json
MODE_FILE = "/home/vibhavaggarwal/trading_mode.json"

def get_trading_mode():
    """Read trading mode from file, defaults to PAPER"""
    try:
        if os.path.exists(MODE_FILE):
            with open(MODE_FILE, "r") as f:
                data = json.load(f)
                mode = data.get("mode", "paper").upper()
                if mode in ["PAPER", "LIVE"]:
                    return mode
    except (OSError, json.JSONDecodeError, KeyError) as e:
        pass  # Silent fallback to PAPER mode
    return "PAPER"
import time
import hmac
import hashlib
import logging
import requests
import threading
import websocket
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import deque

# Import metrics module
try:
    from oracle_metrics import metrics as bot_metrics
    METRICS_ENABLED = True
except ImportError:
    METRICS_ENABLED = False
    bot_metrics = None

# Import custom modules
try:
    from indicators_v11 import calculate_all_indicators, calculate_dynamic_sl_tp, calculate_atr_percent
    from sentiment_v11 import get_combined_sentiment, score_fear_greed
except ImportError:
    print("WARNING: Custom modules not found")

# ============================================================================
# LOGGING SETUP
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.getenv("ORACLE_LOG_FILE", "/home/vibhavaggarwal/oracle_bot.log")),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("OracleBot")

# ============================================================================
# FEE STRUCTURES PER EXCHANGE
# ============================================================================

class FeeStructure:
    """Fee calculation for each exchange"""

    DELTA = {
        "maker": 0.0002, "taker": 0.0005, "gst": 0.18,
        "funding_interval": 8, "leverage_max": 100
    }

    ZEBPAY = {
        "maker": 0.0015, "taker": 0.0025, "gst": 0.18,
        "tds": 0.01, "withdrawal_inr": 10, "withdrawal_crypto_pct": 0.0005
    }

    COINBASE = {
        "maker": 0.004, "taker": 0.006, "gst": 0, "withdrawal_crypto": 0
    }

    @classmethod
    def calculate_delta_fee(cls, size_usd: float, is_taker: bool = True) -> float:
        base_rate = cls.DELTA["taker"] if is_taker else cls.DELTA["maker"]
        fee = size_usd * base_rate
        return fee * (1 + cls.DELTA["gst"])

    @classmethod
    def calculate_zebpay_fee(cls, size_inr: float, is_taker: bool = True, is_sell: bool = False) -> float:
        base_rate = cls.ZEBPAY["taker"] if is_taker else cls.ZEBPAY["maker"]
        fee = size_inr * base_rate * (1 + cls.ZEBPAY["gst"])
        return fee + (size_inr * cls.ZEBPAY["tds"] if is_sell else 0)

    @classmethod
    def calculate_coinbase_fee(cls, size_usd: float, is_taker: bool = True) -> float:
        return size_usd * (cls.COINBASE["taker"] if is_taker else cls.COINBASE["maker"])

    @classmethod
    def calculate_profit(cls, exchange: str, entry_price: float, exit_price: float,
                        size: float, direction: str, leverage: int = 1) -> dict:
        pnl_pct = (exit_price - entry_price) / entry_price if direction == "LONG" else (entry_price - exit_price) / entry_price
        gross_pnl = pnl_pct * size * leverage

        if exchange == "Delta":
            total_fees = cls.calculate_delta_fee(size) * 2
        elif exchange == "Zebpay":
            total_fees = cls.calculate_zebpay_fee(size) + cls.calculate_zebpay_fee(size, is_sell=(direction == "LONG"))
        else:
            total_fees = cls.calculate_coinbase_fee(size) * 2

        net_pnl = gross_pnl - total_fees
        return {
            "gross_pnl": round(gross_pnl, 2),
            "total_fees": round(total_fees, 4),
            "net_pnl": round(net_pnl, 2),
            "roi_pct": round((net_pnl / size) * 100, 2),
            "breakeven_pct": round((total_fees / size / leverage) * 100, 3)
        }

# ============================================================================
# CONFIGURATION
# ============================================================================

TRADING_MODE = get_trading_mode()  # Dynamic from dashboard
PAPER_INITIAL_BALANCE = 1000.0
MAX_POSITIONS = 5
BASE_POSITION_SIZE_PCT = 0.02  # 2% risk per trade (was 20%)
LEVERAGE = 5  # Reduced from 20x for safety
MIN_SCORE_THRESHOLD = 55  # More selective (was 40)
COOLDOWN_AFTER_EXIT = 30
COIN_BLACKLIST_TIME = 3600  # 1 hour blacklist (was 3 min)
MAX_CONSECUTIVE_LOSSES = 3
DAILY_DRAWDOWN_LIMIT = 10.0

# New features
MAX_VOLATILITY_FILTER = 20.0  # Skip if ATR > 20%
IMMEDIATE_LOSS_EXIT = -3.0
# ATR-based risk management
ATR_SL_MULTIPLIER = 3.0  # Wider stops (was 2.0)      # Stop loss at 2x ATR
ATR_TP_MULTIPLIER = 4.5  # Better R:R (was 3.0)      # Take profit at 3x ATR

# Trailing stop configuration
TRAIL_START_PCT = 3.0        # Start trailing at +3%
MIN_TRAIL_DIST = 1.0         # Minimum trail distance 1%
MAX_TRAIL_DIST = 3.0         # Maximum trail distance 3%

# Max volatility (alias)
MAX_VOLATILITY = 20.0        # Skip if ATR > 20%
    # Emergency exit at -3%
SLIPPAGE_MAX_SPREAD = 0.5     # Max 0.5% spread
ADAPTIVE_THRESHOLD_ENABLED = True
TELEGRAM_ENABLED = False
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

PPO_SERVER = "http://10.0.0.74:5002"
FINBERT_SERVER = "http://10.0.0.74:5001"
STATE_FILE = "/home/vibhavaggarwal/oracle_state.json"
WEBHOOK_PORT = 8080

# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class Position:
    symbol: str
    exchange: str
    direction: str
    entry_price: float
    size_usd: float
    leverage: int
    stop_loss: float
    take_profit: float
    entry_time: str
    entry_signals: List[str]
    trailing_active: bool = False
    highest_pnl: float = 0.0
    entry_atr: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        # Handle missing fields gracefully
        defaults = {"trailing_active": False, "highest_pnl": 0.0, "entry_atr": 0.0}
        for k, v in defaults.items():
            if k not in data:
                data[k] = v
        return cls(**data)

@dataclass
class Trade:
    """Completed trade record for history"""
    symbol: str
    exchange: str
    direction: str
    entry_price: float
    exit_price: float
    size_usd: float
    gross_pnl: float
    fees: float
    net_pnl: float
    entry_time: str
    exit_time: str
    exit_reason: str
    hold_duration_mins: int

    def to_dict(self) -> dict:
        return asdict(self)

# ============================================================================
# TELEGRAM NOTIFICATIONS
# ============================================================================

class TelegramNotifier:
    """Send notifications via Telegram"""

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)

    def send(self, message: str):
        if not self.enabled:
            return
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            requests.post(url, data={"chat_id": self.chat_id, "text": message, "parse_mode": "HTML"}, timeout=5)
        except Exception as e:
            logger.warning(f"Telegram send failed: {e}")

    def send_trade_open(self, pos: Position):
        msg = f"<b>OPENED {pos.direction}</b>\n"
        msg += f"Symbol: {pos.symbol}\n"
        msg += f"Entry: ${pos.entry_price:.2f}\n"
        msg += f"Size: ${pos.size_usd:.0f} ({pos.leverage}x)\n"
        msg += f"SL: {pos.stop_loss*100:.1f}% | TP: {pos.take_profit*100:.1f}%"
        self.send(msg)

    def send_trade_close(self, trade: Trade):
        emoji = "+" if trade.net_pnl >= 0 else ""
        msg = f"<b>CLOSED {trade.direction}</b>\n"
        msg += f"Symbol: {trade.symbol}\n"
        msg += f"P&L: ${emoji}{trade.net_pnl:.2f} ({trade.exit_reason})\n"
        msg += f"Duration: {trade.hold_duration_mins} mins"
        self.send(msg)

    def send_message(self, message: str):
        """Alias for send - compatibility"""
        return self.send(message)

    def send_trade_alert(self, action: str, symbol: str, price: float, details: str = ""):
        """Send trade alert"""
        emoji = "🟢" if action.upper() in ["LONG", "BUY"] else "🔴"
        msg = f"{emoji} <b>{action.upper()}</b>\nSymbol: {symbol}\nPrice: ${price:.2f}"
        if details:
            msg += f"\n{details}"
        self.send(msg)

    def send_daily_summary(self, balance: float, pnl: float, wins: int, losses: int):
        """Send daily summary"""
        wr = (wins/(wins+losses)*100) if (wins+losses) > 0 else 0
        emoji = "📈" if pnl >= 0 else "📉"
        msg = f"<b>📊 DAILY SUMMARY</b>\nBalance: ${balance:.2f}\nP&L: {emoji} ${pnl:+.2f}\nWin Rate: {wr:.1f}%"
        self.send(msg)


# ============================================================================
# WEBSOCKET TICKER (Real-time)
# ============================================================================

class DeltaWebSocket:
    """Real-time WebSocket connection for Delta Exchange"""

    WS_URL = "wss://socket.delta.exchange"

    def __init__(self):
        self.ws = None
        self.tickers: Dict[str, dict] = {}
        self.connected = False
        self.thread = None

    def on_message(self, ws, message):
        try:
            data = json.loads(message)
            if data.get("type") == "ticker":
                symbol = data.get("symbol")
                if symbol:
                    self.tickers[symbol] = {
                        "price": float(data.get("mark_price", 0)),
                        "bid": float(data.get("best_bid", 0)),
                        "ask": float(data.get("best_ask", 0)),
                        "timestamp": time.time()
                    }
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # Silently ignore malformed WebSocket messages

    def on_error(self, ws, error):
        logger.warning(f"WebSocket error: {error}")

    def on_close(self, ws, code, msg):
        self.connected = False
        logger.info("WebSocket closed")

    def on_open(self, ws):
        self.connected = True
        logger.info("WebSocket connected")
        # Subscribe to tickers
        symbols = ["BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"]
        for sym in symbols:
            ws.send(json.dumps({"type": "subscribe", "payload": {"channels": [{"name": "ticker", "symbols": [sym]}]}}))

    def start(self):
        def run():
            self.ws = websocket.WebSocketApp(
                self.WS_URL,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close,
                on_open=self.on_open
            )
            self.ws.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()

    def get_ticker(self, symbol: str) -> Optional[dict]:
        ticker = self.tickers.get(symbol)
        if ticker and time.time() - ticker.get("timestamp", 0) < 5:
            return ticker
        return None

    def connect(self):
        """Start WebSocket connection"""
        self.start()

    def subscribe(self, symbols: list):
        """Subscribe to symbols"""
        if self.ws and self.connected:
            for sym in symbols:
                try:
                    self.ws.send(json.dumps({
                        "type": "subscribe",
                        "payload": {"channels": [{"name": "ticker", "symbols": [sym]}]}
                    }))
                except (Exception,):
                    pass  # Ignore subscribe failures


# ============================================================================
# TICKER CACHE (Low-latency)
# ============================================================================

class TickerCache:
    """Cache tickers with TTL for low-latency access"""

    def __init__(self, ttl: float = 0.5):
        self.cache: Dict[str, Tuple[dict, float]] = {}
        self.ttl = ttl

    def get(self, key: str) -> Optional[dict]:
        if key in self.cache:
            data, ts = self.cache[key]
            if time.time() - ts < self.ttl:
                return data
        return None

    def set(self, key: str, data: dict):
        self.cache[key] = (data, time.time())

# ============================================================================
# TRADINGVIEW WEBHOOK HANDLER
# ============================================================================

class TradingViewWebhook(BaseHTTPRequestHandler):
    bot = None

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body)
            logger.info(f"TradingView Alert: {data}")

            if self.bot:
                symbol = data.get("symbol", "")
                action = data.get("action", "").upper()
                exchange = data.get("exchange", "Delta")

                if action in ["LONG", "SHORT"]:
                    self.bot.handle_tv_signal(exchange, symbol, action, data)
                elif action == "CLOSE":
                    self.bot.handle_tv_close(exchange, symbol)

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            self.send_response(400)
            self.end_headers()

    def log_message(self, format, *args):
        pass

# ============================================================================
# EXCHANGE BASE CLASS
# ============================================================================

class Exchange(ABC):
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.session = requests.Session()

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @abstractmethod
    def get_ticker(self, symbol: str) -> dict:
        pass

    @abstractmethod
    def get_candles(self, symbol: str, resolution: str, limit: int) -> List[dict]:
        pass

    @abstractmethod
    def get_orderbook(self, symbol: str) -> dict:
        pass

    @abstractmethod
    def get_recent_trades(self, symbol: str, limit: int) -> List[dict]:
        """NEW: Get recent trades for trade flow analysis"""
        pass

    @abstractmethod
    def get_symbols(self) -> List[str]:
        pass

    @abstractmethod
    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market", price: float = None) -> dict:
        pass

    @abstractmethod
    def get_balance(self) -> dict:
        pass

    def calculate_fee(self, size: float, is_taker: bool = True) -> float:
        return FeeStructure.calculate_delta_fee(size, is_taker)

    def check_spread(self, symbol: str) -> float:
        """Check bid-ask spread as percentage"""
        ticker = self.get_ticker(symbol)
        bid = ticker.get("bid", 0)
        ask = ticker.get("ask", 0)
        if bid > 0 and ask > 0:
            return ((ask - bid) / bid) * 100
        return 0

# ============================================================================
# DELTA EXCHANGE
# ============================================================================

class DeltaExchange(Exchange):
    BASE_URL = "https://api.delta.exchange/v2"
    _cached_symbols = None
    _cache_time = 0
    CACHE_TTL = 3600  # Refresh every hour

    @classmethod
    def get_all_symbols(cls) -> List[str]:
        """Fetch ALL tradeable products from Delta API"""
        import time as _time
        now = _time.time()
        
        if cls._cached_symbols and (now - cls._cache_time) < cls.CACHE_TTL:
            return cls._cached_symbols
        
        try:
            r = requests.get(f"{cls.BASE_URL}/products", timeout=10)
            data = r.json()
            
            # Get perpetual futures AND spot (exclude options - they have expiry)
            pairs = [p["symbol"] for p in data.get("result", [])
                     if p.get("state") == "live" 
                     ]
            
            if pairs:
                cls._cached_symbols = pairs
                cls._cache_time = now
                logger.info(f"Delta: Loaded {len(pairs)} pairs (ALL live)")
                return pairs
                
        except Exception as e:
            logger.warning(f"Delta symbol fetch failed: {e}")
        
        return ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
                "ADAUSDT", "LINKUSDT", "AVAXUSDT", "DOTUSDT", "ATOMUSDT"]

    @property
    def SYMBOLS(self) -> List[str]:
        return self.get_all_symbols()

    @property
    def name(self) -> str:
        return "Delta"

    def _sign(self, method: str, path: str, payload: str = "") -> dict:
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + path + payload
        signature = hmac.new(self.api_secret.encode(), signature_data.encode(), hashlib.sha256).hexdigest()
        return {"api-key": self.api_key, "timestamp": timestamp, "signature": signature, "Content-Type": "application/json"}

    def get_ticker(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.BASE_URL}/tickers/{symbol}", timeout=5)
            data = r.json()
            if "result" in data:
                result = data["result"]
                return {
                    "symbol": symbol,
                    "price": float(result.get("mark_price", 0)),
                    "bid": float(result.get("best_bid", 0)),
                    "ask": float(result.get("best_ask", 0)),
                    "volume": float(result.get("volume", 0))
                }
        except Exception as e:
            logger.error(f"Delta ticker error: {e}")
        return {"symbol": symbol, "price": 0, "bid": 0, "ask": 0}

    def get_candles(self, symbol: str, resolution: str = "1h", limit: int = 100) -> List[dict]:
        try:
            end = int(time.time())
            res_map = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
            interval = res_map.get(resolution, 3600)
            start = end - (limit * interval)

            r = self.session.get(
                f"{self.BASE_URL}/history/candles",
                params={"symbol": symbol, "resolution": resolution, "start": start, "end": end},
                timeout=10
            )
            data = r.json()

            candles = []
            for c in data.get("result", []):
                candles.append({
                    "time": c.get("time"),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "volume": float(c.get("volume", 0))
                })
            return candles
        except Exception as e:
            logger.error(f"Delta candles error: {e}")
        return []

    def get_orderbook(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.BASE_URL}/l2orderbook/{symbol}", timeout=5)
            data = r.json()
            result = data.get("result", {})
            return {"buy": result.get("buy", []), "sell": result.get("sell", [])}
        except (requests.RequestException, json.JSONDecodeError, KeyError):
            return {"buy": [], "sell": []}

    def get_recent_trades(self, symbol: str, limit: int = 50) -> List[dict]:
        """Get recent trades for trade flow analysis"""
        try:
            r = self.session.get(f"{self.BASE_URL}/trades/{symbol}", params={"limit": limit}, timeout=5)
            data = r.json()
            trades = []
            for t in data.get("result", []):
                trades.append({
                    "price": float(t.get("price", 0)),
                    "size": float(t.get("size", 0)),
                    "side": t.get("buyer_role", "taker"),
                    "time": t.get("timestamp")
                })
            return trades
        except (requests.RequestException, json.JSONDecodeError, KeyError):
            return []

    def get_symbols(self) -> List[str]:
        return self.SYMBOLS

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market", price: float = None) -> dict:
        if TRADING_MODE == "PAPER":
            return {"status": "paper", "order_id": f"paper_{int(time.time())}"}

        path = "/orders"
        payload = {"product_symbol": symbol, "size": size, "side": side.lower(), "order_type": order_type}
        if order_type == "limit" and price:
            payload["limit_price"] = str(price)

        payload_str = json.dumps(payload)
        headers = self._sign("POST", path, payload_str)

        try:
            r = self.session.post(f"{self.BASE_URL}{path}", headers=headers, data=payload_str, timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e)}

    def get_balance(self) -> dict:
        if TRADING_MODE == "PAPER":
            return {"available": PAPER_INITIAL_BALANCE}
        return {"available": 0}

    def calculate_fee(self, size: float, is_taker: bool = True) -> float:
        return FeeStructure.calculate_delta_fee(size, is_taker)

    def cancel_order(self, order_id: str) -> dict:
        """Cancel an order"""
        if TRADING_MODE == "PAPER":
            return {"status": "cancelled", "order_id": order_id}
        path = f"/orders/{order_id}"
        headers = self._sign("DELETE", path)
        try:
            r = self.session.delete(f"{self.BASE_URL}{path}", headers=headers, timeout=10)
            return r.json()
        except Exception as e:
            return {"error": str(e)}


# ============================================================================
# ZEBPAY EXCHANGE
# ============================================================================

class ZebpayExchange(Exchange):
    BASE_URL = "https://www.zebapi.com/pro/v1"
    _cached_symbols = None
    _cache_time = 0
    CACHE_TTL = 3600  # Refresh symbols every hour

    @classmethod
    def get_all_symbols(cls) -> List[str]:
        """Fetch ALL trading pairs from Zebpay API"""
        import time as _time
        now = _time.time()
        
        if cls._cached_symbols and (now - cls._cache_time) < cls.CACHE_TTL:
            return cls._cached_symbols
        
        try:
            r = requests.get(f"{cls.BASE_URL}/market", timeout=10)
            data = r.json()
            
            # Get ALL pairs (not just with volume)
            pairs = [d["pair"] for d in data]
            
            if pairs:
                cls._cached_symbols = pairs
                cls._cache_time = now
                logger.info(f"Zebpay: Loaded {len(pairs)} pairs (ALL 767)")
                return pairs
                
        except Exception as e:
            logger.warning(f"Zebpay symbol fetch failed: {e}")
        
        return ["BTC-INR", "ETH-INR", "SOL-INR", "XRP-INR", "DOGE-INR",
                "SHIB-INR", "MATIC-INR", "ADA-INR", "DOT-INR", "AVAX-INR"]

    @property
    def SYMBOLS(self) -> List[str]:
        return self.get_all_symbols()

    @property
    def name(self) -> str:
        return "Zebpay"

    def get_ticker(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.BASE_URL}/market/{symbol}/ticker", timeout=5)
            data = r.json()
            return {"symbol": symbol, "price": float(data.get("lastTradePrice", 0)), "bid": 0, "ask": 0}
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            return {"symbol": symbol, "price": 0, "bid": 0, "ask": 0}

    def get_candles(self, symbol: str, resolution: str = "1h", limit: int = 100) -> List[dict]:
        return []

    def get_orderbook(self, symbol: str) -> dict:
        return {"buy": [], "sell": []}

    def get_recent_trades(self, symbol: str, limit: int = 50) -> List[dict]:
        return []

    def get_symbols(self) -> List[str]:
        return self.get_all_symbols()

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market", price: float = None) -> dict:
        return {"status": "paper"}

    def get_balance(self) -> dict:
        return {"available": PAPER_INITIAL_BALANCE}

    def calculate_fee(self, size: float, is_taker: bool = True) -> float:
        return FeeStructure.calculate_zebpay_fee(size, is_taker)

# ============================================================================
# COINBASE EXCHANGE
# ============================================================================

class CoinbaseExchange(Exchange):
    BASE_URL = "https://api.exchange.coinbase.com"
    _cached_symbols = None
    _cache_time = 0
    CACHE_TTL = 3600  # Refresh every hour

    @classmethod
    def get_all_symbols(cls) -> List[str]:
        """Fetch ALL online trading pairs from Coinbase API"""
        import time as _time
        now = _time.time()
        
        if cls._cached_symbols and (now - cls._cache_time) < cls.CACHE_TTL:
            return cls._cached_symbols
        
        try:
            r = requests.get(f"{cls.BASE_URL}/products", timeout=10)
            data = r.json()
            
            # Get ALL online pairs (USD, USDC, EUR, etc.)
            pairs = [p["id"] for p in data if p.get("status") == "online"]
            
            if pairs:
                cls._cached_symbols = pairs
                cls._cache_time = now
                logger.info(f"Coinbase: Loaded {len(pairs)} pairs (ALL 767)")
                return pairs
                
        except Exception as e:
            logger.warning(f"Coinbase symbol fetch failed: {e}")
        
        return ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD",
                "ADA-USD", "LINK-USD", "AVAX-USD", "DOT-USD", "ATOM-USD"]

    @property
    def SYMBOLS(self) -> List[str]:
        return self.get_all_symbols()

    @property
    def name(self) -> str:
        return "Coinbase"

    def get_ticker(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.BASE_URL}/products/{symbol}/ticker", timeout=5)
            data = r.json()
            return {
                "symbol": symbol,
                "price": float(data.get("price", 0)),
                "bid": float(data.get("bid", 0)),
                "ask": float(data.get("ask", 0))
            }
        except (requests.RequestException, json.JSONDecodeError, ValueError):
            return {"symbol": symbol, "price": 0, "bid": 0, "ask": 0}

    def get_candles(self, symbol: str, resolution: str = "1h", limit: int = 100) -> List[dict]:
        return []

    def get_orderbook(self, symbol: str) -> dict:
        return {"buy": [], "sell": []}

    def get_recent_trades(self, symbol: str, limit: int = 50) -> List[dict]:
        return []

    def get_symbols(self) -> List[str]:
        return self.get_all_symbols()

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market", price: float = None) -> dict:
        return {"status": "paper"}

    def get_balance(self) -> dict:
        return {"available": PAPER_INITIAL_BALANCE}

    def calculate_fee(self, size: float, is_taker: bool = True) -> float:
        return FeeStructure.calculate_coinbase_fee(size, is_taker)

# ============================================================================
# STATE PERSISTENCE
# ============================================================================

class StatePersistence:
    def __init__(self, filepath: str = STATE_FILE):
        self.filepath = filepath
        self.state = self._load()

    def _load(self) -> dict:
        try:
            with open(self.filepath, "r") as f:
                return json.load(f)
        except FileNotFoundError:
            logger.info(f"State file not found, using defaults")
            return self._default_state()
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"State load failed: {e}")
            return self._default_state()

    def _default_state(self) -> dict:
        return {
            "balance": PAPER_INITIAL_BALANCE,
            "positions": {},
            "trades": [],  # Trade history
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "consecutive_losses": 0,
            "daily_pnl": 0.0,
            "last_reset": datetime.now().strftime("%Y-%m-%d"),
            "blacklist": {},
            "cooldowns": {},
            "avg_win": 0.0,
            "avg_loss": 0.0
        }

    def save(self):
        try:
            with open(self.filepath, "w") as f:
                json.dump(self.state, f, indent=2)
        except Exception as e:
            logger.error(f"State save error: {e}")

    def get(self, key: str, default=None):
        return self.state.get(key, default)

    def set(self, key: str, value):
        self.state[key] = value
        self.save()

    def add_position(self, position: Position):
        self.state["positions"][position.symbol] = position.to_dict()
        self.save()

    def remove_position(self, symbol: str):
        if symbol in self.state["positions"]:
            del self.state["positions"][symbol]
            self.save()

    def get_positions(self) -> Dict[str, Position]:
        return {k: Position.from_dict(v) for k, v in self.state.get("positions", {}).items()}

    def add_trade(self, trade: Trade):
        """Add completed trade to history"""
        trades = self.state.get("trades", [])
        trades.append(trade.to_dict())
        # Keep last 100 trades
        self.state["trades"] = trades[-100:]
        self.save()

    def update_avg_metrics(self):
        """Calculate average win/loss from trade history"""
        trades = self.state.get("trades", [])
        wins = [t["net_pnl"] for t in trades if t["net_pnl"] > 0]
        losses = [t["net_pnl"] for t in trades if t["net_pnl"] < 0]

        self.state["avg_win"] = sum(wins) / len(wins) if wins else 0
        self.state["avg_loss"] = sum(losses) / len(losses) if losses else 0
        self.save()

# ============================================================================
# PPO CLIENT
# ============================================================================

def get_ppo_recommendation(candles: List[dict], balance: float) -> dict:
    try:
        data = [[c["open"], c["high"], c["low"], c["close"], c["volume"]] for c in candles[-20:]]
        r = requests.post(f"{PPO_SERVER}/predict/candles", json={"candles": data, "balance": balance}, timeout=5)
        if r.status_code == 200:
            return r.json()
    except (requests.RequestException, json.JSONDecodeError, KeyError, IndexError):
        pass
    return {"position_size": 0, "stop_loss": 0.05, "take_profit": 0.10}

# ============================================================================
# ORACLE BOT MAIN CLASS
# ============================================================================

class OracleBot:
    def __init__(self):
        self.exchanges: Dict[str, Exchange] = {}
        self.state = StatePersistence()
        self.running = False
        self._dp_cache = {}  # Data puller cache (loaded once per scan)
        self._candle_cache = {}  # Candle cache (60s TTL)
        self._last_prices = {}  # For price change detection
        self.ticker_cache = TickerCache(ttl=0.5)
        self.websocket = DeltaWebSocket()
        self.telegram = TelegramNotifier(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
        self.webhook_server = None

        self._init_exchanges()
        logger.info(f"Oracle Bot V2 initialized - Mode: {TRADING_MODE}")
        logger.info(f"Exchanges: {list(self.exchanges.keys())}")

    def _init_exchanges(self):
        self.exchanges["Delta"] = DeltaExchange(
            os.getenv("DELTA_API_KEY", ""),
            os.getenv("DELTA_API_SECRET", "")
        )
        self.exchanges["Zebpay"] = ZebpayExchange(
            os.getenv("ZEBPAY_API_KEY", "9iVCqNhOEjxo3YTAm1MhU_249_qCgUfPav6XYCtQVvc"),
            os.getenv("ZEBPAY_API_SECRET", "sXV8uWCeOugJ-SNfre47XMe2N-NeciJ7BvTQCVrndQEEuo3QGWw4ZnhLSTMMIsGsf-bZGXm85351HGg9ibH21Q")
        )
        self.exchanges["Coinbase"] = CoinbaseExchange(
            os.getenv("COINBASE_API_KEY", ""),
            os.getenv("COINBASE_API_SECRET", "")
        )

    def start_webhook_server(self):
        try:
            TradingViewWebhook.bot = self
            self.webhook_server = HTTPServer(('0.0.0.0', WEBHOOK_PORT), TradingViewWebhook)
            thread = threading.Thread(target=self.webhook_server.serve_forever, daemon=True)
            thread.start()
            logger.info(f"Webhook server started on port {WEBHOOK_PORT}")
        except Exception as e:
            logger.warning(f"Webhook server failed: {e}")

    def handle_tv_signal(self, exchange_name: str, symbol: str, direction: str, data: dict):
        exchange = self.exchanges.get(exchange_name)
        if not exchange:
            return
        candles = exchange.get_candles(symbol, "1h", 50)
        self.open_position(exchange, symbol, direction, ["TV_SIGNAL"], candles, 0.05, 0.10)

    def handle_tv_close(self, exchange_name: str, symbol: str):
        positions = self.state.get_positions()
        if symbol in positions:
            pos = positions[symbol]
            exchange = self.exchanges.get(pos.exchange)
            if exchange:
                ticker = exchange.get_ticker(symbol)
                curr = ticker["price"]
                pnl_pct = (curr - pos.entry_price) / pos.entry_price if pos.direction == "LONG" else (pos.entry_price - curr) / pos.entry_price
                pnl = pnl_pct * pos.size_usd * pos.leverage
                self.close_position(exchange, symbol, pos, curr, pnl_pct, pnl, "TV_CLOSE")

    def get_ticker_cached(self, exchange: Exchange, symbol: str) -> dict:
        # Try WebSocket first
        if exchange.name == "Delta":
            ws_ticker = self.websocket.get_ticker(symbol)
            if ws_ticker:
                return {"symbol": symbol, **ws_ticker}

        # Try internal cache
        key = f"{exchange.name}_{symbol}"
        cached = self.ticker_cache.get(key)
        if cached:
            return cached

        # Try in-memory data puller cache (loaded once per scan)
        dp_key = f"{exchange.name}:{symbol}"
        if dp_key in self._dp_cache:
            ticker_data = self._dp_cache[dp_key]
            return {"symbol": symbol, "price": ticker_data.get("price", 0), "bid": 0, "ask": 0}

        # REST fallback
        ticker = exchange.get_ticker(symbol)
        self.ticker_cache.set(key, ticker)
        return ticker

    def calculate_dynamic_position_size(self, symbol: str, candles: List[dict]) -> float:
        """Dynamic position sizing based on volatility (ATR)"""
        try:
            atr_pct = calculate_atr_percent(candles)
            # Lower size for high volatility, higher for low volatility
            # Base: 20%, Range: 10-30%
            if atr_pct > 5:
                factor = 0.5  # High volatility = smaller position
            elif atr_pct > 3:
                factor = 0.75
            elif atr_pct < 1:
                factor = 1.5  # Low volatility = larger position
            else:
                factor = 1.0

            size_pct = BASE_POSITION_SIZE_PCT * factor
            return max(0.01, min(0.05, size_pct))  # Clamp 1-5%
        except (ValueError, ZeroDivisionError, TypeError) as e:
            logger.debug(f"Position size calc error for {symbol}: {e}")
            return BASE_POSITION_SIZE_PCT

    def get_adaptive_threshold(self) -> int:
        """Adjust score threshold based on win rate"""
        if not ADAPTIVE_THRESHOLD_ENABLED:
            return MIN_SCORE_THRESHOLD

        wins = self.state.get("wins", 0)
        losses = self.state.get("losses", 0)
        total = wins + losses

        if total < 10:
            return MIN_SCORE_THRESHOLD

        win_rate = wins / total

        if win_rate > 0.6:
            return MIN_SCORE_THRESHOLD - 5
        elif win_rate < 0.4:
            return MIN_SCORE_THRESHOLD + 10
        else:
            return MIN_SCORE_THRESHOLD


    def get_ppo_recommendation(self, candles: list, balance: float = None) -> dict:
        """Get PPO model recommendation"""
        if balance is None:
            balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        return get_ppo_recommendation(candles, balance)

    def add_trade(self, trade):
        """Add trade to history"""
        self.state.add_trade(trade)
        self.update_avg_metrics()

    def update_avg_metrics(self):
        """Update avg win/loss"""
        self.state.update_avg_metrics()

        wins = self.state.get("wins", 0)
        losses = self.state.get("losses", 0)
        total = wins + losses

        if total < 10:
            return MIN_SCORE_THRESHOLD

        win_rate = wins / total

        if win_rate > 0.6:
            return MIN_SCORE_THRESHOLD - 5  # Lower threshold if winning
        elif win_rate < 0.4:
            return MIN_SCORE_THRESHOLD + 10  # Higher threshold if losing
        else:
            return MIN_SCORE_THRESHOLD

    def get_candles_cached(self, exchange: Exchange, symbol: str, resolution: str, limit: int) -> List[dict]:
        """Get candles with 60s cache"""
        import time
        cache_key = f"{exchange.name}:{symbol}:{resolution}"
        now = time.time()
        if cache_key in self._candle_cache:
            data, ts = self._candle_cache[cache_key]
            if now - ts < 60:  # 60 second cache
                return data
        candles = exchange.get_candles(symbol, resolution, limit)
        self._candle_cache[cache_key] = (candles, now)
        return candles

    def quick_price_filter(self, exchange: Exchange, symbol: str) -> bool:
        """Quick filter - only analyze if price moved >0.5% recently"""
        dp_key = f"{exchange.name}:{symbol}"
        if dp_key not in self._dp_cache:
            return True  # No cache, analyze anyway
        
        current_price = self._dp_cache[dp_key].get("price", 0)
        if current_price <= 0:
            return False
        
        last_key = f"{exchange.name}:{symbol}"
        last_price = self._last_prices.get(last_key, 0)
        self._last_prices[last_key] = current_price
        
        if last_price <= 0:
            return True  # First time, analyze
        
        change_pct = abs((current_price - last_price) / last_price) * 100
        return change_pct > 0.3  # Only analyze if >0.3% change

    def calculate_score(self, exchange: Exchange, symbol: str) -> dict:
        # Get candles for multiple timeframes
        candles_1h = self.get_candles_cached(exchange, symbol, "1h", 250)  # Need 200+ for proper SMA200
        candles_5m = self.get_candles_cached(exchange, symbol, "5m", 50)
        candles_15m = self.get_candles_cached(exchange, symbol, "15m", 50)

        if len(candles_1h) < 30:
            return {"score": 0, "signals": [], "valid": False}

        orderbook = exchange.get_orderbook(symbol)
        trades = exchange.get_recent_trades(symbol)

        # Primary analysis on 1h
        indicators = calculate_all_indicators(symbol, candles_1h, orderbook, trades)
        # ========== TREND FILTER (Fix #1) ==========
        # Calculate SMA50/200 for trend detection
        if len(candles_1h) >= 50:
            import numpy as np
            closes = [c["close"] for c in candles_1h]
            sma50 = np.mean(closes[-50:])
            sma200 = np.mean(closes[-200:]) if len(closes) >= 200 else np.mean(closes)
            
            is_uptrend = sma50 > sma200
            is_downtrend = sma50 < sma200
            
            indicators["trend"] = "UP" if is_uptrend else ("DOWN" if is_downtrend else "NEUTRAL")
            indicators["sma50"] = round(sma50, 4)
            indicators["sma200"] = round(sma200, 4)
            
            logger.info(f"[TREND] {symbol}: SMA50={sma50:.4f}, SMA200={sma200:.4f}, Trend={indicators["trend"]}")
        else:
            indicators["trend"] = "UNKNOWN"
        # ========== END TREND FILTER ==========


        # ========== MULTI-TIMEFRAME CONFIRMATION (Fix #5) ==========
        # Require 2 out of 3 timeframes to agree before entry
        mtf_confirmations = 1  # 1h already counted (primary)
        primary_direction = indicators.get("direction")
        
        if len(candles_5m) >= 30:
            ind_5m = calculate_all_indicators(symbol, candles_5m)
            if ind_5m.get("direction") == primary_direction:
                mtf_confirmations += 1
                indicators["score"] += 5
                indicators["signals"].append("MTF_5M_CONFIRM")
            else:
                indicators["signals"].append("MTF_5M_DISAGREE")

        if len(candles_15m) >= 30:
            ind_15m = calculate_all_indicators(symbol, candles_15m)
            if ind_15m.get("direction") == primary_direction:
                mtf_confirmations += 1
                indicators["score"] += 5
                indicators["signals"].append("MTF_15M_CONFIRM")
            else:
                indicators["signals"].append("MTF_15M_DISAGREE")
        
        # Store MTF count for later validation
        indicators["mtf_confirmations"] = mtf_confirmations
        
        # If less than 2 timeframes agree, reduce score significantly
        if mtf_confirmations < 2:
            logger.info(f"[MTF WEAK] {symbol}: Only {mtf_confirmations}/3 timeframes confirm")
            indicators["score"] -= 20  # Penalty for weak MTF
            indicators["signals"].append("MTF_WEAK_SIGNAL")
        else:
            logger.info(f"[MTF STRONG] {symbol}: {mtf_confirmations}/3 timeframes confirm")
            indicators["signals"].append("MTF_STRONG_SIGNAL")
        # ========== END MULTI-TIMEFRAME CONFIRMATION ==========

        # Sentiment
        sentiment = get_combined_sentiment(symbol)
        indicators["score"] += sentiment["score"]
        indicators["signals"].extend(sentiment["signals"])

        # PPO
        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        ppo = get_ppo_recommendation(candles_1h, balance)

        if abs(ppo.get("position_size", 0)) > 0.5:
            ppo_score = 15 if ppo["position_size"] > 0 else -15
            indicators["score"] += ppo_score
            direction = "LONG" if ppo["position_size"] > 0 else "SHORT"
            indicators["signals"].append(f"PPO_{direction}")

        indicators["ppo_sl"] = ppo.get("stop_loss", 0.05)
        indicators["ppo_tp"] = ppo.get("take_profit", 0.10)

        # Adaptive threshold
        threshold = self.get_adaptive_threshold()

        # Apply trend filter before setting direction
        trend = indicators.get("trend", "UNKNOWN")
        
        if indicators["score"] >= threshold:
            if trend == "DOWN":
                logger.info(f"[TREND BLOCK] {symbol}: Blocked LONG in downtrend (SMA50 < SMA200)")
                indicators["direction"] = None
                indicators["signals"].append("TREND_BLOCK_LONG")
            else:
                indicators["direction"] = "LONG"
        elif indicators["score"] <= -threshold:
            if trend == "UP":
                logger.info(f"[TREND BLOCK] {symbol}: Blocked SHORT in uptrend (SMA50 > SMA200)")
                indicators["direction"] = None
                indicators["signals"].append("TREND_BLOCK_SHORT")
            else:
                indicators["direction"] = "SHORT"

        return indicators

    def check_risk_limits(self, symbol: str) -> Tuple[bool, str]:
        positions = self.state.get_positions()
        if len(positions) >= MAX_POSITIONS:
            return False, "Max positions"
        if symbol in positions:
            return False, "In position"

        blacklist = self.state.get("blacklist", {})
        if symbol in blacklist and time.time() < blacklist[symbol]:
            return False, "Blacklisted"

        cooldowns = self.state.get("cooldowns", {})
        if symbol in cooldowns and time.time() < cooldowns[symbol]:
            return False, "Cooldown"

        if self.state.get("consecutive_losses", 0) >= MAX_CONSECUTIVE_LOSSES:
            return False, "Consecutive losses"

        daily_pnl = self.state.get("daily_pnl", 0)
        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        if daily_pnl < -(balance * DAILY_DRAWDOWN_LIMIT / 100):
            return False, "Daily drawdown"

        return True, "OK"

    def check_volatility_filter(self, candles: List[dict]) -> Tuple[bool, float]:
        """Check if volatility is within acceptable range"""
        try:
            atr_pct = calculate_atr_percent(candles)
            if atr_pct > MAX_VOLATILITY_FILTER:
                return False, atr_pct
            return True, atr_pct
        except (ValueError, ZeroDivisionError, IndexError) as e:
            logger.debug(f"Volatility filter calc error: {e}")
            return True, 0

    def check_slippage(self, exchange: Exchange, symbol: str) -> Tuple[bool, float]:
        """Check if spread is acceptable"""
        spread = exchange.check_spread(symbol)
        if spread > SLIPPAGE_MAX_SPREAD:
            return False, spread
        return True, spread

    def open_position(self, exchange: Exchange, symbol: str, direction: str,
                     signals: List[str], candles: List[dict], ppo_sl: float, ppo_tp: float):

        # Volatility check
        vol_ok, atr = self.check_volatility_filter(candles)
        if not vol_ok:
            logger.warning(f"Skipping {symbol}: ATR {atr:.1f}% > {MAX_VOLATILITY_FILTER}%")
            return

        # Slippage check
        slip_ok, spread = self.check_slippage(exchange, symbol)
        if not slip_ok:
            logger.warning(f"Skipping {symbol}: Spread {spread:.2f}% > {SLIPPAGE_MAX_SPREAD}%")
            return

        # Dynamic position sizing
        position_size_pct = self.calculate_dynamic_position_size(symbol, candles)
        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        position_size = balance * position_size_pct

        ticker = self.get_ticker_cached(exchange, symbol)
        entry_price = ticker["price"]
        if entry_price <= 0:
            return

        # ========== ATR-BASED STOPS (Fix #3) ==========
        # Use ATR for dynamic stop loss and take profit
        try:
            atr_pct = calculate_atr_percent(candles) if candles else 1.0
        except (ValueError, ZeroDivisionError, IndexError) as e:
            logger.debug(f"ATR calc error for {symbol}: {e}")
            atr_pct = 1.0
        
        # ATR-based stops with min/max bounds
        sl_pct = max(atr_pct * ATR_SL_MULTIPLIER, 0.5)   # Min 0.5% SL
        tp_pct = max(atr_pct * ATR_TP_MULTIPLIER, 1.0)   # Min 1.0% TP
        
        # Cap at reasonable levels
        sl_pct = min(sl_pct, 5.0)   # Max 5% SL
        tp_pct = min(tp_pct, 10.0)  # Max 10% TP
        
        stop_loss = sl_pct / 100
        take_profit = tp_pct / 100
        
        logger.info(f"[ATR STOPS] {symbol}: ATR={atr_pct:.2f}%, SL={sl_pct:.2f}%, TP={tp_pct:.2f}%")
        # ========== END ATR-BASED STOPS ==========

        fee = exchange.calculate_fee(position_size)

        position = Position(
            symbol=symbol,
            exchange=exchange.name,
            direction=direction,
            entry_price=entry_price,
            size_usd=position_size,
            leverage=LEVERAGE,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_time=datetime.now().isoformat(),
            entry_signals=signals[:5],
            entry_atr=atr
        )

        # Place order (limit order for better fills)
        if TRADING_MODE == "LIVE":
            # Try limit order first
            limit_price = entry_price * (0.999 if direction == "LONG" else 1.001)
            order = exchange.place_order(symbol, "buy" if direction == "LONG" else "sell",
                                        position_size / entry_price, "limit", limit_price)
            if "error" in order:
                # Fallback to market
                order = exchange.place_order(symbol, "buy" if direction == "LONG" else "sell",
                                            position_size / entry_price, "market")

        self.state.add_position(position)
        self.state.set("balance", balance - fee)
        self.state.set("total_fees", self.state.get("total_fees", 0) + fee)

        signals_str = ", ".join(signals[:5])
        logger.info(f"OPENED {direction} {symbol} @ ${entry_price:.2f} | Size: ${position_size:.0f} ({position_size_pct*100:.0f}%) | ATR: {atr:.1f}%")
        logger.info(f"SL: {stop_loss*100:.1f}% | TP: {take_profit*100:.1f}% | Signals: {signals_str}")

        # Telegram notification
        self.telegram.send_trade_open(position)

    def check_positions(self):
        positions = self.state.get_positions()

        for symbol, pos in list(positions.items()):
            exchange = self.exchanges.get(pos.exchange)
            if not exchange:
                continue

            ticker = self.get_ticker_cached(exchange, symbol)
            current_price = ticker["price"]
            if current_price <= 0:
                continue

            pnl_pct = (current_price - pos.entry_price) / pos.entry_price if pos.direction == "LONG" else (pos.entry_price - current_price) / pos.entry_price
            pnl_usd = pnl_pct * pos.size_usd * pos.leverage
            exit_reason = None

            # Immediate loss exit (NEW)
            if pnl_pct * 100 <= IMMEDIATE_LOSS_EXIT:
                exit_reason = "IMMEDIATE_LOSS"

            # Stop loss
            elif pnl_pct <= -pos.stop_loss:
                exit_reason = "STOP_LOSS"

            # Take profit
            elif pnl_pct >= pos.take_profit:
                exit_reason = "TAKE_PROFIT"

            # Trailing stop
            if pnl_pct > 0.03 and not pos.trailing_active:
                pos.trailing_active = True
                pos.highest_pnl = pnl_pct
                self.state.add_position(pos)

            if pos.trailing_active:
                if pnl_pct > pos.highest_pnl:
                    pos.highest_pnl = pnl_pct
                    self.state.add_position(pos)

                trail_dist = min(0.03, max(0.01, pnl_pct * 0.3))
                if pnl_pct < pos.highest_pnl - trail_dist:
                    exit_reason = "TRAILING_STOP"

            if exit_reason:
                self.close_position(exchange, symbol, pos, current_price, pnl_pct, pnl_usd, exit_reason)

    def close_position(self, exchange: Exchange, symbol: str, pos: Position,
                      exit_price: float, pnl_pct: float, pnl_usd: float, reason: str):

        exit_fee = exchange.calculate_fee(pos.size_usd)
        entry_fee = exchange.calculate_fee(pos.size_usd)
        total_fees = entry_fee + exit_fee
        net_pnl = pnl_usd - exit_fee

        # Calculate hold duration
        try:
            entry_dt = datetime.fromisoformat(pos.entry_time)
            hold_mins = int((datetime.now() - entry_dt).total_seconds() / 60)
        except (ValueError, TypeError, AttributeError) as e:
            logger.debug(f"Hold duration calc error: {e}")
            hold_mins = 0

        # Create trade record
        trade = Trade(
            symbol=symbol,
            exchange=pos.exchange,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size_usd=pos.size_usd,
            gross_pnl=round(pnl_usd, 2),
            fees=round(total_fees, 4),
            net_pnl=round(net_pnl, 2),
            entry_time=pos.entry_time,
            exit_time=datetime.now().isoformat(),
            exit_reason=reason,
            hold_duration_mins=hold_mins
        )

        # Add to trade history
        self.state.add_trade(trade)

        # Update balance and stats
        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        self.state.set("balance", balance + net_pnl)
        self.state.set("total_pnl", self.state.get("total_pnl", 0) + net_pnl)
        self.state.set("total_fees", self.state.get("total_fees", 0) + exit_fee)
        self.state.set("daily_pnl", self.state.get("daily_pnl", 0) + net_pnl)

        if net_pnl >= 0:
            self.state.set("wins", self.state.get("wins", 0) + 1)
            self.state.set("consecutive_losses", 0)
        else:
            self.state.set("losses", self.state.get("losses", 0) + 1)
            self.state.set("consecutive_losses", self.state.get("consecutive_losses", 0) + 1)
            blacklist = self.state.get("blacklist", {})
            blacklist[symbol] = time.time() + COIN_BLACKLIST_TIME
            self.state.set("blacklist", blacklist)

        cooldowns = self.state.get("cooldowns", {})
        cooldowns[symbol] = time.time() + COOLDOWN_AFTER_EXIT
        self.state.set("cooldowns", cooldowns)

        # Update average metrics
        self.state.update_avg_metrics()

        self.state.remove_position(symbol)

        logger.info(f"CLOSED {pos.direction} {symbol} @ ${exit_price:.2f} | Net P&L: ${net_pnl:+.2f} ({pnl_pct*100:+.2f}%) | {reason}")

        # Telegram notification
        self.telegram.send_trade_close(trade)

        # Record metrics
        if METRICS_ENABLED and bot_metrics:
            bot_metrics.record_trade(net_pnl, total_fees, hold_mins, net_pnl >= 0)
            bot_metrics.update_balance(self.state.get("balance", PAPER_INITIAL_BALANCE))


    def _load_dp_cache(self):
        """Load data puller cache once per scan cycle"""
        try:
            import json
            with open("/tmp/oracle_ticker_cache.json", "r") as f:
                data = json.load(f)
            self._dp_cache = data.get("tickers", {})
            logger.debug(f"Loaded {len(self._dp_cache)} tickers from data puller cache")
        except (FileNotFoundError, json.JSONDecodeError, PermissionError) as e:
            logger.debug(f"Data puller cache unavailable: {e}")
            self._dp_cache = {}

    def scan_markets(self):
        # Load data puller cache once at start
        self._load_dp_cache()
        for name, exchange in self.exchanges.items():
            symbols = exchange.get_symbols()
            logger.info(f"[{name}] Scanning {len(symbols)} pairs...")
            scanned = 0
            for symbol in symbols:
                scanned += 1
                if scanned % 50 == 0:
                    logger.info(f"[{name}] Progress: {scanned}/{len(symbols)} pairs scanned")
                allowed, reason = self.check_risk_limits(symbol)
                if not allowed:
                    continue

                # Quick filter - skip if no significant price change
                if not self.quick_price_filter(exchange, symbol):
                    continue
                    
                try:
                    score_data = self.calculate_score(exchange, symbol)
                    if not score_data.get("valid", False):
                        continue
                except Exception as e:
                    logger.debug(f"[{name}] {symbol} score error: {e}")
                    continue

                direction = score_data.get("direction")
                if direction:
                    logger.info(f"[{name}] {symbol}: Score {score_data['score']} (threshold: {self.get_adaptive_threshold()}) -> {direction}")
                    candles = exchange.get_candles(symbol, "1h", 50)
                    self.open_position(exchange, symbol, direction, score_data.get("signals", []),
                                      candles, score_data.get("ppo_sl", 0.05), score_data.get("ppo_tp", 0.10))

    def display_status(self):
        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        positions = self.state.get_positions()
        wins = self.state.get("wins", 0)
        losses = self.state.get("losses", 0)
        total_pnl = self.state.get("total_pnl", 0)
        fees = self.state.get("total_fees", 0)
        avg_win = self.state.get("avg_win", 0)
        avg_loss = self.state.get("avg_loss", 0)
        trades_count = len(self.state.get("trades", []))

        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        print("\n" + "="*60)
        print(f"ORACLE BOT V2 STATUS - {now_str}")
        print("="*60)
        print(f"Mode: {TRADING_MODE} | Balance: ${balance:.2f}")
        print(f"Positions: {len(positions)}/{MAX_POSITIONS} | Trades: {trades_count}")
        print(f"W/L: {wins}/{losses} ({win_rate:.1f}%) | Threshold: {self.get_adaptive_threshold()}")
        print(f"Total P&L: ${total_pnl:+.2f} | Fees: ${fees:.2f}")
        print(f"Avg Win: ${avg_win:+.2f} | Avg Loss: ${avg_loss:.2f}")
        print("-"*60)

        for sym, pos in positions.items():
            exchange = self.exchanges.get(pos.exchange)
            if exchange:
                ticker = self.get_ticker_cached(exchange, sym)
                curr = ticker["price"]
                pnl_pct = (curr - pos.entry_price) / pos.entry_price if pos.direction == "LONG" else (pos.entry_price - curr) / pos.entry_price
                pnl = pnl_pct * pos.size_usd * pos.leverage
                trail = " [T]" if pos.trailing_active else ""
                print(f"[{pos.exchange}] {sym} {pos.direction}: ${pos.size_usd:.0f} @ ${pos.entry_price:.2f} -> {pnl_pct*100:+.2f}% (${pnl:+.2f}){trail}")

        print("="*60)

    def run(self, scan_interval: float = 0.1):
        self.running = True

        # Start WebSocket
        try:
            self.websocket.start()
        except Exception as e:
            logger.warning(f"WebSocket start failed: {e}")

        # Start webhook server
        self.start_webhook_server()

        logger.info("Oracle Bot V2 starting...")

        last_scan = 0

        try:
            while self.running:
                now = time.time()
                self.check_positions()

                if now - last_scan >= scan_interval:
                    self.scan_markets()
                    last_scan = now
                    self.display_status()

                time.sleep(0.05)  # 50ms for rapid scanning

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.running = False

        self.state.save()
        logger.info("Oracle Bot V2 stopped")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Oracle Trading Bot V2")
    parser.add_argument("--paper", action="store_true", help="Paper trading mode")
    parser.add_argument("--live", action="store_true", help="Live trading mode")
    parser.add_argument("--status", action="store_true", help="Show status")
    args = parser.parse_args()

    if args.live:
        TRADING_MODE = "LIVE"

    bot = OracleBot()

    if args.status:
        bot.display_status()
    else:
        bot.run()

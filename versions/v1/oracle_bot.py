#!/usr/bin/env python3
"""
ORACLE BOT - Multi-Exchange Trading System
Supports: Delta Exchange, Zebpay, Coinbase, TradingView Webhooks
Features: All V1-V10 features + multi-exchange + proper fee structures
"""

import os
import sys
import json
import time
import hmac
import hashlib
import logging
import requests
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from http.server import HTTPServer, BaseHTTPRequestHandler

# Import custom modules
try:
    from indicators_v11 import calculate_all_indicators, calculate_dynamic_sl_tp
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
        logging.FileHandler("/home/vibhavaggarwal/oracle_bot.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("OracleBot")

# ============================================================================
# FEE STRUCTURES PER EXCHANGE
# ============================================================================

class FeeStructure:
    """Fee calculation for each exchange"""

    # Delta Exchange India (Futures)
    DELTA = {
        "maker": 0.0002,      # 0.02%
        "taker": 0.0005,      # 0.05%
        "gst": 0.18,          # 18% GST on fees
        "funding_interval": 8, # hours
        "leverage_max": 100
    }

    # Zebpay India (Spot)
    ZEBPAY = {
        "maker": 0.0015,      # 0.15%
        "taker": 0.0025,      # 0.25%
        "gst": 0.18,          # 18% GST
        "tds": 0.01,          # 1% TDS on sale (Indian tax)
        "withdrawal_inr": 10, # INR 10 flat
        "withdrawal_crypto_pct": 0.0005  # 0.05%
    }

    # Coinbase Pro (International)
    COINBASE = {
        "maker": 0.004,       # 0.4% (tier 1)
        "taker": 0.006,       # 0.6% (tier 1)
        "gst": 0,             # No GST
        "withdrawal_crypto": 0  # Network fee only
    }

    @classmethod
    def calculate_delta_fee(cls, size_usd: float, is_taker: bool = True) -> float:
        """Calculate Delta Exchange fee including GST"""
        base_rate = cls.DELTA["taker"] if is_taker else cls.DELTA["maker"]
        fee = size_usd * base_rate
        gst = fee * cls.DELTA["gst"]
        return fee + gst  # Returns 0.059% effective for taker

    @classmethod
    def calculate_zebpay_fee(cls, size_inr: float, is_taker: bool = True, is_sell: bool = False) -> float:
        """Calculate Zebpay fee including GST and TDS"""
        base_rate = cls.ZEBPAY["taker"] if is_taker else cls.ZEBPAY["maker"]
        fee = size_inr * base_rate
        gst = fee * cls.ZEBPAY["gst"]
        tds = size_inr * cls.ZEBPAY["tds"] if is_sell else 0
        return fee + gst + tds

    @classmethod
    def calculate_coinbase_fee(cls, size_usd: float, is_taker: bool = True) -> float:
        """Calculate Coinbase fee"""
        rate = cls.COINBASE["taker"] if is_taker else cls.COINBASE["maker"]
        return size_usd * rate

    @classmethod
    def calculate_profit(cls, exchange: str, entry_price: float, exit_price: float,
                        size: float, direction: str, leverage: int = 1) -> dict:
        """Calculate net profit after all fees"""
        if direction == "LONG":
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price

        gross_pnl = pnl_pct * size * leverage

        if exchange == "Delta":
            entry_fee = cls.calculate_delta_fee(size)
            exit_fee = cls.calculate_delta_fee(size)
        elif exchange == "Zebpay":
            entry_fee = cls.calculate_zebpay_fee(size, is_sell=False)
            exit_fee = cls.calculate_zebpay_fee(size, is_sell=(direction == "LONG"))
        elif exchange == "Coinbase":
            entry_fee = cls.calculate_coinbase_fee(size)
            exit_fee = cls.calculate_coinbase_fee(size)
        else:
            entry_fee = size * 0.001
            exit_fee = size * 0.001

        total_fees = entry_fee + exit_fee
        net_pnl = gross_pnl - total_fees
        roi = (net_pnl / size) * 100

        return {
            "gross_pnl": round(gross_pnl, 2),
            "entry_fee": round(entry_fee, 4),
            "exit_fee": round(exit_fee, 4),
            "total_fees": round(total_fees, 4),
            "net_pnl": round(net_pnl, 2),
            "roi_pct": round(roi, 2),
            "breakeven_pct": round((total_fees / size / leverage) * 100, 3)
        }

# ============================================================================
# CONFIGURATION
# ============================================================================

TRADING_MODE = os.getenv("TRADING_MODE", "PAPER")
PAPER_INITIAL_BALANCE = 1000.0
MAX_POSITIONS = 5
POSITION_SIZE_PCT = 0.20
LEVERAGE = 20
MIN_SCORE_THRESHOLD = 40
COOLDOWN_AFTER_EXIT = 30
COIN_BLACKLIST_TIME = 180
MAX_CONSECUTIVE_LOSSES = 3
DAILY_DRAWDOWN_LIMIT = 10.0

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

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)

# ============================================================================
# TRADINGVIEW WEBHOOK HANDLER
# ============================================================================

class TradingViewWebhook(BaseHTTPRequestHandler):
    """Handle TradingView alerts as webhooks"""

    bot = None

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')

        try:
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
    def get_symbols(self) -> List[str]:
        pass

    @abstractmethod
    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market") -> dict:
        pass

    @abstractmethod
    def get_balance(self) -> dict:
        pass

    def calculate_fee(self, size: float, is_taker: bool = True) -> float:
        return FeeStructure.calculate_delta_fee(size, is_taker)

# ============================================================================
# DELTA EXCHANGE
# ============================================================================

class DeltaExchange(Exchange):
    BASE_URL = "https://api.delta.exchange/v2"

    SYMBOLS = [
        "BTCUSD", "ETHUSD", "SOLUSD",
        "BTCUSDT", "ETHUSDT", "XRPUSDT", "SOLUSDT",
        "DOGEUSDT", "ADAUSDT", "LINKUSDT", "LTCUSDT",
        "MATICUSDT", "DOTUSDT", "AVAXUSDT", "ATOMUSDT",
        "UNIUSDT", "AAVEUSDT", "SANDUSDT"
    ]

    @property
    def name(self) -> str:
        return "Delta"

    def _sign(self, method: str, path: str, payload: str = "") -> dict:
        timestamp = str(int(time.time()))
        signature_data = method + timestamp + path + payload
        signature = hmac.new(
            self.api_secret.encode(),
            signature_data.encode(),
            hashlib.sha256
        ).hexdigest()
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "Content-Type": "application/json"
        }

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
        return {"symbol": symbol, "price": 0}

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
        except:
            return {"buy": [], "sell": []}

    def get_symbols(self) -> List[str]:
        return self.SYMBOLS

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market") -> dict:
        if TRADING_MODE == "PAPER":
            return {"status": "paper", "order_id": f"paper_{int(time.time())}"}

        path = "/orders"
        payload = {"product_symbol": symbol, "size": size, "side": side.lower(), "order_type": order_type}
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

# ============================================================================
# ZEBPAY EXCHANGE
# ============================================================================

class ZebpayExchange(Exchange):
    BASE_URL = "https://www.zebapi.com/pro/v1"

    SYMBOLS = ["BTC-INR", "ETH-INR", "XRP-INR", "LTC-INR", "USDT-INR", "LINK-INR", "MATIC-INR"]

    @property
    def name(self) -> str:
        return "Zebpay"

    def get_ticker(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.BASE_URL}/market/{symbol}/ticker", timeout=5)
            data = r.json()
            return {
                "symbol": symbol,
                "price": float(data.get("lastTradePrice", 0)),
                "volume": float(data.get("volume24Hours", 0))
            }
        except:
            return {"symbol": symbol, "price": 0}

    def get_candles(self, symbol: str, resolution: str = "1h", limit: int = 100) -> List[dict]:
        return []

    def get_orderbook(self, symbol: str) -> dict:
        return {"buy": [], "sell": []}

    def get_symbols(self) -> List[str]:
        return self.SYMBOLS

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market") -> dict:
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

    SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "LINK-USD"]

    @property
    def name(self) -> str:
        return "Coinbase"

    def get_ticker(self, symbol: str) -> dict:
        try:
            r = self.session.get(f"{self.BASE_URL}/products/{symbol}/ticker", timeout=5)
            data = r.json()
            return {"symbol": symbol, "price": float(data.get("price", 0))}
        except:
            return {"symbol": symbol, "price": 0}

    def get_candles(self, symbol: str, resolution: str = "1h", limit: int = 100) -> List[dict]:
        try:
            granularity_map = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}
            granularity = granularity_map.get(resolution, 3600)
            r = self.session.get(
                f"{self.BASE_URL}/products/{symbol}/candles",
                params={"granularity": granularity},
                timeout=10
            )
            data = r.json()
            candles = []
            for c in data[:limit]:
                candles.append({
                    "time": c[0], "open": float(c[3]), "high": float(c[2]),
                    "low": float(c[1]), "close": float(c[4]), "volume": float(c[5])
                })
            return list(reversed(candles))
        except:
            return []

    def get_orderbook(self, symbol: str) -> dict:
        return {"buy": [], "sell": []}

    def get_symbols(self) -> List[str]:
        return self.SYMBOLS

    def place_order(self, symbol: str, side: str, size: float, order_type: str = "market") -> dict:
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
        except:
            return self._default_state()

    def _default_state(self) -> dict:
        return {
            "balance": PAPER_INITIAL_BALANCE,
            "positions": {},
            "trades": [],
            "wins": 0,
            "losses": 0,
            "total_pnl": 0.0,
            "total_fees": 0.0,
            "consecutive_losses": 0,
            "daily_pnl": 0.0,
            "blacklist": {},
            "cooldowns": {}
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

# ============================================================================
# PPO CLIENT
# ============================================================================

def get_ppo_recommendation(candles: List[dict], balance: float) -> dict:
    try:
        data = [[c["open"], c["high"], c["low"], c["close"], c["volume"]] for c in candles[-20:]]
        r = requests.post(f"{PPO_SERVER}/predict/candles", json={"candles": data, "balance": balance}, timeout=5)
        if r.status_code == 200:
            return r.json()
    except:
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
        self.ticker_cache: Dict[str, Tuple[dict, float]] = {}
        self.cache_ttl = 0.5
        self.webhook_server = None

        self._init_exchanges()
        logger.info(f"Oracle Bot initialized - Mode: {TRADING_MODE}")
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
        TradingViewWebhook.bot = self
        self.webhook_server = HTTPServer(('0.0.0.0', WEBHOOK_PORT), TradingViewWebhook)
        thread = threading.Thread(target=self.webhook_server.serve_forever, daemon=True)
        thread.start()
        logger.info(f"Webhook server started on port {WEBHOOK_PORT}")

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
                if pos.direction == "LONG":
                    pnl_pct = (curr - pos.entry_price) / pos.entry_price
                else:
                    pnl_pct = (pos.entry_price - curr) / pos.entry_price
                pnl = pnl_pct * pos.size_usd * pos.leverage
                self.close_position(exchange, symbol, pos, curr, pnl_pct, pnl, "TV_CLOSE")

    def get_ticker_cached(self, exchange: Exchange, symbol: str) -> dict:
        key = f"{exchange.name}_{symbol}"
        now = time.time()
        if key in self.ticker_cache:
            cached, ts = self.ticker_cache[key]
            if now - ts < self.cache_ttl:
                return cached
        ticker = exchange.get_ticker(symbol)
        self.ticker_cache[key] = (ticker, now)
        return ticker

    def calculate_score(self, exchange: Exchange, symbol: str) -> dict:
        candles = exchange.get_candles(symbol, "1h", 50)
        if len(candles) < 30:
            return {"score": 0, "signals": [], "valid": False}

        orderbook = exchange.get_orderbook(symbol)
        indicators = calculate_all_indicators(symbol, candles, orderbook)

        sentiment = get_combined_sentiment(symbol)
        indicators["score"] += sentiment["score"]
        indicators["signals"].extend(sentiment["signals"])

        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        ppo = get_ppo_recommendation(candles, balance)

        if abs(ppo.get("position_size", 0)) > 0.5:
            ppo_score = 15 if ppo["position_size"] > 0 else -15
            indicators["score"] += ppo_score
            direction = "LONG" if ppo["position_size"] > 0 else "SHORT"
            indicators["signals"].append(f"PPO_{direction}")

        indicators["ppo_sl"] = ppo.get("stop_loss", 0.05)
        indicators["ppo_tp"] = ppo.get("take_profit", 0.10)

        if indicators["score"] >= MIN_SCORE_THRESHOLD:
            indicators["direction"] = "LONG"
        elif indicators["score"] <= -MIN_SCORE_THRESHOLD:
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

        return True, "OK"

    def open_position(self, exchange: Exchange, symbol: str, direction: str,
                     signals: List[str], candles: List[dict], ppo_sl: float, ppo_tp: float):
        balance = self.state.get("balance", PAPER_INITIAL_BALANCE)
        position_size = balance * POSITION_SIZE_PCT

        ticker = self.get_ticker_cached(exchange, symbol)
        entry_price = ticker["price"]
        if entry_price <= 0:
            return

        try:
            sl_tp = calculate_dynamic_sl_tp(candles, direction)
            stop_loss = max(ppo_sl, sl_tp["sl_pct"] / 100)
            take_profit = max(ppo_tp, sl_tp["tp_pct"] / 100)
        except:
            stop_loss = ppo_sl
            take_profit = ppo_tp

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
            entry_signals=signals[:5]
        )

        self.state.add_position(position)
        self.state.set("balance", balance - fee)
        self.state.set("total_fees", self.state.get("total_fees", 0) + fee)

        signals_str = ", ".join(signals[:5])
        logger.info(f"OPENED {direction} {symbol} @ ${entry_price:.2f} | Size: ${position_size:.0f} | Fee: ${fee:.4f}")
        logger.info(f"SL: {stop_loss*100:.1f}% | TP: {take_profit*100:.1f}% | Signals: {signals_str}")

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

            if pos.direction == "LONG":
                pnl_pct = (current_price - pos.entry_price) / pos.entry_price
            else:
                pnl_pct = (pos.entry_price - current_price) / pos.entry_price

            pnl_usd = pnl_pct * pos.size_usd * pos.leverage
            exit_reason = None

            if pnl_pct <= -pos.stop_loss:
                exit_reason = "STOP_LOSS"
            elif pnl_pct >= pos.take_profit:
                exit_reason = "TAKE_PROFIT"

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
        net_pnl = pnl_usd - exit_fee

        profit_calc = FeeStructure.calculate_profit(
            exchange=pos.exchange,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            size=pos.size_usd,
            direction=pos.direction,
            leverage=pos.leverage
        )

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

        self.state.remove_position(symbol)

        logger.info(f"CLOSED {pos.direction} {symbol} @ ${exit_price:.2f} | Net P&L: ${net_pnl:+.2f} ({pnl_pct*100:+.2f}%) | {reason}")
        logger.info(f"Fees: ${profit_calc['total_fees']:.4f} | ROI: {profit_calc['roi_pct']:+.2f}%")

    def scan_markets(self):
        for name, exchange in self.exchanges.items():
            for symbol in exchange.get_symbols():
                allowed, reason = self.check_risk_limits(symbol)
                if not allowed:
                    continue

                score_data = self.calculate_score(exchange, symbol)
                if not score_data.get("valid", False):
                    continue

                direction = score_data.get("direction")
                if direction:
                    logger.info(f"[{name}] {symbol}: Score {score_data['score']} -> {direction}")
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

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print("\n" + "="*60)
        print(f"ORACLE BOT STATUS - {now_str}")
        print("="*60)
        print(f"Mode: {TRADING_MODE} | Balance: ${balance:.2f}")
        print(f"Positions: {len(positions)}/{MAX_POSITIONS} | W/L: {wins}/{losses}")
        print(f"Total P&L: ${total_pnl:+.2f} | Fees: ${fees:.2f}")
        print("-"*60)

        for sym, pos in positions.items():
            exchange = self.exchanges.get(pos.exchange)
            if exchange:
                ticker = self.get_ticker_cached(exchange, sym)
                curr = ticker["price"]
                if pos.direction == "LONG":
                    pnl_pct = (curr - pos.entry_price) / pos.entry_price
                else:
                    pnl_pct = (pos.entry_price - curr) / pos.entry_price
                pnl = pnl_pct * pos.size_usd * pos.leverage
                trail = " [T]" if pos.trailing_active else ""
                print(f"[{pos.exchange}] {sym} {pos.direction}: ${pos.size_usd:.0f} @ ${pos.entry_price:.2f} -> {pnl_pct*100:+.2f}% (${pnl:+.2f}){trail}")

        print("="*60)

    def run(self, scan_interval: int = 60):
        self.running = True
        # self.start_webhook_server()  # Disabled - port conflict
        logger.info("Oracle Bot starting...")

        last_scan = 0

        try:
            while self.running:
                now = time.time()
                self.check_positions()

                if now - last_scan >= scan_interval:
                    self.scan_markets()
                    last_scan = now
                    self.display_status()

                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.running = False

        self.state.save()
        logger.info("Oracle Bot stopped")

# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Oracle Trading Bot")
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

#!/usr/bin/env python3
"""
DELTA WEBSOCKET v6 - ADVANCED TRADING BOT
==========================================
Improvements from V5:
1. REAL RSI using historical candles (not pseudo-RSI)
2. MACD confirmation for trend direction
3. ATR-BASED DYNAMIC STOPS (adapts to volatility)
4. ORDER BOOK IMBALANCE detection
5. DYNAMIC POSITION SIZING based on volatility
6. MULTI-TIMEFRAME CONFIRMATION
7. ADAPTIVE TRAILING STOP distance
8. All V5 features retained (limit orders, slippage protection)

Research Sources:
- ATR Stops: https://www.luxalgo.com/blog/5-atr-stop-loss-strategies-for-risk-control/
- RSI+MACD: https://wundertrading.com/journal/en/learn/article/integrating-crypto-bots-with-technical-indicators
"""

import requests
import socket
import time
import hashlib
import hmac
import json
from datetime import datetime, timezone
import threading
import websocket
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Force IPv4
_orig = socket.getaddrinfo
socket.getaddrinfo = lambda *a, **k: [r for r in _orig(*a, **k) if r[0] == socket.AF_INET]

API_KEY = "KMLkcDcajSQWPmVcgNuAd3KWqf7OzM"
API_SECRET = "ltJaGy3GErRluET1e7FaYOklFx1u7pGwCsiCqCO774ndLdPzcnZzmHYscT5W"
BASE = "https://api.india.delta.exchange"
WS_URL = "wss://socket.india.delta.exchange"
USD_TO_INR = 85

# TRADING SETTINGS
LEVERAGE = 10
BASE_POSITION_SIZE = 0.65  # Will be adjusted by volatility
LOG = "/home/vibhavaggarwal/delta_websocket_v6.log"

# V6: DYNAMIC STOPS (ATR-based)
ATR_STOP_MULTIPLIER = 2.0     # Stop at 2x ATR
ATR_TRAIL_MULTIPLIER = 1.5    # Trail at 1.5x ATR
MIN_STOP_LOSS = -3.0          # Minimum stop (tight for stable coins)
MAX_STOP_LOSS = -10.0         # Maximum stop (cap for volatile coins)
TAKE_PROFIT = 10.0            # Fixed take profit
TRAIL_START = 3.0             # Start trailing at +3%
MIN_TRAIL_DIST = 1.0          # Minimum trail distance
MAX_TRAIL_DIST = 3.0          # Maximum trail distance

# RISK MANAGEMENT
COOLDOWN_AFTER_EXIT = 30
COIN_BLACKLIST_TIME = 180
MAX_CONSECUTIVE_LOSSES = 3
DAILY_DRAWDOWN_LIMIT = 10

# V6: SLIPPAGE PROTECTION (from V5)
MAX_VOLATILITY = 20.0
LIMIT_ORDER_BUFFER = 0.002
SLIPPAGE_CHECK_DELAY = 2.0
MAX_IMMEDIATE_LOSS = -3.0
ORDER_TIMEOUT = 10

# V6: SCORING THRESHOLDS
MIN_SCORE = 55  # Slightly higher due to better signals
MIN_VOLUME = 500000

# V6: CANDLE CACHE (reduce API calls)
candle_cache = {}
CANDLE_CACHE_TTL = 30  # seconds

# Connection pooling
session = requests.Session()
adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=Retry(total=0))
session.mount('https://', adapter)

# WARP Proxy for stable IP
WARP_PROXY = 'socks5://127.0.0.1:40000'
session.proxies = {'http': WARP_PROXY, 'https': WARP_PROXY}

# State
tickers = {}
ticker_lock = threading.Lock()
ws_connected = False
ws_update_count = 0
start_equity = 0
wins = 0
losses = 0
consecutive_losses = 0
last_exit_time = 0
coin_blacklist = {}
trading_paused = False
pause_reason = ""
pending_order = None
entry_time = 0
current_atr = 0  # V6: Store ATR for current position
current_stop = -5  # V6: Dynamic stop for current position
current_trail_dist = 1.5  # V6: Dynamic trail distance

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:12]
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except:
        pass

def sign(m, p, b=None):
    t = str(int(time.time()))
    d = m + t + p + (json.dumps(b, separators=(",",":")) if b else "")
    s = hmac.new(API_SECRET.encode(), d.encode(), hashlib.sha256).hexdigest()
    return {"api-key": API_KEY, "timestamp": t, "signature": s, "Content-Type": "application/json"}

def get(p, timeout=1.5):
    try:
        return session.get(BASE + p, headers=sign("GET", p), timeout=timeout).json()
    except Exception as e:
        return {"error": str(e)}

def post(p, b):
    try:
        return session.post(BASE + p, headers=sign("POST", p, b),
                          data=json.dumps(b, separators=(",",":")), timeout=1.5).json()
    except Exception as e:
        return {"error": str(e)}

def delete(p):
    try:
        return session.delete(BASE + p, headers=sign("DELETE", p), timeout=1.5).json()
    except Exception as e:
        return {"error": str(e)}

# ============================================
# V6 NEW: TECHNICAL INDICATORS
# ============================================

def get_candles(symbol, resolution="5m", count=50):
    """Fetch historical candles with caching"""
    cache_key = f"{symbol}_{resolution}"
    now = time.time()
    
    # Check cache
    if cache_key in candle_cache:
        cached_time, cached_data = candle_cache[cache_key]
        if now - cached_time < CANDLE_CACHE_TTL:
            return cached_data
    
    # Fetch fresh data
    try:
        # Calculate time range
        if resolution == "5m":
            seconds_per_candle = 5 * 60
        elif resolution == "15m":
            seconds_per_candle = 15 * 60
        elif resolution == "1h":
            seconds_per_candle = 60 * 60
        else:
            seconds_per_candle = 5 * 60
        
        end = int(now)
        start = end - (count * seconds_per_candle)
        
        r = session.get(f"{BASE}/v2/history/candles", params={
            "resolution": resolution,
            "symbol": symbol,
            "start": start,
            "end": end
        }, timeout=2).json()
        
        candles = r.get("result", [])
        
        # Cache result
        if candles:
            candle_cache[cache_key] = (now, candles)
        
        return candles
    except Exception as e:
        log(f"[CANDLE] Error fetching {symbol}: {e}")
        return []

def calculate_ema(values, period):
    """Calculate Exponential Moving Average"""
    if len(values) < period:
        return values
    
    ema = []
    multiplier = 2 / (period + 1)
    
    # First EMA is SMA
    sma = sum(values[:period]) / period
    ema.append(sma)
    
    # Calculate EMA for remaining values
    for i in range(period, len(values)):
        val = (values[i] * multiplier) + (ema[-1] * (1 - multiplier))
        ema.append(val)
    
    return ema

def calculate_rsi(candles, period=14):
    """Calculate Real RSI from candles"""
    if len(candles) < period + 1:
        return 50  # Default to neutral
    
    closes = [float(c.get('close', 0)) for c in candles]
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    
    if len(gains) < period:
        return 50
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(candles):
    """Calculate MACD histogram"""
    if len(candles) < 26:
        return 0
    
    closes = [float(c.get('close', 0)) for c in candles]
    
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    
    if not ema12 or not ema26:
        return 0
    
    # MACD line
    min_len = min(len(ema12), len(ema26))
    macd_line = [ema12[i] - ema26[i] for i in range(min_len)]
    
    if len(macd_line) < 9:
        return 0
    
    # Signal line (9-period EMA of MACD line)
    signal = calculate_ema(macd_line, 9)
    
    if not signal:
        return 0
    
    # Histogram
    histogram = macd_line[-1] - signal[-1]
    return histogram

def calculate_atr(candles, period=14):
    """Calculate Average True Range"""
    if len(candles) < period + 1:
        return 0
    
    trs = []
    for i in range(1, len(candles)):
        high = float(candles[i].get('high', 0))
        low = float(candles[i].get('low', 0))
        prev_close = float(candles[i-1].get('close', 0))
        
        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )
        trs.append(tr)
    
    if len(trs) < period:
        return sum(trs) / len(trs) if trs else 0
    
    return sum(trs[-period:]) / period

def analyze_orderbook(symbol, depth=10):
    """Analyze order book imbalance"""
    try:
        r = get(f"/v2/l2orderbook/{symbol}")
        
        if "result" not in r:
            return "NEUTRAL", 0
        
        bids = r["result"].get("buy", [])[:depth]
        asks = r["result"].get("sell", [])[:depth]
        
        bid_volume = sum(float(b.get('size', 0)) * float(b.get('price', 0)) for b in bids)
        ask_volume = sum(float(a.get('size', 0)) * float(a.get('price', 0)) for a in asks)
        
        total = bid_volume + ask_volume
        if total == 0:
            return "NEUTRAL", 0
        
        imbalance = (bid_volume - ask_volume) / total
        
        if imbalance > 0.3:
            return "BUY_PRESSURE", imbalance
        elif imbalance < -0.3:
            return "SELL_PRESSURE", imbalance
        return "NEUTRAL", imbalance
    except Exception as e:
        return "NEUTRAL", 0

def multi_tf_bullish(symbol):
    """Check if bullish on multiple timeframes"""
    timeframes = ["5m", "15m"]  # Skip 1h to reduce API calls
    bullish_count = 0
    
    for tf in timeframes:
        candles = get_candles(symbol, tf, 25)
        if len(candles) < 20:
            continue
        
        closes = [float(c.get('close', 0)) for c in candles]
        sma20 = sum(closes[-20:]) / 20
        
        if closes[-1] > sma20:
            bullish_count += 1
    
    return bullish_count >= 1  # At least 1 of 2 bullish

def dynamic_stop_loss(entry_price, atr, leverage):
    """Calculate ATR-based stop loss"""
    if atr <= 0 or entry_price <= 0:
        return -5.0  # Fallback to fixed stop
    
    stop_distance = atr * ATR_STOP_MULTIPLIER
    stop_percent = (stop_distance / entry_price) * 100 * leverage
    
    # Clamp between min and max
    return max(MAX_STOP_LOSS, min(MIN_STOP_LOSS, -stop_percent))

def dynamic_trail_distance(atr, entry_price, leverage):
    """Calculate ATR-based trailing distance"""
    if atr <= 0 or entry_price <= 0:
        return 1.5  # Fallback
    
    atr_percent = (atr / entry_price) * 100 * leverage * ATR_TRAIL_MULTIPLIER
    
    # Clamp between min and max
    return max(MIN_TRAIL_DIST, min(MAX_TRAIL_DIST, atr_percent))

def dynamic_position_size(volatility, base_size=BASE_POSITION_SIZE):
    """Size inversely proportional to volatility"""
    if volatility < 5:
        return base_size * 1.2  # 78% for stable
    elif volatility < 10:
        return base_size * 1.0  # 65% for normal
    elif volatility < 15:
        return base_size * 0.8  # 52% for volatile
    else:
        return base_size * 0.6  # 39% for very volatile

# ============================================
# Load products
# ============================================
PRODUCTS = {}
resp = session.get(BASE + "/v2/products", timeout=10).json()
for p in resp.get("result", []):
    if p.get("contract_type") == "perpetual_futures" and p.get("state") == "live":
        PRODUCTS[p.get("symbol")] = {
            "id": p.get("id"),
            "cv": float(p.get("contract_value", 1)),
            "tick": float(p.get("tick_size", 0.0001))
        }

# ============================================
# WebSocket Handler
# ============================================
class DeltaWebSocket:
    def __init__(self):
        self.ws = None
        self.running = False
        self.msg_count = 0

    def on_message(self, ws, message):
        global tickers, ws_update_count
        try:
            data = json.loads(message)
            msg_type = data.get("type")

            if self.msg_count < 3:
                log(f"[WS] MSG #{self.msg_count}: type={msg_type}")
                self.msg_count += 1

            if msg_type == "v2/ticker":
                symbol = data.get("symbol")
                if symbol:
                    with ticker_lock:
                        tickers[symbol] = data
                    ws_update_count += 1

            elif msg_type == "subscriptions":
                channels = data.get("channels", [])
                log(f"[WS] Subscribed: {len(channels)} channels")

        except Exception as e:
            log(f"[WS] Parse error: {e}")

    def on_error(self, ws, error):
        log(f"[WS] Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        log(f"[WS] Closed: {close_status_code}")
        self.running = False

    def on_open(self, ws):
        global ws_connected
        log("[WS] Connected!")
        ws_connected = True

        symbols = list(PRODUCTS.keys())
        batch_size = 50
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            subscribe_msg = {
                "type": "subscribe",
                "payload": {
                    "channels": [{
                        "name": "v2/ticker",
                        "symbols": batch
                    }]
                }
            }
            ws.send(json.dumps(subscribe_msg))
            time.sleep(0.1)

        log(f"[WS] Subscribed to {len(symbols)} symbols")

    def start(self):
        self.running = True

        def run():
            while self.running:
                try:
                    self.ws = websocket.WebSocketApp(
                        WS_URL,
                        on_message=self.on_message,
                        on_error=self.on_error,
                        on_close=self.on_close,
                        on_open=self.on_open
                    )
                    self.ws.run_forever(ping_interval=30, ping_timeout=10)
                except Exception as e:
                    log(f"[WS] Error: {e}")

                if self.running:
                    log("[WS] Reconnecting in 2s...")
                    time.sleep(2)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        return thread

# ============================================
# Trading Functions
# ============================================

log("=" * 70)
log("DELTA WEBSOCKET v6 - ADVANCED TRADING BOT")
log("=" * 70)
log(f"Products: {len(PRODUCTS)} | ATR Stop: {ATR_STOP_MULTIPLIER}x | ATR Trail: {ATR_TRAIL_MULTIPLIER}x")
log(f"Dynamic Stops: {MIN_STOP_LOSS}% to {MAX_STOP_LOSS}% | Min Score: {MIN_SCORE}")

# Get equity
w = get("/v2/wallet/balances")
start_equity = float(w.get("meta", {}).get("net_equity", 0))
log(f"Starting Equity: ${start_equity:.2f} (Rs.{start_equity * USD_TO_INR:.0f})")

# Load initial tickers
r = session.get(BASE + "/v2/tickers", timeout=5).json()
for t in r.get("result", []):
    tickers[t.get("symbol")] = t
log(f"Initial tickers: {len(tickers)}")

# Start WebSocket
delta_ws = DeltaWebSocket()
delta_ws.start()
log("WebSocket started, waiting 3s...")
time.sleep(3)

def get_ticker(sym):
    with ticker_lock:
        return tickers.get(sym, {})

def is_coin_blacklisted(sym):
    if sym in coin_blacklist:
        if time.time() < coin_blacklist[sym]:
            return True
        else:
            del coin_blacklist[sym]
    return False

def blacklist_coin(sym):
    coin_blacklist[sym] = time.time() + COIN_BLACKLIST_TIME

def check_cooldown():
    if time.time() < last_exit_time + COOLDOWN_AFTER_EXIT:
        remaining = int(last_exit_time + COOLDOWN_AFTER_EXIT - time.time())
        return True, remaining
    return False, 0

def check_drawdown(current_equity):
    if start_equity > 0:
        drawdown = ((start_equity - current_equity) / start_equity) * 100
        if drawdown >= DAILY_DRAWDOWN_LIMIT:
            return True, drawdown
    return False, 0

def calculate_volatility(ticker):
    high = float(ticker.get("high", 0))
    low = float(ticker.get("low", 0))
    if low > 0:
        return ((high - low) / low) * 100
    return 100

def calculate_v6_score(symbol, ticker):
    """V6 Advanced Scoring with Real Indicators"""
    score = 0
    signals = []
    
    price = float(ticker.get("mark_price", 0))
    chg = float(ticker.get("mark_change_24h", 0))
    vol = float(ticker.get("turnover_usd", 0))
    high = float(ticker.get("high", 0))
    low = float(ticker.get("low", 0))
    funding = float(ticker.get("funding_rate", 0)) * 100
    
    if price <= 0 or vol < MIN_VOLUME:
        return 0, [], 0
    
    # Get candles for real indicators
    candles = get_candles(symbol, "5m", 50)
    
    if len(candles) < 20:
        # Fallback to V5 scoring if no candles
        volatility = calculate_volatility(ticker)
        rsi = ((price - low) / (high - low)) * 100 if high > low else 50
        
        if rsi < 35:
            score += 20
        if 2 <= chg <= 15:
            score += 20
        if vol > 5000000:
            score += 10
        
        return score, ["FALLBACK"], volatility
    
    # 1. Real RSI (25 points max)
    rsi = calculate_rsi(candles)
    if rsi < 25:
        score += 25
        signals.append(f"RSI({rsi:.0f})")
    elif rsi < 35:
        score += 20
        signals.append(f"RSI({rsi:.0f})")
    elif rsi < 45:
        score += 10
    
    # 2. MACD Histogram (20 points max)
    macd_hist = calculate_macd(candles)
    if macd_hist > 0:
        score += 20
        signals.append("MACD+")
    elif macd_hist < 0:
        score -= 5  # Penalty for bearish MACD
    
    # 3. Order Book Imbalance (15 points max)
    pressure, imbalance = analyze_orderbook(symbol)
    if pressure == "BUY_PRESSURE":
        score += 15
        signals.append(f"OB+{imbalance:.0%}")
    elif pressure == "NEUTRAL":
        score += 5
    else:
        score -= 10  # Penalty for sell pressure
        signals.append("OB-")
    
    # 4. Momentum (20 points max)
    if 5 <= chg <= 15:
        score += 20
        signals.append(f"MOM({chg:.1f}%)")
    elif 2 <= chg < 5:
        score += 15
    elif 0 < chg < 2:
        score += 10
    
    # 5. Volume (10 points max)
    if vol > 10_000_000:
        score += 10
        signals.append(f"VOL(${vol/1e6:.0f}M)")
    elif vol > 5_000_000:
        score += 7
    
    # 6. Multi-TF Confirmation (10 points bonus)
    if multi_tf_bullish(symbol):
        score += 10
        signals.append("MTF+")
    
    # 7. Low volatility bonus
    volatility = calculate_volatility(ticker)
    if volatility < 8:
        score += 5
        signals.append(f"STABLE")
    
    # Calculate ATR for dynamic stops
    atr = calculate_atr(candles)
    
    return score, signals, volatility, atr

def find_best(equity):
    with ticker_lock:
        ticker_list = list(tickers.values())

    candidates = []
    skipped_volatile = 0
    
    for t in ticker_list:
        sym = t.get("symbol")
        if sym not in PRODUCTS:
            continue

        if is_coin_blacklisted(sym):
            continue

        price = float(t.get("mark_price", 0))
        volatility = calculate_volatility(t)
        
        if volatility > MAX_VOLATILITY:
            skipped_volatile += 1
            continue

        cv = PRODUCTS[sym]["cv"]
        pos_size = dynamic_position_size(volatility)
        
        if (price * cv) / LEVERAGE > equity * pos_size:
            continue

        result = calculate_v6_score(sym, t)
        
        if len(result) == 4:
            score, signals, vol, atr = result
        else:
            score, signals, vol = result
            atr = 0
        
        if score >= MIN_SCORE:
            candidates.append({
                "sym": sym, 
                "price": price, 
                "score": score,
                "volatility": vol,
                "atr": atr,
                "signals": signals, 
                "id": PRODUCTS[sym]["id"], 
                "cv": cv,
                "tick": PRODUCTS[sym]["tick"],
                "pos_size": dynamic_position_size(vol)
            })

    if skipped_volatile > 0:
        log(f"[SCAN] Skipped {skipped_volatile} high-volatility coins")

    if candidates:
        return max(candidates, key=lambda x: x["score"])
    return None

def find_position():
    r = get("/v2/positions/margined")
    for pos in r.get("result", []):
        sz = pos.get("size")
        if sz is None:
            continue
        sz = float(sz)
        if sz != 0:
            entry = pos.get("entry_price")
            if entry is None or entry == 0:
                continue
            return {
                "sym": pos.get("product", {}).get("symbol", ""),
                "id": pos.get("product_id", 0),
                "size": sz,
                "entry": float(entry)
            }
    return None

def cancel_all_orders(product_id):
    try:
        r = delete(f"/v2/orders/all?product_id={product_id}")
        return r.get("success", False)
    except:
        return False

def close_position(pos, reason, pnl, price):
    global wins, losses, consecutive_losses, last_exit_time
    global current_atr, current_stop, current_trail_dist

    log(f"{'='*50}")
    log(f"{reason}: {pos['sym']} | P&L: {pnl:+.2f}%")
    log(f"  Stop was: {current_stop:.1f}% | Trail dist: {current_trail_dist:.1f}%")

    start = time.time()
    r = post("/v2/orders", {
        "product_id": pos["id"],
        "size": int(abs(pos["size"])),
        "side": "sell",
        "order_type": "market_order"
    })
    elapsed = (time.time() - start) * 1000

    if r.get("success"):
        log(f"  Executed in {elapsed:.0f}ms")
    else:
        log(f"  Error: {r.get('error', r)}")

    if pnl >= 0:
        wins += 1
        consecutive_losses = 0
        log(f"  Result: WIN +{pnl:.1f}%")
    else:
        losses += 1
        consecutive_losses += 1
        log(f"  Result: LOSS {pnl:.1f}% | Consecutive: {consecutive_losses}")

    total = wins + losses
    wr = (wins / total * 100) if total > 0 else 0
    log(f"  Stats: {wins}W/{losses}L ({wr:.0f}%)")

    last_exit_time = time.time()
    blacklist_coin(pos['sym'])

    # Reset dynamic values
    current_atr = 0
    current_stop = -5
    current_trail_dist = 1.5

    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        global trading_paused, pause_reason
        trading_paused = True
        pause_reason = f"{consecutive_losses} consecutive losses"
        log(f"  *** TRADING PAUSED: {pause_reason} ***")

    log(f"{'='*50}")

    return r.get("success", False)

def place_limit_order(product_id, size, price, tick_size):
    rounded_price = round(price / tick_size) * tick_size
    log(f"  Limit order: {size}x @ ${rounded_price:.6f}")
    
    r = post("/v2/orders", {
        "product_id": product_id,
        "size": size,
        "side": "buy",
        "order_type": "limit_order",
        "limit_price": str(rounded_price),
        "time_in_force": "gtc"
    })
    
    return r

# ============================================
# MAIN TRADING LOOP
# ============================================

log("=" * 70)
log("STARTING TRADING LOOP (v6 - Advanced)")
log("=" * 70)

peak_pnl = 0
last_scan = 0
last_log = 0
last_eq_check = 0
last_ws_log = 0
eq = start_equity
slippage_check_done = False

while True:
    try:
        loop_start = time.time()

        # Log WS stats every 15s
        if time.time() - last_ws_log > 15:
            last_ws_log = time.time()
            blacklisted = [s for s, t in coin_blacklist.items() if time.time() < t]
            log(f"[WS] Updates: {ws_update_count} | Cache: {len(candle_cache)} | BL: {blacklisted[:2]}")

        # Check equity every 2s
        if time.time() - last_eq_check > 2:
            w = get("/v2/wallet/balances")
            eq = float(w.get("meta", {}).get("net_equity", 0))
            last_eq_check = time.time()

            hit_limit, dd = check_drawdown(eq)
            if hit_limit and not trading_paused:
                trading_paused = True
                pause_reason = f"Daily drawdown limit ({dd:.1f}%)"
                log(f"*** TRADING PAUSED: {pause_reason} ***")

        inr = eq * USD_TO_INR

        if inr >= 10000:
            log(f"TARGET! Rs.{inr:.0f}")
            break

        if trading_paused:
            if time.time() - last_log > 5:
                last_log = time.time()
                log(f"[PAUSED] {pause_reason} | Rs.{inr:.0f}")
            time.sleep(1)
            continue

        pos = find_position()

        if pos:
            t = get_ticker(pos["sym"])
            price = float(t.get("mark_price", 0))
            entry = pos["entry"]

            if entry > 0 and price > 0:
                pnl = ((price - entry) / entry) * 100 * LEVERAGE

                # V6: Check for immediate slippage after entry
                if entry_time > 0 and not slippage_check_done:
                    time_since_entry = time.time() - entry_time
                    if time_since_entry >= SLIPPAGE_CHECK_DELAY:
                        slippage_check_done = True
                        if pnl < MAX_IMMEDIATE_LOSS:
                            log(f"[SLIPPAGE] Immediate loss {pnl:.1f}% detected!")
                            close_position(pos, "SLIPPAGE_EXIT", pnl, price)
                            entry_time = 0
                            peak_pnl = 0
                            continue

                if pnl > peak_pnl:
                    peak_pnl = pnl
                    if peak_pnl >= TRAIL_START:
                        log(f"[TRAIL] Peak: {peak_pnl:+.1f}% | Dist: {current_trail_dist:.1f}%")

                if time.time() - last_log > 0.2:
                    last_log = time.time()
                    trail = f" TRAIL@{peak_pnl-current_trail_dist:+.1f}%" if peak_pnl >= TRAIL_START else ""
                    log(f"{pos['sym']} ${price:.6f} | {pnl:+.2f}% (pk:{peak_pnl:+.1f}){trail} | SL:{current_stop:.1f}% | Rs.{inr:.0f}")

                # V6: Dynamic stop loss
                if pnl <= current_stop:
                    close_position(pos, "STOP", pnl, price)
                    entry_time = 0
                    peak_pnl = 0
                    continue

                if pnl >= TAKE_PROFIT:
                    close_position(pos, "PROFIT", pnl, price)
                    entry_time = 0
                    peak_pnl = 0
                    continue

                # V6: Dynamic trailing distance
                if peak_pnl >= TRAIL_START and pnl <= peak_pnl - current_trail_dist:
                    close_position(pos, f"TRAIL({peak_pnl:.1f}%)", pnl, price)
                    entry_time = 0
                    peak_pnl = 0
                    continue

            time.sleep(0.025)

        else:
            peak_pnl = 0
            slippage_check_done = False

            if pending_order:
                if time.time() - pending_order["time"] > ORDER_TIMEOUT:
                    log(f"[ORDER] Cancelling timed out order for {pending_order['sym']}")
                    cancel_all_orders(pending_order["id"])
                    pending_order = None

            in_cooldown, remaining = check_cooldown()
            if in_cooldown:
                if time.time() - last_log > 1:
                    last_log = time.time()
                    log(f"[COOLDOWN] {remaining}s remaining | Rs.{inr:.0f}")
                time.sleep(0.5)
                continue

            if time.time() - last_scan > 0.5:
                last_scan = time.time()
                best = find_best(eq)

                if best and eq > 0.05:
                    size = int((eq * LEVERAGE * best["pos_size"]) / (best["price"] * best["cv"]))

                    if size >= 1:
                        log(f"{'='*50}")
                        log(f"BUY: {best['sym']} Score:{best['score']:.0f} | Vol:{best['volatility']:.1f}%")
                        log(f"  Signals: {' '.join(best['signals'])}")
                        log(f"  ${best['price']:.6f} | ATR:${best['atr']:.6f} | x{size}")
                        
                        # V6: Calculate dynamic stop and trail
                        current_atr = best['atr']
                        current_stop = dynamic_stop_loss(best['price'], best['atr'], LEVERAGE)
                        current_trail_dist = dynamic_trail_distance(best['atr'], best['price'], LEVERAGE)
                        
                        log(f"  Dynamic Stop: {current_stop:.1f}% | Trail Dist: {current_trail_dist:.1f}%")

                        limit_price = best["price"] * (1 + LIMIT_ORDER_BUFFER)
                        
                        start = time.time()
                        r = place_limit_order(
                            best["id"], 
                            size, 
                            limit_price, 
                            best["tick"]
                        )
                        elapsed = (time.time() - start) * 1000

                        if r.get("success"):
                            log(f"  LIMIT ORDER PLACED in {elapsed:.0f}ms!")
                            pending_order = {
                                "sym": best["sym"],
                                "id": best["id"],
                                "time": time.time()
                            }
                            entry_time = time.time()
                        else:
                            log(f"  Failed: {r.get('error', r)}")
                            current_atr = 0
                            current_stop = -5
                            current_trail_dist = 1.5
                        log(f"{'='*50}")

            time.sleep(0.1)

    except Exception as e:
        log(f"[ERROR] {e}")
        import traceback
        log(f"[TRACE] {traceback.format_exc()}")
        time.sleep(0.5)

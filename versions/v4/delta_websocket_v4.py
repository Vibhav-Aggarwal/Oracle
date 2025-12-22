#!/usr/bin/env python3
"""
DELTA WEBSOCKET v4 - ADVANCED TRADING BOT
==========================================
Features from GitHub research:
1. Real RSI/MACD from candle data (Freqtrade-style)
2. Multi-timeframe confirmation (Jesse-style)
3. Confidence scoring (jita3-style)
4. Order book analysis (Hummingbot-style)
5. Risk management (v3 features retained)
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
from collections import deque

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
STOP_LOSS = -5
TAKE_PROFIT = 10
TRAIL_START = 3
TRAIL_DIST = 1.5
POSITION_SIZE = 0.65
LOG = "/home/vibhavaggarwal/delta_websocket_v4.log"

# RISK MANAGEMENT (from v3)
COOLDOWN_AFTER_EXIT = 30
COIN_BLACKLIST_TIME = 180
MAX_CONSECUTIVE_LOSSES = 3
DAILY_DRAWDOWN_LIMIT = 10

# ADVANCED SETTINGS (v4 NEW)
MIN_CONFIDENCE = 0.6          # Minimum confidence to enter (0-1)
RSI_PERIOD = 14               # Real RSI period
MACD_FAST = 12                # MACD fast EMA
MACD_SLOW = 26                # MACD slow EMA
MACD_SIGNAL = 9               # MACD signal line
MIN_VOLUME_USD = 1000000      # Minimum 24h volume
ORDERBOOK_IMBALANCE = 0.2     # 20% buy/sell imbalance for signal

# Connection pooling
session = requests.Session()
adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=Retry(total=0))
session.mount('https://', adapter)

# State
tickers = {}
ticker_lock = threading.Lock()
candle_cache = {}  # {symbol: {timeframe: [candles]}}
orderbook_cache = {}
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

def get(p, timeout=1.0):
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

# ============ TECHNICAL INDICATORS ============

def calculate_ema(prices, period):
    """Exponential Moving Average"""
    if len(prices) < period:
        return None
    multiplier = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_real_rsi(closes, period=14):
    """Real RSI using historical closes"""
    if len(closes) < period + 1:
        return 50  # Default
    
    gains = []
    losses_list = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(max(0, change))
        losses_list.append(max(0, -change))
    
    if len(gains) < period:
        return 50
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses_list[-period:]) / period
    
    if avg_loss == 0:
        return 100
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_macd(closes, fast=12, slow=26, signal=9):
    """MACD indicator"""
    if len(closes) < slow + signal:
        return None, None, None
    
    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    
    if ema_fast is None or ema_slow is None:
        return None, None, None
    
    macd_line = ema_fast - ema_slow
    
    # Calculate signal line (EMA of MACD line) - simplified
    signal_line = macd_line * 0.9  # Approximation
    histogram = macd_line - signal_line
    
    return macd_line, signal_line, histogram

def calculate_bollinger(closes, period=20, std_mult=2):
    """Bollinger Bands"""
    if len(closes) < period:
        return None, None, None
    
    recent = closes[-period:]
    sma = sum(recent) / period
    variance = sum((c - sma)**2 for c in recent) / period
    std_dev = variance ** 0.5
    
    upper = sma + std_mult * std_dev
    lower = sma - std_mult * std_dev
    
    return lower, sma, upper

def get_candles(symbol, resolution="1m", limit=50):
    """Fetch historical candles from Delta API"""
    try:
        product_id = PRODUCTS.get(symbol, {}).get("id")
        if not product_id:
            return []
        
        end_time = int(time.time())
        start_time = end_time - (limit * 60 if resolution == "1m" else limit * 300)
        
        url = f"/v2/history/candles?resolution={resolution}&symbol={symbol}&start={start_time}&end={end_time}"
        r = session.get(BASE + url, timeout=2).json()
        
        candles = r.get("result", [])
        return sorted(candles, key=lambda x: x.get("time", 0))
    except:
        return []

def get_orderbook(symbol):
    """Fetch order book for whale detection"""
    try:
        url = f"/v2/l2orderbook/{symbol}"
        r = session.get(BASE + url, timeout=1).json()
        return r.get("result", {})
    except:
        return {}

def analyze_orderbook(symbol):
    """Analyze order book for buy/sell pressure"""
    book = get_orderbook(symbol)
    
    if not book:
        return "NEUTRAL", 0
    
    buys = book.get("buy", [])[:10]
    sells = book.get("sell", [])[:10]
    
    if not buys or not sells:
        return "NEUTRAL", 0
    
    buy_volume = sum(float(b.get("size", 0)) for b in buys)
    sell_volume = sum(float(s.get("size", 0)) for s in sells)
    
    total = buy_volume + sell_volume
    if total == 0:
        return "NEUTRAL", 0
    
    imbalance = (buy_volume - sell_volume) / total
    
    if imbalance > ORDERBOOK_IMBALANCE:
        return "BUY_PRESSURE", imbalance
    elif imbalance < -ORDERBOOK_IMBALANCE:
        return "SELL_PRESSURE", imbalance
    return "NEUTRAL", imbalance

# ============ CONFIDENCE SCORING ============

def calculate_confidence(ticker, candles):
    """Calculate entry confidence score (0-1)"""
    confidence = 0
    signals = []
    
    sym = ticker.get("symbol")
    price = float(ticker.get("mark_price", 0))
    chg = float(ticker.get("mark_change_24h", 0))
    vol = float(ticker.get("turnover_usd", 0))
    funding = float(ticker.get("funding_rate", 0)) * 100
    
    if not candles or len(candles) < 30:
        return 0.3, ["NO_DATA"]
    
    closes = [float(c.get("close", 0)) for c in candles if c.get("close")]
    
    if len(closes) < 20:
        return 0.3, ["INSUFFICIENT_CANDLES"]
    
    # 1. RSI Signal (0-0.25)
    rsi = calculate_real_rsi(closes, RSI_PERIOD)
    if rsi < 25:
        confidence += 0.25
        signals.append(f"RSI_OVERSOLD({rsi:.0f})")
    elif rsi < 35:
        confidence += 0.15
        signals.append(f"RSI_LOW({rsi:.0f})")
    elif rsi < 45:
        confidence += 0.08
    
    # 2. MACD Signal (0-0.20)
    macd, signal, histogram = calculate_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
    if macd is not None and histogram is not None:
        if histogram > 0 and macd > 0:
            confidence += 0.20
            signals.append("MACD_BULLISH")
        elif histogram > 0:
            confidence += 0.10
            signals.append("MACD_CROSS_UP")
    
    # 3. Bollinger Bands (0-0.15)
    lower, middle, upper = calculate_bollinger(closes)
    if lower is not None and price < lower:
        confidence += 0.15
        signals.append("BB_OVERSOLD")
    elif lower is not None and price < middle:
        confidence += 0.08
    
    # 4. Momentum (0-0.15)
    if 3 <= chg <= 12:
        confidence += 0.15
        signals.append(f"MOM({chg:.1f}%)")
    elif 1 <= chg < 3:
        confidence += 0.08
    elif chg < 0:
        confidence -= 0.10  # Penalty for negative momentum
    
    # 5. Volume (0-0.10)
    if vol > 10000000:
        confidence += 0.10
        signals.append(f"VOL(${vol/1e6:.0f}M)")
    elif vol > 5000000:
        confidence += 0.06
    elif vol > 2000000:
        confidence += 0.03
    
    # 6. Order Book Pressure (0-0.10)
    pressure, imbalance = analyze_orderbook(sym)
    if pressure == "BUY_PRESSURE":
        confidence += 0.10
        signals.append(f"WHALES_BUY({imbalance:.0%})")
    elif pressure == "SELL_PRESSURE":
        confidence -= 0.05
        signals.append(f"WHALES_SELL")
    
    # 7. Funding Rate (0-0.05)
    if funding > 0.05:
        confidence += 0.05
        signals.append(f"FUND({funding:.2f}%)")
    elif funding < -0.05:
        confidence -= 0.03  # Penalty for negative funding
    
    # Clamp confidence to 0-1
    confidence = max(0, min(1, confidence))
    
    return confidence, signals

# ============ MULTI-TIMEFRAME ============

def check_multi_timeframe(symbol):
    """Check multiple timeframes for confirmation"""
    confirmations = 0
    tf_signals = []
    
    # Check 1m timeframe
    candles_1m = get_candles(symbol, "1m", 50)
    if candles_1m:
        closes = [float(c.get("close", 0)) for c in candles_1m if c.get("close")]
        if len(closes) >= 20:
            rsi = calculate_real_rsi(closes, 14)
            if rsi < 40:
                confirmations += 1
                tf_signals.append(f"1m:RSI{rsi:.0f}")
    
    # Check 5m timeframe (approximate from 1m)
    if len(candles_1m) >= 25:
        # Group into 5m candles
        closes_5m = []
        for i in range(0, len(candles_1m)-4, 5):
            group = candles_1m[i:i+5]
            if group:
                closes_5m.append(float(group[-1].get("close", 0)))
        
        if len(closes_5m) >= 10:
            rsi_5m = calculate_real_rsi(closes_5m, 10)
            if rsi_5m < 45:
                confirmations += 1
                tf_signals.append(f"5m:RSI{rsi_5m:.0f}")
    
    # Trend check (price above short-term EMA)
    if closes_1m := [float(c.get("close", 0)) for c in candles_1m[-20:] if c.get("close")]:
        if len(closes_1m) >= 10:
            ema = calculate_ema(closes_1m, 10)
            if ema and closes_1m[-1] > ema * 0.995:  # Within 0.5% of EMA
                confirmations += 1
                tf_signals.append("TREND_OK")
    
    return confirmations, tf_signals

# Load products
PRODUCTS = {}
resp = session.get(BASE + "/v2/products", timeout=10).json()
for p in resp.get("result", []):
    if p.get("contract_type") == "perpetual_futures" and p.get("state") == "live":
        PRODUCTS[p.get("symbol")] = {
            "id": p.get("id"),
            "cv": float(p.get("contract_value", 1))
        }

# ============ WEBSOCKET ============

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
            ws.send(json.dumps({
                "type": "subscribe",
                "payload": {"channels": [{"name": "v2/ticker", "symbols": batch}]}
            }))
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

# ============ HELPERS ============

def is_coin_blacklisted(sym):
    if sym in coin_blacklist:
        if time.time() < coin_blacklist[sym]:
            return True
        else:
            del coin_blacklist[sym]
    return False

def blacklist_coin(sym):
    coin_blacklist[sym] = time.time() + COIN_BLACKLIST_TIME
    log(f"[BLACKLIST] {sym} blocked for {COIN_BLACKLIST_TIME}s")

def check_cooldown():
    if time.time() < last_exit_time + COOLDOWN_AFTER_EXIT:
        return True, int(last_exit_time + COOLDOWN_AFTER_EXIT - time.time())
    return False, 0

def check_drawdown(current_equity):
    if start_equity > 0:
        drawdown = ((start_equity - current_equity) / start_equity) * 100
        if drawdown >= DAILY_DRAWDOWN_LIMIT:
            return True, drawdown
    return False, 0

def get_ticker(sym):
    with ticker_lock:
        return tickers.get(sym, {})

# ============ ADVANCED SCANNER ============

def find_best_advanced(equity):
    """Advanced scanner with confidence scoring and multi-TF"""
    with ticker_lock:
        ticker_list = list(tickers.values())

    candidates = []
    
    for t in ticker_list:
        sym = t.get("symbol")
        if sym not in PRODUCTS or is_coin_blacklisted(sym):
            continue

        price = float(t.get("mark_price", 0))
        vol = float(t.get("turnover_usd", 0))

        # Basic filters
        if vol < MIN_VOLUME_USD or price <= 0:
            continue

        cv = PRODUCTS[sym]["cv"]
        if (price * cv) / LEVERAGE > equity * POSITION_SIZE:
            continue

        # Fetch candles for this symbol
        candles = get_candles(sym, "1m", 50)
        
        # Calculate confidence
        confidence, signals = calculate_confidence(t, candles)
        
        # Skip low confidence
        if confidence < MIN_CONFIDENCE:
            continue
        
        # Multi-timeframe confirmation
        tf_confirms, tf_signals = check_multi_timeframe(sym)
        
        # Boost confidence with TF confirmations
        confidence += tf_confirms * 0.05
        confidence = min(1, confidence)
        
        candidates.append({
            "sym": sym,
            "price": price,
            "confidence": confidence,
            "signals": signals + tf_signals,
            "tf_confirms": tf_confirms,
            "vol": vol,
            "id": PRODUCTS[sym]["id"],
            "cv": cv
        })

    if candidates:
        # Sort by confidence
        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        best = candidates[0]
        
        # Log top 3 candidates
        if len(candidates) >= 3:
            log(f"[SCAN] Top 3: {candidates[0]['sym']}({candidates[0]['confidence']:.0%}), {candidates[1]['sym']}({candidates[1]['confidence']:.0%}), {candidates[2]['sym']}({candidates[2]['confidence']:.0%})")
        
        return best
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

def close_position(pos, reason, pnl, price):
    global wins, losses, consecutive_losses, last_exit_time, trading_paused, pause_reason

    log(f"{'='*50}")
    log(f"{reason}: {pos['sym']} | P&L: {pnl:+.2f}%")

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
    log(f"  Cooldown: {COOLDOWN_AFTER_EXIT}s")
    blacklist_coin(pos['sym'])

    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        trading_paused = True
        pause_reason = f"{consecutive_losses} consecutive losses"
        log(f"  *** TRADING PAUSED: {pause_reason} ***")

    log(f"{'='*50}")
    return r.get("success", False)

# ============ MAIN ============

log("=" * 70)
log("DELTA WEBSOCKET v4 - ADVANCED TRADING BOT")
log("=" * 70)
log(f"Features: Real RSI/MACD | Multi-TF | Confidence Scoring | Order Book")
log(f"Min Confidence: {MIN_CONFIDENCE:.0%} | RSI Period: {RSI_PERIOD}")
log(f"Products: {len(PRODUCTS)} | Cooldown: {COOLDOWN_AFTER_EXIT}s")

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

log("=" * 70)
log("STARTING ADVANCED TRADING LOOP (v4)")
log("=" * 70)

peak_pnl = 0
last_scan = 0
last_log = 0
last_eq_check = 0
last_ws_log = 0
eq = start_equity

while True:
    try:
        # Log WS stats every 20s
        if time.time() - last_ws_log > 20:
            last_ws_log = time.time()
            blacklisted = [s for s, t in coin_blacklist.items() if time.time() < t]
            log(f"[WS] Updates: {ws_update_count} | Blacklist: {blacklisted[:3]}")

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
            log(f"TARGET REACHED! Rs.{inr:.0f}")
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
            high = float(t.get("high", 0))
            low = float(t.get("low", 0))
            entry = pos["entry"]

            if entry > 0 and price > 0:
                pnl = ((price - entry) / entry) * 100 * LEVERAGE

                if pnl > peak_pnl:
                    peak_pnl = pnl
                    if peak_pnl >= TRAIL_START:
                        log(f"[TRAIL] Peak: {peak_pnl:+.1f}%")

                if time.time() - last_log > 0.2:
                    last_log = time.time()
                    trail = f" TRAIL@{peak_pnl-TRAIL_DIST:+.1f}%" if peak_pnl >= TRAIL_START else ""
                    log(f"{pos['sym']} ${price:.6f} | {pnl:+.2f}% (pk:{peak_pnl:+.1f}){trail} | Rs.{inr:.0f}")

                if pnl <= STOP_LOSS:
                    close_position(pos, "STOP", pnl, price)
                    peak_pnl = 0
                    continue

                if pnl >= TAKE_PROFIT:
                    close_position(pos, "PROFIT", pnl, price)
                    peak_pnl = 0
                    continue

                if peak_pnl >= TRAIL_START and pnl <= peak_pnl - TRAIL_DIST:
                    close_position(pos, f"TRAIL({peak_pnl:.1f}%)", pnl, price)
                    peak_pnl = 0
                    continue

            time.sleep(0.025)

        else:
            peak_pnl = 0

            in_cooldown, remaining = check_cooldown()
            if in_cooldown:
                if time.time() - last_log > 1:
                    last_log = time.time()
                    log(f"[COOLDOWN] {remaining}s remaining | Rs.{inr:.0f}")
                time.sleep(0.5)
                continue

            # Scan every 1s (slower due to candle fetching)
            if time.time() - last_scan > 1.0:
                last_scan = time.time()
                best = find_best_advanced(eq)

                if best and eq > 0.05:
                    size = int((eq * LEVERAGE * POSITION_SIZE) / (best["price"] * best["cv"]))

                    if size >= 1:
                        log(f"{'='*50}")
                        log(f"BUY: {best['sym']} | Confidence: {best['confidence']:.0%}")
                        log(f"  Signals: {' '.join(best['signals'][:5])}")
                        log(f"  TF Confirms: {best['tf_confirms']}/3 | ${best['price']:.6f} | x{size}")

                        start = time.time()
                        r = post("/v2/orders", {
                            "product_id": best["id"],
                            "size": size,
                            "side": "buy",
                            "order_type": "market_order"
                        })
                        elapsed = (time.time() - start) * 1000

                        if r.get("success"):
                            log(f"  OPENED in {elapsed:.0f}ms!")
                        else:
                            log(f"  Failed: {r.get('error', r)}")
                        log(f"{'='*50}")

            time.sleep(0.1)

    except Exception as e:
        log(f"[ERROR] {e}")
        time.sleep(0.5)

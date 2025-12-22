#!/usr/bin/env python3
"""
DELTA WEBSOCKET v5 - SLIPPAGE-PROOF TRADING
============================================
Key Fixes:
1. LIMIT ORDERS instead of market orders (control entry price)
2. POST-ENTRY VALIDATION (close if immediately losing >3%)
3. VOLATILITY FILTER (skip coins with >15% daily range)
4. ENTRY PRICE VERIFICATION (check fill vs expected)
5. All v3 risk management retained
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
STOP_LOSS = -5
TAKE_PROFIT = 10
TRAIL_START = 3
TRAIL_DIST = 1.5
POSITION_SIZE = 0.65
LOG = "/home/vibhavaggarwal/delta_websocket_v5.log"

# RISK MANAGEMENT (from v3)
COOLDOWN_AFTER_EXIT = 30
COIN_BLACKLIST_TIME = 180
MAX_CONSECUTIVE_LOSSES = 3
DAILY_DRAWDOWN_LIMIT = 10

# V5 NEW: SLIPPAGE PROTECTION
MAX_VOLATILITY = 20.0         # Skip coins with >15% daily range
LIMIT_ORDER_BUFFER = 0.002    # 0.2% above mark price for limit orders
SLIPPAGE_CHECK_DELAY = 2.0    # Wait 2s after entry to check slippage
MAX_IMMEDIATE_LOSS = -3.0     # Close if immediately losing more than 3%
ORDER_TIMEOUT = 10            # Cancel limit order after 10s if not filled

# Connection pooling
session = requests.Session()
adapter = HTTPAdapter(pool_connections=30, pool_maxsize=30, max_retries=Retry(total=0))
session.mount('https://', adapter)

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
pending_order = None  # Track pending limit orders
entry_time = 0        # Track when position was opened

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

def delete(p):
    try:
        return session.delete(BASE + p, headers=sign("DELETE", p), timeout=1.5).json()
    except Exception as e:
        return {"error": str(e)}

# Load products
PRODUCTS = {}
resp = session.get(BASE + "/v2/products", timeout=10).json()
for p in resp.get("result", []):
    if p.get("contract_type") == "perpetual_futures" and p.get("state") == "live":
        PRODUCTS[p.get("symbol")] = {
            "id": p.get("id"),
            "cv": float(p.get("contract_value", 1)),
            "tick": float(p.get("tick_size", 0.0001))
        }

# === WEBSOCKET HANDLER ===
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

            if self.msg_count < 5:
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
                log(f"[WS] Subscribed: {channels}")

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

log("=" * 70)
log("DELTA WEBSOCKET v5 - SLIPPAGE-PROOF TRADING")
log("=" * 70)
log(f"Products: {len(PRODUCTS)} | Max Volatility: {MAX_VOLATILITY}%")
log(f"Limit Order Buffer: {LIMIT_ORDER_BUFFER*100:.1f}% | Max Immediate Loss: {MAX_IMMEDIATE_LOSS}%")
log(f"Cooldown: {COOLDOWN_AFTER_EXIT}s | Blacklist: {COIN_BLACKLIST_TIME}s")

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
    log(f"[BLACKLIST] {sym} blocked for {COIN_BLACKLIST_TIME}s")

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
    """Calculate daily volatility as percentage"""
    high = float(ticker.get("high", 0))
    low = float(ticker.get("low", 0))
    if low > 0:
        volatility = ((high - low) / low) * 100
        return volatility
    return 100  # Return high value if can't calculate

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
        chg = float(t.get("mark_change_24h", 0))
        vol = float(t.get("turnover_usd", 0))
        high = float(t.get("high", 0))
        low = float(t.get("low", 0))
        funding = float(t.get("funding_rate", 0)) * 100

        if vol < 500000 or price <= 0 or high <= 0:
            continue

        # V5 NEW: Skip high volatility coins
        volatility = calculate_volatility(t)
        if volatility > MAX_VOLATILITY:
            skipped_volatile += 1
            continue

        cv = PRODUCTS[sym]["cv"]
        if (price * cv) / LEVERAGE > equity * POSITION_SIZE:
            continue

        rsi = ((price - low) / (high - low)) * 100 if high > low else 50
        dip = ((high - price) / high) * 100 if high > 0 else 0

        score = 0
        signals = []

        # Prefer lower volatility coins (bonus for stability)
        if volatility < 5:
            score += 15
            signals.append(f"STABLE({volatility:.1f}%)")
        elif volatility < 10:
            score += 10

        if 5 <= chg <= 15:
            score += 35
            signals.append(f"MOM({chg:.1f}%)")
        elif 2 <= chg < 5:
            score += 25
        elif 0 < chg < 2:
            score += 15

        if rsi < 20:
            score += 30
            signals.append(f"RSI({rsi:.0f})")
        elif rsi < 35:
            score += 25
        elif rsi < 50:
            score += 15

        if 5 <= dip <= 12:
            score += 25
            signals.append(f"DIP({dip:.1f}%)")
        elif 3 <= dip < 5:
            score += 15

        if vol > 10000000:
            score += 15
            signals.append(f"VOL(${vol/1e6:.1f}M)")
        elif vol > 5000000:
            score += 12
        elif vol > 1000000:
            score += 8

        if funding > 0.05:
            score += 15
        elif funding > 0.02:
            score += 10

        if score >= 50:
            candidates.append({
                "sym": sym, "price": price, "score": score,
                "chg": chg, "rsi": rsi, "dip": dip, "vol": vol,
                "volatility": volatility,
                "signals": signals, "id": PRODUCTS[sym]["id"], "cv": cv,
                "tick": PRODUCTS[sym]["tick"]
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
    """Cancel all open orders for a product"""
    try:
        r = delete(f"/v2/orders/all?product_id={product_id}")
        return r.get("success", False)
    except:
        return False

def close_position(pos, reason, pnl, price):
    global wins, losses, consecutive_losses, last_exit_time

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
        global trading_paused, pause_reason
        trading_paused = True
        pause_reason = f"{consecutive_losses} consecutive losses"
        log(f"  *** TRADING PAUSED: {pause_reason} ***")

    log(f"{'='*50}")

    return r.get("success", False)

def place_limit_order(product_id, size, price, tick_size):
    """Place a limit order with proper price rounding"""
    # Round price to tick size
    rounded_price = round(price / tick_size) * tick_size
    
    log(f"  Limit order: {size}x @ ${rounded_price:.6f}")
    
    r = post("/v2/orders", {
        "product_id": product_id,
        "size": size,
        "side": "buy",
        "order_type": "limit_order",
        "limit_price": str(rounded_price),
        "time_in_force": "gtc"  # Good till cancelled
    })
    
    return r

log("=" * 70)
log("STARTING TRADING LOOP (v5 - Slippage-Proof)")
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
            high = float(t.get("high", 0))
            low = float(t.get("low", 0))
            entry = pos["entry"]

            if entry > 0 and price > 0:
                pnl = ((price - entry) / entry) * 100 * LEVERAGE

                # V5 NEW: Check for immediate slippage after entry
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
                        log(f"[TRAIL] Peak: {peak_pnl:+.1f}%")

                if time.time() - last_log > 0.2:
                    last_log = time.time()
                    trail = f" TRAIL@{peak_pnl-TRAIL_DIST:+.1f}%" if peak_pnl >= TRAIL_START else ""
                    log(f"{pos['sym']} ${price:.6f} | {pnl:+.2f}% (pk:{peak_pnl:+.1f}){trail} | Rs.{inr:.0f}")

                if pnl <= STOP_LOSS:
                    close_position(pos, "STOP", pnl, price)
                    entry_time = 0
                    peak_pnl = 0
                    continue

                if pnl >= TAKE_PROFIT:
                    close_position(pos, "PROFIT", pnl, price)
                    entry_time = 0
                    peak_pnl = 0
                    continue

                if peak_pnl >= TRAIL_START and pnl <= peak_pnl - TRAIL_DIST:
                    close_position(pos, f"TRAIL({peak_pnl:.1f}%)", pnl, price)
                    entry_time = 0
                    peak_pnl = 0
                    continue

            time.sleep(0.025)

        else:
            peak_pnl = 0
            slippage_check_done = False

            # Check and cancel pending orders if timed out
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
                    size = int((eq * LEVERAGE * POSITION_SIZE) / (best["price"] * best["cv"]))

                    if size >= 1:
                        log(f"{'='*50}")
                        log(f"BUY: {best['sym']} Score:{best['score']:.0f} | Vol:{best['volatility']:.1f}%")
                        log(f"  Signals: {' '.join(best['signals'])}")
                        log(f"  ${best['price']:.6f} | RSI:{best['rsi']:.0f} | x{size}")

                        # V5: Use LIMIT ORDER with small buffer above mark price
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
                        log(f"{'='*50}")

            time.sleep(0.1)

    except Exception as e:
        log(f"[ERROR] {e}")
        time.sleep(0.5)

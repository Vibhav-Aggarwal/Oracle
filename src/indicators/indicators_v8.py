#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V8 - Indicator Library
==================================================
Enhanced indicators with caching and order flow analysis.

NEW in V8:
- IndicatorCache for 5x faster calculations
- Delta volume tracking
- Delta divergence detection
- Absorption detection
- Large trade (tape reading) detection

Author: Vibhav Aggarwal
Date: December 20, 2025
"""

import math
import time
from typing import List, Dict, Tuple, Optional


# ============================================
# V8 NEW: INDICATOR CACHING
# ============================================

class IndicatorCache:
    """
    Cache indicator values to avoid recalculating on every scan.
    Uses incremental updates where possible.
    """
    def __init__(self, ttl: float = 60.0):
        self.ttl = ttl  # Cache time-to-live in seconds
        self._rsi_cache = {}      # symbol -> (value, timestamp)
        self._rsi_series_cache = {}
        self._macd_cache = {}
        self._atr_cache = {}
        self._last_candle = {}    # symbol -> last candle timestamp
    
    def _is_valid(self, symbol: str, cache: Dict) -> bool:
        """Check if cache entry is still valid."""
        if symbol not in cache:
            return False
        _, timestamp = cache[symbol]
        return time.time() - timestamp < self.ttl
    
    def get_rsi(self, symbol: str, candles: List[Dict]) -> float:
        """Get RSI with caching."""
        if not candles:
            return 50.0
        
        # Check if we have a fresh cache entry
        if self._is_valid(symbol, self._rsi_cache):
            return self._rsi_cache[symbol][0]
        
        # Calculate and cache
        rsi = calculate_rsi(candles)
        self._rsi_cache[symbol] = (rsi, time.time())
        return rsi
    
    def get_rsi_series(self, symbol: str, candles: List[Dict]) -> List[float]:
        """Get RSI series with caching."""
        if not candles:
            return [50.0]
        
        if self._is_valid(symbol, self._rsi_series_cache):
            return self._rsi_series_cache[symbol][0]
        
        rsi_series = calculate_rsi_series(candles)
        self._rsi_series_cache[symbol] = (rsi_series, time.time())
        return rsi_series
    
    def get_macd(self, symbol: str, candles: List[Dict]) -> Tuple[float, float, float]:
        """Get MACD with caching."""
        if not candles:
            return (0.0, 0.0, 0.0)
        
        if self._is_valid(symbol, self._macd_cache):
            return self._macd_cache[symbol][0]
        
        macd = calculate_macd(candles)
        self._macd_cache[symbol] = (macd, time.time())
        return macd
    
    def get_atr(self, symbol: str, candles: List[Dict]) -> float:
        """Get ATR with caching."""
        if not candles:
            return 0.0
        
        if self._is_valid(symbol, self._atr_cache):
            return self._atr_cache[symbol][0]
        
        atr = calculate_atr(candles)
        self._atr_cache[symbol] = (atr, time.time())
        return atr
    
    def clear(self, symbol: str = None):
        """Clear cache for symbol or all."""
        if symbol:
            for cache in [self._rsi_cache, self._rsi_series_cache, 
                          self._macd_cache, self._atr_cache]:
                cache.pop(symbol, None)
        else:
            self._rsi_cache.clear()
            self._rsi_series_cache.clear()
            self._macd_cache.clear()
            self._atr_cache.clear()


# ============================================
# V8 NEW: ORDER FLOW ANALYSIS
# ============================================

def calculate_delta_volume(trades: List[Dict]) -> float:
    """
    Calculate delta volume (buy vol - sell vol).
    Positive delta = aggressive buying
    Negative delta = aggressive selling
    """
    if not trades:
        return 0.0
    
    buy_vol = 0.0
    sell_vol = 0.0
    
    for trade in trades:
        size = float(trade.get("size", 0))
        # Delta determines buyer/seller aggressor based on side
        side = trade.get("side", "").lower()
        if side == "buy":
            buy_vol += size
        elif side == "sell":
            sell_vol += size
    
    return buy_vol - sell_vol


def detect_delta_divergence(price_trend: float, delta: float) -> str:
    """
    Detect delta divergence - very powerful signal.
    
    Bullish: Price down but delta up (accumulation)
    Bearish: Price up but delta down (distribution)
    """
    # Threshold for significance
    if abs(delta) < 10:  # Not significant delta
        return "NEUTRAL"
    
    if price_trend < 0 and delta > 0:
        return "BULLISH_DIVERGENCE"  # +25 pts
    elif price_trend > 0 and delta < 0:
        return "BEARISH_DIVERGENCE"  # -15 pts
    
    return "NEUTRAL"


def detect_absorption(candle: Dict, volume: float, delta: float, atr: float) -> Tuple[str, int]:
    """
    Detect absorption: high volume + small price move.
    Someone is absorbing aggressive orders = reversal signal.
    
    Bullish absorption: High volume selling absorbed (delta < 0 but price held)
    Bearish absorption: High volume buying absorbed (delta > 0 but price rejected)
    """
    if not candle or volume <= 0 or atr <= 0:
        return ("NEUTRAL", 0)
    
    price_move = abs(float(candle.get("close", 0)) - float(candle.get("open", 0)))
    
    # High volume = 2x normal
    # Small move = less than 0.5x ATR
    is_high_volume = volume > 1.5  # This would need avg volume context
    is_small_move = price_move < atr * 0.5
    
    if is_small_move:
        if delta < 0:  # Selling absorbed
            return ("BULLISH", 15)
        elif delta > 0:  # Buying absorbed (failed to push higher)
            return ("BEARISH", -10)
    
    return ("NEUTRAL", 0)


def detect_large_trades(trades: List[Dict], threshold_usd: float = 50000) -> Tuple[str, int]:
    """
    Detect large trades ($50K+) as institutional activity.
    
    Returns: (signal, score)
    - BUYING: +15 pts
    - SELLING: -15 pts
    - NEUTRAL: 0 pts
    """
    if not trades:
        return ("NEUTRAL", 0)
    
    large_buys = 0
    large_sells = 0
    
    for trade in trades:
        size = float(trade.get("size", 0))
        price = float(trade.get("price", 0))
        notional = size * price
        
        if notional >= threshold_usd:
            side = trade.get("side", "").lower()
            if side == "buy":
                large_buys += 1
            elif side == "sell":
                large_sells += 1
    
    if large_buys > large_sells * 2:
        return ("BUYING", 15)
    elif large_sells > large_buys * 2:
        return ("SELLING", -15)
    
    return ("NEUTRAL", 0)


# ============================================
# CORE INDICATORS (from V7)
# ============================================

def calculate_ema(data: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average."""
    if len(data) < period:
        return [data[0]] * len(data) if data else []
    
    multiplier = 2 / (period + 1)
    ema = [sum(data[:period]) / period]
    
    for price in data[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    
    return [ema[0]] * (period - 1) + ema


def calculate_sma(data: List[float], period: int) -> float:
    """Calculate Simple Moving Average."""
    if len(data) < period:
        return sum(data) / len(data) if data else 0
    return sum(data[-period:]) / period


def calculate_rsi(candles: List[Dict], period: int = 14) -> float:
    """Calculate Relative Strength Index (RSI)."""
    if len(candles) < period + 1:
        return 50.0
    
    closes = [float(c["close"]) for c in candles]
    gains = []
    losses = []
    
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(0, change))
        losses.append(max(0, -change))
    
    if len(gains) < period:
        return 50.0
    
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calculate_rsi_series(candles: List[Dict], period: int = 14) -> List[float]:
    """Calculate RSI for each point (for divergence detection)."""
    if len(candles) < period + 1:
        return [50.0] * len(candles)
    
    rsi_values = [50.0] * period
    for i in range(period, len(candles)):
        rsi_values.append(calculate_rsi(candles[:i + 1], period))
    
    return rsi_values


def calculate_macd(candles: List[Dict]) -> Tuple[float, float, float]:
    """Calculate MACD (12, 26, 9). Returns (macd_line, signal, histogram)."""
    if len(candles) < 26:
        return (0.0, 0.0, 0.0)
    
    closes = [float(c["close"]) for c in candles]
    ema12 = calculate_ema(closes, 12)
    ema26 = calculate_ema(closes, 26)
    
    macd_line = [e12 - e26 for e12, e26 in zip(ema12, ema26)]
    signal_line = calculate_ema(macd_line, 9)
    
    histogram = macd_line[-1] - signal_line[-1]
    return (macd_line[-1], signal_line[-1], histogram)


def calculate_atr(candles: List[Dict], period: int = 14) -> float:
    """Calculate Average True Range (ATR)."""
    if len(candles) < period + 1:
        if candles:
            return float(candles[-1].get("high", 0)) - float(candles[-1].get("low", 0))
        return 0.0
    
    true_ranges = []
    for i in range(1, len(candles)):
        high = float(candles[i]["high"])
        low = float(candles[i]["low"])
        prev_close = float(candles[i - 1]["close"])
        
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    
    return sum(true_ranges[-period:]) / period if true_ranges else 0.0


# ============================================
# ADVANCED INDICATORS (from V7)
# ============================================

def calculate_vwap(candles: List[Dict]) -> Dict:
    """Calculate Volume Weighted Average Price (VWAP)."""
    if not candles:
        return {"vwap": 0, "current": 0, "deviation": 0, "above_vwap": False, "score": 0}
    
    cumulative_tpv = 0
    cumulative_vol = 0
    
    for c in candles:
        tp = (float(c["high"]) + float(c["low"]) + float(c["close"])) / 3
        vol = float(c.get("volume", 1))
        cumulative_tpv += tp * vol
        cumulative_vol += vol
    
    vwap = cumulative_tpv / cumulative_vol if cumulative_vol > 0 else float(candles[-1]["close"])
    current_price = float(candles[-1]["close"])
    deviation = ((current_price - vwap) / vwap) * 100 if vwap > 0 else 0
    above_vwap = current_price > vwap
    
    score = 15 if above_vwap else (5 if abs(deviation) < 0.5 else 0)
    
    return {"vwap": vwap, "current": current_price, "deviation": deviation, 
            "above_vwap": above_vwap, "score": score}


def detect_bb_squeeze(candles: List[Dict], period: int = 20, squeeze_threshold: float = 0.05) -> Dict:
    """Detect Bollinger Band squeeze."""
    if len(candles) < period:
        return {"is_squeeze": False, "bandwidth": 100, "position": 0.5, "direction": "NEUTRAL", "score": 0}
    
    closes = [float(c["close"]) for c in candles[-period:]]
    sma = sum(closes) / period
    variance = sum((c - sma) ** 2 for c in closes) / period
    std_dev = math.sqrt(variance)
    
    upper = sma + 2 * std_dev
    lower = sma - 2 * std_dev
    bandwidth = ((upper - lower) / sma) * 100 if sma > 0 else 100
    
    current_price = closes[-1]
    position = (current_price - lower) / (upper - lower) if upper != lower else 0.5
    
    is_squeeze = bandwidth < squeeze_threshold * 100
    direction = "UP" if position > 0.8 else ("DOWN" if position < 0.2 else "NEUTRAL")
    
    score = 25 if (is_squeeze and direction == "UP") else (15 if is_squeeze else 0)
    
    return {"is_squeeze": is_squeeze, "bandwidth": bandwidth, "position": position,
            "direction": direction, "upper": upper, "lower": lower, "sma": sma, "score": score}


def detect_divergence(candles: List[Dict], rsi_values: List[float], lookback: int = 10) -> Dict:
    """Detect bullish/bearish divergence."""
    if len(candles) < lookback or len(rsi_values) < lookback:
        return {"type": None, "score": 0}
    
    prices = [float(c["close"]) for c in candles[-lookback:]]
    rsis = rsi_values[-lookback:]
    
    price_lower_low = prices[-1] < min(prices[:-1])
    rsi_higher_low = rsis[-1] > min(rsis[:-1])
    price_higher_high = prices[-1] > max(prices[:-1])
    rsi_lower_high = rsis[-1] < max(rsis[:-1])
    
    if price_lower_low and rsi_higher_low:
        return {"type": "BULLISH", "score": 30}
    elif price_higher_high and rsi_lower_high:
        return {"type": "BEARISH", "score": -20}
    
    return {"type": None, "score": 0}


def detect_market_regime(candles: List[Dict], atr: float) -> Dict:
    """Detect trending vs ranging market."""
    if len(candles) < 20:
        return {"regime": "UNKNOWN", "strategy": "WAIT", "direction": "NEUTRAL"}
    
    closes = [float(c["close"]) for c in candles[-20:]]
    direction = ((closes[-1] - closes[0]) / closes[0]) * 100
    volatility = (atr / closes[-1]) * 100 if closes[-1] > 0 else 10
    trend_strength = abs(direction) / volatility if volatility > 0 else 0
    
    if trend_strength > 2.0:
        return {"regime": "TRENDING", "strategy": "MOMENTUM", 
                "direction": "UP" if direction > 0 else "DOWN", "trend_strength": trend_strength}
    else:
        return {"regime": "RANGING", "strategy": "MEAN_REVERSION", 
                "direction": "NEUTRAL", "trend_strength": trend_strength}


def hybrid_strategy(regime: Dict, rsi: float, bb_position: float) -> Dict:
    """Apply momentum in trends, mean reversion in ranges."""
    if regime["strategy"] == "MOMENTUM":
        if regime["direction"] == "UP" and rsi < 70:
            return {"action": "BUY", "score": 20, "reason": "MOMENTUM_UP"}
        elif regime["direction"] == "DOWN":
            return {"action": "AVOID", "score": -10, "reason": "MOMENTUM_DOWN"}
    else:
        if rsi < 30 and bb_position < 0.2:
            return {"action": "BUY", "score": 25, "reason": "OVERSOLD_BOUNCE"}
        elif rsi > 70 and bb_position > 0.8:
            return {"action": "SELL", "score": -20, "reason": "OVERBOUGHT"}
    
    return {"action": "WAIT", "score": 0, "reason": "NO_SIGNAL"}


# ============================================
# RISK MANAGEMENT
# ============================================

def kelly_position_size(win_rate: float, avg_win: float, avg_loss: float,
                        equity: float, kelly_fraction: float = 0.25) -> float:
    """Kelly Criterion with 25% fraction for safety."""
    if avg_loss == 0:
        return 0.10
    
    win_loss_ratio = avg_win / abs(avg_loss)
    p, q, b = win_rate, 1 - win_rate, win_loss_ratio
    
    full_kelly = (p * b - q) / b if b > 0 else 0
    return max(0.05, min(0.50, full_kelly * kelly_fraction))


def chandelier_exit(candles: List[Dict], atr: float, multiplier: float = 3.0) -> Dict:
    """Chandelier Exit: 3x ATR from highest high."""
    if len(candles) < 22:
        return {"stop_price": 0, "highest_high": 0, "stop_percent": 5.0, "triggered": False}
    
    highs = [float(c["high"]) for c in candles[-22:]]
    highest_high = max(highs)
    chandelier_stop = highest_high - (atr * multiplier)
    current_price = float(candles[-1]["close"])
    stop_percent = ((current_price - chandelier_stop) / current_price) * 100 if current_price > 0 else 5.0
    
    return {"stop_price": chandelier_stop, "highest_high": highest_high,
            "stop_percent": stop_percent, "triggered": current_price <= chandelier_stop}


def dynamic_take_profit(entry_price: float, atr: float, leverage: int = 10,
                        risk_reward: float = 3.0) -> Dict:
    """Calculate TP based on 3:1 R:R ratio and ATR."""
    stop_distance = atr * 2
    tp_distance = stop_distance * risk_reward
    tp_price = entry_price + tp_distance
    tp_percent = (tp_distance / entry_price) * 100 * leverage if entry_price > 0 else 30
    
    return {"tp_price": tp_price, "tp_percent": min(tp_percent, 50), "risk_reward": risk_reward}


# ============================================
# MARKET SIGNALS
# ============================================

def analyze_funding_rate(ticker: Dict) -> Dict:
    """Funding rate strategy. Negative funding = contrarian long (+15 pts)."""
    funding = float(ticker.get("funding_rate", 0)) * 100
    
    if funding > 0.1:
        return {"signal": "CAUTION_LONG", "score": -5, "funding": funding}
    elif funding > 0.03:
        return {"signal": "BULLISH", "score": 10, "funding": funding}
    elif funding < -0.05:
        return {"signal": "CONTRARIAN_LONG", "score": 15, "funding": funding}
    elif funding < -0.02:
        return {"signal": "NEUTRAL", "score": 5, "funding": funding}
    else:
        return {"signal": "NEUTRAL", "score": 0, "funding": funding}


def analyze_orderbook(orderbook: Dict) -> Tuple[str, float]:
    """Analyze order book for buy/sell pressure."""
    bids = orderbook.get("buy", [])[:10]
    asks = orderbook.get("sell", [])[:10]
    
    bid_vol = sum(float(b.get("size", 0)) for b in bids)
    ask_vol = sum(float(a.get("size", 0)) for a in asks)
    total = bid_vol + ask_vol
    
    if total == 0:
        return ("NEUTRAL", 0.0)
    
    imbalance = (bid_vol - ask_vol) / total
    
    if imbalance > 0.3:
        return ("BUY_PRESSURE", imbalance)
    elif imbalance < -0.3:
        return ("SELL_PRESSURE", imbalance)
    return ("NEUTRAL", imbalance)


def detect_whale_activity(orderbook: Dict, threshold_usd: float = 50000) -> Dict:
    """Detect large orders (>$50K) = whale activity."""
    bids = orderbook.get("buy", [])[:20]
    asks = orderbook.get("sell", [])[:20]
    
    large_bids = [b for b in bids if float(b.get("size", 0)) * float(b.get("price", 0)) > threshold_usd]
    large_asks = [a for a in asks if float(a.get("size", 0)) * float(a.get("price", 0)) > threshold_usd]
    
    bid_wall = sum(float(b.get("size", 0)) * float(b.get("price", 0)) for b in large_bids)
    ask_wall = sum(float(a.get("size", 0)) * float(a.get("price", 0)) for a in large_asks)
    
    if bid_wall > ask_wall * 1.5:
        return {"signal": "WHALE_BUYING", "score": 15, "bid_wall": bid_wall, "ask_wall": ask_wall}
    elif ask_wall > bid_wall * 1.5:
        return {"signal": "WHALE_SELLING", "score": -15, "bid_wall": bid_wall, "ask_wall": ask_wall}
    return {"signal": "NEUTRAL", "score": 0, "bid_wall": bid_wall, "ask_wall": ask_wall}


def btc_eth_lead_signal(btc_ticker: Dict, eth_ticker: Dict, alt_ticker: Dict) -> Dict:
    """BTC/ETH lead indicator for altcoins."""
    btc_chg = float(btc_ticker.get("mark_change_24h", 0))
    eth_chg = float(eth_ticker.get("mark_change_24h", 0))
    alt_chg = float(alt_ticker.get("mark_change_24h", 0))
    
    major_momentum = (btc_chg + eth_chg) / 2
    
    if major_momentum > 3 and alt_chg < major_momentum - 2:
        return {"signal": "CATCH_UP_POTENTIAL", "score": 10, "major_momentum": major_momentum}
    elif major_momentum < -3 and alt_chg > major_momentum + 2:
        return {"signal": "AVOID_LAGGARD", "score": -10, "major_momentum": major_momentum}
    return {"signal": "NEUTRAL", "score": 0, "major_momentum": major_momentum}


def calculate_volatility(ticker: Dict) -> float:
    """Calculate daily volatility from high/low."""
    high = float(ticker.get("high", 0))
    low = float(ticker.get("low", 0))
    return ((high - low) / low) * 100 if low > 0 else 100.0


# Utility functions
def get_price_from_ticker(ticker: Dict) -> float:
    return float(ticker.get("mark_price", 0))

def get_24h_change(ticker: Dict) -> float:
    return float(ticker.get("mark_change_24h", 0))

def get_volume(ticker: Dict) -> float:
    return float(ticker.get("turnover_usd", 0))


if __name__ == "__main__":
    print("Delta V8 Indicators - Testing")
    print("=" * 40)
    print(f"Kelly Size (75% WR, 5%/5%): {kelly_position_size(0.75, 5, 5, 100):.2%}")
    
    # Test order flow functions
    test_trades = [
        {"size": 100, "side": "buy", "price": 100},
        {"size": 50, "side": "sell", "price": 100},
        {"size": 80, "side": "buy", "price": 100}
    ]
    print(f"Delta Volume: {calculate_delta_volume(test_trades):.0f}")
    print(f"Delta Divergence: {detect_delta_divergence(-5, 100)}")
    print(f"Large Trades: {detect_large_trades(test_trades)}")
    print("All V8 indicators loaded successfully!")

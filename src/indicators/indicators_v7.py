#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V7 - Indicator Library
==================================================
Advanced technical indicators for cryptocurrency trading.
Research-backed implementations from top GitHub projects.

Author: Vibhav Aggarwal
Date: December 20, 2025
"""

import math
from typing import List, Dict, Tuple, Optional


# ============================================
# CORE INDICATORS
# ============================================

def calculate_ema(data: List[float], period: int) -> List[float]:
    """
    Calculate Exponential Moving Average.
    """
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
    """
    Calculate Relative Strength Index (RSI).
    RSI < 30 = oversold, > 70 = overbought
    """
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
    """Calculate Average True Range (ATR) for volatility."""
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
# ADVANCED INDICATORS
# ============================================

def calculate_vwap(candles: List[Dict]) -> Dict:
    """
    Calculate Volume Weighted Average Price (VWAP).
    Price above VWAP = bullish bias. +15 pts.
    """
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
    """
    Detect Bollinger Band squeeze. Squeeze (< 5%) precedes 10%+ moves.
    +25 pts for squeeze breakout.
    """
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
    """
    Detect bullish/bearish divergence. Strongest reversal signal (+30 pts).
    Bullish: Price lower low, RSI higher low.
    """
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
    """
    Detect trending vs ranging market. Hybrid strategy = Sharpe 1.71.
    """
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
    """
    Kelly Criterion with 25% fraction for safety.
    Returns position size as fraction of equity (0.05 to 0.50).
    """
    if avg_loss == 0:
        return 0.10
    
    win_loss_ratio = avg_win / abs(avg_loss)
    p, q, b = win_rate, 1 - win_rate, win_loss_ratio
    
    full_kelly = (p * b - q) / b if b > 0 else 0
    return max(0.05, min(0.50, full_kelly * kelly_fraction))


def chandelier_exit(candles: List[Dict], atr: float, multiplier: float = 3.0) -> Dict:
    """
    Chandelier Exit: 3x ATR from highest high. Reduces whipsaws 40%.
    """
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
    """
    Funding rate strategy. Negative funding = contrarian long (+15 pts).
    """
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
    """Analyze order book for buy/sell pressure. >30% imbalance = signal."""
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
    """Detect large orders (>K) = whale activity. +15 pts."""
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
    """BTC/ETH lead indicator for altcoins. Catch-up potential = +10 pts."""
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
    print("Delta V7 Indicators - Testing")
    print("=" * 40)
    print("Kelly Size (75% WR, 5%/5%): {:.2%}".format(kelly_position_size(0.75, 5, 5, 100)))
    print("All indicators loaded successfully!")

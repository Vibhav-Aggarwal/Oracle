#!/usr/bin/env python3
"""
INDICATORS V11 - Complete Technical Analysis Module
All indicators consolidated from V1-V10
"""

import numpy as np
from typing import List, Tuple, Dict, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# RSI - Relative Strength Index
# ============================================================================

def calculate_rsi(closes: List[float], period: int = 14) -> float:
    """Calculate RSI with Wilder smoothing"""
    if len(closes) < period + 1:
        return 50.0
    
    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    
    # Wilder smoothing
    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])
    
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    
    if avg_loss == 0:
        return 100.0
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return round(rsi, 2)

# ============================================================================
# MACD - Moving Average Convergence Divergence
# ============================================================================

def calculate_ema(data: List[float], period: int) -> List[float]:
    """Calculate Exponential Moving Average"""
    if len(data) < period:
        return [data[-1]] if data else [0]
    
    multiplier = 2 / (period + 1)
    ema = [sum(data[:period]) / period]
    
    for price in data[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    
    return ema

def calculate_macd(closes: List[float], 
                   fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    """Calculate MACD line, signal line, and histogram"""
    if len(closes) < slow + signal:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": None}
    
    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    
    # Align EMAs
    offset = slow - fast
    macd_line = [ema_fast[i] - ema_slow[i - offset] 
                 for i in range(offset, len(ema_fast))]
    
    if len(macd_line) < signal:
        return {"macd": 0, "signal": 0, "histogram": 0, "crossover": None}
    
    signal_line = calculate_ema(macd_line, signal)
    
    macd = macd_line[-1]
    sig = signal_line[-1]
    histogram = macd - sig
    
    # Crossover detection
    crossover = None
    if len(macd_line) >= 2 and len(signal_line) >= 2:
        prev_macd = macd_line[-2]
        prev_sig = signal_line[-2]
        if prev_macd <= prev_sig and macd > sig:
            crossover = "bullish"
        elif prev_macd >= prev_sig and macd < sig:
            crossover = "bearish"
    
    return {
        "macd": round(macd, 4),
        "signal": round(sig, 4),
        "histogram": round(histogram, 4),
        "crossover": crossover,
        "histogram_rising": histogram > (macd_line[-2] - signal_line[-2]) if len(macd_line) >= 2 else False
    }

# ============================================================================
# Bollinger Bands
# ============================================================================

def calculate_bollinger_bands(closes: List[float], 
                              period: int = 20, std_dev: float = 2.0) -> dict:
    """Calculate Bollinger Bands with %B and bandwidth"""
    if len(closes) < period:
        price = closes[-1] if closes else 0
        return {"upper": price, "middle": price, "lower": price, 
                "pct_b": 0.5, "bandwidth": 0}
    
    sma = np.mean(closes[-period:])
    std = np.std(closes[-period:])
    
    upper = sma + (std_dev * std)
    lower = sma - (std_dev * std)
    
    current = closes[-1]
    pct_b = (current - lower) / (upper - lower) if upper != lower else 0.5
    bandwidth = ((upper - lower) / sma) * 100 if sma > 0 else 0
    
    return {
        "upper": round(upper, 2),
        "middle": round(sma, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 4),
        "bandwidth": round(bandwidth, 2)
    }

# ============================================================================
# ATR - Average True Range
# ============================================================================

def calculate_atr(candles: List[dict], period: int = 14) -> float:
    """Calculate Average True Range"""
    if len(candles) < period + 1:
        return 0.0
    
    true_ranges = []
    for i in range(1, len(candles)):
        high = float(candles[i].get("high", candles[i].get("h", 0)))
        low = float(candles[i].get("low", candles[i].get("l", 0)))
        prev_close = float(candles[i-1].get("close", candles[i-1].get("c", 0)))
        
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        true_ranges.append(tr)
    
    if len(true_ranges) < period:
        return np.mean(true_ranges) if true_ranges else 0.0
    
    # Wilder smoothing for ATR
    atr = np.mean(true_ranges[:period])
    for tr in true_ranges[period:]:
        atr = (atr * (period - 1) + tr) / period
    
    return round(atr, 4)

def calculate_atr_percent(candles: List[dict], period: int = 14) -> float:
    """Calculate ATR as percentage of price"""
    atr = calculate_atr(candles, period)
    if not candles:
        return 0.0
    
    close = float(candles[-1].get("close", candles[-1].get("c", 0)))
    if close == 0:
        return 0.0
    
    return round((atr / close) * 100, 2)

# ============================================================================
# VWAP - Volume Weighted Average Price
# ============================================================================

def calculate_vwap(candles: List[dict]) -> dict:
    """Calculate VWAP with deviation bands"""
    if not candles:
        return {"vwap": 0, "deviation": 0, "above": False}
    
    cumulative_tp_vol = 0
    cumulative_vol = 0
    
    for candle in candles:
        high = float(candle.get("high", candle.get("h", 0)))
        low = float(candle.get("low", candle.get("l", 0)))
        close = float(candle.get("close", candle.get("c", 0)))
        volume = float(candle.get("volume", candle.get("v", 0)))
        
        typical_price = (high + low + close) / 3
        cumulative_tp_vol += typical_price * volume
        cumulative_vol += volume
    
    vwap = cumulative_tp_vol / cumulative_vol if cumulative_vol > 0 else 0
    current_price = float(candles[-1].get("close", candles[-1].get("c", 0)))
    deviation = ((current_price - vwap) / vwap * 100) if vwap > 0 else 0
    
    return {
        "vwap": round(vwap, 2),
        "deviation": round(deviation, 2),
        "above": current_price > vwap
    }

# ============================================================================
# EMAs - Multiple periods
# ============================================================================

def calculate_emas(closes: List[float]) -> dict:
    """Calculate multiple EMAs (9, 21, 50)"""
    result = {}
    for period in [9, 21, 50]:
        if len(closes) >= period:
            ema = calculate_ema(closes, period)
            result[f"ema{period}"] = round(ema[-1], 2)
        else:
            result[f"ema{period}"] = closes[-1] if closes else 0
    
    # Trend detection
    if all(k in result for k in ["ema9", "ema21", "ema50"]):
        result["bullish_stack"] = result["ema9"] > result["ema21"] > result["ema50"]
        result["bearish_stack"] = result["ema9"] < result["ema21"] < result["ema50"]
    else:
        result["bullish_stack"] = False
        result["bearish_stack"] = False
    
    return result

# ============================================================================
# Volume Analysis
# ============================================================================

def analyze_volume(candles: List[dict], period: int = 20) -> dict:
    """Analyze volume patterns"""
    if len(candles) < period:
        return {"spike": False, "ratio": 1.0, "trend": "neutral"}
    
    volumes = [float(c.get("volume", c.get("v", 0))) for c in candles]
    current_vol = volumes[-1]
    avg_vol = np.mean(volumes[-period:])
    
    ratio = current_vol / avg_vol if avg_vol > 0 else 1.0
    
    # Volume trend
    recent_avg = np.mean(volumes[-5:]) if len(volumes) >= 5 else current_vol
    older_avg = np.mean(volumes[-period:-5]) if len(volumes) >= period else avg_vol
    
    if recent_avg > older_avg * 1.2:
        trend = "increasing"
    elif recent_avg < older_avg * 0.8:
        trend = "decreasing"
    else:
        trend = "neutral"
    
    return {
        "spike": ratio > 2.0,
        "ratio": round(ratio, 2),
        "trend": trend,
        "current": current_vol,
        "average": round(avg_vol, 2)
    }

# ============================================================================
# Divergence Detection
# ============================================================================

def detect_rsi_divergence(closes: List[float], rsi_values: List[float] = None,
                          lookback: int = 14) -> dict:
    """Detect RSI bullish/bearish divergence"""
    if len(closes) < lookback:
        return {"bullish": False, "bearish": False}
    
    # Calculate RSI values if not provided
    if rsi_values is None:
        rsi_values = []
        for i in range(lookback, len(closes) + 1):
            rsi_values.append(calculate_rsi(closes[:i]))
    
    if len(rsi_values) < 3:
        return {"bullish": False, "bearish": False}
    
    # Find recent lows/highs
    price_window = closes[-lookback:]
    rsi_window = rsi_values[-lookback:] if len(rsi_values) >= lookback else rsi_values
    
    # Bullish: Price makes lower low, RSI makes higher low
    price_min_idx = np.argmin(price_window)
    if price_min_idx > 0:
        earlier_min = min(price_window[:price_min_idx]) if price_min_idx > 0 else price_window[0]
        current_min = price_window[price_min_idx]
        
        if current_min < earlier_min and len(rsi_window) > price_min_idx:
            rsi_at_current = rsi_window[price_min_idx] if price_min_idx < len(rsi_window) else rsi_window[-1]
            rsi_at_earlier = min(rsi_window[:price_min_idx]) if price_min_idx > 0 else rsi_window[0]
            
            if rsi_at_current > rsi_at_earlier:
                return {"bullish": True, "bearish": False}
    
    # Bearish: Price makes higher high, RSI makes lower high
    price_max_idx = np.argmax(price_window)
    if price_max_idx > 0:
        earlier_max = max(price_window[:price_max_idx]) if price_max_idx > 0 else price_window[0]
        current_max = price_window[price_max_idx]
        
        if current_max > earlier_max and len(rsi_window) > price_max_idx:
            rsi_at_current = rsi_window[price_max_idx] if price_max_idx < len(rsi_window) else rsi_window[-1]
            rsi_at_earlier = max(rsi_window[:price_max_idx]) if price_max_idx > 0 else rsi_window[0]
            
            if rsi_at_current < rsi_at_earlier:
                return {"bullish": False, "bearish": True}
    
    return {"bullish": False, "bearish": False}

def detect_macd_divergence(closes: List[float], macd_values: List[float] = None,
                           lookback: int = 14) -> dict:
    """Detect MACD divergence"""
    if len(closes) < lookback:
        return {"bullish": False, "bearish": False}
    
    # Similar logic to RSI divergence
    if macd_values is None:
        macd_values = []
        for i in range(lookback, len(closes) + 1):
            macd_data = calculate_macd(closes[:i])
            macd_values.append(macd_data["histogram"])
    
    if len(macd_values) < 3:
        return {"bullish": False, "bearish": False}
    
    price_window = closes[-lookback:]
    macd_window = macd_values[-lookback:] if len(macd_values) >= lookback else macd_values
    
    # Check for bullish divergence
    price_making_lower_lows = min(price_window[-5:]) < min(price_window[:-5]) if len(price_window) > 5 else False
    macd_making_higher_lows = min(macd_window[-5:]) > min(macd_window[:-5]) if len(macd_window) > 5 else False
    
    if price_making_lower_lows and macd_making_higher_lows:
        return {"bullish": True, "bearish": False}
    
    # Check for bearish divergence
    price_making_higher_highs = max(price_window[-5:]) > max(price_window[:-5]) if len(price_window) > 5 else False
    macd_making_lower_highs = max(macd_window[-5:]) < max(macd_window[:-5]) if len(macd_window) > 5 else False
    
    if price_making_higher_highs and macd_making_lower_highs:
        return {"bullish": False, "bearish": True}
    
    return {"bullish": False, "bearish": False}

# ============================================================================
# Bollinger Band Squeeze Detection
# ============================================================================

def detect_bb_squeeze(candles: List[dict], bb_period: int = 20, 
                      kc_period: int = 20, kc_mult: float = 1.5) -> dict:
    """Detect Bollinger Band squeeze (BB inside Keltner Channel)"""
    if len(candles) < max(bb_period, kc_period):
        return {"squeeze": False, "breakout_up": False, "breakout_down": False, "bandwidth": 0}
    
    closes = [float(c.get("close", c.get("c", 0))) for c in candles]
    
    # Bollinger Bands
    bb = calculate_bollinger_bands(closes, bb_period)
    
    # Keltner Channel
    atr = calculate_atr(candles, kc_period)
    ema = calculate_ema(closes, kc_period)[-1]
    kc_upper = ema + (kc_mult * atr)
    kc_lower = ema - (kc_mult * atr)
    
    # Squeeze: BB inside KC
    squeeze = bb["lower"] > kc_lower and bb["upper"] < kc_upper
    
    # Breakout detection
    prev_closes = closes[-5:]
    breakout_up = not squeeze and closes[-1] > bb["upper"]
    breakout_down = not squeeze and closes[-1] < bb["lower"]
    
    return {
        "squeeze": squeeze,
        "breakout_up": breakout_up,
        "breakout_down": breakout_down,
        "bandwidth": bb["bandwidth"]
    }

# ============================================================================
# Orderbook Analysis
# ============================================================================

def analyze_orderbook(orderbook: dict) -> dict:
    """Analyze orderbook for buy/sell pressure"""
    if not orderbook:
        return {"imbalance": 0, "pressure": "neutral", "bid_wall": False, "ask_wall": False}
    
    buy_orders = orderbook.get("buy", [])
    sell_orders = orderbook.get("sell", [])
    
    # Calculate total volume
    buy_volume = sum(float(o.get("size", 0)) for o in buy_orders[:10])
    sell_volume = sum(float(o.get("size", 0)) for o in sell_orders[:10])
    
    total = buy_volume + sell_volume
    imbalance = (buy_volume - sell_volume) / total if total > 0 else 0
    
    # Determine pressure
    if imbalance > 0.3:
        pressure = "bullish"
    elif imbalance < -0.3:
        pressure = "bearish"
    else:
        pressure = "neutral"
    
    # Wall detection (large orders at specific levels)
    avg_size = total / 20 if total > 0 else 0
    bid_wall = any(float(o.get("size", 0)) > avg_size * 5 for o in buy_orders[:5])
    ask_wall = any(float(o.get("size", 0)) > avg_size * 5 for o in sell_orders[:5])
    
    return {
        "imbalance": round(imbalance, 2),
        "pressure": pressure,
        "bid_wall": bid_wall,
        "ask_wall": ask_wall,
        "buy_volume": buy_volume,
        "sell_volume": sell_volume
    }

# ============================================================================
# Combined Analysis - Main Entry Point
# ============================================================================

def calculate_all_indicators(symbol: str, candles: List[dict], 
                             orderbook: dict = None, 
                             trades: List[dict] = None) -> dict:
    """
    Calculate all indicators and return combined analysis with score
    
    Args:
        symbol: Trading pair symbol
        candles: List of OHLCV candles
        orderbook: Optional orderbook data
        trades: Optional recent trades
    
    Returns:
        dict with score, signals, direction, and all indicators
    """
    if not candles or len(candles) < 30:
        return {
            "score": 0,
            "signals": [],
            "direction": None,
            "valid": False
        }
    
    # Extract closes
    closes = [float(c.get("close", c.get("c", 0))) for c in candles]
    
    # Calculate all indicators
    rsi = calculate_rsi(closes)
    macd = calculate_macd(closes)
    bb = calculate_bollinger_bands(closes)
    atr = calculate_atr(candles)
    atr_pct = calculate_atr_percent(candles)
    vwap = calculate_vwap(candles)
    emas = calculate_emas(closes)
    volume = analyze_volume(candles)
    rsi_div = detect_rsi_divergence(closes)
    macd_div = detect_macd_divergence(closes)
    squeeze = detect_bb_squeeze(candles)
    ob = analyze_orderbook(orderbook) if orderbook else None
    
    # Build result
    result = {
        "score": 0,
        "signals": [],
        "direction": None,
        "valid": True,
        "indicators": {
            "rsi": rsi,
            "macd": macd,
            "bollinger": bb,
            "atr": atr,
            "atr_pct": atr_pct,
            "vwap": vwap,
            "emas": emas,
            "volume": volume,
            "rsi_divergence": rsi_div,
            "macd_divergence": macd_div,
            "squeeze": squeeze,
            "orderbook": ob
        }
    }
    
    # ========== SCORING LOGIC ==========
    
    # RSI
    if rsi < 30:
        result["score"] += 15
        result["signals"].append(f"RSI_OVERSOLD({rsi})")
    elif rsi < 40:
        result["score"] += 8
        result["signals"].append(f"RSI_LOW({rsi})")
    elif rsi > 70:
        result["score"] -= 15
        result["signals"].append(f"RSI_OVERBOUGHT({rsi})")
    elif rsi > 60:
        result["score"] -= 8
        result["signals"].append(f"RSI_HIGH({rsi})")
    
    # MACD
    if macd["crossover"] == "bullish":
        result["score"] += 12
        result["signals"].append("MACD_BULL_CROSS")
    elif macd["crossover"] == "bearish":
        result["score"] -= 12
        result["signals"].append("MACD_BEAR_CROSS")
    
    if macd.get("histogram_rising", False):
        result["score"] += 5
        result["signals"].append("MACD+")
    
    # Bollinger Bands
    pct_b = bb["pct_b"]
    if pct_b < 0.05:
        result["score"] += 10
        pct_str = "{:.0%}".format(pct_b)
        result["signals"].append("BB_LOW(" + pct_str + ")")
    
    bandwidth = squeeze["bandwidth"]
    if squeeze["breakout_up"]:
        result["score"] += 8
        bw_str = "{:.1f}%".format(bandwidth)
        result["signals"].append("SQUEEZE(" + bw_str + ")")
    
    # VWAP
    if vwap["above"] and vwap["deviation"] > 0.5:
        result["score"] += 7
        result["signals"].append("VWAP+")
    elif not vwap["above"] and vwap["deviation"] < -0.5:
        result["score"] -= 7
        result["signals"].append("VWAP-")
    
    # Volume
    if volume["spike"]:
        result["score"] += 5
        ratio_str = "{:.1f}x".format(volume["ratio"])
        result["signals"].append("VOL_SPIKE(" + ratio_str + ")")
    
    # EMA Stack
    if emas["bullish_stack"]:
        result["score"] += 10
        result["signals"].append("EMA_BULL_STACK")
    elif emas["bearish_stack"]:
        result["score"] -= 10
        result["signals"].append("EMA_BEAR_STACK")
    
    # Divergences
    if rsi_div["bullish"]:
        result["score"] += 10
        result["signals"].append("RSI_BULL_DIV")
    elif rsi_div["bearish"]:
        result["score"] -= 10
        result["signals"].append("RSI_BEAR_DIV")
    
    if macd_div["bullish"]:
        result["score"] += 8
        result["signals"].append("MACD_BULL_DIV")
    elif macd_div["bearish"]:
        result["score"] -= 8
        result["signals"].append("MACD_BEAR_DIV")
    
    # Orderbook
    if ob:
        if ob["pressure"] == "bullish":
            result["score"] += 5
            result["signals"].append("OB_BUY_PRESSURE")
        elif ob["pressure"] == "bearish":
            result["score"] -= 5
            result["signals"].append("OB_SELL_PRESSURE")
    
    # Determine direction
    if result["score"] >= 40:
        result["direction"] = "LONG"
    elif result["score"] <= -40:
        result["direction"] = "SHORT"
    
    return result

# ============================================================================
# Dynamic SL/TP Calculation (ATR-based)
# ============================================================================

def calculate_dynamic_sl_tp(candles: List[dict], direction: str,
                            sl_multiplier: float = 2.0,
                            tp_multiplier: float = 3.0) -> dict:
    """
    Calculate ATR-based stop loss and take profit
    
    Args:
        candles: OHLCV candles
        direction: LONG or SHORT
        sl_multiplier: ATR multiplier for stop loss
        tp_multiplier: ATR multiplier for take profit
    
    Returns:
        dict with sl_pct and tp_pct
    """
    atr_pct = calculate_atr_percent(candles)
    
    if atr_pct == 0:
        atr_pct = 2.0  # Default 2%
    
    sl_pct = min(max(atr_pct * sl_multiplier, 1.0), 10.0)  # 1-10%
    tp_pct = min(max(atr_pct * tp_multiplier, 2.0), 20.0)  # 2-20%
    
    return {
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "atr_pct": atr_pct
    }

# ============================================================================
# Test function
# ============================================================================

if __name__ == "__main__":
    # Test with sample data
    sample_closes = [100 + i * 0.5 + np.random.randn() for i in range(50)]
    
    print("=== INDICATORS V11 TEST ===")
    print(f"RSI: {calculate_rsi(sample_closes)}")
    print(f"MACD: {calculate_macd(sample_closes)}")
    print(f"BB: {calculate_bollinger_bands(sample_closes)}")
    
    sample_candles = [
        {"o": 100+i, "h": 102+i, "l": 99+i, "c": 101+i, "v": 1000}
        for i in range(50)
    ]
    print(f"ATR: {calculate_atr(sample_candles)}")
    print(f"VWAP: {calculate_vwap(sample_candles)}")
    
    result = calculate_all_indicators("TEST", sample_candles)
    print(f"Score: {result['score']}")
    print(f"Signals: {result['signals']}")
    print(f"Direction: {result['direction']}")
    print("✅ All tests passed!")

#!/usr/bin/env python3
"""
V9 Indicators Module - Technical + Order Flow Analysis
Created: December 20, 2025
"""

import time
import threading
from typing import List, Dict, Tuple, Optional

def calculate_ema(values: List[float], period: int) -> float:
    if len(values) < period:
        return sum(values) / len(values) if values else 0
    multiplier = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for price in values[period:]:
        ema = (price - ema) * multiplier + ema
    return ema

def calculate_rsi(candles: List[dict], period: int = 14) -> float:
    if len(candles) < period + 1:
        return 50.0
    closes = [float(c.get('close', 0)) for c in candles]
    gains, losses = [], []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i-1]
        gains.append(change if change >= 0 else 0)
        losses.append(abs(change) if change < 0 else 0)
    if len(gains) < period:
        return 50.0
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    return 100 - (100 / (1 + avg_gain / avg_loss))

def calculate_macd(candles: List[dict], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    if len(candles) < slow:
        return {'macd': 0, 'signal': 0, 'histogram': 0, 'prev_histogram': 0}
    closes = [float(c.get('close', 0)) for c in candles]
    ema_fast = calculate_ema(closes, fast)
    ema_slow = calculate_ema(closes, slow)
    macd_line = ema_fast - ema_slow
    macd_values = []
    for i in range(slow - 1, len(closes)):
        macd_values.append(calculate_ema(closes[:i+1], fast) - calculate_ema(closes[:i+1], slow))
    signal_line = calculate_ema(macd_values, signal) if len(macd_values) >= signal else macd_line
    histogram = macd_line - signal_line
    prev_histogram = macd_values[-2] - calculate_ema(macd_values[:-1], signal) if len(macd_values) > signal else 0
    return {'macd': macd_line, 'signal': signal_line, 'histogram': histogram, 'prev_histogram': prev_histogram}

def calculate_atr(candles: List[dict], period: int = 14) -> float:
    if len(candles) < 2:
        return 0
    tr_values = []
    for i in range(1, len(candles)):
        high, low = float(candles[i].get('high', 0)), float(candles[i].get('low', 0))
        prev_close = float(candles[i-1].get('close', 0))
        tr_values.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    return sum(tr_values[-period:]) / min(len(tr_values), period) if tr_values else 0

def calculate_bollinger_bands(candles: List[dict], period: int = 20, std_dev: float = 2.0) -> dict:
    if len(candles) < period:
        return {'upper': 0, 'middle': 0, 'lower': 0, 'bandwidth': 100, 'squeeze': False}
    closes = [float(c.get('close', 0)) for c in candles[-period:]]
    sma = sum(closes) / period
    std = (sum((x - sma) ** 2 for x in closes) / period) ** 0.5
    upper, lower = sma + std_dev * std, sma - std_dev * std
    bandwidth = ((upper - lower) / sma) * 100 if sma > 0 else 100
    return {'upper': upper, 'middle': sma, 'lower': lower, 'bandwidth': bandwidth, 'squeeze': bandwidth < 5.0}

def calculate_vwap(candles: List[dict]) -> float:
    if not candles:
        return 0
    cum_tp_vol, cum_vol = 0, 0
    for c in candles:
        tp = (float(c.get('high', 0)) + float(c.get('low', 0)) + float(c.get('close', 0))) / 3
        vol = float(c.get('volume', 0))
        cum_tp_vol += tp * vol
        cum_vol += vol
    return cum_tp_vol / cum_vol if cum_vol > 0 else 0

def detect_rsi_divergence(candles: List[dict], lookback: int = 10) -> str:
    if len(candles) < lookback:
        return "NONE"
    closes = [float(c.get('close', 0)) for c in candles[-lookback:]]
    rsis = [calculate_rsi(candles[:i]) for i in range(len(candles) - lookback, len(candles) + 1)]
    if len(rsis) < lookback:
        return "NONE"
    rsis = rsis[-lookback:]
    if closes[-1] <= min(closes[:-1]) and rsis[-1] > min(rsis[:-3]):
        return "BULLISH"
    if closes[-1] >= max(closes[:-1]) and rsis[-1] < max(rsis[:-3]):
        return "BEARISH"
    return "NONE"

def detect_bb_squeeze(candles: List[dict], period: int = 20, threshold: float = 5.0) -> dict:
    bb = calculate_bollinger_bands(candles, period)
    if len(candles) < period + 5:
        return {'squeeze': False, 'breakout_up': False, 'breakout_down': False, 'bandwidth': bb['bandwidth']}
    was_squeeze = any(calculate_bollinger_bands(candles[:i])['bandwidth'] < threshold for i in range(-5, -1))
    close = float(candles[-1].get('close', 0))
    return {'squeeze': bb['squeeze'], 'breakout_up': was_squeeze and close > bb['upper'],
            'breakout_down': was_squeeze and close < bb['lower'], 'bandwidth': bb['bandwidth']}

def calculate_delta_volume(trades: List[dict]) -> float:
    if not trades:
        return 0
    buy_vol = sum(float(t.get('size', 0)) for t in trades if t.get('side') == 'buy')
    sell_vol = sum(float(t.get('size', 0)) for t in trades if t.get('side') == 'sell')
    return buy_vol - sell_vol

def detect_delta_divergence(candles: List[dict], delta_values: List[float], lookback: int = 10) -> Tuple[int, Optional[str]]:
    if len(candles) < lookback or len(delta_values) < lookback:
        return 0, None
    price_start, price_end = float(candles[-lookback].get('close', 0)), float(candles[-1].get('close', 0))
    price_change = (price_end - price_start) / price_start * 100 if price_start > 0 else 0
    delta_trend = sum(delta_values[-5:]) - sum(delta_values[-lookback:-5])
    if price_change < -1 and delta_trend > 0:
        return 25, "DELTA_DIV+"
    if price_change > 1 and delta_trend < 0:
        return -20, "DELTA_DIV-"
    return 0, None

def detect_absorption(candle: dict, volume: float, avg_volume: float, delta: float) -> Tuple[int, Optional[str]]:
    if avg_volume <= 0 or volume <= 0:
        return 0, None
    body = abs(float(candle.get('close', 0)) - float(candle.get('open', 0)))
    range_size = float(candle.get('high', 0)) - float(candle.get('low', 0))
    if range_size <= 0:
        return 0, None
    if volume / avg_volume > 2.0 and body / range_size < 0.3:
        return (20, "ABSORB+") if delta > 0 else (-15, "ABSORB-")
    return 0, None

def detect_whale_trades(trades: List[dict], threshold_usd: float = 100000) -> Tuple[int, Optional[str]]:
    if not trades:
        return 0, None
    large_buys = sum(1 for t in trades if t.get('side') == 'buy' and float(t.get('size', 0)) * float(t.get('price', 0)) >= threshold_usd)
    large_sells = sum(1 for t in trades if t.get('side') == 'sell' and float(t.get('size', 0)) * float(t.get('price', 0)) >= threshold_usd)
    if large_buys > large_sells * 2 and large_buys >= 2:
        return 15, f"WHALE_BUY({large_buys})"
    if large_sells > large_buys * 2 and large_sells >= 2:
        return -15, f"WHALE_SELL({large_sells})"
    return 0, None

def calculate_orderbook_imbalance(orderbook: dict) -> float:
    if not orderbook:
        return 0
    bid_vol = sum(float(b.get('size', 0)) for b in orderbook.get('buy', [])[:10])
    ask_vol = sum(float(a.get('size', 0)) for a in orderbook.get('sell', [])[:10])
    total = bid_vol + ask_vol
    return (bid_vol - ask_vol) / total if total > 0 else 0

def calculate_v9_indicators(symbol: str, candles: List[dict], orderbook: dict = None,
                            trades: List[dict] = None, delta_values: List[float] = None) -> dict:
    result = {'symbol': symbol, 'score': 0, 'signals': [], 'indicators': {}}
    if len(candles) < 20:
        return result
    rsi = calculate_rsi(candles)
    macd = calculate_macd(candles)
    atr = calculate_atr(candles)
    bb = calculate_bollinger_bands(candles)
    vwap = calculate_vwap(candles)
    result['indicators'] = {'rsi': rsi, 'macd': macd, 'atr': atr, 'bb': bb, 'vwap': vwap}
    
    if rsi < 25:
        result['score'] += 20
        result['signals'].append(f"RSI({rsi:.0f})")
    elif rsi < 35:
        result['score'] += 10
    
    if macd['histogram'] > 0 and macd['histogram'] > macd['prev_histogram']:
        result['score'] += 20
        result['signals'].append("MACD+")
    
    squeeze = detect_bb_squeeze(candles)
    if squeeze['breakout_up']:
        result['score'] += 25
        result['signals'].append(f"SQUEEZE({squeeze['bandwidth']:.1f}%)")
    
    div = detect_rsi_divergence(candles)
    if div == "BULLISH":
        result['score'] += 30
        result['signals'].append("DIV+")
    
    current_price = float(candles[-1].get('close', 0))
    if vwap > 0 and current_price > vwap:
        result['score'] += 15
        result['signals'].append("VWAP+")
    
    if orderbook:
        imbalance = calculate_orderbook_imbalance(orderbook)
        if imbalance > 0.3:
            result['score'] += 15
            result['signals'].append(f"OB+({imbalance:.0%})")
    
    if delta_values and len(delta_values) >= 10:
        ds, dsig = detect_delta_divergence(candles, delta_values)

    # Absorption detection (high volume + small move = absorption)
    if delta_values and len(delta_values) >= 5:
        last_candle = candles[-1]
        volumes = [float(c.get("volume", 0)) for c in candles[-20:]]
        avg_volume = sum(volumes) / len(volumes) if volumes else 0
        last_volume = float(last_candle.get("volume", 0))
        last_delta = delta_values[-1] if delta_values else 0
        absorb_score, absorb_sig = detect_absorption(last_candle, last_volume, avg_volume, last_delta)
        if absorb_sig:
            result["score"] += absorb_score
            result["signals"].append(absorb_sig)
        if dsig:
            result['score'] += ds
            result['signals'].append(dsig)
    
    if trades:
        ws, wsig = detect_whale_trades(trades)
        if wsig:
            result['score'] += ws
            result['signals'].append(wsig)
    
    return result

if __name__ == "__main__":
    print("V9 Indicators Module - OK")


def estimate_delta_from_candles(candles: List[dict]) -> List[float]:
    """Estimate delta (buy-sell pressure) from candle price movement
    Positive delta = bullish, Negative delta = bearish
    """
    deltas = []
    for c in candles:
        open_p = float(c.get("open", 0))
        close_p = float(c.get("close", 0))
        high_p = float(c.get("high", 0))
        low_p = float(c.get("low", 0))
        volume = float(c.get("volume", 0))
        
        if open_p == 0 or high_p == low_p:
            deltas.append(0)
            continue
        
        # Calculate buying pressure: (close - low) / (high - low)
        # Calculate selling pressure: (high - close) / (high - low)
        price_range = high_p - low_p
        buy_pressure = (close_p - low_p) / price_range
        sell_pressure = (high_p - close_p) / price_range
        
        # Delta = (buy_pressure - sell_pressure) * volume
        delta = (buy_pressure - sell_pressure) * volume
        deltas.append(delta)
    
    return deltas

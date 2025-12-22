#!/usr/bin/env python3
"""
SENTIMENT V11 - Complete Sentiment Analysis Module
Fear & Greed, News, VADER, FinBERT integration
"""

import requests
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
import json
import re

logger = logging.getLogger(__name__)

# Global sentiment cache (5 minute TTL)
_sentiment_cache = {}
_fear_greed_cache = {"value": None, "ts": 0}
_news_cache = {}
SENTIMENT_CACHE_TTL = 300  # 5 minutes

# ============================================================================
# Configuration
# ============================================================================

FEAR_GREED_API = "https://api.alternative.me/fng/"
CRYPTOPANIC_API = "https://cryptopanic.com/api/v1/posts/"
FINBERT_SERVER = "http://10.0.0.74:5001"
CACHE_TTL = 300  # 5 minutes

# Simple cache
_cache = {}

def _get_cached(key: str, ttl: int = CACHE_TTL) -> Optional[dict]:
    """Get cached value if not expired"""
    if key in _cache:
        data, timestamp = _cache[key]
        if datetime.now().timestamp() - timestamp < ttl:
            return data
    return None

def _set_cache(key: str, data: dict):
    """Set cache value"""
    _cache[key] = (data, datetime.now().timestamp())

# ============================================================================
# Fear & Greed Index
# ============================================================================

def get_fear_greed() -> dict:
    """Fetch Fear & Greed Index from Alternative.me"""
    cached = _get_cached("fear_greed")
    if cached:
        return cached
    
    try:
        response = requests.get(FEAR_GREED_API, timeout=5)
        data = response.json()
        
        if "data" in data and len(data["data"]) > 0:
            fng = data["data"][0]
            result = {
                "value": int(fng.get("value", 50)),
                "classification": fng.get("value_classification", "Neutral"),
                "timestamp": fng.get("timestamp", ""),
                "valid": True
            }
            _set_cache("fear_greed", result)
            return result
    except Exception as e:
        logger.warning(f"Fear & Greed fetch failed: {e}")
    
    return {"value": 50, "classification": "Neutral", "valid": False}

def score_fear_greed() -> Tuple[int, str]:
    """
    Score based on Fear & Greed Index
    Returns (points, signal)
    
    Extreme Fear (<20): Bullish +8
    Fear (20-35): Bullish +4
    Neutral (35-65): 0
    Greed (65-80): Bearish -4
    Extreme Greed (>80): Bearish -8
    """
    fg = get_fear_greed()
    value = fg["value"]
    
    if value < 20:
        return (8, f"EXTREME_FEAR({value})")
    elif value < 35:
        return (4, f"FEAR({value})")
    elif value > 80:
        return (-8, f"EXTREME_GREED({value})")
    elif value > 65:
        return (-4, f"GREED({value})")
    else:
        return (0, f"NEUTRAL({value})")

# ============================================================================
# CryptoPanic News
# ============================================================================

def get_crypto_news(symbol: str = "BTC", limit: int = 10) -> List[dict]:
    """Fetch news from CryptoPanic (free tier)"""
    cache_key = f"news_{symbol}"
    cached = _get_cached(cache_key)
    if cached:
        return cached
    
    try:
        # Map symbols to currencies
        currency_map = {
            "BTCUSD": "BTC", "BTCUSDT": "BTC",
            "ETHUSD": "ETH", "ETHUSDT": "ETH",
            "XRPUSDT": "XRP", "SOLUSD": "SOL", "SOLUSDT": "SOL",
            "DOGEUSDT": "DOGE", "ADAUSDT": "ADA"
        }
        currency = currency_map.get(symbol, symbol[:3])
        
        url = f"{CRYPTOPANIC_API}?auth_token=free&currencies={currency}&kind=news&public=true"
        response = requests.get(url, timeout=5)
        data = response.json()
        
        news = []
        for post in data.get("results", [])[:limit]:
            news.append({
                "title": post.get("title", ""),
                "source": post.get("source", {}).get("title", "Unknown"),
                "published": post.get("published_at", ""),
                "votes": post.get("votes", {})
            })
        
        _set_cache(cache_key, news)
        return news
    except Exception as e:
        logger.warning(f"CryptoPanic fetch failed: {e}")
        return []

# ============================================================================
# VADER Sentiment (Fallback)
# ============================================================================

def simple_vader_sentiment(text: str) -> float:
    """
    Simple VADER-like sentiment scoring (fallback when FinBERT unavailable)
    Returns score from -1 (negative) to +1 (positive)
    """
    text = text.lower()
    
    # Positive words
    positive = ["bullish", "surge", "rally", "gain", "high", "up", "rise", 
                "soar", "jump", "breakout", "moon", "ath", "record", "pump",
                "buy", "long", "success", "profit", "win", "boom", "rocket"]
    
    # Negative words
    negative = ["bearish", "crash", "drop", "fall", "low", "down", "sink",
                "plunge", "dump", "breakdown", "sell", "short", "loss", 
                "fail", "bust", "fear", "panic", "correction", "rekt"]
    
    pos_count = sum(1 for word in positive if word in text)
    neg_count = sum(1 for word in negative if word in text)
    
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    
    return round((pos_count - neg_count) / total, 2)

def analyze_news_vader(news: List[dict]) -> dict:
    """Analyze news headlines using simple VADER"""
    if not news:
        return {"score": 0, "sentiment": "neutral", "headlines": 0}
    
    scores = []
    for article in news:
        title = article.get("title", "")
        score = simple_vader_sentiment(title)
        scores.append(score)
    
    avg_score = sum(scores) / len(scores) if scores else 0
    
    if avg_score > 0.3:
        sentiment = "positive"
    elif avg_score < -0.3:
        sentiment = "negative"
    else:
        sentiment = "neutral"
    
    return {
        "score": round(avg_score, 2),
        "sentiment": sentiment,
        "headlines": len(news)
    }

# ============================================================================
# FinBERT Integration (GPU Server)
# ============================================================================

def get_finbert_sentiment(headlines: List[str]) -> Optional[dict]:
    """
    Call FinBERT server on Admin Server (10.0.0.74:5001)
    Returns GPU-powered sentiment analysis
    """
    if not headlines:
        return None
    
    try:
        response = requests.post(
            f"{FINBERT_SERVER}/analyze",
            json={"headlines": headlines},
            timeout=10
        )
        
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.debug(f"FinBERT unavailable: {e}")
    
    return None

def score_finbert(symbol: str) -> Tuple[int, str]:
    """
    Get FinBERT sentiment score for symbol
    Returns (points, signal)
    """
    # Get news headlines
    news = get_crypto_news(symbol)
    if not news:
        return (0, "NO_NEWS")
    
    headlines = [n["title"] for n in news[:5]]
    
    # Try FinBERT first
    finbert_result = get_finbert_sentiment(headlines)
    
    if finbert_result and "average_sentiment" in finbert_result:
        avg = finbert_result["average_sentiment"]
        
        if avg > 0.5:
            return (10, f"FINBERT_BULLISH({avg:.2f})")
        elif avg > 0.2:
            return (5, f"FINBERT_POSITIVE({avg:.2f})")
        elif avg < -0.5:
            return (-10, f"FINBERT_BEARISH({avg:.2f})")
        elif avg < -0.2:
            return (-5, f"FINBERT_NEGATIVE({avg:.2f})")
        else:
            return (0, f"FINBERT_NEUTRAL({avg:.2f})")
    
    # Fallback to VADER
    vader_result = analyze_news_vader(news)
    score = vader_result["score"]
    
    if score > 0.3:
        return (7, f"VADER_POSITIVE({score})")
    elif score < -0.3:
        return (-7, f"VADER_NEGATIVE({score})")
    else:
        return (0, f"VADER_NEUTRAL({score})")

# ============================================================================
# Combined Sentiment Analysis
# ============================================================================

def get_combined_sentiment(symbol: str) -> dict:
    global _sentiment_cache
    import time as _time
    now = _time.time()
    # Use generic key for BTC/crypto-wide sentiment
    base_coin = symbol.replace("USDT", "").replace("-USD", "").replace("-INR", "")[:3]
    cache_key = base_coin  # Group by base coin
    if cache_key in _sentiment_cache and (now - _sentiment_cache[cache_key]["ts"]) < SENTIMENT_CACHE_TTL:
        return _sentiment_cache[cache_key]["data"]
    result = _get_combined_sentiment_uncached(symbol)
    _sentiment_cache[cache_key] = {"data": result, "ts": now}
    return result

def _get_combined_sentiment_uncached(symbol: str) -> dict:
    """
    Get combined sentiment from all sources
    
    Returns:
        dict with total score, signals, and breakdown
    """
    result = {
        "score": 0,
        "signals": [],
        "fear_greed": None,
        "news": None,
        "finbert": None
    }
    
    # Fear & Greed
    fg_points, fg_signal = score_fear_greed()
    result["score"] += fg_points
    if fg_points != 0:
        result["signals"].append(fg_signal)
    result["fear_greed"] = get_fear_greed()
    
    # News + FinBERT
    finbert_points, finbert_signal = score_finbert(symbol)
    result["score"] += finbert_points
    if finbert_points != 0:
        result["signals"].append(finbert_signal)
    
    # Determine overall sentiment
    if result["score"] >= 10:
        result["overall"] = "bullish"
    elif result["score"] <= -10:
        result["overall"] = "bearish"
    else:
        result["overall"] = "neutral"
    
    return result

# ============================================================================
# Test function
# ============================================================================

if __name__ == "__main__":
    print("=== SENTIMENT V11 TEST ===")
    
    # Fear & Greed
    fg = get_fear_greed()
    print(f"Fear & Greed: {fg}")
    
    # Score
    points, signal = score_fear_greed()
    print(f"F&G Score: {points} pts ({signal})")
    
    # News
    news = get_crypto_news("BTCUSD")
    print(f"News articles: {len(news)}")
    if news:
        print(f"Latest: {news[0].get(title, N/A)[:60]}...")
    
    # Combined
    combined = get_combined_sentiment("BTCUSD")
    print(f"Combined Score: {combined['score']}")
    print(f"Signals: {combined['signals']}")
    print(f"Overall: {combined['overall']}")
    
    print("✅ Sentiment V11 test complete!")

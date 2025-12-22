#!/usr/bin/env python3
"""
V9 Sentiment Analysis Module
Created: December 20, 2025

Features:
- Fear & Greed Index from Alternative.me (free, no API key)
- Sentiment caching with TTL
- Score adjustments for trading signals
"""

import requests
import time
import logging
from typing import Tuple, Optional
from datetime import datetime

# Try to import VADER, but don't fail if not available
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False
    logging.warning("VADER sentiment not available. Install: pip3 install vaderSentiment")


class SentimentCache:
    """Simple cache with TTL for sentiment data"""
    
    def __init__(self, ttl_seconds: int = 300):
        self.ttl = ttl_seconds
        self.cache = {}  # key -> (value, timestamp)
    
    def get(self, key: str) -> Optional[any]:
        if key in self.cache:
            value, ts = self.cache[key]
            if time.time() - ts < self.ttl:
                return value
            del self.cache[key]
        return None
    
    def set(self, key: str, value: any):
        self.cache[key] = (value, time.time())
    
    def clear(self):
        self.cache.clear()


class FearGreedIndex:
    """
    Crypto Fear & Greed Index from Alternative.me
    
    Values:
    0-25: Extreme Fear (contrarian buy signal)
    26-46: Fear
    47-54: Neutral
    55-75: Greed
    76-100: Extreme Greed (caution signal)
    """
    
    API_URL = "https://api.alternative.me/fng/"
    
    def __init__(self, cache_ttl: int = 600):  # Cache for 10 minutes
        self.cache = SentimentCache(cache_ttl)
        self.last_value = 50  # Default neutral
        self.last_classification = "Neutral"
    
    def fetch(self) -> Tuple[int, str]:
        """Fetch current Fear & Greed Index"""
        # Check cache first
        cached = self.cache.get("fng")
        if cached:
            return cached
        
        try:
            response = requests.get(self.API_URL, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if 'data' in data and len(data['data']) > 0:
                value = int(data['data'][0]['value'])
                classification = data['data'][0]['value_classification']
                
                self.last_value = value
                self.last_classification = classification
                self.cache.set("fng", (value, classification))
                
                logging.debug(f"Fear & Greed: {value} ({classification})")
                return value, classification
                
        except requests.RequestException as e:
            logging.warning(f"Fear & Greed API error: {e}")
        except (KeyError, ValueError, IndexError) as e:
            logging.warning(f"Fear & Greed parse error: {e}")
        
        return self.last_value, self.last_classification
    
    def get_score_adjustment(self) -> Tuple[int, Optional[str]]:
        """
        Get score adjustment based on Fear & Greed
        
        Returns:
            (points, signal_name) or (0, None)
        """
        value, classification = self.fetch()
        
        # Extreme Fear = contrarian buy signal
        if value < 25:
            return 15, f"FEAR({value})"
        
        # Fear = mild buy signal
        if value < 45:
            return 5, f"FEAR({value})"
        
        # Extreme Greed = caution, reduce position
        if value > 75:
            return -10, f"GREED({value})"
        
        # Greed = mild caution
        if value > 65:
            return -5, None  # Don't add to signals
        
        # Neutral
        return 0, None


class CryptoSentiment:
    """
    Combined sentiment analysis using multiple sources
    """
    
    def __init__(self):
        self.fear_greed = FearGreedIndex()
        self.vader = SentimentIntensityAnalyzer() if VADER_AVAILABLE else None
        self.cache = SentimentCache(300)  # 5 minute cache
    
    def analyze_text(self, text: str) -> float:
        """
        Analyze sentiment of text using VADER
        Returns compound score: -1.0 (negative) to +1.0 (positive)
        """
        if not self.vader:
            return 0.0
        
        try:
            scores = self.vader.polarity_scores(text)
            return scores['compound']
        except:
            return 0.0
    
    def get_market_sentiment(self) -> dict:
        """Get overall market sentiment"""
        fg_value, fg_class = self.fear_greed.fetch()
        
        return {
            'fear_greed_value': fg_value,
            'fear_greed_class': fg_class,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_combined_adjustment(self, symbol: str = None) -> Tuple[int, list]:
        """
        Get combined score adjustment from all sentiment sources
        
        Returns:
            (total_points, list_of_signals)
        """
        total_points = 0
        signals = []
        
        # Fear & Greed Index
        fg_points, fg_signal = self.fear_greed.get_score_adjustment()
        total_points += fg_points
        if fg_signal:
            signals.append(fg_signal)
        
        return total_points, signals


# Singleton instance for easy import
_sentiment_analyzer = None

def get_sentiment_analyzer() -> CryptoSentiment:
    """Get or create singleton sentiment analyzer"""
    global _sentiment_analyzer
    if _sentiment_analyzer is None:
        _sentiment_analyzer = CryptoSentiment()
    return _sentiment_analyzer


def get_fear_greed() -> Tuple[int, str]:
    """Convenience function to get Fear & Greed Index"""
    return get_sentiment_analyzer().fear_greed.fetch()


def get_sentiment_adjustment(symbol: str = None) -> Tuple[int, list]:
    """Convenience function to get sentiment score adjustment"""
    return get_sentiment_analyzer().get_combined_adjustment(symbol)


# Test code
if __name__ == "__main__":
    print("=" * 50)
    print("V9 Sentiment Analysis Module Test")
    print("=" * 50)
    
    # Test Fear & Greed
    print("\n1. Testing Fear & Greed Index...")
    fg = FearGreedIndex()
    value, classification = fg.fetch()
    print(f"   Current Value: {value}")
    print(f"   Classification: {classification}")
    
    points, signal = fg.get_score_adjustment()
    print(f"   Score Adjustment: {points:+d} pts")
    print(f"   Signal: {signal}")
    
    # Test combined
    print("\n2. Testing Combined Sentiment...")
    sentiment = CryptoSentiment()
    market = sentiment.get_market_sentiment()
    print(f"   Market Sentiment: {market}")
    
    total, signals = sentiment.get_combined_adjustment()
    print(f"   Total Adjustment: {total:+d} pts")
    print(f"   Signals: {signals}")
    
    # Test caching
    print("\n3. Testing Cache (should be instant)...")
    start = time.time()
    for _ in range(10):
        fg.fetch()
    elapsed = time.time() - start
    print(f"   10 cached fetches: {elapsed*1000:.1f}ms")
    
    print("\n" + "=" * 50)
    print("Sentiment Module OK")
    print("=" * 50)

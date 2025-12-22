#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V8 - Sentiment Analysis
===================================================
NLP-based sentiment signals for trading decisions.

Features:
- Fear & Greed Index (free, no API key)
- Twitter/X sentiment (optional - requires API key)
- VADER sentiment analyzer
- News headline analysis
- Caching to avoid rate limits

Author: Vibhav Aggarwal
Date: December 20, 2025
"""

import os
import json
import time
import requests
from typing import Dict, List, Tuple, Optional
from datetime import datetime

# VADER for sentiment analysis (standard library if installed)
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    HAS_VADER = True
except ImportError:
    HAS_VADER = False
    print("⚠️ VADER not installed - pip3 install vaderSentiment")

# Tweepy for Twitter (optional)
try:
    import tweepy
    HAS_TWEEPY = True
except ImportError:
    HAS_TWEEPY = False


# ============================================
# CONFIGURATION
# ============================================

# Fear & Greed Index (free, no API needed)
FEAR_GREED_URL = "https://api.alternative.me/fng/"

# Twitter API (optional - set via environment variables)
TWITTER_BEARER_TOKEN = os.environ.get("TWITTER_BEARER_TOKEN", "")

# Cache settings
CACHE_TTL = 300  # 5 minutes


# ============================================
# FEAR & GREED INDEX
# ============================================

class FearGreedIndex:
    """
    Crypto Fear & Greed Index from alternative.me.
    Free API, no key required.
    
    Values:
    - 0-25: Extreme Fear (contrarian BUY signal)
    - 25-45: Fear
    - 45-55: Neutral
    - 55-75: Greed
    - 75-100: Extreme Greed (contrarian SELL signal)
    """
    
    def __init__(self):
        self._cache = None
        self._cache_time = 0
    
    def get(self) -> Dict:
        """Get current Fear & Greed Index."""
        # Check cache
        if self._cache and time.time() - self._cache_time < CACHE_TTL:
            return self._cache
        
        try:
            resp = requests.get(FEAR_GREED_URL, timeout=10)
            data = resp.json()
            
            if data.get("data"):
                fng = data["data"][0]
                result = {
                    "value": int(fng.get("value", 50)),
                    "classification": fng.get("value_classification", "Neutral"),
                    "timestamp": fng.get("timestamp", ""),
                    "score": self._calculate_score(int(fng.get("value", 50)))
                }
                self._cache = result
                self._cache_time = time.time()
                return result
        except Exception as e:
            print(f"Fear & Greed API error: {e}")
        
        return {"value": 50, "classification": "Neutral", "score": 0}
    
    def _calculate_score(self, value: int) -> int:
        """
        Convert F&G value to trading score.
        Contrarian: Extreme fear = bullish, extreme greed = bearish.
        """
        if value < 20:  # Extreme Fear
            return 15  # Strong contrarian BUY
        elif value < 30:  # Fear
            return 10
        elif value < 45:  # Fear-leaning
            return 5
        elif value <= 55:  # Neutral
            return 0
        elif value < 70:  # Greed
            return -5
        elif value < 80:  # High Greed
            return -10
        else:  # Extreme Greed
            return -15  # Contrarian SELL / reduce position


# ============================================
# TWITTER SENTIMENT (Optional)
# ============================================

class TwitterSentiment:
    """
    Twitter/X sentiment analysis for crypto assets.
    Requires Twitter API Bearer Token (v2).
    
    Setup:
    1. Create Twitter Developer account
    2. Create app, get Bearer Token
    3. Set TWITTER_BEARER_TOKEN environment variable
    """
    
    def __init__(self, bearer_token: str = None):
        self.bearer_token = bearer_token or TWITTER_BEARER_TOKEN
        self.enabled = bool(self.bearer_token and HAS_TWEEPY)
        self.client = None
        self.analyzer = SentimentIntensityAnalyzer() if HAS_VADER else None
        self._cache = {}  # symbol -> (score, timestamp)
        
        if self.enabled:
            self.client = tweepy.Client(bearer_token=self.bearer_token)
            print("✅ Twitter sentiment enabled")
        else:
            print("⚠️ Twitter sentiment disabled (no API key or missing tweepy)")
    
    def get_sentiment(self, symbol: str) -> Dict:
        """
        Get Twitter sentiment for a crypto symbol.
        Returns sentiment score from -1 (bearish) to +1 (bullish).
        """
        if not self.enabled or not self.analyzer:
            return {"score": 0, "count": 0, "trading_score": 0}
        
        # Check cache
        if symbol in self._cache:
            cached_score, cached_time = self._cache[symbol]
            if time.time() - cached_time < CACHE_TTL:
                return cached_score
        
        # Clean symbol for search (BTCUSD -> BTC)
        clean_symbol = symbol.replace("USD", "").replace("PERP", "")
        query = f"${clean_symbol} OR #{clean_symbol} -is:retweet lang:en"
        
        try:
            # Fetch recent tweets
            tweets = self.client.search_recent_tweets(
                query=query,
                max_results=100,
                tweet_fields=["created_at", "public_metrics"]
            )
            
            if not tweets.data:
                return {"score": 0, "count": 0, "trading_score": 0}
            
            # Analyze sentiment
            scores = []
            for tweet in tweets.data:
                sentiment = self.analyzer.polarity_scores(tweet.text)
                scores.append(sentiment["compound"])
            
            avg_score = sum(scores) / len(scores) if scores else 0
            
            result = {
                "score": avg_score,
                "count": len(scores),
                "trading_score": self._to_trading_score(avg_score),
                "raw_scores": {
                    "positive": len([s for s in scores if s > 0.1]),
                    "negative": len([s for s in scores if s < -0.1]),
                    "neutral": len([s for s in scores if -0.1 <= s <= 0.1])
                }
            }
            
            # Cache result
            self._cache[symbol] = (result, time.time())
            return result
            
        except Exception as e:
            print(f"Twitter API error: {e}")
            return {"score": 0, "count": 0, "trading_score": 0}
    
    def _to_trading_score(self, sentiment: float) -> int:
        """Convert sentiment score to trading points."""
        if sentiment > 0.4:
            return 15  # Very bullish
        elif sentiment > 0.2:
            return 10
        elif sentiment > 0.1:
            return 5
        elif sentiment < -0.4:
            return -15  # Very bearish
        elif sentiment < -0.2:
            return -10
        elif sentiment < -0.1:
            return -5
        return 0


# ============================================
# CRYPTO NEWS SENTIMENT
# ============================================

class CryptoNewsSentiment:
    """
    Crypto news sentiment from public sources.
    Uses CryptoPanic public API (limited without key).
    """
    
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer() if HAS_VADER else None
        self._cache = {}
        
    def get_news_sentiment(self, currency: str = "BTC") -> Dict:
        """Get sentiment from crypto news headlines."""
        if not self.analyzer:
            return {"score": 0, "headlines": [], "trading_score": 0}
        
        # Check cache
        if currency in self._cache:
            cached, cached_time = self._cache[currency]
            if time.time() - cached_time < CACHE_TTL * 2:  # 10 min cache for news
                return cached
        
        try:
            # CryptoPanic public API (limited)
            url = f"https://cryptopanic.com/api/v1/posts/?auth_token=free&public=true&currencies={currency}"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            
            headlines = []
            scores = []
            
            for post in data.get("results", [])[:20]:
                title = post.get("title", "")
                if title:
                    headlines.append(title)
                    sentiment = self.analyzer.polarity_scores(title)
                    scores.append(sentiment["compound"])
            
            avg_score = sum(scores) / len(scores) if scores else 0
            
            result = {
                "score": avg_score,
                "headlines": headlines[:5],
                "trading_score": self._to_trading_score(avg_score)
            }
            
            self._cache[currency] = (result, time.time())
            return result
            
        except Exception as e:
            # CryptoPanic might block, fallback to neutral
            return {"score": 0, "headlines": [], "trading_score": 0}
    
    def _to_trading_score(self, sentiment: float) -> int:
        """Convert news sentiment to trading points."""
        if sentiment > 0.3:
            return 10
        elif sentiment > 0.1:
            return 5
        elif sentiment < -0.3:
            return -10
        elif sentiment < -0.1:
            return -5
        return 0


# ============================================
# COMBINED SENTIMENT
# ============================================

class CombinedSentiment:
    """
    Combine all sentiment sources into single score.
    
    Weights:
    - Fear & Greed: 40% (most reliable, contrarian)
    - Twitter: 30% (if available)
    - News: 30% (if available)
    """
    
    def __init__(self):
        self.fng = FearGreedIndex()
        self.twitter = TwitterSentiment()
        self.news = CryptoNewsSentiment()
    
    def get_sentiment(self, symbol: str = "BTCUSD") -> Dict:
        """Get combined sentiment for a symbol."""
        # Fear & Greed (always available)
        fng = self.fng.get()
        
        # Twitter (if enabled)
        twitter = self.twitter.get_sentiment(symbol) if self.twitter.enabled else {"trading_score": 0}
        
        # News
        currency = symbol.replace("USD", "").replace("PERP", "")
        news = self.news.get_news_sentiment(currency)
        
        # Weighted combination
        if self.twitter.enabled:
            combined_score = (
                fng["score"] * 0.4 +
                twitter["trading_score"] * 0.3 +
                news["trading_score"] * 0.3
            )
        else:
            combined_score = (
                fng["score"] * 0.6 +
                news["trading_score"] * 0.4
            )
        
        return {
            "combined_score": int(combined_score),
            "fear_greed": fng,
            "twitter": twitter,
            "news": news,
            "recommendation": self._get_recommendation(int(combined_score), fng["value"])
        }
    
    def _get_recommendation(self, score: int, fng_value: int) -> str:
        """Get trading recommendation from sentiment."""
        if score >= 10 or fng_value < 25:
            return "BULLISH - Sentiment supports long"
        elif score >= 5:
            return "SLIGHTLY_BULLISH"
        elif score <= -10 or fng_value > 75:
            return "BEARISH - Sentiment warns against long"
        elif score <= -5:
            return "SLIGHTLY_BEARISH"
        return "NEUTRAL"


# ============================================
# MAIN
# ============================================

def main():
    print("="*50)
    print("V8 Sentiment Analysis Module")
    print("="*50)
    
    # Test Fear & Greed
    print("\n📊 Fear & Greed Index:")
    fng = FearGreedIndex()
    result = fng.get()
    print(f"  Value: {result['value']} ({result['classification']})")
    print(f"  Trading Score: {result['score']:+d} pts")
    
    # Test Twitter (if enabled)
    print("\n🐦 Twitter Sentiment:")
    twitter = TwitterSentiment()
    if twitter.enabled:
        btc_sentiment = twitter.get_sentiment("BTCUSD")
        print(f"  BTC Score: {btc_sentiment['score']:.2f}")
        print(f"  Tweet Count: {btc_sentiment['count']}")
        print(f"  Trading Score: {btc_sentiment['trading_score']:+d} pts")
    else:
        print("  Not enabled (set TWITTER_BEARER_TOKEN)")
    
    # Combined sentiment
    print("\n🎯 Combined Sentiment:")
    combined = CombinedSentiment()
    result = combined.get_sentiment("BTCUSD")
    print(f"  Combined Score: {result['combined_score']:+d} pts")
    print(f"  Recommendation: {result['recommendation']}")
    
    print("\n" + "="*50)
    print("Integration with V8 bot:")
    print("  from sentiment_v8 import CombinedSentiment")
    print("  sentiment = CombinedSentiment()")
    print("  score = sentiment.get_sentiment(symbol)['combined_score']")


if __name__ == "__main__":
    main()

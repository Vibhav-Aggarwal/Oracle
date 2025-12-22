#!/usr/bin/env python3
"""
Social Sentiment Analysis for Oracle Trading Bot
Uses free APIs - no API keys required for basic usage
"""

import requests
import logging
import time
import re
from typing import Dict, Tuple, Optional
from datetime import datetime

class SocialSentiment:
    """Analyze crypto sentiment from social sources"""
    
    CACHE_TTL = 300  # 5 minutes cache
    
    def __init__(self):
        self.cache = {}  # symbol -> (score, timestamp)
        self.last_global_fetch = 0
        self.global_sentiment = 0
    
    def get_lunarcrush_sentiment(self, symbol: str) -> float:
        """Get sentiment from LunarCrush (free tier)"""
        try:
            # LunarCrush public endpoint
            coin = symbol.replace('USD', '').lower()
            url = f"https://lunarcrush.com/api3/coins/{coin}/time-series"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('data'):
                    latest = data['data'][-1]
                    # Sentiment score 1-5, normalize to -1 to 1
                    score = (float(latest.get('average_sentiment', 3)) - 3) / 2
                    return score
        except Exception as e:
            logging.debug(f'[SENTIMENT] LunarCrush error: {e}')
        return 0
    
    def get_reddit_sentiment(self, symbol: str) -> float:
        """Get Reddit mentions sentiment"""
        try:
            coin = symbol.replace('USD', '')
            # Use pushshift or reddit search
            url = f"https://www.reddit.com/r/CryptoCurrency/search.json"
            params = {
                'q': coin,
                'sort': 'new',
                'limit': 25,
                't': 'day'
            }
            headers = {'User-Agent': 'OracleBot/1.0'}
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code == 200:
                data = resp.json()
                posts = data.get('data', {}).get('children', [])
                
                if not posts:
                    return 0
                
                # Simple sentiment: upvote ratio and keywords
                total_score = 0
                for post in posts:
                    p = post.get('data', {})
                    upvote_ratio = float(p.get('upvote_ratio', 0.5))
                    title = p.get('title', '').lower()
                    
                    # Basic keyword sentiment
                    bullish = len(re.findall(r'bull|moon|pump|buy|long|breakout', title))
                    bearish = len(re.findall(r'bear|dump|sell|short|crash|scam', title))
                    
                    post_score = (upvote_ratio - 0.5) * 2  # -1 to 1
                    post_score += (bullish - bearish) * 0.2
                    total_score += post_score
                
                return max(-1, min(1, total_score / len(posts)))
        except Exception as e:
            logging.debug(f'[SENTIMENT] Reddit error: {e}')
        return 0
    
    def get_crypto_twitter_sentiment(self) -> float:
        """Get overall crypto Twitter sentiment (no API key)"""
        try:
            # Use alternative.me sentiment or similar free source
            url = "https://api.alternative.me/fng/"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                # Fear & Greed 0-100, normalize to -1 to 1
                fng = int(data['data'][0]['value'])
                return (fng - 50) / 50  # -1 (fear) to 1 (greed)
        except:
            pass
        return 0
    
    def get_sentiment(self, symbol: str) -> Tuple[float, str]:
        """
        Get aggregated sentiment for a symbol
        Returns: (score -1 to 1, signal string)
        """
        # Check cache
        if symbol in self.cache:
            cached_score, cached_time = self.cache[symbol]
            if time.time() - cached_time < self.CACHE_TTL:
                return self._score_to_signal(cached_score)
        
        # Aggregate from sources
        scores = []
        
        # Reddit sentiment
        reddit = self.get_reddit_sentiment(symbol)
        if reddit != 0:
            scores.append(reddit)
        
        # Global crypto sentiment
        if time.time() - self.last_global_fetch > self.CACHE_TTL:
            self.global_sentiment = self.get_crypto_twitter_sentiment()
            self.last_global_fetch = time.time()
        
        if self.global_sentiment != 0:
            scores.append(self.global_sentiment * 0.5)  # Weight less
        
        # Calculate final score
        if scores:
            final_score = sum(scores) / len(scores)
        else:
            final_score = 0
        
        # Cache result
        self.cache[symbol] = (final_score, time.time())
        
        return self._score_to_signal(final_score)
    
    def _score_to_signal(self, score: float) -> Tuple[float, str]:
        """Convert score to trading signal"""
        if score > 0.3:
            return score, "SOCIAL+"
        elif score < -0.3:
            return score, "SOCIAL-"
        return score, None
    
    def get_score_adjustment(self, symbol: str) -> Tuple[int, Optional[str]]:
        """Get score adjustment for trading bot"""
        score, signal = self.get_sentiment(symbol)
        
        if signal == "SOCIAL+":
            return 10, f"SOCIAL+({score:.0%})"
        elif signal == "SOCIAL-":
            return -10, f"SOCIAL-({score:.0%})"
        return 0, None


# Singleton
_sentiment = None

def get_social_sentiment() -> SocialSentiment:
    global _sentiment
    if _sentiment is None:
        _sentiment = SocialSentiment()
    return _sentiment

def get_social_adjustment(symbol: str) -> Tuple[int, Optional[str]]:
    return get_social_sentiment().get_score_adjustment(symbol)


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    
    sentiment = SocialSentiment()
    
    # Test with BTC
    print("Testing social sentiment...")
    score, signal = sentiment.get_sentiment('BTCUSD')
    print(f"BTCUSD: Score={score:.2f}, Signal={signal}")
    
    adj, sig = sentiment.get_score_adjustment('BTCUSD')
    print(f"Score adjustment: {adj:+d}, {sig}")
    
    print("\nSocial sentiment module ready!")

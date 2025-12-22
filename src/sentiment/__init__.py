"""
Oracle Bot - Sentiment Analysis Module

This module provides market sentiment analysis for trading signals.

Versions:
- v11 (current): Combined sentiment, Fear & Greed, FinBERT
- v9: Improved scoring, rate limiting
- v8: Basic news analysis

Usage:
    from sentiment.sentiment_v11 import get_combined_sentiment, score_fear_greed
"""

from .sentiment_v11 import (
    get_combined_sentiment,
    score_fear_greed
)

__version__ = "11.0.0"
__all__ = [
    "get_combined_sentiment",
    "score_fear_greed"
]

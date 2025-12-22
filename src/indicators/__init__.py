"""
Oracle Bot - Technical Indicators Module

This module provides technical analysis indicators for trading signals.

Versions:
- v11 (current): 90+ indicators, multi-timeframe, ATR calculation
- v9: Squeeze momentum, VWAP improvements
- v8: Bollinger Bands, RSI divergence
- v7: Basic MACD, RSI

Usage:
    from indicators.indicators_v11 import calculate_all_indicators, calculate_atr_percent
"""

from .indicators_v11 import (
    calculate_all_indicators,
    calculate_dynamic_sl_tp,
    calculate_atr_percent
)

__version__ = "11.0.0"
__all__ = [
    "calculate_all_indicators",
    "calculate_dynamic_sl_tp",
    "calculate_atr_percent"
]

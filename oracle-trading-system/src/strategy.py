"""
Oracle Trading Strategy - Production Implementation
Optimized RSI-based momentum strategy with proper signal generation
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class Signal(Enum):
    """Trading signal types"""
    LONG = "long"
    SHORT = "short"
    EXIT_LONG = "exit_long"
    EXIT_SHORT = "exit_short"
    HOLD = "hold"


@dataclass
class TradeSignal:
    """Structured trade signal with metadata"""
    signal: Signal
    symbol: str
    timestamp: datetime
    price: float
    confidence: float
    indicators: Dict[str, float]
    reason: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal": self.signal.value,
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "price": self.price,
            "confidence": self.confidence,
            "indicators": self.indicators,
            "reason": self.reason
        }


class OracleStrategy:
    """
    Production RSI Momentum Strategy
    
    Optimized parameters from backtesting (66% annual return):
    - RSI Entry: 30-60 (oversold to neutral zone)
    - Stop Loss: 7%
    - Take Profit: 21% (3:1 R:R)
    - Risk per trade: 5%
    """
    
    def __init__(self, config):
        self.config = config
        
        # Strategy parameters (from optimized config)
        self.rsi_period = config.strategy.rsi_period
        self.rsi_entry_low = config.strategy.rsi_entry_low
        self.rsi_entry_high = config.strategy.rsi_entry_high
        self.rsi_exit = config.strategy.rsi_exit
        self.fast_sma = config.strategy.fast_sma
        self.slow_sma = config.strategy.slow_sma
        self.stop_loss = config.strategy.stop_loss
        self.take_profit = config.strategy.take_profit
        
        # Internal state
        self._candle_buffer: Dict[str, List[Dict]] = {}
        self._indicators: Dict[str, Dict[str, float]] = {}
        
        logger.info(f"Strategy initialized: RSI({self.rsi_period}) "
                   f"Entry[{self.rsi_entry_low}-{self.rsi_entry_high}] "
                   f"SL:{self.stop_loss*100:.1f}% TP:{self.take_profit*100:.1f}%")
    
    def update_candle(self, symbol: str, candle: Dict) -> None:
        """Add new candle to buffer for indicator calculation"""
        if symbol not in self._candle_buffer:
            self._candle_buffer[symbol] = []
        
        self._candle_buffer[symbol].append(candle)
        
        # Keep last 100 candles for indicator calculation
        if len(self._candle_buffer[symbol]) > 100:
            self._candle_buffer[symbol] = self._candle_buffer[symbol][-100:]
        
        # Recalculate indicators
        self._calculate_indicators(symbol)
    
    def _calculate_indicators(self, symbol: str) -> None:
        """Calculate RSI and SMAs from candle buffer"""
        candles = self._candle_buffer.get(symbol, [])
        
        if len(candles) < self.slow_sma:
            return
        
        df = pd.DataFrame(candles)
        closes = df["close"].astype(float)
        
        # RSI calculation
        delta = closes.diff()
        gain = delta.where(delta > 0, 0).rolling(self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(self.rsi_period).mean()
        rs = gain / loss.replace(0, np.inf)
        rsi = 100 - (100 / (1 + rs))
        
        # SMA calculation
        fast_sma = closes.rolling(self.fast_sma).mean()
        slow_sma = closes.rolling(self.slow_sma).mean()
        
        self._indicators[symbol] = {
            "rsi": rsi.iloc[-1],
            "rsi_prev": rsi.iloc[-2] if len(rsi) > 1 else rsi.iloc[-1],
            "fast_sma": fast_sma.iloc[-1],
            "slow_sma": slow_sma.iloc[-1],
            "price": closes.iloc[-1],
            "trend": "bullish" if fast_sma.iloc[-1] > slow_sma.iloc[-1] else "bearish"
        }
    
    def generate_signal(self, symbol: str, current_position: Optional[str] = None) -> TradeSignal:
        """
        Generate trading signal based on current indicators and position
        
        Args:
            symbol: Trading pair symbol
            current_position: Current position ("long", "short", or None)
        
        Returns:
            TradeSignal with action to take
        """
        indicators = self._indicators.get(symbol)
        
        if not indicators:
            return TradeSignal(
                signal=Signal.HOLD,
                symbol=symbol,
                timestamp=datetime.utcnow(),
                price=0,
                confidence=0,
                indicators={},
                reason="Insufficient data for indicators"
            )
        
        rsi = indicators["rsi"]
        rsi_prev = indicators["rsi_prev"]
        price = indicators["price"]
        trend = indicators["trend"]
        
        # Default signal
        signal = Signal.HOLD
        confidence = 0.0
        reason = "No signal conditions met"
        
        # Exit conditions (check first)
        if current_position == "long":
            if rsi >= self.rsi_exit:
                signal = Signal.EXIT_LONG
                confidence = min(1.0, (rsi - self.rsi_exit) / 10)
                reason = f"RSI overbought exit: {rsi:.1f} >= {self.rsi_exit}"
        
        elif current_position == "short":
            if rsi <= (100 - self.rsi_exit):
                signal = Signal.EXIT_SHORT
                confidence = min(1.0, ((100 - self.rsi_exit) - rsi) / 10)
                reason = f"RSI oversold exit: {rsi:.1f} <= {100 - self.rsi_exit}"
        
        # Entry conditions (only if no position)
        elif current_position is None:
            # Long entry: RSI crossing up from oversold
            if (rsi_prev < self.rsi_entry_low <= rsi <= self.rsi_entry_high 
                and trend == "bullish"):
                signal = Signal.LONG
                confidence = min(1.0, (self.rsi_entry_high - rsi) / 
                               (self.rsi_entry_high - self.rsi_entry_low))
                reason = f"RSI bullish crossup: {rsi_prev:.1f} -> {rsi:.1f}, trend: {trend}"
            
            # Short entry: RSI crossing down from overbought
            elif (rsi_prev > (100 - self.rsi_entry_low) >= rsi >= (100 - self.rsi_entry_high)
                  and trend == "bearish"):
                signal = Signal.SHORT
                confidence = min(1.0, (rsi - (100 - self.rsi_entry_high)) / 
                               (self.rsi_entry_high - self.rsi_entry_low))
                reason = f"RSI bearish crossdown: {rsi_prev:.1f} -> {rsi:.1f}, trend: {trend}"
        
        return TradeSignal(
            signal=signal,
            symbol=symbol,
            timestamp=datetime.utcnow(),
            price=price,
            confidence=confidence,
            indicators=indicators,
            reason=reason
        )
    
    def calculate_position_size(self, balance: float, entry_price: float) -> float:
        """
        Calculate position size based on risk management rules
        
        Uses fixed fractional position sizing:
        Position = (Balance * Risk%) / Stop Loss %
        """
        risk_amount = balance * self.config.strategy.risk_per_trade
        position_size = risk_amount / (entry_price * self.stop_loss)
        
        # Apply maximum position limit
        max_position = balance * 0.5 / entry_price  # Max 50% of balance
        return min(position_size, max_position)
    
    def get_stop_loss_price(self, entry_price: float, side: str) -> float:
        """Calculate stop loss price for a position"""
        if side == "long":
            return entry_price * (1 - self.stop_loss)
        else:  # short
            return entry_price * (1 + self.stop_loss)
    
    def get_take_profit_price(self, entry_price: float, side: str) -> float:
        """Calculate take profit price for a position"""
        if side == "long":
            return entry_price * (1 + self.take_profit)
        else:  # short
            return entry_price * (1 - self.take_profit)
    
    def get_indicators(self, symbol: str) -> Dict[str, float]:
        """Get current indicators for a symbol"""
        return self._indicators.get(symbol, {})
    
    def get_status(self) -> Dict[str, Any]:
        """Get strategy status summary"""
        return {
            "parameters": {
                "rsi_period": self.rsi_period,
                "rsi_entry": [self.rsi_entry_low, self.rsi_entry_high],
                "rsi_exit": self.rsi_exit,
                "stop_loss": f"{self.stop_loss*100:.1f}%",
                "take_profit": f"{self.take_profit*100:.1f}%"
            },
            "symbols_tracked": list(self._indicators.keys()),
            "indicators": {
                sym: {
                    "rsi": round(ind.get("rsi", 0), 2),
                    "trend": ind.get("trend", "unknown")
                }
                for sym, ind in self._indicators.items()
            }
        }

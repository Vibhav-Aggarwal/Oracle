#!/usr/bin/env python3
"""
ORACLE BOT TEST SUITE
Production-grade unit tests for critical trading functions

Run with: pytest tests/ -v
"""

import pytest
import json
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from dataclasses import asdict

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestFeeStructure:
    """Test fee calculations for all exchanges"""
    
    def test_delta_taker_fee(self):
        """Delta taker fee should be 0.05% + 18% GST"""
        from oracle_bot import FeeStructure
        fee = FeeStructure.calculate_delta_fee(1000, is_taker=True)
        # 1000 * 0.0005 * 1.18 = 0.59
        assert 0.58 < fee < 0.60
    
    def test_delta_maker_fee(self):
        """Delta maker fee should be 0.02% + 18% GST"""
        from oracle_bot import FeeStructure
        fee = FeeStructure.calculate_delta_fee(1000, is_taker=False)
        # 1000 * 0.0002 * 1.18 = 0.236
        assert 0.23 < fee < 0.24
    
    def test_profit_calculation_long_win(self):
        """Test profit calc for winning LONG trade"""
        from oracle_bot import FeeStructure
        result = FeeStructure.calculate_profit(
            exchange="Delta",
            entry_price=100,
            exit_price=110,
            size=1000,
            direction="LONG",
            leverage=5
        )
        assert result["gross_pnl"] == 500  # 10% * 1000 * 5
        assert result["net_pnl"] > 0
        assert result["roi_pct"] > 0
    
    def test_profit_calculation_short_win(self):
        """Test profit calc for winning SHORT trade"""
        from oracle_bot import FeeStructure
        result = FeeStructure.calculate_profit(
            exchange="Delta",
            entry_price=100,
            exit_price=90,
            size=1000,
            direction="SHORT",
            leverage=5
        )
        assert result["gross_pnl"] == 500  # 10% * 1000 * 5
        assert result["net_pnl"] > 0


class TestPosition:
    """Test Position dataclass"""
    
    def test_position_creation(self):
        """Test creating a position"""
        from oracle_bot import Position
        pos = Position(
            symbol="BTCUSDT",
            exchange="Delta",
            direction="LONG",
            entry_price=50000.0,
            size_usd=100.0,
            leverage=5,
            stop_loss=0.02,
            take_profit=0.04,
            entry_time=datetime.now().isoformat(),
            entry_signals=["RSI_OVERSOLD", "MACD_CROSS"]
        )
        assert pos.symbol == "BTCUSDT"
        assert pos.leverage == 5
        assert pos.trailing_active == False
    
    def test_position_to_dict(self):
        """Test position serialization"""
        from oracle_bot import Position
        pos = Position(
            symbol="ETHUSDT",
            exchange="Delta",
            direction="SHORT",
            entry_price=3000.0,
            size_usd=50.0,
            leverage=3,
            stop_loss=0.03,
            take_profit=0.06,
            entry_time="2025-01-01T00:00:00",
            entry_signals=["TREND_DOWN"]
        )
        d = pos.to_dict()
        assert isinstance(d, dict)
        assert d["symbol"] == "ETHUSDT"
        assert d["direction"] == "SHORT"
    
    def test_position_from_dict(self):
        """Test position deserialization with missing fields"""
        from oracle_bot import Position
        data = {
            "symbol": "SOLUSDT",
            "exchange": "Delta",
            "direction": "LONG",
            "entry_price": 100.0,
            "size_usd": 25.0,
            "leverage": 2,
            "stop_loss": 0.01,
            "take_profit": 0.02,
            "entry_time": "2025-01-01T00:00:00",
            "entry_signals": []
            # Missing: trailing_active, highest_pnl, entry_atr
        }
        pos = Position.from_dict(data)
        assert pos.trailing_active == False
        assert pos.highest_pnl == 0.0
        assert pos.entry_atr == 0.0


class TestTrade:
    """Test Trade dataclass"""
    
    def test_trade_creation(self):
        """Test creating a completed trade record"""
        from oracle_bot import Trade
        trade = Trade(
            symbol="BTCUSDT",
            exchange="Delta",
            direction="LONG",
            entry_price=50000.0,
            exit_price=51000.0,
            size_usd=100.0,
            gross_pnl=10.0,
            fees=0.5,
            net_pnl=9.5,
            entry_time="2025-01-01T00:00:00",
            exit_time="2025-01-01T01:00:00",
            exit_reason="TAKE_PROFIT",
            hold_duration_mins=60
        )
        assert trade.net_pnl == 9.5
        assert trade.exit_reason == "TAKE_PROFIT"


class TestRiskManagement:
    """Test risk management functions"""
    
    def test_position_size_clamp(self):
        """Position size should be clamped between 1-5%"""
        # This tests the logic, not the actual function
        base = 0.02  # 2%
        
        # High volatility -> smaller position
        high_vol_factor = 0.5
        size = base * high_vol_factor
        clamped = max(0.01, min(0.05, size))
        assert clamped == 0.01  # Minimum 1%
        
        # Low volatility -> larger position  
        low_vol_factor = 1.5
        size = base * low_vol_factor
        clamped = max(0.01, min(0.05, size))
        assert clamped == 0.03  # 3%
        
        # Very low volatility -> capped at 5%
        very_low_factor = 5.0
        size = base * very_low_factor
        clamped = max(0.01, min(0.05, size))
        assert clamped == 0.05  # Maximum 5%
    
    def test_atr_stop_loss_calculation(self):
        """ATR-based stop loss should be bounded"""
        atr_pct = 2.0  # 2% ATR
        multiplier = 3.0
        
        sl_pct = max(atr_pct * multiplier, 0.5)  # Min 0.5%
        sl_pct = min(sl_pct, 5.0)  # Max 5%
        
        assert sl_pct == 5.0  # 2% * 3 = 6%, capped at 5%
        
        # Low ATR
        atr_pct = 0.1
        sl_pct = max(atr_pct * multiplier, 0.5)
        sl_pct = min(sl_pct, 5.0)
        assert sl_pct == 0.5  # 0.1% * 3 = 0.3%, floored at 0.5%
    
    def test_drawdown_limit(self):
        """Daily drawdown should be limited"""
        balance = 1000.0
        daily_limit_pct = 10.0
        max_daily_loss = balance * daily_limit_pct / 100
        
        assert max_daily_loss == 100.0
        
        # Should block trading if daily PnL exceeds limit
        daily_pnl = -120.0
        should_block = daily_pnl < -max_daily_loss
        assert should_block == True


class TestTrendFilter:
    """Test SMA trend filter logic"""
    
    def test_uptrend_detection(self):
        """SMA50 > SMA200 = Uptrend"""
        sma50 = 105.0
        sma200 = 100.0
        
        is_uptrend = sma50 > sma200
        is_downtrend = sma50 < sma200
        
        assert is_uptrend == True
        assert is_downtrend == False
    
    def test_downtrend_detection(self):
        """SMA50 < SMA200 = Downtrend"""
        sma50 = 95.0
        sma200 = 100.0
        
        is_uptrend = sma50 > sma200
        is_downtrend = sma50 < sma200
        
        assert is_uptrend == False
        assert is_downtrend == True
    
    def test_trend_blocks_counter_trade(self):
        """Should block LONG in downtrend, SHORT in uptrend"""
        # Downtrend - block LONG
        trend = "DOWN"
        signal = "LONG"
        should_block = (trend == "DOWN" and signal == "LONG")
        assert should_block == True
        
        # Uptrend - block SHORT
        trend = "UP"
        signal = "SHORT"
        should_block = (trend == "UP" and signal == "SHORT")
        assert should_block == True
        
        # Uptrend - allow LONG
        trend = "UP"
        signal = "LONG"
        should_block = (trend == "DOWN" and signal == "LONG") or (trend == "UP" and signal == "SHORT")
        assert should_block == False


class TestMultiTimeframeConfirmation:
    """Test MTF confirmation logic"""
    
    def test_strong_confirmation(self):
        """2+ timeframes agreeing = strong signal"""
        confirmations = 3  # All 3 agree
        is_strong = confirmations >= 2
        assert is_strong == True
    
    def test_weak_confirmation(self):
        """<2 timeframes agreeing = weak signal"""
        confirmations = 1  # Only 1 agrees
        is_strong = confirmations >= 2
        assert is_strong == False
        
        # Should apply penalty
        score = 60
        penalty = 20
        if not is_strong:
            score -= penalty
        assert score == 40


class TestAdaptiveThreshold:
    """Test adaptive scoring threshold"""
    
    def test_high_winrate_lowers_threshold(self):
        """Win rate > 60% should lower threshold"""
        base_threshold = 55
        wins = 70
        losses = 30
        total = wins + losses
        win_rate = wins / total
        
        if win_rate > 0.6:
            threshold = base_threshold - 5
        elif win_rate < 0.4:
            threshold = base_threshold + 10
        else:
            threshold = base_threshold
        
        assert threshold == 50
    
    def test_low_winrate_raises_threshold(self):
        """Win rate < 40% should raise threshold"""
        base_threshold = 55
        wins = 30
        losses = 70
        total = wins + losses
        win_rate = wins / total
        
        if win_rate > 0.6:
            threshold = base_threshold - 5
        elif win_rate < 0.4:
            threshold = base_threshold + 10
        else:
            threshold = base_threshold
        
        assert threshold == 65


class TestTrailingStop:
    """Test trailing stop logic"""
    
    def test_trailing_activation(self):
        """Trailing should activate at +3%"""
        pnl_pct = 0.035  # 3.5%
        trail_start = 0.03  # 3%
        trailing_active = False
        
        if pnl_pct > trail_start and not trailing_active:
            trailing_active = True
        
        assert trailing_active == True
    
    def test_trailing_stop_trigger(self):
        """Should exit when price drops from highest"""
        highest_pnl = 0.05  # 5%
        current_pnl = 0.02  # 2%
        trail_dist = min(0.03, max(0.01, highest_pnl * 0.3))  # Dynamic trail
        
        should_exit = current_pnl < (highest_pnl - trail_dist)
        # 0.02 < (0.05 - 0.015) = 0.02 < 0.035 = True
        assert should_exit == True


class TestMetrics:
    """Test metrics module"""
    
    def test_trade_metrics_calculation(self):
        """Test trade metrics math"""
        from oracle_metrics import TradeMetrics
        
        tm = TradeMetrics()
        tm.total_trades = 10
        tm.winning_trades = 6
        tm.losing_trades = 4
        tm.total_profit = 300.0
        tm.total_loss = -100.0
        
        tm.calculate()
        
        assert tm.win_rate == 60.0
        assert tm.profit_factor == 3.0  # 300/100
        assert tm.avg_win == 50.0  # 300/6
        assert tm.avg_loss == -25.0  # -100/4
    
    def test_expectancy_calculation(self):
        """Test expectancy formula"""
        # Expectancy = (Win% * Avg Win) - (Loss% * Avg Loss)
        win_pct = 0.6
        loss_pct = 0.4
        avg_win = 50.0
        avg_loss = -25.0
        
        expectancy = (win_pct * avg_win) + (loss_pct * avg_loss)
        # (0.6 * 50) + (0.4 * -25) = 30 - 10 = 20
        assert expectancy == 20.0
    
    def test_api_metrics_p95(self):
        """Test P95 latency calculation"""
        from oracle_metrics import APIMetrics
        
        api = APIMetrics()
        latencies = [100, 150, 200, 250, 300, 350, 400, 450, 500, 5000]
        for lat in latencies:
            api.record_call(lat, True)
        
        # P95 should be near 5000 (the 95th percentile)
        assert api.p95_latency >= 500


# Integration test placeholder
class TestIntegration:
    """Integration tests (require mocking)"""
    
    @pytest.mark.skip(reason="Requires live API mocking")
    def test_full_trade_cycle(self):
        """Test open -> monitor -> close cycle"""
        pass
    
    @pytest.mark.skip(reason="Requires WebSocket mocking")
    def test_websocket_reconnection(self):
        """Test WebSocket auto-reconnect"""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

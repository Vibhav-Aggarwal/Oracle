#!/usr/bin/env python3
"""
Delta Exchange Trading Bot V8 - Backtesting Framework
======================================================
Validate strategies on historical data before live trading.

Features:
- Historical data collection (90 days)
- VectorBT integration for fast backtests
- Parameter optimization grid
- Walk-forward validation
- SQLite storage for candle data

Author: Vibhav Aggarwal
Date: December 20, 2025
"""

import os
import sys
import json
import time
import sqlite3
import requests
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np

# Try importing vectorbt (optional - falls back to simple backtest if not available)
try:
    import vectorbt as vbt
    HAS_VECTORBT = True
except ImportError:
    HAS_VECTORBT = False
    print("⚠️ VectorBT not installed - using simple backtest mode")

# Import V8 indicators
from indicators_v8 import (
    calculate_rsi, calculate_macd, calculate_atr,
    detect_bb_squeeze, detect_divergence, calculate_rsi_series
)

# ============================================
# CONFIGURATION
# ============================================

API_KEY = "KMLkcDcajSQWPmVcgNuAd3KWqf7OzM"
API_SECRET = "ltJaGy3GErRluET1e7FaYOklFx1u7pGwCsiCqCO774ndLdPzcnZzmHYscT5W"
BASE_URL = "https://api.india.delta.exchange"

# WARP Proxy
WARP_PROXY_HOST = "127.0.0.1"
WARP_PROXY_PORT = 40000

# Data storage
DB_PATH = "/home/vibhavaggarwal/trading_data.db"

# Backtesting parameters
DEFAULT_SYMBOLS = ["BTCUSD", "ETHUSD", "SOLUSD", "XRPUSD", "LINKUSD"]
LEVERAGE = 10
TAKER_FEE = 0.001  # 0.1% taker fee
SLIPPAGE = 0.001   # 0.1% estimated slippage


# ============================================
# DATA COLLECTION
# ============================================

class DataCollector:
    """Collect and store historical candle data."""
    
    def __init__(self, use_proxy: bool = True):
        self.session = requests.Session()
        
        if use_proxy:
            self.session.proxies = {
                "http": f"socks5h://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}",
                "https": f"socks5h://{WARP_PROXY_HOST}:{WARP_PROXY_PORT}"
            }
        
        self.db = sqlite3.connect(DB_PATH)
        self._create_tables()
    
    def _create_tables(self):
        """Create database tables."""
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                symbol TEXT,
                timestamp INTEGER,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                resolution TEXT,
                PRIMARY KEY (symbol, timestamp, resolution)
            )
        """)
        self.db.execute("""
            CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts 
            ON candles(symbol, timestamp)
        """)
        self.db.commit()
    
    def _sign(self, method: str, path: str) -> Dict:
        """Generate authentication headers."""
        timestamp = str(int(time.time()))
        data = method + timestamp + path
        signature = hmac.new(
            API_SECRET.encode(),
            data.encode(),
            hashlib.sha256
        ).hexdigest()
        return {
            "api-key": API_KEY,
            "timestamp": timestamp,
            "signature": signature
        }
    
    def fetch_candles(self, symbol: str, resolution: str = "5m", 
                      days: int = 90) -> List[Dict]:
        """Fetch historical candles from Delta Exchange."""
        all_candles = []
        end = int(time.time())
        
        # Resolution to minutes
        minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60}.get(resolution, 5)
        candles_per_day = (24 * 60) // minutes
        
        # Fetch in chunks (API limit is usually 500-1000 per request)
        chunk_days = 7
        chunk_candles = chunk_days * candles_per_day
        
        while days > 0:
            start = end - (min(days, chunk_days) * 24 * 60 * 60)
            
            try:
                resp = self.session.get(
                    f"{BASE_URL}/v2/history/candles",
                    params={
                        "resolution": resolution,
                        "symbol": symbol,
                        "start": start,
                        "end": end
                    },
                    timeout=30
                )
                data = resp.json()
                candles = data.get("result", [])
                
                if candles:
                    all_candles.extend(candles)
                    print(f"  Fetched {len(candles)} candles for {symbol} ({len(all_candles)} total)")
                
            except Exception as e:
                print(f"  Error fetching {symbol}: {e}")
                break
            
            days -= chunk_days
            end = start
            time.sleep(0.5)  # Rate limit
        
        return all_candles
    
    def store_candles(self, symbol: str, candles: List[Dict], resolution: str = "5m"):
        """Store candles in SQLite database."""
        for c in candles:
            try:
                self.db.execute("""
                    INSERT OR REPLACE INTO candles 
                    (symbol, timestamp, open, high, low, close, volume, resolution)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    symbol,
                    int(c.get("time", c.get("timestamp", 0))),
                    float(c.get("open", 0)),
                    float(c.get("high", 0)),
                    float(c.get("low", 0)),
                    float(c.get("close", 0)),
                    float(c.get("volume", 0)),
                    resolution
                ))
            except Exception as e:
                pass  # Skip duplicates
        
        self.db.commit()
        print(f"  Stored {len(candles)} candles for {symbol}")
    
    def get_candles(self, symbol: str, resolution: str = "5m",
                    start: int = None, end: int = None) -> pd.DataFrame:
        """Retrieve candles from database as DataFrame."""
        query = """
            SELECT timestamp, open, high, low, close, volume 
            FROM candles 
            WHERE symbol = ? AND resolution = ?
        """
        params = [symbol, resolution]
        
        if start:
            query += " AND timestamp >= ?"
            params.append(start)
        if end:
            query += " AND timestamp <= ?"
            params.append(end)
        
        query += " ORDER BY timestamp"
        
        df = pd.read_sql_query(query, self.db, params=params)
        if not df.empty:
            df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
            df.set_index('datetime', inplace=True)
        return df
    
    def collect_data(self, symbols: List[str] = None, days: int = 90):
        """Collect data for multiple symbols."""
        symbols = symbols or DEFAULT_SYMBOLS
        print(f"Collecting {days} days of data for {len(symbols)} symbols...")
        
        for symbol in symbols:
            print(f"\n📊 Fetching {symbol}...")
            candles = self.fetch_candles(symbol, "5m", days)
            if candles:
                self.store_candles(symbol, candles, "5m")
        
        print("\n✅ Data collection complete!")


# ============================================
# SIMPLE BACKTESTER (No VectorBT required)
# ============================================

class SimpleBacktester:
    """Simple backtester for strategy validation."""
    
    def __init__(self, data: pd.DataFrame, initial_capital: float = 1000):
        self.data = data
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.position = 0
        self.entry_price = 0
        self.trades = []
    
    def generate_signals(self, min_score: int = 70) -> pd.Series:
        """Generate entry signals based on V8 scoring logic (simplified)."""
        signals = pd.Series(index=self.data.index, data=0)
        
        closes = self.data['close'].values.tolist()
        
        for i in range(30, len(closes)):
            score = 0
            candles = [{"close": closes[j], "high": self.data['high'].iloc[j], 
                        "low": self.data['low'].iloc[j], "open": self.data['open'].iloc[j]}
                       for j in range(max(0, i-50), i+1)]
            
            # RSI
            rsi = calculate_rsi(candles)
            if rsi < 30:
                score += 20
            elif rsi < 40:
                score += 10
            
            # MACD
            macd_line, signal, hist = calculate_macd(candles)
            if hist > 0:
                score += 15
            
            # BB Squeeze
            bb = detect_bb_squeeze(candles)
            score += bb.get("score", 0)
            
            # Momentum
            if len(candles) >= 5:
                change = (closes[i] - closes[i-5]) / closes[i-5] * 100
                if 2 < change < 10:
                    score += 10
            
            if score >= min_score:
                signals.iloc[i] = 1
        
        return signals
    
    def backtest(self, min_score: int = 70, stop_loss: float = -5.0, 
                 take_profit: float = 10.0) -> Dict:
        """Run backtest with given parameters."""
        signals = self.generate_signals(min_score)
        
        in_position = False
        entry_price = 0
        entry_idx = 0
        
        for i in range(len(self.data)):
            price = self.data['close'].iloc[i]
            
            if not in_position:
                # Entry
                if signals.iloc[i] == 1:
                    in_position = True
                    entry_price = price * (1 + SLIPPAGE)  # Slippage on entry
                    entry_idx = i
                    self.capital -= self.capital * TAKER_FEE  # Fee
            else:
                # Exit logic
                pnl = ((price - entry_price) / entry_price) * 100 * LEVERAGE
                
                # Check stop loss
                if pnl <= stop_loss:
                    exit_price = price * (1 - SLIPPAGE)
                    actual_pnl = ((exit_price - entry_price) / entry_price) * 100 * LEVERAGE
                    self.capital *= (1 + actual_pnl / 100)
                    self.capital -= self.capital * TAKER_FEE
                    self.trades.append({
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl": actual_pnl,
                        "type": "STOP"
                    })
                    in_position = False
                
                # Check take profit
                elif pnl >= take_profit:
                    exit_price = price * (1 - SLIPPAGE)
                    actual_pnl = ((exit_price - entry_price) / entry_price) * 100 * LEVERAGE
                    self.capital *= (1 + actual_pnl / 100)
                    self.capital -= self.capital * TAKER_FEE
                    self.trades.append({
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl": actual_pnl,
                        "type": "PROFIT"
                    })
                    in_position = False
                
                # Max hold time (48 candles = 4 hours for 5m)
                elif i - entry_idx >= 48:
                    exit_price = price * (1 - SLIPPAGE)
                    actual_pnl = ((exit_price - entry_price) / entry_price) * 100 * LEVERAGE
                    self.capital *= (1 + actual_pnl / 100)
                    self.capital -= self.capital * TAKER_FEE
                    self.trades.append({
                        "entry": entry_price,
                        "exit": exit_price,
                        "pnl": actual_pnl,
                        "type": "TIMEOUT"
                    })
                    in_position = False
        
        # Calculate metrics
        wins = len([t for t in self.trades if t["pnl"] > 0])
        losses = len([t for t in self.trades if t["pnl"] <= 0])
        win_rate = wins / len(self.trades) if self.trades else 0
        
        total_return = ((self.capital - self.initial_capital) / self.initial_capital) * 100
        
        # Sharpe ratio (simplified)
        if self.trades:
            returns = [t["pnl"] for t in self.trades]
            avg_return = np.mean(returns)
            std_return = np.std(returns) if len(returns) > 1 else 1
            sharpe = (avg_return / std_return) * np.sqrt(252) if std_return > 0 else 0
        else:
            sharpe = 0
        
        return {
            "total_return": total_return,
            "win_rate": win_rate,
            "total_trades": len(self.trades),
            "wins": wins,
            "losses": losses,
            "sharpe_ratio": sharpe,
            "final_capital": self.capital,
            "avg_trade": np.mean([t["pnl"] for t in self.trades]) if self.trades else 0
        }


# ============================================
# PARAMETER OPTIMIZER
# ============================================

class ParameterOptimizer:
    """Optimize strategy parameters on historical data."""
    
    def __init__(self, data: pd.DataFrame):
        self.data = data
    
    def grid_search(self, param_grid: Dict) -> List[Tuple]:
        """
        Test all parameter combinations and return sorted results.
        
        param_grid = {
            "min_score": [60, 65, 70, 75],
            "stop_loss": [-3, -5, -7],
            "take_profit": [8, 10, 15]
        }
        """
        results = []
        total_combos = 1
        for values in param_grid.values():
            total_combos *= len(values)
        
        print(f"Testing {total_combos} parameter combinations...")
        
        tested = 0
        for min_score in param_grid.get("min_score", [70]):
            for stop_loss in param_grid.get("stop_loss", [-5]):
                for take_profit in param_grid.get("take_profit", [10]):
                    bt = SimpleBacktester(self.data.copy())
                    result = bt.backtest(min_score, stop_loss, take_profit)
                    
                    results.append({
                        "params": {
                            "min_score": min_score,
                            "stop_loss": stop_loss,
                            "take_profit": take_profit
                        },
                        **result
                    })
                    
                    tested += 1
                    if tested % 10 == 0:
                        print(f"  Tested {tested}/{total_combos}...")
        
        # Sort by Sharpe ratio
        results.sort(key=lambda x: x["sharpe_ratio"], reverse=True)
        
        return results
    
    def walk_forward(self, train_days: int = 60, test_days: int = 30) -> List[Dict]:
        """
        Walk-forward optimization to avoid overfitting.
        Train on 60 days, test on next 30 days, repeat.
        """
        results = []
        candles_per_day = 288  # 5m candles per day
        
        train_size = train_days * candles_per_day
        test_size = test_days * candles_per_day
        window_size = train_size + test_size
        
        i = 0
        while i + window_size <= len(self.data):
            train_data = self.data.iloc[i:i + train_size]
            test_data = self.data.iloc[i + train_size:i + window_size]
            
            # Optimize on train
            optimizer = ParameterOptimizer(train_data)
            train_results = optimizer.grid_search({
                "min_score": [65, 70, 75],
                "stop_loss": [-4, -5, -6],
                "take_profit": [8, 10, 12]
            })
            
            best_params = train_results[0]["params"] if train_results else {
                "min_score": 70, "stop_loss": -5, "take_profit": 10
            }
            
            # Test on out-of-sample
            bt = SimpleBacktester(test_data.copy())
            test_result = bt.backtest(**best_params)
            
            results.append({
                "period": f"{i // candles_per_day} - {(i + window_size) // candles_per_day}",
                "best_params": best_params,
                "train_sharpe": train_results[0]["sharpe_ratio"] if train_results else 0,
                "test_result": test_result
            })
            
            i += test_size  # Roll forward
        
        return results


# ============================================
# MAIN
# ============================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="V8 Backtesting Framework")
    parser.add_argument("--collect", action="store_true", help="Collect historical data")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--optimize", action="store_true", help="Optimize parameters")
    parser.add_argument("--walkforward", action="store_true", help="Walk-forward validation")
    parser.add_argument("--symbol", default="BTCUSD", help="Symbol to backtest")
    parser.add_argument("--days", type=int, default=90, help="Days of data")
    
    args = parser.parse_args()
    
    if args.collect:
        collector = DataCollector()
        collector.collect_data(DEFAULT_SYMBOLS, args.days)
    
    elif args.backtest:
        collector = DataCollector()
        data = collector.get_candles(args.symbol, "5m")
        
        if data.empty:
            print(f"No data for {args.symbol}. Run with --collect first.")
            return
        
        print(f"\n📈 Backtesting {args.symbol} with {len(data)} candles...")
        bt = SimpleBacktester(data)
        result = bt.backtest(min_score=70, stop_loss=-5, take_profit=10)
        
        print("\n" + "="*50)
        print("BACKTEST RESULTS")
        print("="*50)
        print(f"Total Return: {result['total_return']:.2f}%")
        print(f"Win Rate: {result['win_rate']:.1%}")
        print(f"Total Trades: {result['total_trades']}")
        print(f"Wins/Losses: {result['wins']}/{result['losses']}")
        print(f"Sharpe Ratio: {result['sharpe_ratio']:.2f}")
        print(f"Avg Trade: {result['avg_trade']:.2f}%")
    
    elif args.optimize:
        collector = DataCollector()
        data = collector.get_candles(args.symbol, "5m")
        
        if data.empty:
            print(f"No data for {args.symbol}. Run with --collect first.")
            return
        
        print(f"\n🔧 Optimizing parameters for {args.symbol}...")
        optimizer = ParameterOptimizer(data)
        results = optimizer.grid_search({
            "min_score": [60, 65, 70, 75, 80],
            "stop_loss": [-3, -4, -5, -6, -7],
            "take_profit": [6, 8, 10, 12, 15]
        })
        
        print("\n" + "="*50)
        print("TOP 5 PARAMETER COMBINATIONS")
        print("="*50)
        for i, r in enumerate(results[:5]):
            print(f"\n#{i+1}: {r['params']}")
            print(f"  Return: {r['total_return']:.2f}% | Win Rate: {r['win_rate']:.1%} | Sharpe: {r['sharpe_ratio']:.2f}")
    
    elif args.walkforward:
        collector = DataCollector()
        data = collector.get_candles(args.symbol, "5m")
        
        if data.empty:
            print(f"No data for {args.symbol}. Run with --collect first.")
            return
        
        print(f"\n🚶 Walk-forward validation for {args.symbol}...")
        optimizer = ParameterOptimizer(data)
        results = optimizer.walk_forward()
        
        print("\n" + "="*50)
        print("WALK-FORWARD RESULTS")
        print("="*50)
        for r in results:
            test = r["test_result"]
            print(f"\nPeriod {r['period']}:")
            print(f"  Best Params: {r['best_params']}")
            print(f"  Train Sharpe: {r['train_sharpe']:.2f}")
            print(f"  Test Return: {test['total_return']:.2f}% | Win Rate: {test['win_rate']:.1%}")
    
    else:
        print("V8 Backtesting Framework")
        print("="*40)
        print("\nUsage:")
        print("  python3 backtest_v8.py --collect         # Collect 90 days of data")
        print("  python3 backtest_v8.py --backtest        # Run backtest on BTCUSD")
        print("  python3 backtest_v8.py --optimize        # Find best parameters")
        print("  python3 backtest_v8.py --walkforward     # Walk-forward validation")
        print("\nOptions:")
        print("  --symbol XYZUSD   # Symbol to analyze")
        print("  --days 90         # Days of data to collect")


if __name__ == "__main__":
    main()

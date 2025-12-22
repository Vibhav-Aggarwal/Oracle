# Changelog

All notable changes to Oracle Bot are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [2.1.0] - 2025-12-22

### Added
- **Trend Filter**: SMA 50/200 crossover to prevent counter-trend trades
- **ATR-Based Stops**: Dynamic stop-loss and take-profit based on volatility
- **Multi-Timeframe Confirmation**: Requires 2/3 timeframes to agree before entry
- **1-Hour Blacklist**: Increased cooldown after position exit

### Changed
- Position size reduced from 20% to 2% for proper risk management
- Blacklist time increased from 3 minutes to 1 hour
- Improved signal scoring with MTF penalty for weak confirmations

### Fixed
- Multiple bot instances running simultaneously
- State file not being read correctly after restart
- Position sizing not respecting configuration

---

## [2.0.0] - 2025-12-21

### Added
- **Web Dashboard**: Real-time monitoring at trading.vibhavaggarwal.com
- **Paper/Live Mode Toggle**: Switch modes via dashboard with confirmation modal
- **Premium UI**: Modern toggle switch design with animations
- **REST API**: Endpoints for status, trades, and mode switching
- **Oracle Bot Unified**: Combined all V1-V10 features into single bot
- **Auto-Healer**: Automatic recovery from disconnections
- **Watchdog**: Process monitoring and restart capability
- **Paper Trading V2**: Enhanced simulation with realistic fees

### Changed
- Complete architectural rewrite consolidating V3-V10
- Modular design with separate indicator and sentiment modules
- Improved logging with structured output

### Technical
- Flask-based dashboard with CORS support
- Systemd service integration
- Cloudflare tunnel for remote access

**Files**: `oracle_bot.py`, `paper_trading_v2.py`

---

## [1.10.0] - 2025-12-21 (Internal V10)

### Added
- **Full WebSocket Integration**: Real-time price feeds from Delta Exchange
- **Advanced Position Management**: positions_v10.py with enhanced tracking
- **Multi-Exchange Architecture**: Support for Delta, Zebpay, Coinbase
- **Optimized Order Flow**: Reduced latency for order execution

### Changed
- Upgraded from V9 WebSocket to production-ready implementation
- Position tracking now supports multiple exchanges simultaneously

**Files**: `delta_websocket_v10.py`, `positions_v10.py`

---

## [1.9.0] - 2025-12-20 (Internal V9)

### Added
- **Squeeze Momentum Indicator**: TTM Squeeze detection
- **Position Management V9**: Improved position tracking
- **Dynamic Threshold**: Adaptive signal threshold based on market conditions
- **Indicators V9**: Enhanced technical analysis suite

### Changed
- Refined WebSocket connection handling
- Improved error recovery mechanisms
- Better rate limiting for API calls

### Fixed
- WebSocket reconnection issues
- Memory leaks in long-running sessions

**Files**: `delta_websocket_v9.py`, `positions_v9.py`, `indicators_v9.py`, `sentiment_v9.py`

---

## [1.8.0] - 2025-12-20 (Internal V8)

### Added
- **Backtesting Framework**: backtest_v8.py for strategy validation
- **Bollinger Bands**: Added to indicator suite
- **RSI Divergence Detection**: Bull/bear divergence signals
- **Volume Analysis**: Volume-weighted signals
- **Sentiment V8**: Basic news sentiment analysis
- **Indicators V8**: Expanded technical analysis

### Changed
- Significantly expanded WebSocket functionality (45KB)
- Added historical data fetching for backtests
- Improved signal scoring algorithm

**Files**: `delta_websocket_v8.py`, `backtest_v8.py`, `indicators_v8.py`, `sentiment_v8.py`

---

## [1.7.0] - 2025-12-20 (Internal V7)

### Added
- **Indicators V7**: First modular indicator implementation
  - MACD (Moving Average Convergence Divergence)
  - RSI (Relative Strength Index)
  - EMA crossovers
  - Basic signal scoring
- **WebSocket Improvements**: Enhanced connection stability

### Changed
- Separated indicators into dedicated module
- Cleaner code architecture
- Better error handling

**Files**: `delta_websocket_v7.py`, `indicators_v7.py`

---

## [1.6.0] - 2025-12-20 (Internal V6)

### Added
- **Enhanced WebSocket**: Improved real-time data handling
- **Order Book Integration**: Level 2 data processing
- **Candle Aggregation**: Multi-timeframe candle building
- **Connection Pooling**: Better resource management

### Changed
- WebSocket code expanded to 29KB
- More robust connection handling
- Improved data parsing

**Files**: `delta_websocket_v6.py`

---

## [1.5.0] - 2025-12-19 (Internal V5)

### Added
- **Streamlined WebSocket**: Optimized for performance
- **Event-Driven Architecture**: Cleaner event handling
- **Subscription Management**: Better channel management

### Changed
- Reduced complexity from V4
- Improved memory efficiency
- Cleaner codebase (19KB)

**Files**: `delta_websocket_v5.py`

---

## [1.4.0] - 2025-12-19 (Internal V4)

### Added
- **Extended Features**: V4.1 hotfix release
- **Authentication**: Proper API key authentication
- **Order Placement**: Basic order execution
- **Position Tracking**: Initial position management

### Changed
- Major expansion from V3 (23KB)
- Added trading functionality
- Improved error messages

**Files**: `delta_websocket_v4.py`, `delta_websocket_v4_1.py`

---

## [1.3.0] - 2025-12-19 (Internal V3)

### Added
- **Delta WebSocket Client**: First working WebSocket implementation
- **Real-time Price Feeds**: Live price streaming
- **Channel Subscriptions**: Subscribe to market data
- **Heartbeat Handling**: Connection keep-alive

### Technical
- Initial WebSocket architecture (16KB)
- JSON message parsing
- Basic error handling

**Files**: `delta_websocket_v3.py`

---

## [1.0.0] - 2025-12-20 (Initial Release)

### Added
- **Core Trading Engine**: Basic buy/sell logic
- **Technical Indicators**: MACD, RSI, Bollinger Bands, VWAP
- **Sentiment Analysis**: Fear & Greed Index, news sentiment
- **Position Management**: Max 5 positions, basic SL/TP
- **State Persistence**: JSON-based state file
- **Logging**: File and console output

### Known Issues (Fixed in V2)
- No trend filter (traded against market direction)
- Position size too large (20-30%)
- Fixed stops instead of ATR-based
- Short blacklist time (3 minutes)

**Files**: `oracle_bot.py` (V1 backup)

---

## Development Timeline

```
Dec 19, 2025
├── V3: First WebSocket implementation (16KB)
├── V4: Added trading functionality (23KB)
├── V4.1: Hotfix release
└── V5: Streamlined architecture (19KB)

Dec 20, 2025
├── V6: Enhanced WebSocket (29KB)
├── V7: Modular indicators introduced
├── V8: Backtesting + Bollinger + Sentiment (45KB)
├── V9: Squeeze momentum + Position mgmt
└── V1.0: First stable release

Dec 21, 2025
├── V10: Multi-exchange + Full WebSocket (37KB)
└── V2.0: Dashboard + Unified bot (58KB)

Dec 22, 2025
└── V2.1: Profitability fixes + ATR stops
```

---

## Version Summary Table

| Version | Date | Size | Key Features |
|---------|------|------|--------------|
| **2.1.0** | Dec 22 | 58KB | Trend filter, ATR stops, 2% risk |
| 2.0.0 | Dec 21 | 58KB | Dashboard, unified bot |
| 1.10 (V10) | Dec 21 | 52KB | Multi-exchange, positions |
| 1.9 (V9) | Dec 20 | 44KB | Squeeze momentum |
| 1.8 (V8) | Dec 20 | 65KB | Backtesting, Bollinger |
| 1.7 (V7) | Dec 20 | 30KB | Modular indicators |
| 1.6 (V6) | Dec 20 | 29KB | Order book, candles |
| 1.5 (V5) | Dec 19 | 19KB | Streamlined WebSocket |
| 1.4 (V4) | Dec 19 | 24KB | Trading + auth |
| 1.3 (V3) | Dec 19 | 16KB | First WebSocket |
| 1.0.0 | Dec 20 | 32KB | Initial release |

---

## Module Version Matrix

| Module | V7 | V8 | V9 | V11 |
|--------|----|----|----|----|
| Indicators | Basic MACD/RSI | Bollinger, Volume | Squeeze | 90+ indicators |
| Sentiment | - | News analysis | Rate limiting | Fear & Greed, FinBERT |
| Positions | - | - | Basic tracking | Multi-exchange |

---

## Roadmap

### Planned for V2.2.0
- [ ] Telegram alerts integration
- [ ] Portfolio rebalancing
- [ ] Backtesting framework integration
- [ ] Performance analytics dashboard

### Planned for V3.0.0
- [ ] Machine learning signal generation
- [ ] Reinforcement learning optimization
- [ ] Multi-strategy support
- [ ] Advanced risk metrics (Sharpe, Sortino)

---

## Migration Guide

### V1 to V2
1. Backup your `oracle_state.json`
2. Install new dependencies: `pip install -r requirements.txt`
3. Update configuration in `.env`
4. Start dashboard separately
5. Reset state file for fresh start

### V2.0 to V2.1
1. Stop the bot: `sudo systemctl stop oracle-bot`
2. Pull latest code: `git pull`
3. Reset state (recommended): Copy `config/oracle_state.template.json`
4. Restart: `sudo systemctl start oracle-bot`

---

## Contributors

- **Vibhav Aggarwal** - Initial development and maintenance
- **Claude (Anthropic)** - Architecture design and code review

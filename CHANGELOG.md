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
- **Multi-Exchange Support**: Delta, Zebpay, Coinbase integration
- **WebSocket Feeds**: Real-time price updates from exchanges
- **Auto-Healer**: Automatic recovery from disconnections
- **Watchdog**: Process monitoring and restart capability

### Changed
- Complete rewrite from V1 architecture
- Modular design with separate indicator and sentiment modules
- Improved logging with structured output

### Technical
- Flask-based dashboard with CORS support
- Systemd service integration
- Cloudflare tunnel for remote access

---

## [1.0.0] - 2025-12-20

### Added
- **Core Trading Engine**: Basic buy/sell logic
- **Technical Indicators** (V7-V9):
  - MACD (Moving Average Convergence Divergence)
  - RSI (Relative Strength Index)
  - Bollinger Bands
  - VWAP (Volume Weighted Average Price)
  - Squeeze Momentum
  - Stochastic Oscillator
- **Sentiment Analysis** (V8-V9):
  - Fear & Greed Index integration
  - News sentiment scoring
  - CryptoPanic API integration
- **Position Management**:
  - Maximum 5 concurrent positions
  - Basic stop-loss and take-profit
  - Position sizing based on balance
- **State Persistence**: JSON-based state file
- **Logging**: File and console output

### Known Issues (Fixed in V2)
- No trend filter (traded against market direction)
- Position size too large (20-30%)
- Fixed stops instead of ATR-based
- Short blacklist time (3 minutes)

---

## Version History Summary

| Version | Date | Key Features |
|---------|------|--------------|
| 2.1.0 | 2025-12-22 | Profitability fixes, trend filter, ATR stops |
| 2.0.0 | 2025-12-21 | Dashboard, multi-exchange, auto-healer |
| 1.0.0 | 2025-12-20 | Initial release, basic trading |

---

## Indicator Module Versions

### indicators_v11.py (Current)
- 90+ technical indicators
- Multi-timeframe support
- ATR calculation with percentage output
- Optimized for performance

### indicators_v9.py
- Added Squeeze Momentum
- VWAP improvements
- Bug fixes

### indicators_v8.py
- Bollinger Bands integration
- RSI divergence detection
- Volume analysis

### indicators_v7.py
- Basic MACD, RSI
- Initial implementation

---

## Sentiment Module Versions

### sentiment_v11.py (Current)
- Combined sentiment scoring
- Fear & Greed Index
- News sentiment via FinBERT
- CryptoPanic integration

### sentiment_v9.py
- Improved scoring algorithm
- Rate limiting

### sentiment_v8.py
- Initial sentiment implementation
- Basic news analysis

---

## Roadmap

### Planned for V2.2.0
- [ ] Telegram alerts integration
- [ ] Portfolio rebalancing
- [ ] Backtesting framework
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

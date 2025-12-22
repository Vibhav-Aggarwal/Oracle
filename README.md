# Oracle Bot V2

> **Advanced Multi-Exchange Cryptocurrency Trading System**

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Status: Active](https://img.shields.io/badge/Status-Active-green.svg)]()

Oracle Bot is a sophisticated algorithmic trading system designed for cryptocurrency markets. It supports multiple exchanges, implements advanced technical analysis, and features a real-time web dashboard for monitoring and control.

## Features

### Trading Engine
- **Multi-Exchange Support**: Delta Exchange, Zebpay, Coinbase
- **Paper & Live Trading Modes**: Safe testing environment before going live
- **Position Management**: Up to 5 concurrent positions with automatic sizing
- **Risk Management**: ATR-based dynamic stop-loss and take-profit levels

### Technical Analysis
- **90+ Technical Indicators**: MACD, RSI, Bollinger Bands, VWAP, Squeeze Momentum, and more
- **Multi-Timeframe Analysis**: 5m, 15m, 1h confirmation for high-probability entries
- **Trend Filtering**: SMA 50/200 crossover to avoid counter-trend trades
- **Sentiment Integration**: Fear & Greed Index, news sentiment analysis

### Risk Controls
- **Position Sizing**: Configurable risk per trade (default 2%)
- **Trailing Stops**: Dynamic trailing with ATR-based distance
- **Drawdown Protection**: Daily loss limits and consecutive loss handling
- **Coin Blacklisting**: Automatic cooldown after exits

### Dashboard
- **Real-time Monitoring**: Live P&L, positions, and trade history
- **Mode Switching**: Toggle between Paper and Live with confirmation
- **Performance Metrics**: Win rate, average win/loss, total fees

## Architecture

```
Oracle/
├── src/
│   ├── oracle_bot.py          # Main trading engine
│   ├── oracle_trader.py       # Trade execution logic
│   ├── oracle_autohealer.py   # Auto-recovery and healing
│   └── oracle_watchdog.py     # Process monitoring
├── dashboard/
│   ├── app.py                 # Flask web application
│   ├── static/
│   │   ├── css/style.css      # Dashboard styling
│   │   └── js/dashboard.js    # Real-time updates
│   └── templates/
│       └── index.html         # Dashboard UI
├── config/
│   ├── oracle_weights.json    # Indicator weights
│   └── config.example.env     # Environment template
├── docs/
│   ├── SETUP.md               # Installation guide
│   ├── CONFIGURATION.md       # Config reference
│   └── API.md                 # API documentation
└── requirements.txt           # Python dependencies
```

## Quick Start

### Prerequisites
- Python 3.8 or higher
- Redis (optional, for caching)
- Exchange API keys (Delta, Zebpay, or Coinbase)

### Installation

```bash
# Clone the repository
git clone https://github.com/Vibhav-Aggarwal/Oracle.git
cd Oracle

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp config/config.example.env .env
# Edit .env with your API keys
```

### Configuration

Edit the configuration in `src/oracle_bot.py` or use environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `PAPER` | Trading mode (PAPER/LIVE) |
| `PAPER_INITIAL_BALANCE` | `1000.0` | Starting balance for paper trading |
| `MAX_POSITIONS` | `5` | Maximum concurrent positions |
| `BASE_POSITION_SIZE_PCT` | `0.02` | Risk per trade (2%) |
| `LEVERAGE` | `20` | Default leverage |
| `MIN_SCORE_THRESHOLD` | `40` | Minimum signal score to enter |
| `COIN_BLACKLIST_TIME` | `3600` | Cooldown after exit (seconds) |

### Running the Bot

```bash
# Start the trading bot
python src/oracle_bot.py

# Start the dashboard (separate terminal)
cd dashboard
python app.py
```

Access the dashboard at `http://localhost:5000`

## Signal Generation

Oracle Bot uses a weighted scoring system to generate trading signals:

### Entry Conditions
1. **Technical Score >= 40**: Combination of multiple indicators
2. **Trend Alignment**: Price above SMA200 for longs, below for shorts
3. **Multi-Timeframe Confirmation**: At least 2/3 timeframes agree
4. **Volatility Check**: ATR within acceptable range

### Exit Conditions
1. **Take Profit Hit**: ATR-based dynamic target (3x ATR)
2. **Stop Loss Hit**: ATR-based stop (2x ATR)
3. **Trailing Stop**: Activated at +3% profit
4. **Emergency Exit**: -3% loss protection

## Risk Management

### Position Sizing
```python
position_size = account_balance * BASE_POSITION_SIZE_PCT * leverage_factor
```

Where `leverage_factor` adjusts based on:
- Volatility (lower size in high volatility)
- Win streak (slight increase after wins)
- Drawdown (reduce size during drawdowns)

### Stop Loss Calculation
```python
atr = calculate_atr(candles, period=14)
stop_loss = entry_price * (1 - (atr * ATR_SL_MULTIPLIER / 100))
```

## Dashboard

The web dashboard provides real-time visibility into bot operations:

### Features
- **Balance & P&L Display**: Current balance and profit/loss
- **Position Monitor**: Open positions with entry, P&L, and progress bars
- **Trade History**: Recent trades with outcomes
- **Mode Toggle**: Switch between Paper and Live trading

### API Endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Bot status and positions |
| `/api/trades` | GET | Trade history |
| `/api/mode` | POST | Switch trading mode |

## Exchanges Supported

### Delta Exchange
- **Type**: Derivatives (Futures)
- **Leverage**: Up to 100x
- **Fees**: 0.02% maker, 0.05% taker + 18% GST

### Zebpay
- **Type**: Spot
- **Fees**: 0.15% maker, 0.25% taker + 18% GST + 1% TDS

### Coinbase
- **Type**: Spot
- **Fees**: 0.4% maker, 0.6% taker

## Monitoring & Alerts

### Watchdog
The `oracle_watchdog.py` script monitors the bot and restarts it if:
- Process crashes
- Memory usage exceeds threshold
- No activity for extended period

### Auto-Healer
The `oracle_autohealer.py` handles:
- WebSocket reconnection
- API rate limit recovery
- State file corruption repair

## Testing

```bash
# Run in paper mode first
python src/oracle_bot.py  # Defaults to PAPER mode

# Monitor via dashboard
# Check /tmp/oracle_bot.log for detailed logs

# After validation, switch to live via dashboard
```

## Performance Metrics

Track these metrics to evaluate bot performance:

| Metric | Target | Description |
|--------|--------|-------------|
| Win Rate | >40% | Percentage of winning trades |
| Risk/Reward | >1.5 | Average win vs average loss |
| Max Drawdown | <15% | Maximum peak-to-trough decline |
| Sharpe Ratio | >1.0 | Risk-adjusted returns |

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Disclaimer

**IMPORTANT**: This software is for educational purposes only. Cryptocurrency trading involves substantial risk of loss. Past performance does not guarantee future results. Always:

- Test thoroughly in paper mode before live trading
- Never trade with money you cannot afford to lose
- Understand the risks involved in leveraged trading
- Monitor the bot regularly

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

**Vibhav Aggarwal**
- GitHub: [@Vibhav-Aggarwal](https://github.com/Vibhav-Aggarwal)

---

*Built with discipline. Trade with caution.*

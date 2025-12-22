# Oracle Bot - Complete Version Archive

This folder contains all versions of the Oracle Bot trading system from initial development (V3) to the current release (V2.1).

## Version Evolution

```
V3 ──► V4 ──► V5 ──► V6 ──► V7 ──► V8 ──► V9 ──► V10 ──► V1.0 ──► V2.0 ──► V2.1
│      │      │      │      │      │      │       │        │        │        │
WebSocket  Trading  Opt   Order   Ind   Back    Squeeze  Multi   Stable   Dash   Profit
           Auth          Book   Module  test    Moment   Exch   Release  board   Fixes
```

---

## Directory Structure

```
versions/
├── v1/                          # Initial Stable Release (Dec 20)
│   └── oracle_bot.py            # 32KB - First production bot
│
├── v2/                          # Dashboard Integration (Dec 21)
│   ├── oracle_bot.py            # 58KB - Unified bot with all features
│   └── paper_trading_v2.py      # Paper trading simulation
│
├── v3/                          # First WebSocket (Dec 19)
│   └── delta_websocket_v3.py    # 16KB - Initial WebSocket client
│
├── v4/                          # Trading Functionality (Dec 19)
│   ├── delta_websocket_v4.py    # 23KB - Added authentication
│   └── delta_websocket_v4_1.py  # Hotfix release
│
├── v5/                          # Streamlined (Dec 19)
│   └── delta_websocket_v5.py    # 19KB - Optimized architecture
│
├── v6/                          # Order Book (Dec 20)
│   └── delta_websocket_v6.py    # 29KB - Level 2 data support
│
├── v7/                          # Modular Indicators (Dec 20)
│   └── delta_websocket_v7.py    # 29KB - First indicator module
│
├── v8/                          # Backtesting (Dec 20)
│   ├── delta_websocket_v8.py    # 45KB - Major expansion
│   └── backtest_v8.py           # 20KB - Strategy testing
│
├── v9/                          # Squeeze Momentum (Dec 20)
│   ├── delta_websocket_v9.py    # 29KB - TTM Squeeze
│   └── positions_v9.py          # 14KB - Position tracking
│
└── v10/                         # Multi-Exchange (Dec 21)
    ├── delta_websocket_v10.py   # 37KB - Production WebSocket
    └── positions_v10.py         # 14KB - Enhanced positions
```

---

## Version Details

### V3 - First WebSocket (Dec 19, 2025)
**File**: `delta_websocket_v3.py` (16KB)

The beginning - first working WebSocket connection to Delta Exchange.

**Features**:
- WebSocket client initialization
- Real-time price feed subscription
- Basic message handling
- Connection heartbeat

---

### V4 - Trading Functionality (Dec 19, 2025)
**Files**: `delta_websocket_v4.py`, `delta_websocket_v4_1.py` (24KB)

Added actual trading capabilities.

**Features**:
- API key authentication
- Order placement (market/limit)
- Position tracking basics
- Error handling improvements
- V4.1 hotfix for authentication issues

---

### V5 - Streamlined Architecture (Dec 19, 2025)
**File**: `delta_websocket_v5.py` (19KB)

Cleaned up V4 code, reduced complexity.

**Features**:
- Event-driven design
- Better subscription management
- Memory optimization
- Cleaner codebase

---

### V6 - Order Book Integration (Dec 20, 2025)
**File**: `delta_websocket_v6.py` (29KB)

Added market depth capabilities.

**Features**:
- Level 2 order book data
- Candle aggregation
- Multi-timeframe support
- Connection pooling

---

### V7 - Modular Indicators (Dec 20, 2025)
**File**: `delta_websocket_v7.py` (29KB)

First version with separate indicator module.

**Features**:
- MACD indicator
- RSI indicator
- EMA crossovers
- Signal scoring system
- Separated `indicators_v7.py` module

---

### V8 - Backtesting & Bollinger (Dec 20, 2025)
**Files**: `delta_websocket_v8.py` (45KB), `backtest_v8.py` (20KB)

Largest single version - added backtesting framework.

**Features**:
- Bollinger Bands
- RSI divergence detection
- Volume analysis
- Historical data fetching
- Strategy backtesting
- Performance metrics
- Sentiment analysis (sentiment_v8.py)

---

### V9 - Squeeze Momentum (Dec 20, 2025)
**Files**: `delta_websocket_v9.py` (29KB), `positions_v9.py` (14KB)

Added TTM Squeeze indicator.

**Features**:
- Squeeze Momentum (TTM Squeeze)
- Dynamic signal thresholds
- Position management module
- Rate limiting
- WebSocket reconnection fixes

---

### V10 - Multi-Exchange (Dec 21, 2025)
**Files**: `delta_websocket_v10.py` (37KB), `positions_v10.py` (14KB)

Production-ready WebSocket with multi-exchange support.

**Features**:
- Delta Exchange integration
- Zebpay support
- Coinbase support
- Advanced position tracking
- Optimized order flow
- Low-latency execution

---

### V1.0 - Initial Stable Release (Dec 20, 2025)
**File**: `oracle_bot.py` (32KB)

First stable production release combining V3-V10 learnings.

**Features**:
- Complete trading engine
- All technical indicators
- Sentiment analysis
- Position management
- State persistence
- Logging system

**Known Issues** (fixed in V2):
- No trend filtering
- Large position sizes (20%)
- Fixed stop-loss values
- Short cooldown periods

---

### V2.0 - Dashboard Integration (Dec 21, 2025)
**Files**: `oracle_bot.py` (58KB), `paper_trading_v2.py` (16KB)

Major release with web dashboard.

**Features**:
- Web-based monitoring dashboard
- Paper/Live mode toggle
- REST API endpoints
- Auto-healer for recovery
- Watchdog for monitoring
- Enhanced paper trading
- All 90+ indicators from V1-V10

---

### V2.1 - Profitability Fixes (Dec 22, 2025)
**Current Release**

Focused on improving trading profitability.

**Features**:
- SMA 50/200 trend filter
- ATR-based dynamic stops
- Multi-timeframe confirmation
- 2% position sizing
- 1-hour blacklist cooldown

---

## Code Size Evolution

```
V3:  ████████ 16KB
V4:  ████████████ 24KB
V5:  ██████████ 19KB
V6:  ██████████████ 29KB
V7:  ██████████████ 29KB
V8:  ██████████████████████ 45KB (+ 20KB backtest)
V9:  ██████████████ 29KB (+ 14KB positions)
V10: ██████████████████ 37KB (+ 14KB positions)
V1:  ████████████████ 32KB
V2:  █████████████████████████████ 58KB (+ 16KB paper)
```

---

## Using Archived Versions

### For Reference Only
These versions are provided for:
- Understanding development evolution
- Code review and learning
- Debugging historical issues
- Documentation purposes

### Not Recommended for Production
Old versions contain known issues fixed in newer releases. Always use the latest version (`src/oracle_bot.py`) for production.

### Running Old Version (Not Recommended)
```bash
# Backup current
cp src/oracle_bot.py src/oracle_bot.py.backup

# Copy old version
cp versions/vX/delta_websocket_vX.py src/oracle_bot.py

# Note: Old versions may have missing dependencies or imports
```

---

## Key Learnings from Development

1. **V3-V5**: WebSocket stability is crucial - proper heartbeat and reconnection
2. **V6-V7**: Modular design improves maintainability
3. **V8**: Backtesting before live trading saves money
4. **V9**: Squeeze momentum provides high-quality signals
5. **V10**: Multi-exchange reduces dependency risk
6. **V2.0**: Dashboard provides essential visibility
7. **V2.1**: Trend following beats counter-trend trading

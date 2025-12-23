# Oracle Bot Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ORACLE BOT V2 ARCHITECTURE                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                   │
│  │   Delta API  │    │  Zebpay API  │    │ Coinbase API │                   │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                   │
│         │                   │                   │                           │
│         └───────────────────┼───────────────────┘                           │
│                             │                                               │
│                    ┌────────▼────────┐                                      │
│                    │ Exchange Layer  │◄──── Abstract Exchange Interface     │
│                    │  (ABC Pattern)  │                                      │
│                    └────────┬────────┘                                      │
│                             │                                               │
│         ┌───────────────────┼───────────────────┐                           │
│         │                   │                   │                           │
│  ┌──────▼──────┐    ┌───────▼───────┐   ┌──────▼──────┐                    │
│  │  WebSocket  │    │ Ticker Cache  │   │  REST API   │                    │
│  │  (Real-time)│    │  (0.5s TTL)   │   │  (Fallback) │                    │
│  └──────┬──────┘    └───────┬───────┘   └──────┬──────┘                    │
│         │                   │                   │                           │
│         └───────────────────┼───────────────────┘                           │
│                             │                                               │
│                    ┌────────▼────────┐                                      │
│                    │   OracleBot     │◄──── Main Trading Engine             │
│                    │   Controller    │                                      │
│                    └────────┬────────┘                                      │
│                             │                                               │
│    ┌────────────────────────┼────────────────────────┐                      │
│    │                        │                        │                      │
│ ┌──▼───────┐  ┌─────────────▼─────────────┐  ┌──────▼──────┐               │
│ │ Signals  │  │    Risk Management        │  │  Position   │               │
│ │ Engine   │  │ • Position Sizing         │  │  Manager    │               │
│ │          │  │ • ATR-Based Stops         │  │             │               │
│ │ • MTF    │  │ • Drawdown Limits         │  │ • Open      │               │
│ │ • Trend  │  │ • Consecutive Loss Check  │  │ • Monitor   │               │
│ │ • PPO    │  │ • Blacklist/Cooldown      │  │ • Close     │               │
│ │ • Sent.  │  └───────────────────────────┘  └─────────────┘               │
│ └──────────┘                                                                │
│                             │                                               │
│                    ┌────────▼────────┐                                      │
│                    │ State Persist.  │◄──── JSON File Storage               │
│                    │ (oracle_state)  │                                      │
│                    └────────┬────────┘                                      │
│                             │                                               │
│    ┌────────────────────────┼────────────────────────┐                      │
│    │                        │                        │                      │
│ ┌──▼───────┐      ┌─────────▼─────────┐      ┌──────▼──────┐               │
│ │ Metrics  │      │   Telegram        │      │  Dashboard  │               │
│ │ Module   │      │   Alerts          │      │  (Flask)    │               │
│ └──────────┘      └───────────────────┘      └─────────────┘               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Details

### 1. Exchange Layer (Abstract Factory Pattern)

```python
class Exchange(ABC):
    @abstractmethod
    def get_ticker(symbol: str) -> dict
    @abstractmethod
    def get_candles(symbol: str, resolution: str, limit: int) -> List[dict]
    @abstractmethod
    def place_order(symbol: str, side: str, size: float) -> dict
```

**Implementations:**
- `DeltaExchange` - Primary futures exchange
- `ZebpayExchange` - Indian spot exchange
- `CoinbaseExchange` - US spot exchange

### 2. Signal Generation

```
┌─────────────────────────────────────────────────┐
│              SIGNAL SCORING SYSTEM              │
├─────────────────────────────────────────────────┤
│                                                 │
│  Technical Indicators (indicators_v11.py)       │
│  ├── RSI (14)           → ±10 points           │
│  ├── MACD Cross         → ±15 points           │
│  ├── Bollinger Bands    → ±10 points           │
│  ├── Volume Analysis    → ±5 points            │
│  └── Order Flow         → ±10 points           │
│                                                 │
│  Trend Filter (SMA 50/200)                      │
│  ├── SMA50 > SMA200     → Allow LONG only      │
│  └── SMA50 < SMA200     → Allow SHORT only     │
│                                                 │
│  Multi-Timeframe Confirmation                   │
│  ├── 5m agrees          → +5 points            │
│  ├── 15m agrees         → +5 points            │
│  └── <2 agree           → -20 penalty          │
│                                                 │
│  Sentiment (sentiment_v11.py)                   │
│  ├── Fear & Greed       → ±10 points           │
│  └── Social Sentiment   → ±5 points            │
│                                                 │
│  PPO Model (External)                           │
│  └── AI Recommendation  → ±15 points           │
│                                                 │
│  ═══════════════════════════════════════════   │
│  THRESHOLD: 55 (adaptive: 50-65)               │
│  Score ≥ +55  → LONG signal                    │
│  Score ≤ -55  → SHORT signal                   │
└─────────────────────────────────────────────────┘
```

### 3. Risk Management

| Parameter | Value | Purpose |
|-----------|-------|---------|
| `BASE_POSITION_SIZE_PCT` | 2% | Base risk per trade |
| `LEVERAGE` | 5x | Position leverage |
| `ATR_SL_MULTIPLIER` | 3.0 | Stop loss = 3 × ATR |
| `ATR_TP_MULTIPLIER` | 4.5 | Take profit = 4.5 × ATR |
| `MAX_POSITIONS` | 5 | Maximum concurrent positions |
| `MAX_CONSECUTIVE_LOSSES` | 3 | Trading pause trigger |
| `DAILY_DRAWDOWN_LIMIT` | 10% | Daily loss limit |
| `COIN_BLACKLIST_TIME` | 1 hour | Cooldown after exit |

### 4. Position Lifecycle

```
┌───────────┐     ┌───────────┐     ┌───────────┐     ┌───────────┐
│  Signal   │────▶│  Validate │────▶│   Open    │────▶│  Monitor  │
│ Generated │     │   Risk    │     │ Position  │     │           │
└───────────┘     └───────────┘     └───────────┘     └─────┬─────┘
                                                            │
                       ┌────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┬─────────────┐
         ▼             ▼             ▼             ▼
    ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐
    │STOP_LOSS│  │TAKE_PRO.│  │TRAILING │  │IMMEDIATE│
    │  Hit    │  │  Hit    │  │  Stop   │  │  Loss   │
    └────┬────┘  └────┬────┘  └────┬────┘  └────┬────┘
         │            │            │            │
         └────────────┴────────────┴────────────┘
                       │
                       ▼
                 ┌───────────┐
                 │   Close   │
                 │ Position  │
                 └─────┬─────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
    ┌───────────┐            ┌───────────┐
    │  Update   │            │  Apply    │
    │  Metrics  │            │ Blacklist │
    └───────────┘            └───────────┘
```

### 5. Data Flow

```
Market Data ──▶ Ticker Cache (0.5s) ──▶ Signal Engine
     │                                       │
     │                                       ▼
     │                               Score Calculation
     │                                       │
     ▼                                       ▼
Candle Cache (60s) ──────────────▶ Risk Validation
                                            │
                                            ▼
                                   Position Opened
                                            │
                                            ▼
                                   State Persisted
                                            │
                              ┌─────────────┴─────────────┐
                              ▼                           ▼
                        Metrics Updated            Alert Sent
```

## File Structure

```
Oracle/
├── src/
│   ├── oracle_bot.py        # Main trading engine
│   ├── oracle_metrics.py    # Performance tracking
│   ├── oracle_alerts.py     # Notification system
│   ├── indicators_v11.py    # Technical indicators
│   └── sentiment_v11.py     # Sentiment analysis
├── dashboard/
│   ├── app.py              # Flask web dashboard
│   └── templates/          # HTML templates
├── tests/
│   └── test_oracle_bot.py  # Unit tests
├── config/
│   └── exchanges.json      # Exchange configurations
├── docs/
│   ├── ARCHITECTURE.md     # This document
│   ├── API.md              # API documentation
│   └── SETUP.md            # Setup guide
└── .github/
    └── workflows/
        └── ci.yml          # CI/CD pipeline
```

## Key Design Decisions

### 1. Abstract Exchange Pattern
- Allows easy addition of new exchanges
- Consistent interface across all exchanges
- Testable with mock implementations

### 2. Multi-Layer Caching
- WebSocket for real-time data (Delta only)
- In-memory cache with TTL for REST data
- Reduces API calls and improves latency

### 3. State Persistence
- JSON file for simplicity and debuggability
- Atomic writes to prevent corruption
- Automatic recovery on restart

### 4. Defensive Trading
- Multiple confirmation layers (MTF, trend, score)
- Conservative position sizing (1-5%)
- Automatic trading pause on consecutive losses

### 5. Observability
- Structured logging with levels
- Metrics module for performance tracking
- Telegram alerts for critical events

## Performance Characteristics

| Metric | Value |
|--------|-------|
| Scan interval | 100ms |
| Ticker cache TTL | 500ms |
| Candle cache TTL | 60s |
| Max symbols scanned | ~1700/cycle |
| Memory footprint | ~50-100MB |
| CPU usage (idle) | <5% |

## Security Considerations

1. **API Keys**: Stored in environment variables
2. **Telegram Tokens**: Not committed to repo
3. **State Files**: Local only, not synced
4. **Live Mode**: Requires explicit confirmation
5. **Error Handling**: No secrets logged

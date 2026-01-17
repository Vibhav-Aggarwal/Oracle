# Project Oracle - AI Development Guide

**Cryptocurrency Algorithmic Trading System**

This file helps Claude Code understand the project structure, conventions, and workflows for efficient development.

---

## 🎯 Project Overview

**Purpose:** Production cryptocurrency trading engine with automated strategies
**Tech Stack:** Python 3.x, Docker, Delta Exchange API
**Status:** Active - PRODUCTION SYSTEM ⚠️
**Priority:** HIGH - Real funds involved
**Version:** 2.0.0

---

## ⚠️ CRITICAL WARNINGS

1. **PRODUCTION SYSTEM** - Real money at risk
2. **Test thoroughly** before deploying any changes
3. **Understand risk management** before modifying strategies
4. **Monitor after deployment** - Check logs immediately
5. **Have rollback plan** ready for all changes
6. **Document all changes** in commit messages

---

## 📁 Project Structure

```
oracle/
├── src/
│   ├── main.py            # Main trading engine
│   ├── strategy.py        # Trading strategies
│   ├── risk_manager.py    # Position & risk management
│   ├── exchange.py        # Delta Exchange client
│   ├── config.py          # Configuration loading
│   ├── logger.py          # Logging system
│   └── metrics.py         # Performance metrics
├── config/
│   ├── prometheus.yml     # Monitoring config
│   └── grafana-datasources.yml
├── tests/                 # Unit tests
├── data/                  # Historical data
├── logs/                  # Log files
├── .env                   # Environment variables (SECRET!)
├── .env.example           # Template
├── docker-compose.yml     # Container orchestration
├── Dockerfile             # Python app container
├── requirements.txt       # Python dependencies
└── CLAUDE.md             # This file
```

---

## 🔧 Development Environment

### Local Setup
```bash
cd ~/Projects/oracle

# Check environment
cat .env.example

# Install dependencies
pip install -r requirements.txt

# Test run (DRY MODE)
python src/main.py  # Make sure to use test keys!
```

### Server Deployment
- **Location:** lab-server:/home/vibhavaggarwal/oracle-trading-system
- **Service:** Docker Compose
- **Monitoring:** Prometheus + Grafana
- **Status:** `docker-compose ps`

---

## 🚀 Workflow for Claude Code

### Making Changes - CAREFUL PROCESS

```bash
# 1. Navigate to project
cd ~/Projects/oracle

# 2. Read relevant code
cat src/strategy.py  # or whichever file

# 3. Understand the logic
# - Risk management rules
# - Position sizing
# - Entry/exit conditions

# 4. Make changes using Edit tool
# - Preserve safety checks
# - Don't remove risk limits
# - Maintain error handling

# 5. Test locally with dry-run mode
python src/main.py  # Use test API keys

# 6. Review changes carefully
git diff

# 7. Commit with detailed message
git add .
git commit -m "feat: detailed description of what changed"

# 8. Deploy with monitoring
~/Projects/.meta/deploy.sh deploy oracle

# 9. CRITICAL: Monitor logs immediately
ssh lab-server "cd oracle-trading-system && docker-compose logs -f"

# 10. Watch for 10-15 minutes
# - Check for errors
# - Verify trades execute correctly
# - Monitor P&L
```

---

## 📊 Core Components

### main.py - Trading Engine
**Purpose:** Main event loop, signal processing, trade execution

**Key Classes:**
- `OracleTradingEngine` - Main engine
  - `initialize()` - Setup exchange, strategy, risk manager
  - `_main_loop()` - Continuous trading loop
  - `_process_signal()` - Handle trading signals
  - `_execute_entry()` - Open positions
  - `_execute_exit()` - Close positions

### strategy.py - Trading Logic
**Purpose:** Generate buy/sell signals

**Key Classes:**
- `OracleStrategy` - Signal generation
  - `generate_signal()` - Analyze market, return signal
  - `calculate_position_size()` - Size determination
  - `get_stop_loss_price()` - SL calculation
  - `get_take_profit_price()` - TP calculation

**Signals:**
- `LONG` - Open long position
- `SHORT` - Open short position
- `EXIT_LONG` - Close long
- `EXIT_SHORT` - Close short
- `HOLD` - No action

### risk_manager.py - Risk Controls
**Purpose:** Protect capital, enforce limits

**Key Classes:**
- `RiskManager` - Risk enforcement
  - `check_trade_allowed()` - Pre-trade validation
  - `register_position()` - Track open positions
  - `close_position()` - Position closing logic
  - `update_equity()` - Balance tracking

**Actions:**
- `ALLOW` - Trade permitted
- `REDUCE_SIZE` - Trade with smaller size
- `BLOCK` - Trade rejected
- `CLOSE_ALL` - Emergency stop

### exchange.py - API Client
**Purpose:** Delta Exchange integration

**Key Methods:**
- `place_order()` - Execute trades
- `get_balances()` - Account balance
- `get_position()` - Current positions
- `cancel_order()` - Order cancellation

---

## 🔍 Code Patterns

### Signal Generation
```python
sig = self.strategy.generate_signal(symbol, current_side)
if sig.signal == Signal.LONG:
    self._execute_entry(sig)
```

### Risk Check
```python
action, reason = self.risk_manager.check_trade_allowed(
    symbol, size, side
)
if action == RiskAction.BLOCK:
    logger.info(f"Trade blocked: {reason}")
    return
```

### Error Handling
```python
try:
    order = self.exchange.place_order(...)
except Exception as e:
    logger.exception(f"Order failed: {e}")
```

---

## 🧪 Testing

### Unit Tests
```bash
cd ~/Projects/oracle
python -m pytest tests/
```

### Manual Testing (Dry Run)
```bash
# Use test API keys in .env
TEST_MODE=true python src/main.py
```

### Production Testing
```bash
# Check running system
ssh lab-server "cd oracle-trading-system && docker-compose ps"

# View logs
ssh lab-server "cd oracle-trading-system && docker-compose logs --tail=100"
```

---

## 🚨 Common Issues

### Issue: Order Placement Failed
**Check:**
1. API credentials valid?
2. Sufficient balance?
3. Market open?
4. Position limits reached?

### Issue: Risk Manager Blocking Trades
**Check:**
1. Daily loss limit hit?
2. Max positions reached?
3. Position size too large?

### Issue: Docker Container Crash
**Solution:**
```bash
ssh lab-server "cd oracle-trading-system && docker-compose restart"
```

---

## 📝 Code Standards

### Commit Messages
- `feat:` - New strategy or feature
- `fix:` - Bug fix (critical for production)
- `perf:` - Performance optimization
- `refactor:` - Code cleanup (no logic change)
- `risk:` - Risk management change (extra careful!)

### Code Style
- Type hints for all functions
- Comprehensive error handling
- Logging at all critical points
- Risk checks before trades
- Clear variable names
- Comments for complex logic

---

## 🎯 Strategy Development Guidelines

### Adding New Strategy
1. **Research thoroughly** - Backtest extensively
2. **Start with paper trading** - No real money
3. **Small position sizes** - Test in production
4. **Monitor closely** - Watch first 24 hours
5. **Gradual scaling** - Increase size slowly

### Modifying Existing Strategy
1. **Understand current logic** - Read all code
2. **Document changes** - Why and what
3. **Preserve safety** - Don't remove limits
4. **A/B test** - Compare old vs new
5. **Rollback ready** - Keep old version

---

## 🔗 Dependencies

### Python Packages
```
requests          # HTTP client
python-dotenv     # Environment variables
dataclasses       # Data structures
```

### External Services
- Delta Exchange API
- Prometheus (monitoring)
- Grafana (visualization)

---

## 💰 Risk Management Rules

### Position Limits
- Max positions: 3 simultaneous
- Max position size: Calculated by strategy
- Daily loss limit: Configured in risk manager

### Stop Loss
- Always set on entry
- Cannot be removed
- Adjusted based on volatility

### Emergency Procedures
1. **Immediate stop:** Close all positions
2. **Investigation:** Check logs, analyze
3. **Fix:** Identify and resolve issue
4. **Gradual restart:** Monitor closely

---

## 🤖 Claude Code Optimization Tips

1. **NEVER remove risk checks** - They protect capital
2. **Test everything** - Trading code needs 100% testing
3. **Understand before changing** - Read entire flow
4. **Document assumptions** - Help future debugging
5. **Monitor after deploy** - Stay alert for issues
6. **Keep commits atomic** - One logical change per commit
7. **Preserve logging** - Essential for debugging
8. **Respect money** - Real funds at risk

---

## 📞 Quick Commands

```bash
# Start development
cd ~/Projects/oracle

# Run locally (test mode)
python src/main.py

# Deploy
~/Projects/.meta/deploy.sh deploy oracle

# Check production status
ssh lab-server "cd oracle-trading-system && docker-compose ps"

# View logs
ssh lab-server "cd oracle-trading-system && docker-compose logs -f"

# Restart (if needed)
ssh lab-server "cd oracle-trading-system && docker-compose restart"

# Emergency stop
ssh lab-server "cd oracle-trading-system && docker-compose down"
```

---

## 🔧 Useful Snippets

### Check Current Positions
```bash
ssh lab-server "cd oracle-trading-system && docker-compose logs | grep 'Opened\|Closed'"
```

### View P&L
```bash
ssh lab-server "cd oracle-trading-system && docker-compose logs | grep PnL"
```

### Monitor Health
```bash
ssh lab-server "cd oracle-trading-system && docker-compose logs | grep healthy"
```

---

## 📊 Production Checklist

Before deploying changes:
- [ ] Code reviewed and tested locally
- [ ] Unit tests pass
- [ ] Risk management unchanged or improved
- [ ] Logging added for new code
- [ ] Error handling present
- [ ] Commit message is clear
- [ ] Rollback plan ready
- [ ] Ready to monitor logs

After deployment:
- [ ] Check logs for errors
- [ ] Verify trades execute correctly
- [ ] Monitor P&L
- [ ] Watch for 15-30 minutes
- [ ] Document any issues

---

**Last Updated:** 2026-01-17
**Maintained by:** Claude Code
**Status:** 🔴 PRODUCTION - Handle with extreme care

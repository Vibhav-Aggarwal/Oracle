# Oracle Bot - Version History

This folder contains archived versions of the Oracle Bot trading engine.

## Versions

### v1/ - Initial Release (2025-12-20)
- Basic trading engine
- Simple technical indicators
- Fixed stop-loss/take-profit
- Single exchange support

**Files:**
- `oracle_bot.py` - Main trading bot (32KB)

**Limitations:**
- No trend filtering
- Large position sizes (20%)
- Short cooldown periods
- No dashboard

---

### v2/ - Complete Rewrite (2025-12-21)
- Multi-exchange support
- Web dashboard integration
- Auto-healer and watchdog
- 90+ technical indicators

**Files:**
- `oracle_bot.py` - Enhanced trading bot (58KB)

**Improvements over V1:**
- ATR-based dynamic stops
- Trend filter (SMA 50/200)
- Multi-timeframe confirmation
- Proper risk management (2%)
- 1-hour blacklist cooldown

---

## Using Old Versions

**Warning**: Old versions are provided for reference only. They contain known issues that have been fixed in newer versions.

To use an old version (not recommended):
```bash
# Backup current version
cp src/oracle_bot.py src/oracle_bot.py.current

# Copy old version
cp versions/v1/oracle_bot.py src/oracle_bot.py

# Restart bot
sudo systemctl restart oracle-bot
```

## Comparing Versions

```bash
# Compare V1 to V2
diff versions/v1/oracle_bot.py versions/v2/oracle_bot.py

# View specific changes
git log --oneline src/oracle_bot.py
```

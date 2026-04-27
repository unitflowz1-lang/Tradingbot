# 🚀 Quick Start Guide - Trading Bot

## Current Status: ✅ READY FOR STARTUP

All critical fixes applied. Bot is ready to start.

---

## Step 1: Verify Fixes (2 minutes)

### Test 1: Verify config.yaml is valid
```bash
python -c "
import yaml
try:
    with open('config.yaml') as f:
        config = yaml.safe_load(f)
    print('✓ config.yaml VALID')
    print(f'  App: {config[\"app_name\"]}')
    print(f'  Broker: {config[\"broker\"][\"broker\"]}')
except Exception as e:
    print(f'✗ ERROR: {e}')
"
```

**Expected Output:**
```
✓ config.yaml VALID
  App: AlgoTradingBot Pro
  Broker: mt5
```

---

### Test 2: Verify MT5 Connection
```bash
python -c "
import MetaTrader5 as mt5
mt5.initialize()
acc = mt5.account_info()
print(f'✓ MT5 Connected')
print(f'  Account: {acc.login}')
print(f'  Balance: \${acc.balance:.2f}')
print(f'  Equity: \${acc.equity:.2f}')
mt5.shutdown()
"
```

**Expected Output:**
```
✓ MT5 Connected
  Account: 5044383203
  Balance: $95514.68
  Equity: $95507.01
```

---

### Test 3: Run Pre-Flight Check (all systems)
```bash
python pre_flight_check.py
```

**Expected Output:**
```
✅ ALL CHECKS PASSED - BOT READY FOR STARTUP
```

---

## Step 2: Start the Bot

### For Demo Trading (Current Setup)
```bash
python main_production.py
```

**What to expect:**
- Bot connects to MT5
- Loads market data
- Generates signals
- Opens positions with trailing SL
- Logs appear in console

### Monitor First 5 Minutes
Look for these log messages:

```
[ENGINE] Initializing trading engine...
[ENGINE] Connected to broker ✓
[ENGINE] Engine initialized successfully
[ENGINE] Starting trading loop...
[TRAILING_SL_INIT] Manager initialized ✓
```

---

## Step 3: Verify Trailing SL is Working

### Watch the logs for:

✅ **[TRAILING_SL_UPDATED]** - Good! SL modification succeeded
```
[INFO] [TRAILING_SL_UPDATED] EURUSD | Ticket: 12345 | Price: 1.0875 | New SL: 1.0820
```

✅ **[SL_MOD_THROTTLED]** - Normal! Throttle protecting from spam
```
[DEBUG] [SL_MOD_THROTTLED] Time throttle: 2.5s < 5.0s
```

⚠️ **[SL_MOD_REJECTED]** - Warning! Broker rejected (increase buffer if seen)
```
[WARNING] [SL_MOD_REJECTED] EURUSD ticket 12345 | Broker rejected
```

---

## Step 4: Stop the Bot Safely

### Normal Shutdown
```
Ctrl + C
```

The bot will:
1. Stop accepting new signals
2. Log trailing SL diagnostics
3. Close all open positions
4. Disconnect from MT5
5. Exit cleanly

---

## Troubleshooting

### Problem: "config.yaml not found"
```bash
ls -la config.yaml
# Should show: -rw-r--r-- ... config.yaml
```

### Problem: "MT5 initialization failed"
1. Open MetaTrader5 Terminal
2. Ensure account is logged in
3. Run test again

### Problem: "Strategy not found"
The sma_crossover strategy may be defined elsewhere. The bot will use:
- mean_reversion ✓
- breakout ✓

---

## Current Configuration

### Account Details
- **Login:** 5044383203
- **Server:** MetaQuotes-Demo
- **Balance:** $95,514.68
- **Equity:** $95,507.01

### Trading Settings
- **Mode:** Balanced
- **Position Size:** 2% per trade
- **Max Daily Loss:** 5%
- **Trailing SL:** Enabled
- **Profit Lock:** Enabled
- **Buffer:** 8 pips (STOPS_LEVEL protected)

### Pairs
- EURUSD
- GBPUSD
- USDJPY
- XAUUSD

---

## Before LIVE Trading

When ready to switch to live trading:

1. **Update config.yaml:**
   ```yaml
   broker:
     login: YOUR_LIVE_LOGIN
     password: "YOUR_PASSWORD"
     server: "MetaQuotes-Live"  # Change from Demo
   ```

2. **Reduce position sizing:**
   ```yaml
   risk:
     max_position_size: 0.01  # Reduce from 2% to 1%
   ```

3. **Monitor first week:**
   - Day 1: 50% normal size
   - Day 2-3: 75% normal size
   - Day 4+: 100% normal size (if stable)

---

## Quick Reference

| Command | What it does |
|---------|------------|
| `python main_production.py` | Start the bot |
| `python pre_flight_check.py` | Verify all systems |
| `Ctrl+C` | Stop the bot |
| `tail -f logs/bot.log` | Watch logs in real-time |
| `grep "TRAILING_SL" logs/bot.log` | Find SL modifications |

---

## Emergency Rollback

If critical issue, revert the STOPS_LEVEL guard:
```bash
cp core/engine.py.backup.* core/engine.py
python main_production.py
```

---

## Next Steps

1. ✓ Verify fixes (Run tests above)
2. ✓ Start bot: `python main_production.py`
3. ✓ Monitor for 1 hour
4. ✓ Check for [TRAILING_SL_UPDATED] logs
5. ✓ If no [SL_MOD_REJECTED], you're good!

---

**Status:** 🟢 READY TO START


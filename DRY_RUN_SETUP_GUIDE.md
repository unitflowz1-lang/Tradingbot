# DRY RUN SETUP - 3-5 DAY FORWARD TEST
=======================================

## 📊 CURRENT STATUS

### ✅ What's Already Implemented:
1. **Aggressive Compounding** - 1.2x scaling after 3 wins, auto-reset on loss
2. **Spread Trap Protection** - Blocks entries if spread > 2x average
3. **Quality Floor** - Only high-probability signals admitted
4. **ATR-based SL/TP** - Dynamic stop loss and take profit

### 📁 Configuration Files:
- `config/optimized_params.json` - Aggressive parameters (from earlier sweep)
- `config/optimized_params_real.json` - Real data sweep v1 (FAILED - DO NOT USE)
- `config/optimized_params_conservative.json` - Real data sweep v2 (FAILED - DO NOT USE)

---

## 🎯 DRY RUN OBJECTIVES

### Primary Goals:
1. **Validate Win Rate** - Target: 54-59%
2. **Measure Trade Frequency** - Target: 60-90 trades/month
3. **Test Profit Factor** - Target: >1.7
4. **Monitor Max Drawdown** - Must stay <15%
5. **Verify Spread Protection** - Ensure no false SL hits

### Secondary Goals:
1. Test aggressive compounding logic in live conditions
2. Validate spread trap filter effectiveness
3. Collect real performance data for future optimization
4. Identify any runtime errors before going live

---

## 🛠️ STEP-BY-STEP SETUP

### Step 1: Check Current Configuration

```bash
# View current optimized parameters
cat config/optimized_params.json
```

Expected to see:
```json
{
  "quality_floor": 72,
  "ml_weight": 0.45,
  "atr_sl_multiplier": 2.0,
  "atr_tp_multiplier": 3.0,
  ...
}
```

**If this file doesn't exist or looks wrong, we'll use default conservative params.**

---

### Step 2: Create .env.dry_run Configuration

Create a dedicated environment file for dry run:

```bash
# Trading Mode
DRY_RUN=1
DRY_RUN_BALANCE=10000.0

# Risk Management
MAX_DRAWDOWN_PCT=15.0
RISK_PER_TRADE=0.02
MAX_POSITIONS=3

# Logging
LOG_LEVEL=INFO
LOG_TRADES=1
LOG_SIGNALS=1

# Features
ENABLE_AGGRESSIVE_COMPOUNDING=1
ENABLE_SPREAD_TRAP_PROTECTION=1
```

---

### Step 3: Update main.py for Dry Run

The bot should already have DRY_RUN support. Let me verify and enhance it.

---

### Step 4: Create Monitoring Dashboard

Set up real-time monitoring to track:
- Trade count and frequency
- Win rate progression
- Drawdown levels
- Compounding triggers
- Spread trap activations

---

### Step 5: Define Success/Failure Criteria

#### ✅ PASS Criteria (Go Live):
- Win Rate ≥ 52%
- Profit Factor ≥ 1.3
- Max Drawdown ≤ 12%
- Trade Frequency ≥ 40 trades (over 3-5 days)
- No runtime errors

#### ⚠️ CAUTION Criteria (Adjust & Retest):
- Win Rate 48-52%
- Profit Factor 1.0-1.3
- Max Drawdown 12-15%
- Trade Frequency 20-40 trades

#### ❌ FAIL Criteria (Stop & Review):
- Win Rate < 48%
- Profit Factor < 1.0
- Max Drawdown > 15%
- Runtime errors or crashes

---

## 📋 EXECUTION PLAN

### Day 1-2: Initial Run
- Start bot at market open (Sunday 22:00 UTC or Monday 00:00 UTC)
- Monitor first 10-20 trades closely
- Check for any errors or unexpected behavior
- Verify spread trap is working

### Day 3: Mid-Point Review
- Analyze metrics so far
- Check if trade frequency is on track
- Verify compounding logic is triggering correctly
- Adjust parameters if needed

### Day 4-5: Final Validation
- Collect full dataset
- Calculate final metrics
- Compare against success criteria
- Make go/no-go decision

### Day 6+: Go Live (If Passed)
- Switch DRY_RUN=0
- Start with smaller position sizes
- Monitor closely for first 24 hours

---

## 🔍 WHAT TO MONITOR

### Critical Metrics (Check Every 6 Hours):
```
1. Total Trades: __
2. Win Rate: __%
3. Profit Factor: __
4. Current Drawdown: __%
5. Equity: $__
```

### Warning Signs (Stop Immediately If):
- Drawdown exceeds 10%
- 5+ consecutive losses
- Bot stops logging trades
- Spread trap blocking >50% of signals
- Any runtime errors in logs

### Log Files to Watch:
```bash
# Main bot log
tail -f logs/bot_2026-04-25.log

# Trade log
tail -f logs/trades_2026-04-25.log

# Signal log
tail -f logs/signals_2026-04-25.log
```

---

## 📊 EXPECTED RESULTS

Based on your bot's architecture (ML + multi-TF + LLM + macro):

### Optimistic Scenario:
- Win Rate: 55-62%
- Profit Factor: 1.5-2.0
- Trades/Day: 8-12
- Max DD: 5-8%

### Realistic Scenario:
- Win Rate: 50-55%
- Profit Factor: 1.2-1.6
- Trades/Day: 6-10
- Max DD: 8-12%

### Conservative Scenario:
- Win Rate: 45-50%
- Profit Factor: 1.0-1.3
- Trades/Day: 4-8
- Max DD: 10-15%

**If results are below conservative scenario → Strategy needs review before going live.**

---

## 🚀 QUICK START COMMANDS

### Start Dry Run:
```bash
python main.py
```

### Monitor Logs:
```bash
# Real-time log monitoring
tail -f logs/bot_*.log | grep -E "TRADE|SIGNAL|DRAWDOWN|COMPOUND"
```

### Check Performance (After Run):
```bash
# Run performance analysis
python scripts/analyze_dry_run_results.py
```

### Stop Bot:
```bash
# Graceful shutdown
Ctrl+C
```

---

## 📝 PRE-FLIGHT CHECKLIST

Before starting dry run, verify:

- [ ] MT5 terminal is running and connected
- [ ] Demo account is accessible (Balance: $95,332.81)
- [ ] DRY_RUN=1 is set in environment
- [ ] Log files directory exists
- [ ] Network connection is stable
- [ ] No other instances of bot running
- [ ] Optimized params are loaded
- [ ] Spread trap protection is active
- [ ] Compounding logic is enabled
- [ ] Max drawdown limit is set (15%)

---

## 🎯 NEXT STEPS

1. **I'll create the dry run configuration files**
2. **I'll verify DRY_RUN mode in main.py**
3. **I'll create a monitoring script**
4. **You run the bot for 3-5 days**
5. **We analyze results together**
6. **Make go/no-go decision for live trading**

---

**Generated:** 2026-04-25
**Status:** READY FOR SETUP
**Estimated Duration:** 3-5 days

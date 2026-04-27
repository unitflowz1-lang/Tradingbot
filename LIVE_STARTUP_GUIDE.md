# 🚀 LIVE TRADING STARTUP GUIDE

## ✅ Ready to Launch

Your trading bot has been transitioned from Dry Run to Live Execution with all safety gates active.

---

## 📝 WHAT CHANGED

### Configuration (`.env`)
```diff
- DRY_RUN=1
+ DRY_RUN=0
+ BOOTSTRAP_MODE_ENABLED=0
+ FAIL_SAFE_DETERMINISTIC=1
+ LLM_TIMEOUT_SECONDS=10
+ ... (and 5 more safety gate configurations)
```

### Code (`main.py`)
- Lines 82-107: Safety gate configuration loader
- Lines 2625-2640: Bootstrap mode enforcement
- Lines 8415-8485: LLM fail-safe deterministic timeout handler

---

## 🎯 LAUNCH COMMAND

```bash
# Navigate to project directory
cd "c:\Users\macki\Desktop\v8.6 core RL TradingBot"

# Activate Python environment
.\.venv\Scripts\Activate.ps1

# Start live trading
python main.py
```

---

## 📊 REAL-TIME MONITORING

Open a new terminal and run:

```bash
python scripts/monitor_live_trading.py --alert-threshold 0.5
```

This displays:
- Current positions
- Win rate
- Slippage metrics
- Account equity
- Open trades
- Daily P&L

---

## ⏸️ EMERGENCY STOP

If anything goes wrong, immediately stop trading:

```bash
# Method 1: Kill the process
Ctrl+C

# Method 2: Revert to simulation mode
$env:DRY_RUN=1; python main.py
```

This will:
- Close all active trades gracefully
- Revert to dry-run simulation
- Prevent new orders from executing

---

## 🔍 WHAT TO EXPECT

### First Hour
- **Trades:** 2-5 expected
- **Position Size:** 0.05 lots (fixed)
- **Monitoring:** Manual observation required
- **Safety:** All gates active, maximum protection

### Log Output
```
[LIVE_EXECUTION_INIT] Bootstrap Mode: False | Fail-Safe Deterministic: True
[LIVE_EXECUTION_GATE] Bootstrap mode DISABLED. Strict trade admission enforced.
[ORDER_EXECUTE] EURUSD | BUY | 0.05 lots | Entry=1.08934 | SL=1.08825
[RISK_GUARD] ExposureNow=0.05% | Limit=2.00% | Decision=ADMITTED
```

### Trades Generated
Each trade will show:
- Entry price
- Stop loss
- Take profit
- Position size (0.05 lots)
- Reason for entry

---

## ✅ SAFETY GATES ACTIVE

| Gate | Purpose | Trigger |
|------|---------|---------|
| **Accuracy Guard** | Protect against bad ML models | ML accuracy < 50% → weight clamped to 5% |
| **Risk Guard** | Prevent over-leverage | Daily exposure > 2% → reject trade |
| **News Buffer** | Avoid high-impact events | News event within 30 min → reject trade |
| **Volume Floor** | No micro-positions | Position < 0.05 lots → rejected |
| **LLM Fail-Safe** | Prevent LLM timeout losses | LLM > 10s → use technical signals only |

---

## 📋 PRE-LAUNCH CHECKLIST

- [ ] **MT5 Account:** Connected and ready
- [ ] **Account Funded:** Minimum $5,000 available
- [ ] **Models Trained:** Check `models/` folder for `.pkl` files
- [ ] **Credentials:** API keys in `.env` validated
- [ ] **Market Hours:** Trading during forex hours (Sun 5PM - Fri 5PM ET)
- [ ] **Internet:** Stable connection confirmed
- [ ] **Monitoring:** Dashboard ready to run
- [ ] **Backup:** `.env` and `main.py` backups created

---

## 🔧 CONFIGURATION REVIEW

**Current Live Settings:**
- DRY_RUN: **OFF** (0)
- Bootstrap Mode: **DISABLED** (Strict admission)
- LLM Timeout: **10 seconds**
- Fail-Safe Deterministic: **ENABLED**
- Volume Floor: **0.05 lots**
- Daily Exposure Limit: **2%**
- All Safety Gates: **ACTIVE**

---

## 📞 TROUBLESHOOTING

### "ModuleNotFoundError" on startup
```bash
# Reinstall dependencies
pip install -r requirements.txt
```

### MT5 Connection Issues
```bash
python check_mt5_consts.py
```

### Models Not Found
```bash
python train_models_enhanced.py
```

### LLM Timeouts (> 10s)
- Expected: FAIL_SAFE_DETERMINISTIC activates
- Check LLM API health
- Consider increasing LLM_TIMEOUT_SECONDS if consistently > 15s

### Excessive Rejections
- Check `[LIVE_EXECUTION_GATE]` logs
- May indicate strict gates working correctly
- If normal, consider reviewing filter thresholds

---

## 📊 SUCCESS METRICS

After first 6 hours of live trading:
- ✅ At least 1 successful trade
- ✅ No slippage > 2 pips
- ✅ Account drawdown < 1%
- ✅ All stops/exits functioning
- ✅ Monitoring dashboard active

---

## 🎯 NEXT PHASE

After 6 hours (if all metrics look good):
1. Position sizing increases to 0.05-0.10 lots
2. More aggressive entry signals allowed
3. Continue strict gate enforcement
4. Monitor equity curve daily

---

## 📖 REFERENCE DOCUMENTS

- **Full Details:** `LIVE_EXECUTION_COMPLETE.md`
- **Safety Checklist:** `LIVE_EXECUTION_SAFETY_CHECKLIST.md`
- **Configuration:** `.env` file
- **Logs:** `logs/forex_bot.log`

---

## 🚀 READY TO GO

Your bot is configured and ready for live execution.

**Start trading:**
```bash
python main.py
```

**Monitor progress:**
```bash
python scripts/monitor_live_trading.py
```

Good luck! 🎯

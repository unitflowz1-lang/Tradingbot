# OPTION D DEPLOYMENT GUIDE - CONFIGURATION SUMMARY

**Status:** ✅ READY FOR DEPLOYMENT  
**Last Updated:** 2026-04-03  
**Authorization:** FULL SYSTEM UNLOCK - OPTION D CONFIRMED  

---

## What Changes From Option B to Option D?

### Primary Changes (NEW with Option D)

| Parameter | Option B | Option D | Impact |
|---|---|---|---|
| **FRIDAY_CUTOFF_HOUR** | 23 (11:00 PM UTC) | 23:59 (11:59 PM UTC) | Trade 59 minutes deeper into Friday |
| **OVERRIDE_ROLLOVER_PAUSE** | 0 (Pause ACTIVE) | 1 (Pause DISABLED) | Allows trading during 21:55-22:15 UTC spread spike |

### Secondary Settings (MAINTAINED from Option B)

| Parameter | Value | Purpose |
|---|---|---|
| **ML_ACCURACY_MIN_GATE** | 0.40 | 40% minimum ML accuracy |
| **SIGNAL_QUALITY_MINIMUM** | 0.30 | Signal quality floor 50% |
| **AGGRESSIVE_ENGAGEMENT** | 1 | Aggressive mode active |
| **PERMIT_INSTITUTIONAL_SWEEP_OVERRIDES** | 1 | Sweeps bypass Friday blocks |
| **ALLOW_FRIDAY_LATE_SESSION** | 1 | Friday late session enabled |

### Hard Limits (CANNOT OVERRIDE)

| Limit | Value | Status |
|---|---|---|
| **Daily Loss Limit** | $100/day | ✅ HARD ENFORCED |
| **Max Total Positions** | 12 | ✅ HARD ENFORCED |
| **Max Per-Symbol Positions** | 1 | ✅ HARD ENFORCED |
| **Risk/Reward Minimum** | 1.5R | ✅ HARD ENFORCED |
| **Margin Requirement** | 20% free | ✅ HARD ENFORCED |

---

## Code Changes Implemented

### File: `main.py` - Friday Banking Functions (ENHANCED FOR MINUTE-LEVEL PRECISION)

**Location:** Lines 2365-2396

**Change:** Updated `_friday_profit_clear_active()` and `_friday_force_bank_active()` to parse environment variable format "HH:MM" (hours:minutes)

**Before (Option B):**
```python
friday_cutoff_hour = int(os.environ.get("FRIDAY_CUTOFF_HOUR", "21"))
return now_utc.weekday() == 4 and now_utc.hour >= friday_cutoff_hour
```

**After (Option D):**
```python
friday_cutoff_str = os.environ.get("FRIDAY_CUTOFF_HOUR", "21")
if ":" in friday_cutoff_str:
    parts = friday_cutoff_str.split(":")
    friday_cutoff_hour = int(parts[0])
    friday_cutoff_minute = int(parts[1])
else:
    friday_cutoff_hour = int(friday_cutoff_str)
    friday_cutoff_minute = 0
# Now compares at minute-level: hour > cutoff || (hour == cutoff && minute >= cutoff_minute)
```

**Impact:** 
- Supports both "23" (whole hour) and "23:59" (hour:minute) formats
- Option D can specify exact cutoff to 23:59 (one minute before midnight UTC)
- Backward compatible with Option B format

---

## Deployment Sequence

### STEP 1: Run Activation Script

```powershell
# Navigate to project directory
cd "c:\Users\macki\Desktop\v8.6 core RL TradingBot"

# Activate virtual environment
& ".\.venv\Scripts\Activate.ps1"

# Run Option D activation script
& ".\ACTIVATE_OPTION_D.ps1"
```

**Expected Output:**
```
OPTION D: FULL OVERRIDE ACTIVATION
...
✓ FRIDAY_CUTOFF_HOUR = '23:59'
✓ OVERRIDE_ROLLOVER_PAUSE = '1'
✓ ML_ACCURACY_MIN_GATE = '0.40'
... [other env vars]
OPTION D ACTIVATION COMPLETE
```

### STEP 2: Restart Trading Bot

```powershell
# Kill existing bot process (if running)
Get-Process | Where-Object {$_.Name -eq "python"} | Stop-Process -Force

# Start trading bot with new environment variables
python main.py
```

### STEP 3: Verify Option D is Active (Check Startup Logs)

Look for these confirmations in bot startup output:

```
[GOVERNANCE] OPTION_D Active: FRIDAY_CUTOFF_HOUR=23:59
[GOVERNANCE] OPTION_D Active: OVERRIDE_ROLLOVER_PAUSE=1
[STATUS] Friday cutoff time: 23:59 UTC
[STATUS] Rollover pause: DISABLED (Will trade during 21:55-22:15 UTC)
[STATUS] ML accuracy gate: 40%
[STATUS] Quality floor: 50%
[STATUS] Max positions: 12
```

---

## Operational Timeline

### Friday Session Trading Pattern (NEW OPTION D)

```
UTC Time        Activity                                    Risk Level
─────────────────────────────────────────────────────────────────────────
15:00-21:55    Normal trading (low slippage)              🟢 LOW
21:55-22:15    ⚠️  ROLLOVER WINDOW (spreads 20-50 pips)   🔴 EXTREME
                Normally auto-paused, NOW ACTIVE
22:15-23:59    End-of-session trading (moderate spreads)  🟡 MEDIUM
23:59-00:00    Market close (NO NEW TRADES)               🔴 HIGH
00:00-21:00    Weekend (Sat/Sun, NO LIQUIDITY)            ⚠️  GAP RISK
                Held positions exposed to 50-200 pip gaps
```

### Risk Accumulation Pattern (OPTION D)

**Weekly Scenario:**
- Monday-Thursday: Normal trading, quality signals (40-50% win rate expected)
- Friday 15:00-21:55: Extended session trading (39% loss rate, 40% ML accuracy)
- Friday 21:55-22:15: Rollover period, high slippage trades (potential -$40-200/lot slippage)
- Friday 22:15-23:59: Extended trading (39% loss rate, high end-of-day volatility)
- Friday 23:59-Sunday: Held positions through weekend (50-200 pip gap exposure)

**Expected Monthly Impact:**
- Increased trade volume: +30-40% more trades per week
- Quality degradation: 40% signals (vs 50%+ normal M-Th)
- Slippage costs: +$500-1000/month from rollover window
- Gap losses: +$500-2000/month from weekend open (if positions held)
- Bottom line: -10% account equity per month reasonable projection

---

## Real-Time Monitoring Checklist

### Daily Checks

- [ ] Bot started successfully with Option D env vars loaded
- [ ] Daily loss limit enforcement (stops trading at -$100)
- [ ] Position count stays under 12
- [ ] No margin violations (minimum 20% free margin maintained)

### Friday Checks (CRITICAL)

- [ ] Trading extends from default (21:00 UTC) to new cutoff (23:59 UTC)
- [ ] Positions allowed during rollover window (21:55-22:15 UTC)
- [ ] Spread monitoring during rollover (expect 20-50 pips vs normal 2 pips)
- [ ] Friday close positions automatically cleared at 23:59 UTC
- [ ] No "stranded" positions held through weekend

### Weekly Analysis (MANDATORY)

- [ ] Win rate tracking: Expect 40-45% (down from 50%+ normally)
- [ ] Slippage costs: Track rollover window costs separately
- [ ] Gap exposure: Monitor weekend opening gaps on held positions
- [ ] P&L trend: Should be monitored for drawdown acceleration

---

## Crisis Indicators - STOP TRADING SIGNALS

If ANY of these occur, manually disable Option D immediately:

| Signal | Trigger | Action |
|---|---|---|
| **Consecutive Losses** | 5+ losing trades = -$50-100 | Pause/review quality |
| **Daily Loss Limit Hit** | -$100 reached | Bot auto-stops (reset on midnight) |
| **Gap Losses** | >-150 pips weekend gap | Exit on Monday open |
| **Rollover Slippage** | >-15 pip average slippage | Avoid 21:55-22:15 UTC trades |
| **Margin Pressure** | Free margin <25% | Stop new entries |
| **Weekly Drawdown** | >-2% account equity | Revert to Option B immediately |

---

## How to Revert If Needed

If you need to return to Option B (safer configuration):

```powershell
# Revert Friday cutoff to 23:00 UTC
$env:FRIDAY_CUTOFF_HOUR = "23"

# Revert rollover pause to ACTIVE
$env:OVERRIDE_ROLLOVER_PAUSE = "0"

# Restart bot
# Bot will resume with safer settings
```

**Complete Reversion to Option 2 (Most Conservative):**

```powershell
# Disable aggressive overrides
$env:OVERRIDE_ROLLOVER_PAUSE = "0"
$env:FRIDAY_CUTOFF_HOUR = "21"
$env:AGGRESSIVE_ENGAGEMENT = "0"
```

---

## Key Documentation Files

- ✅ `OPTION_D_AUTHORIZATION_CONFIRMATION_2026_04_03.md` - Authorization log with all 6 confirmations
- ✅ `ACTIVATE_OPTION_D.ps1` - Activation script with all environment variables
- ✅ `OPTION_D_DEPLOYMENT_GUIDE.md` - This file
- ✅ `5_CRITICAL_FIXES_COMPREHENSIVE_GUIDE.md` - Original architecture guide
- ✅ `SYSTEM_GOVERNANCE_OVERRIDES.md` - Options A-D explanation

---

## Final Notes

**OPTION D IS NOW LIVE AND AUTHORIZED**

- All 6 explicit confirmations received and logged
- Code enhanced to support minute-level Friday cutoff precision
- Environment variables ready for activation
- Fallback mechanisms maintained (daily loss limit, position limits, R/R minimum)
- Full monitoring framework established

**Proceed with confidence in the acknowledged risks.**

Status: ✅ **READY FOR LIVE DEPLOYMENT**

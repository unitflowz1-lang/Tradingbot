# BALANCED CONFIGURATION DEPLOYMENT - Complete Guide

**Date:** April 2, 2026  
**Status:** ✅ IMPLEMENTED  
**Version:** Balance Build v0.1

---

## Executive Summary

This document details the balanced configuration deployment for the MT5 forex bot, implementing:
- **Timezone Fix**: UTC+2 broker offset (3 → 2)
- **ML Accuracy Gate**: Lowered to 45% (from 50%) for low-volatility sessions
- **ADX Floors**: Adjusted to 14/10 (from 18/12) with maintained minimums
- **State Preservation**: Disabled amnesia on startup, ML auto-training enabled
- **Macro Risk Handling**: Live news mode with fallback volatility scoring
- **Execution Efficiency**: Early ADX checks, trend strategy in any regime

### Key Principle

**Every trade must pass every gate.** Adaptive floors allow legitimate setups during low-volatility sessions while keeping protective gates at full strength.

---

##Configuration Changes Implemented

### 1. TIMEZONE FIX

**Change:** `BROKER_TIMEZONE_OFFSET_HOURS: 3 → 2`

**Where Updated:**
- `.env.optimized` (line 20)
- `src/data/mt5_broker.py` (default: 2)
- `src/trading/exit_manager.py` (default: 2)
- `src/trading/position_manager.py` (default: 2)
- `main.py` (line 1892, default: 2)

**Impact:**
- Position `opened_at` timestamps now correctly convert from UTC+2 broker time to UTC
- Position age calculation no longer shows negative values
- 40-bar time exit rule will now trigger correctly

**Verification:**
```bash
# Check timezone offset is applied
grep "BROKER_TIMEZONE_OFFSET_HOURS" .env.optimized
# Should show: BROKER_TIMEZONE_OFFSET_HOURS=2

# Test position age calculation
python test_timezone_fix.py
# Should show: ✓ ALL TESTS PASSED
```

---

### 2. ML ACCURACY GATE

**Change:** `ML_ACCURACY_MIN_GATE: 0.50 → 0.45`

**Where Updated:**
- `.env.optimized` (line 30): `ML_ACCURACY_MIN_GATE=0.45`
- `main.py` (line 6070-6089): Now reads from environment variable

**Rationale:**
- Allows more pairs to trade during low-volatility Tokyo session
- Pairs like AUD/USD and USD/JPY frequently have 45% accuracy during range-bound periods
- Still rejects completely statistically compromised models (< 42%)
- Minimum floor of 42% is maintained (do NOT go below this)

**Current Behavior:**
```python
ml_accuracy_min_gate = float(os.environ.get("ML_ACCURACY_MIN_GATE", "0.45"))
# Rejects if ml_acc < ml_accuracy_min_gate
# For forced_execution: also applies ml_accuracy_min_gate check
```

**Monitoring:**
- Watch for `[STRATEGY_REJECT]` messages showing accuracy gate in logs
- Expected: More trades admitted during Tokyo session
- Red flag: Accuracy < 42% (indicates misconfiguration)

---

### 3. ADX FLOORS - BALANCED ADJUSTMENT

**Changes:**
- `ADX_MIN_STANDARD: 18 → 14` (lowered for better trending pair access)
- `ADX_MIN_RELAXED: 12 → 10` (maintained relaxed floor)

**Where Updated:**
- `.env.optimized` (lines 25-26):
  ```
  ADX_MIN_STANDARD=14
  ADX_MIN_RELAXED=10
  ```
- `main.py` (lines 5248-5253): Now reads from environment

**Logic:**
```python
adx_floor_standard = int(os.environ.get("ADX_MIN_STANDARD", "14"))
adx_floor_relaxed = int(os.environ.get("ADX_MIN_RELAXED", "10"))
adx_min_for_profile = adx_floor_standard if tokyo_guard_active else adx_floor_relaxed
```

**Regime Behavior:**
| Condition | ADX Floor | Rationale |
|-----------|-----------|-----------|
| Tokyo Guard Active | 14 (ADX_MIN_STANDARD) | Trend pairs during Asian hours |
| Standard Hours | 10 (ADX_MIN_RELAXED) | Lower floor for broader coverage |
| Never below | 10 | Absolute minimum, no exceptions |

**DO NOT:** Go below 10 under any circumstance (indicates system instability)

---

### 4. ML MODEL TRAINING - STARTUP BEHAVIOR

**Changes:**
```
ML_RETRAIN_ON_STARTUP=true
RETRAIN_IF_NO_MODEL=true
FORCE_ML_TRAIN_MISSING_MODELS=true
```

**Where Updated:** `.env.optimized` (lines 33-35)

**What This Does:**
- On startup, immediately trains ML models for any pair without one
- Prevents "ML=NONE" signals from entering the strategy
- AUD/USD and USD/JPY will train on first cycle if missing models
- Forces model training before admission controller check

**Implementation:** Startup checks for missing models and triggers training loop

---

### 5. STATE PRESERVATION - AMNESIA DISABLED

**Changes:**
```
AMNESIA_MODE_ON_STARTUP=false
BRAIN_WASH_ON_STARTUP=false
```

**Where Updated:** `.env.optimized` (lines 37-38)

**Impact:**
- **Before:** Every startup wiped all cooldowns, volatility floors, strategy memory
- **After:** Learned state, cooldowns, volatility floors preserved across restarts
- Only wipe if explicitly commanded via admin override

**Behavior:**
- Volatility floor data from previous session reloaded
- Pair-specific cooldowns preserved
- Strategy learning state maintained
- Position history available for attribution

**Override:** If needed to reset state, use explicit admin command (not automatic on startup)

---

### 6. EARLY ADX PRECHECK

**Change:** `EARLY_ADX_PRECHECK=true`

**Where Updated:** `.env.optimized` (line 40)

**Rationale:**
Prevents wasted computation on invalid signals:
- Signal passes EV check, correlation check, risk gates
- Then fails on ADX floor (ADX = 7.8 when floor = 10)
- Result: Wasted cycles computing full signal pipeline

**New Behavior:**
1. ADX floor check happens EARLY in pipeline
2. Reject immediately if ADX too low
3. Saves compute resources for valid opportunities

---

### 7. EXPLORATION MODE GUARD

**Change:** `EXPLORATION_ADX_BYPASS=false`

**Where Updated:** `.env.optimized` (line 39)

**Requirement:**
Exploration signals must still satisfy `ADX_MIN_RELAXED` (10).
- A signal with ADX = 7.8 must NOT reach execution stage
- Exploration does not bypass ADX floor
- All signals use same ADX gates

---

### 8. TREND STRATEGY IN RANGING MARKET

**Change:** `ALLOW_TREND_STRATEGY_IN_RANGE=true`

**Where Updated:** `.env.optimized` (line 41)

**Requirement:**
Remove hard-lock that disables trend entries when `market_regime == RANGING`.
- If signal passes new lowered ADX floor (14/10), admit regardless of regime label
- Market regime is informational, not a absolute gate
- Trend setup can still be valid in ranging periods if ADX is strong enough

**Logic:**
```
IF Signal Generation == Trend
  AND market_regime == RANGING
  AND ADX >= ADX_MIN_STANDARD
  THEN: Admit signal (old logic would reject)
```

---

### 9. NEWS & MACRO MODULE

**Changes:**
```
NEWS_MODE=live
MACRO_RISK_FALLBACK=volatility_conservative
MACRO_RISK_PENALTY_WHEN_UNAVAILABLE=0.15
```

**Where Updated:** `.env.optimized` (lines 43-46)

**Requirements:**
- Connect a live news provider (critical for macro guidance)
- If provider unavailable: Apply 0.15 penalty to macro risk score instead of zeroing it out
- This prevents the risk shield from being completely disabled when news data is missing

**Fallback Behavior:**
```
When live news unavailable:
  macro_risk_score = volatility_based_score + 0.15 penalty
  (Previously: macro_risk_score = 0.00 with no penalty)
```

---

## Configuration Summary Table

| Parameter | Old Value | New Value | Reason |
|-----------|-----------|-----------|--------|
| BROKER_TIMEZONE_OFFSET_HOURS | 3 | 2 | UTC+2 broker |
| ML_ACCURACY_MIN_GATE | 0.50 (hardcoded) | 0.45 | Allow Tokyo session trades |
| ADX_MIN_STANDARD | 18 | 14 | Trending pairs during Asian hours |
| ADX_MIN_RELAXED | 12 | 10 | Maintain balanced floor |
| ML_RETRAIN_ON_STARTUP | false | true | Ensure models ready |
| AMNESIA_MODE_ON_STARTUP | true | false | Preserve learned state |
| EARLY_ADX_PRECHECK | false | true | Compute efficiency |
| NEWS_MODE | mock | live | Live macro guidance |
| MACRO_RISK_FALLBACK | — | volatility_conservative | Graceful degradation |

---

## Deployment Checklist

### Pre-Deployment
- [ ] Backup current `.env.optimized` file
- [ ] Backup current `main.py` file
- [ ] Verify broker timezone is actually UTC+2 (not UTC+3 or other)

### Deployment
- [ ] Update `.env.optimized` with new values
- [ ] Update `src/data/mt5_broker.py` (timezone default)
- [ ] Update `src/trading/exit_manager.py` (timezone default)
- [ ] Update `src/trading/position_manager.py` (timezone default)
- [ ] Update `main.py` (ADX floors, ML accuracy gate, timezone)
- [ ] Verify all imports and syntax

### Validation
- [ ] Run: `python test_timezone_fix.py` → All tests pass
- [ ] Check: `grep "BROKER_TIMEZONE_OFFSET_HOURS=2" .env.optimized`
- [ ] Check: `grep "ADX_MIN_STANDARD=14" .env.optimized`
- [ ] Check: `grep "ML_ACCURACY_MIN_GATE=0.45" .env.optimized`

### Post-Deployment Monitoring (First 24 Hours)

#### Hour 1-2: Startup Validation
- [ ] Bot starts without crashes
- [ ] Models train on startup (watch for `[ML_RETRAIN]` or `[FORCE_ML_TRAIN]` messages)
- [ ] No timezone warnings in first cycle
- [ ] Position ages calculate correctly (increasing ~1 bar/hour for 1H charts)

#### Hour 2-6: Tokyo Session (Check ADX Floor Effects)
- [ ] More signals admitted compared to old config
- [ ] Position ages increase normally (0 to 40+ bars over session)
- [ ] 40-bar exit fires when positions held 40+ bars
- [ ] No negative age warnings

#### Hour 6-24: Full Cycle Monitoring
- [ ] ML accuracy gate functioning (watching for `[STRATEGY_REJECT]` with accuracy % > 42%)
- [ ] ADX precheck working (signals rejected early if ADX too low)
- [ ] Macro risk handling working (if live news available, using live data; if not, using fallback)
- [ ] Trend strategy admits signals in ranging markets if ADX strong
- [ ] Volatility floors preserved across cycles (not reset on every startup)

### Red Flags (Alert Immediately)
- ❌ `[POSITION_AGE_SYNC_WARNING]` messages appearing
- ❌ Positions stuck at 0 bars for entire session
- ❌ 40-bar exit never triggering
- ❌ ML accuracies showing < 42%
- ❌ Bot crashing on startup with ML training
- ❌ News provider connection errors with no fallback penalty applied

---

## Testing & Validation

### Test 1: Timezone Conversion
```bash
cd c:\Users\macki\Desktop\v8.5\ core\ RL\ TradingBot
python test_timezone_fix.py
# Expected output: ✓ ALL TESTS PASSED
```

### Test 2: ML Accuracy Gate
Monitor logs for:
```
[STRATEGY_REJECT] EUR/USD | Effective Accuracy 44.0% is below Gate (45.0%).
# Correctly rejecting at 44%, allowing at 45%
```

### Test 3: ADX Floor Enforcement
Monitor logs for:
```
[FILTER] USD/JPY rejected: ADX 9.2 <= 10 (Dynamic Floor)
# Correctly enforcing ADX_MIN_RELAXED=10
```

### Test 4: Position Age Calculation
Monitor logs for increasing age values:
```
Cycle 1: Position EURUSD age = 0.5 bars
Cycle 2: Position EURUSD age = 1.5 bars
Cycle 3: Position EURUSD age = 2.5 bars
# Age increasing correctly, not clamped to 0
```

---

## Troubleshooting

### Issue: Still seeing [POSITION_AGE_SYNC_WARNING]

**Solution:**
1. Verify broker is actually UTC+2: Check MT5 server time vs UTC
2. If broker is UTC+3: Change back to `BROKER_TIMEZONE_OFFSET_HOURS=3`
3. If other offset: Calculate correctly and update
4. Restart bot with new offset

### Issue: ML models not training on startup

**Solution:**
1. Check logs for `[FORCE_ML_TRAIN_MISSING_MODELS]` message
2. Verify `ML_RETRAIN_ON_STARTUP=true` in `.env.optimized`
3. Check for ML training timeouts (may need longer startup time)
4. Force manual training if needed (with admin override)

### Issue: Too many signals rejected for low accuracy

**Solution:**
1. This indicates weak market conditions for ML
2. Lower `ML_ACCURACY_MIN_GATE` to 0.42 (minimum)
3. Do NOT go below 0.42 (system integrity risk)
4. Consider increasing confidence gates instead

### Issue: Trend strategy not entering ranging markets

**Solution:**
1. Verify `ALLOW_TREND_STRATEGY_IN_RANGE=true` set
2. Check ADX value (must meet floor even in ranging market)
3. Verify signal is actually "trend" type (not "mean_reversion")
4. Check regime detection accuracy

---

## Performance Impact

- ✅ **Computational:** Negligible (timezone math is O(1), early ADX check saves cycles)
- ✅ **Memory:** No additional memory usage
- ✅ **Latency:** Slightly improved (early ADX precheck prevents deep pipeline execution)
- ✅ **Throughput:** Potentially higher (more signals admitted through lower ADX floor)

---

## Success Metrics

After 24 hours, target metrics:
- ✅ Zero `[POSITION_AGE_SYNC_WARNING]` messages
- ✅ Position ages increasing correctly (0-40+ bars over session)
- ✅ At least one 40-bar time exit trigger observed
- ✅ ML models trained on startup for all pairs
- ✅ Trend signals admitted in ranging markets when ADX sufficient
- ✅ No crashes or unexpected errors
- ✅ Macro risk scores using live news data (or fallback with penalty)

---

## Rollback Plan

If critical issues arise:

### Immediate Rollback
```bash
# Restore from backup
cp .env.optimized.backup .env.optimized
cp main.py.backup main.py
# Restart bot
```

### Partial Rollback (Keep Some Changes)
- Keep timezone fix (3→2, most reliable)
- Revert ADX floors to 18/12
- Revert ML accuracy gate to 0.50
- Keep state preservation

---

## Documentation Files

Related documentation:
- **TIMEZONE_FIX_COMPREHENSIVE_REPORT.md** - Detailed timezone fix technical details
- **TIMEZONE_FIX_DEPLOYMENT_CHECKLIST.md** - Timezone deployment validation
- **.env.optimized** - Configuration source of truth
- **main.py** - Code implementation (lines 5248-5289, 6070-6089, 1892)

---

## Questions & Support

For configuration questions:
1. Check `.env.optimized` for current values
2. Review test_timezone_fix.py for validation examples
3. Monitor logs for configuration-related messages
4. Verify broker offset is correct for your broker

---

**Last Updated:** 2026-04-02  
**Status:** Ready for Production Deployment

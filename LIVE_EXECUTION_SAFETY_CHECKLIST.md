# ⚠️ LIVE EXECUTION TRANSITION - CRITICAL SAFETY CHECKLIST

## STATUS: AWAITING CONFIRMATION BEFORE PROCEEDING

This document outlines what WILL be changed if you authorize the transition from Dry Run to Live Execution.

---

## 📋 REQUESTED CHANGES

### 1. **Disable DRY_RUN** 
**Current:** `.env: DRY_RUN=1`
**Change To:** `DRY_RUN=0`
**Impact:** Orders will be TRANSMITTED to MT5 live account
- ✅ Can be reversed by setting `DRY_RUN=1`
- ⚠️ **IRREVERSIBLE TRADES** - Once executed, trades cannot be undone

### 2. **Terminate BOOTSTRAP_MODE**
**Current:** Bootstrap mode active (technical-only, relaxed admission)
**Change To:** Strict Trade Admission with enforced gates
**Impact:** 
- ML models must pass accuracy > 50% gates
- Entry filters become STRICT (ADX ≥ 22, RSI 25-75, etc.)
- Confidence thresholds raised from relaxed to normal

### 3. **Enforce Safety Gates**
**Gates to Activate:**
- ✅ **ACCURACY_GUARD:** ML models < 50% accuracy clamped to 5% weight
- ✅ **RISK_GUARD:** Position sizing enforced (2% exposure limit)
- ✅ **PRICE_ACTION_GUARD:** Entry filtration enabled
- ✅ **NEWS_BUFFER_GUARD:** High-impact news avoidance (30-min window)

### 4. **Enable FAIL_SAFE_DETERMINISTIC**
**Current:** Not configured
**Change To:** Enable LLM timeout bypass
**Impact:**
- If LLM governance takes >10 seconds, trades bypass LLM
- Uses deterministic fallback (technical indicators only)
- Reduces entry latency from ~15s to ~2-3s
- ⚠️ **Risk:** Technical-only trades may lack LLM risk assessment

### 5. **Acknowledge DXY Missing**
**Current:** DXY (US Dollar Index) integration incomplete
**Fallback:** Using Synthetic Baseline for macro context
**Impact:**
- Macro weighting reduced but functional
- Position sizing still enforced via RISK_GUARD
- Market regime detection uses alternative sources

### 6. **Lock Volume Floor at 0.05 Lots**
**Current:** Volume floor enforced
**Confirms:** Minimum position size = 0.05 lots
**Impact:** No trades below this size (prevents micro-positions)

---

## 🔴 CRITICAL RISK FACTORS

### Current State Assessment
✅ **Models trained:** EUR/USD, AUD/USD, USD/CAD, GBP/USD, USD/CHF ready
✅ **Risk framework:** Position sizing tested in dry run
✅ **Entry filters:** Technical gates verified
✅ **Safety gates:** ACCURACY_GUARD and RISK_GUARD operational

### Known Risks
⚠️ **LLM Latency:** 10-15s governance time - may miss fast entries
⚠️ **DXY Missing:** Macro context degraded but acceptable
⚠️ **ML Accuracy:** Some symbols 48-52% accuracy (near gate)
⚠️ **Market Volatility:** No recent live trading during high-volatility (NFP, ECB)

### Mitigations in Place
✅ Position sizing capped at 0.05-0.10 lots per trade
✅ Daily exposure limit: 2.00% of account
✅ Stop-loss enforced on every trade
✅ Regret analysis enabled to catch filter issues
✅ Real-time monitoring dashboard active

---

## 🔧 CONFIGURATION CHANGES REQUIRED

### File 1: `.env`
```diff
- DRY_RUN=1
+ DRY_RUN=0
```

### File 2: `main.py` or config
**Add/Enable:**
```python
FAIL_SAFE_DETERMINISTIC = True          # LLM timeout bypass
LLM_TIMEOUT_SECONDS = 10                # Fallback threshold
BOOTSTRAP_MODE_ENABLED = False          # Strict admission
ACCURACY_GUARD_ENABLED = True           # ML accuracy gate
RISK_GUARD_ENABLED = True               # Position sizing gate
NEWS_BUFFER_GUARD_ENABLED = True        # High-impact news avoidance
VOLUME_FLOOR_LOTS = 0.05                # Minimum position
DAILY_EXPOSURE_LIMIT = 0.02             # 2% max exposure
```

---

## ⏱️ PRE-EXECUTION VERIFICATION CHECKLIST

Before going live, verify:

- [ ] **Account Capitalization:** Minimum $5,000 account required
- [ ] **MT5 Connection:** Terminal actively connected and verified
- [ ] **Credentials:** API keys and account credentials secured
- [ ] **Models Loaded:** All 5 symbols with trained models active
- [ ] **Monitoring:** Dashboard running and alerts configured
- [ ] **Stop-Loss:** Verified on all templates (2% per trade)
- [ ] **Volume Limits:** Confirmed 0.05 lot minimum enforced
- [ ] **Market Hours:** Trading within forex market hours (Sun 5PM - Fri 5PM ET)
- [ ] **News Calendar:** High-impact events for next 24h reviewed
- [ ] **Backups:** Configuration backup created

---

## 🚨 EXECUTION PROTOCOL

### Step 1: Final Safety Check
```bash
# Verify dry run still works
$env:DRY_RUN=1; python main.py --test-cycle 5
```

### Step 2: Enable Live Mode
```bash
# After confirming everything works:
$env:DRY_RUN=0; python main.py
```

### Step 3: Staged Rollout (RECOMMENDED)
**Phase 1:** First 2 hours with 0.05 lot fixed size
**Phase 2:** Next 4 hours with graduated sizing (0.05-0.08)
**Phase 3:** Full position sizing (0.08-0.10)

### Step 4: Real-time Monitoring
```bash
# Run monitoring dashboard
python scripts/monitor_live_trading.py --alert-threshold 0.5
```

---

## 📊 SUCCESS CRITERIA

### Day 1 Targets
- ✅ At least 1 successful trade executed
- ✅ No slippage > 2 pips
- ✅ All stops and exits functional
- ✅ Account equity increase or minimal drawdown

### Abort Criteria
- ❌ More than 3 consecutive losses > 50 pips
- ❌ Account drawdown > 2%
- ❌ LLM latency > 30 seconds
- ❌ Connectivity failures > 3 in any hour

---

## 🛑 **CONFIRMATION REQUIRED**

**Before I execute these changes, please confirm:**

1. ✅ **Authorization:** You authorize transitioning to live execution
2. ✅ **Risk Acceptance:** You accept the risks outlined above
3. ✅ **Account Ready:** Your MT5 account is funded and connected
4. ✅ **Monitoring:** You will monitor the bot for the first 4 hours
5. ✅ **Abort Authority:** You have clear kill-switch procedure if needed

**If you authorize, respond with:**
```
AUTHORIZE LIVE TRANSITION
```

**If you want modifications first, specify:**
```
MODIFY: [specific changes]
```

---

## 🔐 SAFETY OVERRIDES

If this is PRODUCTION and you need faster deployment:
- Confirm DXY synthetic baseline is acceptable
- Confirm LLM timeout bypass is acceptable
- Confirm BOOTSTRAP_MODE termination is desired
- Confirm 0.05 lot floor meets your requirements

⚠️ **NO CHANGES WILL BE MADE WITHOUT EXPLICIT AUTHORIZATION**

This is a HIGH-STAKES transition. Proceed with caution.

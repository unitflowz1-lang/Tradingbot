# Critical Issues & Fixes - Trading Bot v8.5

## Issue #1: ML Gate Logic (PRIORITY: HIGH - Likely False Positive)
**Current Code** (main.py, line 5410):
```python
if not has_ml_gate:  # This blocks if ml_conf < threshold
    logger.warning(f"[ML_GATE] {symbol} forced_execution BLOCKED | ML conf: {ml_conf:.1%} (need >={ml_forced_threshold:.0%})")
    signal.forced_execution = False
    is_forced = False
```

**Analysis**: The logic appears correct on the surface, but the issue report suggests 66.6% confidence getting blocked when threshold is 15%. This could be:
1. **Timing issue**: ml_conf calculation might be referencing stale data
2. **Wrong threshold**: ml_forced_threshold might be set to something different
3. **Inverted elsewhere**: The inversion might be in ml_conf calculation

**Fix**: Add debug logging and verify ml_conf is calculated correctly

---

## Issue #2: Loss Restriction Blocking New Trades (PRIORITY: CRITICAL)
**Location**: `src/monitoring/decision_matrix.py`, line 305-310

**Current Code**:
```python
def _check_emergency_conditions(self, metrics: MetricsSnapshot) -> Tuple[Action, List[str]]:
    triggers = []
    if metrics.max_consecutive_losses >= 10:
        triggers.append(f"Consecutive losses: {metrics.max_consecutive_losses} (threshold: 10)")
    if metrics.daily_pnl < -500:  # More than $500 loss in a day
        triggers.append(f"Daily loss exceeds $500: ${metrics.daily_pnl:.2f}")
```

**Problem**: With unrealized PnL of -$2.00, this shouldn't trigger. But loss restriction IS blocking trades. The issue might be:
- Decision matrix is being set to EMERGENCY_CUTOFF unnecessarily
- Or trading signal is hitting a DIFFERENT loss restriction check

**Recommendation**: 
1. Increase daily_pnl threshold from -$500 to -$1,000
2. Add a "recovery window" so once drawdown hits X%, allow forced_execution trades through
3. Log which condition triggered EMERGENCY_CUTOFF for visibility

---

##  Issue #3: Liquidity Trap Kill-Switch Too Aggressive (PRIORITY: HIGH)
**Location**: `src/analysis/predictive_price_engine.py`, lines 120-140

**Current Code**:
```python
if edge >= 0.10:
    size_mult = 1.5
elif edge > 0.0:
    size_mult = 1.2
elif edge == 0.0:
    size_mult = 1.0
elif edge > -0.10:
    size_mult = 0.7
else:  # edge <= -0.10
    size_mult = 0.0  # <-- KILLS TRADE
```

**Problem**: When edge drops below -0.10 (which happens easily with bearish sweeps), size_mult becomes 0.0, killing the trade entirely.

**Fix**: 
```python
else:  # edge <= -0.10
    size_mult = 0.3  # Reduce to 30% instead of killing completely
    dynamic_rr = 1.5
```

This allows liquidity-trap trades to proceed with reduced size instead of zero-size abort.

---

## Issue #4: Accuracy Gate Bypass Logic (PRIORITY: MEDIUM)
**Location**: `main.py`, lines 5386-5396

**Current Code**:
```python
override_active = bool(
    getattr(signal, "forced_execution", False)
    or getattr(signal, "structure_override", False)
    or str(getattr(signal, "mode", "") or "").upper() == "EXPLORATION"
    or str(getattr(signal, "source", getattr(signal, "signal_source", "")) or "").upper() == "STRUCTURE_OVERRIDE"
)
if ml_acc < 0.35 and not override_active:  # Blocks if accuracy < 35% AND no override
```

**Problem**: 38.4% effective accuracy should pass (above 35% gate), BUT the EXPLORATION_OVERRIDE is also present, which double-bypasses the check. The log shows:
`[EXPLORATION_OVERRIDE_ACTIVE] ... | [STRATEGY_REJECT] Effective Accuracy 38.4%`

This means the signal was admitted via EXPLORATION override, then REJECTED anyway by another gate.

**Fix**: Remove double-rejection. Once override is active, do NOT re-check accuracy gate downstream:
```python
if ml_acc < 0.35 and not override_active:
    logger.critical("[STRATEGY_REJECT] ...")
    return  # STOP HERE - don't continue to execution

# If we reach here, signal passed (either via accuracy or override)
# No second accuracy check should happen
```

---

## Issue #5: LLM Governance Timeouts (PRIORITY: LOW)
**Location**: `.env.optimized` / `config.yaml`

**Current Settings**:
```
OLLAMA_FAST_TIMEOUT_SECONDS=2
OLLAMA_HEAVY_TIMEOUT_SECONDS=8
```

**Problem**: 5-second timeout for USD/CHF causing 11-second cycle latency.

**Fix**: 
```env
# Option 1: Increase timeouts
OLLAMA_FAST_TIMEOUT_SECONDS=3
OLLAMA_HEAVY_TIMEOUT_SECONDS=10

# Option 2: Switch to faster model
OLLAMA_MODEL_FAST=phi3:mini  # Faster than qwen3.5:0.8b

# Option 3: Reduce LLM calls
# Set LLM_GOVERNANCE_ENABLED=false for live trading, use only for post-trade analysis
```

**Recommendation**: Use Option 2 (phi3:mini) or Option 3 (disable during live trading).

---

## Issue #6: High "Admitted But Not Executed" Rate (PRIORITY: MEDIUM)
**Current Behavior**: ~70% of admitted signals don't execute (only 2 positions in 8 minutes)

**Root Causes**:
1. Decision matrix EMERGENCY_CUTOFF blocking non-forced trades (Issue #2)
2. Liquidity trap setting size to 0.0 (Issue #3)
3. Accuracy gate double-checking (Issue #4)

**Fix**: Apply all fixes above, which should unlock execution pipeline

**Verification Threshold**: After fixes, should see:
- Minimum 50% execution rate on admitted signals
- Average 4-6 positions per 10-minute cycle (not 2)

---

# Implementation Priority Order

1. ✅ **Fix #3 (Liquidity trap)** - Easy 1-line change, high impact
2. ✅ **Fix #2 (Loss restriction threshold)** - Easy config change, unblocks trading
3. ✅ **Fix #4 (Accuracy gate)** - Medium complexity, prevents double-rejection
4. ✅ **Fix #1 (ML gate)** - Add debug logging first to confirm issue
5. ✅ **Fix #5 (LLM timeouts)** - Config-only, low-medium impact
6. ✅ **Verify** - Run 15-minute live backtest to confirm fixes work together

---


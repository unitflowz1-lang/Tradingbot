# Advanced Trading Controls Implementation Guide

## Overview
This document describes the implementation of three critical advanced trading control features for the bot's core RL Trading system. These features are designed to prevent model degradation, eliminate false confidence signals, and kill the bootstrap/exploration exploitation loophole.

---

## Feature #1: Forced Learning Window

### Purpose
Prevent the bot from trading during model accuracy collapse. If accuracy drops below 45% for 20 consecutive cycles, the bot enters a 60-minute "Forced Learning Window" where:
- All live trading signals are BLOCKED for that symbol
- The bot is forced to run backtesting or model retraining on the last 500 bars
- Normal trading resumes only after the learning window expires

### Implementation Details

**Data Structures Added to `TradeAdmissionController`:**
```python
# Maps symbol -> learning window state
self.symbol_learning_state: Dict[str, Dict[str, Any]] = {}
self.LOW_ACCURACY_THRESHOLD = 0.45  # 45%
self.LOW_ACCURACY_CONSECUTIVE_CYCLES = 20
self.LEARNING_WINDOW_DURATION_MINUTES = 60
```

**Key Methods:**
- `update_accuracy_tracking(symbol, current_accuracy)` - Called every cycle to track accuracy
  - Returns `"LEARNING_WINDOW_TRIGGERED"` when threshold is hit
  - Returns `"LEARNING_WINDOW_ACTIVE"` when window is active
  
- `is_in_forced_learning_window(symbol)` - Check if symbol is currently blocked

**Integration Points:**
1. **In `evaluate_admission()`**: 
   - First check after cooldown gates
   - Calls `update_accuracy_tracking()` to monitor accuracy
   - Returns `REJECTED` with reason `"FORCED_LEARNING_WINDOW"` if active
   - Blocks ALL trades regardless of confidence or expectancy

2. **In `ModelTrainer.force_train_on_historical_bars()`**:
   - Called during the 60-minute window
   - Trains on last 500 bars only
   - Logs training metrics upon completion
   - Auto-saves the retrained model

### Usage

**Monitoring in Bot Cycle:**
```python
# Each cycle, call this to update tracking
learning_status = admission_controller.update_accuracy_tracking(
    symbol="EURUSD", 
    current_accuracy=0.42  # Current ML accuracy
)

if learning_status == "LEARNING_WINDOW_TRIGGERED":
    logger.critical(f"Triggered for {symbol}")
    # Time to force backtesting on 500 bars
    trainer.force_train_on_historical_bars(
        X_historical=last_500_bars_features,
        y_historical=last_500_bars_labels,
        symbol=symbol,
        max_bars=500
    )

# Check admission (will return REJECTED during window)
admission = admission_controller.evaluate_admission(
    symbol="EURUSD",
    ...
    ml_accuracy=0.42,
    ...
)
```

### Expected Behavior

**Scenario:**
- Cycle 1-19: Accuracy stays at 0.42 (< 45%), counter increments
- Cycle 20: Counter hits 20, learning window triggers
- Cycle 20-79: All new signals REJECTED, logs show `FORCED_LEARNING_WINDOW_ACTIVE`
- Cycle 80: Window expires, trading resumes

**Log Messages:**
```
[FORCED_LEARNING_WINDOW_TRIGGERED] EURUSD | Accuracy 42.0% < 45% for 20 consecutive cycles. 
TRADING BLOCKED for 60 minutes. Bot will force backtesting/training on last 500 bars.

[FORCED_LEARNING_WINDOW_ACTIVE] EURUSD | Still in learning window. Trading BLOCKED for 58.3 more minutes.

[FORCED_TRAINING_START] EURUSD | Training on 500 historical bars
[FORCED_TRAINING_COMPLETE] EURUSD | Test Accuracy: 65.3% | Precision: 68% | Recall: 64%
```

---

## Feature #2: Dynamic Thresholding (Rolling Adaptive Confidence Threshold)

### Purpose
Replace the static 0.42 confidence threshold with a rolling adaptive threshold based on:
1. Mean confidence of the last 10 ACCEPTED trades
2. Progressive lowering during stagnation (100+ cycles without accepted trades)

This eliminates the "all-or-nothing" confidence gate and allows the bot to gradually recover from a stagnation trap.

### Implementation Details

**Data Structures Added:**
```python
# Track accepted trade confidences (rolling window)
self.symbol_accepted_trades: Dict[str, deque] = {}  # Last 10 confidences
self.ACCEPTED_TRADES_LOOKBACK = 10

# Track stagnation cycles (no accepted trades)
self.symbol_stagnation_count: Dict[str, int] = {}
self.STAGNATION_CYCLE_THRESHOLD = 100  # Start threshold reduction after 100 cycles
self.THRESHOLD_REDUCTION_PER_CYCLE = 0.01  # Reduce by 0.01 per cycle

# Adaptive threshold per symbol (overrides static 0.42)
self.symbol_adaptive_confidence_threshold: Dict[str, float] = {}
```

**Key Methods:**

1. **`register_accepted_trade(symbol, confidence)`**
   - Called when a trade is ADMITTED (not rejected)
   - Adds confidence to rolling 10-trade window
   - Calculates new rolling mean
   - Resets stagnation counter
   - Updates adaptive threshold = rolling_mean (min 0.42)

2. **`update_stagnation_counter(symbol)`**
   - Called EVERY CYCLE regardless of outcome
   - Tracks cycles without accepted trades
   - After 100 cycles: `new_threshold = current_threshold - (cycles_beyond_100 * 0.01)`
   - Returns `"STAGNATION_THRESHOLD_REDUCED"` when reduction occurs
   - Never allows threshold to drop below 0.05

3. **`get_adaptive_confidence_threshold(symbol)`**
   - Returns the current adaptive threshold for a symbol
   - Falls back to 0.42 if no trades accepted yet

### Integration into evaluate_admission()

In `evaluate_admission()`, after resolving the base threshold:
```python
# Get adaptive threshold based on accepted trades
adaptive_threshold = self.get_adaptive_confidence_threshold(symbol)

# Use the more conservative of the two
effective_min_confidence_threshold = max(effective_min_confidence_threshold, adaptive_threshold)
```

### Usage Example

**Cycle Flow:**
```python
# Cycle 1-10: No accepted trades, adaptive_threshold = 0.42 (default)
symbol_stagnation_count[symbol] = 1..10

# Cycle 101: Stagnation triggers
update_stagnation_counter(symbol)
# Then: threshold = 0.42 - (1 * 0.01) = 0.41

# At cycle 110: No trade accepted yet
update_stagnation_counter(symbol)
# Then: threshold = 0.42 - (10 * 0.01) = 0.32

# Cycle 150: Finally a trade is accepted with confidence 0.55
register_accepted_trade(symbol, 0.55)
# Rolling mean = 0.55 (only 1 trade so far)
# adaptive_threshold = 0.55
# stagnation_count reset to 0

# Cycle 160: Another trade accepted with confidence 0.48
register_accepted_trade(symbol, 0.48)
# Rolling mean = (0.55 + 0.48) / 2 = 0.515
# adaptive_threshold = 0.515
```

### Expected Behavior

**Phase 1 - Healthy Trading:**
- 11 trades accepted with confidences: [0.65, 0.70, 0.68, 0.72, 0.66, 0.71, 0.69, 0.64, 0.73, 0.67]
- Rolling mean = 0.685
- Adaptive threshold = 0.685
- Only confidence >= 0.685 admitted

**Phase 2 - Stagnation Trap (100+ cycles no wins):**
- Cycle 101: threshold drops to 0.41
- Cycle 110: threshold drops to 0.32
- Cycle 120: threshold drops to 0.22
- First trade finally accepted at cycle 135 (confidence 0.50)
- Stagnation counter resets, threshold becomes 0.50
- Trading resumes with confidence gating at 0.50

### Log Messages
```
[DYNAMIC_THRESHOLD] EURUSD | Accepted trade confidence: 0.68 | 
Rolling mean (last 10 trades): 0.685 | Adaptive threshold: 0.685

[STAGNATION_TRAP_RECOVERY] EURUSD | No trades accepted for 110 cycles (threshold: 100).
Progressively lowering confidence threshold: 0.42 → 0.32 (reduction: 0.10)
```

---

## Feature #3: Kill Bootstrap Bypass

### Purpose
Completely disable exploration overrides when the model is in bootstrap mode. This prevents:
- Fail-forward trading on untrained models
- Spamming logs with "EXPLORATION_OVERRIDE_ACTIVE" despite poor accuracy
- Trading with < 45% accuracy just because technical-only or cold-start mode is active

### Implementation Details

**Bootstrap Mode Detection:**
A symbol is in bootstrap mode if ANY of:
```python
technical_only_mode = True  # Macro data unavailable
low_accuracy_cycles > 10    # Chronic low accuracy
0 < bot_cycle_count < 100   # Less than 100 cycles of trading history
trade_count < 100           # Less than 100 historical trades
```

**The Logic:**
When bootstrap mode is active AND confidence < 60% gate:
1. Set `bootstrap_override_disabled = True`
2. Prevent ANY exploration override from working
3. Return signal to `evaluate_trade_permission()` to reject it
4. Bot goes to IDLE mode (no spammy rejected logs, just quiet hold)

### Code Changes

**In `evaluate_admission()`:**
```python
bootstrap_override_disabled = False
if bootstrap_mode_active:
    if float(raw_ml_confidence or 0.0) < effective_min_confidence_threshold:
        bootstrap_override_disabled = True
        logger.warning(
            "[BOOTSTRAP_NO_OVERRIDE] %s | Bootstrap mode active + confidence %.2f < gate %.2f | "
            "Exploration override DISABLED. Model must earn confidence 60%% legitimately.",
            symbol, float(raw_ml_confidence or 0.0), effective_min_confidence_threshold
        )
```

**In `evaluate_trade_permission()`:**
```python
# NEW PARAMETER added
def evaluate_trade_permission(
    self,
    ...
    bootstrap_override_disabled: bool = False,
) -> TradePermissionDecision:
    
    # At the start, check if bootstrap disabled
    if bootstrap_override_disabled and exploration_active:
        logger.warning(
            "[BOOTSTRAP_OVERRIDE_DISABLED] %s | Bootstrap mode prevents exploration override. "
            "Returning permission denied to force IDLE mode.",
            symbol,
        )
        return TradePermissionDecision(
            allowed=False,
            score=0.0,
            reason="BOOTSTRAP_OVERRIDE_DISABLED",
            failed_filter="BOOTSTRAP_MODE",
        )
```

### Behavior Changes

**Before (Old System - Broken):**
```
Cycle 45: technical_only_mode=True, confidence=0.38 (< 60% gate)
Result: STILL TRADED because "exploration override active"
Logs: "[EXPLORATION_OVERRIDE_ACTIVE] EURUSD | Exploration path admitted and downstream accuracy gates skipped"
Problem: Actually no good signals, just spamming bad trades
```

**After (New System - Fixed):**
```
Cycle 45: technical_only_mode=True, confidence=0.38 (< 60% gate)
Result: REJECTED
Logs: "[BOOTSTRAP_NO_OVERRIDE] EURUSD | Bootstrap mode active + confidence 0.38 < gate 0.60"
       "[BOOTSTRAP_OVERRIDE_DISABLED] EURUSD | Bootstrap mode prevents exploration override"
Status: IDLE (quiet wait for model to recover)
```

### Expected Behavior

**Cold Start (< 100 historical trades):**
- Cycle 1: confidence=0.35 → REJECTED (no override allowed)
- Cycle 1: confidence=0.65 → ADMITTED (meets 60% + bootstrap gate is high)
- After 100 trades: bootstrap mode deactivated, normal rules apply

**Low Accuracy Recovery (10+ low accuracy cycles):**
- Cycle 1-10: 50% accuracy → confidence gate remains 0.60
- Cycle 11+: low_accuracy_cycles > 10 → bootstrap mode triggers
- If confidence < 0.60: REJECTION, no exploration override
- Exploration override ONLY works if confidence >= 0.60

**Technical Only Mode (Macro unavailable):**
- Macro data stale → technical_only_mode=true
- If confidence < 0.60: Exploration override DISABLED
- Bot awaits macro data recovery or confidence improvement

### Log Messages
```
[BOOTSTRAP_COOLDOWN] EURUSD | Cold-start (50 trades). 
HC-Adaptive: Confidence gate ENFORCED at 60%% — no fail-forward trading.

[BOOTSTRAP_NO_OVERRIDE] EURUSD | Bootstrap mode active + confidence 0.35 < gate 0.60 | 
Exploration override DISABLED. Model must earn confidence 60%% legitimately.

[BOOTSTRAP_OVERRIDE_DISABLED] EURUSD | Bootstrap mode prevents exploration override. 
Returning permission denied to force IDLE mode.
```

---

## Integration Checklist

### TradeAdmissionController Modifications
- [x] Added learning window state tracking
- [x] Added `update_accuracy_tracking(symbol, accuracy)` method
- [x] Added `is_in_forced_learning_window(symbol)` method
- [x] Added forced learning window check in `evaluate_admission()`
- [x] Added accepted trades tracking with rolling mean
- [x] Added `register_accepted_trade(symbol, confidence)` method
- [x] Added `update_stagnation_counter(symbol)` method
- [x] Added `get_adaptive_confidence_threshold(symbol)` method
- [x] Integrated adaptive threshold into `evaluate_admission()`
- [x] Added bootstrap_override_disabled logic to prevent exploration override
- [x] Added bootstrap_override_disabled parameter to `evaluate_trade_permission()`
- [x] Added check to disable exploration override during bootstrap

### ModelTrainer Modifications
- [x] Added `force_train_on_historical_bars(X, y, symbol, max_bars=500)` method
- [x] Implemented proper train/val/test split for small dataset
- [x] Added comprehensive logging of training results
- [x] Auto-save model after forced training

### Integration Points (Where to Call)

**Every Bot Cycle:**
```python
# 1. Update learning window and stagnation tracking
learning_status = admission_controller.update_accuracy_tracking(
    symbol=symbol,
    current_accuracy=ml_accuracy
)

# 2. Update stagnation counter (call regardless of outcome)
stagnation_status = admission_controller.update_stagnation_counter(symbol)

# 3. When trade is ADMITTED, register it
if admission_decision.admitted:
    admission_controller.register_accepted_trade(
        symbol=symbol,
        confidence=raw_ml_confidence
    )
    
# 4. Check forced learning window and trigger training if needed
if learning_status == "LEARNING_WINDOW_TRIGGERED":
    metrics = model_trainer.force_train_on_historical_bars(
        X_historical=last_500_bars,
        y_historical=last_500_labels,
        symbol=symbol,
        max_bars=500
    )
```

---

## Monitoring & Debugging

### Key Metrics to Monitor

1. **Learning Window Activations:**
   - Count how often a symbol enters learning window (should be rare)
   - Duration of each window (should be 60 minutes)
   - Whether accuracy recovers after training

2. **Adaptive Threshold Adjustments:**
   - How many symbols have rolling mean thresholds > 0.42
   - Stagnation entrances (100+ cycles without trades)
   - Threshold recovery after stagnation breaks

3. **Bootstrap Override Blocks:**
   - Count rejected trades due to `BOOTSTRAP_OVERRIDE_DISABLED`
   - Compare to old system's false "exploration override" trades
   - Monitor bootstrap mode duration (should decrease over time)

### Debug Logging

Enable debug logging to see threshold calculations:
```python
# In evaluate_admission()
logger.debug(
    "[DYNAMIC_THRESHOLD_APPLIED] %s | "
    "Base: %.2f | Adaptive: %.2f | Final: %.2f",
    symbol, base_thresh, adaptive_thresh, final_thresh
)
```

---

## FAQ

**Q: What if a symbol gets stuck in learning window?**
A: The window auto-expires after 60 minutes. If accuracy doesn't improve, it will re-trigger. Use `force_train_on_historical_bars()` with different training parameters or more data.

**Q: Can I customize the thresholds?**
A: Yes! Modify these constants in `TradeAdmissionController.__init__()`:
```python
self.LOW_ACCURACY_THRESHOLD = 0.45  # Change 45%
self.LOW_ACCURACY_CONSECUTIVE_CYCLES = 20  # Change 20 cycles
self.LEARNING_WINDOW_DURATION_MINUTES = 60  # Change 60 minutes
self.STAGNATION_CYCLE_THRESHOLD = 100  # Change 100 cycles
self.THRESHOLD_REDUCTION_PER_CYCLE = 0.01  # Change 0.01 reduction
```

**Q: What's the minimum adaptive threshold?**
A: 0.05 (5% confidence). Prevents system from becoming too permissive during stagnation.

**Q: How often is adaptive threshold updated?**
A: Only when `register_accepted_trade()` is called (i.e., when a trade is ADMITTED).

**Q: Does bootstrap mode ever auto-exit?**
A: Yes!
- When trade_count >= 100: cold_start deactivates
- When low_accuracy_cycles <= 10: recovery mode deactivates
- When bot_cycle_count >= 100: young bot mode deactivates
- When technical_only_mode = False: macro mode reactivates

---

## Performance Impact

These features are designed to be **zero-impact** on normal operations:
- Learning window checks: O(1) dict lookup
- Stagnation counter: O(1) increment
- Adaptive threshold: O(10) deque mean calculation
- Bootstrap check: O(1) boolean logic

**Forced training only runs during explicitly triggered learning windows** (rare, 60-minute duration max).

---

## Testing Recommendations

1. **Unit Test Learning Window:**
   - Create 20-cycle loop with accuracy < 45%
   - Verify window triggers on cycle 20
   - Verify trading blocked during window
   - Verify window expires after 60 minutes

2. **Unit Test Adaptive Threshold:**
   - Register 10 trades with confidences
   - Verify rolling mean is calculated correctly
   - Force 100+ stagnation cycles
   - Verify threshold reduces by 0.01 per cycle

3. **Unit Test Bootstrap Bypass:**
   - Set cold_start_active = True, confidence = 0.35
   - Verify exploration override is disabled
   - Set confidence = 0.65
   - Verify trade is admitted

4. **Integration Test:**
   - Run full backtest with all 3 features enabled
   - Verify no regression vs baseline
   - Check log messages for clarity


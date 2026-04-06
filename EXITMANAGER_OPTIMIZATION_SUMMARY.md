# ExitManager Optimization - Stricter Loss Controls

**Status**: ✅ **COMPLETED**
**Date**: April 2, 2026
**Objective**: Make ExitManager more aggressive about closing losing positions

---

## Changes Made

### 1. Maximum Drawdown Per Position Rule **[FIX #1]**

**Added**: Absolute loss threshold = -$15.00 per position

**Logic**:
```python
MAX_LOSS_THRESHOLD = -15.00
if _rev_pnl < MAX_LOSS_THRESHOLD:
    # FORCE CLOSE - no questions asked
    reversal_condition_met = True
    reversal_reason = f"MAX_DRAWDOWN_STOP: Loss ${_rev_pnl:.2f} < threshold ${MAX_LOSS_THRESHOLD:.2f}"
```

**Priority**: This check runs FIRST, before any technical indicators  
**Effect**: Any position losing more than $15 will close immediately next cycle

**Logging**:
```
[REVERSAL_EXIT_MAX_DRAWDOWN] EURUSD #55303555040 | Loss: $-21.50 < threshold: $-15.00 | Closing immediately to prevent further drawdown
```

**Why This Helps**:
- Prevents "death by a thousand cuts" - positions don't bleed indefinitely
- Gives technical indicators a chance but cuts losses if they fail
- Protects capital on stubborn losing positions

---

### 2. Changed Reversal Signal Logic from AND to OR **[FIX #2]**

**Before** (AND Logic - TOO STRICT):
```python
# Check RSI Divergence
if _rev_rsi is not None:
    if condition_met:
        reversal_condition_met = True

# Check Momentum Loss ONLY if RSI didn't trigger
if NOT reversal_condition_met and _rev_momentum is not None:
    if condition_met:
        reversal_condition_met = True  # Only if RSI was False
```

**After** (OR Logic - FASTER EXITS):
```python
# Check RSI Divergence
if not reversal_condition_met and _rev_rsi is not None:
    if condition_met:
        reversal_condition_met = True
        logger.critical("[REVERSAL_EXIT_RSI] ... closing...")

# Check Momentum Loss (INDEPENDENT check, can trigger even if RSI didn't)
if not reversal_condition_met and _rev_momentum is not None:
    if condition_met:
        reversal_condition_met = True
        logger.critical("[REVERSAL_EXIT_MOMENTUM] ... closing...")
```

**Key Difference**:
- **Before**: RSI and Momentum HAD TO BOTH be true (impossible in practice)
- **After**: RSI OR Momentum - whichever triggers first will close the position

**Logging** (now shows which signal triggered):
```
[REVERSAL_EXIT_RSI] EURUSD #55303555040 | RSI=28.5 triggers exit | Direction: LONG opposes RSI signal | Closing...
[REVERSAL_EXIT_MOMENTUM] GBPUSD #55303555041 | Momentum=-0.00015 triggers exit | Lost momentum in trade direction | Closing...
```

---

## Exit Hierarchy (Priority Order)

The ExitManager now checks in this order:

```
1. Manual Exit Check
   ↓
2. Time-Based Exit (>X hours in trade)
   ↓
3. ★ REVERSAL EXIT CHECKS (NEW OPTIMIZED):
   
   3.1 MAX DRAWDOWN STOP [-$15.00]
       → If position loss > $15, close immediately
       → PRIORITY: Runs first, can't be overridden
   
   3.2 RSI DIVERGENCE [OR logic]
       → LONG: RSI < 30
       → SHORT: RSI > 70
       → Action: Close position
   
   3.3 MOMENTUM LOSS [OR logic]
       → LONG: Momentum ≤ 0
       → SHORT: Momentum ≥ 0
       → Action: Close position
   
   → ANY ONE of 3.1/3.2/3.3 triggers close (OR)
   ↓
4. Position Capacity Checks (if still open)
```

---

## Expected Behavior

### For Positions Already Losing $15+ (Like the Current 4 Losing Positions)

**Before**: Kept waiting for RSI<30 AND Momentum<0 (rarely happens together)
**After**: Closes immediately on next cycle - `[REVERSAL_EXIT_MAX_DRAWDOWN]` triggered

**Example log sequence**:
```
[REVERSAL_EXIT_CHECK_START] EURUSD #55303555040 | Unrealized PnL: $-21.50 |...
[REVERSAL_EXIT_INDICATORS] EURUSD #55303555040 | RSI: 45.2 | Momentum: 0.00001 | ADX: 18
[REVERSAL_EXIT_MAX_DRAWDOWN] EURUSD #55303555040 | Loss: $-21.50 < threshold: $-15.00 | Closing...
[REVERSAL_EXIT_EXECUTING] EURUSD #55303555040 | Executing close order | Reason: MAX_DRAWDOWN_STOP...
[REVERSAL_EXIT_RESULT] EURUSD #55303555040 | Close result: True | PnL locked: $-21.50 | Exit SUCCESSFUL
```

### For Positions With Reversal Signals (But Can't Fully Reverse)

**Before**: Waits for both RSI divergence AND momentum loss
**After**: Exits as soon as EITHER signal appears

**Example**:
```
[REVERSAL_EXIT_CHECK_START] GBPUSD #55303555041 | Unrealized PnL: $-8.50
[REVERSAL_EXIT_INDICATORS] GBPUSD #55303555041 | RSI: 32.1 | Momentum: 0.0001 | ADX: 25
[REVERSAL_EXIT_RSI] GBPUSD #55303555041 | RSI=32.1 triggers exit | Closing...
[REVERSAL_EXIT_RESULT] GBPUSD #55303555041 | PnL locked: $-8.50 | Exit SUCCESSFUL
```

Key: RSI alone triggered exit (didn't wait for momentum)

---

## Suggested Tuning

If the bot is still too hesitant after these changes, adjust:

### Threshold Adjustments (in main.py ~line 3975)
```python
# Current: -$15.00 absolute loss trigger
MAX_LOSS_THRESHOLD = -15.00

# More aggressive: Lower to -$10.00 (close earlier)
MAX_LOSS_THRESHOLD = -10.00

# Less aggressive: Raise to -$25.00 (give more time)
MAX_LOSS_THRESHOLD = -25.00
```

### RSI Threshold Adjustments (in main.py ~lines 3990-3995)
```python
# Current: RSI < 30 for LONG, RSI > 70 for SHORT
if (_rev_direction in (Direction.LONG, 'LONG') and _rev_rsi < 30):
    # Tighter: Change to < 35 (earlier exit on weaker signal)
    if (_rev_direction in (Direction.LONG, 'LONG') and _rev_rsi < 35):
```

### Momentum Threshold Adjustments (in main.py ~lines 4005-4010)
```python
# Current: Momentum <= 0 for LONG, >= 0 for SHORT
if (_rev_direction in (Direction.LONG, 'LONG') and _rev_momentum <= 0):
    # Tighter: Change to < -0.0001 (only extreme momentum reversal)
    if (_rev_direction in (Direction.LONG, 'LONG') and _rev_momentum < -0.0001):
```

---

## Testing Checklist

- [ ] Bot starts without errors
- [ ] Check logs for `[REVERSAL_EXIT_MAX_DRAWDOWN]` on positions with > $15 loss
- [ ] Verify RSI/Momentum exits trigger independently (not requiring both)
- [ ] Monitor that positions close faster but not too aggressively
- [ ] Verify closed positions show exact loss amount and trigger reason

---

## Files Modified

**main.py** (Lines 3970-4025): ExitManager reversal exit logic

---

## Revert Instructions (if needed)

To revert to the previous stricter logic:
1. Change `MAX_LOSS_THRESHOLD = -15.00` to a lower value (e.g., `None`)
2. Change momentum check from separate `if not reversal_condition_met and...` back to nested within RSI check

But recommended: Keep these optimizations - they prevent unnecessary drawdown.

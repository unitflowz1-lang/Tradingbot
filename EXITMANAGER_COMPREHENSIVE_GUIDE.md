# ExitManager - Comprehensive Safety Valves Implementation Guide

**Status**: ✅ **COMPLETED**
**Date**: April 2, 2026
**Version**: 1.0

---

## Overview

The **ExitManager** is a new unified exit control system that prevents positions from bleeding indefinitely. It replaces scattered exit logic with three intelligent safety valves:

1. **Hard Loss Threshold** (-$15.00 default) - Immediate force-close
2. **Time-Based Stagnation** (40 bars default) - Free up capital from stuck positions
3. **Reversal Exit** - Close on technical reversal signals (OR logic)

---

## Architecture

### File Structure

```
src/trading/
├── exit_manager.py          ← NEW: Core safety valve logic
├── profit_protection_module.py  (unchanged: still handles post-entry management)
└── main.py                  ← UPDATED: Integrated exit checks into main loop
```

### Core Classes

**ExitManager** - Main controller
- Checks all exit conditions in priority order
- Returns: (should_exit, reason_string, signal_type)
- Uses the same secure close function as profit manager

**ExitManagerConfig** - Configuration dataclass
- All settings can be changed via environment variables
- Allows dynamic threshold adjustments at runtime

**ExitSignalType** - Enum for exit signal classification
- TIME_BASED_STAGNATION
- HARD_LOSS_THRESHOLD
- REVERSAL_RSI
- REVERSAL_MOMENTUM
- REVERSAL_PRICE_ACTION

---

## Safety Valve #1: Hard Loss Threshold

### Purpose
Prevents positions from losing indefinitely while waiting for perfect reversal signals.

### Configuration
```python
# Default: -$15.00
# Environment variable: EXIT_MANAGER_MAX_LOSS_USD=-15.00

# In code:
enable_hard_loss_stop: bool = True
max_loss_threshold_usd: float = -15.00
```

### Logic
```
IF position.unrealized_pnl < -$15.00:
    FORCE CLOSE immediately
    NO technical indicator check
    NO confirmation required
ELSE:
    Continue to next safety valve
```

### Log Output
```
[HARD_LOSS_STOP] EURUSD #55303555040 | Loss: $-21.50 < threshold: $-15.00 | FORCE CLOSE
```

### When to Adjust
- Increase (e.g., -$25.00) if you want to give positions more time to recover
- Decrease (e.g., -$10.00) for more aggressive risk management
- Set to 0 to disable hard loss stops

---

## Safety Valve #2: Time-Based Stagnation

### Purpose
Closes positions that have been held too long without profit, freeing capital for better opportunities.

### Configuration
```python
# Default: 40 bars at 60-minute timeframe (2,400 minutes = 40 hours)
# Environment variables:
EXIT_MANAGER_STAGNATION_BARS=40         # Number of bars (default 40)
EXIT_MANAGER_BAR_MINUTES=60             # Minutes per bar (60 for 1H, 240 for 4H)

# In code:
enable_time_based_exit: bool = True
stagnation_limit_bars: int = 40
bar_duration_minutes: int = 60
```

### Logic
```
time_held = current_time - position.opened_at
bars_open = time_held / bar_duration_minutes

IF bars_open >= 40:
    FORCE CLOSE
    Frees capital from stagnant positions
ELSE:
    Continue to next safety valve
```

### Examples
- **1-hour bars**: 40 bars = 40 hours = 1.67 days
- **4-hour bars**: 40 bars = 160 hours = 6.67 days
- **15-minute bars**: 40 bars = 10 hours

### Log Output
```
[TIME_BASED_STOP] GBPUSD #55303555041 | Held: 45.3 bars >= 40.0 limit | FORCE CLOSE
```

### When to Adjust
- Increase (e.g., 60 bars) if positions need more time to develop
- Decrease (e.g., 20 bars) for faster capital turnover
- Change bar_duration if using different timeframes

---

## Safety Valve #3: Reversal Exit (OR Logic)

### Purpose
Closes positions showing reversal patterns, using more flexible OR logic instead of strict AND requirements.

### Configuration
```python
# Default: Require 2 of 3 conditions (any pair can trigger)
# Environment variables:
EXIT_MANAGER_REVERSAL=true
EXIT_MANAGER_REVERSAL_CONDITIONS=2      # 1, 2, or 3
EXIT_MANAGER_RSI_LONG=30.0              # LONG reversal threshold
EXIT_MANAGER_RSI_SHORT=70.0             # SHORT reversal threshold

# In code:
enable_reversal_exit: bool = True
reversal_conditions_required: int = 2    # 1=any single, 2=any pair, 3=all three
rsi_threshold_long: float = 30.0
rsi_threshold_short: float = 70.0
momentum_threshold: float = 0.0
enable_price_action_check: bool = True
```

### Three Reversal Conditions

**Condition #1: RSI Divergence**
- LONG: RSI < 30 (oversold → bearish divergence)
- SHORT: RSI > 70 (overbought → bullish divergence)
- Indicates: Price reversal likely

**Condition #2: Momentum Loss**
- LONG: Momentum ≤ 0 (upside momentum gone)
- SHORT: Momentum ≥ 0 (downside momentum gone)
- Indicates: Directional bias weakening

**Condition #3: Price Action**
- LONG: Recent bearish candles (close < open)
- SHORT: Recent bullish candles (close > open)
- Indicates: Rejection of move direction

### OR Logic Examples

**Scenario 1: 2 conditions (default)**
```
Position: LONG EURUSD, $12 profit, held 2 days

Current state:
- RSI = 28 (< 30) ✓ Bearish divergence
- Momentum = 0.0001 (> 0) ✗ Still positive
- Price action = 1 bearish candle

Triggered conditions: 1/3

Decision: HOLD (need 2 conditions)
```

**Scenario 2: 2 conditions (default) - EXITS**
```
Position: LONG EURUSD, $8 profit

Current state:
- RSI = 28 (< 30) ✓ Bearish divergence
- Momentum = -0.00005 (< 0) ✓ Momentum lost
- Price action = 2 bearish candles

Triggered conditions: 2/3 (meets requirement)

Decision: CLOSE ✓ (any pair of conditions triggers exit)
```

### OR Logic Behavior
- `reversal_conditions_required=1`: Exit if ANY SINGLE signal (RSI OR Momentum OR Price Action)
- `reversal_conditions_required=2`: Exit if ANY PAIR of signals (default - more flexible than AND)
- `reversal_conditions_required=3`: Exit if ALL THREE signals (strict, rarely triggers)

### Log Output
```
[REVERSAL_EXIT] EURUSD #55303555040 | Triggered: 2/3 conditions | PnL: $12.50 | 
RSI=28.1 < 30.0 (LONG reversal) + Momentum=-0.00005 <= 0.0 (LONG lost) | CLOSING
```

---

## Integration with Main Bot

### Location in Code
**File**: `main.py` (lines ~3985-4055)

**When it runs**:
- Every cycle in the main event loop
- After time-based exits check (trade_manager.check_time_exit)
- Before position capacity checks

**Integration workflow**:
```
Main Loop Cycle
├─ Check Manual Administrative Exits
├─ Check Time-Based Exits (legacy trade_manager)
├─ [NEW] Check ExitManager Safety Valves
│  ├─ Hard Loss Threshold
│  ├─ Time-Based Stagnation
│  └─ Reversal Exit (OR logic)
├─ Check Profit Management (breakeven, trailing, scale-out)
└─ Continue to next position/signal generation
```

### Secure Close Function
All exits use the same secure close path:
```python
# 1. Close position with broker
await broker.close_position(position_id)

# 2. Update position registry
position_manager.shadow_positions.pop(position_id, None)

# 3. Update profit tracking
profit_mgmt.close_tracking(position_id)

# 4. Log the exit
logger.critical("[EXIT_MANAGER_RESULT] ... PnL locked: $X.XX")
```

This ensures:
- Registry stays synchronized with MT5
- Profit tracking stays accurate
- All logs are generated consistently
- No orphaned shadow positions

---

## Runtime Configuration

### Environment Variables
All settings can be controlled via environment variables:

```bash
# Safety Valve 1: Hard Loss
export EXIT_MANAGER_MAX_LOSS_USD=-15.00

# Safety Valve 2: Time-Based
export EXIT_MANAGER_STAGNATION_BARS=40
export EXIT_MANAGER_BAR_MINUTES=60

# Safety Valve 3: Reversal
export EXIT_MANAGER_REVERSAL_CONDITIONS=2
export EXIT_MANAGER_RSI_LONG=30.0
export EXIT_MANAGER_RSI_SHORT=70.0

# Price Action
export EXIT_MANAGER_PRICE_ACTION=true
```

### Dynamic Adjustment at Runtime
```python
# Change stagnation limit
exit_manager.set_stagnation_limit(50)

# Change max loss threshold
exit_manager.set_max_loss_threshold(-20.00)

# Change reversal condition count
exit_manager.set_reversal_conditions_required(1)
```

---

## Behavior Examples

### Example 1: Position Hits Max Loss

**Setup**:
- Position: SHORT GBPUSD, entry: 1.2500
- Current price: 1.2520 (unrealized loss: -$20.00)
- Held for: 8 bars
- RSI: 55
- Momentum: -0.0001

**Exit Check**:
1. Hard Loss: $-20.00 < $-15.00 ✓ TRIGGERED
2. Time-Based: 8 bars < 40 bars ✗
3. Reversal: 0/3 conditions ✗

**Outcome**:
- **CLOSED** immediately via Hard Loss Threshold
- Log: `[HARD_LOSS_STOP] GBPUSD #... | Loss: $-20.00 < threshold: $-15.00 | FORCE CLOSE`
- PnL locked: -$20.00
- Capital freed for new signals

### Example 2: Position Stagnates Too Long

**Setup**:
- Position: LONG EURUSD, entry: 1.0850
- Current price: 1.0851 (unrealized gain: +$1.00)
- Held for: 43 bars (43 hours)
- RSI: 48
- Momentum: 0.00001

**Exit Check**:
1. Hard Loss: $+1.00 > -$15.00 ✗
2. Time-Based: 43 bars >= 40 bars ✓ TRIGGERED
3. Reversal: N/A (already triggered)

**Outcome**:
- **CLOSED** due to stagnation
- Log: `[TIME_BASED_STOP] EURUSD #... | Held: 43.0 bars >= 40.0 limit | FORCE CLOSE`
- Reason: Free capital from position that isn't moving
- PnL locked: +$1.00

### Example 3: Reversal Signals Trigger (OR Logic)

**Setup**:
- Position: LONG EURUSD, entry: 1.0850
- Current price: 1.0865 (unrealized gain: +$15.00)
- Held for: 5 bars
- RSI: 29 (crossed below 30)
- Momentum: -0.00003 (turned negative)
- Recent candle: bearish (close < open)

**Exit Check**:
1. Hard Loss: $+15.00 > -$15.00 ✗
2. Time-Based: 5 bars < 40 bars ✗
3. Reversal: 2/3 conditions ✓
   - RSI Divergence: 29 < 30 ✓
   - Momentum Loss: -0.00003 <= 0 ✓
   - Price Action: 1 bearish candle

**Outcome**:
- **CLOSED** due to reversal signals
- Log: `[REVERSAL_EXIT] EURUSD #... | Triggered: 2/3 conditions | RSI=29.0 + Momentum loss`
- PnL locked: +$15.00
- Reason: Two reversal signals with OR logic (only needed 2/3)

---

## Tuning Recommendations

### For Aggressive Trading
```python
# Lower losses, earlier exits, looser reversal signals
max_loss_threshold_usd = -10.00      # Exit faster on losses
stagnation_limit_bars = 20            # Don't hold stagnant positions long
reversal_conditions_required = 1      # Any single reversal signal exits
```

### For Conservative Trading
```python
# Higher losses, later exits, strict reversal signals
max_loss_threshold_usd = -30.00      # Give more time to recover
stagnation_limit_bars = 60            # Hold positions longer
reversal_conditions_required = 3      # All three conditions must trigger
```

### For Balanced Trading (Default)
```python
# Middle-ground defaults
max_loss_threshold_usd = -15.00
stagnation_limit_bars = 40
reversal_conditions_required = 2      # Any pair of conditions
```

---

## Logging & Diagnostics

### Log Levels

**CRITICAL** (Always visible):
- `[HARD_LOSS_STOP]` - Hard loss threshold triggered
- `[TIME_BASED_STOP]` - Stagnation limit reached
- `[REVERSAL_EXIT]` - Reversal signals triggered
- `[EXIT_MANAGER_EXECUTING]` - Closing position
- `[EXIT_MANAGER_RESULT]` - Close completed successfully
- `[EXIT_MANAGER_FAILED]` - Close failed, will retry

**DEBUG** (Only if logging enabled):
- `[HARD_LOSS_CHECK]` - Position within loss limit
- `[TIME_BASED_CHECK]` - Position under stagnation limit
- `[REVERSAL_CHECK]` - Detailed reversal signal status

### Reading Exit Logs

```
[HARD_LOSS_STOP] EURUSD #55303555040 | Loss: $-21.50 < threshold: $-15.00 | FORCE CLOSE
│                │      │            │      │            │
│                │      │            │      │            └─ Action taken
│                │      │            │      └─ Reason triggered
│                │      │            └─ Why close is necessary
│                │      └─ Position ID
│                └─ Symbol

[REVERSAL_EXIT] GBPUSD #55303555041 | Triggered: 2/3 conditions | PnL: $12.50 | 
RSI=28.1 < 30.0 (LONG reversal) + Momentum=-0.00005 <= 0.0 (LONG lost) | CLOSING
│                │              │                    │              │              │
│                │              │                    │              │              └─ Action
│                │              │                    │              └─ Signal details
│                │              │                    └─ Count of signals
│                │              └─ Current P&L
│                └─ Position ID
```

---

## Troubleshooting

### Issue: Positions closing too frequently

**Solution 1**: Increase hard loss threshold
```bash
export EXIT_MANAGER_MAX_LOSS_USD=-25.00
```

**Solution 2**: Increase stagnation bars needed
```bash
export EXIT_MANAGER_STAGNATION_BARS=60
```

**Solution 3**: Require all three reversal conditions (stricter)
```bash
export EXIT_MANAGER_REVERSAL_CONDITIONS=3
```

### Issue: Positions bleeding indefinitely

**Solution 1**: Lower hard loss threshold
```bash
export EXIT_MANAGER_MAX_LOSS_USD=-10.00
```

**Solution 2**: Lower RSI thresholds (more sensitive)
```bash
export EXIT_MANAGER_RSI_LONG=35.0
export EXIT_MANAGER_RSI_SHORT=65.0
```

### Issue: Exit logic disabled entirely

**Check environment variables**:
```bash
# These must be "true" or "1" to enable
export EXIT_MANAGER_HARD_LOSS=true
export EXIT_MANAGER_TIME_BASED=true
export EXIT_MANAGER_REVERSAL=true
```

---

## Files Modified

### New Files
- ✅ `src/trading/exit_manager.py` (350+ lines)

### Updated Files
- ✅ `main.py`:
  - Added import: `from src.trading.exit_manager import ExitManager, ExitManagerConfig`
  - Added initialization: `exit_manager = ExitManager(config=..., logger=logger)`
  - Replaced manual reversal checks with `exit_manager.check_exit_conditions()` call

---

## Testing Checklist

- [ ] Bot starts without errors (exit_manager imports successfully)
- [ ] Exit logs show when safety valves are checked: `[HARD_LOSS_CHECK]`, `[TIME_BASED_CHECK]`, `[REVERSAL_CHECK]`
- [ ] Hard loss trigger works: position with loss > -$15 closes with `[HARD_LOSS_STOP]` log
- [ ] Time-based trigger works: position held > 40 bars closes with `[TIME_BASED_STOP]` log
- [ ] Reversal exit works: position with 2+ reversal signals closes with `[REVERSAL_EXIT]` log
- [ ] Position registry updates properly: `position_manager.shadow_positions` cleaned after exit
- [ ] Profit tracking updates: `profit_mgmt.close_tracking()` called on every exit
- [ ] Environment variables work: changing `EXIT_MANAGER_*` vars changes behavior

---

## Known Limitations

1. **Time-based exit uses opened_at timestamp**: If positions have incorrect timestamps, bars calculation may be wrong
2. **Hard loss threshold is per-position**: Not per-symbol or portfolio-wide
3. **Price action check is simplified**: Looks at recent candles, not full reversal patterns
4. **No memory between cycles**: Each cycle checks independently, no state carried forward
5. **RSI/Momentum thresholds are fixed**: No dynamic adjustment based on market volatility

---

## Future Enhancements

1. **Portfolio-wide loss limit**: Close ALL positions if daily loss > threshold
2. **Dynamic thresholds**: Adjust based on market volatility, time of day, etc.
3. **Candle pattern recognition**: More sophisticated reversal detection
4. **Multi-timeframe confirmation**: Require reversal on multiple timeframes
5. **Equity curve monitoring**: Track drawdowns and adjust aggression dynamically

---

## Summary

ExitManager provides **three independent safety valves** for position exits:

| Valve | Trigger | Priority | Config |
|-------|---------|----------|--------|
| **Hard Loss** | Unrealized PnL < -$15 | Highest | EXIT_MANAGER_MAX_LOSS_USD |
| **Time-Based** | Held for > 40 bars | High | EXIT_MANAGER_STAGNATION_BARS |
| **Reversal** | Any 2/3 signals | Medium | EXIT_MANAGER_REVERSAL_CONDITIONS |

**Key Values**:
- Prevents indefinite bleeding
- Frees capital from stagnant positions
- Uses OR logic (flexible, not strict AND)
- Same secure close function as profit manager
- Fully configurable via environment variables
- Comprehensive logging for debugging

**Ready for Live Testing** ✅

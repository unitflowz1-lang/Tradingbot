# Error 10027 Terminal State Guard Implementation Guide

## Overview

This document describes the comprehensive refactoring of the MT5 bot to handle **Error 10027** (AutoTrading disabled) and prevent infinite loops when the "Algorithmic Trading" button is disabled in the MT5 Terminal GUI.

## Problem Statement

**Error 10027** occurs when:
- The "Algorithmic Trading" button is toggled OFF in MT5 Terminal
- The bot attempts to place, modify, or close orders
- This causes an infinite loop of failed order attempts

The bot would continuously try to execute orders, each failing with Error 10027, creating a spam of warnings without gracefully handling the condition.

## Solution Architecture

### 1. Terminal State Guard Module (`src/guards/terminal_state_guard.py`)

A new module that manages terminal trading state and prevents infinite loops.

#### Key Components:

**TerminalStateGuard Class**
- Tracks terminal trading state globally
- Manages multiple suspension modes:
  - **System Paused**: AlgoTrading disabled, checks every 30 seconds
  - **Suspended Trading**: After Error 10027, suspends for 5 minutes
  - **Emergency Idle**: After 5+ errors in 30 seconds, idles for 30 minutes

**Core Methods**:

```python
def check_terminal_trade_allowed() -> Tuple[bool, str]
```
- Checks `TERMINAL_TRADE_ALLOWED` property
- Returns (allowed, reason) tuple
- Logs once when disabled to avoid spam

```python
def suspend_trading(duration_seconds: int, reason: str) -> None
```
- Sets trading suspension flag
- Duration: typically 300 seconds (5 minutes)
- Used when Error 10027 is detected

```python
def trigger_emergency_idle(duration_seconds: int, reason: str) -> None
```
- Triggers emergency idle mode for sustained failures
- Duration: typically 1800 seconds (30 minutes)
- Activated after 5+ errors in 30 seconds

```python
def record_error_10027() -> None
```
- Tracks Error 10027 occurrences
- Automatically triggers Emergency Idle if rapid burst detected

**Guard Functions**:

```python
async def execute_terminal_state_guard() -> None
```
- Called at the beginning of each main loop iteration
- Implements the Main Guard logic
- Checks AlgoTrading status and enforces suspensions
- Sleeps 30 seconds if AlgoTrading disabled

```python
async def handle_error_10027(symbol: str, context: str = "") -> None
```
- Global error handler for Error 10027
- Automatically suspends trading
- Logs detailed context

```python
def check_symbol_trade_stops_level(symbol: str, current_sl: float, new_sl: float) -> Tuple[bool, str]
```
- Validates Stop Loss modification against broker's minimum level
- Returns (valid, reason) tuple
- Prevents Error 10016 (invalid stops)

---

## Implementation Details

### 2. Main Loop Integration (`main.py`)

#### Change 1: Import Terminal State Guard
```python
from src.guards.terminal_state_guard import (
    get_terminal_state_guard,
    execute_terminal_state_guard,
    handle_error_10027,
    check_symbol_trade_stops_level,
)
```

#### Change 2: Main Guard at Loop Beginning
At the beginning of the `while True:` loop (line ~2607):

```python
while True:
    # ===== MAIN GUARD: Terminal State Check (Error 10027 Prevention) =====
    # At the beginning of each cycle, check if AlgoTrading is enabled.
    # If disabled, pause all trading logic and check every 30 seconds.
    await execute_terminal_state_guard()
    # --------------------------------------------------
```

**What This Does**:
- Checks if AlgoTrading is enabled before executing any trading logic
- If disabled, logs "SYSTEM PAUSED: AlgoTrading Disabled" (once only)
- Sleeps for 30 seconds before checking again
- Prevents any trading logic from running when AlgoTrading is off
- Automatically resumes when AlgoTrading is re-enabled

**Log Examples**:
```
[SYSTEM_PAUSED] AlgoTrading Disabled. The 'Algorithmic Trading' button is OFF in MT5 Terminal.
Reason: AlgoTrading disabled in Terminal GUI | Bot will check every 30 seconds for re-enablement.
```

---

### 3. SMALL_WIN_RESET Function Refactoring (`main.py`)

#### Change 3: Enhanced Error Handling in Basket Close

The `SMALL_WIN_RESET` function now:
1. Collects close errors instead of silently failing
2. Detects Error 10027 during basket close
3. Calls `handle_error_10027()` to suspend trading
4. Breaks out of the close loop to avoid infinite attempts
5. Skips cooldown clearing if Error 10027 was encountered

**Before**:
```python
for reset_position in portfolio.positions[:]:
    try:
        await broker.close_position(reset_position.position_id)
    except Exception as basket_reset_err:
        logger.warning(...)  # Just logs and continues
```

**After**:
```python
close_errors = []
for reset_position in portfolio.positions[:]:
    try:
        await broker.close_position(reset_position.position_id)
    except Exception as basket_reset_err:
        close_errors.append((reset_position.symbol, reset_position.position_id, str(basket_reset_err)))
        logger.warning(...)
        
        # Error 10027 Handler: AutoTrading disabled
        error_text = str(basket_reset_err).lower()
        if "10027" in error_text or "autotrading disabled" in error_text:
            logger.critical(
                "[SMALL_WIN_RESET_ERROR_10027] Error 10027 detected while closing basket. "
                "Suspending trading for 5 minutes to allow terminal recovery."
            )
            await handle_error_10027(
                symbol=reset_position.symbol,
                context="SMALL_WIN_RESET basket close"
            )
            # Break out of the close loop - no point trying other positions
            break

# Only clear cooldowns if we didn't encounter Error 10027
error_10027_found = any("10027" in err[2].lower() or "autotrading" in err[2].lower() for err in close_errors)
if not error_10027_found and not get_terminal_state_guard().is_trading_suspended():
    symbol_cooldowns.clear()
    loss_cooldown_until.clear()
    logger.info("[SMALL_WIN_RESET] Symbol cooldown memory cleared after basket recovery close.")
```

**Behavior**:
- If Error 10027 is encountered during basket close:
  - Logs `[SMALL_WIN_RESET_ERROR_10027]` message
  - Calls `handle_error_10027()` which suspends trading for 5 minutes
  - Breaks out of close loop (no point retrying if AlgoTrading is disabled)
  - Does NOT clear cooldowns (preserves state during suspension)
- If no Error 10027:
  - Clears cooldowns as normal (previous behavior)

**Log Examples**:
```
[SMALL_WIN_RESET_ERROR_10027] Error 10027 detected while closing basket.
Suspending trading for 5 minutes to allow terminal recovery.

[SUSPEND_TRADING] Trading suspended for 300s until 2026-04-17 12:35:00 UTC |
Reason: Error 10027 detected on USD/CAD | SMALL_WIN_RESET basket close
```

---

### 4. Broker Error Handling (`src/data/mt5_broker.py`)

#### Change 4: Enhanced `close_position()` Method

The `close_position()` method now explicitly detects and propagates Error 10027:

```python
# Check for Error 10027 specifically
if result.retcode == 10027:
    self.logger.critical(
        f"[CLOSE_ERROR_10027] Position {position_id} | Symbol {pos.symbol} | "
        f"Error 10027: AutoTrading disabled in MT5 Terminal GUI"
    )
    raise BrokerAPIError(f"Failed to close position: AutoTrading disabled: 10027")
```

**Error Propagation**:
- Error 10027 is now explicitly caught and re-raised
- The caller (SMALL_WIN_RESET) can detect it and call `handle_error_10027()`
- Error message includes "10027" for easy detection

---

#### Change 5: Modification Guard (Error 10016 Prevention)

Before sending a Stop Loss modification, the bot now validates against `SYMBOL_TRADE_STOPS_LEVEL`:

```python
# === MODIFICATION GUARD (Error 10016 Prevention) ===
# Check SYMBOL_TRADE_STOPS_LEVEL before sending modification
if final_sl not in (None, 0):
    try:
        from src.guards.terminal_state_guard import check_symbol_trade_stops_level
        is_valid, validation_msg = check_symbol_trade_stops_level(pos.symbol, pos.sl, final_sl)
        if not is_valid:
            self._record_modify_result(...)
            self.logger.warning(
                f"[MODIFICATION_GUARD] {pos.symbol} ticket {order_id} | "
                f"SL modification blocked: {validation_msg}"
            )
            return False
    except ImportError:
        pass  # Fallback if guards module not available
# === END MODIFICATION GUARD ===
```

**What This Does**:
- Gets the symbol's `SYMBOL_TRADE_STOPS_LEVEL` (minimum distance in pips)
- Calculates the proposed distance from current price
- Rejects modification if distance is too small
- Prevents Error 10016 (invalid stops on protected order)

**Example Validation**:
```
[MODIFICATION_GUARD] EUR/USD ticket 12345 |
SL too close to price. Min distance: 0.0002 (20 pips), Current distance: 0.00015
```

---

## Execution Flow Diagram

```
Main Loop Iteration
      |
      v
┌─────────────────────────────────────────┐
│ await execute_terminal_state_guard()     │
│  - Check TERMINAL_TRADE_ALLOWED          │
│  - If disabled: Sleep 30s, skip rest     │
│  - If suspended: Sleep 10s, skip rest    │
│  - If Emergency Idle: Sleep 15s, skip    │
└─────────────────────────────────────────┘
      |
      | (if enabled and not suspended)
      v
┌─────────────────────────────────────────┐
│ Check Resilience Controller              │
│ Check Market Closed                      │
│ Evaluate LLM Signals                     │
└─────────────────────────────────────────┘
      |
      v
┌─────────────────────────────────────────┐
│ SMALL_WIN_RESET Check                    │
│  - Attempt to close positions            │
│  - If Error 10027 detected:              │
│    * Call handle_error_10027()           │
│    * Suspend trading 5 minutes           │
│    * Break close loop                    │
│    * Continue to next iteration          │
└─────────────────────────────────────────┘
      |
      v
┌─────────────────────────────────────────┐
│ Position Analysis & Trading Logic        │
│  - All normal trading execution          │
└─────────────────────────────────────────┘
      |
      v
┌─────────────────────────────────────────┐
│ Before Modification:                     │
│  - Call check_symbol_trade_stops_level() │
│  - Reject if distance too small          │
│  - Send modification if valid            │
└─────────────────────────────────────────┘
      |
      v
   Sleep & Loop
```

---

## State Transitions

### Example 1: AlgoTrading Disabled

```
T=0:00    | SYSTEM_PAUSED logged (once)
T=0:30    | Check again, still disabled
T=1:00    | Still disabled
T=1:30    | User enables AlgoTrading button
T=1:31    | SYSTEM_RESUMED logged
T=1:32    | Normal trading resumes
```

### Example 2: Error 10027 During Basket Close

```
T=0:00    | SMALL_WIN_RESET triggered
          | Attempt to close positions
T=0:02    | Error 10027 on first position
          | SMALL_WIN_RESET_ERROR_10027 logged
          | handle_error_10027() called
          | SUSPEND_TRADING for 5 minutes
T=0:10    | Trading suspended (trading logic skipped)
T=5:00    | Suspension expires
T=5:01    | Normal trading resumes
```

### Example 3: Rapid Error 10027 Burst

```
T=0:00    | Error 10027 #1 (counter: 1)
T=0:05    | Error 10027 #2 (counter: 2)
T=0:10    | Error 10027 #3 (counter: 3)
T=0:15    | Error 10027 #4 (counter: 4)
T=0:20    | Error 10027 #5 (counter: 5)
          | EMERGENCY_IDLE triggered!
          | Emergency idle for 30 minutes
T=0:25    | All trading skipped (emergency idle active)
T=30:20   | Emergency idle expires
T=30:21   | Normal trading resumes
```

---

## Configuration

No environment variables need to be set - the system works with defaults:

- **Terminal Check Interval**: 30 seconds (hardcoded)
- **Trading Suspension Duration**: 300 seconds / 5 minutes (hardcoded)
- **Emergency Idle Duration**: 1800 seconds / 30 minutes (hardcoded)
- **Error Burst Threshold**: 5 errors in 30 seconds (hardcoded)

To customize, modify the constants in `src/guards/terminal_state_guard.py`.

---

## Testing the Implementation

### Test 1: Disable AlgoTrading Button

1. Start the bot normally
2. In MT5 Terminal, click Tools → Options → Server
3. Toggle OFF "Algorithmic Trading"
4. Observe bot logs:
   - `[SYSTEM_PAUSED] AlgoTrading Disabled` (logs once)
   - Every 30 seconds: checks for re-enablement
5. Toggle ON "Algorithmic Trading"
6. Observe: `[SYSTEM_RESUMED] AlgoTrading Re-enabled`
7. Normal trading resumes

### Test 2: Trigger Error 10027 During Basket Close

1. Ensure AlgoTrading is OFF
2. Create several profitable positions manually in MT5
3. Wait for SMALL_WIN_RESET to trigger
4. Observe logs:
   - `[SMALL_WIN_RESET] Unrealized basket reached...`
   - `[SMALL_WIN_RESET_ERROR_10027] Error 10027 detected`
   - `[SUSPEND_TRADING] Trading suspended for 300s`
5. Observe bot skips trading logic for 5 minutes
6. Enable AlgoTrading
7. After 5 minutes, normal trading resumes

### Test 3: Test Modification Guard

1. Create a position
2. Modify the Stop Loss to very close to current price (closer than broker minimum)
3. Observe: `[MODIFICATION_GUARD]` prevents the modification
4. Set Stop Loss to valid distance
5. Observe: Modification sent successfully

---

## Log Reference

### Main Guard Logs

```
[SYSTEM_PAUSED] AlgoTrading Disabled. The 'Algorithmic Trading' button is OFF in MT5 Terminal.
[SYSTEM_RESUMED] AlgoTrading Re-enabled. Bot resuming normal trading operations.
[TERMINAL_STATE_GUARD] Emergency Idle Mode Active. Will resume trading at...
[TERMINAL_STATE_GUARD] Trading Suspended. Will resume in Xs...
```

### Error Handling Logs

```
[ERROR_10027_HANDLER] AutoTrading Disabled for {symbol}...
[SUSPEND_TRADING] Trading suspended for {duration}s until {time} UTC
[EMERGENCY_IDLE] Emergency idle triggered for {duration}s
[ERROR_10027_DETECTION] {N} errors in {X}s. Entering emergency idle mode.
```

### SMALL_WIN_RESET Logs

```
[SMALL_WIN_RESET] Unrealized basket reached $X target (current: $Y).
[SMALL_WIN_RESET_ERROR_10027] Error 10027 detected while closing basket.
[SMALL_WIN_RESET] Symbol cooldown memory cleared after basket recovery close.
```

### Modification Guard Logs

```
[MODIFICATION_GUARD] {symbol} ticket {id} | SL modification blocked: {reason}
[STOP_LOSS_VALIDATION] Error checking SYMBOL_TRADE_STOPS_LEVEL...
```

---

## Benefits

1. **No More Infinite Loops**: System pauses gracefully when AlgoTrading is disabled
2. **Single Log Message**: Logs "SYSTEM PAUSED" once instead of spamming errors
3. **Automatic Recovery**: Detects when AlgoTrading is re-enabled and resumes trading
4. **Intelligent Suspension**: Detects Error 10027 and suspends trading for recovery
5. **Emergency Safeguard**: Triggers Emergency Idle after rapid error bursts
6. **Prevents Error 10016**: Validates SL modifications against broker minimum levels
7. **Maintains Position State**: Preserves cooldowns and state during suspension

---

## Troubleshooting

### Issue: Bot still shows Error 10027 spam

**Solution**:
- Ensure Terminal State Guard is imported in main.py
- Verify `await execute_terminal_state_guard()` is at the start of the while loop
- Check that the guards module is in `src/guards/`

### Issue: Emergency Idle never triggered

**Solution**:
- Emergency Idle requires 5+ errors in 30 seconds
- If testing, disable AlgoTrading to cause rapid errors
- Check logs for `[ERROR_10027_DETECTION]` message

### Issue: Modification Guard not working

**Solution**:
- Ensure import is added to modify_order method
- Check logs for `[MODIFICATION_GUARD]` messages
- Verify `check_symbol_trade_stops_level()` is being called

---

## Files Modified

1. **Created**: `src/guards/terminal_state_guard.py` - Main guard module
2. **Created**: `src/guards/__init__.py` - Module init
3. **Modified**: `main.py` - Added imports and guard check at loop start
4. **Modified**: `main.py` - Refactored SMALL_WIN_RESET function
5. **Modified**: `src/data/mt5_broker.py` - Enhanced close_position and modify_order methods

---

## Future Enhancements

- Add webhook notifications when Emergency Idle is triggered
- Add configurable suspension durations via environment variables
- Add dashboard metrics for terminal state tracking
- Add automatic recovery strategies (e.g., soft reset of connections)


# Terminal State Guard - Quick Reference & Code Examples

## Quick Start

### 1. Verify Terminal State Guard is Installed

Check that these files exist:
```
src/guards/__init__.py
src/guards/terminal_state_guard.py
```

### 2. Verify Main Loop Integration

In `main.py`, search for the main while loop (~line 2607) and verify:

```python
while True:
    # ===== MAIN GUARD: Terminal State Check (Error 10027 Prevention) =====
    await execute_terminal_state_guard()
    # --------------------------------------------------
    
    # Rest of loop continues...
```

### 3. Verify SMALL_WIN_RESET Refactoring

Search for `[SMALL_WIN_RESET]` in main.py and verify it has:

```python
# Error 10027 Handler: AutoTrading disabled
error_text = str(basket_reset_err).lower()
if "10027" in error_text or "autotrading disabled" in error_text:
    await handle_error_10027(...)
```

---

## Code Snippets for Reference

### Snippet 1: Terminal State Guard Usage

```python
from src.guards.terminal_state_guard import (
    get_terminal_state_guard,
    execute_terminal_state_guard,
    handle_error_10027,
    check_symbol_trade_stops_level,
)

# At the start of each main loop iteration
async def main_loop():
    while True:
        # Execute terminal state check
        await execute_terminal_state_guard()
        
        # Rest of trading logic...
```

### Snippet 2: Detecting and Handling Error 10027

```python
try:
    await broker.close_position(position_id)
except Exception as err:
    error_text = str(err).lower()
    
    # Check for Error 10027
    if "10027" in error_text or "autotrading disabled" in error_text:
        # Handle gracefully
        logger.critical(f"[ERROR_10027] Detected: {err}")
        
        # Suspend trading
        await handle_error_10027(
            symbol="EUR/USD",
            context="position close attempt"
        )
```

### Snippet 3: Modifying SL with Guard

```python
# Before sending modification
if final_sl not in (None, 0):
    from src.guards.terminal_state_guard import check_symbol_trade_stops_level
    
    is_valid, msg = check_symbol_trade_stops_level(symbol, current_sl, new_sl)
    if not is_valid:
        logger.warning(f"[MODIFICATION_GUARD] Blocked: {msg}")
        return False
    
    # Send modification request
    result = mt5.order_send(request)
```

### Snippet 4: Using Terminal State Guard

```python
guard = get_terminal_state_guard()

# Check if AlgoTrading is enabled
allowed, reason = guard.check_terminal_trade_allowed()
if not allowed:
    print(f"AlgoTrading disabled: {reason}")
    # Skip trading logic

# Check if trading is currently suspended
if guard.is_trading_suspended():
    remaining = (guard.suspend_trading_until - datetime.now(timezone.utc)).total_seconds()
    print(f"Trading suspended for {remaining:.0f}s more")
    # Skip trading logic

# Manually trigger suspension (if needed)
guard.suspend_trading(
    duration_seconds=300,
    reason="Manual suspension for testing"
)

# Check Emergency Idle status
if guard.is_emergency_idle_active():
    print("Emergency Idle mode active - no trading")
```

---

## Error 10027 Handling Flow

```python
# When Error 10027 is encountered:

1. Detected during order placement/close/modify
   ↓
2. Exception is raised with "10027" in message
   ↓
3. Caller catches and checks error_text
   ↓
4. If "10027" detected:
   - Call: await handle_error_10027(symbol, context)
   ↓
5. handle_error_10027() does:
   - Increments error counter
   - Checks if 5+ errors in 30s (Emergency Idle trigger)
   - Otherwise calls guard.suspend_trading(300, reason)
   ↓
6. On next loop iteration:
   - execute_terminal_state_guard() detects suspension
   - Skips all trading logic
   - Sleeps 10s and checks again
   ↓
7. After 300s:
   - Suspension expires
   - Trading resumes normally
```

---

## Common Log Patterns

### Pattern 1: Normal Shutdown (AlgoTrading Disabled)

```
[SYSTEM_PAUSED] AlgoTrading Disabled. The 'Algorithmic Trading' button is OFF...
[TERMINAL_STATE_GUARD] Checking again in 30s...
[SYSTEM_PAUSED] (logged once only, won't repeat)
...
(after 30s)
[TERMINAL_STATE_GUARD] Checking again...
(if AlgoTrading still disabled, sleeps 30s again)
...
(when AlgoTrading re-enabled)
[SYSTEM_RESUMED] AlgoTrading Re-enabled. Bot resuming...
```

### Pattern 2: Error 10027 Detection & Recovery

```
[SMALL_WIN_RESET] Unrealized basket reached $10.00 target...
[SMALL_WIN_RESET] Failed to close USD/CAD #56278750973: Error 10027...
[SMALL_WIN_RESET_ERROR_10027] Error 10027 detected while closing basket...
[ERROR_10027_HANDLER] AutoTrading Disabled for USD/CAD...
[SUSPEND_TRADING] Trading suspended for 300s until 12:35:00 UTC...
(skip 5 minutes of trading)
[TERMINAL_STATE_GUARD] Trading Suspended. Will resume in 300s...
(after 5 minutes)
[TERMINAL_STATE_GUARD] Trading suspension expired, resuming...
```

### Pattern 3: Emergency Idle Trigger

```
[ERROR_10027_DETECTION] 1 errors in 2.1s.
[ERROR_10027_DETECTION] 2 errors in 4.5s.
[ERROR_10027_DETECTION] 3 errors in 7.2s.
[ERROR_10027_DETECTION] 4 errors in 9.8s.
[ERROR_10027_DETECTION] 5 errors in 12.3s.
[ERROR_10027_DETECTION] 5 errors in 12.3s. Entering emergency idle mode.
[EMERGENCY_IDLE] Emergency idle triggered for 1800s until 01:05:30 UTC...
(skip 30 minutes of all trading)
[TERMINAL_STATE_GUARD] Emergency Idle Mode Active...
(after 30 minutes)
(normal trading resumes)
```

---

## State Query Examples

```python
# Get guard instance
guard = get_terminal_state_guard()

# Query 1: Is AlgoTrading enabled?
allowed, reason = guard.check_terminal_trade_allowed()
if not allowed:
    print(f"Cannot trade: {reason}")

# Query 2: Are we currently suspended?
if guard.is_trading_suspended():
    print(f"Suspended until: {guard.suspend_trading_until}")

# Query 3: Are we in Emergency Idle?
if guard.is_emergency_idle_active():
    print(f"Emergency Idle until: {guard.emergency_idle_until}")

# Query 4: Error statistics
print(f"Error 10027 count: {guard.error_10027_count}")
print(f"First error at: {guard.error_10027_first_seen}")

# Query 5: Terminal status
if guard.algo_trading_disabled_at:
    print(f"AlgoTrading disabled since: {guard.algo_trading_disabled_at}")
```

---

## Testing Checklist

- [ ] Terminal State Guard module exists at `src/guards/terminal_state_guard.py`
- [ ] Guard is imported in main.py
- [ ] `await execute_terminal_state_guard()` is called at start of while loop
- [ ] SMALL_WIN_RESET has Error 10027 detection
- [ ] `handle_error_10027()` is called when 10027 is detected
- [ ] Modification guard is in place in `modify_order()` method
- [ ] Bot gracefully handles AlgoTrading disabled scenario
- [ ] Bot suspends trading when Error 10027 is detected
- [ ] Bot resumes after suspension expires
- [ ] Logs show proper state transitions

---

## Performance Notes

- **CPU Impact**: Negligible - only adds one async function call per loop
- **Memory Impact**: ~2KB for TerminalStateGuard singleton
- **Network Impact**: No network calls (terminal info is local)
- **Latency**: <1ms for guard check

---

## Backward Compatibility

The implementation is fully backward compatible:
- Existing trading logic unchanged
- Only adds guard checks that skip if conditions not met
- No changes to position sizing, risk management, or signal generation
- Can be toggled off by removing the guard check line

---

## Rollback Instructions

If you need to revert:

1. Remove the Terminal State Guard call from main.py:
   ```python
   # Remove this line:
   await execute_terminal_state_guard()
   ```

2. Remove the Error 10027 handling from SMALL_WIN_RESET:
   ```python
   # Replace with original simple try/except
   ```

3. Remove the guard check from modify_order:
   ```python
   # Remove the MODIFICATION_GUARD section
   ```

4. Delete the guard files:
   ```
   rm src/guards/terminal_state_guard.py
   rm src/guards/__init__.py
   ```

---

## Support & Debugging

### Enable Debug Logging

Add to your logging configuration:
```python
logging.getLogger("src.guards.terminal_state_guard").setLevel(logging.DEBUG)
```

### Check Guard State

Add this anywhere in the code to inspect guard state:
```python
guard = get_terminal_state_guard()
print(f"Guard State: trading_allowed={guard.check_terminal_trade_allowed()[0]}, "
      f"suspended={guard.is_trading_suspended()}, "
      f"emergency_idle={guard.is_emergency_idle_active()}")
```

### Force Manual Test

```python
# Force suspension
guard = get_terminal_state_guard()
guard.suspend_trading(60, "test")

# Force Emergency Idle
guard.trigger_emergency_idle(60, "test")

# Record error (simulates 10027)
for i in range(5):
    guard.record_error_10027()
```


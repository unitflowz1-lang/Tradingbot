# AutoTrading Disabled (Error 10027) Refactoring

## Overview
Refactored `execute_order` method to handle MT5 AutoTrading disabled errors (error 10027) proactively. The system now:
1. Checks if AutoTrading is enabled BEFORE attempting order placement
2. Handles error 10027 gracefully with terminal re-sync logic
3. Prevents stop-loss modifications when AutoTrading is disabled
4. Enters HOLD_MODE to pause all execution

---

## Changes Made

### 1. ExecutionEngine (`src/trading/execution_engine.py`)

#### New Attributes (Lines 71-74)
```python
self._hold_mode_active: bool = False
self._hold_mode_until: Optional[datetime] = None
self._last_autotrading_check: Optional[datetime] = None
```
- `_hold_mode_active`: Flag indicating HOLD_MODE is active
- `_hold_mode_until`: Timestamp when HOLD_MODE should expire
- `_last_autotrading_check`: Timestamp of last AutoTrading validation

#### New Methods

**`_check_autotrading_enabled()` (Lines 89-107)**
- Pre-flight check that verifies `mt5.terminal_info().trade_allowed`
- Returns `True` if AutoTrading is enabled, `False` otherwise
- Safe fallback: returns `True` if MT5 is unavailable (assumes OK)
- Used before every order execution attempt

**`_enter_hold_mode(reason, hold_duration_seconds=60)` (Lines 109-121)**
- Activates HOLD_MODE to stop all execution
- Logs critical message with resume timestamp
- Default hold duration: 60 seconds
- Called when error 10027 is detected or AutoTrading check fails

**`_handle_autotrading_disabled_error(order)` (Lines 123-169)**
- Terminal re-sync logic for error 10027
- Steps:
  1. Log critical failure with symbol and order ID
  2. Enter HOLD_MODE for 60 seconds
  3. Wait 60 seconds (blocks execution)
  4. Re-validate terminal state
  5. Exit HOLD_MODE if AutoTrading is re-enabled
  6. Extend HOLD_MODE if still disabled
- Returns `ExecutionResult` with failure status

**`purge_execution_queue_for_symbol(symbol, queue_processor)` (Lines 171-194)**
- Flushes execution queue for affected symbol when AutoTrading is disabled
- Prevents stale trade signals from executing after re-enabling
- Logs critical message with symbol to purge
- Placeholder for queue clearing logic (adjust based on actual queue structure)

#### Updated Methods

**`_execute_market_order()` (Lines 906-954)**
- **PRE-FLIGHT CHECK** (Lines 909-919):
  - Calls `_check_autotrading_enabled()` before proceeding
  - Returns failure if AutoTrading is disabled
  - Triggers `_handle_autotrading_disabled_error()`

- **HOLD_MODE CHECK** (Lines 921-954):
  - Verifies HOLD_MODE is not active
  - Blocks execution if within HOLD_MODE duration
  - Automatically exits HOLD_MODE when duration expires
  - Attempts re-validation and extends HOLD_MODE if still disabled

- **ERROR 10027 HANDLING** (Lines 1270-1277):
  - Detects error 10027 during order placement
  - Checks for patterns: "10027", "autotrading", "trade_allowed"
  - Calls `_handle_autotrading_disabled_error()` for terminal re-sync
  - Returns failure immediately

---

### 2. DynamicTrailingSLManager (`src/trading/dynamic_trailing_sl_manager.py`)

#### New Attributes (Line 154)
```python
self._autotrading_disabled_logged = False  # Track if we've logged AutoTrading disabled once
```
- Prevents log spam from repeated AutoTrading disabled checks

#### New Method

**`_check_autotrading_enabled()` (Lines 164-199)**
- Pre-flight check: verifies `mt5.terminal_info().trade_allowed`
- Logs critical message ONCE when AutoTrading is disabled
- Logs info message when AutoTrading is re-enabled
- Safe fallback: returns `True` if MT5 is unavailable
- Same logic as ExecutionEngine but tailored for SL modifications

#### Updated Method

**`update_trailing_sl()` (Lines 374-376)**
- **PRE-FLIGHT CHECK** (Lines 374-376):
  - First check before any modification attempts
  - Returns early with message: "AutoTrading disabled in MT5 GUI - modifications blocked"
  - Prevents unnecessary calculations and broker calls

---

## Execution Flow

### Normal Execution with AutoTrading Enabled
```
execute_order()
  └─ _execute_market_order()
      └─ _check_autotrading_enabled() ✓
      └─ [HOLD_MODE_CHECK] ✓
      └─ place_order() ✓
      └─ Return: ExecutionResult(success=True)
```

### Execution with AutoTrading Disabled (Pre-flight)
```
execute_order()
  └─ _execute_market_order()
      └─ _check_autotrading_enabled() ✗
      └─ _handle_autotrading_disabled_error()
         ├─ Log: [CRITICAL_AUTH_FAIL]
         ├─ _enter_hold_mode() [60 seconds]
         ├─ await asyncio.sleep(60)
         ├─ Re-check: _check_autotrading_enabled()
         │  ├─ If enabled: exit HOLD_MODE, resume
         │  └─ If disabled: extend HOLD_MODE
         └─ Return: ExecutionResult(success=False)
```

### Error 10027 During Order Placement
```
execute_order()
  └─ _execute_market_order()
      └─ _check_autotrading_enabled() ✓
      └─ place_order() → Exception (10027)
      └─ _handle_autotrading_disabled_error()
         ├─ Log: [ERROR_10027]
         ├─ Terminal re-sync (60s wait + validation)
         └─ Return: ExecutionResult(success=False)
```

### Trailing Stop-Loss with AutoTrading Disabled
```
update_trailing_sl()
  └─ _check_autotrading_enabled() ✗
  └─ Return early: (False, "AutoTrading disabled in MT5 GUI - modifications blocked")
```

---

## Logging Output

### Critical Failure Logs
```
[CRITICAL_AUTH_FAIL] AutoTrading is disabled in MT5 GUI. Enable it to proceed. 
  Symbol: EUR/USD | Order ID: order_12345

[HOLD_MODE_ACTIVATED] AutoTrading disabled. Stopping all execution. 
  Reason: Error 10027: AutoTrading disabled for EUR/USD | 
  Will re-check at: 2026-04-16 14:35:20 UTC

[TERMINAL_RESYNC] Waiting 60 seconds before re-validation...
[TERMINAL_RESYNC] Checking if AutoTrading is re-enabled...

[TERMINAL_RESYNC_SUCCESS] AutoTrading re-enabled. Resuming execution.
  or
[TERMINAL_RESYNC_FAILED] AutoTrading still disabled. Maintaining HOLD_MODE.

[HOLD_MODE_ACTIVE] Execution blocked. EUR/USD | 
  Resume at: 2026-04-16 14:35:20 UTC

[QUEUE_PURGE] Flushing Execution_Queue for EUR/USD to prevent stale signals | 
  AutoTrading was disabled, clearing expired trade signals.
```

---

## Configuration

### HOLD_MODE Duration
- Default: 60 seconds
- Configurable via `_enter_hold_mode(reason, hold_duration_seconds=60)`
- Recommended: 60-120 seconds to allow manual re-enabling in GUI

### AutoTrading Check Frequency
- Checked on every `execute()` call
- Checked on every `update_trailing_sl()` call
- Re-checked after HOLD_MODE duration expires

### Queue Purge
- Adjustable based on actual queue implementation
- Currently placeholder in `purge_execution_queue_for_symbol()`
- Should be called after terminal re-sync if AutoTrading remains disabled

---

## Error Codes Handled

| Code | Error | Handler |
|------|-------|---------|
| 10027 | AutoTrading disabled | `_handle_autotrading_disabled_error()` |
| 10018 | Market closed | Market closed deferral |
| Other | Generic execution error | Standard error handling |

---

## Testing Checklist

- [ ] Pre-flight check blocks execution when `trade_allowed=False`
- [ ] HOLD_MODE prevents execution for 60 seconds
- [ ] After 60 seconds, re-check succeeds if AutoTrading is enabled
- [ ] After 60 seconds, HOLD_MODE extends if AutoTrading still disabled
- [ ] Error 10027 during placement triggers terminal re-sync
- [ ] DynamicTrailingSLManager blocks modifications when AutoTrading disabled
- [ ] Logs show clear progression: [CRITICAL_AUTH_FAIL] → [HOLD_MODE_ACTIVATED] → [TERMINAL_RESYNC]
- [ ] Queue purge removes stale signals for affected symbol

---

## Notes

- **Thread-safe**: Uses existing `asyncio.Lock()` patterns
- **Non-blocking for check**: Pre-flight check is synchronous, minimal overhead
- **Graceful degradation**: Safe fallbacks when MT5 is unavailable
- **Log clarity**: Uses brackets [TAG] for easy log filtering (e.g., `grep "[CRITICAL_AUTH_FAIL]"`)
- **AutoTrading status**: Check MT5 GUI → Settings → Enable "Allow Automated Trading"

# FRIDAY PARADOX FIX - CODE LOCATION REFERENCE

**Purpose**: Locate all three blocking layers in the codebase  
**Last Updated**: April 3, 2026

---

## BLOCK #1: Entry Signal Generation Blocking

### File: `main.py`

#### Location 1A: Utility Function (Line 828-861)
```python
# ===== GLOBAL UTILITY: FRIDAY PARADOX FIX =====
def is_friday_critical_late_trading_hours(check_time: Optional[datetime] = None) -> bool:
    """
    Check if current time is Friday after 15:00 ET (Broker Time).
    STRICT BLOCK: Even 'Institutional Sweep' signals cannot bypass this.
    """
    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)
    
    # Convert UTC to ET (UTC-5)
    et_time = check_time - timedelta(hours=5)
    
    # Friday = 4 (Monday = 0)
    is_friday = et_time.weekday() == 4
    is_after_3pm_et = et_time.hour >= 15
    
    return is_friday and is_after_3pm_et
```

**Key Points**:
- Returns `True` if Friday 15:00+ ET
- Takes optional datetime (defaults to now)
- Converts UTC to ET with -5 hour offset
- Simple boolean check

---

#### Location 1B: Application to Structure Override (Line 5422-5433)
```python
# ===== FIX: FRIDAY PARADOX - STRICT BLOCK FOR STRUCTURE OVERRIDE =====
# Block structure_override even at peak institutional sweep times
is_friday_critical_hours = is_friday_critical_late_trading_hours(velocity_timestamp)
if is_friday_critical_hours and structure_override:
    logger.critical(
        "[FRIDAY_PARADOX_BLOCK] %s | STRICT BLOCK: Friday after 15:00 ET detected. "
        "Institutional Sweep override REJECTED to prevent suicide loop. "
        "Structure: %s | Strength: %.2f",
        symbol,
        structure_label or "UNKNOWN",
        structure_strength
    )
    structure_override = False
    structure_label = None
    structure_strength = 0.0
```

**How It Works**:
1. Gets velocity_timestamp from historical data
2. Checks if it's Friday critical hours
3. If yes AND structure_override is active: Kill the override
4. Logs exactly why (prevents confusion)
5. Clears all override-related variables

**Impact**: No Institutional Sweep signals qualify for override on Friday 15:00+ ET

---

## BLOCK #2: Execution Engine Kill-Switch

### File: `src/trading/execution_engine.py`

#### Location 2A: Utility Function (Line 27-54)
```python
# ===== GLOBAL UTILITY: FRIDAY LATE TRADING RISK CHECK =====
def is_friday_late_trading_risk(check_time: Optional[datetime] = None) -> bool:
    """
    Check if current time is Friday after 15:00 ET (3 PM).
    Used for global Friday entry kill-switch to prevent weekend gap risk.
    """
    if check_time is None:
        check_time = datetime.now(timezone.utc)
    
    if check_time.tzinfo is None:
        check_time = check_time.replace(tzinfo=timezone.utc)
    
    # Convert UTC to ET (UTC-5)
    et_time = check_time - timedelta(hours=5)
    
    # Friday = 4 (Monday = 0)
    is_friday = et_time.weekday() == 4
    is_after_3pm = et_time.hour >= 15
    
    return is_friday and is_after_3pm
```

**Key Points**:
- Similar to Block #1 utility
- Independent implementation for redundancy
- Also returns True if Friday 15:00+ ET

---

#### Location 2B: Application in ExecutionEngine.execute() (Line 388-403)
```python
# ===== FIX #1: GLOBAL FRIDAY ENTRY KILL-SWITCH =====
# Block all new entries on Friday after 15:00 ET to prevent weekend gap risk
if is_friday_late_trading_risk():
    self.logger.critical(
        "[FRIDAY_LATE_KILL_SWITCH] %s | Blocking entry. Current time is Friday after 15:00 ET. "
        "Too much weekend gap risk for new positions.",
        order.symbol,
    )
    return ExecutionResult(
        success=False,
        order_id=order.order_id,
        executed_price=None,
        executed_quantity=None,
        error_message="EXECUTION_PAUSED: FRIDAY_LATE_TRADING_RISK",
        timestamp=datetime.now(timezone.utc),
    )
```

**Where in execute() method**:
- AFTER: HARD SPREAD GATE check (line 377-386)
- BEFORE: structure_override signal clearing (line 404+)
- BEFORE: actual market execution (_execute_market_order / _execute_limit_order)

**How It Works**:
1. Checks if it's Friday critical hours
2. If yes: Rejects with ExecutionResult(success=False)
3. Logs with [FRIDAY_LATE_KILL_SWITCH] identifier
4. Does not reach broker.send_order()

**Impact**: Final safety net - execution rejected even if signal reaches this point

---

## BLOCK #3: Exit Grace Period Protection

### File: `src/trading/profit_protection_module.py`

#### Location 3: Grace Period Logic (Line 1037-1083)
```python
elif self.settings.use_momentum_stall and not state['momentum_stall_done'] and friday_force_close_window:
    # ===== FIX: FRIDAY GRACE PERIOD - PROTECT FRIDAY-OPENED POSITIONS =====
    # Don't force close positions opened on Friday within the last 2 hours
    position_opened_at = None
    try:
        position_opened_at = getattr(position, "opened_at", None)
        if position_opened_at is None:
            position_opened_at = getattr(position, "open_time", None)
        
        if position_opened_at is not None:
            # Ensure timezone awareness
            if isinstance(position_opened_at, datetime) and position_opened_at.tzinfo is None:
                position_opened_at = position_opened_at.replace(tzinfo=timezone.utc)
            
            # Calculate time since position opened
            time_since_open = (broker_now - position_opened_at).total_seconds() / 3600
            
            # Check if position was opened on a Friday
            open_et_time = position_opened_at - timedelta(hours=5)
            was_opened_friday = open_et_time.weekday() == 4
            
            grace_period_hours = 2.0
            within_grace_period = time_since_open < grace_period_hours
            
            if was_opened_friday and within_grace_period:
                self.logger.critical(
                    "[FRIDAY_GRACE_PERIOD] %s | Position opened %.1f hours ago on Friday. "
                    "Granting %d-hour grace period before force close. Skipping momentum exit.",
                    position.symbol,
                    time_since_open,
                    int(grace_period_hours)
                )
            else:
                # Grace period expired or not opened on Friday - allow force close
                if await self._execute_momentum_stall_exit(position, state, current_R, market_data):
                    action_taken = True
        else:
            # Can't determine open time - allow force close to be safe
            if await self._execute_momentum_stall_exit(position, state, current_R, market_data):
                action_taken = True
    except Exception as grace_err:
        self.logger.debug("[FRIDAY_GRACE_PERIOD_ERROR] %s | Error checking grace period: %s | Allowing force close",
            position.symbol, grace_err)
        if await self._execute_momentum_stall_exit(position, state, current_R, market_data):
            action_taken = True
```

**Where in check_exit_conditions() method**:
- AFTER: All normal profit-taking exits (profit shaving, RSI exhaustion, etc.)
- ONLY IF: friday_force_close_window is True (Friday 16:00+ broker time)
- REPLACES: The original simple momentum stall exit on Friday

**How It Works**:
1. Gets position open time (opened_at or open_time)
2. Calculates hours since open
3. Converts open time to ET Friday check
4. If opened Friday AND within 2 hours: SKIP exit (grace period)
5. If opened Friday AND > 2 hours ago: Allow exit (grace expired)
6. If opened other day: Allow exit (not Friday-specific)
7. On any error: Allow exit (fail-safe)

**Impact**: Friday-opened positions protected 2 hours, entry/exit logic aligned

---

## Timezone Conversion Reference

All three blocks use the same timezone logic:

```python
# GET ET TIME FROM UTC
et_time = utc_time - timedelta(hours=5)

# CHECK THE DAY
is_friday = et_time.weekday() == 4  # Monday=0, Friday=4

# CHECK THE TIME
is_after_3pm = et_time.hour >= 15  # 15:00 = 3 PM
```

**Time Examples**:
| UTC Time | ET Time | Weekday | Hour | Friday 15:00+ | Blocked? |
|----------|---------|---------|------|--------------|----------|
| 19:00 UTC | 14:00 ET | Friday | 14 | NO (before 3pm) | ❌ NO |
| 20:00 UTC | 15:00 ET | Friday | 15 | YES | ✅ YES |
| 21:30 UTC | 16:30 ET | Friday | 16 | YES | ✅ YES |
| 21:00 UTC | 16:00 ET | Friday | 16 | YES | ✅ YES |
| 04:00 UTC | 23:00 ET | Thursday | 23 | NO (wrong day) | ❌ NO |

---

## Debug/Testing Log Lines

### To Verify Block #1 is Active
Search logs for:
```
[FRIDAY_PARADOX_BLOCK] .* | STRICT BLOCK: Friday after 15:00 ET
```

Expected: One entry per Institutional Sweep detected on Friday 15:00+ ET

---

### To Verify Block #2 is Active
Search logs for:
```
[FRIDAY_LATE_KILL_SWITCH] .* | Blocking entry
```

Expected: One entry per attempted order execution on Friday 15:00+ ET

---

### To Verify Block #3 is Active
Search logs for:
```
[FRIDAY_GRACE_PERIOD] .* | Position opened .* hours ago
```

Expected: One entry when Friday afternoon force close window active and position is protected

---

## Function Signatures (Copy/Paste)

### Block #1 Function
```python
def is_friday_critical_late_trading_hours(check_time: Optional[datetime] = None) -> bool:
    """Check if Friday after 15:00 ET"""
```

**Location**: main.py line 831  
**Usage**: `if is_friday_critical_late_trading_hours(velocity_timestamp):`

---

### Block #2 Function
```python
def is_friday_late_trading_risk(check_time: Optional[datetime] = None) -> bool:
    """Check if Friday after 15:00 ET"""
```

**Location**: src/trading/execution_engine.py line 30  
**Usage**: `if is_friday_late_trading_risk():`

---

## Manual Testing

### Test Block #1 (Entry Generation)
```python
from datetime import datetime, timezone, timedelta
from main import is_friday_critical_late_trading_hours

# Test Friday 16:00 ET (should be True)
utc_1600_friday = datetime(2026, 4, 3, 21, 0, tzinfo=timezone.utc)  # April 3=Friday, 21:00 UTC=16:00 ET
print(is_friday_critical_late_trading_hours(utc_1600_friday))  # Should print: True

# Test Friday 14:00 ET (should be False)
utc_1400_friday = datetime(2026, 4, 3, 19, 0, tzinfo=timezone.utc)  # April 3=Friday, 19:00 UTC=14:00 ET
print(is_friday_critical_late_trading_hours(utc_1400_friday))  # Should print: False

# Test Monday 16:00 ET (should be False - wrong day)
utc_1600_monday = datetime(2026, 3, 30, 21, 0, tzinfo=timezone.utc)  # March 30=Monday, 21:00 UTC=16:00 ET
print(is_friday_critical_late_trading_hours(utc_1600_monday))  # Should print: False
```

---

## Deployment Verification Checklist

- [ ] Locate main.py line 831 - verify utility function present
- [ ] Locate main.py line 5427 - verify Friday check applied  
- [ ] Locate execution_engine.py line 30 - verify utility function present
- [ ] Locate execution_engine.py line 390 - verify kill-switch applied
- [ ] Locate profit_protection_module.py line 1039 - verify grace period logic present
- [ ] Run: `python -m py_compile *.py` - verify no syntax errors
- [ ] Deploy and test Friday afternoon - verify logs appear
- [ ] Test Monday morning - verify normal operation resumes
- [ ] Monitor 2-3 weeks - verify no Friday suite loop recurrence

---

**All Changes Complete** ✅  
**Status**: DEPLOYMENT READY  
**Risk Level**: LOW (defensive-only changes, no positive logic modified)

---

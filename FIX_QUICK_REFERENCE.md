# Quick Fix Reference - TypeError in _check_entry_filters

## What Was Fixed
**File:** `main.py`
**Lines:** 5979, 5992-5993
**Issue:** Variable `original_entry_filters` was being set to STRING `"TRAP_DETECTED"` instead of the actual method reference

## The Changes

### Change 1: Add trap detection flag (Line 5979)
```python
# ADDED: New line to track trap detection separately
trap_detected = False
```

### Change 2: Use trap flag instead of corrupting method variable (Lines 5992-5993)
```python
# BEFORE (WRONG):
if _trap:
    original_entry_filters = "TRAP_DETECTED"  # ❌ Overwrites method reference!
    break

# AFTER (CORRECT):
if _trap:
    trap_detected = True  # ✅ Use separate flag
    break
```

## Why This Fixes the TypeError

1. **Before Fix:** 
   - `original_entry_filters` could be set to string `"TRAP_DETECTED"`
   - Later, this string was assigned to `strategy._check_entry_filters`
   - When code tried to **call** `self._check_entry_filters(...)`, it got: `TypeError: 'str' object is not callable`

2. **After Fix:**
   - `original_entry_filters` only holds method references (or None)
   - `trap_detected` holds the boolean status
   - When code calls `self._check_entry_filters(...)`, it works correctly

## Verification Steps

Run these commands to verify the fix:

```bash
# 1. Syntax check (should produce no output)
python -m py_compile main.py

# 2. Quick lint check
python -m pylint --errors-only main.py 2>&1 | head -20
```

## Expected Behavior After Fix

✅ **Trap detection still works:**
- Logs will show `[TRAP_VETO]` messages when traps are detected
- Signal rejection logic is intact

✅ **No more TypeError:**
- `_check_entry_filters` is always callable
- Trading cycle runs smoothly

## Integration Notes

- No changes needed to `trend_strategy.py`
- No changes to API or method signatures
- Fully backward compatible
- Existing trap detection logic preserved

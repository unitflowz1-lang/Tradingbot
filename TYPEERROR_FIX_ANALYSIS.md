# TypeError: '_check_entry_filters' - Root Cause & Fix

## 📋 Problem Summary
Your trading bot was repeatedly raising:
```
TypeError: 'str' object is not callable
```
When trying to call `self._check_entry_filters(indicators, timestamp=current_timestamp)` at line 1264 in `trend_strategy.py`.

---

## 🔍 Root Cause Analysis

### The Issue
The bug was **NOT** in `trend_strategy.py` itself, but in **`main.py`** at line 5992.

### What Was Happening

**In `main.py` lines 5978-5993:**
```python
original_entry_filters = None  # Line 5978 - Initialize correctly
try:
    if predictive_engine and historical_data:
        for _dir in (Direction.LONG, Direction.SHORT):
            # ... evaluation code ...
            if _trap:
                original_entry_filters = "TRAP_DETECTED"  # ❌ LINE 5992 - BUG HERE!
                break
```

**Later at line 6354 (restoration logic):**
```python
if original_entry_filters is not None:
    strategy._check_entry_filters = original_entry_filters  # ❌ Assigns string to method!
```

### The Flow of Corruption
1. Line 5978: `original_entry_filters` is correctly initialized as `None`
2. Line 5992: When trap detected, it's **incorrectly** set to the STRING `"TRAP_DETECTED"`
3. Line 6060: Inside `if structure_override_qualified:` block, it's set to the actual method
4. **Problem**: If `structure_override_qualified` is `False`, the string value persists
5. Line 6354: The restoration code assigns `original_entry_filters` (the string) back to `strategy._check_entry_filters`
6. Line 1264: When the code tries to call `self._check_entry_filters(...)`, Python raises `TypeError` because it's trying to call a string

---

## ✅ The Fix

### What Was Changed

**File: `main.py`**

**Before (Lines 5978-5993):**
```python
original_entry_filters = None
try:
    if predictive_engine and historical_data:
        for _dir in (Direction.LONG, Direction.SHORT):
            try:
                # ...
                if _trap:
                    original_entry_filters = "TRAP_DETECTED"  # ❌ WRONG
                    break
```

**After (Lines 5978-5993):**
```python
original_entry_filters = None
trap_detected = False  # ✅ Separate flag for trap status
try:
    if predictive_engine and historical_data:
        for _dir in (Direction.LONG, Direction.SHORT):
            try:
                # ...
                if _trap:
                    trap_detected = True  # ✅ Use separate flag
                    break
```

### Why This Works
- `original_entry_filters` **only stores method references** (or None)
- `trap_detected` **stores the boolean status** of trap detection
- The existing code at line 6545 already uses `trap_detected` for the hard veto logic
- Restoration at line 6354 now works correctly: assigns the actual method (or None)

---

## 📊 Code Flow After Fix

```
1. Initial state:
   - original_entry_filters = None
   - trap_detected = False

2. If trap is detected:
   - original_entry_filters = None (stays None)
   - trap_detected = True ✅

3. If structure override qualified:
   - original_entry_filters = strategy._check_entry_filters ✅
   - (overrides are applied)

4. At restoration (line 6354):
   - if original_entry_filters is not None:
       strategy._check_entry_filters = original_entry_filters ✅
   - (correctly assigns method back)

5. When called at line 1264:
   - self._check_entry_filters(...) ✅ WORKS (no TypeError)
```

---

## 🔧 Testing the Fix

To verify the fix works:

1. **Clear any cached states** (if applicable)
2. **Restart the trading bot**
3. **Monitor logs** for the error - it should NOT appear anymore
4. **Check for trap detection logs** - these will still work correctly with `trap_detected` flag

### Log Indicators
✅ **Good** - you'll see logs like:
```
[TRAP_VETO] EURUSD | Predictive engine detected sweep trap. Signal rejected.
```

❌ **Bad** (before fix) - you'd see:
```
TypeError: 'str' object is not callable
```

---

## 📝 Summary of Changes

| File | Line(s) | Change |
|------|---------|--------|
| main.py | 5979 | Added: `trap_detected = False` |
| main.py | 5992-5993 | Changed: `original_entry_filters = "TRAP_DETECTED"` → `trap_detected = True` |

The fix is **minimal, surgical, and preserves all existing functionality** while eliminating the TypeError.

---

## 🎯 Why This Bug Occurred

The code was trying to use a single variable (`original_entry_filters`) to serve two purposes:
1. Store the original method reference (for restoration)
2. Store trap detection status (for logging/flow control)

This conflation of concerns caused the string to contaminate the method reference. The fix properly separates these concerns using dedicated variables.

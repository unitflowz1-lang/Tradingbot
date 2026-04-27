# Trailing Stop Loss Logging - Before & After Comparison

## What Changed

The `check_symbol_trade_stops_level` function now provides **detailed diagnostic math** when blocking a Stop Loss modification, instead of just saying "too close to price."

---

## BEFORE (Old Behavior)

### When SL Was Blocked:
```
[STOP_LOSS_VALIDATION] Error checking SYMBOL_TRADE_STOPS_LEVEL for EUR/USD: ...
SL too close to price. Min distance: 0.002000 (20 pips), Current distance: 0.001500
```

**Problems**:
- Minimal information about the math
- Doesn't show current Bid/Ask
- Doesn't show proposed SL price
- Hard to calculate why it's blocked
- No visibility into how much more profit you need

---

## AFTER (New Behavior)

### When SL Is BLOCKED:

```
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION BLOCKED
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08750
  │  └─ Ask: 1.08755
  ├─ Proposed SL: 1.08600
  ├─ Current SL: 1.08500
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance (Price → Proposed SL): 0.001500 (15.0 pips)
  ├─ REQUIRED distance: 0.002000 (20 pips)
  └─ SHORTFALL: Need 0.000500 more pips (5.0 pips)
```

**New Information**:
- ✓ Current Bid: 1.08750
- ✓ Current Ask: 1.08755
- ✓ Proposed SL: 1.08600 (where you're trying to move it)
- ✓ Current SL: 1.08500 (where it currently is)
- ✓ Broker minimum: 20 pips = 0.002000 in price
- ✓ Your distance: 15.0 pips
- ✓ SHORTFALL: 5.0 pips (exactly how much more you need)

**Plus the additional log message**:

```
[MODIFICATION_GUARD] EURUSD ticket 12345 (BUY) | SL modification blocked: 
SL too close to price. Current: 1.08750, Proposed SL: 1.08600, Distance: 15.0 pips 
(need 20 pips). Shortfall: 5.0 pips
```

---

### When SL Is ACCEPTED:

```
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION VALID
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08900
  │  └─ Ask: 1.08905
  ├─ Proposed SL: 1.08600
  ├─ Current SL: 1.08500
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance (Price → Proposed SL): 0.003000 (30.0 pips)
  └─ Status: ✓ PASS (30.0 >= 20 required)
```

**Shows**:
- Current market prices (Bid/Ask)
- Where you're trying to move SL
- Distance achieved: 30.0 pips
- Requirement: 20 pips
- Status: ✓ PASS (sufficient margin)

---

## Side-by-Side Comparison

| Aspect | BEFORE | AFTER |
|--------|--------|-------|
| **Shows Bid?** | ✗ No | ✓ Yes |
| **Shows Ask?** | ✗ No | ✓ Yes |
| **Shows Proposed SL?** | ✗ No | ✓ Yes |
| **Shows Broker Min?** | ✓ Yes | ✓ Yes (with units) |
| **Shows Distance?** | ✓ Yes (rough) | ✓ Yes (exact in pips) |
| **Shows Shortfall?** | ✗ No | ✓ Yes (exact amount) |
| **Shows Acceptance?** | ✗ No | ✓ Yes (when valid) |
| **Formatted Clearly?** | ✗ One line | ✓ Tree structure |
| **Position Type?** | ✗ No | ✓ Yes (BUY/SELL) |
| **Log Level Separation?** | ✗ All same | ✓ Debug vs Warning |

---

## What You Can Now Diagnose

### Problem 1: "My SL moved but not as much as I wanted"

**Before**: No information to diagnose

**After**: Log shows exactly how much was possible:
```
Actual distance: 30.0 pips
Required: 20 pips
You have: 10.0 pips of extra cushion beyond broker minimum
```

### Problem 2: "Same position, sometimes SL moves, sometimes it doesn't"

**Before**: Can't see Bid/Ask variation

**After**: Shows Bid/Ask in every attempt:
```
Attempt 1: Bid 1.08750 → distance 15 pips → BLOCKED
Attempt 2: Bid 1.08760 → distance 16 pips → BLOCKED
Attempt 3: Bid 1.08770 → distance 17 pips → BLOCKED
Attempt 4: Bid 1.08775 → distance 17.5 pips → BLOCKED
Attempt 5: Bid 1.08790 → distance 19 pips → BLOCKED
Attempt 6: Bid 1.08800 → distance 20 pips → ACCEPTED ✓
```

You can now SEE the price movement that caused acceptance.

### Problem 3: "Broker always blocks me at this symbol"

**Before**: Generic message, no way to compare symbols

**After**: Shows SYMBOL_TRADE_STOPS_LEVEL for each symbol:
```
EUR/USD: Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips → Min profit: $2.00
GBP/USD: Broker SYMBOL_TRADE_STOPS_LEVEL: 25 pips → Min profit: $2.50
USD/JPY: Broker SYMBOL_TRADE_STOPS_LEVEL: 30 pips → Min profit: $3.00
```

Now you can pick the best symbol for your strategy.

---

## Code Changes Summary

### In `src/guards/terminal_state_guard.py`:

**What Changed**:
1. Enhanced `check_symbol_trade_stops_level()` function
2. Added detailed logging with tree-structured output
3. Now calculates and shows distance in BOTH price and pips
4. Shows SHORTFALL when blocked (exact amount needed)
5. Shows status icon (✓ PASS) when accepted
6. Accepts optional position_type parameter for clarity

**Logging Enhancements**:
```python
# Before:
logger.error(f"Error checking...")
return False, "SL too close..."

# After:
logger.warning(diagnostic_msg)  # Tree-formatted
logger.debug(valid_msg)         # Separate debug message
return False/True, detailed_reason
```

### In `src/data/mt5_broker.py`:

**What Changed**:
1. Enhanced call to `check_symbol_trade_stops_level()`
2. Now passes position_type (BUY/SELL) for better diagnostics
3. Improved log message includes position type and shortfall

**Updated Call**:
```python
# Before:
is_valid, msg = check_symbol_trade_stops_level(pos.symbol, pos.sl, final_sl)

# After:
pos_type_str = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
is_valid, msg = check_symbol_trade_stops_level(
    symbol=pos.symbol, 
    current_sl=pos.sl, 
    new_sl=final_sl,
    position_type=pos_type_str  # NEW: position context
)
```

---

## Log Examples in the Wild

### Real Example 1: Profit Too Small

```
# You: Entry 1.10000, Current 1.10030 (profit $3.00), Want SL at 1.09900
# Bot attempts modification...

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Current Market Prices:
  │  ├─ Bid: 1.10030
  │  └─ Ask: 1.10035
  ├─ Proposed SL: 1.09900
  ├─ Current SL: 1.09950
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance: 0.001300 (13.0 pips)
  ├─ REQUIRED distance: 0.002000 (20 pips)
  └─ SHORTFALL: Need 0.000700 more pips (7.0 pips)

[MODIFICATION_GUARD] EUR/USD ticket 54321 (BUY) | SL modification blocked:
SL too close to price. Current: 1.10030, Proposed SL: 1.09900, Distance: 13.0 pips 
(need 20 pips). Shortfall: 7.0 pips

# Diagnosis: You need $0.70 more profit (7 more pips)
```

### Real Example 2: Profit Sufficient

```
# You: Entry 1.10000, Current 1.10100 (profit $10.00), Want SL at 1.09850
# Bot attempts modification...

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION VALID
  ├─ Current Market Prices:
  │  ├─ Bid: 1.10100
  │  └─ Ask: 1.10105
  ├─ Proposed SL: 1.09850
  ├─ Current SL: 1.09950
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance: 0.002500 (25.0 pips)
  └─ Status: ✓ PASS (25.0 >= 20 required)

# Diagnosis: SL moved successfully. You have 5 pips of cushion beyond minimum.
```

### Real Example 3: Multiple Attempts Show Price Movement

```
# Same position, trailing stop trying to move multiple times...

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  Bid: 1.08750, Distance: 13.0 pips, SHORTFALL: 7.0 pips

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  Bid: 1.08765, Distance: 14.5 pips, SHORTFALL: 5.5 pips

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  Bid: 1.08780, Distance: 16.0 pips, SHORTFALL: 4.0 pips

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION VALID
  Bid: 1.08800, Distance: 20.0 pips, Status: ✓ PASS

# You can see exactly when price moved enough for SL to move
```

---

## How to Use This Information

### Step 1: Watch the Logs
While bot is running, search for: `[STOP_LOSS_VALIDATION]`

### Step 2: Note Key Values
From the log, write down:
- Current Bid/Ask
- Broker minimum (pips)
- Your distance (pips)
- Shortfall (pips)

### Step 3: Calculate What's Needed
```
Profit needed = Shortfall × 0.0001 × Lot_Size

Example:
  Shortfall: 7.0 pips
  Lot size: 1.0 standard
  Additional profit: 7.0 × 0.0001 × 1.0 = $0.70
```

### Step 4: Decide
- **Wait for more profit**: Likely solution for small shortfalls
- **Accept the position as-is**: If sufficient cushion exists
- **Switch symbols**: If this symbol's minimum is too high
- **Change broker**: If consistently problematic

---

## Verification Checklist

After update, verify you see:

- [ ] `[STOP_LOSS_VALIDATION] ... | SL MODIFICATION BLOCKED` (when blocked)
- [ ] Tree-formatted output with indentation (├─, │, └─)
- [ ] Bid and Ask prices shown separately
- [ ] Proposed SL and Current SL shown
- [ ] Broker SYMBOL_TRADE_STOPS_LEVEL value shown (in pips and price)
- [ ] Actual distance calculated (in both pips and price)
- [ ] SHORTFALL line (when blocked)
- [ ] Status: ✓ PASS (when accepted)
- [ ] Position type (BUY/SELL) in `[MODIFICATION_GUARD]` log

If all ✓ → Update applied successfully

---

## File Structure After Update

```
src/guards/
  ├── __init__.py (already existed)
  └── terminal_state_guard.py (ENHANCED with detailed logging)

src/data/
  └── mt5_broker.py (UPDATED call to enhanced function)
```

---

## Next: Practical Testing

### Quick Test Scenario:

1. Open bot logs
2. Create a BUY position manually in MT5
3. Check Symbol Specification for Stops level
4. Watch logs as bot tries to trail SL
5. Look for `[STOP_LOSS_VALIDATION]` messages
6. Note the Bid, Ask, Distance, and Shortfall
7. Verify the math matches your manual calculation
8. Wait for price to move more
9. Watch for SL to finally move when distance ≥ broker minimum

---

## FAQ: "Why So Much Detail?"

**Q**: Why show all this math?

**A**: Because the most common reason for "SL not moving" is insufficient profit margin relative to broker minimum. Now you can:
- See EXACTLY why it's blocked
- Calculate EXACTLY how much more you need
- Verify your strategy matches your broker's minimums
- Switch symbols or strategies if needed

**Q**: Isn't this verbose?

**A**: Only at WARNING level (when blocked). Successful modifications are DEBUG level (typically not shown). So you mainly see detail when there's a problem.

**Q**: Can I disable the detailed logging?

**A**: Yes - if you set the log level to ERROR or higher for this module:
```python
logging.getLogger("src.guards.terminal_state_guard").setLevel(logging.ERROR)
```

But we recommend keeping it at WARNING so you see the diagnostics.


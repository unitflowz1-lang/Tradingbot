# Fee-Adjusted Profit Lock in Dynamic Trailing Stop Loss

## Overview

The trailing stop loss manager now includes **accurate breakeven calculations** that account for all broker fees. Instead of locking profit at exactly the entry price, it locks at `entry_price + (commission + swap)`, ensuring that when the trade hits breakeven, your account balance actually recovers all trading costs.

## Problem Solved

### Before (Basic Breakeven)
```
Entry:          1.0900
Broker Fee:     -$5.00 (commission + swap)
Profit Lock SL: 1.0900 (entry price)

Trade hits SL at 1.0900
Account change: -$5.00 (fees not recovered!)
```

### After (Fee-Adjusted Breakeven)
```
Entry:          1.0900
Broker Fee:     -$5.00 (commission + swap)
Fee offset:     0.5 pips (convert $5 to pips)
Profit Lock SL: 1.0905 (entry price + fee offset)

Trade hits SL at 1.0905
Account change: $0.00 (all fees covered!)
```

---

## Implementation Details

### Data Structure: PositionTrailingState

New fields added to track fees:

```python
@dataclass
class PositionTrailingState:
    ticket: str
    symbol: str
    side: str
    entry_price: float
    current_sl: float
    
    # NEW: Broker fees for true breakeven calculation
    commission: float = 0.0      # Commission in dollars
    swap: float = 0.0            # Accumulated swap fees in dollars
    
    # ... rest of fields
```

### Fee-to-Price Conversion

The system converts dollar fees to price offsets:

**Formula:**
```
fee_in_pips = (commission + abs(swap)) / 10.0

price_offset = fee_in_pips * pip_value

For LONG:   profit_lock_sl = entry_price + price_offset
For SHORT:  profit_lock_sl = entry_price - price_offset
```

**Rationale:**
- Standard forex: 1 pip of major pair ≈ $10 per 1.0 lot
- The `/ 10.0` converts dollar amount to approximate pips
- Then multiply by `pip_value` (0.0001 for 5-decimal pairs) to get price offset

### Tracking API

#### 1. Track Position with Fees

```python
trailing_sl_manager.track_position(
    ticket="123456",
    symbol="EURUSD",
    side="LONG",
    entry_price=1.0900,
    current_sl=1.0850,
    commission=2.50,      # Broker charged $2.50
    swap=-2.50,           # Swap cost -$2.50 overnight
)
```

**Initial SL:** 1.0850 (your original protection)  
**Profit Lock SL:** 1.0905 (entry + $5 in fees converted to pips)

#### 2. Update Fees Dynamically

As swap accumulates overnight or additional fees apply:

```python
# After another night of swap accumulation
trailing_sl_manager.update_position_fees(
    ticket="123456",
    commission=2.50,      # Keep same commission
    swap=-5.00,           # Swap increased to -$5.00
)
```

**New Profit Lock SL:** 1.0912 (entry + $7.50 in fees)

#### 3. Continuous SL Tightening

Every main loop cycle:

```python
modified, reason = await trailing_sl_manager.update_trailing_sl(
    ticket="123456",
    current_price=1.0950,  # Current market price
)
# Returns: (True, "Profit locked (fees: $7.50)")
```

---

## Log Output Examples

### Position Tracked with Fees
```
[TRAILING_SL_TRACK] EURUSD | Ticket: 123456 | Side: LONG | Entry: 1.0900 | SL: 1.0850 | Commission: 2.500000 | Swap: -2.500000
```

### Fee Calculation During Profit Lock
```
[PROFIT_LOCK_CALC] EURUSD | Ticket: 123456 | Entry: 1.0900 | Commission: 2.500000 | Swap: -2.500000 | Fee Offset: 0.0005 | Lock SL: 1.0905
```

### Profit Lock Triggered
```
[CONTINUOUS_TRAIL_ACTIVE] EURUSD | Ticket: 123456 | SL tightened (Profit: $125.00) | SL moved to 1.0905 (fees: $5.00)
```

### Fees Updated
```
[FEE_UPDATE] EURUSD | Ticket: 123456 | Commission: 2.500000 -> 2.500000 | Swap: -2.500000 -> -5.000000
```

---

## Integration with main.py

The main trading loop automatically passes fees when tracking:

```python
# When position is first encountered
if pos_ticket not in trailing_sl_manager._positions:
    position_commission = float(getattr(position, 'commission', 0.0) or 0.0)
    position_swap = float(getattr(position, 'swap', 0.0) or 0.0)
    
    trailing_sl_manager.track_position(
        ticket=pos_ticket,
        symbol=position.symbol,
        side=side,
        entry_price=float(position.entry_price),
        current_sl=float(position.stop_loss or 0.0),
        commission=position_commission,    # Auto-extracted from Position
        swap=position_swap,                # Auto-extracted from Position
    )
```

---

## Configuration

### Enable/Disable Profit Lock

In `TrailingConfig`:

```python
trailing_config = TrailingConfig(
    enable_profit_lock=True,  # Enable fee-adjusted breakeven
    profit_lock_threshold_pips=20.0,  # Trigger after +20 pips profit
)
```

Or via environment variable:

```bash
# .env or .env.optimized
TRAILING_PROFIT_LOCK_THRESHOLD=20.0
```

---

## Fee Calculation Examples

### Example 1: LONG Position (EURUSD)

```
Entry Price:    1.0900
Commission:     $2.50
Swap:           -$2.50
Total Fees:     $5.00

Fee in pips:    5.00 / 10.0 = 0.5 pips
Price offset:   0.5 * 0.0001 = 0.00005

Profit Lock SL: 1.0900 + 0.00005 = 1.09005
```

When this SL is hit at 1.09005:
- Broker closes position
- Account recovers the $5.00 in fees
- Net result: Break-even

### Example 2: SHORT Position (GBPUSD)

```
Entry Price:    1.2700
Commission:     $3.00
Swap:           -$1.50
Total Fees:     $4.50

Fee in pips:    4.50 / 10.0 = 0.45 pips
Price offset:   0.45 * 0.0001 = 0.000045

Profit Lock SL: 1.2700 - 0.000045 = 1.269955
```

When this SL is hit at 1.269955:
- Broker closes SHORT position
- Account recovers the $4.50 in fees
- Net result: Break-even

---

## Testing Checklist

- [ ] Open a position manually
- [ ] Run bot, check logs for `[TRAILING_SL_TRACK]` with commission/swap values
- [ ] Verify commission and swap are extracted from Position object
- [ ] Wait for +20 pips profit
- [ ] Check logs for `[PROFIT_LOCK_CALC]` showing fee offset calculation
- [ ] Watch for `[CONTINUOUS_TRAIL_ACTIVE]` mentioning fees
- [ ] Manually check MT5: verify SL is above entry price (LONG) / below entry price (SHORT)
- [ ] If swap changes overnight, verify `[FEE_UPDATE]` logs
- [ ] Close position at breakeven price, verify account balance reflects fee recovery

---

## Manual Fee Update (Optional)

If fees change mid-trade and auto-extraction doesn't catch them:

```python
# In main.py or custom script
trailing_sl_manager.update_position_fees(
    ticket="123456",
    commission=3.50,  # Updated commission
    swap=-7.00,       # Updated swap after overnight hold
)
```

---

## Limitations & Considerations

1. **Fee Conversion Approximation**: The `/ 10.0` conversion assumes standard forex pricing. For unusual symbols (crypto, indices), adjust if needed.

2. **Swap Volatility**: Swap costs can change daily. Update fees periodically (e.g., after market open) for accuracy.

3. **Multiple Swaps**: If position held across multiple days, swap accumulates. Call `update_position_fees()` daily.

4. **Broker Minimums**: The profit lock SL still respects `SYMBOL_TRADE_STOPS_LEVEL`. If fee-adjusted SL is too close to price, broker will reject it.

5. **Partial Fills**: If position is partially filled, fees apply only to filled quantity. Adjust commission accordingly.

---

## Summary

✅ **What:** Profit lock now includes all broker fees  
✅ **Why:** Ensures true breakeven when SL hits  
✅ **How:** Entry price ± (commission + swap converted to pips)  
✅ **Where:** DynamicTrailingSLManager, auto-integrated in main.py  
✅ **When:** Every cycle, updated dynamically as fees change  

**Result:** Your "breakeven" SL actually breaks even. No fees left behind.

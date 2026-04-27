# Trailing Stop Loss Diagnostic Guide - Detailed Math Logging

## Overview

The bot now logs detailed diagnostic information when a trailing stop loss modification is blocked. This helps you determine if:
1. The broker's minimum SYMBOL_TRADE_STOPS_LEVEL is preventing the SL from moving
2. Your profit margin is too small for the broker's minimum distance requirement
3. Market prices have moved against your position

## What to Look For in Logs

### SUCCESS Log - SL Modification Accepted

When a stop loss modification is **APPROVED**, you'll see:

```
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION VALID
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08750
  │  └─ Ask: 1.08755
  ├─ Proposed SL: 1.08600
  ├─ Current SL: 1.08500
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance (Price → Proposed SL): 0.001500 (15.0 pips)
  └─ Status: ✓ PASS (15.0 >= 20 required)
```

**Read as**: "Current price is 1.08750. You want to move SL from 1.08500 to 1.08600. Distance is 15 pips, but broker requires 20 pips. This should have been BLOCKED, but if you see PASS, something is off."

---

### BLOCKED Log - SL Modification Rejected

When a stop loss modification is **REJECTED**, you'll see:

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

**Read as**: 
- Current Bid: 1.08750
- Your Proposed SL: 1.08600
- Distance: 15 pips
- Broker Minimum: 20 pips
- **SHORTFALL: You need 5 more pips to make this modification work**

---

## Understanding the Math

### Example Scenario 1: Profit Too Small for Broker Minimum

You have:
- Entry Price: 1.08900
- Current Price: 1.08750 (profit position)
- Proposed SL: 1.08600
- Your Profit: 1.08750 - 1.08900 = 0.0015 = **$1.50 per standard lot (or $150 if 100 micro lots)**

But the broker's SYMBOL_TRADE_STOPS_LEVEL is **20 pips**, meaning:
- SL must be at least: 1.08750 - 0.0020 = 1.08550

Your proposed SL of 1.08600 is **too close** (only 15 pips away from current price).

**Solution**: 
- Wait for price to move further in profit, or
- Accept a smaller profit and set SL closer to entry (if broker allows), or
- Set SL to the minimum: 1.08550

**Math Check**:
```
Current Price (Bid): 1.08750
Minimum SL allowed:  1.08750 - (20 pips × 0.0001) = 1.08550
Your proposed SL:    1.08600
Problem: 1.08600 > 1.08550 (SL is above minimum, should be below for BUY)
Result: BLOCKED ✗
```

---

### Example Scenario 2: Profit Margin Sufficient for Modification

You have:
- Entry Price: 1.08900
- Current Price: 1.08700 (larger profit)
- Proposed SL: 1.08500
- Your Profit: 0.0020 = **$20.00 per standard lot**

Broker's SYMBOL_TRADE_STOPS_LEVEL is **20 pips**, so:
- SL must be at least: 1.08700 - 0.0020 = 1.08500

Your proposed SL of 1.08500 is **exactly at the minimum**.

**Math Check**:
```
Current Price (Bid): 1.08700
Minimum SL allowed:  1.08700 - (20 pips × 0.0001) = 1.08500
Your proposed SL:    1.08500
Result: ACCEPTED ✓
```

---

## How to Check Your Broker's SYMBOL_TRADE_STOPS_LEVEL

### Manual Test (as you requested):

1. **Open MT5 Terminal**
2. **Right-click the symbol in Market Watch** (e.g., EURUSD)
3. **Select "Specification"**
4. **Find "Stops level"** field
5. **Note the value** (likely 20, 30, or 50 for forex)

**Example values**:
- Forex Major Pairs: Usually 20-30 pips
- Exotic Pairs: Usually 50-100 pips
- Indices: Usually 50-200 pips
- Metals: Usually 10-50 pips

---

## Diagnostic Workflow

### Question 1: Is my trailing stop blocked?

**Check the log**:
```
[MODIFICATION_GUARD] EURUSD ticket 12345 (BUY) | SL modification blocked: ...
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION BLOCKED
```

If you see these messages → Yes, it's blocked.

### Question 2: Why is it blocked?

**Look at the SHORTFALL line**:
```
└─ SHORTFALL: Need 0.000500 more pips (5.0 pips)
```

The SL is **5.0 pips too close** to the current price.

### Question 3: How much profit do I need to fix this?

**Calculation**:
```
Profit needed = (SYMBOL_TRADE_STOPS_LEVEL pips + Shortfall pips) × 0.0001

Example:
Profit needed = (20 pips + 5 pips) × 0.0001 = 0.0025 = $2.50 per standard lot
```

### Question 4: Can I work around this?

**Options**:
1. **Wait for more profit**: Let price move further, generating more cushion
2. **Lower your TP**: Accept smaller profits per trade
3. **Use wider SL**: Accept more risk per trade
4. **Switch brokers**: Different brokers have different SYMBOL_TRADE_STOPS_LEVEL values

---

## Real-World Example: EUR/USD

**Your Trade**:
- Entry: 1.10000 (BUY)
- Current Price: 1.10050
- Want to move SL from 1.09900 to 1.10000 (lock in breakeven)

**Broker Info**:
- SYMBOL_TRADE_STOPS_LEVEL: 20 pips
- Point value: 0.0001

**The Math**:
```
Current Bid: 1.10050
Proposed SL: 1.10000
Distance: 1.10050 - 1.10000 = 0.0005 = 5 pips
Required: 20 pips
Shortfall: 20 - 5 = 15 pips

Message: "SHORTFALL: Need 0.0015 more pips (15.0 pips)"

Solution: Wait until price reaches 1.10070 to have 20 pips cushion
```

---

## Log Interpretation Checklist

When you see a **BLOCKED** modification, check these:

- [ ] What is Current Bid/Ask?
- [ ] What is Proposed SL?
- [ ] What is SYMBOL_TRADE_STOPS_LEVEL?
- [ ] What is Actual distance vs Required distance?
- [ ] How much is the SHORTFALL?
- [ ] Is this a BUY or SELL position?
- [ ] How much profit would fix this shortfall?

---

## Common Issues & Solutions

### Issue 1: "SL modification constantly blocked at the same price"

**Likely Cause**: Broker's SYMBOL_TRADE_STOPS_LEVEL too large for your profit target

**Solution**: 
```python
# Check the log for SYMBOL_TRADE_STOPS_LEVEL value
# If it's 50+ pips, your $3 profit = 30 pips max, which is insufficient

# Workaround:
# 1. Increase lot size (smaller pip value per lot)
# 2. Switch to pairs with smaller SYMBOL_TRADE_STOPS_LEVEL
# 3. Accept narrower profit targets
```

### Issue 2: "Sometimes blocked, sometimes not"

**Likely Cause**: Market volatility moving the Bid/Ask around

**Solution**:
```python
# SL blocking depends on current price
# High volatility = Bid/Ask jumping around
# This causes distance calculations to vary

# Look at the logs to see how much Bid/Ask is moving
# Example:
#   Bid: 1.08750 → SL blocked
#   Bid: 1.08755 → SL accepted (5 pips move)
```

### Issue 3: "SL finally moved, but only slightly"

**Likely Cause**: SL moved to exactly the minimum allowed distance

**Solution**: This is normal. Your SL is now at the broker's minimum. To move it further:
```python
# You need proportionally more profit
# Current: 20 pips minimum
# To move it 5 more pips: need 25 pips total distance
```

---

## Debugging Commands

If you want to manually check a symbol:

```python
import MetaTrader5 as mt5

symbol = "EURUSD"
info = mt5.symbol_info(symbol)
tick = mt5.symbol_info_tick(symbol)

print(f"Symbol: {symbol}")
print(f"Point: {info.point}")
print(f"SYMBOL_TRADE_STOPS_LEVEL: {info.trade_stops_level} pips")
print(f"Min distance allowed: {info.trade_stops_level * info.point}")
print(f"Current Bid: {tick.bid}")
print(f"Current Ask: {tick.ask}")

# Calculate for your SL
your_sl = 1.08600
distance = abs(tick.bid - your_sl)
min_distance = info.trade_stops_level * info.point

print(f"\nYour SL: {your_sl}")
print(f"Distance from Bid: {distance:.6f} ({distance/info.point:.1f} pips)")
print(f"Min required: {min_distance:.6f} ({info.trade_stops_level} pips)")
print(f"Valid? {distance >= min_distance}")
```

---

## Log Levels Explained

| Level | Example | Meaning |
|-------|---------|---------|
| **WARNING** | `[STOP_LOSS_VALIDATION] EURUSD \| SL MODIFICATION BLOCKED` | SL blocked due to broker minimum |
| **DEBUG** | `[STOP_LOSS_VALIDATION] EURUSD \| SL MODIFICATION VALID` | SL accepted (debug level, may not see in production) |
| **WARNING** | `[MODIFICATION_GUARD] EURUSD ticket 12345` | Broader context of why modification was rejected |

---

## Expected Behavior After Update

### When SL CAN move:
```
✓ Price has moved enough in profit
✓ Distance to price ≥ Broker's SYMBOL_TRADE_STOPS_LEVEL
✓ Log shows: [STOP_LOSS_VALIDATION] ... SL MODIFICATION VALID
✓ SL updates successfully
```

### When SL CANNOT move:
```
✗ Price hasn't moved enough in profit
✗ Distance to price < Broker's SYMBOL_TRADE_STOPS_LEVEL
✗ Log shows: [STOP_LOSS_VALIDATION] ... SL MODIFICATION BLOCKED
✗ Log shows SHORTFALL: tells you how many more pips you need
✗ SL stays at current level
```

---

## Quick Reference: Distance Calculations

```
For BUY positions:
  Distance = Current_Bid - Proposed_SL (should be > 0)
  Example: 1.08750 - 1.08600 = 0.00150 = 15 pips

For SELL positions:
  Distance = Proposed_SL - Current_Ask (should be > 0)
  Example: 1.08600 - 1.08750 = -0.00150 (wrong sign, need SL above price)
  Correct: 1.08850 - 1.08750 = 0.00100 = 10 pips

Minimum required:
  Min_Distance = SYMBOL_TRADE_STOPS_LEVEL × Point
  Example: 20 × 0.0001 = 0.0020 = 2.0 cents per unit
```

---

## Next Steps

1. **Run the bot** with these enhanced logs
2. **Watch for [STOP_LOSS_VALIDATION]** messages
3. **Note your broker's SYMBOL_TRADE_STOPS_LEVEL** from the logs
4. **Calculate**: Do you have enough profit margin for that level?
5. **Verify manually** by checking MT5 Symbol Specification
6. **Adjust your strategy** based on findings:
   - Larger lot sizes
   - Wider profit targets
   - Different symbols
   - Different broker


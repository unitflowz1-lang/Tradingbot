# Trailing Stop Loss - Quick Manual Test Reference

## Manual Test Steps (As Requested)

### Step 1: Check Your Broker's Minimum Distance Setting

1. **Open MT5 Terminal**
2. **Find your trading symbol in Market Watch** (e.g., EURUSD)
3. **Right-click the symbol**
4. **Select "Specification"**
5. **Look for: "Stops level"**
6. **Write down the value** (e.g., 20, 30, 50, etc.)

**Example Symbol Specification Window**:
```
EURUSD
├─ Symbol: EURUSD
├─ Bid: 1.08750
├─ Ask: 1.08755
├─ ...
├─ Stops level: 20        ← THIS IS WHAT YOU NEED
├─ Freeze level: 0
└─ ...
```

---

## What "Stops level: 20" Means

```
"Stops level: 20" = Minimum distance is 20 POINTS (pips for forex)

For EURUSD (4 decimal places):
  20 points = 20 × 0.0001 = 0.0020
  In profit terms: $2.00 per standard lot, $0.20 per micro lot
```

---

## Quick Profit Calculation

### Your Trade Profit Check:

| Your Profit | 20 Points Min | 30 Points Min | 50 Points Min |
|-------------|---------------|---------------|---------------|
| $1.00       | ✗ NOT ENOUGH | ✗ NOT ENOUGH | ✗ NOT ENOUGH |
| $2.00       | ✓ JUST ENOUGH | ✗ NOT ENOUGH | ✗ NOT ENOUGH |
| $3.00       | ✓ OK (5.0 pips cushion) | ✗ NOT ENOUGH | ✗ NOT ENOUGH |
| $4.00       | ✓ GOOD (20.0 pips cushion) | ✓ JUST ENOUGH | ✗ NOT ENOUGH |
| $5.00       | ✓ GOOD (30.0 pips cushion) | ✓ GOOD (20.0 pips cushion) | ✓ JUST ENOUGH |

**Read as**: 
- If your profit is $3.00 and broker minimum is 20 points → You have 5 pips of wiggle room
- If your profit is $3.00 and broker minimum is 30 points → NOT ENOUGH, needs 3 more pips

---

## Formula: Calculate Required Profit

```
Required Profit = Broker_Minimum_Pips × Lot_Size × 0.0001

Example:
  Broker minimum: 20 pips
  Lot size: 1.0 standard
  Required: 20 × 1.0 × 0.0001 = 0.0020 = $2.00

Another Example:
  Broker minimum: 50 pips
  Lot size: 0.5 standard
  Required: 50 × 0.5 × 0.0001 = 0.0025 = $2.50
```

---

## Real-Time Diagnostic During Bot Run

### Watch for These Exact Log Patterns:

#### Pattern 1: SL BLOCKED (Explains Why)

```
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION BLOCKED
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08750        ← Current market
  │  └─ Ask: 1.08755
  ├─ Proposed SL: 1.08600   ← Where you want to move it
  ├─ Current SL: 1.08500    ← Where it is now
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000
  │                                   ↑ ANSWER: Your broker requires this
  ├─ Actual distance (Price → Proposed SL): 0.001500 (15.0 pips)
  │                                          ↑ What you have
  ├─ REQUIRED distance: 0.002000 (20 pips)
  └─ SHORTFALL: Need 0.000500 more pips (5.0 pips)
                ↑ HOW MUCH MORE YOU NEED
```

**Translation**: "Price is at 1.08750. You want SL at 1.08600 (15 pips away). Broker requires 20 pips. You're 5 pips short."

#### Pattern 2: SL ACCEPTED (Ready to Move)

```
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION VALID
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08900        ← Current market
  │  └─ Ask: 1.08905
  ├─ Proposed SL: 1.08600   ← Where you want to move it
  ├─ Current SL: 1.08500    ← Where it is now
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000
  ├─ Actual distance (Price → Proposed SL): 0.003000 (30.0 pips)
  └─ Status: ✓ PASS (30.0 >= 20 required)
```

**Translation**: "Price is at 1.08900. You want SL at 1.08600 (30 pips away). Broker requires 20 pips. ✓ APPROVED"

---

## Debug Checklist During Testing

### When SL is NOT moving:

- [ ] Check logs for `[STOP_LOSS_VALIDATION] ... BLOCKED`
- [ ] Note the **Broker SYMBOL_TRADE_STOPS_LEVEL** value
- [ ] Note the **SHORTFALL** value (pips needed)
- [ ] Calculate: Do you have enough profit to cover shortfall?
- [ ] Check MT5 Specification to verify broker minimum
- [ ] Wait for price to move further in profit
- [ ] Try moving SL again

### When SL IS moving:

- [ ] Check logs for `[STOP_LOSS_VALIDATION] ... VALID`
- [ ] Verify logs show distance ≥ broker minimum
- [ ] Confirm position is in sufficient profit
- [ ] Note how much cushion you have beyond minimum
- [ ] Record this for future reference (repeatable pattern)

---

## Decision Tree: Why Is My Trailing Stop Not Moving?

```
Question: SL not moving
│
├─ Check logs for [STOP_LOSS_VALIDATION] BLOCKED?
│  │
│  ├─ YES → See SHORTFALL line
│  │  │
│  │  └─ Multiply Shortfall × Lot_Size × 0.0001 = Extra $ needed
│  │     Example: 5 pips × 1.0 lot × 0.0001 = $0.50 more needed
│  │
│  └─ NO → Different reason, check [MODIFICATION_GUARD] logs
│
├─ Is your profit > Broker minimum?
│  │
│  ├─ YES (but BLOCKED) → Profit exists but too close to price
│  │  └─ Solution: Wait for more price movement, or
│  │            broker has additional restrictions
│  │
│  └─ NO → Profit too small
│     └─ Solution: Wait for more profit, or
│              adjust lot size/strategy
│
└─ END: Either wait for price to move, or change strategy
```

---

## Symbol Specifications to Collect

For your common trading pairs, manually check and record:

### EUR/USD
```
Stops level: _____ pips
Min profit needed: _____ ($)
```

### GBP/USD
```
Stops level: _____ pips
Min profit needed: _____ ($)
```

### USD/JPY
```
Stops level: _____ pips
Min profit needed: _____ ($)
```

### USD/CAD
```
Stops level: _____ pips
Min profit needed: _____ ($)
```

### USD/CHF
```
Stops level: _____ pips
Min profit needed: _____ ($)
```

**Once collected**, you'll know exactly how much profit each pair needs before the trailing stop can move.

---

## Example Walkthrough: EURUSD Trade

### Setup
```
Entry:  1.10000 (BUY)
Current: 1.10050
Profit: $5.00 (0.0050 = 50 pips)
Lot: 1.0 standard
```

### Step 1: Check MT5 Specification
```
Right-click EURUSD → Specification → Stops level: 20 pips
```

### Step 2: Try to Move SL
```
Bot tries to set SL = 1.10000 (lock breakeven)
Distance = 1.10050 - 1.10000 = 0.0050 = 50 pips
Required = 20 pips
Result = 50 >= 20 ✓ APPROVED
```

### Step 3: Watch the Logs
```
[STOP_LOSS_VALIDATION] EURUSD | SL MODIFICATION VALID
  Actual distance: 0.005000 (50.0 pips)
  Required distance: 0.002000 (20 pips)
  Status: ✓ PASS
```

### Step 4: Conclusion
✓ SL moved successfully because profit was sufficient (50 pips > 20 pips required)

---

## If SL Still Not Moving After Update

### Verify the Update is Live

1. Open [src/guards/terminal_state_guard.py](src/guards/terminal_state_guard.py)
2. Search for: `[STOP_LOSS_VALIDATION]`
3. Should find the function with detailed diagnostics
4. If not found → update wasn't applied, try again

### Enable Debug Logging

Add to your logging config:
```python
logging.getLogger("src.guards.terminal_state_guard").setLevel(logging.DEBUG)
```

### Check Bot Startup

```python
# Should see on bot startup:
[INIT] >> AI Forex Trading Bot Starting...
[RUNTIME_PHASE] ...
# If using new guard:
from src.guards.terminal_state_guard import ...  # Should import successfully
```

---

## Quick Math Reference Cards

### Card 1: Pips to Dollars
```
Forex (4 decimals):
  1 pip = $0.0001 per standard lot
  20 pips = $2.00 per standard lot
  50 pips = $5.00 per standard lot

Example:
  Your profit = $3.00
  = 30 pips per standard lot
  = 3 pips per 0.1 lot
  = 0.3 pips per 0.01 lot (micro)
```

### Card 2: How Much Profit to Cover Broker Min
```
Formula: Minimum_Pips × 0.0001 × Lot_Size = Profit_$

If broker min = 20 pips, lot = 1.0:
  20 × 0.0001 × 1.0 = $2.00 minimum

If broker min = 50 pips, lot = 0.5:
  50 × 0.0001 × 0.5 = $2.50 minimum

If broker min = 30 pips, lot = 0.1 (micro):
  30 × 0.0001 × 0.1 = $0.30 minimum
```

### Card 3: Shortfall to Extra Profit Needed
```
If logs show: SHORTFALL: Need 0.000500 more (5.0 pips)

You need: 5.0 × 0.0001 × Lot_Size more dollars

Example (1.0 lot):
  5.0 × 0.0001 × 1.0 = $0.50 more
  Wait for price to move 5 more pips in profit
```

---

## Support Checklist

Before troubleshooting, confirm:

- [ ] Bot running with updated `src/guards/terminal_state_guard.py`
- [ ] Logs showing `[STOP_LOSS_VALIDATION]` messages
- [ ] You checked MT5 Symbol Specification for Stops level
- [ ] You calculated required profit margin
- [ ] You verified current trade profit vs. requirement
- [ ] You waited for sufficient price movement to meet minimum distance

If all above are ✓ and SL still not moving → Different issue, not broker minimum related.


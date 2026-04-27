# Trailing Stop Diagnostic Logging - Quick Start

## ✅ What's Updated

The `check_symbol_trade_stops_level()` function now provides **detailed diagnostic logging** when a Stop Loss modification is blocked. You'll see:

```
Current Bid/Ask prices
↓
Proposed SL price
↓
Broker SYMBOL_TRADE_STOPS_LEVEL requirement
↓
Actual distance from price to your SL
↓
SHORTFALL (exactly how much more you need)
```

## 🚀 How to Test It

### Step 1: Verify Update is Applied

Open: `src/guards/terminal_state_guard.py`

Search for: `SL MODIFICATION BLOCKED`

Should find the tree-formatted diagnostic log (~250 lines in)

### Step 2: Start the Bot

```powershell
python main.py
```

### Step 3: Create a Test Trade

1. In MT5, manually open a BUY or SELL position
2. Make sure it's profitable (at least $2-5 profit)
3. Let the bot run for a few cycles

### Step 4: Check the Logs

Search the logs for: `[STOP_LOSS_VALIDATION]`

You should see output like:

#### If SL is BLOCKED:
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

**Interpretation**: You need 5 more pips of profit to unlock the SL movement.

#### If SL is ACCEPTED:
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

**Interpretation**: SL moved successfully! You have 10 pips of cushion beyond broker minimum.

## 📊 How to Interpret the Math

### Example: EURUSD Trade

**Your Trade**:
- Entry: 1.10000 (BUY)
- Current: 1.10050
- Profit: $5.00 (50 pips)

**From the Log**:
```
Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
Actual distance: 0.003000 (30.0 pips)
REQUIRED distance: 0.002000 (20 pips)
Status: ✓ PASS
```

**Translation**: 
- Broker minimum: 20 pips
- You have: 30 pips from price to proposed SL
- Result: SL can move (30 > 20) ✓

---

### Example: Insufficient Profit

**Your Trade**:
- Entry: 1.10000 (BUY)
- Current: 1.10025
- Profit: $2.50 (25 pips)

**From the Log**:
```
Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
Actual distance: 0.001500 (15.0 pips)
REQUIRED distance: 0.002000 (20 pips)
SHORTFALL: Need 0.000500 more pips (5.0 pips)
```

**Translation**:
- Broker minimum: 20 pips
- You have: 15 pips from price to proposed SL
- Shortfall: 5 pips
- Solution: Wait for 5 more pips of profit, then SL can move

---

## 🔍 Diagnosis Checklist

When you see SL NOT moving:

- [ ] Look for `[STOP_LOSS_VALIDATION] ... BLOCKED`
- [ ] Check the **SHORTFALL** line
- [ ] Note how many pips you're short
- [ ] Calculate: Shortfall × 0.0001 × Lot_Size = Extra $ needed
- [ ] Wait for price to move that many pips more in profit
- [ ] SL should move on next cycle after target reached

---

## 📋 Manual Verification (Optional)

### Check Your Broker's Minimum

1. Open MT5 Terminal
2. Right-click symbol in Market Watch (e.g., EURUSD)
3. Click "Specification"
4. Find "Stops level" field
5. Note the value (should match log output)

**Example**:
```
Specification: EURUSD
├─ Bid: 1.08750
├─ Ask: 1.08755
├─ ...
├─ Stops level: 20        ← This should match your logs
└─ ...
```

---

## 💡 Common Scenarios

### Scenario 1: "SL moves after bigger profit"

**What's happening**:
- Small profit → SL blocked (too close to price)
- Profit grows → SL unblocks and moves
- This is **normal behavior** - log shows exactly when threshold is crossed

### Scenario 2: "Same trade, SL sometimes moves, sometimes doesn't"

**What's happening**:
- Price volatility = Bid/Ask moving around
- When Bid goes up → more distance → SL can move
- When Bid goes down → less distance → SL blocked
- This is **market behavior** - log shows Bid/Ask in each attempt

### Scenario 3: "Different symbols, different behavior"

**What's happening**:
- Different brokers/symbols have different SYMBOL_TRADE_STOPS_LEVEL values
- EUR/USD: 20 pips minimum
- GBP/USD: 30 pips minimum  
- USD/JPY: 25 pips minimum
- This is **broker-specific** - use the most favorable for your strategy

---

## 🛠️ Troubleshooting

### Q: I don't see [STOP_LOSS_VALIDATION] messages

**Check**:
1. Is the bot running?
2. Are there any profitable positions?
3. Check log file (bot_output.log or similar)
4. Verify src/guards/terminal_state_guard.py was updated

### Q: I see ERROR instead of WARNING

**Check**:
1. Exception in the validation function
2. Symbol not found in MT5
3. Cannot get tick price
4. These are rare - indicates MT5 connection issue

### Q: All modifications show BLOCKED

**Check**:
1. Is profit sufficient? (profit $ / lot size ≥ minimum pips × 0.0001)
2. What's the SHORTFALL amount?
3. Can you increase lot size to reduce pips needed?
4. Can you find symbols with lower SYMBOL_TRADE_STOPS_LEVEL?

---

## 📈 Expected Results

### First 30 minutes:
- Bot will log [STOP_LOSS_VALIDATION] several times
- Mix of BLOCKED and VALID results likely
- Each log shows exact math for that attempt

### After 1 hour:
- You'll have pattern data for your common symbols
- Know broker minimum for each pair
- Know roughly how much profit needed for SL to move

### After 1 trading day:
- Can confidently say: "This broker/symbol combo works" or "Need different strategy"
- Can set expectations: "Need $X profit before SL can trail"
- Can optimize: "Use this symbol when I have Y% profit target"

---

## 📝 Sample Log Walkthrough

### Real Bot Output (Simulation)

```
[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08750
  │  └─ Ask: 1.08755
  ├─ Proposed SL: 1.08600
  ├─ Current SL: 1.08500
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance (Price → Proposed SL): 0.001500 (15.0 pips)
  ├─ REQUIRED distance: 0.002000 (20 pips)
  └─ SHORTFALL: Need 0.000500 more pips (5.0 pips)

[MODIFICATION_GUARD] EUR/USD ticket 54321 (BUY) | SL modification blocked:
SL too close to price. Current: 1.08750, Proposed SL: 1.08600, Distance: 15.0 pips
(need 20 pips). Shortfall: 5.0 pips

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08760
  ├─ Actual distance: 0.001600 (16.0 pips)
  └─ SHORTFALL: Need 0.000400 more pips (4.0 pips)

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08765
  ├─ Actual distance: 0.001650 (16.5 pips)
  └─ SHORTFALL: Need 0.000350 more pips (3.5 pips)

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08770
  ├─ Actual distance: 0.001700 (17.0 pips)
  └─ SHORTFALL: Need 0.000300 more pips (3.0 pips)

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08775
  ├─ Actual distance: 0.001750 (17.5 pips)
  └─ SHORTFALL: Need 0.000250 more pips (2.5 pips)

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08780
  ├─ Actual distance: 0.001800 (18.0 pips)
  └─ SHORTFALL: Need 0.000200 more pips (2.0 pips)

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08785
  ├─ Actual distance: 0.001850 (18.5 pips)
  └─ SHORTFALL: Need 0.000150 more pips (1.5 pips)

--- [2 minutes later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION BLOCKED
  ├─ Bid: 1.08790
  ├─ Actual distance: 0.001900 (19.0 pips)
  └─ SHORTFALL: Need 0.000100 more pips (1.0 pips)

--- [1 minute later] ---

[STOP_LOSS_VALIDATION] EUR/USD | SL MODIFICATION VALID
  ├─ Current Market Prices:
  │  ├─ Bid: 1.08800
  │  └─ Ask: 1.08805
  ├─ Proposed SL: 1.08600
  ├─ Current SL: 1.08500
  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: 20 pips = 0.002000 price
  ├─ Actual distance (Price → Proposed SL): 0.002000 (20.0 pips)
  └─ Status: ✓ PASS (20.0 >= 20 required)

[MODIFICATION_GUARD] EUR/USD ticket 54321 (BUY) | SL modification accepted
(logs show successful modification at 1.08600)
```

**What This Shows**:
1. SL blocked 9 consecutive times as price inched up
2. Each attempt shows Bid moving slightly (750 → 800)
3. Each attempt shows distance improving (15.0 → 20.0 pips)
4. Finally at Bid 1.08800, distance hits 20.0 pips (threshold)
5. SL accepted and moved successfully ✓

This is **exactly what you want to see** - it shows the system is working correctly!

---

## ✨ Summary

- ✅ Update applied to `check_symbol_trade_stops_level()`
- ✅ Logs now show detailed math for every SL modification attempt
- ✅ Can diagnose why SL is/isn't moving
- ✅ Can calculate exactly how much more profit needed
- ✅ Can see price movement cycle in real-time logs

**Next step**: Run the bot and watch the `[STOP_LOSS_VALIDATION]` logs to understand your broker's specific requirements for each symbol!


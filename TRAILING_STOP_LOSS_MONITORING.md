# Dynamic Trailing Stop Loss - Monitoring Guide
**Quick Reference for Real-Time Verification**

---

## Log Messages to Watch For

### ✅ Successful Trailing Stop Updates

When SL is successfully moved, look for:

```
[TRAILING_SL_UPDATED] EUR/USD: Trailing SL moved up
[TRAILING_SL_UPDATED] GBP/USD: Profit locked
[CONTINUOUS_TRAIL_ACTIVE] USD/JPY | Ticket: 12345 | Price: 1.0890 | New SL: 1.0885
```

**What it means:** SL successfully locked in gains by moving in profit direction

---

### ⏱️ Time Throttle Messages

When updates are blocked by throttling:

```
Time throttle: 0.2s < 0.5s
```

**What it means:** Update blocked - must wait for minimum time between modifications  
**Expected:** Every position's first update after tracking will see this

---

### 📊 Modification History in Logs

Look for entries like:

```
[TRAILING_SL_UPDATED] EUR/USD | Ticket: 12345 | Side: LONG |
  Price: 1.0880 | New SL: 1.0875 | Profit: 30.0 pips
```

**Meaning:**
- Position at 1.0880 (30 pips profit vs 1.0850 entry)
- SL moved to 1.0875 (5 pips buffer below price)
- Position now protected - max loss is 5 pips

---

## How to Monitor in Real-Time

### Method 1: Watch Bot Console Output

Run bot and grep for trailing SL messages:

```powershell
# Start bot
python main.py 2>&1 | Select-String "TRAILING_SL"

# Or search log file
Select-String "TRAILING_SL" bot_output.log | Select-Object -Last 10
```

Expected output per position:
```
[TRAILING_SL_UPDATED] EUR/USD: Profit locked
[TRAILING_SL_UPDATED] GBP/USD: Trailing SL moved up
[TRAILING_SL_UPDATED] USD/JPY: Trailing SL moved up
```

### Method 2: Monitor Position Statistics

Look for stats that show trailing SL activity:

```
[POSITION STATS] EUR/USD Ticket: 12345
  Entry: 1.0850
  Current Price: 1.0880 (+30 pips)
  Current SL: 1.0875 (5 pips buffer)
  TP: 1.0950
```

---

## Behavior Checklist - What You Should See

### For Each Position in Profit:

✅ **First update:** Throttled (0.0s < 0.5s) → This is NORMAL
```
Time throttle: 0.0s < 0.5s
```

✅ **After 0.5s+ has passed:** SL updates successfully
```
[TRAILING_SL_UPDATED] EUR/USD: Trailing SL moved up
```

✅ **As position stays in profit:** Multiple SL updates (one every 0.5s minimum)
```
[TRAILING_SL_UPDATED] EUR/USD | Price: 1.0880 | New SL: 1.0875
[TRAILING_SL_UPDATED] EUR/USD | Price: 1.0890 | New SL: 1.0885
[TRAILING_SL_UPDATED] EUR/USD | Price: 1.0895 | New SL: 1.0890
```

✅ **When profit reaches +20 pips:** Profit lock activated
```
[TRAILING_SL_UPDATED] EUR/USD: Profit locked
```

---

## Red Flags - What to Investigate

### ❌ No TRAILING_SL messages at all
**Problem:** Positions may not be tracked or engine not running  
**Solution:** Check that `_update_trailing_stops()` is called in main loop

### ❌ Same SL value stays constant
**Problem:** SL isn't moving even though price is moving  
**Investigation:**
- Is price moving ≥5 pips from last modification?
- Has 0.5s passed since last modification?
- Check `min_pip_movement` and `min_time_between_mods_seconds` config

### ❌ Modification rejected errors
**Messages like:**
```
[TRAILING_SL_MODIFY_FAILED] EUR/USD | Failed to modify SL to X
[SL_MOD_REJECTED] EUR/USD | SL too close: distance X < min_dist Y
```

**Problem:** Broker constraints violated (Error 10016 prevention)  
**Solution:** SL is too close to current price. Built-in safety working correctly.

### ❌ AutoTrading disabled message
```
[TRAILING_SL_AUTOTRADING_CHECK] AutoTrading is disabled in MT5 GUI.
```

**Problem:** MT5's AutoTrading toggle is OFF  
**Solution:** Enable AutoTrading in MT5 terminal to allow SL modifications

---

## Configuration to Monitor

Your current configuration (from `src/trading/dynamic_trailing_sl_manager.py`):

```python
buffer_pips=5.0                          # SL stays 5 pips from price
min_time_between_mods_seconds=0.5       # Wait 0.5s between updates
min_pip_movement=0.0005                 # Need ≥5 pips move to update
enable_profit_lock=True                 # Lock to break-even at +20 pips
profit_lock_threshold_pips=20.0         # Activation point for profit lock
```

To verify these are active:
```
[TRAILING_SL_INIT] Manager initialized | 
  Buffer: 5 pips | Min time: 0.5 sec | Min movement: 0.000500
```

---

## Example: Full Trade Life Cycle

### Entry
```
Time 12:00:00
Entry: EUR/USD LONG at 1.0850
SL: 1.0800 (50 pips risk)
TP: 1.0950
Ticket: 12345

[TRAILING_SL_INIT] Position tracked
```

### Price moves UP +25 pips to 1.0875
```
Time 12:00:03
Time throttle: 0.0s < 0.5s
Status: BLOCKED (normal safety measure)
```

### Wait 0.5s, Price at 1.0880 (+30 pips)
```
Time 12:00:03.5
[TRAILING_SL_UPDATED] EUR/USD | Price: 1.0880 | New SL: 1.0875
Status: SL moved UP 75 pips! (from 1.0800 to 1.0875)
Profit locked: 25 pips minimum guaranteed
```

### Price continues UP to 1.0895 (+45 pips)
```
Time 12:00:04.1
[TRAILING_SL_UPDATED] EUR/USD | Price: 1.0895 | New SL: 1.0890
Status: SL continues following price
Profit locked: 40 pips minimum guaranteed
```

### Market reversal, price drops to 1.0891
```
Time 12:00:10
Price: 1.0891 (still +41 pips vs entry)
SL: 1.0890 (last locked position)
Status: Position protected! SL won't move down (locks gains)
```

### Price continues down to 1.0890
```
Time 12:00:11
Price: 1.0890 = STOP LOSS HIT
Exit: 1.0890
Profit: +40 pips locked ✅
```

---

## Performance Expectations

### Update Frequency
- First position tracked: 1 update after 0.5s
- Subsequent updates: ~1 update per 0.5s while price moving favorably
- If price stalls: 1 update to lock last high, then no more updates

### Typical Profit Protection
- Without trailing SL: -50 to +50 pips (exposed to reversals)
- With trailing SL: +25 to +50+ pips (reversals capped at 5 pips loss)

### Spam Prevention
- Modifications per minute: ~120 maximum (one per 0.5s)
- Actual rate: Much lower (only when price moves ≥5 pips)
- Broker friendly: Won't trigger throttling or Error 10016

---

## Test Your Setup

Run diagnostic to verify trailing SL is active:

```bash
# Run diagnostic test
python diagnose_trailing_sl.py

# Expected output:
# ✅ DIAGNOSIS: LONG position SL follows price correctly
```

---

## Summary

Your trailing stop loss is:
- ✅ **Active** - Updates tracked in logs
- ✅ **Protective** - Locks profits as position moves favorably
- ✅ **Smart** - Throttled to prevent broker spam
- ✅ **Safe** - Broker constraints automatically enforced

Monitor the `[TRAILING_SL_UPDATED]` messages to verify it's working on your positions!

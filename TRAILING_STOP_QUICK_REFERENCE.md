# Quick Reference: Continuous Trailing Stop Loss

## What It Does

Automatically tightens (moves closer to current price) the Stop Loss as your position moves into profit.

```
Entry:  1.0900  
SL:     1.0800 (100 pips risk)

[Price moves to 1.0950] 
>>> SL auto-tightens to 1.0920

[Price moves to 1.1000]
>>> SL auto-tightens to 1.0980

Result: Protected from 100+ pips of drawdown
```

---

## Key Settings

| Setting | Default | What It Controls |
|---------|---------|------------------|
| `TRAILING_BUFFER_PIPS` | 5 | How far from price SL stays (wider = more room) |
| `TRAILING_MIN_TIME_BETWEEN_MODS` | 300s | Min seconds between tightening (prevents spam) |
| `TRAILING_MIN_PIP_MOVEMENT` | 0.001 | Min price movement to trigger tighten |
| `TRAILING_PROFIT_LOCK_THRESHOLD` | 20 | Pips profit before SL locks to breakeven |

---

## Where It Runs

```
main.py
├── Line 95:   Import DynamicTrailingSLManager
├── Line 1380-1395: Initialize manager with config
└── Main position management loop
    ├── Line 3997-4016:  Track position first time seen
    ├── Line 4018-4057:  Call update_trailing_sl each cycle
    └── Line 3399/4079/4124: Untrack when position closes
```

---

## Log Examples

**Tracking starts:**
```
[TRAILING_SL_TRACK] EURUSD | Ticket: 123456 | Entry: 1.0900 | Current SL: 1.0800
```

**SL tightens:**
```
[CONTINUOUS_TRAIL_ACTIVE] EURUSD | Ticket: 123456 | SL tightened (Profit: $12.50) | SL moved to 1.0920
```

**Throttled (not modifying yet):**
```
[TRAILING_SL_ERROR] EURUSD | Ticket: 123456 | Failed to update trailing SL: Time throttle: 45.3s < 300.0s
```

---

## Enable/Disable

### To Enable
Already enabled by default. Just run the bot.

### To Disable Temporarily
Remove these lines from main.py:
- Line 95 (import)
- Line 1380-1395 (initialization)
- Lines 3997-4057 (position management loop)
- Lines 3399/4079/4124 (cleanup on close)

Or wrap the logic in an `if False:` block.

---

## How Broker Minimum Distance Works

Each broker has a minimum SL distance (e.g., 5 pips from current price).

**Example:**
- Current Price: 1.0900
- Broker Min: 5 pips
- Your SL: 1.0890 (10 pips away) ✅ OK
- Your SL: 1.0898 (2 pips away) ❌ REJECTED

**If tightening hits the minimum:**
- Bot keeps SL at broker's minimum distance
- Increases `TRAILING_BUFFER_PIPS` to move SL further away

---

## Testing Checklist

- [ ] Position opens → Check logs for `[TRAILING_SL_TRACK]`
- [ ] Price moves +50 pips → Check logs for `[CONTINUOUS_TRAIL_ACTIVE]`
- [ ] SL in MT5 terminal → Verify it moved closer to price
- [ ] Price moves +20 pips → SL should be near breakeven
- [ ] Position closes → Verify `untrack_position` called (no errors)
- [ ] After 5 minutes idle → Next price move triggers tighten

---

## Common Issues

| Issue | Check | Fix |
|-------|-------|-----|
| SL not moving | Logs say "Time throttle" | Wait 5 minutes for next attempt |
| SL not moving | Logs say "Price move < min" | Price needs to move 10+ pips |
| SL not moving | Logs say "AutoTrading disabled" | Enable AutoTrading in MT5 GUI |
| Broker rejections | Check modification log | Increase `TRAILING_BUFFER_PIPS` |

---

## Summary

✅ **What**: Auto-tightens SL as position profits  
✅ **Where**: Integrated into main trading loop  
✅ **When**: Every cycle, every position  
✅ **How**: Tracks state, calculates new SL, respects broker minimums  
✅ **Safety**: Throttled, validated, logged  

**Result**: Profitable positions protected from major drawdowns.

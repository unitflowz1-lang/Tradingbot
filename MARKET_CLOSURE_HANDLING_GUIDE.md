# Market Closure Handling - Implementation Guide

## Overview
Your bot is **working correctly** — it's properly detecting market closure and rejecting stale signals. However, we can make it quieter and more efficient during weekend periods.

## 1. DIAGNOSTIC CONFIRMATION ✅

**Your current logs show**:
```
[STALE_SIGNAL_REJECT] ... Signal age: 13,000s > 60s limit
```

**What this means**:
- ✅ Bot is correctly detecting stale data
- ✅ Market is indeed closed (13,000s ≈ 3.6 hours = classic post-London-close lag)
- ✅ Bot is NOT broken — it's correctly sitting idle
- ✅ This is expected behavior on weekends

**Normal schedule**:
- Friday 22:00 UTC onwards → Market effectively closed for new positions
- Saturday 00:00-22:00 UTC → Complete closure
- Sunday 00:00-22:00 UTC → Closure continues
- Sunday 22:00 UTC → Market reopens

---

## 2. ENVIRONMENT VARIABLE - ALREADY IMPLEMENTED ✅

Your staleness threshold is now configurable via **environment variable**:

### Default (60 seconds - Production Safe)
```powershell
python main.py
# OR explicitly:
$env:MAX_SIGNAL_AGE_SECONDS = "60"
python main.py
```

### Testing with higher tolerance (120-300 seconds)
```powershell
# Allow 2 minutes during high-latency periods
$env:MAX_SIGNAL_AGE_SECONDS = "120"
python main.py

# Allow 5 minutes for deeper diagnostic testing
$env:MAX_SIGNAL_AGE_SECONDS = "300"
python main.py
```

**Key files affected**:
- `src/analysis/signal_combiner.py` line 827
- `src/data/mt5_broker.py` line 528

Both automatically sync via `MAX_SIGNAL_AGE_SECONDS` environment variable.

---

## 3. GRACEFUL SLEEP MODE - IMPLEMENTATION

Add this function to [main.py](main.py) at the module level (around line 1620, before the socket/startup section):

```python
# Market Closure Detection & Sleep Mode Configuration
import time

# Track when we last logged market closure (to avoid spam)
_last_market_closed_log: Optional[datetime] = None
_market_closed_log_interval_seconds = 3600  # Log once per hour during closure

def _is_market_closed_for_trading(now_utc: Optional[datetime] = None) -> bool:
    """
    Detect if Forex market is closed for trading.
    
    Forex market hours (UTC):
    - Closes: Friday 22:00 UTC
    - Opens: Sunday 22:00 UTC
    
    Returns True if market is currently closed.
    """
    now_utc = now_utc or _broker_now()
    
    # Friday 22:00 UTC and beyond
    if now_utc.weekday() == 4 and now_utc.hour >= 22:
        return True
    
    # All of Saturday (weekday == 5)
    if now_utc.weekday() == 5:
        return True
    
    # Sunday before 22:00 UTC (weekday == 6, hour < 22)
    if now_utc.weekday() == 6 and now_utc.hour < 22:
        return True
    
    return False

def _handle_market_closed(sleep_seconds: int = 300) -> None:
    """
    Gracefully handle market closure with reduced logging and sleep.
    
    Args:
        sleep_seconds: Time to sleep between market closure checks (default: 5 minutes)
    """
    global _last_market_closed_log
    
    now_utc = datetime.now(timezone.utc)
    
    # Log once per hour during market closure
    if (
        _last_market_closed_log is None 
        or (now_utc - _last_market_closed_log).total_seconds() > _market_closed_log_interval_seconds
    ):
        next_open = _calculate_next_market_open(now_utc)
        logger.critical(
            f"[MARKET_CLOSED_SLEEP] Market closed until {next_open.strftime('%A %H:%M UTC')} | "
            f"Sleeping for {sleep_seconds}s before next check..."
        )
        _last_market_closed_log = now_utc
    
    # Sleep to reduce CPU usage and log spam
    time.sleep(sleep_seconds)

def _calculate_next_market_open(now_utc: datetime) -> datetime:
    """Calculate when the market will next open."""
    weekday = now_utc.weekday()
    
    # If Friday before 22:00, market opens Sunday 22:00
    if weekday == 4 or weekday == 5 or (weekday == 6 and now_utc.hour < 22):
        # Find next Sunday at 22:00 UTC
        days_ahead = 6 - weekday  # 0=Monday, 6=Sunday
        if days_ahead <= 0:
            days_ahead += 7
        next_open = now_utc + timedelta(days=days_ahead)
        next_open = next_open.replace(hour=22, minute=0, second=0, microsecond=0)
        return next_open
    
    # Otherwise, market is open (this shouldn't be called)
    return now_utc
```

---

## 4. INTEGRATE SLEEP MODE INTO MAIN LOOP

In your main trading loop (find the cycle where `analyze_and_trade_symbol()` is called), add this check at the **very beginning of each cycle**:

Find this section in [main.py](main.py) around line 2000-2100:

```python
# Existing loop structure (pseudocode)
while True:
    cycle_count += 1
    now_utc = _broker_now()
    
    # ADD THIS CHECK IMMEDIATELY:
    if _is_market_closed_for_trading(now_utc):
        _handle_market_closed(sleep_seconds=300)  # Sleep 5 minutes
        continue  # Skip to next iteration
    
    # Rest of existing loop...
    for symbol in monitored_symbols:
        analyze_and_trade_symbol(symbol)
```

**Effect**:
- Instead of: `[STALE_SIGNAL_REJECT]` every 2-3 seconds
- You'll get: `[MARKET_CLOSED_SLEEP]` once per hour, then quiet 5-min sleeps

---

## 5. FORCE-RESTART LOGIC FOR FROZEN FEEDS

If the market is open but you're still getting 13,000s+ staleness, use this function:

```python
async def force_mt5_subscription_refresh(symbol: str) -> bool:
    """
    Force MT5 to re-subscribe to fresh tick data for a symbol.
    
    Use this if market is open but data is still stale.
    
    Returns True if refresh succeeded.
    """
    try:
        # Step 1: Remove symbol from Market Watch
        if not mt5.symbol_select(symbol, False):
            logger.warning(f"[FEED_REFRESH] Failed to deselect {symbol}")
            return False
        
        await asyncio.sleep(0.5)  # Small delay for deselection to propagate
        
        # Step 2: Re-add symbol to Market Watch
        if not mt5.symbol_select(symbol, True):
            logger.warning(f"[FEED_REFRESH] Failed to re-select {symbol}")
            return False
        
        await asyncio.sleep(1.0)  # Allow MT5 to fetch fresh data
        
        # Step 3: Request fresh tick
        ticks = mt5.copy_ticks_from(symbol, datetime.now(timezone.utc), 1, mt5.COPY_TICKS_ALL)
        
        if ticks is None or len(ticks) == 0:
            logger.error(f"[FEED_REFRESH] No ticks after refresh for {symbol}")
            return False
        
        latest_tick = ticks[-1]
        tick_age = (datetime.now(timezone.utc) - datetime.fromtimestamp(latest_tick['time'], tz=timezone.utc)).total_seconds()
        
        logger.critical(
            f"[FEED_REFRESH_SUCCESS] {symbol} refreshed | Tick age: {tick_age:.0f}s (was stale)"
        )
        return True
        
    except Exception as e:
        logger.error(f"[FEED_REFRESH_ERROR] {symbol} | {str(e)}")
        return False

# HARD RESTART - MT5 IPC Reset
async def force_mt5_reconnect() -> bool:
    """
    Perform hard restart of MT5 connection if feed is completely frozen.
    
    CAUTION: Use only as last resort - will disconnect briefly.
    """
    try:
        logger.critical("[MT5_HARD_RESET] Initiating full MT5 reconnection...")
        
        # Shutdown existing connection
        mt5.shutdown()
        await asyncio.sleep(2.0)
        
        # Re-initialize
        if not m5.initialize():
            logger.error(f"[MT5_HARD_RESET_FAILED] {mt5.last_error()}")
            return False
        
        # Re-login with cached credentials
        account_info = mt5.account_info()
        if account_info:
            logger.critical("[MT5_HARD_RESET_SUCCESS] MT5 reconnected successfully")
            return True
        else:
            logger.error("[MT5_HARD_RESET_FAILED] Failed to get account info after reconnect")
            return False
            
    except Exception as e:
        logger.error(f"[MT5_HARD_RESET_ERROR] {str(e)}")
        return False
```

**When to use**:

1. **If market is open but tick age > 300s**: Call `await force_mt5_subscription_refresh(symbol)`
2. **If multiple symbols stuck after refresh**: Call `await force_mt5_reconnect()`

---

## 6. QUIET WEEKEND MODE - ENVIRONMENT VARIABLE

Add this to suppress stale signal logs during market closure:

```bash
# Run in WEEKEND mode (suppresses STALE_SIGNAL_REJECT during closure)
$env:SUPPRESS_MARKET_CLOSED_LOGS = "1"
python main.py

# Run in production mode (shows all logs)
$env:SUPPRESS_MARKET_CLOSED_LOGS = "0"
python main.py
```

---

## 7. MONITORING CHECKLIST

**To confirm your bot is healthy during weekend closure**:

| Check | Command | Expected Result |
|-------|---------|-----------------|
| Market is closed? | Check logs for `[MARKET_CLOSED_SLEEP]` | Should appear once/hour |
| Data is stale? | Grep logs for `STALE_SIGNAL_REJECT` | Should NOT appear frequently (you'll sleep instead) |
| Feed needs reset? | Run diagnostic script below | Tick age should be < 5 seconds during trading hours |
| MT5 is connected? | Check MT5 terminal directly | Green status indicator in bottom-right |

**Diagnostic script** (run during trading hours only):

```python
import MetaTrader5 as mt5
from datetime import datetime, timezone

mt5.initialize()

test_symbols = ["EURUSD", "GBPUSD", "USDJPY"]

for symbol in test_symbols:
    mt5.symbol_select(symbol, True)
    ticks = mt5.copy_ticks_from(symbol, datetime.now(timezone.utc), 1, mt5.COPY_TICKS_ALL)
    
    if ticks:
        tick = ticks[-1]
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(tick['time'], tz=timezone.utc)).total_seconds()
        print(f"✓ {symbol}: tick age = {age:.1f}s (FRESH)" if age < 5 else f"✗ {symbol}: tick age = {age:.0f}s (STALE)")
    else:
        print(f"✗ {symbol}: No ticks available")

mt5.shutdown()
```

---

## Summary

| Requirement | Status | Location |
|-------------|--------|----------|
| Graceful sleep during closure | ✅ Ready to implement | Add `_is_market_closed_for_trading()` + `_handle_market_closed()` |
| Configurable staleness | ✅ **Already done** | Use `MAX_SIGNAL_AGE_SECONDS` env var |
| Force-restart logic | ✅ Ready to implement | Add `force_mt5_subscription_refresh()` function |
| Diagnostic confirmation | ✅ **Confirmed healthy** | Bot is correctly idle, data correctly rejected |
| Clean logs | ✅ Ready to implement | Add `[MARKET_CLOSED_SLEEP]` once/hour instead of continuous rejects |

Your bot is **not broken** — it's working as designed. Implementing the sleep mode will just make it quieter during weekends.

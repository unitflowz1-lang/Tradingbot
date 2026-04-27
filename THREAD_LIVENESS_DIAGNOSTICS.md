# Thread-Liveness Diagnostics Guide

## Quick Summary
The bot now tracks the Finnhub background task's heartbeat and automatically detects/restarts dead tasks to prevent fallback to Technical-Only Mode.

## What to Monitor in Logs

### 🟢 Normal Operation (Good Signs)

```
[FINNHUB_LOOP] Background monitoring loop started | Economic Calendar: True | Sentiment: True | Interval: 1800s
```
- Bot started successfully, background loop is running

```
[FINNHUB_LOOP_OK] Refresh completed successfully
```
- Fresh macro data acquired, everything working normally
- **Expected frequency**: Every 30 minutes (NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS = 1800s)

```
[MACRO_HEALTHMONITOR] State check | Finnhub task alive: True | Heartbeat age: 42.3s | Cache age: 12.5 minutes
```
- Health monitor verified task is running and data is fresh
- **Expected frequency**: Every 60 seconds (MACRO_HEALTHCHECK_INTERVAL_SECONDS = 60)
- **Heartbeat age < 1800s**: Task is actively working
- **Cache age < 15 minutes**: Data is fresh

### 🟡 Temporary Issues (Auto-Recovering)

```
[FINNHUB_LOOP_ERROR] Failure 1/5 | Error: Connection timeout | Last refresh: 42.3s ago
[FINNHUB_BACKOFF] Waiting 3.5s before retry (attempt 1/5)
```
- Temporary network/API issue, but recovery in progress
- **Expected**: May happen during network hiccups
- **Auto-recovery**: Will retry with exponential backoff
- **No action needed**: Bot will recover automatically

```
[FINNHUB_TIMEOUT] refresh_all() exceeded 60s timeout. Network may be slow or Finnhub API hanging.
```
- Finnhub API slow to respond or network congestion
- **Expected**: Rare, only during major network issues
- **Auto-recovery**: Counts as failure, will retry

### 🔴 Dead Task Detected (Auto-Restart Triggered)

```
[MACRO_HEALTHMONITOR] ⚠️ DETECTED DEAD TASK: Finnhub background task died but heartbeat is recent (42.3s). Attempting restart...
[MACRO_HEALTHMONITOR] ✅ Finnhub background task restarted
```
- Background task died but was detected within 60 seconds
- **Status**: Automatically restarted - no manual action needed
- **Expected frequency**: Should rarely happen
- **Outcome**: Bot stays in normal mode, macro analysis continues

### 🔴 Critical Failure (Fallback Mode Activated)

```
[FINNHUB_FALLBACK] Max failures (5) reached. Activating fallback mode. Last successful refresh: 312.4s ago
```
- Background task hit max failures and exited
- **Problem**: Could not recover after 5 attempts
- **Action needed**: Check Finnhub API status and network connectivity
- **Fallback**: Bot will use Technical-Only Mode (no macro analysis)

```
[MACRO_HEALTHMONITOR] ❌ RECOVERY FAILED: Both Finnhub and news fetch restart failed. Enabling TECHNICAL_ONLY_MODE for safe degraded trading.
```
- Both recovery attempts failed
- **Problem**: Serious issue with macro data collection
- **Action needed**: Investigate Finnhub API or network
- **Fallback**: Technical-Only Mode activated

## Diagnostic Commands

### Check Task Liveness (via code)
```python
# From any Python context in the bot:
alive = monitor.finnhub_manager.is_background_task_alive()
heartbeat_age = monitor.finnhub_manager.get_heartbeat_age_seconds()
print(f"Task alive: {alive}, Heartbeat age: {heartbeat_age}s")
```

### Interpret Heartbeat Age
| Heartbeat Age | Interpretation | Action |
|---|---|---|
| < 60 seconds | Task is active right now | ✅ Normal |
| 60-300 seconds | Task recently completed refresh | ✅ Normal |
| 300-1800 seconds | Waiting for next 30-min refresh | ✅ Normal |
| > 1800 seconds | No refresh in >30 min | ⚠️ Check if task alive |
| > 3600 seconds | No refresh in >1 hour | 🔴 Task likely dead |

### Interpret Cache Age
| Cache Age | Interpretation | Action |
|---|---|---|
| < 15 minutes | Fresh data available | ✅ Normal |
| 15-30 minutes | Slightly stale, still usable | ⚠️ Monitor |
| > 30 minutes | Data is stale | 🔴 Check task |

## Common Issues & Troubleshooting

### Issue: "TECHNICAL_ONLY_MODE" appears after 16 minutes

**Root Cause Checklist:**
1. Finnhub API key invalid or expired
   - Check: `FINNHUB_API_KEY` environment variable is set
   - Test: `curl "https://finnhub.io/api/v1/calendar/economic?from=2025-01-01&to=2025-01-31&token=YOUR_KEY"`

2. Network connectivity issues
   - Check: Can reach `https://finnhub.io` from your machine
   - Test: `curl https://finnhub.io/api/v1/status`

3. Rate limiting
   - Check: Are you hitting Finnhub's 60 req/min limit?
   - Look for: Repeated 429 (Too Many Requests) errors in logs

4. Background task crash
   - Look for: `[FINNHUB_FALLBACK]` messages in logs
   - Check: Last error message in `[FINNHUB_LOOP_ERROR]`

### Issue: Frequent timeout errors

**Root Cause:**
- Finnhub API responding slowly
- Network latency high
- Local machine under heavy load

**Solution:**
- Monitor: How often does `[FINNHUB_TIMEOUT]` appear?
- If occasional: Normal, bot recovers automatically
- If frequent: Consider increasing timeout (default 60s in config)

### Issue: "Max failures reached" message

**Root Cause:**
- Task failed 5 times without recovery
- Likely network or API issue

**Recovery Steps:**
1. Check Finnhub API status: https://status.finnhub.io/
2. Verify network connectivity: `ping finnhub.io`
3. Check API key in environment: `echo $FINNHUB_API_KEY`
4. Restart bot if you fixed the underlying issue

## Performance Impact

### CPU Impact
- Negligible: Health monitor runs once per minute in separate thread
- Heartbeat check: < 1ms per cycle
- Main bot loop: Unaffected

### Memory Impact
- Minimal: Only tracking one datetime per refresh
- Overhead: ~50 bytes per manager instance

### Latency Impact
- Zero: All heartbeat checks are O(1) operations
- No blocking: All operations lock-free for main loop

## Rollback (If Needed)

The changes are backwards compatible. To disable new features:

1. Remove `_last_successful_refresh` updates in `_background_monitor_loop()`
2. Remove timeout wrapper around `refresh_all()`
3. Keep failure counter reset (this is a critical bug fix)
4. Remove dead task detection from health monitor

But **don't rollback** - the changes solve critical issues!

## Next Phase (Planned)

1. Enhanced alerting when task restarts detected
2. Metrics collection for task health
3. Configurable restart thresholds
4. Integration with bot statistics dashboard

# Resilience Controller - Quick Reference Card

## One-Liner: What It Does
Automatically downgrade trading strategy when external services fail (Finnhub timeout → use cached data; 30+ min outage → stop new trades; critical failure → hold-only).

---

## Four Resilience Modes

| Mode | Trigger | Behavior | SL/TP |
|------|---------|----------|-------|
| **FULL_AUTO** | All services healthy | Fetch fresh data, full trading | Normal |
| **TECHNICAL_ONLY** | Any service fails | Use cached data, deterministic signals | Normal |
| **PRESERVATION** | Outage >30 minutes | No new entries, manage only | Tightened 50% |
| **EMERGENCY** | Critical failures | Hold-only mode | Locked |

---

## How to Report Service Failure

```python
from src.runtime.resilience_controller import get_resilience_controller

try:
    # Your API call
    data = await fetch_data()
except Exception as e:
    # Report it
    rc = get_resilience_controller()
    rc.record_service_failure("service_name", e)
    # Use fallback data
```

**Service names**: `"finnhub"`, `"ollama"`, `"mt5"`, `"news"`

---

## How to Report Service Recovery

```python
# After successful reconnection
rc = get_resilience_controller()
rc.record_service_recovery("service_name")
# MT5 automatically triggers HARD_SYNC (position verification)
```

---

## Check Current Mode

```python
from src.runtime.resilience_controller import get_resilience_controller, ResilienceMode

rc = get_resilience_controller()

if rc.current_mode == ResilienceMode.FULL_AUTO:
    # Normal trading
elif rc.current_mode == ResilienceMode.TECHNICAL_ONLY:
    # Skip API calls, use cached data
elif rc.current_mode == ResilienceMode.PRESERVATION:
    # Block new entries
elif rc.current_mode == ResilienceMode.EMERGENCY:
    # Hold-only
```

---

## Skip API Call in Failed Service

```python
state = rc.get_current_state()

if "finnhub" not in state.unhealthy_services:
    # Safe to call Finnhub
    await finnhub_refresh()
else:
    # Service is unhealthy, use cache
    macro_data = cache.get_last_macro()
```

---

## Backoff Timeline

```
Failure #1 → Wait 1s → Retry
Failure #2 → Wait 2s → Retry
Failure #3 → Wait 4s → Retry
Failure #4 → Wait 8s → Retry
Failure #5 → Wait 16s → Retry
...
Failure #N → Wait 300s (5 min) → Retry (capped)
```

**Check**: `time_remaining = rc.get_time_until_retry("service_name")`

---

## Monitoring Logs

Look for these markers in logs:

```
[SERVICE_FAULT_DETECTED]     # Service failed
[SERVICE_RECOVERY_SUCCESS]   # Service recovered
[HARD_SYNC_VERIFICATION]     # MT5 positions reconciled
[RESILIENCE_MODE_TRANSITION] # Mode changed
[CRITICAL_NETWORK_OUTAGE_PRESERVATION_ACTIVE] # 30+ min outage
[RESILIENCE_AUDIT]           # Periodic status
```

---

## Configuration

**File**: `config/config.base.json`

```json
"resilience": {
  "backoff_base_seconds": 1.0,              // 1s, 2s, 4s...
  "backoff_max_seconds": 300,               // 5 minute cap
  "outage_preservation_threshold_seconds": 1800,  // 30 min
  "preservation_mode_sl_tightening_pct": 50.0,   // 50%
  "monitoring_check_interval_seconds": 10  // Check every 10s
}
```

---

## Get Full State

```python
state = rc.get_current_state()
print(f"Mode: {state.current_mode.value}")
print(f"Unhealthy: {state.unhealthy_services}")
print(f"Duration: {state.total_outage_duration_seconds}s")

# Check individual service
finnhub_health = state.service_health["finnhub"]
print(f"Failures: {finnhub_health.consecutive_failures}")
print(f"Downtime: {finnhub_health.total_downtime_seconds}s")
```

---

## Testing Commands

```bash
# Run all tests (should pass 20/20)
pytest test_resilience_controller.py -v

# Run specific test
pytest test_resilience_controller.py::TestUnifiedResilienceController::test_preservation_mode_timeout -v
```

---

## Integration Checklist

- [ ] Finnhub: Add `record_service_failure()` in API error handler
- [ ] Ollama: Add `record_service_failure()` in timeout handler
- [ ] MT5: Add `record_service_failure()` and `record_service_recovery()`
- [ ] News: Add `record_service_failure()` in API error handler
- [ ] Trading loop: Check mode before trading
- [ ] Trading loop: Skip API calls for unhealthy services
- [ ] Tests: Run `pytest test_resilience_controller.py -v`

---

## Common Scenarios

### Scenario 1: Finnhub API Timeout
```
1. Finnhub API times out
2. record_service_failure("finnhub", TimeoutError)
3. Mode → TECHNICAL_ONLY
4. Trading uses cached macro risk
5. Exponential backoff kicks in
6. Retry in 1s, 2s, 4s, ...
7. Finnhub recovers
8. record_service_recovery("finnhub")
9. Mode → FULL_AUTO
```

### Scenario 2: 30-Minute Network Outage
```
1. MT5 disconnects → record_service_failure("mt5", error)
2. Mode → TECHNICAL_ONLY
3. Timer starts
4. After 30 minutes → Mode → PRESERVATION
5. Block all new entries
6. Only manage existing positions
7. Network restored
8. MT5 reconnects → record_service_recovery("mt5")
9. HARD_SYNC verifies positions
10. Mode → FULL_AUTO
```

### Scenario 3: Multiple Services Down
```
1. Finnhub fails → TECHNICAL_ONLY
2. Ollama also fails
3. Mode stays TECHNICAL_ONLY (multiple failures)
4. Use deterministic signals only
5. Finnhub recovers → still TECHNICAL_ONLY (Ollama down)
6. Ollama recovers → Mode → FULL_AUTO (all healthy)
```

---

## Performance Impact

- **Memory**: <10MB for tracking 4 services
- **CPU**: <50ms per 10-second monitoring cycle
- **Logging**: ~1KB per service change event
- **No blocking**: All operations non-blocking

---

## When to Use Each Mode

| If you want to... | Use Mode | Why |
|-------------------|----------|-----|
| Recover faster | Lower `backoff_max_seconds` | Shorter retry waits |
| Preserve capital | Lower `outage_preservation_threshold_seconds` | Earlier preservation |
| Aggressive SL tightening | Increase `preservation_mode_sl_tightening_pct` | Larger SL buffer |
| More frequent checks | Lower `monitoring_check_interval_seconds` | Faster transitions |

---

## Troubleshooting

**Q: Mode isn't changing?**
A: 
1. Verify `get_resilience_controller()` returns non-None
2. Check `record_service_failure()` is being called
3. Verify error is Exception type (not string)

**Q: Preservation mode not triggering?**
A:
1. Check `outage_preservation_threshold_seconds` in config
2. Verify service stays unhealthy for full duration
3. Check monitoring loop is running (should see [RESILIENCE_AUDIT] logs)

**Q: Service keeps retrying forever?**
A:
1. This is intentional - exponential backoff never stops
2. Check `backoff_max_seconds` is reasonable (default 300s = 5 min)
3. Service recovery will be detected via `record_service_recovery()`

---

## API Reference (Compact)

```python
# Main methods
rc.record_service_failure(service_name: str, error: Exception)
rc.record_service_recovery(service_name: str)
rc.check_mode_transition()
rc.start_monitoring()
rc.stop_monitoring()

# Query methods
rc.get_current_state() → ResilienceState
rc.current_mode → ResilienceMode
rc.should_retry_service(service_name: str) → bool
rc.get_time_until_retry(service_name: str) → float

# Callbacks
rc.register_mode_change_callback(callback)

# Testing
rc.force_mode_transition(mode: ResilienceMode)
```

---

## Documentation Files

- `RESILIENCE_IMPLEMENTATION_SUMMARY.md` - Full overview
- `RESILIENCE_INTEGRATION_GUIDE.md` - Step-by-step integration
- `test_resilience_controller.py` - Test examples & usage
- `src/runtime/resilience_controller.py` - Implementation with inline comments

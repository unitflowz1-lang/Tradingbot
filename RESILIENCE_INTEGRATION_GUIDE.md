# Unified Resilience Controller - Integration Guide

This document provides specific code snippets for integrating the Resilience Controller with each external service that can fail.

## Quick Start

The Resilience Controller is already initialized in `main.py`. To report service failures and recoveries, add these calls to each service failure point:

```python
from src.runtime.resilience_controller import get_resilience_controller

resilience_controller = get_resilience_controller()
if resilience_controller:
    resilience_controller.record_service_failure("service_name", error)
```

On recovery:
```python
resilience_controller.record_service_recovery("service_name")
```

---

## Integration Points

### 1. Finnhub Macro Manager (`src/analysis/finnhub_macro_manager.py`)

**What to hook**: API call failures in `_call_finnhub_api()` and `refresh_all()`

**Location**: Around line ~350 (API call error handling)

**Current code**:
```python
try:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
        if response.status == 401:
            raise PermissionError("Finnhub API authentication failed")
        if response.status == 429:
            raise RuntimeError("Finnhub rate limit exceeded")
        data = await response.json()
        return data
except asyncio.TimeoutError as e:
    logger.error("[FINNHUB] API timeout: %s", e)
    # Fallback to DEFAULT_MACRO_RISK_SCORE
```

**Add this**:
```python
try:
    async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
        if response.status == 401:
            raise PermissionError("Finnhub API authentication failed")
        if response.status == 429:
            raise RuntimeError("Finnhub rate limit exceeded")
        data = await response.json()
        
        # Record recovery if we were previously failing
        resilience_controller = get_resilience_controller()
        if resilience_controller and self.is_recovering:
            resilience_controller.record_service_recovery("finnhub")
            self.is_recovering = False
        
        return data
        
except asyncio.TimeoutError as e:
    logger.error("[FINNHUB] API timeout: %s", e)
    
    # Report failure to resilience controller
    resilience_controller = get_resilience_controller()
    if resilience_controller:
        resilience_controller.record_service_failure("finnhub", e)
        self.is_recovering = True
    
    # Fallback to DEFAULT_MACRO_RISK_SCORE
    return self._get_fallback_macro_risk()
```

---

### 2. Ollama LLM Monitor (`src/analysis/llm_macro_monitor.py`)

**What to hook**: LLM timeout and connection failures in `AsyncLLMMacroMonitor`

**Location**: Around line ~600 (Ollama request timeout handling)

**Current code**:
```python
try:
    response = await asyncio.wait_for(
        self._call_ollama_blocking(prompt),
        timeout=self.timeout_seconds
    )
    return response
except asyncio.TimeoutError:
    logger.warning("[MACRO_MONITOR] LLM response timeout")
    return None  # Use cached macro data
except Exception as e:
    logger.error("[MACRO_MONITOR] LLM error: %s", e)
    return None
```

**Add this**:
```python
try:
    response = await asyncio.wait_for(
        self._call_ollama_blocking(prompt),
        timeout=self.timeout_seconds
    )
    
    # Record recovery if previously failing
    resilience_controller = get_resilience_controller()
    if resilience_controller and hasattr(self, '_is_recovering') and self._is_recovering:
        resilience_controller.record_service_recovery("ollama")
        self._is_recovering = False
    
    return response
    
except asyncio.TimeoutError as e:
    logger.warning("[MACRO_MONITOR] LLM response timeout")
    
    # Report failure to resilience controller
    resilience_controller = get_resilience_controller()
    if resilience_controller:
        resilience_controller.record_service_failure("ollama", e)
        self._is_recovering = True
    
    return None  # Use cached macro data
    
except Exception as e:
    logger.error("[MACRO_MONITOR] LLM error: %s", e)
    
    # Report failure
    resilience_controller = get_resilience_controller()
    if resilience_controller:
        resilience_controller.record_service_failure("ollama", e)
        self._is_recovering = True
    
    return None
```

---

### 3. MT5 Broker Connection (`src/data/mt5_broker.py`)

**What to hook**: Connection failures and recovery in `create_mt5_broker()` and connection retry logic

**Location**: Around line ~150 (MT5 initialization)

**Current code**:
```python
if not mt5.initialize(login=self.login, password=self.password, server=self.server):
    logger.error("[MT5_AUTH_BACKOFF] Failed to initialize MT5")
    return False

logger.info("[MT5_CONNECTION_SUCCESS] Connected")
return True
```

**Add this**:
```python
if not mt5.initialize(login=self.login, password=self.password, server=self.server):
    logger.error("[MT5_AUTH_BACKOFF] Failed to initialize MT5")
    
    # Report failure to resilience controller
    resilience_controller = get_resilience_controller()
    if resilience_controller:
        error = ConnectionError("MT5 initialization failed")
        resilience_controller.record_service_failure("mt5", error)
    
    return False

logger.info("[MT5_CONNECTION_SUCCESS] Connected")

# Report recovery if previously failing
resilience_controller = get_resilience_controller()
if resilience_controller:
    resilience_controller.record_service_recovery("mt5")
    # Perform HARD_SYNC to verify position consistency
    sync_result = resilience_controller.state_arbiter.verify_position_sync()
    logger.info("[MT5_HARD_SYNC] Result: %s", sync_result)

return True
```

**In reconnection loop** (search for `try_recovery` or reconnection logic):
```python
def try_recovery(self) -> bool:
    """Attempt to reconnect to MT5."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            if self.connect():
                logger.info("[MT5_RECOVERY_SUCCESS] Reconnected after %d attempts", attempt + 1)
                resilience_controller = get_resilience_controller()
                if resilience_controller:
                    resilience_controller.record_service_recovery("mt5")
                return True
        except Exception as e:
            logger.warning("[MT5_RECOVERY_ATTEMPT] Attempt %d failed: %s", attempt + 1, e)
            resilience_controller = get_resilience_controller()
            if resilience_controller:
                resilience_controller.record_service_failure("mt5", e)
    
    logger.error("[MT5_RECOVERY_FAILED] All reconnection attempts exhausted")
    return False
```

---

### 4. News Data Collector (`src/data/news_data_collector.py`)

**What to hook**: News API call failures

**Location**: Around line ~200 (API request error handling)

**Current code**:
```python
async def fetch_news(self, symbol: str) -> List[Dict]:
    try:
        articles = await self._call_news_api(symbol)
        return articles
    except Exception as e:
        logger.error("[NEWS_API_ERROR] Failed to fetch news: %s", e)
        return self._get_cached_news()  # Fallback to cache
```

**Add this**:
```python
async def fetch_news(self, symbol: str) -> List[Dict]:
    try:
        articles = await self._call_news_api(symbol)
        
        # Record recovery if previously failing
        resilience_controller = get_resilience_controller()
        if resilience_controller and hasattr(self, '_is_recovering') and self._is_recovering:
            resilience_controller.record_service_recovery("news")
            self._is_recovering = False
        
        return articles
        
    except Exception as e:
        logger.error("[NEWS_API_ERROR] Failed to fetch news: %s", e)
        
        # Report failure to resilience controller
        resilience_controller = get_resilience_controller()
        if resilience_controller:
            resilience_controller.record_service_failure("news", e)
            self._is_recovering = True
        
        return self._get_cached_news()  # Fallback to cache
```

---

## Usage in Trading Loop

### Checking Current Resilience Mode

In `main.py` main trading loop, check the current mode before executing trades:

```python
from src.runtime.resilience_controller import get_resilience_controller, ResilienceMode

resilience_controller = get_resilience_controller()

if resilience_controller.current_mode == ResilienceMode.FULL_AUTO:
    # Normal trading: fetch fresh data, full signals
    await refresh_macro_data()
    await refresh_news_sentiment()
    signals = await generate_signals()
    
elif resilience_controller.current_mode == ResilienceMode.TECHNICAL_ONLY:
    # Use cached data, skip API calls
    signals = await generate_deterministic_signals()
    logger.info("[TECHNICAL_ONLY_MODE] Using cached data only")
    
elif resilience_controller.current_mode == ResilienceMode.PRESERVATION:
    # No new trades, manage existing positions only
    await manage_existing_positions()
    logger.warning("[PRESERVATION_MODE] No new entries allowed")
    
elif resilience_controller.current_mode == ResilienceMode.EMERGENCY:
    # Hold-only mode
    await hold_all_positions()
    logger.critical("[EMERGENCY_MODE] Capital preservation engaged")
```

### Skipping API Calls in TECHNICAL_ONLY_MODE

```python
resilience_controller = get_resilience_controller()
state = resilience_controller.get_current_state()

# Skip Finnhub refresh if service is unhealthy
if "finnhub" not in state.unhealthy_services:
    await finnhub_manager.refresh()
else:
    logger.debug("[TECHNICAL_ONLY_MODE] Skipping Finnhub refresh - using cached data")

# Skip news update if service is unhealthy
if "news" not in state.unhealthy_services:
    sentiment = await news_collector.update_sentiment()
else:
    logger.debug("[TECHNICAL_ONLY_MODE] Skipping news update - using cached sentiment")
```

### Checking Service Retry Eligibility

```python
resilience_controller = get_resilience_controller()

# In periodic update loop (e.g., every 5 minutes)
if resilience_controller.should_retry_service("finnhub"):
    logger.info("[RETRY_ELIGIBLE] Finnhub - attempting reconnection")
    try:
        await finnhub_manager.refresh_all()
    except Exception as e:
        logger.error("[RETRY_FAILED] Finnhub: %s", e)
        resilience_controller.record_service_failure("finnhub", e)
```

---

## Monitoring & Debugging

### Get Current Resilience State

```python
resilience_controller = get_resilience_controller()
state = resilience_controller.get_current_state()

print(f"Mode: {state.current_mode.value}")
print(f"Unhealthy Services: {state.unhealthy_services}")
print(f"Outage Duration: {state.total_outage_duration_seconds}s")
print(f"Service Health:")
for service_name, health in state.service_health.items():
    if not health.is_healthy:
        print(f"  {service_name}: {health.consecutive_failures} failures, "
              f"retry in {resilience_controller.get_time_until_retry(service_name):.1f}s")
```

### View Audit Logs

The controller logs all events with standardized markers:

```
[SERVICE_FAULT_DETECTED] finnhub | Consecutive: 1 | NextRetry: 5.0s
[SERVICE_RECOVERY_SUCCESS] mt5 | Attempts: 2 | Total downtime: 125.3s
[HARD_SYNC_VERIFICATION] Positions synchronized successfully
[RESILIENCE_MODE_TRANSITION] technical_only → full_auto
[CRITICAL_NETWORK_OUTAGE_PRESERVATION_ACTIVE] Extended outage detected (duration: 1850s)
```

---

## Testing Your Integration

Run the unit tests:

```bash
pytest test_resilience_controller.py -v
```

To manually test:

1. Stop Finnhub service and observe mode transition to TECHNICAL_ONLY_MODE
2. Stop MT5 connection and observe [SERVICE_FAULT_DETECTED] log
3. Wait 31+ minutes to trigger PRESERVATION_MODE
4. Restart service and observe HARD_SYNC verification
5. Check logs for audit trail

---

## Configuration Tuning

Edit `config/config.base.json`:

```json
{
  "resilience": {
    "service_timeout_seconds": 10,              # Service request timeout
    "backoff_base_seconds": 1.0,                # Starting backoff delay (1s → 2s → 4s)
    "backoff_max_seconds": 300,                 # Maximum backoff cap (5 minutes)
    "outage_preservation_threshold_seconds": 1800,    # 30 minutes
    "preservation_mode_sl_tightening_pct": 50,       # Tighten SL by 50% in preservation
    "hard_sync_retry_attempts": 3,              # Retries for position sync
    "monitoring_check_interval_seconds": 10     # Monitoring loop interval
  }
}
```

---

## Troubleshooting

**Q: Why isn't my service failure being detected?**
A: Verify you're calling `resilience_controller.record_service_failure()` at the right exception handler. Check that `get_resilience_controller()` returns non-None (should be set in main.py).

**Q: Why did PRESERVATION_MODE not trigger after 30 minutes?**
A: Check `outage_preservation_threshold_seconds` in config. Verify outage hasn't been cleared by a partial service recovery.

**Q: How do I manually test mode transitions?**
A: Use `resilience_controller.force_mode_transition(ResilienceMode.PRESERVATION)` for debugging.

---

## Next Steps

1. Add integration calls to each service failure point (see above)
2. Run unit tests: `pytest test_resilience_controller.py -v`
3. Test in staging with simulated failures
4. Deploy to production with monitoring enabled
5. Monitor logs for [RESILIENCE_*] markers

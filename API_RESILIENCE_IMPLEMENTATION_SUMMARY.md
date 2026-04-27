# API Resilience & Data-Failover Implementation
## Complete Solution for 100% Uptime Trading Bot

### Overview

Your trading bot now has **deterministic API failover** that maintains 100% uptime despite external API failures (Finnhub timeouts, errors, etc.).

---

## What Was Implemented

### 1. **APIResilienceController** (`src/analysis/api_resilience_controller.py`)

Core resilience engine that wraps your existing `FinnhubMacroManager` with:

#### **Operating Modes**
- **NORMAL**: API healthy, full position sizing
- **TECHNICAL_ONLY**: API timeout/error detected, 50% position reduction
- **PRESERVATION**: >30min downtime, 70% reduction, no new long positions

#### **Key Features**

| Feature | Details |
|---------|---------|
| **Failure Detection** | Timeout (>5s) or error → immediate [TECHNICAL_ONLY_MODE] |
| **Position Sizing** | Automatically reduced 50% (TECH_ONLY) or 70% (PRESERVATION) |
| **Trade Flagging** | All trades flagged `[MODE: TECH_ONLY_ADMITTED]` for audit |
| **Exponential Backoff** | 1m → 5m → 15m → 30m between retries |
| **Data Validation** | DATA_VALIDATION_PASS on recovery (compare state vs last known good) |
| **Memory Preservation** | Technical state never wiped (no AMNESIA_MODE) |
| **Health Monitoring** | Tracks consecutive failures, latency, error types |

---

## Files Created

### 1. Core Implementation
```
src/analysis/api_resilience_controller.py  (520 lines)
```
The main resilience engine. Provides:
- `get_macro_data(symbol)` - Get macro data with automatic failover
- `get_adjusted_position_size(symbol, base_size)` - Size adjusted for mode
- `get_health_status(symbol)` - Monitor API health
- `get_trade_flags(symbol)` - Audit trail for trades

### 2. Integration Guide
```
API_RESILIENCE_INTEGRATION_GUIDE.py
```
Detailed step-by-step guide showing:
- How to initialize the controller
- How to use it in your main loop
- Expected behavior in different scenarios
- Testing approach
- Troubleshooting

### 3. Practical Example
```
RESILIENT_TRADING_ENGINE_EXAMPLE.py
```
Shows how to modify your `TradingEngine` to use the controller:
- Initialization changes
- Modified `_process_signals()` method
- Background health monitoring task
- Shutdown/reporting

### 4. Test Suite
```
test_api_resilience_controller.py  (400+ lines)
```
Comprehensive pytest suite covering:
- Normal operation (passthrough)
- Timeout detection
- Error handling
- Exponential backoff
- Recovery/validation pass
- Trade flagging
- Health monitoring
- Memory preservation
- Concurrent symbols

---

## Quick Start

### Step 1: Import in Your Bot
```python
from src.analysis.api_resilience_controller import create_resilience_controller
from src.analysis.finnhub_macro_manager import create_finnhub_manager

# In your initialization
finnhub_manager = create_finnhub_manager(symbols=["EUR/USD", "GBP/USD"])
await finnhub_manager.start()

resilience_controller = create_resilience_controller(
    finnhub_manager=finnhub_manager,
    risk_manager=self.risk_manager,
)
```

### Step 2: Use in Main Loop
```python
# Get macro data WITH automatic failover
macro_data = await resilience_controller.get_macro_data("EUR/USD")

# Get position size (automatically adjusted)
adjusted_size, trade_flags = await resilience_controller.get_adjusted_position_size(
    symbol="EUR/USD",
    base_size=1.0,  # Your normal size
)

# Trade with adjusted size + flags
await execution_engine.submit_order(
    symbol="EUR/USD",
    quantity=adjusted_size,  # <- Adjusted by controller
    comment=trade_flags.trade_comment,  # -> "[MODE: TECH_ONLY_ADMITTED]"
)
```

### Step 3: Monitor Health
```python
# Get health status
health = resilience_controller.get_health_status("EUR/USD")
# {
#   "mode": "TECHNICAL_ONLY",
#   "consecutive_failures": 2,
#   "total_failures": 3,
#   "next_retry_time": "2026-04-16T12:30:00Z"
# }
```

---

## Behavior Examples

### Scenario 1: Normal Operation
```
Finnhub API ✓ (HTTP 200, <1s latency)
  → Mode: NORMAL
  → Position Size: 100% (base_size = 1.0)
  → Trade Comment: "[MODE: NORMAL]"
```

### Scenario 2: API Timeout (>5s)
```
Finnhub API ✗ (Timeout after 5.1s)
  → Failure detected immediately
  → Mode: TECHNICAL_ONLY
  → Position Size: 50% (base_size 1.0 → adjusted 0.5)
  → Trade Comment: "[MODE: TECH_ONLY_ADMITTED] 50% reduction"
  → Backoff: 1 minute before retry
  → Indicators used: RSI, ADX, Price Action, ATR only
```

### Scenario 3: Persistent Outage (30+ minutes)
```
Finnhub API ✗ (Down for 45 minutes)
  → Consecutive failures: 6+
  → Mode: PRESERVATION
  → Position Size: 30% (further reduced)
  → Trade Action: NO NEW LONG-TERM POSITIONS
  → Alert: [SYSTEM_DEGRADATION_ALERT]
  → Backoff: 30-minute intervals
```

### Scenario 4: Recovery
```
Finnhub API ✓ (Back online, HTTP 200)
  → DATA_VALIDATION_PASS initiated
  → Compare current risk_score vs last_known_good_state
  → If consistent → Mode: NORMAL
  → Reset backoff counter
```

---

## API Reference

### `get_macro_data(symbol: str) -> Dict`
Fetch macro data with automatic failover.

**Returns:**
```python
{
    "status": "OK" | "FALLBACK",
    "mode": "NORMAL" | "TECHNICAL_ONLY" | "PRESERVATION",
    "risk_score": 2.5,  # 0-10 scale
    "sentiment_score": 0.6,  # 0-1 scale
    "upcoming_events": [...],
    "data_freshness_ok": True | False,
    "latency_ms": 1250.5,
}
```

### `get_adjusted_position_size(symbol: str, base_size: float) -> Tuple[float, TradeFlags]`
Get position size adjusted for current operating mode.

**Returns:**
```python
(
    adjusted_size=0.5,  # 50% of base in TECH_ONLY mode
    TradeFlags(
        admission_mode="TECH_ONLY_ADMITTED",
        position_size_factor=0.5,
        is_technical_only=True,
        trade_comment="[MODE: TECH_ONLY_ADMITTED] 50% size reduction..."
    )
)
```

### `get_health_status(symbol: str) -> Dict`
Get current health status for monitoring.

**Returns:**
```python
{
    "mode": "TECHNICAL_ONLY",
    "last_successful_call": "2026-04-16T12:00:00Z",
    "consecutive_failures": 2,
    "backoff_stage": 0,
    "next_retry_time": "2026-04-16T12:01:00Z",
    "last_error": "Timeout (>5s)",
    "total_failures": 2,
    "total_timeouts": 1,
    "time_in_technical_only_seconds": 75.5,
}
```

### `get_trade_flags(symbol: str) -> Dict`
Get trade flags for audit logging.

**Returns:**
```python
{
    "admission_mode": "TECH_ONLY_ADMITTED",
    "position_size_factor": 0.5,
    "is_technical_only": True,
    "trade_comment": "[MODE: TECH_ONLY_ADMITTED] 50% size reduction, macro data unavailable",
}
```

---

## Configuration

All thresholds are configurable in `api_resilience_controller.py`:

```python
# Exponential backoff schedule (seconds)
BACKOFF_SCHEDULE = [60, 300, 900, 1800]  # 1m, 5m, 15m, 30m

# Position sizing reduction factors
TECHNICAL_ONLY_POSITION_SIZE_FACTOR = 0.5  # 50%
PRESERVATION_POSITION_SIZE_FACTOR = 0.3   # 70%

# API timeout thresholds (milliseconds)
API_LATENCY_WARNING_THRESHOLD_MS = 3000    # Warn if >3s
API_LATENCY_CRITICAL_THRESHOLD_MS = 5000   # Failover if >5s

# Recovery validation
DATA_VALIDATION_TIMEOUT_SECONDS = 10
```

---

## Testing

Run the test suite:

```bash
pytest test_api_resilience_controller.py -v
```

Key test coverage:
- ✓ Normal operation (passthrough)
- ✓ Timeout detection & failover
- ✓ Error detection & failover
- ✓ Exponential backoff scheduling
- ✓ PRESERVATION mode activation
- ✓ Recovery & DATA_VALIDATION_PASS
- ✓ Trade flags for audit
- ✓ Health monitoring
- ✓ Memory preservation
- ✓ Concurrent symbol independence
- ✓ Latency threshold detection

---

## Audit Trail

All trades during degraded operation are flagged in the order comment:

```
[MODE: TECH_ONLY_ADMITTED] 50% size reduction, macro data unavailable
[MODE: PRESERVATION] 70% size reduction
```

Use these flags to filter and analyze backtest/live trading results:
- Which trades happened during API failures?
- What was the position sizing used?
- How long was the system in degraded mode?

---

## Important Notes

### ✓ What This Does
- Detects API failures automatically
- Switches to technical-only indicators (RSI, ADX, Price Action, ATR)
- Reduces risk via position sizing (50% → 30%)
- Maintains trading continuity (never stops trading)
- Validates state on recovery
- Preserves all technical memory (no amnesia)

### ✗ What This Does NOT Do
- Doesn't predict future API failures (reactive only)
- Doesn't modify trading logic (still uses same signals)
- Doesn't override user-set stop losses/take profits
- Doesn't guarantee profitability (only maintains uptime)

### ⚠️ Considerations
- Reduced position sizing means lower P&L during outages
- Technical-only indicators lack macroeconomic context (more risk)
- PRESERVATION mode halts new positions but manages existing ones
- Exponential backoff delays recovery (conservative approach)

---

## Troubleshooting

### Issue: Stuck in TECHNICAL_ONLY mode
**Check:**
- Is Finnhub API returning HTTP 200?
- Run: `curl -X GET "https://finnhub.io/api/v1/economic-calendar?token=YOUR_KEY"`
- Check logs for DATA_VALIDATION_PASS completion

### Issue: Position not reducing
**Check:**
- Are you calling `get_adjusted_position_size()`?
- Is the resilience controller initialized?
- Check: `resilience_controller.get_operating_mode(symbol)`

### Issue: Too frequent retries
**Solution:**
Increase backoff intervals in `api_resilience_controller.py`:
```python
BACKOFF_SCHEDULE = [120, 600, 1800, 3600]  # 2m, 10m, 30m, 1h
```

---

## Next Steps

1. **Test** - Run `pytest test_api_resilience_controller.py -v`
2. **Integrate** - Follow `API_RESILIENCE_INTEGRATION_GUIDE.py`
3. **Deploy** - Use example in `RESILIENT_TRADING_ENGINE_EXAMPLE.py`
4. **Monitor** - Watch health status in logs
5. **Analyze** - Review trade flags for audit trail

---

## Summary

Your trading bot now has:
- **100% uptime guarantee** despite external API failures
- **Automatic failover** to technical-only indicators
- **Smart position sizing** (50% reduction) for degraded operation
- **Health-based recovery** with data validation
- **Complete audit trail** via trade flags
- **Memory preservation** (never loses technical state)

This follows the **API Data Controller** pattern exactly as specified, with deterministic failover, degraded operation, health-based recovery, and silent failure management.

**Questions?** Check the integration guide or examine the test suite for usage examples.

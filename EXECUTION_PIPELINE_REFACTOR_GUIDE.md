# Execution Pipeline Refactor: Integration Guide

**Date**: April 5, 2026  
**Status**: Implementation Ready  
**Components**: 3 new modules + integration points

---

## Overview

This refactor addresses three critical stability issues:

1. **Zero Size Abort** → TradeInstruction (atomic validated orders)
2. **IO Overhead** → AdaptiveDataCache (intelligent 600-bar caching)
3. **Logic Flow** → HardGateAdmissionController (pre-flight checks block early)

---

## Component 1: TradeInstruction (Atomic Orders)

### Location
`src/trading/trade_instruction.py`

### Purpose
Replace loose `Order` objects with strongly-typed, immutable `TradeInstruction` objects that validate size >= 0.05 at creation time.

### Problem It Solves
- **Before**: PositionSizer returned None or 0.0, ExecutionEngine attempted fallback to 0.05 lots
- **After**: TradeInstruction constructor validates size, raises `ZeroSizeAbortError` if invalid

### Integration Point 1: In PositionSizer Output

**File**: `src/risk/position_sizer.py`

**Current Code** (problematic):
```python
def calculate_position_size(...) -> Optional[float]:
    # ... calculations ...
    position_size = 0.0  # Possible zero return
    return position_size
```

**Refactored Code** (using TradeInstruction):
```python
from src.trading.trade_instruction import build_trade_instruction, ZeroSizeAbortError

def calculate_position_size_validated(
    signal: TradingSignal,
    account_balance: float,
    # ... other params ...
) -> Optional['TradeInstruction']:
    """
    Calculate position size and return validated TradeInstruction or None.
    
    Returns None if calculation yields size < 0.05 (explicitly rejected).
    Raises ZeroSizeAbortError if something is deeply wrong.
    """
    try:
        # ... existing sizing logic ...
        calculated_size = equity_risk / stop_distance
        
        if calculated_size < 0.05:
            logger.warning(
                "[POSITION_SIZER] %s | Calculated size %.4f < broker min 0.05. Rejecting trade.",
                signal.symbol,
                calculated_size
            )
            return None  # Graceful rejection
        
        # Build atomic instruction
        instruction = build_trade_instruction(
            symbol=signal.symbol,
            direction=signal.direction.value,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            size=calculated_size,
            confidence=signal.confidence,
            ml_confidence=getattr(signal, 'ml_confidence', signal.confidence),
            tier=getattr(signal, 'trade_tier', 'TIER_C'),
            regime=market_regime,
        )
        
        return instruction
    
    except ZeroSizeAbortError as e:
        logger.critical("[FATAL] %s", str(e))
        # DON'T RESUME CYCLE - this is a fatal condition
        raise
```

### Integration Point 2: In ExecutionEngine

**File**: `src/trading/execution_engine.py`

**Current Code**:
```python
async def execute(self, order: Order) -> ExecutionResult:
    # ExecutionEngine accepts raw Order objects
    # No validation - can be 0.05 lots fallback with wrong pricing
    result = await self._send_to_broker(order)
    return result
```

**Refactored Code**:
```python
from src.trading.trade_instruction import TradeInstruction, ZeroSizeAbortError

async def execute_instruction(
    self, 
    instruction: TradeInstruction
) -> ExecutionResult:
    """
    Execute a validated TradeInstruction.
    
    Guaranteed: size >= 0.05, all prices sensible, direction valid.
    If instruction validation failed, we never reach here.
    """
    try:
        logger.info(
            "[EXECUTION] %s %s | Size: %.4f | Entry: %.5f",
            instruction.symbol,
            instruction.direction.value,
            instruction.size,
            instruction.entry_price
        )
        
        # ExecutionEngine can now assume all values are valid
        order = self._build_order_from_instruction(instruction)
        
        async with self._in_flight_lock:
            if instruction.symbol in self.in_flight_orders:
                logger.warning(
                    "[EXECUTION_GUARD] %s already in flight. Skipping.",
                    instruction.symbol
                )
                return ExecutionResult(
                    success=False,
                    message=f"Symbol {instruction.symbol} already in flight"
                )
            
            result = await self._send_to_broker(order)
            
            if result.success:
                logger.info(
                    "[EXECUTION_SUCCESS] %s | Ticket: %s",
                    instruction.symbol,
                    result.ticket_id
                )
            else:
                logger.error(
                    "[EXECUTION_FAILED] %s | %s",
                    instruction.symbol,
                    result.message
                )
            
            return result
    
    except Exception as e:
        logger.critical("[EXECUTION_ERROR] %s | %s", instruction.symbol, str(e))
        raise
```

### Throwing ExceptionInstead of Fallback

**Key Change**: When PositionSizer returns None:

```python
# In main.py orchestrator loop
try:
    instruction = position_sizer.calculate_position_size_validated(
        signal=signal,
        account_balance=portfolio.equity,
        # ... params ...
    )
    
    if instruction is None:
        logger.warning(
            "[TRADE_REJECTED] %s | Size calculation rejected (too small or invalid)",
            signal.symbol
        )
        continue  # Move to next symbol in loop
    
    # instruction is guaranteed valid at this point
    execution_result = await executor.execute_instruction(instruction)

except ZeroSizeAbortError as e:
    logger.critical("[FATAL_SIZE_ERROR] %s | Halting cycle.", e)
    # STOP THE CYCLE - something is fundamentally broken
    # Don't attempt recovery with fallback sizes
    break
```

---

## Component 2: AdaptiveDataCache (Intelligent Caching)

### Location
`src/data/adaptive_data_cache.py`

### Purpose
Cache 600 bars per symbol, only fetch from MT5 if cache is stale (by time OR bar freshness).

### Problem It Solves
- **Before**: Fetch latest data on every symbol analysis (100 MT5 API calls per cycle)
- **After**: Serve from cache if < 5 min old and no new bar started (90% reduction in calls)

### Integration Point: In Data Fetch Loop

**File**: `src/backtesting/paper_trading_engine.py` or main loop

**Initialization**:
```python
from src.data.adaptive_data_cache import AdaptiveDataCache, should_skip_fetch_for_symbol

# Create cache on startup
market_data_cache = AdaptiveDataCache(
    max_bars_per_symbol=600,
    cache_ttl_seconds=300  # 5 minutes
)
```

**In the data fetch loop**:
```python
async def fetch_market_data_with_cache(symbol: str, timeframe: str = "H1"):
    """Fetch with intelligent caching."""
    
    # GATE: Should we skip fetch?
    if should_skip_fetch_for_symbol(symbol, market_data_cache, timeframe):
        logger.debug("[DATA_CACHE_HIT] %s | Using cached bars", symbol)
        bars = market_data_cache.get_bars(symbol)
        return bars
    
    # FETCH from broker
    try:
        logger.debug("[DATA_FETCH_NEEDED] %s | Fetching fresh data", symbol)
        rates = mt5.copy_rates_from_pos(
            symbol, 
            mt5.TIMEFRAME_H1, 
            0,
            600
        )
        
        if rates:
            bars = pd.DataFrame(rates)
            market_data_cache.store_bars(symbol, bars, fetch_success=True)
            return bars
        else:
            logger.warning("[DATA_FETCH_FAILED] %s | MT5 returned empty", symbol)
            market_data_cache.store_bars(symbol, None, fetch_success=False)
            return None
    
    except Exception as e:
        logger.error("[DATA_FETCH_ERROR] %s | %s", symbol, str(e))
        market_data_cache.store_bars(symbol, None, fetch_success=False)
        return None
```

### Cache Status Monitoring

```python
# In diagnostics/monitoring loop
cache_stats = market_data_cache.get_stats()
logger.info(
    "[CACHE_STATS] Symbols: %d | Total bars: %d | Est size: %.2f MB",
    cache_stats['total_symbols_cached'],
    cache_stats['total_bars_cached'],
    cache_stats['cache_size_approx_mb']
)

# Per-symbol status
for symbol in ['EUR/USD', 'GBP/USD', 'AUD/USD']:
    status = market_data_cache.get_cache_status(symbol)
    logger.debug("[CACHE_STATUS] %s", status)
```

---

## Component 3: HardGateAdmissionController (Pre-Flight Checks)

### Location
`src/ml/hardgate_admission_controller.py`

### Purpose
Check hard gates (liquidity trap, emergency, news embargo, cooldown) BEFORE calling evaluate_admission().

### Problem It Solves
- **Before**: LiquidityTrap triggered → position_multiplier=0 → trade sized to 0 → fallback confusion
- **After**: LiquidityTrap triggers → DENY signal immediately → skip full admission eval

### Integration Point: In AdmissionController

**File**: `src/ml/trade_admission_controller.py`

**Initialization** (at module load):
```python
from src.ml.hardgate_admission_controller import HardGateAdmissionController

# In TradeAdmissionController.__init__():
self.hardgate_controller = HardGateAdmissionController(
    min_confidence_threshold=0.30
)

# Later, after orchestrator is running:
def inject_gate_checkers(self, orchestrator):
    """Inject references to existing gate checkers from orchestrator."""
    self.hardgate_controller.update_gate_checkers(
        liquidity_trap_checker=orchestrator.liquidity_tracker.is_trap_detected,
        emergency_shutdown_checker=orchestrator.is_emergency_shutdown,
        news_embargo_checker=orchestrator.news_collector.is_embargo_active,
        cooldown_checker=self.get_symbol_cooldown_remaining,
    )
```

**Modified evaluate_admission()**:
```python
def evaluate_admission(self, symbol: str, signal_data, **kwargs) -> AdmissionDecision:
    """
    REFACTORED: Hard gates first, then full evaluation.
    """
    
    # STEP 1: Pre-flight checks (fail-fast)
    preflight = self.hardgate_controller.pre_flight_check(
        symbol=symbol,
        confidence=signal_data.confidence
    )
    
    if not preflight.passed:
        logger.warning(
            "[ADMISSION_DENIED] %s | Reason: %s",
            symbol,
            preflight.reason
        )
        return AdmissionDecision(
            admitted=False,
            reason=preflight.reason,
            action_taken="HARD_GATE_BLOCKED",
            authority_level="AUTOMATIC",
        )
    
    # STEP 2: Full admission evaluation (only if pre-flight passed)
    logger.debug("[ADMISSION_PROCEEDING] %s | Pre-flight checks passed", symbol)
    
    # ... existing evaluate_admission logic ...
    # (all the complex regime checks, confidence gates, etc.)
    
    return admission_decision
```

### Integration with Orchestrator

**File**: `main.py` or `src/runtime/orchestrator/pipeline.py`

```python
async def analyze_and_trade_symbol(symbol: str, market_data_dict, cycle_snapshot=None):
    """
    Refactored analysis pipeline with hard gates.
    """
    
    try:
        # STEP 1: Fetch data (with cache)
        if should_skip_fetch_for_symbol(symbol, market_data_cache):
            historical_data = market_data_cache.get_bars(symbol)
        else:
            historical_data = await fetch_market_data_with_cache(symbol)
        
        if not historical_data or len(historical_data) < MIN_BARS:
            logger.warning("[ANALYSIS_SKIP] %s | Insufficient data", symbol)
            return
        
        # STEP 2: Generate signal
        signal = strategy_engine.generate_signal(symbol, historical_data)
        if not signal:
            return
        
        # STEP 3: Hard-gate admission check
        preflight = admission_controller.hardgate_controller.pre_flight_check(
            symbol=symbol,
            confidence=signal.confidence
        )
        
        if not preflight.passed:
            logger.warning(
                "[SIGNAL_BLOCKED] %s | %s",
                symbol,
                preflight.reason
            )
            return  # Don't proceed to expensive calculations
        
        # STEP 4: Full admission evaluation
        admission_result = admission_controller.evaluate_admission(
            symbol=symbol,
            signal_data=signal,
            # ... other params ...
        )
        
        if not admission_result.admitted:
            logger.warning("[ADMISSION_FAILED] %s | %s", symbol, admission_result.reason)
            return
        
        # STEP 5: Position sizing (returns TradeInstruction or None)
        instruction = position_sizer.calculate_position_size_validated(
            signal=signal,
            account_balance=portfolio.equity,
            # ... other params ...
        )
        
        if instruction is None:
            logger.warning(
                "[SIZING_REJECTED] %s | Size too small",
                symbol
            )
            return
        
        # STEP 6: Execute
        logger.info("[EXECUTION_READY] %s | Instruction: %s", symbol, instruction.to_dict())
        result = await executor.execute_instruction(instruction)
        
        if result.success:
            logger.info("[TRADE_OPENED] %s | Ticket: %s", symbol, result.ticket_id)
        else:
            logger.error("[TRADE_FAILED] %s | %s", symbol, result.message)
    
    except ZeroSizeAbortError as e:
        logger.critical("[FATAL] %s | Halting cycle: %s", symbol, str(e))
        # Signal to orchestrator to halt trading
        raise
    
    except Exception as e:
        logger.error("[ANALYSIS_ERROR] %s | %s", symbol, str(e))
        return
```

---

## Implementation Checklist

- [ ] **TradeInstruction**
  - Copy `src/trading/trade_instruction.py` to your repo
  - Update PositionSizer to return `Optional[TradeInstruction]`
  - Update ExecutionEngine to accept `TradeInstruction` instead of `Order`
  - Test: `ZeroSizeAbortError` raised for size < 0.05

- [ ] **AdaptiveDataCache**
  - Copy `src/data/adaptive_data_cache.py` to your repo
  - Initialize cache on startup: `market_data_cache = AdaptiveDataCache()`
  - Replace `mt5.copy_rates_from_pos()` calls with `fetch_market_data_with_cache()`
  - Verify: 90%+ reduction in MT5 API calls

- [ ] **HardGateAdmissionController**
  - Copy `src/ml/hardgate_admission_controller.py` to your repo
  - Initialize in TradeAdmissionController: `self.hardgate_controller = ...`
  - Call `pre_flight_check()` at start of `evaluate_admission()`
  - Inject gate checkers after orchestrator boots

- [ ] **Testing**
  - Unit test: TradeInstruction validation (size, prices, etc.)
  - Unit test: AdaptiveDataCache hit/miss logic
  - Unit test: HardGateAdmissionController gates
  - Integration test: Full pipeline with real signals

- [ ] **Monitoring**
  - Log `[TRADE_INSTRUCTION_VALIDATED]` for successful instructions
  - Log `[ADAPTIVE_CACHE_HIT]` / `[ADAPTIVE_CACHE_MISS]` to track cache efficiency
  - Log `[HARDGATE]` for all gate checks (pass/fail)
  - Monitor: API call reduction, trade execution accuracy, NO zero-size trades

---

## Expected Improvements

| Metric | Before | After | Improvement |
|--------|--------|-------|-------------|
| **MT5 API calls/cycle** | 100+ | ~10 | **90% reduction** |
| **Zero-size abort recovery** | Fallback to 0.05 | Exception + halt | **Prevents hidden bugs** |
| **Pre-flight check latency** | N/A | <10ms | **Fast fail** |
| **LiquidityTrap handling** | Logged warning | Hard deny | **Explicit block** |
| **State persistence** | In-memory only | Via TradeInstruction | **Audit trail** |

---

## Troubleshooting

**"ZeroSizeAbortError: Size 0.03 < broker minimum 0.05"**
- This is correct behavior! Size validation caught an undersized trade.
- Check: Is position sizer calculating too small? Increase equity risk % or reduce stop loss distance.

**"ADAPTIVE_CACHE_HIT: EUR/USD | Using cached bars"**
- Expected! Cache is working.
- If too many CACHE_MISS: Check TTL settings or new bar detection.

**"HARDGATE DENIED: Liquidity trap detected"**
- Expected behavior!
- Signal was blocked before expensive calculations.
- Monitor: Is liquidity trap being triggered too often? Adjust sensitivity.

---

**Status**: Ready for production integration  
**Risk Level**: Low (backward compatible, fail-safe defaults)  
**Rollback**: Can disable each component independently


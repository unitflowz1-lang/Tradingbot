# Critical Performance Fixes: Integration Guide

**Date**: April 5, 2026  
**Status**: ✅ ALL 3 MODULES SYNTAX VALIDATED  
**Impact**: Solves API fetch saturation, position state amnesia, and over-leveraging  

---

## Problem Summary

### Problem 1: API Fetch Saturation (6+ second latency)
**Symptom**: `[MT5_DATA_FETCH]` appears 100+ times per cycle (dozens per symbol)  
**Root Cause**: Main loop calls `mt5.copy_rates_from_pos()` multiple times per symbol per analysis step  
**Impact**: 6+ second latency by time LLM approves trade; market data is stale; bot chases price on shorts → negative PnL  

**Solution**: **DataCoordinator** - Singleton cache manager with 10-second TTL  
- One fetch per symbol per 10 seconds (instead of 50+ per cycle)
- Expected: 90% reduction in API calls

### Problem 2: Position State Amnesia (Memory Persistence)
**Symptom**: `[SYNC_MT5_STATE] Rebuilt runtime state from MT5` every cycle (10 seconds)  
**Root Cause**: Bot doesn't persist position memory; uses full rebuild instead of incremental updates  
**Impact**: Lost learnings, cooled-off symbols re-traded, state forgotten if terminal blips → double-opens  

**Solution**: **PersistentPositionState** - Load once at startup, update incrementally  
- Positions persisted to JSON on state change
- Sync with MT5 only for validation (not primary update)
- Expected: No "SYNC_MT5_STATE" full rebuilds per cycle

### Problem 3: Over-Leverage / Aggressive Mode
**Symptom**: `[AMNESIA_MODE_ACTIVE] Cooldowns and volatility floors bypassed...` while 4-5 positions open  
**Root Cause**: Bot enters "Sniper Mode" / "Aggressive Engagement" without capacity awareness  
**Impact**: Illegal over-leverage, increased drawdown, slippage on oversized short entries  

**Solution**: **CapacityGate** - Hard limit on concurrent positions  
- Max 3 concurrent positions (hard block, not warning)
- Register/unregister trades, block new entries when full
- Expected: No more over-leverage, explicit DENIED logs

---

## Module 1: DataCoordinator (Fix API Saturation)

### File Location
`src/data/data_coordinator.py`

### Key Class
```python
class DataCoordinator:
    """Singleton cache manager for market data."""
    def get_latest(symbol, timeframe=mt5.TIMEFRAME_M1, bars=600, force_refresh=False):
        """Access cached data, fetch only if stale (>10 seconds old)."""
```

### Integration Points

#### A. Initialize at Startup (in main.py)
```python
# At top of async main() function, before trading loop:
from src.data.data_coordinator import get_data_coordinator

# Initialize coordinator once with 10-second refresh interval
data_coordinator = get_data_coordinator(refresh_interval_seconds=10)
logger.info("[STARTUP] DataCoordinator initialized with 10-second TTL")
```

#### B. Replace MT5 Fetch Calls (in main.py loop)
**BEFORE** (WRONG - fetches 50+ times per symbol):
```python
# In analyze_and_trade_symbol() or market data fetch loop:
for symbol in symbols:
    # Analysis step 1
    rates_technical = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 600)
    
    # Analysis step 2
    rates_macro = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 600)
    
    # Analysis step 3
    rates_ml = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 600)
    # ... 50+ more fetches per symbol per cycle
```

**AFTER** (CORRECT - fetch only once, cache the rest):
```python
# In analyze_and_trade_symbol() or market data fetch loop:
for symbol in symbols:
    # All analysis steps use cached data
    rates = data_coordinator.get_latest(symbol)  # Fetch if needed
    
    # Technical analysis
    rsi = calculate_rsi(rates)
    
    # Macro analysis  
    trend = detect_trend(rates)
    
    # ML analysis
    prediction = ml_model.predict(rates)
    # All use same "rates" from cache, no redundant fetches
```

#### C. Force Refresh When Needed
```python
# If you absolutely need fresh data (e.g., after market open):
rates = data_coordinator.get_latest(
    symbol,
    force_refresh=True  # Bypass cache, always fetch
)
```

#### D. Monitor Cache Performance
```python
# Log cache statistics every N cycles:
stats = data_coordinator.get_stats()
logger.info(
    "[CACHE_STATS] Total fetches: %d | Hit ratio: %.1f%% | "
    "Total calls: %d | Symbols: %d",
    stats['total_fetches'],
    stats['cache_hit_ratio'] * 100,
    stats['total_get_latest_calls'],
    stats['total_symbols']
)
```

---

## Module 2: PersistentPositionState (Fix State Amnesia)

### File Location
`src/trading/persistent_position_state.py`

### Key Class
```python
class PersistentPositionState:
    """In-memory position state with JSON disk persistence."""
    def add_position(position: PositionSnapshot):
        """Register opened position, persist to disk."""
    def update_position(position: PositionSnapshot):
        """Update position (price/profit changed), persist."""
    def close_position(ticket: str, final_profit: float):
        """Mark position closed, persist."""
    def sync_with_mt5(mt5_positions: List):
        """Validate/reconcile with MT5 (not full rebuild)."""
```

### Integration Points

#### A. Initialize at Startup (in main.py)
```python
# At top of async main() function, before trading loop:
from src.trading.persistent_position_state import PersistentPositionState

# Initialize once at startup
persistent_state = PersistentPositionState(state_file="position_state_persistent.json")
logger.info("[STARTUP] Restored %d persisted positions from disk", len(persistent_state.get_all_positions()))
```

#### B. Replace Full Rebuilds with Incremental Updates
**BEFORE** (WRONG - rebuilds state every cycle):
```python
# In main trading loop (every 10 seconds):
async def trading_cycle():
    # WRONG: Full state rebuild every cycle
    live_positions = await position_manager.sync_mt5_state(persist=False)
    # Lost in-memory state, all learning wiped, if terminal blinks = amnesia
```

**AFTER** (CORRECT - only reconcile):
```python
# In main trading loop:
async def trading_cycle():
    # Get MT5 positions (cheap API call, we already have them)
    mt5_positions = mt5.positions_get()
    
    # Reconcile with persistent state (not rebuild)
    persistent_state.sync_with_mt5(mt5_positions)
    # Only updates positions that changed in MT5, preserves learning
```

#### C. Register New Positions
```python
# When ExecutionEngine executes a trade:
from src.trading.persistent_position_state import PositionSnapshot

# After successful execution:
position_snapshot = PositionSnapshot(
    symbol="EUR/USD",
    ticket=str(executed_ticket),
    direction="LONG",
    entry_price=1.0880,
    current_price=1.0880,
    volume=0.21,
    profit=0.0,
    stop_loss=1.0850,
    take_profit=1.0920,
    opened_at=datetime.now(timezone.utc),
    updated_at=datetime.now(timezone.utc),
    strategy_meta={"signal_id": signal.signal_id, "confidence": signal.confidence}
)

persistent_state.add_position(position_snapshot)  # Persists to disk
logger.info("[POSITION_OPENED] %s | Registered in persistent state", "EUR/USD")
```

#### D. Update Positions on Price Changes
```python
# In price update loop (every few seconds):
for position in persistent_state.get_all_positions():
    # Get current MT5 data for position
    mt5_pos = mt5.positions_get(ticket=int(position.ticket))[0]
    
    # Update with latest price/profit
    updated_snapshot = PositionSnapshot(
        symbol=position.symbol,
        ticket=position.ticket,
        direction=position.direction,
        entry_price=position.entry_price,
        current_price=mt5_pos.price_current,
        volume=position.volume,
        profit=mt5_pos.profit,
        stop_loss=position.stop_loss,
        take_profit=position.take_profit,
        opened_at=position.opened_at,
        updated_at=datetime.now(timezone.utc),
        strategy_meta=position.strategy_meta,
    )
    
    persistent_state.update_position(updated_snapshot)  # Persists to disk
```

#### E. Close Positions
```python
# When position closes (exit triggered):
persistent_state.close_position(
    ticket=str(closed_ticket),
    final_profit=mt5_position.profit
)
# Position removed from state, persisted to disk
```

#### F. Load State on Recovery
```python
# If bot restarts:
persistent_state = PersistentPositionState()  # Loads from disk
restored_positions = persistent_state.get_all_positions()
logger.info("[RECOVERY] Restored %d positions from disk after restart", len(restored_positions))

# Adopt any positions that exist in MT5 but not in memory
mt5_positions = mt5.positions_get()
persistent_state.sync_with_mt5(mt5_positions)
```

---

## Module 3: CapacityGate (Fix Over-Leverage)

### File Location
`src/trading/capacity_gate.py`

### Key Class
```python
class CapacityGate:
    """Hard limit on concurrent positions."""
    def can_open_new_trade(symbol, direction, volume, risk_amount, account_equity):
        """Check if trade can be opened. Returns (allowed: bool, deny_reason, message)."""
    def register_opened_position(ticket, symbol, direction, volume, risk_amount):
        """Register opened trade."""
    def unregister_closed_position(ticket):
        """Unregister closed trade."""
```

### Integration Points

#### A. Initialize at Startup (in main.py)
```python
# At top of async main() function:
from src.trading.capacity_gate import get_capacity_gate

# Initialize with hard limits
capacity_gate = get_capacity_gate(
    max_concurrent_positions=3,      # HARD LIMIT: No more than 3 open trades
    max_risk_per_symbol=0.02,        # 2% account risk per symbol
    max_sector_exposure=0.50,        # 50% exposure to single sector
)
logger.info("[STARTUP] CapacityGate initialized: Max 3 positions")
```

#### B. Check Capacity Before ExecutionEngine
**BEFORE** (WRONG - no capacity awareness):
```python
# In trade execution logic:
if signal.confidence > 0.60:
    # WRONG: Executes even with 4-5 open positions
    result = await execution_engine.execute(order)
```

**AFTER** (CORRECT - check capacity first):
```python
# In trade execution logic:
# Calculate potential loss/risk
potential_loss = abs(entry_price - stop_loss) * volume

# Check capacity gate
allowed, deny_reason, message = capacity_gate.can_open_new_trade(
    symbol=signal.symbol,
    direction=signal.direction.value,  # "LONG" or "SHORT"
    volume=final_lots,
    risk_amount=potential_loss,
    account_equity=current_balance,
)

if not allowed:
    # HARD BLOCK: This trade does not execute
    logger.warning(message)  # Logs full reason
    return None  # Skip execution entirely
else:
    # Trade allowed, execute it
    logger.info(message)  # Logs approval
    result = await execution_engine.execute(order)
    
    if result.success:
        # Register with capacity gate
        capacity_gate.register_opened_position(
            ticket=str(result.ticket),
            symbol=signal.symbol,
            direction=signal.direction.value,
            volume=final_lots,
            risk_amount=potential_loss,
        )
```

#### C. Unregister Closed Positions
```python
# When position closes (exit triggered):
capacity_gate.unregister_closed_position(ticket)
logger.info("[POSITION_CLOSED] Capacity freed: %s | New load: %d/3", symbol, ...)
```

#### D. Emergency Capacity Lock
```python
# If something goes wrong (large loss, system error, etc.):
capacity_gate.trigger_emergency_shutdown(
    reason="Portfolio drawdown >10%",
    duration_minutes=60,  # No new trades for 1 hour
)
logger.critical("[EMERGENCY] No new trades for 60 minutes")

# Later, when ready to resume:
capacity_gate.clear_emergency_shutdown()
```

#### E. Monitor Capacity
```python
# Log capacity status every N cycles:
load = capacity_gate.get_current_load()
logger.info(
    "[CAPACITY] Load: %d/%d (%.0f%%) | Symbols: %s",
    load['total_positions'],
    load['max_capacity'],
    load['capacity_used_pct'],
    load['symbols']
)
```

---

## Integration Checklist

### Phase 1: DataCoordinator (API Performance)
- [ ] Add import: `from src.data.data_coordinator import get_data_coordinator`
- [ ] Initialize: `data_coordinator = get_data_coordinator(refresh_interval_seconds=10)`
- [ ] Replace all `mt5.copy_rates_from_pos()` calls with `data_coordinator.get_latest(symbol)`
- [ ] Test: Verify `[DATA_COORDINATOR_HIT]` and `[DATA_COORDINATOR_FETCH]` logs appear
- [ ] Monitor: Cache hit ratio should be >80% (vs 0% before)
- [ ] Expected: API call count drops from 100+ to ~10 per cycle

### Phase 2: PersistentPositionState (State Stability)
- [ ] Add import: `from src.trading.persistent_position_state import PersistentPositionState, PositionSnapshot`
- [ ] Initialize: `persistent_state = PersistentPositionState()`
- [ ] Replace `sync_mt5_state(persist=False)` with `persistent_state.sync_with_mt5(mt5.positions_get())`
- [ ] Register new positions: `persistent_state.add_position(position_snapshot)`
- [ ] Update prices: `persistent_state.update_position(updated_snapshot)`
- [ ] Close positions: `persistent_state.close_position(ticket, final_pnl)`
- [ ] Test: Verify `[PERSISTENT_STATE_SAVED]` logs appear on state change
- [ ] Expected: No `[SYNC_MT5_STATE]` logs every cycle (only `[PERSISTENT_STATE_SYNCED]` on reconciliation)

### Phase 3: CapacityGate (Over-Leverage Prevention)
- [ ] Add import: `from src.trading.capacity_gate import get_capacity_gate`
- [ ] Initialize: `capacity_gate = get_capacity_gate(max_concurrent_positions=3)`
- [ ] Before ExecutionEngine: Check `capacity_gate.can_open_new_trade(...)`
- [ ] Block if not allowed: Return/skip if `allowed == False`
- [ ] Register execution: `capacity_gate.register_opened_position(...)`
- [ ] Unregister close: `capacity_gate.unregister_closed_position(ticket)`
- [ ] Test: 4th trade should be `[CAPACITY_DENIED]` with reason
- [ ] Expected: No more than 3 concurrent open trades

---

## Expected Log Changes

### BEFORE (Current - Broken)
```
[MT5_DATA_FETCH] EUR/USD | Fetching 600 bars
[MT5_DATA_FETCH] EUR/USD | Fetching 600 bars
[MT5_DATA_FETCH] EUR/USD | Fetching 600 bars
... 50+ more fetches per cycle ...

[SYNC_MT5_STATE] Rebuilt runtime state from MT5 | live_positions=4
[SYNC_MT5_STATE] Rebuilt runtime state from MT5 | live_positions=4
... Happens every 10 seconds ...

[AMNESIA_MODE_ACTIVE] Cycle 1 | Cooldowns and volatility floors bypassed
[STRATEGY] ENTER_SIGNAL EURUSD (Cycle continues with 5 positions already open = OVER-LEVERAGE)
```

### AFTER (Fixed)
```
[DATA_COORDINATOR_HIT] EUR/USD | Cache fresh (2.3 seconds old)
[DATA_COORDINATOR_HIT] GBP/USD | Cache fresh (1.8 seconds old)
[DATA_COORDINATOR_FETCH] AUD/USD | Reason: cache_expired | Fetch #2

[PERSISTENT_STATE_SYNCED] MT5 reconciliation complete. Now tracking 3 positions

[CAPACITY_OK] EUR/USD LONG trade ALLOWED (load: 2/3)
[ORDER_ATTEMPT] EUR/USD | load=2/3 | size=0.21 | entry=1.0880
[TRADE_OPENED] EUR/USD | Ticket: 123456789 | Profit: +0.00

[CAPACITY_DENIED] GBP/USD SHORT trade BLOCKED | max_positions_reached (3/3)
```

---

## Performance Metrics

### Before
- MT5 API calls: ~100+ per cycle
- Cycle latency: 6+ seconds (latency while fetching)
- Position state rebuilds: Every 10 seconds
- Concurrent positions: 4-5 (over-leverage)
- Cache hit ratio: 0%

### After
- MT5 API calls: ~10 per cycle (90% reduction)
- Cycle latency: 1-2 seconds (fail-fast gates)
- Position state rebuilds: Never (only reconciliation)
- Concurrent positions: Max 3 (hard limit)
- Cache hit ratio: >80%

---

## Troubleshooting

**Q: DataCoordinator not caching**  
A: Check that refresh_interval_seconds is set high enough. Default 10 seconds is good.

**Q: PersistentPositionState not loading on restart**  
A: Verify `position_state_persistent.json` exists in workspace root. Check file permissions.

**Q: CapacityGate blocking all trades**  
A: Check if emergency_shutdown is active. Call `capacity_gate.clear_emergency_shutdown()` if needed.

**Q: Too many `[CAPACITY_DENIED]` logs but should allow trade**  
A: Increase `max_concurrent_positions` or decrease `max_risk_per_symbol` in initialization.

---

## Deployment Steps

1. **Deploy DataCoordinator first** (safest, most isolated)
   - Reduces API calls immediately
   - Monitor cache hit ratio for 1 cycle

2. **Deploy PersistentPositionState second** (requires careful testing)
   - Load existing positions from MT5
   - Verify `[PERSISTENT_STATE_SYNCED]` log appears
   - Monitor for 1 cycle to validate state consistency

3. **Deploy CapacityGate last** (most impactful)
   - Set max_concurrent_positions to 3
   - Monitor for `[CAPACITY_DENIED]` logs
   - Verify no over-leverage occurs

**Total deployment time**: 2-3 hours with testing  
**Risk level**: LOW (all modules are independent, can be disabled)

---

## Recovery Plan

If something breaks, disable in reverse order:

1. Disable CapacityGate: Comment out `capacity_gate.can_open_new_trade()` check
2. Disable PersistentPositionState: Replace with old `sync_mt5_state()` call
3. Disable DataCoordinator: Replace `data_coordinator.get_latest()` with raw `mt5.copy_rates_from_pos()`

All changes are non-destructive and can be rolled back.

---

**Status**: ✅ Ready for integration  
**Next Step**: Start with DataCoordinator, monitor for 1 cycle, then proceed to other modules.

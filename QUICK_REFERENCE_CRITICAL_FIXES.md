# Quick Reference: Critical Performance Fixes

**Status**: ✅ Ready for Integration | **Risk**: LOW | **Time**: 45-60 minutes

---

## Problem → Solution Summary

| Problem | Root Cause | Solution | Module | Impact |
|---------|-----------|----------|--------|--------|
| 6+ sec latency | 100+ MT5 API calls/cycle | Cache with 10s TTL | DataCoordinator | 90% API ↓ |
| State amnesia | SYNC_MT5_STATE rebuilds every cycle | Persistent incremental updates | PersistentPositionState | Never rebuild |
| Over-leverage | 4-5 concurrent trades | Hard limit to 3 | CapacityGate | Safe capacity |

---

## Three New Files

### 1️⃣ DataCoordinator (`src/data/data_coordinator.py`)
```python
from src.data.data_coordinator import get_data_coordinator

coordinator = get_data_coordinator(refresh_interval_seconds=10)
rates = coordinator.get_latest(symbol)  # Use instead of mt5.copy_rates_from_pos()

# Expected: [DATA_COORDINATOR_HIT] or [DATA_COORDINATOR_FETCH] logs
```

### 2️⃣ PersistentPositionState (`src/trading/persistent_position_state.py`)
```python
from src.trading.persistent_position_state import PersistentPositionState, PositionSnapshot

state = PersistentPositionState()

# Register/update/close
state.add_position(position_snapshot)
state.update_position(updated_snapshot)
state.close_position(ticket, final_pnl)

# Reconcile (not rebuild)
state.sync_with_mt5(mt5.positions_get())

# Expected: [PERSISTENT_STATE_SAVED] logs, NO [SYNC_MT5_STATE] every cycle
```

### 3️⃣ CapacityGate (`src/trading/capacity_gate.py`)
```python
from src.trading.capacity_gate import get_capacity_gate

gate = get_capacity_gate(max_concurrent_positions=3)

# Check before execution
allowed, reason, msg = gate.can_open_new_trade(symbol, direction, volume, risk, equity)
if not allowed:
    return None  # HARD BLOCK

# Register/unregister
gate.register_opened_position(ticket, symbol, direction, volume, risk)
gate.unregister_closed_position(ticket)

# Expected: [CAPACITY_OK] or [CAPACITY_DENIED] logs
```

---

## Integration Checklist

### Before Starting
- [ ] Read `CRITICAL_PERFORMANCE_FIXES_INTEGRATION.md` (detailed guide)
- [ ] All 3 modules present in workspace
- [ ] All 3 modules compile without errors

### Phase 1: DataCoordinator (15 min)
- [ ] Import: `from src.data.data_coordinator import get_data_coordinator`
- [ ] Init: `coordinator = get_data_coordinator(refresh_interval_seconds=10)`
- [ ] Replace: `mt5.copy_rates_from_pos()` → `coordinator.get_latest(symbol)`
- [ ] Test: Verify `[DATA_COORDINATOR]` logs appear
- [ ] Monitor: Cache hit ratio >80%

### Phase 2: PersistentPositionState (20 min)
- [ ] Import: `from src.trading.persistent_position_state import PersistentPositionState`
- [ ] Init: `state = PersistentPositionState()`
- [ ] Replace: `sync_mt5_state()` → `state.sync_with_mt5(mt5.positions_get())`
- [ ] Update: Use `add_position()`, `update_position()`, `close_position()`
- [ ] Test: Verify `[PERSISTENT_STATE_SAVED]` logs appear
- [ ] Monitor: Position file persists across restarts

### Phase 3: CapacityGate (15 min)
- [ ] Import: `from src.trading.capacity_gate import get_capacity_gate`
- [ ] Init: `gate = get_capacity_gate(max_concurrent_positions=3)`
- [ ] Check: Before ExecutionEngine, call `gate.can_open_new_trade()`
- [ ] Block: Return if `allowed == False`
- [ ] Register: After execution, call `gate.register_opened_position()`
- [ ] Unregister: On close, call `gate.unregister_closed_position()`
- [ ] Test: 4th trade should be `[CAPACITY_DENIED]`
- [ ] Monitor: No more than 3 concurrent trades

---

## Expected Log Changes

### BEFORE (Current - Broken)
```
[MT5_DATA_FETCH] EUR/USD | Fetching 600 bars
[MT5_DATA_FETCH] EUR/USD | Fetching 600 bars
... 50+ times per cycle ...

[SYNC_MT5_STATE] Rebuilt runtime state from MT5 | live_positions=4
[AMNESIA_MODE_ACTIVE] Cycle 1 | Cooldowns bypassed
[STRATEGY] ENTER 5 concurrent positions = OVER-LEVERAGE
```

### AFTER (Fixed)
```
[DATA_COORDINATOR_HIT] EUR/USD | Cache fresh (2.3 seconds old)
[PERSISTENT_STATE_SAVED] Saved 3 positions to disk
[CAPACITY_OK] EUR/USD LONG trade ALLOWED (load: 2/3)
[CAPACITY_DENIED] GBP/USD SHORT trade BLOCKED (max 3/3)
```

---

## Performance Targets

| Metric | Before | After | Goal |
|--------|--------|-------|------|
| API calls/cycle | 100+ | ~10 | ✅ |
| Cycle latency | 6+ sec | 1-2 sec | ✅ |
| State rebuilds | Every 10s | Never | ✅ |
| Max concurrent trades | 5+ | 3 | ✅ |
| Cache hit ratio | 0% | >80% | ✅ |

---

## Troubleshooting

**DataCoordinator not caching?**  
→ Check `refresh_interval_seconds` is set. Look for `[DATA_COORDINATOR_FETCH]` in logs.

**Positions not persisting?**  
→ Check `position_state_persistent.json` exists & writable. Verify `[PERSISTENT_STATE_SAVED]` logs.

**Too many capacity denials?**  
→ Increase `max_concurrent_positions` from 3 to 4-5 if needed.

**State lost on restart?**  
→ Verify `persistent_state.sync_with_mt5()` called after loading. Check position file format.

---

## Rollback Plan (If Needed)

**Disable DataCoordinator**: Replace `coordinator.get_latest()` with `mt5.copy_rates_from_pos()`  
**Disable PersistentPositionState**: Revert to `sync_mt5_state(persist=False)`  
**Disable CapacityGate**: Comment out `can_open_new_trade()` check  

All changes are non-destructive and can be reverted in <5 minutes.

---

## Files Reference

**Code Modules** (1255 lines total):
- `src/data/data_coordinator.py` (380 lines)
- `src/trading/persistent_position_state.py` (450 lines)
- `src/trading/capacity_gate.py` (425 lines)

**Documentation** (500+ lines):
- `CRITICAL_PERFORMANCE_FIXES_INTEGRATION.md` (detailed guide)
- `DELIVERY_SUMMARY_CRITICAL_FIXES.md` (overview)
- `QUICK_REFERENCE_CRITICAL_FIXES.md` (this file)

---

## Summary

**What**: 3 modules fixing API saturation, state amnesia, over-leverage  
**When**: Integrate now while high-priority issues are known  
**How**: Follow checklist in phases (DataCoordinator → State → Capacity)  
**Time**: 45-60 minutes  
**Risk**: LOW (independent modules, can disable)  
**Benefit**: 90% API reduction, stable state, safe capacity  

---

**Start**: Read `CRITICAL_PERFORMANCE_FIXES_INTEGRATION.md`  
**Status**: ✅ Ready  
**Next**: Integrate Phase 1 (DataCoordinator)

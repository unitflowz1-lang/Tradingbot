# MOMENTUM PROFIT SYSTEM - QUICK REFERENCE CARD

**Status:** ✅ IMPLEMENTED & VERIFIED (55/55 checks)  
**Integration:** Ready for main.py trading loop  

---

## The Three Core Promises

### 1️⃣ HUNTS FOR 2.0R+ MOVES
```
Entry → 0.3R (Breakeven Lock)
      → 0.8R (Chandelier Trail Activation)
      → 1.2R (Scale-Out 25%, Remaining Runs)
      → 2.0R+ (Target Peak)
```

### 2️⃣ PROTECTS CAPITAL
```
Immutable Breakeven Lock at 0.3R
One-Way Trailing (Never Widens)
Most-Protective-Wins for Conflicts
Tokyo Adaptation (20 bars ADX<18)
ML Confidence Killswitch (< 30%)
```

### 3️⃣ AVOIDS REVERSALS
```
Exhaustion Bar Detection (65% body)
Trend Stagnation (3 bars no new extreme)
Reversal Risk Scoring (Momentum+RSI+Volume)
Tight Leash Defense (Peak-based SL)
```

---

## Phase Progression

| Phase | R-Range | Rule | Action |
|-------|---------|------|--------|
| Breakeven Lock | 0.0 → 0.3R | Lock SL immutably | Entry + 1 pip |
| Accumulation | 0.3 → 0.8R | Hold & monitor | Watch exhaustion |
| Trail Activation | 0.8 → 1.2R | Chandelier ATR trail | Dynamic SL |
| Scale-Out | 1.2R | Close 25% | SL → Entry+0.5R for 75% |
| Peak Hold | 1.2R+ | Remaining 75% trail | To 2.0R+ or reversal |

---

## Configuration Checklist

```env
✓ BREAKEVEN_TRIGGER_R=0.3
✓ TRAIL_ACTIVATION_R=0.8
✓ TRAIL_ATR_MULTIPLIER=1.5
✓ SCALE_OUT_TRIGGER_R=1.2
✓ EXHAUSTION_BODY_THRESHOLD_PCT=65
✓ ML_CONFIDENCE_EXIT_THRESHOLD=0.30
✓ TOKYO_STAGNATION_BARS_MAX=20
✓ TOKYO_STAGNATION_OVERRIDE=true
(15 more parameters in .env.optimized)
```

---

## Exit Priority Hierarchy

```
1. BROKER SL           ← Absolute highest (cannot override)
2. BREAKEVEN LOCK      ← Immutable once set
3. ML < 30% EXIT       ← Force close market signal
4. CHANDELIER/LEASH    ← Most protective wins conflict
5. 25% SCALE-OUT       ← One-time insurance
6. STAGNATION          ← 40 or 20 bars Tokyo
```

---

## Method Call Sequence (Per Cycle)

```python
# 1. Calculate R
current_r = momentum_mgr.calculate_r_multiple(...)

# 2. Breakeven lock (0.3R)
be_lock, sl_update = momentum_mgr.apply_breakeven_lock(...)
if be_lock: update_sl(sl_update)

# 3. Chandelier trail (0.8R+)
trail, sl_update = momentum_mgr.update_chandelier_trail(...)
if trail: update_sl(sl_update)

# 4. Scale-out (1.2R)
scale, scale_dict = momentum_mgr.check_scale_out_1_2r(...)
if scale: close_25_percent(scale_dict)

# 5. Exhaustion detection
exhaustion = momentum_mgr.detect_exhaustion_reversal(...)

# 6. Tight leash (if reversal risk > 70%)
leash, sl_update = momentum_mgr.apply_tight_leash_if_reversal_risk(...)
if leash: update_sl(sl_update)

# 7. ML confidence exit (< 30%)
ml_exit, exit_dict = momentum_mgr.check_ml_confidence_exit(...)
if ml_exit: close_100_percent(exit_dict)

# 8. Resolve conflicts (most protective)
effective_sl = momentum_mgr.resolve_conflicting_sls(...)
update_sl(effective_sl)

# 9. Tokyo stagnation check
limit = momentum_mgr.get_effective_stagnation_limit(position, adx=current_adx)
if bars_held > limit: force_close()
```

---

## Key Algorithms

### Breakeven Lock
```
IF current_r >= 0.3R:
  SL = Entry + (Spread + 1 pip)
  LOCK = immutable, irreversible
  RETURN: (True, sl_update)
```

### Chandelier Trail
```
IF current_r >= 0.8R:
  FOR LONG:
    trail_sl = MIN(last_14_bars_low) + (ATR_14 * 1.5)
  FOR SHORT:
    trail_sl = MAX(last_14_bars_high) - (ATR_14 * 1.5)
  
  IF trail_sl is tighter AND price moved 2+ pips:
    UPDATE sl
    RETURN: (True, sl_update)
  ELSE:
    RETURN: (False, None)
```

### Scale-Out 1.2R
```
IF current_r >= 1.2R AND not yet_scaled_out:
  CLOSE 25% at market
  new_sl = Entry + (Risk * 0.5)
  FOR remaining 75%:
    SET sl = new_sl
  RETURN: (True, scale_dict)
```

### Exhaustion Detection
```
FOR last 3 candles:
  body_pct = (close - open) / (high - low) * 100
  IF body_pct > 65% AND direction opposite trade:
    exhaustion_count += 1
RETURN: (exhaustion_count > 0, count)
```

### Tight Leash (Reversal > 70%)
```
reversal_risk = (momentum_score + rsi_score + vol_score) / 3
IF reversal_risk > 0.7:
  FOR LONG: tight_sl = LOW of last candle
  FOR SHORT: tight_sl = HIGH of last candle
  ACTIVATE tight_leash
  RETURN: (True, sl_update)
```

### Conflict Resolution
```
MOST_PROTECTIVE_SL = tightest SL among:
  1. breakeven_lock
  2. tight_leash  
  3. chandelier_trail
APPLY: most_protective_sl
```

---

## Files Delivered

| File | Purpose | Status |
|------|---------|--------|
| momentum_exit_manager.py | Core module (1050+ lines) | ✅ Ready |
| MOMENTUM_PROFIT_SYSTEM_GUIDE.md | Integration guide (500+ lines) | ✅ Ready |
| MOMENTUM_EXIT_SYSTEM_VERIFICATION.py | 55 automated checks | ✅ Passing |
| .env.optimized | 19 new parameters | ✅ Added |
| MOMENTUM_IMPLEMENTATION_COMPLETE.md | Summary document | ✅ Done |

---

## Critical Do's & Don'ts

### ✅ DO
- [ ] Lock breakeven immutably (enforce, no exceptions)
- [ ] Tighten trail only, never widen
- [ ] Apply most protective SL in conflicts
- [ ] Scale-out exactly once at 1.2R
- [ ] Force close at ML confidence < 30% if profitable
- [ ] Use 20-bar limit in Tokyo if ADX < 18
- [ ] Monitor exhaustion every cycle
- [ ] Enable ATR-based chandelier trail

### ❌ DON'T
- [ ] Remove breakeven lock early
- [ ] Widen trailing stop
- [ ] Apply second scale-out
- [ ] Exit at market when tight leash should manage
- [ ] Override most-protective-wins rule
- [ ] Use 40 bars in Tokyo ADX < 18
- [ ] Ignore exhaustion bar signals
- [ ] Disable chandelier trail before 0.8R

---

## Testing Checklist

Before production, verify:

- [ ] Backtest R-multiple improves (+0.3R minimum)
- [ ] Breakeven lock never triggers below entry+1pip
- [ ] Trail never widens, only tightens
- [ ] Scale-out triggers exactly at 1.2R
- [ ] Scale-out closes exactly 25% (not 20%, not 30%)
- [ ] Remaining 75% SL moves to Entry+0.5R
- [ ] Exhaustion detection identifies 65%+ body candles
- [ ] Tight leash activates when reversal risk > 70%
- [ ] ML < 30% triggers market close (profit only)
- [ ] Tokyo 20-bar limit applies when ADX < 18
- [ ] Conflict resolution picks tightest SL every time
- [ ] No SL violations or conflicts in logs

---

## Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| Exits at 0.8R | Increase TRAIL_ATR_MULTIPLIER to 2.0 |
| Trail not activating | Check if reaching 0.8R in backtests |
| Scale-out missing | Verify SCALE_OUT_TRIGGER_R = 1.2 |
| SL below breakeven | Bug: check resolve_conflicting_sls() |
| Tokyo 20-bar not working | Check TOKYO_STAGNATION_OVERRIDE = true |
| ML exit too frequent | Raise ML_CONFIDENCE_EXIT_THRESHOLD to 0.40 |
| Exhaustion never detected | Lower EXHAUSTION_BODY_THRESHOLD_PCT to 60% |

---

## Integration Workflow

```
1. IMPORT
   from src.trading.momentum_exit_manager import MomentumExitManager

2. INITIALIZE (startup)
   momentum_mgr = MomentumExitManager(logger, broker)

3. REGISTER (on entry)
   momentum_mgr.register_position(position)

4. CALCULATE (each cycle)
   current_r = momentum_mgr.calculate_r_multiple(...)

5. APPLY (each method)
   breakeven = momentum_mgr.apply_breakeven_lock(...)
   trail = momentum_mgr.update_chandelier_trail(...)
   scale = momentum_mgr.check_scale_out_1_2r(...)
   leash = momentum_mgr.apply_tight_leash_if_reversal_risk(...)
   ml_exit = momentum_mgr.check_ml_confidence_exit(...)

6. RESOLVE (conflict)
   effective_sl = momentum_mgr.resolve_conflicting_sls(...)

7. UPDATE (broker)
   update_broker_sl(effective_sl)

8. EXECUTE (actions)
   if scale: close_25_percent()
   if ml_exit: close_100_percent()

9. MONITOR (logs)
   Watch for momentum exit signals
```

---

## Performance Targets

### Conservative Estimate
- R-multiple improvement: +0.3R
- Win rate improvement: +5%
- Drawdown reduction: -3 days recovery

### Optimistic Target
- R-multiple improvement: +0.5R
- Win rate improvement: +10%
- Drawdown reduction: -5 days recovery

### Success Thresholds (Backtesting)
- ✅ 70%+ trades reach breakeven lock (0.3R)
- ✅ 40%+ trades reach trail activation (0.8R)
- ✅ 15%+ trades achieve scale-out (1.2R)
- ✅ 5%+ trades hit 2.0R+ target

---

**Status:** ✅ Ready for Integration  
**Next:** Integrate into main.py trading loop  
**Questions?** See MOMENTUM_PROFIT_SYSTEM_GUIDE.md for complete documentation

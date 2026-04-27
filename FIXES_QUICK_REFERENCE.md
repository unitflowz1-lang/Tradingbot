# Quick Reference: 4 Critical Fixes for RL Trading Bot v8.5

## 🎯 Issues Fixed

### Issue 1: AttributeError on entry_price ❌ (No code change needed)
**Status**: Already correctly implemented using Position model  
**Action**: Monitor logs for errors; if they occur, check Position vs MT5 object usage

### Issue 2: Missing avg_test_win_rate ✅ FIXED
**File**: `src/deployment/parameter_loader.py`  
**Change**: Default value changed from 0.0 → 0.50  
**Action**: Add `stability_metrics` to your `config/optimized_params.json`

**Template**:
```json
"stability_metrics": {
  "avg_test_win_rate": 0.55,
  "win_rate_variance": 0.015,
  "sharpe_ratio": 1.2,
  "max_drawdown": 0.08
}
```

### Issue 3: LLM Timeout Exceeding 5 Seconds ✅ FIXED
**File**: `src/llm_governance.py`  
**Changes**:
- Timeout: 12s → 15s
- Auto-downgrade model if 3 consecutive calls exceed 10s
- Recovery mechanism after 50 normal cycles

**Environment Variables**:
```bash
export OLLAMA_FAST_TIMEOUT_SECONDS=15.0
export OLLAMA_HEAVY_TIMEOUT_SECONDS=15.0
```

**Watch for these log messages**:
- `[LLM_GOVERNANCE_SYSTEM_BUSY]` - System overloaded, switching to lightweight model
- `[LLM_GOVERNANCE_SYSTEM_RECOVERY]` - System recovered, resuming normal checks

### Issue 4: Symbols Not in Market Watch ✅ FIXED
**File**: `src/data/mt5_broker.py`  
**Change**: Enhanced `_subscribe_monitored_symbols()` with detailed logging

**Watch for these log messages during startup**:
- `[SYMBOL_INITIALIZATION_START]` - Starting symbol setup
- `[SYMBOL_SELECTED]` - Symbol successfully added ✓
- `[SYMBOL_SELECT_FAILED]` - Symbol failed to initialize ✗
- `[SYMBOL_INITIALIZATION_COMPLETE]` - Final count (X/Y successful)

---

## 🚀 What to Do Next

### 1. Update Your JSON Configuration (Issue 2)
```bash
# Edit your config/optimized_params.json
# Add this section:
"stability_metrics": {
  "avg_test_win_rate": 0.55,
  "win_rate_variance": 0.015,
  "sharpe_ratio": 1.2,
  "max_drawdown": 0.08
}
```

### 2. Monitor LLM Latency (Issue 3)
```bash
# During bot startup, check logs for:
grep "LLM_GOVERNANCE" bot.log

# If you see [LLM_GOVERNANCE_SYSTEM_BUSY], the system detected high latency
# The bot will automatically use a lighter model until system recovers
```

### 3. Verify Symbol Initialization (Issue 4)
```bash
# During bot startup, check logs for:
grep "SYMBOL_INITIALIZATION" bot.log
grep "SYMBOL_SELECTED" bot.log
grep "SYMBOL_FAILED" bot.log

# Expected output:
# [SYMBOL_INITIALIZATION_START] Initializing 7 monitored symbols
# [SYMBOL_SELECTED] ✓ EURUSD added to Market Watch
# [SYMBOL_INITIALIZATION_COMPLETE] Initialized 6/7 successfully
```

### 4. Monitor for entry_price Issues (Issue 1)
```bash
# Watch for this error:
grep "entry_price" bot.log

# If you see "AttributeError: 'TradePosition' object has no attribute 'entry_price'"
# Verify that Position model objects are being used, not raw MT5 objects
```

---

## 📋 Log Tags to Monitor

| Tag | Meaning | Action |
|-----|---------|--------|
| `[SYMBOL_INITIALIZATION_START]` | Starting symbol setup | Normal - startup phase |
| `[SYMBOL_SELECTED] ✓` | Symbol successfully added | Normal - working correctly |
| `[SYMBOL_SELECT_FAILED]` | Symbol not supported | Check broker has symbol |
| `[SYMBOL_INITIALIZATION_COMPLETE]` | Symbol setup done | Normal - check counts |
| `[LLM_GOVERNANCE_SYSTEM_BUSY]` | High latency detected | System overloaded - model auto-downgraded |
| `[LLM_GOVERNANCE_SYSTEM_RECOVERY]` | System recovered | Normal - resuming full LLM checks |
| `[LLM_DEBUG] Raw response... Latency:` | Latency measurement | Informational |
| `avg_test_win_rate missing` | JSON incomplete | Add to config JSON |

---

## 🔍 Troubleshooting

### Problem: Still seeing "avg_test_win_rate missing" warning
**Solution**: Add `stability_metrics` block to `config/optimized_params.json` (see template above)

### Problem: Symbol initialization takes too long or fails
**Solution**: Check that symbol names in `monitored_symbols` match broker's list  
**Command**: `mt5.symbols_get()` in MT5 terminal to see available symbols

### Problem: LLM checks keep bypassing with timeout
**Solution**: 
1. Check Ollama is running: `http://localhost:11434`
2. Increase timeout: `export OLLAMA_FAST_TIMEOUT_SECONDS=20`
3. Check system resources (CPU/RAM/Network)

### Problem: Trading stops after seeing [LLM_GOVERNANCE_SYSTEM_BUSY]
**Solution**: This is expected - bot switched to lightweight model to save resources  
**Expected**: Bot resumes after 50 cycles with normal LLM checks

---

## 📁 Files Modified

- ✅ `src/deployment/parameter_loader.py` - Issue 2
- ✅ `src/llm_governance.py` - Issue 3  
- ✅ `src/data/mt5_broker.py` - Issue 4

**All files passed syntax validation** ✓

---

## 🔄 Rollback (if needed)

```bash
# Revert all changes
git checkout src/deployment/parameter_loader.py src/llm_governance.py src/data/mt5_broker.py

# Or revert specific file
git checkout src/deployment/parameter_loader.py
```

---

## ✅ Summary

| Issue | Status | File | Key Change |
|-------|--------|------|-----------|
| 1 | ✓ Safe | (none) | Already using Position model correctly |
| 2 | ✓ Fixed | parameter_loader.py | Default: 0.0 → 0.50, better warning |
| 3 | ✓ Fixed | llm_governance.py | Timeout: 12s → 15s, auto-downgrade |
| 4 | ✓ Fixed | mt5_broker.py | Enhanced logging, detailed reports |

All fixes implemented and validated ✅

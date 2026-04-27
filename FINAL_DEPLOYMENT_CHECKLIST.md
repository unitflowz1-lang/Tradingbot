# Deployment Checklist: 4 Critical Fixes v8.5

## Pre-Deployment

- [ ] **Backup Current Code**
  ```bash
  git commit -m "Pre-critical-fixes backup"
  ```

- [ ] **Review Changes**
  - [ ] `src/deployment/parameter_loader.py` - Reviewed ✓
  - [ ] `src/llm_governance.py` - Reviewed ✓
  - [ ] `src/data/mt5_broker.py` - Reviewed ✓

- [ ] **Syntax Validation**
  ```bash
  python -m py_compile src/deployment/parameter_loader.py
  python -m py_compile src/llm_governance.py
  python -m py_compile src/data/mt5_broker.py
  # Expected: No output = all OK ✓
  ```

---

## Configuration Updates

### Issue 2: Update JSON Configuration

- [ ] **Open config/optimized_params.json**

- [ ] **Add stability_metrics section**
  ```json
  "stability_metrics": {
    "avg_test_win_rate": 0.55,
    "win_rate_variance": 0.015,
    "sharpe_ratio": 1.2,
    "max_drawdown": 0.08
  }
  ```

- [ ] **Validate JSON syntax**
  ```bash
  python -c "import json; json.load(open('config/optimized_params.json'))" && echo "JSON OK ✓"
  ```

- [ ] **Save file**

---

## Environment Setup

### Issue 3: Ollama Timeouts (Optional)

- [ ] **Check Ollama service is running**
  ```bash
  curl http://localhost:11434
  # Expected: Connected ✓
  ```

- [ ] **Optional: Set higher timeouts**
  ```bash
  # PowerShell
  $env:OLLAMA_FAST_TIMEOUT_SECONDS = "20.0"
  $env:OLLAMA_HEAVY_TIMEOUT_SECONDS = "20.0"
  
  # OR bash/Linux
  export OLLAMA_FAST_TIMEOUT_SECONDS=20.0
  export OLLAMA_HEAVY_TIMEOUT_SECONDS=20.0
  ```

---

## Deployment

### Step 1: Start Bot

- [ ] **Open terminal**

- [ ] **Activate Python environment**
  ```bash
  .venv\Scripts\activate  # Windows
  source .venv/bin/activate  # Linux/Mac
  ```

- [ ] **Start bot**
  ```bash
  python main.py
  ```

- [ ] **Bot starts without errors** ✓

---

### Step 2: Monitor Issue 1 (entry_price)

**Expected**: No errors related to entry_price

- [ ] **Check logs for AttributeError**
  ```bash
  grep -i "entry_price" bot.log
  # Expected: No results ✓
  ```

- [ ] **Check logs for TradePosition**
  ```bash
  grep -i "TradePosition" bot.log
  # Expected: No results ✓
  ```

---

### Step 3: Monitor Issue 2 (Stability Metrics)

**Expected During Startup**: 
- Loads stability_metrics from JSON
- If missing: Shows warning with default value (0.50)

- [ ] **Check logs for stability_metrics**
  ```bash
  grep "stability_metrics\|avg_test_win_rate" bot.log
  
  # Expected output:
  # ✓ "Loaded stability_metrics: avg_test_win_rate=0.55"
  # OR
  # ⚠️ "avg_test_win_rate missing... Using default value (0.50)"
  ```

- [ ] **If warning appears**: JSON config needs the field
  - Go back to JSON update step above

---

### Step 4: Monitor Issue 3 (LLM Timeout)

**Expected During Trading**:
- LLM calls succeed within 15 seconds
- If sustained > 10s: System busy detection triggers
- Auto-recovery after 50 normal cycles

- [ ] **Watch for LLM latency messages**
  ```bash
  tail -f bot.log | grep -E "LLM_DEBUG|Latency"
  
  # Expected output:
  # [LLM_DEBUG] Raw response... Latency: 4523ms
  # [LLM_DEBUG] Raw response... Latency: 6234ms
  # [LLM_DEBUG] Raw response... Latency: 3456ms
  # ... (various latencies under 15000ms)
  ```

- [ ] **If system busy detected**
  ```bash
  grep "LLM_GOVERNANCE_SYSTEM_BUSY" bot.log
  
  # Expected message:
  # [LLM_GOVERNANCE_SYSTEM_BUSY] System detected as busy: 
  # 3 consecutive calls exceeded 10000.0ms threshold...
  ```

- [ ] **Verify recovery after 50 cycles**
  ```bash
  grep "LLM_GOVERNANCE_SYSTEM_RECOVERY" bot.log
  
  # Expected message:
  # [LLM_GOVERNANCE_SYSTEM_RECOVERY] System recovered...
  ```

---

### Step 5: Monitor Issue 4 (Symbol Initialization)

**Expected During Startup**: 
- All monitored symbols added to Market Watch
- Detailed per-symbol logging
- Final success/failure count

- [ ] **Check symbol initialization starts**
  ```bash
  head -100 bot.log | grep "SYMBOL_INITIALIZATION_START"
  
  # Expected:
  # [SYMBOL_INITIALIZATION_START] Initializing 7 monitored symbols
  ```

- [ ] **Check individual symbol initialization**
  ```bash
  grep "SYMBOL_SELECTED\|SYMBOL_FAILED" bot.log | head -20
  
  # Expected:
  # [SYMBOL_SELECTED] ✓ EURUSD added to Market Watch
  # [SYMBOL_SELECTED] ✓ GBPUSD added to Market Watch
  # [SYMBOL_SELECT_FAILED] ... (if any fail)
  ```

- [ ] **Check final initialization report**
  ```bash
  grep "SYMBOL_INITIALIZATION_COMPLETE" bot.log
  
  # Expected:
  # [SYMBOL_INITIALIZATION_COMPLETE] Initialized 6/7 symbols successfully...
  ```

- [ ] **Verify all symbols in Market Watch**
  - Open MT5 Terminal
  - View → Market Watch
  - Verify all symbols from config are listed ✓

---

## Validation Tests

### Test 1: Configuration Load
```bash
# Check that config loads without errors
grep -i "config\|parameter" bot.log | head -20

# Should show successful loading of all sections
```

**Result**: ✓ or ✗

### Test 2: Trading Cycle
```bash
# Let bot run for 1-2 minutes and check for errors
grep -i "error\|exception\|traceback" bot.log

# Expected: No critical errors
```

**Result**: ✓ or ✗

### Test 3: Signal Generation
```bash
# Check that signals are being generated
grep "LLM_GOVERNANCE\|SIGNAL" bot.log | head -20

# Should show governance decisions and signals
```

**Result**: ✓ or ✗

### Test 4: Trade Execution
```bash
# Open a manual trade and check bot response
grep "ORDER\|POSITION" bot.log | tail -20

# Should show trade placement logs
```

**Result**: ✓ or ✗

---

## Success Criteria

All of the following must be true for successful deployment:

### Issue 1: ✓ entry_price
- [ ] No AttributeError messages in logs
- [ ] No TradePosition references
- [ ] Trading continues normally

### Issue 2: ✓ Stability Metrics  
- [ ] JSON loads successfully
- [ ] No config errors during startup
- [ ] Stability metrics appear in logs

### Issue 3: ✓ LLM Timeout
- [ ] LLM calls complete within 15 seconds
- [ ] If system busy: Auto-recovery triggered
- [ ] No permanent timeouts

### Issue 4: ✓ Symbol Initialization
- [ ] [SYMBOL_INITIALIZATION_COMPLETE] appears in logs
- [ ] All symbols show [SYMBOL_SELECTED] ✓
- [ ] Symbols appear in MT5 Market Watch

---

## Rollback Plan

If any test fails:

### Option 1: Quick Rollback (Git)
```bash
# Revert all three files
git checkout src/deployment/parameter_loader.py
git checkout src/llm_governance.py
git checkout src/data/mt5_broker.py

# Restart bot
python main.py
```

### Option 2: Manual Rollback
Delete three files from backup/previous version and restore them.

### Option 3: Investigate Issue
Check logs for specific error messages and refer to:
- CRITICAL_FIXES_IMPLEMENTATION_SUMMARY.md
- IMPLEMENTATION_GUIDE.md

---

## Production Monitoring

### First 24 Hours
- [ ] Monitor for [LLM_GOVERNANCE_SYSTEM_BUSY] messages
- [ ] Check symbol initialization logs
- [ ] Watch for any AttributeError exceptions
- [ ] Track profit/loss metrics

### Weekly Check
- [ ] Review stability_metrics configuration
- [ ] Check average LLM latency trends
- [ ] Verify symbol initialization success rate
- [ ] Review error logs

### Monthly Check
- [ ] Adjust timeouts if needed
- [ ] Update stability_metrics based on backtest results
- [ ] Review system performance metrics
- [ ] Plan any additional improvements

---

## Success Log Examples

### Successful Startup (All Issues Fixed)
```
[2026-04-17 10:30:15] INFO | Bot starting...
[2026-04-17 10:30:16] INFO | [SYMBOL_INITIALIZATION_START] Initializing 7 monitored symbols
[2026-04-17 10:30:17] INFO | [SYMBOL_SELECTED] ✓ EURUSD added to Market Watch
[2026-04-17 10:30:17] INFO | [SYMBOL_SELECTED] ✓ GBPUSD added to Market Watch
[2026-04-17 10:30:18] INFO | [SYMBOL_SELECTED] ✓ USDJPY added to Market Watch
[2026-04-17 10:30:19] INFO | [SYMBOL_SELECTED] ✓ AUDUSD added to Market Watch
[2026-04-17 10:30:19] INFO | [SYMBOL_SELECTED] ✓ USDCAD added to Market Watch
[2026-04-17 10:30:20] INFO | [SYMBOL_SELECTED] ✓ NZDUSD added to Market Watch
[2026-04-17 10:30:20] INFO | [SYMBOL_INITIALIZATION_COMPLETE] Initialized 6/6 symbols successfully. Failed: 0
[2026-04-17 10:30:21] INFO | Loaded stability_metrics: avg_test_win_rate=0.55
[2026-04-17 10:30:22] INFO | Bot ready to trade
[2026-04-17 10:35:23] INFO | [LLM_DEBUG] Raw response... Latency: 4523ms
[2026-04-17 10:35:28] INFO | [LLM_DEBUG] Raw response... Latency: 3234ms
[2026-04-17 10:35:33] INFO | Trading cycle completed successfully
```

---

## Sign-Off

- [ ] **Deployer Name**: ___________________
- [ ] **Date**: ___________________
- [ ] **Version**: v8.5
- [ ] **All Tests Passed**: Yes ☐ No ☐

---

## Notes

Use this space to document any issues found during deployment:

```
_________________________________________________________________________

_________________________________________________________________________

_________________________________________________________________________
```

---

**Deployment Complete!** ✅

Monitor the bot for 1-2 hours to ensure all fixes are working correctly, then resume normal operations.

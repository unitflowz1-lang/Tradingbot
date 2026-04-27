# OLLAMA EMPTY RESPONSE FIX — QUICK START GUIDE

## TL;DR: What Changed?

| Aspect | Before | After |
|--------|--------|-------|
| Primary Timeout | 15s | 60s ✅ |
| Fallback Timeout | 30s | 45s ✅ |
| Error Logging | Generic | Detailed (HTTP codes, connections) ✅ |
| Keep-Alive | ❌ | 5 minutes ✅ |
| Exception Handling | Minimal | Comprehensive ✅ |

## 1. Deploy the Fix

✅ **Code changes already applied to:**
- `src/llm_governance.py` (timeouts + exception handling)
- `src/analysis/llm_macro_monitor.py` (timeouts + exception handling)
- `test_ollama_connectivity.py` (new test script)

## 2. Configure Environment Variables

Add to your `.env` file or export before running:

```bash
# Governance layer (primary decision-making)
export OLLAMA_FAST_TIMEOUT_SECONDS=60.0
export OLLAMA_HEAVY_TIMEOUT_SECONDS=60.0

# Macro monitor (background risk assessment)
export MACRO_MONITOR_PRIMARY_TIMEOUT_SECONDS=60.0
export MACRO_MONITOR_FALLBACK_TIMEOUT_SECONDS=45.0

# Connection details
export OLLAMA_BASE_URL=http://localhost:11434
```

## 3. Verify Ollama Setup

### Step 1: Check if Ollama is running
```bash
curl http://localhost:11434/api/tags
```

Should return JSON with models list (not a connection error).

### Step 2: Verify model is installed
```bash
curl http://localhost:11434/api/tags | grep qwen
```

Should show `"qwen3.5:0.8b"` in the list.

If not, install it:
```bash
ollama pull qwen3.5:0.8b
```

### Step 3: Run the connectivity test
```bash
python test_ollama_connectivity.py
```

Expected output:
```
======================================================================
OLLAMA CONNECTIVITY TEST
======================================================================

Configuration:
  Host: localhost
  Port: 11434
  Base URL: http://localhost:11434
  Model: qwen3.5:0.8b

Running: Port Reachability...
[✓] Port 11434 is open and reachable

Running: Service Health...
[✓] Ollama service healthy (HTTP 200)

Running: Model Installation...
[✓] Qwen models installed: qwen3.5

Running: Generate Endpoint...
[✓] Model responded successfully in 2.45s

======================================================================
RESULTS: 4 passed, 0 failed
======================================================================

[✓] All checks passed! Ollama is ready.
```

## 4. Start Your Bot

```bash
# Set environment if not in .env
export OLLAMA_FAST_TIMEOUT_SECONDS=60.0
export MACRO_MONITOR_PRIMARY_TIMEOUT_SECONDS=60.0

# Run bot
python main.py
```

## 5. Verify Fix is Working

### Good logs (what you should see):
```
[LLM_GOVERNANCE] HTTP 200 response received
[MACRO_MONITOR] Cache updated for 8 symbols
[LLM_GOVERNANCE_AUDIT] Decision: approve | Latency: 2341ms
```

### Bad logs (old behavior - should NOT see these):
```
❌ [MACRO_MONITOR] Empty Ollama response on attempt 1/3 (timeout=15.0s)
❌ [TECHNICAL_ONLY_MODE] Ollama unreachable
❌ [MACRO_MONITOR] Local Ollama cooldown (5m) due to EMPTY_RESPONSE
```

### New detailed error logs (if there's a real problem):
```
[LLM_GOVERNANCE_HTTP_ERROR] Ollama HTTP 404 | model=qwen3.5:0.8b | timeout=60.0s
[LLM_GOVERNANCE_CONNECTION_ERROR] Ollama unreachable | reason=Connection refused
[LLM_GOVERNANCE_TIMEOUT] Ollama timeout after 60.0s | model=qwen3.5:0.8b
```

## 6. Performance Expectations

| Hardware | First Call | Subsequent Calls |
|----------|-----------|-----------------|
| CPU only | 20-40s | 8-15s |
| GPU (CUDA) | 8-12s | 1-3s |
| GPU (Apple Metal) | 5-8s | 1-2s |

The keep-alive parameter keeps the model in memory for 5 minutes, so:
- Trading cycles within 5 min: Use cached model (fast)
- After 5 min idle: Model unloads, next call takes longer

## 7. Troubleshooting

| Problem | Solution |
|---------|----------|
| Still getting empty responses | Run `test_ollama_connectivity.py` to see detailed error |
| "Ollama HTTP 404" | Run `ollama pull qwen3.5:0.8b` |
| "Connection refused" | Ensure Ollama is running: `ollama serve` |
| Timeouts even with 60s | Increase to 120s or use smaller model: `qwen2.5:0.5b` |
| Model loads very slowly | Check if Ollama is using GPU: `ollama info` |

## 8. Key Improvements in Error Logging

Before (unhelpful):
```
Empty Ollama response on attempt 1/3
Local Ollama cooldown (5m) due to EMPTY_RESPONSE
```

After (actionable):
```
[LLM_GOVERNANCE_HTTP_ERROR] Ollama HTTP 404 | model=qwen3.5:0.8b | URL=http://localhost:11434/api/generate | Body={"error":"not found"}

[LLM_GOVERNANCE_TIMEOUT] Ollama timeout after 60.0s | model=qwen3.5:0.8b | URL=http://localhost:11434/api/generate

[LLM_GOVERNANCE] JSON parse error (model=qwen3.5:0.8b timeout=60.0s): ... | Response: <preview>
```

## 9. Files Modified

```
✅ src/llm_governance.py
   • Timeout: 15.0s → 60.0s
   • Added socket timeout detection
   • Added HTTP error handling
   • Added JSON parse error handling
   • Added keep-alive parameter

✅ src/analysis/llm_macro_monitor.py
   • Timeout: 25.0s/30.0s → 60.0s/45.0s
   • Same improvements as governance layer
   • Consistent error logging format

✅ test_ollama_connectivity.py (NEW)
   • Comprehensive diagnostic tool
   • Validates all Ollama components
   • Shows response times
```

## 10. Next Steps

1. ✅ Code deployed
2. ⏱️ Set environment variables
3. ▶️ Run `test_ollama_connectivity.py`
4. 🚀 Start your bot
5. 📊 Monitor logs for 30 minutes
6. ✓ Enjoy macro-aware trading!

---

**Questions or Issues?**

1. Check logs for detailed error messages
2. Run `test_ollama_connectivity.py` for diagnostics
3. Verify Ollama is running: `curl http://localhost:11434/api/tags`
4. Check if model is installed: `ollama list`

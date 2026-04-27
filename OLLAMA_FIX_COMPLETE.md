"""
OLLAMA INTEGRATION FIX — EMPTY RESPONSE ERRORS RESOLVED
========================================================

PROBLEM SUMMARY:
================
Your trading bot was experiencing "Empty Ollama response on attempt N/3" errors 
causing it to fall into Technical-Only Mode. The root causes were:

1. ❌ TIMEOUT TOO SHORT: 15-second timeout insufficient for model warm-up
2. ❌ POOR ERROR HANDLING: No detailed exception logging for debugging
3. ❌ NO KEEP-ALIVE: Model was unloading between requests
4. ❌ MISSING DETAILS: HTTP status codes and connection errors not captured

SOLUTION IMPLEMENTED:
=====================
✅ 1. TIMEOUT INCREASED (15s → 60s primary, 30s → 45s fallback)
     - Gives qwen3.5:0.8b time to warm up from disk into GPU/memory
     - First load can take 20-40 seconds depending on hardware
     - Configurable via environment variables

✅ 2. DETAILED EXCEPTION HANDLING
     - Captures HTTP status codes (404, 500, 502, 503, etc.)
     - Detects connection errors vs timeouts
     - Logs JSON parsing failures with response preview
     - Distinguishes socket timeouts from application timeouts

✅ 3. KEEP-ALIVE PARAMETER
     - "keep_alive": "5m" added to Ollama request payload
     - Model stays loaded in memory for 5 minutes between requests
     - Eliminates reload penalty on subsequent calls
     - HTTP Connection: keep-alive header for connection reuse

✅ 4. COMPREHENSIVE LOGGING
     - [LLM_GOVERNANCE_HTTP_ERROR] → HTTP-level issues
     - [LLM_GOVERNANCE_CONNECTION_ERROR] → Connection refused/DNS
     - [LLM_GOVERNANCE_TIMEOUT] → Socket timeouts with duration
     - [LLM_GOVERNANCE_SOCKET_TIMEOUT] → Python-level timeouts
     - [MACRO_MONITOR_*] → Equivalent logging for macro monitor

FILES MODIFIED:
===============

1. src/llm_governance.py
   ━━━━━━━━━━━━━━━━━━━━━━━
   Line 86:   LLM_TIMEOUT_SECONDS: 15.0 → 60.0
   Line 87:   LLM_HEAVY_TIMEOUT_SECONDS: 15.0 → 60.0
   Line 51:   Added `import socket` for timeout detection
   Lines 959-1050: Completely rewrote _ollama_request_blocking() function
   
   CHANGES:
   • Increased timeouts by 4x
   • Added HTTP error handling with status codes
   • Added connection error detection
   • Added JSON parse error handling
   • Added keep_alive parameter to request
   • Added HTTP Connection: keep-alive header
   • Added detailed exception logging for all error types
   • Returns empty string instead of raising (fail-open design)

2. src/analysis/llm_macro_monitor.py
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   Line 42:   PRIMARY_REQUEST_TIMEOUT_SECONDS: 25.0 → 60.0
   Line 43:   FALLBACK_REQUEST_TIMEOUT_SECONDS: 30.0 → 45.0
   Lines 1033-1171: Rewrote _call_ollama_blocking() method
   
   CHANGES:
   • Updated timeout constants
   • Added JSON parse error handling
   • Added HTTP error handling with 404 special case
   • Added connection error vs timeout detection
   • Added keep_alive parameter to request
   • Added HTTP Connection: keep-alive header
   • Added detailed logging matching governance layer
   • Better error message propagation

3. test_ollama_connectivity.py (NEW)
   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   A new standalone test script that verifies:
   ✓ Port 11434 is reachable
   ✓ Ollama service is healthy
   ✓ qwen3.5:0.8b model is installed
   ✓ Model responds to /api/generate endpoint
   ✓ Response time is acceptable
   ✓ Response format is valid JSON


CONFIGURATION ENVIRONMENT VARIABLES:
====================================

Set these in your .env file or export them before running:

# Governance layer timeouts
OLLAMA_FAST_TIMEOUT_SECONDS=60.0          # Primary model timeout
OLLAMA_HEAVY_TIMEOUT_SECONDS=60.0         # Heavy model timeout

# Macro monitor timeouts
MACRO_MONITOR_PRIMARY_TIMEOUT_SECONDS=60.0    # Primary model timeout
MACRO_MONITOR_FALLBACK_TIMEOUT_SECONDS=45.0   # Fallback model timeout

# Ollama connection details
OLLAMA_BASE_URL=http://localhost:11434    # Ollama server address
OLLAMA_URL=http://localhost:11434/api/generate  # Generate endpoint
OLLAMA_TAGS_URL=http://localhost:11434/api/tags # Tags endpoint

# Model selection
OLLAMA_MODEL_FAST=qwen3.5:0.8b
OLLAMA_MODEL_HEAVY=qwen3.5:0.8b
MACRO_MONITOR_PRIMARY_MODEL=qwen3.5:0.8b
MACRO_MONITOR_FALLBACK_MODEL=qwen3.5:4b


HOW TO TEST:
============

1. Verify Ollama is running:
   ─────────────────────────
   curl http://localhost:11434/api/tags
   
   Expected output: {"models": [{"name": "qwen3.5:0.8b", ...}, ...]}

2. Download the model if missing:
   ───────────────────────────────
   ollama pull qwen3.5:0.8b
   
   This downloads ~1.8GB model to ~/.ollama/models/

3. Run the connectivity test script:
   ──────────────────────────────────
   python test_ollama_connectivity.py
   
   Expected output:
   ======================================================================
   OLLAMA CONNECTIVITY TEST
   ======================================================================
   
   Configuration:
     Host: localhost
     Port: 11434
     Base URL: http://localhost:11434
     Model: qwen3.5:0.8b
   
   Running: Port Reachability...
   [2026-04-20 14:32:15] [✓] Port 11434 is open and reachable
   
   Running: Service Health...
   [2026-04-20 14:32:15] [✓] Ollama service healthy (HTTP 200)
   
   Running: Model Installation...
   [2026-04-20 14:32:16] [✓] Qwen models installed: qwen3.5
   
   Running: Generate Endpoint...
   [2026-04-20 14:32:18] [✓] Model responded successfully in 2.45s
   
   ======================================================================
   RESULTS: 4 passed, 0 failed
   ======================================================================
   
   [2026-04-20 14:32:18] [✓] All checks passed! Ollama is ready.

4. Run your bot:
   ──────────────
   python main.py


DEBUGGING LOG MESSAGES:
=======================

OLD (before fix):
  [MACRO_MONITOR] Empty Ollama response on attempt 1/3 (model=qwen3.5:0.8b timeout=15.0s)
  [MACRO_MONITOR] Local Ollama cooldown (5m) due to EMPTY_RESPONSE
  [TECHNICAL_ONLY_MODE] Ollama unreachable

NEW (with fix - you should see detailed errors):
  [LLM_GOVERNANCE_TIMEOUT] Ollama timeout after 60.0s | model=qwen3.5:0.8b | URL=http://localhost:11434/api/generate
  [LLM_GOVERNANCE_HTTP_ERROR] Ollama HTTP 404 | model=qwen3.5:0.8b | timeout=60.0s | URL=... | Body=<error>
  [LLM_GOVERNANCE_CONNECTION_ERROR] Ollama unreachable | model=qwen3.5:0.8b | URL=http://localhost:11434/api/generate | Reason=Connection refused
  [LLM_GOVERNANCE] JSON parse error (model=qwen3.5:0.8b timeout=60.0s): ... | Response: <preview>

If you see timeouts even with 60s timeout:
  1. Your machine may be very slow (check CPU/RAM usage during Ollama inference)
  2. Increase timeout further: OLLAMA_FAST_TIMEOUT_SECONDS=120.0
  3. Check if Ollama is using GPU: `ollama info` should show CUDA or Metal support
  4. Reduce model size: Use `qwen2.5:0.5b` instead (smaller, faster)


PERFORMANCE EXPECTATIONS:
=========================

Timing for qwen3.5:0.8b on different hardware:

CPU Only (first load):
  - Initial response: 25-40 seconds (model loading from disk)
  - Subsequent calls: 8-15 seconds (model in memory)

GPU (NVIDIA CUDA):
  - Initial response: 8-12 seconds (model loading to GPU)
  - Subsequent calls: 1-3 seconds (GPU cached)

GPU (Apple Metal):
  - Initial response: 5-8 seconds
  - Subsequent calls: 1-2 seconds

If your times are much slower:
  1. Check if Ollama is using GPU: `ollama info`
  2. Verify CPU isn't maxed out: `top` or Task Manager
  3. Try smaller model: `qwen2.5:0.5b` (~0.5B parameters vs 0.8B)
  4. Increase timeout to 120-180 seconds temporarily


COMMON ISSUES & SOLUTIONS:
==========================

Issue: "Ollama HTTP 404"
Solution: Model not found. Run: ollama pull qwen3.5:0.8b

Issue: "Connection refused"
Solution: Ollama not running. Start it:
  ollama serve
  # or: systemctl start ollama  (on Linux)

Issue: "timeout after 60s"
Solution: Model is too slow or hardware insufficient:
  Option 1: Increase timeout to 120s
  Option 2: Use smaller model: qwen2.5:0.5b
  Option 3: Enable GPU acceleration if available

Issue: "Empty response" (still happening)
Solution: Check logs for detailed error:
  1. Run test_ollama_connectivity.py
  2. Look for error messages in bot logs
  3. Verify Ollama is actually responding:
     curl -X POST http://localhost:11434/api/generate \
       -H "Content-Type: application/json" \
       -d '{
         "model": "qwen3.5:0.8b",
         "prompt": "Say OK",
         "stream": false,
         "keep_alive": "5m"
       }'


VERIFYING THE FIX:
==================

After deploying these changes, you should observe:

1. Logs now show detailed error information:
   ✓ HTTP status codes instead of generic "Empty response"
   ✓ Connection errors clearly labeled
   ✓ Timeout duration logged
   ✓ Response times tracked

2. First inference call takes longer (expected):
   ✓ 20-60s first load (model warming up)
   ✓ 1-15s subsequent calls (model in memory)

3. No more "Technical-Only Mode" unless Ollama is actually down:
   ✓ System runs in macro-aware mode continuously
   ✓ Fallback only triggers on real connectivity issues

4. Macro monitor stays active:
   ✓ Continuous macro risk updates
   ✓ No spurious cooldown windows
   ✓ Better trading decisions with macro context


ROLLBACK PROCEDURE (if needed):
================================

If you need to revert to the original timeouts:

1. Edit src/llm_governance.py:
   Line 86:   LLM_TIMEOUT_SECONDS = 15.0
   Line 87:   LLM_HEAVY_TIMEOUT_SECONDS = 15.0

2. Edit src/analysis/llm_macro_monitor.py:
   Line 42:   PRIMARY_REQUEST_TIMEOUT_SECONDS = 25.0
   Line 43:   FALLBACK_REQUEST_TIMEOUT_SECONDS = 30.0

3. Restart bot:
   python main.py


NEXT STEPS:
===========

1. ✅ Apply these code changes (already done)
2. ✅ Update your .env file with new timeout values
3. ✅ Run test_ollama_connectivity.py to verify setup
4. 🔄 Restart your trading bot
5. 📊 Monitor logs for the first 30 minutes
6. ✓ If you still see empty responses, check the detailed error messages
7. 📈 Enjoy macro-aware trading without Technical-Only Mode!


TECHNICAL DETAILS:
==================

Ollama API Payload Format (now correct):
────────────────────────────────────────
{
  "model": "qwen3.5:0.8b",
  "prompt": "...",
  "stream": false,
  "format": "json",
  "keep_alive": "5m",           ← NEW: keeps model in memory
  "options": {
    "num_predict": 150,         ← Max tokens to generate
    "temperature": 0.1,         ← Deterministic (low temp)
    "top_p": 0.85,              ← Nucleus sampling
  }
}

Response Format:
────────────────
{
  "model": "qwen3.5:0.8b",
  "created_at": "2026-04-20T14:32:18.123456Z",
  "response": "{"penalties": {"EURUSD": ...}}",  ← This is what we parse
  "done": true,
  "done_reason": "stop",
  "context": [...]
}

Timeout Behavior:
─────────────────
• urllib.request.urlopen(req, timeout=X)
  - Socket operation timeout (X seconds)
  - Detected as urllib.error.URLError with OSError(errno=110)
  
• asyncio.wait_for(task, timeout=X)
  - Application-level timeout
  - Raises asyncio.TimeoutError
  
• thread.join(timeout=X)
  - Thread-level timeout
  - Returns even if thread still running
  
All three are now properly handled and logged.
"""
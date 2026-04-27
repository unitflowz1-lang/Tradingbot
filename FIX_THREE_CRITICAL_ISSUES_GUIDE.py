"""
THREE CRITICAL FIXES: Disable Old News Scraper, Fix LLM Timeout, Update Model Config

Issues to fix:
1. Old NEWS_FETCH still running - disable NewsCollector, use Finnhub
2. LLM timeout at 3011ms - implement SNIPPET_6 properly with minified JSON
3. Model error - update from nemotron-3-nano:4b to qwen3.5:0.8b
"""

print("""
╔════════════════════════════════════════════════════════════════════════════════╗
║              THREE CRITICAL FIXES: NEWS SCRAPER, LLM TIMEOUT, MODEL            ║
╚════════════════════════════════════════════════════════════════════════════════╝

════════════════════════════════════════════════════════════════════════════════
ISSUE #1: Old News Scraper Still Running
════════════════════════════════════════════════════════════════════════════════

SYMPTOM:
  Logs show: ERROR | [NEWS_FETCH] No live news articles matched for EUR/USD
  Bot is stuck with OLD NewsCollector that fails to fetch articles

ROOT CAUSE:
  1. news_collector is still initialized and called in main loop
  2. get_cached_news() function still tries to fetch from old API
  3. news_collector is passed to macro_monitor
  4. FinnhubMacroManager hasn't been fully integrated yet

FIXES NEEDED:
  1. Replace get_cached_news() calls with Finnhub data
  2. Disable old news_collector.collect_data() calls
  3. Point MACRO_RISK_AUDIT to finnhub_manager.get_macro_score()
  4. Update macro_monitor initialization to remove news_collector

════════════════════════════════════════════════════════════════════════════════
ISSUE #2: LLM Timeout at 3011ms
════════════════════════════════════════════════════════════════════════════════

SYMPTOM:
  Logs show: [LLM_GOVERNANCE] Processing took 3011ms
  Target is <1000ms - currently 3x too slow
  LLM is processing raw macro text instead of minified JSON

ROOT CAUSE:
  1. SNIPPET_6 not implemented - LLM not receiving minified JSON from Finnhub
  2. Old macro data format still being sent (large text blobs)
  3. LLM has to parse unstructured text instead of structured JSON
  4. Latest system prompt update is in place but not being used

FIXES NEEDED:
  1. Verify FinnhubMacroManager is initialized and running
  2. Implement SNIPPET_6 in the LLM governance input builder
  3. Add get_llm_payload_json() call to minify Finnhub data
  4. Wait 1-2 minutes for background task to populate cache before measuring

════════════════════════════════════════════════════════════════════════════════
ISSUE #3: Model Not Found Error
════════════════════════════════════════════════════════════════════════════════

SYMPTOM:
  Logs show: CRITICAL | [MACRO_MONITOR] nemotron-3-nano:4b model not found
  Bot fails to start the macro monitor

ROOT CAUSE:
  main.py line 1617 has hardcoded default: "nemotron-3-nano:4b"
  Config has correct model: MACRO_MONITOR_PRIMARY_MODEL=qwen3.5:0.8b
  But environment variable isn't being read (wrong name being used)

FIX NEEDED:
  Change line 1617 from:
    model=os.environ.get("MACRO_MONITOR_MODEL", "nemotron-3-nano:4b")
  To:
    model=os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b")

════════════════════════════════════════════════════════════════════════════════
COMPREHENSIVE FIXES (Applied in Order)
════════════════════════════════════════════════════════════════════════════════

✅ FIX #1: Update Macro Monitor Model (Line 1617)
   
   OLD:  model=os.environ.get("MACRO_MONITOR_MODEL", "nemotron-3-nano:4b"),
   NEW:  model=os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b"),
   
   Why: Uses correct env var and model that's already installed

✅ FIX #2: Initialize FinnhubMacroManager After Macro Monitor (Phase 4b)
   
   Add this right after macro_health_monitor.start():
   
   # Phase 4b: Initialize Finnhub Macro Manager (Non-blocking background task)
   finnhub_manager = None
   try:
       api_key = os.environ.get("FINNHUB_API_KEY")
       if api_key and str(api_key).strip():
           from src.analysis.finnhub_macro_manager import FinnhubMacroManager
           finnhub_manager = FinnhubMacroManager(
               api_key=api_key,
               symbols=symbols,
               macro_risk_cache=macro_risk_cache,
               enable_economic_calendar=True,
               enable_sentiment_analysis=True,
           )
           await finnhub_manager.start()
           logger.critical(
               "[FINNHUB_MANAGER_INIT] ✅ Started | Background refresh: 5 min | "
               "Main pulse impact: 0ms (cache reads only)"
           )
       else:
           logger.warning("[FINNHUB_MANAGER_INIT] API key not configured")
           finnhub_manager = None
   except Exception as e:
       logger.error("[FINNHUB_STARTUP_ERROR] %s | Proceeding without Finnhub", str(e)[:100])
       finnhub_manager = None

✅ FIX #3: Disable Old News Collector Calls (Throughout Main Loop)
   
   Find all calls to:  get_cached_news(symbol, ...)
   Comment out or replace with:
   
   # OLD: news = await get_cached_news(symbol, "1h")
   # NEW: Get macro context from Finnhub instead
   
   Example: Search for all "await get_cached_news" and replace with pass or skip

✅ FIX #4: Remove news_collector from Macro Monitor (Still Line 1619)
   
   OLD:
   macro_monitor = AsyncLLMMacroMonitor(
       symbols=symbols,
       interval_seconds=...,
       model=...,
       context_provider=lambda: latest_context,
       news_collector=news_collector,  # ← REMOVE THIS LINE
   )
   
   NEW:
   macro_monitor = AsyncLLMMacroMonitor(
       symbols=symbols,
       interval_seconds=...,
       model=...,
       context_provider=lambda: latest_context,
       # news_collector removed - using Finnhub instead
   )

✅ FIX #5: Implement SNIPPET_6 (LLM Input with Minified Finnhub JSON)
   
   Find: Where LLM governance input is built (around line 6340 advisory_input creation)
   
   Add Finnhub macro data to the LLM input:
   
   # Build advisory input for LLM
   advisory_input = GovernanceInput(
       symbol=symbol,
       regime=regime,
       rsi=float(rsi_val),
       ... other fields ...
   )
   
   # ADD THIS: Include minified Finnhub macro data
   if finnhub_manager:
       try:
           snapshot = finnhub_manager.get_latest_snapshot(symbol)
           # Build minified macro JSON for LLM
           advisory_input.macro_context = {
               "risk_score": snapshot.risk_score,
               "risk_reason": snapshot.risk_reason,
               "has_event": snapshot.has_high_impact_event,
               "event_minutes": snapshot.event_minutes_until_high_impact,
               "sentiment": snapshot.sentiment_score,
               "volatility": snapshot.expected_volatility,
           }
       except Exception as e:
           logger.debug("[LLM_MACRO] Could not add Finnhub: %s", str(e)[:50])
   
   Then call LLM:
   advisory_outcome = runtime_ai_advisory.evaluate(
       advisory_input=advisory_input,
       cycle=cycle_count,
       signal_forced=bool(getattr(signal, 'forced_execution', False)),
   )

════════════════════════════════════════════════════════════════════════════════
IMPLEMENTATION CODE (Ready to Copy-Paste)
════════════════════════════════════════════════════════════════════════════════

See file: FIX_THREE_CRITICAL_ISSUES_CODE_TEMPLATE.py
""")

# Code templates for each fix
FIXES = {
    "FIX_1_MODEL": """
# Fix 1: Line 1617 in main.py
# BEFORE:
#   model=os.environ.get("MACRO_MONITOR_MODEL", "nemotron-3-nano:4b"),

# AFTER:
model=os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b"),
""",
    
    "FIX_2_FINNHUB_INIT": """
# Fix 2: Add after macro_health_monitor.start() (around line 1630)

# Phase 4b: Initialize Finnhub Macro Manager (Non-blocking background task)
finnhub_manager = None
try:
    api_key = os.environ.get("FINNHUB_API_KEY")
    if api_key and str(api_key).strip():
        from src.analysis.finnhub_macro_manager import FinnhubMacroManager
        finnhub_manager = FinnhubMacroManager(
            api_key=api_key,
            symbols=symbols,
            macro_risk_cache=macro_risk_cache,
            enable_economic_calendar=True,
            enable_sentiment_analysis=True,
        )
        await finnhub_manager.start()
        logger.critical(
            "[FINNHUB_MANAGER_INIT] ✅ Started | Background refresh: 5 min | "
            "Main pulse impact: 0ms (cache reads only)"
        )
    else:
        logger.warning("[FINNHUB_MANAGER_INIT] API key not configured")
        finnhub_manager = None
except Exception as e:
    logger.error("[FINNHUB_STARTUP_ERROR] %s | Proceeding without Finnhub", str(e)[:100])
    finnhub_manager = None
""",
    
    "FIX_3_NEWS_DISABLE": """
# Fix 3: Comment out news_collector calls

# OLD CODE (comment out):
# fetched = await news_collector.collect_data([symbol], timeframe=timeframe)
# symbol_news = fetched.get(symbol, []) if isinstance(fetched, dict) else []

# NEW CODE (replace with):
# Skip old news collector - using Finnhub for macro context instead
symbol_news = []  # Empty - Finnhub provides macro sentiment
""",
    
    "FIX_4_MACRO_MONITOR": """
# Fix 4: Line 1615-1620 in main.py
# BEFORE:

macro_monitor = AsyncLLMMacroMonitor(
    symbols=symbols,
    interval_seconds=int(os.environ.get("MACRO_MONITOR_INTERVAL_SECONDS", "900")),
    model=os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b"),
    context_provider=lambda: latest_context,
    news_collector=news_collector,  # ← REMOVE THIS
)

# AFTER:

macro_monitor = AsyncLLMMacroMonitor(
    symbols=symbols,
    interval_seconds=int(os.environ.get("MACRO_MONITOR_INTERVAL_SECONDS", "900")),
    model=os.environ.get("MACRO_MONITOR_PRIMARY_MODEL", "qwen3.5:0.8b"),
    context_provider=lambda: latest_context,
    # NEWS_COLLECTOR REMOVED - Using Finnhub instead
)
""",
    
    "FIX_5_LLM_INPUT": """
# Fix 5: Around line 6340 where advisory_input is created
# Add Finnhub macro data to LLM input BEFORE advisory_outcome = runtime_ai_advisory.evaluate()

# Build advisory input
advisory_input = GovernanceInput(
    symbol=symbol,
    regime=regime,
    rsi=float(rsi_val),
    adx=float(adx_val),
    atr=float(atr_mean) if 'atr_mean' in dir() else 0.0,
    rr_ratio=float(_gov_rr),
    ml_confidence=float(ml_conf if 'ml_conf' in dir() else getattr(signal, 'ml_confidence', 0.5)),
    volatility_pct=float(current_volatility),
    forced_execution=bool(getattr(signal, 'forced_execution', False)),
    position_size=float(final_lots),
    expectancy_multiplier=float(_gov_rr),
)

# ADD THIS: Include minified Finnhub macro data (SNIPPET_6)
if finnhub_manager:
    try:
        snapshot = finnhub_manager.get_latest_snapshot(symbol)
        # Build minified macro context for LLM
        macro_dict = {
            "risk_score": round(snapshot.risk_score, 1),
            "risk_reason": snapshot.risk_reason,
            "has_event": snapshot.has_high_impact_event,
            "event_minutes": snapshot.event_minutes_until_high_impact,
            "sentiment": round(snapshot.sentiment_score, 2) if snapshot.sentiment_score else 0.0,
            "volatility": snapshot.expected_volatility,
        }
        # Add to advisory input
        if hasattr(advisory_input, 'macro'):
            advisory_input.macro = macro_dict
        logger.debug("[LLM_MACRO] Finnhub context: risk=%.1f, sentiment=%.2f", 
                     macro_dict.get("risk_score", 0), macro_dict.get("sentiment", 0))
    except Exception as e:
        logger.debug("[LLM_MACRO_ERROR] %s", str(e)[:50])

# Now evaluate with LLM
advisory_outcome = runtime_ai_advisory.evaluate(
    advisory_input=advisory_input,
    cycle=cycle_count,
    signal_forced=bool(getattr(signal, 'forced_execution', False)),
)
""",
    
    "FIX_6_SHUTDOWN": """
# Fix 6: Add before bot shutdown (in finally block around line 7400+)

# Shutdown Finnhub manager
if finnhub_manager:
    try:
        await finnhub_manager.stop()
        logger.info("[SHUTDOWN] Finnhub manager stopped gracefully")
    except Exception as e:
        logger.warning("[SHUTDOWN] Finnhub stop error: %s", str(e)[:50])
"""
}

if __name__ == "__main__":
    for fix_name, fix_code in FIXES.items():
        print(f"\n{fix_name}:")
        print(fix_code)

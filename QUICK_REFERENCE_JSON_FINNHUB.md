"""
QUICK REFERENCE CARD - JSON & Finnhub Fixes
═══════════════════════════════════════════════════════════════════════════════

This is a quick lookup reference for the most common tasks and questions.

═══════════════════════════════════════════════════════════════════════════════
FILES AT A GLANCE
═══════════════════════════════════════════════════════════════════════════════

NEW FILES CREATED:
├─ src/utils/json_utils.py
│  └─ Robust JSON loading/saving with auto-recovery
├─ src/analysis/FINNHUB_NEWS_FETCHING_REFACTORED.py
│  └─ Enhanced Finnhub news fetching with fallback strategy
├─ test_finnhub.py
│  └─ Standalone verification script
│
DOCUMENTATION:
├─ FIX_SUMMARY_JSON_FINNHUB.md (this is the summary, read first!)
├─ INTEGRATION_GUIDE_JSON_FINNHUB_FIXES.md (detailed integration guide)
├─ CODE_EXAMPLES_JSON_FINNHUB_FIXES.md (copy-paste code snippets)
└─ QUICK_REFERENCE_JSON_FINNHUB.md (this file)

═══════════════════════════════════════════════════════════════════════════════
ISSUE 1: JSON CACHE ERRORS
═══════════════════════════════════════════════════════════════════════════════

PROBLEM:
    ERROR | Failed to load state: Expecting value: line 1 column 1 (char 0)
    WARNING | [MACRO_MONITOR] Failed to load cache: ...

FIX:
    from src.utils.json_utils import safe_json_load
    
    data = safe_json_load("file.json", default={})

PLACES TO UPDATE:
    1. src/trading/position_manager.py - Line ~540 - _load_shadow_state()
    2. src/analysis/llm_macro_monitor.py - Line ~60 - MacroRiskCache._load_from_disk()
    3. src/trading/state_sync_manager.py - Line ~188 - JSON registry loading

EXPECTED RESULT:
    ✅ No more "Expecting value" errors
    ✅ Corrupted files auto-recovered
    ✅ Warnings instead of errors

═══════════════════════════════════════════════════════════════════════════════
ISSUE 2: FINNHUB NEWS ERRORS
═══════════════════════════════════════════════════════════════════════════════

PROBLEM:
    ERROR | Error fetching news data for EUR/USD: No live news articles matched
    WARNING | [NEWS_SILENT_FAILOVER] EUR/USD | Falling back to technical-only

FIX:
    await fetch_and_process_news_sentiment_refactored(manager)

PLACES TO UPDATE:
    1. src/analysis/finnhub_macro_manager.py - Line ~700
       - Replace _fetch_and_process_news_sentiment() method

IMPROVEMENTS:
    ✅ 48-hour lookback (was 1 hour)
    ✅ Multi-level fallback strategy
    ✅ Graceful empty state (quiet market, not error)
    ✅ Better sentiment accuracy

EXPECTED RESULT:
    • More articles found
    • Fewer "no results" failures
    • Sentiment scores 0.0-1.0 calculated
    • No ERROR logs for quiet markets

═══════════════════════════════════════════════════════════════════════════════
QUICK INSTALL
═══════════════════════════════════════════════════════════════════════════════

STEP 1: Copy files
    src/utils/json_utils.py              (NEW)
    src/analysis/FINNHUB_NEWS_FETCHING_REFACTORED.py   (NEW)
    test_finnhub.py                      (NEW)

STEP 2: Test Finnhub
    export FINNHUB_API_KEY="your_api_key"
    python test_finnhub.py

    Expected: ✅ PASS for all tests

STEP 3: Update code files
    See CODE_EXAMPLES_JSON_FINNHUB_FIXES.md for exact changes

STEP 4: Restart bot
    python main_bot.py
    
    Monitor for [JSON_UTILS] and [NEWS_FETCH] in logs

═══════════════════════════════════════════════════════════════════════════════
MOST COMMON OPERATIONS
═══════════════════════════════════════════════════════════════════════════════

Load a JSON file with auto-recovery:
    from src.utils.json_utils import safe_json_load
    data = safe_json_load("file.json", default={})

Load a list JSON file:
    from src.utils.json_utils import safe_json_load_list
    items = safe_json_load_list("list.json", default=[])

Save JSON safely:
    from src.utils.json_utils import safe_json_write
    safe_json_write("file.json", data, indent=2)

Test Finnhub news fetching:
    python test_finnhub.py EUR/USD GBP/USD
    
    Or with custom API key:
    export FINNHUB_API_KEY="key"
    python test_finnhub.py

═══════════════════════════════════════════════════════════════════════════════
ERROR DIAGNOSIS
═══════════════════════════════════════════════════════════════════════════════

ERROR: "ModuleNotFoundError: No module named 'src.utils.json_utils'"
FIX:   Ensure src/utils/json_utils.py exists in your workspace

ERROR: "aiohttp not installed" in test_finnhub.py
FIX:   pip install aiohttp

ERROR: "401 Unauthorized" when running test_finnhub.py
FIX:   Check your API key: export FINNHUB_API_KEY="your_correct_key"

ERROR: "Still seeing JSON decode errors in logs"
FIX:   Make sure you updated ALL locations (see INTEGRATION_GUIDE)
      Search codebase for "json.load" to find all occurrences

ERROR: "Sentiment score 0.0 for all pairs"
FIX:   Verify import: from FINNHUB_NEWS_FETCHING_REFACTORED import ...
      Check logs for [FINNHUB_NEWS_ERROR] messages

═══════════════════════════════════════════════════════════════════════════════
LOG MONITORING
═══════════════════════════════════════════════════════════════════════════════

Look for these in logs to verify fixes are working:

AFTER FIX 1 (JSON):
    [JSON_UTILS] Successfully loaded data/state.json
    [JSON_UTILS] Empty JSON file detected: ... Reinitializing...
    [JSON_UTILS] JSON decode error in ...: ... Reinitializing...
    
    (Should NOT see):
    ERROR | Expecting value: line 1 column 1

AFTER FIX 2 (FINNHUB):
    [NEWS_FETCH] Fetching news for EUR/USD | Base: EUR, Quote: USD
    [NEWS_FETCH] ✅ Fetched N articles for EUR/USD | Sentiment: 0.XX
    [NEWS_FETCH] No articles found for EUR/USD (quiet market)
    
    (Should NOT see):
    ERROR | No live news articles matched
    WARNING | [NEWS_SILENT_FAILOVER]

═══════════════════════════════════════════════════════════════════════════════
TESTING CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

□ Run test_finnhub.py and get ✅ for all tests
□ Restart bot and check for [JSON_UTILS] debug messages
□ Verify no "Expecting value" errors in startup logs
□ Check sentiment scores in logs (should be 0.0-1.0, not 0.0 always)
□ Monitor bot for 30+ minutes without JSON/Finnhub errors
□ Verify macro risk penalties are being applied (check [MACRO_MONITOR] logs)
□ Check that quiet markets don't produce ERROR logs

═══════════════════════════════════════════════════════════════════════════════
ROLLBACK PLAN (if needed)
═══════════════════════════════════════════════════════════════════════════════

If something goes wrong during deployment:

1. Revert code changes (git checkout or manual undo)
2. Remove new files (src/utils/json_utils.py, FINNHUB_NEWS_FETCHING_REFACTORED.py)
3. Restart bot
4. Investigate issue in INTEGRATION_GUIDE_JSON_FINNHUB_FIXES.md troubleshooting

The bot will continue to function with original (less robust) implementations.

═══════════════════════════════════════════════════════════════════════════════
CONTACTS & SUPPORT
═══════════════════════════════════════════════════════════════════════════════

For detailed information, see:
    • FIX_SUMMARY_JSON_FINNHUB.md - Overview of all fixes
    • INTEGRATION_GUIDE_JSON_FINNHUB_FIXES.md - Detailed integration steps
    • CODE_EXAMPLES_JSON_FINNHUB_FIXES.md - Copy-paste code snippets
    • QUICK_REFERENCE_JSON_FINNHUB.md - This file

For code questions:
    • src/utils/json_utils.py - Comprehensive docstrings
    • src/analysis/FINNHUB_NEWS_FETCHING_REFACTORED.py - Full documentation

For testing:
    • test_finnhub.py - Run with --help for options
    • See CODE_EXAMPLES for unit test code

═══════════════════════════════════════════════════════════════════════════════
"""

__all__ = []

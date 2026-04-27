"""
INTEGRATION GUIDE - JSON Cache & Finnhub News Fixes

This document explains how to integrate the two fixes into your existing code.

═══════════════════════════════════════════════════════════════════════════════
ISSUE 1: INTEGRATING JSON UTILITY FUNCTION
═══════════════════════════════════════════════════════════════════════════════

The safe_json_load() utility should be used throughout your codebase wherever
JSON files are loaded. Here are the key locations:

LOCATION 1: src/trading/position_manager.py - _load_shadow_state()
─────────────────────────────────────────────────────────────────────────────
BEFORE (current code):
    try:
        with open(self.SHADOW_STATE_FILE, 'r', encoding='utf-8') as f:
            raw_text = f.read()
            if not raw_text.strip():
                data = {}
                with open(self.SHADOW_STATE_FILE, 'w', encoding='utf-8') as reset_file:
                    reset_file.write("{}")
                self.logger.warning("[SHADOW-STATE-RESET] Empty shadow state file...")
            else:
                data = json.loads(raw_text)
    except Exception as e:
        self.logger.error(f"Failed to load shadow state (JSON corrupted?): {e}")
        self.shadow_positions = {}

AFTER (with fix):
    from src.utils.json_utils import safe_json_load
    
    data = safe_json_load(
        self.SHADOW_STATE_FILE,
        default={"shadow_positions": {}},
        auto_recover=True,
    )
    raw_shadow = data.get('shadow_positions', {})
    self.shadow_positions = self._deserialize_shadow_types(raw_shadow)


LOCATION 2: src/analysis/llm_macro_monitor.py - MacroRiskCache._load_from_disk()
─────────────────────────────────────────────────────────────────────────────
BEFORE (current code):
    def _load_from_disk(self) -> None:
        try:
            if not os.path.exists(self.cache_path):
                return
            with open(self.cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            penalties = payload.get("penalties", {}) if isinstance(payload, dict) else {}
            ...
        except json.JSONDecodeError:
            # Silently handle corrupted cache
            return

AFTER (with fix):
    from src.utils.json_utils import safe_json_load
    
    def _load_from_disk(self) -> None:
        payload = safe_json_load(
            self.cache_path,
            default={"penalties": {}, "reasons": {}},
            auto_recover=True,
        )
        penalties = payload.get("penalties", {}) if isinstance(payload, dict) else {}
        reasons = payload.get("reasons", {}) if isinstance(payload, dict) else {}
        ...


LOCATION 3: src/trading/state_sync_manager.py - Any JSON file operations
─────────────────────────────────────────────────────────────────────────────
BEFORE:
    if os.path.exists(registry_path):
        with open(registry_path, "r", encoding="utf-8") as handle:
            registry = json.load(handle)

AFTER (with fix):
    from src.utils.json_utils import safe_json_load
    
    registry = safe_json_load(registry_path, default={}, auto_recover=True)


USAGE PATTERN:
    from src.utils.json_utils import safe_json_load, safe_json_write
    
    # Load with automatic recovery
    data = safe_json_load("path/to/file.json", default={})
    
    # Load a list file
    from src.utils.json_utils import safe_json_load_list
    items = safe_json_load_list("path/to/list.json", default=[])
    
    # Write safely
    safe_json_write("path/to/file.json", data, indent=2)


═══════════════════════════════════════════════════════════════════════════════
ISSUE 2: INTEGRATING FINNHUB NEWS IMPROVEMENTS
═══════════════════════════════════════════════════════════════════════════════

The refactored news fetching module should be integrated into
src/analysis/finnhub_macro_manager.py

INTEGRATION STEPS:

1. Import the refactored module at the top of finnhub_macro_manager.py:

    from FINNHUB_NEWS_FETCHING_REFACTORED import (
        fetch_news_with_fallback_and_cleanup,
        fetch_and_process_news_sentiment_refactored,
        NewsResult,
    )

2. In the FinnhubMacroManager class, replace or enhance the
   _fetch_and_process_news_sentiment method to use the refactored version:

BEFORE (current code):
    async def _fetch_and_process_news_sentiment(self) -> None:
        """Fetch market news and sentiment from Finnhub."""
        if not self.enable_sentiment_analysis:
            return

        try:
            url = f"{FINNHUB_NEWS_ENDPOINT}?category=forex&limit=3&token={self.api_key}"
            data = await self._rate_limited_call(url, timeout_seconds=30.0)
            # ... more code ...

AFTER (with fix):
    async def _fetch_and_process_news_sentiment(self) -> None:
        """
        Fetch market news and sentiment from Finnhub with enhanced fallback strategy.
        
        IMPROVEMENTS:
        1. Broadened Search: Splits symbol pairs (AUD/USD → searches AUD OR USD)
        2. General Forex Fallback: Falls back to general 'forex' category
        3. Extended Lookback: Searches 24+ hours of articles
        4. Graceful Empty Handling: Returns neutral sentiment instead of error
        """
        if not self.enable_sentiment_analysis:
            return

        try:
            # Use refactored news fetching with all enhancements
            await fetch_and_process_news_sentiment_refactored(self)

        except Exception as e:
            logger.warning(
                "[FINNHUB_NEWS_ERROR] Failed to fetch news/sentiment: %s",
                str(e)[:100],
            )
            raise


KEY IMPROVEMENTS EXPLAINED:

1. TIMEFRAME EXPANSION (1h → 48h):
   - OLD: Only searched recent news (implicit 1h window)
   - NEW: NEWS_LOOKBACK_HOURS = 48 (searches 2 full days of articles)
   - BENEFIT: Much broader coverage of macro events affecting currencies

2. QUERY FALLBACK STRATEGY:
   - Level 1: Search for specific currencies (EUR, USD separately)
   - Level 2: Filter by relevance to currency pair
   - Level 3: Fall back to general /news?category=forex
   - Level 4: Calculate neutral sentiment if no articles (quiet market)
   - BENEFIT: Multiple pathways to find relevant news

3. GRACEFUL EMPTY STATE:
   - OLD: Returned error if no articles found
   - NEW: Returns neutral sentiment (0.5) for quiet market
   - BENEFIT: No more ERROR logs for normal quiet market conditions

4. SENTIMENT EXTRACTION:
   - Keyword-based analysis specific to forex news
   - Recognizes bullish terms: "rally", "surge", "hawkish", "rate hike"
   - Recognizes bearish terms: "decline", "dovish", "rate cut", "recession"
   - Returns score 0.0-1.0 (0=very bearish, 1=very bullish)

5. CURRENCY-SPECIFIC FILTERING:
   - Automatically maps EUR/USD → searches both EUR and USD news
   - Filters results for relevance (not just any forex news)
   - Recognizes currency-specific keywords and central bank names


═══════════════════════════════════════════════════════════════════════════════
TESTING THE INTEGRATION
═══════════════════════════════════════════════════════════════════════════════

1. TEST JSON UTILS:
   python -c "
   from src.utils.json_utils import safe_json_load
   data = safe_json_load('data/test.json', default={'test': True})
   print('✅ JSON utils working:', data)
   "

2. TEST FINNHUB WITH STANDALONE SCRIPT:
   export FINNHUB_API_KEY="your_api_key_here"
   python test_finnhub.py EUR/USD GBP/USD USD/JPY
   
   Expected output:
   ✅ API connectivity OK
   ✅ Specific currency queries return articles
   ✅ General forex fallback works
   ✅ Refactored news fetching works
   ✅ Empty results handled gracefully

3. ENABLE DEBUG LOGGING IN BOT:
   At startup, set logging level to DEBUG in main bot code:
   
   logging.getLogger("src.analysis.finnhub_macro_manager").setLevel(logging.DEBUG)
   logging.getLogger("src.utils.json_utils").setLevel(logging.DEBUG)
   
   Then watch logs for:
   - [JSON_UTILS] messages (file operations)
   - [NEWS_FETCH] messages (API queries)
   - [FINNHUB_NEWS] messages (sentiment calculation)


═══════════════════════════════════════════════════════════════════════════════
EXPECTED LOG OUTPUT AFTER FIX
═══════════════════════════════════════════════════════════════════════════════

ISSUE 1 FIX (JSON CACHE):
BEFORE:
    ERROR | Failed to load state: Expecting value: line 1 column 1 (char 0)
    WARNING | [MACRO_MONITOR] Failed to load cache: Expecting value: line 1 column 1 (char 0)

AFTER:
    WARNING | [JSON_UTILS] Empty JSON file detected: data/state.json. Reinitializing...
    DEBUG | [JSON_UTILS] Successfully loaded data/macro_risk_cache.json (5 keys)
    (No more ERROR logs for JSON file loading)


ISSUE 2 FIX (FINNHUB NEWS):
BEFORE:
    ERROR | Error fetching news data for EUR/USD: No live news articles matched
    WARNING | [NEWS_SILENT_FAILOVER] EUR/USD | Falling back to technical-only mode

AFTER:
    INFO | [NEWS_FETCH] Fetching news for EUR/USD | Base: EUR, Quote: USD | Lookback: 48h
    DEBUG | [NEWS_FETCH] Got 8 articles for EUR
    DEBUG | [NEWS_FETCH] Got 5 articles for USD
    DEBUG | [NEWS_FETCH] Filtered to 6 relevant articles
    INFO | [NEWS_FETCH] ✅ Fetched 5 articles for EUR/USD | Sentiment: 0.62 | Source: specific_query
    
    (If no specific articles found:)
    INFO | [NEWS_FETCH] No relevant articles found. Falling back to general forex category
    INFO | [NEWS_FETCH] ✅ Fetched 3 articles for EUR/USD | Sentiment: 0.52 | Source: general_forex
    
    (If truly no news:)
    INFO | [NEWS_FETCH] No articles found for EUR/USD (quiet market). Returning neutral sentiment (0.5)


═══════════════════════════════════════════════════════════════════════════════
DEPLOYMENT CHECKLIST
═══════════════════════════════════════════════════════════════════════════════

□ 1. Create src/utils/json_utils.py (provided)
□ 2. Create src/analysis/FINNHUB_NEWS_FETCHING_REFACTORED.py (provided)
□ 3. Update position_manager.py to import and use safe_json_load
□ 4. Update llm_macro_monitor.py to use safe_json_load
□ 5. Update state_sync_manager.py to use safe_json_load
□ 6. Update finnhub_macro_manager.py to use refactored news fetching
□ 7. Run test_finnhub.py to verify Finnhub integration
□ 8. Deploy to production bot
□ 9. Monitor logs for [JSON_UTILS] and [NEWS_FETCH] messages
□ 10. Verify no more JSON decode errors on startup
□ 11. Verify sentiment scores are calculated for quiet markets (no errors)


═══════════════════════════════════════════════════════════════════════════════
TROUBLESHOOTING
═══════════════════════════════════════════════════════════════════════════════

Q: "ModuleNotFoundError: No module named 'src.utils.json_utils'"
A: Ensure the src/utils/ directory exists. Create it if needed:
   mkdir -p src/utils
   touch src/utils/__init__.py

Q: "test_finnhub.py fails with aiohttp not installed"
A: Install aiohttp: pip install aiohttp

Q: "test_finnhub.py returns 401 Unauthorized"
A: Check your API key. Ensure FINNHUB_API_KEY env var is set correctly.

Q: "Still seeing JSON decode errors in logs"
A: Make sure you've updated ALL locations where json.load() is used:
   - position_manager.py: _load_shadow_state()
   - llm_macro_monitor.py: MacroRiskCache._load_from_disk()
   - state_sync_manager.py: Any JSON loading
   
   Search your codebase for "json.load" to find all occurrences.

Q: "Sentiment score still 0.0 for all pairs"
A: Verify the refactored news module is imported correctly in finnhub_macro_manager.py:
   from FINNHUB_NEWS_FETCHING_REFACTORED import fetch_and_process_news_sentiment_refactored
   
   Check logs for [FINNHUB_NEWS_ERROR] messages.

═══════════════════════════════════════════════════════════════════════════════
"""

__all__ = []

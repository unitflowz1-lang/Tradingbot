"""
PRACTICAL CODE EXAMPLES - JSON & Finnhub Integration

This file contains copy-paste ready code snippets for integrating the fixes.

═══════════════════════════════════════════════════════════════════════════════
FIX 1A: Update position_manager.py - _load_shadow_state() method
═══════════════════════════════════════════════════════════════════════════════

LOCATION: src/trading/position_manager.py, around line 540

ADD THIS AT TOP OF FILE (if not already there):
─────────────────────────────────────────────────────────────────────────────
    from src.utils.json_utils import safe_json_load, safe_json_write

THEN REPLACE THE ENTIRE _load_shadow_state() method with:
─────────────────────────────────────────────────────────────────────────────

    def _load_shadow_state(self) -> None:
        \"\"\"Load shadow positions from dedicated persistence file\"\"\"
        if self._shadow_state_loaded_once:
            self.logger.debug("[SHADOW-STATE-SKIP] Shadow state already loaded once during initialization.")
            return

        # FIX: Use robust safe_json_load utility
        # This handles empty files, corrupted JSON, and auto-recovers
        data = safe_json_load(
            file_path=self.SHADOW_STATE_FILE,
            default={"shadow_positions": {}},
            auto_recover=True,
        )
        
        raw_shadow = data.get('shadow_positions', {})
        self.shadow_positions = self._deserialize_shadow_types(raw_shadow)
        
        if self.shadow_positions:
            self.logger.critical(
                f"[SHADOW-STATE-LOADED] Recovered {len(self.shadow_positions)} shadow positions from disk. "
                f"Memory persistence verified."
            )
        
        # Purge obsolete shadow positions
        self._purge_obsolete_shadow_positions()
        
        # Hard one-time guard: runtime loops must never trigger repeated disk loads.
        self._shadow_state_loaded_once = True

═══════════════════════════════════════════════════════════════════════════════
FIX 1B: Update llm_macro_monitor.py - MacroRiskCache._load_from_disk() method
═══════════════════════════════════════════════════════════════════════════════

LOCATION: src/analysis/llm_macro_monitor.py, around line 46-80

ADD THIS AT TOP OF CLASS:
─────────────────────────────────────────────────────────────────────────────
    from src.utils.json_utils import safe_json_load

THEN REPLACE THE _load_from_disk() method with:
─────────────────────────────────────────────────────────────────────────────

    def _load_from_disk(self) -> None:
        \"\"\"Load macro risk cache from disk with robust error handling.\"\"\"
        
        # FIX: Use safe_json_load instead of raw json.load()
        payload = safe_json_load(
            file_path=self.cache_path,
            default={"penalties": {}, "reasons": {}},
            auto_recover=True,
        )
        
        # Extract fields with fallback to empty dicts
        penalties = payload.get("penalties", {}) if isinstance(payload, dict) else {}
        reasons = payload.get("reasons", {}) if isinstance(payload, dict) else {}
        
        with self._lock:
            self._penalties = {
                _normalize_symbol(k): float(max(0.0, min(0.4, v)))
                for k, v in penalties.items()
                if isinstance(v, (int, float))
            }
            self._reasons = {
                _normalize_symbol(k): str(v)[:200]
                for k, v in reasons.items()
            }
            self._updated_at = payload.get("_updated_at")
            self._source = "disk"
            
            if self._penalties:
                logger.info(
                    f"[MACRO_CACHE_LOADED] {len(self._penalties)} penalties loaded from {self.cache_path}"
                )

═══════════════════════════════════════════════════════════════════════════════
FIX 1C: Update state_sync_manager.py - JSON file operations
═══════════════════════════════════════════════════════════════════════════════

LOCATION: src/trading/state_sync_manager.py, around line 181-190

ADD THIS AT TOP OF FILE:
─────────────────────────────────────────────────────────────────────────────
    from src.utils.json_utils import safe_json_load, safe_json_write

THEN REPLACE THIS CODE:
─────────────────────────────────────────────────────────────────────────────
    registry_path = os.path.join(os.getcwd(), "transactional_tickets.json")
    try:
        registry = {}
        if os.path.exists(registry_path):
            with open(registry_path, "r", encoding="utf-8") as handle:
                registry = json.load(handle)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to load registry: {e}")
        registry = {}

WITH:
─────────────────────────────────────────────────────────────────────────────
    registry_path = os.path.join(os.getcwd(), "transactional_tickets.json")
    # FIX: Use safe_json_load for robust handling
    registry = safe_json_load(
        file_path=registry_path,
        default={},
        auto_recover=True,
    )

═══════════════════════════════════════════════════════════════════════════════
FIX 2A: Update finnhub_macro_manager.py - Import refactored module
═══════════════════════════════════════════════════════════════════════════════

LOCATION: src/analysis/finnhub_macro_manager.py, around line 40-50

ADD THIS IMPORT after existing imports:
─────────────────────────────────────────────────────────────────────────────
    # Import refactored news fetching functions with improved fallback strategies
    try:
        from FINNHUB_NEWS_FETCHING_REFACTORED import (
            fetch_and_process_news_sentiment_refactored,
            NewsResult,
        )
        REFACTORED_NEWS_AVAILABLE = True
    except ImportError:
        REFACTORED_NEWS_AVAILABLE = False
        logger.warning("[FINNHUB_INIT] Refactored news module not available. Using original implementation.")

═══════════════════════════════════════════════════════════════════════════════
FIX 2B: Update finnhub_macro_manager.py - _fetch_and_process_news_sentiment()
═══════════════════════════════════════════════════════════════════════════════

LOCATION: src/analysis/finnhub_macro_manager.py, around line 700

REPLACE THE ENTIRE METHOD _fetch_and_process_news_sentiment() WITH:
─────────────────────────────────────────────────────────────────────────────

    async def _fetch_and_process_news_sentiment(self) -> None:
        \"\"\"
        Fetch market news and sentiment from Finnhub with enhanced fallback strategy.
        
        IMPROVEMENTS:
        1. Timeframe Expansion: 48-hour lookback instead of 1 hour
        2. Query Fallback: Specific pairs → general forex category
        3. Graceful Empty State: Returns neutral sentiment (0.5) for quiet markets
        4. Multi-level Fallback: EUR/USD → searches EUR + USD separately
        
        Uses refactored news fetching module if available for best results.
        Falls back to original implementation if module not found.
        \"\"\"
        if not self.enable_sentiment_analysis:
            return

        try:
            # Use refactored news fetching if available
            if REFACTORED_NEWS_AVAILABLE:
                await fetch_and_process_news_sentiment_refactored(self)
                logger.debug(
                    "[FINNHUB_NEWS] Using refactored news fetching with fallback strategy"
                )
            else:
                # Fallback to original implementation
                await self._fetch_and_process_news_sentiment_original()
                logger.debug(
                    "[FINNHUB_NEWS] Using original news fetching (refactored not available)"
                )

        except Exception as e:
            logger.warning(
                "[FINNHUB_NEWS_ERROR] Failed to fetch news/sentiment: %s",
                str(e)[:100],
            )
            raise

═══════════════════════════════════════════════════════════════════════════════
FIX 2C: Keep original method as fallback
═══════════════════════════════════════════════════════════════════════════════

LOCATION: src/analysis/finnhub_macro_manager.py (existing method)

RENAME THE EXISTING _fetch_and_process_news_sentiment() to:
_fetch_and_process_news_sentiment_original()

This keeps the original logic as a fallback if the refactored module
can't be imported, ensuring no downtime during deployment.

═══════════════════════════════════════════════════════════════════════════════
TESTING EXAMPLES
═══════════════════════════════════════════════════════════════════════════════

TEST 1: Verify JSON utils work
─────────────────────────────────────────────────────────────────────────────
    import json
    import os
    from src.utils.json_utils import safe_json_load, safe_json_write
    
    # Test 1: Load non-existent file (should return default)
    data = safe_json_load("data/nonexistent.json", default={"test": True})
    assert data == {"test": True}, "Failed to return default for missing file"
    print("✅ Test 1: Missing file returns default")
    
    # Test 2: Load empty file (should recover)
    test_file = "data/test_empty.json"
    os.makedirs("data", exist_ok=True)
    with open(test_file, 'w') as f:
        f.write("")  # Empty file
    
    data = safe_json_load(test_file, default={"recovered": True})
    assert data == {"recovered": True}, "Failed to recover empty file"
    assert os.path.getsize(test_file) > 0, "Failed to rewrite empty file"
    print("✅ Test 2: Empty file recovered and rewritten")
    
    # Test 3: Load corrupted JSON (should recover)
    with open(test_file, 'w') as f:
        f.write("{invalid json")  # Corrupted
    
    data = safe_json_load(test_file, default={"fixed": True})
    assert data == {"fixed": True}, "Failed to recover corrupted JSON"
    print("✅ Test 3: Corrupted JSON recovered")
    
    # Test 4: Save and load valid data
    test_data = {"key": "value", "nested": {"data": 123}}
    safe_json_write(test_file, test_data)
    loaded_data = safe_json_load(test_file)
    assert loaded_data == test_data, "Save/load failed"
    print("✅ Test 4: Save and load valid JSON")
    
    # Cleanup
    os.remove(test_file)
    print("✅ All JSON utils tests passed!")

TEST 2: Verify Finnhub refactored news module
─────────────────────────────────────────────────────────────────────────────
    import asyncio
    import os
    from src.analysis.FINNHUB_NEWS_FETCHING_REFACTORED import (
        fetch_news_with_fallback_and_cleanup,
        _split_symbol,
        _extract_sentiment_keywords,
    )
    
    # Test 1: Symbol splitting
    assert _split_symbol("EUR/USD") == ("EUR", "USD")
    assert _split_symbol("EURUSD") == ("EUR", "USD")
    print("✅ Test 1: Symbol splitting works")
    
    # Test 2: Sentiment extraction
    text_bullish = "EUR rallied strongly with hawkish ECB comments"
    sent, score = _extract_sentiment_keywords(text_bullish)
    assert sent == "bullish" and score > 0.6
    print(f"✅ Test 2: Bullish sentiment detected ({score:.2f})")
    
    text_bearish = "USD declined due to dovish Fed guidance"
    sent, score = _extract_sentiment_keywords(text_bearish)
    assert sent == "bearish" and score < 0.4
    print(f"✅ Test 3: Bearish sentiment detected ({score:.2f})")
    
    text_neutral = "Trading volumes increased"
    sent, score = _extract_sentiment_keywords(text_neutral)
    assert sent == "neutral" and 0.4 < score < 0.6
    print(f"✅ Test 4: Neutral sentiment detected ({score:.2f})")
    
    print("✅ All sentiment extraction tests passed!")

═══════════════════════════════════════════════════════════════════════════════
RUN IN PRODUCTION
═══════════════════════════════════════════════════════════════════════════════

After applying all fixes, restart the bot:

    python main_bot.py

Monitor the startup logs for:
    ✅ [JSON_UTILS] messages (should NOT see JSON decode errors)
    ✅ [NEWS_FETCH] messages (should show news fetching with fallback strategy)
    ✅ [FINNHUB_NEWS] messages (should show sentiment scores calculated)

Expected improvement:
    BEFORE: Multiple JSON decode errors, Finnhub fallback warnings
    AFTER: Clean startup, robust error handling, better news coverage

═══════════════════════════════════════════════════════════════════════════════
"""

__all__ = []

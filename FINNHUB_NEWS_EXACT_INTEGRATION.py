"""
EXACT CODE CHANGES FOR finnhub_macro_manager.py
================================================

This file shows the EXACT changes needed to apply the refactored news fetching.
Copy-paste ready code snippets.

==============================================================================
CHANGE 1: Add Import at Top of File (around line 40)
==============================================================================

FIND THIS SECTION (lines 30-45):
    from __future__ import annotations
    
    import asyncio
    import json
    import logging
    import os
    import threading
    import time
    from datetime import datetime, timezone, timedelta
    from typing import Any, Dict, List, Optional, Tuple
    from dataclasses import dataclass, field
    from pathlib import Path
    
    try:
        import aiohttp
    except ImportError:
        aiohttp = None

ADD THIS AFTER THE EXISTING IMPORTS (before "logger = logging.getLogger"):
    
    # Import refactored news fetching functions
    try:
        from FINNHUB_NEWS_FETCHING_REFACTORED import (
            fetch_news_with_fallback_and_cleanup,
            fetch_and_process_news_sentiment_refactored,
            NewsResult,
            _clean_symbol,
            _split_symbol,
            NEWS_LOOKBACK_HOURS,
            USE_GENERAL_FOREX_FALLBACK,
        )
        REFACTORED_NEWS_AVAILABLE = True
    except ImportError:
        logger.warning("[FINNHUB_INIT] Could not import refactored news module. Using original.")
        REFACTORED_NEWS_AVAILABLE = False

FULL CONTEXT:
    ============
    try:
        import aiohttp
    except ImportError:
        aiohttp = None
    
    # NEW: Import refactored news fetching functions
    try:
        from FINNHUB_NEWS_FETCHING_REFACTORED import (
            fetch_news_with_fallback_and_cleanup,
            fetch_and_process_news_sentiment_refactored,
            NewsResult,
            _clean_symbol,
            _split_symbol,
            NEWS_LOOKBACK_HOURS,
            USE_GENERAL_FOREX_FALLBACK,
        )
        REFACTORED_NEWS_AVAILABLE = True
    except ImportError:
        logger.warning("[FINNHUB_INIT] Could not import refactored news module. Using original.")
        REFACTORED_NEWS_AVAILABLE = False
    
    logger = logging.getLogger(__name__)


==============================================================================
CHANGE 2: Replace _fetch_and_process_news_sentiment() Method (around line 649)
==============================================================================

FIND THIS METHOD (exactly as shown in the file):

    async def _fetch_and_process_news_sentiment(self) -> None:
        \"\"\"
        Fetch market news and sentiment from Finnhub.
        
        Updates sentiment scores in snapshot_cache.
        OPTIMIZED: Fetch only last 3 articles with 30s timeout.
        \"\"\"
        if not self.enable_sentiment_analysis:
            return

        try:
            # OPTIMIZED: Fetch only last 3 HIGH-IMPACT news articles to reduce latency
            url = f"{FINNHUB_NEWS_ENDPOINT}?category=forex&limit=3&token={self.api_key}"
            data = await self._rate_limited_call(url, timeout_seconds=30.0)

            # Handle both dict and list responses
            if isinstance(data, dict):
                articles = data.get("data", []) or []
            elif isinstance(data, list):
                articles = data
            else:
                logger.warning("[FINNHUB_NEWS] Unexpected response type: %s", type(data).__name__)
                articles = []
                
            logger.debug("[FINNHUB_NEWS] Fetched %d news articles from API", len(articles))

            # Parse and score sentiment
            parsed_articles = self._parse_news_articles(articles)

            # MEMORY OPTIMIZATION: Keep only the 3 most recent articles in history
            parsed_articles = parsed_articles[:3]

            # Distribute sentiment to symbols
            with self._cache_lock:
                for symbol, snapshot in self._snapshot_cache.items():
                    # Find relevant articles for this symbol
                    relevant_articles = self._filter_articles_for_symbol(
                        parsed_articles, symbol
                    )

                    if relevant_articles:
                        # Calculate weighted sentiment score
                        sentiment_score = self._calculate_weighted_sentiment(
                            relevant_articles
                        )
                        snapshot.news_sentiment_score = sentiment_score
                    else:
                        # Default to neutral
                        snapshot.news_sentiment_score = 0.5

                    snapshot.last_updated_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.warning(
                "[FINNHUB_NEWS_ERROR] Failed to fetch news/sentiment: %s",
                str(e)[:100],
            )
            raise


REPLACE WITH THIS (new refactored version):

    async def _fetch_and_process_news_sentiment(self) -> None:
        \"\"\"
        Fetch market news and sentiment from Finnhub with enhanced fallback strategy.
        
        IMPROVEMENTS:
        1. Broadened Search: Splits symbol pairs (AUD/USD → searches AUD OR USD)
        2. General Forex Fallback: Falls back to general 'forex' category if no currency-specific news
        3. Extended Lookback: Searches 24+ hours of articles (not just 1 hour)
        4. Graceful Empty Handling: Returns neutral sentiment (0.5) instead of error
        5. Symbol Cleaning: Automatically handles AUD/USD vs AUDUSD formats
        
        Updates sentiment scores in snapshot_cache.
        \"\"\"
        if not self.enable_sentiment_analysis:
            return

        try:
            # Use refactored news fetching if available
            if REFACTORED_NEWS_AVAILABLE:
                await fetch_and_process_news_sentiment_refactored(self)
            else:
                # Fallback to original implementation
                await self._fetch_and_process_news_sentiment_original()

        except Exception as e:
            logger.warning(
                "[FINNHUB_NEWS_ERROR] Failed to fetch news/sentiment: %s",
                str(e)[:100],
            )
            raise

    # OPTIONAL: Keep original method as backup
    async def _fetch_and_process_news_sentiment_original(self) -> None:
        \"\"\"
        Original implementation (kept for backward compatibility if refactored import fails).
        \"\"\"
        try:
            url = f"{FINNHUB_NEWS_ENDPOINT}?category=forex&limit=3&token={self.api_key}"
            data = await self._rate_limited_call(url, timeout_seconds=30.0)

            if isinstance(data, dict):
                articles = data.get("data", []) or []
            elif isinstance(data, list):
                articles = data
            else:
                logger.warning("[FINNHUB_NEWS] Unexpected response type: %s", type(data).__name__)
                articles = []
                
            logger.debug("[FINNHUB_NEWS] Fetched %d news articles from API", len(articles))

            parsed_articles = self._parse_news_articles(articles)
            parsed_articles = parsed_articles[:3]

            with self._cache_lock:
                for symbol, snapshot in self._snapshot_cache.items():
                    relevant_articles = self._filter_articles_for_symbol(
                        parsed_articles, symbol
                    )

                    if relevant_articles:
                        sentiment_score = self._calculate_weighted_sentiment(
                            relevant_articles
                        )
                        snapshot.news_sentiment_score = sentiment_score
                    else:
                        snapshot.news_sentiment_score = 0.5

                    snapshot.last_updated_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.warning(
                "[FINNHUB_NEWS_ERROR_ORIGINAL] Failed to fetch news/sentiment: %s",
                str(e)[:100],
            )
            raise


==============================================================================
VERIFICATION CHECKLIST
==============================================================================

After making these changes:

□ 1. File has the new import block at the top
□ 2. _fetch_and_process_news_sentiment() method calls refactored version
□ 3. FINNHUB_NEWS_FETCHING_REFACTORED.py is in the same directory
□ 4. Bot starts without import errors
□ 5. Logs show "[FINNHUB_NEWS]" messages with article counts and sources
□ 6. No more "Technical-Only mode" errors for AUD/USD, EUR/USD, etc.


==============================================================================
SIMPLE VERSION (if you don't want the fallback method)
==============================================================================

If you want the SIMPLEST possible change, just replace the entire 
_fetch_and_process_news_sentiment() method with this one-liner:

    async def _fetch_and_process_news_sentiment(self) -> None:
        \"\"\"Fetch market news and sentiment from Finnhub with full fallback strategy.\"\"\"
        if not self.enable_sentiment_analysis:
            return
        try:
            if REFACTORED_NEWS_AVAILABLE:
                await fetch_and_process_news_sentiment_refactored(self)
            else:
                logger.error("[FINNHUB_NEWS] Refactored module not available")
        except Exception as e:
            logger.warning("[FINNHUB_NEWS_ERROR] Failed: %s", str(e)[:100])

This minimal version:
- ✅ Uses the refactored code
- ✅ Fails gracefully if import not available
- ✅ Removes the old parsing/filtering logic entirely
- ✅ All business logic moved to FINNHUB_NEWS_FETCHING_REFACTORED.py


==============================================================================
ADVANCED: CUSTOM CONFIGURATION
==============================================================================

If you want to customize the refactored behavior per symbol, add this method
to FinnhubMacroManager class:

    def configure_news_fetching(self, **kwargs):
        \"\"\"
        Customize news fetching behavior (called after manager init).
        
        Args:
            lookback_hours: How far back to search for articles
            max_articles_per_query: Maximum articles to fetch per query
            use_forex_fallback: Whether to fall back to general forex category
        
        Example:
            manager.configure_news_fetching(
                lookback_hours=48,
                max_articles_per_query=10,
                use_forex_fallback=True
            )
        \"\"\"
        import FINNHUB_NEWS_FETCHING_REFACTORED as fnfr
        
        if 'lookback_hours' in kwargs:
            fnfr.NEWS_LOOKBACK_HOURS = kwargs['lookback_hours']
        if 'max_articles_per_query' in kwargs:
            fnfr.MAX_ARTICLES_PER_QUERY = kwargs['max_articles_per_query']
        if 'use_forex_fallback' in kwargs:
            fnfr.USE_GENERAL_FOREX_FALLBACK = kwargs['use_forex_fallback']
        
        logger.info(
            "[FINNHUB_CONFIG] News fetching updated: "
            "lookback=%dh, max_articles=%d, fallback=%s",
            fnfr.NEWS_LOOKBACK_HOURS,
            fnfr.MAX_ARTICLES_PER_QUERY,
            fnfr.USE_GENERAL_FOREX_FALLBACK
        )


==============================================================================
TESTING THE INTEGRATION
==============================================================================

Quick test to verify everything is wired up:

In Python REPL:

    import asyncio
    from src.analysis.finnhub_macro_manager import FinnhubMacroManager
    
    async def test():
        manager = FinnhubMacroManager(
            api_key="your_key",
            symbols=["AUD/USD"]
        )
        # Manually call news fetching
        await manager._fetch_and_process_news_sentiment()
        
        # Check the snapshot
        snapshot = manager._snapshot_cache.get("AUDUSD")
        print(f"Sentiment: {snapshot.news_sentiment_score}")
        print(f"Update time: {snapshot.last_updated_at}")
    
    asyncio.run(test())

Expected output:
    Sentiment: 0.52  (or any value 0.0-1.0)
    Update time: 2026-04-16 14:23:45.123456+00:00


==============================================================================
SUMMARY OF CHANGES
==============================================================================

Files to create/modify:
✅ CREATE: FINNHUB_NEWS_FETCHING_REFACTORED.py (new module, 450+ lines)
✅ MODIFY: src/analysis/finnhub_macro_manager.py
   - Add import at top
   - Replace _fetch_and_process_news_sentiment() method

Expected result:
✅ No more "Technical-Only mode" errors
✅ Consistent macro context available
✅ Graceful handling of empty news results
✅ Better sentiment scores with extended lookback
✅ Currency pairs searched more broadly

This is a drop-in replacement - no breaking changes to existing code!
"""

if __name__ == "__main__":
    print(__doc__)

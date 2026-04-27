"""
FinnhubMacroManager - Real-time Macro-Economic Risk & Sentiment Integration

Integrates Finnhub API to provide:
1. Economic Calendar: News impact assessment (HIGH, MEDIUM, LOW)
2. Market News & Sentiment: Positive/Negative/Neutral classification
3. Volatility Anticipation: Upcoming event scheduling
4. Risk Scoring: Dynamic 0.0-10.0 risk scale based on macroeconomic conditions

Features:
- Asynchronous execution (non-blocking MT5 pulse)
- Robust caching (12-24 hours for calendar, 5-15 min for news)
- Rate limiting (respects Finnhub free tier: 60 API calls/min)
- Graceful degradation (falls back to VOLATILITY_NORMAL_FALLBACK on API failure)
- Thread-safe cache updates for macro_risk_cache integration

Usage:
    manager = FinnhubMacroManager(
        api_key="your_finnhub_api_key",
        symbols=["EUR/USD", "GBP/USD", "USD/JPY"],
        macro_risk_cache=macro_risk_cache,  # From llm_macro_monitor
    )
    await manager.start()
    # In main loop, periodically update:
    await manager.refresh_all()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import functools
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from pathlib import Path

try:
    import aiohttp
except ImportError:
    aiohttp = None

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
    REFACTORED_NEWS_AVAILABLE = False

logger = logging.getLogger(__name__)

if not REFACTORED_NEWS_AVAILABLE:
    logger.warning("[FINNHUB_INIT] Could not import refactored news module. Using original.")


def async_retry(*, attempts: int = 3, base_delay_seconds: float = 1.0, exceptions: tuple[type[BaseException], ...] = (Exception,)):
    """Retry async methods with bounded exponential backoff."""
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt >= attempts:
                        break
                    delay = base_delay_seconds * (2 ** (attempt - 1))
                    logger.warning(
                        "[FINNHUB_RETRY] %s failed on attempt %d/%d: %s | retrying in %.1fs",
                        func.__name__,
                        attempt,
                        attempts,
                        str(exc)[:100],
                        delay,
                    )
                    await asyncio.sleep(delay)
            raise last_exc
        return wrapper
    return decorator

# ============================================================================
# Constants & Configuration
# ============================================================================

FINNHUB_API_BASE = "https://finnhub.io/api/v1"
FINNHUB_ECONOMIC_CALENDAR_ENDPOINT = f"{FINNHUB_API_BASE}/economic-calendar"
FINNHUB_NEWS_ENDPOINT = f"{FINNHUB_API_BASE}/news"
FINNHUB_SENTIMENT_ENDPOINT = f"{FINNHUB_API_BASE}/news"

# Rate limiting (Finnhub free tier: 60 calls/min = 1 call/sec)
DEFAULT_RATE_LIMIT_CALLS = 60
DEFAULT_RATE_LIMIT_WINDOW_SECONDS = 60
MIN_API_CALL_INTERVAL_SECONDS = 1.0  # Respect rate limit
FINNHUB_TIMEOUT_SECONDS = float(os.environ.get("FINNHUB_TIMEOUT", "90.0"))  # PRODUCTION: Increased to 90s for ultra-staggered single-symbol requests

# Caching intervals
ECONOMIC_CALENDAR_CACHE_MINUTES = 720  # 12 hours
NEWS_SENTIMENT_CACHE_MINUTES = 10  # Shorter cache for freshness
NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS = 1800  # OPTIMIZATION B: Poll every 30 minutes (was 5 min)

# Currency-to-News-Keywords mapping for Finnhub
CURRENCY_KEYWORDS = {
    "EUR": ["EUR", "EURUSD", "Euro", "eurozone", "ECB"],
    "GBP": ["GBP", "GBPUSD", "sterling", "BOE", "Bank of England"],
    "JPY": ["JPY", "USDJPY", "BoJ", "Bank of Japan", "yen"],
    "CHF": ["CHF", "USDCHF", "Swiss", "SNB"],
    "AUD": ["AUD", "AUDUSD", "Australian dollar", "RBA"],
    "CAD": ["CAD", "USDCAD", "Canadian dollar", "BoC"],
    "NZD": ["NZD", "NZDUSD", "kiwi", "RBNZ"],
    "USD": ["USD", "dollar", "Fed", "Federal Reserve"],
}

# Economic event impact levels to risk score mapping
IMPACT_TO_RISK_MULTIPLIER = {
    "high": 3.0,      # High-impact events (NFP, CPI, ECB rates) -> highest risk
    "medium": 1.5,    # Medium-impact events
    "low": 0.5,       # Low-impact events
}

# Sentiment scores
SENTIMENT_RISK_MAPPING = {
    "bullish": -0.2,    # Positive news reduces risk
    "positive": -0.2,
    "bearish": 0.3,     # Negative news increases risk
    "negative": 0.3,
    "neutral": 0.0,
}

# Default/fallback risk scores
DEFAULT_MACRO_RISK_SCORE = 2.0  # VOLATILITY_NORMAL equivalent
MAX_MACRO_RISK_SCORE = 10.0
MIN_MACRO_RISK_SCORE = 0.0

# ============================================================================
# Data Classes
# ============================================================================


@dataclass
class EconomicEvent:
    """Represents an economic calendar event from Finnhub."""
    country: str = ""
    event_name: str = ""
    impact: str = ""  # "high", "medium", "low"
    forecast: Optional[float] = None
    previous: Optional[float] = None
    actual: Optional[float] = None
    event_datetime_str: str = ""
    minutes_until_event: int = 0


@dataclass
class NewsArticle:
    """Represents a news article with sentiment from Finnhub."""
    headline: str = ""
    summary: str = ""
    source: str = ""
    url: str = ""
    published_at_unix: int = 0
    sentiment: str = ""  # "bullish", "neutral", "bearish"
    sentiment_score: float = 0.5  # 0.0-1.0


@dataclass
class MacroRiskSnapshot:
    """Snapshot of macro risk factors for a symbol."""
    symbol: str = ""
    risk_score: float = DEFAULT_MACRO_RISK_SCORE
    risk_reason: str = "No_Macro_Risk"
    upcoming_events: List[EconomicEvent] = field(default_factory=list)
    news_sentiment_score: float = 0.5  # 0.0 = very bearish, 1.0 = very bullish
    event_minutes_until_high_impact: Optional[int] = None
    last_updated_at: Optional[datetime] = None
    data_freshness_ok: bool = False


# ============================================================================
# FinnhubMacroManager
# ============================================================================


class FinnhubMacroManager:
    """
    NON-BLOCKING Background Task for Real-Time Macro-Economic Monitoring.
    
    ARCHITECTURE:
    - Runs in separate asyncio task (never blocks MT5 pulse)
    - Caches all data locally (zero latency reads from main loop)
    - Updates cache every 5 minutes (economic calendar + sentiment)
    - Main loop reads snapshot cache (instant access, no API calls)
    
    This solves:
    1. Macro Data Lag: Background task, cached data for main loop
    2. LLM Timeout: Minified JSON payload reduces processing time 5s -> <1s
    3. 10s MT5 Pulse: Zero blocking, all async operations in background
    
    Usage:
        # Initialize once, never block main loop after
        manager = FinnhubMacroManager(api_key=key, symbols=symbols, macro_risk_cache=cache)
        await manager.start()  # Start background task once
        
        # In main 10s pulse loop: just read cached snapshots (instant)
        snapshot = manager.get_latest_snapshot(symbol)
        
        # For LLM: get minified JSON (already prepared in background)
        llm_payload_json = manager.get_llm_payload_json()  # <100ms, zero API calls
    
    Manages real-time macro-economic monitoring and sentiment analysis via Finnhub API.
    
    Runs asynchronously with non-blocking API calls. Updates risks in real-time
    and feeds them into macro_risk_cache for the main bot decision loop.
    """

    def __init__(
        self,
        api_key: str,
        symbols: List[str],
        macro_risk_cache: Optional[Any] = None,
        cache_dir: str = "data",
        rate_limit_calls: int = DEFAULT_RATE_LIMIT_CALLS,
        rate_limit_window_seconds: int = DEFAULT_RATE_LIMIT_WINDOW_SECONDS,
        high_impact_event_window_minutes: int = 30,
        enable_sentiment_analysis: bool = True,
        enable_economic_calendar: bool = True,
    ):
        """
        Initialize FinnhubMacroManager.

        Args:
            api_key: Finnhub API key (get from https://finnhub.io/)
            symbols: List of symbols to monitor (e.g., ["EUR/USD", "GBP/USD"])
            macro_risk_cache: Reference to macro_risk_cache from llm_macro_monitor
            cache_dir: Directory to store cache files
            rate_limit_calls: API calls allowed per window
            rate_limit_window_seconds: Rate limit window size
            high_impact_event_window_minutes: Minutes before/after event window
            enable_sentiment_analysis: Enable news sentiment analysis
            enable_economic_calendar: Enable economic calendar fetching
        """
        self.api_key = api_key
        self.symbols = [str(s).replace("/", "").upper() for s in symbols]
        self.symbols_display = list(symbols)  # For logging
        self.macro_risk_cache = macro_risk_cache
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # HARD-KILL: Delete stale news_cache.json on startup if it exists
        # Prevents 1500+ minute old cache from causing timeouts
        news_cache_file = self.cache_dir / "news_cache.json"
        if news_cache_file.exists():
            try:
                news_cache_file.unlink()
                logger.info("[MACRO_CACHE_CLEANUP] Deleted stale news_cache.json to prevent timeout loops.")
            except Exception as e:
                logger.warning("[MACRO_CACHE_CLEANUP] Failed to delete news_cache.json: %s", e)
        
        # Also delete macro_news_cache.json if it exists
        macro_cache_file = self.cache_dir / "macro_news_cache.json"
        if macro_cache_file.exists():
            try:
                macro_cache_file.unlink()
                logger.info("[MACRO_CACHE_CLEANUP] Deleted stale macro_news_cache.json to prevent timeout loops.")
            except Exception as e:
                logger.warning("[MACRO_CACHE_CLEANUP] Failed to delete macro_news_cache.json: %s", e)

        # Rate limiting
        self.rate_limit_calls = max(1, rate_limit_calls)
        self.rate_limit_window_seconds = max(10, rate_limit_window_seconds)
        self._api_call_times: List[float] = []
        self._rate_limit_lock = asyncio.Lock()

        # Configuration
        self.high_impact_event_window_minutes = max(10, high_impact_event_window_minutes)
        self.enable_sentiment_analysis = enable_sentiment_analysis
        self.enable_economic_calendar = enable_economic_calendar

        # State management
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._consecutive_failures = 0
        self.failure_counter = 0
        self._max_consecutive_failures = 5
        self._fallback_mode_active = False
        self._last_api_error: Optional[str] = None
        self._http_session: Optional[aiohttp.ClientSession] = None
        self.technical_only_mode: bool = False
        self._technical_only_mode_until: Optional[datetime] = None  # Track when technical_only_mode expires
        self._skip_refresh_cycles_remaining: int = 0
        self.macro_fail_cooldown: int = 0  # Skip Finnhub calls for N cycles after timeout
        # ✅ NEW: Thread-liveness heartbeat (tracks last successful refresh)
        self._last_successful_refresh: datetime = datetime.now(timezone.utc)

        # Cache state
        self._snapshot_cache: Dict[str, MacroRiskSnapshot] = {}
        self._cache_valid_until: Dict[str, float] = {}
        self._cache_lock = threading.Lock()

        # Extraction helper for currency from symbol
        self.currency_pairs_by_symbol = self._map_symbol_to_currencies(symbols)

        # Initialize empty snapshots
        for symbol in self.symbols:
            self._snapshot_cache[symbol] = MacroRiskSnapshot(symbol=symbol)

        logger.info(
            "[FINNHUB_INIT] FinnhubMacroManager initialized | Symbols: %s | "
            "Calendar: %s | Sentiment: %s | Rate Limit: %d calls/%d sec",
            self.symbols_display,
            self.enable_economic_calendar,
            self.enable_sentiment_analysis,
            self.rate_limit_calls,
            self.rate_limit_window_seconds,
        )

    @staticmethod
    def _map_symbol_to_currencies(symbols: List[str]) -> Dict[str, Tuple[str, str]]:
        """
        Map trading symbols to their base/quote currencies.
        E.g., "EUR/USD" -> ("EUR", "USD")
        """
        mapping = {}
        for symbol_str in symbols:
            symbol = str(symbol_str).replace("/", "").upper()
            if len(symbol_str.replace("/", "")) == 6:
                base = symbol_str.split("/")[0].upper()
                quote = symbol_str.split("/")[1].upper()
                mapping[symbol] = (base, quote)
        return mapping

    # ========================================================================
    # Lifecycle Management
    # ========================================================================

    async def start(self) -> None:
        """Start the background macro monitoring task."""
        if self._task and not self._task.done():
            logger.warning("[FINNHUB_START] Task already running")
            return

        # Validate API key
        if not self.api_key or str(self.api_key).strip() == "":
            logger.error(
                "[FINNHUB_START] ❌ API key is missing. Set FINNHUB_API_KEY environment variable."
            )
            self._fallback_mode_active = True
            return

        # Test API connectivity
        api_ok = await self._test_api_connectivity()
        if not api_ok:
            logger.warning(
                "[FINNHUB_START] ⚠️ API connectivity check failed. Entering fallback mode."
            )
            self._fallback_mode_active = True
            return

        # Start async task with heartbeat initialization
        self._stop_event.clear()
        self._last_successful_refresh = datetime.now(timezone.utc)  # Initialize heartbeat
        self._consecutive_failures = 0  # Reset failures on restart
        self._task = asyncio.create_task(
            self._background_monitor_loop(), name="finnhub-macro-monitor"
        )
        logger.info(
            "[FINNHUB_START] ✅ Background monitoring started | "
            "Heartbeat tracking active | Timeout: %.1fs | Max consecutive failures: %d",
            FINNHUB_TIMEOUT_SECONDS,
            self._max_consecutive_failures,
        )

    async def stop(self) -> None:
        """Stop the background monitoring task."""
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._http_session:
            try:
                await self._http_session.close()
            except Exception:
                pass
            self._http_session = None
        logger.info("[FINNHUB_STOP] Monitoring stopped")

    # ========================================================================
    # Main Loop & Periodic Updates
    # ========================================================================

    async def _background_monitor_loop(self) -> None:
        """
        Main background loop that periodically refreshes macro data.
        Runs independently from the main MT5 execution pulse.
        
        PRODUCTION OPTIMIZATION: Non-blocking refresh
        - The actual API fetching runs in a completely isolated asyncio task
        - The main loop only checks if the background task completed
        - If a refresh takes 40+ seconds, the main loop keeps running
        - Cache reads are always instant (never wait for API)
        
        IMPROVEMENTS:
        ✅ Heartbeat tracking: Records last successful refresh timestamp
        ✅ Timeout protection: Wraps refresh_all() in asyncio.timeout()
        ✅ Better error recovery: Resets failure counter on success
        ✅ Detailed logging: Every cycle logs state for liveness monitoring
        ✅ NON-BLOCKING: Main loop never waits for slow API calls
        """
        logger.info(
            "[FINNHUB_LOOP] Background monitoring loop started | "
            "Economic Calendar: %s | Sentiment: %s | Interval: %ds | NON-BLOCKING MODE",
            self.enable_economic_calendar,
            self.enable_sentiment_analysis,
            NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS,
        )

        self._last_successful_refresh = datetime.now(timezone.utc)  # Initialize heartbeat
        last_diagnostics_log = time.time()
        active_refresh_task: Optional[asyncio.Task] = None

        try:
            while not self._stop_event.is_set():
                try:
                    # Check if technical_only_mode should expire (1-hour timeout)
                    if self.technical_only_mode and self._technical_only_mode_until is not None:
                        if datetime.now(timezone.utc) >= self._technical_only_mode_until:
                            self.technical_only_mode = False
                            self._technical_only_mode_until = None
                            logger.info("[MACRO_RECOVERY] technical_only_mode expired after 1 hour. Re-enabling macro refresh.")
                    
                    # RESILIENCE: Skip Finnhub call if macro_fail_cooldown is active
                    if self.macro_fail_cooldown > 0:
                        self.macro_fail_cooldown -= 1
                        logger.debug(
                            "[FINNHUB_COOLDOWN] Skipping macro refresh for %d more cycles to keep heartbeat fast.",
                            self.macro_fail_cooldown,
                        )
                        await asyncio.sleep(NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS)
                        continue
                    
                    if self._skip_refresh_cycles_remaining > 0:
                        self.technical_only_mode = True
                        self._skip_refresh_cycles_remaining -= 1
                        logger.warning(
                            "[FINNHUB_TECHNICAL_ONLY] Skipping macro refresh for %d more cycles.",
                            self._skip_refresh_cycles_remaining,
                        )
                        await asyncio.sleep(NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS)
                        continue
                    
                    self.technical_only_mode = False
                    
                    # PRODUCTION OPTIMIZATION: Launch refresh in isolated task
                    # If a refresh is already running, skip this cycle (don't stack tasks)
                    if active_refresh_task is not None and not active_refresh_task.done():
                        logger.debug(
                            "[FINNHUB_NONBLOCKING] Previous refresh still running (%.1fs elapsed). Skipping this cycle.",
                            time.time() - getattr(self, '_last_refresh_start_time', time.time()),
                        )
                        await asyncio.sleep(NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS)
                        continue
                    
                    # Launch new refresh task in background
                    self._last_refresh_start_time = time.time()
                    active_refresh_task = asyncio.create_task(
                        self._isolated_refresh_task(),
                        name="finnhub-isolated-refresh"
                    )
                    logger.debug("[FINNHUB_NONBLOCKING] Launched isolated refresh task")
                    
                    # Sleep before next cycle (don't wait for refresh to complete)
                    await asyncio.sleep(NEWS_SENTIMENT_CHECK_INTERVAL_SECONDS)

                except asyncio.CancelledError:
                    logger.info("[FINNHUB_LOOP] Task cancelled, shutting down cleanly")
                    break
                except Exception as e:
                    # RESILIENCE: Immediately set technical_only_mode to prevent 5-second hang
                    self.technical_only_mode = True
                    self.macro_fail_cooldown = 10  # Skip next 10 cycles
                    
                    # Track failure but don't let it accumulate
                    self._consecutive_failures += 1
                    self.failure_counter = 0  # Clear to prevent bootstrap loop
                    self._last_api_error = str(e)[:100]
                    self._skip_refresh_cycles_remaining = 0  # Use macro_fail_cooldown instead
                    
                    logger.debug(
                        "[FINNHUB_FAILURE] API refresh failed. technical_only_mode=TRUE, macro_fail_cooldown=10. Keeping cycle fast.",
                    )
                    
                    heartbeat_age_sec = (datetime.now(timezone.utc) - self._last_successful_refresh).total_seconds()
                    logger.warning(
                        "[FINNHUB_LOOP_ERROR] Failure %d/%d | Error: %s | Last refresh: %.1fs ago",
                        self._consecutive_failures,
                        self._max_consecutive_failures,
                        str(e)[:80],
                        heartbeat_age_sec,
                    )

                    if self._consecutive_failures >= self._max_consecutive_failures:
                        logger.error(
                            "[FINNHUB_FALLBACK] Max failures (%d) reached. Activating fallback mode. "
                            "Last successful refresh: %.1fs ago",
                            self._max_consecutive_failures,
                            heartbeat_age_sec,
                        )
                        self._fallback_mode_active = True
                        break

                    # Exponential backoff with jitter
                    backoff = min(30, 2 ** (self._consecutive_failures - 1))
                    jitter = 0.1 * (time.time() % 1.0)
                    wait_time = backoff + jitter
                    logger.info(
                        "[FINNHUB_BACKOFF] Waiting %.1fs before retry (attempt %d/%d)",
                        wait_time,
                        self._consecutive_failures,
                        self._max_consecutive_failures,
                    )
                    await asyncio.sleep(wait_time)

        except asyncio.CancelledError:
            logger.info("[FINNHUB_LOOP] Cancelled during cleanup")
        finally:
            heartbeat_age_sec = (datetime.now(timezone.utc) - self._last_successful_refresh).total_seconds()
            logger.info(
                "[FINNHUB_LOOP_EXIT] Background monitoring loop stopped. "
                "Last successful refresh: %.1fs ago | Fallback mode: %s",
                heartbeat_age_sec,
                self._fallback_mode_active,
            )

    async def _isolated_refresh_task(self) -> None:
        """
        PRODUCTION OPTIMIZATION: Isolated refresh task that runs independently.
        
        This task handles all API calls and cache updates without blocking the
        main monitoring loop. If it takes 40+ seconds, the main loop continues
        using the previous cache data.
        
        On success: Updates _last_successful_refresh heartbeat
        On failure: Sets technical_only_mode and cooldowns
        """
        try:
            async with asyncio.timeout(FINNHUB_TIMEOUT_SECONDS):
                await self.refresh_all()
            
            # SUCCESS: Update heartbeat and reset failure counter
            self._last_successful_refresh = datetime.now(timezone.utc)
            self._consecutive_failures = 0
            self.failure_counter = 0
            logger.debug("[FINNHUB_ISOLATED_TASK] Refresh completed successfully")
            
            # Log diagnostics periodically
            now = time.time()
            if now - getattr(self, '_last_diagnostics_log_time', 0) >= 300:  # Every 5 minutes
                self._log_diagnostics()
                self._last_diagnostics_log_time = now
                
        except TimeoutError:
            elapsed = time.time() - getattr(self, '_last_refresh_start_time', time.time())
            logger.warning(
                "[FINNHUB_ISOLATED_TASK] Timeout after %.1fs. Main loop was NOT blocked. "
                "Entering technical-only mode for 3 cycles.",
                elapsed,
            )
            self._consecutive_failures = max(1, self._consecutive_failures + 1)
            self._last_api_error = f"TIMEOUT_{FINNHUB_TIMEOUT_SECONDS:.1f}s"
            self.technical_only_mode = True
            self._skip_refresh_cycles_remaining = 3
            self.macro_fail_cooldown = 10
            
        except asyncio.CancelledError:
            logger.info("[FINNHUB_ISOLATED_TASK] Cancelled during execution")
            
        except Exception as e:
            # RESILIENCE: Immediately set technical_only_mode to prevent 5-second hang
            self.technical_only_mode = True
            self.macro_fail_cooldown = 10  # Skip next 10 cycles
            
            # Track failure but don't let it accumulate
            self._consecutive_failures += 1
            self.failure_counter = 0  # Clear to prevent bootstrap loop
            self._last_api_error = str(e)[:100]
            self._skip_refresh_cycles_remaining = 0  # Use macro_fail_cooldown instead
            
            elapsed = time.time() - getattr(self, '_last_refresh_start_time', time.time())
            logger.debug(
                "[FINNHUB_ISOLATED_TASK] API refresh failed after %.1fs. "
                "technical_only_mode=TRUE, macro_fail_cooldown=10. Main loop NOT blocked.",
                elapsed,
            )
            
            if self._consecutive_failures >= self._max_consecutive_failures:
                heartbeat_age_sec = (datetime.now(timezone.utc) - self._last_successful_refresh).total_seconds()
                logger.error(
                    "[FINNHUB_FALLBACK] Max failures (%d) reached. Activating fallback mode. "
                    "Last successful refresh: %.1fs ago",
                    self._max_consecutive_failures,
                    heartbeat_age_sec,
                )
                self._fallback_mode_active = True

    async def refresh_all(self) -> None:
        """
        Synchronize all macro data from Finnhub and update macro_risk_cache.
        Each sub-operation is isolated so one failure doesn't block others.
        
        BUG FIX #3: Improved exception handling - wraps each API call in its own
        try/except so one slow API call doesn't hang the entire macro service.
        """
        if self._fallback_mode_active:
            return  # Silently skip if in fallback mode

        errors = []
        successful_operations = 0
        
        # 1. Fetch economic calendar events
        if self.enable_economic_calendar:
            try:
                await self._fetch_and_process_economic_calendar()
                successful_operations += 1
            except Exception as e:
                errors.append(f"Economic Calendar: {str(e)[:80]}")
                logger.warning("[FINNHUB_REFRESH] Economic calendar fetch failed: %s", str(e)[:80])

        # 2. Fetch and analyze sentiment with ULTRA-STAGGERED fetching
        if self.enable_sentiment_analysis:
            try:
                # PRODUCTION OPTIMIZATION: Ultra-staggered fetches to prevent timeouts
                # Fetch 1 symbol at a time, sleep 1.5s between each request
                # This ensures we stay well under rate limits and socket buffers
                total_symbols = len(self.symbols)
                if total_symbols > 1:
                    batch_size = 1  # Ultra-staggered: only 1 symbol per request
                    batches = [
                        self.symbols[i:i + batch_size]
                        for i in range(0, total_symbols, batch_size)
                    ]
                    
                    logger.info(
                        "[FINNHUB_ULTRA_STAGGER] Splitting %d symbols into %d ultra-staggered requests (1 symbol each) to prevent timeouts.",
                        total_symbols,
                        len(batches),
                    )
                    
                    for batch_idx, batch_symbols in enumerate(batches):
                        logger.debug(
                            "[FINNHUB_ULTRA_STAGGER] Processing request %d/%d with symbol: %s",
                            batch_idx + 1,
                            len(batches),
                            batch_symbols,
                        )
                        
                        # Process this single-symbol batch
                        await self._fetch_news_for_symbol_batch(batch_symbols)
                        
                        # Wait 1.5 seconds between requests (except after last)
                        if batch_idx < len(batches) - 1:
                            logger.debug(
                                "[FINNHUB_ULTRA_STAGGER_DELAY] Waiting 1.5s before next request to prevent socket hangup."
                            )
                            await asyncio.sleep(1.5)
                else:
                    # Single symbol - fetch directly
                    await self._fetch_and_process_news_sentiment()
                
                successful_operations += 1
            except Exception as e:
                errors.append(f"News Sentiment: {str(e)[:80]}")
                logger.warning("[FINNHUB_REFRESH] News sentiment fetch failed: %s", str(e)[:80])

        # 3. Calculate final risk scores (only if we have some data)
        try:
            await self._compute_all_risk_scores()
            successful_operations += 1
        except Exception as e:
            errors.append(f"Risk Scores: {str(e)[:80]}")
            logger.warning("[FINNHUB_REFRESH] Risk score computation failed: %s", str(e)[:80])

        # 4. Update macro_risk_cache (always push, even with partial data)
        try:
            self._push_to_macro_risk_cache()
            successful_operations += 1
        except Exception as e:
            errors.append(f"Cache Push: {str(e)[:80]}")
            logger.warning("[FINNHUB_REFRESH] Cache push failed: %s", str(e)[:80])

        if successful_operations > 0:
            self._last_successful_refresh = datetime.now(timezone.utc)
            self._consecutive_failures = 0

        # If all operations failed, raise to trigger backoff
        total_operations = sum([
            1 if self.enable_economic_calendar else 0,
            1 if self.enable_sentiment_analysis else 0,
            2  # risk scores + cache push always run
        ])
        if errors and len(errors) == total_operations:
            # PRODUCTION FIX: Asynchronous staggered retry with 4-hour cache resilience
            # Instead of immediately forcing technical_only_mode, use cached data for up to 4 hours
            cache_age_minutes = 0.0
            if self._last_successful_refresh:
                cache_age_minutes = (datetime.now(timezone.utc) - self._last_successful_refresh).total_seconds() / 60.0
            
            # If cache is less than 4 hours old, continue using it
            if cache_age_minutes < 240.0:  # 4 hours
                self.technical_only_mode = False  # Don't force technical-only mode
                self._consecutive_failures = min(self._consecutive_failures, 3)  # Cap failures to prevent fallback
                logger.warning(
                    "[MACRO_CACHE_RESILIENCE] All operations failed, but cache is only %.1f minutes old (<4 hours). "
                    "Continuing to use cached macro data. Will retry on next cycle.",
                    cache_age_minutes,
                )
            else:
                # Cache is older than 4 hours, force technical_only_mode
                self.technical_only_mode = True
                self._technical_only_mode_until = datetime.now(timezone.utc) + timedelta(hours=1)
                logger.critical(
                    "[MACRO_TIMEOUT_KILL] All operations failed AND cache is %.1f minutes old (>4 hours). "
                    "Forcing technical_only_mode=TRUE for 1 hour. Cache data expired.",
                    cache_age_minutes,
                )
            raise Exception(f"All operations failed: {'; '.join(errors)}")

    # ========================================================================
    # API Connectivity & Rate Limiting
    # ========================================================================

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with tcp_keepalive and 30s timeout."""
        if self._http_session is None or self._http_session.closed:
            # Create connector with tcp_keepalive to prevent connection hangs
            connector = aiohttp.TCPConnector(
                keepalive_timeout=30,      # Keep connection alive for 30 seconds
                ssl=True,                  # Use SSL for HTTPS
                limit_per_host=5,          # Max 5 connections per host
            )
            timeout = aiohttp.ClientTimeout(total=FINNHUB_TIMEOUT_SECONDS)
            self._http_session = aiohttp.ClientSession(connector=connector, timeout=timeout)
        return self._http_session

    async def _test_api_connectivity(self) -> bool:
        """Test if Finnhub API is reachable."""
        try:
            session = await self._get_session()
            test_url = f"{FINNHUB_ECONOMIC_CALENDAR_ENDPOINT}?token={self.api_key}"
            async with session.get(test_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    logger.info("[FINNHUB_TEST] ✅ API connectivity OK (HTTP 200)")
                    return True
                elif resp.status == 401:
                    logger.error("[FINNHUB_TEST] ❌ API authentication failed (HTTP 401)")
                    return False
                else:
                    logger.warning(f"[FINNHUB_TEST] Unexpected status: {resp.status}")
                    return False
        except Exception as e:
            logger.error("[FINNHUB_TEST] ❌ API connectivity failed: %s", str(e)[:100])
            return False

    async def _rate_limited_call(
        self, url: str, timeout_seconds: float = FINNHUB_TIMEOUT_SECONDS
    ) -> Dict[str, Any]:
        """
        Make a rate-limited API call.

        Respects Finnhub rate limits (60 calls/min on free tier).
        """
        async with self._rate_limit_lock:
            # Clean old timestamps
            now = time.time()
            self._api_call_times = [t for t in self._api_call_times if now - t < self.rate_limit_window_seconds]

            # Check if we need to wait
            if len(self._api_call_times) >= self.rate_limit_calls:
                wait_until = self._api_call_times[0] + self.rate_limit_window_seconds
                wait_seconds = max(0, wait_until - now)
                if wait_seconds > 0:
                    logger.debug(
                        "[FINNHUB_RATE_LIMIT] Waiting %.1f seconds to respect rate limit",
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)

            self._api_call_times.append(time.time())

        # Make the actual request
        try:
            session = await self._get_session()
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=timeout_seconds)
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                elif resp.status == 401:
                    raise PermissionError("Finnhub API authentication failed (401)")
                elif resp.status == 429:
                    raise RuntimeError("Finnhub API rate limit exceeded (429)")
                else:
                    raise RuntimeError(f"API returned HTTP {resp.status}")
        except asyncio.TimeoutError:
            raise TimeoutError(f"API request timed out after {timeout_seconds}s")
        except Exception as e:
            raise

    def clear_cache(self) -> None:
        """Clear stale macro cache and reset all snapshots to default-neutral values."""
        with self._cache_lock:
            self._cache_valid_until.clear()
            now = datetime.now(timezone.utc)
            for symbol in list(self._snapshot_cache.keys()):
                self._snapshot_cache[symbol] = MacroRiskSnapshot(
                    symbol=symbol,
                    risk_score=DEFAULT_MACRO_RISK_SCORE,
                    risk_reason="Cache_Cleared_Default",
                    last_updated_at=now,
                    data_freshness_ok=False,
                )
        self._last_successful_refresh = datetime.now(timezone.utc)
        logger.warning("[FINNHUB_CACHE_CLEAR] Snapshot cache reset to defaults.")

    def _clear_macro_news_cache_file(self) -> None:
        """Delete stale macro news cache file used by Finnhub ingestion."""
        cache_file = self.cache_dir / "macro_news_cache.json"
        try:
            if cache_file.exists():
                cache_file.unlink()
                logger.warning("[FINNHUB_CACHE_CLEAR] Removed stale cache file: %s", str(cache_file))
        except Exception as exc:
            logger.warning("[FINNHUB_CACHE_CLEAR] Failed to remove %s: %s", str(cache_file), str(exc)[:100])

    # ========================================================================
    # Economic Calendar Integration
    # ========================================================================

    @async_retry(attempts=3, base_delay_seconds=1.0, exceptions=(TimeoutError, RuntimeError, aiohttp.ClientError if aiohttp else Exception))
    async def _fetch_and_process_economic_calendar(self) -> None:
        """
        Fetch economic calendar events from Finnhub.
        
        Updates snapshot_cache with upcoming high-impact events for relevant currencies.
        OPTIMIZATION: Filters for high-impact events only to reduce payload size.
        """
        if not self.enable_economic_calendar:
            return

        try:
            # REQUEST OPTIMIZATION: Filter for high-impact events only via API parameter
            # This reduces the dataset size significantly, allowing API to process faster
            url = f"{FINNHUB_ECONOMIC_CALENDAR_ENDPOINT}?token={self.api_key}&impact=high"
            data = await self._rate_limited_call(url, timeout_seconds=FINNHUB_TIMEOUT_SECONDS)

            # Handle both dict and list responses
            if isinstance(data, dict):
                events = data.get("economicCalendar", []) or []
            elif isinstance(data, list):
                events = data
            else:
                logger.warning("[FINNHUB_CALENDAR] Unexpected response type: %s", type(data).__name__)
                events = []
            
            logger.debug("[FINNHUB_CALENDAR] Fetched %d economic events from API", len(events))

            # Parse events
            parsed_events = self._parse_economic_events(events)

            # Distribute events to relevant symbols
            with self._cache_lock:
                for symbol, snapshot in self._snapshot_cache.items():
                    relevant_events = self._filter_events_for_symbol(
                        parsed_events, symbol
                    )
                    snapshot.upcoming_events = relevant_events

                    # Find next high-impact event
                    high_impact_events = [
                        e
                        for e in relevant_events
                        if e.impact == "high"
                        or (e.impact == "medium" and e.minutes_until_event < 60)
                    ]
                    if high_impact_events:
                        next_high_impact = min(high_impact_events, key=lambda e: e.minutes_until_event)
                        snapshot.event_minutes_until_high_impact = (
                            next_high_impact.minutes_until_event
                        )

                    snapshot.last_updated_at = datetime.now(timezone.utc)

        except Exception as e:
            logger.warning(
                "[FINNHUB_CALENDAR_ERROR] Failed to fetch economic calendar: %s",
                str(e)[:100],
            )
            raise

    def _parse_economic_events(self, raw_events: List[Dict]) -> List[EconomicEvent]:
        """Parse raw economic events from Finnhub API."""
        parsed = []
        try:
            now = datetime.now(timezone.utc)

            for event_data in raw_events:
                try:
                    # Parse event time
                    event_time_str = event_data.get("date", "")
                    if not event_time_str:
                        continue

                    # Parse ISO datetime
                    try:
                        event_dt = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
                    except Exception:
                        continue

                    # Skip past events
                    minutes_until = (event_dt - now).total_seconds() / 60.0
                    if minutes_until < -5:  # Allow 5 min grace period
                        continue

                    event = EconomicEvent(
                        country=str(event_data.get("country", "")).upper(),
                        event_name=str(event_data.get("event", "")),
                        impact=str(event_data.get("impact", "low")).lower(),
                        forecast=self._safe_float(event_data.get("forecast")),
                        previous=self._safe_float(event_data.get("prev")),
                        actual=self._safe_float(event_data.get("actual")),
                        event_datetime_str=event_time_str,
                        minutes_until_event=int(max(0, minutes_until)),
                    )
                    parsed.append(event)

                except Exception as e:
                    logger.debug("[FINNHUB_PARSE_EVENT_ERROR] Skipping event: %s", str(e)[:50])
                    continue

        except Exception as e:
            logger.warning("[FINNHUB_PARSE_EVENTS_ERROR] Error parsing events: %s", str(e)[:100])

        return parsed

    def _filter_events_for_symbol(
        self, events: List[EconomicEvent], symbol: str
    ) -> List[EconomicEvent]:
        """
        Filter events relevant to a specific symbol.
        
        E.g., EUR/USD is affected by EUR and USD economic events.
        """
        if symbol not in self.currency_pairs_by_symbol:
            return []

        base_curr, quote_curr = self.currency_pairs_by_symbol[symbol]
        relevant_countries = []

        # Map currency to country codes
        country_map = {
            "EUR": ["EU", "DE", "FR"],
            "GBP": ["GB"],
            "JPY": ["JP"],
            "CHF": ["CH"],
            "AUD": ["AU"],
            "CAD": ["CA"],
            "NZD": ["NZ"],
            "USD": ["US"],
        }

        for curr in [base_curr, quote_curr]:
            relevant_countries.extend(country_map.get(curr, []))

        # Filter and limit to near-term events
        filtered = [
            e
            for e in events
            if e.country in relevant_countries
            and e.minutes_until_event <= self.high_impact_event_window_minutes * 2
        ]

        # Sort by urgency
        return sorted(filtered, key=lambda e: e.minutes_until_event)

    # ========================================================================
    # News & Sentiment Integration
    # ========================================================================

    async def _fetch_news_for_symbol_batch(self, batch_symbols: List[str]) -> None:
        """
        FIX: Fetch news for a batch of symbols (3 at a time) to prevent timeouts.
        This is called by refresh_all with staggered batching.
        
        Args:
            batch_symbols: List of 3 symbols to process in this batch
        """
        if not self.enable_sentiment_analysis:
            return
        
        try:
            # Fetch articles once for the batch
            if REFACTORED_NEWS_AVAILABLE:
                # Use refactored version but only for batch symbols
                original_symbols = self.symbols
                self.symbols = batch_symbols  # Temporarily limit to batch
                try:
                    await fetch_and_process_news_sentiment_refactored(self)
                finally:
                    self.symbols = original_symbols  # Restore
            else:
                # Fallback: fetch articles and process for batch symbols only
                try:
                    url = f"{FINNHUB_NEWS_ENDPOINT}?category=forex&limit=10&token={self.api_key}"
                    data = await self._rate_limited_call(url, timeout_seconds=FINNHUB_TIMEOUT_SECONDS)

                    if isinstance(data, dict):
                        articles = data.get("data", []) or []
                    elif isinstance(data, list):
                        articles = data
                    else:
                        articles = []
                except Exception as fetch_err:
                    logger.error("[FINNHUB_BATCH_FETCH_ERROR] Failed to fetch articles: %s", str(fetch_err)[:100])
                    articles = []
                
                # Process only batch symbols
                with self._cache_lock:
                    for symbol in batch_symbols:
                        if symbol not in self._snapshot_cache:
                            continue
                        
                        try:
                            snapshot = self._snapshot_cache[symbol]
                            parsed_articles = self._parse_news_articles(articles)
                            relevant_articles = self._filter_articles_for_symbol(parsed_articles, symbol)
                            
                            if relevant_articles:
                                sentiment_score = self._calculate_weighted_sentiment(relevant_articles)
                                snapshot.news_sentiment_score = sentiment_score
                            else:
                                snapshot.news_sentiment_score = 0.5
                            
                            snapshot.last_updated_at = datetime.now(timezone.utc)
                        except Exception as symbol_err:
                            logger.warning(
                                "[FINNHUB_BATCH_SYMBOL_ERROR] %s failed in batch: %s",
                                symbol, str(symbol_err)[:80]
                            )
        except Exception as e:
            logger.warning("[FINNHUB_BATCH_ERROR] Batch processing failed: %s", str(e)[:100])
            raise

    async def _fetch_and_process_news_sentiment(self) -> None:
        """
        Fetch market news and sentiment with PER-SYMBOL error isolation.
        
        KEY IMPROVEMENT: Each symbol's fetch wrapped in try/except.
        Single symbol failure does NOT cascade to global recovery trigger.
        
        IMPROVEMENTS:
        1. Per-Symbol Isolation: Each symbol processed independently
        2. Broadened Search: Splits symbol pairs (AUD/USD → searches AUD OR USD)
        3. General Forex Fallback: Falls back to general 'forex' category if no currency-specific news
        4. Extended Lookback: Searches 24+ hours of articles (not just 1 hour)
        5. Graceful Empty Handling: Returns neutral sentiment (0.5) instead of error
        6. Symbol Cleaning: Automatically handles AUD/USD vs AUDUSD formats
        
        Updates sentiment scores in snapshot_cache.
        """
        if not self.enable_sentiment_analysis:
            return

        # Track per-symbol failures (NEW - for non-cascading error handling)
        per_symbol_failures = {}
        symbols_processed = 0
        symbols_failed = 0
        
        try:
            # Use refactored news fetching if available
            if REFACTORED_NEWS_AVAILABLE:
                await fetch_and_process_news_sentiment_refactored(self)
            else:
                # Fallback to original implementation with per-symbol isolation
                try:
                    url = f"{FINNHUB_NEWS_ENDPOINT}?category=forex&limit=10&token={self.api_key}"
                    data = await self._rate_limited_call(url, timeout_seconds=FINNHUB_TIMEOUT_SECONDS)

                    if isinstance(data, dict):
                        articles = data.get("data", []) or []
                    elif isinstance(data, list):
                        articles = data
                    else:
                        logger.warning("[FINNHUB_NEWS] Unexpected response type: %s", type(data).__name__)
                        articles = []
                        
                    logger.debug("[FINNHUB_NEWS] Fetched %d news articles from API", len(articles))
                except Exception as fetch_err:
                    logger.error("[FINNHUB_NEWS_FETCH_ERROR] Failed to fetch articles: %s", str(fetch_err)[:100])
                    articles = []
                
                # Process each symbol INDEPENDENTLY (PER-SYMBOL ISOLATION - KEY CHANGE)
                with self._cache_lock:
                    for symbol, snapshot in self._snapshot_cache.items():
                        try:
                            symbols_processed += 1
                            
                            # Parse and filter articles for this specific symbol
                            parsed_articles = self._parse_news_articles(articles)
                            relevant_articles = self._filter_articles_for_symbol(parsed_articles, symbol)
                            
                            if relevant_articles:
                                sentiment_score = self._calculate_weighted_sentiment(relevant_articles)
                                snapshot.news_sentiment_score = sentiment_score
                                logger.debug(
                                    "[FINNHUB_NEWS_SYMBOL] %s | Found %d articles | Sentiment: %.2f",
                                    symbol, len(relevant_articles), sentiment_score
                                )
                            else:
                                # GRACEFUL: No articles found → neutral sentiment (0.5), not error
                                snapshot.news_sentiment_score = 0.5
                                logger.warning(
                                    "[FINNHUB_NEWS_SYMBOL] %s | No articles matched | Using neutral sentiment (0.5)",
                                    symbol
                                )
                            
                            snapshot.last_updated_at = datetime.now(timezone.utc)
                        
                        except Exception as symbol_err:
                            # PER-SYMBOL ERROR HANDLING (NEW - CRITICAL FIX)
                            symbols_failed += 1
                            per_symbol_failures[symbol] = str(symbol_err)[:100]
                            
                            # Default to neutral sentiment on per-symbol error
                            snapshot.news_sentiment_score = 0.5
                            snapshot.last_updated_at = datetime.now(timezone.utc)
                            
                            logger.warning(
                                "[FINNHUB_NEWS_SYMBOL_ERROR] %s | Failed to process: %s | Defaulting to 0.5 sentiment",
                                symbol, str(symbol_err)[:100]
                            )
                
                # Log summary (NEW)
                if symbols_failed > 0:
                    logger.warning(
                        "[FINNHUB_NEWS_SUMMARY] Processed %d symbols, %d failed (non-fatal) | "
                        "Failed symbols: %s",
                        symbols_processed, symbols_failed, list(per_symbol_failures.keys())
                    )
                else:
                    logger.info("[FINNHUB_NEWS_SUMMARY] Processed %d symbols with sentiment successfully", symbols_processed)

        except Exception as e:
            # IMPORTANT: Do NOT re-raise here - per-symbol errors already handled above
            # This exception should NOT propagate to refresh_all() and trigger global degradation
            logger.error(
                "[FINNHUB_NEWS_CRITICAL_ERROR] Unexpected error in news fetching: %s | "
                "Per-symbol errors already handled - continuing gracefully",
                str(e)[:100]
            )

    async def _fetch_and_process_news_sentiment_original(self) -> None:
        """
        Original implementation (kept for backward compatibility if refactored import fails).
        """
        try:
            url = f"{FINNHUB_NEWS_ENDPOINT}?category=forex&limit=3&token={self.api_key}"
            data = await self._rate_limited_call(url, timeout_seconds=FINNHUB_TIMEOUT_SECONDS)

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

    def _parse_news_articles(self, raw_articles: List[Dict]) -> List[NewsArticle]:
        """Parse raw news articles from Finnhub API."""
        parsed = []
        try:
            for article_data in raw_articles:
                try:
                    headline = str(article_data.get("headline", ""))
                    summary = str(article_data.get("summary", ""))
                    source = str(article_data.get("source", ""))

                    # OPTIMIZATION: Use summary for sentiment classification, then strip it
                    # This reduces token count sent to LLM while preserving sentiment accuracy
                    sentiment = self._classify_sentiment(headline + " " + summary)

                    # Create article with summary stripped (keeps headline + sentiment)
                    # Only headline and sentiment_score are sent to LLM for token efficiency
                    article = NewsArticle(
                        headline=headline,
                        summary="",  # OPTIMIZED: Strip summary to reduce LLM token count
                        source=source,
                        url=str(article_data.get("url", "")),
                        published_at_unix=int(article_data.get("datetime", 0)),
                        sentiment=sentiment,
                        sentiment_score=SENTIMENT_RISK_MAPPING.get(sentiment, 0.0),
                    )
                    parsed.append(article)

                except Exception as e:
                    logger.debug("[FINNHUB_PARSE_ARTICLE_ERROR] Skipping article: %s", str(e)[:50])
                    continue

        except Exception as e:
            logger.warning("[FINNHUB_PARSE_ARTICLES_ERROR] Error parsing articles: %s", str(e)[:100])

        return parsed

    def _filter_articles_for_symbol(
        self, articles: List[NewsArticle], symbol: str
    ) -> List[NewsArticle]:
        """
        Filter news articles relevant to a specific symbol.
        
        Uses keyword matching on headline only (summary was stripped for token efficiency).
        """
        if symbol not in self.currency_pairs_by_symbol:
            return []

        base_curr, quote_curr = self.currency_pairs_by_symbol[symbol]
        keywords = set()

        for curr in [base_curr, quote_curr]:
            keywords.update(CURRENCY_KEYWORDS.get(curr, []))

        filtered = []
        for article in articles:
            # OPTIMIZATION: Use only headline for filtering (summary was stripped)
            article_text = article.headline.lower()
            if any(kw.lower() in article_text for kw in keywords):
                filtered.append(article)

        return filtered

    @staticmethod
    def _classify_sentiment(text: str) -> str:
        """
        Basic sentiment classification using keyword matching.
        
        Can be replaced with a proper NLP model (e.g., TextBlob, Transformers).
        """
        text_lower = text.lower()

        # Bullish keywords
        bullish_kw = [
            "surge", "rally", "strong", "bullish", "gains", "upside",
            "growth", "beat", "exceeds", "expansion", "recovery"
        ]

        # Bearish keywords
        bearish_kw = [
            "crash", "fall", "weakness", "bearish", "loss", "downside",
            "decline", "miss", "contraction", "recession", "weakness"
        ]

        bullish_count = sum(1 for kw in bullish_kw if kw in text_lower)
        bearish_count = sum(1 for kw in bearish_kw if kw in text_lower)

        if bullish_count > bearish_count:
            return "bullish"
        elif bearish_count > bullish_count:
            return "bearish"
        else:
            return "neutral"

    @staticmethod
    def _calculate_weighted_sentiment(articles: List[NewsArticle]) -> float:
        """
        Calculate weighted average sentiment score.
        
        Returns: 0.0 (very bearish) to 1.0 (very bullish)
        """
        if not articles:
            return 0.5

        # Weight recent articles more heavily
        now = time.time()
        weighted_sum = 0.0
        total_weight = 0.0

        for article in articles:
            age_seconds = now - article.published_at_unix
            # Decay weight exponentially: recent=1.0, 1hr old=0.5, 4hr old=0.1
            weight = max(0.01, 2.0 ** (-age_seconds / 3600.0))
            weighted_sum += article.sentiment_score * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 0.5

    # ========================================================================
    # Risk Score Calculation
    # ========================================================================

    async def _compute_all_risk_scores(self) -> None:
        """
        Compute final macro risk scores for all symbols.
        
        Formula:
            risk_score = base_score + event_adjustment + sentiment_adjustment
        """
        with self._cache_lock:
            for symbol, snapshot in self._snapshot_cache.items():
                risk_score = DEFAULT_MACRO_RISK_SCORE

                # Adjustment 1: High-impact upcoming event
                if snapshot.event_minutes_until_high_impact is not None:
                    minutes_until = snapshot.event_minutes_until_high_impact

                    if minutes_until < 5:
                        # Imminent event: high risk
                        risk_score = 8.0
                    elif minutes_until < 15:
                        # Very close: elevated risk
                        risk_score = 6.0
                    elif minutes_until < self.high_impact_event_window_minutes:
                        # Within window: moderate risk increase
                        risk_score = 4.5

                # Adjustment 2: News sentiment
                sentiment_score = snapshot.news_sentiment_score
                if sentiment_score < 0.3:
                    # Very bearish
                    sentiment_adjustment = 1.5
                elif sentiment_score < 0.45:
                    # Bearish
                    sentiment_adjustment = 0.8
                elif sentiment_score > 0.7:
                    # Very bullish - reduces risk
                    sentiment_adjustment = -0.5
                elif sentiment_score > 0.55:
                    # Bullish
                    sentiment_adjustment = -0.2
                else:
                    # Neutral
                    sentiment_adjustment = 0.0

                risk_score += sentiment_adjustment

                # Clamp to valid range
                risk_score = max(MIN_MACRO_RISK_SCORE, min(MAX_MACRO_RISK_SCORE, risk_score))

                # Convert risk_score to macro_risk_cache penalty (0.0-0.4)
                # Map 0-10 scale to 0-0.4 penalty scale
                penalty = (risk_score / MAX_MACRO_RISK_SCORE) * 0.4

                # Generate reason string
                reason_parts = []
                if snapshot.event_minutes_until_high_impact is not None:
                    reason_parts.append(
                        f"High-impact event in {snapshot.event_minutes_until_high_impact}min"
                    )
                if snapshot.news_sentiment_score < 0.4:
                    reason_parts.append("Bearish sentiment")
                elif snapshot.news_sentiment_score > 0.6:
                    reason_parts.append("Bullish sentiment")

                snapshot.risk_score = risk_score
                snapshot.risk_reason = " | ".join(reason_parts) if reason_parts else "Normal_Macro_Outlook"
                snapshot.data_freshness_ok = True

    def _push_to_macro_risk_cache(self) -> None:
        """
        Update macro_risk_cache with computed risk scores.
        
        This is the bridge between FinnhubMacroManager and the main bot's
        macro_risk_cache (from llm_macro_monitor).
        """
        if self.macro_risk_cache is None:
            return

        try:
            penalties: Dict[str, float] = {}
            reasons: Dict[str, str] = {}

            with self._cache_lock:
                for symbol, snapshot in self._snapshot_cache.items():
                    # Convert risk_score (0-10) to penalty (0-0.4)
                    penalty = (snapshot.risk_score / MAX_MACRO_RISK_SCORE) * 0.4
                    penalties[symbol] = penalty
                    reasons[symbol] = snapshot.risk_reason

            # Push to cache
            self.macro_risk_cache.update(
                penalties,
                source="finnhub",
                reasons=reasons,
                replace=False,  # Merge with existing risks
            )

            logger.debug(
                "[FINNHUB_CACHE_UPDATE] Updated macro_risk_cache with %d symbols",
                len(penalties),
            )

        except Exception as e:
            logger.warning(
                "[FINNHUB_CACHE_UPDATE_ERROR] Failed to update macro_risk_cache: %s",
                str(e)[:100],
            )

    # ========================================================================
    # Diagnostics & Logging
    # ========================================================================

    def _log_diagnostics(self) -> None:
        """Log diagnostic information about macro state."""
        try:
            with self._cache_lock:
                for symbol, snapshot in self._snapshot_cache.items():
                    sentiment_desc = "NEUTRAL"
                    if snapshot.news_sentiment_score < 0.4:
                        sentiment_desc = "BEARISH"
                    elif snapshot.news_sentiment_score > 0.6:
                        sentiment_desc = "BULLISH"

                    event_info = ""
                    if snapshot.event_minutes_until_high_impact is not None:
                        event_info = (
                            f" | Event in {snapshot.event_minutes_until_high_impact}min"
                        )

                    logger.info(
                        "[MACRO_MONITOR] Finnhub sentiment for %s: %s | Risk: %.1f/10 | Freshness: %s%s",
                        symbol,
                        sentiment_desc,
                        snapshot.risk_score,
                        "OK" if snapshot.data_freshness_ok else "STALE",
                        event_info,
                    )
        except Exception as e:
            logger.debug("[FINNHUB_DIAG_ERROR] Error logging diagnostics: %s", str(e)[:50])

    # ========================================================================
    # ✅ NEW: Thread-Liveness Monitoring & Restart Mechanism
    # ========================================================================

    def is_background_task_alive(self) -> bool:
        """
        Check if the background monitoring task is still running.
        
        Returns:
            True if task is running, False if task is None, done, or cancelled
            
        Used by health monitor to detect silent task deaths.
        """
        if self._task is None:
            return False
        return not self._task.done()

    def get_heartbeat_age_seconds(self) -> float:
        """
        Get how many seconds ago the last successful refresh occurred.
        
        Returns:
            Age in seconds. High values (>300s) indicate potential hang/crash.
            
        Used by health monitor to trigger restarts if age exceeds threshold.
        """
        age = (datetime.now(timezone.utc) - self._last_successful_refresh).total_seconds()
        return age

    async def async_attempt_restart(self) -> bool:
        """
        Attempt to restart the background monitoring task if it's dead.
        
        Returns:
            True if restart succeeded, False if already running or restart failed
            
        Used by MacroHealthMonitor when detecting stale data and task is dead.
        """
        if self.is_background_task_alive():
            logger.debug("[FINNHUB_RESTART] Task is still alive, no restart needed")
            return True

        try:
            logger.warning(
                "[FINNHUB_RESTART] Background task is dead (heartbeat age: %.1fs). Attempting restart...",
                self.get_heartbeat_age_seconds(),
            )
            # Reset state for restart
            self._consecutive_failures = 0
            self._fallback_mode_active = False
            self._stop_event.clear()
            
            # Create new task
            self._task = asyncio.create_task(
                self._background_monitor_loop(), name="finnhub-macro-monitor-restarted"
            )
            logger.warning("[FINNHUB_RESTART] ✅ Background task restarted successfully")
            return True
        except Exception as e:
            logger.error(
                "[FINNHUB_RESTART] ❌ Failed to restart background task: %s",
                str(e)[:100],
            )
            return False

    # ========================================================================
    # PERFORMANCE-CRITICAL: Main Loop Read Methods (ZERO Blocking)
    # ========================================================================

    def get_latest_snapshot(self, symbol: str) -> MacroRiskSnapshot:
        """
        Get current macro risk snapshot for a symbol (INSTANT, non-blocking).
        
        Called from main 10s MT5 pulse loop - NEVER blocks. Reads from local cache only.
        This is the main entry point for the trading pulse to access macro data.
        
        Returns:
            MacroRiskSnapshot with cached risk data (< 1ms latency)
        """
        with self._cache_lock:
            return self._snapshot_cache.get(symbol, MacroRiskSnapshot(symbol=symbol))

    def get_llm_payload_json(self) -> str:
        """
        Generate minified JSON payload for LLM governance (INSTANT).
        
        Solves LLM timeout issue by pre-computing clean JSON in background:
        - Before: Raw internet text -> LLM processes 5000ms
        - After: Structured JSON -> LLM processes <1000ms
        
        This payload is built continuously in background and served instantly from cache.
        No API calls during main pulse - pure data formatting.
        
        Returns:
            Minified JSON string with essential macro data only (goal: <1000ms LLM parse)
            
        Example output:
            {
              "ev": {"EUR/USD": {"risk": 7.5, "reason": "High-impact event in 15min"},
                     "GBP/USD": {"risk": 3.2, "reason": "Neutral"}},
              "ts": 1713095400,
              "src": "finnhub"
            }
        """
        try:
            with self._cache_lock:
                # Minimal JSON structure for LLM (<100 tokens)
                payload = {
                    "ev": {},  # events
                    "ts": int(time.time()),
                    "src": "finnhub"
                }
                
                # Only include symbols with non-default risk
                for symbol, snapshot in self._snapshot_cache.items():
                    if snapshot.data_freshness_ok:
                        payload["ev"][symbol] = {
                            "risk": round(snapshot.risk_score, 1),
                            "reason": snapshot.risk_reason,
                        }
                
                # Return minified JSON (no whitespace, minimal tokens)
                return json.dumps(payload, separators=(',', ':'))
        except Exception as e:
            logger.warning("[FINNHUB_LLM_JSON_ERROR] Error building LLM payload: %s", str(e)[:50])
            return json.dumps({"ev": {}, "ts": int(time.time()), "src": "finnhub", "error": "fallback"}, 
                            separators=(',', ':'))

    def is_high_impact_event_imminent(self, symbol: str, within_minutes: int = 30) -> bool:
        """
        Check if a high-impact economic event is imminent for a symbol (< 1ms).
        
        Used for MACRO_RISK_AUDIT: decides if we should trigger defensive mode.
        
        Args:
            symbol: Trading symbol (e.g., "EUR/USD")
            within_minutes: Threshold window (default: 30 min)
        
        Returns:
            True if high-impact event is within the window, False otherwise
        """
        with self._cache_lock:
            snapshot = self._snapshot_cache.get(symbol.replace("/", "").upper())
            if not snapshot or not snapshot.data_freshness_ok:
                return False
            
            if snapshot.event_minutes_until_high_impact is None:
                return False
            
            return snapshot.event_minutes_until_high_impact <= within_minutes

    def should_enter_defensive_mode(self, symbol: str) -> Tuple[bool, Optional[str]]:
        """
        Determine if we should enter defensive mode for a symbol (< 1ms).
        
        Returns:
            (should_be_defensive, reason) tuple
            Example: (True, "NFP event in 15 minutes - halt new entries, tighten stops")
        """
        with self._cache_lock:
            symbol_key = symbol.replace("/", "").upper()
            snapshot = self._snapshot_cache.get(symbol_key)
            
            if not snapshot or not snapshot.data_freshness_ok:
                return False, None
            
            # Rule 1: High-impact event within 30 minutes
            if snapshot.event_minutes_until_high_impact is not None:
                if snapshot.event_minutes_until_high_impact <= 30:
                    return True, (
                        f"Defensive: {snapshot.risk_reason} | "
                        f"Event in {snapshot.event_minutes_until_high_impact} min | "
                        f"Risk: {snapshot.risk_score:.1f}/10"
                    )
            
            # Rule 2: Very high risk score (>7/10)
            if snapshot.risk_score > 7.0:
                return True, f"Defensive: Risk level critical ({snapshot.risk_score:.1f}/10) | {snapshot.risk_reason}"
            
            # Rule 3: Bearish sentiment + high macro risk
            if snapshot.news_sentiment_score < 0.35 and snapshot.risk_score > 5.0:
                return True, f"Defensive: Bearish sentiment + high macro risk"
            
            return False, None

    def get_snapshot(self, symbol: str) -> MacroRiskSnapshot:
        """Get current macro risk snapshot for a symbol."""
        with self._cache_lock:
            return self._snapshot_cache.get(symbol, MacroRiskSnapshot(symbol=symbol))

    @staticmethod
    def _safe_float(val: Any) -> Optional[float]:
        """Safely convert value to float."""
        try:
            if val is None:
                return None
            return float(val)
        except (ValueError, TypeError):
            return None


# ============================================================================
# Convenience Functions
# ============================================================================


def create_finnhub_manager(
    api_key: Optional[str] = None,
    symbols: Optional[List[str]] = None,
    macro_risk_cache: Optional[Any] = None,
) -> Optional[FinnhubMacroManager]:
    """
    Factory function to create FinnhubMacroManager with auto-configuration.
    
    Args:
        api_key: Finnhub API key (defaults to FINNHUB_API_KEY env var)
        symbols: Symbols to monitor (defaults to common FX pairs)
        macro_risk_cache: Reference to macro_risk_cache instance
    
    Returns:
        FinnhubMacroManager instance or None if API key not available
    """
    api_key = api_key or os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.warning(
            "[FINNHUB_FACTORY] No API key provided. Set FINNHUB_API_KEY environment variable."
        )
        return None

    symbols = symbols or [
        "EUR/USD",
        "GBP/USD",
        "USD/JPY",
        "USD/CHF",
        "AUD/USD",
        "USD/CAD",
        "NZD/USD",
    ]

    return FinnhubMacroManager(
        api_key=api_key,
        symbols=symbols,
        macro_risk_cache=macro_risk_cache,
        enable_economic_calendar=True,
        enable_sentiment_analysis=True,
    )

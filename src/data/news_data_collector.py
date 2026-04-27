"""News data collector implementation"""

import asyncio
import json
import logging
import os
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Any, Optional
import aiohttp
from src.interfaces import DataCollector
from src.exceptions import DataValidationError, APIError
from src.config import Config


logger = logging.getLogger(__name__)


class NewsArticle:
    """News article data structure"""

    def __init__(self, title: str, content: str, source: str,
                 published_at: datetime, url: str,
                 symbols: Optional[List[str]] = None):
        self.title = title
        self.content = content
        self.source = source
        self.published_at = published_at
        self.url = url
        self.symbols = symbols or []
        self.processed_content = ""
        
    @property
    def timestamp(self):
        """Alias for published_at for historical compatibility"""
        return self.published_at

    def __getitem__(self, key):
        """Dict-like access for compatibility"""
        if key == 'timestamp':
            return self.published_at
        return getattr(self, key)
        
    def __contains__(self, key):
        """Dict-like membership check for compatibility"""
        return hasattr(self, key) or key == 'timestamp'
        
    def validate(self) -> None:
        """Validate news article data"""
        if not self.title or not self.title.strip():
            raise DataValidationError(
                "Article title cannot be empty",
                error_code="EMPTY_TITLE",
                context={"title": self.title}
            )
        
        if not self.content or not self.content.strip():
            raise DataValidationError(
                "Article content cannot be empty",
                error_code="EMPTY_CONTENT",
                context={"content": self.content}
            )
        
        if not self.source or not self.source.strip():
            raise DataValidationError(
                "Article source cannot be empty",
                error_code="EMPTY_SOURCE",
                context={"source": self.source}
            )
        
        if self.published_at.tzinfo is None:
            if self.published_at > datetime.now():
                raise DataValidationError(
                    f"Published date cannot be in the future: {self.published_at}",
                    error_code="FUTURE_TIMESTAMP",
                    context={"published_at": self.published_at}
                )
        else:
            if self.published_at > datetime.now(timezone.utc):
                raise DataValidationError(
                    f"Published date cannot be in the future: {self.published_at}",
                    error_code="FUTURE_TIMESTAMP",
                    context={"published_at": self.published_at}
                )
        
        if not self.url or not self.url.strip():
            raise DataValidationError(
                "Article URL cannot be empty",
                error_code="EMPTY_URL",
                context={"url": self.url}
            )


class NewsDataCollector(DataCollector):
    """Collects financial news data from various APIs"""
    GENERAL_FOREX_CACHE_SYMBOL = "general_forex"
    GENERAL_FOREX_REFRESH_MINUTES = 60.0
    CACHE_FILE_PATH = Path("data") / "news_cache.json"
    _shared_news_cache: Dict[str, List[NewsArticle]] = {}
    _shared_news_timestamp_cache: Dict[str, datetime] = {}
    _shared_fetch_semaphore: Optional[asyncio.Semaphore] = None
    _persistent_cache_loaded: bool = False
    
    def __init__(self, config: Config):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        cache_ttl_minutes = max(int(os.environ.get("NEWS_CACHE_TTL_MINUTES", "60") or 60), 15)
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self.news_cache_ttl_seconds = int(self.cache_ttl.total_seconds())
        # Persistent process-level caches shared across collector instances.
        # This survives per-cycle object churn and is not part of amnesia wipes.
        self.news_cache = NewsDataCollector._shared_news_cache
        self.news_timestamp_cache = NewsDataCollector._shared_news_timestamp_cache
        # Backwards-compatible aliases used elsewhere in this module.
        self.cache = self.news_cache
        self.last_fetch_time = self.news_timestamp_cache
        self.max_fetch_retries = 3
        self.fetch_retry_backoff_seconds = 30
        self.force_refresh_age_limit = self.cache_ttl
        self.news_silent_fail_ttl = timedelta(minutes=10)
        self._last_silent_fail_notice: Dict[str, datetime] = {}
        self._refresh_jitter_minutes = random.uniform(0.0, 7.5)
        news_cfg = getattr(self.config, "news", None)
        configured_provider = str(getattr(news_cfg, "provider", "") or "").strip().lower()
        env_api_key = str(os.environ.get("NEWS_API_KEY", "") or "").strip()
        configured_api_key = str(getattr(news_cfg, "api_key", "") or "").strip()
        self.api_key = configured_api_key or env_api_key
        self.provider = configured_provider or "mock"
        self.mock_mode = bool(getattr(news_cfg, "mock_mode", False))
        self._load_persistent_cache()
        if self.provider in {"unset", "none", "disabled", ""}:
            self.provider = "mock"
        if self.provider == "mock" or not self.api_key:
            self.provider = "mock"
            self.mock_mode = True
        # Financial news keywords for filtering
        self.forex_keywords = [
            'forex', 'currency', 'exchange rate', 'central bank', 'fed',
            'ecb', 'boe', 'interest rate', 'monetary policy', 'inflation',
            'gdp', 'employment', 'trade war', 'brexit', 'dollar', 'euro',
            'pound', 'yen', 'swiss franc'
        ]

        # Currency pair patterns (flexible to match EUR/USD or EURUSD)
        self.currency_patterns = [
            r'EUR/?USD', r'GBP/?USD', r'USD/?JPY', r'USD/?CHF', r'AUD/?USD',
            r'USD/?CAD', r'NZD/?USD', r'EUR/?GBP', r'EUR/?JPY', r'GBP/?JPY'
        ]

    def _news_disabled_or_mocked(self) -> bool:
        """Return True when news collection should be a non-blocking no-op."""
        news_cfg = getattr(self.config, "news", None)
        enabled = getattr(news_cfg, "enabled", None)
        mock_mode = bool(getattr(news_cfg, "mock_mode", False) or getattr(self, "mock_mode", False) or self.provider == "mock")
        disabled = bool(getattr(news_cfg, "disabled", False) or getattr(self, "disabled", False))
        return enabled is False or disabled or mock_mode

    def requires_live_data(self) -> bool:
        news_cfg = getattr(self.config, "news", None)
        return bool(getattr(news_cfg, "require_live_data", False))

    def is_live_feed_ready(self) -> bool:
        news_cfg = getattr(self.config, "news", None)
        provider = self._resolve_provider()
        api_key = str(getattr(news_cfg, "api_key", "") or "").strip()
        if self._news_disabled_or_mocked():
            return False
        if provider in {"", "mock"}:
            return False
        if provider == "newsapi" and not api_key:
            return False
        return True

    def should_pause_for_live_news(self) -> bool:
        return bool(self.requires_live_data() and not self._news_disabled_or_mocked())

    def _resolve_provider(self) -> str:
        if self.provider:
            return self.provider
        if self._news_disabled_or_mocked():
            return "mock"
        return "newsapi"

    def _should_silent_fail(self, exc: Exception) -> bool:
        if self.requires_live_data():
            return False
        if self._resolve_provider() == "mock":
            return False
        error_text = str(exc or "").upper()
        if isinstance(exc, APIError):
            code = str(getattr(exc, "error_code", "") or "").upper()
            if code in {
                "NEWS_API_HTTP_ERROR",
                "NEWS_PROVIDER_UNSUPPORTED",
                "NEWS_FETCH_FAILED",
                "NEWS_FEED_EMPTY",
            }:
                return True
        return any(
            token in error_text
            for token in (
                "NEWSAPI KEY MISSING",
                "UNSUPPORTED LIVE NEWS PROVIDER",
                "FAILED TO FETCH NEWS DATA",
                "NO LIVE NEWS ARTICLES MATCHED",
            )
        )

    def _log_silent_fail_once(self, symbol: str, reason: str) -> None:
        now = datetime.now(timezone.utc)
        last_logged_at = self._last_silent_fail_notice.get(symbol)
        if last_logged_at and (now - last_logged_at) < self.news_silent_fail_ttl:
            return
        self._last_silent_fail_notice[symbol] = now
        logger.warning(
            "[NEWS_SILENT_FAILOVER] %s | %s. Falling back to technical-only macro mode without retry spam.",
            symbol,
            reason,
        )

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.api_timeout)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def collect_data(self, symbols: List[str],
                          timeframe: str = "1h",
                          force_refresh: bool = False,
                          allow_live_fetch: bool = False) -> Dict[str, Any]:
        """
        Collect news data for given symbols

        Args:
            symbols: List of currency pairs to collect news for
            timeframe: Time range for news collection (1h, 4h, 1d)

        Returns:
            Dictionary with symbol as key and list of NewsArticle as value
        """
        if self.requires_live_data() and not self.is_live_feed_ready():
            raise APIError(
                "LIVE_NEWS_REQUIRED: provider/api key missing or mock mode still enabled",
                error_code="LIVE_NEWS_REQUIRED",
                context={"symbols": symbols},
            )
        if self._news_disabled_or_mocked():
            return {symbol: [] for symbol in symbols}

        logger.debug(
            "[NEWS_COLLECT_CALL] symbols=%s timeframe=%s force_refresh=%s allow_live_fetch=%s",
            symbols,
            timeframe,
            force_refresh,
            allow_live_fetch,
        )

        if not symbols:
            raise DataValidationError(
                "Symbols list cannot be empty",
                error_code="EMPTY_SYMBOLS",
                context={"symbols": symbols}
            )

        results = {}
        if NewsDataCollector._shared_fetch_semaphore is None:
            NewsDataCollector._shared_fetch_semaphore = asyncio.Semaphore(1)
        fetch_gate = NewsDataCollector._shared_fetch_semaphore

        async with fetch_gate:
            if self._should_use_shared_general_cache():
                return await self._collect_shared_forex_news(
                    symbols,
                    timeframe,
                    force_refresh,
                    allow_live_fetch=allow_live_fetch,
                )
            for idx, symbol in enumerate(symbols):
                try:
                    if not allow_live_fetch:
                        cached_articles = self._get_cached_articles(symbol, timeframe)
                        if cached_articles is not None:
                            results[symbol] = cached_articles
                        else:
                            results[symbol] = list(self.cache.get(self._cache_key(symbol, timeframe), []) or [])
                        continue
                    # Strict sequential flow: complete symbol A before starting symbol B.
                    symbol_force_refresh = bool(
                        force_refresh or self.should_force_refresh(symbol, timeframe)
                    )
                    cached_articles = None if symbol_force_refresh else self._get_cached_articles(symbol, timeframe)
                    if cached_articles is not None:
                        logger.debug(f"Using cached news data for {symbol}")
                        results[symbol] = cached_articles
                        continue

                    if symbol_force_refresh:
                        # FIX #2: Only log cache staleness if cache actually exists and aged
                        age_minutes = self.get_data_age_minutes(symbol, timeframe)
                        if age_minutes is not None and age_minutes > 0.0:
                            # Cache exists and is stale
                            logger.warning(
                                "[NEWS_FORCE_REFRESH] %s | Cache age %.1fm exceeded 15m. Triggering mandatory refresh.",
                                symbol,
                                float(age_minutes),
                            )
                        elif age_minutes is None:
                            # No cache exists, fresh fetch needed
                            logger.debug(
                                "[NEWS_CACHE_MISSING] %s | No cached data available. Fetching fresh news.",
                                symbol,
                            )
                    logger.info(f"[NEWS_FETCH] Fetching fresh news for {symbol} (timeframe={timeframe})")
                    articles = await self._fetch_news_data_with_retry(symbol, timeframe)
                    if articles:
                        processed_articles = self._process_articles(articles, symbol)
                        self._store_fetch_result(symbol, timeframe, processed_articles)
                        results[symbol] = processed_articles
                        logger.debug(f"Fetched {len(processed_articles)} articles for {symbol}")
                    else:
                        logger.warning(f"No news articles found for {symbol}")
                        self._store_fetch_result(symbol, timeframe, [])
                        results[symbol] = []

                except Exception as e:
                    logger.error(f"Error collecting news data for {symbol}: {e}")
                    fallback_articles = self._get_best_effort_cached_articles(symbol, timeframe)
                    results[symbol] = fallback_articles
                finally:
                    if idx < len(symbols) - 1:
                        await asyncio.sleep(0.5)

        return results

    async def _collect_shared_forex_news(
        self,
        symbols: List[str],
        timeframe: str,
        force_refresh: bool,
        *,
        allow_live_fetch: bool,
    ) -> Dict[str, List[NewsArticle]]:
        shared_symbol = self.GENERAL_FOREX_CACHE_SYMBOL
        shared_age_minutes = self.get_data_age_minutes(shared_symbol, timeframe)
        if (
            shared_age_minutes is not None
            and shared_age_minutes < (self.GENERAL_FOREX_REFRESH_MINUTES + self._refresh_jitter_minutes)
        ):
            cached_articles = self._get_cached_articles(shared_symbol, timeframe)
            if cached_articles is not None:
                return self._map_shared_articles_to_symbols(symbols, cached_articles, shared_symbol)

        shared_force_refresh = bool(force_refresh or self.should_force_refresh(shared_symbol, timeframe))
        cached_articles = None if shared_force_refresh else self._get_cached_articles(shared_symbol, timeframe)

        if cached_articles is None:
            if not allow_live_fetch:
                preferred_cache_key = self._cache_key(shared_symbol, timeframe)
                stale_articles = list(self.cache.get(preferred_cache_key, []) or [])
                if stale_articles:
                    logger.info(
                        "[NEWS_CACHE_ONLY_MODE] Reusing cached %s news for %d symbols without live API access.",
                        shared_symbol,
                        len(symbols),
                    )
                    return self._map_shared_articles_to_symbols(symbols, stale_articles, shared_symbol)
                fallback_articles = self._get_best_effort_cached_articles(shared_symbol, timeframe)
                if fallback_articles:
                    fallback_key = next(
                        (
                            cache_key
                            for cache_key, articles in self.cache.items()
                            if list(articles or []) == list(fallback_articles or [])
                        ),
                        "unknown",
                    )
                    logger.warning(
                        "[NEWS_CACHE_ONLY_MODE] Preferred %s cache missing. Reusing fallback cache key %s for %d symbols.",
                        shared_symbol,
                        fallback_key,
                        len(symbols),
                    )
                    return self._map_shared_articles_to_symbols(symbols, fallback_articles, shared_symbol)
                logger.info(
                    "[NEWS_CACHE_ONLY_MODE] No cached %s news available. Returning empty set without API call.",
                    shared_symbol,
                )
                return {symbol: [] for symbol in symbols}
            if self._newsapi_backoff_active():
                cached_articles = list(self.cache.get(self._cache_key(shared_symbol, timeframe), []) or [])
                if cached_articles:
                    logger.warning(
                        "[NEWS_SHARED_CACHE_BACKOFF] NewsAPI backoff active. Reusing stale %s cache for %d symbols.",
                        shared_symbol,
                        len(symbols),
                    )
                else:
                    fallback = self._get_best_effort_cached_articles(shared_symbol, timeframe)
                    logger.warning(
                        "[NEWS_SHARED_CACHE_BACKOFF] NewsAPI backoff active with no in-memory %s cache. Falling back to persisted cache.",
                        shared_symbol,
                    )
                    return self._map_shared_articles_to_symbols(symbols, fallback, shared_symbol)
            else:
                age_minutes = self.get_data_age_minutes(shared_symbol, timeframe)
                if shared_force_refresh and age_minutes is not None and age_minutes > 0.0:
                    logger.warning(
                        "[NEWS_FORCE_REFRESH] %s | Cache age %.1fm exceeded %.1fm. Refreshing shared forex cache once for %d symbols.",
                        shared_symbol,
                        float(age_minutes),
                        self.cache_ttl.total_seconds() / 60.0,
                        len(symbols),
                    )
                elif shared_force_refresh and age_minutes is None:
                    logger.debug(
                        "[NEWS_CACHE_MISSING] %s | No shared forex cache available. Fetching once for %d symbols.",
                        shared_symbol,
                        len(symbols),
                    )
                logger.info(
                    "[NEWS_FETCH_SHARED] Fetching shared forex news once for %d symbols (timeframe=%s)",
                    len(symbols),
                    timeframe,
                )
                try:
                    cached_articles = await self._fetch_news_data_with_retry(shared_symbol, timeframe)
                    self._store_fetch_result(shared_symbol, timeframe, cached_articles)
                except Exception as exc:
                    logger.warning(
                        "[NEWS_FETCH_SHARED_FAILOVER] Shared fetch failed: %s | Reusing most recent persisted cache.",
                        exc,
                    )
                    cached_articles = self._get_best_effort_cached_articles(shared_symbol, timeframe)
        return self._map_shared_articles_to_symbols(symbols, cached_articles or [], shared_symbol)

    def _map_shared_articles_to_symbols(
        self,
        symbols: List[str],
        articles: List[NewsArticle],
        shared_symbol: str,
    ) -> Dict[str, List[NewsArticle]]:
        results: Dict[str, List[NewsArticle]] = {}
        shared_articles = list(articles or [])
        for symbol in symbols:
            processed_articles = self._process_articles(shared_articles, symbol)
            results[symbol] = processed_articles
            logger.debug(
                "[NEWS_SHARED_CACHE_HIT] %s | Derived %d relevant articles from %s cache",
                symbol,
                len(processed_articles),
                shared_symbol,
            )
        return results

    def _store_fetch_result(self, symbol: str, timeframe: str, articles: List[NewsArticle]) -> None:
        cache_key = self._cache_key(symbol, timeframe)
        self.cache[cache_key] = articles
        self.last_fetch_time[cache_key] = datetime.now(timezone.utc)
        self._persist_cache_to_disk()

    async def _fetch_news_data_with_retry(self, symbol: str, timeframe: str) -> List[NewsArticle]:
        if self.requires_live_data() and not self.is_live_feed_ready():
            raise APIError(
                "LIVE_NEWS_REQUIRED: provider/api key missing or mock mode still enabled",
                error_code="LIVE_NEWS_REQUIRED",
                context={"symbol": symbol},
            )
        if self._news_disabled_or_mocked():
            return []
        last_error: Optional[Exception] = None
        for attempt in range(1, self.max_fetch_retries + 1):
            try:
                return await self._fetch_news_data(symbol, timeframe)
            except Exception as exc:
                if self._should_silent_fail(exc):
                    self._log_silent_fail_once(symbol, str(exc))
                    return []
                last_error = exc
                if attempt >= self.max_fetch_retries:
                    break
                logger.warning(
                    "[NEWS_FETCH_RETRY] %s | Attempt %d/%d failed: %s. Retrying in %ss.",
                    symbol,
                    attempt,
                    self.max_fetch_retries,
                    exc,
                    self.fetch_retry_backoff_seconds,
                )
                await asyncio.sleep(self.fetch_retry_backoff_seconds)

        if last_error is not None:
            fallback_articles = self._get_best_effort_cached_articles(symbol, timeframe)
            if fallback_articles:
                logger.warning(
                    "[NEWS_FETCH_FALLBACK] %s | Returning %d stale cached articles after fetch failure.",
                    symbol,
                    len(fallback_articles),
                )
                return fallback_articles
            raise last_error
        return []
    
    async def validate_data(self, data: Dict[str, Any]) -> bool:
        """
        Validate collected news data
        
        Args:
            data: Dictionary of news data to validate
            
        Returns:
            True if all data is valid, False otherwise
        """
        if not data:
            logger.warning("[NEWS_FEED_EMPTY] No news data to validate. Decision-making may be compromised.")
            # User requirement: Ensure decision-making does not rely on empty feeds.
            # Returning False here forces the consumer to handle the 'no data' case as an error/wait state.
            return False
            
        # Check for empty article lists per symbol
        has_valid_data = False
        for symbol, articles in data.items():
            if articles:
                has_valid_data = True
                break
        
        if not has_valid_data:
            logger.warning("[NEWS_FEED_EMPTY] All symbols returned empty news lists.")
            return False
        
        for symbol, articles in data.items():
            try:
                if not isinstance(articles, list):
                    logger.error(f"Invalid articles type for {symbol}: {type(articles)}")
                    return False
                
                for i, article in enumerate(articles):
                    if not isinstance(article, NewsArticle):
                        logger.error(f"Invalid article type at index {i} for {symbol}: {type(article)}")
                        return False
                    
                    # Validate each article
                    article.validate()
                    
                    # Check if article is too old
                    now = datetime.now(timezone.utc) if article.published_at.tzinfo else datetime.now()
                    age = now - article.published_at
                    if age > timedelta(days=7):  # Articles older than 7 days
                        logger.warning(f"Article too old for {symbol}: {article.published_at}")
                        return False
                        
            except DataValidationError as e:
                logger.error(f"Validation error for {symbol}: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected validation error for {symbol}: {e}")
                return False
        
        logger.info(f"Successfully validated news data for {len(data)} symbols")
        return True
    
    async def _fetch_news_data(self, symbol: str, timeframe: str) -> List[NewsArticle]:
        """
        Fetch news data from various sources
        
        Args:
            symbol: Currency pair symbol
            timeframe: Time range for news
            
        Returns:
            List of NewsArticle objects
        """
        if self.requires_live_data() and not self.is_live_feed_ready():
            raise APIError(
                "LIVE_NEWS_REQUIRED: provider/api key missing or mock mode still enabled",
                error_code="LIVE_NEWS_REQUIRED",
                context={"symbol": symbol},
            )
        if self._news_disabled_or_mocked():
            return []

        articles = []
        
        # Calculate time range based on timeframe
        time_range = self._get_time_range(timeframe)
        
        try:
            provider = self._resolve_provider()
            if provider == "newsapi":
                articles.extend(await self._fetch_newsapi_news(symbol, time_range))
            elif provider == "mock":
                logger.debug("[NEWS_MOCK_MODE] %s | Mock provider active. Returning empty live-news set.", symbol)
                return []
            else:
                raise APIError(
                    f"Unsupported live news provider: {provider or 'unset'}",
                    error_code="NEWS_PROVIDER_UNSUPPORTED",
                    context={"symbol": symbol, "provider": provider},
                )
            
        except Exception as e:
            if self._should_silent_fail(e):
                logger.warning(f"News query degraded for {symbol}: {e}")
            else:
                logger.error(f"Error fetching news data for {symbol}: {e}")
            raise APIError(
                f"Failed to fetch news data for {symbol}: {e}",
                error_code="NEWS_FETCH_FAILED",
                context={"symbol": symbol, "error": str(e)}
            )
        
        return articles

    async def _fetch_newsapi_news(self, symbol: str, time_range: timedelta) -> List[NewsArticle]:
        news_cfg = getattr(self.config, "news", None)
        api_key = str(getattr(news_cfg, "api_key", "") or "").strip()
        if not api_key:
            if not self.requires_live_data():
                self._log_silent_fail_once(symbol, "NEWSAPI key missing")
                return []
            raise APIError(
                "NEWSAPI key missing",
                error_code="NEWS_API_KEY_MISSING",
                context={"symbol": symbol},
            )

        if self._newsapi_backoff_active():
            raise APIError(
                "NewsAPI backoff still active after a previous 429 response",
                error_code="NEWS_API_RATE_LIMITED",
                context={"symbol": symbol},
            )

        from_time = (datetime.now(timezone.utc) - time_range).isoformat()

        session_created = False
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.api_timeout))
            session_created = True

        try:
            articles: List[NewsArticle] = []
            for query in self._build_newsapi_queries(symbol):
                params = {
                    "q": query,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "pageSize": 25,
                    "from": from_time,
                    "apiKey": api_key,
                }
                async with self.session.get("https://newsapi.org/v2/everything", params=params) as response:
                    # ISSUE #3 FIX: Handle NewsAPI 429 rate limit
                    if response.status == 429:
                        logger.critical(
                            "[NEWSAPI_429_RATE_LIMIT] %s | NewsAPI rate limit exceeded. "
                            "Setting macro_technical_only=True for 4 hours to prevent spam.",
                            symbol,
                        )
                        # Set environment flag to disable news fetching for 4 hours
                        import os
                        # FIX #1: datetime shadowing fix - renamed local variable to avoid module name collision
                        # datetime, timezone, timedelta already imported at top of file (line 7)
                        rate_limit_until_ts = datetime.now(timezone.utc) + timedelta(hours=4)
                        os.environ["MACRO_TECHNICAL_ONLY"] = "1"
                        os.environ["NEWSAPI_429_UNTIL"] = str(int(rate_limit_until_ts.timestamp()))
                        raise APIError(
                            f"NewsAPI rate limit (429). News disabled for 4 hours.",
                            error_code="NEWS_API_RATE_LIMITED",
                            context={"symbol": symbol, "retry_after": "4 hours"},
                        )
                    elif response.status != 200:
                        body = await response.text()
                        raise APIError(
                            f"NewsAPI request failed: status={response.status} body={body[:200]}",
                            error_code="NEWS_API_HTTP_ERROR",
                            context={"symbol": symbol, "query": query},
                        )
                    payload = await response.json()

                articles = self._parse_newsapi_payload(symbol, payload)
                if articles:
                    logger.info(
                        "[NEWS_QUERY_FALLBACK] %s | Using query '%s' | matched=%d",
                        symbol,
                        query,
                        len(articles),
                    )
                    break
        finally:
            if session_created and self.session is not None:
                await self.session.close()
                self.session = None

        if not articles:
            logger.info(
                "[NEWS_QUERY_FALLBACK] %s | No live news articles matched after pair, currency, and forex fallback queries.",
                symbol,
            )
        return articles

    def _build_newsapi_queries(self, symbol: str) -> List[str]:
        if str(symbol or "").strip().lower() == self.GENERAL_FOREX_CACHE_SYMBOL:
            return [
                "forex OR currency OR central bank OR fed OR ecb OR boe OR dollar OR euro OR pound OR yen"
            ]
        clean = str(symbol or "").strip().upper()
        compact = clean.replace("/", "")
        base = compact[:3] if len(compact) >= 3 else compact
        quote = compact[3:6] if len(compact) >= 6 else ""
        candidates = [
            clean.replace("/", " OR "),
            f"({base} OR {quote}) forex" if base and quote else clean,
            f"{base} forex" if base else clean,
            f"{quote} forex" if quote else clean,
            "forex OR currency OR central bank",
        ]
        queries: List[str] = []
        seen = set()
        for candidate in candidates:
            query = str(candidate or "").strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
        return queries

    def _parse_newsapi_payload(self, symbol: str, payload: Dict[str, Any]) -> List[NewsArticle]:
        articles: List[NewsArticle] = []
        use_general_scope = str(symbol or "").strip().lower() == self.GENERAL_FOREX_CACHE_SYMBOL
        for item in payload.get("articles", []) or []:
            title = str(item.get("title", "") or "").strip()
            content = str(item.get("description") or item.get("content") or "").strip()
            url = str(item.get("url", "") or "").strip()
            source_name = str((item.get("source") or {}).get("name", "NewsAPI") or "NewsAPI")
            published_raw = str(item.get("publishedAt", "") or "").strip()
            if not title or not content or not url or not published_raw:
                continue
            if (not use_general_scope) and (not self._matches_symbol_or_forex_theme(symbol, title, content)):
                continue
            try:
                published_at = datetime.fromisoformat(published_raw.replace("Z", "+00:00"))
            except Exception:
                continue
            articles.append(
                NewsArticle(
                    title=title,
                    content=content,
                    source=source_name,
                    published_at=published_at,
                    url=url,
                    symbols=self._extract_currency_pairs(f"{title} {content}") if use_general_scope else [symbol],
                )
            )
        return articles

    def _matches_symbol_or_forex_theme(self, symbol: str, title: str, content: str) -> bool:
        haystack = f"{title} {content}".upper()
        base_symbol = symbol.replace("/", "").upper()
        if base_symbol in haystack or symbol.upper() in haystack:
            return True
        return any(keyword.upper() in haystack for keyword in self.forex_keywords)
    
    async def _fetch_mock_news(self, symbol: str, time_range: timedelta) -> List[NewsArticle]:
        """
        Mock news data fetcher for testing
        
        Args:
            symbol: Currency pair symbol
            time_range: Time range for news
            
        Returns:
            List of mock NewsArticle objects
        """
        if self._news_disabled_or_mocked():
            return []

        # Simulate API delay
        await asyncio.sleep(0.1)
        
        mock_articles = []
        base_currencies = symbol.split('/')
        
        # Generate mock articles based on symbol
        mock_data = [
            {
                "title": f"{symbol} Rises on Central Bank Policy Expectations",
                "content": f"The {symbol} pair gained ground today as investors "
                          f"anticipate policy changes from central banks. "
                          f"Market analysts suggest that recent economic "
                          f"indicators support a bullish outlook for the "
                          f"{base_currencies[0]} against the "
                          f"{base_currencies[1]}.",
                "source": "Financial Times",
                "published_at": datetime.now(timezone.utc) - timedelta(minutes=15),
                "url": f"https://example.com/news/"
                       f"{symbol.lower().replace('/', '-')}-rises-1"
            },
            {
                "title": f"Economic Data Impacts {symbol} Trading",
                "content": f"Recent economic releases have significantly "
                          f"impacted {symbol} trading volumes. The latest GDP "
                          f"figures and employment data suggest continued "
                          f"volatility in the {base_currencies[0]}/"
                          f"{base_currencies[1]} exchange rate.",
                "source": "Reuters",
                "published_at": datetime.now(timezone.utc) - timedelta(minutes=45),
                "url": f"https://example.com/news/"
                       f"{symbol.lower().replace('/', '-')}-economic-data-2"
            },
            {
                "title": f"Technical Analysis: {symbol} Breaks Key Resistance",
                "content": f"Technical analysts report that {symbol} has "
                          f"broken through a key resistance level, suggesting "
                          f"potential for further upward movement. Trading "
                          f"volumes have increased significantly as the pair "
                          f"approaches new highs.",
                "source": "MarketWatch",
                "published_at": datetime.now(timezone.utc) - timedelta(hours=2),
                "url": f"https://example.com/news/"
                       f"{symbol.lower().replace('/', '-')}-technical-analysis-3"
            }
        ]

        for article_data in mock_data:
            # Only include articles within the time range
            published_at = article_data["published_at"]
            if isinstance(published_at, datetime):
                now = datetime.now(timezone.utc) if published_at.tzinfo else datetime.now()
                if now - published_at <= time_range:
                    article = NewsArticle(
                        title=str(article_data["title"]),
                        content=str(article_data["content"]),
                        source=str(article_data["source"]),
                        published_at=published_at,
                        url=str(article_data["url"]),
                        symbols=[symbol]
                    )
                    mock_articles.append(article)
        
        return mock_articles
    
    def _process_articles(self, articles: List[NewsArticle], symbol: str) -> List[NewsArticle]:
        """
        Process and filter articles for relevance
        
        Args:
            articles: List of raw articles
            symbol: Target currency pair
            
        Returns:
            List of processed and filtered articles
        """
        processed_articles = []
        
        for article in articles:
            try:
                working_article = NewsArticle(
                    title=str(article.title),
                    content=str(article.content),
                    source=str(article.source),
                    published_at=article.published_at,
                    url=str(article.url),
                    symbols=list(getattr(article, "symbols", []) or []),
                )
                # Clean and preprocess content
                working_article.processed_content = self._clean_text(working_article.content)
                
                # Check relevance to forex/currency trading
                if self._is_forex_relevant(working_article):
                    # Extract mentioned currency pairs
                    mentioned_pairs = self._extract_currency_pairs(working_article.processed_content)
                    
                    # Normalize symbols for comparison (remove slashes)
                    norm_symbol = symbol.replace('/', '')
                    norm_mentioned = [p.replace('/', '') for p in mentioned_pairs]
                    
                    if norm_symbol in norm_mentioned or not norm_mentioned:
                        working_article.symbols = mentioned_pairs if mentioned_pairs else [symbol]
                        processed_articles.append(working_article)
                        
            except Exception as e:
                logger.warning(f"Error processing article: {e}")
                continue
        
        # Sort by publication date (newest first)
        processed_articles.sort(key=lambda x: x.published_at, reverse=True)
        
        return processed_articles
    
    def _clean_text(self, text: str) -> str:
        """
        Clean and preprocess text content
        
        Args:
            text: Raw text content
            
        Returns:
            Cleaned text
        """
        if not text:
            return ""
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        
        # Remove special characters but keep basic punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\/]', '', text)
        
        return text.strip()
    
    def _is_forex_relevant(self, article: NewsArticle) -> bool:
        """
        Check if article is relevant to forex trading
        
        Args:
            article: NewsArticle to check
            
        Returns:
            True if relevant, False otherwise
        """
        content_lower = (article.title + " " + article.processed_content).lower()
        
        # Check for forex-related keywords
        for keyword in self.forex_keywords:
            if keyword.lower() in content_lower:
                return True
        
        # Check for currency pair mentions
        for pattern in self.currency_patterns:
            if re.search(pattern, content_lower, re.IGNORECASE):
                return True
        
        return False
    
    def _extract_currency_pairs(self, text: str) -> List[str]:
        """
        Extract currency pair mentions from text
        
        Args:
            text: Text to analyze
            
        Returns:
            List of found currency pairs
        """
        found_pairs = []
        
        for pattern in self.currency_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                pair = match.upper()
                if pair not in found_pairs:
                    found_pairs.append(pair)
        
        return found_pairs
    
    def _get_time_range(self, timeframe: str) -> timedelta:
        """
        Convert timeframe string to timedelta
        
        Args:
            timeframe: Timeframe string (1h, 4h, 1d)
            
        Returns:
            Corresponding timedelta
        """
        timeframe_map = {
            "1h": timedelta(hours=1),
            "4h": timedelta(hours=4),
            "1d": timedelta(days=1),
            "1w": timedelta(weeks=1)
        }
        
        return timeframe_map.get(timeframe, timedelta(hours=4))
    
    def _cache_key(self, symbol: str, timeframe: str) -> str:
        if str(symbol or "").strip().lower() == self.GENERAL_FOREX_CACHE_SYMBOL:
            return self.GENERAL_FOREX_CACHE_SYMBOL
        return f"{symbol}|{timeframe}"

    def _legacy_cache_key(self, symbol: str, timeframe: str) -> str:
        return f"{symbol}|{timeframe}"

    def _cache_key_candidates(self, symbol: str, timeframe: str) -> List[str]:
        canonical = self._cache_key(symbol, timeframe)
        if str(symbol or "").strip().lower() == self.GENERAL_FOREX_CACHE_SYMBOL:
            legacy = self._legacy_cache_key(symbol, timeframe)
            if legacy != canonical:
                return [canonical, legacy]
        return [canonical]

    def _should_use_shared_general_cache(self) -> bool:
        return self._resolve_provider() == "newsapi" and not self._news_disabled_or_mocked()

    def _newsapi_backoff_active(self) -> bool:
        until_raw = str(os.environ.get("NEWSAPI_429_UNTIL", "") or "").strip()
        if not until_raw:
            return False
        try:
            backoff_until = datetime.fromtimestamp(int(until_raw), tz=timezone.utc)
        except Exception:
            return False
        return datetime.now(timezone.utc) < backoff_until

    @classmethod
    def get_latest_fetch_time(cls, symbol: str, timeframe: Optional[str] = None) -> Optional[datetime]:
        normalized_symbol = str(symbol or "")
        latest: Optional[datetime] = None
        for cache_key, fetch_time in cls._shared_news_timestamp_cache.items():
            if "|" in cache_key:
                cache_symbol, cache_timeframe = cache_key.split("|", 1)
            else:
                cache_symbol = cache_key
                cache_timeframe = None
            if cache_symbol != normalized_symbol:
                continue
            if timeframe is not None and cache_timeframe not in (None, timeframe):
                continue
            if latest is None or fetch_time > latest:
                latest = fetch_time
        if latest is None and normalized_symbol != cls.GENERAL_FOREX_CACHE_SYMBOL:
            shared_keys = [cls.GENERAL_FOREX_CACHE_SYMBOL]
            if timeframe is not None:
                shared_keys.append(f"{cls.GENERAL_FOREX_CACHE_SYMBOL}|{timeframe}")
            for shared_key in shared_keys:
                latest = cls._shared_news_timestamp_cache.get(shared_key)
                if latest is not None:
                    break
            else:
                for cache_key, fetch_time in cls._shared_news_timestamp_cache.items():
                    if "|" in cache_key:
                        cache_symbol, _ = cache_key.split("|", 1)
                    else:
                        cache_symbol = cache_key
                    if cache_symbol != cls.GENERAL_FOREX_CACHE_SYMBOL:
                        continue
                    if latest is None or fetch_time > latest:
                        latest = fetch_time
        return latest

    @classmethod
    def get_data_age_minutes(cls, symbol: str, timeframe: Optional[str] = None) -> Optional[float]:
        latest_fetch = cls.get_latest_fetch_time(symbol, timeframe)
        if latest_fetch is None:
            return None
        if latest_fetch.tzinfo is None:
            latest_fetch = latest_fetch.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - latest_fetch).total_seconds() / 60.0

    def should_force_refresh(self, symbol: str, timeframe: Optional[str] = None, max_age_minutes: Optional[float] = None) -> bool:
        age_minutes = self.get_data_age_minutes(symbol, timeframe)
        refresh_limit = float(max_age_minutes) if max_age_minutes is not None else (self.cache_ttl.total_seconds() / 60.0) + self._refresh_jitter_minutes
        return age_minutes is None or age_minutes > refresh_limit

    def _get_cached_articles(self, symbol: str, timeframe: str) -> Optional[List[NewsArticle]]:
        """
        Get cached news articles if still valid
        
        Args:
            symbol: Currency pair symbol
            
        Returns:
            Cached articles or None if not available/expired
        """
        for cache_key in self._cache_key_candidates(symbol, timeframe):
            if cache_key not in self.cache:
                continue

            cached_articles = self.cache[cache_key]
            last_fetch = self.last_fetch_time.get(cache_key)
            if last_fetch is None:
                continue

            now = datetime.now(timezone.utc)
            fetch_age = now - last_fetch
            if fetch_age.total_seconds() < self.news_cache_ttl_seconds:
                return cached_articles

        # Expired by fetch timestamp; next call may fetch fresh data.
        return None
    
    def clear_cache(self) -> None:
        """Clear all cached news data"""
        self.cache.clear()
        self.last_fetch_time.clear()
        self._persist_cache_to_disk()
        logger.info("News data cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_articles = sum(len(articles) for articles in self.cache.values())
        return {
            "cached_symbols": list(self.cache.keys()),
            "cache_size": len(self.cache),
            "total_articles": total_articles,
            "cache_ttl_minutes": self.cache_ttl.total_seconds() / 60,
            "last_fetch_tracked": len(self.last_fetch_time),
        }

    def _load_persistent_cache(self) -> None:
        if NewsDataCollector._persistent_cache_loaded:
            return
        cache_path = Path(self.CACHE_FILE_PATH)
        try:
            if not cache_path.exists():
                NewsDataCollector._persistent_cache_loaded = True
                return
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            cache_blob = dict(payload.get("cache", {}) or {})
            time_blob = dict(payload.get("timestamps", {}) or {})
            for cache_key, articles_blob in cache_blob.items():
                canonical_key = cache_key
                if cache_key.startswith(f"{self.GENERAL_FOREX_CACHE_SYMBOL}|"):
                    canonical_key = self.GENERAL_FOREX_CACHE_SYMBOL
                restored_articles: List[NewsArticle] = []
                for item in list(articles_blob or []):
                    try:
                        published_at = datetime.fromisoformat(str(item.get("published_at")).replace("Z", "+00:00"))
                        restored_articles.append(
                            NewsArticle(
                                title=str(item.get("title", "") or ""),
                                content=str(item.get("content", "") or ""),
                                source=str(item.get("source", "") or ""),
                                published_at=published_at,
                                url=str(item.get("url", "") or ""),
                                symbols=list(item.get("symbols", []) or []),
                            )
                        )
                    except Exception:
                        continue
                if restored_articles:
                    self.cache[canonical_key] = restored_articles
            for cache_key, ts in time_blob.items():
                canonical_key = cache_key
                if cache_key.startswith(f"{self.GENERAL_FOREX_CACHE_SYMBOL}|"):
                    canonical_key = self.GENERAL_FOREX_CACHE_SYMBOL
                try:
                    self.last_fetch_time[canonical_key] = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                except Exception:
                    continue
            logger.info("[NEWS_CACHE_PERSIST] Loaded %d cache entries from %s", len(self.cache), cache_path)
        except Exception as exc:
            logger.warning("[NEWS_CACHE_PERSIST] Failed to load persistent cache: %s", exc)
        finally:
            NewsDataCollector._persistent_cache_loaded = True

    def _persist_cache_to_disk(self) -> None:
        cache_path = Path(self.CACHE_FILE_PATH)
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "cache": {
                    cache_key: [
                        {
                            "title": article.title,
                            "content": article.content,
                            "source": article.source,
                            "published_at": article.published_at.isoformat(),
                            "url": article.url,
                            "symbols": list(getattr(article, "symbols", []) or []),
                        }
                        for article in list(articles or [])
                    ]
                    for cache_key, articles in self.cache.items()
                },
                "timestamps": {
                    cache_key: fetch_time.isoformat()
                    for cache_key, fetch_time in self.last_fetch_time.items()
                },
            }
            cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("[NEWS_CACHE_PERSIST] Failed to persist cache: %s", exc)

    def _get_best_effort_cached_articles(self, symbol: str, timeframe: str) -> List[NewsArticle]:
        cache_candidates: List[str] = []
        for candidate_symbol in (symbol, self.GENERAL_FOREX_CACHE_SYMBOL):
            for cache_key in self._cache_key_candidates(candidate_symbol, timeframe):
                if cache_key not in cache_candidates:
                    cache_candidates.append(cache_key)
        best_key = None
        best_time = None
        for cache_key in cache_candidates:
            fetch_time = self.last_fetch_time.get(cache_key)
            articles = self.cache.get(cache_key)
            if not articles:
                continue
            if best_time is None or (fetch_time is not None and fetch_time > best_time):
                best_key = cache_key
                best_time = fetch_time
        if best_key is None:
            for cache_key, fetch_time in self.last_fetch_time.items():
                articles = self.cache.get(cache_key)
                if not articles:
                    continue
                if best_time is None or (fetch_time is not None and fetch_time > best_time):
                    best_key = cache_key
                    best_time = fetch_time
        if best_key is None:
            return []
        return list(self.cache.get(best_key, []) or [])

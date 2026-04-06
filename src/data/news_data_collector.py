"""News data collector implementation"""

import asyncio
import logging
import os
import re
from datetime import datetime, timedelta, timezone
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
    _shared_news_cache: Dict[str, List[NewsArticle]] = {}
    _shared_news_timestamp_cache: Dict[str, datetime] = {}
    _shared_fetch_semaphore: Optional[asyncio.Semaphore] = None
    
    def __init__(self, config: Config):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache_ttl = timedelta(minutes=15)  # News cache for 15 minutes
        self.news_cache_ttl_seconds = 900
        # Persistent process-level caches shared across collector instances.
        # This survives per-cycle object churn and is not part of amnesia wipes.
        self.news_cache = NewsDataCollector._shared_news_cache
        self.news_timestamp_cache = NewsDataCollector._shared_news_timestamp_cache
        # Backwards-compatible aliases used elsewhere in this module.
        self.cache = self.news_cache
        self.last_fetch_time = self.news_timestamp_cache
        self.max_fetch_retries = 3
        self.fetch_retry_backoff_seconds = 30
        self.force_refresh_age_limit = timedelta(minutes=15)
        self.news_silent_fail_ttl = timedelta(minutes=10)
        self._last_silent_fail_notice: Dict[str, datetime] = {}
        news_cfg = getattr(self.config, "news", None)
        configured_provider = str(getattr(news_cfg, "provider", "") or "").strip().lower()
        env_api_key = str(os.environ.get("NEWS_API_KEY", "") or "").strip()
        configured_api_key = str(getattr(news_cfg, "api_key", "") or "").strip()
        self.api_key = configured_api_key or env_api_key
        self.provider = configured_provider or "newsapi"
        self.mock_mode = bool(getattr(news_cfg, "mock_mode", False))

        # Determine effective provider: default to forexfactory if newsapi key is missing
        if self.provider == "newsapi" and not self.api_key:
            logger.info("[NEWS_CONFIG] NewsAPI key missing. Defaulting to ForexFactory fallback.")
            self.provider = "forexfactory"

        if self.provider in {"unset", "none", "disabled", ""}:
            self.provider = "forexfactory"
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
                          force_refresh: bool = False) -> Dict[str, Any]:
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
            "[NEWS_COLLECT_CALL] symbols=%s timeframe=%s force_refresh=%s",
            symbols,
            timeframe,
            force_refresh,
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
            for idx, symbol in enumerate(symbols):
                try:
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
                    cache_key = self._cache_key(symbol, timeframe)
                    if (not self.requires_live_data()) and cache_key in self.cache:
                        logger.info(f"Using stale cached news data for {symbol}")
                        results[symbol] = self.cache[cache_key]
                    else:
                        raise
                finally:
                    if idx < len(symbols) - 1:
                        await asyncio.sleep(0.5)

        return results

    def _store_fetch_result(self, symbol: str, timeframe: str, articles: List[NewsArticle]) -> None:
        cache_key = self._cache_key(symbol, timeframe)
        self.cache[cache_key] = articles
        self.last_fetch_time[cache_key] = datetime.now(timezone.utc)

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
        if self._news_disabled_or_mocked() and self.provider == "mock":
            return []

        articles = []
        time_range = self._get_time_range(timeframe)
        
        try:
            provider = self._resolve_provider()

            # Implementation of Fallback Chain
            if provider == "newsapi" and self.api_key:
                try:
                    articles.extend(await self._fetch_newsapi_news(symbol, time_range))
                except Exception as e:
                    logger.warning(f"[NEWS_CHAIN_FALLBACK] NewsAPI failed: {e}. Trying ForexFactory...")
                    articles.extend(await self._fetch_forexfactory_calendar(symbol, time_range))
            elif provider == "forexfactory":
                articles.extend(await self._fetch_forexfactory_calendar(symbol, time_range))
            elif provider == "mock":
                return []
            else:
                # Default to ForexFactory if provider is unknown but not explicitly disabled
                articles.extend(await self._fetch_forexfactory_calendar(symbol, time_range))
            
        except Exception as e:
            logger.error(f"Error fetching news data for {symbol}: {e}")
            raise APIError(
                f"Failed to fetch news data for {symbol}: {e}",
                error_code="NEWS_FETCH_FAILED",
                context={"symbol": symbol, "error": str(e)}
            )
        
        return articles

    async def _fetch_forexfactory_calendar(self, symbol: str, time_range: timedelta) -> List[NewsArticle]:
        """Fetch high-impact events from ForexFactory JSON feed (free, no API key)"""
        url = "https://nfs.forexfactory.com/ff_calendar_thisweek.json"

        session_created = False
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.api_timeout))
            session_created = True

        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    return []
                data = await response.json()
        except Exception as e:
            logger.error(f"[FOREXFACTORY_ERR] Failed to fetch calendar: {e}")
            return []
        finally:
            if session_created and self.session is not None:
                await self.session.close()
                self.session = None

        articles: List[NewsArticle] = []
        now = datetime.now(timezone.utc)

        # Map symbol currencies (e.g., EUR/USD -> ['EUR', 'USD'])
        target_currencies = set(symbol.split('/'))

        for event in data:
            try:
                # Date format: "2025-05-22T08:30:00-04:00"
                published_at = datetime.fromisoformat(event.get("date", ""))
                if published_at.tzinfo is None:
                    published_at = published_at.replace(tzinfo=timezone.utc)

                # Filter by timeframe and currency relevance
                if abs((now - published_at).total_seconds()) > time_range.total_seconds():
                    continue

                if event.get("country") not in target_currencies:
                    continue

                # Only include High/Medium impact for the news articles buffer
                impact = str(event.get("impact", "")).upper()
                if impact not in ["HIGH", "MEDIUM"]:
                    continue

                articles.append(
                    NewsArticle(
                        title=f"[{impact}] {event.get('title')}",
                        content=f"ForexFactory Event: {event.get('title')} | Impact: {impact} | Forecast: {event.get('forecast')} | Prev: {event.get('previous')}",
                        source="ForexFactory",
                        published_at=published_at,
                        url="https://www.forexfactory.com/calendar",
                        symbols=[symbol],
                    )
                )
            except Exception:
                continue

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

        query = symbol.replace("/", " OR ")
        from_time = (datetime.now(timezone.utc) - time_range).isoformat()
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 25,
            "from": from_time,
            "apiKey": api_key,
        }

        session_created = False
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=self.config.api_timeout))
            session_created = True

        try:
            async with self.session.get("https://newsapi.org/v2/everything", params=params) as response:
                if response.status != 200:
                    body = await response.text()
                    raise APIError(
                        f"NewsAPI request failed: status={response.status} body={body[:200]}",
                        error_code="NEWS_API_HTTP_ERROR",
                        context={"symbol": symbol},
                    )
                payload = await response.json()
        finally:
            if session_created and self.session is not None:
                await self.session.close()
                self.session = None

        articles: List[NewsArticle] = []
        for item in payload.get("articles", []) or []:
            title = str(item.get("title", "") or "").strip()
            content = str(item.get("description") or item.get("content") or "").strip()
            url = str(item.get("url", "") or "").strip()
            source_name = str((item.get("source") or {}).get("name", "NewsAPI") or "NewsAPI")
            published_raw = str(item.get("publishedAt", "") or "").strip()
            if not title or not content or not url or not published_raw:
                continue
            if not self._matches_symbol_or_forex_theme(symbol, title, content):
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
                    symbols=[symbol],
                )
            )

        if not articles:
            raise APIError(
                f"No live news articles matched for {symbol}",
                error_code="NEWS_FEED_EMPTY",
                context={"symbol": symbol},
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
                # Clean and preprocess content
                article.processed_content = self._clean_text(article.content)
                
                # Check relevance to forex/currency trading
                if self._is_forex_relevant(article):
                    # Extract mentioned currency pairs
                    mentioned_pairs = self._extract_currency_pairs(article.processed_content)
                    
                    # Normalize symbols for comparison (remove slashes)
                    norm_symbol = symbol.replace('/', '')
                    norm_mentioned = [p.replace('/', '') for p in mentioned_pairs]
                    
                    if norm_symbol in norm_mentioned or not norm_mentioned:
                        article.symbols = mentioned_pairs if mentioned_pairs else [symbol]
                        processed_articles.append(article)
                        
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
        return f"{symbol}|{timeframe}"

    @classmethod
    def get_latest_fetch_time(cls, symbol: str, timeframe: Optional[str] = None) -> Optional[datetime]:
        normalized_symbol = str(symbol or "")
        latest: Optional[datetime] = None
        for cache_key, fetch_time in cls._shared_news_timestamp_cache.items():
            try:
                cache_symbol, cache_timeframe = cache_key.split("|", 1)
            except ValueError:
                continue
            if cache_symbol != normalized_symbol:
                continue
            if timeframe is not None and cache_timeframe != timeframe:
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

    def should_force_refresh(self, symbol: str, timeframe: Optional[str] = None, max_age_minutes: float = 15.0) -> bool:
        age_minutes = self.get_data_age_minutes(symbol, timeframe)
        return age_minutes is None or age_minutes > float(max_age_minutes)

    def _get_cached_articles(self, symbol: str, timeframe: str) -> Optional[List[NewsArticle]]:
        """
        Get cached news articles if still valid
        
        Args:
            symbol: Currency pair symbol
            
        Returns:
            Cached articles or None if not available/expired
        """
        cache_key = self._cache_key(symbol, timeframe)
        if cache_key not in self.cache:
            return None

        cached_articles = self.cache[cache_key]
        last_fetch = self.last_fetch_time.get(cache_key)
        if last_fetch is None:
            return None

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

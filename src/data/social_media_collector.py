"""Social media data collector implementation"""

import asyncio
import logging
import re
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import aiohttp
from src.interfaces import DataCollector
from src.exceptions import DataValidationError, APIError
from src.config import Config


logger = logging.getLogger(__name__)


class SocialMediaPost:
    """Social media post data structure"""

    def __init__(self, content: str, platform: str, author: str, posted_at: datetime,
                 post_id: str, engagement_score: float = 0.0,
                 symbols: Optional[List[str]] = None):
        self.content = content
        self.platform = platform
        self.author = author
        self.posted_at = posted_at
        self.post_id = post_id
        self.engagement_score = engagement_score
        self.symbols = symbols or []
        self.processed_content = ""

    def validate(self) -> None:
        """Validate social media post data"""
        if not self.content or not self.content.strip():
            raise DataValidationError(
                "Post content cannot be empty",
                error_code="EMPTY_CONTENT",
                context={"content": self.content}
            )

        if not self.platform or not self.platform.strip():
            raise DataValidationError(
                "Platform cannot be empty",
                error_code="EMPTY_PLATFORM",
                context={"platform": self.platform}
            )

        if not self.author or not self.author.strip():
            raise DataValidationError(
                "Author cannot be empty",
                error_code="EMPTY_AUTHOR",
                context={"author": self.author}
            )

        if self.posted_at > datetime.now():
            raise DataValidationError(
                f"Posted date cannot be in the future: {self.posted_at}",
                error_code="FUTURE_TIMESTAMP",
                context={"posted_at": self.posted_at}
            )

        if not self.post_id or not self.post_id.strip():
            raise DataValidationError(
                "Post ID cannot be empty",
                error_code="EMPTY_POST_ID",
                context={"post_id": self.post_id}
            )

        if self.engagement_score < 0:
            raise DataValidationError(
                f"Engagement score cannot be negative: {self.engagement_score}",
                error_code="NEGATIVE_ENGAGEMENT",
                context={"engagement_score": self.engagement_score}
            )


class SocialMediaCollector(DataCollector):
    """Collects social media posts relevant to forex trading"""

    def __init__(self, config: Config):
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, List[SocialMediaPost]] = {}
        self.cache_ttl = timedelta(minutes=10)  # Social media cache for 10 min
        
# Forex-related hashtags and keywords for filtering
        self.forex_hashtags = [
            '#forex', '#fx', '#trading', '#currency', '#eurusd', '#gbpusd',
            '#usdjpy', '#usdchf', '#audusd', '#usdcad', '#nzdusd',
            '#forextrading', '#currencytrading', '#forexsignals', '#pip',
            '#spread', '#leverage', '#margin', '#centralbank', '#fed', '#ecb'
        ]

        self.forex_keywords = [
            'forex', 'currency', 'exchange rate', 'central bank', 'fed', 'ecb',
            'boe', 'interest rate', 'monetary policy', 'inflation', 'gdp',
            'employment', 'trade war', 'brexit', 'dollar', 'euro', 'pound',
            'yen', 'swiss franc', 'pip', 'spread', 'leverage', 'margin'
        ]

        # Currency pair patterns
        self.currency_patterns = [
            r'EUR/USD', r'GBP/USD', r'USD/JPY', r'USD/CHF', r'AUD/USD',
            r'USD/CAD', r'NZD/USD', r'EUR/GBP', r'EUR/JPY', r'GBP/JPY'
        ]

        # Minimum engagement score for post relevance
        self.min_engagement_score = 10.0

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
                          timeframe: str = "1h") -> Dict[str, Any]:
        """
        Collect social media data for given symbols

        Args:
            symbols: List of currency pairs to collect posts for
            timeframe: Time range for post collection (1h, 4h, 1d)

        Returns:
            Dictionary with symbol as key and list of SocialMediaPost as value
        """
        logger.info(f"Collecting social media data for symbols: {symbols}, "
                   f"timeframe: {timeframe}")

        if not symbols:
            raise DataValidationError(
                "Symbols list cannot be empty",
                error_code="EMPTY_SYMBOLS",
                context={"symbols": symbols}
            )

        results = {}

        for symbol in symbols:
            try:
                # Check cache first
                cached_posts = self._get_cached_posts(symbol)
                if cached_posts:
                    logger.debug(f"Using cached social media data for {symbol}")
                    results[symbol] = cached_posts
                    continue

                # Fetch fresh social media data
                posts = await self._fetch_social_media_data(symbol, timeframe)
                if posts:
                    # Process and filter posts
                    processed_posts = self._process_posts(posts, symbol)

                    # Cache the data
                    self.cache[symbol] = processed_posts
                    results[symbol] = processed_posts
                    logger.debug(f"Fetched {len(processed_posts)} posts for "
                               f"{symbol}")
                else:
                    logger.warning(f"No social media posts found for {symbol}")
                    results[symbol] = []

            except Exception as e:
                logger.error(f"Error collecting social media data for "
                           f"{symbol}: {e}")
                # Try to use stale cached data as fallback
                if symbol in self.cache:
                    logger.info(f"Using stale cached social media data for "
                              f"{symbol}")
                    results[symbol] = self.cache[symbol]
                else:
                    # Return empty list instead of raising error
                    logger.warning(f"No fallback social media data available "
                                 f"for {symbol}")
                    results[symbol] = []

        return results

    async def validate_data(self, data: Dict[str, Any]) -> bool:
        """
        Validate collected social media data

        Args:
            data: Dictionary of social media data to validate

        Returns:
            True if all data is valid, False otherwise
        """
        if not data:
            logger.warning("No social media data to validate")
            return True  # Empty social media data is acceptable

        for symbol, posts in data.items():
            try:
                if not isinstance(posts, list):
                    logger.error(f"Invalid posts type for {symbol}: "
                               f"{type(posts)}")
                    return False

                for i, post in enumerate(posts):
                    if not isinstance(post, SocialMediaPost):
                        logger.error(f"Invalid post type at index {i} for "
                                   f"{symbol}: {type(post)}")
                        return False

                    # Validate each post
                    post.validate()

                    # Check if post is too old
                    age = datetime.now() - post.posted_at
                    if age > timedelta(days=1):  # Posts older than 1 day
                        logger.warning(f"Post too old for {symbol}: "
                                     f"{post.posted_at}")
                        return False

            except DataValidationError as e:
                logger.error(f"Validation error for {symbol}: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected validation error for {symbol}: {e}")
                return False

        logger.info(f"Successfully validated social media data for "
                   f"{len(data)} symbols")
        return True

    async def _fetch_social_media_data(self, symbol: str,
                                      timeframe: str) -> List[SocialMediaPost]:
        """
        Fetch social media data from various platforms

        Args:
            symbol: Currency pair symbol
            timeframe: Time range for posts

        Returns:
            List of SocialMediaPost objects
        """
        posts = []

        # Calculate time range based on timeframe
        time_range = self._get_time_range(timeframe)

        try:
            # Fetch from multiple sources (mock implementation)
            # In a real implementation, you would integrate with:
            # - Twitter API v2
            # - Reddit API
            # - Discord webhooks
            # - Telegram channels
            # - StockTwits API
            mock_posts = await self._fetch_mock_posts(symbol, time_range)
            posts.extend(mock_posts)

        except Exception as e:
            logger.error(f"Error fetching social media data for {symbol}: {e}")
            raise APIError(
                f"Failed to fetch social media data for {symbol}: {e}",
                error_code="SOCIAL_MEDIA_FETCH_FAILED",
                context={"symbol": symbol, "error": str(e)}
            )

        return posts

    async def _fetch_mock_posts(self, symbol: str,
                               time_range: timedelta) -> List[SocialMediaPost]:
        """
        Mock social media data fetcher for testing

        Args:
            symbol: Currency pair symbol
            time_range: Time range for posts

        Returns:
            List of mock SocialMediaPost objects
        """
        # Simulate API delay
        await asyncio.sleep(0.1)

        mock_posts = []
        base_currencies = symbol.split('/')

        # Generate mock posts based on symbol
        mock_data = [
            {
                "content": f"Bullish on {symbol}! Central bank policy changes "
                          f"could drive {base_currencies[0]} higher. "
                          f"#forex #trading #{symbol.lower().replace('/', '')}",
                "platform": "Twitter",
                "author": "ForexTrader123",
                "posted_at": datetime.now() - timedelta(minutes=30),
                "post_id": f"twitter_{symbol.lower().replace('/', '_')}_1",
                "engagement_score": 45.0
            },
            {
                "content": f"Technical analysis shows {symbol} breaking "
                          f"resistance. Could see continuation to upside. "
                          f"What do you think? #forex #technicalanalysis",
                "platform": "Reddit",
                "author": "TechnicalAnalyst",
                "posted_at": datetime.now() - timedelta(hours=1),
                "post_id": f"reddit_{symbol.lower().replace('/', '_')}_2",
                "engagement_score": 23.0
            },
            {
                "content": f"Market sentiment on {symbol} seems mixed today. "
                          f"Economic data release tomorrow could be key. "
                          f"Stay cautious! #forextrading #marketanalysis",
                "platform": "StockTwits",
                "author": "MarketWatcher",
                "posted_at": datetime.now() - timedelta(hours=2),
                "post_id": f"stocktwits_{symbol.lower().replace('/', '_')}_3",
                "engagement_score": 67.0
            },
            {
                "content": f"Just closed a profitable {symbol} trade! "
                          f"Risk management is key in forex trading. "
                          f"Never risk more than you can afford to lose.",
                "platform": "Discord",
                "author": "ProfitableTrader",
                "posted_at": datetime.now() - timedelta(hours=3),
                "post_id": f"discord_{symbol.lower().replace('/', '_')}_4",
                "engagement_score": 12.0
            }
        ]

        for post_data in mock_data:
            # Only include posts within the time range
            if datetime.now() - post_data["posted_at"] <= time_range:
                post = SocialMediaPost(
                    content=post_data["content"],
                    platform=post_data["platform"],
                    author=post_data["author"],
                    posted_at=post_data["posted_at"],
                    post_id=post_data["post_id"],
                    engagement_score=post_data["engagement_score"],
                    symbols=[symbol]
                )
                mock_posts.append(post)

        return mock_posts

    def _process_posts(self, posts: List[SocialMediaPost],
                      symbol: str) -> List[SocialMediaPost]:
        """
        Process and filter posts for relevance

        Args:
            posts: List of raw posts
            symbol: Target currency pair

        Returns:
            List of processed and filtered posts
        """
        processed_posts = []

        for post in posts:
            try:
                # Clean and preprocess content
                post.processed_content = self._clean_text(post.content)

                # Check relevance to forex/currency trading
                if self._is_forex_relevant(post):
                    # Check minimum engagement threshold
                    if post.engagement_score >= self.min_engagement_score:
                        # Extract mentioned currency pairs
                        mentioned_pairs = self._extract_currency_pairs(
                            post.processed_content)
                        if symbol in mentioned_pairs or not mentioned_pairs:
                            post.symbols = (mentioned_pairs if mentioned_pairs
                                          else [symbol])
                            processed_posts.append(post)

            except Exception as e:
                logger.warning(f"Error processing post: {e}")
                continue

        # Sort by engagement score (highest first)
        processed_posts.sort(key=lambda x: x.engagement_score, reverse=True)

        return processed_posts

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

        # Remove URLs
        text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|'
                     r'[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)

        # Remove mentions (@username)
        text = re.sub(r'@\w+', '', text)

        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)

        # Remove special characters but keep hashtags and basic punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\/\#]', '', text)

        return text.strip()

    def _is_forex_relevant(self, post: SocialMediaPost) -> bool:
        """
        Check if post is relevant to forex trading

        Args:
            post: SocialMediaPost to check

        Returns:
            True if relevant, False otherwise
        """
        content_lower = post.processed_content.lower()

        # Check for forex-related hashtags
        for hashtag in self.forex_hashtags:
            if hashtag.lower() in content_lower:
                return True

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

    def _get_cached_posts(self, symbol: str) -> Optional[List[SocialMediaPost]]:
        """
        Get cached social media posts if still valid

        Args:
            symbol: Currency pair symbol

        Returns:
            Cached posts or None if not available/expired
        """
        if symbol not in self.cache:
            return None

        cached_posts = self.cache[symbol]

        if not cached_posts:
            return cached_posts

        # Check if cache is still valid based on newest post
        newest_post = max(cached_posts, key=lambda x: x.posted_at)
        cache_age = datetime.now() - newest_post.posted_at

        if cache_age <= self.cache_ttl:
            return cached_posts

        # Remove expired cache entry
        del self.cache[symbol]
        return None

    def clear_cache(self) -> None:
        """Clear all cached social media data"""
        self.cache.clear()
        logger.info("Social media data cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_posts = sum(len(posts) for posts in self.cache.values())
        return {
            "cached_symbols": list(self.cache.keys()),
            "cache_size": len(self.cache),
            "total_posts": total_posts,
            "cache_ttl_minutes": self.cache_ttl.total_seconds() / 60
        }
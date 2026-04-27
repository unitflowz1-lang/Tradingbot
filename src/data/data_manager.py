"""High-level data management interface for the AI Forex Trading Bot"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from src.data.storage import DataStorage, CacheManager, DataRetentionManager
from src.data.market_data_collector import MarketDataCollector
from src.data.news_data_collector import NewsDataCollector, NewsArticle
from src.data.social_media_collector import (
    SocialMediaCollector, SocialMediaPost
)
from src.models import MarketData, SentimentResult
from src.config import Config
from src.exceptions import DataValidationError, DatabaseError
logger = logging.getLogger(__name__)


class DataManager:
    """
    High-level data management interface that coordinates data
    collection, storage, caching, and retrieval operations.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.storage = DataStorage(config)
        self.cache_manager = CacheManager(self.storage)
        self.retention_manager = DataRetentionManager(self.storage)
        
        # Data collectors - these will be created in the context manager
        self.market_data_collector = None
        self.news_data_collector = None
        self.social_media_collector = None
        
        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cleanup_interval = timedelta(hours=6)  # Run cleanup every 6 hours
        
    async def initialize(self) -> None:
        """Initialize the data management system"""
        try:
            # Initialize storage
            await self.storage.initialize()
            
            # Start background cleanup task
            self._cleanup_task = asyncio.create_task(self._background_cleanup())
            
            logger.info("Data management system initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize data management system: {e}")
            raise DatabaseError(
                f"Data manager initialization failed: {e}",
                error_code="DATA_MANAGER_INIT_FAILED",
                context={"error": str(e)},
            )
    
    async def shutdown(self) -> None:
        """Shutdown the data management system"""
        try:
            # Cancel background tasks
            if self._cleanup_task and not self._cleanup_task.done():
                self._cleanup_task.cancel()
                try:
                    await self._cleanup_task
                except asyncio.CancelledError:
                    pass
            
            # Close storage connections
            await self.storage.close()
            
            logger.info("Data management system shutdown completed")
            
        except Exception as e:
            logger.error(f"Error during data manager shutdown: {e}")
    
    @asynccontextmanager
    async def get_data_collectors(self):
        """Context manager for data collectors with proper cleanup"""
        collectors = []
        try:
            # Initialize collectors
            # Note: MarketDataCollector requires a BrokerInterface,
            # so we'll create a mock one for now
            from src.data.mock_broker import MockBrokerInterface
            mock_broker = MockBrokerInterface()
            
            market_collector = MarketDataCollector(mock_broker, self.config)
            news_collector = NewsDataCollector(self.config)
            social_collector = SocialMediaCollector(self.config)
            
            collectors = [market_collector, news_collector, social_collector]
            
            yield {
                'market': market_collector,
                'news': news_collector,
                'social': social_collector
            }
            
        finally:
            # Cleanup collectors
            for collector in collectors:
                if hasattr(collector, 'close'):
                    try:
                        await collector.close()
                    except Exception as e:
                        logger.warning(f"Error closing collector: {e}")
    
    async def collect_and_store_market_data(
        self, symbols: List[str], timeframe: str = "1h"
    ) -> Dict[str, int]:
        """
        Collect market data and store it in the database
        
        Args:
            symbols: List of currency pairs to collect data for
            timeframe: Timeframe for data collection
            
        Returns:
            Dictionary with symbol as key and number of stored records as
            value
        """
        results = {}
        
        async with self.get_data_collectors() as collectors:
            try:
                # Collect market data
                market_data = await collectors['market'].collect_data(symbols, timeframe)
                
                # Validate collected data
                if not await collectors['market'].validate_data(market_data):
                    raise DataValidationError(
                        "Market data validation failed",
                        error_code="MARKET_DATA_VALIDATION_FAILED",
                        context={"symbols": symbols, "timeframe": timeframe},
                    )
                
                # Store data for each symbol
                for symbol, data_list in market_data.items():
                    if data_list:
                        stored_count = await self.storage.store_market_data(data_list)
                        results[symbol] = stored_count
                        
                        # Cache recent data
                        cache_key = f"market_data:{symbol}:latest"
                        await self.cache_manager.set(
                            cache_key, 
                            data_list[-1] if data_list else None,
                            timedelta(minutes=5)
                        )
                    else:
                        results[symbol] = 0
                
                logger.info(f"Collected and stored market data: {results}")
                return results
            except Exception as e:
                logger.error(f"Error collecting and storing market data: {e}")
                raise

    async def collect_and_store_news_data(
        self, symbols: List[str], timeframe: str = "4h"
    ) -> Dict[str, int]:
        """
        Collect news data and store it in the database
        
        Args:
            symbols: List of currency pairs to collect news for
            timeframe: Timeframe for news collection
            
        Returns:
            Dictionary with symbol as key and number of stored articles as
            value
        """
        results = {}
        
        async with self.get_data_collectors() as collectors:
            try:
                # Collect news data
                news_data = await collectors['news'].collect_data(symbols, timeframe)
                
                # Validate collected data
                if not await collectors['news'].validate_data(news_data):
                    raise DataValidationError(
                        "News data validation failed",
                        error_code="NEWS_DATA_VALIDATION_FAILED",
                        context={"symbols": symbols, "timeframe": timeframe},
                    )
                
                # Store data for each symbol
                for symbol, articles in news_data.items():
                    if articles:
                        stored_count = await self.storage.store_news_data(articles)
                        results[symbol] = stored_count
                        
                        # Cache recent articles
                        cache_key = f"news_data:{symbol}:recent"
                        await self.cache_manager.set(
                            cache_key,
                            articles[:5],  # Cache top 5 recent articles
                            timedelta(minutes=15)
                        )
                    else:
                        results[symbol] = 0
                
                logger.info(f"Collected and stored news data: {results}")
                return results
                
            except Exception as e:
                logger.error(f"Error collecting and storing news data: {e}")
                raise
    
    async def collect_and_store_social_media_data(
        self, symbols: List[str], timeframe: str = "2h"
    ) -> Dict[str, int]:
        """
        Collect social media data and store it in the database
        
        Args:
            symbols: List of currency pairs to collect posts for
            timeframe: Timeframe for post collection
            
        Returns:
            Dictionary with symbol as key and number of stored posts as value
        """
        results = {}
        
        async with self.get_data_collectors() as collectors:
            try:
                # Collect social media data
                social_data = await collectors['social'].collect_data(
                    symbols, timeframe
                )
                
                # Validate collected data
                if not await collectors['social'].validate_data(social_data):
                    raise DataValidationError(
                        "Social media data validation failed",
                        error_code="SOCIAL_MEDIA_VALIDATION_FAILED",
                        context={"symbols": symbols, "timeframe": timeframe},
                    )
                
                # Store data for each symbol
                for symbol, posts in social_data.items():
                    if posts:
                        stored_count = await self.storage.store_social_media_data(posts)
                        results[symbol] = stored_count
                        
                        # Cache high-engagement posts
                        high_engagement_posts = [
                            post for post in posts 
                            if post.engagement_score >= 50.0
                        ]
                        if high_engagement_posts:
                            cache_key = f"social_data:{symbol}:high_engagement"
                            await self.cache_manager.set(
                                cache_key,
                                high_engagement_posts[:3],  # Cache top 3
                                timedelta(minutes=10)
                            )
                    else:
                        results[symbol] = 0
                
                logger.info(f"Collected and stored social media data: {results}")
                return results
                
            except Exception as e:
                logger.error(f"Error collecting and storing social media data: {e}")
                raise
    
    async def store_sentiment_data(self, sentiment_results: List[SentimentResult]) -> int:
        """
        Store sentiment analysis results
        
        Args:
            sentiment_results: List of sentiment results to store
            
        Returns:
            Number of stored records
        """
        try:
            stored_count = await self.storage.store_sentiment_data(
                sentiment_results
            )
            
            # Cache latest sentiment for each symbol
            symbol_sentiments: Dict[str, SentimentResult] = {}
            for result in sentiment_results:
                if (
                    result.symbol not in symbol_sentiments or
                    result.timestamp > 
                    symbol_sentiments[result.symbol].timestamp
                ):
                    symbol_sentiments[result.symbol] = result
            
            for symbol, sentiment in symbol_sentiments.items():
                cache_key = f"sentiment:{symbol}:latest"
                await self.cache_manager.set(
                    cache_key,
                    sentiment,
                    timedelta(minutes=30)
                )
            
            logger.info(f"Stored {stored_count} sentiment results")
            return stored_count
            
        except Exception as e:
            logger.error(f"Error storing sentiment data: {e}")
            raise
    
    async def get_market_data(
        self, symbol: str, start_time: datetime, 
        end_time: datetime, use_cache: bool = True
    ) -> List[MarketData]:
        """
        Retrieve market data with caching support
        
        Args:
            symbol: Currency pair symbol
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            use_cache: Whether to use cache for recent data
            
        Returns:
            List of MarketData objects
        """
        # Check cache for recent data
        if use_cache and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(minutes=10):
            cache_key = f"market_data:{symbol}:{start_time}:{end_time}"
            cached_data = await self.cache_manager.get(cache_key)
            if cached_data:
                logger.debug(f"Retrieved market data from cache for {symbol}")
                return cached_data
        
        # Retrieve from database
        market_data = await self.storage.get_market_data(
            symbol, start_time, end_time
        )
        
        # Cache the result if it's recent
        if use_cache and market_data and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(hours=1):
            cache_key = f"market_data:{symbol}:{start_time}:{end_time}"
            await self.cache_manager.set(
                cache_key, market_data, timedelta(minutes=30)
            )
        
        return market_data
    
    async def get_news_data(
        self, symbols: List[str], start_time: datetime, 
        end_time: datetime, use_cache: bool = True
    ) -> List[NewsArticle]:
        """
        Retrieve news data with caching support
        
        Args:
            symbols: List of currency pair symbols
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            use_cache: Whether to use cache for recent data
            
        Returns:
            List of NewsArticle objects
        """
        # Check cache for recent data
        if use_cache and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(minutes=30):
            cache_key = f"news_data:{':'.join(symbols)}:{start_time}:{end_time}"
            cached_data = await self.cache_manager.get(cache_key)
            if cached_data:
                logger.debug(f"Retrieved news data from cache for {symbols}")
                return cached_data
        
        # Retrieve from database
        news_data = await self.storage.get_news_data(
            symbols, start_time, end_time
        )
        
        # Cache the result if it's recent
        if use_cache and news_data and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(hours=2):
            cache_key = f"news_data:{':'.join(symbols)}:{start_time}:{end_time}"
            await self.cache_manager.set(
                cache_key, news_data, timedelta(minutes=60)
            )
        
        return news_data
    
    async def get_social_media_data(
        self, symbols: List[str], start_time: datetime, 
        end_time: datetime, use_cache: bool = True
    ) -> List[SocialMediaPost]:
        """
        Retrieve social media data with caching support
        
        Args:
            symbols: List of currency pair symbols
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            use_cache: Whether to use cache for recent data
            
        Returns:
            List of SocialMediaPost objects
        """
        # Check cache for recent data
        if use_cache and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(minutes=15):
            cache_key = f"social_data:{':'.join(symbols)}:{start_time}:{end_time}"
            cached_data = await self.cache_manager.get(cache_key)
            if cached_data:
                logger.debug(f"Retrieved social media data from cache for {symbols}")
                return cached_data
        
        # Retrieve from database
        social_data = await self.storage.get_social_media_data(
            symbols, start_time, end_time
        )
        
        # Cache the result if it's recent
        if use_cache and social_data and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(minutes=30):
            cache_key = f"social_data:{':'.join(symbols)}:{start_time}:{end_time}"
            await self.cache_manager.set(
                cache_key, social_data, timedelta(minutes=20)
            )
        
        return social_data
    
    async def get_sentiment_data(
        self, symbol: str, start_time: datetime, 
        end_time: datetime, use_cache: bool = True
    ) -> List[SentimentResult]:
        """
        Retrieve sentiment data with caching support
        
        Args:
            symbol: Currency pair symbol
            start_time: Start time for data retrieval
            end_time: End time for data retrieval
            use_cache: Whether to use cache for recent data
            
        Returns:
            List of SentimentResult objects
        """
        # Check cache for recent data
        if use_cache and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(minutes=30):
            cache_key = f"sentiment:{symbol}:{start_time}:{end_time}"
            cached_data = await self.cache_manager.get(cache_key)
            if cached_data:
                logger.debug(f"Retrieved sentiment data from cache for {symbol}")
                return cached_data
        
        # Retrieve from database
        sentiment_data = await self.storage.get_sentiment_data(
            symbol, start_time, end_time
        )
        
        # Cache the result if it's recent
        if use_cache and sentiment_data and (
            datetime.now(timezone.utc) - end_time
        ) < timedelta(hours=1):
            cache_key = f"sentiment:{symbol}:{start_time}:{end_time}"
            await self.cache_manager.set(
                cache_key, sentiment_data, timedelta(minutes=45)
            )
        
        return sentiment_data
    
    async def get_latest_data_summary(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Get a summary of the latest data for given symbols
        
        Args:
            symbols: List of currency pair symbols
            
        Returns:
            Dictionary with latest data summary for each symbol
        """
        summary = {}
        
        for symbol in symbols:
            symbol_summary = {}
            
            try:
                # Get latest market data
                end_time = datetime.now(timezone.utc)
                start_time = end_time - timedelta(hours=1)
                market_data = await self.get_market_data(symbol, start_time, end_time)
                if market_data:
                    symbol_summary['latest_market_data'] = {
                        'timestamp': market_data[-1].timestamp,
                        'close': market_data[-1].close,
                        'volume': market_data[-1].volume
                    }
                
                # Get latest sentiment
                cache_key = f"sentiment:{symbol}:latest"
                latest_sentiment = await self.cache_manager.get(cache_key)
                if latest_sentiment:
                    symbol_summary['latest_sentiment'] = {
                        'score': latest_sentiment.sentiment_score,
                        'confidence': latest_sentiment.confidence,
                        'timestamp': latest_sentiment.timestamp
                    }
                
                # Get recent news count
                start_time = end_time - timedelta(hours=24)
                news_data = await self.get_news_data(
                    [symbol], start_time, end_time
                )
                symbol_summary['news_count_24h'] = len(news_data)
                
                # Get recent social media count
                social_data = await self.get_social_media_data(
                    [symbol], start_time, end_time
                )
                symbol_summary['social_posts_24h'] = len(social_data)
                
                summary[symbol] = symbol_summary
                
            except Exception as e:
                logger.error(f"Error getting summary for {symbol}: {e}")
                summary[symbol] = {'error': str(e)}
        
        return summary
    
    async def run_maintenance(self) -> Dict[str, Any]:
        """
        Run maintenance tasks (cleanup, cache optimization, etc.)
        
        Returns:
            Dictionary with maintenance results
        """
        maintenance_results: Dict[str, Any] = {}
        
        try:
            # Clean up expired cache entries
            cache_cleaned = await self.cache_manager.cleanup_expired()
            maintenance_results['cache_cleaned'] = cache_cleaned
            
            # Clean up old data based on retention policies
            data_cleaned = await self.retention_manager.cleanup_old_data()
            maintenance_results['data_cleaned'] = data_cleaned
            
            # Get storage statistics
            storage_stats = await self.retention_manager.get_storage_stats()
            maintenance_results['storage_stats'] = storage_stats
            
            logger.info(f"Maintenance completed: {maintenance_results}")
            return maintenance_results
            
        except Exception as e:
            logger.error(f"Error during maintenance: {e}")
            maintenance_results['error'] = str(e)
            return maintenance_results
    
    async def _background_cleanup(self) -> None:
        """Background task for periodic cleanup"""
        while True:
            try:
                await asyncio.sleep(self._cleanup_interval.total_seconds())
                await self.run_maintenance()
                
            except asyncio.CancelledError:
                logger.info("Background cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in background cleanup: {e}")
                # Continue running despite errors
                await asyncio.sleep(60)  # Wait 1 minute before retrying

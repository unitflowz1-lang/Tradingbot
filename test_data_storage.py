"""Unit tests for data storage and caching system"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, patch
from typing import List

from src.data.storage import (
    DataStorage, CacheManager, DataRetentionManager,
    MarketDataModel, NewsDataModel, SocialMediaDataModel, 
    SentimentDataModel, CacheEntryModel
)
from src.models import MarketData, SentimentResult
from src.data.news_data_collector import NewsArticle
from src.data.social_media_collector import SocialMediaPost
from src.config import Config, DatabaseConfig, TradingConfig, LLMConfig, RiskConfig, BrokerConfig
from src.exceptions import DatabaseError


@pytest.fixture
def mock_config():
    """Create mock configuration for testing"""
    return Config(
        trading=TradingConfig(
            supported_pairs=['EUR/USD', 'GBP/USD'],
            max_positions=5,
            max_daily_trades=10,
            risk_per_trade=0.02,
            max_drawdown=0.10,
            trading_hours={}
        ),
        llm=LLMConfig(
            provider='openai',
            model='gpt-4',
            api_key='test-key',
            max_tokens=1000,
            temperature=0.1,
            timeout=30
        ),
        risk=RiskConfig(
            max_position_size=0.05,
            stop_loss_pct=0.02,
            take_profit_pct=0.04,
            max_correlation=0.7,
            drawdown_limit=0.10
        ),
        broker=BrokerConfig(
            broker_name='test-broker',
            api_key='test-key',
            api_secret='test-secret',
            base_url='https://test.com',
            timeout=30
        ),
        database=DatabaseConfig(
            host='localhost',
            port=5432,
            database='test_db',
            username='test_user',
            password='test_pass'
        )
    )


@pytest.fixture
def sample_market_data():
    """Create sample market data for testing"""
    return [
        MarketData(
            symbol='EUR/USD',
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            open=1.1000,
            high=1.1050,
            low=1.0950,
            close=1.1025,
            volume=1000,
            bid=1.1020,
            ask=1.1025,
            spread=0.0005
        ),
        MarketData(
            symbol='EUR/USD',
            timestamp=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc),
            open=1.1025,
            high=1.1075,
            low=1.1000,
            close=1.1050,
            volume=1200,
            bid=1.1045,
            ask=1.1050,
            spread=0.0005
        )
    ]


@pytest.fixture
def sample_news_articles():
    """Create sample news articles for testing"""
    return [
        NewsArticle(
            title='EUR/USD Rises on ECB Policy',
            content='The EUR/USD pair gained ground today...',
            source='Reuters',
            published_at=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            url='https://example.com/news/1',
            symbols=['EUR/USD']
        ),
        NewsArticle(
            title='Dollar Weakens Against Euro',
            content='The US dollar weakened against the euro...',
            source='Bloomberg',
            published_at=datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc),
            url='https://example.com/news/2',
            symbols=['EUR/USD']
        )
    ]


@pytest.fixture
def sample_social_media_posts():
    """Create sample social media posts for testing"""
    return [
        SocialMediaPost(
            content='Bullish on EUR/USD! #forex #trading',
            platform='Twitter',
            author='trader123',
            posted_at=datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
            post_id='twitter_1',
            engagement_score=45.0,
            symbols=['EUR/USD']
        ),
        SocialMediaPost(
            content='EUR/USD breaking resistance levels',
            platform='Reddit',
            author='analyst456',
            posted_at=datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc),
            post_id='reddit_1',
            engagement_score=23.0,
            symbols=['EUR/USD']
        )
    ]


@pytest.fixture
def sample_sentiment_results():
    """Create sample sentiment results for testing"""
    return [
        SentimentResult(
            symbol='EUR/USD',
            sentiment_score=0.7,
            confidence=0.8,
            reasoning='Positive economic indicators support bullish sentiment',
            sources=['news_1', 'social_1'],
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        ),
        SentimentResult(
            symbol='EUR/USD',
            sentiment_score=0.3,
            confidence=0.6,
            reasoning='Mixed signals from recent data',
            sources=['news_2'],
            timestamp=datetime(2024, 1, 1, 13, 0, 0, tzinfo=timezone.utc)
        )
    ]


class TestDataStorage:
    """Test cases for DataStorage class"""
    
    @pytest.mark.asyncio
    async def test_initialize_success(self, mock_config):
        """Test successful database initialization"""
        storage = DataStorage(mock_config)
        
        with patch('src.data.storage.create_async_engine') as mock_engine, \
             patch('src.data.storage.sessionmaker') as mock_sessionmaker:
            
            mock_engine.return_value = Mock()
            mock_sessionmaker.return_value = Mock()
            
            # Mock the engine.begin() context manager
            mock_conn = Mock()
            mock_conn.run_sync = AsyncMock()
            mock_engine.return_value.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.return_value.begin.return_value.__aexit__ = AsyncMock(return_value=None)
            
            await storage.initialize()
            
            assert storage.engine is not None
            assert storage.async_session is not None
            mock_engine.assert_called_once()
            mock_sessionmaker.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_failure(self, mock_config):
        """Test database initialization failure"""
        storage = DataStorage(mock_config)
        
        with patch('src.data.storage.create_async_engine', side_effect=Exception("Connection failed")):
            with pytest.raises(DatabaseError) as exc_info:
                await storage.initialize()
            
            assert "Database initialization failed" in str(exc_info.value)
            assert exc_info.value.error_code == "DB_INIT_FAILED"
    
    @pytest.mark.asyncio
    async def test_store_market_data_success(self, mock_config, sample_market_data):
        """Test successful market data storage"""
        storage = DataStorage(mock_config)
        
        # Mock the async session and execute result
        mock_result = Mock()
        mock_result.fetchone.return_value = None  # No existing data
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.add = Mock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await storage.store_market_data(sample_market_data)
        
        assert result == 2  # Should store 2 records
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_store_market_data_empty_list(self, mock_config):
        """Test storing empty market data list"""
        storage = DataStorage(mock_config)
        
        result = await storage.store_market_data([])
        
        assert result == 0
    
    @pytest.mark.asyncio
    async def test_store_market_data_failure(self, mock_config, sample_market_data):
        """Test market data storage failure"""
        storage = DataStorage(mock_config)
        
        # Mock session that raises an exception
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        with pytest.raises(DatabaseError) as exc_info:
            await storage.store_market_data(sample_market_data)
        
        assert "Failed to store market data" in str(exc_info.value)
        assert exc_info.value.error_code == "MARKET_DATA_STORE_FAILED"
    
    @pytest.mark.asyncio
    async def test_store_news_data_success(self, mock_config, sample_news_articles):
        """Test successful news data storage"""
        storage = DataStorage(mock_config)
        
        # Mock the async session and execute result
        mock_result = Mock()
        mock_result.fetchone.return_value = None  # No existing data
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.add = Mock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await storage.store_news_data(sample_news_articles)
        
        assert result == 2  # Should store 2 records
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_store_social_media_data_success(self, mock_config, sample_social_media_posts):
        """Test successful social media data storage"""
        storage = DataStorage(mock_config)
        
        # Mock the async session and execute result
        mock_result = Mock()
        mock_result.fetchone.return_value = None  # No existing data
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        mock_session.add = Mock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await storage.store_social_media_data(sample_social_media_posts)
        
        assert result == 2  # Should store 2 records
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_store_sentiment_data_success(self, mock_config, sample_sentiment_results):
        """Test successful sentiment data storage"""
        storage = DataStorage(mock_config)
        
        # Mock the async session
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session.add = Mock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await storage.store_sentiment_data(sample_sentiment_results)
        
        assert result == 2  # Should store 2 records
        assert mock_session.add.call_count == 2
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_market_data_success(self, mock_config):
        """Test successful market data retrieval"""
        storage = DataStorage(mock_config)
        
        # Mock database rows
        mock_row1 = Mock()
        mock_row1.symbol = 'EUR/USD'
        mock_row1.timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_row1.open = 1.1000
        mock_row1.high = 1.1050
        mock_row1.low = 1.0950
        mock_row1.close = 1.1025
        mock_row1.volume = 1000
        mock_row1.bid = 1.1020
        mock_row1.ask = 1.1025
        mock_row1.spread = 0.0005
        
        mock_result = Mock()
        mock_result.fetchall.return_value = [mock_row1]
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        
        result = await storage.get_market_data('EUR/USD', start_time, end_time)
        
        assert len(result) == 1
        assert isinstance(result[0], MarketData)
        assert result[0].symbol == 'EUR/USD'
        assert result[0].open == 1.1000
    
    @pytest.mark.asyncio
    async def test_get_market_data_failure(self, mock_config):
        """Test market data retrieval failure"""
        storage = DataStorage(mock_config)
        
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        start_time = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 1, 14, 0, 0, tzinfo=timezone.utc)
        
        with pytest.raises(DatabaseError) as exc_info:
            await storage.get_market_data('EUR/USD', start_time, end_time)
        
        assert "Failed to retrieve market data" in str(exc_info.value)
        assert exc_info.value.error_code == "MARKET_DATA_RETRIEVE_FAILED"


class TestCacheManager:
    """Test cases for CacheManager class"""
    
    @pytest.mark.asyncio
    async def test_cache_set_and_get_memory(self, mock_config):
        """Test setting and getting from memory cache"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        test_key = "test_key"
        test_value = {"data": "test_data"}
        
        await cache_manager.set(test_key, test_value)
        
        # Should retrieve from memory cache
        result = await cache_manager.get(test_key)
        
        assert result == test_value
        assert test_key in cache_manager._memory_cache
    
    @pytest.mark.asyncio
    async def test_cache_get_database_fallback(self, mock_config):
        """Test getting from database when not in memory cache"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        # Mock database cache hit
        mock_row = Mock()
        mock_row.data = {"data": "test_data"}
        mock_row.expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        
        mock_result = Mock()
        mock_result.fetchone.return_value = mock_row
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await cache_manager.get("test_key")
        
        assert result == {"data": "test_data"}
        # Should now be in memory cache
        assert "test_key" in cache_manager._memory_cache
    
    @pytest.mark.asyncio
    async def test_cache_miss(self, mock_config):
        """Test cache miss (not found in memory or database)"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        # Mock database cache miss
        mock_result = Mock()
        mock_result.fetchone.return_value = None
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await cache_manager.get("nonexistent_key")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_cache_expired_entry(self, mock_config):
        """Test handling of expired cache entries"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        test_key = "test_key"
        test_value = {"data": "test_data"}
        
        # Set cache entry with very short TTL
        await cache_manager.set(test_key, test_value, timedelta(microseconds=1))
        
        # Wait for expiration
        await asyncio.sleep(0.001)
        
        # Mock database to return None (expired entry cleaned up)
        mock_result = Mock()
        mock_result.fetchone.return_value = None
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await cache_manager.get(test_key)
        
        assert result is None
        assert test_key not in cache_manager._memory_cache
    
    @pytest.mark.asyncio
    async def test_cache_delete(self, mock_config):
        """Test cache deletion"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        test_key = "test_key"
        test_value = {"data": "test_data"}
        
        # Set cache entry
        await cache_manager.set(test_key, test_value)
        assert test_key in cache_manager._memory_cache
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Delete cache entry
        await cache_manager.delete(test_key)
        
        assert test_key not in cache_manager._memory_cache
        mock_session.execute.assert_called()
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cache_clear(self, mock_config):
        """Test clearing all cache entries"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        # Set multiple cache entries
        await cache_manager.set("key1", {"data": "data1"})
        await cache_manager.set("key2", {"data": "data2"})
        
        assert len(cache_manager._memory_cache) == 2
        
        # Mock database session
        mock_session = AsyncMock()
        mock_session.commit = AsyncMock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        # Clear cache
        await cache_manager.clear()
        
        assert len(cache_manager._memory_cache) == 0
        mock_session.execute.assert_called()
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_expired(self, mock_config):
        """Test cleanup of expired cache entries"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        # Add expired entry to memory cache
        expired_key = "expired_key"
        cache_manager._memory_cache[expired_key] = {
            'data': {"data": "expired_data"},
            'expires_at': datetime.now(timezone.utc) - timedelta(minutes=1)
        }
        
        # Add valid entry to memory cache
        valid_key = "valid_key"
        cache_manager._memory_cache[valid_key] = {
            'data': {"data": "valid_data"},
            'expires_at': datetime.now(timezone.utc) + timedelta(minutes=10)
        }
        
        # Mock database cleanup
        mock_result = Mock()
        mock_result.rowcount = 3  # 3 expired entries in database
        
        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await cache_manager.cleanup_expired()
        
        # Should clean 1 from memory + 3 from database = 4 total
        assert result == 4
        assert expired_key not in cache_manager._memory_cache
        assert valid_key in cache_manager._memory_cache


class TestDataRetentionManager:
    """Test cases for DataRetentionManager class"""
    
    @pytest.mark.asyncio
    async def test_cleanup_old_data_success(self, mock_config):
        """Test successful cleanup of old data"""
        storage = DataStorage(mock_config)
        retention_manager = DataRetentionManager(storage)
        
        # Mock database cleanup results
        mock_results = [Mock(rowcount=10), Mock(rowcount=5), Mock(rowcount=3), 
                       Mock(rowcount=8), Mock(rowcount=2)]
        
        mock_session = AsyncMock()
        mock_session.execute.side_effect = mock_results
        mock_session.commit = AsyncMock()
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await retention_manager.cleanup_old_data()
        
        expected_result = {
            'market_data': 10,
            'news_data': 5,
            'social_media_data': 3,
            'sentiment_data': 8,
            'cache_entries': 2
        }
        
        assert result == expected_result
        assert mock_session.execute.call_count == 5
        mock_session.commit.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_cleanup_old_data_failure(self, mock_config):
        """Test cleanup failure"""
        storage = DataStorage(mock_config)
        retention_manager = DataRetentionManager(storage)
        
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        with pytest.raises(DatabaseError) as exc_info:
            await retention_manager.cleanup_old_data()
        
        assert "Data cleanup failed" in str(exc_info.value)
        assert exc_info.value.error_code == "DATA_CLEANUP_FAILED"
    
    @pytest.mark.asyncio
    async def test_get_storage_stats_success(self, mock_config):
        """Test successful retrieval of storage statistics"""
        storage = DataStorage(mock_config)
        retention_manager = DataRetentionManager(storage)
        
        # Mock database query results
        count_results = [Mock(fetchone=Mock(return_value=[100])),  # market_data count
                        Mock(fetchone=Mock(return_value=[50])),   # news_data count
                        Mock(fetchone=Mock(return_value=[25])),   # social_media_data count
                        Mock(fetchone=Mock(return_value=[75])),   # sentiment_data count
                        Mock(fetchone=Mock(return_value=[10]))]   # cache_entries count
        
        oldest_results = [Mock(fetchone=Mock(return_value=[datetime(2023, 1, 1, tzinfo=timezone.utc)])),
                         Mock(fetchone=Mock(return_value=[datetime(2023, 6, 1, tzinfo=timezone.utc)])),
                         Mock(fetchone=Mock(return_value=[datetime(2023, 11, 1, tzinfo=timezone.utc)])),
                         Mock(fetchone=Mock(return_value=[datetime(2023, 3, 1, tzinfo=timezone.utc)]))]
        
        newest_results = [Mock(fetchone=Mock(return_value=[datetime(2024, 1, 1, tzinfo=timezone.utc)])),
                         Mock(fetchone=Mock(return_value=[datetime(2024, 1, 2, tzinfo=timezone.utc)])),
                         Mock(fetchone=Mock(return_value=[datetime(2024, 1, 3, tzinfo=timezone.utc)])),
                         Mock(fetchone=Mock(return_value=[datetime(2024, 1, 4, tzinfo=timezone.utc)]))]
        
        cache_stats_result = Mock(fetchone=Mock(return_value=[5.5, 20]))  # avg_access, max_access
        
        all_results = count_results + oldest_results + newest_results + [cache_stats_result]
        
        mock_session = AsyncMock()
        mock_session.execute.side_effect = all_results
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await retention_manager.get_storage_stats()
        
        assert result['market_data_count'] == 100
        assert result['news_data_count'] == 50
        assert result['social_media_data_count'] == 25
        assert result['sentiment_data_count'] == 75
        assert result['cache_entries_count'] == 10
        assert result['cache_avg_access'] == 5.5
        assert result['cache_max_access'] == 20
    
    @pytest.mark.asyncio
    async def test_get_storage_stats_failure(self, mock_config):
        """Test storage stats retrieval failure"""
        storage = DataStorage(mock_config)
        retention_manager = DataRetentionManager(storage)
        
        mock_session = AsyncMock()
        mock_session.execute.side_effect = Exception("Database error")
        
        storage.async_session = Mock(return_value=mock_session)
        storage.async_session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        storage.async_session.return_value.__aexit__ = AsyncMock(return_value=None)
        
        result = await retention_manager.get_storage_stats()
        
        assert 'error' in result
        assert result['error'] == "Database error"


if __name__ == '__main__':
    pytest.main([__file__])

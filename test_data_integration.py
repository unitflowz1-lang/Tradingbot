"""Integration tests for data storage and caching system"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, patch

from src.data.data_manager import DataManager
from src.models import MarketData, SentimentResult
from src.data.news_data_collector import NewsArticle
from src.data.social_media_collector import SocialMediaPost
from src.config import Config, DatabaseConfig, TradingConfig, LLMConfig, RiskConfig, BrokerConfig


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


class TestDataManagerIntegration:
    """Integration tests for DataManager"""
    
    def test_data_manager_initialization(self, mock_config):
        """Test DataManager initialization"""
        data_manager = DataManager(mock_config)
        
        assert data_manager.config == mock_config
        assert data_manager.storage is not None
        assert data_manager.cache_manager is not None
        assert data_manager.retention_manager is not None
        # Collectors are created in the context manager, so they start as None
        assert data_manager.market_data_collector is None
        assert data_manager.news_data_collector is None
        assert data_manager.social_media_collector is None
    
    @pytest.mark.asyncio
    async def test_data_manager_context_manager(self, mock_config):
        """Test DataManager data collectors context manager"""
        data_manager = DataManager(mock_config)
        
        async with data_manager.get_data_collectors() as collectors:
            assert 'market' in collectors
            assert 'news' in collectors
            assert 'social' in collectors
            
            assert collectors['market'] is not None
            assert collectors['news'] is not None
            assert collectors['social'] is not None
    
    @pytest.mark.asyncio
    async def test_store_sentiment_data_with_caching(self, mock_config):
        """Test storing sentiment data with caching"""
        data_manager = DataManager(mock_config)
        
        # Mock the storage layer
        with patch.object(data_manager.storage, 'store_sentiment_data') as mock_store, \
             patch.object(data_manager.cache_manager, 'set') as mock_cache_set:
            
            mock_store.return_value = 2
            
            sentiment_results = [
                SentimentResult(
                    symbol='EUR/USD',
                    sentiment_score=0.7,
                    confidence=0.8,
                    reasoning='Positive sentiment',
                    sources=['news_1'],
                    timestamp=datetime.now(timezone.utc)
                ),
                SentimentResult(
                    symbol='GBP/USD',
                    sentiment_score=0.3,
                    confidence=0.6,
                    reasoning='Mixed sentiment',
                    sources=['news_2'],
                    timestamp=datetime.now(timezone.utc)
                )
            ]
            
            result = await data_manager.store_sentiment_data(sentiment_results)
            
            assert result == 2
            mock_store.assert_called_once_with(sentiment_results)
            # Should cache latest sentiment for each symbol
            assert mock_cache_set.call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_market_data_with_caching(self, mock_config):
        """Test retrieving market data with caching"""
        data_manager = DataManager(mock_config)
        
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        end_time = datetime.now(timezone.utc)
        
        market_data = [
            MarketData(
                symbol='EUR/USD',
                timestamp=datetime.now(timezone.utc),
                open=1.1000,
                high=1.1050,
                low=1.0950,
                close=1.1025,
                volume=1000,
                bid=1.1020,
                ask=1.1025,
                spread=0.0005
            )
        ]
        
        # Mock cache miss, then database hit
        with patch.object(data_manager.cache_manager, 'get') as mock_cache_get, \
             patch.object(data_manager.storage, 'get_market_data') as mock_storage_get, \
             patch.object(data_manager.cache_manager, 'set') as mock_cache_set:
            
            mock_cache_get.return_value = None  # Cache miss
            mock_storage_get.return_value = market_data
            
            result = await data_manager.get_market_data('EUR/USD', start_time, end_time)
            
            assert result == market_data
            mock_cache_get.assert_called_once()
            mock_storage_get.assert_called_once_with('EUR/USD', start_time, end_time)
            mock_cache_set.assert_called_once()  # Should cache the result
    
    @pytest.mark.asyncio
    async def test_get_market_data_cache_hit(self, mock_config):
        """Test retrieving market data from cache"""
        data_manager = DataManager(mock_config)
        
        start_time = datetime.now(timezone.utc) - timedelta(hours=1)
        end_time = datetime.now(timezone.utc)
        
        cached_data = [
            MarketData(
                symbol='EUR/USD',
                timestamp=datetime.now(timezone.utc),
                open=1.1000,
                high=1.1050,
                low=1.0950,
                close=1.1025,
                volume=1000,
                bid=1.1020,
                ask=1.1025,
                spread=0.0005
            )
        ]
        
        # Mock cache hit
        with patch.object(data_manager.cache_manager, 'get') as mock_cache_get, \
             patch.object(data_manager.storage, 'get_market_data') as mock_storage_get:
            
            mock_cache_get.return_value = cached_data  # Cache hit
            
            result = await data_manager.get_market_data('EUR/USD', start_time, end_time)
            
            assert result == cached_data
            mock_cache_get.assert_called_once()
            mock_storage_get.assert_not_called()  # Should not hit database
    
    @pytest.mark.asyncio
    async def test_get_latest_data_summary(self, mock_config):
        """Test getting latest data summary"""
        data_manager = DataManager(mock_config)
        
        symbols = ['EUR/USD', 'GBP/USD']
        
        # Mock various data sources
        with patch.object(data_manager, 'get_market_data') as mock_market, \
             patch.object(data_manager.cache_manager, 'get') as mock_cache, \
             patch.object(data_manager, 'get_news_data') as mock_news, \
             patch.object(data_manager, 'get_social_media_data') as mock_social:
            
            # Mock market data
            mock_market.return_value = [
                MarketData(
                    symbol='EUR/USD',
                    timestamp=datetime.now(timezone.utc),
                    open=1.1000,
                    high=1.1050,
                    low=1.0950,
                    close=1.1025,
                    volume=1000,
                    bid=1.1020,
                    ask=1.1025,
                    spread=0.0005
                )
            ]
            
            # Mock cached sentiment
            mock_cache.return_value = SentimentResult(
                symbol='EUR/USD',
                sentiment_score=0.7,
                confidence=0.8,
                reasoning='Positive sentiment',
                sources=['news_1'],
                timestamp=datetime.now(timezone.utc)
            )
            
            # Mock news and social data
            mock_news.return_value = [Mock(), Mock()]  # 2 news articles
            mock_social.return_value = [Mock()]  # 1 social post
            
            result = await data_manager.get_latest_data_summary(symbols)
            
            assert 'EUR/USD' in result
            assert 'GBP/USD' in result
            
            eur_usd_summary = result['EUR/USD']
            assert 'latest_market_data' in eur_usd_summary
            assert 'latest_sentiment' in eur_usd_summary
            assert 'news_count_24h' in eur_usd_summary
            assert 'social_posts_24h' in eur_usd_summary
            
            assert eur_usd_summary['latest_market_data']['close'] == 1.1025
            assert eur_usd_summary['latest_sentiment']['score'] == 0.7
            assert eur_usd_summary['news_count_24h'] == 2
            assert eur_usd_summary['social_posts_24h'] == 1


class TestDataStorageIntegration:
    """Integration tests for data storage components"""
    
    @pytest.mark.asyncio
    async def test_cache_memory_flow(self, mock_config):
        """Test memory cache functionality"""
        from src.data.storage import DataStorage, CacheManager
        
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        test_key = "integration_test_key"
        test_value = {"integration": "test_data", "timestamp": datetime.now(timezone.utc).isoformat()}
        
        # Mock database operations to avoid actual database calls
        with patch.object(storage, 'async_session') as mock_session_factory:
            # Create a simple mock that doesn't trigger warnings
            mock_session = Mock()
            mock_result = Mock()
            mock_session.execute.return_value = mock_result
            mock_session.commit = Mock()
            
            # Simple async context manager
            class SimpleAsyncContext:
                def __init__(self, session):
                    self.session = session
                
                async def __aenter__(self):
                    return self.session
                
                async def __aexit__(self, *args):
                    pass
            
            mock_session_factory.return_value = SimpleAsyncContext(mock_session)
            
            # Test memory cache set and get
            await cache_manager.set(test_key, test_value, timedelta(minutes=5))
            
            # Verify it's in memory cache
            assert test_key in cache_manager._memory_cache
            
            # Get from memory cache
            result = await cache_manager.get(test_key)
            assert result == test_value
    
    def test_retention_policies_configuration(self, mock_config):
        """Test that retention policies are properly configured"""
        from src.data.storage import DataStorage, DataRetentionManager
        
        storage = DataStorage(mock_config)
        retention_manager = DataRetentionManager(storage)
        
        # Verify retention policies exist for all data types
        expected_tables = [
            'market_data',
            'news_data', 
            'social_media_data',
            'sentiment_data',
            'cache_entries'
        ]
        
        for table in expected_tables:
            assert table in storage.retention_policies
            assert isinstance(storage.retention_policies[table], int)
            assert storage.retention_policies[table] > 0
        
        # Verify reasonable retention periods
        assert storage.retention_policies['market_data'] >= 365  # At least 1 year
        assert storage.retention_policies['news_data'] >= 30     # At least 1 month
        assert storage.retention_policies['social_media_data'] >= 7  # At least 1 week
        assert storage.retention_policies['sentiment_data'] >= 30    # At least 1 month
        assert storage.retention_policies['cache_entries'] >= 1      # At least 1 day


if __name__ == '__main__':
    pytest.main([__file__])
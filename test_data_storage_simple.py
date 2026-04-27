"""Simplified tests for data storage system"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from src.data.storage import DataStorage, CacheManager, DataRetentionManager
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


@pytest.fixture
def sample_market_data():
    """Create sample market data for testing"""
    return [
        MarketData(
            symbol='EUR/USD',
            timestamp=datetime(2024, 1, 1, 12, 0, 0),
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


class TestDataStorageBasic:
    """Basic tests for DataStorage functionality"""
    
    def test_data_storage_initialization(self, mock_config):
        """Test DataStorage initialization"""
        storage = DataStorage(mock_config)
        
        assert storage.config == mock_config
        assert storage.engine is None
        assert storage.async_session is None
        assert isinstance(storage.retention_policies, dict)
        assert 'market_data' in storage.retention_policies
        assert 'news_data' in storage.retention_policies
        assert 'social_media_data' in storage.retention_policies
        assert 'sentiment_data' in storage.retention_policies
        assert 'cache_entries' in storage.retention_policies
    
    def test_retention_policies(self, mock_config):
        """Test retention policies are properly configured"""
        storage = DataStorage(mock_config)
        
        expected_policies = {
            'market_data': 365,  # 1 year
            'news_data': 90,     # 3 months
            'social_media_data': 30,  # 1 month
            'sentiment_data': 180,    # 6 months
            'cache_entries': 7        # 1 week
        }
        
        assert storage.retention_policies == expected_policies
    
    @pytest.mark.asyncio
    async def test_store_empty_market_data(self, mock_config):
        """Test storing empty market data list"""
        storage = DataStorage(mock_config)
        
        result = await storage.store_market_data([])
        
        assert result == 0
    
    @pytest.mark.asyncio
    async def test_store_empty_news_data(self, mock_config):
        """Test storing empty news data list"""
        storage = DataStorage(mock_config)
        
        result = await storage.store_news_data([])
        
        assert result == 0
    
    @pytest.mark.asyncio
    async def test_store_empty_social_media_data(self, mock_config):
        """Test storing empty social media data list"""
        storage = DataStorage(mock_config)
        
        result = await storage.store_social_media_data([])
        
        assert result == 0
    
    @pytest.mark.asyncio
    async def test_store_empty_sentiment_data(self, mock_config):
        """Test storing empty sentiment data list"""
        storage = DataStorage(mock_config)
        
        result = await storage.store_sentiment_data([])
        
        assert result == 0


class TestCacheManagerBasic:
    """Basic tests for CacheManager functionality"""
    
    def test_cache_manager_initialization(self, mock_config):
        """Test CacheManager initialization"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        assert cache_manager.storage == storage
        assert isinstance(cache_manager._memory_cache, dict)
        assert len(cache_manager._memory_cache) == 0
        assert cache_manager._default_ttl == timedelta(minutes=15)
    
    @pytest.mark.asyncio
    async def test_memory_cache_set_get(self, mock_config):
        """Test basic memory cache set and get operations"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        test_key = "test_key"
        test_value = {"data": "test_data"}
        
        # Set in memory cache directly
        cache_manager._memory_cache[test_key] = {
            'data': test_value,
            'expires_at': datetime.now(timezone.utc) + timedelta(minutes=10)
        }
        
        # Should retrieve from memory cache
        result = await cache_manager.get(test_key)
        
        assert result == test_value
    
    @pytest.mark.asyncio
    async def test_memory_cache_expired(self, mock_config):
        """Test expired memory cache entry"""
        storage = DataStorage(mock_config)
        cache_manager = CacheManager(storage)
        
        test_key = "test_key"
        test_value = {"data": "test_data"}
        
        # Set expired entry in memory cache
        cache_manager._memory_cache[test_key] = {
            'data': test_value,
            'expires_at': datetime.now(timezone.utc) - timedelta(minutes=1)
        }
        
        # Mock database to return None (no fallback)
        with patch.object(storage, 'async_session') as mock_session_factory:
            mock_session = AsyncMock()
            mock_result = AsyncMock()
            mock_result.fetchone.return_value = None
            mock_session.execute.return_value = mock_result
            
            mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session_factory.return_value.__aexit__ = AsyncMock(return_value=None)
            
            result = await cache_manager.get(test_key)
            
            assert result is None
            assert test_key not in cache_manager._memory_cache  # Should be removed


class TestDataRetentionManagerBasic:
    """Basic tests for DataRetentionManager functionality"""
    
    def test_retention_manager_initialization(self, mock_config):
        """Test DataRetentionManager initialization"""
        storage = DataStorage(mock_config)
        retention_manager = DataRetentionManager(storage)
        
        assert retention_manager.storage == storage


class TestDataModels:
    """Test database model creation and validation"""
    
    def test_market_data_model_creation(self):
        """Test MarketDataModel can be created"""
        from src.data.storage import MarketDataModel
        
        model = MarketDataModel(
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
        
        assert model.symbol == 'EUR/USD'
        assert model.open == 1.1000
        assert model.volume == 1000
    
    def test_news_data_model_creation(self):
        """Test NewsDataModel can be created"""
        from src.data.storage import NewsDataModel
        
        model = NewsDataModel(
            title='Test News',
            content='Test content',
            source='Test Source',
            published_at=datetime.now(timezone.utc),
            url='https://test.com',
            symbols=['EUR/USD']
        )
        
        assert model.title == 'Test News'
        assert model.source == 'Test Source'
        assert model.symbols == ['EUR/USD']
    
    def test_social_media_model_creation(self):
        """Test SocialMediaDataModel can be created"""
        from src.data.storage import SocialMediaDataModel
        
        model = SocialMediaDataModel(
            content='Test post',
            platform='Twitter',
            author='test_user',
            posted_at=datetime.now(timezone.utc),
            post_id='test_123',
            engagement_score=45.0,
            symbols=['EUR/USD']
        )
        
        assert model.content == 'Test post'
        assert model.platform == 'Twitter'
        assert model.engagement_score == 45.0
    
    def test_sentiment_data_model_creation(self):
        """Test SentimentDataModel can be created"""
        from src.data.storage import SentimentDataModel
        
        model = SentimentDataModel(
            symbol='EUR/USD',
            sentiment_score=0.7,
            confidence=0.8,
            reasoning='Positive sentiment',
            sources=['news_1'],
            timestamp=datetime.now(timezone.utc)
        )
        
        assert model.symbol == 'EUR/USD'
        assert model.sentiment_score == 0.7
        assert model.confidence == 0.8
    
    def test_cache_entry_model_creation(self):
        """Test CacheEntryModel can be created"""
        from src.data.storage import CacheEntryModel
        
        model = CacheEntryModel(
            cache_key='test_key',
            data={'test': 'data'},
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10)
        )
        
        assert model.cache_key == 'test_key'
        assert model.data == {'test': 'data'}
        assert model.access_count == 0


if __name__ == '__main__':
    pytest.main([__file__])
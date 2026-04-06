"""Unit tests for SocialMediaCollector"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from src.data.social_media_collector import SocialMediaCollector, SocialMediaPost
from src.config import Config, TradingConfig, LLMConfig, RiskConfig, BrokerConfig, DatabaseConfig
from src.exceptions import DataValidationError, APIError


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing"""
    return Config(
        trading=TradingConfig(
            supported_pairs=['EUR/USD', 'GBP/USD', 'USD/JPY'],
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
            broker_name='test',
            api_key='test',
            api_secret='test',
            base_url='test',
            timeout=30
        ),
        database=DatabaseConfig(
            host='localhost',
            port=5432,
            database='test',
            username='test',
            password='test'
        ),
        api_timeout=30
    )


@pytest.fixture
def social_media_collector(mock_config):
    """Create a SocialMediaCollector instance for testing"""
    return SocialMediaCollector(mock_config)


class TestSocialMediaPost:
    """Test SocialMediaPost class"""

    def test_social_media_post_creation(self):
        """Test creating a valid social media post"""
        post = SocialMediaPost(
            content="Bullish on EUR/USD! #forex #trading",
            platform="Twitter",
            author="TestUser",
            posted_at=datetime.now() - timedelta(hours=1),
            post_id="test_123",
            engagement_score=25.0,
            symbols=["EUR/USD"]
        )
        
        assert post.content == "Bullish on EUR/USD! #forex #trading"
        assert post.platform == "Twitter"
        assert post.author == "TestUser"
        assert post.post_id == "test_123"
        assert post.engagement_score == 25.0
        assert post.symbols == ["EUR/USD"]
        assert post.processed_content == ""

    def test_social_media_post_validation_empty_content(self):
        """Test validation fails for empty content"""
        with pytest.raises(DataValidationError) as exc_info:
            post = SocialMediaPost(
                content="",
                platform="Twitter",
                author="TestUser",
                posted_at=datetime.now() - timedelta(hours=1),
                post_id="test_123"
            )
            post.validate()
        
        assert exc_info.value.error_code == "EMPTY_CONTENT"

    def test_social_media_post_validation_empty_platform(self):
        """Test validation fails for empty platform"""
        with pytest.raises(DataValidationError) as exc_info:
            post = SocialMediaPost(
                content="Test content",
                platform="",
                author="TestUser",
                posted_at=datetime.now() - timedelta(hours=1),
                post_id="test_123"
            )
            post.validate()
        
        assert exc_info.value.error_code == "EMPTY_PLATFORM"

    def test_social_media_post_validation_negative_engagement(self):
        """Test validation fails for negative engagement score"""
        with pytest.raises(DataValidationError) as exc_info:
            post = SocialMediaPost(
                content="Test content",
                platform="Twitter",
                author="TestUser",
                posted_at=datetime.now() - timedelta(hours=1),
                post_id="test_123",
                engagement_score=-5.0
            )
            post.validate()
        
        assert exc_info.value.error_code == "NEGATIVE_ENGAGEMENT"

    def test_social_media_post_validation_future_timestamp(self):
        """Test validation fails for future timestamp"""
        with pytest.raises(DataValidationError) as exc_info:
            post = SocialMediaPost(
                content="Test content",
                platform="Twitter",
                author="TestUser",
                posted_at=datetime.now() + timedelta(hours=1),
                post_id="test_123"
            )
            post.validate()
        
        assert exc_info.value.error_code == "FUTURE_TIMESTAMP"


class TestSocialMediaCollector:
    """Test SocialMediaCollector class"""

    @pytest.mark.asyncio
    async def test_collect_data_success(self, social_media_collector):
        """Test successful data collection"""
        symbols = ["EUR/USD", "GBP/USD"]
        
        # Mock the _fetch_social_media_data method
        with patch.object(social_media_collector, '_fetch_social_media_data') as mock_fetch:
            mock_posts = [
                SocialMediaPost(
                    content="Bullish on EUR/USD! #forex",
                    platform="Twitter",
                    author="TestUser",
                    posted_at=datetime.now() - timedelta(hours=1),
                    post_id="test_123",
                    engagement_score=25.0,
                    symbols=["EUR/USD"]
                )
            ]
            mock_fetch.return_value = mock_posts
            
            # Mock the _process_posts method
            with patch.object(social_media_collector, '_process_posts') as mock_process:
                mock_process.return_value = mock_posts
                
                result = await social_media_collector.collect_data(symbols)
                
                assert len(result) == 2
                assert "EUR/USD" in result
                assert "GBP/USD" in result
                assert len(result["EUR/USD"]) == 1
                assert result["EUR/USD"][0].content == "Bullish on EUR/USD! #forex"

    @pytest.mark.asyncio
    async def test_collect_data_empty_symbols(self, social_media_collector):
        """Test collect_data with empty symbols list"""
        with pytest.raises(DataValidationError) as exc_info:
            await social_media_collector.collect_data([])
        
        assert exc_info.value.error_code == "EMPTY_SYMBOLS"

    @pytest.mark.asyncio
    async def test_collect_data_with_cache(self, social_media_collector):
        """Test data collection uses cache when available"""
        symbols = ["EUR/USD"]
        
        # Set up cache
        cached_posts = [
            SocialMediaPost(
                content="Cached post about EUR/USD",
                platform="Twitter",
                author="CachedUser",
                posted_at=datetime.now() - timedelta(minutes=5),
                post_id="cached_123",
                engagement_score=15.0,
                symbols=["EUR/USD"]
            )
        ]
        social_media_collector.cache["EUR/USD"] = cached_posts
        
        result = await social_media_collector.collect_data(symbols)
        
        assert len(result) == 1
        assert "EUR/USD" in result
        assert result["EUR/USD"][0].content == "Cached post about EUR/USD"

    @pytest.mark.asyncio
    async def test_validate_data_success(self, social_media_collector):
        """Test successful data validation"""
        valid_data = {
            "EUR/USD": [
                SocialMediaPost(
                    content="Valid post about forex",
                    platform="Twitter",
                    author="ValidUser",
                    posted_at=datetime.now() - timedelta(hours=1),
                    post_id="valid_123",
                    engagement_score=20.0,
                    symbols=["EUR/USD"]
                )
            ]
        }
        
        result = await social_media_collector.validate_data(valid_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_data_empty(self, social_media_collector):
        """Test validation with empty data"""
        result = await social_media_collector.validate_data({})
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_data_invalid_type(self, social_media_collector):
        """Test validation fails with invalid data type"""
        invalid_data = {
            "EUR/USD": "not a list"
        }
        
        result = await social_media_collector.validate_data(invalid_data)
        assert result is False

    @pytest.mark.asyncio
    async def test_validate_data_old_post(self, social_media_collector):
        """Test validation fails with old post"""
        old_data = {
            "EUR/USD": [
                SocialMediaPost(
                    content="Old post",
                    platform="Twitter",
                    author="OldUser",
                    posted_at=datetime.now() - timedelta(days=2),
                    post_id="old_123",
                    engagement_score=20.0
                )
            ]
        }
        
        result = await social_media_collector.validate_data(old_data)
        assert result is False

    def test_clean_text(self, social_media_collector):
        """Test text cleaning functionality"""
        dirty_text = "Check out this link https://example.com @username #forex and some text!"
        clean_text = social_media_collector._clean_text(dirty_text)
        
        assert "https://example.com" not in clean_text
        assert "@username" not in clean_text
        assert "#forex" in clean_text  # Hashtags should be preserved
        assert "Check out this link" in clean_text

    def test_is_forex_relevant_hashtag(self, social_media_collector):
        """Test forex relevance detection with hashtags"""
        post = SocialMediaPost(
            content="Great trading day! #forex #eurusd",
            platform="Twitter",
            author="TestUser",
            posted_at=datetime.now() - timedelta(hours=1),
            post_id="test_123"
        )
        post.processed_content = post.content
        
        result = social_media_collector._is_forex_relevant(post)
        assert result is True

    def test_is_forex_relevant_keyword(self, social_media_collector):
        """Test forex relevance detection with keywords"""
        post = SocialMediaPost(
            content="The central bank policy will affect currency markets",
            platform="Twitter",
            author="TestUser",
            posted_at=datetime.now() - timedelta(hours=1),
            post_id="test_123"
        )
        post.processed_content = post.content
        
        result = social_media_collector._is_forex_relevant(post)
        assert result is True

    def test_is_forex_relevant_currency_pair(self, social_media_collector):
        """Test forex relevance detection with currency pairs"""
        post = SocialMediaPost(
            content="EUR/USD is looking bullish today",
            platform="Twitter",
            author="TestUser",
            posted_at=datetime.now() - timedelta(hours=1),
            post_id="test_123"
        )
        post.processed_content = post.content
        
        result = social_media_collector._is_forex_relevant(post)
        assert result is True

    def test_is_forex_relevant_negative(self, social_media_collector):
        """Test forex relevance detection - negative case"""
        post = SocialMediaPost(
            content="Just had a great lunch with friends!",
            platform="Twitter",
            author="TestUser",
            posted_at=datetime.now() - timedelta(hours=1),
            post_id="test_123"
        )
        post.processed_content = post.content
        
        result = social_media_collector._is_forex_relevant(post)
        assert result is False

    def test_extract_currency_pairs(self, social_media_collector):
        """Test currency pair extraction"""
        text = "EUR/USD and GBP/USD are showing strength while USD/JPY declines"
        pairs = social_media_collector._extract_currency_pairs(text)
        
        assert "EUR/USD" in pairs
        assert "GBP/USD" in pairs
        assert "USD/JPY" in pairs
        assert len(pairs) == 3

    def test_process_posts_engagement_filter(self, social_media_collector):
        """Test post processing filters by engagement score"""
        posts = [
            SocialMediaPost(
                content="High engagement post #forex",
                platform="Twitter",
                author="PopularUser",
                posted_at=datetime.now() - timedelta(hours=1),
                post_id="high_123",
                engagement_score=50.0
            ),
            SocialMediaPost(
                content="Low engagement post #forex",
                platform="Twitter",
                author="UnknownUser",
                posted_at=datetime.now() - timedelta(hours=1),
                post_id="low_123",
                engagement_score=5.0
            )
        ]
        
        # Set processed content for relevance check
        for post in posts:
            post.processed_content = post.content
        
        processed = social_media_collector._process_posts(posts, "EUR/USD")
        
        # Only high engagement post should pass the filter
        assert len(processed) == 1
        assert processed[0].engagement_score == 50.0

    def test_get_time_range(self, social_media_collector):
        """Test time range conversion"""
        assert social_media_collector._get_time_range("1h") == timedelta(hours=1)
        assert social_media_collector._get_time_range("4h") == timedelta(hours=4)
        assert social_media_collector._get_time_range("1d") == timedelta(days=1)
        assert social_media_collector._get_time_range("invalid") == timedelta(hours=4)

    def test_cache_operations(self, social_media_collector):
        """Test cache operations"""
        # Test cache stats
        stats = social_media_collector.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["total_posts"] == 0
        
        # Add to cache
        posts = [
            SocialMediaPost(
                content="Test post",
                platform="Twitter",
                author="TestUser",
                posted_at=datetime.now() - timedelta(minutes=5),
                post_id="test_123",
                engagement_score=15.0
            )
        ]
        social_media_collector.cache["EUR/USD"] = posts
        
        # Test cache stats after adding
        stats = social_media_collector.get_cache_stats()
        assert stats["cache_size"] == 1
        assert stats["total_posts"] == 1
        assert "EUR/USD" in stats["cached_symbols"]
        
        # Test cache clear
        social_media_collector.clear_cache()
        stats = social_media_collector.get_cache_stats()
        assert stats["cache_size"] == 0


if __name__ == "__main__":
    pytest.main([__file__])
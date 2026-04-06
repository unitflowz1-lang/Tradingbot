"""Unit tests for NewsDataCollector"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from src.data.news_data_collector import NewsDataCollector, NewsArticle
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
def news_collector(mock_config):
    """Create a NewsDataCollector instance for testing"""
    return NewsDataCollector(mock_config)


class TestNewsArticle:
    """Test NewsArticle class"""

    def test_news_article_creation(self):
        """Test creating a valid news article"""
        article = NewsArticle(
            title="Test Article",
            content="Test content about forex trading",
            source="Test Source",
            published_at=datetime.now() - timedelta(hours=1),
            url="https://example.com/test",
            symbols=["EUR/USD"]
        )
        
        assert article.title == "Test Article"
        assert article.content == "Test content about forex trading"
        assert article.source == "Test Source"
        assert article.url == "https://example.com/test"
        assert article.symbols == ["EUR/USD"]
        assert article.processed_content == ""

    def test_news_article_validation_empty_title(self):
        """Test validation fails for empty title"""
        with pytest.raises(DataValidationError) as exc_info:
            article = NewsArticle(
                title="",
                content="Test content",
                source="Test Source",
                published_at=datetime.now() - timedelta(hours=1),
                url="https://example.com/test"
            )
            article.validate()
        
        assert exc_info.value.error_code == "EMPTY_TITLE"

    def test_news_article_validation_empty_content(self):
        """Test validation fails for empty content"""
        with pytest.raises(DataValidationError) as exc_info:
            article = NewsArticle(
                title="Test Title",
                content="",
                source="Test Source",
                published_at=datetime.now() - timedelta(hours=1),
                url="https://example.com/test"
            )
            article.validate()
        
        assert exc_info.value.error_code == "EMPTY_CONTENT"

    def test_news_article_validation_future_timestamp(self):
        """Test validation fails for future timestamp"""
        with pytest.raises(DataValidationError) as exc_info:
            article = NewsArticle(
                title="Test Title",
                content="Test content",
                source="Test Source",
                published_at=datetime.now() + timedelta(hours=1),
                url="https://example.com/test"
            )
            article.validate()
        
        assert exc_info.value.error_code == "FUTURE_TIMESTAMP"


class TestNewsDataCollector:
    """Test NewsDataCollector class"""

    @pytest.mark.asyncio
    async def test_collect_data_success(self, news_collector):
        """Test successful data collection"""
        symbols = ["EUR/USD", "GBP/USD"]
        
        # Mock the _fetch_news_data method
        with patch.object(news_collector, '_fetch_news_data') as mock_fetch:
            mock_articles = [
                NewsArticle(
                    title="Test Article 1",
                    content="EUR/USD rises on ECB policy",
                    source="Test Source",
                    published_at=datetime.now() - timedelta(hours=1),
                    url="https://example.com/test1",
                    symbols=["EUR/USD"]
                )
            ]
            mock_fetch.return_value = mock_articles
            
            # Mock the _process_articles method
            with patch.object(news_collector, '_process_articles') as mock_process:
                mock_process.return_value = mock_articles
                
                result = await news_collector.collect_data(symbols)
                
                assert len(result) == 2
                assert "EUR/USD" in result
                assert "GBP/USD" in result
                assert len(result["EUR/USD"]) == 1
                assert result["EUR/USD"][0].title == "Test Article 1"

    @pytest.mark.asyncio
    async def test_collect_data_empty_symbols(self, news_collector):
        """Test collect_data with empty symbols list"""
        with pytest.raises(DataValidationError) as exc_info:
            await news_collector.collect_data([])
        
        assert exc_info.value.error_code == "EMPTY_SYMBOLS"

    @pytest.mark.asyncio
    async def test_collect_data_with_cache(self, news_collector):
        """Test data collection uses cache when available"""
        symbols = ["EUR/USD"]
        
        # Set up cache
        cached_articles = [
            NewsArticle(
                title="Cached Article",
                content="Cached content",
                source="Cache Source",
                published_at=datetime.now() - timedelta(minutes=5),
                url="https://example.com/cached",
                symbols=["EUR/USD"]
            )
        ]
        news_collector.cache["EUR/USD"] = cached_articles
        
        result = await news_collector.collect_data(symbols)
        
        assert len(result) == 1
        assert "EUR/USD" in result
        assert result["EUR/USD"][0].title == "Cached Article"

    @pytest.mark.asyncio
    async def test_validate_data_success(self, news_collector):
        """Test successful data validation"""
        valid_data = {
            "EUR/USD": [
                NewsArticle(
                    title="Valid Article",
                    content="Valid content",
                    source="Valid Source",
                    published_at=datetime.now() - timedelta(hours=1),
                    url="https://example.com/valid",
                    symbols=["EUR/USD"]
                )
            ]
        }
        
        result = await news_collector.validate_data(valid_data)
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_data_empty(self, news_collector):
        """Test validation with empty data"""
        result = await news_collector.validate_data({})
        assert result is True

    @pytest.mark.asyncio
    async def test_validate_data_invalid_type(self, news_collector):
        """Test validation fails with invalid data type"""
        invalid_data = {
            "EUR/USD": "not a list"
        }
        
        result = await news_collector.validate_data(invalid_data)
        assert result is False

    def test_clean_text(self, news_collector):
        """Test text cleaning functionality"""
        dirty_text = "<p>This is a test with <b>HTML</b> tags and   extra   spaces!</p>"
        clean_text = news_collector._clean_text(dirty_text)
        
        assert "<p>" not in clean_text
        assert "<b>" not in clean_text
        assert "This is a test with HTML tags and extra spaces!" in clean_text

    def test_is_forex_relevant_positive(self, news_collector):
        """Test forex relevance detection - positive case"""
        article = NewsArticle(
            title="EUR/USD Analysis",
            content="The EUR/USD pair is showing strong momentum",
            source="Test",
            published_at=datetime.now() - timedelta(hours=1),
            url="https://example.com/test"
        )
        article.processed_content = article.content
        
        result = news_collector._is_forex_relevant(article)
        assert result is True

    def test_is_forex_relevant_negative(self, news_collector):
        """Test forex relevance detection - negative case"""
        article = NewsArticle(
            title="Stock Market News",
            content="Apple stock rises on earnings report",
            source="Test",
            published_at=datetime.now() - timedelta(hours=1),
            url="https://example.com/test"
        )
        article.processed_content = article.content
        
        result = news_collector._is_forex_relevant(article)
        assert result is False

    def test_extract_currency_pairs(self, news_collector):
        """Test currency pair extraction"""
        text = "EUR/USD and GBP/USD are showing strength while USD/JPY declines"
        pairs = news_collector._extract_currency_pairs(text)
        
        assert "EUR/USD" in pairs
        assert "GBP/USD" in pairs
        assert "USD/JPY" in pairs
        assert len(pairs) == 3

    def test_get_time_range(self, news_collector):
        """Test time range conversion"""
        assert news_collector._get_time_range("1h") == timedelta(hours=1)
        assert news_collector._get_time_range("4h") == timedelta(hours=4)
        assert news_collector._get_time_range("1d") == timedelta(days=1)
        assert news_collector._get_time_range("invalid") == timedelta(hours=4)

    def test_cache_operations(self, news_collector):
        """Test cache operations"""
        # Test cache stats
        stats = news_collector.get_cache_stats()
        assert stats["cache_size"] == 0
        assert stats["total_articles"] == 0
        
        # Add to cache
        articles = [
            NewsArticle(
                title="Test",
                content="Test",
                source="Test",
                published_at=datetime.now() - timedelta(minutes=5),
                url="https://example.com/test"
            )
        ]
        news_collector.cache["EUR/USD"] = articles
        
        # Test cache stats after adding
        stats = news_collector.get_cache_stats()
        assert stats["cache_size"] == 1
        assert stats["total_articles"] == 1
        assert "EUR/USD" in stats["cached_symbols"]
        
        # Test cache clear
        news_collector.clear_cache()
        stats = news_collector.get_cache_stats()
        assert stats["cache_size"] == 0


if __name__ == "__main__":
    pytest.main([__file__])
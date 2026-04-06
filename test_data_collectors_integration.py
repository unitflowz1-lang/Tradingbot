"""Integration tests for news and social media data collectors"""

import pytest
import asyncio
from datetime import datetime, timedelta
from src.data.news_data_collector import NewsDataCollector
from src.data.social_media_collector import SocialMediaCollector
from src.config import Config, TradingConfig, LLMConfig, RiskConfig, BrokerConfig, DatabaseConfig


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


class TestDataCollectorsIntegration:
    """Integration tests for data collectors"""

    @pytest.mark.asyncio
    async def test_both_collectors_collect_data(self, mock_config):
        """Test that both collectors can collect data for the same symbols"""
        symbols = ["EUR/USD", "GBP/USD"]
        timeframe = "4h"
        
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        # Collect data from both sources
        news_data = await news_collector.collect_data(symbols, timeframe)
        social_data = await social_collector.collect_data(symbols, timeframe)
        
        # Verify both collectors returned data for all symbols
        assert len(news_data) == len(symbols)
        assert len(social_data) == len(symbols)
        
        for symbol in symbols:
            assert symbol in news_data
            assert symbol in social_data
            
            # Verify data types
            assert isinstance(news_data[symbol], list)
            assert isinstance(social_data[symbol], list)
            
            # Verify data is not empty (mock data should be generated)
            assert len(news_data[symbol]) > 0
            assert len(social_data[symbol]) > 0

    @pytest.mark.asyncio
    async def test_data_validation_consistency(self, mock_config):
        """Test that both collectors validate data consistently"""
        symbols = ["EUR/USD"]
        
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        # Collect data
        news_data = await news_collector.collect_data(symbols)
        social_data = await social_collector.collect_data(symbols)
        
        # Validate data
        news_valid = await news_collector.validate_data(news_data)
        social_valid = await social_collector.validate_data(social_data)
        
        assert news_valid is True
        assert social_valid is True

    @pytest.mark.asyncio
    async def test_cache_behavior_consistency(self, mock_config):
        """Test that both collectors handle caching consistently"""
        symbols = ["EUR/USD"]
        timeframe = "1d"  # Use longer timeframe to include mock data
        
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        # First collection should populate cache
        news_data1 = await news_collector.collect_data(symbols, timeframe)
        social_data1 = await social_collector.collect_data(symbols, timeframe)
        
        # Second collection should use cache
        news_data2 = await news_collector.collect_data(symbols, timeframe)
        social_data2 = await social_collector.collect_data(symbols, timeframe)
        
        # Data should be identical (from cache)
        assert len(news_data1["EUR/USD"]) == len(news_data2["EUR/USD"])
        assert len(social_data1["EUR/USD"]) == len(social_data2["EUR/USD"])
        
        # Verify cache stats
        news_stats = news_collector.get_cache_stats()
        social_stats = social_collector.get_cache_stats()
        
        assert news_stats["cache_size"] > 0
        assert social_stats["cache_size"] > 0
        assert "EUR/USD" in news_stats["cached_symbols"]
        assert "EUR/USD" in social_stats["cached_symbols"]

    @pytest.mark.asyncio
    async def test_error_handling_consistency(self, mock_config):
        """Test that both collectors handle errors consistently"""
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        # Test empty symbols list
        with pytest.raises(Exception):
            await news_collector.collect_data([])
        
        with pytest.raises(Exception):
            await social_collector.collect_data([])

    @pytest.mark.asyncio
    async def test_timeframe_handling_consistency(self, mock_config):
        """Test that both collectors handle different timeframes consistently"""
        symbols = ["EUR/USD"]
        timeframes = ["1h", "4h", "1d"]
        
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        for timeframe in timeframes:
            news_data = await news_collector.collect_data(symbols, timeframe)
            social_data = await social_collector.collect_data(symbols, timeframe)
            
            assert len(news_data) == 1
            assert len(social_data) == 1
            assert "EUR/USD" in news_data
            assert "EUR/USD" in social_data

    def test_text_processing_consistency(self, mock_config):
        """Test that both collectors process text consistently"""
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        test_text = "EUR/USD and GBP/USD are showing strength"
        
        # Both should extract the same currency pairs
        news_pairs = news_collector._extract_currency_pairs(test_text)
        social_pairs = social_collector._extract_currency_pairs(test_text)
        
        assert set(news_pairs) == set(social_pairs)
        assert "EUR/USD" in news_pairs
        assert "GBP/USD" in news_pairs

    def test_configuration_usage(self, mock_config):
        """Test that both collectors use configuration correctly"""
        news_collector = NewsDataCollector(mock_config)
        social_collector = SocialMediaCollector(mock_config)
        
        # Both should use the same timeout from config
        assert news_collector.config.api_timeout == mock_config.api_timeout
        assert social_collector.config.api_timeout == mock_config.api_timeout
        
        # Both should have similar cache TTL behavior
        assert news_collector.cache_ttl.total_seconds() > 0
        assert social_collector.cache_ttl.total_seconds() > 0


if __name__ == "__main__":
    pytest.main([__file__])
"""Unit tests for MarketDataCollector"""

import pytest
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, AsyncMock, patch
from src.data.market_data_collector import MarketDataCollector
from src.data.mock_broker import MockBrokerInterface
from src.models import MarketData
from src.config import ConfigManager
from src.exceptions import DataValidationError, APIError


@pytest.fixture
def config():
    """Create test configuration"""
    config_manager = ConfigManager()
    return config_manager.get_config()


@pytest.fixture
def mock_broker():
    """Create mock broker interface"""
    return MockBrokerInterface()


@pytest.fixture
def market_data_collector(config, mock_broker):
    """Create MarketDataCollector instance"""
    return MarketDataCollector(mock_broker, config)


@pytest.mark.asyncio
async def test_collect_data_success(market_data_collector, mock_broker):
    """Test successful data collection"""
    # Connect mock broker
    await mock_broker.connect()
    
    async with market_data_collector:
        symbols = ['EUR/USD', 'GBP/USD']
        result = await market_data_collector.collect_data(symbols)
        
        assert len(result) == 2
        assert 'EUR/USD' in result
        assert 'GBP/USD' in result
        
        for symbol, data in result.items():
            assert isinstance(data, MarketData)
            assert data.symbol == symbol
            assert data.open > 0
            assert data.high > 0
            assert data.low > 0
            assert data.close > 0
            assert data.bid > 0
            assert data.ask > 0
            assert data.ask > data.bid


@pytest.mark.asyncio
async def test_collect_data_empty_symbols(market_data_collector):
    """Test collection with empty symbols list"""
    async with market_data_collector:
        with pytest.raises(DataValidationError) as exc_info:
            await market_data_collector.collect_data([])
        
        assert exc_info.value.error_code == "EMPTY_SYMBOLS"


@pytest.mark.asyncio
async def test_collect_data_with_cache(market_data_collector, mock_broker):
    """Test data collection with caching"""
    await mock_broker.connect()
    
    async with market_data_collector:
        symbols = ['EUR/USD']
        
        # First call - should fetch fresh data
        result1 = await market_data_collector.collect_data(symbols)
        
        # Second call - should use cached data
        result2 = await market_data_collector.collect_data(symbols)
        
        assert result1['EUR/USD'].timestamp == result2['EUR/USD'].timestamp


@pytest.mark.asyncio
async def test_collect_data_cache_expiry(market_data_collector, mock_broker):
    """Test cache expiry functionality"""
    await mock_broker.connect()
    
    async with market_data_collector:
        # Set very short cache TTL for testing
        market_data_collector.cache_ttl = timedelta(milliseconds=10)
        
        symbols = ['EUR/USD']
        
        # First call
        result1 = await market_data_collector.collect_data(symbols)
        
        # Wait for cache to expire
        await asyncio.sleep(0.02)
        
        # Second call - should fetch fresh data
        result2 = await market_data_collector.collect_data(symbols)
        
        assert result1['EUR/USD'].timestamp != result2['EUR/USD'].timestamp


@pytest.mark.asyncio
async def test_collect_data_broker_error_with_fallback(market_data_collector, mock_broker):
    """Test fallback to cached data when broker fails"""
    await mock_broker.connect()
    
    async with market_data_collector:
        symbols = ['EUR/USD']
        
        # First call - populate cache
        await market_data_collector.collect_data(symbols)
        
        # Disconnect broker to simulate error
        await mock_broker.disconnect()
        
        # Second call - should use cached data as fallback
        result = await market_data_collector.collect_data(symbols)
        
        assert 'EUR/USD' in result
        assert isinstance(result['EUR/USD'], MarketData)


@pytest.mark.asyncio
async def test_collect_data_broker_error_no_fallback(market_data_collector, mock_broker):
    """Test error when broker fails and no cached data available"""
    # Don't connect broker to simulate error
    async with market_data_collector:
        symbols = ['EUR/USD']
        
        with pytest.raises(APIError) as exc_info:
            await market_data_collector.collect_data(symbols)
        
        assert exc_info.value.error_code == "DATA_COLLECTION_FAILED"


@pytest.mark.asyncio
async def test_validate_data_success(market_data_collector):
    """Test successful data validation"""
    async with market_data_collector:
        data = {
            'EUR/USD': MarketData(
                symbol='EUR/USD',
                timestamp=datetime.now(timezone.utc),
                open=1.0850,
                high=1.0860,
                low=1.0840,
                close=1.0855,
                volume=1000,
                bid=1.0854,
                ask=1.0856,
                spread=0.0002
            )
        }
        
        result = await market_data_collector.validate_data(data)
        assert result is True


@pytest.mark.asyncio
async def test_validate_data_empty(market_data_collector):
    """Test validation with empty data"""
    async with market_data_collector:
        result = await market_data_collector.validate_data({})
        assert result is False


@pytest.mark.asyncio
async def test_validate_data_invalid_type(market_data_collector):
    """Test validation with invalid data type"""
    async with market_data_collector:
        data = {
            'EUR/USD': "invalid_data"
        }
        
        result = await market_data_collector.validate_data(data)
        assert result is False


@pytest.mark.asyncio
async def test_validate_data_stale_data(market_data_collector):
    """Test validation with stale data"""
    async with market_data_collector:
        # Create data that's too old
        old_timestamp = datetime.now(timezone.utc) - timedelta(seconds=400)
        
        data = {
            'EUR/USD': MarketData(
                symbol='EUR/USD',
                timestamp=old_timestamp,
                open=1.0850,
                high=1.0860,
                low=1.0840,
                close=1.0855,
                volume=1000,
                bid=1.0854,
                ask=1.0856,
                spread=0.0002
            )
        }
        
        result = await market_data_collector.validate_data(data)
        assert result is False


@pytest.mark.asyncio
async def test_validate_data_wide_spread(market_data_collector):
    """Test validation with wide spread"""
    async with market_data_collector:
        data = {
            'EUR/USD': MarketData(
                symbol='EUR/USD',
                timestamp=datetime.now(timezone.utc),
                open=1.0850,
                high=1.0860,
                low=1.0840,
                close=1.0855,
                volume=1000,
                                    bid=1.0800,  # Very wide spread
                    ask=1.0901,  # Slightly larger ask
                    spread=0.0101  # Above threshold
            )
        }
        
        result = await market_data_collector.validate_data(data)
        assert result is False


def test_normalize_market_data_dict(market_data_collector):
    """Test normalization from dictionary format"""
    raw_data = {
        'open': 1.0850,
        'high': 1.0860,
        'low': 1.0840,
        'close': 1.0855,
        'volume': 1000,
        'bid': 1.0854,
        'ask': 1.0856
    }
    
    result = market_data_collector._normalize_market_data(raw_data, 'EUR/USD')
    
    assert isinstance(result, MarketData)
    assert result.symbol == 'EUR/USD'
    assert result.open == 1.0850
    assert abs(result.spread - 0.0002) < 0.000001  # Allow for floating point precision


def test_normalize_market_data_already_normalized(market_data_collector):
    """Test normalization with already normalized data"""
    market_data = MarketData(
        symbol='EUR/USD',
        timestamp=datetime.now(timezone.utc),
        open=1.0850,
        high=1.0860,
        low=1.0840,
        close=1.0855,
        volume=1000,
        bid=1.0854,
        ask=1.0856,
        spread=0.0002
    )
    
    result = market_data_collector._normalize_market_data(market_data, 'EUR/USD')
    
    assert result is market_data


def test_normalize_market_data_invalid_format(market_data_collector):
    """Test normalization with invalid data format"""
    with pytest.raises(DataValidationError) as exc_info:
        market_data_collector._normalize_market_data("invalid", 'EUR/USD')
    
    assert exc_info.value.error_code == "UNSUPPORTED_DATA_FORMAT"


def test_normalize_market_data_missing_fields(market_data_collector):
    """Test normalization with missing required fields"""
    raw_data = {
        'open': 1.0850,
        # Missing other required fields
    }
    
    with pytest.raises(DataValidationError) as exc_info:
        market_data_collector._normalize_market_data(raw_data, 'EUR/USD')
    
    assert exc_info.value.error_code == "INVALID_OHLC"


def test_get_cached_data_exists(market_data_collector):
    """Test getting existing cached data"""
    market_data = MarketData(
        symbol='EUR/USD',
        timestamp=datetime.now(timezone.utc),
        open=1.0850,
        high=1.0860,
        low=1.0840,
        close=1.0855,
        volume=1000,
        bid=1.0854,
        ask=1.0856,
        spread=0.0002
    )
    
    market_data_collector.cache['EUR/USD'] = market_data
    
    result = market_data_collector._get_cached_data('EUR/USD')
    assert result is market_data


def test_get_cached_data_not_exists(market_data_collector):
    """Test getting non-existent cached data"""
    result = market_data_collector._get_cached_data('EUR/USD')
    assert result is None


def test_get_cached_data_expired(market_data_collector):
    """Test getting expired cached data"""
    # Create old data
    old_timestamp = datetime.now(timezone.utc) - timedelta(seconds=120)
    market_data = MarketData(
        symbol='EUR/USD',
        timestamp=old_timestamp,
        open=1.0850,
        high=1.0860,
        low=1.0840,
        close=1.0855,
        volume=1000,
        bid=1.0854,
        ask=1.0856,
        spread=0.0002
    )
    
    market_data_collector.cache['EUR/USD'] = market_data
    
    result = market_data_collector._get_cached_data('EUR/USD')
    assert result is None
    assert 'EUR/USD' not in market_data_collector.cache


def test_clear_cache(market_data_collector):
    """Test cache clearing"""
    market_data = MarketData(
        symbol='EUR/USD',
        timestamp=datetime.now(timezone.utc),
        open=1.0850,
        high=1.0860,
        low=1.0840,
        close=1.0855,
        volume=1000,
        bid=1.0854,
        ask=1.0856,
        spread=0.0002
    )
    
    market_data_collector.cache['EUR/USD'] = market_data
    assert len(market_data_collector.cache) == 1
    
    market_data_collector.clear_cache()
    assert len(market_data_collector.cache) == 0


def test_get_cache_stats(market_data_collector):
    """Test cache statistics"""
    market_data = MarketData(
        symbol='EUR/USD',
        timestamp=datetime.now(timezone.utc),
        open=1.0850,
        high=1.0860,
        low=1.0840,
        close=1.0855,
        volume=1000,
        bid=1.0854,
        ask=1.0856,
        spread=0.0002
    )
    
    market_data_collector.cache['EUR/USD'] = market_data
    
    stats = market_data_collector.get_cache_stats()
    
    assert stats['cached_symbols'] == ['EUR/USD']
    assert stats['cache_size'] == 1
    assert stats['cache_ttl_seconds'] == 60.0


if __name__ == "__main__":
    pytest.main([__file__])
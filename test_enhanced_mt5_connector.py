"""
Unit tests for Enhanced MT5 Connector for RL System
"""

import pytest
import asyncio
import numpy as np
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any, List

from src.rl.integration.mt5_connector import EnhancedMT5Connector, create_enhanced_mt5_connector
from src.rl.environments.state_processor import StateProcessor
from src.models import MarketData, Portfolio, Position, Direction
from src.exceptions import BrokerAPIError


class TestEnhancedMT5Connector:
    """Test cases for EnhancedMT5Connector"""
    
    @pytest.fixture
    def mock_state_processor(self):
        """Mock state processor for testing"""
        processor = Mock(spec=StateProcessor)
        processor.get_state_dimension.return_value = 50
        processor.process_market_data.return_value = np.random.random(50)
        return processor
    
    @pytest.fixture
    def connector(self, mock_state_processor):
        """Create connector instance for testing"""
        return EnhancedMT5Connector(
            login=12345,
            password="test_password",
            server="test_server",
            state_processor=mock_state_processor,
            lookback_window=100
        )
    
    @pytest.fixture
    def sample_market_data(self):
        """Sample market data for testing"""
        return MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000,
            high=1.1010,
            low=1.0990,
            close=1.1005,
            volume=1000,
            bid=1.1003,
            ask=1.1007,
            spread=0.0004
        )
    
    @pytest.fixture
    def sample_portfolio(self):
        """Sample portfolio for testing"""
        return Portfolio(
            account_id="12345",
            balance=10000.0,
            equity=10000.0,
            margin_used=1000.0,
            margin_available=9000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
    
    def test_initialization(self, mock_state_processor):
        """Test connector initialization"""
        connector = EnhancedMT5Connector(
            login=12345,
            password="test_password",
            server="test_server",
            state_processor=mock_state_processor,
            lookback_window=50
        )
        
        assert connector.login == 12345
        assert connector.password == "test_password"
        assert connector.server == "test_server"
        assert connector.state_processor == mock_state_processor
        assert connector.lookback_window == 50
        assert connector.rl_symbols == ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF']
        assert len(connector._price_history) == 0
        assert len(connector._last_update) == 0
    
    @patch('src.rl.integration.mt5_connector.mt5')
    @pytest.mark.asyncio
    async def test_initialize_rl_data_feeds_success(self, mock_mt5, connector):
        """Test successful initialization of RL data feeds"""
        # Mock MT5 connection
        connector.connected = True
        
        # Mock historical data
        mock_rates = [
            {'time': 1640995200, 'open': 1.1000, 'high': 1.1010, 'low': 1.0990, 'close': 1.1005, 'tick_volume': 100},
            {'time': 1640995260, 'open': 1.1005, 'high': 1.1015, 'low': 1.0995, 'close': 1.1010, 'tick_volume': 150}
        ]
        mock_mt5.copy_rates_from_pos.return_value = mock_rates
        
        # Test initialization
        symbols = ['EUR/USD', 'GBP/USD']
        result = await connector.initialize_rl_data_feeds(symbols)
        
        assert result is True
        assert 'EUR/USD' in connector._price_history
        assert 'GBP/USD' in connector._price_history
        assert len(connector._price_history['EUR/USD']) == 2
        assert len(connector._price_history['GBP/USD']) == 2
        
        # Verify data structure
        first_data = connector._price_history['EUR/USD'][0]
        assert first_data.symbol == 'EUR/USD'
        assert first_data.open == 1.1000
        assert first_data.close == 1.1005
    
    @patch('src.rl.integration.mt5_connector.mt5')
    @pytest.mark.asyncio
    async def test_initialize_rl_data_feeds_failure(self, mock_mt5, connector):
        """Test failure in initializing RL data feeds"""
        connector.connected = True
        mock_mt5.copy_rates_from_pos.return_value = None
        
        result = await connector.initialize_rl_data_feeds(['EUR/USD'])
        
        assert result is True  # Should continue even if some symbols fail
        assert len(connector._price_history) == 0
    
    @pytest.mark.asyncio
    async def test_get_rl_state_vector_success(self, connector, sample_market_data, mock_state_processor):
        """Test successful state vector construction"""
        # Setup mock data
        connector._price_history['EUR/USD'] = [sample_market_data] * 50
        
        with patch.object(connector, '_update_price_history') as mock_update, \
             patch.object(connector, 'get_market_data', return_value=sample_market_data) as mock_market, \
             patch.object(connector, 'get_account_info') as mock_account:
            
            mock_account.return_value = Portfolio(
                account_id="12345",
                balance=10000.0,
                equity=10000.0,
                margin_used=1000.0,
                margin_available=9000.0,
                positions=[],
                updated_at=datetime.now(timezone.utc)
            )
            
            # Mock technical indicators
            mock_indicators = {
                'rsi': 50.0,
                'macd_line': 0.001,
                'macd_signal': 0.0005,
                'bb_upper': 1.1020,
                'bb_lower': 1.0980,
                'sma_20': 1.1000,
                'ema_12': 1.1002,
                'stoch_k': 80.0,
                'stoch_d': 75.0,
                'volume_sma': 1000.0
            }
            
            with patch.object(connector.technical_indicators, 'calculate_all_indicators', return_value=mock_indicators):
                
                state_vector = await connector.get_rl_state_vector('EUR/USD')
                
                assert isinstance(state_vector, np.ndarray)
                assert len(state_vector) == 50
                mock_update.assert_called_once_with('EUR/USD')
                mock_market.assert_called_once_with('EUR/USD')
                mock_state_processor.process_market_data.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_get_rl_state_vector_insufficient_data(self, connector):
        """Test state vector construction with insufficient data"""
        connector._price_history['EUR/USD'] = []  # Empty history
        
        with patch.object(connector, '_update_price_history'), \
             patch.object(connector, 'get_market_data'):
            
            with pytest.raises(BrokerAPIError, match="Insufficient historical data"):
                await connector.get_rl_state_vector('EUR/USD')
    
    @pytest.mark.asyncio
    async def test_execute_rl_action_hold(self, connector):
        """Test RL action execution - HOLD"""
        action_config = {'action_space': 'discrete'}
        
        result = await connector.execute_rl_action('EUR/USD', 0, action_config)
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_execute_rl_action_buy(self, connector):
        """Test RL action execution - BUY"""
        action_config = {
            'action_space': 'discrete',
            'max_position_size': 0.1,
            'risk_per_trade': 0.02,
            'account_balance': 10000
        }
        
        with patch.object(connector, 'place_order', return_value="12345") as mock_place:
            result = await connector.execute_rl_action('EUR/USD', 1, action_config)
            
            assert result == "12345"
            mock_place.assert_called_once()
            args, kwargs = mock_place.call_args
            assert kwargs['symbol'] == 'EUR/USD'
            assert kwargs['direction'] == Direction.LONG
            assert kwargs['size'] > 0
    
    @pytest.mark.asyncio
    async def test_execute_rl_action_close_position(self, connector):
        """Test RL action execution - CLOSE_POSITION"""
        action_config = {'action_space': 'discrete'}
        
        # Mock existing position
        mock_position = Mock()
        mock_position.symbol = 'EUR/USD'
        mock_position.order_id = '54321'
        
        with patch.object(connector, 'get_positions', return_value=[mock_position]) as mock_positions, \
             patch.object(connector, 'close_position', return_value=True) as mock_close:
            
            result = await connector.execute_rl_action('EUR/USD', 7, action_config)
            
            assert result == '54321'
            mock_positions.assert_called_once()
            mock_close.assert_called_once_with('54321')
    
    @patch('src.rl.integration.mt5_connector.mt5')
    @pytest.mark.asyncio
    async def test_get_real_time_features_success(self, mock_mt5, connector):
        """Test getting real-time market features"""
        # Mock tick data
        mock_tick = Mock()
        mock_tick.bid = 1.1000
        mock_tick.ask = 1.1004
        mock_tick.last = 1.1002
        mock_tick.volume = 100
        mock_tick.time = 1640995200
        
        mock_mt5.symbol_info_tick.return_value = mock_tick
        mock_mt5.market_book_get.return_value = None
        
        features = await connector.get_real_time_features('EUR/USD')
        
        assert 'bid_ask_spread' in features
        assert 'mid_price' in features
        assert 'tick_volume' in features
        assert abs(features['bid_ask_spread'] - 0.0004) < 0.0001
        assert features['mid_price'] == 1.1002
        assert features['tick_volume'] == 100.0
    
    @patch('src.rl.integration.mt5_connector.mt5')
    @pytest.mark.asyncio
    async def test_get_real_time_features_with_order_book(self, mock_mt5, connector):
        """Test getting real-time features with order book data"""
        # Mock tick data
        mock_tick = Mock()
        mock_tick.bid = 1.1000
        mock_tick.ask = 1.1004
        mock_tick.last = 1.1002
        mock_tick.volume = 100
        mock_tick.time = 1640995200
        
        # Mock order book
        mock_bid_item = Mock()
        mock_bid_item.type = 1
        mock_bid_item.volume = 50
        
        mock_ask_item = Mock()
        mock_ask_item.type = 2
        mock_ask_item.volume = 30
        
        mock_mt5.symbol_info_tick.return_value = mock_tick
        mock_mt5.market_book_get.return_value = [mock_bid_item, mock_ask_item]
        
        features = await connector.get_real_time_features('EUR/USD')
        
        assert 'order_book_imbalance' in features
        assert 'bid_depth' in features
        assert 'ask_depth' in features
        assert features['bid_depth'] == 50
        assert features['ask_depth'] == 30
    
    @patch('src.rl.integration.mt5_connector.mt5')
    @pytest.mark.asyncio
    async def test_update_price_history(self, mock_mt5, connector):
        """Test updating price history with new data"""
        # Mock new rate data
        mock_rates = [{
            'time': 1640995200,
            'open': 1.1000,
            'high': 1.1010,
            'low': 1.0990,
            'close': 1.1005,
            'tick_volume': 100
        }]
        mock_mt5.copy_rates_from_pos.return_value = mock_rates
        
        # Initialize with some existing data
        connector._price_history['EUR/USD'] = []
        
        await connector._update_price_history('EUR/USD')
        
        assert len(connector._price_history['EUR/USD']) == 1
        assert connector._price_history['EUR/USD'][0].close == 1.1005
        assert 'EUR/USD' in connector._last_update
    
    def test_decode_rl_action_discrete(self, connector):
        """Test decoding discrete RL actions"""
        config = {'action_space': 'discrete'}
        
        # Test HOLD action
        action = connector._decode_rl_action(0, config)
        assert action['type'] == 'HOLD'
        
        # Test BUY action
        action = connector._decode_rl_action(1, config)
        assert action['type'] == 'BUY'
        assert action['direction'] == 'BUY'
        assert action['size'] == 0.01
        
        # Test SELL action
        action = connector._decode_rl_action(4, config)
        assert action['type'] == 'SELL'
        assert action['direction'] == 'SELL'
        assert action['size'] == 0.01
        
        # Test CLOSE_POSITION action
        action = connector._decode_rl_action(7, config)
        assert action['type'] == 'CLOSE_POSITION'
        
        # Test invalid action (should default to HOLD)
        action = connector._decode_rl_action(99, config)
        assert action['type'] == 'HOLD'
    
    def test_apply_risk_management(self, connector):
        """Test risk management application"""
        config = {
            'max_position_size': 0.1,
            'risk_per_trade': 0.02,
            'account_balance': 10000
        }
        
        # Test normal size
        size = connector._apply_risk_management(0.05, 'EURUSD', config)
        assert size == 0.05
        
        # Test size exceeding maximum
        size = connector._apply_risk_management(0.2, 'EURUSD', config)
        assert size == 0.1  # Should be capped at max_position_size
        
        # Test minimum size enforcement
        size = connector._apply_risk_management(0.005, 'EURUSD', config)
        assert size == 0.01  # Should be minimum 0.01
    
    def test_get_current_position_size(self, connector):
        """Test getting current position size"""
        # Mock positions
        long_position = Mock()
        long_position.symbol = 'EUR/USD'
        long_position.direction = Direction.LONG
        long_position.quantity = 0.1
        
        short_position = Mock()
        short_position.symbol = 'GBP/USD'
        short_position.direction = Direction.SHORT
        short_position.quantity = 0.05
        
        positions = [long_position, short_position]
        
        # Test existing long position
        size = connector._get_current_position_size('EUR/USD', positions)
        assert size == 0.1
        
        # Test existing short position
        size = connector._get_current_position_size('GBP/USD', positions)
        assert size == -0.05
        
        # Test no position
        size = connector._get_current_position_size('USD/JPY', positions)
        assert size == 0.0
    
    def test_calculate_order_book_imbalance(self, connector):
        """Test order book imbalance calculation"""
        # Mock order book items
        bid_item1 = Mock()
        bid_item1.type = 1
        bid_item1.volume = 100
        
        bid_item2 = Mock()
        bid_item2.type = 1
        bid_item2.volume = 50
        
        ask_item1 = Mock()
        ask_item1.type = 2
        ask_item1.volume = 75
        
        depth = [bid_item1, bid_item2, ask_item1]
        
        imbalance = connector._calculate_order_book_imbalance(depth)
        
        # Total bid: 150, Total ask: 75, Total: 225
        # Imbalance: (150 - 75) / 225 = 75/225 = 1/3
        expected_imbalance = (150 - 75) / 225
        assert abs(imbalance - expected_imbalance) < 0.001
        
        # Test empty depth
        imbalance = connector._calculate_order_book_imbalance([])
        assert imbalance == 0.0
    
    @pytest.mark.asyncio
    async def test_get_multiple_symbols_state(self, connector, mock_state_processor):
        """Test getting state vectors for multiple symbols"""
        symbols = ['EUR/USD', 'GBP/USD']
        
        # Mock portfolio
        mock_portfolio = Portfolio(
            account_id="12345",
            balance=10000.0,
            equity=10000.0,
            margin_used=1000.0,
            margin_available=9000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        with patch.object(connector, 'get_account_info', return_value=mock_portfolio), \
             patch.object(connector, 'get_rl_state_vector') as mock_get_state:
            
            mock_get_state.return_value = np.random.random(50)
            
            states = await connector.get_multiple_symbols_state(symbols)
            
            assert len(states) == 2
            assert 'EUR/USD' in states
            assert 'GBP/USD' in states
            assert isinstance(states['EUR/USD'], np.ndarray)
            assert isinstance(states['GBP/USD'], np.ndarray)
            assert mock_get_state.call_count == 2
    
    @pytest.mark.asyncio
    async def test_get_multiple_symbols_state_with_error(self, connector, mock_state_processor):
        """Test getting multiple symbol states with error handling"""
        symbols = ['EUR/USD', 'INVALID_SYMBOL']
        
        mock_portfolio = Portfolio(
            account_id="12345",
            balance=10000.0,
            equity=10000.0,
            margin_used=1000.0,
            margin_available=9000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        def mock_get_state_side_effect(symbol, portfolio_state):
            if symbol == 'EUR/USD':
                return np.random.random(50)
            else:
                raise BrokerAPIError("Invalid symbol")
        
        with patch.object(connector, 'get_account_info', return_value=mock_portfolio), \
             patch.object(connector, 'get_rl_state_vector', side_effect=mock_get_state_side_effect):
            
            states = await connector.get_multiple_symbols_state(symbols)
            
            assert len(states) == 2
            assert 'EUR/USD' in states
            assert 'INVALID_SYMBOL' in states
            assert isinstance(states['EUR/USD'], np.ndarray)
            # Invalid symbol should have zero state
            assert np.allclose(states['INVALID_SYMBOL'], np.zeros(50))


class TestFactoryFunction:
    """Test cases for factory function"""
    
    def test_create_enhanced_mt5_connector_default(self):
        """Test factory function with default parameters"""
        connector = create_enhanced_mt5_connector()
        
        assert isinstance(connector, EnhancedMT5Connector)
        assert connector.login == 95185205
        assert connector.password == "QxE@7tYo"
        assert connector.server == "MetaQuotes-Demo"
        assert connector.state_processor is not None
    
    def test_create_enhanced_mt5_connector_custom(self):
        """Test factory function with custom parameters"""
        mock_processor = Mock(spec=StateProcessor)
        
        connector = create_enhanced_mt5_connector(
            login=12345,
            password="custom_password",
            server="custom_server",
            state_processor=mock_processor
        )
        
        assert connector.login == 12345
        assert connector.password == "custom_password"
        assert connector.server == "custom_server"
        assert connector.state_processor == mock_processor


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
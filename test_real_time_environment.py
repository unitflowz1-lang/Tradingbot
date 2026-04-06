"""
Unit tests for Real-Time Trading Environment
"""

import pytest
import asyncio
import numpy as np
from datetime import datetime, timezone
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, Any, List

from src.rl.integration.real_time_environment import (
    RealTimeEnvironment, TradingMode, create_real_time_environment
)
from src.rl.integration.mt5_connector import EnhancedMT5Connector
from src.rl.environments.base import EnvironmentConfig, PortfolioState
from src.models import MarketData, Portfolio, Position, Direction
from src.exceptions import BrokerAPIError, TradeExecutionError


class TestRealTimeEnvironment:
    """Test cases for RealTimeEnvironment"""
    
    @pytest.fixture
    def env_config(self):
        """Environment configuration for testing"""
        return EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='profit_based',
            lookback_window=100,
            normalization_method='robust',
            transaction_cost=0.0001,
            max_position_size=0.1,
            initial_balance=10000.0,
            max_episode_steps=1000
        )
    
    @pytest.fixture
    def mock_mt5_connector(self):
        """Mock MT5 connector for testing"""
        connector = Mock(spec=EnhancedMT5Connector)
        connector.connected = True
        connector.connect = AsyncMock(return_value=True)
        connector.disconnect = AsyncMock(return_value=True)
        connector.initialize_rl_data_feeds = AsyncMock(return_value=True)
        connector.get_market_data = AsyncMock()
        connector.get_rl_state_vector = AsyncMock(return_value=np.random.random(50))
        connector.execute_rl_action = AsyncMock(return_value="12345")
        connector.get_account_info = AsyncMock()
        
        # Mock state processor
        mock_processor = Mock()
        mock_processor.get_state_dimension.return_value = 50
        connector.state_processor = mock_processor
        
        return connector
    
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
    
    @pytest.fixture
    def real_time_env(self, env_config, mock_mt5_connector):
        """Real-time environment instance for testing"""
        return RealTimeEnvironment(
            config=env_config,
            mt5_connector=mock_mt5_connector,
            trading_mode=TradingMode.PAPER,
            symbols=['EUR/USD', 'GBP/USD']
        )
    
    def test_initialization(self, env_config, mock_mt5_connector):
        """Test environment initialization"""
        env = RealTimeEnvironment(
            config=env_config,
            mt5_connector=mock_mt5_connector,
            trading_mode=TradingMode.PAPER,
            symbols=['EUR/USD', 'GBP/USD', 'USD/JPY']
        )
        
        assert env.config == env_config
        assert env.mt5_connector == mock_mt5_connector
        assert env.trading_mode == TradingMode.PAPER
        assert env.symbols == ['EUR/USD', 'GBP/USD', 'USD/JPY']
        assert env.current_symbol == 'EUR/USD'
        assert not env.is_running
        assert env.paper_portfolio.balance == 10000.0
        assert env.paper_portfolio.current_position == 0.0
    
    @pytest.mark.asyncio
    async def test_initialize_success(self, real_time_env):
        """Test successful environment initialization"""
        # Set connector as not connected to test connection logic
        real_time_env.mt5_connector.connected = False
        
        with patch.object(real_time_env, '_start_real_time_monitoring') as mock_monitoring:
            result = await real_time_env.initialize()
            
            assert result is True
            real_time_env.mt5_connector.connect.assert_called_once()
            real_time_env.mt5_connector.initialize_rl_data_feeds.assert_called_once_with(['EUR/USD', 'GBP/USD'])
            mock_monitoring.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_initialize_connection_failure(self, real_time_env):
        """Test initialization with connection failure"""
        real_time_env.mt5_connector.connected = False
        real_time_env.mt5_connector.connect.return_value = False
        
        result = await real_time_env.initialize()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_reset_paper_mode(self, real_time_env):
        """Test environment reset in paper trading mode"""
        # Set some initial state
        real_time_env.paper_portfolio.realized_pnl = 100.0
        real_time_env.current_step = 50
        real_time_env.done = True
        
        with patch.object(real_time_env, '_get_current_state_async', return_value=np.random.random(50)):
            state = await real_time_env.reset()
            
            assert isinstance(state, np.ndarray)
            assert len(state) == 50
            assert real_time_env.paper_portfolio.balance == 10000.0
            assert real_time_env.paper_portfolio.realized_pnl == 0.0
            assert real_time_env.current_step == 0
            assert not real_time_env.done
            assert len(real_time_env.trade_history) == 0
    
    @pytest.mark.asyncio
    async def test_reset_live_mode(self, real_time_env, sample_portfolio):
        """Test environment reset in live trading mode"""
        real_time_env.trading_mode = TradingMode.LIVE
        real_time_env.mt5_connector.get_account_info.return_value = sample_portfolio
        
        with patch.object(real_time_env, '_get_current_state_async', return_value=np.random.random(50)):
            state = await real_time_env.reset()
            
            assert isinstance(state, np.ndarray)
            real_time_env.mt5_connector.get_account_info.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_step_paper_mode_hold_action(self, real_time_env):
        """Test step with HOLD action in paper mode"""
        real_time_env.market_data_cache['EUR/USD'] = MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.1010, low=1.0990, close=1.1005,
            volume=1000, bid=1.1003, ask=1.1007, spread=0.0004
        )
        
        with patch.object(real_time_env, '_get_current_state_async', return_value=np.random.random(50)):
            state, reward, done, info = await real_time_env.step(0)  # HOLD action
            
            assert isinstance(state, np.ndarray)
            assert isinstance(reward, float)
            assert isinstance(done, bool)
            assert isinstance(info, dict)
            assert info['action_executed']['action'] == 'HOLD'
            assert real_time_env.current_step == 1
    
    @pytest.mark.asyncio
    async def test_step_paper_mode_buy_action(self, real_time_env):
        """Test step with BUY action in paper mode"""
        real_time_env.market_data_cache['EUR/USD'] = MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.1010, low=1.0990, close=1.1005,
            volume=1000, bid=1.1003, ask=1.1007, spread=0.0004
        )
        
        with patch.object(real_time_env, '_get_current_state_async', return_value=np.random.random(50)):
            state, reward, done, info = await real_time_env.step(1)  # BUY action
            
            assert real_time_env.paper_portfolio.current_position > 0
            assert real_time_env.paper_portfolio.total_trades == 1
            assert len(real_time_env.trade_history) == 1
            assert real_time_env.trade_history[0]['action'] == 'BUY'
    
    @pytest.mark.asyncio
    async def test_step_paper_mode_close_position(self, real_time_env):
        """Test step with CLOSE_POSITION action in paper mode"""
        # Set up existing position
        real_time_env.paper_portfolio.current_position = 0.01
        real_time_env.trade_history = [{
            'timestamp': datetime.now(timezone.utc),
            'action': 'BUY',
            'symbol': 'EUR/USD',
            'price': 1.1000,
            'position_size': 0.01,
            'pnl': 0.0
        }]
        
        real_time_env.market_data_cache['EUR/USD'] = MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.1010, low=1.0990, close=1.1005,
            volume=1000, bid=1.1003, ask=1.1007, spread=0.0004
        )
        
        with patch.object(real_time_env, '_get_current_state_async', return_value=np.random.random(50)):
            state, reward, done, info = await real_time_env.step(7)  # CLOSE_POSITION action
            
            assert real_time_env.paper_portfolio.current_position == 0.0
            assert real_time_env.paper_portfolio.realized_pnl != 0.0  # Should have some P&L
            assert len(real_time_env.trade_history) == 2
            assert real_time_env.trade_history[1]['action'] == 'CLOSE'
    
    @pytest.mark.asyncio
    async def test_step_live_mode(self, real_time_env, sample_portfolio):
        """Test step in live trading mode"""
        real_time_env.trading_mode = TradingMode.LIVE
        real_time_env.mt5_connector.get_account_info.return_value = sample_portfolio
        
        with patch.object(real_time_env, '_get_current_state_async', return_value=np.random.random(50)):
            state, reward, done, info = await real_time_env.step(1)  # BUY action
            
            real_time_env.mt5_connector.execute_rl_action.assert_called_once()
            assert info['trading_mode'] == 'live'
    
    @pytest.mark.asyncio
    async def test_execute_paper_action_hold(self, real_time_env):
        """Test executing HOLD action in paper mode"""
        config = {'action_space': 'discrete'}
        
        result = await real_time_env._execute_paper_action(0, config)
        
        assert result['success'] is True
        assert result['action'] == 'HOLD'
        assert result['order_id'] is None
    
    @pytest.mark.asyncio
    async def test_execute_paper_action_buy(self, real_time_env, sample_market_data):
        """Test executing BUY action in paper mode"""
        real_time_env.market_data_cache['EUR/USD'] = sample_market_data
        config = {
            'action_space': 'discrete',
            'max_position_size': 0.1,
            'risk_per_trade': 0.02,
            'account_balance': 10000
        }
        
        result = await real_time_env._execute_paper_action(1, config)
        
        assert result['success'] is True
        assert result['action'] == 'BUY'
        assert 'size' in result
        assert 'price' in result
    
    @pytest.mark.asyncio
    async def test_execute_live_action(self, real_time_env):
        """Test executing action in live mode"""
        config = {'action_space': 'discrete'}
        real_time_env.mt5_connector.execute_rl_action.return_value = "12345"
        
        result = await real_time_env._execute_live_action(1, config)
        
        assert result['success'] is True
        assert result['order_id'] == "12345"
        real_time_env.mt5_connector.execute_rl_action.assert_called_once_with(
            'EUR/USD', 1, config
        )
    
    @pytest.mark.asyncio
    async def test_get_current_state(self, real_time_env):
        """Test getting current state"""
        expected_state = np.random.random(50)
        real_time_env.mt5_connector.get_rl_state_vector.return_value = expected_state
        
        state = await real_time_env._get_current_state_async()
        
        assert np.array_equal(state, expected_state)
        real_time_env.mt5_connector.get_rl_state_vector.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_portfolio_state_paper_mode(self, real_time_env, sample_market_data):
        """Test updating portfolio state in paper mode"""
        real_time_env.paper_portfolio.current_position = 0.01
        real_time_env.trade_history = [{
            'price': 1.1000,
            'timestamp': datetime.now(timezone.utc)
        }]
        real_time_env.market_data_cache['EUR/USD'] = sample_market_data
        
        await real_time_env._update_portfolio_state()
        
        assert real_time_env.paper_portfolio.unrealized_pnl != 0.0
        assert real_time_env.paper_portfolio.equity != real_time_env.paper_portfolio.balance
    
    @pytest.mark.asyncio
    async def test_update_portfolio_state_live_mode(self, real_time_env, sample_portfolio):
        """Test updating portfolio state in live mode"""
        real_time_env.trading_mode = TradingMode.LIVE
        real_time_env.mt5_connector.get_account_info.return_value = sample_portfolio
        
        await real_time_env._update_portfolio_state()
        
        real_time_env.mt5_connector.get_account_info.assert_called_once()
        assert real_time_env.portfolio.balance == 10000.0
    
    def test_decode_action(self, real_time_env):
        """Test action decoding"""
        # Test HOLD action
        action_info = real_time_env._decode_action(0)
        assert action_info['type'] == 'HOLD'
        
        # Test BUY action
        action_info = real_time_env._decode_action(1)
        assert action_info['type'] == 'BUY'
        assert action_info['direction'] == 'BUY'
        assert action_info['size'] == 0.01
        
        # Test SELL action
        action_info = real_time_env._decode_action(4)
        assert action_info['type'] == 'SELL'
        assert action_info['direction'] == 'SELL'
        assert action_info['size'] == 0.01
        
        # Test CLOSE_POSITION action
        action_info = real_time_env._decode_action(7)
        assert action_info['type'] == 'CLOSE_POSITION'
        
        # Test invalid action
        action_info = real_time_env._decode_action(99)
        assert action_info['type'] == 'HOLD'
    
    def test_apply_paper_risk_management(self, real_time_env):
        """Test paper trading risk management"""
        config = {
            'max_position_size': 0.1,
            'risk_per_trade': 0.02,
            'account_balance': 10000
        }
        
        # Test normal size
        size = real_time_env._apply_paper_risk_management(0.05, config)
        assert size == 0.05
        
        # Test size exceeding maximum
        size = real_time_env._apply_paper_risk_management(0.2, config)
        assert size == 0.1  # Should be capped
        
        # Test minimum size enforcement
        size = real_time_env._apply_paper_risk_management(0.005, config)
        assert size == 0.01  # Should be minimum
    
    def test_calculate_position_pnl(self, real_time_env):
        """Test position P&L calculation"""
        # Test no position
        pnl = real_time_env._calculate_position_pnl(1.1005)
        assert pnl == 0.0
        
        # Test long position with profit
        real_time_env.paper_portfolio.current_position = 0.01
        real_time_env.trade_history = [{
            'price': 1.1000,
            'timestamp': datetime.now(timezone.utc)
        }]
        
        pnl = real_time_env._calculate_position_pnl(1.1005)
        assert pnl > 0  # Should be profitable
        
        # Test short position with profit
        real_time_env.paper_portfolio.current_position = -0.01
        real_time_env.trade_history = [{
            'price': 1.1005,
            'timestamp': datetime.now(timezone.utc)
        }]
        
        pnl = real_time_env._calculate_position_pnl(1.1000)
        assert pnl > 0  # Should be profitable
    
    def test_calculate_reward(self, real_time_env):
        """Test reward calculation"""
        prev_portfolio = PortfolioState(
            balance=10000.0, equity=10000.0, current_position=0.0,
            unrealized_pnl=0.0, realized_pnl=0.0, total_trades=0,
            winning_trades=0, max_drawdown=0.0, current_drawdown=0.0
        )
        
        current_portfolio = PortfolioState(
            balance=10000.0, equity=10100.0, current_position=0.01,
            unrealized_pnl=100.0, realized_pnl=0.0, total_trades=1,
            winning_trades=1, max_drawdown=0.0, current_drawdown=0.0
        )
        
        reward = real_time_env._calculate_reward(prev_portfolio, current_portfolio, 1)
        
        assert isinstance(reward, float)
        assert -1.0 <= reward <= 1.0
        assert reward > 0  # Should be positive due to equity increase
    
    def test_check_episode_done(self, real_time_env):
        """Test episode termination conditions"""
        # Test normal conditions
        assert not real_time_env._check_episode_done()
        
        # Test maximum drawdown
        real_time_env.portfolio.current_drawdown = 0.25
        assert real_time_env._check_episode_done()
        
        # Reset and test maximum steps
        real_time_env.portfolio.current_drawdown = 0.0
        real_time_env.current_step = 1001
        assert real_time_env._check_episode_done()
        
        # Reset and test minimum equity
        real_time_env.current_step = 0
        real_time_env.portfolio.equity = 4000.0  # Below 50% of initial
        assert real_time_env._check_episode_done()
    
    def test_convert_to_portfolio_state(self, real_time_env, sample_portfolio):
        """Test converting Portfolio to PortfolioState"""
        # Add a position for the current symbol
        # Calculate correct P&L: (current_price - entry_price) * quantity
        # For EUR/USD: (1.1005 - 1.1000) * 0.01 = 0.00005
        position = Position(
            position_id="123",
            symbol="EUR/USD",
            direction=Direction.LONG,
            quantity=0.01,
            entry_price=1.1000,
            current_price=1.1005,
            unrealized_pnl=0.00005,  # (1.1005 - 1.1000) * 0.01
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        sample_portfolio.positions = [position]
        
        portfolio_state = real_time_env._convert_to_portfolio_state(sample_portfolio)
        
        assert portfolio_state.balance == 10000.0
        assert portfolio_state.equity == 10000.0
        assert portfolio_state.current_position == 0.01
        assert portfolio_state.unrealized_pnl == 0.00005
    
    def test_copy_portfolio_state(self, real_time_env):
        """Test copying portfolio state"""
        original = PortfolioState(
            balance=10000.0, equity=10100.0, current_position=0.01,
            unrealized_pnl=100.0, realized_pnl=50.0, total_trades=5,
            winning_trades=3, max_drawdown=0.05, current_drawdown=0.02
        )
        
        copy = real_time_env._copy_portfolio_state(original)
        
        assert copy.balance == original.balance
        assert copy.equity == original.equity
        assert copy.current_position == original.current_position
        assert copy is not original  # Should be different objects
    
    @pytest.mark.asyncio
    async def test_switch_trading_mode(self, real_time_env):
        """Test switching trading modes"""
        assert real_time_env.trading_mode == TradingMode.PAPER
        
        result = await real_time_env.switch_trading_mode(TradingMode.LIVE)
        
        assert result is True
        assert real_time_env.trading_mode == TradingMode.LIVE
    
    @pytest.mark.asyncio
    async def test_get_performance_summary(self, real_time_env):
        """Test getting performance summary"""
        real_time_env.paper_portfolio.equity = 10500.0
        real_time_env.paper_portfolio.realized_pnl = 300.0
        real_time_env.paper_portfolio.unrealized_pnl = 200.0
        real_time_env.paper_portfolio.total_trades = 10
        real_time_env.paper_portfolio.winning_trades = 6
        real_time_env.paper_portfolio.max_drawdown = 0.05
        real_time_env.paper_portfolio.current_position = 0.01
        
        # Set the main portfolio reference to paper portfolio
        real_time_env.portfolio = real_time_env.paper_portfolio
        
        summary = await real_time_env.get_performance_summary()
        
        assert summary['total_equity'] == 10500.0
        assert summary['total_return'] == 0.05  # 5% return
        assert summary['realized_pnl'] == 300.0
        assert summary['unrealized_pnl'] == 200.0
        assert summary['total_trades'] == 10
        assert summary['winning_trades'] == 6
        assert summary['win_rate'] == 0.6
        assert summary['max_drawdown'] == 0.05
        assert summary['current_position'] == 0.01
        assert summary['trading_mode'] == 'paper'
        assert summary['symbols'] == ['EUR/USD', 'GBP/USD']
    
    @pytest.mark.asyncio
    async def test_cleanup(self, real_time_env):
        """Test environment cleanup"""
        real_time_env.is_running = True
        real_time_env.data_thread = Mock()
        real_time_env.data_thread.is_alive.return_value = False
        
        await real_time_env.cleanup()
        
        assert not real_time_env.is_running
        real_time_env.mt5_connector.disconnect.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_start_real_time_monitoring(self, real_time_env):
        """Test starting real-time monitoring"""
        with patch('threading.Thread') as mock_thread:
            mock_thread_instance = Mock()
            mock_thread.return_value = mock_thread_instance
            
            await real_time_env._start_real_time_monitoring()
            
            assert real_time_env.is_running is True
            mock_thread.assert_called_once()
            mock_thread_instance.start.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_update_market_data(self, real_time_env, sample_market_data):
        """Test updating market data"""
        real_time_env.mt5_connector.get_market_data.return_value = sample_market_data
        
        await real_time_env._update_market_data()
        
        assert 'EUR/USD' in real_time_env.market_data_cache
        assert 'GBP/USD' in real_time_env.market_data_cache
        assert real_time_env.market_data_cache['EUR/USD'] == sample_market_data
        assert 'EUR/USD' in real_time_env.last_update_time
        assert 'GBP/USD' in real_time_env.last_update_time


class TestFactoryFunction:
    """Test cases for factory function"""
    
    def test_create_real_time_environment(self):
        """Test factory function"""
        config = EnvironmentConfig(
            state_features=['price'],
            action_space_type='discrete',
            reward_function='profit_based',
            lookback_window=100,
            normalization_method='robust',
            transaction_cost=0.0001,
            max_position_size=0.1,
            initial_balance=10000.0
        )
        
        mock_connector = Mock(spec=EnhancedMT5Connector)
        
        env = create_real_time_environment(
            config=config,
            mt5_connector=mock_connector,
            trading_mode=TradingMode.LIVE,
            symbols=['EUR/USD', 'GBP/USD']
        )
        
        assert isinstance(env, RealTimeEnvironment)
        assert env.config == config
        assert env.mt5_connector == mock_connector
        assert env.trading_mode == TradingMode.LIVE
        assert env.symbols == ['EUR/USD', 'GBP/USD']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
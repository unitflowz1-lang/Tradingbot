"""
Unit tests for RL Trading Environment

This module tests the core trading environment functionality including
state processing, action execution, and reward calculation.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pytest
from datetime import datetime, timedelta, timezone
from typing import List

from src.models import MarketData
from src.rl.environments import (
    ForexTradingEnvironment, 
    EnvironmentConfig, 
    ActionType,
    DefaultStateProcessor,
    DefaultRewardCalculator,
    RewardConfig
)


def create_sample_market_data(num_points: int = 100, 
                            start_price: float = 1.1000,
                            volatility: float = 0.001) -> List[MarketData]:
    """Create sample market data for testing."""
    data = []
    current_price = start_price
    base_time = datetime.now(timezone.utc)
    
    for i in range(num_points):
        # Simple random walk with some trend
        price_change = np.random.normal(0, volatility)
        current_price += price_change
        
        # Ensure positive prices
        current_price = max(current_price, 0.5)
        
        # Create OHLC data
        high = current_price + abs(np.random.normal(0, volatility/2))
        low = current_price - abs(np.random.normal(0, volatility/2))
        open_price = current_price + np.random.normal(0, volatility/4)
        
        # Ensure OHLC relationships
        high = max(high, current_price, open_price)
        low = min(low, current_price, open_price)
        
        # Create bid/ask
        spread = 0.0001  # 1 pip spread
        bid = current_price - spread/2
        ask = current_price + spread/2
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=base_time + timedelta(minutes=i),
            open=open_price,
            high=high,
            low=low,
            close=current_price,
            volume=1000 + int(np.random.normal(0, 100)),
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        data.append(market_data)
        
    return data


class TestEnvironmentConfig:
    """Test environment configuration."""
    
    def test_config_creation(self):
        """Test creating environment configuration."""
        config = EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=20,
            normalization_method='minmax',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        assert config.lookback_window == 20
        assert config.transaction_cost == 0.0001
        assert config.initial_balance == 10000.0


class TestDefaultStateProcessor:
    """Test default state processor."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=20,
            normalization_method='minmax',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        self.processor = DefaultStateProcessor(self.config)
        self.market_data = create_sample_market_data(50)
        
    def test_state_dimension(self):
        """Test state dimension calculation."""
        expected_dim = (
            4 * self.config.lookback_window +  # Price features
            8 +  # Technical features
            6 +  # Portfolio features
            4    # Temporal features
        )
        assert self.processor.get_state_dimension() == expected_dim
        
    def test_process_market_data(self):
        """Test processing market data into state vector."""
        from src.rl.environments.base import PortfolioState
        
        portfolio = PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Test with sufficient data
        state = self.processor.process_market_data(
            self.market_data[-20:], portfolio
        )
        
        assert isinstance(state, np.ndarray)
        assert state.shape == (self.processor.get_state_dimension(),)
        assert not np.any(np.isnan(state))
        assert not np.any(np.isinf(state))
        
    def test_process_insufficient_data(self):
        """Test processing with insufficient market data."""
        from src.rl.environments.base import PortfolioState
        
        portfolio = PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Test with insufficient data (should pad)
        short_data = self.market_data[:5]
        state = self.processor.process_market_data(short_data, portfolio)
        
        assert isinstance(state, np.ndarray)
        assert state.shape == (self.processor.get_state_dimension(),)
        
    def test_empty_data(self):
        """Test processing with empty market data."""
        from src.rl.environments.base import PortfolioState
        
        portfolio = PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        state = self.processor.process_market_data([], portfolio)
        
        assert isinstance(state, np.ndarray)
        assert state.shape == (self.processor.get_state_dimension(),)
        assert np.all(state == 0.0)


class TestDefaultRewardCalculator:
    """Test default reward calculator."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.env_config = EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=20,
            normalization_method='minmax',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        self.reward_config = RewardConfig()
        self.calculator = DefaultRewardCalculator(self.env_config, self.reward_config)
        self.market_data = create_sample_market_data(10)[0]
        
    def test_reward_calculation(self):
        """Test basic reward calculation."""
        from src.rl.environments.base import PortfolioState
        
        prev_state = PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        current_state = PortfolioState(
            balance=10000.0,
            equity=10100.0,  # $100 profit
            current_position=0.5,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=1,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        reward = self.calculator.calculate_reward(
            prev_state, current_state, ActionType.BUY_MEDIUM.value, self.market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        assert self.reward_config.min_reward <= reward <= self.reward_config.max_reward
        
    def test_reward_breakdown(self):
        """Test reward component breakdown."""
        from src.rl.environments.base import PortfolioState
        
        prev_state = PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        current_state = PortfolioState(
            balance=9950.0,  # Lost $50
            equity=9950.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=-50.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.005,
            current_drawdown=0.005
        )
        
        breakdown = self.calculator.get_reward_breakdown(
            prev_state, current_state, ActionType.SELL_MEDIUM.value, self.market_data
        )
        
        assert isinstance(breakdown, dict)
        assert 'pnl' in breakdown
        assert 'risk' in breakdown
        assert 'transaction' in breakdown
        assert 'drawdown' in breakdown
        assert 'consistency' in breakdown
        assert 'total' in breakdown
        
        # P&L component should be negative (lost money)
        assert breakdown['pnl'] < 0
        
        # Drawdown component should be negative (penalty)
        assert breakdown['drawdown'] < 0


class TestForexTradingEnvironment:
    """Test forex trading environment."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=20,
            normalization_method='minmax',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0,
            max_episode_steps=100,
            min_episode_steps=10
        )
        self.market_data = create_sample_market_data(200)
        self.env = ForexTradingEnvironment(self.market_data, self.config)
        
    def test_environment_initialization(self):
        """Test environment initialization."""
        assert self.env.config == self.config
        assert len(self.env.market_data) == 200
        assert self.env.current_step == 0
        assert not self.env.done
        
    def test_observation_space_shape(self):
        """Test observation space shape."""
        shape = self.env.get_observation_space_shape()
        assert isinstance(shape, tuple)
        assert len(shape) == 1
        assert shape[0] > 0
        
    def test_action_space_size(self):
        """Test action space size."""
        size = self.env.get_action_space_size()
        assert size == len(ActionType)
        assert size == 8  # HOLD, BUY_SMALL, BUY_MEDIUM, BUY_LARGE, SELL_SMALL, SELL_MEDIUM, SELL_LARGE, CLOSE_POSITION
        
    def test_reset(self):
        """Test environment reset."""
        initial_state = self.env.reset()
        
        assert isinstance(initial_state, np.ndarray)
        assert initial_state.shape == self.env.get_observation_space_shape()
        assert self.env.current_step == 0
        assert not self.env.done
        assert self.env.portfolio.balance == self.config.initial_balance
        assert self.env.portfolio.current_position == 0.0
        
    def test_step_hold_action(self):
        """Test step with HOLD action."""
        self.env.reset()
        
        state, reward, done, info = self.env.step(ActionType.HOLD.value)
        
        assert isinstance(state, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert isinstance(info, dict)
        
        assert self.env.current_step == 1
        assert self.env.portfolio.current_position == 0.0
        assert info['execution_info']['action_type'] == 'HOLD'
        assert info['execution_info']['executed'] == True
        
    def test_step_buy_action(self):
        """Test step with BUY action."""
        self.env.reset()
        
        state, reward, done, info = self.env.step(ActionType.BUY_MEDIUM.value)
        
        assert self.env.portfolio.current_position > 0
        assert info['execution_info']['action_type'] == 'BUY_MEDIUM'
        assert info['execution_info']['executed'] == True
        assert self.env.portfolio.total_trades == 1
        
    def test_step_sell_action(self):
        """Test step with SELL action."""
        self.env.reset()
        
        state, reward, done, info = self.env.step(ActionType.SELL_MEDIUM.value)
        
        assert self.env.portfolio.current_position < 0
        assert info['execution_info']['action_type'] == 'SELL_MEDIUM'
        assert info['execution_info']['executed'] == True
        assert self.env.portfolio.total_trades == 1
        
    def test_step_close_position(self):
        """Test closing position."""
        self.env.reset()
        
        # First, open a position
        self.env.step(ActionType.BUY_MEDIUM.value)
        assert self.env.portfolio.current_position > 0
        
        # Then close it
        state, reward, done, info = self.env.step(ActionType.CLOSE_POSITION.value)
        
        assert abs(self.env.portfolio.current_position) < 1e-6
        assert info['execution_info']['action_type'] == 'CLOSE_POSITION'
        assert info['execution_info']['executed'] == True
        
    def test_position_limits(self):
        """Test position size limits."""
        self.env.reset()
        
        # Try to exceed position limit
        for _ in range(10):  # Try to build large position
            self.env.step(ActionType.BUY_LARGE.value)
            
        # Position should be capped at max_position_size
        assert self.env.portfolio.current_position <= self.config.max_position_size
        
    def test_episode_termination(self):
        """Test episode termination conditions."""
        self.env.reset()
        
        # Run until episode ends
        done = False
        steps = 0
        while not done and steps < self.config.max_episode_steps + 10:
            state, reward, done, info = self.env.step(ActionType.HOLD.value)
            steps += 1
            
        assert done
        assert 'termination_reason' in info
        
    def test_seed_reproducibility(self):
        """Test that seeding produces reproducible results."""
        # Reset with same seed
        self.env.seed(42)
        state1 = self.env.reset()
        
        self.env.seed(42)
        state2 = self.env.reset()
        
        np.testing.assert_array_equal(state1, state2)
        
    def test_render(self):
        """Test rendering functionality."""
        self.env.reset()
        
        # Should not raise exception
        self.env.render('human')
        result = self.env.render('rgb_array')
        assert result is None  # Default implementation returns None
        
    def test_episode_summary(self):
        """Test episode summary generation."""
        self.env.reset()
        
        # Run a few steps
        for _ in range(10):
            self.env.step(ActionType.HOLD.value)
            
        # Force episode to end
        self.env.done = True
        
        summary = self.env.get_episode_summary()
        
        assert isinstance(summary, dict)
        assert 'episode_length' in summary
        assert 'total_return' in summary
        assert 'final_balance' in summary
        assert 'win_rate' in summary
        assert 'sharpe_ratio' in summary
        
    def test_invalid_action(self):
        """Test handling of invalid actions."""
        self.env.reset()
        
        with pytest.raises(ValueError):
            self.env.step(-1)  # Invalid action
            
        with pytest.raises(ValueError):
            self.env.step(10)  # Invalid action
            
    def test_step_after_done(self):
        """Test stepping after episode is done."""
        self.env.reset()
        self.env.done = True
        
        with pytest.raises(RuntimeError):
            self.env.step(ActionType.HOLD.value)


def test_integration():
    """Integration test for complete environment workflow."""
    # Create environment
    config = EnvironmentConfig(
        state_features=['price', 'technical', 'portfolio'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=10,
        normalization_method='minmax',
        transaction_cost=0.0001,
        max_position_size=0.5,
        initial_balance=10000.0,
        max_episode_steps=50,
        min_episode_steps=5
    )
    
    market_data = create_sample_market_data(100)
    env = ForexTradingEnvironment(market_data, config)
    
    # Run complete episode
    env.seed(123)
    state = env.reset()
    
    total_reward = 0
    episode_length = 0
    
    while not env.done:
        # Random action selection
        action = np.random.choice(env.get_action_space_size())
        
        next_state, reward, done, info = env.step(action)
        
        total_reward += reward
        episode_length += 1
        
        # Validate step results
        assert isinstance(next_state, np.ndarray)
        assert isinstance(reward, float)
        assert isinstance(done, bool)
        assert isinstance(info, dict)
        
        state = next_state
        
        # Safety check
        if episode_length > config.max_episode_steps + 10:
            break
            
    # Validate episode completion
    assert env.done
    assert episode_length > 0
    
    # Get episode summary
    summary = env.get_episode_summary()
    assert summary['episode_length'] == episode_length
    
    print(f"Integration test completed successfully!")
    print(f"Episode length: {episode_length}")
    print(f"Total reward: {total_reward:.4f}")
    print(f"Final equity: ${summary['final_equity']:.2f}")
    print(f"Total return: {summary['total_return']:.2%}")


if __name__ == "__main__":
    # Run integration test
    test_integration()
    
    print("\nRunning all unit tests...")
    
    # Run all tests
    pytest.main([__file__, "-v"])
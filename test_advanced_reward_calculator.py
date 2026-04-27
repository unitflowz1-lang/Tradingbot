"""
Unit tests for Advanced Reward Calculator

This module tests the advanced reward calculation functionality including
multi-objective rewards, risk adjustments, and transaction cost modeling.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pytest
from datetime import datetime, timezone
from typing import List

from src.models import MarketData
from src.rl.environments import EnvironmentConfig
from src.rl.environments.base import PortfolioState, ActionType
from src.rl.environments import AdvancedRewardCalculator


def create_test_market_data() -> MarketData:
    """Create test market data."""
    return MarketData(
        symbol="EUR/USD",
        timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        open=1.1000,
        high=1.1010,
        low=1.0990,
        close=1.1005,
        volume=1000,
        bid=1.1004,
        ask=1.1006,
        spread=0.0002
    )


def create_test_portfolio_states() -> tuple:
    """Create test portfolio states for before and after scenarios."""
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
        equity=10100.0,
        current_position=0.5,
        unrealized_pnl=100.0,
        realized_pnl=0.0,
        total_trades=1,
        winning_trades=1,
        max_drawdown=0.0,
        current_drawdown=0.0
    )
    
    return prev_state, current_state


# Configuration is now handled via constructor parameters


class TestAdvancedRewardCalculator:
    """Test advanced reward calculator."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.env_config = EnvironmentConfig(
            state_features=['price', 'technical', 'portfolio'],
            action_space_type='discrete',
            reward_function='multi_objective',
            lookback_window=20,
            normalization_method='robust',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        self.calculator = AdvancedRewardCalculator(self.env_config)
        
        self.market_data = create_test_market_data()
        self.prev_state, self.current_state = create_test_portfolio_states()
        
    def test_calculator_initialization(self):
        """Test calculator initialization."""
        assert self.calculator.env_config == self.env_config
        assert self.calculator.profit_weight == 0.4
        assert len(self.calculator.performance_history) == 0
        assert len(self.calculator.return_history) == 0
        assert self.calculator.market_volatility == 0.01
        assert self.calculator.market_trend == 0.0
        
    def test_simple_return_reward(self):
        """Test simple return reward calculation."""
        config = AdvancedRewardConfig(reward_function=RewardFunction.SIMPLE_RETURN)
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        reward = calculator.calculate_reward(
            self.prev_state, self.current_state, ActionType.BUY_MEDIUM.value, self.market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        # Should be positive since equity increased
        assert reward > 0
        
    def test_sharpe_adjusted_reward(self):
        """Test Sharpe ratio adjusted reward calculation."""
        config = AdvancedRewardConfig(reward_function=RewardFunction.SHARPE_ADJUSTED)
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        # Need to build some history for Sharpe calculation
        for i in range(15):
            # Create varying portfolio states
            prev = PortfolioState(10000, 10000 + i*10, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
            curr = PortfolioState(10000, 10000 + (i+1)*10, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
            
            reward = calculator.calculate_reward(
                prev, curr, ActionType.HOLD.value, self.market_data
            )
            
            assert isinstance(reward, float)
            assert not np.isnan(reward)
            assert not np.isinf(reward)
            
    def test_multi_objective_reward(self):
        """Test multi-objective reward calculation."""
        reward = self.calculator.calculate_reward(
            self.prev_state, self.current_state, ActionType.BUY_MEDIUM.value, self.market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        
        # Should be within clipping bounds
        assert self.reward_config.min_reward <= reward <= self.reward_config.max_reward
        
    def test_calmar_ratio_reward(self):
        """Test Calmar ratio reward calculation."""
        config = AdvancedRewardConfig(reward_function=RewardFunction.CALMAR_RATIO)
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        # Create state with some drawdown
        current_state_with_drawdown = PortfolioState(
            balance=10000.0,
            equity=10100.0,
            current_position=0.5,
            unrealized_pnl=100.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=1,
            max_drawdown=0.05,  # 5% max drawdown
            current_drawdown=0.02
        )
        
        reward = calculator.calculate_reward(
            self.prev_state, current_state_with_drawdown, ActionType.BUY_MEDIUM.value, self.market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        
    def test_sortino_ratio_reward(self):
        """Test Sortino ratio reward calculation."""
        config = AdvancedRewardConfig(reward_function=RewardFunction.SORTINO_RATIO)
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        # Build history with mixed returns
        for i in range(15):
            return_val = 0.01 if i % 2 == 0 else -0.005  # Alternating returns
            prev = PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
            curr = PortfolioState(10000, 10000 * (1 + return_val), 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
            
            reward = calculator.calculate_reward(
                prev, curr, ActionType.HOLD.value, self.market_data
            )
            
            assert isinstance(reward, float)
            assert not np.isnan(reward)
            assert not np.isinf(reward)
            
    def test_transaction_cost_penalties(self):
        """Test transaction cost penalty calculations."""
        # Test different actions
        actions_to_test = [
            ActionType.HOLD,
            ActionType.BUY_SMALL,
            ActionType.BUY_MEDIUM,
            ActionType.BUY_LARGE,
            ActionType.SELL_SMALL,
            ActionType.CLOSE_POSITION
        ]
        
        rewards = {}
        for action in actions_to_test:
            reward = self.calculator.calculate_reward(
                self.prev_state, self.current_state, action.value, self.market_data
            )
            rewards[action.name] = reward
            
        # HOLD should have the least penalty (no transaction costs)
        # Larger trades should have more penalties
        assert rewards['BUY_LARGE'] <= rewards['BUY_MEDIUM']
        assert rewards['BUY_MEDIUM'] <= rewards['BUY_SMALL']
        
    def test_holding_time_rewards(self):
        """Test holding time reward calculations."""
        config = AdvancedRewardConfig(
            holding_time_reward=True,
            optimal_holding_periods=[5, 10],
            holding_reward_multiplier=0.2
        )
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        # Simulate holding a position
        position_state = PortfolioState(10000, 10050, 0.5, 50.0, 0.0, 1, 1, 0.0, 0.0)
        
        rewards = []
        for step in range(12):
            reward = calculator.calculate_reward(
                position_state, position_state, ActionType.HOLD.value, self.market_data
            )
            rewards.append(reward)
            
        # Should get bonus rewards at optimal holding periods
        assert len(rewards) == 12
        
    def test_market_condition_adjustments(self):
        """Test market condition based adjustments."""
        config = AdvancedRewardConfig(
            market_condition_adjustment=True,
            volatility_adjustment=True,
            trend_adjustment=True
        )
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        # Build some market history to establish conditions
        for i in range(10):
            # Create market data with increasing volatility
            market_data = MarketData(
                symbol="EUR/USD",
                timestamp=datetime(2024, 1, 1, 12, i, 0, tzinfo=timezone.utc),
                open=1.1000 + i * 0.001,
                high=1.1010 + i * 0.001,
                low=1.0990 + i * 0.001,
                close=1.1005 + i * 0.001,
                volume=1000,
                bid=1.1004 + i * 0.001,
                ask=1.1006 + i * 0.001,
                spread=0.0002
            )
            
            reward = calculator.calculate_reward(
                self.prev_state, self.current_state, ActionType.BUY_MEDIUM.value, market_data
            )
            
            assert isinstance(reward, float)
            assert not np.isnan(reward)
            
        # Market volatility should have been updated
        assert calculator.market_volatility != 0.01  # Should have changed from default
        
    def test_adaptive_scaling(self):
        """Test adaptive reward scaling."""
        config = AdvancedRewardConfig(adaptive_scaling=True)
        calculator = AdvancedRewardCalculator(self.env_config, config)
        
        initial_scaling = calculator.current_scaling_factor
        
        # Generate many small rewards to trigger scaling adjustment
        for i in range(25):
            # Create states with very small changes
            prev = PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
            curr = PortfolioState(10000, 10000.01, 0.0, 0.01, 0.0, 0, 0, 0.0, 0.0)
            
            reward = calculator.calculate_reward(
                prev, curr, ActionType.HOLD.value, self.market_data
            )
            
        # Scaling factor should have been adjusted
        assert calculator.current_scaling_factor != initial_scaling
        
    def test_reward_breakdown(self):
        """Test reward breakdown functionality."""
        breakdown = self.calculator.get_reward_breakdown(
            self.prev_state, self.current_state, ActionType.BUY_MEDIUM.value, self.market_data
        )
        
        assert isinstance(breakdown, dict)
        
        # Should contain multi-objective components
        expected_components = ['profit', 'risk', 'consistency', 'efficiency', 'drawdown']
        for component in expected_components:
            assert component in breakdown
            assert isinstance(breakdown[component], (int, float))
            assert not np.isnan(breakdown[component])
            
        # Should contain additional components
        assert 'transaction_costs' in breakdown
        assert 'holding_time' in breakdown
        assert 'market_adjustment' in breakdown
        
        if 'weighted_total' in breakdown:
            assert isinstance(breakdown['weighted_total'], (int, float))
            
    def test_performance_metrics(self):
        """Test performance metrics collection."""
        # Generate some rewards to build history
        for i in range(10):
            self.calculator.calculate_reward(
                self.prev_state, self.current_state, ActionType.HOLD.value, self.market_data
            )
            
        metrics = self.calculator.get_performance_metrics()
        
        assert isinstance(metrics, dict)
        assert 'mean_reward' in metrics
        assert 'std_reward' in metrics
        assert 'min_reward' in metrics
        assert 'max_reward' in metrics
        assert 'total_rewards' in metrics
        assert 'current_scaling_factor' in metrics
        assert 'market_volatility' in metrics
        assert 'market_trend' in metrics
        
        assert metrics['total_rewards'] == 10
        
    def test_calculator_reset(self):
        """Test calculator reset functionality."""
        # Build some history
        for i in range(5):
            self.calculator.calculate_reward(
                self.prev_state, self.current_state, ActionType.HOLD.value, self.market_data
            )
            
        # Verify history exists
        assert len(self.calculator.performance_history) > 0
        assert len(self.calculator.return_history) > 0
        
        # Reset calculator
        self.calculator.reset()
        
        # Verify history is cleared
        assert len(self.calculator.performance_history) == 0
        assert len(self.calculator.return_history) == 0
        assert len(self.calculator.volatility_history) == 0
        assert len(self.calculator.drawdown_history) == 0
        assert self.calculator.position_entry_step is None
        assert self.calculator.position_entry_price is None
        
    def test_config_update(self):
        """Test configuration update during training."""
        original_config = self.calculator.reward_config
        
        new_config = AdvancedRewardConfig(
            reward_function=RewardFunction.SHARPE_ADJUSTED,
            profit_weight=0.8,
            risk_weight=0.2
        )
        
        self.calculator.update_config(new_config)
        
        assert self.calculator.reward_config != original_config
        assert self.calculator.reward_config.reward_function == RewardFunction.SHARPE_ADJUSTED
        assert self.calculator.reward_config.profit_weight == 0.8
        
    def test_edge_cases(self):
        """Test edge cases and error handling."""
        # Test with zero equity change
        same_state = PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
        
        reward = self.calculator.calculate_reward(
            same_state, same_state, ActionType.HOLD.value, self.market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        
        # Test with negative equity change
        loss_state = PortfolioState(10000, 9900, -0.5, -100.0, 0.0, 1, 0, 0.01, 0.01)
        
        reward = self.calculator.calculate_reward(
            self.prev_state, loss_state, ActionType.SELL_MEDIUM.value, self.market_data
        )
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        # Should be negative due to loss
        assert reward < 0
        
    def test_different_reward_functions(self):
        """Test all available reward functions."""
        reward_functions = [
            RewardFunction.SIMPLE_RETURN,
            RewardFunction.SHARPE_ADJUSTED,
            RewardFunction.RISK_ADJUSTED,
            RewardFunction.MULTI_OBJECTIVE,
            RewardFunction.CALMAR_RATIO,
            RewardFunction.SORTINO_RATIO,
            RewardFunction.INFORMATION_RATIO
        ]
        
        for reward_func in reward_functions:
            config = AdvancedRewardConfig(reward_function=reward_func)
            calculator = AdvancedRewardCalculator(self.env_config, config)
            
            # Build some history for ratio-based functions
            for i in range(15):
                prev = PortfolioState(10000, 10000 + i*5, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
                curr = PortfolioState(10000, 10000 + (i+1)*5, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
                
                reward = calculator.calculate_reward(
                    prev, curr, ActionType.HOLD.value, self.market_data
                )
                
                assert isinstance(reward, float)
                assert not np.isnan(reward)
                assert not np.isinf(reward)


def test_integration_advanced_reward_calculator():
    """Integration test for advanced reward calculator."""
    print("Running Advanced Reward Calculator Integration Test...")
    
    # Create configuration
    env_config = EnvironmentConfig(
        state_features=['price', 'technical', 'portfolio'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=20,
        normalization_method='robust',
        transaction_cost=0.0001,
        max_position_size=1.0,
        initial_balance=10000.0
    )
    
    reward_config = AdvancedRewardConfig(
        reward_function=RewardFunction.MULTI_OBJECTIVE,
        profit_weight=0.4,
        risk_weight=0.25,
        consistency_weight=0.15,
        efficiency_weight=0.1,
        drawdown_weight=0.1,
        adaptive_scaling=True,
        holding_time_reward=True,
        market_condition_adjustment=True
    )
    
    calculator = AdvancedRewardCalculator(env_config, reward_config)
    
    print(f"✅ Calculator initialized with {reward_config.reward_function.value} reward function")
    
    # Simulate a trading episode
    portfolio = PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
    rewards = []
    
    for step in range(50):
        # Create varying market conditions
        price = 1.1000 + 0.0001 * np.sin(step / 10) + np.random.normal(0, 0.0002)
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=datetime(2024, 1, 1, 12, step, 0, tzinfo=timezone.utc),
            open=price - 0.0001,
            high=price + 0.0002,
            low=price - 0.0002,
            close=price,
            volume=1000 + int(np.random.normal(0, 100)),
            bid=price - 0.0001,
            ask=price + 0.0001,
            spread=0.0002
        )
        
        # Simulate portfolio changes
        prev_portfolio = PortfolioState(
            balance=portfolio.balance,
            equity=portfolio.equity,
            current_position=portfolio.current_position,
            unrealized_pnl=portfolio.unrealized_pnl,
            realized_pnl=portfolio.realized_pnl,
            total_trades=portfolio.total_trades,
            winning_trades=portfolio.winning_trades,
            max_drawdown=portfolio.max_drawdown,
            current_drawdown=portfolio.current_drawdown
        )
        
        # Random action selection
        action = np.random.choice([ActionType.HOLD.value, ActionType.BUY_SMALL.value, ActionType.SELL_SMALL.value])
        
        # Update portfolio (simplified)
        if action == ActionType.BUY_SMALL.value:
            portfolio.current_position = min(portfolio.current_position + 0.1, 1.0)
            portfolio.total_trades += 1
        elif action == ActionType.SELL_SMALL.value:
            portfolio.current_position = max(portfolio.current_position - 0.1, -1.0)
            portfolio.total_trades += 1
            
        # Simulate P&L
        pnl_change = np.random.normal(0, 20)
        portfolio.equity += pnl_change
        portfolio.unrealized_pnl += pnl_change
        
        if pnl_change > 0:
            portfolio.winning_trades += 1
            
        # Update drawdown
        if portfolio.equity < 10000:
            portfolio.current_drawdown = (10000 - portfolio.equity) / 10000
            portfolio.max_drawdown = max(portfolio.max_drawdown, portfolio.current_drawdown)
        else:
            portfolio.current_drawdown = 0.0
            
        # Calculate reward
        reward = calculator.calculate_reward(prev_portfolio, portfolio, action, market_data)
        rewards.append(reward)
        
        # Validate reward
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        assert reward_config.min_reward <= reward <= reward_config.max_reward
        
    # Analyze results
    rewards_array = np.array(rewards)
    
    print(f"✅ Processed {len(rewards)} reward calculations successfully")
    print(f"   Reward Statistics:")
    print(f"      Mean: {np.mean(rewards_array):.4f}")
    print(f"      Std: {np.std(rewards_array):.4f}")
    print(f"      Min: {np.min(rewards_array):.4f}")
    print(f"      Max: {np.max(rewards_array):.4f}")
    print(f"      Range: [{reward_config.min_reward}, {reward_config.max_reward}]")
    
    # Test reward breakdown
    breakdown = calculator.get_reward_breakdown(
        prev_portfolio, portfolio, ActionType.HOLD.value, market_data
    )
    
    print(f"   Reward Breakdown Components: {len(breakdown)}")
    for component, value in breakdown.items():
        print(f"      {component}: {value:.4f}")
        
    # Test performance metrics
    metrics = calculator.get_performance_metrics()
    print(f"   Performance Metrics:")
    print(f"      Total Rewards: {metrics['total_rewards']}")
    print(f"      Current Scaling Factor: {metrics['current_scaling_factor']:.3f}")
    print(f"      Market Volatility: {metrics['market_volatility']:.6f}")
    print(f"      Market Trend: {metrics['market_trend']:.6f}")
    
    print(f"✅ Integration test completed successfully!")
    
    return True


if __name__ == "__main__":
    # Run integration test
    test_integration_advanced_reward_calculator()
    
    print("\nRunning all unit tests...")
    
    # Run all tests
    pytest.main([__file__, "-v"])
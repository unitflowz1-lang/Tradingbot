"""
Simple test for Advanced Reward Calculator
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from datetime import datetime, timezone

from src.models import MarketData
from src.rl.environments import EnvironmentConfig, AdvancedRewardCalculator
from src.rl.environments.base import PortfolioState, ActionType


def create_test_data():
    """Create test data for reward calculation."""
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
    
    market_data = MarketData(
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
    
    return env_config, prev_state, current_state, market_data


def test_basic_functionality():
    """Test basic reward calculator functionality."""
    print("🧪 Testing Advanced Reward Calculator")
    print("=" * 50)
    
    # Create test data
    env_config, prev_state, current_state, market_data = create_test_data()
    
    # Create calculator
    calculator = AdvancedRewardCalculator(env_config)
    print(f"✅ Calculator created successfully")
    
    # Test reward calculation
    reward = calculator.calculate_reward(prev_state, current_state, ActionType.BUY_MEDIUM.value, market_data)
    print(f"✅ Reward calculated: {reward:.4f}")
    
    assert isinstance(reward, float)
    assert not np.isnan(reward)
    assert not np.isinf(reward)
    assert -10.0 <= reward <= 10.0
    
    # Test reward breakdown
    breakdown = calculator.get_reward_breakdown(prev_state, current_state, ActionType.BUY_MEDIUM.value, market_data)
    print(f"✅ Reward breakdown: {len(breakdown)} components")
    
    expected_components = ['profit', 'risk', 'consistency', 'efficiency', 'drawdown', 'transaction']
    for component in expected_components:
        assert component in breakdown
        assert isinstance(breakdown[component], (int, float))
        assert not np.isnan(breakdown[component])
        
    # Test performance metrics
    metrics = calculator.get_performance_metrics()
    print(f"✅ Performance metrics: {len(metrics)} metrics")
    
    # Test multiple calculations
    rewards = []
    for i in range(10):
        # Vary the states slightly
        test_current = PortfolioState(
            balance=10000.0,
            equity=10000.0 + i * 10,
            current_position=i * 0.1,
            unrealized_pnl=i * 10,
            realized_pnl=0.0,
            total_trades=i,
            winning_trades=i // 2,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        reward = calculator.calculate_reward(prev_state, test_current, ActionType.HOLD.value, market_data)
        rewards.append(reward)
        
    print(f"✅ Multiple calculations: {len(rewards)} rewards")
    print(f"   Reward range: [{min(rewards):.4f}, {max(rewards):.4f}]")
    
    # Test reset
    calculator.reset()
    assert len(calculator.performance_history) == 0
    assert len(calculator.return_history) == 0
    print(f"✅ Reset functionality working")
    
    # Test different actions
    actions_rewards = {}
    for action in [ActionType.HOLD, ActionType.BUY_SMALL, ActionType.SELL_SMALL, ActionType.CLOSE_POSITION]:
        reward = calculator.calculate_reward(prev_state, current_state, action.value, market_data)
        actions_rewards[action.name] = reward
        
    print(f"✅ Different actions tested:")
    for action_name, reward in actions_rewards.items():
        print(f"   {action_name}: {reward:.4f}")
        
    print(f"\n🎉 All tests passed successfully!")
    return True


def test_integration():
    """Test integration with trading environment."""
    print("\n🔗 Integration Test")
    print("=" * 30)
    
    env_config, prev_state, current_state, market_data = create_test_data()
    
    # Test with different configurations
    configs = [
        {"profit_weight": 1.0, "risk_weight": 0.0},  # Pure profit
        {"profit_weight": 0.5, "risk_weight": 0.5},  # Balanced
        {"adaptive_scaling": False},  # No adaptive scaling
        {"reward_scaling": 50.0}  # Different scaling
    ]
    
    for i, config in enumerate(configs):
        calculator = AdvancedRewardCalculator(env_config, **config)
        reward = calculator.calculate_reward(prev_state, current_state, ActionType.BUY_MEDIUM.value, market_data)
        print(f"   Config {i+1}: {reward:.4f}")
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        
    print(f"✅ Integration test completed")
    return True


if __name__ == "__main__":
    try:
        success1 = test_basic_functionality()
        success2 = test_integration()
        
        if success1 and success2:
            print(f"\n🏆 All tests completed successfully!")
            print(f"   Advanced Reward Calculator is ready for use!")
        else:
            print(f"\n❌ Some tests failed")
            
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
"""
Simple test for advanced reward calculator
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    from src.rl.environments.advanced_reward_calculator import AdvancedRewardCalculator, AdvancedRewardConfig, RewardFunction
    print("✅ Import successful!")
    
    # Test basic functionality
    from src.rl.environments import EnvironmentConfig
    from src.rl.environments.base import PortfolioState
    from src.models import MarketData
    from datetime import datetime, timezone
    
    # Create test objects
    env_config = EnvironmentConfig(
        state_features=['price'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=20,
        normalization_method='robust',
        transaction_cost=0.0001,
        max_position_size=1.0,
        initial_balance=10000.0
    )
    
    reward_config = AdvancedRewardConfig()
    calculator = AdvancedRewardCalculator(env_config, reward_config)
    
    # Create test states
    prev_state = PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
    current_state = PortfolioState(10000, 10100, 0.5, 100.0, 0.0, 1, 1, 0.0, 0.0)
    
    # Create test market data
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
    
    # Test reward calculation
    reward = calculator.calculate_reward(prev_state, current_state, 1, market_data)
    print(f"✅ Reward calculation successful: {reward:.4f}")
    
    # Test reward breakdown
    breakdown = calculator.get_reward_breakdown(prev_state, current_state, 1, market_data)
    print(f"✅ Reward breakdown successful: {len(breakdown)} components")
    
    print("✅ All tests passed!")
    
except ImportError as e:
    print(f"❌ Import failed: {e}")
except Exception as e:
    print(f"❌ Test failed: {e}")
    import traceback
    traceback.print_exc()
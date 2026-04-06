"""
Demo script for RL Trading Environment

This script demonstrates how to use the ForexTradingEnvironment
for training RL agents on forex market data.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List

# Optional matplotlib import
try:
    import matplotlib.pyplot as plt
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False

from src.models import MarketData
from src.rl.environments import (
    ForexTradingEnvironment, 
    EnvironmentConfig, 
    ActionType,
    DefaultStateProcessor,
    DefaultRewardCalculator
)


def create_realistic_market_data(num_points: int = 1000, 
                               start_price: float = 1.1000) -> List[MarketData]:
    """Create realistic forex market data with trends and volatility."""
    data = []
    current_price = start_price
    # Use historical date to avoid validation issues
    base_time = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    
    # Add some market regimes
    trend_changes = [200, 400, 600, 800]  # Points where trend changes
    trends = [0.0001, -0.0002, 0.00015, -0.0001, 0.00005]  # Trend strengths
    
    current_trend_idx = 0
    
    for i in range(num_points):
        # Change trend at specified points
        if i in trend_changes and current_trend_idx < len(trends) - 1:
            current_trend_idx += 1
            
        # Apply trend and random walk
        trend = trends[current_trend_idx]
        volatility = 0.0008 + 0.0004 * np.sin(i / 100)  # Varying volatility
        
        price_change = trend + np.random.normal(0, volatility)
        current_price += price_change
        
        # Ensure reasonable price bounds
        current_price = max(min(current_price, 1.3000), 0.9000)
        
        # Create realistic OHLC data
        intrabar_volatility = volatility * 0.5
        high = current_price + abs(np.random.normal(0, intrabar_volatility))
        low = current_price - abs(np.random.normal(0, intrabar_volatility))
        open_price = current_price + np.random.normal(0, intrabar_volatility * 0.3)
        
        # Ensure OHLC relationships
        high = max(high, current_price, open_price)
        low = min(low, current_price, open_price)
        
        # Create realistic bid/ask spread (1-2 pips)
        spread = 0.0001 + np.random.uniform(0, 0.0001)
        bid = current_price - spread/2
        ask = current_price + spread/2
        
        # Realistic volume with some correlation to volatility
        base_volume = 1000
        volume_multiplier = 1 + abs(price_change) * 10000  # Higher volume on big moves
        volume = int(base_volume * volume_multiplier * (1 + np.random.uniform(-0.3, 0.3)))
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=base_time + timedelta(minutes=i),
            open=open_price,
            high=high,
            low=low,
            close=current_price,
            volume=volume,
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        data.append(market_data)
        
    return data


def simple_trading_strategy(state: np.ndarray, step: int) -> int:
    """
    Simple trading strategy for demonstration.
    
    This is just for demo purposes - real RL agents would learn
    much more sophisticated strategies.
    """
    # Extract some features from state (this is simplified)
    # In reality, you'd need to understand the state structure
    
    # Simple momentum strategy
    if step < 10:
        return ActionType.HOLD.value
        
    # Random strategy with some logic
    if np.random.random() < 0.7:
        return ActionType.HOLD.value
    elif np.random.random() < 0.5:
        return ActionType.BUY_SMALL.value
    else:
        return ActionType.SELL_SMALL.value


def run_trading_demo():
    """Run a complete trading environment demonstration."""
    print("🚀 RL Trading Environment Demo")
    print("=" * 50)
    
    # Create configuration
    config = EnvironmentConfig(
        state_features=['price', 'technical', 'portfolio'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=20,
        normalization_method='minmax',
        transaction_cost=0.0001,  # 1 pip transaction cost
        max_position_size=1.0,    # Max 100% position
        initial_balance=10000.0,  # $10,000 starting balance
        max_episode_steps=200,    # 200 steps per episode
        min_episode_steps=50      # Minimum 50 steps
    )
    
    print(f"📊 Environment Configuration:")
    print(f"   Initial Balance: ${config.initial_balance:,.2f}")
    print(f"   Transaction Cost: {config.transaction_cost:.4f}")
    print(f"   Max Position Size: {config.max_position_size:.1%}")
    print(f"   Lookback Window: {config.lookback_window} steps")
    print(f"   Episode Length: {config.min_episode_steps}-{config.max_episode_steps} steps")
    
    # Create market data
    print(f"\n📈 Generating Market Data...")
    market_data = create_realistic_market_data(1000)
    print(f"   Generated {len(market_data)} data points")
    print(f"   Price range: ${min(d.close for d in market_data):.4f} - ${max(d.close for d in market_data):.4f}")
    
    # Create environment
    print(f"\n🏗️  Creating Trading Environment...")
    env = ForexTradingEnvironment(market_data, config)
    print(f"   State dimension: {env.get_observation_space_shape()[0]}")
    print(f"   Action space size: {env.get_action_space_size()}")
    
    # Run multiple episodes
    num_episodes = 3
    episode_results = []
    
    for episode in range(num_episodes):
        print(f"\n🎯 Episode {episode + 1}/{num_episodes}")
        print("-" * 30)
        
        # Reset environment
        env.seed(42 + episode)  # Different seed for each episode
        state = env.reset()
        
        episode_rewards = []
        episode_actions = []
        episode_positions = []
        episode_equity = []
        
        step = 0
        while not env.done:
            # Select action using simple strategy
            action = simple_trading_strategy(state, step)
            
            # Execute action
            next_state, reward, done, info = env.step(action)
            
            # Store data for analysis
            episode_rewards.append(reward)
            episode_actions.append(action)
            episode_positions.append(env.portfolio.current_position)
            episode_equity.append(env.portfolio.equity)
            
            # Print periodic updates
            if step % 50 == 0:
                print(f"   Step {step:3d}: Action={ActionType(action).name:12s} "
                      f"Reward={reward:6.2f} Equity=${env.portfolio.equity:8.2f} "
                      f"Position={env.portfolio.current_position:6.2f}")
            
            state = next_state
            step += 1
            
            # Safety check
            if step > config.max_episode_steps + 10:
                break
                
        # Get episode summary
        summary = env.get_episode_summary()
        episode_results.append(summary)
        
        print(f"\n📊 Episode {episode + 1} Results:")
        print(f"   Episode Length: {summary['episode_length']} steps")
        print(f"   Total Return: {summary['total_return']:.2%}")
        print(f"   Final Equity: ${summary['final_equity']:.2f}")
        print(f"   Total Trades: {summary['total_trades']}")
        print(f"   Win Rate: {summary['win_rate']:.1%}")
        print(f"   Max Drawdown: {summary['max_drawdown']:.2%}")
        print(f"   Sharpe Ratio: {summary['sharpe_ratio']:.2f}")
        print(f"   Total Reward: {summary['total_reward']:.2f}")
        
    # Overall statistics
    print(f"\n📈 Overall Performance Summary")
    print("=" * 50)
    
    avg_return = np.mean([r['total_return'] for r in episode_results])
    avg_sharpe = np.mean([r['sharpe_ratio'] for r in episode_results])
    avg_trades = np.mean([r['total_trades'] for r in episode_results])
    avg_win_rate = np.mean([r['win_rate'] for r in episode_results])
    
    print(f"Average Return: {avg_return:.2%}")
    print(f"Average Sharpe Ratio: {avg_sharpe:.2f}")
    print(f"Average Trades per Episode: {avg_trades:.1f}")
    print(f"Average Win Rate: {avg_win_rate:.1%}")
    
    # Action distribution
    all_actions = []
    for episode in range(num_episodes):
        env.seed(42 + episode)
        state = env.reset()
        step = 0
        while not env.done and step < config.max_episode_steps:
            action = simple_trading_strategy(state, step)
            all_actions.append(action)
            state, _, _, _ = env.step(action)
            step += 1
            
    action_counts = {action.name: 0 for action in ActionType}
    for action in all_actions:
        action_counts[ActionType(action).name] += 1
        
    print(f"\n🎯 Action Distribution:")
    for action_name, count in action_counts.items():
        percentage = count / len(all_actions) * 100
        print(f"   {action_name:15s}: {count:4d} ({percentage:5.1f}%)")
        
    print(f"\n✅ Demo completed successfully!")
    print(f"   Total steps executed: {len(all_actions)}")
    print(f"   Environment is ready for RL agent training!")


def plot_market_data_sample():
    """Plot a sample of the generated market data."""
    if not HAS_MATPLOTLIB:
        print(f"\n📊 Matplotlib not available - skipping plot generation")
        return
        
    print(f"\n📊 Generating sample market data plot...")
    
    # Generate sample data
    data = create_realistic_market_data(500)
    prices = [d.close for d in data]
    timestamps = [d.timestamp for d in data]
    
    # Create plot
    plt.figure(figsize=(12, 6))
    plt.plot(timestamps, prices, linewidth=1, alpha=0.8)
    plt.title('Sample EUR/USD Market Data')
    plt.xlabel('Time')
    plt.ylabel('Price')
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    # Save plot
    plt.savefig('sample_market_data.png', dpi=150, bbox_inches='tight')
    print(f"   Plot saved as 'sample_market_data.png'")
    plt.close()


if __name__ == "__main__":
    try:
        run_trading_demo()
        
        # Optionally create a plot
        plot_market_data_sample()
            
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()
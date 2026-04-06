"""
A/B Testing Framework Example

This example demonstrates how to use the A/B testing framework
for comparing RL trading strategies with statistical significance testing.
"""

import numpy as np
import time
from datetime import datetime, timedelta
import logging

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.rl.strategies.ab_testing import (
    ABTestingFramework, ABTestConfiguration, SignificanceTest
)
from src.rl.strategies.models import (
    RLStrategy, StrategyMetadata, PerformanceMetrics,
    StrategyStatus, AgentType, create_strategy_metadata
)
from src.rl.strategies.registry import StrategyRegistry


# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sample_strategies():
    """Create sample strategies for testing."""
    
    # Strategy A - PPO-based strategy
    metadata_a = create_strategy_metadata(
        name="PPO Momentum Strategy",
        description="PPO agent with momentum indicators",
        agent_type=AgentType.PPO,
        created_by="strategy_team",
        tags=["momentum", "ppo", "v1.0"],
        currency_pairs=["EURUSD", "GBPUSD"],
        timeframe="1H"
    )
    
    performance_a = PerformanceMetrics(
        total_return=0.18,
        sharpe_ratio=1.35,
        max_drawdown=0.08,
        win_rate=0.62,
        profit_factor=1.6,
        calmar_ratio=2.25,
        sortino_ratio=1.8,
        num_trades=150,
        avg_trade_duration=3.2,
        volatility=0.13,
        alpha=0.05,
        beta=0.8,
        information_ratio=0.9
    )
    
    strategy_a = RLStrategy(metadata=metadata_a, performance_metrics=performance_a)
    strategy_a.metadata.status = StrategyStatus.APPROVED
    
    # Strategy B - DQN-based strategy
    metadata_b = create_strategy_metadata(
        name="DQN Mean Reversion Strategy",
        description="DQN agent with mean reversion signals",
        agent_type=AgentType.DQN,
        created_by="strategy_team",
        tags=["mean_reversion", "dqn", "v1.0"],
        currency_pairs=["EURUSD", "GBPUSD"],
        timeframe="1H"
    )
    
    performance_b = PerformanceMetrics(
        total_return=0.14,
        sharpe_ratio=1.15,
        max_drawdown=0.12,
        win_rate=0.58,
        profit_factor=1.4,
        calmar_ratio=1.17,
        sortino_ratio=1.3,
        num_trades=180,
        avg_trade_duration=2.8,
        volatility=0.16,
        alpha=0.02,
        beta=1.1,
        information_ratio=0.6
    )
    
    strategy_b = RLStrategy(metadata=metadata_b, performance_metrics=performance_b)
    strategy_b.metadata.status = StrategyStatus.APPROVED
    
    return strategy_a, strategy_b


def simulate_live_performance(strategy_id: str, base_sharpe: float, days: int = 30):
    """Simulate live performance data for a strategy."""
    performance_data = []
    
    for day in range(days):
        # Simulate daily performance with some noise
        daily_sharpe = base_sharpe + np.random.normal(0, 0.1)
        daily_return = np.random.normal(0.001, 0.02)  # Daily return
        daily_drawdown = abs(np.random.normal(0.005, 0.01))  # Daily drawdown
        
        performance_data.append({
            'timestamp': datetime.now() - timedelta(days=days-day),
            'sharpe_ratio': daily_sharpe,
            'total_return': daily_return,
            'max_drawdown': daily_drawdown,
            'win_rate': np.random.uniform(0.45, 0.65),
            'volatility': np.random.uniform(0.10, 0.20)
        })
    
    return performance_data


def main():
    """Main example function."""
    print("=== A/B Testing Framework Example ===\n")
    
    # 1. Setup strategy registry and A/B testing framework
    print("1. Setting up strategy registry and A/B testing framework...")
    registry = StrategyRegistry("data/example_strategies")
    
    # Create and register sample strategies
    strategy_a, strategy_b = create_sample_strategies()
    
    strategy_a_id = registry.register_strategy(strategy_a)
    strategy_b_id = registry.register_strategy(strategy_b)
    
    print(f"   Registered Strategy A: {strategy_a_id} ({strategy_a.name})")
    print(f"   Registered Strategy B: {strategy_b_id} ({strategy_b.name})")
    
    # Initialize A/B testing framework
    ab_framework = ABTestingFramework(
        strategy_registry=registry,
        min_confidence_level=0.95,
        auto_switch_enabled=True
    )
    
    # 2. Create A/B test configuration
    print("\n2. Creating A/B test configuration...")
    test_config = ABTestConfiguration(
        test_name="PPO vs DQN Strategy Comparison",
        strategy_a_id=strategy_a_id,
        strategy_b_id=strategy_b_id,
        allocation_split=(0.6, 0.4),  # 60% to A, 40% to B
        primary_metric="sharpe_ratio",
        secondary_metrics=["total_return", "max_drawdown", "win_rate"],
        significance_level=0.05,
        minimum_sample_size=50,
        maximum_duration_days=30,
        early_stopping_enabled=True,
        significance_test=SignificanceTest.WELCH_T_TEST
    )
    
    print(f"   Test Name: {test_config.test_name}")
    print(f"   Allocation Split: {test_config.allocation_split}")
    print(f"   Primary Metric: {test_config.primary_metric}")
    print(f"   Significance Level: {test_config.significance_level}")
    
    # 3. Register callbacks for test events
    print("\n3. Registering event callbacks...")
    
    def on_test_started(test):
        print(f"   📊 Test started: {test.config.test_name}")
    
    def on_significance_achieved(test):
        print(f"   🎯 Significance achieved for test: {test.config.test_name}")
        winner = test.get_winner_recommendation()
        if winner:
            print(f"      Winner: {winner['winner_strategy_name']} "
                  f"(confidence: {winner['confidence']:.1f}%)")
    
    def on_test_completed(test):
        print(f"   ✅ Test completed: {test.config.test_name}")
        print(f"      Reason: {test.stop_reason}")
    
    ab_framework.register_callback('test_started', on_test_started)
    ab_framework.register_callback('significance_achieved', on_significance_achieved)
    ab_framework.register_callback('test_completed', on_test_completed)
    
    # 4. Create and start A/B test
    print("\n4. Creating and starting A/B test...")
    test_id = ab_framework.create_test(test_config, start_immediately=True)
    print(f"   Test ID: {test_id}")
    
    # 5. Calculate required sample size
    print("\n5. Sample size analysis...")
    required_sample_size = ab_framework.calculate_required_sample_size(
        effect_size=0.3,  # Detect 30% effect size
        power=0.8,
        significance_level=0.05
    )
    print(f"   Required sample size per group: {required_sample_size}")
    
    # 6. Simulate live performance data
    print("\n6. Simulating live performance data...")
    
    # Generate historical performance data
    np.random.seed(42)  # For reproducible results
    perf_data_a = simulate_live_performance(strategy_a_id, base_sharpe=1.4, days=60)
    perf_data_b = simulate_live_performance(strategy_b_id, base_sharpe=1.1, days=60)
    
    print(f"   Generated {len(perf_data_a)} data points for Strategy A")
    print(f"   Generated {len(perf_data_b)} data points for Strategy B")
    
    # Feed performance data to the framework
    print("\n7. Feeding performance data to A/B test...")
    for i, (data_a, data_b) in enumerate(zip(perf_data_a, perf_data_b)):
        ab_framework.update_performance(strategy_a_id, data_a)
        ab_framework.update_performance(strategy_b_id, data_b)
        
        # Print progress every 10 data points
        if (i + 1) % 10 == 0:
            status = ab_framework.get_test_status(test_id)
            sample_sizes = (
                status['strategy_a']['sample_size'],
                status['strategy_b']['sample_size']
            )
            print(f"   Progress: {i+1}/60 - Sample sizes: A={sample_sizes[0]}, B={sample_sizes[1]}")
    
    # 8. Get test results
    print("\n8. Analyzing test results...")
    test_results = ab_framework.get_test_results(test_id)
    
    if test_results:
        print(f"   Test Status: {test_results['status']}")
        print(f"   Duration: {test_results['duration_days']:.1f} days")
        
        # Current metrics
        if 'current_metrics' in test_results and test_results['current_metrics']:
            metrics = test_results['current_metrics']
            print(f"\n   Current Performance Metrics:")
            print(f"   Strategy A - Sharpe: {metrics['strategy_a'].get('sharpe_ratio', 'N/A'):.3f}, "
                  f"Return: {metrics['strategy_a'].get('total_return', 'N/A'):.4f}")
            print(f"   Strategy B - Sharpe: {metrics['strategy_b'].get('sharpe_ratio', 'N/A'):.3f}, "
                  f"Return: {metrics['strategy_b'].get('total_return', 'N/A'):.4f}")
        
        # Significance tests
        if 'significance_tests' in test_results and test_results['significance_tests']:
            print(f"\n   Statistical Significance Tests:")
            for metric, result in test_results['significance_tests'].items():
                significance = "✅ Significant" if result['is_significant'] else "❌ Not Significant"
                print(f"   {metric}: p-value={result['p_value']:.4f}, {significance}")
                print(f"      Effect size: {result['effect_size']:.3f}")
        
        # Winner recommendation
        winner = test_results.get('winner_recommendation')
        if winner:
            print(f"\n   🏆 Winner Recommendation:")
            print(f"   Winner: {winner['winner_strategy_name']}")
            print(f"   Confidence: {winner['confidence']:.1f}%")
            print(f"   Improvement: {winner['improvement']:.1f}%")
            print(f"   Statistical Significance: {'Yes' if winner['is_significant'] else 'No'}")
    
    # 9. List all active tests
    print("\n9. Active tests summary...")
    active_tests = ab_framework.list_active_tests()
    for test_info in active_tests:
        print(f"   Test: {test_info['test_name']}")
        print(f"   Status: {test_info['status']}")
        print(f"   Duration: {test_info['duration_days']:.1f} days")
    
    # 10. Demonstrate manual test stopping
    print("\n10. Stopping test manually...")
    success = ab_framework.stop_test(test_id, "Example completed")
    if success:
        print(f"   ✅ Test {test_id} stopped successfully")
    
    # Final results
    final_results = ab_framework.get_test_results(test_id)
    if final_results:
        print(f"\n   Final Status: {final_results['status']}")
        print(f"   Stop Reason: {final_results.get('stop_reason', 'N/A')}")
    
    print("\n=== A/B Testing Example Completed ===")


if __name__ == "__main__":
    main()
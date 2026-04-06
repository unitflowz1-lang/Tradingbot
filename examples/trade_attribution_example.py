"""
Trade Attribution and Analysis Example

This example demonstrates how to use the trade attribution system to analyze
RL agent trading decisions and decompose strategy performance.
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Add src to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from src.rl.monitoring.trade_attribution import (
    TradeAttributionAnalyzer, MarketRegimeDetector, MarketRegime, AttributionFactor
)
from src.rl.monitoring.performance_tracker import TradeRecord
from src.rl.monitoring.logger import RLLogger
from src.rl.agents.base import RLAgent
from src.models import MarketData, Direction


class ExampleRLAgent(RLAgent):
    """Example RL agent for demonstration."""
    
    def __init__(self, agent_id: str = "example_agent"):
        self.agent_id = agent_id
        
    def select_action(self, state, training=False):
        # Simple example: random action selection
        return np.random.choice([0, 1, 2])  # HOLD, BUY, SELL
        
    def store_experience(self, *args):
        pass
        
    def train_step(self):
        return np.random.random()
        
    def get_state(self):
        return {}
        
    def get_training_metrics(self):
        return {}
        
    def update(self, experience):
        pass
        
    def reset_episode(self):
        pass
        
    def save_model(self, filepath):
        pass
        
    def load_model(self, filepath):
        pass
        
    def get_model_info(self):
        return {"type": "ExampleRLAgent", "parameters": 1000}


def create_sample_market_data(num_periods: int = 200) -> list:
    """Create sample market data for demonstration."""
    from datetime import timezone
    base_time = datetime.now(timezone.utc) - timedelta(hours=num_periods)
    data = []
    
    # Create realistic price movement with different regimes
    price = 1.2000
    
    for i in range(num_periods):
        timestamp = base_time + timedelta(hours=i)
        
        # Create different market regimes
        if i < 50:
            # Trending up period
            price += np.random.normal(0.0002, 0.0005)
        elif i < 100:
            # High volatility period
            price += np.random.normal(0, 0.002)
        elif i < 150:
            # Ranging period
            price += np.random.normal(0, 0.0003) + 0.0001 * np.sin(i * 0.2)
        else:
            # Trending down period
            price += np.random.normal(-0.0001, 0.0004)
        
        # Ensure price stays positive
        price = max(price, 0.5)
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=timestamp,
            open=price,
            high=price + abs(np.random.normal(0, 0.0003)),
            low=price - abs(np.random.normal(0, 0.0003)),
            close=price,
            volume=1000 + int(np.random.normal(0, 200)),
            bid=price - 0.00015,
            ask=price + 0.00015,
            spread=0.0003
        )
        data.append(market_data)
    
    return data


def create_sample_trades(market_data: list, agent: RLAgent) -> list:
    """Create sample trades based on market data."""
    trades = []
    
    # Simulate trading decisions at regular intervals
    for i in range(0, len(market_data) - 10, 20):  # Trade every 20 periods
        entry_data = market_data[i]
        exit_idx = min(i + np.random.randint(5, 15), len(market_data) - 1)
        exit_data = market_data[exit_idx]
        
        # Random trade direction
        direction = np.random.choice([-1, 1])  # -1 for short, 1 for long
        position_size = direction * np.random.uniform(0.005, 0.02)
        
        # Calculate P&L
        price_change = exit_data.close - entry_data.close
        pnl = position_size * price_change * 100000  # Convert to base currency
        
        # Add some transaction costs
        pnl -= abs(position_size) * 2.0  # $2 per lot transaction cost
        
        trade = TradeRecord(
            entry_time=entry_data.timestamp,
            exit_time=exit_data.timestamp,
            entry_price=entry_data.close,
            exit_price=exit_data.close,
            position_size=position_size,
            currency_pair="EUR/USD",
            pnl=pnl,
            duration=(exit_data.timestamp - entry_data.timestamp).total_seconds() / 3600,
            agent_id=agent.agent_id,
            strategy_id=agent.agent_id
        )
        trades.append(trade)
    
    return trades


def demonstrate_regime_detection():
    """Demonstrate market regime detection."""
    print("=== Market Regime Detection Demo ===")
    
    detector = MarketRegimeDetector()
    
    # Test different market conditions
    test_cases = {
        "Upward Trend": [1.0 + i * 0.01 for i in range(50)],
        "Downward Trend": [1.0 - i * 0.008 for i in range(50)],
        "High Volatility": [1.0 + np.random.normal(0, 0.03) for _ in range(50)],
        "Ranging Market": [1.0 + 0.005 * np.sin(i * 0.2) for i in range(50)],
        "Low Volatility": [1.0 + np.random.normal(0, 0.002) for _ in range(50)]
    }
    
    for case_name, prices in test_cases.items():
        regime = detector.detect_regime(prices)
        stats = detector.get_regime_statistics(prices)
        
        print(f"\n{case_name}:")
        print(f"  Detected Regime: {regime.value}")
        print(f"  Volatility: {stats.get('volatility', 0):.4f}")
        print(f"  Trend Strength: {stats.get('trend_strength', 0):.4f}")


def demonstrate_trade_attribution():
    """Demonstrate trade attribution analysis."""
    print("\n=== Trade Attribution Analysis Demo ===")
    
    # Create sample data
    agent = ExampleRLAgent("demo_agent")
    market_data = create_sample_market_data(200)
    trades = create_sample_trades(market_data, agent)
    
    print(f"Created {len(trades)} sample trades")
    
    # Initialize analyzer
    analyzer = TradeAttributionAnalyzer()
    
    # Analyze each trade
    print("\nAnalyzing trades...")
    for i, trade in enumerate(trades[:5]):  # Analyze first 5 trades for demo
        # Create sample state vector (would come from actual RL agent)
        state_vector = np.random.random(50)
        
        # Create sample action probabilities (would come from actual RL agent)
        action_probabilities = np.random.dirichlet([1, 1, 1])  # 3 actions
        
        # Find relevant market data for this trade
        trade_market_data = [
            md for md in market_data 
            if md.timestamp <= trade.entry_time
        ][-100:]  # Last 100 periods before trade
        
        attribution = analyzer.analyze_trade(
            trade=trade,
            agent=agent,
            market_data=trade_market_data,
            state_vector=state_vector,
            action_probabilities=action_probabilities
        )
        
        print(f"\nTrade {i+1} Attribution:")
        print(f"  Trade ID: {attribution.trade_id}")
        print(f"  P&L: ${attribution.pnl:.2f}")
        print(f"  Market Regime: {attribution.market_regime.value}")
        print(f"  Confidence Score: {attribution.confidence_score:.3f}")
        print(f"  Entry Timing Score: {attribution.entry_timing_score:.3f}")
        print(f"  Exit Timing Score: {attribution.exit_timing_score:.3f}")
        
        # Show top factor contributions
        sorted_factors = sorted(
            attribution.factor_contributions.items(),
            key=lambda x: abs(x[1]),
            reverse=True
        )
        print("  Top Factor Contributions:")
        for factor, contribution in sorted_factors[:3]:
            print(f"    {factor.value}: ${contribution:.2f}")


def demonstrate_strategy_decomposition():
    """Demonstrate strategy performance decomposition."""
    print("\n=== Strategy Performance Decomposition Demo ===")
    
    # Create sample data
    agent = ExampleRLAgent("demo_strategy")
    market_data = create_sample_market_data(200)
    trades = create_sample_trades(market_data, agent)
    
    # Initialize analyzer
    analyzer = TradeAttributionAnalyzer()
    
    # Analyze all trades first
    print("Analyzing all trades for decomposition...")
    for trade in trades:
        state_vector = np.random.random(50)
        action_probabilities = np.random.dirichlet([1, 1, 1])
        
        trade_market_data = [
            md for md in market_data 
            if md.timestamp <= trade.entry_time
        ][-100:]
        
        analyzer.analyze_trade(
            trade=trade,
            agent=agent,
            market_data=trade_market_data,
            state_vector=state_vector,
            action_probabilities=action_probabilities
        )
    
    # Perform strategy decomposition
    start_date = min(trade.entry_time for trade in trades)
    end_date = max(trade.entry_time for trade in trades)
    
    decomposition = analyzer.decompose_strategy_performance(
        strategy_id=agent.agent_id,
        trades=trades,
        start_date=start_date,
        end_date=end_date
    )
    
    print(f"\nStrategy Decomposition Results:")
    print(f"  Strategy ID: {decomposition.strategy_id}")
    print(f"  Analysis Period: {decomposition.analysis_period[0].date()} to {decomposition.analysis_period[1].date()}")
    print(f"  Total Return: {decomposition.total_return:.4f}")
    print(f"  Risk-Adjusted Return: {decomposition.risk_adjusted_return:.4f}")
    print(f"  Skill Score: {decomposition.skill_score:.3f}")
    print(f"  Luck Component: {decomposition.luck_component:.3f}")
    print(f"  Statistical Significance: {decomposition.statistical_significance:.3f}")
    
    # Show factor returns
    print("\n  Factor Returns:")
    for factor, return_val in decomposition.factor_returns.items():
        print(f"    {factor.value}: {return_val:.4f}")
    
    # Show regime performance
    print("\n  Regime Performance:")
    for regime, performance in decomposition.regime_performance.items():
        print(f"    {regime.value}:")
        print(f"      Total Return: {performance.total_return:.4f}")
        print(f"      Win Rate: {performance.win_rate:.3f}")
        print(f"      Num Trades: {performance.num_trades}")
    
    # Show regime exposure
    print("\n  Regime Exposure:")
    for regime, exposure in decomposition.regime_exposure.items():
        print(f"    {regime.value}: {exposure:.1%}")


def demonstrate_attribution_summary():
    """Demonstrate attribution summary generation."""
    print("\n=== Attribution Summary Demo ===")
    
    # Create sample data
    agent = ExampleRLAgent("summary_agent")
    market_data = create_sample_market_data(100)
    trades = create_sample_trades(market_data, agent)
    
    # Initialize analyzer
    analyzer = TradeAttributionAnalyzer()
    
    # Analyze trades
    for trade in trades:
        state_vector = np.random.random(50)
        action_probabilities = np.random.dirichlet([1, 1, 1])
        
        trade_market_data = [
            md for md in market_data 
            if md.timestamp <= trade.entry_time
        ][-50:]
        
        analyzer.analyze_trade(
            trade=trade,
            agent=agent,
            market_data=trade_market_data,
            state_vector=state_vector,
            action_probabilities=action_probabilities
        )
    
    # Get attribution summary
    summary = analyzer.get_attribution_summary(agent.agent_id)
    
    print(f"Attribution Summary for {summary['strategy_id']}:")
    print(f"  Total Trades: {summary['total_trades']}")
    print(f"  Total P&L: ${summary['total_pnl']:.2f}")
    print(f"  Average Confidence: {summary['avg_confidence']:.3f}")
    
    print("\n  Factor Contributions:")
    for factor, contribution in summary['factor_contributions'].items():
        print(f"    {factor}: ${contribution:.2f}")
    
    print("\n  Regime Distribution:")
    for regime, percentage in summary['regime_distribution'].items():
        print(f"    {regime}: {percentage:.1%}")
    
    print("\n  Average Timing Scores:")
    print(f"    Entry: {summary['avg_timing_scores']['entry']:.3f}")
    print(f"    Exit: {summary['avg_timing_scores']['exit']:.3f}")


def demonstrate_save_load():
    """Demonstrate saving and loading attribution analysis."""
    print("\n=== Save/Load Attribution Analysis Demo ===")
    
    # Create sample data and analysis
    agent = ExampleRLAgent("save_load_agent")
    market_data = create_sample_market_data(50)
    trades = create_sample_trades(market_data, agent)
    
    analyzer = TradeAttributionAnalyzer()
    
    # Analyze a few trades
    for trade in trades[:3]:
        state_vector = np.random.random(50)
        trade_market_data = market_data[-50:]
        
        analyzer.analyze_trade(
            trade=trade,
            agent=agent,
            market_data=trade_market_data,
            state_vector=state_vector
        )
    
    # Save analysis
    filepath = analyzer.save_attribution_analysis("demo_attribution_analysis.json")
    print(f"Attribution analysis saved to: {filepath}")
    
    # Create new analyzer and load
    new_analyzer = TradeAttributionAnalyzer()
    new_analyzer.load_attribution_analysis(filepath)
    
    print(f"Loaded {len(new_analyzer.trade_attributions)} trade attributions")
    print("Save/load demonstration completed successfully!")


def main():
    """Run all demonstration examples."""
    print("Trade Attribution and Analysis System Demo")
    print("=" * 50)
    
    try:
        demonstrate_regime_detection()
        demonstrate_trade_attribution()
        demonstrate_strategy_decomposition()
        demonstrate_attribution_summary()
        demonstrate_save_load()
        
        print("\n" + "=" * 50)
        print("All demonstrations completed successfully!")
        
    except Exception as e:
        print(f"\nError during demonstration: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
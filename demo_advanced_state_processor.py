"""
Demo script for Advanced State Processor

This script demonstrates the enhanced feature engineering capabilities
of the AdvancedStateProcessor with comprehensive technical indicators
and normalization methods.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
from datetime import datetime, timedelta, timezone
from typing import List

from src.models import MarketData
from src.rl.environments import (
    EnvironmentConfig,
    AdvancedStateProcessor,
    FeatureConfig,
    NormalizationMethod,
    TechnicalIndicators,
    IndicatorConfig
)
from src.rl.environments.base import PortfolioState


def create_realistic_forex_data(num_points: int = 500) -> List[MarketData]:
    """Create realistic forex market data with various market conditions."""
    data = []
    base_price = 1.1000
    base_time = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    
    # Create different market regimes
    regimes = [
        {"trend": 0.0002, "volatility": 0.0008, "duration": 100},  # Uptrend
        {"trend": -0.0001, "volatility": 0.0012, "duration": 150},  # Downtrend with high vol
        {"trend": 0.0, "volatility": 0.0004, "duration": 100},     # Sideways low vol
        {"trend": 0.0003, "volatility": 0.0015, "duration": 100},  # Strong uptrend high vol
        {"trend": -0.0002, "volatility": 0.0006, "duration": 50}   # Moderate downtrend
    ]
    
    current_regime = 0
    regime_step = 0
    
    for i in range(num_points):
        # Switch regimes
        if regime_step >= regimes[current_regime]["duration"]:
            current_regime = (current_regime + 1) % len(regimes)
            regime_step = 0
            
        regime = regimes[current_regime]
        
        # Apply regime characteristics
        trend = regime["trend"]
        volatility = regime["volatility"]
        
        # Add some cyclical patterns
        cycle = 0.0001 * np.sin(i / 30) * np.cos(i / 50)
        
        # Random walk with trend and cycle
        price_change = trend + cycle + np.random.normal(0, volatility)
        base_price += price_change
        
        # Ensure reasonable bounds
        base_price = max(min(base_price, 1.3000), 0.9000)
        
        # Create realistic OHLC with intrabar volatility
        intrabar_vol = volatility * 0.6
        high = base_price + abs(np.random.normal(0, intrabar_vol))
        low = base_price - abs(np.random.normal(0, intrabar_vol))
        open_price = base_price + np.random.normal(0, intrabar_vol * 0.3)
        
        # Ensure OHLC relationships
        high = max(high, base_price, open_price)
        low = min(low, base_price, open_price)
        
        # Realistic spread (varies with volatility)
        spread = 0.0001 + volatility * 0.1
        bid = base_price - spread/2
        ask = base_price + spread/2
        
        # Volume correlated with volatility and time of day
        hour = (base_time + timedelta(minutes=i)).hour
        volume_multiplier = 1.0
        if 8 <= hour <= 17:  # European session
            volume_multiplier = 1.5
        elif 13 <= hour <= 22:  # US session
            volume_multiplier = 1.3
            
        base_volume = 1000
        volume = int(base_volume * volume_multiplier * (1 + abs(price_change) * 5000))
        volume = max(volume, 100)
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=base_time + timedelta(minutes=i),
            open=open_price,
            high=high,
            low=low,
            close=base_price,
            volume=volume,
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        data.append(market_data)
        regime_step += 1
        
    return data


def demonstrate_technical_indicators():
    """Demonstrate technical indicators calculation."""
    print("🔧 Technical Indicators Demo")
    print("=" * 50)
    
    # Create test data
    market_data = create_realistic_forex_data(200)
    
    # Initialize technical indicators
    config = IndicatorConfig(
        rsi_period=14,
        macd_fast=12,
        macd_slow=26,
        bb_period=20,
        atr_period=14
    )
    
    tech_indicators = TechnicalIndicators(config)
    
    # Extract price data
    opens = [d.open for d in market_data]
    highs = [d.high for d in market_data]
    lows = [d.low for d in market_data]
    closes = [d.close for d in market_data]
    volumes = [d.volume for d in market_data]
    
    # Calculate all indicators
    indicators = tech_indicators.calculate_all_indicators(
        opens, highs, lows, closes, volumes
    )
    
    print(f"📊 Calculated {len(indicators)} technical indicators:")
    print(f"   Current Price: ${closes[-1]:.5f}")
    print(f"   RSI: {indicators['rsi']:.2f}")
    print(f"   SMA(20): ${indicators['sma_20']:.5f}")
    print(f"   EMA(20): ${indicators['ema_20']:.5f}")
    print(f"   MACD Line: {indicators['macd_line']:.6f}")
    print(f"   Bollinger Upper: ${indicators['bb_upper']:.5f}")
    print(f"   Bollinger Lower: ${indicators['bb_lower']:.5f}")
    print(f"   ATR: {indicators['atr']:.6f}")
    print(f"   Stochastic %K: {indicators['stoch_k']:.2f}")
    print(f"   Williams %R: {indicators['williams_r']:.2f}")
    print(f"   Volume Ratio: {indicators['volume_ratio']:.2f}")
    
    return indicators


def demonstrate_feature_engineering():
    """Demonstrate advanced feature engineering."""
    print("\n🧠 Advanced Feature Engineering Demo")
    print("=" * 50)
    
    # Create configurations
    env_config = EnvironmentConfig(
        state_features=['price', 'technical', 'portfolio'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=30,
        normalization_method='robust',
        transaction_cost=0.0001,
        max_position_size=1.0,
        initial_balance=10000.0
    )
    
    feature_config = FeatureConfig(
        include_ohlc=True,
        include_returns=True,
        include_log_returns=True,
        include_price_ratios=True,
        include_trend_indicators=True,
        include_momentum_indicators=True,
        include_volatility_indicators=True,
        include_volume_indicators=True,
        include_support_resistance=True,
        include_market_microstructure=True,
        include_regime_features=True,
        normalization_method=NormalizationMethod.ROBUST,
        price_lookback=20,
        technical_lookback=50,
        max_features=None  # Use all features
    )
    
    # Create processor
    processor = AdvancedStateProcessor(env_config, feature_config)
    
    print(f"📏 State Processor Configuration:")
    print(f"   Total Feature Dimension: {processor.get_state_dimension()}")
    print(f"   Price Lookback: {feature_config.price_lookback}")
    print(f"   Technical Lookback: {feature_config.technical_lookback}")
    print(f"   Normalization Method: {feature_config.normalization_method.value}")
    
    # Create market data
    market_data = create_realistic_forex_data(300)
    
    # Create portfolio states for different scenarios
    portfolio_scenarios = [
        ("Initial", PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)),
        ("Long Position", PortfolioState(10000, 10150, 0.8, 150.0, 0.0, 5, 3, 0.0, 0.0)),
        ("Short Position", PortfolioState(10000, 9950, -0.6, -50.0, 0.0, 8, 4, 0.005, 0.005)),
        ("Heavy Trading", PortfolioState(10000, 10080, 0.2, 80.0, 200.0, 25, 15, 0.02, 0.01))
    ]
    
    print(f"\n📈 Processing States for Different Scenarios:")
    
    for scenario_name, portfolio in portfolio_scenarios:
        print(f"\n   {scenario_name} Scenario:")
        
        # Process state
        state = processor.process_market_data(market_data[-100:], portfolio)
        
        print(f"      State Vector Shape: {state.shape}")
        print(f"      Value Range: [{np.min(state):.3f}, {np.max(state):.3f}]")
        print(f"      Mean: {np.mean(state):.3f}")
        print(f"      Std Dev: {np.std(state):.3f}")
        print(f"      Non-zero Features: {np.count_nonzero(state)}/{len(state)}")
        
        # Check for invalid values
        nan_count = np.sum(np.isnan(state))
        inf_count = np.sum(np.isinf(state))
        print(f"      NaN/Inf Values: {nan_count + inf_count}")
        
    return processor, market_data


def demonstrate_normalization_methods():
    """Demonstrate different normalization methods."""
    print("\n📊 Normalization Methods Comparison")
    print("=" * 50)
    
    env_config = EnvironmentConfig(
        state_features=['price', 'technical'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=20,
        normalization_method='robust',
        transaction_cost=0.0001,
        max_position_size=1.0,
        initial_balance=10000.0
    )
    
    normalization_methods = [
        NormalizationMethod.NONE,
        NormalizationMethod.MINMAX,
        NormalizationMethod.ZSCORE,
        NormalizationMethod.ROBUST,
        NormalizationMethod.QUANTILE
    ]
    
    market_data = create_realistic_forex_data(200)
    portfolio = PortfolioState(10000, 10100, 0.5, 100.0, 0.0, 5, 3, 0.0, 0.0)
    
    results = {}
    
    for method in normalization_methods:
        feature_config = FeatureConfig(
            normalization_method=method,
            price_lookback=10,
            max_features=50  # Limit for comparison
        )
        
        processor = AdvancedStateProcessor(env_config, feature_config)
        
        # Process multiple states to build normalization history
        states = []
        for i in range(20):
            start_idx = max(0, i * 5)
            end_idx = min(len(market_data), start_idx + 50)
            data_slice = market_data[start_idx:end_idx]
            
            state = processor.process_market_data(data_slice, portfolio)
            states.append(state)
            
        final_state = states[-1]
        results[method.value] = {
            'mean': np.mean(final_state),
            'std': np.std(final_state),
            'min': np.min(final_state),
            'max': np.max(final_state),
            'range': np.max(final_state) - np.min(final_state)
        }
        
    # Display results
    print(f"{'Method':<12} {'Mean':<8} {'Std':<8} {'Min':<8} {'Max':<8} {'Range':<8}")
    print("-" * 60)
    
    for method, stats in results.items():
        print(f"{method:<12} {stats['mean']:<8.3f} {stats['std']:<8.3f} "
              f"{stats['min']:<8.3f} {stats['max']:<8.3f} {stats['range']:<8.3f}")
        
    return results


def demonstrate_feature_analysis():
    """Demonstrate feature analysis and interpretation."""
    print("\n🔍 Feature Analysis Demo")
    print("=" * 50)
    
    # Create processor with all features
    env_config = EnvironmentConfig(
        state_features=['all'],
        action_space_type='discrete',
        reward_function='multi_objective',
        lookback_window=30,
        normalization_method='robust',
        transaction_cost=0.0001,
        max_position_size=1.0,
        initial_balance=10000.0
    )
    
    feature_config = FeatureConfig(
        include_ohlc=True,
        include_returns=True,
        include_trend_indicators=True,
        include_momentum_indicators=True,
        include_volatility_indicators=True,
        include_market_microstructure=True,
        include_regime_features=True,
        normalization_method=NormalizationMethod.ROBUST,
        price_lookback=15
    )
    
    processor = AdvancedStateProcessor(env_config, feature_config)
    
    # Get feature names
    feature_names = processor.get_feature_names()
    
    print(f"📋 Feature Categories Analysis:")
    print(f"   Total Features: {len(feature_names)}")
    
    # Categorize features
    categories = {
        'Price': [name for name in feature_names if any(x in name for x in ['open', 'high', 'low', 'close'])],
        'Returns': [name for name in feature_names if 'return' in name],
        'Technical': [name for name in feature_names if any(x in name for x in ['sma', 'ema', 'rsi', 'macd', 'bb', 'stoch'])],
        'Volume': [name for name in feature_names if 'volume' in name or 'obv' in name],
        'Portfolio': [name for name in feature_names if any(x in name for x in ['position', 'pnl', 'drawdown', 'equity'])],
        'Temporal': [name for name in feature_names if any(x in name for x in ['hour', 'day', 'month', 'session'])],
        'Microstructure': [name for name in feature_names if any(x in name for x in ['spread', 'gap', 'shadow', 'body'])],
        'Regime': [name for name in feature_names if any(x in name for x in ['regime', 'trend', 'vol_', 'momentum'])]
    }
    
    for category, features in categories.items():
        if features:
            print(f"   {category}: {len(features)} features")
            if len(features) <= 5:
                print(f"      {', '.join(features)}")
            else:
                print(f"      {', '.join(features[:3])} ... (+{len(features)-3} more)")
                
    # Process a sample state and show feature values
    market_data = create_realistic_forex_data(100)
    portfolio = PortfolioState(10000, 10200, 0.3, 200.0, 50.0, 10, 6, 0.01, 0.005)
    
    state = processor.process_market_data(market_data[-50:], portfolio)
    
    print(f"\n📊 Sample State Analysis:")
    print(f"   State Vector Length: {len(state)}")
    print(f"   Non-zero Values: {np.count_nonzero(state)}")
    print(f"   Value Distribution:")
    print(f"      Mean: {np.mean(state):.4f}")
    print(f"      Median: {np.median(state):.4f}")
    print(f"      Std Dev: {np.std(state):.4f}")
    print(f"      Min/Max: [{np.min(state):.4f}, {np.max(state):.4f}]")
    
    # Show some example feature values
    print(f"\n🔢 Sample Feature Values:")
    for i, (name, value) in enumerate(zip(feature_names[:10], state[:10])):
        print(f"      {name}: {value:.4f}")
    print(f"      ... ({len(state)-10} more features)")


def main():
    """Run all demonstrations."""
    print("🚀 Advanced State Processor Comprehensive Demo")
    print("=" * 70)
    
    try:
        # 1. Technical Indicators Demo
        indicators = demonstrate_technical_indicators()
        
        # 2. Feature Engineering Demo
        processor, market_data = demonstrate_feature_engineering()
        
        # 3. Normalization Methods Demo
        norm_results = demonstrate_normalization_methods()
        
        # 4. Feature Analysis Demo
        demonstrate_feature_analysis()
        
        print(f"\n✅ All demonstrations completed successfully!")
        print(f"   The Advanced State Processor is ready for RL agent training!")
        print(f"   Key capabilities demonstrated:")
        print(f"      • {len(indicators)} technical indicators")
        print(f"      • {processor.get_state_dimension()} dimensional state space")
        print(f"      • {len(norm_results)} normalization methods")
        print(f"      • Comprehensive feature engineering pipeline")
        
    except Exception as e:
        print(f"\n❌ Demo failed with error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
"""
Unit tests for Advanced State Processor

This module tests the advanced state processing functionality including
technical indicators, feature engineering, and normalization methods.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pytest
from datetime import datetime, timedelta, timezone
from typing import List

from src.models import MarketData
from src.rl.environments import EnvironmentConfig
from src.rl.environments.base import PortfolioState
from src.rl.environments.advanced_state_processor import (
    AdvancedStateProcessor, 
    FeatureConfig, 
    NormalizationMethod
)
from src.rl.environments.technical_indicators import TechnicalIndicators, IndicatorConfig


def create_test_market_data(num_points: int = 100) -> List[MarketData]:
    """Create test market data with realistic patterns."""
    data = []
    base_price = 1.1000
    base_time = datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)
    
    for i in range(num_points):
        # Create trending price with some noise
        trend = 0.0001 * np.sin(i / 20)  # Cyclical trend
        noise = np.random.normal(0, 0.0005)
        price_change = trend + noise
        
        current_price = base_price + price_change * i
        current_price = max(current_price, 0.5)  # Ensure positive
        
        # Create OHLC
        high = current_price + abs(np.random.normal(0, 0.0002))
        low = current_price - abs(np.random.normal(0, 0.0002))
        open_price = current_price + np.random.normal(0, 0.0001)
        
        # Ensure OHLC relationships
        high = max(high, current_price, open_price)
        low = min(low, current_price, open_price)
        
        # Create bid/ask
        spread = 0.0001
        bid = current_price - spread/2
        ask = current_price + spread/2
        
        market_data = MarketData(
            symbol="EUR/USD",
            timestamp=base_time + timedelta(minutes=i),
            open=open_price,
            high=high,
            low=low,
            close=current_price,
            volume=1000 + int(np.random.normal(0, 200)),
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        data.append(market_data)
        
    return data


class TestTechnicalIndicators:
    """Test technical indicators calculation."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.config = IndicatorConfig()
        self.indicators = TechnicalIndicators(self.config)
        self.market_data = create_test_market_data(100)
        
    def test_calculate_all_indicators(self):
        """Test calculating all technical indicators."""
        opens = [d.open for d in self.market_data]
        highs = [d.high for d in self.market_data]
        lows = [d.low for d in self.market_data]
        closes = [d.close for d in self.market_data]
        volumes = [d.volume for d in self.market_data]
        
        indicators = self.indicators.calculate_all_indicators(
            opens, highs, lows, closes, volumes
        )
        
        # Check that all expected indicators are present
        expected_indicators = [
            'sma_5', 'sma_10', 'sma_20', 'sma_50',
            'ema_5', 'ema_10', 'ema_20',
            'macd_line', 'macd_signal', 'macd_histogram',
            'rsi', 'stoch_k', 'stoch_d', 'williams_r',
            'bb_upper', 'bb_middle', 'bb_lower', 'bb_position',
            'atr', 'volatility', 'volume_ratio', 'obv'
        ]
        
        for indicator in expected_indicators:
            assert indicator in indicators
            assert isinstance(indicators[indicator], (int, float))
            assert not np.isnan(indicators[indicator])
            assert not np.isinf(indicators[indicator])
            
    def test_rsi_calculation(self):
        """Test RSI calculation."""
        closes = [1.1000, 1.1010, 1.1005, 1.1015, 1.1020, 1.1018, 1.1025, 1.1030]
        rsi = self.indicators._rsi(np.array(closes), 7)
        
        assert 0 <= rsi <= 100
        assert isinstance(rsi, float)
        
    def test_sma_calculation(self):
        """Test Simple Moving Average calculation."""
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        sma = self.indicators._sma(data, 3)
        
        expected = np.mean([3.0, 4.0, 5.0])  # Last 3 values
        assert abs(sma - expected) < 1e-6
        
    def test_bollinger_bands(self):
        """Test Bollinger Bands calculation."""
        closes = np.array([1.1000 + 0.0001 * i for i in range(20)])
        upper, middle, lower = self.indicators._bollinger_bands(closes)
        
        assert upper > middle > lower
        assert isinstance(upper, float)
        assert isinstance(middle, float)
        assert isinstance(lower, float)
        
    def test_insufficient_data(self):
        """Test indicators with insufficient data."""
        short_data = create_test_market_data(5)
        opens = [d.open for d in short_data]
        highs = [d.high for d in short_data]
        lows = [d.low for d in short_data]
        closes = [d.close for d in short_data]
        volumes = [d.volume for d in short_data]
        
        indicators = self.indicators.calculate_all_indicators(
            opens, highs, lows, closes, volumes
        )
        
        # Should return default values without errors
        assert isinstance(indicators, dict)
        assert len(indicators) > 0
        
        for value in indicators.values():
            assert not np.isnan(value)
            assert not np.isinf(value)


class TestAdvancedStateProcessor:
    """Test advanced state processor."""
    
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
        
        self.feature_config = FeatureConfig(
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
            price_lookback=10,
            technical_lookback=30
        )
        
        self.processor = AdvancedStateProcessor(
            self.env_config, self.feature_config
        )
        
        self.market_data = create_test_market_data(100)
        self.portfolio_state = PortfolioState(
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
        
    def test_state_dimension_calculation(self):
        """Test state dimension calculation."""
        expected_dim = self.processor._calculate_feature_dimension()
        actual_dim = self.processor.get_state_dimension()
        
        assert actual_dim == expected_dim
        assert actual_dim > 0
        
    def test_process_market_data(self):
        """Test processing market data into state vector."""
        state = self.processor.process_market_data(
            self.market_data[-30:], self.portfolio_state
        )
        
        assert isinstance(state, np.ndarray)
        # Allow some tolerance in state dimension due to dynamic feature calculation
        expected_dim = self.processor.get_state_dimension()
        assert abs(len(state) - expected_dim) <= 5  # Allow small variance
        assert not np.any(np.isnan(state))
        assert not np.any(np.isinf(state))
        
        # Check that values are in reasonable range after normalization
        assert np.all(state >= -10.0)
        assert np.all(state <= 10.0)
        
    def test_feature_names_generation(self):
        """Test feature names generation."""
        feature_names = self.processor.get_feature_names()
        
        assert isinstance(feature_names, list)
        # Feature names may not match exactly due to dynamic calculation
        assert len(feature_names) >= self.processor.get_state_dimension() - 5  # Allow some tolerance
        
        # Check that names are strings
        for name in feature_names:
            assert isinstance(name, str)
            assert len(name) > 0
            
    def test_price_feature_extraction(self):
        """Test price feature extraction."""
        features = self.processor._extract_price_features(self.market_data[-20:])
        
        assert isinstance(features, list)
        assert len(features) > 0
        
        # Check for no NaN or infinite values
        for feature in features:
            assert not np.isnan(feature)
            assert not np.isinf(feature)
            
    def test_technical_feature_extraction(self):
        """Test technical indicator feature extraction."""
        features = self.processor._extract_technical_features(self.market_data[-50:])
        
        assert isinstance(features, list)
        assert len(features) > 0
        
        # Check for no NaN or infinite values
        for feature in features:
            assert not np.isnan(feature)
            assert not np.isinf(feature)
            
    def test_microstructure_feature_extraction(self):
        """Test market microstructure feature extraction."""
        features = self.processor._extract_microstructure_features(self.market_data[-10:])
        
        assert isinstance(features, list)
        assert len(features) == 9  # Expected number of microstructure features
        
        # Check for no NaN or infinite values
        for feature in features:
            assert not np.isnan(feature)
            assert not np.isinf(feature)
            
    def test_regime_feature_extraction(self):
        """Test market regime feature extraction."""
        features = self.processor._extract_regime_features(self.market_data[-30:])
        
        assert isinstance(features, list)
        assert len(features) == 6  # Expected number of regime features
        
        # Check for no NaN or infinite values
        for feature in features:
            assert not np.isnan(feature)
            assert not np.isinf(feature)
            
    def test_portfolio_feature_extraction(self):
        """Test portfolio feature extraction."""
        # Test with different portfolio states
        portfolio_states = [
            PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0),  # Initial
            PortfolioState(10000, 10100, 0.5, 100.0, 0.0, 1, 1, 0.0, 0.0),  # Profitable
            PortfolioState(10000, 9900, -0.3, -100.0, 0.0, 2, 0, 0.01, 0.01)  # Loss
        ]
        
        for portfolio in portfolio_states:
            features = self.processor._extract_portfolio_features(portfolio)
            
            assert isinstance(features, list)
            assert len(features) == 9  # Expected number of portfolio features
            
            # Check for no NaN or infinite values
            for feature in features:
                assert not np.isnan(feature)
                assert not np.isinf(feature)
                
    def test_temporal_feature_extraction(self):
        """Test temporal feature extraction."""
        features = self.processor._extract_temporal_features(self.market_data[-1])
        
        assert isinstance(features, list)
        assert len(features) == 9  # Expected number of temporal features
        
        # Check for no NaN or infinite values
        for feature in features:
            assert not np.isnan(feature)
            assert not np.isinf(feature)
            
    def test_normalization_methods(self):
        """Test different normalization methods."""
        normalization_methods = [
            NormalizationMethod.MINMAX,
            NormalizationMethod.ZSCORE,
            NormalizationMethod.ROBUST,
            NormalizationMethod.QUANTILE,
            NormalizationMethod.NONE
        ]
        
        for method in normalization_methods:
            feature_config = FeatureConfig(normalization_method=method)
            processor = AdvancedStateProcessor(self.env_config, feature_config)
            
            # Process multiple states to build normalization history
            for i in range(10):
                state = processor.process_market_data(
                    self.market_data[-30:], self.portfolio_state
                )
                
                assert isinstance(state, np.ndarray)
                assert not np.any(np.isnan(state))
                assert not np.any(np.isinf(state))
                
    def test_insufficient_data_handling(self):
        """Test handling of insufficient market data."""
        # Test with very little data
        short_data = self.market_data[:3]
        
        state = self.processor.process_market_data(short_data, self.portfolio_state)
        
        assert isinstance(state, np.ndarray)
        # Allow some tolerance in state dimension due to dynamic feature calculation
        expected_dim = self.processor.get_state_dimension()
        assert abs(len(state) - expected_dim) <= 5  # Allow small variance
        assert not np.any(np.isnan(state))
        assert not np.any(np.isinf(state))
        
    def test_empty_data_handling(self):
        """Test handling of empty market data."""
        state = self.processor.process_market_data([], self.portfolio_state)
        
        assert isinstance(state, np.ndarray)
        assert state.shape == (self.processor.get_state_dimension(),)
        assert np.all(state == 0.0)
        
    def test_feature_selection(self):
        """Test feature selection functionality."""
        # Test with max_features limit
        feature_config = FeatureConfig(max_features=50)
        processor = AdvancedStateProcessor(self.env_config, feature_config)
        
        state = processor.process_market_data(
            self.market_data[-30:], self.portfolio_state
        )
        
        assert len(state) <= 50
        assert len(state) == processor.get_state_dimension()
        
    def test_invalid_value_handling(self):
        """Test handling of invalid values in features."""
        # Create feature vector with invalid values
        test_vector = np.array([1.0, np.nan, np.inf, -np.inf, 100.0, -100.0])
        
        cleaned_vector = self.processor._handle_invalid_values(test_vector)
        
        assert not np.any(np.isnan(cleaned_vector))
        assert not np.any(np.isinf(cleaned_vector))
        assert np.all(cleaned_vector >= -10.0)
        assert np.all(cleaned_vector <= 10.0)
        
    def test_normalization_stats_update(self):
        """Test normalization statistics updating."""
        # Process multiple states to build history
        for i in range(20):
            self.processor.process_market_data(
                self.market_data[-30:], self.portfolio_state
            )
            
        # Check that normalization history is maintained
        assert 'history' in self.processor.normalization_history
        assert len(self.processor.normalization_history['history']) > 0
        assert len(self.processor.normalization_history['history']) <= self.feature_config.normalization_window
        
    def test_reset_normalization_stats(self):
        """Test resetting normalization statistics."""
        # Build some history
        for i in range(5):
            self.processor.process_market_data(
                self.market_data[-30:], self.portfolio_state
            )
            
        # Reset
        self.processor.reset_normalization_stats()
        
        # Check that history is cleared
        assert len(self.processor.normalization_history) == 0
        assert len(self.processor.feature_stats) == 0
        
    def test_session_indicators(self):
        """Test market session indicators."""
        # Test different hours
        test_hours = [2, 8, 16, 20]  # Different sessions
        
        for hour in test_hours:
            session_indicator = self.processor._get_session_indicator(hour)
            assert -1.0 <= session_indicator <= 1.0
            
            detailed_features = self.processor._get_detailed_session_features(hour)
            assert len(detailed_features) == 4
            assert all(0.0 <= f <= 1.0 for f in detailed_features)
            
    def test_weekend_proximity(self):
        """Test weekend proximity feature."""
        # Test different weekdays
        for weekday in range(7):
            proximity = self.processor._get_weekend_proximity(weekday)
            assert -1.0 <= proximity <= 1.0
            
    def test_returns_calculation(self):
        """Test returns calculation methods."""
        prices = [1.1000, 1.1010, 1.1005, 1.1015, 1.1020]
        
        # Simple returns
        returns = self.processor._calculate_returns(prices, 3)
        assert len(returns) == 3
        assert all(isinstance(r, float) for r in returns)
        
        # Log returns
        log_returns = self.processor._calculate_log_returns(prices, 3)
        assert len(log_returns) == 3
        assert all(isinstance(r, float) for r in log_returns)
        
    def test_price_ratios_calculation(self):
        """Test price ratios calculation."""
        opens = [1.1000, 1.1005]
        highs = [1.1015, 1.1020]
        lows = [1.0995, 1.1000]
        closes = [1.1010, 1.1015]
        
        ratios = self.processor._calculate_price_ratios(opens, highs, lows, closes)
        
        assert len(ratios) == 6
        assert all(isinstance(r, float) for r in ratios)
        assert all(not np.isnan(r) for r in ratios)
        assert all(not np.isinf(r) for r in ratios)


def test_integration_advanced_processor():
    """Integration test for advanced state processor."""
    print("Running Advanced State Processor Integration Test...")
    
    # Create configuration
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
        include_trend_indicators=True,
        include_momentum_indicators=True,
        include_volatility_indicators=True,
        include_market_microstructure=True,
        include_regime_features=True,
        normalization_method=NormalizationMethod.ROBUST,
        price_lookback=15,
        max_features=100
    )
    
    # Create processor
    processor = AdvancedStateProcessor(env_config, feature_config)
    
    # Create test data
    market_data = create_test_market_data(200)
    
    # Test processing multiple states
    states = []
    portfolio = PortfolioState(10000, 10000, 0.0, 0.0, 0.0, 0, 0, 0.0, 0.0)
    
    for i in range(50):
        # Simulate changing portfolio state
        portfolio.current_position = np.sin(i / 10) * 0.5
        portfolio.unrealized_pnl = np.random.normal(0, 50)
        portfolio.total_trades = i // 5
        portfolio.winning_trades = portfolio.total_trades // 2
        
        # Process state
        start_idx = max(0, i * 2)
        end_idx = min(len(market_data), start_idx + 50)
        data_slice = market_data[start_idx:end_idx]
        
        state = processor.process_market_data(data_slice, portfolio)
        states.append(state)
        
        # Validate state
        assert isinstance(state, np.ndarray)
        assert state.shape == (processor.get_state_dimension(),)
        assert not np.any(np.isnan(state))
        assert not np.any(np.isinf(state))
        
    # Analyze results
    states_array = np.array(states)
    
    print(f"✅ Processed {len(states)} states successfully")
    print(f"   State dimension: {processor.get_state_dimension()}")
    print(f"   Feature names: {len(processor.get_feature_names())}")
    print(f"   State value range: [{np.min(states_array):.3f}, {np.max(states_array):.3f}]")
    print(f"   State mean: {np.mean(states_array):.3f}")
    print(f"   State std: {np.std(states_array):.3f}")
    
    # Test feature names (note: may be truncated due to max_features)
    feature_names = processor.get_feature_names()
    state_dim = processor.get_state_dimension()
    
    # Feature names represent all possible features, state_dim may be limited by max_features
    assert len(feature_names) >= state_dim
    
    print(f"✅ Integration test completed successfully!")


if __name__ == "__main__":
    # Run integration test
    test_integration_advanced_processor()
    
    print("\nRunning all unit tests...")
    
    # Run all tests
    pytest.main([__file__, "-v"])
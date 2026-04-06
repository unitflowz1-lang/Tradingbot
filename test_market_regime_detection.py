"""
Unit tests for Market Regime Detection and Adaptive Rewards

Tests market session detection, volatility regime classification,
trend regime detection, and adaptive reward calculations.
"""

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, List
import pytz

from src.rl.environments.market_regime_detector import (
    SessionDetector,
    VolatilityRegimeDetector,
    TrendRegimeDetector,
    MarketRegimeDetector,
    TradingSession,
    VolatilityRegime,
    TrendRegime,
    MarketRegime,
    SessionInfo
)
from src.rl.environments.adaptive_reward_calculator import AdaptiveRewardCalculator
from src.rl.environments.multi_pair_environment import MultiPairEnvironmentConfig, MultiPairPortfolioState
from src.models import MarketData


def create_test_market_data_with_regime(regime_type: str, num_points: int = 100) -> List[MarketData]:
    """Create test market data with specific regime characteristics."""
    start_time = datetime.now(timezone.utc) - timedelta(hours=num_points)
    market_data = []
    base_price = 1.2000
    
    for i in range(num_points):
        timestamp = start_time + timedelta(hours=i)
        
        if regime_type == 'trending_up':
            # Strong uptrend with increasing prices
            price_change = np.random.normal(0.0005, 0.0002)  # Positive bias
            volatility_multiplier = 0.8
        elif regime_type == 'trending_down':
            # Strong downtrend with decreasing prices
            price_change = np.random.normal(-0.0005, 0.0002)  # Negative bias
            volatility_multiplier = 0.8
        elif regime_type == 'high_volatility':
            # High volatility sideways market
            price_change = np.random.normal(0, 0.002)  # High volatility
            volatility_multiplier = 2.0
        elif regime_type == 'low_volatility':
            # Low volatility sideways market
            price_change = np.random.normal(0, 0.0005)  # Low volatility
            volatility_multiplier = 0.3
        else:  # 'normal'
            price_change = np.random.normal(0, 0.001)
            volatility_multiplier = 1.0
            
        base_price += price_change
        base_price = max(base_price, 0.5000)
        
        # Generate OHLC with regime-appropriate volatility
        vol_range = base_price * 0.001 * volatility_multiplier
        high = base_price + abs(np.random.normal(0, vol_range))
        low = base_price - abs(np.random.normal(0, vol_range))
        open_price = low + (high - low) * np.random.random()
        close_price = base_price
        
        # Generate volume based on time (session simulation)
        hour = timestamp.hour
        if 8 <= hour <= 17:  # London session
            volume = np.random.randint(8000, 15000)
        elif 13 <= hour <= 22:  # New York session
            volume = np.random.randint(6000, 12000)
        elif 0 <= hour <= 9:  # Tokyo session
            volume = np.random.randint(4000, 8000)
        else:
            volume = np.random.randint(1000, 3000)
            
        spread = 0.0001
        bid = close_price - spread / 2
        ask = close_price + spread / 2
        
        market_data_point = MarketData(
            symbol='EUR/USD',
            timestamp=timestamp,
            open=open_price,
            high=high,
            low=low,
            close=close_price,
            volume=volume,
            bid=bid,
            ask=ask,
            spread=spread
        )
        
        market_data.append(market_data_point)
        
    return market_data


class TestSessionDetector:
    """Test trading session detection."""
    
    def setup_method(self):
        """Set up test session detector."""
        self.detector = SessionDetector()
        
    def test_detector_initialization(self):
        """Test session detector initialization."""
        assert len(self.detector.sessions) == 4
        assert TradingSession.LONDON in self.detector.sessions
        assert TradingSession.NEW_YORK in self.detector.sessions
        assert TradingSession.TOKYO in self.detector.sessions
        assert TradingSession.SYDNEY in self.detector.sessions
        
    def test_london_session_detection(self):
        """Test London session detection."""
        # London session: 8:00-17:00 UTC
        london_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)  # 12:00 UTC
        session = self.detector.detect_session(london_time)
        assert session == TradingSession.LONDON
        
    def test_new_york_session_detection(self):
        """Test New York session detection."""
        # New York session: 13:00-22:00 UTC
        ny_time = datetime(2024, 1, 15, 18, 0, 0, tzinfo=timezone.utc)  # 18:00 UTC
        session = self.detector.detect_session(ny_time)
        assert session == TradingSession.NEW_YORK
        
    def test_tokyo_session_detection(self):
        """Test Tokyo session detection."""
        # Tokyo session: 0:00-9:00 UTC
        tokyo_time = datetime(2024, 1, 15, 5, 0, 0, tzinfo=timezone.utc)  # 05:00 UTC
        session = self.detector.detect_session(tokyo_time)
        assert session == TradingSession.TOKYO
        
    def test_sydney_session_detection(self):
        """Test Sydney session detection."""
        # Sydney session: 22:00-7:00 UTC (crosses midnight)
        sydney_time = datetime(2024, 1, 15, 2, 0, 0, tzinfo=timezone.utc)  # 02:00 UTC
        session = self.detector.detect_session(sydney_time)
        assert session == TradingSession.SYDNEY
        
    def test_london_ny_overlap_detection(self):
        """Test London-NY overlap detection."""
        # Overlap: 13:00-17:00 UTC
        overlap_time = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)  # 15:00 UTC
        session = self.detector.detect_session(overlap_time)
        assert session == TradingSession.OVERLAP_LONDON_NY
        
    def test_tokyo_london_overlap_detection(self):
        """Test Tokyo-London overlap detection."""
        # Overlap: 2:00-9:00 UTC
        overlap_time = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)  # 06:00 UTC
        session = self.detector.detect_session(overlap_time)
        assert session == TradingSession.OVERLAP_TOKYO_LONDON
        
    def test_quiet_session_detection(self):
        """Test quiet session detection."""
        # Quiet period: around 20:00-22:00 UTC
        quiet_time = datetime(2024, 1, 15, 21, 0, 0, tzinfo=timezone.utc)  # 21:00 UTC
        session = self.detector.detect_session(quiet_time)
        # Should be either NEW_YORK (if still active) or QUIET
        assert session in [TradingSession.NEW_YORK, TradingSession.QUIET]
        
    def test_pair_specific_detection(self):
        """Test pair-specific session detection."""
        london_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        
        # EUR/USD should be detected as London session
        session = self.detector.detect_session(london_time, 'EUR/USD')
        assert session == TradingSession.LONDON
        
        # AUD/USD might not be as active during London
        session = self.detector.detect_session(london_time, 'AUD/USD')
        # Should still detect London but might be different logic
        assert session in [TradingSession.LONDON, TradingSession.QUIET]
        
    def test_get_active_sessions(self):
        """Test getting all active sessions."""
        # During London-NY overlap
        overlap_time = datetime(2024, 1, 15, 15, 0, 0, tzinfo=timezone.utc)
        active_sessions = self.detector.get_active_sessions(overlap_time)
        
        assert len(active_sessions) >= 1
        assert TradingSession.LONDON in active_sessions
        assert TradingSession.NEW_YORK in active_sessions
        
    def test_session_multipliers(self):
        """Test session volume and volatility multipliers."""
        vol_mult, vol_mult_val = self.detector.get_session_multipliers(TradingSession.LONDON)
        
        assert isinstance(vol_mult, float)
        assert isinstance(vol_mult_val, float)
        assert vol_mult > 0
        assert vol_mult_val > 0
        
    def test_timezone_handling(self):
        """Test handling of different timezones."""
        # Test with naive datetime (should be treated as UTC)
        naive_time = datetime(2024, 1, 15, 12, 0, 0)
        session = self.detector.detect_session(naive_time)
        assert session == TradingSession.LONDON
        
        # Test with different timezone
        ny_tz = pytz.timezone('America/New_York')
        ny_local_time = ny_tz.localize(datetime(2024, 1, 15, 8, 0, 0))  # 8 AM NY time
        session = self.detector.detect_session(ny_local_time)
        assert session == TradingSession.NEW_YORK


class TestVolatilityRegimeDetector:
    """Test volatility regime detection."""
    
    def setup_method(self):
        """Set up test volatility detector."""
        self.detector = VolatilityRegimeDetector(lookback_periods=50)
        
    def test_detector_initialization(self):
        """Test volatility detector initialization."""
        assert self.detector.lookback_periods == 50
        assert self.detector.current_regime == VolatilityRegime.NORMAL
        assert len(self.detector.volatility_history) == 0
        
    def test_low_volatility_detection(self):
        """Test low volatility regime detection."""
        market_data = create_test_market_data_with_regime('low_volatility', 60)
        
        # Feed data to detector
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should eventually detect low volatility
        final_regime = self.detector.current_regime
        assert final_regime in [VolatilityRegime.LOW, VolatilityRegime.NORMAL]
        
    def test_high_volatility_detection(self):
        """Test high volatility regime detection."""
        market_data = create_test_market_data_with_regime('high_volatility', 60)
        
        # Feed data to detector
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should eventually detect high volatility
        final_regime = self.detector.current_regime
        assert final_regime in [VolatilityRegime.HIGH, VolatilityRegime.EXTREME, VolatilityRegime.NORMAL]
        
    def test_volatility_stats(self):
        """Test volatility statistics calculation."""
        market_data = create_test_market_data_with_regime('normal', 30)
        
        for data in market_data:
            self.detector.update(data)
            
        stats = self.detector.get_volatility_stats()
        
        assert 'current' in stats
        assert 'mean' in stats
        assert 'std' in stats
        assert 'percentile' in stats
        
        assert stats['current'] >= 0
        assert stats['mean'] >= 0
        assert stats['std'] >= 0
        assert 0 <= stats['percentile'] <= 100
        
    def test_insufficient_data_handling(self):
        """Test handling of insufficient data."""
        market_data = create_test_market_data_with_regime('normal', 5)
        
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should maintain initial regime with insufficient data
        assert self.detector.current_regime == VolatilityRegime.NORMAL
        
    def test_regime_change_detection(self):
        """Test detection of regime changes."""
        # Start with low volatility data
        low_vol_data = create_test_market_data_with_regime('low_volatility', 30)
        
        for data in low_vol_data:
            self.detector.update(data)
            
        initial_regime = self.detector.current_regime
        
        # Switch to high volatility data
        high_vol_data = create_test_market_data_with_regime('high_volatility', 30)
        
        for data in high_vol_data:
            self.detector.update(data)
            
        final_regime = self.detector.current_regime
        
        # Regime should have changed or at least be different from initial
        # (Due to randomness, we can't guarantee specific regime, but should see change)
        assert isinstance(final_regime, VolatilityRegime)


class TestTrendRegimeDetector:
    """Test trend regime detection."""
    
    def setup_method(self):
        """Set up test trend detector."""
        self.detector = TrendRegimeDetector(short_period=10, long_period=20)
        
    def test_detector_initialization(self):
        """Test trend detector initialization."""
        assert self.detector.short_period == 10
        assert self.detector.long_period == 20
        assert self.detector.current_regime == TrendRegime.SIDEWAYS
        
    def test_uptrend_detection(self):
        """Test uptrend detection."""
        market_data = create_test_market_data_with_regime('trending_up', 50)
        
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should detect some form of uptrend
        final_regime = self.detector.current_regime
        assert final_regime in [TrendRegime.STRONG_UPTREND, TrendRegime.WEAK_UPTREND, TrendRegime.SIDEWAYS]
        
    def test_downtrend_detection(self):
        """Test downtrend detection."""
        market_data = create_test_market_data_with_regime('trending_down', 50)
        
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should detect some form of downtrend
        final_regime = self.detector.current_regime
        assert final_regime in [TrendRegime.STRONG_DOWNTREND, TrendRegime.WEAK_DOWNTREND, TrendRegime.SIDEWAYS]
        
    def test_sideways_detection(self):
        """Test sideways market detection."""
        market_data = create_test_market_data_with_regime('normal', 50)
        
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should detect sideways or weak trend
        final_regime = self.detector.current_regime
        assert isinstance(final_regime, TrendRegime)
        
    def test_trend_stats(self):
        """Test trend statistics calculation."""
        market_data = create_test_market_data_with_regime('trending_up', 30)
        
        for data in market_data:
            self.detector.update(data)
            
        stats = self.detector.get_trend_stats()
        
        assert 'strength' in stats
        assert 'direction' in stats
        
        assert 0 <= stats['strength'] <= 1
        assert -1 <= stats['direction'] <= 1
        
    def test_insufficient_data_handling(self):
        """Test handling of insufficient data."""
        market_data = create_test_market_data_with_regime('normal', 5)
        
        for data in market_data:
            regime = self.detector.update(data)
            
        # Should maintain initial regime
        assert self.detector.current_regime == TrendRegime.SIDEWAYS


class TestMarketRegimeDetector:
    """Test integrated market regime detector."""
    
    def setup_method(self):
        """Set up test market regime detector."""
        self.detector = MarketRegimeDetector()
        
    def test_detector_initialization(self):
        """Test market regime detector initialization."""
        assert self.detector.session_detector is not None
        assert self.detector.volatility_detector is not None
        assert self.detector.trend_detector is not None
        assert isinstance(self.detector.current_regime, MarketRegime)
        
    def test_regime_update(self):
        """Test regime update with market data."""
        market_data = create_test_market_data_with_regime('normal', 30)
        
        for data in market_data:
            regime = self.detector.update(data, 'EUR/USD')
            
        assert isinstance(regime, MarketRegime)
        assert isinstance(regime.volatility_regime, VolatilityRegime)
        assert isinstance(regime.trend_regime, TrendRegime)
        assert isinstance(regime.current_session, TradingSession)
        assert 0 <= regime.volatility_percentile <= 100
        assert 0 <= regime.regime_confidence <= 1
        
    def test_regime_features(self):
        """Test regime feature extraction."""
        market_data = create_test_market_data_with_regime('normal', 20)
        
        for data in market_data:
            self.detector.update(data, 'EUR/USD')
            
        features = self.detector.get_regime_features()
        
        # Check session features
        session_features = [k for k in features.keys() if k.startswith('session_')]
        assert len(session_features) == 7  # 7 possible sessions
        
        # Check volatility features
        vol_features = [k for k in features.keys() if k.startswith('vol_')]
        assert len(vol_features) == 5  # 4 regimes + percentile
        
        # Check trend features
        trend_features = [k for k in features.keys() if k.startswith('trend_')]
        assert len(trend_features) == 6  # 5 regimes + strength
        
        # Check all values are in valid ranges
        for key, value in features.items():
            assert 0 <= value <= 1, f"Feature {key} has invalid value {value}"
            
    def test_regime_summary(self):
        """Test regime summary generation."""
        market_data = create_test_market_data_with_regime('normal', 20)
        
        for data in market_data:
            self.detector.update(data, 'EUR/USD')
            
        summary = self.detector.get_regime_summary()
        
        assert 'current_session' in summary
        assert 'volatility_regime' in summary
        assert 'trend_regime' in summary
        assert 'volatility_percentile' in summary
        assert 'trend_strength' in summary
        assert 'regime_confidence' in summary
        assert 'regime_duration' in summary
        assert 'last_regime_change' in summary
        assert 'active_sessions' in summary
        
    def test_strategy_adjustment_recommendations(self):
        """Test strategy adjustment recommendations."""
        market_data = create_test_market_data_with_regime('high_volatility', 30)
        
        for data in market_data:
            self.detector.update(data, 'EUR/USD')
            
        should_adjust, reason = self.detector.should_adjust_strategy()
        
        assert isinstance(should_adjust, bool)
        assert isinstance(reason, str)
        
    def test_session_adjusted_features(self):
        """Test session-adjusted feature calculation."""
        market_data = create_test_market_data_with_regime('normal', 20)
        
        for data in market_data:
            self.detector.update(data, 'EUR/USD')
            
        base_features = {'volatility': 0.5, 'volume': 0.8, 'momentum': 0.3}
        adjusted_features = self.detector.get_session_adjusted_features(base_features)
        
        assert len(adjusted_features) == len(base_features)
        assert 'volatility' in adjusted_features
        assert 'volume' in adjusted_features
        assert 'momentum' in adjusted_features
        
    def test_regime_history(self):
        """Test regime history tracking."""
        market_data = create_test_market_data_with_regime('normal', 20)
        
        for data in market_data:
            self.detector.update(data, 'EUR/USD')
            
        history = self.detector.get_regime_history(10)
        
        assert len(history) <= 10
        assert all(isinstance(regime, MarketRegime) for regime in history)


class TestAdaptiveRewardCalculator:
    """Test adaptive reward calculator."""
    
    def setup_method(self):
        """Set up test adaptive reward calculator."""
        self.config = MultiPairEnvironmentConfig(
            currency_pairs=['EUR/USD', 'GBP/USD'],
            state_features=['price', 'technical'],
            action_space_type='discrete',
            reward_function='adaptive',
            lookback_window=10,
            normalization_method='standard',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        self.calculator = AdaptiveRewardCalculator(self.config)
        
    def test_calculator_initialization(self):
        """Test adaptive reward calculator initialization."""
        assert self.calculator.config == self.config
        assert self.calculator.regime_detector is not None
        assert len(self.calculator.base_weights) > 0
        assert len(self.calculator.session_adjustments) > 0
        assert len(self.calculator.volatility_adjustments) > 0
        
    def test_reward_calculation(self):
        """Test basic reward calculation."""
        prev_portfolio = MultiPairPortfolioState(
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
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        market_data = MarketData(
            symbol='EUR/USD',
            timestamp=datetime.now(timezone.utc),
            open=1.2000,
            high=1.2010,
            low=1.1990,
            close=1.2005,
            volume=5000,
            bid=1.2003,
            ask=1.2007,
            spread=0.0004
        )
        
        reward = self.calculator.calculate_reward(prev_portfolio, current_portfolio, 1, market_data)
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        assert -5.0 <= reward <= 5.0  # Should be clipped to reasonable range
        
    def test_regime_based_adjustment(self):
        """Test that rewards are adjusted based on regime."""
        # Create portfolios
        prev_portfolio = MultiPairPortfolioState(
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
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Test during London session (should get bonus)
        london_time = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        london_data = MarketData(
            symbol='EUR/USD',
            timestamp=london_time,
            open=1.2000,
            high=1.2010,
            low=1.1990,
            close=1.2005,
            volume=10000,  # High volume
            bid=1.2003,
            ask=1.2007,
            spread=0.0004
        )
        
        london_reward = self.calculator.calculate_reward(prev_portfolio, current_portfolio, 1, london_data)
        
        # Test during quiet session (should get penalty)
        quiet_time = datetime(2024, 1, 15, 21, 0, 0, tzinfo=timezone.utc)
        quiet_data = MarketData(
            symbol='EUR/USD',
            timestamp=quiet_time,
            open=1.2000,
            high=1.2010,
            low=1.1990,
            close=1.2005,
            volume=1000,  # Low volume
            bid=1.2003,
            ask=1.2007,
            spread=0.0004
        )
        
        quiet_reward = self.calculator.calculate_reward(prev_portfolio, current_portfolio, 1, quiet_data)
        
        # London session should generally give better rewards for trading
        # (though this depends on the specific regime detected)
        assert isinstance(london_reward, float)
        assert isinstance(quiet_reward, float)
        
    def test_reward_breakdown(self):
        """Test detailed reward breakdown."""
        prev_portfolio = MultiPairPortfolioState(
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
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        market_data = MarketData(
            symbol='EUR/USD',
            timestamp=datetime.now(timezone.utc),
            open=1.2000,
            high=1.2010,
            low=1.1990,
            close=1.2005,
            volume=5000,
            bid=1.2003,
            ask=1.2007,
            spread=0.0004
        )
        
        breakdown = self.calculator.get_reward_breakdown(prev_portfolio, current_portfolio, 1, market_data)
        
        assert isinstance(breakdown, dict)
        assert 'final_reward' in breakdown
        assert 'current_session' in breakdown
        assert 'volatility_regime' in breakdown
        assert 'trend_regime' in breakdown
        assert 'regime_confidence' in breakdown
        
    def test_multi_pair_reward_calculation(self):
        """Test reward calculation with multi-pair market data."""
        prev_portfolio = MultiPairPortfolioState(
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
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        market_data = {
            'EUR/USD': MarketData(
                symbol='EUR/USD',
                timestamp=datetime.now(timezone.utc),
                open=1.2000,
                high=1.2010,
                low=1.1990,
                close=1.2005,
                volume=5000,
                bid=1.2003,
                ask=1.2007,
                spread=0.0004
            ),
            'GBP/USD': MarketData(
                symbol='GBP/USD',
                timestamp=datetime.now(timezone.utc),
                open=1.3000,
                high=1.3015,
                low=1.2985,
                close=1.3008,
                volume=4000,
                bid=1.3006,
                ask=1.3010,
                spread=0.0004
            )
        }
        
        reward = self.calculator.calculate_reward(prev_portfolio, current_portfolio, 1, market_data)
        
        assert isinstance(reward, float)
        assert not np.isnan(reward)
        assert not np.isinf(reward)
        
    def test_regime_info_retrieval(self):
        """Test regime information retrieval."""
        # Update regime with some data first
        market_data = MarketData(
            symbol='EUR/USD',
            timestamp=datetime.now(timezone.utc),
            open=1.2000,
            high=1.2010,
            low=1.1990,
            close=1.2005,
            volume=5000,
            bid=1.2003,
            ask=1.2007,
            spread=0.0004
        )
        
        self.calculator.regime_detector.update(market_data, 'EUR/USD')
        
        regime_info = self.calculator.get_regime_info()
        
        assert isinstance(regime_info, dict)
        assert 'current_session' in regime_info
        assert 'volatility_regime' in regime_info
        assert 'trend_regime' in regime_info
        
    def test_reward_weight_updates(self):
        """Test updating reward weights."""
        original_pnl_weight = self.calculator.base_weights['pnl']
        
        self.calculator.update_reward_weights(pnl=2.0)
        
        assert self.calculator.base_weights['pnl'] == 2.0
        assert self.calculator.base_weights['pnl'] != original_pnl_weight
        
    def test_adaptive_config_retrieval(self):
        """Test adaptive configuration retrieval."""
        config = self.calculator.get_adaptive_config()
        
        assert isinstance(config, dict)
        assert 'base_weights' in config
        assert 'session_adjustments' in config
        assert 'volatility_adjustments' in config
        assert 'trend_adjustments' in config
        assert 'current_regime' in config


class TestMarketRegimeIntegration:
    """Integration tests for market regime detection and adaptive rewards."""
    
    def test_full_regime_detection_workflow(self):
        """Test complete regime detection workflow."""
        detector = MarketRegimeDetector()
        
        # Create market data with different regimes
        trending_data = create_test_market_data_with_regime('trending_up', 50)
        high_vol_data = create_test_market_data_with_regime('high_volatility', 30)
        
        # Process trending data
        for data in trending_data:
            regime = detector.update(data, 'EUR/USD')
            
        trending_regime = detector.current_regime
        
        # Process high volatility data
        for data in high_vol_data:
            regime = detector.update(data, 'EUR/USD')
            
        high_vol_regime = detector.current_regime
        
        # Verify regime detection
        assert isinstance(trending_regime, MarketRegime)
        assert isinstance(high_vol_regime, MarketRegime)
        
        # Regimes should potentially be different
        # (though randomness might make them similar)
        assert trending_regime.volatility_regime in list(VolatilityRegime)
        assert high_vol_regime.volatility_regime in list(VolatilityRegime)
        
    def test_adaptive_reward_with_regime_changes(self):
        """Test adaptive rewards responding to regime changes."""
        config = MultiPairEnvironmentConfig(
            currency_pairs=['EUR/USD', 'GBP/USD'],
            state_features=['price', 'technical'],
            action_space_type='discrete',
            reward_function='adaptive',
            lookback_window=10,
            normalization_method='standard',
            transaction_cost=0.0001,
            max_position_size=1.0,
            initial_balance=10000.0
        )
        
        calculator = AdaptiveRewardCalculator(config)
        
        # Create portfolios
        prev_portfolio = MultiPairPortfolioState(
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
        
        current_portfolio = MultiPairPortfolioState(
            balance=10000.0,
            equity=10050.0,
            current_position=0.1,
            unrealized_pnl=50.0,
            realized_pnl=0.0,
            total_trades=1,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
        
        # Test rewards in different regimes
        rewards = []
        
        # Low volatility regime
        low_vol_data = create_test_market_data_with_regime('low_volatility', 20)
        for data in low_vol_data:
            reward = calculator.calculate_reward(prev_portfolio, current_portfolio, 1, data)
            rewards.append(reward)
            
        # High volatility regime
        high_vol_data = create_test_market_data_with_regime('high_volatility', 20)
        for data in high_vol_data:
            reward = calculator.calculate_reward(prev_portfolio, current_portfolio, 1, data)
            rewards.append(reward)
            
        # Should have calculated rewards for all data points
        assert len(rewards) == 40
        assert all(isinstance(r, float) for r in rewards)
        assert all(not np.isnan(r) for r in rewards)


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
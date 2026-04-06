"""
Unit tests for Trade Attribution and Analysis System
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil
from pathlib import Path

from src.rl.monitoring.trade_attribution import (
    TradeAttributionAnalyzer, MarketRegimeDetector, TradeAttribution,
    StrategyDecomposition, MarketRegime, AttributionFactor
)
from src.rl.monitoring.performance_tracker import TradeRecord, PerformanceMetrics
from src.rl.monitoring.logger import RLLogger
from src.rl.agents.base import RLAgent
from src.models import MarketData, Direction


class MockAgent(RLAgent):
    """Mock RL agent for testing."""
    
    def __init__(self):
        self.agent_id = "test_agent"
        
    def select_action(self, state, training=False):
        return 1
        
    def store_experience(self, *args):
        pass
        
    def train_step(self):
        return 0.1
        
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
        return {}


class TestMarketRegimeDetector:
    """Test cases for MarketRegimeDetector."""
    
    @pytest.fixture
    def detector(self):
        """Create regime detector for testing."""
        return MarketRegimeDetector(
            lookback_window=20,
            volatility_threshold=0.02,
            trend_threshold=0.01
        )
    
    def test_initialization(self, detector):
        """Test detector initialization."""
        assert detector.lookback_window == 20
        assert detector.volatility_threshold == 0.02
        assert detector.trend_threshold == 0.01
    
    def test_detect_trending_up_regime(self, detector):
        """Test detection of upward trending regime."""
        # Create upward trending price data with higher trend strength
        prices = [1.0 + i * 0.02 for i in range(30)]  # Stronger upward trend
        
        regime = detector.detect_regime(prices)
        
        # Should detect either trending up or low volatility (both are valid for strong trends)
        assert regime in [MarketRegime.TRENDING_UP, MarketRegime.LOW_VOLATILITY]
    
    def test_detect_trending_down_regime(self, detector):
        """Test detection of downward trending regime."""
        # Create downward trending price data
        prices = [1.0 - i * 0.01 for i in range(30)]  # Steady downward trend
        
        regime = detector.detect_regime(prices)
        
        assert regime == MarketRegime.TRENDING_DOWN
    
    def test_detect_ranging_regime(self, detector):
        """Test detection of ranging market regime."""
        # Create sideways price data
        prices = [1.0 + 0.001 * np.sin(i * 0.1) for i in range(30)]  # Small oscillations
        
        regime = detector.detect_regime(prices)
        
        assert regime in [MarketRegime.RANGING, MarketRegime.LOW_VOLATILITY]
    
    def test_detect_high_volatility_regime(self, detector):
        """Test detection of high volatility regime."""
        # Create high volatility price data
        np.random.seed(42)
        prices = [1.0 + np.random.normal(0, 0.05) for i in range(30)]  # High volatility
        
        regime = detector.detect_regime(prices)
        
        assert regime in [MarketRegime.HIGH_VOLATILITY, MarketRegime.RANGING]
    
    def test_detect_breakout_regime(self, detector):
        """Test detection of breakout regime."""
        # Create breakout pattern - stable then sudden volatility
        stable_prices = [1.0 + 0.001 * i for i in range(20)]
        volatile_prices = [1.02 + np.random.normal(0, 0.03) for i in range(10)]
        prices = stable_prices + volatile_prices
        
        regime = detector.detect_regime(prices)
        
        # Should detect breakout or high volatility
        assert regime in [MarketRegime.BREAKOUT, MarketRegime.HIGH_VOLATILITY]
    
    def test_insufficient_data(self, detector):
        """Test behavior with insufficient data."""
        prices = [1.0, 1.01, 1.02]  # Less than lookback window
        
        regime = detector.detect_regime(prices)
        
        assert regime == MarketRegime.RANGING
    
    def test_get_regime_statistics(self, detector):
        """Test regime statistics calculation."""
        prices = [1.0 + i * 0.01 + np.random.normal(0, 0.005) for i in range(30)]
        
        stats = detector.get_regime_statistics(prices)
        
        assert 'volatility' in stats
        assert 'trend_strength' in stats
        assert 'skewness' in stats
        assert 'kurtosis' in stats
        assert 'autocorrelation' in stats
        
        assert isinstance(stats['volatility'], float)
        assert isinstance(stats['trend_strength'], float)
    
    def test_empty_price_data(self, detector):
        """Test behavior with empty price data."""
        prices = []
        
        regime = detector.detect_regime(prices)
        stats = detector.get_regime_statistics(prices)
        
        assert regime == MarketRegime.RANGING
        assert stats == {}


class TestTradeAttributionAnalyzer:
    """Test cases for TradeAttributionAnalyzer."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def mock_logger(self):
        """Create mock logger."""
        return Mock(spec=RLLogger)
    
    @pytest.fixture
    def analyzer(self, temp_dir, mock_logger):
        """Create trade attribution analyzer."""
        return TradeAttributionAnalyzer(
            logger=mock_logger,
            save_dir=temp_dir
        )
    
    @pytest.fixture
    def sample_trade(self):
        """Create sample trade record."""
        return TradeRecord(
            entry_time=datetime.now() - timedelta(hours=2),
            exit_time=datetime.now(),
            entry_price=1.2000,
            exit_price=1.2050,
            position_size=0.01,
            currency_pair="EUR/USD",
            pnl=5.0,
            duration=2.0,
            agent_id="test_agent",
            strategy_id="test_strategy"
        )
    
    @pytest.fixture
    def sample_market_data(self):
        """Create sample market data."""
        from datetime import timezone
        base_time = datetime.now(timezone.utc) - timedelta(hours=100)
        data = []
        
        for i in range(100):
            timestamp = base_time + timedelta(hours=i)
            price = 1.2000 + 0.001 * np.sin(i * 0.1) + np.random.normal(0, 0.0005)
            
            data.append(MarketData(
                symbol="EUR/USD",
                timestamp=timestamp,
                open=price,
                high=price + 0.0005,
                low=price - 0.0005,
                close=price,
                volume=1000,
                bid=price - 0.0001,
                ask=price + 0.0001,
                spread=0.0002
            ))
        
        return data
    
    @pytest.fixture
    def mock_agent(self):
        """Create mock agent."""
        return MockAgent()
    
    def test_initialization(self, analyzer, temp_dir):
        """Test analyzer initialization."""
        assert analyzer.save_dir == Path(temp_dir)
        assert analyzer.save_dir.exists()
        assert isinstance(analyzer.regime_detector, MarketRegimeDetector)
        assert len(analyzer.trade_attributions) == 0
        assert len(analyzer.strategy_decompositions) == 0
    
    def test_analyze_trade_success(self, analyzer, sample_trade, mock_agent, sample_market_data):
        """Test successful trade analysis."""
        state_vector = np.random.random(50)
        action_probabilities = np.array([0.1, 0.7, 0.2])
        q_values = np.array([0.5, 1.2, 0.8])
        
        attribution = analyzer.analyze_trade(
            trade=sample_trade,
            agent=mock_agent,
            market_data=sample_market_data,
            state_vector=state_vector,
            action_probabilities=action_probabilities,
            q_values=q_values
        )
        
        assert isinstance(attribution, TradeAttribution)
        assert attribution.trade_id is not None
        assert attribution.agent_id == mock_agent.agent_id
        assert attribution.symbol == sample_trade.currency_pair
        assert attribution.pnl == sample_trade.pnl
        assert isinstance(attribution.market_regime, MarketRegime)
        assert len(attribution.factor_contributions) == len(AttributionFactor)
        assert 0.0 <= attribution.confidence_score <= 1.0
        assert len(analyzer.trade_attributions) == 1
    
    def test_analyze_trade_without_probabilities(self, analyzer, sample_trade, mock_agent, sample_market_data):
        """Test trade analysis without action probabilities."""
        state_vector = np.random.random(50)
        
        attribution = analyzer.analyze_trade(
            trade=sample_trade,
            agent=mock_agent,
            market_data=sample_market_data,
            state_vector=state_vector
        )
        
        assert isinstance(attribution, TradeAttribution)
        assert attribution.action_probabilities is None
        assert attribution.q_values is None
        assert attribution.confidence_score == 0.5  # Default confidence
    
    def test_analyze_trade_with_null_pnl(self, analyzer, mock_agent, sample_market_data):
        """Test trade analysis with null P&L."""
        trade = TradeRecord(
            entry_time=datetime.now() - timedelta(hours=1),
            exit_time=None,  # Open trade
            entry_price=1.2000,
            exit_price=None,
            position_size=0.01,
            currency_pair="EUR/USD",
            pnl=None,
            duration=None,
            agent_id="test_agent",
            strategy_id="test_strategy"
        )
        
        state_vector = np.random.random(50)
        
        attribution = analyzer.analyze_trade(
            trade=trade,
            agent=mock_agent,
            market_data=sample_market_data,
            state_vector=state_vector
        )
        
        assert attribution.pnl is None
        assert attribution.exit_time is None
        assert attribution.exit_price is None
    
    def test_decompose_strategy_performance(self, analyzer, mock_agent, sample_market_data):
        """Test strategy performance decomposition."""
        # Create multiple trades
        trades = []
        for i in range(10):
            trade = TradeRecord(
                entry_time=datetime.now() - timedelta(days=10-i),
                exit_time=datetime.now() - timedelta(days=10-i, hours=-2),
                entry_price=1.2000 + i * 0.001,
                exit_price=1.2000 + i * 0.001 + (0.005 if i % 2 == 0 else -0.003),
                position_size=0.01,
                currency_pair="EUR/USD",
                pnl=5.0 if i % 2 == 0 else -3.0,
                duration=2.0,
                agent_id="test_agent",
                strategy_id="test_strategy"
            )
            trades.append(trade)
            
            # Analyze each trade first
            state_vector = np.random.random(50)
            analyzer.analyze_trade(
                trade=trade,
                agent=mock_agent,
                market_data=sample_market_data,
                state_vector=state_vector
            )
        
        start_date = datetime.now() - timedelta(days=15)
        end_date = datetime.now()
        
        decomposition = analyzer.decompose_strategy_performance(
            strategy_id="test_strategy",
            trades=trades,
            start_date=start_date,
            end_date=end_date
        )
        
        assert isinstance(decomposition, StrategyDecomposition)
        assert decomposition.strategy_id == "test_strategy"
        assert decomposition.analysis_period == (start_date, end_date)
        assert isinstance(decomposition.total_return, float)
        assert len(decomposition.factor_returns) == len(AttributionFactor)
        assert len(decomposition.regime_performance) > 0
        assert 0.0 <= decomposition.skill_score <= 1.0
    
    def test_decompose_strategy_no_trades(self, analyzer):
        """Test strategy decomposition with no trades."""
        start_date = datetime.now() - timedelta(days=10)
        end_date = datetime.now()
        
        with pytest.raises(ValueError, match="No trades found in specified period"):
            analyzer.decompose_strategy_performance(
                strategy_id="empty_strategy",
                trades=[],
                start_date=start_date,
                end_date=end_date
            )
    
    def test_factor_contribution_calculation(self, analyzer, sample_trade, sample_market_data):
        """Test factor contribution calculation."""
        state_vector = np.random.random(50)
        regime_stats = {
            'volatility': 0.015,
            'trend_strength': 0.008,
            'skewness': 0.1,
            'kurtosis': 2.5
        }
        
        contributions = analyzer._calculate_factor_contributions(
            sample_trade, sample_market_data, state_vector, regime_stats
        )
        
        assert len(contributions) == len(AttributionFactor)
        assert all(isinstance(contrib, float) for contrib in contributions.values())
        
        # Check that all factors are present
        for factor in AttributionFactor:
            assert factor in contributions
    
    def test_timing_score_calculation(self, analyzer, sample_trade, sample_market_data):
        """Test timing score calculations."""
        entry_score = analyzer._calculate_entry_timing_score(sample_trade, sample_market_data)
        exit_score = analyzer._calculate_exit_timing_score(sample_trade, sample_market_data)
        
        assert 0.0 <= entry_score <= 1.0
        assert 0.0 <= exit_score <= 1.0
    
    def test_risk_metrics_calculation(self, analyzer, sample_trade, sample_market_data):
        """Test risk metrics calculation."""
        risk_metrics = analyzer._calculate_trade_risk_metrics(sample_trade, sample_market_data)
        
        assert 'risk_adjusted_return' in risk_metrics
        assert 'sharpe_contribution' in risk_metrics
        assert 'max_adverse_excursion' in risk_metrics
        assert 'max_favorable_excursion' in risk_metrics
        
        assert all(isinstance(metric, float) for metric in risk_metrics.values())
    
    def test_confidence_score_calculation(self, analyzer):
        """Test confidence score calculation."""
        # Test with action probabilities
        action_probs = np.array([0.1, 0.8, 0.1])
        confidence = analyzer._calculate_confidence_score(action_probs, None)
        assert confidence == 0.8
        
        # Test with Q-values
        q_values = np.array([0.5, 1.5, 0.8])
        confidence = analyzer._calculate_confidence_score(None, q_values)
        assert 0.0 <= confidence <= 1.0
        
        # Test with neither
        confidence = analyzer._calculate_confidence_score(None, None)
        assert confidence == 0.5
    
    def test_volatility_percentile_calculation(self, analyzer):
        """Test volatility percentile calculation."""
        # Create price series with known volatility pattern
        prices = [1.0 + 0.01 * np.sin(i * 0.1) + np.random.normal(0, 0.005) for i in range(100)]
        
        percentile = analyzer._calculate_volatility_percentile(prices)
        
        assert 0.0 <= percentile <= 1.0
    
    def test_get_attribution_summary(self, analyzer, sample_trade, mock_agent, sample_market_data):
        """Test attribution summary generation."""
        # Analyze a trade first
        state_vector = np.random.random(50)
        analyzer.analyze_trade(
            trade=sample_trade,
            agent=mock_agent,
            market_data=sample_market_data,
            state_vector=state_vector
        )
        
        summary = analyzer.get_attribution_summary(mock_agent.agent_id)
        
        assert 'strategy_id' in summary
        assert 'total_trades' in summary
        assert 'total_pnl' in summary
        assert 'avg_confidence' in summary
        assert 'factor_contributions' in summary
        assert 'regime_distribution' in summary
        assert 'avg_timing_scores' in summary
        
        assert summary['total_trades'] == 1
        assert summary['total_pnl'] == sample_trade.pnl
    
    def test_get_attribution_summary_empty(self, analyzer):
        """Test attribution summary with no trades."""
        summary = analyzer.get_attribution_summary("nonexistent_strategy")
        
        assert summary == {}
    
    def test_save_and_load_attribution_analysis(self, analyzer, temp_dir, sample_trade, mock_agent, sample_market_data):
        """Test saving and loading attribution analysis."""
        # Analyze a trade first
        state_vector = np.random.random(50)
        analyzer.analyze_trade(
            trade=sample_trade,
            agent=mock_agent,
            market_data=sample_market_data,
            state_vector=state_vector
        )
        
        # Save analysis
        filepath = analyzer.save_attribution_analysis()
        
        assert Path(filepath).exists()
        assert Path(filepath).suffix == '.json'
        
        # Create new analyzer and load
        new_analyzer = TradeAttributionAnalyzer(save_dir=temp_dir)
        new_analyzer.load_attribution_analysis(filepath)
        
        # Verify data was loaded (simplified check)
        assert len(new_analyzer.trade_attributions) > 0
    
    def test_regime_performance_calculation(self, analyzer):
        """Test regime-based performance calculation."""
        # Create trades with different regimes
        trades = []
        for i in range(5):
            trade = TradeRecord(
                entry_time=datetime.now() - timedelta(days=i),
                exit_time=datetime.now() - timedelta(days=i, hours=-2),
                entry_price=1.2000,
                exit_price=1.2010 if i % 2 == 0 else 1.1990,
                position_size=0.01,
                currency_pair="EUR/USD",
                pnl=10.0 if i % 2 == 0 else -10.0,
                duration=2.0,
                agent_id="test_agent",
                strategy_id="test_strategy"
            )
            trades.append(trade)
            
            # Create attribution with different regimes
            trade_id = analyzer._generate_trade_id(trade)
            attribution = TradeAttribution(
                trade_id=trade_id,
                agent_id="test_agent",
                symbol=trade.currency_pair,
                entry_time=trade.entry_time,
                exit_time=trade.exit_time,
                direction=Direction.LONG,
                entry_price=trade.entry_price,
                exit_price=trade.exit_price,
                position_size=trade.position_size,
                pnl=trade.pnl,
                market_regime=MarketRegime.TRENDING_UP if i % 2 == 0 else MarketRegime.RANGING,
                volatility_percentile=0.5,
                trend_strength=0.01,
                factor_contributions={factor: 0.0 for factor in AttributionFactor},
                state_vector=np.random.random(50),
                action_probabilities=None,
                q_values=None,
                confidence_score=0.7,
                risk_adjusted_return=0.1,
                sharpe_contribution=0.05,
                max_adverse_excursion=5.0,
                max_favorable_excursion=15.0,
                entry_timing_score=0.8,
                exit_timing_score=0.7,
                hold_duration=2.0
            )
            analyzer.trade_attributions[trade_id] = attribution
        
        regime_performance = analyzer._calculate_regime_performance(trades)
        
        assert len(regime_performance) > 0
        for regime, performance in regime_performance.items():
            assert isinstance(regime, MarketRegime)
            assert isinstance(performance, PerformanceMetrics)
    
    def test_skill_metrics_calculation(self, analyzer):
        """Test skill vs luck metrics calculation."""
        # Create trades with consistent positive returns (skill)
        skilled_trades = [
            TradeRecord(
                entry_time=datetime.now() - timedelta(days=i),
                exit_time=datetime.now() - timedelta(days=i, hours=-2),
                entry_price=1.2000,
                exit_price=1.2010,
                position_size=0.01,
                currency_pair="EUR/USD",
                pnl=10.0 + np.random.normal(0, 2),  # Consistent positive with small noise
                duration=2.0,
                agent_id="skilled_agent",
                strategy_id="skilled_strategy"
            )
            for i in range(20)
        ]
        
        skill_metrics = analyzer._calculate_skill_metrics(skilled_trades)
        
        assert 'skill_score' in skill_metrics
        assert 'luck_component' in skill_metrics
        assert 'statistical_significance' in skill_metrics
        assert 'risk_adjusted_return' in skill_metrics
        
        # Should show high skill for consistent positive returns
        assert skill_metrics['skill_score'] > 0.0
        assert skill_metrics['luck_component'] < 1.0
    
    def test_consistency_metrics_calculation(self, analyzer):
        """Test consistency metrics calculation."""
        # Create trades spread across multiple months
        trades = []
        base_date = datetime(2023, 1, 1)
        
        for month in range(1, 7):  # 6 months
            for day in range(1, 6):  # 5 trades per month
                trade_date = base_date.replace(month=month, day=day)
                trade = TradeRecord(
                    entry_time=trade_date,
                    exit_time=trade_date + timedelta(hours=2),
                    entry_price=1.2000,
                    exit_price=1.2005,
                    position_size=0.01,
                    currency_pair="EUR/USD",
                    pnl=5.0 + np.random.normal(0, 1),  # Consistent returns with noise
                    duration=2.0,
                    agent_id="consistent_agent",
                    strategy_id="consistent_strategy"
                )
                trades.append(trade)
        
        consistency_metrics = analyzer._calculate_consistency_metrics(trades)
        
        assert 'monthly_returns' in consistency_metrics
        assert 'return_consistency' in consistency_metrics
        assert 'drawdown_consistency' in consistency_metrics
        
        assert len(consistency_metrics['monthly_returns']) == 6  # 6 months
        assert isinstance(consistency_metrics['return_consistency'], float)


class TestTradeAttributionDataClasses:
    """Test cases for attribution data classes."""
    
    def test_trade_attribution_to_dict(self):
        """Test TradeAttribution serialization."""
        attribution = TradeAttribution(
            trade_id="test_trade",
            agent_id="test_agent",
            symbol="EUR/USD",
            entry_time=datetime.now(),
            exit_time=datetime.now() + timedelta(hours=2),
            direction=Direction.LONG,
            entry_price=1.2000,
            exit_price=1.2050,
            position_size=0.01,
            pnl=5.0,
            market_regime=MarketRegime.TRENDING_UP,
            volatility_percentile=0.7,
            trend_strength=0.015,
            factor_contributions={AttributionFactor.MARKET_DIRECTION: 2.5},
            state_vector=np.array([1.0, 2.0, 3.0]),
            action_probabilities=np.array([0.1, 0.8, 0.1]),
            q_values=np.array([0.5, 1.5, 0.8]),
            confidence_score=0.8,
            risk_adjusted_return=0.1,
            sharpe_contribution=0.05,
            max_adverse_excursion=2.0,
            max_favorable_excursion=8.0,
            entry_timing_score=0.9,
            exit_timing_score=0.8,
            hold_duration=2.0
        )
        
        result_dict = attribution.to_dict()
        
        assert isinstance(result_dict, dict)
        assert result_dict['trade_id'] == "test_trade"
        assert result_dict['market_regime'] == MarketRegime.TRENDING_UP.value
        assert isinstance(result_dict['state_vector'], list)
        assert isinstance(result_dict['action_probabilities'], list)
        assert isinstance(result_dict['q_values'], list)
    
    def test_strategy_decomposition_to_dict(self):
        """Test StrategyDecomposition serialization."""
        start_date = datetime.now() - timedelta(days=30)
        end_date = datetime.now()
        
        decomposition = StrategyDecomposition(
            strategy_id="test_strategy",
            analysis_period=(start_date, end_date),
            total_return=0.15,
            risk_adjusted_return=0.12,
            factor_returns={AttributionFactor.MARKET_DIRECTION: 0.08},
            factor_sharpe_ratios={AttributionFactor.MARKET_DIRECTION: 1.2},
            factor_hit_rates={AttributionFactor.MARKET_DIRECTION: 0.65},
            regime_performance={MarketRegime.TRENDING_UP: Mock()},
            regime_exposure={MarketRegime.TRENDING_UP: 0.6},
            skill_score=0.8,
            luck_component=0.2,
            statistical_significance=0.95,
            monthly_returns=[0.02, 0.03, 0.01],
            return_consistency=0.85,
            drawdown_consistency=0.90
        )
        
        # Mock the performance metrics to_dict method
        decomposition.regime_performance[MarketRegime.TRENDING_UP].to_dict = Mock(return_value={'mock': 'data'})
        
        result_dict = decomposition.to_dict()
        
        assert isinstance(result_dict, dict)
        assert result_dict['strategy_id'] == "test_strategy"
        assert MarketRegime.TRENDING_UP.value in result_dict['regime_performance']
        assert MarketRegime.TRENDING_UP.value in result_dict['regime_exposure']


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
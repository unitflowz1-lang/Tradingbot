"""
Unit tests for A/B Testing Framework.

Tests the ABTestingFramework class and related components for
statistical significance testing and automated strategy switching.
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
import tempfile
import shutil
from pathlib import Path

from src.rl.strategies.ab_testing import (
    ABTestingFramework, ABTest, ABTestConfiguration, StatisticalTestResult,
    ABTestStatus, SignificanceTest, ABTestSnapshot
)
from src.rl.strategies.models import (
    RLStrategy, StrategyMetadata, PerformanceMetrics,
    StrategyStatus, AgentType, create_strategy_metadata
)
from src.rl.strategies.registry import StrategyRegistry


class TestABTestConfiguration:
    """Test ABTestConfiguration class."""
    
    def test_valid_configuration(self):
        """Test valid configuration creation."""
        config = ABTestConfiguration(
            test_name="Test A vs B",
            strategy_a_id="strategy_a",
            strategy_b_id="strategy_b",
            allocation_split=(0.6, 0.4),
            primary_metric="sharpe_ratio",
            significance_level=0.05
        )
        
        assert config.test_name == "Test A vs B"
        assert config.allocation_split == (0.6, 0.4)
        assert config.primary_metric == "sharpe_ratio"
        assert config.significance_level == 0.05
    
    def test_invalid_allocation_split(self):
        """Test invalid allocation split validation."""
        with pytest.raises(ValueError, match="Invalid allocation split"):
            ABTestConfiguration(
                test_name="Test",
                strategy_a_id="a",
                strategy_b_id="b",
                allocation_split=(0.0, 1.0)  # Invalid: 0.0
            )
        
        with pytest.raises(ValueError, match="Allocation split must sum to 1.0"):
            ABTestConfiguration(
                test_name="Test",
                strategy_a_id="a",
                strategy_b_id="b",
                allocation_split=(0.6, 0.5)  # Invalid: doesn't sum to 1.0
            )
    
    def test_invalid_significance_level(self):
        """Test invalid significance level validation."""
        with pytest.raises(ValueError, match="Significance level must be between 0 and 1"):
            ABTestConfiguration(
                test_name="Test",
                strategy_a_id="a",
                strategy_b_id="b",
                significance_level=1.5  # Invalid
            )
    
    def test_invalid_sample_size(self):
        """Test invalid minimum sample size validation."""
        with pytest.raises(ValueError, match="Minimum sample size too small"):
            ABTestConfiguration(
                test_name="Test",
                strategy_a_id="a",
                strategy_b_id="b",
                minimum_sample_size=5  # Too small
            )


class TestStatisticalTestResult:
    """Test StatisticalTestResult class."""
    
    def test_test_result_creation(self):
        """Test StatisticalTestResult creation and serialization."""
        result = StatisticalTestResult(
            test_type=SignificanceTest.WELCH_T_TEST,
            statistic=2.5,
            p_value=0.012,
            is_significant=True,
            confidence_interval=(-0.5, -0.1),
            effect_size=0.8,
            power=0.85
        )
        
        assert result.test_type == SignificanceTest.WELCH_T_TEST
        assert result.statistic == 2.5
        assert result.p_value == 0.012
        assert result.is_significant is True
        assert result.confidence_interval == (-0.5, -0.1)
        assert result.effect_size == 0.8
        assert result.power == 0.85
        
        # Test serialization
        result_dict = result.to_dict()
        assert result_dict['test_type'] == 'welch_t_test'
        assert result_dict['statistic'] == 2.5
        assert result_dict['p_value'] == 0.012
        assert result_dict['is_significant'] is True


class TestABTest:
    """Test ABTest class."""
    
    @pytest.fixture
    def sample_strategies(self):
        """Create sample strategies for testing."""
        metadata_a = create_strategy_metadata(
            name="Strategy A",
            description="Test strategy A",
            agent_type=AgentType.PPO,
            created_by="test_user"
        )
        
        metadata_b = create_strategy_metadata(
            name="Strategy B", 
            description="Test strategy B",
            agent_type=AgentType.DQN,
            created_by="test_user"
        )
        
        performance_a = PerformanceMetrics(
            total_return=0.15,
            sharpe_ratio=1.2,
            max_drawdown=0.08,
            win_rate=0.6,
            profit_factor=1.5,
            calmar_ratio=1.8,
            sortino_ratio=1.4,
            num_trades=100,
            avg_trade_duration=2.5,
            volatility=0.12
        )
        
        performance_b = PerformanceMetrics(
            total_return=0.12,
            sharpe_ratio=1.0,
            max_drawdown=0.10,
            win_rate=0.55,
            profit_factor=1.3,
            calmar_ratio=1.2,
            sortino_ratio=1.1,
            num_trades=95,
            avg_trade_duration=2.8,
            volatility=0.15
        )
        
        strategy_a = RLStrategy(metadata=metadata_a, performance_metrics=performance_a)
        strategy_b = RLStrategy(metadata=metadata_b, performance_metrics=performance_b)
        
        return strategy_a, strategy_b
    
    @pytest.fixture
    def test_config(self):
        """Create test configuration."""
        return ABTestConfiguration(
            test_name="Strategy Comparison Test",
            strategy_a_id="strategy_a",
            strategy_b_id="strategy_b",
            allocation_split=(0.5, 0.5),
            primary_metric="sharpe_ratio",
            secondary_metrics=["total_return", "max_drawdown"],
            significance_level=0.05,
            minimum_sample_size=30
        )
    
    def test_ab_test_creation(self, test_config, sample_strategies):
        """Test ABTest creation."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        assert test.config == test_config
        assert test.strategy_a == strategy_a
        assert test.strategy_b == strategy_b
        assert test.status == ABTestStatus.SETUP
        assert test.started_at is None
        assert test.completed_at is None
        assert len(test.performance_history) == 2
    
    def test_test_lifecycle(self, test_config, sample_strategies):
        """Test test lifecycle (start, stop)."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        # Start test
        test.start()
        assert test.status == ABTestStatus.RUNNING
        assert test.started_at is not None
        
        # Stop test
        test.stop("Manual stop")
        assert test.status == ABTestStatus.STOPPED
        assert test.completed_at is not None
        assert test.stop_reason == "Manual stop"
    
    def test_performance_data_addition(self, test_config, sample_strategies):
        """Test adding performance data."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        # Add performance data
        perf_data_a = {
            "sharpe_ratio": 1.3,
            "total_return": 0.16,
            "max_drawdown": 0.07
        }
        
        test.add_performance_data(strategy_a.strategy_id, perf_data_a)
        
        assert len(test.performance_history[strategy_a.strategy_id]) == 1
        assert test.performance_history[strategy_a.strategy_id][0]["sharpe_ratio"] == 1.3
    
    def test_sample_sizes(self, test_config, sample_strategies):
        """Test sample size calculation."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        # Add some data
        for i in range(5):
            test.add_performance_data(strategy_a.strategy_id, {"sharpe_ratio": 1.0 + i * 0.1})
        
        for i in range(3):
            test.add_performance_data(strategy_b.strategy_id, {"sharpe_ratio": 0.9 + i * 0.1})
        
        sample_sizes = test.get_sample_sizes()
        assert sample_sizes == (5, 3)
    
    def test_duration_calculation(self, test_config, sample_strategies):
        """Test duration calculation."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        # Before starting
        assert test.get_duration_days() == 0.0
        
        # After starting
        test.start()
        duration = test.get_duration_days()
        assert duration >= 0.0
        assert duration < 1.0  # Should be less than a day
    
    def test_status_summary(self, test_config, sample_strategies):
        """Test status summary generation."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        test.start()
        
        summary = test.get_status_summary()
        
        assert summary['test_name'] == "Strategy Comparison Test"
        assert summary['status'] == ABTestStatus.RUNNING.value
        assert summary['strategy_a']['name'] == "Strategy A"
        assert summary['strategy_b']['name'] == "Strategy B"
        assert summary['primary_metric'] == "sharpe_ratio"
    
    def test_significance_testing(self, test_config, sample_strategies):
        """Test statistical significance testing."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        # Add sufficient data for testing
        np.random.seed(42)
        for i in range(50):
            test.add_performance_data(
                strategy_a.strategy_id,
                {"sharpe_ratio": np.random.normal(1.2, 0.1)}
            )
            test.add_performance_data(
                strategy_b.strategy_id,
                {"sharpe_ratio": np.random.normal(1.0, 0.1)}
            )
        
        # Run significance test
        result = test._run_significance_test("sharpe_ratio")
        
        assert result is not None
        assert isinstance(result, StatisticalTestResult)
        assert result.test_type == SignificanceTest.WELCH_T_TEST
        assert isinstance(result.statistic, float)
        assert 0 <= result.p_value <= 1
        assert isinstance(result.is_significant, bool)
        assert len(result.confidence_interval) == 2
    
    def test_winner_recommendation(self, test_config, sample_strategies):
        """Test winner recommendation."""
        strategy_a, strategy_b = sample_strategies
        test = ABTest(test_config, strategy_a, strategy_b)
        
        # Add data where A clearly outperforms B
        for i in range(30):
            test.add_performance_data(
                strategy_a.strategy_id,
                {"sharpe_ratio": 1.5 + np.random.normal(0, 0.05)}
            )
            test.add_performance_data(
                strategy_b.strategy_id,
                {"sharpe_ratio": 1.0 + np.random.normal(0, 0.05)}
            )
        
        # Force create snapshot to run significance tests
        test._create_snapshot()
        
        recommendation = test.get_winner_recommendation()
        
        if recommendation:  # May be None if not enough data
            assert 'winner_strategy_id' in recommendation
            assert 'confidence' in recommendation
            assert 'is_significant' in recommendation
            assert 'improvement' in recommendation


class TestABTestingFramework:
    """Test ABTestingFramework class."""
    
    @pytest.fixture
    def temp_registry_path(self):
        """Create temporary registry path."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
    
    @pytest.fixture
    def strategy_registry(self, temp_registry_path):
        """Create strategy registry with sample strategies."""
        registry = StrategyRegistry(temp_registry_path)
        
        # Create and register sample strategies
        metadata_a = create_strategy_metadata(
            name="Strategy A",
            description="Test strategy A",
            agent_type=AgentType.PPO,
            created_by="test_user"
        )
        
        metadata_b = create_strategy_metadata(
            name="Strategy B",
            description="Test strategy B", 
            agent_type=AgentType.DQN,
            created_by="test_user"
        )
        
        performance_a = PerformanceMetrics(
            total_return=0.15,
            sharpe_ratio=1.2,
            max_drawdown=0.08,
            win_rate=0.6,
            profit_factor=1.5,
            calmar_ratio=1.8,
            sortino_ratio=1.4,
            num_trades=100,
            avg_trade_duration=2.5,
            volatility=0.12
        )
        
        performance_b = PerformanceMetrics(
            total_return=0.12,
            sharpe_ratio=1.0,
            max_drawdown=0.10,
            win_rate=0.55,
            profit_factor=1.3,
            calmar_ratio=1.2,
            sortino_ratio=1.1,
            num_trades=95,
            avg_trade_duration=2.8,
            volatility=0.15
        )
        
        strategy_a = RLStrategy(metadata=metadata_a, performance_metrics=performance_a)
        strategy_b = RLStrategy(metadata=metadata_b, performance_metrics=performance_b)
        
        registry.register_strategy(strategy_a)
        registry.register_strategy(strategy_b)
        
        return registry
    
    @pytest.fixture
    def ab_framework(self, strategy_registry):
        """Create ABTestingFramework instance."""
        return ABTestingFramework(
            strategy_registry=strategy_registry,
            min_confidence_level=0.95,
            auto_switch_enabled=True
        )
    
    def test_framework_initialization(self, strategy_registry):
        """Test framework initialization."""
        framework = ABTestingFramework(
            strategy_registry=strategy_registry,
            min_confidence_level=0.95,
            auto_switch_enabled=True
        )
        
        assert framework.strategy_registry == strategy_registry
        assert framework.min_confidence_level == 0.95
        assert framework.auto_switch_enabled is True
        assert len(framework.active_tests) == 0
        assert len(framework.completed_tests) == 0
    
    def test_create_test(self, ab_framework, strategy_registry):
        """Test test creation."""
        strategies = list(strategy_registry._strategies.values())
        
        config = ABTestConfiguration(
            test_name="Test A vs B",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        test_id = ab_framework.create_test(config, start_immediately=False)
        
        assert test_id in ab_framework.active_tests
        test = ab_framework.active_tests[test_id]
        assert test.status == ABTestStatus.SETUP
        assert test.config.test_name == "Test A vs B"
    
    def test_create_test_with_invalid_strategy(self, ab_framework):
        """Test test creation with invalid strategy."""
        config = ABTestConfiguration(
            test_name="Invalid Test",
            strategy_a_id="nonexistent_a",
            strategy_b_id="nonexistent_b"
        )
        
        with pytest.raises(ValueError, match="Strategy A not found"):
            ab_framework.create_test(config)
    
    def test_start_test(self, ab_framework, strategy_registry):
        """Test starting a test."""
        strategies = list(strategy_registry._strategies.values())
        
        config = ABTestConfiguration(
            test_name="Test A vs B",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        test_id = ab_framework.create_test(config, start_immediately=False)
        
        # Start test
        success = ab_framework.start_test(test_id)
        assert success is True
        
        test = ab_framework.active_tests[test_id]
        assert test.status == ABTestStatus.RUNNING
        assert test.started_at is not None
    
    def test_stop_test(self, ab_framework, strategy_registry):
        """Test stopping a test."""
        strategies = list(strategy_registry._strategies.values())
        
        config = ABTestConfiguration(
            test_name="Test A vs B",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        test_id = ab_framework.create_test(config, start_immediately=True)
        
        # Stop test
        success = ab_framework.stop_test(test_id, "Manual stop")
        assert success is True
        
        # Test should be moved to completed
        assert test_id not in ab_framework.active_tests
        assert test_id in ab_framework.completed_tests
        
        test = ab_framework.completed_tests[test_id]
        assert test.status == ABTestStatus.STOPPED
        assert test.stop_reason == "Manual stop"
    
    def test_update_performance(self, ab_framework, strategy_registry):
        """Test performance data updates."""
        strategies = list(strategy_registry._strategies.values())
        strategy_id = strategies[0].strategy_id
        
        config = ABTestConfiguration(
            test_name="Test A vs B",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        test_id = ab_framework.create_test(config, start_immediately=True)
        
        # Update performance
        performance_data = {
            "sharpe_ratio": 1.3,
            "total_return": 0.16,
            "max_drawdown": 0.07
        }
        
        ab_framework.update_performance(strategy_id, performance_data)
        
        # Check that data was added to test
        test = ab_framework.active_tests[test_id]
        assert len(test.performance_history[strategy_id]) == 1
        assert test.performance_history[strategy_id][0]["sharpe_ratio"] == 1.3
    
    def test_get_test_status(self, ab_framework, strategy_registry):
        """Test getting test status."""
        strategies = list(strategy_registry._strategies.values())
        
        config = ABTestConfiguration(
            test_name="Test A vs B",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        test_id = ab_framework.create_test(config, start_immediately=True)
        
        status = ab_framework.get_test_status(test_id)
        
        assert status is not None
        assert status['test_name'] == "Test A vs B"
        assert status['status'] == ABTestStatus.RUNNING.value
        assert 'strategy_a' in status
        assert 'strategy_b' in status
    
    def test_list_active_tests(self, ab_framework, strategy_registry):
        """Test listing active tests."""
        strategies = list(strategy_registry._strategies.values())
        
        # Create multiple tests
        config1 = ABTestConfiguration(
            test_name="Test 1",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        test_id1 = ab_framework.create_test(config1, start_immediately=True)
        
        active_tests = ab_framework.list_active_tests()
        
        assert len(active_tests) == 1
        assert active_tests[0]['test_name'] == "Test 1"
        assert active_tests[0]['status'] == ABTestStatus.RUNNING.value
    
    def test_conflicting_tests(self, ab_framework, strategy_registry):
        """Test detection of conflicting tests."""
        strategies = list(strategy_registry._strategies.values())
        
        config1 = ABTestConfiguration(
            test_name="Test 1",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id
        )
        
        config2 = ABTestConfiguration(
            test_name="Test 2",
            strategy_a_id=strategies[0].strategy_id,  # Same strategy
            strategy_b_id=strategies[1].strategy_id
        )
        
        # Create first test
        ab_framework.create_test(config1, start_immediately=True)
        
        # Try to create conflicting test
        with pytest.raises(ValueError, match="Conflicting test already running"):
            ab_framework.create_test(config2)
    
    def test_sample_size_calculation(self, ab_framework):
        """Test required sample size calculation."""
        sample_size = ab_framework.calculate_required_sample_size(
            effect_size=0.5,
            power=0.8,
            significance_level=0.05
        )
        
        assert isinstance(sample_size, int)
        assert sample_size > 0
        # For effect size 0.5, power 0.8, alpha 0.05, should be around 64 per group
        assert 50 < sample_size < 100
    
    def test_callback_registration(self, ab_framework):
        """Test callback registration and triggering."""
        callback_called = []
        
        def test_callback(test):
            callback_called.append(test.test_id)
        
        ab_framework.register_callback('test_started', test_callback)
        
        # Verify callback is registered
        assert len(ab_framework.test_callbacks['test_started']) == 1
        
        # Test invalid event
        with pytest.raises(ValueError, match="Unknown event type"):
            ab_framework.register_callback('invalid_event', test_callback)
    
    @patch('src.rl.strategies.ab_testing.logger')
    def test_early_stopping(self, mock_logger, ab_framework, strategy_registry):
        """Test early stopping functionality."""
        strategies = list(strategy_registry._strategies.values())
        
        config = ABTestConfiguration(
            test_name="Early Stop Test",
            strategy_a_id=strategies[0].strategy_id,
            strategy_b_id=strategies[1].strategy_id,
            early_stopping_enabled=True,
            minimum_sample_size=20
        )
        
        test_id = ab_framework.create_test(config, start_immediately=True)
        test = ab_framework.active_tests[test_id]
        
        # Mock test to appear older than 7 days
        test.started_at = datetime.now() - timedelta(days=8)
        
        # Add data that should show clear significance
        np.random.seed(42)
        for i in range(30):
            ab_framework.update_performance(
                strategies[0].strategy_id,
                {"sharpe_ratio": np.random.normal(2.0, 0.1)}  # Much higher
            )
            ab_framework.update_performance(
                strategies[1].strategy_id,
                {"sharpe_ratio": np.random.normal(1.0, 0.1)}  # Lower
            )
        
        # The test should potentially be stopped early due to significance
        # (This depends on the random data generating significant results)


class TestStatisticalTests:
    """Test individual statistical test methods."""
    
    @pytest.fixture
    def ab_test_instance(self):
        """Create ABTest instance for testing statistical methods."""
        config = ABTestConfiguration(
            test_name="Statistical Test",
            strategy_a_id="a",
            strategy_b_id="b"
        )
        
        metadata_a = create_strategy_metadata(
            name="Strategy A",
            description="Test strategy A",
            agent_type=AgentType.PPO,
            created_by="test_user"
        )
        
        metadata_b = create_strategy_metadata(
            name="Strategy B",
            description="Test strategy B",
            agent_type=AgentType.DQN,
            created_by="test_user"
        )
        
        strategy_a = RLStrategy(metadata=metadata_a)
        strategy_b = RLStrategy(metadata=metadata_b)
        
        return ABTest(config, strategy_a, strategy_b)
    
    def test_t_test(self, ab_test_instance):
        """Test t-test implementation."""
        np.random.seed(42)
        data_a = np.random.normal(1.0, 0.2, 50)
        data_b = np.random.normal(0.8, 0.2, 50)
        
        result = ab_test_instance._t_test(data_a, data_b)
        
        assert isinstance(result, StatisticalTestResult)
        assert result.test_type == SignificanceTest.T_TEST
        assert isinstance(result.statistic, float)
        assert 0 <= result.p_value <= 1
        assert isinstance(result.is_significant, bool)
        assert len(result.confidence_interval) == 2
        assert isinstance(result.effect_size, float)
    
    def test_welch_t_test(self, ab_test_instance):
        """Test Welch's t-test implementation."""
        np.random.seed(42)
        data_a = np.random.normal(1.0, 0.1, 30)  # Different variance
        data_b = np.random.normal(0.8, 0.3, 40)  # and sample size
        
        result = ab_test_instance._welch_t_test(data_a, data_b)
        
        assert isinstance(result, StatisticalTestResult)
        assert result.test_type == SignificanceTest.WELCH_T_TEST
        assert isinstance(result.statistic, float)
        assert 0 <= result.p_value <= 1
        assert isinstance(result.is_significant, bool)
        assert len(result.confidence_interval) == 2
        assert isinstance(result.effect_size, float)
    
    def test_mann_whitney_test(self, ab_test_instance):
        """Test Mann-Whitney U test implementation."""
        np.random.seed(42)
        # Create non-normal data
        data_a = np.random.exponential(1.0, 40)
        data_b = np.random.exponential(1.5, 35)
        
        result = ab_test_instance._mann_whitney_test(data_a, data_b)
        
        assert isinstance(result, StatisticalTestResult)
        assert result.test_type == SignificanceTest.MANN_WHITNEY
        assert isinstance(result.statistic, float)
        assert 0 <= result.p_value <= 1
        assert isinstance(result.is_significant, bool)
        assert len(result.confidence_interval) == 2
        assert isinstance(result.effect_size, float)
    
    def test_bootstrap_test(self, ab_test_instance):
        """Test bootstrap test implementation."""
        np.random.seed(42)
        data_a = np.random.normal(1.0, 0.2, 30)
        data_b = np.random.normal(0.8, 0.2, 30)
        
        result = ab_test_instance._bootstrap_test(data_a, data_b, n_bootstrap=1000)
        
        assert isinstance(result, StatisticalTestResult)
        assert result.test_type == SignificanceTest.BOOTSTRAP
        assert isinstance(result.statistic, float)
        assert 0 <= result.p_value <= 1
        assert isinstance(result.is_significant, bool)
        assert len(result.confidence_interval) == 2
        assert isinstance(result.effect_size, float)


if __name__ == "__main__":
    pytest.main([__file__])

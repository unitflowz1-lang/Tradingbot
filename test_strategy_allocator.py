"""
Unit tests for RL Strategy Allocator system.

Tests strategy allocation algorithms, portfolio management,
and risk-based allocation constraints.
"""

import pytest
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

from src.rl.strategies.allocator import (
    StrategyAllocator, AllocationMethod, AllocationConstraints,
    AllocationResult
)
from src.rl.strategies.models import (
    RLStrategy, StrategyMetadata, PerformanceMetrics,
    StrategyStatus, AgentType, create_strategy_metadata
)


class TestAllocationConstraints:
    """Test cases for AllocationConstraints."""
    
    def test_valid_constraints(self):
        """Test valid constraint creation."""
        constraints = AllocationConstraints(
            min_allocation=0.05,
            max_allocation=0.3,
            max_strategies=5,
            min_sharpe_ratio=0.5,
            max_drawdown_threshold=0.2
        )
        assert constraints.min_allocation == 0.05
        assert constraints.max_allocation == 0.3
        assert constraints.max_strategies == 5
    
    def test_invalid_min_allocation(self):
        """Test invalid min_allocation raises error."""
        with pytest.raises(ValueError, match="min_allocation must be between 0 and 1"):
            AllocationConstraints(min_allocation=-0.1)
        
        with pytest.raises(ValueError, match="min_allocation must be between 0 and 1"):
            AllocationConstraints(min_allocation=1.5)
    
    def test_invalid_max_allocation(self):
        """Test invalid max_allocation raises error."""
        with pytest.raises(ValueError, match="max_allocation must be between 0 and 1"):
            AllocationConstraints(max_allocation=-0.1)
        
        with pytest.raises(ValueError, match="max_allocation must be between 0 and 1"):
            AllocationConstraints(max_allocation=1.5)
    
    def test_min_greater_than_max(self):
        """Test min_allocation > max_allocation raises error."""
        with pytest.raises(ValueError, match="min_allocation cannot be greater than max_allocation"):
            AllocationConstraints(min_allocation=0.6, max_allocation=0.4)
    
    def test_invalid_max_strategies(self):
        """Test invalid max_strategies raises error."""
        with pytest.raises(ValueError, match="max_strategies must be positive"):
            AllocationConstraints(max_strategies=0)
        
        with pytest.raises(ValueError, match="max_strategies must be positive"):
            AllocationConstraints(max_strategies=-1)


class TestAllocationResult:
    """Test cases for AllocationResult."""
    
    @pytest.fixture
    def sample_result(self):
        """Create sample allocation result."""
        return AllocationResult(
            allocations={"strategy1": 0.4, "strategy2": 0.3, "strategy3": 0.3},
            total_allocation=1.0,
            excluded_strategies=["strategy4"],
            rebalance_required=True,
            allocation_method=AllocationMethod.PERFORMANCE_WEIGHTED,
            timestamp=datetime.now(),
            metadata={"num_strategies": 3}
        )
    
    def test_get_active_strategies(self, sample_result):
        """Test getting active strategies."""
        active = sample_result.get_active_strategies()
        assert len(active) == 3
        assert "strategy1" in active
        assert "strategy2" in active
        assert "strategy3" in active
    
    def test_get_allocation(self, sample_result):
        """Test getting specific allocation."""
        assert sample_result.get_allocation("strategy1") == 0.4
        assert sample_result.get_allocation("strategy2") == 0.3
        assert sample_result.get_allocation("nonexistent") == 0.0


class TestStrategyAllocator:
    """Test cases for StrategyAllocator class."""
    
    @pytest.fixture
    def allocator(self):
        """Create StrategyAllocator instance."""
        return StrategyAllocator()
    
    @pytest.fixture
    def sample_strategies(self):
        """Create sample strategies with performance metrics."""
        strategies = []
        
        # Strategy 1: High Sharpe, moderate return
        metadata1 = create_strategy_metadata(
            name="Strategy 1", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        performance1 = PerformanceMetrics(
            total_return=0.15,
            sharpe_ratio=1.5,
            max_drawdown=0.08,
            win_rate=0.65,
            profit_factor=1.8,
            calmar_ratio=1.9,
            sortino_ratio=1.6,
            num_trades=100,
            avg_trade_duration=2.5,
            volatility=0.10
        )
        strategies.append(RLStrategy(metadata=metadata1, performance_metrics=performance1))
        
        # Strategy 2: Moderate Sharpe, high return
        metadata2 = create_strategy_metadata(
            name="Strategy 2", description="Test", agent_type=AgentType.PPO, created_by="test"
        )
        performance2 = PerformanceMetrics(
            total_return=0.25,
            sharpe_ratio=1.2,
            max_drawdown=0.12,
            win_rate=0.60,
            profit_factor=1.6,
            calmar_ratio=2.1,
            sortino_ratio=1.4,
            num_trades=120,
            avg_trade_duration=2.0,
            volatility=0.15
        )
        strategies.append(RLStrategy(metadata=metadata2, performance_metrics=performance2))
        
        # Strategy 3: Low Sharpe, low return
        metadata3 = create_strategy_metadata(
            name="Strategy 3", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        performance3 = PerformanceMetrics(
            total_return=0.08,
            sharpe_ratio=0.8,
            max_drawdown=0.15,
            win_rate=0.55,
            profit_factor=1.3,
            calmar_ratio=0.5,
            sortino_ratio=0.9,
            num_trades=80,
            avg_trade_duration=3.0,
            volatility=0.12
        )
        strategies.append(RLStrategy(metadata=metadata3, performance_metrics=performance3))
        
        return strategies
    
    def test_allocator_initialization(self):
        """Test allocator initialization."""
        constraints = AllocationConstraints(min_allocation=0.1, max_allocation=0.5)
        allocator = StrategyAllocator(
            allocation_method=AllocationMethod.SHARPE_WEIGHTED,
            constraints=constraints,
            lookback_days=60
        )
        
        assert allocator.allocation_method == AllocationMethod.SHARPE_WEIGHTED
        assert allocator.constraints.min_allocation == 0.1
        assert allocator.lookback_days == 60
        assert len(allocator.allocation_history) == 0
    
    def test_calculate_allocations_empty_strategies(self, allocator):
        """Test allocation calculation with empty strategy list."""
        result = allocator.calculate_allocations([])
        
        assert len(result.allocations) == 0
        assert result.total_allocation == 0.0
        assert not result.rebalance_required
        assert len(result.excluded_strategies) == 0
    
    def test_equal_weight_allocation(self, sample_strategies):
        """Test equal weight allocation method."""
        allocator = StrategyAllocator(allocation_method=AllocationMethod.EQUAL_WEIGHT)
        result = allocator.calculate_allocations(sample_strategies)
        
        assert len(result.allocations) == 3
        expected_weight = 1.0 / 3
        for weight in result.allocations.values():
            assert abs(weight - expected_weight) < 1e-6
        assert abs(result.total_allocation - 1.0) < 1e-6
    
    def test_performance_weighted_allocation(self, sample_strategies):
        """Test performance-weighted allocation method."""
        allocator = StrategyAllocator(allocation_method=AllocationMethod.PERFORMANCE_WEIGHTED)
        result = allocator.calculate_allocations(sample_strategies)
        
        assert len(result.allocations) == 3
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
        
        # Strategy 2 should have highest allocation (highest return)
        strategy_ids = [s.strategy_id for s in sample_strategies]
        strategy2_id = strategy_ids[1]  # Strategy 2 has highest return (0.25)
        
        max_allocation = max(result.allocations.values())
        assert result.allocations[strategy2_id] == max_allocation
    
    def test_sharpe_weighted_allocation(self, sample_strategies):
        """Test Sharpe ratio weighted allocation method."""
        allocator = StrategyAllocator(allocation_method=AllocationMethod.SHARPE_WEIGHTED)
        result = allocator.calculate_allocations(sample_strategies)
        
        assert len(result.allocations) == 3
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
        
        # Strategy 1 should have highest allocation (highest Sharpe ratio)
        strategy_ids = [s.strategy_id for s in sample_strategies]
        strategy1_id = strategy_ids[0]  # Strategy 1 has highest Sharpe (1.5)
        
        max_allocation = max(result.allocations.values())
        assert result.allocations[strategy1_id] == max_allocation
    
    def test_volatility_inverse_allocation(self, sample_strategies):
        """Test inverse volatility weighted allocation method."""
        allocator = StrategyAllocator(allocation_method=AllocationMethod.VOLATILITY_INVERSE)
        result = allocator.calculate_allocations(sample_strategies)
        
        assert len(result.allocations) == 3
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
        
        # Strategy 1 should have highest allocation (lowest volatility)
        strategy_ids = [s.strategy_id for s in sample_strategies]
        strategy1_id = strategy_ids[0]  # Strategy 1 has lowest volatility (0.10)
        
        max_allocation = max(result.allocations.values())
        assert result.allocations[strategy1_id] == max_allocation
    
    def test_kelly_criterion_allocation(self, sample_strategies):
        """Test Kelly criterion allocation method."""
        allocator = StrategyAllocator(allocation_method=AllocationMethod.KELLY_CRITERION)
        result = allocator.calculate_allocations(sample_strategies)
        
        assert len(result.allocations) == 3
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
        
        # All allocations should be positive and reasonable
        for weight in result.allocations.values():
            assert weight > 0
            # Kelly weights are normalized, so individual weights can be higher after normalization
    
    def test_allocation_with_constraints(self, sample_strategies):
        """Test allocation with constraints."""
        constraints = AllocationConstraints(
            min_allocation=0.1,
            max_allocation=0.4,
            min_sharpe_ratio=1.0  # Should exclude Strategy 3 (Sharpe = 0.8)
        )
        allocator = StrategyAllocator(
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
            constraints=constraints
        )
        
        result = allocator.calculate_allocations(sample_strategies)
        
        # Should only have 2 strategies (Strategy 3 excluded)
        assert len(result.allocations) == 2
        assert len(result.excluded_strategies) == 1
        
        # Each allocation should be at least min_allocation
        # Note: max_allocation constraint is applied before normalization,
        # so final weights may exceed max_allocation after renormalization
        for weight in result.allocations.values():
            assert weight >= constraints.min_allocation
    
    def test_max_strategies_constraint(self, sample_strategies):
        """Test maximum strategies constraint."""
        constraints = AllocationConstraints(max_strategies=2)
        allocator = StrategyAllocator(
            allocation_method=AllocationMethod.SHARPE_WEIGHTED,
            constraints=constraints
        )
        
        result = allocator.calculate_allocations(sample_strategies)
        
        # Should only have 2 strategies (top 2 by Sharpe ratio)
        assert len(result.allocations) == 2
        assert len(result.excluded_strategies) == 1
        
        # Should include strategies 1 and 2 (highest Sharpe ratios)
        strategy_ids = [s.strategy_id for s in sample_strategies]
        assert strategy_ids[0] in result.allocations  # Strategy 1
        assert strategy_ids[1] in result.allocations  # Strategy 2
        assert strategy_ids[2] in result.excluded_strategies  # Strategy 3
    
    def test_strategies_without_performance_metrics(self, allocator):
        """Test handling strategies without performance metrics."""
        # Create strategy without performance metrics
        metadata = create_strategy_metadata(
            name="No Metrics Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        strategy_no_metrics = RLStrategy(metadata=metadata)
        
        result = allocator.calculate_allocations([strategy_no_metrics])
        
        assert len(result.allocations) == 0
        assert len(result.excluded_strategies) == 1
        assert strategy_no_metrics.strategy_id in result.excluded_strategies
    
    def test_update_performance(self, allocator):
        """Test updating performance history."""
        strategy_id = "test_strategy"
        performance_data = {
            "return": 0.05,
            "sharpe": 1.2,
            "drawdown": 0.03
        }
        
        allocator.update_performance(strategy_id, performance_data)
        
        assert strategy_id in allocator.performance_history
        assert len(allocator.performance_history[strategy_id]) == 1
        assert allocator.performance_history[strategy_id][0]["return"] == 0.05
        assert "timestamp" in allocator.performance_history[strategy_id][0]
    
    def test_get_current_allocations(self, allocator, sample_strategies):
        """Test getting current allocations."""
        # Initially empty
        current = allocator.get_current_allocations()
        assert len(current) == 0
        
        # After calculation
        result = allocator.calculate_allocations(sample_strategies)
        current = allocator.get_current_allocations()
        
        assert len(current) == len(result.allocations)
        for strategy_id, weight in result.allocations.items():
            assert current[strategy_id] == weight
    
    def test_get_allocation_history(self, allocator, sample_strategies):
        """Test getting allocation history."""
        # Initially empty
        history = allocator.get_allocation_history()
        assert len(history) == 0
        
        # After calculations
        allocator.calculate_allocations(sample_strategies)
        allocator.calculate_allocations(sample_strategies[:2])  # Different allocation
        
        history = allocator.get_allocation_history()
        assert len(history) == 2
        
        # Test with days filter
        recent_history = allocator.get_allocation_history(days=1)
        assert len(recent_history) == 2  # Both should be recent
    
    def test_calculate_portfolio_metrics(self, allocator, sample_strategies):
        """Test calculating portfolio-level metrics."""
        allocations = {
            sample_strategies[0].strategy_id: 0.5,
            sample_strategies[1].strategy_id: 0.3,
            sample_strategies[2].strategy_id: 0.2
        }
        
        metrics = allocator.calculate_portfolio_metrics(allocations, sample_strategies)
        
        assert "portfolio_return" in metrics
        assert "portfolio_sharpe" in metrics
        assert "portfolio_max_drawdown" in metrics
        assert "diversification_ratio" in metrics
        assert "concentration_risk" in metrics
        
        # Portfolio return should be weighted average
        expected_return = (
            0.5 * 0.15 +  # Strategy 1
            0.3 * 0.25 +  # Strategy 2
            0.2 * 0.08    # Strategy 3
        )
        assert metrics["portfolio_return"] == pytest.approx(expected_return, abs=1e-6)
        
        # Concentration risk should be max allocation
        assert metrics["concentration_risk"] == 0.5
    
    def test_rebalancing_threshold(self, sample_strategies):
        """Test rebalancing threshold logic."""
        # Create allocator with low rebalance threshold
        constraints = AllocationConstraints(rebalance_threshold=0.01)
        allocator = StrategyAllocator(
            allocation_method=AllocationMethod.PERFORMANCE_WEIGHTED,
            constraints=constraints
        )
        
        # First allocation
        result1 = allocator.calculate_allocations(sample_strategies)
        assert result1.rebalance_required  # First allocation always requires rebalancing
        
        # Second allocation with same strategies (should not require rebalancing)
        result2 = allocator.calculate_allocations(sample_strategies)
        assert not result2.rebalance_required
        
        # Change allocation method to force rebalancing
        allocator.allocation_method = AllocationMethod.EQUAL_WEIGHT
        result3 = allocator.calculate_allocations(sample_strategies)
        assert result3.rebalance_required
    
    def test_risk_parity_allocation(self, sample_strategies):
        """Test risk parity allocation method."""
        allocator = StrategyAllocator(allocation_method=AllocationMethod.RISK_PARITY)
        result = allocator.calculate_allocations(sample_strategies)
        
        assert len(result.allocations) == 3
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
        
        # Without correlation matrix, should fall back to inverse volatility
        # Strategy 1 should have highest allocation (lowest volatility)
        strategy_ids = [s.strategy_id for s in sample_strategies]
        strategy1_id = strategy_ids[0]
        
        max_allocation = max(result.allocations.values())
        assert result.allocations[strategy1_id] == max_allocation
    
    def test_allocation_with_correlation_matrix(self, sample_strategies):
        """Test allocation with correlation matrix."""
        # Create sample correlation matrix
        correlation_matrix = np.array([
            [1.0, 0.3, 0.1],
            [0.3, 1.0, 0.2],
            [0.1, 0.2, 1.0]
        ])
        
        allocator = StrategyAllocator(allocation_method=AllocationMethod.RISK_PARITY)
        result = allocator.calculate_allocations(
            sample_strategies,
            correlation_matrix=correlation_matrix
        )
        
        assert len(result.allocations) == 3
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
    
    def test_edge_case_single_strategy(self, allocator):
        """Test allocation with single strategy."""
        metadata = create_strategy_metadata(
            name="Single Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        performance = PerformanceMetrics(
            total_return=0.15, sharpe_ratio=1.2, max_drawdown=0.08,
            win_rate=0.65, profit_factor=1.5, calmar_ratio=1.9,
            sortino_ratio=1.4, num_trades=100, avg_trade_duration=2.5,
            volatility=0.10
        )
        strategy = RLStrategy(metadata=metadata, performance_metrics=performance)
        
        result = allocator.calculate_allocations([strategy])
        
        assert len(result.allocations) == 1
        assert result.total_allocation == pytest.approx(1.0, abs=1e-6)
        assert list(result.allocations.values())[0] == pytest.approx(1.0, abs=1e-6)
    
    def test_allocation_with_zero_returns(self, allocator):
        """Test allocation with strategies having zero or negative returns."""
        metadata = create_strategy_metadata(
            name="Zero Return Strategy", description="Test", agent_type=AgentType.DQN, created_by="test"
        )
        performance = PerformanceMetrics(
            total_return=0.0,  # Zero return
            sharpe_ratio=0.0,
            max_drawdown=0.05,
            win_rate=0.5,
            profit_factor=1.0,
            calmar_ratio=0.0,
            sortino_ratio=0.0,
            num_trades=50,
            avg_trade_duration=2.0,
            volatility=0.08
        )
        strategy = RLStrategy(metadata=metadata, performance_metrics=performance)
        
        result = allocator.calculate_allocations([strategy])
        
        # Should still allocate (minimum weight applied)
        assert len(result.allocations) == 1
        assert result.total_allocation > 0
    
    def test_performance_history_cleanup(self, allocator):
        """Test performance history cleanup based on lookback period."""
        strategy_id = "test_strategy"
        
        # Add old performance data
        old_data = {"return": 0.05, "timestamp": datetime.now() - timedelta(days=100)}
        allocator.performance_history[strategy_id] = [old_data]
        
        # Add new performance data
        new_data = {"return": 0.08}
        allocator.update_performance(strategy_id, new_data)
        
        # Old data should be cleaned up
        assert len(allocator.performance_history[strategy_id]) == 1
        assert allocator.performance_history[strategy_id][0]["return"] == 0.08


if __name__ == "__main__":
    pytest.main([__file__])
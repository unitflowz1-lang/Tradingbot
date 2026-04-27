"""
Strategy Allocator for RL System

This module contains the StrategyAllocator class for dynamic
capital allocation across multiple RL strategies.
"""

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from enum import Enum
import logging

from .models import RLStrategy, PerformanceMetrics


logger = logging.getLogger(__name__)


class AllocationMethod(Enum):
    """Strategy allocation methods."""
    EQUAL_WEIGHT = "equal_weight"
    PERFORMANCE_WEIGHTED = "performance_weighted"
    RISK_PARITY = "risk_parity"
    SHARPE_WEIGHTED = "sharpe_weighted"
    KELLY_CRITERION = "kelly_criterion"
    VOLATILITY_INVERSE = "volatility_inverse"


@dataclass
class AllocationConstraints:
    """Constraints for strategy allocation."""
    min_allocation: float = 0.0  # Minimum allocation per strategy
    max_allocation: float = 1.0  # Maximum allocation per strategy
    max_strategies: Optional[int] = None  # Maximum number of active strategies
    min_sharpe_ratio: Optional[float] = None  # Minimum Sharpe ratio to include
    max_drawdown_threshold: Optional[float] = None  # Maximum drawdown to include
    correlation_threshold: Optional[float] = None  # Maximum correlation between strategies
    rebalance_threshold: float = 0.05  # Minimum change to trigger rebalancing
    
    def __post_init__(self):
        """Validate constraints."""
        if not 0.0 <= self.min_allocation <= 1.0:
            raise ValueError(f"min_allocation must be between 0 and 1: {self.min_allocation}")
        if not 0.0 <= self.max_allocation <= 1.0:
            raise ValueError(f"max_allocation must be between 0 and 1: {self.max_allocation}")
        if self.min_allocation > self.max_allocation:
            raise ValueError("min_allocation cannot be greater than max_allocation")
        if self.max_strategies is not None and self.max_strategies < 1:
            raise ValueError(f"max_strategies must be positive: {self.max_strategies}")


@dataclass
class AllocationResult:
    """Result of strategy allocation calculation."""
    allocations: Dict[str, float]  # strategy_id -> allocation weight
    total_allocation: float
    excluded_strategies: List[str]  # Strategies excluded due to constraints
    rebalance_required: bool
    allocation_method: AllocationMethod
    timestamp: datetime
    metadata: Dict[str, Any]
    
    def get_active_strategies(self) -> List[str]:
        """Get list of strategies with non-zero allocation."""
        return [strategy_id for strategy_id, weight in self.allocations.items() if weight > 0]
    
    def get_allocation(self, strategy_id: str) -> float:
        """Get allocation for specific strategy."""
        return self.allocations.get(strategy_id, 0.0)


class StrategyAllocator:
    """
    Manages capital allocation across multiple RL strategies.
    
    Supports various allocation methods including performance-based weighting,
    risk parity, and correlation-aware allocation with configurable constraints.
    """
    
    def __init__(
        self,
        allocation_method: AllocationMethod = AllocationMethod.PERFORMANCE_WEIGHTED,
        constraints: Optional[AllocationConstraints] = None,
        lookback_days: int = 30
    ):
        """
        Initialize strategy allocator.
        
        Args:
            allocation_method: Method for calculating allocations
            constraints: Allocation constraints
            lookback_days: Days of performance history to consider
        """
        self.allocation_method = allocation_method
        self.constraints = constraints or AllocationConstraints()
        self.lookback_days = lookback_days
        
        # Track allocation history
        self.allocation_history: List[AllocationResult] = []
        self.current_allocations: Dict[str, float] = {}
        
        # Performance tracking
        self.performance_history: Dict[str, List[Dict[str, Any]]] = {}
        
    def calculate_allocations(
        self,
        strategies: List[RLStrategy],
        performance_history: Optional[Dict[str, List[float]]] = None,
        correlation_matrix: Optional[np.ndarray] = None
    ) -> AllocationResult:
        """
        Calculate optimal capital allocation across strategies.
        
        Args:
            strategies: List of available strategies
            performance_history: Historical returns for each strategy
            correlation_matrix: Correlation matrix between strategies
            
        Returns:
            AllocationResult with calculated weights
        """
        if not strategies:
            return AllocationResult(
                allocations={},
                total_allocation=0.0,
                excluded_strategies=[],
                rebalance_required=False,
                allocation_method=self.allocation_method,
                timestamp=datetime.now(),
                metadata={}
            )
        
        # Filter strategies based on constraints
        eligible_strategies, excluded = self._filter_strategies(strategies)
        
        if not eligible_strategies:
            logger.warning("No eligible strategies after applying constraints")
            return AllocationResult(
                allocations={},
                total_allocation=0.0,
                excluded_strategies=[s.strategy_id for s in strategies],
                rebalance_required=False,
                allocation_method=self.allocation_method,
                timestamp=datetime.now(),
                metadata={"reason": "no_eligible_strategies"}
            )
        
        # Calculate allocations based on method
        allocations = self._calculate_weights(
            eligible_strategies, performance_history, correlation_matrix
        )
        
        # Normalize to sum to 1 first
        total_weight = sum(allocations.values())
        if total_weight > 0:
            allocations = {k: v / total_weight for k, v in allocations.items()}
        
        # Apply constraints after normalization
        allocations = self._apply_constraints(allocations)
        
        # Renormalize after applying constraints
        total_weight = sum(allocations.values())
        if total_weight > 0:
            allocations = {k: v / total_weight for k, v in allocations.items()}
        
        # Check if rebalancing is required
        rebalance_required = self._should_rebalance(allocations)
        
        result = AllocationResult(
            allocations=allocations,
            total_allocation=sum(allocations.values()),
            excluded_strategies=excluded,
            rebalance_required=rebalance_required,
            allocation_method=self.allocation_method,
            timestamp=datetime.now(),
            metadata={
                "num_strategies": len(eligible_strategies),
                "allocation_method": self.allocation_method.value
            }
        )
        
        # Update history
        self.allocation_history.append(result)
        if rebalance_required:
            self.current_allocations = allocations.copy()
        
        logger.info(f"Calculated allocations for {len(eligible_strategies)} strategies using {self.allocation_method.value}")
        return result
    
    def update_performance(
        self,
        strategy_id: str,
        performance_data: Dict[str, Any]
    ) -> None:
        """
        Update performance history for a strategy.
        
        Args:
            strategy_id: Strategy identifier
            performance_data: Performance metrics and data
        """
        if strategy_id not in self.performance_history:
            self.performance_history[strategy_id] = []
        
        performance_data['timestamp'] = datetime.now()
        self.performance_history[strategy_id].append(performance_data)
        
        # Keep only recent history
        cutoff_date = datetime.now() - timedelta(days=self.lookback_days * 2)
        self.performance_history[strategy_id] = [
            data for data in self.performance_history[strategy_id]
            if data['timestamp'] >= cutoff_date
        ]
    
    def get_current_allocations(self) -> Dict[str, float]:
        """Get current strategy allocations."""
        return self.current_allocations.copy()
    
    def get_allocation_history(self, days: Optional[int] = None) -> List[AllocationResult]:
        """
        Get allocation history.
        
        Args:
            days: Number of days to look back (None for all history)
            
        Returns:
            List of allocation results
        """
        if days is None:
            return self.allocation_history.copy()
        
        cutoff_date = datetime.now() - timedelta(days=days)
        return [
            result for result in self.allocation_history
            if result.timestamp >= cutoff_date
        ]
    
    def calculate_portfolio_metrics(
        self,
        allocations: Dict[str, float],
        strategies: List[RLStrategy]
    ) -> Dict[str, float]:
        """
        Calculate portfolio-level metrics given allocations.
        
        Args:
            allocations: Strategy allocations
            strategies: List of strategies
            
        Returns:
            Portfolio metrics
        """
        if not allocations or not strategies:
            return {}
        
        # Create strategy lookup
        strategy_lookup = {s.strategy_id: s for s in strategies}
        
        # Calculate weighted metrics
        total_return = 0.0
        weighted_sharpe = 0.0
        max_drawdown = 0.0
        total_weight = 0.0
        
        for strategy_id, weight in allocations.items():
            if weight <= 0 or strategy_id not in strategy_lookup:
                continue
            
            strategy = strategy_lookup[strategy_id]
            if not strategy.performance_metrics:
                continue
            
            metrics = strategy.performance_metrics
            total_return += weight * metrics.total_return
            weighted_sharpe += weight * metrics.sharpe_ratio
            max_drawdown = max(max_drawdown, metrics.max_drawdown)
            total_weight += weight
        
        if total_weight == 0:
            return {}
        
        return {
            'portfolio_return': total_return,
            'portfolio_sharpe': weighted_sharpe,
            'portfolio_max_drawdown': max_drawdown,
            'diversification_ratio': len([w for w in allocations.values() if w > 0.01]),
            'concentration_risk': max(allocations.values()) if allocations else 0.0
        }
    
    def _filter_strategies(
        self,
        strategies: List[RLStrategy]
    ) -> Tuple[List[RLStrategy], List[str]]:
        """Filter strategies based on constraints."""
        eligible = []
        excluded = []
        
        for strategy in strategies:
            # Check if strategy has performance metrics
            if not strategy.performance_metrics:
                excluded.append(strategy.strategy_id)
                continue
            
            metrics = strategy.performance_metrics
            
            # Check Sharpe ratio threshold
            if (self.constraints.min_sharpe_ratio is not None and
                metrics.sharpe_ratio < self.constraints.min_sharpe_ratio):
                excluded.append(strategy.strategy_id)
                continue
            
            # Check drawdown threshold
            if (self.constraints.max_drawdown_threshold is not None and
                metrics.max_drawdown > self.constraints.max_drawdown_threshold):
                excluded.append(strategy.strategy_id)
                continue
            
            eligible.append(strategy)
        
        # Limit number of strategies if specified
        if (self.constraints.max_strategies is not None and
            len(eligible) > self.constraints.max_strategies):
            # Sort by Sharpe ratio and take top strategies
            eligible.sort(key=lambda s: s.performance_metrics.sharpe_ratio, reverse=True)
            excluded.extend([s.strategy_id for s in eligible[self.constraints.max_strategies:]])
            eligible = eligible[:self.constraints.max_strategies]
        
        return eligible, excluded
    
    def _calculate_weights(
        self,
        strategies: List[RLStrategy],
        performance_history: Optional[Dict[str, List[float]]],
        correlation_matrix: Optional[np.ndarray]
    ) -> Dict[str, float]:
        """Calculate weights based on allocation method."""
        if not strategies:
            return {}
        
        strategy_ids = [s.strategy_id for s in strategies]
        
        if self.allocation_method == AllocationMethod.EQUAL_WEIGHT:
            return self._equal_weight_allocation(strategy_ids)
        
        elif self.allocation_method == AllocationMethod.PERFORMANCE_WEIGHTED:
            return self._performance_weighted_allocation(strategies)
        
        elif self.allocation_method == AllocationMethod.SHARPE_WEIGHTED:
            return self._sharpe_weighted_allocation(strategies)
        
        elif self.allocation_method == AllocationMethod.VOLATILITY_INVERSE:
            return self._volatility_inverse_allocation(strategies)
        
        elif self.allocation_method == AllocationMethod.RISK_PARITY:
            return self._risk_parity_allocation(strategies, correlation_matrix)
        
        elif self.allocation_method == AllocationMethod.KELLY_CRITERION:
            return self._kelly_criterion_allocation(strategies)
        
        else:
            logger.warning(f"Unknown allocation method: {self.allocation_method}")
            return self._equal_weight_allocation(strategy_ids)
    
    def _equal_weight_allocation(self, strategy_ids: List[str]) -> Dict[str, float]:
        """Equal weight allocation."""
        if not strategy_ids:
            return {}
        
        weight = 1.0 / len(strategy_ids)
        return {strategy_id: weight for strategy_id in strategy_ids}
    
    def _performance_weighted_allocation(self, strategies: List[RLStrategy]) -> Dict[str, float]:
        """Performance-weighted allocation based on total returns."""
        returns = []
        strategy_ids = []
        
        for strategy in strategies:
            if strategy.performance_metrics:
                returns.append(max(0.01, strategy.performance_metrics.total_return + 1.0))  # Avoid negative weights
                strategy_ids.append(strategy.strategy_id)
        
        if not returns:
            return {}
        
        total_return = sum(returns)
        return {
            strategy_ids[i]: returns[i] / total_return
            for i in range(len(strategy_ids))
        }
    
    def _sharpe_weighted_allocation(self, strategies: List[RLStrategy]) -> Dict[str, float]:
        """Sharpe ratio weighted allocation."""
        sharpe_ratios = []
        strategy_ids = []
        
        for strategy in strategies:
            if strategy.performance_metrics:
                sharpe_ratios.append(max(0.01, strategy.performance_metrics.sharpe_ratio))
                strategy_ids.append(strategy.strategy_id)
        
        if not sharpe_ratios:
            return {}
        
        total_sharpe = sum(sharpe_ratios)
        return {
            strategy_ids[i]: sharpe_ratios[i] / total_sharpe
            for i in range(len(strategy_ids))
        }
    
    def _volatility_inverse_allocation(self, strategies: List[RLStrategy]) -> Dict[str, float]:
        """Inverse volatility weighted allocation."""
        inv_volatilities = []
        strategy_ids = []
        
        for strategy in strategies:
            if strategy.performance_metrics:
                volatility = max(0.01, strategy.performance_metrics.volatility)
                inv_volatilities.append(1.0 / volatility)
                strategy_ids.append(strategy.strategy_id)
        
        if not inv_volatilities:
            return {}
        
        total_inv_vol = sum(inv_volatilities)
        return {
            strategy_ids[i]: inv_volatilities[i] / total_inv_vol
            for i in range(len(strategy_ids))
        }
    
    def _risk_parity_allocation(
        self,
        strategies: List[RLStrategy],
        correlation_matrix: Optional[np.ndarray]
    ) -> Dict[str, float]:
        """Risk parity allocation (simplified version)."""
        if correlation_matrix is None:
            # Fall back to inverse volatility if no correlation matrix
            return self._volatility_inverse_allocation(strategies)
        
        # For simplicity, use inverse volatility as approximation
        # In practice, this would solve for equal risk contribution
        return self._volatility_inverse_allocation(strategies)
    
    def _kelly_criterion_allocation(self, strategies: List[RLStrategy]) -> Dict[str, float]:
        """Kelly criterion allocation."""
        kelly_weights = []
        strategy_ids = []
        
        for strategy in strategies:
            if strategy.performance_metrics:
                # Simplified Kelly: f = (bp - q) / b
                # where b = odds, p = win probability, q = loss probability
                win_rate = strategy.performance_metrics.win_rate
                profit_factor = strategy.performance_metrics.profit_factor
                
                if profit_factor > 1 and win_rate > 0:
                    # Approximate Kelly fraction
                    kelly_fraction = (win_rate * profit_factor - (1 - win_rate)) / profit_factor
                    kelly_weights.append(max(0.01, min(0.20, kelly_fraction)))  # Cap at 20%
                else:
                    kelly_weights.append(0.01)
                
                strategy_ids.append(strategy.strategy_id)
        
        if not kelly_weights:
            return {}
        
        total_kelly = sum(kelly_weights)
        return {
            strategy_ids[i]: kelly_weights[i] / total_kelly
            for i in range(len(strategy_ids))
        }
    
    def _apply_constraints(self, allocations: Dict[str, float]) -> Dict[str, float]:
        """Apply allocation constraints."""
        constrained = {}
        
        for strategy_id, weight in allocations.items():
            # Apply min/max constraints
            constrained_weight = max(
                self.constraints.min_allocation,
                min(self.constraints.max_allocation, weight)
            )
            
            if constrained_weight >= self.constraints.min_allocation:
                constrained[strategy_id] = constrained_weight
        
        return constrained
    
    def _should_rebalance(self, new_allocations: Dict[str, float]) -> bool:
        """Check if rebalancing is required based on threshold."""
        if not self.current_allocations:
            return True
        
        # Calculate maximum change in allocation
        max_change = 0.0
        all_strategies = set(self.current_allocations.keys()) | set(new_allocations.keys())
        
        for strategy_id in all_strategies:
            current = self.current_allocations.get(strategy_id, 0.0)
            new = new_allocations.get(strategy_id, 0.0)
            change = abs(new - current)
            max_change = max(max_change, change)
        
        return max_change >= self.constraints.rebalance_threshold
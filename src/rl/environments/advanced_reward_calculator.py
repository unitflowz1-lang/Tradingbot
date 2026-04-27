"""
Advanced Reward Calculator for RL Trading Environment

This module provides sophisticated multi-objective reward functions with
risk-adjusted components, transaction cost modeling, and adaptive reward shaping.
"""

print("DEBUG: Starting advanced_reward_calculator.py")

import numpy as np
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum
import warnings

print("DEBUG: About to import dependencies")

from ...models import MarketData
print("DEBUG: MarketData imported")

from .base import PortfolioState, EnvironmentConfig
print("DEBUG: Base imports done")

from .reward_calculator import RewardCalculator
print("DEBUG: RewardCalculator imported")


class RewardFunction(Enum):
    """Available reward function types."""
    SIMPLE_RETURN = "simple_return"
    SHARPE_ADJUSTED = "sharpe_adjusted"
    MULTI_OBJECTIVE = "multi_objective"


@dataclass
class AdvancedRewardConfig:
    """Advanced configuration for reward calculation."""
    reward_function: RewardFunction = RewardFunction.MULTI_OBJECTIVE
    profit_weight: float = 0.4
    risk_weight: float = 0.25
    consistency_weight: float = 0.15
    efficiency_weight: float = 0.1
    drawdown_weight: float = 0.1
    risk_free_rate: float = 0.02
    lookback_window: int = 50
    transaction_cost_penalty: float = 1.0
    spread_penalty_multiplier: float = 0.5
    reward_scaling: float = 100.0
    reward_clipping: bool = True
    max_reward: float = 10.0
    min_reward: float = -10.0
    adaptive_scaling: bool = True
    performance_window: int = 100
    scaling_factor: float = 1.0
    holding_time_reward: bool = True
    optimal_holding_periods: List[int] = None
    holding_reward_multiplier: float = 0.1
    
    def __post_init__(self):
        if self.optimal_holding_periods is None:
            self.optimal_holding_periods = [5, 10, 20]


class AdvancedRewardCalculator(RewardCalculator):
    """Advanced multi-objective reward calculator."""
    
    def __init__(self, env_config: EnvironmentConfig, reward_config: AdvancedRewardConfig = None):
        self.env_config = env_config
        self.reward_config = reward_config or AdvancedRewardConfig()
        self.performance_history = []
        self.return_history = []
        self.market_volatility = 0.01
        self.market_trend = 0.0
        self.position_entry_step = None
        self.current_scaling_factor = self.reward_config.scaling_factor
        
    def calculate_reward(self, prev_state: PortfolioState, current_state: PortfolioState,
                        action: int, market_data: MarketData) -> float:
        """Calculate advanced multi-objective reward."""
        # Update market conditions
        self._update_market_conditions(market_data)
        
        # Calculate base reward
        if self.reward_config.reward_function == RewardFunction.SIMPLE_RETURN:
            base_reward = self._calculate_simple_return_reward(prev_state, current_state)
        elif self.reward_config.reward_function == RewardFunction.SHARPE_ADJUSTED:
            base_reward = self._calculate_sharpe_adjusted_reward(prev_state, current_state)
        else:
            base_reward = self._calculate_multi_objective_reward(prev_state, current_state)
            
        # Apply penalties and bonuses
        transaction_penalty = self._calculate_transaction_costs(action, market_data)
        holding_reward = self._calculate_holding_time_reward(action, current_state)
        
        # Combine components
        total_reward = base_reward + transaction_penalty + holding_reward
        
        # Apply scaling and clipping
        if self.reward_config.adaptive_scaling:
            total_reward *= self.current_scaling_factor
        total_reward *= self.reward_config.reward_scaling
        
        if self.reward_config.reward_clipping:
            total_reward = np.clip(total_reward, self.reward_config.min_reward, self.reward_config.max_reward)
        
        # Update tracking
        self._update_performance_tracking(total_reward)
        
        return float(total_reward)
        
    def _calculate_simple_return_reward(self, prev_state: PortfolioState, current_state: PortfolioState) -> float:
        """Calculate simple return-based reward."""
        equity_change = current_state.equity - prev_state.equity
        return equity_change / self.env_config.initial_balance
        
    def _calculate_sharpe_adjusted_reward(self, prev_state: PortfolioState, current_state: PortfolioState) -> float:
        """Calculate Sharpe ratio adjusted reward."""
        equity_return = (current_state.equity - prev_state.equity) / prev_state.equity
        self.return_history.append(equity_return)
        
        if len(self.return_history) > self.reward_config.lookback_window:
            self.return_history.pop(0)
            
        if len(self.return_history) < 10:
            return equity_return
            
        returns = np.array(self.return_history)
        excess_returns = returns - (self.reward_config.risk_free_rate / 252)
        
        if np.std(excess_returns) == 0:
            return 0.0
        else:
            return np.mean(excess_returns) / np.std(excess_returns)
            
    def _calculate_multi_objective_reward(self, prev_state: PortfolioState, current_state: PortfolioState) -> float:
        """Calculate multi-objective reward."""
        # Profit component
        equity_change = current_state.equity - prev_state.equity
        profit_component = equity_change / self.env_config.initial_balance
        
        # Risk component
        risk_component = 0.0
        if len(self.return_history) >= 5:
            volatility = np.std(self.return_history[-5:])
            if volatility > 0:
                mean_return = np.mean(self.return_history[-5:])
                risk_component = mean_return / (1.0 + volatility * 10)
        
        # Consistency component
        consistency_component = 0.0
        if current_state.total_trades >= 2:
            win_rate = current_state.winning_trades / current_state.total_trades
            consistency_component = (win_rate - 0.5) * 2
        
        # Efficiency component
        efficiency_component = 0.0
        if current_state.total_trades > 0:
            total_profit = current_state.realized_pnl + current_state.unrealized_pnl
            profit_per_trade = total_profit / current_state.total_trades
            efficiency_component = profit_per_trade / self.env_config.initial_balance * 10
        
        # Drawdown component
        drawdown_change = current_state.current_drawdown - prev_state.current_drawdown
        drawdown_component = -drawdown_change * 5 if drawdown_change > 0 else -drawdown_change * 2
        
        # Weighted combination
        return (self.reward_config.profit_weight * profit_component +
                self.reward_config.risk_weight * risk_component +
                self.reward_config.consistency_weight * consistency_component +
                self.reward_config.efficiency_weight * efficiency_component +
                self.reward_config.drawdown_weight * drawdown_component)
        
    def _calculate_transaction_costs(self, action: int, market_data: MarketData) -> float:
        """Calculate transaction cost penalties."""
        from .base import ActionType
        action_type = ActionType(action)
        
        if action_type == ActionType.HOLD:
            return 0.0
            
        penalty = 0.0
        if action_type != ActionType.CLOSE_POSITION:
            penalty -= self.env_config.transaction_cost * self.reward_config.transaction_cost_penalty
            
        spread_penalty = (market_data.spread / market_data.close) * self.reward_config.spread_penalty_multiplier
        penalty -= spread_penalty
        
        return penalty
        
    def _calculate_holding_time_reward(self, action: int, current_state: PortfolioState) -> float:
        """Calculate holding time rewards."""
        if not self.reward_config.holding_time_reward:
            return 0.0
            
        from .base import ActionType
        action_type = ActionType(action)
        
        if abs(current_state.current_position) > 1e-6 and self.position_entry_step is None:
            self.position_entry_step = 0
            return 0.0
        elif abs(current_state.current_position) < 1e-6:
            self.position_entry_step = None
            return 0.0
            
        if self.position_entry_step is not None:
            self.position_entry_step += 1
            for optimal_period in self.reward_config.optimal_holding_periods:
                if self.position_entry_step == optimal_period:
                    return self.reward_config.holding_reward_multiplier
                    
        return 0.0
        
    def _update_market_conditions(self, market_data: MarketData) -> None:
        """Update market condition estimates."""
        if hasattr(self, '_prev_price'):
            price_change = abs(market_data.close - self._prev_price) / self._prev_price
            self.market_volatility = 0.9 * self.market_volatility + 0.1 * price_change
            trend = (market_data.close - self._prev_price) / self._prev_price
            self.market_trend = 0.9 * self.market_trend + 0.1 * trend
        self._prev_price = market_data.close
        
    def _update_performance_tracking(self, reward: float) -> None:
        """Update performance tracking."""
        self.performance_history.append(reward)
        if len(self.performance_history) > self.reward_config.performance_window:
            self.performance_history.pop(0)
            
        if self.reward_config.adaptive_scaling and len(self.performance_history) >= 20:
            recent_performance = np.mean(self.performance_history[-20:])
            if abs(recent_performance) < 0.1:
                self.current_scaling_factor *= 1.1
            elif abs(recent_performance) > 2.0:
                self.current_scaling_factor *= 0.9
            self.current_scaling_factor = np.clip(self.current_scaling_factor, 0.1, 10.0)
            
    def get_reward_breakdown(self, prev_state: PortfolioState, current_state: PortfolioState,
                           action: int, market_data: MarketData) -> Dict[str, float]:
        """Get detailed breakdown of reward components."""
        equity_change = current_state.equity - prev_state.equity
        breakdown = {
            'profit': equity_change / self.env_config.initial_balance,
            'transaction_costs': self._calculate_transaction_costs(action, market_data),
            'holding_time': self._calculate_holding_time_reward(action, current_state)
        }
        breakdown['total'] = sum(breakdown.values())
        return breakdown
        
    def reset(self) -> None:
        """Reset calculator state."""
        self.performance_history = []
        self.return_history = []
        self.position_entry_step = None
        self.current_scaling_factor = self.reward_config.scaling_factor
        self.market_volatility = 0.01
        self.market_trend = 0.0
        if hasattr(self, '_prev_price'):
            delattr(self, '_prev_price')
            
    def get_performance_metrics(self) -> Dict[str, float]:
        """Get performance metrics."""
        if not self.performance_history:
            return {}
        return {
            'mean_reward': np.mean(self.performance_history),
            'std_reward': np.std(self.performance_history),
            'min_reward': np.min(self.performance_history),
            'max_reward': np.max(self.performance_history),
            'total_rewards': len(self.performance_history),
            'current_scaling_factor': self.current_scaling_factor,
            'market_volatility': self.market_volatility,
            'market_trend': self.market_trend
        }
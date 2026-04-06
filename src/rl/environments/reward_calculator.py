"""
Reward Calculator for RL Trading Environment

This module contains the RewardCalculator class for computing
multi-objective rewards based on trading performance.
"""

from abc import ABC, abstractmethod
import numpy as np
from typing import Dict, Any
from dataclasses import dataclass

from ...models import MarketData
from .base import PortfolioState, EnvironmentConfig, ActionType


@dataclass
class RewardConfig:
    """Configuration for reward calculation."""
    pnl_weight: float = 1.0
    risk_weight: float = 0.3
    transaction_weight: float = 0.1
    drawdown_weight: float = 0.5
    consistency_weight: float = 0.2
    max_reward: float = 10.0
    min_reward: float = -10.0


class RewardCalculator(ABC):
    """Abstract base class for reward calculation."""
    
    @abstractmethod
    def calculate_reward(self, prev_state: PortfolioState, 
                        current_state: PortfolioState,
                        action: int, market_data: MarketData) -> float:
        """Calculate reward for the given state transition."""
        pass


class DefaultRewardCalculator(RewardCalculator):
    """
    Default multi-objective reward calculator.
    
    Combines profit/loss, risk-adjusted returns, transaction costs,
    and drawdown penalties into a single reward signal.
    """
    
    def __init__(self, env_config: EnvironmentConfig, reward_config: RewardConfig = None):
        self.env_config = env_config
        self.reward_config = reward_config or RewardConfig()
        
        # Track reward history for consistency calculation
        self.reward_history = []
        self.max_history_length = 100
        
    def calculate_reward(self, prev_state: PortfolioState, 
                        current_state: PortfolioState,
                        action: int, market_data: MarketData) -> float:
        """
        Calculate multi-objective reward.
        
        Args:
            prev_state: Previous portfolio state
            current_state: Current portfolio state
            action: Action taken
            market_data: Current market data
            
        Returns:
            Calculated reward value
        """
        reward_components = {}
        
        # 1. P&L-based reward
        pnl_reward = self._calculate_pnl_reward(prev_state, current_state)
        reward_components['pnl'] = pnl_reward
        
        # 2. Risk-adjusted reward
        risk_reward = self._calculate_risk_adjusted_reward(prev_state, current_state)
        reward_components['risk'] = risk_reward
        
        # 3. Transaction cost penalty
        transaction_penalty = self._calculate_transaction_penalty(action, market_data)
        reward_components['transaction'] = transaction_penalty
        
        # 4. Drawdown penalty
        drawdown_penalty = self._calculate_drawdown_penalty(prev_state, current_state)
        reward_components['drawdown'] = drawdown_penalty
        
        # 5. Consistency reward
        consistency_reward = self._calculate_consistency_reward(current_state)
        reward_components['consistency'] = consistency_reward
        
        # Combine components with weights
        total_reward = (
            self.reward_config.pnl_weight * pnl_reward +
            self.reward_config.risk_weight * risk_reward +
            self.reward_config.transaction_weight * transaction_penalty +
            self.reward_config.drawdown_weight * drawdown_penalty +
            self.reward_config.consistency_weight * consistency_reward
        )
        
        # Clip reward to bounds
        total_reward = np.clip(
            total_reward, 
            self.reward_config.min_reward, 
            self.reward_config.max_reward
        )
        
        # Store reward for consistency calculation
        self.reward_history.append(total_reward)
        if len(self.reward_history) > self.max_history_length:
            self.reward_history.pop(0)
            
        return float(total_reward)
        
    def _calculate_pnl_reward(self, prev_state: PortfolioState, 
                             current_state: PortfolioState) -> float:
        """Calculate reward based on P&L change."""
        # Calculate change in total equity
        equity_change = current_state.equity - prev_state.equity
        
        # Normalize by initial balance to make reward scale-invariant
        normalized_change = equity_change / self.env_config.initial_balance
        
        # Scale the reward (typical forex moves are small)
        scaled_reward = normalized_change * 1000  # Scale up for meaningful rewards
        
        return scaled_reward
        
    def _calculate_risk_adjusted_reward(self, prev_state: PortfolioState, 
                                      current_state: PortfolioState) -> float:
        """Calculate risk-adjusted reward component."""
        # Simple Sharpe-like adjustment
        equity_change = current_state.equity - prev_state.equity
        
        if len(self.reward_history) < 2:
            return 0.0
            
        # Calculate volatility of recent rewards
        recent_rewards = self.reward_history[-min(20, len(self.reward_history)):]
        reward_volatility = np.std(recent_rewards) if len(recent_rewards) > 1 else 1.0
        
        if reward_volatility == 0:
            return 0.0
            
        # Risk-adjusted return
        normalized_change = equity_change / self.env_config.initial_balance
        risk_adjusted = (normalized_change * 1000) / (reward_volatility + 1e-8)
        
        return np.clip(risk_adjusted, -2.0, 2.0)
        
    def _calculate_transaction_penalty(self, action: int, market_data: MarketData) -> float:
        """Calculate transaction cost penalty."""
        action_type = ActionType(action)
        
        # No penalty for holding
        if action_type == ActionType.HOLD:
            return 0.0
            
        # Small penalty for closing positions (risk management)
        if action_type == ActionType.CLOSE_POSITION:
            return -0.1
            
        # Penalty based on spread and transaction costs
        spread_penalty = market_data.spread / market_data.close
        transaction_penalty = self.env_config.transaction_cost
        
        total_penalty = -(spread_penalty + transaction_penalty) * 100
        
        return total_penalty
        
    def _calculate_drawdown_penalty(self, prev_state: PortfolioState, 
                                  current_state: PortfolioState) -> float:
        """Calculate drawdown penalty."""
        # Penalty for increasing drawdown
        drawdown_increase = current_state.current_drawdown - prev_state.current_drawdown
        
        if drawdown_increase > 0:
            # Exponential penalty for increasing drawdown
            penalty = -drawdown_increase * 10 * (1 + current_state.current_drawdown)
            return penalty
        else:
            # Small reward for reducing drawdown
            return -drawdown_increase * 2
            
    def _calculate_consistency_reward(self, current_state: PortfolioState) -> float:
        """Calculate consistency reward based on win rate and trade frequency."""
        if current_state.total_trades < 2:
            return 0.0
            
        # Reward for maintaining good win rate
        win_rate = current_state.winning_trades / current_state.total_trades
        win_rate_reward = (win_rate - 0.5) * 2  # Reward above 50% win rate
        
        # Slight penalty for overtrading (encourage quality over quantity)
        trade_frequency_penalty = 0.0
        if current_state.total_trades > 50:  # Arbitrary threshold
            trade_frequency_penalty = -0.1
            
        return win_rate_reward + trade_frequency_penalty
        
    def get_reward_breakdown(self, prev_state: PortfolioState, 
                           current_state: PortfolioState,
                           action: int, market_data: MarketData) -> Dict[str, float]:
        """
        Get detailed breakdown of reward components for analysis.
        
        Returns:
            Dictionary with individual reward components
        """
        breakdown = {}
        
        breakdown['pnl'] = self._calculate_pnl_reward(prev_state, current_state)
        breakdown['risk'] = self._calculate_risk_adjusted_reward(prev_state, current_state)
        breakdown['transaction'] = self._calculate_transaction_penalty(action, market_data)
        breakdown['drawdown'] = self._calculate_drawdown_penalty(prev_state, current_state)
        breakdown['consistency'] = self._calculate_consistency_reward(current_state)
        
        # Calculate weighted total
        breakdown['total'] = (
            self.reward_config.pnl_weight * breakdown['pnl'] +
            self.reward_config.risk_weight * breakdown['risk'] +
            self.reward_config.transaction_weight * breakdown['transaction'] +
            self.reward_config.drawdown_weight * breakdown['drawdown'] +
            self.reward_config.consistency_weight * breakdown['consistency']
        )
        
        return breakdown
        
    def reset(self) -> None:
        """Reset reward calculator state for new episode."""
        self.reward_history = []


class SharpeRewardCalculator(RewardCalculator):
    """
    Sharpe ratio-based reward calculator.
    
    Focuses primarily on risk-adjusted returns using Sharpe ratio calculation.
    """
    
    def __init__(self, env_config: EnvironmentConfig, lookback_window: int = 50):
        self.env_config = env_config
        self.lookback_window = lookback_window
        self.return_history = []
        
    def calculate_reward(self, prev_state: PortfolioState, 
                        current_state: PortfolioState,
                        action: int, market_data: MarketData) -> float:
        """Calculate Sharpe ratio-based reward."""
        # Calculate return
        equity_return = (current_state.equity - prev_state.equity) / prev_state.equity
        self.return_history.append(equity_return)
        
        # Keep only recent returns
        if len(self.return_history) > self.lookback_window:
            self.return_history.pop(0)
            
        # Need at least some history to calculate Sharpe ratio
        if len(self.return_history) < 10:
            return equity_return * 1000  # Simple return-based reward initially
            
        # Calculate Sharpe ratio
        mean_return = np.mean(self.return_history)
        std_return = np.std(self.return_history)
        
        if std_return == 0:
            sharpe_ratio = 0.0
        else:
            sharpe_ratio = mean_return / std_return
            
        # Scale Sharpe ratio for reward
        reward = sharpe_ratio * 10
        
        # Add transaction cost penalty
        if ActionType(action) != ActionType.HOLD:
            reward -= self.env_config.transaction_cost * 100
            
        return np.clip(reward, -10.0, 10.0)
        
    def reset(self) -> None:
        """Reset calculator state."""
        self.return_history = []


class SimpleReturnRewardCalculator(RewardCalculator):
    """
    Simple return-based reward calculator.
    
    Provides straightforward reward based on equity changes with transaction costs.
    """
    
    def __init__(self, env_config: EnvironmentConfig):
        self.env_config = env_config
        
    def calculate_reward(self, prev_state: PortfolioState, 
                        current_state: PortfolioState,
                        action: int, market_data: MarketData) -> float:
        """Calculate simple return-based reward."""
        # Basic P&L reward
        equity_change = current_state.equity - prev_state.equity
        pnl_reward = equity_change / self.env_config.initial_balance * 1000
        
        # Transaction cost penalty
        transaction_penalty = 0.0
        if ActionType(action) != ActionType.HOLD:
            transaction_penalty = -self.env_config.transaction_cost * 100
            
        # Drawdown penalty
        drawdown_penalty = 0.0
        if current_state.current_drawdown > prev_state.current_drawdown:
            drawdown_penalty = -(current_state.current_drawdown - prev_state.current_drawdown) * 10
            
        total_reward = pnl_reward + transaction_penalty + drawdown_penalty
        
        return np.clip(total_reward, -10.0, 10.0)
        
    def reset(self) -> None:
        """Reset calculator state."""
        pass


class AdvancedRewardCalculator(RewardCalculator):
    """
    Advanced multi-objective reward calculator with sophisticated risk adjustments.
    
    Provides comprehensive reward functions that consider profit, risk, consistency,
    efficiency, and market conditions for optimal RL agent training.
    """
    
    def __init__(self, env_config: EnvironmentConfig, 
                 profit_weight: float = 0.4,
                 risk_weight: float = 0.25,
                 consistency_weight: float = 0.15,
                 efficiency_weight: float = 0.1,
                 drawdown_weight: float = 0.1,
                 reward_scaling: float = 100.0,
                 adaptive_scaling: bool = True):
        """
        Initialize advanced reward calculator.
        
        Args:
            env_config: Environment configuration
            profit_weight: Weight for profit component
            risk_weight: Weight for risk component
            consistency_weight: Weight for consistency component
            efficiency_weight: Weight for efficiency component
            drawdown_weight: Weight for drawdown component
            reward_scaling: Scaling factor for rewards
            adaptive_scaling: Whether to use adaptive scaling
        """
        self.env_config = env_config
        self.profit_weight = profit_weight
        self.risk_weight = risk_weight
        self.consistency_weight = consistency_weight
        self.efficiency_weight = efficiency_weight
        self.drawdown_weight = drawdown_weight
        self.reward_scaling = reward_scaling
        self.adaptive_scaling = adaptive_scaling
        
        # Performance tracking
        self.performance_history = []
        self.return_history = []
        self.current_scaling_factor = 1.0
        
        # Market condition tracking
        self.market_volatility = 0.01
        self.market_trend = 0.0
        
    def calculate_reward(self, prev_state: PortfolioState, 
                        current_state: PortfolioState,
                        action: int, market_data: MarketData) -> float:
        """Calculate advanced multi-objective reward."""
        # Update market conditions
        self._update_market_conditions(market_data)
        
        # Calculate multi-objective reward components
        components = {}
        
        # 1. Profit component
        equity_change = current_state.equity - prev_state.equity
        components['profit'] = equity_change / self.env_config.initial_balance
        
        # 2. Risk component (Sharpe-like)
        components['risk'] = self._calculate_risk_component(current_state)
        
        # 3. Consistency component
        components['consistency'] = self._calculate_consistency_component(current_state)
        
        # 4. Efficiency component
        components['efficiency'] = self._calculate_efficiency_component(prev_state, current_state)
        
        # 5. Drawdown component
        components['drawdown'] = self._calculate_drawdown_component(prev_state, current_state)
        
        # Transaction cost penalty
        transaction_penalty = self._calculate_transaction_penalty(action, market_data)
        
        # Weighted combination
        base_reward = (
            self.profit_weight * components['profit'] +
            self.risk_weight * components['risk'] +
            self.consistency_weight * components['consistency'] +
            self.efficiency_weight * components['efficiency'] +
            self.drawdown_weight * components['drawdown']
        )
        
        total_reward = base_reward + transaction_penalty
        
        # Apply adaptive scaling
        if self.adaptive_scaling:
            total_reward *= self.current_scaling_factor
            
        # Apply reward scaling and clipping
        total_reward *= self.reward_scaling
        total_reward = np.clip(total_reward, -10.0, 10.0)
        
        # Update performance tracking
        self._update_performance_tracking(total_reward, prev_state, current_state)
        
        return float(total_reward)
        
    def _calculate_risk_component(self, current_state: PortfolioState) -> float:
        """Calculate risk-adjusted component."""
        if len(self.return_history) < 5:
            return 0.0
            
        # Calculate recent volatility
        recent_returns = self.return_history[-5:]
        volatility = np.std(recent_returns)
        
        # Risk-adjusted return (higher volatility = lower reward)
        if volatility == 0:
            return 0.0
            
        mean_return = np.mean(recent_returns)
        risk_adjusted = mean_return / (1.0 + volatility * 10)
        
        return risk_adjusted
        
    def _calculate_consistency_component(self, current_state: PortfolioState) -> float:
        """Calculate consistency component based on win rate."""
        if current_state.total_trades < 2:
            return 0.0
            
        # Win rate component
        win_rate = current_state.winning_trades / current_state.total_trades
        win_rate_score = (win_rate - 0.5) * 2  # Scale to [-1, 1]
        
        # Trade frequency penalty (discourage overtrading)
        trade_frequency_penalty = 0.0
        if current_state.total_trades > 100:
            trade_frequency_penalty = -0.1
            
        return win_rate_score + trade_frequency_penalty
        
    def _calculate_efficiency_component(self, prev_state: PortfolioState, 
                                      current_state: PortfolioState) -> float:
        """Calculate trading efficiency component."""
        if current_state.total_trades == 0:
            return 0.0
            
        # Profit per trade
        total_profit = current_state.realized_pnl + current_state.unrealized_pnl
        profit_per_trade = total_profit / current_state.total_trades
        
        # Normalize by initial balance
        efficiency = profit_per_trade / self.env_config.initial_balance
        
        return efficiency * 10  # Scale for reasonable range
        
    def _calculate_drawdown_component(self, prev_state: PortfolioState, 
                                    current_state: PortfolioState) -> float:
        """Calculate drawdown-based component."""
        # Penalty for increasing drawdown
        drawdown_change = current_state.current_drawdown - prev_state.current_drawdown
        
        if drawdown_change > 0:
            # Exponential penalty for increasing drawdown
            penalty = -drawdown_change * 5 * (1 + current_state.current_drawdown)
        else:
            # Small reward for reducing drawdown
            penalty = -drawdown_change * 2
            
        return penalty
        
    def _calculate_transaction_penalty(self, action: int, market_data: MarketData) -> float:
        """Calculate transaction cost penalties."""
        action_type = ActionType(action)
        
        # No penalty for holding
        if action_type == ActionType.HOLD:
            return 0.0
            
        penalty = 0.0
        
        # Base transaction cost
        if action_type != ActionType.CLOSE_POSITION:
            penalty -= self.env_config.transaction_cost * 100
            
        # Spread penalty
        spread_penalty = (market_data.spread / market_data.close) * 50
        penalty -= spread_penalty
        
        return penalty
        
    def _update_market_conditions(self, market_data: MarketData) -> None:
        """Update market condition estimates."""
        if hasattr(self, '_prev_price'):
            price_change = abs(market_data.close - self._prev_price) / self._prev_price
            self.market_volatility = 0.9 * self.market_volatility + 0.1 * price_change
            
            # Simple trend estimate
            trend = (market_data.close - self._prev_price) / self._prev_price
            self.market_trend = 0.9 * self.market_trend + 0.1 * trend
            
        self._prev_price = market_data.close
        
    def _update_performance_tracking(self, reward: float, 
                                   prev_state: PortfolioState, 
                                   current_state: PortfolioState) -> None:
        """Update performance tracking for adaptive scaling."""
        self.performance_history.append(reward)
        
        # Calculate return for risk component
        if prev_state.equity > 0:
            equity_return = (current_state.equity - prev_state.equity) / prev_state.equity
            self.return_history.append(equity_return)
        
        # Keep only recent history
        if len(self.performance_history) > 100:
            self.performance_history.pop(0)
        if len(self.return_history) > 50:
            self.return_history.pop(0)
            
        # Update adaptive scaling factor
        if self.adaptive_scaling and len(self.performance_history) >= 20:
            recent_performance = np.mean(self.performance_history[-20:])
            
            # Adjust scaling based on performance
            if abs(recent_performance) < 0.1:  # Very small rewards
                self.current_scaling_factor *= 1.05  # Increase scaling
            elif abs(recent_performance) > 2.0:  # Very large rewards
                self.current_scaling_factor *= 0.95  # Decrease scaling
                
            # Keep scaling factor in reasonable bounds
            self.current_scaling_factor = np.clip(self.current_scaling_factor, 0.1, 5.0)
            
    def get_reward_breakdown(self, prev_state: PortfolioState, 
                           current_state: PortfolioState,
                           action: int, market_data: MarketData) -> Dict[str, float]:
        """Get detailed breakdown of reward components for analysis."""
        breakdown = {}
        
        # Calculate each component separately
        equity_change = current_state.equity - prev_state.equity
        breakdown['profit'] = equity_change / self.env_config.initial_balance
        breakdown['risk'] = self._calculate_risk_component(current_state)
        breakdown['consistency'] = self._calculate_consistency_component(current_state)
        breakdown['efficiency'] = self._calculate_efficiency_component(prev_state, current_state)
        breakdown['drawdown'] = self._calculate_drawdown_component(prev_state, current_state)
        breakdown['transaction'] = self._calculate_transaction_penalty(action, market_data)
        
        # Calculate weighted total
        breakdown['weighted_total'] = (
            self.profit_weight * breakdown['profit'] +
            self.risk_weight * breakdown['risk'] +
            self.consistency_weight * breakdown['consistency'] +
            self.efficiency_weight * breakdown['efficiency'] +
            self.drawdown_weight * breakdown['drawdown'] +
            breakdown['transaction']
        )
        
        return breakdown
        
    def get_performance_metrics(self) -> Dict[str, float]:
        """Get performance metrics for analysis."""
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
        
    def reset(self) -> None:
        """Reset calculator state for new episode."""
        self.performance_history = []
        self.return_history = []
        self.current_scaling_factor = 1.0
        
        # Reset market condition tracking
        self.market_volatility = 0.01
        self.market_trend = 0.0
        if hasattr(self, '_prev_price'):
            delattr(self, '_prev_price')
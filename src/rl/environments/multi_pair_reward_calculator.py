"""
Multi-Pair Reward Calculator for RL Trading Environment

This module contains the reward calculator for multi-currency pair environments,
with diversification bonuses and cross-pair risk management.
"""

from typing import Dict, Any, List, Optional
import numpy as np
from datetime import datetime
import logging

from ...models import MarketData
from .base import PortfolioState
from .reward_calculator import RewardCalculator
from .multi_pair_environment import MultiPairEnvironmentConfig, MultiPairPortfolioState


logger = logging.getLogger(__name__)


class MultiPairRewardCalculator(RewardCalculator):
    """
    Reward calculator for multi-currency pair environments.
    
    Incorporates diversification benefits, cross-pair correlations,
    and currency-specific risk adjustments.
    """
    
    def __init__(self, config: MultiPairEnvironmentConfig):
        self.config = config
        self.currency_pairs = config.currency_pairs
        
        # Multi-pair reward weights
        self.pnl_weight = 1.0
        self.diversification_weight = 0.3
        self.correlation_risk_weight = -0.2
        self.volatility_weight = -0.1
        self.transaction_cost_weight = -0.5
        self.drawdown_weight = -1.0
        self.exposure_limit_weight = -0.5
        
        # Risk parameters
        self.max_correlation_penalty = 0.8  # Maximum correlation before penalty
        self.max_total_exposure = config.max_position_size * len(config.currency_pairs)
        self.target_diversification = 0.7  # Target diversification score
        
        logger.info(f"Initialized multi-pair reward calculator for {len(self.currency_pairs)} pairs")
        
    def calculate_reward(self, 
                        prev_portfolio: MultiPairPortfolioState,
                        current_portfolio: MultiPairPortfolioState,
                        action: int,
                        market_data: Dict[str, MarketData]) -> float:
        """
        Calculate multi-pair reward incorporating diversification and correlation effects.
        
        Args:
            prev_portfolio: Previous portfolio state
            current_portfolio: Current portfolio state
            action: Action taken (encoded multi-pair action)
            market_data: Current market data for all pairs
            
        Returns:
            Calculated reward value
        """
        try:
            # 1. Base P&L reward
            pnl_reward = self._calculate_pnl_reward(prev_portfolio, current_portfolio)
            
            # 2. Diversification bonus
            diversification_reward = self._calculate_diversification_reward(current_portfolio)
            
            # 3. Correlation risk penalty
            correlation_penalty = self._calculate_correlation_risk_penalty(
                current_portfolio, market_data
            )
            
            # 4. Volatility-adjusted reward
            volatility_adjustment = self._calculate_volatility_adjustment(
                current_portfolio, market_data
            )
            
            # 5. Transaction cost penalty
            transaction_penalty = self._calculate_transaction_cost_penalty(
                prev_portfolio, current_portfolio
            )
            
            # 6. Drawdown penalty
            drawdown_penalty = self._calculate_drawdown_penalty(current_portfolio)
            
            # 7. Exposure limit penalty
            exposure_penalty = self._calculate_exposure_limit_penalty(current_portfolio)
            
            # Combine all components
            total_reward = (
                self.pnl_weight * pnl_reward +
                self.diversification_weight * diversification_reward +
                self.correlation_risk_weight * correlation_penalty +
                self.volatility_weight * volatility_adjustment +
                self.transaction_cost_weight * transaction_penalty +
                self.drawdown_weight * drawdown_penalty +
                self.exposure_limit_weight * exposure_penalty
            )
            
            # Clip reward to reasonable range
            total_reward = np.clip(total_reward, -10.0, 10.0)
            
            return total_reward
            
        except Exception as e:
            logger.error(f"Error calculating multi-pair reward: {e}")
            return 0.0
            
    def _calculate_pnl_reward(self, 
                            prev_portfolio: MultiPairPortfolioState,
                            current_portfolio: MultiPairPortfolioState) -> float:
        """Calculate P&L-based reward component."""
        # Calculate change in total P&L
        prev_total_pnl = prev_portfolio.realized_pnl + prev_portfolio.unrealized_pnl
        current_total_pnl = current_portfolio.realized_pnl + current_portfolio.unrealized_pnl
        
        pnl_change = current_total_pnl - prev_total_pnl
        
        # Normalize by account balance
        if current_portfolio.balance > 0:
            normalized_pnl = pnl_change / current_portfolio.balance
        else:
            normalized_pnl = 0.0
            
        # Apply risk adjustment based on position size
        total_exposure = current_portfolio.get_total_position_exposure()
        if total_exposure > 0:
            risk_adjusted_pnl = normalized_pnl / (1.0 + total_exposure)
        else:
            risk_adjusted_pnl = normalized_pnl
            
        return risk_adjusted_pnl
        
    def _calculate_diversification_reward(self, portfolio: MultiPairPortfolioState) -> float:
        """Calculate diversification bonus."""
        diversification_score = portfolio.get_diversification_score()
        
        # Reward for maintaining good diversification
        if diversification_score >= self.target_diversification:
            return (diversification_score - self.target_diversification) * 2.0
        else:
            # Penalty for poor diversification
            return (diversification_score - self.target_diversification) * 1.0
            
    def _calculate_correlation_risk_penalty(self, 
                                          portfolio: MultiPairPortfolioState,
                                          market_data: Dict[str, MarketData]) -> float:
        """Calculate penalty for high correlation risk."""
        # Calculate correlation-weighted position risk
        correlation_risk = 0.0
        
        # Get current positions
        positions = {}
        for pair in self.currency_pairs:
            positions[pair] = portfolio.pair_positions.get(pair, 0.0)
            
        # Calculate pairwise correlation risk
        for i, pair1 in enumerate(self.currency_pairs):
            for j, pair2 in enumerate(self.currency_pairs):
                if i < j:  # Avoid double counting
                    pos1 = positions[pair1]
                    pos2 = positions[pair2]
                    
                    # Estimate correlation (simplified - could use actual correlation matrix)
                    estimated_corr = self._estimate_pair_correlation(pair1, pair2, market_data)
                    
                    # Calculate correlation risk
                    if abs(estimated_corr) > self.max_correlation_penalty:
                        # Penalty for high correlation with same-direction positions
                        if (pos1 > 0 and pos2 > 0) or (pos1 < 0 and pos2 < 0):
                            correlation_risk += abs(estimated_corr) * abs(pos1) * abs(pos2)
                            
        return -correlation_risk  # Negative because it's a penalty
        
    def _calculate_volatility_adjustment(self, 
                                       portfolio: MultiPairPortfolioState,
                                       market_data: Dict[str, MarketData]) -> float:
        """Calculate volatility-based reward adjustment."""
        volatility_adjustment = 0.0
        
        for pair in self.currency_pairs:
            position = portfolio.pair_positions.get(pair, 0.0)
            
            if abs(position) > 1e-6 and pair in market_data:
                # Estimate current volatility from spread
                current_data = market_data[pair]
                estimated_volatility = current_data.spread / current_data.close
                
                # Reward for taking positions in low volatility environments
                # Penalty for excessive positions in high volatility
                if estimated_volatility > 0.001:  # 0.1% spread threshold
                    volatility_penalty = abs(position) * estimated_volatility * 100
                    volatility_adjustment -= volatility_penalty
                    
        return volatility_adjustment
        
    def _calculate_transaction_cost_penalty(self, 
                                          prev_portfolio: MultiPairPortfolioState,
                                          current_portfolio: MultiPairPortfolioState) -> float:
        """Calculate transaction cost penalty."""
        total_cost = 0.0
        
        for pair in self.currency_pairs:
            prev_pos = prev_portfolio.pair_positions.get(pair, 0.0)
            current_pos = current_portfolio.pair_positions.get(pair, 0.0)
            
            position_change = abs(current_pos - prev_pos)
            
            if position_change > 1e-6:
                # Calculate transaction cost
                pair_weight = self.config.pair_weights.get(pair, 1.0)
                cost = position_change * self.config.transaction_cost * pair_weight
                total_cost += cost
                
        return -total_cost  # Negative because it's a cost
        
    def _calculate_drawdown_penalty(self, portfolio: MultiPairPortfolioState) -> float:
        """Calculate drawdown-based penalty."""
        current_drawdown = portfolio.current_drawdown
        
        # Progressive penalty for increasing drawdown
        if current_drawdown < 0.05:  # Less than 5%
            return 0.0
        elif current_drawdown < 0.10:  # 5-10%
            return -(current_drawdown - 0.05) * 10.0
        elif current_drawdown < 0.20:  # 10-20%
            return -0.5 - (current_drawdown - 0.10) * 20.0
        else:  # More than 20%
            return -2.5 - (current_drawdown - 0.20) * 50.0
            
    def _calculate_exposure_limit_penalty(self, portfolio: MultiPairPortfolioState) -> float:
        """Calculate penalty for excessive total exposure."""
        total_exposure = portfolio.get_total_position_exposure()
        
        if total_exposure <= self.max_total_exposure:
            return 0.0
        else:
            # Progressive penalty for exceeding exposure limits
            excess_exposure = total_exposure - self.max_total_exposure
            return -excess_exposure * 5.0  # Strong penalty
            
    def _estimate_pair_correlation(self, 
                                 pair1: str, 
                                 pair2: str, 
                                 market_data: Dict[str, MarketData]) -> float:
        """Estimate correlation between two currency pairs."""
        try:
            # Simple correlation estimation based on currency overlap
            base1, quote1 = pair1.split('/')
            base2, quote2 = pair2.split('/')
            
            # High correlation if same base or quote currency
            if base1 == base2 or quote1 == quote2:
                return 0.7
            elif base1 == quote2 or quote1 == base2:
                return -0.7  # Inverse correlation
            else:
                # Check for common major currencies
                major_currencies = {'USD', 'EUR', 'GBP', 'JPY'}
                
                pair1_majors = {base1, quote1} & major_currencies
                pair2_majors = {base2, quote2} & major_currencies
                
                if len(pair1_majors & pair2_majors) > 0:
                    return 0.3  # Moderate correlation through major currencies
                else:
                    return 0.1  # Low correlation
                    
        except Exception as e:
            logger.warning(f"Error estimating correlation between {pair1} and {pair2}: {e}")
            return 0.0
            
    def get_reward_breakdown(self, 
                           prev_portfolio: MultiPairPortfolioState,
                           current_portfolio: MultiPairPortfolioState,
                           action: int,
                           market_data: Dict[str, MarketData]) -> Dict[str, float]:
        """Get detailed breakdown of reward components."""
        try:
            breakdown = {}
            
            breakdown['pnl_reward'] = self._calculate_pnl_reward(prev_portfolio, current_portfolio)
            breakdown['diversification_reward'] = self._calculate_diversification_reward(current_portfolio)
            breakdown['correlation_penalty'] = self._calculate_correlation_risk_penalty(current_portfolio, market_data)
            breakdown['volatility_adjustment'] = self._calculate_volatility_adjustment(current_portfolio, market_data)
            breakdown['transaction_penalty'] = self._calculate_transaction_cost_penalty(prev_portfolio, current_portfolio)
            breakdown['drawdown_penalty'] = self._calculate_drawdown_penalty(current_portfolio)
            breakdown['exposure_penalty'] = self._calculate_exposure_limit_penalty(current_portfolio)
            
            # Calculate total
            breakdown['total_reward'] = (
                self.pnl_weight * breakdown['pnl_reward'] +
                self.diversification_weight * breakdown['diversification_reward'] +
                self.correlation_risk_weight * breakdown['correlation_penalty'] +
                self.volatility_weight * breakdown['volatility_adjustment'] +
                self.transaction_cost_weight * breakdown['transaction_penalty'] +
                self.drawdown_weight * breakdown['drawdown_penalty'] +
                self.exposure_limit_weight * breakdown['exposure_penalty']
            )
            
            return breakdown
            
        except Exception as e:
            logger.error(f"Error calculating reward breakdown: {e}")
            return {'total_reward': 0.0}
            
    def update_reward_weights(self, **kwargs) -> None:
        """Update reward component weights."""
        for key, value in kwargs.items():
            if hasattr(self, f"{key}_weight"):
                setattr(self, f"{key}_weight", value)
                logger.info(f"Updated {key}_weight to {value}")
            else:
                logger.warning(f"Unknown reward weight: {key}")
                
    def get_reward_config(self) -> Dict[str, float]:
        """Get current reward configuration."""
        return {
            'pnl_weight': self.pnl_weight,
            'diversification_weight': self.diversification_weight,
            'correlation_risk_weight': self.correlation_risk_weight,
            'volatility_weight': self.volatility_weight,
            'transaction_cost_weight': self.transaction_cost_weight,
            'drawdown_weight': self.drawdown_weight,
            'exposure_limit_weight': self.exposure_limit_weight,
            'max_correlation_penalty': self.max_correlation_penalty,
            'max_total_exposure': self.max_total_exposure,
            'target_diversification': self.target_diversification
        }
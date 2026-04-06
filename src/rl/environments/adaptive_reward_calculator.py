"""
Adaptive Reward Calculator for Market Regime Awareness

This module implements reward functions that adapt based on market sessions,
volatility regimes, and trend conditions.
"""

import numpy as np
from typing import Dict, Any, List, Optional, Tuple
import logging
from datetime import datetime

from ...models import MarketData
from .base import PortfolioState
from .reward_calculator import RewardCalculator
from .multi_pair_environment import MultiPairEnvironmentConfig, MultiPairPortfolioState
from .market_regime_detector import (
    MarketRegimeDetector, 
    MarketRegime, 
    TradingSession, 
    VolatilityRegime, 
    TrendRegime
)


logger = logging.getLogger(__name__)


class AdaptiveRewardCalculator(RewardCalculator):
    """
    Reward calculator that adapts based on market regimes.
    
    Adjusts reward functions based on:
    - Trading session (different sessions have different characteristics)
    - Volatility regime (high/low volatility requires different strategies)
    - Trend regime (trending vs sideways markets)
    """
    
    def __init__(self, config: MultiPairEnvironmentConfig):
        self.config = config
        self.regime_detector = MarketRegimeDetector()
        
        # Base reward weights
        self.base_weights = {
            'pnl': 1.0,
            'sharpe': 0.5,
            'drawdown': -1.0,
            'transaction_cost': -0.3,
            'position_consistency': 0.2,
            'regime_adaptation': 0.4,
            'exit_quality': 0.5,
            'regret_penalty': 0.8,
            'opportunity_cost_penalty': 1.0  # Penalty for entering low-quality trades
        }
        
        # Session-specific adjustments
        self.session_adjustments = {
            TradingSession.LONDON: {
                'pnl': 1.1,           # Higher reward for profits in active session
                'transaction_cost': -0.2,  # Lower penalty for transaction costs
                'volatility_bonus': 0.1
            },
            TradingSession.NEW_YORK: {
                'pnl': 1.1,
                'transaction_cost': -0.2,
                'volatility_bonus': 0.1
            },
            TradingSession.OVERLAP_LONDON_NY: {
                'pnl': 1.2,           # Highest reward during most active period
                'transaction_cost': -0.1,
                'volatility_bonus': 0.2
            },
            TradingSession.TOKYO: {
                'pnl': 1.0,
                'transaction_cost': -0.3,
                'volatility_bonus': 0.05
            },
            TradingSession.SYDNEY: {
                'pnl': 0.9,
                'transaction_cost': -0.4,
                'volatility_bonus': 0.0
            },
            TradingSession.QUIET: {
                'pnl': 0.8,           # Lower reward during quiet periods
                'transaction_cost': -0.5,  # Higher penalty for unnecessary trading
                'inactivity_bonus': 0.1    # Bonus for not trading when inappropriate
            }
        }
        
        # Volatility regime adjustments
        self.volatility_adjustments = {
            VolatilityRegime.LOW: {
                'pnl_multiplier': 1.2,     # Higher reward for profits in low vol
                'risk_penalty': -0.5,      # Lower risk penalty
                'position_size_bonus': 0.1  # Bonus for larger positions in low vol
            },
            VolatilityRegime.NORMAL: {
                'pnl_multiplier': 1.0,
                'risk_penalty': -1.0,
                'position_size_bonus': 0.0
            },
            VolatilityRegime.HIGH: {
                'pnl_multiplier': 0.9,     # Lower reward multiplier in high vol
                'risk_penalty': -1.5,      # Higher risk penalty
                'position_size_penalty': -0.2  # Penalty for large positions in high vol
            },
            VolatilityRegime.EXTREME: {
                'pnl_multiplier': 0.7,     # Much lower reward in extreme vol
                'risk_penalty': -2.0,      # Very high risk penalty
                'position_size_penalty': -0.5,  # Strong penalty for large positions
                'safety_bonus': 0.3        # Bonus for conservative behavior
            }
        }
        
        # Trend regime adjustments
        self.trend_adjustments = {
            TrendRegime.STRONG_UPTREND: {
                'long_bias_bonus': 0.2,    # Bonus for long positions in uptrend
                'trend_following_bonus': 0.15,
                'counter_trend_penalty': -0.3
            },
            TrendRegime.WEAK_UPTREND: {
                'long_bias_bonus': 0.1,
                'trend_following_bonus': 0.05,
                'counter_trend_penalty': -0.1
            },
            TrendRegime.SIDEWAYS: {
                'mean_reversion_bonus': 0.1,  # Bonus for mean reversion in sideways
                'range_trading_bonus': 0.05,
                'breakout_penalty': -0.1
            },
            TrendRegime.WEAK_DOWNTREND: {
                'short_bias_bonus': 0.1,
                'trend_following_bonus': 0.05,
                'counter_trend_penalty': -0.1
            },
            TrendRegime.STRONG_DOWNTREND: {
                'short_bias_bonus': 0.2,
                'trend_following_bonus': 0.15,
                'counter_trend_penalty': -0.3
            }
        }
        
        logger.info("Initialized adaptive reward calculator with regime-based adjustments")
        
    def calculate_reward(self, 
                        prev_portfolio: PortfolioState,
                        current_portfolio: PortfolioState,
                        action: int,
                        market_data: Any) -> float:
        """
        Calculate adaptive reward based on current market regime.
        
        Args:
            prev_portfolio: Previous portfolio state
            current_portfolio: Current portfolio state
            action: Action taken
            market_data: Current market data (can be single or dict for multi-pair)
            
        Returns:
            Calculated reward value
        """
        try:
            # Update regime detector with market data
            if isinstance(market_data, dict):
                # Multi-pair case - use first available pair
                for pair, data in market_data.items():
                    if data is not None:
                        current_regime = self.regime_detector.update(data, pair)
                        break
                else:
                    # No valid market data
                    return 0.0
            else:
                # Single pair case
                current_regime = self.regime_detector.update(market_data)
                
            # Calculate base reward components
            base_reward = self._calculate_base_reward(prev_portfolio, current_portfolio, action)
            
            # Apply regime-based adjustments
            adjusted_reward = self._apply_regime_adjustments(
                base_reward, current_regime, prev_portfolio, current_portfolio, action
            )
            
            # Add regime-specific bonuses/penalties
            regime_bonus = self._calculate_regime_bonus(
                current_regime, prev_portfolio, current_portfolio, action
            )
            
            total_reward = adjusted_reward + regime_bonus
            
            # Clip to reasonable range
            total_reward = np.clip(total_reward, -5.0, 5.0)
            
            return total_reward
            
        except Exception as e:
            logger.error(f"Error calculating adaptive reward: {e}")
            return 0.0
            
    def _calculate_base_reward(self, 
                             prev_portfolio: PortfolioState,
                             current_portfolio: PortfolioState,
                             action: int) -> Dict[str, float]:
        """Calculate base reward components."""
        # P&L component
        pnl_change = (current_portfolio.realized_pnl + current_portfolio.unrealized_pnl) - \
                    (prev_portfolio.realized_pnl + prev_portfolio.unrealized_pnl)
        
        if current_portfolio.balance > 0:
            pnl_reward = pnl_change / current_portfolio.balance
        else:
            pnl_reward = 0.0
            
        # Sharpe ratio component (simplified)
        if hasattr(current_portfolio, 'equity'):
            returns = (current_portfolio.equity - prev_portfolio.equity) / max(prev_portfolio.equity, 1.0)
            sharpe_reward = returns  # Simplified - would need return history for true Sharpe
        else:
            sharpe_reward = pnl_reward
            
        # Drawdown penalty
        drawdown_penalty = -current_portfolio.current_drawdown
        
        # Transaction cost penalty
        position_change = abs(current_portfolio.current_position - prev_portfolio.current_position)
        transaction_penalty = -position_change * self.config.transaction_cost
        
        # Position consistency reward (avoid excessive position changes)
        consistency_reward = -abs(position_change) * 0.1
        
        # Exit Quality Reward (Exit Attribution)
        exit_quality_reward = 0.0
        # Check if position reduced (exit)
        if hasattr(prev_portfolio, 'mfe') and abs(prev_portfolio.current_position) > 0 and abs(current_portfolio.current_position) < abs(prev_portfolio.current_position):
            realized_change = current_portfolio.realized_pnl - prev_portfolio.realized_pnl
            trade_mfe = prev_portfolio.mfe
            
            # Use MFE from prev state (peak profit during trade)
            if trade_mfe > 0:
                # Calculate how much of the peak profit we captured
                capture_ratio = realized_change / trade_mfe
                
                # Penalize early trailing exits that gave back too much (low capture)
                if capture_ratio < 0.5:
                    # Penalty increases as capture ratio drops
                    # giving back 50% = -0.1, giving back 100% (breakeven) = -0.25, loss = worse
                    exit_quality_reward -= 0.5 * (1.0 - capture_ratio)
                
                # Reward efficient TP hits (high capture)
                elif capture_ratio > 0.85:
                    # Bonus for capturing >85% of the move
                    exit_quality_reward += 0.5 * capture_ratio
                    
        # Regret Penalty (from ML/Exit Analysis)
        regret_penalty = 0.0
        if hasattr(current_portfolio, 'last_regret') and current_portfolio.last_regret > 0:
            # Penalty proportional to regret (R-multiples left on table)
            # Cap penalty to avoid destabilizing learning
            regret_penalty = -min(current_portfolio.last_regret * 0.5, 2.0)
        
        # Opportunity Cost Penalty (from Trade Admission)
        opportunity_cost_penalty = 0.0
        if hasattr(current_portfolio, 'opportunity_cost_regret') and current_portfolio.opportunity_cost_regret > 0:
            # Penalty for entering low-quality trades when better opportunities exist
            # This teaches the agent to wait for high-percentile setups
            opportunity_cost_penalty = -min(current_portfolio.opportunity_cost_regret * 0.75, 1.5)

        return {
            'pnl': pnl_reward,
            'sharpe': sharpe_reward,
            'drawdown': drawdown_penalty,
            'transaction_cost': transaction_penalty,
            'position_consistency': consistency_reward,
            'exit_quality': exit_quality_reward,
            'regret_penalty': regret_penalty,
            'opportunity_cost_penalty': opportunity_cost_penalty
        }
        
    def _apply_regime_adjustments(self, 
                                base_reward: Dict[str, float],
                                regime: MarketRegime,
                                prev_portfolio: PortfolioState,
                                current_portfolio: PortfolioState,
                                action: int) -> float:
        """Apply regime-based adjustments to base reward."""
        adjusted_reward = 0.0
        
        # Get session adjustments
        session_adj = self.session_adjustments.get(regime.current_session, {})
        
        # Get volatility adjustments
        vol_adj = self.volatility_adjustments.get(regime.volatility_regime, {})
        
        # Apply base weights with session and volatility adjustments
        for component, base_value in base_reward.items():
            weight = self.base_weights.get(component, 1.0)
            
            # Apply session adjustment
            if component in session_adj:
                weight *= session_adj[component]
                
            # Apply volatility adjustment
            if component == 'pnl' and 'pnl_multiplier' in vol_adj:
                weight *= vol_adj['pnl_multiplier']
                
            adjusted_reward += weight * base_value
            
        return adjusted_reward
        
    def _calculate_regime_bonus(self, 
                              regime: MarketRegime,
                              prev_portfolio: PortfolioState,
                              current_portfolio: PortfolioState,
                              action: int) -> float:
        """Calculate regime-specific bonuses and penalties."""
        bonus = 0.0
        
        # Session-specific bonuses
        bonus += self._calculate_session_bonus(regime, prev_portfolio, current_portfolio, action)
        
        # Volatility regime bonuses
        bonus += self._calculate_volatility_bonus(regime, prev_portfolio, current_portfolio, action)
        
        # Trend regime bonuses
        bonus += self._calculate_trend_bonus(regime, prev_portfolio, current_portfolio, action)
        
        # Regime confidence bonus
        bonus += regime.regime_confidence * 0.1  # Small bonus for high confidence regimes
        
        return bonus
        
    def _calculate_session_bonus(self, 
                               regime: MarketRegime,
                               prev_portfolio: PortfolioState,
                               current_portfolio: PortfolioState,
                               action: int) -> float:
        """Calculate session-specific bonuses."""
        session_adj = self.session_adjustments.get(regime.current_session, {})
        bonus = 0.0
        
        # Volatility bonus during active sessions
        if 'volatility_bonus' in session_adj:
            # Reward for taking advantage of volatility
            position_change = abs(current_portfolio.current_position - prev_portfolio.current_position)
            if position_change > 0.01:  # Significant position change
                bonus += session_adj['volatility_bonus']
                
        # Inactivity bonus during quiet sessions
        if 'inactivity_bonus' in session_adj:
            # Reward for not trading during inappropriate times
            position_change = abs(current_portfolio.current_position - prev_portfolio.current_position)
            if position_change < 0.01:  # Minimal position change
                bonus += session_adj['inactivity_bonus']
                
        return bonus
        
    def _calculate_volatility_bonus(self, 
                                  regime: MarketRegime,
                                  prev_portfolio: PortfolioState,
                                  current_portfolio: PortfolioState,
                                  action: int) -> float:
        """Calculate volatility regime bonuses."""
        vol_adj = self.volatility_adjustments.get(regime.volatility_regime, {})
        bonus = 0.0
        
        current_position = abs(current_portfolio.current_position)
        
        # Position size bonuses/penalties
        if 'position_size_bonus' in vol_adj:
            # Bonus for appropriate position sizing in low volatility
            if current_position > 0.5:  # Large position
                bonus += vol_adj['position_size_bonus']
                
        if 'position_size_penalty' in vol_adj:
            # Penalty for large positions in high volatility
            if current_position > 0.3:  # Moderate to large position
                bonus += vol_adj['position_size_penalty'] * current_position
                
        # Safety bonus in extreme volatility
        if 'safety_bonus' in vol_adj:
            # Bonus for conservative behavior in extreme conditions
            if current_position < 0.2:  # Small position
                bonus += vol_adj['safety_bonus']
                
        return bonus
        
    def _calculate_trend_bonus(self, 
                             regime: MarketRegime,
                             prev_portfolio: PortfolioState,
                             current_portfolio: PortfolioState,
                             action: int) -> float:
        """Calculate trend regime bonuses."""
        trend_adj = self.trend_adjustments.get(regime.trend_regime, {})
        bonus = 0.0
        
        current_position = current_portfolio.current_position
        
        # Long bias bonus in uptrends
        if 'long_bias_bonus' in trend_adj and current_position > 0:
            bonus += trend_adj['long_bias_bonus'] * current_position
            
        # Short bias bonus in downtrends
        if 'short_bias_bonus' in trend_adj and current_position < 0:
            bonus += trend_adj['short_bias_bonus'] * abs(current_position)
            
        # Trend following bonus
        if 'trend_following_bonus' in trend_adj:
            # Bonus for positions aligned with trend
            if ((regime.trend_regime in [TrendRegime.STRONG_UPTREND, TrendRegime.WEAK_UPTREND] and current_position > 0) or
                (regime.trend_regime in [TrendRegime.STRONG_DOWNTREND, TrendRegime.WEAK_DOWNTREND] and current_position < 0)):
                bonus += trend_adj['trend_following_bonus'] * abs(current_position)
                
        # Counter-trend penalty
        if 'counter_trend_penalty' in trend_adj:
            # Penalty for positions against strong trends
            if ((regime.trend_regime in [TrendRegime.STRONG_UPTREND, TrendRegime.WEAK_UPTREND] and current_position < 0) or
                (regime.trend_regime in [TrendRegime.STRONG_DOWNTREND, TrendRegime.WEAK_DOWNTREND] and current_position > 0)):
                bonus += trend_adj['counter_trend_penalty'] * abs(current_position)
                
        # Mean reversion bonus in sideways markets
        if 'mean_reversion_bonus' in trend_adj:
            # This would require more sophisticated logic to detect mean reversion
            # For now, just give small bonus for any trading in sideways markets
            if abs(current_position) > 0:
                bonus += trend_adj['mean_reversion_bonus'] * 0.5
                
        return bonus
        
    def get_regime_info(self) -> Dict[str, Any]:
        """Get current regime information."""
        return self.regime_detector.get_regime_summary()
        
    def get_reward_breakdown(self, 
                           prev_portfolio: PortfolioState,
                           current_portfolio: PortfolioState,
                           action: int,
                           market_data: Any) -> Dict[str, float]:
        """Get detailed breakdown of reward components."""
        try:
            # Update regime
            if isinstance(market_data, dict):
                for pair, data in market_data.items():
                    if data is not None:
                        current_regime = self.regime_detector.update(data, pair)
                        break
                else:
                    current_regime = self.regime_detector.current_regime
            else:
                current_regime = self.regime_detector.update(market_data)
                
            # Calculate components
            base_reward = self._calculate_base_reward(prev_portfolio, current_portfolio, action)
            adjusted_reward = self._apply_regime_adjustments(
                base_reward, current_regime, prev_portfolio, current_portfolio, action
            )
            regime_bonus = self._calculate_regime_bonus(
                current_regime, prev_portfolio, current_portfolio, action
            )
            
            # Create breakdown
            breakdown = base_reward.copy()
            breakdown['adjusted_total'] = adjusted_reward
            breakdown['regime_bonus'] = regime_bonus
            breakdown['final_reward'] = adjusted_reward + regime_bonus
            
            # Add regime information
            breakdown['current_session'] = current_regime.current_session.value
            breakdown['volatility_regime'] = current_regime.volatility_regime.value
            breakdown['trend_regime'] = current_regime.trend_regime.value
            breakdown['regime_confidence'] = current_regime.regime_confidence
            
            return breakdown
            
        except Exception as e:
            logger.error(f"Error calculating reward breakdown: {e}")
            return {'final_reward': 0.0}
            
    def update_reward_weights(self, **kwargs) -> None:
        """Update reward weights and adjustments."""
        # Update base weights
        for key, value in kwargs.items():
            if key in self.base_weights:
                self.base_weights[key] = value
                logger.info(f"Updated base weight {key} to {value}")
                
        # Update session adjustments
        if 'session_adjustments' in kwargs:
            self.session_adjustments.update(kwargs['session_adjustments'])
            logger.info("Updated session adjustments")
            
        # Update volatility adjustments
        if 'volatility_adjustments' in kwargs:
            self.volatility_adjustments.update(kwargs['volatility_adjustments'])
            logger.info("Updated volatility adjustments")
            
        # Update trend adjustments
        if 'trend_adjustments' in kwargs:
            self.trend_adjustments.update(kwargs['trend_adjustments'])
            logger.info("Updated trend adjustments")
            
    def get_adaptive_config(self) -> Dict[str, Any]:
        """Get current adaptive reward configuration."""
        return {
            'base_weights': self.base_weights,
            'session_adjustments': {k.value: v for k, v in self.session_adjustments.items()},
            'volatility_adjustments': {k.value: v for k, v in self.volatility_adjustments.items()},
            'trend_adjustments': {k.value: v for k, v in self.trend_adjustments.items()},
            'current_regime': self.regime_detector.get_regime_summary()
        }
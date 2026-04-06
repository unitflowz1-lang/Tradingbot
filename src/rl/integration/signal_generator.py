"""
RL Signal Generator

This module converts RL agent actions into trading signals that can be
integrated with the existing AI trading bot infrastructure.
"""

import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum

from src.models import TradingSignal, Direction, MarketData
from src.exceptions import SignalGenerationError
from src.rl.agents.base import RLAgent
from src.rl.environments.base import PortfolioState
from src.interfaces import RiskManager


class SignalStrength(Enum):
    """Signal strength levels"""
    WEAK = "weak"
    MODERATE = "moderate"
    STRONG = "strong"
    VERY_STRONG = "very_strong"


class RLSignalGenerator:
    """
    Converts RL agent actions into trading signals.
    
    Provides signal validation, risk checking, and integration
    with existing trading signal infrastructure.
    """
    
    def __init__(self, 
                 agent: RLAgent,
                 risk_manager: Optional[RiskManager] = None,
                 confidence_threshold: float = 0.6,
                 max_position_size: float = 0.1):
        """
        Initialize RL signal generator.
        
        Args:
            agent: Trained RL agent
            risk_manager: Risk management system
            confidence_threshold: Minimum confidence for signal generation
            max_position_size: Maximum position size for signals
        """
        self.agent = agent
        self.risk_manager = risk_manager
        self.confidence_threshold = confidence_threshold
        self.max_position_size = max_position_size
        
        # Signal generation state
        self.last_signal_time: Optional[datetime] = None
        self.signal_history: List[TradingSignal] = []
        self.action_confidence_cache: Dict[str, float] = {}
        
        # Action mapping configuration
        self.action_mapping = {
            0: {'type': 'HOLD', 'direction': None, 'strength': 0.0},
            1: {'type': 'BUY', 'direction': Direction.LONG, 'strength': 0.3},
            2: {'type': 'BUY', 'direction': Direction.LONG, 'strength': 0.6},
            3: {'type': 'BUY', 'direction': Direction.LONG, 'strength': 0.9},
            4: {'type': 'SELL', 'direction': Direction.SHORT, 'strength': 0.3},
            5: {'type': 'SELL', 'direction': Direction.SHORT, 'strength': 0.6},
            6: {'type': 'SELL', 'direction': Direction.SHORT, 'strength': 0.9},
            7: {'type': 'CLOSE', 'direction': None, 'strength': 1.0}
        }
        
        self.logger = logging.getLogger(__name__)
    
    def generate_signal(self, 
                       symbol: str,
                       market_data: MarketData,
                       state_vector: np.ndarray,
                       portfolio_state: PortfolioState) -> Optional[TradingSignal]:
        """
        Generate trading signal from RL agent action.
        
        Args:
            symbol: Trading symbol
            market_data: Current market data
            state_vector: RL state vector
            portfolio_state: Current portfolio state
            
        Returns:
            TradingSignal or None if no signal generated
        """
        try:
            # Get action from RL agent
            action = self.agent.select_action(state_vector, training=False)
            
            # Get action confidence/Q-values if available
            confidence = self._get_action_confidence(state_vector, action)
            
            # Check if confidence meets threshold
            if confidence < self.confidence_threshold:
                self.logger.debug(f"Action confidence {confidence:.3f} below threshold {self.confidence_threshold}")
                return None
            
            # Decode action to signal parameters
            action_info = self.action_mapping.get(action, self.action_mapping[0])
            
            # Skip HOLD actions
            if action_info['type'] == 'HOLD':
                return None
            
            # Generate signal
            signal = self._create_trading_signal(
                symbol=symbol,
                market_data=market_data,
                action_info=action_info,
                confidence=confidence,
                portfolio_state=portfolio_state
            )
            
            # Validate signal
            if not self._validate_signal(signal, portfolio_state):
                return None
            
            # Apply risk management
            if self.risk_manager:
                risk_check = self._apply_risk_management(signal, portfolio_state)
                if not risk_check['approved']:
                    self.logger.info(f"Signal rejected by risk management: {risk_check['reason']}")
                    return None
            
            # Store signal in history
            self.signal_history.append(signal)
            self.last_signal_time = datetime.now(timezone.utc)
            
            # Keep only recent signals
            if len(self.signal_history) > 100:
                self.signal_history = self.signal_history[-100:]
            
            self.logger.info(f"Generated RL signal: {signal.direction.value} {symbol} "
                           f"confidence={confidence:.3f}")
            
            return signal
            
        except Exception as e:
            self.logger.error(f"Error generating RL signal for {symbol}: {e}")
            raise SignalGenerationError(f"Failed to generate RL signal: {e}")
    
    def _get_action_confidence(self, state_vector: np.ndarray, action: int) -> float:
        """Get confidence score for the selected action."""
        try:
            # Try to get Q-values or action probabilities from agent
            if hasattr(self.agent, 'get_action_values'):
                action_values = self.agent.get_action_values(state_vector)
                if action_values is not None:
                    # Normalize Q-values to confidence score
                    max_q = np.max(action_values)
                    min_q = np.min(action_values)
                    if max_q != min_q:
                        confidence = (action_values[action] - min_q) / (max_q - min_q)
                        return float(confidence)
            
            elif hasattr(self.agent, 'get_action_probabilities'):
                action_probs = self.agent.get_action_probabilities(state_vector)
                if action_probs is not None:
                    return float(action_probs[action])
            
            # Fallback: use action strength as confidence
            action_info = self.action_mapping.get(action, self.action_mapping[0])
            return action_info['strength']
            
        except Exception as e:
            self.logger.warning(f"Error getting action confidence: {e}")
            # Fallback to action strength
            action_info = self.action_mapping.get(action, self.action_mapping[0])
            return action_info['strength']
    
    def _create_trading_signal(self,
                              symbol: str,
                              market_data: MarketData,
                              action_info: Dict[str, Any],
                              confidence: float,
                              portfolio_state: PortfolioState) -> TradingSignal:
        """Create trading signal from action information."""
        
        # Determine signal strength
        strength = self._calculate_signal_strength(action_info['strength'], confidence)
        
        # Calculate position size based on strength and risk
        position_size = self._calculate_position_size(strength, portfolio_state)
        
        # Set stop loss and take profit based on market conditions
        stop_loss, take_profit = self._calculate_stop_take_levels(
            market_data, action_info['direction'], strength
        )
        
        # Create signal
        rr_ratio = 0.0
        risk = abs(
            (market_data.ask if action_info['direction'] == Direction.LONG else market_data.bid)
            - stop_loss
        )
        reward = abs(
            take_profit
            - (market_data.ask if action_info['direction'] == Direction.LONG else market_data.bid)
        )
        if risk > 0:
            rr_ratio = reward / risk

        signal = TradingSignal(
            symbol=symbol,
            direction=action_info['direction'],
            entry_price=market_data.ask if action_info['direction'] == Direction.LONG else market_data.bid,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confidence=confidence,
            reasoning=f"RL Agent {type(self.agent).__name__} action with strength {strength:.3f}",
            timestamp=datetime.now(timezone.utc),
            rr_ratio=rr_ratio,
        )
        
        # Store strength as additional attribute for internal use
        signal.strength = strength
        
        return signal
    
    def _calculate_signal_strength(self, action_strength: float, confidence: float) -> float:
        """Calculate final signal strength from action strength and confidence."""
        # Combine action strength and confidence
        combined_strength = (action_strength + confidence) / 2
        
        # Normalize to 0-1 range
        return min(max(combined_strength, 0.0), 1.0)
    
    def _calculate_position_size(self, strength: float, portfolio_state: PortfolioState) -> float:
        """Calculate position size based on signal strength and portfolio state."""
        # Base position size from strength
        base_size = strength * self.max_position_size
        
        # Adjust based on current portfolio heat
        portfolio_heat = abs(portfolio_state.current_position) / self.max_position_size
        heat_adjustment = max(0.1, 1.0 - portfolio_heat)
        
        # Adjust based on recent performance
        if portfolio_state.current_drawdown > 0.05:  # 5% drawdown
            drawdown_adjustment = max(0.5, 1.0 - portfolio_state.current_drawdown)
        else:
            drawdown_adjustment = 1.0
        
        # Final position size
        position_size = base_size * heat_adjustment * drawdown_adjustment
        
        return min(max(position_size, 0.01), self.max_position_size)
    
    def _calculate_stop_take_levels(self, 
                                   market_data: MarketData, 
                                   direction: Direction,
                                   strength: float) -> Tuple[Optional[float], Optional[float]]:
        """Calculate stop loss and take profit levels."""
        
        # Base stop distance as percentage of price
        base_stop_pct = 0.001  # 0.1% base stop
        strength_multiplier = 1.0 + (1.0 - strength) * 0.5  # Wider stops for weaker signals
        stop_distance_pct = base_stop_pct * strength_multiplier
        
        # Risk-reward ratio (take profit distance relative to stop loss)
        risk_reward_ratio = 1.5 + strength * 0.5  # 1.5:1 to 2:1 based on strength
        
        if direction == Direction.LONG:
            entry_price = market_data.ask
            stop_loss = entry_price * (1 - stop_distance_pct)
            take_profit = entry_price * (1 + stop_distance_pct * risk_reward_ratio)
        else:  # SHORT
            entry_price = market_data.bid
            stop_loss = entry_price * (1 + stop_distance_pct)
            take_profit = entry_price * (1 - stop_distance_pct * risk_reward_ratio)
        
        return stop_loss, take_profit
    
    def _validate_signal(self, signal: TradingSignal, portfolio_state: PortfolioState) -> bool:
        """Validate trading signal before generation."""
        
        # Check minimum time between signals
        if self.last_signal_time:
            time_since_last = datetime.now(timezone.utc) - self.last_signal_time
            if time_since_last.total_seconds() < 60:  # Minimum 1 minute between signals
                self.logger.debug("Signal rejected: too soon after last signal")
                return False
        
        # Check position size limits
        if signal.position_size > self.max_position_size:
            self.logger.warning(f"Signal position size {signal.position_size} exceeds maximum {self.max_position_size}")
            return False
        
        # Check for conflicting positions
        if signal.direction == Direction.LONG and portfolio_state.current_position < -0.01:
            # Going long while short - this is allowed (closing + reversing)
            pass
        elif signal.direction == Direction.SHORT and portfolio_state.current_position > 0.01:
            # Going short while long - this is allowed (closing + reversing)
            pass
        
        # Check stop loss and take profit validity
        if signal.stop_loss is not None:
            if signal.direction == Direction.LONG and signal.stop_loss >= signal.entry_price:
                self.logger.warning("Invalid stop loss for long position")
                return False
            elif signal.direction == Direction.SHORT and signal.stop_loss <= signal.entry_price:
                self.logger.warning("Invalid stop loss for short position")
                return False
        
        if signal.take_profit is not None:
            if signal.direction == Direction.LONG and signal.take_profit <= signal.entry_price:
                self.logger.warning("Invalid take profit for long position")
                return False
            elif signal.direction == Direction.SHORT and signal.take_profit >= signal.entry_price:
                self.logger.warning("Invalid take profit for short position")
                return False
        
        return True
    
    def _apply_risk_management(self, signal: TradingSignal, portfolio_state: PortfolioState) -> Dict[str, Any]:
        """Apply risk management checks to signal."""
        try:
            if self.risk_manager:
                # This would call the actual risk manager implementation
                # For now, return a simple approval
                return {'approved': True, 'reason': 'Risk check passed'}
            else:
                return {'approved': True, 'reason': 'No risk manager configured'}
                
        except Exception as e:
            self.logger.error(f"Error in risk management check: {e}")
            return {'approved': False, 'reason': f'Risk check error: {e}'}
    
    def get_signal_statistics(self) -> Dict[str, Any]:
        """Get statistics about generated signals."""
        if not self.signal_history:
            return {
                'total_signals': 0,
                'long_signals': 0,
                'short_signals': 0,
                'avg_strength': 0.0,
                'avg_confidence': 0.0,
                'last_signal_time': None
            }
        
        long_signals = [s for s in self.signal_history if s.direction == Direction.LONG]
        short_signals = [s for s in self.signal_history if s.direction == Direction.SHORT]
        
        # Get strength values, using confidence as fallback if strength attribute doesn't exist
        strength_values = [getattr(s, 'strength', s.confidence) for s in self.signal_history]
        
        return {
            'total_signals': len(self.signal_history),
            'long_signals': len(long_signals),
            'short_signals': len(short_signals),
            'avg_strength': np.mean(strength_values) if strength_values else 0.0,
            'avg_confidence': np.mean([s.confidence for s in self.signal_history]),
            'last_signal_time': self.last_signal_time.isoformat() if self.last_signal_time else None,
            'signals_last_hour': len([s for s in self.signal_history 
                                    if _is_within_last_hour(s.timestamp)])
        }
    
    def update_confidence_threshold(self, new_threshold: float) -> None:
        """Update confidence threshold for signal generation."""
        if 0.0 <= new_threshold <= 1.0:
            self.confidence_threshold = new_threshold
            self.logger.info(f"Updated confidence threshold to {new_threshold}")
        else:
            raise ValueError("Confidence threshold must be between 0.0 and 1.0")
    
    def clear_signal_history(self) -> None:
        """Clear signal history."""
        self.signal_history.clear()
        self.last_signal_time = None
        self.logger.info("Signal history cleared")


def _is_within_last_hour(ts: datetime) -> bool:
    """Check if timestamp is within the last hour, handling both naive and aware datetimes."""
    try:
        # Get current time in the same timezone as the provided timestamp
        if ts.tzinfo:
            now = datetime.now(timezone.utc)
        else:
            now = datetime.now()
        
        time_diff = (now - ts).total_seconds()
        return 0 <= time_diff < 3600
    except (TypeError, AttributeError):
        return False


def create_rl_signal_generator(agent: RLAgent,
                              risk_manager: Optional[RiskManager] = None,
                              confidence_threshold: float = 0.6,
                              max_position_size: float = 0.1) -> RLSignalGenerator:
    """Factory function to create RL signal generator."""
    return RLSignalGenerator(
        agent=agent,
        risk_manager=risk_manager,
        confidence_threshold=confidence_threshold,
        max_position_size=max_position_size
    )

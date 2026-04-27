"""
Hybrid Decision Engine

This module combines RL signals with existing AI bot signals to make
final trading decisions using ensemble methods and signal fusion.
"""

import logging
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from enum import Enum
from dataclasses import dataclass

from src.models import TradingSignal, Direction, MarketData
from src.exceptions import SignalGenerationError
from src.rl.integration.signal_generator import RLSignalGenerator
from src.rl.environments.base import PortfolioState


class DecisionMethod(Enum):
    """Decision fusion methods"""
    WEIGHTED_AVERAGE = "weighted_average"
    MAJORITY_VOTE = "majority_vote"
    CONFIDENCE_BASED = "confidence_based"
    RL_PRIORITY = "rl_priority"
    AI_PRIORITY = "ai_priority"


@dataclass
class SignalWeight:
    """Signal source weights for decision fusion"""
    rl_weight: float = 0.6
    ai_weight: float = 0.4
    technical_weight: float = 0.3
    sentiment_weight: float = 0.2
    news_weight: float = 0.1


@dataclass
class DecisionConfig:
    """Configuration for hybrid decision making"""
    method: DecisionMethod = DecisionMethod.WEIGHTED_AVERAGE
    weights: SignalWeight = None
    min_confidence: float = 0.5
    max_signals_per_hour: int = 10
    signal_timeout_minutes: int = 5
    require_consensus: bool = False
    consensus_threshold: float = 0.7


class HybridDecisionEngine:
    """
    Combines RL signals with existing AI bot signals for final trading decisions.
    
    Implements various signal fusion methods and provides comprehensive
    decision making with risk management integration.
    """
    
    def __init__(self,
                 rl_signal_generator: RLSignalGenerator,
                 config: DecisionConfig = None):
        """
        Initialize hybrid decision engine.
        
        Args:
            rl_signal_generator: RL signal generator
            config: Decision making configuration
        """
        self.rl_generator = rl_signal_generator
        self.config = config or DecisionConfig()
        
        if self.config.weights is None:
            self.config.weights = SignalWeight()
        
        # Decision state
        self.recent_decisions: List[Dict[str, Any]] = []
        self.signal_cache: Dict[str, List[TradingSignal]] = {}
        self.last_decision_time: Optional[datetime] = None
        
        # Performance tracking
        self.decision_stats = {
            'total_decisions': 0,
            'rl_decisions': 0,
            'ai_decisions': 0,
            'consensus_decisions': 0,
            'rejected_decisions': 0
        }
        
        self.logger = logging.getLogger(__name__)
    
    def make_decision(self,
                     symbol: str,
                     market_data: MarketData,
                     state_vector: np.ndarray,
                     portfolio_state: PortfolioState,
                     ai_signals: List[TradingSignal] = None,
                     technical_signals: List[TradingSignal] = None,
                     sentiment_signals: List[TradingSignal] = None) -> Optional[TradingSignal]:
        """
        Make final trading decision by combining all available signals.
        
        Args:
            symbol: Trading symbol
            market_data: Current market data
            state_vector: RL state vector
            portfolio_state: Current portfolio state
            ai_signals: Signals from existing AI bot
            technical_signals: Technical analysis signals
            sentiment_signals: Sentiment analysis signals
            
        Returns:
            Final trading signal or None
        """
        try:
            # Check rate limiting
            if not self._check_rate_limit():
                self.logger.debug("Decision rejected: rate limit exceeded")
                return None
            
            # Generate RL signal
            rl_signal = self.rl_generator.generate_signal(
                symbol, market_data, state_vector, portfolio_state
            )
            
            # Collect all signals
            all_signals = {
                'rl': [rl_signal] if rl_signal else [],
                'ai': ai_signals or [],
                'technical': technical_signals or [],
                'sentiment': sentiment_signals or []
            }
            
            # Filter valid signals
            valid_signals = self._filter_valid_signals(all_signals, market_data)
            
            # Check if we have any signals
            total_signals = sum(len(signals) for signals in valid_signals.values())
            if total_signals == 0:
                self.logger.debug("No valid signals available for decision")
                return None
            
            # Make decision based on configured method
            final_signal = self._fuse_signals(valid_signals, market_data, portfolio_state)
            
            # Validate final decision
            if final_signal and self._validate_final_decision(final_signal, portfolio_state):
                # Record decision
                self._record_decision(final_signal, valid_signals)
                
                self.logger.info(f"Hybrid decision: {final_signal.direction.value} {symbol} "
                               f"strength={final_signal.strength:.3f} confidence={final_signal.confidence:.3f}")
                
                return final_signal
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error making hybrid decision for {symbol}: {e}")
            self.decision_stats['rejected_decisions'] += 1
            return None
    
    def _check_rate_limit(self) -> bool:
        """Check if decision rate limit is exceeded."""
        now = datetime.now(timezone.utc)
        
        # Clean old decisions
        cutoff_time = now - timedelta(hours=1)
        self.recent_decisions = [
            d for d in self.recent_decisions 
            if d['timestamp'] > cutoff_time
        ]
        
        # Check rate limit
        if len(self.recent_decisions) >= self.config.max_signals_per_hour:
            return False
        
        # Check minimum time between decisions
        if self.last_decision_time:
            time_since_last = now - self.last_decision_time
            if time_since_last.total_seconds() < 30:  # Minimum 30 seconds
                return False
        
        return True
    
    def _filter_valid_signals(self, 
                             all_signals: Dict[str, List[TradingSignal]], 
                             market_data: MarketData) -> Dict[str, List[TradingSignal]]:
        """Filter and validate signals."""
        valid_signals = {}
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=self.config.signal_timeout_minutes)
        
        for source, signals in all_signals.items():
            valid_list = []
            for signal in signals:
                # Check signal age
                if signal.timestamp < cutoff_time:
                    continue
                
                # Check signal validity
                if not self._is_signal_valid(signal, market_data):
                    continue
                
                # Check minimum confidence
                if signal.confidence < self.config.min_confidence:
                    continue
                
                valid_list.append(signal)
            
            valid_signals[source] = valid_list
        
        return valid_signals
    
    def _is_signal_valid(self, signal: TradingSignal, market_data: MarketData) -> bool:
        """Check if individual signal is valid."""
        # Check required fields
        if not signal.direction or signal.strength <= 0:
            return False
        
        # Check price validity
        if signal.entry_price <= 0:
            return False
        
        # Check stop loss validity
        if signal.stop_loss is not None:
            if signal.direction == Direction.LONG and signal.stop_loss >= signal.entry_price:
                return False
            elif signal.direction == Direction.SHORT and signal.stop_loss <= signal.entry_price:
                return False
        
        # Check take profit validity
        if signal.take_profit is not None:
            if signal.direction == Direction.LONG and signal.take_profit <= signal.entry_price:
                return False
            elif signal.direction == Direction.SHORT and signal.take_profit >= signal.entry_price:
                return False
        
        return True
    
    def _fuse_signals(self, 
                     valid_signals: Dict[str, List[TradingSignal]], 
                     market_data: MarketData,
                     portfolio_state: PortfolioState) -> Optional[TradingSignal]:
        """Fuse signals based on configured method."""
        
        if self.config.method == DecisionMethod.WEIGHTED_AVERAGE:
            return self._weighted_average_fusion(valid_signals, market_data)
        
        elif self.config.method == DecisionMethod.MAJORITY_VOTE:
            return self._majority_vote_fusion(valid_signals, market_data)
        
        elif self.config.method == DecisionMethod.CONFIDENCE_BASED:
            return self._confidence_based_fusion(valid_signals, market_data)
        
        elif self.config.method == DecisionMethod.RL_PRIORITY:
            return self._rl_priority_fusion(valid_signals, market_data)
        
        elif self.config.method == DecisionMethod.AI_PRIORITY:
            return self._ai_priority_fusion(valid_signals, market_data)
        
        else:
            # Default to weighted average
            return self._weighted_average_fusion(valid_signals, market_data)
    
    def _weighted_average_fusion(self, 
                                valid_signals: Dict[str, List[TradingSignal]], 
                                market_data: MarketData) -> Optional[TradingSignal]:
        """Fuse signals using weighted average method."""
        
        # Calculate weighted scores for each direction
        long_score = 0.0
        short_score = 0.0
        total_weight = 0.0
        
        # Weight mapping
        weight_map = {
            'rl': self.config.weights.rl_weight,
            'ai': self.config.weights.ai_weight,
            'technical': self.config.weights.technical_weight,
            'sentiment': self.config.weights.sentiment_weight
        }
        
        signal_details = []
        
        for source, signals in valid_signals.items():
            if not signals:
                continue
                
            source_weight = weight_map.get(source, 0.1)
            
            for signal in signals:
                # Get strength from signal attribute or use confidence as fallback
                signal_strength = getattr(signal, 'strength', signal.confidence)
                weighted_strength = signal_strength * signal.confidence * source_weight
                
                if signal.direction == Direction.LONG:
                    long_score += weighted_strength
                else:
                    short_score += weighted_strength
                
                total_weight += source_weight
                signal_details.append({
                    'source': source,
                    'direction': signal.direction,
                    'strength': signal_strength,
                    'confidence': signal.confidence,
                    'weight': source_weight
                })
        
        if total_weight == 0:
            return None
        
        # Determine final direction and strength
        if long_score > short_score:
            final_direction = Direction.LONG
            final_strength = long_score / total_weight
        elif short_score > long_score:
            final_direction = Direction.SHORT
            final_strength = short_score / total_weight
        else:
            # Tie - no signal
            return None
        
        # Calculate final confidence
        final_confidence = max(long_score, short_score) / total_weight
        
        # Check consensus requirement
        if self.config.require_consensus:
            consensus_ratio = max(long_score, short_score) / (long_score + short_score)
            if consensus_ratio < self.config.consensus_threshold:
                self.logger.debug(f"Consensus requirement not met: {consensus_ratio:.3f} < {self.config.consensus_threshold}")
                return None
        
        # Create final signal
        return self._create_final_signal(
            symbol=market_data.symbol,
            direction=final_direction,
            strength=final_strength,
            confidence=final_confidence,
            market_data=market_data,
            source_signals=signal_details
        )
    
    def _majority_vote_fusion(self, 
                             valid_signals: Dict[str, List[TradingSignal]], 
                             market_data: MarketData) -> Optional[TradingSignal]:
        """Fuse signals using majority vote method."""
        
        long_votes = 0
        short_votes = 0
        total_strength = 0.0
        total_confidence = 0.0
        vote_count = 0
        
        for source, signals in valid_signals.items():
            for signal in signals:
                if signal.direction == Direction.LONG:
                    long_votes += 1
                else:
                    short_votes += 1
                
                # Get strength from signal attribute or use confidence as fallback
                signal_strength = getattr(signal, 'strength', signal.confidence)
                total_strength += signal_strength
                total_confidence += signal.confidence
                vote_count += 1
        
        if vote_count == 0:
            return None
        
        # Determine majority
        if long_votes > short_votes:
            final_direction = Direction.LONG
        elif short_votes > long_votes:
            final_direction = Direction.SHORT
        else:
            # Tie - no signal
            return None
        
        # Average strength and confidence
        avg_strength = total_strength / vote_count
        avg_confidence = total_confidence / vote_count
        
        return self._create_final_signal(
            symbol=market_data.symbol,
            direction=final_direction,
            strength=avg_strength,
            confidence=avg_confidence,
            market_data=market_data,
            source_signals=[]
        )
    
    def _confidence_based_fusion(self, 
                                valid_signals: Dict[str, List[TradingSignal]], 
                                market_data: MarketData) -> Optional[TradingSignal]:
        """Fuse signals by selecting highest confidence signal."""
        
        best_signal = None
        best_confidence = 0.0
        
        for source, signals in valid_signals.items():
            for signal in signals:
                # Get strength from signal attribute or use confidence as fallback
                signal_strength = getattr(signal, 'strength', signal.confidence)
                combined_score = signal_strength * signal.confidence
                if combined_score > best_confidence:
                    best_confidence = combined_score
                    best_signal = signal
        
        if best_signal is None:
            return None
        
        signal_strength = getattr(best_signal, 'strength', best_signal.confidence)
        return self._create_final_signal(
            symbol=market_data.symbol,
            direction=best_signal.direction,
            strength=signal_strength,
            confidence=best_signal.confidence,
            market_data=market_data,
            source_signals=[{'source': 'best_confidence', 'signal': best_signal}]
        )
    
    def _rl_priority_fusion(self, 
                           valid_signals: Dict[str, List[TradingSignal]], 
                           market_data: MarketData) -> Optional[TradingSignal]:
        """Prioritize RL signals, fallback to others."""
        
        # Check RL signals first
        if valid_signals.get('rl'):
            rl_signal = valid_signals['rl'][0]  # Take first RL signal
            signal_strength = getattr(rl_signal, 'strength', rl_signal.confidence)
            return self._create_final_signal(
                symbol=market_data.symbol,
                direction=rl_signal.direction,
                strength=signal_strength,
                confidence=rl_signal.confidence,
                market_data=market_data,
                source_signals=[{'source': 'rl_priority', 'signal': rl_signal}]
            )
        
        # Fallback to weighted average of other signals
        other_signals = {k: v for k, v in valid_signals.items() if k != 'rl'}
        return self._weighted_average_fusion(other_signals, market_data)
    
    def _ai_priority_fusion(self, 
                           valid_signals: Dict[str, List[TradingSignal]], 
                           market_data: MarketData) -> Optional[TradingSignal]:
        """Prioritize AI signals, fallback to others."""
        
        # Check AI signals first
        if valid_signals.get('ai'):
            ai_signal = valid_signals['ai'][0]  # Take first AI signal
            signal_strength = getattr(ai_signal, 'strength', ai_signal.confidence)
            return self._create_final_signal(
                symbol=market_data.symbol,
                direction=ai_signal.direction,
                strength=signal_strength,
                confidence=ai_signal.confidence,
                market_data=market_data,
                source_signals=[{'source': 'ai_priority', 'signal': ai_signal}]
            )
        
        # Fallback to weighted average of other signals
        other_signals = {k: v for k, v in valid_signals.items() if k != 'ai'}
        return self._weighted_average_fusion(other_signals, market_data)
    
    def _create_final_signal(self,
                            symbol: str,
                            direction: Direction,
                            strength: float,
                            confidence: float,
                            market_data: MarketData,
                            source_signals: List[Dict[str, Any]]) -> TradingSignal:
        """Create final trading signal."""
        
        # Calculate position size based on strength
        position_size = min(strength * 0.1, 0.05)  # Max 5% position
        
        # Calculate stop loss and take profit
        stop_distance_pct = 0.001 * (2.0 - strength)  # Tighter stops for stronger signals
        risk_reward_ratio = 1.5 + strength * 0.5
        
        if direction == Direction.LONG:
            entry_price = market_data.ask
            stop_loss = entry_price * (1 - stop_distance_pct)
            take_profit = entry_price * (1 + stop_distance_pct * risk_reward_ratio)
        else:
            entry_price = market_data.bid
            stop_loss = entry_price * (1 + stop_distance_pct)
            take_profit = entry_price * (1 - stop_distance_pct * risk_reward_ratio)
        
        signal = TradingSignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confidence=confidence,
            reasoning=f"Hybrid decision using {self.config.method.value} with {len(source_signals)} sources",
            timestamp=datetime.now(timezone.utc)
        )
        
        # Add strength as additional attribute for internal use
        signal.strength = strength
        
        return signal
    
    def _validate_final_decision(self, signal: TradingSignal, portfolio_state: PortfolioState) -> bool:
        """Validate final trading decision."""
        
        # Get strength from signal attribute or use confidence as fallback
        signal_strength = getattr(signal, 'strength', signal.confidence)
        
        # Check minimum strength and confidence
        if signal_strength < 0.1 or signal.confidence < self.config.min_confidence:
            return False
        
        # Check position size
        if signal.position_size <= 0 or signal.position_size > 0.1:
            return False
        
        # Additional validation can be added here
        
        return True
    
    def _record_decision(self, signal: TradingSignal, source_signals: Dict[str, List[TradingSignal]]) -> None:
        """Record decision for tracking and analysis."""
        
        # Get strength from signal attribute or use confidence as fallback
        signal_strength = getattr(signal, 'strength', signal.confidence)
        
        decision_record = {
            'timestamp': datetime.now(timezone.utc),
            'symbol': signal.symbol,
            'direction': signal.direction.value,
            'strength': signal_strength,
            'confidence': signal.confidence,
            'method': self.config.method.value,
            'source_count': sum(len(signals) for signals in source_signals.values()),
            'rl_signals': len(source_signals.get('rl', [])),
            'ai_signals': len(source_signals.get('ai', [])),
            'technical_signals': len(source_signals.get('technical', [])),
            'sentiment_signals': len(source_signals.get('sentiment', []))
        }
        
        self.recent_decisions.append(decision_record)
        self.last_decision_time = datetime.now(timezone.utc)
        
        # Update statistics
        self.decision_stats['total_decisions'] += 1
        
        if source_signals.get('rl'):
            self.decision_stats['rl_decisions'] += 1
        if source_signals.get('ai'):
            self.decision_stats['ai_decisions'] += 1
        
        # Check for consensus
        total_sources = sum(len(signals) for signals in source_signals.values())
        if total_sources >= 2:
            self.decision_stats['consensus_decisions'] += 1
    
    def get_decision_statistics(self) -> Dict[str, Any]:
        """Get decision making statistics."""
        return {
            **self.decision_stats,
            'recent_decisions_count': len(self.recent_decisions),
            'last_decision_time': self.last_decision_time.isoformat() if self.last_decision_time else None,
            'decisions_last_hour': len(self.recent_decisions),
            'avg_confidence': np.mean([d['confidence'] for d in self.recent_decisions]) if self.recent_decisions else 0.0,
            'avg_strength': np.mean([d['strength'] for d in self.recent_decisions]) if self.recent_decisions else 0.0
        }
    
    def update_config(self, new_config: DecisionConfig) -> None:
        """Update decision configuration."""
        self.config = new_config
        self.logger.info(f"Updated decision config: method={new_config.method.value}")
    
    def clear_history(self) -> None:
        """Clear decision history."""
        self.recent_decisions.clear()
        self.signal_cache.clear()
        self.last_decision_time = None
        self.logger.info("Decision history cleared")


def create_hybrid_decision_engine(rl_signal_generator: RLSignalGenerator,
                                 config: DecisionConfig = None) -> HybridDecisionEngine:
    """Factory function to create hybrid decision engine."""
    return HybridDecisionEngine(
        rl_signal_generator=rl_signal_generator,
        config=config
    )
"""Confidence calculation for trading signals"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
from src.models import TechnicalSignal, SignalType, TradingSignal
from src.analysis.sentiment_aggregator import AggregatedSentiment
from src.analysis.signal_combiner import CombinedSignalResult
from src.exceptions import DataValidationError
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class ConfidenceFactors:
    """Individual factors contributing to overall confidence"""
    signal_strength: float
    signal_consistency: float
    source_reliability: float
    temporal_stability: float
    market_alignment: float
    volume_confirmation: float
    risk_reward_ratio: float


@dataclass
class ConfidenceResult:
    """Result of confidence calculation"""
    overall_confidence: float
    confidence_factors: ConfidenceFactors
    confidence_breakdown: Dict[str, float]
    reliability_score: float
    recommendation: str  # "STRONG", "MODERATE", "WEAK", "AVOID"


class ConfidenceCalculator:
    """Calculate confidence scores for trading signals"""
    
    def __init__(self,
                 signal_strength_weight: float = 0.25,
                 consistency_weight: float = 0.20,
                 reliability_weight: float = 0.15,
                 temporal_weight: float = 0.15,
                 market_alignment_weight: float = 0.15,
                 volume_weight: float = 0.05,
                 risk_reward_weight: float = 0.05):
        """Initialize confidence calculator with weights"""
        
        # Validate weights sum to 1.0
        total_weight = (signal_strength_weight + consistency_weight + reliability_weight +
                       temporal_weight + market_alignment_weight + volume_weight + risk_reward_weight)
        
        if abs(total_weight - 1.0) > 0.001:
            raise DataValidationError(
                f"Confidence weights must sum to 1.0, got {total_weight}",
                error_code="INVALID_WEIGHTS",
                context={"total_weight": total_weight}
            )
        
        self.weights = {
            "signal_strength": signal_strength_weight,
            "consistency": consistency_weight,
            "reliability": reliability_weight,
            "temporal": temporal_weight,
            "market_alignment": market_alignment_weight,
            "volume": volume_weight,
            "risk_reward": risk_reward_weight
        }
        
        # Historical performance tracking for reliability
        self.signal_performance_history: Dict[str, List[float]] = {}
        
        # Source reliability scores
        self.source_reliability_scores = {
            "technical_rsi": 0.8,
            "technical_macd": 0.85,
            "technical_ma": 0.75,
            "technical_bollinger": 0.7,
            "technical_stochastic": 0.65,
            "sentiment_news": 0.7,
            "sentiment_social": 0.6,
            "pattern_recognition": 0.75,
            "support_resistance": 0.8
        }
    
    def calculate_confidence(self,
                           trading_signal: TradingSignal,
                           sentiment_result: Optional[AggregatedSentiment] = None,
                           technical_signals: List[TechnicalSignal] = None,
                           market_data: Dict[str, float] = None) -> ConfidenceResult:
        """Calculate overall confidence for a trading signal"""
        
        logger.info(f"Calculating confidence for {trading_signal.symbol} {trading_signal.direction.value} signal")
        
        # Calculate individual confidence factors
        factors = self._calculate_confidence_factors(
            trading_signal, sentiment_result, technical_signals, market_data
        )
        
        # Calculate weighted overall confidence
        overall_confidence = self._calculate_weighted_confidence(factors)
        
        # Create confidence breakdown
        breakdown = {
            "signal_strength": factors.signal_strength,
            "signal_consistency": factors.signal_consistency,
            "source_reliability": factors.source_reliability,
            "temporal_stability": factors.temporal_stability,
            "market_alignment": factors.market_alignment,
            "volume_confirmation": factors.volume_confirmation,
            "risk_reward_ratio": factors.risk_reward_ratio
        }
        
        # Calculate reliability score
        reliability_score = self._calculate_reliability_score(
            trading_signal, sentiment_result, technical_signals
        )
        
        # Generate recommendation
        recommendation = self._generate_recommendation(overall_confidence, reliability_score)
        
        return ConfidenceResult(
            overall_confidence=overall_confidence,
            confidence_factors=factors,
            confidence_breakdown=breakdown,
            reliability_score=reliability_score,
            recommendation=recommendation
        )
    
    def _calculate_confidence_factors(self,
                                    trading_signal: TradingSignal,
                                    sentiment_result: Optional[AggregatedSentiment],
                                    technical_signals: List[TechnicalSignal],
                                    market_data: Dict[str, float]) -> ConfidenceFactors:
        """Calculate individual confidence factors"""
        
        # Signal strength factor
        signal_strength = trading_signal.confidence
        
        # Signal consistency factor
        signal_consistency = self._calculate_signal_consistency(
            sentiment_result, technical_signals
        )
        
        # Source reliability factor
        source_reliability = self._calculate_source_reliability(
            sentiment_result, technical_signals
        )
        
        # Temporal stability factor
        temporal_stability = self._calculate_temporal_stability(
            sentiment_result, technical_signals
        )
        
        # Market alignment factor
        market_alignment = self._calculate_market_alignment(
            trading_signal, market_data
        )
        
        # Volume confirmation factor
        volume_confirmation = self._calculate_volume_confirmation(
            trading_signal, market_data
        )
        
        # Risk-reward ratio factor
        risk_reward_ratio = self._calculate_risk_reward_factor(trading_signal)
        
        return ConfidenceFactors(
            signal_strength=signal_strength,
            signal_consistency=signal_consistency,
            source_reliability=source_reliability,
            temporal_stability=temporal_stability,
            market_alignment=market_alignment,
            volume_confirmation=volume_confirmation,
            risk_reward_ratio=risk_reward_ratio
        )
    
    def _calculate_signal_consistency(self,
                                    sentiment_result: Optional[AggregatedSentiment],
                                    technical_signals: List[TechnicalSignal]) -> float:
        """Calculate consistency between different signal sources"""
        
        if not sentiment_result and not technical_signals:
            return 0.0
        
        consistency_scores = []
        
        # Sentiment consistency
        if sentiment_result:
            consistency_scores.append(sentiment_result.consistency_score)
        
        # Technical signal consistency
        if technical_signals and len(technical_signals) > 1:
            # Calculate agreement between technical signals
            buy_signals = sum(1 for s in technical_signals if s.signal_type == SignalType.BUY)
            sell_signals = sum(1 for s in technical_signals if s.signal_type == SignalType.SELL)
            total_signals = len(technical_signals)
            
            # Higher agreement = higher consistency
            max_agreement = max(buy_signals, sell_signals)
            technical_consistency = max_agreement / total_signals
            consistency_scores.append(technical_consistency)
        
        # Cross-source consistency (sentiment vs technical)
        if sentiment_result and technical_signals:
            sentiment_bullish = sentiment_result.final_sentiment_score > 0.1
            technical_bullish = sum(1 for s in technical_signals if s.signal_type == SignalType.BUY) > \
                               sum(1 for s in technical_signals if s.signal_type == SignalType.SELL)
            
            cross_consistency = 1.0 if sentiment_bullish == technical_bullish else 0.3
            consistency_scores.append(cross_consistency)
        
        return mean(consistency_scores) if consistency_scores else 0.5
    
    def _calculate_source_reliability(self,
                                     sentiment_result: Optional[AggregatedSentiment],
                                     technical_signals: List[TechnicalSignal]) -> float:
        """Calculate reliability based on signal sources"""
        
        reliability_scores = []
        
        # Sentiment source reliability
        if sentiment_result:
            sentiment_reliability = 0.0
            for source in sentiment_result.sources:
                if "news" in source.lower():
                    sentiment_reliability = max(sentiment_reliability, self.source_reliability_scores["sentiment_news"])
                elif "social" in source.lower():
                    sentiment_reliability = max(sentiment_reliability, self.source_reliability_scores["sentiment_social"])
            
            if sentiment_reliability > 0:
                reliability_scores.append(sentiment_reliability)
        
        # Technical signal source reliability
        if technical_signals:
            for signal in technical_signals:
                signal_reliability = 0.5  # Default
                
                # Determine signal type from indicators
                for indicator_name in signal.indicators.keys():
                    if indicator_name.lower() in ["rsi"]:
                        signal_reliability = max(signal_reliability, self.source_reliability_scores["technical_rsi"])
                    elif indicator_name.lower() in ["macd", "macd_signal"]:
                        signal_reliability = max(signal_reliability, self.source_reliability_scores["technical_macd"])
                    elif "sma" in indicator_name.lower() or "ema" in indicator_name.lower():
                        signal_reliability = max(signal_reliability, self.source_reliability_scores["technical_ma"])
                    elif "bollinger" in indicator_name.lower() or "bb_" in indicator_name.lower():
                        signal_reliability = max(signal_reliability, self.source_reliability_scores["technical_bollinger"])
                    elif "stochastic" in indicator_name.lower():
                        signal_reliability = max(signal_reliability, self.source_reliability_scores["technical_stochastic"])
                    elif "support" in indicator_name.lower() or "resistance" in indicator_name.lower():
                        signal_reliability = max(signal_reliability, self.source_reliability_scores["support_resistance"])
                
                reliability_scores.append(signal_reliability)
        
        return mean(reliability_scores) if reliability_scores else 0.5
    
    def _calculate_temporal_stability(self,
                                    sentiment_result: Optional[AggregatedSentiment],
                                    technical_signals: List[TechnicalSignal]) -> float:
        """Calculate temporal stability of signals"""
        
        current_time = datetime.now(timezone.utc)
        stability_scores = []
        
        # Sentiment temporal stability
        if sentiment_result:
            age_minutes = (current_time - sentiment_result.timestamp).total_seconds() / 60
            # Fresher signals are more stable, decay over time
            sentiment_stability = max(0.0, 1.0 - (age_minutes / 60.0))  # 1 hour decay
            stability_scores.append(sentiment_stability)
        
        # Technical signal temporal stability
        if technical_signals:
            for signal in technical_signals:
                age_minutes = (current_time - signal.timestamp).total_seconds() / 60
                signal_stability = max(0.0, 1.0 - (age_minutes / 30.0))  # 30 min decay
                stability_scores.append(signal_stability)
        
        # Signal timing synchronization
        if sentiment_result and technical_signals:
            all_timestamps = [sentiment_result.timestamp] + [s.timestamp for s in technical_signals]
            time_span = (max(all_timestamps) - min(all_timestamps)).total_seconds() / 60
            
            # Signals closer in time are more stable
            sync_stability = max(0.0, 1.0 - (time_span / 15.0))  # 15 min window
            stability_scores.append(sync_stability)
        
        return mean(stability_scores) if stability_scores else 0.5
    
    def _calculate_market_alignment(self,
                                  trading_signal: TradingSignal,
                                  market_data: Dict[str, float]) -> float:
        """Calculate alignment with current market conditions"""
        
        if not market_data:
            return 0.5  # Neutral if no market data
        
        alignment_factors = []
        
        # Trend alignment
        if "trend_direction" in market_data and "trend_strength" in market_data:
            trend_direction = market_data["trend_direction"]  # 1 for up, -1 for down, 0 for sideways
            trend_strength = market_data["trend_strength"]
            
            signal_direction_value = 1 if trading_signal.direction.value == "LONG" else -1
            
            # Check if signal aligns with trend
            if trend_direction != 0:  # Not sideways
                alignment = 1.0 if (trend_direction * signal_direction_value) > 0 else 0.2
                # Weight by trend strength
                trend_alignment = alignment * trend_strength
                alignment_factors.append(trend_alignment)
        
        # Volatility alignment
        if "volatility" in market_data:
            volatility = market_data["volatility"]
            # Higher volatility requires higher confidence
            volatility_penalty = max(0.0, 1.0 - (volatility - 0.5))
            alignment_factors.append(volatility_penalty)
        
        # Market session alignment
        if "market_session" in market_data:
            session = market_data["market_session"]  # "LONDON", "NEW_YORK", "TOKYO", "SYDNEY"
            
            # Major sessions have better liquidity
            session_scores = {
                "LONDON": 1.0,
                "NEW_YORK": 1.0,
                "TOKYO": 0.8,
                "SYDNEY": 0.7,
                "OVERLAP": 1.0,  # Session overlaps
                "OFF_HOURS": 0.4
            }
            
            session_alignment = session_scores.get(session, 0.5)
            alignment_factors.append(session_alignment)
        
        return mean(alignment_factors) if alignment_factors else 0.5
    
    def _calculate_volume_confirmation(self,
                                     trading_signal: TradingSignal,
                                     market_data: Dict[str, float]) -> float:
        """Calculate volume confirmation factor"""
        
        if not market_data or "volume_ratio" not in market_data:
            return 0.5  # Neutral if no volume data
        
        volume_ratio = market_data["volume_ratio"]  # Current volume / average volume
        
        # Higher volume confirms the signal
        if volume_ratio > 1.5:
            return 1.0  # Strong volume confirmation
        elif volume_ratio > 1.2:
            return 0.8  # Good volume confirmation
        elif volume_ratio > 0.8:
            return 0.6  # Adequate volume
        else:
            return 0.3  # Low volume, weak confirmation
    
    def _calculate_risk_reward_factor(self, trading_signal: TradingSignal) -> float:
        """Calculate risk-reward ratio factor"""
        
        risk_reward_ratio = trading_signal.calculate_risk_reward_ratio()
        
        # Better risk-reward ratios increase confidence
        if risk_reward_ratio >= 2.0:
            return 1.0  # Excellent risk-reward
        elif risk_reward_ratio >= 1.5:
            return 0.8  # Good risk-reward
        elif risk_reward_ratio >= 1.0:
            return 0.6  # Acceptable risk-reward
        else:
            return 0.3  # Poor risk-reward
    
    def _calculate_weighted_confidence(self, factors: ConfidenceFactors) -> float:
        """Calculate weighted overall confidence"""
        
        weighted_sum = (
            factors.signal_strength * self.weights["signal_strength"] +
            factors.signal_consistency * self.weights["consistency"] +
            factors.source_reliability * self.weights["reliability"] +
            factors.temporal_stability * self.weights["temporal"] +
            factors.market_alignment * self.weights["market_alignment"] +
            factors.volume_confirmation * self.weights["volume"] +
            factors.risk_reward_ratio * self.weights["risk_reward"]
        )
        
        return min(max(weighted_sum, 0.0), 1.0)  # Clamp to [0, 1]
    
    def _calculate_reliability_score(self,
                                   trading_signal: TradingSignal,
                                   sentiment_result: Optional[AggregatedSentiment],
                                   technical_signals: List[TechnicalSignal]) -> float:
        """Calculate overall reliability score"""
        
        reliability_factors = []
        
        # Signal age reliability
        current_time = datetime.now(timezone.utc)
        signal_age = (current_time - trading_signal.timestamp).total_seconds() / 60
        age_reliability = max(0.0, 1.0 - (signal_age / 30.0))  # 30 min decay
        reliability_factors.append(age_reliability)
        
        # Source diversity reliability
        source_count = 0
        if sentiment_result:
            source_count += len(sentiment_result.sources)
        if technical_signals:
            source_count += len(technical_signals)
        
        diversity_reliability = min(source_count / 5.0, 1.0)  # Normalize to max 5 sources
        reliability_factors.append(diversity_reliability)
        
        # Historical performance reliability
        signal_key = f"{trading_signal.symbol}_{trading_signal.direction.value}"
        if signal_key in self.signal_performance_history:
            historical_performance = mean(self.signal_performance_history[signal_key])
            reliability_factors.append(historical_performance)
        else:
            reliability_factors.append(0.5)  # Neutral for new signals
        
        return mean(reliability_factors)
    
    def _generate_recommendation(self, confidence: float, reliability: float) -> str:
        """Generate trading recommendation based on confidence and reliability"""
        
        combined_score = (confidence + reliability) / 2
        
        if combined_score >= 0.8 and confidence >= 0.7:
            return "STRONG"
        elif combined_score >= 0.6 and confidence >= 0.5:
            return "MODERATE"
        elif combined_score >= 0.4:
            return "WEAK"
        else:
            return "AVOID"
    
    def update_signal_performance(self, signal_key: str, performance_score: float) -> None:
        """Update historical performance for signal reliability"""
        
        if signal_key not in self.signal_performance_history:
            self.signal_performance_history[signal_key] = []
        
        self.signal_performance_history[signal_key].append(performance_score)
        
        # Keep only last 100 performance records
        if len(self.signal_performance_history[signal_key]) > 100:
            self.signal_performance_history[signal_key] = \
                self.signal_performance_history[signal_key][-100:]
        
        logger.debug(f"Updated performance for {signal_key}: {performance_score}")
    
    def update_source_reliability(self, source_name: str, reliability_score: float) -> None:
        """Update reliability score for a signal source"""
        
        if 0.0 <= reliability_score <= 1.0:
            self.source_reliability_scores[source_name] = reliability_score
            logger.info(f"Updated reliability for {source_name}: {reliability_score}")
        else:
            logger.warning(f"Invalid reliability score for {source_name}: {reliability_score}")
    
    def get_confidence_statistics(self) -> Dict[str, any]:
        """Get statistics about confidence calculations"""
        
        stats = {
            "weights": self.weights.copy(),
            "source_reliability_scores": self.source_reliability_scores.copy(),
            "performance_history_count": len(self.signal_performance_history),
            "total_performance_records": sum(
                len(records) for records in self.signal_performance_history.values()
            )
        }
        
        # Calculate average performance by signal type
        if self.signal_performance_history:
            avg_performance = {}
            for signal_key, performances in self.signal_performance_history.items():
                avg_performance[signal_key] = mean(performances)
            stats["average_performance_by_signal"] = avg_performance
        
        return stats
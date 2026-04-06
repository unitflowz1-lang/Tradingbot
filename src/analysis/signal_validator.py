"""Signal validation to filter out weak or conflicting signals"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from src.models import TechnicalSignal, SignalType, MarketData, TradingSignal, Direction
from src.analysis.trend_analyzer import TrendAnalysis, TrendAnalyzer
from src.analysis.technical_indicators import TechnicalIndicators
from src.exceptions import DataValidationError


@dataclass
class SignalValidationResult:
    """Result of signal validation"""
    is_valid: bool
    valid_signals: List[TradingSignal]
    invalid_signals: List[TradingSignal]
    reasoning: str
    overall_confidence: float
    confidence_score: float  # 0.0 to 1.0
    validation_reasons: List[str]
    filtered_signals: List[TechnicalSignal]
    risk_level: str  # "LOW", "MEDIUM", "HIGH"


@dataclass
class SignalPersistence:
    """Track signal persistence over time"""
    signal_type: SignalType
    first_seen: datetime
    last_seen: datetime
    occurrence_count: int
    average_strength: float
    is_persistent: bool


class SignalValidator:
    """Validate and filter trading signals"""
    
    def __init__(self,
                 min_signal_strength: float = 0.3,
                 min_confluence_signals: int = 2,
                 max_signal_age_minutes: int = 60,
                 persistence_threshold: int = 3,
                 min_confidence: float = 0.5,
                 min_risk_reward_ratio: float = 1.2,
                 max_position_size: float = 0.2):
        """Initialize signal validator"""
        self.min_signal_strength = min_signal_strength
        self.min_confluence_signals = min_confluence_signals
        self.max_signal_age_minutes = max_signal_age_minutes
        self.persistence_threshold = persistence_threshold
        self.min_confidence = min_confidence
        self.min_risk_reward_ratio = min_risk_reward_ratio
        self.max_position_size = max_position_size
        
        # Track signal history for persistence analysis
        self.signal_history: Dict[str, List[SignalPersistence]] = {}
        self.trend_analyzer = TrendAnalyzer()
        
        # Validation statistics
        self.validation_stats = {
            "total_signals_validated": 0,
            "valid_signals_count": 0,
            "invalid_signals_count": 0,
            "validation_success_rate": 0.0,
            "avg_confidence": 0.0
        }
    
    def validate_signals(self, signals: List[TradingSignal]) -> SignalValidationResult:
        """Validate a list of trading signals"""
        
        if not signals:
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[],
                reasoning="No signals provided",
                overall_confidence=0.0,
                confidence_score=0.0,
                validation_reasons=["No signals provided"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        valid_signals = []
        invalid_signals = []
        validation_reasons = []
        
        # Update statistics
        self.validation_stats["total_signals_validated"] += len(signals)
        
        for signal in signals:
            individual_result = self.validate_signal(signal)
            if individual_result.is_valid:
                valid_signals.append(signal)
            else:
                invalid_signals.append(signal)
                validation_reasons.append(f"Signal {signal.symbol}: {individual_result.reasoning}")
        
        # Calculate overall confidence
        if valid_signals:
            overall_confidence = sum(s.confidence for s in valid_signals) / len(valid_signals)
        else:
            overall_confidence = 0.0
        
        # Determine if signals are valid overall
        is_valid = len(valid_signals) >= self.min_confluence_signals and overall_confidence >= self.min_confidence
        
        # Generate reasoning
        if is_valid:
            reasoning = f"Validated {len(valid_signals)} signals with {overall_confidence:.2f} confidence"
        else:
            if len(valid_signals) < self.min_confluence_signals:
                reasoning = f"Insufficient valid signals ({len(valid_signals)} < {self.min_confluence_signals})"
            else:
                reasoning = f"Low confidence ({overall_confidence:.2f} < {self.min_confidence})"
            
            # Add specific validation reasons to the reasoning
            if validation_reasons:
                specific_reasons = [reason.split(": ")[-1] for reason in validation_reasons]
                reasoning += f" - {', '.join(specific_reasons)}"
        
        # Update statistics
        self.validation_stats["valid_signals_count"] += len(valid_signals)
        self.validation_stats["invalid_signals_count"] += len(invalid_signals)
        self.validation_stats["validation_success_rate"] = (
            self.validation_stats["valid_signals_count"] / 
            max(self.validation_stats["total_signals_validated"], 1)
        )
        
        if valid_signals:
            self.validation_stats["avg_confidence"] = (
                (self.validation_stats["avg_confidence"] * (self.validation_stats["valid_signals_count"] - len(valid_signals)) + 
                 sum(s.confidence for s in valid_signals)) / 
                self.validation_stats["valid_signals_count"]
            )
        
        return SignalValidationResult(
            is_valid=is_valid,
            valid_signals=valid_signals,
            invalid_signals=invalid_signals,
            reasoning=reasoning,
            overall_confidence=overall_confidence,
            confidence_score=overall_confidence,
            validation_reasons=validation_reasons,
            filtered_signals=[],  # Not used in this context
            risk_level="MEDIUM" if is_valid else "HIGH"
        )
    
    def validate_signal(self, signal: TradingSignal) -> SignalValidationResult:
        """Validate a single trading signal"""
        
        # Check confidence threshold
        if signal.confidence < self.min_confidence:
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning=f"low confidence ({signal.confidence:.2f} < {self.min_confidence})",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=[f"Confidence {signal.confidence:.2f} below threshold {self.min_confidence}"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Check signal age
        current_time = datetime.now(timezone.utc)
        signal_age = current_time - signal.timestamp
        if signal_age > timedelta(minutes=self.max_signal_age_minutes):
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning=f"old signal ({signal_age.total_seconds() / 60:.1f} minutes > {self.max_signal_age_minutes})",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=[f"Signal age {signal_age.total_seconds() / 60:.1f} minutes exceeds threshold"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Check risk-reward ratio
        if signal.direction == Direction.LONG:
            risk = signal.entry_price - signal.stop_loss
            reward = signal.take_profit - signal.entry_price
        else:  # SHORT
            risk = signal.stop_loss - signal.entry_price
            reward = signal.entry_price - signal.take_profit
        
        if risk > 0 and reward > 0:
            rr_ratio = reward / risk
            if rr_ratio < self.min_risk_reward_ratio:
                return SignalValidationResult(
                    is_valid=False,
                    valid_signals=[],
                    invalid_signals=[signal],
                    reasoning=f"poor risk-reward ratio ({rr_ratio:.2f} < {self.min_risk_reward_ratio})",
                    overall_confidence=signal.confidence,
                    confidence_score=signal.confidence,
                    validation_reasons=[f"Risk-reward ratio {rr_ratio:.2f} below threshold"],
                    filtered_signals=[],
                    risk_level="HIGH"
                )
        
        # Check position size
        if signal.position_size > self.max_position_size:
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning=f"position size too large ({signal.position_size:.2f} > {self.max_position_size})",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=[f"Position size {signal.position_size:.2f} exceeds maximum"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Check price validation
        if signal.direction == Direction.LONG:
            if signal.stop_loss >= signal.entry_price:
                return SignalValidationResult(
                    is_valid=False,
                    valid_signals=[],
                    invalid_signals=[signal],
                    reasoning="stop loss above entry price for LONG position",
                    overall_confidence=signal.confidence,
                    confidence_score=signal.confidence,
                    validation_reasons=["Invalid stop loss for LONG position"],
                    filtered_signals=[],
                    risk_level="HIGH"
                )
            if signal.take_profit <= signal.entry_price:
                return SignalValidationResult(
                    is_valid=False,
                    valid_signals=[],
                    invalid_signals=[signal],
                    reasoning="take profit below entry price for LONG position",
                    overall_confidence=signal.confidence,
                    confidence_score=signal.confidence,
                    validation_reasons=["Invalid take profit for LONG position"],
                    filtered_signals=[],
                    risk_level="HIGH"
                )
        else:  # SHORT
            if signal.stop_loss <= signal.entry_price:
                return SignalValidationResult(
                    is_valid=False,
                    valid_signals=[],
                    invalid_signals=[signal],
                    reasoning="stop loss below entry price for SHORT position",
                    overall_confidence=signal.confidence,
                    confidence_score=signal.confidence,
                    validation_reasons=["Invalid stop loss for SHORT position"],
                    filtered_signals=[],
                    risk_level="HIGH"
                )
            if signal.take_profit >= signal.entry_price:
                return SignalValidationResult(
                    is_valid=False,
                    valid_signals=[],
                    invalid_signals=[signal],
                    reasoning="take profit above entry price for SHORT position",
                    overall_confidence=signal.confidence,
                    confidence_score=signal.confidence,
                    validation_reasons=["Invalid take profit for SHORT position"],
                    filtered_signals=[],
                    risk_level="HIGH"
                )
        
        # Check symbol validation
        if not signal.symbol or len(signal.symbol) < 3:
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning="invalid symbol format",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=["Invalid symbol format"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Check direction validation
        if signal.direction not in [Direction.LONG, Direction.SHORT]:
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning="invalid direction",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=["Invalid direction"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Check reasoning validation
        if not signal.reasoning or signal.reasoning.strip() == "":
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning="reasoning cannot be empty",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=["Empty reasoning"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Check timestamp validation
        if signal.timestamp > datetime.now(timezone.utc):
            return SignalValidationResult(
                is_valid=False,
                valid_signals=[],
                invalid_signals=[signal],
                reasoning="timestamp cannot be in the future",
                overall_confidence=signal.confidence,
                confidence_score=signal.confidence,
                validation_reasons=["Future timestamp"],
                filtered_signals=[],
                risk_level="HIGH"
            )
        
        # Signal is valid
        return SignalValidationResult(
            is_valid=True,
            valid_signals=[signal],
            invalid_signals=[],
            reasoning="Signal passed all validation criteria",
            overall_confidence=signal.confidence,
            confidence_score=signal.confidence,
            validation_reasons=["All validation criteria passed"],
            filtered_signals=[],
            risk_level="LOW"
        )
    
    def get_validation_statistics(self) -> Dict[str, float]:
        """Get validation statistics"""
        return self.validation_stats.copy()
    
    def clear_validation_history(self):
        """Clear validation history and statistics"""
        self.signal_history.clear()
        self.validation_stats = {
            "total_signals_validated": 0,
            "valid_signals_count": 0,
            "invalid_signals_count": 0,
            "validation_success_rate": 0.0,
            "avg_confidence": 0.0
        }
    
    def _filter_basic_criteria(self, signals: List[TechnicalSignal]) -> List[TechnicalSignal]:
        """Filter signals by basic criteria"""
        filtered = []
        
        for signal in signals:
            # Check minimum strength
            if signal.strength < self.min_signal_strength:
                continue
            
            # Check for valid indicators
            if not signal.indicators:
                continue
            
            # Check for reasonable indicator values
            valid_indicators = True
            for name, value in signal.indicators.items():
                if not isinstance(value, (int, float)):
                    valid_indicators = False
                    break
                if not (-1000 < value < 1000):  # Reasonable range
                    valid_indicators = False
                    break
            
            if not valid_indicators:
                continue
            
            filtered.append(signal)
        
        return filtered
    
    def _filter_by_age(self, signals: List[TechnicalSignal]) -> List[TechnicalSignal]:
        """Filter signals by age"""
        current_time = datetime.now()
        max_age = timedelta(minutes=self.max_signal_age_minutes)
        
        filtered = []
        for signal in signals:
            age = current_time - signal.timestamp
            if age <= max_age:
                filtered.append(signal)
        
        return filtered
    
    def _filter_conflicting_signals(self, signals: List[TechnicalSignal]) -> List[TechnicalSignal]:
        """Filter out conflicting signals, keeping the strongest"""
        if len(signals) <= 1:
            return signals
        
        # Group by signal type
        buy_signals = [s for s in signals if s.signal_type == SignalType.BUY]
        sell_signals = [s for s in signals if s.signal_type == SignalType.SELL]
        hold_signals = [s for s in signals if s.signal_type == SignalType.HOLD]
        
        filtered = []
        
        # If we have both buy and sell signals, keep the stronger group
        if buy_signals and sell_signals:
            buy_strength = sum(s.strength for s in buy_signals) / len(buy_signals)
            sell_strength = sum(s.strength for s in sell_signals) / len(sell_signals)
            
            if buy_strength > sell_strength:
                filtered.extend(buy_signals)
            else:
                filtered.extend(sell_signals)
        else:
            # No conflict, keep all
            filtered.extend(buy_signals)
            filtered.extend(sell_signals)
        
        # Always keep hold signals
        filtered.extend(hold_signals)
        
        return filtered
    
    def _filter_against_trend(self, signals: List[TechnicalSignal], 
                             trend_analysis: TrendAnalysis) -> List[TechnicalSignal]:
        """Filter signals that go against the trend"""
        if trend_analysis.trend_direction == "SIDEWAYS":
            return signals  # All signals valid in sideways market
        
        filtered = []
        
        for signal in signals:
            # Check if signal aligns with trend
            if trend_analysis.trend_direction == "UPTREND":
                if signal.signal_type in [SignalType.BUY, SignalType.HOLD]:
                    filtered.append(signal)
                elif signal.signal_type == SignalType.SELL:
                    # Only allow sell signals if trend is weakening
                    if trend_analysis.trend_strength < 0.5:
                        filtered.append(signal)
            
            elif trend_analysis.trend_direction == "DOWNTREND":
                if signal.signal_type in [SignalType.SELL, SignalType.HOLD]:
                    filtered.append(signal)
                elif signal.signal_type == SignalType.BUY:
                    # Only allow buy signals if trend is weakening
                    if trend_analysis.trend_strength < 0.5:
                        filtered.append(signal)
        
        return filtered
    
    def _calculate_confluence(self, signals: List[TechnicalSignal]) -> float:
        """Calculate signal confluence score"""
        if not signals:
            return 0.0
        
        # Count signals by type
        signal_counts = {}
        for signal in signals:
            signal_type = signal.signal_type
            if signal_type not in signal_counts:
                signal_counts[signal_type] = []
            signal_counts[signal_type].append(signal)
        
        # Calculate confluence based on agreement
        total_signals = len(signals)
        max_agreement = max(len(signals_list) for signals_list in signal_counts.values())
        
        confluence = max_agreement / total_signals
        
        # Boost confluence for multiple strong signals
        if max_agreement >= 3:
            strong_signals = sum(1 for s in signals if s.strength >= 0.7)
            if strong_signals >= 2:
                confluence = min(confluence * 1.2, 1.0)
        
        return confluence
    
    def _update_signal_persistence(self, signals: List[TechnicalSignal], symbol: str):
        """Update signal persistence tracking"""
        if symbol not in self.signal_history:
            self.signal_history[symbol] = []
        
        current_time = datetime.now()
        
        # Group current signals by type
        current_signal_types = {}
        for signal in signals:
            signal_type = signal.signal_type
            if signal_type not in current_signal_types:
                current_signal_types[signal_type] = []
            current_signal_types[signal_type].append(signal)
        
        # Update persistence for each signal type
        for signal_type, signal_list in current_signal_types.items():
            avg_strength = sum(s.strength for s in signal_list) / len(signal_list)
            
            # Find existing persistence record
            existing_persistence = None
            for persistence in self.signal_history[symbol]:
                if (persistence.signal_type == signal_type and 
                    (current_time - persistence.last_seen).total_seconds() < 3600):  # Within 1 hour
                    existing_persistence = persistence
                    break
            
            if existing_persistence:
                # Update existing record
                existing_persistence.last_seen = current_time
                existing_persistence.occurrence_count += 1
                existing_persistence.average_strength = (
                    (existing_persistence.average_strength * (existing_persistence.occurrence_count - 1) + avg_strength) /
                    existing_persistence.occurrence_count
                )
                existing_persistence.is_persistent = existing_persistence.occurrence_count >= self.persistence_threshold
            else:
                # Create new persistence record
                new_persistence = SignalPersistence(
                    signal_type=signal_type,
                    first_seen=current_time,
                    last_seen=current_time,
                    occurrence_count=1,
                    average_strength=avg_strength,
                    is_persistent=False
                )
                self.signal_history[symbol].append(new_persistence)
        
        # Clean up old persistence records (older than 24 hours)
        cutoff_time = current_time - timedelta(hours=24)
        self.signal_history[symbol] = [
            p for p in self.signal_history[symbol] 
            if p.last_seen > cutoff_time
        ]
    
    def _check_signal_persistence(self, signals: List[TechnicalSignal], symbol: str) -> float:
        """Check signal persistence score"""
        if not signals or symbol not in self.signal_history:
            return 0.0
        
        persistence_scores = []
        
        for signal in signals:
            signal_type = signal.signal_type
            
            # Find matching persistence record
            for persistence in self.signal_history[symbol]:
                if persistence.signal_type == signal_type:
                    if persistence.is_persistent:
                        # Boost score for persistent signals
                        score = min(persistence.occurrence_count / 10.0, 1.0)
                        persistence_scores.append(score)
                    else:
                        # Lower score for non-persistent signals
                        score = persistence.occurrence_count / self.persistence_threshold * 0.5
                        persistence_scores.append(score)
                    break
            else:
                # New signal, no persistence
                persistence_scores.append(0.1)
        
        return sum(persistence_scores) / len(persistence_scores) if persistence_scores else 0.0
    
    def _calculate_final_confidence(self, 
                                   signals: List[TechnicalSignal],
                                   confluence_score: float,
                                   persistence_score: float,
                                   trend_analysis: TrendAnalysis = None) -> float:
        """Calculate final confidence score"""
        if not signals:
            return 0.0
        
        # Base confidence from signal strengths
        avg_strength = sum(s.strength for s in signals) / len(signals)
        
        # Weight the components
        strength_weight = 0.4
        confluence_weight = 0.3
        persistence_weight = 0.2
        trend_weight = 0.1
        
        confidence = (avg_strength * strength_weight +
                     confluence_score * confluence_weight +
                     persistence_score * persistence_weight)
        
        # Add trend confirmation bonus
        if trend_analysis and trend_analysis.trend_confidence > 0.5:
            trend_bonus = trend_analysis.trend_confidence * trend_weight
            confidence += trend_bonus
        
        return min(confidence, 1.0)
    
    def _assess_risk_level(self, 
                          signals: List[TechnicalSignal],
                          confidence_score: float,
                          trend_analysis: TrendAnalysis = None) -> str:
        """Assess risk level of the signals"""
        
        # Start with medium risk
        risk_factors = 0
        
        # Low confidence increases risk
        if confidence_score < 0.4:
            risk_factors += 2
        elif confidence_score < 0.6:
            risk_factors += 1
        
        # Few signals increase risk
        if len(signals) < 2:
            risk_factors += 1
        
        # Weak signals increase risk
        weak_signals = sum(1 for s in signals if s.strength < 0.5)
        if weak_signals > len(signals) / 2:
            risk_factors += 1
        
        # Trend uncertainty increases risk
        if trend_analysis:
            if trend_analysis.trend_direction == "SIDEWAYS":
                risk_factors += 1
            elif trend_analysis.trend_confidence < 0.5:
                risk_factors += 1
        else:
            risk_factors += 1  # No trend analysis
        
        # Determine risk level
        if risk_factors >= 4:
            return "HIGH"
        elif risk_factors >= 2:
            return "MEDIUM"
        else:
            return "LOW"
    
    def get_signal_quality_metrics(self, signals: List[TechnicalSignal]) -> Dict[str, float]:
        """Get quality metrics for signals"""
        if not signals:
            return {
                "average_strength": 0.0,
                "strength_consistency": 0.0,
                "signal_diversity": 0.0,
                "temporal_consistency": 0.0
            }
        
        # Average strength
        avg_strength = sum(s.strength for s in signals) / len(signals)
        
        # Strength consistency (lower std dev = more consistent)
        strengths = [s.strength for s in signals]
        strength_std = np.std(strengths) if len(strengths) > 1 else 0.0
        strength_consistency = max(0.0, 1.0 - strength_std)
        
        # Signal diversity (different indicator types)
        unique_indicators = set()
        for signal in signals:
            unique_indicators.update(signal.indicators.keys())
        signal_diversity = min(len(unique_indicators) / 5.0, 1.0)  # Normalize to max 5 types
        
        # Temporal consistency (signals close in time)
        if len(signals) > 1:
            timestamps = [s.timestamp for s in signals]
            time_span = (max(timestamps) - min(timestamps)).total_seconds()
            temporal_consistency = max(0.0, 1.0 - (time_span / 3600.0))  # 1 hour max span
        else:
            temporal_consistency = 1.0
        
        return {
            "average_strength": avg_strength,
            "strength_consistency": strength_consistency,
            "signal_diversity": signal_diversity,
            "temporal_consistency": temporal_consistency
        }
    
    def clear_signal_history(self, symbol: str = None):
        """Clear signal persistence history"""
        if symbol:
            if symbol in self.signal_history:
                del self.signal_history[symbol]
        else:
            self.signal_history.clear()
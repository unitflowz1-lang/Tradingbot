"""
Signal Strength and Quality Analyzer
Evaluates signal quality based on multiple confluence factors
"""

import logging
from dataclasses import dataclass
from typing import Optional, List, Dict
from enum import Enum

from src.models import Direction, TechnicalSignal, SignalType


class SignalQuality(Enum):
    """Signal quality levels"""
    POOR = 0.3       # < 0.4
    WEAK = 0.5       # 0.4-0.6
    MODERATE = 0.7   # 0.6-0.75
    STRONG = 0.85    # 0.75-0.90
    EXCELLENT = 0.95 # > 0.90


@dataclass
class SignalQualityAnalysis:
    """Result of signal quality analysis"""
    quality_score: float  # 0-1
    quality_level: SignalQuality
    confluence_count: int  # Number of confirming signals
    entry_filters_passed: bool
    trend_alignment: float  # 0-1 score
    volume_confirmation: bool
    time_of_day_score: float  # 0-1, penalizes low-volume times
    risk_reward_ratio: float
    reasoning: str


class SignalStrengthCalculator:
    """Calculates signal strength based on multiple factors"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Configuration
        self.require_rsi_filter = True        # RSI not in overbought/oversold
        self.require_adx_minimum = 20         # Trend strength minimum
        self.require_volume_confirmation = True
        self.penalize_asian_session = False    # Do not handicap Sydney/Tokyo session quality
        self.penalize_low_volume_times = True
    
    def analyze_signal_quality(self,
                              technical_signals: List[TechnicalSignal],
                              indicators: Dict,
                              current_price: float,
                              direction: Direction,
                              volume: Optional[int] = None,
                              hour_of_day: Optional[int] = None) -> SignalQualityAnalysis:
        """
        Analyze quality of trading signal based on multiple factors
        
        Args:
            technical_signals: List of technical signals
            indicators: Dictionary of technical indicators (RSI, ADX, etc.)
            current_price: Current market price
            direction: Trade direction (LONG/SHORT)
            volume: Current volume
            hour_of_day: Hour in UTC for time-of-day analysis
            
        Returns:
            SignalQualityAnalysis with detailed quality breakdown
        """
        
        quality_components = {}
        
        # 1. Confluence Score (how many signals agree)
        confluence_score, confluence_count = self._calculate_confluence(
            technical_signals, direction
        )
        quality_components['confluence'] = confluence_score
        
        # 2. Entry Filters
        filters_passed, filters_score = self._check_entry_filters(indicators, direction)
        quality_components['filters'] = filters_score
        
        # 3. Trend Alignment (ADX strength)
        trend_score = self._calculate_trend_score(indicators)
        quality_components['trend'] = trend_score
        
        # 4. Volume Confirmation
        volume_confirmed = self._check_volume_confirmation(volume)
        quality_components['volume'] = 0.8 if volume_confirmed else 0.3
        
        # 5. Time of Day Score
        time_score = self._calculate_time_of_day_score(hour_of_day)
        quality_components['time'] = time_score
        
        # 6. Signal Strength
        strength_score = self._calculate_signal_strength(technical_signals)
        quality_components['strength'] = strength_score
        
        # 7. Risk/Reward (estimate from indicators)
        rr_score, rr_ratio = self._estimate_risk_reward(indicators, direction)
        quality_components['rr'] = rr_score
        
        # Weighted aggregate score
        weights = {
            'confluence': 0.25,
            'filters': 0.20,
            'trend': 0.20,
            'volume': 0.10,
            'time': 0.05,
            'strength': 0.15,
            'rr': 0.05
        }
        
        quality_score = sum(
            quality_components.get(key, 0) * weight
            for key, weight in weights.items()
        )
        quality_score = min(1.0, max(0.0, quality_score))  # Clamp to 0-1
        
        # Determine quality level
        if quality_score >= 0.90:
            quality_level = SignalQuality.EXCELLENT
        elif quality_score >= 0.75:
            quality_level = SignalQuality.STRONG
        elif quality_score >= 0.60:
            quality_level = SignalQuality.MODERATE
        elif quality_score >= 0.40:
            quality_level = SignalQuality.WEAK
        else:
            quality_level = SignalQuality.POOR
        
        # Build reasoning
        reasoning = self._build_reasoning(
            quality_components, confluence_count, filters_passed
        )
        
        return SignalQualityAnalysis(
            quality_score=quality_score,
            quality_level=quality_level,
            confluence_count=confluence_count,
            entry_filters_passed=filters_passed,
            trend_alignment=trend_score,
            volume_confirmation=volume_confirmed,
            time_of_day_score=time_score,
            risk_reward_ratio=rr_ratio,
            reasoning=reasoning
        )
    
    def _calculate_confluence(self,
                             technical_signals: List[TechnicalSignal],
                             direction: Direction) -> tuple:
        """Calculate how many signals agree on direction"""
        if not technical_signals:
            return 0.3, 0  # Low score if no signals
        
        agreeing_signals = 0
        for signal in technical_signals:
            signal_direction = (
                Direction.LONG if signal.signal_type == SignalType.BUY else Direction.SHORT
            )
            if signal_direction == direction:
                agreeing_signals += signal.strength
        
        confluence_ratio = agreeing_signals / len(technical_signals) if technical_signals else 0
        # Score: perfect confluence = 1.0, minimum = 0.3
        confluence_score = 0.3 + (confluence_ratio * 0.7)
        confluence_count = sum(1 for s in technical_signals if (
            (s.signal_type == SignalType.BUY and direction == Direction.LONG) or
            (s.signal_type == SignalType.SELL and direction == Direction.SHORT)
        ))
        
        return confluence_score, confluence_count
    
    def _check_entry_filters(self, indicators: Dict, direction: Direction) -> tuple:
        """Check if signal passes basic entry filters"""
        score = 1.0
        
        # RSI filter - avoid extremes
        rsi = indicators.get('rsi') or indicators.get('RSI')
        if rsi is not None and self.require_rsi_filter:
            if direction == Direction.LONG:
                # For BUY: prefer RSI < 70 (not overbought)
                if rsi > 70:
                    score -= 0.2
                if rsi < 30:
                    score += 0.1  # Oversold = good setup
            else:  # SHORT
                # For SELL: prefer RSI > 25 (not oversold)
                if rsi < 25:
                    score -= 0.2
                if rsi > 70:
                    score += 0.1  # Overbought = good setup
        
        # ADX filter - trend strength
        adx = indicators.get('adx') or indicators.get('ADX')
        if adx is not None and self.require_adx_minimum:
            if adx < self.require_adx_minimum:
                score -= 0.3  # Weak trend
            elif adx > 40:
                score += 0.1  # Very strong trend
        
        filters_passed = score > 0.5
        return filters_passed, score
    
    def _calculate_trend_score(self, indicators: Dict) -> float:
        """Score based on trend strength (ADX)"""
        adx = indicators.get('adx') or indicators.get('ADX')
        if adx is None:
            return 0.5  # Neutral
        
        # ADX 0-14: Weak trend (0.3)
        # ADX 14-25: Moderate trend (0.6)
        # ADX 25-40: Strong trend (0.9)
        # ADX 40+: Very strong trend (1.0)
        
        if adx < 14:
            return 0.3
        elif adx < 25:
            return 0.5 + (adx - 14) / 22 * 0.1
        elif adx < 40:
            return 0.6 + (adx - 25) / 15 * 0.3
        else:
            return 1.0
    
    def _check_volume_confirmation(self, volume: Optional[int]) -> bool:
        """Check if volume confirms the move"""
        if not self.require_volume_confirmation or volume is None:
            return True
        
        # Simple heuristic: above-average volume is good
        # In real implementation, compare to MA of volume
        return volume > 10000  # Arbitrary threshold
    
    def _calculate_time_of_day_score(self, hour_of_day: Optional[int]) -> float:
        """Score based on time of day (UTC)"""
        if hour_of_day is None:
            return 0.8  # Neutral
        
        # Prefer London/US overlap hours (8-16 UTC)
        if 8 <= hour_of_day <= 16:
            return 1.0
        # Moderate: 6-8 and 16-20 UTC
        elif 6 <= hour_of_day <= 20:
            return 0.8
        # Low: Asian session 20-6 UTC
        elif self.penalize_asian_session:
            return 0.5
        else:
            return 1.0
    
    def _calculate_signal_strength(self, technical_signals: List[TechnicalSignal]) -> float:
        """Calculate average strength of all signals"""
        if not technical_signals:
            return 0.3
        
        avg_strength = sum(s.strength for s in technical_signals) / len(technical_signals)
        return avg_strength
    
    def _estimate_risk_reward(self, indicators: Dict, direction: Direction) -> tuple:
        """Estimate risk/reward ratio from indicators"""
        # This is simplified - in practice use ATR or other volatility measures
        volatility_score = 0.7  # Default
        
        atr = indicators.get('atr') or indicators.get('ATR')
        if atr is not None and atr > 0:
            # Higher ATR = more room for profit targets
            volatility_score = min(1.0, atr * 100)
        
        # Prefer RR of 1.5+ for good risk management
        # Score based on theoretical RR potential
        rr_ratio = 1.5
        rr_score = min(1.0, rr_ratio / 2.0)
        
        return rr_score, rr_ratio
    
    def _build_reasoning(self, components: Dict, confluence_count: int,
                        filters_passed: bool) -> str:
        """Build human-readable reasoning for signal quality"""
        reasons = []
        
        confluence = components.get('confluence', 0)
        if confluence > 0.8:
            reasons.append(f"Strong confluence ({confluence:.0%})")
        
        if confluence_count >= 2:
            reasons.append(f"{confluence_count} confirming signals")
        
        if filters_passed:
            reasons.append("Entry filters passed")
        else:
            reasons.append("⚠️ Some filters not passed")
        
        trend = components.get('trend', 0)
        if trend > 0.8:
            reasons.append("Strong trend")
        elif trend > 0.5:
            reasons.append("Moderate trend")
        else:
            reasons.append("⚠️ Weak trend")
        
        return " | ".join(reasons)

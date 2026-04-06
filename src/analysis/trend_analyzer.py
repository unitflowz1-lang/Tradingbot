"""Trend analysis for determining overall market direction"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from src.models import MarketData, TechnicalSignal
from src.analysis.technical_indicators import TechnicalIndicators
from src.exceptions import DataValidationError


@dataclass
class TrendAnalysis:
    """Result of trend analysis"""
    symbol: str
    timestamp: datetime
    trend_direction: str  # "UPTREND", "DOWNTREND", "SIDEWAYS"
    trend_strength: float  # 0.0 to 1.0
    trend_duration: int  # Number of periods
    support_level: Optional[float] = None
    resistance_level: Optional[float] = None
    trend_confidence: float = 0.0  # 0.0 to 1.0


class TrendAnalyzer:
    """Analyze market trends and determine overall direction"""
    
    def __init__(self, 
                 min_trend_periods: int = 10,
                 trend_threshold: float = 0.001,  # 0.1% minimum price change
                 sideways_threshold: float = 0.005):  # 0.5% range for sideways
        """Initialize trend analyzer"""
        self.min_trend_periods = min_trend_periods
        self.trend_threshold = trend_threshold
        self.sideways_threshold = sideways_threshold
    
    def analyze_trend(self, 
                     market_data: List[MarketData],
                     indicators: TechnicalIndicators = None,
                     lookback_periods: int = 50) -> TrendAnalysis:
        """Analyze trend from market data and indicators"""
        
        if len(market_data) < self.min_trend_periods:
            raise DataValidationError(
                f"Need at least {self.min_trend_periods} periods for trend analysis",
                error_code="INSUFFICIENT_DATA",
                context={"periods": len(market_data), "required": self.min_trend_periods}
            )
        
        # Use last N periods
        data = market_data[-lookback_periods:] if len(market_data) > lookback_periods else market_data
        
        # Extract price data
        closes = np.array([d.close for d in data])
        highs = np.array([d.high for d in data])
        lows = np.array([d.low for d in data])
        timestamps = [d.timestamp for d in data]
        
        # Calculate trend direction using multiple methods
        price_trend = self._analyze_price_trend(closes)
        ma_trend = self._analyze_moving_average_trend(indicators) if indicators else None
        volume_trend = self._analyze_volume_trend(data)
        
        # Combine trend signals
        trend_direction, trend_strength = self._combine_trend_signals(
            price_trend, ma_trend, volume_trend
        )
        
        # Calculate trend duration
        trend_duration = self._calculate_trend_duration(closes, trend_direction)
        
        # Find support and resistance levels
        support_level, resistance_level = self._find_key_levels(highs, lows, closes)
        
        # Calculate trend confidence
        trend_confidence = self._calculate_trend_confidence(
            trend_strength, trend_duration, indicators
        )
        
        return TrendAnalysis(
            symbol=data[-1].symbol,
            timestamp=data[-1].timestamp,
            trend_direction=trend_direction,
            trend_strength=trend_strength,
            trend_duration=trend_duration,
            support_level=support_level,
            resistance_level=resistance_level,
            trend_confidence=trend_confidence
        )
    
    def _analyze_price_trend(self, closes: np.ndarray) -> Dict[str, float]:
        """Analyze trend from price action"""
        if len(closes) < 2:
            return {"direction": "SIDEWAYS", "strength": 0.0}
        
        # Calculate linear regression slope
        x = np.arange(len(closes))
        slope, intercept = np.polyfit(x, closes, 1)
        
        # Calculate R-squared for trend strength
        y_pred = slope * x + intercept
        ss_res = np.sum((closes - y_pred) ** 2)
        ss_tot = np.sum((closes - np.mean(closes)) ** 2)
        r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
        
        # Determine trend direction
        price_change_pct = abs(slope) / closes[0] if closes[0] != 0 else 0
        
        if price_change_pct < self.trend_threshold:
            direction = "SIDEWAYS"
        elif slope > 0:
            direction = "UPTREND"
        else:
            direction = "DOWNTREND"
        
        # Calculate strength based on slope magnitude and R-squared
        strength = min(price_change_pct * 100 * r_squared, 1.0)
        
        return {
            "direction": direction,
            "strength": strength,
            "slope": slope,
            "r_squared": r_squared
        }
    
    def _analyze_moving_average_trend(self, indicators: TechnicalIndicators) -> Optional[Dict[str, float]]:
        """Analyze trend from moving averages"""
        if not indicators or not indicators.sma_20 or not indicators.sma_50:
            return None
        
        sma_20 = indicators.sma_20
        sma_50 = indicators.sma_50
        
        # Calculate MA spread
        ma_diff = sma_20 - sma_50
        ma_diff_pct = abs(ma_diff) / sma_50 if sma_50 != 0 else 0
        
        # Determine direction
        if ma_diff_pct < self.trend_threshold:
            direction = "SIDEWAYS"
        elif ma_diff > 0:
            direction = "UPTREND"
        else:
            direction = "DOWNTREND"
        
        # Strength based on MA separation
        strength = min(ma_diff_pct * 50, 1.0)  # Scale appropriately
        
        return {
            "direction": direction,
            "strength": strength,
            "ma_diff": ma_diff,
            "ma_diff_pct": ma_diff_pct
        }
    
    def _analyze_volume_trend(self, data: List[MarketData]) -> Dict[str, float]:
        """Analyze trend from volume patterns"""
        if len(data) < 10:
            return {"direction": "NEUTRAL", "strength": 0.0}
        
        # Calculate volume moving averages
        volumes = np.array([d.volume for d in data])
        recent_volume = np.mean(volumes[-5:])  # Last 5 periods
        avg_volume = np.mean(volumes[:-5])     # Previous periods
        
        volume_ratio = recent_volume / avg_volume if avg_volume > 0 else 1.0
        
        # High volume suggests trend continuation
        if volume_ratio > 1.2:  # 20% above average
            strength = min((volume_ratio - 1.0) * 2, 1.0)
            direction = "CONFIRMING"
        elif volume_ratio < 0.8:  # 20% below average
            strength = min((1.0 - volume_ratio) * 2, 1.0)
            direction = "WEAKENING"
        else:
            strength = 0.5
            direction = "NEUTRAL"
        
        return {
            "direction": direction,
            "strength": strength,
            "volume_ratio": volume_ratio
        }
    
    def _combine_trend_signals(self, 
                              price_trend: Dict[str, float],
                              ma_trend: Optional[Dict[str, float]],
                              volume_trend: Dict[str, float]) -> Tuple[str, float]:
        """Combine multiple trend signals"""
        
        # Weight the signals
        price_weight = 0.5
        ma_weight = 0.3 if ma_trend else 0.0
        volume_weight = 0.2
        
        # Adjust weights if MA trend is not available
        if not ma_trend:
            price_weight = 0.7
            volume_weight = 0.3
        
        # Count directional votes
        uptrend_votes = 0
        downtrend_votes = 0
        sideways_votes = 0
        
        total_strength = 0.0
        
        # Price trend vote
        if price_trend["direction"] == "UPTREND":
            uptrend_votes += price_weight
        elif price_trend["direction"] == "DOWNTREND":
            downtrend_votes += price_weight
        else:
            sideways_votes += price_weight
        
        total_strength += price_trend["strength"] * price_weight
        
        # MA trend vote
        if ma_trend:
            if ma_trend["direction"] == "UPTREND":
                uptrend_votes += ma_weight
            elif ma_trend["direction"] == "DOWNTREND":
                downtrend_votes += ma_weight
            else:
                sideways_votes += ma_weight
            
            total_strength += ma_trend["strength"] * ma_weight
        
        # Volume doesn't vote on direction but affects strength
        if volume_trend["direction"] == "CONFIRMING":
            total_strength *= 1.2  # Boost strength
        elif volume_trend["direction"] == "WEAKENING":
            total_strength *= 0.8  # Reduce strength
        
        # Determine final direction
        if uptrend_votes > downtrend_votes and uptrend_votes > sideways_votes:
            direction = "UPTREND"
        elif downtrend_votes > uptrend_votes and downtrend_votes > sideways_votes:
            direction = "DOWNTREND"
        else:
            direction = "SIDEWAYS"
        
        # Normalize strength
        strength = min(total_strength, 1.0)
        
        return direction, strength
    
    def _calculate_trend_duration(self, closes: np.ndarray, trend_direction: str) -> int:
        """Calculate how long the current trend has been in place"""
        if len(closes) < 3 or trend_direction == "SIDEWAYS":
            return 0
        
        # Look backwards to find trend start
        duration = 1
        
        if trend_direction == "UPTREND":
            # Count consecutive periods where price is generally rising
            for i in range(len(closes) - 2, 0, -1):
                if closes[i] >= closes[i-1] * (1 - self.trend_threshold):
                    duration += 1
                else:
                    break
        
        elif trend_direction == "DOWNTREND":
            # Count consecutive periods where price is generally falling
            for i in range(len(closes) - 2, 0, -1):
                if closes[i] <= closes[i-1] * (1 + self.trend_threshold):
                    duration += 1
                else:
                    break
        
        return min(duration, len(closes))
    
    def _find_key_levels(self, highs: np.ndarray, lows: np.ndarray, 
                        closes: np.ndarray) -> Tuple[Optional[float], Optional[float]]:
        """Find key support and resistance levels"""
        if len(closes) < 5:  # Reduced minimum requirement
            return None, None
        
        # Find recent support (lowest low in last 20 periods)
        recent_lows = lows[-20:] if len(lows) > 20 else lows
        support_level = float(np.min(recent_lows))
        
        # Find recent resistance (highest high in last 20 periods)
        recent_highs = highs[-20:] if len(highs) > 20 else highs
        resistance_level = float(np.max(recent_highs))
        
        # Validate levels make sense
        current_price = closes[-1]
        if support_level >= current_price:
            support_level = current_price * 0.99  # 1% below current price
        
        if resistance_level <= current_price:
            resistance_level = current_price * 1.01  # 1% above current price
        
        return support_level, resistance_level
    
    def _calculate_trend_confidence(self, 
                                   trend_strength: float,
                                   trend_duration: int,
                                   indicators: TechnicalIndicators = None) -> float:
        """Calculate confidence in the trend analysis"""
        
        # Base confidence from trend strength
        confidence = trend_strength
        
        # Boost confidence for longer trends
        duration_boost = min(trend_duration / 20.0, 0.3)  # Max 30% boost
        confidence += duration_boost
        
        # Additional confidence from indicators
        if indicators:
            indicator_confidence = 0.0
            
            # RSI confirmation
            if indicators.rsi is not None:
                if 30 <= indicators.rsi <= 70:  # RSI in normal range
                    indicator_confidence += 0.1
            
            # MACD confirmation
            if (indicators.macd is not None and 
                indicators.macd_signal is not None):
                if abs(indicators.macd - indicators.macd_signal) > 0.0001:
                    indicator_confidence += 0.1
            
            confidence += indicator_confidence
        
        return min(confidence, 1.0)
    
    def is_trend_strong(self, trend_analysis: TrendAnalysis, 
                       strength_threshold: float = 0.6) -> bool:
        """Check if trend is considered strong"""
        return (trend_analysis.trend_strength >= strength_threshold and
                trend_analysis.trend_confidence >= 0.5 and
                trend_analysis.trend_duration >= 5)
    
    def is_trend_weakening(self, 
                          current_analysis: TrendAnalysis,
                          previous_analysis: TrendAnalysis) -> bool:
        """Check if trend is weakening compared to previous analysis"""
        if current_analysis.trend_direction != previous_analysis.trend_direction:
            return True
        
        strength_decline = previous_analysis.trend_strength - current_analysis.trend_strength
        confidence_decline = previous_analysis.trend_confidence - current_analysis.trend_confidence
        
        return strength_decline > 0.2 or confidence_decline > 0.2
    
    def get_trend_targets(self, trend_analysis: TrendAnalysis,
                         current_price: float) -> Dict[str, Optional[float]]:
        """Get potential price targets based on trend analysis"""
        targets = {
            "support_target": trend_analysis.support_level,
            "resistance_target": trend_analysis.resistance_level,
            "trend_target": None
        }
        
        if trend_analysis.trend_direction == "UPTREND" and trend_analysis.resistance_level:
            # Calculate uptrend target beyond resistance
            resistance_distance = trend_analysis.resistance_level - current_price
            targets["trend_target"] = trend_analysis.resistance_level + (resistance_distance * 0.5)
        
        elif trend_analysis.trend_direction == "DOWNTREND" and trend_analysis.support_level:
            # Calculate downtrend target below support
            support_distance = current_price - trend_analysis.support_level
            targets["trend_target"] = trend_analysis.support_level - (support_distance * 0.5)
        
        return targets
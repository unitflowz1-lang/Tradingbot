"""Pattern recognition for technical analysis"""

import numpy as np
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
from src.models import MarketData
from src.analysis.technical_indicators import TechnicalIndicators
from src.exceptions import DataValidationError


@dataclass
class SupportResistanceLevel:
    """Support or resistance level"""
    price: float
    strength: float  # 0.0 to 1.0
    level_type: str  # "SUPPORT" or "RESISTANCE"
    touches: int
    last_touch: datetime


@dataclass
class ChartPattern:
    """Detected chart pattern"""
    pattern_type: str  # "DOUBLE_TOP", "DOUBLE_BOTTOM", "HEAD_SHOULDERS", etc.
    confidence: float  # 0.0 to 1.0
    start_time: datetime
    end_time: datetime
    key_levels: List[float]
    expected_direction: str  # "BULLISH" or "BEARISH"


class PatternRecognizer:
    """Recognize chart patterns and support/resistance levels"""
    
    def __init__(self, min_touches: int = 2, strength_threshold: float = 0.5):
        """Initialize pattern recognizer"""
        self.min_touches = min_touches
        self.strength_threshold = strength_threshold
        self.price_tolerance = 0.001  # 0.1% tolerance for level matching
    
    def find_support_resistance_levels(self, market_data: List[MarketData], 
                                     lookback_periods: int = 50) -> List[SupportResistanceLevel]:
        """Find support and resistance levels from market data"""
        if len(market_data) < 10:
            raise DataValidationError(
                "Need at least 10 periods for support/resistance analysis",
                error_code="INSUFFICIENT_DATA",
                context={"periods": len(market_data)}
            )
        
        # Use last N periods
        data = market_data[-lookback_periods:] if len(market_data) > lookback_periods else market_data
        
        # Extract price levels (highs and lows)
        highs = [(d.high, d.timestamp, "RESISTANCE") for d in data]
        lows = [(d.low, d.timestamp, "SUPPORT") for d in data]
        
        all_levels = highs + lows
        
        # Find significant levels
        levels = []
        
        for price, timestamp, level_type in all_levels:
            # Count touches within tolerance
            touches = self._count_touches(price, all_levels, level_type)
            
            if touches >= self.min_touches:
                strength = min(touches / 5.0, 1.0)  # Normalize to 0-1
                
                level = SupportResistanceLevel(
                    price=price,
                    strength=strength,
                    level_type=level_type,
                    touches=touches,
                    last_touch=timestamp
                )
                levels.append(level)
        
        # Remove duplicate levels (within tolerance)
        levels = self._remove_duplicate_levels(levels)
        
        # Sort by strength
        levels.sort(key=lambda x: x.strength, reverse=True)
        
        return levels[:10]  # Return top 10 levels
    
    def detect_chart_patterns(self, market_data: List[MarketData]) -> List[ChartPattern]:
        """Detect chart patterns in market data"""
        if len(market_data) < 20:
            return []
        
        patterns = []
        
        # Detect double top/bottom patterns
        double_patterns = self._detect_double_patterns(market_data)
        patterns.extend(double_patterns)
        
        # Detect head and shoulders patterns
        hs_patterns = self._detect_head_shoulders(market_data)
        patterns.extend(hs_patterns)
        
        # Detect triangle patterns
        triangle_patterns = self._detect_triangles(market_data)
        patterns.extend(triangle_patterns)
        
        return patterns
    
    def _count_touches(self, target_price: float, all_levels: List[Tuple], 
                      level_type: str) -> int:
        """Count how many times a price level was touched"""
        touches = 0
        tolerance = target_price * self.price_tolerance
        
        for price, _, ltype in all_levels:
            if ltype == level_type and abs(price - target_price) <= tolerance:
                touches += 1
        
        return touches
    
    def _remove_duplicate_levels(self, levels: List[SupportResistanceLevel]) -> List[SupportResistanceLevel]:
        """Remove duplicate levels within tolerance"""
        unique_levels = []
        
        for level in levels:
            is_duplicate = False
            
            for existing in unique_levels:
                if (existing.level_type == level.level_type and 
                    abs(existing.price - level.price) <= existing.price * self.price_tolerance):
                    # Keep the stronger level
                    if level.strength > existing.strength:
                        unique_levels.remove(existing)
                        unique_levels.append(level)
                    is_duplicate = True
                    break
            
            if not is_duplicate:
                unique_levels.append(level)
        
        return unique_levels
    
    def _detect_double_patterns(self, market_data: List[MarketData]) -> List[ChartPattern]:
        """Detect double top and double bottom patterns"""
        patterns = []
        
        if len(market_data) < 30:
            return patterns
        
        # Find local peaks and troughs
        peaks = self._find_local_extremes(market_data, "peaks")
        troughs = self._find_local_extremes(market_data, "troughs")
        
        # Look for double tops
        for i in range(len(peaks) - 1):
            peak1 = peaks[i]
            peak2 = peaks[i + 1]
            
            # Check if peaks are similar in height
            height_diff = abs(peak1['price'] - peak2['price']) / peak1['price']
            
            if height_diff < 0.02:  # Within 2%
                # Find trough between peaks
                between_troughs = [t for t in troughs 
                                 if peak1['time'] < t['time'] < peak2['time']]
                
                if between_troughs:
                    lowest_trough = min(between_troughs, key=lambda x: x['price'])
                    
                    # Validate pattern structure
                    if (peak1['price'] > lowest_trough['price'] * 1.01 and 
                        peak2['price'] > lowest_trough['price'] * 1.01):
                        
                        pattern = ChartPattern(
                            pattern_type="DOUBLE_TOP",
                            confidence=0.7,
                            start_time=peak1['time'],
                            end_time=peak2['time'],
                            key_levels=[peak1['price'], peak2['price'], lowest_trough['price']],
                            expected_direction="BEARISH"
                        )
                        patterns.append(pattern)
        
        # Look for double bottoms (similar logic, inverted)
        for i in range(len(troughs) - 1):
            trough1 = troughs[i]
            trough2 = troughs[i + 1]
            
            height_diff = abs(trough1['price'] - trough2['price']) / trough1['price']
            
            if height_diff < 0.02:
                between_peaks = [p for p in peaks 
                               if trough1['time'] < p['time'] < trough2['time']]
                
                if between_peaks:
                    highest_peak = max(between_peaks, key=lambda x: x['price'])
                    
                    if (trough1['price'] < highest_peak['price'] * 0.99 and 
                        trough2['price'] < highest_peak['price'] * 0.99):
                        
                        pattern = ChartPattern(
                            pattern_type="DOUBLE_BOTTOM",
                            confidence=0.7,
                            start_time=trough1['time'],
                            end_time=trough2['time'],
                            key_levels=[trough1['price'], trough2['price'], highest_peak['price']],
                            expected_direction="BULLISH"
                        )
                        patterns.append(pattern)
        
        return patterns
    
    def _detect_head_shoulders(self, market_data: List[MarketData]) -> List[ChartPattern]:
        """Detect head and shoulders patterns"""
        patterns = []
        
        if len(market_data) < 40:
            return patterns
        
        peaks = self._find_local_extremes(market_data, "peaks")
        
        if len(peaks) < 3:
            return patterns
        
        # Look for head and shoulders pattern (3 peaks)
        for i in range(len(peaks) - 2):
            left_shoulder = peaks[i]
            head = peaks[i + 1]
            right_shoulder = peaks[i + 2]
            
            # Validate pattern structure
            if (head['price'] > left_shoulder['price'] * 1.02 and 
                head['price'] > right_shoulder['price'] * 1.02 and
                abs(left_shoulder['price'] - right_shoulder['price']) / left_shoulder['price'] < 0.05):
                
                pattern = ChartPattern(
                    pattern_type="HEAD_SHOULDERS",
                    confidence=0.8,
                    start_time=left_shoulder['time'],
                    end_time=right_shoulder['time'],
                    key_levels=[left_shoulder['price'], head['price'], right_shoulder['price']],
                    expected_direction="BEARISH"
                )
                patterns.append(pattern)
        
        return patterns
    
    def _detect_triangles(self, market_data: List[MarketData]) -> List[ChartPattern]:
        """Detect triangle patterns (ascending, descending, symmetrical)"""
        patterns = []
        
        if len(market_data) < 30:
            return patterns
        
        # Find trend lines for highs and lows
        highs = [d.high for d in market_data[-20:]]
        lows = [d.low for d in market_data[-20:]]
        times = list(range(len(highs)))
        
        # Calculate trend lines
        high_slope = self._calculate_trend_slope(times, highs)
        low_slope = self._calculate_trend_slope(times, lows)
        
        # Classify triangle type
        if abs(high_slope) < 0.0001 and low_slope > 0.0001:
            # Ascending triangle
            pattern = ChartPattern(
                pattern_type="ASCENDING_TRIANGLE",
                confidence=0.6,
                start_time=market_data[-20].timestamp,
                end_time=market_data[-1].timestamp,
                key_levels=[max(highs), min(lows)],
                expected_direction="BULLISH"
            )
            patterns.append(pattern)
        
        elif high_slope < -0.0001 and abs(low_slope) < 0.0001:
            # Descending triangle
            pattern = ChartPattern(
                pattern_type="DESCENDING_TRIANGLE",
                confidence=0.6,
                start_time=market_data[-20].timestamp,
                end_time=market_data[-1].timestamp,
                key_levels=[max(highs), min(lows)],
                expected_direction="BEARISH"
            )
            patterns.append(pattern)
        
        elif high_slope < -0.0001 and low_slope > 0.0001:
            # Symmetrical triangle
            pattern = ChartPattern(
                pattern_type="SYMMETRICAL_TRIANGLE",
                confidence=0.5,
                start_time=market_data[-20].timestamp,
                end_time=market_data[-1].timestamp,
                key_levels=[max(highs), min(lows)],
                expected_direction="NEUTRAL"
            )
            patterns.append(pattern)
        
        return patterns
    
    def _find_local_extremes(self, market_data: List[MarketData], 
                           extreme_type: str) -> List[Dict]:
        """Find local peaks or troughs"""
        extremes = []
        window = 3  # Look at 3 periods on each side
        
        if extreme_type == "peaks":
            prices = [d.high for d in market_data]
        else:
            prices = [d.low for d in market_data]
        
        for i in range(window, len(prices) - window):
            is_extreme = True
            current_price = prices[i]
            
            # Check if current point is higher/lower than surrounding points
            for j in range(i - window, i + window + 1):
                if j == i:
                    continue
                
                if extreme_type == "peaks":
                    if prices[j] >= current_price:
                        is_extreme = False
                        break
                else:  # troughs
                    if prices[j] <= current_price:
                        is_extreme = False
                        break
            
            if is_extreme:
                extremes.append({
                    'price': current_price,
                    'time': market_data[i].timestamp,
                    'index': i
                })
        
        return extremes
    
    def _calculate_trend_slope(self, x_values: List[int], y_values: List[float]) -> float:
        """Calculate trend line slope using linear regression"""
        if len(x_values) != len(y_values) or len(x_values) < 2:
            return 0.0
        
        n = len(x_values)
        sum_x = sum(x_values)
        sum_y = sum(y_values)
        sum_xy = sum(x * y for x, y in zip(x_values, y_values))
        sum_x2 = sum(x * x for x in x_values)
        
        # Calculate slope using least squares method
        denominator = n * sum_x2 - sum_x * sum_x
        if denominator == 0:
            return 0.0
        
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope
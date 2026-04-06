"""
Adaptive Strictness Controller
File: src/analysis/adaptive_strictness.py

Dynamically adjusts filter thresholds based on market conditions:
- STRICT in trending markets (high confluence required)
- RELAXED in sideways/low-volatility markets (more opportunities)
- GRADUAL transitions between modes (no abrupt changes)

Integrates with AdaptiveSignalFilterer for intelligent threshold management.
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class MarketCondition(Enum):
    """Market condition classification."""
    STRONG_TREND = "STRONG_TREND"      # ADX ≥ 30, ATR increasing
    WEAK_TREND = "WEAK_TREND"          # 20 ≤ ADX < 30
    SIDEWAYS = "SIDEWAYS"              # ADX < 20, low ATR
    CHOPPY = "CHOPPY"                  # ADX < 15, erratic ATR


class StrictnessMode(Enum):
    """Filter strictness modes."""
    STRICT = "STRICT"          # Trending - all filters at full strength
    MODERATE = "MODERATE"      # Weak trend - slight relaxation
    RELAXED = "RELAXED"        # Sideways - filters relaxed for opportunities
    SEMI_STRICT = "SEMI_STRICT"  # Transitioning between modes


class AdaptiveStrictnessController:
    """
    Adaptive filter strictness based on market conditions.
    
    Key Features:
    - Detects trending vs sideways markets
    - Adjusts filter thresholds dynamically
    - Maintains risk controls (SL/TP, position sizing)
    - Gradual transitions (no abrupt changes)
    - Performance tracking by condition
    """
    
    def __init__(self, enable_adaptive: bool = True):
        """
        Initialize adaptive strictness controller.
        
        Args:
            enable_adaptive: Enable adaptive threshold adjustment
        """
        self.enable_adaptive = enable_adaptive
        
        # Market condition history for smoothing
        self.condition_history = deque(maxlen=10)
        self.atr_history = deque(maxlen=20)
        
        # Performance tracking by condition
        self.performance_by_condition = {
            MarketCondition.STRONG_TREND: {'trades': 0, 'wins': 0, 'profit': 0.0},
            MarketCondition.WEAK_TREND: {'trades': 0, 'wins': 0, 'profit': 0.0},
            MarketCondition.SIDEWAYS: {'trades': 0, 'wins': 0, 'profit': 0.0},
            MarketCondition.CHOPPY: {'trades': 0, 'wins': 0, 'profit': 0.0}
        }
        
        # Threshold adjustment tracking
        self.current_adjustments = {}
        self.transition_step = 0.0  # For gradual transitions (0.0 to 1.0)
        
    def detect_market_condition(self, analysis_data: Dict[str, Any]) -> MarketCondition:
        """
        Detect current market condition based on ADX and ATR.
        
        Thresholds:
        - STRONG_TREND: ADX ≥ 30 or (ADX ≥ 25 and ATR increasing >10%)
        - WEAK_TREND: 20 ≤ ADX < 30
        - SIDEWAYS: ADX < 20 and ATR stable
        - CHOPPY: ADX < 15 and ATR erratic
        
        Args:
            analysis_data: Technical indicators
            
        Returns:
            MarketCondition enum
        """
        adx = analysis_data.get('adx', 20)
        atr = analysis_data.get('atr', 0)
        atr_mean = analysis_data.get('atr_mean', atr)
        
        # Track ATR for trend detection
        self.atr_history.append(atr)
        
        # Calculate ATR trend
        atr_increasing = False
        atr_erratic = False
        
        if len(self.atr_history) >= 5:
            recent_atr = list(self.atr_history)[-5:]
            atr_change = (recent_atr[-1] - recent_atr[0]) / recent_atr[0] if recent_atr[0] > 0 else 0
            atr_increasing = atr_change > 0.10  # >10% increase
            
            # Check for erratic ATR (high variance)
            atr_std = self._calculate_std(recent_atr)
            atr_erratic = atr_std > (sum(recent_atr) / len(recent_atr)) * 0.3
        
        # Classify market condition
        if adx >= 30:
            condition = MarketCondition.STRONG_TREND
        elif adx >= 25 and atr_increasing:
            condition = MarketCondition.STRONG_TREND
        elif adx >= 20:
            condition = MarketCondition.WEAK_TREND
        elif adx < 15 and atr_erratic:
            condition = MarketCondition.CHOPPY
        else:  # ADX < 20, stable ATR
            condition = MarketCondition.SIDEWAYS
        
        # Smooth condition changes (prevent oscillation)
        self.condition_history.append(condition)
        if len(self.condition_history) >= 3:
            # Require 3 consecutive similar readings for change
            recent_conditions = list(self.condition_history)[-3:]
            if len(set(recent_conditions)) == 1:
                smoothed_condition = recent_conditions[0]
            else:
                # Keep previous if inconsistent
                smoothed_condition = self.condition_history[-2] if len(self.condition_history) >= 2 else condition
        else:
            smoothed_condition = condition
        
        return smoothed_condition
    
    def get_strictness_mode(self, market_condition: MarketCondition) -> StrictnessMode:
        """
        Determine appropriate strictness mode for market condition.
        
        Args:
            market_condition: Current market condition
            
        Returns:
            StrictnessMode enum
        """
        mode_mapping = {
            MarketCondition.STRONG_TREND: StrictnessMode.STRICT,
            MarketCondition.WEAK_TREND: StrictnessMode.MODERATE,
            MarketCondition.SIDEWAYS: StrictnessMode.RELAXED,
            MarketCondition.CHOPPY: StrictnessMode.STRICT  # Stay strict in choppy markets
        }
        
        return mode_mapping.get(market_condition, StrictnessMode.MODERATE)
    
    def get_adaptive_adjustments(self, market_condition: MarketCondition, 
                                 strictness_mode: StrictnessMode) -> Dict[str, float]:
        """
        Calculate filter threshold adjustments based on market condition.
        
        Adjustments are gradual (transition_step controls blend).
        
        Returns:
            Dict with adjustment multipliers for each filter
        """
        if not self.enable_adaptive:
            # No adjustments - use base thresholds
            return {
                'min_score_adjust': 0.0,
                'ml_conf_adjust': 0.0,
                'adx_adjust': 0.0,
                'rsi_range_adjust': 0.0,
                'quality_threshold_adjust': 0.0
            }
        
        # Define adjustments per mode
        adjustments_by_mode = {
            StrictnessMode.STRICT: {
                'min_score_adjust': 0.0,      # No change - keep strict
                'ml_conf_adjust': 0.0,        # No change
                'adx_adjust': 0.0,            # No change
                'rsi_range_adjust': 0.0,      # No change
                'quality_threshold_adjust': 0.0
            },
            StrictnessMode.MODERATE: {
                'min_score_adjust': -3.0,     # Lower by 3 points
                'ml_conf_adjust': -0.03,      # Lower by 3%
                'adx_adjust': -2.0,           # Lower by 2 points
                'rsi_range_adjust': 3.0,      # Widen by 3 points each side
                'quality_threshold_adjust': -5.0
            },
            StrictnessMode.RELAXED: {
                'min_score_adjust': -7.0,     # Lower by 7 points
                'ml_conf_adjust': -0.07,      # Lower by 7%
                'adx_adjust': -5.0,           # Lower by 5 points
                'rsi_range_adjust': 5.0,      # Widen by 5 points each side
                'quality_threshold_adjust': -10.0
            },
            StrictnessMode.SEMI_STRICT: {
                'min_score_adjust': -1.5,     # Small relaxation
                'ml_conf_adjust': -0.02,      # 2% lower
                'adx_adjust': -1.0,
                'rsi_range_adjust': 2.0,
                'quality_threshold_adjust': -3.0
            }
        }
        
        target_adjustments = adjustments_by_mode.get(strictness_mode, adjustments_by_mode[StrictnessMode.MODERATE])
        
        # Gradual transition (blend between current and target)
        if not self.current_adjustments:
            self.current_adjustments = target_adjustments.copy()
            self.transition_step = 1.0
        else:
            # Increment transition (10% per call)
            self.transition_step = min(1.0, self.transition_step + 0.1)
            
            # Blend current toward target
            for key in target_adjustments:
                current = self.current_adjustments.get(key, 0.0)
                target = target_adjustments[key]
                self.current_adjustments[key] = current + (target - current) * self.transition_step
        
        return self.current_adjustments
    
    def apply_adjustments_to_filterer(self, filterer, adjustments: Dict[str, float],
                                     market_condition: MarketCondition):
        """
        Apply adaptive adjustments to AdaptiveSignalFilterer.
        
        Args:
            filterer: AdaptiveSignalFilterer instance
            adjustments: Adjustment values
            market_condition: Current market condition
        """
        # Adjust minimum score threshold
        base_min = filterer.base_min_score
        adjusted_min = max(40, base_min + adjustments['min_score_adjust'])
        filterer.current_min_score = adjusted_min
        
        # Log significant changes
        if abs(adjusted_min - filterer.current_min_score) > 0.5:
            logger.info(
                f"[ADAPTIVE STRICTNESS] {market_condition.value}: "
                f"Threshold {base_min:.1f} → {adjusted_min:.1f} "
                f"({adjustments['min_score_adjust']:+.1f})"
            )
    
    def should_trade_with_strictness(self, should_trade_base: bool, score: float,
                                     ml_confidence: float, market_condition: MarketCondition,
                                     adjustments: Dict[str, float]) -> Tuple[bool, str]:
        """
        Final trade decision incorporating adaptive strictness.
        
        Even if base filterer accepts, may reject in choppy markets.
        May accept marginal signals in sideways markets.
        
        Args:
            should_trade_base: Base filterer decision
            score: Signal quality score
            ml_confidence: ML confidence
            market_condition: Current market condition
            adjustments: Current adjustments
            
        Returns:
            (should_trade_final, reason)
        """
        # CHOPPY MARKET: Extra strict - reject unless both score and ML high
        if market_condition == MarketCondition.CHOPPY:
            if score < 70 or ml_confidence < 0.65:
                return False, (
                    f"[STRICTNESS OVERRIDE] Rejected in CHOPPY market "
                    f"(Score={score:.1f} < 70 or ML={ml_confidence:.1%} < 65%)"
                )
        
        # SIDEWAYS MARKET: Give marginal signals a chance if ML decent
        if market_condition == MarketCondition.SIDEWAYS:
            if not should_trade_base and ml_confidence >= 0.60 and score >= 40:
                return True, (
                    f"[STRICTNESS OVERRIDE] Accepted in SIDEWAYS market "
                    f"(ML={ml_confidence:.1%} ≥ 60%, Score={score:.1f} ≥ 40)"
                )
        
        # STRONG_TREND: Require extra quality
        if market_condition == MarketCondition.STRONG_TREND:
            if should_trade_base and score < 60:
                return False, (
                    f"[STRICTNESS OVERRIDE] Requires score ≥60 in STRONG_TREND "
                    f"(Score={score:.1f})"
                )
        
        # Otherwise, respect base filterer decision
        return should_trade_base, "Base filterer decision respected"
    
    def log_trade_decision(self, symbol: str, market_condition: MarketCondition,
                          strictness_mode: StrictnessMode, adjustments: Dict[str, float],
                          final_decision: bool, score: float, ml_conf: float):
        """
        Log comprehensive trade decision with adaptive context.
        """
        logger.info(
            f"[ADAPTIVE DECISION] {symbol}\n"
            f"   Market: {market_condition.value} ({strictness_mode.value})\n"
            f"   Adjustments: Score {adjustments['min_score_adjust']:+.1f}, "
            f"ML {adjustments['ml_conf_adjust']:+.1%}, ADX {adjustments['adx_adjust']:+.1f}\n"
            f"   Final: {'✓ TRADE' if final_decision else '✗ NO TRADE'} "
            f"(Score={score:.1f}, ML={ml_conf:.1%})"
        )
    
    def update_performance(self, market_condition: MarketCondition, 
                          is_win: bool, profit: float):
        """
        Track performance by market condition for analysis.
        
        Args:
            market_condition: Condition when trade was taken
            is_win: Whether trade was profitable
            profit: Profit amount
        """
        stats = self.performance_by_condition[market_condition]
        stats['trades'] += 1
        if is_win:
            stats['wins'] += 1
        stats['profit'] += profit
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        Generate performance report by market condition.
        
        Returns:
            Dict with win rates and profit by condition
        """
        report = {}
        
        for condition, stats in self.performance_by_condition.items():
            total = stats['trades']
            wins = stats['wins']
            win_rate = (wins / total * 100) if total > 0 else 0
            
            report[condition.value] = {
                'trades': total,
                'win_rate': f"{win_rate:.1f}%",
                'profit': stats['profit'],
                'avg_profit': stats['profit'] / total if total > 0 else 0
            }
        
        return report
    
    def print_performance_report(self):
        """Print formatted performance report."""
        report = self.get_performance_report()
        
        print("\n" + "="*70)
        print("ADAPTIVE STRICTNESS PERFORMANCE REPORT")
        print("="*70)
        
        for condition, stats in report.items():
            print(f"\n{condition}:")
            print(f"  Trades: {stats['trades']}")
            print(f"  Win Rate: {stats['win_rate']}")
            print(f"  Total Profit: ${stats['profit']:.2f}")
            print(f"  Avg Profit/Trade: ${stats['avg_profit']:.2f}")
        
        print("\n" + "="*70 + "\n")
    
    def _calculate_std(self, values: list) -> float:
        """Calculate standard deviation."""
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Example integration
    controller = AdaptiveStrictnessController(enable_adaptive=True)
    
    # Simulate different market conditions
    test_scenarios = [
        {
            'name': 'Strong Trend',
            'adx': 32,
            'atr': 0.00018,
            'atr_mean': 0.00015
        },
        {
            'name': 'Sideways',
            'adx': 16,
            'atr': 0.00012,
            'atr_mean': 0.00012
        },
        {
            'name': 'Choppy',
            'adx': 12,
            'atr': 0.00022,
            'atr_mean': 0.00015
        }
    ]
    
    for scenario in test_scenarios:
        print(f"\n{'='*50}")
        print(f"Scenario: {scenario['name']}")
        print(f"{'='*50}")
        
        condition = controller.detect_market_condition(scenario)
        mode = controller.get_strictness_mode(condition)
        adjustments = controller.get_adaptive_adjustments(condition, mode)
        
        print(f"Market Condition: {condition.value}")
        print(f"Strictness Mode: {mode.value}")
        print(f"Adjustments:")
        for key, val in adjustments.items():
            print(f"  {key}: {val:+.2f}")

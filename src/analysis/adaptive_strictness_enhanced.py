"""
Enhanced Adaptive Strictness Controller (v2)
File: src/analysis/adaptive_strictness_enhanced.py

ENHANCEMENTS:
1. Comprehensive performance tracking per regime (trades, win rate, PnL)
2. ML-regime integration (ML >75% overrides in weak/sideways markets)
3. Refined ADX boundaries (23/18 instead of 25/20)
4. Detailed logging with cumulative PnL per regime
5. Accept/reject counters per condition
"""

import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


class MarketCondition(Enum):
    """Market condition classification."""
    TRENDING = "TRENDING"          # ADX ≥ 28 (Aggressive/Strict)
    RANGING = "RANGING"            # ADX < 18 (Mean reversion/Relaxed)
    LOW_VOLATILITY = "LOW_VOL"      # ATR < percentile 20 (Exploratory)


class StrictnessMode(Enum):
    """Filter strictness modes."""
    STRICT = "STRICT"
    MODERATE = "MODERATE"
    RELAXED = "RELAXED"
    SEMI_STRICT = "SEMI_STRICT"


class TradeTier(Enum):
    """Trade quality tiers."""
    TIER_A = "TIER_A"  # Elite: High quality (Score >= 80) -> 1.0x Full Risk
    TIER_B = "TIER_B"  # High: Medium quality (Score 70-80) -> 0.7x Reduced Risk
    TIER_C = "TIER_C"  # Exploratory: Low quality (Score 60-70 or ML Override) -> 0.4x Micro Risk
    REJECTED = "REJECTED"


class EnhancedAdaptiveStrictnessController:
    """
    Enhanced adaptive filter strictness with comprehensive tracking.
    
    New Features:
    - Track accepted/rejected per regime
    - ML override in weak/sideways markets (>75% confidence)
    - Refined ADX boundaries (23/18)
    - Cumulative PnL logging per regime
    - Position size reduction for ML overrides
    """
    
    def __init__(self, enable_adaptive: bool = True, enable_ml_override: bool = True):
        """
        Initialize enhanced adaptive strictness controller.
        
        Args:
            enable_adaptive: Enable adaptive threshold adjustment
            enable_ml_override: Enable ML confidence override in weak markets
        """
        self.enable_adaptive = enable_adaptive
        self.enable_ml_override = enable_ml_override
        
        # Market condition history for smoothing
        self.condition_history = deque(maxlen=10)
        self.atr_history = deque(maxlen=20)
        
        # ENHANCED: Comprehensive performance tracking by condition
        self.performance_by_condition = {
            MarketCondition.TRENDING: {
                'trades': 0, 'wins': 0, 'losses': 0, 
                'profit': 0.0, 'accepted': 0, 'rejected': 0,
                'ml_overrides': 0, 'strictness_overrides': 0,
                'avg_score': 0.0, 'avg_ml_conf': 0.0
            },
            MarketCondition.RANGING: {
                'trades': 0, 'wins': 0, 'losses': 0,
                'profit': 0.0, 'accepted': 0, 'rejected': 0,
                'ml_overrides': 0, 'strictness_overrides': 0,
                'avg_score': 0.0, 'avg_ml_conf': 0.0
            },
            MarketCondition.LOW_VOLATILITY: {
                'trades': 0, 'wins': 0, 'losses': 0,
                'profit': 0.0, 'accepted': 0, 'rejected': 0,
                'ml_overrides': 0, 'strictness_overrides': 0,
                'avg_score': 0.0, 'avg_ml_conf': 0.0
            }
        }
        
        # Strictness mode performance
        self.mode_performance = {
            StrictnessMode.STRICT: {'trades': 0, 'profit': 0.0, 'wins': 0},
            StrictnessMode.MODERATE: {'trades': 0, 'profit': 0.0, 'wins': 0},
            StrictnessMode.RELAXED: {'trades': 0, 'profit': 0.0, 'wins': 0}
        }
        
        # Threshold adjustment tracking
        self.current_adjustments = {}
        self.transition_step = 0.0
        
        # Running totals for display
        self.total_accepted = 0
        self.total_rejected = 0
        
    def detect_market_condition(self, analysis_data: Dict[str, Any]) -> MarketCondition:
        """
        Detect current market condition with REFINED boundaries.
        
        REFINED THRESHOLDS (more sensitive):
        - STRONG_TREND: ADX ≥ 28 or (ADX ≥ 23 and ATR increasing >12%)
        - WEAK_TREND: 18 ≤ ADX < 28
        - SIDEWAYS: ADX < 18 and ATR stable
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
            atr_increasing = atr_change > 0.12  # REFINED: >12% increase (from 10%)
            
            # Check for erratic ATR (high variance)
            atr_std = self._calculate_std(recent_atr)
            atr_erratic = atr_std > (sum(recent_atr) / len(recent_atr)) * 0.3
        
        # Classify with requested regimes
        if adx >= 28 or (adx >= 23 and atr_increasing):
            condition = MarketCondition.TRENDING
        elif atr < (atr_mean * 0.70):  # Significant vol drop
            condition = MarketCondition.LOW_VOLATILITY
        else:
            condition = MarketCondition.RANGING
        
        # Smooth condition changes
        self.condition_history.append(condition)
        if len(self.condition_history) >= 3:
            recent_conditions = list(self.condition_history)[-3:]
            if len(set(recent_conditions)) == 1:
                smoothed_condition = recent_conditions[0]
            else:
                smoothed_condition = self.condition_history[-2] if len(self.condition_history) >= 2 else condition
        else:
            smoothed_condition = condition
        
        return smoothed_condition
    
    def get_strictness_mode(self, market_condition: MarketCondition) -> StrictnessMode:
        """Determine strictness mode for market condition."""
        mode_mapping = {
            MarketCondition.TRENDING: StrictnessMode.STRICT,
            MarketCondition.RANGING: StrictnessMode.RELAXED,
            MarketCondition.LOW_VOLATILITY: StrictnessMode.MODERATE
        }
        return mode_mapping.get(market_condition, StrictnessMode.MODERATE)
    
    def get_adaptive_adjustments(self, market_condition: MarketCondition, 
                                 strictness_mode: StrictnessMode) -> Dict[str, float]:
        """Calculate filter threshold adjustments."""
        if not self.enable_adaptive:
            return {
                'min_score_adjust': 0.0,
                'ml_conf_adjust': 0.0,
                'adx_adjust': 0.0,
                'rsi_range_adjust': 0.0,
                'quality_threshold_adjust': 0.0
            }
        
        adjustments_by_mode = {
            StrictnessMode.STRICT: {
                'min_score_adjust': 0.0,
                'ml_conf_adjust': 0.0,
                'adx_adjust': 0.0,
                'rsi_range_adjust': 0.0,
                'quality_threshold_adjust': 0.0
            },
            StrictnessMode.MODERATE: {
                'min_score_adjust': -3.0,
                'ml_conf_adjust': -0.03,
                'adx_adjust': -2.0,
                'rsi_range_adjust': 3.0,
                'quality_threshold_adjust': -5.0
            },
            StrictnessMode.RELAXED: {
                'min_score_adjust': -7.0,
                'ml_conf_adjust': -0.07,
                'adx_adjust': -5.0,
                'rsi_range_adjust': 5.0,
                'quality_threshold_adjust': -10.0
            },
            StrictnessMode.SEMI_STRICT: {
                'min_score_adjust': -1.5,
                'ml_conf_adjust': -0.02,
                'adx_adjust': -1.0,
                'rsi_range_adjust': 2.0,
                'quality_threshold_adjust': -3.0
            }
        }
        
        target_adjustments = adjustments_by_mode.get(strictness_mode, adjustments_by_mode[StrictnessMode.MODERATE])
        
        # Gradual transition
        if not self.current_adjustments:
            self.current_adjustments = target_adjustments.copy()
            self.transition_step = 1.0
        else:
            self.transition_step = min(1.0, self.transition_step + 0.1)
            for key in target_adjustments:
                current = self.current_adjustments.get(key, 0.0)
                target = target_adjustments[key]
                self.current_adjustments[key] = current + (target - current) * self.transition_step
        
        return self.current_adjustments
    
    def apply_adjustments_to_filterer(self, filterer, adjustments: Dict[str, float],
                                     market_condition: MarketCondition):
        """Apply adaptive adjustments to filterer."""
        base_min = filterer.base_min_score
        adjusted_min = max(40, base_min + adjustments['min_score_adjust'])
        filterer.current_min_score = adjusted_min
        
        if abs(adjusted_min - base_min) > 0.5:
            logger.info(
                f"[ADAPTIVE STRICTNESS] {market_condition.value}: "
                f"Threshold {base_min:.1f} → {adjusted_min:.1f} "
                f"({adjustments['min_score_adjust']:+.1f})"
            )
    
    def should_trade_with_strictness(self, should_trade_base: bool, score: float,
                                     ml_confidence: float, market_condition: MarketCondition,
                                     adjustments: Dict[str, float]) -> Tuple[bool, str, Optional[float], TradeTier]:
        """
        ENHANCED: Final trade decision with ML-regime integration and Trade Tiering.
        
        NEW: 
        - ML override in WEAK/SIDEWAYS markets.
        - Trade Tiers (A, B, C) for granular risk control.
        
        Returns:
            (should_trade_final, reason, position_size_multiplier, trade_tier)
        """
        position_size_mult = None
        current_tier = TradeTier.REJECTED
        
        # TIER CLASSIFICATION LOGIC
        final_decision = False
        reason = "Unknown"
        
        # 1. Check for ML Overrides first (Tier C exploratory)
        # HARDENING: ML Overrides are restricted in TRENDING regimes to prevent risk.
        # They are allowed in RANGING / LOW_VOLATILITY with high confidence.
        if self.enable_ml_override:
            if market_condition == MarketCondition.TRENDING:
                # Require elite ML (85%) OR standard technical pass for Trending
                if ml_confidence < 0.85 and (not should_trade_base or score < 60):
                    # Not an override, must pass technical bar in Trending
                    pass 
                elif ml_confidence >= 0.85 and (not should_trade_base or score < 55):
                    # Elite override allowed even in trending
                    current_tier = TradeTier.TIER_B
                    position_size_mult = 0.60
                    final_decision = True
                    reason = f"[ML-TREND OVERRIDE] Elite ML ({ml_confidence:.1%}) bypass in TRENDING"
            
            elif market_condition in [MarketCondition.RANGING, MarketCondition.LOW_VOLATILITY]:
                # RANGING allows 70% override, LOW_VOL allows 65% for exploratory
                ml_threshold = 0.70 if market_condition == MarketCondition.RANGING else 0.65
                if ml_confidence >= ml_threshold and (not should_trade_base or score < 55):
                    current_tier = TradeTier.TIER_C
                    position_size_mult = 0.40  # Micro risk for overrides
                    final_decision = True
                    reason = f"[ML-REGIME OVERRIDE] Tier C Accepted ({market_condition.value}), ML={ml_confidence:.1%}"
        
        # 2. Check for RANGING specific overrides (Tier C)
        if not final_decision and market_condition == MarketCondition.RANGING:
            if not should_trade_base and ml_confidence >= 0.60 and score >= 40:
                current_tier = TradeTier.TIER_C
                position_size_mult = 0.40
                final_decision = True
                reason = f"[STRICTNESS OVERRIDE] Tier C Accepted (RANGING), Score={score:.1f}"

        # 3. Handle Base Decision with Tiering
        if not final_decision and should_trade_base:
            # Apply Regime strictness filters
            if market_condition == MarketCondition.TRENDING:
                # Require score >= 60 UNLESS ML is elite (>=80%)
                quality_min = 55 if ml_confidence >= 0.80 else 60
                if score < quality_min:
                    final_decision = False
                    reason = f"[STRICTNESS REJECT] Higher score required in TRENDING ({score:.1f} < {quality_min})"
                    current_tier = TradeTier.REJECTED
                else:
                    final_decision = True # Handled by mapping below
            else:
                final_decision = True # Handled by mapping below
                
            if final_decision:
                # TIER MAPPING
                if score >= 80:
                    current_tier = TradeTier.TIER_A
                    position_size_mult = 1.0  # Full size
                elif score >= 70:
                    current_tier = TradeTier.TIER_B
                    position_size_mult = 0.7  # Reduced size
                elif score >= 60:
                    current_tier = TradeTier.TIER_C
                    position_size_mult = 0.4  # Micro size
                else:
                    # Score 55-60 in Trending 
                    current_tier = TradeTier.TIER_C
                    position_size_mult = 0.4
                
                reason = f"Accepted Tier {current_tier.value.split('_')[-1]}"

        # Track decision
        stats = self.performance_by_condition[market_condition]
        if final_decision:
            stats['accepted'] += 1
            self.total_accepted += 1
        else:
            stats['rejected'] += 1
            self.total_rejected += 1
            current_tier = TradeTier.REJECTED
        
        return final_decision, reason, position_size_mult, current_tier

    def log_trade_decision(self, symbol: str, market_condition: MarketCondition,
                          strictness_mode: StrictnessMode, adjustments: Dict[str, float],
                          final_decision: bool, score: float, ml_conf: float,
                          tier: TradeTier = TradeTier.REJECTED):
        """
        ENHANCED: Log with Tier and cumulative PnL per regime.
        """
        stats = self.performance_by_condition[market_condition]
        
        tier_str = tier.value if final_decision else "REJECTED"
        logger.info(
            f"[ADAPTIVE DECISION] {symbol} | TIER: {tier_str}\n"
            f"   Market: {market_condition.value} ({strictness_mode.value})\n"
            f"   Adjustments: Score {adjustments['min_score_adjust']:+.1f}, "
            f"ML {adjustments['ml_conf_adjust']:+.1%}, ADX {adjustments['adx_adjust']:+.1f}\n"
            f"   Decision: {'✓ TRADE' if final_decision else '✗ NO TRADE'} "
            f"(Score={score:.1f}, ML={ml_conf:.1%})\n"
            f"   Regime Stats: {stats['trades']} trades, "
            f"${stats['profit']:.2f} cumulative PnL, "
            f"{stats['accepted']} accepted / {stats['rejected']} rejected"
        )
    
    def track_signal_evaluation(self, market_condition: MarketCondition, 
                                score: float, ml_conf: float,
                                accepted: bool):
        """
        Track signal evaluation for averages.
        """
        stats = self.performance_by_condition[market_condition]
        
        # Update running averages
        total_signals = stats['accepted'] + stats['rejected']
        if total_signals > 0:
            stats['avg_score'] = ((stats['avg_score'] * (total_signals - 1)) + score) / total_signals
            stats['avg_ml_conf'] = ((stats['avg_ml_conf'] * (total_signals - 1)) + ml_conf) / total_signals
    
    def update_performance(self, market_condition: Any, 
                          profit: float, is_ml_override: bool = False):
        """
        ENHANCED: Track performance with automated win/loss detection.
        
        Args:
            market_condition: MarketCondition enum or string value
            profit: Realized profit/loss in account currency
            is_ml_override: Whether this trade was an ML override
        """
        # Convert string to enum if needed
        if isinstance(market_condition, str):
            try:
                # Handle cases where string might be 'MarketCondition.SIDEWAYS' or similar
                clean_name = market_condition.split('.')[-1]
                market_condition = MarketCondition[clean_name]
            except (KeyError, ValueError):
                logger.error(f"Invalid market condition string: {market_condition}")
                return

        if market_condition not in self.performance_by_condition:
            logger.error(f"Unrecognized market condition: {market_condition}")
            return

        is_win = profit > 0
        strictness_mode = self.get_strictness_mode(market_condition)
        
        # Update condition stats
        stats = self.performance_by_condition[market_condition]
        stats['trades'] += 1
        if is_win:
            stats['wins'] += 1
        else:
            stats['losses'] += 1
        stats['profit'] += profit
        
        # Update mode stats
        mode_stats = self.mode_performance[strictness_mode]
        mode_stats['trades'] += 1
        mode_stats['profit'] += profit
        if is_win:
            mode_stats['wins'] += 1
        
        # Log cumulative PnL update
        logger.info(
            f"[REGIME PnL UPDATE] {market_condition.value}: "
            f"Trade #{stats['trades']} {'WIN' if is_win else 'LOSS'} ${profit:+.2f} "
            f"→ Cumulative: ${stats['profit']:.2f}"
        )
    
    def get_performance_report(self) -> Dict[str, Any]:
        """
        ENHANCED: Generate comprehensive performance report.
        """
        report = {
            'overall': {
                'total_accepted': self.total_accepted,
                'total_rejected': self.total_rejected,
                'acceptance_rate': f"{(self.total_accepted / (self.total_accepted + self.total_rejected) * 100):.1f}%" if (self.total_accepted + self.total_rejected) > 0 else "N/A"
            },
            'by_condition': {},
            'by_mode': {}
        }
        
        # By market condition
        for condition, stats in self.performance_by_condition.items():
            total = stats['trades']
            wins = stats['wins']
            win_rate = (wins / total * 100) if total > 0 else 0
            total_signals = stats['accepted'] + stats['rejected']
            acceptance_rate = (stats['accepted'] / total_signals * 100) if total_signals > 0 else 0
            
            report['by_condition'][condition.value] = {
                'signals_evaluated': total_signals,
                'accepted': stats['accepted'],
                'rejected': stats['rejected'],
                'acceptance_rate': f"{acceptance_rate:.1f}%",
                'trades_executed': total,
                'win_rate': f"{win_rate:.1f}%",
                'profit': f"${stats['profit']:.2f}",
                'avg_profit_per_trade': f"${(stats['profit'] / total):.2f}" if total > 0 else "N/A",
                'ml_overrides': stats['ml_overrides'],
                'strictness_overrides': stats['strictness_overrides'],
                'avg_score': f"{stats['avg_score']:.1f}",
                'avg_ml_conf': f"{stats['avg_ml_conf']:.1%}"
            }
        
        # By strictness mode
        for mode, stats in self.mode_performance.items():
            total = stats['trades']
            wins = stats['wins']
            win_rate = (wins / total * 100) if total > 0 else 0
            
            report['by_mode'][mode.value] = {
                'trades': total,
                'win_rate': f"{win_rate:.1f}%",
                'profit': f"${stats['profit']:.2f}",
                'avg_profit': f"${(stats['profit'] / total):.2f}" if total > 0 else "N/A"
            }
        
        return report
    
    def print_performance_report(self):
        """ENHANCED: Print comprehensive report."""
        report = self.get_performance_report()
        
        print("\n" + "="*80)
        print("ENHANCED ADAPTIVE STRICTNESS PERFORMANCE REPORT")
        print("="*80)
        
        # Overall stats
        print(f"\nOVERALL:")
        print(f"  Signals Accepted: {report['overall']['total_accepted']}")
        print(f"  Signals Rejected: {report['overall']['total_rejected']}")
        print(f"  Acceptance Rate: {report['overall']['acceptance_rate']}")
        
        # By market condition
        print(f"\nBY MARKET CONDITION:")
        print("-" * 80)
        for condition, stats in report['by_condition'].items():
            print(f"\n{condition}:")
            print(f"  Signals: {stats['accepted']} accepted / {stats['rejected']} rejected ({stats['acceptance_rate']})")
            print(f"  Trades Executed: {stats['trades_executed']}")
            print(f"  Win Rate: {stats['win_rate']}")
            print(f"  Cumulative PnL: {stats['profit']} (Avg: {stats['avg_profit_per_trade']})")
            print(f"  ML Overrides: {stats['ml_overrides']}")
            print(f"  Strictness Overrides: {stats['strictness_overrides']}")
            print(f"  Avg Signal Quality: Score={stats['avg_score']}, ML={stats['avg_ml_conf']}")
        
        # By strictness mode
        print(f"\nBY STRICTNESS MODE:")
        print("-" * 80)
        for mode, stats in report['by_mode'].items():
            print(f"\n{mode}:")
            print(f"  Trades: {stats['trades']}")
            print(f"  Win Rate: {stats['win_rate']}")
            print(f"  Total PnL: {stats['profit']} (Avg: {stats['avg_profit']})")
        
        print("\n" + "="*80 + "\n")
    
    def _calculate_std(self, values: list) -> float:
        """Calculate standard deviation."""
        if not values:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5

"""
Enhanced Signal Scoring with Adaptive Filtering
File: src/analysis/enhanced_signal_scoring.py

Features:
- 70% adaptive threshold (allows marginally good signals)
- ML confidence weighting
- Dynamic ADX/RSI adjustments based on volatility
- Comprehensive rejection logging
- Automatic threshold optimization suggestions
"""

import logging
from typing import Tuple, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

from src.analysis.market_regime_detector import MarketRegimeDetector, TradingSession


class EnhancedSignalFilterer:
    """
    Adaptive signal filterer with ML integration and comprehensive logging.
    
    Key Features:
    - Accepts signals at 70% of minimum threshold
    - Weights ML confidence alongside technical score
    - Dynamically adjusts based on session and volatility
    - Logs every rejection with specific reasons
    - Provides threshold optimization suggestions
    """
    
    def __init__(self, min_score: float = 65, max_score: float = 100):
        """
        Initialize adaptive signal filterer.
        
        Args:
            min_score: Target minimum quality score (0-100)
            max_score: Maximum quality score (default 100)
        """
        from src.analysis.signal_scoring import SignalScorer
        
        self.min_score = min_score
        self.max_score = max_score
        self.scorer = SignalScorer()
        self.regime_detector = MarketRegimeDetector()
        
        # Statistics tracking
        self.trades_accepted = 0
        self.trades_rejected = 0
        self.rejection_reasons = {}
        self.acceptance_by_bracket = {'excellent': 0, 'good': 0, 'acceptable_70pct': 0}
        self.rejected_signals_log = []
        
    def should_trade_signal(self, signal: Dict[str, Any], 
                           analysis_data: Dict[str, Any],
                           timestamp: Optional[datetime] = None,
                           ml_confidence: float = 0.5) -> Tuple[bool, float, str]:
        """
        Determine if signal should be traded with adaptive thresholds.
        
        SCORING FORMULA:
        Final Score = Base Technical Score + ML Boost (up to +15) + Volatility Adjustment (up to +10)
        
        ACCEPTANCE CRITERIA:
        - ≥ min_score: EXCELLENT (full confidence)
        - ≥ min_score × 0.70: ACCEPTABLE (70% threshold)
        - < min_score × 0.70: REJECTED (with detailed logging)
        
        Args:
            signal: Trading signal data
            analysis_data: Technical analysis metrics (ADX, RSI, ATR, etc.)
            timestamp: Signal timestamp for session detection
            ml_confidence: ML model confidence (0.0-1.0)
        
        Returns:
            (should_trade, final_score, detailed_reasoning)
        """
        # Calculate base quality score
        base_score = self.scorer.calculate_score(analysis_data, timestamp)
        
        # Get session context for dynamic adjustments
        session = self.regime_detector.detect_session(timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)
        
        # ML Confidence Weighting (boost up to +15 points)
        ml_boost = ml_confidence * 15.0
        
        # Dynamic volatility adjustment
        atr = analysis_data.get('atr', 0)
        atr_mean = analysis_data.get('atr_mean', 1)
        volatility_ratio = (atr / atr_mean) if atr_mean > 0 else 1.0
        
        # In high volatility, relax ADX/RSI requirements (up to +10 points)
        volatility_adjustment = 0
        if volatility_ratio > 1.3:  # High volatility environment
            volatility_adjustment = min(10, (volatility_ratio - 1.0) * 15)
        
        # Calculate final weighted score
        final_score = base_score + ml_boost + volatility_adjustment
        final_score = min(100, final_score)
        
        # Adaptive threshold: 70% of minimum (allows marginal trades)
        adaptive_threshold = self.min_score * 0.70
        
        # Decision logic with tiered acceptance
        if final_score >= self.min_score:
            # EXCELLENT: Full execution recommended
            self.trades_accepted += 1
            self.acceptance_by_bracket['excellent'] += 1
            reason = self._format_acceptance(
                final_score, base_score, ml_boost, volatility_adjustment, "EXCELLENT", session
            )
            logger.info(f"[SIGNAL ACCEPTED] {reason}")
            return True, final_score, reason
        
        elif final_score >= adaptive_threshold:
            # ACCEPTABLE: 70%+ threshold allows entry with reduced size
            self.trades_accepted += 1
            self.acceptance_by_bracket['acceptable_70pct'] += 1
            reason = self._format_acceptance(
                final_score, base_score, ml_boost, volatility_adjustment, "ACCEPTABLE (70%)", session
            )
            logger.info(f"[SIGNAL ACCEPTED] {reason}")
            return True, final_score, reason
        
        else:
            # REJECTED: Log detailed reason and suggest improvements
            self.trades_rejected += 1
            rejection_info = self._analyze_rejection(
                base_score, final_score, analysis_data, thresholds, ml_confidence, session
            )
            
            # Track rejection category
            category = rejection_info['category']
            if category not in self.rejection_reasons:
                self.rejection_reasons[category] = 0
            self.rejection_reasons[category] += 1
            
            # Store for later analysis
            self.rejected_signals_log.append({
                'timestamp': timestamp,
                'score': final_score,
                'threshold': adaptive_threshold,
                'category': category,
                'suggestions': rejection_info['suggestions']
            })
            
            logger.warning(f"[SIGNAL REJECTED] {rejection_info['message']}")
            return False, final_score, rejection_info['message']
    
    def _format_acceptance(self, final_score: float, base_score: float, 
                          ml_boost: float, vol_adj: float, grade: str, session: str) -> str:
        """Format acceptance message with detailed breakdown."""
        parts = [f"Base={base_score:.1f}"]
        if ml_boost > 0.5:
            parts.append(f"ML=+{ml_boost:.1f}")
        if vol_adj > 0.5:
            parts.append(f"VolAdj=+{vol_adj:.1f}")
        
        return (f"✓ {grade} | Final Score: {final_score:.1f}/100 | "
                f"{' | '.join(parts)} | Session: {session.value}")
    
    def _analyze_rejection(self, base_score: float, final_score: float,
                          data: Dict[str, Any], thresholds: Dict[str, float],
                          ml_conf: float, session: str) -> Dict[str, Any]:
        """
        Analyze why signal was rejected and suggest specific improvements.
        
        Returns:
            Dict with category, message, and actionable suggestions
        """
        adx = data.get('adx', 0)
        rsi = data.get('rsi', 50)
        atr = data.get('atr', 0)
        atr_mean = data.get('atr_mean', 1)
        
        issues = []
        suggestions = []
        
        # ADX Strength Analysis
        if adx < thresholds['adx_weak']:
            gap = thresholds['adx_weak'] - adx
            issues.append(f"ADX={adx:.1f} (need >{thresholds['adx_weak']:.0f})")
            suggestions.append(f"Lower {session.value} ADX threshold by {gap:.0f} points")
        
        # RSI Positioning Analysis
        rsi_ob = thresholds['rsi_ob']
        rsi_os = thresholds['rsi_os']
        if rsi_os + 5 < rsi < rsi_ob - 5:  # In neutral zone
            issues.append(f"RSI={rsi:.1f} (neutral, need <{rsi_os} or >{rsi_ob})")
            suggestions.append(f"Widen RSI range to {rsi_os-5:.0f}-{rsi_ob+5:.0f} for {session.value}")
        
        # ML Confidence Analysis
        if ml_conf < 0.55:
            issues.append(f"ML Confidence={ml_conf:.1%} (low)")
            if ml_conf < 0.4:
                suggestions.append("URGENT: Retrain ML model (conf < 40%)")
            else:
                suggestions.append("Lower ML confidence requirement to 50%")
        
        # Volatility Analysis
        vol_ratio = (atr / atr_mean) if atr_mean > 0 else 1.0
        if vol_ratio < 0.6:
            issues.append(f"Low volatility (ATR={vol_ratio:.2f}x mean)")
            suggestions.append(f"Lower minimum ATR or wait for volatility pickup")
        elif vol_ratio > 2.0:
            issues.append(f"Extreme volatility (ATR={vol_ratio:.2f}x mean)")
            suggestions.append("Increase spread tolerance or pause during volatility spikes")
        
        # Determine primary category
        if adx < thresholds['adx_weak']:
            category = "weak_trend"
        elif rsi_os + 5 < rsi < rsi_ob - 5:
            category = "neutral_rsi"
        elif ml_conf < 0.5:
            category = "low_ml_confidence"
        elif vol_ratio < 0.6:
            category = "low_volatility"
        else:
            category = "overall_quality"
        
        # Format comprehensive message
        threshold = self.min_score * 0.70
        message = (
            f"✗ Score: {final_score:.1f} < {threshold:.1f} (70% threshold)\n"
            f"   Primary Issue: {category.replace('_', ' ').title()}\n"
            f"   Details: {' | '.join(issues) if issues else 'Multiple factors below par'}\n"
            f"   Suggested Fix: {suggestions[0] if suggestions else 'Review overall parameters'}"
        )
        
        return {
            'category': category,
            'message': message,
            'suggestions': suggestions,
            'raw_data': {
                'base_score': base_score,
                'final_score': final_score,
                'adx': adx,
                'rsi': rsi,
                'ml_conf': ml_conf,
                'vol_ratio': vol_ratio
            }
        }
    
    def adjust_position_size(self, score: float, base_size: float, 
                            ml_confidence: float = 0.5) -> float:
        """
        Adjust position size based on signal quality AND ML confidence.
        
        Weighting formula:
        - Signal Score (60%): Technical quality assessment
        - ML Confidence (40%): Model prediction strength
        
        Sizing Tiers:
        - Composite ≥ 0.85: 1.5× base (excellent)
        - Composite ≥ 0.70: 1.0× base (good)
        - Composite ≥ 0.55: 0.75× base (acceptable)
        - Composite < 0.55: 0.5× base (marginal)
        
        Args:
            score: Signal quality score (0-100)
            base_size: Base position size (lots)
            ml_confidence: ML model confidence (0.0-1.0)
        
        Returns:
            Adjusted position size
        """
        # Normalize score to 0-1
        normalized_score = score / 100.0
        
        # Weighted composite strength (60% technical, 40% ML)
        composite = (normalized_score * 0.60) + (ml_confidence * 0.40)
        
        # Sizing tiers with ML influence
        if composite >= 0.85:  # Excellent
            multiplier = 1.5
        elif composite >= 0.70:  # Good
            multiplier = 1.0
        elif composite >= 0.55:  # Acceptable
            multiplier = 0.75
        else:  # Marginal
            multiplier = 0.5
        
        adjusted = base_size * multiplier
        logger.debug(f"Position sizing: Base={base_size:.2f} * {multiplier:.2f} (Score={score:.1f}, ML={ml_conf:.2f}) = {adjusted:.2f}")
        
        return adjusted
    
    def get_rejection_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive summary of rejection patterns with optimization suggestions.
        
        Returns:
            Detailed rejection analysis with actionable recommendations
        """
        if not self.rejection_reasons:
            return {'message': 'No rejections yet - all signals accepted or no signals processed'}
        
        # Find most common rejection reason
        top_reason = max(self.rejection_reasons.items(), key=lambda x: x[1])
        total_rejected = sum(self.rejection_reasons.values())
        
        # Generate specific suggestions based on top reason
        optimization_guides = {
            'weak_trend': [
                f"→ Lower ADX minimum by 3-5 points (currently rejecting {top_reason[1]} signals)",
                "→ Enable trend-following in ranging markets (ADX 15-20)",
                "→ Consider counter-trend signals during specific sessions"
            ],
            'neutral_rsi': [
                "→ Widen RSI thresholds to 35-65 range (from 30-70)",
                "→ Enable RSI neutral zone trading (40-60 range)",
                "→ Focus on momentum divergence rather than extremes"
            ],
            'low_ml_confidence': [
                "→ CRITICAL: Retrain ML model with recent 3-6 months data",
                "→ Lower ML confidence minimum from 55% to 50%",
                "→ Increase technical signal weight (reduce ML dependency)"
            ],
            'low_volatility': [
                "→ Lower minimum ATR threshold by 20%",
                "→ Trade only during London/NY overlap (higher volatility)",
                "→ Increase position size during volatile periods"
            ],
            'overall_quality': [
                f"→ Lower minimum score from {self.min_score} to {max(50, self.min_score - 5)}",
                "→ Already using 70% adaptive threshold - consider 60%",
                "→ Review and re-weight confluence factors"
            ]
        }
        
        return {
            'total_rejected': total_rejected,
            'rejection_breakdown': dict(self.rejection_reasons),
            'primary_issue': top_reason[0],
            'primary_issue_count': top_reason[1],
            'primary_issue_percentage': f"{(top_reason[1]/total_rejected*100):.1f}%",
            'optimization_suggestions': optimization_guides.get(top_reason[0], ['Review overall parameters']),
            'recent_rejections': self.rejected_signals_log[-10:]  # Last 10 rejections
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """
        Get comprehensive statistics on signal filtering performance.
        
        Returns:
            Dict with acceptance rates, quality distribution, and analysis
        """
        total = self.trades_accepted + self.trades_rejected
        acceptance_rate = (self.trades_accepted / total * 100) if total > 0 else 0
        
        stats = {
            'total_signals_evaluated': total,
            'accepted': self.trades_accepted,
            'rejected': self.trades_rejected,
            'acceptance_rate': f"{acceptance_rate:.1f}%",
            'quality_distribution': {
                'excellent_full_size': self.acceptance_by_bracket['excellent'],
                'good_normal_size': self.acceptance_by_bracket.get('good', 0),
                'acceptable_70pct_reduced _size': self.acceptance_by_bracket['acceptable_70pct']
            }
        }
        
        if self.trades_rejected > 0:
            stats['rejection_analysis'] = self.get_rejection_summary()
        
        return stats
    
    def print_performance_report(self):
        """Print a formatted performance report to console."""
        stats = self.get_statistics()
        
        print("\n" + "="*60)
        print("ADAPTIVE SIGNAL FILTER PERFORMANCE REPORT")
        print("="*60)
        print(f"Total Signals Evaluated: {stats['total_signals_evaluated']}")
        print(f"Accepted: {stats['accepted']} ({stats['acceptance_rate']})")
        print(f"Rejected: {stats['rejected']}")
        print("\nQuality Distribution:")
        for quality, count in stats['quality_distribution'].items():
            print(f"  - {quality}: {count}")
        
        if 'rejection_analysis' in stats:
            rej = stats['rejection_analysis']
            print(f"\nTop Rejection Reason: {rej['primary_issue']} ({rej['primary_issue_percentage']})")
            print("\nOptimization Suggestions:")
            for suggestion in rej['optimization_suggestions']:
                print(f"  {suggestion}")
        
        print("="*60 + "\n")

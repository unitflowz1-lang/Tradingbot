"""
Adaptive Signal Scoring with ML Accuracy Feedback
File: src/analysis/adaptive_signal_scoring.py

Features:
- Dynamic threshold adjustment based on ML model performance
- ML confidence override (70%+ ML can override moderate scores)
- Session-aware filter relaxation
- Comprehensive logging with actionable suggestions
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Tuple, Dict, Any, Optional
from collections import deque

# ===== FIX #5: ACCURACY SESSION OVERRIDE (Logic-Chain Sync) =====
# For the next 2 hours, ignore ML Accuracy floor for trades with confidence > 80%
SESSION_ACCURACY_IGNORE = False
SESSION_ACCURACY_IGNORE_EXPIRY = datetime.now(timezone.utc)

# ===== SURGICAL FIX #4: SESSION-AGNOSTIC EXECUTION =====
# For the next 4 hours, ignore session filter for signals with ML Confidence > 80%
SESSION_AGNOSTIC_EXECUTION = False
SESSION_AGNOSTIC_EXPIRY = datetime.now(timezone.utc)

logger = logging.getLogger(__name__)

from src.analysis.market_regime_detector import MarketRegimeDetector, TradingSession

TEMP_GLOBAL_QUALITY_FLOOR = 40.0
TEMP_GLOBAL_QUALITY_WINDOW_HOURS = 4


class AdaptiveSignalFilterer:
    """
    Self-adjusting signal filterer that learns from ML model performance.
    
    Key Adaptive Features:
    - Lowers thresholds when ML accuracy drops below 50%
    - Allows ML confidence override (70%+ ML = auto-accept)
    - Session-specific filter relaxation
    - Tracks performance and suggests optimizations
    """
    
    def __init__(self, min_score: float = 50, ml_accuracy_target: float = 0.55):
        """
        Initialize adaptive signal filterer.
        
        Args:
            min_score: Base minimum quality score (will adapt) - NOW 50% for low-volatility markets
            ml_accuracy_target: Target ML accuracy (default 55%)
        """
        from src.analysis.signal_scoring import SignalScorer
        
        # Initialize logger first before any log statements
        self.logger = logging.getLogger(__name__)
        
        self.base_min_score = min_score  # Original threshold - LOWERED TO 50% GLOBALLY
        self.current_min_score = min_score  # Adaptive threshold
        self.ml_accuracy_target = ml_accuracy_target
        self.scorer = SignalScorer()
        self.regime_detector = MarketRegimeDetector()
        
        # Temporary market-relaxation patch.
        from datetime import datetime, timedelta, timezone
        self.patch_start_time = datetime.now(timezone.utc)
        self.patch_expiry_time = self.patch_start_time + timedelta(hours=TEMP_GLOBAL_QUALITY_WINDOW_HOURS)
        self.logger.critical(
            f"[SURGICAL_PATCH] Global Quality Floor lowered to {TEMP_GLOBAL_QUALITY_FLOOR:.0f}% for "
            f"{TEMP_GLOBAL_QUALITY_WINDOW_HOURS} hours. Temporary market-relaxation window is active."
        )
        self.current_min_score = TEMP_GLOBAL_QUALITY_FLOOR
        
        # ML Performance Tracking
        self.ml_predictions = deque(maxlen=50)  # Last 50 predictions
        self.ml_accuracy_history = deque(maxlen=10)  # Last 10 accuracy calculations
        
        # Statistics
        self.trades_accepted = 0
        self.trades_rejected = 0
        self.rejection_reasons = {}
        self.acceptance_by_method = {
            'excellent_quality': 0,
            'good_quality': 0,
            'ml_override': 0,
            'adaptive_70pct': 0
        }
        self.rejected_signals_log = []
        
    def update_ml_performance(self, prediction: int, actual_outcome: Optional[int] = None):
        """
        Track ML predictions and calculate rolling accuracy.
        
        Args:
            prediction: ML prediction (0 or 1)
            actual_outcome: Actual result (0 or 1), None if not yet known
        """
        self.ml_predictions.append({
            'prediction': prediction,
            'outcome': actual_outcome,
            'timestamp': datetime.now()
        })
        
        # Calculate accuracy when we have outcomes
        if actual_outcome is not None:
            correct = sum(1 for p in self.ml_predictions 
                         if p['outcome'] is not None and p['prediction'] == p['outcome'])
            total = sum(1 for p in self.ml_predictions if p['outcome'] is not None)
            
            if total >= 10:  # Need at least 10 samples
                accuracy = correct / total
                self.ml_accuracy_history.append(accuracy)
                self._adjust_thresholds_based_on_accuracy(accuracy)
    
    def _adjust_thresholds_based_on_accuracy(self, current_accuracy: float):
        """
        Dynamically adjust min_score based on ML model performance.
        
        Logic:
        - ML accuracy < 45%: Lower threshold by 10%
        - ML accuracy < 50%: Lower threshold by 5%
        - ML accuracy > 60%: Raise threshold by 5% (up to base)
        """
        if current_accuracy < 0.45:
            # Poor ML performance - significantly relax filters
            adjustment = -0.10
            reason = f"ML accuracy critically low ({current_accuracy:.1%})"
        elif current_accuracy < 0.50:
            # Below target - relax filters
            adjustment = -0.05
            reason = f"ML accuracy below target ({current_accuracy:.1%} < 50%)"
        elif current_accuracy > 0.60 and self.current_min_score < self.base_min_score:
            # Good performance - tighten back toward base
            adjustment = +0.05
            reason = f"ML accuracy strong ({current_accuracy:.1%})"
        else:
            return  # No adjustment needed
        
        new_threshold = self.base_min_score * (1 + adjustment)
        new_threshold = max(40, min(self.base_min_score, new_threshold))  # Bounds: 40-base
        
        if abs(new_threshold - self.current_min_score) > 1:
            logger.info(f"[ADAPTIVE THRESHOLD] {reason}")
            logger.info(f"[ADAPTIVE THRESHOLD] Adjusting from {self.current_min_score:.1f} → {new_threshold:.1f}")
            self.current_min_score = new_threshold
    
    def get_quality_threshold(self, ml_confidence: float) -> float:
        """
        Get dynamic quality threshold with hardcoded limit for high confidence.
        """
        current_time = datetime.now(timezone.utc)
        if current_time < self.patch_expiry_time:
            temporary_floor = TEMP_GLOBAL_QUALITY_FLOOR
        else:
            temporary_floor = self.base_min_score

        if ml_confidence > 0.80:
            return min(temporary_floor, 45.0)

        return min(self.current_min_score, temporary_floor)

    def get_effective_accuracy_gate(
        self,
        *,
        ml_confidence: float,
        analysis_data: Dict[str, Any],
        timestamp: Optional[datetime] = None,
        symbol: str = "",
    ) -> float:
        """Adaptive accuracy floor that tracks volatility and confidence."""
        accuracy_floor = 0.45
        atr = float(analysis_data.get('atr', 0.0) or 0.0)
        atr_mean = float(analysis_data.get('atr_mean', atr) or atr or 1.0)
        volatility_ratio = (atr / atr_mean) if atr_mean > 0 else 1.0

        if volatility_ratio < 0.85:
            accuracy_floor -= 0.05
        elif volatility_ratio > 1.20:
            accuracy_floor += 0.03

        if ml_confidence >= 0.80:
            accuracy_floor -= 0.08
        elif ml_confidence >= 0.65:
            accuracy_floor -= 0.03

        if symbol == 'EUR/USD' and ml_confidence > 0.85 and timestamp:
            hour = timestamp.hour
            if hour >= 13 or hour < 2:
                accuracy_floor -= 0.04

        return max(0.25, min(0.55, accuracy_floor))
    
    def should_trade_signal(self, signal: Dict[str, Any], 
                           analysis_data: Dict[str, Any],
                           timestamp: Optional[datetime] = None,
                           ml_confidence: float = 0.5) -> Tuple[bool, float, str]:
        """
        Adaptive signal evaluation with multiple acceptance paths.
        
        Acceptance Paths:
        1. EXCELLENT: Score ≥ current_min_score (NOW 50% GLOBAL STANDARD)
        2. ML OVERRIDE: ML confidence ≥ 70% (even if score < min)
        3. ADAPTIVE 70%: Score ≥ 70% of current_min_score
        4. SESSION RELAXED: Score ≥ relaxed threshold for low-vol sessions
        
        Args:
            signal: Trading signal
            analysis_data: Technical metrics
            timestamp: Signal time
            ml_confidence: ML model confidence (0.0-1.0)
        
        Returns:
            (should_trade, final_score, reasoning)
        """
        # Forced execution bypass is deprecated. EV gatekeeper handles final overrides.
        
        # ===== FIX #5: EUR/USD ACCURACY GATE FOR NY/TOKYO OVERLAP =====
        # For EUR/USD with Confidence > 85%, lower required ML Accuracy to 30% during NY/Tokyo overlap
        symbol = signal.get('symbol', '')
        accuracy = self.get_current_ml_accuracy() or 0.50
        accuracy_floor = self.get_effective_accuracy_gate(
            ml_confidence=ml_confidence,
            analysis_data=analysis_data,
            timestamp=timestamp,
            symbol=symbol,
        )
        
        if symbol == 'EUR/USD' and ml_confidence > 0.85:
            # ===== FIX #9: ACCURACY-SESSION LOGIC FIX =====
            # Ignore ML Accuracy requirements for 60 minutes if Confidence is > 85%
            # (Within the first 60 mins of patch deployment)
            time_since_patch = (datetime.now() - self.patch_start_time).total_seconds() / 60
            if time_since_patch < 60:
                ml_accuracy_required = 0.0  # IGNORE ACCURACY
                logger.critical(
                    f"[ACCURACY_SESSION_BYPASS] {symbol} | Confidence {ml_confidence:.1%} > 85% | "
                    f"First 60 mins of deployment: ML Accuracy requirement IGNORED (0.0%)."
                )
            else:
                # Check if we're in NY/Tokyo overlap session (approximately 13:00-09:00 UTC next day)
                if timestamp:
                    hour = timestamp.hour
                    # NY/Tokyo overlap: roughly 13:00 UTC - 22:00 UTC
                    if 13 <= hour < 22:
                        ml_accuracy_required = 0.30  # ===== FIX #5: LOWER TO 30% FOR EUR/USD IN NY/TOKYO OVERLAP =====
                        logger.critical(
                            f"[EUR_USD_OVERLAP_GATE] {symbol} | Confidence: {ml_confidence:.1%} > 85% | "
                            f"NY/Tokyo overlap detected | ML Accuracy requirement LOWERED: 50% → 30%"
                        )
        
        # ===== FIX #5: ACCURACY SESSION OVERRIDE (Logic-Chain Sync) =====
        # Get accuracy value FIRST before using it in comparisons
        accuracy = self.get_current_ml_accuracy() or 0.50
        accuracy_floor = ml_accuracy_required
        
        # Check if SESSION_ACCURACY_IGNORE is active and applicable
        current_time = datetime.now(timezone.utc)
        if SESSION_ACCURACY_IGNORE and current_time < SESSION_ACCURACY_IGNORE_EXPIRY:
            if ml_confidence > 0.80:
                accuracy_floor = 0.0  # Force ignore
                logger.critical(f"[ACCURACY_SESSION_OVERRIDE] {symbol} | Confidence {ml_confidence:.1%} > 80% | Ignoring all accuracy floors.")
        
        # ===== FIX #7: ACCURACY OVERRIDE FOR HIGH CONFIDENCE + RR =====
        # Force ML Accuracy ignored for any signal where Confidence > 80% AND RR > 2.0
        # Check RR from signal dict
        entry = signal.get('entry_price')
        sl = signal.get('stop_loss')
        tp = signal.get('take_profit')
        rr = 0.0
        if entry and sl and tp:
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            if risk > 0:
                rr = reward / risk
        
        if ml_confidence > 0.80:
            # Only apply override if RR > 2.0 (High Quality Setup)
            if rr > 2.0:
                accuracy_floor = 0.0
                logger.critical(f"[ACCURACY_OVERRIDE] {symbol} | Confidence {ml_confidence:.1%} > 80% | RR {rr:.2f} > 2.0 | Accuracy requirement DROPPED to 0%.")
            else:
                logger.info(f"[ACCURACY_OVERRIDE_SKIP] {symbol} | Confidence {ml_confidence:.1%} > 80% but RR {rr:.2f} <= 2.0. Floor maintained.")

        # ===== SURGICAL FIX #6: STRIKING PHASE ACCURACY FLOOR =====
        # Set absolute minimum accuracy to 20% if confidence is > 85%
        if ml_confidence > 0.85:
            accuracy_floor = min(accuracy_floor, 0.20) if accuracy_floor > 0 else 0.0
            logger.critical(f"[STRIKING_PHASE_ACCURACY] {symbol} | Confidence {ml_confidence:.1%} > 85% | Floor lowered to 20% (Striking Phase Active)")
        
        if accuracy < accuracy_floor:
            self.trades_rejected += 1
            if 'low_accuracy' not in self.rejection_reasons:
                self.rejection_reasons['low_accuracy'] = 0
            self.rejection_reasons['low_accuracy'] += 1
            logger.warning(f"[ACCURACY_VETO] {symbol} | ML Accuracy {accuracy:.1%} < {accuracy_floor:.1%} requirement. Rejecting signal.")
            return False, final_score, f"ML Accuracy below {accuracy_floor:.1%} floor (Veto Active)"
        
        # --- NEW: High-Accuracy Relaxation ---
        effective_min_score = self.get_quality_threshold(ml_confidence)
        if accuracy > 0.70:
            effective_min_score = min(65.0, self.current_min_score)
            logger.debug(f"[ACCURACY BOOST] ML Accuracy {accuracy:.1%} > 70%: Lowering min_score to {effective_min_score}")

        # Calculate base score
        base_score = self.scorer.calculate_score(analysis_data, timestamp)
        
        # Session context
        session = self.regime_detector.detect_session(timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)
        
        # ML confidence boost (up to +15)
        ml_boost = ml_confidence * 15.0
        
        # Volatility adjustment (up to +10)
        atr = analysis_data.get('atr', 0)
        atr_mean = analysis_data.get('atr_mean', 1)
        volatility_ratio = (atr / atr_mean) if atr_mean > 0 else 1.0
        vol_adjustment = 0
        if volatility_ratio > 1.3:
            vol_adjustment = min(10, (volatility_ratio - 1.0) * 15)
        
        # Final weighted score
        final_score = base_score + ml_boost + vol_adjustment
        final_score = min(100, final_score)
        
        # ===== FIX #6: EFFECTIVE ADX FLOOR LOGGING =====
        effective_adx_floor = thresholds.get('adx_weak', 20.0)
        logger.info(f"[ADX_FLOOR_VERIFY] {symbol} | Session: {session.value} | Effective ADX Floor: {effective_adx_floor:.1f}")
        
        # Session-specific relaxation for Tokyo (low volatility)
        session_relaxation = 0
        if session == TradingSession.TOKYO:
            # In Tokyo, relax ADX requirement if other factors good
            adx = analysis_data.get('adx', 0)
            if adx >= (thresholds['adx_weak'] * 0.85):  # 85% of normal threshold
                session_relaxation = 5
                logger.debug(f"[SESSION RELAX] Tokyo session: ADX {adx:.1f} → +5 points")
        
        final_score += session_relaxation
        final_score = min(100, final_score)
        
        # DECISION TREE
        
        # Path 1: ML Elite Override (80%+ ML confidence)
        # Bypasses a marginal score if ML is extremely confident
        if ml_confidence >= 0.80:
            self.trades_accepted += 1
            self.acceptance_by_method['ml_override'] += 1
            
            # Check for Session-Agnostic status
            session_agnostic = ""
            if SESSION_AGNOSTIC_EXECUTION and datetime.now(timezone.utc) < SESSION_AGNOSTIC_EXPIRY:
                session_agnostic = " | [SESSION-AGNOSTIC ACTIVE]"
            
            reason = (f"✓ ML ELITE OVERRIDE | ML Confidence: {ml_confidence:.1%} ≥ 80% "
                     f"| Score: {final_score:.1f} (Filters marginally bypassed) | {session.value}{session_agnostic}")
            logger.info(f"[ACCEPTED] {reason}")
            return True, final_score, reason
        
        # Path 1.5: ML Standard Override (70%-80% ML confidence)
        if ml_confidence >= 0.70:
            self.trades_accepted += 1
            self.acceptance_by_method['ml_override'] += 1
            reason = (f"✓ ML OVERRIDE | ML Confidence: {ml_confidence:.1%} ≥ 70% "
                     f"| Score: {final_score:.1f} | {session.value}")
            logger.info(f"[ACCEPTED] {reason}")
            return True, final_score, reason
        
        # Path 2: Excellent Quality
        if final_score >= effective_min_score:
            self.trades_accepted += 1
            self.acceptance_by_method['excellent_quality'] += 1
            reason = self._format_acceptance(
                final_score, base_score, ml_boost, vol_adjustment, session_relaxation,
                "EXCELLENT", session, effective_min_score
            )
            logger.info(f"[ACCEPTED] {reason}")
            return True, final_score, reason
        
        # Path 3: Adaptive 70% Threshold
        adaptive_threshold = effective_min_score * 0.70
        if final_score >= adaptive_threshold:
            self.trades_accepted += 1
            self.acceptance_by_method['adaptive_70pct'] += 1
            reason = self._format_acceptance(
                final_score, base_score, ml_boost, vol_adjustment, session_relaxation,
                f"ACCEPTABLE (70% of {self.current_min_score:.0f})", session
            )
            logger.info(f"[ACCEPTED] {reason}")
            return True, final_score, reason
        
        # REJECTED - Log and analyze
        self.trades_rejected += 1
        rejection_info = self._analyze_rejection(
            base_score, final_score, analysis_data, thresholds, 
            ml_confidence, session, adaptive_threshold
        )
        
        # Track category
        category = rejection_info['category']
        if category not in self.rejection_reasons:
            self.rejection_reasons[category] = 0
        self.rejection_reasons[category] += 1
        
        # Store for analysis
        self.rejected_signals_log.append({
            'timestamp': timestamp,
            'score': final_score,
            'ml_conf': ml_confidence,
            'threshold': adaptive_threshold,
            'category': category,
            'suggestions': rejection_info['suggestions']
        })
        
        logger.warning(f"[REJECTED] {rejection_info['message']}")
        return False, final_score, rejection_info['message']
    
    def _format_acceptance(self, final: float, base: float, ml: float, 
                          vol: float, session_adj: float, grade: str, session, threshold: float) -> str:
        """Format detailed acceptance message."""
        parts = [f"Base={base:.1f}"]
        if ml > 0.5:
            parts.append(f"ML=+{ml:.1f}")
        if vol > 0.5:
            parts.append(f"Vol=+{vol:.1f}")
        if session_adj > 0:
            parts.append(f"Session=+{session_adj:.1f}")
        
        return (f"✓ {grade} | Score: {final:.1f} (Threshold: {threshold:.1f}) | "
                f"{' | '.join(parts)} | {session.value}")
    
    def _analyze_rejection(self, base_score: float, final_score: float,
                          data: Dict[str, Any], thresholds: Dict[str, float],
                          ml_conf: float, session, threshold: float) -> Dict[str, Any]:
        """Analyze rejection and provide specific suggestions."""
        adx = data.get('adx', 0)
        rsi = data.get('rsi', 50)
        
        issues = []
        suggestions = []
        
        # ADX Analysis
        if adx < thresholds['adx_weak']:
            gap = thresholds['adx_weak'] - adx
            issues.append(f"ADX={adx:.1f} (need >{thresholds['adx_weak']:.0f})")
            suggestions.append(f"→ Lower {session.value} ADX by {gap:.0f} points to {thresholds['adx_weak']-gap:.0f}")
        
        # RSI Analysis
        rsi_ob, rsi_os = thresholds['rsi_ob'], thresholds['rsi_os']
        if rsi_os + 5 < rsi < rsi_ob - 5:
            issues.append(f"RSI={rsi:.1f} (neutral zone, range: 25-75)")
            suggestions.append(f"→ Widen {session.value} RSI to {rsi_os-5:.0f}-{rsi_ob+5:.0f} (standard range: 25-75)")
        else:
            # ===== FIX #7: RSI STANDARDIZATION STRINGS =====
            # Ensure final rejection log strictly prints standardized range for RSI
            issues.append(f"RSI={rsi:.1f} (range: 25-75)")
        
        # ML Confidence
        if ml_conf < 0.55:
            issues.append(f"ML={ml_conf:.1%}")
            if ml_conf < 0.40:
                suggestions.append("→ URGENT: Retrain ML model (use 500-1000 bars)")
            else:
                suggestions.append("→ Lower ML confidence requirement or retrain model")
        
        # Overall Score
        if final_score < threshold and not suggestions:
            suggestions.append(f"→ Lower base threshold from {self.base_min_score:.0f} to {self.base_min_score-5:.0f}")
        
        # Determine category
        if adx < thresholds['adx_weak']:
            category = "weak_trend"
        elif ml_conf < 0.50:
            category = "low_ml_confidence"
        elif rsi_os + 5 < rsi < rsi_ob - 5:
            category = "neutral_rsi"
        else:
            category = "overall_quality"
        
        message = (f"✗ Score: {final_score:.1f} < {threshold:.1f}\n"
                  f"   Category: {category.replace('_', ' ').title()}\n"
                  f"   Issues: {' | '.join(issues) if issues else 'Multiple factors'}\n"
                  f"   Fix: {suggestions[0] if suggestions else 'Increase data quality'}")
        
        return {
            'category': category,
            'message': message,
            'suggestions': suggestions
        }
    
    def adjust_position_size(self, score: float, base_size: float, 
                            ml_confidence: float = 0.5) -> float:
        # Formula: (Score/100 × 0.50) + (Accuracy × 0.50)
        # Prioritize accuracy over individual trade confidence
        accuracy = self.get_current_ml_accuracy() or 0.50
        normalized_score = score / 100.0
        composite = (normalized_score * 0.50) + (accuracy * 0.50)
        
        if composite >= 0.85:
            multiplier = 1.5
        elif composite >= 0.70:
            multiplier = 1.0
        elif composite >= 0.55:
            multiplier = 0.75
        else:
            multiplier = 0.5
        
        return base_size * multiplier
    
    def get_current_ml_accuracy(self) -> Optional[float]:
        """Get most recent ML accuracy."""
        if self.ml_accuracy_history:
            return self.ml_accuracy_history[-1]
        return None
    
    def get_statistics(self) -> Dict[str, Any]:
        """Comprehensive performance statistics."""
        total = self.trades_accepted + self.trades_rejected
        acceptance_rate = (self.trades_accepted / total * 100) if total > 0 else 0
        
        ml_acc = self.get_current_ml_accuracy()
        
        stats = {
            'total_signals': total,
            'accepted': self.trades_accepted,
            'rejected': self.trades_rejected,
            'acceptance_rate': f"{acceptance_rate:.1f}%",
            'current_threshold': f"{self.current_min_score:.1f} (base: {self.base_min_score:.0f})",
            'ml_accuracy': f"{ml_acc:.1%}" if ml_acc else "Not yet calculated",
            'acceptance_methods': dict(self.acceptance_by_method),
            'rejection_categories': dict(self.rejection_reasons) if self.rejection_reasons else None
        }
        
        return stats
    
    def print_performance_report(self):
        """Print formatted performance report."""
        stats = self.get_statistics()
        
        print("\n" + "="*70)
        print("ADAPTIVE SIGNAL FILTER PERFORMANCE REPORT")
        print("="*70)
        print(f"Signals Evaluated: {stats['total_signals']}")
        print(f"Accepted: {stats['accepted']} ({stats['acceptance_rate']})")
        print(f"Rejected: {stats['rejected']}")
        print(f"\nCurrent Threshold: {stats['current_threshold']}")
        print(f"ML Model Accuracy: {stats['ml_accuracy']}")
        
        print("\nAcceptance Breakdown:")
        for method, count in stats['acceptance_methods'].items():
            print(f"  {method.replace('_', ' ').title()}: {count}")
        
        if stats['rejection_categories']:
            print("\nTop Rejection Reasons:")
            sorted_reasons = sorted(stats['rejection_categories'].items(), 
                                   key=lambda x: x[1], reverse=True)
            for reason, count in sorted_reasons[:3]:
                print(f"  {reason.replace('_', ' ').title()}: {count}")
        
        # Recent suggestions
        if self.rejected_signals_log:
            recent = self.rejected_signals_log[-5:]
            print("\nRecent Rejection Suggestions:")
            for i, rej in enumerate(recent, 1):
                if rej['suggestions']:
                    print(f"  {i}. {rej['suggestions'][0]}")
        
        print("="*70 + "\n")


def _adaptive_should_trade_signal_override(self, signal: Dict[str, Any],
                                           analysis_data: Dict[str, Any],
                                           timestamp: Optional[datetime] = None,
                                           ml_confidence: float = 0.5) -> Tuple[bool, float, str]:
    symbol = signal.get('symbol', '')
    accuracy = self.get_current_ml_accuracy() or 0.50
    accuracy_floor = self.get_effective_accuracy_gate(
        ml_confidence=ml_confidence,
        analysis_data=analysis_data,
        timestamp=timestamp,
        symbol=symbol,
    )

    current_time = datetime.now(timezone.utc)
    if SESSION_ACCURACY_IGNORE and current_time < SESSION_ACCURACY_IGNORE_EXPIRY and ml_confidence > 0.80:
        accuracy_floor = 0.0
        logger.critical(f"[ACCURACY_SESSION_OVERRIDE] {symbol} | Confidence {ml_confidence:.1%} > 80% | Ignoring all accuracy floors.")

    entry = signal.get('entry_price')
    sl = signal.get('stop_loss')
    tp = signal.get('take_profit')
    rr = 0.0
    if entry and sl and tp:
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk > 0:
            rr = reward / risk

    if ml_confidence > 0.80 and rr > 2.0:
        accuracy_floor = max(0.20, accuracy_floor - 0.08)
        logger.info(
            f"[ACCURACY_OVERRIDE] {symbol} | Confidence {ml_confidence:.1%} | RR {rr:.2f} | "
            f"Adaptive floor eased to {accuracy_floor:.1%}."
        )

    if accuracy < accuracy_floor:
        self.trades_rejected += 1
        self.rejection_reasons['low_accuracy'] = self.rejection_reasons.get('low_accuracy', 0) + 1
        logger.warning(f"[ACCURACY_VETO] {symbol} | ML Accuracy {accuracy:.1%} < {accuracy_floor:.1%} requirement. Rejecting signal.")
        return False, 0.0, f"ML Accuracy below adaptive {accuracy_floor:.1%} floor (Veto Active)"

    effective_min_score = self.get_quality_threshold(ml_confidence)
    if accuracy > 0.70:
        effective_min_score = min(65.0, self.current_min_score)
        logger.debug(f"[ACCURACY BOOST] ML Accuracy {accuracy:.1%} > 70%: Lowering min_score to {effective_min_score}")

    base_score = self.scorer.calculate_score(analysis_data, timestamp)
    session = self.regime_detector.detect_session(timestamp)
    thresholds = self.regime_detector.get_dynamic_thresholds(session)
    ml_boost = ml_confidence * 15.0
    atr = analysis_data.get('atr', 0)
    atr_mean = analysis_data.get('atr_mean', 1)
    volatility_ratio = (atr / atr_mean) if atr_mean > 0 else 1.0
    vol_adjustment = min(10, (volatility_ratio - 1.0) * 15) if volatility_ratio > 1.3 else 0
    final_score = min(100, base_score + ml_boost + vol_adjustment)

    effective_adx_floor = thresholds.get('adx_weak', 20.0)
    logger.info(f"[ADX_FLOOR_VERIFY] {symbol} | Session: {session.value} | Effective ADX Floor: {effective_adx_floor:.1f}")

    session_relaxation = 0
    if session == TradingSession.TOKYO:
        adx = analysis_data.get('adx', 0)
        if adx >= (thresholds['adx_weak'] * 0.85):
            session_relaxation = 5
            logger.debug(f"[SESSION RELAX] Tokyo session: ADX {adx:.1f} -> +5 points")

    final_score = min(100, final_score + session_relaxation)

    if ml_confidence >= 0.80:
        self.trades_accepted += 1
        self.acceptance_by_method['ml_override'] += 1
        reason = f"[OK] ML ELITE OVERRIDE | ML Confidence: {ml_confidence:.1%} >= 80% | Score: {final_score:.1f} | {session.value}"
        logger.info(f"[ACCEPTED] {reason}")
        return True, final_score, reason

    if ml_confidence >= 0.70:
        self.trades_accepted += 1
        self.acceptance_by_method['ml_override'] += 1
        reason = f"[OK] ML OVERRIDE | ML Confidence: {ml_confidence:.1%} >= 70% | Score: {final_score:.1f} | {session.value}"
        logger.info(f"[ACCEPTED] {reason}")
        return True, final_score, reason

    if final_score >= effective_min_score:
        self.trades_accepted += 1
        self.acceptance_by_method['excellent_quality'] += 1
        reason = self._format_acceptance(
            final_score, base_score, ml_boost, vol_adjustment, session_relaxation,
            "EXCELLENT", session, effective_min_score
        )
        logger.info(f"[ACCEPTED] {reason}")
        return True, final_score, reason

    adaptive_threshold = effective_min_score * 0.70
    if final_score >= adaptive_threshold:
        self.trades_accepted += 1
        self.acceptance_by_method['adaptive_70pct'] += 1
        reason = self._format_acceptance(
            final_score, base_score, ml_boost, vol_adjustment, session_relaxation,
            f"ACCEPTABLE (70% of {self.current_min_score:.0f})", session, adaptive_threshold
        )
        logger.info(f"[ACCEPTED] {reason}")
        return True, final_score, reason

    self.trades_rejected += 1
    rejection_info = self._analyze_rejection(
        base_score, final_score, analysis_data, thresholds,
        ml_confidence, session, adaptive_threshold
    )
    category = rejection_info['category']
    self.rejection_reasons[category] = self.rejection_reasons.get(category, 0) + 1
    self.rejected_signals_log.append({
        'timestamp': timestamp,
        'score': final_score,
        'ml_conf': ml_confidence,
        'threshold': adaptive_threshold,
        'category': category,
        'suggestions': rejection_info['suggestions']
    })
    logger.warning(f"[REJECTED] {rejection_info['message']}")
    return False, final_score, rejection_info['message']


AdaptiveSignalFilterer.should_trade_signal = _adaptive_should_trade_signal_override



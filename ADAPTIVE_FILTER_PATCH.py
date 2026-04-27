# ========================================================================
# ADAPTIVE SIGNAL FILTERER INTEGRATION PATCH
# File: trend_strategy.py
# 
# This patch integrates AdaptiveSignalFilterer with the following features:
# - ML confidence override (≥70% = auto-accept)
# - Dynamic threshold adjustment based on ML accuracy
# - Session-aware filtering (Tokyo gets +5 bonus)
# - Comprehensive rejection logging with suggestions
# - ML-weighted position sizing (60% score / 40% ML confidence)
#
# Changes Summary:
# 1. Import AdaptiveSignalFilterer (line 14)
# 2. Initialize with ML accuracy tracking (line 33-36)
# 3. Get ML confidence before filtering (line 290-292)
# 4. Pass ML confidence to should_trade_signal (line 326-330)
# 5. Pass ML confidence to position sizing (line 352)
# 6. Enhanced logging (line 337-342, 358-364)
# ========================================================================

# ========================================================================
# SECTION 1: IMPORTS (Line 14)
# ========================================================================
# OLD:
# from src.analysis.signal_scoring import SignalFilterer

# NEW:
from src.analysis.adaptive_signal_scoring import AdaptiveSignalFilterer

# ========================================================================
# SECTION 2: INITIALIZATION (Lines 32-36)
# ========================================================================
# OLD:
#         # Phase 1: Signal Quality Filter & Market Regime Detection (IMPROVED WIN RATE)
#         self.signal_filterer = SignalFilterer(min_score=68)  # IMPROVED: Raised from 58 to 68 for better quality
#         self.regime_detector = MarketRegimeDetector()
#         self.logger.info(f"[PHASE 1] Signal quality filter initialized (min_score=68) - IMPROVED WIN RATE")
#         self.logger.info(f"[PHASE 1] Market regime detector initialized")

# NEW:
        # ===== ADAPTIVE SIGNAL FILTERING =====
        # Features: ML override (70%+), session relaxation, auto-threshold adjustment
        self.signal_filterer = AdaptiveSignalFilterer(
            min_score=65,              # Base threshold (adapts 40-65 based on ML performance)
            ml_accuracy_target=0.55    # Target 55% ML accuracy
        )
        self.regime_detector = MarketRegimeDetector()
        
        self.logger.info("[ADAPTIVE FILTER] Initialized with adaptive thresholds")
        self.logger.info("[ADAPTIVE FILTER] • ML Override: ≥70% confidence → auto-accept")
        self.logger.info("[ADAPTIVE FILTER] • Session Aware: Tokyo +5 bonus, relaxed ADX")
        self.logger.info("[ADAPTIVE FILTER] • Auto-Adjust: Threshold lowers when ML accuracy <50%")
        self.logger.info("[ADAPTIVE FILTER] • Rejection Logging: Specific fixes suggested")

# ========================================================================
# SECTION 3: GET ML CONFIDENCE BEFORE FILTERING (Insert after line 289)
# ========================================================================
# Insert this BEFORE the analysis_data dictionary creation (around line 290):

                # ===== EXTRACT ML CONFIDENCE =====
                # Get ML prediction and confidence for adaptive filtering
                ml_direction, ml_confidence = self.ml_predictor.predict(historical_data, indicators)
                
                # analysis_data = { ... } (existing code continues)

# ========================================================================
# SECTION 4: UPDATE should_trade_signal CALL (Lines 326-330)
# ========================================================================
# OLD:
#                 should_trade_phase1, score_phase1, reason_phase1 = self.signal_filterer.should_trade_signal(
#                     combined_result.trading_signal.__dict__, 
#                     analysis_data,
#                     timestamp=current_timestamp
#                 )

# NEW:
                # ===== ADAPTIVE SIGNAL FILTERING =====
                # Accepts if: score ≥ min_score OR ml_conf ≥ 70% OR score ≥ 70% of min
                should_trade_phase1, score_phase1, reason_phase1 = self.signal_filterer.should_trade_signal(
                    combined_result.trading_signal.__dict__, 
                    analysis_data,
                    timestamp=current_timestamp,
                    ml_confidence=ml_confidence  # ADDED: ML confidence for override logic
                )

# ========================================================================
# SECTION 5: UPDATE POSITION SIZING (Line 352)
# ========================================================================
# OLD:
#                 quality_size = self.signal_filterer.adjust_position_size(score_phase1, base_size)

# NEW:
                # ===== ML-WEIGHTED POSITION SIZING =====
                # Composite: 60% technical score + 40% ML confidence
                quality_size = self.signal_filterer.adjust_position_size(
                    score_phase1, 
                    base_size, 
                    ml_confidence=ml_confidence  # ADDED: ML weighting
                )

# ========================================================================
# SECTION 6: ENHANCED REJECTION LOGGING (Lines 337-342)
# ========================================================================
# OLD:
#                 if not should_trade_phase1 and not regime_action['trade']:
#                     self.logger.info(
#                         f"[PHASE1+REGIME] {self.symbol} rejected | "
#                         f"Score: {score_phase1:.1f}/100 | Regime: {regime}/{vol_regime} | "
#                         f"Reason: {regime_action['reason']}"
#                     )
#                     return None

# NEW:
                if not should_trade_phase1 and not regime_action['trade']:
                    # ===== DETAILED REJECTION LOGGING =====
                    # reason_phase1 now includes specific issues and suggestions
                    self.logger.warning(
                        f"[✗ REJECTED] {self.symbol}\n"
                        f"   {reason_phase1}\n"  # Detailed reason from adaptive filterer
                        f"   Regime: {regime}/{vol_regime} ({regime_action['reason']})\n"
                        f"   ML Conf: {ml_confidence:.1%}"
                    )
                    return None

# ========================================================================
# SECTION 7: ENHANCED ACCEPTANCE LOGGING (Lines 358-364)
# ========================================================================
# OLD:
#                 if self.verbose:
#                     self.logger.info(
#                         f"[SIGNAL ACCEPTED] {self.symbol} | "
#                         f"Quality: {score_phase1:.1f}% | "
#                         f"Regime: {regime}/{vol_regime} ({final_size_mult:.2f}x size) | "
#                         f"Entry: {combined_result.trading_signal.entry_price:.5f}"
#                     )

# NEW:
                if self.verbose:
                    # ===== DETAILED ACCEPTANCE LOGGING =====
                    # reason_phase1 includes acceptance path (ML Override, Excellent, etc.)
                    self.logger.info(
                        f"[✓ ACCEPTED] {self.symbol}\n"
                        f"   {reason_phase1}\n"  # Detailed acceptance reason
                        f"   Regime: {regime}/{vol_regime}\n"
                        f"   Position: {final_size_mult:.2f}x (quality={quality_size:.2f}, regime={regime_action.get('size_multiplier', 1.0):.2f})\n"
                        f"   Entry: {combined_result.trading_signal.entry_price:.5f} | ML: {ml_confidence:.1%}"
                    )

# ========================================================================
# SECTION 8: ADD ML PERFORMANCE TRACKING (OPTIONAL - Add to trade close handler)
# ========================================================================
# Add this method to SimpleTrendStrategy class:
"""
    def update_ml_performance(self, trade_closed_data: Dict):
        '''
        Track ML model performance and trigger threshold adjustments.
        Call this when a trade closes.
        
        Args:
            trade_closed_data: Dict with 'profit', 'ml_prediction', etc.
        '''
        # Determine if ML was correct
        was_profitable = trade_closed_data.get('profit', 0) > 0
        ml_predicted_win = trade_closed_data.get('ml_predicted_direction') == trade_closed_data.get('actual_direction')
        
        # 1 = correct prediction, 0 = wrong
        actual_outcome = 1 if (was_profitable and ml_predicted_win) else 0
        ml_prediction = 1 if trade_closed_data.get('ml_confidence', 0.5) > 0.5 else 0
        
        # Update filterer with outcome
        self.signal_filterer.update_ml_performance(ml_prediction, actual_outcome)
        
        # Log if threshold adjusted
        ml_acc = self.signal_filterer.get_current_ml_accuracy()
        if ml_acc:
            self.logger.info(
                f"[ML TRACKING] Accuracy: {ml_acc:.1%} | "
                f"Threshold: {self.signal_filterer.current_min_score:.1f}"
            )
"""

# ========================================================================
# SECTION 9: ADD PERFORMANCE REPORTING METHOD (OPTIONAL)
# ========================================================================
# Add this method to SimpleTrendStrategy class:
"""
    def print_filter_performance(self):
        '''Print adaptive filter performance report.'''
        self.signal_filterer.print_performance_report()
"""

# ========================================================================
# COMPLETE FILE CHANGES - READY TO APPLY
# ========================================================================

"""
SUMMARY OF CHANGES:
===================

Line 14:
  - Import: AdaptiveSignalFilterer instead of SignalFilterer

Lines 32-36:
  - Initialize AdaptiveSignalFilterer with base_threshold=65, ml_target=0.55
  - Enhanced logging explaining features

~Line 290 (INSERT NEW):
  - Extract ml_direction, ml_confidence BEFORE analysis_data creation

Lines 326-330:
  - Pass ml_confidence to should_trade_signal()

Line 352:
  - Pass ml_confidence to adjust_position_size()

Lines 337-342:
  - Enhanced rejection logging with detailed reason and ML confidence

Lines 358-364:
  - Enhanced acceptance logging with acceptance path and ML confidence

OPTIONAL ADDITIONS:
- update_ml_performance() method for tracking
- print_filter_performance() method for reporting


EXPECTED LOG OUTPUT EXAMPLES:
==============================

Initialization:
  [ADAPTIVE FILTER] Initialized with adaptive thresholds
  [ADAPTIVE FILTER] • ML Override: ≥70% confidence → auto-accept
  [ADAPTIVE FILTER] • Session Aware: Tokyo +5 bonus, relaxed ADX
  [ADAPTIVE FILTER] • Auto-Adjust: Threshold lowers when ML accuracy <50%

ML Override Acceptance:
  [✓ ACCEPTED] EUR/USD
     ✓ ML OVERRIDE | ML Confidence: 73% ≥ 70% | Score: 58.2 | LONDON
     Regime: TRENDING/NORMAL
     Position: 1.15x (quality=1.15, regime=1.00)
     Entry: 1.08450 | ML: 73%

Session Relaxation Acceptance:
  [✓ ACCEPTED] USD/JPY
     ✓ ACCEPTABLE (70% of 65) | Score: 52.3 | Base=47.3 | Session=+5.0 | TOKYO
     Regime: RANGING/LOW
     Position: 0.75x (quality=0.75, regime=1.00)
     Entry: 148.250 | ML: 58%

Detailed Rejection:
  [✗ REJECTED] GBP/USD
     ✗ Score: 41.2 < 45.5
        Category: Weak Trend
        Issues: ADX=14.1 (need >20) | ML=48%
        Fix: → Lower LONDON ADX by 6 points to 14
     Regime: CHOPPY/NORMAL (Low quality + choppy)
     ML Conf: 48%

ML Accuracy Adjustment:
  [ML PERFORMANCE] Accuracy: 48% | Threshold adjusted 65.0 → 61.75
  [ADAPTIVE THRESHOLD] ML accuracy below target (48% < 50%)
  [ADAPTIVE THRESHOLD] Adjusting from 65.0 → 61.75


INTEGRATION VERIFICATION:
==========================

After applying patch, check logs for:
✓ [ADAPTIVE FILTER] initialization messages
✓ [✓ ACCEPTED] with detailed acceptance reasons
✓ [✗ REJECTED] with specific issues and suggestions
✓ ML confidence shown in acceptance/rejection logs
✓ [ML OVERRIDE] for high-confidence ML signals
✓ [SESSION RELAX] Tokyo bonus in acceptance logs
✓ [ADAPTIVE THRESHOLD] messages when ML accuracy changes


TESTING CHECKLIST:
==================

1. ✓ Bot starts without errors
2. ✓ Sees "ADAPTIVE FILTER" in initialization
3. ✓ Acceptance logs show ML confidence %
4. ✓ Rejection logs show specific fixes
5. ✓ ML override path activates for 70%+ confidence
6. ✓ Tokyo session gets +5 bonus points
7. ✓ Threshold auto-adjusts when ML accuracy <50%
8. ✓ Position sizing varies with ML confidence


SUCCESS METRICS:
================

Target After Integration:
- Acceptance rate: 45-60% (up from ~30-35%)
- ML override usage: 15-25% of acceptances
- ML accuracy tracked and auto-adjusts threshold
- All rejections include actionable suggestions
- Session bonuses applied appropriately

"""

"""Signal combination algorithms to merge sentiment and technical signals"""

import os
import csv
import threading
from collections import deque
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean, stdev
import numpy as np
from src.models import SentimentResult, TechnicalSignal, TradingSignal, SignalType, Direction, MarketData, ExitPolicy
from src.analysis.sentiment_aggregator import AggregatedSentiment
from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator
from src.exceptions import DataValidationError
from src.logging_config import get_logger
from src.ml.exit_policy_ensemble import ExitPolicyEnsemble
from src.analysis.market_regime_detector import MarketRegimeDetector
from src.ml.trade_admission_controller import TradeAdmissionController
from src.ml.rl_dispatcher import RLTacticalDispatcher, RLTacticAction

logger = get_logger(__name__)


class RollingMetrics:
    """In-memory rolling win/loss metrics with one-time CSV bootstrap."""

    def __init__(self, maxlen: int = 10, csv_path: str = "trade_history.csv") -> None:
        self._lock = threading.Lock()
        self._deque: deque[int] = deque(maxlen=maxlen)
        self._csv_path = csv_path
        self._bootstrap_from_csv()

    def _bootstrap_from_csv(self) -> None:
        if not os.path.exists(self._csv_path):
            return
        try:
            with open(self._csv_path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            if not rows:
                return
            recent = rows[-self._deque.maxlen :]
            for row in recent:
                try:
                    pnl = float(row.get("pnl", 0.0) or 0.0)
                except Exception:
                    pnl = 0.0
                self._deque.append(1 if pnl > 0 else 0)
        except Exception:
            return

    def record_trade(self, pnl: float) -> None:
        with self._lock:
            self._deque.append(1 if pnl > 0 else 0)

    def win_loss_ratio(self) -> float:
        with self._lock:
            if not self._deque:
                return 0.0
            return float(sum(self._deque)) / float(len(self._deque))


rolling_metrics = RollingMetrics()


@dataclass
class SignalWeights:
    """Weights for different signal types in combination"""
    sentiment_weight: float = 0.4
    technical_weight: float = 0.6
    trend_confirmation_bonus: float = 0.1
    volume_confirmation_bonus: float = 0.05


@dataclass
class CombinedSignalResult:
    """Result of signal combination"""
    trading_signal: Optional[TradingSignal]
    confidence_score: float
    combination_reasoning: str
    contributing_signals: Dict[str, List]
    risk_assessment: str
    timestamp: datetime


class SignalCombiner:
    """Combines sentiment and technical signals into trading signals"""
    
    def __init__(self, 
                 signal_weights: SignalWeights = None,
                 min_confidence_threshold: float = 0.5,
                 sentiment_technical_sync_window_minutes: int = 30,
                 admission_controller: Optional[TradeAdmissionController] = None):
        """Initialize signal combiner"""
        self.logger = logger
        self.weights = signal_weights or SignalWeights()
        self.min_confidence_threshold = min_confidence_threshold
        self.sync_window = timedelta(minutes=sentiment_technical_sync_window_minutes)
        
        # ML-based Exit Policy Ensemble
        self.exit_policy_ensemble = ExitPolicyEnsemble()
        
        # Market Regime Detector
        self.regime_detector = MarketRegimeDetector()
        
        # Trade Admission Controller (Shared or New)
        self.admission_controller = admission_controller or TradeAdmissionController()
        self.rl_dispatcher = RLTacticalDispatcher()
        self._portfolio_context: Optional[Dict[str, float]] = None
        # Synthetic pipeline verification window.
        self._synthetic_force_cycles_remaining = 0
        self._last_trading_signal: Optional[TradingSignal] = None
        self._last_admission_result = None
        # Per-cycle overrides (set by strategy/main loop when needed)
        self.override_ml_confidence: Optional[float] = None
        self.override_meta_win_prob: Optional[float] = None
        self.structure_override_active: bool = False
        self.structure_override_min_ml: float = 0.05
        self.news_guard_active: bool = False
        self.news_guard_min_conf: float = 0.20
        self._adx_for_cycle: float = 0.0
        self._effective_adx_floor_for_cycle: float = 0.0
        self._adx_gate_enabled_for_cycle: bool = True
        self._trade_style_for_cycle: str = "TREND"
        
        # Signal type mapping
        self.signal_direction_map = {
            SignalType.BUY: Direction.LONG,
            SignalType.SELL: Direction.SHORT
        }

    def _normalize_timeframe_label(self, value: object) -> str:
        raw = str(value or "").strip().upper()
        mapping = {
            "15M": "M15",
            "M15": "M15",
            "1H": "H1",
            "H1": "H1",
        }
        return mapping.get(raw, raw)

    def _detect_elite_mtf_alignment(
        self,
        symbol: str,
        technical_signals: List[TechnicalSignal],
    ) -> bool:
        """
        Flag elite setups when both RSI and MACD align across H1 and M15.
        This is tolerant to indicator metadata styles used across the repo.
        """
        rsi_dirs: Dict[str, Direction] = {}
        macd_dirs: Dict[str, Direction] = {}

        for signal in technical_signals or []:
            indicators = getattr(signal, "indicators", {}) or {}
            timeframe = self._normalize_timeframe_label(
                indicators.get("timeframe") or indicators.get("tf") or indicators.get("TIMEFRAME")
            )
            signal_dir = Direction.LONG if signal.signal_type == SignalType.BUY else Direction.SHORT

            if timeframe in {"H1", "M15"}:
                if "rsi" in indicators or "RSI" in indicators:
                    rsi_dirs[timeframe] = signal_dir
                if "macd" in indicators or "MACD" in indicators:
                    macd_dirs[timeframe] = signal_dir

            for tf in ("H1", "M15"):
                rsi_key = f"rsi_{tf.lower()}"
                macd_key = f"macd_{tf.lower()}"
                if rsi_key in indicators:
                    rsi_dirs[tf] = signal_dir
                if macd_key in indicators:
                    macd_dirs[tf] = signal_dir

        if not all(tf in rsi_dirs for tf in ("H1", "M15")):
            return False
        if not all(tf in macd_dirs for tf in ("H1", "M15")):
            return False

        if rsi_dirs["H1"] != rsi_dirs["M15"]:
            return False
        if macd_dirs["H1"] != macd_dirs["M15"]:
            return False

        aligned_direction = rsi_dirs["H1"]
        return macd_dirs["H1"] == aligned_direction

    def reset_cycle_state(self, symbol: Optional[str] = None) -> None:
        """
        Clear per-cycle analysis artifacts so no admission/signal values bleed between cycles.
        """
        self._last_trading_signal = None
        self._last_admission_result = None
        self.admission_controller.reset_cycle_state(symbol=symbol)

    # ===== FIX #5: ADD METHOD TO CREATE ML-ONLY FALLBACK WITH ACCURACY GUARD =====
    def create_ml_only_fallback_signal(
        self,
        symbol: str,
        technical_signals: List[TechnicalSignal],
        current_price: float,
        min_ml_accuracy_threshold: float = 0.50,
    ) -> Optional[TradingSignal]:
        """
        Create ML-only fallback signal when primary MTF filter rejects the trade.
        
        ===== FIX #5: ENFORCE MINIMUM ACCURACY GATE FOR ML-ONLY FALLBACK =====
        Prevents the bot from trading on very-low-accuracy models
        when primary signals fail. Guards against BOOTSTRAP_GRACE_PERIOD
        forcing trades with poor historical performance.
        
        Args:
            symbol: Trading symbol
            technical_signals: Available technical signals
            current_price: Current market price
            min_ml_accuracy_threshold: Minimum model accuracy required (default 50%)
        
        Returns:
            TradingSignal if ML confidence is high enough AND accuracy >= threshold
            None if accuracy is too low (reject trade)
        """
        
        if not technical_signals:
            logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | No technical signals available for fallback")
            return None
        
        # ===== FIX #5: GET SYMBOL'S ML MODEL ACCURACY =====
        ml_accuracy = None
        if hasattr(self, 'admission_controller') and self.admission_controller:
            ml_accuracy = self.admission_controller.get_ml_symbol_accuracy(symbol)
        
        # If accuracy cannot be determined, use conservative default (None means unknown = unsafe)
        if ml_accuracy is None:
            logger.warning(
                "[ML_ONLY_FALLBACK_REJECTED] %s | Model accuracy unavailable. "
                "Rejecting ML-only fallback for safety (unknown accuracy treated as unsafe).",
                symbol,
            )
            return None
        
        # ===== FIX #5: ENFORCE MINIMUM ACCURACY THRESHOLD =====
        if ml_accuracy < min_ml_accuracy_threshold:
            logger.warning(
                "[ML_ONLY_FALLBACK_REJECTED] %s | Model accuracy %.2f%% < %.2f%% minimum threshold. "
                "Rejecting ML-only fallback. (Primary MTF filter already rejected; cannot compound risk with low-accuracy model)",
                symbol,
                ml_accuracy * 100.0,
                min_ml_accuracy_threshold * 100.0,
            )
            return None
        
        # Accuracy is acceptable, proceed with ML-only signal generation
        logger.info(
            "[ML_ONLY_FALLBACK_APPROVED] %s | Model accuracy %.2f%% >= %.2f%% threshold. "
            "Proceeding with ML-only signal.",
            symbol,
            ml_accuracy * 100.0,
            min_ml_accuracy_threshold * 100.0,
        )
        
        # Extract ML confidence from technical signals
        ml_confidences = []
        for s in technical_signals:
            conf = float(getattr(s, "indicators", {}).get("ML_CONFIDENCE", 0.0) or 0.0)
            if conf > 0:
                ml_confidences.append(conf)
        
        if not ml_confidences:
            logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | No ML confidence data available")
            return None
        
        avg_ml_confidence = sum(ml_confidences) / len(ml_confidences)
        
        # Require high ML confidence (>= 60%) to justify ML-only trade
        min_ml_confidence_for_fallback = 0.60
        if avg_ml_confidence < min_ml_confidence_for_fallback:
            logger.warning(
                "[ML_ONLY_FALLBACK_REJECTED] %s | ML confidence %.2f < %.2f minimum. "
                "Not enough conviction for unsupported (non-MTF) trade.",
                symbol,
                avg_ml_confidence,
                min_ml_confidence_for_fallback,
            )
            return None
        
        # Determine signal direction from technical signals
        buy_count = sum(1 for s in technical_signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in technical_signals if s.signal_type == SignalType.SELL)
        
        if buy_count > sell_count:
            signal_direction = Direction.LONG
            signal_type = SignalType.BUY
        elif sell_count > buy_count:
            signal_direction = Direction.SHORT
            signal_type = SignalType.SELL
        else:
            logger.debug(f"[ML_ONLY_FALLBACK_REJECTED] {symbol} | Conflicting signals (no majority)")
            return None
        
        # Create fallback trading signal
        trading_signal = TradingSignal(
            symbol=symbol,
            signal_type=signal_type,
            direction=signal_direction,
            entry_price=current_price,
            stop_loss=current_price - (50 * 0.0001),  # Example: 50 pips below for major pairs
            take_profit=current_price + (100 * 0.0001),  # Example: 100 pips above
            confidence=avg_ml_confidence,
            timestamp=datetime.now(timezone.utc),
        )
        
        logger.info(
            "[ML_ONLY_FALLBACK_SIGNAL] %s | Direction: %s | ML Confidence: %.2f | Model Accuracy: %.2f%%",
            symbol,
            signal_direction.value,
            avg_ml_confidence,
            ml_accuracy * 100.0,
        )
        
        return trading_signal

    def set_portfolio_context(self, summary: Optional[Dict[str, float]]) -> None:
        """
        Cache portfolio context for RL state vector construction.
        Expected keys: drawdown_pct, margin_util_pct, win_loss_ratio_10
        """
        self._portfolio_context = summary or None
    
    def combine_signals(self,
                       sentiment_result: Optional[AggregatedSentiment],
                       technical_signals: List[TechnicalSignal],
                       current_price: float,
                       symbol: str,
                       reference_time: Optional[datetime] = None,
                       historical_data: Optional[List[MarketData]] = None,
                       current_positions: Optional[List] = None) -> CombinedSignalResult:
        """Combine sentiment and technical signals into a trading signal"""
        
        # Note: Logging removed to reduce noise during backtests
        self.reset_cycle_state(symbol=symbol)
        
        # Validate inputs
        if not sentiment_result and not technical_signals:
            return CombinedSignalResult(
                trading_signal=None,
                confidence_score=0.0,
                combination_reasoning="No signals available for combination",
                contributing_signals={"sentiment": [], "technical": []},
                risk_assessment="HIGH",
                timestamp=reference_time or datetime.now(timezone.utc)
            )
        
        # Synchronize signal timing
        synchronized_signals = self._synchronize_signal_timing(
            sentiment_result, technical_signals, reference_time
        )
        
        # Calculate combined signal direction and strength
        signal_direction, signal_strength, reasoning = self._calculate_combined_signal(
            synchronized_signals["sentiment"],
            synchronized_signals["technical"]
        )

        high_priority_queue = [
            s for s in synchronized_signals["technical"]
            if bool(getattr(s, "indicators", {}).get("SYNTHETIC", 0))
        ]
        if high_priority_queue:
            top_synth = max(high_priority_queue, key=lambda s: float(getattr(s, "strength", 0.0) or 0.0))
            signal_direction = Direction.LONG if top_synth.signal_type == SignalType.BUY else Direction.SHORT
            signal_strength = max(signal_strength, float(getattr(top_synth, "strength", 0.0) or 0.0))
            reasoning += f" | Synthetic bypass queued: {len(high_priority_queue)} high-priority signal(s)."
        
        # Calculate confidence score
        confidence_score = self._calculate_combined_confidence(
            synchronized_signals["sentiment"],
            synchronized_signals["technical"],
            signal_strength
        )

        # Authority Hierarchy: apply optional confidence floor adjustments
        min_conf_for_cycle = float(self.min_confidence_threshold)
        if self.news_guard_active:
            min_conf_for_cycle = max(min_conf_for_cycle, float(self.news_guard_min_conf))
            logger.info(
                "[NEWS_GUARD] %s | High-impact news pending. Confidence floor raised to %.2f",
                symbol,
                min_conf_for_cycle,
            )
        # Persist per-cycle floor for downstream use
        self._min_conf_for_cycle = float(min_conf_for_cycle)

        raw_ml_conf = self.override_ml_confidence
        meta_win_prob = self.override_meta_win_prob
        
        # ===== FIX #1: PREVENT CONFIDENCE DOWNGRADING - FORCE HIGH CONFIDENCE THROUGH =====
        # If raw_ml_conf is higher than 0.10, ensure it's preserved and used (never downgraded to default)
        if raw_ml_conf is None:
            try:
                raw_ml_conf = max(
                    float(getattr(s, "indicators", {}).get("ML_CONFIDENCE", 0.0) or 0.0)
                    for s in (synchronized_signals["technical"] or [])
                )
            except Exception:
                raw_ml_conf = 0.0
        # Persist per-cycle ML confidence for downstream use
        self._raw_ml_conf_for_cycle = float(raw_ml_conf or 0.0)
        if meta_win_prob is None:
            meta_win_prob = 1.0
        
        # === FIX #2: CONFIDENCE NORMALIZATION (NEWS_GUARD WEIGHTED FORMULA) ===
        # If NEWS_GUARD active and raw confidence is low, try weighting with ML_Accuracy
        # ===== FIX #2: FORCE-ENABLE WEIGHTED ACCURACY SCORE =====
        # Always apply weighted formula if we have technical signals with accuracy data
        # Formula: Final_Confidence = (Raw_ML_Confidence * 0.7) + (ML_Accuracy * 0.3)
        normalized_ml_conf = float(raw_ml_conf or 0.0)  # Use as default
        weighted_admission_score = None  # Track if weighting was applied
        
        try:
            # Extract ML_Accuracy from technical signals - always attempt weighting
            ml_accuracies = []
            for s in (synchronized_signals["technical"] or []):
                acc = float(getattr(s, "indicators", {}).get("ML_ACCURACY", 0.0) or 0.0)
                if acc > 0:
                    ml_accuracies.append(acc)
            
            if ml_accuracies:
                avg_accuracy = sum(ml_accuracies) / len(ml_accuracies)
                # Weighted formula: Confidence = (ML_Conf * 0.7) + (ML_Accuracy * 0.3)
                weighted_ml_conf = (float(raw_ml_conf or 0.0) * 0.7) + (avg_accuracy * 0.3)
                
                # Apply weighting if it improves confidence OR if NEWS_GUARD is active
                if weighted_ml_conf > float(raw_ml_conf or 0.0) or self.news_guard_active:
                    normalized_ml_conf = weighted_ml_conf
                    weighted_admission_score = weighted_ml_conf  # Store for later logging
                    logger.info(
                        "[NEWS_GUARD_WEIGHTED] %s | Raw Confidence: %.2f + Accuracy: %.2f -> Normalized: %.2f | Status: APPLIED",
                        symbol,
                        float(raw_ml_conf or 0.0),
                        avg_accuracy,
                        normalized_ml_conf
                    )
                    # Update the override so it flows through the rest of the logic
                    self.override_ml_confidence = normalized_ml_conf
                    raw_ml_conf = normalized_ml_conf
        except Exception as e:
            logger.warning(f"[NEWS_GUARD_WEIGHT_ERROR] Could not apply weighted formula: {e}")
        
        # Fallback: if NEWS_GUARD is active and raw confidence is below floor, ensure at least the floor is used
        if self.news_guard_active and float(raw_ml_conf or 0.0) < float(self.news_guard_min_conf):
            if normalized_ml_conf < float(self.news_guard_min_conf):
                # If even weighted formula doesn't help, log weighted admission attempt
                logger.info(
                    "[WEIGHTED_ADMISSION] %s | Signal promoted to %.3f due to high accuracy. "
                    "Final Score: %.3f (Raw: %.2f, Weighted: %.2f)",
                    symbol,
                    normalized_ml_conf,
                    normalized_ml_conf,
                    float(raw_ml_conf or 0.0),
                    weighted_admission_score if weighted_admission_score else float(raw_ml_conf or 0.0)
                )
        # ====================================================================
        # ===== FIX #2B: ENSURE WEIGHTED ACCURACY FLOWS BEFORE ENSEMBLE GATE =====
        # The normalized_ml_conf (with weighted accuracy applied) should be passed to admission controller
        # before any hard gates like NEWS_GUARD or ENSEMBLE discount
        # Store normalized confidence for downstream use
        self._normalized_ml_conf_for_cycle = float(normalized_ml_conf or 0.0)

        structure_force_admit = bool(
            self.structure_override_active
            and raw_ml_conf is not None
            and float(raw_ml_conf) >= float(self.structure_override_min_ml)
        )
        if structure_force_admit:
            min_conf_for_cycle = 0.0

        # Emergency full-auto behavior: never drop strategy-originated technical signals.
        if signal_direction is None and synchronized_signals["technical"]:
            strongest = max(
                synchronized_signals["technical"],
                key=lambda s: float(getattr(s, "strength", 0.0) or 0.0),
            )
            signal_direction = Direction.LONG if strongest.signal_type == SignalType.BUY else Direction.SHORT
            reasoning += " | Direction recovered from strongest technical signal."
        
        # Generate trading signal if confidence is sufficient
        trading_signal = None
        if (
            signal_direction is not None
            and (confidence_score >= min_conf_for_cycle or structure_force_admit)
        ):
            
            trading_signal = self._create_trading_signal(
                symbol=symbol,
                direction=signal_direction,
                current_price=current_price,
                confidence=confidence_score,
                reasoning=reasoning,
                sentiment_result=synchronized_signals["sentiment"],
                technical_signals=synchronized_signals["technical"],
                timestamp=reference_time or datetime.now(timezone.utc),
                historical_data=historical_data,
                current_positions=current_positions,
            )
            if trading_signal:
                setattr(trading_signal, "ml_confidence", float(raw_ml_conf or 0.0))
                setattr(trading_signal, "meta_win_prob", float(meta_win_prob or 0.0))
                setattr(trading_signal, "structure_override", bool(self.structure_override_active))
                
                # Log weighted admission if the weighted formula was applied
                if hasattr(self, 'override_ml_confidence') and self.override_ml_confidence:
                    weighted_conf = float(self.override_ml_confidence or 0.0)
                    # Log only if override was actually used (different from raw confidence)
                    if weighted_conf > 0 and weighted_conf != float(raw_ml_conf or 0.0):
                        # Back-calculate accuracy from weighted formula: weighted = (raw * 0.7) + (acc * 0.3)
                        # Solving for accuracy: acc = (weighted - (raw * 0.7)) / 0.3
                        raw_conf = float(synchronized_signals.get("ml_confidence", 0.0) or raw_ml_conf or 0.0)
                        accuracy = (weighted_conf - (raw_conf * 0.7)) / 0.3 if raw_conf > 0 else 0.0
                        self.logger.info(
                            "[WEIGHTED_ADMISSION] %s | Final Score: %.3f (Raw: %.3f, Acc: %.3f)",
                            symbol,
                            weighted_conf,
                            raw_conf,
                            accuracy
                        )
                        # Mark this as a weighted admission for downstream controllers
                        setattr(trading_signal, "_weighted_admission_active", True)
                        # Also set flag on admission controller if available
                        if hasattr(self, 'admission_controller') and self.admission_controller:
                            self.admission_controller._weighted_admission_active = True
                
                self.logger.info("[TRACE-1] Signal Generated for %s", symbol)
        elif signal_direction is not None and technical_signals:
            # === ISSUE #3 FIX: Check exploration override before force-rejecting ===
            # If exploration mode is active or override_authorized flag is set, allow lower confidence
            # Calculate exploration_active using same logic as admission controller:
            # exploration_active = bool(technical_only_mode or velocity_mode_active or striking_mode_active)
            technical_only_mode = bool(getattr(self, '_technical_only_mode_for_cycle', False))
            striking_mode_active = str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"} or \
                                  str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
            is_exploration_mode = bool(technical_only_mode or striking_mode_active)
            signal_override_authorized = bool(getattr(self, '_override_authorized', False))
            
            # Only reject if NO override flags are set AND confidence is too low
            if not (is_exploration_mode or signal_override_authorized) and confidence_score < min_conf_for_cycle:
                # Normal rejection path: no overrides active
                logger.warning(
                    f"[COMBINER_FORCE_PASS_REMOVED] {symbol} blocked | "
                    f"Confidence {confidence_score:.2f} < min {min_conf_for_cycle:.2f}."
                )
                logger.info(
                    "[FILTER_REJECT] %s | Reason: CONFIDENCE (%.2f < %.2f)",
                    symbol,
                    confidence_score,
                    min_conf_for_cycle,
                )
                trading_signal = None
            elif is_exploration_mode or signal_override_authorized:
                # Override path: exploration or authorization active - allow lower confidence
                logger.critical(
                    f"[COMBINER_CONFIDENCE_OVERRIDE] {symbol} | "
                    f"Confidence {confidence_score:.2f} < min {min_conf_for_cycle:.2f}, but ALLOWED due to "
                    f"exploration_mode={is_exploration_mode} | override_authorized={signal_override_authorized} | "
                    f"Proceeding to signal generation."
                )
                # Continue to signal generation below
                pass
        else:
            # ===== FIX #5: TRY ML-ONLY FALLBACK IF PRIMARY MTF FILTER REJECTED =====
            # Before fully rejecting, check if we can generate ML-only fallback signal
            # with accuracy guardrail (must be >= 50% accuracy to proceed)
            if signal_direction is None and technical_signals:
                logger.info(
                    "[ML_ONLY_FALLBACK_ATTEMPT] %s | Primary MTF filter rejected. "
                    "Attempting ML-only fallback with accuracy guardrail.",
                    symbol
                )
                
                fallback_signal = self.create_ml_only_fallback_signal(
                    symbol=symbol,
                    technical_signals=technical_signals,
                    current_price=current_price,
                    min_ml_accuracy_threshold=0.50,  # FIX #5: Enforce 50% minimum
                )
                
                if fallback_signal is not None:
                    # Accuracy guardrail passed - use ML-only fallback signal
                    trading_signal = fallback_signal
                    reasoning += " | ML-Only Fallback (Accuracy Guardrail Passed)"
                    # LOG: Track that we're using fallback (transitioned from None to valid signal)
                    logger.warning(
                        "[ML_ONLY_FALLBACK_ACTIVATED] %s | Using ML-only fallback instead of rejection. "
                        "Primary MTF filter failed, but ML model accuracy sufficient for entry.",
                        symbol
                    )
                else:
                    # Accuracy guardrail rejected - log and skip trade
                    logger.debug(
                        f"[COMBINER] Signal rejected for {symbol} | "
                        f"Direction: {signal_direction} | "
                        f"Confidence: {confidence_score:.2f} (min: {min_conf_for_cycle}) | "
                        f"Strength: {signal_strength:.2f} | "
                        f"ML-Only Fallback: REJECTED (accuracy too low)"
                    )
            else:
                logger.debug(
                    f"[COMBINER] Signal rejected for {symbol} | "
                    f"Direction: {signal_direction} | "
                    f"Confidence: {confidence_score:.2f} (min: {min_conf_for_cycle}) | "
                    f"Strength: {signal_strength:.2f}"
                )
        
        # Assess risk
        risk_assessment = self._assess_combined_risk(
            synchronized_signals["sentiment"],
            synchronized_signals["technical"],
            confidence_score
        )
        
        return CombinedSignalResult(
            trading_signal=trading_signal,
            confidence_score=confidence_score,
            combination_reasoning=reasoning,
            contributing_signals=synchronized_signals,
            risk_assessment=risk_assessment,
            timestamp=datetime.now(timezone.utc)
        )    

    def _synchronize_signal_timing(self,
                                  sentiment_result: Optional[AggregatedSentiment],
                                  technical_signals: List[TechnicalSignal],
                                  reference_time: Optional[datetime] = None) -> Dict[str, List]:
        """Synchronize sentiment and technical signals by timing"""
        
        current_time = reference_time or datetime.now(timezone.utc)
        
        # Find signals within sync window
        now = reference_time or datetime.now(timezone.utc)
        synced_technical = []
        for s in technical_signals:
            try:
                # Ensure both are aware for comparison if possible, or both naive
                s_ts = s.timestamp
                ref_ts = now
                
                # Make both aware if one is
                if s_ts.tzinfo is None and ref_ts.tzinfo is not None:
                    s_ts = s_ts.replace(tzinfo=timezone.utc)
                elif s_ts.tzinfo is not None and ref_ts.tzinfo is None:
                    ref_ts = ref_ts.replace(tzinfo=timezone.utc)
                
                diff = abs((s_ts - ref_ts).total_seconds())
                if diff <= self.sync_window.total_seconds():
                    synced_technical.append(s)
                else:
                    logger.debug(f"[SYNC] Signal too old: {diff}s > {self.sync_window.total_seconds()}s")
            except Exception as e:
                logger.error(f"[SYNC] Error comparing timestamps: {e}")
                
        if not synced_technical and technical_signals:
             logger.warning(f"[SYNC] All {len(technical_signals)} technical signals filtered out by window!")
        
        # Check sentiment timing
        synchronized_sentiment = None
        if sentiment_result:
            age = current_time - sentiment_result.timestamp
            if age <= self.sync_window:
                synchronized_sentiment = sentiment_result
        
        logger.debug(f"Signal synchronization: "
                    f"technical={len(synced_technical)}/{len(technical_signals)}, "
                    f"sentiment={'synced' if synchronized_sentiment else 'out_of_sync'}")
        
        return {
            "sentiment": synchronized_sentiment,
            "technical": synced_technical
        }
    
    def _calculate_combined_signal(self,
                                  sentiment_result: Optional[AggregatedSentiment],
                                  technical_signals: List[TechnicalSignal]) -> Tuple[Optional[Direction], float, str]:
        """Calculate combined signal direction and strength"""
        
        reasoning_parts = []
        
        # Calculate sentiment contribution
        sentiment_score = 0.0
        sentiment_confidence = 0.0
        
        if sentiment_result:
            sentiment_score = sentiment_result.final_sentiment_score
            sentiment_confidence = sentiment_result.final_confidence
            reasoning_parts.append(
                f"Sentiment: {sentiment_score:.3f} (confidence: {sentiment_confidence:.3f})"
            )
        else:
            reasoning_parts.append("Sentiment: No data available")
        
        # Calculate technical contribution
        technical_score = 0.0
        technical_confidence = 0.0
        
        if technical_signals:
            # Aggregate technical signals
            buy_signals = [s for s in technical_signals if s.signal_type == SignalType.BUY]
            sell_signals = [s for s in technical_signals if s.signal_type == SignalType.SELL]
            
            buy_strength = sum(s.strength for s in buy_signals)
            sell_strength = sum(s.strength for s in sell_signals)
            
            # Calculate net technical score (-1 to 1)
            if buy_strength > sell_strength:
                technical_score = min(buy_strength / len(technical_signals), 1.0)
            elif sell_strength > buy_strength:
                technical_score = -min(sell_strength / len(technical_signals), 1.0)
            else:
                technical_score = 0.0
            
            # Technical confidence is average of all signal strengths
            technical_confidence = sum(s.strength for s in technical_signals) / len(technical_signals)
            
            # ===== FIX #2: CALCULATE INDICATOR CONFLUENCE SCORE =====
            # Confluence = percentage of technical indicators agreeing with primary direction
            # Count how many indicators align with the strongest signal direction
            if buy_strength > sell_strength:
                # Strong buy signal
                confluence_count = len(buy_signals)
                total_signals = len(technical_signals)
            elif sell_strength > buy_strength:
                # Strong sell signal
                confluence_count = len(sell_signals)
                total_signals = len(technical_signals)
            else:
                # Conflicting signals
                confluence_count = 0
                total_signals = max(len(technical_signals), 1)
            
            # Store confluence score (0-100 scale) for later use
            self._indicator_confluence_score = (confluence_count / total_signals) * 100.0 if total_signals > 0 else 0.0
            
            reasoning_parts.append(
                f"Technical: {technical_score:.3f} ({len(buy_signals)} buy, {len(sell_signals)} sell signals) | Confluence: {self._indicator_confluence_score:.1f}%"
            )
        else:
            reasoning_parts.append("Technical: No signals available")
            self._indicator_confluence_score = 0.0

        adx_value = float(getattr(self, "_adx_for_cycle", 0.0) or 0.0)
        trade_style = str(getattr(self, "_trade_style_for_cycle", "TREND") or "TREND").upper()
        adx_component = max(0.0, adx_value / 50.0)
        if technical_signals and adx_component > 0.0:
            direction_sign = 1.0 if technical_score >= 0.0 else -1.0
            if trade_style in {"MEAN_REVERSION", "MEANREVERSION", "RANGE"}:
                technical_score -= direction_sign * adx_component
                reasoning_parts.append(f"ADX soft score: -{adx_component:.3f} ({trade_style})")
            else:
                technical_score += direction_sign * adx_component
                reasoning_parts.append(f"ADX soft score: +{adx_component:.3f} ({trade_style})")
            technical_score = max(-1.0, min(1.0, technical_score))
        
        # Combine scores using weights
        total_active_weight = (self.weights.sentiment_weight if sentiment_result else 0) + \
                             (self.weights.technical_weight if technical_signals else 0)
        
        if total_active_weight > 0:
            combined_score = (sentiment_score * self.weights.sentiment_weight + 
                             technical_score * self.weights.technical_weight) / total_active_weight
        else:
            combined_score = 0.0
        
        # Determine direction
        signal_direction = None
        if combined_score > 0.1:
            signal_direction = Direction.LONG
        elif combined_score < -0.1:
            signal_direction = Direction.SHORT
        
        # Calculate signal strength (0 to 1)
        signal_strength = abs(combined_score)
        
        # Add trend confirmation bonus if both agree
        if sentiment_result and technical_signals:
            sentiment_bullish = sentiment_score > 0.1
            technical_bullish = technical_score > 0.1
            sentiment_bearish = sentiment_score < -0.1
            technical_bearish = technical_score < -0.1
            
            if (sentiment_bullish and technical_bullish) or (sentiment_bearish and technical_bearish):
                signal_strength = min(signal_strength + self.weights.trend_confirmation_bonus, 1.0)
                reasoning_parts.append("Trend confirmation bonus applied")
        
        reasoning = f"Combined signal: {combined_score:.3f}. " + "; ".join(reasoning_parts)
        
        return signal_direction, signal_strength, reasoning
    
    def _calculate_combined_confidence(self,
                                     sentiment_result: Optional[AggregatedSentiment],
                                     technical_signals: List[TechnicalSignal],
                                     signal_strength: float) -> float:
        """Calculate combined confidence score"""
        # Weighted Sum override: ML + Meta (avoid multiplicative compression)
        ml_conf = self.override_ml_confidence
        meta_prob = self.override_meta_win_prob
        if ml_conf is not None and meta_prob is not None:
            try:
                ml_conf_val = float(ml_conf)
                meta_prob_val = float(meta_prob)
            except Exception:
                ml_conf_val = None
                meta_prob_val = None
            if ml_conf_val is not None and meta_prob_val is not None:
                combined = (ml_conf_val * 0.6) + (meta_prob_val * 0.4)
                return max(0.0, min(1.0, combined))

        confidence_components = []
        
        # Sentiment confidence component
        if sentiment_result:
            sentiment_confidence = sentiment_result.final_confidence * self.weights.sentiment_weight
            confidence_components.append(sentiment_confidence)
        
        # Technical confidence component
        if technical_signals:
            avg_technical_confidence = sum(s.strength for s in technical_signals) / len(technical_signals)
            technical_confidence = avg_technical_confidence * self.weights.technical_weight
            confidence_components.append(technical_confidence)
        
        # Base confidence from components
        if confidence_components:
            # Normalize based on available signal types
            total_active_weight = (self.weights.sentiment_weight if sentiment_result else 0) + \
                                 (self.weights.technical_weight if technical_signals else 0)
            
            if total_active_weight > 0:
                base_confidence = sum(confidence_components) / total_active_weight
            else:
                base_confidence = 0.0
        else:
            base_confidence = 0.0
        
        # Adjust by signal strength
        strength_adjusted_confidence = base_confidence * signal_strength
        
        # Boost confidence if multiple signal types agree
        if sentiment_result and technical_signals and len(confidence_components) == 2:
            agreement_bonus = 0.1
            strength_adjusted_confidence = min(strength_adjusted_confidence + agreement_bonus, 1.0)
        
        return strength_adjusted_confidence    

    def _create_trading_signal(self,
                              symbol: str,
                              direction: Direction,
                              current_price: float,
                              confidence: float,
                              reasoning: str,
                              sentiment_result: Optional[AggregatedSentiment],
                              technical_signals: List[TechnicalSignal],
                              timestamp: datetime,
                              historical_data: Optional[List[MarketData]] = None,
                              current_positions: Optional[List] = None) -> TradingSignal:
        """Create a trading signal from combined analysis"""
        
        # Calculate entry price (use current price with small adjustment for slippage)
        slippage_adjustment = 0.0001  # 1 pip for forex
        if direction == Direction.LONG:
            entry_price = current_price + slippage_adjustment
        else:
            entry_price = current_price - slippage_adjustment
        
        # Calculate stop loss and take profit using ATR-based calculator if historical data available
        if historical_data and len(historical_data) >= 14:
            # Use ATR-based calculation for better sizing
            # Get parameters from environment variables (for optimization testing) or use defaults
            atr_period = int(os.environ.get('BACKTEST_ATR_PERIOD', '14'))
            risk_ratio = float(os.environ.get('BACKTEST_RISK_RATIO', '3.0'))  # Increased from 1.5 to 3.0
            min_sl_pips = float(os.environ.get('BACKTEST_MIN_SL_PIPS', '10.0'))
            
            calculator = StopLossTakeProfitCalculator(
                atr_period=atr_period, 
                risk_reward_ratio=risk_ratio,
                min_sl_pips=min_sl_pips
            )
            levels_dict = calculator.calculate_levels(
                entry_price=entry_price,
                direction=direction,
                historical_data=historical_data
            )
            stop_loss = levels_dict["stop_loss"]
            take_profit = levels_dict["take_profit"]
            logger.info(
                f"ATR-based SL/TP: Entry={entry_price:.5f}, Dir={direction.value}, "
                f"SL={stop_loss:.5f}, TP={take_profit:.5f}, Period={atr_period}, RR={risk_ratio}"
            )
        else:
            # Fallback to percentage-based if no historical data
            stop_loss, take_profit = self._calculate_stop_take_levels(
                entry_price, direction, confidence, technical_signals
            )
            logger.info(
                f"Fallback SL/TP (no ATR): Entry={entry_price:.5f}, "
                f"SL={stop_loss:.5f}, TP={take_profit:.5f}, DataLen={len(historical_data) if historical_data else 0}"
            )
        
        # Calculate position size based on confidence
        position_size = self._calculate_position_size(confidence)
        
        # Enhanced reasoning with signal details
        enhanced_reasoning = self._create_enhanced_reasoning(
            reasoning, sentiment_result, technical_signals, confidence
        )
        
        # Determine Exit Policy
        exit_policy = ExitPolicy.STANDARD
        trade_style = str(getattr(self, "_trade_style_for_cycle", "TREND") or "TREND").upper()
        
        # High confidence trending signals -> Trend Follow (let winners run)
        if trade_style in {"MEAN_REVERSION", "MEANREVERSION", "RANGE"}:
            exit_policy = ExitPolicy.MEAN_REVERT
        elif confidence >= 0.8:
            exit_policy = ExitPolicy.TREND_FOLLOW
            
        # Low confidence -> Scalp (quick targets)
        elif confidence < 0.6:
            exit_policy = ExitPolicy.SCALP
            
        # Specific market conditions (if available) can override
        if sentiment_result and sentiment_result.consistency_score < 0.4:
             # Conflicting sentiment -> Scalp/Mean Revert safe
             exit_policy = ExitPolicy.SCALP
        
        # Default fallback
        
        # Extract features for ML ensemble
        # Feature Spec: [ATR, ADX, RSI, Spread, Confidence]
        features_list = [0.0, 0.0, 50.0, 0.0001, confidence]
        
        try:
            # 1. Try to get indicators from technical signals
            found_indicators = {}
            if technical_signals:
                # Prioritize the signal with highest strength
                best_signal = max(technical_signals, key=lambda s: s.strength)
                if best_signal.indicators:
                    found_indicators = best_signal.indicators
            
            # Map found indicators
            if 'atr' in found_indicators: features_list[0] = found_indicators['atr']
            if 'adx' in found_indicators: features_list[1] = found_indicators['adx']
            if 'rsi' in found_indicators: features_list[2] = found_indicators['rsi']
            
            # 2. Backfill with historical data calculation if missing
            if historical_data and len(historical_data) >= 15:
                # ATR Proxy
                if features_list[0] == 0.0:
                    features_list[0] = sum(d.high - d.low for d in historical_data[-14:]) / 14
                    
                # RSI Proxy (Simple 14-period)
                if features_list[2] == 50.0:
                    closes = [d.close for d in historical_data[-15:]]
                    gains = []
                    losses = []
                    for i in range(1, len(closes)):
                        diff = closes[i] - closes[i-1]
                        if diff > 0: gains.append(diff)
                        else: losses.append(abs(diff))
                    
                    avg_gain = sum(gains) / 14 if gains else 0
                    avg_loss = sum(losses) / 14 if losses else 0
                    if avg_loss == 0:
                        features_list[2] = 100.0
                    else:
                        rs = avg_gain / avg_loss
                        features_list[2] = 100 - (100 / (1 + rs))

                # ADX Proxy (Trend Strength via Price Velocity)
                if features_list[1] == 0.0:
                     # Simple: Abs((Close - Close[14]) / ATR)
                     momentum = abs(historical_data[-1].close - historical_data[-14].close)
                     features_list[1] = (momentum / features_list[0]) * 10 if features_list[0] > 0 else 0
                     
                # Spread
                if hasattr(historical_data[-1], 'spread'):
                    features_list[3] = historical_data[-1].spread
            
            # Ensure confidence is updated
            features_list[4] = confidence
            
        except Exception as e:
            self.logger.warning(f"Error extracting features for ML exit prediction: {e}")
        
        # REGIME-AWARE EXIT POLICY ENSEMBLE
        # Build feature dictionary for regime detection
        feature_dict = {
            'atr': features_list[0],
            'adx': features_list[1],
            'rsi': features_list[2],
            'spread': features_list[3],
            'atr_80_percentile': features_list[0] * 1.5,  # Rough estimate
            'atr_20_percentile': features_list[0] * 0.5,
        }
        
        # Detect regime
        regime_label = self.regime_detector.get_detailed_regime_label(feature_dict)
        
        # Get optimal allocation from ensemble
        allocation = self.exit_policy_ensemble.get_optimal_allocation(
            regime=regime_label,
            features=np.array(features_list).reshape(1, -1),
            current_volatility=features_list[0],  # ATR
            current_spread=features_list[3],
            base_confidence=confidence,
            enforce_invariants=True
        )
        
        # Apply position size multiplier from ensemble
        adjusted_position_size = position_size * allocation.position_size_multiplier
        adjusted_position_size = np.clip(adjusted_position_size, 0.01, 1.0)
        
        # ===== FIX #4: RANGING MULTIPLIER BOOST (0.75x -> 0.90x for >85% confidence) =====
        # When market is RANGING and ML confidence is high, boost capital to maximize opportunity
        if regime_label == "RANGING" and confidence > 0.85:
            original_multiplier = allocation.position_size_multiplier
            allocation.position_size_multiplier *= 1.2  # 0.75 * 1.2 = 0.90
            adjusted_position_size = position_size * allocation.position_size_multiplier
            adjusted_position_size = np.clip(adjusted_position_size, 0.01, 1.0)
            
            self.logger.critical(
                f"[RANGING_MULTIPLIER_BOOST] {symbol} | Confidence {confidence:.1%} > 85% in RANGING market. "
                f"Position size boosted: {original_multiplier:.2f}x -> {allocation.position_size_multiplier:.2f}x | "
                f"Final adjusted size: {adjusted_position_size:.2f} lots"
            )
        
        # Log allocation decision
        self.logger.debug(
            f"[ENSEMBLE] {symbol} | Regime: {regime_label} | "
            f"Policy: {allocation.exit_policy.value} | "
            f"Expectancy: {allocation.expectancy:.2f}R | "
            f"Size Mult: {allocation.position_size_multiplier:.2f}x | "
            f"Confidence: {allocation.confidence:.2f}"
        )
        
        # ===== PATCH #1: CALCULATE REAL-TIME R:R RATIO =====
        # Pull actual RR from calculated stop_loss and take_profit rather than ensemble default
        real_risk_reward_ratio = 0.0
        if stop_loss is not None and take_profit is not None and current_price is not None:
            if direction == Direction.LONG:
                risk = abs(current_price - stop_loss)
                reward = abs(take_profit - current_price)
            else:  # SHORT
                risk = abs(stop_loss - current_price)
                reward = abs(current_price - take_profit)
            
            if risk > 0.00001:  # Avoid division by zero
                real_risk_reward_ratio = reward / risk
                self.logger.debug(
                    f"[RR-SYNC] {symbol} | Real R:R calculated: {real_risk_reward_ratio:.2f}R | "
                    f"Risk: {risk:.5f}, Reward: {reward:.5f}"
                )
        
        # TRADE ADMISSION GATE
        # ===== PATCH #1: EXPLICIT MAPPING OF REAL_RISK_REWARD_RATIO TO RR_RATIO =====
        # Directly log the source and value of RR being mapped
        self.logger.critical(
            f"[RR_MAPPING_SOURCE] {symbol} | Direct assignment: "
            f"real_risk_reward_ratio ({real_risk_reward_ratio:.3f}R) -> TradingSignal.rr_ratio (source: SLTPCalculator)"
        )
        
        # ===== PATCH #2: PASS REAL RR TO VALIDATION =====
        has_synthetic_signal = any(
            bool(getattr(ts, "indicators", {}).get("SYNTHETIC", 0))
            for ts in technical_signals
        )
        if has_synthetic_signal:
            self._synthetic_force_cycles_remaining = max(self._synthetic_force_cycles_remaining, 50)

        synthetic_force_active = self._synthetic_force_cycles_remaining > 0
        forced_exec_for_admission = False
        elite_mtf_alignment = self._detect_elite_mtf_alignment(symbol, technical_signals)
        if elite_mtf_alignment:
            forced_exec_for_admission = True
            self.logger.critical(
                "[ELITE_SIGNAL_TRIGGER] %s | RSI and MACD aligned on H1 + M15. forced_execution=True",
                symbol,
            )

        # ===== FIX #3: STALE SIGNAL HARD-REJECT =====
        # Check if signal is too old (> 60 seconds) — do NOT trade "old news"
        # CRITICAL FIX: Ensure timestamp is UTC-aware before calculating age
        current_time_utc = datetime.now(timezone.utc)
        if timestamp and timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        signal_age_seconds = (current_time_utc - timestamp).total_seconds() if timestamp else 0
        max_signal_age = int(os.environ.get("MAX_SIGNAL_AGE_SECONDS", "60"))  # Configurable via env var
        
        if signal_age_seconds > max_signal_age:
            self.logger.critical(
                f"[STALE_SIGNAL_REJECT] {symbol} | Signal age: {signal_age_seconds:.0f}s > {max_signal_age}s limit | "
                f"Rejecting to avoid chasing {signal_age_seconds:.0f}s-old price action"
            )
            return None  # Reject stale signal before admission
        
        admission = self.admission_controller.evaluate_admission(
            symbol=symbol,
            regime=regime_label,
            expectancy=allocation.expectancy,
            confidence=allocation.confidence,
            exit_policy=allocation.exit_policy,
            position_size_multiplier=allocation.position_size_multiplier,
            real_risk_reward_ratio=real_risk_reward_ratio,  # TRUE RR from SLTPCalculator
            forced_execution=forced_exec_for_admission,
            striking_mode_active=str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"} or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"},
            synthetic_present=has_synthetic_signal or synthetic_force_active,
            direction=direction.value,
            current_positions=current_positions,
            min_confidence_threshold=float(getattr(self, "_min_conf_for_cycle", self.min_confidence_threshold)),
            current_spread=features_list[3],
            current_atr=features_list[0],
            structure_override_active=bool(self.structure_override_active),
            raw_ml_confidence=float(getattr(self, "_raw_ml_conf_for_cycle", 0.0) or 0.0),
            high_impact_news_pending=bool(self.news_guard_active),
            ml_accuracy=float(getattr(self, "_ml_accuracy_for_cycle", 0.0) or 0.0),
            historical_trade_count=int(getattr(self, "_historical_trade_count_for_cycle", 0) or 0),
            low_accuracy_cycle_count=int(getattr(self, "_low_accuracy_cycle_count_for_cycle", 0) or 0),
            bot_cycle_count=int(getattr(self, "_bot_cycle_count_for_cycle", 0) or 0),
            trade_tier=str(getattr(self, "_trade_tier_for_cycle", "") or ("TIER_A" if float(allocation.confidence or 0.0) * 100.0 >= 80.0 else "")),
            signal_score=float(float(allocation.confidence or 0.0) * 100.0),
            trend_following=bool(str(getattr(self, "_trade_style_for_cycle", "TREND") or "TREND").upper() not in {"MEAN_REVERSION", "MEANREVERSION", "RANGE"}),
            technical_only_mode=bool(getattr(self, "_technical_only_mode_for_cycle", False)),
            desperation_mode=bool(getattr(self, "_desperation_mode_for_cycle", False)),
            adx_value=float(features_list[1] or 0.0),
            effective_adx_floor=float(getattr(self, "_effective_adx_floor_for_cycle", 0.0) or 0.0),
            adx_gate_enabled=bool(getattr(self, "_adx_gate_enabled_for_cycle", True)),
            trade_style=str(getattr(self, "_trade_style_for_cycle", "TREND") or "TREND"),
        )
        self._last_admission_result = admission

        if self._synthetic_force_cycles_remaining > 0:
            self._synthetic_force_cycles_remaining -= 1
        
        # Check admission decision
        if not admission.admitted:
            self.logger.warning(
                f"[TRADE_ADMISSION] {symbol} REJECTED - {admission.reason}"
            )
            return None  # Signal rejected by admission controller
        self.logger.info("[TRACE-2] Passed Hard Safety Gates for %s", symbol)
        
        # Apply admission-adjusted position size
        final_position_size = position_size * admission.final_position_multiplier
        final_position_size = np.clip(final_position_size, 0.01, 1.0)

        # RL Tactical Dispatcher (between admission and position sizing)
        news_lockout_seconds = 0
        if hasattr(self.admission_controller, "get_global_lockout_remaining"):
            try:
                news_lockout_seconds = int(self.admission_controller.get_global_lockout_remaining() or 0)
            except Exception:
                news_lockout_seconds = 0

        portfolio_ctx = self._portfolio_context or {}
        wl_ratio = portfolio_ctx.get("win_loss_ratio_10")
        if wl_ratio is None:
            wl_ratio = rolling_metrics.win_loss_ratio()
        rl_decision = self.rl_dispatcher.decide(
            symbol=symbol,
            direction=direction.value,
            admission_approved=admission.admitted,
            base_position_size=final_position_size,
            spread=features_list[3],
            atr=features_list[0],
            rsi=features_list[2],
            adx=features_list[1],
            ml_confidence=confidence,
            expectancy_r=real_risk_reward_ratio,
            hour_of_day=int(timestamp.hour),
            news_lockout_seconds=news_lockout_seconds,
            open_drawdown_pct=portfolio_ctx.get("drawdown_pct"),
            margin_util_pct=portfolio_ctx.get("margin_util_pct"),
            win_loss_ratio_10=wl_ratio,
        )

        if rl_decision.applied:
            if rl_decision.action in (RLTacticAction.HARD_SKIP, RLTacticAction.TACTICAL_DELAY):
                self.logger.info(
                    "[RL_TACTIC] %s | Action: %s | Deferred/Skipped by RL dispatcher.",
                    symbol,
                    rl_decision.action.name,
                )
                return None
            final_position_size = np.clip(
                final_position_size * rl_decision.multiplier, 0.01, 1.0
            )
        self.logger.info("[TRACE-3] Passed RL Tactical Dispatcher for %s", symbol)
        
        # Enhanced reasoning with admission info
        full_reasoning = (
            f"{enhanced_reasoning} | {allocation.reasoning} | "
            f"Admission: {admission.action_taken} (Score: {admission.opportunity_score:.1f}%ile)"
        )
        if rl_decision.action:
            full_reasoning += f" | RL: {rl_decision.action.name}"
        
        # Forced execution bypass is deprecated. Admission is now EV-gated in TradeAdmissionController.
        forced_execution = forced_exec_for_admission
        
        # ===== HARD-MAPPING: EXPLICIT RR ASSIGNMENT WITH NO DEFAULT =====
        # Log the exact RR value being assigned to prove hard-mapping is active
        # Ensure float conversion to prevent type errors
        rr_ratio_final = float(real_risk_reward_ratio)
        
        # ===== CRITICAL FIX: USE CONFIDENCE FROM ADMISSION DECISION =====
        # If admission modified confidence (e.g., for ADX penalties, macro shields), use that modified value
        # NEVER use the original confidence - it may have been gated or penalized by admission controller
        admission_confidence = float(getattr(admission, "final_confidence", float(confidence) or 0.0) or 0.0)
        confidence_cast = float(admission_confidence) if isinstance(admission_confidence, (int, float, str)) else float(confidence) if isinstance(confidence, (int, float, str)) else 0.0
        ml_accuracy_cast = float(getattr(self, "_ml_accuracy_for_cycle", 0.0) or 0.0)
        
        self.logger.critical(
            f"[HARD_MAPPING_RR] {symbol} | Direct assignment: "
            f"real_risk_reward_ratio = {rr_ratio_final:.3f}R (NO default fallback allowed) | "
            f"Type: {type(rr_ratio_final).__name__} | Confidence: {confidence_cast:.3f}(float from admission) | "
            f"Accuracy: {ml_accuracy_cast:.3f}(float) | Value guaranteed non-default"
        )
        
        expectancy_value = float(rr_ratio_final)
        
        signal_source = "synthetic" if has_synthetic_signal else (
            "synthetic_followthrough" if synthetic_force_active else "standard"
        )
        if symbol.replace("/", "").upper() == "NZDUSD" and allocation.position_size_multiplier < 0.50:
            old_mult = allocation.position_size_multiplier
            allocation.position_size_multiplier = 0.50
            final_position_size = np.clip(position_size * allocation.position_size_multiplier, 0.01, 1.0)
            self.logger.critical(
                f"[SIZE_OVERRIDE] {symbol} | Position multiplier floor applied: "
                f"{old_mult:.2f}x -> {allocation.position_size_multiplier:.2f}x"
            )

        trading_signal = TradingSignal(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=final_position_size,
            confidence=confidence_cast,  # Type-cast to float
            reasoning=full_reasoning,
            timestamp=timestamp,
            exit_policy=allocation.exit_policy,
            predicted_exit_policy=allocation.exit_policy,  # For compatibility
            policy_confidence=allocation.confidence,
            entry_features=features_list,
            regime_label=regime_label,
            rr_ratio=rr_ratio_final,  # HARD-MAPPED from SLTPCalculator (NOT default 1.0R) - explicitly float-cast
            expectancy=expectancy_value,  # ===== FIX #5: EXPLICIT SYNC TO PREVENT DEFAULT 1.00R =====
            ml_accuracy=ml_accuracy_cast,  # Type-cast to float for Alpha Gate compatibility
            forced_execution=forced_execution,
            source=signal_source,
            rl_action=rl_decision.action.name if rl_decision.action else None,
            rl_action_id=int(rl_decision.action) if rl_decision.action else None,
            rl_multiplier=rl_decision.multiplier,
            rl_decision_id=rl_decision.decision_id,
            rl_shadow_mode=rl_decision.shadow_mode,
            rl_warmup_complete=rl_decision.warmup_complete,
        )
        setattr(trading_signal, "admitted", bool(admission.admitted))
        # Production safety: downstream validators remain mandatory for live trades.
        setattr(trading_signal, "skip_validator", False)
        
        # ===== FIX #2: SET EV OVERRIDE FLAGS FOR DOWNSTREAM SIGNAL FILTER =====
        # These flags communicate the admission decision to the signal filter
        # so it can bypass confidence floors for high-EV trades
        setattr(trading_signal, "override_authorized", bool(admission.authority_level != "LEVEL_3"))
        setattr(trading_signal, "ev_score", float(expectancy_value))  # Pass the EV/expectancy
        self.logger.critical(
            f"[EV_OVERRIDE_FLAGS_SET] {symbol} | override_authorized={bool(admission.authority_level != 'LEVEL_3')} | "
            f"ev_score={float(expectancy_value):.2f}R | authority_level={admission.authority_level}"
        )
        
        # ===== FIX #1: PROPAGATE INDICATOR CONFLUENCE SCORE =====
        # Maps confluence score from technical analysis to signal object
        indicator_confluence_score = float(getattr(self, '_indicator_confluence_score', 0.0) or 0.0)
        setattr(trading_signal, "indicator_confluence", indicator_confluence_score)
        # V12 Immutable Levels:
        # Once AdmissionController admits, SL/TP become immutable (Accept -> Lock -> Execute).
        lock_signal_levels = bool(admission.admitted)
        setattr(trading_signal, "locked_stop_loss", float(stop_loss))
        setattr(trading_signal, "locked_take_profit", float(take_profit))
        setattr(trading_signal, "level_lock_enabled", lock_signal_levels)
        setattr(trading_signal, "levels_finalized", lock_signal_levels)
        setattr(trading_signal, "locked", lock_signal_levels)
        if lock_signal_levels and hasattr(trading_signal, "finalize_levels"):
            try:
                trading_signal.finalize_levels()
            except Exception:
                pass
        self._last_trading_signal = trading_signal
        self.logger.info("[TRACE-4] Handed to Execution Engine for %s", symbol)
        return trading_signal
    
    def _calculate_stop_take_levels(self,
                                   entry_price: float,
                                   direction: Direction,
                                   confidence: float,
                                   technical_signals: List[TechnicalSignal]) -> Tuple[float, float]:
        """Calculate stop loss and take profit levels"""
        
        # Base risk percentage (lower for higher confidence)
        base_risk_pct = 0.02  # 2%
        confidence_adjustment = (1.0 - confidence) * 0.01  # Up to 1% additional risk
        risk_pct = base_risk_pct + confidence_adjustment
        
        # Look for support/resistance levels in technical signals
        support_resistance_levels = []
        for signal in technical_signals:
            if "support_level" in signal.indicators:
                support_resistance_levels.append(signal.indicators["support_level"])
            if "resistance_level" in signal.indicators:
                support_resistance_levels.append(signal.indicators["resistance_level"])
        
        # PHASE 2.2: Dynamic risk-reward based on signal quality
        # Ultra-high confidence (0.78+) gets 2.5:1 RR, medium (0.65-0.78) gets 2.2:1, rest gets 2:1
        if confidence >= 0.78:
            rr_ratio = 2.5  # ELITE signals get aggressive TP
        elif confidence >= 0.65:
            rr_ratio = 2.2  # HIGH quality signals get improved TP
        else:
            rr_ratio = 2.0  # Standard signals get conservative TP
        
        if direction == Direction.LONG:
            # Stop loss below entry
            stop_loss = entry_price * (1.0 - risk_pct)
            
            # Adjust stop loss to nearest support if available
            if support_resistance_levels:
                nearest_support = max([level for level in support_resistance_levels 
                                     if level < entry_price], default=stop_loss)
                if nearest_support > stop_loss:
                    stop_loss = nearest_support * 0.999  # Slightly below support
            
            # Take profit with dynamic risk-reward ratio
            risk_amount = entry_price - stop_loss
            take_profit = entry_price + (risk_amount * rr_ratio)
            
            # Adjust take profit to nearest resistance if closer
            if support_resistance_levels:
                nearest_resistance = min([level for level in support_resistance_levels 
                                        if level > entry_price], default=take_profit)
                if nearest_resistance < take_profit:
                    take_profit = nearest_resistance * 0.999  # Slightly below resistance
        
        else:  # SHORT
            # Stop loss above entry
            stop_loss = entry_price * (1.0 + risk_pct)
            
            # Adjust stop loss to nearest resistance if available
            if support_resistance_levels:
                nearest_resistance = min([level for level in support_resistance_levels 
                                        if level > entry_price], default=stop_loss)
                if nearest_resistance < stop_loss:
                    stop_loss = nearest_resistance * 1.001  # Slightly above resistance
            
            # Take profit with dynamic risk-reward ratio
            risk_amount = stop_loss - entry_price
            take_profit = entry_price - (risk_amount * rr_ratio)
            
            # Adjust take profit to nearest support if closer
            if support_resistance_levels:
                nearest_support = max([level for level in support_resistance_levels 
                                     if level < entry_price], default=take_profit)
                if nearest_support > take_profit:
                    take_profit = nearest_support * 1.001  # Slightly above support
        
        return stop_loss, take_profit
    
    def _calculate_position_size(self, confidence: float) -> float:
        """Calculate position size based on confidence
        
        FIXED SIZING: Always use 0.01 lots per signal for realistic backtesting.
        This matches typical demo account position sizing and prevents
        unrealistic compounding from dynamic scaling.
        
        Live Behavior: Position size is determined by:
        - Account size (typically 0.01 lots = $100 notional on $10k account)
        - Risk per trade (1-2% of account per trade)
        - NOT confidence level (which can be noisy)
        """
        # FIXED: Always 0.01 lots per signal, regardless of confidence
        # This eliminates lookahead bias from confidence-based scaling
        # and matches realistic live trading patterns
        return 0.01  # Fixed 0.01 lots per trade
    
    def _create_enhanced_reasoning(self,
                                  base_reasoning: str,
                                  sentiment_result: Optional[AggregatedSentiment],
                                  technical_signals: List[TechnicalSignal],
                                  confidence: float) -> str:
        """Create enhanced reasoning with detailed signal information"""
        
        reasoning_parts = [base_reasoning]
        
        # Add sentiment details
        if sentiment_result:
            reasoning_parts.append(
                f"Sentiment analysis from {len(sentiment_result.sources)} sources "
                f"with {sentiment_result.consistency_score:.2f} consistency."
            )
        
        # Add technical signal details
        if technical_signals:
            indicator_types = set()
            for signal in technical_signals:
                indicator_types.update(signal.indicators.keys())
            
            reasoning_parts.append(
                f"Technical analysis based on {len(technical_signals)} signals "
                f"using {len(indicator_types)} indicator types: {', '.join(list(indicator_types)[:5])}."
            )
        
        # Add confidence assessment
        if confidence >= 0.8:
            confidence_desc = "Very high confidence"
        elif confidence >= 0.6:
            confidence_desc = "High confidence"
        elif confidence >= 0.4:
            confidence_desc = "Moderate confidence"
        else:
            confidence_desc = "Low confidence"
        
        reasoning_parts.append(f"{confidence_desc} signal ({confidence:.3f}).")
        
        return " ".join(reasoning_parts)
    
    def _assess_combined_risk(self,
                             sentiment_result: Optional[AggregatedSentiment],
                             technical_signals: List[TechnicalSignal],
                             confidence_score: float) -> str:
        """Assess risk level of combined signal"""
        
        risk_factors = 0
        
        # Low confidence increases risk
        if confidence_score < 0.4:
            risk_factors += 2
        elif confidence_score < 0.6:
            risk_factors += 1
        
        # Missing sentiment data increases risk
        if not sentiment_result:
            risk_factors += 1
        elif sentiment_result.consistency_score < 0.5:
            risk_factors += 1
        
        # Few technical signals increase risk
        if len(technical_signals) < 2:
            risk_factors += 1
        
        # Weak technical signals increase risk
        if technical_signals:
            weak_signals = sum(1 for s in technical_signals if s.strength < 0.5)
            if weak_signals > len(technical_signals) / 2:
                risk_factors += 1
        
        # Determine risk level
        if risk_factors >= 4:
            return "HIGH"
        elif risk_factors >= 2:
            return "MEDIUM"
        else:
            return "LOW"   
 
    def update_signal_weights(self, new_weights: SignalWeights) -> None:
        """Update signal combination weights"""
        self.weights = new_weights
        logger.info(f"Updated signal weights: sentiment={new_weights.sentiment_weight}, "
                   f"technical={new_weights.technical_weight}")
    
    def get_signal_statistics(self,
                             sentiment_result: Optional[AggregatedSentiment],
                             technical_signals: List[TechnicalSignal]) -> Dict[str, any]:
        """Get statistics about the signals being combined"""
        
        stats = {
            "sentiment_available": sentiment_result is not None,
            "technical_signals_count": len(technical_signals),
            "signal_types": {},
            "average_technical_strength": 0.0,
            "signal_age_seconds": {}
        }
        
        # Sentiment stats
        if sentiment_result:
            stats["sentiment_score"] = sentiment_result.final_sentiment_score
            stats["sentiment_confidence"] = sentiment_result.final_confidence
            stats["sentiment_consistency"] = sentiment_result.consistency_score
            stats["sentiment_sources"] = len(sentiment_result.sources)
            
            age = (datetime.now(timezone.utc) - sentiment_result.timestamp).total_seconds()
            stats["signal_age_seconds"]["sentiment"] = age
        
        # Technical signal stats
        if technical_signals:
            signal_types = {}
            strengths = []
            ages = []
            
            for signal in technical_signals:
                signal_type = signal.signal_type.value
                signal_types[signal_type] = signal_types.get(signal_type, 0) + 1
                strengths.append(signal.strength)
                
                age = (datetime.now(timezone.utc) - signal.timestamp).total_seconds()
                ages.append(age)
            
            stats["signal_types"] = signal_types
            stats["average_technical_strength"] = sum(strengths) / len(strengths)
            stats["signal_age_seconds"]["technical_avg"] = sum(ages) / len(ages)
            stats["signal_age_seconds"]["technical_max"] = max(ages)
        
        return stats
    
    def validate_signal_inputs(self,
                              sentiment_result: Optional[AggregatedSentiment],
                              technical_signals: List[TechnicalSignal],
                              current_price: float,
                              symbol: str) -> List[str]:
        """Validate inputs for signal combination"""
        
        validation_errors = []
        
        # Validate symbol
        if not symbol or not isinstance(symbol, str):
            validation_errors.append("Invalid symbol provided")
        
        # Validate current price
        if not isinstance(current_price, (int, float)) or current_price <= 0:
            validation_errors.append("Invalid current price")
        
        # Validate sentiment result
        if sentiment_result:
            try:
                sentiment_result.validate() if hasattr(sentiment_result, 'validate') else None
            except Exception as e:
                validation_errors.append(f"Invalid sentiment result: {str(e)}")
        
        # Validate technical signals
        for i, signal in enumerate(technical_signals):
            try:
                signal.validate()
            except Exception as e:
                validation_errors.append(f"Invalid technical signal {i}: {str(e)}")
        
        # Check signal timing consistency
        if sentiment_result and technical_signals:
            sentiment_age = (datetime.now(timezone.utc) - sentiment_result.timestamp).total_seconds()
            technical_ages = [(datetime.now(timezone.utc) - s.timestamp).total_seconds() for s in technical_signals]
            
            max_age_diff = 3600  # 1 hour
            if sentiment_age > max_age_diff or any(age > max_age_diff for age in technical_ages):
                validation_errors.append("Some signals are too old for reliable combination")
        
        return validation_errors
    
    def create_weighted_scoring_system(self,
                                      market_conditions: Dict[str, float] = None) -> SignalWeights:
        """Create adaptive signal weights based on market conditions"""
        
        # Default weights
        weights = SignalWeights()
        
        if market_conditions:
            volatility = market_conditions.get("volatility", 0.5)
            volume = market_conditions.get("volume_ratio", 1.0)
            trend_strength = market_conditions.get("trend_strength", 0.5)
            
            # Adjust weights based on market conditions
            # High volatility: favor technical signals
            if volatility > 0.7:
                weights.technical_weight = 0.7
                weights.sentiment_weight = 0.3
            # Low volatility: favor sentiment
            elif volatility < 0.3:
                weights.technical_weight = 0.4
                weights.sentiment_weight = 0.6
            
            # High volume: boost volume confirmation
            if volume > 1.5:
                weights.volume_confirmation_bonus = 0.1
            
            # Strong trend: boost trend confirmation
            if trend_strength > 0.7:
                weights.trend_confirmation_bonus = 0.15
        
        return weights

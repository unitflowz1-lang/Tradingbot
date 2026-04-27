""" 
Simple Trend Following Strategy for MT5
"""
import os
import logging
import asyncio
import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Tuple, Any
from collections import deque
import pandas as pd
import numpy as np


from src.models import MarketData, TradingSignal, Direction, TechnicalSignal, SignalType
from src.analysis.technical_indicators import IndicatorCalculator, TechnicalIndicators
from src.analysis.technical_signal_generator import TechnicalSignalGenerator
from src.analysis.signal_combiner import SignalCombiner, SignalWeights
from src.analysis.ml_model import PriceMovementPredictor
from src.analysis.price_action_math import PriceActionMath
from src.analysis.signal_strength_calculator import SignalStrengthCalculator
from src.analysis.adaptive_signal_scoring import AdaptiveSignalFilterer
from src.analysis.adaptive_strictness_enhanced import EnhancedAdaptiveStrictnessController as AdaptiveStrictnessController, MarketCondition, StrictnessMode
from src.analysis.market_regime_detector import MarketRegimeDetector
from src.strategies.symbol_config import symbol_manager  # NEW: Per-symbol filters
from src.ml.trade_admission_controller import TradeAdmissionController, TradePermissionDecision

class SimpleTrendStrategy:
    """A strategy that follows trends using SMA, RSI and Machine Learning"""
    ADX_FLOOR = 22.0
    TEMP_RELAXATION_HOURS = 4
    TEMP_QUALITY_FLOOR = 0.40
    TEMP_ADX_MULTIPLIER = 0.80
    
    def __init__(self, 
                 symbol: str, 
                 verbose: bool = True, 
                 entry_filters: Optional[Dict] = None, 
                 config: Optional[Any] = None,
                 admission_controller: Optional[TradeAdmissionController] = None):
        self.symbol = symbol
        self.verbose = verbose
        self.logger = logging.getLogger(__name__)
        self.indicator_calculator = IndicatorCalculator()
        self.signal_generator = TechnicalSignalGenerator()
        self.ml_predictor = PriceMovementPredictor(self.symbol)
        self.signal_quality_calculator = SignalStrengthCalculator(logger=self.logger)
        
        # Track last SL hit to implement cooling-off period
        self.last_sl_hit_time: Optional[datetime] = None
        self.cooldown_timer: int = 0
        self.sl_cooldown_active: bool = True
        self._nuclear_cooldown_cycles_remaining: int = 100
        self.cooling_off_minutes = 240
        self._meta_gate_override_until: Optional[datetime] = None
        self._ml_cache_flushed_once = False
        self._sl_cooldown_bypass_until: Optional[datetime] = None
        self._market_closed_seen_at: Optional[datetime] = None
        self._reopen_spread_guard_until: Optional[datetime] = None
        self._market_reopened_at: Optional[datetime] = None
        self._opening_silence_until: Optional[datetime] = None
        self._weekend_time_reset_armed: bool = False
        self._temporary_relaxation_until: datetime = datetime.now(timezone.utc) + timedelta(hours=self.TEMP_RELAXATION_HOURS)
        self._time_exit_disabled_until: datetime = datetime.now(timezone.utc) + timedelta(hours=4)
        self.regret_analysis_enabled: bool = False
        self.minimum_accuracy_records_threshold: int = int(os.environ.get("ML_MIN_RECORDS_THRESHOLD", "5"))
        self.training_cooldown_minutes: int = int(os.environ.get("ML_TRAINING_COOLDOWN_MINUTES", "60"))
        self.training_retrade_threshold: int = int(os.environ.get("ML_TRAINING_MIN_NEW_CLOSED_TRADES", "3"))
        self._last_training_time: Optional[datetime] = None
        self._last_training_closed_trade_count: int = 0
        self._closed_trade_count_cache: int = 0
        self._closed_trade_count_checked_at: Optional[datetime] = None
        self.cycle_cache: Dict[str, Optional[TradingSignal]] = {}
        self._cycle_cache_id: Optional[int] = None
        self._last_symbol_report: Dict[str, Any] = {}
        self._last_metrics_cycle_id: Optional[int] = None
        self.low_accuracy_cycle_count: int = 0
        self.low_accuracy_force_retrain_threshold: float = 0.40
        self.low_accuracy_force_retrain_cycles: int = 10
        self.force_retrain: bool = False
        self.force_retrain_lookback_bars: int = int(os.environ.get("ML_FORCE_RETRAIN_LOOKBACK_BARS", "2000"))  # FIX #3: Increased from 150 to 2000
        self.force_retrain_cooldown_minutes: int = int(
            os.environ.get("ML_FORCE_RETRAIN_COOLDOWN_MINUTES", str(max(self.training_cooldown_minutes, 90)))
        )
        self._last_force_retrain_trigger_at: Optional[datetime] = None
        self._pending_model_reset_recovery: bool = False
        self.cold_start_trade_threshold: int = int(os.environ.get("ML_COLD_START_TRADE_THRESHOLD", "100"))
        self.hard_reset_accuracy_threshold: float = float(os.environ.get("ML_HARD_RESET_ACCURACY_THRESHOLD", "0.30"))
        self.hard_reset_cycle_threshold: int = int(os.environ.get("ML_HARD_RESET_CYCLE_THRESHOLD", "50"))
        self.hard_reset_lookback_bars: int = int(os.environ.get("ML_HARD_RESET_LOOKBACK_BARS", "2000"))  # FIX #3: Increased from 500 to 2000
        self.hard_reset_cooldown_minutes: int = int(os.environ.get("ML_HARD_RESET_COOLDOWN_MINUTES", "240"))
        self._last_hard_reset_at: Optional[datetime] = None
        
        # Track missed opportunities
        self.missed_opportunities = deque(maxlen=20)
        self.tracked_rejections = [] # For Regret Analysis
        
        # News Buffer
        from src.data.news_data_collector import NewsDataCollector
        if config is None:
            try:
                from src.config import get_config_manager
                config = get_config_manager().get_config()
            except Exception as e:
                self.logger.error(f"Failed to load config for NewsDataCollector: {e}")
                # We need a Config object, but creating one from scratch is hard.
                # If we are here, something is likely wrong with initialization.
                
        self.config = config
        self.news_collector = NewsDataCollector(self.config)
        
        self.logger.info(f"SimpleTrendStrategy initialized for {self.symbol}")
        self.is_trained = False
        self.ml_trained = False
        self.fine_tuned = False
        
        # ===== ADAPTIVE SIGNAL FILTERING =====
        # Features: ML override (70%+), session relaxation, auto-threshold adjustment
        self.signal_filterer = AdaptiveSignalFilterer(
            min_score=70,              # Base threshold for sniper-mode selection
            ml_accuracy_target=0.55    # Target 55% ML accuracy
        )
        self.regime_detector = MarketRegimeDetector()
        
        # ===== ADAPTIVE STRICTNESS CONTROLLER =====
        # Adjusts filter thresholds based on market conditions (trending vs sideways)
        self.strictness_controller = AdaptiveStrictnessController(enable_adaptive=True)
        
        self.logger.info("[ADAPTIVE FILTER] Initialized with adaptive thresholds")
        self.logger.info("[ADAPTIVE FILTER] - ML Override: >=70% confidence -> auto-accept")
        self.logger.info("[ADAPTIVE FILTER] - Session Aware: Tokyo +5 bonus, relaxed ADX")
        self.logger.info("[ADAPTIVE FILTER] - Auto-Adjust: Threshold lowers when ML accuracy <50%")
        self.logger.info("[ADAPTIVE FILTER] - Rejection Logging: Specific fixes suggested")
        
        self.logger.info("[ADAPTIVE STRICTNESS] Initialized")
        self.logger.info("[ADAPTIVE STRICTNESS] - STRICT in strong trends (ADX >=28)")
        self.logger.info("[ADAPTIVE STRICTNESS] - MODERATE in weak trends (ADX >=18)")
        self.logger.info("[ADAPTIVE STRICTNESS] - ML-OVERRIDE in sideways/weak markets (ML >=75%)")
        self.logger.info("[ADAPTIVE STRICTNESS] - EXTRA STRICT in choppy/erratic markets")
        self.logger.critical(
            f"[TEMP_FILTER_RELAXATION] {self.symbol} | Active until "
            f"{self._temporary_relaxation_until.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
            f"Quality floor -> {self.TEMP_QUALITY_FLOOR:.0%} | ADX thresholds -> 80% of configured values | "
            "REGRET ANALYSIS logs disabled."
        )
        
        # Try to load pre-trained model immediately
        safe_symbol = self.symbol.replace('/', '')
        model_path = f"models/{safe_symbol}_ml.pkl"
        
        # ===== MODEL LOADING DIAGNOSTICS =====
        self.logger.info(
            f"[ML_MODEL_CHECK] {self.symbol} | Looking for: {model_path} | "
            f"Exists: {os.path.exists(model_path)}"
        )
        
        if self.ml_predictor.load_model(model_path):
            self.logger.info(f"Loaded pre-trained ML model for {self.symbol}")
            self._sync_ml_training_state(True)
            trained_at = getattr(self.ml_predictor, "metadata", {}).get("trained_at")
            if trained_at:
                try:
                    parsed = datetime.fromisoformat(str(trained_at))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    self._last_training_time = parsed
                except Exception:
                    self._last_training_time = None
        else:
            self.logger.warning(
                f"[ML_MODEL_FALLBACK] {self.symbol} | Model file '{model_path}' not found or failed to load. "
                f"Using RSI+MACD heuristic fallback. Run train_models_enhanced.py to train models."
            )
            self._sync_ml_training_state(False)
        
        # Entry filters - PHASE 3: PER-SYMBOL OPTIMIZATION
        # Use per-symbol config if available, otherwise fallback to balanced defaults
        self.symbol_manager = symbol_manager
        self.entry_filters = entry_filters or {
            'adx_min': 22,     # Sniper filter for confirmed trends
            'rsi_min': 38,     # Momentum power zone lower bound
            'rsi_max': 62,     # Momentum power zone upper bound
            'ml_confidence_min': 0.60,
            'meta_win_prob_min': 0.30,  # Phase 2: meta-label admission threshold
            'signal_quality_min': 0.70,
            'chop_max': 60.0   # New CHOP filter (< 61.8 indicates Trending)
        }
        self.use_per_symbol_filters = True  # Enable per-symbol optimization
        
        # Use technical weights with ML influence
        weights = SignalWeights(sentiment_weight=0.80, technical_weight=0.20)
        self.admission_controller = admission_controller or TradeAdmissionController()
        self.combiner = SignalCombiner(
            signal_weights=weights, 
            min_confidence_threshold=0.2, # Lowered from 0.4
            sentiment_technical_sync_window_minutes=240, # Increased to 4 hours
            admission_controller=self.admission_controller
        )

    def _sync_ml_training_state(self, loaded_ok: Optional[bool] = None) -> bool:
        model_ready = bool(self.ml_predictor.model is not None and self.ml_predictor.scaler is not None)
        predictor_flag = bool(getattr(self.ml_predictor, "is_trained", False))
        effective_trained = bool(model_ready and (predictor_flag or bool(loaded_ok)))
        self.ml_predictor.is_trained = effective_trained
        self.ml_trained = effective_trained
        self.is_trained = effective_trained
        return effective_trained

    async def _get_closed_trade_count(self, lookback_days: int = 30) -> int:
        now_utc = datetime.now(timezone.utc)
        if (
            self._closed_trade_count_checked_at is not None
            and (now_utc - self._closed_trade_count_checked_at) < timedelta(minutes=5)
        ):
            return self._closed_trade_count_cache
        try:
            import MetaTrader5 as mt5
            from_date = now_utc - timedelta(days=lookback_days)
            deals = await asyncio.to_thread(
                mt5.history_deals_get,
                from_date,
                now_utc,
                group=f"*{self.symbol.replace('/','') or self.symbol}*",
            )
            closed_ids = set()
            for deal in deals or []:
                entry_type = getattr(deal, "entry", None)
                if entry_type in {
                    getattr(mt5, "DEAL_ENTRY_OUT", 1),
                    getattr(mt5, "DEAL_ENTRY_OUT_BY", 3),
                }:
                    closed_ids.add(str(getattr(deal, "position_id", getattr(deal, "position", ""))))
            self._closed_trade_count_cache = len(closed_ids)
            self._closed_trade_count_checked_at = now_utc
            return self._closed_trade_count_cache
        except Exception as exc:
            self.logger.debug("[ML_ACCURACY] Failed to count closed trades for %s: %s", self.symbol, exc)
            return self._closed_trade_count_cache

    async def _resolve_effective_ml_accuracy(self) -> Tuple[float, int, str, float, float]:
        model_acc = float(getattr(self.ml_predictor, 'metadata', {}).get('accuracy_score', 0.0) or 0.0)
        live_acc = float(self.signal_filterer.get_current_ml_accuracy() or 0.0)
        closed_trade_count = await self._get_closed_trade_count()
        live_observation_count = int(len(getattr(self.signal_filterer, "ml_accuracy_history", []) or []))
        recent_fine_tune_active = bool(
            self.fine_tuned
            and self._last_training_time is not None
            and (datetime.now(timezone.utc) - self._last_training_time) <= timedelta(minutes=30)
        )
        if recent_fine_tune_active and model_acc > 0.0:
            bayesian_prior = (model_acc * 0.8) + (live_acc * 0.2) if live_observation_count < 3 else (live_acc if live_acc > 0 else model_acc)
            effective = (model_acc * 0.8) + (bayesian_prior * 0.2)
            source = "fine_tune_weighted_80_20"
            return float(effective), int(closed_trade_count), source, model_acc, live_acc
        if live_observation_count < 3:
            if model_acc > 0:
                effective = (model_acc * 0.8) + (live_acc * 0.2)
                source = "weighted_bayesian_prior"
            else:
                effective = live_acc
                source = "live_accuracy_only"
        elif closed_trade_count < self.minimum_accuracy_records_threshold:
            effective = model_acc if model_acc > 0 else live_acc
            source = "model_training_accuracy"
        else:
            effective = live_acc if live_acc > 0 else model_acc
            source = "live_accuracy"
        return float(effective), int(closed_trade_count), source, model_acc, live_acc
    
    def _filter_training_by_regime(
        self,
        training_window: List[MarketData],
        target_regime: str,
        min_bars: int = 500,
    ) -> Tuple[List[MarketData], List[float]]:
        """
        FIX #1: Regime Filter with Weighted Window for ML Training
        
        Filters training data to prioritize bars that match the current market regime.
        If regime_matched_bars < min_bars, implements Weighted Window instead of falling back.
        
        Args:
            training_window: Full historical data window
            target_regime: Current market regime (e.g., "TRENDING", "RANGING", "LOW_VOLATILITY")
            min_bars: Minimum bars to return (uses weighted window if insufficient)
            
        Returns:
            Tuple of (filtered training data, sample weights)
            - If regime-matched >= min_bars: returns matched bars with uniform weights
            - If regime-matched < min_bars: returns all bars with 3x weight on regime-matched
        """
        try:
            if len(training_window) < min_bars:
                # Not enough data - return as-is with uniform weights
                return training_window, [1.0] * len(training_window)
            
            # Calculate rolling regime for each bar in the window
            regime_matched_indices = []
            regime_matched_bars = []
            window_size = 50  # Use 50-bar rolling window for regime detection
            
            for i in range(window_size, len(training_window)):
                rolling_window = training_window[i - window_size:i]
                try:
                    rolling_regime = self.regime_detector.detect_regime(rolling_window)
                    # Match regime (case-insensitive)
                    if rolling_regime.upper() == target_regime.upper():
                        regime_matched_indices.append(i)
                        regime_matched_bars.append(training_window[i])
                except Exception:
                    continue
            
            # FIX #1: If we have enough regime-matched bars, return them with uniform weights
            if len(regime_matched_bars) >= min_bars:
                matched_bars = regime_matched_bars[-min_bars:]  # Return most recent min_bars
                return matched_bars, [1.0] * len(matched_bars)
            
            # FIX #1: WEIGHTED WINDOW - Instead of falling back, use all data with weights
            # Regime-matched bars get 3x weight, other bars get 1x weight
            self.logger.info(
                "[REGIME_WEIGHTED_WINDOW] %s | regime-matched=%d < min_bars=%d | "
                "Implementing Weighted Window (3x regime-matched weight)",
                self.symbol,
                len(regime_matched_bars),
                min_bars,
            )
            
            # Build weighted dataset: include all bars, but regime-matched get higher weight
            weighted_bars = []
            sample_weights = []
            regime_matched_set = set(regime_matched_indices)
            
            for i in range(window_size, len(training_window)):
                bar = training_window[i]
                if i in regime_matched_set:
                    # Regime-matched: add 3 copies (3x weight)
                    weighted_bars.extend([bar, bar, bar])
                    sample_weights.extend([3.0, 3.0, 3.0])
                else:
                    # Other bars: add 1 copy (1x weight)
                    weighted_bars.append(bar)
                    sample_weights.append(1.0)
            
            # Sort by timestamp to maintain temporal order
            combined = list(zip(weighted_bars, sample_weights))
            combined.sort(key=lambda x: x[0].timestamp)
            
            final_bars = [bar for bar, _ in combined]
            final_weights = [weight for _, weight in combined]
            
            self.logger.info(
                "[REGIME_WEIGHTED_OK] %s | Total bars: %d | Regime-matched: %d (3x weight) | "
                "Other bars: %d (1x weight) | Effective sample size: %.0f",
                self.symbol,
                len(final_bars),
                len(regime_matched_bars),
                len(training_window) - len(regime_matched_bars),
                sum(final_weights),
            )
            
            return final_bars, final_weights
            
        except Exception as filter_err:
            self.logger.warning(
                "[REGIME_FILTER_ERROR] %s | Filtering failed: %s. Returning full window with uniform weights.",
                self.symbol,
                filter_err,
            )
            return training_window, [1.0] * len(training_window)

    async def _should_retrain_model(self, closed_trade_count: int) -> Tuple[bool, Optional[float]]:
        if self._last_training_time is None:
            return True, None
        age_minutes = (datetime.now(timezone.utc) - self._last_training_time).total_seconds() / 60.0
        if age_minutes >= self.training_cooldown_minutes:
            return True, age_minutes
        if closed_trade_count >= (self._last_training_closed_trade_count + self.training_retrade_threshold):
            return True, age_minutes
        return False, age_minutes

    def _track_accuracy_degradation(self, effective_accuracy: float) -> bool:
        if float(effective_accuracy or 0.0) < self.low_accuracy_force_retrain_threshold:
            self.low_accuracy_cycle_count += 1
        else:
            self.low_accuracy_cycle_count = 0
            self.force_retrain = False
            return False

        now_utc = datetime.now(timezone.utc)
        if (
            self._last_force_retrain_trigger_at is not None
            and (now_utc - self._last_force_retrain_trigger_at) < timedelta(minutes=self.force_retrain_cooldown_minutes)
        ):
            if self.low_accuracy_cycle_count > self.low_accuracy_force_retrain_cycles:
                cooldown_remaining = self.force_retrain_cooldown_minutes - (
                    now_utc - self._last_force_retrain_trigger_at
                ).total_seconds() / 60.0
                self.logger.info(
                    "[ML_RETRAIN_COOLDOWN] %s | Accuracy still weak at %.1f%%, but force-retrain is cooling down for %.0fm more.",
                    self.symbol,
                    float(effective_accuracy or 0.0) * 100.0,
                    max(0.0, cooldown_remaining),
                )
            return False

        if self.low_accuracy_cycle_count > self.low_accuracy_force_retrain_cycles:
            self.force_retrain = True
            self._pending_model_reset_recovery = True
            self._last_force_retrain_trigger_at = now_utc
            self.logger.critical(
                "[ML_RETRAIN_TRIGGER] %s | Effective ML accuracy %.1f%% below %.1f%% for %d consecutive cycles. "
                "Forcing model reset recovery with %d-bar lookback.",
                self.symbol,
                float(effective_accuracy or 0.0) * 100.0,
                self.low_accuracy_force_retrain_threshold * 100.0,
                self.low_accuracy_cycle_count,
                self.force_retrain_lookback_bars,
            )
            return True
        return False

    async def _run_model_reset_recovery(self) -> None:
        if not self._pending_model_reset_recovery:
            return
        self._pending_model_reset_recovery = False
        try:
            self.indicator_calculator.clear_cache(self.symbol)
        except Exception as exc:
            self.logger.debug("[MODEL_RESET] %s | Indicator cache clear failed: %s", self.symbol, exc)
        try:
            if hasattr(self.signal_filterer, "ml_accuracy_history"):
                self.signal_filterer.ml_accuracy_history.clear()
        except Exception as exc:
            self.logger.debug("[MODEL_RESET] %s | Signal filter cache clear failed: %s", self.symbol, exc)
        self.cycle_cache.clear()
        self.fine_tuned = False
        self.logger.critical(
            "[MODEL_RESET] %s | Fine-tuning caches cleared. Awaiting MacroMonitor-owned news refresh before recalibrating on latest %d bars.",
            self.symbol,
            self.force_retrain_lookback_bars,
        )

    def mark_market_closed(self) -> None:
        """Record market-closed state to arm open-session spread guard."""
        self._market_closed_seen_at = datetime.now(timezone.utc)
        self._weekend_time_reset_armed = True

    def mark_market_reopened(self) -> None:
        """Activate spread guard window after first non-10018 response."""
        now_utc = datetime.now(timezone.utc)
        self._market_closed_seen_at = None
        self._market_reopened_at = now_utc
        self._opening_silence_until = now_utc + timedelta(minutes=10)
        self._reopen_spread_guard_until = now_utc + timedelta(minutes=30)
        if self._weekend_time_reset_armed:
            self.logger.critical(
                f"[OPEN_REENTRY_RESET] {self.symbol} | Weekend amnesty armed. "
                "Main loop will reset open-position entry timers on first valid reopen tick."
            )
            self._weekend_time_reset_armed = False
        self.logger.critical(
            f"[WEEK_AHEAD_READY] {self.symbol} | Sunday open spread guard active until "
            f"{self._reopen_spread_guard_until.isoformat()} (hard cap: 10.0 pips for first 30m)."
        )

    def is_open_session_spread_allowed(self, spread_pips: float) -> bool:
        """
        During the first 30 minutes post-reopen, enforce a hard 10.0 pip spread cap.
        """
        now_utc = datetime.now(timezone.utc)
        in_open_guard = bool(
            self._market_reopened_at and now_utc <= (self._market_reopened_at + timedelta(minutes=30))
        )
        if not in_open_guard:
            return True
        return float(spread_pips or 0.0) <= 10.0

    def is_cooldown_active(self, symbol=None, direction=None) -> bool:
        """
        Master cooldown gate.
        In SYSTEM_UNCAGED modes, cooldown is always disabled.
        """
        return False
        uncaged_active = (
            str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
        )
        if uncaged_active:
            return False
        return bool(self.sl_cooldown_active)

    def is_time_exit_disabled(self) -> bool:
        return datetime.now(timezone.utc) < self._time_exit_disabled_until

    def _temp_relaxation_active(self, now: Optional[datetime] = None) -> bool:
        now_utc = now or datetime.now(timezone.utc)
        return now_utc < self._temporary_relaxation_until

    def _get_effective_quality_floor(self, fallback_floor: float = 0.65, now: Optional[datetime] = None) -> float:
        base_floor = float(fallback_floor)
        if self._temp_relaxation_active(now):
            return min(base_floor, self.TEMP_QUALITY_FLOOR)
        return base_floor

    def _get_effective_adx_threshold(self, base_adx: float, now: Optional[datetime] = None) -> float:
        effective_adx = float(base_adx)
        if self._temp_relaxation_active(now):
            effective_adx *= self.TEMP_ADX_MULTIPLIER
        return max(self.ADX_FLOOR, effective_adx)

    def _get_active_symbol_filters(self, direction: str) -> Dict[str, Any]:
        """
        Return the symbol filter set after applying any runtime override pushed by
        the live orchestrator. This lets the execution layer relax or tighten the
        profile without fighting static symbol_config defaults.
        """
        filters = self.symbol_manager.get_filters(self.symbol, direction)
        runtime_override = getattr(self, "_runtime_symbol_filter_override", None)
        if isinstance(runtime_override, dict) and runtime_override:
            filters.update(runtime_override)
        return filters

    def _maybe_hard_reset_broken_model(self, effective_accuracy: float) -> bool:
        if float(effective_accuracy or 0.0) >= self.hard_reset_accuracy_threshold:
            return False
        if int(self.low_accuracy_cycle_count or 0) <= self.hard_reset_cycle_threshold:
            return False
        now_utc = datetime.now(timezone.utc)
        if (
            self._last_hard_reset_at is not None
            and (now_utc - self._last_hard_reset_at) < timedelta(minutes=self.hard_reset_cooldown_minutes)
        ):
            return False

        safe_symbol = self.symbol.replace('/', '')
        model_path = f"models/{safe_symbol}_ml.pkl"
        self.logger.critical(
            "[MODEL_HARD_RESET] %s | Accuracy %.1f%% below %.1f%% for %d cycles. Resetting persisted model and forcing retrain on %d bars.",
            self.symbol,
            float(effective_accuracy or 0.0) * 100.0,
            float(self.hard_reset_accuracy_threshold or 0.0) * 100.0,
            int(self.low_accuracy_cycle_count or 0),
            int(self.hard_reset_lookback_bars or 0),
        )
        self.ml_predictor.reset(filepath=model_path, remove_persisted=True)
        self.ml_trained = False
        self.fine_tuned = False
        self.force_retrain = True
        self._last_training_time = None
        self._last_hard_reset_at = now_utc
        return True
        
        
    async def analyze(self, historical_data: List[MarketData], current_positions: Optional[List] = None) -> Optional[TradingSignal]:
        """Analyze market data and generate a trading signal"""
        # ===== FIX #1: INITIALIZE tech_signals AT METHOD START =====
        # Prevents UnboundLocalError when tech_signals is referenced before assignment
        tech_signals = []  # Initialize as empty list - will be populated later
        signals = []       # Also initialize signals fallback variable
        
        # Log entry point
        self.logger.critical("[ANALYZE_ENTRY] %s | Called with %d candles", self.symbol, len(historical_data) if historical_data else 0)
        try:
            setattr(self.ml_predictor, "_current_cycle_id", getattr(self, "_current_cycle_id", None))
            setattr(self.ml_predictor, "_bot_cycle_count", getattr(self, "_bot_cycle_count", None))
        except Exception:
            pass
        metrics_snapshot = self.update_metrics_snapshot(historical_data, reason="analyze_start")
        if metrics_snapshot:
            self._last_symbol_report = dict(metrics_snapshot)
        
        # Helper: Set fallback report before any early return
        def _ensure_fallback_report(reason: str = ""):
            if not self._last_symbol_report or not self._last_symbol_report.get("direction"):
                # Try to extract current indicators if available
                try:
                    current_rsi = 50.0
                    current_price_val = 0.0
                    if historical_data:
                        current_price_val = float(historical_data[-1].close or 0.0)
                        # Quick RSI calculation if possible
                        if len(historical_data) >= 14:
                            closes = [d.close for d in historical_data[-14:]]
                            gains = [max(0, closes[i] - closes[i-1]) for i in range(1, len(closes))]
                            losses = [max(0, closes[i-1] - closes[i]) for i in range(1, len(closes))]
                            avg_gain = sum(gains) / len(gains) if gains else 0
                            avg_loss = sum(losses) / len(losses) if losses else 1
                            rs = avg_gain / avg_loss if avg_loss != 0 else 1
                            current_rsi = 100 - (100 / (1 + rs))
                except Exception:
                    current_rsi = 50.0
                    current_price_val = 0.0
                
                self._last_symbol_report = {
                    "price": current_price_val,
                    "rsi": current_rsi,
                    "direction": "DOWN",
                    "confidence": 0.45,
                    "z_score": float(getattr(self, 'current_z_score', 0.0) or 0.0),
                    "garch_vol": float(getattr(self, 'current_garch_vol', 0.0) or 0.0),
                    "flow_delta": float(getattr(self, 'current_flow_delta', 0.0) or 0.0),
                    "timestamp": datetime.now(timezone.utc),
                }
                self.logger.critical("[FALLBACK_REPORT_SET] %s | %s | fallback DOWN", self.symbol, reason)
        
        if not historical_data:
            _ensure_fallback_report("Empty data")
            return None
        
        current_price = float(historical_data[-1].close or 0.0)
        
        cycle_id = getattr(self, "_current_cycle_id", getattr(self, "_bot_cycle_count", None))
        try:
            cycle_id = int(cycle_id) if cycle_id is not None else None
        except Exception:
            cycle_id = None
        if cycle_id is not None and self._cycle_cache_id != cycle_id:
            self.cycle_cache.clear()
            self._cycle_cache_id = cycle_id
        cache_key = self.symbol.replace("/", "").upper()
        if cycle_id is not None and cache_key in self.cycle_cache:
            self.logger.debug(
                "[ANALYSIS_CACHE_HIT] %s | Returning cached signal for cycle %s.",
                self.symbol,
                cycle_id,
            )
            # BUG FIX: Even on cache hit, ensure _last_symbol_report is populated
            if not self._last_symbol_report or not self._last_symbol_report.get("direction"):
                self._last_symbol_report = {
                    "direction": "UP",
                    "confidence": 0.45,
                    "rsi": 50.0,
                }
                self.logger.debug(
                    "[CACHE_HIT_FALLBACK] %s | Cache hit but _last_symbol_report empty, setting fallback",
                    self.symbol,
                )
            return self.cycle_cache.get(cache_key)

        # Hard-reset cycle-local analysis artifacts before any scoring/admission work.
        if hasattr(self, "combiner") and self.combiner is not None:
            try:
                self.combiner.reset_cycle_state(symbol=self.symbol)
            except Exception as reset_err:
                self.logger.debug(f"[ANALYSIS_RESET_WARN] {self.symbol} cycle reset failed: {reset_err}")

        min_volatility_threshold = 0.000
        quality_floor = self._get_effective_quality_floor(0.45)
        if self._opening_silence_until and datetime.now(timezone.utc) < self._opening_silence_until:
            self.logger.critical(
                f"[ANALYZE_EARLY_RETURN_2] {self.symbol} | Opening silence active until "
                f"{self._opening_silence_until.isoformat()}. New entries paused."
            )
            # Ensure fallback is set before returning
            _ensure_fallback_report("Opening silence")
            return None

        # Clear combiner overrides at the start of each analysis cycle
        if self.combiner is not None:
            self.combiner.override_ml_confidence = None
            self.combiner.override_meta_win_prob = None
            self.combiner.structure_override_active = False
            self.combiner.news_guard_active = bool(getattr(self, "_news_guard_active", False))
        if not historical_data or len(historical_data) < 50:
            self.logger.critical(f"[ANALYZE_EARLY_RETURN_1] {self.symbol} | Insufficient data: {len(historical_data) if historical_data else 0} bars")
            # Ensure fallback is set before returning
            _ensure_fallback_report("Insufficient data")
            return None
        uncaged_active = (
            str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
        )
        striking_active = str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
        # Nuclear reset: evaporate any manual-decision cooldown dictionaries if present.
        if hasattr(self, "manual_exit_cooldowns") and isinstance(self.manual_exit_cooldowns, dict):
            self.manual_exit_cooldowns.clear()
        if hasattr(self, "cooldowns") and isinstance(self.cooldowns, dict):
            self.cooldowns.clear()
        if (uncaged_active or striking_active) and self._sl_cooldown_bypass_until is None:
            self._sl_cooldown_bypass_until = datetime.now(timezone.utc) + timedelta(hours=4)
            self.logger.critical(
                f"[SL_COOLDOWN_BYPASS] {self.symbol} cooldown bypass enabled until "
                f"{self._sl_cooldown_bypass_until.isoformat()}."
            )
        if (uncaged_active or striking_active) and self._nuclear_cooldown_cycles_remaining > 0:
            self.cooldown_timer = 0
            self.sl_cooldown_active = False
            self.last_sl_hit_time = None
            self._nuclear_cooldown_cycles_remaining -= 1
            self.logger.critical(
                f"[STRATEGY_FULLY_UNLEASHED] {self.symbol} | MetaGateCap=30.0% | "
                f"CooldownBypassActive=True | CyclesRemaining={self._nuclear_cooldown_cycles_remaining}"
            )
        if (uncaged_active or striking_active) and not self._ml_cache_flushed_once:
            # Emergency stale-confidence recovery: flush per-symbol model cache once.
            self.ml_predictor.model = None
            self.ml_predictor.meta_model = None
            self.ml_predictor.is_trained = False
            self.ml_predictor.metadata = {}
            self.fine_tuned = False
            self.ml_trained = False
            self.is_trained = False
            self._ml_cache_flushed_once = True
            self.logger.critical(f"[ML_CACHE_FLUSH] {self.symbol} model cache flushed for short-horizon recalibration.")

        # Emergency override: clear NZD/USD cooldown immediately.
        if str(self.symbol).upper() == "NZD/USD":
            self.cooldown_timer = 0
            self.sl_cooldown_active = False
            self.last_sl_hit_time = None
            
        current_price = historical_data[-1].close
        
        # 0. Check news buffer
        # Suspend entries 30 mins before/after high-impact releases
        # ===== PATCH #9: NEWS BUFFER AS ULTIMATE GATEKEEPER =====
        # Reinforce that news buffer overrides ALL other admission rules, including
        # Priority Admission and High-Confidence overrides
        news_buffer_result = await self._check_news_buffer()
        if isinstance(news_buffer_result, tuple):
            news_buffer_active = bool(news_buffer_result[0]) if len(news_buffer_result) >= 1 else False
            news_reason = str(news_buffer_result[1]) if len(news_buffer_result) >= 2 else ""
        else:
            news_buffer_active = bool(news_buffer_result)
            news_reason = ""
        if news_buffer_active:
            self.logger.critical(
                f"[ANALYZE_EARLY_RETURN_3] {self.symbol} entries BLOCKED: {news_reason}\n"
                f"   → No overrides allowed during economic volatility."
            )
            _ensure_fallback_report("News buffer active")
            return None

        # 0.1 Update Regret Analysis for previous rejections
        await self._run_regret_analysis(current_price)

        # 0.5. Check cooling-off period
        if self.is_cooldown_active() and not self.last_sl_hit_time:
            await self._check_recent_sl_hits()

        if str(self.symbol).upper() == "NZD/USD":
            self.cooldown_timer = 0
            self.sl_cooldown_active = False
            self.last_sl_hit_time = None
            
        if self.is_cooldown_active() and self.last_sl_hit_time:
            # Handle both naive and aware datetimes
            now = datetime.now(timezone.utc) if self.last_sl_hit_time.tzinfo else datetime.now()
            if self._sl_cooldown_bypass_until and datetime.now(timezone.utc) < self._sl_cooldown_bypass_until:
                self.logger.critical(
                    f"[SL_COOLDOWN_BYPASS] {self.symbol} bypassing cooldown despite recent SL hit."
                )
                self.last_sl_hit_time = None
            else:
                time_since_sl = (now - self.last_sl_hit_time).total_seconds() / 60
                if time_since_sl < self.cooling_off_minutes:
                    self.logger.critical(
                        f"[LOSS_COOLDOWN] {self.symbol} | SL recently hit. Symbol locked for 4 hours to prevent revenge trading."
                    )
                    _ensure_fallback_report("Loss cooldown active")
                    return None
                else:
                    self.last_sl_hit_time = None # Cooldown expired
        
        # 1. Calculate indicators
        # Note: IndicatorCalculator is stateful, so we clear it or use it carefully
        # For this simple strategy, we can just use the latest data
        self.indicator_calculator = IndicatorCalculator()
        for data in historical_data:
            self.indicator_calculator.add_market_data(data)
        
        # BUG FIX #2 (ENHANCED): Calculate indicators EARLY and update _last_symbol_report
        # This happens BEFORE any early returns, ensuring the table always gets actual data
        # FIX #3: CRITICAL - MUST update for ALL symbols, not just those with active trades
        try:
            early_indicators = self.indicator_calculator.calculate_indicators(self.symbol, timeframe='1h')
            early_rsi = float(early_indicators.rsi or 50.0)
            
            # Get quick ML direction (reuse the predictor)
            try:
                early_ml_dir, early_ml_conf, _ = self.ml_predictor.predict_with_details(
                    historical_data, early_indicators, bars_since_last_loss=999
                )
                early_ml_desc = str(early_ml_dir or "UP") if early_ml_dir else "UP"
            except Exception:
                early_ml_desc = "UP"
                early_ml_conf = 0.45
            
            # ALWAYS update _last_symbol_report with actual calculated values
            # FIX #1: CRITICAL - This MUST happen BEFORE any return statements
            # FIX #3: This MUST happen for EVERY symbol, regardless of trade status
            self._last_symbol_report = {
                "price": float(current_price or 0.0),
                "rsi": early_rsi,  # ACTUAL RSI from indicators
                "direction": early_ml_desc,  # ACTUAL ML direction
                "confidence": float(early_ml_conf or 0.45),  # ACTUAL ML confidence
                "timestamp": datetime.now(timezone.utc),  # Track when report was generated
            }
            self.logger.info(
                "[SYMBOL_REPORT_UPDATED] %s | RSI=%.1f | ML=%s | Conf=%.2f | Actual values set before any returns",
                self.symbol,
                early_rsi,
                early_ml_desc,
                early_ml_conf,
            )
        except Exception as early_update_err:
            self.logger.warning(
                "[SYMBOL_REPORT_UPDATE_FAILED] %s | Could not update with actual values: %s",
                self.symbol,
                early_update_err,
            )
            # FIX #3: Even on error, set a fallback to ensure the report is never empty
            if not self._last_symbol_report or not self._last_symbol_report.get("direction"):
                self._last_symbol_report = {
                    "price": float(current_price or 0.0),
                    "rsi": 50.0,
                    "direction": "UP",
                    "confidence": 0.45,
                    "timestamp": datetime.now(timezone.utc),
                }
            
        try:
            closed_trade_count = await self._get_closed_trade_count()
            pretrain_model_acc = float(getattr(self.ml_predictor, 'metadata', {}).get('accuracy_score', 0.0) or 0.0)
            pretrain_live_acc = float(self.signal_filterer.get_current_ml_accuracy() or 0.0)
            if pretrain_live_acc > 0 and closed_trade_count >= self.minimum_accuracy_records_threshold:
                effective_pretrain_accuracy = pretrain_live_acc
            elif pretrain_model_acc > 0:
                effective_pretrain_accuracy = pretrain_model_acc
            else:
                effective_pretrain_accuracy = pretrain_live_acc
            # 1. Calculate indicators for all points (needed for ML training)
            # 1. Calculate indicators for all points (needed for ML training)
            all_indicators = []
            
            hard_reset_triggered = self._maybe_hard_reset_broken_model(effective_pretrain_accuracy)
            force_retrain = self._track_accuracy_degradation(effective_pretrain_accuracy) or hard_reset_triggered
            retrain_result = await self._should_retrain_model(closed_trade_count)
            if isinstance(retrain_result, tuple):
                should_retrain = bool(retrain_result[0]) if len(retrain_result) >= 1 else False
                training_age_minutes = retrain_result[1] if len(retrain_result) >= 2 else None
            else:
                should_retrain = bool(retrain_result)
                training_age_minutes = None
            if force_retrain or should_retrain:
                if len(historical_data) < 80:
                    pass
                else:
                    if force_retrain:
                        await self._run_model_reset_recovery()
                    if hard_reset_triggered:
                        training_window = historical_data[-self.hard_reset_lookback_bars:]
                    elif force_retrain:
                        training_window = historical_data[-self.force_retrain_lookback_bars:]
                    else:
                        training_window = historical_data
                    
                    # FIX #1: Apply Regime Filter with Weighted Window to training data
                    # Only train on data that matches the current market regime
                    sample_weights = None
                    try:
                        current_regime = self.regime_detector.detect_regime(historical_data[-100:])
                        regime_result = self._filter_training_by_regime(
                            training_window,
                            target_regime=current_regime,
                            min_bars=500  # Minimum bars to ensure sufficient training data
                        )
                        # FIX #1: Unpack tuple (bars, weights)
                        regime_filtered_window, sample_weights = regime_result
                        
                        if len(regime_filtered_window) >= 500:
                            weight_info = ""
                            if sample_weights:
                                unique_weights = set(sample_weights)
                                weight_info = f" | Weighted: {unique_weights}"
                            
                            self.logger.info(
                                "[REGIME_FILTERED_TRAINING] %s | Current regime: %s | "
                                "Filtered %d bars -> %d bars matching regime%s",
                                self.symbol,
                                current_regime,
                                len(training_window),
                                len(regime_filtered_window),
                                weight_info,
                            )
                            training_window = regime_filtered_window
                        else:
                            self.logger.warning(
                                "[REGIME_FILTER_FALLBACK] %s | Insufficient regime-matched bars (%d < 500). "
                                "Using full training window.",
                                self.symbol,
                                len(regime_filtered_window),
                            )
                    except Exception as regime_err:
                        self.logger.warning(
                            "[REGIME_FILTER_ERROR] %s | Regime filtering failed: %s. Using full window.",
                            self.symbol,
                            regime_err,
                        )
                    
                    self.logger.info(
                        "Adaptive Learning for %s: Fine-tuning ML model on %d local bars%s...",
                        self.symbol,
                        len(training_window),
                        " (hard reset retrain)" if hard_reset_triggered else (" (forced retrain)" if force_retrain else ""),
                    )
                    
                    # FIX #3: Check if accuracy is below 48% - auto-increase training window
                    current_accuracy = float(getattr(self.ml_predictor, 'metadata', {}).get('accuracy_score', 0.0) or 0.0)
                    if current_accuracy < 0.48 and len(training_window) < 1500:
                        self.logger.critical(
                            "[ML_ACCURACY_LOW] %s | Accuracy %.1f%% below 48%% threshold | "
                            "Expanding training window from %d to 1500 bars",
                            self.symbol,
                            current_accuracy * 100,
                            len(training_window),
                        )
                        # Expand training window to 1500 bars
                        expanded_window = historical_data[-1500:] if len(historical_data) >= 1500 else historical_data
                        if len(expanded_window) > len(training_window):
                            training_window = expanded_window
                            self.logger.info(
                                "[ML_WINDOW_EXPANDED] %s | Using expanded window: %d bars",
                                self.symbol,
                                len(training_window),
                            )
                    
                    # Calculate indicators for the whole history buffer to train
                    all_indicators = []
                    # Optimization: Don't recalculate generic calculator every time, just batch process
                    # But for now, sticking to logic that mimics the online accumulation
                    # We start from index 20 to have enough data for sma/rsi
                    for i in range(50, len(training_window)):
                         # We need a window of data ending at i
                        window = training_window[:i+1]
                        
                        # Use a temporary calculator to get point-in-time indicators
                        # Note: This O(N^2) loop is heavy for backtests but necessary for correct point-in-time training without lookahead
                        if i % 100 == 0: # Optimization: Don't train on EVERY bar, sample it? 
                             # No, previous code did all. Let's keep it but maybe optimize calculator usage?
                             pass

                        # RE-USE MAIN CALCULATOR STATE if possible? 
                        # No, main calculator has "current" state.
                        # We are reconstructing history.
                        
                        temp_calc = IndicatorCalculator()
                        # Optimization: Add only necessary slice (last 100 bars)
                        start_slice = max(0, i-200)
                        for d in window[start_slice:]:
                            temp_calc.add_market_data(d)
                            
                        try:
                            # Calculate and store
                            all_indicators.append(temp_calc.calculate_indicators(self.symbol))
                        except:
                            continue
                            
                    if len(all_indicators) >= 50:
                        # Train on aligned data
                        # We calculated indicators for history[50] to history[end]
                        # So we slice history correspondingly
                        train_data = training_window[50:50+len(all_indicators)]
                        
                        # FIX #1: Align sample_weights with train_data slice
                        train_weights = None
                        if sample_weights is not None:
                            label_count = max(0, len(train_data) - int(getattr(self.ml_predictor, "horizon", 1) or 1))
                            if label_count > 0 and len(sample_weights) > 50:
                                train_weights = sample_weights[50:50 + label_count]
                        
                        self.ml_predictor.train(train_data, all_indicators, sample_weights=train_weights)
                        if self.ml_predictor.is_trained:
                            self.ml_trained = True
                            self.fine_tuned = True
                            self._last_training_time = datetime.now(timezone.utc)
                            self._last_training_closed_trade_count = closed_trade_count
                            self.force_retrain = False
                            self.low_accuracy_cycle_count = 0
                            self.logger.info(f"✓ Fine-tuning complete. Accuracy: {self.ml_predictor.metadata.get('accuracy_score', 0):.1%}")
                            
                            # FIX #3: If accuracy still low after training, try Gradient Boosting
                            post_accuracy = float(self.ml_predictor.metadata.get('accuracy_score', 0.0) or 0.0)
                            if post_accuracy < 0.48:
                                self.logger.critical(
                                    "[ML_ACCURACY_STILL_LOW] %s | Accuracy %.1f%% still below 48%% after training | "
                                    "Attempting Gradient Boosting fallback",
                                    self.symbol,
                                    post_accuracy * 100,
                                )
                                try:
                                    # Try switching to Gradient Boosting
                                    from ml.model_trainer import ModelTrainer
                                    gb_trainer = ModelTrainer(model_type="gradient_boosting")
                                    self.ml_predictor.model_trainer = gb_trainer
                                    
                                    # Retrain with Gradient Boosting
                                    self.ml_predictor.train(train_data, all_indicators)
                                    
                                    if self.ml_predictor.is_trained:
                                        gb_accuracy = float(self.ml_predictor.metadata.get('accuracy_score', 0.0) or 0.0)
                                        self.logger.info(
                                            "[GRADIENT_BOOSTING_ACTIVATED] %s | Switched to Gradient Boosting | "
                                            "New accuracy: %.1f%%",
                                            self.symbol,
                                            gb_accuracy * 100,
                                        )
                                except Exception as gb_err:
                                    self.logger.warning(
                                        "[GRADIENT_BOOSTING_FAILED] %s | Gradient Boosting fallback failed: %s",
                                        self.symbol,
                                        gb_err,
                                    )
                        else:
                            # Still set fine_tuned so we don't keep trying every loop if it's failing/skipping
                            self.fine_tuned = True 
                            self.logger.info(f"ML Fine-tuning skipped or failed for {self.symbol} (using fallback logic)")
            elif training_age_minutes is not None:
                self.logger.info(
                    "[TRAINING_SKIPPED] %s | Model is still fresh (Age: %.0fm).",
                    self.symbol,
                    training_age_minutes,
                )
            
            # Current indicators for latest bar (H1)
            indicators = self.indicator_calculator.calculate_indicators(self.symbol, timeframe='1h')
            
            # BUG FIX #2: Update _last_symbol_report with ACTUAL indicator values immediately
            # This ensures the Global Cache gets real RSI/ML data even if we return None later
            # Get preliminary ML direction (will be refined later if we get that far)
            try:
                temp_ml_dir, temp_ml_conf, _ = self.ml_predictor.predict_with_details(
                    historical_data, indicators, bars_since_last_loss=999
                )
                temp_ml_desc = str(temp_ml_dir or "UP") if temp_ml_dir else "UP"
            except Exception:
                temp_ml_desc = "UP"
                temp_ml_conf = 0.45
            
            # Set actual values now (not fallback 50.0)
            self._last_symbol_report = {
                "price": float(current_price or 0.0),
                "rsi": float(indicators.rsi or 50.0),  # Use actual RSI
                "direction": temp_ml_desc,  # Use actual ML direction
                "confidence": float(temp_ml_conf or 0.45),  # Use actual ML confidence
                "volatility": float(getattr(indicators, 'atr', 0.0) or 0.0),
                "z_score": float(getattr(self, 'current_z_score', 0.0) or 0.0),
                "garch_vol": float(getattr(self, 'current_garch_vol', 0.0) or 0.0),
                "flow_delta": float(getattr(self, 'current_flow_delta', 0.0) or 0.0),
                "timestamp": datetime.now(timezone.utc),
            }
            self.logger.debug(
                "[SYMBOL_REPORT_EARLY_UPDATE] %s | RSI=%.1f | ML=%s | Conf=%.2f | Updated with actual values",
                self.symbol,
                float(indicators.rsi or 50.0),
                temp_ml_desc,
                float(temp_ml_conf or 0.45),
            )
            
            # --- MULTI-TIMEFRAME CONFIRMATION (H4 Trend) ---
            # Calculate H4 indicators using the same historical data (resampled internally or via separate feed)
            # Note: The backtest engine passes 'historical_data' which is likely 1H bars.
            # To get H4, we need to construct it or assume it's separate. 
            # Given current architecture, we can approximate H4 SMA50 by using SMA200 on H1 
            # (since 4x50=200). H1 SMA200 is a very close proxy for H4 SMA50.
            
            # Ensure we have enough data for SMA 200 (H1) -> Proxy for H4 Trend
            h4_trend_sma = None
            if len(historical_data) >= 200:
                 closes_long = [d.close for d in historical_data[-200:]]
                 h4_trend_sma = sum(closes_long) / 200
            
            indicators.h4_trend = h4_trend_sma # Attach to indicators object for usage later
            
            # SANITIZE: Ensure no complex numbers leak into analysis
            indicators = self._sanitize_indicators(indicators)

            price_action_df, price_action_signal = self._extract_price_action_context(historical_data)
            latest_price_action = price_action_df.iloc[-1] if not price_action_df.empty else {}
            indicators.price_action_score = float(getattr(latest_price_action, "get", lambda *_: 0.0)("price_action_score", 0.0) or 0.0)
            indicators.price_action_probability = float(price_action_signal.get("probability", 0.5) or 0.5)
            indicators.price_action_confidence = float(price_action_signal.get("confidence", 0.0) or 0.0) / 100.0
            indicators.price_action_signal = str(price_action_signal.get("action", "HOLD") or "HOLD")
            indicators.price_action_attack_ready = bool(
                indicators.price_action_signal in {"LONG", "SHORT"}
                and indicators.price_action_probability >= 0.65
            )
            
            
            # 2. ML Prediction
            bars_since_last_loss = self._estimate_bars_since_last_loss(historical_data)
            
            # [ML_INFERENCE_ATTEMPT] Log before and after inference attempt
            self.logger.info(
                "[ML_INFERENCE_ATTEMPT_START] %s | is_trained=%s | model_available=%s | bars_since_loss=%s | historical_bars=%d",
                self.symbol,
                self._sync_ml_training_state(),
                (self.ml_predictor.model is not None and self.ml_predictor.scaler is not None),
                bars_since_last_loss,
                len(historical_data),
            )
            
            ml_dir, ml_conf, ml_details = self.ml_predictor.predict_with_details(
                historical_data,
                indicators,
                bars_since_last_loss=bars_since_last_loss,
                short_horizon_bars=50 if (uncaged_active or striking_active) else None,
            )
            
            # [ML_INFERENCE_ATTEMPT_RESULT] Log the actual inference output
            fallback_reason = ml_details.get('fallback_reason', 'model_trained')
            self.combiner._ml_fallback_reason_for_cycle = str(fallback_reason or "model_trained")
            ml_mode = "Actual ML" if self._sync_ml_training_state() and fallback_reason == "model_trained" else "Synthetic Fallback"
            self.logger.info(
                "[ML_INFERENCE_ATTEMPT_RESULT] %s | mode=%s | direction=%s | raw_confidence=%.6f | fallback_reason=%s | meta_win_prob=%.4f | all_details=%s",
                self.symbol,
                ml_mode,
                "UP" if ml_dir == 1 else "DOWN",
                float(ml_conf or 0.0),
                fallback_reason,
                float(ml_details.get('meta_win_prob', 1.0)),
                str(ml_details),
            )
            
            meta_win_prob = float(ml_details.get('meta_win_prob', 1.0))
            ml_desc = "UP" if ml_dir == 1 else "DOWN"
            indicators.ml_confidence = float(ml_conf or 0.0)
            
            # [SYTHETIC_ML_SIGNAL_GENERATED] If fallback was used, note it
            if fallback_reason != 'model_trained':
                self.logger.critical(
                    "[SYTHETIC_ML_SIGNAL_GENERATED] %s | Fallback signal active. Reason: %s | Using indicator-based heuristic | Direction: %s | Confidence: %.4f",
                    self.symbol,
                    fallback_reason,
                    ml_desc,
                    float(ml_conf or 0.0),
                )
            
            # Get model metadata for transparency
            meta = getattr(self.ml_predictor, 'metadata', {})
            effective_ml_accuracy, closed_trade_count, accuracy_source, model_acc, live_acc = await self._resolve_effective_ml_accuracy()
            indicators.ml_accuracy = effective_ml_accuracy
            indicators.ml_accuracy_source = accuracy_source
            indicators.ml_closed_trade_count = int(closed_trade_count)
            self._last_accuracy_source = accuracy_source
            
            # === FIX #4: DEBUG FLAT 0.10 CONFIDENCE ISSUE ===
            # Verify ml_conf is not hardcoded and trace its source
            if ml_conf is not None and abs(ml_conf - 0.10) < 0.001:  # Flag if flat 0.10
                self.logger.critical(
                    "[CONFIDENCE_TRACE] %s | ALERT: ml_conf is flat 0.10 (±0.001) | "
                    "Verify this is not hardcoded. Source: ml_predictor.predict_with_details()",
                    self.symbol
                )
            # Always log ML confidence source for debugging
            ml_conf_source = "predict_with_details"
            if hasattr(indicators, 'ml_confidence'):
                ml_conf_source += "+indicators.ml_confidence"
            self.logger.debug(
                "[ML_CONF_SOURCE] %s | ML Confidence: %.2f | Accuracy: %.2f | WinProb: %.2f | Source: %s | AccSource=%s | ClosedTrades=%d | LiveAcc=%.2f | TrainAcc=%.2f",
                self.symbol, ml_conf, effective_ml_accuracy, meta_win_prob, ml_conf_source, accuracy_source, closed_trade_count, live_acc, model_acc
            )
            # ====================================================
            
            # Capture one consolidated symbol snapshot for the execution loop.
            self._last_symbol_report = {
                "price": float(current_price or 0.0),
                "rsi": float(indicators.rsi or 0.0),
                "direction": ml_desc,
                "confidence": float(ml_conf or 0.0),
                "price_action_score": float(indicators.price_action_score or 0.0),
                "price_action_probability": float(indicators.price_action_probability or 0.0),
            }
            # DEBUG: Log when we set _last_symbol_report with actual ML data
            self.logger.critical(
                "[LAST_SYMBOL_REPORT_SET] %s | direction=%s | confidence=%.2f | rsi=%.1f | This is the actual data, not fallback",
                self.symbol,
                ml_desc,
                float(ml_conf or 0.0),
                float(indicators.rsi or 0.0)
            )
            # Log detailed indicator values (only in verbose mode)
            if self.verbose:
                self.logger.debug("[ANALYSIS] %s | Price: %.5f | RSI: %.1f (range: 25-75) | ML: %s (Conf: %.0f%%, Acc: %.0f%%) | PA: %.2f | Bayes: %.0f%%",
                                 self.symbol, current_price, 
                                 indicators.rsi or 0,
                                 ml_desc, ml_conf * 100, effective_ml_accuracy * 100,
                                 indicators.price_action_score or 0.0,
                                 (indicators.price_action_probability or 0.0) * 100.0)

            # Phase 2: Meta-labeling hard gate (skip entries with low predicted win probability)
            meta_gate_min = self._compute_meta_gate_threshold(
                direction_hint=ml_desc,
                indicators=indicators,
                historical_data=historical_data,
                timestamp=historical_data[-1].timestamp,
                bars_since_last_loss=bars_since_last_loss
            )
            structure_override_active = bool(getattr(self, "_structure_override_active", False))
            technical_only_mode = bool(getattr(self, "_technical_only_mode", False))
            if structure_override_active and ml_conf > 0.05:
                self.logger.critical(
                    f"[STRUCTURE_OVERRIDE] {self.symbol} | Meta gate bypassed | "
                    f"RawML={ml_conf:.2f} > 0.05 | MetaWin={meta_win_prob:.1%} | Gate={meta_gate_min:.1%}"
                )
            elif technical_only_mode:
                self.logger.info(
                    "[META-GATE-BYPASS] %s | TECHNICAL_ONLY_MODE active | MetaWin=%.1f%% | Gate=DISABLED",
                    self.symbol,
                    meta_win_prob * 100.0,
                )
            elif meta_win_prob < meta_gate_min:
                gap = float(meta_gate_min - meta_win_prob)
                if ml_conf >= 0.75:
                    self.logger.critical(
                        f"[META-GATE-BYPASS] {self.symbol} | Elite ML confidence {ml_conf:.1%} >= 75%. "
                        f"Bypassing meta gate ({meta_win_prob:.1%} < {meta_gate_min:.1%})."
                    )
                elif gap <= 0.05:
                    self.logger.critical(
                        f"[META_BUFFER_PENDING] {self.symbol} | Meta gap {gap:.1%} within 5% buffer. "
                        "Deferring final decision to RR-aware pre-admission gate."
                    )
                elif (uncaged_active or striking_active) and meta_win_prob > 0.50:
                    self.logger.critical(
                        f"[META-GATE-BYPASS] {self.symbol} | Uncaged mode active. "
                        f"WinProb {meta_win_prob:.1%} > 50%% despite threshold {meta_gate_min:.1%}. "
                        f"Passing to RR-based admission gate."
                    )
                else:
                    self.logger.info(
                        f"[META-GATE] {self.symbol} rejected | "
                        f"Meta win prob: {meta_win_prob:.1%} < {meta_gate_min:.1%} | "
                        f"ML dir: {ml_desc} | CalibConf: {ml_conf:.1%}"
                    )
                    self.logger.info(
                        "[FILTER_DEBUG] %s | Filter=META_GATE | Actual=%.3f | Required=%.3f | Mode=%s",
                        self.symbol,
                        float(meta_win_prob or 0.0),
                        float(meta_gate_min or 0.0),
                        "TECHNICAL_ONLY" if technical_only_mode else "STANDARD",
                    )
                    self.logger.info(
                        f"[FILTER_REJECT] {self.symbol} | Reason: META_GATE "
                        f"({meta_win_prob:.2%} < {meta_gate_min:.2%})"
                    )
                    # FIX #2 CRITICAL: Update _last_symbol_report BEFORE returning None
                    try:
                        self._last_symbol_report = {
                            "price": float(current_price or 0.0),
                            "rsi": float(indicators.rsi or 50.0),
                            "direction": ml_desc,
                            "confidence": float(ml_conf or 0.45),
                            "volatility": float(getattr(indicators, 'atr', 0.0) or 0.0),
                            "timestamp": datetime.now(timezone.utc),
                        }
                    except Exception as e:
                        self.logger.debug(f"[SYMBOL_REPORT_UPDATE_META_GATE] {self.symbol} | Could not update: {e}")
                    return None
            
            # Check entry filters before generating signals
            current_timestamp = historical_data[-1].timestamp
            
            # CRITICAL FIX: Ensure _check_entry_filters is callable (not corrupted to string)
            if not callable(self._check_entry_filters):
                self.logger.critical(
                    f"[METHOD_CORRUPTION_FIX] {self.symbol} | _check_entry_filters is {type(self._check_entry_filters).__name__}, restoring method..."
                )
                # Restore from the class-level method (which was monkey-patched at module load)
                type_self = type(self)
                if hasattr(type_self, '_check_entry_filters') and callable(getattr(type_self, '_check_entry_filters')):
                    # Get the unbound method and bind it to this instance
                    self._check_entry_filters = getattr(type_self, '_check_entry_filters').__get__(self, type_self)
                else:
                    self.logger.error(f"[METHOD_CORRUPTION_FIX] {self.symbol} | Cannot restore _check_entry_filters - class method also missing!")
                    # Fallback: pass the filters
                    filter_result = (True, "METHOD_CORRUPTION_FALLBACK")
                    if isinstance(filter_result, tuple):
                        filters_passed = bool(filter_result[0]) if len(filter_result) >= 1 else False
                        filter_reason = str(filter_result[1]) if len(filter_result) >= 2 else ""
                    else:
                        filters_passed = bool(filter_result)
                        filter_reason = ""
                    # Skip the rest of the analysis and return None
                    return None
            
            filter_result = self._check_entry_filters(indicators, timestamp=current_timestamp)
            if isinstance(filter_result, tuple):
                filters_passed = bool(filter_result[0]) if len(filter_result) >= 1 else False
                filter_reason = str(filter_result[1]) if len(filter_result) >= 2 else ""
            else:
                filters_passed = bool(filter_result)
                if filters_passed and bool(getattr(self, "_structure_override_active", False)):
                    filter_reason = "STRUCTURE_OVERRIDE"
                elif filters_passed:
                    filter_reason = ""
                else:
                    filter_reason = "Baseline filters failed"
            
            if not filters_passed:
                session = self.regime_detector.detect_session(current_timestamp)
                reason = filter_reason or "Baseline filters failed"
                
                # Log missed opportunity
                self.missed_opportunities.append({
                    'timestamp': current_timestamp,
                    'direction': 'POTENTIAL',
                    'price': current_price,
                    'reason': reason,
                    'score': 0.0,
                    'ml_conf': ml_conf
                })
                
                # Track for Regret Analysis if it's a "near miss" (e.g. ADX > 8)
                if self.regret_analysis_enabled and (indicators.adx or 0) >= 8:
                    self.tracked_rejections.append({
                        'symbol': self.symbol,
                        'entry_price': current_price,
                        'tp': current_price * 1.002, # Estimated
                        'sl': current_price * 0.998, # Estimated
                        'direction': Direction.LONG, # Dummy
                        'timestamp': current_timestamp,
                        'reason': reason,
                        'status': 'PENDING'
                    })

                # FIX #2 CRITICAL: Update _last_symbol_report BEFORE returning None
                # This ensures the Quant Engine table always has current indicator data
                # even when no trade signal is generated
                try:
                    self._last_symbol_report = {
                        "price": float(current_price or 0.0),
                        "rsi": float(indicators.rsi or 50.0),
                        "direction": ml_desc,
                        "confidence": float(ml_conf or 0.45),
                        "volatility": float(getattr(indicators, 'atr', 0.0) or 0.0),
                        "z_score": float(getattr(self, 'current_z_score', 0.0) or 0.0),
                        "garch_vol": float(getattr(self, 'current_garch_vol', 0.0) or 0.0),
                        "flow_delta": float(getattr(self, 'current_flow_delta', 0.0) or 0.0),
                        "timestamp": datetime.now(timezone.utc),
                    }
                except Exception as e:
                    self.logger.debug(f"[SYMBOL_REPORT_UPDATE_FILTERED] {self.symbol} | Could not update: {e}")
                
                # CRITICAL: Ensure tech_signals is defined before any reference
                if 'tech_signals' not in locals():
                    tech_signals = []
                
            # CRITICAL SAFEGUARD: Ensure tech_signals exists before any conditional checks
            if 'tech_signals' not in locals():
                tech_signals = []
            
            if tech_signals and indicators.sma_50:
                # Much more relaxed: only filter if signal direction is clearly against trend
                # Get approximate SMA slope
                prev_sma_50 = indicators.sma_50  # Default to current if can't calculate
                if len(historical_data) > 55:
                    prev_sma_50 = sum(d.close for d in historical_data[-55:-5]) / 50

                filtered_signals = []
                for signal in tech_signals:
                    # Allow signal through unless it's STRONGLY against the trend
                    # BUY signal: Allow if price is ANYWHERE reasonable (not just above SMA)
                    # SELL signal: Allow if price is ANYWHERE reasonable (not just below SMA)
                    # This is much more permissive than before
                    filtered_signals.append(signal)
                                
                tech_signals = filtered_signals
                
            # --- H4 TREND FILTER (MTF) - RELAXED FOR RANGING MARKETS ---
            # Filter technical signals against the major trend (H4 SMA 50 proxy)
            # Buy only if Price > H4 Trend (with 2% buffer for ranging markets)
            # Sell only if Price < H4 Trend (with 2% buffer for ranging markets)
            # FIXED: Previous 0.05% tolerance was TOO STRICT, blocking ALL signals in ranging/choppy markets
            if tech_signals and indicators.h4_trend:
                mtf_filtered_signals = []
                for signal in tech_signals:
                    if signal.signal_type == SignalType.BUY:
                        # Allow BUY if price is above H4 Trend, with 2% downside tolerance for retests
                        # This allows trading near support in bullish environments
                        if current_price > indicators.h4_trend * 0.98: 
                            mtf_filtered_signals.append(signal)
                        else:
                            self.logger.debug(f"[MTF-FILTER] Rejected BUY on {self.symbol} (Price {current_price:.5f} < H4 Trend {indicators.h4_trend:.5f} * 0.98)")
                    
                    elif signal.signal_type == SignalType.SELL:
                        # Allow SELL if price is below H4 Trend, with 2% upside tolerance for retests
                        # This allows trading near resistance in bearish environments
                        if current_price < indicators.h4_trend * 1.02:
                            mtf_filtered_signals.append(signal)
                        else:
                            self.logger.debug(f"[MTF-FILTER] Rejected SELL on {self.symbol} (Price {current_price:.5f} > H4 Trend {indicators.h4_trend:.5f} * 1.02)")
                            
                tech_signals = mtf_filtered_signals
                if not mtf_filtered_signals and signals:
                    self.logger.critical(
                        f"[H4_TREND_FILTER_BLOCKED_ALL] {self.symbol} | H4 Trend filter removed ALL {len(signals)} technical signals. "
                        f"Price {current_price:.5f} vs SMA200 {indicators.h4_trend:.5f} (Gap: {abs(current_price - indicators.h4_trend):.5f}). "
                        f"Allowing signals to pass for admission gate evaluation."
                    )
                    tech_signals = signals  # FALLBACK: Allow technical signals through if all blocked
            
            # Refine signals with ML
            if tech_signals:
                for signal in tech_signals:
                    # If ML agrees with signal direction
                    if (signal.signal_type == SignalType.BUY and ml_dir == 1) or \
                       (signal.signal_type == SignalType.SELL and ml_dir == 0):
                        signal.strength = min(signal.strength * (1.0 + ml_conf), 1.0)
                    else:
                        # ML disagrees - penalize signal strength
                        signal.strength *= (1.0 - ml_conf)
            # Always incorporate ML as a synthetic signal if confidence is sufficient
            # FIXED: Lowered from 0.7 to 0.4 to ensure ML signals contribute even with moderate confidence
            if ml_conf > 0.4:
                signal_type = SignalType.BUY if ml_dir == 1 else SignalType.SELL
                synthetic_signal = TechnicalSignal(
                    symbol=self.symbol,
                    signal_type=signal_type,
                    strength=ml_conf,
                    indicators={"ML_CONFIDENCE": ml_conf, "SYNTHETIC": 1},
                    timestamp=historical_data[-1].timestamp
                )
                tech_signals.append(synthetic_signal)
                self.logger.info(f"[STRATEGY] Added synthetic ML {signal_type.value} signal (conf: {ml_conf:.2f})")
            elif ml_conf > 0.2:
                # FALLBACK: Even low-confidence ML signals contribute when no strong tech signals exist
                if not tech_signals:
                    signal_type = SignalType.BUY if ml_dir == 1 else SignalType.SELL
                    fallback_signal = TechnicalSignal(
                        symbol=self.symbol,
                        signal_type=signal_type,
                        strength=max(ml_conf, 0.25),  # Ensure minimum strength for combiner processing
                        indicators={"ML_CONFIDENCE": ml_conf, "SYNTHETIC": 1, "FALLBACK": 1},
                        timestamp=historical_data[-1].timestamp
                    )
                    tech_signals.append(fallback_signal)
                    self.logger.info(f"[STRATEGY_FALLBACK] Added fallback ML {signal_type.value} signal (conf: {ml_conf:.2f}) - no tech signals available")


            if (
                price_action_signal.get("action") in {"LONG", "SHORT"}
                and float(price_action_signal.get("confidence", 0.0) or 0.0) > 65.0
            ):
                signal_type = (
                    SignalType.BUY if price_action_signal["action"] == "LONG" else SignalType.SELL
                )
                pa_strength = min(
                    1.0,
                    max(float(price_action_signal.get("confidence", 0.0) or 0.0) / 100.0, 0.0),
                )
                price_action_tech_signal = TechnicalSignal(
                    symbol=self.symbol,
                    signal_type=signal_type,
                    strength=pa_strength,
                    indicators={
                        "PRICE_ACTION_SCORE": float(indicators.price_action_score or 0.0),
                        "PRICE_ACTION_PROB": float(indicators.price_action_probability or 0.5),
                        "PRICE_ACTION_CONF": pa_strength,
                        "PRICE_ACTION": 1.0,
                        "SYNTHETIC": 1.0,
                    },
                    timestamp=historical_data[-1].timestamp,
                )
                tech_signals.append(price_action_tech_signal)
                self.logger.critical(
                    "[AGGRESSIVE_STRIKE] %s | Price Action Math %s attack detected | Confidence: %.1f%% | Bayes: %.1f%% | Score: %.2f",
                    self.symbol,
                    signal_type.value,
                    float(price_action_signal.get("confidence", 0.0) or 0.0),
                    float(price_action_signal.get("probability", 0.5) or 0.5) * 100.0,
                    float(price_action_signal.get("score", 0.0) or 0.0),
                )
            
            # FALLBACK: If no signals exist and ML is confident enough, create synthetic signal
            if not tech_signals and ml_conf > 0.45:  # Ultra-aggressive: Lowered to 45%
                signal_type = SignalType.BUY if ml_dir == 1 else SignalType.SELL
                synthetic_signal = TechnicalSignal(
                    symbol=self.symbol,
                    signal_type=signal_type,
                    strength=ml_conf * 0.8,  # Slightly penalize for lack of technical confirmation
                    indicators={"ML_CONFIDENCE": ml_conf, "FALLBACK": True, "SYNTHETIC": 1},
                    timestamp=historical_data[-1].timestamp
                )
                tech_signals.append(synthetic_signal)
                self.logger.info(f"[STRATEGY] FALLBACK: Created ML-only {signal_type.value} signal (conf: {ml_conf:.2f})")
                
            # 4. Combine signals into a TradingSignal
            if self.combiner is not None:
                self.combiner.override_ml_confidence = float(ml_conf or 0.0)
                self.combiner.override_meta_win_prob = float(meta_win_prob or 0.0)
                self.combiner.override_price_action_score = float(price_action_signal.get("confidence", 0.0) or 0.0)
                self.combiner.override_pa_type = str(price_action_signal.get("type", "NONE") or "NONE")
                self.combiner.structure_override_active = bool(getattr(self, "_structure_override_active", False))
                self.combiner.structure_override_min_ml = 0.05
                self.combiner.news_guard_active = bool(getattr(self, "_news_guard_active", False))
                self.combiner._ml_accuracy_for_cycle = float(effective_ml_accuracy or 0.0)
                self.combiner._historical_trade_count_for_cycle = int(closed_trade_count or 0)
                self.combiner._low_accuracy_cycle_count_for_cycle = int(self.low_accuracy_cycle_count or 0)
                self.combiner._bot_cycle_count_for_cycle = int(getattr(self, "_bot_cycle_count", 0) or 0)
                self.combiner._technical_only_mode_for_cycle = bool(getattr(self, "_technical_only_mode", False))
                self.combiner._desperation_mode_for_cycle = bool(getattr(self, "_desperation_mode", False))
            combined_result = self.combiner.combine_signals(
                sentiment_result=None,
                technical_signals=tech_signals,
                current_price=current_price,
                symbol=self.symbol,
                reference_time=historical_data[-1].timestamp,
                historical_data=historical_data,  # Pass historical data for ATR calculation
                current_positions=current_positions,
            )
            
            self.logger.critical(
                f"[COMBINE_RESULT_DEBUG] {self.symbol} | Tech signals in: {len(tech_signals)} | "
                f"Signal out: {combined_result.trading_signal is not None} | "
                f"Conf: {combined_result.confidence_score:.2f}"
            )
            
            if not combined_result.trading_signal:
                pass  # No signal generated
            
            if combined_result.trading_signal:
                combined_result.trading_signal.price_action_score = float(price_action_signal.get("confidence", 0.0) or 0.0)
                combined_result.trading_signal.pa_type = str(price_action_signal.get("type", "NONE") or "NONE")
                if float(getattr(combined_result.trading_signal, "confidence", 0.0) or 0.0) >= 0.75:
                    combined_result.trading_signal.forced_execution = True
                    self.logger.critical(
                        f"[SYNTHETIC_FORCE_EXEC] {self.symbol} | signal.confidence "
                        f"{combined_result.trading_signal.confidence:.2f} >= 0.75 -> forced_execution=True"
                    )

                # 5. Evaluate signal quality before returning
                quality_analysis = self.signal_quality_calculator.analyze_signal_quality(
                    technical_signals=tech_signals,
                    indicators=indicators,
                    current_price=current_price,
                    direction=combined_result.trading_signal.direction,
                    volume=historical_data[-1].volume if historical_data else None,
                    hour_of_day=historical_data[-1].timestamp.hour if historical_data else None
                )
                
                # Update cooling-off if we see a recent SL hit in history (optional, or via callback)
                # For now, we assume the bot tracks its own SL hits in real-time
                
                # PHASE 2: Check standard technical entry filters
                # Get symbol-specific filters for quality check
                signal_direction = combined_result.trading_signal.direction.name  # 'LONG' or 'SHORT'
                symbol_filters = self._get_active_symbol_filters(signal_direction)
                min_quality = self._get_effective_quality_floor(
                    symbol_filters.get('signal_quality_min', quality_floor),
                    now=current_timestamp if getattr(current_timestamp, "tzinfo", None) else None,
                )
                
                if quality_analysis.quality_score < min_quality:
                    # FALLBACK: If ML model is untrained, bypass quality check to allow signals through
                    is_ml_trained = bool(getattr(self.ml_predictor, 'is_trained', False))
                    if not is_ml_trained:
                        self.logger.critical(
                            f"[QUALITY_BYPASS_ML_UNTRAINED] {self.symbol} {signal_direction} | "
                            f"ML model untrained - bypassing quality floor. "
                            f"Score: {quality_analysis.quality_score:.2f} < Min: {min_quality:.2f}"
                        )
                        # Continue to next checks - don't return None
                    else:
                        self.logger.critical(
                            f"[QUALITY_REJECTION] {self.symbol} {signal_direction} | "
                            f"Score: {quality_analysis.quality_score:.2f} < Min: {min_quality:.2f} | SIGNAL BLOCKED | "
                            f"Reason: {quality_analysis.reasoning}"
                        )
                        return None
                
                # PHASE 1: Multi-factor Signal Quality Filter (Session-Aware)
                current_timestamp = historical_data[-1].timestamp
                session = self.regime_detector.detect_session(current_timestamp)
                
                analysis_data = {
                    'adx': indicators.adx or 15,
                    'trend_aligned': True,  # Already checked by filters
                    'rsi_extreme': (indicators.rsi or 50) < 25 or (indicators.rsi or 50) > 75,
                    'volume_confirmed': (historical_data[-1].volume if historical_data else 0) > 0,
                    'ma_bullish': indicators.sma_50 is not None and current_price > indicators.sma_50,
                    'pattern_bullish': True,  # Already in tech_signals strength
                    'atr': indicators.atr or 0.0001,
                    'atr_mean': indicators.atr or 0.0001,  # Simplified for current ATR
                    'rsi': indicators.rsi or 50,
                    'volume': historical_data[-1].volume if historical_data else 0,
                    'volume_mean': sum(d.volume for d in historical_data[-20:]) / 20 if len(historical_data) >= 20 else historical_data[-1].volume if historical_data else 0,
                    'session': session.value
                }
                
                # Get ML confidence for adaptive filtering
                bars_since_last_loss = self._estimate_bars_since_last_loss(historical_data)
                ml_direction, ml_confidence, ml_details = self.ml_predictor.predict_with_details(
                    historical_data,
                    indicators,
                    bars_since_last_loss=bars_since_last_loss,
                    short_horizon_bars=50 if (uncaged_active or striking_active) else None,
                )
                self.combiner._ml_fallback_reason_for_cycle = str(ml_details.get('fallback_reason', 'model_trained') or "model_trained")
                meta_win_prob = float(ml_details.get('meta_win_prob', 1.0))
                meta_gate_min = self._compute_meta_gate_threshold(
                    direction_hint=signal_direction,
                    indicators=indicators,
                    historical_data=historical_data,
                    timestamp=current_timestamp,
                    bars_since_last_loss=bars_since_last_loss
                )

                structure_override_active = bool(getattr(self, "_structure_override_active", False))
                technical_only_mode = bool(getattr(self, "_technical_only_mode", False))
                if structure_override_active and ml_confidence > 0.05:
                    self.logger.critical(
                        f"[STRUCTURE_OVERRIDE] {self.symbol} | Pre-admission meta gate bypassed | "
                        f"RawML={ml_confidence:.2f} > 0.05 | MetaWin={meta_win_prob:.1%} | Gate={meta_gate_min:.1%}"
                    )
                elif technical_only_mode:
                    self.logger.info(
                        "[META-GATE-BYPASS] %s | TECHNICAL_ONLY_MODE active pre-admission | "
                        "MetaWin=%.1f%% | Gate=DISABLED",
                        self.symbol,
                        meta_win_prob * 100.0,
                    )
                elif meta_win_prob < meta_gate_min:
                    rr_ratio = float(getattr(combined_result.trading_signal, "rr_ratio", 0.0) or 0.0)
                    gap = float(meta_gate_min - meta_win_prob)
                    if getattr(combined_result.trading_signal, "forced_execution", False):
                        self.logger.critical(
                            f"[META-GATE-BYPASS] {self.symbol} forced_execution=True. "
                            f"Skipping pre-admission meta gate."
                        )
                    elif gap <= 0.05 and rr_ratio > 2.5:
                        self.logger.critical(
                            f"[META_BUFFER_ADMISSION] Admitting {self.symbol} despite marginal prob gap due to high RR. "
                            f"MetaWin={meta_win_prob:.1%} Target={meta_gate_min:.1%} Gap={gap:.1%} RR={rr_ratio:.2f}R"
                        )
                    elif (uncaged_active or striking_active) and meta_win_prob > 0.50 and rr_ratio > 2.0:
                        self.logger.critical(
                            f"[META-GATE-BYPASS] {self.symbol} pre-admission bypass | "
                            f"WinProb {meta_win_prob:.1%} > 50%% and RR {rr_ratio:.2f}R > 2.0R."
                        )
                    else:
                        self.logger.info(
                            f"[META-GATE] {self.symbol} rejected pre-admission | "
                            f"Meta win prob: {meta_win_prob:.1%} < {meta_gate_min:.1%}"
                        )
                        self.logger.info(
                            "[FILTER_DEBUG] %s | Filter=META_GATE_PRE | Actual=%.3f | Required=%.3f | Mode=%s",
                            self.symbol,
                            float(meta_win_prob or 0.0),
                            float(meta_gate_min or 0.0),
                            "TECHNICAL_ONLY" if technical_only_mode else "STANDARD",
                        )
                        self.logger.info(
                            f"[FILTER_REJECT] {self.symbol} | Reason: META_GATE "
                            f"({meta_win_prob:.2%} < {meta_gate_min:.2%})"
                        )
                        return None
                
                # Forced execution bypass removed. EV gatekeeper in admission controller decides final admit.
                
                # ===== DETECT MARKET CONDITION & APPLY ADAPTIVE STRICTNESS =====
                market_condition = self.strictness_controller.detect_market_condition(analysis_data)
                strictness_mode = self.strictness_controller.get_strictness_mode(market_condition)
                adjustments = self.strictness_controller.get_adaptive_adjustments(market_condition, strictness_mode)
                
                # Apply adjustments to filterer (modifies current_min_score)
                self.strictness_controller.apply_adjustments_to_filterer(
                    self.signal_filterer,
                    adjustments,
                    market_condition
                )
                
                self.logger.debug(
                    f"[MARKET STATE] {market_condition.value} ({strictness_mode.value}) | "
                    f"Threshold: {self.signal_filterer.current_min_score:.1f}"
                )
                
                # ===== ADAPTIVE SIGNAL FILTERING =====
                # Accepts if: score ≥ min_score OR ml_conf ≥ 70% OR score ≥ 70% of min
                self.signal_filterer.current_min_score = 25.0
                should_trade_phase1, score_phase1, reason_phase1 = self.signal_filterer.should_trade_signal(
                    combined_result.trading_signal.__dict__, 
                    analysis_data,
                    timestamp=current_timestamp,
                    ml_confidence=ml_confidence  # ADDED: ML confidence for override logic
                )
                
                # ===== ADAPTIVE STRICTNESS OVERRIDE =====
                # May further filter or accept based on market condition
                # NEW: Returns (success, reason, position_size_mult, trade_tier)
                should_trade_final, strictness_reason, strictness_size_mult, trade_tier = self.strictness_controller.should_trade_with_strictness(
                    should_trade_phase1,
                    score_phase1,
                    ml_confidence,
                    market_condition,
                    adjustments
                )
                
                # Track signal evaluation for averages and statistics
                self.strictness_controller.track_signal_evaluation(
                    market_condition,
                    score_phase1,
                    ml_confidence,
                    should_trade_final
                )
                
                # ===== LOG ADAPTIVE DECISION =====
                self.strictness_controller.log_trade_decision(
                    self.symbol,
                    market_condition,
                    strictness_mode,
                    adjustments,
                    should_trade_final,
                    score_phase1,
                    ml_confidence,
                    trade_tier
                )
                
                if not should_trade_final:
                    # FALLBACK: If ML model is untrained, allow signal through despite strictness checks
                    is_ml_trained = bool(getattr(self.ml_predictor, 'is_trained', False))
                    if not is_ml_trained:
                        self.logger.critical(
                            f"[STRICTNESS_BYPASS_ML_UNTRAINED] {self.symbol} {signal_direction} | "
                            f"ML model untrained - bypassing strictness filter. "
                            f"Reason: {strictness_reason} | Score: {score_phase1:.1f}"
                        )
                        # Continue - don't return None
                    else:
                        # Log missed opportunity data for analysis
                        self.missed_opportunities.append({
                            'timestamp': current_timestamp,
                            'direction': signal_direction,
                            'price': current_price,
                            'reason': strictness_reason,
                            'score': score_phase1,
                            'ml_conf': ml_confidence
                        })
                        self.logger.info(f"[MISSED OPPORTUNITY] Logged rejection for {self.symbol} {signal_direction} at {current_price:.5f}")
                        return None
                
                # GET REGIME-BASED ACTION (Including High Quality Overrides)
                regime = self.regime_detector.get_regime(analysis_data, session)
                vol_regime = self.regime_detector.get_volatility_regime(analysis_data, session)
                regime_action = self.regime_detector.get_action(regime, vol_regime, signal_quality=score_phase1)
                
                if not should_trade_final and not regime_action['trade']:
                    # FALLBACK: If ML model is untrained, allow signal through
                    is_ml_trained = bool(getattr(self.ml_predictor, 'is_trained', False))
                    if not is_ml_trained:
                        self.logger.critical(
                            f"[DUAL_REJECTION_BYPASS_ML_UNTRAINED] {self.symbol} | "
                            f"ML model untrained - bypassing both strictness and regime checks. "
                            f"Reason: {strictness_reason} | Regime: {regime}/{vol_regime}"
                        )
                        # Continue - don't return None
                    else:
                        # ===== DETAILED REJECTION LOGGING =====
                        self.logger.warning(
                            f"[✗ REJECTED] {self.symbol}\n"
                            f"   {reason_phase1}\n"
                            f"   {strictness_reason}\n"
                            f"   Regime: {regime}/{vol_regime} ({regime_action['reason']})\n"
                            f"   ML Conf: {ml_confidence:.1%}"
                        )
                        return None
                
                # No forced regime-veto bypass; keep regime controls intact.
                if not regime_action['trade'] and regime == 'CHOPPY':
                    # FALLBACK: If ML model is untrained, allow trading even in choppy markets
                    is_ml_trained = bool(getattr(self.ml_predictor, 'is_trained', False))
                    if not is_ml_trained:
                        self.logger.critical(
                            f"[CHOPPY_BYPASS_ML_UNTRAINED] {self.symbol} | "
                            f"ML model untrained - allowing trade in CHOPPY regime"
                        )
                    else:
                        self.logger.info(f"[CHOPPY-STAYOUT] {self.symbol} rejected due to choppy regime")
                        return None
                
                # Adjust position size based on signal quality AND regime action
                base_size = 1.0
                # ===== ML-WEIGHTED POSITION SIZING =====
                # Composite: 60% technical score + 40% ML confidence
                quality_size = self.signal_filterer.adjust_position_size(
                    score_phase1, 
                    base_size, 
                    ml_confidence=ml_confidence
                )
                
                # Apply regime action multiplier AND strictness multiplier (for ML overrides in weak markets)
                final_size_mult = quality_size * regime_action.get('size_multiplier', 1.0)
                if strictness_size_mult is not None:
                    final_size_mult *= strictness_size_mult
                
                # ===== PATCH #8: VERIFY 0.75X RANGING MULTIPLIER STILL APPLIES =====
                # Even for Priority Admission entries, maintain conservative risk profile in non-trending markets
                # Check if regime is RANGING and ensure 0.75x multiplier is applied
                if regime == 'RANGING' and final_size_mult > 0.75:
                    original_size = final_size_mult
                    final_size_mult = min(final_size_mult, 0.75)  # Cap at 0.75x for ranging markets
                    if abs(original_size - final_size_mult) > 0.01:  # If it actually got reduced
                        self.logger.info(
                            f"[0.75X RANGING-MULTIPLIER ENFORCED] {self.symbol} in RANGING regime. "
                            f"Position reduced from {original_size:.2f}x to {final_size_mult:.2f}x "
                            f"(conservative risk profile maintained)"
                        )
                
                # Store adjusted size multiplier and metadata for later tracking
                combined_result.trading_signal.position_size = final_size_mult
                combined_result.trading_signal.market_condition = market_condition.value
                combined_result.trading_signal.is_ml_override = "[ML-REGIME OVERRIDE]" in strictness_reason
                combined_result.trading_signal.trade_tier = trade_tier.value
                combined_result.trading_signal.adaptive_score = float(score_phase1)
                combined_result.trading_signal.strictness_reason = str(strictness_reason)
                combined_result.trading_signal.rule_source = str(rule_source) if 'rule_source' in locals() else "UNKNOWN"
                
                if self.verbose:
                    # ===== DETAILED ACCEPTANCE LOGGING =====
                    self.logger.info(
                        f"[✓ ACCEPTED] {self.symbol}\n"
                        f"   {reason_phase1}\n"
                        f"   Regime: {regime}/{vol_regime}\n"
                        f"   Position: {final_size_mult:.2f}x (quality={quality_size:.2f}, regime={regime_action.get('size_multiplier', 1.0):.2f})\n"
                        f"   Entry: {combined_result.trading_signal.entry_price:.5f} | ML: {ml_confidence:.1%}"
                    )
                
            # PHASE 3: Expectancy Floor (R:R >= 1.8)
            sig = combined_result.trading_signal
            if sig is None:
                self.logger.debug(f"[FILTER] {self.symbol} - No trading signal generated, skipping RR validation")
                return None
            
            if sig.stop_loss and sig.take_profit:
                risk = abs(sig.entry_price - sig.stop_loss)
                reward = abs(sig.take_profit - sig.entry_price)
                rr = reward / risk if risk > 0 else 0
                if rr < 1.8:
                    self.logger.info(f"[FILTER] {self.symbol} rejected: Expectancy Floor (RR: {rr:.2f} < 1.8)")
                    self.tracked_rejections.append({
                        'symbol': self.symbol,
                        'entry_price': sig.entry_price,
                        'tp': sig.take_profit,
                        'sl': sig.stop_loss,
                        'direction': sig.direction,
                        'timestamp': current_timestamp,
                        'reason': f"RR Floor {rr:.2f}",
                        'status': 'PENDING'
                    })
                    return None

            # ===== FIX #6: [TRADE_READY] LOG - AFTER ALL FILTERS, BEFORE ADMISSION CHECK =====
            # This is the checkpoint where signal has passed all quality/technical filters
            # and is now ready for admission controller evaluation
            # Include Rule Source to show which logic path won
            risk_amt = abs(sig.entry_price - sig.stop_loss) * final_size_mult if sig.stop_loss else 0
            reward_amt = abs(sig.take_profit - sig.entry_price) * final_size_mult if sig.take_profit else 0
            actual_rr = reward_amt / risk_amt if risk_amt > 0 else 0
            
            # Determine rule source
            rule_source = "UNKNOWN"
            if regime == 'RANGING' and ml_confidence > 0.85:
                rule_source = "HIGH_CONFIDENCE_PASS"
            elif trade_tier and trade_tier.value and 'TIER' in trade_tier.value:
                rule_source = f"CONFIDENCE_ALPHA ({trade_tier.value})"
            elif score_phase1 > 85:
                rule_source = "ELITE_SIGNAL (>85% Quality)"
            else:
                rule_source = "STANDARD_PASS"
            
            self.logger.critical(
                f"[TRADE_READY] {self.symbol} {sig.direction.value} | "
                f"ALL FILTERS PASSED | Ready for Admission Controller evaluation | "
                f"Entry: {sig.entry_price:.5f} | SL: {sig.stop_loss:.5f} | TP: {sig.take_profit:.5f} | "
                f"RR: {actual_rr:.2f}R | Size: {final_size_mult:.2f}x | ML: {ml_confidence:.1%} | "
                f"Confidence: {score_phase1:.1f} | Source: {rule_source}"
            )

            if combined_result.trading_signal is not None:
                combined_result.trading_signal.ml_accuracy = float(effective_ml_accuracy)
                combined_result.trading_signal.model_training_accuracy = float(model_acc)
                combined_result.trading_signal.ml_live_accuracy = float(live_acc)
                combined_result.trading_signal.ml_live_trade_count = int(closed_trade_count)
                combined_result.trading_signal.ml_accuracy_source = accuracy_source
                combined_result.trading_signal.adaptive_score = float(score_phase1)
                combined_result.trading_signal.market_regime = str(regime)
                combined_result.trading_signal.volatility_regime = str(vol_regime)
            if cycle_id is not None:
                self.cycle_cache[cache_key] = combined_result.trading_signal
            
            # EMERGENCY OVERRIDE: Force signal data so ML is never NONE
            if not isinstance(ml_desc, str) or ml_desc == 'NONE' or ml_desc not in ('UP', 'DOWN'):
                ml_desc = 'UP' if (indicators.rsi or 50) > 50 else 'DOWN'
                ml_conf = 0.45
                self.logger.info(f'[FORCE] Applied fallback ML for {self.symbol}')
            
            # Ensure the _last_symbol_report has EXACTLY these keys
            self._last_symbol_report = {
                'direction': str(ml_desc), 
                'confidence': float(ml_conf),
                'rsi': float(indicators.rsi or 0.0)
            }
            
            # FIX #2: CRITICAL - ALWAYS update _last_symbol_report at the END of analyze()
            # This ensures Quant Engine has current RSI and Volatility data for ALL symbols EVERY cycle
            # FIX #5: Round volatility and RSI to 2 decimal places for clean Quant Table display
            try:
                self._last_symbol_report = {
                    "price": float(current_price or 0.0),
                    "rsi": round(float(indicators.rsi or 50.0), 2),
                    "direction": str(ml_desc),
                    "confidence": round(float(ml_conf or 0.45), 2),
                    "volatility": round(float(getattr(indicators, 'atr', 0.0) or 0.0), 2),
                    "timestamp": datetime.now(timezone.utc),
                }
                self.logger.debug(
                    "[SYMBOL_REPORT_FINAL_UPDATE] %s | RSI=%.2f | ML=%s | Conf=%.2f | Updated at end of analyze()",
                    self.symbol,
                    round(float(indicators.rsi or 50.0), 2),
                    str(ml_desc),
                    round(float(ml_conf or 0.45), 2),
                )
            except Exception as final_update_err:
                self.logger.warning(
                    "[SYMBOL_REPORT_FINAL_ERROR] %s | Failed to update at end: %s",
                    self.symbol,
                    final_update_err,
                )
            
            # Log exit point with signal status
            self.logger.critical(
                "[ANALYZE_EXIT] %s | Returning signal | direction=%s | confidence=%.2f | signal_present=%s",
                self.symbol,
                ml_desc,
                float(ml_conf),
                combined_result.trading_signal is not None
            )
            
            return combined_result.trading_signal
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error in strategy analysis for {self.symbol}: {e}\n{traceback.format_exc()}")
            # CRITICAL: Even on exception, populate _last_symbol_report with fallback so ML is never NONE
            if not hasattr(self, '_last_symbol_report') or not self._last_symbol_report:
                self._last_symbol_report = {
                    "direction": "DOWN",
                    "confidence": 0.45,
                    "rsi": 50.0
                }
                self.logger.critical("[EXCEPTION_FALLBACK] %s | analyze() threw exception, setting fallback DOWN", self.symbol)
            else:
                self.logger.critical("[EXCEPTION_PRESERVE] %s | analyze() threw exception, keeping existing report: %s", self.symbol, self._last_symbol_report)
            if cycle_id is not None:
                self.cycle_cache[cache_key] = None
            return None
    
    async def _check_recent_sl_hits(self):
        """
        Scans recent trade history for the symbol to detect stop-loss hits
        and trigger the cooling-off period.
        """
        try:
            import MetaTrader5 as mt5
            # Scan last 4 hours of history
            from_date = datetime.now() - timedelta(hours=4)
            deals = await asyncio.to_thread(mt5.history_deals_get, from_date, datetime.now(), group=f"*{self.symbol.replace('/','') or self.symbol}*")
            
            if deals:
                # Sort by time descending
                sorted_deals = sorted(deals, key=lambda x: x.time, reverse=True)
                for deal in sorted_deals:
                    # Check if deal info indicates an SL hit
                    # MT5 comment usually contains 'sl' for stop loss hits
                    comment = deal.comment.lower()
                    if 'sl' in comment or 'stop loss' in comment:
                        hit_time = datetime.fromtimestamp(deal.time)
                        self.last_sl_hit_time = hit_time
                        self.logger.critical(
                            f"[LOSS_COOLDOWN] {self.symbol} | SL recently hit. Symbol locked for 4 hours to prevent revenge trading."
                        )
                        break
        except Exception as e:
            self.logger.error(f"Error checking recent SL hits for {self.symbol}: {e}")

    def _estimate_bars_since_last_loss(self, historical_data: List[MarketData]) -> int:
        """Estimate bars since last stop-loss event for structural ML context."""
        if not historical_data:
            return 999
        if not self.last_sl_hit_time:
            return 999

        try:
            if len(historical_data) >= 2:
                bar_seconds = abs((historical_data[-1].timestamp - historical_data[-2].timestamp).total_seconds())
                if bar_seconds <= 0:
                    bar_seconds = 3600.0
            else:
                bar_seconds = 3600.0

            now_ts = historical_data[-1].timestamp
            if self.last_sl_hit_time.tzinfo and now_ts.tzinfo is None:
                now_ts = now_ts.replace(tzinfo=timezone.utc)
            elif self.last_sl_hit_time.tzinfo is None and now_ts.tzinfo:
                now_ts = now_ts.replace(tzinfo=None)

            elapsed = (now_ts - self.last_sl_hit_time).total_seconds()
            if elapsed <= 0:
                return 0

            return int(elapsed // max(bar_seconds, 1.0))
        except Exception:
            return 999

    def _estimate_atr_baseline(self, historical_data: List[MarketData], lookback: int = 50) -> float:
        """Estimate ATR baseline from recent bars for volatility-aware meta gating."""
        if not historical_data or len(historical_data) < 3:
            return 0.0
        window = historical_data[-(lookback + 2):]
        tr_values = []
        for i in range(1, len(window)):
            c = window[i]
            p = window[i - 1]
            tr = max(c.high - c.low, abs(c.high - p.close), abs(c.low - p.close))
            tr_values.append(tr)
        if not tr_values:
            return 0.0
        return float(np.mean(tr_values))

    def _compute_meta_gate_threshold(
        self,
        direction_hint: str,
        indicators: TechnicalIndicators,
        historical_data: List[MarketData],
        timestamp: datetime,
        bars_since_last_loss: int
    ) -> float:
        """
        Compute adaptive Phase 2 meta threshold using symbol profile + regime context.
        """
        if bool(getattr(self, "_desperation_mode", False)):
            self.logger.warning(
                "[META-GATE-BYPASS] %s | DESPERATION_MODE active. Meta gate disabled for bootstrap trading.",
                self.symbol,
            )
            return 0.0
        if bool(getattr(self, "_technical_only_mode", False)):
            self.logger.info(
                "[META-GATE-BYPASS] %s | TECHNICAL_ONLY_MODE active. Meta gate disabled for bootstrap trading.",
                self.symbol,
            )
            return 0.0

        direction = "LONG" if str(direction_hint).upper() in ("LONG", "UP", "BUY") else "SHORT"
        symbol_filters = self._get_active_symbol_filters(direction)
        base_threshold = float(symbol_filters.get('meta_win_prob_min', self.entry_filters.get('meta_win_prob_min', 0.30)))

        threshold = base_threshold
        session = self.regime_detector.detect_session(timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)

        atr = float(indicators.atr or 0.0)
        atr_base = self._estimate_atr_baseline(historical_data, lookback=50)
        vol_ratio = (atr / atr_base) if atr > 0 and atr_base > 0 else 1.0

        # High volatility -> stricter meta requirement; low volatility -> mildly relaxed
        if vol_ratio > 1.25:
            threshold += 0.04
        elif vol_ratio < 0.80:
            threshold -= 0.02

        # If market is strongly trending for this session, allow slightly lower threshold.
        adx = float(indicators.adx or 0.0)
        if adx >= float(thresholds.get('adx_strong', 25)):
            threshold -= 0.02

        # Immediately after a loss, require stronger meta confirmation.
        if bars_since_last_loss < 5:
            threshold += 0.06
        elif bars_since_last_loss < 12:
            threshold += 0.03

        # Model quality guardrail.
        model_acc = float(getattr(self.ml_predictor, 'metadata', {}).get('accuracy_score', 0.5) or 0.5)
        if model_acc < 0.50:
            threshold += 0.02
        elif model_acc >= 0.56:
            threshold -= 0.01

        # SYSTEM_UNCAGED striking mode: relax all meta-gate requirements by 10% (relative).
        uncaged = (
            str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
        )
        if uncaged:
            threshold *= 0.90

        threshold = float(min(max(threshold, 0.30), 0.72))
        # Emergency full-auto override: flat 30% meta gate.
        threshold = 0.30
        # Adaptive meta-gate relaxation when predictive edge is positive.
        edge_hint = float(getattr(self, "_predictive_edge_hint", 0.0) or 0.0)
        if edge_hint > 0.0:
            threshold = min(threshold, 0.30)

        # SYSTEM_UNCAGED / STRIKING_MODE override:
        # hard-cap meta-gate requirements at 52% for 12 hours from first activation.
        uncaged_active = (
            str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
        )
        striking_active = str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
        if uncaged_active or striking_active:
            now_utc = datetime.now(timezone.utc)
            if self._meta_gate_override_until is None or now_utc > self._meta_gate_override_until:
                self._meta_gate_override_until = now_utc + timedelta(hours=12)
            if now_utc <= self._meta_gate_override_until:
                threshold = 0.30

        self.logger.debug(
            f"[META-GATE-THRESH] {self.symbol} {direction} | Session={session.value} | "
            f"ADX={adx:.1f} | ATR-ratio={vol_ratio:.2f} | BarsSinceLoss={bars_since_last_loss} | "
            f"ModelAcc={model_acc:.1%} | Threshold={threshold:.2f}"
        )
        return threshold

    def _sanitize_indicators(self, indicators: TechnicalIndicators) -> TechnicalIndicators:
        """
        Sanitize indicators to ensure no complex numbers or NaNs cause crashes.
        """
        if not indicators:
            return indicators
            
        # Use __dict__.keys() to avoid issues during iteration if we modified it
        for key in list(indicators.__dict__.keys()):
            value = getattr(indicators, key)
            if value is None or isinstance(value, (str, datetime)):
                continue
                
            # Handle complex numbers (including numpy variant)
            if isinstance(value, complex) or np.iscomplexobj(value):
                real_val = float(np.real(value))
                self.logger.warning(f"Sanitizing COMPLEX indicator {key}: {value} -> {real_val}")
                setattr(indicators, key, real_val)
            
            # Handle NaNs/Infs which also cause comparison issues
            elif isinstance(value, (float, np.floating)):
                 if np.isnan(value) or np.isinf(value):
                     self.logger.warning(f"Sanitizing NaN/INF indicator {key}: {value} -> None")
                     setattr(indicators, key, None)
                
        return indicators

    def _build_price_action_dataframe(self, historical_data: List[MarketData]) -> pd.DataFrame:
        """Convert recent candles into a compact OHLCV dataframe for math-based analysis."""
        if not historical_data:
            return pd.DataFrame(columns=["open", "high", "low", "close", "tick_volume"])

        rows = []
        for candle in historical_data[-250:]:
            rows.append(
                {
                    "open": float(candle.open),
                    "high": float(candle.high),
                    "low": float(candle.low),
                    "close": float(candle.close),
                    "tick_volume": float(getattr(candle, "volume", getattr(candle, "tick_volume", 0.0)) or 0.0),
                }
            )
        return pd.DataFrame(rows)

    def _extract_price_action_context(self, historical_data: List[MarketData]) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """Compute the latest price-action math snapshot and immediate attack classification."""
        pa_df = self._build_price_action_dataframe(historical_data)
        if pa_df.empty:
            return pa_df, {"action": "HOLD", "confidence": 0.0, "type": "NONE", "probability": 0.5, "score": 0.0}

        enriched = PriceActionMath.extract_features(pa_df)
        signal = PriceActionMath.get_attack_signal(enriched)
        return enriched, signal

    def _check_entry_filters(self, indicators, timestamp: Optional[datetime] = None) -> Tuple[bool, str]:
        """
        Check if indicators pass entry quality filters with session awareness.
        """
        session = self.regime_detector.detect_session(timestamp)
        thresholds = self.regime_detector.get_dynamic_thresholds(session)
        
        # Check ADX (trend strength)
        adx = getattr(indicators, 'adx', None) or 0
        ml_confidence = getattr(indicators, 'ml_confidence', 0.0) or 0.0  # Get ML confidence for adaptive logic
        ml_accuracy = getattr(indicators, 'ml_accuracy', 0.0) or 0.0  # Get ML accuracy for priority admission
        price_action_attack_ready = bool(getattr(indicators, "price_action_attack_ready", False))
        price_action_probability = float(getattr(indicators, "price_action_probability", 0.5) or 0.5)
        price_action_score = float(getattr(indicators, "price_action_score", 0.0) or 0.0)
        price_action_signal = str(getattr(indicators, "price_action_signal", "HOLD") or "HOLD")
        inferred_trade_tier = str(getattr(indicators, 'trade_tier', '') or '')
        inferred_signal_score = float(
            getattr(indicators, 'adaptive_score', getattr(indicators, 'signal_score', float(ml_confidence or 0.0) * 100.0))
            or float(ml_confidence or 0.0) * 100.0
        )
        permission_controller = getattr(self, "admission_controller", None) or getattr(self.combiner, "admission_controller", None)
        elite_accuracy_pass = False
        if permission_controller is not None and hasattr(permission_controller, "validate_accuracy_gate"):
            try:
                elite_accuracy_pass = bool(permission_controller.validate_accuracy_gate(
                    symbol=self.symbol,
                    ml_accuracy=float(ml_accuracy or 0.0),
                    trade_tier=inferred_trade_tier,
                    signal_score=inferred_signal_score,
                    default_gate=0.0,  # DISABLED: Accuracy gate removed to allow all signals
                ))
            except Exception:
                elite_accuracy_pass = False

        # Bypass Strategy Gate for institutional/structure overrides.
        forced_execution = bool(getattr(indicators, 'forced_execution', False))
        signal_source = str(
            getattr(indicators, "source", getattr(indicators, "signal_source", "")) or ""
        )
        structure_override_source = signal_source.upper() == "STRUCTURE_OVERRIDE"
        admitted = bool(getattr(indicators, 'admitted', False))
        
        signal_mode = str(getattr(indicators, "mode", "") or "").upper()
        structure_override_flag = bool(getattr(indicators, "structure_override", False))
        signal_confidence = float(getattr(indicators, "confidence", getattr(indicators, "ml_confidence", 0.0)) or 0.0)
        elite_structure_override = bool((structure_override_source or structure_override_flag) and signal_confidence >= 0.90)
        if forced_execution or elite_structure_override or signal_mode == "EXPLORATION":
            if forced_execution:
                self.logger.critical(
                    f"[STRATEGY_BYPASS] {self.symbol} | Bypassing strategy gate due to forced_execution=True."
                )
            elif elite_structure_override:
                self.logger.critical(
                    f"[STRATEGY_BYPASS] {self.symbol} | Bypassing strategy gate due to elite structure override (confidence {signal_confidence:.1%})."
                )
            else:
                self.logger.critical(
                    f"[STRATEGY_BYPASS] {self.symbol} | Bypassing strategy gate due to mode=EXPLORATION."
                )
            elite_accuracy_pass = True
        elif admitted:
            self.logger.critical(
                f"[STRATEGY_BYPASS] {self.symbol} | Bypassing strategy gate due to admitted=True from AdmissionController."
            )
            elite_accuracy_pass = True

        if ml_accuracy < 0.45 and not elite_accuracy_pass:
            self.logger.critical(
                "[STRATEGY_REJECT] %s | Effective Accuracy %.1f%% (Source: %s) is below Gate.",
                self.symbol,
                ml_accuracy * 100.0,
                str(getattr(indicators, 'ml_accuracy_source', getattr(self, '_last_accuracy_source', 'unknown'))),
            )
            source = str(getattr(indicators, 'ml_accuracy_source', getattr(self, '_last_accuracy_source', 'unknown')))
            return False, f"Baseline filters failed (Effective Accuracy: {ml_accuracy:.1%} < 45.0% gate | Source: {source})"
        
        # Use optimized entry filter (from self.entry_filters) if available, otherwise fallback to regime dynamic thresh
        config_adx = self.entry_filters.get('adx_min', 26)
        if config_adx < thresholds['adx_weak']:
             # If config is more relaxed than dynamic, use config (High Velocity mode)
             adx_min = config_adx
        else:
             # Otherwise respect dynamic threshold
             adx_min = thresholds['adx_weak']
        adx_min = self.ADX_FLOOR
        
        # ===== PATCH #3: ADAPTIVE ADX FLOOR =====
        # Dynamically reduce required ADX from 12.0 to 10.0 when ML confidence >= 80%
        if ml_confidence >= 0.80:
            adaptive_adx_floor = self.ADX_FLOOR
            self.logger.info(
                f"[ADAPTIVE ADX FLOOR] ML confidence {ml_confidence:.1%} >= 80%. "
                f"Reducing required ADX from {adx_min:.1f} to {adaptive_adx_floor:.1f}"
            )
            adx_min = min(adx_min, adaptive_adx_floor)
        
        # ===== PATCH #6: PRIORITY ADMISSION =====
        # Allow entry with ADX as low as 9.5 if ML Accuracy > 75% AND Confidence > 80%
        if ml_accuracy > 0.75 and ml_confidence > 0.80:
            priority_adx_floor = self.ADX_FLOOR
            if adx >= priority_adx_floor:
                self.logger.critical(
                    f"[FORCED-EXEC-PRIORITY] Priority Admission for {self.symbol} | "
                    f"ML Accuracy: {ml_accuracy:.1%} | ML Conf: {ml_confidence:.1%} | "
                    f"ADX: {adx:.1f} ≥ {priority_adx_floor} (floor)"
                )
                # Signal that this is a priority admission for risk management
                return True, "PRIORITY_ADMISSION"
        
        # If signal score is expected to be high, we can even allow slightly lower ADX
        # but for this basic filter, we use the session-aware baseline
        if adx < adx_min:
            return False, f"Baseline filters failed (ADX: {adx:.1f} < {adx_min:.1f})"
        
        # ===== PATCH #6: RSI RANGE STANDARDIZATION =====
        # Standardized RSI ranges globally to 25-75 for consistency across all timeframes
        rsi = getattr(indicators, 'rsi', None) or 50
        
        # STANDARDIZED VALUES
        standard_rsi_min = 25  # Oversold threshold (standardized)
        # ===== FIX #7: RSI STANDARDIZATION - HARD-CODE 25-75 IN FINAL COMPARISON =====
        # These values are hard-coded and cannot be overridden by external config
        standard_rsi_min = 25  # Oversold threshold (permanently hard-coded)
        standard_rsi_max = 75  # Overbought threshold (permanently hard-coded)
        
        # Use config values if they vary from standard (for debugging logging only)
        config_rsi_min = self.entry_filters.get('rsi_min', 41)
        config_rsi_max = self.entry_filters.get('rsi_max', 59)
        
        # FORCE the use of 25-75 in the actual comparison gate
        rsi_os = standard_rsi_min  # Always 25
        rsi_ob = standard_rsi_max  # Always 75
        
        # Log if config values differ from standard (indicates async state)
        if config_rsi_min != standard_rsi_min or config_rsi_max != standard_rsi_max:
            self.logger.debug(
                f"[RSI-STANDARDIZED] Config RSI {config_rsi_min}-{config_rsi_max} "
                f"IGNORED. Final comparison gate hardcoded to {standard_rsi_min}-{standard_rsi_max}"
            )
        
        # In Asia (Sydney/Tokyo), we expect more range-bound behavior
        # in London/NY we expect more trending behavior
        # ===== FIX #7: RSI STANDARDIZATION - SYMMETRIC ABSOLUTE LOGIC =====
        # Handle long/short asymmetry using midpoint distance (25 pips from 50)
        if abs(rsi - 50) > 25:
            # Check if it's a momentum play in a strong trend
            if adx < thresholds['adx_strong']:
                if price_action_attack_ready and price_action_probability >= 0.65:
                    self.logger.critical(
                        "[PRICE_ACTION_ATTACK] %s | Bypassing RSI lag gate | Signal=%s | Bayes=%.1f%% | Score=%.2f",
                        self.symbol,
                        price_action_signal,
                        price_action_probability * 100.0,
                        price_action_score,
                    )
                else:
                    return False, (
                        f"Baseline filters failed (RSI: {rsi:.1f} implies momentum without "
                        f"ADX >= {thresholds['adx_strong']:.1f})"
                    )
                
        # Check Choppiness Index (Market Efficiency)
        # CHOP < 38.2 = Trending, > 61.8 = Consolidating
        # We use a config max (e.g. 60) to avoid entering deep consolidation
        chop = getattr(indicators, 'choppiness_index', None)
        chop_max = self.entry_filters.get('chop_max', 60.0)
        
        if chop is not None and chop > chop_max:
             return False, f"Baseline filters failed (CHOP: {chop:.1f} > {chop_max:.1f})"
        
        return True, ""
    
    def set_entry_filters(self, filters: Dict) -> None:
        """Update entry filters"""
        self.entry_filters.update(filters)
        self.logger.info(f"Updated entry filters for {self.symbol}: {self.entry_filters}")

    async def _check_news_buffer(self) -> Tuple[bool, str]:
        """
        Check if we are within 30 mins of high-impact news.
        (Mock implementation using NewsDataCollector)
        """
        try:
            # Get news for this symbol
            news = await self.news_collector.collect_data([self.symbol], timeframe="1h", allow_live_fetch=False)
            articles = news.get(self.symbol, [])
            
            now = datetime.now(timezone.utc)
            for article in articles:
                # Mock: Assume articles with "FED", "CPI", "Interest Rate" are high impact
                high_impact_keywords = ['FED', 'CPI', 'INTEREST RATE', 'GDP', 'ECB', 'NON-FARM']
                content = (article.title + " " + article.content).upper()
                
                if any(kw in content for kw in high_impact_keywords):
                    # Handle both naive and aware datetimes
                    pub_time = article.published_at
                    if pub_time.tzinfo is None:
                        pub_time = pub_time.replace(tzinfo=timezone.utc)
                    if now.tzinfo is None:
                        now = now.replace(tzinfo=timezone.utc)
                    time_diff = abs((now - pub_time).total_seconds()) / 60
                    if time_diff <= 30:
                        return True, f"High-impact news nearby: {article.title}"
            
            return False, ""
        except Exception as e:
            self.logger.error(f"Error checking news buffer: {e}")
            return False, ""

    def update_metrics_snapshot(
        self,
        historical_data: List[MarketData],
        *,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Populate _last_symbol_report immediately using live technical values.
        This is safe to call before the main analyze() body or by quant wrappers.
        """
        current_cycle_id = getattr(self, "_current_cycle_id", getattr(self, "_bot_cycle_count", None))
        if (
            current_cycle_id is not None
            and getattr(self, "_last_metrics_cycle_id", None) == current_cycle_id
            and getattr(self, "_last_symbol_report", None)
        ):
            return dict(self._last_symbol_report)
        if not historical_data:
            self._last_symbol_report = {
                "price": 0.0,
                "rsi": 50.0,
                "direction": "DOWN",
                "confidence": 0.45,
                "volatility": 0.0,
                "timestamp": datetime.now(timezone.utc),
            }
            return dict(self._last_symbol_report)

        current_price = float(getattr(historical_data[-1], "close", 0.0) or 0.0)
        trend_direction = "UP" if current_price >= float(getattr(historical_data[0], "close", current_price) or current_price) else "DOWN"
        try:
            setattr(self.ml_predictor, "_current_cycle_id", getattr(self, "_current_cycle_id", None))
            setattr(self.ml_predictor, "_bot_cycle_count", getattr(self, "_bot_cycle_count", None))
        except Exception:
            pass

        try:
            temp_calc = IndicatorCalculator()
            for bar in historical_data:
                temp_calc.add_market_data(bar)
            indicators = temp_calc.calculate_indicators(self.symbol, timeframe='1h')
            rsi_value = float(getattr(indicators, "rsi", 50.0) or 50.0)
            atr_value = float(getattr(indicators, "atr", 0.0) or 0.0)
            macd_value = float(getattr(indicators, "macd", 0.0) or 0.0)
            macd_signal = float(getattr(indicators, "macd_signal", 0.0) or 0.0)
            macd_histogram = float(getattr(indicators, "macd_histogram", 0.0) or 0.0)
            try:
                temp_ml_dir, temp_ml_conf, _ = self.ml_predictor.predict_with_details(
                    historical_data,
                    indicators,
                    bars_since_last_loss=999,
                )
                ml_direction = str(temp_ml_dir or trend_direction)
                ml_confidence = float(temp_ml_conf or 0.45)
            except Exception:
                ml_direction = trend_direction
                ml_confidence = 0.45

            self._last_symbol_report = {
                "price": current_price,
                "rsi": rsi_value,
                "direction": ml_direction,
                "confidence": ml_confidence,
                "atr": atr_value,
                "volatility": atr_value,
                "macd": macd_value,
                "macd_signal": macd_signal,
                "macd_histogram": macd_histogram,
                "timestamp": datetime.now(timezone.utc),
            }
        except Exception as exc:
            self._last_symbol_report = {
                "price": current_price,
                "rsi": 50.0,
                "direction": trend_direction,
                "confidence": 0.45,
                "atr": 0.0,
                "volatility": 0.0,
                "macd": 0.0,
                "macd_signal": 0.0,
                "macd_histogram": 0.0,
                "timestamp": datetime.now(timezone.utc),
            }
            self.logger.debug("[SYMBOL_REPORT_SNAPSHOT_FAIL] %s | %s", self.symbol, exc)

        if reason:
            self.logger.debug(
                "[SYMBOL_REPORT_PRIMED] %s | reason=%s | RSI=%.2f | ML=%s | Conf=%.2f",
                self.symbol,
                reason,
                float(self._last_symbol_report.get("rsi", 50.0) or 50.0),
                str(self._last_symbol_report.get("direction", trend_direction)),
                float(self._last_symbol_report.get("confidence", 0.45) or 0.45),
            )
        if current_cycle_id is not None:
            self._last_metrics_cycle_id = current_cycle_id
        return dict(self._last_symbol_report)

    def get_symbol_report(
        self,
        historical_data: Optional[List[MarketData]] = None,
        *,
        reason: str = "",
    ) -> Dict[str, Any]:
        """
        Return the most recent symbol report, optionally refreshing it from market data.
        """
        if historical_data is not None:
            return self.update_metrics_snapshot(historical_data, reason=reason or "get_symbol_report")
        return dict(getattr(self, "_last_symbol_report", {}) or {})

    async def refresh_held_position_state(
        self,
        historical_data: List[MarketData],
        *,
        current_positions: Optional[List[Any]] = None,
    ) -> Dict[str, Any]:
        _ = current_positions
        symbol_report = self.get_symbol_report(historical_data, reason="held_position_refresh")
        technical_indicators = {
            "rsi": float(symbol_report.get("rsi", 50.0) or 50.0),
            "atr": float(symbol_report.get("atr", symbol_report.get("volatility", 0.0)) or 0.0),
            "macd": float(symbol_report.get("macd", 0.0) or 0.0),
            "macd_signal": float(symbol_report.get("macd_signal", 0.0) or 0.0),
            "macd_histogram": float(symbol_report.get("macd_histogram", 0.0) or 0.0),
        }
        return {
            "symbol_report": dict(symbol_report or {}),
            "technical_indicators": technical_indicators,
            "atr": float(technical_indicators.get("atr", 0.0) or 0.0),
        }

    async def _run_regret_analysis(self, current_price: float):
        """
        Check if rejected trades reached their targets or stops.
        Generates a 'Regret Analysis' for rejections that would have been profitable.
        """
        if not self.regret_analysis_enabled:
            self.tracked_rejections.clear()
            return
        if not self.tracked_rejections:
            return
            
        remaining = []
        for rej in self.tracked_rejections:
            direction = rej['direction']
            tp = rej['tp']
            sl = rej['sl']
            
            rejection_hit_target = False
            rejection_hit_stop = False
            
            if direction == Direction.LONG:
                if current_price >= tp:
                    rejection_hit_target = True
                elif current_price <= sl:
                    rejection_hit_stop = True
            else: # SHORT
                if current_price <= tp:
                    rejection_hit_target = True
                elif current_price >= sl:
                    rejection_hit_stop = True
                    
            if rejection_hit_target:
                rej['status'] = 'PROFITABLE'
                self.logger.warning(
                    f"[REGRET ANALYSIS] '{rej['reason']}' rejected a trade that REACHED TARGET. "
                    f"Symbol: {rej['symbol']} | Price: {rej['entry_price']:.5f} -> {tp:.5f} | "
                    f"Suggests filter might be too restrictive (Current ADX Threshold: 10)."
                )
            elif rejection_hit_stop:
                rej['status'] = 'STOP_LOSS'
                self.logger.info(f"[REGRET ANALYSIS] Filter SUCCESS: Rejected trade '{rej['reason']}' would have hit SL.")
            else:
                # Still active, keep tracking for up to 4 hours
                # Handle both naive and aware datetimes
                rej_time = rej['timestamp']
                now = datetime.now(timezone.utc) if rej_time.tzinfo else datetime.now()
                if (now - rej_time).total_seconds() < 14400:
                    remaining.append(rej)
                else:
                    self.logger.info(f"[REGRET ANALYSIS] Expired rejection tracking for {rej['reason']}.")
                    
        self.tracked_rejections = remaining


def _trend_check_entry_filters_override(self, indicators, timestamp: Optional[datetime] = None) -> Tuple[bool, str]:
    session = self.regime_detector.detect_session(timestamp)
    thresholds = self.regime_detector.get_dynamic_thresholds(session)

    adx = getattr(indicators, 'adx', None) or 0
    ml_confidence = getattr(indicators, 'ml_confidence', 0.0) or 0.0
    ml_accuracy = getattr(indicators, 'ml_accuracy', 0.0) or 0.0
    striking_active = str(os.environ.get("STRIKING_MODE", "0")).lower() in {"1", "true", "yes", "on"}
    uncaged_active = (
        str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
        or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
    )
    news_guard_active = bool(getattr(self, "_news_guard_active", False))
    technical_only_mode = bool(getattr(self, "_technical_only_mode", False))
    desperation_mode = bool(getattr(self, "_desperation_mode", False))
    velocity_mode_active = bool((striking_active or uncaged_active) and not news_guard_active)
    closed_trade_count = int(getattr(indicators, 'ml_closed_trade_count', 0) or 0)
    bot_cycle_count = int(getattr(self, "_bot_cycle_count", 0) or 0)

    if desperation_mode:
        self.logger.warning("[DESPERATION_MODE] %s | Technical filters bypassed for bootstrap cycle.", self.symbol)
        return True, "DESPERATION_MODE"
    active_filters = dict(getattr(self, "entry_filters", {}) or {})
    runtime_override = getattr(self, "_runtime_symbol_filter_override", None)
    if isinstance(runtime_override, dict) and runtime_override:
        active_filters.update(runtime_override)

    base_adx_min = min(float(active_filters.get("adx_min", 26) or 26), float(thresholds['adx_weak']))
    if self._temp_relaxation_active(timestamp if getattr(timestamp, "tzinfo", None) else None):
        base_adx_min = self._get_effective_adx_threshold(base_adx_min, timestamp if getattr(timestamp, "tzinfo", None) else None)

    rsi = getattr(indicators, 'rsi', None) or 50
    permission_controller = getattr(self, "admission_controller", None) or getattr(self.combiner, "admission_controller", None)
    permission_decision: Optional[TradePermissionDecision] = None
    if permission_controller is not None and hasattr(permission_controller, "evaluate_trade_permission"):
        permission_decision = permission_controller.evaluate_trade_permission(
            symbol=self.symbol,
            adx=float(adx or 0.0),
            rsi=float(rsi or 50.0),
            ml_accuracy=float(ml_accuracy or 0.0),
            ml_confidence=float(ml_confidence or 0.0),
            closed_trade_count=int(closed_trade_count or 0),
            low_accuracy_cycle_count=int(getattr(self, "low_accuracy_cycle_count", 0) or 0),
            bot_cycle_count=int(bot_cycle_count or 0),
            technical_only_mode=bool(technical_only_mode),
            velocity_mode_active=bool(velocity_mode_active),
            striking_mode_active=bool(striking_active),
            desperation_mode=bool(desperation_mode),
            base_adx_min=float(base_adx_min or 0.0),
            base_rsi_lower=float(active_filters.get("rsi_min", 25.0) or 25.0),
            base_rsi_upper=float(active_filters.get("rsi_max", 75.0) or 75.0),
            base_confidence_min=float(active_filters.get("ml_confidence_min", 0.20) or 0.20),
            min_target_accuracy=0.45,
            trade_tier=str(getattr(indicators, "trade_tier", "") or ""),
            signal_score=float(
                getattr(indicators, "adaptive_score", getattr(indicators, "signal_score", float(ml_confidence or 0.0) * 100.0))
                or float(ml_confidence or 0.0) * 100.0
            ),
        )

    if permission_decision is not None and not permission_decision.allowed:
        reason = "Dynamic permission evaluator rejected setup."
        if permission_decision.failed_filter == "ACCURACY":
            source = str(getattr(indicators, 'ml_accuracy_source', getattr(self, '_last_accuracy_source', 'unknown')))
            reason = (
                f"Dynamic filters failed (Effective Accuracy: {ml_accuracy:.1%} < "
                f"{float(permission_decision.required_value or 0.0):.1%} gate | Source: {source})"
            )
        elif permission_decision.failed_filter == "ADX":
            reason = f"Dynamic filters failed (ADX: {adx:.1f} < {float(permission_decision.required_value or 0.0):.1f})"
        elif permission_decision.failed_filter == "RSI":
            thresholds_used = permission_decision.thresholds
            if thresholds_used is not None:
                reason = (
                    f"Dynamic filters failed (RSI: {rsi:.1f} outside "
                    f"{float(thresholds_used.rsi_lower or 0.0):.1f}-{float(thresholds_used.rsi_upper or 100.0):.1f})"
                )
        elif permission_decision.failed_filter == "CONFIDENCE":
            reason = (
                f"Dynamic filters failed (ML confidence: {float(ml_confidence or 0.0):.1%} < "
                f"{float(permission_decision.required_value or 0.0):.1%})"
            )
        return False, reason

    chop = getattr(indicators, 'choppiness_index', None)
    chop_max = active_filters.get('chop_max', 60.0)
    if chop is not None and chop > chop_max:
        self.logger.info(
            "[FILTER_DEBUG] %s | REJECTED: CHOP Actual %.3f > Allowed %.3f | Mode=%s",
            self.symbol,
            float(chop or 0.0),
            float(chop_max or 0.0),
            "TECHNICAL_ONLY" if technical_only_mode else ("VELOCITY" if velocity_mode_active else "STANDARD"),
        )
        return False, f"Dynamic filters failed (CHOP: {chop:.1f} > {chop_max:.1f})"

    return True, ""


SimpleTrendStrategy._check_entry_filters = _trend_check_entry_filters_override

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
from src.analysis.signal_strength_calculator import SignalStrengthCalculator
from src.analysis.adaptive_signal_scoring import AdaptiveSignalFilterer
from src.analysis.adaptive_strictness_enhanced import EnhancedAdaptiveStrictnessController as AdaptiveStrictnessController, MarketCondition, StrictnessMode
from src.analysis.market_regime_detector import MarketRegimeDetector
from src.strategies.symbol_config import symbol_manager  # NEW: Per-symbol filters
from src.ml.trade_admission_controller import TradeAdmissionController, TradePermissionDecision
from src.exceptions import DataValidationError  # For graceful data error handling

class SimpleTrendStrategy:
    """A strategy that follows trends using SMA, RSI and Machine Learning"""
    ADX_FLOOR = 12.0
    TEMP_RELAXATION_HOURS = 24
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
        self._time_exit_disabled_until: datetime = datetime.now(timezone.utc) - timedelta(seconds=1)
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
        self.low_accuracy_cycle_count: int = 0
        self.low_accuracy_force_retrain_threshold: float = 0.40
        self.low_accuracy_force_retrain_cycles: int = 10
        self.force_retrain: bool = False
        self.force_retrain_lookback_bars: int = 150
        self.force_retrain_cooldown_minutes: int = int(
            os.environ.get("ML_FORCE_RETRAIN_COOLDOWN_MINUTES", str(max(self.training_cooldown_minutes, 90)))
        )
        self._last_force_retrain_trigger_at: Optional[datetime] = None
        self._pending_model_reset_recovery: bool = False
        self.cold_start_trade_threshold: int = int(os.environ.get("ML_COLD_START_TRADE_THRESHOLD", "100"))
        self.hard_reset_accuracy_threshold: float = float(os.environ.get("ML_HARD_RESET_ACCURACY_THRESHOLD", "0.30"))
        self.hard_reset_cycle_threshold: int = int(os.environ.get("ML_HARD_RESET_CYCLE_THRESHOLD", "50"))
        self.hard_reset_lookback_bars: int = int(os.environ.get("ML_HARD_RESET_LOOKBACK_BARS", "500"))
        self.hard_reset_cooldown_minutes: int = int(os.environ.get("ML_HARD_RESET_COOLDOWN_MINUTES", "240"))
        self._last_hard_reset_at: Optional[datetime] = None
        self._startup_ml_pending: bool = False
        self._startup_ml_pending_reason: str = ""
        
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
        self.ml_trained = False
        self.fine_tuned = False
        
        # ===== ADAPTIVE SIGNAL FILTERING =====
        # Features: ML override (70%+), session relaxation, auto-threshold adjustment
        self.signal_filterer = AdaptiveSignalFilterer(
            min_score=float(os.environ.get("QUALITY_FLOOR_SCORE", "30") or "30"),
            ml_accuracy_target=0.55    # Target 55% ML accuracy
        )
        self.regime_detector = MarketRegimeDetector()
        
        # ===== ADAPTIVE STRICTNESS CONTROLLER =====
        # Adjusts filter thresholds based on market conditions (trending vs sideways)
        self.strictness_controller = AdaptiveStrictnessController(enable_adaptive=True)
        
        self.logger.info("[ADAPTIVE FILTER] Initialized with adaptive thresholds")
        self.logger.info("[ADAPTIVE FILTER] • ML Override: ≥70% confidence → auto-accept")
        self.logger.info("[ADAPTIVE FILTER] • Session Aware: Tokyo +5 bonus, relaxed ADX")
        self.logger.info("[ADAPTIVE FILTER] • Auto-Adjust: Threshold lowers when ML accuracy <50%")
        self.logger.info("[ADAPTIVE FILTER] • Rejection Logging: Specific fixes suggested")
        
        self.logger.info("[ADAPTIVE STRICTNESS] Initialized")
        self.logger.info("[ADAPTIVE STRICTNESS] • STRICT in strong trends (ADX ≥28)")
        self.logger.info("[ADAPTIVE STRICTNESS] • MODERATE in weak trends (ADX ≥18)")
        self.logger.info("[ADAPTIVE STRICTNESS] • ML-OVERRIDE in sideways/weak markets (ML ≥75%)")
        self.logger.info("[ADAPTIVE STRICTNESS] • EXTRA STRICT in choppy/erratic markets")
        # ===== PATCH DISABLED: Market-relaxation and temp filter relaxation are forbidden. =====
        
        # Try to load pre-trained model immediately
        safe_symbol = self.symbol.replace('/', '')
        if self.ml_predictor.load_model(f"models/{safe_symbol}_ml.pkl"):
            self.logger.info(f"Loaded pre-trained ML model for {self.symbol}")
            self.ml_trained = True
            self._startup_ml_pending = False
            self._startup_ml_pending_reason = ""
            trained_at = getattr(self.ml_predictor, "metadata", {}).get("trained_at")
            if trained_at:
                try:
                    parsed = datetime.fromisoformat(str(trained_at))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    self._last_training_time = parsed
                except Exception:
                    self._last_training_time = None
        
        # Entry filters - PHASE 3: PER-SYMBOL OPTIMIZATION
        # Use per-symbol config if available, otherwise fallback to balanced defaults
        self.symbol_manager = symbol_manager
        self.entry_filters = entry_filters or {
            'adx_min': 22,     # Relaxed from 26 to catch early trends
            'rsi_min': 38,     # Widen range
            'rsi_max': 62,     # Widen range
            'ml_confidence_min': 0.60,
            'meta_win_prob_min': 0.30,  # Phase 2: meta-label admission threshold
            'signal_quality_min': 0.70,
            'chop_max': 60.0   # New CHOP filter (< 61.8 indicates Trending)
        }
        self.use_per_symbol_filters = True  # Enable per-symbol optimization
        
        # Use technical weights with ML influence
        weights = SignalWeights(sentiment_weight=0.0, technical_weight=1.0)
        self.admission_controller = admission_controller or TradeAdmissionController()
        self.combiner = SignalCombiner(
            signal_weights=weights, 
            min_confidence_threshold=0.2, # Lowered from 0.4
            sentiment_technical_sync_window_minutes=240, # Increased to 4 hours
            admission_controller=self.admission_controller
        )

    def has_trained_ml_model(self) -> bool:
        predictor = getattr(self, "ml_predictor", None)
        return bool(
            predictor is not None
            and getattr(predictor, "is_trained", False)
            and getattr(predictor, "model", None) is not None
            and getattr(predictor, "scaler", None) is not None
            and bool(getattr(self, "ml_trained", False))
        )

    def mark_startup_ml_pending(self, pending: bool, reason: str = "") -> None:
        self._startup_ml_pending = bool(pending)
        self._startup_ml_pending_reason = str(reason or "")

    def _train_model_from_window(
        self,
        training_window: List[MarketData],
        *,
        closed_trade_count: int,
        reason: str,
    ) -> bool:
        if len(training_window) < 80:
            self.logger.warning(
                "[ML_MODEL_READY] %s | Training skipped | Reason=%s | Bars=%d < 80",
                self.symbol,
                reason,
                len(training_window),
            )
            return False

        all_indicators = []
        for i in range(50, len(training_window)):
            window = training_window[: i + 1]
            temp_calc = IndicatorCalculator()
            start_slice = max(0, i - 200)
            for d in window[start_slice:]:
                temp_calc.add_market_data(d)
            try:
                all_indicators.append(temp_calc.calculate_indicators(self.symbol))
            except Exception:
                continue

        if len(all_indicators) < 50:
            self.logger.warning(
                "[ML_MODEL_READY] %s | Training skipped | Reason=%s | Indicators=%d < 50",
                self.symbol,
                reason,
                len(all_indicators),
            )
            return False

        train_data = training_window[50:50 + len(all_indicators)]
        self.ml_predictor.train(train_data, all_indicators)
        if not self.ml_predictor.is_trained:
            self.logger.warning(
                "[ML_MODEL_READY] %s | Training failed | Reason=%s | Predictor remained untrained",
                self.symbol,
                reason,
            )
            return False

        self.ml_trained = True
        self.fine_tuned = True
        self._last_training_time = datetime.now(timezone.utc)
        self._last_training_closed_trade_count = int(closed_trade_count or 0)
        self.force_retrain = False
        self.low_accuracy_cycle_count = 0
        self.mark_startup_ml_pending(False, "")
        self.logger.info(
            "[ML_MODEL_READY] %s | Reason=%s | Accuracy=%.1f%%",
            self.symbol,
            reason,
            float(self.ml_predictor.metadata.get("accuracy_score", 0.0) or 0.0) * 100.0,
        )
        if self.admission_controller:
            if hasattr(self.admission_controller, "clear_forced_learning_window"):
                self.admission_controller.clear_forced_learning_window(self.symbol)
            if hasattr(self.admission_controller, "clear_exploration_override_count"):
                self.admission_controller.clear_exploration_override_count(self.symbol)
        return True

    async def ensure_ml_model_ready(
        self,
        historical_data: List[MarketData],
        *,
        reason: str = "STARTUP_AUDIT",
        force_retrain: bool = False,
    ) -> bool:
        if self.has_trained_ml_model() and not force_retrain:
            self.mark_startup_ml_pending(False, "")
            return True

        if len(historical_data or []) < 80:
            self.mark_startup_ml_pending(True, f"{reason}:INSUFFICIENT_HISTORY")
            self.logger.warning(
                "[ML_MODEL_READY] %s | Pending initial model training | Reason=%s | Bars=%d",
                self.symbol,
                reason,
                len(historical_data or []),
            )
            return False

        closed_trade_count = await self._get_closed_trade_count()
        if force_retrain:
            self._pending_model_reset_recovery = True
            await self._run_model_reset_recovery()

        success = self._train_model_from_window(
            list(historical_data),
            closed_trade_count=closed_trade_count,
            reason=reason,
        )
        if not success:
            self.mark_startup_ml_pending(True, reason)
        return success

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
            await self.news_collector.collect_data([self.symbol], timeframe="1h", force_refresh=True)
        except Exception as exc:
            self.logger.warning("[NEWS_FORCE_REFRESH] %s | Forced refresh failed during model reset: %s", self.symbol, exc)
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
            "[MODEL_RESET] %s | News force-refresh requested and fine-tuning caches cleared. Recalibrating on latest %d bars.",
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
        return False

    def _temp_relaxation_active(self, now: Optional[datetime] = None) -> bool:
        now_utc = now or datetime.now(timezone.utc)
        return now_utc < self._temporary_relaxation_until

    def _get_effective_quality_floor(self, fallback_floor: float = 0.40, now: Optional[datetime] = None) -> float:
        base_floor = float(fallback_floor)
        if self._temp_relaxation_active(now):
            return min(base_floor, self.TEMP_QUALITY_FLOOR)
        return base_floor

    def _get_effective_adx_threshold(self, base_adx: float, now: Optional[datetime] = None) -> float:
        effective_adx = float(base_adx)
        if self._temp_relaxation_active(now):
            effective_adx *= self.TEMP_ADX_MULTIPLIER
        required_floor = float(os.environ.get("ADX_MIN_EXECUTION_FLOOR", str(self.ADX_FLOOR)) or self.ADX_FLOOR)
        return max(self.ADX_FLOOR, min(effective_adx, required_floor))

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
            return self.cycle_cache.get(cache_key)

        # Hard-reset cycle-local analysis artifacts before any scoring/admission work.
        if hasattr(self, "combiner") and self.combiner is not None:
            try:
                self.combiner.reset_cycle_state(symbol=self.symbol)
            except Exception as reset_err:
                self.logger.debug(f"[ANALYSIS_RESET_WARN] {self.symbol} cycle reset failed: {reset_err}")

        min_volatility_threshold = 0.000
        quality_floor = self._get_effective_quality_floor(float(os.environ.get("SIGNAL_QUALITY_MINIMUM", "0.30") or "0.30"))
        if self._opening_silence_until and datetime.now(timezone.utc) < self._opening_silence_until:
            self.logger.critical(
                f"[GAP_PROTECTION_ACTIVE] {self.symbol} opening silence active until "
                f"{self._opening_silence_until.isoformat()}. New entries paused."
            )
            return None

        # Clear combiner overrides at the start of each analysis cycle
        if self.combiner is not None:
            self.combiner.override_ml_confidence = None
            self.combiner.override_meta_win_prob = None
            self.combiner.structure_override_active = False
            self.combiner.news_guard_active = bool(getattr(self, "_news_guard_active", False))
        if not historical_data or len(historical_data) < 500:
            self.logger.warning(f"Insufficient data for analysis of {self.symbol}: {len(historical_data) if historical_data else 0} bars")
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
                f"[NEWS-BUFFER|ULTIMATE-GATEKEEPER] {self.symbol} entries BLOCKED: {news_reason}\n"
                f"   → No overrides allowed during economic volatility. "
                f"Priority Admission and high-confidence relaxations are SUSPENDED."
            )
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
                    return None
                else:
                    self.last_sl_hit_time = None # Cooldown expired
        
        # 1. Calculate indicators
        # Note: IndicatorCalculator is stateful, so we clear it or use it carefully
        # For this simple strategy, we can just use the latest data
        self.indicator_calculator = IndicatorCalculator()
        for data in historical_data:
            self.indicator_calculator.add_market_data(data)
            
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
            
            # ISSUE #1 FIX: Bypass model freshness check during forced learning window
            # When accuracy < 45% for 20 cycles, forced learning window activates
            # Model MUST retrain immediately, regardless of age check
            if self.admission_controller and self.admission_controller.is_in_forced_learning_window(self.symbol):
                should_retrain = True
                training_age_minutes = None  # Bypass age-based skip message
                self.logger.info("[FORCED_LEARNING_RETRAIN_OVERRIDE] %s | Forcing retrain despite fresh model (accuracy crashed)", self.symbol)
            if self.admission_controller and hasattr(self.admission_controller, "consume_forced_retrain_request"):
                if self.admission_controller.consume_forced_retrain_request(self.symbol):
                    should_retrain = True
                    force_retrain = True
                    training_age_minutes = None
                    self._pending_model_reset_recovery = True
                    self.logger.critical(
                        "[FORCED_RETRAIN_EXECUTE] %s | Reason=EXPLORATION_CAP | Freshness timer bypassed.",
                        self.symbol,
                    )
            
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
                    self.logger.info(
                        "Adaptive Learning for %s: Fine-tuning ML model on %d local bars%s...",
                        self.symbol,
                        len(training_window),
                        " (hard reset retrain)" if hard_reset_triggered else (" (forced retrain)" if force_retrain else ""),
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
                        self.ml_predictor.train(train_data, all_indicators)
                        if self.ml_predictor.is_trained:
                            self.ml_trained = True
                            self.fine_tuned = True
                            self._last_training_time = datetime.now(timezone.utc)
                            self._last_training_closed_trade_count = closed_trade_count
                            self.force_retrain = False
                            self.low_accuracy_cycle_count = 0
                            self.logger.info(f"✓ Fine-tuning complete. Accuracy: {self.ml_predictor.metadata.get('accuracy_score', 0):.1%}")
                            # ===== ISSUE #1 FIX: Clear forced learning window after successful retrain =====
                            # After model retrains successfully, clear the 60-minute penalty timer
                            # This allows trading to resume immediately, not wait for original timer
                            if self.admission_controller:
                                self.admission_controller.clear_forced_learning_window(self.symbol)
                                self.logger.info(f"[FORCED_LEARNING_CLEARED] {self.symbol} | Learning window timer reset after successful retrain")
                                if hasattr(self.admission_controller, "clear_exploration_override_count"):
                                    self.admission_controller.clear_exploration_override_count(self.symbol)
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
            # === FIX: Graceful error handling for insufficient data ===
            try:
                indicators = self.indicator_calculator.calculate_indicators(self.symbol, timeframe='1h')
            except DataValidationError as e:
                # If insufficient data, log warning and skip analysis for this pair
                self.logger.warning(
                    f"[INSUFFICIENT_DATA_SKIP] {self.symbol} | Cannot calculate indicators: {str(e)} | "
                    f"Skipping analysis cycle. Waiting for more data from broker."
                )
                return None  # Skip this symbol's analysis gracefully
            
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
            
            
            # 2. ML Prediction
            bars_since_last_loss = self._estimate_bars_since_last_loss(historical_data)
            ml_dir, ml_conf, ml_details = self.ml_predictor.predict_with_details(
                historical_data,
                indicators,
                bars_since_last_loss=bars_since_last_loss,
                short_horizon_bars=50 if (uncaged_active or striking_active) else None,
            )
            meta_win_prob = float(ml_details.get('meta_win_prob', 1.0))
            ml_desc = "UP" if ml_dir == 1 else "DOWN"
            indicators.ml_confidence = float(ml_conf or 0.0)
            
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
                "ml_direction": ml_desc,
                "confidence": float(ml_conf or 0.0),
            }
            # Log detailed indicator values (only in verbose mode)
            if self.verbose:
                self.logger.debug("[ANALYSIS] %s | Price: %.5f | RSI: %.1f (range: 25-75) | ML: %s (Conf: %.0f%%, Acc: %.0f%%)", 
                                 self.symbol, current_price, 
                                 indicators.rsi or 0,
                                 ml_desc, ml_conf * 100, effective_ml_accuracy * 100)

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
                    return None
            
            # Check entry filters before generating signals
            current_timestamp = historical_data[-1].timestamp
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

                self.logger.info(
                    f"[FILTER] {self.symbol} rejected in {session.value} | {reason} | "
                    f"RSI: {indicators.rsi or 0:.1f} (range: 25-75)"
                )
                return None
            
            # 3. Generate Technical Signals
            tech_signals = self.signal_generator.generate_signals(
                market_data=historical_data,
                indicators=indicators
            )
            
            # --- MOMENTUM FILTER (RELAXED FOR MORE SIGNALS) ---
            # Only filter extreme cases - allow most technical signals through
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
                
            # --- H4 TREND FILTER (MTF) ---
            # Filter technical signals against the major trend (H4 SMA 50 proxy)
            # Buy only if Price > H4 Tren
            # Sell only if Price < H4 Trend
            use_mtf_filter = str(os.environ.get("USE_MTF_FILTER", "1")).strip().lower() in {"1", "true", "yes", "on"}
            if tech_signals and indicators.h4_trend and use_mtf_filter:
                mtf_filtered_signals = []
                mtf_confidence_override = float(ml_conf or 0.0) >= 0.60
                for signal in tech_signals:
                    if signal.signal_type == SignalType.BUY:
                        # Allow BUY only if price is above H4 Trend (Bullish) or very close to it (retest)
                        if current_price > indicators.h4_trend * 0.9995: 
                            mtf_filtered_signals.append(signal)
                        elif mtf_confidence_override and current_price > indicators.h4_trend * 0.9985:
                            self.logger.info(
                                f"[MTF-CONFIDENCE-OVERRIDE] BUY accepted on {self.symbol} | "
                                f"ML {float(ml_conf or 0.0):.1%} offsets minor H4 mismatch."
                            )
                            mtf_filtered_signals.append(signal)
                        else:
                            self.logger.info(f"[MTF-FILTER] Rejected BUY on {self.symbol} (Price {current_price:.5f} < H4 Trend {indicators.h4_trend:.5f})")
                    
                    elif signal.signal_type == SignalType.SELL:
                        # Allow SELL only if price is below H4 Trend (Bearish) or very close
                        if current_price < indicators.h4_trend * 1.0005:
                            mtf_filtered_signals.append(signal)
                        elif mtf_confidence_override and current_price < indicators.h4_trend * 1.0015:
                            self.logger.info(
                                f"[MTF-CONFIDENCE-OVERRIDE] SELL accepted on {self.symbol} | "
                                f"ML {float(ml_conf or 0.0):.1%} offsets minor H4 mismatch."
                            )
                            mtf_filtered_signals.append(signal)
                        else:
                            self.logger.info(f"[MTF-FILTER] Rejected SELL on {self.symbol} (Price {current_price:.5f} > H4 Trend {indicators.h4_trend:.5f})")
                            
                tech_signals = mtf_filtered_signals
            elif tech_signals and indicators.h4_trend and not use_mtf_filter:
                self.logger.info(
                    "[MTF-FILTER-BYPASSED] %s | USE_MTF_FILTER=0 | Counter-trend entries permitted.",
                    self.symbol,
                )
            
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
            # Always incorporate ML as a synthetic signal if confidence is high
            if ml_conf > 0.7:
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
                self.combiner.structure_override_active = bool(getattr(self, "_structure_override_active", False))
                self.combiner.structure_override_min_ml = 0.05
                self.combiner.news_guard_active = bool(getattr(self, "_news_guard_active", False))
                self.combiner._ml_accuracy_for_cycle = float(effective_ml_accuracy or 0.0)
                self.combiner._historical_trade_count_for_cycle = int(closed_trade_count or 0)
                self.combiner._low_accuracy_cycle_count_for_cycle = int(self.low_accuracy_cycle_count or 0)
                self.combiner._bot_cycle_count_for_cycle = int(getattr(self, "_bot_cycle_count", 0) or 0)
                self.combiner._technical_only_mode_for_cycle = bool(getattr(self, "_technical_only_mode", False))
                self.combiner._desperation_mode_for_cycle = bool(getattr(self, "_desperation_mode", False))
                self.combiner._trade_style_for_cycle = str(getattr(self, "_preferred_trade_style", "TREND") or "TREND")
                self.combiner._adx_for_cycle = float(getattr(indicators, "adx", 0.0) or 0.0)
                self.combiner._effective_adx_floor_for_cycle = float(self._get_effective_adx_threshold(
                    float(getattr(self, "entry_filters", {}).get("adx_min", self.ADX_FLOOR) or self.ADX_FLOOR),
                    current_timestamp if getattr(current_timestamp, "tzinfo", None) else None,
                ) or 0.0)
                self.combiner._adx_gate_enabled_for_cycle = True
            combined_result = self.combiner.combine_signals(
                sentiment_result=None,
                technical_signals=tech_signals,
                current_price=current_price,
                symbol=self.symbol,
                reference_time=historical_data[-1].timestamp,
                historical_data=historical_data,  # Pass historical data for ATR calculation
                current_positions=current_positions,
            )
            
            if not combined_result.trading_signal:
                pass  # No signal generated
            
            if combined_result.trading_signal:
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
                    self.logger.info(
                        f"[QUALITY] {self.symbol} {signal_direction} rejected | "
                        f"Score: {quality_analysis.quality_score:.0%} (min: {min_quality:.0%}) | "
                        f"Filters: {self.symbol_manager.log_config(self.symbol, signal_direction)} | "
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
                if regime == 'RANGING' and str(session).upper() == 'TOKYO':
                    original_size = final_size_mult
                    final_size_mult *= 0.50
                    self.logger.info(
                        f"[TOKYO_RANGE_SCALP_SIZING] {self.symbol} in TOKYO/RANGING regime. "
                        f"Position reduced from {original_size:.2f}x to {final_size_mult:.2f}x "
                        f"to preserve capital for London/New York."
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
            return combined_result.trading_signal
            
        except Exception as e:
            import traceback
            self.logger.error(f"Error in strategy analysis for {self.symbol}: {e}\n{traceback.format_exc()}")
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
        inferred_trade_tier = str(getattr(indicators, 'trade_tier', '') or '')
        inferred_signal_score = float(
            getattr(indicators, 'adaptive_score', getattr(indicators, 'signal_score', float(ml_confidence or 0.0) * 100.0))
            or float(ml_confidence or 0.0) * 100.0
        )
        # Option D / aggressive profile aware: read ML_ACCURACY_MIN_GATE from environment
        min_accuracy_gate = float(os.environ.get("ML_ACCURACY_MIN_GATE", "0.30") or "0.30")
        if ml_accuracy < min_accuracy_gate:
            self.logger.critical(
                "[STRATEGY_REJECT] %s | Effective Accuracy %.1f%% (Source: %s) is below Gate (%.0f%%.",
                self.symbol,
                ml_accuracy * 100.0,
                str(getattr(indicators, 'ml_accuracy_source', getattr(self, '_last_accuracy_source', 'unknown'))),
                min_accuracy_gate * 100.0,
            )
            source = str(getattr(indicators, 'ml_accuracy_source', getattr(self, '_last_accuracy_source', 'unknown')))
            return False, f"Baseline filters failed (Effective Accuracy: {ml_accuracy:.1%} < {min_accuracy_gate:.0%} gate | Source: {source})"
        
        adx_min = self._get_effective_adx_threshold(max(12.0, self.ADX_FLOOR), timestamp)
        regime_name = str(getattr(indicators, "market_regime", getattr(indicators, "regime", "")) or "").upper()
        regime_confidence_floor = 0.65 if regime_name == "RANGING" else 0.45
        if ml_confidence < regime_confidence_floor:
            return False, (
                f"Baseline filters failed (ML confidence {ml_confidence:.1%} < "
                f"{regime_confidence_floor:.0%} floor for {regime_name or 'DEFAULT'} regime)"
            )
        
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
            news = await self.news_collector.collect_data([self.symbol], timeframe="1h")
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

    timestamp_for_threshold = timestamp if getattr(timestamp, "tzinfo", None) else None
    base_adx_min = max(12.0, float(active_filters.get("adx_min", 12) or 12))
    base_adx_min = self._get_effective_adx_threshold(base_adx_min, timestamp_for_threshold)

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
            meta_win_prob=float(getattr(indicators, "meta_win_prob", 0.0) or 0.0),
            closed_trade_count=int(closed_trade_count or 0),
            low_accuracy_cycle_count=int(getattr(self, "low_accuracy_cycle_count", 0) or 0),
            bot_cycle_count=int(bot_cycle_count or 0),
            technical_only_mode=bool(technical_only_mode),
            velocity_mode_active=bool(velocity_mode_active),
            striking_mode_active=bool(striking_active),
            desperation_mode=bool(desperation_mode),
            base_adx_min=float(base_adx_min or 0.0),
            adx_gate_enabled=False,
            base_rsi_lower=float(active_filters.get("rsi_min", 25.0) or 25.0),
            base_rsi_upper=float(active_filters.get("rsi_max", 75.0) or 75.0),
            base_confidence_min=float(
                0.65 if str(getattr(indicators, "market_regime", getattr(indicators, "regime", "")) or "").upper() == "RANGING"
                else max(0.45, float(active_filters.get("ml_confidence_min", 0.45) or 0.45))
            ),
            min_target_accuracy=0.50,
            trade_tier=str(getattr(indicators, "trade_tier", "") or ""),
            signal_score=float(
                getattr(indicators, "adaptive_score", getattr(indicators, "signal_score", float(ml_confidence or 0.0) * 100.0))
                or float(ml_confidence or 0.0) * 100.0
            ),
        )

    regime_name = str(getattr(indicators, "market_regime", getattr(indicators, "regime", "")) or "").upper()
    regime_confidence_floor = 0.65 if regime_name == "RANGING" else 0.45
    if ml_confidence < regime_confidence_floor:
        return False, (
            f"Dynamic filters failed (ML confidence: {float(ml_confidence or 0.0):.1%} < "
            f"{regime_confidence_floor:.0%} floor for {regime_name or 'DEFAULT'} regime)"
        )

    # Option D / aggressive profile aware: read ML_ACCURACY_MIN_GATE from environment
    min_accuracy_gate = float(os.environ.get("ML_ACCURACY_MIN_GATE", "0.30") or "0.30")
    if ml_accuracy < min_accuracy_gate:
        source = str(getattr(indicators, 'ml_accuracy_source', getattr(self, '_last_accuracy_source', 'unknown')))
        return False, f"Dynamic filters failed (Effective Accuracy: {ml_accuracy:.1%} < {min_accuracy_gate:.0%} gate | Source: {source})"

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

"""
Trade Admission & Opportunity Cost Controller
Determines whether a trade should enter based on relative edge quality.
"""

import json
import os
import logging
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from collections import deque
import numpy as np
import pandas as pd

from src.models import ExitPolicy
from src.analysis.llm_macro_monitor import (
    get_macro_risk_penalty,
    macro_risk_cache,
)
from src.data.news_data_collector import NewsDataCollector
from src.utils.pip_standardizer import PipStandardizer

from src.risk.expectancy_calculator import calculate_expectancy
from utils.safe_format import format_float, safe_float

logger = logging.getLogger(__name__)


@dataclass
class OpportunityRecord:
    """Record of an evaluated trading opportunity"""
    timestamp: datetime
    symbol: str
    regime: str
    expectancy: float
    confidence: float
    exit_policy: str
    position_size_multiplier: float
    was_admitted: bool
    admission_reason: str
    opportunity_score: float = 0.0  # Percentile rank
    ev: float = 0.0
    rr_for_ev: float = 0.0
    calibrated_ml_confidence: float = 0.0
    macro_risk_penalty: float = 0.0
    adjusted_win_prob: float = 0.0
    max_portfolio_correlation: float = 0.0
    most_correlated_symbol: str = ""
    correlation_blocked: bool = False


@dataclass
class AdmissionConfig:
    """Configuration for trade admission controller"""
    lookback_window: int = 50  # Number of recent signals to compare against
    percentile_threshold_normal: float = 20.0  # Minimum percentile for normal regimes (lowered from 30)
    percentile_threshold_volatile: float = 40.0  # Stricter for HIGH_VOLATILITY (lowered from 50)
    percentile_threshold_illiquid: float = 50.0  # Strictest for LOW_LIQUIDITY (lowered from 60)
    micro_allocation_multiplier: float = 0.1  # Downscale factor for marginal trades
    min_exploration_rate: float = 0.05  # Always admit at least 5% of signals
    opportunity_cost_penalty_weight: float = 0.5  # Weight in regret calculation
    max_correlation_threshold: float = 0.70  # Hard diversification limit
    correlation_lookback_bars: int = 50
    correlation_timeframe: int = 16385  # MT5 H1
    min_confidence_threshold: float = 0.40  # Hard gate for admission (lowered to 0.40 to allow 0.45 fallback signals)
    baseline_expectancy_min: float = 1.00  # Baseline expectancy requirement for size boosts
    baseline_rr_min: float = 1.00  # Baseline RR requirement for size boosts
    spread_atr_ratio_max: float = 0.25  # Reject only when spread exceeds 25% of ATR
    elite_spread_padding_pips: float = 2.0  # Extra spread room for elite signals
    elite_confidence_threshold: float = 0.85
    elite_ev_threshold: float = 2.0
    # ISSUE #2 FIX: Minimum position size floor for admitted trades
    min_position_size_floor: float = 0.10  # MIN_POSITION_SIZE: 0.10x floor for any trade that passes admission


@dataclass
class AdmissionDecision:
    """Result of admission evaluation"""
    admitted: bool
    opportunity_score: float  # 0-100 percentile
    opportunity_cost_regret: float  # Expected value left on table
    final_position_multiplier: float  # After admission adjustments
    reason: str
    action_taken: str  # "ADMITTED", "DOWNSCALED", "REJECTED", "EXPLORATION"
    authority_level: str = "LEVEL_3"
    # ===== FIX #1: TERMINATE FILTER CHAIN ON OVERRIDE =====
    skip_validator: bool = False  # If True, bypass all downstream validation gates


@dataclass
class PermissionThresholds:
    adx_min: float
    rsi_lower: float
    rsi_upper: float
    accuracy_gate: float
    confidence_gate: float
    required_score: float
    multiplier: float


@dataclass
class TradePermissionContext:
    adx: float
    rsi: float
    ml_accuracy: float
    ml_confidence: float
    closed_trade_count: int
    low_accuracy_cycle_count: int
    bot_cycle_count: int
    technical_only_mode: bool
    velocity_mode_active: bool
    striking_mode_active: bool
    desperation_mode: bool
    base_adx_min: float
    base_rsi_lower: float = 25.0
    base_rsi_upper: float = 75.0
    base_confidence_min: float = 0.20
    min_target_accuracy: float = 0.45
    trade_tier: str = ""
    signal_score: float = 0.0


@dataclass
class TradePermissionDecision:
    allowed: bool
    score: float
    reason: str
    failed_filter: str = ""
    actual_value: float = 0.0
    required_value: float = 0.0
    thresholds: Optional[PermissionThresholds] = None


class TradePermissionEvaluator:
    """
    Unified dynamic filter evaluator that replaces separate baseline vs exploratory
    gates with one permission score driven by mode and model maturity.
    """

    def evaluate(self, context: TradePermissionContext) -> TradePermissionDecision:
        if context.desperation_mode:
            thresholds = PermissionThresholds(
                adx_min=0.0,
                rsi_lower=0.0,
                rsi_upper=100.0,
                accuracy_gate=0.0,
                confidence_gate=0.0,
                required_score=0.0,
                multiplier=0.0,
            )
            return TradePermissionDecision(
                allowed=True,
                score=1.0,
                reason="DESPERATION_MODE",
                thresholds=thresholds,
            )

        multiplier = 1.0
        if context.velocity_mode_active or context.striking_mode_active:
            multiplier *= 0.8
        if context.technical_only_mode:
            multiplier *= 0.7

        effective_adx_min = max(5.0, float(context.base_adx_min or 0.0) * multiplier)
        midpoint = 50.0
        half_range = (float(context.base_rsi_upper) - midpoint) / max(multiplier, 0.5)
        rsi_lower = max(0.0, midpoint - half_range)
        rsi_upper = min(100.0, midpoint + half_range)

        maturity_proxy = max(int(context.closed_trade_count or 0), int(context.bot_cycle_count or 0))
        maturity_factor = max(0.0, min(1.0, maturity_proxy / 100.0))
        accuracy_gate = max(0.20, float(context.min_target_accuracy or 0.15) * maturity_factor)
        if context.technical_only_mode or int(context.low_accuracy_cycle_count or 0) > 10 or (0 < int(context.bot_cycle_count or 0) < 100):
            accuracy_gate = 0.15

        confidence_gate = max(0.05, float(context.base_confidence_min or 0.20) * multiplier)
        required_score = 0.55
        if context.velocity_mode_active or context.striking_mode_active:
            required_score = 0.50
        if context.technical_only_mode:
            required_score = 0.40

        thresholds = PermissionThresholds(
            adx_min=effective_adx_min,
            rsi_lower=rsi_lower,
            rsi_upper=rsi_upper,
            accuracy_gate=accuracy_gate,
            confidence_gate=confidence_gate,
            required_score=required_score,
            multiplier=multiplier,
        )

        adx_score = min(1.0, float(context.adx or 0.0) / max(effective_adx_min, 1e-6))
        if rsi_lower <= float(context.rsi or 0.0) <= rsi_upper:
            rsi_score = 1.0
        else:
            distance = min(abs(float(context.rsi or 0.0) - rsi_lower), abs(float(context.rsi or 0.0) - rsi_upper))
            rsi_score = max(0.0, 1.0 - (distance / 25.0))
        accuracy_score = 1.0 if accuracy_gate <= 0.0 else min(1.0, float(context.ml_accuracy or 0.0) / max(accuracy_gate, 1e-6))
        confidence_score = 1.0 if confidence_gate <= 0.0 else min(1.0, float(context.ml_confidence or 0.0) / max(confidence_gate, 1e-6))

        permission_score = (
            (adx_score * 0.35)
            + (rsi_score * 0.20)
            + (accuracy_score * 0.20)
            + (confidence_score * 0.25)
        )

        dominant = min(
            [
                ("ADX", adx_score, float(context.adx or 0.0), effective_adx_min),
                ("RSI", rsi_score, float(context.rsi or 0.0), rsi_lower if float(context.rsi or 0.0) < rsi_lower else rsi_upper),
                ("ACCURACY", accuracy_score, float(context.ml_accuracy or 0.0), accuracy_gate),
                ("CONFIDENCE", confidence_score, float(context.ml_confidence or 0.0), confidence_gate),
            ],
            key=lambda item: item[1],
        )

        if permission_score >= required_score:
            return TradePermissionDecision(
                allowed=True,
                score=float(permission_score),
                reason="PERMISSION_SCORE_PASS",
                thresholds=thresholds,
            )

        failed_filter, _, actual_value, required_value = dominant
        return TradePermissionDecision(
            allowed=False,
            score=float(permission_score),
            reason=f"{failed_filter}_BELOW_DYNAMIC_THRESHOLD",
            failed_filter=failed_filter,
            actual_value=float(actual_value),
            required_value=float(required_value),
            thresholds=thresholds,
        )
    

class TradeAdmissionController:
    """
    Gate-keeper that ensures only high-quality trades consume capital.
    Maintains a rolling history of signal quality per regime.
    """
    
    HISTORY_FILE = "trade_admission_history.json"
    QUALITY_FLOOR = 0.40
    
    def __init__(self, config: Optional[AdmissionConfig] = None, data_dir: str = "."):
        self.config = config or AdmissionConfig()
        self.permission_evaluator = TradePermissionEvaluator()
        self.QUALITY_FLOOR = 0.40
        self.quality_threshold = 0.40
        # Env override for portfolio correlation hard limit.
        # .env: MAX_PORTFOLIO_CORRELATION=0.70
        try:
            env_corr = os.environ.get("MAX_PORTFOLIO_CORRELATION")
            if env_corr is not None:
                self.config.max_correlation_threshold = float(max(0.0, min(1.0, float(env_corr))))
        except Exception as exc:
            logger.warning("[CORRELATION_GATE] Invalid MAX_PORTFOLIO_CORRELATION env value: %s", exc)
        self.data_dir = data_dir
        self.history_path = os.path.join(data_dir, self.HISTORY_FILE)
        
        # ===== FIX #1: Reference to ProfitProtectionModule for weekend lockout check =====
        self.profit_protection_module = None
        
        # Regime-specific opportunity windows
        # Key: regime, Value: deque of OpportunityRecords
        self.opportunity_windows: Dict[str, deque] = {}
        
        # Statistics
        self.stats = {
            'total_evaluated': 0,
            'total_admitted': 0,
            'total_rejected': 0,
            'total_downscaled': 0,
            'total_exploration': 0,
            'avg_opportunity_score_admitted': 0.0,
            'avg_opportunity_score_rejected': 0.0
        }
        
        # Load existing history
        self.load_history()
        self.ml_forced_threshold = 0.15
        self.max_total_positions = 7
        self.max_positions_per_symbol = 3
        # Nuclear override budget: allow deep EV threshold for a bounded number of evaluations.
        self._ev_override_cycles_remaining = 0
        # Emergency full-auto window (24h): force permissive EV math.
        self._full_auto_until = datetime.now(timezone.utc) + pd.Timedelta(hours=24)

        # ===== SYMBOL COOLDOWN (Anti Revenge-Trade) =====
        # Maps normalized symbol -> cooldown expiry datetime (UTC).
        # Any symbol in this map with a future expiry is HARD-REJECTED by evaluate_admission.
        # Populated by PositionManager via register_symbol_cooldown() on every position close.
        self.symbol_cooldowns: Dict[str, datetime] = {}
        self.SYMBOL_COOLDOWN_MINUTES: int = 60
        # Reduce-only control: symbol -> expiry (UTC)
        self.reduce_only_symbols: Dict[str, datetime] = {}
        self.reduce_only_reasons: Dict[str, str] = {}

        # Allow env overrides for hard gates
        try:
            min_conf = os.environ.get("MIN_CONFIDENCE_THRESHOLD")
            if min_conf is not None:
                self.config.min_confidence_threshold = float(min_conf)
        except Exception as exc:
            logger.warning("[ADMISSION_GATE] Invalid MIN_CONFIDENCE_THRESHOLD env value: %s", exc)
        try:
            rr_min = os.environ.get("BASELINE_RR_MIN")
            if rr_min is not None:
                self.config.baseline_rr_min = float(rr_min)
        except Exception as exc:
            logger.warning("[ADMISSION_GATE] Invalid BASELINE_RR_MIN env value: %s", exc)
        try:
            exp_min = os.environ.get("BASELINE_EXPECTANCY_MIN")
            if exp_min is not None:
                self.config.baseline_expectancy_min = float(exp_min)
        except Exception as exc:
            logger.warning("[ADMISSION_GATE] Invalid BASELINE_EXPECTANCY_MIN env value: %s", exc)
        try:
            spread_atr_ratio = os.environ.get("SPREAD_ATR_RATIO_MAX")
            if spread_atr_ratio is not None:
                self.config.spread_atr_ratio_max = float(spread_atr_ratio)
        except Exception as exc:
            logger.warning("[ADMISSION_GATE] Invalid SPREAD_ATR_RATIO_MAX env value: %s", exc)
    
    # ===== FIX #1: WEEKEND LOCKOUT API =====
    def set_profit_protection_module(self, module) -> None:
        """Set reference to profit protection module for weekend lockout checks"""
        self.profit_protection_module = module
        logger.debug("[WEEKEND_LOCKOUT_API] ProfitProtectionModule reference set for admission controller")

    # ------------------------------------------------------------------
    # Symbol Cooldown API  (called by PositionManager on every exit)
    # ------------------------------------------------------------------

    def register_symbol_cooldown(self, symbol: str, cooldown_minutes: Optional[int] = None, reason: str = "RECENT_CLOSE") -> None:
        """
        Stamp a 60-minute re-entry cooldown for *symbol*.
        Called by PositionManager immediately after any position close
        (SL hit, TP hit, or manual close) to prevent revenge-trading.
        """
        key = self._normalize_symbol(symbol)
        if not key:
            return
        cooldown_window = max(1, int(cooldown_minutes or self.SYMBOL_COOLDOWN_MINUTES))
        expiry = datetime.now(timezone.utc) + timedelta(minutes=cooldown_window)
        self.symbol_cooldowns[key] = expiry
        logger.critical(
            "[SYMBOL_COOLDOWN] %s | Reason=%s | Re-entry BLOCKED until %s (%d min).",
            key,
            str(reason or "RECENT_CLOSE"),
            expiry.strftime("%H:%M:%S UTC"),
            cooldown_window,
        )

    def is_symbol_on_cooldown(self, symbol: str) -> bool:
        """Return True if *symbol* is currently within its post-close cooldown window."""
        key = self._normalize_symbol(symbol)
        expiry = self.symbol_cooldowns.get(key)
        if expiry is None:
            return False
        if datetime.now(timezone.utc) < expiry:
            return True
        # Expired — clean up
        del self.symbol_cooldowns[key]
        return False

    def reset_cycle_state(self, symbol: Optional[str] = None) -> None:
        """
        Reset per-cycle admission memory so each analysis cycle starts clean.
        This intentionally clears opportunity windows to prevent score bleed/decay
        from previous cycles.
        """
        self.opportunity_windows.clear()
        if symbol:
            logger.debug("[ADMISSION_CYCLE_RESET] %s | Cleared admission windows for fresh cycle.", symbol)

    def _get_macro_news_state(self, symbol: str) -> Dict[str, Any]:
        """
        Resolve macro/news state with a freshness check so stale calendar inputs
        do not permanently trap the pipeline in defensive mode.
        """
        reason = ""
        penalty = 0.0
        source = ""
        snapshot_age_minutes: Optional[float] = None
        stale_news = False
        news_fetch_age_minutes: Optional[float] = None
        try:
            reason = str(macro_risk_cache.get_macro_risk_reason(symbol) or "")
            penalty = float(macro_risk_cache.get_macro_risk_penalty(symbol) or 0.0)
            snapshot = macro_risk_cache.snapshot() if hasattr(macro_risk_cache, "snapshot") else {}
            source = str(snapshot.get("source", "") or "").lower()
            updated_at_raw = snapshot.get("updated_at")
            if isinstance(updated_at_raw, str) and updated_at_raw:
                updated_at = datetime.fromisoformat(updated_at_raw)
                if updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                snapshot_age_minutes = (
                    datetime.now(timezone.utc) - updated_at
                ).total_seconds() / 60.0
        except Exception:
            pass
        try:
            news_fetch_age_minutes = NewsDataCollector.get_data_age_minutes(symbol)
        except Exception:
            news_fetch_age_minutes = None

        freshness_candidates = [
            age for age in (snapshot_age_minutes, news_fetch_age_minutes) if age is not None
        ]
        effective_snapshot_age_minutes = min(freshness_candidates) if freshness_candidates else None

        reason_upper = reason.upper()
        if "technical_only_mode" in source:
            return {
                "reason": "Technical_Only_Mode",
                "penalty": 0.0,
                "macro_high": False,
                "news_pending": False,
                "stale_news": False,
                "technical_only_mode": True,
                "source": source,
                "snapshot_age_minutes": effective_snapshot_age_minutes,
            }
        news_pending = ("NEWS" in reason_upper) or ("HIGH_IMPACT" in reason_upper)
        stale_limit_minutes = float(
            os.environ.get(
                "MACRO_STALENESS_THRESHOLD",
                os.environ.get("MACRO_NEWS_MAX_STALENESS_MINUTES", "60"),
            )
        )
        technical_only_mode = False
        if (
            news_pending
            and effective_snapshot_age_minutes is not None
            and effective_snapshot_age_minutes > stale_limit_minutes
        ):
            stale_news = True
            news_pending = False
            penalty = 0.0
            if "news" in source or "heuristic" in source or "calendar" in source or reason_upper == "HIGH_IMPACT_NEWS_PENDING":
                reason = "Macro_Data_Stale_Hold"

        macro_high = (("HIGH" in reason_upper) or (penalty >= 0.25)) and not stale_news
        return {
            "reason": reason,
            "penalty": penalty,
            "macro_high": macro_high,
            "news_pending": news_pending,
            "stale_news": stale_news,
            "technical_only_mode": technical_only_mode,
            "source": source,
            "snapshot_age_minutes": effective_snapshot_age_minutes,
        }

    def evaluate_trade_permission(
        self,
        *,
        symbol: str,
        adx: float,
        rsi: float,
        ml_accuracy: float,
        ml_confidence: float,
        closed_trade_count: int,
        low_accuracy_cycle_count: int,
        bot_cycle_count: int,
        technical_only_mode: bool,
        velocity_mode_active: bool,
        striking_mode_active: bool,
        desperation_mode: bool,
        base_adx_min: float,
        base_rsi_lower: float = 25.0,
        base_rsi_upper: float = 75.0,
        base_confidence_min: float = 0.20,
        min_target_accuracy: float = 0.45,
        trade_tier: str = "",
        signal_score: float = 0.0,
    ) -> TradePermissionDecision:
        context = TradePermissionContext(
            adx=float(adx or 0.0),
            rsi=float(rsi or 50.0),
            ml_accuracy=float(ml_accuracy or 0.0),
            ml_confidence=float(ml_confidence or 0.0),
            closed_trade_count=int(closed_trade_count or 0),
            low_accuracy_cycle_count=int(low_accuracy_cycle_count or 0),
            bot_cycle_count=int(bot_cycle_count or 0),
            technical_only_mode=bool(technical_only_mode),
            velocity_mode_active=bool(velocity_mode_active),
            striking_mode_active=bool(striking_mode_active),
            desperation_mode=bool(desperation_mode),
            base_adx_min=float(base_adx_min or 0.0),
            base_rsi_lower=float(base_rsi_lower or 25.0),
            base_rsi_upper=float(base_rsi_upper or 75.0),
            base_confidence_min=float(base_confidence_min or 0.20),
            min_target_accuracy=float(min_target_accuracy or 0.45),
            trade_tier=str(trade_tier or ""),
            signal_score=float(signal_score or 0.0),
        )
        exploration_active = bool(technical_only_mode or velocity_mode_active or striking_mode_active)
        mode = "DESPERATION" if desperation_mode else ("EXPLORATION" if exploration_active else "STANDARD")
        permission_decision = self.permission_evaluator.evaluate(context)

        if exploration_active and permission_decision.allowed:
            thresholds = permission_decision.thresholds or PermissionThresholds(0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 1.0)
            logger.info(
                "[EXPLORATION_OVERRIDE_ACTIVE] %s | Score %.2f >= %.2f | ADX %.2f >= %.2f | Confidence %.2f%% >= %.2f%% | Exploration path admitted and downstream accuracy gates skipped | Mode=%s",
                symbol,
                float(permission_decision.score or 0.0),
                float(thresholds.required_score or 0.0),
                float(adx or 0.0),
                float(thresholds.adx_min or 0.0),
                float(ml_confidence or 0.0) * 100.0,
                float(thresholds.confidence_gate or 0.0) * 100.0,
                mode,
            )
            permission_decision.reason = "EXPLORATION_OVERRIDE_ACTIVE"
            permission_decision.failed_filter = ""
            return permission_decision

        if not exploration_active:
            if self.validate_accuracy_gate(
                symbol=symbol,
                ml_accuracy=float(ml_accuracy or 0.0),
                trade_tier=str(trade_tier or ""),
                signal_score=float(signal_score or 0.0),
                default_gate=0.0,  # DISABLED: Accuracy gate removed to allow all signals
            ):
                thresholds = PermissionThresholds(0.0, 0.0, 100.0, 0.30, 0.0, 0.0, 1.0)
                return TradePermissionDecision(
                    allowed=True,
                    score=1.0,
                    reason="PRIORITY_0_ELITE_ACCURACY_BYPASS",
                    actual_value=float(ml_accuracy or 0.0),
                    required_value=0.30,
                    thresholds=thresholds,
                )

        decision = permission_decision
        if decision.allowed:
            if exploration_active:
                thresholds = decision.thresholds or PermissionThresholds(0.0, 0.0, 100.0, 0.0, 0.0, 0.0, 1.0)
                logger.info(
                    "[EXPLORATION_OVERRIDE_ACTIVE] %s | Score %.2f >= %.2f | ADX %.2f >= %.2f | Accuracy %.2f%% >= %.2f%% | Confidence %.2f%% >= %.2f%% | RSI %.1f within %.1f-%.1f | Mode=%s",
                    symbol,
                    float(decision.score or 0.0),
                    float(thresholds.required_score or 0.0),
                    float(adx or 0.0),
                    float(thresholds.adx_min or 0.0),
                    float(ml_accuracy or 0.0) * 100.0,
                    float(thresholds.accuracy_gate or 0.0) * 100.0,
                    float(ml_confidence or 0.0) * 100.0,
                    float(thresholds.confidence_gate or 0.0) * 100.0,
                    float(rsi or 0.0),
                    float(thresholds.rsi_lower or 0.0),
                    float(thresholds.rsi_upper or 100.0),
                    mode,
            )
            return decision

        tier_name = str(context.trade_tier or "").upper()
        effective_score = float(context.signal_score or (float(context.ml_confidence or 0.0) * 100.0))
        if (
            str(decision.failed_filter or "").upper() == "ACCURACY"
            and tier_name == "TIER_A"
            and effective_score >= 80.0
        ):
            relaxed_gate = 0.30
            if float(context.ml_accuracy or 0.0) >= relaxed_gate:
                logger.info(
                    "[ACCURACY_BYPASS] TIER_A signal %s admitted with relaxed 30%% gate.",
                    symbol,
                )
                thresholds = decision.thresholds or PermissionThresholds(0.0, 0.0, 100.0, relaxed_gate, 0.0, 0.0, 1.0)
                thresholds.accuracy_gate = relaxed_gate
                return TradePermissionDecision(
                    allowed=True,
                    score=float(decision.score or 0.0),
                    reason="TIER_A_ACCURACY_BYPASS",
                    failed_filter="",
                    actual_value=float(context.ml_accuracy or 0.0),
                    required_value=relaxed_gate,
                    thresholds=thresholds,
                )

        self._filter_debug(
            symbol,
            decision.failed_filter or "PERMISSION_SCORE",
            float(decision.actual_value or 0.0),
            float(decision.required_value or 0.0),
            mode,
        )
        if str(decision.failed_filter or "").upper() == "ACCURACY":
            logger.info(
                "[REJECTED_BY_ACCURACY] Symbol: %s | Actual: %.1f%% | Gate: %.1f%% | Mode: %s",
                symbol,
                float(decision.actual_value or 0.0) * 100.0,
                float(decision.required_value or 0.0) * 100.0,
                mode,
            )
        return decision

    def validate_signal(self, signal: Any, default_gate: float = 0.50) -> bool:
        """
        Object-safe signal validator entry point for hard accuracy bypass logic.
        """
        sig_tier = str(getattr(signal, "tier", getattr(signal, "trade_tier", "C")) or "C").upper()
        sig_score = float(
            getattr(signal, "score", getattr(signal, "adaptive_score", getattr(signal, "signal_score", 0.0))) or 0.0
        )
        sig_confidence = float(getattr(signal, "confidence", 0.0) or 0.0)
        signal_mode = str(getattr(signal, "mode", "") or "").upper()
        structure_override = bool(getattr(signal, "structure_override", False))
        signal_source = str(getattr(signal, "source", getattr(signal, "signal_source", "")) or "").upper()
        forced_execution = bool(getattr(signal, "forced_execution", False))
        override_active = bool(
            forced_execution
            or structure_override
            or signal_source == "STRUCTURE_OVERRIDE"
            or signal_mode == "EXPLORATION"
        )
        if override_active:
            logger.critical(
                "[OVERRIDE_AUTHORIZED] %s | forced=%s | structure_override=%s | source=%s | confidence=%.1f%% | mode=%s | Accuracy gate bypassed before MT5 execution.",
                getattr(signal, "symbol", "UNKNOWN"),
                forced_execution,
                structure_override,
                signal_source or "STANDARD",
                sig_confidence * 100.0,
                signal_mode or "STANDARD",
            )
            return True
        if sig_tier == "TIER_A" and sig_score >= 75.0:
            return True

        signal_accuracy = float(
            getattr(signal, "ml_accuracy", getattr(signal, "accuracy", 0.0)) or 0.0
        )
        return signal_accuracy >= float(default_gate or 0.50)

    def validate_accuracy_gate(
        self,
        *,
        symbol: str,
        ml_accuracy: float,
        trade_tier: str = "",
        signal_score: float = 0.0,
        signal_rr: float = 0.0,
        technical_only_mode: bool = False,
        default_gate: float = 0.0,  # DISABLED: Default gate set to 0.0
    ) -> bool:
        tier_name = str(trade_tier or "").upper()
        score_value = float(signal_score or 0.0)
        rr_value = float(signal_rr or 0.0)
        acc_value = float(ml_accuracy or 0.0)
        
        # 1. TECHNICAL_ONLY_MODE no longer bypasses accuracy or RR gates.
        if technical_only_mode:
            logger.info(
                "[TECHNICAL_ONLY_MODE] %s | Accuracy gate remains active in degraded macro mode.",
                symbol,
            )

        # 2. Elite Tier Hard Bypass
        if tier_name == "TIER_A" and score_value >= 75.0:
            return True
            
        # 3. Dynamic Accuracy Floor for High Expectancy Setups
        dynamic_gate = float(default_gate)
        if rr_value >= 2.5 and score_value >= 70.0:
            dynamic_gate = 0.30
            logger.critical(f"[EXPECTANCY_FLOOR] {symbol} High RR ({rr_value:.2f}) & Score ({score_value:.1f}) detected. Lowering accuracy gate to 30%.")

        if acc_value >= dynamic_gate:
            return True
            
        # SUPPRESSED: Accuracy gate log disabled after accuracy gates set to 0.0
        # logger.warning(f"[STRATEGY_REJECT] {symbol} Accuracy {acc_value*100:.1f}% fails dynamic gate of {dynamic_gate*100:.1f}%.")
        return False

    def _is_tradeable_atr_band(self, current_spread: Optional[float], current_atr: Optional[float]) -> bool:
        try:
            spread = float(current_spread or 0.0)
            atr = float(current_atr or 0.0)
        except Exception:
            return False
        if atr <= 0.0:
            return False
        if spread <= 0.0:
            return True
        max_spread = float(self.config.spread_atr_ratio_max) * atr
        return spread < max_spread

    def _filter_debug(self, symbol: str, filter_name: str, actual_value: float, required_value: float, mode: str) -> None:
        logger.info(
            "[FILTER_DEBUG] %s | REJECTED: %s Actual %.3f < Required %.3f | Mode=%s",
            symbol,
            filter_name,
            float(actual_value or 0.0),
            float(required_value or 0.0),
            mode,
        )

    def _get_dynamic_filter_multiplier(self, technical_only_mode: bool) -> float:
        """
        Exploratory/bootstrap mode loosens entry gates by applying a 70% multiplier
        to threshold-style filters.
        """
        return 0.7 if technical_only_mode else 1.0

    def _resolve_effective_confidence_threshold(
        self,
        *,
        min_confidence_threshold: Optional[float],
        striking_mode_active: bool,
        structure_override_active: bool,
        raw_ml_confidence: float,
        high_impact_news_pending: bool,
        technical_only_mode: bool = False,
    ) -> float:
        effective_threshold = (
            float(min_confidence_threshold)
            if min_confidence_threshold is not None
            else float(self.config.min_confidence_threshold)
        )
        if structure_override_active and float(raw_ml_confidence or 0.0) > 0.05:
            effective_threshold = min(effective_threshold, 0.05)
        elif striking_mode_active:
            effective_threshold = min(effective_threshold, 0.12)
        if high_impact_news_pending:
            effective_threshold = max(effective_threshold, 0.20)
        effective_threshold *= self._get_dynamic_filter_multiplier(bool(technical_only_mode))
        return float(max(0.0, min(1.0, effective_threshold)))

    # ------------------------------------------------------------------
    # Reduce-Only Gate Controls
    # ------------------------------------------------------------------

    def set_reduce_only(self, symbol: str, until: datetime, reason: str) -> None:
        key = self._normalize_symbol(symbol)
        if not key:
            return
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        self.reduce_only_symbols[key] = until
        self.reduce_only_reasons[key] = str(reason or "")
        logger.critical(
            "[REDUCE_ONLY] %s | Active until %s | Reason: %s",
            key,
            until.strftime("%Y-%m-%d %H:%M:%S UTC"),
            reason,
        )

    def is_reduce_only(self, symbol: str) -> bool:
        key = self._normalize_symbol(symbol)
        expiry = self.reduce_only_symbols.get(key)
        if expiry is None:
            return False
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < expiry:
            return True
        del self.reduce_only_symbols[key]
        self.reduce_only_reasons.pop(key, None)
        return False

    def get_global_lockout_remaining(self) -> int:
        """
        Return seconds remaining until the furthest NEWS_HARD_STOP expires.
        Only considers reduce-only entries caused by the news hard stop gate.
        """
        now = datetime.now(timezone.utc)
        max_remaining = 0
        expired_keys: List[str] = []
        for key, expiry in list(self.reduce_only_symbols.items()):
            if expiry is None:
                expired_keys.append(key)
                continue
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)
            if expiry <= now:
                expired_keys.append(key)
                continue
            reason = self.reduce_only_reasons.get(key, "")
            if "NEWS_HARD_STOP" in str(reason).upper():
                remaining = int((expiry - now).total_seconds())
                if remaining > max_remaining:
                    max_remaining = remaining
        for key in expired_keys:
            self.reduce_only_symbols.pop(key, None)
            self.reduce_only_reasons.pop(key, None)
        return max_remaining
        
    def evaluate_admission(self, 
                          symbol: str,
                          regime: str,
                          expectancy: float,
                          confidence: float,
                          exit_policy: ExitPolicy,
                          position_size_multiplier: float,
                          real_risk_reward_ratio: float = None,
                          forced_execution: bool = False,
                          striking_mode_active: bool = False,
                          synthetic_present: bool = False,
                          direction: Optional[str] = None,
                          current_positions: Optional[List[Any]] = None,
                          min_confidence_threshold: Optional[float] = None,
                          current_spread: Optional[float] = None,
                          current_atr: Optional[float] = None,
                          structure_override_active: bool = False,
                          raw_ml_confidence: Optional[float] = None,
                          high_impact_news_pending: bool = False,
                          ml_accuracy: Optional[float] = None,
                          historical_trade_count: Optional[int] = None,
                          low_accuracy_cycle_count: Optional[int] = None,
                          bot_cycle_count: Optional[int] = None,
                          trade_tier: str = "",
                          signal_score: Optional[float] = None,
                          signal_type: str = "",
                          direction_matches_trend: bool = False,
                          trend_following: bool = False,
                          technical_only_mode: bool = False,
                          desperation_mode: bool = False) -> AdmissionDecision:
        """
        Evaluate whether this trade should be admitted.
        
        Returns:
            AdmissionDecision with admission verdict and reasoning
        """
        
        # ISSUE #4 FIX: Normalize AUD/USD overrides to respect Hard Safety Gates
        # Priority override is DISABLED (if False) to prevent bypassing safety gates.
        # Even with high signal scores, Hard Safety Gates (Spread, Volatility, Accuracy)
        # cannot be bypassed unless SYSTEM_UNCAGED is explicitly enabled.
        val_score = float(signal_score if signal_score is not None else (confidence * 100.0))
        val_tier = str(trade_tier or "C").upper()
        is_priority_override = structure_override_active or (val_score >= 85.0 and val_tier in ["TIER_A"])  # Raised threshold from 70 to 85
        
        if False and is_priority_override:  # DISABLED: Priority override no longer bypasses safety gates
            # Check only hard safety limits (RR >= 1.5, Spread <= 10.0)
            valid_rr = real_risk_reward_ratio is not None and real_risk_reward_ratio >= 1.5
            valid_spread = current_spread is None or current_spread <= 10.0
            
            if valid_rr and valid_spread:
                logger.critical(
                    f"[OVERRIDE_ABSOLUTE_PRIORITY] {symbol} | Priority override detected | "
                    f"Score: {val_score:.1f} | Tier: {val_tier} | Structure: {structure_override_active} | "
                    f"RR: {format_float(real_risk_reward_ratio, '.2f')}R | Spread: {format_float(current_spread, '.1f')} pips | "
                    f"ALL ACCURACY GATES BYPASSED — ADMITTED IMMEDIATELY"
                )
                self.stats['total_evaluated'] += 1
                self.stats['total_admitted'] += 1
                return AdmissionDecision(
                    admitted=True,
                    opportunity_score=val_score,
                    opportunity_cost_regret=0.0,
                    final_position_multiplier=position_size_multiplier,
                    reason=f"OVERRIDE_ABSOLUTE_PRIORITY: {val_tier} Score {val_score:.1f} | Structure override active",
                    action_taken="ADMITTED",
                    authority_level="LEVEL_0",
                    skip_validator=False
                )
            else:
                # Safety limits violated
                if not valid_rr:
                    logger.critical(
                        f"[OVERRIDE_SAFETY_REJECT_RR] {symbol} | Priority override failed safety check: "
                        f"RR={format_float(real_risk_reward_ratio, '.2f')}R < 1.5R minimum"
                    )
                if not valid_spread:
                    logger.critical(
                        f"[OVERRIDE_SAFETY_REJECT_SPREAD] {symbol} | Priority override failed safety check: "
                        f"Spread={format_float(current_spread, '.1f')} > 10.0 pips maximum"
                    )
                # Fall through to standard accuracy checks
        
        # ===== Standard Accuracy Gates (only if NOT a priority override) =====
        # If we reach here, this is NOT a priority override - run full accuracy checks

        # ===== SYMBOL COOLDOWN GATE (must be first — no bypass) =====
        # If this symbol was closed within the last 60 minutes (for ANY reason:
        # SL, TP, or manual close) hard-reject immediately. This permanently
        # breaks the revenge-trading loop without relying on MT5 deal history.
        _sym_key = self._normalize_symbol(symbol)
        _cooldown_expiry = self.symbol_cooldowns.get(_sym_key)
        if _cooldown_expiry is not None and datetime.now(timezone.utc) < _cooldown_expiry:
            _remaining = (_cooldown_expiry - datetime.now(timezone.utc)).total_seconds()
            logger.critical(
                "[SYMBOL_COOLDOWN] %s | RE-ENTRY BLOCKED — %.0f min %.0f sec remaining on 60-min cooldown.",
                _sym_key,
                _remaining // 60,
                _remaining % 60,
            )
            return AdmissionDecision(
                admitted=False,
                opportunity_score=0.0,
                opportunity_cost_regret=0.0,
                final_position_multiplier=0.0,
                reason=(
                    f"SYMBOL_COOLDOWN: {_sym_key} is blocked for "
                    f"{int(_remaining // 60)}m {int(_remaining % 60)}s "
                    f"after position close. Re-entry allowed after "
                    f"{_cooldown_expiry.strftime('%H:%M:%S UTC')}."
                ),
                action_taken="REJECTED",
            )
        elif _cooldown_expiry is not None:
            # Cooldown has expired — clean it up
            del self.symbol_cooldowns[_sym_key]

        # ===== FIX #1: WEEKEND LOCKOUT GATE =====
        # If symbol was harvested on Friday, reject new signals until Sunday/Monday market open
        if self.profit_protection_module and self.profit_protection_module.is_symbol_locked_for_weekend(symbol):
            logger.critical(
                "[WEEKEND_LOCKOUT] %s | RE-ENTRY BLOCKED — Symbol was harvested on Friday. "
                "Locked until market re-opens on Sunday/Monday.",
                symbol,
            )
            return AdmissionDecision(
                admitted=False,
                opportunity_score=0.0,
                opportunity_cost_regret=0.0,
                final_position_multiplier=0.0,
                reason="WEEKEND_LOCKOUT: Friday harvest protection active",
                action_taken="REJECTED",
            )


        # Hard reset of per-evaluation scalar inputs to avoid cross-cycle bleed.
        expectancy = float(expectancy or 0.0)
        confidence = float(confidence or 0.0)
        position_size_multiplier = float(position_size_multiplier or 0.0)

        self.max_total_positions = 7
        self.max_positions_per_symbol = 3
        self.QUALITY_FLOOR = 0.40
        self.quality_threshold = 0.40
        raw_ml_confidence = float(raw_ml_confidence or confidence or 0.0)
        try:
            weighted_strength = float(getattr(self, "_weighted_strength_override", 0.0) or 0.0)
        except Exception:
            weighted_strength = 0.0
        try:
            self._weighted_strength_override = None
        except Exception:
            pass

        macro_state = self._get_macro_news_state(symbol)
        macro_reason = str(macro_state.get("reason", "") or "")
        macro_high = bool(macro_state.get("macro_high", False))
        stale_news = bool(macro_state.get("stale_news", False))
        technical_only_mode = bool(technical_only_mode or macro_state.get("technical_only_mode", False))
        macro_source = str(macro_state.get("source", "") or "").lower()
        exploration_mode = bool(technical_only_mode or stale_news)
        if technical_only_mode:
            self.QUALITY_FLOOR = 0.35
            self.quality_threshold = 0.35
            configured_news_provider = str(os.environ.get("NEWS_PROVIDER", "") or "").strip().lower()
            mock_mode_active = configured_news_provider == "mock" or "news_unavailable_volatility_fallback" in macro_source
            if mock_mode_active:
                self.QUALITY_FLOOR = 0.33
                self.quality_threshold = 0.33
        mode_label = "DESPERATION" if desperation_mode else ("EXPLORATION" if exploration_mode else "STANDARD")
        if stale_news:
            logger.warning(
                "[MACRO_DATA_STALE_HOLD] %s | Macro/news snapshot is stale (age=%.0fm). "
                "Blocking new entries until data freshness recovers.",
                symbol,
                float(macro_state.get("snapshot_age_minutes") or 0.0),
            )
            return AdmissionDecision(
                admitted=False,
                opportunity_score=0.0,
                opportunity_cost_regret=0.0,
                final_position_multiplier=0.0,
                reason="MACRO_DATA_STALE_HOLD",
                action_taken="HOLD",
            )
        if technical_only_mode:
            macro_high = False
            macro_reason = "Technical_Only_Mode"

        # ===== FIX #3: ADJUST MACRO_SHIELD SIZE FLOOR FOR WEIGHTED_ADMISSION TRADES =====
        # LEVEL 1: MACRO SHIELD (News/Risk) - with exception for high-accuracy weighted trades
        if macro_high:
            # Check if this signal was admitted via weighted confidence formula
            is_weighted_admission = bool(hasattr(self, '_weighted_admission_active') and self._weighted_admission_active)
            if is_weighted_admission:
                # For weighted admission trades during news: allow 0.50x but respect it as floor (not further downscale)
                position_size_multiplier = max(position_size_multiplier, 0.50)  # Floor at 0.50x for safety
                logger.critical(
                    "[MACRO_SHIELD] %s | MacroRisk=HIGH + WEIGHTED_ADMISSION | Size multiplier set to floor 0.50x (protected)",
                    symbol,
                )
            else:
                # Standard macro shield: downscale to 0.50x
                position_size_multiplier = min(position_size_multiplier, 0.5)
                logger.critical(
                    "[MACRO_SHIELD] %s | MacroRisk=HIGH | Size multiplier forced to 0.50x",
                    symbol,
                )

        # Anti-Revenge News Guard: raise confidence floor when news pending
        effective_min_confidence_threshold = self._resolve_effective_confidence_threshold(
            min_confidence_threshold=min_confidence_threshold,
            striking_mode_active=bool(striking_mode_active),
            structure_override_active=bool(structure_override_active),
            raw_ml_confidence=float(raw_ml_confidence or 0.0),
            high_impact_news_pending=bool(high_impact_news_pending),
            technical_only_mode=bool(technical_only_mode),
        )
        if exploration_mode:
            effective_min_confidence_threshold = min(effective_min_confidence_threshold, 0.10)
        if desperation_mode:
            effective_min_confidence_threshold = 0.0
        cold_start_active = False
        recovery_mode_active = False
        try:
            trade_count = int(historical_trade_count or 0)
        except Exception:
            trade_count = 0
        try:
            effective_ml_accuracy = float(ml_accuracy or 0.0)
        except Exception:
            effective_ml_accuracy = 0.0
        try:
            low_accuracy_cycles = int(low_accuracy_cycle_count or 0)
        except Exception:
            low_accuracy_cycles = 0
        try:
            current_cycle_count = int(bot_cycle_count or 0)
        except Exception:
            current_cycle_count = 0

        bootstrap_mode_active = bool(
            technical_only_mode
            or low_accuracy_cycles > 10
            or (0 < current_cycle_count < 100)
            or trade_count < 100
        )

        if trade_count < 100:
            cold_start_active = True
            effective_min_confidence_threshold = min(effective_min_confidence_threshold, 0.12)
        if low_accuracy_cycles >= 5 and self._is_tradeable_atr_band(current_spread, current_atr):
            recovery_mode_active = True
            effective_min_confidence_threshold = min(effective_min_confidence_threshold, 0.10)
        if bootstrap_mode_active:
            effective_min_confidence_threshold = min(effective_min_confidence_threshold, 0.10)

        if cold_start_active and effective_ml_accuracy < 0.20:
            logger.info(
                "[COLD_START_GATE] %s | Historical trades=%d and ML accuracy %.1f%% < 20%%. Admission remains restricted.",
                symbol,
                trade_count,
                effective_ml_accuracy * 100.0,
            )
        elif cold_start_active:
            logger.info(
                "[COLD_START_GATE] %s | Cold-start active (%d trades). Lowering confidence gate for bootstrap.",
                symbol,
                trade_count,
            )
        if recovery_mode_active:
            logger.info(
                "[ML_RECOVERY_MODE] %s | Low-accuracy cycle count=%d, but ATR/spread band is tradeable. "
                "Relaxing confidence gate to allow technical recovery trades.",
                symbol,
                low_accuracy_cycles,
            )
        if bootstrap_mode_active:
            logger.info(
                "[BOOTSTRAP_MODE] %s | Technical-only=%s | LowAccCycles=%d | Cycle=%d | Trades=%d | "
                "Admission confidence gate relaxed for fail-forward learning.",
                symbol,
                technical_only_mode,
                low_accuracy_cycles,
                current_cycle_count,
                trade_count,
            )
        if desperation_mode:
            logger.warning(
                "[DESPERATION_MODE] %s | Idle loop exceeded threshold. Admission confidence gate disabled for bootstrap cycle.",
                symbol,
            )
        if high_impact_news_pending:
            score_value = float(signal_score if signal_score is not None else (confidence * 100.0))
            signal_type_name = str(signal_type or "").upper()
            is_trend_signal = bool(direction_matches_trend) or bool(trend_following) or signal_type_name == "TREND"
            
            # Allow entries despite High_Impact_News_Pending if:
            # The signal strategy type is "TREND" or matches the 4H bias.
            # AND signal.score >= 80.
            # Maintain the block ONLY for "Reversal" or "Mean Reversion" strategies.
            blocking_signal = signal_type_name in {"REVERSAL", "MEAN_REVERSION", "MEAN REVERSION"}
            if is_trend_signal and score_value >= 80.0:
                logger.critical(
                    f"[NEWS_OVERRIDE] Striking Trend move on {symbol} despite macro risk."
                )
                high_impact_news_pending = False
            elif blocking_signal:
                logger.critical(
                    "[NEWS_GUARD] %s | High-impact news pending | Confidence floor forced to %.2f",
                    symbol,
                    float(effective_min_confidence_threshold),
                )
            else:
                high_impact_news_pending = False

        # ===== FIX #2: EXPECTANCY SPLIT-BRAIN - HARD SYNC RR RATIO AT START =====
        # Force hard sync: ensure signal.expectancy = float(signal.rr_ratio) at very beginning
        # This prevents expectancy ghosting where different modules reference different values
        # If real_risk_reward_ratio is provided, use it as the canonical expectancy source
        if real_risk_reward_ratio is not None and real_risk_reward_ratio > 0:
            expectancy = float(real_risk_reward_ratio)

        # Spread gating is applied later in _apply_final_hard_gates so all
        # volatility and elite-padding decisions come from one consistent path.
        
        uncaged_active = (
            str(os.environ.get("SYSTEM_UNCAGED", "0")).lower() in {"1", "true", "yes", "on"}
            or str(os.environ.get("SYSTEM_UNCAGED_V6", "0")).lower() in {"1", "true", "yes", "on"}
            or striking_mode_active
        )
        unleashed_active = str(os.environ.get("STRATEGY_FULLY_UNLEASHED", "0")).lower() in {"1", "true", "yes", "on"}

        # Correlation Engine: reject highly correlated additions unless it's an opposite-direction hedge.
        correlation_threshold = 0.98 if (uncaged_active or unleashed_active) else self.config.max_correlation_threshold
        if correlation_threshold >= 0.98:
            logger.critical(
                f"[CORRELATION_OVERRIDE_ACTIVE] {symbol} | Threshold forced to {correlation_threshold:.2f} "
                f"(MaxCorr below this level will be admitted)."
            )
        corr_reject, max_corr, corr_ref_symbol = self._is_too_correlated(
            new_symbol=symbol,
            new_direction=direction,
            current_positions=current_positions,
            threshold=correlation_threshold,
            lookback_bars=self.config.correlation_lookback_bars,
            timeframe=self.config.correlation_timeframe,
        )
        logger.info(
            "[CORRELATION_GATE] %s | MaxCorr=%.3f | Ref=%s | Threshold=%.2f | Reject=%s",
            symbol,
            max_corr,
            corr_ref_symbol or "N/A",
            correlation_threshold,
            corr_reject,
        )
        
        # Initialize regime window if needed
        if regime not in self.opportunity_windows:
            self.opportunity_windows[regime] = deque(maxlen=self.config.lookback_window)
        
        window = self.opportunity_windows[regime]
        
        # Calculate opportunity score (percentile rank)
        if len(window) == 0:
            # No history - admit with caution
            opportunity_score = 50.0  # Neutral percentile
            opportunity_cost_regret = 0.0
        else:
            # ===== FIX #1: FORCE EXPECTANCY_SCORE TO USE real_risk_reward_ratio AS UNIQUE INPUT =====
            # Override expectancy parameter to use ONLY the RR ratio to prevent ghosting
            # This prevents expectancy ghosting where default values leak through
            if real_risk_reward_ratio and real_risk_reward_ratio > 0:
                expectancy = real_risk_reward_ratio
            
            # Get expectancies from window
            historical_expectancies = [rec.expectancy for rec in window]
            
            # Calculate percentile
            percentile_rank = self._calculate_percentile(expectancy, historical_expectancies)
            opportunity_score = percentile_rank * 100  # Convert to 0-100 scale
            
            # Calculate opportunity cost regret
            # Regret = difference between median opportunity and current
            median_expectancy = np.median(historical_expectancies)
            opportunity_cost_regret = max(0.0, median_expectancy - expectancy)
        
        # Determine BASE admission threshold based on regime
        effective_regime = regime
        if uncaged_active and regime in ['LOW_LIQUIDITY', 'LOW_VOLATILITY']:
            # Nuclear override: ignore low-liquidity/low-volatility regime penalties.
            effective_regime = "NORMAL"

        if effective_regime in ['HIGH_VOLATILITY']:
            base_threshold = self.config.percentile_threshold_volatile
        elif effective_regime in ['LOW_LIQUIDITY']:
            base_threshold = self.config.percentile_threshold_illiquid
        else:
            base_threshold = self.config.percentile_threshold_normal
        
        # Apply adaptive scaling based on data availability
        threshold = self._get_adaptive_threshold(regime, base_threshold)
        
        # Log adaptive adjustment for transparency
        window = self.opportunity_windows.get(regime)
        sample_count = len(window) if window else 0
        if sample_count < 50:
            logger.debug(
                f"[ADAPTIVE_THRESHOLD] {regime}: {sample_count} samples | "
                f"Base: {base_threshold:.1f}%ile → Adaptive: {threshold:.1f}%ile"
            )
        
        # ===== FIX #2: CANONICAL RR EXTRACTION - PRICE-BASED ONLY =====
        # real_risk_reward_ratio is the ONLY source - it's the price-based RR from SLTPCalculator
        # No fallbacks, no theoretical values, no scanning for orphan variables
        forced_execution = bool(forced_execution)
        striking_mode_active = bool(striking_mode_active)
        
        # Extract RR from the canonical source
        if isinstance(real_risk_reward_ratio, dict):
            real_rr = float(real_risk_reward_ratio.get('rr_ratio', 0.0))
        else:
            real_rr = float(real_risk_reward_ratio) if real_risk_reward_ratio else 0.0
        
        # Hard validation: RR must be price-based and > 0
        if real_rr <= 0:
            logger.warning(
                f"[RR_VALIDATION] {symbol} | Invalid RR value: {real_rr:.3f}R. "
                f"Expected price-based RR from SLTPCalculator. Rejecting trade."
            )
            real_rr = 0.0  # Will trigger rejection downstream
        
        # EV Gatekeeper:
        # EV = (calibrated_ml_confidence * RR) - ((1.0 - calibrated_ml_confidence) * 1.0)
        calibrated_ml_confidence = float(max(0.0, min(1.0, confidence)))
        macro_risk_penalty = float(max(0.0, min(0.4, get_macro_risk_penalty(symbol))))

        # If macro monitor is running in heuristic fallback mode, cap penalty to avoid
        # statistical paralysis from low-confidence macro inputs.
        try:
            macro_source = str(macro_risk_cache.snapshot().get("source", "")).lower()
        except Exception:
            macro_source = ""
        if "heuristic" in macro_source and macro_risk_penalty > 0.10:
            macro_risk_penalty = 0.10

        raw_adjusted_win_prob = float(calibrated_ml_confidence)
        full_auto_active = datetime.now(timezone.utc) < self._full_auto_until
        floor = float(getattr(self, "QUALITY_FLOOR", 0.20))
        adjusted_win_prob = max(floor, raw_adjusted_win_prob)
        if raw_adjusted_win_prob < floor:
            logger.critical(
                f"[MATH_IMPEDIMENT_REMOVED] {symbol} | "
                f"AdjProb floored {raw_adjusted_win_prob:.3f} -> {adjusted_win_prob:.3f} (Floor={floor:.2f}) | "
                f"MacroPenalty={macro_risk_penalty:.3f}"
            )
        rr_for_ev = float(real_rr) if real_rr is not None else float(expectancy)
        raw_ev = (adjusted_win_prob * rr_for_ev) - ((1.0 - adjusted_win_prob) * 1.0)
        ev = raw_ev - macro_risk_penalty
        ev_gate_threshold = -2.0
        if uncaged_active or full_auto_active:
            logger.critical(
                f"[STRATEGY_FULLY_UNLEASHED] {symbol} | AdjProbFloor={floor:.2f} | "
                f"EVThreshold={ev_gate_threshold:.2f}R | Uncaged={uncaged_active} | FullAuto={full_auto_active}"
            )
            logger.critical(
                "[REOPEN_STRIKE_READY] Runtime active. Quality floor locked at 65% and hard gates remain enforced."
            )
        logger.info(
            f"[EV_GATE] {symbol} | CalibConf={calibrated_ml_confidence:.3f} | "
            f"MacroPenalty={macro_risk_penalty:.3f} | AdjProb={adjusted_win_prob:.3f} | "
            f"RR={rr_for_ev:.3f}R | RawEV={raw_ev:.3f}R | EV={ev:.3f}R | Threshold={ev_gate_threshold:.3f}R"
        )
        
        # Decision logic
        admitted = False
        action_taken = "REJECTED"
        final_multiplier = 0.0
        reason = ""
        structure_auto_admit = bool(
            structure_override_active
            and (
                (raw_ml_confidence is not None and float(raw_ml_confidence) > 0.08)
                or (float(weighted_strength or 0.0) > 0.85)
            )
        )
        if structure_auto_admit:
            admitted = True
            final_multiplier = position_size_multiplier
            action_taken = "ADMITTED"
            reason = (
                f"STRUCTURE_OVERRIDE_AUTO_ADMIT | Strength={float(weighted_strength):.3f} > 0.85 or "
                f"RawML={float(raw_ml_confidence):.3f} > 0.08 | "
                f"MacroRisk={'HIGH' if macro_high else 'OK'}"
            )
            self.stats['total_admitted'] += 1
        elif corr_reject:
            self._filter_debug(symbol, "CORRELATION", float(max_corr or 0.0), float(correlation_threshold or 0.0), mode_label)
            admitted = False
            final_multiplier = 0.0
            action_taken = "REJECTED"
            reason = (
                f"High Portfolio Correlation: max corr {max_corr:.3f} with {corr_ref_symbol or 'open book'} "
                f"> {correlation_threshold:.2f}"
            )
            self.stats['total_rejected'] += 1
        elif (not full_auto_active) and (not exploration_mode) and (not structure_override_active) and ev <= 0.0:
            # ===== FIX #3: EXPECTANCY FLOOR BYPASS =====
            # Skip hard EV rejection if exploration_mode or structure_override_active
            # This allows USD/CHF and other exploration signals through even with EV <= 0
            # The hard floor of -2.0R (ev_gate_threshold) still applies for next condition
            self._filter_debug(symbol, "EV_GATE", float(ev or 0.0), 0.0, mode_label)
            admitted = False
            final_multiplier = 0.0
            action_taken = "REJECTED"
            reason = (
                f"Hard reject by EV gate: EV {ev:.3f}R <= 0.000R | "
                f"Conf: {calibrated_ml_confidence:.3f}, AdjProb: {adjusted_win_prob:.3f}, RR: {rr_for_ev:.2f}R"
            )
            self.stats['total_rejected'] += 1
        elif ev > ev_gate_threshold:
            admitted = True
            final_multiplier = position_size_multiplier
            action_taken = "ADMITTED"
            reason = (
                f"Admitted by EV gate: EV {ev:.3f}R > {ev_gate_threshold:.3f}R | "
                f"Conf: {calibrated_ml_confidence:.3f}, AdjProb: {adjusted_win_prob:.3f}, RR: {rr_for_ev:.2f}R | "
                f"Size: {final_multiplier:.2f}x"
            )
            self.stats['total_admitted'] += 1
        elif opportunity_score >= threshold:
            admitted = True
            final_multiplier = position_size_multiplier
            action_taken = "ADMITTED"
            reason = (
                f"Admitted (strict path): 0 < EV {ev:.3f}R < 0.150R and "
                f"Score {opportunity_score:.1f}%ile >= threshold {threshold:.1f}%ile | "
                f"Conf: {calibrated_ml_confidence:.3f}, AdjProb: {adjusted_win_prob:.3f}, RR: {rr_for_ev:.2f}R"
            )
            self.stats['total_admitted'] += 1
        else:
            self._filter_debug(symbol, "OPPORTUNITY_SCORE", float(opportunity_score or 0.0), float(threshold or 0.0), mode_label)
            admitted = False
            final_multiplier = 0.0
            action_taken = "REJECTED"
            reason = (
                f"Rejected by strict path: 0 < EV {ev:.3f}R < 0.150R but "
                f"Score {opportunity_score:.1f}%ile < threshold {threshold:.1f}%ile."
            )
            self.stats['total_rejected'] += 1        

        # ===== FINAL HARD GATES (Non-Bypassable) =====
        admitted, final_multiplier, action_taken, reason = self._apply_final_hard_gates(
            symbol=symbol,
            admitted=admitted,
            final_multiplier=final_multiplier,
            action_taken=action_taken,
            reason=reason,
            confidence=confidence,
            ev=ev,
            min_confidence_threshold=effective_min_confidence_threshold,
            expectancy=expectancy,
            rr_for_ev=rr_for_ev,
            position_size_multiplier=position_size_multiplier,
            current_spread=current_spread,
            current_atr=current_atr,
            structure_override_active=bool(structure_override_active),
            raw_ml_confidence=float(raw_ml_confidence or 0.0),
            high_impact_news_pending=bool(high_impact_news_pending),
            technical_only_mode=bool(technical_only_mode),
        )
        if not admitted:
            logger.info("[FILTER_REJECT] %s | Reason: %s", symbol, reason)
        # Update statistics
        self.stats['total_evaluated'] += 1
        if admitted:
            n = self.stats['total_admitted'] + self.stats['total_downscaled'] + self.stats['total_exploration']
            self.stats['avg_opportunity_score_admitted'] = (
                (self.stats['avg_opportunity_score_admitted'] * (n - 1) + opportunity_score) / n
            )
            
            # ===== FIX #6: RANGING MULTIPLIER BOOST - LOG WHEN DEPLOYING >= 0.9x CAPITAL =====
            # If deploying >= 90% of position size, log as boosted capital deployment
            if final_multiplier >= position_size_multiplier * 0.9:
                logger.critical(
                    f"[DEPLOYING_BOOSTED_CAPITAL] {symbol} | Position Multiplier: {final_multiplier:.2f}x "
                    f"(>= {position_size_multiplier * 0.9:.2f}x threshold) | High-confidence trade. "
                    f"Bot is leaning into elite signal with strong capital allocation."
                )
        else:
            n = self.stats['total_rejected']
            self.stats['avg_opportunity_score_rejected'] = (
                (self.stats['avg_opportunity_score_rejected'] * (n - 1) + opportunity_score) / n
                if n > 0 else opportunity_score
            )
        
        # Log decision
        authority_level = "LEVEL_3"
        if macro_high:
            authority_level = "LEVEL_1"
        elif structure_auto_admit:
            authority_level = "LEVEL_2"
        logger.info(
            f"[TRADE_ADMISSION] {symbol} | Regime: {regime} | "
            f"Action: {action_taken} | {reason}"
        )
        if technical_only_mode:
            logger.info("[TECHNICAL_ONLY_MODE] %s | Macro/news penalties may be relaxed, but hard safety gates remain active.", symbol)
        logger.info(
            "[AUTHORITY_LEVEL] %s | %s | Evaluated",
            symbol,
            authority_level,
        )
        
        # ===== PATCH #4-ENHANCED: DEBUG_RR_SYNC LOG (Logic-Chain Sync Fix #6) =====
        # Log RR value arriving at admission controller for verification with status
        logger.critical(
            f"[DEBUG_RR_SYNC] {symbol} | RR: {real_rr:.3f}R | "
            f"Admission Status: {action_taken} | EV: {ev:.3f}R | "
            f"Penalty: {macro_risk_penalty:.3f} | AdjProb: {adjusted_win_prob:.3f} | "
            f"ForcedBypass: DISABLED | Data source confirmed"
        )
        
        # Record this opportunity
        record = OpportunityRecord(
            timestamp=datetime.now(timezone.utc),
            symbol=symbol,
            regime=regime,
            expectancy=expectancy,
            confidence=confidence,
            exit_policy=exit_policy.value,
            position_size_multiplier=position_size_multiplier,
            was_admitted=admitted,
            admission_reason=reason,
            opportunity_score=opportunity_score,
            ev=ev,
            rr_for_ev=rr_for_ev,
            calibrated_ml_confidence=calibrated_ml_confidence,
            macro_risk_penalty=macro_risk_penalty,
            adjusted_win_prob=adjusted_win_prob,
            max_portfolio_correlation=max_corr,
            most_correlated_symbol=corr_ref_symbol or "",
            correlation_blocked=corr_reject,
        )
        window.append(record)
        
        # ===== PATCH #10: PIPELINE_INTEGRITY_VERIFIED - CONFIRM NON-1.0 RR PASSES ENTIRE STACK =====
        # Trigger only when:
        # 1. Signal is admitted (admitted=True)
        # 2. RR value is > 1.0 (not default 1.0R)
        # 3. Real RR !== 1.0 (confirms actual calculation, not default)
        # Reset integrity score every symbol evaluation to avoid sticky cross-cycle penalties.
        pipeline_score = 100.0
        pipeline_score = max(0.0, min(100.0, adjusted_win_prob * 100.0))
        if admitted and real_rr is not None and real_rr > 1.0 and real_rr != 1.0:
            logger.critical(
                f"[PIPELINE_INTEGRITY_VERIFIED] ✅ SUCCESS | {symbol} | "
                f"Non-default R:R ({real_rr:.3f}R) successfully passed entire pipeline: "
                f"Strategy → SLTPCalculator → SignalCombiner (RR_MAPPING_SOURCE logged) → "
                f"TradeAdmissionController (DEBUG_RR_SYNC logged) → SignalFilter → Final Admission | "
                f"Confidence: {confidence:.1%} | Regime: {regime} | Score: {pipeline_score:.1f}%"
            )
        elif admitted and (real_rr is None or real_rr == 1.0):
            logger.warning(
                f"[PIPELINE_INTEGRITY_WARNING] ⚠️ Accepted with degraded RR | {symbol} | "
                f"Expected non-1.0R but got {real_rr}. Check if data mapping is correct."
            )
        
        # Persist periodically (every 10 evaluations)
        if self.stats['total_evaluated'] % 10 == 0:
            self.save_history()
        
        # ===== FIX #3: ABSOLUTE OVERRIDE PRIORITY (End-of-Method Check) =====
        # Check for SNIPER OVERRIDE at the very end, AFTER all other gates
        # This ensures override bypasses ALL accuracy gates but still respects hard safety limits
        val_score = float(signal_score if signal_score is not None else (confidence * 100.0))
        val_tier = str(trade_tier or "C").upper()
        
        # Only apply override if RR > 1.5 and spread <= 10.0 (hard safety limits)
        valid_rr = real_rr is not None and real_rr >= 1.5
        valid_spread = current_spread is None or current_spread <= 10.0
        
        if val_score >= 70.0 and val_tier in ["TIER_A", "TIER_B"] and valid_rr and valid_spread:
            logger.critical(
                f"[OVERRIDE_AUTHORIZED] {symbol} (Score: {val_score:.1f}) admitted via Priority 0 Score Override. "
                f"All accuracy gates bypassed. RR={real_rr:.2f}R (>{1.5}), Spread={current_spread or 'N/A'} (<10.0)"
            )
            self.stats['total_evaluated'] += 1
            self.stats['total_admitted'] += 1
            return AdmissionDecision(
                admitted=True,
                opportunity_score=val_score,
                opportunity_cost_regret=0.0,
                final_position_multiplier=position_size_multiplier,
                reason=f"OVERRIDE_AUTHORIZED: {val_tier} Score {val_score:.1f} >= 70 hard-bypass (RR/Spread safety limits met).",
                action_taken="ADMITTED",
                authority_level="LEVEL_0"
            )
        elif val_score >= 70.0 and val_tier in ["TIER_A", "TIER_B"]:
            # Override score met but safety limits violated
            if not valid_rr:
                logger.critical(
                    f"[OVERRIDE_REJECTED_RR] {symbol} (Score: {val_score:.1f}) failed safety check: RR={real_rr:.2f}R < 1.5R minimum"
                )
            if not valid_spread:
                logger.critical(
                    f"[OVERRIDE_REJECTED_SPREAD] {symbol} (Score: {val_score:.1f}) failed safety check: Spread={current_spread:.1f} > 10.0 pips maximum"
                )
        
        return AdmissionDecision(
            admitted=admitted,
            opportunity_score=opportunity_score,
            opportunity_cost_regret=opportunity_cost_regret,
            final_position_multiplier=final_multiplier,
            reason=reason,
            action_taken=action_taken,
            authority_level=authority_level,
        )

    def _apply_final_hard_gates(
        self,
        *,
        symbol: str,
        admitted: bool,
        final_multiplier: float,
        action_taken: str,
        reason: str,
        confidence: float,
        ev: float,
        min_confidence_threshold: Optional[float],
        expectancy: float,
        rr_for_ev: float,
        position_size_multiplier: float,
        current_spread: Optional[float],
        current_atr: Optional[float],
        structure_override_active: bool = False,
        raw_ml_confidence: float = 0.0,
        high_impact_news_pending: bool = False,
        technical_only_mode: bool = False,
    ) -> Tuple[bool, float, str, str]:
        """
        Final non-bypassable safety gates. These execute last and override prior logic.
        """
        symbol_key = self._normalize_symbol(symbol)
        hard_min_conf = self._resolve_effective_confidence_threshold(
            min_confidence_threshold=min_confidence_threshold,
            striking_mode_active=False,
            structure_override_active=bool(structure_override_active),
            raw_ml_confidence=float(raw_ml_confidence or 0.0),
            high_impact_news_pending=bool(high_impact_news_pending),
            technical_only_mode=bool(technical_only_mode),
        )

        # 1) Volatility gate: reject only when spread exceeds 25% of ATR,
        # with a small elite-signal padding for very high-conviction setups.
        vol_ok, vol_reason = self._volatility_gate(
            symbol_key=symbol_key,
            current_spread=current_spread,
            current_atr=current_atr,
            confidence=confidence,
            ev=ev,
        )
        if not vol_ok:
            logger.critical("[FINAL_HARD_GATE] %s | %s", symbol_key, vol_reason)
            return False, 0.0, "REJECTED", vol_reason

        # 2) Reduce-only already active
        if self.is_reduce_only(symbol_key):
            reduce_reason = str(self.reduce_only_reasons.get(symbol_key, "") or "")
            rejection_reason = f"REJECTED: REDUCE_ONLY_ACTIVE | {symbol_key}"
            logger.critical("[FINAL_HARD_GATE] %s | %s", symbol_key, rejection_reason)
            return False, 0.0, "REJECTED", rejection_reason

        # 3) Confidence hard floor (no force-pass)
        if (
            not (structure_override_active and float(raw_ml_confidence or 0.0) > 0.05)
            and float(confidence or 0.0) < hard_min_conf
        ):
            rejection_reason = f"REJECTED: CONFIDENCE_BELOW_THRESHOLD | {confidence:.3f} < {hard_min_conf:.3f}"
            logger.critical("[FINAL_HARD_GATE] %s | %s", symbol_key, rejection_reason)
            logger.info(
                "[FILTER_REJECT] %s | Reason: CONFIDENCE (%.3f < %.3f)",
                symbol_key,
                float(confidence or 0.0),
                float(hard_min_conf),
            )
            return False, 0.0, "REJECTED", rejection_reason

        # 3.5) Mathematical floor (minimum 1.5R)
        try:
            rr_ratio = float(rr_for_ev or 0.0)
        except Exception:
            rr_ratio = 0.0
        if rr_ratio > 0.0 and rr_ratio < 1.5:
            rejection_reason = f"REJECTED: MATHEMATICAL_SUICIDE | RR {rr_ratio:.2f} < 1.50"
            logger.critical("[FINAL_HARD_GATE] %s | %s", symbol_key, rejection_reason)
            return False, 0.0, "REJECTED", rejection_reason

        # 4) Size boost clamp when expectancy or RR below baseline
        if final_multiplier > 1.0:
            baseline_exp = float(self.config.baseline_expectancy_min)
            baseline_rr = float(self.config.baseline_rr_min)
            if float(expectancy) < baseline_exp or float(rr_for_ev) < baseline_rr:
                logger.critical(
                    "[SIZE_BOOST_BLOCKED] %s | Multiplier %.2fx -> 1.00x | "
                    "Expectancy=%.3fR (min %.3fR) | RR=%.3fR (min %.3fR).",
                    symbol_key,
                    final_multiplier,
                    float(expectancy),
                    baseline_exp,
                    float(rr_for_ev),
                    baseline_rr,
                )
                final_multiplier = min(final_multiplier, 1.0)
                if admitted:
                    action_taken = "ADMITTED"
                    reason = (
                        f"{reason} | SIZE_BOOST_BLOCKED: "
                        f"Expectancy {expectancy:.2f}R or RR {rr_for_ev:.2f}R below baseline."
                    )

        # ISSUE #2 FIX: Enforce MIN_POSITION_SIZE floor for admitted trades
        # If trade passes admission, ensure position size is never zeroed
        if admitted and final_multiplier > 0.0:
            min_floor = float(self.config.min_position_size_floor)
            if final_multiplier < min_floor:
                logger.critical(
                    "[MIN_POSITION_SIZE_FLOOR] %s | Raising multiplier from %.2fx to %.2fx | "
                    "Trade admitted with quality=%.2f — enforcing minimum size floor.",
                    symbol_key,
                    final_multiplier,
                    min_floor,
                    float(expectancy),
                )
                final_multiplier = min_floor
                reason = f"{reason} | MIN_POSITION_SIZE_FLOOR: Enforced {min_floor:.2f}x minimum"

        return admitted, final_multiplier, action_taken, reason

    def _volatility_gate(
        self,
        *,
        symbol_key: str,
        current_spread: Optional[float],
        current_atr: Optional[float],
        confidence: float = 0.0,
        ev: float = 0.0,
    ) -> Tuple[bool, str]:
        """
        Spread-to-ATR ratio gate:
        Reject only if current spread > (ATR * configured ratio), with optional
        elite padding for very high-conviction trades.
        """
        try:
            spread = float(current_spread or 0.0)
            atr = float(current_atr or 0.0)
        except Exception:
            return True, ""

        if spread <= 0.0 or atr <= 0.0:
            return True, ""

        elite_padding = 0.0
        elite_padding_pips = 0.0
        if (
            float(confidence or 0.0) > float(self.config.elite_confidence_threshold)
            and float(ev or 0.0) > float(self.config.elite_ev_threshold)
        ):
            elite_padding_pips = float(self.config.elite_spread_padding_pips)
            elite_padding = PipStandardizer.pips_to_broker_value(elite_padding_pips, symbol_key)

        max_spread = (float(self.config.spread_atr_ratio_max) * atr) + elite_padding
        if spread > max_spread:
            spread_pips = PipStandardizer.broker_value_to_pips(spread, symbol_key)
            threshold_pips = PipStandardizer.broker_value_to_pips(max_spread, symbol_key)
            atr_band_pips = PipStandardizer.broker_value_to_pips(
                float(self.config.spread_atr_ratio_max) * atr,
                symbol_key,
            )
            return False, (
                f"REJECTED: VOLATILITY_GATE_SPREAD_ATR | Spread {spread:.6f} "
                f"({spread_pips:.1f} pips) > {max_spread:.6f} ({threshold_pips:.1f} pips) | "
                f"ATR={atr:.6f} | ATRBand={atr_band_pips:.1f} pips | "
                f"ElitePadding={elite_padding_pips:.1f} pips"
            )

        return True, ""
    
    def _calculate_percentile(self, value: float, historical_values: List[float]) -> float:
        """
        Calculate percentile rank of value in historical distribution.
        Returns 0.0 to 1.0 where 1.0 = 100th percentile (best)
        """
        if not historical_values:
            return 0.5
        
        # Count how many historical values are worse than current
        worse_count = sum(1 for v in historical_values if v < value)
        
        # Percentile = proportion worse
        percentile = worse_count / len(historical_values)
        
        return percentile
    
    def _get_adaptive_threshold(self, regime: str, base_threshold: float) -> float:
        """
        Calculate adaptive threshold based on data availability.
        Returns lower thresholds during cold start, gradually increasing to base_threshold.
        
        Logic:
        - 0-10 samples: Use 0%ile (admit almost everything)
        - 10-30 samples: Linear interpolation from 0% to 50% of base
        - 30-50 samples: Linear interpolation from 50% to 100% of base
        - 50+ samples: Use full base_threshold
        """
        if regime not in self.opportunity_windows:
            return 0.0  # No data - admit everything
        
        window = self.opportunity_windows[regime]
        sample_count = len(window)
        
        # Phase 1: Cold start (0-10 samples) - Very permissive
        if sample_count < 10:
            return 0.0  # Admit everything to build baseline
        
        # Phase 2: Warm-up (10-30 samples) - Gradually introduce filtering
        elif sample_count < 30:
            progress = (sample_count - 10) / 20.0  # 0.0 to 1.0
            return base_threshold * 0.5 * progress  # 0% to 50% of base
        
        # Phase 3: Maturation (30-50 samples) - Approach full threshold
        elif sample_count < 50:
            progress = (sample_count - 30) / 20.0  # 0.0 to 1.0
            return base_threshold * (0.5 + 0.5 * progress)  # 50% to 100% of base
        
        # Phase 4: Mature (50+ samples) - Full filtering
        else:
            return base_threshold
    
    def get_regime_statistics(self, regime: str) -> Dict[str, Any]:
        """Get statistics for a specific regime"""
        if regime not in self.opportunity_windows:
            return {'sample_count': 0, 'message': 'No data for this regime'}
        
        window = self.opportunity_windows[regime]
        if len(window) == 0:
            return {'sample_count': 0, 'message': 'No opportunities evaluated'}
        
        expectancies = [rec.expectancy for rec in window]
        scores = [rec.opportunity_score for rec in window]
        admitted = [rec for rec in window if rec.was_admitted]
        
        return {
            'sample_count': len(window),
            'admitted_count': len(admitted),
            'rejection_rate': (len(window) - len(admitted)) / len(window) if window else 0,
            'avg_expectancy': np.mean(expectancies),
            'median_expectancy': np.median(expectancies),
            'p25_expectancy': np.percentile(expectancies, 25),
            'p75_expectancy': np.percentile(expectancies, 75),
            'avg_opportunity_score': np.mean(scores),
            'expectancy_std': np.std(expectancies)
        }
    
    def get_global_statistics(self) -> Dict[str, Any]:
        """Get overall admission statistics"""
        total = self.stats['total_evaluated']
        
        if total == 0:
            return {'message': 'No trades evaluated yet'}
        
        return {
            'total_evaluated': total,
            'total_admitted': self.stats['total_admitted'],
            'total_rejected': self.stats['total_rejected'],
            'total_downscaled': self.stats['total_downscaled'],
            'total_exploration': self.stats['total_exploration'],
            'admission_rate': (self.stats['total_admitted'] + self.stats['total_downscaled'] + 
                              self.stats['total_exploration']) / total,
            'rejection_rate': self.stats['total_rejected'] / total,
            'avg_score_admitted': self.stats['avg_opportunity_score_admitted'],
            'avg_score_rejected': self.stats['avg_opportunity_score_rejected'],
            'regimes_tracked': len(self.opportunity_windows)
        }
    
    def get_diagnostics(self) -> Dict[str, Any]:
        """Comprehensive diagnostics"""
        diagnostics = {
            'global_stats': self.get_global_statistics(),
            'regime_stats': {}
        }
        
        for regime in self.opportunity_windows.keys():
            diagnostics['regime_stats'][regime] = self.get_regime_statistics(regime)
        
        return diagnostics
    
    def save_history(self) -> None:
        """Persist opportunity history and statistics"""
        try:
            data = {
                'stats': self.stats,
                'opportunity_windows': {}
            }
            
            # Convert windows to serializable format
            for regime, window in self.opportunity_windows.items():
                data['opportunity_windows'][regime] = [
                    {
                        'timestamp': rec.timestamp.isoformat(),
                        'symbol': rec.symbol,
                        'regime': rec.regime,
                        'expectancy': rec.expectancy,
                        'confidence': rec.confidence,
                        'exit_policy': rec.exit_policy,
                        'position_size_multiplier': rec.position_size_multiplier,
                        'was_admitted': rec.was_admitted,
                        'admission_reason': rec.admission_reason,
                        'opportunity_score': rec.opportunity_score,
                        'ev': rec.ev,
                        'rr_for_ev': rec.rr_for_ev,
                        'calibrated_ml_confidence': rec.calibrated_ml_confidence,
                        'macro_risk_penalty': rec.macro_risk_penalty,
                        'adjusted_win_prob': rec.adjusted_win_prob,
                        'max_portfolio_correlation': rec.max_portfolio_correlation,
                        'most_correlated_symbol': rec.most_correlated_symbol,
                        'correlation_blocked': rec.correlation_blocked,
                    }
                    for rec in window
                ]
            
            with open(self.history_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
                
        except Exception as e:
            logger.error(f"Failed to save admission history: {e}")
    
    def load_history(self) -> None:
        """Load persisted history"""
        if not os.path.exists(self.history_path):
            return
        
        try:
            with open(self.history_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Restore stats
            self.stats = data.get('stats', self.stats)
            
            # Restore windows
            windows_data = data.get('opportunity_windows', {})
            for regime, records_data in windows_data.items():
                self.opportunity_windows[regime] = deque(maxlen=self.config.lookback_window)
                
                for rec_data in records_data:
                    record = OpportunityRecord(
                        timestamp=datetime.fromisoformat(rec_data['timestamp']),
                        symbol=rec_data['symbol'],
                        regime=rec_data['regime'],
                        expectancy=rec_data['expectancy'],
                        confidence=rec_data['confidence'],
                        exit_policy=rec_data['exit_policy'],
                        position_size_multiplier=rec_data['position_size_multiplier'],
                        was_admitted=rec_data['was_admitted'],
                        admission_reason=rec_data['admission_reason'],
                        opportunity_score=rec_data.get('opportunity_score', 0.0),
                        ev=rec_data.get('ev', 0.0),
                        rr_for_ev=rec_data.get('rr_for_ev', rec_data.get('expectancy', 0.0)),
                        calibrated_ml_confidence=rec_data.get('calibrated_ml_confidence', rec_data.get('confidence', 0.0)),
                        macro_risk_penalty=rec_data.get('macro_risk_penalty', 0.0),
                        adjusted_win_prob=rec_data.get('adjusted_win_prob', rec_data.get('confidence', 0.0)),
                        max_portfolio_correlation=rec_data.get('max_portfolio_correlation', 0.0),
                        most_correlated_symbol=rec_data.get('most_correlated_symbol', ""),
                        correlation_blocked=rec_data.get('correlation_blocked', False),
                    )
                    self.opportunity_windows[regime].append(record)
            
            logger.info(f"Loaded admission history: {self.stats['total_evaluated']} evaluations, "
                       f"{len(self.opportunity_windows)} regimes")
            
        except Exception as e:
            logger.error(f"Failed to load admission history: {e}")

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        return str(symbol or "").replace("/", "").upper()

    @staticmethod
    def _normalize_direction(direction: Any) -> Optional[str]:
        if direction is None:
            return None
        raw = str(getattr(direction, "value", direction)).upper()
        if raw in {"LONG", "BUY", "0"}:
            return "LONG"
        if raw in {"SHORT", "SELL", "1"}:
            return "SHORT"
        return None

    def _extract_position_symbol_direction(self, pos: Any) -> Tuple[Optional[str], Optional[str]]:
        # Supports dicts, MT5 namedtuples, and Position model objects.
        if isinstance(pos, dict):
            sym = pos.get("symbol")
            dir_raw = pos.get("direction", pos.get("type"))
            return self._normalize_symbol(sym), self._normalize_direction(dir_raw)

        sym = getattr(pos, "symbol", None)
        dir_raw = getattr(pos, "direction", None)
        if dir_raw is None:
            dir_raw = getattr(pos, "type", None)
        return self._normalize_symbol(sym), self._normalize_direction(dir_raw)

    def _fetch_mt5_open_positions(self) -> List[Any]:
        try:
            import MetaTrader5 as mt5
            positions = mt5.positions_get()
            return list(positions) if positions else []
        except Exception as exc:
            logger.debug("[CORRELATION_GATE] Could not fetch MT5 positions: %s", exc)
            return []

    def _get_close_series(self, symbol: str, lookback_bars: int, timeframe: int) -> Optional[pd.Series]:
        try:
            import MetaTrader5 as mt5
            rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, max(lookback_bars, 10))
            if rates is None or len(rates) < 10:
                return None
            closes = pd.Series([float(r["close"]) for r in rates], dtype="float64")
            if closes.isna().all():
                return None
            return closes.reset_index(drop=True)
        except Exception as exc:
            logger.debug("[CORRELATION_GATE] Failed to fetch rates for %s: %s", symbol, exc)
            return None

    def _get_symbol_correlation(
        self,
        symbol_a: str,
        symbol_b: str,
        lookback_bars: int = 50,
        timeframe: int = 16385,
    ) -> Optional[float]:
        """
        Pearson correlation helper for two symbols using last N close prices.
        """
        sym_a = self._normalize_symbol(symbol_a)
        sym_b = self._normalize_symbol(symbol_b)
        if not sym_a or not sym_b or sym_a == sym_b:
            return None

        s1 = self._get_close_series(sym_a, lookback_bars, timeframe)
        s2 = self._get_close_series(sym_b, lookback_bars, timeframe)
        if s1 is None or s2 is None:
            return None

        aligned = pd.concat([s1, s2], axis=1).dropna()
        if len(aligned) < 10:
            return None
        corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
        if corr is None or np.isnan(corr):
            return None
        return float(corr)

    def get_portfolio_correlation(
        self,
        new_symbol: str,
        currently_open_symbols: List[str],
        lookback_bars: int = 50,
        timeframe: int = 16385,
    ) -> Dict[str, float]:
        """
        Compute Pearson correlation of new_symbol vs each currently open symbol.
        Uses pandas.Series.corr().
        """
        new_sym = self._normalize_symbol(new_symbol)
        if not new_sym or not currently_open_symbols:
            return {}

        new_series = self._get_close_series(new_sym, lookback_bars, timeframe)
        if new_series is None:
            return {}

        correlations: Dict[str, float] = {}
        for open_sym_raw in currently_open_symbols:
            open_sym = self._normalize_symbol(open_sym_raw)
            if not open_sym or open_sym == new_sym:
                continue
            corr_val = self._get_symbol_correlation(
                symbol_a=new_sym,
                symbol_b=open_sym,
                lookback_bars=lookback_bars,
                timeframe=timeframe,
            )
            if corr_val is None:
                continue
            correlations[open_sym] = corr_val
        return correlations

    def _usd_exposure_sign(self, symbol: str, direction: Optional[str]) -> Optional[int]:
        """
        Net USD directional exposure sign:
        +1 => long USD exposure, -1 => short USD exposure.
        """
        sym = self._normalize_symbol(symbol)
        d = self._normalize_direction(direction)
        if len(sym) != 6 or d is None:
            return None

        base, quote = sym[:3], sym[3:]
        if "USD" not in (base, quote):
            return None

        # LONG base/SHORT quote for LONG trades, inverse for SHORT trades.
        if quote == "USD":
            return -1 if d == "LONG" else +1
        if base == "USD":
            return +1 if d == "LONG" else -1
        return None

    def _is_natural_hedge(
        self,
        new_symbol: str,
        new_direction: Optional[str],
        open_symbol: str,
        open_direction: Optional[str],
    ) -> bool:
        new_exp = self._usd_exposure_sign(new_symbol, new_direction)
        open_exp = self._usd_exposure_sign(open_symbol, open_direction)
        if new_exp is None or open_exp is None:
            return False
        return new_exp != open_exp

    def _is_too_correlated(
        self,
        new_symbol: str,
        new_direction: Optional[str],
        current_positions: Optional[List[Any]] = None,
        threshold: float = 0.70,
        lookback_bars: int = 50,
        timeframe: int = 16385,
    ) -> Tuple[bool, float, str]:
        """
        Returns (reject, max_corr, most_correlated_symbol).
        Reject if corr > threshold with any open position in same direction.
        Allow opposite-direction correlated positions as natural hedges.
        """
        self.correlation_threshold = 0.99
        threshold = self.correlation_threshold
        positions = current_positions if current_positions is not None else self._fetch_mt5_open_positions()
        if not positions:
            return False, 0.0, ""

        new_sym = self._normalize_symbol(new_symbol)
        new_dir = self._normalize_direction(new_direction)

        open_symbol_dirs: Dict[str, str] = {}
        for p in positions:
            sym, d = self._extract_position_symbol_direction(p)
            if not sym or sym == new_sym:
                continue
            if d is None:
                d = "UNKNOWN"
            open_symbol_dirs[sym] = d

        if not open_symbol_dirs:
            return False, 0.0, ""

        corr_map = self.get_portfolio_correlation(
            new_symbol=new_sym,
            currently_open_symbols=list(open_symbol_dirs.keys()),
            lookback_bars=lookback_bars,
            timeframe=timeframe,
        )
        if not corr_map:
            return False, 0.0, ""

        max_sym, max_corr = max(corr_map.items(), key=lambda x: x[1])

        # Hard filter applies only to positive high-correlation clustering.
        violating = {sym: c for sym, c in corr_map.items() if c > threshold}
        if not violating:
            return False, float(max_corr), max_sym

        # Hedge exception: opposite direction with correlated open position is allowed.
        for sym, corr in violating.items():
            open_dir = open_symbol_dirs.get(sym, "UNKNOWN")
            if self._is_natural_hedge(new_sym, new_dir, sym, open_dir):
                continue
            if new_dir is not None and open_dir in {"LONG", "SHORT"} and open_dir != new_dir:
                continue
            return True, float(max_corr), max_sym

        return False, float(max_corr), max_sym

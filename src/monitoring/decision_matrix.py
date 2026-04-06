"""
Decision Matrix - Autonomous Trading Governance

Converts trading metrics into actionable decisions:
- Risk reduction triggers
- Capital scaling recommendations
- Filter adjustment signals
- Emergency safeguards
"""

import logging
import os
import json
import csv
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Tuple, Any
from collections import deque

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk assessment levels"""
    CRITICAL = "CRITICAL"      # Immediate action required
    HIGH = "HIGH"              # Scale down immediately
    ELEVATED = "ELEVATED"      # Caution mode
    NORMAL = "NORMAL"          # Operating normally
    OPTIMAL = "OPTIMAL"        # Scale up opportunity


class Action(Enum):
    """Automated governance actions"""
    EMERGENCY_CUTOFF = "EMERGENCY_CUTOFF"           # Stop trading entirely
    REDUCE_POSITION_75 = "REDUCE_POSITION_75"       # 75% position reduction
    REDUCE_POSITION_50 = "REDUCE_POSITION_50"       # 50% position reduction
    REDUCE_POSITION_25 = "REDUCE_POSITION_25"       # 25% position reduction
    MAINTAIN_CURRENT = "MAINTAIN_CURRENT"           # Keep current sizing
    INCREASE_POSITION_25 = "INCREASE_POSITION_25"   # 25% position increase
    INCREASE_POSITION_50 = "INCREASE_POSITION_50"   # 50% position increase
    AGGRESSIVE_ENGAGEMENT = "AGGRESSIVE_ENGAGEMENT" # Emergency execution-forward mode
    DEFENSIVE_PRESERVATION = "DEFENSIVE_PRESERVATION" # Macro-risk defense mode
    RELAX_FILTERS = "RELAX_FILTERS"                 # Loosen entry filters
    TIGHTEN_FILTERS = "TIGHTEN_FILTERS"             # Tighten entry filters
    REVIEW_REQUIRED = "REVIEW_REQUIRED"             # Manual review needed


@dataclass
class MetricsSnapshot:
    """Current state of all metrics"""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Daily metrics
    win_rate: float = 0.0
    trades_taken: int = 0
    trades_rejected: int = 0
    rejection_rate: float = 0.0
    avg_volatility: float = 0.0
    position_multiplier: float = 0.9
    max_consecutive_losses: int = 0
    daily_pnl: float = 0.0
    equity: float = 96500.0  # Default to base if not provided
    
    # Weekly metrics (if available)
    mean_r_multiple: float = 0.0
    sharpe_ratio: float = 0.0
    tail_loss_99: float = 0.0  # Negative value (e.g., -2.16)
    volatility_correlation: float = 0.0
    rejection_accuracy: str = "UNKNOWN"  # "GOOD", "BROKEN", "NEUTRAL"
    macro_risk: float = 0.0
    macro_risk_reason: str = "No_Macro_Risk"
    
    # Rolling series (for trend analysis)
    sharpe_rolling_3week: float = 0.0
    max_drawdown_rolling: float = 0.0
    volatility_stability: float = 0.0  # StdDev of volatility


@dataclass
class DecisionMatrixResult:
    """Result of decision matrix evaluation"""
    risk_level: RiskLevel = RiskLevel.NORMAL
    primary_action: Action = Action.MAINTAIN_CURRENT
    secondary_actions: List[Action] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)  # What triggered this
    severity_score: float = 0.0  # 0-100, higher = worse
    confidence: float = 1.0  # 0-1, how confident in the decision
    recommendation: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DecisionMatrix:
    """
    Autonomous governance system that converts metrics into actions.
    
    Philosophy: Metrics are only valuable if they drive decisions.
    This system makes decisions transparent and auditable.
    """
    
    def __init__(self, lookback_days: int = 21):
        """
        Initialize decision matrix.
        
        Args:
            lookback_days: Days to track for rolling averages
        """
        self.lookback_days = lookback_days
        self.metric_history: deque = deque(maxlen=lookback_days * 24)  # Hourly samples
        self.decision_history: List[DecisionMatrixResult] = []
        self.last_decision_time = datetime.now(timezone.utc)
        self.min_warmup_trades = 15  # Minimum trades before complex metrics matter
        self.logger = logging.getLogger("[DECISION_MATRIX]")
        self._last_warmup_log_trades = -1  # Track last trades count when we logged warmup
        self._force_governance_until = datetime.now(timezone.utc) + timedelta(hours=4)
        self.severity = 50.0
        self.performance_weights: Dict[str, float] = {}
        self._evaluations: List[Dict[str, Any]] = []
        self.is_ready: bool = False
        self._weights_ready_event = asyncio.Event()
        
        logger.info(f"[OK] Decision Matrix initialized - Lookback: {lookback_days} days")

    def load_weights(self, data: Dict[str, Any]) -> bool:
        """Load validated weight data into the decision matrix and mark it ready."""
        weights: Dict[str, float] = {}
        for key, val in (data or {}).items():
            try:
                weights[str(key)] = float(val)
            except Exception:
                continue

        if not weights:
            self.is_ready = False
            self._weights_ready_event.clear()
            return False

        self.performance_weights = weights
        self.is_ready = True
        self._weights_ready_event.set()
        self._evaluations = [{
            "source": "weights",
            "loaded_at": datetime.now(timezone.utc),
            "count": len(weights),
        }]
        self.logger.info(
            "[DECISION_MATRIX] Loaded %d performance weights.",
            len(weights),
        )
        return True

    async def wait_for_weights(self, timeout: Optional[float] = None) -> bool:
        """Wait until weights are loaded and the matrix is ready."""
        if self.is_ready:
            return True
        try:
            await asyncio.wait_for(self._weights_ready_event.wait(), timeout=timeout)
            return self.is_ready
        except asyncio.TimeoutError:
            return False

    def load_performance_weights(
        self,
        json_path: Optional[str] = None,
        csv_path: Optional[str] = None,
    ) -> bool:
        """
        Load Decision Matrix performance weights from JSON or CSV.
        Returns True when weights are loaded successfully.
        """
        json_path = json_path or os.environ.get("DECISION_MATRIX_WEIGHTS_JSON")
        csv_path = csv_path or os.environ.get("DECISION_MATRIX_WEIGHTS_CSV")
        if not json_path:
            json_path = os.path.join(os.getcwd(), "data", "decision_matrix_weights.json")
        if not csv_path:
            csv_path = os.path.join(os.getcwd(), "data", "decision_matrix_weights.csv")

        weights: Dict[str, float] = {}
        try:
            if json_path and os.path.exists(json_path):
                with open(json_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    for key, val in raw.items():
                        try:
                            weights[str(key)] = float(val)
                        except Exception:
                            continue
        except Exception as exc:
            self.logger.warning("[DECISION_MATRIX] Failed to load JSON weights: %s", exc)

        if not weights:
            try:
                if csv_path and os.path.exists(csv_path):
                    with open(csv_path, "r", encoding="utf-8") as f:
                        reader = csv.DictReader(f)
                        if reader.fieldnames:
                            for row in reader:
                                key = row.get("metric") or row.get("name") or row.get("key")
                                val = row.get("weight") or row.get("value")
                                if key is None or val is None:
                                    continue
                                try:
                                    weights[str(key)] = float(val)
                                except Exception:
                                    continue
                        else:
                            f.seek(0)
                            simple_reader = csv.reader(f)
                            for row in simple_reader:
                                if len(row) < 2:
                                    continue
                                try:
                                    weights[str(row[0])] = float(row[1])
                                except Exception:
                                    continue
            except Exception as exc:
                self.logger.warning("[DECISION_MATRIX] Failed to load CSV weights: %s", exc)

        return self.load_weights(weights)

    def get_governance_state(self, metrics: Optional[MetricsSnapshot] = None) -> Tuple[Action, float]:
        """
        Dynamic governor state. Macro risk can override aggressive posture.
        """
        macro_risk = float(getattr(metrics, "macro_risk", 0.0) or 0.0)
        macro_reason = str(getattr(metrics, "macro_risk_reason", "") or "").upper()
        technical_only_mode = bool(getattr(metrics, "technical_only_mode", False))
        forced_execution = bool(getattr(metrics, "forced_execution", False))
        high_impact_pending = ("HIGH_IMPACT_NEWS_PENDING" in macro_reason) and macro_risk >= 0.10
        elevated_macro = macro_risk >= 0.25
        if elevated_macro or high_impact_pending:
            if technical_only_mode and forced_execution:
                return Action.DEFENSIVE_PRESERVATION, 30.0
            return Action.DEFENSIVE_PRESERVATION, max(70.0, float(getattr(self, "severity", 50.0)))
        if float(getattr(self, "severity", 50.0)) <= 10.0:
            return Action.AGGRESSIVE_ENGAGEMENT, 10.0
        return Action.MAINTAIN_CURRENT, 50.0
    
    def evaluate(self, metrics: MetricsSnapshot) -> DecisionMatrixResult:
        """
        Evaluate current metrics and generate decision.
        
        Returns:
            DecisionMatrixResult with action and reasoning
        """
        self.metric_history.append(metrics)
        
        result = DecisionMatrixResult()
        result.timestamp = metrics.timestamp
        forced_action, forced_severity = self.get_governance_state(metrics)
        if forced_action in {Action.AGGRESSIVE_ENGAGEMENT, Action.DEFENSIVE_PRESERVATION}:
            result.risk_level = (
                RiskLevel.HIGH if forced_action == Action.DEFENSIVE_PRESERVATION else RiskLevel.NORMAL
            )
            result.primary_action = forced_action
            if forced_action == Action.DEFENSIVE_PRESERVATION:
                result.triggers = [
                    f"Macro risk elevated: {float(getattr(metrics, 'macro_risk', 0.0) or 0.0):.2f}",
                    str(getattr(metrics, "macro_risk_reason", "Macro risk override") or "Macro risk override"),
                ]
                result.recommendation = "MACRO GOV: Defensive preservation engaged"
            else:
                result.triggers = ["Governor allows aggressive engagement while macro risk remains low"]
                result.recommendation = "GOVERNOR: Aggressive engagement permitted"
            result.severity_score = forced_severity
            self._log_decision(result)
            return result
        
        # Step 1: Check emergency conditions (CRITICAL)
        emergency_action, emergency_triggers = self._check_emergency_conditions(metrics)
        if emergency_action != Action.MAINTAIN_CURRENT:
            result.risk_level = RiskLevel.CRITICAL
            result.primary_action = emergency_action
            result.triggers = emergency_triggers
            result.severity_score = 95.0
            result.recommendation = "⚠️ EMERGENCY: Immediate risk reduction required"
            self._log_decision(result)
            return result
        
        # Step 2: Check high-risk conditions
        high_risk_action, high_risk_triggers = self._check_high_risk(metrics)
        if high_risk_action != Action.MAINTAIN_CURRENT:
            result.risk_level = RiskLevel.HIGH
            result.primary_action = high_risk_action
            result.triggers = high_risk_triggers
            result.severity_score = 75.0
            result.recommendation = "🔴 HIGH RISK: Reduce position sizing immediately"
            self._log_decision(result)
            return result
        
        # Step 3: Check elevated-risk conditions
        elevated_action, elevated_triggers = self._check_elevated_risk(metrics)
        if elevated_action != Action.MAINTAIN_CURRENT:
            result.risk_level = RiskLevel.ELEVATED
            result.primary_action = elevated_action
            result.triggers = elevated_triggers
            result.severity_score = 50.0
            result.recommendation = "🟠 CAUTION: Enter monitoring mode"
            self._log_decision(result)
            return result
        
        # Step 4: Check optimal conditions
        optimal_action, optimal_triggers = self._check_optimal_conditions(metrics)
        if optimal_action != Action.MAINTAIN_CURRENT:
            result.risk_level = RiskLevel.OPTIMAL
            result.primary_action = optimal_action
            result.triggers = optimal_triggers
            result.severity_score = 10.0
            result.recommendation = "🟢 OPTIMAL: Capital scale-up opportunity"
            self._log_decision(result)
            return result
        
        # Step 5: Normal operations
        result.risk_level = RiskLevel.NORMAL
        result.primary_action = Action.MAINTAIN_CURRENT
        result.triggers = ["All metrics within normal ranges"]
        result.severity_score = 50.0
        result.recommendation = "HARVEST GOV: Maintain current portfolio and sizing"
        self._log_decision(result)
        return result
    
    def _check_emergency_conditions(self, metrics: MetricsSnapshot) -> Tuple[Action, List[str]]:
        """Emergency cutoff conditions - Stop trading immediately"""
        triggers = []
        
        # Condition 1: Massive consecutive losses
        if metrics.max_consecutive_losses >= 10:
            triggers.append(f"Consecutive losses: {metrics.max_consecutive_losses} (threshold: 10)")
        
        # Condition 2: Account losing rapidly (Dynamic % based)
        daily_loss_threshold = metrics.equity * 0.02  # 2% of equity
        if metrics.daily_pnl < -daily_loss_threshold:
            triggers.append(f"Daily loss exceeds 2% equity: ${metrics.daily_pnl:.2f} (Limit: ${-daily_loss_threshold:.2f})")
        
        # Condition 3: Catastrophic tail loss
        if metrics.tail_loss_99 < -10:  # Loss worse than -10%
            triggers.append(f"Tail loss 99% critical: {metrics.tail_loss_99:.2f}% (threshold: -10%)")
        
        # Condition 4: Filter completely broken - rejecting 90%+ of winners
        if "BROKEN" in metrics.rejection_accuracy and metrics.trades_rejected > 50:
            triggers.append("Filter broken: Rejecting majority of potentially winning trades")
        
        if triggers:
            logger.critical(f"[EMERGENCY] Decision Matrix found critical conditions: {triggers}")
            return Action.EMERGENCY_CUTOFF, triggers
        
        return Action.MAINTAIN_CURRENT, []
    
    def _check_high_risk(self, metrics: MetricsSnapshot) -> Tuple[Action, List[str]]:
        """High-risk conditions - Reduce position sizing"""
        triggers = []
        
        # ===== STRICT OPERATIONAL OVERRIDE (Warm-up Logic) =====
        # PATCH #1 & #2: Bypass all performance triggers until 15-trade warm-up threshold is crossed
        # Treat Sharpe Ratio of 0.000 as "Neutral" rather than "Declining"
        if metrics.trades_taken < self.min_warmup_trades:
            # During warm-up period, log only once per new trade (prevent duplicate logs)
            if metrics.trades_taken != self._last_warmup_log_trades:
                logger.info(
                    f"[STRICT OPERATIONAL OVERRIDE] Warm-up period active ({metrics.trades_taken}/{self.min_warmup_trades} trades). "
                    f"Risk: OPERATIONAL. Ignoring Sharpe Ratio penalties until threshold crossed."
                )
                self._last_warmup_log_trades = metrics.trades_taken
            return Action.MAINTAIN_CURRENT, []
        
        # Treat Sharpe of 0.000 as neutral (no data yet) rather than declining
        # This prevents self-punishing loops when the bot has just started
        if abs(metrics.sharpe_ratio) < 0.001:  # 0.000 or nearly zero
            logger.debug(
                f"[SHARPE RATIO NEUTRAL] Detected Sharpe={metrics.sharpe_ratio:.3f} (treat as neutral state). "
                f"Bypassing Sharpe-based risk penalties until meaningful data accumulates."
            )
            # Don't use Sharpe as a penalty trigger for first batch of trades
            if metrics.trades_taken < 30:
                return Action.MAINTAIN_CURRENT, []
        
        # Condition 1: Poor tail loss + Poor Sharpe + Bad filter
        tail_bad = metrics.tail_loss_99 < -6  # Worse than -6%
        sharpe_bad = metrics.sharpe_ratio < 0.7
        filter_bad = "BROKEN" in metrics.rejection_accuracy or "DEGRADED" in metrics.rejection_accuracy
        
        if tail_bad and sharpe_bad and filter_bad:
            triggers.append(f"Tail loss {metrics.tail_loss_99:.2f}% + Sharpe {metrics.sharpe_ratio:.2f} + Bad filter")
        
        # Condition 2: High consecutive losses with poor win rate
        if metrics.max_consecutive_losses >= 5 and metrics.win_rate < 50:
            triggers.append(f"Losing streak {metrics.max_consecutive_losses} with {metrics.win_rate:.1f}% win rate")
        
        # Condition 3: Rejection rate too high without good filter
        if metrics.rejection_rate > 85 and "GOOD" not in metrics.rejection_accuracy:
            triggers.append(f"High rejection {metrics.rejection_rate:.1f}% without good filter assessment")
        
        # ===== PATCH #7: HARD-SILENCE MEAN R-MULTIPLE WARNINGS DURING WARM-UP =====
        # Condition 4: Mean R-multiple negative or near-zero (skip during warm-up)
        if metrics.trades_taken >= self.min_warmup_trades:
            if metrics.mean_r_multiple < 0.5:
                triggers.append(f"Mean R-multiple poor: {metrics.mean_r_multiple:.2f}R (threshold: 0.5R)")
        else:
            # During warm-up, do NOT log Mean R warnings
            logger.debug(
                f"[MEAN_R_SILENCE-HARD] Cycle warm-up ({metrics.trades_taken}/{self.min_warmup_trades}). "
                f"Mean R-multiple warning suppressed (value: {metrics.mean_r_multiple:.2f}R)."
            )
        
        if triggers:
            # Ghost Risk elimination: Ensure we have a baseline before reducing position
            if metrics.trades_taken == 0:
                logger.debug(f"[GHOST RISK BYPASS] Potential risk detected but skipping as trade baseline is zero")
                return Action.MAINTAIN_CURRENT, []
                
            # Warm-up Period: Defer complex metric assessment until enough trades
            if metrics.trades_taken < self.min_warmup_trades:
                # Still check for severe loss streaks even in warm-up
                if metrics.max_consecutive_losses < 4:
                    logger.info(f"[WARM-UP] Risk assessment deferred until {self.min_warmup_trades} trades (Current: {metrics.trades_taken})")
                    return Action.MAINTAIN_CURRENT, []

            # Governance: Only trigger position reduction if we have a minimum sample size
            if metrics.trades_taken >= 5:
                # Self-Punishing Loop Fix: Maintain Operational if drawdown is statistically insignificant (< 0.05%)
                total_equity = metrics.equity
                drawdown_pct = abs(metrics.daily_pnl) / total_equity if total_equity > 0 else 0
                if drawdown_pct < 0.0005: # less than 0.05%
                    logger.debug(f"[DD SAFEGUARD] Drawdown {drawdown_pct:.4%} is within floor (0.05%), maintaining Operational status")
                    return Action.MAINTAIN_CURRENT, []

                logger.warning(f"[HIGH RISK] Reducing position sizing: {triggers}")
                return Action.REDUCE_POSITION_50, triggers
            else:
                logger.info(f"[HIGH RISK DEFERRED] Potential risk detected but sample size too small ({metrics.trades_taken} < 5): {triggers}")
        
        return Action.MAINTAIN_CURRENT, []
    
    def _check_elevated_risk(self, metrics: MetricsSnapshot) -> Tuple[Action, List[str]]:
        """Elevated-risk conditions - Light position reduction"""
        triggers = []
        
        # ===== PATCH #7: HARD-SILENCE SHARPE RATIO AND MEAN R WARNINGS DURING WARM-UP =====
        # During warm-up phase (first N trades), skip ALL Sharpe and Mean R analysis
        # to prevent log clutter from incomplete statistical data and false signals
        if metrics.trades_taken < self.min_warmup_trades:
            # Silent pass during warm-up - no Sharpe, no Mean R warnings
            logger.debug(
                f"[SHARPE-SILENCE-HARD] Cycle warm-up ({metrics.trades_taken}/{self.min_warmup_trades}). "
                f"All Sharpe and Mean R warnings suppressed."
            )
            return Action.MAINTAIN_CURRENT, []
        
        # ===== POST WARM-UP: NORMAL SHARPE ANALYSIS =====
        if -6 <= metrics.tail_loss_99 < -3:
            triggers.append(f"Tail loss elevated: {metrics.tail_loss_99:.2f}%")
        
        # Condition 3: Win rate below 50% but above 45%
        if 45 <= metrics.win_rate < 50:
            triggers.append(f"Win rate below 50%: {metrics.win_rate:.1f}%")
        
        # Condition 4: High volatility impact on returns
        if metrics.volatility_correlation < -0.6:  # Strategy loses in volatile markets
            triggers.append(f"Negative volatility correlation: {metrics.volatility_correlation:.3f}")
        
        # Condition 5: Filter accuracy degrading
        if "DEGRADED" in metrics.rejection_accuracy and metrics.trades_rejected > 30:
            triggers.append("Filter showing signs of degradation")
        
        if triggers:
            logger.warning(f"[ELEVATED RISK] Caution mode: {triggers}")
            return Action.REDUCE_POSITION_25, triggers
        
        return Action.MAINTAIN_CURRENT, []
    
    def _check_optimal_conditions(self, metrics: MetricsSnapshot) -> Tuple[Action, List[str]]:
        """Optimal conditions - Scale up opportunity"""
        triggers = []
        
        # All conditions must be met for scale-up
        
        # Condition 1: Strong Sharpe ratio trend
        rolling_sharpe = self._get_rolling_sharpe()
        if rolling_sharpe < 1.2:
            return Action.MAINTAIN_CURRENT, []
        triggers.append(f"Rolling 3-week Sharpe strong: {rolling_sharpe:.3f}")
        
        # Condition 2: Drawdown within limits
        max_dd = self._get_rolling_max_drawdown()
        if max_dd < -15:
            return Action.MAINTAIN_CURRENT, []
        triggers.append(f"Max drawdown contained: {max_dd:.1f}%")
        
        # Condition 3: Volatility correlation stable
        if abs(metrics.volatility_correlation) > 0.4:  # Not too extreme
            return Action.MAINTAIN_CURRENT, []
        triggers.append(f"Volatility correlation stable: {metrics.volatility_correlation:.3f}")
        
        # Condition 4: Good filter accuracy
        if "GOOD" not in metrics.rejection_accuracy:
            return Action.MAINTAIN_CURRENT, []
        triggers.append("Filter providing good protection")
        
        # Condition 5: Mean R-multiple strong
        if metrics.mean_r_multiple < 1.2:
            return Action.MAINTAIN_CURRENT, []
        triggers.append(f"Mean R-multiple strong: {metrics.mean_r_multiple:.2f}R")
        
        if len(triggers) == 5:  # All conditions met
            logger.info(f"[OPTIMAL] Scale-up opportunity: {triggers}")
            # Bigger account = bigger scale up
            if metrics.trades_taken > 100:
                return Action.INCREASE_POSITION_50, triggers
            else:
                return Action.INCREASE_POSITION_25, triggers
        
        return Action.MAINTAIN_CURRENT, []
    
    def _get_rolling_sharpe(self) -> float:
        """Calculate rolling 3-week Sharpe ratio"""
        if len(self.metric_history) < 72:  # 3 weeks of hourly samples
            return 0.0
        
        recent = list(self.metric_history)[-72:]  # Last 3 weeks
        recent_sharpes = [m.sharpe_ratio for m in recent if m.sharpe_ratio > 0]
        
        if not recent_sharpes:
            return 0.0
        
        return sum(recent_sharpes) / len(recent_sharpes)
    
    def _get_rolling_max_drawdown(self) -> float:
        """Calculate rolling maximum drawdown"""
        if len(self.metric_history) < 24:
            return 0.0
        
        pnls = [m.daily_pnl for m in list(self.metric_history)[-168:]]  # 1 week
        if not pnls:
            return 0.0
        
        # Simplified: find largest cumulative loss
        cumulative = 0
        peak = 0
        max_dd = 0
        
        for pnl in pnls:
            cumulative += pnl
            peak = max(peak, cumulative)
            dd = cumulative - peak
            max_dd = min(max_dd, dd)
        
        return max_dd
    
    def _log_decision(self, result: DecisionMatrixResult) -> None:
        """Log decision for audit trail"""
        self.decision_history.append(result)
        
        emoji_map = {
            RiskLevel.CRITICAL: "🚨",
            RiskLevel.HIGH: "🔴",
            RiskLevel.ELEVATED: "🟠",
            RiskLevel.NORMAL: "🟡",
            RiskLevel.OPTIMAL: "🟢"
        }
        
        emoji = emoji_map.get(result.risk_level, "❓")
        
        logger.info(
            f"[DECISION_MATRIX] {emoji} {result.risk_level.value:10s} | "
            f"Action: {result.primary_action.value:25s} | "
            f"Severity: {result.severity_score:5.0f} | "
            f"Triggers: {len(result.triggers)}"
        )
        
        for trigger in result.triggers:
            logger.debug(f"  - {trigger}")
        
        logger.info(f"  → {result.recommendation}")
    
    def get_position_multiplier(self, base_multiplier: float, last_decision: Optional[DecisionMatrixResult] = None) -> float:
        """
        Adjust position multiplier based on latest decision.
        
        Args:
            base_multiplier: Original position multiplier (0.5 - 1.0)
            last_decision: Latest decision matrix result
        
        Returns:
            Adjusted multiplier
        """
        if not last_decision:
            return base_multiplier
        
        action_map = {
            Action.EMERGENCY_CUTOFF: 0.0,
            Action.REDUCE_POSITION_75: 0.25 * base_multiplier,
            Action.REDUCE_POSITION_50: 0.50 * base_multiplier,
            Action.REDUCE_POSITION_25: 0.75 * base_multiplier,
            Action.MAINTAIN_CURRENT: base_multiplier,
            Action.INCREASE_POSITION_25: base_multiplier * 1.25,
            Action.INCREASE_POSITION_50: base_multiplier * 1.50,
            Action.AGGRESSIVE_ENGAGEMENT: base_multiplier * 1.75,
            Action.DEFENSIVE_PRESERVATION: 0.50 * base_multiplier,
            Action.RELAX_FILTERS: base_multiplier,
            Action.TIGHTEN_FILTERS: base_multiplier,
            Action.REVIEW_REQUIRED: base_multiplier * 0.9,
        }
        
        multiplier = action_map.get(last_decision.primary_action, base_multiplier)
        
        # Clamp to valid range [0, 1.75]
        multiplier = max(0.0, min(1.75, multiplier))
        
        return multiplier
    
    def should_trade(self, last_decision: Optional[DecisionMatrixResult] = None) -> bool:
        """
        Determine if trading should continue based on latest decision.
        
        Returns:
            True if trading allowed, False if cutoff is active
        """
        if not last_decision:
            return True
        
        return last_decision.primary_action != Action.EMERGENCY_CUTOFF
    
    def get_summary(self) -> Dict[str, any]:
        """Get summary of recent decisions"""
        if not self.decision_history:
            return {
                "total_decisions": 0,
                "latest_decision": None,
                "risk_level": "UNKNOWN",
                "action": "NONE"
            }
        
        latest = self.decision_history[-1]
        
        return {
            "total_decisions": len(self.decision_history),
            "latest_decision": latest.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "risk_level": latest.risk_level.value,
            "action": latest.primary_action.value,
            "severity": latest.severity_score,
            "recommendation": latest.recommendation,
            "triggers": latest.triggers
        }


from dataclasses import dataclass
import re
from typing import Any, Optional, Protocol

from src.runtime.contracts.commands import SignalIntent
from src.runtime.contracts.decisions import RiskDecision
from src.runtime.contracts.snapshots import MarketSnapshot, PortfolioSnapshot


class RiskPolicyEngine(Protocol):
    def evaluate(
        self,
        intent: SignalIntent,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
    ) -> RiskDecision:
        """Centralized risk decision for a signal intent."""
        ...


@dataclass(frozen=True)
class ExposureGuardDecision:
    allow_trade: bool
    size_multiplier: float
    effective_limit_pct: float
    proposed_exposure_pct: float
    total_open_risk_pct: float
    requires_a_plus: bool
    high_conviction_override: bool
    admission_buffer_pct: float
    reason: str


class AdaptiveRiskGuard:
    """
    Adaptive exposure guard for live signal admission.

    Behavior:
      - Hard blocks only beyond the true portfolio hard cap.
      - Elevated exposure invokes admission checks instead of blind rejection.
      - High-conviction / excellent-score signals can bypass the A+ label requirement.
      - When a trade would push exposure above the active limit, size is reduced rather
        than the signal being hard-blocked, unless the hard cap is breached.
      - When DISABLE_EXIT_AGGRESSION is True, allows slightly higher total margin usage
        since trades stay open longer and don't exit early.
    """

    def __init__(
        self,
        base_limit_pct: float = 2.0,
        hard_cap_pct: float = 60.0,  # Increased to 60.0% (DISABLE_EXIT_AGGRESSION active)
        admission_buffer_pct: float = 0.75,
        excellent_score_threshold: float = 60.0,
        elite_score_threshold: float = 80.0,
        risk_reduction_multiplier: float = 0.50,
        tier_a_floor_multiplier: float = 0.75,
        tier_b_floor_multiplier: float = 0.50,
    ):
        self.base_limit_pct = float(base_limit_pct)
        self.hard_cap_pct = float(hard_cap_pct)
        self.admission_buffer_pct = float(admission_buffer_pct)
        self.excellent_score_threshold = float(excellent_score_threshold)
        self.elite_score_threshold = float(elite_score_threshold)
        self.risk_reduction_multiplier = float(risk_reduction_multiplier)
        self.tier_a_floor_multiplier = float(tier_a_floor_multiplier)
        self.tier_b_floor_multiplier = float(tier_b_floor_multiplier)
        
        # Check if DISABLE_EXIT_AGGRESSION is enabled
        import os
        self.exit_aggression_disabled = str(os.environ.get("DISABLE_EXIT_AGGRESSION", "True")).lower() in {"1", "true", "yes", "on"}
        if self.exit_aggression_disabled:
            # Allow higher total margin usage since trades stay open longer
            # NOTE: hard_cap is already 60%, so we only modestly increase base_limit
            self.base_limit_pct = self.base_limit_pct * 1.5  # Increase from 2.0% to 3.0%
            # Don't increase hard_cap further - 60% is already very generous

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_pct_value(value: float) -> float:
        """
        Normalize mixed percent inputs:
        - 0.37 -> 0.37%
        - 37.0 -> 37.0%
        """
        val = float(value or 0.0)
        if 0.0 < val <= 1.0:
            return val * 100.0
        return val

    def _extract_signal_score(self, signal: Any) -> float:
        score = self._safe_float(getattr(signal, "adaptive_score", None), None)
        if score is None:
            score = self._safe_float(getattr(signal, "score", None), None)
        if score is None:
            score = self._safe_float(getattr(signal, "confidence", 0.0), 0.0)
            if score <= 1.0:
                score *= 100.0
        return float(score)

    @staticmethod
    def _extract_pair_currencies(symbol: str) -> set[str]:
        clean = str(symbol or "").replace("/", "").upper()
        if len(clean) >= 6:
            return {clean[:3], clean[3:6]}
        return set()

    @staticmethod
    def _extract_macro_currencies(reason: str) -> set[str]:
        return {token for token in re.findall(r"\b[A-Z]{3}\b", str(reason or "").upper())}

    def resolve_macro_shield_cap(
        self,
        signal: Any,
        symbol: str,
        macro_penalty: float,
        macro_reason: str,
    ) -> Optional[float]:
        macro_reason_upper = str(macro_reason or "").upper()
        macro_high = ("HIGH" in macro_reason_upper) or (float(macro_penalty or 0.0) >= 0.25)
        if not macro_high:
            return None

        trade_tier = str(getattr(signal, "trade_tier", "") or "").upper()
        signal_score = self._extract_signal_score(signal)
        pair_currencies = self._extract_pair_currencies(symbol)
        news_currencies = self._extract_macro_currencies(macro_reason_upper)
        pair_specific = bool(pair_currencies & news_currencies)
        tier_a_like = trade_tier == "TIER_A" or signal_score >= self.elite_score_threshold

        if pair_specific:
            return 0.50
        if tier_a_like:
            return 0.80
        return 0.50

    def evaluate_signal(
        self,
        signal: Any,
        total_open_risk_pct: float,
        proposed_trade_risk_pct: float,
        latest_decision: Optional[Any] = None,
        macro_reason: str = "",
        macro_penalty: float = 0.0,
    ) -> ExposureGuardDecision:
        conviction = None
        try:
            conviction = getattr(signal, "predictive_attribution", {}).get("Conviction")
        except Exception:
            conviction = None

        trade_tier = str(getattr(signal, "trade_tier", "") or "").upper()
        signal_score = self._extract_signal_score(signal)
        high_conviction_override = bool(
            conviction == "MAX"
            or trade_tier == "TIER_A"
            or signal_score >= self.elite_score_threshold
            or signal_score >= self.excellent_score_threshold
        )

        requires_a_plus = total_open_risk_pct > self.base_limit_pct
        effective_limit_pct = self.base_limit_pct
        if high_conviction_override and requires_a_plus:
            effective_limit_pct = min(
                self.hard_cap_pct,
                self.base_limit_pct + self.admission_buffer_pct,
            )

        total_open_risk_pct = self._normalize_pct_value(total_open_risk_pct)
        proposed_trade_risk_pct = self._normalize_pct_value(proposed_trade_risk_pct)

        # Hard single-trade ceiling regardless of signal strength.
        if proposed_trade_risk_pct > 2.0:
            return ExposureGuardDecision(
                allow_trade=False,
                size_multiplier=0.0,
                effective_limit_pct=min(self.hard_cap_pct, 2.0),
                proposed_exposure_pct=total_open_risk_pct + proposed_trade_risk_pct,
                total_open_risk_pct=total_open_risk_pct,
                requires_a_plus=True,
                high_conviction_override=high_conviction_override,
                admission_buffer_pct=0.0,
                reason="single_trade_exposure_cap",
            )

        proposed_exposure_pct = total_open_risk_pct + max(0.0, proposed_trade_risk_pct)

        if total_open_risk_pct > self.hard_cap_pct or proposed_exposure_pct > self.hard_cap_pct:
            return ExposureGuardDecision(
                allow_trade=False,
                size_multiplier=0.0,
                effective_limit_pct=self.hard_cap_pct,
                proposed_exposure_pct=proposed_exposure_pct,
                total_open_risk_pct=total_open_risk_pct,
                requires_a_plus=requires_a_plus,
                high_conviction_override=high_conviction_override,
                admission_buffer_pct=self.admission_buffer_pct if high_conviction_override else 0.0,
                reason="hard_cap_breached",
            )

        if requires_a_plus and not high_conviction_override:
            return ExposureGuardDecision(
                allow_trade=False,
                size_multiplier=0.0,
                effective_limit_pct=effective_limit_pct,
                proposed_exposure_pct=proposed_exposure_pct,
                total_open_risk_pct=total_open_risk_pct,
                requires_a_plus=True,
                high_conviction_override=False,
                admission_buffer_pct=0.0,
                reason="non_aplus_blocked",
            )

        size_multiplier = 1.0
        reason = "admitted"
        if total_open_risk_pct > self.base_limit_pct or proposed_exposure_pct > effective_limit_pct:
            size_multiplier *= self.risk_reduction_multiplier
            reason = "risk_reduction_mode"

        if latest_decision and getattr(latest_decision, "primary_action", None) is not None:
            if str(getattr(latest_decision.primary_action, "value", latest_decision.primary_action)) == "DEFENSIVE_PRESERVATION":
                technical_only_forced_relief = bool(
                    getattr(latest_decision, "technical_only_forced_relief", False)
                ) and float(getattr(latest_decision, "severity_score", 100.0) or 100.0) <= 30.0
                if not technical_only_forced_relief:
                    macro_cap = self.resolve_macro_shield_cap(
                        signal=signal,
                        symbol=str(getattr(signal, "symbol", "") or ""),
                        macro_penalty=float(macro_penalty or 0.0),
                        macro_reason=str(macro_reason or getattr(latest_decision, "reason", "") or ""),
                    )
                    if macro_cap is None:
                        macro_cap = 0.50
                    size_multiplier = min(size_multiplier, float(macro_cap))

        if trade_tier in {"TIER_A", "TIER_B"} and size_multiplier > 0.0:
            floor_multiplier = self.tier_a_floor_multiplier if trade_tier == "TIER_A" else self.tier_b_floor_multiplier
            floor_multiplier = max(0.0, min(1.0, floor_multiplier))
            if size_multiplier < floor_multiplier:
                size_multiplier = floor_multiplier
                reason = "conviction_floor_applied"

        return ExposureGuardDecision(
            allow_trade=True,
            size_multiplier=size_multiplier,
            effective_limit_pct=effective_limit_pct,
            proposed_exposure_pct=proposed_exposure_pct,
            total_open_risk_pct=total_open_risk_pct,
            requires_a_plus=requires_a_plus,
            high_conviction_override=high_conviction_override,
            admission_buffer_pct=self.admission_buffer_pct if high_conviction_override else 0.0,
            reason=reason,
        )

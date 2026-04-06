import logging
from typing import Any

from src.llm_governance import GovernanceInput
from src.runtime.ai.advisory_contracts import AdvisoryInput, AdvisoryOutcome


class RuntimeLLMAdvisoryEngine:
    """
    Phase 6 runtime wrapper around existing LLM governance.

    Enforces a strict advisory contract:
    - Allows only APPROVE / DEMOTE / REJECT / BYPASS outputs
    - Never modifies SL/TP or position size
    - Safe fallback to REJECT on adapter/runtime errors
    """

    def __init__(self, governance_client: Any, logger: logging.Logger | None = None):
        self.governance_client = governance_client
        self.logger = logger or logging.getLogger(__name__)

    def evaluate(
        self,
        advisory_input: AdvisoryInput,
        cycle: int,
        signal_forced: bool,
    ) -> AdvisoryOutcome:
        try:
            gov_input = GovernanceInput(
                symbol=advisory_input.symbol,
                regime=advisory_input.regime,
                rsi=float(advisory_input.rsi),
                adx=float(advisory_input.adx),
                atr=float(advisory_input.atr),
                rr_ratio=float(advisory_input.rr_ratio),
                ml_confidence=float(advisory_input.ml_confidence),
                volatility_pct=float(advisory_input.volatility_pct),
                forced_execution=bool(advisory_input.forced_execution),
                position_size=float(advisory_input.position_size),
                expectancy_multiplier=float(advisory_input.expectancy_multiplier),
            )
            decision = self.governance_client.evaluate(
                gov_input,
                cycle=cycle,
                signal_forced=bool(signal_forced),
            )
            return self._normalize(decision)
        except Exception as exc:
            self.logger.critical(
                "[RUNTIME_AI_ADVISORY] SAFE_REJECT | %s | %s",
                advisory_input.symbol,
                exc,
            )
            return AdvisoryOutcome(
                action="REJECT",
                confidence=0,
                reason="Runtime AI advisory exception",
                risk_flag=True,
                latency_ms=0.0,
                bypassed=False,
                bypass_reason=str(exc),
            )

    def _normalize(self, decision: Any) -> AdvisoryOutcome:
        action = "APPROVE"
        if getattr(decision, "bypassed", False):
            action = "BYPASS"
        elif getattr(decision, "rejected", False):
            action = "REJECT"
        elif getattr(decision, "demoted", False):
            action = "DEMOTE"

        return AdvisoryOutcome(
            action=action,
            confidence=int(getattr(decision, "confidence", 0)),
            reason=str(getattr(decision, "reason", "")),
            risk_flag=bool(getattr(decision, "risk_flag", False)),
            latency_ms=float(getattr(decision, "latency_ms", 0.0)),
            bypassed=bool(getattr(decision, "bypassed", False)),
            bypass_reason=str(getattr(decision, "bypass_reason", "")),
        )

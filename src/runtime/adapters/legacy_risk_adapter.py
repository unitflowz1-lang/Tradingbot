from datetime import datetime, timezone

from src.models import Direction, RiskAssessment, TradingSignal
from src.risk.risk_calculator import RiskCalculator
from src.runtime.contracts.commands import SignalIntent
from src.runtime.contracts.decisions import RiskDecision
from src.runtime.contracts.snapshots import MarketSnapshot, PortfolioSnapshot
from src.runtime.risk.policy_engine import RiskPolicyEngine


class LegacyRiskAdapter(RiskPolicyEngine):
    """
    Adapter for existing RiskCalculator.
    Phase 1 behavior: delegate risk validity to legacy calculator.
    """

    def __init__(self, risk_calculator: RiskCalculator):
        self.risk_calculator = risk_calculator

    def evaluate(
        self,
        intent: SignalIntent,
        portfolio: PortfolioSnapshot,
        market: MarketSnapshot,
    ) -> RiskDecision:
        signal = self._to_signal(intent)
        assessment: RiskAssessment = self.risk_calculator.assess_trade_risk(
            signal=signal,
            portfolio=portfolio.portfolio,
            market_data=None,
        )

        capped_qty = 0.0 if not assessment.is_valid else max(assessment.position_size, 0.01)
        return RiskDecision(
            approved=assessment.is_valid,
            reason_code="APPROVED" if assessment.is_valid else "RISK_REJECTED",
            capped_qty_lots=capped_qty,
            risk_budget_used=assessment.risk_score,
            details={"risk_score": assessment.risk_score},
        )

    def _to_signal(self, intent: SignalIntent) -> TradingSignal:
        # Minimum viable synthetic signal for risk assessment in Phase 1.
        entry = intent.entry_ref
        rr = max(intent.rr_estimate, 1.0)
        risk_unit = entry * 0.001

        if intent.side == Direction.LONG:
            sl = entry - risk_unit
            tp = entry + (risk_unit * rr)
        else:
            sl = entry + risk_unit
            tp = entry - (risk_unit * rr)

        return TradingSignal(
            symbol=intent.symbol,
            direction=intent.side,
            entry_price=entry,
            stop_loss=sl,
            take_profit=tp,
            position_size=max(0.01, min(1.0, intent.confidence)),
            confidence=max(0.0, min(1.0, intent.confidence)),
            reasoning="legacy_risk_adapter_synthetic_signal",
            timestamp=datetime.now(timezone.utc),
            rr_ratio=rr,
        )


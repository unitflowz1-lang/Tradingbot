from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason_code: str
    capped_qty_lots: float
    risk_budget_used: float
    details: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class AdmissionDecision:
    approved: bool
    reason_code: str
    score: float
    metadata: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionDecision:
    accepted: bool
    reason_code: str
    ticket_id: Optional[str] = None
    latency_ms: Optional[float] = None
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


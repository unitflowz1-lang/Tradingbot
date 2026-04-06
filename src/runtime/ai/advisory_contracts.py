from dataclasses import dataclass
from typing import Literal


AdvisoryAction = Literal["APPROVE", "DEMOTE", "REJECT", "BYPASS"]


@dataclass(frozen=True)
class AdvisoryInput:
    symbol: str
    regime: str
    rsi: float
    adx: float
    atr: float
    rr_ratio: float
    ml_confidence: float
    volatility_pct: float
    forced_execution: bool
    position_size: float
    expectancy_multiplier: float


@dataclass(frozen=True)
class AdvisoryOutcome:
    action: AdvisoryAction
    confidence: int
    reason: str
    risk_flag: bool
    latency_ms: float
    bypassed: bool = False
    bypass_reason: str = ""


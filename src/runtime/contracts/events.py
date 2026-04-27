from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional


@dataclass(frozen=True)
class PipelineEvent:
    event_type: str
    at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: Optional[str] = None
    correlation_id: Optional[str] = None
    payload: Dict[str, str] = field(default_factory=dict)


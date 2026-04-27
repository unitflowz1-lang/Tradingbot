from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, Literal, Optional

from src.models import Direction, Order, OrderStatus, OrderType


PriorityClass = Literal["NORMAL", "HIGH", "CRITICAL"]


@dataclass(frozen=True)
class SignalIntent:
    symbol: str
    side: Direction
    entry_ref: float
    confidence: float
    rr_estimate: float
    priority: PriorityClass = "NORMAL"
    features: Dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPlan:
    symbol: str
    side: Direction
    qty_lots: float
    entry_type: OrderType
    sl: Optional[float]
    tp: Optional[float]
    client_order_id: str
    entry_price: Optional[float] = None
    time_in_force: str = "GTC"
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_order(self) -> Order:
        return Order(
            order_id=self.client_order_id,
            symbol=self.symbol,
            order_type=self.entry_type,
            direction=self.side,
            quantity=self.qty_lots,
            price=self.entry_price,
            stop_loss=self.sl,
            take_profit=self.tp,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc),
        )


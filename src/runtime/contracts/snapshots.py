from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from src.models import MarketData, Portfolio


@dataclass(frozen=True)
class SymbolSnapshot:
    symbol: str
    bars: List[MarketData]
    tick: Optional[MarketData] = None
    spread_pips: Optional[float] = None
    session: Optional[str] = None
    volatility_pct: Optional[float] = None


@dataclass(frozen=True)
class MarketSnapshot:
    asof: datetime
    symbols: Dict[str, SymbolSnapshot] = field(default_factory=dict)


@dataclass(frozen=True)
class PortfolioSnapshot:
    asof: datetime
    portfolio: Portfolio


from datetime import datetime, timezone
from typing import Dict, List

from src.models import MarketData, Portfolio
from src.runtime.contracts.snapshots import (
    MarketSnapshot,
    PortfolioSnapshot,
    SymbolSnapshot,
)


class LegacySnapshotAdapter:
    """
    Snapshot helper backed by existing broker methods.
    Phase 1: thin compatibility layer, no caching yet.
    """

    def __init__(self, broker, symbols: List[str], timeframe: int = 16385, bars: int = 150):
        self.broker = broker
        self.symbols = symbols
        self.timeframe = timeframe
        self.bars = bars

    async def build_market_snapshot(self) -> MarketSnapshot:
        symbol_data: Dict[str, SymbolSnapshot] = {}
        for symbol in self.symbols:
            bars: List[MarketData] = await self.broker.get_historical_data(
                symbol, timeframe=self.timeframe, count=self.bars
            )
            tick = await self.broker.get_market_data(symbol)
            symbol_data[symbol] = SymbolSnapshot(symbol=symbol, bars=bars or [], tick=tick)
        return MarketSnapshot(asof=datetime.now(timezone.utc), symbols=symbol_data)

    async def build_portfolio_snapshot(self) -> PortfolioSnapshot:
        portfolio: Portfolio = await self.broker.get_account_info()
        return PortfolioSnapshot(asof=datetime.now(timezone.utc), portfolio=portfolio)


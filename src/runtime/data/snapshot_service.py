import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from src.models import MarketData


@dataclass
class CycleSnapshot:
    asof: datetime
    bars: Dict[str, Dict[Any, List[MarketData]]] = field(default_factory=dict)
    ticks: Dict[str, MarketData] = field(default_factory=dict)


class RuntimeSnapshotService:
    """
    Shared cycle snapshot builder.
    Fetches all required bars/ticks once per cycle for reuse across the pipeline.
    """

    def __init__(self, broker):
        self.broker = broker
        self.logger = logging.getLogger(__name__)

    async def collect_cycle_snapshot(
        self,
        symbols: List[str],
        bar_requests: List[Tuple[Any, int]],
        include_ticks: bool = True,
    ) -> CycleSnapshot:
        snapshot = CycleSnapshot(asof=datetime.now(timezone.utc))
        unique_symbols = list(dict.fromkeys(symbols))

        bar_tasks = []
        for symbol in unique_symbols:
            for timeframe, count in bar_requests:
                bar_tasks.append(self._fetch_bars(symbol, timeframe, count))

        bar_results = await asyncio.gather(*bar_tasks, return_exceptions=True)
        for result in bar_results:
            if isinstance(result, Exception):
                self.logger.debug("[RUNTIME_SNAPSHOT] Bar fetch error: %s", result)
                continue
            symbol, timeframe, bars = result
            snapshot.bars.setdefault(symbol, {})[timeframe] = bars or []

        if include_ticks:
            tick_tasks = [self._fetch_tick(symbol) for symbol in unique_symbols]
            tick_results = await asyncio.gather(*tick_tasks, return_exceptions=True)
            for result in tick_results:
                if isinstance(result, Exception):
                    self.logger.debug("[RUNTIME_SNAPSHOT] Tick fetch error: %s", result)
                    continue
                symbol, tick = result
                if tick is not None:
                    snapshot.ticks[symbol] = tick

        return snapshot

    async def _fetch_bars(self, symbol: str, timeframe: Any, count: int):
        bars = await self.broker.get_historical_data(symbol, timeframe=timeframe, count=count)
        return symbol, timeframe, bars

    async def _fetch_tick(self, symbol: str):
        tick = await self.broker.get_market_data(symbol)
        return symbol, tick


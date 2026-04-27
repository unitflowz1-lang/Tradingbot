import asyncio
import logging
from typing import Awaitable, Callable

from src.runtime.contracts.snapshots import MarketSnapshot, PortfolioSnapshot
from src.runtime.orchestrator.pipeline import TradingPipeline


class RuntimeTradingLoop:
    """Thin loop wrapper for the new pipeline (not wired into production yet)."""

    def __init__(
        self,
        pipeline: TradingPipeline,
        market_provider: Callable[[], Awaitable[MarketSnapshot]],
        portfolio_provider: Callable[[], Awaitable[PortfolioSnapshot]],
        interval_seconds: float = 10.0,
    ):
        self.pipeline = pipeline
        self.market_provider = market_provider
        self.portfolio_provider = portfolio_provider
        self.interval_seconds = interval_seconds
        self.logger = logging.getLogger(__name__)

    async def run_forever(self) -> None:
        while True:
            market = await self.market_provider()
            portfolio = await self.portfolio_provider()
            await self.pipeline.run_once(market, portfolio)
            await asyncio.sleep(self.interval_seconds)


from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.models import Direction, MarketData
from src.strategies.advanced_mean_reversion import (
    AdvancedMeanReversionStrategy,
)
from src.strategies.factory import build_strategy


def _make_bar(symbol: str, ts: datetime, price: float, spread: float = 0.0002) -> MarketData:
    return MarketData(
        symbol=symbol,
        timestamp=ts,
        open=price - 0.0003,
        high=price + 0.0007,
        low=price - 0.0007,
        close=price,
        volume=1000,
        bid=price - spread / 2,
        ask=price + spread / 2,
        spread=spread,
    )


def _build_oscillating_series(symbol: str, *, final_price: float, periods: int = 120) -> list[MarketData]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars: list[MarketData] = []
    base = 1.1000
    for idx in range(periods - 1):
        wave = 0.0026 if idx % 2 == 0 else -0.0026
        drift = ((idx % 6) - 3) * 0.00008
        bars.append(_make_bar(symbol, start + timedelta(hours=idx), base + wave + drift))
    bars.append(_make_bar(symbol, start + timedelta(hours=periods - 1), final_price))
    return bars


def _build_trending_series(symbol: str, periods: int = 120) -> list[MarketData]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        _make_bar(symbol, start + timedelta(hours=idx), 1.0700 + idx * 0.0008)
        for idx in range(periods)
    ]


@pytest.mark.asyncio
async def test_mean_reversion_strategy_emits_short_on_overbought_dislocation():
    strategy = AdvancedMeanReversionStrategy(symbol="EUR/USD")
    bars = _build_oscillating_series("EUR/USD", final_price=1.1075)

    signal = await strategy.analyze(bars)

    assert signal is not None
    assert signal.direction == Direction.SHORT
    assert signal.exit_policy.value == "MEAN_REVERT"
    assert signal.source == "advanced_mean_reversion"
    assert signal.strategy_meta["ou_zscore"] > 0


@pytest.mark.asyncio
async def test_mean_reversion_strategy_emits_long_on_oversold_dislocation():
    strategy = AdvancedMeanReversionStrategy(symbol="EUR/USD")
    bars = _build_oscillating_series("EUR/USD", final_price=1.0925)

    signal = await strategy.analyze(bars)

    assert signal is not None
    assert signal.direction == Direction.LONG
    assert signal.strategy_meta["ou_zscore"] < 0


@pytest.mark.asyncio
async def test_mean_reversion_strategy_rejects_trending_market():
    strategy = AdvancedMeanReversionStrategy(symbol="EUR/USD")

    signal = await strategy.analyze(_build_trending_series("EUR/USD"))

    assert signal is None


def test_factory_builds_advanced_mean_reversion_strategy():
    class DummyConfigManager:
        def get_nested_config(self, key: str, default=None):
            if key == "trading_pairs.EURUSD":
                return {
                    "strategy": "AdvancedMeanReversion",
                    "strategy_params": {
                        "entry_zscore": 1.6,
                        "risk_per_trade": 0.02,
                    },
                }
            return default

    strategy = build_strategy(
        symbol="EUR/USD",
        config=None,
        admission_controller=None,
        config_manager=DummyConfigManager(),
    )

    assert isinstance(strategy, AdvancedMeanReversionStrategy)
    assert strategy.config.entry_zscore == 1.6
    assert strategy.config.risk_per_trade == 0.02

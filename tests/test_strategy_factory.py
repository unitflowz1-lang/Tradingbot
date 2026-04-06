from __future__ import annotations

import asyncio
import pathlib
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.models import Direction, MarketData
from src.strategies import factory
from src.strategies.high_reward_reversal_peaks import (
    HighRewardReversalPeaksStrategy,
    ReversalPeaksConfig,
)


class _FakeConfigManager:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_nested_config(self, path, default=None):
        keys = path.split(".")
        node = self.mapping
        try:
            for key in keys:
                node = node[key]
            return node
        except (KeyError, TypeError):
            return default


class _DummyStrategy:
    def __init__(self, symbol, config=None, admission_controller=None):
        self.symbol = symbol
        self.config = config
        self.admission_controller = admission_controller


def _build_history(symbol: str = "EUR/USD", bars: int = 90):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = []
    for i in range(bars):
        price = 100 + (i * 0.1)
        history.append(
            MarketData(
                symbol=symbol,
                timestamp=start + timedelta(minutes=15 * i),
                open=price,
                high=price + 0.5,
                low=price - 0.5,
                close=price + 0.1,
                volume=1000 + i,
                bid=price + 0.09,
                ask=price + 0.11,
                spread=0.02,
            )
        )
    return history


def test_build_strategy_uses_symbol_level_reversal_config():
    cfg = type("Cfg", (), {"trading": type("Trading", (), {"risk_per_trade": 0.01})()})()
    config_manager = _FakeConfigManager(
        {
            "trading_pairs": {
                "EUR/USD": {
                    "strategy": "ReversalPeaks",
                    "strategy_params": {
                        "risk_per_trade": 0.02,
                        "activation_r_multiple": 1.8,
                    },
                }
            }
        }
    )

    strategy = factory.build_strategy("EUR/USD", config=cfg, config_manager=config_manager)

    assert isinstance(strategy, HighRewardReversalPeaksStrategy)
    assert strategy.symbol == "EUR/USD"
    assert strategy.config.risk_per_trade == 0.02
    assert strategy.config.activation_r_multiple == 1.8


def test_build_strategy_defaults_to_simpletrend_registry_entry(monkeypatch):
    original = factory.STRATEGY_REGISTRY["simpletrend"]
    factory.STRATEGY_REGISTRY["simpletrend"] = _DummyStrategy
    try:
        cfg = type("Cfg", (), {"trading": type("Trading", (), {"risk_per_trade": 0.01})()})()
        strategy = factory.build_strategy(
            "EUR/USD",
            config=cfg,
            admission_controller="admit",
            config_manager=_FakeConfigManager({}),
        )
    finally:
        factory.STRATEGY_REGISTRY["simpletrend"] = original

    assert isinstance(strategy, _DummyStrategy)
    assert strategy.symbol == "EUR/USD"
    assert strategy.admission_controller == "admit"


def test_reversal_peaks_analyze_emits_live_signal(monkeypatch):
    history = _build_history()
    index = pd.to_datetime([bar.timestamp for bar in history], utc=True)
    feature_frame = pd.DataFrame(
        {
            "close": [bar.close for bar in history],
            "long_entry_signal": [False] * (len(history) - 1) + [True],
            "short_entry_signal": [False] * len(history),
            "long_stop": [bar.close - 1.2 for bar in history],
            "short_stop": [bar.close + 1.2 for bar in history],
            "signal_volume_ratio": [1.0] * (len(history) - 1) + [2.1],
            "signal_bullish_divergence_strength": [0.0] * (len(history) - 1) + [6.0],
            "signal_bearish_divergence_strength": [0.0] * len(history),
            "long_band_excess": [0.0] * (len(history) - 1) + [1.3],
            "short_band_excess": [0.0] * len(history),
        },
        index=index,
    )

    strategy = HighRewardReversalPeaksStrategy(
        symbol="EUR/USD",
        config=ReversalPeaksConfig(risk_per_trade=0.01, activation_r_multiple=1.5),
    )
    monkeypatch.setattr(strategy, "prepare_features", lambda _df: feature_frame)

    signal = asyncio.run(strategy.analyze(history))

    assert signal is not None
    assert signal.direction == Direction.LONG
    assert signal.symbol == "EUR/USD"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.position_size == 0.01
    assert signal.rr_ratio == 1.5
    assert signal.source == "reversal_peaks"

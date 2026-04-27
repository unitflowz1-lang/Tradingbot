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
from src.strategies.advanced_microstructure_strategy import (
    AdvancedMicrostructureStrategy,
    AdvancedMicrostructureConfig,
)
from src.strategies.advanced_volatility_strategy import (
    AdvancedVolatilityStrategy,
    AdvancedVolatilityConfig,
)
from src.strategies.advanced_intermarket_strategy import (
    AdvancedIntermarketStrategy,
    AdvancedIntermarketConfig,
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


def test_build_strategy_uses_symbol_level_microstructure_config():
    cfg = type("Cfg", (), {"trading": type("Trading", (), {"risk_per_trade": 0.01})()})()
    config_manager = _FakeConfigManager(
        {
            "trading_pairs": {
                "EURUSD": {
                    "strategy": "AdvancedMicrostructure",
                    "strategy_params": {
                        "imbalance_threshold": 0.22,
                        "risk_per_trade": 0.015,
                    },
                }
            }
        }
    )

    strategy = factory.build_strategy("EUR/USD", config=cfg, config_manager=config_manager)

    assert isinstance(strategy, AdvancedMicrostructureStrategy)
    assert strategy.config.imbalance_threshold == 0.22
    assert strategy.config.risk_per_trade == 0.015


def test_advanced_microstructure_analyze_emits_live_signal(monkeypatch):
    history = _build_history()
    index = pd.to_datetime([bar.timestamp for bar in history], utc=True)
    feature_frame = pd.DataFrame(
        {
            "close": [bar.close for bar in history],
            "atr": [0.18] * len(history),
            "spread": [0.02] * len(history),
            "order_flow_imbalance": [0.05] * (len(history) - 1) + [0.31],
            "tick_imbalance": [0.03] * (len(history) - 1) + [0.24],
            "vwap": [bar.close - 0.05 for bar in history],
            "vwap_deviation": [0.00005] * (len(history) - 1) + [0.00042],
            "spread_zscore": [0.2] * len(history),
            "spread_to_range": [0.08] * len(history),
            "institutional_footprint": [0.2] * (len(history) - 1) + [0.55],
            "poc": [bar.close - 0.02 for bar in history],
            "poc_distance": [0.0003] * len(history),
            "midpoint_skew": [0.1] * len(history),
        },
        index=index,
    )

    strategy = AdvancedMicrostructureStrategy(
        symbol="EUR/USD",
        config=AdvancedMicrostructureConfig(risk_per_trade=0.01),
    )
    monkeypatch.setattr(strategy, "_prepare_features", lambda _bars: feature_frame)

    signal = asyncio.run(strategy.analyze(history))

    assert signal is not None
    assert signal.direction == Direction.LONG
    assert signal.symbol == "EUR/USD"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.position_size == 0.01
    assert signal.source == "advanced_microstructure"


def test_advanced_microstructure_rejects_wide_spread(monkeypatch):
    history = _build_history()
    index = pd.to_datetime([bar.timestamp for bar in history], utc=True)
    feature_frame = pd.DataFrame(
        {
            "close": [bar.close for bar in history],
            "atr": [0.18] * len(history),
            "spread": [0.02] * len(history),
            "order_flow_imbalance": [0.31] * len(history),
            "tick_imbalance": [0.24] * len(history),
            "vwap": [bar.close - 0.05 for bar in history],
            "vwap_deviation": [0.00042] * len(history),
            "spread_zscore": [2.4] * len(history),
            "spread_to_range": [0.08] * len(history),
            "institutional_footprint": [0.55] * len(history),
            "poc": [bar.close - 0.02 for bar in history],
            "poc_distance": [0.0003] * len(history),
            "midpoint_skew": [0.1] * len(history),
        },
        index=index,
    )

    strategy = AdvancedMicrostructureStrategy(symbol="EUR/USD")
    monkeypatch.setattr(strategy, "_prepare_features", lambda _bars: feature_frame)

    signal = asyncio.run(strategy.analyze(history))

    assert signal is None


def test_build_strategy_uses_symbol_level_volatility_config():
    cfg = type("Cfg", (), {"trading": type("Trading", (), {"risk_per_trade": 0.01})()})()
    config_manager = _FakeConfigManager(
        {
            "trading_pairs": {
                "EURUSD": {
                    "strategy": "AdvancedVolatility",
                    "strategy_params": {
                        "forecast_premium_threshold": 1.2,
                        "risk_per_trade": 0.02,
                    },
                }
            }
        }
    )

    strategy = factory.build_strategy("EUR/USD", config=cfg, config_manager=config_manager)

    assert isinstance(strategy, AdvancedVolatilityStrategy)
    assert strategy.config.forecast_premium_threshold == 1.2
    assert strategy.config.risk_per_trade == 0.02


def test_build_strategy_passes_runtime_hooks_to_intermarket_strategy():
    cfg = type("Cfg", (), {"trading": type("Trading", (), {"risk_per_trade": 0.01})()})()
    loader = object()
    alpha_engine = object()
    config_manager = _FakeConfigManager(
        {
            "trading_pairs": {
                "EURUSD": {
                    "strategy": "AdvancedIntermarket",
                }
            }
        }
    )

    strategy = factory.build_strategy(
        "EUR/USD",
        config=cfg,
        config_manager=config_manager,
        runtime_hooks={
            "related_data_loader": loader,
            "alpha_portfolio_engine": alpha_engine,
        },
    )

    assert isinstance(strategy, AdvancedIntermarketStrategy)
    assert strategy.related_data_loader is loader
    assert getattr(strategy, "alpha_portfolio_engine") is alpha_engine


def test_advanced_volatility_analyze_emits_breakout_signal(monkeypatch):
    history = _build_history()
    index = pd.to_datetime([bar.timestamp for bar in history], utc=True)
    feature_frame = pd.DataFrame(
        {
            "close": [bar.close for bar in history],
            "atr": [0.18] * len(history),
            "spread": [0.02] * len(history),
            "spread_zscore": [0.25] * len(history),
            "spread_to_range": [0.08] * len(history),
            "realized_vol_short": [0.0010] * (len(history) - 1) + [0.0022],
            "realized_vol_long": [0.0011] * len(history),
            "forecast_vol": [0.0013] * (len(history) - 1) + [0.0028],
            "vol_premium_proxy": [1.02] * (len(history) - 1) + [1.35],
            "vol_zscore": [0.3] * (len(history) - 1) + [1.7],
            "vol_of_vol": [0.05] * (len(history) - 1) + [0.16],
            "cluster_score": [0.9] * (len(history) - 1) + [1.35],
            "upper_breakout": [bar.close - 0.10 for bar in history],
            "lower_breakout": [bar.close - 0.80 for bar in history],
            "rolling_mean": [bar.close - 0.20 for bar in history],
            "price_zscore": [0.5] * len(history),
            "momentum": [0.001] * (len(history) - 1) + [0.015],
        },
        index=index,
    )

    strategy = AdvancedVolatilityStrategy(
        symbol="EUR/USD",
        config=AdvancedVolatilityConfig(risk_per_trade=0.01),
    )
    monkeypatch.setattr(strategy, "_prepare_features", lambda _bars: feature_frame)

    signal = asyncio.run(strategy.analyze(history))

    assert signal is not None
    assert signal.direction == Direction.LONG
    assert signal.symbol == "EUR/USD"
    assert signal.stop_loss < signal.entry_price < signal.take_profit
    assert signal.position_size == 0.01
    assert signal.source == "advanced_volatility"
    assert signal.regime_label == "VOL_EXPANSION_BREAKOUT"


def test_advanced_volatility_rejects_wide_spread(monkeypatch):
    history = _build_history()
    index = pd.to_datetime([bar.timestamp for bar in history], utc=True)
    feature_frame = pd.DataFrame(
        {
            "close": [bar.close for bar in history],
            "atr": [0.18] * len(history),
            "spread": [0.02] * len(history),
            "spread_zscore": [2.1] * len(history),
            "spread_to_range": [0.08] * len(history),
            "realized_vol_short": [0.0022] * len(history),
            "realized_vol_long": [0.0011] * len(history),
            "forecast_vol": [0.0028] * len(history),
            "vol_premium_proxy": [1.35] * len(history),
            "vol_zscore": [1.7] * len(history),
            "vol_of_vol": [0.16] * len(history),
            "cluster_score": [1.35] * len(history),
            "upper_breakout": [bar.close - 0.10 for bar in history],
            "lower_breakout": [bar.close - 0.80 for bar in history],
            "rolling_mean": [bar.close - 0.20 for bar in history],
            "price_zscore": [0.5] * len(history),
            "momentum": [0.015] * len(history),
        },
        index=index,
    )

    strategy = AdvancedVolatilityStrategy(symbol="EUR/USD")
    monkeypatch.setattr(strategy, "_prepare_features", lambda _bars: feature_frame)

    signal = asyncio.run(strategy.analyze(history))

    assert signal is None


def _build_reference_history(symbol: str, closes: list[float]):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = []
    for i, price in enumerate(closes):
        history.append(
            MarketData(
                symbol=symbol,
                timestamp=start + timedelta(minutes=15 * i),
                open=price,
                high=price + 0.2,
                low=price - 0.2,
                close=price,
                volume=1000 + i,
                bid=price - 0.01,
                ask=price + 0.01,
                spread=0.02,
            )
        )
    return history


def test_build_strategy_uses_symbol_level_intermarket_config():
    cfg = type("Cfg", (), {"trading": type("Trading", (), {"risk_per_trade": 0.01})()})()
    config_manager = _FakeConfigManager(
        {
            "trading_pairs": {
                "EURUSD": {
                    "strategy": "AdvancedIntermarket",
                    "strategy_params": {
                        "residual_zscore_entry": 1.8,
                        "risk_per_trade": 0.02,
                    },
                }
            }
        }
    )

    strategy = factory.build_strategy("EUR/USD", config=cfg, config_manager=config_manager)

    assert isinstance(strategy, AdvancedIntermarketStrategy)
    assert strategy.config.residual_zscore_entry == 1.8
    assert strategy.config.risk_per_trade == 0.02


def test_advanced_intermarket_analyze_emits_signal(monkeypatch):
    main_closes = [100 + (i * 0.08) for i in range(89)] + [108.5]
    peer_closes = [100 + (i * 0.07) for i in range(90)]
    history = _build_reference_history("EUR/USD", main_closes)
    related = {"GBP/USD": _build_reference_history("GBP/USD", peer_closes)}

    async def loader(_symbol, _symbols, _count):
        return related

    strategy = AdvancedIntermarketStrategy(
        symbol="EUR/USD",
        config=AdvancedIntermarketConfig(
            risk_per_trade=0.01,
            reference_map={
                "EUR/USD": [
                    {"symbol": "GBP/USD", "expected_sign": 1, "role": "peer", "weight": 1.0}
                ]
            },
        ),
        related_data_loader=loader,
    )
    monkeypatch.setattr(
        strategy,
        "_score_reference",
        lambda _aligned, _spec: {
            "corr": 0.82,
            "aligned_corr": 0.82,
            "beta": 1.0,
            "residual_z": 2.1,
            "half_life": 8.0,
            "spread_vol": 0.01,
            "weight": 1.0,
        },
    )

    signal = asyncio.run(strategy.analyze(history))

    assert signal is not None
    assert signal.symbol == "EUR/USD"
    assert signal.source == "advanced_intermarket"
    assert signal.stop_loss < signal.entry_price or signal.stop_loss > signal.entry_price
    assert signal.take_profit > 0


def test_advanced_intermarket_returns_none_without_related_data():
    history = _build_history()

    async def loader(_symbol, _symbols, _count):
        return {}

    strategy = AdvancedIntermarketStrategy(
        symbol="EUR/USD",
        related_data_loader=loader,
    )

    signal = asyncio.run(strategy.analyze(history))

    assert signal is None

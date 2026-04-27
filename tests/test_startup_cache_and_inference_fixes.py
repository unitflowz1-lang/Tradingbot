import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd

from src.analysis.ml_model import PriceMovementPredictor
from src.data.news_data_collector import NewsDataCollector
from src.data.news_data_collector import NewsArticle
from src.ml.trade_admission_controller import TradeAdmissionController
from src.models import ExitPolicy, MarketData
from src.strategies.quant_hybrid_strategy import QuantHybridStrategy
from src.strategies.trend_strategy import SimpleTrendStrategy


def _news_config():
    return SimpleNamespace(
        api_timeout=30,
        news=SimpleNamespace(
            enabled=True,
            disabled=False,
            mock_mode=False,
            provider="newsapi",
            api_key="demo-key",
            require_live_data=False,
        ),
    )


def test_news_cache_only_mode_falls_back_to_first_available_entry():
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    NewsDataCollector._persistent_cache_loaded = True

    collector = NewsDataCollector(_news_config())
    article = NewsArticle(
        title="Fallback macro context",
        content="General forex context for EUR/USD and GBP/USD should survive cache-key mismatches.",
        source="TestWire",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/fallback",
        symbols=["EURUSD", "GBPUSD"],
    )

    collector.cache["AUDUSD|4h"] = [article]
    collector.last_fetch_time["AUDUSD|4h"] = datetime.now(timezone.utc)

    result = asyncio.run(
        collector.collect_data(["EUR/USD", "GBP/USD"], timeframe="4h", allow_live_fetch=False)
    )

    assert len(result["EUR/USD"]) == 1
    assert len(result["GBP/USD"]) == 1
    assert result["EUR/USD"][0].title == "Fallback macro context"


def test_price_movement_predictor_reuses_same_timestamp_inference():
    predictor = PriceMovementPredictor("AUD/USD")
    predictor.is_trained = True

    class _Scaler:
        def __init__(self):
            self.calls = 0

        def transform(self, df):
            self.calls += 1
            return np.array([[1.0, 2.0]])

    class _Model:
        def __init__(self):
            self.calls = 0

        def predict_proba(self, _x):
            self.calls += 1
            return np.array([[0.2, 0.8]])

    predictor.scaler = _Scaler()
    predictor.model = _Model()
    predictor.meta_model = None
    predictor.metadata = {"feature_names": []}
    predictor._prepare_latest_feature_row = lambda *_args, **_kwargs: pd.DataFrame([{"feature": 1.0}])

    bar = MarketData(
        symbol="AUD/USD",
        timestamp=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
        open=1.0,
        high=1.1,
        low=0.9,
        close=1.05,
        volume=100,
        bid=1.0499,
        ask=1.0501,
        spread=0.0002,
    )
    indicators = SimpleNamespace(
        rsi=45.0,
        macd_histogram=0.1,
        adx=20.0,
        atr=0.01,
    )

    first = predictor.predict_with_details([bar], indicators, bars_since_last_loss=10)
    second = predictor.predict_with_details([bar], indicators, bars_since_last_loss=10)

    assert first == second
    assert predictor.scaler.calls == 1
    assert predictor.model.calls == 1


def test_model_not_trained_fallback_is_neutral():
    predictor = PriceMovementPredictor("AUD/USD")
    predictor.is_trained = False
    predictor.model = None
    predictor.scaler = None

    bar = MarketData(
        symbol="AUD/USD",
        timestamp=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
        open=1.0,
        high=1.1,
        low=0.9,
        close=1.05,
        volume=100,
        bid=1.0499,
        ask=1.0501,
        spread=0.0002,
    )
    indicators = SimpleNamespace(rsi=35.0, macd_histogram=0.2)

    direction, confidence, details = predictor.predict_with_details([bar], indicators, bars_since_last_loss=10)

    assert direction in (0, 1)
    assert confidence == 0.5
    assert details["meta_win_prob"] == 0.5
    assert details["calibrated_confidence"] == 0.5
    assert details["fallback_reason"] == "model_not_trained"


def test_general_forex_uses_plain_cache_key():
    collector = NewsDataCollector(_news_config())
    assert collector._cache_key(NewsDataCollector.GENERAL_FOREX_CACHE_SYMBOL, "4h") == "general_forex"
    assert collector._cache_key("EUR/USD", "4h") == "EUR/USD|4h"


def test_macro_penalty_is_subtracted_from_ev_not_win_probability(monkeypatch):
    monkeypatch.setattr(
        "src.ml.trade_admission_controller.get_macro_risk_penalty",
        lambda symbol: 0.08,
    )
    monkeypatch.setattr(
        "src.ml.trade_admission_controller.macro_risk_cache.snapshot",
        lambda: {"source": "news_calendar"},
    )

    controller = TradeAdmissionController(data_dir=".")
    decision = controller.evaluate_admission(
        symbol="AUD/USD",
        regime="TRENDING",
        expectancy=1.0,
        confidence=1.0,
        exit_policy=ExitPolicy.STANDARD,
        position_size_multiplier=1.0,
        real_risk_reward_ratio=3.0,
    )

    assert decision.admitted is True
    record = controller.opportunity_windows["TRENDING"][-1]
    assert record.adjusted_win_prob == 1.0
    assert record.ev == 2.92


def _market_series(symbol: str = "AUD/USD", count: int = 80):
    bars = []
    base = 1.0
    for idx in range(count):
        close = base + (idx * 0.0015) + (0.001 if idx % 5 == 0 else -0.0004)
        bars.append(
            MarketData(
                symbol=symbol,
                timestamp=datetime(2026, 4, 22, 12, 0, tzinfo=timezone.utc),
                open=close - 0.0008,
                high=close + 0.0012,
                low=close - 0.0011,
                close=close,
                volume=100 + idx,
                bid=close - 0.0001,
                ask=close + 0.0001,
                spread=0.0002,
            )
        )
    return bars


def test_trend_symbol_report_primes_atr_and_macd_fields():
    strategy = SimpleTrendStrategy.__new__(SimpleTrendStrategy)
    strategy.symbol = "AUD/USD"
    strategy.logger = SimpleNamespace(debug=lambda *_args, **_kwargs: None)
    strategy._last_metrics_cycle_id = None
    strategy._last_symbol_report = {}
    strategy._current_cycle_id = None
    strategy._bot_cycle_count = None
    strategy.ml_predictor = SimpleNamespace(
        predict_with_details=lambda *_args, **_kwargs: ("UP", 0.61, {}),
    )

    report = strategy.update_metrics_snapshot(_market_series(), reason="test_prime")

    assert report["rsi"] > 0.0
    assert "atr" in report and report["atr"] > 0.0
    assert "macd" in report
    assert "macd_signal" in report
    assert "macd_histogram" in report


def test_quant_live_indicator_snapshot_rebuilds_nonzero_rsi_and_macd():
    strategy = QuantHybridStrategy.__new__(QuantHybridStrategy)
    strategy.symbol = "AUD/USD"
    strategy.logger = SimpleNamespace(debug=lambda *_args, **_kwargs: None)
    strategy._last_symbol_report = {"rsi": 0.0, "macd_histogram": 0.0, "volatility": 0.0}

    snapshot = strategy._build_live_indicator_snapshot(_market_series())

    assert snapshot["rsi"] > 0.0
    assert snapshot["atr"] > 0.0
    assert snapshot["macd_histogram"] != 0.0

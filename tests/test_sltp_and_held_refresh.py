import sys
from datetime import datetime, timedelta, timezone
import logging

import pytest

from src.models import MarketData
from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator
from src.runtime.orchestrator.pipeline import LegacySymbolBatchOrchestrator
from src.strategies.trend_strategy import SimpleTrendStrategy


def _bars(symbol: str = "GBP/USD", count: int = 60):
    start = datetime.now(timezone.utc) - timedelta(hours=count)
    rows = []
    price = 1.2500
    for idx in range(count):
        close = price + (idx * 0.0003)
        rows.append(
            MarketData(
                symbol=symbol,
                timestamp=start + timedelta(hours=idx),
                open=close - 0.0002,
                high=close + 0.0005,
                low=close - 0.0005,
                close=close,
                volume=1000 + idx,
                bid=close - 0.0001,
                ask=close + 0.0001,
                spread=0.0002,
            )
        )
    return rows


def test_resolve_atr_value_uses_indicator_buffers_before_fallback_recalc():
    calculator = StopLossTakeProfitCalculator()

    atr_from_buffer = calculator.resolve_atr_value(
        market_snapshot={"indicators": {"atr": 0.0017}},
        strategy_meta={"symbol_report": {"atr": 0.0009}},
        historical_data=_bars(),
    )

    assert atr_from_buffer == pytest.approx(0.0017)


@pytest.mark.asyncio
async def test_refresh_held_position_state_returns_live_indicator_payload():
    strategy = SimpleTrendStrategy.__new__(SimpleTrendStrategy)
    strategy.symbol = "GBP/USD"
    strategy.logger = logging.getLogger("test.held_refresh")
    strategy._last_symbol_report = {}
    strategy._last_metrics_cycle_id = None
    strategy._current_cycle_id = None
    strategy._bot_cycle_count = None

    class _Predictor:
        def predict_with_details(self, historical_data, indicators, bars_since_last_loss):
            return "UP", 0.61, {}

    strategy.ml_predictor = _Predictor()

    payload = await strategy.refresh_held_position_state(_bars())

    assert float(payload["symbol_report"]["rsi"]) > 0.0
    assert float(payload["technical_indicators"]["atr"]) > 0.0
    assert payload["symbol_report"]["direction"] == "UP"


def test_dxy_check_marks_system_health_ok_when_dx_is_found(monkeypatch):
    orchestrator = LegacySymbolBatchOrchestrator()

    class StubInfo:
        visible = True

    class StubMt5:
        @staticmethod
        def symbol_info(symbol):
            return StubInfo() if symbol == "DX" else None

    monkeypatch.setitem(sys.modules, "MetaTrader5", StubMt5)

    orchestrator.check_and_suppress_macro(["EUR/USD", "DX"])

    assert orchestrator.dxy_symbol == "DX"
    assert orchestrator.system_health["dxy"] == "OK"

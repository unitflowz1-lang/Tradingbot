from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Direction
from src.data.news_data_collector import NewsDataCollector
from src.monitoring.weekly_distribution_report import WeeklyDistributionReportGenerator
from src.trading.execution_engine import ExecutionEngine
from src.trading.exit_reason import ExitLogger
from src.trading.position_manager import PositionManager


def _workspace_tmp(name: str) -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp" / name
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.mark.asyncio
async def test_news_collector_returns_immediately_when_disabled():
    config = SimpleNamespace(
        api_timeout=30,
        news=SimpleNamespace(enabled=False, disabled=False, mock_mode=False),
    )
    collector = NewsDataCollector(config)

    result = await collector.collect_data(["EUR/USD"], timeframe="1h")

    assert result == {"EUR/USD": []}


@pytest.mark.asyncio
async def test_news_fetch_retry_short_circuits_in_mock_mode():
    config = SimpleNamespace(
        api_timeout=30,
        news=SimpleNamespace(enabled=True, disabled=False, mock_mode=True),
    )
    collector = NewsDataCollector(config)

    result = await collector._fetch_news_data_with_retry("EUR/USD", "1h")

    assert result == []


def test_execution_engine_slippage_direction_is_trade_aware():
    assert ExecutionEngine._is_favorable_execution_price(Direction.LONG, 1.2500, 1.2495) is True
    assert ExecutionEngine._is_favorable_execution_price(Direction.LONG, 1.2500, 1.2505) is False
    assert ExecutionEngine._is_favorable_execution_price(Direction.SHORT, 1.2500, 1.2505) is True
    assert ExecutionEngine._is_favorable_execution_price(Direction.SHORT, 1.2500, 1.2495) is False


def test_exit_logger_loads_shared_records_once(monkeypatch):
    tmp_path = _workspace_tmp("exit_logger")
    monkeypatch.chdir(tmp_path)
    payload = [
        {
            "position_id": "1",
            "symbol": "EUR/USD",
            "entry_time": datetime(2026, 3, 27, tzinfo=timezone.utc).isoformat(),
            "exit_time": datetime(2026, 3, 27, 1, tzinfo=timezone.utc).isoformat(),
            "entry_price": 1.1,
            "exit_price": 1.11,
            "direction": "LONG",
            "quantity": 0.1,
            "reason": "tp_hit",
            "profit_loss": 10.0,
            "profit_loss_pips": 10.0,
            "hold_time_seconds": 60,
        }
    ]
    (tmp_path / "exit_history.json").write_text(json.dumps(payload), encoding="utf-8")

    # Reset the singleton for testing
    ExitLogger._instance = None
    ExitLogger._initialized = False
    ExitLogger._exit_records = []
    ExitLogger._records_loaded = False
    ExitLogger._load_log_emitted = False
    ExitLogger._ensemble = None
    ExitLogger._logger = None

    logger_a = ExitLogger()
    logger_b = ExitLogger()

    # Both should be the exact same instance (Singleton pattern)
    assert logger_a is logger_b
    assert logger_a.exit_records is logger_b.exit_records
    assert len(logger_a.exit_records) == 1
    assert len(logger_b.exit_records) == 1


def test_weekly_distribution_report_generator_is_singleton():
    tmp_path = _workspace_tmp("weekly_distribution")
    WeeklyDistributionReportGenerator._shared_instance = None

    report_a = WeeklyDistributionReportGenerator(output_dir=str(tmp_path / "weekly_a"))
    report_b = WeeklyDistributionReportGenerator(output_dir=str(tmp_path / "weekly_b"))

    assert report_a is report_b


class _BrokerStub:
    def __init__(self, positions):
        self.positions = positions
        self.calls = 0

    async def get_positions(self):
        self.calls += 1
        return list(self.positions)


@pytest.mark.asyncio
async def test_sync_mt5_state_debounces_duplicate_boot_calls(monkeypatch):
    tmp_path = _workspace_tmp("position_manager")
    monkeypatch.chdir(tmp_path)
    broker = _BrokerStub(
        [
            SimpleNamespace(
                position_id="123",
                symbol="EUR/USD",
                direction="LONG",
                entry_price=1.1,
                current_price=1.101,
                quantity=0.1,
                volume=0.1,
                contract_size=100000.0,
                stop_loss=1.09,
                take_profit=1.12,
            )
        ]
    )
    manager = PositionManager(broker=broker, execution_engine=None)

    await manager.sync_mt5_state(persist=False)
    await manager.sync_mt5_state(persist=False)

    assert broker.calls == 1

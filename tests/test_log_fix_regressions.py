from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Direction
from src.data.news_data_collector import NewsArticle, NewsDataCollector
from src.monitoring.weekly_distribution_report import WeeklyDistributionReportGenerator
from src.runtime.orchestrator.pipeline import LegacySymbolBatchOrchestrator
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


@pytest.mark.asyncio
async def test_newsapi_uses_shared_general_forex_cache_for_all_symbols(monkeypatch):
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    config = SimpleNamespace(
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
    collector = NewsDataCollector(config)
    calls = []

    article = NewsArticle(
        title="Central bank outlook steadies forex markets",
        content="Forex traders are watching central bank guidance and broad currency moves.",
        source="TestWire",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/shared-news",
        symbols=[],
    )

    async def fake_fetch(symbol, timeframe):
        calls.append((symbol, timeframe))
        return [article]

    monkeypatch.setattr(collector, "_fetch_news_data", fake_fetch)

    result = await collector.collect_data(["EUR/USD", "GBP/USD"], timeframe="4h", force_refresh=True, allow_live_fetch=True)

    assert calls == [(NewsDataCollector.GENERAL_FOREX_CACHE_SYMBOL, "4h")]
    assert len(result["EUR/USD"]) == 1
    assert len(result["GBP/USD"]) == 1
    assert NewsDataCollector.get_latest_fetch_time("EUR/USD", "4h") is not None


@pytest.mark.asyncio
async def test_strategy_side_news_reads_cached_general_forex_without_live_fetch(monkeypatch):
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    config = SimpleNamespace(
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
    collector = NewsDataCollector(config)
    article = NewsArticle(
        title="Forex update",
        content="Forex traders focus on EUR/USD and GBP/USD moves.",
        source="TestWire",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/cached-news",
        symbols=["EURUSD", "GBPUSD"],
    )
    cache_key = f"{NewsDataCollector.GENERAL_FOREX_CACHE_SYMBOL}|4h"
    NewsDataCollector._shared_news_cache[cache_key] = [article]
    NewsDataCollector._shared_news_timestamp_cache[cache_key] = datetime.now(timezone.utc)

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("live fetch should not be used from strategy-side cache-only calls")

    monkeypatch.setattr(collector, "_fetch_news_data", fail_fetch)

    result = await collector.collect_data(["EUR/USD"], timeframe="4h", allow_live_fetch=False)

    assert len(result["EUR/USD"]) == 1


@pytest.mark.asyncio
async def test_news_fetch_failure_returns_stale_persisted_cache(monkeypatch):
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    config = SimpleNamespace(
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
    collector = NewsDataCollector(config)
    stale_article = NewsArticle(
        title="Stale but usable",
        content="Old cached forex context is better than an empty feed.",
        source="TestWire",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/stale-cache",
        symbols=["EUR/USD"],
    )
    cache_key = f"{NewsDataCollector.GENERAL_FOREX_CACHE_SYMBOL}|4h"
    collector.cache[cache_key] = [stale_article]
    collector.last_fetch_time[cache_key] = datetime.now(timezone.utc)

    async def fail_fetch(*_args, **_kwargs):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(collector, "_fetch_news_data", fail_fetch)

    result = await collector.collect_data(["EUR/USD"], timeframe="4h", force_refresh=True, allow_live_fetch=True)

    assert len(result["EUR/USD"]) == 1
    assert result["EUR/USD"][0].title == "Stale but usable"


def test_weighted_median_prefers_heavier_component():
    orchestrator = LegacySymbolBatchOrchestrator()
    value = orchestrator._weighted_median([0.9, 1.0, 1.2], [0.1, 0.7, 0.2])
    assert value == pytest.approx(1.0)


def test_news_cache_persists_to_disk_and_reloads():
    tmp_path = _workspace_tmp("news_cache_persist")
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    NewsDataCollector._persistent_cache_loaded = False
    NewsDataCollector.CACHE_FILE_PATH = tmp_path / "news_cache.json"

    config = SimpleNamespace(
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
    collector = NewsDataCollector(config)
    article = NewsArticle(
        title="Persistent forex cache",
        content="Forex cache persistence should survive restarts.",
        source="TestWire",
        published_at=datetime.now(timezone.utc),
        url="https://example.com/persisted",
        symbols=["EUR/USD"],
    )
    collector._store_fetch_result(NewsDataCollector.GENERAL_FOREX_CACHE_SYMBOL, "4h", [article])

    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    NewsDataCollector._persistent_cache_loaded = False
    reloaded = NewsDataCollector(config)

    cache_key = NewsDataCollector.GENERAL_FOREX_CACHE_SYMBOL
    assert cache_key in reloaded.cache
    assert reloaded.cache[cache_key][0].title == "Persistent forex cache"


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

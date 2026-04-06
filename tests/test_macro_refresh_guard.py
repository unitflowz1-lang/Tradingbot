import asyncio
import os
import sys
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
import uuid

import pytest

sys.path.insert(0, os.getcwd())

from src.analysis.llm_macro_monitor import AsyncLLMMacroMonitor, MacroHealthMonitor
from src.data.news_data_collector import NewsArticle, NewsDataCollector
from src.learning.user_intervention_learner import UserInterventionLearner
from src.ml.trade_admission_controller import TradeAdmissionController
from src.monitoring.decision_matrix import Action, DecisionMatrix, MetricsSnapshot
from src.runtime.risk.policy_engine import AdaptiveRiskGuard
from src.trading.profit_protection_module import TradeManagementSettings
from src.trading.position_manager import PositionManager
from src.trading.profit_protection_module import ProfitProtectionModule
from src.models import Direction
from src.config import (
    BrokerConfig,
    CerebrasConfig,
    Config,
    DatabaseConfig,
    LLMConfig,
    NewsConfig,
    NotificationConfig,
    RiskConfig,
    TradingConfig,
)


def _build_config() -> Config:
    return Config(
        trading=TradingConfig(
            supported_pairs=["EUR/USD"],
            max_daily_trades=5,
            risk_per_trade=0.01,
            max_drawdown=0.1,
            trading_hours={},
        ),
        llm=LLMConfig(
            provider="mock",
            model="mock",
            api_key="",
            max_tokens=128,
            temperature=0,
            timeout=5,
        ),
        risk=RiskConfig(
            max_position_size=1.0,
            stop_loss_pct=0.01,
            take_profit_pct=0.02,
            max_correlation=0.7,
            drawdown_limit=0.1,
        ),
        broker=BrokerConfig(
            broker_name="mock",
            api_key="",
            api_secret="",
            base_url="http://localhost",
            timeout=5,
        ),
        database=DatabaseConfig(
            host="localhost",
            port=5432,
            database="test",
            username="test",
            password="test",
        ),
        cerebras=CerebrasConfig(
            api_key="",
            model="mock",
        ),
        notification=NotificationConfig(),
        news=NewsConfig(),
    )


@pytest.mark.asyncio
async def test_news_fetch_retries_and_updates_timestamp(monkeypatch):
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    collector = NewsDataCollector(_build_config())
    collector.fetch_retry_backoff_seconds = 30

    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    article = NewsArticle(
        title="EUR/USD update",
        content="Fed and ECB remain in focus for EUR/USD traders.",
        source="TestWire",
        published_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        url="https://example.com/story",
        symbols=["EUR/USD"],
    )
    attempts = {"count": 0}

    async def fake_fetch(symbol, timeframe):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary fetch failure")
        return [article]

    monkeypatch.setattr("src.data.news_data_collector.asyncio.sleep", fake_sleep)
    monkeypatch.setattr(collector, "_fetch_news_data", fake_fetch)

    result = await collector.collect_data(["EUR/USD"], timeframe="4h", force_refresh=True)

    assert attempts["count"] == 3
    assert delays == [30, 30]
    assert result["EUR/USD"]
    assert NewsDataCollector.get_latest_fetch_time("EUR/USD", "4h") is not None


def test_trade_admission_clears_stale_hold_when_news_fetch_is_fresh(monkeypatch):
    NewsDataCollector._shared_news_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache.clear()
    cache_key = "EUR/USD|4h"
    NewsDataCollector._shared_news_timestamp_cache[cache_key] = datetime.now(timezone.utc)

    stale_snapshot = {
        "updated_at": (datetime.now(timezone.utc) - timedelta(minutes=290)).isoformat(),
        "source": "news_calendar",
    }

    monkeypatch.setenv("MACRO_NEWS_MAX_STALENESS_MINUTES", "15")
    monkeypatch.setattr(
        "src.ml.trade_admission_controller.macro_risk_cache.get_macro_risk_reason",
        lambda symbol: "HIGH_IMPACT_NEWS_PENDING",
    )
    monkeypatch.setattr(
        "src.ml.trade_admission_controller.macro_risk_cache.get_macro_risk_penalty",
        lambda symbol: 0.25,
    )
    monkeypatch.setattr(
        "src.ml.trade_admission_controller.macro_risk_cache.snapshot",
        lambda: stale_snapshot,
    )

    controller = TradeAdmissionController(data_dir=".")
    macro_state = controller._get_macro_news_state("EUR/USD")

    assert macro_state["snapshot_age_minutes"] is not None
    assert macro_state["snapshot_age_minutes"] < 15
    assert macro_state["stale_news"] is False
    assert macro_state["news_pending"] is True


@pytest.mark.asyncio
async def test_macro_monitor_forces_refresh_when_age_exceeds_limit():
    class StubCollector:
        def __init__(self):
            self.calls = []

        async def collect_data(self, symbols, timeframe="4h", force_refresh=False):
            self.calls.append(
                {
                    "symbols": list(symbols),
                    "timeframe": timeframe,
                    "force_refresh": force_refresh,
                }
            )
            now = datetime.now(timezone.utc)
            for symbol in symbols:
                NewsDataCollector._shared_news_timestamp_cache[f"{symbol}|{timeframe}"] = now
            return {symbol: [] for symbol in symbols}

    NewsDataCollector._shared_news_timestamp_cache.clear()
    NewsDataCollector._shared_news_timestamp_cache["EUR/USD|4h"] = datetime.now(timezone.utc) - timedelta(minutes=16)

    stub_collector = StubCollector()
    monitor = AsyncLLMMacroMonitor(
        symbols=["EUR/USD"],
        interval_seconds=300,
        news_collector=stub_collector,
    )
    monitor._next_macro_eval_at = datetime.now(timezone.utc) + timedelta(minutes=10)

    await monitor._maybe_force_refresh_stale_macro_data()

    assert len(stub_collector.calls) == 1
    assert stub_collector.calls[0]["force_refresh"] is True
    assert stub_collector.calls[0]["timeframe"] == "4h"
    assert monitor._next_macro_eval_at <= datetime.now(timezone.utc)


def test_momentum_stall_defaults_are_relaxed():
    settings = TradeManagementSettings()
    assert settings.momentum_stall_candles == 20
    assert settings.momentum_stall_range_pips == 30.0


def test_check_momentum_stall_uses_configured_candle_count_and_min_open_time():
    module = ProfitProtectionModule.__new__(ProfitProtectionModule)
    module.settings = TradeManagementSettings(momentum_stall_candles=20, momentum_stall_range_pips=30.0)
    position = type(
        "Position",
        (),
        {
            "direction": Direction.LONG,
            "opened_at": datetime.now(timezone.utc) - timedelta(minutes=10),
        },
    )()
    state = {"price_history": [1.1000] * 25}

    stalled, price_range = module._check_momentum_stall(position, state, pip_value=0.0001, current_r=1.0)

    assert stalled is False
    assert price_range == 0.0

    position.opened_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    state["price_history"] = [1.1000] * 19
    stalled, _ = module._check_momentum_stall(position, state, pip_value=0.0001, current_r=1.0)
    assert stalled is False


def test_check_momentum_stall_requires_three_adverse_candles_when_in_profit():
    module = ProfitProtectionModule.__new__(ProfitProtectionModule)
    module.settings = TradeManagementSettings(momentum_stall_candles=20, momentum_stall_range_pips=30.0)
    module._count_recent_adverse_candles = ProfitProtectionModule._count_recent_adverse_candles.__get__(module, ProfitProtectionModule)
    position = type(
        "Position",
        (),
        {
            "direction": Direction.LONG,
            "opened_at": datetime.now(timezone.utc) - timedelta(minutes=20),
        },
    )()
    state = {"price_history": [1.1000] * 17 + [1.1002, 1.1001, 1.1003]}

    stalled, _ = module._check_momentum_stall(position, state, pip_value=0.0001, current_r=1.0)
    assert stalled is False

    state["price_history"] = [1.1000] * 16 + [1.1004, 1.1003, 1.1002, 1.1001]
    stalled, _ = module._check_momentum_stall(position, state, pip_value=0.0001, current_r=1.0)
    assert stalled is True


def test_amnesia_guard_only_triggers_after_ten_consecutive_losses():
    history_path = Path(os.getcwd()) / f"trade_history_test_{uuid.uuid4().hex}.csv"
    with history_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["timestamp", "pnl"])
        writer.writeheader()
        writer.writerow({"timestamp": "2026-01-01T00:00:00+00:00", "pnl": "5"})
        for idx in range(9):
            writer.writerow({"timestamp": f"2026-01-01T00:0{idx+1}:00+00:00", "pnl": "-1"})

    try:
        learner = UserInterventionLearner.__new__(UserInterventionLearner)
        assert learner._calculate_consecutive_losses(str(history_path)) == 9

        with history_path.open("a", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["timestamp", "pnl"])
            writer.writerow({"timestamp": "2026-01-01T00:10:00+00:00", "pnl": "-1"})

        assert learner._calculate_consecutive_losses(str(history_path)) == 10
    finally:
        history_path.unlink(missing_ok=True)


def test_macro_health_monitor_switches_to_technical_only_when_restart_fails():
    class StubMonitor:
        def __init__(self):
            self.news_collector = object()
            self.raw_symbols = ["EUR/USD"]
            self.technical_only_mode_active = False
            self.activated_reason = None

        def _get_macro_data_age_minutes(self):
            return 20.0

        def _activate_technical_only_mode(self, reason):
            self.technical_only_mode_active = True
            self.activated_reason = reason

    stub_monitor = StubMonitor()
    loop = asyncio.new_event_loop()
    try:
        health_monitor = MacroHealthMonitor(stub_monitor, loop, check_interval_seconds=60, stale_limit_minutes=15)
        health_monitor._attempt_news_fetch_restart = lambda: False
        calls = {"count": 0}

        def fake_wait(_timeout):
            calls["count"] += 1
            return calls["count"] > 1

        health_monitor._stop_event.wait = fake_wait
        health_monitor.run()
        assert stub_monitor.technical_only_mode_active is True
        assert stub_monitor.activated_reason == "MACRO_HEALTHMONITOR_NEWS_FETCH_RESTART_FAILED"
    finally:
        loop.close()


def test_user_intervention_learner_can_clear_cooldowns_for_symbols():
    learner = UserInterventionLearner.__new__(UserInterventionLearner)
    learner._smarter_exit_cooldown = {
        ("AUDUSD", "LONG"): datetime.now(timezone.utc) + timedelta(minutes=5),
        ("EURUSD", "SHORT"): datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    learner._save_cooldowns = lambda: None

    removed = learner.clear_cooldowns_for_symbols(["AUD/USD"])

    assert removed == 1
    assert ("AUDUSD", "LONG") not in learner._smarter_exit_cooldown
    assert ("EURUSD", "SHORT") in learner._smarter_exit_cooldown


def test_user_intervention_learner_records_manual_intervention_once_per_ticket_reason():
    learner = UserInterventionLearner.__new__(UserInterventionLearner)
    learner._history = []
    learner._save_history = lambda: None

    first = learner.record_intervention(
        ticket_id="12345",
        symbol="EUR/USD",
        direction="LONG",
        reason="MANUAL_CLOSE",
        metadata={"source": "deal_history"},
    )
    second = learner.record_intervention(
        ticket_id="12345",
        symbol="EUR/USD",
        direction="LONG",
        reason="MANUAL_CLOSE",
        metadata={"source": "duplicate_attempt"},
    )

    assert first is not None
    assert second == first
    assert len(learner._history) == 1
    assert learner._history[0]["symbol"] == "EURUSD"
    assert learner._history[0]["direction"] == "LONG"


def test_decision_matrix_softens_defensive_governance_for_technical_only_forced_execution():
    matrix = DecisionMatrix()
    metrics = MetricsSnapshot(
        macro_risk=0.10,
        macro_risk_reason="High_Impact_News_Pending",
    )
    metrics.technical_only_mode = True
    metrics.forced_execution = True

    action, severity = matrix.get_governance_state(metrics)

    assert action == Action.DEFENSIVE_PRESERVATION
    assert severity == 30.0


def test_adaptive_risk_guard_respects_technical_only_forced_relief():
    latest_decision = type(
        "Decision",
        (),
        {
            "primary_action": Action.DEFENSIVE_PRESERVATION,
            "severity_score": 30.0,
            "technical_only_forced_relief": True,
        },
    )()
    signal = type("Signal", (), {"confidence": 0.9, "trade_tier": "", "predictive_attribution": {}})()
    guard = AdaptiveRiskGuard()

    result = guard.evaluate_signal(
        signal=signal,
        total_open_risk_pct=1.0,
        proposed_trade_risk_pct=0.5,
        latest_decision=latest_decision,
    )

    assert result.allow_trade is True
    assert result.size_multiplier == 1.0


def test_position_manager_resets_corrupt_shadow_state_file():
    shadow_path = Path(os.getcwd()) / f"shadow_state_test_{uuid.uuid4().hex}.json"
    shadow_path.write_text("", encoding="utf-8")
    manager = PositionManager.__new__(PositionManager)
    manager._shadow_state_loaded_once = False
    manager.SHADOW_STATE_FILE = str(shadow_path)
    manager.shadow_positions = {"stale": {}}
    manager.logger = type("Logger", (), {"debug": lambda *a, **k: None, "critical": lambda *a, **k: None, "error": lambda *a, **k: None, "warning": lambda *a, **k: None})()
    manager._deserialize_shadow_types = lambda raw: raw
    manager._purge_obsolete_shadow_positions = lambda: None

    try:
        manager._load_shadow_state()
        assert manager.shadow_positions == {}
        assert shadow_path.read_text(encoding="utf-8") == "{}"
    finally:
        shadow_path.unlink(missing_ok=True)

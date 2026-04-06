import asyncio
import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.trading import state_sync_manager as sync_module
from src.trading.state_sync_manager import StateSyncManager


class DummyPositionManager:
    def __init__(self):
        self.open_positions = {"1": {"symbol": "EURUSD"}}
        self.active_ticket_registry = {"1"}
        self.managed_tickets = {"1": {"ticket": "1"}}
        self.saved = False

    def _save_shadow_state(self):
        self.saved = True


def test_mt5_call_with_backoff_retries_until_success(monkeypatch):
    attempts = {"count": 0}

    def flaky_call():
        attempts["count"] += 1
        if attempts["count"] < 3:
            return None
        return ["ok"]

    monkeypatch.setattr(sync_module.mt5, "positions_get", flaky_call)
    mgr = StateSyncManager(broker=None, shadow_tracker_dict={})

    result = asyncio.run(mgr._call_mt5_with_backoff("positions_get"))

    assert result == ["ok"]
    assert attempts["count"] == 3


def test_fetch_mt5_positions_uses_live_terminal_profit(monkeypatch):
    monkeypatch.setattr(sync_module.mt5, "ORDER_TYPE_BUY", 0, raising=False)

    def fake_positions_get():
        return [
            SimpleNamespace(
                ticket=12345,
                symbol="EURUSD",
                price_open=1.1000,
                price_current=1.0950,
                profit=87.65,
                time=1_700_000_000,
                volume=1.0,
                type=0,
            )
        ]

    monkeypatch.setattr(sync_module.mt5, "positions_get", fake_positions_get)
    mgr = StateSyncManager(broker=None, shadow_tracker_dict={})

    snapshots = asyncio.run(mgr._fetch_mt5_positions())

    assert len(snapshots) == 1
    assert snapshots[0].profit_loss == 87.65


def test_cleanup_and_reset_state_clears_local_mirrors():
    shadow = {"1": {"symbol": "EURUSD"}}
    pm = DummyPositionManager()
    mgr = StateSyncManager(broker=None, shadow_tracker_dict=shadow, position_manager=pm)
    mgr.last_mt5_snapshot = {"1": object()}
    mgr.pending_cleanup = {"1": {"remaining_cycles": 1}}
    mgr.pending_adoption = {"2": {"cycles_seen": 1}}

    mgr.cleanup_and_reset_state("unit_test")

    assert shadow == {}
    assert mgr.last_mt5_snapshot == {}
    assert mgr.pending_cleanup == {}
    assert mgr.pending_adoption == {}
    assert pm.open_positions == {}
    assert pm.active_ticket_registry == set()
    assert pm.managed_tickets == {}
    assert pm.saved is True


def test_heartbeat_reconcile_uses_terminal_truth_and_resets_on_drift(monkeypatch):
    monkeypatch.setattr(sync_module.mt5, "ORDER_TYPE_BUY", 0, raising=False)
    monkeypatch.setattr(sync_module.mt5, "account_info", lambda: SimpleNamespace(balance=10000.0))
    monkeypatch.setattr(
        sync_module.mt5,
        "positions_get",
        lambda: [
            SimpleNamespace(
                ticket=777,
                symbol="EURUSD",
                price_open=1.1000,
                price_current=1.1010,
                profit=25.0,
                time=1_700_000_000,
                volume=1.0,
                type=0,
            )
        ],
    )

    shadow = {"777": {"symbol": "EURUSD", "profit": 3.0}}
    mgr = StateSyncManager(
        broker=None,
        shadow_tracker_dict=shadow,
        config={"heartbeat_drift_threshold": 5.0, "enable_auto_healing": True},
        position_manager=DummyPositionManager(),
    )

    result = asyncio.run(mgr.heartbeat_reconcile(tracked_total_pnl=0.0))

    assert result["live_total_pnl"] == 25.0
    assert result["drift"] == 25.0
    assert shadow["777"]["profit"] == 25.0
    assert shadow["777"]["sync_source"] == "MT5_SINGLE_SOURCE_OF_TRUTH"

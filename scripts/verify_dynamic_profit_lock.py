import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Direction, Position
from src.trading.profit_protection_module import ProfitProtectionModule, TradeManagementSettings


@dataclass(frozen=True)
class MockSymbolSpec:
    name: str = "EURUSD"
    digits: int = 5
    point: float = 0.00001
    trade_tick_size: float = 0.00001


class MockMT5Broker:
    def __init__(self):
        self.modify_requests = []

    async def modify_order(self, order_id, sl=None, tp=None):
        request = {
            "action": "SIMULATED_TRADE_ACTION_MODIFY",
            "position": int(order_id),
            "sl": sl,
            "tp": tp,
        }
        self.modify_requests.append(request)
        return True


def build_position() -> Position:
    return Position(
        position_id="1001",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=0.10,
        entry_price=1.14900,
        current_price=1.15300,
        unrealized_pnl=(1.15300 - 1.14900) * 0.10 * 100000.0,
        stop_loss=1.14500,
        take_profit=1.16000,
        opened_at=datetime.now(timezone.utc),
    )


def build_module() -> ProfitProtectionModule:
    settings = TradeManagementSettings(
        use_dynamic_profit_locking=True,
        dynamic_profit_lock_min_step_pips=2.0,
        dynamic_profit_lock_levels=[
            {"trigger_profit_pct": 0.3, "lock_profit_pct": 0.0, "use_entry_plus_spread": 1.0},
        ],
    )
    module = ProfitProtectionModule.__new__(ProfitProtectionModule)
    module.settings = settings
    module.broker = MockMT5Broker()
    module.execution_engine = SimpleNamespace()
    module.position_manager = None
    module.position_states = {}
    module.modify_failure_counts = {}
    module.modify_cooldowns = {}
    module.shield_cooldowns = {}
    module._save_state = lambda: None
    return module


async def verify_dynamic_profit_lock() -> None:
    module = build_module()
    position = build_position()
    symbol_spec = MockSymbolSpec()

    state = {
        "dynamic_profit_lock_hits": set(),
        "breakeven_reached": False,
        "last_modified_sl": position.stop_loss,
    }
    module.position_states[str(position.position_id)] = state

    expected_spread = 0.00010
    expected_sl = round(position.entry_price + expected_spread, symbol_spec.digits)

    simulated_requests = []

    async def fake_get_symbol_info(symbol: str):
        return symbol_spec

    async def fake_secure_modify(position_obj, target_sl, label, atr=0.0, priority_execution=False):
        normalized_sl = round(float(target_sl), symbol_spec.digits)
        last_modified_price = float(state.get("last_modified_sl") or 0.0)
        if abs(normalized_sl - last_modified_price) < symbol_spec.point:
            print("[SIMULATION] last_modified_price guard blocked duplicate modification.")
            return False

        simulated_request = {
            "action": "SIMULATED_TRADE_ACTION_MODIFY",
            "symbol": symbol_spec.name,
            "position": int(position_obj.position_id),
            "sl": normalized_sl,
            "tp": round(float(position_obj.take_profit), symbol_spec.digits),
            "digits": symbol_spec.digits,
            "comment": label,
        }
        simulated_requests.append(simulated_request)
        print("Simulated OrderSend:", simulated_request)

        state["last_modified_sl"] = normalized_sl
        position_obj.stop_loss = normalized_sl
        return True

    module._get_symbol_info = AsyncMock(side_effect=fake_get_symbol_info)
    module._secure_modify_sl = AsyncMock(side_effect=fake_secure_modify)

    live_tick = SimpleNamespace(bid=1.15290, ask=1.15300)
    with patch("src.trading.profit_protection_module.mt5.symbol_info_tick", return_value=live_tick):
        triggered = await module._apply_dynamic_profit_lock(position, state)

    current_profit_pct = ((live_tick.bid - position.entry_price) / position.entry_price) * 100.0
    assert current_profit_pct >= 0.3, f"Expected trigger >= 0.3%, got {current_profit_pct:.4f}%"
    assert triggered is True, "Expected profit protection to trigger"
    assert position.stop_loss == expected_sl, f"Expected SL {expected_sl}, got {position.stop_loss}"
    assert round(position.stop_loss, symbol_spec.digits) == expected_sl, "Expected rounded SL to match symbol digits"
    assert len(simulated_requests) == 1, "Expected one simulated modify request"

    print(
        f"[PROFIT_PROTECTION_DEBUG] | Symbol: {position.symbol} | Entry: {position.entry_price:.5f} | "
        f"Triggered: 0.3% | Old SL: 1.14500 | New SL: {expected_sl:.5f}"
    )

    state["dynamic_profit_lock_hits"] = set()
    with patch("src.trading.profit_protection_module.mt5.symbol_info_tick", return_value=live_tick):
        duplicate_trigger = await module._apply_dynamic_profit_lock(position, state)

    assert duplicate_trigger is False, "Expected duplicate modify to be suppressed"
    assert len(simulated_requests) == 1, "Expected no second simulated modify request"

    print("[VERIFY PASS] Dynamic profit lock triggered once and duplicate modification was blocked.")


if __name__ == "__main__":
    asyncio.run(verify_dynamic_profit_lock())

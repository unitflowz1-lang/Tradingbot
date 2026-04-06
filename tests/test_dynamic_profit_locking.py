from pathlib import Path
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Direction, Position
from src.trading.profit_protection_module import ProfitProtectionModule, TradeManagementSettings


def _make_position(
    *,
    direction: Direction = Direction.LONG,
    entry_price: float = 1.1000,
    current_price: float = 1.1035,
    stop_loss: float = 1.0950,
    take_profit: float = 1.1200,
) -> Position:
    if direction == Direction.LONG:
        unrealized_pnl = (current_price - entry_price) * 0.10 * 100000.0
    else:
        unrealized_pnl = (entry_price - current_price) * 0.10 * 100000.0
    return Position(
        position_id="lock-1",
        symbol="EUR/USD",
        direction=direction,
        quantity=0.10,
        entry_price=entry_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        stop_loss=stop_loss,
        take_profit=take_profit,
        opened_at=datetime.now(timezone.utc),
    )


def _make_module(settings: TradeManagementSettings | None = None) -> ProfitProtectionModule:
    module = ProfitProtectionModule.__new__(ProfitProtectionModule)
    module.settings = settings or TradeManagementSettings()
    module.position_states = {}
    module.modify_failure_counts = {}
    module.modify_cooldowns = {}
    module.shield_cooldowns = {}
    module.broker = SimpleNamespace()
    module.execution_engine = SimpleNamespace()
    module.position_manager = None
    module._save_state = lambda: None
    return module


@pytest.mark.asyncio
async def test_dynamic_profit_lock_moves_long_to_entry_plus_spread_at_point_three_percent():
    module = _make_module()
    position = _make_position(current_price=1.1036)
    state = {"dynamic_profit_lock_hits": set(), "breakeven_reached": False}

    module._get_symbol_info = AsyncMock(return_value=SimpleNamespace(name="EURUSD", point=0.00001, trade_tick_size=0.00001))
    module._secure_modify_sl = AsyncMock(return_value=True)

    from src.trading import profit_protection_module as ppm

    tick = SimpleNamespace(bid=1.1035, ask=1.1036)
    monkey_target = "src.trading.profit_protection_module.mt5.symbol_info_tick"

    from unittest.mock import patch

    with patch(monkey_target, return_value=tick):
        acted = await module._apply_dynamic_profit_lock(position, state)

    assert acted is True
    module._secure_modify_sl.assert_awaited()
    target_sl = module._secure_modify_sl.await_args.args[1]
    assert target_sl == pytest.approx(1.1001)
    assert "lock_pct_0_3" in state["dynamic_profit_lock_hits"]
    assert state["breakeven_reached"] is True


@pytest.mark.asyncio
async def test_dynamic_profit_lock_moves_short_to_locked_profit_tiers():
    module = _make_module()
    position = _make_position(
        direction=Direction.SHORT,
        entry_price=1.1000,
        current_price=1.0888,
        stop_loss=1.1050,
        take_profit=1.0800,
    )
    state = {"dynamic_profit_lock_hits": {"lock_pct_0_3"}, "breakeven_reached": True}

    module._get_symbol_info = AsyncMock(return_value=SimpleNamespace(name="EURUSD", point=0.00001, trade_tick_size=0.00001))

    async def _mock_modify(position_obj, target_sl, label, atr=0.0, priority_execution=False):
        position_obj.stop_loss = target_sl
        return True

    module._secure_modify_sl = AsyncMock(side_effect=_mock_modify)

    from unittest.mock import patch

    with patch("src.trading.profit_protection_module.mt5.symbol_info_tick", return_value=SimpleNamespace(bid=1.0887, ask=1.0888)):
        acted = await module._apply_dynamic_profit_lock(position, state)

    assert acted is True
    calls = module._secure_modify_sl.await_args_list
    assert len(calls) == 2
    assert calls[0].args[1] == pytest.approx(1.0978)
    assert calls[1].args[1] == pytest.approx(1.0934)
    assert {"lock_pct_0_6", "lock_pct_1_0"}.issubset(state["dynamic_profit_lock_hits"])


@pytest.mark.asyncio
async def test_dynamic_profit_lock_skips_when_improvement_is_below_min_step():
    settings = TradeManagementSettings(dynamic_profit_lock_min_step_pips=2.0)
    module = _make_module(settings=settings)
    position = _make_position(current_price=1.1036, stop_loss=1.1000)
    state = {"dynamic_profit_lock_hits": set(), "breakeven_reached": False}

    module._get_symbol_info = AsyncMock(return_value=SimpleNamespace(name="EURUSD", point=0.00001, trade_tick_size=0.00001))
    module._secure_modify_sl = AsyncMock(return_value=True)

    from unittest.mock import patch

    with patch("src.trading.profit_protection_module.mt5.symbol_info_tick", return_value=SimpleNamespace(bid=1.1035, ask=1.1036)):
        acted = await module._apply_dynamic_profit_lock(position, state)

    assert acted is False
    module._secure_modify_sl.assert_not_awaited()
    assert state["dynamic_profit_lock_hits"] == set()

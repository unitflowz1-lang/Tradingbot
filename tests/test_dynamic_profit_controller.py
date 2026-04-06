from pathlib import Path
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.models import Direction, Position
from src.trading.profit_protection_module import (
    DynamicProfitController,
    ProfitProtectionModule,
    TradeManagementSettings,
)


def _make_position(
    *,
    direction: Direction = Direction.LONG,
    entry_price: float = 1.1000,
    current_price: float = 1.1085,
    stop_loss: float = 1.0900,
    take_profit: float = 1.1300,
) -> Position:
    if direction == Direction.LONG:
        unrealized_pnl = (current_price - entry_price) * 0.10 * 100000.0
    else:
        unrealized_pnl = (entry_price - current_price) * 0.10 * 100000.0
    return Position(
        position_id="12345",
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


def _make_state(*, peak_profit_price: float, initial_risk_price: float = 0.0100):
    return {
        "initial_risk_price": initial_risk_price,
        "peak_profit_price": peak_profit_price,
        "partial_hits": set(),
        "breakeven_reached": False,
        "trailing_active": False,
        "scaled_out": False,
    }


def _make_module(be_result=True, partial_result=True, trail_result=True):
    return SimpleNamespace(
        _move_to_breakeven=AsyncMock(return_value=be_result),
        _execute_partial_close=AsyncMock(return_value=partial_result),
        _apply_velocity_trailing=AsyncMock(return_value=trail_result),
    )


@pytest.mark.asyncio
async def test_dynamic_profit_hits_breakeven_at_primary_r():
    controller = DynamicProfitController(
        broker=SimpleNamespace(),
        settings=TradeManagementSettings(),
        position_manager=None,
    )
    position = _make_position(current_price=1.1085)
    state = _make_state(peak_profit_price=1.1085)
    module = _make_module()

    acted = await controller.check_exits(module, position, state, atr=0.0020)

    assert acted is True
    module._move_to_breakeven.assert_awaited_once()
    assert "dynamic_be_primary" in state["partial_hits"]
    assert state["breakeven_reached"] is True


@pytest.mark.asyncio
async def test_dynamic_profit_chains_all_milestones_when_trade_reaches_1_5r():
    controller = DynamicProfitController(
        broker=SimpleNamespace(),
        settings=TradeManagementSettings(),
        position_manager=None,
    )
    position = _make_position(current_price=1.1160)
    state = _make_state(peak_profit_price=1.1160)
    module = _make_module()

    acted = await controller.check_exits(module, position, state, atr=0.0020)

    assert acted is True
    module._move_to_breakeven.assert_awaited_once()
    module._execute_partial_close.assert_awaited_once_with(position, 0.5)
    module._apply_velocity_trailing.assert_awaited_once()
    assert state["breakeven_reached"] is True
    assert state["scaled_out"] is True
    assert state["trailing_active"] is True
    assert {
        "dynamic_be_primary",
        "dynamic_partial_1_0r",
        "dynamic_trail_1_5r",
    }.issubset(state["partial_hits"])


@pytest.mark.asyncio
async def test_dynamic_profit_stops_advancing_when_partial_close_fails():
    controller = DynamicProfitController(
        broker=SimpleNamespace(),
        settings=TradeManagementSettings(),
        position_manager=None,
    )
    position = _make_position(current_price=1.1160)
    state = _make_state(peak_profit_price=1.1160)
    module = _make_module(be_result=True, partial_result=False, trail_result=True)

    acted = await controller.check_exits(module, position, state, atr=0.0020)

    assert acted is True
    module._move_to_breakeven.assert_awaited_once()
    module._execute_partial_close.assert_awaited_once_with(position, 0.5)
    module._apply_velocity_trailing.assert_not_awaited()
    assert "dynamic_be_primary" in state["partial_hits"]
    assert "dynamic_partial_1_0r" not in state["partial_hits"]
    assert "dynamic_trail_1_5r" not in state["partial_hits"]


@pytest.mark.asyncio
async def test_scale_out_harvests_profit_and_locks_breakeven_before_trailing():
    module = ProfitProtectionModule.__new__(ProfitProtectionModule)
    module.settings = TradeManagementSettings(
        use_scale_out=True,
        scale_out_trigger_r=0.5,
        scale_out_close_percent=0.5,
        scale_out_be_with_spread=True,
        use_breakeven=True,
    )
    module._execute_partial_close = AsyncMock(return_value=True)
    module._move_to_breakeven = AsyncMock(return_value=True)

    position = _make_position(current_price=1.1060)
    state = {
        "scaled_out": False,
        "breakeven_reached": False,
        "partial_hits": set(),
    }

    acted = await module._execute_scale_out_and_lock(position, state, current_r=0.6)

    assert acted is True
    module._execute_partial_close.assert_awaited_once_with(position, 0.5)
    module._move_to_breakeven.assert_awaited_once()
    assert state["scaled_out"] is True
    assert state["breakeven_reached"] is True
    assert "dynamic_partial_1_0r" in state["partial_hits"]

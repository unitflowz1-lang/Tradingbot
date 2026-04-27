from __future__ import annotations

import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.models import Direction, Position
from src.strategies.high_reward_reversal_peaks import (
    HighRewardReversalPeaksStrategy,
    ReversalPeaksConfig,
)


def _position(direction=Direction.LONG, strategy_meta=None, stop_loss=99.0):
    return Position(
        position_id="12345",
        symbol="EUR/USD",
        direction=direction,
        quantity=1.0,
        entry_price=100.0,
        current_price=101.0 if direction == Direction.LONG else 99.0,
        unrealized_pnl=1.0,
        stop_loss=stop_loss,
        take_profit=103.0 if direction == Direction.LONG else 97.0,
        opened_at=datetime.now(timezone.utc),
        contract_size=1.0,
        strategy_meta=strategy_meta or {},
    )


def test_position_strategy_meta_defaults_to_dict():
    pos = _position(strategy_meta=None)
    assert isinstance(pos.strategy_meta, dict)


def test_reversal_peaks_loads_persisted_state():
    strategy = HighRewardReversalPeaksStrategy(
        symbol="EUR/USD",
        config=ReversalPeaksConfig(),
    )
    state = {
        "strategy": "reversal_peaks",
        "trail_active": True,
        "activation_price": 101.5,
        "extreme_price": 102.2,
    }
    pos = _position(strategy_meta=state)

    strategy.load_position_state(pos)

    assert strategy._trail_state["trail_active"] is True
    assert strategy._trail_state["extreme_price"] == 102.2


def test_reversal_peaks_updates_trailing_stop_after_activation():
    strategy = HighRewardReversalPeaksStrategy(
        symbol="EUR/USD",
        config=ReversalPeaksConfig(trailing_atr_mult=3.0),
    )
    state = {
        "strategy": "reversal_peaks",
        "trail_active": False,
        "activation_price": 101.5,
        "extreme_price": 100.0,
    }
    pos = _position(strategy_meta=state, stop_loss=99.0)

    new_sl = strategy.update_trailing_stop(current_price=102.4, position=pos, current_atr=0.4)

    assert new_sl is not None
    assert round(new_sl, 5) == round(102.4 - (3.0 * 0.4), 5)
    assert pos.strategy_meta["trail_active"] is True
    assert pos.strategy_meta["extreme_price"] == 102.4

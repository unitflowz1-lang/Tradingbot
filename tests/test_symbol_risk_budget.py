from __future__ import annotations

from types import SimpleNamespace
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.risk.symbol_risk_budget import (
    estimate_position_risk_fraction,
    estimate_max_quantity_for_risk_fraction,
    evaluate_symbol_risk_budget,
    profitable_stack_capacity_bypass_allowed,
    stacking_direction_allowed,
)


def test_estimate_position_risk_fraction_uses_stop_distance_and_quantity():
    risk_fraction = estimate_position_risk_fraction(
        symbol="EUR/USD",
        entry_price=1.1000,
        stop_loss=1.0950,
        quantity=0.10,
        equity=10000.0,
    )

    assert round(risk_fraction, 4) == 0.005


def test_estimate_max_quantity_for_risk_fraction_converts_budget_to_lots():
    lots = estimate_max_quantity_for_risk_fraction(
        entry_price=1.1000,
        stop_loss=1.0980,
        equity=10000.0,
        risk_fraction=0.0025,
    )

    assert round(lots, 4) == 0.125


def test_evaluate_symbol_risk_budget_allows_multiple_small_risk_entries():
    positions = [
        SimpleNamespace(
            symbol="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0975,
            quantity=0.05,
            contract_size=100000.0,
        ),
        SimpleNamespace(
            symbol="EUR/USD",
            entry_price=1.1010,
            stop_loss=1.0985,
            quantity=0.05,
            contract_size=100000.0,
        ),
    ]

    decision = evaluate_symbol_risk_budget(
        symbol="EUR/USD",
        positions=positions,
        portfolio_positions=positions,
        equity=10000.0,
        candidate_entry_price=1.1020,
        candidate_stop_loss=1.1005,
        candidate_quantity=0.03,
        configured_max_positions_per_symbol=2,
        base_risk_per_trade=0.0025,
        dynamic_max_positions_per_symbol=7,
        max_portfolio_risk_fraction=0.05,
    )

    assert decision.allowed is True
    assert decision.current_positions == 2
    assert decision.allowed_positions >= 3
    assert decision.max_additional_quantity >= 0.03


def test_evaluate_symbol_risk_budget_rejects_when_budget_would_be_exceeded():
    positions = [
        SimpleNamespace(
            symbol="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0975,
            quantity=0.10,
            contract_size=100000.0,
        ),
        SimpleNamespace(
            symbol="EUR/USD",
            entry_price=1.1010,
            stop_loss=1.0985,
            quantity=0.10,
            contract_size=100000.0,
        ),
    ]

    decision = evaluate_symbol_risk_budget(
        symbol="EUR/USD",
        positions=positions,
        portfolio_positions=positions,
        equity=10000.0,
        candidate_entry_price=1.1020,
        candidate_stop_loss=1.0990,
        candidate_quantity=0.10,
        configured_max_positions_per_symbol=2,
        base_risk_per_trade=0.0025,
        dynamic_max_positions_per_symbol=7,
        max_portfolio_risk_fraction=0.05,
    )

    assert decision.allowed is False
    assert "budget" in decision.reason


def test_stacking_direction_allowed_only_for_short_when_symbol_already_open():
    positions = [SimpleNamespace(symbol="EUR/USD")]

    assert stacking_direction_allowed(
        current_positions=positions,
        candidate_direction="SHORT",
        allowed_stack_direction="SHORT",
    ) is True
    assert stacking_direction_allowed(
        current_positions=positions,
        candidate_direction="LONG",
        allowed_stack_direction="SHORT",
    ) is False
    assert stacking_direction_allowed(
        current_positions=[],
        candidate_direction="LONG",
        allowed_stack_direction="SHORT",
    ) is True


def test_profitable_stack_capacity_bypass_requires_same_direction_and_profit():
    positions = [
        SimpleNamespace(symbol="EUR/USD", direction="SHORT", unrealized_pnl=12.5),
        SimpleNamespace(symbol="EUR/USD", direction="SHORT", unrealized_pnl=3.0),
    ]
    assert profitable_stack_capacity_bypass_allowed(
        current_positions=positions,
        candidate_direction="SHORT",
    ) is True
    assert profitable_stack_capacity_bypass_allowed(
        current_positions=positions,
        candidate_direction="LONG",
    ) is False
    assert profitable_stack_capacity_bypass_allowed(
        current_positions=[SimpleNamespace(symbol="EUR/USD", direction="SHORT", unrealized_pnl=-4.0)],
        candidate_direction="SHORT",
    ) is False


def test_evaluate_symbol_risk_budget_resizes_to_remaining_budget():
    positions = [
        SimpleNamespace(
            symbol="EUR/USD",
            entry_price=1.1000,
            stop_loss=1.0980,
            quantity=0.225,
            contract_size=100000.0,
        ),
    ]

    decision = evaluate_symbol_risk_budget(
        symbol="EUR/USD",
        positions=positions,
        portfolio_positions=positions,
        equity=10000.0,
        candidate_entry_price=1.1010,
        candidate_stop_loss=1.0990,
        candidate_quantity=0.10,
        configured_max_positions_per_symbol=2,
        base_risk_per_trade=0.0025,
        dynamic_max_positions_per_symbol=7,
        max_portfolio_risk_fraction=0.05,
    )

    assert decision.allowed is True
    assert round(decision.max_additional_quantity, 4) == 0.025

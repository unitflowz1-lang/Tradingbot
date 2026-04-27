"""Helpers for risk-based same-symbol stacking decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


def normalize_symbol(symbol: str) -> str:
    return str(symbol or "").replace("/", "").replace("_", "").upper()


def normalize_direction(direction: Any) -> str:
    if direction is None:
        return ""
    return str(getattr(direction, "value", direction) or "").strip().upper()


def stacking_direction_allowed(
    *,
    current_positions: Iterable[Any],
    candidate_direction: Any,
    allowed_stack_direction: str = "SHORT",
) -> bool:
    """Allow stacking only for the configured direction once a symbol is already open."""
    if not list(current_positions):
        return True
    return normalize_direction(candidate_direction) == normalize_direction(allowed_stack_direction)


def profitable_stack_capacity_bypass_allowed(
    *,
    current_positions: Iterable[Any],
    candidate_direction: Any,
) -> bool:
    """
    Allow bypassing the portfolio-wide hard cap only when adding to an already
    winning position cluster in the same direction.
    """
    positions = list(current_positions)
    if not positions:
        return False
    target_direction = normalize_direction(candidate_direction)
    if target_direction != "SHORT":
        return False
    matching_positions = [
        pos for pos in positions
        if normalize_direction(getattr(pos, "direction", None)) == target_direction
    ]
    if not matching_positions:
        return False
    total_pnl = sum(float(getattr(pos, "unrealized_pnl", 0.0) or 0.0) for pos in matching_positions)
    return total_pnl > 0.0


def estimate_position_risk_fraction(
    *,
    symbol: str,
    entry_price: float,
    stop_loss: float,
    quantity: float,
    equity: float,
    contract_size: float = 100000.0,
) -> float:
    """Estimate absolute risk as a fraction of account equity."""
    if equity <= 0:
        return 0.0
    if quantity <= 0 or entry_price <= 0 or stop_loss <= 0:
        return 0.0
    price_risk = abs(float(entry_price) - float(stop_loss))
    if price_risk <= 0:
        return 0.0
    notional_risk = price_risk * float(contract_size or 100000.0) * float(quantity)
    return max(0.0, notional_risk / float(equity))


@dataclass
class SymbolRiskBudgetDecision:
    allowed: bool
    current_positions: int
    allowed_positions: int
    dynamic_cap: int
    current_risk_fraction: float
    candidate_risk_fraction: float
    symbol_risk_budget_fraction: float
    portfolio_risk_budget_fraction: float
    current_portfolio_risk_fraction: float
    remaining_risk_fraction: float
    remaining_portfolio_risk_fraction: float
    max_additional_quantity: float
    reason: str


def estimate_max_quantity_for_risk_fraction(
    *,
    entry_price: float,
    stop_loss: float,
    equity: float,
    risk_fraction: float,
    contract_size: float = 100000.0,
) -> float:
    """Convert remaining risk fraction into maximum additional lot size."""
    if equity <= 0 or risk_fraction <= 0:
        return 0.0
    price_risk = abs(float(entry_price) - float(stop_loss))
    if price_risk <= 0:
        return 0.0
    risk_amount = float(equity) * float(risk_fraction)
    return max(0.0, risk_amount / (price_risk * float(contract_size or 100000.0)))


def estimate_portfolio_risk_fraction(
    *,
    positions: Iterable[Any],
    equity: float,
) -> float:
    total = 0.0
    for pos in positions:
        total += estimate_position_risk_fraction(
            symbol=getattr(pos, "symbol", ""),
            entry_price=float(getattr(pos, "entry_price", 0.0) or 0.0),
            stop_loss=float(getattr(pos, "stop_loss", 0.0) or 0.0),
            quantity=float(getattr(pos, "quantity", getattr(pos, "volume", 0.0)) or 0.0),
            equity=equity,
            contract_size=float(getattr(pos, "contract_size", 100000.0) or 100000.0),
        )
    return total


def evaluate_symbol_risk_budget(
    *,
    symbol: str,
    positions: Iterable[Any],
    portfolio_positions: Iterable[Any],
    equity: float,
    candidate_entry_price: float,
    candidate_stop_loss: float,
    candidate_quantity: float,
    configured_max_positions_per_symbol: int,
    base_risk_per_trade: float,
    dynamic_max_positions_per_symbol: int,
    max_portfolio_risk_fraction: float,
) -> SymbolRiskBudgetDecision:
    """
    Decide whether another position on the same symbol can be opened.

    The symbol risk budget scales from the configured per-symbol count and the
    base risk-per-trade. This allows multiple smaller-risk entries while still
    blocking oversized concentration.
    """
    symbol_key = normalize_symbol(symbol)
    same_symbol_positions = [
        pos for pos in positions if normalize_symbol(getattr(pos, "symbol", "")) == symbol_key
    ]
    current_positions = len(same_symbol_positions)
    dynamic_cap = max(1, int(dynamic_max_positions_per_symbol or configured_max_positions_per_symbol or 1))
    configured_cap = max(1, int(configured_max_positions_per_symbol or 1))
    base_risk = max(0.0, float(base_risk_per_trade or 0.0))
    symbol_risk_budget_fraction = max(base_risk, configured_cap * base_risk)
    portfolio_risk_budget_fraction = max(0.0, float(max_portfolio_risk_fraction or 0.0))

    current_risk_fraction = 0.0
    for pos in same_symbol_positions:
        current_risk_fraction += estimate_position_risk_fraction(
            symbol=getattr(pos, "symbol", symbol),
            entry_price=float(getattr(pos, "entry_price", 0.0) or 0.0),
            stop_loss=float(getattr(pos, "stop_loss", 0.0) or 0.0),
            quantity=float(
                getattr(pos, "quantity", getattr(pos, "volume", 0.0)) or 0.0
            ),
            equity=equity,
            contract_size=float(getattr(pos, "contract_size", 100000.0) or 100000.0),
        )

    candidate_risk_fraction = estimate_position_risk_fraction(
        symbol=symbol,
        entry_price=float(candidate_entry_price or 0.0),
        stop_loss=float(candidate_stop_loss or 0.0),
        quantity=float(candidate_quantity or 0.0),
        equity=equity,
    )
    current_portfolio_risk_fraction = estimate_portfolio_risk_fraction(
        positions=portfolio_positions,
        equity=equity,
    )
    remaining_risk_fraction = max(0.0, symbol_risk_budget_fraction - current_risk_fraction)
    remaining_portfolio_risk_fraction = max(0.0, portfolio_risk_budget_fraction - current_portfolio_risk_fraction)
    max_quantity_symbol = estimate_max_quantity_for_risk_fraction(
        entry_price=candidate_entry_price,
        stop_loss=candidate_stop_loss,
        equity=equity,
        risk_fraction=remaining_risk_fraction,
    )
    max_quantity_portfolio = estimate_max_quantity_for_risk_fraction(
        entry_price=candidate_entry_price,
        stop_loss=candidate_stop_loss,
        equity=equity,
        risk_fraction=remaining_portfolio_risk_fraction,
    )
    max_additional_quantity = min(
        float(candidate_quantity or 0.0),
        max_quantity_symbol,
        max_quantity_portfolio,
    )

    if current_positions >= dynamic_cap:
        return SymbolRiskBudgetDecision(
            allowed=False,
            current_positions=current_positions,
            allowed_positions=dynamic_cap,
            dynamic_cap=dynamic_cap,
            current_risk_fraction=current_risk_fraction,
            candidate_risk_fraction=candidate_risk_fraction,
            symbol_risk_budget_fraction=symbol_risk_budget_fraction,
            portfolio_risk_budget_fraction=portfolio_risk_budget_fraction,
            current_portfolio_risk_fraction=current_portfolio_risk_fraction,
            remaining_risk_fraction=remaining_risk_fraction,
            remaining_portfolio_risk_fraction=remaining_portfolio_risk_fraction,
            max_additional_quantity=0.0,
            reason=f"symbol stack cap reached ({current_positions}/{dynamic_cap})",
        )

    if candidate_risk_fraction <= 0:
        return SymbolRiskBudgetDecision(
            allowed=True,
            current_positions=current_positions,
            allowed_positions=dynamic_cap,
            dynamic_cap=dynamic_cap,
            current_risk_fraction=current_risk_fraction,
            candidate_risk_fraction=0.0,
            symbol_risk_budget_fraction=symbol_risk_budget_fraction,
            portfolio_risk_budget_fraction=portfolio_risk_budget_fraction,
            current_portfolio_risk_fraction=current_portfolio_risk_fraction,
            remaining_risk_fraction=remaining_risk_fraction,
            remaining_portfolio_risk_fraction=remaining_portfolio_risk_fraction,
            max_additional_quantity=0.0,
            reason="candidate risk unavailable; allowing within stack cap",
        )

    epsilon = 1e-12
    max_affordable_positions = current_positions + max(
        0,
        int(math.floor((symbol_risk_budget_fraction - current_risk_fraction + epsilon) / candidate_risk_fraction)),
    )
    allowed_positions = min(dynamic_cap, max_affordable_positions)
    full_candidate_within_budget = (
        (current_risk_fraction + candidate_risk_fraction) <= (symbol_risk_budget_fraction + epsilon)
        and (current_portfolio_risk_fraction + candidate_risk_fraction) <= (portfolio_risk_budget_fraction + epsilon)
    )
    allowed = max_additional_quantity > epsilon

    reason = (
        f"symbol risk budget exceeded ({current_risk_fraction + candidate_risk_fraction:.4f} > "
        f"{symbol_risk_budget_fraction:.4f})"
    )
    if (current_portfolio_risk_fraction + candidate_risk_fraction) > (portfolio_risk_budget_fraction + epsilon):
        reason = (
            f"portfolio risk budget exceeded ({current_portfolio_risk_fraction + candidate_risk_fraction:.4f} > "
            f"{portfolio_risk_budget_fraction:.4f})"
        )
    if full_candidate_within_budget:
        reason = (
            f"symbol/portfolio stack allowed by risk budget ({current_risk_fraction + candidate_risk_fraction:.4f} <= "
            f"{symbol_risk_budget_fraction:.4f}, {current_portfolio_risk_fraction + candidate_risk_fraction:.4f} <= "
            f"{portfolio_risk_budget_fraction:.4f})"
        )
    elif allowed:
        resized_candidate_risk_fraction = estimate_position_risk_fraction(
            symbol=symbol,
            entry_price=float(candidate_entry_price or 0.0),
            stop_loss=float(candidate_stop_loss or 0.0),
            quantity=max_additional_quantity,
            equity=equity,
        )
        reason = (
            f"symbol/portfolio stack allowed after resize ({current_risk_fraction + resized_candidate_risk_fraction:.4f} <= "
            f"{symbol_risk_budget_fraction:.4f}, {current_portfolio_risk_fraction + resized_candidate_risk_fraction:.4f} <= "
            f"{portfolio_risk_budget_fraction:.4f})"
        )

    return SymbolRiskBudgetDecision(
        allowed=allowed,
        current_positions=current_positions,
        allowed_positions=max(current_positions + (1 if allowed else 0), allowed_positions),
        dynamic_cap=dynamic_cap,
        current_risk_fraction=current_risk_fraction,
        candidate_risk_fraction=candidate_risk_fraction,
        symbol_risk_budget_fraction=symbol_risk_budget_fraction,
        portfolio_risk_budget_fraction=portfolio_risk_budget_fraction,
        current_portfolio_risk_fraction=current_portfolio_risk_fraction,
        remaining_risk_fraction=remaining_risk_fraction,
        remaining_portfolio_risk_fraction=remaining_portfolio_risk_fraction,
        max_additional_quantity=max(0.0, max_additional_quantity),
        reason=reason,
    )

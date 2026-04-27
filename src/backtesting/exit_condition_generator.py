"""
Exit Condition Generator for Backtesting
Provides multiple exit strategies for trades during simulation
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, List, Dict, Any
from enum import Enum

from src.models import Position, MarketData, Direction


class ExitConditionType(Enum):
    """Types of exit conditions"""
    TAKE_PROFIT = "take_profit"
    STOP_LOSS = "stop_loss"
    TRAILING_STOP = "trailing_stop"
    TIME_BASED = "time_based"
    TECHNICAL = "technical"
    BREAKEVEN = "breakeven"
    CUSTOM = "custom"


@dataclass
class ExitCondition:
    """Represents a single exit condition"""
    condition_type: ExitConditionType
    enabled: bool = True
    description: str = ""

    def check(
        self,
        position: Position,
        market_data: MarketData,
        entry_price: float,
        entry_time: datetime,
        position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str]]:
        """
        Check if exit condition is met.

        Args:
            position: The open position
            market_data: Current market data
            entry_price: Price when position was opened
            entry_time: Time when position was opened
            position_history: Historical data for the position

        Returns:
            Tuple of (should_exit, exit_reason)
        """
        raise NotImplementedError


@dataclass
class TakeProfitCondition(ExitCondition):
    """Exit when profit target is reached"""
    profit_pips: float = 50  # Profit in pips
    condition_type: ExitConditionType = ExitConditionType.TAKE_PROFIT

    def __post_init__(self):
        if not self.description:
            self.description = (
                f"Take Profit at {self.profit_pips} pips")

    def check(
        self,
        position: Position,
        market_data: MarketData,
        entry_price: float,
        entry_time: datetime,
        position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str]]:
        """Check if profit target is reached"""
        if not self.enabled:
            return False, None

        # Use position's take_profit price if available
        if position.take_profit is None:
            return False, None

        if position.direction == Direction.LONG:
            # For longs, check if high touched the target
            if market_data.high >= position.take_profit:
                return True, f"Take Profit at {position.take_profit:.5f}"
        else:  # SHORT
            # For shorts, check if low touched the target
            if market_data.low <= position.take_profit:
                return True, f"Take Profit at {position.take_profit:.5f}"

        return False, None


@dataclass
class StopLossCondition(ExitCondition):
    """Exit when loss limit is reached"""
    loss_pips: float = 30  # Max loss in pips
    condition_type: ExitConditionType = ExitConditionType.STOP_LOSS

    def __post_init__(self):
        if not self.description:
            self.description = f"Stop Loss at {self.loss_pips} pips"

    def check(
        self,
        position: Position,
        market_data: MarketData,
        entry_price: float,
        entry_time: datetime,
        position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str]]:
        """Check if stop loss is hit"""
        if not self.enabled:
            return False, None

        # Use position's stop_loss price if available
        if position.stop_loss is None:
            return False, None

        if position.direction == Direction.LONG:
            # For longs, check if low touched the stop loss
            if market_data.low <= position.stop_loss:
                return True, f"Stop Loss hit: {position.stop_loss:.5f}"
        else:  # SHORT
            # For shorts, check if high touched the stop loss
            if market_data.high >= position.stop_loss:
                return True, f"Stop Loss hit: {position.stop_loss:.5f}"

        return False, None


@dataclass
class TrailingStopCondition(ExitCondition):
    """Exit using trailing stop"""
    trailing_pips: float = 20  # Trailing stop in pips
    max_profit_pips: float = 0  # Only activate after reaching
    condition_type: ExitConditionType = ExitConditionType.TRAILING_STOP

    def __post_init__(self):
        if not self.description:
            self.description = (
                f"Trailing Stop: {self.trailing_pips} pips "
                f"(activate at {self.max_profit_pips} pips profit)")
        self.highest_price = None
        self.lowest_price = None

    def check(
        self,
        position: Position,
        market_data: MarketData,
        entry_price: float,
        entry_time: datetime,
        position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str]]:
        """Check trailing stop condition"""
        if not self.enabled:
            return False, None

        pip_value = 0.01 if 'JPY' in market_data.symbol else 0.0001
        trailing_distance = self.trailing_pips * pip_value
        activation_profit = self.max_profit_pips * pip_value

        if position.direction == Direction.LONG:
            # Track highest price
            if self.highest_price is None:
                self.highest_price = market_data.close
            else:
                self.highest_price = max(self.highest_price,
                                        market_data.close)

            # Check if activated
            current_profit = self.highest_price - entry_price
            if current_profit >= activation_profit:
                # Trailing stop is active
                stop_level = self.highest_price - trailing_distance
                if market_data.close <= stop_level:
                    return True, (
                        f"Trailing Stop hit: "
                        f"high={self.highest_price:.5f}, "
                        f"current={market_data.close:.5f}")

        else:  # SHORT
            # Track lowest price
            if self.lowest_price is None:
                self.lowest_price = market_data.close
            else:
                self.lowest_price = min(self.lowest_price,
                                       market_data.close)

            # Check if activated
            current_profit = entry_price - self.lowest_price
            if current_profit >= activation_profit:
                # Trailing stop is active
                stop_level = self.lowest_price + trailing_distance
                if market_data.close >= stop_level:
                    return True, (
                        f"Trailing Stop hit: "
                        f"low={self.lowest_price:.5f}, "
                        f"current={market_data.close:.5f}")

        return False, None


@dataclass
class TimeBasedCondition(ExitCondition):
    """Exit after a certain time period"""
    hold_minutes: int = 60  # Hold position for X minutes
    condition_type: ExitConditionType = ExitConditionType.TIME_BASED

    def __post_init__(self):
        if not self.description:
            self.description = (
                f"Time-based exit: {self.hold_minutes} minutes")

    def check(
        self,
        position: Position,
        market_data: MarketData,
        entry_price: float,
        entry_time: datetime,
        position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str]]:
        """Check if hold period has expired"""
        if not self.enabled:
            return False, None

        time_held = market_data.timestamp - entry_time
        hold_period = timedelta(minutes=self.hold_minutes)

        if time_held >= hold_period:
            return True, (
                f"Time-based exit: held for {time_held} "
                f"(target: {hold_period})")

        return False, None


@dataclass
class BreakEvenCondition(ExitCondition):
    """Exit at breakeven when profit reaches minimum"""
    min_profit_pips: float = 10  # Activate when reaching profit
    protection_pips: float = 2   # Lock in protection
    condition_type: ExitConditionType = ExitConditionType.BREAKEVEN

    def __post_init__(self):
        if not self.description:
            self.description = (
                f"Breakeven protection: activate at {self.min_profit_pips} "
                f"pips, protect {self.protection_pips} pips")
        self.highest_profit_reached = 0.0

    def check(
        self,
        position: Position,
        market_data: MarketData,
        entry_price: float,
        entry_time: datetime,
        position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str]]:
        """Check breakeven stop condition"""
        if not self.enabled:
            return False, None

        pip_value = 0.01 if 'JPY' in market_data.symbol else 0.0001
        min_profit = self.min_profit_pips * pip_value
        protection = self.protection_pips * pip_value

        if position.direction == Direction.LONG:
            current_profit = market_data.close - entry_price
            self.highest_profit_reached = max(
                self.highest_profit_reached, current_profit)

            # If reached minimum profit and now pulling back
            if (self.highest_profit_reached >= min_profit and
                    current_profit <= (self.highest_profit_reached -
                                      protection)):
                return True, (
                    f"Breakeven protection triggered: "
                    f"max_profit={self.highest_profit_reached:.5f}, "
                    f"current={current_profit:.5f}")

        else:  # SHORT
            current_profit = entry_price - market_data.close
            self.highest_profit_reached = max(
                self.highest_profit_reached, current_profit)

            if (self.highest_profit_reached >= min_profit and
                    current_profit <= (self.highest_profit_reached -
                                      protection)):
                return True, (
                    f"Breakeven protection triggered: "
                    f"max_profit={self.highest_profit_reached:.5f}, "
                    f"current={current_profit:.5f}")

        return False, None


class ExitConditionGenerator:
    """Generator for creating and managing exit conditions"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.conditions: List[ExitCondition] = []

    def add_condition(self, condition: ExitCondition) -> 'ExitConditionGenerator':
        """Add an exit condition"""
        self.conditions.append(condition)
        self.logger.info(
            f"Added exit condition: {condition.condition_type.value} - "
            f"{condition.description}")
        return self

    def add_take_profit(
            self, profit_pips: float = 50) -> 'ExitConditionGenerator':
        """Add take profit condition"""
        return self.add_condition(
            TakeProfitCondition(profit_pips=profit_pips))

    def add_stop_loss(
            self, loss_pips: float = 30) -> 'ExitConditionGenerator':
        """Add stop loss condition"""
        return self.add_condition(
            StopLossCondition(loss_pips=loss_pips))

    def add_trailing_stop(
            self, trailing_pips: float = 20,
            activate_at_pips: float = 0) -> 'ExitConditionGenerator':
        """Add trailing stop condition"""
        return self.add_condition(
            TrailingStopCondition(
                trailing_pips=trailing_pips,
                max_profit_pips=activate_at_pips))

    def add_time_based_exit(
            self, hold_minutes: int = 60) -> 'ExitConditionGenerator':
        """Add time-based exit condition"""
        return self.add_condition(
            TimeBasedCondition(hold_minutes=hold_minutes))

    def add_breakeven_protection(
            self, min_profit_pips: float = 10,
            protection_pips: float = 2) -> 'ExitConditionGenerator':
        """Add breakeven protection condition"""
        return self.add_condition(
            BreakEvenCondition(
                min_profit_pips=min_profit_pips,
                protection_pips=protection_pips))

    def check_all_conditions(
            self,
            position: Position,
            market_data: MarketData,
            entry_price: float,
            entry_time: datetime,
            position_history: List[MarketData] = None
    ) -> tuple[bool, Optional[str], Optional[ExitConditionType]]:
        """
        Check all conditions and return first one that triggers.

        Returns:
            Tuple of (should_exit, reason, condition_type)
        """
        for condition in self.conditions:
            should_exit, reason = condition.check(
                position, market_data, entry_price,
                entry_time, position_history)

            if should_exit:
                self.logger.info(
                    f"Exit triggered by {condition.condition_type.value}: "
                    f"{reason}")
                return True, reason, condition.condition_type

        return False, None, None

    def create_default_strategy(self) -> 'ExitConditionGenerator':
        """Create default exit strategy (TP, SL, Trailing)"""
        return (self
                .add_take_profit(profit_pips=50)
                .add_stop_loss(loss_pips=30)
                .add_trailing_stop(trailing_pips=20, activate_at_pips=25))

    def create_aggressive_strategy(self) -> 'ExitConditionGenerator':
        """Create aggressive exit strategy (tight stops)"""
        return (self
                .add_stop_loss(loss_pips=15)
                .add_take_profit(profit_pips=30)
                .add_time_based_exit(hold_minutes=30))

    def create_conservative_strategy(self) -> 'ExitConditionGenerator':
        """Create conservative exit strategy (wide stops)"""
        return (self
                .add_stop_loss(loss_pips=50)
                .add_take_profit(profit_pips=100)
                .add_breakeven_protection(min_profit_pips=20,
                                         protection_pips=5))

    def create_scalping_strategy(self) -> 'ExitConditionGenerator':
        """Create scalping strategy (quick exits)"""
        return (self
                .add_take_profit(profit_pips=10)
                .add_stop_loss(loss_pips=5)
                .add_time_based_exit(hold_minutes=5)
                .add_trailing_stop(trailing_pips=3, activate_at_pips=5))

    def reset(self) -> 'ExitConditionGenerator':
        """Clear all conditions"""
        self.conditions.clear()
        return self

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all conditions"""
        return {
            'total_conditions': len(self.conditions),
            'conditions': [
                {
                    'type': c.condition_type.value,
                    'description': c.description,
                    'enabled': c.enabled
                }
                for c in self.conditions
            ]
        }

    def enable_condition(self,
                        condition_type: ExitConditionType) -> 'ExitConditionGenerator':
        """Enable specific condition type"""
        for condition in self.conditions:
            if condition.condition_type == condition_type:
                condition.enabled = True
        return self

    def disable_condition(self,
                         condition_type: ExitConditionType) -> 'ExitConditionGenerator':
        """Disable specific condition type"""
        for condition in self.conditions:
            if condition.condition_type == condition_type:
                condition.enabled = False
        return self

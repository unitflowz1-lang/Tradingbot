"""
Advanced Exit Conditions Handler
Manages multiple exit strategies for better profit-taking and risk management
"""

import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime, timedelta, timezone
from enum import Enum

from src.models import Direction, ExitPolicy


class ExitType(Enum):
    """Types of exit triggers"""
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    BREAKEVEN = "BREAKEVEN"
    TIME_EXIT = "TIME_EXIT"
    PARTIAL_PROFIT = "PARTIAL_PROFIT"
    REVERSAL = "REVERSAL"
    FRIDAY_CLOSE = "FRIDAY_CLOSE"


@dataclass
class ExitLevel:
    """Represents an exit level with conditions"""
    price: float
    pnl_percent: float
    exit_type: ExitType
    exit_quantity_percent: float = 1.0  # % of position to close
    description: str = ""


class AdvancedExitHandler:
    """Handles advanced exit conditions for positions"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)
        
        # Configuration - QUANTITATIVE FOREX APPROACH
        self.use_trailing_stop = True
        self.use_breakeven_stop = True
        self.use_time_based_exit = True
        
        # 1. Break Even+ Protocol
        self.breakeven_trigger_r = 1.0        # Secure break even at 1.0R
        self.breakeven_plus_pips = 1.5        # Extra buffer (BE + Spread + 1.5 pips)
        
        # 2. Dynamic Scale-Outs (Securing the bag)
        self.partial_profit_levels = [
            (1.5, 0.50, "TP1 Securing 50%"),  # TP1: 50% at 1.5R
            (2.5, 0.25, "TP2 Securing 25%")   # TP2: 25% at 2.5R
        ]
        
        # 3. ATR Trailing Stop (Only after TP1)
        self.trail_activation_r = 1.5         # Activates after TP1
        self.trail_atr_multiplier = 2.0       # Default 2.0x ATR
        self.trail_atr_strong_trend = 2.5     # 2.5x ATR if ADX > 25
        
        # 4. Time-Based Stagnation (Anti-Bleed)
        self.stagnation_hours = 8             # Close if stagnating for 8 hours
        self.stagnation_r_range = 0.2         # Range ±0.2R for stagnation
        
        # Friday Close Rule
        self.friday_close_hour = 21           # 21:00 Broker Time
        
        # Legacy/Misc
        self.secure_profit_threshold = 50.0   # Secure everything if up $50 (scaled for 95k)
        
    def evaluate_exit_conditions(self,
                                 symbol: str,
                                 entry_price: float,
                                 current_price: float,
                                 current_pnl: float,
                                 stop_loss: float,
                                 take_profit: float,
                                 direction: Direction,
                                 position_open_time: datetime,
                                 position_high: Optional[float] = None,
                                 exit_policy: ExitPolicy = ExitPolicy.STANDARD,
                                 atr: float = 0.0,
                                 adx: float = 0.0,
                                 current_spread_pips: float = 2.0) -> Tuple[Optional[ExitLevel], float]:
        """
        Evaluate all exit conditions based on quantitative Forex mechanics
        """
        pip_value = 0.01 if 'JPY' in symbol else 0.0001
        now = datetime.now(timezone.utc)
        
        # Calculate Risk and current Profit in R-multiple
        risk_price = abs(entry_price - stop_loss) if stop_loss else (entry_price * 0.01)
        
        if direction == Direction.LONG:
            profit_price = current_price - entry_price
            high_profit_price = (position_high - entry_price) if position_high else profit_price
        else:
            profit_price = entry_price - current_price
            high_profit_price = (entry_price - position_high) if position_high else profit_price
            
        current_R = profit_price / risk_price if risk_price > 0 else 0
        high_R = high_profit_price / risk_price if risk_price > 0 else 0
        profit_pips = profit_price / pip_value

        # List to track triggered exits
        exit_levels = []
        
        # 1. Friday Close Rule (21:00 Broker Time)
        if now.weekday() == 4 and now.hour >= self.friday_close_hour:
             return ExitLevel(current_price, profit_pips, ExitType.FRIDAY_CLOSE, 1.0, "Friday Close Rule"), profit_pips

        # 2. Hard stops (SL/TP)
        if direction == Direction.LONG:
            if stop_loss and current_price <= stop_loss:
                exit_levels.append(ExitLevel(stop_loss, profit_pips, ExitType.STOP_LOSS, 1.0, "Hard SL"))
            if take_profit and current_price >= take_profit:
                exit_levels.append(ExitLevel(take_profit, profit_pips, ExitType.TAKE_PROFIT, 1.0, "Hard TP"))
        else:
            if stop_loss and current_price >= stop_loss:
                exit_levels.append(ExitLevel(stop_loss, profit_pips, ExitType.STOP_LOSS, 1.0, "Hard SL"))
            if take_profit and current_price <= take_profit:
                exit_levels.append(ExitLevel(take_profit, profit_pips, ExitType.TAKE_PROFIT, 1.0, "Hard TP"))

        # 3. The 'Break Even+' Protocol (at +1.0R)
        if self.use_breakeven_stop and current_R >= self.breakeven_trigger_r:
            # BE + Spread + 1.5 pips
            be_offset = (current_spread_pips + self.breakeven_plus_pips) * pip_value
            be_price = entry_price + be_offset if direction == Direction.LONG else entry_price - be_offset

            # Trigger modification if current SL is worse than BE+
            is_better = (direction == Direction.LONG and (not stop_loss or be_price > stop_loss)) or \
                        (direction == Direction.SHORT and (not stop_loss or be_price < stop_loss))

            if is_better:
                # This returns a modification request
                exit_levels.append(ExitLevel(be_price, profit_pips, ExitType.BREAKEVEN, 0.0, "Move to BE+"))

        # 4. Dynamic Scale-Outs
        for target_R, qty_pct, label in self.partial_profit_levels:
            if current_R >= target_R:
                 # Check if this partial was already hit (handled by PositionManager, but we flag it here)
                 exit_levels.append(ExitLevel(current_price, profit_pips, ExitType.PARTIAL_PROFIT, qty_pct, label))

        # 5. ATR Trailing Stop (Only after TP1 / 1.5R)
        if self.use_trailing_stop and current_R >= self.trail_activation_r:
            # Dynamic ATR Buffer
            mult = self.trail_atr_multiplier
            if adx > 25: mult = self.trail_atr_strong_trend

            trail_dist = atr * mult
            if direction == Direction.LONG:
                trail_price = current_price - trail_dist
                if stop_loss and trail_price > stop_loss:
                    exit_levels.append(ExitLevel(trail_price, profit_pips, ExitType.TRAILING_STOP, 0.0, f"Trailing {mult}x ATR"))
            else:
                trail_price = current_price + trail_dist
                if stop_loss and trail_price < stop_loss:
                    exit_levels.append(ExitLevel(trail_price, profit_pips, ExitType.TRAILING_STOP, 0.0, f"Trailing {mult}x ATR"))

        # 6. Time-Based Stagnation Exit
        if self.use_time_based_exit:
            hold_time_hours = (now - position_open_time).total_seconds() / 3600
            if hold_time_hours >= self.stagnation_hours:
                # If stagnating between -0.2R and +0.2R
                if abs(current_R) <= self.stagnation_r_range:
                    exit_levels.append(ExitLevel(current_price, profit_pips, ExitType.TIME_EXIT, 1.0, f"Stagnation Exit ({hold_time_hours:.1f}h)"))

        if not exit_levels:
            return None, profit_pips
        
        # Prioritize stop loss
        for exit_level in exit_levels:
            if exit_level.exit_type == ExitType.STOP_LOSS:
                return exit_level, profit_pips
        
        # Otherwise return best exit
        best_exit = max(exit_levels, key=lambda x: x.pnl_percent)
        return best_exit, profit_pips
    
    def _check_trailing_stop(self,
                            entry_price: float,
                            position_high: float,
                            current_price: float,
                            direction: Direction,
                            pip_value: float) -> Optional[ExitLevel]:
        """Check if trailing stop should trigger"""
        if direction == Direction.LONG:
            profit_pips = (position_high - entry_price) / pip_value
            # Trigger trailing stop if price fell X pips from high
            if profit_pips >= self.trailing_stop_pips_trigger:
                trailing_stop_price = position_high - (self.trailing_stop_move_pips * pip_value)
                if current_price <= trailing_stop_price:
                    return ExitLevel(
                        price=current_price,
                        pnl_percent=profit_pips,
                        exit_type=ExitType.TRAILING_STOP,
                        description=f"Trailing stop triggered at {current_price:.5f}"
                    )
        else:  # SHORT
            profit_pips = (entry_price - position_high) / pip_value
            if profit_pips >= self.trailing_stop_pips_trigger:
                trailing_stop_price = position_high + (self.trailing_stop_move_pips * pip_value)
                if current_price >= trailing_stop_price:
                    return ExitLevel(
                        price=current_price,
                        pnl_percent=profit_pips,
                        exit_type=ExitType.TRAILING_STOP,
                        description=f"Trailing stop triggered at {current_price:.5f}"
                    )
        
        return None
    
    def _check_breakeven_stop(self,
                             entry_price: float,
                             current_price: float,
                             direction: Direction,
                             pip_value: float) -> Optional[ExitLevel]:
        """Check if breakeven stop should be set"""
        # Define offset to cover fees/spread (e.g. 1 pip secured)
        # Use simple string check for JPY pairs (direction enum doesn't contain symbol usually, but we passed it earlier or can infer)
        # Actually direction is an Enum. We should pass symbol to this method if we want to be precise, 
        # but for now we'll assume standard 1 pip (0.0001) or 0.01 for JPY based on the pip_value passed in.
        BE_OFFSET = 10 * pip_value if pip_value > 0.001 else 1 * pip_value 
        
        if direction == Direction.LONG:
            profit_pips = (current_price - entry_price) / pip_value
            if profit_pips >= self.breakeven_trigger_pips:
                return ExitLevel(
                    price=entry_price + BE_OFFSET,
                    pnl_percent=profit_pips,
                    exit_type=ExitType.BREAKEVEN,
                    description="Move SL to Breakeven"
                )
        else:  # SHORT
            profit_pips = (entry_price - current_price) / pip_value
            if profit_pips >= self.breakeven_trigger_pips:
                return ExitLevel(
                    price=entry_price - BE_OFFSET,
                    pnl_percent=profit_pips,
                    exit_type=ExitType.BREAKEVEN,
                    description="Move SL to Breakeven"
                )
        
        return None
    
    def _check_partial_profits(self,
                              entry_price: float,
                              current_price: float,
                              direction: Direction,
                              unrealized_pnl_pips: float,
                              pip_value: float) -> list:
        """Check if any partial profit targets should be hit"""
        partial_exits = []
        
        for target_pips, quantity_percent in self.partial_profit_levels:
            if unrealized_pnl_pips >= target_pips:
                # Only add if we haven't already added this level
                if not any(e.exit_type == ExitType.PARTIAL_PROFIT and e.pnl_percent >= target_pips for e in partial_exits):
                    partial_exits.append(ExitLevel(
                        price=current_price,
                        pnl_percent=unrealized_pnl_pips,
                        exit_type=ExitType.PARTIAL_PROFIT,
                        exit_quantity_percent=quantity_percent,
                        description=f"Partial profit at {target_pips} pips, close {quantity_percent*100:.0f}%"
                    ))
        
        return partial_exits
    
    def _check_time_based_exit(self,
                              entry_price: float,
                              current_price: float,
                              position_open_time: datetime,
                              unrealized_pnl_pips: float,
                              direction: Direction,
                              pip_value: float) -> Optional[ExitLevel]:
        """Check if time-based exit conditions are met"""
        now = datetime.now(timezone.utc)
        hold_time_minutes = (now - position_open_time).total_seconds() / 60
        
        # Exit if held too long AND losing money
        # 1. Hard Time Limit (Max Hold) - expanded to include even small profits if stuck
        if hold_time_minutes >= self.max_hold_time_minutes:
            # If we haven't hit TP by now, just exit. 
            # Especially if PnL is weak (< 5 pips) or negative.
            if unrealized_pnl_pips < 5.0:
                return ExitLevel(
                    price=current_price,
                    pnl_percent=unrealized_pnl_pips,
                    exit_type=ExitType.TIME_EXIT,
                    description=f"Max hold time ({self.max_hold_time_minutes}m) reached"
                )
        
        # 2. Smart Stagnation Cut (Optimization)
        # If trade is drifting negative for > 2 hours, cut it early.
        # Don't wait 8 hours to lose full SL.
        if hold_time_minutes > 120 and unrealized_pnl_pips < -2.0:
             return ExitLevel(
                price=current_price,
                pnl_percent=unrealized_pnl_pips,
                exit_type=ExitType.TIME_EXIT,
                description=f"Stagnation Exit: Drifting negative for {hold_time_minutes:.0f}m"
            )
        
        return None


def get_suggested_exit_levels(entry_price: float,
                             direction: Direction,
                             initial_stop_loss: float) -> Tuple[float, float, float]:
    """
    Calculate suggested exit levels based on entry and initial stop loss
    
    Returns:
        Tuple of (conservative_tp, balanced_tp, aggressive_tp)
    """
    pip_value = 0.01 if 'JPY' in str(direction) else 0.0001
    
    if direction == Direction.LONG:
        stop_loss_distance = (entry_price - initial_stop_loss) / pip_value
    else:  # SHORT
        stop_loss_distance = (initial_stop_loss - entry_price) / pip_value
    
    # Risk:Reward ratios
    conservative_rr = 1.0  # 1:1
    balanced_rr = 1.5      # 1:1.5
    aggressive_rr = 2.0    # 1:2
    
    tp_distance_conservative = stop_loss_distance * conservative_rr
    tp_distance_balanced = stop_loss_distance * balanced_rr
    tp_distance_aggressive = stop_loss_distance * aggressive_rr
    
    if direction == Direction.LONG:
        conservative_tp = entry_price + (tp_distance_conservative * pip_value)
        balanced_tp = entry_price + (tp_distance_balanced * pip_value)
        aggressive_tp = entry_price + (tp_distance_aggressive * pip_value)
    else:  # SHORT
        conservative_tp = entry_price - (tp_distance_conservative * pip_value)
        balanced_tp = entry_price - (tp_distance_balanced * pip_value)
        aggressive_tp = entry_price - (tp_distance_aggressive * pip_value)
    
    return conservative_tp, balanced_tp, aggressive_tp

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
        
        # Configuration - SMART MONEY APPROACH (Defaults / STANDARD)
        self.use_trailing_stop = True
        self.use_breakeven_stop = True
        self.use_time_based_exit = False  # DISABLED
        
        # Trailing stop: move stop loss up based on R-multiples
        self.trailing_stop_r_trigger = 1.0    # Trigger after 1.0R profit
        self.trailing_stop_r_trail = 0.5      # Trail by 0.5R distance
        
        # Breakeven: move stop to entry after 0.5R profit (Aggressive risk elimination)
        self.breakeven_trigger_r = 0.5        # Secure break even at 0.5R
        self.breakeven_offset_pips = 1        # Small offset to cover costs
        
        # Time-based exit (DISABLED)
        self.max_hold_time_minutes = 240      
        self.time_exit_loss_threshold_pips = -10 
        
        # Partial profit taking (DISABLED - Smart Money runs to full TP)
        self.partial_profit_levels = []
        
        # Secure profit threshold ($ value)
        self.secure_profit_threshold = 10.0   # Secure everything if up $10
        self.partial_profit_levels = []
        
    def _get_policy_parameters(self, policy: ExitPolicy) -> dict:
        """Get exit parameters for a specific policy"""
        params = {
            'use_trailing': True,
            'trail_trigger_r': self.trailing_stop_r_trigger,
            'trail_dist_r': self.trailing_stop_r_trail,
            'use_be': True,
            'be_trigger_r': self.breakeven_trigger_r,
            'partials': self.partial_profit_levels,
            'max_hold': self.max_hold_time_minutes
        }
        
        if policy == ExitPolicy.SCALP:
            # Scalp: Tight management, quick BE, quick partials
            params.update({
                'trail_trigger_r': 0.8,   # Start trailing early
                'trail_dist_r': 0.3,      # Tight trail
                'be_trigger_r': 0.4,      # Aggressive BE
                'partials': [(1.0, 0.5, "Scalp Partial 1R")], # Take 50% at 1R
                'max_hold': 60            # Don't hold scalps long
            })
            
        elif policy == ExitPolicy.TREND_FOLLOW:
            # Trend: Loose management, let it run
            params.update({
                'trail_trigger_r': 1.5,   # Late trail start
                'trail_dist_r': 1.0,      # Loose trail
                'be_trigger_r': 0.8,      # Standard BE
                'max_hold': 480           # Allow day-long hold
            })
            
        elif policy == ExitPolicy.MEAN_REVERT:
            # Mean Revert: Aim for target, standard management
            params.update({
                'trail_trigger_r': 1.2,
                'trail_dist_r': 0.5,
                'max_hold': 120
            })
            
        return params
    
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
                                 exit_policy: ExitPolicy = ExitPolicy.STANDARD) -> Tuple[Optional[ExitLevel], float]:
        """
        Evaluate all exit conditions based on Risk-Reward (R) units
        """
        pip_value = 0.01 if 'JPY' in symbol else 0.0001
        
        # Get parameters from policy
        params = self._get_policy_parameters(exit_policy)
        
        # Calculate Risk and current Profit in Pips and R-multiple
        risk_price = abs(entry_price - stop_loss) if stop_loss else (entry_price * 0.01)
        risk_pips = risk_price / pip_value
        
        if direction == Direction.LONG:
            profit_pips = (current_price - entry_price) / pip_value
            position_high_profit = (position_high - entry_price) / pip_value if position_high else profit_pips
        else:
            profit_pips = (entry_price - current_price) / pip_value
            position_high_profit = (entry_price - position_high) / pip_value if position_high else profit_pips
            
        current_R = profit_pips / risk_pips if risk_pips > 0 else 0
        high_R = position_high_profit / risk_pips if risk_pips > 0 else 0
        
        # 1. Secure Profit ($)
        if current_pnl >= self.secure_profit_threshold:
             return ExitLevel(
                price=current_price,
                pnl_percent=profit_pips,
                exit_type=ExitType.TAKE_PROFIT,
                exit_quantity_percent=1.0,
                description=f"Securing Profit: +${current_pnl:.2f}"
            ), profit_pips

        # List to track best exit
        exit_levels = []
        
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
        
        # 3. Trailing Stop (R-based via Policy)
        if params['use_trailing'] and high_R >= params['trail_trigger_r']:
            trail_distance = params['trail_dist_r'] * risk_pips * pip_value
            if direction == Direction.LONG:
                trailing_stop = position_high - trail_distance
                if current_price <= trailing_stop:
                    exit_levels.append(ExitLevel(current_price, profit_pips, ExitType.TRAILING_STOP, 1.0, f"Trailing Stop ({high_R:.1f}R high)"))
            else:
                trailing_stop = position_high + trail_distance
                if current_price >= trailing_stop:
                    exit_levels.append(ExitLevel(current_price, profit_pips, ExitType.TRAILING_STOP, 1.0, f"Trailing Stop ({high_R:.1f}R high)"))

        # 4. Breakeven Stop (R-based via Policy)
        if params['use_be'] and current_R >= params['be_trigger_r']:
            be_price = entry_price + (self.breakeven_offset_pips * pip_value) if direction == Direction.LONG else entry_price - (self.breakeven_offset_pips * pip_value)
            # If current price re-touches BE after trigger
            if (direction == Direction.LONG and current_price <= be_price) or (direction == Direction.SHORT and current_price >= be_price):
                 exit_levels.append(ExitLevel(be_price, profit_pips, ExitType.BREAKEVEN, 1.0, f"Breakeven after {current_R:.1f}R"))

        # 5. Partial Profits (R-based via Policy)
        for target_R, qty_pct, label in params['partials']:
            if current_R >= target_R:
                 exit_levels.append(ExitLevel(current_price, profit_pips, ExitType.PARTIAL_PROFIT, qty_pct, label))

        # 6. Time-based Exit
        if self.use_time_based_exit:
            now = datetime.now(timezone.utc)
            hold_time = (now - position_open_time).total_seconds() / 60
            if hold_time >= self.max_hold_time_minutes and current_R < 0.5:
                exit_levels.append(ExitLevel(current_price, profit_pips, ExitType.TIME_EXIT, 1.0, "Max hold time"))

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

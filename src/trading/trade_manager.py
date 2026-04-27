"""
Trade Management Layer
Separates ADMINISTRATIVE trade management from ML model intelligence.

Handles:
- Manual closes (TP/SL/discretionary)
- Trailing stops
- Equity locks (when to take profit)
- Time-based exits
- Exit reason tracking

This layer operates INDEPENDENTLY from the ML model and position sizing,
ensuring the model learns only from market behavior, not from exit decisions.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Tuple
from enum import Enum

from src.models import Position, Direction
from src.trading.exit_reason import ExitReason, ExitRecord, ExitLogger

# Phase 3: Exit Optimization
from src.exit.phase3_integration import Phase3ExitManager


@dataclass
class TradeManagementConfig:
    """Configuration for trade management behavior"""
    
    # Trailing Stop
    use_trailing_stop: bool = True
    trailing_stop_trigger_pips: float = 20  # Trigger every 20 pips profit
    trailing_stop_move_pips: float = 15     # Move stop loss by this amount
    
    # Equity Lock (Partial Profit Taking)
    use_equity_lock: bool = True
    equity_lock_levels: List[Tuple[float, float]] = None  # (profit_level, close_percent)
    # Default: Close 20% at 10 pips, 20% at 20 pips, 15% at 35 pips
    
    # Time-Based Exit
    use_time_exit: bool = True
    max_hold_time_minutes: int = 480  # Close unprofitable trades after 8 hours
    time_exit_loss_threshold_pips: float = -10  # Exit if loss exceeds -10 pips
    
    # Breakeven Stop
    use_breakeven_stop: bool = True
    breakeven_trigger_pips: float = 15  # Trigger after 15 pips profit
    breakeven_offset_pips: float = 2    # Place stop 2 pips above entry
    
    def __post_init__(self):
        """Set default equity lock levels if not provided"""
        if self.equity_lock_levels is None:
            self.equity_lock_levels = [
                (10, 0.20),   # Close 20% at 10 pips profit
                (20, 0.20),   # Close 20% at 20 pips profit
                (35, 0.15),   # Close 15% at 35 pips profit
            ]


class TradeManagementLayer:
    """
    Manages trade lifecycle AFTER entry.
    
    Responsibility: Execute administrative trade decisions without affecting
    the ML model's learning signal.
    
    The model only sees the trade entry. How/when it exits is managed here
    independently and logged with exit reasons.
    """
    
    def __init__(self, config: Optional[TradeManagementConfig] = None, 
                 logger: Optional[logging.Logger] = None):
        self.config = config or TradeManagementConfig()
        self.logger = logger or logging.getLogger(__name__)
        self.exit_logger = ExitLogger(logger)
        
        # Track partial closes to avoid re-closing already-closed portions
        self._partial_close_tracking: dict[str, float] = {}  # position_id -> qty_closed
        
        # Phase 3: Initialize Exit Optimization Manager
        self.phase3_manager = Phase3ExitManager(logger=self.logger)
    
    def check_manual_close(self, position: Position, 
                          manual_tp: Optional[float] = None,
                          manual_sl: Optional[float] = None) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if position should be manually closed.
        
        Manual closes are ADMINISTRATIVE decisions (not included in training).
        
        Args:
            position: The position to check
            manual_tp: Optional manual take-profit price
            manual_sl: Optional manual stop-loss price
        
        Returns:
            (should_close, exit_reason)
        """
        current_price = position.current_price
        
        # Check manual TP
        if manual_tp is not None:
            if position.direction == Direction.LONG and current_price >= manual_tp:
                self.logger.warning(
                    "[MANUAL CLOSE] %s | Reason: Manual TP @ %.5f | Current: %.5f",
                    position.symbol, manual_tp, current_price
                )
                return True, ExitReason.MANUAL_CLOSE_TP
            elif position.direction == Direction.SHORT and current_price <= manual_tp:
                self.logger.warning(
                    "[MANUAL CLOSE] %s | Reason: Manual TP @ %.5f | Current: %.5f",
                    position.symbol, manual_tp, current_price
                )
                return True, ExitReason.MANUAL_CLOSE_TP
        
        # Check manual SL
        if manual_sl is not None:
            if position.direction == Direction.LONG and current_price <= manual_sl:
                self.logger.warning(
                    "[MANUAL CLOSE] %s | Reason: Manual SL @ %.5f | Current: %.5f",
                    position.symbol, manual_sl, current_price
                )
                return True, ExitReason.MANUAL_CLOSE_SL
            elif position.direction == Direction.SHORT and current_price >= manual_sl:
                self.logger.warning(
                    "[MANUAL CLOSE] %s | Reason: Manual SL @ %.5f | Current: %.5f",
                    position.symbol, manual_sl, current_price
                )
                return True, ExitReason.MANUAL_CLOSE_SL
        
        return False, None
    
    def check_trailing_stop(self, position: Position, 
                           position_highest: Optional[float] = None,
                           position_lowest: Optional[float] = None) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if trailing stop should close the position.
        
        Trailing stops are ADMINISTRATIVE (exclude from training).
        
        Args:
            position: The position to check
            position_highest: Highest price reached for LONG positions
            position_lowest: Lowest price reached for SHORT positions
        
        Returns:
            (should_close, exit_reason)
        """
        if not self.config.use_trailing_stop:
            return False, None
        
        current_price = position.current_price
        
        if position.direction == Direction.LONG and position_highest:
            # For LONG: trigger when price drops by trigger_pips from highest
            trigger_price = position_highest - (self.config.trailing_stop_trigger_pips / 10000)
            if current_price <= trigger_price:
                self.logger.warning(
                    "[TRAILING STOP] %s | High: %.5f → Current: %.5f | "
                    "Dropped %.1f pips",
                    position.symbol, position_highest, current_price,
                    (position_highest - current_price) * 10000
                )
                return True, ExitReason.MANUAL_CLOSE_OTHER  # Admin-driven
        
        elif position.direction == Direction.SHORT and position_lowest:
            # For SHORT: trigger when price rises by trigger_pips from lowest
            trigger_price = position_lowest + (self.config.trailing_stop_trigger_pips / 10000)
            if current_price >= trigger_price:
                self.logger.warning(
                    "[TRAILING STOP] %s | Low: %.5f → Current: %.5f | "
                    "Risen %.1f pips",
                    position.symbol, position_lowest, current_price,
                    (current_price - position_lowest) * 10000
                )
                return True, ExitReason.MANUAL_CLOSE_OTHER  # Admin-driven
        
        return False, None
    
    def check_time_exit(self, position: Position) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if position should close due to time limit.
        
        Time-based exits are ADMINISTRATIVE (exclude from training).
        Only closes unprofitable trades after max hold time.
        
        Args:
            position: The position to check
        
        Returns:
            (should_close, exit_reason)
        """
        if not self.config.use_time_exit:
            return False, None
        
        if position.opened_at is None:
            return False, None
        
        hold_time = datetime.now(timezone.utc) - position.opened_at
        max_hold = timedelta(minutes=self.config.max_hold_time_minutes)
        
        if hold_time > max_hold:
            # Only close if losing money
            if position.unrealized_pnl < 0:
                pips_loss = abs(position.unrealized_pnl) / (position.quantity * 10)
                if pips_loss >= self.config.time_exit_loss_threshold_pips:
                    self.logger.warning(
                        "[TIME EXIT] %s | Held: %dm | Loss: %.1f pips | "
                        "Exceeds threshold: %.1f pips",
                        position.symbol,
                        hold_time.total_seconds() / 60,
                        pips_loss,
                        self.config.time_exit_loss_threshold_pips
                    )
                    return True, ExitReason.TIME_EXIT
        
        return False, None
    
    def check_equity_lock(self, position: Position) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if position should take partial profits based on equity lock levels.
        
        Equity locks are ADMINISTRATIVE (exclude from training).
        
        Args:
            position: The position to check
        
        Returns:
            (should_close_portion, exit_reason)
        """
        if not self.config.use_equity_lock:
            return False, None
        
        if position.unrealized_pnl <= 0:
            return False, None  # Only lock profits, not losses
        
        # Check each equity lock level
        for profit_level_pips, close_percent in self.config.equity_lock_levels:
            profit_level_price = profit_level_pips / 10000
            
            # Calculate how much profit needed to hit this level
            if position.direction == Direction.LONG:
                threshold_price = position.entry_price + profit_level_price
                if position.current_price >= threshold_price:
                    self.logger.info(
                        "[EQUITY LOCK] %s | Profit threshold: %.1f pips reached | "
                        "Close: %.0f%% of position",
                        position.symbol, profit_level_pips, close_percent * 100
                    )
                    return True, ExitReason.EQUITY_LOCK
            
            elif position.direction == Direction.SHORT:
                threshold_price = position.entry_price - profit_level_price
                if position.current_price <= threshold_price:
                    self.logger.info(
                        "[EQUITY LOCK] %s | Profit threshold: %.1f pips reached | "
                        "Close: %.0f%% of position",
                        position.symbol, profit_level_pips, close_percent * 100
                    )
                    return True, ExitReason.EQUITY_LOCK
        
        return False, None
    
    def check_breakeven_stop(self, position: Position) -> Tuple[bool, Optional[ExitReason]]:
        """
        Check if breakeven stop should trigger.
        
        Breakeven stops are ADMINISTRATIVE (exclude from training).
        
        Args:
            position: The position to check
        
        Returns:
            (should_close, exit_reason)
        """
        if not self.config.use_breakeven_stop:
            return False, None
        
        trigger_pips = self.config.breakeven_trigger_pips / 10000
        offset_pips = self.config.breakeven_offset_pips / 10000
        
        if position.direction == Direction.LONG:
            # Trigger when profit >= breakeven_trigger_pips
            if position.current_price >= position.entry_price + trigger_pips:
                # Would close if price drops to breakeven offset
                if position.current_price <= position.entry_price + offset_pips:
                    self.logger.warning(
                        "[BREAKEVEN STOP] %s | Entry: %.5f | Current: %.5f",
                        position.symbol, position.entry_price, position.current_price
                    )
                    return True, ExitReason.BREAKEVEN_STOP_HIT
        
        elif position.direction == Direction.SHORT:
            # Trigger when profit >= breakeven_trigger_pips
            if position.current_price <= position.entry_price - trigger_pips:
                # Would close if price rises to breakeven offset
                if position.current_price >= position.entry_price - offset_pips:
                    self.logger.warning(
                        "[BREAKEVEN STOP] %s | Entry: %.5f | Current: %.5f",
                        position.symbol, position.entry_price, position.current_price
                    )
                    return True, ExitReason.BREAKEVEN_STOP_HIT
        
        return False, None
    
    def record_exit(self, position: Position, exit_price: float, 
                   exit_reason: ExitReason,
                   was_manual: bool = False,
                   manual_user: Optional[str] = None,
                   notes: Optional[str] = None) -> ExitRecord:
        """
        Record a trade exit with full metadata for analysis and training filtering.
        
        Args:
            position: The closed position
            exit_price: Price at which it was closed
            exit_reason: Why it was closed
            was_manual: If true, this was a manual action
            manual_user: Who manually closed it
            notes: Additional context
        
        Returns:
            ExitRecord for database storage
        """
        exit_time = datetime.now(timezone.utc)
        hold_time = (exit_time - position.opened_at).total_seconds() if position.opened_at else 0
        
        # Calculate P&L
        pips = (exit_price - position.entry_price) * 10000
        if position.direction == Direction.SHORT:
            pips = -pips
        
        pnl = pips * position.quantity * 10  # Assuming 0.01 lot = 1 unit
        
        record = ExitRecord(
            position_id=position.position_id,
            symbol=position.symbol,
            entry_time=position.opened_at or exit_time,
            exit_time=exit_time,
            entry_price=position.entry_price,
            exit_price=exit_price,
            direction="LONG" if position.direction == Direction.LONG else "SHORT",
            quantity=position.quantity,
            reason=exit_reason,
            profit_loss=pnl,
            profit_loss_pips=pips,
            hold_time_seconds=int(hold_time),
            was_manual=was_manual,
            manual_user=manual_user,
            notes=notes,
            entry_features=position.entry_features,
            predicted_exit_policy=position.predicted_exit_policy.value if position.predicted_exit_policy else None,
            policy_confidence=position.policy_confidence,
            exit_policy=position.exit_policy.value if hasattr(position.exit_policy, 'value') else str(position.exit_policy)
        )
        
        self.exit_logger.log_exit(record)
        return record
    
    # ========================================================================
    # PHASE 3: Exit Optimization Integration
    # ========================================================================
    
    def check_phase3_exits(self, position: Position, symbol: str,
                          atr: float = 0.01,
                          volatility_regime: str = 'NORMAL_VOL',
                          trend_strength: float = 20.0,
                          buy_signal: bool = False,
                          sell_signal: bool = False) -> Tuple[bool, Optional[ExitReason], Optional[str]]:
        """
        Check Phase 3 exit conditions (multi-level, reversal, mode-adaptive).
        
        Args:
            position: Position to check
            symbol: Trading symbol
            atr: Current ATR value
            volatility_regime: Current volatility regime
            trend_strength: Current trend strength (ADX)
            buy_signal: Whether BUY signal is active
            sell_signal: Whether SELL signal is active
        
        Returns:
            (should_exit, exit_reason, notes)
        """
        if self.phase3_manager is None:
            return False, None, None
        
        signal = self.phase3_manager.check_all_exits(
            position=position,
            symbol=symbol,
            atr=atr,
            volatility_regime=volatility_regime,
            trend_strength=trend_strength,
            buy_signal=buy_signal,
            sell_signal=sell_signal,
        )
        
        # Convert Phase 3 signal to exit reason
        exit_reason = None
        notes = signal.reason
        
        if signal.exit_type == 'MULTI_LEVEL':
            exit_reason = ExitReason.PROFIT_TARGET  # Treat as TP hit
            if signal.exit_percentage and signal.exit_percentage < 100:
                notes = f"[MULTI_LEVEL] {signal.reason} | Exit: {signal.exit_percentage}%"
        
        elif signal.exit_type == 'REVERSAL':
            exit_reason = ExitReason.REVERSAL_DETECTED
            notes = f"[REVERSAL] {signal.reason}"
        
        elif signal.exit_type == 'MODE_ADAPTIVE':
            # Update targets instead of exiting
            if signal.new_tp and signal.new_sl:
                self.logger.info(
                    "[PHASE3] Updated targets for %s | New TP: %.5f | New SL: %.5f",
                    position.symbol, signal.new_tp, signal.new_sl
                )
            return False, None, None
        
        if signal.should_exit and exit_reason:
            self.logger.warning(
                "[PHASE3] Exit triggered: %s | Reason: %s",
                position.symbol, notes
            )
            return True, exit_reason, notes
        
        return False, None, None
    
    def update_phase3_data(self, symbol: str, ohlc: dict, rsi: float = 0.0, momentum: float = 0.0):
        """
        Update Phase 3 manager with market data.
        
        Args:
            symbol: Trading symbol
            ohlc: Dictionary with 'open', 'high', 'low', 'close'
            rsi: Current RSI value
            momentum: Current momentum value
        """
        if self.phase3_manager:
            self.phase3_manager.update_candle_history(symbol, ohlc)
            if rsi > 0:
                self.phase3_manager.update_rsi_history(symbol, rsi)
            if momentum != 0:
                self.phase3_manager.momentum_history[symbol] = self.phase3_manager.momentum_history.get(symbol, []) + [momentum]
    
    def get_phase3_summary(self) -> dict:
        """Get Phase 3 status summary"""
        if self.phase3_manager:
            return self.phase3_manager.get_summary()
        return {}
    
    def get_exit_summary(self) -> dict:
        """Get summary of all exits for performance analysis"""
        return self.exit_logger.get_summary()

"""
Risk Governor Layer
Independent risk control that can OVERRIDE all other trading logic.

Monitors and enforces:
- Daily profit/loss limits
- Drawdown limits
- Equity targets
- Position limits
- Margin safety

The risk governor operates at the SYSTEM level, not the signal level.
It can halt trading or force-close positions regardless of model signals.
All risk governor exits are logged as administrative (excluded from training).
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date, timezone, timedelta
from typing import Optional, List, Tuple
from enum import Enum

from src.models import Portfolio, Position
from src.trading.exit_reason import ExitReason, ExitRecord, ExitLogger


class RiskGovernorState(Enum):
    """State of the risk governor"""
    OPERATIONAL = "operational"  # Normal trading allowed
    WARNING = "warning"          # Close position but don't open new ones
    HALTED = "halted"           # No new positions, only closing existing


@dataclass
class RiskGovernorConfig:
    """Configuration for risk governor behavior"""
    
    # Daily P&L Limits (Percentage of Account Equity)
    max_daily_loss_percent: float = 2.0     # Stop trading if daily loss exceeds 2% of equity
    max_daily_profit_percent: float = 5.0   # Close all positions if daily profit reaches 5% of equity
    max_daily_trades: int = 15              # Max trades per day
    
    # Drawdown Limits
    max_drawdown_percent: float = 15.0      # Stop if drawdown exceeds 15% of equity
    release_drawdown_percent: float = 0.5   # Resume trading when drawdown drops below 0.5%
    
    # Equity Limits
    min_equity_buffer: float = 100.0        # Keep $100 equity buffer before halting
    equity_target_percent: float = 5.0      # When profit reaches 5% of equity, close positions
    
    # Position Limits
    max_concurrent_positions: int = 3       # Never open more than 3 positions
    max_positions_per_symbol: int = 1       # Max 1 position per symbol
    
    # Margin Safety
    min_margin_percent: float = 20.0        # Minimum 20% margin available
    min_margin_absolute: float = 100.0      # Absolute minimum $100 margin
    
    # Recovery Behavior
    cooldown_minutes_after_halt: int = 60   # Wait 1 hour before resuming after halt
    

class RiskGovernor:
    """
    Independent risk control system that operates above the strategy layer.
    
    Can:
    - Halt all new trades
    - Force-close positions
    - Override position limits
    - Enforce equity targets
    - Track all risk-driven exits
    
    All exits triggered by the risk governor are marked as administrative
    and excluded from ML training.
    """
    
    def __init__(self, config: Optional[RiskGovernorConfig] = None,
                 logger: Optional[logging.Logger] = None):
        self.config = config or RiskGovernorConfig()
        self.logger = logger or logging.getLogger(__name__)
        self.exit_logger = ExitLogger(logger)
        
        self.state = RiskGovernorState.OPERATIONAL
        self.state_changed_at = datetime.now(timezone.utc)
        
        # Track daily metrics
        self.daily_start_equity: Optional[float] = None
        self.daily_start_time: Optional[datetime] = None
        self.daily_trades_count = 0
        self.daily_closed_pnl = 0.0  # Realized P&L today
        
        self._reset_daily_metrics()
    
    def _reset_daily_metrics(self) -> None:
        """Reset daily metrics at market start"""
        self.daily_start_time = datetime.now(timezone.utc)
        self.daily_start_date = datetime.now(timezone.utc).date()
        self.daily_trades_count = 0
        self.daily_closed_pnl = 0.0
        self.daily_positions_opened: dict[str, datetime] = {}  # symbol -> first open time
    
    def _check_new_day(self) -> bool:
        """Check if we've crossed into a new trading day"""
        now = datetime.now(timezone.utc).date()
        if not hasattr(self, 'daily_start_date') or now > self.daily_start_date:
            self._reset_daily_metrics()
            self.logger.info("[RISK GOVERNOR] New trading day - resetting daily limits")
            return True
        return False
    
    def check_trading_allowed(self, portfolio: Portfolio) -> Tuple[bool, Optional[str]]:
        """
        Check if new trades are allowed given current risk status.
        
        Args:
            portfolio: Current portfolio state
        
        Returns:
            (trades_allowed, halt_reason)
        """
        self._check_new_day()
        
        # Check if we can recover from HALTED/WARNING state
        if self.state != RiskGovernorState.OPERATIONAL:
            if not self.check_recovery_conditions(portfolio):
                return False, f"Trading {self.state.value.upper()} by Risk Governor (Recovery Pending)"
        
        # Check daily loss limit (Dynamic % based)
        unrealized_pnl = sum(p.unrealized_pnl for p in portfolio.positions)
        daily_pnl = unrealized_pnl + self.daily_closed_pnl

        # Calculate dynamic dollar thresholds based on equity
        max_loss_dollar = portfolio.equity * (self.config.max_daily_loss_percent / 100.0)
        max_profit_dollar = portfolio.equity * (self.config.max_daily_profit_percent / 100.0)

        if daily_pnl < -max_loss_dollar:
            reason = (f"Daily loss limit exceeded: ${daily_pnl:.2f} "
                     f"({self.config.max_daily_loss_percent}% limit: ${-max_loss_dollar:.2f})")
            self._halt_trading(reason, RiskGovernorState.WARNING)
            return False, reason
        
        # Check daily profit target (Dynamic % based)
        if daily_pnl > max_profit_dollar:
            reason = (f"Daily profit target reached: ${daily_pnl:.2f} "
                     f"({self.config.max_daily_profit_percent}% target: ${max_profit_dollar:.2f})")
            self._halt_trading(reason, RiskGovernorState.WARNING)
            return False, reason
        
        # Check daily trade count (0 means unlimited)
        if self.config.max_daily_trades > 0 and self.daily_trades_count >= self.config.max_daily_trades:
            reason = f"Daily trade limit reached: {self.daily_trades_count}/{self.config.max_daily_trades}"
            return False, reason
        
        # Check drawdown
        if self.daily_start_equity:
            drawdown = (self.daily_start_equity - portfolio.equity) / self.daily_start_equity * 100
            if drawdown > self.config.max_drawdown_percent:
                reason = (f"Drawdown limit exceeded: {drawdown:.1f}% "
                         f"(limit: {self.config.max_drawdown_percent:.1f}%)")
                self._halt_trading(reason, RiskGovernorState.WARNING)
                return False, reason
        
        # Check equity buffer
        if portfolio.equity < self.config.min_equity_buffer:
            reason = f"Equity too low: ${portfolio.equity:.2f} (min: ${self.config.min_equity_buffer:.2f})"
            self._halt_trading(reason, RiskGovernorState.HALTED)
            return False, reason
        
        # Check margin
        margin_percent = (portfolio.margin_available / portfolio.equity * 100) if portfolio.equity > 0 else 0
        if margin_percent < self.config.min_margin_percent:
            reason = (f"Margin below minimum: {margin_percent:.1f}% "
                     f"(min: {self.config.min_margin_percent:.1f}%)")
            return False, reason
        
        if portfolio.margin_available < self.config.min_margin_absolute:
            reason = (f"Margin critically low: ${portfolio.margin_available:.2f} "
                     f"(min: ${self.config.min_margin_absolute:.2f})")
            return False, reason
        
        # Check position count
        if len(portfolio.positions) >= self.config.max_concurrent_positions:
            reason = (f"Position limit reached: {len(portfolio.positions)}/"
                     f"{self.config.max_concurrent_positions}")
            return False, reason
        
        return True, None
    
    def check_emergency_close(self, portfolio: Portfolio) -> Tuple[bool, Optional[str]]:
        """
        Check if positions should be emergency-closed due to critical risk conditions.
        
        Args:
            portfolio: Current portfolio state
        
        Returns:
            (should_force_close, reason)
        """
        # Check critical equity loss
        if self.daily_start_equity:
            drawdown = (self.daily_start_equity - portfolio.equity) / self.daily_start_equity * 100
            if drawdown > self.config.max_drawdown_percent * 1.5:  # 1.5x the normal limit
                return True, f"CRITICAL DRAWDOWN: {drawdown:.1f}%"
        
        # Check margin emergency
        if portfolio.margin_available < self.config.min_margin_absolute * 0.5:
            return True, f"CRITICAL MARGIN: ${portfolio.margin_available:.2f}"
        
        # Check equity emergency
        if portfolio.equity < self.config.min_equity_buffer * 0.5:
            return True, f"CRITICAL EQUITY: ${portfolio.equity:.2f}"
        
        return False, None
    
    def register_trade_opened(self, symbol: str) -> None:
        """Register that a new trade was opened"""
        self.daily_trades_count += 1
        if symbol not in self.daily_positions_opened:
            self.daily_positions_opened[symbol] = datetime.now(timezone.utc)
    
    def register_trade_closed(self, pnl: float) -> None:
        """Register that a trade was closed with realized P&L"""
        self.daily_closed_pnl += pnl
    
    def get_forced_close_positions(self, portfolio: Portfolio, 
                                   reason: str) -> List[Position]:
        """
        Determine which positions to force-close based on risk governor rules.
        
        Strategy:
        1. Close oldest losing positions first (least pain)
        2. Then close oldest winning positions (lock in profits)
        
        Args:
            portfolio: Current portfolio
            reason: Why we're force-closing
        
        Returns:
            List of positions to close
        """
        if not portfolio.positions:
            return []
        
        # Separate into winning and losing
        losers = [p for p in portfolio.positions if p.unrealized_pnl < 0]
        winners = [p for p in portfolio.positions if p.unrealized_pnl >= 0]
        
        # Sort by opened_at (oldest first)
        losers.sort(key=lambda p: p.opened_at or datetime.now(timezone.utc))
        winners.sort(key=lambda p: p.opened_at or datetime.now(timezone.utc))
        
        # Prefer closing losers, but include winners if needed
        to_close = []
        
        # Close all losers if we have them
        if losers:
            to_close.extend(losers)
            self.logger.warning(
                "[RISK GOVERNOR FORCE CLOSE] Closing %d losing positions: %s",
                len(losers),
                reason
            )
        
        # If we need to close more, add winners
        if len(to_close) < len(portfolio.positions):
            num_winners_to_close = len(portfolio.positions) - len(to_close)
            to_close.extend(winners[:num_winners_to_close])
            if num_winners_to_close > 0:
                self.logger.critical(
                    "[RISK GOVERNOR FORCE CLOSE] Also closing %d winning positions: %s",
                    num_winners_to_close,
                    reason
                )
        
        return to_close
    
    def _halt_trading(self, reason: str, new_state: RiskGovernorState) -> None:
        """Transition to a halted state"""
        if self.state != new_state:
            self.state = new_state
            self.state_changed_at = datetime.now(timezone.utc)
            emoji = "🛑" if new_state == RiskGovernorState.HALTED else "⚠️"
            self.logger.critical(
                "%s [RISK GOVERNOR] Trading %s | Reason: %s",
                emoji, new_state.value.upper(), reason
            )
    
    def check_recovery_conditions(self, portfolio: Portfolio) -> bool:
        """Check if trading can resume after a halt"""
        if self.state == RiskGovernorState.OPERATIONAL:
            return True
        
        # Check if cooldown period has passed
        time_since_halt = datetime.now(timezone.utc) - self.state_changed_at
        if time_since_halt < timedelta(minutes=self.config.cooldown_minutes_after_halt):
            return False
        
        # Check drawdown recovery (Percentage-based release threshold)
        if self.daily_start_equity:
            current_drawdown = (self.daily_start_equity - portfolio.equity) / self.daily_start_equity * 100
            if current_drawdown > self.config.release_drawdown_percent:
                self.logger.debug(
                    "[RISK GOVERNOR] Recovery pending. Current drawdown %.2f%% > Release threshold %.2f%%",
                    current_drawdown, self.config.release_drawdown_percent
                )
                return False

        # Could add additional recovery conditions here
        self.state = RiskGovernorState.OPERATIONAL
        self.logger.info("[RISK GOVERNOR] Trading resumed after cooldown and drawdown recovery")
        return True
    
    def get_status(self) -> dict:
        """Get current risk governor status"""
        return {
            'state': self.state.value,
            'daily_trades': self.daily_trades_count,
            'daily_limit': self.config.max_daily_trades,
            'daily_pnl': self.daily_closed_pnl,
            'time_in_current_state': (
                datetime.now(timezone.utc) - self.state_changed_at
            ).total_seconds(),
        }

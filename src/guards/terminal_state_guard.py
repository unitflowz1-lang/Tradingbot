"""
Terminal State Guard - Prevents trading loop errors when AlgoTrading is disabled
Handles TERMINAL_TRADE_ALLOWED checks and Emergency Idle state management
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Tuple, Any
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)

# Global state for terminal trading suspension
class TerminalStateGuard:
    """Manages terminal trading state and prevents infinite loops on Error 10027"""
    
    def __init__(self):
        self.suspend_trading_until: Optional[datetime] = None
        self.emergency_idle_mode: bool = False
        self.emergency_idle_until: Optional[datetime] = None
        self.last_algo_trading_check: Optional[datetime] = None
        self.algo_trading_disabled_at: Optional[datetime] = None
        self.error_10027_count: int = 0
        self.error_10027_first_seen: Optional[datetime] = None
        self.system_paused_logged: bool = False
        
    def check_terminal_trade_allowed(self) -> Tuple[bool, str]:
        """
        Check if TERMINAL_TRADE_ALLOWED is True
        Returns (allowed: bool, reason: str)
        """
        try:
            # FIX #1: Use correct MT5 API - terminal_info() instead of terminal_info_integer()
            terminal_info = mt5.terminal_info()
            trade_allowed = terminal_info.trade_allowed if terminal_info is not None else False
            self.last_algo_trading_check = datetime.now(timezone.utc)
            
            if not trade_allowed:
                if self.algo_trading_disabled_at is None:
                    self.algo_trading_disabled_at = datetime.now(timezone.utc)
                return False, "AlgoTrading disabled in Terminal GUI"
            else:
                # AlgoTrading re-enabled - clear the suspension
                self.algo_trading_disabled_at = None
                return True, "AlgoTrading enabled"
                
        except Exception as e:
            logger.error(f"[TERMINAL_STATE_GUARD] Error checking TERMINAL_TRADE_ALLOWED: {e}")
            return False, f"Error checking terminal state: {str(e)[:100]}"
    
    def is_trading_suspended(self) -> bool:
        """Check if trading is currently suspended"""
        if self.suspend_trading_until and datetime.now(timezone.utc) < self.suspend_trading_until:
            return True
        if self.suspend_trading_until and datetime.now(timezone.utc) >= self.suspend_trading_until:
            self.suspend_trading_until = None  # Clear expired suspension
        return False
    
    def is_emergency_idle_active(self) -> bool:
        """Check if emergency idle mode is active"""
        if self.emergency_idle_until and datetime.now(timezone.utc) < self.emergency_idle_until:
            return True
        if self.emergency_idle_until and datetime.now(timezone.utc) >= self.emergency_idle_until:
            self.emergency_idle_mode = False
            self.emergency_idle_until = None  # Clear expired emergency idle
        return self.emergency_idle_mode
    
    def suspend_trading(self, duration_seconds: int, reason: str) -> None:
        """
        Suspend trading for the specified duration
        Args:
            duration_seconds: How long to suspend trading (e.g., 300 for 5 minutes)
            reason: Description of why trading is suspended
        """
        self.suspend_trading_until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        logger.critical(
            f"[SUSPEND_TRADING] Trading suspended for {duration_seconds}s until "
            f"{self.suspend_trading_until.isoformat()} | Reason: {reason}"
        )
    
    def trigger_emergency_idle(self, duration_seconds: int, reason: str) -> None:
        """
        Trigger emergency idle mode (no trading, sleep cycles)
        Args:
            duration_seconds: How long to idle (e.g., 1800 for 30 minutes)
            reason: Description of the emergency
        """
        self.emergency_idle_mode = True
        self.emergency_idle_until = datetime.now(timezone.utc) + timedelta(seconds=duration_seconds)
        logger.critical(
            f"[EMERGENCY_IDLE] Emergency idle triggered for {duration_seconds}s until "
            f"{self.emergency_idle_until.isoformat()} | Reason: {reason}"
        )
    
    def record_error_10027(self) -> None:
        """Record an Error 10027 occurrence for tracking"""
        self.error_10027_count += 1
        if self.error_10027_first_seen is None:
            self.error_10027_first_seen = datetime.now(timezone.utc)
        
        # If we see 5+ Error 10027s in 30 seconds, enter emergency idle
        if self.error_10027_first_seen:
            time_since_first = (datetime.now(timezone.utc) - self.error_10027_first_seen).total_seconds()
            if time_since_first < 30 and self.error_10027_count >= 5:
                logger.critical(
                    f"[ERROR_10027_DETECTION] {self.error_10027_count} errors in {time_since_first:.1f}s. "
                    "Entering emergency idle mode."
                )
                self.trigger_emergency_idle(duration_seconds=1800, reason="Rapid Error 10027 burst detected")
            elif time_since_first >= 30:
                # Reset counter after 30 seconds of no errors
                self.error_10027_first_seen = None
                self.error_10027_count = 0
    
    def reset_error_tracking(self) -> None:
        """Reset error tracking counters"""
        self.error_10027_count = 0
        self.error_10027_first_seen = None


# Global instance
_terminal_state_guard: Optional[TerminalStateGuard] = None


def get_terminal_state_guard() -> TerminalStateGuard:
    """Get or create the singleton terminal state guard"""
    global _terminal_state_guard
    if _terminal_state_guard is None:
        _terminal_state_guard = TerminalStateGuard()
    return _terminal_state_guard


async def execute_terminal_state_guard() -> None:
    """
    Main Guard Logic: Check if AlgoTrading is disabled
    If disabled, log once and sleep for 30 seconds
    This should be called at the beginning of each main loop iteration
    """
    guard = get_terminal_state_guard()
    
    # Check if we're in emergency idle mode
    if guard.is_emergency_idle_active():
        logger.critical(
            "[TERMINAL_STATE_GUARD] Emergency Idle Mode Active. "
            f"Will resume trading at {guard.emergency_idle_until.isoformat()}"
        )
        await asyncio.sleep(15)  # Sleep 15s between emergency idle checks
        return
    
    # Check if trading is suspended (e.g., after failed SMALL_WIN_RESET)
    if guard.is_trading_suspended():
        remaining = (guard.suspend_trading_until - datetime.now(timezone.utc)).total_seconds()
        logger.warning(
            f"[TERMINAL_STATE_GUARD] Trading Suspended. "
            f"Will resume in {remaining:.0f}s at {guard.suspend_trading_until.isoformat()}"
        )
        await asyncio.sleep(10)  # Sleep 10s between suspension checks
        return
    
    # Check TERMINAL_TRADE_ALLOWED
    trade_allowed, reason = guard.check_terminal_trade_allowed()
    
    if not trade_allowed:
        if not guard.system_paused_logged:
            logger.critical(
                "[SYSTEM_PAUSED] AlgoTrading Disabled. The 'Algorithmic Trading' button is OFF in MT5 Terminal. "
                f"Reason: {reason} | Bot will check every 30 seconds for re-enablement."
            )
            guard.system_paused_logged = True
        
        # Sleep and check again
        await asyncio.sleep(30)
        return
    else:
        # AlgoTrading is enabled - clear the paused flag
        if guard.system_paused_logged:
            logger.critical(
                "[SYSTEM_RESUMED] AlgoTrading Re-enabled. Bot resuming normal trading operations."
            )
            guard.system_paused_logged = False


async def handle_error_10027(symbol: str, context: str = "") -> None:
    """
    Global Error 10027 handler
    Triggers emergency idle state and prevents infinite loops
    
    Args:
        symbol: The symbol being traded when the error occurred
        context: Additional context about where the error occurred
    """
    guard = get_terminal_state_guard()
    guard.record_error_10027()
    
    logger.critical(
        f"[ERROR_10027_HANDLER] AutoTrading Disabled for {symbol} | Context: {context} | "
        f"Total occurrences: {guard.error_10027_count}"
    )
    
    # If not already in emergency idle, suspend trading for 5 minutes
    if not guard.is_emergency_idle_active() and not guard.is_trading_suspended():
        logger.critical(
            "[ERROR_10027_HANDLER] Suspending all trading for 5 minutes to allow Terminal recovery."
        )
        guard.suspend_trading(
            duration_seconds=300,
            reason=f"Error 10027 detected on {symbol} | {context}"
        )


def check_symbol_trade_stops_level(symbol: str, current_sl: float, new_sl: float, position_type: Optional[str] = None) -> Tuple[bool, str]:
    """
    Check if Stop Loss modification respects SYMBOL_TRADE_STOPS_LEVEL
    Provides detailed diagnostic logging of the math when a modification is blocked
    
    Args:
        symbol: The trading symbol (e.g., 'EURUSD')
        current_sl: Current Stop Loss price
        new_sl: Proposed new Stop Loss price
        position_type: Optional position type ('BUY' or 'SELL') for better diagnostics
    
    Returns:
        (valid: bool, reason: str) - validation result with detailed message
    """
    try:
        symbol_info = mt5.symbol_info(symbol)
        if not symbol_info:
            logger.warning(f"[STOP_LOSS_VALIDATION] Symbol not found: {symbol}")
            return False, f"Symbol not found: {symbol}"
        
        # SYMBOL_TRADE_STOPS_LEVEL is the minimum distance in pips from current price
        min_stops_level_pips = symbol_info.trade_stops_level
        point = symbol_info.point
        min_distance_price = min_stops_level_pips * point
        
        # Get current market prices
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            logger.warning(f"[STOP_LOSS_VALIDATION] Cannot get tick for {symbol}")
            return False, f"Cannot get tick for {symbol}"
        
        current_bid = tick.bid
        current_ask = tick.ask
        current_price = current_bid if current_bid > 0 else current_ask
        
        # Calculate distance from current price to proposed SL
        distance_from_price = abs(current_price - new_sl)
        
        # Calculate in pips for easier reading
        distance_pips = distance_from_price / point if point > 0 else 0
        
        # Check if new SL is closer than minimum allowed
        if distance_from_price < min_distance_price:
            # Build detailed diagnostic message
            diagnostic_msg = (
                f"[STOP_LOSS_VALIDATION] {symbol} | SL MODIFICATION BLOCKED\n"
                f"  ├─ Current Market Prices:\n"
                f"  │  ├─ Bid: {current_bid:.5f}\n"
                f"  │  └─ Ask: {current_ask:.5f}\n"
                f"  ├─ Proposed SL: {new_sl:.5f}\n"
                f"  ├─ Current SL: {current_sl:.5f}\n"
                f"  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: {min_stops_level_pips} pips = {min_distance_price:.6f} price\n"
                f"  ├─ Actual distance (Price → Proposed SL): {distance_from_price:.6f} ({distance_pips:.1f} pips)\n"
                f"  ├─ REQUIRED distance: {min_distance_price:.6f} ({min_stops_level_pips} pips)\n"
                f"  └─ SHORTFALL: Need {(min_distance_price - distance_from_price):.6f} more pips ({(min_distance_price - distance_from_price)/point:.1f} pips)\n"
            )
            
            logger.warning(diagnostic_msg)
            
            reason = (
                f"SL too close to price. "
                f"Current: {current_price:.5f}, Proposed SL: {new_sl:.5f}, "
                f"Distance: {distance_pips:.1f} pips (need {min_stops_level_pips} pips). "
                f"Shortfall: {(min_distance_price - distance_from_price)/point:.1f} pips"
            )
            return False, reason
        
        # SL modification is valid
        valid_msg = (
            f"[STOP_LOSS_VALIDATION] {symbol} | SL MODIFICATION VALID\n"
            f"  ├─ Current Market Prices:\n"
            f"  │  ├─ Bid: {current_bid:.5f}\n"
            f"  │  └─ Ask: {current_ask:.5f}\n"
            f"  ├─ Proposed SL: {new_sl:.5f}\n"
            f"  ├─ Current SL: {current_sl:.5f}\n"
            f"  ├─ Broker SYMBOL_TRADE_STOPS_LEVEL: {min_stops_level_pips} pips = {min_distance_price:.6f} price\n"
            f"  ├─ Actual distance (Price → Proposed SL): {distance_from_price:.6f} ({distance_pips:.1f} pips)\n"
            f"  └─ Status: ✓ PASS ({distance_pips:.1f} >= {min_stops_level_pips} required)\n"
        )
        
        logger.debug(valid_msg)
        
        reason = f"SL modification valid. Distance: {distance_pips:.1f} pips >= {min_stops_level_pips} pips required"
        return True, reason
        
    except Exception as e:
        logger.error(f"[STOP_LOSS_VALIDATION] Exception checking SYMBOL_TRADE_STOPS_LEVEL for {symbol}: {e}")
        return False, f"Validation error: {str(e)[:100]}"

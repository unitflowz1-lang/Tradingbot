"""
Dynamic Trailing Stop Loss Manager
===================================

Implements intelligent trailing stop loss that:
1. Only moves SL in the direction of profit (locks gains)
2. Never tightens SL below entry price (except for scalp modes)
3. Includes MT5 spam protection (no ERR_TRADE_TOO_MANY_REQUESTS)
4. Tracks modification history for analysis
5. Respects broker freeze zones and minimum distances

PROBLEM SOLVED:
- Positions oscillating ±1.00 to ±3.00 without profit protection
- Without trailing SL: Leave profit on the table
- With trailing SL: Lock $2+ profit to break-even, escape before reversal

SPAM PROTECTION:
- Minimum price movement threshold (X pips before modification)
- Minimum time threshold (Y seconds between modifications)
- Prevents "ERR_TRADE_TOO_MANY_REQUESTS" from broker throttling
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Configuration Constants
# ============================================================================

# Minimum time between modifications (seconds)
MIN_TIME_BETWEEN_MODIFICATIONS = 5.0

# Minimum pip movement before SL update (prevents spam)
# INSTITUTIONAL REQUIREMENT: High-Sensitivity Ratchet (2 pips)
# The SL should follow the price like a shadow, updating whenever price moves 2 pips.
# This ensures aggressive profit protection without broker throttling.
# Adjust based on your broker and symbol:
# - Forex (5 decimal): 2 pips = 0.00020 (INSTITUTIONAL: SL follows price like shadow)
# - Forex (3 decimal): 2 pips = 0.002
# - Crypto: 2 pips = 2 (or adjust to your scale)
MIN_PIP_MOVEMENT_FOR_MODIFICATION = {
    "default": 0.00020,  # 2 pips for 5-decimal pairs (INSTITUTIONAL: hyper-responsive)
    "crypto": 0.01,    # 2 pips for 3-decimal
    "index": 0.1,      # 2 pips for indices
}

# Default trailing buffer (in pips from current price)
DEFAULT_TRAILING_BUFFER_PIPS = 5  # 5 pips from current price

# Profit lock thresholds
PROFIT_LOCK_THRESHOLD_PIPS = 20  # Lock SL to break-even after +20 pips
PROFIT_LOCK_MODE = True  # Enable automatic profit locking


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class PositionTrailingState:
    """Tracks trailing SL state for a position."""
    ticket: str
    symbol: str
    side: str  # "LONG" or "SHORT"
    entry_price: float
    current_sl: float
    tp_price: float = 0.0  # Take Profit price (for Endzone 90% detection)

    # Broker fees for true breakeven calculation
    commission: float = 0.0  # Broker commission on trade
    swap: float = 0.0  # Swap/overnight fees accumulated

    # Tracking
    last_sl_modification_time: datetime = field(default_factory=datetime.now)
    last_sl_modification_price: float = 0.0
    last_fee_update_time: datetime = field(default_factory=datetime.now)  # For 5-minute fee update interval
    highest_price_long: float = 0.0  # For LONG positions
    lowest_price_short: float = float('inf')  # For SHORT positions
    
    # ATR for volatility-based buffer
    atr_value: float = 0.0  # Current ATR for volatility-adaptive SL buffer

    # Statistics
    total_modifications: int = 0
    profit_locked_at_price: Optional[float] = None
    times_sl_moved: int = 0
    is_running_as_runner: bool = False
    endzone_activated: bool = False  # Track if 90% Endzone was triggered
    
    # Virtual TP tracking (NEW)
    is_virtual_tp: bool = False  # Track if TP was assigned by bot
    virtual_tp_assigned_at: Optional[datetime] = None  # When virtual TP was assigned
    
    # DPC Tiered Profit Sniper tracking (NEW)
    dpc_tier_1_hit: bool = False  # 40% to TP: Entry + Fees (breakeven)
    dpc_tier_2_hit: bool = False  # 65% to TP: Entry + 40% profit
    dpc_tier_3_hit: bool = False  # 85% to TP: Entry + 75% profit
    
    # Hard Dollar Profit Locking System (Institutional Lockdown)
    hard_dollar_2_lock_hit: bool = False   # $2.00 Lock: Entry + Fees + 1 point (No-Loss Floor)
    hard_dollar_4_lock_hit: bool = False   # $4.00: Lock $1.50 (Institutional aggressive)
    hard_dollar_7_5_lock_hit: bool = False  # $7.50: Lock $4.00 (Institutional maximum)
    
    # Tiered Cash Protection ($5/$10/$15)
    tiered_cash_5_hit: bool = False    # $5.00 profit threshold
    tiered_cash_10_hit: bool = False   # $10.00 profit threshold
    tiered_cash_15_hit: bool = False   # $15.00 profit threshold
    
    # Hard Floor Activation (Capital Guardian)
    hard_floor_activated: bool = False  # $2.00+ profit: Entry + Fees + 1 point (No-Loss Floor)
    
    # Hyper-Aggressive 90% Sniper
    hyper_aggressive_90_hit: bool = False  # 90% to TP: Lock 90% of profit (finish line strangulation)
    
    # Legacy milestone/circuit-breaker tracking (deprecated)
    milestone_50_hit: bool = False  # 50% to TP: Entry + Fees + 1 pip (100% safe)
    milestone_80_hit: bool = False  # 80% to TP: Lock 65% of profit
    milestone_90_hit: bool = False  # 90% to TP: Lock 85% of profit (Sniper Zone)
    hard_dollar_2_50_hit: bool = False  # $2.50 threshold
    hard_dollar_5_hit: bool = False    # $5.00 threshold
    hard_dollar_10_hit: bool = False   # $10.00 threshold
    hard_dollar_3_hit: bool = False  # $3.00 profit threshold
    hard_dollar_6_hit: bool = False  # $6.00 profit threshold

    # History
    modification_history: List[Dict] = field(default_factory=list)


@dataclass
class TrailingConfig:
    """Configuration for trailing SL behavior."""
    buffer_pips: float = DEFAULT_TRAILING_BUFFER_PIPS
    min_time_between_mods_seconds: float = MIN_TIME_BETWEEN_MODIFICATIONS
    min_pip_movement: float = MIN_PIP_MOVEMENT_FOR_MODIFICATION["default"]
    enable_profit_lock: bool = PROFIT_LOCK_MODE
    profit_lock_threshold_pips: float = PROFIT_LOCK_THRESHOLD_PIPS
    enable_hard_dollar_locks: bool = False

    # Scalp mode: tighter trailing
    scalp_mode: bool = False
    scalp_buffer_pips: float = 2.0


# ============================================================================
# Dynamic Trailing Stop Loss Manager
# ============================================================================

class DynamicTrailingSLManager:
    """
    Intelligent trailing stop loss management.

    Features:
    - Trails SL in direction of profit only
    - Locks profit to break-even or slightly positive
    - MT5 spam protection (throttles modifications)
    - Tracks modification history
    - Respects broker freeze zones

    Usage:
        manager = DynamicTrailingSLManager(broker, config)

        # Track a position
        manager.track_position(
            ticket="12345",
            symbol="EURUSD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )

        # Periodically update
        await manager.update_trailing_sl(
            ticket="12345",
            current_price=1.0875,
        )
    """

    def __init__(
        self,
        broker,
        config: Optional[TrailingConfig] = None,
    ):
        """
        Initialize trailing SL manager.

        Args:
            broker: MT5 broker instance (with modify_order method)
            config: TrailingConfig for behavior tuning
        """
        self.broker = broker
        self.config = config or TrailingConfig()

        # Track all positions
        self._positions: Dict[str, PositionTrailingState] = {}
        self._lock = asyncio.Lock()
        self._autotrading_disabled_logged = False  # Track if we've logged AutoTrading disabled once

        logger.info(
            "[TRAILING_SL_INIT] Manager initialized | "
            "Buffer: %d pips | Min time: %.1f sec | Min movement: %.6f",
            self.config.buffer_pips,
            self.config.min_time_between_mods_seconds,
            self.config.min_pip_movement,
        )

    def _resolve_symbol(self, symbol: str) -> str:
        """
        FUZZY SYMBOL HANDSHAKE: Resolve symbol using broker-specific naming.
        
        This method implements the critical fuzzy symbol matching to handle broker-specific
        symbol naming conventions (e.g., 'EURUSD.m', 'EURUSD.pro', 'EURUSD', etc.).
        
        This solves the 'symbol_info unavailable' warnings by ensuring the bot uses the exact
        symbol name that the broker expects, not just what the config specifies.
        
        Examples:
        - Config 'EUR/USD' → Broker uses 'EURUSD.m' → Resolves to 'EURUSD.m'
        - Config 'EURUSD' → Broker uses 'EURUSD' → Resolves to 'EURUSD'
        
        Falls back to original symbol if resolution fails (graceful degradation).
        
        Args:
            symbol: Raw symbol name (may have slashes or special chars)
        
        Returns:
            Resolved symbol name ready for MT5 API calls
        """
        try:
            from src.data.mt5_broker import find_fuzzy_symbol, sanitize_symbol
            import MetaTrader5 as mt5
            
            # Try fuzzy lookup first
            resolved = find_fuzzy_symbol(symbol)
            if resolved:
                logger.debug(f"[FUZZY_SYMBOL_RESOLVED] {symbol} → {resolved}")
                return resolved
            
            # Fallback: sanitize and try direct lookup
            sanitized = sanitize_symbol(symbol)
            if sanitized != symbol:
                logger.debug(f"[FUZZY_SYMBOL_FALLBACK] {symbol} sanitized to {sanitized}")
                return sanitized
            
            # Last resort: return as-is
            logger.warning(f"[FUZZY_SYMBOL_UNRESOLVED] Using original symbol: {symbol}")
            return symbol
        except Exception as e:
            logger.debug(f"[FUZZY_SYMBOL_ERROR] Failed to resolve {symbol}: {str(e)[:100]}")
            return symbol

    def _check_autotrading_enabled(self) -> bool:
        """
        Pre-flight check: Verify AutoTrading is enabled in MT5 terminal.
        Prevents attempting SL modifications while AutoTrading is disabled.

        Returns:
            True if trading is allowed, False otherwise
        """
        try:
            import MetaTrader5 as mt5
            terminal_info = mt5.terminal_info()
            if terminal_info is None:
                return True  # Can't check, assume OK

            trade_allowed = bool(getattr(terminal_info, "trade_allowed", False))
            if not trade_allowed:
                if not self._autotrading_disabled_logged:
                    logger.critical(
                        "[TRAILING_SL_AUTOTRADING_CHECK] AutoTrading is disabled in MT5 GUI. "
                        "Stop-loss modifications are blocked until AutoTrading is re-enabled."
                    )
                    self._autotrading_disabled_logged = True
                return False

            # AutoTrading is enabled, reset the flag
            if self._autotrading_disabled_logged:
                logger.info("[TRAILING_SL_AUTOTRADING_CHECK] AutoTrading re-enabled. Resuming modifications.")
                self._autotrading_disabled_logged = False

            return True
        except Exception as e:
            logger.warning(
                "[TRAILING_SL_AUTOTRADING_CHECK_ERROR] Failed to check terminal state: %s",
                str(e)[:100]
            )
            return True  # Can't check, assume OK

    def get_min_dist_from_price(self, symbol: str, symbol_info=None) -> float:
        """
        Fetch the minimum allowed distance from current price to SL.

        This prevents ERR_10016 (SL too close to price).

        Args:
            symbol: Trading symbol
            symbol_info: Optional pre-fetched symbol info (for efficiency)

        Returns:
            Minimum distance in price units (e.g., 0.0005 for 5 pips on EURUSD)
        """
        try:
            if symbol_info is None:
                # Import at method level to avoid module-level dependency
                import MetaTrader5 as mt5
                symbol_info = mt5.symbol_info(symbol)

            # FIX #3: STOPS_GUARD Fallback - Try symbol_select before giving up
            if symbol_info is None:
                logger.debug(
                    "[STOPS_GUARD] symbol_info returned None for %s. "
                    "Attempting to Market Watch symbol first...",
                    symbol
                )
                try:
                    import MetaTrader5 as mt5
                    # Try to add symbol to Market Watch
                    if mt5.symbol_select(symbol, True):
                        symbol_info = mt5.symbol_info(symbol)
                        if symbol_info is not None:
                            logger.debug(
                                "[STOPS_GUARD] Successfully added %s to Market Watch. "
                                "Now have symbol_info.",
                                symbol
                            )
                except Exception as select_err:
                    logger.debug(
                        "[STOPS_GUARD] symbol_select failed for %s: %s",
                        symbol,
                        str(select_err)[:50],
                    )

            if symbol_info is None:
                logger.info(
                    "[GUARD_ACTIVE] %s | Symbol not in Market Watch, using safety floor: 0.5 pips (0.00005)",
                    symbol
                )
                return 0.00005  # Safety floor: 0.5 pips for 5-decimal pairs (ultra-aggressive micro-profit protection)

            # stops_level is in POINTS (not pips)
            # 1 point = 0.0001 for 5-decimal pairs
            stops_level_points = symbol_info.trade_stops_level
            point_size = symbol_info.point

            if stops_level_points > 0:
                # Broker has explicit minimum distance requirement
                min_dist = stops_level_points * point_size
                logger.info(
                    "[GUARD_ACTIVE] %s | Broker safety limit: %d points | Min distance: %.8f",
                    symbol,
                    stops_level_points,
                    min_dist,
                )
                return min_dist
            else:
                # Broker doesn't enforce stops_level, use 0.5 pip floor
                min_dist = 0.5 * point_size
                logger.info(
                    "[GUARD_ACTIVE] %s | No explicit limit, using safety floor: 0.5 pips",
                    symbol
                )
                return min_dist

        except Exception as e:
            logger.info(
                "[GUARD_ACTIVE] Failed to retrieve %s broker limits: %s | Using safety floor: 0.5 pips",
                symbol,
                str(e)[:100],
            )
            return 0.00005  # Safety floor: 0.5 pips

    def get_min_dist(self, symbol: str, symbol_info=None) -> float:
        """Compatibility wrapper for the stops-level guard helper."""
        return self.get_min_dist_from_price(symbol, symbol_info)

    def snap_to_stops_level(
        self,
        new_sl: float,
        current_price: float,
        side: str,
        symbol_info=None,
    ) -> float:
        """
        Snap SL to the closest legal distance from current price (Stops Level + 1 point).
        Used when modification is too close to the price.
        
        Returns:
            Snapped SL price (closest legal distance from current price)
        """
        try:
            # Get stops level in points
            stops_level_points = int(getattr(symbol_info, 'trade_stops_level', 0) or 0)
            if stops_level_points == 0:
                stops_level_points = 5  # Broker default fallback (5 points)
            
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001) if symbol_info else 0.0001
        except:
            stops_level_points = 5
            point = 0.0001
        
        # Calculate minimum distance from price
        min_dist = (stops_level_points + 1) * point
        
        # Snap SL to minimum legal distance
        if side == "LONG":
            snapped_sl = current_price - min_dist
        else:  # SHORT
            snapped_sl = current_price + min_dist
        
        logger.debug(
            "[STOPS_LEVEL_SNAP] SL snapped from %.8f to %.8f (min_dist: %.8f)",
            new_sl, snapped_sl, min_dist
        )
        return snapped_sl

    def is_valid_modification(
        self,
        ticket: str,
        new_sl: float,
        side: str,
        symbol: str,
        current_price: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[str], Optional[float]]:
        """
        Validate if the new SL meets broker's minimum distance requirement.
        If too close, snaps to legal distance instead of blocking.

        Returns:
            (is_valid, reason_if_invalid, snapped_sl_if_snapped)
        """
        try:
            # Get minimum distance requirement
            min_dist = self.get_min_dist_from_price(symbol, symbol_info)

            # Calculate distance between current price and proposed SL
            distance = abs(current_price - new_sl)

            # Use small epsilon for floating point comparison (1 pip buffer)
            epsilon = self._get_pip_value(symbol)

            if distance < (min_dist - epsilon):
                # SL too close: Snap to legal distance instead of blocking
                snapped_sl = self.snap_to_stops_level(new_sl, current_price, side, symbol_info)
                
                logger.info(
                    "[STOPS_LEVEL_SNAP] %s ticket %s | distance %.8f < min_dist %.8f. Snapped to %.8f.",
                    symbol,
                    ticket,
                    distance,
                    min_dist,
                    snapped_sl,
                )
                return True, None, snapped_sl

            # Valid distance
            logger.debug(
                "[STOPS_GUARD_PASS] %s ticket %s | distance %.8f >= min_dist %.8f",
                symbol,
                ticket,
                distance,
                min_dist,
            )
            return True, None, new_sl

        except Exception as e:
            logger.error(
                "[STOPS_GUARD_ERROR] Validation failed for %s ticket %s: %s",
                symbol,
                ticket,
                str(e)[:100],
            )
            # On error, allow (conservative - assume broker will validate)
            return True, None, new_sl

    def track_position(
        self,
        ticket: str,
        symbol: str,
        side: str,
        entry_price: float,
        current_sl: float,
        tp_price: float = 0.0,
        commission: float = 0.0,
        swap: float = 0.0,
        current_price: float = None,
        atr_value: float = None,
    ) -> None:
        """
        Start tracking a position for trailing SL.
        
        CRITICAL: VIRTUAL TP FOR ADOPTED TRADES
        ======================================
        If a trade is adopted with TP == 0 (no take-profit set), the bot automatically assigns
        a Virtual TP at 3x the ATR distance from entry price. This enables DPC logic for manual
        trades that don't have explicit take-profit levels.
        
        If ATR is unavailable, falls back to 2.5:1 risk-reward ratio.
        
        Example:
        - Entry: 1.0850, SL: 1.0800 (risk = 50 pips = 0.0050)
        - ATR: 0.0030 → Virtual TP = 1.0850 + (0.0030 * 3) = 1.0940
        - Fallback: Virtual TP = 1.0850 + (50 pips * 2.5) = 1.1100

        Args:
            ticket: Position ticket/ID
            symbol: Trading symbol (will be resolved via fuzzy handshake)
            side: "LONG" or "SHORT"
            entry_price: Entry price
            current_sl: Current stop loss
            tp_price: Take Profit price (optional, for Endzone 90% detection)
            commission: Broker commission on trade (in $ or pips equivalent)
            swap: Accumulated swap/overnight fees (in $ or pips equivalent)
            current_price: Current price (needed for virtual TP calculation)
            atr_value: Current ATR value (optional, for virtual TP calculation)
        """
        # ===== FUZZY SYMBOL HANDSHAKE =====
        # Resolve symbol: EUR/USD → EURUSD or EURUSD.m, etc.
        resolved_symbol = self._resolve_symbol(symbol)
        
        # Calculate Virtual TP if not provided
        virtual_tp = tp_price
        is_virtual = False
        virtual_method = ""
        
        if tp_price == 0.0 and current_price:
            virtual_tp, virtual_method = self._calculate_virtual_tp(
                symbol=resolved_symbol,
                side=side,
                entry_price=entry_price,
                current_sl=current_sl,
                current_price=current_price,
                atr_value=atr_value,
            )
            is_virtual = True
            logger.info(
                "[DPC_TARGET_SET] %s Ticket: %s | No TP detected. Assigned Virtual Target at %.5f (method: %s)",
                resolved_symbol, ticket, virtual_tp, virtual_method
            )
        
        state = PositionTrailingState(
            ticket=ticket,
            symbol=resolved_symbol,
            side=side,
            entry_price=entry_price,
            current_sl=current_sl,
            tp_price=virtual_tp,
            commission=commission,
            swap=swap,
            is_virtual_tp=is_virtual,
            virtual_tp_assigned_at=datetime.now(timezone.utc) if is_virtual else None,
            highest_price_long=entry_price if side == "LONG" else 0.0,
            lowest_price_short=entry_price if side == "SHORT" else float('inf'),
            atr_value=atr_value if atr_value else 0.0,
        )

        self._positions[ticket] = state

        if is_virtual:
            logger.info(
                "[TRAILING_SL_TRACK] %s | Ticket: %s | Side: %s | Entry: %.5f | SL: %.5f | TP: %.5f (Virtual) | Commission: %.6f | Swap: %.6f",
                resolved_symbol, ticket, side, entry_price, current_sl, virtual_tp, commission, swap
            )
        else:
            logger.info(
                "[TRAILING_SL_TRACK] %s | Ticket: %s | Side: %s | Entry: %.5f | SL: %.5f | TP: %.5f | Commission: %.6f | Swap: %.6f",
                resolved_symbol, ticket, side, entry_price, current_sl, tp_price, commission, swap
            )
    
    def _calculate_virtual_tp(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        current_sl: float,
        current_price: float = None,
        atr_value: float = None,
    ) -> Tuple[float, str]:
        """
        Calculate Virtual TP for positions with TP=0.
        Uses 3x ATR distance from entry price.
        
        Returns:
            (virtual_tp_price, calculation_method)
        """
        # If no ATR, use 2.5:1 RR as fallback
        if not atr_value or atr_value <= 0:
            # Fallback: 2.5:1 RR ratio
            if side == "LONG":
                risk_distance = entry_price - current_sl
                virtual_tp = entry_price + (risk_distance * 2.5)
            else:  # SHORT
                risk_distance = current_sl - entry_price
                virtual_tp = entry_price - (risk_distance * 2.5)
            return virtual_tp, "RR_2.5x_fallback"
        
        # Primary method: 3x ATR from entry
        if side == "LONG":
            virtual_tp = entry_price + (atr_value * 3)
        else:  # SHORT
            virtual_tp = entry_price - (atr_value * 3)
        
        return virtual_tp, "ATR_3x"
    
    def _check_hard_floor_lock(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Capital Guardian Rule: If profit > $2.00 and SL is below entry, move SL to Entry + Fees + 0.5 pips.
        Makes the trade 'Risk-Free' regardless of TP distance.
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Calculate current profit in dollars
        if state.side == "LONG":
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Check if profit exceeds $2.00
        if current_profit_dollars <= 2.00:
            return False, None, ""
        
        # Calculate Entry + Fees + 0.5 pips (risk-free protection)
        try:
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001) if symbol_info else 0.0001
        except:
            point = 0.0001
        
        fee_price = state.commission + abs(state.swap)
        safety_pips = 0.5 * point  # 0.5 pips safety
        
        if state.side == "LONG":
            capital_guardian_sl = state.entry_price + fee_price + safety_pips
            # Only move if SL would be higher (tighter)
            if capital_guardian_sl > state.current_sl:
                # Check if current SL is still at a loss
                if state.current_sl < state.entry_price:
                    return True, capital_guardian_sl, f"Capital Guardian: Profit ${current_profit_dollars:.2f}"
        else:  # SHORT
            capital_guardian_sl = state.entry_price - fee_price - safety_pips
            # Only move if SL would be lower (tighter)
            if capital_guardian_sl < state.current_sl:
                # Check if current SL is still at a loss
                if state.current_sl > state.entry_price:
                    return True, capital_guardian_sl, f"Capital Guardian: Profit ${current_profit_dollars:.2f}"
        
        return False, None, ""
    
    def _check_tiered_cash_protection(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Tiered Cash-Profit Locking: Lock in specific dollar amounts at profit milestones.
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        - Profit > $5.00: Lock in $2.00
        - Profit > $10.00: Lock in $6.00
        - Profit > $15.00: Lock in $11.00
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Calculate current profit in dollars
        if state.side == "LONG":
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Check $15.00 threshold first (highest priority)
        if current_profit_dollars > 15.00 and not state.tiered_cash_15_hit:
            locked_amount = 11.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.tiered_cash_15_hit = True
                return True, new_sl, f"[CASH_SECURED] {state.symbol} profit hit $15.00 milestone. SL moved to lock in $11.00."
        
        # Check $10.00 threshold
        if current_profit_dollars > 10.00 and not state.tiered_cash_10_hit and not state.tiered_cash_15_hit:
            locked_amount = 6.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.tiered_cash_10_hit = True
                return True, new_sl, f"[CASH_SECURED] {state.symbol} profit hit $10.00 milestone. SL moved to lock in $6.00."
        
        # Check $5.00 threshold
        if current_profit_dollars > 5.00 and not state.tiered_cash_5_hit and not state.tiered_cash_10_hit and not state.tiered_cash_15_hit:
            locked_amount = 2.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.tiered_cash_5_hit = True
                return True, new_sl, f"[CASH_SECURED] {state.symbol} profit hit $5.00 milestone. SL moved to lock in $2.00."
        
        return False, None, ""
    
    def _check_dpc_tiered_profit_sniper(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Aggressive Profit Sniper (DPC): Lock profits at TP progress milestones.
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        RECALIBRATED:
        - Tier 1 (40% to TP): SL = Entry + Fees (breakeven - no point buffer)
        - Tier 2 (65% to TP): SL = Entry + (40% of current profit)
        - Tier 3 (85% to TP): SL = Entry + (75% of current profit, "Anti-Heartbreak")
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Check if TP is set (Virtual or Real)
        if state.tp_price <= 0:
            return False, None, ""
        
        # Calculate progress to TP
        if state.side == "LONG":
            tp_distance = state.tp_price - state.entry_price
            if tp_distance <= 0:
                return False, None, ""
            progress = (current_price - state.entry_price) / tp_distance
        else:  # SHORT
            tp_distance = state.entry_price - state.tp_price
            if tp_distance <= 0:
                return False, None, ""
            progress = (state.entry_price - current_price) / tp_distance
        
        # Tier 3 (85% to TP): Lock 75% of profit
        if progress >= 0.85 and not state.dpc_tier_3_hit:
            current_profit_dollars = (current_price - state.entry_price) * pip_value * 10000 if state.side == "LONG" else (state.entry_price - current_price) * pip_value * 10000
            
            if state.side == "LONG":
                current_profit_pips = (current_price - state.entry_price) / pip_value
                locked_pips = 0.75 * current_profit_pips
                tier_3_sl = state.entry_price + (locked_pips * pip_value)
            else:  # SHORT
                current_profit_pips = (state.entry_price - current_price) / pip_value
                locked_pips = 0.75 * current_profit_pips
                tier_3_sl = state.entry_price - (locked_pips * pip_value)
            
            # Validate
            is_tighter = (state.side == "LONG" and tier_3_sl > state.current_sl) or (state.side == "SHORT" and tier_3_sl < state.current_sl)
            if is_tighter:
                state.dpc_tier_3_hit = True
                return True, tier_3_sl, f"[PROFIT_SNIPER] {state.symbol} locked in ${current_profit_dollars:.2f} (Milestone hit)"
        
        # Tier 2 (65% to TP): Lock 40% of profit
        if progress >= 0.65 and not state.dpc_tier_2_hit and not state.dpc_tier_3_hit:
            if state.side == "LONG":
                current_profit_pips = (current_price - state.entry_price) / pip_value
                locked_pips = 0.40 * current_profit_pips
                tier_2_sl = state.entry_price + (locked_pips * pip_value)
            else:  # SHORT
                current_profit_pips = (state.entry_price - current_price) / pip_value
                locked_pips = 0.40 * current_profit_pips
                tier_2_sl = state.entry_price - (locked_pips * pip_value)
            
            # Validate
            is_tighter = (state.side == "LONG" and tier_2_sl > state.current_sl) or (state.side == "SHORT" and tier_2_sl < state.current_sl)
            if is_tighter:
                state.dpc_tier_2_hit = True
                current_profit_dollars = (current_price - state.entry_price) * pip_value * 10000 if state.side == "LONG" else (state.entry_price - current_price) * pip_value * 10000
                return True, tier_2_sl, f"[PROFIT_SNIPER] {state.symbol} locked in ${current_profit_dollars:.2f} (Milestone hit)"
        
        # Tier 1 (40% to TP): Entry + Fees (breakeven)
        if progress >= 0.40 and not state.dpc_tier_1_hit and not state.dpc_tier_2_hit and not state.dpc_tier_3_hit:
            fee_price = state.commission + abs(state.swap)
            
            if state.side == "LONG":
                tier_1_sl = state.entry_price + fee_price
            else:  # SHORT
                tier_1_sl = state.entry_price - fee_price
            
            # Validate
            is_tighter = (state.side == "LONG" and tier_1_sl > state.current_sl) or (state.side == "SHORT" and tier_1_sl < state.current_sl)
            if is_tighter:
                state.dpc_tier_1_hit = True
                current_profit_dollars = (current_price - state.entry_price) * pip_value * 10000 if state.side == "LONG" else (state.entry_price - current_price) * pip_value * 10000
                return True, tier_1_sl, f"[PROFIT_SNIPER] {state.symbol} locked in ${current_profit_dollars:.2f} (Milestone hit)"
        
        return False, None, ""
    
    def _check_capital_protection_2_dollar_floor(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        PRIORITY 0: Capital Protection $2.00 No-Loss Floor (HIGHEST PRIORITY)
        ===================================================================
        
        This is the HIGHEST priority check that runs FIRST before all other conditions.
        If profit > $2.00 AND SL is still at a loss, move SL to Entry + Fees + 1 point immediately,
        bypassing all timers and other conditions.
        
        This ensures the bot NEVER lets a profitable trade turn into a loss due to slow SL updates.
        
        INSTITUTIONAL RULE: Once you hit $2.00 profit, the trade is LOCKED to protect capital.
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Only check once (prevent repetition)
        if state.hard_dollar_2_lock_hit:
            return False, None, ""
        
        # Calculate current profit in dollars
        if state.side == "LONG":
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Check if profit exceeds $2.00 AND SL is at a loss
        if current_profit_dollars > 2.00:
            sl_at_loss = (state.side == "LONG" and state.current_sl < state.entry_price) or (state.side == "SHORT" and state.current_sl > state.entry_price)
            
            if sl_at_loss:
                try:
                    point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001) if symbol_info else 0.0001
                except:
                    point = 0.0001
                
                fee_price = state.commission + abs(state.swap)
                
                if state.side == "LONG":
                    new_sl = state.entry_price + fee_price + point
                else:  # SHORT
                    new_sl = state.entry_price - fee_price - point
                
                # Verify it's a tighter SL
                is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
                if is_tighter:
                    state.hard_dollar_2_lock_hit = True
                    locked_profit = current_profit_dollars - 0.02  # Approximate locked profit (fees)
                    return True, new_sl, f"[CAPITAL_PROTECTION] {state.symbol} PRIORITY 0: $2.00 no-loss floor activated. SL moved to Entry+Fees+1point."
        
        return False, None, ""
    
    def _check_hard_dollar_profit_locking(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Hard Dollar Profit Locking: Institutional lockdown at specific dollar milestones.
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        Thresholds (Institutional Profit Lockdown):
        1. $2.00 Lock: If profit > $2.00 AND SL at loss → Move SL to Entry + Fees + 1 point (No-Loss Floor)
        2. $4.00 Milestone: If profit >= $4.00 → Lock $1.50 profit (aggressive early capture)
        3. $7.50 Milestone: If profit >= $7.50 → Lock $4.00 profit (maximum institutional lock)
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Calculate current profit in dollars
        if state.side == "LONG":
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # PRIORITY 1: $2.00 Lock (No-Loss Floor)
        # If profit > $2.00 and SL is still at a loss, move SL to Entry + Fees + 1 point
        if current_profit_dollars > 2.00 and not state.hard_dollar_2_lock_hit:
            sl_at_loss = (state.side == "LONG" and state.current_sl < state.entry_price) or (state.side == "SHORT" and state.current_sl > state.entry_price)
            
            if sl_at_loss:
                try:
                    point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001) if symbol_info else 0.0001
                except:
                    point = 0.0001
                
                fee_price = state.commission + abs(state.swap)
                
                if state.side == "LONG":
                    new_sl = state.entry_price + fee_price + point
                else:  # SHORT
                    new_sl = state.entry_price - fee_price - point
                
                # Verify it's a tighter SL
                is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
                if is_tighter:
                    state.hard_dollar_2_lock_hit = True
                locked_profit = current_profit_dollars - (state.commission + abs(state.swap))
                return True, new_sl, f"[CASH_SECURED] {state.symbol} $2.00 no-loss floor activated. SL moved to lock in ${locked_profit:.2f}."
        # PRIORITY 2: $7.50 Milestone (highest first, then cascade down)
        if current_profit_dollars >= 7.50 and not state.hard_dollar_7_5_lock_hit:
            locked_amount = 4.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_7_5_lock_hit = True
                return True, new_sl, f"[CASH_SECURED] {state.symbol} profit hit $7.50 milestone. SL moved to lock in $4.00."
        
        # PRIORITY 3: $4.00 Milestone
        if current_profit_dollars >= 4.00 and not state.hard_dollar_4_lock_hit and not state.hard_dollar_7_5_lock_hit:
            locked_amount = 1.50
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_4_lock_hit = True
                return True, new_sl, f"[CASH_SECURED] {state.symbol} profit hit $4.00 milestone. SL moved to lock in $1.50."
        
        return False, None, ""
    
    def _check_hyper_aggressive_sniper_90(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Hyper-Aggressive 90% Sniper: Strangles price at the finish line.
        If trade is within 90% of its TP distance, lock in 90% of current profit immediately.
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Only works if position has a valid TP
        if state.tp_price == 0.0 or state.tp_price == state.entry_price:
            return False, None, ""
        
        # Already hit this tier
        if state.hyper_aggressive_90_hit:
            return False, None, ""
        
        # Calculate progress toward TP
        if state.side == "LONG":
            distance_to_tp = state.tp_price - state.entry_price
            current_distance = current_price - state.entry_price
            progress_pct = current_distance / distance_to_tp if distance_to_tp != 0 else 0
            
            # Calculate current profit in dollars
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            distance_to_tp = state.entry_price - state.tp_price
            current_distance = state.entry_price - current_price
            progress_pct = current_distance / distance_to_tp if distance_to_tp != 0 else 0
            
            # Calculate current profit in dollars
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Check if within 90% of TP
        if progress_pct >= 0.90 and current_profit_dollars > 0:
            # Lock in 90% of current profit
            locked_amount = current_profit_dollars * 0.90
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Verify it's a tighter SL
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hyper_aggressive_90_hit = True
                return True, new_sl, f"[CASH_SECURED] {state.symbol} 90% to TP! Profit ${current_profit_dollars:.2f}. SL locked in ${locked_amount:.2f} (SNIPER)."
        
        return False, None, ""
    
    def _check_hard_dollar_lock(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Hard Dollar Lock: Lock profits at specific dollar milestones ($3/$6).
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        - $3.00 profit: Lock $0.50
        - $6.00 profit: Lock $3.00
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Calculate current profit in dollars
        if state.side == "LONG":
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Check $6.00 threshold first (highest priority)
        if current_profit_dollars > 6.00 and not state.hard_dollar_6_hit:
            locked_amount = 3.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_6_hit = True
                return True, new_sl, f"[PROFIT_SNIPER] {state.symbol} profit reached ${current_profit_dollars:.2f}. SL locked at ${locked_amount:.2f}."
        
        # Check $3.00 threshold
        if current_profit_dollars > 3.00 and not state.hard_dollar_3_hit and not state.hard_dollar_6_hit:
            locked_amount = 0.50
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_3_hit = True
                return True, new_sl, f"[PROFIT_SNIPER] {state.symbol} profit reached ${current_profit_dollars:.2f}. SL locked at ${locked_amount:.2f}."
        
        return False, None, ""
    
    def _check_milestone_profit_sniper(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Milestone Profit Sniper (Hyper-Aggressive): Lock profits at TP progress milestones.
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        - Milestone 50% (50% to TP): SL = Entry + Fees + 1 pip (100% capital safe)
        - Milestone 80% (80% to TP): SL = Entry + (65% of current profit)
        - Milestone 90% (90% to TP): SL = Entry + (85% of current profit, "Sniper Zone")
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Check if TP is set (Virtual or Real)
        if state.tp_price <= 0:
            return False, None, ""
        
        # Calculate progress to TP
        if state.side == "LONG":
            tp_distance = state.tp_price - state.entry_price
            if tp_distance <= 0:
                return False, None, ""
            progress = (current_price - state.entry_price) / tp_distance
        else:  # SHORT
            tp_distance = state.entry_price - state.tp_price
            if tp_distance <= 0:
                return False, None, ""
            progress = (state.entry_price - current_price) / tp_distance
        
        # Milestone 90% (Sniper Zone): Lock 85% of profit
        if progress >= 0.90 and not state.milestone_90_hit:
            current_profit_dollars = (current_price - state.entry_price) * pip_value * 10000 if state.side == "LONG" else (state.entry_price - current_price) * pip_value * 10000
            
            if state.side == "LONG":
                current_profit_pips = (current_price - state.entry_price) / pip_value
                locked_pips = 0.85 * current_profit_pips
                milestone_90_sl = state.entry_price + (locked_pips * pip_value)
            else:  # SHORT
                current_profit_pips = (state.entry_price - current_price) / pip_value
                locked_pips = 0.85 * current_profit_pips
                milestone_90_sl = state.entry_price - (locked_pips * pip_value)
            
            # Validate
            is_tighter = (state.side == "LONG" and milestone_90_sl > state.current_sl) or (state.side == "SHORT" and milestone_90_sl < state.current_sl)
            if is_tighter:
                state.milestone_90_hit = True
                return True, milestone_90_sl, f"[SNIPER_LOCK] {state.symbol} Tier 3 reached. Profit secured: ${current_profit_dollars:.2f}"
        
        # Milestone 80%: Lock 65% of profit
        if progress >= 0.80 and not state.milestone_80_hit and not state.milestone_90_hit:
            current_profit_dollars = (current_price - state.entry_price) * pip_value * 10000 if state.side == "LONG" else (state.entry_price - current_price) * pip_value * 10000
            
            if state.side == "LONG":
                current_profit_pips = (current_price - state.entry_price) / pip_value
                locked_pips = 0.65 * current_profit_pips
                milestone_80_sl = state.entry_price + (locked_pips * pip_value)
            else:  # SHORT
                current_profit_pips = (state.entry_price - current_price) / pip_value
                locked_pips = 0.65 * current_profit_pips
                milestone_80_sl = state.entry_price - (locked_pips * pip_value)
            
            # Validate
            is_tighter = (state.side == "LONG" and milestone_80_sl > state.current_sl) or (state.side == "SHORT" and milestone_80_sl < state.current_sl)
            if is_tighter:
                state.milestone_80_hit = True
                return True, milestone_80_sl, f"[SNIPER_LOCK] {state.symbol} Tier 2 reached. Profit secured: ${current_profit_dollars:.2f}"
        
        # Milestone 50%: Entry + Fees + 1 pip (100% capital safe)
        if progress >= 0.50 and not state.milestone_50_hit and not state.milestone_80_hit and not state.milestone_90_hit:
            try:
                point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001) if symbol_info else 0.0001
            except:
                point = 0.0001
            
            fee_price = state.commission + abs(state.swap)
            safety_pips = 1.0 * point  # 1 pip safety
            
            if state.side == "LONG":
                milestone_50_sl = state.entry_price + fee_price + safety_pips
            else:  # SHORT
                milestone_50_sl = state.entry_price - fee_price - safety_pips
            
            # Validate
            is_tighter = (state.side == "LONG" and milestone_50_sl > state.current_sl) or (state.side == "SHORT" and milestone_50_sl < state.current_sl)
            if is_tighter:
                state.milestone_50_hit = True
                current_profit_dollars = (current_price - state.entry_price) * pip_value * 10000 if state.side == "LONG" else (state.entry_price - current_price) * pip_value * 10000
                return True, milestone_50_sl, f"[SNIPER_LOCK] {state.symbol} Tier 1 reached. Profit secured: ${current_profit_dollars:.2f}"
        
        return False, None, ""
    
    def _check_hard_dollar_circuit_breakers(
        self,
        state: PositionTrailingState,
        current_price: float,
        pip_value: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Hard Dollar Circuit-Breakers: Lock profits at cash-based thresholds (Hyper-Aggressive).
        This is an INSTANT LOCK that bypasses the 5-minute throttle.
        
        - $2.50 profit: Move SL to Entry + Fees (breakeven + fees covered)
        - $5.00 profit: Lock $2.00 profit
        - $10.00 profit: Lock $7.00 profit
        
        Returns:
            (should_modify, new_sl, reason)
        """
        # Calculate current profit in dollars
        if state.side == "LONG":
            price_move = current_price - state.entry_price
            current_profit_dollars = price_move * pip_value * 10000
        else:  # SHORT
            price_move = state.entry_price - current_price
            current_profit_dollars = price_move * pip_value * 10000
        
        # Check $10.00 threshold first (highest priority)
        if current_profit_dollars > 10.00 and not state.hard_dollar_10_hit:
            locked_amount = 7.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_10_hit = True
                return True, new_sl, f"[SNIPER_LOCK] {state.symbol} Circuit-Breaker $10 hit. Locked ${locked_amount:.2f} profit."
        
        # Check $5.00 threshold
        if current_profit_dollars > 5.00 and not state.hard_dollar_5_hit and not state.hard_dollar_10_hit:
            locked_amount = 2.00
            locked_pips = locked_amount / (pip_value * 10000)
            
            if state.side == "LONG":
                new_sl = state.entry_price + locked_pips
            else:
                new_sl = state.entry_price - locked_pips
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_5_hit = True
                return True, new_sl, f"[SNIPER_LOCK] {state.symbol} Circuit-Breaker $5 hit. Locked ${locked_amount:.2f} profit."
        
        # Check $2.50 threshold
        if current_profit_dollars > 2.50 and not state.hard_dollar_2_50_hit and not state.hard_dollar_5_hit and not state.hard_dollar_10_hit:
            fee_price = state.commission + abs(state.swap)
            
            if state.side == "LONG":
                new_sl = state.entry_price + fee_price
            else:
                new_sl = state.entry_price - fee_price
            
            # Check if tighter
            is_tighter = (state.side == "LONG" and new_sl > state.current_sl) or (state.side == "SHORT" and new_sl < state.current_sl)
            if is_tighter:
                state.hard_dollar_2_50_hit = True
                return True, new_sl, f"[SNIPER_LOCK] {state.symbol} Circuit-Breaker $2.50 hit. SL at Entry + Fees."
        
        return False, None, ""
    
    def update_fees(
        self,
        ticket: str,
        commission: float = None,
        swap: float = None,
    ) -> None:
        """
        Update accumulated fees for a tracked position.
        
        Useful when swap costs accumulate overnight or additional commissions apply.
        This ensures the profit lock SL stays accurate as fees increase.
        
        Args:
            ticket: Position ticket/ID
            commission: Updated commission (if None, keeps current value)
            swap: Updated swap (if None, keeps current value)
        """
        if ticket not in self._positions:
            logger.warning("[FEE_UPDATE] Ticket %s not tracked, cannot update fees", ticket)
            return
        
        state = self._positions[ticket]
        old_commission = state.commission
        old_swap = state.swap
        
        if commission is not None:
            state.commission = float(commission)
        if swap is not None:
            state.swap = float(swap)
        
        logger.debug(
            "[FEE_UPDATE] %s | Ticket: %s | Commission: %.6f -> %.6f | Swap: %.6f -> %.6f",
            state.symbol, ticket, old_commission, state.commission, old_swap, state.swap
        )

    def untrack_position(self, ticket: str) -> Optional[PositionTrailingState]:
        """Stop tracking and return final state."""
        return self._positions.pop(ticket, None)

    async def update_trailing_sl(
        self,
        ticket: str,
        current_price: float,
    ) -> Tuple[bool, Optional[str]]:
        """
        Update trailing SL for a position based on current price.
        
        CRITICAL: Institutional Profit Lockdown Logic
        ============================================
        This implementation includes instant execution of cash milestone and DPC logic,
        which BYPASSES the normal 5-minute throttle to ensure rapid profit protection.
        
        Execution Order (by priority):
        1. PRIORITY 0: $2.00 Capital Protection (No-Loss Floor) - INSTANT EXECUTION
        2. PRIORITY 1: Hyper-Aggressive 90% Sniper - INSTANT EXECUTION
        3. PRIORITY 2: Hard Dollar Profit Locking ($4.00, $7.50) - INSTANT EXECUTION
        4. PRIORITY 3: DPC Tiered Profit Sniper (40%/65%/85%) - INSTANT EXECUTION
        5. Legacy: Milestone Profit Sniper & Circuit-Breakers (fallback)
        6. Standard: Normal Trailing SL with 5-minute throttle

        Returns:
            (modified, reason) - True if SL was modified, reason string
        """
        # ===== PRE-FLIGHT CHECK: Verify AutoTrading is enabled =====
        if not self._check_autotrading_enabled():
            return False, "AutoTrading disabled in MT5 GUI - modifications blocked"

        if ticket not in self._positions:
            return False, "Position not tracked"

        state = self._positions[ticket]
        current_time = datetime.now()

        # ===== Fetch symbol info once (efficient) =====
        symbol_info = None
        try:
            import MetaTrader5 as mt5
            symbol_info = mt5.symbol_info(state.symbol)
        except:
            symbol_info = None

        if state.is_running_as_runner:
            return await self.continuous_sl_check(ticket, current_price, symbol_info=symbol_info)

        # ===== AGGRESSIVE PROFIT SNIPER: INSTANT LOCKS (BYPASS 5-MIN THROTTLE) =====
        # These checks execute immediately on every price tick, bypassing the normal 5-minute
        # throttle between modifications. This enables rapid profit protection and capital preservation.
        #
        # CASH MILESTONES (Institutional Lockdown):
        # - $2.00 No-Loss Floor: If profit > $2.00, move SL to Entry + Fees + 1 point (removes all risk)
        # - $4.00 Milestone: If profit >= $4.00, lock $1.50 (aggressive early capture)
        # - $7.50 Milestone: If profit >= $7.50, lock $4.00 (maximum institutional lock)
        #
        # DPC TIERED PROFIT SNIPER (Percentage-based):
        # - Tier 1 (40% to TP): SL = Entry + Fees (breakeven)
        # - Tier 2 (65% to TP): SL = Entry + (40% of current profit)
        # - Tier 3 (85% to TP): SL = Entry + (75% of current profit, "Anti-Heartbreak")
        #
        # HYPER-AGGRESSIVE 90% SNIPER:
        # - At 90% to TP: Lock 90% of current profit (finish line strangulation)
        pip_value = self._get_pip_value(state.symbol)
        
        # ===== PRIORITY 0: $2.00 Capital Protection (HIGHEST PRIORITY) =====
        # The $2.00 no-loss floor is checked FIRST, before all other conditions
        # This ensures that as soon as any trade hits $2.00 profit, we move SL immediately
        capital_protect_modify, capital_protect_sl, capital_protect_reason = self._check_capital_protection_2_dollar_floor(
            state, current_price, pip_value, symbol_info
        )
        if capital_protect_modify:
            try:
                success = await self.broker.modify_order(
                    order_id=ticket,
                    sl=capital_protect_sl,
                    tp=None,
                )
                if success:
                    state.current_sl = capital_protect_sl
                    state.last_sl_modification_time = current_time
                    state.last_sl_modification_price = current_price
                    state.total_modifications += 1
                    logger.info("%s", capital_protect_reason)
                    return True, capital_protect_reason
            except Exception as e:
                logger.debug("[CAPITAL_PROTECTION_ERROR] Failed: %s", str(e)[:100])
        
        # ===== INSTANT EXECUTION PROFIT PROTECTION (BYPASS 5-MIN THROTTLE) =====
        # Maximum SL tightening speed for profit preservation
        
        # PRIORITY 1: Hyper-Aggressive 90% Sniper (finish line strangulation)
        sniper_90_modify, sniper_90_sl, sniper_90_reason = self._check_hyper_aggressive_sniper_90(
            state, current_price, pip_value, symbol_info
        )
        if sniper_90_modify:
            try:
                success = await self.broker.modify_order(
                    order_id=ticket,
                    sl=sniper_90_sl,
                    tp=None,
                )
                if success:
                    state.current_sl = sniper_90_sl
                    state.last_sl_modification_time = current_time
                    state.last_sl_modification_price = current_price
                    state.total_modifications += 1
                    logger.info("%s", sniper_90_reason)
                    return True, sniper_90_reason
            except Exception as e:
                logger.debug("[HYPER_AGGRESSIVE_90_ERROR] Failed: %s", str(e)[:100])
        
        # PRIORITY 2: Hard Dollar Profit Locking ($4/$7.50)
        if self.config.enable_hard_dollar_locks:
            hdpl_modify, hdpl_sl, hdpl_reason = self._check_hard_dollar_profit_locking(
                state, current_price, pip_value, symbol_info
            )
            if hdpl_modify:
                try:
                    success = await self.broker.modify_order(
                        order_id=ticket,
                        sl=hdpl_sl,
                        tp=None,
                    )
                    if success:
                        state.current_sl = hdpl_sl
                        state.last_sl_modification_time = current_time
                        state.last_sl_modification_price = current_price
                        state.total_modifications += 1
                        logger.info("%s", hdpl_reason)
                        return True, hdpl_reason
                except Exception as e:
                    logger.debug("[HARD_DOLLAR_PROFIT_LOCKING_ERROR] Failed: %s", str(e)[:100])
        
        # PRIORITY 3: DPC Tiered Profit Sniper (40%/65%/85% - RECALIBRATED)
        dpc_modify, dpc_sl, dpc_reason = self._check_dpc_tiered_profit_sniper(
            state, current_price, pip_value, symbol_info
        )
        if dpc_modify:
            try:
                success = await self.broker.modify_order(
                    order_id=ticket,
                    sl=dpc_sl,
                    tp=None,
                )
                if success:
                    state.current_sl = dpc_sl
                    state.last_sl_modification_time = current_time
                    state.last_sl_modification_price = current_price
                    state.total_modifications += 1
                    logger.info("%s", dpc_reason)
                    return True, dpc_reason
            except Exception as e:
                logger.debug("[DPC_TIER_ERROR] Failed: %s", str(e)[:100])
        
        # LEGACY: Check Milestone Profit Sniper (50/80/90% Rule) - HYPER-AGGRESSIVE
        milestone_modify, milestone_sl, milestone_reason = self._check_milestone_profit_sniper(
            state, current_price, pip_value, symbol_info
        )
        if milestone_modify:
            try:
                success = await self.broker.modify_order(
                    order_id=ticket,
                    sl=milestone_sl,
                    tp=None,
                )
                if success:
                    state.current_sl = milestone_sl
                    state.last_sl_modification_time = current_time
                    state.last_sl_modification_price = current_price
                    state.total_modifications += 1
                    logger.info("%s", milestone_reason)
                    return True, milestone_reason
            except Exception as e:
                logger.debug("[MILESTONE_SNIPER_ERROR] Failed: %s", str(e)[:100])
        
        # LEGACY: Check Hard Dollar Circuit-Breakers ($2.50/$5.00/$10.00) - HYPER-AGGRESSIVE
        if self.config.enable_hard_dollar_locks:
            circuit_modify, circuit_sl, circuit_reason = self._check_hard_dollar_circuit_breakers(
                state, current_price, pip_value, symbol_info
            )
            if circuit_modify:
                try:
                    success = await self.broker.modify_order(
                        order_id=ticket,
                        sl=circuit_sl,
                        tp=None,
                    )
                    if success:
                        state.current_sl = circuit_sl
                        state.last_sl_modification_time = current_time
                        state.last_sl_modification_price = current_price
                        state.total_modifications += 1
                        logger.info("%s", circuit_reason)
                        return True, circuit_reason
                except Exception as e:
                    logger.debug("[CIRCUIT_BREAKER_ERROR] Failed: %s", str(e)[:100])
        
        # LEGACY: Check Hard Dollar Lock ($3/$6)
        if self.config.enable_hard_dollar_locks:
            hdl_modify, hdl_sl, hdl_reason = self._check_hard_dollar_lock(
                state, current_price, pip_value, symbol_info
            )
            if hdl_modify:
                try:
                    success = await self.broker.modify_order(
                        order_id=ticket,
                        sl=hdl_sl,
                        tp=None,
                    )
                    if success:
                        state.current_sl = hdl_sl
                        state.last_sl_modification_time = current_time
                        state.last_sl_modification_price = current_price
                        state.total_modifications += 1
                        logger.info("%s", hdl_reason)
                        return True, hdl_reason
                except Exception as e:
                    logger.debug("[HARD_DOLLAR_ERROR] Failed: %s", str(e)[:100])

        # ===== INSTANT RATCHET: Check Hard Floor Lock & Tiered Cash Protection (BYPASS 5-MIN THROTTLE) =====
        
        if self.config.enable_hard_dollar_locks:
            # Check Hard Floor Lock: $2.00 profit protection
            hard_floor_modify, hard_floor_sl, hard_floor_reason = self._check_hard_floor_lock(
                state, current_price, pip_value, symbol_info
            )
            if hard_floor_modify:
                try:
                    success = await self.broker.modify_order(
                        order_id=ticket,
                        sl=hard_floor_sl,
                        tp=None,
                    )
                    if success:
                        state.current_sl = hard_floor_sl
                        state.last_sl_modification_time = current_time
                        state.last_sl_modification_price = current_price
                        state.total_modifications += 1
                        state.hard_floor_activated = True
                        logger.info(
                            "[CASH_LOCK] %s Ticket: %s | %s",
                            state.symbol, ticket, hard_floor_reason
                        )
                        return True, hard_floor_reason
                except Exception as e:
                    logger.debug("[INSTANT_RATCHET_ERROR] Hard floor lock failed: %s", str(e)[:100])
            
            # Check Tiered Cash Protection: $5/$10 profit locks
            tiered_modify, tiered_sl, tiered_reason = self._check_tiered_cash_protection(
                state, current_price, pip_value, symbol_info
            )
            if tiered_modify:
                try:
                    success = await self.broker.modify_order(
                        order_id=ticket,
                        sl=tiered_sl,
                        tp=None,
                    )
                    if success:
                        state.current_sl = tiered_sl
                        state.last_sl_modification_time = current_time
                        state.last_sl_modification_price = current_price
                        state.total_modifications += 1
                        logger.info("%s", tiered_reason)
                        return True, tiered_reason
                except Exception as e:
                    logger.debug("[INSTANT_RATCHET_ERROR] Tiered cash protection failed: %s", str(e)[:100])

        # ===== STEP 1: Check time throttle =====
        time_since_last_mod = (current_time - state.last_sl_modification_time).total_seconds()
        if time_since_last_mod < self.config.min_time_between_mods_seconds:
            # Still in throttle period
            return False, f"Time throttle: {time_since_last_mod:.1f}s < {self.config.min_time_between_mods_seconds}s"

        # ===== STEP 2: Calculate new SL based on side =====
        should_modify, new_sl, reason = self._calculate_new_sl(state, current_price, symbol_info)

        if not should_modify:
            return False, reason

        # ===== STEP 3: Check price movement threshold =====
        price_movement = abs(current_price - state.last_sl_modification_price)
        if price_movement < self.config.min_pip_movement:
            return False, f"Price move {price_movement:.6f} < min {self.config.min_pip_movement:.6f}"

        # ===== STEP 4: Attempt modification =====
        try:
            success = await self.broker.modify_order(
                order_id=ticket,
                sl=new_sl,
                tp=None,  # Don't modify TP
            )

            if success:
                # Record successful modification
                state.current_sl = new_sl
                state.last_sl_modification_time = current_time
                state.last_sl_modification_price = current_price
                state.total_modifications += 1
                state.times_sl_moved += 1

                # Record in history
                state.modification_history.append({
                    "timestamp": current_time.isoformat(),
                    "price": current_price,
                    "new_sl": new_sl,
                    "old_sl": state.current_sl,
                    "profit_pips": self._calculate_profit_pips(state, current_price),
                })

                logger.info(
                    "[TRAILING_SL_UPDATED] %s | Ticket: %s | Side: %s | "
                    "Price: %.5f | New SL: %.5f | Profit: %.1f pips",
                    state.symbol,
                    ticket,
                    state.side,
                    current_price,
                    new_sl,
                    self._calculate_profit_pips(state, current_price),
                )

                return True, f"SL moved to {new_sl:.5f} (profit locked: {reason})"

            else:
                logger.warning(
                    "[TRAILING_SL_MODIFY_FAILED] %s | Ticket: %s | "
                    "Failed to modify SL to %.5f",
                    state.symbol, ticket, new_sl
                )
                return False, "Modification rejected by broker"

        except Exception as e:
            logger.error(
                "[TRAILING_SL_ERROR] %s | Ticket: %s | Error: %s",
                state.symbol, ticket, str(e)[:100]
            )
            return False, f"Error: {str(e)[:50]}"

    async def continuous_sl_check(
        self,
        ticket: str,
        current_price: float,
        buffer_pips: Optional[float] = None,
        symbol_info=None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Continuously tighten the runner SL from live price while respecting broker distance rules.

        Formula:
        - LONG:  SL = Price - (Buffer_Pips * Point * 10)
        - SHORT: SL = Price + (Buffer_Pips * Point * 10)
        """
        if not self._check_autotrading_enabled():
            return False, "AutoTrading disabled in MT5 GUI - modifications blocked"

        if ticket not in self._positions:
            return False, "Position not tracked"

        state = self._positions[ticket]
        current_time = datetime.now()

        if symbol_info is None:
            try:
                import MetaTrader5 as mt5
                symbol_info = mt5.symbol_info(state.symbol)
            except Exception:
                symbol_info = None

        point = float(getattr(symbol_info, "point", 0.0) or 0.0)
        if point <= 0.0:
            point = self._get_pip_value(state.symbol) / 10.0

        buffer_pips = float(buffer_pips if buffer_pips is not None else self.config.buffer_pips)
        buffer_price = buffer_pips * point * 10.0

        if state.side == "LONG":
            proposed_sl = current_price - buffer_price
        else:
            proposed_sl = current_price + buffer_price

        min_dist = self.get_min_dist(state.symbol, symbol_info)
        if state.side == "LONG":
            legal_sl = current_price - min_dist
            if proposed_sl > legal_sl:
                proposed_sl = legal_sl
        else:
            legal_sl = current_price + min_dist
            if proposed_sl < legal_sl:
                proposed_sl = legal_sl

        is_valid, validation_error = self.is_valid_modification(
            ticket=ticket,
            new_sl=proposed_sl,
            side=state.side,
            symbol=state.symbol,
            current_price=current_price,
            symbol_info=symbol_info,
        )
        if not is_valid:
            return False, validation_error or "Runner SL too close to price"

        if state.side == "LONG":
            if proposed_sl <= state.current_sl:
                return False, "Runner SL already tighter"
        else:
            if state.current_sl and proposed_sl >= state.current_sl:
                return False, "Runner SL already tighter"

        time_since_last_mod = (current_time - state.last_sl_modification_time).total_seconds()
        if time_since_last_mod < self.config.min_time_between_mods_seconds:
            return False, f"Time throttle: {time_since_last_mod:.1f}s < {self.config.min_time_between_mods_seconds}s"

        price_movement = abs(current_price - state.last_sl_modification_price)
        if price_movement < self.config.min_pip_movement:
            return False, f"Price move {price_movement:.6f} < min {self.config.min_pip_movement:.6f}"

        old_sl = state.current_sl
        try:
            success = await self.broker.modify_order(
                order_id=ticket,
                sl=proposed_sl,
                tp=None,
            )
            if not success:
                logger.warning(
                    "[TRAILING_SL_MODIFY_FAILED] %s | Ticket: %s | Failed runner update to %.5f",
                    state.symbol,
                    ticket,
                    proposed_sl,
                )
                return False, "Modification rejected by broker"

            state.current_sl = proposed_sl
            state.last_sl_modification_time = current_time
            state.last_sl_modification_price = current_price
            state.total_modifications += 1
            state.times_sl_moved += 1
            state.is_running_as_runner = True
            state.modification_history.append({
                "timestamp": current_time.isoformat(),
                "price": current_price,
                "new_sl": proposed_sl,
                "old_sl": old_sl,
                "profit_pips": self._calculate_profit_pips(state, current_price),
                "mode": "continuous_runner",
            })
            logger.info(
                "[CONTINUOUS_TRAIL_ACTIVE] %s | Ticket: %s | Side: %s | Price: %.5f | New SL: %.5f | Buffer: %.1f pips",
                state.symbol,
                ticket,
                state.side,
                current_price,
                proposed_sl,
                buffer_pips,
            )
            return True, f"Runner SL moved to {proposed_sl:.5f}"
        except Exception as e:
            logger.error(
                "[TRAILING_SL_ERROR] %s | Ticket: %s | Runner error: %s",
                state.symbol,
                ticket,
                str(e)[:100],
            )
            return False, f"Error: {str(e)[:50]}"

    def _calculate_new_sl(
        self,
        state: PositionTrailingState,
        current_price: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """
        Calculate new SL level.

        Returns:
            (should_modify, new_sl, reason)
        """
        if state.side == "LONG":
            return self._calculate_new_sl_long(state, current_price, symbol_info)
        else:
            return self._calculate_new_sl_short(state, current_price, symbol_info)

    def _calculate_new_sl_long(
        self,
        state: PositionTrailingState,
        current_price: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """Calculate new SL for LONG position WITH STOPS_LEVEL validation and snapping."""

        # Track highest price
        if current_price > state.highest_price_long:
            state.highest_price_long = current_price

        # ===== ATR-BASED VOLATILITY BUFFER (NEW) =====
        # Instead of flat 2-point buffer, use 0.1 * ATR
        # This makes buffer wider during high volatility and tighter during quiet markets
        if state.atr_value and state.atr_value > 0:
            buffer = 0.1 * state.atr_value  # Volatility-adaptive buffer
        else:
            # Fallback to config buffer if ATR not available
            buffer = self.config.buffer_pips * self._get_pip_value(state.symbol)
        
        trailing_sl = state.highest_price_long - buffer

        # ===== NEW: DPC TIER TIGHTENING (40/70/90% to TP) =====
        # Handled separately in update_trailing_sl() via _check_dpc_tiered_profit_sniper()
        # This is here for reference; main logic checks tiers BEFORE time throttle

        # ===== ENDZONE TIGHTENING (90% to TP) - Legacy logic kept for reference =====
        # If TP is set, check if we're at 90% progress to TP
        if state.tp_price > 0 and not state.endzone_activated:
            tp_distance = state.tp_price - state.entry_price
            if tp_distance > 0:
                progress_to_tp = (current_price - state.entry_price) / tp_distance
                
                if progress_to_tp >= 0.90:
                    # At 90% mark: lock 85% of current profit immediately
                    pip_value = self._get_pip_value(state.symbol)
                    current_profit_pips = (current_price - state.entry_price) / pip_value
                    endzone_lock_sl = state.entry_price + (0.85 * current_profit_pips * pip_value)
                    
                    # Validate endzone SL
                    is_valid_endzone, _, snapped_endzone = self.is_valid_modification(
                        ticket=state.ticket,
                        new_sl=endzone_lock_sl,
                        side="LONG",
                        symbol=state.symbol,
                        current_price=current_price,
                        symbol_info=symbol_info,
                    )
                    
                    final_endzone_sl = snapped_endzone if snapped_endzone else endzone_lock_sl
                    if is_valid_endzone and final_endzone_sl > state.current_sl:
                        state.endzone_activated = True
                        logger.info(
                            "[PROFIT_SNIPER] %s Ticket: %s | SL moved to %.5f (Progress: 90%%)",
                            state.symbol, state.ticket, final_endzone_sl
                        )
                        return True, final_endzone_sl, f"Endzone 90% activated: locked 85% profit"

        # ===== NEW: STOPS_LEVEL GUARD WITH SNAPPING =====
        # Ensure SL isn't too close to current price; snap if needed
        is_valid, validation_error, snapped_trailing = self.is_valid_modification(
            ticket=state.ticket,
            new_sl=trailing_sl,
            side="LONG",
            symbol=state.symbol,
            current_price=current_price,
            symbol_info=symbol_info,
        )

        if not is_valid:
            return False, None, validation_error or "SL validation failed"
        
        # Use snapped SL if provided
        trailing_sl = snapped_trailing if snapped_trailing else trailing_sl

        # ===== PROFIT LOCK LOGIC =====
        # If in profit and enabled, lock to break-even + fees
        # For LONG: SL = Entry + (Commission + Swap) / Quantity / Pip to convert $ to pips
        profit_pips = (current_price - state.entry_price) / self._get_pip_value(state.symbol)

        if self.config.enable_profit_lock and profit_pips >= self.config.profit_lock_threshold_pips:
            # Lock profit: move SL to entry price + accumulated fees
            # This ensures that when SL is hit, account balance covers all broker costs
            pip_value = self._get_pip_value(state.symbol)
            
            # Convert total fees ($ to pip equivalent)
            # Assume 1 lot = 100,000 units; adjust if quantity is different
            total_fees = state.commission + abs(state.swap)
            if total_fees > 0:
                # Convert $ fee to price offset
                # For forex: 1 pip of EURUSD = ~$10 per 1.0 lot
                # General formula: fee_in_pips = (fee_in_dollars * pip_value) / standard_lot_value
                # Approximation: assume $10 per 1.0 lot = 1 pip
                fee_pips = total_fees / 10.0 if total_fees > 0 else 0
                fee_price_offset = fee_pips * pip_value
            else:
                fee_price_offset = 0
            
            profit_lock_sl = state.entry_price + fee_price_offset

            logger.debug(
                "[PROFIT_LOCK_CALC] %s | Ticket: %s | Entry: %.5f | Commission: %.6f | Swap: %.6f | Fee Offset: %.8f | Lock SL: %.5f",
                state.symbol, state.ticket, state.entry_price, state.commission, state.swap, fee_price_offset, profit_lock_sl
            )

            # ===== ALSO VALIDATE PROFIT LOCK SL =====
            is_valid_lock, lock_error, snapped_lock = self.is_valid_modification(
                ticket=state.ticket,
                new_sl=profit_lock_sl,
                side="LONG",
                symbol=state.symbol,
                current_price=current_price,
                symbol_info=symbol_info,
            )

            profit_lock_sl = snapped_lock if snapped_lock else profit_lock_sl
            if is_valid_lock and profit_lock_sl > trailing_sl:
                if profit_lock_sl > state.current_sl:
                    # Only modify if it improves SL
                    return True, profit_lock_sl, f"Profit locked (fees: ${total_fees:.2f})"

        # Only modify if new SL is better (higher) than current
        if trailing_sl > state.current_sl:
            return True, trailing_sl, "Trailing SL moved up"

        return False, None, "SL already optimal"

    def _calculate_new_sl_short(
        self,
        state: PositionTrailingState,
        current_price: float,
        symbol_info=None,
    ) -> Tuple[bool, Optional[float], str]:
        """Calculate new SL for SHORT position WITH STOPS_LEVEL validation and snapping."""

        # Track lowest price
        if current_price < state.lowest_price_short:
            state.lowest_price_short = current_price

        # ===== ATR-BASED VOLATILITY BUFFER (NEW) =====
        # Instead of flat 2-point buffer, use 0.1 * ATR
        # This makes buffer wider during high volatility and tighter during quiet markets
        if state.atr_value and state.atr_value > 0:
            buffer = 0.1 * state.atr_value  # Volatility-adaptive buffer
        else:
            # Fallback to config buffer if ATR not available
            buffer = self.config.buffer_pips * self._get_pip_value(state.symbol)
        
        trailing_sl = state.lowest_price_short + buffer

        # ===== NEW: DPC TIER TIGHTENING (40/70/90% to TP) =====
        # Handled separately in update_trailing_sl() via _check_dpc_tiered_profit_sniper()
        # This is here for reference; main logic checks tiers BEFORE time throttle

        # ===== ENDZONE TIGHTENING (90% to TP) - Legacy logic kept for reference =====
        # If TP is set, check if we're at 90% progress to TP
        if state.tp_price > 0 and not state.endzone_activated:
            tp_distance = state.entry_price - state.tp_price
            if tp_distance > 0:
                progress_to_tp = (state.entry_price - current_price) / tp_distance
                
                if progress_to_tp >= 0.90:
                    # At 90% mark: lock 85% of current profit immediately
                    pip_value = self._get_pip_value(state.symbol)
                    current_profit_pips = (state.entry_price - current_price) / pip_value
                    endzone_lock_sl = state.entry_price - (0.85 * current_profit_pips * pip_value)
                    
                    # Validate endzone SL
                    is_valid_endzone, _, snapped_endzone = self.is_valid_modification(
                        ticket=state.ticket,
                        new_sl=endzone_lock_sl,
                        side="SHORT",
                        symbol=state.symbol,
                        current_price=current_price,
                        symbol_info=symbol_info,
                    )
                    
                    final_endzone_sl = snapped_endzone if snapped_endzone else endzone_lock_sl
                    if is_valid_endzone and final_endzone_sl < state.current_sl:
                        state.endzone_activated = True
                        logger.info(
                            "[PROFIT_SNIPER] %s Ticket: %s | SL moved to %.5f (Progress: 90%%)",
                            state.symbol, state.ticket, final_endzone_sl
                        )
                        return True, final_endzone_sl, f"Endzone 90% activated: locked 85% profit"

        # ===== NEW: STOPS_LEVEL GUARD WITH SNAPPING =====
        is_valid, validation_error, snapped_trailing = self.is_valid_modification(
            ticket=state.ticket,
            new_sl=trailing_sl,
            side="SHORT",
            symbol=state.symbol,
            current_price=current_price,
            symbol_info=symbol_info,
        )

        if not is_valid:
            return False, None, validation_error or "SL validation failed"
        
        # Use snapped SL if provided
        trailing_sl = snapped_trailing if snapped_trailing else trailing_sl

        # ===== PROFIT LOCK LOGIC =====
        profit_pips = (state.entry_price - current_price) / self._get_pip_value(state.symbol)

        if self.config.enable_profit_lock and profit_pips >= self.config.profit_lock_threshold_pips:
            # Lock profit: move SL to entry price - accumulated fees
            # For SHORT: SL = Entry - (Commission + Swap) / Quantity / Pip
            pip_value = self._get_pip_value(state.symbol)
            
            # Convert total fees ($ to pip equivalent)
            total_fees = state.commission + abs(state.swap)
            if total_fees > 0:
                fee_pips = total_fees / 10.0 if total_fees > 0 else 0
                fee_price_offset = fee_pips * pip_value
            else:
                fee_price_offset = 0
            
            profit_lock_sl = state.entry_price - fee_price_offset

            logger.debug(
                "[PROFIT_LOCK_CALC] %s | Ticket: %s | Entry: %.5f | Commission: %.6f | Swap: %.6f | Fee Offset: %.8f | Lock SL: %.5f",
                state.symbol, state.ticket, state.entry_price, state.commission, state.swap, fee_price_offset, profit_lock_sl
            )

            # ===== ALSO VALIDATE PROFIT LOCK SL =====
            is_valid_lock, lock_error, snapped_lock = self.is_valid_modification(
                ticket=state.ticket,
                new_sl=profit_lock_sl,
                side="SHORT",
                symbol=state.symbol,
                current_price=current_price,
                symbol_info=symbol_info,
            )

            profit_lock_sl = snapped_lock if snapped_lock else profit_lock_sl
            if is_valid_lock and profit_lock_sl < trailing_sl:
                if profit_lock_sl < state.current_sl:
                    # Only modify if it improves SL
                    return True, profit_lock_sl, f"Profit locked (fees: ${total_fees:.2f})"

        # Only modify if new SL is better (lower) than current
        if trailing_sl < state.current_sl:
            return True, trailing_sl, "Trailing SL moved down"

        return False, None, "SL already optimal"

    @staticmethod
    def _get_pip_value(symbol: str) -> float:
        """Get pip value for symbol (adjust for your pairs)."""
        # Default: forex 5-decimal = 0.0001
        if symbol.endswith("JPY"):
            return 0.01  # 3-decimal
        elif symbol in ["BTC/USD", "ETH/USD"]:
            return 0.1  # Crypto example
        return 0.0001  # Default 5-decimal

    @staticmethod
    def _calculate_profit_pips(state: PositionTrailingState, current_price: float) -> float:
        """Calculate current profit in pips."""
        pip_value = DynamicTrailingSLManager._get_pip_value(state.symbol)

        if state.side == "LONG":
            return (current_price - state.entry_price) / pip_value
        else:
            return (state.entry_price - current_price) / pip_value

    def get_position_state(self, ticket: str) -> Optional[PositionTrailingState]:
        """Get tracking state for a position."""
        return self._positions.get(ticket)

    def get_all_positions(self) -> Dict[str, PositionTrailingState]:
        """Get all tracked positions."""
        return dict(self._positions)

    def get_modification_history(self, ticket: str) -> List[Dict]:
        """Get modification history for a position."""
        state = self._positions.get(ticket)
        return state.modification_history if state else []

    def log_diagnostics(self) -> None:
        """Log diagnostic info about all tracked positions."""
        if not self._positions:
            logger.info("[TRAILING_SL_DIAG] No positions tracked")
            return

        logger.info("[TRAILING_SL_DIAG] ===== Trailing SL Status =====")
        for ticket, state in self._positions.items():
            logger.info(
                "  Ticket: %s | Symbol: %s | Side: %s | "
                "Mods: %d | SL: %.5f | Profit Locked: %s",
                ticket,
                state.symbol,
                state.side,
                state.total_modifications,
                state.current_sl,
                state.profit_locked_at_price is not None,
            )


# ============================================================================
# Integration Helper: Main Loop Update
# ============================================================================

async def update_trailing_stops_for_all_positions(
    manager: DynamicTrailingSLManager,
    broker,
    symbols: List[str],
) -> Dict[str, Tuple[bool, str]]:
    """
    Main loop integration: Update trailing SL for all tracked positions.

    Usage in your main trading loop:
        results = await update_trailing_stops_for_all_positions(
            manager=trailing_sl_manager,
            broker=your_broker,
            symbols=["EURUSD", "GBPUSD"],
        )

        for ticket, (modified, reason) in results.items():
            if modified:
                logger.info(f"Trailing SL updated for {ticket}: {reason}")
    """
    results = {}

    for symbol in symbols:
        try:
            # Get current price from broker
            tick = broker.get_tick(symbol)
            if not tick:
                logger.warning(f"No tick data for {symbol}")
                continue

            current_price = (tick.bid + tick.ask) / 2  # Mid price

            # Update all positions for this symbol
            for ticket, state in manager.get_all_positions().items():
                if state.symbol == symbol:
                    modified, reason = await manager.update_trailing_sl(ticket, current_price)
                    results[ticket] = (modified, reason)

        except Exception as e:
            logger.error(f"Error updating trailing SL for {symbol}: {e}")

    return results


# ============================================================================
# Example Usage
# ============================================================================

async def example_usage():
    """
    Example showing how to use DynamicTrailingSLManager.
    """
    # Initialize manager
    config = TrailingConfig(
        buffer_pips=5,  # Trail 5 pips behind
        min_time_between_mods_seconds=5,
        min_pip_movement=0.001,  # 10 pips before update
        enable_profit_lock=True,
        profit_lock_threshold_pips=20,
    )

    manager = DynamicTrailingSLManager(broker=None, config=config)

    # Track a position
    manager.track_position(
        ticket="12345",
        symbol="EURUSD",
        side="LONG",
        entry_price=1.0850,
        current_sl=1.0800,
    )

    # Simulate price updates
    prices = [1.0860, 1.0870, 1.0875, 1.0880, 1.0870, 1.0850]

    for current_price in prices:
        modified, reason = await manager.update_trailing_sl("12345", current_price)
        print(f"Price: {current_price:.5f} | Modified: {modified} | Reason: {reason}")

    # View history
    manager.log_diagnostics()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(example_usage())

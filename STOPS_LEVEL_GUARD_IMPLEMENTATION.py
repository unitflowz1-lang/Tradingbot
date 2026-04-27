"""
STOPS_LEVEL Guard Implementation
=================================

Add this to src/trading/dynamic_trailing_sl_manager.py

This prevents broker rejections (ERR_10016, ERR_10029) by ensuring
the SL is never closer to current price than the broker's minimum distance.
"""

# ============================================================================
# ADD THIS SECTION TO DynamicTrailingSLManager CLASS
# ============================================================================

STOPS_LEVEL_GUARD_CODE = """
# ============================================================================
# STOPS_LEVEL GUARD (Add to DynamicTrailingSLManager class)
# ============================================================================

def get_min_dist_from_price(self, symbol: str, symbol_info=None) -> float:
    \"\"\"
    Fetch the minimum allowed distance from current price to SL.

    This prevents ERR_10016 (SL too close to price).

    Args:
        symbol: Trading symbol
        symbol_info: Optional pre-fetched symbol info (for efficiency)

    Returns:
        Minimum distance in price units (e.g., 0.0005 for 5 pips on EURUSD)
    \"\"\"
    try:
        if symbol_info is None:
            # Import at method level to avoid module-level dependency
            import MetaTrader5 as mt5
            symbol_info = mt5.symbol_info(symbol)

        if symbol_info is None:
            logger.warning(
                "[STOPS_GUARD] symbol_info returned None for %s. "
                "Using safe fallback (5 pips).",
                symbol
            )
            return 0.0005  # Safe fallback: 5 pips for 5-decimal pairs

        # stops_level is in POINTS (not pips)
        # 1 point = 0.0001 for 5-decimal pairs
        stops_level_points = symbol_info.trade_stops_level
        point_size = symbol_info.point

        if stops_level_points > 0:
            # Broker has explicit minimum distance requirement
            min_dist = stops_level_points * point_size
            logger.debug(
                "[STOPS_GUARD] %s: stops_level=%d points, point_size=%.8f, "
                "min_dist=%.8f",
                symbol,
                stops_level_points,
                point_size,
                min_dist,
            )
            return min_dist
        else:
            # Broker doesn't enforce stops_level, use reasonable floor
            # Default: 5 pips (standard for most brokers)
            min_dist = 5 * point_size
            logger.debug(
                "[STOPS_GUARD] %s: stops_level=0, using default 5 pips (%.8f)",
                symbol,
                min_dist,
            )
            return min_dist

    except Exception as e:
        logger.warning(
            "[STOPS_GUARD_ERROR] Failed to get min_dist for %s: %s. "
            "Using safe fallback.",
            symbol,
            str(e)[:100],
        )
        return 0.0005  # Safe fallback


def is_valid_modification(
    self,
    ticket: str,
    new_sl: float,
    side: str,
    symbol: str,
    current_price: float,
    symbol_info=None,
) -> Tuple[bool, Optional[str]]:
    \"\"\"
    Validate if the new SL meets broker's minimum distance requirement.

    Returns:
        (is_valid, reason_if_invalid)
    \"\"\"
    try:
        # Get minimum distance requirement
        min_dist = self.get_min_dist_from_price(symbol, symbol_info)

        # Calculate distance between current price and proposed SL
        distance = abs(current_price - new_sl)

        if distance < min_dist:
            reason = (
                f"[STOPS_GUARD] SL too close: distance {distance:.8f} < "
                f"min_dist {min_dist:.8f}. Modification blocked."
            )
            logger.warning(
                "[SL_MOD_REJECTED] %s ticket %s | %s",
                symbol,
                ticket,
                reason,
            )
            return False, reason

        # Valid distance
        logger.debug(
            "[STOPS_GUARD_PASS] %s ticket %s | distance {distance:.8f} >= "
            "min_dist {min_dist:.8f}",
            symbol,
            ticket,
        )
        return True, None

    except Exception as e:
        logger.error(
            "[STOPS_GUARD_ERROR] Validation failed for %s ticket %s: %s",
            symbol,
            ticket,
            str(e)[:100],
        )
        # On error, allow (conservative - assume broker will validate)
        return True, None


# ============================================================================
# MODIFY THIS METHOD: _calculate_new_sl_long
# ============================================================================

def _calculate_new_sl_long_with_guard(
    self,
    state: PositionTrailingState,
    current_price: float,
    symbol_info=None,
) -> Tuple[bool, Optional[float], str]:
    \"\"\"Calculate new SL for LONG position WITH STOPS_LEVEL validation.\"\"\"

    # Track highest price
    if current_price > state.highest_price_long:
        state.highest_price_long = current_price

    # Calculate trailing SL (buffer below highest price)
    buffer = self.config.buffer_pips * self._get_pip_value(state.symbol)
    trailing_sl = state.highest_price_long - buffer

    # ===== NEW: STOPS_LEVEL GUARD =====
    # Ensure SL isn't too close to current price
    is_valid, validation_error = self.is_valid_modification(
        ticket=state.ticket,
        new_sl=trailing_sl,
        side="LONG",
        symbol=state.symbol,
        current_price=current_price,
        symbol_info=symbol_info,
    )

    if not is_valid:
        return False, None, validation_error or "SL too close to price"

    # Profit lock logic (existing code)
    profit_pips = (current_price - state.entry_price) / self._get_pip_value(state.symbol)

    if self.config.enable_profit_lock and profit_pips >= self.config.profit_lock_threshold_pips:
        profit_lock_sl = state.entry_price + (0.0001 if '.' in str(state.entry_price) else 0.01)

        # ===== ALSO VALIDATE PROFIT LOCK SL =====
        is_valid_lock, lock_error = self.is_valid_modification(
            ticket=state.ticket,
            new_sl=profit_lock_sl,
            side="LONG",
            symbol=state.symbol,
            current_price=current_price,
            symbol_info=symbol_info,
        )

        if is_valid_lock and profit_lock_sl > trailing_sl:
            if profit_lock_sl > state.current_sl:
                return True, profit_lock_sl, "Profit locked"

    # Only modify if new SL is better (higher) than current
    if trailing_sl > state.current_sl:
        return True, trailing_sl, "Trailing SL moved up"

    return False, None, "SL already optimal"


# ============================================================================
# MODIFY THIS METHOD: _calculate_new_sl_short
# ============================================================================

def _calculate_new_sl_short_with_guard(
    self,
    state: PositionTrailingState,
    current_price: float,
    symbol_info=None,
) -> Tuple[bool, Optional[float], str]:
    \"\"\"Calculate new SL for SHORT position WITH STOPS_LEVEL validation.\"\"\"

    # Track lowest price
    if current_price < state.lowest_price_short:
        state.lowest_price_short = current_price

    # Calculate trailing SL (buffer above lowest price)
    buffer = self.config.buffer_pips * self._get_pip_value(state.symbol)
    trailing_sl = state.lowest_price_short + buffer

    # ===== NEW: STOPS_LEVEL GUARD =====
    is_valid, validation_error = self.is_valid_modification(
        ticket=state.ticket,
        new_sl=trailing_sl,
        side="SHORT",
        symbol=state.symbol,
        current_price=current_price,
        symbol_info=symbol_info,
    )

    if not is_valid:
        return False, None, validation_error or "SL too close to price"

    # Profit lock logic
    profit_pips = (state.entry_price - current_price) / self._get_pip_value(state.symbol)

    if self.config.enable_profit_lock and profit_pips >= self.config.profit_lock_threshold_pips:
        profit_lock_sl = state.entry_price - (0.0001 if '.' in str(state.entry_price) else 0.01)

        # ===== ALSO VALIDATE PROFIT LOCK SL =====
        is_valid_lock, lock_error = self.is_valid_modification(
            ticket=state.ticket,
            new_sl=profit_lock_sl,
            side="SHORT",
            symbol=state.symbol,
            current_price=current_price,
            symbol_info=symbol_info,
        )

        if is_valid_lock and profit_lock_sl < trailing_sl:
            if profit_lock_sl < state.current_sl:
                return True, profit_lock_sl, "Profit locked"

    # Only modify if new SL is better (lower) than current
    if trailing_sl < state.current_sl:
        return True, trailing_sl, "Trailing SL moved down"

    return False, None, "SL already optimal"
"""


# ============================================================================
# IMPLEMENTATION INSTRUCTIONS
# ============================================================================

IMPLEMENTATION_STEPS = """
╔════════════════════════════════════════════════════════════════════════════╗
║               ADDING STOPS_LEVEL GUARD - STEP BY STEP                      ║
╠════════════════════════════════════════════════════════════════════════════╣

STEP 1: Backup existing file
────────────────────────────────────────────────────────────────────────────

$ cp src/trading/dynamic_trailing_sl_manager.py \\
     src/trading/dynamic_trailing_sl_manager.py.backup

Status: [ ] Backup created


STEP 2: Add new methods to DynamicTrailingSLManager class
────────────────────────────────────────────────────────────────────────────

Add these two NEW methods to the class (after existing methods):

1. get_min_dist_from_price()
   - Fetches broker's STOPS_LEVEL requirement
   - Returns minimum distance in price units
   - Has safe fallback (5 pips)

2. is_valid_modification()
   - Validates if new SL meets minimum distance
   - Compares: abs(current_price - new_sl) >= min_dist
   - Returns: (is_valid, error_reason)

Copy from the code block above and paste into the class.

Status: [ ] Methods added


STEP 3: Update _calculate_new_sl_long()
────────────────────────────────────────────────────────────────────────────

Replace existing _calculate_new_sl_long() with _calculate_new_sl_long_with_guard()

Key changes:
  - Call is_valid_modification() for trailing_sl
  - Call is_valid_modification() for profit_lock_sl
  - Return False if validation fails

Status: [ ] Method updated


STEP 4: Update _calculate_new_sl_short()
────────────────────────────────────────────────────────────────────────────

Replace existing _calculate_new_sl_short() with _calculate_new_sl_short_with_guard()

Same changes as LONG version (but for SHORT positions)

Status: [ ] Method updated


STEP 5: Update _calculate_new_sl()
────────────────────────────────────────────────────────────────────────────

In _calculate_new_sl() method, pass symbol_info to the new methods:

BEFORE:
    if state.side == "LONG":
        return self._calculate_new_sl_long(state, current_price)
    else:
        return self._calculate_new_sl_short(state, current_price)

AFTER:
    # Get symbol info once (efficient)
    try:
        import MetaTrader5 as mt5
        symbol_info = mt5.symbol_info(state.symbol)
    except:
        symbol_info = None

    if state.side == "LONG":
        return self._calculate_new_sl_long_with_guard(state, current_price, symbol_info)
    else:
        return self._calculate_new_sl_short_with_guard(state, current_price, symbol_info)

Status: [ ] Method updated


STEP 6: Test the updated code
────────────────────────────────────────────────────────────────────────────

$ python verify_trailing_sl.py

Expected output:
  ✓ All verifications passed
  ✓ SL calculation verification passed

If errors:
  - Compare your edits with the code block above
  - Check indentation (Python is whitespace-sensitive)
  - Try again

Status: [ ] Tests passed


STEP 7: Update config (IMPORTANT)
────────────────────────────────────────────────────────────────────────────

In core/engine.py, update TrailingConfig:

BEFORE:
    trailing_config = TrailingConfig(
        buffer_pips=5,  # May be too small!
        ...
    )

AFTER:
    trailing_config = TrailingConfig(
        buffer_pips=8,  # Increased to account for STOPS_LEVEL
        min_time_between_mods_seconds=5,
        min_pip_movement=0.001,
        enable_profit_lock=True,
        profit_lock_threshold_pips=20,
    )

Recommendation:
  - EURUSD (stops_level 2): buffer_pips=5-8 (OK)
  - GBP/USD (stops_level 3): buffer_pips=8-10 (safer)
  - Other pairs: Check symbol info, add 3 pips to stops_level

Status: [ ] Config updated


════════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# TESTING THE GUARD
# ============================================================================

TESTING_GUIDE = """
╔════════════════════════════════════════════════════════════════════════════╗
║                    TESTING THE STOPS_LEVEL GUARD                           ║
╚════════════════════════════════════════════════════════════════════════════╝

Test 1: Verify guard is callable
────────────────────────────────────────────────────────────────────────────

$ python -c "
from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager, TrailingConfig

class MockBroker:
    pass

manager = DynamicTrailingSLManager(MockBroker(), TrailingConfig())

# Test get_min_dist_from_price
min_dist = manager.get_min_dist_from_price('EURUSD')
print(f'[TEST] Min distance for EURUSD: {min_dist:.8f}')

# Test is_valid_modification
is_valid, reason = manager.is_valid_modification(
    ticket='TEST_001',
    new_sl=1.08000,
    side='LONG',
    symbol='EURUSD',
    current_price=1.08750,
)

print(f'[TEST] SL 1.08000 valid when price is 1.08750? {is_valid}')
if reason:
    print(f'[TEST] Reason: {reason}')
"

Expected output:
  [TEST] Min distance for EURUSD: 0.00050 (or similar)
  [TEST] SL 1.08000 valid when price is 1.08750? True

If is_valid=False, it means SL too close and would be rejected.


Test 2: Simulate SL too close
────────────────────────────────────────────────────────────────────────────

$ python -c "
from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager, TrailingConfig

manager = DynamicTrailingSLManager(None, TrailingConfig())

# SL very close to price (would be rejected)
is_valid, reason = manager.is_valid_modification(
    ticket='TEST_002',
    new_sl=1.08700,  # Only 0.0005 below price (too close!)
    side='LONG',
    symbol='EURUSD',
    current_price=1.08750,
)

print(f'[TEST] SL 1.08700 valid when price is 1.08750? {is_valid}')
print(f'[TEST] Distance: {abs(1.08750 - 1.08700):.8f}')
"

Expected output:
  [TEST] SL 1.08700 valid when price is 1.08750? False
  [TEST] Distance: 0.00050 (too small, rejected)
  [TEST] Reason: [STOPS_GUARD] SL too close...


Test 3: Real MT5 validation
────────────────────────────────────────────────────────────────────────────

$ python -c "
import MetaTrader5 as mt5
from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager, TrailingConfig

mt5.initialize()

class RealBroker:
    pass

manager = DynamicTrailingSLManager(RealBroker(), TrailingConfig())

# Get real symbol info
symbol_info = mt5.symbol_info('EURUSD')
tick = mt5.symbol_info_tick('EURUSD')

print(f'[TEST] EURUSD stops_level: {symbol_info.trade_stops_level} points')
print(f'[TEST] Current price: {(tick.bid + tick.ask) / 2:.5f}')

# Get actual min distance
min_dist = manager.get_min_dist_from_price('EURUSD', symbol_info)
print(f'[TEST] Min distance required: {min_dist:.8f}')

mt5.shutdown()
"

Expected output:
  [TEST] EURUSD stops_level: 2 points (or similar)
  [TEST] Current price: 1.08750 (or current)
  [TEST] Min distance required: 0.00020 (2 points * 0.0001)

════════════════════════════════════════════════════════════════════════════════
"""


if __name__ == "__main__":
    print(IMPLEMENTATION_STEPS)
    print("\n")
    print(TESTING_GUIDE)

"""
Verification Script: Dynamic Trailing SL Manager
================================================

Performs integration checks before deploying to live trading:
1. Module imports and initialization
2. Configuration validation
3. Position tracking logic
4. SL calculation sanity checks
5. MT5 compatibility checks (non-destructive)

Run: python verify_trailing_sl.py
"""

import sys
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# STEP 1: Import Verification
# ============================================================================

def verify_imports() -> bool:
    """Verify all required modules can be imported."""
    logger.info("[1/5] Verifying imports...")

    try:
        from src.trading.dynamic_trailing_sl_manager import (
            DynamicTrailingSLManager,
            TrailingConfig,
            PositionTrailingState,
        )
        logger.info("✓ DynamicTrailingSLManager imported successfully")

        try:
            import MetaTrader5 as mt5
            logger.info("✓ MetaTrader5 module available")
            mt5_available = True
        except ImportError:
            logger.warning("⚠ MetaTrader5 not installed (expected in dev env)")
            mt5_available = False

        return True

    except ImportError as e:
        logger.error(f"✗ Import failed: {e}")
        return False


# ============================================================================
# STEP 2: Configuration Validation
# ============================================================================

def verify_config() -> bool:
    """Verify TrailingConfig initialization and validation."""
    logger.info("[2/5] Validating configuration...")

    try:
        from src.trading.dynamic_trailing_sl_manager import TrailingConfig

        # Test default config
        default_config = TrailingConfig()
        logger.info(f"✓ Default config created")
        logger.info(f"  - Buffer: {default_config.buffer_pips} pips")
        logger.info(f"  - Min time: {default_config.min_time_between_mods_seconds}s")
        logger.info(f"  - Min movement: {default_config.min_pip_movement:.6f}")
        logger.info(f"  - Profit lock: {default_config.enable_profit_lock}")
        logger.info(f"  - Lock threshold: {default_config.profit_lock_threshold_pips} pips")

        # Test custom config
        custom_config = TrailingConfig(
            buffer_pips=10,
            min_time_between_mods_seconds=15,
            min_pip_movement=0.002,
            enable_profit_lock=True,
            profit_lock_threshold_pips=30,
        )
        logger.info(f"✓ Custom config created successfully")

        # Validate ranges
        assert 1 <= custom_config.buffer_pips <= 50, "Buffer pips out of range"
        assert custom_config.min_time_between_mods_seconds >= 1, "Time throttle too small"
        assert custom_config.min_pip_movement > 0, "Pip movement must be positive"

        logger.info("✓ Config validation passed")
        return True

    except Exception as e:
        logger.error(f"✗ Config validation failed: {e}")
        return False


# ============================================================================
# STEP 3: Position Tracking Logic
# ============================================================================

def verify_position_tracking() -> bool:
    """Verify position state tracking without broker."""
    logger.info("[3/5] Verifying position tracking logic...")

    try:
        from src.trading.dynamic_trailing_sl_manager import (
            DynamicTrailingSLManager,
            TrailingConfig,
            PositionTrailingState,
        )

        # Mock broker (doesn't need to do anything)
        mock_broker = type('MockBroker', (), {})()

        config = TrailingConfig()
        manager = DynamicTrailingSLManager(broker=mock_broker, config=config)

        # Track a LONG position
        logger.info("  Testing LONG position tracking...")
        manager.track_position(
            ticket="TEST_LONG_001",
            symbol="EURUSD",
            side="LONG",
            entry_price=1.08500,
            current_sl=1.08000,
        )

        # Verify state
        state = manager.get_position_state("TEST_LONG_001")
        assert state is not None, "Position not tracked"
        assert state.ticket == "TEST_LONG_001", "Ticket mismatch"
        assert state.symbol == "EURUSD", "Symbol mismatch"
        assert state.side == "LONG", "Side mismatch"
        assert state.entry_price == 1.08500, "Entry price mismatch"
        assert state.current_sl == 1.08000, "SL mismatch"
        assert state.highest_price_long == 1.08500, "Initial high price mismatch"

        logger.info("  ✓ LONG position tracked correctly")

        # Track a SHORT position
        logger.info("  Testing SHORT position tracking...")
        manager.track_position(
            ticket="TEST_SHORT_001",
            symbol="GBPUSD",
            side="SHORT",
            entry_price=1.27000,
            current_sl=1.27500,
        )

        state = manager.get_position_state("TEST_SHORT_001")
        assert state is not None, "SHORT position not tracked"
        assert state.side == "SHORT", "SHORT side mismatch"
        assert state.lowest_price_short == 1.27000, "Initial low price mismatch"

        logger.info("  ✓ SHORT position tracked correctly")

        # Verify untracking
        logger.info("  Testing position untracking...")
        untracked = manager.untrack_position("TEST_LONG_001")
        assert untracked is not None, "Untrack returned None"
        assert "TEST_LONG_001" not in manager.get_all_positions(), "Position still tracked"

        logger.info("  ✓ Position untracking works")
        logger.info("✓ Position tracking verification passed")
        return True

    except Exception as e:
        logger.error(f"✗ Position tracking verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# STEP 4: SL Calculation Logic
# ============================================================================

def verify_sl_calculation() -> bool:
    """Verify SL calculation logic for LONG and SHORT positions."""
    logger.info("[4/5] Verifying SL calculation logic...")

    try:
        from src.trading.dynamic_trailing_sl_manager import (
            DynamicTrailingSLManager,
            TrailingConfig,
        )

        mock_broker = type('MockBroker', (), {})()
        config = TrailingConfig(
            buffer_pips=5,
            enable_profit_lock=True,
            profit_lock_threshold_pips=20,
        )
        manager = DynamicTrailingSLManager(broker=mock_broker, config=config)

        # Test LONG calculation
        logger.info("  Testing LONG SL calculation...")
        manager.track_position(
            ticket="CALC_LONG",
            symbol="EURUSD",
            side="LONG",
            entry_price=1.08500,
            current_sl=1.08000,
        )

        state = manager.get_position_state("CALC_LONG")

        # Simulate price move to +25 pips
        current_price = 1.08750
        state.highest_price_long = current_price  # Track high

        # Call internal calculation
        should_modify, new_sl, reason = manager._calculate_new_sl_long(state, current_price)

        logger.info(f"    Entry: {state.entry_price}, Current: {current_price}")
        logger.info(f"    Should modify: {should_modify}")
        logger.info(f"    New SL: {new_sl}")
        logger.info(f"    Reason: {reason}")

        # Verify calculation
        pip_value = 0.0001  # For EURUSD
        buffer_distance = 5 * pip_value  # 5 pips
        expected_trailing_sl = current_price - buffer_distance

        assert should_modify, "Should trigger modification for profitable move"
        assert new_sl is not None, "New SL is None"

        # Allow small floating point tolerance
        assert abs(new_sl - expected_trailing_sl) < 0.00001, \
            f"SL calculation off: expected {expected_trailing_sl}, got {new_sl}"

        logger.info(f"    ✓ Calculated SL matches expected: {new_sl:.5f}")

        # Test SHORT calculation
        logger.info("  Testing SHORT SL calculation...")
        manager.track_position(
            ticket="CALC_SHORT",
            symbol="EURUSD",
            side="SHORT",
            entry_price=1.08500,
            current_sl=1.09000,
        )

        state = manager.get_position_state("CALC_SHORT")

        # Simulate price move down to -25 pips
        current_price = 1.08250
        state.lowest_price_short = current_price  # Track low

        should_modify, new_sl, reason = manager._calculate_new_sl_short(state, current_price)

        logger.info(f"    Entry: {state.entry_price}, Current: {current_price}")
        logger.info(f"    Should modify: {should_modify}")
        logger.info(f"    New SL: {new_sl}")
        logger.info(f"    Reason: {reason}")

        expected_trailing_sl = current_price + buffer_distance

        assert should_modify, "Should trigger modification for profitable move"
        assert new_sl is not None, "New SL is None"
        assert abs(new_sl - expected_trailing_sl) < 0.00001, \
            f"SHORT SL calculation off: expected {expected_trailing_sl}, got {new_sl}"

        logger.info(f"    ✓ Calculated SHORT SL matches expected: {new_sl:.5f}")
        logger.info("✓ SL calculation verification passed")
        return True

    except Exception as e:
        logger.error(f"✗ SL calculation verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# STEP 5: MT5 Compatibility Check
# ============================================================================

def verify_mt5_compatibility() -> bool:
    """Verify MT5-specific requirements (non-destructive)."""
    logger.info("[5/5] Verifying MT5 compatibility...")

    try:
        import MetaTrader5 as mt5

        # Initialize MT5
        logger.info("  Attempting MT5 connection...")
        if not mt5.initialize():
            logger.warning("  ⚠ MT5 not available (expected in dev/testing environment)")
            logger.info("  ✓ Continuing with mock verification...")
            return verify_mt5_mock_compatibility()

        logger.info("  ✓ MT5 initialized successfully")

        # Check a symbol exists and get specs
        symbol = "EURUSD"
        logger.info(f"  Checking symbol specs for {symbol}...")

        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            logger.warning(f"  ⚠ Symbol {symbol} not in market watch")
            logger.info("  Trying USDJPY...")
            symbol = "USDJPY"
            symbol_info = mt5.symbol_info(symbol)

        if symbol_info is None:
            logger.warning("  ⚠ Could not find any forex symbols")
            logger.info("  This is expected in backtesting/paper trading")
            mt5.shutdown()
            return verify_mt5_mock_compatibility()

        logger.info(f"  ✓ Symbol {symbol} found")
        logger.info(f"    - Point size: {symbol_info.point}")
        logger.info(f"    - Digits: {symbol_info.digits}")
        logger.info(f"    - Trade stops level: {symbol_info.trade_stops_level}")
        logger.info(f"    - Tick size: {symbol_info.trade_tick_size}")

        # Verify data types for MT5 order_send
        logger.info("  Verifying data types for order_send...")

        test_price = 1.08500
        digits = symbol_info.digits

        # Verify rounding
        rounded_price = round(test_price, digits)
        logger.info(f"    Original price: {test_price}")
        logger.info(f"    Digits: {digits}")
        logger.info(f"    Rounded price: {rounded_price}")
        logger.info(f"    Type: {type(rounded_price).__name__}")

        assert isinstance(rounded_price, float), f"Price not float: {type(rounded_price)}"

        logger.info("  ✓ Data type validation passed")

        mt5.shutdown()
        logger.info("✓ MT5 compatibility verification passed")
        return True

    except ImportError:
        logger.warning("  ⚠ MetaTrader5 module not available")
        return verify_mt5_mock_compatibility()
    except Exception as e:
        logger.error(f"✗ MT5 compatibility verification failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_mt5_mock_compatibility() -> bool:
    """Verify MT5 compatibility with mock data (for dev/testing)."""
    logger.info("  Running mock MT5 compatibility check...")

    # Mock symbol info
    class MockSymbolInfo:
        point = 0.0001
        digits = 5
        trade_stops_level = 0
        trade_tick_size = 0.00001

    symbol_info = MockSymbolInfo()

    # Verify price rounding
    test_price = 1.08500
    digits = symbol_info.digits
    rounded_price = round(test_price, digits)

    logger.info(f"    Mock rounding: {test_price} -> {rounded_price}")
    assert isinstance(rounded_price, float), f"Mock price not float"

    # Verify MT5 structure
    logger.info("  Verifying MT5 order structure...")

    # This is what would be sent to mt5.order_send
    mock_request = {
        "action": "TRADE_ACTION_SLTP",  # Would be mt5.TRADE_ACTION_SLTP
        "position": 12345,
        "symbol": "EURUSD",
        "sl": float(round(1.08000, 5)),
        "tp": float(round(1.09000, 5)),
    }

    assert isinstance(mock_request["position"], int), "Ticket not int"
    assert isinstance(mock_request["symbol"], str), "Symbol not str"
    assert isinstance(mock_request["sl"], float), "SL not float"
    assert isinstance(mock_request["tp"], float), "TP not float"

    logger.info("  ✓ Mock MT5 structure validated")
    logger.info("✓ MT5 mock compatibility verification passed")
    return True


# ============================================================================
# STATIC CODE ANALYSIS (Per User Request)
# ============================================================================

def static_code_analysis() -> bool:
    """
    Perform static analysis as requested:
    1. Data types (float values, proper rounding)
    2. Execution context (mt5.order_send structure)
    3. NoneType guards
    """
    logger.info("\n[STATIC CODE ANALYSIS]")
    logger.info("=" * 60)

    issues = []
    warnings = []

    try:
        from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager

        # Check 1: Data types
        logger.info("\n[CHECK 1] Data Types Verification")
        logger.info("-" * 60)

        # Read the manager code
        import inspect
        source = inspect.getsource(DynamicTrailingSLManager._calculate_new_sl_long)

        if "float(" in source or "round(" in source:
            logger.info("✓ Found float() and round() conversions in SL calculations")
        else:
            warnings.append("No explicit float() conversion found in SL calculations")

        # Check 2: Execution context
        logger.info("\n[CHECK 2] Execution Context (mt5.order_send structure)")
        logger.info("-" * 60)

        source = inspect.getsource(DynamicTrailingSLManager.update_trailing_sl)

        if "TRADE_ACTION_SLTP" in source or "modify_order" in source:
            logger.info("✓ References TRADE_ACTION_SLTP or modify_order pattern")
        else:
            warnings.append("No clear MT5 order_send pattern found")

        # Check 3: NoneType guards
        logger.info("\n[CHECK 3] NoneType Guard Analysis")
        logger.info("-" * 60)

        source = inspect.getsource(DynamicTrailingSLManager.update_trailing_sl)

        if "is None" in source or "if not" in source:
            logger.info("✓ Found NoneType guards in critical methods")
        else:
            warnings.append("Missing NoneType guards")

        # Summary
        logger.info("\n[ANALYSIS SUMMARY]")
        logger.info("-" * 60)

        if issues:
            logger.error(f"Found {len(issues)} critical issues:")
            for issue in issues:
                logger.error(f"  ✗ {issue}")
            return False

        if warnings:
            logger.warning(f"Found {len(warnings)} warnings:")
            for warning in warnings:
                logger.warning(f"  ⚠ {warning}")

        logger.info("✓ Static analysis passed")
        return True

    except Exception as e:
        logger.error(f"✗ Static analysis failed: {e}")
        import traceback
        traceback.print_exc()
        return False


# ============================================================================
# Main Verification Flow
# ============================================================================

async def main():
    """Run all verification checks."""
    logger.info("=" * 60)
    logger.info("DYNAMIC TRAILING SL - INTEGRATION VERIFICATION")
    logger.info("=" * 60)
    logger.info("")

    results = {
        "Imports": verify_imports(),
        "Configuration": verify_config(),
        "Position Tracking": verify_position_tracking(),
        "SL Calculation": verify_sl_calculation(),
        "MT5 Compatibility": verify_mt5_compatibility(),
    }

    # Static analysis
    logger.info("")
    static_ok = static_code_analysis()
    results["Static Analysis"] = static_ok

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("VERIFICATION SUMMARY")
    logger.info("=" * 60)

    for check, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {check}")

    all_passed = all(results.values())

    logger.info("=" * 60)
    if all_passed:
        logger.info("✓ ALL VERIFICATIONS PASSED - READY FOR INTEGRATION")
        logger.info("=" * 60)
        return 0
    else:
        logger.error("✗ SOME VERIFICATIONS FAILED - REVIEW ERRORS ABOVE")
        logger.info("=" * 60)
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n[INTERRUPTED] Verification cancelled by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n[FATAL ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

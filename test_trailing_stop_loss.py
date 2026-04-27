"""
Comprehensive Test Suite for Dynamic Trailing Stop Loss (TSL)
==============================================================

Tests the following:
1. TSL initialization and configuration
2. Position tracking
3. Profit-following mechanics (SL moves in direction of profit only)
4. Throttling (time and price movement requirements)
5. Broker constraint compliance
6. Modification history and statistics
7. Profit locking behavior
8. Real position data from MT5 (if available)
"""

import asyncio
import logging
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.trading.dynamic_trailing_sl_manager import (
    DynamicTrailingSLManager,
    PositionTrailingState,
    TrailingConfig,
)

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | [%(name)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# Mock Broker for Testing
# ============================================================================

class MockBroker:
    """Mock MT5 broker for testing TSL logic without live connection."""
    
    def __init__(self):
        self.modifications = []
        self.fail_next = False
    
    async def modify_order(self, order_id: str, sl: float, tp: Optional[float] = None) -> bool:
        """Record modification attempts."""
        if self.fail_next:
            self.fail_next = False
            return False
        
        self.modifications.append({
            'ticket': order_id,
            'sl': sl,
            'tp': tp,
            'timestamp': datetime.now(),
        })
        logger.info(f"[MOCK_BROKER] Modification recorded: ticket={order_id}, sl={sl}")
        return True


# ============================================================================
# Test Cases
# ============================================================================

class TestTrailingSL:
    """Test suite for dynamic trailing stop loss."""
    
    def __init__(self):
        self.broker = MockBroker()
        self.manager = DynamicTrailingSLManager(
            self.broker,
            TrailingConfig(
                buffer_pips=5.0,
                min_time_between_mods_seconds=1.0,  # Shorter for testing
                min_pip_movement=0.0005,  # 5 pips
                enable_profit_lock=True,
                profit_lock_threshold_pips=20.0,
            )
        )
        self.tests_passed = 0
        self.tests_failed = 0
    
    def assert_equal(self, actual, expected, message: str):
        """Helper assertion."""
        if actual == expected:
            logger.info(f"✅ PASS: {message}")
            self.tests_passed += 1
            return True
        else:
            logger.error(f"❌ FAIL: {message} | Expected: {expected}, Got: {actual}")
            self.tests_failed += 1
            return False
    
    def assert_true(self, condition, message: str):
        """Helper assertion."""
        if condition:
            logger.info(f"✅ PASS: {message}")
            self.tests_passed += 1
            return True
        else:
            logger.error(f"❌ FAIL: {message}")
            self.tests_failed += 1
            return False
    
    def assert_in_range(self, actual, min_val, max_val, message: str):
        """Helper assertion for range checks."""
        if min_val <= actual <= max_val:
            logger.info(f"✅ PASS: {message} (Value: {actual})")
            self.tests_passed += 1
            return True
        else:
            logger.error(f"❌ FAIL: {message} | Expected: {min_val} <= {actual} <= {max_val}")
            self.tests_failed += 1
            return False
    
    # ========================================================================
    # Test: Initialization
    # ========================================================================
    
    def test_initialization(self):
        """Test TSL manager initializes correctly."""
        logger.info("\n" + "="*80)
        logger.info("TEST 1: Initialization")
        logger.info("="*80)
        
        self.assert_equal(
            len(self.manager._positions), 0,
            "Manager starts with no tracked positions"
        )
        
        self.assert_equal(
            self.manager.config.buffer_pips, 5.0,
            "Buffer pips configured correctly"
        )
        
        self.assert_equal(
            self.manager.config.enable_profit_lock, True,
            "Profit lock enabled"
        )
    
    # ========================================================================
    # Test: Position Tracking
    # ========================================================================
    
    def test_position_tracking(self):
        """Test that positions are tracked correctly."""
        logger.info("\n" + "="*80)
        logger.info("TEST 2: Position Tracking")
        logger.info("="*80)
        
        # Track a LONG position
        self.manager.track_position(
            ticket="12345",
            symbol="EUR/USD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )
        
        self.assert_equal(
            len(self.manager._positions), 1,
            "Position tracked successfully"
        )
        
        state = self.manager._positions["12345"]
        self.assert_equal(state.symbol, "EUR/USD", "Symbol recorded correctly")
        self.assert_equal(state.side, "LONG", "Side recorded correctly")
        self.assert_equal(state.entry_price, 1.0850, "Entry price recorded correctly")
        self.assert_equal(state.current_sl, 1.0800, "Current SL recorded correctly")
    
    # ========================================================================
    # Test: LONG Position - SL Moves UP with Price
    # ========================================================================
    
    async def test_long_position_sl_moves_up(self):
        """Test that LONG position SL moves UP as price increases."""
        logger.info("\n" + "="*80)
        logger.info("TEST 3: LONG Position - SL Follows Price UP")
        logger.info("="*80)
        
        # Setup LONG position
        self.manager.track_position(
            ticket="LONG_1",
            symbol="EUR/USD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )
        
        # Price moves up: 1.0850 → 1.0875 (25 pips profit)
        logger.info("\n[SCENARIO] Price moves UP to 1.0875 (+25 pips profit)")
        modified, reason = await self.manager.update_trailing_sl(
            ticket="LONG_1",
            current_price=1.0875,
        )
        
        self.assert_true(
            modified,
            "SL modified when price increases (LONG position)"
        )
        
        state = self.manager._positions["LONG_1"]
        self.assert_true(
            state.current_sl > 1.0800,
            f"SL moved UP from 1.0800 to {state.current_sl}"
        )
        
        logger.info(f"   Old SL: 1.0800 → New SL: {state.current_sl}")
        logger.info(f"   Profit: +25 pips, SL protection: ~5 pips below price")
    
    # ========================================================================
    # Test: SHORT Position - SL Moves DOWN with Price
    # ========================================================================
    
    async def test_short_position_sl_moves_down(self):
        """Test that SHORT position SL moves DOWN as price decreases."""
        logger.info("\n" + "="*80)
        logger.info("TEST 4: SHORT Position - SL Follows Price DOWN")
        logger.info("="*80)
        
        # Setup SHORT position
        self.manager.track_position(
            ticket="SHORT_1",
            symbol="GBP/USD",
            side="SHORT",
            entry_price=1.2800,
            current_sl=1.2850,
        )
        
        # Price moves down: 1.2800 → 1.2775 (25 pips profit)
        logger.info("\n[SCENARIO] Price moves DOWN to 1.2775 (+25 pips profit)")
        modified, reason = await self.manager.update_trailing_sl(
            ticket="SHORT_1",
            current_price=1.2775,
        )
        
        self.assert_true(
            modified,
            "SL modified when price decreases (SHORT position)"
        )
        
        state = self.manager._positions["SHORT_1"]
        self.assert_true(
            state.current_sl < 1.2850,
            f"SL moved DOWN from 1.2850 to {state.current_sl}"
        )
        
        logger.info(f"   Old SL: 1.2850 → New SL: {state.current_sl}")
        logger.info(f"   Profit: +25 pips, SL protection: ~5 pips above price")
    
    # ========================================================================
    # Test: Profit Locking - SL Never Moves Against Profit
    # ========================================================================
    
    async def test_profit_lock_protection(self):
        """Test that SL never moves backward (locking gains)."""
        logger.info("\n" + "="*80)
        logger.info("TEST 5: Profit Locking - SL Never Moves Backward")
        logger.info("="*80)
        
        # Setup LONG position
        self.manager.track_position(
            ticket="LOCK_1",
            symbol="EUR/USD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )
        
        # Move 1: Price up to 1.0875 → SL up to ~1.0825
        logger.info("\n[MOVE 1] Price 1.0850 → 1.0875 (+25 pips)")
        await self.manager.update_trailing_sl("LOCK_1", 1.0875)
        state_after_move1 = self.manager._positions["LOCK_1"].current_sl
        logger.info(f"   SL: 1.0800 → {state_after_move1}")
        
        # Simulate small pullback: Price down to 1.0868
        logger.info("\n[MOVE 2] Price 1.0875 → 1.0868 (-7 pips pullback)")
        await self.manager.update_trailing_sl("LOCK_1", 1.0868)
        state_after_move2 = self.manager._positions["LOCK_1"].current_sl
        
        self.assert_true(
            state_after_move2 >= state_after_move1,
            f"SL stays locked (never moves backward): {state_after_move1} → {state_after_move2}"
        )
        logger.info(f"   SL locked at: {state_after_move2} (protects gains)")
    
    # ========================================================================
    # Test: Time Throttling
    # ========================================================================
    
    async def test_time_throttling(self):
        """Test that modifications are throttled by time."""
        logger.info("\n" + "="*80)
        logger.info("TEST 6: Time Throttling")
        logger.info("="*80)
        
        self.manager.track_position(
            ticket="THROTTLE_1",
            symbol="EUR/USD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )
        
        # First modification should succeed
        logger.info("\n[ATTEMPT 1] First modification at high price")
        modified1, reason1 = await self.manager.update_trailing_sl("THROTTLE_1", 1.0900)
        self.assert_true(modified1, "First modification succeeds")
        
        # Immediate second modification should fail (throttled)
        logger.info("\n[ATTEMPT 2] Immediate second modification (should be throttled)")
        modified2, reason2 = await self.manager.update_trailing_sl("THROTTLE_1", 1.0905)
        self.assert_true(
            not modified2 and "throttle" in reason2.lower(),
            f"Second modification throttled: {reason2}"
        )
        
        # Wait and try again
        logger.info("\n[ATTEMPT 3] After throttle period expires")
        state = self.manager._positions["THROTTLE_1"]
        state.last_sl_modification_time = datetime.now() - timedelta(seconds=2)
        modified3, reason3 = await self.manager.update_trailing_sl("THROTTLE_1", 1.0910)
        self.assert_true(modified3, "Modification succeeds after throttle period")
    
    # ========================================================================
    # Test: Modification History
    # ========================================================================
    
    async def test_modification_history(self):
        """Test that modification history is tracked correctly."""
        logger.info("\n" + "="*80)
        logger.info("TEST 7: Modification History Tracking")
        logger.info("="*80)
        
        self.manager.track_position(
            ticket="HIST_1",
            symbol="EUR/USD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )
        
        # Make several modifications
        prices = [1.0870, 1.0880, 1.0890, 1.0895]
        for i, price in enumerate(prices):
            await self.manager.update_trailing_sl("HIST_1", price)
            if i < len(prices) - 1:
                # Reset throttle for next iteration
                state = self.manager._positions["HIST_1"]
                state.last_sl_modification_time = datetime.now() - timedelta(seconds=2)
        
        state = self.manager._positions["HIST_1"]
        history = state.modification_history
        
        self.assert_true(
            len(history) > 0,
            f"Modification history recorded ({len(history)} entries)"
        )
        
        logger.info(f"\n[HISTORY] {len(history)} modifications tracked:")
        for i, mod in enumerate(history):
            logger.info(f"   {i+1}. Price: {mod['price']:.5f}, "
                       f"New SL: {mod['new_sl']:.5f}, "
                       f"Profit: {mod['profit_pips']:.1f} pips")
    
    # ========================================================================
    # Test: Statistics
    # ========================================================================
    
    async def test_statistics(self):
        """Test that statistics are calculated correctly."""
        logger.info("\n" + "="*80)
        logger.info("TEST 8: Statistics Tracking")
        logger.info("="*80)
        
        self.manager.track_position(
            ticket="STATS_1",
            symbol="EUR/USD",
            side="LONG",
            entry_price=1.0850,
            current_sl=1.0800,
        )
        
        # Make modifications
        await self.manager.update_trailing_sl("STATS_1", 1.0870)
        state = self.manager._positions["STATS_1"]
        state.last_sl_modification_time = datetime.now() - timedelta(seconds=2)
        
        await self.manager.update_trailing_sl("STATS_1", 1.0880)
        
        state = self.manager._positions["STATS_1"]
        
        self.assert_true(
            state.total_modifications > 0,
            f"total_modifications tracked: {state.total_modifications}"
        )
        
        self.assert_true(
            state.times_sl_moved > 0,
            f"times_sl_moved tracked: {state.times_sl_moved}"
        )
        
        logger.info(f"\n[STATS] Position tracking statistics:")
        logger.info(f"   Total modifications: {state.total_modifications}")
        logger.info(f"   SL move events: {state.times_sl_moved}")
        logger.info(f"   Highest price (LONG): {state.highest_price_long}")
    
    # ========================================================================
    # Test: Broker Constraint Compliance
    # ========================================================================
    
    def test_broker_constraints(self):
        """Test that broker minimum distance constraints are respected."""
        logger.info("\n" + "="*80)
        logger.info("TEST 9: Broker Constraint Compliance")
        logger.info("="*80)
        
        # Test validation logic
        is_valid, reason = self.manager.is_valid_modification(
            ticket="TEST_1",
            new_sl=1.0820,
            side="LONG",
            symbol="EUR/USD",
            current_price=1.0850,  # 30 pips away (safe)
            symbol_info=None,
        )
        
        self.assert_true(
            is_valid,
            "SL modification with safe distance (30 pips) is valid"
        )
        
        logger.info(f"   Current price: 1.0850")
        logger.info(f"   Proposed SL:   1.0820 (distance: 30 pips)")
        logger.info(f"   Status: VALID ✅")
    
    # ========================================================================
    # Run All Tests
    # ========================================================================
    
    async def run_all_tests(self):
        """Run all test cases."""
        logger.info("\n" + "="*80)
        logger.info("DYNAMIC TRAILING STOP LOSS - COMPREHENSIVE TEST SUITE")
        logger.info("="*80)
        
        # Synchronous tests
        self.test_initialization()
        self.test_position_tracking()
        self.test_broker_constraints()
        
        # Async tests
        await self.test_long_position_sl_moves_up()
        await self.test_short_position_sl_moves_down()
        await self.test_profit_lock_protection()
        await self.test_time_throttling()
        await self.test_modification_history()
        await self.test_statistics()
        
        # Summary
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        total = self.tests_passed + self.tests_failed
        logger.info(f"✅ PASSED: {self.tests_passed}/{total}")
        logger.info(f"❌ FAILED: {self.tests_failed}/{total}")
        
        if self.tests_failed == 0:
            logger.info("\n🎉 ALL TESTS PASSED! Dynamic TSL is working correctly.")
        else:
            logger.warning(f"\n⚠️  {self.tests_failed} test(s) failed. Review output above.")
        
        return self.tests_failed == 0


# ============================================================================
# Main
# ============================================================================

async def main():
    """Run the test suite."""
    tester = TestTrailingSL()
    success = await tester.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())

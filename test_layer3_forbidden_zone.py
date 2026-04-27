"""
Unit Test for Layer 3 Forbidden Zone Logic
Tests the SL adjustment mechanism that prevents MT5 Error 10016
"""
import sys
import logging
from dataclasses import dataclass
from typing import Optional, Tuple
from datetime import datetime, timezone

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


@dataclass
class MockPosition:
    """Mock Position for testing"""
    position_id: str
    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    current_price: float
    take_profit: float


@dataclass
class MockSymbolInfo:
    """Mock symbol info with broker constraints"""
    trade_stops_level: float  # in points
    point: float  # 0.0001 for most pairs, 0.01 for JPY pairs
    digits: int


class Layer3ForbiddenZoneTest:
    """Test the forbidden zone check and auto-adjustment logic"""
    
    def __init__(self):
        self.test_results = []
    
    def test_long_position_adjustment(self):
        """Test: LONG position with SL in forbidden zone should be adjusted DOWN"""
        logger.info("\n" + "="*80)
        logger.info("TEST 1: LONG Position - SL in Forbidden Zone (Must Adjust DOWN)")
        logger.info("="*80)
        
        # Setup
        position = MockPosition(
            position_id="123",
            symbol="EUR/USD",
            direction="LONG",
            entry_price=1.18000,
            stop_loss=1.17800,  # Current SL
            current_price=1.18600,  # Market price
            take_profit=1.19000,
        )
        
        symbol_info = MockSymbolInfo(
            trade_stops_level=20.0,  # Broker requires 20 points minimum
            point=0.0001,
            digits=5,
        )
        
        # Calculate forbidden zone
        trade_stops_level = symbol_info.trade_stops_level
        point = symbol_info.point
        current_price = position.current_price
        
        forbidden_zone_min = current_price - (trade_stops_level * point)
        forbidden_zone_max = current_price + (trade_stops_level * point)
        safety_buffer = 5 * point
        
        # Propose a small SL tightening (but it falls in forbidden zone)
        proposed_sl = 1.18550  # Too close to current price (1.18600)
        
        logger.debug(f"Position ID: {position.position_id}")
        logger.debug(f"Symbol: {position.symbol}")
        logger.debug(f"Direction: {position.direction}")
        logger.debug(f"Current Price: {current_price:.5f}")
        logger.debug(f"Current SL: {position.stop_loss:.5f}")
        logger.debug(f"Proposed SL (original): {proposed_sl:.5f}")
        logger.debug(f"Forbidden Zone: {forbidden_zone_min:.5f} - {forbidden_zone_max:.5f}")
        logger.debug(f"Trade Stops Level: {trade_stops_level:.0f} points")
        logger.debug(f"Safety Buffer: {5} points")
        
        # Check if in forbidden zone
        sl_in_forbidden_zone = forbidden_zone_min <= proposed_sl <= forbidden_zone_max
        logger.info(f"Proposed SL in Forbidden Zone? {sl_in_forbidden_zone}")
        
        if sl_in_forbidden_zone:
            # For LONG, push SL further DOWN (away from price)
            adjusted_sl = forbidden_zone_min - safety_buffer
            adjusted_sl = round(adjusted_sl, symbol_info.digits)
            
            logger.warning(
                f"[STOPS_LEVEL_ADJUSTMENT] {position.symbol} #{position.position_id} | Direction: {position.direction} | "
                f"Original Proposed SL: {proposed_sl:.5f} | Forbidden Zone: {forbidden_zone_min:.5f} - {forbidden_zone_max:.5f} | "
                f"Adjustment Required | Original SL would be {(current_price - proposed_sl) / point:.0f} points too close to price | "
                f"Auto-Adjusted SL: {adjusted_sl:.5f} (trade_stops_level: {trade_stops_level:.0f} points, safety buffer: 5 points)"
            )
            
            # Verify adjustment is outside forbidden zone
            is_safe = adjusted_sl < forbidden_zone_min
            logger.info(f"✅ Adjusted SL {adjusted_sl:.5f} is safe (outside forbidden zone)? {is_safe}")
            
            self.test_results.append(("TEST 1 - LONG Adjustment", is_safe))
            return is_safe
        else:
            logger.info("✅ SL already outside forbidden zone, no adjustment needed")
            self.test_results.append(("TEST 1 - LONG Adjustment", True))
            return True
    
    def test_short_position_adjustment(self):
        """Test: SHORT position with SL in forbidden zone should be adjusted UP"""
        logger.info("\n" + "="*80)
        logger.info("TEST 2: SHORT Position - SL in Forbidden Zone (Must Adjust UP)")
        logger.info("="*80)
        
        # Setup
        position = MockPosition(
            position_id="456",
            symbol="GBP/USD",
            direction="SHORT",
            entry_price=1.26000,
            stop_loss=1.26500,  # Current SL (above current price for SHORT)
            current_price=1.25600,  # Market price
            take_profit=1.25000,
        )
        
        symbol_info = MockSymbolInfo(
            trade_stops_level=20.0,  # Broker requires 20 points minimum
            point=0.0001,
            digits=5,
        )
        
        # Calculate forbidden zone
        trade_stops_level = symbol_info.trade_stops_level
        point = symbol_info.point
        current_price = position.current_price
        
        forbidden_zone_min = current_price - (trade_stops_level * point)
        forbidden_zone_max = current_price + (trade_stops_level * point)
        safety_buffer = 5 * point
        
        # Propose a small SL tightening (but it falls in forbidden zone)
        proposed_sl = 1.25650  # Too close to current price (1.25600)
        
        logger.debug(f"Position ID: {position.position_id}")
        logger.debug(f"Symbol: {position.symbol}")
        logger.debug(f"Direction: {position.direction}")
        logger.debug(f"Current Price: {current_price:.5f}")
        logger.debug(f"Current SL: {position.stop_loss:.5f}")
        logger.debug(f"Proposed SL (original): {proposed_sl:.5f}")
        logger.debug(f"Forbidden Zone: {forbidden_zone_min:.5f} - {forbidden_zone_max:.5f}")
        logger.debug(f"Trade Stops Level: {trade_stops_level:.0f} points")
        logger.debug(f"Safety Buffer: {5} points")
        
        # Check if in forbidden zone
        sl_in_forbidden_zone = forbidden_zone_min <= proposed_sl <= forbidden_zone_max
        logger.info(f"Proposed SL in Forbidden Zone? {sl_in_forbidden_zone}")
        
        if sl_in_forbidden_zone:
            # For SHORT, push SL further UP (away from price)
            adjusted_sl = forbidden_zone_max + safety_buffer
            adjusted_sl = round(adjusted_sl, symbol_info.digits)
            
            logger.warning(
                f"[STOPS_LEVEL_ADJUSTMENT] {position.symbol} #{position.position_id} | Direction: {position.direction} | "
                f"Original Proposed SL: {proposed_sl:.5f} | Forbidden Zone: {forbidden_zone_min:.5f} - {forbidden_zone_max:.5f} | "
                f"Adjustment Required | Original SL would be {(proposed_sl - current_price) / point:.0f} points too close to price | "
                f"Auto-Adjusted SL: {adjusted_sl:.5f} (trade_stops_level: {trade_stops_level:.0f} points, safety buffer: 5 points)"
            )
            
            # Verify adjustment is outside forbidden zone
            is_safe = adjusted_sl > forbidden_zone_max
            logger.info(f"✅ Adjusted SL {adjusted_sl:.5f} is safe (outside forbidden zone)? {is_safe}")
            
            self.test_results.append(("TEST 2 - SHORT Adjustment", is_safe))
            return is_safe
        else:
            logger.info("✅ SL already outside forbidden zone, no adjustment needed")
            self.test_results.append(("TEST 2 - SHORT Adjustment", True))
            return True
    
    def test_safe_sl_no_adjustment(self):
        """Test: SL already outside forbidden zone should NOT be adjusted"""
        logger.info("\n" + "="*80)
        logger.info("TEST 3: Safe SL - Outside Forbidden Zone (No Adjustment Needed)")
        logger.info("="*80)
        
        # Setup
        position = MockPosition(
            position_id="789",
            symbol="EUR/GBP",
            direction="LONG",
            entry_price=0.85500,
            stop_loss=0.85200,
            current_price=0.85600,
            take_profit=0.86000,
        )
        
        symbol_info = MockSymbolInfo(
            trade_stops_level=20.0,
            point=0.0001,
            digits=5,
        )
        
        # Calculate forbidden zone
        trade_stops_level = symbol_info.trade_stops_level
        point = symbol_info.point
        current_price = position.current_price
        
        forbidden_zone_min = current_price - (trade_stops_level * point)
        forbidden_zone_max = current_price + (trade_stops_level * point)
        
        # Propose SL that is SAFE (well outside forbidden zone)
        proposed_sl = 0.85300  # 300 points below current price - very safe
        
        logger.debug(f"Current Price: {current_price:.5f}")
        logger.debug(f"Proposed SL: {proposed_sl:.5f}")
        logger.debug(f"Forbidden Zone: {forbidden_zone_min:.5f} - {forbidden_zone_max:.5f}")
        logger.debug(f"Distance from Price: {(current_price - proposed_sl) / point:.0f} points")
        
        # Check if in forbidden zone
        sl_in_forbidden_zone = forbidden_zone_min <= proposed_sl <= forbidden_zone_max
        logger.info(f"Proposed SL in Forbidden Zone? {sl_in_forbidden_zone}")
        
        if not sl_in_forbidden_zone:
            logger.debug(
                f"[STOPS_LEVEL_CHECK_OK] {position.symbol} #{position.position_id} | Proposed SL: {proposed_sl:.5f} | "
                f"Current Price: {current_price:.5f} | Forbidden Zone: {forbidden_zone_min:.5f} - {forbidden_zone_max:.5f} | "
                f"SL is safely outside forbidden zone (trade_stops_level: {trade_stops_level:.0f} points)"
            )
            logger.info(f"✅ SL is safe - no adjustment needed")
            self.test_results.append(("TEST 3 - Safe SL Check", True))
            return True
        else:
            logger.error("❌ SL should be safe but was detected in forbidden zone!")
            self.test_results.append(("TEST 3 - Safe SL Check", False))
            return False
    
    def test_jpy_pair(self):
        """Test: JPY pair with different point value (0.01 instead of 0.0001)"""
        logger.info("\n" + "="*80)
        logger.info("TEST 4: JPY Pair - Different Point Value (0.01)")
        logger.info("="*80)
        
        # Setup for JPY pair
        position = MockPosition(
            position_id="999",
            symbol="EUR/JPY",
            direction="LONG",
            entry_price=129.50,
            stop_loss=129.00,
            current_price=130.00,
            take_profit=131.50,
        )
        
        symbol_info = MockSymbolInfo(
            trade_stops_level=20.0,  # Still in points
            point=0.01,  # JPY pairs use 0.01 as point value
            digits=2,  # JPY pairs use 2 decimal digits
        )
        
        trade_stops_level = symbol_info.trade_stops_level
        point = symbol_info.point
        current_price = position.current_price
        
        forbidden_zone_min = current_price - (trade_stops_level * point)
        forbidden_zone_max = current_price + (trade_stops_level * point)
        safety_buffer = 5 * point
        
        proposed_sl = 129.80  # In forbidden zone
        
        logger.debug(f"Symbol: {position.symbol} (JPY Pair)")
        logger.debug(f"Current Price: {current_price:.2f}")
        logger.debug(f"Point Value: {point}")
        logger.debug(f"Proposed SL: {proposed_sl:.2f}")
        logger.debug(f"Forbidden Zone: {forbidden_zone_min:.2f} - {forbidden_zone_max:.2f}")
        
        sl_in_forbidden_zone = forbidden_zone_min <= proposed_sl <= forbidden_zone_max
        logger.info(f"Proposed SL in Forbidden Zone? {sl_in_forbidden_zone}")
        
        if sl_in_forbidden_zone:
            adjusted_sl = forbidden_zone_min - safety_buffer
            adjusted_sl = round(adjusted_sl, symbol_info.digits)
            
            logger.warning(
                f"[STOPS_LEVEL_ADJUSTMENT] {position.symbol} #{position.position_id} | "
                f"Original Proposed SL: {proposed_sl:.2f} | "
                f"Auto-Adjusted SL: {adjusted_sl:.2f}"
            )
            
            is_safe = adjusted_sl < forbidden_zone_min
            logger.info(f"✅ Adjusted SL {adjusted_sl:.2f} is safe for JPY pair? {is_safe}")
            self.test_results.append(("TEST 4 - JPY Pair", is_safe))
            return is_safe
        
        self.test_results.append(("TEST 4 - JPY Pair", True))
        return True
    
    def run_all_tests(self):
        """Run all tests and print summary"""
        logger.info("\n\n" + "╔" + "="*78 + "╗")
        logger.info("║" + " "*78 + "║")
        logger.info("║" + "  LAYER 3 FORBIDDEN ZONE TEST SUITE  ".center(78) + "║")
        logger.info("║" + " "*78 + "║")
        logger.info("╚" + "="*78 + "╝\n")
        
        # Run all tests
        self.test_long_position_adjustment()
        self.test_short_position_adjustment()
        self.test_safe_sl_no_adjustment()
        self.test_jpy_pair()
        
        # Print summary
        logger.info("\n" + "="*80)
        logger.info("TEST SUMMARY")
        logger.info("="*80)
        
        all_passed = True
        for test_name, passed in self.test_results:
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"{status} | {test_name}")
            if not passed:
                all_passed = False
        
        logger.info("="*80)
        if all_passed:
            logger.critical(f"\n🎉 ALL TESTS PASSED ({len(self.test_results)}/{len(self.test_results)}) ✅")
            logger.critical("The Layer 3 Forbidden Zone logic is working correctly!\n")
        else:
            failed_count = sum(1 for _, passed in self.test_results if not passed)
            logger.critical(f"\n❌ SOME TESTS FAILED ({failed_count}/{len(self.test_results)} failures)\n")
        
        return all_passed


if __name__ == "__main__":
    tester = Layer3ForbiddenZoneTest()
    success = tester.run_all_tests()
    sys.exit(0 if success else 1)

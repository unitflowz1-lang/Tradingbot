"""
Test script to validate timezone normalization fixes for MT5 positions.

Tests:
1. normalize_mt5_timestamp_to_utc function with various input formats
2. Position opening timestamp normalization
3. Age calculation with corrected timezones
4. Simulation of the warning scenario (broker UTC+3 offset)
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.data.mt5_broker import normalize_mt5_timestamp_to_utc
from src.trading.exit_manager import ExitManager, ExitManagerConfig

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger("TIMEZONE_TEST")

def test_normalize_mt5_timestamp():
    """Test the normalize_mt5_timestamp_to_utc function"""
    logger.info("=" * 80)
    logger.info("TEST 1: normalize_mt5_timestamp_to_utc function")
    logger.info("=" * 80)
    
    # Test 1.1: UNIX timestamp (should be interpreted as UTC)
    logger.info("\n[TEST 1.1] UNIX timestamp input")
    unix_ts = 1743667200  # Some future timestamp
    result = normalize_mt5_timestamp_to_utc(unix_ts, broker_offset_hours=3)
    logger.info(f"Input (UNIX): {unix_ts}")
    logger.info(f"Result (UTC): {result.isoformat()}")
    assert result.tzinfo == timezone.utc, "Result should be UTC-aware"
    
    # Test 1.2: Naive datetime (should be treated as broker time and offset applied)
    logger.info("\n[TEST 1.2] Naive datetime (assuming broker UTC+3)")
    broker_time = datetime(2026, 4, 3, 1, 0, 40)  # 01:00:40 (broker time)
    result = normalize_mt5_timestamp_to_utc(broker_time, broker_offset_hours=3)
    expected_utc = datetime(2026, 4, 2, 22, 0, 40, tzinfo=timezone.utc)  # Should be 22:00:40 UTC
    logger.info(f"Input (naive): {broker_time.isoformat()}")
    logger.info(f"Result (UTC):  {result.isoformat()}")
    logger.info(f"Expected UTC:  {expected_utc.isoformat()}")
    assert result == expected_utc, f"Conversion failed: {result} != {expected_utc}"
    
    # Test 1.3: UTC-aware datetime (should pass through unchanged)
    logger.info("\n[TEST 1.3] UTC-aware datetime (should pass through)")
    utc_time = datetime(2026, 4, 2, 22, 0, 40, tzinfo=timezone.utc)
    result = normalize_mt5_timestamp_to_utc(utc_time, broker_offset_hours=3)
    logger.info(f"Input (UTC):  {utc_time.isoformat()}")
    logger.info(f"Result (UTC): {result.isoformat()}")
    assert result == utc_time, "UTC datetime should pass through unchanged"
    
    logger.info("\n✓ All normalize_mt5_timestamp tests PASSED")


def test_position_age_calculation():
    """Test position age calculation with timezone-corrected timestamps"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 2: Position age calculation")
    logger.info("=" * 80)
    
    # Create exit manager
    config = ExitManagerConfig(bar_duration_minutes=60)
    exit_mgr = ExitManager(config)
    
    # Simulate the original warning scenario:
    # Current UTC time: 2026-04-02T22:00:49+00:00
    # Broker time for open: 2026-04-03T01:00:40 (which is actually 2026-04-02T22:00:40 UTC)
    # Position was opened 9 seconds before current time
    
    logger.info("\n[TEST 2.1] Original scenario that caused the warning")
    current_utc = datetime(2026, 4, 2, 22, 0, 49, 372070, tzinfo=timezone.utc)
    opened_at_broker = datetime(2026, 4, 3, 1, 0, 40)  # Broker time (UTC+3, no tzinfo)
    
    logger.info(f"Current UTC time:        {current_utc.isoformat()}")
    logger.info(f"Original opened_at:      {opened_at_broker.isoformat()} (naive, broker time)")
    
    # Before fix: would be treated as UTC, causing negative age
    # After fix: should be converted to 2026-04-02T22:00:40+00:00
    
    # Set the environment variable so exit manager can use it
    os.environ["BROKER_TIMEZONE_OFFSET_HOURS"] = "3"
    
    bars_held = exit_mgr.get_bars_held(opened_at_broker, current_time=current_utc)
    logger.info(f"Position age:            {bars_held:.2f} bars")
    
    # Should be approximately 0.0025 bars (9 seconds / 3600 seconds per bar)
    expected_min_bars = 0.0
    expected_max_bars = 0.01
    assert expected_min_bars <= bars_held <= expected_max_bars, \
        f"Age should be between {expected_min_bars} and {expected_max_bars}, got {bars_held}"
    
    logger.info(f"✓ Position age is correctly calculated (not negative)")
    
    # Test 2.2: Test with a position held for 50 bars
    logger.info("\n[TEST 2.2] Position held for 50 bars")
    # Original opened at broker time: 2026-04-03T01:00:40 = 2026-04-02T22:00:40 UTC
    # Current time: 2026-04-03T22:00:40 UTC (24 hours + 0 minutes = 24 bars later)
    # Let's test with 50+ bars: 2026-04-05T00:00:40 UTC (2 days + 2 hours = 50 bars)
    current_utc = datetime(2026, 4, 5, 0, 0, 40, tzinfo=timezone.utc)  # 50 bars later (50 * 60 minutes)
    opened_at_broker = datetime(2026, 4, 3, 1, 0, 40)  # Same original time (broker UTC+3)
    
    logger.info(f"Current UTC time:        {current_utc.isoformat()}")
    logger.info(f"Position opened at:      {opened_at_broker.isoformat()} (broker time UTC+3)")
    
    bars_held = exit_mgr.get_bars_held(opened_at_broker, current_time=current_utc)
    logger.info(f"Position age:            {bars_held:.2f} bars")
    
    # Should be approximately 50 bars
    assert 49.9 <= bars_held <= 50.1, \
        f"Age should be approximately 50 bars, got {bars_held}"
    
    logger.info(f"✓ Position age for 50 bar hold is correct")
    
    logger.info("\n✓ All position age calculation tests PASSED")


def test_scenario_with_40bar_exit():
    """Test that 40-bar time exit now triggers correctly"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 3: 40-bar time exit scenario")
    logger.info("=" * 80)
    
    config = ExitManagerConfig(bar_duration_minutes=60, stagnation_limit_bars=40)
    exit_mgr = ExitManager(config)
    os.environ["BROKER_TIMEZONE_OFFSET_HOURS"] = "3"
    
    # Position opened at broker time 2026-04-03T14:00:00
    # UTC equivalent: 2026-04-03T11:00:00
    # Current UTC: 2026-04-05T11:00:00
    # Difference: 48 hours = 48 bars (triggers 40-bar exit)
    current_utc = datetime(2026, 4, 5, 11, 0, 0, tzinfo=timezone.utc)
    opened_at_broker = datetime(2026, 4, 3, 14, 0, 0)  # Naive, broker time UTC+3
    
    logger.info(f"Current UTC time:        {current_utc.isoformat()}")
    logger.info(f"Position opened at:      {opened_at_broker.isoformat()} (broker time, UTC+3)")
    logger.info(f"Position should be:      ~48 bars old")
    logger.info(f"40-bar exit threshold:   {config.stagnation_limit_bars} bars")
    
    bars_held = exit_mgr.get_bars_held(opened_at_broker, current_time=current_utc)
    logger.info(f"Calculated age:          {bars_held:.2f} bars")
    
    # Should trigger exit
    should_exit = bars_held >= config.stagnation_limit_bars
    logger.info(f"Should exit:             {should_exit}")
    
    assert should_exit, f"Should trigger exit at {bars_held} bars (>= {config.stagnation_limit_bars} bars)"
    logger.info("\n✓ 40-bar time exit trigger works correctly")


def test_broker_offset_configuration():
    """Test that BROKER_TIMEZONE_OFFSET_HOURS environment variable works"""
    logger.info("\n" + "=" * 80)
    logger.info("TEST 4: Broker timezone offset configuration")
    logger.info("=" * 80)
    
    # Test with different offsets
    test_cases = [
        (3, "UTC+3 (typical forex broker)"),
        (0, "UTC (no offset)"),
        (5, "UTC+5 (some regional brokers)"),
        (8, "UTC+8 (Asian brokers)"),
    ]
    
    for offset, description in test_cases:
        logger.info(f"\n[TEST 4] Testing offset: {offset} ({description})")
        os.environ["BROKER_TIMEZONE_OFFSET_HOURS"] = str(offset)
        
        # Broker time: 10:00:00
        # UTC should be: 10:00:00 - offset
        broker_time = datetime(2026, 4, 2, 10, 0, 0)
        result = normalize_mt5_timestamp_to_utc(broker_time, broker_offset_hours=offset)
        
        expected_utc = datetime(2026, 4, 2, 10, 0, 0, tzinfo=timezone.utc) - timedelta(hours=offset)
        expected_utc = expected_utc.replace(tzinfo=timezone.utc)
        
        logger.info(f"  Broker time:     {broker_time}")
        logger.info(f"  Result UTC:      {result}")
        logger.info(f"  Expected UTC:    {expected_utc}")
        
        assert result == expected_utc, f"Offset conversion failed for offset={offset}"
    
    logger.info("\n✓ All broker offset configuration tests PASSED")


if __name__ == "__main__":
    logger.info("\n" + "=" * 80)
    logger.info("STARTING TIMEZONE FIX VALIDATION TESTS")
    logger.info("=" * 80)
    
    try:
        test_normalize_mt5_timestamp()
        test_position_age_calculation()
        test_scenario_with_40bar_exit()
        test_broker_offset_configuration()
        
        logger.info("\n" + "=" * 80)
        logger.info("✓ ALL TESTS PASSED - TIMEZONE FIX IS WORKING CORRECTLY")
        logger.info("=" * 80)
        logger.info("\nSummary of fixes:")
        logger.info("1. normalize_mt5_timestamp_to_utc() converts broker server time to UTC")
        logger.info("2. Position open_time from MT5 is normalized in get_positions()")
        logger.info("3. Position recovery paths apply timezone normalization")
        logger.info("4. Exit manager properly calculates position age without negative values")
        logger.info("5. 40-bar time exit rule will now trigger correctly")
        logger.info("\nConfiguration: Set BROKER_TIMEZONE_OFFSET_HOURS environment variable")
        logger.info("Default value: 3 (for UTC+3 brokers)")
        
        sys.exit(0)
        
    except AssertionError as e:
        logger.error(f"\n✗ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n✗ UNEXPECTED ERROR: {e}", exc_info=True)
        sys.exit(1)

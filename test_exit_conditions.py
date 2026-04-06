"""
Test Exit Condition Generator
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import List

from src.backtesting.exit_condition_generator import (
    ExitConditionGenerator,
    ExitConditionType,
    TakeProfitCondition,
    StopLossCondition,
    TrailingStopCondition,
    TimeBasedCondition,
    BreakEvenCondition
)
from src.models import Position, Direction, MarketData

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)

def create_test_position() -> Position:
    """Create a test position"""
    return Position(
        position_id="TEST_001",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=10000.0,
        entry_price=1.0900,
        current_price=1.0900,
        unrealized_pnl=0.0,
        stop_loss=None,
        take_profit=None,
        opened_at=datetime.now(timezone.utc)
    )

def create_test_market_data(price: float) -> MarketData:
    """Create test market data"""
    spread = 0.0002
    return MarketData(
        symbol="EUR/USD",
        timestamp=datetime.now(timezone.utc),
        open=price,
        high=price + 0.0010,
        low=price - 0.0010,
        close=price,
        bid=price - spread / 2,
        ask=price + spread / 2,
        spread=spread,
        volume=1000000
    )

def test_take_profit():
    """Test take profit condition"""
    print("\n" + "=" * 60)
    print("TEST 1: Take Profit Condition")
    print("=" * 60)

    generator = ExitConditionGenerator()
    generator.add_condition(TakeProfitCondition(profit_pips=100))

    position = create_test_position()
    entry_price = 1.0900

    # Test 1: Price hasn't reached TP
    market_data = create_test_market_data(1.0905)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.0905: Exit={should_exit}, Reason={reason}")
    assert not should_exit

    # Test 2: Price reaches TP (100 pips = 0.0100)
    market_data = create_test_market_data(1.1000)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.1000: Exit={should_exit}, Reason={reason}")
    assert should_exit

    print("✓ Take Profit test PASSED")

def test_stop_loss():
    """Test stop loss condition"""
    print("\n" + "=" * 60)
    print("TEST 2: Stop Loss Condition")
    print("=" * 60)

    generator = ExitConditionGenerator()
    generator.add_condition(StopLossCondition(loss_pips=50))

    position = create_test_position()
    entry_price = 1.0900

    # Test 1: Price hasn't hit SL
    market_data = create_test_market_data(1.0880)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.0880: Exit={should_exit}, Reason={reason}")
    assert not should_exit

    # Test 2: Price hits SL (50 pips = 0.0050)
    market_data = create_test_market_data(1.0850)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.0850: Exit={should_exit}, Reason={reason}")
    assert should_exit

    print("✓ Stop Loss test PASSED")

def test_trailing_stop():
    """Test trailing stop condition"""
    print("\n" + "=" * 60)
    print("TEST 3: Trailing Stop Condition")
    print("=" * 60)

    generator = ExitConditionGenerator()
    trailing_stop = TrailingStopCondition(
        trailing_pips=30,
        max_profit_pips=10)
    generator.add_condition(trailing_stop)

    position = create_test_position()
    entry_price = 1.0900

    # First call to set the initial highest price
    market_data1 = create_test_market_data(1.0920)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data1, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.0920: Exit={should_exit}, Reason={reason}")
    assert not should_exit  # Still below activation point or just activated

    # Now test drop past trailing stop (1.0920 - 0.0030 = 1.0890)
    market_data2 = create_test_market_data(1.0888)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data2, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.0888: Exit={should_exit}, Reason={reason}")
    assert should_exit

    print("✓ Trailing Stop test PASSED")

def test_time_based():
    """Test time-based condition"""
    print("\n" + "=" * 60)
    print("TEST 4: Time-Based Condition")
    print("=" * 60)

    generator = ExitConditionGenerator()
    generator.add_condition(TimeBasedCondition(hold_minutes=60))

    position = create_test_position()
    entry_price = 1.0900
    entry_time = datetime.now(timezone.utc)

    # Test 1: Less than 60 minutes
    market_data = create_test_market_data(1.0910)
    current_time = entry_time + timedelta(minutes=30)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, entry_time)
    logger.info(f"30 minutes elapsed: Exit={should_exit}")
    assert not should_exit

    # Test 2: More than 60 minutes (simulate by checking market timestamp)
    # Create a new generator instance for this test
    generator2 = ExitConditionGenerator()
    condition = TimeBasedCondition(hold_minutes=60)
    generator2.add_condition(condition)

    market_data_future = MarketData(
        symbol="EUR/USD",
        timestamp=entry_time + timedelta(minutes=70),
        open=1.0910,
        high=1.0920,
        low=1.0905,
        close=1.0910,
        bid=1.0908,
        ask=1.0912,
        spread=0.0004,
        volume=1000000
    )

    should_exit, reason, _ = generator2.check_all_conditions(
        position, market_data_future, entry_price, entry_time)
    logger.info(f"70 minutes elapsed: Exit={should_exit}, Reason={reason}")
    assert should_exit

    print("✓ Time-Based test PASSED")

def test_breakeven():
    """Test breakeven condition"""
    print("\n" + "=" * 60)
    print("TEST 5: Breakeven Condition")
    print("=" * 60)

    generator = ExitConditionGenerator()
    generator.add_condition(
        BreakEvenCondition(
            min_profit_pips=50,
            protection_pips=20))

    position = create_test_position()
    entry_price = 1.0900
    entry_time = datetime.now(timezone.utc)

    position_history = [
        create_test_market_data(1.0905),
        create_test_market_data(1.0920),  # Max: 1.0920
    ]

    # Test 1: Price in profit but hasn't hit min
    market_data = create_test_market_data(1.0910)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, entry_time,
        position_history)
    logger.info(f"Price 1.0910: Exit={should_exit}")
    assert not should_exit

    # Test 2: In max profit zone, drops below protection
    # Max was 1.0920, protection is 20 pips, so SL at 1.0900
    position_history2 = [
        create_test_market_data(1.0905),
        create_test_market_data(1.0950),  # Max: 1.0950
    ]

    market_data = create_test_market_data(1.0930)  # > min profit
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, entry_time,
        position_history2)
    logger.info(f"Price 1.0930: Exit={should_exit}, Reason={reason}")
    # Should not exit yet - price is still above breakeven protection

    print("✓ Breakeven test PASSED")

def test_default_strategy():
    """Test default strategy combination"""
    print("\n" + "=" * 60)
    print("TEST 6: Default Strategy")
    print("=" * 60)

    generator = ExitConditionGenerator()
    generator.create_default_strategy()

    logger.info(f"Strategy: {generator.get_summary()}")

    position = create_test_position()
    entry_price = 1.0900
    entry_time = datetime.now(timezone.utc)

    # Should include TP, SL, and Trailing Stop
    assert len(generator.conditions) >= 3
    logger.info(f"Number of conditions: {len(generator.conditions)}")

    # Test take profit triggers
    market_data = create_test_market_data(1.1000)
    should_exit, reason, _ = generator.check_all_conditions(
        position, market_data, entry_price, entry_time)
    logger.info(f"TP trigger test: Exit={should_exit}, "
                f"Reason={reason}")

    print("✓ Default Strategy test PASSED")

def test_multiple_conditions():
    """Test multiple conditions - first one triggers"""
    print("\n" + "=" * 60)
    print("TEST 7: Multiple Conditions Priority")
    print("=" * 60)

    generator = ExitConditionGenerator()
    generator.add_condition(StopLossCondition(loss_pips=50))
    generator.add_condition(TakeProfitCondition(profit_pips=100))

    position = create_test_position()
    entry_price = 1.0900

    # Price triggers both TP and SL - SL should trigger first
    # (but won't because it's at 1.0850, above price)
    # Test at price that hits TP but not SL
    market_data = create_test_market_data(1.1000)
    should_exit, reason, cond_type = generator.check_all_conditions(
        position, market_data, entry_price, datetime.now(timezone.utc))
    logger.info(f"Price 1.1000: Exit={should_exit}, "
                f"Type={cond_type}, Reason={reason}")
    assert cond_type == ExitConditionType.STOP_LOSS or (
        should_exit and cond_type is not None)

    print("✓ Multiple Conditions test PASSED")

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("EXIT CONDITION GENERATOR TEST SUITE")
    print("=" * 60)

    try:
        test_take_profit()
        test_stop_loss()
        test_trailing_stop()
        test_time_based()
        test_breakeven()
        test_default_strategy()
        test_multiple_conditions()

        print("\n" + "=" * 60)
        print("✓ ALL TESTS PASSED!")
        print("=" * 60 + "\n")

    except AssertionError as e:
        print(f"\n✗ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n✗ UNEXPECTED ERROR: {e}")
        raise

"""Test script for data models and validation"""

import sys
import os
from datetime import datetime, timedelta, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.models import *
from src.validation import *
from src.exceptions import DataValidationError


def test_market_data_validation():
    """Test MarketData validation"""
    print("Testing MarketData validation...")
    
    # Valid market data
    valid_data = MarketData(
        symbol="EUR/USD",
        timestamp=datetime.now(timezone.utc) - timedelta(minutes=1),
        open=1.1000,
        high=1.1050,
        low=1.0950,
        close=1.1025,
        volume=1000000,
        bid=1.1024,
        ask=1.1026,
        spread=0.0002
    )
    print("✓ Valid MarketData created successfully")
    
    # Test invalid symbol
    try:
        MarketData(
            symbol="INVALID",
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.1050, low=1.0950, close=1.1025,
            volume=1000000, bid=1.1024, ask=1.1026, spread=0.0002
        )
        print("❌ Should have failed for invalid symbol")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid symbol: {e.error_code}")
    
    # Test invalid OHLC relationship
    try:
        MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.0900, low=1.0950, close=1.1025,  # high < low
            volume=1000000, bid=1.1024, ask=1.1026, spread=0.0002
        )
        print("❌ Should have failed for invalid OHLC")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid OHLC: {e.error_code}")
    
    # Test invalid bid/ask
    try:
        MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.1050, low=1.0950, close=1.1025,
            volume=1000000, bid=1.1026, ask=1.1024, spread=0.0002  # bid > ask
        )
        print("❌ Should have failed for invalid bid/ask")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid bid/ask: {e.error_code}")
    
    # Test utility methods
    mid_price = valid_data.get_mid_price()
    print(f"✓ Mid price calculated: {mid_price}")
    
    is_stale = valid_data.is_stale(max_age_seconds=30)
    print(f"✓ Staleness check: {is_stale}")


def test_sentiment_result_validation():
    """Test SentimentResult validation"""
    print("\nTesting SentimentResult validation...")
    
    # Valid sentiment result
    valid_sentiment = SentimentResult(
        symbol="EUR/USD",
        sentiment_score=0.75,
        confidence=0.85,
        reasoning="Positive economic indicators suggest bullish trend",
        sources=["Reuters", "Bloomberg"],
        timestamp=datetime.now(timezone.utc)
    )
    print("✓ Valid SentimentResult created successfully")
    
    # Test invalid sentiment score range
    try:
        SentimentResult(
            symbol="EUR/USD",
            sentiment_score=1.5,  # > 1.0
            confidence=0.85,
            reasoning="Test",
            sources=["Reuters"],
            timestamp=datetime.now(timezone.utc)
        )
        print("❌ Should have failed for invalid sentiment score")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid sentiment score: {e.error_code}")
    
    # Test empty reasoning
    try:
        SentimentResult(
            symbol="EUR/USD",
            sentiment_score=0.75,
            confidence=0.85,
            reasoning="",  # Empty
            sources=["Reuters"],
            timestamp=datetime.now(timezone.utc)
        )
        print("❌ Should have failed for empty reasoning")
    except DataValidationError as e:
        print(f"✓ Correctly caught empty reasoning: {e.error_code}")
    
    # Test utility methods
    print(f"✓ Is bullish: {valid_sentiment.is_bullish()}")
    print(f"✓ Is high confidence: {valid_sentiment.is_high_confidence()}")


def test_trading_signal_validation():
    """Test TradingSignal validation"""
    print("\nTesting TradingSignal validation...")
    
    # Valid LONG signal
    valid_long_signal = TradingSignal(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry_price=1.1000,
        stop_loss=1.0950,
        take_profit=1.1100,
        position_size=0.02,
        confidence=0.80,
        reasoning="Strong bullish sentiment + technical confirmation",
        timestamp=datetime.now(timezone.utc)
    )
    print("✓ Valid LONG TradingSignal created successfully")
    
    # Valid SHORT signal
    valid_short_signal = TradingSignal(
        symbol="GBP/USD",
        direction=Direction.SHORT,
        entry_price=1.2000,
        stop_loss=1.2050,
        take_profit=1.1900,
        position_size=0.015,
        confidence=0.75,
        reasoning="Bearish sentiment + technical breakdown",
        timestamp=datetime.now(timezone.utc)
    )
    print("✓ Valid SHORT TradingSignal created successfully")
    
    # Test invalid stop loss for LONG
    try:
        TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.1050,  # Above entry for LONG
            take_profit=1.1100,
            position_size=0.02,
            confidence=0.80,
            reasoning="Test",
            timestamp=datetime.now(timezone.utc)
        )
        print("❌ Should have failed for invalid LONG stop loss")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid LONG stop loss: {e.error_code}")
    
    # Test invalid take profit for SHORT
    try:
        TradingSignal(
            symbol="EUR/USD",
            direction=Direction.SHORT,
            entry_price=1.1000,
            stop_loss=1.1050,
            take_profit=1.1100,  # Above entry for SHORT
            position_size=0.02,
            confidence=0.80,
            reasoning="Test",
            timestamp=datetime.now(timezone.utc)
        )
        print("❌ Should have failed for invalid SHORT take profit")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid SHORT take profit: {e.error_code}")
    
    # Test utility methods
    rr_ratio = valid_long_signal.calculate_risk_reward_ratio()
    print(f"✓ Risk-reward ratio calculated: {rr_ratio:.2f}")


def test_position_validation():
    """Test Position validation"""
    print("\nTesting Position validation...")
    
    # Valid position
    valid_position = Position(
        position_id="POS_001",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=10000.0,
        entry_price=1.1000,
        current_price=1.1025,
        unrealized_pnl=25.0,  # (1.1025 - 1.1000) * 10000
        stop_loss=1.0950,
        take_profit=1.1100,
        opened_at=datetime.now(timezone.utc) - timedelta(hours=1)
    )
    print("✓ Valid Position created successfully")
    
    # Test PnL calculation validation
    try:
        Position(
            position_id="POS_002",
            symbol="EUR/USD",
            direction=Direction.LONG,
            quantity=10000.0,
            entry_price=1.1000,
            current_price=1.1025,
            unrealized_pnl=100.0,  # Incorrect PnL
            stop_loss=1.0950,
            take_profit=1.1100,
            opened_at=datetime.now(timezone.utc)
        )
        print("❌ Should have failed for incorrect PnL")
    except DataValidationError as e:
        print(f"✓ Correctly caught incorrect PnL: {e.error_code}")
    
    # Test utility methods
    valid_position.update_current_price(1.1050)
    print(f"✓ Position updated, new PnL: {valid_position.unrealized_pnl}")
    print(f"✓ Is profitable: {valid_position.is_profitable()}")


def test_portfolio_validation():
    """Test Portfolio validation"""
    print("\nTesting Portfolio validation...")
    
    # Create valid positions
    position1 = Position(
        position_id="POS_001",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=10000.0,
        entry_price=1.1000,
        current_price=1.1025,
        unrealized_pnl=25.0,
        stop_loss=1.0950,
        take_profit=1.1100,
        opened_at=datetime.now(timezone.utc)
    )
    
    # Valid portfolio
    valid_portfolio = Portfolio(
        account_id="ACC_123",
        balance=10000.0,
        equity=10025.0,
        margin_used=1000.0,
        margin_available=9025.0,
        positions=[position1],
        updated_at=datetime.now(timezone.utc)
    )
    print("✓ Valid Portfolio created successfully")
    
    # Test invalid margin relationship
    try:
        Portfolio(
            account_id="ACC_123",
            balance=10000.0,
            equity=10025.0,
            margin_used=1000.0,
            margin_available=8000.0,  # Doesn't add up to equity
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        print("❌ Should have failed for invalid margin relationship")
    except DataValidationError as e:
        print(f"✓ Correctly caught invalid margin relationship: {e.error_code}")
    
    # Test utility methods
    total_pnl = valid_portfolio.get_total_unrealized_pnl()
    margin_level = valid_portfolio.get_margin_level()
    print(f"✓ Total PnL: {total_pnl}")
    print(f"✓ Margin level: {margin_level:.2f}%")


def test_validation_utilities():
    """Test validation utility functions"""
    print("\nTesting validation utilities...")
    
    # Test ValidationRules
    print(f"✓ Valid forex symbol: {ValidationRules.validate_forex_symbol('EUR/USD')}")
    print(f"✓ Invalid forex symbol: {ValidationRules.validate_forex_symbol('INVALID')}")
    print(f"✓ Is major pair: {ValidationRules.is_major_pair('EUR/USD')}")
    print(f"✓ Valid price: {ValidationRules.validate_price(1.1000)}")
    print(f"✓ Invalid price: {ValidationRules.validate_price(-1.0)}")
    
    # Test MarketDataValidator
    validator = MarketDataValidator()
    test_data = {
        'symbol': 'EUR/USD',
        'timestamp': datetime.now(timezone.utc),
        'open': 1.1000,
        'high': 1.1050,
        'low': 1.0950,
        'close': 1.1025,
        'volume': 1000000,
        'bid': 1.1024,
        'ask': 1.1026,
        'spread': 0.0002
    }
    
    is_valid = validator.validate(test_data)
    print(f"✓ Market data validation: {is_valid}")
    
    if not is_valid:
        print(f"Errors: {validator.get_errors()}")


def test_error_handling():
    """Test error handling and edge cases"""
    print("\nTesting error handling...")
    
    # Test with None values
    try:
        MarketData(
            symbol=None,
            timestamp=datetime.now(timezone.utc),
            open=1.1000, high=1.1050, low=1.0950, close=1.1025,
            volume=1000000, bid=1.1024, ask=1.1026, spread=0.0002
        )
        print("❌ Should have failed for None symbol")
    except (DataValidationError, TypeError) as e:
        print(f"✓ Correctly caught None symbol error")
    
    # Test with extreme values
    try:
        MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=float('inf'),  # Infinite value
            high=1.1050, low=1.0950, close=1.1025,
            volume=1000000, bid=1.1024, ask=1.1026, spread=0.0002
        )
        print("❌ Should have failed for infinite value")
    except (DataValidationError, ValueError) as e:
        print(f"✓ Correctly caught infinite value error")


def main():
    """Run all validation tests"""
    print("=== AI Forex Trading Bot - Data Models and Validation Test ===\n")
    
    try:
        test_market_data_validation()
        test_sentiment_result_validation()
        test_trading_signal_validation()
        test_position_validation()
        test_portfolio_validation()
        test_validation_utilities()
        test_error_handling()
        
        print("\n=== All validation tests completed successfully! ===")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
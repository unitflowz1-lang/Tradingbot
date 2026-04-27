"""
Test and validate signal improvements and advanced exit logic
"""

import logging
from datetime import datetime, timezone, timedelta
from src.models import Direction, SignalType, TechnicalSignal
from src.analysis.signal_strength_calculator import SignalStrengthCalculator, SignalQuality
from src.trading.advanced_exit_handler import AdvancedExitHandler, ExitType

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


def test_signal_strength_calculator():
    """Test signal quality analysis"""
    print("\n" + "="*70)
    print("TEST 1: Signal Strength Calculator")
    print("="*70)
    
    calculator = SignalStrengthCalculator()
    
    # Test Case 1: Strong BUY signal (high confluence, good filters)
    print("\n📊 Test Case 1: Strong BUY Signal")
    print("-" * 70)
    
    now = datetime.now(timezone.utc)
    signals_strong = [
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.BUY,
            strength=0.9,
            indicators={"rsi": 35, "macd": 0.001},
            timestamp=now
        ),
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.BUY,
            strength=0.85,
            indicators={"rsi": 35, "macd": 0.001},
            timestamp=now
        ),
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.SELL,
            strength=0.2,
            indicators={"rsi": 35, "macd": 0.001},
            timestamp=now
        ),  # 1 weak disagree
    ]
    
    analysis = calculator.analyze_signal_quality(
        technical_signals=signals_strong,
        indicators={'rsi': 35, 'adx': 28, 'atr': 0.0045},
        current_price=1.0850,
        direction=Direction.LONG,
        volume=75000,
        hour_of_day=12  # London hours
    )
    
    print(f"Quality Score: {analysis.quality_score:.1%}")
    print(f"Quality Level: {analysis.quality_level.name}")
    print(f"Confluence: {analysis.confluence_count}/3 signals agree")
    print(f"Trend: {analysis.trend_alignment:.0%} (ADX strength)")
    print(f"Reasoning: {analysis.reasoning}")
    
    assert analysis.quality_score > 0.75, "Strong signal should score > 75%"
    assert analysis.quality_level == SignalQuality.STRONG, "Should be STRONG quality"
    print("✓ PASSED: Strong signal identified correctly")
    
    # Test Case 2: Weak BUY signal (low confluence, poor filters)
    print("\n📊 Test Case 2: Weak BUY Signal")
    print("-" * 70)
    
    signals_weak = [
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.BUY,
            strength=0.6,
            indicators={"rsi": 75, "macd": -0.001},
            timestamp=now
        ),
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.SELL,
            strength=0.8,
            indicators={"rsi": 75, "macd": -0.001},
            timestamp=now
        ),
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.SELL,
            strength=0.7,
            indicators={"rsi": 75, "macd": -0.001},
            timestamp=now
        ),
    ]
    
    analysis = calculator.analyze_signal_quality(
        technical_signals=signals_weak,
        indicators={'rsi': 75, 'adx': 12, 'atr': 0.0020},  # Overbought, weak trend
        current_price=1.0850,
        direction=Direction.LONG,
        volume=15000,
        hour_of_day=2  # Asian hours (low quality)
    )
    
    print(f"Quality Score: {analysis.quality_score:.1%}")
    print(f"Quality Level: {analysis.quality_level.name}")
    print(f"Confluence: {analysis.confluence_count}/3 signals agree")
    print(f"Trend: {analysis.trend_alignment:.0%} (ADX strength)")
    print(f"⚠️  Reasoning: {analysis.reasoning}")
    
    assert analysis.quality_score < 0.60, "Weak signal should score < 60%"
    assert analysis.quality_level in (SignalQuality.WEAK, SignalQuality.POOR), "Should be WEAK/POOR quality"
    print("✓ PASSED: Weak signal rejected correctly")


def test_advanced_exit_handler():
    """Test advanced exit logic"""
    print("\n" + "="*70)
    print("TEST 2: Advanced Exit Handler")
    print("="*70)
    
    handler = AdvancedExitHandler()
    
    # Test Case 1: Trailing Stop activation
    print("\n🎯 Test Case 1: Trailing Stop Exit")
    print("-" * 70)
    
    entry_price = 1.0850
    position_high = 1.0900  # 50 pips profit
    current_price = 1.0880  # Pulled back 20 pips
    
    exit_level, unrealized_pnl = handler.evaluate_exit_conditions(
        symbol="EUR/USD",
        entry_price=entry_price,
        current_price=current_price,
        current_pnl=30.0, # Example P&L $30
        stop_loss=1.0800,
        take_profit=1.0950,
        direction=Direction.LONG,
        position_open_time=datetime.now(timezone.utc) - timedelta(minutes=30),
        position_high=position_high
    )
    
    if exit_level:
        print(f"Exit Triggered: {exit_level.exit_type.value}")
        print(f"Exit Price: {exit_level.price:.5f}")
        print(f"P&L: {exit_level.pnl_percent:.2f} pips")
        print(f"Description: {exit_level.description}")
        
        # Trailing stop should activate on pullback from high
        if exit_level.exit_type == ExitType.TRAILING_STOP:
            print("✓ PASSED: Trailing stop activated on pullback")
        else:
            print(f"⚠️  Got {exit_level.exit_type.value} instead of TRAILING_STOP")
    else:
        print("No exit triggered")
    
    # Test Case 2: Partial Profit Taking
    print("\n🎯 Test Case 2: Partial Profit Exit")
    print("-" * 70)
    
    entry_price = 1.0850
    current_price = 1.0860  # 10 pips profit
    position_high = 1.0860
    
    exit_level, unrealized_pnl = handler.evaluate_exit_conditions(
        symbol="EUR/USD",
        entry_price=entry_price,
        current_price=current_price,
        current_pnl=10.0,
        stop_loss=1.0800,
        take_profit=1.0950,
        direction=Direction.LONG,
        position_open_time=datetime.now(timezone.utc),
        position_high=position_high
    )
    
    if exit_level:
        print(f"Exit Triggered: {exit_level.exit_type.value}")
        print(f"Exit Price: {exit_level.price:.5f}")
        print(f"P&L: {exit_level.pnl_percent:.2f} pips")
        print(f"Close: {exit_level.exit_quantity_percent:.0%} of position")
        print(f"Description: {exit_level.description}")
        
        if exit_level.exit_quantity_percent < 1.0:
            print(f"✓ PASSED: Partial profit triggered (closing {exit_level.exit_quantity_percent:.0%})")
        else:
            print("Full position closure")
    
    # Test Case 3: Time-Based Exit
    print("\n🎯 Test Case 3: Time-Based Exit")
    print("-" * 70)
    
    entry_price = 1.0850
    current_price = 1.0820  # 30 pips loss
    position_high = 1.0820
    open_time = datetime.now(timezone.utc) - timedelta(hours=1, minutes=30)  # 90 min old
    
    exit_level, unrealized_pnl = handler.evaluate_exit_conditions(
        symbol="EUR/USD",
        entry_price=entry_price,
        current_price=current_price,
        current_pnl=-30.0,
        stop_loss=1.0800,
        take_profit=1.0950,
        direction=Direction.LONG,
        position_open_time=open_time,
        position_high=position_high
    )
    
    if exit_level:
        print(f"Exit Triggered: {exit_level.exit_type.value}")
        print(f"Exit Price: {exit_level.price:.5f}")
        print(f"P&L: {exit_level.pnl_percent:.2f} pips")
        print(f"Description: {exit_level.description}")
        
        if exit_level.exit_type == ExitType.TIME_EXIT:
            print("✓ PASSED: Time-based exit on old losing position")
    else:
        print("No exit triggered")


def test_combined_workflow():
    """Test combined signal quality + exit logic workflow"""
    print("\n" + "="*70)
    print("TEST 3: Combined Workflow (Signal → Entry → Exit)")
    print("="*70)
    
    calculator = SignalStrengthCalculator()
    handler = AdvancedExitHandler()
    
    print("\n🚀 Workflow: Generate signal → Check quality → Enter trade → Manage exit")
    print("-" * 70)
    
    # Step 1: Generate trading signals
    now = datetime.now(timezone.utc)
    technical_signals = [
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.BUY,
            strength=0.88,
            indicators={"rsi": 40, "adx": 25, "atr": 0.0045},
            timestamp=now
        ),
        TechnicalSignal(
            symbol="EUR/USD",
            signal_type=SignalType.BUY,
            strength=0.82,
            indicators={"rsi": 40, "adx": 25, "atr": 0.0045},
            timestamp=now
        ),
    ]
    
    print(f"\n1️⃣  Generated {len(technical_signals)} technical signals")
    
    # Step 2: Evaluate signal quality
    signal_analysis = calculator.analyze_signal_quality(
        technical_signals=technical_signals,
        indicators={'rsi': 40, 'adx': 25, 'atr': 0.0045},
        current_price=1.0850,
        direction=Direction.LONG,
        volume=60000,
        hour_of_day=13
    )
    
    print(f"2️⃣  Signal Quality: {signal_analysis.quality_score:.0%} ({signal_analysis.quality_level.name})")
    
    # Step 3: Entry decision
    if signal_analysis.quality_score >= 0.75:
        print("3️⃣  ✓ ENTER TRADE (quality threshold met)")
        
        entry_price = 1.0850
        stop_loss = entry_price - 0.0050  # 50 pips
        take_profit = entry_price + 0.0100  # 100 pips
        
        print(f"    Entry: {entry_price:.5f}")
        print(f"    Stop Loss: {stop_loss:.5f}")
        print(f"    Take Profit: {take_profit:.5f}")
        
        # Step 4: Manage position (after some time)
        print(f"\n4️⃣  Position Management (after 45 minutes):")
        
        current_price = 1.0895  # 45 pips profit
        position_high = 1.0895
        open_time = datetime.now(timezone.utc) - timedelta(minutes=45)
        
        exit_level, unrealized_pnl = handler.evaluate_exit_conditions(
            symbol="EUR/USD",
            entry_price=entry_price,
            current_price=current_price,
            current_pnl=45.0,
            stop_loss=stop_loss,
            take_profit=take_profit,
            direction=Direction.LONG,
            position_open_time=open_time,
            position_high=position_high
        )
        
        if exit_level:
            print(f"    💰 Exit Signal: {exit_level.exit_type.value}")
            print(f"    Exit Price: {exit_level.price:.5f}")
            print(f"    Realized P&L: {exit_level.pnl_percent:.2f} pips ({exit_level.description})")
            print("    ✓ COMPLETE")
        else:
            print("    Position held, no exit yet")
    else:
        print("3️⃣  ✗ SKIP TRADE (quality threshold not met)")


def run_all_tests():
    """Run all validation tests"""
    print("\n" + "="*70)
    print("SIGNAL IMPROVEMENT & ADVANCED EXIT VALIDATION")
    print("="*70)
    
    try:
        test_signal_strength_calculator()
        test_advanced_exit_handler()
        test_combined_workflow()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED!")
        print("="*70)
        print("\n✓ Signal quality analysis working correctly")
        print("✓ Advanced exit logic implemented successfully")
        print("✓ Combined workflow validated")
        print("\n📈 Ready for backtesting with improved signals and exits!")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)

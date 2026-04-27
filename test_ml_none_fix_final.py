#!/usr/bin/env python3
"""
Test script to verify ML=NONE fix
Tests that _last_symbol_report always has 'direction' key
"""
import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

# Add src to path
sys.path.insert(0, os.path.dirname(__file__))

from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy

async def test_ml_signal_generation():
    """Test that ML signals are never NONE"""
    print("\n" + "="*80)
    print("TEST: ML Signal Generation Fix")
    print("="*80)
    
    # Create strategy
    strategy = SimpleTrendStrategy(symbol="EUR/USD", verbose=False)
    print(f"✓ Strategy created for {strategy.symbol}")
    
    # Create fake market data (100 candles)
    now = datetime.now(timezone.utc)
    historical_data = []
    base_price = 1.0850
    
    for i in range(100):
        ts = now - timedelta(hours=100-i)
        # Create uptrend
        close = base_price + (i * 0.00005)
        bid = close - 0.0001
        ask = close + 0.0001
        
        historical_data.append(
            MarketData(
                symbol="EUR/USD",
                timestamp=ts,
                open=close - 0.00005,
                high=close + 0.00010,
                low=close - 0.00010,
                close=close,
                volume=1000000,
                bid=bid,
                ask=ask,
                spread=0.0002
            )
        )
    
    print(f"✓ Created {len(historical_data)} candles of test data")
    
    # Test 1: Call analyze() and check _last_symbol_report
    print("\n[TEST 1] Call analyze() with uptrend data...")
    signal = await strategy.analyze(historical_data)
    
    report = strategy._last_symbol_report
    print(f"\n_last_symbol_report keys: {list(report.keys())}")
    print(f"_last_symbol_report content: {report}")
    
    # Check for 'direction' key
    if 'direction' not in report:
        print("❌ FAILED: 'direction' key not in _last_symbol_report!")
        print(f"   Available keys: {list(report.keys())}")
        return False
    
    direction = report.get('direction')
    print(f"\n✓ 'direction' key found: {direction}")
    
    if direction == 'NONE':
        print("❌ FAILED: direction is NONE")
        return False
    
    if direction not in ('UP', 'DOWN'):
        print(f"❌ FAILED: direction is invalid ({direction}), expected UP or DOWN")
        return False
    
    print(f"✓ direction is valid: {direction}")
    
    # Check confidence
    confidence = report.get('confidence', 0.0)
    print(f"✓ confidence: {confidence:.2%}")
    
    if confidence <= 0:
        print("⚠ WARNING: confidence is 0 or negative (but not critical)")
    
    # Test 2: Verify RSI
    rsi = report.get('rsi', 0.0)
    print(f"✓ rsi: {rsi:.1f}")
    
    # Test 3: Check signal
    if signal is None:
        print("\n⚠ Signal is None (expected in some cases due to filters)")
        print("  But _last_symbol_report should still have ML direction")
    else:
        print(f"\n✓ Signal returned: {signal.direction.value if hasattr(signal.direction, 'value') else signal.direction}")
    
    print("\n" + "="*80)
    print("✅ TEST PASSED: ML signal generation working correctly!")
    print("="*80)
    return True

async def test_early_return_scenario():
    """Test that _last_symbol_report is populated even when analyze returns early"""
    print("\n" + "="*80)
    print("TEST: Early Return Scenario")
    print("="*80)
    
    strategy = SimpleTrendStrategy(symbol="GBP/USD", verbose=False)
    
    # Test with empty data (should return None early)
    print("\n[TEST 2a] Call analyze() with empty data...")
    signal = await strategy.analyze([])
    
    report = strategy._last_symbol_report
    print(f"_last_symbol_report: {report}")
    
    if 'direction' not in report:
        print("❌ FAILED: 'direction' key missing even with early return!")
        return False
    
    print(f"✓ Even with early return, _last_symbol_report has 'direction': {report.get('direction')}")
    
    # Test with minimal data (1 candle - should also return early)
    print("\n[TEST 2b] Call analyze() with 1 candle...")
    now = datetime.now(timezone.utc)
    minimal_data = [
        MarketData(
            symbol="GBP/USD",
            timestamp=now,
            open=1.2500,
            high=1.2510,
            low=1.2490,
            close=1.2505,
            volume=100000,
            bid=1.2500,
            ask=1.2510,
            spread=0.0010
        )
    ]
    
    signal = await strategy.analyze(minimal_data)
    report = strategy._last_symbol_report
    print(f"_last_symbol_report: {report}")
    
    if 'direction' not in report:
        print("❌ FAILED: 'direction' key missing with minimal data!")
        return False
    
    print(f"✓ With minimal data, _last_symbol_report has 'direction': {report.get('direction')}")
    
    print("\n" + "="*80)
    print("✅ TEST PASSED: Early returns handled correctly!")
    print("="*80)
    return True

async def main():
    """Run all tests"""
    print("\n\n")
    print("╔" + "="*78 + "╗")
    print("║" + " "*20 + "ML=NONE FIX VERIFICATION TEST" + " "*30 + "║")
    print("╚" + "="*78 + "╝")
    
    try:
        test1_passed = await test_ml_signal_generation()
        test2_passed = await test_early_return_scenario()
        
        print("\n\n")
        print("+" + "="*78 + "+")
        print("|" + "TEST SUMMARY".center(78) + "|")
        print("+" + "="*78 + "+")
        test1_status = '✅ PASSED' if test1_passed else '❌ FAILED'
        test2_status = '✅ PASSED' if test2_passed else '❌ FAILED'
        print(f"| Test 1 (ML Signal Generation): {test1_status.ljust(50)} |")
        print(f"| Test 2 (Early Return Handling): {test2_status.ljust(48)} |")
        print("+" + "="*78 + "+")
        
        if test1_passed and test2_passed:
            print("|" + "🎉 ALL TESTS PASSED - FIX VERIFIED!".center(78) + "|")
            print("+" + "="*78 + "+")
            print("\n✅ ML=NONE FIX IS WORKING CORRECTLY!")
            print("\nWhat was fixed:")
            print("  1. _last_symbol_report now uses 'direction' key (not 'ml_direction')")
            print("  2. Fallback values initialized at start of analyze()")
            print("  3. Early returns still populate the report with ML direction")
            print("  4. main.py now reads from correct 'direction' key in SYMBOL_REPORT")
            return True
        else:
            print("|" + "⚠ SOME TESTS FAILED - DEBUGGING NEEDED".center(78) + "|")
            print("+" + "="*78 + "+")
            return False
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

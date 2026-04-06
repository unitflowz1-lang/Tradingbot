"""
Quick test to verify historical data integration
Run this to validate the setup
"""

import sys
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.data.historical_data_loader import HistoricalDataLoader
from src.data.hybrid_data_provider import HybridDataProvider
from datetime import datetime, timezone


def test_historical_loader():
    """Test 1: Historical Data Loader"""
    print("\n" + "="*60)
    print("TEST 1: Historical Data Loader")
    print("="*60)

    loader = HistoricalDataLoader()

    # Check files exist
    files = loader.list_available_files()
    assert files, "❌ No data files found"
    print(f"✓ Found {len(files)} data file(s)")

    # Load data
    data = loader.load_eurusd_data()
    assert data, "❌ Failed to load EURUSD data"
    assert len(data) > 0, "❌ No candles loaded"
    print(f"✓ Loaded {len(data)} EURUSD candles")

    # Verify data structure
    candle = data[0]
    assert hasattr(candle, 'timestamp'), "❌ Missing timestamp"
    assert hasattr(candle, 'close'), "❌ Missing close price"
    assert hasattr(candle, 'open'), "❌ Missing open price"
    assert hasattr(candle, 'high'), "❌ Missing high price"
    assert hasattr(candle, 'low'), "❌ Missing low price"
    assert hasattr(candle, 'volume'), "❌ Missing volume"
    print("✓ All required fields present")

    # Verify data integrity
    assert candle.close > 0, "❌ Invalid close price"
    assert candle.high >= candle.open, "❌ Invalid OHLC relationship"
    assert candle.high >= candle.close, "❌ Invalid OHLC relationship"
    assert candle.low <= candle.open, "❌ Invalid OHLC relationship"
    assert candle.low <= candle.close, "❌ Invalid OHLC relationship"
    print("✓ Data integrity verified")

    return True


def test_hybrid_provider():
    """Test 2: Hybrid Data Provider"""
    print("\n" + "="*60)
    print("TEST 2: Hybrid Data Provider")
    print("="*60)

    provider = HybridDataProvider()

    # Test get_historical_data
    data = provider.get_historical_data('EUR/USD', count=50)
    assert data, "❌ Failed to get historical data"
    assert len(data) == 50, "❌ Wrong number of candles returned"
    print(f"✓ Retrieved {len(data)} candles")

    # Test available symbols
    symbols = provider.list_available_symbols()
    assert 'EUR/USD' in symbols, "❌ EUR/USD not in available symbols"
    print(f"✓ Available symbols: {symbols}")

    # Test symbol info
    info = provider.get_symbol_info('EUR/USD')
    assert info.get('available'), "❌ EUR/USD not available"
    assert info.get('symbol') == 'EUR/USD', "❌ Wrong symbol in info"
    print(f"✓ Symbol info retrieved")
    print(f"  - Candles: {info.get('candle_count')}")
    print(f"  - Start: {info.get('start_time')}")
    print(f"  - End: {info.get('end_time')}")

    return True


def test_data_for_period():
    """Test 3: Data for Specific Period"""
    print("\n" + "="*60)
    print("TEST 3: Data for Specific Period")
    print("="*60)

    provider = HybridDataProvider()

    start = datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 12, 2, 0, 0, 0, tzinfo=timezone.utc)

    data = provider.get_data_for_period('EUR/USD', start, end)
    assert data, "❌ No data for period"
    assert all(start <= d.timestamp <= end for d in data), \
        "❌ Data outside specified period"
    print(f"✓ Retrieved {len(data)} candles for period")
    print(f"  - Start: {data[0].timestamp}")
    print(f"  - End: {data[-1].timestamp}")

    return True


def test_backtest_iterator():
    """Test 4: Backtest Iterator"""
    print("\n" + "="*60)
    print("TEST 4: Backtest Iterator")
    print("="*60)

    provider = HybridDataProvider()

    start = datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 12, 1, 1, 0, 0, tzinfo=timezone.utc)

    count = 0
    for candle in provider.backtest_data_iterator('EUR/USD', start, end):
        count += 1
        assert candle.timestamp >= start, "❌ Data before start date"
        assert candle.timestamp <= end, "❌ Data after end date"

    assert count > 0, "❌ No candles from iterator"
    print(f"✓ Iterator yielded {count} candles")
    print(f"  - Period: 1 hour")
    print(f"  - Candles/hour: {count}")

    return True


def test_file_info():
    """Test 5: File Information"""
    print("\n" + "="*60)
    print("TEST 5: File Information")
    print("="*60)

    loader = HistoricalDataLoader()
    files = loader.list_available_files()

    assert files, "❌ No files found"
    print(f"✓ Found {len(files)} file(s):")

    for filename in files:
        info = loader.get_file_info(filename)
        assert info, "❌ Failed to get file info"
        assert info.get('filename'), "❌ Missing filename"
        assert info.get('candle_count') > 0, "❌ No candles in file"

        print(f"\n  📊 {filename}")
        print(f"     Symbol: {info.get('symbol')}")
        print(f"     Candles: {info.get('candle_count')}")
        print(f"     Start: {info.get('start_time')}")
        print(f"     End: {info.get('end_time')}")

    return True


def run_all_tests():
    """Run all integration tests"""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  HISTORICAL DATA INTEGRATION TESTS".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")

    tests = [
        ("Historical Data Loader", test_historical_loader),
        ("Hybrid Data Provider", test_hybrid_provider),
        ("Data for Period", test_data_for_period),
        ("Backtest Iterator", test_backtest_iterator),
        ("File Information", test_file_info),
    ]

    passed = 0
    failed = 0

    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            print(f"\n✗ {test_name} FAILED")
            print(f"  {str(e)}")
            failed += 1
        except Exception as e:
            print(f"\n✗ {test_name} ERROR")
            print(f"  {type(e).__name__}: {str(e)}")
            failed += 1

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")
    total = passed + failed
    if failed == 0:
        print(f"\n✓ All {total} tests passed!")
        print("\n✓ Historical data integration is working correctly")
        print("✓ You can now use the historical data in your trading bot")
    else:
        print(f"\n✗ {failed} test(s) failed")
        return False

    print("="*60 + "\n")
    return True


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

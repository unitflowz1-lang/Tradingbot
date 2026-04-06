"""
Example: Using Historical Data Loader

This demonstrates how to load and use the EURUSD historical data
from the EURUSD Data folder.
"""

import logging
from datetime import datetime, timezone, timedelta

from src.data.historical_data_loader import HistoricalDataLoader
from src.data.hybrid_data_provider import HybridDataProvider

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def example_load_eurusd_data():
    """Example 1: Load all EURUSD data from latest file"""
    print("\n" + "="*60)
    print("EXAMPLE 1: Load All EURUSD Data")
    print("="*60)

    loader = HistoricalDataLoader()

    # Load the latest EURUSD data file
    data = loader.load_eurusd_data()

    if data:
        print(f"✓ Loaded {len(data)} candles")
        print(f"  First candle: {data[0].timestamp}")
        print(f"  Last candle:  {data[-1].timestamp}")
        print(f"  First OHLC:   {data[0].open:.5f} / {data[0].high:.5f} / "
              f"{data[0].low:.5f} / {data[0].close:.5f}")
    else:
        print("✗ Failed to load data")


def example_list_files():
    """Example 2: List available data files"""
    print("\n" + "="*60)
    print("EXAMPLE 2: List Available Data Files")
    print("="*60)

    loader = HistoricalDataLoader()
    files = loader.list_available_files()

    if files:
        print(f"✓ Found {len(files)} data file(s):")
        for filename in files:
            info = loader.get_file_info(filename)
            if info:
                print(f"\n  📊 {filename}")
                print(f"     Symbol: {info.get('symbol')}")
                print(f"     Candles: {info.get('candle_count')}")
                start = info.get('start_time')
                end = info.get('end_time')
                if start and end:
                    print(f"     Period: {start} to {end}")
    else:
        print("✗ No data files found")


def example_get_period_data():
    """Example 3: Get data for a specific time period"""
    print("\n" + "="*60)
    print("EXAMPLE 3: Get Data for Specific Period")
    print("="*60)

    loader = HistoricalDataLoader()

    # Get data for December 2025
    start = datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 12, 2, 0, 0, 0, tzinfo=timezone.utc)

    # Get all files and load
    files = loader.list_available_files()
    if files:
        filename = files[0]
        data = loader.get_data_for_period(filename, start, end)
        print(f"✓ Retrieved {len(data)} candles for period:")
        print(f"  {start} to {end}")
        if data:
            print(f"  Price range: {min(d.low for d in data):.5f} - "
                  f"{max(d.high for d in data):.5f}")


def example_hybrid_provider():
    """Example 4: Use HybridDataProvider (with fallback)"""
    print("\n" + "="*60)
    print("EXAMPLE 4: Hybrid Data Provider")
    print("="*60)

    # Create hybrid provider (no MT5 broker in this example)
    provider = HybridDataProvider(mt5_broker=None)

    # Get last 50 candles
    data = provider.get_historical_data('EUR/USD', count=50)

    if data:
        print(f"✓ Retrieved {len(data)} candles via hybrid provider")
        print(f"  Latest candle: {data[-1].timestamp}")
        print(f"  Close price: {data[-1].close:.5f}")

    # List available symbols
    symbols = provider.list_available_symbols()
    print(f"\n✓ Available symbols: {symbols}")

    # Get symbol info
    info = provider.get_symbol_info('EUR/USD')
    print(f"\n✓ EUR/USD Info:")
    for key, value in info.items():
        print(f"    {key}: {value}")


def example_backtest_iterator():
    """Example 5: Use data iterator for backtesting"""
    print("\n" + "="*60)
    print("EXAMPLE 5: Backtest Data Iterator")
    print("="*60)

    provider = HybridDataProvider()

    # Define backtest period
    start = datetime(2025, 12, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 12, 1, 1, 0, 0, tzinfo=timezone.utc)

    candle_count = 0
    for candle in provider.backtest_data_iterator(
            'EUR/USD', start, end):
        candle_count += 1
        if candle_count <= 3 or candle_count % 10 == 0:
            print(f"  Candle {candle_count}: {candle.timestamp} - "
                  f"Close: {candle.close:.5f}")

    print(f"\n✓ Processed {candle_count} candles for backtest period")


def example_integration_with_trading_bot():
    """Example 6: Integration with trading bot"""
    print("\n" + "="*60)
    print("EXAMPLE 6: Integration with Trading Bot")
    print("="*60)

    # This is how you would integrate into main.py or other modules

    provider = HybridDataProvider()

    # Get current market data
    print("\nSimulating trading bot data retrieval:")
    symbols = ['EUR/USD']

    for symbol in symbols:
        data = provider.get_historical_data(symbol, count=100)

        if data:
            latest = data[-1]
            print(f"\n  {symbol}:")
            print(f"    Latest close: {latest.close:.5f}")
            print(f"    Latest high:  {latest.high:.5f}")
            print(f"    Latest low:   {latest.low:.5f}")
            print(f"    Timestamp:    {latest.timestamp}")

            # Calculate simple MA
            closes = [d.close for d in data[-20:]]
            ma20 = sum(closes) / len(closes)
            print(f"    MA20:         {ma20:.5f}")


if __name__ == "__main__":
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*58 + "║")
    print("║" + "  HISTORICAL DATA LOADER - USAGE EXAMPLES".center(58) + "║")
    print("║" + " "*58 + "║")
    print("╚" + "="*58 + "╝")

    # Run examples
    example_list_files()
    example_load_eurusd_data()
    example_get_period_data()
    example_hybrid_provider()
    example_backtest_iterator()
    example_integration_with_trading_bot()

    print("\n" + "="*60)
    print("Examples completed!")
    print("="*60 + "\n")

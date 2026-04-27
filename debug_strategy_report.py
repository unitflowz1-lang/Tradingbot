#!/usr/bin/env python3
"""
Debug script to see what's in strategy._last_symbol_report during bot run
"""
import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from src.data.mt5_broker import MetaTrader5Broker
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.models import MarketData

async def main():
    print("\n" + "="*80)
    print("DEBUG: Check strategy._last_symbol_report during real market data fetch")
    print("="*80)
    
    # Initialize broker
    print("\nInitializing MetaTrader5 broker...")
    broker = MetaTrader5Broker(demo=True, verbose=False)
    is_connected = broker.connect()
    print(f"✓ Broker connected: {is_connected}")
    
    if not is_connected:
        print("❌ Failed to connect to broker!")
        return False
    
    # Test symbols
    test_symbols = ["EUR/USD", "GBP/USD", "USD/JPY"]
    
    for symbol in test_symbols[:1]:  # Just test first symbol
        print(f"\n" + "="*80)
        print(f"Symbol: {symbol}")
        print("="*80)
        
        # Create strategy
        strategy = SimpleTrendStrategy(symbol=symbol, verbose=False)
        print(f"✓ Strategy created")
        
        # Get historical data from broker
        print(f"Fetching historical data for {symbol}...")
        historical_data = broker.get_historical_data(
            symbol=symbol,
            timeframe='H1',
            bars=100
        )
        
        if not historical_data:
            print(f"❌ No historical data for {symbol}")
            continue
        
        print(f"✓ Got {len(historical_data)} candles")
        
        # Before analyze
        print(f"\nBefore analyze():")
        print(f"  _last_symbol_report: {strategy._last_symbol_report}")
        
        # Run analyze
        print(f"\nCalling analyze()...")
        signal = await strategy.analyze(historical_data)
        
        # After analyze
        print(f"\nAfter analyze():")
        report = strategy._last_symbol_report
        print(f"  _last_symbol_report keys: {list(report.keys())}")
        print(f"  _last_symbol_report: {report}")
        
        if 'direction' in report:
            print(f"  ✓ direction = {report['direction']}")
            print(f"  ✓ confidence = {report.get('confidence', 'N/A')}")
            print(f"  ✓ rsi = {report.get('rsi', 'N/A')}")
        else:
            print(f"  ❌ 'direction' key missing!")
        
        print(f"\nSignal returned: {signal is not None}")
        if signal:
            print(f"  Signal direction: {signal.direction}")
            print(f"  Signal confidence: {signal.confidence}")
    
    broker.disconnect()
    return True

if __name__ == "__main__":
    asyncio.run(main())

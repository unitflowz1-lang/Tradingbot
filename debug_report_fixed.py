import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from src.data.mt5_broker import create_mt5_broker
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.models import MarketData

async def main():
    print("\n" + "="*80)
    print("DEBUG: Check strategy._last_symbol_report during real market data fetch")
    print("="*80)
    
    # Initialize broker using factory function
    print("\nInitializing MetaTrader5 broker...")
    try:
        broker = create_mt5_broker(monitored_symbols=["EURUSD"])
        is_connected = broker.connect()
        print(f"Broker connected: {is_connected}")
    except Exception as e:
        print(f"Broker connection failed: {e}")
        return
    
    if not is_connected:
        print("Cannot connect to MetaTrader5")
        return
    
    # Initialize strategy
    print("\nInitializing SimpleTrendStrategy...")
    strategy = SimpleTrendStrategy(symbol="EURUSD", timeframe="H1")
    
    print("\nFetching market data for EURUSD...")
    try:
        # Fetch market data
        market_data_list = broker.fetch_market_data("EURUSD")
        if market_data_list:
            print(f"Fetched {len(market_data_list)} market data points")
            
            # Show data before analyze
            print("\n" + "-"*80)
            print("BEFORE analyze():")
            print(f"strategy._last_symbol_report = {strategy._last_symbol_report}")
            
            # Run analyze on the most recent data
            latest_data = market_data_list[-1]
            print(f"\nAnalyzing: {latest_data}")
            
            result = strategy.analyze(latest_data)
            
            # Show data after analyze
            print("\n" + "-"*80)
            print("AFTER analyze():")
            print(f"strategy._last_symbol_report = {strategy._last_symbol_report}")
            print(f"\nAnalyze result: {result}")
            
            # Check for 'direction' key
            if strategy._last_symbol_report:
                print(f"\nKeys in _last_symbol_report: {list(strategy._last_symbol_report.keys())}")
                print(f"'direction' key present: {'direction' in strategy._last_symbol_report}")
            else:
                print("\n_last_symbol_report is None/empty")
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()
    finally:
        broker.disconnect()
        print("\nBroker disconnected")

if __name__ == "__main__":
    asyncio.run(main())

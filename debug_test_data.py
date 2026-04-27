import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
sys.path.insert(0, os.path.dirname(__file__))

from src.strategies.trend_strategy import SimpleTrendStrategy
from src.models import MarketData

async def main():
    print("\n" + "="*80)
    print("DEBUG: Check strategy._last_symbol_report during analysis")
    print("="*80)
    
    # Initialize strategy
    print("\nInitializing SimpleTrendStrategy...")
    strategy = SimpleTrendStrategy(symbol="EURUSD", verbose=False)
    
    print("\nCreating test market data...")
    try:
        # Create some test market data points
        current_time = datetime.now(timezone.utc)
        
        test_prices = [
            (1.0850, 1.0860, 100),  # close, high, volume
            (1.0855, 1.0865, 150),
            (1.0860, 1.0870, 120),
            (1.0865, 1.0875, 180),
            (1.0870, 1.0880, 200),
            (1.0875, 1.0885, 160),
        ]
        
        market_data_list = []
        for i, (close, high, volume) in enumerate(test_prices):
            data = MarketData(
                symbol="EURUSD",
                timestamp=current_time - timedelta(hours=len(test_prices)-i-1),
                open=close - 0.0005,
                high=high,
                low=close - 0.0010,
                close=close,
                volume=volume,
                bid=close - 0.0005,
                ask=close + 0.0005,
                spread=0.0010
            )
            market_data_list.append(data)
        
        print(f"Created {len(market_data_list)} test market data points")
        
        # Show data before analyze
        print("\n" + "-"*80)
        print("BEFORE analyze():")
        print(f"strategy._last_symbol_report = {strategy._last_symbol_report}")
        
        # Run analyze on all data points sequentially
        for i, data in enumerate(market_data_list):
            print(f"\nAnalyzing point {i+1}/{len(market_data_list)}: {data.timestamp}, Close={data.close}")
            result = await strategy.analyze(data)
            print(f"  Result: {result}")
            
            # Show intermediate state after each analysis
            if i == len(market_data_list) - 1:
                # Final analysis
                print("\n" + "-"*80)
                print("AFTER final analyze():")
                print(f"strategy._last_symbol_report = {strategy._last_symbol_report}")
                print(f"\nFinal analyze result: {result}")
                
                # Check for 'direction' key
                if strategy._last_symbol_report:
                    print(f"\nKeys in _last_symbol_report: {list(strategy._last_symbol_report.keys())}")
                    print(f"'direction' key present: {'direction' in strategy._last_symbol_report}")
                    if 'direction' in strategy._last_symbol_report:
                        print(f"'direction' value: {strategy._last_symbol_report['direction']}")
                    # Print the full report
                    print(f"\nFull _last_symbol_report content:")
                    for key, value in strategy._last_symbol_report.items():
                        print(f"  {key}: {value}")
                else:
                    print("\n_last_symbol_report is None/empty")
    except Exception as e:
        print(f"Error during analysis: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
Diagnostic script to test signal generation
"""
import asyncio
import sys
import os

os.chdir("c:\\Users\\macki\\Desktop\\TradingBot")
sys.path.insert(0, "c:\\Users\\macki\\Desktop\\TradingBot")

from src.data.mt5_broker import MT5BrokerInterface
from src.strategies.trend_strategy import SimpleTrendStrategy
import MetaTrader5 as mt5

async def test_signals():
    """Test signal generation for each symbol"""
    
    print("Testing signal generation...")
    
    # Initialize MT5
    if not mt5.initialize():
        print("❌ MT5 init failed")
        return
    
    # Login
    if not mt5.login(5044383203, "!t1bTkHu", "ExLTS*DO"):
        print("❌ Login failed")
        return
    
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
    
    for symbol in symbols:
        print(f"\n{'='*60}")
        print(f"Testing: {symbol}")
        print(f"{'='*60}")
        
        # Get historical data
        mt5_symbol = symbol.replace("/", "")
        rates = mt5.copy_rates_from_pos(mt5_symbol, mt5.TIMEFRAME_H1, 0, 100)
        
        if rates is None:
            print(f"❌ Failed to get data for {symbol}")
            continue
        
        from src.models import MarketData
        from datetime import datetime, timezone
        
        historical_data = []
        for rate in rates:
            ts = datetime.fromtimestamp(rate['time'], tz=timezone.utc)
            md = MarketData(
                symbol=symbol,
                timestamp=ts,
                open=rate['open'],
                high=rate['high'],
                low=rate['low'],
                close=rate['close'],
                volume=int(rate['tick_volume'])
            )
            historical_data.append(md)
        
        # Create strategy
        strategy = SimpleTrendStrategy(symbol, verbose=True)
        
        # Analyze
        signal = await strategy.analyze(historical_data)
        
        if signal:
            print(f"\n✅ SIGNAL GENERATED!")
            print(f"   Direction: {signal.direction}")
            print(f"   Entry: {signal.entry_price}")
            print(f"   Confidence: {signal.confidence if hasattr(signal, 'confidence') else 'N/A'}")
        else:
            print(f"\n❌ NO SIGNAL (filtered out)")
    
    mt5.shutdown()

if __name__ == "__main__":
    asyncio.run(test_signals())

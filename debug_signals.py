#!/usr/bin/env python3
"""
Debug Backtest - Check if signals are being generated
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict

from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.models import MarketData
from src.logging_config import setup_logging

async def debug_backtest():
    # 1. Setup Logging
    setup_logging(log_level="INFO")
    logger = logging.getLogger(__name__)
    
    print("\n[DEBUG] Starting signal generation test...")

    # 2. Configuration
    config_manager = ConfigManager('mt5')
    config = config_manager.get_config()
    symbols = ["EUR/USD"]
    
    # 3. Connection to MT5
    broker = create_mt5_broker(
        login=config.broker.login,
        password=config.broker.password,
        server=config.broker.server
    )
    
    if not await broker.connect():
        logger.error("Failed to connect to MT5")
        print("[ERROR] Cannot connect to MT5 - will use historical data")

    try:
        # Fetch data
        print("\n[STEP 1] Loading data...")
        all_market_data = {}
        for symbol in symbols:
            try:
                data = await broker.get_historical_data(symbol, timeframe=16385, count=200)
                if data:
                    all_market_data[symbol] = data
                    print(f"  {symbol}: {len(data)} bars loaded")
            except:
                print(f"  {symbol}: Failed to fetch (will skip)")

        if not all_market_data:
            print("[ERROR] No data available")
            return

        # Generate signals
        print("\n[STEP 2] Generating signals...")
        all_signals = []
        
        for symbol in symbols:
            strategy = SimpleTrendStrategy(symbol, verbose=True)
            data_list = all_market_data[symbol]
            
            print(f"\nAnalyzing {symbol} ({len(data_list)} bars)...")
            
            # Start from bar 100
            for i in range(100, min(150, len(data_list))):  # Just first 50 bars
                window = data_list[:i+1]
                signal = await strategy.analyze(window)
                if signal:
                    all_signals.append(signal)
                    print(f"  Bar {i}: {signal.direction.value} @ {signal.entry_price:.5f} (confidence: {signal.confidence*100:.0f}%)")
                    
                    if len(all_signals) >= 5:  # Just show first 5
                        break
        
        print(f"\n[RESULT] Generated {len(all_signals)} signals total")
        
        if len(all_signals) == 0:
            print("[DEBUG] No signals generated - checking possible issues...")
            
            # Test strategy directly with last window
            strategy = SimpleTrendStrategy(symbols[0], verbose=True)
            data_list = all_market_data[symbols[0]]
            window = data_list[-50:]
            
            print(f"\nTesting with last 50 bars...")
            signal = await strategy.analyze(window)
            print(f"Signal result: {signal}")

    finally:
        try:
            await broker.disconnect()
        except:
            pass

if __name__ == "__main__":
    asyncio.run(debug_backtest())

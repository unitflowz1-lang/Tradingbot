#!/usr/bin/env python3
"""
Check actual ATR values for 200 bars of data
"""
import asyncio
from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator

async def check_atr():
    config_manager = ConfigManager('mt5')
    config = config_manager.get_config()
    broker = create_mt5_broker(
        login=config.broker.login,
        password=config.broker.password,
        server=config.broker.server
    )
    
    if not await broker.connect():
        print("[ERROR] Cannot connect")
        return
    
    try:
        # Get full 200-bar window
        data = await broker.get_historical_data("EUR/USD", timeframe=16385, count=200)
        print(f"\nFull 200 bars of data:")
        
        for period in [10, 14, 20, 30]:
            calc = StopLossTakeProfitCalculator(atr_period=period)
            atr = calc.calculate_atr(data)
            atr_pips = atr * 10000
            print(f"  ATR{period}: {atr:.5f} ({atr_pips:.1f} pips)")
        
        # Compare with last 50 bars
        print(f"\nLast 50 bars only:")
        window = data[-50:]
        
        for period in [10, 14, 20, 30]:
            calc = StopLossTakeProfitCalculator(atr_period=period)
            atr = calc.calculate_atr(window)
            atr_pips = atr * 10000
            print(f"  ATR{period}: {atr:.5f} ({atr_pips:.1f} pips)")
    
    finally:
        await broker.disconnect()

if __name__ == "__main__":
    asyncio.run(check_atr())

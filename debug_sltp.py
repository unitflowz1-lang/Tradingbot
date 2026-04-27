#!/usr/bin/env python3
"""
Debug script to check SL/TP calculation
"""
import asyncio
import logging
import os
from datetime import datetime
from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.risk.sl_tp_calculator import StopLossTakeProfitCalculator
from src.models import Direction

async def debug_sltp():
    print("\n[DEBUG] SL/TP Calculation Test\n")
    
    # Setup
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
        # Get data
        data = await broker.get_historical_data("EUR/USD", timeframe=16385, count=200)
        if not data:
            print("[ERROR] No data")
            return
        
        print(f"Loaded {len(data)} bars")
        
        # Test with different ATR values
        for atr_period in [10, 14, 20, 30]:
            for risk_ratio in [1.0, 1.5, 2.0]:
                calc = StopLossTakeProfitCalculator(atr_period=atr_period, risk_reward_ratio=risk_ratio)
                
                # Use last 50 bars
                window = data[-50:]
                entry = window[-1].close
                
                atr = calc.calculate_atr(window)
                sl, tp = calc.calculate_levels(entry, Direction.LONG, window)
                
                sl_dist = entry - sl
                tp_dist = tp - entry
                
                print(f"\nATR{atr_period}_RR{risk_ratio}: Entry={entry:.5f} | ATR={atr:.5f}")
                print(f"  SL={sl:.5f} (dist: {sl_dist:.5f}) | TP={tp:.5f} (dist: {tp_dist:.5f})")
                print(f"  SL pips: {sl_dist*10000:.1f} | TP pips: {tp_dist*10000:.1f}")
    
    finally:
        await broker.disconnect()

if __name__ == "__main__":
    asyncio.run(debug_sltp())

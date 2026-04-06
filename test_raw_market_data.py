#!/usr/bin/env python3
"""
Test Raw Market Data - Bypass validation
"""

import MetaTrader5 as mt5
import asyncio

async def test_raw_market_data():
    """Test raw market data from MT5"""
    print("🔍 Testing Raw Market Data")
    print("=" * 40)
    
    try:
        # Initialize MT5
        if not mt5.initialize():
            error = mt5.last_error()
            print(f"❌ MT5 initialization failed: {error}")
            return
        
        print("✅ MT5 initialized successfully!")
        
        # Get account info
        account = mt5.account_info()
        if account:
            print(f"👤 Account: {account.login}")
            print(f"💰 Balance: ${account.balance:.2f}")
        
        # Test raw market data
        print(f"\n📊 Raw Market Data:")
        symbols = ["EURUSD", "GBPUSD", "USDJPY"]
        
        for symbol in symbols:
            print(f"\n🔍 Testing {symbol}:")
            
            # Get tick data
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                print(f"   ✅ Tick Data:")
                print(f"      Time: {tick.time}")
                print(f"      Bid: {tick.bid}")
                print(f"      Ask: {tick.ask}")
                print(f"      Last: {tick.last}")
                print(f"      Volume: {tick.volume}")
                print(f"      Spread: {tick.ask - tick.bid:.5f}")
            else:
                print(f"   ❌ No tick data available")
            
            # Get symbol info
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info:
                print(f"   ✅ Symbol Info:")
                print(f"      Name: {symbol_info.name}")
                print(f"      Point: {symbol_info.point}")
                print(f"      Digits: {symbol_info.digits}")
                print(f"      Spread: {symbol_info.spread}")
                print(f"      Trade Mode: {symbol_info.trade_mode}")
            else:
                print(f"   ❌ No symbol info available")
        
        # Test if we can place orders (simulation)
        print(f"\n🎯 Testing Order Capabilities:")
        symbol_info = mt5.symbol_info("EURUSD")
        if symbol_info:
            print(f"   Symbol: EURUSD")
            print(f"   Trade Mode: {symbol_info.trade_mode}")
            print(f"   Min Volume: {symbol_info.volume_min}")
            print(f"   Max Volume: {symbol_info.volume_max}")
            print(f"   Volume Step: {symbol_info.volume_step}")
            
            if symbol_info.trade_mode == 4:  # Full trading
                print(f"   ✅ Full trading allowed")
            elif symbol_info.trade_mode == 3:  # Close only
                print(f"   ⚠️  Close only mode")
            else:
                print(f"   ❌ Trading disabled")
        
        mt5.shutdown()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main function"""
    success = await test_raw_market_data()
    
    if success:
        print(f"\n🎉 Raw market data test successful!")
        print(f"The MT5 connection and data access is working perfectly.")
    else:
        print(f"\n❌ Raw market data test failed.")

if __name__ == "__main__":
    asyncio.run(main())
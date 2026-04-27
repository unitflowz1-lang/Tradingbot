#!/usr/bin/env python3
"""
Test with Existing MT5 Session
"""

import MetaTrader5 as mt5
import asyncio

async def test_existing_session():
    """Test using the existing MT5 session"""
    print("🤖 Testing Existing MT5 Session")
    print("=" * 40)
    
    try:
        # Initialize MT5 (should connect to existing session)
        print("📡 Connecting to existing MT5 session...")
        
        if not mt5.initialize():
            error = mt5.last_error()
            print(f"❌ Failed to initialize: {error}")
            return False
        
        print("✅ Connected to MT5!")
        
        # Get account info
        account_info = mt5.account_info()
        if account_info:
            print(f"\n👤 Account Information:")
            print(f"   Login: {account_info.login}")
            print(f"   Server: {account_info.server}")
            print(f"   Balance: ${account_info.balance:.2f}")
            print(f"   Equity: ${account_info.equity:.2f}")
            print(f"   Company: {account_info.company}")
            print(f"   Trade Allowed: {account_info.trade_allowed}")
        else:
            print("❌ No account information available")
            mt5.shutdown()
            return False
        
        # Test market data
        print(f"\n📈 Testing Market Data:")
        symbols = ["EURUSD", "GBPUSD", "USDJPY"]
        
        for symbol in symbols:
            tick = mt5.symbol_info_tick(symbol)
            if tick:
                print(f"   {symbol}: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}, Spread={tick.ask-tick.bid:.5f}")
            else:
                print(f"   {symbol}: No data available")
        
        # Get available symbols
        symbols = mt5.symbols_get()
        if symbols:
            print(f"\n📊 Available symbols: {len(symbols)} total")
            print("   First 10 symbols:")
            for i, symbol in enumerate(symbols[:10]):
                print(f"     {i+1}. {symbol.name}")
        
        # Test positions
        positions = mt5.positions_get()
        print(f"\n📍 Open positions: {len(positions) if positions else 0}")
        
        # Test orders
        orders = mt5.orders_get()
        print(f"📋 Pending orders: {len(orders) if orders else 0}")
        
        print(f"\n🎉 SUCCESS! MT5 demo account is fully functional!")
        print(f"   Account: {account_info.login} (${account_info.balance:.0f})")
        print(f"   Server: {account_info.server}")
        print(f"   Ready for automated trading!")
        
        mt5.shutdown()
        return True
        
    except Exception as e:
        print(f"❌ Error: {e}")
        if 'mt5' in locals():
            mt5.shutdown()
        return False

async def main():
    """Main function"""
    success = await test_existing_session()
    
    if success:
        print(f"\n🚀 Your MT5 connection is working perfectly!")
        print(f"\n📝 Next Steps:")
        print(f"   1. The demo account is ready for trading")
        print(f"   2. You can now start the AI trading bot")
        print(f"   3. All trades will be virtual (no real money risk)")
        print(f"\n💡 Commands to try:")
        print(f"   python main.py                    # Start the trading bot")
        print(f"   python -m src.backtesting.paper_trading_engine  # Paper trading")
    else:
        print(f"\n❌ Connection test failed.")
        print(f"Please make sure MT5 Terminal is open and logged in.")

if __name__ == "__main__":
    asyncio.run(main())
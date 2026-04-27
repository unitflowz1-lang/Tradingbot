#!/usr/bin/env python3
"""
Test Order Fix - Verify the comment field fix works
"""

import MetaTrader5 as mt5
from datetime import datetime

def test_order_request():
    """Test a simple order request to verify the fix"""
    
    # Initialize MT5
    if not mt5.initialize():
        print("Failed to initialize MT5")
        return
    
    # Login to demo account
    login = 95185205
    password = "QxE@7tYo"
    server = "MetaQuotes-Demo"
    
    if not mt5.login(login, password, server):
        print(f"Failed to login: {mt5.last_error()}")
        mt5.shutdown()
        return
    
    print("✅ Connected to MT5")
    
    # Get current price for EURUSD
    symbol = "EURUSD"
    tick = mt5.symbol_info_tick(symbol)
    
    if not tick:
        print(f"❌ Failed to get tick data for {symbol}")
        mt5.shutdown()
        return
    
    print(f"📊 Current {symbol} price: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}")
    
    # Test order request (we won't actually send it, just validate the format)
    test_request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": 0.01,  # Micro lot
        "type": mt5.ORDER_TYPE_BUY,
        "price": tick.ask,
        "sl": tick.ask - 0.0020,  # 20 pips stop loss
        "tp": tick.ask + 0.0030,  # 30 pips take profit
        "deviation": 20,
        "magic": 234000,
        "comment": "AIBot",  # Fixed comment
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }
    
    print("\n🔍 Testing order request format:")
    for key, value in test_request.items():
        print(f"   {key}: {value}")
    
    # Check if we should actually send the order
    response = input("\n🚀 Send test order? (y/n): ")
    
    if response.lower() in ['y', 'yes']:
        print("📤 Sending test order...")
        result = mt5.order_send(test_request)
        
        if result is None:
            error = mt5.last_error()
            print(f"❌ Order failed: {error}")
        else:
            print(f"✅ Order result: {result}")
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"🎉 Order executed successfully!")
                print(f"   Order ID: {result.order}")
                print(f"   Fill Price: {result.price:.5f}")
                
                # Close the position immediately for testing
                print("🔄 Closing test position...")
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": 0.01,
                    "type": mt5.ORDER_TYPE_SELL,
                    "position": result.order,
                    "price": tick.bid,
                    "deviation": 20,
                    "magic": 234000,
                    "comment": "AIBot",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_FOK,
                }
                
                close_result = mt5.order_send(close_request)
                if close_result and close_result.retcode == mt5.TRADE_RETCODE_DONE:
                    print("✅ Test position closed successfully")
                else:
                    print(f"⚠️  Failed to close test position: {close_result}")
            else:
                print(f"❌ Order failed with code: {result.retcode}")
                print(f"   Comment: {result.comment}")
    else:
        print("📋 Order format test completed (not sent)")
    
    mt5.shutdown()
    print("👋 Disconnected from MT5")

if __name__ == "__main__":
    test_order_request()
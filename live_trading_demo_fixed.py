#!/usr/bin/env python3
"""
Fixed Live Trading Demo - Test actual order execution with MT5
All issues resolved: comment field, filling mode, error handling
"""

import MetaTrader5 as mt5
import time
from datetime import datetime

def initialize_mt5():
    """Initialize MT5 connection"""
    if not mt5.initialize():
        print(f"❌ MT5 initialization failed: {mt5.last_error()}")
        return False
    
    # Login to demo account
    login = 95185205
    password = "QxE@7tYo"
    server = "MetaQuotes-Demo"
    
    if not mt5.login(login, password, server):
        print(f"❌ Login failed: {mt5.last_error()}")
        mt5.shutdown()
        return False
    
    print("✅ Connected to MT5 successfully")
    return True

def get_account_info():
    """Get and display account information"""
    account = mt5.account_info()
    if account:
        print(f"💰 Account Balance: ${account.balance:.2f}")
        print(f"💎 Equity: ${account.equity:.2f}")
        print(f"📊 Margin Used: ${account.margin:.2f}")
        return account
    return None

def place_test_order(symbol="EURUSD", volume=0.01):
    """Place a test buy order"""
    print(f"\n🚀 Placing test order: {symbol}")
    
    # Get current price
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print(f"❌ Failed to get price for {symbol}")
        return None
    
    print(f"📊 Current price: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}")
    
    # Calculate stop loss and take profit
    entry_price = tick.ask
    stop_loss = entry_price - 0.0020  # 20 pips
    take_profit = entry_price + 0.0030  # 30 pips
    
    # Prepare order request
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": mt5.ORDER_TYPE_BUY,
        "price": entry_price,
        "sl": stop_loss,
        "tp": take_profit,
        "deviation": 20,
        "magic": 234000,
        "comment": "AIBot",  # Fixed comment
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,  # Fixed filling mode
    }
    
    print(f"📤 Sending order...")
    print(f"   Entry: {entry_price:.5f}")
    print(f"   Stop Loss: {stop_loss:.5f}")
    print(f"   Take Profit: {take_profit:.5f}")
    
    # Send order
    result = mt5.order_send(request)
    
    if result is None:
        error = mt5.last_error()
        print(f"❌ Order failed: {error}")
        return None
    
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ Order executed successfully!")
        print(f"   Order ID: {result.order}")
        print(f"   Deal ID: {result.deal}")
        print(f"   Fill Price: {result.price:.5f}")
        print(f"   Volume: {result.volume}")
        return result
    else:
        print(f"❌ Order failed with code: {result.retcode}")
        print(f"   Comment: {result.comment}")
        return None

def monitor_position(deal_id, duration=30):
    """Monitor the position for a specified duration"""
    print(f"\n📊 Monitoring position for {duration} seconds...")
    
    start_time = time.time()
    while time.time() - start_time < duration:
        positions = mt5.positions_get()
        
        if positions:
            for pos in positions:
                if pos.identifier == deal_id:
                    profit_color = "🟢" if pos.profit >= 0 else "🔴"
                    print(f"   {profit_color} P&L: ${pos.profit:.2f} | Price: {pos.price_current:.5f}")
                    break
            else:
                print("   Position closed or not found")
                break
        else:
            print("   No open positions")
            break
        
        time.sleep(5)

def close_position(symbol="EURUSD"):
    """Close all positions for the symbol"""
    print(f"\n🔄 Closing positions for {symbol}...")
    
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        print("   No positions to close")
        return True
    
    for pos in positions:
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            continue
        
        # Determine close price and order type
        if pos.type == 0:  # Buy position
            close_price = tick.bid
            order_type = mt5.ORDER_TYPE_SELL
        else:  # Sell position
            close_price = tick.ask
            order_type = mt5.ORDER_TYPE_BUY
        
        # Close request
        close_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": pos.ticket,
            "price": close_price,
            "deviation": 20,
            "magic": 234000,
            "comment": "AIBot",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        
        result = mt5.order_send(close_request)
        
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"   ✅ Position {pos.ticket} closed successfully")
            print(f"   Final P&L: ${pos.profit:.2f}")
        else:
            print(f"   ❌ Failed to close position {pos.ticket}")
            if result:
                print(f"      Error: {result.comment}")

def main():
    """Main trading demo function"""
    print("🤖 Live Trading Demo - Fixed Version")
    print("=" * 50)
    print("⚠️  This will place REAL orders on your demo account")
    print("💰 Using virtual money - no real financial risk")
    print()
    
    # Confirm user wants to proceed
    response = input("🚀 Proceed with live trading demo? (y/n): ")
    if response.lower() not in ['y', 'yes']:
        print("Demo cancelled.")
        return
    
    # Initialize MT5
    if not initialize_mt5():
        return
    
    try:
        # Show account info
        account = get_account_info()
        if not account:
            return
        
        # Place test order
        result = place_test_order()
        if not result:
            return
        
        # Monitor the position
        monitor_position(result.deal)
        
        # Close positions
        close_position()
        
        # Final account info
        print(f"\n📈 Final Results:")
        final_account = get_account_info()
        if final_account and account:
            pnl = final_account.balance - account.balance
            pnl_color = "🟢" if pnl >= 0 else "🔴"
            print(f"   {pnl_color} Session P&L: ${pnl:.2f}")
        
        print(f"\n🎉 Live trading demo completed successfully!")
        
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        
    finally:
        # Cleanup
        print(f"\n🧹 Cleaning up...")
        close_position()  # Ensure all positions are closed
        mt5.shutdown()
        print(f"👋 Disconnected from MT5")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Test MetaTrader 5 Connection
"""

import asyncio
import sys
from pathlib import Path

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.data.mt5_broker import create_mt5_broker


async def test_mt5_connection():
    """Test MT5 connection and basic functionality"""
    print("🔗 Testing MetaTrader 5 Connection...")
    print("=" * 60)
    
    # Try different server names
    servers_to_try = [
        "ExLTS*DO",
        "MetaQuotes-Demo",
        "MetaQuotes-Demo2", 
        "MetaQuotes-Demo3",
        "MetaQuotes-Demo4",
        "MetaQuotes-Demo5"
    ]
    
    broker = None
    
    for server in servers_to_try:
        print(f"\n📡 Trying server: {server}")
        
        # Create MT5 broker interface
        broker = create_mt5_broker(
            login=5038790723,
            password="CvTYV-W7",
            server=server
        )
        
        try:
            # Test connection
            connected = await broker.connect()
            
            if connected:
                print(f"✅ Successfully connected to MT5 using server: {server}")
                break
            else:
                print(f"❌ Failed to connect with server: {server}")
                await broker.disconnect()
                
        except Exception as e:
            print(f"❌ Error with server {server}: {e}")
            if broker:
                await broker.disconnect()
    
    if not broker or not broker.connected:
        print("\n❌ Failed to connect to MT5 with any server")
        print("\n🔍 Troubleshooting tips:")
        print("1. Make sure MetaTrader 5 is installed and running")
        print("2. Verify your login credentials (5038790723)")
        print("3. Check if your demo account is active")
        print("4. Try logging into MT5 manually first")
        print("5. Contact your broker for the correct server name")
        return False
    
    try:
        # Get account info
        print("\n📊 Getting account information...")
        account_info = await broker.get_account_info()
        
        print(f"💰 Balance: ${account_info.balance:.2f}")
        print(f"📈 Equity: ${account_info.equity:.2f}")
        print(f"💳 Margin: ${account_info.margin:.2f}")
        print(f"🆓 Free Margin: ${account_info.free_margin:.2f}")
        print(f"📋 Open Positions: {len(account_info.positions)}")
        
        # Get market data for EUR/USD
        print("\n📈 Getting EUR/USD market data...")
        market_data = await broker.get_market_data("EUR/USD")
        
        print(f"💱 Symbol: {market_data.symbol}")
        print(f"📉 Bid: {market_data.bid}")
        print(f"📈 Ask: {market_data.ask}")
        print(f"💰 Last Price: {market_data.last_price}")
        print(f"📊 Spread: {market_data.spread}")
        print(f"⏰ Timestamp: {market_data.timestamp}")
        
        # Get positions
        print("\n📋 Getting open positions...")
        positions = await broker.get_positions()
        
        if positions:
            print(f"Found {len(positions)} open positions:")
            for pos in positions:
                print(f"  - {pos.symbol} {pos.direction.value} {pos.size} lots")
                print(f"    Entry: {pos.entry_price}, Current: {pos.current_price}")
                print(f"    Profit: ${pos.profit:.2f}")
        else:
            print("No open positions found.")
        
        # Get pending orders
        print("\n⏳ Getting pending orders...")
        orders = await broker.get_orders()
        
        if orders:
            print(f"Found {len(orders)} pending orders:")
            for order in orders:
                print(f"  - {order.symbol} {order.direction.value} {order.size} lots @ {order.price}")
        else:
            print("No pending orders found.")
        
        print("\n✅ MT5 connection test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Error during MT5 test: {e}")
        return False
    
    finally:
        # Disconnect
        print("\n🔌 Disconnecting from MT5...")
        await broker.disconnect()
        print("✅ Disconnected from MT5")


async def main():
    """Main function"""
    success = await test_mt5_connection()
    
    if success:
        print("\n🎉 MT5 integration is working correctly!")
        print("You can now use the trading bot with your MT5 demo account.")
    else:
        print("\n⚠️  MT5 integration test failed.")
        print("Please check your credentials and MT5 installation.")


if __name__ == "__main__":
    asyncio.run(main()) 
#!/usr/bin/env python3
"""
Test New Demo Account
Username: 95185205
Password: QxE@7tYo
"""

import MetaTrader5 as mt5
import asyncio
from src.data.mt5_broker import MT5BrokerInterface

def test_direct_connection():
    """Test direct MT5 connection with new account"""
    print("🔧 Testing New Demo Account - Direct Connection")
    print("=" * 50)
    print("Username: 95185205")
    print("Password: QxE@7tYo")
    print("Server: MetaQuotes-Demo")
    print("-" * 50)
    
    # Test 1: Check if already logged in
    print("\n1️⃣ Checking current MT5 session...")
    try:
        if mt5.initialize():
            print("✅ MT5 initialized successfully!")
            
            account = mt5.account_info()
            if account:
                print(f"👤 Currently logged in as: {account.login}")
                print(f"🏦 Server: {account.server}")
                print(f"💰 Balance: ${account.balance:.2f}")
                
                if account.login == 95185205:
                    print("🎉 Already connected to your new demo account!")
                    
                    # Test market data
                    tick = mt5.symbol_info_tick("EURUSD")
                    if tick:
                        print(f"📈 EUR/USD: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}")
                        print("✅ Market data is working!")
                    
                    mt5.shutdown()
                    return True
                else:
                    print(f"⚠️  Connected to different account: {account.login}")
                    print("Need to login to the new account manually")
            else:
                print("❌ No account logged in")
            
            mt5.shutdown()
        else:
            error = mt5.last_error()
            print(f"❌ MT5 initialization failed: {error}")
            
            if error[0] == -6:
                print("💡 Authorization failed - need to login manually first")
            elif error[0] == -10005:
                print("💡 IPC timeout - need Administrator privileges")
    
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    return False

async def test_broker_interface():
    """Test using our broker interface"""
    print("\n2️⃣ Testing Broker Interface...")
    
    broker = MT5BrokerInterface(
        login=95185205,
        password="QxE@7tYo", 
        server="MetaQuotes-Demo"
    )
    
    try:
        print("📡 Attempting to connect...")
        connected = await broker.connect()
        
        if connected:
            print("✅ Broker interface connected!")
            
            # Get account info
            portfolio = await broker.get_account_info()
            print(f"💰 Balance: ${portfolio.balance:.2f}")
            print(f"💎 Equity: ${portfolio.equity:.2f}")
            print(f"📍 Positions: {len(portfolio.positions)}")
            
            # Test market data
            try:
                market_data = await broker.get_market_data("EUR/USD")
                print(f"📈 EUR/USD: Bid={market_data.bid:.5f}, Ask={market_data.ask:.5f}")
            except Exception as e:
                print(f"⚠️  Market data error: {e}")
            
            await broker.disconnect()
            return True
        else:
            print("❌ Broker interface connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Broker interface error: {e}")
        return False

def provide_setup_instructions():
    """Provide setup instructions for new account"""
    print("\n📋 SETUP INSTRUCTIONS FOR NEW ACCOUNT")
    print("=" * 50)
    
    print("\n🔑 Step 1: Login to MT5 Terminal")
    print("1. Open MT5 Terminal")
    print("2. File → Login to Trade Account (or Ctrl+L)")
    print("3. Enter credentials:")
    print("   Username: 95185205")
    print("   Password: QxE@7tYo")
    print("   Server: MetaQuotes-Demo")
    print("4. Click OK")
    
    print("\n⚙️ Step 2: Enable Algorithmic Trading")
    print("1. Tools → Options (or Ctrl+O)")
    print("2. Expert Advisors tab")
    print("3. Check: ✅ Allow algorithmic trading")
    print("4. Check: ✅ Allow DLL imports")
    print("5. Click OK")
    print("6. Make AutoTrading button GREEN")
    
    print("\n🧪 Step 3: Test Connection")
    print("Run as Administrator:")
    print("   python test_new_account.py")
    print("   python connect_mt5_demo.py")

async def main():
    """Main test function"""
    print("🤖 AI Trading Bot - New Demo Account Test")
    print("=" * 60)
    
    # Test direct connection first
    direct_success = test_direct_connection()
    
    if direct_success:
        # Test broker interface
        broker_success = await test_broker_interface()
        
        if broker_success:
            print("\n🎉 SUCCESS! New demo account is fully connected!")
            print("\n🚀 Ready for trading:")
            print("   python main.py                # Start trading bot")
            print("   python connect_mt5_demo.py    # Full connection test")
            return
    
    # If tests failed, provide instructions
    provide_setup_instructions()

if __name__ == "__main__":
    asyncio.run(main())
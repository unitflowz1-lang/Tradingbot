#!/usr/bin/env python3
"""
MT5 Test with Explicit Path
"""

import MetaTrader5 as mt5
import ctypes
import sys

def check_admin():
    """Check if running as administrator"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except:
        return False

def test_mt5_connection():
    """Test MT5 connection with explicit path"""
    print("🔧 MT5 Connection Test with Explicit Path")
    print("=" * 50)
    
    # Check admin status
    is_admin = check_admin()
    print(f"Administrator privileges: {'✅ YES' if is_admin else '❌ NO'}")
    
    if not is_admin:
        print("\n⚠️  WARNING: Not running as Administrator")
        print("This may cause connection issues.")
        print("For best results, run as Administrator.")
    
    # MT5 Terminal path
    mt5_path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    print(f"\nMT5 Path: {mt5_path}")
    
    # Test connection
    print("\n🔄 Attempting to connect to MT5...")
    
    try:
        # Initialize with explicit path
        result = mt5.initialize(path=mt5_path)
        
        if result:
            print("✅ MT5 initialized successfully!")
            
            # Get terminal info
            terminal_info = mt5.terminal_info()
            if terminal_info:
                print(f"\n📊 Terminal Information:")
                print(f"   Company: {terminal_info.company}")
                print(f"   Name: {terminal_info.name}")
                print(f"   Connected: {terminal_info.connected}")
                print(f"   Trade Allowed: {terminal_info.trade_allowed}")
                # Note: Some terminal info attributes may not be available
                try:
                    print(f"   Experts Enabled: {getattr(terminal_info, 'experts_enabled', 'N/A')}")
                    print(f"   DLL Allowed: {getattr(terminal_info, 'dlls_allowed', 'N/A')}")
                except:
                    print("   Expert/DLL info not available")
            
            # Check account info
            account_info = mt5.account_info()
            if account_info:
                print(f"\n👤 Account Information:")
                print(f"   Login: {account_info.login}")
                print(f"   Server: {account_info.server}")
                print(f"   Balance: ${account_info.balance:.2f}")
                print(f"   Equity: ${account_info.equity:.2f}")
                print(f"   Company: {account_info.company}")
                print(f"   Trade Allowed: {account_info.trade_allowed}")
                
                # Check if it's your demo account
                if account_info.login == 5044383203:
                    print("\n🎉 SUCCESS! Connected to your demo account!")
                    
                    # Test market data
                    print("\n📈 Testing market data...")
                    tick = mt5.symbol_info_tick("EURUSD")
                    if tick:
                        print(f"   EUR/USD: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}")
                        print("✅ Market data is working!")
                    else:
                        print("⚠️  Market data test failed")
                    
                    mt5.shutdown()
                    return True
                else:
                    print(f"\n⚠️  Connected to different account: {account_info.login}")
                    print("Expected: 5044383203 (your demo account)")
                    print("\n💡 Please login to your demo account in MT5 Terminal:")
                    print("   1. File → Login to Trade Account")
                    print("   2. Login: 5044383203")
                    print("   3. Password: !t1bTkHu")
                    print("   4. Server: ExLTS*DO")
            else:
                print("\n❌ No account logged in")
                print("\n💡 Please login to your demo account in MT5 Terminal first:")
                print("   1. Open MT5 Terminal")
                print("   2. File → Login to Trade Account")
                print("   3. Enter your credentials:")
                print("      Login: 5044383203")
                print("      Password: !t1bTkHu")
                print("      Server: ExLTS*DO")
            
            mt5.shutdown()
            return account_info is not None
            
        else:
            error = mt5.last_error()
            print(f"❌ MT5 initialization failed: {error}")
            
            # Provide specific error guidance
            if error[0] == -6:
                print("\n💡 Error -6 (Authorization failed) solutions:")
                print("   1. Run this script as Administrator")
                print("   2. Login manually in MT5 Terminal first")
                print("   3. Enable algorithmic trading in MT5 Options")
            elif error[0] == -10005:
                print("\n💡 Error -10005 (IPC timeout) solutions:")
                print("   1. Run as Administrator")
                print("   2. Restart MT5 Terminal")
                print("   3. Check if logged in to MT5 Terminal")
            
            return False
            
    except Exception as e:
        print(f"❌ Exception occurred: {e}")
        return False

def main():
    """Main function"""
    success = test_mt5_connection()
    
    if success:
        print("\n🎉 MT5 connection test successful!")
        print("You can now run the full trading bot:")
        print("   python connect_mt5_demo.py")
        print("   python main.py")
    else:
        print("\n❌ MT5 connection test failed.")
        print("\n🔧 Next steps:")
        print("1. Make sure you're logged into MT5 Terminal manually")
        print("2. Enable algorithmic trading: Tools → Options → Expert Advisors")
        print("3. Run this script as Administrator")
        print("4. Check that AutoTrading button is green in MT5")

if __name__ == "__main__":
    main()
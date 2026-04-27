#!/usr/bin/env python3
"""
Direct MT5 Test - Bypass our broker interface
"""

import MetaTrader5 as mt5
import time

def test_direct_mt5():
    """Test MT5 directly without our wrapper"""
    print("🔧 Direct MT5 Connection Test")
    print("=" * 40)
    
    # Step 1: Initialize
    print("\n1️⃣ Initializing MT5...")
    if not mt5.initialize():
        error = mt5.last_error()
        print(f"❌ Initialization failed: {error}")
        
        # Try to get more info about the error
        if error[0] == -6:
            print("\n💡 Error -6 means 'Authorization failed'")
            print("This usually means:")
            print("   - MT5 Terminal is not logged in")
            print("   - Need to run as Administrator")
            print("   - Algorithmic trading is disabled")
            
        return False
    
    print("✅ MT5 initialized successfully!")
    
    # Step 2: Check terminal info
    print("\n2️⃣ Getting terminal info...")
    terminal_info = mt5.terminal_info()
    if terminal_info:
        print(f"✅ Terminal Info:")
        print(f"   Name: {terminal_info.name}")
        print(f"   Company: {terminal_info.company}")
        print(f"   Connected: {terminal_info.connected}")
        print(f"   Trade Allowed: {terminal_info.trade_allowed}")
        print(f"   Experts Enabled: {terminal_info.experts_enabled}")
        print(f"   DLL Allowed: {terminal_info.dlls_allowed}")
    
    # Step 3: Check current account
    print("\n3️⃣ Checking current account...")
    account_info = mt5.account_info()
    if account_info:
        print(f"✅ Account Info:")
        print(f"   Login: {account_info.login}")
        print(f"   Server: {account_info.server}")
        print(f"   Balance: ${account_info.balance:.2f}")
        print(f"   Equity: ${account_info.equity:.2f}")
        print(f"   Company: {account_info.company}")
        print(f"   Trade Allowed: {account_info.trade_allowed}")
        print(f"   Trade Expert: {account_info.trade_expert}")
        
        # Check if it's our demo account
        if account_info.login == 5038790723:
            print("\n🎉 This is your demo account!")
        else:
            print(f"\n⚠️  This is not your demo account (expected: 5038790723)")
    else:
        print("❌ No account logged in")
        print("\n💡 You need to login manually in MT5 Terminal first:")
        print("   1. Open MT5 Terminal")
        print("   2. Go to File → Login to Trade Account")
        print("   3. Enter: Login=5038790723, Password=CvTYV-W7, Server=ExLTS*DO")
    
    # Step 4: Test market data
    print("\n4️⃣ Testing market data...")
    symbols = ["EURUSD", "GBPUSD", "USDJPY"]
    
    for symbol in symbols:
        tick = mt5.symbol_info_tick(symbol)
        if tick:
            print(f"✅ {symbol}: Bid={tick.bid:.5f}, Ask={tick.ask:.5f}")
        else:
            print(f"❌ {symbol}: No data available")
    
    # Step 5: Check symbols
    print("\n5️⃣ Available symbols...")
    symbols = mt5.symbols_get()
    if symbols:
        print(f"✅ Found {len(symbols)} symbols")
        # Show first few symbols
        for i, symbol in enumerate(symbols[:5]):
            print(f"   {symbol.name}")
    else:
        print("❌ No symbols available")
    
    mt5.shutdown()
    return True

def main():
    """Main function"""
    success = test_direct_mt5()
    
    if success:
        print("\n🎉 Direct MT5 test completed!")
        print("If you saw your account info above, the connection is working!")
    else:
        print("\n❌ Direct MT5 test failed.")
        print("Please try:")
        print("1. Login manually in MT5 Terminal")
        print("2. Enable algorithmic trading")
        print("3. Run as Administrator")

if __name__ == "__main__":
    main()
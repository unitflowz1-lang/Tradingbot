#!/usr/bin/env python3
"""
Simple MT5 Connection Test
Test basic MT5 functionality step by step
"""

import MetaTrader5 as mt5
import time

def test_mt5_step_by_step():
    """Test MT5 connection step by step with detailed feedback"""
    
    print("🔧 MT5 Connection Test - Step by Step")
    print("=" * 50)
    
    # Step 1: Initialize MT5
    print("\n1️⃣ Initializing MT5...")
    if not mt5.initialize():
        error = mt5.last_error()
        print(f"❌ MT5 initialization failed: {error}")
        print("\n💡 Possible solutions:")
        print("- Make sure MT5 Terminal is running")
        print("- Try running this script as Administrator")
        print("- Restart MT5 Terminal")
        return False
    
    print("✅ MT5 initialized successfully")
    
    # Step 2: Get terminal info
    print("\n2️⃣ Getting terminal information...")
    terminal_info = mt5.terminal_info()
    if terminal_info:
        print(f"✅ Terminal Info:")
        print(f"   Company: {terminal_info.company}")
        print(f"   Name: {terminal_info.name}")
        print(f"   Path: {terminal_info.path}")
        print(f"   Connected: {terminal_info.connected}")
        print(f"   Trade Allowed: {terminal_info.trade_allowed}")
    else:
        print("⚠️  Could not get terminal info")
    
    # Step 3: Check current account
    print("\n3️⃣ Checking current account...")
    account_info = mt5.account_info()
    if account_info:
        print(f"✅ Already logged in:")
        print(f"   Account: {account_info.login}")
        print(f"   Server: {account_info.server}")
        print(f"   Balance: ${account_info.balance:.2f}")
        print(f"   Company: {account_info.company}")
        print(f"   Trade Allowed: {account_info.trade_allowed}")
        
        # If already logged in to the correct account, we're done!
        if account_info.login == 5038790723:
            print("\n🎉 Already connected to your demo account!")
            mt5.shutdown()
            return True
    else:
        print("ℹ️  No active account session")
    
    # Step 4: Try to login
    print("\n4️⃣ Attempting to login to demo account...")
    
    # Try different server variations
    servers_to_try = [
        "ExLTS*DO",
        "ExLTS-Demo",
        "ExLTS",
        "ExLTS-MT5Demo",
        "ExLTS-Live",
        "MetaQuotes-Demo"
    ]
    
    login = 5038790723
    password = "CvTYV-W7"
    
    for server in servers_to_try:
        print(f"\n   🔄 Trying server: {server}")
        
        result = mt5.login(login=login, password=password, server=server)
        if result:
            print(f"   ✅ Successfully logged in to {server}!")
            
            # Verify account info
            account_info = mt5.account_info()
            if account_info:
                print(f"   📊 Account verified:")
                print(f"      Login: {account_info.login}")
                print(f"      Balance: ${account_info.balance:.2f}")
                print(f"      Server: {account_info.server}")
                print(f"      Company: {account_info.company}")
            
            mt5.shutdown()
            return True
        else:
            error = mt5.last_error()
            print(f"   ❌ Failed: {error}")
    
    print("\n❌ Could not login to any server")
    print("\n💡 Please try:")
    print("1. Login manually in MT5 Terminal first")
    print("2. Check that your demo account is still active")
    print("3. Verify the server name in MT5 Terminal")
    print("4. Contact your broker for the correct server name")
    
    mt5.shutdown()
    return False

def main():
    """Main function"""
    success = test_mt5_step_by_step()
    
    if success:
        print("\n🎉 MT5 connection test successful!")
        print("You can now run the full trading bot.")
    else:
        print("\n❌ MT5 connection test failed.")
        print("Please follow the manual setup guide.")

if __name__ == "__main__":
    main()
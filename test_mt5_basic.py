#!/usr/bin/env python3
"""
Basic MT5 Test - Minimal approach
"""

import MetaTrader5 as mt5
import sys
import os

def test_basic_mt5():
    """Test basic MT5 functionality"""
    print("🔧 Basic MT5 Test")
    print("=" * 30)
    
    # Check if we're running as admin
    try:
        is_admin = os.getuid() == 0
    except AttributeError:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
    
    print(f"Running as Administrator: {is_admin}")
    
    # Try different initialization approaches
    print("\n1️⃣ Testing MT5 initialization...")
    
    # Method 1: Basic initialization
    print("   Method 1: Basic init...")
    if mt5.initialize():
        print("   ✅ Basic initialization successful!")
        
        # Get terminal info
        terminal_info = mt5.terminal_info()
        if terminal_info:
            print(f"   📊 Terminal: {terminal_info.name}")
            print(f"   🏢 Company: {terminal_info.company}")
            print(f"   🔗 Connected: {terminal_info.connected}")
            print(f"   📈 Trade Allowed: {terminal_info.trade_allowed}")
        
        # Check if already logged in
        account_info = mt5.account_info()
        if account_info:
            print(f"   👤 Current Account: {account_info.login}")
            print(f"   🏦 Server: {account_info.server}")
            print(f"   💰 Balance: ${account_info.balance:.2f}")
            
            if account_info.login == 5038790723:
                print("   🎉 Already logged into your demo account!")
                mt5.shutdown()
                return True
        else:
            print("   ℹ️  No active account session")
        
        mt5.shutdown()
        return True
    else:
        error = mt5.last_error()
        print(f"   ❌ Failed: {error}")
    
    # Method 2: Try with path specification
    print("\n   Method 2: Init with path...")
    mt5_paths = [
        r"C:\Program Files\MetaTrader 5\terminal64.exe",
        r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"
    ]
    
    for path in mt5_paths:
        if os.path.exists(path):
            print(f"   Trying path: {path}")
            if mt5.initialize(path=path):
                print("   ✅ Path-based initialization successful!")
                mt5.shutdown()
                return True
            else:
                error = mt5.last_error()
                print(f"   ❌ Failed with path: {error}")
    
    # Method 3: Try with login parameter
    print("\n   Method 3: Init with login...")
    if mt5.initialize(login=5038790723, server="ExLTS*DO", password="CvTYV-W7"):
        print("   ✅ Login-based initialization successful!")
        mt5.shutdown()
        return True
    else:
        error = mt5.last_error()
        print(f"   ❌ Failed with login: {error}")
    
    return False

def main():
    """Main function"""
    print("🚀 Starting basic MT5 test...\n")
    
    success = test_basic_mt5()
    
    if success:
        print("\n✅ Basic MT5 test passed!")
        print("Now try running: python connect_mt5_demo.py")
    else:
        print("\n❌ All MT5 initialization methods failed.")
        print("\n🔧 Try these solutions:")
        print("1. Close MT5 Terminal completely")
        print("2. Restart MT5 Terminal")
        print("3. Login manually in MT5 Terminal first")
        print("4. Run this script as Administrator")
        print("5. Check if antivirus is blocking the connection")

if __name__ == "__main__":
    main()
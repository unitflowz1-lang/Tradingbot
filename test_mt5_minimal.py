#!/usr/bin/env python3
"""
Minimal MT5 Test - Try different initialization methods
"""

import MetaTrader5 as mt5
import time
import sys
import os

def test_minimal_mt5():
    """Minimal MT5 test with multiple approaches"""
    print("🔧 Minimal MT5 Test")
    print("=" * 30)
    
    # Check admin status
    try:
        import ctypes
        is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        print(f"Admin privileges: {is_admin}")
    except:
        print("Admin check failed")
    
    # Method 1: Basic initialization with timeout
    print("\n1️⃣ Basic initialization...")
    try:
        result = mt5.initialize()
        if result:
            print("✅ MT5 initialized!")
            
            # Quick check
            account = mt5.account_info()
            if account:
                print(f"   Account: {account.login}")
                print(f"   Balance: ${account.balance:.2f}")
                if account.login == 5038790723:
                    print("   🎉 Your demo account is connected!")
                    mt5.shutdown()
                    return True
            else:
                print("   ⚠️  No account logged in")
            
            mt5.shutdown()
            return True
        else:
            error = mt5.last_error()
            print(f"❌ Failed: {error}")
    except Exception as e:
        print(f"❌ Exception: {e}")
    
    # Method 2: Try with explicit path
    print("\n2️⃣ Trying with explicit path...")
    mt5_path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    if os.path.exists(mt5_path):
        try:
            result = mt5.initialize(path=mt5_path)
            if result:
                print("✅ Path-based initialization worked!")
                mt5.shutdown()
                return True
            else:
                error = mt5.last_error()
                print(f"❌ Path method failed: {error}")
        except Exception as e:
            print(f"❌ Path exception: {e}")
    else:
        print("❌ MT5 path not found")
    
    # Method 3: Try with timeout and retry
    print("\n3️⃣ Trying with retry logic...")
    for attempt in range(3):
        print(f"   Attempt {attempt + 1}/3...")
        try:
            time.sleep(1)  # Small delay
            result = mt5.initialize()
            if result:
                print("✅ Retry method worked!")
                mt5.shutdown()
                return True
            else:
                error = mt5.last_error()
                print(f"   ❌ Attempt {attempt + 1} failed: {error}")
        except Exception as e:
            print(f"   ❌ Attempt {attempt + 1} exception: {e}")
    
    return False

def check_mt5_process():
    """Check MT5 process details"""
    print("\n🔍 Checking MT5 process...")
    try:
        import psutil
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            if 'terminal' in proc.info['name'].lower():
                print(f"   Found: {proc.info['name']} (PID: {proc.info['pid']})")
                print(f"   Path: {proc.info['exe']}")
    except ImportError:
        print("   psutil not available, using basic check")
        import subprocess
        result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq terminal64.exe'], 
                              capture_output=True, text=True)
        if "terminal64.exe" in result.stdout:
            print("   ✅ terminal64.exe is running")
        else:
            print("   ❌ terminal64.exe not found")

def main():
    """Main function"""
    print("🚀 Starting minimal MT5 test...\n")
    
    check_mt5_process()
    
    success = test_minimal_mt5()
    
    if success:
        print("\n🎉 MT5 connection successful!")
        print("Now you can run: python connect_mt5_demo.py")
    else:
        print("\n❌ All connection attempts failed.")
        print("\n🔧 Next steps:")
        print("1. Make sure you're logged into MT5 Terminal manually")
        print("2. Enable 'Allow algorithmic trading' in MT5 Options")
        print("3. Try running this script as Administrator")
        print("4. Restart MT5 Terminal and try again")
        print("\n💡 To run as Administrator:")
        print("   Right-click PowerShell → 'Run as Administrator'")
        print("   Then run: python test_mt5_minimal.py")

if __name__ == "__main__":
    main()
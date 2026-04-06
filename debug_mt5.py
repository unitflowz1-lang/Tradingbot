
import MetaTrader5 as mt5
import sys

def test_bare():
    print("1. Testing bare initialization (connect to existing Open Terminal)...")
    if mt5.initialize():
        print("   ✅ Success")
        print(f"   Terminal: {mt5.terminal_info().path}")
        print(f"   Account: {mt5.account_info().login}")
        mt5.shutdown()
        return True
    else:
        err = mt5.last_error()
        print(f"   ❌ Failed: {err}")
        return False

def test_path():
    print("\n2. Testing path initialization...")
    path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    if mt5.initialize(path=path):
        print("   ✅ Success")
        mt5.shutdown()
        return True
    else:
        err = mt5.last_error()
        print(f"   ❌ Failed: {err}")
        return False

if __name__ == "__main__":
    print("--- MT5 DEBUG SCRIPT ---")
    if not test_bare():
        print("\nTrying with path...")
        test_path()
        
    print("\n------------------------")
    print("If you see Error -6 (Authorization failed), please:")
    print("1. OPEN MT5 Terminal manually")
    print("2. Go to File -> Login to Trade Account set: 95185205, QxE@7tYo, MetaQuotes-Demo")
    print("3. Go to Tools -> Options -> Expert Advisors -> Check 'Allow algorithmic trading' and 'Allow DLL imports'")
    print("4. Restart the Terminal")
    print("5. Run this script AGAIN as ADMINISTRATOR")


import ctypes
import os
import sys
import MetaTrader5 as mt5

def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

print(f"Python Executable: {sys.executable}")
print(f"Is Admin: {is_admin()}")
print(f"MT5 Package Version: {mt5.__version__}")

print("\nAttempting MT5 Init...")
if mt5.initialize():
    print("✅ Init SUCCESS")
    mt5.shutdown()
else:
    print(f"❌ Init FAILED: {mt5.last_error()}")

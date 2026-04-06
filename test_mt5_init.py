import MetaTrader5 as mt5
import os

def test():
    print("Testing mt5.initialize() without path...")
    if mt5.initialize():
        print("✅ Successfully initialized without path!")
        print(f"Terminal Info: {mt5.terminal_info()}")
        mt5.shutdown()
    else:
        print(f"❌ Failed without path: {mt5.last_error()}")
        
    print("\nTesting mt5.initialize() with specific path...")
    path = r"C:\Program Files\MetaTrader 5\terminal64.exe"
    if mt5.initialize(path=path):
        print("✅ Successfully initialized with path!")
        mt5.shutdown()
    else:
        print(f"❌ Failed with path: {mt5.last_error()}")

if __name__ == "__main__":
    test()

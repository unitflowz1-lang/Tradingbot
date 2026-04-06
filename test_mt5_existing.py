import MetaTrader5 as mt5

def test_existing():
    print("Attempting to connect to existing MT5 terminal...")
    # initialize() without arguments tries to connect to a running terminal
    if mt5.initialize():
        print("✅ Successfully connected to existing terminal!")
        print(f"Account: {mt5.account_info().login if mt5.account_info() else 'N/A'}")
        mt5.shutdown()
    else:
        print(f"❌ Failed: {mt5.last_error()}")

if __name__ == "__main__":
    test_existing()

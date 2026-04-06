import MetaTrader5 as mt5

def check():
    if not mt5.initialize():
        print(f"Initialize failed: {mt5.last_error()}")
        return
        
    acc = mt5.account_info()
    if acc:
        print(f"Current Account: {acc.login}")
        print(f"Server: {acc.server}")
    else:
        print("No account info available (not logged in or terminal busy)")
        
    mt5.shutdown()

if __name__ == "__main__":
    check()

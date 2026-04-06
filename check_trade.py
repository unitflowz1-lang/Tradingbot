import MetaTrader5 as mt5

def check():
    if not mt5.initialize():
        print(f"Initialize failed: {mt5.last_error()}")
        return
        
    info = mt5.terminal_info()
    if info:
        print(f"Trade allowed: {info.trade_allowed}")
        print(f"Terminal trade allowed: {info.trade_allowed}")
        print(f"EA trade allowed: {info.trade_expert}")
    else:
        print("Failed to get terminal info")
        
    mt5.shutdown()

if __name__ == "__main__":
    check()

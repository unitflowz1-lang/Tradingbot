import MetaTrader5 as mt5

def check():
    if not mt5.initialize():
        print(f"Initialize failed: {mt5.last_error()}")
        return
        
    info = mt5.terminal_info()
    if info:
        print("Terminal Info Attributes:")
        for attr in dir(info):
            if not attr.startswith('_'):
                try:
                    print(f"{attr}: {getattr(info, attr)}")
                except:
                    pass
    else:
        print("Failed to get terminal info")
        
    acc = mt5.account_info()
    if acc:
        print("\nAccount Info Attributes:")
        print(f"Trade allowed: {acc.trade_allowed}")
        print(f"Expert allowed: {acc.trade_expert}")
        
    mt5.shutdown()

if __name__ == "__main__":
    check()

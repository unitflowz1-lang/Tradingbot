import MetaTrader5 as mt5

def check():
    if not mt5.initialize():
        return
    
    # Try common pairs
    for s in ['EURUSD', 'AUDUSD', 'EUR/USD']: # Try both formats
        info = mt5.symbol_info(s)
        if info:
            print(f"Symbol: {s}")
            print(f"  Filling mode: {info.filling_mode}")
            print(f"  Trade mode: {info.trade_mode}")
            
    mt5.shutdown()

if __name__ == "__main__":
    check()

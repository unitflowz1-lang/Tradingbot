import MetaTrader5 as mt5

def check():
    if not mt5.initialize():
        return
    
    symbol = "EURUSD"
    info = mt5.symbol_info(symbol)
    if info:
        print(f"Symbol: {symbol}")
        print(f"  Volume min: {info.volume_min}")
        print(f"  Volume max: {info.volume_max}")
        print(f"  Volume step: {info.volume_step}")
        print(f"  Trade mode: {info.trade_mode}")
    else:
        print(f"Failed to get info for {symbol}")
        
    mt5.shutdown()

if __name__ == "__main__":
    check()

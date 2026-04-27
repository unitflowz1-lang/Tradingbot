import MetaTrader5 as mt5
if not mt5.initialize():
    print("fail")
    quit()
tick = mt5.symbol_info_tick("EURUSD")
print(f"Bid: {tick.bid}, Ask: {tick.ask}")
mt5.shutdown()

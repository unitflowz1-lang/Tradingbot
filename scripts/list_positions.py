import MetaTrader5 as mt5
import pandas as pd

if not mt5.initialize():
    print("initialize() failed")
    quit()

positions = mt5.positions_get()
if positions is None:
    print("No positions found or error:", mt5.last_error())
else:
    df = pd.DataFrame(list(positions), columns=positions[0]._asdict().keys())
    print(df[['ticket', 'symbol', 'magic', 'comment', 'price_open', 'sl', 'tp']])

mt5.shutdown()

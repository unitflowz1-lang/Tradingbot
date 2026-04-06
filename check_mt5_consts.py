import MetaTrader5 as mt5
import json
res = {
    'FILLING': [attr for attr in dir(mt5) if 'FILLING' in attr],
    'SYMBOL': [attr for attr in dir(mt5) if 'SYMBOL' in attr]
}
with open('mt5_consts.json', 'w') as f:
    json.dump(res, f)

import MetaTrader5 as mt5
import sys
import json

def main():
    config_path = r"c:\Users\macki\Desktop\v4.0-core TradingBot\config\config.mt5.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    broker_cfg = config['broker']
    
    if not mt5.initialize(
        login=broker_cfg['login'],
        password=broker_cfg['password'],
        server=broker_cfg['server']
    ):
        print(f"Failed to initialize MT5: {mt5.last_error()}")
        return

    ticket = 55303742738
    pos = mt5.positions_get(ticket=ticket)
    if not pos:
        print(f"Position {ticket} not found")
        mt5.shutdown()
        return
    
    pos = pos[0]
    symbol = pos.symbol
    tick = mt5.symbol_info_tick(symbol)
    
    # Move TP to BID (for a BUY, this should trigger immediately)
    # Actually, TP must be >= BID + StopLevel.
    symbol_info = mt5.symbol_info(symbol)
    stoplevel = symbol_info.trade_stops_level * symbol_info.point
    if stoplevel == 0: stoplevel = 2 * symbol_info.point
    
    target_tp = tick.bid + stoplevel + symbol_info.point
    
    request = {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "position": ticket,
        "sl": pos.sl,
        "tp": target_tp,
    }
    
    res = mt5.order_send(request)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"Moved TP to {target_tp:.5f} (Bid: {tick.bid:.5f})")
    else:
        print(f"Failed to move TP: {res.retcode} - {res.comment}")
    
    mt5.shutdown()

if __name__ == "__main__":
    main()

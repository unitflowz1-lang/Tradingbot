import MetaTrader5 as mt5
import time
import sys

def close_all_positions():
    print("Initializing MT5...")
    if not mt5.initialize():
        print(f"initialize() failed, error code = {mt5.last_error()}")
        return

    print("Checking for open positions...")
    positions = mt5.positions_get()
    
    if positions is None:
        print(f"No positions found or error getting positions. Error code: {mt5.last_error()}")
    elif len(positions) > 0:
        print(f"Found {len(positions)} open positions. Closing them now...")
        
        count = 0
        for position in positions:
            tick = mt5.symbol_info_tick(position.symbol)
            if tick is None:
                print(f"Failed to get tick for {position.symbol}")
                continue
                
            # Determine close type (Opposite of position type)
            # Position Type 0 = Buy, 1 = Sell
            # Order Type 0 = Buy, 1 = Sell
            # To close a Buy (0), we need to Sell (1)
            order_type = mt5.ORDER_TYPE_SELL if position.type == mt5.POSITION_TYPE_BUY else mt5.ORDER_TYPE_BUY
            price = tick.bid if position.type == mt5.POSITION_TYPE_BUY else tick.ask
            
            # Determine filling mode
            filling_mode = mt5.ORDER_FILLING_FOK # Default
            symbol_info = mt5.symbol_info(position.symbol)
            if symbol_info:
                if symbol_info.filling_mode & 1: # SYMBOL_FILLING_FOK
                    filling_mode = mt5.ORDER_FILLING_FOK
                elif symbol_info.filling_mode & 2: # SYMBOL_FILLING_IOC
                    filling_mode = mt5.ORDER_FILLING_IOC
                else: 
                    filling_mode = mt5.ORDER_FILLING_RETURN
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": position.ticket,
                "symbol": position.symbol,
                "volume": position.volume,
                "type": order_type,
                "price": price,
                "deviation": 20,
                "magic": 0,
                "comment": "Manual Cleanup",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling_mode,
            }
            
            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"Failed to close position {position.ticket}: {result.comment} ({result.retcode})")
            else:
                print(f"Closed position {position.ticket}: {position.symbol} {position.volume} lots")
                count += 1
                
            time.sleep(0.1) # Avoid rate limits
            
        print(f"Cleanup complete. Closed {count}/{len(positions)} positions.")
    else:
        print("No open positions found.")

    mt5.shutdown()

if __name__ == "__main__":
    close_all_positions()

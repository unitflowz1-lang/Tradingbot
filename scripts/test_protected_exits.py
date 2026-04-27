
import asyncio
import MetaTrader5 as mt5
import os
import json
import logging
from datetime import datetime, timezone

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')
logger = logging.getLogger(__name__)

async def check_log_for_pattern(pattern, timeout=60):
    log_file = r"c:\Users\macki\Desktop\v4.0-core TradingBot\logs\forex_bot.log"
    start_time = datetime.now(timezone.utc)
    logger.info(f"Monitoring log for pattern: {pattern}")
    
    while (datetime.now(timezone.utc) - start_time).total_seconds() < timeout:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.readlines()
                # Check last 50 lines
                for line in reversed(content[-50:]):
                    if pattern in line:
                        logger.info(f"MATCH FOUND: {line.strip()}")
                        return True
        await asyncio.sleep(2)
    return False

async def main():
    # Load config
    config_path = r"c:\Users\macki\Desktop\v4.0-core TradingBot\config\config.mt5.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    broker_cfg = config['broker']
    
    # Initialize MT5
    if not mt5.initialize(
        login=broker_cfg['login'],
        password=broker_cfg['password'],
        server=broker_cfg['server']
    ):
        logger.error(f"MT5 initialization failed: {mt5.last_error()}")
        return

    symbol = "EURUSD"
    mt5.symbol_select(symbol, True)
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        logger.error(f"Symbol {symbol} not found")
        mt5.shutdown()
        return

    point = symbol_info.point
    digits = symbol_info.digits
    stoplevel = symbol_info.trade_stops_level * point
    if stoplevel == 0:
        stoplevel = 20 * point # Fallback 2 pips
        
    logger.info(f"Symbol stoplevel: {stoplevel:.5f}")

    # 1. TEST TP HIT
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask
    sl = round(price - 100 * point, digits)
    tp = round(price + 200 * point, digits)
    
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": 0.01,
        "type": mt5.ORDER_TYPE_BUY,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 999999,
        "comment": "TP_TEST",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    res = mt5.order_send(request)
    if res.retcode != mt5.TRADE_RETCODE_DONE:
        # Try FOK if IOC fails
        request["type_filling"] = mt5.ORDER_FILLING_FOK
        res = mt5.order_send(request)
        
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        ticket = res.order
        logger.info(f"TP Test position opened: {ticket}")
        
        # Wait for bot to confirm protection
        await check_log_for_pattern(f"[PROTECTION_CONFIRMED] {symbol.replace('/','')} #{ticket}", timeout=45)
        
        # Move TP to trigger it
        tick = mt5.symbol_info_tick(symbol)
        # For a BUY, TP must be above bid.
        # We try to set it at bid + stoplevel + 1 point
        target_tp = round(tick.bid + stoplevel + 2 * point, digits)
        logger.info(f"Setting TP to {target_tp:.5f} (Bid: {tick.bid:.5f}, StopLevel: {stoplevel:.5f})")
        
        mod_req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": sl,
            "tp": target_tp,
        }
        
        mod_res = mt5.order_send(mod_req)
        if mod_res.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"TP modification failed: {mod_res.retcode} - {mod_res.comment}")
            # Try even further
            target_tp = round(tick.bid + stoplevel * 2, digits)
            mod_req["tp"] = target_tp
            mt5.order_send(mod_req)
            
        logger.info("Waiting for TP hit (price to touch target)...")
        while mt5.positions_get(ticket=ticket):
            await asyncio.sleep(1)
        logger.info("TP position closed.")
        
        # Verify bot log for TP_HIT
        await check_log_for_pattern(f"[EXIT_REASON] TP_HIT for position {ticket}", timeout=45)
    else:
        logger.error(f"Failed to open TP test position: {res.retcode}")

    # 2. TEST SL HIT
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask
    sl = round(price - 200 * point, digits)
    tp = round(price + 200 * point, digits)
    
    request["comment"] = "SL_TEST"
    request["sl"] = sl
    request["tp"] = tp
    
    res = mt5.order_send(request)
    if res.retcode == mt5.TRADE_RETCODE_DONE:
        ticket = res.order
        logger.info(f"SL Test position opened: {ticket}")
        
        await check_log_for_pattern(f"[PROTECTION_CONFIRMED] {symbol.replace('/','')} #{ticket}", timeout=45)
        
        tick = mt5.symbol_info_tick(symbol)
        # For a BUY, SL must be below bid.
        # We try to set it at bid - stoplevel - 1 point
        target_sl = round(tick.bid - stoplevel - 2 * point, digits)
        logger.info(f"Setting SL to {target_sl:.5f} (Bid: {tick.bid:.5f}, StopLevel: {stoplevel:.5f})")
        
        mod_req = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": symbol,
            "position": ticket,
            "sl": target_sl,
            "tp": tp,
        }
        
        mod_res = mt5.order_send(mod_req)
        if mod_res.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"SL modification failed: {mod_res.retcode} - {mod_res.comment}")
            target_sl = round(tick.bid - stoplevel * 2, digits)
            mod_req["sl"] = target_sl
            mt5.order_send(mod_req)

        logger.info("Waiting for SL hit...")
        while mt5.positions_get(ticket=ticket):
            await asyncio.sleep(1)
        logger.info("SL position closed.")
        
        # Verify bot log for SL_HIT
        await check_log_for_pattern(f"[EXIT_REASON] SL_HIT for position {ticket}", timeout=45)
    else:
        logger.error(f"Failed to open SL test position: {res.retcode}")

    mt5.shutdown()
    logger.info("Full test suite finished.")

if __name__ == "__main__":
    asyncio.run(main())

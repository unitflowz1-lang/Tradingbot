"""
MT5 Candle Data Feed Diagnostic & Fix Tool
============================================
Diagnoses and fixes common issues with MT5 historical data feed:

1. Checks if symbols are properly formatted (EUR/USD → EURUSD)
2. Verifies symbols are in Market Watch
3. Tests copy_rates_from_pos() returns valid data
4. Forces symbol subscription if missing
5. Validates data quality (no empty arrays, None values)

Usage:
    python diagnose_and_fix_candle_feed.py
"""

import MetaTrader5 as mt5
import pandas as pd
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import re

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def sanitize_symbol(symbol_name: str) -> str:
    """
    Remove ALL special characters from symbol name.
    EUR/USD → EURUSD, GBP.USD → GBPUSD
    """
    if not isinstance(symbol_name, str):
        return str(symbol_name)
    
    # Remove all non-alphanumeric characters
    sanitized = re.sub(r'[^A-Z0-9]', '', symbol_name.upper())
    return sanitized if sanitized else symbol_name


def check_mt5_connection() -> bool:
    """Check if MT5 is connected and initialized"""
    logger.info("="*80)
    logger.info("STAGE 1: Checking MT5 Connection")
    logger.info("="*80)
    
    if not mt5.initialize():
        logger.error("❌ MT5 initialization failed")
        logger.error("   Make sure MetaTrader 5 terminal is running")
        return False
    
    account_info = mt5.account_info()
    if account_info is None:
        logger.error("❌ Failed to get account info (not logged in)")
        return False
    
    logger.info(f"✅ MT5 Connected")
    logger.info(f"   Account: {account_info.login}")
    logger.info(f"   Server: {account_info.server}")
    logger.info(f"   Balance: ${account_info.balance:.2f}")
    return True


def check_symbols_in_market_watch(symbols: List[str]) -> Dict[str, Tuple[bool, str]]:
    """
    Check which symbols are in Market Watch and which need to be added.
    
    Returns dict: {symbol: (is_present, status_message)}
    """
    logger.info("\n" + "="*80)
    logger.info("STAGE 2: Checking Symbols in Market Watch")
    logger.info("="*80)
    
    # Get all available symbols from MT5
    all_symbols = mt5.symbols_get()
    if all_symbols is None or len(all_symbols) == 0:
        logger.error("❌ No symbols available from MT5")
        return {}
    
    available_symbol_names = {sym.name for sym in all_symbols}
    logger.info(f"   Total symbols available in terminal: {len(available_symbol_names)}")
    
    results = {}
    
    for symbol in symbols:
        # Sanitize symbol (remove /, ., etc.)
        sanitized = sanitize_symbol(symbol)
        
        # Try to find matching symbol in terminal
        matching_symbols = [
            sym for sym in available_symbol_names 
            if sanitize_symbol(sym) == sanitized
        ]
        
        if not matching_symbols:
            results[symbol] = (False, f"No match found for '{sanitized}'")
            logger.warning(f"❌ {symbol:12} → {sanitized:8} | NOT FOUND in terminal")
        else:
            # Check if it's in Market Watch
            terminal_symbol = matching_symbols[0]
            symbol_info = mt5.symbol_info(terminal_symbol)
            
            if symbol_info is None:
                results[symbol] = (False, "symbol_info returned None")
                logger.warning(f"❌ {symbol:12} → {terminal_symbol:12} | symbol_info FAILED")
            elif symbol_info.visible:
                results[symbol] = (True, "In Market Watch")
                logger.info(f"✅ {symbol:12} → {terminal_symbol:12} | Already in Market Watch")
            else:
                results[symbol] = (False, "Found but not in Market Watch")
                logger.warning(f"⚠️  {symbol:12} → {terminal_symbol:12} | Found but NOT in Market Watch")
    
    return results


def force_add_symbols_to_market_watch(symbols: List[str]) -> Dict[str, bool]:
    """
    Force-add symbols to Market Watch using symbol_select().
    
    Returns dict: {symbol: success}
    """
    logger.info("\n" + "="*80)
    logger.info("STAGE 3: Forcing Symbols into Market Watch")
    logger.info("="*80)
    
    results = {}
    
    for symbol in symbols:
        sanitized = sanitize_symbol(symbol)
        
        # Find the actual terminal symbol name
        all_symbols = mt5.symbols_get()
        matching_symbols = [
            sym.name for sym in all_symbols 
            if sanitize_symbol(sym.name) == sanitized
        ]
        
        if not matching_symbols:
            results[symbol] = False
            logger.error(f"❌ {symbol:12} → {sanitized:8} | Cannot add: not found in terminal")
            continue
        
        terminal_symbol = matching_symbols[0]
        
        # Force add to Market Watch
        select_result = mt5.symbol_select(terminal_symbol, True)
        
        if select_result:
            results[symbol] = True
            logger.info(f"✅ {symbol:12} → {terminal_symbol:12} | ADDED to Market Watch")
        else:
            results[symbol] = False
            last_error = mt5.last_error()
            logger.error(f"❌ {symbol:12} → {terminal_symbol:12} | FAILED to add | Error: {last_error}")
    
    return results


def test_candle_data_fetch(symbol: str, timeframe, count: int = 100) -> Optional[pd.DataFrame]:
    """
    Test fetching candle data using copy_rates_from_pos().
    
    Returns DataFrame if successful, None if failed.
    """
    sanitized = sanitize_symbol(symbol)
    
    # Find terminal symbol
    all_symbols = mt5.symbols_get()
    matching_symbols = [
        sym.name for sym in all_symbols 
        if sanitize_symbol(sym.name) == sanitized
    ]
    
    if not matching_symbols:
        logger.error(f"❌ {symbol} → No matching symbol found")
        return None
    
    terminal_symbol = matching_symbols[0]
    
    try:
        logger.info(f"\n   Testing: {symbol} → {terminal_symbol} | Timeframe: {timeframe} | Count: {count}")
        
        # Fetch rates
        rates = mt5.copy_rates_from_pos(terminal_symbol, timeframe, 0, count)
        
        if rates is None:
            logger.error(f"   ❌ copy_rates_from_pos returned None")
            return None
        
        if len(rates) == 0:
            logger.error(f"   ❌ copy_rates_from_pos returned empty array (0 bars)")
            return None
        
        if len(rates) < count:
            logger.warning(f"   ⚠️  Got {len(rates)}/{count} bars (incomplete history)")
        
        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Validate data quality
        has_nulls = df.isnull().any().any()
        has_zero_prices = (df['close'] == 0).any()
        
        if has_nulls:
            logger.warning(f"   ⚠️  DataFrame contains NULL values")
        
        if has_zero_prices:
            logger.warning(f"   ⚠️  DataFrame contains zero prices (corrupted data)")
        
        # Show sample
        logger.info(f"   ✅ SUCCESS: {len(df)} bars fetched")
        logger.info(f"       Time range: {df['time'].iloc[0]} → {df['time'].iloc[-1]}")
        logger.info(f"       Price range: {df['close'].min():.5f} → {df['close'].max():.5f}")
        logger.info(f"       Latest candle: {df.iloc[-1]['time']} | O:{df.iloc[-1]['open']:.5f} H:{df.iloc[-1]['high']:.5f} L:{df.iloc[-1]['low']:.5f} C:{df.iloc[-1]['close']:.5f}")
        
        return df
        
    except Exception as e:
        logger.error(f"   ❌ Exception during data fetch: {e}")
        return None


def warmup_symbol_history(symbol: str) -> bool:
    """
    Warm up symbol history by fetching small chunks of data.
    This forces MT5 to download and cache historical data.
    """
    sanitized = sanitize_symbol(symbol)
    
    all_symbols = mt5.symbols_get()
    matching_symbols = [
        sym.name for sym in all_symbols 
        if sanitize_symbol(sym.name) == sanitized
    ]
    
    if not matching_symbols:
        return False
    
    terminal_symbol = matching_symbols[0]
    
    try:
        logger.info(f"   Warming up {symbol} → {terminal_symbol}...")
        
        # Fetch small chunks to seed history
        for count in [10, 50, 100]:
            rates = mt5.copy_rates_from_pos(terminal_symbol, mt5.TIMEFRAME_M1, 0, count)
            if rates is None or len(rates) == 0:
                logger.warning(f"   ⚠️  Warmup failed at {count} bars")
                return False
        
        # Also fetch H1 data
        rates_h1 = mt5.copy_rates_from_pos(terminal_symbol, mt5.TIMEFRAME_H1, 0, 100)
        if rates_h1 is None or len(rates_h1) == 0:
            logger.warning(f"   ⚠️  H1 warmup failed")
            return False
        
        logger.info(f"   ✅ History warmup complete for {terminal_symbol}")
        return True
        
    except Exception as e:
        logger.error(f"   ❌ Warmup exception: {e}")
        return False


def run_full_diagnostic(symbols: List[str] = None):
    """
    Run complete diagnostic pipeline.
    """
    if symbols is None:
        symbols = ['EUR/USD', 'GBP/USD', 'USD/JPY', 'AUD/USD', 'USD/CHF', 'USD/CAD', 'NZD/USD']
    
    logger.info("="*80)
    logger.info("MT5 CANDLE DATA FEED DIAGNOSTIC")
    logger.info("="*80)
    logger.info(f"Testing {len(symbols)} symbols: {', '.join(symbols)}")
    logger.info(f"Timestamp: {datetime.now()}")
    
    # Stage 1: Check connection
    if not check_mt5_connection():
        logger.error("\n❌ DIAGNOSTIC FAILED: MT5 not connected")
        logger.error("   Fix: Make sure MT5 terminal is running and you're logged in")
        return
    
    # Stage 2: Check Market Watch
    market_watch_status = check_symbols_in_market_watch(symbols)
    
    # Stage 3: Force-add missing symbols
    missing_symbols = [
        sym for sym, (present, _) in market_watch_status.items() 
        if not present
    ]
    
    if missing_symbols:
        logger.info(f"\n   Found {len(missing_symbols)} symbols not in Market Watch")
        add_results = force_add_symbols_to_market_watch(missing_symbols)
        
        failed_adds = [sym for sym, success in add_results.items() if not success]
        if failed_adds:
            logger.error(f"\n❌ CRITICAL: {len(failed_adds)} symbols could NOT be added:")
            for sym in failed_adds:
                logger.error(f"   - {sym}")
            logger.error("   These symbols may not be offered by your broker")
    else:
        logger.info("\n✅ All symbols already in Market Watch")
    
    # Stage 4: Warmup history
    logger.info("\n" + "="*80)
    logger.info("STAGE 4: Warming Up Historical Data")
    logger.info("="*80)
    
    for symbol in symbols:
        warmup_symbol_history(symbol)
    
    # Stage 5: Test data fetch
    logger.info("\n" + "="*80)
    logger.info("STAGE 5: Testing Candle Data Fetch")
    logger.info("="*80)
    
    timeframes_to_test = [
        (mt5.TIMEFRAME_M1, "M1"),
        (mt5.TIMEFRAME_H1, "H1"),
        (mt5.TIMEFRAME_H4, "H4"),
    ]
    
    results_summary = {}
    
    for symbol in symbols:
        logger.info(f"\n{'─'*80}")
        logger.info(f"Testing: {symbol}")
        logger.info(f"{'─'*80}")
        
        symbol_results = {}
        
        for tf, tf_name in timeframes_to_test:
            df = test_candle_data_fetch(symbol, tf, count=100)
            symbol_results[tf_name] = df is not None and len(df) > 0
        
        results_summary[symbol] = symbol_results
    
    # Summary
    logger.info("\n" + "="*80)
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info("="*80)
    
    all_good = True
    for symbol, tf_results in results_summary.items():
        status = "✅" if all(tf_results.values()) else "❌"
        if not all(tf_results.values()):
            all_good = False
        
        working_tfs = [tf for tf, ok in tf_results.items() if ok]
        failing_tfs = [tf for tf, ok in tf_results.items() if not ok]
        
        logger.info(f"{status} {symbol:12} | Working: {', '.join(working_tfs) if working_tfs else 'NONE'}")
        if failing_tfs:
            logger.info(f"   ⚠️  Failing: {', '.join(failing_tfs)}")
    
    if all_good:
        logger.info("\n✅ ALL SYMBOLS AND TIMEFRAMES WORKING CORRECTLY")
        logger.info("   Your candle data feed is healthy!")
    else:
        logger.info("\n⚠️  SOME SYMBOLS/TIMEFRAMES FAILED")
        logger.info("   See recommendations below:")
        print_recommendations()
    
    mt5.shutdown()


def print_recommendations():
    """Print troubleshooting recommendations"""
    logger.info("\n" + "="*80)
    logger.info("RECOMMENDATIONS")
    logger.info("="*80)
    logger.info("""
If symbols are failing, try these fixes:

1. CHECK MT5 TERMINAL:
   - Open MetaTrader 5 terminal manually
   - View → Market Watch (Ctrl+U)
   - Right-click → Show All
   - Verify symbols are visible

2. CHECK BROKER SUPPORT:
   - Some brokers don't offer all pairs
   - Contact broker to confirm symbol availability
   - Check if you need specific account type

3. VERIFY SYMBOL FORMAT:
   - MT5 uses EURUSD, not EUR/USD
   - Our code auto-sanitizes, but check logs
   - Look for [SYMBOL_SELECTED] messages

4. FORCE HISTORY DOWNLOAD:
   - In MT5 terminal, open chart for each symbol
   - Scroll back to force history download
   - Wait for "Downloaded X bars" message

5. RESTART MT5 TERMINAL:
   - Close MT5 completely
   - Reopen and login
   - Run this diagnostic again

6. CHECK NETWORK/FIREWALL:
   - Ensure MT5 can connect to broker servers
   - Check firewall isn't blocking MT5
   - Try different network if needed

7. UPDATE CODE:
   - Make sure mt5_broker.py calls _subscribe_to_symbols()
   - Verify symbol_select(symbol, True) is called after connect
   - Check get_historical_data() has retry logic
""")


if __name__ == '__main__':
    run_full_diagnostic()

#!/usr/bin/env python
"""
Feed Health Diagnostic Script
Tests if MT5 is providing fresh tick data for each monitored symbol.
Run this during trading hours to verify data freshness.
"""

import MetaTrader5 as mt5
from datetime import datetime, timezone
import time
import sys

def main():
    print("=" * 70)
    print("MT5 FEED HEALTH DIAGNOSTIC")
    print(f"Current UTC Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)
    
    # Initialize MT5
    if not mt5.initialize():
        print(f"✗ ERROR: Could not initialize MT5: {mt5.last_error()}")
        return 1
    
    # Monitored symbols (adjust to match your config)
    symbols = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD"]
    
    print("\n[Refreshing feeds and checking tick freshness...]\n")
    
    max_age = 0
    stale_symbols = []
    healthy_symbols = []
    
    for symbol in symbols:
        print(f"► {symbol}")
        
        try:
            # Step 1: Deselect from Market Watch
            if not mt5.symbol_select(symbol, False):
                print(f"  ⚠ Warning: Failed to deselect")
                continue
            
            time.sleep(0.3)
            
            # Step 2: Re-select to Market Watch
            if not mt5.symbol_select(symbol, True):
                print(f"  ✗ ERROR: Failed to re-select")
                continue
            
            time.sleep(0.5)
            
            # Step 3: Get fresh ticks
            ticks = mt5.copy_ticks_from(symbol, datetime.now(timezone.utc), 1, mt5.COPY_TICKS_ALL)
            
            if not ticks or len(ticks) == 0:
                print(f"  ✗ ERROR: No ticks returned (symbol may not exist or be tradeable)")
                stale_symbols.append((symbol, "NO_DATA"))
                continue
            
            # Step 4: Calculate tick age
            latest_tick = ticks[-1]
            tick_time = datetime.fromtimestamp(latest_tick['time'], tz=timezone.utc)
            tick_age = (datetime.now(timezone.utc) - tick_time).total_seconds()
            
            bid = latest_tick['bid']
            ask = latest_tick['ask']
            spread_pips = round((ask - bid) * 10000, 1) if symbol != "USDJPY" else round((ask - bid) * 100, 1)
            
            # Determine health status
            if tick_age < 2:
                status = f"✓ EXCELLENT (age: {tick_age:.1f}s)"
                healthy_symbols.append(symbol)
            elif tick_age < 10:
                status = f"✓ GOOD (age: {tick_age:.1f}s)"
                healthy_symbols.append(symbol)
            elif tick_age < 60:
                status = f"⚠ ACCEPTABLE (age: {tick_age:.0f}s)"
                healthy_symbols.append(symbol)
            else:
                status = f"✗ STALE (age: {tick_age:.0f}s)"
                stale_symbols.append((symbol, f"{tick_age:.0f}s"))
            
            print(f"  {status}")
            print(f"    Bid: {bid:.5f} | Ask: {ask:.5f} | Spread: {spread_pips} pips")
            
            max_age = max(max_age, tick_age)
            
        except Exception as e:
            print(f"  ✗ ERROR: {str(e)}")
            stale_symbols.append((symbol, str(e)))
    
    # Shutdown MT5
    mt5.shutdown()
    
    # Summary report
    print("\n" + "=" * 70)
    print("DIAGNOSTIC SUMMARY")
    print("=" * 70)
    
    print(f"\n✓ Healthy symbols ({len(healthy_symbols)}): {', '.join(healthy_symbols) if healthy_symbols else 'None'}")
    
    if stale_symbols:
        print(f"✗ Stale/Error symbols ({len(stale_symbols)}):")
        for symbol, reason in stale_symbols:
            print(f"   - {symbol}: {reason}")
    else:
        print(f"✗ Stale/Error symbols (0): None")
    
    print(f"\nMax tick age: {max_age:.1f} seconds")
    
    # Recommendations
    print("\n" + "=" * 70)
    print("RECOMMENDATIONS")
    print("=" * 70)
    
    if max_age < 5:
        print("✓ All feeds are FRESH - bot should execute normally")
        print("  Expected: Few to no [STALE_SIGNAL_REJECT] logs")
        return 0
    
    elif max_age < 60:
        print("⚠ Feed latency is slightly elevated but acceptable")
        print("  Expected: Occasional [STALE_SIGNAL_REJECT] logs (normal)")
        print("  Action: Monitor - may be high market volatility or network latency")
        return 0
    
    elif max_age < 300:
        print("⚠ Feed latency is high - consider troubleshooting")
        print("  Expected: Frequent [STALE_SIGNAL_REJECT] logs")
        print("  Actions:")
        print("    1. Check MT5 terminal connection in Tools → Options → Data")
        print("    2. Verify account authorization status")
        print("    3. Check network connectivity")
        print("    4. Restart MT5 terminal")
        return 1
    
    else:
        print("✗ Feed is FROZEN - immediate action required")
        print(f"  Expected: [STALE_SIGNAL_REJECT] for every symbol (age {max_age:.0f}s)")
        print("  Actions:")
        print("    1. Check if market is closed (Fri 22:00 UTC - Sun 22:00 UTC)")
        print("    2. Verify MT5 terminal is running and connected (check status bar)")
        print("    3. Right-click Market Watch → Refresh to manually refresh")
        print("    4. Restart MT5 terminal completely")
        print("    5. Contact broker support if problem persists")
        print(f"\n  *** Your bot will enter MARKET_CLOSED_SLEEP mode if close time detected ***")
        return 1

if __name__ == "__main__":
    exit_code = main()
    print("\n" + "=" * 70 + "\n")
    sys.exit(exit_code)

#!/usr/bin/env python3
"""
MT5 DATA HARVESTER
==================
Exports real historical candle data from MT5 terminal for backtesting validation.

Usage:
    python scripts/harvest_real_data.py

Output:
    data/EURUSD_90d_real.csv
    data/GBPUSD_90d_real.csv
"""

import MetaTrader5 as mt5
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import sys


def harvest_historical_data(symbol: str, timeframe=mt5.TIMEFRAME_M5, days: int = 90) -> bool:
    """
    Harvest historical candle data from MT5 terminal.
    
    Args:
        symbol: Trading symbol (e.g., "EURUSD", "GBPUSD")
        timeframe: MT5 timeframe (default: M5)
        days: Number of days to harvest (default: 90)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Initialize MT5
        if not mt5.initialize():
            print(f"❌ MT5 initialization failed for {symbol}")
            return False
        
        # Calculate date range
        utc_from = datetime.utcnow() - timedelta(days=days)
        utc_to = datetime.utcnow()
        
        print(f"\n📊 Harvesting {symbol}...")
        print(f"   Timeframe: M5")
        print(f"   Period: {utc_from.strftime('%Y-%m-%d')} to {utc_to.strftime('%Y-%m-%d')}")
        print(f"   Days: {days}")
        
        # Fetch rates
        rates = mt5.copy_rates_range(symbol, timeframe, utc_from, utc_to)
        
        if rates is None or len(rates) == 0:
            print(f"   ⚠️  No data returned for {symbol}")
            print(f"   Possible reasons:")
            print(f"   - Symbol not available in MT5 Market Watch")
            print(f"   - Insufficient history in terminal")
            print(f"   - Market is closed")
            return False
        
        # Convert to DataFrame
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        
        # Calculate additional metrics for analysis
        df['range'] = df['high'] - df['low']
        df['body'] = abs(df['close'] - df['open'])
        df['upper_wick'] = df['high'] - df[['open', 'close']].max(axis=1)
        df['lower_wick'] = df[['open', 'close']].min(axis=1) - df['low']
        
        # Save to CSV
        output_dir = Path(__file__).parent.parent / "data"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{symbol.replace('/', '')}_{days}d_real.csv"
        output_path = output_dir / filename
        
        df.to_csv(output_path, index=False)
        
        # Print statistics
        print(f"\n✅ Successfully harvested {len(df)} candles for {symbol}")
        print(f"   Saved to: {output_path}")
        print(f"\n📈 Data Statistics:")
        print(f"   Date Range: {df['time'].min()} to {df['time'].max()}")
        print(f"   Price Range: {df['close'].min():.5f} - {df['close'].max():.5f}")
        print(f"   Avg Candle Range: {df['range'].mean():.5f} ({df['range'].mean() * 10000:.1f} pips)")
        print(f"   Max Candle Range: {df['range'].max():.5f} ({df['range'].max() * 10000:.1f} pips)")
        print(f"   Min Candle Range: {df['range'].min():.5f} ({df['range'].min() * 10000:.1f} pips)")
        
        # Check for gaps
        time_diffs = df['time'].diff().dt.total_seconds().dropna()
        avg_interval = time_diffs.mean()
        expected_interval = 300  # M5 = 300 seconds
        gap_count = (time_diffs > expected_interval * 1.5).sum()
        
        print(f"\n⏱️  Data Quality:")
        print(f"   Avg Candle Interval: {avg_interval:.0f}s (expected: {expected_interval}s)")
        print(f"   Missing Candles (gaps): {gap_count}")
        
        if gap_count > 0:
            print(f"   ⚠️  {gap_count} gaps detected (normal for weekends/holidays)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error harvesting {symbol}: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Don't shutdown here - keep MT5 initialized for multiple symbols
        pass


def main():
    """Harvest data for all alpha pairs"""
    print("="*80)
    print("MT5 DATA HARVESTER - Real Historical Data Export")
    print("="*80)
    
    # Initialize MT5 once
    if not mt5.initialize():
        print("\n❌ CRITICAL: MT5 initialization failed!")
        print("   Please ensure:")
        print("   1. MetaTrader 5 terminal is installed")
        print("   2. You are logged into your MT5 account")
        print("   3. Terminal is running and connected")
        print("\n   Troubleshooting:")
        print("   - Open MT5 terminal manually and login")
        print("   - Check internet connection")
        print("   - Verify broker allows automated access")
        sys.exit(1)
    
    print("\n✅ MT5 terminal connected successfully")
    
    # Get account info
    account_info = mt5.account_info()
    if account_info:
        print(f"   Account: {account_info.login}")
        print(f"   Server: {account_info.server}")
        print(f"   Balance: ${account_info.balance:.2f}")
    
    # Alpha Pairs to harvest
    alpha_pairs = ["EURUSD", "GBPUSD"]
    
    print(f"\n🎯 Harvesting data for {len(alpha_pairs)} alpha pairs...")
    print(f"   Timeframe: M5 (5-minute candles)")
    print(f"   Period: Last 90 days")
    
    results = {}
    for symbol in alpha_pairs:
        results[symbol] = harvest_historical_data(symbol, timeframe=mt5.TIMEFRAME_M5, days=90)
    
    # Shutdown MT5
    mt5.shutdown()
    print(f"\n🔌 MT5 connection closed")
    
    # Summary
    print("\n" + "="*80)
    print("HARVEST SUMMARY")
    print("="*80)
    
    success_count = sum(1 for v in results.values() if v)
    print(f"\n✅ Successful: {success_count}/{len(alpha_pairs)}")
    
    if success_count == len(alpha_pairs):
        print("\n🎉 All data harvested successfully!")
        print("\n📁 Files created:")
        for symbol in alpha_pairs:
            filename = f"data/{symbol}_{90}d_real.csv"
            print(f"   • {filename}")
        
        print(f"\n🚀 Next Steps:")
        print(f"   1. Run aggressive sweep with real data:")
        print(f"      python scripts/aggressive_hyperparameter_sweep.py --real-data")
        print(f"\n   2. Or manually edit aggressive_hyperparameter_sweep.py to load CSV files")
    else:
        print(f"\n⚠️  Some symbols failed to harvest")
        print(f"   Failed symbols: {[k for k, v in results.items() if not v]}")
        print(f"\n   Possible solutions:")
        print(f"   - Add symbols to MT5 Market Watch")
        print(f"   - Check symbol naming (EURUSD vs EUR/USD)")
        print(f"   - Verify broker provides historical data")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    main()

"""
Fast quality threshold optimization - tests signal generation only
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy

logging.getLogger("src").setLevel(logging.CRITICAL)
logging.getLogger("__main__").setLevel(logging.INFO)

def load_eurusd_data():
    """Load EURUSD data"""
    csv_file = Path("EURUSD Data/DAT_MT_EURUSD_M1_202512.csv")
    if not csv_file.exists():
        print(f"ERROR: {csv_file} not found")
        return None
    
    df = pd.read_csv(csv_file, header=None, names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
    data = []
    
    for idx, row in df.iterrows():
        try:
            timestamp_str = f"{row['Date']} {row['Time']}"
            timestamp = datetime.strptime(timestamp_str, "%Y.%m.%d %H:%M")
            timestamp = timestamp.replace(tzinfo=timezone.utc)
            
            md = MarketData(
                symbol="EUR/USD",
                timestamp=timestamp,
                open=float(row['Open']),
                high=float(row['High']),
                low=float(row['Low']),
                close=float(row['Close']),
                volume=int(row['Volume']) if pd.notna(row['Volume']) else 0,
                bid=float(row['Close']) - 0.0002,
                ask=float(row['Close']) + 0.0002,
                spread=0.0004
            )
            data.append(md)
        except:
            continue
    
    return data

async def test_quality_threshold(quality_threshold, market_data_list):
    """Test a specific quality threshold"""
    print(f"\nTesting Threshold: {quality_threshold:.2f}...", end=" ", flush=True)
    
    # Create strategy with custom quality threshold
    strategy = SimpleTrendStrategy("EUR/USD", verbose=False, entry_filters={
        'adx_min': 8,
        'rsi_min': 25,
        'rsi_max': 75,
        'ml_confidence_min': 0.55,
        'signal_quality_min': quality_threshold  # Test this threshold
    })
    
    # Generate signals at regular intervals (FASTER - every 300 bars instead of 60)
    signals = []
    
    for i in range(100, len(market_data_list), 300):  # Every 300 bars for speed
        historical = market_data_list[max(0, i-100):i+1]  # Use last 100 bars only
        try:
            signal = await strategy.analyze(historical)
            if signal:
                signals.append({
                    'time': historical[-1].timestamp,
                    'price': historical[-1].close,
                    'direction': signal.direction.value,
                    'confidence': getattr(signal, 'confidence', 0.5)
                })
        except Exception as e:
            pass
    
    print(f"✓ {len(signals)} signals")
    
    return {
        'threshold': quality_threshold,
        'signals': len(signals),
    }

async def main():
    """Test multiple quality thresholds"""
    print("\n" + "="*70)
    print("QUALITY THRESHOLD OPTIMIZATION TEST")
    print("="*70)
    
    print("\nLoading EURUSD data...")
    market_data_list = load_eurusd_data()
    
    if not market_data_list:
        print("❌ Failed to load data")
        return
    
    print(f"✓ Loaded {len(market_data_list)} bars\n")
    
    results = []
    thresholds = [0.35, 0.40, 0.45, 0.50, 0.55, 0.60]
    
    for threshold in thresholds:
        result = await test_quality_threshold(threshold, market_data_list)
        if result:
            results.append(result)
    
    # Summary
    print(f"\n{'='*70}")
    print("SUMMARY - Signal Generation by Threshold")
    print(f"{'='*70}")
    print(f"\n{'Threshold':<12} {'Signals Generated':<20}")
    print("-"*35)
    
    for r in sorted(results, key=lambda x: x['threshold']):
        print(f"{r['threshold']:<12.2f} {r['signals']:<20}")
    
    # Recommendations
    print(f"\n{'='*70}")
    print("RECOMMENDATIONS")
    print(f"{'='*70}")
    
    min_signals = min(r['signals'] for r in results)
    max_signals = max(r['signals'] for r in results)
    
    optimal = [r for r in results if 15 <= r['signals'] <= 25]
    
    if optimal:
        best_threshold = optimal[0]['threshold']
        print(f"\n🎯 OPTIMAL THRESHOLD: {best_threshold:.2f}")
        print(f"   Generates {optimal[0]['signals']} signals (balanced)")
        print(f"\n   ✓ Not too few (miss opportunities)")
        print(f"   ✓ Not too many (avoid false signals)")
    else:
        best_threshold = 0.50
        print(f"\n⚠️  No optimal range found. Recommending: {best_threshold:.2f}")
    
    print(f"\nNext: Update main.py with this threshold:")
    print(f"   'signal_quality_min': {best_threshold}")

asyncio.run(main())

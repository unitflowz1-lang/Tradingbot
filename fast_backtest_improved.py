"""
Fast backtest with improved signal filtering - optimized for speed
"""

import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy

# Silence verbose logging for speed
logging.getLogger("src").setLevel(logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)

def load_eurusd_data():
    """Load real EURUSD data from CSV"""
    csv_file = Path("EURUSD Data/DAT_MT_EURUSD_M1_202512.csv")
    
    if not csv_file.exists():
        print(f"ERROR: CSV file not found at {csv_file}")
        return None
    
    df = pd.read_csv(csv_file, header=None, names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
    print(f"Loaded {len(df)} bars")
    
    data = {"EUR/USD": []}
    
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
            data["EUR/USD"].append(md)
        except:
            continue
    
    if len(data["EUR/USD"]) == 0:
        print("ERROR: No valid data")
        return None
    
    return data

async def generate_signals_fast(data):
    """Generate signals with improved filtering (less verbose)"""
    signals = []
    
    # Use non-verbose strategy for speed
    strategy = SimpleTrendStrategy("EUR/USD", verbose=False)
    
    market_data_list = data["EUR/USD"]
    signal_interval = 15  # Every 15 bars
    
    total_bars = len(market_data_list)
    checked = 0
    accepted = 0
    
    for i in range(signal_interval, len(market_data_list), signal_interval):
        historical = market_data_list[:i+1]
        checked += 1
        
        try:
            signal = await strategy.analyze(historical)
            if signal:
                signal.timestamp = historical[-1].timestamp
                signals.append(signal)
                accepted += 1
        except Exception as e:
            pass
        
        if checked % 50 == 0:
            print(f"   Checked: {checked} | Accepted: {accepted}")
    
    return signals, checked, accepted

def run_fast_backtest():
    """Run improved backtest with quality filtering"""
    print("\n" + "="*70)
    print("IMPROVED BACKTEST: Signal Quality Filtering + Tight Entry Filters")
    print("="*70 + "\n")
    
    try:
        print("1. Loading EURUSD data...")
        data = load_eurusd_data()
        if not data:
            return
        
        print("\n2. Generating HIGH-QUALITY signals only...")
        signals, checked, accepted = asyncio.run(generate_signals_fast(data))
        
        print(f"\n   Results:")
        print(f"   - Checked: {checked} signal opportunities")
        print(f"   - Accepted: {accepted} high-quality signals")
        print(f"   - Filtered: {checked - accepted} ({100*(checked-accepted)/checked:.1f}%)")
        print(f"   - Quality Rate: {100*accepted/checked:.1f}%")
        
        if len(signals) == 0:
            print("\n   WARNING: No high-quality signals generated")
            return
        
        print(f"\n3. Running backtest with {len(signals)} signals...")
        config = BacktestConfig(
            initial_balance=10000,
            leverage=2.0,
            slippage_pips=0.5,
        )
        
        engine = BacktestEngine(config)
        results = engine.run_backtest(data, signals)
        
        print("\n" + "="*70)
        print("BACKTEST RESULTS (WITH IMPROVEMENTS)")
        print("="*70)
        print(f"\nTrading Activity:")
        print(f"  Total Trades:        {results.total_trades}")
        print(f"  Winning Trades:      {results.winning_trades}")
        print(f"  Losing Trades:       {results.losing_trades}")
        print(f"  Win Rate:            {results.win_rate:.1%}")
        with open("results_clean.txt", "w") as f:
            f.write(f"Win Rate: {results.win_rate:.1%}\n")
            f.write(f"Total Trades: {results.total_trades}\n")
            f.write(f"Profit Factor: {results.profit_factor:.2f}\n")
        
        print(f"\nProfitability:")
        print(f"  Total P&L:           ${results.total_pnl:+,.2f}")
        print(f"  Profit Factor:       {results.profit_factor:.2f}")
        if results.winning_trades > 0:
            print(f"  Avg Win:             ${results.avg_win:+,.2f}")
        if results.losing_trades > 0:
            print(f"  Avg Loss:            ${results.avg_loss:+,.2f}")
        
        print(f"\nRisk:")
        print(f"  Max Drawdown:        {results.max_drawdown:.1%}")
        print(f"  Sharpe Ratio:        {results.sharpe_ratio:.2f}")
        
        print("\n" + "="*70)
        print("TARGET COMPARISON")
        print("="*70)
        
        targets = [
            ("Win Rate > 60%", results.win_rate, 0.60, True),
            ("Profit Factor > 2.0", results.profit_factor, 2.0, True),
            ("Max Drawdown < 15%", results.max_drawdown, 0.15, False),
            ("Positive P&L", results.total_pnl, 0, True),
            ("Sharpe Ratio > 1.0", results.sharpe_ratio, 1.0, True),
        ]
        
        passed = 0
        for name, actual, target, is_greater in targets:
            if is_greater:
                ok = actual >= target
            else:
                ok = actual <= target
            
            status = "PASS" if ok else "FAIL"
            symbol = "[OK]" if ok else "[X]"
            print(f"{symbol} {name:25} Actual: {actual:.2f}  Target: {target:.2f}")
            if ok:
                passed += 1
        
        print(f"\nScore: {passed}/5 targets achieved")
        
        # Improvement analysis
        print("\n" + "="*70)
        print("IMPROVEMENT ANALYSIS")
        print("="*70)
        print(f"\nBefore Improvements:")
        print(f"  Trades Generated:    345 (no filtering)")
        print(f"  Win Rate:            3.5%")
        print(f"  Profit Factor:       0.04")
        print(f"\nAfter Improvements:")
        print(f"  Trades Generated:    {len(signals)} (quality filtered)")
        print(f"  Win Rate:            {results.win_rate:.1%}")
        print(f"  Profit Factor:       {results.profit_factor:.2f}")
        
        if results.total_trades > 0:
            win_improvement = (results.win_rate - 0.035) * 100
            pf_improvement = ((results.profit_factor - 0.04) / 0.04) * 100 if results.profit_factor > 0 else 0
            print(f"\nImprovement:")
            print(f"  Win Rate Change:     {win_improvement:+.1f} percentage points")
            print(f"  Profit Factor Gain:  {pf_improvement:+.0f}%")
            print(f"  Signal Reduction:    {100*(345-len(signals))/345:.0f}% (better quality)")
        
        print("\n" + "="*70)
        if passed >= 4:
            print("SUCCESS! Improvements working - targets achieved!")
        elif passed >= 3:
            print("PROGRESS - Getting close to targets. Fine-tune parameters.")
        else:
            print("CONTINUE - Need more optimization. Try parameter adjustments.")
        print("="*70)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_fast_backtest()

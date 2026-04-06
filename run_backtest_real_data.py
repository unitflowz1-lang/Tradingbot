"""
Backtest with real EURUSD historical data
"""

import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy

# Configure logging to be less verbose
logging.getLogger("src").setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

def load_eurusd_data():
    """Load real EURUSD data from CSV"""
    csv_file = Path("EURUSD Data/DAT_MT_EURUSD_M1_202512.csv")
    
    if not csv_file.exists():
        print(f"ERROR: CSV file not found at {csv_file}")
        return None
    
    try:
        # Read CSV without header (data starts immediately)
        df = pd.read_csv(csv_file, header=None, names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
        print(f"Loaded {len(df)} rows from {csv_file}")
        
        # Convert to MarketData objects
        data = {"EUR/USD": []}
        
        for idx, row in df.iterrows():
            try:
                # Parse timestamp from separate date and time columns
                # Format: Date='2025.12.01', Time='00:00'
                timestamp_str = f"{row['Date']} {row['Time']}"
                timestamp = datetime.strptime(timestamp_str, "%Y.%m.%d %H:%M")
                timestamp = timestamp.replace(tzinfo=timezone.utc)
                
                # Extract OHLCV data
                md = MarketData(
                    symbol="EUR/USD",
                    timestamp=timestamp,
                    open=float(row['Open']),
                    high=float(row['High']),
                    low=float(row['Low']),
                    close=float(row['Close']),
                    volume=int(row['Volume']) if pd.notna(row['Volume']) else 0,
                    bid=float(row['Close']) - 0.0002,  # Approximate bid
                    ask=float(row['Close']) + 0.0002,  # Approximate ask
                    spread=0.0004
                )
                data["EUR/USD"].append(md)
            except (ValueError, IndexError) as e:
                # Skip bad rows
                continue
        
        if len(data["EUR/USD"]) == 0:
            print("ERROR: No valid data rows found")
            return None
        
        print(f"Successfully converted {len(data['EUR/USD'])} data points")
        return data
        
    except Exception as e:
        print(f"ERROR loading CSV: {e}")
        import traceback
        traceback.print_exc()
        return None

async def generate_signals_from_real_data(data):
    """Generate trading signals from real historical data"""
    signals = []
    strategy = SimpleTrendStrategy("EUR/USD", verbose=False)
    
    market_data_list = data["EUR/USD"]
    
    # Process every 15th bar to generate signals (e.g., 15M timeframe from 1M data)
    signal_interval = 15
    
    for i in range(signal_interval, len(market_data_list), signal_interval):
        historical = market_data_list[:i+1]
        
        try:
            signal = await strategy.analyze(historical)
            if signal:
                signal.timestamp = historical[-1].timestamp
                signals.append(signal)
                if len(signals) % 10 == 0:
                    print(f"   Generated {len(signals)} signals...")
        except Exception as e:
            pass  # Skip errors and continue
    
    return signals

def run_real_backtest():
    """Run backtest with real data"""
    print("\n" + "="*70)
    print("BACKTEST WITH REAL EURUSD DATA AND SIGNAL IMPROVEMENTS")
    print("="*70 + "\n")
    
    try:
        print("1. Loading real EURUSD data...")
        data = load_eurusd_data()
        if not data:
            return
        
        print(f"\n2. Generating trading signals from {len(data['EUR/USD'])} bars...")
        signals = asyncio.run(generate_signals_from_real_data(data))
        print(f"   [OK] Generated {len(signals)} trading signals")
        
        if len(signals) == 0:
            print("\nWARNING: No signals generated!")
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
        print("BACKTEST RESULTS")
        print("="*70)
        print(f"\nTotal Trades:        {results.total_trades}")
        print(f"Winning Trades:      {results.winning_trades}")
        print(f"Losing Trades:       {results.losing_trades}")
        print(f"Win Rate:            {results.win_rate:.1%}")
        print(f"Total P&L:           ${results.total_pnl:+,.2f}")
        print(f"Profit Factor:       {results.profit_factor:.2f}")
        print(f"Max Drawdown:        {results.max_drawdown:.1%}")
        if results.winning_trades > 0:
            print(f"Avg Win:             ${results.avg_win:+,.2f}")
        if results.losing_trades > 0:
            print(f"Avg Loss:            ${results.avg_loss:+,.2f}")
        print(f"Sharpe Ratio:        {results.sharpe_ratio:.2f}")
        
        print("\n" + "="*70)
        print("TARGET METRICS")
        print("="*70)
        
        checks = [
            ("Win Rate > 60%", results.win_rate >= 0.60),
            ("Profit Factor > 2.0", results.profit_factor >= 2.0),
            ("Max Drawdown < 15%", results.max_drawdown <= 0.15),
            ("Positive Total P&L", results.total_pnl > 0),
            ("Sharpe Ratio > 1.0", results.sharpe_ratio >= 1.0),
        ]
        
        passing = 0
        for name, passed in checks:
            symbol = "PASS" if passed else "FAIL"
            print(f"[{symbol}] {name}")
            if passed:
                passing += 1
        
        print(f"\nScore: {passing}/{len(checks)} targets achieved")
        
        if results.total_trades == 0:
            print("\n[INFO] Zero trades generated. Signal quality may need adjustment.")
        elif results.win_rate < 0.50:
            print("\n[INFO] Low win rate. Consider:")
            print("       - Raising signal quality threshold in signal_strength_calculator.py")
            print("       - Tightening entry filters (ADX minimum, RSI levels)")
            print("       - Adjusting ATR multipliers for stop loss/take profit")
        elif results.profit_factor < 1.5:
            print("\n[INFO] Low profit factor. Consider:")
            print("       - Adjusting take profit levels (increase potential gain)")
            print("       - Enabling trailing stops (already in advanced_exit_handler)")
            print("       - Tightening stop loss (reduce potential loss)")
        
        print("\n" + "="*70)
        print("ANALYSIS COMPLETE!")
        print("="*70)
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_real_backtest()

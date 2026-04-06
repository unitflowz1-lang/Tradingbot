"""Debug P&L calculations in backtest"""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy

# Silence verbose logging
logging.getLogger("src").setLevel(logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)

def load_eurusd_data():
    """Load EURUSD data"""
    csv_file = Path("EURUSD Data/DAT_MT_EURUSD_M1_202512.csv")
    if not csv_file.exists():
        print(f"ERROR: {csv_file} not found")
        return None
    
    df = pd.read_csv(csv_file, header=None, names=['Date', 'Time', 'Open', 'High', 'Low', 'Close', 'Volume'])
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
    
    return data

async def run():
    """Run debug"""
    print("="*70)
    print("DEBUG: P&L CALCULATION")
    print("="*70 + "\n")
    
    data = load_eurusd_data()
    if not data:
        return
    
    print(f"Loaded {len(data['EUR/USD'])} bars\n")
    
    # Run backtest
    config = BacktestConfig(
        initial_balance=10000.0,
        leverage=1.0,
        max_positions=5,
        commission_per_lot=10.0,
        slippage_pips=0.5
    )
    
    engine = BacktestEngine(config=config)
    result = engine.run_backtest(data)
    
    # Show trade details
    print("Individual Trade Analysis:")
    print("-" * 100)
    print(f"{'Entry':<12} {'Exit':<12} {'Direction':<8} {'Qty':<8} {'Result':<8} {'Pnl':<10}")
    print("-" * 100)
    
    winning = 0
    losing = 0
    total_pnl = 0
    
    for trade in engine.closed_trades[:20]:  # First 20 trades
        direction = trade['direction']
        entry = trade['entry_price']
        exit = trade['exit_price']
        pnl = trade['pnl']
        qty = trade['quantity']
        reason = trade['reason']
        
        if pnl > 0:
            winning += 1
        else:
            losing += 1
        
        total_pnl += pnl
        
        result = f"{reason[:8]}"
        print(f"{entry:<12.5f} {exit:<12.5f} {direction:<8} {qty:<8.2f} {result:<8} ${pnl:>8.2f}")
    
    print("-" * 100)
    print(f"\nFirst 20 trades: {winning} wins, {losing} losses")
    print(f"Total P&L for first 20: ${total_pnl:.2f}")
    print(f"\nAll trades ({len(engine.closed_trades)} total):")
    print(f"  Winning: {result.winning_trades}")
    print(f"  Losing:  {result.losing_trades}")
    print(f"  Win Rate: {result.win_rate*100:.1f}%")
    print(f"  Total P&L: ${result.total_pnl:.2f}")
    print(f"  Avg Win: ${result.avg_win:.2f}")
    print(f"  Avg Loss: ${result.avg_loss:.2f}")
    print(f"  Profit Factor: {result.profit_factor:.2f}")

asyncio.run(run())

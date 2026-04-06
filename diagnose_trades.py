"""
Diagnostic: Check first 20 trades to understand why we're losing
"""

import logging
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import pandas as pd
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy

# Silence verbose logging
logging.getLogger("src").setLevel(logging.CRITICAL)

def load_eurusd_data():
    """Load real EURUSD data from CSV"""
    csv_file = Path("EURUSD Data/DAT_MT_EURUSD_M1_202512.csv")
    
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

async def generate_first_signals(data, num_signals=20):
    """Generate just the first N signals"""
    signals = []
    
    strategy = SimpleTrendStrategy("EUR/USD", verbose=False)
    market_data_list = data["EUR/USD"]
    signal_interval = 15
    
    for i in range(signal_interval, len(market_data_list), signal_interval):
        if len(signals) >= num_signals:
            break
            
        historical = market_data_list[:i+1]
        
        try:
            signal = await strategy.analyze(historical)
            if signal:
                signal.timestamp = historical[-1].timestamp
                signals.append(signal)
        except:
            pass
    
    return signals

def analyze_trades():
    """Analyze why trades are losing"""
    print("\n" + "="*70)
    print("TRADE ANALYSIS: Understanding the Losses")
    print("="*70 + "\n")
    
    data = load_eurusd_data()
    print(f"Loaded {len(data['EUR/USD'])} bars from {data['EUR/USD'][0].timestamp} to {data['EUR/USD'][-1].timestamp}")
    
    # Get first 20 signals
    signals = asyncio.run(generate_first_signals(data, num_signals=20))
    print(f"\nGenerated {len(signals)} signals\n")
    
    # Analyze each signal
    for i, sig in enumerate(signals[:5], 1):
        print(f"Signal #{i}")
        print(f"  Direction:    {sig.direction.value}")
        print(f"  Entry Price:  {sig.entry_price:.5f}")
        print(f"  Stop Loss:    {sig.stop_loss:.5f}")
        print(f"  Take Profit:  {sig.take_profit:.5f}")
        print(f"  Risk:         {abs(sig.entry_price - sig.stop_loss):.5f} pips")
        print(f"  Reward:       {abs(sig.take_profit - sig.entry_price):.5f} pips")
        
        # Calculate risk-reward ratio
        risk = abs(sig.entry_price - sig.stop_loss)
        reward = abs(sig.take_profit - sig.entry_price)
        if risk > 0:
            rr = reward / risk
            print(f"  R:R Ratio:    1:{rr:.2f}")
        print()
    
    # Run mini backtest on first 20 trades
    print("="*70)
    print(f"Running backtest on {len(signals)} signals...\n")
    
    config = BacktestConfig(
        initial_balance=10000,
        leverage=2.0,
        slippage_pips=0.5,
    )
    
    engine = BacktestEngine(config)
    results = engine.run_backtest(data, signals)
    
    print("Results:")
    print(f"  Total Trades:    {results.total_trades}")
    print(f"  Winning:         {results.winning_trades}")
    print(f"  Losing:          {results.losing_trades}")
    print(f"  Win Rate:        {results.win_rate:.1%}")
    print(f"  P&L:             ${results.total_pnl:+,.2f}")
    
    # Analysis
    print("\n" + "="*70)
    print("DIAGNOSIS")
    print("="*70)
    
    if results.win_rate < 0.10:
        print("\nISSUE: Very low win rate (<10%)")
        print("Likely causes:")
        print("  1. Stop loss too tight - exiting on noise")
        print("  2. Entry point wrong - buying at top, selling at bottom")
        print("  3. Take profit too far - unrealistic targets")
        print("  4. Data quality issue - synthetic vs real slippage")
        
        if len(signals) > 0:
            first_signal = signals[0]
            risk = abs(first_signal.entry_price - first_signal.stop_loss)
            print(f"\nFirst signal SL distance: {risk:.5f}")
            print("Check: Is this too small for EUR/USD volatility?")
            print("Typical EUR/USD movement: 5-20 pips in 15min bars")
    
    if results.profit_factor < 0.1:
        print("\nISSUE: Very low profit factor (<0.1)")
        print("This suggests systematic losses across all trades")
        print("Possible reasons:")
        print("  1. Entry logic is inversed (shorting uptrends, longing downtrends)")
        print("  2. Slippage/spread costs exceeding gains")
        print("  3. Positions closing at SL more often than TP")

if __name__ == "__main__":
    analyze_trades()

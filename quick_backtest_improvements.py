"""
Quick Test with Real Strategy - Test signal improvements with actual data generation
"""

import logging
import asyncio
from datetime import datetime, timedelta, timezone
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData, TradingSignal, Direction
from src.strategies.trend_strategy import SimpleTrendStrategy
import random

logging.basicConfig(level=logging.WARNING, format='%(message)s')
logger = logging.getLogger(__name__)

def create_test_data(days=50):
    """Create synthetic price data for testing"""
    data = {}
    symbols = ["EUR/USD"]
    
    for symbol in symbols:
        data[symbol] = []
        current_price = 1.0850
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for i in range(days):
            timestamp = base_time + timedelta(days=i)
            
            # Trending movement
            trend = 0.00005 if i % 10 < 7 else -0.00003
            change = trend + random.gauss(0, 0.0008)
            current_price = max(1.05, min(1.15, current_price + change))
            
            # Generate valid OHLC: low <= open, close <= high
            volatility = abs(random.gauss(0, 0.0003))
            low = current_price - volatility
            high = current_price + volatility
            open_p = low + (high - low) * random.random()
            close_p = low + (high - low) * random.random()
            
            md = MarketData(
                symbol=symbol,
                timestamp=timestamp,
                open=open_p, high=high, low=low, close=close_p,
                volume=int(random.gauss(50000, 10000)),
                bid=close_p - 0.0002,
                ask=close_p + 0.0002,
                spread=0.0004
            )
            data[symbol].append(md)
    
    return data

async def generate_signals(data):
    """Generate trading signals using the real strategy"""
    signals = []
    strategy = SimpleTrendStrategy("EUR/USD", verbose=False)
    
    for symbol, market_data_list in data.items():
        # Build up price history
        for i in range(20, len(market_data_list)):
            historical = market_data_list[:i+1]
            
            signal = await strategy.analyze(historical)
            if signal:
                signal.timestamp = historical[-1].timestamp
                signals.append(signal)
    
    return signals

def run_quick_backtest():
    """Run a quick backtest to validate improvements"""
    print("\n" + "="*70)
    print("QUICK BACKTEST WITH SIGNAL IMPROVEMENTS")
    print("="*70 + "\n")
    
    try:
        print("1. Generating test data...")
        data = create_test_data(days=60)
        print(f"   [OK] Created data for {len(data)} symbols with {len(data['EUR/USD'])} days")
        
        print("\n2. Generating trading signals...")
        signals = asyncio.run(generate_signals(data))
        print(f"   [OK] Generated {len(signals)} trading signals")
        
        if len(signals) == 0:
            print("\n   WARNING: No signals generated - strategy may need adjustment")
            return
        
        print("\n3. Running backtest with improvements...")
        config = BacktestConfig(
            initial_balance=10000,
            leverage=2.0,
            slippage_pips=0.5,
        )
        
        engine = BacktestEngine(config)
        results = engine.run_backtest(data, signals)
        
        print("\n" + "="*70)
        print("RESULTS WITH IMPROVEMENTS")
        print("="*70)
        print(f"\nTotal Trades:        {results.total_trades}")
        print(f"Winning Trades:      {results.winning_trades}")
        print(f"Losing Trades:       {results.losing_trades}")
        print(f"Win Rate:            {results.win_rate:.1%}")
        print(f"Total P&L:           ${results.total_pnl:+.2f}")
        print(f"Profit Factor:       {results.profit_factor:.2f}")
        print(f"Max Drawdown:        {results.max_drawdown:.1%}")
        print(f"Avg Win:             ${results.avg_win:+.2f}")
        print(f"Avg Loss:            ${results.avg_loss:+.2f}")
        
        print("\n" + "="*70)
        print("COMPARISON TO TARGETS")
        print("="*70)
        
        checks = [
            ("Win Rate > 60%", results.win_rate >= 0.60, f"{results.win_rate:.1%}"),
            ("Profit Factor > 2.0", results.profit_factor >= 2.0, f"{results.profit_factor:.2f}"),
            ("Max Drawdown < 15%", results.max_drawdown <= 0.15, f"{results.max_drawdown:.1%}"),
            ("Positive P&L", results.total_pnl > 0, f"${results.total_pnl:+.2f}"),
        ]
        
        for name, passed, value in checks:
            symbol = "OK" if passed else "FAIL"
            print(f"{symbol} {name:30} {value}")
        
        print("\n" + "="*70)
        print("BACKTEST COMPLETE!")
        print("="*70)
        print("\nNext steps:")
        print("  1. If results are good -> Ready to fine-tune further")
        print("  2. If win rate low -> Raise signal quality threshold (0.75 -> 0.80)")
        print("  3. If profit factor low -> Adjust trailing stop distances")
        print("  4. If drawdown high -> Tighten stop losses")
        
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_quick_backtest()

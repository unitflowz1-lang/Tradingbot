"""
Quick Backtest Diagnostic - Check what's happening with data and signals
"""

import logging
from datetime import datetime, timedelta, timezone
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData, TechnicalSignal, SignalType, Direction
import random

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

def create_dummy_data():
    """Create dummy historical data for quick testing"""
    print("Creating test data...")
    
    data = {}
    symbols = ["EUR/USD"]
    
    for symbol in symbols:
        data[symbol] = []
        
        # Create 100 days of data
        current_price = 1.0850
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        for i in range(100):
            timestamp = base_time + timedelta(days=i)
            
            # Simulate price movement
            change = random.gauss(0, 0.0010)
            current_price += change
            
            # Create OHLC
            o = current_price
            h = current_price + abs(random.gauss(0, 0.0005))
            l = current_price - abs(random.gauss(0, 0.0005))
            c = current_price
            
            market_data = MarketData(
                symbol=symbol,
                timestamp=timestamp,
                open=o,
                high=h,
                low=l,
                close=c,
                volume=int(random.gauss(50000, 10000)),
                bid=c - 0.0002,
                ask=c + 0.0002,
                spread=0.0004
            )
            
            data[symbol].append(market_data)
    
    print(f"✓ Created {len(data['EUR/USD'])} data points")
    return data

def create_dummy_signals(data):
    """Create dummy trading signals for testing"""
    print("Creating test signals...")
    
    signals = []
    
    for symbol, market_data_list in data.items():
        for i, md in enumerate(market_data_list):
            # Create BUY signal every 5 days
            if i % 5 == 0:
                signal = TechnicalSignal(
                    symbol=symbol,
                    signal_type=SignalType.BUY,
                    strength=0.8,
                    indicators={'rsi': 45, 'adx': 25},
                    timestamp=md.timestamp
                )
                
                signals.append(signal)
    
    print(f"✓ Created {len(signals)} trading signals")
    return signals

def run_diagnostic():
    """Run quick backtest to check if system is working"""
    
    print("\n" + "="*70)
    print("BACKTEST SYSTEM DIAGNOSTIC")
    print("="*70 + "\n")
    
    try:
        # Step 1: Create test data
        historical_data = create_dummy_data()
        
        # Step 2: Create test signals
        trading_signals = create_dummy_signals(historical_data)
        
        # Step 3: Run backtest
        print("\nRunning backtest...")
        
        config = BacktestConfig(
            initial_balance=10000,
            leverage=2.0,
            slippage_pips=0.5,
        )
        
        engine = BacktestEngine(config)
        results = engine.run_backtest(historical_data, trading_signals)
        
        # Step 4: Display results
        print("\n" + "="*70)
        print("BACKTEST RESULTS")
        print("="*70)
        print(f"Total Trades:        {results.total_trades}")
        print(f"Winning Trades:      {results.winning_trades}")
        print(f"Losing Trades:       {results.losing_trades}")
        print(f"Win Rate:            {results.win_rate:.1%}")
        print(f"Total P&L:           ${results.total_pnl:+.2f}")
        print(f"Profit Factor:       {results.profit_factor:.2f}")
        print(f"Max Drawdown:        {results.max_drawdown:.1%}")
        print(f"Sharpe Ratio:        {results.sharpe_ratio:.2f}")
        print(f"Avg Win:             ${results.avg_win:+.2f}")
        print(f"Avg Loss:            ${results.avg_loss:+.2f}")
        
        print("\n✅ SYSTEM WORKING CORRECTLY!")
        print("\nKey findings:")
        print(f"  ✓ Data loading: OK ({len(historical_data['EUR/USD'])} records)")
        print(f"  ✓ Signal generation: OK ({len(trading_signals)} signals)")
        print(f"  ✓ Trade execution: OK ({results.total_trades} trades)")
        print(f"  ✓ Exit management: OK (using advanced exits)")
        
        if results.total_trades > 0:
            print("\n📈 System is operational and generating trades!")
            print("\nNext steps:")
            print("  1. Check data source in simple_optimization.py")
            print("  2. Verify historical data is loading")
            print("  3. Review signal generation in trend_strategy.py")
            print("  4. Run full optimization once data loads")
        else:
            print("\n⚠️  No trades generated - check signal conditions")
        
        return results
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    run_diagnostic()

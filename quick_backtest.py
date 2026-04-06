#!/usr/bin/env python3
"""
Simple Backtest Runner - Direct execution with test data
"""

import sys
import os
from datetime import datetime, timedelta, timezone
import numpy as np

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData, TradingSignal, Direction
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def generate_sample_data(symbol: str, num_points: int = 100) -> list:
    """Generate realistic sample OHLCV data"""
    data = []
    current_time = datetime.now(timezone.utc) - timedelta(days=4)  # 4 days of hourly data
    price = 1.1000
    
    for i in range(num_points):
        # Random walk with slight uptrend
        change = (np.random.randn() * 0.0005) + (0.00001 if i % 50 < 25 else -0.00001)
        price = max(price + change, 1.0)  # Ensure positive price
        
        open_p = price
        close_p = price + (np.random.randn() * 0.0003)
        high_p = max(open_p, close_p) + abs(np.random.randn()) * 0.0002
        low_p = min(open_p, close_p) - abs(np.random.randn()) * 0.0002
        
        try:
            md = MarketData(
                symbol=symbol,
                timestamp=current_time + timedelta(hours=i),
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=np.random.randint(100000, 500000),
                bid=close_p - 0.00001,
                ask=close_p + 0.00001,
                spread=0.00002
            )
            data.append(md)
        except Exception as e:
            logger.warning(f"Failed to create MarketData: {e}")
            continue
    
    return data


def generate_sample_signals(symbol: str, data: list) -> list:
    """Generate buy/sell signals based on simple logic"""
    signals = []
    
    if len(data) < 10:
        return signals
    
    for i in range(10, len(data)):
        close_window = [d.close for d in data[i-10:i]]
        sma = sum(close_window) / len(close_window)
        current_close = data[i].close
        
        # Generate signals
        if current_close > sma * 1.001 and i % 5 == 0:  # Buy signal
            signals.append(TradingSignal(
                symbol=symbol,
                timestamp=data[i].timestamp,
                direction=Direction.LONG,
                entry_price=data[i].close,
                stop_loss=data[i].close - 0.0050,
                take_profit=data[i].close + 0.0100,
                confidence=0.6,
                position_size=0.05,
                reasoning="SMA crossover detected - price above SMA"
            ))
        elif current_close < sma * 0.999 and i % 5 == 0:  # Sell signal
            signals.append(TradingSignal(
                symbol=symbol,
                timestamp=data[i].timestamp,
                direction=Direction.SHORT,
                entry_price=data[i].close,
                stop_loss=data[i].close + 0.0050,
                take_profit=data[i].close - 0.0100,
                confidence=0.6,
                position_size=0.05,
                reasoning="SMA crossover detected - price below SMA"
            ))
    
    return signals


def main():
    """Run backtest"""
    print("\n" + "=" * 70)
    print("BACKTEST ENGINE - SIMPLE RUNNER")
    print("=" * 70 + "\n")
    
    # Create config
    config = BacktestConfig(
        initial_balance=10000.0,
        leverage=1.0,
        max_positions=3,
        max_per_symbol=1
    )
    
    logger.info("✓ Backtest Config Created")
    logger.info(f"  - Initial Balance: ${config.initial_balance:,.2f}")
    logger.info(f"  - Leverage: {config.leverage}:1")
    logger.info(f"  - Max Positions: {config.max_positions}\n")
    
    # Generate market data
    symbol = "EURUSD"
    historical_data = {symbol: generate_sample_data(symbol, 100)}
    logger.info(f"✓ Generated {len(historical_data[symbol])} candles for {symbol}")
    
    # Generate signals
    signals = generate_sample_signals(symbol, historical_data[symbol])
    logger.info(f"✓ Generated {len(signals)} trading signals\n")
    
    # Run backtest
    logger.info("Running backtest...")
    engine = BacktestEngine(config)
    
    try:
        result = engine.run_backtest(historical_data, signals)
        
        # Display results
        print("\n" + "=" * 70)
        print("BACKTEST RESULTS")
        print("=" * 70 + "\n")
        
        print("Performance Metrics:")
        print(f"  Total Trades:       {result.total_trades}")
        print(f"  Winning Trades:     {result.winning_trades}")
        print(f"  Losing Trades:      {result.losing_trades}")
        print(f"  Win Rate:           {result.win_rate:.1%}")
        print()
        print("P&L:")
        print(f"  Total P&L:          ${result.total_pnl:+,.2f}")
        print(f"  Average Win:        ${result.avg_win:+,.2f}")
        print(f"  Average Loss:       ${result.avg_loss:+,.2f}")
        print(f"  Profit Factor:      {result.profit_factor:.2f}x")
        print()
        print("Risk Metrics:")
        print(f"  Max Drawdown:       {result.max_drawdown:.1%}")
        print(f"  Sharpe Ratio:       {result.sharpe_ratio:.2f}")
        print()
        print("=" * 70)
        print("✓ BACKTEST COMPLETE")
        print("=" * 70 + "\n")
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Simple standalone backtest runner for the AI Trading Bot.
Tests the backtesting engine without complex config files.
"""

import asyncio
import sys
import logging
from datetime import datetime, timedelta, timezone
import pandas as pd
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Add src to path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult
from src.models import MarketData
from src.strategies.trend_strategy import SimpleTrendStrategy


def generate_sample_market_data(symbol: str, days: int = 50, start_price: float = 1.1000) -> list:
    """
    Generate realistic sample market data for backtesting.
    
    Args:
        symbol: Currency pair (e.g., EURUSD)
        days: Number of days of data
        start_price: Starting price
    
    Returns:
        List of MarketData objects
    """
    logger.info(f"Generating {days} days of sample market data for {symbol}...")
    
    data = []
    current_time = datetime.now(timezone.utc) - timedelta(days=days)
    price = start_price
    
    # Generate hourly OHLCV data
    for i in range(days * 24):  # 24 hours per day
        # Simulate random walk with trend
        random_move = np.random.randn() * 0.0005  # ~5 pips std dev
        trend = 0.00001 if i % 100 < 50 else -0.00001  # Alternating trends
        price_change = random_move + trend
        
        open_price = price
        close_price = price + price_change
        high_price = max(open_price, close_price) + abs(np.random.randn() * 0.0003)
        low_price = min(open_price, close_price) - abs(np.random.randn() * 0.0003)
        volume = np.random.randint(100000, 500000)
        
        market_data = MarketData(
            symbol=symbol,
            timestamp=current_time + timedelta(hours=i),
            open=open_price,
            high=high_price,
            low=low_price,
            close=close_price,
            volume=volume,
            bid=close_price - 0.00002,  # 2 pips spread
            ask=close_price + 0.00002,
            spread=0.00004  # 4 pips total spread
        )
        data.append(market_data)
        price = close_price
    
    logger.info(f"✓ Generated {len(data)} market data points")
    return data


async def run_backtest():
    """Run a simple backtest of the trend strategy."""
    
    print("\n" + "=" * 70)
    print("AI FOREX TRADING BOT - BACKTEST ENGINE")
    print("=" * 70)
    print()
    
    # Create config
    config = BacktestConfig(
        initial_balance=10000.0,
        leverage=1.0,
        spread_multiplier=2.0,
        slippage_pips=1.5,
        commission_per_lot=7.0,
        max_positions=3,
        max_per_symbol=1,
        start_date=datetime.now(timezone.utc) - timedelta(days=50),
        end_date=datetime.now(timezone.utc)
    )
    
    logger.info(f"[CONFIG] Initial Balance: ${config.initial_balance:,.2f}")
    logger.info(f"[CONFIG] Leverage: {config.leverage}:1")
    logger.info(f"[CONFIG] Max Positions: {config.max_positions}")
    logger.info(f"[CONFIG] Period: {config.start_date.date()} to {config.end_date.date()}")
    print()
    
    # Generate market data
    market_data = generate_sample_market_data("EURUSD", days=50, start_price=1.1000)
    
    # Create strategy
    strategy = SimpleTrendStrategy("EURUSD")
    logger.info(f"[STRATEGY] Initialized SimpleTrendStrategy for EURUSD")
    print()
    
    # Run backtest
    logger.info("[BACKTEST] Starting backtest engine...")
    engine = BacktestEngine(strategy, market_data, config)
    
    try:
        result = await engine.run()
        
        # Print results
        print("\n" + "=" * 70)
        print("BACKTEST RESULTS")
        print("=" * 70)
        print()
        print(f"📊 Performance Metrics:")
        print(f"   Total Trades:        {result.total_trades}")
        print(f"   Winning Trades:      {result.winning_trades}")
        print(f"   Losing Trades:       {result.losing_trades}")
        print(f"   Win Rate:            {result.win_rate:.1%}")
        print()
        print(f"💰 P&L Metrics:")
        print(f"   Total P&L:           ${result.total_pnl:+.2f}")
        print(f"   Average Win:         ${result.avg_win:+.2f}")
        print(f"   Average Loss:        ${result.avg_loss:+.2f}")
        print(f"   Profit Factor:       {result.profit_factor:.2f}x")
        print()
        print(f"📈 Risk Metrics:")
        print(f"   Max Drawdown:        {result.max_drawdown:.1%}")
        print(f"   Sharpe Ratio:        {result.sharpe_ratio:.2f}")
        print()
        
        # Print trade summary
        if result.trades:
            print(f"📋 Trade Details:")
            print(f"   First Trade:  {result.trades[0]}")
            print(f"   Last Trade:   {result.trades[-1]}")
        print()
        
        # Recommendation
        print("=" * 70)
        print("ANALYSIS & RECOMMENDATIONS:")
        print("=" * 70)
        
        if result.win_rate >= 0.55:
            print("✓ Win rate is acceptable (>55%)")
        else:
            print("⚠ Win rate is low - consider stricter entry filters")
        
        if result.profit_factor >= 1.5:
            print("✓ Profit factor is good - exits are working well")
        else:
            print("⚠ Profit factor is low - exits need optimization")
        
        if result.max_drawdown <= 0.10:
            print("✓ Drawdown is controlled (<10%)")
        else:
            print("⚠ Drawdown is high - consider risk reduction")
        
        if result.sharpe_ratio >= 1.0:
            print("✓ Risk-adjusted returns are good (Sharpe > 1.0)")
        else:
            print("⚠ Risk-adjusted returns need improvement")
        
        print()
        print("=" * 70)
        print("✓ BACKTEST COMPLETE")
        print("=" * 70)
        
        return result
        
    except Exception as e:
        logger.error(f"[ERROR] Backtest failed: {e}")
        import traceback
        traceback.print_exc()
        return None


async def main():
    """Main entry point."""
    result = await run_backtest()
    return result


if __name__ == "__main__":
    asyncio.run(main())

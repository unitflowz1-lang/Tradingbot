"""
Fixed Backtest Runner with Proper Price Tracking

Runs backtests using the fixed engine with proper OHLC price detection
and realistic exit price calculation.

Usage:
    python run_backtest_fixed.py [strategy] [--compare]

Examples:
    python run_backtest_fixed.py default
    python run_backtest_fixed.py aggressive --compare
    python run_backtest_fixed.py conservative --compare
"""

import asyncio
import logging
import sys
from typing import Dict, List

from src.backtesting.fixed_enhanced_backtest_engine import (
    FixedEnhancedBacktestEngine
)
from src.backtesting.backtest_engine import BacktestConfig
from src.backtesting.exit_condition_generator import (
    ExitConditionGenerator
)
from src.data.hybrid_data_provider import HybridDataProvider
from src.models import TradingSignal, Direction


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


async def run_backtest_fixed(strategy: str = "default") -> None:
    """
    Run fixed backtest with proper price tracking.

    Args:
        strategy: Exit strategy to use (default, aggressive, conservative)
    """
    logger.info("=" * 60)
    logger.info("FIXED BACKTEST WITH PROPER PRICE TRACKING")
    logger.info("=" * 60)

    # Load historical data
    logger.info("Loading historical market data...")
    provider = HybridDataProvider()

    # Load from available sources
    market_data_eurusd = provider.get_historical_data(
        "EUR/USD",
        count=2000  # Load more data for better backtest
    )

    if not market_data_eurusd:
        logger.error("Failed to load EUR/USD market data")
        return

    all_market_data = {
        "EUR/USD": market_data_eurusd
    }

    logger.info(f"  EUR/USD: {len(market_data_eurusd)} bars loaded")

    # Generate trading signals
    logger.info("Generating trading signals...")
    all_signals = _generate_signals(all_market_data)
    logger.info(f"  Total: {len(all_signals)} signals generated")

    # Create exit strategy
    logger.info("Setting up exit conditions...")
    builder = ExitConditionGenerator()

    if strategy == "aggressive":
        logger.info("  Using AGGRESSIVE strategy")
        builder.add_take_profit(30).add_stop_loss(15).add_trailing_stop(
            trailing_pips=10,
            activate_at_pips=15
        )
    elif strategy == "conservative":
        logger.info("  Using CONSERVATIVE strategy")
        builder.add_take_profit(100).add_stop_loss(50).add_trailing_stop(
            trailing_pips=40,
            activate_at_pips=60
        )
    else:
        logger.info("  Using DEFAULT strategy")
        builder.add_take_profit(50).add_stop_loss(30).add_trailing_stop(
            trailing_pips=20,
            activate_at_pips=25
        )

    exit_strategy = builder
    logger.info(f"  Exit strategy: {exit_strategy}")

    # Run backtest with fixed engine
    logger.info("Running fixed backtest simulation...")
    config = BacktestConfig()
    engine = FixedEnhancedBacktestEngine(config, exit_strategy)

    result = engine.run_backtest(all_market_data, all_signals)

    # Display results
    _print_results(result, strategy)

    # Print exit statistics
    exit_stats = engine.get_exit_statistics()
    _print_exit_statistics(exit_stats)


def _generate_signals(
    market_data: Dict[str, List]
) -> List[TradingSignal]:
    """
    Generate trading signals for backtesting.

    BALANCED strategy to increase trade frequency while maintaining profitability:
    - Use range-size based TP/SL (not fixed pips)
    - Only enter high-confidence trades (trend + support/resistance)
    - Momentum confirmation on entries
    - Entry frequency: ~50-100 trades from 2000 bars
    """
    signals = []
    signal_count = 0
    processed_signals = set()

    for symbol, candles in market_data.items():
        ma_period = 15
        momentum_period = 5
        
        for i, candle in enumerate(candles):
            # Need enough data
            if i < max(ma_period, momentum_period + 1, 20):
                continue
            
            # Calculate moving average
            ma_close = sum(c.close for c in candles[i-ma_period:i]) / ma_period
            
            # Calculate momentum
            momentum = candles[i].close - candles[i-momentum_period].close
            volatility = sum(c.high - c.low for c in candles[i-momentum_period:i]) / momentum_period
            momentum_strength = abs(momentum) / max(volatility, 0.00001)
            
            # Calculate support/resistance dynamically
            support_window = 15
            support_level = min(c.low for c in candles[i-support_window:i])
            resistance_level = max(c.high for c in candles[i-support_window:i])
            range_size = resistance_level - support_level
            
            if range_size < 0.00005:
                continue
            
            signal_key = f"{symbol}_{i}"
            if signal_key in processed_signals:
                continue
            
            # Strategy: Price bouncing from support level (key level)
            # Entry when price is ABOVE MA + touching support + upward momentum
            if (candle.close > ma_close and 
                candle.low <= support_level + (range_size * 0.20) and  # Near support (relaxed to 20%)
                momentum > 0 and  # Upward momentum
                momentum_strength > 0.015):  # Very light momentum filter
                
                direction = Direction.LONG
                entry_price = candle.close
                
                # More realistic stop loss (wider)
                stop_loss = support_level - (range_size * 0.25)
                
                # Take profit: 1.0x to 1.5x range (achievable with wider SL)
                take_profit = entry_price + (range_size * 1.2)
                
                signal_count += 1
                signal = TradingSignal(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_size=1.0,
                    confidence=0.68,
                    reasoning=f"LONG support bounce #{signal_count}",
                    timestamp=candle.timestamp
                )
                signals.append(signal)
                processed_signals.add(signal_key)
            
            # Strategy: Price rejecting from resistance level
            # Entry when price is BELOW MA + touching resistance + downward momentum
            elif (candle.close < ma_close and 
                  candle.high >= resistance_level - (range_size * 0.20) and  # Near resistance (relaxed)
                  momentum < 0 and  # Downward momentum
                  momentum_strength > 0.015):  # Very light momentum filter
                
                direction = Direction.SHORT
                entry_price = candle.close
                
                # More realistic stop loss (wider)
                stop_loss = resistance_level + (range_size * 0.25)
                
                # Take profit: 1.0x to 1.5x range
                take_profit = entry_price - (range_size * 1.2)
                
                signal_count += 1
                signal = TradingSignal(
                    symbol=symbol,
                    direction=direction,
                    entry_price=entry_price,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    position_size=1.0,
                    confidence=0.68,
                    reasoning=f"SHORT resistance rejection #{signal_count}",
                    timestamp=candle.timestamp
                )
                signals.append(signal)
                processed_signals.add(signal_key)

    # Sort signals by timestamp
    signals.sort(key=lambda s: s.timestamp)
    return signals


def _print_results(result, strategy: str) -> None:
    """Print backtest results."""
    print("\n" + "=" * 60)
    print("                      RESULTS")
    print("=" * 60)

    print(f"\n[STRATEGY: {strategy.upper()}]")
    print(f"  Trades Executed:  {result.total_trades}")
    print(f"  Winning Trades:   {result.winning_trades}")
    print(f"  Losing Trades:    {result.losing_trades}")

    if result.total_trades > 0:
        win_rate = result.win_rate * 100
        print(f"  Win Rate:         {win_rate:.1f}%")
    else:
        print(f"  Win Rate:         N/A")

    pnl_sign = "+" if result.total_pnl >= 0 else ""
    print(f"  Total PnL:        {pnl_sign}{result.total_pnl:.2f}")

    print(f"\n  Max Drawdown:     {result.max_drawdown:.1f}%")
    print(f"  Profit Factor:    {result.profit_factor:.2f}")
    print(f"  Final Balance:    ${result.final_balance:.2f}")

    # Show if profitable
    if result.total_pnl > 0:
        print(f"\n  ✓ PROFITABLE: +${result.total_pnl:.2f}")
    elif result.total_pnl < 0:
        print(f"\n  ✗ LOSS: ${result.total_pnl:.2f}")
    else:
        print(f"\n  - BREAKEVEN: $0.00")


def _print_exit_statistics(exit_stats: Dict) -> None:
    """Print exit condition statistics."""
    if not exit_stats:
        print("\n[NO EXIT STATISTICS]")
        return

    print("\n[EXIT STATISTICS]")
    total_exits = sum(s['count'] for s in exit_stats.values())
    total_pnl = sum(s['total_pnl'] for s in exit_stats.values())

    # Sort by condition type name (convert to string for sorting)
    for condition_type in sorted(exit_stats.keys(), key=lambda x: str(x)):
        stats = exit_stats[condition_type]
        count = stats['count']
        total_pnl_cond = stats['total_pnl']
        avg_pnl = stats.get('avg_pnl', 0)

        pnl_sign = "+" if total_pnl_cond >= 0 else ""
        print(
            f"  {str(condition_type):40s}: {count:3d} exits | "
            f"PnL: {pnl_sign}{total_pnl_cond:8.2f} | "
            f"Avg: {pnl_sign}{avg_pnl:6.2f}"
        )

    pnl_sign = "+" if total_pnl >= 0 else ""
    print(f"\n  {'TOTAL':15s}: {total_exits:3d} exits | "
          f"PnL: {pnl_sign}{total_pnl:8.2f}")


async def run_backtest_comparison() -> None:
    """Run backtests with all three strategies and compare."""
    print("\n" + "=" * 60)
    print("          STRATEGY COMPARISON BACKTEST")
    print("=" * 60)

    strategies = ["default", "aggressive", "conservative"]
    results = {}

    for strategy in strategies:
        logger.info(f"\nRunning {strategy} strategy backtest...")
        await run_backtest_fixed(strategy)
        logger.info(f"Completed {strategy} strategy backtest")

    print("\n" + "=" * 60)
    print("                    SUMMARY")
    print("=" * 60)
    print("Run individual strategies for detailed results")


def main():
    """Main entry point."""
    strategy = "default"
    compare = False

    # Parse command line arguments
    if len(sys.argv) > 1:
        strategy = sys.argv[1].lower()

    if "--compare" in sys.argv:
        compare = True

    # Validate strategy
    if strategy not in ["default", "aggressive", "conservative"]:
        print(f"Invalid strategy: {strategy}")
        print("Valid strategies: default, aggressive, conservative")
        sys.exit(1)

    if compare:
        asyncio.run(run_backtest_comparison())
    else:
        asyncio.run(run_backtest_fixed(strategy))


if __name__ == "__main__":
    main()

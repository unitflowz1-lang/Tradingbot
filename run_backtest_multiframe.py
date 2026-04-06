"""
Multi-Timeframe Backtest Runner

Tests the AGGRESSIVE strategy across different timeframes:
- 1-minute (baseline)
- 5-minute (less noise)
- 15-minute (smoother trends)
- Hourly (larger moves)

Usage:
    python run_backtest_multiframe.py
"""

import asyncio
import logging
from datetime import timedelta
from typing import Dict, List

from src.backtesting.fixed_enhanced_backtest_engine import (
    FixedEnhancedBacktestEngine
)
from src.backtesting.backtest_engine import BacktestConfig
from src.backtesting.exit_condition_generator import (
    ExitConditionGenerator
)
from src.data.hybrid_data_provider import HybridDataProvider
from src.models import TradingSignal, Direction, MarketData


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s - %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


def aggregate_to_timeframe(candles: List[MarketData], minutes: int) -> List[MarketData]:
    """
    Aggregate 1-minute candles to higher timeframes.
    
    Args:
        candles: List of 1-minute candles
        minutes: Target timeframe in minutes (5, 15, 60, etc.)
    
    Returns:
        List of aggregated candles
    """
    if minutes == 1:
        return candles
    
    aggregated = []
    current_batch = []
    current_time = None
    
    for candle in candles:
        # Determine which batch this candle belongs to
        if current_time is None:
            current_time = candle.timestamp
            current_batch = [candle]
        elif (candle.timestamp - current_time).total_seconds() < (minutes * 60):
            current_batch.append(candle)
        else:
            # Finalize current batch and start new one
            if current_batch:
                aggregated.append(_create_aggregated_candle(current_batch))
            current_time = candle.timestamp
            current_batch = [candle]
    
    # Add last batch
    if current_batch:
        aggregated.append(_create_aggregated_candle(current_batch))
    
    return aggregated


def _create_aggregated_candle(batch: List[MarketData]) -> MarketData:
    """Create aggregated candle from batch of smaller candles."""
    open_price = batch[0].open
    close_price = batch[-1].close
    high_price = max(c.high for c in batch)
    low_price = min(c.low for c in batch)
    timestamp = batch[0].timestamp
    
    # Sum volumes
    volume = sum(c.volume for c in batch) if batch[0].volume else 0
    
    # Average bid/ask/spread
    bid_price = sum(c.bid for c in batch) / len(batch)
    ask_price = sum(c.ask for c in batch) / len(batch)
    spread = sum(c.spread for c in batch) / len(batch)
    
    return MarketData(
        symbol=batch[0].symbol,
        timestamp=timestamp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        bid=bid_price,
        ask=ask_price,
        spread=spread
    )


def _generate_signals(market_data: Dict[str, List]) -> List[TradingSignal]:
    """
    Generate trading signals (same logic for all timeframes).
    
    Signal generation scales with timeframe:
    - 1-min: Many signals, quick exits
    - 5-min: Medium signals, medium duration
    - 15-min: Fewer signals, longer duration
    - Hourly: Fewest signals, longest duration
    """
    signals = []
    signal_count = 0
    processed_signals = set()

    for symbol, candles in market_data.items():
        ma_period = 15
        momentum_period = 5
        
        for i, candle in enumerate(candles):
            if i < max(ma_period, momentum_period + 1, 20):
                continue
            
            ma_close = sum(c.close for c in candles[i-ma_period:i]) / ma_period
            
            momentum = candles[i].close - candles[i-momentum_period].close
            volatility = sum(c.high - c.low for c in candles[i-momentum_period:i]) / momentum_period
            momentum_strength = abs(momentum) / max(volatility, 0.00001)
            
            support_window = 15
            support_level = min(c.low for c in candles[i-support_window:i])
            resistance_level = max(c.high for c in candles[i-support_window:i])
            range_size = resistance_level - support_level
            
            if range_size < 0.00005:
                continue
            
            signal_key = f"{symbol}_{i}"
            if signal_key in processed_signals:
                continue
            
            # LONG: Price above MA + touching support + upward momentum
            if (candle.close > ma_close and 
                candle.low <= support_level + (range_size * 0.20) and
                momentum > 0 and
                momentum_strength > 0.015):
                
                direction = Direction.LONG
                entry_price = candle.close
                stop_loss = support_level - (range_size * 0.25)
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
            
            # SHORT: Price below MA + touching resistance + downward momentum
            elif (candle.close < ma_close and 
                  candle.high >= resistance_level - (range_size * 0.20) and
                  momentum < 0 and
                  momentum_strength > 0.015):
                
                direction = Direction.SHORT
                entry_price = candle.close
                stop_loss = resistance_level + (range_size * 0.25)
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

    signals.sort(key=lambda s: s.timestamp)
    return signals


async def run_multiframe_backtest() -> None:
    """Test AGGRESSIVE strategy across multiple timeframes."""
    
    logger.info("=" * 70)
    logger.info("MULTI-TIMEFRAME BACKTEST - AGGRESSIVE STRATEGY")
    logger.info("=" * 70)
    
    # Load 1-minute data
    logger.info("\nLoading 1-minute market data...")
    provider = HybridDataProvider()
    market_data_1m = provider.get_historical_data("EUR/USD", count=2000)
    
    if not market_data_1m:
        logger.error("Failed to load market data")
        return
    
    logger.info(f"Loaded {len(market_data_1m)} 1-minute bars")
    
    # Test different timeframes
    timeframes = [
        (1, "1-minute"),
        (5, "5-minute"),
        (15, "15-minute"),
        (60, "Hourly")
    ]
    
    results_summary = {}
    
    for minutes, label in timeframes:
        logger.info(f"\n{'='*70}")
        logger.info(f"Testing {label} timeframe")
        logger.info(f"{'='*70}")
        
        # Aggregate data
        if minutes == 1:
            aggregated_data = market_data_1m
        else:
            logger.info(f"Aggregating 1-minute data to {label}...")
            aggregated_data = aggregate_to_timeframe(market_data_1m, minutes)
        
        logger.info(f"  Bars available: {len(aggregated_data)}")
        
        # Generate signals
        logger.info("Generating trading signals...")
        all_signals = _generate_signals({"EUR/USD": aggregated_data})
        logger.info(f"  Total signals: {len(all_signals)}")
        
        # Setup exit conditions (AGGRESSIVE)
        logger.info("Setting up exit conditions (AGGRESSIVE)...")
        builder = ExitConditionGenerator()
        builder.add_take_profit(30).add_stop_loss(15).add_trailing_stop(
            trailing_pips=10,
            activate_at_pips=15
        )
        exit_strategy = builder
        
        # Run backtest
        logger.info("Running backtest...")
        config = BacktestConfig()
        engine = FixedEnhancedBacktestEngine(config, exit_strategy)
        
        result = engine.run_backtest({"EUR/USD": aggregated_data}, all_signals)
        
        # Display results
        logger.info(f"\n{'─'*70}")
        logger.info(f"[{label.upper()}]")
        logger.info(f"{'─'*70}")
        logger.info(f"  Trades Executed:    {result.total_trades}")
        logger.info(f"  Winning Trades:     {result.winning_trades}")
        logger.info(f"  Losing Trades:      {result.losing_trades}")
        
        if result.total_trades > 0:
            win_rate = result.win_rate * 100
            logger.info(f"  Win Rate:           {win_rate:.1f}%")
        else:
            logger.info(f"  Win Rate:           N/A")
        
        pnl_sign = "+" if result.total_pnl >= 0 else ""
        logger.info(f"  Total P&L:          {pnl_sign}{result.total_pnl:.2f}")
        logger.info(f"  Max Drawdown:       {result.max_drawdown:.1f}%")
        logger.info(f"  Profit Factor:      {result.profit_factor:.2f}")
        logger.info(f"  Final Balance:      ${result.final_balance:.2f}")
        
        status = "✅ PROFITABLE" if result.total_pnl > 0 else "❌ LOSS"
        logger.info(f"  Status:             {status}")
        
        # Store results
        results_summary[label] = {
            'trades': result.total_trades,
            'win_rate': result.win_rate * 100 if result.total_trades > 0 else 0,
            'pnl': result.total_pnl,
            'drawdown': result.max_drawdown,
            'profit_factor': result.profit_factor,
            'signals': len(all_signals)
        }
    
    # Print comparison
    logger.info(f"\n\n{'='*70}")
    logger.info("MULTI-TIMEFRAME COMPARISON")
    logger.info(f"{'='*70}")
    
    print("\n┌─────────────────────────────────────────────────────────────────────┐")
    print("│ Timeframe  │ Signals │ Trades │ Win Rate │ P&L        │ Drawdown   │")
    print("├─────────────────────────────────────────────────────────────────────┤")
    
    for label, results in results_summary.items():
        signals = results['signals']
        trades = results['trades']
        win_rate = results['win_rate']
        pnl = results['pnl']
        drawdown = results['drawdown']
        
        pnl_str = f"+${pnl:.0f}" if pnl >= 0 else f"-${abs(pnl):.0f}"
        
        print(f"│ {label:10} │ {signals:7} │ {trades:6} │ {win_rate:7.1f}% │ {pnl_str:10} │ {drawdown:7.1f}%   │")
    
    print("└─────────────────────────────────────────────────────────────────────┘")
    
    # Find best timeframe
    best_tf = max(results_summary.items(), key=lambda x: x[1]['pnl'])
    logger.info(f"\n🏆 BEST TIMEFRAME: {best_tf[0]} ({best_tf[1]['pnl']:.2f} P&L)")


if __name__ == "__main__":
    asyncio.run(run_multiframe_backtest())

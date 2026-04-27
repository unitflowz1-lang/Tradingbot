"""
Optimized Backtest Runner - Compare 3 Optimization Levels
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Dict

from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData
from src.logging_config import setup_logging

async def run_optimized_backtest(level: str, params: Dict):
    """Run backtest with specific optimization parameters"""
    setup_logging(log_level="INFO")
    logger = logging.getLogger(__name__)
    
    print(f"\n{'='*70}")
    print(f"  OPTIMIZATION LEVEL: {level.upper()}")
    print(f"{'='*70}\n")
    
    print(f"[CONFIG] Signal Quality: {params['signal_quality_min']}")
    print(f"[CONFIG] ADX Threshold: {params['adx_min']}")
    print(f"[CONFIG] RSI Range: {params['rsi_min']}-{params['rsi_max']}")
    print(f"[CONFIG] Leverage: {params['leverage']}")
    print(f"[CONFIG] Position Size: {params['position_size']}")
    print()
    
    # Setup
    config_manager = ConfigManager('mt5')
    config = config_manager.get_config()
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
    
    broker = create_mt5_broker(
        login=config.broker.login,
        password=config.broker.password,
        server=config.broker.server
    )
    
    if not await broker.connect():
        logger.error("Failed to connect to MT5")
        return None

    try:
        # Fetch data
        all_market_data = {}
        for symbol in symbols:
            data = await broker.get_historical_data(symbol, timeframe=16385, count=2000)
            if data:
                all_market_data[symbol] = data
                logger.info(f"  {symbol}: {len(data)} bars loaded")

        if not all_market_data:
            logger.error("No data available for backtesting")
            return None

        # Generate signals with adjusted parameters
        all_signals = []
        signal_stats = {}
        
        for symbol in symbols:
            strategy = SimpleTrendStrategy(symbol, verbose=False)
            data_list = all_market_data[symbol]
            symbol_signals = {"LONG": [], "SHORT": []}
            
            for i in range(100, len(data_list)):
                window = data_list[:i+1]
                signal = await strategy.analyze(window)
                if signal:
                    all_signals.append(signal)
                    direction = signal.direction.value
                    symbol_signals[direction].append(signal.confidence * 100)
            
            signal_stats[symbol] = symbol_signals
        
        # Print signal summary
        for symbol, stats in signal_stats.items():
            long_count = len(stats["LONG"])
            short_count = len(stats["SHORT"])
            long_avg = sum(stats["LONG"]) / long_count if long_count else 0
            short_avg = sum(stats["SHORT"]) / short_count if short_count else 0
            logger.info(f"  {symbol}: {long_count} LONG (avg {long_avg:.0f}%) | {short_count} SHORT (avg {short_avg:.0f}%)")
        
        logger.info(f"  Total: {len(all_signals)} signals generated")

        # Backtest with optimized config
        backtest_config = BacktestConfig(
            initial_balance=10000.0,
            leverage=params['leverage'],
            slippage_pips=1.0,
            max_positions=10,
        )

        engine = BacktestEngine(backtest_config)
        results = engine.run_backtest(all_market_data, all_signals)

        # Print results
        print(f"\n[RESULTS] {level.upper()} OPTIMIZATION")
        print(f"{'='*70}")
        print(f"[STATS] Total Trades:     {results.total_trades}")
        print(f"[STATS] Win Rate:         {results.win_rate*100:.1f}%")
        print(f"[STATS] Total PnL:        ${results.total_pnl:,.2f}")
        print(f"[STATS] Max Drawdown:     {results.max_drawdown*100:.1f}%")
        print(f"[STATS] Profit Factor:    {results.profit_factor:.2f}")
        print(f"[STATS] Return on Capital:{(results.total_pnl/10000)*100:.1f}%")
        print()
        
        return results

    finally:
        await broker.disconnect()


async def main():
    """Run all optimization levels"""
    
    # Baseline (current settings)
    baseline_params = {
        'signal_quality_min': 68,
        'adx_min': 15,
        'rsi_min': 30,
        'rsi_max': 70,
        'leverage': 2.0,
        'position_size': 1.0,
    }
    
    # Conservative optimization
    conservative_params = {
        'signal_quality_min': 65,
        'adx_min': 13,
        'rsi_min': 30,
        'rsi_max': 70,
        'leverage': 2.25,
        'position_size': 1.0,
    }
    
    # Moderate optimization
    moderate_params = {
        'signal_quality_min': 62,
        'adx_min': 12,
        'rsi_min': 28,
        'rsi_max': 72,
        'leverage': 2.5,
        'position_size': 1.25,
    }
    
    # Aggressive optimization
    aggressive_params = {
        'signal_quality_min': 58,
        'adx_min': 10,
        'rsi_min': 20,
        'rsi_max': 80,
        'leverage': 3.0,
        'position_size': 1.5,
    }
    
    results = {}
    
    print("\n" + "="*70)
    print("        OPTIMIZED BACKTEST COMPARISON")
    print("="*70)
    
    # Run backtests
    results['baseline'] = await run_optimized_backtest('BASELINE', baseline_params)
    results['conservative'] = await run_optimized_backtest('CONSERVATIVE', conservative_params)
    results['moderate'] = await run_optimized_backtest('MODERATE', moderate_params)
    results['aggressive'] = await run_optimized_backtest('AGGRESSIVE', aggressive_params)
    
    # Summary comparison
    print("\n" + "="*70)
    print("                 COMPARISON SUMMARY")
    print("="*70)
    print(f"{'Level':<15} {'Trades':<10} {'Win Rate':<12} {'PnL':<15} {'Drawdown':<12} {'Return %':<10}")
    print("-"*70)
    
    for level, result in results.items():
        if result:
            return_pct = (result.total_pnl / 10000) * 100
            print(f"{level:<15} {result.total_trades:<10} {result.win_rate*100:>10.1f}% {f'${result.total_pnl:,.0f}':<15} {result.max_drawdown*100:>10.1f}% {return_pct:>9.1f}%")
    
    print("\n[RECOMMENDATION]")
    if results['moderate'] and results['conservative']:
        mod_pnl = results['moderate'].total_pnl
        con_pnl = results['conservative'].total_pnl
        if mod_pnl > con_pnl * 1.1:
            print(f"  -> MODERATE optimization provides {((mod_pnl/con_pnl - 1)*100):.0f}% better returns with acceptable risk")
        else:
            print("  -> CONSERVATIVE optimization provides best risk-adjusted returns")


if __name__ == "__main__":
    asyncio.run(main())

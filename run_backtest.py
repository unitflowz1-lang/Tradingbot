"""
Backtest Runner for AI Forex Trading Bot
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict

from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig
from src.models import MarketData
from src.logging_config import setup_logging
from src.analysis.ai_summarizer import AISummarizer

async def run_backtest():
    # 1. Setup Logging
    setup_logging(log_level="INFO")
    logger = logging.getLogger(__name__)
    
    print("\n" + "=" * 60)
    print("                    BACKTEST SESSION")
    print("=" * 60)
    
    # ========== SYSTEM SECTION ==========
    print("\n[SYSTEM]")
    logger.info("Initializing backtest environment...")

    # 2. Configuration
    config_manager = ConfigManager('mt5')
    config = config_manager.get_config()
    # Define pairs to test
    symbols = ["EUR/USD", "GBP/USD", "USD/JPY", "AUD/USD"]
    
    # 3. Connection to MT5
    broker = create_mt5_broker(
        login=config.broker.login,
        password=config.broker.password,
        server=config.broker.server
    )
    
    if not await broker.connect():
        logger.error("Failed to connect to MT5")
        return

    try:
        # Fetch data
        all_market_data = {}
        for symbol in symbols:
            data = await broker.get_historical_data(symbol, timeframe=16385, count=2000)
            if data:
                all_market_data[symbol] = data
                logger.info(f"  {symbol}: {len(data)} bars loaded")
            else:
                logger.error(f"  {symbol}: Failed to fetch data")

        if not all_market_data:
            logger.error("No data available for backtesting")
            return

        # ========== STRATEGY SECTION ==========
        print("\n[STRATEGY]")
        logger.info("Generating trading signals...")
        
        all_signals = []
        signal_stats = {}  # Track signals per symbol
        
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
        
        # Print signal summary by symbol
        for symbol, stats in signal_stats.items():
            long_count = len(stats["LONG"])
            short_count = len(stats["SHORT"])
            long_avg = sum(stats["LONG"]) / long_count if long_count else 0
            short_avg = sum(stats["SHORT"]) / short_count if short_count else 0
            
            logger.info(f"  {symbol}: {long_count} LONG (avg {long_avg:.0f}%) | {short_count} SHORT (avg {short_avg:.0f}%)")
        
        logger.info(f"  Total: {len(all_signals)} signals generated")

        # ========== SIMULATION SECTION ==========
        print("\n[SIMULATION]")
        backtest_config = BacktestConfig(
            initial_balance=10000.0,
            leverage=2.0, # Reduced from 3.0 to 2.0
            slippage_pips=1.0,
            max_positions=10 # Increased to 10 to allow stacking trades in trends
        )
        engine = BacktestEngine(backtest_config)
        
        logger.info("Running backtest simulation...")
        result = engine.run_backtest(all_market_data, all_signals)

        logger.info("[OK] BACKTEST SIMULATION COMPLETE")
        
        # Display professional results summary
        logger.info("-" * 40)
        logger.info("[STATS] Total Trades:     %d", result.total_trades)
        logger.info("[STATS] Win Rate:         %.1f%%", result.win_rate * 100)
        logger.info("[STATS] Total PnL:        $%+.2f", result.total_pnl)
        logger.info("[STATS] Max Drawdown:     %.1f%%", result.max_drawdown * 100)
        logger.info("[STATS] Profit Factor:    %.2f", result.profit_factor)
        logger.info("[STATS] Final Balance:    $%.2f", 10000.0 + result.total_pnl)
        logger.info("-" * 40)

        # Display Exit Statistics
        exit_stats = engine.get_exit_statistics()
        if exit_stats:
            logger.info("[STATS] EXIT BREAKDOWN:")
            for exit_type, stats in exit_stats.items():
                logger.info(f"  - {exit_type:18s}: {stats['count']:3d} exits | PnL: ${stats['total_pnl']:8.2f}")
        
        # ========== AI OBSERVATION ==========
        if config.cerebras and config.cerebras.api_key:
            logger.info("[INIT] Generating AI Strategic Analysis...")
            summarizer = AISummarizer(api_key=config.cerebras.api_key, model=config.cerebras.model)
            ai_summary = await summarizer.summarize_activities({
                "total_trades": result.total_trades,
                "win_rate": result.win_rate,
                "total_pnl": result.total_pnl,
                "max_drawdown": result.max_drawdown,
                "profit_factor": result.profit_factor
            })
            logger.info("[OK] AI ANALYSIS: %s", ai_summary)
        else:
            logger.info("[SKIP] AI analysis skipped (Cerebras API key not configured)")
        
        print("\n" + "=" * 60 + "\n")

    finally:
        await broker.disconnect()

if __name__ == "__main__":
    asyncio.run(run_backtest())

"""
Enhanced Backtest Runner with Exit Conditions
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict

from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.backtesting.enhanced_backtest_engine import (
    EnhancedBacktestEngine
)
from src.backtesting.backtest_engine import BacktestConfig
from src.backtesting.exit_condition_generator import (
    ExitConditionGenerator
)
from src.models import MarketData
from src.logging_config import setup_logging
from src.analysis.ai_summarizer import AISummarizer

async def run_backtest_with_exits(
    strategy_type: str = "default"
):
    """
    Run backtest with configurable exit conditions.

    Args:
        strategy_type: "default", "aggressive", "conservative",
                       or "scalping"
    """
    # 1. Setup Logging
    setup_logging(log_level="INFO")
    logger = logging.getLogger(__name__)

    print("\n" + "=" * 60)
    print("         ENHANCED BACKTEST WITH EXIT CONDITIONS")
    print("=" * 60)

    # ========== SYSTEM SECTION ==========
    print("\n[SYSTEM]")
    logger.info("Initializing enhanced backtest environment...")

    # 2. Configuration
    config_manager = ConfigManager('mt5')
    config = config_manager.get_config()
    symbols = ["EUR/USD", "GBP/USD"]

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
            data = await broker.get_historical_data(
                symbol, timeframe=16385, count=600)
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
                    symbol_signals[direction].append(
                        signal.confidence * 100)

            signal_stats[symbol] = symbol_signals

        # Print signal summary by symbol
        for symbol, stats in signal_stats.items():
            long_count = len(stats["LONG"])
            short_count = len(stats["SHORT"])
            long_avg = (
                sum(stats["LONG"]) / long_count
                if long_count else 0)
            short_avg = (
                sum(stats["SHORT"]) / short_count
                if short_count else 0)

            logger.info(
                f"  {symbol}: {long_count} LONG "
                f"(avg {long_avg:.0f}%) | {short_count} SHORT "
                f"(avg {short_avg:.0f}%)")

        logger.info(f"  Total: {len(all_signals)} signals generated")

        # ========== EXIT CONDITIONS SECTION ==========
        print("\n[EXIT CONDITIONS]")
        exit_generator = ExitConditionGenerator()

        # Build strategy based on type
        if strategy_type == "aggressive":
            exit_generator.create_aggressive_strategy()
            logger.info("Using AGGRESSIVE exit strategy")
        elif strategy_type == "conservative":
            exit_generator.create_conservative_strategy()
            logger.info("Using CONSERVATIVE exit strategy")
        elif strategy_type == "scalping":
            exit_generator.create_scalping_strategy()
            logger.info("Using SCALPING exit strategy")
        else:
            exit_generator.create_default_strategy()
            logger.info("Using DEFAULT exit strategy")

        logger.info(exit_generator.get_summary())

        # ========== SIMULATION SECTION ==========
        print("\n[SIMULATION]")
        backtest_config = BacktestConfig(
            initial_balance=10000.0,
            leverage=10.0,
            slippage_pips=1.0,
            max_positions=3
        )

        engine = EnhancedBacktestEngine(
            backtest_config,
            exit_generator)

        logger.info("Running enhanced backtest simulation...")
        result = engine.run_backtest(all_market_data, all_signals)

        # ========== RESULTS SECTION ==========
        print("\n" + "=" * 60)
        print("                      RESULTS")
        print("=" * 60)

        # Color coding
        pnl_color = "\033[92m" if result.total_pnl >= 0 else "\033[91m"
        reset = "\033[0m"

        print(f"\n  Trades Executed:  {result.total_trades}")
        print(f"  Winning Trades:   {result.winning_trades}")
        print(f"  Losing Trades:    {result.losing_trades}")
        print(f"  Win Rate:         {result.win_rate * 100:.1f}%")
        print(f"  Total PnL:        "
              f"{pnl_color}{result.total_pnl:+.2f}{reset}")
        print(f"  Avg Win:          "
              f"{result.avg_win:+.2f}" if result.avg_win else "")
        print(f"  Avg Loss:         "
              f"{result.avg_loss:+.2f}" if result.avg_loss else "")
        print(f"  Max Drawdown:     {result.max_drawdown * 100:.1f}%")
        print(f"  Profit Factor:    {result.profit_factor:.2f}")
        final_balance = 10000.0 + result.total_pnl
        print(f"  Final Balance:    "
              f"{pnl_color}${final_balance:.2f}{reset}")

        # ========== EXIT STATISTICS SECTION ==========
        print("\n[EXIT STATISTICS]")
        exit_stats = engine.get_exit_statistics()
        logger.info(f"Total exits: {exit_stats['total_exits']}")

        for exit_type, count in (
            exit_stats['exit_counts'].items()):
            pnl = exit_stats['exit_pnl'].get(exit_type, 0.0)
            logger.info(
                f"  {exit_type}: {count} exits | "
                f"PnL: {pnl:+.2f}")

        # ========== AI OBSERVATION ==========
        print("\n[AI OBSERVATION]")
        try:
            summarizer = AISummarizer(
                api_key=config.cerebras.api_key,
                model=config.cerebras.model)
            ai_summary = await summarizer.summarize_activities({
                "total_trades": result.total_trades,
                "win_rate": result.win_rate,
                "total_pnl": result.total_pnl,
                "max_drawdown": result.max_drawdown,
                "profit_factor": result.profit_factor,
                "strategy": strategy_type
            })
            print(f"  {ai_summary}")
        except Exception as e:
            logger.warning(f"AI summarization failed: {e}")

        print("\n" + "=" * 60 + "\n")

    finally:
        await broker.disconnect()

async def run_backtest_comparison():
    """
    Run backtest with all exit strategies and compare results.
    """
    setup_logging(log_level="INFO")
    logger = logging.getLogger(__name__)

    strategies = ["default", "aggressive", "conservative", "scalping"]
    results = {}

    print("\n" + "=" * 60)
    print("    BACKTEST STRATEGY COMPARISON")
    print("=" * 60)

    for strategy in strategies:
        print(f"\n--- Testing {strategy.upper()} strategy ---")
        try:
            await run_backtest_with_exits(strategy)
        except Exception as e:
            logger.error(f"Error in {strategy} strategy: {e}")
            results[strategy] = None

    print("\n" + "=" * 60)
    print("    COMPARISON COMPLETE")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        # Run all strategies
        asyncio.run(run_backtest_comparison())
    else:
        # Run single strategy (default or specified)
        strategy = sys.argv[1] if len(sys.argv) > 1 else "default"
        asyncio.run(run_backtest_with_exits(strategy))

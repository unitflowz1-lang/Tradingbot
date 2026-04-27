"""
Production-Ready Algorithmic Trading Bot
Main Entry Point - Modular, Scalable, Enterprise-Grade
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from utils.logger import get_logger
from utils.config import ConfigManager, TradingConfig
from core.engine import TradingEngine
from core.execution import MockBroker  # Replace with MT5Broker for live trading
from core.data_handler import MT5DataHandler  # Or replace with appropriate data handler
from core.strategy_manager import Strategy
from strategies.sma import SMAStrategy
from strategies.mean_reversion import MeanReversionStrategy
from strategies.breakout import BreakoutStrategy
from strategies.ml_strategy import MLStrategy
from ml.feature_engineering import FeatureEngineer
from ml.model_trainer import ModelTrainer
from ml.predictor import MLPredictor
from backtesting.backtester import Backtester, BacktestConfig
from backtesting.walk_forward import WalkForwardAnalyzer
from backtesting.monte_carlo import MonteCarloSimulator


logger = get_logger(__name__)


class AlgoTradingBot:
    """
    Main trading bot orchestrator.
    Integrates all modules for production trading.
    """
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize AlgoTradingBot.
        
        Args:
            config_path: Path to configuration file
        """
        logger.info("[BOT] Initializing Algorithmic Trading Bot v2.0")
        
        # Load configuration
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get_config()
        
        # Validate configuration
        if not self.config_manager.validate():
            raise ValueError("Invalid configuration")
        
        # Initialize components
        self.broker = None
        self.data_handler = None
        self.engine = None
        self.strategies = {}
        self.ml_predictor = None
    
    async def initialize(self, skip_broker: bool = False):
        """
        Initialize all components.

        Args:
            skip_broker: If True, use MockBroker for testing
        """
        logger.info("[BOT] Initializing components...")

        try:
            # Initialize broker
            if skip_broker:
                self.broker = MockBroker()
                logger.info("[BOT] Using MockBroker")
            else:
                # Use real MT5 broker
                try:
                    import MetaTrader5 as mt5
                    from src.data.mt5_broker import MT5BrokerInterface

                    self.broker = MT5BrokerInterface(
                        login=self.config.broker.login,
                        password=self.config.broker.password,
                        server=self.config.broker.server
                    )
                    logger.info("[BOT] Using MT5BrokerInterface")
                except Exception as e:
                    logger.warning(f"[BOT] MT5 Broker failed ({e}), falling back to MockBroker")
                    self.broker = MockBroker()
                    logger.info("[BOT] Using MockBroker (fallback)")

            # Initialize data handler
            await self.broker.connect()
            self.data_handler = MT5DataHandler(self.broker) if self.broker else None

            # Initialize trading engine
            self.engine = TradingEngine(self.config, self.broker, self.data_handler)

            if not await self.engine.initialize():
                raise RuntimeError("Failed to initialize trading engine")

            # Register strategies
            self._register_strategies()

            # Initialize ML if enabled
            if self.config.ml.enabled:
                self._initialize_ml()

            logger.info("[BOT] Initialization complete")
            return True

        except Exception as e:
            logger.error(f"[BOT] Initialization error: {e}")
            return False
    
    def _register_strategies(self):
        """Register all enabled strategies."""
        strategies_to_register = [
            (SMAStrategy, self.config.strategies[0] if len(self.config.strategies) > 0 else None),
            (MeanReversionStrategy, self.config.strategies[1] if len(self.config.strategies) > 1 else None),
            (BreakoutStrategy, self.config.strategies[2] if len(self.config.strategies) > 2 else None),
        ]
        
        for strategy_class, strategy_config in strategies_to_register:
            if strategy_config and strategy_config.enabled:
                strategy = strategy_class(strategy_config.__dict__)
                weight = strategy_config.weight
                self.engine.add_strategy(strategy, weight)
                self.strategies[strategy.name] = strategy
                logger.info(f"[BOT] Registered strategy: {strategy.name} (weight: {weight})")
    
    def _initialize_ml(self):
        """Initialize ML pipeline."""
        logger.info("[BOT] Initializing ML pipeline...")
        
        try:
            # Create ML predictor
            self.ml_predictor = MLPredictor(
                model_type=self.config.ml.model_type
            )
            
            # Register ML strategy
            ml_strategy = MLStrategy(self.config.ml.__dict__)
            ml_strategy.set_feature_engineer(self.ml_predictor.feature_engineer)
            
            # Try to load pre-trained model
            if Path("models").exists():
                self.ml_predictor.model_trainer.load_model()
                ml_strategy.set_model(self.ml_predictor.model_trainer.model)
            
            self.engine.add_strategy(ml_strategy, 0.2)
            logger.info("[BOT] ML pipeline initialized")
        
        except Exception as e:
            logger.warning(f"[BOT] ML initialization failed: {e}")
    
    async def run_backtest(self, strategy_name: str = "sma_crossover") -> dict:
        """
        Run backtest on selected strategy.
        
        Args:
            strategy_name: Name of strategy to backtest
        
        Returns:
            Dictionary with backtest results
        """
        logger.info(f"[BOT] Starting backtest for {strategy_name}...")
        
        try:
            # Load historical data
            if not self.data_handler:
                logger.error("Data handler not initialized")
                return {}
            
            # Create backtest config
            backtest_config = BacktestConfig(
                start_date=self.config.backtest.start_date,
                end_date=self.config.backtest.end_date,
                initial_capital=self.config.backtest.initial_capital,
                spread_bps=self.config.backtest.spread_bps,
                slippage_bps=self.config.backtest.slippage_bps,
                commission_pct=self.config.backtest.commission_pct,
                latency_ms=self.config.backtest.latency_ms
            )
            
            # Get strategy
            if strategy_name not in self.strategies:
                logger.error(f"Strategy not found: {strategy_name}")
                return {}
            
            strategy = self.strategies[strategy_name]
            
            # TODO: Load actual historical data
            # For now, using simulated data
            dummy_data = self._create_dummy_data()
            
            # Run backtest
            backtester = Backtester(strategy, dummy_data, backtest_config)
            trades, metrics = backtester.run()
            
            logger.info(f"[BOT] Backtest complete. Return: {metrics.total_return:.2%}")
            
            return {
                'trades': trades,
                'metrics': metrics,
                'num_trades': len(trades)
            }
        
        except Exception as e:
            logger.error(f"[BOT] Backtest error: {e}")
            return {}
    
    async def run_walk_forward(self, strategy_name: str = "sma_crossover") -> dict:
        """
        Run walk-forward analysis to detect overfitting.
        
        Args:
            strategy_name: Name of strategy to test
        
        Returns:
            Walk-forward analysis results
        """
        logger.info("[BOT] Running walk-forward analysis...")
        
        try:
            if strategy_name not in self.strategies:
                logger.error(f"Strategy not found: {strategy_name}")
                return {}
            
            strategy = self.strategies[strategy_name]
            
            # Create backtest config
            backtest_config = BacktestConfig(
                start_date=self.config.backtest.start_date,
                end_date=self.config.backtest.end_date,
                initial_capital=self.config.backtest.initial_capital
            )
            
            # Load historical data
            dummy_data = self._create_dummy_data()
            
            # Run walk-forward
            wf_analyzer = WalkForwardAnalyzer(strategy, dummy_data, backtest_config)
            results = wf_analyzer.run_analysis(
                train_period_days=252,
                test_period_days=63,
                step_days=63
            )
            
            logger.info("[BOT] Walk-forward analysis complete")
            print(wf_analyzer.get_overfitting_report())
            
            return results
        
        except Exception as e:
            logger.error(f"[BOT] Walk-forward error: {e}")
            return {}
    
    async def run_live_trading(self):
        """Start live trading."""
        logger.info("[BOT] Starting live trading...")
        
        if not self.engine:
            logger.error("Engine not initialized")
            return
        
        try:
            await self.engine.run()
        
        except KeyboardInterrupt:
            logger.info("[BOT] Received shutdown signal")
        
        except Exception as e:
            logger.error(f"[BOT] Trading error: {e}")
        
        finally:
            await self.shutdown()
    
    async def shutdown(self):
        """Shutdown bot and cleanup."""
        logger.info("[BOT] Shutting down...")
        
        if self.engine:
            await self.engine.shutdown()
        
        if self.broker:
            await self.broker.disconnect()
        
        logger.info("[BOT] Shutdown complete")
    
    def _create_dummy_data(self):
        """Create dummy OHLCV data for testing."""
        import pandas as pd
        import numpy as np
        
        dates = pd.date_range(
            start=self.config.backtest.start_date,
            end=self.config.backtest.end_date,
            freq='H'
        )
        
        prices = 100 + np.cumsum(np.random.randn(len(dates)) * 0.5)
        
        return pd.DataFrame({
            'timestamp': dates,
            'open': prices,
            'high': prices + abs(np.random.randn(len(dates)) * 0.2),
            'low': prices - abs(np.random.randn(len(dates)) * 0.2),
            'close': prices + np.random.randn(len(dates)) * 0.1,
            'volume': np.random.randint(1000, 10000, len(dates))
        })
    
    def print_summary(self):
        """Print configuration summary."""
        print("\n" + "="*70)
        print("ALGO TRADING BOT v2.0 - SYSTEM SUMMARY")
        print("="*70)
        
        print(f"\nApplication: {self.config.app_name}")
        print(f"Version: {self.config.version}")
        
        print("\n--- RISK MANAGEMENT ---")
        print(f"Mode: {self.config.risk.mode}")
        print(f"Max Position Size: {self.config.risk.max_position_size:.1%}")
        print(f"Max Daily Loss: {self.config.risk.max_daily_loss:.1%}")
        print(f"Max Drawdown: {self.config.risk.max_drawdown:.1%}")
        print(f"Max Open Trades: {self.config.risk.max_open_trades}")
        
        print("\n--- STRATEGIES ENABLED ---")
        for strategy in self.config.strategies:
            if strategy.enabled:
                print(f"✓ {strategy.name:<20} (weight: {strategy.weight})")
        
        print("\n--- ML CONFIGURATION ---")
        if self.config.ml.enabled:
            print(f"✓ ML Enabled")
            print(f"  Model: {self.config.ml.model_type}")
            print(f"  Confidence Threshold: {self.config.ml.confidence_threshold}")
        else:
            print(f"✗ ML Disabled")
        
        print("\n--- BACKTESTING ---")
        if self.config.backtest.enabled:
            print(f"✓ Backtesting Enabled")
            print(f"  Period: {self.config.backtest.start_date} to {self.config.backtest.end_date}")
            print(f"  Initial Capital: ${self.config.backtest.initial_capital:,.0f}")
            if self.config.backtest.walk_forward_enabled:
                print(f"  ✓ Walk-Forward Validation Enabled")
            if self.config.backtest.monte_carlo_enabled:
                print(f"  ✓ Monte Carlo Simulation Enabled")
        else:
            print(f"✗ Backtesting Disabled")
        
        print("\n--- DATA & BROKER ---")
        print(f"Broker: {self.config.broker.broker}")
        print(f"Trading Pairs: {', '.join(self.config.data.pairs)}")
        print(f"Granularity: {self.config.data.granularity}")
        
        print("\n" + "="*70 + "\n")


async def main():
    """Main entry point."""
    bot = AlgoTradingBot("config.yaml")
    bot.print_summary()

    try:
        # Initialize with MT5 broker (real trading)
        if await bot.initialize(skip_broker=False):
            
            # Run backtests
            logger.info("Running backtests...")
            
            for strategy_name in bot.strategies.keys():
                logger.info(f"\nBacktesting {strategy_name}...")
                backtest_result = await bot.run_backtest(strategy_name)
                
                if backtest_result:
                    metrics = backtest_result['metrics']
                    logger.info(f"Return: {metrics.total_return:.2%}, "
                              f"Sharpe: {metrics.sharpe_ratio:.2f}, "
                              f"Win Rate: {metrics.win_rate:.1%}")
            
            # Run walk-forward if enabled
            if bot.config.backtest.walk_forward_enabled:
                logger.info("\nRunning walk-forward analysis...")
                await bot.run_walk_forward("sma_crossover")
        
        else:
            logger.error("Failed to initialize bot")
    
    except Exception as e:
        logger.error(f"Error: {e}")
    
    finally:
        await bot.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

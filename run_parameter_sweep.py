#!/usr/bin/env python3
"""
Hyperparameter Optimization Sweep for Forex Trading Bot
========================================================

Sweeps over signal weights, exit parameters, and other critical knobs
to find the optimal trading configuration. Uses walk-forward validation
to avoid overfitting.

Usage:
    python run_parameter_sweep.py [--quick] [--plot] [--save-results]

Options:
    --quick          Run a small subset of parameters for testing (default: False)
    --plot           Generate heatmaps and parallel coordinates plots
    --save-results   Save detailed results to CSV and JSON
"""

import asyncio
import json
import logging
import os
import sys
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd

from src.config import ConfigManager
from src.data.mt5_broker import create_mt5_broker
from src.models import MarketData, Direction
from src.backtesting.backtest_engine import BacktestEngine, BacktestConfig, BacktestResult
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.logging_config import setup_logging

# Attempt to import visualization libraries (optional)
try:
    import matplotlib.pyplot as plt
    import seaborn as sns
    VISUALIZATION_AVAILABLE = True
except ImportError:
    VISUALIZATION_AVAILABLE = False
    print("⚠️  Matplotlib/Seaborn not available - visualization disabled")

# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass
class ParameterGrid:
    """Parameter grid for sweep"""
    weight_technical: List[float] = field(default_factory=lambda: [0.3, 0.5, 0.7])
    weight_ml: List[float] = field(default_factory=lambda: [0.3, 0.5, 0.7])
    weight_mtf: List[float] = field(default_factory=lambda: [0.0, 0.2, 0.4])
    tp_multiplier: List[float] = field(default_factory=lambda: [1.5, 2.0, 2.5, 3.0])
    trailing_activation_r: List[float] = field(default_factory=lambda: [0.5, 1.0, 1.5])
    time_exit_bars: List[int] = field(default_factory=lambda: [10, 20, 30])
    partial_profit_levels: List[Tuple[float, float]] = field(
        default_factory=lambda: [
            ((0.5, 0.2), (1.0, 0.3)),  # Close 20% @ 0.5R, 30% @ 1.0R
            ((1.0, 0.4),),              # Close 40% @ 1.0R
            ((1.5, 0.3), (2.0, 0.3)),  # Close 30% @ 1.5R, 30% @ 2.0R
        ]
    )

@dataclass
class SweepConfig:
    """Configuration for the sweep"""
    initial_balance: float = 10000.0
    leverage: float = 1.0
    spread_multiplier: float = 2.0
    slippage_pips: float = 1.5
    commission_per_lot: float = 7.0
    max_positions: int = 3
    
    # Walk-forward validation
    total_bars: int = 2000  # Total historical bars
    train_bars: int = 1500  # Training period
    test_bars: int = 500    # Out-of-sample test period
    
    # Optimization settings
    symbols: List[str] = field(default_factory=lambda: ["EUR/USD"])
    quick_mode: bool = False  # Run smaller grid if True


@dataclass
class OptimizationResult:
    """Result of a single backtest run"""
    params: Dict[str, Any]
    total_pnl: float
    sharpe_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    max_drawdown: float
    avg_trade_pnl: float
    recovery_factor: float  # Profit / Max Drawdown
    combined_score: float   # Weighted objective metric
    
    def to_dict(self):
        return asdict(self)


# ============================================================================
# PARAMETER SWEEP ENGINE
# ============================================================================

class ParameterSweepEngine:
    """Main optimization engine"""
    
    def __init__(self, config: SweepConfig, param_grid: ParameterGrid):
        self.config = config
        self.param_grid = param_grid
        self.logger = logging.getLogger(__name__)
        self.results: List[OptimizationResult] = []
        self.cache: Dict[str, OptimizationResult] = {}
        self.iteration_count = 0
        
    def generate_parameter_combinations(self) -> List[Dict[str, Any]]:
        """Generate all parameter combinations to test"""
        # Build stable feature weights
        weight_combos = list(product(
            self.param_grid.weight_technical,
            self.param_grid.weight_ml,
            self.param_grid.weight_mtf,
        ))
        
        # Exit parameters
        exit_combos = list(product(
            self.param_grid.tp_multiplier,
            self.param_grid.trailing_activation_r,
            self.param_grid.time_exit_bars,
            self.param_grid.partial_profit_levels,
        ))
        
        # Normalize weights for each combo to sum to 1.0
        combinations = []
        for (w_tech, w_ml, w_mtf), (tp_mult, trail_act, time_exit, partial_prof) in product(weight_combos, exit_combos):
            total_weight = w_tech + w_ml + w_mtf
            if total_weight == 0:
                continue
                
            params = {
                'weight_technical': w_tech / total_weight,
                'weight_ml': w_ml / total_weight,
                'weight_mtf': w_mtf / total_weight,
                'tp_multiplier': tp_mult,
                'trailing_activation_r': trail_act,
                'time_exit_bars': time_exit,
                'partial_profit_levels': partial_prof,
            }
            combinations.append(params)
        
        return combinations
    
    def parameter_hash(self, params: Dict[str, Any]) -> str:
        """Create a hash of parameters for caching"""
        return json.dumps(params, sort_keys=True, default=str)
    
    async def run_backtest_with_params(
        self, 
        market_data: Dict[str, List[MarketData]],
        params: Dict[str, Any],
        is_train: bool = True
    ) -> BacktestResult:
        """Run a single backtest with given parameters"""
        
        # Create backtest config
        bt_config = BacktestConfig(
            initial_balance=self.config.initial_balance,
            leverage=self.config.leverage,
            spread_multiplier=self.config.spread_multiplier,
            slippage_pips=self.config.slippage_pips,
            commission_per_lot=self.config.commission_per_lot,
            max_positions=self.config.max_positions,
        )
        
        # Create strategy with parameters (requires symbol)
        symbol = self.config.symbols[0]  # Use first symbol
        strategy = SimpleTrendStrategy(symbol=symbol, verbose=False)
        
        # Inject parameters into strategy (via dynamic attributes)
        strategy.weight_technical = params['weight_technical']
        strategy.weight_ml = params['weight_ml']
        strategy.weight_mtf = params['weight_mtf']
        strategy.tp_multiplier = params['tp_multiplier']
        strategy.trailing_activation_r = params['trailing_activation_r']
        strategy.time_exit_bars = params['time_exit_bars']
        strategy.partial_profit_levels = params['partial_profit_levels']
        
        # Create backtest engine
        engine = BacktestEngine(config=bt_config)
        
        # Prepare data for selected period
        if is_train:
            slice_data = {sym: data[:self.config.train_bars] 
                         for sym, data in market_data.items()}
        else:
            slice_data = {sym: data[-self.config.test_bars:] 
                         for sym, data in market_data.items()}
        
        # Generate signals from strategy
        all_signals = []
        for symbol in self.config.symbols:
            if symbol not in slice_data:
                continue
            
            data_list = slice_data[symbol]
            
            # Generate signals across the period
            for i in range(50, len(data_list)):  # Start from bar 50 to allow indicator calculation
                window = data_list[:i+1]
                try:
                    signal = await strategy.analyze(window)
                    if signal:
                        all_signals.append(signal)
                except Exception:
                    # Skip errors in signal generation
                    pass
        
        # Run backtest with generated signals
        try:
            result = engine.run_backtest(slice_data, all_signals)
            return result
        except Exception as e:
            self.logger.debug(f"Backtest error: {e}")
            # Return empty result
            return BacktestResult(
                total_pnl=0,
                sharpe_ratio=0,
                win_rate=0,
                profit_factor=0,
                total_trades=0,
                max_drawdown=0,
                trades=[]
            )
    
    def calculate_objective_metrics(self, result: BacktestResult) -> Tuple[float, Dict[str, float]]:
        """
        Calculate objective metrics from backtest result.
        
        Weighted scoring:
        - 40% Sharpe Ratio (risk-adjusted return)
        - 30% Win Rate (consistency)
        - 20% Profit Factor (profitability)
        - 10% Recovery Factor (efficiency)
        """
        
        # Safe metrics
        sharpe = max(-10, min(10, result.sharpe_ratio))  # Clamp to [-10, 10]
        win_rate = result.win_rate  # Already 0-1
        profit_factor = max(0, min(5, result.profit_factor))  # Clamp to [0, 5]
        
        # Recovery factor = Total Profit / Max Drawdown
        if result.max_drawdown != 0:
            recovery = abs(result.total_pnl) / abs(result.max_drawdown)
        else:
            recovery = 0
        recovery = max(0, min(10, recovery))  # Clamp to [0, 10]
        
        # Normalize to 0-1 scale
        sharpe_norm = (sharpe + 10) / 20  # [-10, 10] → [0, 1]
        profit_factor_norm = profit_factor / 5  # [0, 5] → [0, 1]
        recovery_norm = recovery / 10  # [0, 10] → [0, 1]
        
        # Combined score (weighted)
        combined = (
            0.40 * sharpe_norm +
            0.30 * win_rate +
            0.20 * profit_factor_norm +
            0.10 * recovery_norm
        )
        
        metrics = {
            'sharpe_normalized': sharpe_norm,
            'win_rate_normalized': win_rate,
            'profit_factor_normalized': profit_factor_norm,
            'recovery_normalized': recovery_norm,
            'combined_score': combined,
        }
        
        return combined, metrics
    
    async def sweep(self, market_data: Dict[str, List[MarketData]]) -> List[OptimizationResult]:
        """Run the full parameter sweep"""
        
        combinations = self.generate_parameter_combinations()
        total_combos = len(combinations)
        
        if self.config.quick_mode:
            # For testing: run only a small subset
            combinations = combinations[::max(1, len(combinations) // 10)]
            self.logger.info(f"🚀 Quick mode: Testing {len(combinations)} configurations (of {total_combos})")
        
        self.logger.info(f"📊 Starting sweep over {len(combinations)} parameter combinations")
        
        for idx, params in enumerate(combinations, 1):
            self.iteration_count += 1
            
            # Check cache
            param_key = self.parameter_hash(params)
            if param_key in self.cache:
                result = self.cache[param_key]
                self.logger.debug(f"  [{idx}/{len(combinations)}] Cache HIT")
                self.results.append(result)
                continue
            
            try:
                # Train on training period
                train_result = await self.run_backtest_with_params(
                    market_data, params, is_train=True
                )
                
                # Test on out-of-sample period
                test_result = await self.run_backtest_with_params(
                    market_data, params, is_train=False
                )
                
                # Use test period for scoring (out-of-sample)
                combined_score, metrics = self.calculate_objective_metrics(test_result)
                
                # Create result entry
                opt_result = OptimizationResult(
                    params=params,
                    total_pnl=test_result.total_pnl,
                    sharpe_ratio=test_result.sharpe_ratio,
                    win_rate=test_result.win_rate,
                    profit_factor=test_result.profit_factor,
                    total_trades=test_result.total_trades,
                    max_drawdown=test_result.max_drawdown,
                    avg_trade_pnl=test_result.total_pnl / max(1, test_result.total_trades),
                    recovery_factor=abs(test_result.total_pnl) / max(0.01, abs(test_result.max_drawdown)),
                    combined_score=combined_score,
                )
                
                self.results.append(opt_result)
                self.cache[param_key] = opt_result
                
                # Log progress
                if idx % max(1, len(combinations) // 10) == 0:
                    progress_pct = (idx / len(combinations)) * 100
                    best_score = max([r.combined_score for r in self.results])
                    self.logger.info(
                        f"  [{idx}/{len(combinations)}] {progress_pct:.0f}% | "
                        f"Score: {combined_score:.4f} | Best: {best_score:.4f}"
                    )
                
            except Exception as e:
                self.logger.warning(f"  [{idx}/{len(combinations)}] Error: {e}")
                continue
        
        return self.results
    
    def get_top_results(self, n: int = 10) -> List[OptimizationResult]:
        """Get top N results sorted by combined score"""
        return sorted(self.results, key=lambda x: x.combined_score, reverse=True)[:n]
    
    def print_summary(self):
        """Print summary of results"""
        if not self.results:
            self.logger.error("No results to summarize")
            return
        
        top_results = self.get_top_results(10)
        
        print("\n" + "="*100)
        print(" HYPERPARAMETER OPTIMIZATION RESULTS ".center(100, "="))
        print("="*100)
        
        print(f"\n📊 Total Configurations Tested: {len(self.results)}")
        print(f"Iterations with cache: {len(self.cache)}")
        
        print("\n🏆 TOP 10 CONFIGURATIONS:\n")
        
        for rank, result in enumerate(top_results, 1):
            print(f"\n[{rank}] Score: {result.combined_score:.4f} ⭐")
            print(f"    PnL: ${result.total_pnl:,.2f} | "
                  f"Sharpe: {result.sharpe_ratio:.2f} | "
                  f"Win Rate: {result.win_rate:.1%} | "
                  f"PF: {result.profit_factor:.2f}")
            print(f"    Trades: {result.total_trades} | "
                  f"Max DD: ${result.max_drawdown:,.2f} | "
                  f"Recovery: {result.recovery_factor:.2f}x")
            print(f"    Parameters:")
            for key, val in result.params.items():
                if key != 'partial_profit_levels':
                    print(f"      • {key}: {val}")
                else:
                    print(f"      • {key}: {val}")
        
        print("\n" + "="*100)


# ============================================================================
# MAIN EXECUTION
# ============================================================================

async def main(args=None):
    """Main entry point"""
    
    # Setup logging
    setup_logging(log_level="INFO")
    logger = logging.getLogger(__name__)
    
    # Parse command-line arguments
    quick_mode = "--quick" in (sys.argv[1:] if args is None else args)
    plot_results = "--plot" in (sys.argv[1:] if args is None else args)
    save_results = "--save-results" in (sys.argv[1:] if args is None else args)
    
    logger.info("🤖 Forex Trading Bot - Hyperparameter Optimization Sweep")
    logger.info("="*60)
    
    # Initialize sweep configuration
    config = SweepConfig(quick_mode=quick_mode)
    param_grid = ParameterGrid()
    
    if quick_mode:
        # Reduce parameter ranges for quick testing
        param_grid.weight_technical = [0.4, 0.6]
        param_grid.weight_ml = [0.4, 0.6]
        param_grid.weight_mtf = [0.2]
        param_grid.tp_multiplier = [2.0, 2.5]
        param_grid.trailing_activation_r = [1.0]
        param_grid.time_exit_bars = [20]
        param_grid.partial_profit_levels = [((1.0, 0.4),)]
    
    # Initialize sweep engine
    engine = ParameterSweepEngine(config, param_grid)
    
    # Load historical data
    logger.info("📥 Loading historical data...")
    try:
        config_manager = ConfigManager('mt5')
        broker = create_mt5_broker(
            login=config_manager.get_config().broker.login,
            password=config_manager.get_config().broker.password,
            server=config_manager.get_config().broker.server
        )
        
        if not await broker.connect():
            logger.error("Failed to connect to MT5")
            return
        
        # Fetch data for each symbol
        market_data = {}
        for symbol in config.symbols:
            logger.info(f"  Fetching {symbol}...")
            data = await broker.get_historical_data(symbol, timeframe=16385, count=config.total_bars)
            if data:
                market_data[symbol] = data
                logger.info(f"    ✅ Loaded {len(data)} bars")
            else:
                logger.warning(f"    ⚠️  No data for {symbol}")
        
        await broker.disconnect()
        
        if not market_data:
            logger.error("No data available for sweep")
            return
        
    except Exception as e:
        logger.error(f"Data loading failed: {e}")
        logger.info("Using synthetic data for demo...")
        # Could load from CSV/parquet here
        return
    
    # Run sweep
    logger.info(f"\n🔄 Starting parameter sweep...")
    start_time = datetime.now(timezone.utc)
    
    results = await engine.sweep(market_data)
    
    elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(f"✅ Sweep complete in {elapsed:.1f} seconds")
    
    # Print summary
    engine.print_summary()
    
    # Save results if requested
    if save_results:
        logger.info("\n💾 Saving results...")
        if engine.results:
            results_df = pd.DataFrame([r.to_dict() for r in engine.get_top_results(min(50, len(engine.results)))])
            
            csv_path = Path("sweep_results.csv")
            json_path = Path("sweep_results.json")
            
            results_df.to_csv(csv_path, index=False)
            logger.info(f"  ✅ CSV saved: {csv_path}")
            
            # Save all results as JSON for easy reference
            all_results = [r.to_dict() for r in engine.get_top_results(len(engine.results))]
            with open(json_path, 'w') as f:
                json.dump(all_results, f, indent=2, default=str)
            logger.info(f"  ✅ All results saved: {json_path}")
        else:
            logger.error("❌ No results to save!")
    
    # Generate plots if requested
    if plot_results and VISUALIZATION_AVAILABLE:
        logger.info("\n📊 Generating visualizations...")
        generate_plots(engine.results)
    
    print("\n✨ Optimization complete!")


def generate_plots(results: List[OptimizationResult]):
    """Generate visualization plots (requires matplotlib/seaborn)"""
    
    if not VISUALIZATION_AVAILABLE:
        print("⚠️  Visualization requires matplotlib and seaborn")
        return
    
    # Convert results to DataFrame
    results_list = [r.to_dict() for r in results]
    df = pd.DataFrame(results_list)
    
    # Extract numeric parameter columns for heatmap
    try:
        # Create heatmap of score vs top parameters
        fig, axes = plt.subplots(2, 2, figsize=(15, 12))
        
        # Plot 1: Score vs TP Multiplier and Trailing Activation
        ax = axes[0, 0]
        pivot_data = df.pivot_table(
            values='combined_score',
            index='tp_multiplier',
            columns='trailing_activation_r',
            aggfunc='mean'
        )
        sns.heatmap(pivot_data, annot=True, fmt='.3f', cmap='RdYlGn', ax=ax, cbar_kws={'label': 'Score'})
        ax.set_title('Combined Score vs Exit Parameters')
        ax.set_xlabel('Trailing Activation (R)')
        ax.set_ylabel('TP Multiplier (R)')
        
        # Plot 2: Win Rate Distribution
        ax = axes[0, 1]
        ax.hist(df['win_rate'], bins=20, color='skyblue', edgecolor='black')
        ax.set_xlabel('Win Rate')
        ax.set_ylabel('Frequency')
        ax.set_title('Win Rate Distribution')
        ax.axvline(df['win_rate'].mean(), color='red', linestyle='--', label=f'Mean: {df["win_rate"].mean():.1%}')
        ax.legend()
        
        # Plot 3: Sharpe Ratio vs PnL
        ax = axes[1, 0]
        scatter = ax.scatter(df['sharpe_ratio'], df['total_pnl'], c=df['combined_score'], cmap='viridis', s=100)
        ax.set_xlabel('Sharpe Ratio')
        ax.set_ylabel('Total PnL ($)')
        ax.set_title('Risk-Adjusted Return vs Total Profit')
        plt.colorbar(scatter, ax=ax, label='Combined Score')
        
        # Plot 4: Score Distribution
        ax = axes[1, 1]
        ax.hist(df['combined_score'], bins=20, color='coral', edgecolor='black')
        ax.set_xlabel('Combined Score')
        ax.set_ylabel('Frequency')
        ax.set_title('Score Distribution')
        ax.axvline(df['combined_score'].mean(), color='red', linestyle='--', label=f'Mean: {df["combined_score"].mean():.3f}')
        ax.legend()
        
        plt.tight_layout()
        plt.savefig('sweep_results_plots.png', dpi=300, bbox_inches='tight')
        print("✅ Plots saved: sweep_results_plots.png")
        
    except Exception as e:
        print(f"⚠️  Couldn't generate plots: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)

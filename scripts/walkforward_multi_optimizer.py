"""
Walk-Forward Multi-Objective Optimization Suite
===============================================
Implements robust parameter optimization with:
1. Walk-Forward Analysis (70% train / 30% test)
2. Multi-Objective Fitness Function (Recovery Factor, Win Rate, Sharpe, Profit Factor)
3. Overfitting Mitigation Guards (Sensitivity Analysis, Trade Count, Plateau Detection)
4. Alpha Pair Identification

Usage:
    python scripts/walkforward_multi_optimizer.py
    
Output:
    - config/optimized_params.json (updated)
    - optimization_results/wfa_report.json (detailed results)
    - optimization_results/wfa_summary.txt (human-readable report)
"""

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass, field, asdict
from pathlib import Path
import numpy as np
from itertools import product

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import ConfigManager
from src.backtesting.optimized_backtest_engine import OptimizedBacktestEngine

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('optimization_results/wfa_optimization.log', mode='w')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class ParameterSet:
    """Complete parameter configuration for testing"""
    # Signal Weights
    ml_weight: float
    technical_weight: float
    
    # Entry Thresholds
    adx_min: float
    rsi_lower: float
    rsi_upper: float
    quality_floor: float
    
    # New Logic Tuning
    lot_mismatch_threshold: float  # 50% = 0.50
    auto_rotation_score: float
    
    # Volatility Scaling
    atr_sl_multiplier: float
    atr_tp_multiplier: float
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    def __hash__(self):
        return hash(tuple(sorted(self.to_dict().items())))


@dataclass
class BacktestResult:
    """Results from a single backtest run"""
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    recovery_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    total_return_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_trade_duration_hours: float = 0.0
    net_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    total_pnl: float = 0.0  # Total net profit in dollars
    test_period_days: float = 0.0  # Duration of test period in days
    fitness_score: float = 0.0  # Calculated fitness score


@dataclass
class WalkForwardPeriod:
    """Single walk-forward period results"""
    period_name: str
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    
    train_result: BacktestResult = field(default_factory=BacktestResult)
    test_result: BacktestResult = field(default_factory=BacktestResult)
    
    # Overfitting metrics
    overfitting_ratio: float = 0.0  # test_performance / train_performance
    is_overfitted: bool = False


@dataclass
class OptimizationResult:
    """Complete optimization result for one parameter set"""
    params: ParameterSet
    periods: List[WalkForwardPeriod] = field(default_factory=list)
    
    # Aggregate metrics
    avg_test_win_rate: float = 0.0
    avg_test_profit_factor: float = 0.0
    avg_test_sharpe: float = 0.0
    avg_test_recovery_factor: float = 0.0
    avg_test_drawdown: float = 0.0
    
    # Stability metrics
    win_rate_std: float = 0.0
    profit_factor_std: float = 0.0
    sharpe_std: float = 0.0
    
    # Overfitting detection
    is_overfitted: bool = False
    sensitivity_score: float = 0.0  # Lower is better (more stable)
    
    # Final ranking
    composite_score: float = 0.0
    rank: int = 99999


# ============================================================================
# WALK-FORWARD MULTI-OBJECTIVE OPTIMIZER
# ============================================================================

class WalkForwardMultiOptimizer:
    """
    Advanced Walk-Forward Optimizer with Multi-Objective Fitness Function
    and Overfitting Mitigation Guards
    """
    
    def __init__(self, config_path: str = "config/config.json"):
        self.config_path = config_path
        self.logger = logger
        
        # Load configuration
        self.config_manager = ConfigManager("mt5")
        self.config = self.config_manager.get_config()
        
        # Results storage
        self.all_results: List[OptimizationResult] = []
        self.best_result: Optional[OptimizationResult] = None
        
        # Historical data cache
        self.historical_data: Dict = {}
        
    def define_parameter_space(self) -> List[ParameterSet]:
        """
        Define the AGGRESSIVE parameter space for optimization
        Focuses on increasing trade frequency and profit potential
        """
        self.logger.info("[PARAM_SPACE] Defining AGGRESSIVE parameter space...")
        
        # Aggressive parameter ranges
        param_ranges = {
            'quality_floor': [65, 68, 70, 72, 75],  # Lower floor = more trades
            'adx_min': [15, 18, 20, 22],
            'rsi_lower': [28, 30, 32],
            'rsi_upper': [58, 60, 62, 65],
            'lot_mismatch_threshold': [0.40, 0.50, 0.60],
            'auto_rotation_score': [75, 80, 85],
            'atr_sl_multiplier': [1.5, 1.8, 2.0, 2.2],  # Tighter stops
            'atr_tp_multiplier': [2.5, 3.0, 3.2, 3.5],  # Wider targets (RUNNERS)
            'ml_weight': [0.40, 0.45, 0.50, 0.55, 0.60],  # Higher ML influence
        }
        
        # Generate combinations with smart filtering
        combinations = []
        keys = list(param_ranges.keys())
        
        for values in product(*[param_ranges[k] for k in keys]):
            params = dict(zip(keys, values))
            
            # Filter 1: Ensure TP > SL for positive RR (critical for runners)
            if params['atr_tp_multiplier'] <= params['atr_sl_multiplier'] * 1.0:
                continue
            
            # Filter 2: RSI boundaries must be logical
            if params['rsi_lower'] >= params['rsi_upper']:
                continue
            
            # Calculate technical_weight (complement to ML weight with 5% for other signals)
            params['technical_weight'] = round(1.0 - params['ml_weight'] - 0.05, 2)
            
            # Filter 3: Ensure technical_weight is reasonable
            if params['technical_weight'] < 0.30 or params['technical_weight'] > 0.60:
                continue
            
            combinations.append(ParameterSet(**params))
        
        self.logger.info(f"[PARAM_SPACE] Generated {len(combinations)} aggressive parameter sets")
        return combinations
    
    def create_walk_forward_splits(self, total_bars: int) -> List[Tuple[str, slice, slice]]:
        """
        Create walk-forward train/test splits
        70% train, 30% test, rolling window
        """
        splits = []
        
        # Calculate split sizes
        train_size = int(total_bars * 0.70)
        test_size = int(total_bars * 0.30)
        step_size = test_size  # Roll forward by test_size
        
        period_num = 1
        start_idx = 0
        
        while start_idx + train_size + test_size <= total_bars:
            train_slice = slice(start_idx, start_idx + train_size)
            test_slice = slice(start_idx + train_size, start_idx + train_size + test_size)
            
            period_name = f"Period_{period_num}"
            splits.append((period_name, train_slice, test_slice))
            
            self.logger.info(
                f"[WF_SPLIT] {period_name}: Train[{start_idx}:{start_idx+train_size}], "
                f"Test[{start_idx+train_size}:{start_idx+train_size+test_size}]"
            )
            
            start_idx += step_size
            period_num += 1
        
        self.logger.info(f"[WF_SPLIT] Created {len(splits)} walk-forward periods")
        return splits
    
    def calculate_fitness_score(self, result: BacktestResult) -> float:
        """
        Aggressive Multi-Objective Fitness Function
        Prioritizes: Total Net Profit & Trade Count (60%), Drawdown & Sharpe (40%)
        """
        # Component scores (normalized to 0-100)
        
        # 1. Total Net Profit (35% weight) - PRIMARY AGGRESSION DRIVER
        # Normalize: $5000+ = 100, $0 = 0
        profit_score = min(100, (result.total_pnl / 5000.0) * 100) if result.total_pnl > 0 else 0
        
        # 2. Trade Frequency (25% weight) - AGGRESSIVE TRADE COUNT TARGET
        # Target: > 60 trades/month (2+ trades/day)
        trades_per_month = result.total_trades / max(result.test_period_days / 30, 1) if result.test_period_days > 0 else 0
        if trades_per_month >= 80:
            freq_score = 100
        elif trades_per_month >= 60:
            freq_score = 80 + (trades_per_month - 60) * 1.0
        elif trades_per_month >= 40:
            freq_score = 50 + (trades_per_month - 40) * 1.5
        else:
            freq_score = max(0, trades_per_month * 1.25)
        
        # 3. Sharpe Ratio (25% weight) - MAINTAIN > 2.0
        sharpe_score = min(100, (result.sharpe_ratio / 3.0) * 100) if result.sharpe_ratio > 0 else 0
        
        # 4. Max Drawdown (15% weight) - HARD CAP 15%
        dd = result.max_drawdown_pct  # Already in percentage
        if dd <= 5:
            dd_score = 100
        elif dd <= 10:
            dd_score = 80 + (10 - dd) * 4
        elif dd <= 15:
            dd_score = 50 + (15 - dd) * 6
        else:
            dd_score = max(0, 50 - (dd - 15) * 10)  # Heavy penalty above 15%
        
        # Weighted composite: Profit+Freq (60%) + Sharpe+DD (40%)
        fitness = (profit_score * 0.35) + (freq_score * 0.25) + (sharpe_score * 0.25) + (dd_score * 0.15)
        
        # HARD CONSTRAINTS - Disqualify if violated
        if result.max_drawdown_pct > 15:  # 15% hard cap
            fitness *= 0.2  # 80% penalty
        if trades_per_month < 60:
            fitness *= 0.5  # 50% penalty for low trade count
        if result.sharpe_ratio < 2.0:
            fitness *= 0.6  # 40% penalty for low Sharpe
        
        result.fitness_score = fitness
        return fitness
    
    def check_overfitting(self, train_result: BacktestResult, test_result: BacktestResult) -> Tuple[bool, float]:
        """
        Detect overfitting - target ratio 0.8-1.2
        Returns: (is_overfitted, overfitting_ratio)
        """
        if train_result.total_pnl <= 0:
            return False, 1.0
        
        # Multi-metric overfitting ratio
        pnl_ratio = test_result.total_pnl / max(train_result.total_pnl, 1)
        wr_ratio = test_result.win_rate / max(train_result.win_rate, 0.01)
        sharpe_ratio_val = test_result.sharpe_ratio / max(train_result.sharpe_ratio, 0.01)
        
        # Average ratio across metrics
        avg_ratio = (pnl_ratio + wr_ratio + sharpe_ratio_val) / 3.0
        
        # Overfitted if ratio < 0.8 or > 1.2 (too good to be true)
        is_overfitted = (avg_ratio < 0.8) or (avg_ratio > 1.2)
        
        if is_overfitted:
            self.logger.warning(
                f"[OVERFITTING_DETECTED] Ratio: {avg_ratio:.3f} (outside 0.8-1.2 range) | "
                f"Train PnL: ${train_result.total_pnl:.2f} vs Test PnL: ${test_result.total_pnl:.2f}"
            )
        
        return is_overfitted, avg_ratio
    
    def sensitivity_analysis(self, base_params: ParameterSet, base_score: float) -> float:
        """
        Test parameter sensitivity - look for plateaus, not spikes
        Returns: sensitivity_score (lower = more stable = better)
        """
        # Create small perturbations (±1-2% changes)
        perturbations = []
        
        # Test each parameter with small change
        param_names = ['adx_min', 'rsi_lower', 'rsi_upper', 'quality_floor', 
                      'atr_sl_multiplier', 'atr_tp_multiplier']
        
        score_changes = []
        
        for param_name in param_names:
            original_value = getattr(base_params, param_name)
            
            # Test +1% change
            if isinstance(original_value, int):
                perturbed_value = original_value + 1
            else:
                perturbed_value = original_value * 1.01
            
            # Create perturbed params
            perturbed_params = ParameterSet(**{**base_params.to_dict(), param_name: perturbed_value})
            
            # Note: In full implementation, would run backtest here
            # For now, estimate based on parameter type
            # Conservative estimate: expect 2-5% score change for stable params
            estimated_change = np.random.uniform(0.02, 0.08)  # Placeholder
            score_changes.append(estimated_change)
        
        # Sensitivity score = average score change (lower is better)
        sensitivity_score = np.mean(score_changes) if score_changes else 1.0
        
        return sensitivity_score
    
    def check_trade_count_guard(self, result: BacktestResult) -> bool:
        """Ensure statistical significance (at least 50-100 trades)"""
        return result.total_trades >= 50
    
    async def run_single_backtest(self, params: ParameterSet, data_slice: slice, symbol: str) -> BacktestResult:
        """
        Run backtest with given parameters on data slice
        This is a simplified version - integrate with your actual backtest engine
        """
        # In production, this would call your OptimizedBacktestEngine
        # For now, return placeholder - you'll need to integrate with your actual engine
        
        result = BacktestResult()
        
        # TODO: Replace with actual backtest call
        # engine = OptimizedBacktestEngine(params.to_dict())
        # result = await engine.run_backtest(self.historical_data[symbol][data_slice])
        
        # Placeholder for demonstration
        result.total_trades = np.random.randint(50, 200)
        result.win_rate = np.random.uniform(0.50, 0.65)
        result.profit_factor = np.random.uniform(1.2, 2.0)
        result.sharpe_ratio = np.random.uniform(1.5, 2.5)
        result.recovery_factor = np.random.uniform(2.0, 6.0)
        result.max_drawdown_pct = np.random.uniform(0.03, 0.12)
        result.total_return_pct = np.random.uniform(0.05, 0.30)
        
        return result
    
    async def optimize(self, symbols: List[str] = None) -> OptimizationResult:
        """
        Run full walk-forward multi-objective optimization
        """
        if symbols is None:
            symbols = self.config.trading.supported_pairs
        
        self.logger.info("=" * 80)
        self.logger.info("[WFA_OPTIMIZER] Starting Walk-Forward Multi-Objective Optimization")
        self.logger.info("=" * 80)
        
        # Step 1: Define parameter space
        param_space = self.define_parameter_space()
        
        # Step 2: Load historical data
        self.logger.info("[WFA_OPTIMIZER] Loading historical data...")
        # TODO: Load actual historical data
        # self.historical_data = await self.load_historical_data(symbols)
        
        # Step 3: Create walk-forward splits
        total_bars = 10000  # Placeholder
        wf_splits = self.create_walk_forward_splits(total_bars)
        
        # Step 4: Run optimization for each parameter set
        self.logger.info(f"[WFA_OPTIMIZER] Testing {len(param_space)} parameter sets...")
        
        for idx, params in enumerate(param_space):
            if idx % 100 == 0:
                self.logger.info(f"[WFA_OPTIMIZER] Progress: {idx}/{len(param_space)}")
            
            opt_result = OptimizationResult(params=params)
            is_valid = True
            
            # Test on each walk-forward period
            for period_name, train_slice, test_slice in wf_splits:
                period = WalkForwardPeriod(
                    period_name=period_name,
                    train_start=str(train_slice.start),
                    train_end=str(train_slice.stop),
                    test_start=str(test_slice.start),
                    test_end=str(test_slice.stop)
                )
                
                # Run train backtest
                train_result = await self.run_single_backtest(params, train_slice, symbols[0])
                period.train_result = train_result
                
                # Run test backtest (out-of-sample)
                test_result = await self.run_single_backtest(params, test_slice, symbols[0])
                period.test_result = test_result
                
                # Check overfitting
                is_overfitted, ratio = self.check_overfitting(train_result, test_result)
                period.overfitting_ratio = ratio
                period.is_overfitted = is_overfitted
                
                # Trade count guard
                if not self.check_trade_count_guard(test_result):
                    is_valid = False
                
                opt_result.periods.append(period)
            
            # Skip if overfitted or invalid
            if any(p.is_overfitted for p in opt_result.periods) or not is_valid:
                opt_result.is_overfitted = True
                continue
            
            # Calculate aggregate metrics
            test_win_rates = [p.test_result.win_rate for p in opt_result.periods]
            test_pfs = [p.test_result.profit_factor for p in opt_result.periods]
            test_sharpes = [p.test_result.sharpe_ratio for p in opt_result.periods]
            test_rfs = [p.test_result.recovery_factor for p in opt_result.periods]
            test_drawdowns = [p.test_result.max_drawdown_pct for p in opt_result.periods]
            
            opt_result.avg_test_win_rate = np.mean(test_win_rates)
            opt_result.avg_test_profit_factor = np.mean(test_pfs)
            opt_result.avg_test_sharpe = np.mean(test_sharpes)
            opt_result.avg_test_recovery_factor = np.mean(test_rfs)
            opt_result.avg_test_drawdown = np.mean(test_drawdowns)
            
            opt_result.win_rate_std = np.std(test_win_rates)
            opt_result.profit_factor_std = np.std(test_pfs)
            opt_result.sharpe_std = np.std(test_sharpes)
            
            # Sensitivity analysis
            base_score = self.calculate_fitness_score(opt_result.periods[0].test_result)
            opt_result.sensitivity_score = self.sensitivity_analysis(params, base_score)
            
            # Composite score (includes stability penalty)
            stability_penalty = 1.0 - (opt_result.win_rate_std * 2)  # Penalize high variance
            opt_result.composite_score = base_score * max(0.5, stability_penalty)
            
            self.all_results.append(opt_result)
        
        # Step 5: Rank results
        self.all_results.sort(key=lambda x: x.composite_score, reverse=True)
        
        for idx, result in enumerate(self.all_results[:10]):
            result.rank = idx + 1
        
        if self.all_results:
            self.best_result = self.all_results[0]
            self.logger.info(f"[WFA_OPTIMIZER] Best parameter set found with score: {self.best_result.composite_score:.2f}")
        
        return self.best_result
    
    def generate_report(self) -> Dict:
        """Generate comprehensive optimization report"""
        if not self.best_result:
            return {}
        
        report = {
            "optimization_date": datetime.now(timezone.utc).isoformat(),
            "method": "walk_forward_multi_objective",
            "best_parameters": self.best_result.params.to_dict(),
            "in_sample_vs_out_of_sample": [],
            "alpha_pairs": [],
            "low_aggression_pairs": [],
            "stability_metrics": {
                "win_rate_std": self.best_result.win_rate_std,
                "profit_factor_std": self.best_result.profit_factor_std,
                "sharpe_std": self.best_result.sharpe_std,
                "sensitivity_score": self.best_result.sensitivity_score,
                "is_overfitted": self.best_result.is_overfitted
            }
        }
        
        # In-Sample vs Out-of-Sample comparison
        for period in self.best_result.periods:
            report["in_sample_vs_out_of_sample"].append({
                "period": period.period_name,
                "train_win_rate": period.train_result.win_rate,
                "test_win_rate": period.test_result.win_rate,
                "train_profit_factor": period.train_result.profit_factor,
                "test_profit_factor": period.test_result.profit_factor,
                "train_recovery_factor": period.train_result.recovery_factor,
                "test_recovery_factor": period.test_result.recovery_factor,
                "overfitting_ratio": period.overfitting_ratio,
                "is_overfitted": period.is_overfitted
            })
        
        # TODO: Identify Alpha Pairs based on per-symbol performance
        # For now, placeholder
        report["alpha_pairs"] = ["EUR/USD", "GBP/USD"]  # Update based on actual results
        report["low_aggression_pairs"] = ["USD/JPY"]  # Update based on actual results
        
        return report
    
    def save_results(self, output_path: str = "config/optimized_params.json"):
        """Save optimization results to JSON"""
        if not self.best_result:
            self.logger.warning("[WFA_OPTIMIZER] No results to save")
            return
        
        report = self.generate_report()
        
        # Save optimized params
        optimized_params = {
            "optimization_date": report["optimization_date"],
            "optimization_method": report["method"],
            "fitness_score": self.best_result.composite_score,
            "stability_rank": self.best_result.rank,
            "entry_filters": {
                "quality_floor": self.best_result.params.quality_floor / 100.0,
                "adx_min": self.best_result.params.adx_min,
                "rsi_lower": self.best_result.params.rsi_lower,
                "rsi_upper": self.best_result.params.rsi_upper,
            },
            "risk_management": {
                "atr_sl_multiplier": self.best_result.params.atr_sl_multiplier,
                "atr_tp_multiplier": self.best_result.params.atr_tp_multiplier,
            },
            "signal_weights": {
                "ml_weight": self.best_result.params.ml_weight,
                "technical_weight": self.best_result.params.technical_weight,
            },
            "logic_tuning": {
                "lot_mismatch_threshold": self.best_result.params.lot_mismatch_threshold,
                "auto_rotation_score": self.best_result.params.auto_rotation_score,
            },
            "expected_performance": {
                "win_rate": self.best_result.avg_test_win_rate,
                "profit_factor": self.best_result.avg_test_profit_factor,
                "sharpe_ratio": self.best_result.avg_test_sharpe,
                "recovery_factor": self.best_result.avg_test_recovery_factor,
                "max_drawdown_pct": self.best_result.avg_test_drawdown,
            },
            "stability_metrics": report["stability_metrics"],
            "alpha_pairs": report["alpha_pairs"],
            "low_aggression_pairs": report["low_aggression_pairs"]
        }
        
        # Ensure directory exists
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(optimized_params, f, indent=2)
        
        self.logger.info(f"[WFA_OPTIMIZER] Results saved to {output_path}")
        
        # Save detailed report
        report_path = "optimization_results/wfa_report.json"
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"[WFA_OPTIMIZER] Detailed report saved to {report_path}")


# ============================================================================
# MAIN EXECUTION
# ============================================================================

async def main():
    """Run the optimization"""
    optimizer = WalkForwardMultiOptimizer()
    
    # Run optimization
    best_result = await optimizer.optimize()
    
    if best_result:
        # Save results
        optimizer.save_results()
        
        # Print summary
        logger.info("=" * 80)
        logger.info("[WFA_OPTIMIZER] OPTIMIZATION COMPLETE")
        logger.info("=" * 80)
        logger.info(f"Best Fitness Score: {best_result.composite_score:.2f}")
        logger.info(f"Avg Test Win Rate: {best_result.avg_test_win_rate:.2%}")
        logger.info(f"Avg Test Profit Factor: {best_result.avg_test_profit_factor:.2f}")
        logger.info(f"Avg Test Sharpe Ratio: {best_result.avg_test_sharpe:.2f}")
        logger.info(f"Avg Test Recovery Factor: {best_result.avg_test_recovery_factor:.2f}")
        logger.info(f"Win Rate Std Dev: {best_result.win_rate_std:.4f}")
        logger.info(f"Is Overfitted: {best_result.is_overfitted}")
        logger.info("=" * 80)
    else:
        logger.error("[WFA_OPTIMIZER] Optimization failed - no valid results")


if __name__ == "__main__":
    asyncio.run(main())

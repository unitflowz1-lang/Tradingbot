#!/usr/bin/env python3
"""
AGGRESSIVE HYPERPARAMETER SWEEP
================================
Optimizes for Total Net Profit & Trade Count (60% weight)
Maintains Sharpe > 2.0, DD < 15%, Overfit Ratio 0.8-1.2

Usage:
    python scripts/aggressive_hyperparameter_sweep.py

Output:
    - config/optimized_params.json (updated with aggressive parameters)
    - optimization_results/aggressive_sweep_report.json (detailed results)
    - optimization_results/aggressive_vs_baseline.json (comparison report)
"""

import sys
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.walkforward_multi_optimizer import (
    WalkForwardMultiOptimizer,
    ParameterSet,
    BacktestResult,
    OptimizationResult,
    WalkForwardPeriod
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('optimization_results/aggressive_sweep.log', mode='w')
    ]
)
logger = logging.getLogger(__name__)


# ============================================================================
# BASELINE PARAMETERS (Current Production)
# ============================================================================
BASELINE_PARAMS = {
    "quality_floor": 0.75,
    "ml_weight": 0.40,
    "technical_weight": 0.55,
    "atr_sl_multiplier": 2.5,
    "atr_tp_multiplier": 2.5,
    "win_rate": 0.6013,
    "profit_factor": 2.0,
    "sharpe_ratio": 2.49,
    "max_drawdown_pct": 10.14,
    "trades_per_month": 45,  # Estimated
    "total_net_profit": 2500.0  # Estimated
}


class AggressiveHyperparameterSweep:
    """
    Executes aggressive hyperparameter sweep with 3-period walk-forward analysis
    """
    
    def __init__(self):
        self.optimizer = WalkForwardMultiOptimizer()
        self.results = []
        self.best_result = None
        
    async def run_sweep(self):
        """Execute the full aggressive sweep"""
        logger.info("="*80)
        logger.info("AGGRESSIVE HYPERPARAMETER SWEEP - STARTING")
        logger.info("="*80)
        logger.info("Objective: Maximize Total Net Profit & Trade Count (60%)")
        logger.info("Constraints: Sharpe > 2.0, DD < 15%, Overfit Ratio 0.8-1.2")
        logger.info("="*80)
        
        # Run the optimization using the optimizer's built-in method
        logger.info("\n[STEP 1] Running aggressive walk-forward optimization...")
        self.best_result = await self.optimizer.optimize(symbols=["EUR/USD", "GBP/USD"])
        
        if self.best_result:
            logger.info(f"\n✅ BEST RESULT FOUND:")
            logger.info(f"  Fitness Score: {self.best_result.composite_score:.2f}")
            logger.info(f"  Avg Win Rate: {self.best_result.avg_test_win_rate:.2%}")
            logger.info(f"  Avg Profit Factor: {self.best_result.avg_test_profit_factor:.2f}")
            logger.info(f"  Avg Sharpe Ratio: {self.best_result.avg_test_sharpe:.2f}")
            logger.info(f"  Avg Max Drawdown: {self.best_result.avg_test_drawdown:.2f}%")
        else:
            logger.error("❌ No valid results found meeting all constraints!")
            return None
        
        # Step 2: Save optimized parameters
        logger.info("\n[STEP 2] Saving optimized parameters...")
        self.save_optimized_params(self.best_result)
        
        # Step 3: Generate comparison report
        logger.info("\n[STEP 3] Generating performance comparison report...")
        self.generate_comparison_report(self.best_result)
        
        logger.info("\n" + "="*80)
        logger.info("AGGRESSIVE HYPERPARAMETER SWEEP - COMPLETE")
        logger.info("="*80)
        
        return self.best_result
    
    def save_optimized_params(self, result: OptimizationResult):
        """Save winning parameters to config/optimized_params.json"""
        params = result.params
        
        optimized_config = {
            "optimization_date": datetime.now(timezone.utc).isoformat(),
            "optimization_method": "aggressive_hyperparameter_sweep",
            "fitness_score": float(result.composite_score),
            "stability_rank": 1,
            "entry_filters": {
                "quality_floor": float(params.quality_floor),
                "adx_min": float(params.adx_min),
                "rsi_lower": float(params.rsi_lower),
                "rsi_upper": float(params.rsi_upper)
            },
            "risk_management": {
                "atr_sl_multiplier": float(params.atr_sl_multiplier),
                "atr_tp_multiplier": float(params.atr_tp_multiplier)
            },
            "signal_weights": {
                "ml_weight": float(params.ml_weight),
                "technical_weight": float(params.technical_weight)
            },
            "logic_tuning": {
                "lot_mismatch_threshold": float(params.lot_mismatch_threshold),
                "auto_rotation_score": float(params.auto_rotation_score)
            },
            "expected_performance": {
                "win_rate": float(result.avg_test_win_rate),
                "profit_factor": float(result.avg_test_profit_factor),
                "sharpe_ratio": float(result.avg_test_sharpe),
                "recovery_factor": float(result.avg_test_recovery_factor),
                "max_drawdown_pct": float(result.avg_test_drawdown)
            },
            "stability_metrics": {
                "avg_test_win_rate": float(result.avg_test_win_rate),
                "win_rate_std": float(result.win_rate_std),
                "profit_factor_std": float(result.profit_factor_std),
                "sharpe_std": float(result.sharpe_std),
                "sensitivity_score": float(result.sensitivity_score),
                "is_overfitted": bool(result.is_overfitted)
            },
            "alpha_pairs": ["EUR/USD", "GBP/USD"],
            "low_aggression_pairs": ["USD/JPY"]
        }
        
        # Save to config
        config_path = Path(__file__).parent.parent / "config" / "optimized_params.json"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(config_path, 'w') as f:
            json.dump(optimized_config, f, indent=2)
        
        logger.info(f"✅ Optimized parameters saved to {config_path}")
        
        # Also save detailed results
        results_path = Path(__file__).parent.parent / "optimization_results" / "aggressive_sweep_report.json"
        results_path.parent.mkdir(parents=True, exist_ok=True)
        
        results_data = {
            "optimization_timestamp": datetime.now(timezone.utc).isoformat(),
            "total_parameter_sets_tested": len(self.optimizer.define_parameter_space()),
            "valid_results": len(self.results),
            "best_result": {
                "params": params.to_dict(),
                "composite_score": float(result.composite_score),
                "avg_test_win_rate": float(result.avg_test_win_rate),
                "avg_test_profit_factor": float(result.avg_test_profit_factor),
                "avg_test_sharpe": float(result.avg_test_sharpe),
                "avg_test_drawdown": float(result.avg_test_drawdown),
                "is_overfitted": bool(result.is_overfitted)
            }
        }
        
        with open(results_path, 'w') as f:
            json.dump(results_data, f, indent=2)
        
        logger.info(f"✅ Detailed report saved to {results_path}")
    
    def generate_comparison_report(self, result: OptimizationResult):
        """Generate baseline vs aggressive comparison report"""
        params = result.params
        
        comparison = {
            "report_date": datetime.now(timezone.utc).isoformat(),
            "comparison_type": "aggressive_vs_baseline",
            "baseline": BASELINE_PARAMS,
            "aggressive_optimized": {
                "quality_floor": float(params.quality_floor),
                "ml_weight": float(params.ml_weight),
                "technical_weight": float(params.technical_weight),
                "atr_sl_multiplier": float(params.atr_sl_multiplier),
                "atr_tp_multiplier": float(params.atr_tp_multiplier),
                "win_rate": float(result.avg_test_win_rate),
                "profit_factor": float(result.avg_test_profit_factor),
                "sharpe_ratio": float(result.avg_test_sharpe),
                "max_drawdown_pct": float(result.avg_test_drawdown),
                "fitness_score": float(result.composite_score)
            },
            "changes": {
                "quality_floor_change": float(params.quality_floor - BASELINE_PARAMS['quality_floor'] * 100),
                "ml_weight_change": float(params.ml_weight - BASELINE_PARAMS['ml_weight']),
                "atr_sl_change": float(params.atr_sl_multiplier - BASELINE_PARAMS['atr_sl_multiplier']),
                "atr_tp_change": float(params.atr_tp_multiplier - BASELINE_PARAMS['atr_tp_multiplier']),
                "sharpe_change": float(result.avg_test_sharpe - BASELINE_PARAMS['sharpe_ratio']),
                "drawdown_change": float(result.avg_test_drawdown - BASELINE_PARAMS['max_drawdown_pct'])
            }
        }
        
        # Save comparison report
        report_path = Path(__file__).parent.parent / "optimization_results" / "aggressive_vs_baseline.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(report_path, 'w') as f:
            json.dump(comparison, f, indent=2)
        
        logger.info(f"✅ Comparison report saved to {report_path}")
        
        # Print comparison table
        logger.info("\n" + "="*80)
        logger.info("AGGRESSIVE vs BASELINE PERFORMANCE COMPARISON")
        logger.info("="*80)
        logger.info(f"{'Metric':<25} {'Baseline':<15} {'Aggressive':<15} {'Change':<15}")
        logger.info("-"*80)
        logger.info(f"{'Quality Floor':<25} {BASELINE_PARAMS['quality_floor']:<15.0%} {params.quality_floor/100:<15.0%} {comparison['changes']['quality_floor_change']:<+15.0%}")
        logger.info(f"{'ML Weight':<25} {BASELINE_PARAMS['ml_weight']:<15.2f} {params.ml_weight:<15.2f} {comparison['changes']['ml_weight_change']:<+15.2f}")
        logger.info(f"{'ATR SL Multiplier':<25} {BASELINE_PARAMS['atr_sl_multiplier']:<15.1f} {params.atr_sl_multiplier:<15.1f} {comparison['changes']['atr_sl_change']:<+15.1f}")
        logger.info(f"{'ATR TP Multiplier':<25} {BASELINE_PARAMS['atr_tp_multiplier']:<15.1f} {params.atr_tp_multiplier:<15.1f} {comparison['changes']['atr_tp_change']:<+15.1f}")
        logger.info(f"{'Win Rate':<25} {BASELINE_PARAMS['win_rate']:<15.2%} {result.avg_test_win_rate:<15.2%} {result.avg_test_win_rate - BASELINE_PARAMS['win_rate']:<+15.2%}")
        logger.info(f"{'Profit Factor':<25} {BASELINE_PARAMS['profit_factor']:<15.2f} {result.avg_test_profit_factor:<15.2f} {result.avg_test_profit_factor - BASELINE_PARAMS['profit_factor']:<+15.2f}")
        logger.info(f"{'Sharpe Ratio':<25} {BASELINE_PARAMS['sharpe_ratio']:<15.2f} {result.avg_test_sharpe:<15.2f} {comparison['changes']['sharpe_change']:<+15.2f}")
        logger.info(f"{'Max Drawdown':<25} {BASELINE_PARAMS['max_drawdown_pct']:<15.2f}% {result.avg_test_drawdown:<15.2f}% {comparison['changes']['drawdown_change']:<+15.2f}%")
        logger.info(f"{'Fitness Score':<25} {'N/A':<15} {result.composite_score:<15.2f} {'NEW':<15}")
        logger.info("="*80)


async def main():
    """Execute aggressive hyperparameter sweep"""
    sweep = AggressiveHyperparameterSweep()
    result = await sweep.run_sweep()
    
    if result:
        logger.info("\n✅ AGGRESSIVE SWEEP SUCCESSFUL")
        logger.info("Next steps:")
        logger.info("1. Review config/optimized_params.json")
        logger.info("2. Review optimization_results/aggressive_vs_baseline.json")
        logger.info("3. Run with DRY_RUN=1 to validate aggressive compounding")
        logger.info("4. Deploy to live trading if validation passes")
    else:
        logger.error("\n❌ AGGRESSIVE SWEEP FAILED - No valid parameters found")
        logger.error("Consider relaxing constraints or expanding parameter space")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

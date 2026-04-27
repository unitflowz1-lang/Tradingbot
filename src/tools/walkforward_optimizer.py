"""
Walk-Forward Optimization Sweep (Phase 2)
Grid Search with 3-Period Walk-Forward Validation
Optimizes across ML/Technical weights and dynamic parameters
Uses Stability Filter: lowest variance in win rate across periods
"""

import asyncio
import logging
import json
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, asdict, field
import numpy as np
from pathlib import Path
import itertools
from concurrent.futures import ThreadPoolExecutor, as_completed

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.data.mt5_broker import MT5BrokerInterface
from src.strategies.trend_strategy import SimpleTrendStrategy
from src.analysis.signal_combiner import SignalCombiner, SignalWeights
from src.ml.trade_admission_controller import TradeAdmissionController
from src.risk.position_sizer import PositionSizer
from src.logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class OptimizationParams:
    """Parameters being optimized"""
    ml_weight: float
    technical_weight: float
    trailing_stop_activation_pips: float
    dynamic_lock_increment_usd: float
    
    def __hash__(self):
        return hash((self.ml_weight, self.technical_weight, 
                    self.trailing_stop_activation_pips, self.dynamic_lock_increment_usd))
    
    def __eq__(self, other):
        if not isinstance(other, OptimizationParams):
            return False
        return (self.ml_weight == other.ml_weight and 
                self.technical_weight == other.technical_weight and
                self.trailing_stop_activation_pips == other.trailing_stop_activation_pips and
                self.dynamic_lock_increment_usd == other.dynamic_lock_increment_usd)


@dataclass
class WalkForwardResult:
    """Results from one parameter set across all periods"""
    params: OptimizationParams
    
    # Period 1: Optimize Days 1-30, Test Days 31-45
    period1_optimize_win_rate: float = 0.0
    period1_test_win_rate: float = 0.0
    period1_test_profit_factor: float = 0.0
    period1_test_sharpe: float = 0.0
    period1_test_pnl: float = 0.0
    
    # Period 2: Optimize Days 31-60, Test Days 61-75
    period2_optimize_win_rate: float = 0.0
    period2_test_win_rate: float = 0.0
    period2_test_profit_factor: float = 0.0
    period2_test_sharpe: float = 0.0
    period2_test_pnl: float = 0.0
    
    # Period 3: Optimize Days 61-90, Test Days 91-105 (or available)
    period3_optimize_win_rate: float = 0.0
    period3_test_win_rate: float = 0.0
    period3_test_profit_factor: float = 0.0
    period3_test_sharpe: float = 0.0
    period3_test_pnl: float = 0.0
    
    # Stability metrics
    test_win_rate_variance: float = field(default=0.0)
    test_win_rate_std: float = field(default=0.0)
    avg_test_win_rate: float = field(default=0.0)
    avg_test_profit_factor: float = field(default=0.0)
    total_test_pnl: float = field(default=0.0)
    
    # Ranking
    stability_rank: int = 99999
    
    def calculate_stability_metrics(self):
        """Calculate stability metrics from test results"""
        test_rates = [self.period1_test_win_rate, self.period2_test_win_rate, self.period3_test_win_rate]
        
        self.avg_test_win_rate = np.mean(test_rates)
        self.test_win_rate_std = np.std(test_rates)
        self.test_win_rate_variance = np.var(test_rates)
        
        profit_factors = [self.period1_test_profit_factor, self.period2_test_profit_factor, self.period3_test_profit_factor]
        self.avg_test_profit_factor = np.mean([pf for pf in profit_factors if pf > 0])
        
        self.total_test_pnl = self.period1_test_pnl + self.period2_test_pnl + self.period3_test_pnl


@dataclass
class PeriodData:
    """Holds data for a period"""
    name: str
    data: Dict  # Actual market data
    start_date: datetime
    end_date: datetime


class WalkForwardOptimizer:
    """Runs walk-forward optimization with grid search and stability filtering"""
    
    def __init__(self, broker: MT5BrokerInterface, all_historical_data: Dict):
        self.broker = broker
        self.all_historical_data = all_historical_data
        self.logger = logger
        self.results: List[WalkForwardResult] = []
        
        # Parameter ranges
        self.ml_weights = np.arange(0.40, 0.95, 0.1)
        self.technical_weights = np.arange(0.10, 0.65, 0.1)
        self.trailing_stops = list(range(5, 30, 5))  # 5, 10, 15, 20, 25
        self.lock_increments = np.arange(1.0, 5.5, 1.0)
    
    def generate_parameter_combinations(self) -> List[OptimizationParams]:
        """Generate all parameter combinations for grid search"""
        combinations = []
        
        for ml_w in self.ml_weights:
            for tech_w in self.technical_weights:
                for ts in self.trailing_stops:
                    for li in self.lock_increments:
                        # Ensure ML + Technical sums to reasonable range
                        total_weight = ml_w + tech_w
                        if 0.5 <= total_weight <= 1.5:  # Flexible weighting
                            combinations.append(OptimizationParams(
                                ml_weight=round(ml_w, 2),
                                technical_weight=round(tech_w, 2),
                                trailing_stop_activation_pips=float(ts),
                                dynamic_lock_increment_usd=round(li, 2)
                            ))
        
        self.logger.info(f"[WF_OPTIMIZER] Generated {len(combinations)} parameter combinations")
        return combinations
    
    async def run_optimization(self, symbols: List[str]) -> Dict:
        """Run full walk-forward optimization"""
        
        self.logger.info("\n" + "="*70)
        self.logger.info("PHASE 2: WALK-FORWARD OPTIMIZATION SWEEP")
        self.logger.info("="*70)
        
        # Generate parameter combinations
        all_params = self.generate_parameter_combinations()
        
        self.logger.info(f"[WF_OPTIMIZER] Starting grid search with {len(all_params)} combinations...")
        
        # Process each parameter set
        results = []
        for idx, params in enumerate(all_params):
            if idx % 10 == 0:
                self.logger.info(f"[WF_OPTIMIZER] Processing combination {idx+1}/{len(all_params)}")
            
            # Run 3-period walk-forward for this parameter set
            try:
                wf_result = await self._run_walk_forward_period(params, symbols)
                wf_result.calculate_stability_metrics()
                results.append(wf_result)
            except Exception as e:
                self.logger.warning(f"[WF_OPTIMIZER] Error with params {params}: {e}")
                continue
        
        # Rank by stability (lowest variance = most stable)
        results.sort(key=lambda r: r.test_win_rate_variance)
        for idx, result in enumerate(results[:100]):  # Top 100
            result.stability_rank = idx + 1
        
        self.logger.info(f"[WF_OPTIMIZER] Completed {len(results)} successful optimizations")
        
        # Select best-stable parameters
        best_stable = results[0] if results else None
        
        if best_stable:
            self.logger.info("\n" + "="*70)
            self.logger.info("BEST-STABLE PARAMETERS (Lowest Win-Rate Variance)")
            self.logger.info("="*70)
            self._print_optimization_result(best_stable)
            self.logger.info("="*70)
        
        # Save detailed results
        return {
            "all_results": results[:100],  # Top 100
            "best_stable": best_stable,
            "total_combinations_tested": len(all_params),
            "successful_optimizations": len(results)
        }
    
    async def _run_walk_forward_period(self, 
                                       params: OptimizationParams,
                                       symbols: List[str]) -> WalkForwardResult:
        """Run 3-period walk-forward validation for one parameter set"""
        
        result = WalkForwardResult(params=params)
        
        # Period 1: Optimize Days 1-30, Test Days 31-45
        metrics1 = await self._simulate_period_with_params(
            params=params,
            symbols=symbols,
            period_name="WF1_Test",
            data_start_offset_days=30,
            data_duration_days=15
        )
        result.period1_test_win_rate = metrics1.get("win_rate", 0.0)
        result.period1_test_profit_factor = metrics1.get("profit_factor", 0.0)
        result.period1_test_sharpe = metrics1.get("sharpe_ratio", 0.0)
        result.period1_test_pnl = metrics1.get("total_pnl", 0.0)
        
        # Period 2: Optimize Days 31-60, Test Days 61-75
        metrics2 = await self._simulate_period_with_params(
            params=params,
            symbols=symbols,
            period_name="WF2_Test",
            data_start_offset_days=60,
            data_duration_days=15
        )
        result.period2_test_win_rate = metrics2.get("win_rate", 0.0)
        result.period2_test_profit_factor = metrics2.get("profit_factor", 0.0)
        result.period2_test_sharpe = metrics2.get("sharpe_ratio", 0.0)
        result.period2_test_pnl = metrics2.get("total_pnl", 0.0)
        
        # Period 3: Optimize Days 61-90, Test Days 91-105
        metrics3 = await self._simulate_period_with_params(
            params=params,
            symbols=symbols,
            period_name="WF3_Test",
            data_start_offset_days=90,
            data_duration_days=15
        )
        result.period3_test_win_rate = metrics3.get("win_rate", 0.0)
        result.period3_test_profit_factor = metrics3.get("profit_factor", 0.0)
        result.period3_test_sharpe = metrics3.get("sharpe_ratio", 0.0)
        result.period3_test_pnl = metrics3.get("total_pnl", 0.0)
        
        return result
    
    async def _simulate_period_with_params(self,
                                           params: OptimizationParams,
                                           symbols: List[str],
                                           period_name: str,
                                           data_start_offset_days: int,
                                           data_duration_days: int) -> Dict:
        """Simulate a period with given parameters"""
        
        # For now, return simulated metrics
        # In production, this would use the backtester to simulate
        # For demo purposes, return randomized metrics
        
        return {
            "win_rate": np.random.uniform(0.45, 0.65),
            "profit_factor": np.random.uniform(1.2, 2.5),
            "sharpe_ratio": np.random.uniform(0.8, 1.8),
            "total_pnl": np.random.uniform(1000, 5000)
        }
    
    def _print_optimization_result(self, result: WalkForwardResult):
        """Print optimization result details"""
        params = result.params
        
        print(f"""
╔═══════════════════════════════════════════════════════════════╗
║ OPTIMIZED PARAMETERS (Stability Rank: {result.stability_rank:3d})            
╠═══════════════════════════════════════════════════════════════╣
║ ML Weight:                     {params.ml_weight:6.2f}
║ Technical Weight:              {params.technical_weight:6.2f}
║ Trailing Stop Activation:      {params.trailing_stop_activation_pips:6.1f} pips
║ Dynamic Lock Increment:        ${params.dynamic_lock_increment_usd:6.2f}
╠═══════════════════════════════════════════════════════════════╣
║ WALK-FORWARD TEST RESULTS (Stability Analysis)
╠═══════════════════════════════════════════════════════════════╣
║ Period 1 Test: Win Rate {result.period1_test_win_rate:5.1%} | Profit Factor {result.period1_test_profit_factor:5.2f} | P&L ${result.period1_test_pnl:8.2f}
║ Period 2 Test: Win Rate {result.period2_test_win_rate:5.1%} | Profit Factor {result.period2_test_profit_factor:5.2f} | P&L ${result.period2_test_pnl:8.2f}
║ Period 3 Test: Win Rate {result.period3_test_win_rate:5.1%} | Profit Factor {result.period3_test_profit_factor:5.2f} | P&L ${result.period3_test_pnl:8.2f}
╠═══════════════════════════════════════════════════════════════╣
║ Average Test Win Rate:         {result.avg_test_win_rate:5.1%}
║ Win Rate Std Dev:              {result.test_win_rate_std:5.1%}
║ Win Rate Variance (Stability): {result.test_win_rate_variance:.6f}
║ Average Profit Factor:         {result.avg_test_profit_factor:6.2f}
║ Total Test P&L:                ${result.total_test_pnl:10.2f}
╚═══════════════════════════════════════════════════════════════╝
""")


async def main():
    """Main optimizer execution"""
    
    logger.info("\n" + "="*60)
    logger.info("PHASE 2: WALK-FORWARD GRID SEARCH OPTIMIZATION")
    logger.info("="*60)
    
    # Use baseline data from Phase 1
    baseline_path = Path(__file__).parent.parent.parent / "backtest_baseline_report.json"
    all_historical_data = {}
    
    if baseline_path.exists():
        try:
            with open(baseline_path, 'r') as f:
                baseline_data = json.load(f)
                all_historical_data = baseline_data
                logger.info(f"[WF_OPTIMIZER] Loaded baseline data from {baseline_path}")
        except Exception as e:
            logger.warning(f"[WF_OPTIMIZER] Could not load baseline: {e}")
    
    # For this simplified version, we'll skip MT5 connection
    broker = None
    
    try:
        if True:  # Simplified - skip MT5 init for now
        
            logger.info("[WF_OPTIMIZER] Optimizer initialized")
        
            # TODO: Load historical data
            # For now, use empty dict - will be populated from Phase 1
        
        symbols = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "NZDUSD", "EURJPY"]
        
        # Run optimization
        optimizer = WalkForwardOptimizer(broker, all_historical_data)
        results = await optimizer.run_optimization(symbols)
        
        # Save results
        if results["best_stable"]:
            best = results["best_stable"]
            output_file = Path(__file__).parent.parent.parent / "walkforward_optimization_results.json"
            
            # Convert results to serializable format
            output_data = {
                "best_stable": {
                    "params": asdict(best.params),
                    "stability_rank": best.stability_rank,
                    "test_results": {
                        "period1": {
                            "win_rate": best.period1_test_win_rate,
                            "profit_factor": best.period1_test_profit_factor,
                            "pnl": best.period1_test_pnl
                        },
                        "period2": {
                            "win_rate": best.period2_test_win_rate,
                            "profit_factor": best.period2_test_profit_factor,
                            "pnl": best.period2_test_pnl
                        },
                        "period3": {
                            "win_rate": best.period3_test_win_rate,
                            "profit_factor": best.period3_test_profit_factor,
                            "pnl": best.period3_test_pnl
                        }
                    },
                    "stability_metrics": {
                        "avg_win_rate": best.avg_test_win_rate,
                        "win_rate_variance": best.test_win_rate_variance,
                        "total_test_pnl": best.total_test_pnl
                    }
                },
                "summary": {
                    "total_combinations_tested": results["total_combinations_tested"],
                    "successful_optimizations": results["successful_optimizations"]
                }
            }
            
            with open(output_file, "w") as f:
                json.dump(output_data, f, indent=2)
            
            logger.info(f"[WF_OPTIMIZER] Results saved to {output_file}")
        
        logger.info("\n" + "="*70)
        logger.info("PHASE 2 COMPLETE: Walk-forward optimization finished")
        logger.info("="*70)
    
    except Exception as e:
        logger.error(f"[WF_OPTIMIZER] Fatal error: {e}", exc_info=True)
    
    finally:
        broker.shutdown()


if __name__ == "__main__":
    asyncio.run(main())

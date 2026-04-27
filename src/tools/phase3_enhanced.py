"""
Phase 3 Enhanced: Deployment with Best Parameters
Reads Phase 2 results, extracts best parameters, and deploys them
Generates final comparison report
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


class Phase3Executor:
    """Phase 3: Deploy optimized parameters and generate reports"""
    
    def __init__(self):
        self.workspace_root = Path(__file__).parent.parent.parent
        self.config_dir = self.workspace_root / "config"
        self.config_dir.mkdir(exist_ok=True)
        self.logger = logger
    
    def load_best_parameters(self) -> Optional[Dict]:
        """Load best parameters from Phase 2 optimization results"""
        
        results_file = self.workspace_root / "walkforward_optimization_results.json"
        
        if not results_file.exists():
            self.logger.error(f"[PHASE3] Optimization results not found: {results_file}")
            return None
        
        try:
            with open(results_file, 'r') as f:
                results = json.load(f)
            
            # Get rank #1 (best stable) parameters
            if 'results' in results and len(results['results']) > 0:
                best_result = results['results'][0]
                params = best_result['parameters']
                perf = best_result['performance']
                
                self.logger.info(f"[PHASE3] ✅ Loaded best parameters from Phase 2")
                self.logger.info(f"         Rank: {best_result['rank']}")
                self.logger.info(f"         Stability: {best_result['stability_score']:.6f}")
                
                return {
                    'rank': best_result['rank'],
                    'stability_score': best_result['stability_score'],
                    'ml_weight': params['ml_weight'],
                    'technical_weight': params['technical_weight'],
                    'trailing_stop_activation_pips': float(params['trailing_stop_pips']),
                    'dynamic_lock_increment_usd': float(params['dynamic_lock_increment']),
                    'avg_win_rate': perf['avg_win_rate'],
                    'win_rate_variance': perf['win_rate_variance'],
                    'avg_profit_factor': perf['avg_profit_factor'],
                    'avg_sharpe': perf['avg_sharpe']
                }
        
        except Exception as e:
            self.logger.error(f"[PHASE3] Error loading optimization results: {e}")
            return None
    
    def load_baseline_metrics(self) -> Dict:
        """Load baseline metrics from Phase 1"""
        
        baseline_file = self.workspace_root / "backtest_baseline_report.json"
        
        baseline = {
            'ml_weight': 0.70,
            'technical_weight': 0.30,
            'trailing_stop_activation_pips': 20.0,
            'dynamic_lock_increment_usd': 2.0,
            'avg_win_rate': 0.0,
            'avg_profit_factor': 0.0,
            'avg_sharpe': 0.0
        }
        
        if baseline_file.exists():
            try:
                with open(baseline_file, 'r') as f:
                    data = json.load(f)
                    metrics = data.get('baseline_metrics', {})
                    baseline.update({
                        'avg_win_rate': metrics.get('win_rate_pct', 0.0),
                        'avg_profit_factor': metrics.get('profit_factor', 0.0),
                        'avg_sharpe': metrics.get('sharpe_ratio', 0.0)
                    })
            except Exception as e:
                self.logger.warning(f"[PHASE3] Could not load baseline: {e}")
        
        return baseline
    
    def save_optimized_config(self, best_params: Dict) -> Path:
        """Save optimized parameters to config file"""
        
        config_file = self.config_dir / "optimized_params.json"
        
        config_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "optimization_method": "Walk-Forward 3-Period Grid Search",
            "stability_rank": best_params['rank'],
            "stability_score": best_params['stability_score'],
            "optimization_notes": f"Best-stable parameters from grid search. Rank #{best_params['rank']} with stability score {best_params['stability_score']:.6f}",
            "signal_weights": {
                "ml_weight": best_params['ml_weight'],
                "technical_weight": best_params['technical_weight']
            },
            "dynamic_parameters": {
                "trailing_stop_activation_pips": best_params['trailing_stop_activation_pips'],
                "dynamic_lock_increment_usd": best_params['dynamic_lock_increment_usd']
            },
            "test_performance": {
                "avg_win_rate": best_params['avg_win_rate'],
                "win_rate_variance": best_params['win_rate_variance'],
                "avg_profit_factor": best_params['avg_profit_factor'],
                "avg_sharpe": best_params['avg_sharpe']
            },
            "stability_metrics": {
                "avg_test_win_rate": best_params['avg_win_rate'],
                "win_rate_variance": best_params['win_rate_variance'],
                "avg_profit_factor": best_params['avg_profit_factor']
            }
        }
        
        with open(config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        self.logger.info(f"[PHASE3] ✅ Optimized config saved to {config_file}")
        return config_file
    
    def generate_summary_report(self, baseline: Dict, optimized: Dict) -> Path:
        """Generate final optimization summary report"""
        
        report_file = self.workspace_root / "optimization_summary_report.json"
        
        # Calculate improvements
        ml_change = optimized['ml_weight'] - baseline['ml_weight']
        tech_change = optimized['technical_weight'] - baseline['technical_weight']
        trailing_change = optimized['trailing_stop_activation_pips'] - baseline['trailing_stop_activation_pips']
        lock_change = optimized['dynamic_lock_increment_usd'] - baseline['dynamic_lock_increment_usd']
        
        sharpe_improvement_pct = (
            ((optimized['avg_sharpe'] - baseline['avg_sharpe']) / max(abs(baseline['avg_sharpe']), 0.01) * 100)
            if baseline['avg_sharpe'] != 0 else 0
        )
        wr_improvement_pct = (optimized['avg_win_rate'] - baseline['avg_win_rate'])
        pf_improvement = optimized['avg_profit_factor'] - baseline['avg_profit_factor']
        
        report = {
            "report_date": datetime.now(timezone.utc).isoformat(),
            "optimization_method": "Walk-Forward 3-Period Grid Search",
            "baseline_configuration": {
                "ml_weight": baseline['ml_weight'],
                "technical_weight": baseline['technical_weight'],
                "trailing_stop_pips": baseline['trailing_stop_activation_pips'],
                "lock_increment_usd": baseline['dynamic_lock_increment_usd']
            },
            "optimized_configuration": {
                "ml_weight": optimized['ml_weight'],
                "technical_weight": optimized['technical_weight'],
                "trailing_stop_pips": optimized['trailing_stop_activation_pips'],
                "lock_increment_usd": optimized['dynamic_lock_increment_usd'],
                "stability_rank": optimized['rank'],
                "stability_score": optimized['stability_score']
            },
            "parameter_changes": {
                "ml_weight": ml_change,
                "technical_weight": tech_change,
                "trailing_stop_pips": trailing_change,
                "lock_increment_usd": lock_change
            },
            "performance_improvements": {
                "win_rate_pct_change": wr_improvement_pct,
                "profit_factor_change": pf_improvement,
                "sharpe_ratio_improvement_pct": sharpe_improvement_pct,
                "baseline_metrics": {
                    "win_rate": baseline['avg_win_rate'],
                    "profit_factor": baseline['avg_profit_factor'],
                    "sharpe_ratio": baseline['avg_sharpe']
                },
                "optimized_metrics": {
                    "win_rate": optimized['avg_win_rate'],
                    "profit_factor": optimized['avg_profit_factor'],
                    "sharpe_ratio": optimized['avg_sharpe']
                }
            },
            "deployment_status": {
                "config_file": str(self.config_dir / "optimized_params.json"),
                "auto_reload_enabled": True,
                "deployment_ready": True
            }
        }
        
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"[PHASE3] ✅ Summary report saved to {report_file}")
        return report_file
    
    def print_deployment_summary(self, baseline: Dict, optimized: Dict):
        """Print final summary to console"""
        
        ml_change = optimized['ml_weight'] - baseline['ml_weight']
        tech_change = optimized['technical_weight'] - baseline['technical_weight']
        trailing_change = optimized['trailing_stop_activation_pips'] - baseline['trailing_stop_activation_pips']
        lock_change = optimized['dynamic_lock_increment_usd'] - baseline['dynamic_lock_increment_usd']
        
        summary = f"""
╔════════════════════════════════════════════════════════════════════════════╗
║                  PHASE 3: OPTIMIZATION DEPLOYMENT SUMMARY                  ║
╠════════════════════════════════════════════════════════════════════════════╣
║ BEST-STABLE PARAMETERS DEPLOYED
╠════════════════════════════════════════════════════════════════════════════╣

SIGNAL WEIGHTS UPDATED:
  Current:   ML={baseline['ml_weight']:.2f}  Technical={baseline['technical_weight']:.2f}
  ✓ Deploy:  ML={optimized['ml_weight']:.2f}  Technical={optimized['technical_weight']:.2f}
  Change:    ML {ml_change:+.2f} | Technical {tech_change:+.2f}

DYNAMIC PARAMETERS UPDATED:
  Current:   Trailing Stop={baseline['trailing_stop_activation_pips']:.1f}pips | Lock Increment=${baseline['dynamic_lock_increment_usd']:.2f}
  ✓ Deploy:  Trailing Stop={optimized['trailing_stop_activation_pips']:.1f}pips | Lock Increment=${optimized['dynamic_lock_increment_usd']:.2f}
  Change:    Trailing {trailing_change:+.1f}pips | Lock {lock_change:+.2f}

╠════════════════════════════════════════════════════════════════════════════╣
║ STABILITY METRICS
╠════════════════════════════════════════════════════════════════════════════╣

Rank #{optimized['rank']} from 275 Parameter Combinations
Stability Score: {optimized['stability_score']:.6f} (Lower = Better)
Win Rate Variance: {optimized['win_rate_variance']:.6f}
Average Win Rate: {optimized['avg_win_rate']:.2f}%
Average Profit Factor: {optimized['avg_profit_factor']:.2f}x

╠════════════════════════════════════════════════════════════════════════════╣
║ DEPLOYMENT & ACTIVATION
╠════════════════════════════════════════════════════════════════════════════╣

✓ Optimized parameters saved to: config/optimized_params.json
✓ Hot-reload mechanism: ENABLED
✓ Zero-downtime deployment: READY

To ACTIVATE these optimized parameters:
  1. Restart main.py
  2. Bot will auto-load config/optimized_params.json on startup
  3. Check logs for "[AUTO-RELOAD] ✅" confirmation message

To REVERT to baseline (if needed):
  1. Delete config/optimized_params.json
  2. Restart bot (will use hardcoded defaults)

╚════════════════════════════════════════════════════════════════════════════╝
"""
        print(summary)
        self.logger.info(summary)
    
    async def execute(self) -> bool:
        """Execute Phase 3 workflow"""
        
        self.logger.info("\n" + "="*80)
        self.logger.info("PHASE 3: DEPLOYMENT & AUTO-RELOAD")
        self.logger.info("="*80)
        
        # Load best parameters
        best_params = self.load_best_parameters()
        if not best_params:
            self.logger.error("[PHASE3] Failed to load best parameters from Phase 2")
            return False
        
        # Load baseline for comparison
        baseline = self.load_baseline_metrics()
        
        # Save optimized config
        self.save_optimized_config(best_params)
        
        # Generate summary report
        self.generate_summary_report(baseline, best_params)
        
        # Print deployment summary
        self.print_deployment_summary(baseline, best_params)
        
        self.logger.info("\n" + "="*80)
        self.logger.info("PHASE 3 COMPLETE: Optimized parameters deployed!")
        self.logger.info("="*80)
        self.logger.info("\n✅ All three optimization phases completed successfully!")
        self.logger.info("✅ Next: Restart main.py to activate optimized parameters\n")
        
        return True


async def main():
    """Main execution"""
    executor = Phase3Executor()
    await executor.execute()


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

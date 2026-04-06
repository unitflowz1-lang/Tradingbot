"""
Trading Bot Optimization Engine
Tests multiple parameter combinations to find the most profitable configuration
"""

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
import subprocess
import sys


class OptimizationEngine:
    """Runs backtests with different parameter combinations"""
    
    def __init__(self, output_dir: str = "optimization_results"):
        """Initialize optimization engine"""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger(__name__)
        self.results: List[Dict] = []
        
        # Parameter combinations to test
        self.atr_periods = [10, 14, 20, 30]
        self.risk_ratios = [1.0, 1.5, 2.0, 3.0]
        self.entry_filters = [
            {"adx_min": 0, "rsi_min": 0, "rsi_max": 100, "name": "NO_FILTER"},
            {"adx_min": 25, "rsi_min": 30, "rsi_max": 70, "name": "STRICT_FILTER"}
        ]
    
    def generate_test_params(self) -> List[Dict]:
        """Generate all parameter combinations to test"""
        test_configs = []
        
        for atr in self.atr_periods:
            for ratio in self.risk_ratios:
                for filter_config in self.entry_filters:
                    config = {
                        'atr_period': atr,
                        'risk_reward_ratio': ratio,
                        'entry_filter': filter_config,
                        'name': f"ATR{atr}_RR{ratio}_{filter_config['name']}"
                    }
                    test_configs.append(config)
        
        return test_configs
    
    def save_config(self, config: Dict, filename: str) -> str:
        """Save config to file for backtest to use"""
        config_file = self.output_dir / filename
        with open(config_file, 'w') as f:
            json.dump(config, f, indent=2)
        return str(config_file)
    
    def run_backtest_with_config(self, config: Dict) -> Dict:
        """Run single backtest with given config"""
        config_name = config.get('name', 'unknown')
        print(f"\n[TEST] Testing: {config_name}")
        print(f"   ATR Period: {config['atr_period']}")
        print(f"   Risk:Reward: {config['risk_reward_ratio']}")
        print(f"   Entry Filter: {config['entry_filter']['name']}")
        print("   Running backtest...", end=" ", flush=True)
        
        # Save config
        config_file = self.save_config(config, f"{config_name}_config.json")
        
        # Run backtest
        try:
            result = subprocess.run(
                [sys.executable, "run_backtest.py"],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Parse results from output
            output = result.stdout + result.stderr
            
            backtest_result = {
                'config': config,
                'config_name': config_name,
                'success': result.returncode == 0,
                'output': output,
                'metrics': self._parse_backtest_output(output)
            }
            
            print("✅ Done")
            return backtest_result
            
        except subprocess.TimeoutExpired:
            print("❌ Timeout")
            return {
                'config': config,
                'config_name': config_name,
                'success': False,
                'output': "Backtest timeout",
                'metrics': {}
            }
        except Exception as e:
            print(f"❌ Error: {e}")
            return {
                'config': config,
                'config_name': config_name,
                'success': False,
                'output': str(e),
                'metrics': {}
            }
    
    def _parse_backtest_output(self, output: str) -> Dict:
        """Extract metrics from backtest output"""
        metrics = {
            'trades': 0,
            'win_rate': 0.0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'profit_factor': 0.0,
            'final_balance': 10000.0
        }
        
        # Simple parsing (adjust regex for your output format)
        import re
        
        patterns = {
            'trades': r'Trades Executed:\s*(\d+)',
            'win_rate': r'Win Rate:\s*([\d.]+)%',
            'total_pnl': r'Total PnL:\s*\$?([-\d.]+)',
            'max_drawdown': r'Max Drawdown:\s*([\d.]+)%',
            'profit_factor': r'Profit Factor:\s*([\d.]+)',
            'final_balance': r'Final Balance:\s*\$?([\d,.]+)'
        }
        
        for key, pattern in patterns.items():
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                try:
                    value = match.group(1)
                    if key == 'final_balance':
                        value = float(value.replace(',', ''))
                    elif key in ['win_rate', 'max_drawdown']:
                        value = float(value.rstrip('%'))
                    else:
                        value = float(value)
                    metrics[key] = value
                except:
                    pass
        
        return metrics
    
    async def optimize(self) -> List[Dict]:
        """Run optimization across all parameter combinations"""
        configs = self.generate_test_params()
        
        print("\n" + "="*60)
        print("   TRADING BOT OPTIMIZATION ENGINE")
        print("="*60)
        print(f"\nTesting {len(configs)} parameter combinations...")
        print("This may take several minutes...\n")
        
        for i, config in enumerate(configs, 1):
            print(f"[{i}/{len(configs)}]", end=" ")
            result = self.run_backtest_with_config(config)
            self.results.append(result)
        
        return self.results
    
    def analyze_results(self) -> Dict:
        """Analyze optimization results and find best parameters"""
        if not self.results:
            return {}
        
        # Filter successful backtests
        successful = [r for r in self.results if r['success'] and r['metrics']]
        
        if not successful:
            print("❌ No successful backtests")
            return {}
        
        # Sort by profit factor (best metric for trading)
        sorted_by_profit = sorted(
            successful,
            key=lambda x: x['metrics'].get('profit_factor', 0),
            reverse=True
        )
        
        # Top 5 configurations
        top_5 = sorted_by_profit[:5]
        
        analysis = {
            'total_tested': len(self.results),
            'successful': len(successful),
            'failed': len(self.results) - len(successful),
            'best_by_profit_factor': top_5[0] if top_5 else None,
            'top_5_configs': top_5,
            'summary_stats': {
                'avg_pnl': sum(r['metrics'].get('total_pnl', 0) for r in successful) / len(successful),
                'avg_win_rate': sum(r['metrics'].get('win_rate', 0) for r in successful) / len(successful),
                'max_pnl': max(r['metrics'].get('total_pnl', 0) for r in successful),
                'min_pnl': min(r['metrics'].get('total_pnl', 0) for r in successful),
            }
        }
        
        return analysis
    
    def generate_report(self, analysis: Dict) -> str:
        """Generate optimization report"""
        report = []
        report.append("\n" + "="*70)
        report.append("   OPTIMIZATION RESULTS SUMMARY")
        report.append("="*70)
        
        report.append(f"\nTests Run: {analysis.get('total_tested', 0)}")
        report.append(f"Successful: {analysis.get('successful', 0)}")
        report.append(f"Failed: {analysis.get('failed', 0)}")
        
        stats = analysis.get('summary_stats', {})
        report.append(f"\nAverage Metrics Across All Tests:")
        report.append(f"  Average PnL: ${stats.get('avg_pnl', 0):.2f}")
        report.append(f"  Average Win Rate: {stats.get('avg_win_rate', 0):.1f}%")
        report.append(f"  Best PnL: ${stats.get('max_pnl', 0):.2f}")
        report.append(f"  Worst PnL: ${stats.get('min_pnl', 0):.2f}")
        
        best = analysis.get('best_by_profit_factor', {})
        if best:
            config = best.get('config', {})
            metrics = best.get('metrics', {})
            report.append(f"\n🏆 BEST CONFIGURATION:")
            report.append(f"  Name: {best.get('config_name', 'N/A')}")
            report.append(f"  ATR Period: {config.get('atr_period', 'N/A')}")
            report.append(f"  Risk:Reward Ratio: {config.get('risk_reward_ratio', 'N/A')}")
            report.append(f"  Entry Filter: {config.get('entry_filter', {}).get('name', 'N/A')}")
            report.append(f"\n  Results:")
            report.append(f"    Trades: {metrics.get('trades', 0)}")
            report.append(f"    Win Rate: {metrics.get('win_rate', 0):.1f}%")
            report.append(f"    Total PnL: ${metrics.get('total_pnl', 0):.2f}")
            report.append(f"    Profit Factor: {metrics.get('profit_factor', 0):.2f}")
            report.append(f"    Max Drawdown: {metrics.get('max_drawdown', 0):.1f}%")
            report.append(f"    Final Balance: ${metrics.get('final_balance', 0):.2f}")
        
        report.append(f"\n📊 TOP 5 CONFIGURATIONS:")
        for i, result in enumerate(analysis.get('top_5_configs', []), 1):
            config = result.get('config', {})
            metrics = result.get('metrics', {})
            report.append(f"\n  {i}. {result.get('config_name', 'N/A')}")
            report.append(f"     Profit Factor: {metrics.get('profit_factor', 0):.2f}")
            report.append(f"     PnL: ${metrics.get('total_pnl', 0):.2f} | Win Rate: {metrics.get('win_rate', 0):.1f}%")
        
        report.append("\n" + "="*70)
        
        return "\n".join(report)
    
    def save_results(self, analysis: Dict, report: str):
        """Save results to files"""
        # Save detailed results as JSON
        results_file = self.output_dir / "optimization_results.json"
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        # Save analysis
        analysis_file = self.output_dir / "optimization_analysis.json"
        with open(analysis_file, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        
        # Save report
        report_file = self.output_dir / "OPTIMIZATION_REPORT.txt"
        with open(report_file, 'w') as f:
            f.write(report)
        
        print(f"\n✅ Results saved to {self.output_dir}/")
        print(f"   - optimization_results.json")
        print(f"   - optimization_analysis.json")
        print(f"   - OPTIMIZATION_REPORT.txt")
        
        return str(results_file), str(analysis_file), str(report_file)


async def main():
    """Main optimization entry point"""
    logging.basicConfig(level=logging.INFO)
    
    engine = OptimizationEngine()
    
    # Run optimization
    results = await engine.optimize()
    
    # Analyze results
    analysis = engine.analyze_results()
    
    # Generate report
    report = engine.generate_report(analysis)
    print(report)
    
    # Save results
    engine.save_results(analysis, report)
    
    # Display best configuration to use
    best = analysis.get('best_by_profit_factor', {})
    if best:
        config = best.get('config', {})
        print("\n" + "="*70)
        print("   RECOMMENDED CONFIGURATION FOR LIVE TRADING")
        print("="*70)
        print(f"\nUpdate main.py with these parameters:\n")
        print(f"sl_tp_calculator = StopLossTakeProfitCalculator(")
        print(f"    atr_period={config.get('atr_period', 14)},")
        print(f"    risk_reward_ratio={config.get('risk_reward_ratio', 1.5)}")
        print(f")")
        print("\n" + "="*70)


if __name__ == "__main__":
    asyncio.run(main())

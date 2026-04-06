"""
Simplified Optimization Runner - No Emoji Version
Tests parameter combinations and saves results
"""

import asyncio
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


class SimpleOptimizer:
    """Simple optimization engine without encoding issues"""
    
    def __init__(self, output_dir: str = "optimization_results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Test configurations
        self.configs = self._generate_configs()
        self.results = []
    
    def _generate_configs(self) -> List[Dict]:
        """Generate all test configurations"""
        configs = []
        atr_periods = [10, 14, 20, 30]
        risk_ratios = [1.0, 1.5, 2.0]
        
        for atr in atr_periods:
            for ratio in risk_ratios:
                config = {
                    'atr_period': atr,
                    'risk_reward_ratio': ratio,
                    'name': f"ATR{atr}_RR{ratio}"
                }
                configs.append(config)
        
        return configs
    
    def run_backtest(self, config: Dict) -> Dict:
        """Run a single backtest"""
        config_name = config['name']
        print(f"[{len(self.results)+1}/{len(self.configs)}] Testing: {config_name}...", end=" ", flush=True)
        
        try:
            # Create a temporary config file for this backtest
            import json
            config_file = f"temp_backtest_config_{config_name}.json"
            with open(config_file, 'w') as f:
                json.dump(config, f)
            
            result = subprocess.run(
                [sys.executable, "run_backtest.py", config_file],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=str(Path.cwd())
            )
            
            # Clean up temp file
            try:
                Path(config_file).unlink()
            except:
                pass
            
            output = result.stdout + result.stderr
            metrics = self._parse_metrics(output)
            
            test_result = {
                'config': config,
                'config_name': config_name,
                'success': result.returncode == 0,
                'metrics': metrics,
                'output': output[:500]  # First 500 chars
            }
            
            print(f"OK [PnL: ${metrics.get('total_pnl', 0):.2f}]")
            return test_result
            
        except Exception as e:
            print(f"ERROR: {str(e)[:50]}")
            return {
                'config': config,
                'config_name': config_name,
                'success': False,
                'metrics': {},
                'output': str(e)
            }
    
    def _parse_metrics(self, output: str) -> Dict:
        """Parse backtest output for key metrics"""
        import re
        
        metrics = {
            'trades': 0,
            'win_rate': 0.0,
            'total_pnl': 0.0,
            'max_drawdown': 0.0,
            'profit_factor': 0.0,
            'final_balance': 10000.0
        }
        
        patterns = {
            'trades': r'Trades Executed:\s*(\d+)',
            'win_rate': r'Win Rate:\s*([\d.]+)%',
            'total_pnl': r'Total PnL:\s*\$?([-\d.]+)',
            'max_drawdown': r'Max Drawdown:\s*([\d.]+)%',
            'profit_factor': r'Profit Factor:\s*([\d.]+)',
            'final_balance': r'Final Balance:\s*\$?([\d,.]+)'
        }
        
        for key, pattern in patterns.items():
            try:
                match = re.search(pattern, output, re.IGNORECASE)
                if match:
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
    
    def optimize(self):
        """Run all optimization tests"""
        print("\n" + "="*70)
        print("TRADING BOT OPTIMIZATION ENGINE")
        print("="*70)
        print(f"\nTesting {len(self.configs)} configurations...\n")
        
        for config in self.configs:
            result = self.run_backtest(config)
            self.results.append(result)
        
        return self.results
    
    def analyze(self) -> Dict:
        """Analyze optimization results"""
        successful = [r for r in self.results if r.get('success') and r.get('metrics')]
        
        if not successful:
            return {
                'error': 'No successful backtests',
                'total_tested': len(self.results),
                'successful': 0,
                'failed': len(self.results)
            }
        
        # Sort by profit factor
        sorted_results = sorted(
            successful,
            key=lambda x: x['metrics'].get('profit_factor', 0),
            reverse=True
        )
        
        best = sorted_results[0] if sorted_results else {}
        
        return {
            'total_tested': len(self.results),
            'successful': len(successful),
            'failed': len(self.results) - len(successful),
            'best': best,
            'top_5': sorted_results[:5]
        }
    
    def print_results(self, analysis: Dict):
        """Print analysis results"""
        print("\n" + "="*70)
        print("OPTIMIZATION RESULTS")
        print("="*70)
        
        print(f"\nTests: {analysis.get('total_tested', 0)} | Success: {analysis.get('successful', 0)} | Failed: {analysis.get('failed', 0)}")
        
        if analysis.get('error'):
            print(f"\nError: {analysis['error']}")
            return
        
        best = analysis.get('best', {})
        if best:
            config = best.get('config', {})
            metrics = best.get('metrics', {})
            
            print(f"\nBEST CONFIGURATION:")
            print(f"  Name: {best.get('config_name')}")
            print(f"  ATR Period: {config.get('atr_period')}")
            print(f"  Risk:Reward: {config.get('risk_reward_ratio')}")
            print(f"\n  Metrics:")
            print(f"    Trades: {metrics.get('trades')}")
            print(f"    Win Rate: {metrics.get('win_rate'):.1f}%")
            print(f"    Total PnL: ${metrics.get('total_pnl'):.2f}")
            print(f"    Profit Factor: {metrics.get('profit_factor'):.2f}")
            print(f"    Max Drawdown: {metrics.get('max_drawdown'):.1f}%")
        
        print(f"\nTOP 5 CONFIGURATIONS:")
        for i, result in enumerate(analysis.get('top_5', []), 1):
            config = result.get('config', {})
            metrics = result.get('metrics', {})
            print(f"  {i}. {result.get('config_name')}")
            print(f"     PnL: ${metrics.get('total_pnl'):.2f} | Win: {metrics.get('win_rate'):.1f}% | PF: {metrics.get('profit_factor'):.2f}")
        
        print("\n" + "="*70)
    
    def save_results(self, analysis: Dict):
        """Save results to files"""
        results_file = self.output_dir / "optimization_results.json"
        with open(results_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        analysis_file = self.output_dir / "optimization_analysis.json"
        with open(analysis_file, 'w') as f:
            json.dump(analysis, f, indent=2, default=str)
        
        print(f"\nResults saved to: {self.output_dir}/")
        print(f"  - optimization_results.json")
        print(f"  - optimization_analysis.json")


def main():
    """Main entry point"""
    optimizer = SimpleOptimizer()
    results = optimizer.optimize()
    analysis = optimizer.analyze()
    optimizer.print_results(analysis)
    optimizer.save_results(analysis)


if __name__ == "__main__":
    main()

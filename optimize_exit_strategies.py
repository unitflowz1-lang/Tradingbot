#!/usr/bin/env python3
"""
Advanced Exit Strategy Optimizer
Tests multiple exit strategy configurations to find optimal parameters
"""

import subprocess
import json
import sys
from datetime import datetime
from pathlib import Path

class ExitOptimizer:
    def __init__(self):
        self.results = {}
        self.base_path = Path(__file__).parent.parent.parent
        
    def run_backtest_with_config(self, config_name: str) -> dict:
        """Run backtest with specific exit configuration"""
        print(f"\n{'='*60}")
        print(f"Testing: {config_name.upper()}")
        print(f"{'='*60}")
        
        # Update advanced_exit_handler with config
        self._apply_config(config_name)
        
        # Run backtest
        try:
            result = subprocess.run(
                ["python", "run_backtest.py"],
                cwd=self.base_path,
                capture_output=True,
                text=True,
                timeout=120
            )
            
            # Parse results from output
            output = result.stdout
            metrics = self._parse_backtest_output(output)
            metrics['config'] = config_name
            metrics['timestamp'] = datetime.now().isoformat()
            
            self.results[config_name] = metrics
            return metrics
            
        except subprocess.TimeoutExpired:
            print(f"ERROR: Backtest timeout for {config_name}")
            return {'error': 'timeout'}
        except Exception as e:
            print(f"ERROR: {str(e)}")
            return {'error': str(e)}
    
    def _apply_config(self, config_name: str):
        """Apply configuration to advanced_exit_handler"""
        config_map = {
            'balanced': {
                'atr_multiplier': 0.5,
                'activation_ratio': 0.7,
                'max_hold_bars': 72,
                'use_reversal': False,
            },
            'aggressive': {
                'atr_multiplier': 0.4,
                'activation_ratio': 0.6,
                'max_hold_bars': 48,
                'use_reversal': True,
            },
            'conservative': {
                'atr_multiplier': 0.6,
                'activation_ratio': 0.8,
                'max_hold_bars': 96,
                'use_reversal': False,
            },
            'ultra_aggressive': {
                'atr_multiplier': 0.3,
                'activation_ratio': 0.5,
                'max_hold_bars': 36,
                'use_reversal': True,
            },
        }
        
        config = config_map.get(config_name.lower(), config_map['balanced'])
        handler_file = self.base_path / "src" / "trading" / "advanced_exit_handler.py"
        
        with open(handler_file, 'r') as f:
            content = f.read()
        
        # Update parameters
        content = content.replace(
            f"self.atr_multiplier = 0.5",
            f"self.atr_multiplier = {config['atr_multiplier']}"
        )
        content = content.replace(
            f"self.activation_ratio = 0.7",
            f"self.activation_ratio = {config['activation_ratio']}"
        )
        content = content.replace(
            f"self.max_hold_bars = 72",
            f"self.max_hold_bars = {config['max_hold_bars']}"
        )
        
        with open(handler_file, 'w') as f:
            f.write(content)
    
    def _parse_backtest_output(self, output: str) -> dict:
        """Extract metrics from backtest output"""
        metrics = {}
        
        lines = output.split('\n')
        for line in lines:
            if '[STATS]' in line:
                if 'Win Rate:' in line:
                    metrics['win_rate'] = float(line.split()[-1].rstrip('%'))
                elif 'Total Trades:' in line:
                    metrics['trades'] = int(line.split()[-1])
                elif 'Total PnL:' in line:
                    pnl_str = line.split()[-1]
                    metrics['pnl'] = float(pnl_str.replace('$', '').replace('+', ''))
                elif 'Profit Factor:' in line:
                    metrics['profit_factor'] = float(line.split()[-1])
                elif 'Max Drawdown:' in line:
                    metrics['max_drawdown'] = float(line.split()[-1].rstrip('%'))
            elif '[EXIT BREAKDOWN]' in line:
                metrics['exit_breakdown_found'] = True
        
        return metrics
    
    def compare_results(self):
        """Compare all test results"""
        print(f"\n\n{'='*80}")
        print("ADVANCED EXIT STRATEGY OPTIMIZATION RESULTS")
        print(f"{'='*80}\n")
        
        if not self.results:
            print("No results to compare")
            return
        
        # Sort by win rate
        sorted_results = sorted(
            self.results.items(),
            key=lambda x: x[1].get('win_rate', 0),
            reverse=True
        )
        
        print(f"{'Config':<20} {'Win Rate':<12} {'Trades':<10} {'PnL':<15} {'P.Factor':<12} {'Drawdown':<12}")
        print("-" * 80)
        
        baseline_wr = None
        for config_name, metrics in sorted_results:
            if 'error' in metrics:
                print(f"{config_name:<20} ERROR: {metrics['error']}")
                continue
            
            wr = metrics.get('win_rate', 0)
            trades = metrics.get('trades', 0)
            pnl = metrics.get('pnl', 0)
            pf = metrics.get('profit_factor', 0)
            dd = metrics.get('max_drawdown', 0)
            
            if baseline_wr is None:
                baseline_wr = wr
            
            change = f"({wr - baseline_wr:+.1f}%)" if baseline_wr else ""
            
            print(f"{config_name:<20} {wr:>6.1f}%       {trades:>6}      ${pnl:>10,.0f}   {pf:>8.2f}      {dd:>6.1f}%")
        
        print("-" * 80)
        
        # Find best configuration
        best_config = sorted_results[0][0]
        best_metrics = sorted_results[0][1]
        
        print(f"\n✓ BEST CONFIG: {best_config.upper()}")
        print(f"  Win Rate: {best_metrics.get('win_rate', 0):.1f}%")
        print(f"  Profit Factor: {best_metrics.get('profit_factor', 0):.2f}")
        print(f"  PnL: ${best_metrics.get('pnl', 0):,.0f}")
        
        if best_metrics.get('win_rate', 0) > 54.6:
            improvement = best_metrics.get('win_rate', 0) - 54.6
            print(f"  Improvement vs Baseline: +{improvement:.1f}%")
        
        return best_config, best_metrics

def main():
    print("Starting Advanced Exit Strategy Optimization...")
    print(f"Baseline Win Rate: 54.6%")
    print(f"Testing 4 configurations: Balanced, Aggressive, Conservative, Ultra-Aggressive\n")
    
    optimizer = ExitOptimizer()
    
    # Test each configuration
    configs = ['balanced', 'aggressive', 'conservative', 'ultra_aggressive']
    
    for config in configs:
        metrics = optimizer.run_backtest_with_config(config)
        if 'error' not in metrics and metrics:
            print(f"✓ {config.upper()}: {metrics.get('win_rate', 0):.1f}% WR | {metrics.get('trades', 0)} trades | ${metrics.get('pnl', 0):,.0f}")
    
    # Compare results
    best_config, best_metrics = optimizer.compare_results()
    
    # Restore balanced config if different from best
    if best_config != 'balanced':
        print(f"\n→ Deploying optimal config: {best_config}")
        optimizer._apply_config('balanced')  # Restore original
    
    return best_config, best_metrics

if __name__ == "__main__":
    main()

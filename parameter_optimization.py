#!/usr/bin/env python3
"""
Parameter Optimization Script for Three-Layer Trading System

Performs systematic parameter sweeps to optimize:
1. Entry filter thresholds (ADX, RSI, ML confidence)
2. Exit levels (take-profit, stop-loss, trailing stop)
3. Position sizing (fixed vs equity-based)

Generates comparison report with metrics.
"""

import json
import subprocess
import csv
from typing import Dict, List, Tuple
from dataclasses import dataclass
from pathlib import Path

@dataclass
class OptimizationResult:
    """Stores optimization test results"""
    name: str
    params: Dict
    win_rate: float
    profit_factor: float
    max_drawdown: float
    total_pnl: float
    total_trades: int
    
    def score(self) -> float:
        """Calculate composite optimization score"""
        # Weighted scoring: PF (40%) + WR (30%) + DD (20%) + Trades (10%)
        pf_score = min(self.profit_factor / 3.0, 1.0)  # Normalize to 3.0 max
        wr_score = self.win_rate / 100.0
        dd_score = max(1.0 - self.max_drawdown / 25.0, 0)  # 25% max DD
        trade_score = min(self.total_trades / 2000, 1.0)  # 2000 trades target
        
        return (pf_score * 0.40 + wr_score * 0.30 + dd_score * 0.20 + trade_score * 0.10)

def parse_backtest_output(output: str) -> Dict:
    """Parse backtest statistics from output"""
    stats = {}
    try:
        for line in output.split('\n'):
            if '[STATS]' in line:
                if 'Win Rate:' in line:
                    stats['win_rate'] = float(line.split('Win Rate:')[1].strip().rstrip('%'))
                elif 'Total Trades:' in line:
                    stats['total_trades'] = int(line.split('Total Trades:')[1].strip())
                elif 'Total PnL:' in line:
                    pnl_str = line.split('$')[1].strip()
                    stats['total_pnl'] = float(pnl_str.replace(',', ''))
                elif 'Max Drawdown:' in line:
                    stats['max_drawdown'] = float(line.split('Max Drawdown:')[1].strip().rstrip('%'))
                elif 'Profit Factor:' in line:
                    stats['profit_factor'] = float(line.split('Profit Factor:')[1].strip())
    except Exception as e:
        print(f"Error parsing backtest output: {e}")
    return stats

def run_backtest_with_params(params: Dict) -> Dict:
    """Run backtest with given parameters and return results"""
    # Update config with new parameters
    config_path = Path("config.json.example")
    if config_path.exists():
        with open(config_path) as f:
            config = json.load(f)
        
        # Update entry filters
        if 'entry_filter_adx_min' in params:
            config['adx_min'] = params['entry_filter_adx_min']
        if 'entry_filter_rsi_min' in params:
            config['rsi_min'] = params['entry_filter_rsi_min']
        if 'entry_filter_rsi_max' in params:
            config['rsi_max'] = params['entry_filter_rsi_max']
        if 'entry_filter_ml_confidence' in params:
            config['ml_confidence'] = params['entry_filter_ml_confidence']
        
        # Update exit levels
        if 'tp_pips' in params:
            config['tp_pips'] = params['tp_pips']
        if 'sl_pips' in params:
            config['sl_pips'] = params['sl_pips']
        if 'trailing_stop_pips' in params:
            config['trailing_stop_pips'] = params['trailing_stop_pips']
        
        # Update position sizing
        if 'position_size' in params:
            config['position_size'] = params['position_size']
        
        # Write updated config
        with open("config.json", 'w') as f:
            json.dump(config, f, indent=2)
    
    # Run backtest
    result = subprocess.run(['python', 'run_backtest.py'], 
                          capture_output=True, text=True, timeout=300)
    
    stats = parse_backtest_output(result.stdout + result.stderr)
    return stats

def optimize_entry_filters() -> List[OptimizationResult]:
    """Optimize entry filter thresholds"""
    results = []
    
    # Test different ADX minimums
    adx_values = [6, 8, 10, 12, 15]
    for adx in adx_values:
        print(f"Testing ADX minimum: {adx}")
        params = {'entry_filter_adx_min': adx}
        stats = run_backtest_with_params(params)
        if stats:
            result = OptimizationResult(
                name=f"ADX_min={adx}",
                params=params,
                win_rate=stats.get('win_rate', 0),
                profit_factor=stats.get('profit_factor', 0),
                max_drawdown=stats.get('max_drawdown', 0),
                total_pnl=stats.get('total_pnl', 0),
                total_trades=stats.get('total_trades', 0)
            )
            results.append(result)
            print(f"  Score: {result.score():.4f}")
    
    return results

def optimize_exit_levels() -> List[OptimizationResult]:
    """Optimize exit levels (TP/SL/TS)"""
    results = []
    
    # Test different TP/SL ratios
    tp_configs = [
        {'tp_pips': 30, 'sl_pips': 20},
        {'tp_pips': 40, 'sl_pips': 20},
        {'tp_pips': 50, 'sl_pips': 20},
        {'tp_pips': 50, 'sl_pips': 25},
    ]
    
    for config in tp_configs:
        print(f"Testing TP={config['tp_pips']} SL={config['sl_pips']}")
        params = config
        stats = run_backtest_with_params(params)
        if stats:
            result = OptimizationResult(
                name=f"TP={config['tp_pips']}_SL={config['sl_pips']}",
                params=params,
                win_rate=stats.get('win_rate', 0),
                profit_factor=stats.get('profit_factor', 0),
                max_drawdown=stats.get('max_drawdown', 0),
                total_pnl=stats.get('total_pnl', 0),
                total_trades=stats.get('total_trades', 0)
            )
            results.append(result)
            print(f"  Score: {result.score():.4f}")
    
    return results

def generate_optimization_report(results: List[OptimizationResult]):
    """Generate comparison report of optimization results"""
    # Sort by score descending
    results.sort(key=lambda x: x.score(), reverse=True)
    
    report_path = Path("OPTIMIZATION_RESULTS.csv")
    with open(report_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'Config Name', 'Win Rate %', 'Profit Factor', 'Max Drawdown %', 
            'Total PnL', 'Total Trades', 'Score'
        ])
        for result in results:
            writer.writerow([
                result.name,
                f"{result.win_rate:.1f}",
                f"{result.profit_factor:.2f}",
                f"{result.max_drawdown:.1f}",
                f"${result.total_pnl:,.2f}",
                result.total_trades,
                f"{result.score():.4f}"
            ])
    
    print(f"\n📊 Optimization Report: {report_path}")
    print(f"Top Configuration: {results[0].name}")
    print(f"  Win Rate: {results[0].win_rate:.1f}%")
    print(f"  Profit Factor: {results[0].profit_factor:.2f}")
    print(f"  Max Drawdown: {results[0].max_drawdown:.1f}%")
    print(f"  Score: {results[0].score():.4f}")

def main():
    """Run parameter optimization"""
    print("🚀 Starting Parameter Optimization")
    print("=" * 60)
    
    all_results = []
    
    # Step 1: Optimize entry filters
    print("\n📈 Step 1: Optimizing Entry Filters...")
    entry_results = optimize_entry_filters()
    all_results.extend(entry_results)
    
    # Step 2: Optimize exit levels
    print("\n📊 Step 2: Optimizing Exit Levels...")
    exit_results = optimize_exit_levels()
    all_results.extend(exit_results)
    
    # Generate report
    print("\n" + "=" * 60)
    generate_optimization_report(all_results)
    
    print("\n✅ Parameter optimization complete!")
    print("Review OPTIMIZATION_RESULTS.csv for full details")

if __name__ == "__main__":
    main()

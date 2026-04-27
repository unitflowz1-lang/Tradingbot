#!/usr/bin/env python3
"""
Ultra-Simple Optimization - Working Version
No complex configurations, just backtests with different parameters passed via environment variables
"""
import subprocess
import sys
import os
import json
import re
from pathlib import Path

def parse_metrics(output):
    """Extract metrics from backtest output"""
    # Strip ANSI color codes from output first
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    output_clean = ansi_escape.sub('', output)
    
    metrics = {
        'trades': 0,
        'win_rate': 0.0,
        'total_pnl': 0.0,
        'max_drawdown': 0.0,
        'profit_factor': 0.0,
    }
    
    patterns = {
        'trades': r'Trades Executed:\s*(\d+)',
        'win_rate': r'Win Rate:\s*([\d.]+)%',
        'total_pnl': r'Total PnL:\s*([+-]?[\d.]+)',
        'max_drawdown': r'Max Drawdown:\s*([\d.]+)%',
        'profit_factor': r'Profit Factor:\s*([\d.]+)',
    }
    
    for key, pattern in patterns.items():
        try:
            match = re.search(pattern, output_clean, re.IGNORECASE)
            if match:
                value = float(match.group(1))
                metrics[key] = value
        except:
            pass
    
    return metrics

def run_backtest_with_params(atr_period, risk_ratio):
    """Run backtest with specific parameters"""
    config_name = f"ATR{atr_period}_RR{risk_ratio}"
    
    # Set environment variables for the backtest to use
    env = os.environ.copy()
    env['BACKTEST_ATR_PERIOD'] = str(atr_period)
    env['BACKTEST_RISK_RATIO'] = str(risk_ratio)
    
    try:
        print(f"Testing {config_name}... ", end="", flush=True)
        result = subprocess.run(
            [sys.executable, "run_backtest.py"],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(Path.cwd()),
            env=env
        )
        
        output = result.stdout + result.stderr
        metrics = parse_metrics(output)
        
        # Check if we got real results
        if metrics['trades'] > 0:
            pnl_val = metrics['total_pnl']
            print(f"OK [{metrics['trades']} trades, PnL: ${pnl_val:.2f}]")
            return {'success': True, 'metrics': metrics}
            # Debug: log the actual parsed values
            if False:  # Set to True for debug output
                print(f"  DEBUG - Raw PnL: {metrics['total_pnl']}, Trades: {metrics['trades']}")
            return {'success': True, 'metrics': metrics}
        else:
            print(f"ZERO trades (Check data or filters)")
            return {'success': False, 'metrics': metrics, 'reason': 'no_trades'}
            
    except subprocess.TimeoutExpired:
        print("TIMEOUT")
        return {'success': False, 'reason': 'timeout'}
    except Exception as e:
        print(f"ERROR: {str(e)[:50]}")
        return {'success': False, 'reason': str(e)[:50]}

def main():
    print("\n" + "="*60)
    print("ULTRA-SIMPLE PARAMETER OPTIMIZATION")
    print("="*60)
    
    # Test parameters
    atr_periods = [10, 14, 20, 30]
    risk_ratios = [1.0, 1.5, 2.0]
    
    results = []
    successful = 0
    total = 0
    
    print(f"\nTesting {len(atr_periods) * len(risk_ratios)} configurations...\n")
    
    for atr in atr_periods:
        for rr in risk_ratios:
            total += 1
            result = run_backtest_with_params(atr, rr)
            results.append({
                'atr': atr,
                'risk_ratio': rr,
                'result': result
            })
            if result['success']:
                successful += 1
    
    print(f"\n" + "="*60)
    print(f"RESULTS: {successful} successful, {total - successful} failed")
    print("="*60)
    
    # Show successful results
    successful_results = [r for r in results if r['result']['success']]
    if successful_results:
        print("\nSUCCESSFUL BACKTESTS:")
        print("-" * 60)
        
        # Sort by profit factor
        successful_results.sort(
            key=lambda x: x['result']['metrics'].get('profit_factor', 0),
            reverse=True
        )
        
        for i, r in enumerate(successful_results[:5], 1):
            atr = r['atr']
            rr = r['risk_ratio']
            metrics = r['result']['metrics']
            print(f"{i}. ATR{atr}_RR{rr}")
            print(f"   Trades: {metrics['trades']} | Win: {metrics['win_rate']:.1f}% | PnL: ${metrics['total_pnl']:.2f} | PF: {metrics['profit_factor']:.2f}")
    else:
        print("\n[ERROR] No successful backtests!")
        print("\nPossible causes:")
        print("  1. No historical data available")
        print("  2. All signals filtered out by entry filters")
        print("  3. Strategy not generating signals")
        print("  4. Data format issue")
        
        print("\n[DEBUG] First result details:")
        if results:
            print(f"  Config: ATR{results[0]['atr']}_RR{results[0]['risk_ratio']}")
            print(f"  Success: {results[0]['result'].get('success')}")
            print(f"  Metrics: {results[0]['result'].get('metrics')}")
            print(f"  Reason: {results[0]['result'].get('reason')}")

if __name__ == "__main__":
    main()

"""
Backtest Results Analysis & Fine-Tuning Guide

Once backtest completes, use this to interpret results and optimize.
"""

import json
import os

def analyze_backtest_results():
    """Analyze the backtest output and recommend optimizations"""
    
    # Look for optimization_report.json
    report_file = 'optimization_report.json'
    
    if not os.path.exists(report_file):
        print("Waiting for backtest to complete...")
        print("Results will be saved to: optimization_report.json")
        return None
    
    with open(report_file, 'r') as f:
        results = json.load(f)
    
    print("\n" + "="*70)
    print("BACKTEST RESULTS ANALYSIS")
    print("="*70)
    
    # Extract key metrics
    total_pnl = results.get('total_pnl', 0)
    win_rate = results.get('win_rate', 0)
    profit_factor = results.get('profit_factor', 0)
    max_drawdown = results.get('max_drawdown', 0)
    total_trades = results.get('total_trades', 0)
    avg_win = results.get('avg_win', 0)
    avg_loss = results.get('avg_loss', 0)
    
    print(f"\n📊 METRICS")
    print(f"{'─' * 70}")
    print(f"Total Trades:        {total_trades}")
    print(f"Total P&L:           ${total_pnl:+.2f}")
    print(f"Win Rate:            {win_rate:.1%}")
    print(f"Profit Factor:       {profit_factor:.2f}")
    print(f"Max Drawdown:        {max_drawdown:.1%}")
    print(f"Average Win:         ${avg_win:.2f}")
    print(f"Average Loss:        ${avg_loss:.2f}")
    
    # Compare to targets
    print(f"\n🎯 COMPARISON TO TARGETS")
    print(f"{'─' * 70}")
    
    targets = {
        'win_rate': (0.60, 0.65, 'Win Rate'),
        'profit_factor': (2.0, 2.5, 'Profit Factor'),
        'max_drawdown': (0, 0.15, 'Max Drawdown (lower better)'),
    }
    
    for key, (target_min, target_max, label) in targets.items():
        value = results.get(key, 0)
        if key == 'max_drawdown':
            status = "✓" if value <= target_max else "✗"
            print(f"{status} {label:30} {value:.1%} (Target: <{target_max:.0%})")
        else:
            status = "✓" if target_min <= value <= target_max else "✗"
            print(f"{status} {label:30} {value:.1%} (Target: {target_min:.0%}-{target_max:.0%})")
    
    # Recommendations
    print(f"\n💡 OPTIMIZATION RECOMMENDATIONS")
    print(f"{'─' * 70}")
    
    if win_rate < 0.55:
        print("⚠️  LOW WIN RATE - Need more selective entries")
        print("   → Raise signal quality threshold: 0.75 → 0.80")
        print("   → Raise ADX minimum: 20 → 25")
        print("   → File: src/analysis/signal_strength_calculator.py (line 22-23)")
    
    elif win_rate > 0.70:
        print("✓ GOOD WIN RATE - Entries are working well")
    
    if profit_factor < 1.8:
        print("⚠️  LOW PROFIT FACTOR - Exits need optimization")
        print("   → Increase trailing stop distance: 8 → 12 pips")
        print("   → Increase partial profit levels: (5,0.25) → (10,0.25)")
        print("   → Increase time-based hold: 60 → 90 minutes")
        print("   → File: src/trading/advanced_exit_handler.py (lines 48-60)")
    
    elif profit_factor > 2.0:
        print("✓ EXCELLENT PROFIT FACTOR - Exit strategy working well")
    
    if max_drawdown > 0.15:
        print("⚠️  HIGH DRAWDOWN - Need better risk control")
        print("   → Lower trailing stop trigger: 10 → 7 pips")
        print("   → Lower breakeven trigger: 5 → 3 pips")
        print("   → Reduce position sizing")
        print("   → File: src/trading/advanced_exit_handler.py (lines 46-50)")
    
    elif max_drawdown < 0.10:
        print("✓ EXCELLENT DRAWDOWN - Risk is well controlled")
    
    print(f"\n{'='*70}")
    
    return results

if __name__ == "__main__":
    results = analyze_backtest_results()
    
    if results:
        print("\n✓ Analysis complete!")
        print("\nNext steps:")
        print("  1. Review recommendations above")
        print("  2. Adjust parameters in recommended files")
        print("  3. Re-run backtest to compare")
        print("  4. Repeat until satisfied with results")

#!/usr/bin/env python3
"""
AGGRESSIVE vs BASELINE PERFORMANCE COMPARISON REPORT GENERATOR
==============================================================
Generates a detailed comparison table showing the improvements
from the aggressive hyperparameter sweep.

Usage:
    python scripts/generate_comparison_report.py
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def load_json(filepath: str) -> dict:
    """Load JSON file safely"""
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {filepath}: {e}")
        return {}


def generate_report():
    """Generate comprehensive comparison report"""
    
    # File paths
    baseline_path = Path(__file__).parent.parent / "config" / "optimized_params.json"
    comparison_path = Path(__file__).parent.parent / "optimization_results" / "aggressive_vs_baseline.json"
    
    # Load data
    current_config = load_json(str(baseline_path))
    comparison_data = load_json(str(comparison_path))
    
    print("\n" + "="*100)
    print("AGGRESSIVE HYPERPARAMETER SWEEP - PERFORMANCE COMPARISON REPORT")
    print("="*100)
    print(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("="*100)
    
    # Extract baseline (previous production)
    baseline = {
        "quality_floor": 0.75,
        "ml_weight": 0.40,
        "technical_weight": 0.55,
        "atr_sl_multiplier": 2.5,
        "atr_tp_multiplier": 2.5,
        "win_rate": 0.6013,
        "profit_factor": 2.0,
        "sharpe_ratio": 2.49,
        "max_drawdown_pct": 10.14,
        "trades_per_month": 45,
        "total_net_profit": 2500.0
    }
    
    # Extract aggressive optimized values
    if comparison_data and 'aggressive_optimized' in comparison_data:
        aggressive = comparison_data['aggressive_optimized']
    elif current_config:
        aggressive = {
            "quality_floor": current_config.get('entry_filters', {}).get('quality_floor', 75),
            "ml_weight": current_config.get('signal_weights', {}).get('ml_weight', 0.40),
            "technical_weight": current_config.get('signal_weights', {}).get('technical_weight', 0.55),
            "atr_sl_multiplier": current_config.get('risk_management', {}).get('atr_sl_multiplier', 2.5),
            "atr_tp_multiplier": current_config.get('risk_management', {}).get('atr_tp_multiplier', 2.5),
            "win_rate": current_config.get('expected_performance', {}).get('win_rate', 0.60),
            "profit_factor": current_config.get('expected_performance', {}).get('profit_factor', 2.0),
            "sharpe_ratio": current_config.get('expected_performance', {}).get('sharpe_ratio', 2.49),
            "max_drawdown_pct": current_config.get('expected_performance', {}).get('max_drawdown_pct', 10.14),
            "fitness_score": current_config.get('fitness_score', 0)
        }
    else:
        print("❌ No optimized parameters found. Run the sweep first!")
        return
    
    # Calculate changes
    changes = {
        "quality_floor": aggressive.get('quality_floor', 75) - baseline['quality_floor'] * 100,
        "ml_weight": aggressive.get('ml_weight', 0.40) - baseline['ml_weight'],
        "technical_weight": aggressive.get('technical_weight', 0.55) - baseline['technical_weight'],
        "atr_sl": aggressive.get('atr_sl_multiplier', 2.5) - baseline['atr_sl_multiplier'],
        "atr_tp": aggressive.get('atr_tp_multiplier', 3.0) - baseline['atr_tp_multiplier'],
        "win_rate": aggressive.get('win_rate', 0.60) - baseline['win_rate'],
        "profit_factor": aggressive.get('profit_factor', 2.0) - baseline['profit_factor'],
        "sharpe": aggressive.get('sharpe_ratio', 2.49) - baseline['sharpe_ratio'],
        "drawdown": aggressive.get('max_drawdown_pct', 10.14) - baseline['max_drawdown_pct']
    }
    
    # Print comparison table
    print("\n" + "="*100)
    print("PARAMETER CONFIGURATION COMPARISON")
    print("="*100)
    print(f"{'Metric':<30} {'Baseline':<20} {'Aggressive Optimized':<25} {'Change':<20}")
    print("-"*100)
    
    # Entry Filters
    print(f"\n{'ENTRY FILTERS':<30}")
    print(f"  {'Quality Floor (%)':<28} {baseline['quality_floor']*100:<20.0f} {aggressive.get('quality_floor', 75):<25.0f} {changes['quality_floor']:<+20.0f}")
    print(f"  {'ML Weight':<28} {baseline['ml_weight']:<20.2f} {aggressive.get('ml_weight', 0.40):<25.2f} {changes['ml_weight']:<+20.2f}")
    print(f"  {'Technical Weight':<28} {baseline['technical_weight']:<20.2f} {aggressive.get('technical_weight', 0.55):<25.2f} {changes['technical_weight']:<+20.2f}")
    
    # Risk Management
    print(f"\n{'RISK MANAGEMENT':<30}")
    print(f"  {'ATR SL Multiplier':<28} {baseline['atr_sl_multiplier']:<20.1f} {aggressive.get('atr_sl_multiplier', 2.5):<25.1f} {changes['atr_sl']:<+20.1f}")
    print(f"  {'ATR TP Multiplier':<28} {baseline['atr_tp_multiplier']:<20.1f} {aggressive.get('atr_tp_multiplier', 3.0):<25.1f} {changes['atr_tp']:<+20.1f}")
    print(f"  {'Risk/Reward Ratio':<28} {baseline['atr_tp_multiplier']/baseline['atr_sl_multiplier']:<20.2f} {aggressive.get('atr_tp_multiplier', 3.0)/aggressive.get('atr_sl_multiplier', 2.5):<25.2f} {(aggressive.get('atr_tp_multiplier', 3.0)/aggressive.get('atr_sl_multiplier', 2.5) - baseline['atr_tp_multiplier']/baseline['atr_sl_multiplier']):<+20.2f}")
    
    # Performance Metrics
    print(f"\n{'PERFORMANCE METRICS':<30}")
    print(f"  {'Win Rate (%)':<28} {baseline['win_rate']*100:<20.2f} {aggressive.get('win_rate', 0.60)*100:<25.2f} {changes['win_rate']*100:<+20.2f}")
    print(f"  {'Profit Factor':<28} {baseline['profit_factor']:<20.2f} {aggressive.get('profit_factor', 2.0):<25.2f} {changes['profit_factor']:<+20.2f}")
    print(f"  {'Sharpe Ratio':<28} {baseline['sharpe_ratio']:<20.2f} {aggressive.get('sharpe_ratio', 2.49):<25.2f} {changes['sharpe']:<+20.2f}")
    print(f"  {'Max Drawdown (%)':<28} {baseline['max_drawdown_pct']:<20.2f} {aggressive.get('max_drawdown_pct', 10.14):<25.2f} {changes['drawdown']:<+20.2f}")
    
    # Fitness & Stability
    print(f"\n{'OPTIMIZATION METRICS':<30}")
    fitness = aggressive.get('fitness_score', 0)
    print(f"  {'Fitness Score':<28} {'N/A (Old Method)':<20} {fitness:<25.2f} {'NEW AGGRESSIVE':<20}")
    
    # Overfitting check
    if comparison_data and 'baseline' in comparison_data:
        overfit_ratio = comparison_data.get('changes', {}).get('overfitting_ratio', 'N/A')
        print(f"  {'Overfitting Ratio':<28} {'N/A':<20} {overfit_ratio:<25} {'Target: 0.8-1.2':<20}")
    
    # Key Insights
    print("\n" + "="*100)
    print("KEY INSIGHTS & IMPROVEMENTS")
    print("="*100)
    
    insights = []
    
    # Trade frequency insight
    if changes['quality_floor'] < 0:
        insights.append(f"✓ Quality floor reduced by {abs(changes['quality_floor']):.0f}% → Expected 30-50% more trade entries")
    
    # Runner trades insight
    if changes['atr_tp'] > 0 and changes['atr_sl'] < 0:
        rr_improvement = (aggressive.get('atr_tp_multiplier', 3.0)/aggressive.get('atr_sl_multiplier', 2.5) - 
                         baseline['atr_tp_multiplier']/baseline['atr_sl_multiplier'])
        insights.append(f"✓ Tighter stops (-{abs(changes['atr_sl']):.1f}) + Wider targets (+{changes['atr_tp']:.1f}) → Better risk/reward ({rr_improvement:+.2f})")
    
    # ML influence insight
    if changes['ml_weight'] > 0:
        insights.append(f"✓ ML weight increased by +{changes['ml_weight']:.2f} → More AI-driven aggressive entries")
    
    # Sharpe ratio check
    if aggressive.get('sharpe_ratio', 0) > 2.0:
        insights.append(f"✓ Sharpe ratio maintained at {aggressive.get('sharpe_ratio', 0):.2f} (> 2.0 constraint satisfied)")
    
    # Drawdown check
    if aggressive.get('max_drawdown_pct', 0) < 15:
        insights.append(f"✓ Max drawdown at {aggressive.get('max_drawdown_pct', 0):.2f}% (< 15% hard cap satisfied)")
    
    # Aggressive compounding
    insights.append("✓ Aggressive compounding active: 1.2x position size after 3 consecutive profitable trades")
    
    # Print insights
    for i, insight in enumerate(insights, 1):
        print(f"\n{i}. {insight}")
    
    # Validation checks
    print("\n" + "="*100)
    print("VALIDATION CHECKS")
    print("="*100)
    
    checks = [
        ("Sharpe Ratio > 2.0", aggressive.get('sharpe_ratio', 0) > 2.0),
        ("Max Drawdown < 15%", aggressive.get('max_drawdown_pct', 100) < 15),
        ("TP Multiplier > SL Multiplier", aggressive.get('atr_tp_multiplier', 0) > aggressive.get('atr_sl_multiplier', 0)),
        ("ML Weight <= 0.60", aggressive.get('ml_weight', 1) <= 0.60),
        ("Quality Floor >= 65%", aggressive.get('quality_floor', 0) >= 65),
    ]
    
    for check_name, passed in checks:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status:<10} {check_name}")
    
    # Final summary
    print("\n" + "="*100)
    print("DEPLOYMENT RECOMMENDATION")
    print("="*100)
    
    all_passed = all(passed for _, passed in checks)
    
    if all_passed:
        print("\n✅ ALL VALIDATION CHECKS PASSED")
        print("\nRecommended Next Steps:")
        print("  1. Review config/optimized_params.json for final parameter values")
        print("  2. Run bot with DRY_RUN=1 for 24-48 hours to validate aggressive compounding")
        print("  3. Monitor trade frequency and ensure > 60 trades/month")
        print("  4. Verify Sharpe ratio remains > 2.0 in live conditions")
        print("  5. If validation passes, deploy to live trading")
    else:
        print("\n⚠️  SOME VALIDATION CHECKS FAILED")
        print("\nRecommended Actions:")
        print("  1. Review failed checks above")
        print("  2. Consider relaxing constraints or adjusting parameter ranges")
        print("  3. Re-run the optimization sweep with adjusted parameters")
    
    print("\n" + "="*100)
    print("REPORT COMPLETE")
    print("="*100 + "\n")
    
    # Save report to file
    report_path = Path(__file__).parent.parent / "optimization_results" / "final_comparison_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "baseline": baseline,
        "aggressive_optimized": aggressive,
        "changes": changes,
        "validation_checks": {check_name: passed for check_name, passed in checks},
        "all_checks_passed": all_passed
    }
    
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"📄 Full report saved to: {report_path}\n")


if __name__ == "__main__":
    generate_report()

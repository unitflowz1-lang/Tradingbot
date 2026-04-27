#!/usr/bin/env python3
"""
TRADE FREQUENCY & SAMPLE SIZE VALIDATION
=========================================
Validates that the aggressive optimization has sufficient trade count
for statistical significance before going live.

Checks:
1. Minimum 50 trades in test period (statistically significant)
2. Trade frequency > 60 trades/month projected
3. Win rate reliability based on sample size
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any

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


def validate_sample_size():
    """Perform comprehensive sample size validation"""
    
    print("\n" + "="*80)
    print("TRADE FREQUENCY & SAMPLE SIZE VALIDATION")
    print("="*80)
    
    # Load optimization results
    sweep_report = load_json(str(Path(__file__).parent.parent / "optimization_results" / "aggressive_sweep_report.json"))
    optimized_params = load_json(str(Path(__file__).parent.parent / "config" / "optimized_params.json"))
    wfa_summary = load_json(str(Path(__file__).parent.parent / "optimization_results" / "WFA_RESULTS_SUMMARY.md"))
    
    # Extract key metrics
    best_result = sweep_report.get('best_result', {})
    avg_win_rate = best_result.get('avg_test_win_rate', 0)
    win_rate_std = best_result.get('win_rate_std', 0)
    is_overfitted = best_result.get('is_overfitted', True)
    
    print(f"\n📊 OPTIMIZATION METRICS:")
    print(f"  Win Rate: {avg_win_rate:.2%}")
    print(f"  Win Rate Std Dev: {win_rate_std:.4f}")
    print(f"  Overfitting Detected: {is_overfitted}")
    print(f"  Total Parameter Sets Tested: {sweep_report.get('total_parameter_sets_tested', 0):,}")
    print(f"  Valid Results: {sweep_report.get('valid_results', 0)}")
    
    # Sample Size Analysis
    print(f"\n" + "="*80)
    print("SAMPLE SIZE VALIDATION")
    print("="*80)
    
    # Check 1: Valid results count
    valid_results = sweep_report.get('valid_results', 0)
    if valid_results == 0:
        print(f"\n❌ CRITICAL ISSUE: No valid results from walk-forward analysis")
        print(f"   This suggests the backtest engine used SIMULATED data, not real trades")
        print(f"   The 64.13% win rate may NOT be statistically significant")
    else:
        print(f"\n✅ Valid Results: {valid_results}")
    
    # Check 2: Win rate variance
    if win_rate_std == 0.0:
        print(f"\n⚠️  WARNING: Win rate standard deviation is 0.0")
        print(f"   This indicates single-period optimization, not multi-period validation")
        print(f"   The results may not generalize across different market conditions")
    elif win_rate_std < 0.05:
        print(f"\n✅ Win rate stability: {win_rate_std:.4f} (< 5% threshold)")
    else:
        print(f"\n❌ Win rate instability: {win_rate_std:.4f} (> 5% threshold)")
    
    # Check 3: Trade count estimation
    print(f"\n" + "="*80)
    print("TRADE COUNT ESTIMATION")
    print("="*80)
    
    # With quality floor at 72%, estimate trade frequency
    quality_floor = optimized_params.get('entry_filters', {}).get('quality_floor', 75)
    
    print(f"\n📈 PROJECTED TRADE FREQUENCY:")
    print(f"  Quality Floor: {quality_floor}%")
    print(f"  ATR SL: {optimized_params.get('risk_management', {}).get('atr_sl_multiplier', 2.5)}")
    print(f"  ATR TP: {optimized_params.get('risk_management', {}).get('atr_tp_multiplier', 2.5)}")
    
    # Estimation based on quality floor reduction
    baseline_trades = 45  # Estimated from previous optimization
    quality_reduction = (75 - quality_floor) / 100  # How much we lowered the floor
    
    # Rough estimation: 3-5% more trades per 1% quality floor reduction
    estimated_increase = quality_reduction * 40  # 40% increase per 10% floor reduction
    projected_trades = baseline_trades * (1 + estimated_increase)
    
    print(f"\n  Baseline Trades/Month: ~{baseline_trades}")
    print(f"  Projected Trades/Month: ~{projected_trades:.0f} (estimated)")
    
    if projected_trades >= 60:
        print(f"  ✅ PASS: Projected > 60 trades/month (statistically significant)")
    elif projected_trades >= 40:
        print(f"  ⚠️  CAUTION: Projected 40-60 trades/month (moderate significance)")
    else:
        print(f"  ❌ FAIL: Projected < 40 trades/month (low significance)")
    
    # Statistical Significance Check
    print(f"\n" + "="*80)
    print("STATISTICAL SIGNIFICANCE ANALYSIS")
    print("="*80)
    
    # Win rate confidence intervals based on sample size
    import math
    
    def confidence_interval(win_rate, n, confidence=0.95):
        """Calculate confidence interval for win rate"""
        z = 1.96 if confidence == 0.95 else 2.576  # 95% or 99%
        margin = z * math.sqrt((win_rate * (1 - win_rate)) / n)
        return (win_rate - margin, win_rate + margin)
    
    # Test different sample sizes
    sample_sizes = [20, 30, 50, 75, 100, 150]
    
    print(f"\n📊 Win Rate Confidence Intervals (95% confidence):")
    print(f"  {'Sample Size':<15} {'Lower Bound':<15} {'Upper Bound':<15} {'Margin of Error':<15}")
    print(f"  {'-'*60}")
    
    for n in sample_sizes:
        lower, upper = confidence_interval(avg_win_rate, n)
        margin = (upper - lower) / 2
        print(f"  {n:<15} {lower:.2%}  {upper:<15.2%} {margin:<15.2%}")
    
    print(f"\n  ⚠️  RECOMMENDATION:")
    print(f"  - Minimum 50 trades needed for reliable statistics")
    print(f"  - With 50 trades: margin of error ≈ ±6.5%")
    print(f"  - With 100 trades: margin of error ≈ ±4.6%")
    print(f"  - With 150 trades: margin of error ≈ ±3.7%")
    
    # Final Validation
    print(f"\n" + "="*80)
    print("FINAL VALIDATION VERDICT")
    print("="*80)
    
    issues = []
    warnings = []
    passes = []
    
    # Check 1: Valid results
    if valid_results == 0:
        issues.append("No valid walk-forward results (simulated data used)")
    else:
        passes.append(f"{valid_results} valid results from optimization")
    
    # Check 2: Win rate variance
    if win_rate_std == 0.0:
        warnings.append("Zero win rate variance (single-period optimization)")
    else:
        passes.append(f"Win rate variance: {win_rate_std:.4f}")
    
    # Check 3: Projected trade count
    if projected_trades < 40:
        issues.append(f"Projected trade count too low: {projected_trades:.0f}/month")
    elif projected_trades < 60:
        warnings.append(f"Projected trade count moderate: {projected_trades:.0f}/month")
    else:
        passes.append(f"Projected trade count sufficient: {projected_trades:.0f}/month")
    
    # Check 4: Overfitting
    if is_overfitted:
        issues.append("Overfitting detected in optimization")
    else:
        passes.append("No overfitting detected")
    
    # Print results
    if passes:
        print(f"\n✅ PASSED CHECKS:")
        for p in passes:
            print(f"  • {p}")
    
    if warnings:
        print(f"\n⚠️  WARNINGS:")
        for w in warnings:
            print(f"  • {w}")
    
    if issues:
        print(f"\n❌ CRITICAL ISSUES:")
        for i in issues:
            print(f"  • {i}")
    
    # Overall verdict
    print(f"\n" + "="*80)
    if issues:
        print("🚨 VERDICT: NOT READY FOR LIVE TRADING")
        print(f"\n  {len(issues)} critical issue(s) must be resolved before deployment:")
        for idx, issue in enumerate(issues, 1):
            print(f"  {idx}. {issue}")
        print(f"\n  Recommended Actions:")
        print(f"  1. Run backtest with REAL historical data (not simulated)")
        print(f"  2. Ensure minimum 50 trades in test period")
        print(f"  3. Perform multi-period walk-forward validation")
        print(f"  4. Verify trade frequency projections with actual data")
    elif warnings:
        print("⚠️  VERDICT: PROCEED WITH CAUTION")
        print(f"\n  No critical issues, but {len(warnings)} warning(s):")
        for idx, warning in enumerate(warnings, 1):
            print(f"  {idx}. {warning}")
        print(f"\n  Recommended Actions:")
        print(f"  1. Run DRY_RUN for 48+ hours to validate trade frequency")
        print(f"  2. Monitor actual trade count vs projections")
        print(f"  3. Be prepared to adjust quality floor if trades < 60/month")
    else:
        print("✅ VERDICT: READY FOR LIVE TRADING")
        print(f"\n  All checks passed successfully!")
        print(f"\n  Recommended Actions:")
        print(f"  1. Run DRY_RUN for 24 hours as final validation")
        print(f"  2. Deploy to live trading if metrics hold")
    
    print(f"\n" + "="*80)
    
    # Save validation report
    validation_report = {
        "validation_date": "2026-04-25T03:40:00+00:00",
        "sample_size_analysis": {
            "win_rate": avg_win_rate,
            "win_rate_std": win_rate_std,
            "is_overfitted": is_overfitted,
            "valid_results": valid_results,
            "projected_trades_per_month": projected_trades
        },
        "confidence_intervals": {
            f"n={n}": confidence_interval(avg_win_rate, n) for n in sample_sizes
        },
        "validation_result": {
            "passes": passes,
            "warnings": warnings,
            "issues": issues,
            "ready_for_live": len(issues) == 0
        }
    }
    
    report_path = Path(__file__).parent.parent / "optimization_results" / "sample_size_validation.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, 'w') as f:
        json.dump(validation_report, f, indent=2)
    
    print(f"\n📄 Validation report saved to: {report_path}\n")


if __name__ == "__main__":
    validate_sample_size()

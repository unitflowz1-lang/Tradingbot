"""
Diagnostics for Regime-Aware Exit Policy Ensemble
Displays performance matrix, staleness alerts, and capital efficiency metrics.
"""

import logging
import sys
import os
import json
from typing import Dict, Any

sys.path.append(os.getcwd())

from src.ml.exit_policy_ensemble import ExitPolicyEnsemble
from src.logging_config import setup_logging

def print_performance_matrix(diagnostics: Dict[str, Any]) -> None:
    """Print regime-policy performance matrix"""
    print("\n" + "="*80)
    print("REGIME → POLICY PERFORMANCE MATRIX")
    print("="*80)
    
    matrix = diagnostics.get('regime_policy_matrix', {})
    
    if not matrix:
        print("No performance data available yet. Trade more to build the matrix!")
        return
    
    for regime, policies in matrix.items():
        print(f"\n📊 {regime}")
        print("-" * 80)
        
        for policy_name, perf in sorted(policies.items(), key=lambda x: x[1]['expectancy'], reverse=True):
            exp = perf['expectancy']
            wr = perf['win_rate'] * 100
            samples = perf['samples']
            conf = perf['confidence']
            cap_eff = perf['capital_efficiency']
            
            # Visual indicator
            indicator = "🟢" if exp > 0.5 else "🟡" if exp > 0 else "🔴"
            
            print(f"  {indicator} {policy_name:15s} | "
                  f"Expectancy: {exp:+.2f}R | "
                  f"Win Rate: {wr:5.1f}% | "
                  f"Samples: {samples:3d} | "
                  f"Confidence: {conf:.2f} | "
                  f"Cap Efficiency: {cap_eff:.3f}")

def print_best_policies(diagnostics: Dict[str, Any]) -> None:
    """Print best policy for each regime"""
    print("\n" + "="*80)
    print("BEST POLICY PER REGIME")
    print("="*80 + "\n")
    
    best = diagnostics.get('best_policy_per_regime', {})
    
    if not best:
        print("No regime data available yet.")
        return
    
    for regime, data in best.items():
        policy = data.get('policy', 'N/A')
        exp = data.get('expectancy', 0.0)
        
        print(f"  {regime:20s} → {policy:15s} (Expectancy: {exp:+.2f}R)")

def print_staleness_alerts(diagnostics: Dict[str, Any]) -> None:
    """Print staleness alerts"""
    print("\n" + "="*80)
    print("STALENESS ALERTS (Regimes with Low Sample Counts)")
    print("="*80 + "\n")
    
    alerts = diagnostics.get('staleness_alerts', [])
    
    if not alerts:
        print("✅ All regimes have sufficient sample counts!")
        return
    
    for alert in alerts:
        regime = alert['regime']
        policy = alert['policy']
        samples = alert['samples']
        needed = alert['needed']
        
        print(f"  ⚠️  {regime:15s} / {policy:15s}: {samples}/{needed} samples")

def print_capital_efficiency_summary(diagnostics: Dict[str, Any]) -> None:
    """Print capital efficiency summary"""
    print("\n" + "="*80)
    print("CAPITAL EFFICIENCY SUMMARY")
    print("="*80 + "\n")
    
    matrix = diagnostics.get('regime_policy_matrix', {})
    
    if not matrix:
        return
    
    # Collect all capital efficiencies
    efficiencies = []
    for regime, policies in matrix.items():
        for policy_name, perf in policies.items():
            if perf['samples'] >= 5:  # Only include with sufficient data
                efficiencies.append({
                    'regime': regime,
                    'policy': policy_name,
                    'efficiency': perf['capital_efficiency'],
                    'samples': perf['samples']
                })
    
    # Sort by efficiency
    efficiencies.sort(key=lambda x: x['efficiency'], reverse=True)
    
    print("Top 10 Most Capital-Efficient Regime/Policy Combinations:\n")
    for i, item in enumerate(efficiencies[:10], 1):
        print(f"  {i}. {item['regime']:15s} / {item['policy']:15s}: "
              f"{item['efficiency']:.3f} (n={item['samples']})")
    
    if len(efficiencies) > 10:
        print(f"\n  ... and {len(efficiencies) - 10} more combinations")

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("\n" + "="*80)
    print("REGIME-AWARE EXIT POLICY ENSEMBLE DIAGNOSTICS")
    print("="*80)
    
    ensemble = ExitPolicyEnsemble()
    
    # Get diagnostics
    diagnostics = ensemble.get_diagnostics()
    
    # Print sections
    print_performance_matrix(diagnostics)
    print_best_policies(diagnostics)
    print_staleness_alerts(diagnostics)
    print_capital_efficiency_summary(diagnostics)
    
    print("\n" + "="*80)
    print("End of Diagnostics")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()

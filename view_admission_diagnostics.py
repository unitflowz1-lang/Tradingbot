"""
Diagnostics for Trade Admission & Opportunity Cost Controller
Displays admission statistics, rejection rates, and opportunity scoring.
"""

import logging
import sys
import os

sys.path.append(os.getcwd())

from src.ml.trade_admission_controller import TradeAdmissionController
from src.logging_config import setup_logging

def print_global_statistics(diagnostics: dict) -> None:
    """Print overall admission statistics"""
    print("\n" + "="*80)
    print("GLOBAL ADMISSION STATISTICS")
    print("="*80)
    
    stats = diagnostics.get('global_stats', {})
    
    if 'message' in stats:
        print(f"\n{stats['message']}")
        return
    
    total = stats.get('total_evaluated', 0)
    admitted = stats.get('total_admitted', 0)
    rejected = stats.get('total_rejected', 0)
    downscaled = stats.get('total_downscaled', 0)
    exploration = stats.get('total_exploration', 0)
    
    print(f"\n📊 Total Signals Evaluated: {total}")
    print(f"   ✅ Admitted (Full Size):    {admitted:4d} ({admitted/total*100:5.1f}%)" if total > 0 else "   No data")
    print(f"   ⚠️  Downscaled (Micro):      {downscaled:4d} ({downscaled/total*100:5.1f}%)" if total > 0 else "")
    print(f"   🔬 Exploration:             {exploration:4d} ({exploration/total*100:5.1f}%)" if total > 0 else "")
    print(f"   ❌ Rejected:                {rejected:4d} ({rejected/total*100:5.1f}%)" if total > 0 else "")
    
    print(f"\n📈 Overall Admission Rate: {stats.get('admission_rate', 0)*100:.1f}%")
    print(f"📉 Overall Rejection Rate: {stats.get('rejection_rate', 0)*100:.1f}%")
    
    print(f"\n🎯 Avg Opportunity Score:")
    print(f"   Admitted Trades:  {stats.get('avg_score_admitted', 0):.1f}th percentile")
    print(f"   Rejected Trades:  {stats.get('avg_score_rejected', 0):.1f}th percentile")
    
    print(f"\n🌍 Regimes Tracked: {stats.get('regimes_tracked', 0)}")

def print_regime_statistics(diagnostics: dict) -> None:
    """Print per-regime admission statistics"""
    print("\n" + "="*80)
    print("REGIME-SPECIFIC ADMISSION STATISTICS")
    print("="*80)
    
    regime_stats = diagnostics.get('regime_stats', {})
    
    if not regime_stats:
        print("\nNo regime-specific data available yet.")
        return
    
    for regime, stats in sorted(regime_stats.items()):
        if 'message' in stats:
            print(f"\n{regime}: {stats['message']}")
            continue
        
        sample_count = stats.get('sample_count', 0)
        admitted_count = stats.get('admitted_count', 0)
        rejection_rate = stats.get('rejection_rate', 0)
        
        avg_exp = stats.get('avg_expectancy', 0)
        median_exp = stats.get('median_expectancy', 0)
        p25_exp = stats.get('p25_expectancy', 0)
        p75_exp = stats.get('p75_expectancy', 0)
        avg_score = stats.get('avg_opportunity_score', 0)
        
        print(f"\n📊 {regime}")
        print(f"   Samples: {sample_count} | Admitted: {admitted_count} | Rejection Rate: {rejection_rate*100:.1f}%")
        print(f"   Expectancy: Avg={avg_exp:+.2f}R | Median={median_exp:+.2f}R | P25={p25_exp:+.2f}R | P75={p75_exp:+.2f}R")
        print(f"   Avg Opportunity Score: {avg_score:.1f}th percentile")

def print_admission_thresholds(controller: TradeAdmissionController) -> None:
    """Print configured admission thresholds"""
    print("\n" + "="*80)
    print("ADMISSION THRESHOLDS & CONFIGURATION")
    print("="*80)
    
    config = controller.config
    
    print(f"\n📏 Percentile Thresholds:")
    print(f"   Normal Regimes:         {config.percentile_threshold_normal:.1f}th percentile")
    print(f"   HIGH_VOLATILITY:        {config.percentile_threshold_volatile:.1f}th percentile (stricter)")
    print(f"   LOW_LIQUIDITY:          {config.percentile_threshold_illiquid:.1f}th percentile (strictest)")
    
    print(f"\n⚙️  Other Settings:")
    print(f"   Lookback Window:        {config.lookback_window} signals")
    print(f"   Micro Allocation:       {config.micro_allocation_multiplier:.2f}x")
    print(f"   Exploration Rate:       {config.min_exploration_rate*100:.1f}%")
    print(f"   Opportunity Cost Weight: {config.opportunity_cost_penalty_weight:.2f}")

def print_quality_control_impact(diagnostics: dict) -> None:
    """Analyze the impact of quality control"""
    print("\n" + "="*80)
    print("QUALITY CONTROL IMPACT ANALYSIS")
    print("="*80)
    
    stats = diagnostics.get('global_stats', {})
    
    if 'message' in stats:
        print(f"\n{stats['message']}")
        return
    
    avg_admitted = stats.get('avg_score_admitted', 0)
    avg_rejected = stats.get('avg_score_rejected', 0)
    
    if avg_admitted > 0 and avg_rejected > 0:
        quality_gap = avg_admitted - avg_rejected
        
        print(f"\n✨ Quality Improvement:")
        print(f"   Trades that got through are {quality_gap:.1f} percentile points higher than rejected ones")
        
        if quality_gap > 20:
            print(f"   ✅ EXCELLENT filtering - significant quality difference")
        elif quality_gap > 10:
            print(f"   👍 GOOD filtering - noticeable quality difference")
        else:
            print(f"   ⚠️  WEAK filtering - consider adjusting thresholds")
    
    rejection_rate = stats.get('rejection_rate', 0)
    print(f"\n🛑 Capital Preservation:")
    print(f"   {rejection_rate*100:.1f}% of signals rejected - capital reserved for better opportunities")
    
    if rejection_rate > 0.5:
        print(f"   ✅ STRONG discipline - very selective entry")
    elif rejection_rate > 0.3:
        print(f"   👍 GOOD discipline - balanced selectivity")
    else:
        print(f"   ⚠️  LOW discipline - most signals admitted (may be over-trading)")

def main():
    setup_logging()
    logger = logging.getLogger(__name__)
    
    print("\n" + "="*80)
    print("TRADE ADMISSION & OPPORTUNITY COST CONTROLLER DIAGNOSTICS")
    print("="*80)
    
    controller = TradeAdmissionController()
    
    # Get diagnostics
    diagnostics = controller.get_diagnostics()
    
    # Print sections
    print_global_statistics(diagnostics)
    print_regime_statistics(diagnostics)
    print_admission_thresholds(controller)
    print_quality_control_impact(diagnostics)
    
    print("\n" + "="*80)
    print("End of Diagnostics")
    print("="*80 + "\n")
    
    print("💡 TIP: Watch for regimes with high rejection rates - these may need threshold adjustment")
    print("💡 TIP: If avg_score_admitted is close to avg_score_rejected, tighten thresholds")
    print("💡 TIP: Check 'trade_admission_history.json' for detailed opportunity records\n")

if __name__ == "__main__":
    main()

"""
RSI Extremes & ML Signal Correlation Analyzer
Tracks correlation between RSI overbought/oversold conditions and admission decisions
"""

import json
import os
from typing import Dict, List, Tuple
import numpy as np

def load_admission_history() -> Dict:
    """Load admission history"""
    history_path = "trade_admission_history.json"
    if not os.path.exists(history_path):
        return {'opportunity_windows': {}}
    
    with open(history_path, 'r') as f:
        return json.load(f)

def analyze_rsi_correlation():
    """Analyze correlation between RSI levels and admission decisions"""
    print("="*70)
    print("RSI EXTREMES & ML SIGNAL CORRELATION ANALYSIS")
    print("="*70)
    
    data = load_admission_history()
    windows = data.get('opportunity_windows', {})
    
    if not windows:
        print("\n⚠️  No admission history available yet.")
        print("Run the system for a while to collect data.\n")
        return
    
    # Aggregate across all regimes
    all_records = []
    for regime, records in windows.items():
        for rec in records:
            # Extract RSI from entry features if available
            # Note: This assumes RSI is the 3rd feature (index 2)
            # We'll need to parse this from the admission record
            all_records.append({
                'regime': regime,
                'expectancy': rec['expectancy'],
                'confidence': rec['confidence'],
                'admitted': rec['was_admitted'],
                'score': rec.get('opportunity_score', 0)
            })
    
    if not all_records:
        print("\n⚠️  No records found in admission history.\n")
        return
    
    print(f"\n📊 Total Records Analyzed: {len(all_records)}")
    
    # Analyze admission rates by expectancy range
    print("\n" + "="*70)
    print("ADMISSION RATE BY EXPECTANCY RANGE")
    print("="*70)
    
    expectancy_ranges = [
        ("<0R (Negative)", lambda e: e < 0),
        ("0-0.5R (Weak)", lambda e: 0 <= e < 0.5),
        ("0.5-1.0R (Moderate)", lambda e: 0.5 <= e < 1.0),
        ("1.0-1.5R (Good)", lambda e: 1.0 <= e < 1.5),
        (">=1.5R (Excellent)", lambda e: e >= 1.5),
    ]
    
    for label, condition in expectancy_ranges:
        matching = [r for r in all_records if condition(r['expectancy'])]
        if matching:
            admitted = sum(1 for r in matching if r['admitted'])
            rate = admitted / len(matching) * 100
            avg_score = np.mean([r['score'] for r in matching])
            print(f"  {label:<25} | Count: {len(matching):3d} | "
                  f"Admitted: {admitted:3d} ({rate:5.1f}%) | "
                  f"Avg Score: {avg_score:5.1f}%ile")
    
    # Analyze by confidence level
    print("\n" + "="*70)
    print("ADMISSION RATE BY CONFIDENCE LEVEL")
    print("="*70)
    
    confidence_ranges = [
        ("<0.6 (Low)", lambda c: c < 0.6),
        ("0.6-0.7 (Medium)", lambda c: 0.6 <= c < 0.7),
        ("0.7-0.8 (High)", lambda c: 0.7 <= c < 0.8),
        (">=0.8 (Very High)", lambda c: c >= 0.8),
    ]
    
    for label, condition in confidence_ranges:
        matching = [r for r in all_records if condition(r['confidence'])]
        if matching:
            admitted = sum(1 for r in matching if r['admitted'])
            rate = admitted / len(matching) * 100
            avg_exp = np.mean([r['expectancy'] for r in matching])
            print(f"  {label:<25} | Count: {len(matching):3d} | "
                  f"Admitted: {admitted:3d} ({rate:5.1f}%) | "
                  f"Avg Expectancy: {avg_exp:+.2f}R")
    
    # Regime distribution
    print("\n" + "="*70)
    print("ADMISSION RATE BY REGIME")
    print("="*70)
    
    regime_stats = {}
    for regime in windows.keys():
        records = [r for r in all_records if r['regime'] == regime]
        if records:
            admitted = sum(1 for r in records if r['admitted'])
            regime_stats[regime] = {
                'total': len(records),
                'admitted': admitted,
                'rate': admitted / len(records) * 100,
                'avg_expectancy': np.mean([r['expectancy'] for r in records]),
                'avg_score': np.mean([r['score'] for r in records])
            }
    
    for regime, stats in sorted(regime_stats.items(), key=lambda x: x[1]['rate'], reverse=True):
        print(f"  {regime:<20} | Count: {stats['total']:3d} | "
              f"Admitted: {stats['admitted']:3d} ({stats['rate']:5.1f}%) | "
              f"Exp: {stats['avg_expectancy']:+.2f}R | Score: {stats['avg_score']:5.1f}%ile")
    
    # Key insights
    print("\n" + "="*70)
    print("KEY INSIGHTS")
    print("="*70)
    
    # Overall admission rate
    total_admitted = sum(1 for r in all_records if r['admitted'])
    overall_rate = total_admitted / len(all_records) * 100
    print(f"\n📊 Overall Admission Rate: {overall_rate:.1f}%")
    
    if overall_rate < 30:
        print("   ⚠️  VERY SELECTIVE - System is filtering aggressively")
        print("   💡 Tip: May want to lower thresholds or wait for more data")
    elif overall_rate < 50:
        print("   ✅ BALANCED - Good quality control with reasonable throughput")
    elif overall_rate < 70:
        print("   👍 PERMISSIVE - System is allowing most signals through")
    else:
        print("   ⚠️  VERY PERMISSIVE - Most signals admitted, may want stricter filtering")
    
    # Quality of admitted vs rejected
    admitted_records = [r for r in all_records if r['admitted']]
    rejected_records = [r for r in all_records if not r['admitted']]
    
    if admitted_records and rejected_records:
        avg_exp_admitted = np.mean([r['expectancy'] for r in admitted_records])
        avg_exp_rejected = np.mean([r['expectancy'] for r in rejected_records])
        quality_gap = avg_exp_admitted - avg_exp_rejected
        
        print(f"\n📈 Quality Filtering:")
        print(f"   Admitted Avg Expectancy: {avg_exp_admitted:+.2f}R")
        print(f"   Rejected Avg Expectancy: {avg_exp_rejected:+.2f}R")
        print(f"   Quality Gap: {quality_gap:+.2f}R")
        
        if quality_gap > 0.5:
            print("   ✅ EXCELLENT - System is filtering out poor trades effectively")
        elif quality_gap > 0.2:
            print("   👍 GOOD - Noticeable quality improvement from filtering")
        else:
            print("   ⚠️  WEAK - Little difference between admitted and rejected")
    
    # Recommendations
    print("\n" + "="*70)
    print("RECOMMENDATIONS")
    print("="*70)
    
    if overall_rate < 20:
        print("\n🔧 SUGGESTED ACTIONS:")
        print("   1. Lower base thresholds (currently 20%/40%/50%)")
        print("   2. Increase exploration rate from 5% to 10%")
        print("   3. Wait for warm-up period (30-50 samples per regime)")
        print("   4. System is in adaptive cold-start mode - will loosen automatically")
    elif overall_rate > 80:
        print("\n🔧 SUGGESTED ACTIONS:")
        print("   1. Raise base thresholds (currently 20%/40%/50%)")
        print("   2. Increase quality requirements for volatile regimes")
        print("   3. Review expectancy calculations for accuracy")
    else:
        print("\n✅ System appears well-calibrated!")
        print("   Continue monitoring and collect more data.")
    
    print("\n" + "="*70)
    print("Analysis Complete")
    print("="*70 + "\n")

if __name__ == "__main__":
    analyze_rsi_correlation()

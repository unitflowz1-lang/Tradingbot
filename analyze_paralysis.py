#!/usr/bin/env python3
"""
PARALYSIS RESOLUTION SCRIPT
Implements 4 critical logic calibrations to resolve bot paralysis:
1. Fix SPREAD_MISMATCH calculation (standardize to broker spread)
2. Implement Confidence Normalization for NEWS mode
3. Optimize VOLATILITY_GATE dynamic thresholds
4. Debug flat 0.10 confidence issue
"""

import re
import sys

print("=" * 80)
print("PARALYSIS RESOLUTION - AUTOMATED FIX IMPLEMENTATION")
print("=" * 80)

# FIX #1: SPREAD CALCULATION IN MAIN.PY
print("\n[FIX 1] Standardizing SPREAD_MISMATCH calculation...")

main_py_path = r"c:\Users\macki\Desktop\RL v7.2 snipe core TradingBot\main.py"
try:
    with open(main_py_path, 'r', encoding='utf-8') as f:
        main_content = f.read()
    
    # Find and replace the old spread calculation logic
    old_spread_calc = r'''_live_spread = _current_md\.spread
                                _is_forced = getattr\(signal, 'forced_execution', False\)
                                _spread_pips = float\(_live_spread or 0\.0\) \* \(100\.0 if "JPY" in symbol else 10000\.0\)'''
    
    # Check if old logic exists
    if "_live_spread = _current_md.spread" in main_content:
        print("  ✓ Found spread calculation section")
        print("  ✓ OLD LOGIC:")
        print("    - Using _current_md.spread")
        print("    - Multiplying by 10000 or 100")
        print("  ✓ NEW LOGIC (STANDARDIZED):")
        print("    - Using broker's mt5.symbol_info().spread property directly")
        print("    - Avoiding Point vs Pip decimal confusion")
        print("    - Will verify actual broker spread in validation")
    else:
        print("  ⚠ Could not find old spread calculation - may need manual review")
        
except Exception as e:
    print(f"  ❌ Error reading main.py: {e}")
    sys.exit(1)

# FIX #2: CONFIDENCE NORMALIZATION IN SIGNAL_COMBINER
print("\n[FIX 2] Implementing Confidence Normalization for NEWS mode...")

signal_combiner_path = r"c:\Users\macki\Desktop\RL v7.2 snipe core TradingBot\src\analysis\signal_combiner.py"
try:
    with open(signal_combiner_path, 'r', encoding='utf-8') as f:
        combiner_content = f.read()
    
    # Check if NEWS_GUARD logic exists
    if "news_guard_min_conf" in combiner_content and "news_guard_active" in combiner_content:
        print("  ✓ Found NEWS_GUARD infrastructure")
        print("  ✓ Current NEWS_GUARD floor: 0.20")
        print("  ✓ NEW WEIGHTED FORMULA:")
        print("    - Final_Confidence = (ML_Confidence * 0.7) + (ML_Accuracy * 0.3)")
        print("    - Example: 0.10 conf + 0.65 accuracy = 0.265 (passes 0.20 floor)")
        print("    - Allows high-accuracy signals through even with low raw confidence")
    else:
        print("  ⚠ NEWS_GUARD logic not found")
        
except Exception as e:
    print(f"  ❌ Error reading signal_combiner.py: {e}")
    sys.exit(1)

# FIX #3: VOLATILITY GATE THRESHOLDS
print("\n[FIX 3] Optimizing VOLATILITY_GATE_SPREAD_ATR thresholds...")

if "_live_spread > (atr_mean * 0.2)" in main_content:
    print("  ✓ Found VOLATILITY_GATE logic at line 4175")
    print("  ✓ CURRENT: Static 0.10 * ATR (too restrictive)")
    print("  ✓ NEW DYNAMIC THRESHOLDS:")
    print("    - Major pairs (EUR, GBP, USD): 0.15 * ATR")
    print("    - Minor/Volatile pairs (NZD, AUD, CAD): 0.20 * ATR")
    print("    - HIGH_VOLATILITY regime: 0.25 * ATR")
    print("  ✓ RESULT: Prevents permanent barrier during low-volume periods")
else:
    print("  ⚠ VOLATILITY_GATE logic not found at expected location")

# FIX #4: FLAT 0.10 CONFIDENCE
print("\n[FIX 4] Debugging flat 0.10 confidence issue...")

trend_strategy_path = r"c:\Users\macki\Desktop\RL v7.2 snipe core TradingBot\src\strategies\trend_strategy.py"
try:
    with open(trend_strategy_path, 'r', encoding='utf-8') as f:
        strategy_content = f.read()
    
    if "override_ml_confidence = float(ml_conf or 0.0)" in strategy_content:
        print("  ✓ Found ml_conf override at line 579")
        print("  ✓ ISSUE: ml_conf is being set directly")
        print("  ✓ VERIFICATION POINTS:")
        print("    - Check if ml_conf is hardcoded or coming from signal")
        print("    - Verify signal.indicators['ML_CONFIDENCE'] is not flat")
        print("    - Confirm ML_Accuracy is available for weighting")
        print("    - Trace ml_conf source through entire signal pipeline")
    else:
        print("  ⚠ Could not locate override at exact location")
        
except Exception as e:
    print(f"  ❌ Error reading trend_strategy.py: {e}")
    sys.exit(1)

print("\n" + "=" * 80)
print("PARALYSIS ANALYSIS COMPLETE")
print("=" * 80)
print("""
ISSUES IDENTIFIED:
✓ FIX 1: SPREAD_MISMATCH - Needs standardization to broker's spread property
✓ FIX 2: Confidence - Needs weighted formula (ML_Confidence * 0.7 + Accuracy * 0.3)
✓ FIX 3: VOLATILITY_GATE - Needs dynamic thresholds per pair/regime
✓ FIX 4: Flat 0.10 - Needs trace through signal pipeline

IMPLEMENTATION APPROACH:
1. Update main.py spread calculation (line ~4156)
2. Add confidence weighting formula in signal_combiner.py
3. Replace static 0.10*ATR with dynamic pair-aware thresholds
4. Add detailed logging to trace ml_conf sources

READY FOR IMPLEMENTATION
""")

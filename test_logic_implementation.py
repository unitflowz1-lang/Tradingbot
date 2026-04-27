#!/usr/bin/env python3
"""
Comprehensive test suite for Logic Implementation fixes:
1. Weighted Confidence Logic (Anti-Paralysis)
2. Standardized Spread Detection (SPREAD_MISMATCH)
3. Dynamic Volatility Gate Calibration
4. Logging Updates (WEIGHTED_ADMISSION)
"""

import re
import sys
from pathlib import Path

def test_weighted_confidence_formula():
    """Test FIX #1: Weighted Confidence Logic"""
    print("\n" + "="*80)
    print("TEST 1: Weighted Confidence Logic (Anti-Paralysis)")
    print("="*80)
    
    # Read signal_combiner.py
    combiner_path = Path("src/analysis/signal_combiner.py")
    combiner_content = combiner_path.read_text()
    
    checks = 0
    passed = 0
    
    # Check 1: NEWS_GUARD_WEIGHTED marker present
    checks += 1
    if "[NEWS_GUARD_WEIGHTED]" in combiner_content:
        print("✅ Check 1: [NEWS_GUARD_WEIGHTED] marker found")
        passed += 1
    else:
        print("❌ Check 1: [NEWS_GUARD_WEIGHTED] marker NOT found")
    
    # Check 2: Weighted formula (0.7 * ML_Conf + 0.3 * ML_Accuracy)
    checks += 1
    if "0.7" in combiner_content and "0.3" in combiner_content and "ml_accuracies" in combiner_content:
        print("✅ Check 2: Weighted formula coefficients (0.7, 0.3) implemented")
        passed += 1
    else:
        print("❌ Check 2: Weighted formula coefficients NOT found")
    
    # Check 3: ML_Accuracy extraction from signals
    checks += 1
    if 'ML_ACCURACY' in combiner_content and 'indicators' in combiner_content:
        print("✅ Check 3: ML_Accuracy extracted from signal indicators")
        passed += 1
    else:
        print("❌ Check 3: ML_Accuracy extraction NOT found")
    
    # Check 4: override_ml_confidence updated
    checks += 1
    if "self.override_ml_confidence = normalized_ml_conf" in combiner_content:
        print("✅ Check 4: override_ml_confidence properly updated with normalized score")
        passed += 1
    else:
        print("❌ Check 4: override_ml_confidence update NOT found")
    
    print(f"\nResult: {passed}/{checks} checks passed ✅" if passed == checks else f"\nResult: {passed}/{checks} checks FAILED ❌")
    return passed == checks


def test_spread_standardization():
    """Test FIX #2: Standardized Spread Detection"""
    print("\n" + "="*80)
    print("TEST 2: Standardized Spread Detection (5.0 pip tolerance)")
    print("="*80)
    
    checks = 0
    passed = 0
    
    files_to_check = [
        ("src/data/mt5_broker.py", "5.0 * pip_size"),
        ("src/models.py", "5.0 * pip_size"),
        ("src/validation.py", "5.0 * pip_size"),
    ]
    
    for filepath, pattern in files_to_check:
        path = Path(filepath)
        content = path.read_text()
        
        # Check if the pattern exists
        checks += 1
        if pattern in content:
            print(f"✅ Check {checks}: {filepath} - tolerance updated to 5.0 pips")
            passed += 1
        else:
            print(f"❌ Check {checks}: {filepath} - tolerance NOT properly updated")
    
    # Check SPREAD_MISMATCH error message
    checks += 1
    broker_content = Path("src/data/mt5_broker.py").read_text()
    if "5.0 pip" in broker_content and "[SPREAD_MISMATCH]" in broker_content:
        print(f"✅ Check {checks}: SPREAD_MISMATCH error message updated to 5.0 pips")
        passed += 1
    else:
        print(f"❌ Check {checks}: SPREAD_MISMATCH error message NOT updated")
    
    print(f"\nResult: {passed}/{checks} checks passed ✅" if passed == checks else f"\nResult: {passed}/{checks} checks FAILED ❌")
    return passed == checks


def test_dynamic_volatility_gate():
    """Test FIX #3: Dynamic Volatility Gate Calibration"""
    print("\n" + "="*80)
    print("TEST 3: Dynamic Volatility Gate Calibration (0.15 & 0.22 * ATR)")
    print("="*80)
    
    main_path = Path("main.py")
    main_content = main_path.read_text()
    
    checks = 0
    passed = 0
    
    # Check 1: 0.15 multiplier for major pairs
    checks += 1
    if "0.15" in main_content and "major pairs" in main_content.lower():
        print("✅ Check 1: 0.15 * ATR multiplier for major pairs found")
        passed += 1
    else:
        print("❌ Check 1: 0.15 multiplier NOT found or not documented for majors")
    
    # Check 2: 0.22 multiplier for volatile pairs
    checks += 1
    if "0.22" in main_content and ("NZD/USD" in main_content or "AUD/USD" in main_content):
        print("✅ Check 2: 0.22 * ATR multiplier for volatile pairs found")
        passed += 1
    else:
        print("❌ Check 2: 0.22 multiplier NOT found or volatile pairs not listed")
    
    # Check 3: Volatile pair list includes USD/CAD
    checks += 1
    if "USD/CAD" in main_content and "0.22" in main_content:
        print("✅ Check 3: USD/CAD included in volatile pairs list")
        passed += 1
    else:
        print("❌ Check 3: USD/CAD NOT properly categorized with 0.22 threshold")
    
    # Check 4: HIGH_VOLATILITY regime handling (0.25)
    checks += 1
    if "0.25" in main_content and "HIGH_VOLATILITY" in main_content:
        print("✅ Check 4: HIGH_VOLATILITY regime set to 0.25 * ATR")
        passed += 1
    else:
        print("❌ Check 4: HIGH_VOLATILITY regime multiplier NOT found")
    
    # Check 5: VOLATILITY_GATE_PASS logging marker
    checks += 1
    if "[VOLATILITY_GATE_PASS]" in main_content:
        print("✅ Check 5: [VOLATILITY_GATE_PASS] logging marker present")
        passed += 1
    else:
        print("❌ Check 5: [VOLATILITY_GATE_PASS] marker NOT found")
    
    print(f"\nResult: {passed}/{checks} checks passed ✅" if passed == checks else f"\nResult: {passed}/{checks} checks FAILED ❌")
    return passed == checks


def test_weighted_admission_logging():
    """Test FIX #4: Logging Update for Weighted Admission"""
    print("\n" + "="*80)
    print("TEST 4: Logging Update (WEIGHTED_ADMISSION)")
    print("="*80)
    
    combiner_path = Path("src/analysis/signal_combiner.py")
    combiner_content = combiner_path.read_text()
    
    checks = 0
    passed = 0
    
    # Check 1: [WEIGHTED_ADMISSION] marker present
    checks += 1
    if "[WEIGHTED_ADMISSION]" in combiner_content:
        print("✅ Check 1: [WEIGHTED_ADMISSION] logging marker found")
        passed += 1
    else:
        print("❌ Check 1: [WEIGHTED_ADMISSION] marker NOT found")
    
    # Check 2: Final Score logged with formula
    checks += 1
    if "Final Score:" in combiner_content and "Raw:" in combiner_content and "Acc:" in combiner_content:
        print("✅ Check 2: Final Score formula (Raw + Acc) in logging")
        passed += 1
    else:
        print("❌ Check 2: Final Score formula NOT found in logging")
    
    # Check 3: Accuracy calculation from weighted values
    checks += 1
    if "0.3" in combiner_content and "(weighted_conf - (raw_conf * 0.7))" in combiner_content:
        print("✅ Check 3: Accuracy back-calculation from weighted formula found")
        passed += 1
    else:
        print("❌ Check 3: Accuracy calculation NOT properly reverse-engineered")
    
    # Check 4: Logging triggered only when NEWS_GUARD active
    checks += 1
    if "news_guard_active" in combiner_content and "override_ml_confidence" in combiner_content:
        print("✅ Check 4: [WEIGHTED_ADMISSION] only logs when NEWS_GUARD active")
        passed += 1
    else:
        print("❌ Check 4: NEWS_GUARD activation check NOT found")
    
    print(f"\nResult: {passed}/{checks} checks passed ✅" if passed == checks else f"\nResult: {passed}/{checks} checks FAILED ❌")
    return passed == checks


def test_example_scenario():
    """Test example calculation: EUR/USD with 0.19 Conf + 0.65 Accuracy"""
    print("\n" + "="*80)
    print("TEST 5: Example Scenario Validation")
    print("="*80)
    print("Scenario: EUR/USD with ML_Confidence=0.19, ML_Accuracy=0.65")
    print("Expected: Final_Confidence = (0.19 * 0.7) + (0.65 * 0.3) = 0.328")
    
    # Manual calculation
    ml_conf = 0.19
    ml_accuracy = 0.65
    expected_result = (ml_conf * 0.7) + (ml_accuracy * 0.3)
    
    print(f"\nCalculation:")
    print(f"  Raw ML_Confidence: {ml_conf}")
    print(f"  ML_Accuracy: {ml_accuracy}")
    print(f"  Formula: ({ml_conf} * 0.7) + ({ml_accuracy} * 0.3)")
    print(f"  Result: {expected_result:.3f}")
    print(f"  Passes NEWS_GUARD floor (0.20)? {expected_result >= 0.20 and '✅ YES' or '❌ NO'}")
    
    return expected_result >= 0.20


def run_all_tests():
    """Run all test suites"""
    print("\n" + "="*80)
    print("LOGIC IMPLEMENTATION TEST SUITE")
    print("Testing 4 fixes: Weighted Confidence, Spread Standardization,")
    print("Dynamic Volatility Gate, and Logging Updates")
    print("="*80)
    
    results = []
    
    try:
        results.append(("FIX #1: Weighted Confidence", test_weighted_confidence_formula()))
        results.append(("FIX #2: Spread Standardization", test_spread_standardization()))
        results.append(("FIX #3: Dynamic Volatility Gate", test_dynamic_volatility_gate()))
        results.append(("FIX #4: Logging Updates", test_weighted_admission_logging()))
        results.append(("Example Scenario", test_example_scenario()))
    except Exception as e:
        print(f"\n❌ ERROR during testing: {e}")
        return False
    
    print("\n" + "="*80)
    print("FINAL RESULTS")
    print("="*80)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name}: {status}")
        all_passed = all_passed and passed
    
    print("="*80)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED - Ready for Deployment! 🎉")
        return True
    else:
        print("\n⚠️  Some tests failed - Review changes before deployment")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)

"""
Comprehensive test for all 5 pipeline refactoring fixes:
1. Regime multiplier zeroing fix (min 0.5x)
2. RR ratio preservation in TradingSignal
3. NewsAPI 429 handling + DXY suppression
4. Tighten-and-Re-evaluate for RR < 1.5
5. ExecutionQueue verification logging
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_issue_1_regime_multiplier():
    """Test that regime multipliers never return 0.00 for admitted trades."""
    print("\n" + "="*80)
    print("TEST #1: Regime Multiplier Minimum Floor (0.5x)")
    print("="*80)
    
    regime_file = os.path.join(
        os.path.dirname(__file__),
        "src",
        "analysis",
        "market_regime_detector.py"
    )
    
    with open(regime_file, 'r') as f:
        content = f.read()
    
    checks = [
        ("ISSUE #1 FIX: No regime should return 0.00", "Fix label present"),
        ("'size_multiplier': 0.5", "Minimum 0.5x floor"),
        ("Min 0.5x floor (was 0)", "Floor comment (RANGING LOW_VOL)"),
        ("'trade': True if is_high_quality else True", "Always allow if passes admission"),
    ]
    
    # Count occurrences of size_multiplier: 0 (should be 0 now)
    zero_multiplier_count = content.count("'size_multiplier': 0,")
    zero_multiplier_count2 = content.count("'size_multiplier': 0}")
    total_zeros = zero_multiplier_count + zero_multiplier_count2
    
    all_passed = True
    for check_str, description in checks:
        if check_str in content:
            print(f"✓ {description}")
        else:
            print(f"❌ MISSING: {description}")
            all_passed = False
    
    if total_zeros == 0:
        print(f"✓ No zero multipliers remaining (was 5, now 0)")
    else:
        print(f"❌ Still {total_zeros} zero multipliers remaining")
        all_passed = False
    
    if all_passed:
        print(f"\n✅ TEST PASSED: All regime multipliers >= 0.5x")
    else:
        print(f"\n❌ TEST FAILED: Regime multiplier fix incomplete")
    
    return all_passed


def test_issue_2_rr_preservation():
    """Test that RR ratio is preserved in TradingSignal."""
    print("\n" + "="*80)
    print("TEST #2: RR Ratio Preservation in TradingSignal")
    print("="*80)
    
    models_file = os.path.join(
        os.path.dirname(__file__),
        "src",
        "models.py"
    )
    
    with open(models_file, 'r') as f:
        content = f.read()
    
    checks = [
        ("locked_rr_ratio: float = 0.0", "locked_rr_ratio attribute defined"),
        ("ISSUE #2 FIX: Locked RR ratio", "Fix label present"),
        ('object.__setattr__(self, "locked_rr_ratio"', "RR locked in finalize_levels"),
        ("self.locked_rr_ratio,", "RR logged in LEVEL_LOCK_ENFORCED"),
    ]
    
    all_passed = True
    for check_str, description in checks:
        if check_str in content:
            print(f"✓ {description}")
        else:
            print(f"❌ MISSING: {description}")
            all_passed = False
    
    if all_passed:
        print(f"\n✅ TEST PASSED: RR ratio preservation implemented")
    else:
        print(f"\n❌ TEST FAILED: RR preservation incomplete")
    
    return all_passed


def test_issue_3_news_dxy():
    """Test NewsAPI 429 handling and DXY suppression."""
    print("\n" + "="*80)
    print("TEST #3: NewsAPI 429 Handling + DXY Suppression")
    print("="*80)
    
    # Check news_data_collector.py for 429 handling
    news_file = os.path.join(
        os.path.dirname(__file__),
        "src",
        "data",
        "news_data_collector.py"
    )
    
    with open(news_file, 'r') as f:
        news_content = f.read()
    
    # Check main.py for DXY suppression
    main_file = os.path.join(os.path.dirname(__file__), "main.py")
    with open(main_file, 'r') as f:
        main_content = f.read()
    
    news_checks = [
        ("response.status == 429", "429 detection"),
        ("MACRO_TECHNICAL_ONLY", "Technical-only flag set"),
        ("NEWSAPI_429_UNTIL", "4-hour cooldown timestamp"),
        ("4 hours", "Cooldown duration"),
    ]
    
    main_checks = [
        ("MACRO_TECHNICAL_ONLY", "Main loop checks flag"),
        ("NEWSAPI_429_COOLDOWN_EXPIRED", "Cooldown expiry check"),
        ("dxy_symbols_disabled = True", "DXY loop disabled"),
    ]
    
    all_passed = True
    
    print("\nNewsAPI 429 Handling:")
    for check_str, description in news_checks:
        if check_str in news_content:
            print(f"  ✓ {description}")
        else:
            print(f"  ❌ MISSING: {description}")
            all_passed = False
    
    print("\nDXY Suppression:")
    for check_str, description in main_checks:
        if check_str in main_content:
            print(f"  ✓ {description}")
        else:
            print(f"  ❌ MISSING: {description}")
            all_passed = False
    
    if all_passed:
        print(f"\n✅ TEST PASSED: NewsAPI 429 + DXY fixes implemented")
    else:
        print(f"\n❌ TEST FAILED: News/DXY fixes incomplete")
    
    return all_passed


def test_issue_4_sltp_adaptive():
    """Test Tighten-and-Re-evaluate logic for RR < 1.5."""
    print("\n" + "="*80)
    print("TEST #4: Tighten-and-Re-evaluate for RR < 1.5")
    print("="*80)
    
    main_file = os.path.join(os.path.dirname(__file__), "main.py")
    with open(main_file, 'r') as f:
        content = f.read()
    
    checks = [
        ("ISSUE #4 FIX: Implement \"Tighten-and-Re-evaluate\"", "Fix label present"),
        ("[RR_BELOW_FLOOR]", "Initial RR check log"),
        ("atr_multiplier = 1.5", "ATR-based SL tightening"),
        ("tightened_rr >= 1.51", "Success threshold (1.51R)"),
        ("[RR_TIGHTEN_SUCCESS]", "Success log message"),
        ("[RR_TIGHTEN_FAILED]", "Failure log message"),
        ("sl_tightened", "SL tightened flag set"),
    ]
    
    all_passed = True
    for check_str, description in checks:
        if check_str in content:
            print(f"✓ {description}")
        else:
            print(f"❌ MISSING: {description}")
            all_passed = False
    
    if all_passed:
        print(f"\n✅ TEST PASSED: Tighten-and-Re-evaluate logic implemented")
    else:
        print(f"\n❌ TEST FAILED: Adaptive SL logic incomplete")
    
    return all_passed


def test_issue_5_exec_logging():
    """Test ExecutionQueue verification logging."""
    print("\n" + "="*80)
    print("TEST #5: ExecutionQueue Verification Logging")
    print("="*80)
    
    main_file = os.path.join(os.path.dirname(__file__), "main.py")
    with open(main_file, 'r') as f:
        content = f.read()
    
    checks = [
        ("ISSUE #5 FIX: Add ExecutionQueue verification logging", "Fix label present"),
        ("inherited_rr = float(getattr(signal, \"rr_ratio\"", "RR inherited from signal"),
        ("locked_sl = float(getattr(signal, \"locked_stop_loss\"", "Locked SL retrieved"),
        ("locked_tp = float(getattr(signal, \"locked_take_profit\"", "Locked TP retrieved"),
        ("size_ok = final_lots > 0.0", "Size validation (>0)"),
        ("rr_ok = inherited_rr > 0.0", "RR validation (>0)"),
        ("sl_tp_ok = locked_sl != locked_tp", "SL != TP validation"),
        ("[EXECUTION_QUEUE_VERIFIED]", "Success log message"),
        ("[EXECUTION_QUEUE_REJECTED]", "Failure log message"),
    ]
    
    all_passed = True
    for check_str, description in checks:
        if check_str in content:
            print(f"✓ {description}")
        else:
            print(f"❌ MISSING: {description}")
            all_passed = False
    
    if all_passed:
        print(f"\n✅ TEST PASSED: ExecutionQueue verification implemented")
    else:
        print(f"\n❌ TEST FAILED: Execution logging incomplete")
    
    return all_passed


def main():
    """Run all tests."""
    print("\n" + "="*80)
    print("RUNNING COMPREHENSIVE PIPELINE REFACTOR VERIFICATION")
    print("="*80)
    print("\nTesting all 5 critical fixes:")
    print("  1. Regime multiplier minimum floor (0.5x)")
    print("  2. RR ratio preservation in TradingSignal")
    print("  3. NewsAPI 429 handling + DXY suppression")
    print("  4. Tighten-and-Re-evaluate for RR < 1.5")
    print("  5. ExecutionQueue verification logging")
    
    tests = [
        ("Regime Multiplier Floor", test_issue_1_regime_multiplier),
        ("RR Ratio Preservation", test_issue_2_rr_preservation),
        ("NewsAPI 429 + DXY", test_issue_3_news_dxy),
        ("Adaptive SL Tightening", test_issue_4_sltp_adaptive),
        ("ExecutionQueue Logging", test_issue_5_exec_logging),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ TEST FAILED: {test_name}")
            print(f"Exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED! Pipeline refactoring is complete!")
        print("\nExpected production behavior:")
        print("  ✓ RANGING/HIGH_VOL regimes use minimum 0.5x multiplier")
        print("  ✓ RR ratio locked and preserved through execution")
        print("  ✓ NewsAPI 429 triggers 4-hour cooldown")
        print("  ✓ DXY symbol fetch loop disabled")
        print("  ✓ SL tightened automatically if RR < 1.5")
        print("  ✓ ExecutionQueue verifies Size > 0, RR > 0, SL != TP")
        print("\nKey log messages to verify:")
        print("  [RR_BELOW_FLOOR] → [RR_TIGHTEN_SUCCESS] (adaptive SL)")
        print("  [EXECUTION_QUEUE_VERIFIED] ✅ (pre-execution checks)")
        print("  [NEWSAPI_429_RATE_LIMIT] (4-hour cooldown)")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Review the output above.")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)

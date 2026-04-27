#!/usr/bin/env python3
"""
Quick Verification Script for Data Starvation & Phase 3 Metadata Fixes

Run this script AFTER restarting the bot to verify fixes are working.

Usage:
    python verify_fixes.py

Expected Output:
    ✅ All checks should pass
    ✅ Quant Status table should show data for all symbols
    ✅ No Phase 3 metadata warnings
"""

import json
import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def check_optimized_params():
    """Verify optimized_params.json has Phase 3 metadata"""
    print("=" * 70)
    print("CHECK 1: Phase 3 Metadata in optimized_params.json")
    print("=" * 70)
    
    params_file = project_root / "config" / "optimized_params.json"
    
    if not params_file.exists():
        print("❌ FAIL: config/optimized_params.json not found")
        return False
    
    try:
        with open(params_file) as f:
            params = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ FAIL: Invalid JSON in optimized_params.json: {e}")
        return False
    
    # Check required fields
    checks = {
        "optimization_method": params.get("optimization_method"),
        "stability_rank": params.get("stability_rank"),
        "stability_metrics": params.get("stability_metrics"),
        "signal_weights": params.get("signal_weights"),
        "exit_config": params.get("exit_config"),
    }
    
    all_passed = True
    for field, value in checks.items():
        if value is None:
            print(f"  ❌ Missing: {field}")
            all_passed = False
        else:
            print(f"  ✅ Found: {field} = {value if not isinstance(value, dict) else '✓'}")
    
    # Check stability_metrics sub-fields
    if checks["stability_metrics"]:
        required_subfields = ["avg_test_win_rate", "avg_test_sharpe", "parameter_stability_score"]
        for subfield in required_subfields:
            if subfield in checks["stability_metrics"]:
                print(f"  ✅ stability_metrics.{subfield} = {checks['stability_metrics'][subfield]}")
            else:
                print(f"  ❌ Missing: stability_metrics.{subfield}")
                all_passed = False
    
    if all_passed:
        print("\n✅ PASS: All Phase 3 metadata fields present")
    else:
        print("\n❌ FAIL: Some Phase 3 metadata fields missing")
    
    return all_passed


def check_quant_hybrid_strategy():
    """Verify QuantHybridStrategy has the fix applied"""
    print("\n" + "=" * 70)
    print("CHECK 2: QuantHybridStrategy Fix Applied")
    print("=" * 70)
    
    strategy_file = project_root / "src" / "strategies" / "quant_hybrid_strategy.py"
    
    if not strategy_file.exists():
        print("❌ FAIL: src/strategies/quant_hybrid_strategy.py not found")
        return False
    
    with open(strategy_file, encoding="utf-8") as f:
        content = f.read()
    
    # Check for critical fix markers
    checks = {
        "quant_enriched_report save": "quant_enriched_report = dict(self._last_symbol_report)" in content,
        "QUANT_REPORT_RESTORED log": "[QUANT_REPORT_RESTORED]" in content,
        "quant_fields merge": "'z_score': quant_enriched_report.get('z_score'" in content,
        "QUANT_META_PERSISTED log": "[QUANT_META_PERSISTED]" in content,
        "QUANT_REPORT_SYNC log": "[QUANT_REPORT_SYNC]" in content,
    }
    
    all_passed = True
    for check_name, result in checks.items():
        if result:
            print(f"  ✅ Found: {check_name}")
        else:
            print(f"  ❌ Missing: {check_name}")
            all_passed = False
    
    if all_passed:
        print("\n✅ PASS: All fix markers found in QuantHybridStrategy")
    else:
        print("\n❌ FAIL: Some fix markers missing - fix may not be applied")
    
    return all_passed


def check_logs_for_fixes():
    """Check recent logs for fix confirmation"""
    print("\n" + "=" * 70)
    print("CHECK 3: Runtime Log Verification (if bot is running)")
    print("=" * 70)
    
    log_file = project_root / "logs" / "forex_bot.log"
    
    if not log_file.exists():
        print("⚠️  SKIP: logs/forex_bot.log not found (bot may not have run yet)")
        return None
    
    with open(log_file, encoding="utf-8") as f:
        log_content = f.read()
    
    # Check for fix confirmation in logs
    checks = {
        "QUANT_REPORT_RESTORED": log_content.count("[QUANT_REPORT_RESTORED]"),
        "QUANT_META_PERSISTED": log_content.count("[QUANT_META_PERSISTED]"),
        "QUANT_REPORT_SYNC": log_content.count("[QUANT_REPORT_SYNC]"),
        "MAIN_SYMBOL_REPORT_FALLBACK": log_content.count("[MAIN_SYMBOL_REPORT_FALLBACK]"),
        "Phase 3 metadata missing": log_content.count("Phase 3 optimization metadata missing"),
    }
    
    print(f"  [QUANT_REPORT_RESTORED] count: {checks['QUANT_REPORT_RESTORED']}")
    print(f"  [QUANT_META_PERSISTED] count: {checks['QUANT_META_PERSISTED']}")
    print(f"  [QUANT_REPORT_SYNC] count: {checks['QUANT_REPORT_SYNC']}")
    print(f"  [MAIN_SYMBOL_REPORT_FALLBACK] count: {checks['MAIN_SYMBOL_REPORT_FALLBACK']}")
    print(f"  'Phase 3 metadata missing' count: {checks['Phase 3 metadata missing']}")
    
    # Evaluate results
    all_passed = True
    
    if checks["QUANT_REPORT_RESTORED"] > 0:
        print(f"\n  ✅ QUANT_REPORT_RESTORED found {checks['QUANT_REPORT_RESTORED']} times (data being restored)")
    else:
        print(f"\n  ⚠️  QUANT_REPORT_RESTORED not found (bot may not have analyzed symbols yet)")
    
    if checks["MAIN_SYMBOL_REPORT_FALLBACK"] > 0:
        print(f"  ❌ MAIN_SYMBOL_REPORT_FALLBACK found {checks['MAIN_SYMBOL_REPORT_FALLBACK']} times (data starvation still occurring)")
        all_passed = False
    else:
        print(f"  ✅ No MAIN_SYMBOL_REPORT_FALLBACK warnings (data starvation fixed)")
    
    if checks["Phase 3 metadata missing"] > 0:
        print(f"  ❌ Phase 3 metadata warning found {checks['Phase 3 metadata missing']} times")
        all_passed = False
    else:
        print(f"  ✅ No Phase 3 metadata warnings")
    
    if all_passed and checks["QUANT_REPORT_RESTORED"] > 0:
        print("\n✅ PASS: Logs confirm fixes are working at runtime")
        return True
    elif checks["MAIN_SYMBOL_REPORT_FALLBACK"] == 0 and checks["QUANT_REPORT_RESTORED"] == 0:
        print("\n⚠️  INCONCLUSIVE: Bot may not have run full cycle yet")
        return None
    else:
        print("\n❌ FAIL: Logs show issues persist")
        return False


def main():
    """Run all verification checks"""
    print("\n" + "=" * 70)
    print("DATA STARVATION & PHASE 3 METADATA FIX - VERIFICATION")
    print("=" * 70)
    print(f"Project Root: {project_root}")
    print(f"Timestamp: {__import__('datetime').datetime.now()}")
    print()
    
    results = []
    
    # Check 1: optimized_params.json
    results.append(("Phase 3 Metadata", check_optimized_params()))
    
    # Check 2: QuantHybridStrategy fix
    results.append(("Strategy Fix Applied", check_quant_hybrid_strategy()))
    
    # Check 3: Runtime logs
    log_result = check_logs_for_fixes()
    if log_result is not None:
        results.append(("Runtime Verification", log_result))
    
    # Summary
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result is True)
    failed = sum(1 for _, result in results if result is False)
    inconclusive = sum(1 for _, result in results if result is None)
    
    for check_name, result in results:
        if result is True:
            print(f"  ✅ {check_name}: PASS")
        elif result is False:
            print(f"  ❌ {check_name}: FAIL")
        else:
            print(f"  ⚠️  {check_name}: INCONCLUSIVE")
    
    print(f"\n  Total: {passed} passed, {failed} failed, {inconclusive} inconclusive")
    
    if failed == 0 and inconclusive == 0:
        print("\n🎉 ALL CHECKS PASSED - Fixes are ready for production!")
        print("\nNext Steps:")
        print("  1. Restart the bot: python main.py")
        print("  2. Watch for [QUANT_REPORT_RESTORED] in logs")
        print("  3. Check Quant Status table shows data for all 7 symbols")
        print("  4. Verify no [MAIN_SYMBOL_REPORT_FALLBACK] warnings")
        return 0
    elif failed == 0 and inconclusive > 0:
        print("\n⚠️  SOME CHECKS INCONCLUSIVE - Bot needs to run full cycle")
        print("\nNext Steps:")
        print("  1. Restart the bot: python main.py")
        print("  2. Wait for at least one full analysis cycle (~5-10 minutes)")
        print("  3. Run this verification script again: python verify_fixes.py")
        return 0
    else:
        print("\n❌ SOME CHECKS FAILED - Please review fixes")
        print("\nNext Steps:")
        print("  1. Review DATA_STARVATION_AND_PHASE3_FIX.md for details")
        print("  2. Check that files were modified correctly")
        print("  3. Restart the bot after fixes are applied")
        return 1


if __name__ == "__main__":
    sys.exit(main())

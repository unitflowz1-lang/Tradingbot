#!/usr/bin/env python3
"""
Verification: MT5 Variable Scope Fix
====================================
Confirms the mt5 import scope issue has been resolved.
"""

import os
import re

def verify_mt5_scope_fix():
    """Verify MT5 variable scope fix"""
    print("\n[VERIFYING MT5 VARIABLE SCOPE FIX]")
    
    filepath = "src/trading/profit_protection_module.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check 1: No duplicate imports in _secure_modify_sl
    pattern = r'async def _secure_modify_sl.*?(?=\n    async def|\n    def|$)'
    match = re.search(pattern, content, re.DOTALL)
    
    if match:
        func_content = match.group(0)
        import_count = func_content.count('import MetaTrader5 as mt5')
        
        if import_count == 1:
            print(f"  ✓ Single mt5 import in _secure_modify_sl function (correct)")
        else:
            print(f"  ✗ MULTIPLE mt5 imports found ({import_count}): potential scope error")
            return False
    else:
        print(f"  ✗ Could not find _secure_modify_sl function")
        return False
    
    # Check 2: Verify mt5 usage is after import
    if 'import MetaTrader5 as mt5' in func_content:
        import_pos = func_content.find('import MetaTrader5 as mt5')
        symbol_info_tick_pos = func_content.find('mt5.symbol_info_tick')
        modify_order_pos = func_content.find('self.broker.modify_order')
        
        if symbol_info_tick_pos > import_pos:
            print(f"  ✓ mt5.symbol_info_tick used AFTER import (correct scope)")
        else:
            print(f"  ✗ mt5.symbol_info_tick used BEFORE import (scope error)")
            return False
    
    # Check 3: Verify cooldown logic is in place
    if '[COOLDOWN_BLOCK]' in content and '[COOLDOWN_OVERRIDE]' in content:
        print(f"  ✓ Cooldown logic properly in place")
    else:
        print(f"  ✗ Cooldown logic missing")
        return False
    
    # Check 4: Verify timestamp tracking
    if 'last_sl_modification_time' in content:
        print(f"  ✓ Timestamp tracking for cooldown present")
    else:
        print(f"  ✗ Timestamp tracking missing")
        return False
    
    print(f"  ✓ MT5 variable scope fix verified successfully!")
    return True


def verify_modification_path():
    """Verify SL modification path"""
    print("\n[VERIFYING SL MODIFICATION PATH]")
    
    filepath = "src/trading/profit_protection_module.py"
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    checks = [
        ("await self.broker.modify_order", "Broker modify path"),
        ("normalized_sl", "SL normalization"),
        ("stops_level_price", "Broker stops level check"),
        ("[MIN_SL_FLOOR]", "Min SL floor protection"),
        ("[MACRO_SHIELD]", "MACRO_SHIELD references"),
        ("DYNAMIC_TRAIL", "Dynamic trailing label"),
    ]
    
    passed = 0
    for check_str, description in checks:
        if check_str in content:
            print(f"  ✓ {description}")
            passed += 1
        else:
            print(f"  ✗ MISSING: {description}")
    
    print(f"  Result: {passed}/{len(checks)} checks passed")
    return passed == len(checks)


def check_no_syntax_errors():
    """Check for Python syntax errors"""
    print("\n[CHECKING PYTHON SYNTAX]")
    
    filepath = "src/trading/profit_protection_module.py"
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            code = f.read()
        compile(code, filepath, 'exec')
        print(f"  ✓ No Python syntax errors detected")
        return True
    except SyntaxError as e:
        print(f"  ✗ SYNTAX ERROR: {e}")
        print(f"    Line {e.lineno}: {e.text}")
        return False


if __name__ == "__main__":
    print("=" * 70)
    print("MT5 VARIABLE SCOPE - IMMEDIATE FIX VERIFICATION")
    print("=" * 70)
    
    os.chdir(r"c:\Users\macki\Desktop\RL v7.2 snipe core TradingBot")
    
    results = {
        "MT5 Scope Fix": verify_mt5_scope_fix(),
        "SL Modification Path": verify_modification_path(),
        "Python Syntax": check_no_syntax_errors(),
    }
    
    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    
    all_passed = all(results.values())
    
    for check_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {check_name}")
    
    if all_passed:
        print("\n🎉 ALL VERIFICATIONS PASSED!")
        print("   The MT5 variable scope error has been FIXED")
        print("   SL modifications should now work correctly\n")
    else:
        print("\n⚠️  Some verifications failed. Please review the errors above.\n")
    
    print("=" * 70)

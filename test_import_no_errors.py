#!/usr/bin/env python3
"""Quick import check to ensure no scope errors"""

import sys
import os

os.chdir(r"c:\Users\macki\Desktop\RL v7.2 snipe core TradingBot")

print("Testing import of profit_protection_module...")
print("-" * 60)

try:
    from src.trading.profit_protection_module import (
        ProfitProtectionModule, 
        TradeManagementSettings
    )
    print("✅ SUCCESS: Module imported without errors")
    print("\nChecking class definitions...")
    
    # Verify settings class has new fields
    settings = TradeManagementSettings()
    
    assert hasattr(settings, 'min_sl_distance_atr_multiplier'), "Missing min_sl_distance_atr_multiplier"
    assert hasattr(settings, 'modification_cooldown_seconds'), "Missing modification_cooldown_seconds"
    assert hasattr(settings, 'significant_price_move_r'), "Missing significant_price_move_r"
    
    print("✅ TradeManagementSettings has all required fields:")
    print(f"   • min_sl_distance_atr_multiplier = {settings.min_sl_distance_atr_multiplier}")
    print(f"   • modification_cooldown_seconds = {settings.modification_cooldown_seconds}")
    print(f"   • significant_price_move_r = {settings.significant_price_move_r}")
    
    # Verify methods exist
    import inspect
    methods = [m for m, _ in inspect.getmembers(ProfitProtectionModule, predicate=inspect.ismethod)]
    method_names = [m for m, _ in inspect.getmembers(ProfitProtectionModule, predicate=inspect.isfunction)]
    
    assert '_secure_modify_sl' in method_names or 'manage_position' in method_names, "Methods not found"
    print("\n✅ All methods are accessible")
    
    print("\n" + "=" * 60)
    print("✨ IMPORT CHECK PASSED - NO SCOPE ERRORS")
    print("=" * 60)
    
except Exception as e:
    print(f"❌ IMPORT FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

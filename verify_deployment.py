#!/usr/bin/env python3
"""
Deployment Verification Script
Confirms optimized parameters are loaded and ready for trading
"""

import json
import sys
from pathlib import Path
from typing import Dict, Any


def verify_config_exists() -> bool:
    """Check if config_optimized_params.json exists"""
    config_path = Path("config_optimized_params.json")
    if not config_path.exists():
        print(f"❌ FAIL: config_optimized_params.json not found in {Path.cwd()}")
        return False
    print(f"✅ PASS: config_optimized_params.json found")
    return True


def verify_config_format() -> Dict[str, Any]:
    """Verify JSON structure is correct"""
    try:
        with open("config_optimized_params.json") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"❌ FAIL: Invalid JSON format: {e}")
        return {}
    except Exception as e:
        print(f"❌ FAIL: Cannot read config file: {e}")
        return {}
    
    print(f"✅ PASS: config_optimized_params.json is valid JSON")
    
    # Check required sections
    required_keys = ["signal_weights", "exit_config"]
    missing = [k for k in required_keys if k not in config]
    
    if missing:
        print(f"❌ FAIL: Missing required keys: {missing}")
        return {}
    
    print(f"✅ PASS: All required sections present")
    return config


def verify_signal_weights(config: Dict[str, Any]) -> bool:
    """Verify signal weight parameters"""
    if "signal_weights" not in config:
        print("❌ FAIL: signal_weights section missing")
        return False
    
    weights = config["signal_weights"]
    required_weights = ["weight_technical", "weight_ml", "weight_mtf"]
    missing = [k for k in required_weights if k not in weights]
    
    if missing:
        print(f"❌ FAIL: Missing signal weights: {missing}")
        return False
    
    # Validate ranges
    for key, value in weights.items():
        if not isinstance(value, (int, float)):
            print(f"❌ FAIL: {key} is not numeric (got {type(value).__name__})")
            return False
        if value < 0 or value > 1:
            print(f"❌ FAIL: {key}={value} is out of valid range [0, 1]")
            return False
    
    # Check sum
    total = sum(weights.values())
    if total < 0.5 or total > 1.5:
        print(f"❌ FAIL: Signal weights sum to {total} (expected ~1.0)")
        return False
    
    print(f"✅ PASS: Signal weights valid")
    print(f"   • Technical: {weights['weight_technical']:.2f}")
    print(f"   • ML: {weights['weight_ml']:.2f}")
    print(f"   • Multi-Timeframe: {weights['weight_mtf']:.2f}")
    return True


def verify_exit_config(config: Dict[str, Any]) -> bool:
    """Verify exit configuration parameters"""
    if "exit_config" not in config:
        print("❌ FAIL: exit_config section missing")
        return False
    
    exit_cfg = config["exit_config"]
    required_params = ["tp_multiplier", "trailing_activation_r", "time_exit_bars"]
    missing = [k for k in required_params if k not in exit_cfg]
    
    if missing:
        print(f"❌ FAIL: Missing exit parameters: {missing}")
        return False
    
    # Validate TP multiplier
    tp = exit_cfg["tp_multiplier"]
    if not isinstance(tp, (int, float)) or tp < 1.0 or tp > 5.0:
        print(f"❌ FAIL: tp_multiplier={tp} invalid (expected 1.0-5.0)")
        return False
    
    # Validate trailing activation
    trailing = exit_cfg["trailing_activation_r"]
    if not isinstance(trailing, (int, float)) or trailing < 0.1 or trailing > 2.0:
        print(f"❌ FAIL: trailing_activation_r={trailing} invalid (expected 0.1-2.0)")
        return False
    
    # Validate time exit
    time_exit = exit_cfg["time_exit_bars"]
    if not isinstance(time_exit, int) or time_exit < 5 or time_exit > 100:
        print(f"❌ FAIL: time_exit_bars={time_exit} invalid (expected 5-100)")
        return False
    
    print(f"✅ PASS: Exit configuration valid")
    print(f"   • TP Multiplier: {tp:.1f}R")
    print(f"   • Trailing Activation: {trailing:.1f}R")
    print(f"   • Time Exit: {time_exit} bars")
    
    if "partial_profit_levels" in exit_cfg:
        partial = exit_cfg["partial_profit_levels"]
        if isinstance(partial, list) and len(partial) > 0:
            print(f"   • Partial Profit Levels: {len(partial)} configured")
    
    return True


def verify_loader_available() -> bool:
    """Check if parameter_loader.py is available"""
    loader_path = Path("src/deployment/parameter_loader.py")
    if not loader_path.exists():
        print(f"❌ FAIL: Loader module not found at {loader_path}")
        return False
    
    print(f"✅ PASS: parameter_loader.py available")
    return True


def verify_main_integration() -> bool:
    """Check if main.py has been updated with parameter loader import"""
    main_path = Path("main.py")
    if not main_path.exists():
        print(f"⚠️  WARN: main.py not found (may be okay during offline verification)")
        return True
    
    with open(main_path) as f:
        content = f.read()
    
    if "apply_parameters_to_strategies" not in content:
        print(f"❌ FAIL: main.py has no apply_parameters_to_strategies integration")
        return False
    
    if "from src.deployment.parameter_loader import" not in content:
        print(f"❌ FAIL: main.py missing parameter_loader import")
        return False
    
    print(f"✅ PASS: main.py properly integrated")
    return True


def main():
    """Run all verification checks"""
    print("=" * 70)
    print("DEPLOYMENT VERIFICATION - Optimized Parameters")
    print("=" * 70 + "\n")
    
    checks = [
        ("Config File Exists", verify_config_exists),
        ("Config Format Valid", lambda: bool(verify_config_format())),
        ("Loader Available", verify_loader_available),
        ("Main Integration", verify_main_integration),
    ]
    
    results = []
    for name, check_fn in checks:
        print(f"[CHECK] {name}...")
        try:
            result = check_fn()
            results.append((name, result))
        except Exception as e:
            print(f"❌ EXCEPTION: {e}\n")
            results.append((name, False))
    
    # Config content checks (only if config is valid)
    config = verify_config_format()
    if config:
        print(f"\n[CHECK] Signal Weights...")
        results.append(("Signal Weights Validation", verify_signal_weights(config)))
        
        print(f"\n[CHECK] Exit Configuration...")
        results.append(("Exit Configuration Validation", verify_exit_config(config)))
    
    # Summary
    print("\n" + "=" * 70)
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    if passed == total:
        print(f"✅ ALL CHECKS PASSED ({passed}/{total})")
        print("\n🚀 DEPLOYMENT READY - Optimized parameters will be applied at bot startup")
        print("=" * 70 + "\n")
        return 0
    else:
        print(f"❌ DEPLOYMENT CHECK FAILED ({passed}/{total} passed)")
        print("\n⚠️  Fix the issues above before starting the bot")
        print("=" * 70 + "\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
GOLDILOCKS VERIFICATION SCRIPT
===============================
Verifies that Goldilocks parameters are correctly loaded and active.

Usage:
    python scripts/verify_goldilocks.py
"""

import json
from pathlib import Path
from datetime import datetime


def verify_goldilocks_config():
    """Verify Goldilocks parameters in config file"""
    print("="*80)
    print("  GOLDILOCKS PARAMETER VERIFICATION")
    print("="*80)
    print()
    
    config_path = Path("config/optimized_params.json")
    
    if not config_path.exists():
        print("❌ FAIL: config/optimized_params.json not found!")
        return False
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    print(f"📁 Config File: {config_path}")
    print(f"📅 Optimization Date: {config.get('optimization_date', 'N/A')}")
    print(f"🔧 Method: {config.get('optimization_method', 'N/A')}")
    print()
    
    # Verify Goldilocks parameters
    checks = []
    
    # Entry Filters
    entry_filters = config.get('entry_filters', {})
    
    checks.append({
        'name': 'Quality Floor',
        'expected': 70,
        'actual': entry_filters.get('quality_floor'),
        'section': 'entry_filters'
    })
    
    checks.append({
        'name': 'ADX Min',
        'expected': 20,
        'actual': entry_filters.get('adx_min'),
        'section': 'entry_filters'
    })
    
    checks.append({
        'name': 'RSI Upper',
        'expected': 65,
        'actual': entry_filters.get('rsi_upper'),
        'section': 'entry_filters'
    })
    
    checks.append({
        'name': 'Max Spread (pts)',
        'expected': 20,
        'actual': entry_filters.get('max_spread_pts'),
        'section': 'entry_filters'
    })
    
    # Risk Management
    risk_mgmt = config.get('risk_management', {})
    
    checks.append({
        'name': 'ATR SL Multiplier',
        'expected': 2.2,
        'actual': risk_mgmt.get('atr_sl_multiplier'),
        'section': 'risk_management'
    })
    
    checks.append({
        'name': 'ATR TP Multiplier',
        'expected': 3.2,
        'actual': risk_mgmt.get('atr_tp_multiplier'),
        'section': 'risk_management'
    })
    
    checks.append({
        'name': 'Aggressive Compounding',
        'expected': True,
        'actual': risk_mgmt.get('aggressive_compounding'),
        'section': 'risk_management'
    })
    
    checks.append({
        'name': 'Streak Threshold',
        'expected': 3,
        'actual': risk_mgmt.get('streak_threshold'),
        'section': 'risk_management'
    })
    
    checks.append({
        'name': 'Compounding Multiplier',
        'expected': 1.2,
        'actual': risk_mgmt.get('compounding_multiplier'),
        'section': 'risk_management'
    })
    
    # Signal Weights
    signal_weights = config.get('signal_weights', {})
    
    checks.append({
        'name': 'ML Weight',
        'expected': 0.50,
        'actual': signal_weights.get('ml_weight'),
        'section': 'signal_weights'
    })
    
    checks.append({
        'name': 'Technical Weight',
        'expected': 0.50,
        'actual': signal_weights.get('technical_weight'),
        'section': 'signal_weights'
    })
    
    # Display results
    print("─"*80)
    print("  PARAMETER VERIFICATION RESULTS")
    print("─"*80)
    print()
    
    all_pass = True
    for check in checks:
        expected = check['expected']
        actual = check['actual']
        passed = (expected == actual)
        
        if not passed:
            all_pass = False
        
        status = "✅ PASS" if passed else "❌ FAIL"
        section = check['section']
        
        print(f"  {check['name']:<30} {status}  Expected: {expected:<10} Actual: {actual}")
    
    print()
    print("─"*80)
    
    if all_pass:
        print("  ✅ ALL CHECKS PASSED - Goldilocks config is correct!")
        print()
        print("  ⚠️  IMPORTANT: Bot must be RESTARTED to load these parameters!")
        print("     The bot loaded OLD parameters at startup (06:11:05)")
        print("     Hot-reload may not have detected the change yet.")
        print()
        print("  📋 Next Steps:")
        print("     1. Stop the bot (Ctrl+C)")
        print("     2. Restart: python main.py")
        print("     3. Verify in logs: 'ML Weight: 0.50' (not 0.45)")
    else:
        print("  ❌ SOME CHECKS FAILED - Config needs correction!")
        print()
        failed = [c['name'] for c in checks if c['expected'] != c['actual']]
        print(f"  Failed parameters: {', '.join(failed)}")
    
    print("─"*80)
    print()
    
    return all_pass


def check_bot_status():
    """Check if bot is running with correct parameters"""
    print("="*80)
    print("  BOT STATUS CHECK")
    print("="*80)
    print()
    
    log_file = Path("logs/forex_bot.log")
    
    if not log_file.exists():
        print("⚠️  No log file found yet")
        return
    
    # Read last 500 lines
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        lines = f.readlines()
    
    # Find parameter loading
    param_lines = [line for line in lines if 'ML Weight:' in line or 'Quality Floor' in line or 'ATR' in line]
    
    if param_lines:
        print("  Last parameter load detected:")
        for line in param_lines[-5:]:
            # Clean up the line
            clean_line = line.strip()
            if '|' in clean_line:
                # Extract the message part after last |
                parts = clean_line.split('|')
                message = parts[-1].strip()
                print(f"    {message}")
        print()
        
        # Check if it's Goldilocks or Aggressive
        last_param_line = param_lines[-1]
        if '0.45' in last_param_line:
            print("  ❌ Bot is running with OLD Aggressive parameters (ML Weight: 0.45)")
            print("  ✅ Goldilocks requires: ML Weight: 0.50")
            print()
            print("  🔄 ACTION REQUIRED: Restart the bot!")
        elif '0.50' in last_param_line:
            print("  ✅ Bot is running with Goldilocks parameters (ML Weight: 0.50)")
        else:
            print("  ⚠️  Could not determine which parameters are loaded")
    else:
        print("  ⚠️  No parameter loading messages found in logs")
    
    print()


def main():
    """Main verification"""
    print()
    
    # Verify config file
    config_ok = verify_goldilocks_config()
    
    # Check bot status
    check_bot_status()
    
    # Summary
    print("="*80)
    print("  SUMMARY")
    print("="*80)
    print()
    
    if config_ok:
        print("  ✅ Config file: GOLDILOCKS PARAMETERS CORRECT")
        print("  ⚠️  Bot status: NEEDS RESTART to load new config")
        print()
        print("  📋 Command to restart:")
        print("     1. Press Ctrl+C in bot terminal")
        print("     2. Run: python main.py")
        print()
        print("  ✓ After restart, you should see in logs:")
        print("     • ML Weight: 0.50")
        print("     • ATR SL: 2.2")
        print("     • Quality Floor: 70")
    else:
        print("  ❌ Config file has errors - needs fixing!")
    
    print()
    print("="*80)


if __name__ == "__main__":
    main()

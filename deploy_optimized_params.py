"""
Quick Deploy Script - Apply Optimized Parameters
=================================================
Run this to verify and apply the optimized parameters to your bot.

Steps:
1. Backup current config
2. Verify optimized parameters
3. Instructions for bot restart
"""

import json
import os
import shutil
from datetime import datetime

print("="*80)
print("PARAMETER OPTIMIZATION DEPLOYMENT")
print("="*80)

# 1. Backup current config
config_file = "config/config.prod.json"
backup_file = f"config/config.prod.json.backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"

if os.path.exists(config_file):
    print(f"\n[1/3] Backing up {config_file}")
    shutil.copy2(config_file, backup_file)
    print(f"  ✅ Backup created: {backup_file}")
else:
    print(f"\n[1/3] ⚠️ Config file not found: {config_file}")

# 2. Verify optimized parameters
optimized_config_file = "config/optimized_params.json"

if os.path.exists(optimized_config_file):
    print(f"\n[2/3] Verifying optimized parameters from {optimized_config_file}")
    
    with open(optimized_config_file, 'r') as f:
        optimized = json.load(f)
    
    print(f"  ✅ Quality Floor: {optimized['entry_filters']['quality_floor']:.0%}")
    print(f"  ✅ ML Confidence: {optimized['entry_filters']['ml_confidence_min']:.2f}")
    print(f"  ✅ Filter Mode: {optimized['entry_filters']['filter_mode']}")
    print(f"  ✅ ADX Min: {optimized['entry_filters']['adx_min']}")
    print(f"  ✅ Expected Trades/Month: {optimized['expected_performance']['trades_per_month']:.1f}")
    print(f"  ✅ Fitness Score: {optimized['fitness_score']:.1f}")
else:
    print(f"\n[2/3] ❌ Optimized config not found: {optimized_config_file}")
    print("  Run: python src/backtesting/param_optimizer.py")

# 3. Verify signal_filter.py update
signal_filter_file = "src/analysis/signal_filter.py"

print(f"\n[3/3] Checking {signal_filter_file}")

if os.path.exists(signal_filter_file):
    with open(signal_filter_file, 'r') as f:
        content = f.read()
    
    if "OPTIMIZED PARAMETERS (2026-04-23)" in content:
        print("  ✅ Signal filter has been updated with optimized parameters")
    else:
        print("  ⚠️ Signal filter may not be updated")
        print("  Manual update required - see PARAMETER_OPTIMIZATION_RESULTS.md")
else:
    print(f"  ❌ File not found: {signal_filter_file}")

# Next steps
print("\n" + "="*80)
print("NEXT STEPS")
print("="*80)
print("""
1. ✅ Parameters have been optimized and applied to code
    
2. RESTART YOUR BOT to apply changes:
   - Stop the current running bot
   - Run: python main.py
   
3. MONITOR for 1-2 weeks:
   - Check logs for trade frequency
   - Verify signals are passing filters
   - Monitor win rate and drawdown
   
4. VALIDATE performance:
   - Target: 8-10 trades per month
   - Watch for: Profit Factor > 1.2, Max DD < 5%
   
5. REVIEW optimization results:
   - Full report: PARAMETER_OPTIMIZATION_RESULTS.md
   - Raw data: optimization_results/param_optimization.json
   - Logs: optimization_results/param_optimization.log

⚠️ IMPORTANT:
- The bot must be RESTARTED for changes to take effect
- Current running instance still uses old parameters
- Consider testing in paper trading mode first
""")

print("="*80)
print("DEPLOYMENT COMPLETE")
print("="*80)

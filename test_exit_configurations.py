#!/usr/bin/env python3
"""
Advanced Exit Strategy Optimization Test
Tests optimized parameter sets for advanced exit conditions
"""

import logging
from src.trading.advanced_exit_handler import AdvancedExitHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Define parameter sets to test
exit_configurations = {
    "current": {
        "trailing_stop_r_trigger": 1.5,
        "trailing_stop_r_trail": 1.0,
        "breakeven_trigger_r": 1.0,
        "breakeven_offset_pips": 2,
        "max_hold_time_minutes": 480,
        "description": "Current Production Config (54.6% baseline)"
    },
    "aggressive_trailing": {
        "trailing_stop_r_trigger": 1.2,  # Trigger earlier (1.2R instead of 1.5R)
        "trailing_stop_r_trail": 0.75,   # Trail tighter (0.75R instead of 1.0R)
        "breakeven_trigger_r": 0.8,      # Secure BE earlier
        "breakeven_offset_pips": 1,      # Tighter offset
        "max_hold_time_minutes": 420,    # Shorter max hold (7h instead of 8h)
        "description": "Aggressive Trailing (Capture more mid-moves)"
    },
    "conservative_trailing": {
        "trailing_stop_r_trigger": 2.0,  # Trigger later (wait for bigger moves)
        "trailing_stop_r_trail": 1.5,    # Trail wider
        "breakeven_trigger_r": 1.2,      # Conservative BE protection
        "breakeven_offset_pips": 3,      # Wider offset
        "max_hold_time_minutes": 540,    # Longer max hold (9h)
        "description": "Conservative Trailing (Let winners run longer)"
    },
    "fast_scalper": {
        "trailing_stop_r_trigger": 0.75, # Very early trigger
        "trailing_stop_r_trail": 0.5,    # Very tight trail
        "breakeven_trigger_r": 0.5,      # Protect BE quickly
        "breakeven_offset_pips": 1,
        "max_hold_time_minutes": 240,    # 4h max hold
        "description": "Fast Scalper (Lock profits quickly)"
    },
    "extended_hold": {
        "trailing_stop_r_trigger": 2.5,  # Very late trigger
        "trailing_stop_r_trail": 1.5,    # Wide trail
        "breakeven_trigger_r": 1.5,      # Late BE trigger
        "breakeven_offset_pips": 5,      # Wide offset
        "max_hold_time_minutes": 600,    # 10h max hold
        "description": "Extended Hold (Trend follower)"
    }
}

def print_configuration_summary():
    """Print summary of all test configurations"""
    print("\n" + "="*70)
    print("ADVANCED EXIT STRATEGY PARAMETER SETS FOR OPTIMIZATION")
    print("="*70)
    
    for name, params in exit_configurations.items():
        print(f"\n📊 {name.upper()}")
        print(f"   Description: {params['description']}")
        print(f"   Trailing Stop Trigger: {params['trailing_stop_r_trigger']}R")
        print(f"   Trailing Stop Trail: {params['trailing_stop_r_trail']}R")
        print(f"   Breakeven Trigger: {params['breakeven_trigger_r']}R")
        print(f"   Breakeven Offset: {params['breakeven_offset_pips']} pips")
        print(f"   Max Hold Time: {params['max_hold_time_minutes']} minutes ({params['max_hold_time_minutes']/60:.1f}h)")

def apply_configuration(handler: AdvancedExitHandler, config: dict) -> None:
    """Apply configuration parameters to advanced exit handler"""
    handler.trailing_stop_r_trigger = config['trailing_stop_r_trigger']
    handler.trailing_stop_r_trail = config['trailing_stop_r_trail']
    handler.breakeven_trigger_r = config['breakeven_trigger_r']
    handler.breakeven_offset_pips = config['breakeven_offset_pips']
    handler.max_hold_time_minutes = config['max_hold_time_minutes']

def test_configuration(name: str, config: dict) -> None:
    """Test a specific configuration"""
    handler = AdvancedExitHandler(logger=logger)
    apply_configuration(handler, config)
    
    logger.info(f"\n✅ {name} configuration applied successfully")
    logger.info(f"   Use Trailing Stop: {handler.use_trailing_stop}")
    logger.info(f"   Use Breakeven Stop: {handler.use_breakeven_stop}")
    logger.info(f"   Use Time-based Exit: {handler.use_time_based_exit}")
    logger.info(f"   Use Partial Profits: {handler.use_partial_profits}")

if __name__ == "__main__":
    print_configuration_summary()
    
    print("\n" + "="*70)
    print("TESTING CONFIGURATIONS")
    print("="*70)
    
    for name, config in exit_configurations.items():
        test_configuration(name, config)
    
    print("\n" + "="*70)
    print("OPTIMIZATION STRATEGY")
    print("="*70)
    print("""
The current production config (54.6% win rate) already has all advanced
exits enabled. The next optimization variations to test are:

1. AGGRESSIVE_TRAILING: Capture more mid-range moves (potential +0.5-1.0%)
   - Triggers trailing stop earlier (1.2R vs 1.5R)
   - Tighter trail distance (0.75R vs 1.0R)
   - Result: Could improve win rate by locking profits at better levels

2. FAST_SCALPER: Very quick profit-taking (potential +0.3-0.8%)
   - Trailing stop triggers at 0.75R
   - Tight 0.5R trail
   - Shorter max hold time
   - Result: Could reduce losses on choppy days

3. EXTENDED_HOLD: Trend-following (potential +0.2-0.5%)
   - Later triggers allow trends to develop
   - Wider trailing stops
   - Could maximize trending days

RECOMMENDATION:
Test AGGRESSIVE_TRAILING first as it balances profit-taking with trend-following.
It should show measurable improvement over the current 54.6% baseline.

FILES TO MODIFY FOR TESTING:
- src/trading/advanced_exit_handler.py (lines 49-57 config parameters)
- run_backtest.py (execute and measure win rate)
""")
    
    print("="*70)
    print("Next step: Run backtest with AGGRESSIVE_TRAILING configuration")
    print("="*70 + "\n")

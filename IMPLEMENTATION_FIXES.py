"""
Implementation fixes for MT5 Trading Bot Logic Optimization

This file documents the key changes that need to be applied to fix:
1. SL Strangling (Early Exit)
2. MT5 Error 10025 (No Changes in Modifications)
3. Tracker Sync Discrepancies
4. Safety Guard Bypasses
5. Expectancy Split-Brain Logic

STATUS: Creating a patch file to track all required changes
"""

# Fix #1: profit_protection_module.py - Add fields to TradeManagementSettings
# ADD AFTER trailing_atr_by_regime:
"""
    # === FIX #1A: Min SL Distance Floor (prevents 30% tightening spiral) ===
    min_sl_distance_atr_multiplier: float = 1.5  # SL must be at least 1.5x ATR away from current price
    
    # === FIX #1B: Modification Cooldown (prevents SL spam and broker rate-limiting) ===
    modification_cooldown_seconds: int = 300  # 5 minutes: do not tighten SL more than once per 5 min
    significant_price_move_r: float = 1.0     # Only modify SL if price moved > 1.0R (overrides cooldown)
"""

# Fix #1: profit_protection_module.py - Add tracking to position state initialization
# CHANGE THIS:
"""
             self.position_states[pos_id] = {
                 'symbol': position.symbol,
                 'entry_price': position.entry_price,
                 'initial_risk_price': initial_risk_price,
                 'breakeven_reached': False,
                 'trailing_active': False,
                 'scaled_out': False,
                 'partial_hits': set(),
                 'last_modified_sl': position.stop_loss,
                 'peak_profit_price': position.current_price,
                 'market_regime': None,
                 'volatility_regime': None,
             }
"""
# TO THIS:
"""
             self.position_states[pos_id] = {
                 'symbol': position.symbol,
                 'entry_price': position.entry_price,
                 'initial_risk_price': initial_risk_price,
                 'breakeven_reached': False,
                 'trailing_active': False,
                 'scaled_out': False,
                 'partial_hits': set(),
                 'last_modified_sl': position.stop_loss,
                 'peak_profit_price': position.current_price,
                 'market_regime': None,
                 'volatility_regime': None,
                 'last_sl_modification_time': None,  # === FIX #1B: Cooldown tracking ===
             }
"""

# Fix #1: profit_protection_module.py - Update _apply_velocity_trailing() function
# Replace the entire function with dynamic trailing logic (0.8-1.2R range instead of 0.4R)
# and add Min_SL_Distance_ATR floor check

# Fix #2: mt5_broker.py - Add pre-check to modify_order() function
# AT THE START of modify_order(), after getting position and normalizing SL/TP:
"""
        # === FIX #2: Pre-check to prevent MT5 Error 10025 (no changes) ===
        current_sl = pos.sl
        if current_sl and current_sl != 0:
            # Minimum change = broker_min_points * 10 (approximately 1-2 pips)
            # For 5-digit brokers: point is 0.00001, so min is 0.0001 (1 pip)
            min_points = info.point * 10  # ~1-2 pips
            sl_change = abs(final_sl - current_sl)
            
             if sl_change < min_points:
                logger.debug(
                    f"[FIX_10025_SKIP] {pos.symbol} ticket {order_id} | "
                    f"Change {sl_change:.6f} < minimum {min_points:.6f}. Skipping modification."
                )
                return False
"""

# Fix #3: position_tracker.py - Implement Verify_Ticket sub-routine
# Add a method that checks HistorySelect for missing tickets instead of hard reset

# Fix #4: trade_admission_controller.py - Strengthen SPREAD_ATR_FILTER
# Disable bypass of spread filters even in "Hunter Mode" or "News Guard"
# Implement Max_Spread limit check (reject if current spread > 2.0x average)

# Fix #5: Create centralized Calculate_Expectancy function
# Location: src/risk/risk_calculator.py or new utils file
# This function should be called by all modules that need expectancy calculations

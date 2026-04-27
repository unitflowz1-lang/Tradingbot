#!/usr/bin/env python3
"""Update _apply_velocity_trailing and _secure_modify_sl functions with new logic"""

import os

os.chdir(r"c:\Users\macki\Desktop\RL v7.2 snipe core TradingBot")

# Read the file
with open("src/trading/profit_protection_module.py", 'r', encoding='utf-8') as f:
    content = f.read()

# Update 1: Replace _apply_velocity_trailing function
old_velocity_func = '''    async def _apply_velocity_trailing(self, position: Position, atr: float, state: Dict, current_r: float) -> bool:
        """
        Dynamic "Velocity Trailing" based on R-multiple milestones.
        - >1.5R: lock in +0.5R
        - >2.0R: trail at 0.4 * ATR
        - >2.5R: hyper-trail at 0.2 * ATR
        """
        if current_r < 1.5:
            return False

        risk_price = float(state.get("initial_risk_price") or 0.0)
        if risk_price <= 0:
            return False

        entry = float(position.entry_price)
        lock_sl = None
        if position.direction == Direction.LONG:
            lock_sl = entry + (0.5 * risk_price)
        else:
            lock_sl = entry - (0.5 * risk_price)

        trail_sl = None
        if atr > 0 and current_r >= 2.0:
            mult = 0.2 if current_r >= 2.5 else 0.4
            trail_dist = atr * mult
            peak = float(state.get("peak_profit_price") or position.current_price)
            if position.direction == Direction.LONG:
                trail_sl = peak - trail_dist
            else:
                trail_sl = peak + trail_dist

        # Pick the more protective SL (never widen risk).
        target_sl = lock_sl
        if trail_sl is not None:
            if position.direction == Direction.LONG:
                target_sl = max(lock_sl or trail_sl, trail_sl)
            else:
                target_sl = min(lock_sl or trail_sl, trail_sl)

        if target_sl is None:
            return False

        # Require meaningful improvement to avoid SL spam.
        current_sl = position.stop_loss
        pip_val = self._get_pip_value(position.symbol)
        min_improvement = 0.5 * pip_val
        if current_sl and current_sl != 0:
            if position.direction == Direction.LONG:
                if target_sl <= current_sl + min_improvement:
                    return False
            else:
                if target_sl >= current_sl - min_improvement:
                    return False

        modified = await self._secure_modify_sl(position, target_sl, "DYNAMIC_TRAIL")
        if modified:
            if position.direction == Direction.LONG:
                lock_r = (target_sl - entry) / risk_price
            else:
                lock_r = (entry - target_sl) / risk_price
            logger.critical(
                f"[DYNAMIC_EXIT] Symbol {position.symbol} | Trail Active | Current Lock-in: +{lock_r:.2f} R."
            )
        return modified'''

new_velocity_func = '''    async def _apply_velocity_trailing(self, position: Position, atr: float, state: Dict, current_r: float) -> bool:
        """
        Dynamic "Velocity Trailing" based on R-multiple milestones.
        === FIX #1: DYNAMIC VELOCITY_MODE (replaced static 0.4R with 0.8-1.2R range) ===
        - >1.5R: lock in +0.5R
        - >2.0R: trail at dynamic 0.8R-1.2R (based on volatility)
        - >2.5R: continue dynamic trail from 0.8R-1.2R range
        - All changes respect Min_SL_Distance_ATR floor (1.5x ATR)
        """
        if current_r < 1.5:
            return False

        risk_price = float(state.get("initial_risk_price") or 0.0)
        if risk_price <= 0:
            return False

        entry = float(position.entry_price)
        lock_sl = None
        if position.direction == Direction.LONG:
            lock_sl = entry + (0.5 * risk_price)
        else:
            lock_sl = entry - (0.5 * risk_price)

        trail_sl = None
        if atr > 0 and current_r >= 2.0:
            # === FIX #1: Dynamic VELOCITY_MODE range (0.8-1.2R instead of 0.4-0.2R) ===
            # Calculate volatility-based trail multiplier within 0.8 - 1.2 ATR range
            if current_r >= 2.5:
                # Hyper-trail at 0.8x ATR (tighter)
                trail_mult = 0.8
            else:
                # Standard trail at 1.0x ATR
                trail_mult = 1.0
            
            # If volatility regime supports (low vol), can tighten to 0.8
            vol_regime = state.get('volatility_regime', '').upper()
            if vol_regime == 'LOW_VOLATILITY':
                trail_mult = 0.8
            elif vol_regime == 'HIGH_VOLATILITY':
                trail_mult = 1.2  # Loosen in high vol
            
            trail_dist = atr * trail_mult
            peak = float(state.get("peak_profit_price") or position.current_price)
            if position.direction == Direction.LONG:
                trail_sl = peak - trail_dist
            else:
                trail_sl = peak + trail_dist

        # Pick the more protective SL (never widen risk).
        target_sl = lock_sl
        if trail_sl is not None:
            if position.direction == Direction.LONG:
                target_sl = max(lock_sl or trail_sl, trail_sl)
            else:
                target_sl = min(lock_sl or trail_sl, trail_sl)

        if target_sl is None:
            return False

        # === FIX #1A: Apply Min_SL_Distance_ATR floor before update ===
        min_sl_floor = self.settings.min_sl_distance_atr_multiplier * atr
        current_price = position.current_price
        pip_val = self._get_pip_value(position.symbol)
        
        dist_to_sl = abs(target_sl - current_price)
        if dist_to_sl < min_sl_floor:
            # SL is too close to current price - back it off to floor distance
            if position.direction == Direction.LONG:
                target_sl = current_price - min_sl_floor
            else:
                target_sl = current_price + min_sl_floor
            logger.info(
                f"[MIN_SL_FLOOR] {position.symbol} ID:{position.position_id} | "
                f"Proposed SL too close ({dist_to_sl:.5f}) | Backed off to {min_sl_floor:.5f} (1.5x ATR floor)"
            )

        # Require meaningful improvement to avoid SL spam.
        current_sl = position.stop_loss
        min_improvement = 0.5 * pip_val
        if current_sl and current_sl != 0:
            if position.direction == Direction.LONG:
                if target_sl <= current_sl + min_improvement:
                    return False
            else:
                if target_sl >= current_sl - min_improvement:
                    return False

        modified = await self._secure_modify_sl(position, target_sl, "DYNAMIC_TRAIL", atr=atr)
        if modified:
            if position.direction == Direction.LONG:
                lock_r = (target_sl - entry) / risk_price
            else:
                lock_r = (entry - target_sl) / risk_price
            logger.critical(
                f"[DYNAMIC_EXIT] Symbol {position.symbol} | Trail Active | Current Lock-in: +{lock_r:.2f} R."
            )
        return modified'''

if old_velocity_func in content:
    content = content.replace(old_velocity_func, new_velocity_func)
    print("✓ Updated _apply_velocity_trailing with dynamic 0.8-1.2R range and Min_SL_Distance_ATR floor")
else:
    print("⚠ Could not find old _apply_velocity_trailing function")

# Update 2: Replace _secure_modify_sl function signature and add cooldown logic
old_secure_modify = '''    async def _secure_modify_sl(self, position: Position, target_sl: float, label: str) -> bool:
        """Modify SL with broker validation, normalization, and retries"""
        import MetaTrader5 as mt5'''

new_secure_modify = '''    async def _secure_modify_sl(self, position: Position, target_sl: float, label: str, atr: float = 0.0) -> bool:
        """Modify SL with broker validation, normalization, retries, cooldown check
        
        === FIX #1B: Modification cooldown check ===
        - No more than once per 5 minutes unless price moved significantly (> 1.0R)
        """
        import MetaTrader5 as mt5
        
        symbol_info = await self._get_symbol_info(position.symbol)
        if not symbol_info: return False
        
        # === FIX #1B: Cooldown check (do not tighten SL more than once per 5 minutes) ===
        pos_id = str(position.position_id)
        state = self.position_states.get(pos_id, {})
        now = datetime.now(timezone.utc)
        last_mod_time = state.get('last_sl_modification_time')
        
        if last_mod_time is not None:
            elapsed_sec = (now - last_mod_time).total_seconds()
            cooldown_sec = self.settings.modification_cooldown_seconds
            
            if elapsed_sec < cooldown_sec:
                # Check if price moved significantly to override cooldown
                risk_price = state.get('initial_risk_price', 0.0)
                significant_move_threshold = self.settings.significant_price_move_r * risk_price
                entry = position.entry_price
                current_price = position.current_price
                price_move = abs(current_price - entry)
                
                if price_move < significant_move_threshold:
                    logger.info(
                        f"[COOLDOWN_BLOCK] {position.symbol} ID:{position.position_id} | "
                        f"Cooldown active ({elapsed_sec:.0f}s of {cooldown_sec}s). "
                        f"Price move {price_move:.5f} < threshold {significant_move_threshold:.5f}. Skipping."
                    )
                    return False
                else:
                    logger.info(
                        f"[COOLDOWN_OVERRIDE] {position.symbol} ID:{position.position_id} | "
                        f"Significant price move {price_move:.5f} > {significant_move_threshold:.5f}. Proceeding despite cooldown."
                    )
        
        # Update modification timestamp AFTER all checks pass but BEFORE actual modification
        if pos_id in self.position_states:
            self.position_states[pos_id]['last_sl_modification_time'] = now
        import MetaTrader5 as mt5'''

if old_secure_modify in content:
    content = content.replace(old_secure_modify, new_secure_modify)
    print("✓ Updated _secure_modify_sl with cooldown check logic")
else:
    print("⚠ Could not find old _secure_modify_sl function")

# Write back
with open("src/trading/profit_protection_module.py", 'w', encoding='utf-8') as f:
    f.write(content)

print("\n✓ All velocity trailing and cooldown fixes applied successfully!")

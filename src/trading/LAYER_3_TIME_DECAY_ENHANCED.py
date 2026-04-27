"""
LAYER 3: TIME-DECAY STOP LOSS - ENHANCED WITH PRE-FLIGHT CHECKS
================================================================

This is the production-ready version with all three pre-flight validations:
1. MT5 SYMBOL_TRADE_STOPS_LEVEL validation (prevents Error 10016)
2. Bars counter verification (per-bar, not per-pulse)
3. Auto-Rotation & Harvest conflict detection

Use this instead of LAYER_3_TIME_DECAY_IMPLEMENTATION.py
"""

import logging
import os
import asyncio
import re
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from src.models import Position, Direction

logger = logging.getLogger(__name__)


class TimeDecayStopLossManager:
    """
    Manages time-decay stop loss logic for stagnant positions with full MT5 constraint validation.
    
    Features:
    - Detects stagnant trades (drawdown + no price progress)
    - Progressive SL shrinkage (15p → 10p → 5p per stage)
    - Validates against broker's SYMBOL_TRADE_STOPS_LEVEL (prevents Error 10016)
    - Detects if bars_since_entry is incrementing per-pulse vs per-bar
    - Coordinates with Auto-Rotation and Harvest engines
    - Safety floor: Never shrink within 10 pips of entry
    - Shadow mode logging before actual execution
    """
    
    # ========== CONFIGURATION ==========
    SHADOW_MODE = False  # LIVE MODE: Set to True for testing/validation only
    STAGNATION_BAR_THRESHOLD = 15
    STAGNATION_PRICE_THRESHOLD_PIPS = 5.0
    MIN_DRAWDOWN_R = -0.50
    MAX_DRAWDOWN_R = -0.05
    SHRINKAGE_SCHEDULE = {
        15: 15.0,   # Bars 15-24: Shrink by 15 pips
        25: 10.0,   # Bars 25-39: Shrink by 10 pips
        40: 5.0,    # Bars 40+:   Shrink by 5 pips
    }
    SAFETY_FLOOR_PIPS = 10.0
    MIN_DISTANCE_FROM_PRICE_PIPS = 3.0
    
    def __init__(self):
        """Initialize manager with pre-flight tracking"""
        self.decay_tracking: Dict[str, Dict[str, Any]] = {}
        self.bars_counter_history: Dict[str, list] = {}  # For detecting pulse vs bar increments
        self.cooldown_list: Dict[str, datetime] = {}  # Track positions in cooldown (failed modifications)
        self.execution_cooldown: Dict[str, Dict[str, Any]] = {}  # Track failed MT5 execution attempts with error codes
        logger.info("[LAYER_3_INIT] Time-Decay Manager initialized (SHADOW_MODE=%s)", self.SHADOW_MODE)
        logger.info("[LAYER_3_INIT] Pre-flight checks active: trade_stops_level, bars_counter, rotation_coordination")
        logger.info("[LAYER_3_INIT] Cooldown list active: 15-minute timeout for failed modification attempts")
        logger.info("[LAYER_3_INIT] Execution cooldown active: 15-minute timeout for MT5 broker rejection")
    
    def get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol"""
        if 'JPY' in symbol.upper():
            return 0.01
        return 0.0001
    
    # ========== COOLDOWN LIST MANAGEMENT ==========
    
    def is_in_cooldown(self, position_id: str) -> bool:
        """Check if position is in modification cooldown (15 minutes)"""
        if position_id not in self.cooldown_list:
            return False
        
        cooldown_time = self.cooldown_list[position_id]
        elapsed = (datetime.now(timezone.utc) - cooldown_time).total_seconds()
        
        if elapsed >= 900:  # 15 minutes = 900 seconds
            del self.cooldown_list[position_id]
            logger.debug("[COOLDOWN_EXPIRED] Position %s | Cooldown expired, re-enabling modifications", position_id)
            return False
        
        remaining_seconds = 900 - elapsed
        logger.debug("[COOLDOWN_ACTIVE] Position %s | Still in cooldown (%.0f seconds remaining)", position_id, remaining_seconds)
        return True
    
    def add_to_cooldown(self, position_id: str) -> None:
        """Add position to cooldown list after failed modification"""
        self.cooldown_list[position_id] = datetime.now(timezone.utc)
        logger.info("[COOLDOWN_ADDED] Position %s | Added to 15-minute cooldown", position_id)
    
    # ========== EXECUTION COOLDOWN MANAGEMENT (MT5 Error Tracking) ==========
    
    def is_in_execution_cooldown(self, ticket: str) -> bool:
        """Check if ticket is in execution cooldown due to MT5 rejection"""
        if ticket not in self.execution_cooldown:
            return False
        
        cooldown_data = self.execution_cooldown[ticket]
        cooldown_time = cooldown_data['time']
        elapsed = (datetime.now(timezone.utc) - cooldown_time).total_seconds()
        
        if elapsed >= 900:  # 15 minutes = 900 seconds
            error_code = cooldown_data.get('error_code', 'UNKNOWN')
            del self.execution_cooldown[ticket]
            logger.debug(
                "[EXECUTION_COOLDOWN_EXPIRED] Ticket %s | Cooldown expired (error: %s) | Re-enabling modifications",
                ticket,
                error_code,
            )
            return False
        
        remaining_seconds = 900 - elapsed
        error_code = cooldown_data.get('error_code', 'UNKNOWN')
        logger.debug(
            "[EXECUTION_COOLDOWN_ACTIVE] Ticket %s | Still in cooldown (%.0f seconds remaining) | "
            "Last Error Code: %s | Reason: %s",
            ticket,
            remaining_seconds,
            error_code,
            cooldown_data.get('reason', 'Unknown'),
        )
        return True
    
    def add_to_execution_cooldown(self, ticket: str, error_code: int, reason: str) -> None:
        """Add ticket to execution cooldown after MT5 broker rejection"""
        self.execution_cooldown[ticket] = {
            'time': datetime.now(timezone.utc),
            'error_code': error_code,
            'reason': reason,
            'attempts': self.execution_cooldown.get(ticket, {}).get('attempts', 0) + 1,
        }
        logger.warning(
            "[EXECUTION_COOLDOWN_ADDED] Ticket %s | Added to 15-minute cooldown | "
            "Error Code: %s | Reason: %s | Total Attempts: %d",
            ticket,
            error_code,
            reason,
            self.execution_cooldown[ticket]['attempts'],
        )
    
    # ========== PRE-FLIGHT CHECK #1: MT5 TRADE STOPS LEVEL VALIDATION ==========
    
    async def validate_with_broker(
        self,
        symbol: str,
        proposed_sl: float,
        current_price: float,
        mt5_symbol_info: Any,
    ) -> Tuple[bool, str]:
        """
        Validate proposed SL against broker's minimum stop level constraints with 100% safety buffer.
        
        This is the 'Test-Before-Fail' logic:
        - Fetches symbol_info from MT5
        - Calculates min_stop_distance = trade_stops_level * point
        - Ensures abs(proposed_sl - current_price) > min_stop_distance * 2.0 (100% buffer)
        - Prevents [LAYER3_FAILED] by self-censoring invalid orders
        
        Args:
            symbol: Trading symbol (e.g., 'EUR/USD')
            proposed_sl: Proposed stop loss price
            current_price: Current market price (bid/ask)
            mt5_symbol_info: MT5 symbol info object
            
        Returns:
            (is_valid, reason_string)
        """
        try:
            # Ensure symbol_info is not None
            if mt5_symbol_info is None:
                return False, f"Symbol {symbol} | symbol_info is None. Cannot validate broker constraints."
            
            # Extract broker constraints
            trade_stops_level = float(getattr(mt5_symbol_info, 'trade_stops_level', 0) or 0)
            point = float(getattr(mt5_symbol_info, 'point', 0.0001) or 0.0001)
            
            # Calculate minimum distance required (base broker constraint)
            min_stop_distance = trade_stops_level * point
            
            # Calculate actual distance between proposed SL and current price
            actual_distance = abs(proposed_sl - current_price)
            
            # Apply 100% safety buffer: require 2x the broker minimum
            required_distance = min_stop_distance * 2.0
            
            # Validate: actual distance must be greater than required distance
            if actual_distance <= required_distance:
                deficit = required_distance - actual_distance
                reason = (
                    f"Symbol {symbol} | Proposed SL: {proposed_sl:.5f} | Current Price: {current_price:.5f} | "
                    f"Actual Distance: {actual_distance:.5f} | Required Distance: {required_distance:.5f} "
                    f"(trade_stops_level {trade_stops_level} * point {point} * 2.0 safety buffer) | "
                    f"Deficit: {deficit:.5f} | Stop Level violation detected."
                )
                return False, reason
            
            # Validation passed
            reason = (
                f"Symbol {symbol} | Proposed SL: {proposed_sl:.5f} | Current Price: {current_price:.5f} | "
                f"Actual Distance: {actual_distance:.5f} | Required Distance: {required_distance:.5f} | "
                f"Status: ✓ PASS - Safe to execute"
            )
            return True, reason
            
        except Exception as e:
            return False, f"Symbol {symbol} | Exception during validation: {str(e)}"
    
    async def validate_sl_against_broker_constraints(
        self,
        position: Position,
        proposed_sl: float,
        symbol_info: Any,
        current_tick: Any,
    ) -> Tuple[bool, str]:
        """
        PRE-FLIGHT CHECK #1: Validate proposed SL against broker's SYMBOL_TRADE_STOPS_LEVEL.
        
        Prevents MT5 Error 10016 (ERR_INVALID_STOPS) by checking:
        1. Trade stops level (minimum distance in points)
        2. Freeze level (where orders are frozen)
        3. Spread (bid-ask gap)
        
        Args:
            position: Position object
            proposed_sl: Proposed stop loss price
            symbol_info: MT5 symbol info object
            current_tick: Current bid/ask tick
            
        Returns:
            (is_valid, reason_string)
        """
        try:
            # Extract broker constraints
            trade_stops_level = float(getattr(symbol_info, 'trade_stops_level', 0) or 0)
            freeze_level = float(getattr(symbol_info, 'trade_freeze_level', 0) or 0)
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
            
            # Current price (bid for LONG, ask for SHORT)
            bid = float(getattr(current_tick, 'bid', 0) or 0)
            ask = float(getattr(current_tick, 'ask', 0) or 0)
            current_price = bid if position.direction == Direction.LONG else ask
            
            # Spread in price units
            spread_price = abs(ask - bid)
            
            # Calculate minimum required distance
            min_distance_points = max(trade_stops_level, freeze_level)
            min_distance_price = (min_distance_points * point) + (0.2 * point)  # +0.2 point buffer
            
            # Check actual distance
            actual_distance = abs(proposed_sl - current_price)
            
            # Pre-flight log
            logger.debug(
                "[BROKER_CONSTRAINTS_CHECK] %s | "
                "trade_stops_level=%d pts | freeze_level=%d pts | "
                "min_distance=%.5f | actual_distance=%.5f",
                position.symbol,
                trade_stops_level,
                freeze_level,
                min_distance_price,
                actual_distance,
            )
            
            if actual_distance < min_distance_price:
                reason = (
                    f"SL too close to price ({actual_distance:.5f}) < "
                    f"min_required ({min_distance_price:.5f}). "
                    f"Trade stops level: {trade_stops_level} points, Freeze: {freeze_level} points"
                )
                return False, reason
            
            return True, "OK"
        
        except Exception as e:
            reason = f"Validation error: {str(e)}"
            logger.warning("[BROKER_CONSTRAINTS_ERROR] %s: %s", position.symbol, reason)
            return False, reason
    
    # ========== PRE-FLIGHT CHECK #2: BARS COUNTER VERIFICATION ==========
    
    def verify_bars_increment_frequency(
        self,
        position_id: str,
        current_bars: int,
        timestamp: datetime,
    ) -> Tuple[bool, str]:
        """
        PRE-FLIGHT CHECK #2: Verify bars_since_entry increments per-bar, not per-pulse.
        
        Tracks the timing of bar increments to detect:
        - Correct: +1 bar per hour (or per chart period)
        - Incorrect: +1 bar every 10 seconds (per data pulse)
        
        Args:
            position_id: Position ID
            current_bars: Current bars_since_entry value
            timestamp: Current timestamp
            
        Returns:
            (is_correct, diagnostic_message)
        """
        if position_id not in self.bars_counter_history:
            self.bars_counter_history[position_id] = []
        
        history = self.bars_counter_history[position_id]
        
        # Store current reading with timestamp
        history.append({
            'bars': current_bars,
            'timestamp': timestamp,
        })
        
        # Keep only last 100 readings
        if len(history) > 100:
            history.pop(0)
        
        # Check frequency if we have enough data
        if len(history) >= 10:
            # Look at the last 10 increments
            old_bars = history[-10]['bars']
            new_bars = history[-1]['bars']
            time_diff = (history[-1]['timestamp'] - history[-10]['timestamp']).total_seconds()
            
            # If bars incremented by exactly 10, check the time difference
            if new_bars - old_bars == 10:
                # Expected: 10 bars should span ~10 hours (36000 seconds)
                # Actual: If only ~100 seconds, then it's per-pulse
                if time_diff < 300:  # Less than 5 minutes
                    reason = (
                        f"BARS INCREMENT FREQUENCY ERROR: 10 bars in {time_diff:.0f} seconds. "
                        f"This indicates manage_position() is called per-pulse, not per-bar. "
                        f"Expected: 10 bars in ~36000 seconds (10 hours)"
                    )
                    logger.warning("[PREFLIGHT_BARS_ERROR] %s: %s", position_id, reason)
                    return False, reason
                else:
                    # Looks correct
                    logger.debug(
                        "[PREFLIGHT_BARS_OK] %s: 10 bars in %.0f seconds (expected ~10 hours)",
                        position_id,
                        time_diff
                    )
                    return True, "Bars increment frequency OK"
        
        return True, "Not enough data yet"
    
    # ========== PRE-FLIGHT CHECK #3: AUTO-ROTATION & HARVEST COORDINATION ==========
    
    def check_rotation_conflict(
        self,
        state: Dict[str, Any],
        position_id: str,
    ) -> Tuple[bool, str]:
        """
        PRE-FLIGHT CHECK #3: Detect conflicts with Auto-Rotation and Harvest engines.
        
        Ensures Layer 3 runs BEFORE Auto-Rotation and Harvest:
        - If marked for rotation, skip Layer 3
        - If already harvested, skip Layer 3
        - Set time_decay_sl_applied flag to prevent conflicts
        
        Args:
            state: Position state dictionary
            position_id: Position ID
            
        Returns:
            (should_proceed, diagnostic_message)
        """
        # Check if already marked for rotation
        if state.get('marked_for_auto_rotation', False):
            reason = "Position marked for auto-rotation. Skipping Layer 3 to let rotation proceed."
            logger.debug("[ROTATION_CONFLICT] %s: %s", position_id, reason)
            return False, reason
        
        # Check if already harvested
        if state.get('harvested', False):
            reason = "Position already harvested. Skipping Layer 3."
            logger.debug("[HARVEST_CONFLICT] %s: %s", position_id, reason)
            return False, reason
        
        # Check if time_decay_sl_applied flag is set (prevent double-execution)
        if state.get('time_decay_sl_applied', False):
            reason = "Layer 3 already applied SL modification this cycle. Skipping redundant check."
            logger.debug("[TIME_DECAY_SKIP] %s: %s", position_id, reason)
            return False, reason
        
        return True, "No conflicts detected"
    
    # ========== CORE DETECTION LOGIC ==========
    
    def detect_stagnation(
        self,
        position: Position,
        bars_since_entry: int,
        price_history: Optional[list] = None,
    ) -> bool:
        """Detect if a position is stagnant"""
        if bars_since_entry < self.STAGNATION_BAR_THRESHOLD:
            return False
        
        if price_history and len(price_history) >= self.STAGNATION_BAR_THRESHOLD:
            oldest_price = price_history[-self.STAGNATION_BAR_THRESHOLD]
            current_price = position.current_price
            pip_value = self.get_pip_value(position.symbol)
            price_move_pips = abs(current_price - oldest_price) / pip_value
            
            if price_move_pips > self.STAGNATION_PRICE_THRESHOLD_PIPS:
                return False
        
        return True
    
    def is_in_drawdown_window(self, current_r: float) -> bool:
        """Check if trade is in the drawdown window where decay applies"""
        return self.MIN_DRAWDOWN_R <= current_r <= self.MAX_DRAWDOWN_R
    
    def calculate_shrinkage_amount(self, bars_stagnant: int) -> float:
        """Get shrinkage amount (in pips) based on stagnation duration"""
        if bars_stagnant < self.STAGNATION_BAR_THRESHOLD:
            return 0.0
        
        if bars_stagnant >= 40:
            return self.SHRINKAGE_SCHEDULE[40]
        elif bars_stagnant >= 25:
            return self.SHRINKAGE_SCHEDULE[25]
        elif bars_stagnant >= 15:
            return self.SHRINKAGE_SCHEDULE[15]
        
        return 0.0
    
    def calculate_decayed_sl(
        self,
        position: Position,
        entry_price: float,
        current_sl: Optional[float],
        bars_stagnant: int,
        symbol: str,
    ) -> Optional[float]:
        """
        TASK 1: MATH FIX - Calculate a tighter SL if decay conditions are met.
        
        CRITICAL CONSTRAINT-BASED LOGIC (Risk Reduction Only):
        
        For LONGs:
        - proposed_sl = current_sl + (pips_to_tighten * point)
        - Constraint: proposed_sl must be > current_sl AND < entry_price
        
        For SHORTs:
        - proposed_sl = current_sl - (pips_to_tighten * point)
        - Constraint: proposed_sl must be < current_sl AND > entry_price
        
        Returns None if ANY validation fails. No exceptions - just safe returns.
        """
        # ===== INPUT VALIDATION =====
        if current_sl is None:
            logger.warning("[TIME_DECAY] NoneType Guard: Current SL is None for %s. Skipping.", symbol)
            return None
        
        if position is None:
            logger.warning("[TIME_DECAY] NoneType Guard: Position is None. Skipping.")
            return None
        
        if entry_price is None or entry_price <= 0:
            logger.warning("[TIME_DECAY] NoneType Guard: Invalid entry price. Skipping.")
            return None
        
        # ===== PRE-CONDITIONS =====
        pip_value = self.get_pip_value(symbol)
        
        # Check stagnation threshold
        if bars_stagnant < self.STAGNATION_BAR_THRESHOLD:
            return None
        
        # Check safety floor (minimum risk at entry)
        entry_to_sl_pips = abs(entry_price - current_sl) / pip_value
        if entry_to_sl_pips - self.SAFETY_FLOOR_PIPS < self.SAFETY_FLOOR_PIPS:
            logger.debug(
                "[TIME_DECAY] Safety floor reached for %s. Current risk=%.1f pips, Minimum=%.1f pips.",
                symbol,
                entry_to_sl_pips,
                self.SAFETY_FLOOR_PIPS,
            )
            return None
        
        # Get decay amount in pips and convert to price
        shrinkage_pips = self.calculate_shrinkage_amount(bars_stagnant)
        if shrinkage_pips <= 0:
            return None
        
        pips_to_tighten = shrinkage_pips
        point = pip_value
        direction_str = "LONG" if position.direction == Direction.LONG else "SHORT"
        
        # ===== MATH FIX: CONSTRAINT-BASED DIRECTIONAL CALCULATION =====
        
        if position.direction == Direction.LONG:
            # For LONGs: proposed_sl = current_sl + (pips_to_tighten * point)
            proposed_sl = current_sl + (pips_to_tighten * point)
            
            # Constraint: proposed_sl must be > current_sl AND < entry_price
            if proposed_sl > current_sl and proposed_sl < entry_price:
                logger.debug(
                    "[MATH_FIX_VALID] %s LONG #%s | Decay: %.1f pips | "
                    "SL: %.5f → %.5f | Entry: %.5f | Constraints: ✓ PASS (%.5f > %.5f AND %.5f < %.5f)",
                    symbol,
                    position.position_id,
                    pips_to_tighten,
                    current_sl,
                    proposed_sl,
                    entry_price,
                    proposed_sl,
                    current_sl,
                    proposed_sl,
                    entry_price,
                )
                return round(proposed_sl, 5)
            else:
                # Log specific constraint failure
                if proposed_sl <= current_sl:
                    logger.error(
                        "[MATH_FIX_FAILED] %s LONG #%s | Constraint Violated: proposed_sl (%.5f) NOT > current_sl (%.5f) | "
                        "Risk Expansion Prevented.",
                        symbol,
                        position.position_id,
                        proposed_sl,
                        current_sl,
                    )
                if proposed_sl >= entry_price:
                    logger.error(
                        "[MATH_FIX_FAILED] %s LONG #%s | Constraint Violated: proposed_sl (%.5f) NOT < entry_price (%.5f) | "
                        "Position would be closed.",
                        symbol,
                        position.position_id,
                        proposed_sl,
                        entry_price,
                    )
                return None
        
        elif position.direction == Direction.SHORT:
            # For SHORTs: proposed_sl = current_sl - (pips_to_tighten * point)
            proposed_sl = current_sl - (pips_to_tighten * point)
            
            # Constraint: proposed_sl must be < current_sl AND > entry_price
            if proposed_sl < current_sl and proposed_sl > entry_price:
                logger.debug(
                    "[MATH_FIX_VALID] %s SHORT #%s | Decay: %.1f pips | "
                    "SL: %.5f → %.5f | Entry: %.5f | Constraints: ✓ PASS (%.5f < %.5f AND %.5f > %.5f)",
                    symbol,
                    position.position_id,
                    pips_to_tighten,
                    current_sl,
                    proposed_sl,
                    entry_price,
                    proposed_sl,
                    current_sl,
                    proposed_sl,
                    entry_price,
                )
                return round(proposed_sl, 5)
            else:
                # Log specific constraint failure
                if proposed_sl >= current_sl:
                    logger.error(
                        "[MATH_FIX_FAILED] %s SHORT #%s | Constraint Violated: proposed_sl (%.5f) NOT < current_sl (%.5f) | "
                        "Risk Expansion Prevented.",
                        symbol,
                        position.position_id,
                        proposed_sl,
                        current_sl,
                    )
                if proposed_sl <= entry_price:
                    logger.error(
                        "[MATH_FIX_FAILED] %s SHORT #%s | Constraint Violated: proposed_sl (%.5f) NOT > entry_price (%.5f) | "
                        "Position would be closed.",
                        symbol,
                        position.position_id,
                        proposed_sl,
                        entry_price,
                    )
                return None
        
        else:
            logger.error(
                "[MATH_FIX_FAILED] %s | Invalid position direction: %s",
                symbol,
                position.direction,
            )
            return None
    
    
    
    def log_decay_proposal(
        self,
        symbol: str,
        position_id: int,
        current_r: float,
        bars_stagnant: int,
        current_sl: float,
        proposed_sl: Optional[float],
        shrinkage_pips: float,
        position_direction = None,
    ) -> None:
        """Log the proposed decay change (SHADOW MODE) with directional verification"""
        if proposed_sl is None:
            return
        
        pip_value = self.get_pip_value(symbol)
        risk_reduction_pips = abs(proposed_sl - current_sl) / pip_value
        
        # Determine direction string
        direction_str = "LONG" if position_direction == Direction.LONG else "SHORT"
        
        # Calculate adjustment direction for logging
        if position_direction == Direction.LONG:
            # LONG: SL should increase (move UP)
            adjustment_direction = "↑ UP" if proposed_sl > current_sl else "↓ DOWN (ERROR)"
            risk_change = "TIGHTENING" if proposed_sl > current_sl else "INCREASING (ERROR)"
        else:  # SHORT
            # SHORT: SL should decrease (move DOWN)
            adjustment_direction = "↓ DOWN" if proposed_sl < current_sl else "↑ UP (ERROR)"
            risk_change = "TIGHTENING" if proposed_sl < current_sl else "INCREASING (ERROR)"
        
        logger.info(
            "[TIME_DECAY] SHADOW MODE - %s (ID:%s) | Direction: %s | Stagnant: %s bars | P&L: %.2f R | "
            "SL Adjustment: %.5f %s %.5f (%s) | Risk: %s (%.1f pips) | "
            "Directional Adjustment: +%.1f pips %s (Expected for %s)",
            symbol,
            position_id,
            direction_str,
            bars_stagnant,
            current_r,
            current_sl,
            adjustment_direction,
            proposed_sl,
            risk_change,
            risk_change,
            risk_reduction_pips,
            shrinkage_pips,
            adjustment_direction,
            direction_str,
        )
    
    # ========== TASK 2: DIAGNOSTIC VERIFICATION ==========
    
    def diagnostic_test_run(
        self,
        positions: Optional[list] = None,
    ) -> bool:
        """
        TASK 2: Diagnostic Verification - Verify fix without modifying broker.
        
        This method:
        - Loops through active positions (or provided positions list)
        - Simulates a 10-pip tightening move for each
        - Prints: [DIAGNOSTIC_CHECK] Symbol | Type: LONG/SHORT | 
                  Current SL: X | Proposed SL: Y | Direction_Check: PASSED/FAILED
        - If Direction_Check fails, logs the reason
        
        Returns: True if ALL diagnostics pass, False if ANY diagnostic fails
        
        Usage: Call this manually to verify the fix before deploying!
        """
        if positions is None or len(positions) == 0:
            logger.info("[DIAGNOSTIC_TEST_RUN] No positions provided. Skipping diagnostic.")
            return True
        
        all_diagnostics_passed = True
        diagnostic_summary = []
        
        for position in positions:
            symbol = position.symbol
            direction_str = "LONG" if position.direction == Direction.LONG else "SHORT"
            current_sl = position.stop_loss
            entry_price = position.entry_price
            pip_value = self.get_pip_value(symbol)
            
            # Simulate 10-pip tightening move
            diagnostic_decay_pips = 10.0
            diagnostic_point = pip_value
            
            # Calculate proposed SL for diagnostic
            if position.direction == Direction.LONG:
                proposed_sl = current_sl + (diagnostic_decay_pips * diagnostic_point)
                # Constraint: proposed_sl must be > current_sl AND < entry_price
                direction_check_passed = proposed_sl > current_sl and proposed_sl < entry_price
                constraint_reason = (
                    f"proposed_sl ({proposed_sl:.5f}) > current_sl ({current_sl:.5f}) ✓ AND "
                    f"proposed_sl ({proposed_sl:.5f}) < entry_price ({entry_price:.5f})"
                ) if direction_check_passed else (
                    f"proposed_sl ({proposed_sl:.5f}) NOT > current_sl ({current_sl:.5f})" if proposed_sl <= current_sl
                    else f"proposed_sl ({proposed_sl:.5f}) NOT < entry_price ({entry_price:.5f})"
                )
            else:  # SHORT
                proposed_sl = current_sl - (diagnostic_decay_pips * diagnostic_point)
                # Constraint: proposed_sl must be < current_sl AND > entry_price
                direction_check_passed = proposed_sl < current_sl and proposed_sl > entry_price
                constraint_reason = (
                    f"proposed_sl ({proposed_sl:.5f}) < current_sl ({current_sl:.5f}) ✓ AND "
                    f"proposed_sl ({proposed_sl:.5f}) > entry_price ({entry_price:.5f})"
                ) if direction_check_passed else (
                    f"proposed_sl ({proposed_sl:.5f}) NOT < current_sl ({current_sl:.5f})" if proposed_sl >= current_sl
                    else f"proposed_sl ({proposed_sl:.5f}) NOT > entry_price ({entry_price:.5f})"
                )
            
            # Log diagnostic result
            status_str = "PASSED" if direction_check_passed else "FAILED"
            log_message = (
                f"[DIAGNOSTIC_CHECK] {symbol} | Type: {direction_str} | "
                f"Current SL: {current_sl:.5f} | Proposed SL: {proposed_sl:.5f} | "
                f"Direction_Check: {status_str}"
            )
            
            logger.info(log_message)
            diagnostic_summary.append({
                'symbol': symbol,
                'direction': direction_str,
                'current_sl': current_sl,
                'proposed_sl': proposed_sl,
                'status': status_str,
                'constraint_reason': constraint_reason,
            })
            
            if not direction_check_passed:
                all_diagnostics_passed = False
                logger.warning(
                    f"[DIAGNOSTIC_CONSTRAINT_FAILED] {symbol} {direction_str} | Reason: {constraint_reason}"
                )
        
        # Summary
        total = len(diagnostic_summary)
        passed = sum(1 for d in diagnostic_summary if d['status'] == "PASSED")
        logger.info(
            f"[DIAGNOSTIC_SUMMARY] Total Positions: {total} | Passed: {passed} | Failed: {total - passed} | "
            f"Overall Result: {'ALL DIAGNOSTICS PASSED ✓' if all_diagnostics_passed else 'SOME DIAGNOSTICS FAILED ✗'}"
        )
        
        return all_diagnostics_passed
    
    # ========== INTEGRATION METHOD (Call this from manage_position) ==========
    
    async def check_and_apply_decay(
        self,
        position: Position,
        state: Dict[str, Any],
        current_r: float,
        bars_since_entry: int,
        risk_price: float,
        symbol_info: Optional[Any] = None,
        current_tick: Optional[Any] = None,
        broker: Optional[Any] = None,
    ) -> bool:
        """
        Check if decay applies and execute/simulate SL modification.
        
        DIRECTION-AWARE LOGIC:
        - LONG: proposed_sl = current_sl + (decay_pips * point) → SL moves UP
        - SHORT: proposed_sl = current_sl - (decay_pips * point) → SL moves DOWN
        
        SL TIGHTENING VALIDATION:
        - Ensures new SL is closer to entry price than current SL
        - Prevents SL expansion (logged as [SL_EXPANSION_PREVENTED])
        
        SHADOW MODE: Validates proposal and logs success without modifying MT5.
        LIVE MODE: Validates, executes modification, and logs only on MT5 success.
        
        PRE-FLIGHT CHECKS INTEGRATED:
        - Check #1: Broker constraints (trade_stops_level)
        - Check #2: Bars counter frequency
        - Check #3: Rotation/Harvest conflicts
        
        Returns: True if proposal is valid (shadow) or execution succeeded (live), False otherwise
        """
        pos_id = str(position.position_id)
        direction_str = "LONG" if position.direction == Direction.LONG else "SHORT"
        
        # ===== EXECUTION COOLDOWN CHECK: Skip if ticket was recently rejected by MT5 =====
        if self.is_in_execution_cooldown(pos_id):
            logger.debug("[LAYER3_SKIP] %s #%s | Ticket in execution cooldown (MT5 rejection). Skipping.", position.symbol, pos_id)
            return False
        
        # ===== COOLDOWN CHECK: Skip modifications for recently-failed positions =====
        if self.is_in_cooldown(pos_id):
            logger.debug("[LAYER3_SKIP] %s #%s | Position in modification cooldown. Skipping.", position.symbol, pos_id)
            return False
        
        # ===== PRE-FLIGHT CHECK #3: ROTATION/HARVEST CONFLICTS =====
        should_proceed, conflict_reason = self.check_rotation_conflict(state, pos_id)
        if not should_proceed:
            logger.debug("[PREFLIGHT_CHECK_3] %s: %s", pos_id, conflict_reason)
            return False
        
        # ===== PRE-FLIGHT CHECK #2: BARS COUNTER VERIFICATION =====
        is_correct, bars_diagnostic = self.verify_bars_increment_frequency(
            pos_id,
            bars_since_entry,
            datetime.now(timezone.utc),
        )
        if not is_correct and bars_since_entry > 50:
            logger.error("[PREFLIGHT_CHECK_2_FAILED] %s: %s", pos_id, bars_diagnostic)
            return False
        
        # Check if in drawdown window
        if not self.is_in_drawdown_window(current_r):
            return False
        
        # Get price history
        price_history = state.get('price_history', [])
        
        # Detect stagnation
        if not self.detect_stagnation(position, bars_since_entry, price_history):
            return False
        
        # Calculate decay with direction-aware logic
        pip_value = self.get_pip_value(position.symbol)
        bars_stagnant = bars_since_entry - self.STAGNATION_BAR_THRESHOLD
        entry_price = state.get('entry_price', position.entry_price)
        
        proposed_sl = self.calculate_decayed_sl(
            position=position,
            entry_price=entry_price,
            current_sl=position.stop_loss,
            bars_stagnant=bars_stagnant,
            symbol=position.symbol,
        )
        
        if proposed_sl is None:
            return False
        
        # ===== ADJUSTMENT SIZE CHECK: Skip if adjustment is too small =====
        if symbol_info:
            trade_stops_level = float(getattr(symbol_info, 'trade_stops_level', 0) or 0)
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
            adjustment_required = trade_stops_level * 2.0 * point
            adjustment_actual = abs(proposed_sl - position.stop_loss)
            
            if adjustment_actual < adjustment_required:
                logger.info(
                    "[LAYER3_SKIP] %s #%s | SL adjustment too small or too close to stops | "
                    "Current SL: %.5f | Proposed SL: %.5f | Adjustment: %.5f | "
                    "Minimum Required: %.5f (trade_stops_level %.0f * 2.0 * point %.5f) | "
                    "Skipping.",
                    position.symbol,
                    pos_id,
                    position.stop_loss,
                    proposed_sl,
                    adjustment_actual,
                    adjustment_required,
                    trade_stops_level,
                    point,
                )
                return False
        
        # ===== CRITICAL VALIDATION: Verify SL movement direction is correct =====
        if position.direction == Direction.LONG:
            # LONG: SL should move UP (increase)
            sl_moved_correctly = proposed_sl > position.stop_loss
            movement_symbol = "↑ UP" if sl_moved_correctly else "↓ DOWN (WRONG!)"
        else:
            # SHORT: SL should move DOWN (decrease)
            sl_moved_correctly = proposed_sl < position.stop_loss
            movement_symbol = "↓ DOWN" if sl_moved_correctly else "↑ UP (WRONG!)"
        
        if not sl_moved_correctly:
            logger.error(
                "[DECAY_DIRECTION_ERROR] %s #%s | Direction: %s | SL: %.5f → %.5f %s | "
                "Status: ✗ INCORRECT - WRONG DIRECTION! Current Price: %.5f",
                position.symbol,
                position.position_id,
                direction_str,
                position.stop_loss,
                proposed_sl,
                movement_symbol,
                position.current_price,
            )
            return False
        
        # ===== VALIDATION: Verify SL is closer to entry price =====
        distance_current_to_entry = abs(position.stop_loss - entry_price)
        distance_proposed_to_entry = abs(proposed_sl - entry_price)
        
        if distance_proposed_to_entry > distance_current_to_entry:
            logger.error(
                "[SL_EXPANSION_PREVENTED] %s #%s | Direction: %s | Entry: %.5f | "
                "Current SL: %.5f (%.1f pips from entry) → Proposed SL: %.5f (%.1f pips from entry) | "
                "ERROR: SL moving AWAY from entry price (expansion)!",
                position.symbol,
                position.position_id,
                direction_str,
                entry_price,
                position.stop_loss,
                distance_current_to_entry / pip_value,
                proposed_sl,
                distance_proposed_to_entry / pip_value,
            )
            return False
        
        pips_tightened = (distance_current_to_entry - distance_proposed_to_entry) / pip_value
        
        logger.debug(
            "[DECAY_CALCULATION_CHECK] %s #%s | Direction: %s | SL: %.5f → %.5f %s | "
            "Status: ✓ CORRECT | Tightened: %.1f pips | Entry: %.5f | "
            "Distance to Entry: %.1f → %.1f pips | Current Price: %.5f",
            position.symbol,
            position.position_id,
            direction_str,
            position.stop_loss,
            proposed_sl,
            movement_symbol,
            pips_tightened,
            entry_price,
            distance_current_to_entry / pip_value,
            distance_proposed_to_entry / pip_value,
            position.current_price,
        )
        
        # ===== PRE-FLIGHT CHECK #1: BROKER CONSTRAINTS =====
        if symbol_info and current_tick:
            is_valid, constraint_reason = await self.validate_sl_against_broker_constraints(
                position=position,
                proposed_sl=proposed_sl,
                symbol_info=symbol_info,
                current_tick=current_tick,
            )
            
            if not is_valid:
                logger.warning(
                    "[PREFLIGHT_CHECK_1_FAILED] %s: %s",
                    pos_id,
                    constraint_reason
                )
                return False
        
        # Calculate pips saved
        shrinkage_pips = self.calculate_shrinkage_amount(bars_stagnant)
        pips_saved = abs(proposed_sl - position.stop_loss) / pip_value
        
        # ===== ROUND PROPOSED_SL TO SYMBOL DIGITS EARLY =====
        symbol_digits = symbol_info.digits if symbol_info else 5
        proposed_sl_rounded = round(float(proposed_sl), symbol_digits)
        
        # ===== BROKER MINIMUM STOP LEVEL VALIDATION =====
        if symbol_info and current_tick:
            trade_stops_level = float(getattr(symbol_info, 'trade_stops_level', 0) or 0)
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
            current_price = position.current_price
            
            # Calculate distance in points (not pips)
            distance_in_points = abs(proposed_sl_rounded - current_price) / point
            
            if distance_in_points < trade_stops_level:
                logger.warning(
                    "[BROKER_MIN_STOP_VIOLATION] %s #%s | Direction: %s | "
                    "Proposed SL: %.5f | Current Price: %.5f | "
                    "Distance: %.0f points | Broker Minimum: %.0f points | "
                    "Violation: SL too close to current price. Skipping modification.",
                    position.symbol,
                    pos_id,
                    direction_str,
                    proposed_sl_rounded,
                    current_price,
                    distance_in_points,
                    trade_stops_level,
                )
                return False
            
            logger.debug(
                "[BROKER_STOP_LEVEL_OK] %s #%s | Distance: %.0f points | "
                "Broker Minimum: %.0f points | Status: ✓ VALID",
                position.symbol,
                pos_id,
                distance_in_points,
                trade_stops_level,
            )
            
            # ===== MINIMUM DISTANCE SAFETY CHECK (CRITICAL FOR MT5) =====
            # Fetch the symbol's stop level and create a minimum distance requirement
            stop_level = float(getattr(symbol_info, 'trade_stops_level', 0) or 0)
            point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
            current_price = position.current_price
            
            # Convert stop level into a price distance with 50% buffer for safety
            # min_distance = stop_level * point * 1.5
            min_distance = stop_level * point * 1.5
            
            # Calculate actual distance between proposed SL and current price
            actual_distance = abs(proposed_sl_rounded - current_price)
            
            # Validate: SL must maintain minimum distance from current price
            if actual_distance < min_distance:
                logger.warning(
                    "[BROKER_MIN_STOP_VIOLATION] %s #%s | Proposed SL (%.5f) is too close to price (%.5f) | "
                    "Actual Distance: %.5f | Min Distance Required: %.5f (stop_level %.0f * point %.5f * 1.5) | "
                    "Difference Deficit: %.5f | Aborting modification.",
                    position.symbol,
                    pos_id,
                    proposed_sl_rounded,
                    current_price,
                    actual_distance,
                    min_distance,
                    stop_level,
                    point,
                    min_distance - actual_distance,
                )
                return False
            
            logger.debug(
                "[MIN_DISTANCE_OK] %s #%s | Proposed SL: %.5f | Current Price: %.5f | "
                "Actual Distance: %.5f | Min Distance Required: %.5f | Status: ✓ SAFE",
                position.symbol,
                pos_id,
                proposed_sl_rounded,
                current_price,
                actual_distance,
                min_distance,
            )
        
        # ===== SHADOW MODE: Validate only, log success ======
        if self.SHADOW_MODE:
            logger.info(
                "[LAYER3_SHADOW_SUCCESS] %s #%s | Direction: %s | Stagnant: %s bars | "
                "SL: %.5f → %.5f %s | Tightening: %.1f pips (%.1f pips closer to entry %.5f) | "
                "P&L: %.2f R",
                position.symbol,
                pos_id,
                direction_str,
                bars_stagnant,
                position.stop_loss,
                proposed_sl,
                movement_symbol,
                pips_saved,
                pips_tightened,
                entry_price,
                current_r,
            )
            return True
        
        # ===== LIVE MODE: Execute modification on MT5 ======
        if broker is None:
            logger.warning(
                "[LAYER3_NO_BROKER] %s #%s | Broker not provided. Skipping live modification.",
                position.symbol,
                pos_id,
            )
            return False
        
        try:
            # Prepare parameters
            order_id_str = str(position.position_id)
            # Use pre-rounded SL from broker validation section
            sl_price = proposed_sl_rounded
            
            # Safely prepare TP
            tp_price = None
            if position.take_profit:
                try:
                    tp_float = float(position.take_profit)
                    if tp_float > 0:
                        tp_price = round(tp_float, symbol_digits)
                except (ValueError, TypeError):
                    logger.debug(
                        "[LAYER3_TP_SKIP] %s #%s | Invalid TP: %s",
                        position.symbol,
                        pos_id,
                        position.take_profit,
                    )
            
            logger.debug(
                "[LAYER3_MODIFY_ATTEMPT] %s #%s | Direction: %s | SL: %.5f → %.5f %s | "
                "TP: %s | Pips Saved: %.1f | Entry: %.5f",
                position.symbol,
                pos_id,
                direction_str,
                position.stop_loss,
                sl_price,
                movement_symbol,
                tp_price if tp_price else "None",
                pips_saved,
                entry_price,
            )
            
            # ===== TASK 3: INTEGRATION SAFETY - Run diagnostic before broker modification =====
            # Call diagnostic_test_run() internally before attempting broker.modify_order()
            diagnostic_passed = self.diagnostic_test_run(positions=[position])
            
            if not diagnostic_passed:
                logger.error(
                    "[SAFETY_ABORT] %s #%s | Diagnostic test failed. Aborting broker modification. | "
                    "Direction: %s | Proposed SL: %.5f | Entry: %.5f",
                    position.symbol,
                    pos_id,
                    direction_str,
                    sl_price,
                    entry_price,
                )
                return False
            
            # ===== BROKER CONSTRAINT CHECK (With 100% Safety Buffer) =====
            # Use validate_with_broker for comprehensive validation before any broker call
            if symbol_info:
                is_broker_valid, broker_reason = await self.validate_with_broker(
                    symbol=position.symbol,
                    proposed_sl=sl_price,
                    current_price=position.current_price,
                    mt5_symbol_info=symbol_info,
                )
                
                if not is_broker_valid:
                    logger.warning(
                        "[BROKER_CONSTRAINT_PREVENTED] %s | Reason: Stop Level violation | %s",
                        position.symbol,
                        broker_reason,
                    )
                    # Add to execution cooldown to prevent retry spam
                    self.add_to_execution_cooldown(
                        ticket=str(position.position_id),
                        error_code=10016,  # ERR_INVALID_STOPS
                        reason="Pre-validation constraint check failed",
                    )
                    return False
                else:
                    logger.debug("[BROKER_CONSTRAINT_PASSED] %s | %s", position.symbol, broker_reason)
            
            # ===== BROKER FORBIDDEN ZONE CHECK & AUTO-ADJUSTMENT =====
            # Calculate the 'Forbidden Zone' based on the broker's SYMBOL_TRADE_STOPS_LEVEL
            # If the proposed SL falls within this zone, adjust it to be outside
            if symbol_info:
                trade_stops_level = float(getattr(symbol_info, 'trade_stops_level', 0) or 0)
                point = float(getattr(symbol_info, 'point', 0.0001) or 0.0001)
                current_price = position.current_price
                
                # Calculate forbidden zone boundaries (current price ± stops_level)
                forbidden_zone_min = current_price - (trade_stops_level * point)
                forbidden_zone_max = current_price + (trade_stops_level * point)
                
                # Safety buffer: add 5 points to ensure SL is clearly outside forbidden zone
                safety_buffer = 5 * point
                
                # Check if proposed SL is in forbidden zone
                sl_in_forbidden_zone = forbidden_zone_min <= sl_price <= forbidden_zone_max
                
                original_sl_price = sl_price  # Store original for logging
                
                if sl_in_forbidden_zone:
                    # Auto-adjust SL to be outside the forbidden zone
                    if position.direction == Direction.LONG:
                        # For LONG: SL must be below current price, push it further down (away from price)
                        adjusted_sl = forbidden_zone_min - safety_buffer
                    else:
                        # For SHORT: SL must be above current price, push it further up (away from price)
                        adjusted_sl = forbidden_zone_max + safety_buffer
                    
                    # Round to symbol digits
                    adjusted_sl = round(adjusted_sl, symbol_digits)
                    
                    logger.debug(
                        "[STOPS_LEVEL_ADJUSTMENT] %s #%s | Direction: %s | "
                        "Original Proposed SL: %.5f | Forbidden Zone: %.5f - %.5f | "
                        "Adjustment Required | Original SL would be %.1f points too close to price | "
                        "Auto-Adjusted SL: %.5f (trade_stops_level: %.0f points, safety buffer: 5 points)",
                        position.symbol,
                        pos_id,
                        direction_str,
                        original_sl_price,
                        forbidden_zone_min,
                        forbidden_zone_max,
                        (current_price - original_sl_price) / point if position.direction == Direction.LONG 
                        else (original_sl_price - current_price) / point,
                        adjusted_sl,
                        trade_stops_level,
                    )
                    
                    # Update sl_price to the adjusted value
                    sl_price = adjusted_sl
                else:
                    # SL is already outside forbidden zone
                    logger.debug(
                        "[STOPS_LEVEL_CHECK_OK] %s #%s | Proposed SL: %.5f | "
                        "Current Price: %.5f | Forbidden Zone: %.5f - %.5f | "
                        "SL is safely outside forbidden zone (trade_stops_level: %.0f points)",
                        position.symbol,
                        pos_id,
                        sl_price,
                        current_price,
                        forbidden_zone_min,
                        forbidden_zone_max,
                        trade_stops_level,
                    )
            
            # Execute modification
            success = await broker.modify_order(
                order_id=order_id_str,
                sl=sl_price,
                tp=tp_price,
            )
            
            if success:
                logger.info(
                    "[LAYER3_APPLIED] %s #%s | Direction: %s | Stagnant: %s bars | "
                    "SL: %.5f → %.5f %s | Tightening: %.1f pips (%.1f pips closer to entry %.5f) | "
                    "P&L: %.2f R",
                    position.symbol,
                    pos_id,
                    direction_str,
                    bars_stagnant,
                    position.stop_loss,
                    sl_price,
                    movement_symbol,
                    pips_saved,
                    pips_tightened,
                    entry_price,
                    current_r,
                )
                state['time_decay_sl_applied'] = True
                state['last_sl_modification_time'] = datetime.now(timezone.utc)
                return True
            else:
                logger.warning(
                    "[LAYER3_FAILED] %s #%s | MT5 modification rejected | "
                    "Proposed SL: %.5f (rounded: %.5f, current: %.5f) %s | Pips: %.1f",
                    position.symbol,
                    pos_id,
                    proposed_sl,
                    sl_price,
                    position.stop_loss,
                    movement_symbol,
                    pips_saved,
                )
                # Add to execution cooldown with error tracking
                # Most common rejection codes: 10016 (ERR_INVALID_STOPS), 10013 (ERR_INVALID_PRICE)
                self.add_to_execution_cooldown(
                    ticket=str(position.position_id),
                    error_code=10016,  # Assume stops level violation as most common cause
                    reason="Broker rejected modification (likely stop level violation)",
                )
                return False
                
        except Exception as modify_error:
            error_str = str(modify_error)
            
            # Try to extract MT5 error code from exception message
            mt5_error_code = 10016  # Default to ERR_INVALID_STOPS
            if hasattr(modify_error, 'code'):
                mt5_error_code = modify_error.code
            elif 'code' in error_str:
                try:
                    # Extract error code from string like "error code 10016"
                    match = re.search(r'(?:code|error)\s*(\d+)', error_str, re.IGNORECASE)
                    if match:
                        mt5_error_code = int(match.group(1))
                except (ValueError, AttributeError):
                    pass
            
            logger.error(
                "[LAYER3_ERROR] %s #%s | Exception during modification: %s | "
                "MT5 Error Code: %s | Attempted SL: %.5f → %.5f (rounded: %.5f) | "
                "Not a critical bot failure.",
                position.symbol,
                pos_id,
                error_str,
                mt5_error_code,
                position.stop_loss,
                proposed_sl,
                proposed_sl_rounded,
            )
            # Add to execution cooldown with error code tracking
            self.add_to_execution_cooldown(
                ticket=str(position.position_id),
                error_code=mt5_error_code,
                reason=f"Exception: {error_str[:100]}",
            )
            return False

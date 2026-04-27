"""
LAYER 3: TIME-DECAY STOP LOSS IMPLEMENTATION
=============================================

Purpose: Recover capital faster from stagnant losing trades by progressively
shrinking the stop loss if a trade shows no price progress for 15+ bars.

Shadow Mode: This code logs proposed changes WITHOUT executing them in MT5.
Once you verify the math is correct, change shadow_mode = False.

Integration: Add these methods to the ProfitProtectionModule class.
"""

import logging
import os
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone
from src.models import Position, Direction

logger = logging.getLogger(__name__)


class TimeDecayStopLossManager:
    """
    Manages time-decay stop loss logic for stagnant positions.
    
    Features:
    - Detects stagnant trades (drawdown + no price progress)
    - Progressive SL shrinkage (15p → 10p → 5p per stage)
    - Safety floor: Never shrink within 10 pips of entry
    - Shadow mode logging before actual execution
    """
    
    # ========== CONFIGURATION ==========
    # Enable/disable shadow mode (log only, don't modify)
    SHADOW_MODE = True  # Set to False when ready to enable actual modifications
    
    # Stagnation trigger thresholds
    STAGNATION_BAR_THRESHOLD = 15       # Bars of price stagnation before decay kicks in
    STAGNATION_PRICE_THRESHOLD_PIPS = 5.0  # Max price movement = 5 pips
    
    # Drawdown window: SL decay only applies if profit is in this range
    MIN_DRAWDOWN_R = -0.50  # Do not decay if losing more than 0.5R
    MAX_DRAWDOWN_R = -0.05  # Do not decay if winning (>0.05R profit)
    
    # Progressive shrinkage schedule (pips to shrink per stage)
    SHRINKAGE_SCHEDULE = {
        15: 15.0,   # Bars 15-24: Shrink by 15 pips
        25: 10.0,   # Bars 25-39: Shrink by 10 pips
        40: 5.0,    # Bars 40+:   Shrink by 5 pips
    }
    
    # Safety buffer: Never move SL closer than this to entry
    SAFETY_FLOOR_PIPS = 10.0
    
    # Minimum distance from current price (prevents order rejection)
    MIN_DISTANCE_FROM_PRICE_PIPS = 3.0
    
    def __init__(self):
        """Initialize manager"""
        self.decay_tracking: Dict[str, Dict[str, Any]] = {}  # {pos_id: decay_state}
        logger.info("[LAYER_3_INIT] Time-Decay Stop Loss Manager initialized (SHADOW_MODE=%s)", self.SHADOW_MODE)
    
    def get_pip_value(self, symbol: str) -> float:
        """Get pip value for symbol"""
        if 'JPY' in symbol.upper():
            return 0.01
        return 0.0001
    
    # ========== CORE DETECTION LOGIC ==========
    
    def detect_stagnation(
        self,
        position: Position,
        bars_since_entry: int,
        price_history: Optional[list] = None,
    ) -> bool:
        """
        Detect if a position is stagnant:
        - Bars without significant price movement
        
        Args:
            position: Position object
            bars_since_entry: Number of bars since entry
            price_history: Optional list of recent prices
            
        Returns:
            True if stagnant, False otherwise
        """
        if bars_since_entry < self.STAGNATION_BAR_THRESHOLD:
            return False  # Too early to consider stagnant
        
        # If we have price history, check for movement
        if price_history and len(price_history) >= self.STAGNATION_BAR_THRESHOLD:
            # Get price from 15 bars ago
            oldest_price = price_history[-self.STAGNATION_BAR_THRESHOLD]
            current_price = position.current_price
            
            pip_value = self.get_pip_value(position.symbol)
            price_move_pips = abs(current_price - oldest_price) / pip_value
            
            if price_move_pips > self.STAGNATION_PRICE_THRESHOLD_PIPS:
                return False  # Price moved enough, not stagnant
        
        return True  # Stagnant: bars threshold met, price hasn't moved
    
    def is_in_drawdown_window(
        self,
        current_r: float,
    ) -> bool:
        """
        Check if trade is in the drawdown window where decay applies.
        
        Decay applies when: -0.50R ≤ profit ≤ -0.05R
        (i.e., losing between 5% and 50% of initial risk)
        
        Args:
            current_r: Current profit/loss in R-multiples
            
        Returns:
            True if in decay window, False otherwise
        """
        return self.MIN_DRAWDOWN_R <= current_r <= self.MAX_DRAWDOWN_R
    
    # ========== SHRINKAGE CALCULATION ==========
    
    def calculate_shrinkage_amount(
        self,
        bars_stagnant: int,
    ) -> float:
        """
        Get shrinkage amount (in pips) based on stagnation duration.
        
        Args:
            bars_stagnant: Number of bars position has been stagnant
            
        Returns:
            Pips to shrink the SL by (positive value)
        """
        if bars_stagnant < self.STAGNATION_BAR_THRESHOLD:
            return 0.0
        
        # Progressive schedule
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
        Calculate a tighter SL if decay conditions are met.
        
        THIS IS SHADOW MODE: Log the proposal but don't modify yet.
        
        Args:
            position: Position object
            entry_price: Entry price of the trade
            current_sl: Current stop loss price
            bars_stagnant: How many bars position has been stagnant
            symbol: Symbol (e.g., "EUR/USD")
            
        Returns:
            New SL price if decay applies, None if no change
        """
        # ===== NONEONE TYPE GUARD =====
        if current_sl is None:
            logger.warning("[TIME_DECAY] NoneType Guard: Current SL is None for %s. Skipping decay.", symbol)
            return None
        
        if position is None:
            logger.warning("[TIME_DECAY] NoneType Guard: Position is None. Skipping decay.")
            return None
        
        if entry_price is None or entry_price <= 0:
            logger.warning("[TIME_DECAY] NoneType Guard: Invalid entry price. Skipping decay.")
            return None
        
        # ===== CONDITION CHECKS =====
        pip_value = self.get_pip_value(symbol)
        
        # 1. Check if stagnant
        if bars_stagnant < self.STAGNATION_BAR_THRESHOLD:
            return None
        
        # 2. Calculate distance from entry to current SL
        entry_to_sl_pips = abs(entry_price - current_sl) / pip_value
        
        # 3. Check safety floor: Don't shrink within 10 pips of entry
        if entry_to_sl_pips - self.SAFETY_FLOOR_PIPS < self.SAFETY_FLOOR_PIPS:
            logger.debug(
                "[TIME_DECAY] Safety floor reached for %s. Current SL risk=%.1f pips. Minimum=%.1f pips.",
                symbol,
                entry_to_sl_pips,
                self.SAFETY_FLOOR_PIPS,
            )
            return None
        
        # 4. Get shrinkage amount
        shrinkage_pips = self.calculate_shrinkage_amount(bars_stagnant)
        if shrinkage_pips <= 0:
            return None
        
        # 5. Calculate new SL (move closer to entry by shrinkage amount)
        if position.direction == Direction.LONG:
            # LONG: SL is below entry, move it up (closer to entry)
            new_sl = current_sl + (shrinkage_pips * pip_value)
            
            # Sanity check: Don't move SL ABOVE current price
            if new_sl > position.current_price:
                logger.warning(
                    "[TIME_DECAY] New SL (%.5f) would exceed current price (%.5f) for %s LONG. Skipping.",
                    new_sl, position.current_price, symbol
                )
                return None
        else:
            # SHORT: SL is above entry, move it down (closer to entry)
            new_sl = current_sl - (shrinkage_pips * pip_value)
            
            # Sanity check: Don't move SL BELOW current price
            if new_sl < position.current_price:
                logger.warning(
                    "[TIME_DECAY] New SL (%.5f) would exceed current price (%.5f) for %s SHORT. Skipping.",
                    new_sl, position.current_price, symbol
                )
                return None
        
        # 6. Ensure distance from current price (broker minimum)
        distance_from_price = abs(new_sl - position.current_price) / pip_value
        if distance_from_price < self.MIN_DISTANCE_FROM_PRICE_PIPS:
            logger.warning(
                "[TIME_DECAY] New SL too close to current price (%.1f pips) for %s. Minimum=%.1f pips. Skipping.",
                distance_from_price, symbol, self.MIN_DISTANCE_FROM_PRICE_PIPS
            )
            return None
        
        return new_sl
    
    # ========== SHADOW MODE LOGGING ==========
    
    def log_decay_proposal(
        self,
        symbol: str,
        position_id: int,
        current_r: float,
        bars_stagnant: int,
        current_sl: float,
        proposed_sl: Optional[float],
        shrinkage_pips: float,
    ) -> None:
        """
        Log the proposed decay change (SHADOW MODE).
        
        This logs what WOULD happen if decay is executed, without actually
        modifying the position in MT5.
        """
        if proposed_sl is None:
            return
        
        pip_value = self.get_pip_value(symbol)
        risk_reduction_pips = abs(proposed_sl - current_sl) / pip_value
        
        logger.info(
            "[TIME_DECAY] SHADOW MODE - %s (ID:%d) | "
            "Stagnant=%d bars | P&L=%.2fR | "
            "Proposed SL: %.5f → %.5f (shrink %.1f pips, save %.1f pips risk)",
            symbol,
            position_id,
            bars_stagnant,
            current_r,
            current_sl,
            proposed_sl,
            shrinkage_pips,
            risk_reduction_pips,
        )
    
    # ========== INTEGRATION POINT ==========
    
    def check_and_apply_decay(
        self,
        position: Position,
        state: Dict[str, Any],
        current_r: float,
        bars_since_entry: int,
        risk_price: float,
    ) -> Optional[float]:
        """
        Check if decay applies and return proposed new SL (for shadow logging).
        
        Integration: Call this from manage_position() or _continuous_sl_check().
        
        Args:
            position: Position object
            state: Position state dictionary
            current_r: Current profit/loss in R-multiples
            bars_since_entry: Bars since entry
            risk_price: Initial risk in price units (for context)
            
        Returns:
            Proposed new SL if decay applies, None otherwise
        """
        # Check if in drawdown window
        if not self.is_in_drawdown_window(current_r):
            return None
        
        # Get price history from state (if available)
        price_history = state.get('price_history', [])
        
        # Detect stagnation
        if not self.detect_stagnation(position, bars_since_entry, price_history):
            return None
        
        # Calculate decay
        pip_value = self.get_pip_value(position.symbol)
        bars_stagnant = bars_since_entry - self.STAGNATION_BAR_THRESHOLD
        
        proposed_sl = self.calculate_decayed_sl(
            position=position,
            entry_price=state.get('entry_price', position.entry_price),
            current_sl=position.stop_loss,
            bars_stagnant=bars_stagnant,
            symbol=position.symbol,
        )
        
        if proposed_sl is None:
            return None
        
        # Log in shadow mode
        shrinkage_pips = self.calculate_shrinkage_amount(bars_stagnant)
        self.log_decay_proposal(
            symbol=position.symbol,
            position_id=position.position_id,
            current_r=current_r,
            bars_stagnant=bars_stagnant,
            current_sl=position.stop_loss,
            proposed_sl=proposed_sl,
            shrinkage_pips=shrinkage_pips,
        )
        
        return proposed_sl


# ============================================================================
# INTEGRATION GUIDE FOR ProfitProtectionModule
# ============================================================================

"""
STEP 1: Add to __init__ method of ProfitProtectionModule:
-----------
In the __init__ method, add:

        # === LAYER 3: TIME-DECAY STOP LOSS ===
        self.time_decay_manager = TimeDecayStopLossManager()
        self.time_decay_enabled = bool(os.environ.get("TIME_DECAY_ENABLED", "True").lower() in ("true", "1", "yes"))


STEP 2: Track bars since entry in position_states:
-----------
In manage_position(), when initializing state for a new position, add:

        self.position_states[pos_id] = {
            # ... existing fields ...
            
            # === LAYER 3: TIME-DECAY TRACKING ===
            'bars_since_entry': 0,
            'bars_stagnant': 0,
            'bars_at_peak_profit': 0,
            'last_peak_profit': position.current_price,
            'time_decay_sl_applied': False,
        }


STEP 3: Increment bars_since_entry in manage_position():
-----------
In manage_position(), after state initialization, add:

        # Increment bars counter
        state['bars_since_entry'] = state.get('bars_since_entry', 0) + 1
        
        # Track price history for stagnation detection
        if 'price_history' not in state:
            state['price_history'] = []
        state['price_history'].append(position.current_price)
        if len(state['price_history']) > 100:
            state['price_history'].pop(0)  # Keep last 100 prices


STEP 4: Call decay check in _continuous_sl_check():
-----------
In the _continuous_sl_check() method, after calculating current_r, add:

        # === LAYER 3: TIME-DECAY CHECK ===
        if self.time_decay_enabled:
            proposed_decayed_sl = self.time_decay_manager.check_and_apply_decay(
                position=position,
                state=state,
                current_r=current_r,
                bars_since_entry=state.get('bars_since_entry', 0),
                risk_price=risk_price,
            )
            
            if proposed_decayed_sl is not None and not self.time_decay_manager.SHADOW_MODE:
                # Execute the modification (once shadow mode verification is complete)
                try:
                    new_sl = await self.broker.modify_position(
                        position_id=position.position_id,
                        stop_loss=proposed_decayed_sl,
                    )
                    if new_sl:
                        logger.info(
                            "[TIME_DECAY_EXECUTED] %s (ID:%s) SL moved: %.5f → %.5f",
                            position.symbol,
                            position.position_id,
                            position.stop_loss,
                            proposed_decayed_sl,
                        )
                        state['time_decay_sl_applied'] = True
                        action_taken = True
                except Exception as e:
                    logger.error("[TIME_DECAY_ERROR] Failed to apply decay for %s: %s", position.symbol, e)


STEP 5: Enable Shadow Mode Verification:
-----------
Run your bot with TIME_DECAY_ENABLED=True environment variable.

Watch the logs for entries like:
    [TIME_DECAY] SHADOW MODE - EUR/USD (ID:12345) | Stagnant=20 bars | P&L=-0.25R | 
    Proposed SL: 1.0540 → 1.0520 (shrink 20 pips, save 20 pips risk)

If the math looks correct for 20+ minutes of trading:

    1. Change TimeDecayStopLossManager.SHADOW_MODE = False
    2. Re-run the bot
    3. Monitor for [TIME_DECAY_EXECUTED] messages


STEP 6: Phased Deployment:
-----------
Once verified in shadow mode:

    1. Paper trade for 2 hours with shadow_mode=False
    2. Monitor for any MT5 order modification errors
    3. Check that SL movements happen at expected times
    4. If no issues, deploy to live trading


CONFIGURATION ENVIRONMENT VARIABLES:
-----------
TIME_DECAY_ENABLED=True                     # Enable/disable layer 3
TIME_DECAY_STAGNATION_BARS=15               # Bars before decay triggers
TIME_DECAY_STAGNATION_PIPS=5.0              # Max movement = stagnant
TIME_DECAY_MIN_DRAWDOWN_R=-0.50             # Don't decay if losing > 50%
TIME_DECAY_MAX_DRAWDOWN_R=-0.05             # Don't decay if in profit
TIME_DECAY_SAFETY_FLOOR_PIPS=10.0           # Never shrink within 10 pips of entry
"""

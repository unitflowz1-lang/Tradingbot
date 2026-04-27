"""
Integration Guide: Profit Protection Optimizer Methods
======================================================

This file contains ready-to-integrate Python methods that implement the 4
optimization layers into your existing ProfitProtectionModule.

Drop these methods directly into your ProfitProtectionModule class, and
integrate the configuration updates as specified.

SECTIONS:
1. __init__ updates - Add optimizer config
2. manage_position() - Enhanced with optimizations
3. Helper methods - New calculation functions
4. State tracking - New fields for time-decay tracking
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Tuple, Any
from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig

logger = logging.getLogger(__name__)


# ============================================================================
# SECTION 1: UPDATE __init__ METHOD
# ============================================================================

def _init_profit_protection_optimizer(self):
    """
    ADD THIS TO: ProfitProtectionModule.__init__()
    
    Purpose: Initialize optimizer configuration and state tracking
    
    Integration:
        # In ProfitProtectionModule.__init__(), add this line:
        self._init_profit_protection_optimizer()
    """
    
    # Load optimized configuration
    self.optimizer_config = OptimizedProfitProtectionConfig()
    
    logger.info("[PROFIT_PROTECTION_OPTIMIZER] Initialized with 4 optimization layers")
    logger.info(f"  • Trail Params: Whipsaw prevention (0.25R / 0.35R triggers)")
    logger.info(f"  • Chandelier Exit: Volatility-adjusted trailing")
    logger.info(f"  • Time-Decay SL: Stagnation prevention")
    logger.info(f"  • Regime Adaptive: Dynamic ATR multipliers")
    
    # State tracking for time-decay stop loss
    # Format: {pos_id: {
    #     'stagnant_bars': int,
    #     'last_significant_price': float,
    #     'decay_applies_since_bar': int,
    #     'sl_decay_applied_pips': float,
    # }}
    self.stagnation_state: Dict[str, Dict[str, Any]] = {}


# ============================================================================
# SECTION 2: ENHANCED manage_position() METHOD
# ============================================================================

"""
REPLACE the existing manage_position() method signature with this enhanced version:

async def manage_position(self, 
                         position: Position, 
                         market_data: MarketData, 
                         atr: float,
                         regime: Optional[str] = None,
                         volatility_regime: Optional[str] = None,
                         rsi: Optional[float] = None,
                         ml_confidence: Optional[float] = None,
                         atr_percentile: Optional[float] = None,  # NEW: For volatility scaling
                         adx_value: Optional[float] = None,        # NEW: For regime tuning
                         regime_confidence: Optional[float] = None # NEW: For confidence filtering
                        ) -> bool:
    
Then, add these optimization checks in the manage_position() flow:
"""

async def _apply_optimized_trail_activation(
    self,
    position,
    market_data,
    atr,
    regime: Optional[str] = None,
) -> bool:
    """
    OPTIMIZATION #1: Whipsaw-Resistant Trail Activation
    
    Replaces the simple "trailing_stop_activation_r" check with symbol-aware logic.
    
    ADD TO: manage_position() method, right after initializing position state
    
    Example Integration:
        # In manage_position(), after state initialization:
        if not state.get("trailing_active", False):
            action = await self._apply_optimized_trail_activation(
                position, market_data, atr, regime
            )
            if action:
                return True
    """
    pos_id = str(position.position_id)
    
    # Step 1: Get symbol-specific optimal triggers (Optimization #1)
    trail_act, be_trig = self.optimizer_config.trail_params.get_optimized_triggers(
        position.symbol
    )
    
    # Step 2: Calculate current profit in R-multiples
    initial_risk = getattr(position, 'stop_loss', position.entry_price)
    if position.direction.name == "LONG":
        risk_pips = (position.entry_price - initial_risk) / 0.0001
    else:
        risk_pips = (initial_risk - position.entry_price) / 0.0001
    
    current_profit = position.current_price - position.entry_price
    if position.direction.name == "SHORT":
        current_profit = position.entry_price - position.current_price
    
    current_r = current_profit / (risk_pips * 0.0001) if risk_pips > 0 else 0.0
    
    # Step 3: Check if trail activation threshold met (OPTIMIZED)
    if current_r >= trail_act:
        logger.info(
            f"[TRAIL_OPTIMIZED] {position.symbol} reached {current_r:.2f}R "
            f"(threshold: {trail_act:.2f}R) → Activate trailing"
        )
        
        state = self.position_states.get(pos_id, {})
        state["trailing_active"] = True
        state["trail_activation_r"] = trail_act
        self.position_states[pos_id] = state
        
        return True
    
    return False


async def _apply_candlelier_exit(
    self,
    position,
    atr: float,
    atr_percentile: Optional[float] = None,
    session_volatility_factor: Optional[float] = None,
) -> float:
    """
    OPTIMIZATION #2: Volatility-Adjusted Trailing (Chandelier Exit)
    
    Calculates dynamic trailing step instead of static 2.0 pips.
    
    ADD TO: manage_position() or _continuous_sl_check() method
    
    Returns: Dynamic trailing step in pips
    
    Example Integration:
        # In _continuous_sl_check(), replace static minStep:
        # OLD: trailing_step_pips = 2.0
        # NEW:
        trailing_step_pips = await self._apply_candlelier_exit(
            position, atr, atr_percentile, session_volatility_factor
        )
    """
    
    # Calculate dynamic step based on volatility
    trailing_step = self.optimizer_config.chandelier.calculate_dynamic_trail_step(
        atr=atr,
        atr_percentile=atr_percentile,
        session_volatility_factor=session_volatility_factor,
    )
    
    logger.debug(
        f"[CHANDELIER_EXIT] {position.symbol} | "
        f"ATR:{atr:.1f} | Percentile:{atr_percentile} | "
        f"TrailingStep:{trailing_step:.1f}p"
    )
    
    return trailing_step


async def _check_time_decay_stop_loss(
    self,
    position,
    market_data: MarketData,
    current_r: float,
) -> Tuple[bool, Optional[float]]:
    """
    OPTIMIZATION #3: Time-Decay Stop Loss for Stagnant Trades
    
    Shrinks hard SL if trade stuck in drawdown for 15+ bars.
    
    Returns:
        (should_apply, new_sl_price)
    
    ADD TO: manage_position() method
    
    Example Integration:
        # In manage_position(), after checking current R:
        should_apply, new_sl = await self._check_time_decay_stop_loss(
            position, market_data, current_r
        )
        if should_apply and new_sl:
            state["sl_adjusted_for_decay"] = True
            # Then modify position SL to new_sl
    """
    pos_id = str(position.position_id)
    
    # Step 1: Check if trade is stagnant
    if pos_id not in self.stagnation_state:
        self.stagnation_state[pos_id] = {
            'stagnant_bars': 0,
            'last_significant_price': position.current_price,
            'decay_applies_since_bar': 0,
            'sl_decay_applied_pips': 0.0,
        }
    
    stag_state = self.stagnation_state[pos_id]
    
    # Step 2: Track price movement
    price_movement_pips = abs(position.current_price - stag_state['last_significant_price']) / 0.0001
    
    if price_movement_pips > self.optimizer_config.time_decay.stagnation_price_movement_pips:
        # Significant move: reset stagnation counter
        stag_state['stagnant_bars'] = 0
        stag_state['last_significant_price'] = position.current_price
    else:
        # No significant move: increment counter
        stag_state['stagnant_bars'] += 1
    
    # Step 3: Check if decay should apply
    should_apply = self.optimizer_config.time_decay.should_apply_decay(
        current_profit_loss_r=current_r,
        bars_since_last_progress=stag_state['stagnant_bars'],
    )
    
    if not should_apply:
        return False, None
    
    # Step 4: Calculate SL shrinkage
    shrinkage_pips = self.optimizer_config.time_decay.calculate_sl_shrinkage(
        bars_stagnant=stag_state['stagnant_bars']
    )
    
    # Step 5: Calculate new SL
    current_sl = position.stop_loss
    min_cushion = self.optimizer_config.time_decay.min_sl_cushion_pips * 0.0001
    
    if position.direction.name == "LONG":
        # For LONG: SL is below entry, move it closer (reduce cushion)
        new_sl = position.entry_price - min_cushion
        if current_sl < position.entry_price - shrinkage_pips * 0.0001:
            new_sl = current_sl + (shrinkage_pips * 0.0001)
    else:
        # For SHORT: SL is above entry, move it closer
        new_sl = position.entry_price + min_cushion
        if current_sl > position.entry_price + shrinkage_pips * 0.0001:
            new_sl = current_sl - (shrinkage_pips * 0.0001)
    
    logger.info(
        f"[TIME_DECAY_SL] {position.symbol} | Stagnant:{stag_state['stagnant_bars']}bars | "
        f"Current:{current_r:.2f}R | Shrinkage:{shrinkage_pips:.1f}p | "
        f"SL:{current_sl:.5f} → {new_sl:.5f}"
    )
    
    return True, new_sl


async def _get_adaptive_atr_multiplier(
    self,
    position,
    regime: Optional[str] = None,
    regime_confidence: Optional[float] = None,
    adx_value: Optional[float] = None,
    atr_percentile: Optional[float] = None,
) -> float:
    """
    OPTIMIZATION #4: Market Regime Integration
    
    Returns adaptive ATR multiplier based on current regime.
    
    ADD TO: manage_position() or _continuous_sl_check() method
    
    Example Integration:
        # OLD: Use fixed trailing_stop_atr_multiplier = 1.8
        # NEW:
        atr_mult = await self._get_adaptive_atr_multiplier(
            position,
            regime=regime,
            regime_confidence=regime_confidence,
            adx_value=adx_value,
            atr_percentile=atr_percentile,
        )
        # Then use atr_mult instead of self.settings.trailing_stop_atr_multiplier
    """
    
    atr_mult = self.optimizer_config.regime_adaptive.get_atr_multiplier(
        regime=regime,
        regime_confidence=regime_confidence,
        volatility_percentile=atr_percentile,
        adx_value=adx_value,
    )
    
    logger.debug(
        f"[REGIME_ATR_MULT] {position.symbol} | "
        f"Regime:{regime} (conf:{regime_confidence:.0%}) | "
        f"ADX:{adx_value} | ATR_Mult:{atr_mult:.2f}x"
    )
    
    return atr_mult


# ============================================================================
# SECTION 3: UPDATED CONTINUOUS SL CHECK (with all optimizations)
# ============================================================================

async def _continuous_sl_check_optimized(
    self,
    position,
    state: Dict[str, Any],
    market_data: MarketData,
    atr: float,
    regime: Optional[str] = None,
    atr_percentile: Optional[float] = None,
    adx_value: Optional[float] = None,
    regime_confidence: Optional[float] = None,
) -> bool:
    """
    ENHANCED: _continuous_sl_check() with all 4 optimizations integrated.
    
    REPLACE the existing _continuous_sl_check() method with this version.
    
    This method combines:
    • Whipsaw prevention (optimized activation)
    • Chandelier exit (dynamic trailing)
    • Time-decay SL (stagnation prevention)
    • Regime adaptation (dynamic ATR multiplier)
    """
    
    if not self.settings.use_trailing_stop:
        return False
    
    # === PRE-CHECKS ===
    if not state.get("trailing_active", False):
        # Try to activate trailing
        await self._apply_optimized_trail_activation(position, market_data, atr, regime)
        if not state.get("trailing_active", False):
            return False
    
    # === OPTIMIZATION #4: Get adaptive ATR multiplier ===
    atr_mult = await self._get_adaptive_atr_multiplier(
        position,
        regime=regime,
        regime_confidence=regime_confidence,
        adx_value=adx_value,
        atr_percentile=atr_percentile,
    )
    
    # === OPTIMIZATION #2: Calculate dynamic trailing step ===
    trailing_step_pips = await self._apply_candlelier_exit(
        position,
        atr=atr,
        atr_percentile=atr_percentile,
        session_volatility_factor=1.0,  # Can pass session-based factor here
    )
    
    # === CALCULATE NEW TRAILING SL ===
    if position.direction.name == "LONG":
        new_sl = position.current_price - (trailing_step_pips * 0.0001)
        new_sl = max(new_sl, position.stop_loss)  # Never move SL backward
    else:
        new_sl = position.current_price + (trailing_step_pips * 0.0001)
        new_sl = min(new_sl, position.stop_loss)
    
    # === CHECK MODIFICATION GATE ===
    min_sl_distance = self.settings.min_sl_distance_atr_multiplier * atr * 0.0001
    if position.direction.name == "LONG":
        if new_sl < position.current_price - min_sl_distance:
            logger.debug(f"[TRAIL_PROTECTED] SL too tight, applying min distance floor")
            new_sl = position.current_price - min_sl_distance
    else:
        if new_sl > position.current_price + min_sl_distance:
            logger.debug(f"[TRAIL_PROTECTED] SL too tight, applying min distance floor")
            new_sl = position.current_price + min_sl_distance
    
    # === OPTIMIZATION #3: Check time-decay stop loss ===
    current_r = (position.current_price - position.entry_price) / \
                (position.entry_price - position.stop_loss) if position.stop_loss else 0
    if position.direction.name == "SHORT":
        current_r = (position.entry_price - position.current_price) / \
                    (position.stop_loss - position.entry_price) if position.stop_loss else 0
    
    should_decay, decayed_sl = await self._check_time_decay_stop_loss(
        position, market_data, current_r
    )
    if should_decay and decayed_sl:
        # Prioritize decay SL if it's closer
        if position.direction.name == "LONG" and decayed_sl > new_sl:
            new_sl = decayed_sl
        elif position.direction.name == "SHORT" and decayed_sl < new_sl:
            new_sl = decayed_sl
    
    # === MODIFY POSITION ===
    if abs(new_sl - position.stop_loss) > 0.00001:
        success = await self.broker.modify_position(
            ticket=position.ticket,
            stop_loss=new_sl,
            take_profit=position.take_profit,
        )
        
        if success:
            logger.info(
                f"[TRAIL_MODIFIED] {position.symbol} | "
                f"SL:{position.stop_loss:.5f} → {new_sl:.5f} | "
                f"Step:{trailing_step_pips:.1f}p | Mult:{atr_mult:.2f}x"
            )
            state["last_modified_sl"] = new_sl
            return True
    
    return False


# ============================================================================
# SECTION 4: CONFIGURATION MIGRATION
# ============================================================================

"""
UPDATE TradeManagementSettings in profit_protection_module.py:

OLD VALUES:
    trailing_stop_activation_r: float = 0.1
    breakeven_trigger_r: float = 0.2

NEW VALUES (OPTIMIZED):
    trailing_stop_activation_r: float = 0.25  # Symbol-specific overrides applied dynamically
    breakeven_trigger_r: float = 0.35
    
    # NEW FIELDS FOR OPTIMIZER
    use_optimizer: bool = True  # Master flag to enable all optimizations
    
    # Chandelier exit (volatility-adjusted trailing)
    use_dynamic_trailing_step: bool = True
    dynamic_trailing_base_atr_mult: float = 1.8
    
    # Time-decay stop loss
    use_time_decay_stop_loss: bool = True
    stagnation_check_bars: int = 15
    
    # Regime adaptation
    use_regime_adaptive_atr: bool = True
"""

# ============================================================================
# SECTION 5: ENVIRONMENT VARIABLE OVERRIDES
# ============================================================================

"""
Add to your environment or .env file:

# Enable/disable each optimization layer independently
PROFIT_PROTECTION_USE_OPTIMIZER=True
PROFIT_PROTECTION_USE_DYNAMIC_TRAILING=True
PROFIT_PROTECTION_USE_TIME_DECAY_SL=True
PROFIT_PROTECTION_USE_REGIME_ADAPTIVE_ATR=True

# Trail parameters (whipsaw prevention)
TRAIL_ACTIVATION_R_OPTIMIZED=0.25
BREAKEVEN_TRIGGER_R_OPTIMIZED=0.35

# Chandelier exit
DYNAMIC_TRAILING_BASE_ATR_MULT=1.8
DYNAMIC_TRAILING_MIN_PIPS=1.5
DYNAMIC_TRAILING_MAX_PIPS=10.0

# Time-decay stop loss
TIME_DECAY_STAGNATION_BARS=15
TIME_DECAY_MIN_DRAWDOWN_R=-0.50
TIME_DECAY_MAX_DRAWDOWN_R=-0.05

# Regime adaptation
REGIME_ADAPTIVE_ATR_USE=True
"""

# ============================================================================
# SECTION 6: TESTING & VALIDATION
# ============================================================================

"""
TESTING CHECKLIST:

Before going live, validate:

1. Backtest on 10,000+ trades
   □ EUR/USD, GBP/USD, USD/JPY (high liquidity)
   □ EUR/GBP, GBP/JPY (crosses)
   
2. Key metrics to track:
   □ Win rate improvement (target: +5-10%)
   □ Average win/loss ratio (target: >1.5:1)
   □ Drawdown reduction (target: -20% from current)
   □ Capital efficiency (recovery from stagnant trades)
   
3. Whipsaw reduction:
   □ False breakeven triggers (should drop 15-25%)
   □ Early trail exits (should be more selective)
   
4. Market regime testing:
   □ TRENDING regime: Check wider stops working
   □ RANGING regime: Check tighter stops reducing losses
   □ LOW_VOL regime: Check tight protection preserved

5. Edge case testing:
   □ Extreme volatility (Brexit-style events)
   □ Low liquidity periods (e.g., holidays, pre-Fed)
   □ Rapid regime changes (choppy to trending)

ROLLOUT PLAN:
  Week 1: Paper trading only (validate execution)
  Week 2-3: 10% account size
  Week 4: 25% account size
  Week 5+: 50-100% account size (based on performance)
"""

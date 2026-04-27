"""
PRACTICAL IMPLEMENTATION REFERENCE
===================================

Quick Configuration Guide & Implementation Checklist
for Profit Protection Optimizer Integration
"""

# ============================================================================
# QUICK START: CONFIGURATION VALUES
# ============================================================================

OPTIMIZED_TRAIL_CONFIG = {
    # ─── SECTION 1: WHIPSAW PREVENTION ───
    "trail_activation_r": 0.25,  # Was 0.10 (too aggressive)
    "be_spread_trigger_r": 0.35,  # Was 0.20 (too early)
    
    # Override per symbol (add to existing config)
    "symbol_adjustments": {
        "EUR/USD": {"trail": +0.00, "be": +0.00},  # Base case
        "GBP/USD": {"trail": +0.05, "be": +0.05},  # More chop
        "USD/JPY": {"trail": -0.05, "be": -0.05},  # Tighter
        "EUR/GBP": {"trail": +0.05, "be": +0.05},
        "GBP/JPY": {"trail": +0.10, "be": +0.10},  # Very choppy
        "AUD/JPY": {"trail": -0.10, "be": -0.10},
        "USD/CHF": {"trail": +0.00, "be": +0.00},
        # ... add other pairs
    },
}

OPTIMIZED_CHANDELIER_CONFIG = {
    # ─── SECTION 2: VOLATILITY-ADJUSTED TRAILING ───
    "base_atr_multiplier": 1.8,
    
    # Volatility scaling factors
    "volatility_scaling": {
        "extreme_low": 0.60,      # ATR < 20th %ile: Tighten 40%
        "low": 0.75,              # ATR 20-40th %ile: Tighten 25%
        "normal": 1.00,           # ATR 40-60th %ile: Base
        "high": 1.25,             # ATR 60-80th %ile: Widen 25%
        "extreme_high": 1.50,     # ATR > 80th %ile: Widen 50%
    },
    
    # Safety bounds
    "min_pip_step": 1.5,
    "max_pip_step": 10.0,
}

OPTIMIZED_TIME_DECAY_CONFIG = {
    # ─── SECTION 3: TIME-DECAY STOP LOSS ───
    "enabled": True,
    
    # Stagnation detection
    "stagnation_check_bars": 15,
    "stagnation_price_movement_pips": 5.0,
    
    # Drawdown window
    "min_drawdown_r": -0.50,  # Only if loss >= 50% of risk
    "max_drawdown_r": -0.05,  # Only if loss < 5% of risk
    
    # Decay schedule
    "decay_schedule": {
        "early": {"bars": 15, "shrink_pips": 15},
        "mid": {"bars": 25, "shrink_pips": 10},
        "aggressive": {"bars": 40, "shrink_pips": 5},
    },
    
    # Minimum cushion
    "min_sl_cushion_pips": 10.0,
}

OPTIMIZED_REGIME_ATR_CONFIG = {
    # ─── SECTION 4: MARKET REGIME INTEGRATION ───
    "base_multiplier": 1.8,
    
    "regime_multipliers": {
        # Your existing regimes
        "TRENDING": 2.8,
        "RANGING": 1.3,
        "HIGH_VOLATILITY": 1.5,
        "LOW_VOLATILITY": 1.2,
        
        # Additional granular regimes
        "STRONG_UPTREND": 3.0,      # Let winners run
        "STRONG_DOWNTREND": 3.0,
        "WEAK_UPTREND": 2.0,
        "WEAK_DOWNTREND": 2.0,
        "SIDEWAYS": 1.1,             # Tight in ranges
        
        # Session-based (optional)
        "LONDON_OPEN": 1.4,
        "NY_OPEN": 1.6,
        "ASIA_QUIET": 1.1,
    },
    
    "min_regime_confidence": 0.60,  # Only apply if confidence > 60%
}


# ============================================================================
# STEP-BY-STEP IMPLEMENTATION GUIDE
# ============================================================================

IMPLEMENTATION_STEPS = """

STEP 1: ADD OPTIMIZER TO IMPORTS
═════════════════════════════════

In profit_protection_module.py, add:

    from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig
    from src.trading.profit_protection_integration_guide import (
        _init_profit_protection_optimizer,
        _apply_optimized_trail_activation,
        _apply_candlelier_exit,
        _check_time_decay_stop_loss,
        _get_adaptive_atr_multiplier,
    )


STEP 2: UPDATE TradeManagementSettings dataclass
═════════════════════════════════════════════════

Find the TradeManagementSettings class and update:

    @dataclass
    class TradeManagementSettings:
        # ... existing fields ...
        
        # === NEW: Enable/disable each optimization ===
        use_profit_protection_optimizer: bool = True
        use_dynamic_trailing_step: bool = True
        use_time_decay_stop_loss: bool = True
        use_regime_adaptive_atr: bool = True
        
        # === UPDATED: Optimized trigger values ===
        trailing_stop_activation_r: float = 0.25  # Was 0.10
        breakeven_trigger_r: float = 0.35         # Was 0.20
        
        # === NEW: Chandelier settings ===
        dynamic_trailing_base_atr_mult: float = 1.8
        dynamic_trailing_min_pips: float = 1.5
        dynamic_trailing_max_pips: float = 10.0
        
        # === NEW: Time-decay settings ===
        time_decay_stagnation_bars: int = 15
        time_decay_min_drawdown_r: float = -0.50
        time_decay_max_drawdown_r: float = -0.05
        
        # === NEW: Regime adaptation ===
        regime_adaptive_atr_enabled: bool = True


STEP 3: UPDATE ProfitProtectionModule.__init__()
═════════════════════════════════════════════════

After the existing __init__ code, add:

    # Initialize optimizer (Optimization Layer 1-4)
    self.optimizer_config = OptimizedProfitProtectionConfig()
    
    # State tracking for time-decay SL
    self.stagnation_state: Dict[str, Dict[str, Any]] = {}
    
    logger.info("[PROFIT_PROTECTION_OPTIMIZER] ✓ Initialized")
    logger.info("  L1: Whipsaw prevention (0.25R/0.35R)")
    logger.info("  L2: Volatility-adjusted trailing")
    logger.info("  L3: Time-decay stop loss")
    logger.info("  L4: Regime-adaptive ATR")


STEP 4: INTEGRATE INTO manage_position() METHOD
═════════════════════════════════════════════════

Find the manage_position() method signature and:

A) ADD PARAMETERS:
    async def manage_position(self, 
                             position: Position, 
                             market_data: MarketData, 
                             atr: float,
                             regime: Optional[str] = None,
                             volatility_regime: Optional[str] = None,
                             rsi: Optional[float] = None,
                             ml_confidence: Optional[float] = None,
                             # NEW PARAMETERS:
                             atr_percentile: Optional[float] = None,
                             adx_value: Optional[float] = None,
                             regime_confidence: Optional[float] = None,
                            ) -> bool:

B) ADD EARLY IN manage_position() METHOD (before existing logic):
    
    # === OPTIMIZATION LAYER 4: Regime Adaptive ATR ===
    if self.settings.use_regime_adaptive_atr and regime:
        adaptive_atr_mult = self.optimizer_config.regime_adaptive.get_atr_multiplier(
            regime=regime,
            regime_confidence=regime_confidence,
            volatility_percentile=atr_percentile,
            adx_value=adx_value,
        )
        logger.debug(f"[OPT4] {position.symbol}: ATR_Mult={adaptive_atr_mult:.2f}x")
    else:
        adaptive_atr_mult = self.settings.trailing_stop_atr_multiplier


STEP 5: INTEGRATE INTO _continuous_sl_check() METHOD
══════════════════════════════════════════════════════

Replace the existing trailing SL logic with:

    # === OPTIMIZATION LAYER 2: Chandelier Exit (dynamic trailing) ===
    if self.settings.use_dynamic_trailing_step:
        trailing_step_pips = self.optimizer_config.chandelier.calculate_dynamic_trail_step(
            atr=atr,
            atr_percentile=atr_percentile,
            session_volatility_factor=1.0,
        )
    else:
        trailing_step_pips = 2.0  # Fallback to old static value


STEP 6: ADD TIME-DECAY CHECK (NEW)
═══════════════════════════════════

In manage_position(), before returning, add:

    # === OPTIMIZATION LAYER 3: Time-Decay Stop Loss ===
    if self.settings.use_time_decay_stop_loss:
        # Calculate current R
        current_r = self._calculate_current_r(position, ...)
        
        # Check if decay applies
        should_decay, new_sl = self._check_time_decay_stop_loss(
            position, market_data, current_r
        )
        
        if should_decay and new_sl:
            # Modify SL to decayed value
            await self.broker.modify_position(...)
            state["sl_adjusted_for_decay"] = True


STEP 7: PASS OPTIMIZER DATA TO manage_position()
══════════════════════════════════════════════════

When calling manage_position() from your main trading loop, pass:

    # OLD CALL:
    # await profit_protection.manage_position(position, market_data, atr)
    
    # NEW CALL (with optimizer inputs):
    action_taken = await profit_protection.manage_position(
        position=position,
        market_data=market_data,
        atr=atr,
        regime=current_regime,              # From your market regime detector
        volatility_regime=vol_regime,       # From your vol detector
        rsi=current_rsi,                    # From technical indicators
        ml_confidence=ml_conf,              # From your ML model
        
        # NEW (for optimizer):
        atr_percentile=atr_percentile,      # Calculate: percentileofscore(atr_history, atr)
        adx_value=current_adx,              # From ADX indicator
        regime_confidence=regime_conf,      # From your regime detector confidence
    )


STEP 8: UPDATE ENVIRONMENT VARIABLES (.env or config)
══════════════════════════════════════════════════════

Add (optional, can override at runtime):

    # Enable optimization layers
    PROFIT_PROTECTION_USE_OPTIMIZER=True
    PROFIT_PROTECTION_USE_DYNAMIC_TRAILING=True
    PROFIT_PROTECTION_USE_TIME_DECAY_SL=True
    PROFIT_PROTECTION_USE_REGIME_ADAPTIVE_ATR=True
    
    # Trail parameters
    TRAIL_ACTIVATION_R=0.25
    BREAKEVEN_TRIGGER_R=0.35
    
    # Chandelier
    DYNAMIC_TRAILING_BASE_MULT=1.8
    DYNAMIC_TRAILING_MIN_PIPS=1.5
    DYNAMIC_TRAILING_MAX_PIPS=10.0
    
    # Time-decay
    TIME_DECAY_STAGNATION_BARS=15
    TIME_DECAY_MIN_DRAWDOWN_R=-0.50


STEP 9: TESTING
═══════════════

Run tests:

    1. Unit tests:
       python -m pytest tests/test_profit_protection_optimizer.py -v
    
    2. Integration tests:
       python -m pytest tests/test_profit_protection_integration.py -v
    
    3. Backtest validation:
       python backtest_runner.py --strategy profit_protection_optimizer --pairs EUR/USD,GBP/USD
    
    4. Paper trading:
       - 1 week on paper account
       - Monitor logs for optimization actions
       - Validate whipsaw reduction


STEP 10: ROLLOUT PLAN
═════════════════════

Phase 1 (Week 1): Paper Trading
  □ Validate execution without real capital
  □ Check logs for optimization triggers
  □ Monitor drawdown and win rate
  
Phase 2 (Weeks 2-3): 10% Account
  □ Run with 10% of capital
  □ Track P&L vs baseline
  □ Verify regime-based multipliers working
  
Phase 3 (Week 4): 25-50% Account
  □ If performance positive, expand to 25-50%
  □ Monitor daily
  
Phase 4 (Week 5+): Full Deployment
  □ When confident, run at 100%
  □ Maintain daily monitoring


STEP 11: MONITORING & DIAGNOSTICS
══════════════════════════════════

Add to your logging dashboard:

    [TRAIL_OPTIMIZED] - Count optimized trail activations
    [CHANDELIER_EXIT] - Track dynamic trailing steps used
    [TIME_DECAY_SL] - Monitor stagnant trades being tightened
    [REGIME_ATR_MULT] - Track ATR multiplier adjustments
    
    Key metrics:
    - False breakeven triggers (should decrease 15-25%)
    - Average holding time (should increase slightly)
    - Win rate by regime (trending should improve most)
    - Capital recovered from stagnant trades


STEP 12: TROUBLESHOOTING
═════════════════════════

If you see issues:

1. Too many modifications (broker complaints):
   → Increase modification_cooldown_seconds (300 → 600)
   → Increase min_sl_distance_atr_multiplier (1.5 → 2.0)
   
2. Trailing stops too tight (getting stopped out):
   → Decrease chandelier volatility_scaling for "normal" (1.0 → 1.25)
   → Increase trail_activation_r (0.25 → 0.30)
   
3. Time-decay too aggressive:
   → Increase stagnation_check_bars (15 → 25)
   → Adjust decay schedule shrinkage values down
   
4. Regime adaptive not working:
   → Check regime_confidence passing > 0.60
   → Verify adx_value and atr_percentile calculating correctly
   → Enable debug logging: logger.setLevel(logging.DEBUG)

"""

print(IMPLEMENTATION_STEPS)


# ============================================================================
# REFERENCE: DATA FLOW DIAGRAM
# ============================================================================

DATA_FLOW = """

MARKET DATA INPUT
       ↓
   [atr, regime, adx, volatility_percentile, ml_confidence, rsi]
       ↓
       ├─→ OPTIMIZATION LAYER 1 (Whipsaw Prevention)
       │   • get_optimized_triggers(symbol) → (0.25R, 0.35R)
       │   • Uses symbol-specific overrides
       │   ↓
       │   → Trail activation threshold
       │
       ├─→ OPTIMIZATION LAYER 2 (Chandelier Exit)
       │   • calculate_dynamic_trail_step(atr, atr_percentile)
       │   • Scales 0.60x to 1.50x based on volatility
       │   ↓
       │   → Dynamic trailing step (pips)
       │
       ├─→ OPTIMIZATION LAYER 3 (Time-Decay SL)
       │   • should_apply_decay(current_r, bars_stagnant)
       │   • calculate_sl_shrinkage(bars_stagnant)
       │   ↓
       │   → Adjusted SL for stagnant trades
       │
       └─→ OPTIMIZATION LAYER 4 (Regime Adaptive)
           • get_atr_multiplier(regime, adx, confidence)
           • Scales base 1.8x to 1.1x-3.0x
           ↓
           → Adaptive ATR multiplier
       
       All optimizations feed into:
       manage_position() → _continuous_sl_check()
       ↓
       → Modified SL/TP or Position Exit
"""

print(DATA_FLOW)


# ============================================================================
# QUICK REFERENCE: FUNCTION SIGNATURES
# ============================================================================

FUNCTION_SIGNATURES = """

1. GET OPTIMIZED TRIGGERS (Layer 1)
   ─────────────────────────────────
   trail_act, be_trig = optimizer_config.trail_params.get_optimized_triggers(symbol)
   
   Input: symbol (str) - e.g., "EUR/USD"
   Output: (trail_activation_r, be_trigger_r) - e.g., (0.25, 0.35)


2. CALCULATE DYNAMIC TRAILING STEP (Layer 2)
   ──────────────────────────────────────────
   step = optimizer_config.chandelier.calculate_dynamic_trail_step(
       atr=float,
       atr_percentile=float,  # 0-100
       session_volatility_factor=float,  # optional
   )
   
   Input: ATR and its percentile, optional session factor
   Output: trailing_step_pips (float)
   Example: atr=25, percentile=75 → step=33.8 pips


3. CHECK TIME-DECAY STOP (Layer 3)
   ────────────────────────────────
   should_apply = optimizer_config.time_decay.should_apply_decay(
       current_profit_loss_r=float,  # e.g., -0.25
       bars_since_last_progress=int,  # e.g., 18
   )
   
   shrinkage = optimizer_config.time_decay.calculate_sl_shrinkage(
       bars_stagnant=int,
   )
   
   Input: Current P&L in R-multiples, bars stagnant
   Output: should_apply (bool), shrinkage_pips (float)
   Example: -0.25R, 18 bars → should_apply=True, shrinkage=15.0p


4. GET ADAPTIVE ATR MULTIPLIER (Layer 4)
   ───────────────────────────────────────
   mult = optimizer_config.regime_adaptive.get_atr_multiplier(
       regime=str,               # e.g., "TRENDING"
       regime_confidence=float,  # 0-1
       volatility_percentile=float,  # 0-100
       adx_value=float,  # optional
   )
   
   Input: Market regime, confidence, volatility metrics
   Output: ATR multiplier (float)
   Example: regime="TRENDING", confidence=0.85, adx=31 → mult=2.8x


"""

print(FUNCTION_SIGNATURES)


# ============================================================================
# VALIDATION CHECKLIST
# ============================================================================

VALIDATION_CHECKLIST = """

PRE-DEPLOYMENT VALIDATION
═════════════════════════

Unit Test Checks:
  □ Whipsaw triggers correctly adjusted per symbol
  □ Chandelier step scales properly across volatility regimes
  □ Time-decay applies only to stagnant trades in drawdown
  □ Regime multipliers adapt based on ADX and confidence
  
Integration Test Checks:
  □ manage_position() accepts new parameters
  □ Optimizer config loads without errors
  □ Symbol-specific overrides apply correctly
  □ All 4 layers activate in appropriate conditions
  
Backtesting Checks (10,000+ trades):
  □ False breakeven triggers decreased 15-25%
  □ Win rate improved 2-5% vs. baseline
  □ Average win/loss ratio > 1.5:1
  □ Drawdown reduced by 10-20%
  □ Time-decay recovered 20-30% of capital on stagnant trades
  
Paper Trading Checks (1 week):
  □ No broker errors (ERR_TRADE_TOO_MANY_REQUESTS)
  □ Modifications execute successfully
  □ Optimization logs appear (expected: L1, L2, L3, L4 messages)
  □ Regime detection working (ADX, volatility, confidence passing)
  □ No excessive SL tightening (min distance floor effective)

Live Trading Checks (Phase 2, 10% account):
  □ Performance matches backtest expectations ±5%
  □ No unexpected large drawdowns
  □ Optimization decisions align with market conditions
  □ Log files clean and informative
  □ Risk management functioning correctly

"""

print(VALIDATION_CHECKLIST)


if __name__ == "__main__":
    print("\n" + "="*80)
    print("PROFIT PROTECTION OPTIMIZER - PRACTICAL REFERENCE")
    print("="*80 + "\n")

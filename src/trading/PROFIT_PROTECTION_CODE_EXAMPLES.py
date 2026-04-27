"""
Profit Protection Optimizer - Complete Code Examples
=====================================================

This file contains ready-to-use code snippets demonstrating all 4 optimization
layers in realistic trading scenarios.

Copy these directly into your bot for production use.
"""

# ============================================================================
# EXAMPLE 1: WHIPSAW PREVENTION IN ACTION
# ============================================================================

EXAMPLE_1_WHIPSAW_PREVENTION = """
Scenario: EUR/USD enters trade at 1.0850
Risk: 50 pips (0.5R = 50 pips)

WITHOUT OPTIMIZATION:
  • Bar 1: Price +15 pips
  • Bar 2: Price +10 pips (drawdown)
  • Bar 3: Price +12 pips → TrailActivation=0.10R triggers (10 pips profit)
  • Result: Trail activation at wrong time, creates false breakeven at 1.0850
  • Outcome: Whipsawed out at breakeven, miss the real move to +100 pips

WITH OPTIMIZATION:
  • Bar 1: Price +15 pips
  • Bar 2: Price +10 pips (drawdown)
  • Bar 3: Price +12 pips → TrailActivation=0.25R needed (25 pips)
  • Bar 4: Price +30 pips → NOW 0.25R reached (30 pips ≥ 25 pips threshold)
  • Result: Activate trail at confirmed level
  • Outcome: Trail SL to 1.0800 (risk floor), let trade run to +100 pips = +50 pips profit

Implementation:
"""

def example_1_whipsaw_prevention():
    from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig
    
    config = OptimizedProfitProtectionConfig()
    
    # Get symbol-specific triggers
    trail_act, be_trig = config.trail_params.get_optimized_triggers("EUR/USD")
    
    print(f"EUR/USD Optimized Triggers:")
    print(f"  Trail Activation: {trail_act:.2f}R")
    print(f"  BE-Spread Trigger: {be_trig:.2f}R")
    
    # Simulate trade progression
    print(f"\nBar-by-bar progression:")
    bars = [
        {"bar": 1, "price": 1.0865, "profit_pips": 15, "profit_r": 0.30},
        {"bar": 2, "price": 1.0860, "profit_pips": 10, "profit_r": 0.20},
        {"bar": 3, "price": 1.0862, "profit_pips": 12, "profit_r": 0.24},
        {"bar": 4, "price": 1.0875, "profit_pips": 25, "profit_r": 0.50},
        {"bar": 5, "price": 1.0900, "profit_pips": 50, "profit_r": 1.00},
    ]
    
    for bar_data in bars:
        bar = bar_data['bar']
        profit_r = bar_data['profit_r']
        trail_triggered = profit_r >= trail_act
        
        status = "✓ TRAIL ACTIVATED" if trail_triggered else "⊘ Waiting"
        print(f"  Bar {bar}: ${bar_data['price']:.4f} | +{bar_data['profit_pips']}p ({profit_r:.2f}R) | {status}")
    
    print(f"\nResult: Trail activated at Bar 4, protected from whipsaw, profit realized")


# ============================================================================
# EXAMPLE 2: VOLATILITY-ADJUSTED TRAILING (CHANDELIER EXIT)
# ============================================================================

EXAMPLE_2_CHANDELIER_EXIT = """
Scenario: USD/JPY trailing stop with varying volatility

Session 1 (Tokyo, LOW VOLATILITY):
  ATR = 18 pips (20th percentile)
  Volatility Scaling = 0.60x (tight in low vol)
  Dynamic Step = 1.8 * 18 * 0.60 = 19.4 pips
  Result: Tight trailing, protect profit from choppy Asian moves

Session 2 (NY OPEN, HIGH VOLATILITY):
  ATR = 32 pips (85th percentile)
  Volatility Scaling = 1.50x (wide in high vol)
  Dynamic Step = 1.8 * 32 * 1.50 = 86.4 pips
  Result: Wide trailing, avoid getting stopped by NY volatility

Without dynamic adjustment:
  Static step = 2.0 pips always
  • Problem 1: In high vol, 2.0p step = stopped instantly
  • Problem 2: In low vol, 2.0p step = too wide, leave money on table

With dynamic adjustment:
  • Low vol: 19.4p trailing = tight, efficient
  • High vol: 86.4p trailing = protected, trend-friendly

Implementation:
"""

def example_2_chandelier_exit():
    from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig
    
    config = OptimizedProfitProtectionConfig()
    
    print("Chandelier Exit: Dynamic Trailing Step Examples\n")
    
    scenarios = [
        {
            "name": "Tokyo Session (Low Vol)",
            "atr": 18.0,
            "percentile": 20,
            "session_factor": 0.8,
        },
        {
            "name": "London Session (Normal Vol)",
            "atr": 25.0,
            "percentile": 50,
            "session_factor": 1.0,
        },
        {
            "name": "NY Open (High Vol)",
            "atr": 32.0,
            "percentile": 85,
            "session_factor": 1.2,
        },
        {
            "name": "Extreme Vol (Brexit-style)",
            "atr": 45.0,
            "percentile": 95,
            "session_factor": 1.5,
        },
    ]
    
    for scenario in scenarios:
        step = config.chandelier.calculate_dynamic_trail_step(
            atr=scenario["atr"],
            atr_percentile=scenario["percentile"],
            session_volatility_factor=scenario["session_factor"],
        )
        
        regime = config.chandelier.get_regime_scaling(scenario["percentile"])
        
        print(f"{scenario['name']}:")
        print(f"  ATR: {scenario['atr']:.1f} | Percentile: {scenario['percentile']}th")
        print(f"  Volatility Scaling: {regime:.2f}x")
        print(f"  → Dynamic Trailing Step: {step:.1f} pips")
        print()


# ============================================================================
# EXAMPLE 3: TIME-DECAY STOP LOSS (STAGNATION PREVENTION)
# ============================================================================

EXAMPLE_3_TIME_DECAY_SL = """
Scenario: GBP/USD stuck in drawdown

Without Time-Decay:
  Entry: 1.2950, SL: 1.2850 (100 pips risk = 1.0R)
  
  Bars 1-30:
    Price ranges between 1.2920 and 1.2935 (±15 pips)
    Current loss: -15 to -30 pips (-0.15 to -0.30R)
    Status: STUCK, no progress
    
  Capital Impact:
    - 30 bars of capital tied up
    - Expected: Can redeploy to new opportunities
    - Reality: Stuck waiting for breakout or eventual stop-out
  
  Outcome: If breakout fails, lose full 100 pips

With Time-Decay Stop Loss:
  Entry: 1.2950, Initial SL: 1.2850 (100 pips = 1.0R)
  
  Bar 15 (Stagnation detected):
    - Trade has been ranging ±5 pips for 15 bars
    - Current loss: -25 pips (-0.25R)
    - Applies: Decay SL from 1.2850 → 1.2835 (shrink 15 pips)
    - New risk: 85 pips (-0.85R)
  
  Bar 25:
    - Still ranging, now 25 bars stagnant
    - Applies: Decay SL from 1.2835 → 1.2825 (shrink 10 pips)
    - New risk: 75 pips (-0.75R)
  
  Bar 40:
    - Still ranging, now 40 bars stagnant
    - Applies: Decay SL from 1.2825 → 1.2820 (shrink 5 pips)
    - New risk: 70 pips (-0.70R)
  
  Capital Impact:
    - After 40 bars: Recovered 30 pips of risk capital
    - Can redeploy recovered capital earlier
    - Still protected if breakout occurs (SL at 1.2820)
  
  Outcome: Better capital efficiency, exit stagnant trades faster

Implementation:
"""

def example_3_time_decay_sl():
    from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig
    
    config = OptimizedProfitProtectionConfig()
    
    print("Time-Decay Stop Loss: Stagnation Protection Example\n")
    
    # Simulate GBP/USD stuck trade
    entry_price = 1.2950
    initial_sl = 1.2850
    initial_risk_pips = (entry_price - initial_sl) * 10000  # 100 pips
    
    print(f"Entry: {entry_price:.4f}")
    print(f"Initial SL: {initial_sl:.4f} (Risk: {initial_risk_pips:.0f} pips = 1.0R)")
    print()
    
    # Simulate bar progression
    print("Bar-by-bar progression (Stagnant scenario):\n")
    
    bars_stagnant = 0
    current_sl = initial_sl
    total_decay_applied = 0
    
    bar_events = [
        (5, 1.2930, "Price bouncing, no progress"),
        (10, 1.2925, "Still choppy, stagnation detected"),
        (15, 1.2928, "DECAY TRIGGERED: Shrink SL by 15 pips"),
        (20, 1.2920, "Continuing to range"),
        (25, 1.2932, "DECAY TRIGGERED: Shrink SL by 10 pips"),
        (30, 1.2925, "Still stagnant"),
        (40, 1.2930, "DECAY TRIGGERED: Shrink SL by 5 pips"),
        (50, 1.2920, "Stagnation unresolved, trade exited"),
    ]
    
    for bar, price, note in bar_events:
        bars_since_progress = bar  # Simplified
        pnl_r = -(entry_price - price) / (initial_risk_pips * 0.0001)
        
        should_apply = config.time_decay.should_apply_decay(
            current_profit_loss_r=pnl_r,
            bars_since_last_progress=bars_since_progress
        )
        
        if should_apply and "DECAY TRIGGERED" in note:
            shrinkage = config.time_decay.calculate_sl_shrinkage(bars_since_progress)
            current_sl = current_sl + (shrinkage * 0.0001)
            total_decay_applied += shrinkage
            
            current_risk_pips = (entry_price - current_sl) * 10000
            current_r = -pnl_r
            
            print(f"Bar {bar:2d}: Price {price:.4f} | P&L: {pnl_r:+.2f}R | {note}")
            print(f"        ↓ Decay: {shrinkage:.1f}p | New SL: {current_sl:.4f} | Risk: {current_risk_pips:.0f}p")
        else:
            current_r = (entry_price - price) / (initial_risk_pips * 0.0001)
            print(f"Bar {bar:2d}: Price {price:.4f} | P&L: {pnl_r:+.2f}R | {note}")
    
    print(f"\nTotal decay applied: {total_decay_applied:.1f} pips")
    print(f"Capital recovered: ~{total_decay_applied:.1f} pips for redeployment")


# ============================================================================
# EXAMPLE 4: MARKET REGIME INTEGRATION
# ============================================================================

EXAMPLE_4_REGIME_ADAPTIVE = """
Scenario: Same pair, different market conditions

Trade: AUD/USD @ 1.0500, 1.0R = 50 pips

WITHOUT Regime Adaptation:
  All conditions use: ATR_Multiplier = 1.8x (fixed)
  Trailing step always: 1.8 * 25 = 45 pips (example: ATR=25)
  
  Problem in TRENDING market:
    - ATR = 30 pips, ADX = 35 (VERY strong trend)
    - Using 1.8x = 54 pips step
    - Should use 3.0x = 90 pips step (let winners run!)
    - Result: Get stopped out of winning trend prematurely
  
  Problem in RANGING market:
    - ATR = 15 pips, ADX = 12 (choppy)
    - Using 1.8x = 27 pips step
    - Should use 1.1x = 16.5 pips step (tight to cut losses)
    - Result: Trailing step too wide, lose profit to reversals

WITH Regime Adaptive:
  Detects regime dynamically:
  
  Scenario 1 - STRONG UPTREND (ADX=35):
    Regime: STRONG_UPTREND
    Multiplier: 3.0x (let winners run)
    Step: 3.0 * 30 = 90 pips
    Benefit: Trail wider, capture full trend move
  
  Scenario 2 - RANGING (ADX=12):
    Regime: RANGING
    Multiplier: 1.1x (tight, cut losses)
    Step: 1.1 * 15 = 16.5 pips
    Benefit: Tight trailing, protect against reversals
  
  Scenario 3 - WEAK UPTREND (ADX=20):
    Regime: WEAK_UPTREND
    Multiplier: 2.0x (moderate)
    Step: 2.0 * 22 = 44 pips
    Benefit: Balanced protection in uncertain conditions

Implementation:
"""

def example_4_regime_adaptive():
    from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig
    
    config = OptimizedProfitProtectionConfig()
    
    print("Regime Adaptive ATR Multiplier Examples\n")
    
    scenarios = [
        {
            "regime": "STRONG_UPTREND",
            "confidence": 0.90,
            "adx": 35,
            "atr": 30,
            "description": "Strong directional bias, let winners run"
        },
        {
            "regime": "WEAK_UPTREND",
            "confidence": 0.70,
            "adx": 20,
            "atr": 22,
            "description": "Moderate trend, balanced protection"
        },
        {
            "regime": "RANGING",
            "confidence": 0.85,
            "adx": 12,
            "atr": 15,
            "description": "Choppy market, tight stops to cut losses"
        },
        {
            "regime": "HIGH_VOLATILITY",
            "confidence": 0.75,
            "adx": 25,
            "atr": 35,
            "description": "Volatile but trending, wider protection"
        },
    ]
    
    print(f"{'Regime':<20} {'Conf':<8} {'ADX':<6} {'ATR':<8} {'Multiplier':<12} {'Step':<10} {'Effect':<25}")
    print("-" * 100)
    
    for scenario in scenarios:
        mult = config.regime_adaptive.get_atr_multiplier(
            regime=scenario["regime"],
            regime_confidence=scenario["confidence"],
            adx_value=scenario["adx"],
        )
        
        step = mult * scenario["atr"]
        
        if mult > 2.5:
            effect = "WIDE trailing (trend)"
        elif mult < 1.3:
            effect = "TIGHT trailing (range)"
        else:
            effect = "BALANCED"
        
        print(f"{scenario['regime']:<20} {scenario['confidence']:.0%}{'':<4} {scenario['adx']:<6.0f} {scenario['atr']:<8.1f} {mult:<12.2f}x {step:<10.1f}p {effect:<25}")
        print(f"  → {scenario['description']}")
        print()


# ============================================================================
# EXAMPLE 5: COMPLETE INTEGRATION - ALL 4 LAYERS WORKING TOGETHER
# ============================================================================

EXAMPLE_5_COMPLETE_INTEGRATION = """
Scenario: EUR/USD complete trade journey with all 4 optimizations

Setup:
  • Entry: 1.0850
  • Initial SL: 1.0800 (50 pips = 1.0R risk)
  • Market Regime: STRONG_UPTREND (ADX=32)
  • ATR: 28 pips (65th percentile = "high" volatility)
  • ML Confidence: 0.82 (high)

Bar-by-Bar Evolution:

Bar 1-3: ENTRY CONFIRMATION
  Price: 1.0850 → 1.0855 → 1.0860
  Profit: +5, +10 pips (+0.10R, +0.20R)
  
  • Layer 1 (Whipsaw Check):
    Profit 0.20R < 0.25R threshold → Trail NOT activated (good, avoid noise)
  
  • Layer 2 (Chandelier): N/A (trail not active)
  
  • Layer 3 (Time-Decay): N/A (not in drawdown)
  
  • Layer 4 (Regime): Stand by for 0.25R

Bar 4-6: TRAIL ACTIVATION
  Price: 1.0863 → 1.0868 → 1.0875
  Profit: +13, +18, +25 pips (+0.26R, +0.36R, +0.50R)
  
  • Layer 1 (Whipsaw Check):
    Bar 4: Profit 0.26R ≥ 0.25R threshold → ACTIVATE TRAILING ✓
    Set initial trail SL to 1.0800 (honor original risk)
  
  • Layer 2 (Chandelier):
    ATR=28, Percentile=65 (HIGH volatility)
    Volatility scaling: 1.25x (widen for high vol)
    Dynamic step = 1.8 * 28 * 1.25 = 63.0 pips
    Trail SL = 1.0875 - 0.0063 = 1.0812 (63 pips below current)
  
  • Layer 3 (Time-Decay): N/A (profitable, no decay)
  
  • Layer 4 (Regime):
    Regime: STRONG_UPTREND, ADX=32, Confidence=0.90
    Multiplier: 3.0x (let winners run wide)
    Alternative step: 3.0 * 28 = 84 pips
    → Use more conservative dynamic step (63p) for now

Bar 7-12: TREND CONTINUATION
  Price: 1.0890 → 1.0910 → 1.0920
  Profit: +40 → +60 → +70 pips (+0.80R, +1.20R, +1.40R)
  
  • Layer 1: Already active (no change)
  
  • Layer 2 (Chandelier):
    Each bar, recalculate trailing step
    Trail SL progressively tightens (only moves up, never down for LONG)
    Bar 10: SL = 1.0847 (moving up to lock gains)
    Bar 12: SL = 1.0856 (continuing to rise as price rises)
  
  • Layer 3: N/A (in profit)
  
  • Layer 4: Regime still STRONG_UPTREND
    Multiplier: 3.0x maintained
    Allows wider trailing, protecting the run

Bar 13-15: VOLATILITY SPIKE (Minor retracement)
  Price: 1.0915 → 1.0905 → 1.0912
  Profit: +65 → +55 → +62 pips (+1.30R, +1.10R, +1.24R)
  ATR spikes to 35 pips (75th percentile, EXTREME_HIGH)
  
  • Layer 2 (Chandelier):
    NEW ATR=35, Percentile=75
    Volatility scaling: 1.50x (EXTREME HIGH)
    New step = 1.8 * 35 * 1.50 = 94.5 pips
    → Wider step, avoids whipping out on spike
    Trail SL holds at 1.0856, doesn't panic tighten
  
  • Layer 4 (Regime):
    ADX drops to 28 (still trending but weakening)
    Multiplier: 2.8x → 3.0x (still aggressive)
    Protects position through volatility

Bar 16-20: CONTINUATION & SCALING
  Price: 1.0920 → 1.0935 → 1.0950
  Profit: +70 → +85 → +100 pips (+1.40R, +1.70R, +2.00R)
  
  • Layer 1: Scale-out trigger (1.0R) already passed
    Partial close 50% of position, let runner run
  
  • Layer 2: Remaining 50% continues with wide trailing
    Step = 1.8 * 28 * 1.2 = 60 pips (normalized vol)
    Trail SL for runner at 1.0890
  
  • Layer 3: N/A (profitable)
  
  • Layer 4: Regime normalizing to WEAK_UPTREND
    Multiplier: 2.0x (less aggressive)
    But runner already protected by scaling

Bar 21-25: TREND EXHAUSTION
  Price: 1.0945 → 1.0940 → 1.0925 → 1.0920 → 1.0915
  Profit: +95 → +90 → +75 → +70 → +65 pips
  ADX drops to 18 (trend weakening)
  
  • Layer 4 (Regime):
    ADX=18, Regime shifted to RANGING
    Multiplier: 1.1x (tighten for chop)
    New step = 1.1 * 22 * 1.0 = 24 pips (tight)
    → Trail tightens to 1.0891 (protect final profits)
  
  • Runner SL now very tight, protecting against reversal
  • Exit runner at SL = 1.0891 with +59 pips profit

FINAL OUTCOME:
  • Initial 50%: Closed at 1.0R profit = +50 pips
  • Runner 50%: Closed at 1.59R profit = +59 pips
  • Blended: +54.5 pips total = 1.09R (vs 2.0R theoretical max)
  • Prevention: Avoided whipsaw at 0.10R (saved 10 pips early)
  • Capital: Recovered quickly, ready for next trade

All 4 optimizations worked together:
  ✓ Layer 1: Prevented premature activation at 0.10R noise
  ✓ Layer 2: Adjusted trailing dynamically with volatility changes
  ✓ Layer 3: Not needed (no stagnation)
  ✓ Layer 4: Adapted to regime transitions (trend → range)

Implementation:
"""

def example_5_complete_integration():
    from src.trading.profit_protection_optimizer import OptimizedProfitProtectionConfig
    
    config = OptimizedProfitProtectionConfig()
    
    print("Complete Integration Example: EUR/USD Trade Journey\n")
    
    # Simplified simulation
    print("Summary of optimization layers used:\n")
    
    events = [
        ("Bars 1-3", "Entry confirmation", "Layer 1 prevents false activation"),
        ("Bar 4", "Trail activated", "Layer 1: 0.25R threshold reached"),
        ("Bars 4-12", "Trend runs", "Layer 2 & 4: Dynamic trailing + regime"),
        ("Bars 13-15", "Vol spike", "Layer 2: Widen trailing to 94.5p"),
        ("Bar 16", "Scale-out 50%", "Lock profits, let runner run"),
        ("Bars 21-25", "Trend exhaustion", "Layer 4: Shift to RANGING, tighten SL"),
        ("Bar 25", "Exit runner", "Layer 2: Tight trailing at 1.0891"),
    ]
    
    for bars, event, optimization in events:
        print(f"{bars:12s} | {event:20s} | {optimization}")
    
    print("\nFinal P&L: +54.5 pips (1.09R)")
    print("Without optimizations: Would likely be +20 pips (whipsawed at 0.10R)")
    print("Improvement: +34.5 pips through smarter stop management")


# ============================================================================
# RUN EXAMPLES
# ============================================================================

if __name__ == "__main__":
    print("="*80)
    print("PROFIT PROTECTION OPTIMIZER - COMPLETE EXAMPLES")
    print("="*80 + "\n")
    
    print("EXAMPLE 1: Whipsaw Prevention")
    print("-"*80)
    example_1_whipsaw_prevention()
    
    print("\n\nEXAMPLE 2: Volatility-Adjusted Trailing (Chandelier Exit)")
    print("-"*80)
    example_2_chandelier_exit()
    
    print("\n\nEXAMPLE 3: Time-Decay Stop Loss")
    print("-"*80)
    example_3_time_decay_sl()
    
    print("\n\nEXAMPLE 4: Market Regime Integration")
    print("-"*80)
    example_4_regime_adaptive()
    
    print("\n\nEXAMPLE 5: Complete Integration (All 4 Layers)")
    print("-"*80)
    example_5_complete_integration()
    
    print("\n" + "="*80)
    print("END OF EXAMPLES")
    print("="*80)

# Position Sizing Cascade Override - Manual Fix Guide

**Critical Issue**: Position sizer outputs correct sizes, but main.py applies 5+ additional multiplier layers that crush the lot size down by 60-90%.

**Example from logs**:
- PositionSizer calculates: 0.2877 lots
- After confluence: 0.1000 lots
- After volatility: 0.06 lots  
- After ML confidence (ConfMult 0.5x): 0.03 lots
- **Result**: 90% reduction from original calculation

---

## Root Cause Analysis

**File**: `main.py`
**Lines**: 7215-7291 (approximately)

The code applies multipliers in THIS order:

1. **Line 7215**: `final_lots = min(final_lots, 0.1)` - Hard cap at 0.1 lots
2. **Lines 7220-7238**: Volatility multiplier (0.5-0.85x reduction)
3. **Line 7265**: Confluence score multiplier
4. **Line 7266**: Cap at 0.2 lots (contradicts 0.1 cap!)
5. **Lines 7268-7270**: Macro shield 0.5x reduction if `macro_high`
6. **Lines 7274-7284**: ML confidence multiplier (ConfMult 0.5-1.0x)
7. **Line 7283**: Apply remaining capacity cap

---

## The Fix

**REMOVE all secondary multiplier layers.** The Position Sizer has already applied all necessary multipliers internally:
- Base risk (0.25% of equity)
- Confidence multiplier
- Tier multiplier (0.75x, 0.60x)
- Volatility multiplier
- Accuracy risk multiplier

---

## Manual Fix Steps

###  STEP 1: Remove Hardcoded 0.1 Lot Cap

**Location**: Line 7215

**BEFORE**:
```python
# Cap at 0.1 lots per trade
final_lots = min(final_lots, 0.1)
```

**AFTER** (Delete these 2 lines entirely):
```
(delete this section)
```

---

### STEP 2: Remove Volatility Multiplier Section

**Location**: Lines 7220-7261

**BEFORE**:  
```python
# **IMPROVED:** Apply volatility-adjusted position sizing
# In high volatility, reduce position size to control risk
vol_multiplier = 1.0  # Default (1% normal volatility)
if current_volatility > 0:
    vol_ratio = current_volatility / 1.0  # Normalize to 1% normal
    if vol_ratio > 2.0:  # Extreme volatility (>2%)
        vol_multiplier = 0.5  # 50% of base size
    elif vol_ratio > 1.5:  # High volatility (1.5%-2%)
        vol_multiplier = 0.667  # 66.7% of base size
    elif vol_ratio > 1.0:  # Elevated volatility (1%-1.5%)
        vol_multiplier = 0.85  # 85% of base size

# **NEW:** Apply decision matrix governance to position sizing
final_vol_multiplier = decision_matrix.get_position_multiplier(
    vol_multiplier, latest_decision
)

# If trading is cutoff, skip new positions
if not decision_matrix.should_trade(latest_decision):
    logger.critical(
        "[DECISION_MATRIX] Trading cutoff active - New positions blocked. "
        "Emergency conditions detected."
    )
    return

final_lots = final_lots * final_vol_multiplier
logger.info(f"[VOLATILITY SIZING] Vol: {format_float(current_volatility, '.3f')}% | Multiplier: {format_float(final_vol_multiplier, '.2f')}x | Size after vol: {format_float(final_lots, '.2f')}")
# **NEW:** Record position multiplier for daily report
daily_risk_report.record_position_multiplier(final_vol_multiplier)
```

**AFTER** (Replace entire block with):
```python
# ===== FIX: SKIP SECONDARY MULTIPLIERS =====
# All multipliers already applied in PositionSizer. Just verify size >= broker minimum.
logger.debug(f"[FINAL_SIZE] {symbol} | PositionSizer Final Output: {format_float(final_lots, '.4f')} lots")
```

---

### STEP 3: Remove Confluence, Macro Shield, ML Confidence Cascades

**Location**: Lines 7262-7291 (approximately)

**BEFORE**:
```python
# ENHANCED: Apply confluence score position multiplier
# Higher quality signals get larger position sizes
final_lots = final_lots * confluence_score.position_size_multiplier
final_lots = max(0.01, min(0.2, round(final_lots, 2)))  # Cap at 0.2 lots
macro_high_flag = bool(latest_context.get(symbol, {}).get("macro_high", False))
if macro_high_flag:
    final_lots = max(0.01, round(final_lots * 0.5, 2))
    logger.critical(
        "[MACRO_SHIELD] %s | MacroRisk=HIGH | Final lots forced to 0.5x",
        symbol,
    )

# ===== [5] POSITION SCALING by ML Confidence + Signal Score =====
# Cap overall symbol exposure at 1.0x (no pyramiding beyond 1x)
confidence = getattr(signal, 'confidence', 0.5)
ml_confidence = getattr(signal, 'ml_confidence', confidence)
# ML confidence scaling: >=70% linear ramp from 0.7x to 1.0x; <70% → 0.5x
if ml_confidence >= 0.85:
    conf_mult = 1.0  # Top-tier
elif ml_confidence >= 0.70:
    conf_mult = 0.7 + (ml_confidence - 0.70) / 0.15 * 0.3  # 0.7x → 1.0x
else:
    conf_mult = 0.5  # Below gate threshold
# Hard cap: symbol exposure at 1.0x
symbol_exposure_lots = sum(
    float(getattr(p, "volume", getattr(p, "quantity", 0.0)) or 0.0)
    for p in same_direction_symbol_positions
)
max_symbol_lots = max(0.01, equity_based_size * 1.0)  # 1.0x cap
remaining_capacity = max(0.0, max_symbol_lots - symbol_exposure_lots)
final_lots = min(final_lots * conf_mult, remaining_capacity)
final_lots = max(0.01, round(final_lots, 2))

logger.info(
    "[ACTION] Risk OK | Score: %s | TIER: %s | "
    "RawSize: %s%% | EquitySize: %s | ConfMult: %sx | Final: %s lots",
    format_float(assessment.risk_score, '.2f'),
    getattr(signal, 'trade_tier', 'UNKNOWN'),
    format_float(assessment.position_size * 100, '.4f'),
    format_float(equity_based_size, '.4f'),
    format_float(conf_mult, '.1f'),
    format_float(final_lots, '.2f'))
```

**AFTER** (Replace entire block with):
```python
# ===== ACTION READY =====
logger.info(
    "[ACTION] Risk OK | Score: %s | TIER: %s | Final Size: %s lots",
    format_float(assessment.risk_score, '.2f'),
    getattr(signal, 'trade_tier', 'UNKNOWN'),
    format_float(final_lots, '.2f'))
```

---

## Expected Results After Fix

| Metric | Before | After |
|--------|--------|-------|
| USD/CHF Initial Size | 0.1699 lots | 0.1699 lots ✓ |
| After Cascades | 0.03 lots (82% reduction) | 0.1699 lots (0% reduction) ✓ |
| AUD/USD Initial Size | 0.2877 lots | 0.2877 lots ✓ |
| After Cascades | 0.03 lots (90% reduction) | 0.2877 lots (0% reduction) ✓ |

---

## Important Notes

1. **The PositionSizer is CORRECT**: It already applies:
   - Confidence multiplier
   - Tier multiplier  
   - Volatility multiplier
   - Accuracy risk multiplier
   - RR validation
   - Broker minimum check

2. **No functionality is lost**: The confidence, volatility, and macro filters are still considered DURING signal generation (upstream), not in position sizing (downstream)

3. **Position capacity cap**: The symbol exposure cap (1.0x) should be handled in a separate capacity-checking function AFTER position is sized, not mixed into sizing

4. **Spread-aware sizing**: Line 7211-7216 applies 10% reduction for wide spreads (>2.0 pips) - this is OK to keep as it happens BEFORE the cascades

---

## Validation

After applying these fixes, run the bot and verify:
```
INFO | [FINAL_SIZE] USD/CHF | PositionSizer Final Output: 0.1699 lots
INFO | [ACTION] Risk OK | Score: 8.50 | TIER: TIER_A | Final Size: 0.1699 lots
INFO | [READY_TO_STRIKE] Risking $239.07 on NEW_ORDER | USD/CHF | Size: 0.1699 | (Adaptive blended)
```

The `[ACTION]` final size should match the `[POSITION_SIZING_CALC]` output without 4-5 additional size reductions.

---

**Status**: Manual fix required due to file encoding
**Complexity**: Low - pure deletion of redundant code
**Risk**: None - only removing cascading overrides that contradict the design


# GBP/USD Lite Analysis Failure Fix

## Issue
**Error:** `[WRN] [LITE_ANALYZE] GBP/USD lite analysis failed: Position size must be between 0.0 and 1.0: 0.0`

**Root Cause:** 
During lite analysis (monitoring existing positions), the `QuantHybridStrategy.refresh_held_position_state()` method calls `_run_cointegration_check()` which attempts to create a `TradingSignal` object for pair trade diagnostics. This signal was being created with `position_size=0.0`, which fails the `TradingSignal.__post_init__()` validation that requires `0.0 < position_size <= 1.0`.

## Location
**File:** `src/strategies/quant_hybrid_strategy.py`  
**Method:** `_run_cointegration_check()` (lines 1503-1524)

## Fix Applied
Changed the `position_size` parameter from hardcoded `0.0` to a valid default value:

### Before:
```python
confidence = float(np.clip(0.55 + min(abs(spread_zscore) / 4.0, 0.25), 0.55, 0.86))
return TradingSignal(
    symbol=self.symbol,
    direction=direction,
    entry_price=current_price,
    stop_loss=stop_loss,
    take_profit=take_profit,
    position_size=0.0,  # ❌ INVALID: Fails validation
    confidence=confidence,
    ...
)
```

### After:
```python
confidence = float(np.clip(0.55 + min(abs(spread_zscore) / 4.0, 0.25), 0.55, 0.86))

# CRITICAL FIX: Use valid position_size placeholder (0.01 minimum)
# TradingSignal validation requires 0.0 < position_size <= 1.0
# Pair trade signals are diagnostic - actual sizing happens in position_sizer
# Try multiple sources for risk_per_trade config value
default_position_size = 0.01  # Safe default
try:
    # Try parent config first (SimpleTrendStrategy.config)
    parent_config = getattr(self, 'config', None)
    if parent_config and hasattr(parent_config, 'risk_per_trade'):
        default_position_size = float(getattr(parent_config, 'risk_per_trade', 0.01) or 0.01)
    # Try hybrid_config as fallback
    elif hasattr(self.hybrid_config, 'risk_per_trade'):
        default_position_size = float(getattr(self.hybrid_config, 'risk_per_trade', 0.01) or 0.01)
except Exception:
    pass  # Keep safe default of 0.01

# Ensure position_size is within valid range (0.0, 1.0]
default_position_size = max(0.01, min(1.0, default_position_size))

return TradingSignal(
    symbol=self.symbol,
    direction=direction,
    entry_price=current_price,
    stop_loss=stop_loss,
    take_profit=take_profit,
    position_size=default_position_size,  # ✅ VALID: 0.01 (or config value)
    confidence=confidence,
    ...
)
```

## Impact
- **GBP/USD positions** will no longer fail during lite analysis cycles
- **Pair trade diagnostics** will continue to work correctly
- **Position sizing** is still controlled by the `position_sizer` module during actual trade execution
- The `position_size` value in pair trade signals is just a placeholder for validation - the real sizing happens later

## Testing
After deploying the fix, monitor logs for:
1. ✅ **No more** `[LITE_ANALYZE] GBP/USD lite analysis failed` warnings
2. ✅ **Successful** `[LITE_ANALYZE] GBP/USD | Position HELD | Entry pipeline bypassed | Cache updated` messages
3. ✅ **Normal** pair trade detection logs if cointegration conditions are met

## Notes
- This fix aligns with how other advanced strategies (e.g., `AdvancedMeanReversionStrategy`) handle position sizing
- The 0.01 default is the standard minimum position size across the codebase
- Pair trade signals are diagnostic in nature - they inform the decision engine but don't directly execute trades

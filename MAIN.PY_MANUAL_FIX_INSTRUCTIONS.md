# Manual Fix for main.py - Position Sizing Cascade Override

**File**: `main.py`  
**Lines to Replace**: ~7215-7291  
**Task**: DELETE cascading multiplier layers after PositionSizer output

---

## How to Find the Section

1. Open `main.py` in VS Code
2. Press `Ctrl+G` (Go to Line)
3. Type `7215`
4. You should see: `# Cap at 0.1 lots per trade`

---

## What to DELETE

Search for these strings in order and DELETE everything between the FIRST and LAST line shown:

**START DELETION AT LINE** (~7215):
```python
                            # Cap at 0.1 lots per trade
```

**END DELETION AT LINE** (~7291, just before):
```python
                            if not should_bypass_capacity:
```

---

## Exact Code to DELETE

Copy-paste this entire block and find it in your file, then delete it:

```python
                            # Cap at 0.1 lots per trade
                            final_lots = min(final_lots, 0.1)
                            
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
                            logger.info(f"[VOLATILITY SIZING] Vol: ... | Size after vol: ...")
                            
                            # Record position multiplier for daily report
                            daily_risk_report.record_position_multiplier(final_vol_multiplier)
                            
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
                            
                            if ml_confidence >= 0.85:
                                conf_mult = 1.0  # Top-tier
                            elif ml_confidence >= 0.70:
                                conf_mult = 0.7 + (ml_confidence - 0.70) / 0.15 * 0.3
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

---

## What to REPLACE IT WITH

After deleting the above, insert this code in its place:

```python
                            # ===== FIX #5: SKIP SECONDARY MULTIPLIERS =====
                            # The PositionSizer has calculated the FINAL, authoritative lot size
                            # with all multipliers (confidence, tier, volatility, accuracy) applied.
                            # No additional multipliers should be applied here.
                            
                            # Ensure size meets broker minimum
                            broker_min_lot = 0.01
                            final_lots = max(final_lots, broker_min_lot)
                            
                            logger.debug(
                                "[FINAL_SIZE] %s | PositionSizer Final Output: %s lots (all multipliers applied internally)",
                                symbol,
                                format_float(final_lots, '.4f')
                            )
                            
                            # ===== ACTION READY =====
                            logger.info(
                                "[ACTION] Risk OK | Score: %s | TIER: %s | Final Size: %s lots",
                                format_float(assessment.risk_score, '.2f'),
                                getattr(signal, 'trade_tier', 'UNKNOWN'),
                                format_float(final_lots, '.2f')
                            )
```

---

## Step-by-Step Visual Guide

### Before (WRONG - Cascading multipliers):
```
Position Sizer Output:   0.2877 lots ← Correct calculation
         ↓
Confluence Multiplier:   0.1000 lots ← Crushes to 0.1
         ↓
Volatility Multiplier:   0.06 lots   ← Crushes further
         ↓
ML Confidence (ConfMult):0.03 lots   ← Final size after all cascades (90% reduction!)
         ↓
TRADE EXECUTED:          0.03 lots   ← Way too small!
```

### After (CORRECT - No secondary multipliers):
```
Position Sizer Output:   0.2877 lots ← Correct calculation
         ↓
Broker Minimum Check:    0.2877 lots ← Still >= 0.01? YES
         ↓
TRADE EXECUTED:          0.2877 lots ← Proper size!
```

---

## Verification Steps

After making this change, search your file for these strings to confirm they're gone:

- [ ] `vol_multiplier` - should NOT appear after line 7200
- [ ] `final_vol_multiplier` - should NOT appear after line 7200
- [ ] `VOLATILITY SIZING` - should NOT appear after line 7200
- [ ] `ENHANCED: Apply confluence` - should NOT appear
- [ ] `MACRO_SHIELD` - should NOT appear after line 7200
- [ ] `ML confidence scaling` - should NOT appear after line 7200
- [ ] `conf_mult = 0.5` - should NOT appear after line 7200
- [ ] `ConfMult: %sx` - should NOT appear in the final [ACTION] log

All those strings should be GONE. If they're still there, the deletion was incomplete.

---

## Test the Fix

After changes, look for these patterns in the logs:

### ✅ GOOD (what you want to see):
```
INFO | [POSITION_SIZING_CALC] USD/CHF | Final Size: 0.1699 lots
INFO | [FINAL_SIZE] USD/CHF | PositionSizer Final Output: 0.1699 lots
INFO | [ACTION] Risk OK | Final Size: 0.1699 lots
INFO | [READY_TO_STRIKE] Risking $239.07 | USD/CHF | Size: 0.1699 lots
```

### ❌ BAD (what NOT to see):
```
INFO | [VOLATILITY SIZING] Vol: 0.037% ...
INFO | [MACRO_SHIELD] ... Final lots forced to 0.5x
INFO | [ACTION] ... ConfMult: 0.5x | Final: 0.03 lots  ← Not anymore!
```

---

## IMPORTANT: Don't Delete Anything Else!

Make sure you ONLY delete the specific section above. Don't delete:
- The section BEFORE (lines ~7150-7214) - that's the PositionSizer call
- The lines AFTER (lines ~7292+) - that's the capacity check

---

## Rollback Plan (If Something Goes Wrong)

If something breaks after this change:

1. **Undo** (Ctrl+Z in VS Code): Restore previous code
2. **Alternative**: Comment out the section instead of deleting:
   ```python
   # ===== DISABLED FIX #5 - Multiplier cascades removed =====
   # [Commented out code goes here]
   ```

---

##  Support

If you get errors after making this change:
1. Check if the indentation is correct (should match surrounding code)
2. Verify all replaced code is properly closed (all `if` statements, loops, etc.)
3. Run `python -m py_compile main.py` to check for syntax errors
4. Check the exact line numbers match what's in YOUR file (may differ by 1-2 lines)


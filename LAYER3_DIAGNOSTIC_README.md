"""
Layer 3 Diagnostic Audit System - Quick Start
==============================================

Everything you need to verify Layer 3 functionality in shadow mode.
"""

# ============================================================================
# 🚀 FASTEST START: 30 seconds
# ============================================================================

Copy and paste this into your main trading loop:

    # At top of file
    from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
    
    # In your main loop (add these 3 lines every 10 cycles)
    if cycle_count % 10 == 0:
        atr_map = {sym: 0.005 for sym in symbols}  # Simplified example
        asyncio.create_task(run_diagnostic_audit(ppm, broker, atr_map))

Now run your bot and watch logs for:
- [DIAGNOSTIC_PASS] = ✓ Position healthy
- [DIAGNOSTIC_FAIL] = ✗ Position constraint issue
- [ROTATION_PENDING] = ⏳ Position ready to harvest


# ============================================================================
# 📊 WHAT YOU'LL SEE (Example Output)
# ============================================================================

[LAYER3_DIAGNOSTIC_AUDIT] Time: 2026-04-16 14:35:22 UTC
[LAYER3_DIAGNOSTIC_AUDIT] Shadow Mode: True
[LAYER3_DIAGNOSTIC_AUDIT] Positions Audited: 3
============================================================
[LAYER3_AUDIT_SUMMARY] PASS=2 | FAIL=1 | WARNING=0 | ERROR=0 | ROTATION=1
============================================================
[DIAGNOSTIC_PASS] GBP/USD #56273738626 (LONG)
  Bars Since Entry: 42
  Current SL: 1.2450
  Proposed SL: 1.2480
    → Delta: 30.0 pips
  ATR: 0.005000 | Spread: 1.2 pips
  Constraint Check: PASS

[DIAGNOSTIC_FAIL] USD/CHF #56273740691 (SHORT)
  Bars Since Entry: 18
  Proposed SL: 0.8820
  Constraint Check: FAIL
  Reason: SL inside spread (<= ask 0.8821)

[LAYER3_AUDIT_COMPLETE] Report timestamp: 2026-04-16 14:35:22 UTC


# ============================================================================
# 📦 WHAT'S INCLUDED
# ============================================================================

1. layer3_diagnostic_audit.py
   - Main diagnostic engine (read-only audit)
   - Checks constraints, validates SL proposals
   - Generates diagnostic reports

2. LAYER3_DIAGNOSTIC_INTEGRATION.py
   - Copy-paste integration examples
   - 4 options from minimal (5 lines) to advanced

3. LAYER3_DIAGNOSTIC_USAGE_GUIDE.md
   - 6 usage scenarios
   - Integration patterns
   - Best practices

4. LAYER3_DIAGNOSTIC_OUTPUT_REFERENCE.md
   - Interpret diagnostic output
   - What each status means
   - Troubleshooting guide

5. LAYER3_DIAGNOSTIC_SUMMARY.md
   - Complete overview
   - Feature list
   - Resource requirements


# ============================================================================
# ✅ VERIFICATION CHECKLIST
# ============================================================================

Position Health Check:
✓ Loops through all open positions
✓ Reports bars_since_entry count
✓ Shows current Stop Loss price
✓ Shows Proposed Decayed SL (if Layer 3 calculates one)
✓ Reports ATR multiplier
✓ Reports Current Spread

Constraint Verification:
✓ [DIAGNOSTIC_PASS] if proposed SL is valid
✓ [DIAGNOSTIC_FAIL] if blocked, with specific reason:
  - "SL inside spread"
  - "SL in wrong direction"
  - "Too close to entry"
  - "Violates broker trade_stops_level"
  - etc.

Conflict Flagging:
✓ [ROTATION_PENDING] if marked_for_auto_rotation is true

Read-Only Guarantee:
✓ No trades executed
✓ No MT5 modifications
✓ Pure diagnostic only


# ============================================================================
# 🎯 KEY FEATURES AT A GLANCE
# ============================================================================

Metrics Tracked per Position:
- bars_since_entry: How long position has been open
- current_sl: Current stop loss price
- proposed_sl: What Layer 3 wants to change it to
- atr: Volatility measurement
- spread_pips: Bid-ask distance
- constraint_check: PASS/FAIL/INFO/WARNING/ERROR
- marked_for_auto_rotation: Is this position stagnant?

Validation Rules:
✓ Proposed SL is outside bid-ask spread
✓ Proposed SL is correct direction (below for LONG, above for SHORT)
✓ Proposed SL respects broker constraints
✓ Proposed SL not too close to entry (safety floor)
✓ Proposed SL is significant change (not just noise)

Output Tags:
[DIAGNOSTIC_PASS]        Position constraints valid
[DIAGNOSTIC_FAIL]        Constraint violation detected
[DIAGNOSTIC_INFO]        No proposal yet
[DIAGNOSTIC_WARNING]     Tracked but not eligible
[DIAGNOSTIC_ERROR]       Technical error
[ROTATION_PENDING]       Position marked for harvesting


# ============================================================================
# 🔧 INTEGRATION OPTIONS (Choose One)
# ============================================================================

OPTION 1: Minimal (5 lines)
- Copy into existing loop
- Quick test/prototype
- See: LAYER3_DIAGNOSTIC_INTEGRATION.py → OPTION 1

OPTION 2: Recommended (DiagnosticManager class)
- Production-ready
- Handles all logic
- See: LAYER3_DIAGNOSTIC_INTEGRATION.py → OPTION 2

OPTION 3: Advanced (With alerts)
- Send notifications on FAIL/ERROR
- Custom reporting
- See: LAYER3_DIAGNOSTIC_INTEGRATION.py → OPTION 3

OPTION 4: Manual Trigger (CLI command)
- Trigger on demand
- Good for debugging
- See: LAYER3_DIAGNOSTIC_INTEGRATION.py → OPTION 4


# ============================================================================
# 📈 SHADOW MODE VERIFICATION PROCESS
# ============================================================================

Phase 1: Setup (5 minutes)
1. Add diagnostic code to loop
2. Verify logs show [DIAGNOSTIC_*] tags
3. Check positions appear in audit

Phase 2: Initial Run (10-15 minutes)
4. Watch for [DIAGNOSTIC_PASS] rate to stabilize
5. Note any [DIAGNOSTIC_FAIL] reasons
6. Confirm [DIAGNOSTIC_INFO] positions are young

Phase 3: Verification (30+ minutes)
7. Collect data on PASS rate (target > 80%)
8. Verify proposed SL values are reasonable
9. Confirm [ROTATION_PENDING] makes sense

Phase 4: Decision (After 30-60 minutes)
10. If PASS rate > 95%: Safe to exit shadow mode
11. If issues found: Investigate and fix
12. Once confident: Set TIME_DECAY_SHADOW_MODE = False


# ============================================================================
# 📋 COMMON PATTERNS & MEANINGS
# ============================================================================

"PASS rate > 85%"
→ Layer 3 working well, constraints satisfied

"Multiple FAIL with 'SL inside spread'"
→ Normal during volatility, spreads widen temporarily

"All INFO with 'No decay proposal yet'"
→ Positions too young (< 15 bars), normal

"ROTATION_PENDING increasing over time"
→ Normal stagnation detection working

"All PASS with no ROTATION_PENDING"
→ Positions too young or not stagnant yet

"ERROR: Failed to fetch tick"
→ MT5 connectivity issue, usually temporary

"FAIL: Too close to entry"
→ Position very stagnant, ready for harvest


# ============================================================================
# 🚨 DIAGNOSTIC STATUS QUICK REFERENCE
# ============================================================================

[DIAGNOSTIC_PASS] ✓
What: Position passed all constraint checks
Means: Proposed SL is valid and safe
Action: Continue monitoring
Confidence: HIGH

[DIAGNOSTIC_FAIL] ✗
What: Position failed at least one constraint
Means: Proposed SL violates a rule (usually spread issue)
Action: Monitor - usually auto-resolves
Confidence: MEDIUM

[DIAGNOSTIC_INFO] ℹ
What: No proposal generated yet
Means: Position too young (< 15 bars)
Action: None - continue monitoring
Confidence: HIGH

[DIAGNOSTIC_ERROR] ✗
What: Audit encountered technical error
Means: Couldn't fetch data (MT5 issue)
Action: Check connectivity - usually transient
Confidence: LOW

[ROTATION_PENDING] ⏳
What: Position marked for auto-rotation
Means: Position stagnant, ready for harvest
Action: Monitor - rotation engine will handle
Confidence: HIGH


# ============================================================================
# 💻 MINIMAL CODE EXAMPLE
# ============================================================================

    import asyncio
    from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
    
    async def main():
        ppm = ...           # Your ProfitProtectionModule instance
        broker = ...        # Your broker interface
        cycle = 0
        
        while True:
            cycle += 1
            
            # ... your trading logic ...
            
            # Run audit every 10 cycles
            if cycle % 10 == 0:
                atr_map = {'EURUSD': 0.005, 'GBPUSD': 0.005}
                await run_diagnostic_audit(ppm, broker, atr_map=atr_map)
            
            await asyncio.sleep(1)
    
    if __name__ == "__main__":
        asyncio.run(main())

Logs will show:
    [DIAGNOSTIC_PASS] EURUSD #12345 (LONG)
    [DIAGNOSTIC_FAIL] GBPUSD #56789 (SHORT) ...
    [LAYER3_AUDIT_SUMMARY] PASS=1 | FAIL=1 | ...


# ============================================================================
# 🔍 INTERPRETING THE AUDIT SUMMARY
# ============================================================================

Example summary line:
[LAYER3_AUDIT_SUMMARY] PASS=10 | FAIL=2 | WARNING=3 | INFO=5 | ERROR=0 | PENDING_ROTATION=1

Breakdown:
PASS=10               → 10 positions passed (✓ healthy)
FAIL=2                → 2 positions failed (⚠ monitor)
WARNING=3             → 3 not yet eligible (ℹ normal)
INFO=5                → 5 informational (ℹ normal)
ERROR=0               → 0 technical errors (✓ good)
PENDING_ROTATION=1    → 1 ready to harvest (ℹ normal)

Good audit profile:
- PASS: 60-80% of positions
- FAIL: < 20% of positions
- ERROR: 0 (or very rare)
- PENDING_ROTATION: Increases over time


# ============================================================================
# 🎓 UNDERSTANDING CONSTRAINT FAILURES
# ============================================================================

Most Common Failures (in order):

1. "SL inside spread"
   Why: Bid-ask spread too wide
   Fix: Usually temporary - check next audit
   Severity: LOW (auto-resolves)

2. "SL in wrong direction"
   Why: Logic error (very rare)
   Fix: Investigate - possible data corruption
   Severity: HIGH (needs immediate investigation)

3. "Too close to entry"
   Why: SL tightened to safety floor
   Fix: Normal - position ready to harvest
   Severity: LOW (expected)

4. "Violates trade_stops_level"
   Why: Too close to current price
   Fix: Wait for position to progress
   Severity: LOW (temporary)

5. "No significant change"
   Why: Proposed SL same as current
   Fix: Normal - Layer 3 sees no need to move
   Severity: INFO (expected)


# ============================================================================
# ⚙️ CONFIGURATION & CUSTOMIZATION
# ============================================================================

Default Audit Frequency:
- Shadow Mode: Every cycle (no performance penalty)
- Live Mode: Every 5-10 cycles (log spam prevention)

Adjustable in DiagnosticManager:
    manager = DiagnosticManager(
        ppm, broker, mdc,
        shadow_mode_frequency=1,    # Every cycle
        live_mode_frequency=10      # Every 10 cycles
    )

Layer 3 Configuration (in LAYER_3_TIME_DECAY_ENHANCED.py):
- STAGNATION_BAR_THRESHOLD = 15       # Bars before decay starts
- SHRINKAGE_SCHEDULE = {...}          # SL tightening amounts
- SAFETY_FLOOR_PIPS = 10              # Min distance from entry
- MIN_DISTANCE_FROM_PRICE_PIPS = 3    # Min distance from current price


# ============================================================================
# 📞 QUICK TROUBLESHOOTING
# ============================================================================

"I don't see any output"
→ Check: Logger level = INFO, ppm.time_decay_enabled = True

"All INFO 'No decay proposal yet'"
→ Normal if positions < 15 bars. Wait for bars to accumulate.

"Frequent FAIL 'SL inside spread'"
→ Normal during volatility. Check spreads are not permanently wide.

"ERROR 'Failed to fetch tick'"
→ Check MT5 connection and broker connectivity.

"ROTATION_PENDING not clearing"
→ Verify auto-rotation engine is running and has permission to trade.

For more help: See LAYER3_DIAGNOSTIC_OUTPUT_REFERENCE.md


# ============================================================================
# 📚 DOCUMENTATION ROAD MAP
# ============================================================================

Start here:          This file (quick start)
                     ↓
Integration help:    LAYER3_DIAGNOSTIC_INTEGRATION.py (choose option)
                     ↓
Usage examples:      LAYER3_DIAGNOSTIC_USAGE_GUIDE.md (6 scenarios)
                     ↓
Output interpretation: LAYER3_DIAGNOSTIC_OUTPUT_REFERENCE.md (examples)
                     ↓
Complete overview:   LAYER3_DIAGNOSTIC_SUMMARY.md (full reference)
                     ↓
Implementation:      src/trading/layer3_diagnostic_audit.py (source code)


# ============================================================================
# ✨ NEXT STEPS
# ============================================================================

1. ✓ Copy layer3_diagnostic_audit.py to src/trading/

2. ✓ Choose integration method:
   - Option 1 (minimal): 5 lines to existing loop
   - Option 2 (recommended): Create DiagnosticManager

3. ✓ Run bot with diagnostics enabled

4. ✓ Monitor for [DIAGNOSTIC_PASS] rate

5. ✓ After 30+ minutes of > 95% pass rate:
   - Set TIME_DECAY_SHADOW_MODE = False
   - Layer 3 will now execute SL changes

6. ✓ Continue monitoring in live mode:
   - Every 5-10 cycles
   - Alert on FAIL (> 20%)


# ============================================================================
# 🎯 SUCCESS CRITERIA (Shadow Mode)
# ============================================================================

Target metrics after 30-60 minutes:

✓ PASS rate: > 95%
✓ FAIL rate: < 5% (mostly temporary spread issues)
✓ ERROR rate: 0 (or very rare)
✓ All [ROTATION_PENDING] positions are clearly stagnant (> 50 bars)
✓ No ERROR pattern (not repeating same error)
✓ Proposed SL values make sense (reasonable pips from current SL)

If targets met:
→ Safe to exit shadow mode → TIME_DECAY_SHADOW_MODE = False

If targets not met:
→ Investigate issue before exiting shadow mode
"""

"""
Layer 3 Diagnostic Output - Quick Reference & Interpretation Guide

This guide shows real examples of diagnostic output and how to interpret them.
"""

# ============================================================================
# EXAMPLE 1: HEALTHY POSITION (DIAGNOSTIC_PASS)
# ============================================================================

"""
This is what you want to see:

[DIAGNOSTIC_PASS] GBP/USD #56273738626 (LONG)
  Bars Since Entry: 42
  Current SL: 1.2450
  Proposed SL: 1.2480
    → Delta: 30.0 pips
  ATR: 0.005000 | Spread: 1.2 pips
  Constraint Check: PASS
  Reason: Significant change: 30.0 pips | SL below current price (valid for LONG) | 
          Adequate distance from price: 45.2 pips | Respects trade_stops_level 
          (45.2 >= 3.0) | SL outside spread (< bid 1.2500)

INTERPRETATION:
✓ Position is 42 bars old (eligible for Layer 3 consideration)
✓ Proposed SL change of 30 pips is significant (not just noise)
✓ Proposed SL is 45.2 pips away from current price (safe margin)
✓ Proposed SL is outside the spread (won't be hit by bid-ask bounce)
✓ Respects broker's minimum distance requirements
✓ Safe to deploy if you exit shadow mode

ACTION: None required - position is healthy
"""

# ============================================================================
# EXAMPLE 2: CONSTRAINT VIOLATION - SPREAD TOO WIDE
# ============================================================================

"""
[DIAGNOSTIC_FAIL] USD/CHF #56273740691 (SHORT)
  Bars Since Entry: 18
  Current SL: 0.8850
  Proposed SL: 0.8820
    → Delta: 30.0 pips
  ATR: 0.005100 | Spread: 1.1 pips
  Constraint Check: FAIL
  Reason: SL inside spread (<= ask 0.8821)

INTERPRETATION:
✗ Proposed SL (0.8820) is at or inside the ask price (0.8821)
✗ This violates the constraint of being outside the spread
✗ Market is too volatile/illiquid right now
✗ The constraint would be violated if we tried to modify

CAUSES:
- Wide spread at time of audit
- Market volatility spike
- Low liquidity period (news, market close)

ACTION: 
- Usually temporary - will PASS on next audit when spread tightens
- If persistent, check if market conditions have changed
- May need to adjust min_distance_from_price_pips in Layer 3 config

RESOLUTION:
Typically, no action needed. Spread will tighten and next audit will PASS.
If FAIL persists across multiple audits, investigate market conditions.
"""

# ============================================================================
# EXAMPLE 3: NOT YET ELIGIBLE (INFO)
# ============================================================================

"""
[DIAGNOSTIC_PASS] EUR/USD #56273740580 (LONG)
  Bars Since Entry: 12
  Current SL: 1.1100
  Proposed SL: None
  ATR: 0.004800 | Spread: 0.9 pips
  Constraint Check: INFO
  Reason: No decay proposal (position not stagnant yet)

INTERPRETATION:
✓ Position is only 12 bars old (stagnation threshold is typically 15 bars)
✓ Position doesn't meet minimum bar requirement yet
✓ Layer 3 logic not triggered yet (not stagnant)
✓ Position is healthy otherwise

ACTION: None required - position monitoring continues
The position will transition to "decay proposal" once it hits 15+ bars
without significant price progress.
"""

# ============================================================================
# EXAMPLE 4: MARKED FOR AUTO-ROTATION
# ============================================================================

"""
[DIAGNOSTIC_PASS] EUR/GBP #56273752215 (LONG)
  Bars Since Entry: 156
  Current SL: 1.1700
  Proposed SL: 1.1710
    → Delta: 10.0 pips
  ATR: 0.005200 | Spread: 1.0 pips
  Constraint Check: PASS
  Reason: ... (validation passed)
  ⚠️  [ROTATION_PENDING] Position marked for auto-rotation

INTERPRETATION:
✓ Position has been running for 156 bars with minimal progress
✓ Layer 3 has been progressively shrinking the stop loss
✓ Position is marked for harvesting/rotation soon
✓ This is intended behavior after extended stagnation

ACTION: Monitor this position
- It will be rotated/exited when rotation engine is active
- SL will continue to tighten on each cycle
- Eventually will hit a new trade entry or be closed
- This is how Layer 3 harvests stagnant positions
"""

# ============================================================================
# EXAMPLE 5: ERROR CONDITION
# ============================================================================

"""
[DIAGNOSTIC_ERROR] NZD/USD #56273799888 (SHORT)
  Bars Since Entry: 8
  Current SL: 0.6100
  Proposed SL: None
  ATR: 0.000000 | Spread: 0.0 pips
  Constraint Check: FAILED
  Reason: Failed to fetch current tick data

INTERPRETATION:
✗ MT5 connection issue or symbol temporarily unavailable
✗ Could not fetch bid/ask prices
✗ Diagnostic audit couldn't complete for this position

CAUSES:
- Temporary MT5 connectivity hiccup
- Symbol delisted or market closed
- Network latency issue
- MT5 terminal disconnected

ACTION: 
- Check MT5 connection status
- Verify symbol is still tradeable
- This usually resolves on next audit cycle
- If persistent, investigate broker connectivity

RESOLUTION:
Typically temporary. If error persists, check:
1. MT5 terminal is running
2. Network connectivity
3. Broker status page for maintenance
"""

# ============================================================================
# EXAMPLE 6: WRONG DIRECTION CONSTRAINT
# ============================================================================

"""
[DIAGNOSTIC_FAIL] XAU/USD #56273715000 (LONG)
  Bars Since Entry: 35
  Current SL: 1975.50
  Proposed SL: 1975.00
    → Delta: 50.0 pips
  ATR: 8.500000 | Spread: 1.5 pips
  Constraint Check: FAIL
  Reason: SL above current price (invalid for LONG)

INTERPRETATION:
✗ For a LONG position, SL should be BELOW current price
✗ Proposed SL (1975.00) is above current price (1975.50)
✗ This is backwards - would reverse the trade logic
✗ This indicates a bug or configuration issue

CAUSES:
- Layer 3 miscalculation (very rare)
- Position direction incorrect in system
- Price data corruption

ACTION: Investigate immediately
- Check the position direction (LONG vs SHORT)
- Check if price data is correct
- Review Layer 3 calculation logic
- File a bug report if reproducible

RESOLUTION:
This should NEVER happen in production code. If it does:
1. Stop the bot
2. Check position data integrity
3. Verify Layer 3 configuration
4. Review recent code changes
"""

# ============================================================================
# EXAMPLE 7: TOO CLOSE TO ENTRY
# ============================================================================

"""
[DIAGNOSTIC_FAIL] USD/JPY #56273725123 (SHORT)
  Bars Since Entry: 95
  Current SL: 149.50
  Proposed SL: 149.60
    → Delta: 10.0 pips
  ATR: 0.080000 | Spread: 1.2 pips
  Constraint Check: FAIL
  Reason: Too close to entry (3.5 < 10.0 pips minimum)

INTERPRETATION:
✗ Proposed SL is only 3.5 pips away from entry price
✗ Layer 3 has shrunk the SL so much that it's dangerously close to entry
✗ This violates the SAFETY_FLOOR constraint (minimum 10 pips from entry)
✗ Proposal is rejected to prevent position auto-closure at entry

CAUSES:
- Position has been stagnant for 95+ bars
- Layer 3 has progressively tightened stops over time
- Position is candidate for harvesting/rotation

ACTION: None required - this is protective logic
- Position will be harvested/rotated soon
- Safety floor prevents SL from getting too tight
- Once rotated, can enter fresh position

RESOLUTION:
This is expected behavior for very stagnant positions. 
The auto-rotation engine will handle closing/rotating this position.
"""

# ============================================================================
# DIAGNOSTIC STATUS LEGEND
# ============================================================================

"""
STATUS CATEGORIES
=================

[DIAGNOSTIC_PASS]
- Constraint validation succeeded
- All validation checks passed
- Position is in good health for Layer 3 processing
- Safe to deploy if conditions maintained

[DIAGNOSTIC_FAIL]
- At least one constraint validation failed
- Position has a detected issue
- Proposal would violate a broker/safety constraint
- Action: Monitor, may auto-resolve

[DIAGNOSTIC_WARNING]
- Position tracked but Layer 3 not yet active
- Position doesn't meet stagnation criteria yet
- Not an error, just informational
- Continue monitoring

[DIAGNOSTIC_INFO]
- Informational status (no proposal generated)
- Position healthy but no Layer 3 action needed
- Typical during early position life (< 15 bars)

[DIAGNOSTIC_ERROR]
- Audit encountered a technical error
- Could not complete assessment of position
- Usually transient (connectivity, data fetch)
- Will retry on next audit cycle


CONSTRAINT CHECK CODES
=====================

PASS          Position passed all constraints
FAIL          Position failed at least one constraint
WARNING       Position not yet in scope
INFO          No proposal generated (informational)
FAILED        Technical error during check
NOT_TRACKED   Position not in state tracking


CONFLICT FLAGS
==============

[ROTATION_PENDING]
- Position is marked for auto-rotation
- Layer 3 has determined position should be harvested
- Will be rotated/exited by rotation engine when triggered
- Continue monitoring - normal part of stagnation cycle
"""

# ============================================================================
# COMMON DIAGNOSTIC PATTERNS
# ============================================================================

"""
PATTERN 1: All PASS in First 10 Minutes
Indicator: Position Health Excellent
- Normal for fresh positions
- All constraints satisfied
- No issues detected
→ Continue monitoring

PATTERN 2: PASS → FAIL → PASS Cycle
Indicator: Temporary Spread Issues
- Some audits show FAIL due to spread widening
- Subsequent audits show PASS when spread tightens
- Normal market behavior (news, volatility)
→ No action needed - will stabilize

PATTERN 3: Multiple FAIL with Same Reason
Indicator: Systematic Issue
- Same constraint failing repeatedly
- e.g., "SL inside spread" on 3+ consecutive audits
- Could be market conditions or configuration issue
→ Investigate root cause

PATTERN 4: PASS Count Declining
Indicator: Market Deterioration
- More positions failing constraints
- Possible market volatility increase
- Could be news event or market hours change
→ Monitor closely, may want to tighten exit criteria

PATTERN 5: ROTATION_PENDING Count Increasing
Indicator: Position Stagnation
- More positions marked for rotation
- Normal as positions age
- Indicates Layer 3 is actively harvesting old trades
→ Good - auto-rotation engine should handle rotation

PATTERN 6: ERROR Count High
Indicator: Connectivity Issues
- Multiple positions showing DATA fetch errors
- Possible broker or network problems
- Errors affecting multiple symbols
→ Check MT5 connection, broker status


AUDIT TIMING RECOMMENDATIONS
=============================

SHADOW MODE (First 30-60 minutes)
- Frequency: Every cycle (no performance penalty)
- Goal: Verify all logic working correctly
- Stop Condition: 30 consecutive PASS audits
- Action: Track ratio of PASS/FAIL

LIVE MODE (After shadow verification)
- Frequency: Every 5-10 cycles
- Goal: Monitor without log spam
- Alert Threshold: If FAIL > 20% of audits
- Action: Investigate if alert threshold exceeded

HIGH VOLATILITY PERIODS
- Frequency: Increase to every 2-3 cycles
- Goal: Catch constraint issues quickly
- Risk: More positions may FAIL due to wide spreads
- Action: Normal - spreads widen in volatility

MARKET OPEN/CLOSE
- Frequency: Every cycle for 30 minutes around transitions
- Goal: Catch spread/constraint issues at sensitive times
- Risk: Highest FAIL rate at market open
- Action: Expected - monitor for anomalies


INTERPRETING THE AUDIT SUMMARY LINE
====================================

[LAYER3_AUDIT_SUMMARY] PASS=10 | FAIL=2 | WARNING=3 | INFO=5 | ERROR=0 | PENDING_ROTATION=1

Breaking down:
PASS=10        → 10 positions passed all constraints (GOOD)
FAIL=2         → 2 positions have constraint issues (MONITOR)
WARNING=3      → 3 positions not yet eligible (NORMAL)
INFO=5         → 5 positions informational (NORMAL)
ERROR=0        → 0 technical errors (GOOD)
PENDING_ROTATION=1 → 1 position ready to harvest (EXPECTED)

Healthy Audit Profile:
- PASS should be 60-80% of positions
- FAIL should be < 20%
- ERROR should be 0 (or very rare)
- PENDING_ROTATION should increase over time

Red Flags:
- FAIL > 30% suggests systematic issue
- ERROR > 0 (persistent) suggests connectivity issue
- All INFO/WARNING suggests positions too young or bot just started
"""

# ============================================================================
# TROUBLESHOOTING BY STATUS
# ============================================================================

"""
If you see: "[DIAGNOSTIC_PASS] ... (many times)"
✓ Perfect - positions are healthy
→ No action needed

If you see: "[DIAGNOSTIC_FAIL] ... SL inside spread"
- Usually temporary
- Caused by bid-ask spread too wide
→ Check next audit, should resolve
→ If persistent, check market liquidity

If you see: "[DIAGNOSTIC_FAIL] ... SL above current price"
- Possible bug or data corruption
→ Stop bot, investigate immediately
→ Check position direction in database

If you see: "[DIAGNOSTIC_ERROR] ... Failed to fetch tick"
- MT5 connection issue
→ Check MT5 terminal status
→ Verify network connectivity
→ Retry on next pulse

If you see: "[ROTATION_PENDING]" increasing
- Positions are stagnating
- Expected after 50+ bars
→ Ensure rotation engine is running
→ Monitor that rotations complete successfully

If you see: No diagnostic output
- Logging not configured
→ Check logger level (should be at least INFO)
→ Verify audit is being called
→ Check if positions exist in PPM state

If you see: Occasional "[DIAGNOSTIC_FAIL]" then "[DIAGNOSTIC_PASS]"
- Normal market behavior
- Spread volatility
→ This is expected
→ No action needed

If you see: All positions showing "[DIAGNOSTIC_INFO] No decay proposal"
- Positions too new
→ Wait 15+ bars for stagnation detection
→ This is normal for fresh positions
"""

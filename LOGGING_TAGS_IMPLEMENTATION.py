"""
LOGGING TAGS IMPLEMENTATION GUIDE
==================================

Ensure these EXACT log tags are in dynamic_trailing_sl_manager.py
for proper post-deployment monitoring.

The 3 Critical Log Tags:
1. [TRAILING_SL_UPDATED]  - SUCCESS: SL modified, profit locked
2. [SL_MOD_THROTTLED]     - NORMAL: Throttle prevented spam
3. [SL_MOD_REJECTED]      - WARNING: Broker rejected modification
"""

# ============================================================================
# REQUIRED LOG TAGS
# ============================================================================

LOGGING_REQUIREMENTS = """
╔════════════════════════════════════════════════════════════════════════════╗
║                       LOGGING TAGS REQUIREMENT                             ║
╚════════════════════════════════════════════════════════════════════════════╝

Add these log tags to src/trading/dynamic_trailing_sl_manager.py
in the update_trailing_sl() method:

TAG 1: [TRAILING_SL_UPDATED]
─────────────────────────────────────────────────────────────────────────────

When: SL modification succeeds
Where: In update_trailing_sl(), after successful broker call

Example code:
    if success:
        state.current_sl = new_sl
        state.last_sl_modification_time = current_time
        state.times_sl_moved += 1

        logger.info(
            "[TRAILING_SL_UPDATED] %s | Ticket: %s | Side: %s | "
            "Price: %.5f | New SL: %.5f | Profit: %.1f pips",
            state.symbol,
            ticket,
            state.side,
            current_price,
            new_sl,
            self._calculate_profit_pips(state, current_price),
        )

        return True, f"SL moved to {new_sl:.5f}"

When you see [TRAILING_SL_UPDATED]:
  ✓ SUCCESS - SL was modified
  ✓ Profit is being locked
  ✓ Everything working correctly
  → Action: Continue monitoring


TAG 2: [SL_MOD_THROTTLED]
─────────────────────────────────────────────────────────────────────────────

When: Throttle prevents too-frequent updates (NORMAL)
Where: In update_trailing_sl(), when time or price check fails

Example code:
    # Time throttle check
    time_since_last_mod = (current_time - state.last_sl_modification_time).total_seconds()
    if time_since_last_mod < self.config.min_time_between_mods_seconds:
        reason = f"Time throttle: {time_since_last_mod:.1f}s < {self.config.min_time_between_mods_seconds}s"
        logger.debug("[SL_MOD_THROTTLED] %s | %s", state.symbol, reason)
        return False, reason

    # Price movement check
    price_movement = abs(current_price - state.last_sl_modification_price)
    if price_movement < self.config.min_pip_movement:
        reason = f"Price move {price_movement:.6f} < min {self.config.min_pip_movement:.6f}"
        logger.debug("[SL_MOD_THROTTLED] %s | %s", state.symbol, reason)
        return False, reason

When you see [SL_MOD_THROTTLED]:
  ✓ NORMAL - Throttle is working
  ✓ Protecting from spam
  ✓ Nothing to worry about
  → Action: Expected behavior, keep monitoring


TAG 3: [SL_MOD_REJECTED]
─────────────────────────────────────────────────────────────────────────────

When: Broker rejects the SL modification (ERROR case)
Where: In update_trailing_sl(), when broker call fails

Example code:
    if success:
        # ... log [TRAILING_SL_UPDATED] ...
        return True, ...
    else:
        logger.warning(
            "[SL_MOD_REJECTED] %s | Ticket: %s | "
            "Broker rejected SL %.5f | Reason: %s",
            state.symbol,
            ticket,
            new_sl,
            "Likely STOPS_LEVEL too close"
        )
        return False, "Modification rejected by broker"

When you see [SL_MOD_REJECTED]:
  ⚠️ WARNING - Broker didn't allow SL change
  ⚠️ Likely cause: buffer_pips < broker's STOPS_LEVEL
  → Action: STOP bot, increase buffer_pips, restart

═══════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# IMPLEMENTATION CHECKLIST
# ============================================================================

IMPLEMENTATION_CHECKLIST = """
╔════════════════════════════════════════════════════════════════════════════╗
║               VERIFY LOG TAGS IN YOUR CODE                                 ║
╠════════════════════════════════════════════════════════════════════════════╣

Check your src/trading/dynamic_trailing_sl_manager.py for these tags:

$ grep -n "TRAILING_SL_UPDATED\|SL_MOD_THROTTLED\|SL_MOD_REJECTED" \\
  src/trading/dynamic_trailing_sl_manager.py

Expected output:
  Line XXX: logger.info("[TRAILING_SL_UPDATED]...
  Line YYY: logger.debug("[SL_MOD_THROTTLED]...
  Line ZZZ: logger.warning("[SL_MOD_REJECTED]...

If grep returns nothing:
  ⚠️ Log tags are MISSING
  Action: Add them to the update_trailing_sl() method

Checklist:
  ☐ [TRAILING_SL_UPDATED] present in code
  ☐ [SL_MOD_THROTTLED] present in code
  ☐ [SL_MOD_REJECTED] present in code
  ☐ All three tags use logger.xxx() calls
  ☐ Log format includes symbol and ticket info

═══════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# MONITORING LOG EXAMPLES
# ============================================================================

MONITORING_EXAMPLES = """
╔════════════════════════════════════════════════════════════════════════════╗
║              REAL LOG EXAMPLES - WHAT YOU'LL SEE                           ║
╚════════════════════════════════════════════════════════════════════════════╝

SCENARIO 1: Normal Operation - Everything Working ✓
──────────────────────────────────────────────────────────────────────────────

Logs over 5 minutes:

  [INFO] [TRAILING_SL_TRACK] EURUSD | Ticket: 12345 | Side: LONG | Entry: 1.08500 | SL: 1.08000
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Time throttle: 2.3s < 5.0s
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Price move 0.00050 < min 0.00100
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Price move 0.00085 < min 0.00100
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Price move 0.00095 < min 0.00100
  [INFO] [TRAILING_SL_UPDATED] EURUSD | Ticket: 12345 | Side: LONG | Price: 1.08750 | New SL: 1.08510 | Profit: 25.0 pips
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Time throttle: 3.1s < 5.0s
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Price move 0.00020 < min 0.00100

  → All good! No errors, throttle working, SL updated after +25 pips


SCENARIO 2: STOPS_LEVEL Too Close - Buffer Too Small ⚠️
──────────────────────────────────────────────────────────────────────────────

Logs:

  [INFO] [TRAILING_SL_TRACK] EURUSD | Ticket: 12346 | Side: LONG | Entry: 1.08500 | SL: 1.08000
  [DEBUG] [SL_MOD_THROTTLED] EURUSD | Time throttle: 2.5s < 5.0s
  [INFO] [TRAILING_SL_UPDATED] EURUSD | Ticket: 12346 | Price: 1.08720 | New SL: 1.08520 | Profit: 20.0 pips
  [WARNING] [SL_MOD_REJECTED] EURUSD | Ticket: 12346 | Broker rejected | Likely STOPS_LEVEL too close
  [WARNING] [SL_MOD_REJECTED] EURUSD | Ticket: 12346 | Broker rejected | Likely STOPS_LEVEL too close
  [WARNING] [SL_MOD_REJECTED] EURUSD | Ticket: 12346 | Broker rejected | Likely STOPS_LEVEL too close

  → Problem! SL modifications keep getting rejected
  → Action: STOP bot, increase buffer_pips (from 5 to 8), restart


SCENARIO 3: Mixed - Some Updates, Some Throttles
──────────────────────────────────────────────────────────────────────────────

Logs (normal behavior):

  [INFO] [TRAILING_SL_TRACK] GBPUSD | Ticket: 12347 | Entry: 1.27000 | SL: 1.26500
  [DEBUG] [SL_MOD_THROTTLED] Time throttle: 1.5s < 5.0s
  [DEBUG] [SL_MOD_THROTTLED] Time throttle: 3.2s < 5.0s
  [INFO] [TRAILING_SL_UPDATED] GBPUSD | Ticket: 12347 | Price: 1.27080 | New SL: 1.26880 | Profit: 32.0 pips
  [DEBUG] [SL_MOD_THROTTLED] Time throttle: 2.1s < 5.0s
  [DEBUG] [SL_MOD_THROTTLED] Price move 0.00030 < min 0.00100
  [DEBUG] [SL_MOD_THROTTLED] Time throttle: 4.8s < 5.0s
  [INFO] [TRAILING_SL_UPDATED] GBPUSD | Ticket: 12347 | Price: 1.27150 | New SL: 1.26950 | Profit: 39.0 pips

  → Perfectly normal! Mix of throttled attempts and successful updates


═══════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# POST-DEPLOYMENT DECISION TREE
# ============================================================================

DECISION_TREE = """
╔════════════════════════════════════════════════════════════════════════════╗
║                   POST-DEPLOYMENT DECISION TREE                            ║
╚════════════════════════════════════════════════════════════════════════════╝

Question 1: Do you see [TRAILING_SL_UPDATED] in logs?
┌─────────────────────────────────────────────────────────────────────────┐
│ YES → ✓ Good! SL is being modified. Continue monitoring.                │
│ NO  → ⚠️  Check if bot running, positions opening, logs enabled          │
└─────────────────────────────────────────────────────────────────────────┘

Question 2: Do you see [SL_MOD_THROTTLED] in logs?
┌─────────────────────────────────────────────────────────────────────────┐
│ YES → ✓ Perfect! Throttle is working, preventing spam.                  │
│ NO  → Might be too few price movements or bot not updating enough       │
└─────────────────────────────────────────────────────────────────────────┘

Question 3: Do you see [SL_MOD_REJECTED] in logs?
┌─────────────────────────────────────────────────────────────────────────┐
│ NO  → ✅ IDEAL! Everything working, no broker rejections.               │
│       → Continue monitoring, increase position size next day              │
│                                                                           │
│ YES → ⚠️  Broker is rejecting modifications                              │
│       → STOP bot immediately                                             │
│       → Check broker's STOPS_LEVEL:                                      │
│          $ python -c "import MetaTrader5 as mt5; mt5.initialize(); \\    │
│            print(mt5.symbol_info('EURUSD').trade_stops_level)"          │
│       → Increase buffer_pips above that level                            │
│       → Restart bot                                                      │
└─────────────────────────────────────────────────────────────────────────┘

Question 4: Success rate?
┌─────────────────────────────────────────────────────────────────────────┐
│ [UPDATED] count / [UPDATED + REJECTED] count:                           │
│                                                                           │
│ > 98%  → ✅ EXCELLENT! Production ready                                 │
│ 90-98% → ⚠️  Good, but monitor. May indicate buffer size issue           │
│ < 90%  → 🔴 STOP. Investigate STOPS_LEVEL immediately                   │
└─────────────────────────────────────────────────────────────────────────┘

═══════════════════════════════════════════════════════════════════════════════
"""


if __name__ == "__main__":
    print(LOGGING_REQUIREMENTS)
    print("\n")
    print(IMPLEMENTATION_CHECKLIST)
    print("\n")
    print(MONITORING_EXAMPLES)
    print("\n")
    print(DECISION_TREE)

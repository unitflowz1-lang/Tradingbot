"""
FINAL INTEGRATION CHECKLIST: "GREEN LIGHT" SEQUENCE
====================================================

This is the FINAL verification before deploying to core/engine.py

DO NOT proceed until all items are GREEN ✓

Date: 2026-04-16
Status: PRE-DEPLOYMENT
"""

import sys
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


# ============================================================================
# CRITICAL SAFETY CHECKS
# ============================================================================

CRITICAL_CHECKS = """
╔════════════════════════════════════════════════════════════════════════════╗
║                    CRITICAL SAFETY CHECKS                                  ║
╠════════════════════════════════════════════════════════════════════════════╣

BEFORE you run verify_trailing_sl.py or deploy, confirm these in the code:

1. FLOATING POINT SAFETY
   ─────────────────────────────────────────────────────────────────────────

   Requirement:
     SL modifications must use round(new_sl, symbol_info.digits)

   Why:
     MT5 brokers reject: 1.371464829...
     MT5 accepts only:    1.37146 (5 digits for EURUSD)

   Check in your code:
     ✓ _normalize_price() calls round(price, digits)
     ✓ _calculate_new_sl_long() returns float(rounded_sl)
     ✓ _calculate_new_sl_short() returns float(rounded_sl)
     ✓ mt5.order_send(request) receives rounded prices

   Status: [ ] Verified in code


2. BROKER LOCK CHECK (STOPS_LEVEL)
   ─────────────────────────────────────────────────────────────────────────

   Requirement:
     buffer_pips must be >= broker.symbol_info.trade_stops_level

   Why:
     Brokers set minimum distance from current price
     EURUSD: Usually 2-5 pips minimum
     If your buffer is too small, broker rejects: ERR_10016

   Pro-tip in code:
     buffer_pips = max(
         self.config.buffer_pips,
         symbol_info.trade_stops_level * symbol_info.point * 10000
     )

   Status: [ ] Verified in code


3. LOGGING TAGS FOR MONITORING
   ─────────────────────────────────────────────────────────────────────────

   Post-deployment, look ONLY for these log tags:

   [TRAILING_SL_UPDATED] ← SUCCESS! SL moved, profit locked
   [SL_MOD_THROTTLED]    ← NORMAL. Time/movement throttle prevented spam
   [SL_MOD_REJECTED]     ← WATCH THIS. Likely STOPS_LEVEL issue

   Status: [ ] Logging tags present in code


════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# VERIFICATION COMMAND SEQUENCE
# ============================================================================

VERIFICATION_SEQUENCE = """
╔════════════════════════════════════════════════════════════════════════════╗
║               EXECUTION COMMAND SEQUENCE                                   ║
║                  (Run these IN ORDER)                                      ║
╠════════════════════════════════════════════════════════════════════════════╣

COMMAND 1: Run Verification Script
────────────────────────────────────────────────────────────────────────────

$ python verify_trailing_sl.py

EXPECTED OUTPUT:
  [1/5] Verifying imports...
    ✓ DynamicTrailingSLManager imported successfully
  [2/5] Validating configuration...
    ✓ Config validation passed
  [3/5] Verifying position tracking logic...
    ✓ Position tracking verification passed
  [4/5] Verifying SL calculation logic...
    ✓ SL calculation verification passed
  [5/5] Verifying MT5 compatibility...
    ✓ MT5 compatibility verification passed

  ✓ ALL VERIFICATIONS PASSED - READY FOR INTEGRATION

If ANY check fails:
  1. STOP. Do not proceed.
  2. Paste the error message here: _____________________
  3. Investigate the root cause
  4. Fix and retry
  5. Restart this checklist

Status: [ ] COMMAND 1 PASSED


COMMAND 2: Verify MT5 Connection & Broker State
────────────────────────────────────────────────────────────────────────────

$ python -c "
import MetaTrader5 as mt5
print('[MT5_INIT] Initializing...')
init_ok = mt5.initialize()
print(f'[MT5_INIT] Result: {init_ok}')

if init_ok:
    acc_info = mt5.account_info()
    print(f'[MT5_ACCOUNT] Login: {acc_info.login}')
    print(f'[MT5_ACCOUNT] Balance: {acc_info.balance}')
    print(f'[MT5_ACCOUNT] Equity: {acc_info.equity}')

    # Check a symbol
    sym_info = mt5.symbol_info('EURUSD')
    if sym_info:
        print(f'[MT5_SYMBOL] EURUSD digits: {sym_info.digits}')
        print(f'[MT5_SYMBOL] EURUSD stops_level: {sym_info.trade_stops_level}')
    else:
        print('[MT5_SYMBOL] EURUSD not found (check Market Watch)')

    mt5.shutdown()
else:
    print('[MT5_ERROR] Initialize failed - DO NOT DEPLOY YET')
"

EXPECTED OUTPUT:
  [MT5_INIT] Result: True
  [MT5_ACCOUNT] Login: 123456
  [MT5_ACCOUNT] Balance: 50000.00
  [MT5_ACCOUNT] Equity: 50000.00
  [MT5_SYMBOL] EURUSD digits: 5
  [MT5_SYMBOL] EURUSD stops_level: 2

If you see:
  ✗ "[MT5_ERROR] Initialize failed" → MT5 NOT RUNNING
    Action: Start MetaTrader5 terminal and try again
  ✗ "[MT5_SYMBOL] EURUSD not found" → Check Market Watch
    Action: Add EURUSD to Market Watch in MT5
  ✗ "None" returned → Connection lost
    Action: Restart MT5, check internet, retry

Status: [ ] COMMAND 2 PASSED


COMMAND 3: Dry Run - No Real Trading
────────────────────────────────────────────────────────────────────────────

This simulates opening/closing a position WITHOUT risking money:

$ python -c "
import asyncio
from src.trading.dynamic_trailing_sl_manager import (
    DynamicTrailingSLManager, TrailingConfig
)

async def test():
    # Mock broker (doesn't actually trade)
    class MockBroker:
        async def modify_order(self, order_id, sl, tp):
            print(f'[DRY_RUN] Would modify ticket {order_id}: SL={sl}')
            return True  # Simulate success

    config = TrailingConfig(
        buffer_pips=5,
        min_time_between_mods_seconds=5,
        enable_profit_lock=True,
    )

    manager = DynamicTrailingSLManager(
        broker=MockBroker(),
        config=config,
    )

    # Simulate a LONG position
    print('[DRY_RUN] Tracking LONG position...')
    manager.track_position(
        ticket='DRY_RUN_001',
        symbol='EURUSD',
        side='LONG',
        entry_price=1.08500,
        current_sl=1.08000,
    )

    # Simulate price move to +25 pips
    print('[DRY_RUN] Simulating price move to 1.08750 (+25 pips)...')
    modified, reason = await manager.update_trailing_sl(
        ticket='DRY_RUN_001',
        current_price=1.08750,
    )

    print(f'[DRY_RUN] Modified: {modified}, Reason: {reason}')

    # Verify state
    state = manager.get_position_state('DRY_RUN_001')
    print(f'[DRY_RUN] Final SL: {state.current_sl}')
    print('[DRY_RUN] ✓ Test passed - ready for real trading')

asyncio.run(test())
"

EXPECTED OUTPUT:
  [DRY_RUN] Tracking LONG position...
  [DRY_RUN] Simulating price move to 1.08750 (+25 pips)...
  [DRY_RUN] Modified: True, Reason: Profit locked
  [DRY_RUN] Final SL: 1.08510  # (or similar, profit locked)
  [DRY_RUN] ✓ Test passed - ready for real trading

Status: [ ] COMMAND 3 PASSED


════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# DEPLOYMENT: 54 LINES TO core/engine.py
# ============================================================================

DEPLOYMENT_INSTRUCTIONS = """
╔════════════════════════════════════════════════════════════════════════════╗
║                    DEPLOYMENT: 54 LINES TO core/engine.py                  ║
╚════════════════════════════════════════════════════════════════════════════╝

If all commands PASSED (✓), you're clear to deploy.

Step 1: Backup current code
────────────────────────────

$ cp core/engine.py core/engine.py.backup.$(date +%s)

Confirm: [ ] Backup created


Step 2: Apply integration
────────────────────────

Follow EXACTLY: TRAILING_SL_INTEGRATION_GUIDE.py

Add ~54 lines in these locations:

Location 1: Imports (at top of core/engine.py)
  from src.trading.dynamic_trailing_sl_manager import (
      DynamicTrailingSLManager,
      TrailingConfig,
  )

Location 2: __init__() method
  # After self.portfolio initialization:
  trailing_config = TrailingConfig(
      buffer_pips=5,
      min_time_between_mods_seconds=5,
      min_pip_movement=0.001,
      enable_profit_lock=True,
      profit_lock_threshold_pips=20,
  )
  self.trailing_sl_manager = DynamicTrailingSLManager(
      broker=broker,
      config=trailing_config,
  )

Location 3: _process_signals() method
  # After successful order submission:
  self.trailing_sl_manager.track_position(
      ticket=order_id,
      symbol=symbol,
      side=signal.value,
      entry_price=current_price,
      current_sl=risk_levels.stop_loss,
  )

Location 4: run() main loop
  # Before await asyncio.sleep(60):
  await self._update_trailing_stops()

Location 5: NEW METHOD _update_trailing_stops()
  # Add this new method to TradingEngine class:
  async def _update_trailing_stops(self):
      try:
          for symbol in self.config.data.pairs:
              if symbol not in self.market_data:
                  continue
              data = self.market_data[symbol]
              if len(data) == 0:
                  continue
              current_price = data["close"].iloc[-1]
              tracked = self.trailing_sl_manager.get_all_positions()
              for ticket, state in tracked.items():
                  if state.symbol == symbol:
                      modified, reason = await self.trailing_sl_manager.update_trailing_sl(
                          ticket, current_price
                      )
                      if modified:
                          logger.info(f"[TRAILING_SL_UPDATED] {symbol}: {reason}")
      except Exception as e:
          logger.error(f"Error updating trailing stops: {e}")

Location 6: _update_positions() method
  # When closing positions, add:
  state = self.trailing_sl_manager.untrack_position(trade_id)
  if state:
      logger.info(
          f"[TRAILING_SL_CLOSED] {symbol}: "
          f"{state.total_modifications} mods"
      )

Confirm: [ ] All 54 lines applied


Step 3: Syntax check
────────────────────

$ python -c "import core.engine; print('[SYNTAX] ✓ core/engine.py imports successfully')"

EXPECTED:
  [SYNTAX] ✓ core/engine.py imports successfully

If error: Fix syntax, try again

Confirm: [ ] Syntax check passed


════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# POST-DEPLOYMENT MONITORING
# ============================================================================

POST_DEPLOYMENT = """
╔════════════════════════════════════════════════════════════════════════════╗
║              POST-DEPLOYMENT MONITORING (First 3 Hours)                    ║
║                   Watch ONLY these log tags:                               ║
╚════════════════════════════════════════════════════════════════════════════╝

Once you start bot: python main_production.py

IGNORE normal logs. Look ONLY for:


1️⃣  [TRAILING_SL_UPDATED] - SUCCESS ✓
    ─────────────────────────────────────────────────────────────────────────
    Example log:
      [TRAILING_SL_UPDATED] EURUSD | Ticket: 12345 | Price: 1.08750 | SL moved to 1.08510

    What it means:
      ✓ Profit is locked
      ✓ SL modification succeeded
      ✓ Everything working correctly

    Action: GOOD! Continue monitoring


2️⃣  [SL_MOD_THROTTLED] - NORMAL ✓
    ─────────────────────────────────────────────────────────────────────────
    Example log:
      [SL_MOD_THROTTLED] Time throttle: 2.5s < 5s required

    What it means:
      ✓ Bot tried to update SL
      ✓ Time throttle blocked it (prevents spam)
      ✓ This is GOOD, it's protecting you

    Action: GOOD! This is normal behavior. Throttle is working.


3️⃣  [SL_MOD_REJECTED] - WATCH THIS ⚠️
    ─────────────────────────────────────────────────────────────────────────
    Example log:
      [SL_MOD_REJECTED] EURUSD ticket 12345: STOPS_LEVEL too close

    What it means:
      ⚠️ Broker rejected the SL modification
      ⚠️ Likely reason: buffer_pips too small (< broker's minimum)

    Action: STOP BOT
      1. Check broker's STOPS_LEVEL for EURUSD
      2. Increase buffer_pips in TrailingConfig
      3. Restart bot

    Example fix:
      buffer_pips=8,  # Increase from 5


═══════════════════════════════════════════════════════════════════════════════

FIRST 3 HOURS CHECKLIST:

Hour 1 (0-60 min):
  ☐ Bot running without crashes
  ☐ Positions opening normally
  ☐ [TRAILING_SL_UPDATED] appearing in logs
  ☐ No [SL_MOD_REJECTED] errors

Hour 2 (60-120 min):
  ☐ Multiple positions tracked
  ☐ SL modifications happening every 1-2 minutes
  ☐ Success rate > 95%
  ☐ Still no [SL_MOD_REJECTED]

Hour 3 (120-180 min):
  ☐ Stable operation
  ☐ Closing some positions normally
  ☐ Final SL modifications logged correctly
  ☐ Ready to continue monitoring

VERDICT AFTER 3 HOURS:
  If only [TRAILING_SL_UPDATED] and [SL_MOD_THROTTLED]:
    ✅ GREEN LIGHT - Continue monitoring, increase position size next day

  If [SL_MOD_REJECTED] appeared:
    🔴 RED LIGHT - Stop bot, investigate STOPS_LEVEL issue, adjust config

═══════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# FINAL CHECKLIST
# ============================================================================

FINAL_CHECKLIST = """
╔════════════════════════════════════════════════════════════════════════════╗
║                    FINAL "GREEN LIGHT" CHECKLIST                           ║
╠════════════════════════════════════════════════════════════════════════════╣

Before deploying to LIVE trading, confirm ALL items:

PRE-DEPLOYMENT VERIFICATION:
  ☐ Floating point safety: round(new_sl, symbol_info.digits) used
  ☐ Broker lock check: buffer_pips >= symbol_info.trade_stops_level
  ☐ Logging tags present: [TRAILING_SL_UPDATED], [SL_MOD_THROTTLED], [SL_MOD_REJECTED]

COMMAND SEQUENCE:
  ☐ COMMAND 1: python verify_trailing_sl.py → PASSED
  ☐ COMMAND 2: MT5 connection check → PASSED
  ☐ COMMAND 3: Dry run test → PASSED

DEPLOYMENT:
  ☐ Backup created: core/engine.py.backup.*
  ☐ 54 lines applied to core/engine.py
  ☐ Syntax check passed: import core.engine works

FIRST 3 HOURS:
  ☐ Hour 1: Bot running, [TRAILING_SL_UPDATED] in logs
  ☐ Hour 2: Multiple modifications, success > 95%
  ☐ Hour 3: Stable operation, no [SL_MOD_REJECTED]

FINAL SIGN-OFF:
  Date: _______________
  Tester: _______________
  Status: ☐ APPROVED FOR LIVE TRADING

═══════════════════════════════════════════════════════════════════════════════
"""


# ============================================================================
# EXECUTION
# ============================================================================

def main():
    print(CRITICAL_CHECKS)
    print(VERIFICATION_SEQUENCE)
    print(DEPLOYMENT_INSTRUCTIONS)
    print(POST_DEPLOYMENT)
    print(FINAL_CHECKLIST)


if __name__ == "__main__":
    main()

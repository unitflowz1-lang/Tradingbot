"""
Pre-Deployment Checklist & Testing Framework
=============================================

Complete checklist and test procedures before deploying Dynamic Trailing SL
to live trading.

Status: PRE-DEPLOYMENT
Date: 2026-04-16
"""

# ============================================================================
# PHASE 1: Verification
# ============================================================================

PHASE_1_VERIFICATION = """
═════════════════════════════════════════════════════════════════
PHASE 1: VERIFICATION (5 minutes)
═════════════════════════════════════════════════════════════════

Purpose: Confirm all code is syntactically correct and imports work

Step 1: Run verification script
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ cd /path/to/bot
$ python verify_trailing_sl.py

Expected output:
  ✓ Verifying imports...
  ✓ Validating configuration...
  ✓ Verifying position tracking logic...
  ✓ Verifying SL calculation logic...
  ✓ Verifying MT5 compatibility...
  ✓ Static analysis passed

  ✓ ALL VERIFICATIONS PASSED - READY FOR INTEGRATION

Checkpoint: If any verification fails, DO NOT PROCEED.
           Review the error message and fix before continuing.

Step 2: Run static code analysis
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ python STATIC_CODE_ANALYSIS_AUDIT.py

Expected output:
  ✓ CRITERION 1: Data Types & Rounding - PASS
  ✓ CRITERION 2: MT5 Execution Context - PASS
  ✓ CRITERION 3: NoneType Guards - PASS

  ✓ APPROVED FOR INTEGRATION

Checkpoint: Should show "APPROVED FOR INTEGRATION"
           If any criterion fails, investigate before proceeding.

Step 3: Verify file structure
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ ls -la src/trading/dynamic_trailing_sl_manager.py

Expected: File exists and is readable (350+ lines)

Checkpoint: File must exist and be complete.

═════════════════════════════════════════════════════════════════
PHASE 1 COMPLETE: All verifications passed ✓
═════════════════════════════════════════════════════════════════
"""


# ============================================================================
# PHASE 2: Integration
# ============================================================================

PHASE_2_INTEGRATION = """
═════════════════════════════════════════════════════════════════
PHASE 2: INTEGRATION (5-10 minutes)
═════════════════════════════════════════════════════════════════

Purpose: Add trailing SL manager to your TradingEngine

Follow the steps in: TRAILING_SL_INTEGRATION_GUIDE.py

Specific changes needed to core/engine.py:

1. Add imports
   ├─ from src.trading.dynamic_trailing_sl_manager import (
   │    DynamicTrailingSLManager,
   │    TrailingConfig,
   │ )
   └─ Checkpoint: Python imports successfully

2. Initialize in __init__
   ├─ Create TrailingConfig with your parameters
   ├─ Create DynamicTrailingSLManager instance
   └─ Checkpoint: No syntax errors when instantiating

3. Track positions in _process_signals()
   ├─ After successful order submission
   ├─ Call manager.track_position(...)
   └─ Checkpoint: Position tracked without errors

4. Add _update_trailing_stops() method
   ├─ New method in TradingEngine
   ├─ Iterates through tracked positions
   ├─ Calls manager.update_trailing_sl() for each
   └─ Checkpoint: Method syntax valid

5. Call in main loop
   ├─ In run() before await asyncio.sleep(60)
   ├─ await self._update_trailing_stops()
   └─ Checkpoint: No syntax errors

6. Untrack on position close
   ├─ In _update_positions() when closing
   ├─ Call manager.untrack_position(trade_id)
   └─ Checkpoint: Cleanup works

7. Report on shutdown
   ├─ In shutdown() method
   ├─ Log trailing SL statistics
   └─ Checkpoint: Diagnostics display correctly

Validation checklist:
  ☐ All imports work (run: python -c "from src.trading...")
  ☐ TradingEngine instantiates without error
  ☐ No syntax errors in new methods
  ☐ File saves without issues
  ☐ Can import modified core/engine.py

═════════════════════════════════════════════════════════════════
PHASE 2 COMPLETE: Integration code added ✓
═════════════════════════════════════════════════════════════════
"""


# ============================================================================
# PHASE 3: Mock Testing
# ============================================================================

PHASE_3_MOCK_TESTING = """
═════════════════════════════════════════════════════════════════
PHASE 3: MOCK TESTING (10 minutes)
═════════════════════════════════════════════════════════════════

Purpose: Test with mock broker before touching real MT5

Step 1: Run bot with mock broker
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ python main_production.py --mock-broker

Expected behavior:
  ✓ Bot starts without errors
  ✓ Positions open normally
  ✓ Trailing SL updates logged
  ✓ Mock orders submitted successfully

Check logs for:
  [TRAILING_SL_TRACK] Position tracked
  [TRAILING_SL_UPDATE] SL moved
  [TRAILING_SL_CLOSED] Position closed

Checkpoint: No crashes, logs show trailing SL working

Step 2: Simulate price movements
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Mock some price data to test:
  1. Entry at 1.0850
  2. Move to 1.0875 (+25 pips)
  3. Reverse to 1.0840
  4. Check if SL was trailed to ~1.0820

Expected outcome:
  ✓ SL modified after +25 pips
  ✓ Modification logged
  ✓ Position survives reversal
  ✓ No exceptions thrown

Checkpoint: Trailing SL math is correct

Step 3: Check modification history
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ python -c "
from src.trading.dynamic_trailing_sl_manager import DynamicTrailingSLManager
manager = DynamicTrailingSLManager(None, None)
# ...history should show modifications
"

Expected: History shows timestamps, prices, SL changes

Checkpoint: History tracking works

Step 4: Verify no MT5 errors with mock
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Grep logs for errors:
  $ grep -i "error\|exception\|traceback" logs/bot.log

Expected: No trailing SL related errors

Checkpoint: Mock test passes cleanly

═════════════════════════════════════════════════════════════════
PHASE 3 COMPLETE: Mock testing passed ✓
═════════════════════════════════════════════════════════════════
"""


# ============================================================================
# PHASE 4: Paper Trading
# ============================================================================

PHASE_4_PAPER_TRADING = """
═════════════════════════════════════════════════════════════════
PHASE 4: PAPER TRADING (1-3 days)
═════════════════════════════════════════════════════════════════

Purpose: Test with real MT5 on demo account (no money at risk)

Prerequisites:
  ✓ Have demo MT5 account (free from broker)
  ✓ Demo has trading capability
  ✓ MetaTrader5 Python package installed

Step 1: Configure for demo
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

In config.yaml:
  broker:
    account: "your_demo_account"
    password: "demo_password"
    server: "broker-demo-server"
    account_type: "demo"  # <- Important!

Checkpoint: Config connects to demo account

Step 2: Deploy with trailing SL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ python main_production.py

Monitor output:
  ✓ Connects to demo MT5
  ✓ Sends orders successfully
  ✓ Trailing SL modifications execute
  ✓ No MT5 errors (10013, 10015, etc.)

Checkpoint: Bot trades normally with trailing SL

Step 3: Monitor modifications
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Watch logs for:
  [TRAILING_SL_UPDATE] EURUSD | Ticket: 123 | Price: 1.0875 | SL moved

Record:
  ☐ How many modifications per trade?
  ☐ Are they happening at right times?
  ☐ Is profit locking triggering?
  ☐ Any modification failures?

Checkpoint: Trailing SL behavior matches expectations

Step 4: Test spam protection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Create rapid price movements:
  1. Move price up 50 pips in 10 seconds
  2. Watch logs for time throttle messages
  3. Verify modifications aren't rejected

Expected:
  ✓ Time throttle prevents too-frequent updates
  ✓ No "ERR_TRADE_TOO_MANY_REQUESTS"
  ✓ Updates happen at appropriate intervals

Checkpoint: Spam protection works

Step 5: Close positions normally
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Manually close positions in MT5 terminal.

Expected logs:
  [TRAILING_SL_CLOSED] EURUSD | 7 SL modifications | Profit locked: True

Checkpoint: Position untracking works

Step 6: Run for 1-3 days
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

During this period:
  ☐ Monitor for any crashes
  ☐ Watch modification success rate
  ☐ Check for unexpected errors
  ☐ Collect statistics on trailing SL usage

Exit criteria for moving to live:
  ✓ 100% modification success rate
  ✓ No crashes or hangs
  ✓ Trailing SL behavior correct
  ✓ No MT5 error codes
  ✓ Profit locking working as expected

Checkpoint: Demo paper trading passes

═════════════════════════════════════════════════════════════════
PHASE 4 COMPLETE: Paper trading successful ✓
═════════════════════════════════════════════════════════════════
"""


# ============================================================================
# PHASE 5: Live Deployment
# ============================================================================

PHASE_5_LIVE_DEPLOYMENT = """
═════════════════════════════════════════════════════════════════
PHASE 5: LIVE DEPLOYMENT (First week monitoring)
═════════════════════════════════════════════════════════════════

Purpose: Deploy to live trading with close monitoring

⚠ CRITICAL PRECAUTIONS:
  ☐ Reduce position sizing to 50% of normal for first week
  ☐ Have manual kill-switch ready (able to stop bot instantly)
  ☐ Monitor logs in real-time
  ☐ Set alert for any errors
  ☐ Have MT5 terminal open to watch trades
  ☐ Start during liquid market hours
  ☐ Start with one trading pair first

Step 1: Pre-flight check
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before starting:
  ☐ Backup all code and configs
  ☐ Close all demo accounts
  ☐ Verify account has live funds
  ☐ Test kill-switch procedure
  ☐ Verify MT5 connection working
  ☐ Check internet stability

Step 2: Deploy with reduced position size
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

config.yaml:
  risk:
    max_position_size: 0.5%  # Reduced from normal 1-2%
    max_daily_loss: 0.25%     # More conservative
    max_drawdown: 5%

$ python main_production.py

First 30 minutes:
  ☐ Watch logs for normal operation
  ☐ Verify positions opening
  ☐ Check trailing SL modifications happening
  ☐ Monitor account equity

Checkpoint: No issues in first 30 minutes

Step 3: Hour 1-6 monitoring
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Check every 30 minutes:
  ☐ Bot still running
  ☐ No error messages
  ☐ Trailing SL updating normally
  ☐ Account equity stable
  ☐ Order execution working
  ☐ MT5 connection stable

Record metrics:
  - Positions opened: ___
  - SL modifications: ___
  - Modifications successful: ___%
  - Profits/losses: ___
  - Errors encountered: ___

Step 4: First day summary
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

After 24 hours, review:
  ✓ Daily P&L: Positive, neutral, or small loss?
  ✓ Modification count: Reasonable? Too many? Too few?
  ✓ Success rate: Close to 100%?
  ✓ Any error patterns?
  ✓ Any crashes or hangs?

If all good, proceed to Day 2-7.
If issues found, revert to paper trading.

Step 5: First week monitoring
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Daily checklist:
  ☐ Review logs for errors
  ☐ Check modification success rate
  ☐ Monitor P&L
  ☐ Verify MT5 connection stable
  ☐ Confirm trailing SL working

Weekly summary:
  - Total trades: ___
  - Total SL modifications: ___
  - Avg mods per trade: ___
  - Success rate: ___%
  - P&L: ___
  - Win rate: ___%

Step 6: Scale up gradually
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

After first week of success:

Week 1: Position size = 50%, live trading ✓
Week 2: Position size = 75% (if no issues)
Week 3: Position size = 100% (normal)

At each increase, monitor for 3-5 days before next increase.

Step 7: Ongoing monitoring
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Monthly checks:
  ☐ SL modification stats still healthy?
  ☐ Any recurring error patterns?
  ☐ Performance meeting expectations?
  ☐ Config tuning needed?

Quarterly review:
  ☐ Total P&L
  ☐ Win rate with trailing SL
  ☐ Compare vs without trailing SL
  ☐ Adjust config for next quarter

═════════════════════════════════════════════════════════════════
PHASE 5 COMPLETE: Live trading stable ✓
═════════════════════════════════════════════════════════════════
"""


# ============================================================================
# SUCCESS CRITERIA
# ============================================================================

SUCCESS_CRITERIA = """
═════════════════════════════════════════════════════════════════
SUCCESS CRITERIA & SIGN-OFF
═════════════════════════════════════════════════════════════════

Deployment is considered SUCCESSFUL when:

FUNCTIONALITY:
  ✓ Positions are tracked when opened
  ✓ SL modifications occur at expected times
  ✓ Profit locking triggers at configured threshold
  ✓ Time throttle prevents spam (no ERR_TRADE_TOO_MANY_REQUESTS)
  ✓ Positions are untracked when closed

RELIABILITY:
  ✓ Modification success rate > 98%
  ✓ No unhandled exceptions
  ✓ No crashes or hangs
  ✓ MT5 connection stable
  ✓ Logs show expected behavior

PERFORMANCE:
  ✓ SL modifications happen within 100ms
  ✓ CPU usage remains low (<5% for trailing SL)
  ✓ Memory stable (no leaks)
  ✓ No performance degradation over time

PROFITABILITY:
  ✓ Win rate maintained or improved
  ✓ P&L positive or small loss (first week)
  ✓ Average trade duration unchanged
  ✓ Position sizing working correctly

VALIDATION:
  ✓ All verification steps passed
  ✓ Static analysis approved
  ✓ Paper trading 1-3 days successful
  ✓ Live trading first week successful

═════════════════════════════════════════════════════════════════
SIGN-OFF CHECKLIST
═════════════════════════════════════════════════════════════════

I have completed the following steps and confirm:

Phase 1: Verification
  ☐ verify_trailing_sl.py passed all checks
  ☐ STATIC_CODE_ANALYSIS_AUDIT.py approved for integration
  ☐ All files present and readable

Phase 2: Integration
  ☐ Code integrated into core/engine.py
  ☐ No syntax errors
  ☐ All methods working as expected

Phase 3: Mock Testing
  ☐ Mock broker testing passed
  ☐ Trailing SL logic verified
  ☐ No exceptions thrown

Phase 4: Paper Trading
  ☐ Demo account trading 1-3 days
  ☐ Trailing SL working correctly
  ☐ No MT5 errors
  ☐ Modification success rate > 98%

Phase 5: Live Deployment
  ☐ First week live trading complete
  ☐ Reduced position sizing (50%)
  ☐ Daily monitoring passed
  ☐ All success criteria met

DEPLOYMENT APPROVED BY:
  Name: _______________________
  Date: _______________________
  Time: _______________________

═════════════════════════════════════════════════════════════════
"""


# ============================================================================
# ROLLBACK PROCEDURE (Emergency)
# ============================================================================

ROLLBACK_PROCEDURE = """
═════════════════════════════════════════════════════════════════
EMERGENCY ROLLBACK PROCEDURE
═════════════════════════════════════════════════════════════════

If you encounter critical issues, follow this procedure:

IMMEDIATE ACTIONS (< 1 minute):
  1. Stop bot: Ctrl+C in terminal
  2. Check open positions in MT5
  3. If positions are healthy and trailing SL is working,
     wait before taking action

  If positions at risk:
  4. Manually close positions in MT5 terminal
  5. Set bot to demo/paper trading

DIAGNOSTIC (1-5 minutes):
  $ tail -100 logs/bot.log | grep -i "error\|exception"

  Look for:
  - ERR_10013 (Invalid Request) -> Check MT5 structure
  - ERR_10015 (Invalid Price) -> Check rounding
  - ERR_TRADE_TOO_MANY_REQUESTS -> Increase time throttle
  - Other errors -> Review STATIC_CODE_ANALYSIS_AUDIT.py

ROLLBACK STEPS:

Option A: Disable trailing SL only
  1. Edit core/engine.py
  2. Comment out: await self._update_trailing_stops()
  3. Restart bot
  4. Positions will trade normally without trailing SL
  → Data loss: None, positions intact

Option B: Revert to previous version
  1. $ git checkout HEAD~1 core/engine.py
  2. Restart bot
  3. Positions resume normal operation
  → Data loss: None, positions intact

Option C: Full emergency stop
  1. Stop bot immediately
  2. Switch to demo trading only
  3. Close live positions manually
  4. Review logs and code
  5. Investigate root cause
  → Data preservation: All logs saved

RECOVERY PROTOCOL:

After rolling back:
  1. Identify root cause
  2. Fix in code (reference STATIC_CODE_ANALYSIS_AUDIT.py)
  3. Rerun verify_trailing_sl.py
  4. Return to Phase 4 (paper trading)
  5. Run 1-3 days before re-deploying live

═════════════════════════════════════════════════════════════════
"""


if __name__ == "__main__":
    print(PHASE_1_VERIFICATION)
    print("\n")
    print(PHASE_2_INTEGRATION)
    print("\n")
    print(PHASE_3_MOCK_TESTING)
    print("\n")
    print(PHASE_4_PAPER_TRADING)
    print("\n")
    print(PHASE_5_LIVE_DEPLOYMENT)
    print("\n")
    print(SUCCESS_CRITERIA)
    print("\n")
    print(ROLLBACK_PROCEDURE)

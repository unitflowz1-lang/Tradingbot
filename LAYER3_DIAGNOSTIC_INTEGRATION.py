"""
Layer 3 Diagnostic - Quick Integration Template

Copy-paste this into your existing main trading loop to add diagnostics.
Modify paths/variables as needed for your codebase.
"""

# ============================================================================
# OPTION 1: MINIMAL - Add to existing heartbeat (5 lines)
# ============================================================================

"""
Location: Your main trading loop (e.g., main.py, trading_engine.py)

Find where your main loop runs positions and add this:
"""

async def main_trading_loop_with_diagnostics():
    """Example of minimal integration"""
    
    profit_protection_module = ...  # Your PPM instance
    broker = ...  # Your broker instance
    market_data_collector = ...  # Your market data source
    
    cycle_count = 0
    
    while True:
        cycle_count += 1
        
        # ... your existing trading logic ...
        
        # === ADD THIS BLOCK (5 lines) ===
        if cycle_count % 10 == 0:  # Every 10 cycles
            from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
            atr_map = {s: getattr(market_data_collector.get_market_data(s), 'atr', 0.005) 
                       for s in market_data_collector.symbols}
            await run_diagnostic_audit(profit_protection_module, broker, atr_map=atr_map)
        # === END ADD BLOCK ===
        
        await asyncio.sleep(1)


# ============================================================================
# OPTION 2: RECOMMENDED - Create diagnostic manager class
# ============================================================================

"""
Location: Create as src/trading/diagnostic_manager.py or add to existing manager

This is more maintainable for production code.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict

logger = logging.getLogger(__name__)


class DiagnosticManager:
    """Manages Layer 3 diagnostic audits integrated with trading loop"""
    
    def __init__(
        self,
        profit_protection_module,
        broker,
        market_data_collector,
        audit_interval_cycles: int = 10,
        shadow_mode_frequency: int = 1,  # Every cycle in shadow mode
        live_mode_frequency: int = 10,   # Every 10 cycles in live mode
    ):
        self.ppm = profit_protection_module
        self.broker = broker
        self.market_data_collector = market_data_collector
        self.cycle_count = 0
        self.audit_interval_cycles = audit_interval_cycles
        self.shadow_mode_frequency = shadow_mode_frequency
        self.live_mode_frequency = live_mode_frequency
        self.last_audit_time = None
    
    async def pulse(self) -> bool:
        """
        Call this once per trading cycle.
        
        Returns: True if audit was run, False otherwise
        """
        self.cycle_count += 1
        
        # Determine audit frequency based on shadow mode
        frequency = (
            self.shadow_mode_frequency 
            if self.ppm.TIME_DECAY_SHADOW_MODE 
            else self.live_mode_frequency
        )
        
        # Check if it's time to audit
        if self.cycle_count % frequency != 0:
            return False
        
        # Run audit
        try:
            await self._run_diagnostic()
            return True
        except Exception as e:
            logger.error(f"[DIAGNOSTIC_MANAGER_ERROR] Audit failed: {e}", exc_info=True)
            return False
    
    async def _run_diagnostic(self) -> None:
        """Execute diagnostic audit"""
        from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
        
        # Build ATR map from market data
        atr_map = {}
        try:
            for symbol in self.market_data_collector.symbols:
                md = self.market_data_collector.get_market_data(symbol)
                if md and hasattr(md, 'atr'):
                    atr_map[symbol] = float(md.atr)
        except Exception as e:
            logger.warning(f"[DIAGNOSTIC_MANAGER] Failed to build ATR map: {e}")
        
        # Run audit (automatically logs results)
        self.last_audit_time = datetime.now(timezone.utc)
        await run_diagnostic_audit(self.ppm, self.broker, atr_map=atr_map)
    
    def force_audit(self) -> bool:
        """Manually trigger audit immediately"""
        try:
            asyncio.create_task(self._run_diagnostic())
            return True
        except Exception as e:
            logger.error(f"[DIAGNOSTIC_MANAGER] Force audit failed: {e}")
            return False


# Usage in main loop:
async def main_with_diagnostic_manager():
    """Example using DiagnosticManager"""
    
    ppm = ...
    broker = ...
    mdc = ...
    
    # Create manager
    diagnostic_manager = DiagnosticManager(
        ppm, broker, mdc,
        shadow_mode_frequency=1,   # Every cycle in shadow mode
        live_mode_frequency=10,    # Every 10 cycles in live
    )
    
    while True:
        # ... your trading logic ...
        
        # Call diagnostic pulse
        was_audited = await diagnostic_manager.pulse()
        
        await asyncio.sleep(1)


# ============================================================================
# OPTION 3: ADVANCED - With alerts and custom logging
# ============================================================================

"""
Location: Create src/trading/diagnostic_alert_handler.py
"""

import logging
from src.trading.layer3_diagnostic_audit import Layer3DiagnosticAudit, DiagnosticResult
from typing import List

logger = logging.getLogger(__name__)


class DiagnosticAlertHandler:
    """Handle alerts and notifications from Layer 3 diagnostics"""
    
    def __init__(self, ppm, broker, mdc, alert_backends: List = None):
        self.ppm = ppm
        self.broker = broker
        self.mdc = mdc
        self.alert_backends = alert_backends or []  # e.g., [EmailAlert, SlackAlert, ...]
    
    async def run_with_alerts(self) -> None:
        """Run diagnostic and handle alerts"""
        from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
        
        # Run audit
        open_positions = await self.broker.get_open_positions()
        auditor = Layer3DiagnosticAudit(self.ppm)
        
        # Build ATR map
        atr_map = {}
        for symbol in self.mdc.symbols:
            md = self.mdc.get_market_data(symbol)
            if md:
                atr_map[symbol] = getattr(md, 'atr', 0.005)
        
        results = await auditor.run_full_audit(open_positions, atr_map=atr_map)
        auditor.print_audit_report(results)
        
        # Process alerts
        await self._handle_results(results)
    
    async def _handle_results(self, results: List[DiagnosticResult]) -> None:
        """Process results and send alerts"""
        
        failures = [r for r in results if r.status == "FAIL"]
        rotations = [r for r in results if r.marked_for_auto_rotation]
        errors = [r for r in results if r.status == "ERROR"]
        passes = [r for r in results if r.status == "PASS"]
        
        # Alert on failures
        if failures:
            message = (
                f"[LAYER3_ALERT] {len(failures)} constraint violation(s):\n" +
                "\n".join([
                    f"  {r.symbol} #{r.position_id}: {r.reason}"
                    for r in failures
                ])
            )
            logger.critical(message)
            await self._send_alert("LAYER3_CONSTRAINT_FAIL", message)
        
        # Alert on rotations
        if rotations:
            message = (
                f"[LAYER3_ALERT] {len(rotations)} position(s) pending auto-rotation:\n" +
                "\n".join([f"  {r.symbol} #{r.position_id}" for r in rotations])
            )
            logger.warning(message)
            await self._send_alert("LAYER3_ROTATION_PENDING", message)
        
        # Alert on errors
        if errors:
            message = (
                f"[LAYER3_ERROR] {len(errors)} audit error(s):\n" +
                "\n".join([f"  {r.symbol} #{r.position_id}: {r.reason}" for r in errors])
            )
            logger.error(message)
            await self._send_alert("LAYER3_AUDIT_ERROR", message)
        
        # Log summary
        logger.info(
            f"[LAYER3_SUMMARY] PASS={len(passes)} | FAIL={len(failures)} | "
            f"ROTATION={len(rotations)} | ERROR={len(errors)}"
        )
    
    async def _send_alert(self, alert_type: str, message: str) -> None:
        """Send alert to all configured backends"""
        for backend in self.alert_backends:
            try:
                await backend.send(alert_type, message)
            except Exception as e:
                logger.error(f"Failed to send {alert_type} via {backend.__class__.__name__}: {e}")


# ============================================================================
# OPTION 4: MANUAL TRIGGER VIA CLI/COMMAND
# ============================================================================

"""
Add this to your command handler/CLI interface
"""

async def handle_audit_command(ppm, broker, args=None):
    """Handler for 'audit' or 'diagnose' command"""
    from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
    
    print("\n" + "="*80)
    print("[CLI] Initiating Layer 3 Diagnostic Audit")
    print("[CLI] This is read-only - no trades will be executed")
    print("="*80 + "\n")
    
    results = await run_diagnostic_audit(ppm, broker)
    
    # Print summary
    pass_count = sum(1 for r in results if r.status == "PASS")
    fail_count = sum(1 for r in results if r.status == "FAIL")
    print(f"\n[CLI] Audit Summary: {pass_count} PASS, {fail_count} FAIL")
    print("[CLI] Full report logged to application logger\n")
    
    return results


# ============================================================================
# INTEGRATION STEPS
# ============================================================================

"""
1. Copy layer3_diagnostic_audit.py to src/trading/

2. Choose integration method:
   - Option 1: Add 5 lines to existing loop (quick test)
   - Option 2: Create DiagnosticManager class (recommended for production)
   - Option 3: Add alerts/notifications (advanced)
   - Option 4: Add CLI command (manual triggering)

3. Add imports to your main module:
   from src.trading.diagnostic_manager import DiagnosticManager

4. In your main trading loop initialization:
   diagnostic_manager = DiagnosticManager(
       profit_protection_module, broker, market_data_collector,
       shadow_mode_frequency=1,
       live_mode_frequency=10
   )

5. In your main loop cycle:
   was_audited = await diagnostic_manager.pulse()

6. Start bot and watch logs for [DIAGNOSTIC_PASS], [DIAGNOSTIC_FAIL], etc.

7. After 30 minutes of clean PASS results in shadow mode, consider exiting shadow mode

EXPECTED LOG OUTPUT
===================

[LAYER3_DIAGNOSTIC_AUDIT] Time: 2026-04-16 14:35:22 UTC
[LAYER3_DIAGNOSTIC_AUDIT] Shadow Mode: True
[LAYER3_DIAGNOSTIC_AUDIT] Positions Audited: 3
============================================================
[LAYER3_AUDIT_SUMMARY] PASS=2 | FAIL=1 | WARNING=0 | INFO=0 | ERROR=0 | PENDING_ROTATION=0
============================================================
[DIAGNOSTIC_PASS] GBP/USD #56273738626 (LONG)
  Bars Since Entry: 42
  Current SL: 1.2450
  Proposed SL: 1.2480
    → Delta: 30.0 pips
  Constraint Check: PASS
  Reason: ... (validation details)

[DIAGNOSTIC_FAIL] USD/CHF #56273740691 (SHORT)
  ...

[LAYER3_AUDIT_COMPLETE] Report timestamp: 2026-04-16 14:35:22 UTC

TROUBLESHOOTING
===============

Q: No output showing?
A: Check if Layer 3 is enabled (time_decay_enabled = True)
   Check if positions exist in ppm.position_states

Q: All FAIL with "No decay proposal"?
A: Positions not stagnant yet - Layer 3 logic not triggered
   Normal in first 15-20 bars per position

Q: "Too close to current price" fails?
A: Proposed SL less than 3 pips from current market price
   May resolve as position moves or bars increase

Q: Shadow mode showing but no actual SL changes?
A: Correct - shadow mode logs proposals without executing
   Exit shadow mode to actually apply SL changes (set TIME_DECAY_SHADOW_MODE=False)

Q: Performance impact?
A: Negligible - diagnostic runs only on scheduled interval
   Read-only, no MT5 modifications
   In shadow mode: can run every cycle (minimal overhead)
"""

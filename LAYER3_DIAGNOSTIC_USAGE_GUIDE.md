"""
Layer 3 Diagnostic Audit - Usage Guide & Integration Examples
==============================================================

This guide shows how to integrate and use the Layer3DiagnosticAudit
in various scenarios.
"""

# ============================================================================
# USAGE SCENARIO 1: Manual Trigger in Main Trading Loop
# ============================================================================

"""
Call the diagnostic function periodically from your main trading loop.
This is useful for monitoring and logging Layer 3 behavior.

Example in your main.py or trading_engine.py:
"""

import asyncio
from src.trading.layer3_diagnostic_audit import run_diagnostic_audit, Layer3DiagnosticAudit

# In your main trading loop:
async def trading_heartbeat(ppm, broker, market_data_collector):
    """Main trading loop with periodic diagnostics"""
    
    audit_counter = 0
    AUDIT_EVERY_N_CYCLES = 10  # Run audit every 10 cycles (adjust as needed)
    
    while True:
        # ... your normal trading logic ...
        
        # Every N cycles, run diagnostic audit
        audit_counter += 1
        if audit_counter >= AUDIT_EVERY_N_CYCLES:
            audit_counter = 0
            
            # Build ATR map from your market data
            atr_map = {}
            for symbol in market_data_collector.symbols:
                md = market_data_collector.get_market_data(symbol)
                if md and hasattr(md, 'atr'):
                    atr_map[symbol] = md.atr
            
            # Run diagnostic
            results = await run_diagnostic_audit(ppm, broker, atr_map=atr_map)
            
            # Optional: Store results for analysis
            # await store_audit_results(results)
        
        await asyncio.sleep(1)  # Heartbeat interval


# ============================================================================
# USAGE SCENARIO 2: Manual Trigger via Console/Command
# ============================================================================

"""
Trigger diagnostic from a management console or CLI command.
"""

async def cli_run_audit_command(ppm, broker):
    """CLI command handler for manual audit trigger"""
    from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
    
    print("\n[CLI] Initiating Layer 3 Diagnostic Audit...")
    print("[CLI] This is read-only. No trades will be executed.\n")
    
    results = await run_diagnostic_audit(ppm, broker)
    
    print("\n[CLI] Audit complete. Check logs for full report.")
    return results


# ============================================================================
# USAGE SCENARIO 3: Integration with Existing Heartbeat
# ============================================================================

"""
If you already have a heartbeat pulse system, integrate diagnostic there.
"""

class TradingHeartbeat:
    """Existing heartbeat system with Layer 3 diagnostics"""
    
    def __init__(self, ppm, broker, market_data_collector):
        self.ppm = ppm
        self.broker = broker
        self.market_data_collector = market_data_collector
        self.audit_interval_seconds = 60  # Run audit every 60 seconds
        self.last_audit_time = None
    
    async def pulse(self):
        """Run each heartbeat cycle"""
        
        # ... your existing heartbeat logic ...
        
        # Check if it's time for diagnostic
        now = datetime.now(timezone.utc)
        if (self.last_audit_time is None or 
            (now - self.last_audit_time).total_seconds() >= self.audit_interval_seconds):
            
            self.last_audit_time = now
            await self._run_diagnostic()
    
    async def _run_diagnostic(self):
        """Run diagnostic audit"""
        from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
        
        try:
            # Build ATR map
            atr_map = {}
            for symbol in self.market_data_collector.symbols:
                md = self.market_data_collector.get_market_data(symbol)
                if md and hasattr(md, 'atr'):
                    atr_map[symbol] = md.atr
            
            # Run audit (automatically logs results)
            await run_diagnostic_audit(self.ppm, self.broker, atr_map=atr_map)
        
        except Exception as e:
            logger.error(f"[HEARTBEAT_AUDIT_ERROR] Diagnostic failed: {e}", exc_info=True)


# ============================================================================
# USAGE SCENARIO 4: Custom Reporting with Results Processing
# ============================================================================

"""
Process audit results programmatically for custom reporting, alerts, etc.
"""

async def advanced_audit_with_alerts(ppm, broker, alert_handler):
    """Run audit and trigger alerts on issues"""
    from src.trading.layer3_diagnostic_audit import run_diagnostic_audit, Layer3DiagnosticAudit
    
    auditor = Layer3DiagnosticAudit(ppm)
    open_positions = await broker.get_open_positions()
    results = await auditor.run_full_audit(open_positions)
    
    # Process results
    failures = [r for r in results if r.status == "FAIL"]
    rotations = [r for r in results if r.marked_for_auto_rotation]
    errors = [r for r in results if r.status == "ERROR"]
    
    # Send alerts if needed
    if failures:
        await alert_handler.send_alert(
            f"[LAYER3_ALERT] {len(failures)} position(s) failed constraint validation:\n" +
            "\n".join([f"  {r.symbol} #{r.position_id}: {r.reason}" for r in failures])
        )
    
    if rotations:
        await alert_handler.send_alert(
            f"[LAYER3_ALERT] {len(rotations)} position(s) pending auto-rotation:\n" +
            "\n".join([f"  {r.symbol} #{r.position_id}" for r in rotations])
        )
    
    if errors:
        await alert_handler.send_alert(
            f"[LAYER3_ERROR] {len(errors)} error(s) during audit:\n" +
            "\n".join([f"  {r.symbol} #{r.position_id}: {r.reason}" for r in errors])
        )
    
    # Print report
    auditor.print_audit_report(results)
    
    return results


# ============================================================================
# USAGE SCENARIO 5: Scheduled Audit (e.g., Every Market Session)
# ============================================================================

"""
Run audit at specific times (e.g., start of day, end of trading session).
"""

async def scheduled_audit_task(ppm, broker, schedule_times):
    """Background task for scheduled audits"""
    from datetime import time
    from src.trading.layer3_diagnostic_audit import run_diagnostic_audit
    
    while True:
        now = datetime.now(timezone.utc)
        current_time = now.time()
        
        # Check if current time matches any scheduled time
        for scheduled_time in schedule_times:
            # scheduled_time format: "09:00" (UTC)
            hour, minute = map(int, scheduled_time.split(':'))
            
            if (current_time.hour == hour and 
                current_time.minute == minute and
                current_time.second < 5):  # Within first 5 seconds of minute
                
                logger.info(f"[SCHEDULED_AUDIT] Running audit at {scheduled_time} UTC")
                await run_diagnostic_audit(ppm, broker)
                
                # Wait to avoid running twice in same minute
                await asyncio.sleep(60)
        
        await asyncio.sleep(10)  # Check every 10 seconds


# ============================================================================
# USAGE SCENARIO 6: Direct Instantiation for Custom Diagnostics
# ============================================================================

"""
Create auditor instance directly for custom diagnostic logic.
"""

async def custom_diagnostic_logic(ppm, position):
    """Run custom diagnostics on a single position"""
    from src.trading.layer3_diagnostic_audit import Layer3DiagnosticAudit
    
    auditor = Layer3DiagnosticAudit(ppm)
    
    # Run diagnostic on single position
    result = await auditor.check_single_position(position, atr=0.005)
    
    # Custom processing
    print(f"\n{'='*80}")
    print(f"Position: {result.symbol} #{result.position_id}")
    print(f"Status: {result.status}")
    print(f"Bars Since Entry: {result.bars_since_entry}")
    print(f"Current SL: {result.current_sl:.5f}")
    print(f"Proposed SL: {result.proposed_sl if result.proposed_sl else 'None'}")
    print(f"Spread: {result.spread_pips:.1f} pips")
    print(f"Reason: {result.reason}")
    
    if result.marked_for_auto_rotation:
        print(f"⚠️  ROTATION_PENDING: Yes")
    
    print(f"{'='*80}\n")
    
    return result


# ============================================================================
# OUTPUT EXAMPLES
# ============================================================================

"""
Here's what the diagnostic output looks like:

[LAYER3_DIAGNOSTIC_AUDIT] Time: 2026-04-16 14:35:22 UTC
[LAYER3_DIAGNOSTIC_AUDIT] Shadow Mode: True
[LAYER3_DIAGNOSTIC_AUDIT] Positions Audited: 3
========================================================

[LAYER3_AUDIT_SUMMARY] PASS=2 | FAIL=1 | WARNING=0 | INFO=0 | ERROR=0 | PENDING_ROTATION=0

========================================================

[DIAGNOSTIC_PASS] GBP/USD #56273738626 (LONG)
  Bars Since Entry: 42
  Current SL: 1.2450
  Proposed SL: 1.2480
    → Delta: 30.0 pips
  ATR: 0.005000 | Spread: 1.2 pips
  Constraint Check: PASS
  Reason: Significant change: 30.0 pips | SL below current price (valid for LONG) | Adequate distance from price: 45.2 pips | Respects trade_stops_level (45.2 >= 3.0) | SL outside spread (< bid 1.2500)

[DIAGNOSTIC_FAIL] USD/CHF #56273740691 (SHORT)
  Bars Since Entry: 18
  Current SL: 0.8850
  Proposed SL: 0.8820
    → Delta: 30.0 pips
  ATR: 0.005100 | Spread: 1.1 pips
  Constraint Check: FAIL
  Reason: SL inside spread (<= ask 0.8821)

[DIAGNOSTIC_PASS] EUR/USD #56273740580 (LONG)
  Bars Since Entry: 156
  Proposed SL: None
  ATR: 0.004800 | Spread: 0.9 pips
  Constraint Check: INFO
  Reason: No decay proposal (position not stagnant yet)
  ⚠️  [ROTATION_PENDING] Position marked for auto-rotation

========================================================

[LAYER3_AUDIT_COMPLETE] Report timestamp: 2026-04-16 14:35:22 UTC


INTERPRETATION GUIDE
====================

[DIAGNOSTIC_PASS]:
- Position constraints are valid
- Proposed SL (if any) respects all broker limits and spreads
- Safe to deploy in live mode if constraints pass

[DIAGNOSTIC_FAIL]:
- Position has constraint violations
- Most common cause: Proposed SL inside current spread
- Action: Monitor and investigate (may auto-resolve if spread tightens)

[DIAGNOSTIC_WARNING]:
- Position is tracked but not yet in decay zone
- Layer 3 logic not triggered yet (not enough bars or not stagnant)

[ROTATION_PENDING]:
- Position marked for auto-rotation by Layer 3
- Will be harvested/rotated when appropriate conditions met
- Check marked_for_auto_rotation flag for integration

[DIAGNOSTIC_ERROR]:
- Audit encountered issue (MT5 tick fetch failed, etc.)
- Usually transient; will resolve on next audit cycle
"""

# ============================================================================
# INTEGRATION CHECKLIST
# ============================================================================

"""
✓ Import the diagnostic module in your main trading loop
✓ Choose audit frequency (every N cycles, time-based, or manual)
✓ Build ATR map from your market data collector
✓ Call run_diagnostic_audit() or instantiate Layer3DiagnosticAudit
✓ Monitor [DIAGNOSTIC_PASS], [DIAGNOSTIC_FAIL], [ROTATION_PENDING] tags
✓ Set up alerts for FAIL and ROTATION_PENDING conditions (optional)
✓ Review logs regularly to catch constraint issues early
✓ Gradually increase audit frequency as you gain confidence in Layer 3

SHADOW MODE BEST PRACTICES
===========================

During Shadow Mode (recommended first 30 minutes):
1. Run audit every cycle (no performance penalty in shadow mode)
2. Log all [DIAGNOSTIC_PASS] positions to verify SL proposals are reasonable
3. Look for patterns in [DIAGNOSTIC_FAIL] (spread too wide, wrong direction, etc.)
4. If all positions show [DIAGNOSTIC_PASS], confidence increases
5. After 30 minutes of clean passes, consider exiting shadow mode

After Exiting Shadow Mode:
1. Run audit every N cycles (N=5-10) to avoid log spam
2. Treat [DIAGNOSTIC_FAIL] as signal to investigate
3. Track [ROTATION_PENDING] positions for manual monitoring
4. Alert if error rate climbs (indicates MT5 connectivity issues)
"""

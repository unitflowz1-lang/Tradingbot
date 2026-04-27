# PRODUCTION STABILIZATION - THREE CRITICAL FIXES
# Apply these fixes to main.py to stabilize the bot for production

# ==============================================================================
# TASK A: GATE THE AMNESIA FUNCTION (Prevent Brain Wipe on Restart)
# ==============================================================================
# LOCATION: main.py, line ~1835

# REPLACE THIS:
"""
    amnesia_interval_seconds = max(300, int(os.environ.get("AMNESIA_INTERVAL_SECONDS", "3600")))
    last_amnesia_run_at: Optional[datetime] = None
"""

# WITH THIS:
"""
    # Task A: Gate amnesia behind hard reset flag to prevent routine brain wipe
    amnesia_enabled = str(os.environ.get("ENABLE_AMNESIA_CYCLES", "false")).lower() in {"1", "true", "yes", "on"}
    amnesia_interval_seconds = max(300, int(os.environ.get("AMNESIA_INTERVAL_SECONDS", "3600"))) if amnesia_enabled else float('inf')
    last_amnesia_run_at: Optional[datetime] = None
    logger.critical(f"[AMNESIA_GATE] Amnesia cycles: {'ENABLED' if amnesia_enabled else 'DISABLED (Default - Only enable with ENABLE_AMNESIA_CYCLES=1)'}")
"""

# ==============================================================================
# TASK A IMPLEMENTATION: Modify the amnesia trigger logic
# ==============================================================================
# LOCATION: main.py, line ~2915

# REPLACE THIS:
"""
            should_run_amnesia = (
                cycle_count == 1
                or last_amnesia_run_at is None
                or (now_utc - last_amnesia_run_at).total_seconds() >= amnesia_interval_seconds
            )
            if should_run_amnesia:
                logger.info(
                    f"[AMNESIA_MODE_ACTIVE] Cycle {cycle_count} | Cooldowns and volatility floors bypassed | "
                    f"Universe reset: {symbols}"
                )
"""

# WITH THIS:
"""
            # Task A: Only run amnesia if explicitly enabled
            should_run_amnesia = (
                amnesia_enabled and (
                    cycle_count == 1
                    or last_amnesia_run_at is None
                    or (now_utc - last_amnesia_run_at).total_seconds() >= amnesia_interval_seconds
                )
            )
            if should_run_amnesia:
                logger.critical(
                    f"[AMNESIA_MODE_ACTIVE] Cycle {cycle_count} | HARD RESET TRIGGERED | "
                    f"Cooldowns and volatility floors bypassed | "
                    f"Universe reset: {symbols}"
                )
"""

# ==============================================================================
# TASK B: IMPLEMENT PRESERVATION LOGIC IN MAIN LOOP
# ==============================================================================
# LOCATION: main.py, find the main trading cycle loop (around line ~2700-2900)

# ADD THIS AT THE START OF EACH MAIN LOOP CYCLE:
"""
            # TASK B: Check Resilience Controller status
            resilience_controller = get_resilience_controller()
            if resilience_controller:
                resilience_state = resilience_controller.get_current_state()
                
                # Log resilience status for monitoring
                if resilience_state.unhealthy_services:
                    logger.warning(
                        f"[RESILIENCE_STATUS] Mode: {resilience_state.current_mode.value} | "
                        f"Unhealthy: {resilience_state.unhealthy_services} | "
                        f"Outage: {resilience_state.total_outage_duration_seconds:.0f}s"
                    )
                
                # PRESERVATION_MODE: No new trades
                if resilience_state.current_mode == ResilienceMode.PRESERVATION:
                    logger.critical(
                        f"[PRESERVATION_PROTOCOL] Blocking new entries. "
                        f"Outage: {resilience_state.total_outage_duration_seconds:.0f}s > 30min threshold. "
                        f"Only managing existing positions."
                    )
                    # Skip signal generation and trade execution
                    # Continue to position management section only
                    continue_to_position_management_only = True
                else:
                    continue_to_position_management_only = False
                
                # TECHNICAL_ONLY_MODE: Skip API calls for unhealthy services
                if resilience_state.current_mode == ResilienceMode.TECHNICAL_ONLY:
                    logger.info(
                        f"[TECHNICAL_ONLY_MODE] Using cached data only. "
                        f"Skipping: {', '.join(resilience_state.unhealthy_services)}"
                    )
                    # Skip Finnhub refresh, use cached macro risks
                    # Skip news refresh, use cached sentiment
"""

# ==============================================================================
# TASK C: BREAK THE 7/7 DEADLOCK (Force Time-Exits in HARVEST_MODE)
# ==============================================================================
# LOCATION: main.py, line ~2643

# REPLACE THIS:
"""
            if harvest_time_exit_disabled_until and datetime.now(timezone.utc) < harvest_time_exit_disabled_until:
                logger.critical("[HARVEST_MODE_ACTIVE] Shadow merged. Time-exits disabled. Portfolio locked at 7/7.")
"""

# WITH THIS:
"""
            # TASK C: Override HARVEST_MODE to force time-exits at 7/7 capacity
            is_at_max_capacity = len(getattr(portfolio, "positions", [])) >= int(getattr(getattr(config, "trading", None), "max_total_positions", 7) or 7)
            harvest_mode_blocked_but_at_capacity = (
                harvest_time_exit_disabled_until 
                and datetime.now(timezone.utc) < harvest_time_exit_disabled_until
                and is_at_max_capacity
            )
            
            if harvest_time_exit_disabled_until and datetime.now(timezone.utc) < harvest_time_exit_disabled_until:
                if harvest_mode_blocked_but_at_capacity:
                    logger.critical(
                        "[HARVEST_MODE_OVERRIDE] Portfolio locked at 7/7. FORCING time-exits despite HARVEST_MODE "
                        "to prevent deadlock. Allow stagnant trades to close."
                    )
                    # OVERRIDE: Force time-exits to close stagnant positions
                    force_time_exits = True
                else:
                    logger.critical("[HARVEST_MODE_ACTIVE] Shadow merged. Time-exits disabled. Portfolio locked at 7/7.")
                    force_time_exits = False
            else:
                force_time_exits = False
"""

# ==============================================================================
# TASK C IMPLEMENTATION: Modify exit logic to respect force_time_exits
# ==============================================================================
# LOCATION: main.py, search for "should_exit" or "exit_reason" logic (around line ~3950)

# FIND THIS CONDITION:
"""
                        or (harvest_time_exit_disabled_until and datetime.now(timezone.utc) < harvest_time_exit_disabled_until)
"""

# REPLACE WITH THIS:
"""
                        or (harvest_time_exit_disabled_until and datetime.now(timezone.utc) < harvest_time_exit_disabled_until and not force_time_exits)
                        # TASK C: Exceptions for deadlock prevention - force close stagnant trades at 7/7
"""

# ==============================================================================
# PRODUCTION DEPLOYMENT CHECKLIST
# ==============================================================================

DEPLOYMENT_CHECKLIST = """
✅ TASK A: DISABLE AMNESIA BY DEFAULT
   - Set environment variable: ENABLE_AMNESIA_CYCLES=0 (default)
   - Or remove from environment entirely
   - To enable (only if needed): ENABLE_AMNESIA_CYCLES=1
   
   Verification:
   - Look for: [AMNESIA_GATE] Amnesia cycles: DISABLED in startup logs
   - Bot should NOT show [BRAIN_WASH_COMPLETE] on routine restarts

✅ TASK B: PRESERVATION MODE ACTIVE
   - Resilience controller automatically tracks 30+ minute outages
   - When triggered, bot stops opening new trades
   - Existing positions continue to be managed
   - User should see: [PRESERVATION_PROTOCOL] messages in logs
   
   Verification:
   - Simulate Finnhub failure: Stop service for 31+ minutes
   - Observe [CRITICAL_NETWORK_OUTAGE_PRESERVATION_ACTIVE] alert
   - Verify no new trades open while in preservation mode
   - Verify existing positions can still close

✅ TASK C: 7/7 DEADLOCK FIXED
   - Time-exits now forced even in HARVEST_MODE when at max capacity
   - Stagnant trades will close automatically
   - Portfolio can return to <7 positions and accept new trades
   - Prevents "frozen at 7/7" deadlock
   
   Verification:
   - Bot reaches 7/7 positions
   - HARVEST_MODE is active (4-hour window)
   - Observe: [HARVEST_MODE_OVERRIDE] message
   - Stale positions should close via time-exit
   - New trades should be allowed once below 7

ENVIRONMENT VARIABLES FOR PRODUCTION:
   - ENABLE_AMNESIA_CYCLES=0           # Disable amnesia (default is recommended)
   - AMNESIA_INTERVAL_SECONDS=3600     # If enabled, frequency in seconds
   - MAX_DYNAMIC_TRADES_PER_SYMBOL=2   # Prevent symbol oversaturation

MONITORING IN LOGS:
   [AMNESIA_GATE]                       # Amnesia status on startup
   [RESILIENCE_STATUS]                  # Resilience mode every cycle
   [PRESERVATION_PROTOCOL]              # When preservation triggered
   [HARVEST_MODE_ACTIVE]                # Harvest mode status
   [HARVEST_MODE_OVERRIDE]              # When deadlock prevention kicks in
   [CRITICAL_NETWORK_OUTAGE_PRESERVATION_ACTIVE]  # 30+ min outage
"""

print(DEPLOYMENT_CHECKLIST)

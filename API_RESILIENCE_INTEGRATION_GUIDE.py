"""
Integration Guide: API Resilience Controller + FinnhubMacroManager
==========================================

This guide shows how to integrate the APIResilienceController into your trading bot
to achieve 100% uptime despite external API failures.

ARCHITECTURE OVERVIEW:
======================

Before:
    [Main Loop]
        └─> FinnhubMacroManager
            └─> Finnhub API (can fail)
        └─> Position Sizing
        └─> Trade Execution

After:
    [Main Loop]
        └─> APIResilienceController
            ├─> FinnhubMacroManager (with automatic failover)
            ├─> TECHNICAL_ONLY_MODE (when API fails)
            ├─> Position Sizing (auto-reduced 50%)
            └─> Trade Execution (flagged as TECH_ONLY_ADMITTED)


STEP 1: Initialize in Main Bot
================================

In main_production.py or your entry point:

    from src.analysis.api_resilience_controller import create_resilience_controller
    from src.analysis.finnhub_macro_manager import create_finnhub_manager

    async def initialize_bot():
        # ... existing initialization code ...

        # 1. Create Finnhub macro manager
        finnhub_manager = create_finnhub_manager(
            api_key="your_finnhub_key",
            symbols=["EUR/USD", "GBP/USD", "USD/JPY"],
            macro_risk_cache=macro_risk_cache,  # from llm_macro_monitor
        )
        await finnhub_manager.start()

        # 2. Create resilience controller (wraps finnhub_manager)
        resilience_controller = create_resilience_controller(
            finnhub_manager=finnhub_manager,
            risk_manager=self.risk_manager,  # from TradingEngine
        )

        # Store for use in main loop
        self.resilience_controller = resilience_controller


STEP 2: Use in Main Trading Loop
==================================

In TradingEngine.run() or main loop:

    async def run_main_loop(self):
        while self.state.is_running:
            for symbol in self.config.data.pairs:
                try:
                    # 1. Get macro data WITH automatic failover
                    macro_data = await self.resilience_controller.get_macro_data(symbol)

                    # Check operating mode
                    if macro_data["status"] == "FALLBACK":
                        logger.info(f"Using fallback data for {symbol}: {macro_data['fallback_reason']}")

                    # 2. Generate trading signals (using both macro + technical)
                    signals = self.strategy_manager.generate_signals(
                        market_data=self.market_data[symbol],
                        macro_data=macro_data,
                    )

                    # 3. Calculate base position size
                    base_position_size = 1.0  # Your normal size

                    # 4. Get ADJUSTED size + trade flags
                    adjusted_size, trade_flags = await self.resilience_controller.get_adjusted_position_size(
                        symbol=symbol,
                        base_size=base_position_size,
                    )

                    # 5. Use adjusted size for order
                    if signals.signal == "BUY":
                        order_id = await self.execution_engine.submit_market_order(
                            symbol=symbol,
                            direction="BUY",
                            quantity=adjusted_size,  # <- ADJUSTED by resilience controller
                            comment=trade_flags.trade_comment,  # -> Flags like "[MODE: TECH_ONLY_ADMITTED]"
                        )
                        logger.info(
                            f"Order {order_id} | {trade_flags.trade_comment} | "
                            f"Size: {base_position_size} -> {adjusted_size}"
                        )

                    # 6. Log trade flags for audit trail
                    all_flags = self.resilience_controller.get_trade_flags()

                except Exception as e:
                    logger.error(f"Error in loop for {symbol}: {e}")


STEP 3: Monitor Health & Status
================================

Periodically check health status:

    async def monitor_health(self):
        while True:
            for symbol in self.config.data.pairs:
                health = self.resilience_controller.get_health_status(symbol)

                if health:
                    logger.info(
                        f"[HEALTH] {symbol} | Mode: {health['mode']} | "
                        f"Failures: {health['consecutive_failures']} | "
                        f"Next retry: {health['next_retry_time']}"
                    )

                    # Alert if in PRESERVATION mode
                    if health['mode'] == 'PRESERVATION':
                        logger.critical(
                            f"[DEGRADATION_ALERT] {symbol} in PRESERVATION mode | "
                            f"New positions halted, only managing active trades"
                        )

            await asyncio.sleep(60)  # Check every minute


STEP 4: Shutdown & Cleanup
============================

In shutdown:

    async def shutdown(self):
        # Stop resilience monitoring
        if hasattr(self, 'resilience_controller'):
            health_summary = {}
            for symbol in self.config.data.pairs:
                health_summary[symbol] = self.resilience_controller.get_health_status(symbol)

            logger.info(f"Resilience Status at Shutdown:\n{health_summary}")

        # Stop macro manager
        if self.finnhub_manager:
            await self.finnhub_manager.stop()

        # Continue normal shutdown...


EXPECTED BEHAVIOR
=================

Scenario 1: Normal Operation
----------------------------
Finnhub API ✓ (HTTP 200, <1s)
→ Mode: NORMAL
→ Position Size: 100%
→ Trade Flag: "[MODE: NORMAL]"


Scenario 2: API Timeout (>5s)
-----------------------------
Finnhub API ✗ (Timeout)
→ Failure count: 1
→ Mode: TECHNICAL_ONLY
→ Position Size: 50% (reduced)
→ Trade Flag: "[MODE: TECH_ONLY_ADMITTED] 50% size reduction, macro data unavailable"
→ Backoff: 1 minute (uses exponential: 1m → 5m → 15m → 30m)
→ Indicators used: RSI, ADX, Price Action, ATR only


Scenario 3: Long Outage (>30 min)
---------------------------------
Finnhub API ✗ (Down for 45 minutes)
→ Failure count: ≥6
→ Mode: PRESERVATION
→ Position Size: 30% (even more reduced)
→ Trade Action: NO NEW LONG-TERM POSITIONS (only active trade management)
→ Alert: "[SYSTEM_DEGRADATION_ALERT]"
→ Backoff: 30 minute intervals


Scenario 4: Recovery
-------------------
Finnhub API ✓ (Returns HTTP 200 after downtime)
→ DATA_VALIDATION_PASS initiated
→ Compare current risk_score with last known good state
→ If consistent → Mode: NORMAL, reset backoff counter
→ If drift detected → Remain cautious, log warning


CODE FLOW DIAGRAM
=================

┌─────────────────────────────────────────┐
│  Main Trading Loop                      │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│  APIResilienceController                │
│  .get_macro_data(symbol)                │
└──────────┬────────────────┬─────────────┘
           │                │
           ▼                ▼
      ✓ Normal       ✗ Timeout/Error
         mode            detected
           │                │
           ▼                ▼
    ┌────────────────┐  ┌──────────────────────┐
    │ Mode: NORMAL   │  │ Trigger TECHNICAL_   │
    │ Size: 100%     │  │ ONLY_MODE            │
    │ Freshness: ✓   │  │ - Size reduced 50%   │
    └────────────────┘  │ - Backoff wait       │
                        │ - Flag trade         │
                        └──────────────────────┘
                               │
                        Retry after backoff
                               │
                               ▼
                        ✓ Reconnected?
                         /          \
                        ▼            ▼
                    Yes          No (< 30m)
                     │            │
                     ▼            ▼
              DATA_VALIDATION   Exponential
              PASS initiated    backoff
                     │          continues
                     ▼
              Mode: NORMAL
              resumed


TESTING
=======

Test 1: Simulate API Timeout
----------------------------
Mock the Finnhub manager to raise TimeoutError:

    def test_api_timeout_triggers_tech_only():
        resilience = APIResilienceController(finnhub_manager, risk_manager)

        # Mock timeout
        with patch.object(finnhub_manager, 'get_latest_snapshot', side_effect=TimeoutError):
            macro_data = await resilience.get_macro_data("EUR/USD")

            assert macro_data["status"] == "FALLBACK"
            assert macro_data["mode"] == "TECHNICAL_ONLY"

            adjusted_size, flags = await resilience.get_adjusted_position_size("EUR/USD", 1.0)
            assert adjusted_size == 0.5  # 50% reduction
            assert flags.is_technical_only == True


Test 2: Verify Exponential Backoff
-----------------------------------
Simulate 5+ consecutive failures:

    def test_exponential_backoff():
        for i in range(6):
            await resilience.get_macro_data("EUR/USD")  # Simulate failure

        health = resilience.get_health_status("EUR/USD")
        assert health["mode"] == "PRESERVATION"  # After 6 failures


Test 3: Recovery & Data Validation
-----------------------------------
Simulate recovery after failures:

    def test_recovery_triggers_validation():
        # Trigger failures
        for i in range(3):
            await resilience.get_macro_data("EUR/USD")  # Fail 3 times

        # Recovery
        # Mock successful response
        macro_data = await resilience.get_macro_data("EUR/USD")

        # Should be NORMAL again
        health = resilience.get_health_status("EUR/USD")
        assert health["mode"] == "NORMAL"


AUDIT LOGGING
=============

All trades during degraded operation are flagged in the order comment:

    [MODE: TECH_ONLY_ADMITTED] 50% size reduction, macro data unavailable

This allows post-trading analysis to identify:
1. Which trades were executed during API failures
2. What position sizing was used
3. How long the system was in degraded mode


TROUBLESHOOTING
===============

Issue: Stuck in TECHNICAL_ONLY_MODE even after recovery
-------
Check that:
1. Finnhub API returns HTTP 200 (not 429, 401)
2. DATA_VALIDATION_PASS completes without exceptions
3. Check logs for "DATA_VALIDATION_PASS" messages

Issue: Position sizing not reducing
-------
Check that:
1. get_adjusted_position_size() is being called (not just base size)
2. Resilience controller is properly initialized
3. Backoff wait has completed before next retry

Issue: Too many backoff retries
-------
Reduce BACKOFF_SCHEDULE values in api_resilience_controller.py:
    BACKOFF_SCHEDULE = [30, 120, 300, 600]  # Shorter waits


SUMMARY
=======

✓ 100% uptime: Trading continues despite API failures
✓ Safe fallback: Automatic switch to technical-only indicators
✓ Reduced risk: 50% position sizing during degraded operation
✓ Smart recovery: Data validation on reconnection
✓ Memory preservation: No state loss during failures
✓ Audit trail: All trades flagged for analysis
"""

print(__doc__)

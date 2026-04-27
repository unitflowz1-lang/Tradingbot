"""
INTEGRATION GUIDE: FinnhubMacroManager into Main Bot Loop

This guide shows exactly how to integrate the FinnhubMacroManager into your main.py
to enable real-time macro-economic and sentiment-awareness decision making.

Key Integration Points:
1. Initialization (Phase 4: After AsyncLLMMacroMonitor setup)
2. Periodic refresh in main market loop
3. Governor sentiment-based downgrade logic
4. Graceful degradation on API failure
"""

# ============================================================================
# STEP 1: Add to main.py imports (after line ~65)
# ============================================================================
# ADD THESE IMPORTS:
from src.analysis.finnhub_macro_manager import (
    FinnhubMacroManager, 
    create_finnhub_manager,
)


# ============================================================================
# STEP 2: Initialization Code (in main() function, Phase 4)
# ============================================================================
# LOCATION: In main() after AsyncLLMMacroMonitor initialization (around line 1606)
# Replace or enhance the existing macro monitoring setup:

async def initialize_finnhub_manager(symbols, macro_risk_cache):
    """
    Initialize FinnhubMacroManager with graceful degradation.
    
    Returns:
        FinnhubMacroManager instance or None if unavailable
    """
    finnhub_api_key = os.environ.get("FINNHUB_API_KEY")
    
    if not finnhub_api_key:
        logger.warning(
            "[FINNHUB_INIT] FINNHUB_API_KEY not set. Get a free key at https://finnhub.io/"
        )
        return None
    
    try:
        finnhub_manager = FinnhubMacroManager(
            api_key=finnhub_api_key,
            symbols=symbols,
            macro_risk_cache=macro_risk_cache,
            enable_economic_calendar=True,
            enable_sentiment_analysis=True,
        )
        
        # Start background monitoring (non-blocking)
        await finnhub_manager.start()
        
        logger.critical(
            "[INIT] Finnhub Macro Manager initialized | Economic Calendar: ON | Sentiment: ON"
        )
        return finnhub_manager
        
    except Exception as e:
        logger.error("[FINNHUB_INIT_ERROR] Failed to initialize: %s | Proceeding without Finnhub", 
                     str(e)[:100])
        return None


# USAGE IN main():
# Add this in the Phase 4 section (after AsyncLLMMacroMonitor):

    # Phase 4: Finnhub Macro Manager (real-time economic calendar + news sentiment)
    finnhub_manager = None
    try:
        finnhub_manager = await initialize_finnhub_manager(symbols, macro_risk_cache)
    except Exception as e:
        logger.warning("[FINNHUB_STARTUP] Could not initialize Finnhub: %s", str(e)[:100])


# ============================================================================
# STEP 3: Periodic Refresh in Main Loop
# ============================================================================
# LOCATION: In the main market evaluation loop (around line 3000+)
# Add this inside the main async loop (every few cycles):

    # ===== FINNHUB MACRO REFRESH =====
    # Refresh Finnhub data periodically (every 300 seconds = 5 minutes)
    if finnhub_manager and cycle_count % 10 == 0:  # Every ~10 cycles if cycle time is ~30 sec
        try:
            await finnhub_manager.refresh_all()
        except Exception as e:
            logger.warning("[MAIN_LOOP] Finnhub refresh failed: %s", str(e)[:50])


# ============================================================================
# STEP 4: Governor Sentiment-Based Downgrade
# ============================================================================
# LOCATION: In the signal evaluation/Governor decision logic
# This shows how to use Finnhub sentiment to downgrade trade actions

def apply_finnhub_sentiment_override(
    signal_direction,          # Direction.LONG or Direction.SHORT
    symbol,                    # e.g., "ESR#USD" or symbol pair
    decision_matrix_action,    # e.g., Action.AGGRESSIVE_ENGAGEMENT
    finnhub_manager,           # FinnhubMacroManager instance
    macro_risk_cache,          # macro_risk_cache instance
):
    """
    Apply Finnhub-based sentiment override to trade decisions.
    
    Decision Logic:
    - If technicals signal LONG but sentiment is BEARISH -> downgrade to DEFENSIVE
    - If macro risk is HIGH (from economic calendar) -> trigger SHARPE_SILENCE
    - If upcoming high-impact event -> tighten trailing stop to 0.1R
    
    Returns:
        (modified_action, override_reason) tuple
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not finnhub_manager:
        return decision_matrix_action, None  # No override, use original action
    
    # Normalize symbol for lookup
    symbol_key = str(symbol).replace("/", "").upper()
    snapshot = finnhub_manager.get_snapshot(symbol_key)
    
    if not snapshot.data_freshness_ok:
        logger.debug("[SENTIMENT_OVERRIDE] Snapshot stale for %s, skipping override", symbol)
        return decision_matrix_action, None
    
    override_reason = None
    modified_action = decision_matrix_action
    
    # ===== RULE 1: BEARISH SENTIMENT BLOCKS LONG SIGNALS =====
    if snapshot.news_sentiment_score < 0.35:  # Strongly bearish
        if signal_direction == Direction.LONG:
            modified_action = None  # BLOCK the trade
            override_reason = f"Finnhub: Bearish sentiment ({snapshot.news_sentiment_score:.2f})"
            logger.warning(
                "[SENTIMENT_OVERRIDE] BLOCKED LONG signal for %s | %s | Reason: %s",
                symbol, signal_direction, override_reason
            )
    
    # ===== RULE 2: BULLISH SENTIMENT BLOCKS SHORT SIGNALS =====
    if snapshot.news_sentiment_score > 0.65:  # Strongly bullish
        if signal_direction == Direction.SHORT:
            modified_action = None  # BLOCK the trade
            override_reason = f"Finnhub: Bullish sentiment ({snapshot.news_sentiment_score:.2f})"
            logger.warning(
                "[SENTIMENT_OVERRIDE] BLOCKED SHORT signal for %s | %s | Reason: %s",
                symbol, signal_direction, override_reason
            )
    
    # ===== RULE 3: HIGH MACRO RISK DOWNGRADES TO DEFENSIVE =====
    macro_risk_penalty = macro_risk_cache.get_macro_risk_penalty(symbol)
    if macro_risk_penalty > 0.25:  # High macro risk
        if modified_action in [Action.AGGRESSIVE_ENGAGEMENT, Action.RELAX_FILTERS]:
            modified_action = Action.DEFENSIVE_PRESERVATION
            override_reason = f"Finnhub: High macro risk ({macro_risk_penalty:.2f}) - Event incoming"
            logger.warning(
                "[SENTIMENT_OVERRIDE] Downgraded %s to DEFENSIVE | %s",
                symbol, override_reason
            )
    
    # ===== RULE 4: IMMINENT EVENT TRIGGERS NEWS SILENCE =====
    if snapshot.event_minutes_until_high_impact is not None:
        if snapshot.event_minutes_until_high_impact < 5:
            modified_action = "NEWS_SILENCE"  # Mute trading near event
            override_reason = f"Finnhub: High-impact event in {snapshot.event_minutes_until_high_impact}min"
            logger.critical(
                "[SENTIMENT_OVERRIDE] NEWS_SILENCE activated for %s | %s",
                symbol, override_reason
            )
    
    return modified_action, override_reason


# USAGE IN Governor signal evaluation:
# Wrap your existing signal evaluation with sentiment check:

    # ... existing signal evaluation logic ...
    signal_decision = decision_matrix.evaluate(...)
    
    # ENHANCED: Apply Finnhub sentiment override
    if finnhub_manager:
        signal_decision, override_reason = apply_finnhub_sentiment_override(
            signal_direction=signal_decision.direction,
            symbol=symbol,
            decision_matrix_action=signal_decision.action,
            finnhub_manager=finnhub_manager,
            macro_risk_cache=macro_risk_cache,
        )
        
        if override_reason:
            logger.info(
                "[GOVERNOR] Finnhub override for %s | Reason: %s | Original: %s | Modified: %s",
                symbol, override_reason, "...", signal_decision
            )


# ============================================================================
# STEP 5: Dynamic Trailing Stop Tightening Before News Events
# ============================================================================
# LOCATION: In position management / profit protection module

def adjust_trailing_stop_for_news(
    position,                  # Current position object
    finnhub_manager,          # FinnhubMacroManager instance
    base_trailing_stop_pips,  # Default trailing stop (e.g., 20 pips)
):
    """
    Tighten trailing stops before high-impact news events.
    
    Logic:
    - Minutes until event >= 30: Use base trailing stop
    - Minutes until event 15-30: Tighten to 0.5x (e.g., 10 pips)
    - Minutes until event 5-15: Tighten to 0.3x (e.g., 6 pips)
    - Minutes until event < 5: Tighten to 0.1R lock (minimal loss)
    """
    symbol_key = str(position.symbol).replace("/", "").upper()
    snapshot = finnhub_manager.get_snapshot(symbol_key) if finnhub_manager else None
    
    if not snapshot or snapshot.event_minutes_until_high_impact is None:
        return base_trailing_stop_pips  # No adjustment
    
    minutes_until = snapshot.event_minutes_until_high_impact
    
    if minutes_until < 5:
        # Lock profit: use minimal 0.1R trailing stop
        adjusted_stop = base_trailing_stop_pips * 0.1
        severity = "CRITICAL"
    elif minutes_until < 15:
        # Tight protection: 0.3x
        adjusted_stop = base_trailing_stop_pips * 0.3
        severity = "HIGH"
    elif minutes_until < 30:
        # Moderate tightening: 0.5x
        adjusted_stop = base_trailing_stop_pips * 0.5
        severity = "MODERATE"
    else:
        # Safe: use base
        adjusted_stop = base_trailing_stop_pips
        severity = None
    
    if severity:
        logger.info(
            "[TRAILING_STOP] Adjusted for news | %s | Severity: %s | "
            "Base: %.0f pips -> Adjusted: %.0f pips | Event in %d min",
            position.symbol, severity, base_trailing_stop_pips, adjusted_stop, minutes_until
        )
    
    return adjusted_stop


# USAGE IN profit protector:
# In your profit protection module, replace static trailing stop with:

    for position in active_positions:
        trailing_stop_pips = adjust_trailing_stop_for_news(
            position=position,
            finnhub_manager=finnhub_manager,
            base_trailing_stop_pips=20.0,  # Your default
        )
        update_trailing_stop(position, trailing_stop_pips)


# ============================================================================
# STEP 6: Environment Configuration
# ============================================================================
# ADD TO .env or .env.optimized:

# Finnhub integration
FINNHUB_API_KEY=your_api_key_here  # Get at https://finnhub.io/
FINNHUB_ENABLE_ECONOMIC_CALENDAR=true
FINNHUB_ENABLE_SENTIMENT_ANALYSIS=true
FINNHUB_ECONOMIC_CALENDAR_CACHE_MINUTES=720
FINNHUB_NEWS_SENTIMENT_CACHE_MINUTES=10
FINNHUB_HIGH_IMPACT_EVENT_WINDOW_MINUTES=30


# ============================================================================
# STEP 7: Graceful Degradation Fallback
# ============================================================================
# The FinnhubMacroManager automatically:
# 1. Tests API connectivity on startup
# 2. Falls back to VOLATILITY_NORMAL_FALLBACK if API unavailable
# 3. Respects rate limits (60 calls/min on free tier)
# 4. Retries with exponential backoff (max 5 consecutive failures)
# 5. Logs all failures for diagnostics

# Check fallback status in main loop:
    if finnhub_manager:
        if finnhub_manager._fallback_mode_active:
            logger.warning("[FINNHUB_STATUS] Fallback mode active | Using llm_macro_monitor defaults")
        elif finnhub_manager._consecutive_failures > 0:
            logger.warning(
                "[FINNHUB_STATUS] %d consecutive API failures | May degrade soon",
                finnhub_manager._consecutive_failures
            )


# ============================================================================
# STEP 8: Example: Complete Integration Template
# ============================================================================
"""
This is a complete example showing all pieces working together:
"""

async def main_with_finnhub_integration():
    # ... existing initialization code ...
    
    # Initialize Finnhub manager
    finnhub_manager = Await initialize_finnhub_manager(symbols, macro_risk_cache)
    
    cycle_count = 0
    while True:
        cycle_count += 1
        
        # ===== Refresh Finnhub data (every 10 cycles)
        if finnhub_manager and cycle_count % 10 == 0:
            try:
                await finnhub_manager.refresh_all()
            except Exception as e:
                logger.warning("[FINNHUB_REFRESH] Failed: %s", str(e)[:50])
        
        # ===== Evaluate signals with Finnhub override
        for symbol in symbols:
            signal = generate_signal(symbol)  # Your signal generation
            
            if signal and finnhub_manager:
                # Apply sentiment-based override
                modified_signal, reason = apply_finnhub_sentiment_override(
                    signal_direction=signal.direction,
                    symbol=symbol,
                    decision_matrix_action=signal.action,
                    finnhub_manager=finnhub_manager,
                    macro_risk_cache=macro_risk_cache,
                )
                
                if reason:
                    logger.info("[DECISION] %s | Override: %s", symbol, reason)
                    signal.action = modified_signal
            
            # ===== Place trade if not blocked
            if signal and signal.action != "NEWS_SILENCE":
                await execute_trade(symbol, signal)
        
        # ===== Adjust trailing stops for news events
        for position in active_positions:
            trailing_stop = adjust_trailing_stop_for_news(
                position=position,
                finnhub_manager=finnhub_manager,
                base_trailing_stop_pips=20.0,
            )
            update_trailing_stop(position, trailing_stop)
        
        await asyncio.sleep(30)  # Main cycle interval


# ============================================================================
# STEP 9: Testing & Validation
# ============================================================================
"""
To test the Finnhub integration:

1. Get a free API key at https://finnhub.io/
2. Set FINNHUB_API_KEY environment variable
3. Run bot with verbose logging: export DEBUG=1
4. Watch for these log messages:

   - [FINNHUB_TEST] ✅ API connectivity OK
   - [FINNHUB_LOOP] Background monitoring loop started
   - [MACRO_MONITOR] Finnhub sentiment for EUR/USD: BEARISH | Risk: 7.5/10
   - [SENTIMENT_OVERRIDE] Downgraded EUR/USD to DEFENSIVE
   - [TRAILING_STOP] Adjusted for news | Severity: CRITICAL
   
5. Verify macro_risk_cache is being updated:
   Check data/macro_risk_cache.json after bot runs
   Look for "source": "finnhub" entries

6. Monitor fallback behavior (optional):
   # Temporarily disable API or set invalid key
   # Should see [FINNHUB_FALLBACK] messages
   # Bot should continue with llm_macro_monitor defaults
"""

# ============================================================================
# STEP 10: Performance Metrics & Monitoring
# ============================================================================
"""
Key metrics to monitor after integration:

1. API Response Times:
   - Economic Calendar: <2 sec (cached 12 hours)
   - News/Sentiment: <3 sec (cached 10 min)

2. Cache Hit Rate:
   - Economic Calendar: 95%+ (12-hour cache)
   - News: 70-80% (10-min cache, updates frequently)

3. Decision Impact:
   - Sentiment-blocked trades: Track vs profitability
   - News-adjusted trailing stops: Compare to non-Finnhub runs
   - Risk score distribution: Check against historical baseline

4. Reliability:
   - API uptime: Target >99%
   - Fallback activation rate: <1%
   - Recovery time from failure: <5 min

5. Rate Limit Compliance:
   - API calls per minute: <60 (free tier)
   - Throttle events: Should be 0 (if properly spaced)
"""

print(__doc__)

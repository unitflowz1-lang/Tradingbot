"""
COMPLETE INTEGRATION TEMPLATE: Main.py Integration Points

This file shows exactly WHERE and HOW to integrate FinnhubMacroManager into your
existing main.py code. Copy-paste ready for each integration point.

Find each section by searching your main.py for the markers in comments.
"""

# ============================================================================
# INTEGRATION POINT #1: IMPORTS (Line ~65 after existing imports)
# ============================================================================

"""
ADD THESE LINES to main.py after existing imports from src.analysis:

from src.analysis.finnhub_macro_manager import (
    FinnhubMacroManager, 
    create_finnhub_manager,
    MacroRiskSnapshot,
)
"""

# ============================================================================
# INTEGRATION POINT #2: INITIALIZATION HELPER (Paste as new function)
# ============================================================================

"""
Create this helper function BEFORE main() definition:
"""

async def _initialize_finnhub_manager(symbols, macro_risk_cache):
    """
    Initialize FinnhubMacroManager with full error handling.
    
    Returns:
        (manager, is_active) tuple where:
        - manager: FinnhubMacroManager instance or None
        - is_active: Boolean indicating if manager is running
    """
    finnhub_api_key = os.environ.get("FINNHUB_API_KEY")
    
    if not finnhub_api_key or str(finnhub_api_key).strip() == "":
        logger.warning(
            "[FINNHUB_INIT] API key not provided. Get free key at https://finnhub.io/ "
            "and set FINNHUB_API_KEY environment variable. "
            "Skipping Finnhub integration (bot will use llm_macro_monitor defaults)."
        )
        return None, False
    
    try:
        manager = FinnhubMacroManager(
            api_key=finnhub_api_key,
            symbols=symbols,
            macro_risk_cache=macro_risk_cache,
            enable_economic_calendar=os.environ.get("FINNHUB_ENABLE_ECONOMIC_CALENDAR", "true").lower() == "true",
            enable_sentiment_analysis=os.environ.get("FINNHUB_ENABLE_SENTIMENT_ANALYSIS", "true").lower() == "true",
        )
        
        # Start background monitoring (non-blocking)
        await manager.start()
        
        logger.critical(
            "[INIT] ✅ Finnhub Macro Manager initialized | "
            "Economic Calendar: %s | Sentiment Analysis: %s",
            manager.enable_economic_calendar,
            manager.enable_sentiment_analysis,
        )
        return manager, True
        
    except Exception as e:
        logger.error(
            "[FINNHUB_INIT_ERROR] Failed to initialize FinnhubMacroManager: %s | "
            "Bot will operate with llm_macro_monitor defaults only",
            str(e)[:150],
        )
        return None, False


# ============================================================================
# INTEGRATION POINT #3: PHASE 4 INITIALIZATION (In main(), ~line 1606)
# ============================================================================

"""
FIND THIS in main():
    macro_monitor = AsyncLLMMacroMonitor(
        symbols=symbols,
        ...
    )

ADD AFTER macro_monitor initialization:

    # Phase 4b: Finnhub Macro Manager (Real-time economic calendar + sentiment)
    finnhub_manager, finnhub_active = await _initialize_finnhub_manager(symbols, macro_risk_cache)
    if not finnhub_active:
        logger.info("[INIT] Operating without Finnhub integration (fallback to llm_macro_monitor)")
        finnhub_manager = None
"""

# ============================================================================
# INTEGRATION POINT #4: MAIN LOOP PERIODIC REFRESH (~line 3000+)
# ============================================================================

"""
FIND THIS in main loop (inside the main while True loop):
    cycle_count += 1

ADD AFTER cycle_count increment:

    # ===== FINNHUB DATA REFRESH (every 10 cycles ≈ every 5 minutes) =====
    if finnhub_manager is not None and cycle_count % 10 == 0:
        try:
            await finnhub_manager.refresh_all()
        except Exception as e:
            logger.warning(
                "[MAIN_LOOP] Finnhub refresh cycle %d failed: %s",
                cycle_count, str(e)[:100]
            )
"""

# ============================================================================
# INTEGRATION POINT #5: SIGNAL EVALUATION WITH SENTIMENT OVERRIDE (~line 3200+)
# ============================================================================

"""
FIND THIS in your signal evaluation loop:
    for symbol in symbols_to_evaluate:
        signal = generate_signal(symbol, ...)
        
REPLACE WITH THIS to add sentiment override:
"""

def _apply_finnhub_sentiment_override_to_signal(
    signal,
    symbol,
    finnhub_manager,
    macro_risk_cache,
    decision_matrix,
):
    """
    Apply FinnhubMacroManager sentiment override to trading signal.
    
    Implements these rules:
    1. Bearish sentiment (< 0.35) BLOCKS LONG signals
    2. Bullish sentiment (> 0.65) BLOCKS SHORT signals
    3. High macro risk (penalty > 0.25) downgrades to DEFENSIVE
    4. Imminent events (< 5 min) trigger NEWS_SILENCE
    
    Args:
        signal: TradingSignal object (or None if no signal)
        symbol: Trading symbol (e.g., "EUR/USD")
        finnhub_manager: FinnhubMacroManager instance
        macro_risk_cache: macro_risk_cache instance
        decision_matrix: DecisionMatrix instance (for action types)
    
    Returns:
        (modified_signal, override_reason) tuple
        - modified_signal: Updated signal or None if blocked
        - override_reason: String explaining what changed (or None)
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not signal or not finnhub_manager:
        return signal, None  # No override
    
    symbol_key = str(symbol).replace("/", "").upper()
    snapshot = finnhub_manager.get_snapshot(symbol_key)
    
    # If data is stale, use original signal
    if not snapshot.data_freshness_ok:
        return signal, None
    
    override_reason = None
    
    # ===== RULE 1: BEARISH SENTIMENT BLOCKS LONG =====
    if snapshot.news_sentiment_score < 0.35:
        if signal.direction == Direction.LONG:
            logger.warning(
                "[SENTIMENT_OVERRIDE] BLOCKED LONG signal | %s | "
                "Bearish sentiment (%.2f) | Risk: %.1f/10",
                symbol,
                snapshot.news_sentiment_score,
                snapshot.risk_score,
            )
            return None, f"Finnhub: Bearish sentiment ({snapshot.news_sentiment_score:.2f})"
    
    # ===== RULE 2: BULLISH SENTIMENT BLOCKS SHORT =====
    if snapshot.news_sentiment_score > 0.65:
        if signal.direction == Direction.SHORT:
            logger.warning(
                "[SENTIMENT_OVERRIDE] BLOCKED SHORT signal | %s | "
                "Bullish sentiment (%.2f) | Risk: %.1f/10",
                symbol,
                snapshot.news_sentiment_score,
                snapshot.risk_score,
            )
            return None, f"Finnhub: Bullish sentiment ({snapshot.news_sentiment_score:.2f})"
    
    # ===== RULE 3: HIGH MACRO RISK DOWNGRADES TO DEFENSIVE =====
    macro_risk_penalty = macro_risk_cache.get_macro_risk_penalty(symbol)
    if macro_risk_penalty > 0.25:  # High macro risk threshold
        # Downgrade action if signal suggests aggressive trading
        if hasattr(signal, 'action'):
            if str(signal.action).upper() in ["AGGRESSIVE_ENGAGEMENT", "RELAX_FILTERS", "INCREASE_POSITION_50"]:
                logger.warning(
                    "[SENTIMENT_OVERRIDE] Downgraded action to DEFENSIVE | %s | "
                    "High macro risk (penalty: %.3f) | Reason: %s",
                    symbol,
                    macro_risk_penalty,
                    macro_risk_cache.get_macro_risk_reason(symbol),
                )
                signal.action = "DEFENSIVE_PRESERVATION"
                override_reason = f"Finnhub: High macro risk ({macro_risk_penalty:.3f})"
    
    # ===== RULE 4: IMMINENT EVENT TRIGGERS NEWS_SILENCE =====
    if snapshot.event_minutes_until_high_impact is not None:
        if snapshot.event_minutes_until_high_impact < 5:
            logger.critical(
                "[SENTIMENT_OVERRIDE] NEWS_SILENCE activated | %s | "
                "High-impact event in %d minutes | Event: %s",
                symbol,
                snapshot.event_minutes_until_high_impact,
                snapshot.risk_reason,
            )
            return None, f"Finnhub: High-impact event in {snapshot.event_minutes_until_high_impact} min"
    
    return signal, override_reason


"""
USAGE IN main loop signal evaluation:

    for symbol in symbols_to_evaluate:
        signal = generate_signal(symbol, ...)
        
        # Apply Finnhub sentiment override
        if finnhub_manager:
            signal, override_reason = _apply_finnhub_sentiment_override_to_signal(
                signal=signal,
                symbol=symbol,
                finnhub_manager=finnhub_manager,
                macro_risk_cache=macro_risk_cache,
                decision_matrix=decision_matrix,
            )
            
            if override_reason:
                logger.info(
                    "[GOVERNOR] Finnhub override applied | %s | %s",
                    symbol, override_reason
                )
        
        # Continue with execution if signal not blocked
        if signal:
            await execute_trade(symbol, signal)
"""

# ============================================================================
# INTEGRATION POINT #6: PROFIT PROTECTION - DYNAMIC TRAILING STOPS (~line 4500+)
# ============================================================================

"""
In your profit protection module, enhance trailing stop adjustment:
"""

def _compute_news_aware_trailing_stop(
    position,
    finnhub_manager,
    base_trailing_stop_pips,
    symbol=None,
):
    """
    Compute trailing stop adjusted for upcoming economic events.
    
    Tightens trailing stops as high-impact events approach:
    - > 30 min to event: use base trailing stop
    - 15-30 min: tighten to 50% (0.5x)
    - 5-15 min: tighten to 30% (0.3x)  
    - < 5 min: lock profit at 10% (0.1x) to protect from slippage
    
    Args:
        position: Position object
        finnhub_manager: FinnhubMacroManager instance
        base_trailing_stop_pips: Default trailing stop (e.g., 20 pips)
        symbol: Symbol (or derived from position)
    
    Returns:
        Adjusted trailing stop in pips
    """
    import logging
    logger = logging.getLogger(__name__)
    
    if not finnhub_manager:
        return base_trailing_stop_pips  # No adjustment
    
    # Get symbol
    symbol = symbol or getattr(position, 'symbol', None)
    if not symbol:
        return base_trailing_stop_pips
    
    symbol_key = str(symbol).replace("/", "").upper()
    snapshot = finnhub_manager.get_snapshot(symbol_key)
    
    # If no event or data stale, use base
    if snapshot.event_minutes_until_high_impact is None or not snapshot.data_freshness_ok:
        return base_trailing_stop_pips
    
    minutes_until = snapshot.event_minutes_until_high_impact
    adjusted_stop = base_trailing_stop_pips  # Default
    severity = None
    
    if minutes_until < 5:
        # CRITICAL: Lock profit (0.1x)
        adjusted_stop = base_trailing_stop_pips * 0.1
        severity = "CRITICAL_LOCK"
    elif minutes_until < 15:
        # HIGH: Tight protection (0.3x)
        adjusted_stop = base_trailing_stop_pips * 0.3
        severity = "HIGH_TIGHT"
    elif minutes_until < 30:
        # MODERATE: Half tightening (0.5x)
        adjusted_stop = base_trailing_stop_pips * 0.5
        severity = "MODERATE"
    
    if severity:
        logger.info(
            "[TRAILING_STOP_ADJUST] %s | Severity: %s | "
            "Base: %.1f pips → Adjusted: %.1f pips | Event in %d min",
            symbol, severity, base_trailing_stop_pips, adjusted_stop, minutes_until
        )
    
    return adjusted_stop


"""
USAGE IN profit protection routine:

    for position in active_positions:
        # Compute news-aware trailing stop
        adjusted_stop = _compute_news_aware_trailing_stop(
            position=position,
            finnhub_manager=finnhub_manager,
            base_trailing_stop_pips=20.0,  # Your default
        )
        
        # Update position
        update_position_trailing_stop(position, adjusted_stop)
"""

# ============================================================================
# INTEGRATION POINT #7: GOVERNOR MACRO RISK CHECK (~line 4800+)
# ============================================================================

"""
In your GovERNOR risk evaluation logic:
"""

def _apply_macro_risk_governor_rules(
    symbol,
    macro_risk_cache,
    finnhub_manager,
    current_decision_action,
):
    """
    Apply macro risk rules to Governor decisions.
    
    Returns modified action if macro conditions warrant change.
    """
    import logging
    logger = logging.getLogger(__name__)
    
    macro_penalty = macro_risk_cache.get_macro_risk_penalty(symbol)
    macro_reason = macro_risk_cache.get_macro_risk_reason(symbol)
    
    # Rule: High macro risk (>0.3) triggers defensive mode
    if macro_penalty > 0.3:
        if str(current_decision_action).upper() in [
            "AGGRESSIVE_ENGAGEMENT",
            "INCREASE_POSITION_50",
            "INCREASE_POSITION_25",
            "RELAX_FILTERS"
        ]:
            logger.warning(
                "[GOVERNOR_MACRO] Macro risk override | %s | "
                "Penalty: %.3f (threshold: 0.3) | Reason: %s",
                symbol, macro_penalty, macro_reason
            )
            return "DEFENSIVE_PRESERVATION"
    
    # Rule: Very high macro risk (>0.35) may trigger silence
    if macro_penalty > 0.35:
        if finnhub_manager:
            snapshot = finnhub_manager.get_snapshot(symbol.replace("/", "").upper())
            if snapshot.event_minutes_until_high_impact and snapshot.event_minutes_until_high_impact < 10:
                logger.critical(
                    "[GOVERNOR_MACRO] SILENCE activated | %s | "
                    "Critical macro event in %d min | Penalty: %.3f",
                    symbol, snapshot.event_minutes_until_high_impact, macro_penalty
                )
                return "MACRO_SILENCE"
    
    return current_decision_action  # No macro override


"""
USAGE IN governor decision loop:

    governor_action = decision_matrix.evaluate(metrics)
    
    # Apply macro risk override
    governor_action = _apply_macro_risk_governor_rules(
        symbol=symbol,
        macro_risk_cache=macro_risk_cache,
        finnhub_manager=finnhub_manager,
        current_decision_action=governor_action.action,
    )
"""

# ============================================================================
# INTEGRATION POINT #8: SHUTDOWN/CLEANUP (~line end of main())
# ============================================================================

"""
At the end of main() in the finally block:

    finally:
        if finnhub_manager:
            try:
                await finnhub_manager.stop()
                logger.info("[SHUTDOWN] Finnhub manager stopped gracefully")
            except Exception as e:
                logger.warning("[SHUTDOWN] Error stopping Finnhub manager: %s", str(e)[:50])
"""

# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

"""
Add to your .env file:

# Finnhub Integration
FINNHUB_API_KEY=your_free_key_from_finnhub_io

# Optional controls
FINNHUB_ENABLE_ECONOMIC_CALENDAR=true
FINNHUB_ENABLE_SENTIMENT_ANALYSIS=true
FINNHUB_ECONOMIC_CALENDAR_CACHE_MINUTES=720
FINNHUB_NEWS_SENTIMENT_CACHE_MINUTES=10
FINNHUB_HIGH_IMPACT_EVENT_WINDOW_MINUTES=30
"""

# ============================================================================
# COMPLETE WORKFLOW EXAMPLE
# ============================================================================

"""
Here's how it all flows together:

1. BOT STARTUP:
   [INIT] Finnhub Macro Manager initialized
   → START monitoring economic calendar & news
   
2. MAIN LOOP (every 10 cycles):
   [MAIN_LOOP] Finnhub refresh cycle 10 started
   → FETCH economic calendar from Finnhub
   → FETCH news articles & calculate sentiment
   → UPDATE macro_risk_cache with penalties & reasons
   
3. SIGNAL GENERATION:
   → Generate technical signal (RSI, ADX, etc.)
   
4. SENTIMENT OVERRIDE CHECK:
   [SENTIMENT_OVERRIDE] Checking EUR/USD
   → EUR/USD has BEARISH sentiment (0.28)
   → BLOCKED LONG signal
   
5. GOVERNOR DECISION:
   [GOVERNOR] Macro risk penalty: 0.32
   → Downgrade AGGRESSIVE to DEFENSIVE
   
6. POSITION MANAGEMENT:
   [TRAILING_STOP_ADJUST] EUR/USD
   → NFP event in 8 minutes
   → Tighten trailing stop from 20 to 6 pips

7. GRACEFUL DEGRADATION (if API fails):
   [FINNHUB_FALLBACK] Max failures reached
   → Switch to llm_macro_monitor defaults
   → Continue trading with reduced macro awareness
   → Resume Finnhub monitoring when API returns

8. SHUTDOWN:
   [SHUTDOWN] Finnhub manager stopped gracefully
"""

# ============================================================================
print(__doc__)

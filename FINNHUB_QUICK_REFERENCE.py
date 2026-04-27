"""
FINNHUB_MACROASMANAGER - QUICK REFERENCE

Your complete cheat sheet for Finnhub integration in the MT5 trading bot.
Copy-paste code snippets ready to use!
"""

# ============================================================================
# 1. QUICK START: Get an API Key
# ============================================================================

"""
1. Visit: https://finnhub.io/
2. Sign up for FREE account (no credit card required)
3. Go to Dashboard → API keys
4. Copy your API key
5. Set environment variable:
   
   # Linux/Mac:
   export FINNHUB_API_KEY=your_api_key_here
   
   # Windows (PowerShell):
   $env:FINNHUB_API_KEY="your_api_key_here"
   
   # Or add to .env file:
   FINNHUB_API_KEY=your_api_key_here
"""

# ============================================================================
# 2. MINIMAL INTEGRATION (3 lines of code)
# ============================================================================

"""
In your main.py, add these 3 lines to Phase 4:

from src.analysis.finnhub_macro_manager import FinnhubMacroManager

finnhub_manager = FinnhubMacroManager(
    api_key=os.environ.get("FINNHUB_API_KEY"),
    symbols=symbols,
    macro_risk_cache=macro_risk_cache,
)
await finnhub_manager.start()
"""

# ============================================================================
# 3. ACCESS MACRO RISK DATA IN YOUR CODE
# ============================================================================

"""
Get current risk snapshot for a symbol:

snapshot = finnhub_manager.get_snapshot("EURUSD")
print(f"Risk Score: {snapshot.risk_score}/10")  # 0-10 scale
print(f"Sentiment: {snapshot.news_sentiment_score}")  # 0-1 scale (0=bearish, 1=bullish)
print(f"Next event in: {snapshot.event_minutes_until_high_impact} min")
print(f"Reason: {snapshot.risk_reason}")
"""

# ============================================================================
# 4. BLOCK TRADES BASED ON SENTIMENT
# ============================================================================

Example_Code_1_Block_LONG_on_Bearish = """
# Check sentiment before placing LONG trade:
snapshot = finnhub_manager.get_snapshot(symbol)
if snapshot.news_sentiment_score < 0.35:
    logger.warning(f"[BLOCK] Bearish sentiment for {symbol}")
    return None  # Block the trade

# Or use auto-override function:
modified_signal, reason = apply_finnhub_sentiment_override(
    signal_direction=signal.direction,
    symbol=symbol,
    decision_matrix_action=signal.action,
    finnhub_manager=finnhub_manager,
    macro_risk_cache=macro_risk_cache,
)
if reason:
    logger.info(f"Override: {reason}")
"""

# ============================================================================
# 5. TRIGGER SHARPE_SILENCE ON NEWS EVENTS
# ============================================================================

Example_Code_2_News_Silence = """
# Silence trading 5 minutes before high-impact event:
snapshot = finnhub_manager.get_snapshot(symbol)
if snapshot.event_minutes_until_high_impact and snapshot.event_minutes_until_high_impact < 5:
    logger.critical(f"NEWS_SILENCE for {symbol} - event imminent!")
    return "NEWS_SILENCE"  # Skip new trades
"""

# ============================================================================
# 6. TIGHTEN TRAILING STOPS BEFORE NEWS
# ============================================================================

Example_Code_3_Tighten_Stops = """
# Dynamic trailing stop adjustment:
snapshot = finnhub_manager.get_snapshot(symbol)
trailing_stop_pips = 20  # Your base

if snapshot.event_minutes_until_high_impact:
    minutes_until = snapshot.event_minutes_until_high_impact
    
    if minutes_until < 5:
        trailing_stop_pips *= 0.1  # Critical: lock profit
    elif minutes_until < 15:
        trailing_stop_pips *= 0.3  # Tight protection
    elif minutes_until < 30:
        trailing_stop_pips *= 0.5  # Moderate tightening

# Apply new trailing stop
update_position_trailing_stop(position, trailing_stop_pips)
"""

# ============================================================================
# 7. DOWNGRADE AGGRESSIVE TO DEFENSIVE ON MACRO RISK
# ============================================================================

Example_Code_4_Macro_Downgrade = """
# Check macro risk and downgrade decisions:
macro_penalty = macro_risk_cache.get_macro_risk_penalty(symbol)

if macro_penalty > 0.25:  # High macro risk
    logger.warning(f"Downgrading {symbol} to DEFENSIVE (macro risk: {macro_penalty:.2f})")
    
    if decision.action == Action.AGGRESSIVE_ENGAGEMENT:
        decision.action = Action.DEFENSIVE_PRESERVATION
"""

# ============================================================================
# 8. MONITOR IN PRODUCTION
# ============================================================================

Log_Examples = """
Watch your logs for these messages:

✅ [FINNHUB_START] ✅ Background monitoring started
   → Manager started successfully

[FINNHUB_TEST] ✅ API connectivity OK (HTTP 200)
   → API key is valid and reachable

[MACRO_MONITOR] Finnhub sentiment for EUR/USD: BEARISH | Risk: 7.5/10
   → Data update received

[SENTIMENT_OVERRIDE] BLOCKED LONG signal for EUR/USD | Reason: Bearish sentiment
   → Trade was blocked by sentiment check

[TRAILING_STOP] Adjusted for news | Severity: CRITICAL | Base: 20 pips -> 2 pips
   → Trailing stop was tightened for news event

[FINNHUB_FALLBACK] Max failures reached. Activating fallback mode.
   → API down; using defaults instead

[FINNHUB_LOOP_ERROR] Attempt 3/5 | Error: API rate limit exceeded
   → Temporary API issue (will recover)
"""

# ============================================================================
# 9. ENVIRONMENT VARIABLE REFERENCE
# ============================================================================

Environment_Variables = """
Required:
  FINNHUB_API_KEY=your_key_here

Optional (with defaults):
  FINNHUB_ENABLE_ECONOMIC_CALENDAR=true       # Fetch economic calendar
  FINNHUB_ENABLE_SENTIMENT_ANALYSIS=true      # Fetch news & sentiment
  FINNHUB_ECONOMIC_CALENDAR_CACHE_MINUTES=720 # Cache 12 hours
  FINNHUB_NEWS_SENTIMENT_CACHE_MINUTES=10     # Cache 10 minutes
  FINNHUB_HIGH_IMPACT_EVENT_WINDOW_MINUTES=30 # Event window size
"""

# ============================================================================
# 10. DECISION MATRIX INTEGRATION
# ============================================================================

Integration_With_Decision_Matrix = """
The FinnhubMacroManager updates macro_risk_cache with:

symbol -> risk_penalty (0.0-0.4)
symbol -> risk_reason (string)

Your DECISION_MATRIX uses these via:

macro_penalty = macro_risk_cache.get_macro_risk_penalty(symbol)
macro_reason = macro_risk_cache.get_macro_risk_reason(symbol)

Risk Score Mapping:
  0.0-0.1   → Very low risk     → OPTIMAL    action
  0.1-0.2   → Low risk          → MAINTAIN   action
  0.2-0.3   → Medium risk       → DEFENSIVE  action
  0.3-0.4   → High risk         → CRITICAL   action
"""

# ============================================================================
# 11. DATA STRUCTURES REFERENCE
# ============================================================================

Data_Structures = """
MacroRiskSnapshot (what you get from get_snapshot()):
  - symbol: str                          # "EURUSD"
  - risk_score: float                    # 0.0-10.0 (0=safe, 10=critical)
  - risk_reason: str                     # "High-impact event in 15min"
  - upcoming_events: List[EconomicEvent] # [NFP, CPI, ECB rates, ...]
  - news_sentiment_score: float          # 0.0-1.0 (0=bearish, 1=bullish)
  - event_minutes_until_high_impact: int # None or minutes until event
  - last_updated_at: datetime            # When data was fetched
  - data_freshness_ok: bool              # True if data <5min old

EconomicEvent:
  - country: str                         # "US", "EU", "GB", etc.
  - event_name: str                      # "Non-Farm Payrolls"
  - impact: str                          # "high", "medium", "low"
  - forecast: float                      # Expected value
  - previous: float                      # Last release value
  - actual: float                        # Actual value (if released)
  - minutes_until_event: int             # Minutes to release

NewsArticle:
  - headline: str                        # Article title
  - sentiment: str                       # "bullish", "neutral", "bearish"
  - sentiment_score: float               # -0.5 to 0.5 (bearish to bullish)
  - source: str                          # News source name
  - published_at_unix: int               # Unix timestamp
"""

# ============================================================================
# 12. RATE LIMITING DETAILS
# ============================================================================

Rate_Limiting = """
Finnhub Free Tier Limits:
  - 60 API calls per minute
  - 1 call per 1 second (implemented as minimum interval)

FinnhubMacroManager handles this automatically:
  - Tracks call timestamps
  - Automatically delays calls if limit reached
  - Exponential backoff on failures
  - Graceful degradation if API overloaded

Your job: Just call refresh_all() on regular schedule!

Recommended intervals:
  - Economic calendar: Every 12 hours (cached)
  - News/sentiment: Every 5-10 minutes
  - In main loop: Every 10 cycles (if 30sec per cycle ≈ 5 min)
"""

# ============================================================================
# 13. TROUBLESHOOTING CHECKLIST
# ============================================================================

Troubleshooting = """
❌ [FINNHUB_TEST] ❌ API connectivity failed:
   → Check API key: echo $FINNHUB_API_KEY
   → Verify key format (alphanumeric string, no spaces)
   → Test Finnhub directly: curl "https://finnhub.io/api/v1/economic-calendar?token=YOUR_KEY"

❌ [FINNHUB_FALLBACK] Max failures reached:
   → Check internet connection
   → Verify Finnhub service status
   → Check for firewall/proxy issues
   → Bot will use llm_macro_monitor defaults

⚠️  [FINNHUB_RATE_LIMIT] Waiting X seconds:
   → Normal on free tier with many requests
   → Add small delays between refresh_all() calls
   → Reduce number of symbols if possible

📝 Data not updating?
   → Check if manager is running: finnhub_manager._task
   → Verify await finnhub_manager.start() was called
   → Check logs for errors
   → Try restarting manager

🔍 No override happening?
   → Verify apply_finnhub_sentiment_override() is called
   → Check sentiment threshold (default: <0.35 for bear, >0.65 for bull)
   → Ensure finnhub_manager is not None
"""

# ============================================================================
# 14. PERFORMANCE OPTIMIZATION
# ============================================================================

Optimization_Tips = """
1. Symbol Reduction:
   - Monitor only major pairs: EUR/USD, GBP/USD, USD/JPY, USD/CHF, AUD/USD
   - Skip minors if not trading them
   - Reduces API calls by 50%

2. Cache Tuning:
   - Economic calendar: 720+ minutes (rarely changes)
   - News: 5-10 minutes (updating frequently)
   - Adjust based on your needs

3. Refresh Frequency:
   - Every 5 minutes for news/sentiment
   - Every 12 hours for economic calendar
   - Fine-tune based on trading style

4. API Key Monitoring:
   - Monitor call count: Check Finnhub dashboard
   - Stay under 60 calls/min limit
   - Contact Finnhub support if limits insufficient

5. Fallback Mode:
   - Bot gracefully falls back to llm_macro_monitor
   - No trading stops; macro awareness just reduces
   - Recovery automatic when API returns online
"""

# ============================================================================
# 15. PRODUCTION DEPLOYMENT CHECKLIST
# ============================================================================

Deployment_Checklist = """
Before going live:

□ API Key
  □ Have valid Finnhub API key
  □ Set FINNHUB_API_KEY environment variable
  □ Tested connectivity with test_finnhub_integration.py

□ Integration
  □ FinnhubMacroManager imported in main.py
  □ Manager initialized in Phase 4
  □ refresh_all() called in main loop
  □ Log statements match expected format

□ Decision Logic
  □ Sentiment override implemented
  □ Trailing stop tightening active
  □ NEWS_SILENCE works
  □ Macro risk downgrade works

□ Error Handling
  □ Fallback mode tested (disable API temporarily)
  □ No exceptions crash bot
  □ Logs show graceful degradation

□ Monitoring
  □ Log parsing configured
  □ Alerts set for [FINNHUB_FALLBACK]
  □ Performance metrics baseline established

□ Documentation
  □ Team knows how Finnhub works
  □ Troubleshooting guide shared
  □ API key stored securely
"""

# ============================================================================
# USAGE: Print this file
# ============================================================================

if __name__ == "__main__":
    import sys
    
    print(__doc__)
    
    sections = [
        ("QUICK START", "1. QUICK START: Get an API Key"),
        ("MINIMAL INTEGRATION", "2. MINIMAL INTEGRATION (3 lines of code)"),
        ("ACCESSING DATA", "3. ACCESS MACRO RISK DATA IN YOUR CODE"),
        ("BLOCK TRADES", "4. BLOCK TRADES BASED ON SENTIMENT"),
        ("NEWS SILENCE", "5. TRIGGER SHARPE_SILENCE ON NEWS EVENTS"),
        ("TIGHTEN STOPS", "6. TIGHTEN TRAILING STOPS BEFORE NEWS"),
        ("DOWNGRADE DECISION", "7. DOWNGRADE AGGRESSIVE TO DEFENSIVE ON MACRO RISK"),
        ("LOG MONITORING", "8. MONITOR IN PRODUCTION"),
        ("ENVIRONMENT VARS", "9. ENVIRONMENT VARIABLE REFERENCE"),
        ("DECISION INTEGRATION", "10. DECISION MATRIX INTEGRATION"),
        ("DATA STRUCTURES", "11. DATA STRUCTURES REFERENCE"),
        ("RATE LIMITING", "12. RATE LIMITING DETAILS"),
        ("TROUBLESHOOTING", "13. TROUBLESHOOTING CHECKLIST"),
        ("OPTIMIZATION", "14. PERFORMANCE OPTIMIZATION"),
        ("DEPLOYMENT", "15. PRODUCTION DEPLOYMENT CHECKLIST"),
    ]
    
    print("\nQuick navigation:")
    for short, full in sections:
        print(f"  - {short}: {full}")
    print("\nTo search specifically:")
    print("  grep -n 'SECTION_TITLE' FINNHUB_QUICK_REFERENCE.py")

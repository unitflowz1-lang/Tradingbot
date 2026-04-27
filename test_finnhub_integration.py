#!/usr/bin/env python3
"""
WORKING EXAMPLE: FinnhubMacroManager Standalone Demo

This script demonstrates how to use FinnhubMacroManager independently
and shows the data structures returned by Finnhub API integration.

Run this to test your Finnhub setup before integrating into main.py:
    python test_finnhub_integration.py
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

# Configure logging to match bot format
logging.basicConfig(
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# Import after logging setup to catch initialization logs
from src.analysis.finnhub_macro_manager import FinnhubMacroManager
from src.analysis.llm_macro_monitor import MacroRiskCache


async def demo_basic_initialization():
    """Demo 1: Initialize FinnhubMacroManager and start monitoring."""
    print("\n" + "="*80)
    print("DEMO 1: Basic Initialization")
    print("="*80 + "\n")

    api_key = os.environ.get("FINNHUB_API_KEY", "demo_key_xyz")
    
    if api_key == "demo_key_xyz":
        logger.error("[DEMO] FINNHUB_API_KEY not set. Get one at https://finnhub.io/")
        logger.info("[DEMO] Set: export FINNHUB_API_KEY=your_api_key")
        return None

    # Initialize macro risk cache (same as main bot uses)
    macro_cache = MacroRiskCache()

    # Create manager
    manager = FinnhubMacroManager(
        api_key=api_key,
        symbols=["EUR/USD", "GBP/USD", "USD/JPY"],
        macro_risk_cache=macro_cache,
    )

    # Start background monitoring
    await manager.start()

    logger.info("[DEMO] Manager started. Waiting for first data refresh...")
    await asyncio.sleep(5)

    # Get snapshots
    logger.info("[DEMO] Current macro risk snapshots:")
    for symbol in ["EURUSD", "GBPUSD", "USDJPY"]:
        snapshot = manager.get_snapshot(symbol)
        logger.info(
            "[DEMO] %s | Risk: %.1f/10 | Sentiment: %.2f | "
            "Events: %d | Freshness: %s",
            symbol,
            snapshot.risk_score,
            snapshot.news_sentiment_score,
            len(snapshot.upcoming_events),
            "OK" if snapshot.data_freshness_ok else "STALE",
        )

    # Check macro_risk_cache
    logger.info("[DEMO] Macro risk cache state:")
    cache_snapshot = macro_cache.snapshot()
    for symbol, penalty in cache_snapshot.get("penalties", {}).items():
        reason = cache_snapshot.get("reasons", {}).get(symbol, "Unknown")
        logger.info("[DEMO] %s | Penalty: %.3f | Reason: %s", symbol, penalty, reason)

    await manager.stop()
    logger.info("[DEMO 1] Complete")
    return manager


async def demo_economic_calendar():
    """Demo 2: Show economic calendar event processing."""
    print("\n" + "="*80)
    print("DEMO 2: Economic Calendar Events")
    print("="*80 + "\n")

    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.warning("[DEMO 2] Skipped (no API key)")
        return

    macro_cache = MacroRiskCache()

    manager = FinnhubMacroManager(
        api_key=api_key,
        symbols=["EUR/USD", "GBP/USD"],
        macro_risk_cache=macro_cache,
        enable_sentiment_analysis=False,  # Focus on calendar
        enable_economic_calendar=True,
    )

    await manager.start()
    logger.info("[DEMO 2] Fetching economic calendar...")
    await asyncio.sleep(3)

    # Show upcoming events
    for symbol in ["EURUSD", "GBPUSD"]:
        snapshot = manager.get_snapshot(symbol)
        if snapshot.upcoming_events:
            logger.info("[DEMO 2] %s - Upcoming events:", symbol)
            for event in snapshot.upcoming_events[:3]:  # Show top 3
                logger.info(
                    "[DEMO 2]   - %s: %s | Impact: %s | In %d min",
                    event.country,
                    event.event_name,
                    event.impact,
                    event.minutes_until_event,
                )

    await manager.stop()
    logger.info("[DEMO 2] Complete")


async def demo_sentiment_analysis():
    """Demo 3: News sentiment analysis."""
    print("\n" + "="*80)
    print("DEMO 3: News & Sentiment Analysis")
    print("="*80 + "\n")

    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.warning("[DEMO 3] Skipped (no API key)")
        return

    macro_cache = MacroRiskCache()

    manager = FinnhubMacroManager(
        api_key=api_key,
        symbols=["EUR/USD", "USD/JPY"],
        macro_risk_cache=macro_cache,
        enable_sentiment_analysis=True,
        enable_economic_calendar=False,  # Focus on news
    )

    await manager.start()
    logger.info("[DEMO 3] Fetching news and sentiment...")
    await asyncio.sleep(3)

    # Show sentiment scores
    for symbol in ["EURUSD", "USDJPY"]:
        snapshot = manager.get_snapshot(symbol)
        sentiment_desc = "NEUTRAL"
        if snapshot.news_sentiment_score < 0.35:
            sentiment_desc = "VERY BEARISH"
        elif snapshot.news_sentiment_score < 0.45:
            sentiment_desc = "BEARISH"
        elif snapshot.news_sentiment_score > 0.65:
            sentiment_desc = "VERY BULLISH"
        elif snapshot.news_sentiment_score > 0.55:
            sentiment_desc = "BULLISH"

        logger.info(
            "[DEMO 3] %s | Sentiment: %s (%.3f) | Risk Impact: %.2f",
            symbol,
            sentiment_desc,
            snapshot.news_sentiment_score,
            snapshot.risk_score,
        )

    await manager.stop()
    logger.info("[DEMO 3] Complete")


async def demo_sentiment_override_logic():
    """Demo 4: Show how sentiment can override trade decisions."""
    print("\n" + "="*80)
    print("DEMO 4: Sentiment-Based Trade Override Logic")
    print("="*80 + "\n")

    logger.info("[DEMO 4] Demonstrating override scenarios:")

    # Scenario 1: Bearish sentiment blocks LONG
    logger.info(
        "[DEMO 4] Scenario 1: Technical LONG signal + BEARISH sentiment"
    )
    logger.info("[DEMO 4]   → Result: BLOCK TRADE (downside risk too high)")

    # Scenario 2: Bullish sentiment blocks SHORT
    logger.info(
        "[DEMO 4] Scenario 2: Technical SHORT signal + BULLISH sentiment"
    )
    logger.info("[DEMO 4]   → Result: BLOCK TRADE (upside risk too high)")

    # Scenario 3: High macro risk + incoming event
    logger.info(
        "[DEMO 4] Scenario 3: Normal signal + High-impact event in 10 min"
    )
    logger.info("[DEMO 4]   → Result: DOWNGRADE to DEFENSIVE_PRESERVATION")
    logger.info("[DEMO 4]   → Action: Tighten trailing stop to 0.3x")

    # Scenario 4: Imminent event
    logger.info(
        "[DEMO 4] Scenario 4: Any signal + High-impact event in 2 min"
    )
    logger.info("[DEMO 4]   → Result: NEWS_SILENCE (no new trades)")
    logger.info("[DEMO 4]   → Action: Tighten trailing stop to 0.1R lock")

    logger.info("[DEMO 4] Complete")


async def demo_rate_limiting():
    """Demo 5: Show rate limiting in action."""
    print("\n" + "="*80)
    print("DEMO 5: Rate Limiting")
    print("="*80 + "\n")

    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.warning("[DEMO 5] Skipped (no API key)")
        return

    manager = FinnhubMacroManager(
        api_key=api_key,
        symbols=["EUR/USD"],
        rate_limit_calls=10,
        rate_limit_window_seconds=60,
    )

    await manager.start()
    logger.info("[DEMO 5] Made rapid API calls - rate limiting in effect")
    logger.info("[DEMO 5] Limit: %d calls per %d seconds",
                manager.rate_limit_calls, manager.rate_limit_window_seconds)
    
    # Simulate multiple rapid calls
    for i in range(3):
        try:
            await manager.refresh_all()
            logger.info("[DEMO 5] Call %d completed", i + 1)
        except Exception as e:
            logger.warning("[DEMO 5] Call %d error: %s", i + 1, str(e)[:50])
        await asyncio.sleep(10)

    await manager.stop()
    logger.info("[DEMO 5] Complete")


async def demo_fallback_mode():
    """Demo 6: Show graceful degradation."""
    print("\n" + "="*80)
    print("DEMO 6: Graceful Degradation (Fallback Mode)")
    print("="*80 + "\n")

    # Use invalid API key to trigger fallback
    manager = FinnhubMacroManager(
        api_key="invalid_key_xyz",
        symbols=["EUR/USD"],
    )

    await manager.start()
    logger.info("[DEMO 6] Started with invalid API key")
    
    if manager._fallback_mode_active:
        logger.warning("[DEMO 6] ✓ Fallback mode activated as expected")
        logger.warning("[DEMO 6] Bot will use llm_macro_monitor defaults (VOLATILITY_NORMAL_FALLBACK)")
        logger.warning("[DEMO 6] Check data/macro_risk_cache.json for fallback values")
    else:
        logger.info("[DEMO 6] Manager still trying to connect")

    await manager.stop()
    logger.info("[DEMO 6] Complete")


async def demo_integration_guide():
    """Demo 7: Show integration code snippets."""
    print("\n" + "="*80)
    print("DEMO 7: Integration Code Snippets")
    print("="*80 + "\n")

    code_snippets = {
        "Initialization": """
# In main.py Phase 4 (after AsyncLLMMacroMonitor):
finnhub_manager = FinnhubMacroManager(
    api_key=os.environ.get("FINNHUB_API_KEY"),
    symbols=symbols,
    macro_risk_cache=macro_risk_cache,
)
await finnhub_manager.start()
        """,

        "Periodic Refresh": """
# In main market loop (every 10 cycles):
if finnhub_manager and cycle_count % 10 == 0:
    await finnhub_manager.refresh_all()
        """,

        "Sentiment Override": """
# In signal evaluation:
snapshot = finnhub_manager.get_snapshot(symbol)
if snapshot.news_sentiment_score < 0.4 and signal.direction == Direction.LONG:
    logger.warning("[OVERRIDE] Blocked LONG due to bearish sentiment")
    signal = None  # Block trade
        """,

        "Dynamic Trailing Stop": """
# In profit protection:
trailing_stop = base_stop
if snapshot.event_minutes_until_high_impact and snapshot.event_minutes_until_high_impact < 10:
    trailing_stop = base_stop * 0.1  # Tighten to 0.1R
        """,
    }

    for title, code in code_snippets.items():
        logger.info("[DEMO 7] %s:\n%s", title, code)

    logger.info("[DEMO 7] Complete")


async def demo_cache_inspection():
    """Demo 8: Inspect macro_risk_cache JSON file."""
    print("\n" + "="*80)
    print("DEMO 8: Cache File Inspection")
    print("="*80 + "\n")

    cache_path = Path("data/macro_risk_cache.json")
    
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                cache_data = json.load(f)
            
            logger.info("[DEMO 8] Cache file contents (data/macro_risk_cache.json):")
            logger.info("[DEMO 8] %s", json.dumps(cache_data, indent=2)[:500])
            logger.info("[DEMO 8] Source: %s | Updated: %s",
                       cache_data.get("source"),
                       cache_data.get("updated_at"))
        except Exception as e:
            logger.warning("[DEMO 8] Could not read cache: %s", str(e))
    else:
        logger.info("[DEMO 8] Cache file not yet created (will be after first run)")

    logger.info("[DEMO 8] Complete")


async def main():
    """Run all demos."""
    print("\n" + "="*80)
    print("FINNHUB_MACROASMANAGER WORKING EXAMPLES")
    print("="*80)

    # Check for API key
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        logger.error("\n❌ FINNHUB_API_KEY environment variable not set!")
        logger.error("Get a free API key at: https://finnhub.io/")
        logger.error("Then set: export FINNHUB_API_KEY=your_key")
        print("\nRunning demos that don't require API key...")
    else:
        logger.info("\n✅ FINNHUB_API_KEY detected")

    try:
        # Run demos
        await demo_basic_initialization()
        await demo_economic_calendar()
        await demo_sentiment_analysis()
        await demo_sentiment_override_logic()
        await demo_rate_limiting()
        await demo_fallback_mode()
        await demo_integration_guide()
        await demo_cache_inspection()

    except Exception as e:
        logger.error("\n❌ Demo failed with error: %s", str(e), exc_info=True)
    
    finally:
        print("\n" + "="*80)
        print("ALL DEMOS COMPLETE")
        print("="*80)
        print("""
NEXT STEPS:
1. Review FINNHUB_INTEGRATION_GUIDE.md for full integration steps
2. Add FINNHUB_API_KEY to your .env file
3. Integrate FinnhubMacroManager into main.py (follow STEP 1-5 in guide)
4. Test with: python test_finnhub_integration.py
5. Monitor logs for [FINNHUB_*] messages in production bot

DOCUMENTATION:
- finns/src/analysis/finnhub_macro_manager.py - Full class documentation
- FINNHUB_INTEGRATION_GUIDE.md - Step-by-step integration
- This file - Working examples and patterns
        """)


if __name__ == "__main__":
    asyncio.run(main())

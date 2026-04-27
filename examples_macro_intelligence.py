"""
Macro Intelligence Integration Examples

This module shows how to integrate the Macro Intelligence Module
with your trading bot and Finnhub data.
"""

from src.analysis.macro_intelligence import (
    validate_macro_signal,
    get_macro_signal_validation,
)
import json


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 1: Simple JSON Output (Best for Logging)
# ═════════════════════════════════════════════════════════════════════════════

def example_simple_logging():
    """
    Generate macro validation in JSON format for logging.
    Perfect for INFO/DEBUG logging to output files.
    """
    print("\n" + "="*70)
    print("EXAMPLE 1: Simple JSON Logging")
    print("="*70)
    
    # This is the easiest way - just get JSON string directly
    json_result = get_macro_signal_validation(
        symbol="EUR/USD",
        technical_signal="LONG",
        finnhub_sentiment=0.72,
        finnhub_events=[],
    )
    
    print(f"\n[MACRO_INTELLIGENCE] EUR/USD LONG validation:")
    print(f"  JSON Output: {json_result}")
    
    # Parse it to show structure
    data = json.loads(json_result)
    print(f"\n  Parsed breakdown:")
    for key, value in data.items():
        print(f"    {key}: {value}")


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 2: Full API with Direct Integration
# ═════════════════════════════════════════════════════════════════════════════

def example_full_api():
    """
    Use the full validation_macro_signal API for advanced control.
    Best when you need direct object access or additional logic.
    """
    print("\n" + "="*70)
    print("EXAMPLE 2: Full API with Direct Object Access")
    print("="*70)
    
    result = validate_macro_signal(
        symbol="GBP/USD",
        technical_signal="SHORT",
        sentiment_score=0.28,  # Bearish - aligns with SHORT
        upcoming_events=[],
    )
    
    print(f"\n[MACRO_INTELLIGENCE] GBP/USD SHORT validation:")
    print(f"  Macro Bias: {result.macro_bias}")
    print(f"  Confidence: {result.macro_confidence}%")
    print(f"  Risk Level: {result.risk_level}")
    print(f"  Volatility Warning: {result.volatility_warning}")
    print(f"  Reasoning: {result.reasoning}")
    
    # Direct conditional logic based on result
    if result.risk_level == "CRITICAL":
        print(f"  → ACTION: Skip this trade - critical risk")
    elif result.macro_confidence < 40:
        print(f"  → ACTION: Reduce position size - low confidence")
    else:
        print(f"  → ACTION: Proceed with trade")


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 3: Real Finnhub Data Integration
# ═════════════════════════════════════════════════════════════════════════════

def example_with_finnhub_data():
    """
    Integration with actual Finnhub data from FinnhubMacroManager.
    This shows how to extract sentiment and events from your existing manager.
    """
    print("\n" + "="*70)
    print("EXAMPLE 3: Integration with Finnhub Data")
    print("="*70)
    
    # This would typically come from your FinnhubMacroManager
    # In your bot, you'd do:
    # 
    #   sentiment = finnhub_manager.get_news_sentiment(symbol)
    #   events = finnhub_manager.get_upcoming_events(symbol)
    #
    # For this example, we simulate the data:
    
    simulated_finnhub_data = {
        "EUR/USD": {
            "sentiment": 0.68,
            "events": [
                {
                    "country": "EUR",
                    "event": "ECB Interest Rate Decision",
                    "date": "2026-05-15T13:00:00Z",
                    "impact": "high",
                    "forecast": "2.50%",
                    "previous": "2.50%",
                },
            ]
        },
        "USD/JPY": {
            "sentiment": 0.42,  # Slightly bearish
            "events": [],
        },
    }
    
    # Example: Validate EUR/USD LONG with Finnhub data
    eur_data = simulated_finnhub_data["EUR/USD"]
    result = validate_macro_signal(
        symbol="EUR/USD",
        technical_signal="LONG",
        sentiment_score=eur_data["sentiment"],
        upcoming_events=eur_data["events"],
    )
    
    print(f"\n[MACRO_INTELLIGENCE] EUR/USD validation with Finnhub data:")
    print(f"  Sentiment: {eur_data['sentiment']}")
    print(f"  Upcoming events: {len(eur_data['events'])} events")
    print(f"  → Result: {result.to_json()}")
    
    # Example: Validate USD/JPY SHORT with Finnhub data
    usd_jpy_data = simulated_finnhub_data["USD/JPY"]
    result = validate_macro_signal(
        symbol="USD/JPY",
        technical_signal="SHORT",
        sentiment_score=usd_jpy_data["sentiment"],
        upcoming_events=usd_jpy_data["events"],
    )
    
    print(f"\n[MACRO_INTELLIGENCE] USD/JPY validation with Finnhub data:")
    print(f"  Sentiment: {usd_jpy_data['sentiment']}")
    print(f"  Upcoming events: {len(usd_jpy_data['events'])} events")
    print(f"  → Result: {result.to_json()}")


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 4: Integration with Trading Signal Flow
# ═════════════════════════════════════════════════════════════════════════════

def example_trading_workflow():
    """
    Shows how macro intelligence fits into your trading signal flow.
    This would be called after your technical analysis generates a signal.
    """
    print("\n" + "="*70)
    print("EXAMPLE 4: Trading Workflow Integration")
    print("="*70)
    
    # Simulated technical analysis output
    technical_signal = {
        "symbol": "AUD/USD",
        "direction": "LONG",
        "entry": 0.6650,
        "sl": 0.6630,
        "tp": 0.6700,
        "confidence": 72,  # ML confidence
    }
    
    # Simulated Finnhub data (from your FinnhubMacroManager)
    finnhub_context = {
        "sentiment": 0.58,  # Slightly bullish
        "events": [],
    }
    
    print(f"\nStep 1: Technical analysis generated signal")
    print(f"  {technical_signal['symbol']} {technical_signal['direction']}")
    print(f"  Entry: {technical_signal['entry']}, SL: {technical_signal['sl']}, TP: {technical_signal['tp']}")
    print(f"  ML Confidence: {technical_signal['confidence']}%")
    
    # Validate with macro intelligence
    print(f"\nStep 2: Validate against macro context")
    macro_result = validate_macro_signal(
        symbol=technical_signal['symbol'],
        technical_signal=technical_signal['direction'],
        sentiment_score=finnhub_context['sentiment'],
        upcoming_events=finnhub_context['events'],
    )
    
    print(f"  Macro validation: {macro_result.to_json()}")
    
    # Step 3: Make final decision
    print(f"\nStep 3: Final trading decision")
    
    combined_confidence = (
        technical_signal['confidence'] * 0.6 +  # 60% weight from technical
        macro_result.macro_confidence * 0.4      # 40% weight from macro
    )
    
    print(f"  Combined confidence: {combined_confidence:.1f}%")
    print(f"  Macro bias: {macro_result.macro_bias}")
    print(f"  Risk level: {macro_result.risk_level}")
    
    if macro_result.risk_level == "CRITICAL":
        print(f"  → DECISION: REJECT trade (critical macro risk)")
    elif combined_confidence > 65:
        print(f"  → DECISION: APPROVE trade (high combined confidence)")
    elif combined_confidence > 50:
        print(f"  → DECISION: APPROVE with reduced sizing")
    else:
        print(f"  → DECISION: REJECT trade (low combined confidence)")


# ═════════════════════════════════════════════════════════════════════════════
# EXAMPLE 5: Batch Processing Multiple Pairs
# ═════════════════════════════════════════════════════════════════════════════

def example_batch_processing():
    """
    Process multiple currency pairs efficiently.
    Shows how to generate macro context for all your monitored pairs.
    """
    print("\n" + "="*70)
    print("EXAMPLE 5: Batch Processing Multiple Pairs")
    print("="*70)
    
    # Your monitored pairs with generated signals
    signals = [
        {"symbol": "EUR/USD", "signal": "LONG", "finnhub_sentiment": 0.65},
        {"symbol": "GBP/USD", "signal": "SHORT", "finnhub_sentiment": 0.32},
        {"symbol": "USD/JPY", "signal": "LONG", "finnhub_sentiment": 0.72},
        {"symbol": "USD/CHF", "signal": "SHORT", "finnhub_sentiment": 0.28},
        {"symbol": "AUD/USD", "signal": "LONG", "finnhub_sentiment": 0.55},
        {"symbol": "USD/CAD", "signal": "SHORT", "finnhub_sentiment": 0.35},
        {"symbol": "NZD/USD", "signal": "LONG", "finnhub_sentiment": 0.60},
    ]
    
    print(f"\nValidating {len(signals)} pairs:\n")
    
    results = []
    for sig in signals:
        result = validate_macro_signal(
            symbol=sig['symbol'],
            technical_signal=sig['signal'],
            sentiment_score=sig['finnhub_sentiment'],
            upcoming_events=[],
        )
        results.append(result)
        
        # Print summary line
        print(f"  {sig['symbol']:10} | Signal: {sig['signal']:5} | "
              f"Macro: {result.macro_bias:6} | Conf: {result.macro_confidence:3}% | "
              f"Risk: {result.risk_level:8} | Vol: {str(result.volatility_warning):5}")
    
    # Statistics
    critical_count = sum(1 for r in results if r.risk_level == "CRITICAL")
    high_conf_count = sum(1 for r in results if r.macro_confidence >= 65)
    
    print(f"\nSummary:")
    print(f"  Critical risk pairs: {critical_count}")
    print(f"  High confidence pairs: {high_conf_count}")


if __name__ == "__main__":
    print("\n" + "█"*70)
    print("█" + " "*68 + "█")
    print("█" + "  MACRO INTELLIGENCE MODULE - INTEGRATION EXAMPLES".center(68) + "█")
    print("█" + " "*68 + "█")
    print("█"*70)
    
    example_simple_logging()
    example_full_api()
    example_with_finnhub_data()
    example_trading_workflow()
    example_batch_processing()
    
    print("\n" + "█"*70)
    print("█" + "  All examples completed successfully ✓".center(68) + "█")
    print("█"*70 + "\n")

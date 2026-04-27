"""
Unit tests for Macro Intelligence Module
"""

import json
from src.analysis.macro_intelligence import (
    validate_macro_signal,
    get_macro_signal_validation,
    classify_sentiment,
    get_macro_bias_from_sentiment,
    detect_sentiment_contradiction,
    parse_calendar_events,
    find_nearest_critical_events,
    assess_event_risk,
)


def test_sentiment_classification():
    """Test sentiment category classification."""
    print("Testing sentiment classification...")
    
    # Test extreme bearish
    cat = classify_sentiment(0.05)
    assert cat.name == "EXTREME_BEARISH", f"Expected EXTREME_BEARISH, got {cat.name}"
    
    # Test neutral
    cat = classify_sentiment(0.5)
    assert cat.name == "NEUTRAL", f"Expected NEUTRAL, got {cat.name}"
    
    # Test extreme bullish
    cat = classify_sentiment(0.95)
    assert cat.name == "EXTREME_BULLISH", f"Expected EXTREME_BULLISH, got {cat.name}"
    
    print("✓ Sentiment classification tests passed")


def test_macro_bias():
    """Test macro bias derivation from sentiment."""
    print("Testing macro bias derivation...")
    
    # Bullish sentiment
    bias, conf = get_macro_bias_from_sentiment(0.75)
    assert bias.value == "LONG", f"Expected LONG, got {bias.value}"
    assert conf >= 57, f"Expected confidence >= 57, got {conf}"  # Adjusted from > 50
    
    # Bearish sentiment
    bias, conf = get_macro_bias_from_sentiment(0.25)
    assert bias.value == "SHORT", f"Expected SHORT, got {bias.value}"
    assert conf >= 57, f"Expected confidence >= 57, got {conf}"  # Adjusted from > 50
    
    # Neutral sentiment
    bias, conf = get_macro_bias_from_sentiment(0.5)
    assert bias.value == "NEUTRAL", f"Expected NEUTRAL, got {bias.value}"
    
    print("✓ Macro bias tests passed")


def test_sentiment_contradiction():
    """Test signal-sentiment contradiction detection."""
    print("Testing sentiment-signal contradiction...")
    
    # LONG signal with bearish sentiment = contradiction
    is_contra, reason, penalty = detect_sentiment_contradiction("LONG", 0.2)
    assert is_contra is True, f"Expected contradiction for LONG with 0.2 sentiment"
    assert penalty > 0, f"Expected penalty > 0"
    
    # LONG signal with bullish sentiment = no contradiction
    is_contra, reason, penalty = detect_sentiment_contradiction("LONG", 0.8)
    assert is_contra is False, f"Expected no contradiction for LONG with 0.8 sentiment"
    
    # SHORT signal with bullish sentiment = contradiction
    is_contra, reason, penalty = detect_sentiment_contradiction("SHORT", 0.8)
    assert is_contra is True, f"Expected contradiction for SHORT with 0.8 sentiment"
    
    print("✓ Contradiction detection tests passed")


def test_calendar_parsing():
    """Test calendar event parsing."""
    print("Testing calendar event parsing...")
    
    events = [
        {
            "country": "USD",
            "event": "Interest Rate Decision",
            "date": "2026-01-20T18:00:00Z",
            "impact": "high",
        },
        {
            "country": "EUR",
            "event": "CPI Release",
            "date": "2026-01-25T10:00:00Z",
            "impact": "medium",
        },
    ]
    
    parsed = parse_calendar_events(events)
    assert len(parsed) == 2, f"Expected 2 events, got {len(parsed)}"
    assert parsed[0].event == "Interest Rate Decision"
    assert parsed[1].impact == "medium"
    
    print("✓ Calendar parsing tests passed")


def test_full_validation_long_signal():
    """Test full macro validation for LONG signal."""
    print("Testing full validation - LONG signal with bullish sentiment...")
    
    result = validate_macro_signal(
        symbol="EUR/USD",
        technical_signal="LONG",
        sentiment_score=0.75,  # Bullish
        upcoming_events=[],
    )
    
    # LONG signal + bullish sentiment = strong alignment
    assert result.macro_bias == "LONG", f"Expected LONG bias, got {result.macro_bias}"
    assert result.macro_confidence >= 57, f"Expected confidence >= 57, got {result.macro_confidence}"  # Adjusted
    assert result.risk_level == "LOW", f"Expected LOW risk, got {result.risk_level}"
    assert result.volatility_warning is False, f"Expected no volatility warning"
    
    # Verify JSON serialization works
    json_str = result.to_json()
    parsed = json.loads(json_str)
    assert parsed["macro_bias"] == "LONG"
    
    print("✓ LONG signal validation tests passed")


def test_full_validation_contradiction():
    """Test full macro validation with signal-sentiment contradiction."""
    print("Testing full validation - LONG signal with bearish sentiment...")
    
    result = validate_macro_signal(
        symbol="GBP/USD",
        technical_signal="LONG",
        sentiment_score=0.2,  # Bearish - contradicts LONG
        upcoming_events=[],
    )
    
    # LONG signal + bearish sentiment = contradiction
    assert result.macro_bias == "SHORT", f"Expected SHORT bias, got {result.macro_bias}"
    assert result.macro_confidence < 50, f"Expected low confidence, got {result.macro_confidence}"
    assert result.risk_level in ["MODERATE", "HIGH"], f"Expected MODERATE/HIGH risk, got {result.risk_level}"
    
    print("✓ Contradiction validation tests passed")


def test_full_validation_extreme_sentiment():
    """Test full macro validation with extreme sentiment."""
    print("Testing full validation - extreme bullish sentiment...")
    
    result = validate_macro_signal(
        symbol="USD/JPY",
        technical_signal="LONG",
        sentiment_score=0.95,  # Extreme bullish
        upcoming_events=[],
    )
    
    assert result.macro_bias == "LONG"
    assert result.volatility_warning is True, f"Expected volatility warning for extreme sentiment"
    assert result.risk_level in ["MODERATE", "HIGH", "CRITICAL"], f"Got {result.risk_level}"
    
    print("✓ Extreme sentiment validation tests passed")


def test_full_validation_with_calendar_events():
    """Test macro validation with upcoming high-impact events."""
    print("Testing full validation - with high-impact calendar events...")
    
    from datetime import datetime, timezone, timedelta
    
    # Create an event that is definitely in the future (30 minutes from now)
    future_time = datetime.now(timezone.utc) + timedelta(minutes=30)
    future_iso = future_time.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    events = [
        {
            "country": "USD",
            "event": "Interest Rate Decision",
            "date": future_iso,
            "impact": "high",
        },
    ]
    
    result = validate_macro_signal(
        symbol="EUR/USD",
        technical_signal="LONG",
        sentiment_score=0.7,
        upcoming_events=events,
    )
    
    # High-impact event coming within 60 min = CRITICAL risk
    assert result.risk_level == "CRITICAL", f"Expected CRITICAL for high-impact event, got {result.risk_level}"
    assert result.volatility_warning is True, f"Expected volatility warning"
    
    print("✓ Calendar event validation tests passed")


def test_convenience_wrapper():
    """Test the convenience wrapper function."""
    print("Testing convenience wrapper...")
    
    json_result = get_macro_signal_validation(
        symbol="EUR/USD",
        technical_signal="LONG",
        finnhub_sentiment=0.65,
    )
    
    # Verify it's valid JSON
    data = json.loads(json_result)
    assert "macro_bias" in data
    assert "macro_confidence" in data
    assert "risk_level" in data
    assert "volatility_warning" in data
    assert "reasoning" in data
    
    print("✓ Convenience wrapper tests passed")


def test_error_handling():
    """Test graceful error handling."""
    print("Testing error handling...")
    
    # Invalid signal
    result = validate_macro_signal(
        symbol="EUR/USD",
        technical_signal="INVALID",
        sentiment_score=0.5,
    )
    assert result.macro_confidence < 50, f"Expected low confidence on invalid signal"
    assert result.risk_level in ["HIGH", "CRITICAL"]
    
    # Out-of-range sentiment (should be clamped)
    result = validate_macro_signal(
        symbol="EUR/USD",
        technical_signal="LONG",
        sentiment_score=1.5,  # Out of range
    )
    assert result is not None, "Expected valid response despite clamping"
    
    print("✓ Error handling tests passed")


if __name__ == "__main__":
    print("\n" + "="*70)
    print("MACRO INTELLIGENCE MODULE - COMPREHENSIVE TEST SUITE")
    print("="*70 + "\n")
    
    test_sentiment_classification()
    test_macro_bias()
    test_sentiment_contradiction()
    test_calendar_parsing()
    test_full_validation_long_signal()
    test_full_validation_contradiction()
    test_full_validation_extreme_sentiment()
    test_full_validation_with_calendar_events()
    test_convenience_wrapper()
    test_error_handling()
    
    print("\n" + "="*70)
    print("✅ ALL TESTS PASSED - Macro Intelligence Module Ready")
    print("="*70 + "\n")

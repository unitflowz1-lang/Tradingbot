"""
Macro Intelligence Module - Signal Validation via Finnhub Real-Time Data

Validates trading signals against macro-economic context by analyzing:
1. Real-time news sentiment (0.0-1.0 scale)
2. Upcoming high-impact calendar events (Interest Rate, CPI, NFP)
3. Volatility warnings from sentiment extremes
4. Macro bias alignment with technical signal direction

Contract:
- Input: Technical signal (LONG/SHORT), symbol, Finnhub data
- Output: Valid JSON with macro_bias, macro_confidence, risk_level, volatility_warning, reasoning
- On any error: Return graceful JSON with NEUTRAL bias and reduced confidence
- All responses are JSON only (no conversational text)

Risk Level Rules:
1. CRITICAL: High-impact event within 60 minutes OR extreme sentiment (>0.9 or <0.1)
2. HIGH: Moderate-impact event within 4 hours OR strong sentiment contradiction (0.2-0.35 or 0.65-0.8)
3. MODERATE: Low-impact event within 24 hours OR mild sentiment misalignment
4. LOW: No events upcoming or sentiment aligns with signal

Volatility Warning: Triggered if upcoming events or extreme sentiment conditions detected
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# ENUMS & CONSTANTS
# ═════════════════════════════════════════════════════════════════════════════

class MacroBias(Enum):
    """Macro context alignment with signal direction."""
    LONG = "LONG"
    SHORT = "SHORT"
    NEUTRAL = "NEUTRAL"


class RiskLevel(Enum):
    """Risk assessment based on macro events and sentiment."""
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SentimentCategory(Enum):
    """Sentiment classification from 0.0-1.0 score."""
    EXTREME_BEARISH = (0.0, 0.1)    # <0.1
    VERY_BEARISH = (0.1, 0.25)      # 0.1-0.25
    BEARISH = (0.25, 0.4)           # 0.25-0.4
    SLIGHTLY_BEARISH = (0.4, 0.45)  # 0.4-0.45
    NEUTRAL = (0.45, 0.55)          # 0.45-0.55
    SLIGHTLY_BULLISH = (0.55, 0.6)  # 0.55-0.6
    BULLISH = (0.6, 0.75)           # 0.6-0.75
    VERY_BULLISH = (0.75, 0.9)      # 0.75-0.9
    EXTREME_BULLISH = (0.9, 1.0)    # >0.9


class EventImpact(Enum):
    """Finnhub calendar event impact level."""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


# Event thresholds (minutes until event)
HIGH_IMPACT_THRESHOLD_MIN = 60      # High-impact events within 60 min = CRITICAL risk
MEDIUM_IMPACT_THRESHOLD_MIN = 240   # Medium-impact events within 4 hours = HIGH risk
LOW_IMPACT_THRESHOLD_MIN = 1440     # Low-impact events within 24 hours = MODERATE risk

# Sentiment boundaries for risk assessment
EXTREME_SENTIMENT_THRESHOLD = (0.1, 0.9)  # Triggers volatility warning
CONTRADICTION_STRONG_THRESHOLD = (0.2, 0.35, 0.65, 0.8)  # Strong contradiction
CONTRADICTION_MILD_THRESHOLD = (0.3, 0.45, 0.55, 0.7)    # Mild contradiction


@dataclass
class CalendarEvent:
    """Structured calendar event from Finnhub."""
    country: str
    event: str
    date: str
    impact: str  # "high", "medium", "low"
    forecast: Optional[str] = None
    previous: Optional[str] = None
    unit: Optional[str] = None
    
    def minutes_until_event(self) -> Optional[int]:
        """Calculate minutes until this event occurs."""
        try:
            # Parse ISO format: "2024-01-15T14:30:00Z"
            event_dt = datetime.fromisoformat(self.date.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            delta = (event_dt - now).total_seconds() / 60
            return int(delta) if delta > 0 else None
        except Exception as e:
            logger.warning(f"[MACRO_INTELLIGENCE] Failed to parse event date {self.date}: {e}")
            return None


@dataclass
class MacroSignalInput:
    """Input signal and market context for macro validation."""
    symbol: str
    technical_signal: str  # "LONG" or "SHORT"
    sentiment_score: float  # 0.0-1.0 from Finnhub
    upcoming_events: List[Dict[str, Any]] = None  # Finnhub calendar events
    headlines: List[str] = None  # Recent news headlines
    volatility_pct: float = 0.0  # Current volatility
    
    def __post_init__(self):
        if self.upcoming_events is None:
            self.upcoming_events = []
        if self.headlines is None:
            self.headlines = []


@dataclass
class MacroIntelligenceOutput:
    """JSON-serializable macro validation result."""
    macro_bias: str  # "LONG" | "SHORT" | "NEUTRAL"
    macro_confidence: int  # 0-100
    risk_level: str  # "LOW" | "MODERATE" | "HIGH" | "CRITICAL"
    volatility_warning: bool
    reasoning: str
    
    def to_json(self) -> str:
        """Serialize to valid JSON string (single-line for logging)."""
        data = {
            "macro_bias": self.macro_bias,
            "macro_confidence": self.macro_confidence,
            "risk_level": self.risk_level,
            "volatility_warning": self.volatility_warning,
            "reasoning": self.reasoning,
        }
        return json.dumps(data, separators=(",", ":"))
    
    def to_dict(self) -> Dict[str, Any]:
        """Return as dictionary."""
        return {
            "macro_bias": self.macro_bias,
            "macro_confidence": self.macro_confidence,
            "risk_level": self.risk_level,
            "volatility_warning": self.volatility_warning,
            "reasoning": self.reasoning,
        }


# ═════════════════════════════════════════════════════════════════════════════
# SENTIMENT ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def classify_sentiment(sentiment_score: float) -> SentimentCategory:
    """Classify sentiment score into category."""
    if sentiment_score < 0.1:
        return SentimentCategory.EXTREME_BEARISH
    elif sentiment_score < 0.25:
        return SentimentCategory.VERY_BEARISH
    elif sentiment_score < 0.4:
        return SentimentCategory.BEARISH
    elif sentiment_score < 0.45:
        return SentimentCategory.SLIGHTLY_BEARISH
    elif sentiment_score < 0.55:
        return SentimentCategory.NEUTRAL
    elif sentiment_score < 0.6:
        return SentimentCategory.SLIGHTLY_BULLISH
    elif sentiment_score < 0.75:
        return SentimentCategory.BULLISH
    elif sentiment_score < 0.9:
        return SentimentCategory.VERY_BULLISH
    else:
        return SentimentCategory.EXTREME_BULLISH


def get_macro_bias_from_sentiment(sentiment_score: float) -> Tuple[MacroBias, int]:
    """
    Derive macro bias direction and confidence from sentiment score.
    
    Returns:
        Tuple of (MacroBias, confidence_pct)
        - Confidence based on distance from neutral (0.5)
        - Maximum confidence: 85% (never 100% on sentiment alone)
    """
    distance_from_neutral = abs(sentiment_score - 0.5)
    
    # Confidence increases with distance from neutral
    # Maps distance [0, 0.5] → confidence [30, 85]
    # At 0.25 distance: 30 + (0.25/0.5) * 55 = 57.5
    # At 0.5 distance: 30 + (0.5/0.5) * 55 = 85
    base_confidence = min(int(30 + (distance_from_neutral / 0.5) * 55), 85)
    
    if sentiment_score > 0.55:
        return MacroBias.LONG, base_confidence
    elif sentiment_score < 0.45:
        return MacroBias.SHORT, base_confidence
    else:
        return MacroBias.NEUTRAL, 40  # Neutral area: low confidence


def detect_sentiment_contradiction(
    technical_signal: str,
    sentiment_score: float
) -> Tuple[bool, str, int]:
    """
    Check if sentiment contradicts technical signal.
    
    Returns:
        Tuple of (is_contradiction, description, confidence_penalty)
    """
    sentiment_cat = classify_sentiment(sentiment_score)
    
    if technical_signal == "LONG":
        # LONG signals contradict bearish sentiment
        if sentiment_score < 0.35:
            return True, "Strong bearish sentiment contradicts LONG signal", 15
        elif sentiment_score < 0.45:
            return True, "Mild bearish sentiment contradicts LONG signal", 5
    elif technical_signal == "SHORT":
        # SHORT signals contradict bullish sentiment
        if sentiment_score > 0.65:
            return True, "Strong bullish sentiment contradicts SHORT signal", 15
        elif sentiment_score > 0.55:
            return True, "Mild bullish sentiment contradicts SHORT signal", 5
    
    return False, "", 0


# ═════════════════════════════════════════════════════════════════════════════
# CALENDAR EVENT ANALYSIS
# ═════════════════════════════════════════════════════════════════════════════

def parse_calendar_events(events: List[Dict[str, Any]]) -> List[CalendarEvent]:
    """Convert Finnhub calendar events to structured format."""
    parsed = []
    for event in events:
        try:
            parsed.append(CalendarEvent(
                country=event.get("country", ""),
                event=event.get("event", ""),
                date=event.get("date", ""),
                impact=event.get("impact", "low").lower(),
                forecast=event.get("forecast"),
                previous=event.get("previous"),
                unit=event.get("unit"),
            ))
        except Exception as e:
            logger.warning(f"[MACRO_INTELLIGENCE] Failed to parse event: {e}")
    return parsed


def find_nearest_critical_events(
    events: List[CalendarEvent]
) -> Tuple[List[CalendarEvent], List[CalendarEvent], List[CalendarEvent]]:
    """
    Partition events by impact level and proximity.
    
    Returns:
        Tuple of (high_impact_events, medium_impact_events, low_impact_events)
        where each list is sorted by proximity (nearest first)
    """
    high = []
    medium = []
    low = []
    
    for event in events:
        minutes = event.minutes_until_event()
        if minutes is None or minutes < 0:
            continue  # Event already passed
        
        event_data = (minutes, event)
        if event.impact == "high":
            high.append(event_data)
        elif event.impact == "medium":
            medium.append(event_data)
        else:
            low.append(event_data)
    
    # Sort by proximity
    high.sort(key=lambda x: x[0])
    medium.sort(key=lambda x: x[0])
    low.sort(key=lambda x: x[0])
    
    return [e[1] for e in high], [e[1] for e in medium], [e[1] for e in low]


def assess_event_risk(
    high_events: List[CalendarEvent],
    medium_events: List[CalendarEvent],
    low_events: List[CalendarEvent]
) -> Tuple[RiskLevel, bool, str]:
    """
    Assess risk level based on upcoming events.
    
    Returns:
        Tuple of (risk_level, volatility_warning, description)
    """
    # Check high-impact events within threshold
    if high_events:
        nearest = high_events[0]
        minutes = nearest.minutes_until_event()
        if minutes and minutes <= HIGH_IMPACT_THRESHOLD_MIN:
            return RiskLevel.CRITICAL, True, f"HIGH-IMPACT event '{nearest.event}' in {minutes} min"
    
    # Check medium-impact events within threshold
    if medium_events:
        nearest = medium_events[0]
        minutes = nearest.minutes_until_event()
        if minutes and minutes <= MEDIUM_IMPACT_THRESHOLD_MIN:
            return RiskLevel.HIGH, True, f"MEDIUM-IMPACT event '{nearest.event}' in {minutes} min"
    
    # Check low-impact events within threshold
    if low_events:
        nearest = low_events[0]
        minutes = nearest.minutes_until_event()
        if minutes and minutes <= LOW_IMPACT_THRESHOLD_MIN:
            return RiskLevel.MODERATE, False, f"LOW-IMPACT event '{nearest.event}' in {minutes} min"
    
    # No upcoming events within thresholds
    return RiskLevel.LOW, False, "No high-impact events within risk windows"


def detect_extreme_sentiment_volatility(sentiment_score: float) -> Tuple[bool, str]:
    """
    Detect extreme sentiment conditions that warrant volatility warning.
    
    Returns:
        Tuple of (has_warning, description)
    """
    if sentiment_score > 0.9:
        return True, "Extreme bullish sentiment (>0.9) - high volatility risk"
    elif sentiment_score < 0.1:
        return True, "Extreme bearish sentiment (<0.1) - high volatility risk"
    return False, ""


# ═════════════════════════════════════════════════════════════════════════════
# MAIN VALIDATION ENGINE
# ═════════════════════════════════════════════════════════════════════════════

def validate_macro_signal(
    symbol: str,
    technical_signal: str,
    sentiment_score: float,
    upcoming_events: Optional[List[Dict[str, Any]]] = None,
    headlines: Optional[List[str]] = None,
) -> MacroIntelligenceOutput:
    """
    Core macro intelligence validation engine.
    
    Validates trading signal against macro-economic context:
    1. Analyzes sentiment alignment with signal direction
    2. Checks for nearby high-impact calendar events
    3. Detects extreme volatility conditions
    4. Returns structured JSON-compatible decision
    
    Args:
        symbol: Trading pair (e.g., "EUR/USD")
        technical_signal: "LONG" or "SHORT"
        sentiment_score: Finnhub sentiment (0.0-1.0)
        upcoming_events: List of Finnhub calendar events
        headlines: List of recent news headlines (informational)
    
    Returns:
        MacroIntelligenceOutput with JSON-serializable fields
    """
    try:
        # Validate inputs
        if technical_signal not in ("LONG", "SHORT"):
            logger.error(f"[MACRO_INTELLIGENCE] Invalid signal: {technical_signal}")
            return MacroIntelligenceOutput(
                macro_bias="NEUTRAL",
                macro_confidence=30,
                risk_level="HIGH",
                volatility_warning=True,
                reasoning="Invalid technical signal provided"
            )
        
        # Clamp sentiment to valid range
        sentiment_score = max(0.0, min(1.0, sentiment_score))
        
        # ───────────────────────────────────────────────────────────────
        # 1. SENTIMENT ANALYSIS
        # ───────────────────────────────────────────────────────────────
        macro_bias, sentiment_confidence = get_macro_bias_from_sentiment(sentiment_score)
        
        # Check for sentiment-signal contradiction
        contradiction, contradiction_reason, contradiction_penalty = detect_sentiment_contradiction(
            technical_signal, sentiment_score
        )
        
        # Check for extreme sentiment volatility
        extreme_vol, extreme_vol_reason = detect_extreme_sentiment_volatility(sentiment_score)
        
        # ───────────────────────────────────────────────────────────────
        # 2. CALENDAR EVENT ANALYSIS
        # ───────────────────────────────────────────────────────────────
        event_risk = RiskLevel.LOW
        event_volatility_warning = False
        event_reason = "No high-impact events"
        
        if upcoming_events:
            try:
                parsed_events = parse_calendar_events(upcoming_events)
                high, medium, low = find_nearest_critical_events(parsed_events)
                event_risk, event_volatility_warning, event_reason = assess_event_risk(
                    high, medium, low
                )
            except Exception as e:
                logger.warning(f"[MACRO_INTELLIGENCE] Error parsing calendar events: {e}")
        
        # ───────────────────────────────────────────────────────────────
        # 3. COMBINE SENTIMENT + CALENDAR RISK
        # ───────────────────────────────────────────────────────────────
        
        # Determine overall risk level
        # Calendar event risk takes precedence
        if event_risk == RiskLevel.CRITICAL:
            overall_risk = RiskLevel.CRITICAL
        elif event_risk == RiskLevel.HIGH:
            overall_risk = RiskLevel.HIGH
        elif event_risk == RiskLevel.MODERATE:
            overall_risk = RiskLevel.MODERATE
        elif extreme_vol or (contradiction and sentiment_score in [s for r in [CONTRADICTION_STRONG_THRESHOLD] for s in (r[0], r[2])]):
            # Extreme sentiment or strong contradiction → at least MODERATE
            overall_risk = RiskLevel.MODERATE
        else:
            overall_risk = RiskLevel.LOW
        
        # Volatility warning from either events or extreme sentiment
        volatility_warning = event_volatility_warning or extreme_vol
        
        # ───────────────────────────────────────────────────────────────
        # 4. CALCULATE FINAL CONFIDENCE
        # ───────────────────────────────────────────────────────────────
        
        base_confidence = sentiment_confidence
        
        # Apply contradiction penalty
        if contradiction:
            base_confidence = max(20, base_confidence - contradiction_penalty)
        
        # Apply critical risk penalty
        if overall_risk == RiskLevel.CRITICAL:
            base_confidence = max(10, base_confidence - 30)
        elif overall_risk == RiskLevel.HIGH:
            base_confidence = max(20, base_confidence - 20)
        elif overall_risk == RiskLevel.MODERATE:
            base_confidence = max(30, base_confidence - 10)
        
        # Ensure confidence is in valid range
        final_confidence = max(0, min(100, int(base_confidence)))
        
        # ───────────────────────────────────────────────────────────────
        # 5. BUILD REASONING STRING
        # ───────────────────────────────────────────────────────────────
        
        reasoning_parts = []
        
        # Sentiment component
        sentiment_cat = classify_sentiment(sentiment_score)
        reasoning_parts.append(f"Sentiment: {sentiment_cat.name} ({sentiment_score:.2f})")
        
        if macro_bias == MacroBias.LONG:
            reasoning_parts.append("→ Bullish macro bias")
        elif macro_bias == MacroBias.SHORT:
            reasoning_parts.append("→ Bearish macro bias")
        else:
            reasoning_parts.append("→ Neutral macro bias")
        
        # Signal alignment
        if contradiction:
            reasoning_parts.append(f"⚠ {contradiction_reason}")
        else:
            reasoning_parts.append(f"✓ {technical_signal} signal aligned with sentiment")
        
        # Calendar events
        reasoning_parts.append(f"Events: {event_reason}")
        
        # Extreme conditions
        if extreme_vol:
            reasoning_parts.append(f"⚠ {extreme_vol_reason}")
        
        # Risk summary
        reasoning_parts.append(f"Risk: {overall_risk.value}")
        
        reasoning = " | ".join(reasoning_parts)
        
        # ───────────────────────────────────────────────────────────────
        # 6. BUILD RESPONSE
        # ───────────────────────────────────────────────────────────────
        
        return MacroIntelligenceOutput(
            macro_bias=macro_bias.value,
            macro_confidence=final_confidence,
            risk_level=overall_risk.value,
            volatility_warning=volatility_warning,
            reasoning=reasoning
        )
    
    except Exception as e:
        logger.critical(f"[MACRO_INTELLIGENCE] Unexpected error: {e}", exc_info=True)
        # Graceful fallback: neutral bias, reduced confidence
        return MacroIntelligenceOutput(
            macro_bias="NEUTRAL",
            macro_confidence=30,
            risk_level="HIGH",
            volatility_warning=True,
            reasoning=f"Macro intelligence error: {str(e)[:50]}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# CONVENIENCE WRAPPER FOR INTEGRATION
# ═════════════════════════════════════════════════════════════════════════════

def get_macro_signal_validation(
    symbol: str,
    technical_signal: str,
    finnhub_sentiment: float,
    finnhub_events: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Convenience function that returns JSON string directly.
    
    Perfect for logging and integration with decision systems.
    
    Args:
        symbol: Trading pair
        technical_signal: "LONG" or "SHORT"
        finnhub_sentiment: 0.0-1.0 sentiment score
        finnhub_events: Finnhub calendar events
    
    Returns:
        JSON string with macro validation result
    """
    result = validate_macro_signal(
        symbol=symbol,
        technical_signal=technical_signal,
        sentiment_score=finnhub_sentiment,
        upcoming_events=finnhub_events or [],
    )
    return result.to_json()

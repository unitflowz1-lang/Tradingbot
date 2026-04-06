"""
Market Mode Detector
Automatically detects whether market is in TREND or RANGE mode based on ADX.
Used to switch between TrendStrategy and RangeStrategy.
"""

import logging
import os
from typing import Literal
from datetime import datetime, timezone
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class MarketModeDecision:
    """Result of market mode detection"""
    mode: Literal["TREND", "RANGE"]
    adx_value: float
    threshold: float
    confidence: float  # How confident in the detection (0-1)
    reasoning: str
    timestamp: datetime


class MarketModeDetector:
    """
    Detects market mode (TREND vs RANGE) based on ADX and other indicators.
    
    **Fix 5B Implementation:**
    - When ADX < threshold → RANGE mode (use RangeStrategy)
    - When ADX >= threshold → TREND mode (use TrendStrategy)
    
    This allows automatic strategy switching without manual intervention.
    """
    
    def __init__(self, range_mode_threshold: float = 15.0):
        """
        Initialize market mode detector.
        
        Args:
            range_mode_threshold: ADX below this value triggers RANGE mode (default: 15.0)
        """
        self.range_mode_threshold = float(
            os.environ.get("RANGE_MODE_ADX_THRESHOLD", str(range_mode_threshold))
        )
        logger.info(
            "[MARKET_MODE_DETECTOR] Initialized with RANGE threshold: %.1f",
            self.range_mode_threshold
        )
    
    def detect_mode(
        self,
        adx: float,
        additional_context: dict = None
    ) -> MarketModeDecision:
        """
        Detect current market mode based on ADX.
        
        Args:
            adx: Current ADX value (0-100)
            additional_context: Optional dict with other indicators:
                - rsi: Current RSI (0-100) for confirmation
                - chop: Current CHOP index (0-100)
                - atr: Current ATR for volatility
                - bb_width: Bollinger Band width for squeeze detection
        
        Returns:
            MarketModeDecision with mode, confidence, and reasoning
        """
        context = additional_context or {}
        
        # Core: ADX-based mode detection
        if adx < self.range_mode_threshold:
            base_mode = "RANGE"
            base_confidence = max(0.5, 1.0 - (adx / self.range_mode_threshold))  # Higher confidence when ADX very low
        else:
            base_mode = "TREND"
            base_confidence = min(1.0, (adx - self.range_mode_threshold) / (50.0 - self.range_mode_threshold))  # Higher confidence when ADX high
        
        # Optional: Confirm with CHOP index (if provided)
        chop = context.get("chop")
        if chop is not None:
            # CHOP > 61.8: choppy/ranging market
            # CHOP < 38.2: trending market
            chop_mode = "RANGE" if chop > 61.8 else ("TREND" if chop < 38.2 else None)
            if chop_mode:
                mode_match = chop_mode == base_mode
                if mode_match:
                    base_confidence = min(1.0, base_confidence + 0.15)  # Boost confidence
                else:
                    base_confidence = max(0.3, base_confidence - 0.10)  # Reduce confidence
        
        # Optional: Double check with RSI extremes (high/low bound usage indicates ranging)
        rsi = context.get("rsi")
        if rsi is not None:
            rsi_in_extreme = (rsi < 30.0) or (rsi > 70.0)
            if base_mode == "RANGE" and rsi_in_extreme:
                base_confidence = min(1.0, base_confidence + 0.10)  # Confirms range extremes
            elif base_mode == "TREND" and not rsi_in_extreme:
                base_confidence = min(1.0, base_confidence + 0.05)  # Confirms trending behavior
        
        # Build reasoning
        reasoning = self._build_reasoning(
            adx=adx,
            mode=base_mode,
            threshold=self.range_mode_threshold,
            chop=chop,
            rsi=rsi
        )
        
        decision = MarketModeDecision(
            mode=base_mode,
            adx_value=adx,
            threshold=self.range_mode_threshold,
            confidence=base_confidence,
            reasoning=reasoning,
            timestamp=datetime.now(timezone.utc)
        )
        
        logger.info(
            "[MARKET_MODE] %s mode detected (ADX=%.1f, Confidence=%.1f%%) | %s",
            decision.mode,
            adx,
            (decision.confidence * 100),
            reasoning
        )
        
        return decision
    
    def _build_reasoning(
        self,
        adx: float,
        mode: str,
        threshold: float,
        chop: float = None,
        rsi: float = None
    ) -> str:
        """Build human-readable reasoning string"""
        parts = []
        
        # ADX-based reasoning
        if mode == "RANGE":
            if adx < 5.0:
                parts.append("ADX very weak (<5) - strong ranging signal")
            elif adx < threshold:
                parts.append(f"ADX {adx:.1f} below threshold {threshold:.1f}")
        else:
            if adx > 40.0:
                parts.append("ADX very strong (>40) - strong trending signal")
            else:
                parts.append(f"ADX {adx:.1f} above threshold {threshold:.1f}")
        
        # CHOP confirmation
        if chop is not None:
            if chop > 61.8:
                parts.append(f"CHOP {chop:.1f} confirms choppy/ranging")
            elif chop < 38.2:
                parts.append(f"CHOP {chop:.1f} confirms directional/trending")
        
        # RSI assessment
        if rsi is not None:
            if rsi < 30.0:
                parts.append(f"RSI {rsi:.0f} oversold (range entry signal)")
            elif rsi > 70.0:
                parts.append(f"RSI {rsi:.0f} overbought (range entry signal)")
            else:
                parts.append(f"RSI {rsi:.0f} mid-range (no extreme signal)")
        
        return " | ".join(parts) if parts else "Standard market conditions"
    
    def get_strategy_recommendation(self, adx: float, additional_context: dict = None) -> str:
        """
        Get strategy recommendation based on market mode.
        
        Returns:
            "TREND_STRATEGY" or "RANGE_STRATEGY"
        """
        decision = self.detect_mode(adx, additional_context)
        
        if decision.mode == "RANGE":
            return "RANGE_STRATEGY"
        else:
            return "TREND_STRATEGY"
    
    def should_switch_strategy(
        self,
        current_strategy: str,
        adx: float,
        hysteresis_threshold: float = 1.5
    ) -> tuple[bool, str]:
        """
        Determine if strategy switch is needed with hysteresis to prevent flip-flopping.
        
        Args:
            current_strategy: "TREND_STRATEGY" or "RANGE_STRATEGY"
            adx: Current ADX value
            hysteresis_threshold: ADX buffer to prevent rapid switching (default: 1.5)
        
        Returns:
            (should_switch: bool, new_strategy: str)
        """
        decision = self.detect_mode(adx)
        recommended = decision.mode
        
        # Get current mode from strategy name
        current_mode = "TREND" if "TREND" in current_strategy.upper() else "RANGE"
        
        # Apply hysteresis: only switch if we're sufficiently past threshold
        if current_mode == "TREND" and recommended == "RANGE":
            # Only switch to RANGE if ADX is well below threshold
            threshold_with_hysteresis = self.range_mode_threshold - hysteresis_threshold
            should_switch = adx < threshold_with_hysteresis
        elif current_mode == "RANGE" and recommended == "TREND":
            # Only switch to TREND if ADX is well above threshold
            threshold_with_hysteresis = self.range_mode_threshold + hysteresis_threshold
            should_switch = adx > threshold_with_hysteresis
        else:
            should_switch = False
        
        new_strategy = (
            "RANGE_STRATEGY" if recommended == "RANGE" else "TREND_STRATEGY"
        )
        
        if should_switch:
            logger.warning(
                "[STRATEGY_SWITCH] Switching from %s to %s (ADX=%.1f, hysteresis=%.1f)",
                current_strategy,
                new_strategy,
                adx,
                hysteresis_threshold
            )
        
        return should_switch, new_strategy


# Global singleton instance
_market_mode_detector = None


def get_market_mode_detector(range_threshold: float = 15.0) -> MarketModeDetector:
    """Get or create global market mode detector instance"""
    global _market_mode_detector
    if _market_mode_detector is None:
        _market_mode_detector = MarketModeDetector(range_mode_threshold=range_threshold)
    return _market_mode_detector


def detect_market_mode(adx: float, context: dict = None) -> MarketModeDecision:
    """
    Convenience function: detect market mode without creating detector instance.
    Uses global singleton.
    """
    detector = get_market_mode_detector()
    return detector.detect_mode(adx, context)

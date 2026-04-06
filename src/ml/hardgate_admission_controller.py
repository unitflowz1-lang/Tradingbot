"""
HardGateAdmissionController: Pre-flight checks that block undesirable trades before expensive calculations.

This module enforces a "fail-fast" philosophy:
1. Check hard gates FIRST (liquidity traps, emergency shutdowns)
2. Only proceed to expensive calculations if hard gates pass
3. Return explicit DENY decision, not logging-only warnings
"""

from dataclasses import dataclass
from typing import Optional, Callable
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class AdmissionDecision(Enum):
    """Hard decision gates - not gradual warnings."""
    ADMIT = "ADMIT"
    DENY_LIQUIDITY_TRAP = "DENY_LIQUIDITY_TRAP"
    DENY_EMERGENCY_SHUTDOWN = "DENY_EMERGENCY_SHUTDOWN"
    DENY_NEWS_EMBARGO = "DENY_NEWS_EMBARGO"
    DENY_COOLDOWN = "DENY_COOLDOWN"
    DENY_INSUFFICIENT_CONFIDENCE = "DENY_INSUFFICIENT_CONFIDENCE"
    DENY_UNKNOWN = "DENY_UNKNOWN"


@dataclass
class PreFlightCheckResult:
    """Result of pre-flight gate checks."""
    decision: AdmissionDecision
    passed: bool  # True = ADMIT, False = DENY_*
    reason: str
    block_duration_seconds: Optional[int] = None


class HardGateAdmissionController:
    """
    Pre-flight check controller that gates trades BEFORE expensive calculations.
    
    Gates (in order):
    1. LiquidityTrap Check: Is symbol in liquidity trap? DENY immediately.
    2. Emergency Shutdown: Is system in emergency mode? DENY all trades.
    3. News Embargo: Is symbol under news event embargo? DENY immediately.
    4. Cooldown Check: Is symbol on post-trade cooldown? DENY until cooldown expires.
    5. Confidence Gate: Is raw confidence below minimum threshold? DENY immediately.
    
    Each gate is a "hard block" - if triggered, trade is DENIED. There are no
    warnings or logging events that allow trades to proceed despite gate violations.
    """
    
    def __init__(
        self,
        liquidity_trap_checker: Optional[Callable[[str], bool]] = None,
        emergency_shutdown_checker: Optional[Callable[[], bool]] = None,
        news_embargo_checker: Optional[Callable[[str], bool]] = None,
        cooldown_checker: Optional[Callable[[str], Optional[int]]] = None,
        min_confidence_threshold: float = 0.30,
    ):
        """
        Initialize hard-gate admission controller.
        
        Args:
            liquidity_trap_checker: Function(symbol) -> bool (True = trap detected)
            emergency_shutdown_checker: Function() -> bool (True = emergency active)
            news_embargo_checker: Function(symbol) -> bool (True = embargo active)
            cooldown_checker: Function(symbol) -> Optional[seconds_remaining]
            min_confidence_threshold: Minimum confidence to admit (0.0 - 1.0)
        """
        self._liquidity_trap_checker = liquidity_trap_checker
        self._emergency_shutdown_checker = emergency_shutdown_checker
        self._news_embargo_checker = news_embargo_checker
        self._cooldown_checker = cooldown_checker
        self._min_confidence = min_confidence_threshold
        
        logger.info(
            "[HARDGATE_ADMISSION_INIT] Initialized with min_confidence=%.2f%%",
            min_confidence_threshold * 100
        )
    
    def pre_flight_check(
        self,
        symbol: str,
        confidence: Optional[float] = None,
    ) -> PreFlightCheckResult:
        """
        Perform hard-gate pre-flight checks BEFORE any expensive calculations.
        
        This is called at the TOP of evaluate_admission() to fail-fast if any
        hard gate is violated.
        
        Returns:
            PreFlightCheckResult with ADMIT or specific DENY reason
        """
        
        # GATE 1: Emergency Shutdown (Absolute priority)
        if self._emergency_shutdown_checker and self._emergency_shutdown_checker():
            logger.critical(
                "[HARDGATE] %s | DENIED: Emergency shutdown active. All trades blocked.",
                symbol
            )
            return PreFlightCheckResult(
                decision=AdmissionDecision.DENY_EMERGENCY_SHUTDOWN,
                passed=False,
                reason="Emergency shutdown active - system-wide trading pause",
            )
        
        # GATE 2: Liquidity Trap Check (RiskGuard gate)
        if self._liquidity_trap_checker and self._liquidity_trap_checker(symbol):
            logger.critical(
                "[HARDGATE] %s | DENIED: Liquidity trap detected. Trade blocked.",
                symbol
            )
            return PreFlightCheckResult(
                decision=AdmissionDecision.DENY_LIQUIDITY_TRAP,
                passed=False,
                reason="Liquidity trap detected - market conditions unsafe",
            )
        
        # GATE 3: News Embargo Check
        if self._news_embargo_checker and self._news_embargo_checker(symbol):
            logger.warning(
                "[HARDGATE] %s | DENIED: News event embargo active.",
                symbol
            )
            return PreFlightCheckResult(
                decision=AdmissionDecision.DENY_NEWS_EMBARGO,
                passed=False,
                reason="News event embargo active - high volatility period",
            )
        
        # GATE 4: Symbol Cooldown Check (Post-trade revenge protection)
        if self._cooldown_checker:
            cooldown_remaining = self._cooldown_checker(symbol)
            if cooldown_remaining is not None and cooldown_remaining > 0:
                logger.warning(
                    "[HARDGATE] %s | DENIED: Symbol cooldown active for %d more seconds.",
                    symbol,
                    cooldown_remaining
                )
                return PreFlightCheckResult(
                    decision=AdmissionDecision.DENY_COOLDOWN,
                    passed=False,
                    reason=f"Symbol cooldown active - {cooldown_remaining}s remaining",
                    block_duration_seconds=cooldown_remaining,
                )
        
        # GATE 5: Confidence Threshold Gate (Hard floor)
        if confidence is not None and confidence < self._min_confidence:
            logger.warning(
                "[HARDGATE] %s | DENIED: Confidence %.2f%% < threshold %.2f%%",
                symbol,
                confidence * 100,
                self._min_confidence * 100
            )
            return PreFlightCheckResult(
                decision=AdmissionDecision.DENY_INSUFFICIENT_CONFIDENCE,
                passed=False,
                reason=f"Confidence {confidence*100:.1f}% below threshold {self._min_confidence*100:.1f}%",
            )
        
        # All gates passed - proceed to full admission evaluation
        logger.debug(
            "[HARDGATE] %s | PASSED all pre-flight checks. Proceeding to full admission eval.",
            symbol
        )
        return PreFlightCheckResult(
            decision=AdmissionDecision.ADMIT,
            passed=True,
            reason="All pre-flight gates passed",
        )
    
    def update_gate_checkers(
        self,
        liquidity_trap_checker: Optional[Callable[[str], bool]] = None,
        emergency_shutdown_checker: Optional[Callable[[], bool]] = None,
        news_embargo_checker: Optional[Callable[[str], bool]] = None,
        cooldown_checker: Optional[Callable[[str], Optional[int]]] = None,
    ) -> None:
        """
        Update gate checker functions (for integration with existing systems).
        
        This allows the orchestrator to inject references to existing checkers
        without requiring refactoring the entire admission pipeline.
        """
        if liquidity_trap_checker:
            self._liquidity_trap_checker = liquidity_trap_checker
        if emergency_shutdown_checker:
            self._emergency_shutdown_checker = emergency_shutdown_checker
        if news_embargo_checker:
            self._news_embargo_checker = news_embargo_checker
        if cooldown_checker:
            self._cooldown_checker = cooldown_checker
        
        logger.info("[HARDGATE] Gate checkers updated")
    
    def set_confidence_threshold(self, threshold: float) -> None:
        """Update minimum confidence threshold."""
        if not 0.0 <= threshold <= 1.0:
            raise ValueError(f"Threshold must be 0.0-1.0, got {threshold}")
        self._min_confidence = threshold
        logger.info("[HARDGATE] Confidence threshold updated to %.2f%%", threshold * 100)


def create_default_hardgate_controller() -> HardGateAdmissionController:
    """
    Create a HardGateAdmissionController with safe defaults.
    
    All gate checkers default to None (not triggered).
    Min confidence defaults to 30%.
    """
    return HardGateAdmissionController(
        liquidity_trap_checker=None,
        emergency_shutdown_checker=None,
        news_embargo_checker=None,
        cooldown_checker=None,
        min_confidence_threshold=0.30,
    )

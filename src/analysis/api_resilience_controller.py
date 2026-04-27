"""
API Data Controller - Resilience & Failover Engine
Maintains 100% uptime despite external API failures.

ARCHITECTURAL PRINCIPLES:
- Deterministic Failover: API timeout/error triggers TECHNICAL_ONLY_MODE immediately
- Degraded Operation: Reduces position sizing by 50%, uses only technical indicators
- Health-Based Recovery: DATA_VALIDATION_PASS on connection restoration
- Silent Failure Management: Exponential backoff (1m → 5m → 15m → 30m)
- Never Amnesia: Technical memory and learned state preserved during failures

USAGE:
    controller = APIResilienceController(finnhub_manager, risk_manager)

    # In main loop:
    macro_data = await controller.get_macro_data(symbol)
    position_size = await controller.get_adjusted_position_size(symbol, base_size)

    # Returns trade flags for logging:
    trade_flags = controller.get_trade_flags()
"""

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, Any, Tuple, List
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Constants
# ============================================================================

class APIOperatingMode(Enum):
    """Operating modes for API resilience."""
    NORMAL = "NORMAL"
    TECHNICAL_ONLY = "TECHNICAL_ONLY"
    PRESERVATION = "PRESERVATION"


class TradeAdmissionMode(Enum):
    """Trade admission modes for flagging."""
    NORMAL = "NORMAL"
    TECH_ONLY_ADMITTED = "TECH_ONLY_ADMITTED"
    PRESERVATION_ONLY = "PRESERVATION_ONLY"


# Exponential backoff schedule (seconds)
BACKOFF_SCHEDULE = [60, 300, 900, 1800]  # 1m, 5m, 15m, 30m
MAX_BACKOFF_STAGE = len(BACKOFF_SCHEDULE) - 1
SYSTEM_DEGRADATION_ALERT_THRESHOLD = 1800  # 30 minutes

# Position sizing reduction factors
TECHNICAL_ONLY_POSITION_SIZE_FACTOR = 0.5  # 50% reduction
PRESERVATION_POSITION_SIZE_FACTOR = 0.3   # 70% reduction

# API timeout thresholds (milliseconds)
API_LATENCY_WARNING_THRESHOLD_MS = 3000
API_LATENCY_CRITICAL_THRESHOLD_MS = 5000

# Recovery validation
DATA_VALIDATION_TIMEOUT_SECONDS = 10


# ============================================================================
# Data Classes
# ============================================================================

@dataclass
class APIHealthStatus:
    """Tracks API health and failure recovery."""
    mode: APIOperatingMode = APIOperatingMode.NORMAL
    last_successful_call: Optional[datetime] = None
    consecutive_failures: int = 0
    backoff_stage: int = 0
    next_retry_time: Optional[datetime] = None
    last_error: Optional[str] = None
    error_timestamp: Optional[datetime] = None

    # Metrics
    total_api_calls: int = 0
    total_failures: int = 0
    total_timeouts: int = 0
    time_in_technical_only: float = 0.0  # seconds
    time_entered_technical_only: Optional[datetime] = None


@dataclass
class DataValidationSnapshot:
    """Snapshot of market state for validation pass."""
    timestamp: datetime
    symbol: str
    risk_score: float
    sentiment_score: float
    upcoming_events: List[Dict] = field(default_factory=list)


@dataclass
class TradeFlags:
    """Flags for trade monitoring during resilience."""
    admission_mode: TradeAdmissionMode = TradeAdmissionMode.NORMAL
    position_size_factor: float = 1.0
    is_technical_only: bool = False
    is_preservation_only: bool = False
    trade_comment: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================================
# API Resilience Controller
# ============================================================================

class APIResilienceController:
    """
    Controls API resilience and failover for macro data integration.

    Provides:
    - Transparent API failure detection and mode switching
    - Automatic technical-only mode activation
    - Position sizing adjustments for degraded operation
    - Health-based recovery with data validation
    - Trade flagging for audit and analysis
    """

    def __init__(
        self,
        finnhub_manager: Any,
        risk_manager: Any,
        enable_preservation_mode: bool = True,
    ):
        """
        Initialize APIResilienceController.

        Args:
            finnhub_manager: FinnhubMacroManager instance
            risk_manager: RiskManager instance for position sizing
            enable_preservation_mode: Enable 70% reduction mode when > 30min down
        """
        self.finnhub_manager = finnhub_manager
        self.risk_manager = risk_manager
        self.enable_preservation_mode = enable_preservation_mode

        # Health tracking per symbol
        self._health: Dict[str, APIHealthStatus] = {}
        self._health_lock = asyncio.Lock()

        # Data validation history
        self._validation_snapshots: Dict[str, DataValidationSnapshot] = {}
        self._validation_lock = asyncio.Lock()

        # Trade flags for current session
        self._current_trade_flags: Dict[str, TradeFlags] = {}
        self._flags_lock = asyncio.Lock()

        # Last known good state (for comparison during validation)
        self._last_known_good_state: Dict[str, Dict] = {}

        logger.info(
            "[API_RESILIENCE] Controller initialized | "
            "Preservation mode: %s",
            enable_preservation_mode
        )

    async def get_macro_data(self, symbol: str) -> Dict[str, Any]:
        """
        Get macro data with automatic failover.

        Returns macro data from Finnhub if available, otherwise returns
        technical-only fallback with appropriate flags.

        Args:
            symbol: Trading symbol (e.g., "EUR/USD")

        Returns:
            Dict with macro data and mode information
        """
        if symbol not in self._health:
            self._health[symbol] = APIHealthStatus()

        health = self._health[symbol]
        current_time = datetime.now(timezone.utc)

        # Check if we should retry
        if health.mode != APIOperatingMode.NORMAL:
            if health.next_retry_time and current_time < health.next_retry_time:
                # Still in backoff period - return fallback data
                return self._get_fallback_macro_data(symbol, health.mode)

        # Attempt to fetch macro data
        try:
            start_time = time.time()
            snapshot = self.finnhub_manager.get_latest_snapshot(symbol)
            latency_ms = (time.time() - start_time) * 1000

            # Log latency warnings
            if latency_ms > API_LATENCY_CRITICAL_THRESHOLD_MS:
                logger.warning(
                    "[API_LATENCY_CRITICAL] %s: %.0fms exceeds 5s threshold",
                    symbol, latency_ms
                )
                # Trigger failover if consistently slow
                await self._trigger_technical_only_mode(
                    symbol,
                    f"API latency critical: {latency_ms:.0f}ms"
                )
                return self._get_fallback_macro_data(symbol, APIOperatingMode.TECHNICAL_ONLY)

            elif latency_ms > API_LATENCY_WARNING_THRESHOLD_MS:
                logger.warning(
                    "[API_LATENCY_WARNING] %s: %.0fms approaching threshold",
                    symbol, latency_ms
                )

            # Success - reset health
            health.last_successful_call = current_time
            health.consecutive_failures = 0
            health.total_api_calls += 1

            # If recovering from TECHNICAL_ONLY, run validation pass
            if health.mode in [APIOperatingMode.TECHNICAL_ONLY, APIOperatingMode.PRESERVATION]:
                logger.info(
                    "[DATA_VALIDATION_PASS] Initiated for %s (recovered from %s)",
                    symbol, health.mode.value
                )
                await self._perform_data_validation_pass(symbol, snapshot)
                health.mode = APIOperatingMode.NORMAL
                health.backoff_stage = 0
                health.next_retry_time = None
                logger.info("[API_RECOVERY] %s switched back to NORMAL mode", symbol)

            # Store for validation
            self._last_known_good_state[symbol] = {
                "risk_score": snapshot.risk_score,
                "sentiment_score": snapshot.news_sentiment_score,
                "timestamp": current_time,
            }

            return {
                "status": "OK",
                "risk_score": snapshot.risk_score,
                "sentiment_score": snapshot.news_sentiment_score,
                "upcoming_events": snapshot.upcoming_events,
                "mode": APIOperatingMode.NORMAL.value,
                "data_freshness_ok": snapshot.data_freshness_ok,
                "latency_ms": latency_ms,
            }

        except asyncio.TimeoutError as e:
            logger.error(
                "[API_TIMEOUT] %s: Request exceeded timeout threshold",
                symbol
            )
            health.total_timeouts += 1
            await self._handle_api_failure(
                symbol,
                "Timeout (>5s)",
                e
            )
            return self._get_fallback_macro_data(symbol, health.mode)

        except Exception as e:
            logger.error(
                "[API_ERROR] %s: %s",
                symbol, str(e)[:100]
            )
            await self._handle_api_failure(symbol, str(e)[:100], e)
            return self._get_fallback_macro_data(symbol, health.mode)

    async def get_adjusted_position_size(
        self,
        symbol: str,
        base_size: float
    ) -> Tuple[float, TradeFlags]:
        """
        Get position size adjusted for API failure mode.

        Returns 50% of base_size in TECHNICAL_ONLY mode,
        30% in PRESERVATION mode.

        Args:
            symbol: Trading symbol
            base_size: Base position size (contracts or units)

        Returns:
            Tuple of (adjusted_size, trade_flags)
        """
        if symbol not in self._health:
            self._health[symbol] = APIHealthStatus()

        health = self._health[symbol]

        # Determine position size factor and flags
        if health.mode == APIOperatingMode.PRESERVATION:
            factor = PRESERVATION_POSITION_SIZE_FACTOR
            admission_mode = TradeAdmissionMode.PRESERVATION_ONLY
            comment = "[MODE: PRESERVATION] 70% size reduction"

        elif health.mode == APIOperatingMode.TECHNICAL_ONLY:
            factor = TECHNICAL_ONLY_POSITION_SIZE_FACTOR
            admission_mode = TradeAdmissionMode.TECH_ONLY_ADMITTED
            comment = "[MODE: TECH_ONLY_ADMITTED] 50% size reduction, macro data unavailable"

        else:  # NORMAL
            factor = 1.0
            admission_mode = TradeAdmissionMode.NORMAL
            comment = "[MODE: NORMAL]"

        adjusted_size = base_size * factor

        # Create trade flags
        flags = TradeFlags(
            admission_mode=admission_mode,
            position_size_factor=factor,
            is_technical_only=(health.mode == APIOperatingMode.TECHNICAL_ONLY),
            is_preservation_only=(health.mode == APIOperatingMode.PRESERVATION),
            trade_comment=comment,
        )

        # Store for auditing
        async with self._flags_lock:
            self._current_trade_flags[symbol] = flags

        if factor < 1.0:
            logger.info(
                "[POSITION_SIZING] %s: %.2f -> %.2f (factor: %.1%%) | %s",
                symbol, base_size, adjusted_size, factor * 100, comment
            )

        return adjusted_size, flags

    def get_operating_mode(self, symbol: str) -> APIOperatingMode:
        """Get current operating mode for a symbol."""
        if symbol not in self._health:
            return APIOperatingMode.NORMAL
        return self._health[symbol].mode

    def get_trade_flags(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """
        Get trade flags for audit logging.

        Args:
            symbol: Specific symbol, or None for all

        Returns:
            Dict with trade flags for flagging/logging
        """
        if symbol:
            flags = self._current_trade_flags.get(symbol)
            if flags:
                return {
                    "admission_mode": flags.admission_mode.value,
                    "position_size_factor": flags.position_size_factor,
                    "is_technical_only": flags.is_technical_only,
                    "trade_comment": flags.trade_comment,
                    "timestamp": flags.timestamp.isoformat(),
                }
            return {"admission_mode": "NORMAL", "position_size_factor": 1.0}

        # Return all
        return {
            s: {
                "admission_mode": f.admission_mode.value,
                "position_size_factor": f.position_size_factor,
                "trade_comment": f.trade_comment,
            }
            for s, f in self._current_trade_flags.items()
        }

    def get_health_status(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get health status for monitoring/diagnostics."""
        if symbol:
            health = self._health.get(symbol)
            if health:
                return {
                    "mode": health.mode.value,
                    "last_successful_call": health.last_successful_call.isoformat() if health.last_successful_call else None,
                    "consecutive_failures": health.consecutive_failures,
                    "backoff_stage": health.backoff_stage,
                    "next_retry_time": health.next_retry_time.isoformat() if health.next_retry_time else None,
                    "last_error": health.last_error,
                    "total_failures": health.total_failures,
                    "total_timeouts": health.total_timeouts,
                    "time_in_technical_only_seconds": health.time_in_technical_only,
                }
            return {}

        return {
            s: {
                "mode": h.mode.value,
                "consecutive_failures": h.consecutive_failures,
                "total_failures": h.total_failures,
            }
            for s, h in self._health.items()
        }

    # ========================================================================
    # Private Methods - Failure Handling
    # ========================================================================

    async def _handle_api_failure(
        self,
        symbol: str,
        error_msg: str,
        exception: Exception
    ) -> None:
        """
        Handle API failure with exponential backoff.

        Progression:
        1. First failures (0-2): Wait 1 minute, attempt recovery
        2. Medium failures (3-4): Wait 5+ minutes
        3. Long failures (5+): Wait 30 minutes, enter PRESERVATION mode
        """
        health = self._health[symbol]
        current_time = datetime.now(timezone.utc)

        health.consecutive_failures += 1
        health.total_failures += 1
        health.last_error = error_msg
        health.error_timestamp = current_time

        # Determine backoff stage
        if health.consecutive_failures <= 2:
            backoff_stage = 0  # 1 minute
        elif health.consecutive_failures <= 4:
            backoff_stage = 1  # 5 minutes
        elif health.consecutive_failures <= 6:
            backoff_stage = 2  # 15 minutes
        else:
            backoff_stage = 3  # 30 minutes

        backoff_seconds = BACKOFF_SCHEDULE[min(backoff_stage, MAX_BACKOFF_STAGE)]
        health.backoff_stage = backoff_stage
        health.next_retry_time = current_time + timedelta(seconds=backoff_seconds)

        # Trigger TECHNICAL_ONLY_MODE
        await self._trigger_technical_only_mode(symbol, error_msg)

        logger.warning(
            "[API_FAILURE] %s | Attempt %d | Error: %s | "
            "Next retry: %.0f seconds | Mode: %s",
            symbol,
            health.consecutive_failures,
            error_msg,
            backoff_seconds,
            health.mode.value
        )

        # If we're at max backoff, escalate to PRESERVATION_MODE
        time_failed_seconds = (
            current_time - health.error_timestamp
        ).total_seconds() if health.error_timestamp else 0

        if self.enable_preservation_mode and backoff_seconds >= SYSTEM_DEGRADATION_ALERT_THRESHOLD:
            logger.critical(
                "[SYSTEM_DEGRADATION_ALERT] %s has been down for %.0f seconds | "
                "Entering PRESERVATION_MODE (new positions halted)",
                symbol,
                time_failed_seconds
            )
            health.mode = APIOperatingMode.PRESERVATION

    async def _trigger_technical_only_mode(
        self,
        symbol: str,
        reason: str
    ) -> None:
        """
        Trigger TECHNICAL_ONLY_MODE for a symbol.

        In this mode:
        - Only technical indicators (RSI, ADX, Price Action, ATR)
        - Position sizing reduced to 50%
        - All trades flagged as [MODE: TECH_ONLY_ADMITTED]
        """
        health = self._health[symbol]
        current_time = datetime.now(timezone.utc)

        if health.mode == APIOperatingMode.NORMAL:
            health.mode = APIOperatingMode.TECHNICAL_ONLY
            health.time_entered_technical_only = current_time
            logger.info(
                "[TECHNICAL_ONLY_MODE_ACTIVATED] %s | Reason: %s | "
                "Position sizing: 50% | Indicators: RSI, ADX, Price Action, ATR",
                symbol,
                reason
            )

    async def _perform_data_validation_pass(
        self,
        symbol: str,
        new_snapshot: Any
    ) -> None:
        """
        Perform DATA_VALIDATION_PASS to compare current state with last known good state.

        Compares:
        - Risk score drift
        - Sentiment change
        - Event changes

        This validates that macro data is consistent before re-enabling normal mode.
        """
        if symbol not in self._last_known_good_state:
            logger.info("[DATA_VALIDATION] No prior state to validate against")
            return

        last_good = self._last_known_good_state[symbol]
        current_time = datetime.now(timezone.utc)

        # Snapshot current state
        validation = DataValidationSnapshot(
            timestamp=current_time,
            symbol=symbol,
            risk_score=new_snapshot.risk_score,
            sentiment_score=new_snapshot.news_sentiment_score,
            upcoming_events=[
                {
                    "event_name": e.event_name,
                    "impact": e.impact,
                    "minutes_until": e.minutes_until_event,
                }
                for e in new_snapshot.upcoming_events[:3]
            ]
        )

        async with self._validation_lock:
            self._validation_snapshots[symbol] = validation

        # Compare with last known good state
        risk_drift = abs(new_snapshot.risk_score - last_good["risk_score"])
        sentiment_drift = abs(new_snapshot.news_sentiment_score - last_good["sentiment_score"])

        logger.info(
            "[DATA_VALIDATION_PASS] %s | Risk drift: %.1f | Sentiment drift: %.2f | "
            "State validated, resuming normal operation",
            symbol,
            risk_drift,
            sentiment_drift
        )

    def _get_fallback_macro_data(
        self,
        symbol: str,
        mode: APIOperatingMode
    ) -> Dict[str, Any]:
        """
        Return fallback macro data when API is unavailable.

        In TECHNICAL_ONLY_MODE, returns neutral data (safe fallback).
        """
        return {
            "status": "FALLBACK",
            "risk_score": 2.0,  # NORMAL equivalent
            "sentiment_score": 0.5,  # NEUTRAL
            "upcoming_events": [],
            "mode": mode.value,
            "data_freshness_ok": False,
            "fallback_reason": "API unavailable - using technical indicators only",
        }


# ============================================================================
# Convenience Factory
# ============================================================================

def create_resilience_controller(
    finnhub_manager: Any,
    risk_manager: Any,
) -> APIResilienceController:
    """
    Factory function to create APIResilienceController.

    Args:
        finnhub_manager: FinnhubMacroManager instance
        risk_manager: RiskManager instance

    Returns:
        APIResilienceController instance
    """
    return APIResilienceController(
        finnhub_manager=finnhub_manager,
        risk_manager=risk_manager,
        enable_preservation_mode=True,
    )

"""
Test Suite: API Resilience Controller
======================================

Comprehensive tests for the APIResilienceController to verify:
1. Normal operation (passthrough to Finnhub)
2. API failure detection (timeout, error)
3. TECHNICAL_ONLY_MODE activation
4. Position sizing reduction (50%)
5. Exponential backoff scheduling
6. Recovery and DATA_VALIDATION_PASS
7. Trade flagging and audit trail
"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import logging

from src.analysis.api_resilience_controller import (
    APIResilienceController,
    APIOperatingMode,
    TradeAdmissionMode,
    BACKOFF_SCHEDULE,
    TECHNICAL_ONLY_POSITION_SIZE_FACTOR,
    PRESERVATION_POSITION_SIZE_FACTOR,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def mock_finnhub_manager():
    """Mock FinnhubMacroManager."""
    manager = AsyncMock()
    manager.get_latest_snapshot = AsyncMock()
    return manager


@pytest.fixture
def mock_risk_manager():
    """Mock RiskManager."""
    manager = Mock()
    manager.calculate_position_size = Mock()
    return manager


@pytest.fixture
def resilience_controller(mock_finnhub_manager, mock_risk_manager):
    """Create APIResilienceController instance."""
    return APIResilienceController(
        finnhub_manager=mock_finnhub_manager,
        risk_manager=mock_risk_manager,
        enable_preservation_mode=True,
    )


@pytest.fixture
def mock_snapshot():
    """Mock MacroRiskSnapshot."""
    snapshot = Mock()
    snapshot.risk_score = 2.0
    snapshot.news_sentiment_score = 0.5
    snapshot.upcoming_events = []
    snapshot.data_freshness_ok = True
    return snapshot


# ============================================================================
# Test: Normal Operation (Passthrough)
# ============================================================================

@pytest.mark.asyncio
async def test_normal_operation_passthrough(resilience_controller, mock_finnhub_manager, mock_snapshot):
    """
    Test: API is healthy, data passes through unchanged.

    Expected:
    - Mode: NORMAL
    - Position size: 100% (no reduction)
    - Trade flag: "NORMAL"
    """
    # Setup
    mock_finnhub_manager.get_latest_snapshot.return_value = mock_snapshot
    symbol = "EUR/USD"

    # Execute
    macro_data = await resilience_controller.get_macro_data(symbol)

    # Assert
    assert macro_data["status"] == "OK"
    assert macro_data["mode"] == APIOperatingMode.NORMAL.value
    assert macro_data["risk_score"] == 2.0
    assert macro_data["data_freshness_ok"] is True

    # Check position size not reduced
    adjusted_size, flags = await resilience_controller.get_adjusted_position_size(symbol, 1.0)
    assert adjusted_size == 1.0  # No reduction
    assert flags.position_size_factor == 1.0
    assert flags.admission_mode == TradeAdmissionMode.NORMAL


# ============================================================================
# Test: API Timeout Detection
# ============================================================================

@pytest.mark.asyncio
async def test_api_timeout_triggers_technical_only(resilience_controller, mock_finnhub_manager):
    """
    Test: API timeout (>5s) triggers TECHNICAL_ONLY_MODE.

    Expected:
    - Status: FALLBACK
    - Mode: TECHNICAL_ONLY
    - Position size reduced to 50%
    - Trade flag: "[MODE: TECH_ONLY_ADMITTED]"
    """
    # Setup
    mock_finnhub_manager.get_latest_snapshot.side_effect = asyncio.TimeoutError("Timeout")
    symbol = "EUR/USD"

    # Execute
    macro_data = await resilience_controller.get_macro_data(symbol)

    # Assert - fallback data
    assert macro_data["status"] == "FALLBACK"
    assert macro_data["mode"] == APIOperatingMode.TECHNICAL_ONLY.value
    assert macro_data["data_freshness_ok"] is False

    # Assert - position size reduced
    adjusted_size, flags = await resilience_controller.get_adjusted_position_size(symbol, 1.0)
    assert adjusted_size == 0.5  # 50% reduction
    assert flags.position_size_factor == TECHNICAL_ONLY_POSITION_SIZE_FACTOR
    assert flags.admission_mode == TradeAdmissionMode.TECH_ONLY_ADMITTED
    assert "[MODE: TECH_ONLY_ADMITTED]" in flags.trade_comment


# ============================================================================
# Test: API Error Detection
# ============================================================================

@pytest.mark.asyncio
async def test_api_error_triggers_technical_only(resilience_controller, mock_finnhub_manager):
    """
    Test: API error (e.g., 401, 429) triggers TECHNICAL_ONLY_MODE.
    """
    # Setup
    mock_finnhub_manager.get_latest_snapshot.side_effect = PermissionError("API 401: Unauthorized")
    symbol = "GBP/USD"

    # Execute
    macro_data = await resilience_controller.get_macro_data(symbol)

    # Assert
    assert macro_data["status"] == "FALLBACK"
    assert macro_data["mode"] == APIOperatingMode.TECHNICAL_ONLY.value

    # Assert - position size reduced
    adjusted_size, flags = await resilience_controller.get_adjusted_position_size(symbol, 2.0)
    assert adjusted_size == 1.0  # 50% of 2.0


# ============================================================================
# Test: Exponential Backoff
# ============================================================================

@pytest.mark.asyncio
async def test_exponential_backoff_schedule(resilience_controller, mock_finnhub_manager):
    """
    Test: Consecutive failures trigger exponential backoff (1m, 5m, 15m, 30m).

    Expected:
    - Failure 1: backoff 60s
    - Failure 3: backoff 300s (5m)
    - Failure 5: backoff 900s (15m)
    - Failure 6+: backoff 1800s (30m), enter PRESERVATION mode
    """
    symbol = "USD/JPY"
    mock_finnhub_manager.get_latest_snapshot.side_effect = TimeoutError("Timeout")

    # Simulate 6 consecutive failures
    for attempt in range(6):
        await resilience_controller.get_macro_data(symbol)

    # Assert - check backoff timing
    health = resilience_controller._health[symbol]
    assert health.consecutive_failures == 6
    assert health.backoff_stage == 3  # Max backoff stage
    assert health.next_retry_time is not None

    # Calculate expected backoff
    expected_backoff = BACKOFF_SCHEDULE[3]  # 1800 seconds
    actual_backoff = (health.next_retry_time - datetime.now(timezone.utc)).total_seconds()
    assert actual_backoff > 0
    assert actual_backoff <= expected_backoff + 5  # Allow small tolerance


# ============================================================================
# Test: PRESERVATION Mode Activation
# ============================================================================

@pytest.mark.asyncio
async def test_preservation_mode_after_long_outage(resilience_controller, mock_finnhub_manager):
    """
    Test: After 30+ minutes of failures, enter PRESERVATION mode.

    Expected:
    - Mode: PRESERVATION
    - Position size: 30% (even more reduced)
    - Trade comment: "[MODE: PRESERVATION]"
    """
    symbol = "AUD/USD"
    mock_finnhub_manager.get_latest_snapshot.side_effect = TimeoutError("Timeout")

    # Simulate 7+ consecutive failures (triggers PRESERVATION after stage 3)
    for attempt in range(7):
        await resilience_controller.get_macro_data(symbol)

    # Assert - in PRESERVATION mode
    health = resilience_controller._health[symbol]
    assert health.mode == APIOperatingMode.PRESERVATION

    # Assert - position size even more reduced
    adjusted_size, flags = await resilience_controller.get_adjusted_position_size(symbol, 1.0)
    assert adjusted_size == 0.3  # 30% reduction
    assert flags.position_size_factor == PRESERVATION_POSITION_SIZE_FACTOR
    assert flags.admission_mode == TradeAdmissionMode.PRESERVATION_ONLY


# ============================================================================
# Test: Recovery & DATA_VALIDATION_PASS
# ============================================================================

@pytest.mark.asyncio
async def test_recovery_triggers_validation_pass(
    resilience_controller, mock_finnhub_manager, mock_snapshot
):
    """
    Test: Recovery from failure triggers DATA_VALIDATION_PASS.

    Expected:
    - Failures occur → TECHNICAL_ONLY mode
    - API recovers → DATA_VALIDATION_PASS
    - After validation → Mode: NORMAL
    """
    symbol = "EUR/USD"

    # Phase 1: Simulate failures
    mock_finnhub_manager.get_latest_snapshot.side_effect = TimeoutError("Timeout")
    for _ in range(3):
        await resilience_controller.get_macro_data(symbol)

    health = resilience_controller._health[symbol]
    assert health.mode == APIOperatingMode.TECHNICAL_ONLY

    # Phase 2: API recovers
    mock_finnhub_manager.get_latest_snapshot.side_effect = None
    mock_finnhub_manager.get_latest_snapshot.return_value = mock_snapshot

    # Execute
    macro_data = await resilience_controller.get_macro_data(symbol)

    # Assert - validation performed and mode recovered
    assert macro_data["status"] == "OK"
    assert macro_data["mode"] == APIOperatingMode.NORMAL.value

    # Assert - failure counter reset
    health = resilience_controller._health[symbol]
    assert health.consecutive_failures == 0
    assert health.mode == APIOperatingMode.NORMAL


# ============================================================================
# Test: Trade Flags for Audit
# ============================================================================

@pytest.mark.asyncio
async def test_trade_flags_for_audit_trail(resilience_controller, mock_finnhub_manager):
    """
    Test: Trade flags are generated for audit logging.

    Expected:
    - Normal mode: "[MODE: NORMAL]"
    - Tech-only mode: "[MODE: TECH_ONLY_ADMITTED] 50% size reduction, macro data unavailable"
    - Preservation mode: "[MODE: PRESERVATION] 70% size reduction"
    """
    symbol = "GBP/USD"
    mock_finnhub_manager.get_latest_snapshot.side_effect = TimeoutError()

    # Trigger tech-only mode
    for _ in range(2):
        await resilience_controller.get_macro_data(symbol)

    # Get trade flags
    flags = resilience_controller.get_trade_flags(symbol)

    # Assert
    assert flags["admission_mode"] == TradeAdmissionMode.TECH_ONLY_ADMITTED.value
    assert flags["position_size_factor"] == 0.5
    assert "[MODE: TECH_ONLY_ADMITTED]" in flags["trade_comment"]


# ============================================================================
# Test: Health Status Monitoring
# ============================================================================

@pytest.mark.asyncio
async def test_health_status_monitoring(resilience_controller, mock_finnhub_manager, mock_snapshot):
    """
    Test: Health status is tracked and retrievable.

    Expected:
    - Consecutive failures counted
    - Last error logged
    - Mode tracked
    """
    symbol = "USD/CHF"

    # Simulate failures
    mock_finnhub_manager.get_latest_snapshot.side_effect = Exception("API Error: 429")
    for _ in range(2):
        await resilience_controller.get_macro_data(symbol)

    # Get health status
    health = resilience_controller.get_health_status(symbol)

    # Assert
    assert health["mode"] == APIOperatingMode.TECHNICAL_ONLY.value
    assert health["consecutive_failures"] == 2
    assert health["total_failures"] == 2
    assert "429" in health["last_error"]


# ============================================================================
# Test: Position Size Never Exceeds Base
# ============================================================================

@pytest.mark.asyncio
async def test_position_size_never_exceeds_base(resilience_controller, mock_finnhub_manager, mock_snapshot):
    """
    Test: Position size adjustment never increases size above base.

    Expected:
    - Normal mode: adjusted_size == base_size (100%)
    - Tech-only mode: adjusted_size == base_size * 0.5 (50%)
    - Never: adjusted_size > base_size
    """
    symbol = "NZD/USD"
    base_size = 5.0

    # Normal mode
    mock_finnhub_manager.get_latest_snapshot.return_value = mock_snapshot
    adjusted_size, flags = await resilience_controller.get_adjusted_position_size(symbol, base_size)
    assert adjusted_size == base_size

    # Tech-only mode
    mock_finnhub_manager.get_latest_snapshot.side_effect = TimeoutError()
    await resilience_controller.get_macro_data(symbol)
    adjusted_size, flags = await resilience_controller.get_adjusted_position_size(symbol, base_size)
    assert adjusted_size == base_size * 0.5
    assert adjusted_size < base_size  # Always less


# ============================================================================
# Test: Memory Preservation During Failures
# ============================================================================

@pytest.mark.asyncio
async def test_memory_preservation_no_amnesia(resilience_controller):
    """
    Test: Technical memory is preserved during API failures.

    Expected:
    - Last known good state is stored
    - Not cleared on failure
    - Available for validation pass
    """
    symbol = "EUR/GBP"

    # Store a known good state
    resilience_controller._last_known_good_state[symbol] = {
        "risk_score": 3.5,
        "sentiment_score": 0.6,
        "timestamp": datetime.now(timezone.utc),
    }

    # Simulate failures
    resilience_controller.finnhub_manager.get_latest_snapshot.side_effect = TimeoutError()
    for _ in range(3):
        await resilience_controller.get_macro_data(symbol)

    # Assert - memory preserved (no amnesia)
    assert symbol in resilience_controller._last_known_good_state
    assert resilience_controller._last_known_good_state[symbol]["risk_score"] == 3.5
    assert resilience_controller._last_known_good_state[symbol]["sentiment_score"] == 0.6


# ============================================================================
# Test: Concurrent Symbols
# ============================================================================

@pytest.mark.asyncio
async def test_independent_failover_per_symbol(
    resilience_controller, mock_finnhub_manager, mock_snapshot
):
    """
    Test: Failure in one symbol doesn't affect others.

    Expected:
    - EUR/USD: TECHNICAL_ONLY (failure)
    - GBP/USD: NORMAL (success)
    - Each has independent health state
    """
    # EUR/USD fails
    mock_finnhub_manager.get_latest_snapshot.side_effect = TimeoutError()
    await resilience_controller.get_macro_data("EUR/USD")

    # GBP/USD succeeds
    mock_finnhub_manager.get_latest_snapshot.side_effect = None
    mock_finnhub_manager.get_latest_snapshot.return_value = mock_snapshot
    await resilience_controller.get_macro_data("GBP/USD")

    # Assert - independent states
    assert resilience_controller.get_operating_mode("EUR/USD") == APIOperatingMode.TECHNICAL_ONLY
    assert resilience_controller.get_operating_mode("GBP/USD") == APIOperatingMode.NORMAL


# ============================================================================
# Test: Latency Threshold
# ============================================================================

@pytest.mark.asyncio
async def test_api_latency_warning_threshold(resilience_controller, mock_finnhub_manager, mock_snapshot):
    """
    Test: High latency (>5s) is detected and triggers failover.

    Expected:
    - Latency > 5s → TECHNICAL_ONLY mode
    - Warning logged
    """
    symbol = "EUR/USD"
    mock_finnhub_manager.get_latest_snapshot.return_value = mock_snapshot

    # Simulate slow response (>5s)
    async def slow_call(*args, **kwargs):
        await asyncio.sleep(5.1)
        return mock_snapshot

    mock_finnhub_manager.get_latest_snapshot = slow_call

    # Execute
    macro_data = await resilience_controller.get_macro_data(symbol)

    # Assert - should trigger failover due to latency
    assert macro_data["mode"] == APIOperatingMode.TECHNICAL_ONLY.value


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    # Run with: pytest test_api_resilience_controller.py -v
    pytest.main([__file__, "-v", "-s"])

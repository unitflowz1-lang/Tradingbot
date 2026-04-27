"""
Unified Resilience Controller

Coordinates fault handling across all external services (Finnhub, Ollama, MT5, News).
Implements progressive mode transitions:
  FULL_AUTO → TECHNICAL_ONLY → PRESERVATION → EMERGENCY

Key Features:
  - OLLAMA LATENCY CIRCUIT BREAKER: Tracks 3-cycle moving average. If latency > 3s,
    activates TECHNICAL_ONLY_MODE for 5 minutes (skip LLM calls entirely)
  - GRANULAR PER-SERVICE SHIELDS:
    * Finnhub Down → MACRO_SHIELD_ACTIVE (trade on technicals only)
    * MT5 Down → PRESERVATION_MODE (full halt)
    * Ollama Slow → OLLAMA_LATENCY_SHIELD (skip LLM, use cache)
  - SERVICE_FAULT_DETECTED unified logging
  - Exponential backoff with 5-minute cap
  - 30+ minute outage detection → PRESERVATION_MODE
  - HARD_SYNC verification on recovery
  - Comprehensive audit trail
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResilienceMode(Enum):
    """Four-tier resilience mode progression."""
    FULL_AUTO = "full_auto"              # Normal operation, all systems active
    TECHNICAL_ONLY = "technical_only"    # Service failures, deterministic only
    PRESERVATION = "preservation"         # Extended outage >30 min, no new trades
    EMERGENCY = "emergency"               # Critical failures, hold-only


class ServiceShieldType(Enum):
    """Granular per-service shield types for cascading failure handling."""
    NONE = "none"                          # No shield active
    MACRO_SHIELD_ACTIVE = "macro_shield"   # Finnhub down - trade on technicals only
    OLLAMA_LATENCY_SHIELD = "ollama_latency"  # LLM slow - skip LLM, use technical
    PRESERVATION_MODE = "preservation"     # MT5 down - full halt
    EMERGENCY_SHIELD = "emergency"         # Critical failures - hold-only


@dataclass
class LatencySample:
    """Single LLM request latency measurement."""
    timestamp: float
    response_time_ms: float
    success: bool
    error_msg: Optional[str] = None


@dataclass
class ServiceHealthState:
    """Tracks health of a single external service."""
    service_name: str                              # "finnhub", "ollama", "mt5", "news"
    is_healthy: bool = True
    last_failure_time: Optional[float] = None
    consecutive_failures: int = 0
    last_error: Optional[str] = None
    next_retry_time: float = 0.0                  # Absolute timestamp for next retry
    backoff_multiplier: float = 1.0               # Exponential backoff state
    total_downtime_seconds: float = 0.0           # Cumulative outage duration
    recovery_attempts: int = 0
    last_recovery_time: Optional[float] = None

    # Latency tracking (for LLM/API services)
    latency_samples: deque = field(default_factory=lambda: deque(maxlen=10))
    avg_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    latency_spike_detected: bool = False
    
    # Circuit breaker state for latency-based failures
    latency_circuit_breaker_active: bool = False
    circuit_breaker_until: float = 0.0  # Absolute timestamp when circuit breaker expires
    consecutive_high_latency: int = 0   # Count of consecutive high-latency calls

    def update_failure(self, error: Exception, backoff_base: float = 1.0,
                      backoff_max: float = 300.0) -> None:
        """Record a service failure and calculate next retry time."""
        self.is_healthy = False
        self.last_failure_time = time.time()
        self.consecutive_failures += 1
        self.last_error = str(error)[:200]  # Limit error message length
        self.recovery_attempts = 0

        # Exponential backoff: 1s → 2s → 4s → ... → capped at 300s
        delay = min(backoff_max, backoff_base * (2 ** (self.consecutive_failures - 1)))
        self.next_retry_time = time.time() + delay

    def update_latency_sample(self, response_time_ms: float, success: bool,
                             latency_threshold_ms: float = 3000.0,
                             circuit_breaker_duration_seconds: float = 300.0) -> bool:
        """
        Record LLM latency sample and check if circuit breaker should activate.
        
        Returns True if circuit breaker was just activated.
        
        Logic: If average latency exceeds 3 seconds over 3 consecutive cycles,
        activate TECHNICAL_ONLY_MODE for 5 minutes.
        """
        now = time.time()
        
        # Check if circuit breaker should deactivate
        if self.latency_circuit_breaker_active and now >= self.circuit_breaker_until:
            self.latency_circuit_breaker_active = False
            self.consecutive_high_latency = 0
            logger.info(
                "[LLM_LATENCY_CIRCUIT_BREAKER] DEACTIVATED | "
                "Service: %s | Circuit breaker expired, resuming LLM calls",
                self.service_name
            )
        
        # Don't check for activation if circuit breaker is already active
        if self.latency_circuit_breaker_active:
            return False
        
        # Add sample to rolling window
        self.latency_samples.append(LatencySample(
            timestamp=now,
            response_time_ms=response_time_ms,
            success=success
        ))
        
        # Check if this sample exceeds threshold
        if response_time_ms > latency_threshold_ms:
            self.consecutive_high_latency += 1
            
            # Activate circuit breaker after 3 consecutive high-latency samples
            if self.consecutive_high_latency >= 3:
                # Calculate average for logging
                if len(self.latency_samples) >= 3:
                    recent_samples = list(self.latency_samples)[-3:]
                    avg_latency = sum(s.response_time_ms for s in recent_samples) / len(recent_samples)
                    self.avg_latency_ms = avg_latency
                else:
                    avg_latency = response_time_ms
                    self.avg_latency_ms = avg_latency
                
                # Calculate p99 latency
                sorted_latencies = sorted([s.response_time_ms for s in self.latency_samples])
                p99_idx = int(len(sorted_latencies) * 0.99)
                self.p99_latency_ms = sorted_latencies[min(p99_idx, len(sorted_latencies) - 1)]
                
                self.latency_circuit_breaker_active = True
                self.circuit_breaker_until = now + circuit_breaker_duration_seconds
                logger.critical(
                    "[LLM_LATENCY_CIRCUIT_BREAKER] ACTIVATED | "
                    "Service: %s | Avg latency: %.0fms over %d consecutive high-latency cycles > %.0fms threshold | "
                    "Circuit breaker active for %.0f seconds",
                    self.service_name, avg_latency, self.consecutive_high_latency,
                    latency_threshold_ms, circuit_breaker_duration_seconds
                )
                return True
        else:
            # Reset counter if latency is acceptable
            self.consecutive_high_latency = 0
            # Update average latency
            if len(self.latency_samples) >= 3:
                recent_samples = list(self.latency_samples)[-3:]
                self.avg_latency_ms = sum(s.response_time_ms for s in recent_samples) / len(recent_samples)
            else:
                self.avg_latency_ms = response_time_ms
        
        return False

    def is_circuit_breaker_active(self) -> bool:
        """Check if latency circuit breaker is currently active."""
        if not self.latency_circuit_breaker_active:
            return False
        
        # Check if circuit breaker has expired
        if time.time() >= self.circuit_breaker_until:
            self.latency_circuit_breaker_active = False
            self.consecutive_high_latency = 0
            return False
        
        return True

    def update_recovery(self) -> None:
        """Record successful recovery."""
        self.is_healthy = True
        self.consecutive_failures = 0
        self.backoff_multiplier = 1.0
        self.recovery_attempts += 1
        self.last_recovery_time = time.time()
        self.last_error = None

    def get_outage_duration(self) -> float:
        """Return outage duration in seconds (0 if healthy)."""
        if self.is_healthy:
            return 0.0
        if self.last_failure_time is None:
            return 0.0
        return time.time() - self.last_failure_time


@dataclass
class ResilienceState:
    """Current resilience system state."""
    current_mode: ResilienceMode
    service_health: Dict[str, ServiceHealthState]
    outage_start_time: Optional[float]
    total_outage_duration_seconds: float
    unhealthy_services: List[str] = field(default_factory=list)
    mode_change_reason: str = ""
    timestamp: float = field(default_factory=time.time)


class AdaptiveRecoveryCoordinator:
    """Manages exponential backoff for service reconnection."""

    def __init__(self, backoff_base: float = 1.0, backoff_max: float = 300.0):
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max

    def should_retry_now(self, service_state: ServiceHealthState) -> bool:
        """Check if enough time has passed for next retry attempt."""
        if service_state.is_healthy:
            return False
        return time.time() >= service_state.next_retry_time

    def get_time_until_retry(self, service_state: ServiceHealthState) -> float:
        """Return seconds until next retry (0 if ready)."""
        if service_state.is_healthy:
            return 0.0
        remaining = service_state.next_retry_time - time.time()
        return max(0.0, remaining)


class StateProtectionArbiter:
    """Ensures position state survives outage scenarios."""

    def __init__(self, state_sync_manager: Optional[Any] = None):
        self.state_sync_manager = state_sync_manager

    def verify_position_sync(self) -> Dict[str, Any]:
        """
        Perform HARD_SYNC after service recovery.
        Compare shadow_tracker vs MT5 live positions and reconcile.
        """
        if self.state_sync_manager is None:
            logger.warning("[HARD_SYNC] No state_sync_manager available, skipping verification")
            return {"status": "skipped", "reason": "no_state_sync_manager"}

        try:
            # Delegate to existing StateSyncManager
            diffs = self.state_sync_manager.detect_and_reconcile()

            if not diffs:
                logger.info("[HARD_SYNC_VERIFICATION] Positions synchronized successfully")
                return {"status": "success", "discrepancies": 0}

            logger.warning(f"[HARD_SYNC_VERIFICATION] Found {len(diffs)} discrepancies, reconciling...")
            for diff in diffs:
                logger.warning(f"  - {diff.type}: {diff.detail} (action: {diff.recommended_action})")

            return {"status": "reconciled", "discrepancies": len(diffs)}

        except Exception as e:
            logger.error(f"[HARD_SYNC] Verification failed: {e}")
            return {"status": "failed", "error": str(e)}


class TechnicalOnlyModeHandler:
    """Executes trading using only cached data, no new API calls."""

    def __init__(self, logger_: logging.Logger = None):
        self.logger = logger_ or logger

    def should_skip_api_call(self, service_name: str, resilience_state: ResilienceState) -> bool:
        """Check if API call should be skipped (service unhealthy)."""
        return service_name in resilience_state.unhealthy_services


class PreservationModeHandler:
    """Manages extended outage (>30 minutes): no new trades, tighten SLs."""

    def __init__(self, sl_tightening_pct: float = 50.0, logger_: logging.Logger = None):
        self.sl_tightening_pct = sl_tightening_pct
        self.logger = logger_ or logger

    def activate(self, resilience_state: ResilienceState) -> None:
        """Activate PRESERVATION_MODE."""
        self.logger.critical(
            "[CRITICAL_NETWORK_OUTAGE_PRESERVATION_ACTIVE] "
            "Extended outage detected (duration: %.0fs). "
            "Stopping new trade entries and tightening trailing stop-losses by %.0f%%.",
            resilience_state.total_outage_duration_seconds,
            self.sl_tightening_pct
        )

    def should_allow_new_entry(self) -> bool:
        """PRESERVATION_MODE disallows new entries."""
        return False


class EmergencyModeHandler:
    """Critical failures: hold-only, prepare to close positions gracefully."""

    def __init__(self, logger_: logging.Logger = None):
        self.logger = logger_ or logger

    def activate(self) -> None:
        """Activate EMERGENCY_MODE."""
        self.logger.critical(
            "[CRITICAL_EMERGENCY_PRESERVE_CAPITAL] "
            "Critical system failures detected. Switching to HOLD-ONLY mode. "
            "Complex positions will be closed gracefully to preserve capital."
        )

    def should_allow_new_entry(self) -> bool:
        """EMERGENCY_MODE disallows new entries."""
        return False


class UnifiedResilienceController:
    """
    Main orchestrator for system-wide fault handling and recovery.

    Coordinates:
    - Service health tracking (Finnhub, Ollama, MT5, News)
    - Mode transitions (FULL_AUTO → TECHNICAL_ONLY → PRESERVATION → EMERGENCY)
    - Exponential backoff for reconnection
    - State protection and HARD_SYNC verification
    """

    def __init__(
        self,
        config: Optional[Any] = None,
        error_handler: Optional[Any] = None,
        degradation_manager: Optional[Any] = None,
        health_checker: Optional[Any] = None,
        state_sync_manager: Optional[Any] = None,
        position_manager: Optional[Any] = None,
    ):
        self.config = config or {}
        self.error_handler = error_handler
        self.degradation_manager = degradation_manager
        self.health_checker = health_checker
        self.position_manager = position_manager

        # Resilience configuration
        resilience_cfg = self.config.get("resilience", {}) if isinstance(self.config, dict) else {}
        self.service_timeout_seconds = resilience_cfg.get("service_timeout_seconds", 5.0)
        self.backoff_base_seconds = resilience_cfg.get("backoff_base_seconds", 1.0)
        self.backoff_max_seconds = resilience_cfg.get("backoff_max_seconds", 300)
        self.outage_preservation_threshold = resilience_cfg.get("outage_preservation_threshold_seconds", 1800)
        self.preservation_sl_tightening_pct = resilience_cfg.get("preservation_mode_sl_tightening_pct", 50.0)
        self.hard_sync_retry_attempts = resilience_cfg.get("hard_sync_retry_attempts", 3)
        self.monitoring_interval = resilience_cfg.get("monitoring_check_interval_seconds", 10)
        
        # LLM latency circuit breaker configuration
        self.llm_latency_threshold_ms = resilience_cfg.get("llm_latency_threshold_ms", 3000.0)
        self.llm_circuit_breaker_duration = resilience_cfg.get("llm_circuit_breaker_duration_seconds", 300.0)
        self.llm_latency_sample_cycles = resilience_cfg.get("llm_latency_sample_cycles", 3)

        # State tracking
        self.current_mode: ResilienceMode = ResilienceMode.FULL_AUTO
        self.service_health: Dict[str, ServiceHealthState] = {}
        self.outage_start_time: Optional[float] = None
        self.total_outage_duration_seconds: float = 0.0

        # Handlers
        self.recovery_coordinator = AdaptiveRecoveryCoordinator(
            backoff_base=self.backoff_base_seconds,
            backoff_max=self.backoff_max_seconds
        )
        self.state_arbiter = StateProtectionArbiter(state_sync_manager=state_sync_manager)
        self.tech_only_handler = TechnicalOnlyModeHandler()
        self.preservation_handler = PreservationModeHandler(
            sl_tightening_pct=self.preservation_sl_tightening_pct
        )
        self.emergency_handler = EmergencyModeHandler()

        # Callbacks
        self.mode_transition_callbacks: List[Callable[[ResilienceMode, ResilienceMode], None]] = []

        # Monitoring
        self.monitoring_active = False
        self.monitor_thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        # Initialize service health states
        for service in ["finnhub", "ollama", "mt5", "news"]:
            self.service_health[service] = ServiceHealthState(service_name=service)

        logger.info(
            "[RESILIENCE_INIT] UnifiedResilienceController initialized | "
            "Backoff: %.1fs-%.0fs | Preservation threshold: %.0fs",
            self.backoff_base_seconds, self.backoff_max_seconds,
            self.outage_preservation_threshold
        )

    def record_service_failure(self, service_name: str, error: Exception) -> None:
        """Called when external service fails."""
        with self._lock:
            if service_name not in self.service_health:
                self.service_health[service_name] = ServiceHealthState(service_name=service_name)

            state = self.service_health[service_name]
            state.update_failure(error, self.backoff_base_seconds, self.backoff_max_seconds)

            # Set outage start time if this is first failure
            if self.outage_start_time is None:
                self.outage_start_time = time.time()

            logger.critical(
                "[SERVICE_FAULT_DETECTED] %s | Consecutive: %d | NextRetry: %.0fs | "
                "Error: %s",
                service_name, state.consecutive_failures,
                self.recovery_coordinator.get_time_until_retry(state),
                state.last_error
            )
            
            # Apply granular per-service shields
            self._apply_service_specific_shield(service_name, state)

            # Check if mode transition needed
            self.check_mode_transition()

    def record_service_recovery(self, service_name: str) -> None:
        """Called when service reconnects successfully."""
        with self._lock:
            if service_name not in self.service_health:
                logger.warning(f"[SERVICE_RECOVERY] Unknown service: {service_name}")
                return

            state = self.service_health[service_name]
            state.update_recovery()
            
            # Reset latency circuit breaker on recovery
            state.latency_circuit_breaker_active = False
            state.consecutive_high_latency = 0

            logger.info(
                "[SERVICE_RECOVERY_SUCCESS] %s | Attempts: %d | "
                "Total downtime: %.0fs",
                service_name, state.recovery_attempts, state.total_downtime_seconds
            )

            # Perform HARD_SYNC if MT5 recovered
            if service_name == "mt5":
                sync_result = self.state_arbiter.verify_position_sync()
                if sync_result["status"] != "success":
                    logger.warning(
                        f"[HARD_SYNC_WARNING] MT5 sync result: {sync_result}"
                    )

            # Check if mode de-escalation needed
            self.check_mode_transition()

    def record_llm_latency(self, response_time_ms: float, success: bool, service_name: str = "ollama") -> bool:
        """
        Record LLM response latency and check if circuit breaker should activate.
        
        This is the key method for the "Ollama Latency Circuit Breaker" feature.
        Call this after every LLM request to track performance.
        
        Returns True if circuit breaker was just activated (LLM is now too slow).
        
        Usage in main loop:
            start_time = time.time()
            response = await call_ollama()
            latency_ms = (time.time() - start_time) * 1000
            
            if resilience_controller.record_llm_latency(latency_ms, success=(response is not None)):
                # Circuit breaker just activated - switch to TECHNICAL_ONLY
                logger.warning("[LLM_SLOW] AI is slow, switching to technical-only mode")
        """
        with self._lock:
            if service_name not in self.service_health:
                self.service_health[service_name] = ServiceHealthState(service_name=service_name)
            
            state = self.service_health[service_name]
            
            # Update latency sample and check circuit breaker
            circuit_breaker_activated = state.update_latency_sample(
                response_time_ms=response_time_ms,
                success=success,
                latency_threshold_ms=self.llm_latency_threshold_ms,
                circuit_breaker_duration_seconds=self.llm_circuit_breaker_duration
            )
            
            if circuit_breaker_activated:
                # LLM is too slow - activate TECHNICAL_ONLY mode proactively
                logger.critical(
                    "[LLM_LATENCY_SHIELD] %s avg latency %.0fms > %.0fms threshold | "
                    "Activating TECHNICAL_ONLY_MODE for %.0f seconds | "
                    "Skipping LLM calls, using technical analysis only",
                    service_name, state.avg_latency_ms, self.llm_latency_threshold_ms,
                    self.llm_circuit_breaker_duration
                )
                
                # Transition to TECHNICAL_ONLY if not already in higher mode
                if self.current_mode in (ResilienceMode.FULL_AUTO,):
                    self.current_mode = ResilienceMode.TECHNICAL_ONLY
                    self._notify_mode_change(ResilienceMode.FULL_AUTO, ResilienceMode.TECHNICAL_ONLY,
                                           f"llm_latency_circuit_breaker_{service_name}")
            
            return circuit_breaker_activated

    def should_skip_llm_call(self) -> bool:
        """
        Check if LLM calls should be skipped due to high latency.
        
        This is the proactive check for the main loop.
        Instead of waiting 10 seconds for a timeout, check this FIRST.
        
        Returns True if LLM circuit breaker is active (skip LLM, use technical only).
        """
        with self._lock:
            ollama_state = self.service_health.get("ollama")
            if ollama_state and ollama_state.is_circuit_breaker_active():
                return True
            return False

    def _apply_service_specific_shield(self, service_name: str, state: ServiceHealthState) -> None:
        """
        Apply granular per-service shields for cascading failure scenarios.
        
        This implements the coordinated mode transitions:
        - Finnhub Down → MACRO_SHIELD_ACTIVE (trade on technicals only)
        - MT5 Down → PRESERVATION_MODE (full halt)
        - Ollama Slow → OLLAMA_LATENCY_SHIELD (skip LLM, use technical)
        """
        if service_name == "finnhub":
            # Finnhub failure: Activate MACRO_SHIELD
            # Bot can still trade on technicals, but without macro risk filtering
            logger.warning(
                "[MACRO_SHIELD_ACTIVE] Finnhub down | Trading on technicals only | "
                "Macro risk filtering disabled until recovery"
            )
            # Don't change global mode - Finnhub is non-critical for execution
            
        elif service_name == "mt5":
            # MT5 failure: PRESERVATION_MODE (full halt)
            # Cannot trade without broker connection
            logger.critical(
                "[PRESERVATION_MODE] MT5 broker down | Full trading halt | "
                "Managing existing positions only"
            )
            if self.current_mode != ResilienceMode.PRESERVATION:
                old_mode = self.current_mode
                self.current_mode = ResilienceMode.PRESERVATION
                self._notify_mode_change(old_mode, ResilienceMode.PRESERVATION,
                                       "mt5_broker_failure")
            
        elif service_name == "ollama":
            # Ollama failure: TECHNICAL_ONLY (skip LLM validation)
            logger.warning(
                "[TECHNICAL_ONLY_MODE] Ollama down | Skipping LLM governance | "
                "Using technical analysis only for trade decisions"
            )
            if self.current_mode == ResilienceMode.FULL_AUTO:
                old_mode = self.current_mode
                self.current_mode = ResilienceMode.TECHNICAL_ONLY
                self._notify_mode_change(old_mode, ResilienceMode.TECHNICAL_ONLY,
                                       "ollama_llm_failure")

    def check_mode_transition(self) -> None:
        """Evaluate if current mode should change based on service health."""
        with self._lock:
            old_mode = self.current_mode
            unhealthy = [s for s, state in self.service_health.items() if not state.is_healthy]

            # Calculate total outage duration
            if self.outage_start_time is not None:
                if unhealthy:
                    self.total_outage_duration_seconds = time.time() - self.outage_start_time
                else:
                    self.total_outage_duration_seconds = 0.0
                    self.outage_start_time = None

            # Mode transition logic - respect severity hierarchy
            # MT5 failure > Finnhub failure > Ollama latency
            new_mode = old_mode
            reason = ""
            
            # Check for critical service failures first (MT5)
            mt5_unhealthy = not self.service_health.get("mt5", ServiceHealthState(service_name="mt5")).is_healthy
            
            if not unhealthy:
                # All services healthy → FULL_AUTO
                new_mode = ResilienceMode.FULL_AUTO
                reason = "all_services_healthy"

            elif mt5_unhealthy:
                # MT5 is down - must be PRESERVATION (full halt)
                # Don't downgrade from PRESERVATION even if outage is short
                if old_mode != ResilienceMode.PRESERVATION:
                    new_mode = ResilienceMode.PRESERVATION
                    reason = f"mt5_broker_down"
                    self.preservation_handler.activate(self.get_current_state())

            elif self.total_outage_duration_seconds > self.outage_preservation_threshold:
                # Extended outage → PRESERVATION
                new_mode = ResilienceMode.PRESERVATION
                reason = f"outage_duration_{self.total_outage_duration_seconds:.0f}s"
                if old_mode != ResilienceMode.PRESERVATION:
                    self.preservation_handler.activate(self.get_current_state())

            elif unhealthy:
                # Other services failing → TECHNICAL_ONLY or higher
                # Don't downgrade if already in PRESERVATION or EMERGENCY
                if old_mode not in (ResilienceMode.PRESERVATION, ResilienceMode.EMERGENCY):
                    new_mode = ResilienceMode.TECHNICAL_ONLY
                    reason = f"unhealthy_services_{','.join(unhealthy)}"

            # Apply mode transition
            if new_mode != old_mode:
                self.current_mode = new_mode
                logger.critical(
                    "[RESILIENCE_MODE_TRANSITION] %s → %s | Reason: %s | "
                    "Unhealthy: %s | Outage: %.0fs",
                    old_mode.value, new_mode.value, reason,
                    ",".join(unhealthy) or "none",
                    self.total_outage_duration_seconds
                )

                # Invoke callbacks
                for callback in self.mode_transition_callbacks:
                    try:
                        callback(old_mode, new_mode)
                    except Exception as e:
                        logger.error(f"Error in mode transition callback: {e}")

    def should_retry_service(self, service_name: str) -> bool:
        """Check if service retry should be attempted now."""
        with self._lock:
            if service_name not in self.service_health:
                return True
            return self.recovery_coordinator.should_retry_now(self.service_health[service_name])

    def get_time_until_retry(self, service_name: str) -> float:
        """Get seconds until next retry attempt for service."""
        with self._lock:
            if service_name not in self.service_health:
                return 0.0
            return self.recovery_coordinator.get_time_until_retry(self.service_health[service_name])

    def register_mode_change_callback(
        self, callback: Callable[[ResilienceMode, ResilienceMode], None]
    ) -> None:
        """Register callback for mode transitions."""
        with self._lock:
            self.mode_transition_callbacks.append(callback)

    def get_current_state(self) -> ResilienceState:
        """Return comprehensive resilience state."""
        with self._lock:
            unhealthy = [s for s, state in self.service_health.items() if not state.is_healthy]
            return ResilienceState(
                current_mode=self.current_mode,
                service_health={k: v for k, v in self.service_health.items()},
                outage_start_time=self.outage_start_time,
                total_outage_duration_seconds=self.total_outage_duration_seconds,
                unhealthy_services=unhealthy,
            )
    
    def get_current_status(self) -> Dict[str, Any]:
        """
        Return actionable status dict for main loop integration.
        
        This is the simplified interface for the main loop to check at the start of each cycle.
        
        Usage:
            resilience_status = self.resilience_controller.get_current_status()
            
            if resilience_status['mode'] == ResilienceMode.PRESERVATION:
                # Handle preservation logic
                continue
            
            if resilience_status['skip_llm']:
                # Skip LLM calls, use technical only
                llm_approved = True  # Auto-approve
        """
        with self._lock:
            unhealthy_services = [s for s, state in self.service_health.items() if not state.is_healthy]
            ollama_state = self.service_health.get("ollama")
            mt5_state = self.service_health.get("mt5")
            finnhub_state = self.service_health.get("finnhub")
            
            return {
                'mode': self.current_mode,
                'unhealthy_services': unhealthy_services,
                'skip_llm': ollama_state.is_circuit_breaker_active() if ollama_state else False,
                'mt5_healthy': mt5_state.is_healthy if mt5_state else True,
                'finnhub_healthy': finnhub_state.is_healthy if finnhub_state else True,
                'ollama_avg_latency_ms': ollama_state.avg_latency_ms if ollama_state else 0.0,
                'outage_duration_seconds': self.total_outage_duration_seconds,
                'can_trade': self.current_mode not in (ResilienceMode.PRESERVATION, ResilienceMode.EMERGENCY),
                'should_use_technical_only': self.current_mode == ResilienceMode.TECHNICAL_ONLY or (
                    ollama_state.is_circuit_breaker_active() if ollama_state else False
                ),
            }

    def start_monitoring(self) -> None:
        """Start background monitoring loop."""
        if self.monitoring_active:
            logger.warning("[RESILIENCE_MONITOR] Monitoring already active")
            return

        self.monitoring_active = True
        self.monitor_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="ResilienceMonitor"
        )
        self.monitor_thread.start()
        logger.info("[RESILIENCE_MONITOR] Started (interval: %.0fs)", self.monitoring_interval)

    def stop_monitoring(self) -> None:
        """Stop background monitoring loop."""
        self.monitoring_active = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        logger.info("[RESILIENCE_MONITOR] Stopped")

    def _monitoring_loop(self) -> None:
        """Background monitoring loop."""
        while self.monitoring_active:
            try:
                with self._lock:
                    # Re-evaluate mode transition every cycle
                    self.check_mode_transition()

                    # Emit periodic audit info
                    state = self.get_current_state()
                    if state.unhealthy_services:
                        logger.info(
                            "[RESILIENCE_AUDIT] Mode: %s | Unhealthy: %s | "
                            "Outage: %.0fs | Services: %s",
                            state.current_mode.value,
                            ",".join(state.unhealthy_services),
                            state.total_outage_duration_seconds,
                            ", ".join(
                                f"{k}(attempts:{v.recovery_attempts})"
                                for k, v in state.service_health.items()
                            )
                        )

                time.sleep(self.monitoring_interval)

            except Exception as e:
                logger.error(f"[RESILIENCE_MONITOR] Error: {e}")
                time.sleep(self.monitoring_interval)

    def force_mode_transition(self, target_mode: ResilienceMode) -> None:
        """Force transition to specific mode (for testing/manual intervention)."""
        with self._lock:
            old_mode = self.current_mode
            self.current_mode = target_mode
            logger.critical(
                "[RESILIENCE_FORCE_TRANSITION] %s → %s (manual override)",
                old_mode.value, target_mode.value
            )
            for callback in self.mode_transition_callbacks:
                try:
                    callback(old_mode, target_mode)
                except Exception as e:
                    logger.error(f"Error in mode transition callback: {e}")
    
    def _notify_mode_change(self, old_mode: ResilienceMode, new_mode: ResilienceMode, reason: str = "") -> None:
        """Notify callbacks of mode change."""
        logger.critical(
            "[RESILIENCE_MODE_TRANSITION] %s → %s | Reason: %s",
            old_mode.value, new_mode.value, reason
        )
        
        for callback in self.mode_transition_callbacks:
            try:
                callback(old_mode, new_mode)
            except Exception as e:
                logger.error(f"Error in mode transition callback: {e}")


# Global singleton instance
_resilience_controller: Optional[UnifiedResilienceController] = None


def get_resilience_controller() -> Optional[UnifiedResilienceController]:
    """Get global resilience controller instance."""
    return _resilience_controller


def set_resilience_controller(controller: UnifiedResilienceController) -> None:
    """Set global resilience controller instance."""
    global _resilience_controller
    _resilience_controller = controller
    _resilience_controller = controller

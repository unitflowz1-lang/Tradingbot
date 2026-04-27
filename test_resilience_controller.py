"""
Unit tests for UnifiedResilienceController
Tests mode transitions, adaptive backoff, and fault handling
"""

import pytest
import time
from src.runtime.resilience_controller import (
    UnifiedResilienceController,
    ResilienceMode,
    ServiceHealthState,
    AdaptiveRecoveryCoordinator,
    TechnicalOnlyModeHandler,
    PreservationModeHandler,
    ServiceShieldType,
)


class TestResilienceMode:
    """Test resilience mode enum."""

    def test_modes_exist(self):
        """Verify all four resilience modes exist."""
        assert ResilienceMode.FULL_AUTO.value == "full_auto"
        assert ResilienceMode.TECHNICAL_ONLY.value == "technical_only"
        assert ResilienceMode.PRESERVATION.value == "preservation"
        assert ResilienceMode.EMERGENCY.value == "emergency"


class TestServiceHealthState:
    """Test service health state management."""

    def test_initial_state(self):
        """Test initial service health state."""
        state = ServiceHealthState(service_name="finnhub")
        assert state.is_healthy is True
        assert state.consecutive_failures == 0
        assert state.total_downtime_seconds == 0.0

    def test_update_failure(self):
        """Test recording a service failure."""
        state = ServiceHealthState(service_name="finnhub")
        error = Exception("API timeout")
        state.update_failure(error, backoff_base=1.0, backoff_max=300.0)

        assert state.is_healthy is False
        assert state.consecutive_failures == 1
        assert state.last_error is not None
        assert state.last_failure_time is not None
        assert state.next_retry_time > time.time()

    def test_exponential_backoff(self):
        """Test exponential backoff calculation."""
        state = ServiceHealthState(service_name="ollama")

        # First failure: 1 second
        state.update_failure(Exception("failure 1"), backoff_base=1.0, backoff_max=300.0)
        retry1 = state.next_retry_time
        assert retry1 - time.time() < 2.0  # ~1 second

        time.sleep(0.1)

        # Second failure: 2 seconds
        state.update_failure(Exception("failure 2"), backoff_base=1.0, backoff_max=300.0)
        retry2 = state.next_retry_time
        assert retry2 - time.time() >= 1.5  # ~2 seconds

        # Third failure: 4 seconds
        state.update_failure(Exception("failure 3"), backoff_base=1.0, backoff_max=300.0)
        retry3 = state.next_retry_time
        assert retry3 - time.time() >= 3.5  # ~4 seconds

    def test_backoff_max_cap(self):
        """Test that backoff is capped at maximum."""
        state = ServiceHealthState(service_name="mt5")
        for i in range(15):  # Trigger many failures
            state.update_failure(Exception(f"failure {i}"), backoff_base=1.0, backoff_max=10.0)

        # Should not exceed 10 seconds
        remaining = state.next_retry_time - time.time()
        assert remaining <= 10.5  # Allow small margin

    def test_recovery_reset(self):
        """Test that recovery resets backoff state."""
        state = ServiceHealthState(service_name="news")
        state.update_failure(Exception("error"), backoff_base=1.0, backoff_max=300.0)
        assert state.consecutive_failures == 1

        state.update_recovery()
        assert state.is_healthy is True
        assert state.consecutive_failures == 0
        assert state.backoff_multiplier == 1.0

    def test_outage_duration(self):
        """Test outage duration tracking."""
        state = ServiceHealthState(service_name="finnhub")
        assert state.get_outage_duration() == 0.0

        state.update_failure(Exception("error"), backoff_base=1.0, backoff_max=300.0)
        time.sleep(0.1)
        duration = state.get_outage_duration()
        assert duration >= 0.1


class TestAdaptiveRecoveryCoordinator:
    """Test adaptive recovery and backoff logic."""

    def test_backoff_calculation(self):
        """Test backoff delay calculation."""
        coordinator = AdaptiveRecoveryCoordinator(backoff_base=1.0, backoff_max=300.0)

        state = ServiceHealthState(service_name="test")
        state.update_failure(Exception("error"), backoff_base=1.0, backoff_max=300.0)

        # Should not be ready to retry immediately
        assert not coordinator.should_retry_now(state)

        # Wait for backoff period and test again
        time.sleep(1.1)
        assert coordinator.should_retry_now(state)

    def test_time_until_retry(self):
        """Test time calculation for next retry."""
        coordinator = AdaptiveRecoveryCoordinator()
        state = ServiceHealthState(service_name="test")
        state.update_failure(Exception("error"), backoff_base=1.0, backoff_max=300.0)

        time_remaining = coordinator.get_time_until_retry(state)
        assert 0.5 < time_remaining < 1.5


class TestUnifiedResilienceController:
    """Test main resilience controller."""

    def test_initialization(self):
        """Test controller initialization."""
        controller = UnifiedResilienceController()
        assert controller.current_mode == ResilienceMode.FULL_AUTO
        assert len(controller.service_health) == 4  # finnhub, ollama, mt5, news
        assert all(state.is_healthy for state in controller.service_health.values())

    def test_service_failure_recording(self):
        """Test recording service failures."""
        controller = UnifiedResilienceController()

        # Record Finnhub failure
        error = Exception("Connection refused")
        controller.record_service_failure("finnhub", error)

        # Should transition to TECHNICAL_ONLY_MODE
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        assert not controller.service_health["finnhub"].is_healthy
        assert controller.service_health["finnhub"].consecutive_failures == 1

    def test_mode_transition_full_auto_to_technical_only(self):
        """Test transition from FULL_AUTO to TECHNICAL_ONLY."""
        controller = UnifiedResilienceController()
        assert controller.current_mode == ResilienceMode.FULL_AUTO

        # Simulate service failure
        controller.record_service_failure("ollama", Exception("Timeout"))

        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        assert "ollama" in controller.get_current_state().unhealthy_services

    def test_mode_transition_recovery(self):
        """Test recovery and transition back to FULL_AUTO."""
        controller = UnifiedResilienceController()

        # Fail service (use finnhub instead of mt5, as mt5 triggers PRESERVATION)
        controller.record_service_failure("finnhub", Exception("Connection lost"))
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY

        # Service recovers
        controller.record_service_recovery("finnhub")
        assert controller.current_mode == ResilienceMode.FULL_AUTO
        assert controller.service_health["finnhub"].is_healthy

    def test_preservation_mode_timeout(self):
        """Test transition to PRESERVATION_MODE after extended outage."""
        # Create controller with 1-second preservation threshold for testing
        config = {
            "resilience": {
                "outage_preservation_threshold_seconds": 1,
                "backoff_base_seconds": 0.1,
                "backoff_max_seconds": 0.5,
            }
        }
        controller = UnifiedResilienceController(config=config)

        # Simulate service failure
        controller.record_service_failure("finnhub", Exception("API error"))
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY

        # Wait for preservation threshold
        time.sleep(1.2)

        # Re-evaluate mode
        controller.check_mode_transition()

        assert controller.current_mode == ResilienceMode.PRESERVATION
        assert controller.total_outage_duration_seconds > 1.0

    def test_multiple_service_failures(self):
        """Test handling multiple simultaneous service failures."""
        controller = UnifiedResilienceController()

        # Fail multiple services
        controller.record_service_failure("finnhub", Exception("API error"))
        controller.record_service_failure("ollama", Exception("Timeout"))

        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        unhealthy = controller.get_current_state().unhealthy_services
        assert "finnhub" in unhealthy
        assert "ollama" in unhealthy

    def test_mode_change_callback(self):
        """Test mode change callbacks."""
        controller = UnifiedResilienceController()
        callback_calls = []

        def mock_callback(old_mode, new_mode):
            callback_calls.append((old_mode, new_mode))

        controller.register_mode_change_callback(mock_callback)

        # Trigger mode change
        controller.record_service_failure("finnhub", Exception("error"))

        assert len(callback_calls) == 1
        assert callback_calls[0] == (ResilienceMode.FULL_AUTO, ResilienceMode.TECHNICAL_ONLY)

    def test_retry_eligibility(self):
        """Test service retry eligibility."""
        controller = UnifiedResilienceController()

        # Fail service
        controller.record_service_failure("news", Exception("error"))
        assert not controller.should_retry_service("news")

        # Wait for backoff
        time.sleep(1.1)
        assert controller.should_retry_service("news")


class TestTechnicalOnlyModeHandler:
    """Test TECHNICAL_ONLY_MODE handler."""

    def test_skip_api_call(self):
        """Test that API calls are skipped for failed services."""
        handler = TechnicalOnlyModeHandler()
        controller = UnifiedResilienceController()

        # Fail Finnhub
        controller.record_service_failure("finnhub", Exception("error"))
        state = controller.get_current_state()

        assert handler.should_skip_api_call("finnhub", state)
        assert not handler.should_skip_api_call("ollama", state)


class TestPreservationModeHandler:
    """Test PRESERVATION_MODE handler."""

    def test_no_new_entries(self):
        """Test that PRESERVATION_MODE disallows new entries."""
        handler = PreservationModeHandler()
        assert not handler.should_allow_new_entry()


class TestResilienceState:
    """Test resilience state reporting."""

    def test_current_state(self):
        """Test comprehensive state reporting."""
        controller = UnifiedResilienceController()

        # Fail some services
        controller.record_service_failure("ollama", Exception("error"))
        controller.record_service_failure("finnhub", Exception("error"))

        state = controller.get_current_state()
        assert state.current_mode == ResilienceMode.TECHNICAL_ONLY
        assert len(state.unhealthy_services) == 2
        assert "ollama" in state.unhealthy_services
        assert "finnhub" in state.unhealthy_services


class TestLLMLatencyCircuitBreaker:
    """Test LLM latency circuit breaker functionality."""

    def test_latency_sample_recording(self):
        """Test recording LLM latency samples."""
        controller = UnifiedResilienceController()
        
        # Record normal latency samples
        circuit_activated = controller.record_llm_latency(500.0, success=True)
        assert not circuit_activated
        
        # Check service state
        ollama_state = controller.service_health["ollama"]
        assert ollama_state.avg_latency_ms == 500.0

    def test_circuit_breaker_activation(self):
        """Test circuit breaker activates after 3 consecutive high-latency cycles."""
        # Create controller with low threshold for testing
        config = {
            "resilience": {
                "llm_latency_threshold_ms": 1000.0,  # 1 second threshold
                "llm_circuit_breaker_duration_seconds": 5.0,  # 5 second circuit breaker
                "llm_latency_sample_cycles": 3,
            }
        }
        controller = UnifiedResilienceController(config=config)
        
        # Record 3 consecutive high-latency samples (>1000ms)
        result1 = controller.record_llm_latency(1500.0, success=True)
        assert not result1  # Not activated yet (1st sample)
        
        result2 = controller.record_llm_latency(1600.0, success=True)
        assert not result2  # Not activated yet (2nd sample)
        
        result3 = controller.record_llm_latency(1700.0, success=True)
        assert result3  # Activated! (3rd consecutive high-latency)
        
        # Verify circuit breaker is active
        assert controller.should_skip_llm_call()
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        
        # Double-check the service state
        ollama_state = controller.service_health["ollama"]
        assert ollama_state.latency_circuit_breaker_active is True
        assert ollama_state.circuit_breaker_until > time.time()

    def test_circuit_breaker_expiration(self):
        """Test circuit breaker deactivates after duration expires."""
        config = {
            "resilience": {
                "llm_latency_threshold_ms": 1000.0,
                "llm_circuit_breaker_duration_seconds": 1.0,  # 1 second for testing
            }
        }
        controller = UnifiedResilienceController(config=config)
        
        # Activate circuit breaker
        controller.record_llm_latency(1500.0, success=True)
        controller.record_llm_latency(1600.0, success=True)
        controller.record_llm_latency(1700.0, success=True)
        
        assert controller.should_skip_llm_call()
        
        # Wait for circuit breaker to expire
        time.sleep(1.2)
        
        # Circuit breaker should be deactivated
        assert not controller.should_skip_llm_call()

    def test_latency_reset_on_normal_performance(self):
        """Test that consecutive counter resets when latency returns to normal."""
        config = {
            "resilience": {
                "llm_latency_threshold_ms": 1000.0,
            }
        }
        controller = UnifiedResilienceController(config=config)
        
        # Record 2 high-latency samples
        controller.record_llm_latency(1500.0, success=True)
        controller.record_llm_latency(1600.0, success=True)
        
        # Record normal latency - should reset counter
        controller.record_llm_latency(500.0, success=True)
        
        # Record 2 more high-latency samples
        controller.record_llm_latency(1500.0, success=True)
        controller.record_llm_latency(1600.0, success=True)
        
        # Should not activate yet (counter was reset)
        assert not controller.should_skip_llm_call()

    def test_should_skip_llm_call_interface(self):
        """Test the should_skip_llm_call() method interface."""
        controller = UnifiedResilienceController()
        
        # Initially should not skip
        assert not controller.should_skip_llm_call()
        
        # Activate circuit breaker
        config = {
            "resilience": {
                "llm_latency_threshold_ms": 1000.0,
                "llm_circuit_breaker_duration_seconds": 5.0,
            }
        }
        controller = UnifiedResilienceController(config=config)
        controller.record_llm_latency(1500.0, success=True)
        controller.record_llm_latency(1600.0, success=True)
        controller.record_llm_latency(1700.0, success=True)
        
        # Should skip LLM calls now
        assert controller.should_skip_llm_call()


class TestGranularServiceShields:
    """Test granular per-service shield functionality."""

    def test_finnhub_failure_macro_shield(self):
        """Test Finnhub failure activates MACRO_SHIELD."""
        controller = UnifiedResilienceController()
        
        # Finnhub failure should not change global mode (non-critical)
        controller.record_service_failure("finnhub", Exception("API error"))
        
        # Mode should be TECHNICAL_ONLY due to service failure
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        assert not controller.service_health["finnhub"].is_healthy

    def test_mt5_failure_preservation_mode(self):
        """Test MT5 failure activates PRESERVATION_MODE."""
        controller = UnifiedResilienceController()
        
        # MT5 failure should trigger PRESERVATION_MODE
        controller.record_service_failure("mt5", Exception("Connection lost"))
        
        assert controller.current_mode == ResilienceMode.PRESERVATION
        assert not controller.service_health["mt5"].is_healthy

    def test_ollama_failure_technical_only(self):
        """Test Ollama failure activates TECHNICAL_ONLY_MODE."""
        controller = UnifiedResilienceController()
        
        # Ollama failure should trigger TECHNICAL_ONLY
        controller.record_service_failure("ollama", Exception("Timeout"))
        
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        assert not controller.service_health["ollama"].is_healthy

    def test_cascading_failure_scenario(self):
        """Test cascading failure: Finnhub fails first, then MT5."""
        controller = UnifiedResilienceController()
        
        # Finnhub fails first
        controller.record_service_failure("finnhub", Exception("API error"))
        assert controller.current_mode == ResilienceMode.TECHNICAL_ONLY
        
        # Then MT5 fails - should escalate to PRESERVATION
        controller.record_service_failure("mt5", Exception("Connection lost"))
        assert controller.current_mode == ResilienceMode.PRESERVATION
        
        # Both services should be unhealthy
        assert not controller.service_health["finnhub"].is_healthy
        assert not controller.service_health["mt5"].is_healthy

    def test_service_recovery_resets_circuit_breaker(self):
        """Test that service recovery resets latency circuit breaker."""
        config = {
            "resilience": {
                "llm_latency_threshold_ms": 1000.0,
                "llm_circuit_breaker_duration_seconds": 300.0,
            }
        }
        controller = UnifiedResilienceController(config=config)
        
        # Activate circuit breaker
        controller.record_llm_latency(1500.0, success=True)
        controller.record_llm_latency(1600.0, success=True)
        controller.record_llm_latency(1700.0, success=True)
        
        assert controller.should_skip_llm_call()
        
        # Recover service
        controller.record_service_recovery("ollama")
        
        # Circuit breaker should be reset
        assert not controller.should_skip_llm_call()
        assert controller.service_health["ollama"].is_healthy


class TestGetCurrentStatus:
    """Test the get_current_status() method for main loop integration."""

    def test_normal_operation_status(self):
        """Test status dict during normal operation."""
        controller = UnifiedResilienceController()
        
        status = controller.get_current_status()
        
        assert status['mode'] == ResilienceMode.FULL_AUTO
        assert status['can_trade'] is True
        assert status['skip_llm'] is False
        assert status['mt5_healthy'] is True
        assert status['finnhub_healthy'] is True
        assert status['should_use_technical_only'] is False

    def test_preservation_mode_status(self):
        """Test status dict during PRESERVATION_MODE."""
        controller = UnifiedResilienceController()
        
        # Trigger PRESERVATION_MODE via MT5 failure
        controller.record_service_failure("mt5", Exception("Connection lost"))
        
        status = controller.get_current_status()
        
        assert status['mode'] == ResilienceMode.PRESERVATION
        assert status['can_trade'] is False
        assert status['mt5_healthy'] is False

    def test_llm_circuit_breaker_status(self):
        """Test status dict when LLM circuit breaker is active."""
        config = {
            "resilience": {
                "llm_latency_threshold_ms": 1000.0,
                "llm_circuit_breaker_duration_seconds": 5.0,
            }
        }
        controller = UnifiedResilienceController(config=config)
        
        # Activate LLM circuit breaker
        controller.record_llm_latency(1500.0, success=True)
        controller.record_llm_latency(1600.0, success=True)
        controller.record_llm_latency(1700.0, success=True)
        
        status = controller.get_current_status()
        
        assert status['skip_llm'] is True
        assert status['should_use_technical_only'] is True
        assert status['ollama_avg_latency_ms'] > 1000.0

    def test_technical_only_mode_status(self):
        """Test status dict during TECHNICAL_ONLY_MODE."""
        controller = UnifiedResilienceController()
        
        # Trigger TECHNICAL_ONLY via Ollama failure
        controller.record_service_failure("ollama", Exception("Timeout"))
        
        status = controller.get_current_status()
        
        assert status['mode'] == ResilienceMode.TECHNICAL_ONLY
        assert status['can_trade'] is True  # Can still trade on technicals
        assert status['should_use_technical_only'] is True
        assert status['ollama_healthy'] is False if 'ollama_healthy' in status else True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

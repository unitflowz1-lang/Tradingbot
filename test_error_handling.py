"""
Unit tests for error handling and recovery mechanisms.
"""
import unittest
import tempfile
import shutil
import time
import threading
from unittest.mock import Mock, patch, MagicMock
import os
import sys

# Add src to path for imports
sys.path.append('src')

import torch
import numpy as np
import redis

from src.rl.error_handling.error_handler import (
    ErrorHandler, ErrorInfo, ErrorCategory, ErrorSeverity,
    ModelRecoveryStrategy, NetworkRecoveryStrategy, ResourceRecoveryStrategy,
    TrainingRecoveryStrategy, error_handler_decorator
)
from src.rl.error_handling.graceful_degradation import (
    GracefulDegradationManager, DegradationLevel, SystemState,
    ReducedComplexityStrategy, FallbackModelStrategy, EmergencyModeStrategy
)

class TestErrorHandler(unittest.TestCase):
    """Test error handling functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Mock Redis
        self.mock_redis = Mock(spec=redis.Redis)
        self.mock_redis.ping.return_value = True
        
        # Create error handler with mocked Redis
        with patch('redis.Redis', return_value=self.mock_redis):
            self.error_handler = ErrorHandler()
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_error_info_creation(self):
        """Test error info creation."""
        exception = ValueError("Test error")
        context = {'component': 'test', 'data': 'test_data'}
        
        # Handle error
        success = self.error_handler.handle_error(
            exception=exception,
            category=ErrorCategory.TRAINING,
            severity=ErrorSeverity.MEDIUM,
            context=context,
            component='test_component'
        )
        
        # Check error was stored
        self.assertEqual(len(self.error_handler.error_history), 1)
        
        error_info = self.error_handler.error_history[0]
        self.assertEqual(error_info.category, ErrorCategory.TRAINING)
        self.assertEqual(error_info.severity, ErrorSeverity.MEDIUM)
        self.assertEqual(error_info.message, "Test error")
        self.assertIn('component', error_info.context)
    
    def test_model_recovery_strategy(self):
        """Test model recovery strategy."""
        strategy = ModelRecoveryStrategy()
        
        # Create test error
        error_info = ErrorInfo(
            error_id="test_error",
            category=ErrorCategory.MODEL,
            severity=ErrorSeverity.MEDIUM,
            message="Model loading failed",
            exception=Exception("Model error"),
            context={},
            timestamp=time.time(),
            stack_trace="test_trace"
        )
        
        # Test can_recover
        self.assertTrue(strategy.can_recover(error_info))
        
        # Test recovery with checkpoint
        mock_agent = Mock()
        mock_agent.load_checkpoint.return_value = True
        
        context = {
            'agent': mock_agent,
            'checkpoint_path': '/fake/path/checkpoint.pt'
        }
        
        with patch('os.path.exists', return_value=True):
            success = strategy.recover(error_info, context)
            self.assertTrue(success)
            mock_agent.load_checkpoint.assert_called_once()
    
    def test_network_recovery_strategy(self):
        """Test network recovery strategy."""
        strategy = NetworkRecoveryStrategy()
        
        # Create network error
        error_info = ErrorInfo(
            error_id="test_error",
            category=ErrorCategory.NETWORK,
            severity=ErrorSeverity.HIGH,
            message="Connection failed",
            exception=ConnectionError("Network error"),
            context={},
            timestamp=time.time(),
            stack_trace="test_trace"
        )
        
        # Test can_recover
        self.assertTrue(strategy.can_recover(error_info))
        
        # Test recovery with reconnection
        mock_connection = Mock()
        mock_connection.reconnect.return_value = True
        
        context = {'connection': mock_connection}
        
        with patch('time.sleep'):  # Skip sleep in tests
            success = strategy.recover(error_info, context)
            self.assertTrue(success)
            mock_connection.reconnect.assert_called_once()
    
    def test_resource_recovery_strategy(self):
        """Test resource recovery strategy."""
        strategy = ResourceRecoveryStrategy()
        
        # Create resource error
        error_info = ErrorInfo(
            error_id="test_error",
            category=ErrorCategory.RESOURCE,
            severity=ErrorSeverity.MEDIUM,
            message="CUDA out of memory",
            exception=RuntimeError("CUDA error"),
            context={},
            timestamp=time.time(),
            stack_trace="test_trace"
        )
        
        # Test can_recover
        self.assertTrue(strategy.can_recover(error_info))
        
        # Test recovery
        mock_config = Mock()
        mock_config.batch_size = 32
        
        context = {'config': mock_config}
        
        with patch('torch.cuda.is_available', return_value=True):
            with patch('torch.cuda.empty_cache'):
                success = strategy.recover(error_info, context)
                self.assertTrue(success)
                self.assertEqual(mock_config.batch_size, 16)  # Should be halved
    
    def test_training_recovery_strategy(self):
        """Test training recovery strategy."""
        strategy = TrainingRecoveryStrategy()
        
        # Create training error
        error_info = ErrorInfo(
            error_id="test_error",
            category=ErrorCategory.TRAINING,
            severity=ErrorSeverity.MEDIUM,
            message="Training loss exploded",
            exception=RuntimeError("Loss error"),
            context={},
            timestamp=time.time(),
            stack_trace="test_trace"
        )
        
        # Test can_recover
        self.assertTrue(strategy.can_recover(error_info))
        
        # Test recovery
        mock_environment = Mock()
        mock_agent = Mock()
        mock_agent.learning_rate = 0.001
        mock_optimizer = Mock()
        mock_optimizer.param_groups = [{'lr': 0.001}]
        mock_agent.optimizer = mock_optimizer
        
        context = {
            'environment': mock_environment,
            'agent': mock_agent
        }
        
        success = strategy.recover(error_info, context)
        self.assertTrue(success)
        mock_environment.reset.assert_called_once()
        self.assertEqual(mock_agent.learning_rate, 0.0005)  # Should be halved
    
    def test_circuit_breaker(self):
        """Test circuit breaker functionality."""
        # Simulate multiple failures
        exception = RuntimeError("Repeated error")
        context = {'component': 'test'}
        
        # First failure should attempt recovery
        success1 = self.error_handler.handle_error(
            exception=exception,
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            context=context,
            component='test_component'
        )
        
        # Immediate second failure should trigger circuit breaker
        success2 = self.error_handler.handle_error(
            exception=exception,
            category=ErrorCategory.SYSTEM,
            severity=ErrorSeverity.HIGH,
            context=context,
            component='test_component'
        )
        
        # Circuit breaker should be open
        self.assertTrue(self.error_handler._is_circuit_open('test_component'))
    
    def test_error_statistics(self):
        """Test error statistics calculation."""
        # Add some test errors
        for i in range(5):
            exception = ValueError(f"Test error {i}")
            self.error_handler.handle_error(
                exception=exception,
                category=ErrorCategory.TRAINING,
                severity=ErrorSeverity.MEDIUM,
                context={},
                component='test'
            )
        
        # Get statistics
        stats = self.error_handler.get_error_statistics()
        
        self.assertEqual(stats['total_errors'], 5)
        self.assertIn('error_counts', stats)
        self.assertIn('recovery_rate', stats)
        self.assertIn('most_common_errors', stats)
    
    def test_error_decorator(self):
        """Test error handling decorator."""
        
        @error_handler_decorator(
            category=ErrorCategory.TRAINING,
            severity=ErrorSeverity.MEDIUM,
            component='test_function'
        )
        def failing_function():
            raise ValueError("Function failed")
        
        # Set error handler for decorator
        failing_function._error_handler = self.error_handler
        
        # Call function - should not raise exception due to decorator
        result = failing_function()
        self.assertIsNone(result)
        
        # Check error was handled
        self.assertEqual(len(self.error_handler.error_history), 1)

class TestGracefulDegradation(unittest.TestCase):
    """Test graceful degradation functionality."""
    
    def setUp(self):
        """Set up test environment."""
        # Mock error handler
        self.mock_error_handler = Mock()
        self.mock_error_handler.get_error_statistics.return_value = {
            'recovery_rate': 0.8,
            'recent_errors': 5
        }
        self.mock_error_handler.error_history = []
        
        self.degradation_manager = GracefulDegradationManager(self.mock_error_handler)
    
    def test_reduced_complexity_strategy(self):
        """Test reduced complexity degradation strategy."""
        strategy = ReducedComplexityStrategy()
        
        # Create system state with high resource usage
        system_state = SystemState(
            degradation_level=DegradationLevel.NORMAL,
            active_components=['agent', 'environment'],
            disabled_components=[],
            performance_metrics={'resource_usage': 0.9},
            timestamp=time.time()
        )
        
        # Test should_activate
        should_activate = strategy.should_activate(system_state, 0.05)
        self.assertTrue(should_activate)
        
        # Test activation
        mock_config = Mock()
        mock_config.batch_size = 32
        
        context = {
            'training_config': mock_config,
            'feature_flags': {},
            'agent': Mock()
        }
        
        success = strategy.activate(context)
        self.assertTrue(success)
        self.assertTrue(strategy.is_active)
        self.assertEqual(mock_config.batch_size, 16)
    
    def test_fallback_model_strategy(self):
        """Test fallback model degradation strategy."""
        strategy = FallbackModelStrategy()
        
        # Create system state with high model error rate
        system_state = SystemState(
            degradation_level=DegradationLevel.NORMAL,
            active_components=['agent'],
            disabled_components=[],
            performance_metrics={'model_error_rate': 0.3},
            timestamp=time.time()
        )
        
        # Test should_activate
        should_activate = strategy.should_activate(system_state, 0.1)
        self.assertTrue(should_activate)
        
        # Test activation
        mock_agent = Mock()
        mock_fallback_agent = Mock()
        
        context = {
            'agent': mock_agent,
            'fallback_agent': mock_fallback_agent,
            'trading_strategy': 'aggressive',
            'position_sizer': Mock()
        }
        
        success = strategy.activate(context)
        self.assertTrue(success)
        self.assertTrue(strategy.is_active)
        self.assertEqual(context['agent'], mock_fallback_agent)
        self.assertEqual(context['trading_strategy'], 'conservative')
    
    def test_emergency_mode_strategy(self):
        """Test emergency mode degradation strategy."""
        strategy = EmergencyModeStrategy()
        
        # Create system state with critical errors
        system_state = SystemState(
            degradation_level=DegradationLevel.NORMAL,
            active_components=['agent'],
            disabled_components=[],
            performance_metrics={'critical_error_rate': 0.6},
            timestamp=time.time()
        )
        
        # Test should_activate
        should_activate = strategy.should_activate(system_state, 0.3)
        self.assertTrue(should_activate)
        
        # Test activation
        mock_trainer = Mock()
        mock_position_manager = Mock()
        mock_service = Mock()
        
        context = {
            'trainer': mock_trainer,
            'position_manager': mock_position_manager,
            'trading_mode': 'active',
            'services': {'non_essential': mock_service}
        }
        
        success = strategy.activate(context)
        self.assertTrue(success)
        self.assertTrue(strategy.is_active)
        self.assertEqual(context['trading_mode'], 'hold_only')
        mock_trainer.stop_training.assert_called_once()
        mock_position_manager.close_all_positions.assert_called_once()
    
    def test_degradation_manager_monitoring(self):
        """Test degradation manager monitoring."""
        context = {
            'agent': Mock(),
            'environment': Mock(),
            'trainer': Mock(),
            'data_loader': Mock()
        }
        
        # Mock system state updates
        with patch.object(self.degradation_manager, '_update_system_state'):
            with patch.object(self.degradation_manager, '_calculate_error_rate', return_value=0.05):
                with patch.object(self.degradation_manager, '_check_degradation_strategies'):
                    
                    # Start monitoring
                    self.degradation_manager.start_monitoring(context)
                    
                    # Let it run briefly
                    time.sleep(0.1)
                    
                    # Stop monitoring
                    self.degradation_manager.stop_monitoring()
                    
                    self.assertFalse(self.degradation_manager.monitoring_active)
    
    def test_force_degradation_level(self):
        """Test forcing specific degradation level."""
        context = {
            'training_config': Mock(),
            'feature_flags': {},
            'agent': Mock()
        }
        
        # Force reduced complexity
        success = self.degradation_manager.force_degradation_level(
            DegradationLevel.REDUCED,
            context
        )
        
        self.assertTrue(success)
        self.assertEqual(self.degradation_manager.current_level, DegradationLevel.REDUCED)
        
        # Check that reduced complexity strategy is active
        reduced_strategy = next(
            (s for s in self.degradation_manager.strategies if s.name == 'reduced_complexity'),
            None
        )
        self.assertIsNotNone(reduced_strategy)
        self.assertTrue(reduced_strategy.is_active)
    
    @patch('psutil.cpu_percent', return_value=75.0)
    @patch('psutil.virtual_memory')
    def test_system_state_update(self, mock_memory, mock_cpu):
        """Test system state update."""
        # Mock memory usage
        mock_memory.return_value.percent = 60.0
        
        context = {
            'agent': Mock(),
            'environment': Mock()
        }
        
        # Update system state
        self.degradation_manager._update_system_state(context)
        
        # Check system state
        state = self.degradation_manager.get_current_state()
        self.assertIsNotNone(state)
        self.assertIn('cpu_usage', state.performance_metrics)
        self.assertIn('memory_usage', state.performance_metrics)
        self.assertEqual(len(state.active_components), 2)

class TestErrorRecoveryIntegration(unittest.TestCase):
    """Test integration between error handling and graceful degradation."""
    
    def setUp(self):
        """Set up test environment."""
        with patch('redis.Redis'):
            self.error_handler = ErrorHandler()
        
        self.degradation_manager = GracefulDegradationManager(self.error_handler)
    
    def test_error_triggered_degradation(self):
        """Test that errors trigger appropriate degradation."""
        context = {
            'training_config': Mock(),
            'feature_flags': {},
            'agent': Mock()
        }
        
        # Simulate multiple errors to trigger degradation
        for i in range(10):
            exception = RuntimeError(f"Training error {i}")
            self.error_handler.handle_error(
                exception=exception,
                category=ErrorCategory.TRAINING,
                severity=ErrorSeverity.MEDIUM,
                context=context,
                component='trainer'
            )
        
        # Update system state with high error rate
        self.degradation_manager.system_state.performance_metrics['error_rate'] = 0.15
        
        # Check degradation strategies
        error_rate = 0.15
        self.degradation_manager._check_degradation_strategies(context, error_rate)
        
        # Should activate reduced complexity strategy
        reduced_strategy = next(
            (s for s in self.degradation_manager.strategies if s.name == 'reduced_complexity'),
            None
        )
        self.assertIsNotNone(reduced_strategy)
    
    def test_recovery_and_restoration(self):
        """Test recovery and restoration of normal operation."""
        context = {
            'training_config': Mock(),
            'feature_flags': {},
            'agent': Mock(),
            'original_config': {'batch_size': 32}
        }
        
        # Force degradation
        self.degradation_manager.force_degradation_level(
            DegradationLevel.REDUCED,
            context
        )
        
        # Simulate improvement (low error rate)
        self.degradation_manager.system_state.performance_metrics['error_rate'] = 0.02
        self.degradation_manager.system_state.performance_metrics['resource_usage'] = 0.5
        
        # Check degradation strategies with low error rate
        self.degradation_manager._check_degradation_strategies(context, 0.02)
        
        # Should deactivate reduced complexity strategy
        reduced_strategy = next(
            (s for s in self.degradation_manager.strategies if s.name == 'reduced_complexity'),
            None
        )
        self.assertIsNotNone(reduced_strategy)

if __name__ == '__main__':
    # Set up logging
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Run tests
    unittest.main(verbosity=2)
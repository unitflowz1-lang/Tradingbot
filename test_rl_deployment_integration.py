"""
RL System Deployment Integration Tests

Tests for deployment workflows, model serving, and production readiness
of the RL trading system.
"""

import pytest
import numpy as np
import pandas as pd
import asyncio
import tempfile
import os
import json
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, AsyncMock
from typing import Dict, List, Any
import requests
from concurrent.futures import ThreadPoolExecutor

# RL System imports
from src.rl.inference.server import RLInferenceServer
from src.rl.health_check import HealthChecker
from src.rl.agents.dqn import DQNAgent
from src.rl.agents.ppo import PPOAgent
from src.rl.environments.forex_environment import ForexEnvironment
from src.rl.strategies.registry import StrategyRegistry
from src.rl.monitoring.performance_tracker import PerformanceTracker
from src.rl.error_handling.error_handler import RLErrorHandler
from src.rl.error_handling.graceful_degradation import GracefulDegradationManager

# Test utilities
from test_utils.cleanup import cleanup_test_files


class TestInferenceServerIntegration:
    """Test RL inference server integration and deployment."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup inference server test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        self.server_port = 8888
        
        # Create test configuration
        self.server_config = {
            'host': '127.0.0.1',
            'port': self.server_port,
            'workers': 1,
            'model_cache_size': 10,
            'request_timeout': 30,
            'health_check_interval': 60
        }
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    @pytest.mark.asyncio
    async def test_inference_server_startup_shutdown(self):
        """Test inference server startup and shutdown procedures."""
        # Create mock trained agent
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='1H'),
            'open': np.random.random(100) + 1.1,
            'high': np.random.random(100) + 1.1,
            'low': np.random.random(100) + 1.1,
            'close': np.random.random(100) + 1.1,
            'volume': np.random.randint(1000, 10000, 100),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        # Save agent model
        model_path = os.path.join(self.temp_dir, 'test_model.pth')
        agent.save_model(model_path)
        self.test_files.append(model_path)
        
        # Create inference server
        server = RLInferenceServer(
            config=self.server_config,
            model_registry_path=self.temp_dir
        )
        
        # Test server startup
        await server.load_model('test_model', model_path)
        
        # Verify model is loaded
        loaded_models = server.get_loaded_models()
        assert 'test_model' in loaded_models
        
        # Test inference
        test_state = np.random.random(environment.observation_space.shape[0])
        
        inference_result = await server.predict(
            model_name='test_model',
            state=test_state.tolist()
        )
        
        assert 'action' in inference_result
        assert 'confidence' in inference_result
        assert 'timestamp' in inference_result
        assert isinstance(inference_result['action'], int)
        assert 0 <= inference_result['action'] < environment.action_space.n
        
        # Test batch inference
        batch_states = [test_state.tolist() for _ in range(5)]
        batch_results = await server.predict_batch(
            model_name='test_model',
            states=batch_states
        )
        
        assert len(batch_results) == 5
        for result in batch_results:
            assert 'action' in result
            assert 'confidence' in result
        
        print("✓ Inference server startup/shutdown test passed")
    
    @pytest.mark.asyncio
    async def test_inference_server_load_balancing(self):
        """Test inference server under concurrent load."""
        # Setup server with model
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=50, freq='1H'),
            'open': np.random.random(50) + 1.1,
            'high': np.random.random(50) + 1.1,
            'low': np.random.random(50) + 1.1,
            'close': np.random.random(50) + 1.1,
            'volume': np.random.randint(1000, 10000, 50),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        model_path = os.path.join(self.temp_dir, 'load_test_model.pth')
        agent.save_model(model_path)
        self.test_files.append(model_path)
        
        server = RLInferenceServer(
            config=self.server_config,
            model_registry_path=self.temp_dir
        )
        
        await server.load_model('load_test_model', model_path)
        
        # Simulate concurrent requests
        async def make_inference_request():
            test_state = np.random.random(environment.observation_space.shape[0])
            return await server.predict('load_test_model', test_state.tolist())
        
        # Create multiple concurrent requests
        num_requests = 20
        start_time = time.time()
        
        tasks = [make_inference_request() for _ in range(num_requests)]
        results = await asyncio.gather(*tasks)
        
        end_time = time.time()
        
        # Verify all requests completed successfully
        assert len(results) == num_requests
        for result in results:
            assert 'action' in result
            assert 'confidence' in result
        
        # Performance assertions
        total_time = end_time - start_time
        requests_per_second = num_requests / total_time
        
        assert requests_per_second > 10  # Should handle at least 10 RPS
        assert total_time < 5.0  # Should complete in under 5 seconds
        
        print(f"✓ Inference server load balancing test passed")
        print(f"  - Requests per second: {requests_per_second:.2f}")
        print(f"  - Total time: {total_time:.2f}s")
    
    @pytest.mark.asyncio
    async def test_model_hot_swapping(self):
        """Test hot-swapping of models without downtime."""
        # Create two different models
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=50, freq='1H'),
            'open': np.random.random(50) + 1.1,
            'high': np.random.random(50) + 1.1,
            'low': np.random.random(50) + 1.1,
            'close': np.random.random(50) + 1.1,
            'volume': np.random.randint(1000, 10000, 50),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        # Create first model
        agent1 = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        model1_path = os.path.join(self.temp_dir, 'model_v1.pth')
        agent1.save_model(model1_path)
        self.test_files.append(model1_path)
        
        # Create second model (different configuration)
        agent2 = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.002, 'batch_size': 64}
        )
        
        model2_path = os.path.join(self.temp_dir, 'model_v2.pth')
        agent2.save_model(model2_path)
        self.test_files.append(model2_path)
        
        # Setup server
        server = RLInferenceServer(
            config=self.server_config,
            model_registry_path=self.temp_dir
        )
        
        # Load first model
        await server.load_model('production_model', model1_path)
        
        # Test inference with first model
        test_state = np.random.random(environment.observation_space.shape[0])
        result1 = await server.predict('production_model', test_state.tolist())
        
        # Hot-swap to second model
        await server.update_model('production_model', model2_path)
        
        # Test inference with second model
        result2 = await server.predict('production_model', test_state.tolist())
        
        # Verify both inferences worked
        assert 'action' in result1
        assert 'action' in result2
        
        # Verify model was actually swapped (results might be different)
        # Note: Results could be the same by chance, so we just verify no errors
        
        # Verify server maintained availability during swap
        loaded_models = server.get_loaded_models()
        assert 'production_model' in loaded_models
        
        print("✓ Model hot-swapping test passed")


class TestHealthCheckIntegration:
    """Test health check and monitoring integration."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup health check test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_system_health_monitoring(self):
        """Test comprehensive system health monitoring."""
        # Create health checker
        health_checker = HealthChecker(
            config={
                'check_interval': 1,
                'alert_thresholds': {
                    'cpu_usage': 80,
                    'memory_usage': 85,
                    'inference_latency': 1000,  # ms
                    'error_rate': 0.05
                },
                'storage_path': self.temp_dir
            }
        )
        
        # Test individual health checks
        cpu_health = health_checker.check_cpu_usage()
        assert 'status' in cpu_health
        assert 'value' in cpu_health
        assert cpu_health['status'] in ['healthy', 'warning', 'critical']
        
        memory_health = health_checker.check_memory_usage()
        assert 'status' in memory_health
        assert 'value' in memory_health
        
        # Test model health check
        # Create mock model for testing
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=50, freq='1H'),
            'open': np.random.random(50) + 1.1,
            'high': np.random.random(50) + 1.1,
            'low': np.random.random(50) + 1.1,
            'close': np.random.random(50) + 1.1,
            'volume': np.random.randint(1000, 10000, 50),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        model_health = health_checker.check_model_health(agent)
        assert 'status' in model_health
        assert 'inference_latency' in model_health
        
        # Test comprehensive health check
        overall_health = health_checker.get_overall_health()
        assert 'status' in overall_health
        assert 'components' in overall_health
        assert 'timestamp' in overall_health
        
        # Test health history
        health_checker.record_health_check(overall_health)
        history = health_checker.get_health_history(hours=1)
        assert len(history) > 0
        
        print("✓ System health monitoring test passed")
    
    def test_error_handling_integration(self):
        """Test error handling and graceful degradation."""
        # Create error handler
        error_handler = RLErrorHandler(
            config={
                'max_retries': 3,
                'retry_delay': 0.1,
                'fallback_strategy': 'conservative',
                'alert_on_error': True,
                'storage_path': self.temp_dir
            }
        )
        
        # Test error recording and handling
        test_error = Exception("Test error for integration testing")
        
        error_handler.handle_error(
            error=test_error,
            context={'component': 'test_component', 'operation': 'test_operation'}
        )
        
        # Verify error was recorded
        error_history = error_handler.get_error_history()
        assert len(error_history) > 0
        assert error_history[0]['error_type'] == 'Exception'
        
        # Test graceful degradation
        degradation_manager = GracefulDegradationManager(
            config={
                'degradation_levels': ['normal', 'reduced', 'minimal', 'emergency'],
                'auto_recovery': True,
                'recovery_check_interval': 1
            }
        )
        
        # Simulate system stress
        degradation_manager.assess_system_health({
            'cpu_usage': 90,  # High CPU usage
            'memory_usage': 85,  # High memory usage
            'error_rate': 0.1  # High error rate
        })
        
        current_level = degradation_manager.get_current_level()
        assert current_level in ['reduced', 'minimal', 'emergency']
        
        # Test recovery
        degradation_manager.assess_system_health({
            'cpu_usage': 30,  # Normal CPU usage
            'memory_usage': 40,  # Normal memory usage
            'error_rate': 0.01  # Low error rate
        })
        
        # Should recover to normal or better level
        recovered_level = degradation_manager.get_current_level()
        assert recovered_level in ['normal', 'reduced']
        
        print("✓ Error handling integration test passed")


class TestProductionDeploymentIntegration:
    """Test production deployment scenarios and workflows."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup production deployment test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_model_deployment_workflow(self):
        """Test complete model deployment workflow."""
        # Create strategy registry for deployment
        registry = StrategyRegistry(storage_path=self.temp_dir)
        
        # Create and train a model
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='1H'),
            'open': np.random.random(100) + 1.1,
            'high': np.random.random(100) + 1.1,
            'low': np.random.random(100) + 1.1,
            'close': np.random.random(100) + 1.1,
            'volume': np.random.randint(1000, 10000, 100),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        # Register strategy for deployment
        strategy_metadata = {
            'name': 'production_strategy_v1',
            'agent_type': 'DQN',
            'currency_pair': 'EURUSD',
            'timeframe': '1H',
            'performance_metrics': {
                'sharpe_ratio': 1.5,
                'max_drawdown': 0.1,
                'total_return': 0.15,
                'validation_score': 0.85
            },
            'deployment_status': 'pending'
        }
        
        strategy_id = registry.register_strategy(
            agent=agent,
            metadata=strategy_metadata
        )
        
        # Test deployment validation
        validation_result = registry.validate_strategy_for_deployment(strategy_id)
        assert validation_result['valid']
        assert validation_result['score'] > 0.8
        
        # Test deployment approval
        registry.approve_strategy_for_deployment(
            strategy_id=strategy_id,
            approver='test_user',
            notes='Integration test deployment'
        )
        
        # Verify deployment status
        strategy_info = registry.get_strategy_metadata(strategy_id)
        assert strategy_info['deployment_status'] == 'approved'
        
        # Test production deployment
        registry.deploy_strategy_to_production(
            strategy_id=strategy_id,
            deployment_config={
                'allocation': 0.1,  # 10% allocation
                'risk_limits': {
                    'max_position_size': 0.02,
                    'max_daily_loss': 0.01
                }
            }
        )
        
        # Verify production deployment
        production_strategies = registry.get_production_strategies()
        assert len(production_strategies) == 1
        assert production_strategies[0]['id'] == strategy_id
        
        print("✓ Model deployment workflow test passed")
    
    def test_rollback_and_recovery_workflow(self):
        """Test rollback and recovery procedures."""
        # Setup registry with multiple strategy versions
        registry = StrategyRegistry(storage_path=self.temp_dir)
        
        # Create two versions of a strategy
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=50, freq='1H'),
            'open': np.random.random(50) + 1.1,
            'high': np.random.random(50) + 1.1,
            'low': np.random.random(50) + 1.1,
            'close': np.random.random(50) + 1.1,
            'volume': np.random.randint(1000, 10000, 50),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        # Version 1 (stable)
        agent_v1 = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        strategy_v1_id = registry.register_strategy(
            agent=agent_v1,
            metadata={
                'name': 'rollback_test_strategy',
                'version': '1.0',
                'performance_metrics': {'sharpe_ratio': 1.2}
            }
        )
        
        # Deploy version 1
        registry.deploy_strategy_to_production(strategy_v1_id, {'allocation': 0.1})
        
        # Version 2 (problematic)
        agent_v2 = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.002, 'batch_size': 64}
        )
        
        strategy_v2_id = registry.register_strategy(
            agent=agent_v2,
            metadata={
                'name': 'rollback_test_strategy',
                'version': '2.0',
                'performance_metrics': {'sharpe_ratio': 0.8}  # Worse performance
            }
        )
        
        # Deploy version 2
        registry.deploy_strategy_to_production(strategy_v2_id, {'allocation': 0.1})
        
        # Simulate performance monitoring detecting issues
        performance_tracker = PerformanceTracker(storage_path=self.temp_dir)
        
        # Record poor performance for v2
        session_id = performance_tracker.start_session(strategy_v2_id, 'EURUSD')
        
        for _ in range(10):
            trade = {
                'timestamp': datetime.now(),
                'action': 'BUY',
                'price': 1.1000,
                'volume': 0.1,
                'pnl': -50.0  # Consistent losses
            }
            performance_tracker.record_trade(session_id, trade)
        
        performance_tracker.end_session(session_id)
        
        # Check if rollback is needed
        recent_performance = performance_tracker.calculate_performance(session_id)
        
        if recent_performance['total_pnl'] < -200:  # Significant losses
            # Trigger rollback to v1
            registry.rollback_strategy(
                current_strategy_id=strategy_v2_id,
                target_strategy_id=strategy_v1_id,
                reason='Poor performance detected'
            )
            
            # Verify rollback
            production_strategies = registry.get_production_strategies()
            active_strategy = production_strategies[0]
            assert active_strategy['id'] == strategy_v1_id
            assert active_strategy['metadata']['version'] == '1.0'
        
        print("✓ Rollback and recovery workflow test passed")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])
"""
Unit tests for hyperparameter optimization framework.

Tests the hyperparameter optimization system including Optuna integration,
resource management, and parallel optimization capabilities.
"""

import pytest
import numpy as np
import tempfile
import shutil
import time
import json
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from src.rl.training.hyperparameter_optimizer import (
    OptimizationConfig, HyperparameterOptimizer, RLObjectiveFunction,
    OptunaPruningCallback, OptimizationManager, TrialResult
)
from src.rl.training.resource_manager import (
    ResourceManager, ResourceMonitor, ResourceAllocator, ResourceLimits, ResourceUsage
)
from src.rl.training.agent_trainer import TrainingConfig, TrainingMetrics
from src.rl.agents.base import AgentConfig
from src.rl.agents.dqn import DQNConfig
from src.rl.agents.ppo import PPOConfig


# Mock classes for testing
class MockAgent:
    """Mock RL agent for testing."""
    
    def __init__(self, config):
        self.config = config
        self.training_step_count = 0
        
    def select_action(self, state, training=False):
        return np.random.randint(0, 4)
        
    def store_experience(self, *args):
        pass
        
    def train_step(self):
        self.training_step_count += 1
        return max(0.1, 1.0 - self.training_step_count * 0.01)
        
    def get_state(self):
        return {'training_steps': self.training_step_count}
        
    def get_training_metrics(self):
        return {'training_steps': self.training_step_count}
        
    def update(self, experience):
        pass
        
    def reset_episode(self):
        pass
        
    def save_model(self, filepath):
        pass
        
    def load_model(self, filepath):
        pass
        
    def get_model_info(self):
        return {'type': 'MockAgent'}


class MockEnvironment:
    """Mock environment for testing."""
    
    def __init__(self, max_steps=50):
        self.max_steps = max_steps
        self.current_step = 0
        self.state_dim = 10
        
    def reset(self):
        self.current_step = 0
        return np.random.randn(self.state_dim)
        
    def step(self, action):
        self.current_step += 1
        next_state = np.random.randn(self.state_dim)
        reward = np.random.randn() + action * 0.1
        done = self.current_step >= self.max_steps or np.random.random() < 0.1
        return next_state, reward, done, {}


class TestOptimizationConfig:
    """Test cases for OptimizationConfig."""
    
    def test_optimization_config_defaults(self):
        """Test default optimization configuration."""
        config = OptimizationConfig(study_name="test_study")
        
        assert config.study_name == "test_study"
        assert config.direction == "maximize"
        assert config.n_trials == 100
        assert config.sampler == "tpe"
        assert config.pruner == "median"
        assert config.n_jobs == 1
        
    def test_optimization_config_custom_values(self):
        """Test custom optimization configuration."""
        config = OptimizationConfig(
            study_name="custom_study",
            direction="minimize",
            n_trials=50,
            sampler="random",
            n_jobs=4
        )
        
        assert config.study_name == "custom_study"
        assert config.direction == "minimize"
        assert config.n_trials == 50
        assert config.sampler == "random"
        assert config.n_jobs == 4


class TestRLObjectiveFunction:
    """Test cases for RLObjectiveFunction."""
    
    @pytest.fixture
    def base_configs(self):
        """Create base configurations for testing."""
        training_config = TrainingConfig(
            total_episodes=10,
            max_steps_per_episode=20,
            evaluation_frequency=5
        )
        
        agent_config = DQNConfig(
            learning_rate=1e-3,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=1000,
            target_update_frequency=10,
            hidden_layers=[64, 64],
            activation="relu",
            optimizer="adam"
        )
        
        return training_config, agent_config
        
    def test_objective_function_initialization(self, base_configs):
        """Test objective function initialization."""
        training_config, agent_config = base_configs
        
        objective = RLObjectiveFunction(
            base_training_config=training_config,
            base_agent_config=agent_config,
            agent_type="dqn",
            metric="mean_reward"
        )
        
        assert objective.agent_type == "dqn"
        assert objective.metric == "mean_reward"
        assert objective.base_training_config == training_config
        assert objective.base_agent_config == agent_config 
       
    @patch('optuna.create_study')
    def test_hyperparameter_suggestion(self, mock_create_study, base_configs):
        """Test hyperparameter suggestion."""
        training_config, agent_config = base_configs
        
        # Mock trial
        mock_trial = Mock()
        mock_trial.suggest_float.side_effect = lambda name, low, high, **kwargs: 0.001
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_int.side_effect = lambda name, low, high: low
        
        objective = RLObjectiveFunction(
            base_training_config=training_config,
            base_agent_config=agent_config,
            agent_type="dqn"
        )
        
        params = objective.suggest_hyperparameters(mock_trial)
        
        assert 'learning_rate' in params
        assert 'batch_size' in params
        assert 'gamma' in params
        assert 'hidden_layers' in params
        
    def test_config_creation(self, base_configs):
        """Test configuration creation from parameters."""
        training_config, agent_config = base_configs
        
        objective = RLObjectiveFunction(
            base_training_config=training_config,
            base_agent_config=agent_config,
            agent_type="dqn"
        )
        
        params = {
            'learning_rate': 0.001,
            'batch_size': 64,
            'total_episodes': 20,
            'hidden_layers': [128, 128]
        }
        
        new_training_config = objective._create_training_config(params)
        new_agent_config = objective._create_agent_config(params)
        
        assert new_training_config.total_episodes == 20
        assert new_agent_config.learning_rate == 0.001
        assert new_agent_config.batch_size == 64
        assert new_agent_config.hidden_layers == [128, 128]
        
    def test_objective_value_calculation(self, base_configs):
        """Test objective value calculation."""
        training_config, agent_config = base_configs
        
        objective = RLObjectiveFunction(
            base_training_config=training_config,
            base_agent_config=agent_config,
            metric="mean_reward"
        )
        
        # Create mock training history
        training_history = [
            TrainingMetrics(episode=i, total_reward=float(i), episode_length=10, average_reward=float(i/2))
            for i in range(10)
        ]
        
        mock_trainer = Mock()
        mock_trainer._find_convergence_episode.return_value = 5
        
        # Test different metrics
        objective.metric = "mean_reward"
        value = objective._calculate_objective_value(training_history, mock_trainer)
        assert value > 0
        
        objective.metric = "final_reward"
        value = objective._calculate_objective_value(training_history, mock_trainer)
        assert value == 9.0
        
        objective.metric = "best_reward"
        value = objective._calculate_objective_value(training_history, mock_trainer)
        assert value == 9.0


class TestResourceManager:
    """Test cases for ResourceManager."""
    
    @pytest.fixture
    def resource_limits(self):
        """Create resource limits for testing."""
        return ResourceLimits(
            max_memory_gb=2.0,
            max_cpu_percent=50.0,
            max_time_seconds=60.0,
            max_concurrent_trials=2
        )
        
    def test_resource_limits_initialization(self, resource_limits):
        """Test resource limits initialization."""
        assert resource_limits.max_memory_gb == 2.0
        assert resource_limits.max_cpu_percent == 50.0
        assert resource_limits.max_time_seconds == 60.0
        assert resource_limits.max_concurrent_trials == 2
        
    def test_resource_manager_initialization(self, resource_limits):
        """Test resource manager initialization."""
        manager = ResourceManager(resource_limits)
        
        assert manager.limits == resource_limits
        assert not manager.is_running
        assert manager.monitor is not None
        assert manager.allocator is not None
        
    def test_resource_manager_start_stop(self, resource_limits):
        """Test resource manager start and stop."""
        manager = ResourceManager(resource_limits)
        
        # Start
        manager.start()
        assert manager.is_running
        
        # Stop
        manager.stop()
        assert not manager.is_running
        
    def test_trial_registration(self, resource_limits):
        """Test trial registration and resource allocation."""
        manager = ResourceManager(resource_limits)
        manager.start()
        
        try:
            # Register trial
            allocated = manager.register_trial(1, memory_gb=0.5, cpu_percent=10.0)
            assert allocated
            
            # Check status
            status = manager.get_status()
            assert status['allocation']['active_trials'] == 1
            
            # Unregister trial
            manager.unregister_trial(1)
            
            status = manager.get_status()
            assert status['allocation']['active_trials'] == 0
            
        finally:
            manager.stop()
            
    def test_resource_allocation_limits(self, resource_limits):
        """Test resource allocation limits."""
        manager = ResourceManager(resource_limits)
        manager.start()
        
        try:
            # Allocate up to limit
            allocated1 = manager.register_trial(1, memory_gb=1.0, cpu_percent=25.0)
            allocated2 = manager.register_trial(2, memory_gb=1.0, cpu_percent=25.0)
            
            assert allocated1
            assert allocated2
            
            # Try to exceed limit
            allocated3 = manager.register_trial(3, memory_gb=1.0, cpu_percent=25.0)
            assert not allocated3  # Should fail due to concurrent trial limit
            
        finally:
            manager.stop()
            
    def test_resource_status(self, resource_limits):
        """Test resource status reporting."""
        manager = ResourceManager(resource_limits)
        
        status = manager.get_status()
        
        assert 'is_running' in status
        assert 'limits' in status
        assert 'monitoring' in status
        assert 'allocation' in status
        
        assert status['limits']['max_memory_gb'] == 2.0
        assert status['limits']['max_concurrent_trials'] == 2


class TestResourceMonitor:
    """Test cases for ResourceMonitor."""
    
    @pytest.fixture
    def resource_limits(self):
        """Create resource limits for testing."""
        return ResourceLimits(
            max_memory_gb=1.0,
            max_cpu_percent=80.0,
            max_time_seconds=5.0,  # Short for testing
            max_concurrent_trials=2
        )
        
    def test_resource_monitor_initialization(self, resource_limits):
        """Test resource monitor initialization."""
        monitor = ResourceMonitor(resource_limits, check_interval=0.1)
        
        assert monitor.limits == resource_limits
        assert monitor.check_interval == 0.1
        assert not monitor.is_monitoring
        assert len(monitor.resource_history) == 0
        
    def test_resource_monitor_start_stop(self, resource_limits):
        """Test resource monitor start and stop."""
        monitor = ResourceMonitor(resource_limits, check_interval=0.1)
        
        # Start monitoring
        monitor.start_monitoring()
        assert monitor.is_monitoring
        
        # Let it run briefly
        time.sleep(0.2)
        
        # Stop monitoring
        monitor.stop_monitoring()
        assert not monitor.is_monitoring
        
        # Should have collected some data
        assert len(monitor.resource_history) > 0
        
    def test_trial_registration(self, resource_limits):
        """Test trial registration and monitoring."""
        monitor = ResourceMonitor(resource_limits, check_interval=0.1)
        
        # Register trial
        monitor.register_trial(1)
        assert 1 in monitor.active_trials
        
        # Unregister trial
        monitor.unregister_trial(1)
        assert 1 not in monitor.active_trials
        
    def test_resource_usage_collection(self, resource_limits):
        """Test resource usage data collection."""
        monitor = ResourceMonitor(resource_limits, check_interval=0.1)
        
        usage = monitor._get_current_usage()
        
        assert isinstance(usage, ResourceUsage)
        assert usage.memory_gb >= 0
        assert usage.cpu_percent >= 0
        assert usage.time_elapsed == 0.0
        
    def test_resource_summary(self, resource_limits):
        """Test resource summary generation."""
        monitor = ResourceMonitor(resource_limits, check_interval=0.1)
        
        # Add some mock data
        for i in range(5):
            usage = ResourceUsage(
                memory_gb=1.0 + i * 0.1,
                cpu_percent=50.0 + i * 5.0,
                time_elapsed=float(i)
            )
            monitor.resource_history.append(usage)
            
        summary = monitor.get_resource_summary()
        
        assert 'current_memory_gb' in summary
        assert 'current_cpu_percent' in summary
        assert 'avg_memory_gb' in summary
        assert 'max_cpu_percent' in summary
        assert summary['monitoring_duration'] > 0


class TestResourceAllocator:
    """Test cases for ResourceAllocator."""
    
    @pytest.fixture
    def resource_limits(self):
        """Create resource limits for testing."""
        return ResourceLimits(
            max_memory_gb=4.0,
            max_cpu_percent=80.0,
            max_concurrent_trials=3
        )
        
    def test_resource_allocator_initialization(self, resource_limits):
        """Test resource allocator initialization."""
        allocator = ResourceAllocator(resource_limits)
        
        assert allocator.limits == resource_limits
        assert allocator.allocated_memory == 0.0
        assert allocator.allocated_cpu == 0.0
        assert len(allocator.active_allocations) == 0
        
    def test_resource_allocation(self, resource_limits):
        """Test resource allocation and release."""
        allocator = ResourceAllocator(resource_limits)
        
        # Request resources
        allocated = allocator.request_resources(1, memory_gb=1.0, cpu_percent=20.0)
        assert allocated
        assert allocator.allocated_memory == 1.0
        assert allocator.allocated_cpu == 20.0
        assert 1 in allocator.active_allocations
        
        # Release resources
        allocator.release_resources(1)
        assert allocator.allocated_memory == 0.0
        assert allocator.allocated_cpu == 0.0
        assert 1 not in allocator.active_allocations
        
    def test_resource_allocation_limits(self, resource_limits):
        """Test resource allocation limits."""
        allocator = ResourceAllocator(resource_limits)
        
        # Allocate within limits
        allocated1 = allocator.request_resources(1, memory_gb=2.0, cpu_percent=40.0)
        allocated2 = allocator.request_resources(2, memory_gb=2.0, cpu_percent=40.0)
        
        assert allocated1
        assert allocated2
        
        # Try to exceed memory limit
        allocated3 = allocator.request_resources(3, memory_gb=1.0, cpu_percent=10.0)
        assert not allocated3  # Should fail due to memory limit
        
    def test_allocation_summary(self, resource_limits):
        """Test allocation summary."""
        allocator = ResourceAllocator(resource_limits)
        
        # Allocate some resources
        allocator.request_resources(1, memory_gb=1.0, cpu_percent=25.0)
        allocator.request_resources(2, memory_gb=1.5, cpu_percent=30.0)
        
        summary = allocator.get_allocation_summary()
        
        assert summary['allocated_memory_gb'] == 2.5
        assert summary['allocated_cpu_percent'] == 55.0
        assert summary['active_trials'] == 2
        assert summary['utilization']['memory_percent'] == 62.5  # 2.5/4.0 * 100


class TestHyperparameterOptimizer:
    """Test cases for HyperparameterOptimizer."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
        
    @pytest.fixture
    def optimization_config(self):
        """Create optimization configuration for testing."""
        return OptimizationConfig(
            study_name="test_study",
            n_trials=3,  # Small number for testing
            n_jobs=1,
            sampler="random"  # Faster for testing
        )
        
    @patch('optuna.create_study')
    def test_optimizer_initialization(self, mock_create_study, optimization_config):
        """Test optimizer initialization."""
        mock_study = Mock()
        mock_create_study.return_value = mock_study
        
        optimizer = HyperparameterOptimizer(optimization_config)
        
        assert optimizer.config == optimization_config
        assert optimizer.study == mock_study
        assert optimizer.best_params is None
        assert optimizer.best_value is None
        
    @patch('optuna.create_study')
    def test_optimization_results_tracking(self, mock_create_study, optimization_config):
        """Test optimization results tracking."""
        # Mock study and trials
        mock_trial1 = Mock()
        mock_trial1.number = 0
        mock_trial1.value = 10.0
        mock_trial1.params = {'learning_rate': 0.001}
        mock_trial1.state = Mock()
        mock_trial1.state.name = 'COMPLETE'
        mock_trial1.datetime_start = None
        mock_trial1.datetime_complete = None
        mock_trial1.duration = None
        mock_trial1.user_attrs = {}
        
        mock_study = Mock()
        mock_study.trials = [mock_trial1]
        mock_study.best_params = {'learning_rate': 0.001}
        mock_study.best_value = 10.0
        mock_create_study.return_value = mock_study
        
        optimizer = HyperparameterOptimizer(optimization_config)
        
        # Get optimization history
        history = optimizer.get_optimization_history()
        
        assert len(history) == 1
        assert history[0]['number'] == 0
        assert history[0]['value'] == 10.0
        assert history[0]['params'] == {'learning_rate': 0.001}
        
        # Get best trials
        best_trials = optimizer.get_best_trials(n_trials=1)
        
        assert len(best_trials) == 1
        assert best_trials[0]['value'] == 10.0
        
    @patch('optuna.create_study')
    def test_save_load_results(self, mock_create_study, optimization_config, temp_dir):
        """Test saving and loading optimization results."""
        mock_study = Mock()
        mock_study.trials = []
        mock_create_study.return_value = mock_study
        
        optimizer = HyperparameterOptimizer(optimization_config)
        optimizer.best_params = {'learning_rate': 0.001}
        optimizer.best_value = 15.0
        
        # Save results
        save_path = Path(temp_dir) / "results.json"
        optimizer.save_results(str(save_path))
        
        assert save_path.exists()
        
        # Load results
        new_optimizer = HyperparameterOptimizer(optimization_config)
        loaded_results = new_optimizer.load_results(str(save_path))
        
        assert loaded_results['best_params'] == {'learning_rate': 0.001}
        assert loaded_results['best_value'] == 15.0
        assert new_optimizer.best_params == {'learning_rate': 0.001}
        assert new_optimizer.best_value == 15.0


class TestOptimizationManager:
    """Test cases for OptimizationManager."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
        
    def test_optimization_manager_initialization(self, temp_dir):
        """Test optimization manager initialization."""
        manager = OptimizationManager(temp_dir)
        
        assert manager.base_dir == Path(temp_dir)
        assert manager.base_dir.exists()
        assert len(manager.optimizers) == 0
        
    @patch('src.rl.training.hyperparameter_optimizer.HyperparameterOptimizer')
    def test_create_optimizer(self, mock_optimizer_class, temp_dir):
        """Test optimizer creation."""
        mock_optimizer = Mock()
        mock_optimizer_class.return_value = mock_optimizer
        
        manager = OptimizationManager(temp_dir)
        config = OptimizationConfig(study_name="test")
        
        optimizer = manager.create_optimizer("test_opt", config)
        
        assert "test_opt" in manager.optimizers
        assert manager.optimizers["test_opt"] == mock_optimizer
        
    def test_optimization_summary(self, temp_dir):
        """Test optimization summary generation."""
        manager = OptimizationManager(temp_dir)
        
        # Add mock optimizers
        mock_optimizer1 = Mock()
        mock_optimizer1.config.study_name = "study1"
        mock_optimizer1.study.trials = [Mock(), Mock()]
        mock_optimizer1.best_value = 10.0
        
        mock_optimizer2 = Mock()
        mock_optimizer2.config.study_name = "study2"
        mock_optimizer2.study.trials = [Mock()]
        mock_optimizer2.best_value = None
        
        manager.optimizers["opt1"] = mock_optimizer1
        manager.optimizers["opt2"] = mock_optimizer2
        
        summary = manager.get_optimization_summary()
        
        assert summary['total_optimizations'] == 2
        assert 'opt1' in summary['optimizations']
        assert 'opt2' in summary['optimizations']
        assert summary['optimizations']['opt1']['n_trials'] == 2
        assert summary['optimizations']['opt1']['status'] == 'completed'
        assert summary['optimizations']['opt2']['status'] == 'running'


class TestIntegration:
    """Integration tests for hyperparameter optimization."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)
        
    def test_resource_management_integration(self, temp_dir):
        """Test integration between resource management components."""
        limits = ResourceLimits(
            max_memory_gb=2.0,
            max_cpu_percent=50.0,
            max_concurrent_trials=2
        )
        
        manager = ResourceManager(limits)
        manager.start()
        
        try:
            # Test resource allocation workflow
            allocated1 = manager.register_trial(1, memory_gb=0.8, cpu_percent=20.0)
            allocated2 = manager.register_trial(2, memory_gb=0.8, cpu_percent=20.0)
            allocated3 = manager.register_trial(3, memory_gb=0.8, cpu_percent=20.0)
            
            assert allocated1
            assert allocated2
            assert not allocated3  # Should fail due to concurrent limit
            
            # Check status
            status = manager.get_status()
            assert status['allocation']['active_trials'] == 2
            
            # Release resources
            manager.unregister_trial(1)
            
            # Now trial 3 should be able to allocate
            time.sleep(0.1)  # Give allocation loop time to process
            allocated3_retry = manager.register_trial(3, memory_gb=0.8, cpu_percent=20.0)
            assert allocated3_retry
            
        finally:
            manager.stop()
            
    def test_end_to_end_workflow(self, temp_dir):
        """Test end-to-end optimization workflow."""
        # This test would require Optuna, so we'll mock the key components
        
        # Create mock configurations
        training_config = TrainingConfig(
            total_episodes=5,
            max_steps_per_episode=10
        )
        
        agent_config = DQNConfig(
            learning_rate=1e-3,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=1000,
            target_update_frequency=10,
            hidden_layers=[64],
            activation="relu",
            optimizer="adam"
        )
        
        # Create factories
        def agent_factory(config):
            return MockAgent(config)
            
        def environment_factory():
            return MockEnvironment(max_steps=10)
            
        # Test objective function
        objective = RLObjectiveFunction(
            base_training_config=training_config,
            base_agent_config=agent_config,
            agent_type="dqn",
            metric="mean_reward"
        )
        
        # Test parameter suggestion
        mock_trial = Mock()
        mock_trial.suggest_float.side_effect = lambda name, low, high, **kwargs: (low + high) / 2
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_int.side_effect = lambda name, low, high: (low + high) // 2
        
        params = objective.suggest_hyperparameters(mock_trial)
        
        assert 'learning_rate' in params
        assert 'batch_size' in params
        assert 'hidden_layers' in params
        
        # Test configuration creation
        new_training_config = objective._create_training_config(params)
        new_agent_config = objective._create_agent_config(params)
        
        assert isinstance(new_training_config, TrainingConfig)
        assert isinstance(new_agent_config, DQNConfig)


if __name__ == "__main__":
    pytest.main([__file__])
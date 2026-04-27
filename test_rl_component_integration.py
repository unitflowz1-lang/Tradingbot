"""
RL System Component Integration Tests

Tests for integration between major RL system components including
agents, environments, training pipeline, and monitoring systems.
"""

import pytest
import numpy as np
import pandas as pd
import asyncio
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any

# RL System imports
from src.rl.environments.forex_environment import ForexEnvironment
from src.rl.environments.multi_pair_environment import MultiPairEnvironment
from src.rl.environments.state_processor import StateProcessor
from src.rl.environments.reward_calculator import RewardCalculator
from src.rl.agents.dqn import DQNAgent
from src.rl.agents.ppo import PPOAgent
from src.rl.training.agent_trainer import AgentTrainer
from src.rl.training.hyperparameter_optimizer import HyperparameterOptimizer
from src.rl.data.loader import DataLoader
from src.rl.data.preprocessor import DataPreprocessor
from src.rl.data.batch_manager import BatchManager
from src.rl.monitoring.performance_tracker import PerformanceTracker
from src.rl.monitoring.training_visualizer import TrainingVisualizer
from src.rl.strategies.registry import StrategyRegistry
from src.rl.strategies.allocator import StrategyAllocator
from src.rl.strategies.ab_testing import ABTestingFramework

# Test utilities
from test_utils.cleanup import cleanup_test_files


class TestAgentEnvironmentIntegration:
    """Test integration between RL agents and trading environments."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        # Create test market data
        self.market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=200, freq='1H'),
            'open': 1.1000 + np.random.normal(0, 0.001, 200),
            'high': 1.1000 + np.random.normal(0, 0.001, 200) + 0.0005,
            'low': 1.1000 + np.random.normal(0, 0.001, 200) - 0.0005,
            'close': 1.1000 + np.random.normal(0, 0.001, 200),
            'volume': np.random.randint(1000, 10000, 200),
            'symbol': 'EURUSD'
        })
        
        self.env_config = {
            'state_features': ['close', 'volume', 'rsi', 'macd'],
            'lookback_window': 10,
            'action_space_size': 8,
            'reward_function': 'sharpe_adjusted',
            'transaction_cost': 0.0001
        }
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_dqn_environment_interaction(self):
        """Test DQN agent interaction with forex environment."""
        # Create environment
        environment = ForexEnvironment(
            data=self.market_data,
            config=self.env_config
        )
        
        # Create DQN agent
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 1000,
                'epsilon_start': 1.0,
                'epsilon_end': 0.01,
                'epsilon_decay': 0.995
            }
        )
        
        # Test episode interaction
        state = environment.reset()
        assert state is not None
        assert isinstance(state, np.ndarray)
        assert state.shape == environment.observation_space.shape
        
        total_reward = 0
        steps = 0
        
        for _ in range(50):
            # Agent selects action
            action = agent.select_action(state, training=True)
            assert 0 <= action < environment.action_space.n
            
            # Environment processes action
            next_state, reward, done, info = environment.step(action)
            
            assert isinstance(next_state, np.ndarray)
            assert isinstance(reward, (int, float))
            assert isinstance(done, bool)
            assert isinstance(info, dict)
            
            # Store experience
            agent.store_experience(state, action, reward, next_state, done)
            
            # Update agent if enough experiences
            if len(agent.memory) >= agent.batch_size:
                loss = agent.update()
                assert loss is not None
                assert loss >= 0
            
            total_reward += reward
            steps += 1
            state = next_state
            
            if done:
                state = environment.reset()
        
        assert steps > 0
        assert abs(total_reward) < 1000  # Reasonable reward range
        
        print(f"✓ DQN-Environment interaction test passed")
        print(f"  - Steps: {steps}, Total reward: {total_reward:.4f}")
    
    def test_ppo_environment_interaction(self):
        """Test PPO agent interaction with forex environment."""
        # Create environment
        environment = ForexEnvironment(
            data=self.market_data,
            config=self.env_config
        )
        
        # Create PPO agent
        agent = PPOAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.0003,
                'clip_ratio': 0.2,
                'entropy_coef': 0.01,
                'value_coef': 0.5,
                'max_grad_norm': 0.5
            }
        )
        
        # Collect trajectory
        states, actions, rewards, log_probs, values = [], [], [], [], []
        
        state = environment.reset()
        
        for _ in range(32):  # Collect batch of experiences
            action, log_prob, value = agent.select_action_with_log_prob(state)
            next_state, reward, done, info = environment.step(action)
            
            states.append(state)
            actions.append(action)
            rewards.append(reward)
            log_probs.append(log_prob)
            values.append(value)
            
            state = next_state if not done else environment.reset()
        
        # Update PPO agent
        trajectory = {
            'states': np.array(states),
            'actions': np.array(actions),
            'rewards': np.array(rewards),
            'log_probs': np.array(log_probs),
            'values': np.array(values)
        }
        
        loss_info = agent.update(trajectory)
        
        assert 'policy_loss' in loss_info
        assert 'value_loss' in loss_info
        assert 'entropy_loss' in loss_info
        
        print(f"✓ PPO-Environment interaction test passed")
        print(f"  - Policy loss: {loss_info['policy_loss']:.4f}")
        print(f"  - Value loss: {loss_info['value_loss']:.4f}")
    
    def test_multi_pair_environment_integration(self):
        """Test agent interaction with multi-pair environment."""
        # Create multi-pair data
        pairs = ['EURUSD', 'GBPUSD', 'USDJPY']
        multi_pair_data = {}
        
        for pair in pairs:
            multi_pair_data[pair] = pd.DataFrame({
                'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='1H'),
                'open': np.random.random(100) + 1.1,
                'high': np.random.random(100) + 1.1,
                'low': np.random.random(100) + 1.1,
                'close': np.random.random(100) + 1.1,
                'volume': np.random.randint(1000, 10000, 100),
                'symbol': pair
            })
        
        # Create multi-pair environment
        multi_env = MultiPairEnvironment(
            data=multi_pair_data,
            config=self.env_config
        )
        
        # Create agent for multi-pair environment
        agent = DQNAgent(
            state_dim=multi_env.observation_space.shape[0],
            action_dim=multi_env.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 1000
            }
        )
        
        # Test multi-pair interaction
        state = multi_env.reset()
        assert state.shape[0] > self.env_config['lookback_window'] * len(self.env_config['state_features'])
        
        for _ in range(20):
            action = agent.select_action(state, training=True)
            next_state, reward, done, info = multi_env.step(action)
            
            # Verify multi-pair specific info
            assert 'pair_rewards' in info
            assert len(info['pair_rewards']) == len(pairs)
            
            agent.store_experience(state, action, reward, next_state, done)
            state = next_state if not done else multi_env.reset()
        
        print("✓ Multi-pair environment integration test passed")


class TestTrainingPipelineIntegration:
    """Test integration of the complete training pipeline."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup training pipeline test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        # Create larger dataset for training
        self.market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=500, freq='1H'),
            'open': 1.1000 + np.cumsum(np.random.normal(0, 0.0001, 500)),
            'high': 1.1000 + np.cumsum(np.random.normal(0, 0.0001, 500)) + 0.0005,
            'low': 1.1000 + np.cumsum(np.random.normal(0, 0.0001, 500)) - 0.0005,
            'close': 1.1000 + np.cumsum(np.random.normal(0, 0.0001, 500)),
            'volume': np.random.randint(1000, 10000, 500),
            'symbol': 'EURUSD'
        })
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_data_pipeline_integration(self):
        """Test integration of data loading, preprocessing, and batch management."""
        # Test data loading
        data_loader = DataLoader({
            'data_source': 'dataframe',
            'preprocessing': True
        })
        
        loaded_data = data_loader.load_from_dataframe(self.market_data)
        assert len(loaded_data) == len(self.market_data)
        
        # Test preprocessing
        preprocessor = DataPreprocessor({
            'normalization': 'minmax',
            'feature_engineering': True,
            'technical_indicators': ['rsi', 'macd', 'bb']
        })
        
        processed_data = preprocessor.preprocess(loaded_data)
        assert len(processed_data.columns) > len(loaded_data.columns)
        
        # Test batch management
        batch_manager = BatchManager({
            'batch_size': 64,
            'sequence_length': 10,
            'overlap': 0.5
        })
        
        batches = batch_manager.create_batches(processed_data)
        assert len(batches) > 0
        
        for batch in batches[:3]:  # Test first few batches
            assert len(batch) <= 64
            assert 'features' in batch
            assert 'targets' in batch
        
        print("✓ Data pipeline integration test passed")
    
    def test_training_monitoring_integration(self):
        """Test integration between training and monitoring systems."""
        # Setup environment and agent
        env_config = {
            'state_features': ['close', 'volume'],
            'lookback_window': 5,
            'action_space_size': 3
        }
        
        environment = ForexEnvironment(
            data=self.market_data,
            config=env_config
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 1000
            }
        )
        
        # Setup monitoring
        performance_tracker = PerformanceTracker(storage_path=self.temp_dir)
        training_visualizer = TrainingVisualizer(storage_path=self.temp_dir)
        
        # Setup trainer with monitoring
        trainer = AgentTrainer(
            agent=agent,
            environment=environment,
            config={
                'episodes': 10,
                'max_steps': 50,
                'checkpoint_frequency': 5,
                'validation_frequency': 5
            },
            performance_tracker=performance_tracker,
            visualizer=training_visualizer
        )
        
        # Run training with monitoring
        training_results = trainer.train()
        
        # Verify training results
        assert 'episode_rewards' in training_results
        assert 'training_metrics' in training_results
        assert len(training_results['episode_rewards']) == 10
        
        # Verify monitoring data was collected
        training_history = training_visualizer.get_training_history()
        assert len(training_history) > 0
        
        performance_data = performance_tracker.get_latest_performance()
        assert performance_data is not None
        
        print("✓ Training-monitoring integration test passed")
    
    def test_hyperparameter_optimization_integration(self):
        """Test integration of hyperparameter optimization with training."""
        # Define search space
        search_space = {
            'learning_rate': (0.0001, 0.01),
            'batch_size': [16, 32, 64],
            'epsilon_decay': (0.99, 0.999),
            'hidden_layers': [[64], [128], [64, 32]]
        }
        
        # Create objective function
        def objective_function(params):
            env_config = {
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
            
            environment = ForexEnvironment(
                data=self.market_data[:100],  # Use smaller dataset for speed
                config=env_config
            )
            
            agent = DQNAgent(
                state_dim=environment.observation_space.shape[0],
                action_dim=environment.action_space.n,
                config=params
            )
            
            trainer = AgentTrainer(
                agent=agent,
                environment=environment,
                config={'episodes': 5, 'max_steps': 20}
            )
            
            results = trainer.train()
            return np.mean(results['episode_rewards'])
        
        # Run hyperparameter optimization
        optimizer = HyperparameterOptimizer(
            objective_function=objective_function,
            search_space=search_space,
            n_trials=3,  # Small number for testing
            storage_path=self.temp_dir
        )
        
        best_params = optimizer.optimize()
        
        assert best_params is not None
        assert 'learning_rate' in best_params
        assert 'batch_size' in best_params
        
        # Verify optimization history
        study_results = optimizer.get_optimization_history()
        assert len(study_results) == 3
        
        print("✓ Hyperparameter optimization integration test passed")


class TestStrategyManagementIntegration:
    """Test integration of strategy management components."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup strategy management test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_strategy_registry_allocator_integration(self):
        """Test integration between strategy registry and allocator."""
        # Create strategy registry
        registry = StrategyRegistry(storage_path=self.temp_dir)
        
        # Create multiple mock strategies
        strategies = []
        performance_history = {}
        
        for i in range(3):
            # Create mock agent
            mock_agent = Mock()
            mock_agent.select_action.return_value = i % 3
            
            # Register strategy
            strategy_id = registry.register_strategy(
                agent=mock_agent,
                metadata={
                    'name': f'strategy_{i}',
                    'agent_type': 'DQN',
                    'currency_pair': 'EURUSD',
                    'performance_metrics': {
                        'sharpe_ratio': 1.0 + i * 0.2,
                        'max_drawdown': 0.1 - i * 0.02,
                        'total_return': 0.1 + i * 0.05
                    }
                }
            )
            
            strategies.append({
                'id': strategy_id,
                'agent': mock_agent,
                'metadata': registry.get_strategy_metadata(strategy_id)
            })
            
            # Create mock performance history
            performance_history[strategy_id] = [0.1 + i * 0.02] * 10
        
        # Test strategy allocation
        allocator = StrategyAllocator(method='performance_weighted')
        allocations = allocator.calculate_allocations(strategies, performance_history)
        
        assert len(allocations) == 3
        assert abs(sum(allocations.values()) - 1.0) < 0.01
        
        # Test dynamic reallocation
        # Simulate performance change
        performance_history[strategies[0]['id']][-1] = -0.05  # Poor recent performance
        
        new_allocations = allocator.calculate_allocations(strategies, performance_history)
        
        # Strategy 0 should get less allocation due to poor recent performance
        assert new_allocations[strategies[0]['id']] < allocations[strategies[0]['id']]
        
        print("✓ Strategy registry-allocator integration test passed")
    
    def test_ab_testing_integration(self):
        """Test A/B testing framework integration."""
        # Create A/B testing framework
        ab_framework = ABTestingFramework(storage_path=self.temp_dir)
        
        # Create mock strategies for testing
        strategy_a = Mock()
        strategy_a.select_action.return_value = 1
        
        strategy_b = Mock()
        strategy_b.select_action.return_value = 2
        
        # Setup A/B test
        test_id = ab_framework.create_test(
            name='DQN_vs_PPO',
            strategy_a=strategy_a,
            strategy_b=strategy_b,
            allocation_ratio=0.5,
            duration_days=1
        )
        
        # Simulate trading sessions
        for session in range(20):
            # Get strategy assignment
            assigned_strategy = ab_framework.get_strategy_for_session(test_id, f'session_{session}')
            
            # Simulate performance
            performance = np.random.normal(0.1, 0.05)  # Random performance
            
            ab_framework.record_performance(
                test_id=test_id,
                session_id=f'session_{session}',
                performance=performance,
                strategy=assigned_strategy
            )
        
        # Analyze results
        results = ab_framework.analyze_test(test_id)
        
        assert 'strategy_a_performance' in results
        assert 'strategy_b_performance' in results
        assert 'statistical_significance' in results
        assert 'confidence_interval' in results
        
        # Test automatic winner selection
        if results['statistical_significance']:
            winner = ab_framework.get_winning_strategy(test_id)
            assert winner in ['strategy_a', 'strategy_b']
        
        print("✓ A/B testing integration test passed")


class TestMonitoringIntegration:
    """Test integration of monitoring and analytics components."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup monitoring integration test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_performance_tracking_integration(self):
        """Test integration of performance tracking with trading system."""
        # Create performance tracker
        tracker = PerformanceTracker(storage_path=self.temp_dir)
        
        # Simulate multiple trading sessions
        sessions = []
        
        for strategy_idx in range(2):
            for session_idx in range(3):
                session_id = tracker.start_session(
                    strategy_id=f'strategy_{strategy_idx}',
                    currency_pair='EURUSD'
                )
                sessions.append(session_id)
                
                # Simulate trades
                for trade_idx in range(10):
                    trade = {
                        'timestamp': datetime.now() + timedelta(minutes=trade_idx * 30),
                        'action': 'BUY' if trade_idx % 2 == 0 else 'SELL',
                        'price': 1.1000 + np.random.normal(0, 0.001),
                        'volume': 0.1,
                        'pnl': np.random.normal(10, 50)
                    }
                    tracker.record_trade(session_id, trade)
                
                tracker.end_session(session_id)
        
        # Test cross-session analysis
        all_performance = tracker.get_all_performance_data()
        assert len(all_performance) == 6  # 2 strategies * 3 sessions each
        
        # Test strategy comparison
        strategy_comparison = tracker.compare_strategies(['strategy_0', 'strategy_1'])
        assert 'strategy_0' in strategy_comparison
        assert 'strategy_1' in strategy_comparison
        
        # Test performance aggregation
        aggregated = tracker.aggregate_performance_by_strategy()
        assert len(aggregated) == 2
        
        for strategy_id, perf in aggregated.items():
            assert 'total_pnl' in perf
            assert 'num_sessions' in perf
            assert 'avg_session_pnl' in perf
        
        print("✓ Performance tracking integration test passed")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])
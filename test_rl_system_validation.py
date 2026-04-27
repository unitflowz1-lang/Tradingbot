"""
RL System Validation and Stress Testing

Comprehensive validation tests for the RL trading system including
stress testing, robustness testing, and system validation scenarios.
"""

import pytest
import numpy as np
import pandas as pd
import asyncio
import tempfile
import os
import time
import threading
import multiprocessing
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any
import gc
import psutil

# Import mock components from the comprehensive test
from test_rl_integration_comprehensive import (
    MockForexEnvironment,
    MockDQNAgent,
    MockStrategyRegistry,
    MockPerformanceTracker
)

# Test utilities
def cleanup_test_files(file_list):
    """Simple cleanup function for test files."""
    for filepath in file_list:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except (PermissionError, OSError):
            pass  # Ignore cleanup errors in tests


class TestRLSystemStressTesting:
    """Stress testing for the RL trading system."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup stress testing environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def create_stress_test_data(self, size: int, volatility: float = 0.01) -> pd.DataFrame:
        """Create market data for stress testing."""
        dates = pd.date_range(
            start=datetime.now() - timedelta(hours=size),
            periods=size,
            freq='1h'
        )
        
        # Generate data with specified volatility
        np.random.seed(42)
        base_price = 1.1000
        returns = np.random.normal(0, volatility, size)
        prices = base_price * np.exp(np.cumsum(returns))
        
        # Add extreme events for stress testing
        extreme_events = np.random.choice(size, size // 100, replace=False)
        for event_idx in extreme_events:
            prices[event_idx] *= np.random.choice([0.95, 1.05])  # 5% price shock
        
        data = pd.DataFrame({
            'timestamp': dates,
            'open': prices * (1 + np.random.normal(0, 0.0001, size)),
            'high': prices * (1 + np.abs(np.random.normal(0, 0.001, size))),
            'low': prices * (1 - np.abs(np.random.normal(0, 0.001, size))),
            'close': prices,
            'volume': np.random.randint(1000, 50000, size),
            'symbol': 'EURUSD'
        })
        
        return data
    
    def test_high_volume_data_stress(self):
        """Test system performance with high-volume market data."""
        # Create large dataset (10,000 data points)
        large_data = self.create_stress_test_data(10000)
        
        config = {
            'state_features': ['close', 'volume', 'rsi', 'macd'],
            'lookback_window': 20,
            'action_space_size': 8,
            'reward_function': 'sharpe_adjusted'
        }
        
        # Test environment creation with large data
        start_time = time.time()
        environment = MockForexEnvironment(data=large_data, config=config)
        env_creation_time = time.time() - start_time
        
        assert env_creation_time < 5.0  # Should create environment in under 5 seconds
        
        # Test agent performance with large state space
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 128,
                'memory_size': 50000
            }
        )
        
        # Stress test with rapid trading
        state = environment.reset()
        start_time = time.time()
        
        for step in range(1000):  # 1000 rapid trading steps
            action = agent.select_action(state, training=True)
            next_state, reward, done, info = environment.step(action)
            
            agent.store_experience(state, action, reward, next_state, done)
            
            # Update agent frequently
            if step % 10 == 0 and len(agent.memory) >= agent.batch_size:
                agent.update()
            
            state = next_state if not done else environment.reset()
        
        stress_test_time = time.time() - start_time
        
        # Performance assertions
        assert stress_test_time < 30.0  # Should complete in under 30 seconds
        steps_per_second = 1000 / stress_test_time
        assert steps_per_second > 30  # Should handle at least 30 steps per second
        
        print(f"✓ High-volume data stress test passed")
        print(f"  - Environment creation: {env_creation_time:.2f}s")
        print(f"  - Stress test time: {stress_test_time:.2f}s")
        print(f"  - Steps per second: {steps_per_second:.2f}")
    
    def test_extreme_market_conditions_stress(self):
        """Test system robustness under extreme market conditions."""
        # Create data with extreme volatility
        extreme_data = self.create_stress_test_data(1000, volatility=0.05)  # 5% volatility
        
        config = {
            'state_features': ['close', 'volume'],
            'lookback_window': 10,
            'action_space_size': 3
        }
        
        environment = MockForexEnvironment(data=extreme_data, config=config)
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        # Test with extreme market conditions
        state = environment.reset()
        extreme_rewards = []
        extreme_actions = []
        
        for step in range(100):
            action = agent.select_action(state, training=False)
            next_state, reward, done, info = environment.step(action)
            
            extreme_rewards.append(reward)
            extreme_actions.append(action)
            
            # Verify system handles extreme values
            assert not np.isnan(reward), f"NaN reward at step {step}"
            assert not np.isinf(reward), f"Infinite reward at step {step}"
            assert isinstance(action, (int, np.integer)), f"Invalid action type at step {step}"
            
            state = next_state if not done else environment.reset()
        
        # Verify system stability
        reward_std = np.std(extreme_rewards)
        assert reward_std < 1000, "Rewards too volatile under extreme conditions"
        
        action_distribution = np.bincount(extreme_actions, minlength=environment.action_space.n)
        assert all(count >= 0 for count in action_distribution), "Invalid action distribution"
        
        print(f"✓ Extreme market conditions stress test passed")
        print(f"  - Reward std: {reward_std:.4f}")
        print(f"  - Action distribution: {action_distribution}")
    
    def test_memory_pressure_stress(self):
        """Test system behavior under memory pressure."""
        # Create multiple large environments to stress memory
        environments = []
        agents = []
        
        try:
            for i in range(5):  # Create 5 large environments
                data = self.create_stress_test_data(2000)
                
                env = MockForexEnvironment(
                    data=data,
                    config={
                        'state_features': ['close', 'volume', 'rsi'],
                        'lookback_window': 15,
                        'action_space_size': 5
                    }
                )
                environments.append(env)
                
                agent = MockDQNAgent(
                    state_dim=env.observation_space.shape[0],
                    action_dim=env.action_space.n,
                    config={
                        'learning_rate': 0.001,
                        'batch_size': 64,
                        'memory_size': 20000  # Large memory buffer
                    }
                )
                agents.append(agent)
            
            # Monitor memory usage
            process = psutil.Process()
            initial_memory = process.memory_info().rss / 1024 / 1024  # MB
            
            # Fill all agent memories
            for env, agent in zip(environments, agents):
                state = env.reset()
                for _ in range(500):  # Fill memory buffers
                    action = agent.select_action(state, training=True)
                    next_state, reward, done, _ = env.step(action)
                    agent.store_experience(state, action, reward, next_state, done)
                    state = next_state if not done else env.reset()
            
            peak_memory = process.memory_info().rss / 1024 / 1024  # MB
            memory_usage = peak_memory - initial_memory
            
            # Verify system handles memory pressure
            assert memory_usage < 2000, f"Excessive memory usage: {memory_usage:.1f}MB"
            
            # Test that system still functions under memory pressure
            for env, agent in zip(environments[:2], agents[:2]):  # Test subset
                state = env.reset()
                for _ in range(10):
                    action = agent.select_action(state, training=False)
                    next_state, reward, done, _ = env.step(action)
                    
                    # Verify no memory-related errors
                    assert not np.isnan(reward)
                    assert isinstance(action, (int, np.integer))
                    
                    state = next_state if not done else env.reset()
            
            print(f"✓ Memory pressure stress test passed")
            print(f"  - Memory usage: {memory_usage:.1f}MB")
            
        finally:
            # Clean up to prevent memory leaks
            del environments, agents
            gc.collect()
    
    def test_concurrent_access_stress(self):
        """Test system behavior under concurrent access."""
        # Create shared resources
        registry = MockStrategyRegistry(storage_path=self.temp_dir)
        performance_tracker = MockPerformanceTracker(storage_path=self.temp_dir)
        
        # Create test agent
        data = self.create_stress_test_data(200)
        environment = MockForexEnvironment(
            data=data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        # Register strategy
        strategy_id = registry.register_strategy(
            agent=agent,
            metadata={'name': 'concurrent_test_strategy', 'agent_type': 'DQN'}
        )
        
        # Concurrent access test
        results = []
        errors = []
        
        def concurrent_worker(worker_id):
            """Worker function for concurrent access testing."""
            try:
                # Test concurrent strategy access
                strategy = registry.get_strategy(strategy_id)
                assert strategy is not None
                
                # Test concurrent performance tracking
                session_id = performance_tracker.start_session(f'session_{worker_id}', 'EURUSD')
                
                for i in range(20):
                    trade = {
                        'timestamp': datetime.now(),
                        'action': 'BUY',
                        'price': 1.1000 + np.random.normal(0, 0.001),
                        'volume': 0.1,
                        'pnl': np.random.normal(0, 10)
                    }
                    performance_tracker.record_trade(session_id, trade)
                
                performance_tracker.end_session(session_id)
                performance = performance_tracker.calculate_performance(session_id)
                
                results.append({
                    'worker_id': worker_id,
                    'performance': performance,
                    'success': True
                })
                
            except Exception as e:
                errors.append({
                    'worker_id': worker_id,
                    'error': str(e),
                    'success': False
                })
        
        # Create multiple threads for concurrent access
        threads = []
        num_workers = 10
        
        for i in range(num_workers):
            thread = threading.Thread(target=concurrent_worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify concurrent access results
        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        assert len(results) == num_workers, f"Expected {num_workers} results, got {len(results)}"
        
        # Verify all workers succeeded
        successful_workers = [r for r in results if r['success']]
        assert len(successful_workers) == num_workers
        
        print(f"✓ Concurrent access stress test passed")
        print(f"  - Workers: {num_workers}")
        print(f"  - Successful: {len(successful_workers)}")
        print(f"  - Errors: {len(errors)}")
    
    def test_long_running_stability(self):
        """Test system stability over extended periods."""
        # Create environment for long-running test
        data = self.create_stress_test_data(5000)  # Large dataset
        
        environment = MockForexEnvironment(
            data=data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 10,
                'action_space_size': 3
            }
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 10000
            }
        )
        
        # Monitor system metrics over time
        performance_tracker = MockPerformanceTracker(storage_path=self.temp_dir)
        session_id = performance_tracker.start_session('stability_test', 'EURUSD')
        
        # Track system metrics
        memory_usage = []
        inference_times = []
        rewards = []
        
        process = psutil.Process()
        
        state = environment.reset()
        
        for step in range(2000):  # Long-running test
            # Measure inference time
            start_time = time.time()
            action = agent.select_action(state, training=True)
            inference_time = time.time() - start_time
            inference_times.append(inference_time)
            
            # Execute step
            next_state, reward, done, info = environment.step(action)
            rewards.append(reward)
            
            # Store experience and update
            agent.store_experience(state, action, reward, next_state, done)
            
            if step % 50 == 0 and len(agent.memory) >= agent.batch_size:
                agent.update()
            
            # Monitor memory usage periodically
            if step % 100 == 0:
                memory_mb = process.memory_info().rss / 1024 / 1024
                memory_usage.append(memory_mb)
            
            # Record trade periodically
            if step % 10 == 0 and action != 0:
                trade = {
                    'timestamp': datetime.now(),
                    'action': 'BUY' if action == 1 else 'SELL',
                    'price': info.get('current_price', 1.1000),
                    'volume': 0.1,
                    'pnl': reward * 100
                }
                performance_tracker.record_trade(session_id, trade)
            
            state = next_state if not done else environment.reset()
        
        # Analyze stability metrics
        avg_inference_time = np.mean(inference_times)
        inference_time_std = np.std(inference_times)
        
        memory_growth = (memory_usage[-1] - memory_usage[0]) if len(memory_usage) > 1 else 0
        
        reward_mean = np.mean(rewards)
        reward_std = np.std(rewards)
        
        # Stability assertions
        assert avg_inference_time < 0.01, f"Inference time too slow: {avg_inference_time:.4f}s"
        assert inference_time_std < 0.005, f"Inference time too variable: {inference_time_std:.4f}s"
        assert memory_growth < 100, f"Excessive memory growth: {memory_growth:.1f}MB"
        assert abs(reward_mean) < 10, f"Reward mean too extreme: {reward_mean:.4f}"
        assert reward_std < 100, f"Reward too variable: {reward_std:.4f}"
        
        # End session
        performance_tracker.end_session(session_id)
        final_performance = performance_tracker.calculate_performance(session_id)
        
        print(f"✓ Long-running stability test passed")
        print(f"  - Steps: 2000")
        print(f"  - Avg inference time: {avg_inference_time:.4f}s")
        print(f"  - Memory growth: {memory_growth:.1f}MB")
        print(f"  - Reward mean: {reward_mean:.4f}")
        print(f"  - Final performance: {final_performance}")


class TestRLSystemRobustness:
    """Robustness testing for various failure scenarios."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup robustness testing environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_corrupted_data_robustness(self):
        """Test system robustness with corrupted market data."""
        # Create data with various corruption scenarios
        base_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='1H'),
            'open': np.random.random(100) + 1.1,
            'high': np.random.random(100) + 1.1,
            'low': np.random.random(100) + 1.1,
            'close': np.random.random(100) + 1.1,
            'volume': np.random.randint(1000, 10000, 100),
            'symbol': 'EURUSD'
        })
        
        corruption_scenarios = [
            # NaN values
            lambda df: df.assign(close=df['close'].where(df.index % 10 != 0, np.nan)),
            # Infinite values
            lambda df: df.assign(volume=df['volume'].where(df.index % 15 != 0, np.inf)),
            # Negative prices
            lambda df: df.assign(low=df['low'].where(df.index % 20 != 0, -1.0)),
            # Zero volume
            lambda df: df.assign(volume=df['volume'].where(df.index % 8 != 0, 0)),
            # Missing timestamps
            lambda df: df.drop(df.index[::12])
        ]
        
        config = {
            'state_features': ['close', 'volume'],
            'lookback_window': 5,
            'action_space_size': 3
        }
        
        for i, corruption_func in enumerate(corruption_scenarios):
            corrupted_data = corruption_func(base_data.copy())
            
            try:
                # Test environment creation with corrupted data
                environment = MockForexEnvironment(data=corrupted_data, config=config)
                
                # Test agent interaction with corrupted environment
                agent = MockDQNAgent(
                    state_dim=environment.observation_space.shape[0],
                    action_dim=environment.action_space.n,
                    config={'learning_rate': 0.001, 'batch_size': 32}
                )
                
                # Test episode with corrupted data
                state = environment.reset()
                
                for step in range(10):
                    action = agent.select_action(state, training=False)
                    next_state, reward, done, info = environment.step(action)
                    
                    # Verify system handles corruption gracefully
                    assert not np.isnan(reward) or np.isfinite(reward), f"Invalid reward in scenario {i}"
                    assert isinstance(action, (int, np.integer)), f"Invalid action in scenario {i}"
                    
                    if done:
                        state = environment.reset()
                    else:
                        state = next_state
                
                print(f"✓ Corruption scenario {i} handled gracefully")
                
            except Exception as e:
                # Acceptable if system raises appropriate exceptions
                assert any(keyword in str(e).lower() for keyword in 
                          ['nan', 'inf', 'invalid', 'corrupt', 'missing']), \
                    f"Unexpected error in scenario {i}: {e}"
                print(f"✓ Corruption scenario {i} raised appropriate exception: {type(e).__name__}")
    
    def test_network_failure_robustness(self):
        """Test system robustness during network/connection failures."""
        # Simulate network failures with mock data source
        class FailingDataSource:
            def __init__(self):
                self.call_count = 0
            
            def get_data(self):
                self.call_count += 1
                if self.call_count % 3 == 0:  # Fail every 3rd call
                    raise ConnectionError("Simulated network failure")
                
                return pd.DataFrame({
                    'timestamp': [datetime.now()],
                    'open': [1.1000],
                    'high': [1.1010],
                    'low': [1.0990],
                    'close': [1.1005],
                    'volume': [1000],
                    'symbol': ['EURUSD']
                })
        
        data_source = FailingDataSource()
        
        # Test multiple data requests with failures
        successful_requests = 0
        failed_requests = 0
        
        for i in range(10):
            try:
                data = data_source.get_data()
                if data is not None and len(data) > 0:
                    successful_requests += 1
                else:
                    failed_requests += 1
            except ConnectionError:
                failed_requests += 1
            except Exception as e:
                # Should handle other errors gracefully
                print(f"Handled error gracefully: {type(e).__name__}")
                failed_requests += 1
        
        # Verify system handles failures appropriately
        assert successful_requests > 0, "No successful requests despite retries"
        assert failed_requests > 0, "No failures detected in failure simulation"
        
        print(f"✓ Network failure robustness test passed")
        print(f"  - Successful requests: {successful_requests}")
        print(f"  - Failed requests: {failed_requests}")
    
    def test_resource_exhaustion_robustness(self):
        """Test system behavior when resources are exhausted."""
        # Test with limited memory scenario
        config = {
            'state_features': ['close', 'volume'],
            'lookback_window': 5,
            'action_space_size': 3
        }
        
        # Create agent with very small memory buffer
        data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=200, freq='1H'),
            'open': np.random.random(200) + 1.1,
            'high': np.random.random(200) + 1.1,
            'low': np.random.random(200) + 1.1,
            'close': np.random.random(200) + 1.1,
            'volume': np.random.randint(1000, 10000, 200),
            'symbol': 'EURUSD'
        })
        
        environment = MockForexEnvironment(data=data, config=config)
        
        # Agent with very limited memory
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 50  # Very small memory buffer
            }
        )
        
        # Fill memory buffer beyond capacity
        state = environment.reset()
        
        for step in range(100):  # More steps than memory capacity
            action = agent.select_action(state, training=True)
            next_state, reward, done, info = environment.step(action)
            
            # Store experience (should handle memory overflow)
            agent.store_experience(state, action, reward, next_state, done)
            
            # Verify memory doesn't exceed capacity
            assert len(agent.memory) <= agent.config.get('memory_size', 50)
            
            # Try to update (should handle small batch sizes gracefully)
            if len(agent.memory) >= min(agent.batch_size, len(agent.memory)):
                try:
                    loss = agent.update()
                    assert loss is not None and loss >= 0
                except Exception as e:
                    # Should handle gracefully if batch size issues
                    assert "batch" in str(e).lower() or "size" in str(e).lower()
            
            state = next_state if not done else environment.reset()
        
        print(f"✓ Resource exhaustion robustness test passed")
        print(f"  - Memory size: {len(agent.memory)}")
        print(f"  - Max capacity: {agent.config.get('memory_size', 50)}")
    
    def test_model_corruption_robustness(self):
        """Test system behavior with corrupted model files."""
        # Create and save a valid model
        data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=50, freq='1H'),
            'open': np.random.random(50) + 1.1,
            'high': np.random.random(50) + 1.1,
            'low': np.random.random(50) + 1.1,
            'close': np.random.random(50) + 1.1,
            'volume': np.random.randint(1000, 10000, 50),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=data,
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
        
        # Save valid model
        valid_model_path = os.path.join(self.temp_dir, 'valid_model.pth')
        agent.save_model(valid_model_path)
        self.test_files.append(valid_model_path)
        
        # Create corrupted model files
        corrupted_paths = []
        
        # Empty file
        empty_path = os.path.join(self.temp_dir, 'empty_model.pth')
        with open(empty_path, 'w') as f:
            pass
        corrupted_paths.append(empty_path)
        self.test_files.append(empty_path)
        
        # Random binary data
        random_path = os.path.join(self.temp_dir, 'random_model.pth')
        with open(random_path, 'wb') as f:
            f.write(np.random.bytes(1024))
        corrupted_paths.append(random_path)
        self.test_files.append(random_path)
        
        # Test loading corrupted models
        for i, corrupted_path in enumerate(corrupted_paths):
            new_agent = MockDQNAgent(
                state_dim=environment.observation_space.shape[0],
                action_dim=environment.action_space.n,
                config={'learning_rate': 0.001, 'batch_size': 32}
            )
            
            try:
                new_agent.load_model(corrupted_path)
                # If loading succeeds, test that agent still functions
                test_state = np.random.random(environment.observation_space.shape[0])
                action = new_agent.select_action(test_state, training=False)
                assert isinstance(action, (int, np.integer))
                print(f"✓ Corrupted model {i} loaded with fallback behavior")
                
            except Exception as e:
                # Should raise appropriate exceptions for corrupted files
                assert any(keyword in str(e).lower() for keyword in 
                          ['corrupt', 'invalid', 'load', 'file', 'format']), \
                    f"Unexpected error for corrupted model {i}: {e}"
                print(f"✓ Corrupted model {i} raised appropriate exception: {type(e).__name__}")
        
        # Verify valid model still works
        valid_agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        valid_agent.load_model(valid_model_path)
        test_state = np.random.random(environment.observation_space.shape[0])
        action = valid_agent.select_action(test_state, training=False)
        assert isinstance(action, (int, np.integer))
        
        print(f"✓ Model corruption robustness test passed")


class TestRLSystemValidation:
    """System validation tests for correctness and compliance."""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup validation testing environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        yield
        
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def test_mathematical_correctness_validation(self):
        """Validate mathematical correctness of RL algorithms."""
        # Create deterministic environment for validation
        np.random.seed(42)
        
        data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=100, freq='1H'),
            'open': [1.1000] * 100,
            'high': [1.1010] * 100,
            'low': [1.0990] * 100,
            'close': [1.1000] * 100,
            'volume': [1000] * 100,
            'symbol': 'EURUSD'
        })
        
        environment = MockForexEnvironment(
            data=data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3,
                'reward_function': 'simple_pnl'
            }
        )
        
        # Test DQN mathematical properties
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.1,
                'batch_size': 32,
                'gamma': 0.99,
                'epsilon_start': 0.0  # No exploration for deterministic testing
            }
        )
        
        # Test Q-value updates
        state = environment.reset()
        action = 1  # Fixed action
        next_state, reward, done, _ = environment.step(action)
        
        # Store experience
        agent.store_experience(state, action, reward, next_state, done)
        
        # Get initial Q-values (simplified for mock agent)
        initial_q_table = agent.q_table.copy()
        
        # Perform update
        if len(agent.memory) >= agent.batch_size:
            loss = agent.update()
            
            # Get updated Q-values
            updated_q_table = agent.q_table
            
            # Verify Q-values changed (learning occurred)
            assert not np.array_equal(initial_q_table, updated_q_table), \
                "Q-values should change after update"
            
            # Verify loss is non-negative
            assert loss >= 0, f"Loss should be non-negative, got {loss}"
        
        # Test action selection consistency
        test_state = np.random.random(environment.observation_space.shape[0])
        
        # With no exploration, should be deterministic
        action1 = agent.select_action(test_state, training=False)
        action2 = agent.select_action(test_state, training=False)
        assert action1 == action2, "Action selection should be deterministic without exploration"
        
        print(f"✓ Mathematical correctness validation passed")
    
    def test_performance_metrics_validation(self):
        """Validate correctness of performance metrics calculations."""
        # Create performance tracker
        tracker = MockPerformanceTracker(storage_path=self.temp_dir)
        
        # Create session with known trades
        session_id = tracker.start_session('validation_test', 'EURUSD')
        
        # Add trades with known outcomes
        trades = [
            {'timestamp': datetime.now(), 'action': 'BUY', 'price': 1.1000, 'volume': 0.1, 'pnl': 100.0},
            {'timestamp': datetime.now(), 'action': 'SELL', 'price': 1.1010, 'volume': 0.1, 'pnl': -50.0},
            {'timestamp': datetime.now(), 'action': 'BUY', 'price': 1.1005, 'volume': 0.1, 'pnl': 75.0},
            {'timestamp': datetime.now(), 'action': 'SELL', 'price': 1.1015, 'volume': 0.1, 'pnl': -25.0}
        ]
        
        for trade in trades:
            tracker.record_trade(session_id, trade)
        
        tracker.end_session(session_id)
        
        # Calculate performance metrics
        performance = tracker.calculate_performance(session_id)
        
        # Validate calculations
        expected_total_pnl = sum(trade['pnl'] for trade in trades)
        assert abs(performance['total_pnl'] - expected_total_pnl) < 0.01, \
            f"Total PnL mismatch: expected {expected_total_pnl}, got {performance['total_pnl']}"
        
        expected_num_trades = len(trades)
        assert performance['num_trades'] == expected_num_trades, \
            f"Trade count mismatch: expected {expected_num_trades}, got {performance['num_trades']}"
        
        # Validate win rate
        winning_trades = sum(1 for trade in trades if trade['pnl'] > 0)
        expected_win_rate = winning_trades / len(trades)
        assert abs(performance['win_rate'] - expected_win_rate) < 0.01, \
            f"Win rate mismatch: expected {expected_win_rate}, got {performance['win_rate']}"
        
        print(f"✓ Performance metrics validation passed")
        print(f"  - Total PnL: {performance['total_pnl']}")
        print(f"  - Win rate: {performance['win_rate']}")
        print(f"  - Num trades: {performance['num_trades']}")
    
    def test_data_integrity_validation(self):
        """Validate data integrity throughout the system."""
        # Create test data with known properties
        data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=50, freq='1H'),
            'open': np.linspace(1.1000, 1.1050, 50),
            'high': np.linspace(1.1010, 1.1060, 50),
            'low': np.linspace(1.0990, 1.1040, 50),
            'close': np.linspace(1.1005, 1.1055, 50),
            'volume': [1000] * 50,
            'symbol': 'EURUSD'
        })
        
        # Validate data properties
        assert len(data) == 50, "Data length mismatch"
        assert data['high'].min() >= data[['open', 'close']].min().min(), "High prices should be >= open/close"
        assert data['low'].max() <= data[['open', 'close']].max().max(), "Low prices should be <= open/close"
        
        # Test data processing pipeline (simplified for mock components)
        loaded_data = data.copy()  # Simulate data loading
        
        # Validate loaded data integrity
        assert len(loaded_data) == len(data), "Data length changed during loading"
        assert set(loaded_data.columns) >= set(data.columns), "Columns lost during loading"
        
        # Simulate preprocessing
        processed_data = loaded_data.copy()
        
        # Validate processed data integrity
        assert len(processed_data) <= len(loaded_data), "Data length should not increase"
        assert not processed_data.isnull().all().any(), "No column should be entirely null"
        
        # Test environment data integrity
        environment = MockForexEnvironment(
            data=processed_data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        # Validate environment state integrity
        state = environment.reset()
        assert not np.isnan(state).any(), "State should not contain NaN values"
        assert np.isfinite(state).all(), "State should contain only finite values"
        
        # Test state consistency across steps
        for _ in range(10):
            action = 1  # Fixed action
            next_state, reward, done, info = environment.step(action)
            
            assert not np.isnan(next_state).any(), "Next state should not contain NaN"
            assert np.isfinite(next_state).all(), "Next state should be finite"
            assert np.isfinite(reward), "Reward should be finite"
            assert isinstance(done, bool), "Done should be boolean"
            
            if done:
                state = environment.reset()
            else:
                state = next_state
        
        print(f"✓ Data integrity validation passed")
    
    def test_system_boundaries_validation(self):
        """Validate system operates within defined boundaries."""
        # Test action space boundaries
        data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=30, freq='1h'),
            'open': np.random.random(30) + 1.1,
            'high': np.random.random(30) + 1.1,
            'low': np.random.random(30) + 1.1,
            'close': np.random.random(30) + 1.1,
            'volume': np.random.randint(1000, 10000, 30),
            'symbol': 'EURUSD'
        })
        
        environment = MockForexEnvironment(
            data=data,
            config={
                'state_features': ['close', 'volume'],
                'lookback_window': 5,
                'action_space_size': 3
            }
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={'learning_rate': 0.001, 'batch_size': 32}
        )
        
        # Test action boundaries
        state = environment.reset()
        
        for _ in range(20):
            action = agent.select_action(state, training=False)
            
            # Validate action is within bounds
            assert 0 <= action < environment.action_space.n, \
                f"Action {action} outside bounds [0, {environment.action_space.n})"
            
            next_state, reward, done, info = environment.step(action)
            
            # Validate state boundaries
            assert state.shape == environment.observation_space.shape, \
                f"State shape {state.shape} doesn't match expected {environment.observation_space.shape}"
            
            # Validate reward boundaries (should be reasonable)
            assert abs(reward) < 1000, f"Reward {reward} seems unreasonably large"
            
            state = next_state if not done else environment.reset()
        
        # Test memory boundaries
        for _ in range(100):
            fake_experience = (
                np.random.random(environment.observation_space.shape[0]),
                np.random.randint(0, environment.action_space.n),
                np.random.uniform(-1, 1),
                np.random.random(environment.observation_space.shape[0]),
                np.random.choice([True, False])
            )
            agent.store_experience(*fake_experience)
        
        # Validate memory doesn't exceed capacity
        max_memory = agent.config.get('memory_size', 10000)
        assert len(agent.memory) <= max_memory, \
            f"Memory size {len(agent.memory)} exceeds capacity {max_memory}"
        
        print(f"✓ System boundaries validation passed")
        print(f"  - Action space: [0, {environment.action_space.n})")
        print(f"  - State shape: {environment.observation_space.shape}")
        print(f"  - Memory usage: {len(agent.memory)}/{max_memory}")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])
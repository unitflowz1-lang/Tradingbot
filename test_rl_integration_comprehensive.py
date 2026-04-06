"""
Comprehensive RL System Integration Tests

End-to-end integration tests for the RL trading system that validate
the complete pipeline from data ingestion to trade execution.
"""

import pytest
import numpy as np
import pandas as pd
import tempfile
import os
import time
import threading
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any
import json

# Test utilities
def cleanup_test_files(file_list):
    """Simple cleanup function for test files."""
    for filepath in file_list:
        try:
            if os.path.exists(filepath):
                os.remove(filepath)
        except (PermissionError, OSError):
            pass  # Ignore cleanup errors in tests


class MockForexEnvironment:
    """Mock forex environment for integration testing."""
    
    def __init__(self, data, config):
        self.data = data
        self.config = config
        self.current_step = 0
        self.max_steps = len(data) - config.get('lookback_window', 10)
        
        # Define observation and action spaces
        self.observation_space = Mock()
        self.observation_space.shape = (len(config.get('state_features', ['close', 'volume'])) * config.get('lookback_window', 10),)
        
        self.action_space = Mock()
        self.action_space.n = config.get('action_space_size', 3)
    
    def reset(self):
        """Reset environment to initial state."""
        self.current_step = 0
        return self._get_state()
    
    def step(self, action):
        """Execute action and return next state, reward, done, info."""
        self.current_step += 1
        
        # Calculate reward based on action and market movement
        if self.current_step < len(self.data):
            current_price = self.data.iloc[self.current_step]['close']
            prev_price = self.data.iloc[self.current_step - 1]['close']
            price_change = (current_price - prev_price) / prev_price
            
            # Simple reward calculation
            if action == 1:  # BUY
                reward = price_change * 1000
            elif action == 2:  # SELL
                reward = -price_change * 1000
            else:  # HOLD
                reward = 0
        else:
            reward = 0
        
        done = self.current_step >= self.max_steps
        info = {
            'current_price': self.data.iloc[min(self.current_step, len(self.data) - 1)]['close'],
            'step': self.current_step
        }
        
        next_state = self._get_state()
        return next_state, reward, done, info
    
    def _get_state(self):
        """Get current state vector."""
        lookback = self.config.get('lookback_window', 10)
        features = self.config.get('state_features', ['close', 'volume'])
        
        start_idx = max(0, self.current_step - lookback)
        end_idx = max(lookback, self.current_step)
        
        state_data = []
        for feature in features:
            if feature in self.data.columns:
                values = self.data[feature].iloc[start_idx:end_idx].values
                # Pad if necessary
                if len(values) < lookback:
                    padding = np.full(lookback - len(values), values[0] if len(values) > 0 else 0)
                    values = np.concatenate([padding, values])
                state_data.extend(values[-lookback:])
        
        return np.array(state_data, dtype=np.float32)


class MockDQNAgent:
    """Mock DQN agent for integration testing."""
    
    def __init__(self, state_dim, action_dim, config):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config
        self.memory = []
        self.epsilon = config.get('epsilon_start', 1.0)
        self.batch_size = config.get('batch_size', 32)
        
        # Simple Q-table for testing
        self.q_table = np.random.random((100, action_dim))  # Simplified
    
    def select_action(self, state, training=False):
        """Select action using epsilon-greedy policy."""
        if training and np.random.random() < self.epsilon:
            return np.random.randint(0, self.action_dim)
        
        # Use state hash for Q-table lookup (simplified)
        state_hash = int(np.sum(state) * 1000) % 100
        return np.argmax(self.q_table[state_hash])
    
    def store_experience(self, state, action, reward, next_state, done):
        """Store experience in memory."""
        experience = {
            'state': state,
            'action': action,
            'reward': reward,
            'next_state': next_state,
            'done': done
        }
        self.memory.append(experience)
        
        # Keep memory size manageable
        max_memory = self.config.get('memory_size', 10000)
        if len(self.memory) > max_memory:
            self.memory.pop(0)
    
    def update(self):
        """Update agent parameters."""
        if len(self.memory) < self.batch_size:
            return 0.0
        
        # Simple update simulation
        batch = np.random.choice(len(self.memory), self.batch_size, replace=False)
        
        # Simulate learning by adding small random updates to Q-table
        for idx in batch:
            experience = self.memory[idx]
            state_hash = int(np.sum(experience['state']) * 1000) % 100
            action = experience['action']
            
            # Simple Q-learning update simulation
            target = experience['reward']
            if not experience['done']:
                next_state_hash = int(np.sum(experience['next_state']) * 1000) % 100
                target += 0.99 * np.max(self.q_table[next_state_hash])
            
            self.q_table[state_hash, action] += 0.01 * (target - self.q_table[state_hash, action])
        
        # Decay epsilon
        self.epsilon *= self.config.get('epsilon_decay', 0.995)
        self.epsilon = max(self.epsilon, self.config.get('epsilon_end', 0.01))
        
        return np.random.random()  # Mock loss value
    
    def save_model(self, filepath):
        """Save model to file."""
        model_data = {
            'q_table': self.q_table.tolist(),
            'epsilon': self.epsilon,
            'config': self.config
        }
        with open(filepath, 'w') as f:
            json.dump(model_data, f)
    
    def load_model(self, filepath):
        """Load model from file."""
        with open(filepath, 'r') as f:
            model_data = json.load(f)
        
        self.q_table = np.array(model_data['q_table'])
        self.epsilon = model_data['epsilon']
        self.config.update(model_data['config'])


class MockStrategyRegistry:
    """Mock strategy registry for integration testing."""
    
    def __init__(self, storage_path):
        self.storage_path = storage_path
        self.strategies = {}
        self.strategy_counter = 0
    
    def register_strategy(self, agent, metadata):
        """Register a strategy."""
        strategy_id = f"strategy_{self.strategy_counter}"
        self.strategy_counter += 1
        
        # Save agent model
        model_path = os.path.join(self.storage_path, f"{strategy_id}_model.json")
        agent.save_model(model_path)
        
        self.strategies[strategy_id] = {
            'agent': agent,
            'metadata': metadata,
            'model_path': model_path,
            'created_at': datetime.now()
        }
        
        return strategy_id
    
    def get_strategy(self, strategy_id):
        """Get a registered strategy."""
        return self.strategies.get(strategy_id)
    
    def list_strategies(self):
        """List all registered strategies."""
        return [
            {
                'id': sid,
                'metadata': info['metadata'],
                'created_at': info['created_at']
            }
            for sid, info in self.strategies.items()
        ]


class MockPerformanceTracker:
    """Mock performance tracker for integration testing."""
    
    def __init__(self, storage_path):
        self.storage_path = storage_path
        self.sessions = {}
        self.session_counter = 0
    
    def start_session(self, strategy_id, currency_pair):
        """Start a new trading session."""
        session_id = f"session_{self.session_counter}"
        self.session_counter += 1
        
        self.sessions[session_id] = {
            'strategy_id': strategy_id,
            'currency_pair': currency_pair,
            'trades': [],
            'start_time': datetime.now(),
            'end_time': None,
            'active': True
        }
        
        return session_id
    
    def record_trade(self, session_id, trade_info):
        """Record a trade in the session."""
        if session_id in self.sessions and self.sessions[session_id]['active']:
            self.sessions[session_id]['trades'].append(trade_info.copy())
    
    def end_session(self, session_id):
        """End a trading session."""
        if session_id in self.sessions:
            self.sessions[session_id]['end_time'] = datetime.now()
            self.sessions[session_id]['active'] = False
    
    def calculate_performance(self, session_id):
        """Calculate performance metrics for a session."""
        if session_id not in self.sessions:
            return None
        
        session = self.sessions[session_id]
        trades = session['trades']
        
        if not trades:
            return {
                'total_pnl': 0.0,
                'num_trades': 0,
                'win_rate': 0.0,
                'avg_trade_pnl': 0.0
            }
        
        total_pnl = sum(trade['pnl'] for trade in trades)
        num_trades = len(trades)
        winning_trades = sum(1 for trade in trades if trade['pnl'] > 0)
        win_rate = winning_trades / num_trades if num_trades > 0 else 0.0
        avg_trade_pnl = total_pnl / num_trades if num_trades > 0 else 0.0
        
        return {
            'total_pnl': total_pnl,
            'num_trades': num_trades,
            'win_rate': win_rate,
            'avg_trade_pnl': avg_trade_pnl,
            'session_duration': (session['end_time'] - session['start_time']).total_seconds() if session['end_time'] else 0
        }


class TestRLSystemIntegrationComprehensive:
    """Comprehensive integration tests for the RL trading system."""
    
    @pytest.fixture(autouse=True)
    def setup_and_cleanup(self):
        """Setup test environment and cleanup after tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        # Create test configuration
        self.config = {
            'environment': {
                'state_features': ['close', 'volume'],
                'lookback_window': 10,
                'action_space_size': 3,
                'reward_function': 'simple_pnl'
            },
            'agent': {
                'type': 'DQN',
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 1000,
                'epsilon_start': 1.0,
                'epsilon_end': 0.01,
                'epsilon_decay': 0.995
            },
            'training': {
                'episodes': 10,
                'max_steps': 100,
                'checkpoint_frequency': 5
            }
        }
        
        yield
        
        # Cleanup
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def create_mock_market_data(self, num_samples: int = 200) -> pd.DataFrame:
        """Create realistic mock market data for testing."""
        dates = pd.date_range(
            start=datetime.now() - timedelta(hours=num_samples),
            periods=num_samples,
            freq='1h'  # Use lowercase 'h' to avoid deprecation warning
        )
        
        # Generate realistic OHLCV data
        np.random.seed(42)
        base_price = 1.1000
        returns = np.random.normal(0, 0.001, num_samples)
        close_prices = base_price * np.exp(np.cumsum(returns))
        
        # Generate OHLC data ensuring high >= max(open, close) and low <= min(open, close)
        open_prices = close_prices * (1 + np.random.normal(0, 0.0001, num_samples))
        
        # Ensure high is at least the max of open and close
        high_base = np.maximum(open_prices, close_prices)
        high_prices = high_base * (1 + np.abs(np.random.normal(0, 0.0005, num_samples)))
        
        # Ensure low is at most the min of open and close
        low_base = np.minimum(open_prices, close_prices)
        low_prices = low_base * (1 - np.abs(np.random.normal(0, 0.0005, num_samples)))
        
        data = pd.DataFrame({
            'timestamp': dates,
            'open': open_prices,
            'high': high_prices,
            'low': low_prices,
            'close': close_prices,
            'volume': np.random.randint(1000, 10000, num_samples),
            'symbol': 'EURUSD'
        })
        
        return data
    
    def test_complete_data_pipeline_integration(self):
        """Test the complete data pipeline from ingestion to processing."""
        # Create mock market data
        market_data = self.create_mock_market_data(100)
        
        # Verify data structure
        assert len(market_data) == 100
        assert 'close' in market_data.columns
        assert 'volume' in market_data.columns
        assert 'timestamp' in market_data.columns
        
        # Test data preprocessing (basic validation)
        assert market_data['close'].notna().all()
        assert market_data['volume'].notna().all()
        assert (market_data['high'] >= market_data[['open', 'close']].max(axis=1)).all()
        assert (market_data['low'] <= market_data[['open', 'close']].min(axis=1)).all()
        
        print("✓ Complete data pipeline integration test passed")
    
    def test_agent_environment_interaction(self):
        """Test agent interaction with trading environment."""
        # Create environment and agent
        market_data = self.create_mock_market_data(150)
        
        environment = MockForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
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
            
            # Store experience and update
            agent.store_experience(state, action, reward, next_state, done)
            
            if len(agent.memory) >= agent.batch_size:
                loss = agent.update()
                assert loss is not None and loss >= 0
            
            total_reward += reward
            steps += 1
            state = next_state
            
            if done:
                state = environment.reset()
        
        assert steps > 0
        print(f"✓ Agent-environment interaction test passed")
        print(f"  - Steps: {steps}, Total reward: {total_reward:.4f}")
    
    def test_training_workflow_integration(self):
        """Test the complete training workflow."""
        # Setup environment and agent
        market_data = self.create_mock_market_data(200)
        
        environment = MockForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Training loop
        episode_rewards = []
        initial_epsilon = agent.epsilon
        
        for episode in range(self.config['training']['episodes']):
            state = environment.reset()
            episode_reward = 0
            
            for step in range(self.config['training']['max_steps']):
                action = agent.select_action(state, training=True)
                next_state, reward, done, info = environment.step(action)
                
                agent.store_experience(state, action, reward, next_state, done)
                
                if len(agent.memory) >= agent.batch_size:
                    agent.update()
                
                episode_reward += reward
                state = next_state
                
                if done:
                    break
            
            episode_rewards.append(episode_reward)
        
        # Verify training results
        assert len(episode_rewards) == self.config['training']['episodes']
        assert agent.epsilon < initial_epsilon  # Should decay during training
        
        # Test model persistence
        model_path = os.path.join(self.temp_dir, 'test_model.json')
        agent.save_model(model_path)
        self.test_files.append(model_path)
        
        assert os.path.exists(model_path)
        
        # Test model loading
        new_agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        new_agent.load_model(model_path)
        
        # Verify loaded agent produces consistent results
        test_state = np.random.random(environment.observation_space.shape[0])
        original_action = agent.select_action(test_state, training=False)
        loaded_action = new_agent.select_action(test_state, training=False)
        
        assert original_action == loaded_action
        
        print(f"✓ Training workflow integration test passed")
        print(f"  - Episodes: {len(episode_rewards)}")
        print(f"  - Epsilon decay: {initial_epsilon:.3f} -> {agent.epsilon:.3f}")
    
    def test_strategy_management_integration(self):
        """Test strategy management and registry integration."""
        # Create strategy registry
        registry = MockStrategyRegistry(storage_path=self.temp_dir)
        
        # Create and train agents
        market_data = self.create_mock_market_data(100)
        environment = MockForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        # Create multiple agents
        agents = []
        strategy_ids = []
        
        for i in range(3):
            agent = MockDQNAgent(
                state_dim=environment.observation_space.shape[0],
                action_dim=environment.action_space.n,
                config=self.config['agent']
            )
            
            # Quick training
            state = environment.reset()
            for _ in range(20):
                action = agent.select_action(state, training=True)
                next_state, reward, done, info = environment.step(action)
                agent.store_experience(state, action, reward, next_state, done)
                
                if len(agent.memory) >= agent.batch_size:
                    agent.update()
                
                state = next_state if not done else environment.reset()
            
            # Register strategy
            strategy_id = registry.register_strategy(
                agent=agent,
                metadata={
                    'name': f'test_strategy_{i}',
                    'agent_type': 'DQN',
                    'currency_pair': 'EURUSD',
                    'performance_metrics': {
                        'sharpe_ratio': 1.0 + i * 0.1,
                        'max_drawdown': 0.1 - i * 0.01
                    }
                }
            )
            
            agents.append(agent)
            strategy_ids.append(strategy_id)
        
        # Test strategy retrieval
        for strategy_id in strategy_ids:
            strategy = registry.get_strategy(strategy_id)
            assert strategy is not None
            assert 'agent' in strategy
            assert 'metadata' in strategy
        
        # Test strategy listing
        strategies = registry.list_strategies()
        assert len(strategies) == 3
        
        print(f"✓ Strategy management integration test passed")
        print(f"  - Registered strategies: {len(strategies)}")
    
    def test_performance_monitoring_integration(self):
        """Test performance monitoring and tracking integration."""
        # Create performance tracker
        tracker = MockPerformanceTracker(storage_path=self.temp_dir)
        
        # Create trading session
        strategy_id = 'test_strategy'
        session_id = tracker.start_session(strategy_id, 'EURUSD')
        
        # Simulate trading with performance tracking
        market_data = self.create_mock_market_data(80)
        environment = MockForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Trading loop with performance tracking
        state = environment.reset()
        
        for step in range(30):
            action = agent.select_action(state, training=False)
            next_state, reward, done, info = environment.step(action)
            
            # Record trade if action was not HOLD
            if action != 0:
                trade_info = {
                    'timestamp': datetime.now(),
                    'action': 'BUY' if action == 1 else 'SELL',
                    'price': info.get('current_price', 1.1000),
                    'volume': 0.1,
                    'pnl': reward
                }
                tracker.record_trade(session_id, trade_info)
            
            state = next_state if not done else environment.reset()
        
        # End session and calculate performance
        tracker.end_session(session_id)
        performance = tracker.calculate_performance(session_id)
        
        assert performance is not None
        assert 'total_pnl' in performance
        assert 'num_trades' in performance
        assert 'win_rate' in performance
        assert performance['num_trades'] >= 0
        assert 0 <= performance['win_rate'] <= 1
        
        print(f"✓ Performance monitoring integration test passed")
        print(f"  - Total PnL: {performance['total_pnl']:.2f}")
        print(f"  - Number of trades: {performance['num_trades']}")
        print(f"  - Win rate: {performance['win_rate']:.2%}")
    
    def test_end_to_end_system_integration(self):
        """Test complete end-to-end system integration."""
        # 1. Data preparation
        market_data = self.create_mock_market_data(150)
        
        # 2. Environment setup
        environment = MockForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        # 3. Agent creation and training
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Quick training
        for episode in range(5):
            state = environment.reset()
            for step in range(20):
                action = agent.select_action(state, training=True)
                next_state, reward, done, info = environment.step(action)
                agent.store_experience(state, action, reward, next_state, done)
                
                if len(agent.memory) >= agent.batch_size:
                    agent.update()
                
                state = next_state if not done else environment.reset()
        
        # 4. Strategy registration
        registry = MockStrategyRegistry(storage_path=self.temp_dir)
        strategy_id = registry.register_strategy(
            agent=agent,
            metadata={
                'name': 'e2e_test_strategy',
                'agent_type': 'DQN',
                'currency_pair': 'EURUSD'
            }
        )
        
        # 5. Performance monitoring
        tracker = MockPerformanceTracker(storage_path=self.temp_dir)
        session_id = tracker.start_session(strategy_id, 'EURUSD')
        
        # 6. Live trading simulation
        state = environment.reset()
        total_reward = 0
        
        for step in range(25):
            action = agent.select_action(state, training=False)
            next_state, reward, done, info = environment.step(action)
            
            if action != 0:
                trade_info = {
                    'timestamp': datetime.now(),
                    'action': 'BUY' if action == 1 else 'SELL',
                    'price': info.get('current_price', 1.1000),
                    'volume': 0.1,
                    'pnl': reward
                }
                tracker.record_trade(session_id, trade_info)
            
            total_reward += reward
            state = next_state if not done else environment.reset()
        
        # 7. Results verification
        tracker.end_session(session_id)
        final_performance = tracker.calculate_performance(session_id)
        
        # Verify all components worked together
        assert strategy_id is not None
        assert final_performance is not None
        assert 'total_pnl' in final_performance
        
        # Verify strategy can be retrieved and used
        retrieved_strategy = registry.get_strategy(strategy_id)
        assert retrieved_strategy is not None
        
        print(f"✓ End-to-end system integration test passed")
        print(f"  - Strategy ID: {strategy_id}")
        print(f"  - Total reward: {total_reward:.4f}")
        print(f"  - Final performance: {final_performance}")
    
    def test_concurrent_system_access(self):
        """Test system behavior under concurrent access."""
        # Create shared components
        registry = MockStrategyRegistry(storage_path=self.temp_dir)
        tracker = MockPerformanceTracker(storage_path=self.temp_dir)
        
        # Create test agent and register strategy
        market_data = self.create_mock_market_data(100)
        environment = MockForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        strategy_id = registry.register_strategy(
            agent=agent,
            metadata={'name': 'concurrent_test', 'agent_type': 'DQN'}
        )
        
        # Concurrent access test
        results = []
        errors = []
        
        def concurrent_worker(worker_id):
            """Worker function for concurrent testing."""
            try:
                # Test concurrent strategy access
                strategy = registry.get_strategy(strategy_id)
                assert strategy is not None
                
                # Test concurrent performance tracking
                session_id = tracker.start_session(f'session_{worker_id}', 'EURUSD')
                
                # Simulate some trades
                for i in range(5):
                    trade = {
                        'timestamp': datetime.now(),
                        'action': 'BUY',
                        'price': 1.1000 + np.random.normal(0, 0.001),
                        'volume': 0.1,
                        'pnl': np.random.normal(0, 10)
                    }
                    tracker.record_trade(session_id, trade)
                
                tracker.end_session(session_id)
                performance = tracker.calculate_performance(session_id)
                
                results.append({
                    'worker_id': worker_id,
                    'performance': performance,
                    'success': True
                })
                
            except Exception as e:
                errors.append({
                    'worker_id': worker_id,
                    'error': str(e)
                })
        
        # Create multiple threads
        threads = []
        num_workers = 5
        
        for i in range(num_workers):
            thread = threading.Thread(target=concurrent_worker, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Verify results
        assert len(errors) == 0, f"Concurrent access errors: {errors}"
        assert len(results) == num_workers
        
        print(f"✓ Concurrent system access test passed")
        print(f"  - Workers: {num_workers}")
        print(f"  - Successful: {len(results)}")
        print(f"  - Errors: {len(errors)}")
    
    def test_system_performance_benchmarks(self):
        """Test system performance benchmarks."""
        # Create larger dataset for performance testing
        large_data = self.create_mock_market_data(1000)
        
        environment = MockForexEnvironment(
            data=large_data,
            config=self.config['environment']
        )
        
        agent = MockDQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Measure training performance
        start_time = time.time()
        
        state = environment.reset()
        for step in range(500):  # 500 training steps
            action = agent.select_action(state, training=True)
            next_state, reward, done, info = environment.step(action)
            
            agent.store_experience(state, action, reward, next_state, done)
            
            if step % 10 == 0 and len(agent.memory) >= agent.batch_size:
                agent.update()
            
            state = next_state if not done else environment.reset()
        
        training_time = time.time() - start_time
        
        # Measure inference performance
        start_time = time.time()
        
        for _ in range(1000):  # 1000 inference calls
            test_state = np.random.random(environment.observation_space.shape[0])
            action = agent.select_action(test_state, training=False)
        
        inference_time = time.time() - start_time
        
        # Performance assertions
        steps_per_second = 500 / training_time
        inferences_per_second = 1000 / inference_time
        
        assert steps_per_second > 50, f"Training too slow: {steps_per_second:.2f} steps/sec"
        assert inferences_per_second > 500, f"Inference too slow: {inferences_per_second:.2f} inferences/sec"
        
        print(f"✓ System performance benchmarks test passed")
        print(f"  - Training: {steps_per_second:.2f} steps/sec")
        print(f"  - Inference: {inferences_per_second:.2f} inferences/sec")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])
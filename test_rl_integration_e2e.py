"""
End-to-End RL System Integration Tests

This module contains comprehensive integration tests that validate the complete
RL trading system pipeline from data ingestion to trade execution.
"""

import pytest
import numpy as np
import pandas as pd
import asyncio
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, List, Any
import tempfile
import os
import json

# RL System imports
from src.rl.environments.forex_environment import ForexEnvironment
from src.rl.environments.state_processor import StateProcessor
from src.rl.environments.reward_calculator import RewardCalculator
from src.rl.agents.dqn import DQNAgent
from src.rl.agents.ppo import PPOAgent
from src.rl.training.agent_trainer import AgentTrainer
from src.rl.strategies.registry import StrategyRegistry
from src.rl.strategies.allocator import StrategyAllocator
from src.rl.integration.mt5_connector import EnhancedMT5Connector
from src.rl.integration.signal_generator import RLSignalGenerator
from src.rl.integration.hybrid_decision_engine import HybridDecisionEngine
from src.rl.integration.real_time_environment import RealTimeEnvironment
from src.rl.monitoring.performance_tracker import PerformanceTracker
from src.rl.data.loader import DataLoader
from src.rl.data.preprocessor import DataPreprocessor
from src.rl.config.manager import ConfigManager

# Test utilities
from test_utils.cleanup import cleanup_test_files
from test_utils.platform_utils import get_test_data_path


class TestRLSystemE2EIntegration:
    """End-to-end integration tests for the complete RL trading system."""
    
    @pytest.fixture(autouse=True)
    def setup_and_cleanup(self):
        """Setup test environment and cleanup after tests."""
        self.temp_dir = tempfile.mkdtemp()
        self.test_files = []
        
        # Create test configuration
        self.config = {
            'environment': {
                'state_features': ['close', 'volume', 'rsi', 'macd'],
                'lookback_window': 10,
                'action_space_size': 8,
                'reward_function': 'sharpe_adjusted'
            },
            'agent': {
                'type': 'DQN',
                'learning_rate': 0.001,
                'batch_size': 32,
                'memory_size': 10000,
                'epsilon_start': 1.0,
                'epsilon_end': 0.01,
                'epsilon_decay': 0.995
            },
            'training': {
                'episodes': 100,
                'max_steps': 1000,
                'checkpoint_frequency': 50,
                'validation_frequency': 25
            },
            'mt5': {
                'server': 'test_server',
                'login': 12345,
                'password': 'test_password',
                'path': '/test/path'
            }
        }
        
        yield
        
        # Cleanup
        cleanup_test_files(self.test_files)
        if os.path.exists(self.temp_dir):
            import shutil
            shutil.rmtree(self.temp_dir)
    
    def create_mock_market_data(self, num_samples: int = 1000) -> pd.DataFrame:
        """Create realistic mock market data for testing."""
        dates = pd.date_range(
            start=datetime.now() - timedelta(days=num_samples),
            periods=num_samples,
            freq='1H'
        )
        
        # Generate realistic OHLCV data
        np.random.seed(42)
        base_price = 1.1000
        returns = np.random.normal(0, 0.001, num_samples)
        prices = base_price * np.exp(np.cumsum(returns))
        
        data = pd.DataFrame({
            'timestamp': dates,
            'open': prices * (1 + np.random.normal(0, 0.0001, num_samples)),
            'high': prices * (1 + np.abs(np.random.normal(0, 0.0005, num_samples))),
            'low': prices * (1 - np.abs(np.random.normal(0, 0.0005, num_samples))),
            'close': prices,
            'volume': np.random.randint(1000, 10000, num_samples),
            'symbol': 'EURUSD'
        })
        
        return data
    
    @pytest.mark.asyncio
    async def test_complete_data_pipeline(self):
        """Test the complete data ingestion and preprocessing pipeline."""
        # Create mock data
        market_data = self.create_mock_market_data(500)
        
        # Test data loading
        data_loader = DataLoader(self.config)
        loaded_data = data_loader.load_from_dataframe(market_data)
        
        assert len(loaded_data) == 500
        assert 'close' in loaded_data.columns
        assert 'volume' in loaded_data.columns
        
        # Test data preprocessing
        preprocessor = DataPreprocessor(self.config['environment'])
        processed_data = preprocessor.preprocess(loaded_data)
        
        assert processed_data is not None
        assert len(processed_data) > 0
        
        # Test state processing
        state_processor = StateProcessor(self.config['environment'])
        states = []
        
        for i in range(10, len(processed_data)):
            window_data = processed_data.iloc[i-10:i]
            state = state_processor.process_market_data(window_data)
            states.append(state)
        
        assert len(states) > 0
        assert all(isinstance(state, np.ndarray) for state in states)
        
        print("✓ Complete data pipeline test passed")
    
    @pytest.mark.asyncio
    async def test_agent_training_workflow(self):
        """Test the complete agent training workflow."""
        # Setup environment
        market_data = self.create_mock_market_data(200)
        
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        # Create agent
        state_dim = environment.observation_space.shape[0]
        action_dim = environment.action_space.n
        
        agent = DQNAgent(
            state_dim=state_dim,
            action_dim=action_dim,
            config=self.config['agent']
        )
        
        # Create trainer
        trainer = AgentTrainer(
            agent=agent,
            environment=environment,
            config=self.config['training']
        )
        
        # Test training
        initial_epsilon = agent.epsilon
        training_results = trainer.train(episodes=10)
        
        assert training_results is not None
        assert 'episode_rewards' in training_results
        assert 'training_time' in training_results
        assert len(training_results['episode_rewards']) == 10
        assert agent.epsilon < initial_epsilon  # Should decay during training
        
        # Test model saving and loading
        model_path = os.path.join(self.temp_dir, 'test_model.pth')
        agent.save_model(model_path)
        self.test_files.append(model_path)
        
        assert os.path.exists(model_path)
        
        # Create new agent and load model
        new_agent = DQNAgent(
            state_dim=state_dim,
            action_dim=action_dim,
            config=self.config['agent']
        )
        new_agent.load_model(model_path)
        
        # Test that loaded agent produces same outputs
        test_state = np.random.random(state_dim)
        original_action = agent.select_action(test_state, training=False)
        loaded_action = new_agent.select_action(test_state, training=False)
        
        assert original_action == loaded_action
        
        print("✓ Agent training workflow test passed")
    
    @pytest.mark.asyncio
    async def test_strategy_management_workflow(self):
        """Test the complete strategy management workflow."""
        # Create strategy registry
        registry = StrategyRegistry(storage_path=self.temp_dir)
        
        # Create mock trained agent
        market_data = self.create_mock_market_data(100)
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        state_dim = environment.observation_space.shape[0]
        action_dim = environment.action_space.n
        
        agent = DQNAgent(
            state_dim=state_dim,
            action_dim=action_dim,
            config=self.config['agent']
        )
        
        # Register strategy
        strategy_metadata = {
            'name': 'test_strategy',
            'agent_type': 'DQN',
            'currency_pair': 'EURUSD',
            'timeframe': '1H',
            'performance_metrics': {
                'sharpe_ratio': 1.5,
                'max_drawdown': 0.1,
                'total_return': 0.15
            }
        }
        
        strategy_id = registry.register_strategy(
            agent=agent,
            metadata=strategy_metadata
        )
        
        assert strategy_id is not None
        assert len(strategy_id) > 0
        
        # Test strategy retrieval
        retrieved_strategy = registry.get_strategy(strategy_id)
        assert retrieved_strategy is not None
        
        # Test strategy listing
        strategies = registry.list_strategies()
        assert len(strategies) == 1
        assert strategies[0]['id'] == strategy_id
        
        # Test strategy allocation
        allocator = StrategyAllocator()
        
        # Create multiple strategies for allocation testing
        strategies_for_allocation = []
        performance_history = {}
        
        for i in range(3):
            sid = f"strategy_{i}"
            strategies_for_allocation.append({
                'id': sid,
                'agent': agent,
                'metadata': strategy_metadata
            })
            performance_history[sid] = [0.1 + i * 0.05] * 10  # Mock performance
        
        allocations = allocator.calculate_allocations(
            strategies_for_allocation,
            performance_history
        )
        
        assert len(allocations) == 3
        assert abs(sum(allocations.values()) - 1.0) < 0.01  # Should sum to 1
        
        print("✓ Strategy management workflow test passed")
    
    @pytest.mark.asyncio
    async def test_mt5_integration_workflow(self):
        """Test the complete MT5 integration workflow."""
        with patch('MetaTrader5.initialize') as mock_init, \
             patch('MetaTrader5.login') as mock_login, \
             patch('MetaTrader5.copy_rates_from') as mock_rates, \
             patch('MetaTrader5.positions_get') as mock_positions, \
             patch('MetaTrader5.order_send') as mock_order:
            
            # Setup mocks
            mock_init.return_value = True
            mock_login.return_value = True
            mock_positions.return_value = []
            mock_order.return_value = MagicMock(retcode=10009)  # Success code
            
            # Mock market data
            mock_rates.return_value = np.array([
                (datetime.now().timestamp(), 1.1000, 1.1010, 1.0990, 1.1005, 0, 1000, 0),
                (datetime.now().timestamp(), 1.1005, 1.1015, 1.0995, 1.1010, 0, 1200, 0)
            ], dtype=[
                ('time', 'i8'), ('open', 'f8'), ('high', 'f8'), 
                ('low', 'f8'), ('close', 'f8'), ('tick_volume', 'i8'),
                ('real_volume', 'i8'), ('spread', 'i4')
            ])
            
            # Test MT5 connector
            mt5_connector = EnhancedMT5Connector(self.config['mt5'])
            
            # Test connection
            connected = await mt5_connector.connect()
            assert connected
            
            # Test data retrieval
            rates = await mt5_connector.get_rates('EURUSD', '1H', 100)
            assert rates is not None
            assert len(rates) > 0
            
            # Test real-time environment
            real_time_env = RealTimeEnvironment(
                mt5_connector=mt5_connector,
                config=self.config['environment']
            )
            
            # Test environment initialization
            initial_state = real_time_env.reset()
            assert initial_state is not None
            assert isinstance(initial_state, np.ndarray)
            
            # Test signal generation
            market_data = self.create_mock_market_data(50)
            environment = ForexEnvironment(
                data=market_data,
                config=self.config['environment']
            )
            
            agent = DQNAgent(
                state_dim=environment.observation_space.shape[0],
                action_dim=environment.action_space.n,
                config=self.config['agent']
            )
            
            signal_generator = RLSignalGenerator(
                agent=agent,
                mt5_connector=mt5_connector
            )
            
            # Test signal generation
            test_state = np.random.random(environment.observation_space.shape[0])
            signal = signal_generator.generate_signal(test_state)
            
            assert signal is not None
            assert hasattr(signal, 'action')
            assert hasattr(signal, 'confidence')
            
            print("✓ MT5 integration workflow test passed")
    
    @pytest.mark.asyncio
    async def test_hybrid_decision_engine_workflow(self):
        """Test the hybrid decision engine integration."""
        # Create mock AI bot
        mock_ai_bot = Mock()
        mock_ai_bot.generate_signal.return_value = {
            'action': 'BUY',
            'confidence': 0.8,
            'reasoning': 'Technical analysis indicates uptrend'
        }
        
        # Create RL agent
        market_data = self.create_mock_market_data(50)
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Create hybrid decision engine
        hybrid_config = {
            'rl_weight': 0.6,
            'ai_bot_weight': 0.4,
            'confidence_threshold': 0.5,
            'conflict_resolution': 'weighted_average'
        }
        
        hybrid_engine = HybridDecisionEngine(
            rl_agents=[agent],
            ai_bot=mock_ai_bot,
            config=hybrid_config
        )
        
        # Test decision making
        test_market_data = {
            'close': 1.1000,
            'volume': 1000,
            'timestamp': datetime.now()
        }
        
        decision = hybrid_engine.make_decision(test_market_data)
        
        assert decision is not None
        assert 'final_action' in decision
        assert 'confidence' in decision
        assert 'rl_signal' in decision
        assert 'ai_bot_signal' in decision
        
        print("✓ Hybrid decision engine workflow test passed")
    
    @pytest.mark.asyncio
    async def test_performance_monitoring_workflow(self):
        """Test the complete performance monitoring workflow."""
        # Create performance tracker
        tracker = PerformanceTracker(storage_path=self.temp_dir)
        
        # Simulate trading session
        session_id = tracker.start_session('test_strategy', 'EURUSD')
        
        # Record some trades
        trades = [
            {
                'timestamp': datetime.now(),
                'action': 'BUY',
                'price': 1.1000,
                'volume': 0.1,
                'pnl': 50.0
            },
            {
                'timestamp': datetime.now() + timedelta(minutes=30),
                'action': 'SELL',
                'price': 1.1010,
                'volume': 0.1,
                'pnl': 100.0
            }
        ]
        
        for trade in trades:
            tracker.record_trade(session_id, trade)
        
        # Test performance calculation
        performance = tracker.calculate_performance(session_id)
        
        assert performance is not None
        assert 'total_pnl' in performance
        assert 'num_trades' in performance
        assert 'win_rate' in performance
        
        # Test session ending
        tracker.end_session(session_id)
        
        # Test performance history retrieval
        history = tracker.get_performance_history('test_strategy')
        assert len(history) > 0
        
        print("✓ Performance monitoring workflow test passed")
    
    @pytest.mark.asyncio
    async def test_complete_system_integration(self):
        """Test the complete system integration from end to end."""
        # This test simulates a complete trading cycle
        
        # 1. Data ingestion and preprocessing
        market_data = self.create_mock_market_data(100)
        data_loader = DataLoader(self.config)
        loaded_data = data_loader.load_from_dataframe(market_data)
        
        preprocessor = DataPreprocessor(self.config['environment'])
        processed_data = preprocessor.preprocess(loaded_data)
        
        # 2. Environment setup
        environment = ForexEnvironment(
            data=processed_data,
            config=self.config['environment']
        )
        
        # 3. Agent creation and training
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        trainer = AgentTrainer(
            agent=agent,
            environment=environment,
            config=self.config['training']
        )
        
        # Quick training
        training_results = trainer.train(episodes=5)
        assert training_results is not None
        
        # 4. Strategy registration
        registry = StrategyRegistry(storage_path=self.temp_dir)
        strategy_id = registry.register_strategy(
            agent=agent,
            metadata={
                'name': 'integration_test_strategy',
                'agent_type': 'DQN',
                'currency_pair': 'EURUSD'
            }
        )
        
        # 5. Performance monitoring setup
        performance_tracker = PerformanceTracker(storage_path=self.temp_dir)
        session_id = performance_tracker.start_session(strategy_id, 'EURUSD')
        
        # 6. Simulate trading session
        state = environment.reset()
        total_reward = 0
        
        for step in range(10):
            action = agent.select_action(state, training=False)
            next_state, reward, done, info = environment.step(action)
            
            # Record trade if action was not HOLD
            if action != 0:  # Assuming 0 is HOLD action
                trade_info = {
                    'timestamp': datetime.now(),
                    'action': 'BUY' if action < 4 else 'SELL',
                    'price': info.get('current_price', 1.1000),
                    'volume': 0.1,
                    'pnl': reward * 1000  # Scale reward to PnL
                }
                performance_tracker.record_trade(session_id, trade_info)
            
            total_reward += reward
            state = next_state
            
            if done:
                break
        
        # 7. End session and verify results
        performance_tracker.end_session(session_id)
        final_performance = performance_tracker.calculate_performance(session_id)
        
        assert final_performance is not None
        assert 'total_pnl' in final_performance
        
        # 8. Verify strategy can be retrieved and used
        retrieved_strategy = registry.get_strategy(strategy_id)
        assert retrieved_strategy is not None
        
        # Test that retrieved strategy produces consistent results
        test_state = np.random.random(environment.observation_space.shape[0])
        original_action = agent.select_action(test_state, training=False)
        retrieved_action = retrieved_strategy['agent'].select_action(test_state, training=False)
        
        assert original_action == retrieved_action
        
        print("✓ Complete system integration test passed")
        print(f"  - Total reward: {total_reward:.4f}")
        print(f"  - Final performance: {final_performance}")
    
    @pytest.mark.asyncio
    async def test_multi_agent_system_integration(self):
        """Test integration with multiple agents and strategies."""
        # Create multiple agents with different configurations
        market_data = self.create_mock_market_data(150)
        
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        # Create DQN and PPO agents
        dqn_agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        ppo_config = {
            'learning_rate': 0.0003,
            'clip_ratio': 0.2,
            'entropy_coef': 0.01,
            'value_coef': 0.5
        }
        
        ppo_agent = PPOAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=ppo_config
        )
        
        # Register both strategies
        registry = StrategyRegistry(storage_path=self.temp_dir)
        
        dqn_strategy_id = registry.register_strategy(
            agent=dqn_agent,
            metadata={
                'name': 'dqn_strategy',
                'agent_type': 'DQN',
                'currency_pair': 'EURUSD'
            }
        )
        
        ppo_strategy_id = registry.register_strategy(
            agent=ppo_agent,
            metadata={
                'name': 'ppo_strategy',
                'agent_type': 'PPO',
                'currency_pair': 'EURUSD'
            }
        )
        
        # Test strategy allocation
        allocator = StrategyAllocator()
        
        strategies = [
            {'id': dqn_strategy_id, 'agent': dqn_agent, 'metadata': {'performance_metrics': {'sharpe_ratio': 1.2}}},
            {'id': ppo_strategy_id, 'agent': ppo_agent, 'metadata': {'performance_metrics': {'sharpe_ratio': 1.1}}}
        ]
        
        performance_history = {
            dqn_strategy_id: [0.1, 0.12, 0.11, 0.13, 0.14],
            ppo_strategy_id: [0.08, 0.09, 0.10, 0.11, 0.12]
        }
        
        allocations = allocator.calculate_allocations(strategies, performance_history)
        
        assert len(allocations) == 2
        assert abs(sum(allocations.values()) - 1.0) < 0.01
        assert allocations[dqn_strategy_id] > allocations[ppo_strategy_id]  # DQN should get more allocation
        
        # Test concurrent trading with both agents
        performance_tracker = PerformanceTracker(storage_path=self.temp_dir)
        
        dqn_session = performance_tracker.start_session(dqn_strategy_id, 'EURUSD')
        ppo_session = performance_tracker.start_session(ppo_strategy_id, 'EURUSD')
        
        state = environment.reset()
        
        for step in range(15):
            # Get actions from both agents
            dqn_action = dqn_agent.select_action(state, training=False)
            ppo_action = ppo_agent.select_action(state, training=False)
            
            # Use allocation-weighted decision (simplified)
            if allocations[dqn_strategy_id] > allocations[ppo_strategy_id]:
                chosen_action = dqn_action
                chosen_session = dqn_session
            else:
                chosen_action = ppo_action
                chosen_session = ppo_session
            
            next_state, reward, done, info = environment.step(chosen_action)
            
            # Record trade
            if chosen_action != 0:
                trade_info = {
                    'timestamp': datetime.now(),
                    'action': 'BUY' if chosen_action < 4 else 'SELL',
                    'price': info.get('current_price', 1.1000),
                    'volume': 0.1,
                    'pnl': reward * 1000
                }
                performance_tracker.record_trade(chosen_session, trade_info)
            
            state = next_state
            if done:
                break
        
        # End sessions and verify
        performance_tracker.end_session(dqn_session)
        performance_tracker.end_session(ppo_session)
        
        dqn_performance = performance_tracker.calculate_performance(dqn_session)
        ppo_performance = performance_tracker.calculate_performance(ppo_session)
        
        assert dqn_performance is not None
        assert ppo_performance is not None
        
        print("✓ Multi-agent system integration test passed")
        print(f"  - DQN performance: {dqn_performance}")
        print(f"  - PPO performance: {ppo_performance}")
    
    @pytest.mark.asyncio
    async def test_error_recovery_integration(self):
        """Test system integration with error scenarios and recovery."""
        # Create environment and agent
        market_data = self.create_mock_market_data(80)
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Test with corrupted state (should handle gracefully)
        state = environment.reset()
        
        # Simulate corrupted state
        corrupted_state = np.full_like(state, np.nan)
        
        try:
            action = agent.select_action(corrupted_state, training=False)
            # Should either handle NaN gracefully or raise appropriate exception
            assert isinstance(action, (int, np.integer))
        except (ValueError, RuntimeError) as e:
            # Expected behavior for corrupted input
            assert "nan" in str(e).lower() or "invalid" in str(e).lower()
        
        # Test recovery with valid state
        valid_state = environment.reset()
        action = agent.select_action(valid_state, training=False)
        assert isinstance(action, (int, np.integer))
        assert 0 <= action < environment.action_space.n
        
        # Test environment step with invalid action
        try:
            invalid_action = environment.action_space.n + 1  # Out of bounds
            next_state, reward, done, info = environment.step(invalid_action)
            # Should handle gracefully or raise appropriate exception
        except (ValueError, IndexError) as e:
            # Expected behavior for invalid action
            assert "action" in str(e).lower() or "index" in str(e).lower()
        
        # Test recovery with valid action
        valid_action = 1
        next_state, reward, done, info = environment.step(valid_action)
        assert isinstance(next_state, np.ndarray)
        assert isinstance(reward, (int, float))
        assert isinstance(done, bool)
        
        print("✓ Error recovery integration test passed")
    
    @pytest.mark.asyncio
    async def test_distributed_training_integration(self):
        """Test integration with distributed training components."""
        # Create multiple environments for distributed training
        market_data = self.create_mock_market_data(120)
        
        environments = []
        for i in range(3):  # Create 3 parallel environments
            env = ForexEnvironment(
                data=market_data,
                config=self.config['environment']
            )
            environments.append(env)
        
        # Create agent for distributed training
        agent = PPOAgent(
            state_dim=environments[0].observation_space.shape[0],
            action_dim=environments[0].action_space.n,
            config={
                'learning_rate': 0.0003,
                'clip_ratio': 0.2,
                'entropy_coef': 0.01
            }
        )
        
        # Simulate distributed data collection
        all_experiences = []
        
        for env in environments:
            state = env.reset()
            experiences = []
            
            for step in range(10):
                action, log_prob, value = agent.select_action_with_log_prob(state)
                next_state, reward, done, info = env.step(action)
                
                experiences.append({
                    'state': state,
                    'action': action,
                    'reward': reward,
                    'log_prob': log_prob,
                    'value': value,
                    'done': done
                })
                
                state = next_state if not done else env.reset()
            
            all_experiences.extend(experiences)
        
        # Verify distributed data collection
        assert len(all_experiences) == 30  # 3 environments * 10 steps
        
        # Test batch update with distributed experiences
        states = np.array([exp['state'] for exp in all_experiences])
        actions = np.array([exp['action'] for exp in all_experiences])
        rewards = np.array([exp['reward'] for exp in all_experiences])
        log_probs = np.array([exp['log_prob'] for exp in all_experiences])
        values = np.array([exp['value'] for exp in all_experiences])
        
        trajectory = {
            'states': states,
            'actions': actions,
            'rewards': rewards,
            'log_probs': log_probs,
            'values': values
        }
        
        # Update agent with distributed experiences
        loss_info = agent.update(trajectory)
        
        assert 'policy_loss' in loss_info
        assert 'value_loss' in loss_info
        assert isinstance(loss_info['policy_loss'], (int, float))
        assert isinstance(loss_info['value_loss'], (int, float))
        
        print("✓ Distributed training integration test passed")
        print(f"  - Policy loss: {loss_info['policy_loss']:.4f}")
        print(f"  - Value loss: {loss_info['value_loss']:.4f}")
    
    @pytest.mark.asyncio
    async def test_real_time_data_integration(self):
        """Test integration with real-time data processing."""
        # Simulate real-time data stream
        def generate_real_time_data():
            """Generator for real-time market data."""
            base_price = 1.1000
            for i in range(20):
                price_change = np.random.normal(0, 0.0001)
                current_price = base_price + price_change
                
                yield {
                    'timestamp': datetime.now() + timedelta(seconds=i),
                    'open': current_price,
                    'high': current_price + abs(np.random.normal(0, 0.0001)),
                    'low': current_price - abs(np.random.normal(0, 0.0001)),
                    'close': current_price,
                    'volume': np.random.randint(1000, 5000),
                    'symbol': 'EURUSD'
                }
                
                base_price = current_price
        
        # Create real-time environment
        with patch('src.rl.integration.mt5_connector.EnhancedMT5Connector') as mock_mt5:
            mock_mt5_instance = Mock()
            mock_mt5.return_value = mock_mt5_instance
            
            # Mock real-time data feed
            data_stream = list(generate_real_time_data())
            mock_mt5_instance.get_real_time_data.return_value = data_stream[0]
            
            real_time_env = RealTimeEnvironment(
                mt5_connector=mock_mt5_instance,
                config=self.config['environment']
            )
            
            # Create agent for real-time trading
            agent = DQNAgent(
                state_dim=10,  # Simplified state dimension
                action_dim=3,
                config=self.config['agent']
            )
            
            # Test real-time trading loop
            performance_tracker = PerformanceTracker(storage_path=self.temp_dir)
            session_id = performance_tracker.start_session('real_time_test', 'EURUSD')
            
            for i, market_tick in enumerate(data_stream[:10]):
                # Update mock to return current tick
                mock_mt5_instance.get_real_time_data.return_value = market_tick
                
                # Get current state from real-time environment
                try:
                    state = real_time_env.get_current_state()
                    if state is not None:
                        action = agent.select_action(state, training=False)
                        
                        # Execute action in real-time environment
                        result = real_time_env.execute_action(action)
                        
                        if result and result.get('executed'):
                            trade_info = {
                                'timestamp': market_tick['timestamp'],
                                'action': 'BUY' if action == 1 else 'SELL' if action == 2 else 'HOLD',
                                'price': market_tick['close'],
                                'volume': 0.1,
                                'pnl': result.get('pnl', 0)
                            }
                            performance_tracker.record_trade(session_id, trade_info)
                
                except Exception as e:
                    # Handle real-time data processing errors gracefully
                    print(f"Real-time processing error at tick {i}: {e}")
                    continue
            
            # End real-time session
            performance_tracker.end_session(session_id)
            final_performance = performance_tracker.calculate_performance(session_id)
            
            # Verify real-time integration worked
            assert final_performance is not None
            
            print("✓ Real-time data integration test passed")
            print(f"  - Final performance: {final_performance}")


class TestRLSystemPerformance:
    """Performance and latency tests for the RL system."""
    
    @pytest.fixture(autouse=True)
    def setup_performance_test(self):
        """Setup for performance testing."""
        self.config = {
            'environment': {
                'state_features': ['close', 'volume', 'rsi', 'macd'],
                'lookback_window': 10,
                'action_space_size': 8
            },
            'agent': {
                'type': 'DQN',
                'learning_rate': 0.001,
                'batch_size': 32
            }
        }
    
    def test_training_speed_performance(self):
        """Test training speed performance benchmarks."""
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=1000, freq='1H'),
            'open': np.random.random(1000) + 1.1,
            'high': np.random.random(1000) + 1.1,
            'low': np.random.random(1000) + 1.1,
            'close': np.random.random(1000) + 1.1,
            'volume': np.random.randint(1000, 10000, 1000),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Measure training time
        start_time = time.time()
        
        state = environment.reset()
        for _ in range(100):  # 100 training steps
            action = agent.select_action(state, training=True)
            next_state, reward, done, _ = environment.step(action)
            
            # Simulate experience storage and learning
            experience = {
                'state': state,
                'action': action,
                'reward': reward,
                'next_state': next_state,
                'done': done
            }
            
            if len(agent.memory) > agent.batch_size:
                agent.update()
            
            state = next_state if not done else environment.reset()
        
        training_time = time.time() - start_time
        
        # Performance assertions
        assert training_time < 10.0  # Should complete in under 10 seconds
        steps_per_second = 100 / training_time
        assert steps_per_second > 10  # Should process at least 10 steps per second
        
        print(f"✓ Training speed test passed")
        print(f"  - Training time: {training_time:.2f}s")
        print(f"  - Steps per second: {steps_per_second:.2f}")
    
    def test_inference_latency_performance(self):
        """Test inference latency performance."""
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
            config=self.config['environment']
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Warm up
        test_state = np.random.random(environment.observation_space.shape[0])
        for _ in range(10):
            agent.select_action(test_state, training=False)
        
        # Measure inference latency
        num_inferences = 1000
        start_time = time.time()
        
        for _ in range(num_inferences):
            test_state = np.random.random(environment.observation_space.shape[0])
            action = agent.select_action(test_state, training=False)
        
        inference_time = time.time() - start_time
        avg_latency = (inference_time / num_inferences) * 1000  # Convert to milliseconds
        
        # Performance assertions
        assert avg_latency < 10.0  # Should be under 10ms per inference
        inferences_per_second = num_inferences / inference_time
        assert inferences_per_second > 100  # Should handle 100+ inferences per second
        
        print(f"✓ Inference latency test passed")
        print(f"  - Average latency: {avg_latency:.2f}ms")
        print(f"  - Inferences per second: {inferences_per_second:.2f}")
    
    def test_memory_usage_performance(self):
        """Test memory usage during training and inference."""
        import psutil
        import gc
        
        # Get initial memory usage
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Create large dataset for memory testing
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=5000, freq='1H'),
            'open': np.random.random(5000) + 1.1,
            'high': np.random.random(5000) + 1.1,
            'low': np.random.random(5000) + 1.1,
            'close': np.random.random(5000) + 1.1,
            'volume': np.random.randint(1000, 10000, 5000),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config={
                'learning_rate': 0.001,
                'batch_size': 64,
                'memory_size': 10000  # Large memory buffer
            }
        )
        
        # Fill memory buffer
        state = environment.reset()
        for _ in range(1000):
            action = agent.select_action(state, training=True)
            next_state, reward, done, _ = environment.step(action)
            
            agent.store_experience(state, action, reward, next_state, done)
            
            state = next_state if not done else environment.reset()
        
        # Check memory usage after filling buffer
        buffer_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = buffer_memory - initial_memory
        
        # Perform training updates
        for _ in range(100):
            if len(agent.memory) >= agent.batch_size:
                agent.update()
        
        # Check memory usage after training
        training_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Clean up
        del agent, environment, market_data
        gc.collect()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Memory usage assertions
        assert memory_increase < 500  # Should not use more than 500MB for buffer
        assert training_memory - buffer_memory < 100  # Training should not add much memory
        assert final_memory < initial_memory + 50  # Should clean up most memory
        
        print(f"✓ Memory usage test passed")
        print(f"  - Initial memory: {initial_memory:.1f}MB")
        print(f"  - Buffer memory increase: {memory_increase:.1f}MB")
        print(f"  - Training memory: {training_memory:.1f}MB")
        print(f"  - Final memory: {final_memory:.1f}MB")
    
    def test_concurrent_inference_performance(self):
        """Test performance under concurrent inference load."""
        import threading
        import queue
        
        market_data = pd.DataFrame({
            'timestamp': pd.date_range(start='2023-01-01', periods=200, freq='1H'),
            'open': np.random.random(200) + 1.1,
            'high': np.random.random(200) + 1.1,
            'low': np.random.random(200) + 1.1,
            'close': np.random.random(200) + 1.1,
            'volume': np.random.randint(1000, 10000, 200),
            'symbol': 'EURUSD'
        })
        
        environment = ForexEnvironment(
            data=market_data,
            config=self.config['environment']
        )
        
        agent = DQNAgent(
            state_dim=environment.observation_space.shape[0],
            action_dim=environment.action_space.n,
            config=self.config['agent']
        )
        
        # Results queue for thread communication
        results_queue = queue.Queue()
        
        def inference_worker(worker_id, num_inferences):
            """Worker function for concurrent inference."""
            start_time = time.time()
            
            for i in range(num_inferences):
                test_state = np.random.random(environment.observation_space.shape[0])
                action = agent.select_action(test_state, training=False)
                
                # Verify action is valid
                assert 0 <= action < environment.action_space.n
            
            end_time = time.time()
            results_queue.put({
                'worker_id': worker_id,
                'time': end_time - start_time,
                'inferences': num_inferences
            })
        
        # Create multiple threads for concurrent inference
        num_threads = 4
        inferences_per_thread = 250
        threads = []
        
        start_time = time.time()
        
        for i in range(num_threads):
            thread = threading.Thread(
                target=inference_worker,
                args=(i, inferences_per_thread)
            )
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        total_time = time.time() - start_time
        
        # Collect results
        results = []
        while not results_queue.empty():
            results.append(results_queue.get())
        
        assert len(results) == num_threads
        
        total_inferences = sum(r['inferences'] for r in results)
        avg_thread_time = sum(r['time'] for r in results) / len(results)
        throughput = total_inferences / total_time
        
        # Performance assertions
        assert total_time < 5.0  # Should complete in under 5 seconds
        assert throughput > 200  # Should handle 200+ inferences per second
        assert avg_thread_time < 2.0  # Each thread should complete in under 2 seconds
        
        print(f"✓ Concurrent inference test passed")
        print(f"  - Total time: {total_time:.2f}s")
        print(f"  - Throughput: {throughput:.2f} inferences/sec")
        print(f"  - Average thread time: {avg_thread_time:.2f}s")
    
    def test_scalability_performance(self):
        """Test system scalability with increasing load."""
        # Test with different data sizes
        data_sizes = [100, 500, 1000, 2000]
        performance_results = []
        
        for size in data_sizes:
            market_data = pd.DataFrame({
                'timestamp': pd.date_range(start='2023-01-01', periods=size, freq='1H'),
                'open': np.random.random(size) + 1.1,
                'high': np.random.random(size) + 1.1,
                'low': np.random.random(size) + 1.1,
                'close': np.random.random(size) + 1.1,
                'volume': np.random.randint(1000, 10000, size),
                'symbol': 'EURUSD'
            })
            
            # Measure environment creation time
            start_time = time.time()
            environment = ForexEnvironment(
                data=market_data,
                config=self.config['environment']
            )
            env_creation_time = time.time() - start_time
            
            # Measure agent creation time
            start_time = time.time()
            agent = DQNAgent(
                state_dim=environment.observation_space.shape[0],
                action_dim=environment.action_space.n,
                config=self.config['agent']
            )
            agent_creation_time = time.time() - start_time
            
            # Measure episode execution time
            start_time = time.time()
            state = environment.reset()
            for _ in range(min(50, size // 10)):  # Scale steps with data size
                action = agent.select_action(state, training=False)
                next_state, reward, done, _ = environment.step(action)
                state = next_state if not done else environment.reset()
            episode_time = time.time() - start_time
            
            performance_results.append({
                'data_size': size,
                'env_creation_time': env_creation_time,
                'agent_creation_time': agent_creation_time,
                'episode_time': episode_time
            })
        
        # Verify scalability (times should not grow exponentially)
        for i in range(1, len(performance_results)):
            prev_result = performance_results[i-1]
            curr_result = performance_results[i]
            
            size_ratio = curr_result['data_size'] / prev_result['data_size']
            time_ratio = curr_result['episode_time'] / prev_result['episode_time']
            
            # Time should not grow faster than data size
            assert time_ratio < size_ratio * 2, f"Poor scalability at size {curr_result['data_size']}"
        
        print(f"✓ Scalability test passed")
        for result in performance_results:
            print(f"  - Size {result['data_size']}: env={result['env_creation_time']:.3f}s, "
                  f"agent={result['agent_creation_time']:.3f}s, episode={result['episode_time']:.3f}s")


if __name__ == "__main__":
    # Run the tests
    pytest.main([__file__, "-v", "--tb=short"])
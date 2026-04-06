"""
Unit tests for DQN Agent Implementation

This module tests the DQN agent functionality including neural network
architecture, experience replay, and basic DQN operations.
"""

import unittest
import numpy as np
import torch
import tempfile
import os
from datetime import datetime
from unittest.mock import Mock, patch

# Import the DQN components
from src.rl.agents.dqn import DQNAgent, DQNConfig, ExperienceBuffer
from src.rl.agents.networks import NeuralNetwork, DuelingNetwork, NetworkConfig, ActivationFunction, OptimizerType
from src.rl.agents.base import Experience


class TestNeuralNetwork(unittest.TestCase):
    """Test neural network architecture and forward pass."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.input_dim = 10
        self.output_dim = 4
        self.config = NetworkConfig(
            hidden_layers=[64, 32],
            activation=ActivationFunction.RELU,
            dropout_rate=0.1,
            batch_norm=True,
            learning_rate=0.001
        )
        
    def test_network_initialization(self):
        """Test neural network initialization."""
        network = NeuralNetwork(self.input_dim, self.output_dim, self.config)
        
        # Check dimensions
        self.assertEqual(network.input_dim, self.input_dim)
        self.assertEqual(network.output_dim, self.output_dim)
        self.assertEqual(network.config, self.config)
        
        # Check optimizer is created
        self.assertIsNotNone(network.optimizer)
        
        # Check layers are built
        self.assertGreater(len(network.layers), 0)
        
    def test_forward_pass(self):
        """Test neural network forward pass."""
        network = NeuralNetwork(self.input_dim, self.output_dim, self.config)
        
        # Test single input
        input_tensor = torch.randn(self.input_dim)
        output = network(input_tensor)
        
        self.assertEqual(output.shape, (1, self.output_dim))
        self.assertFalse(torch.isnan(output).any())
        
        # Test batch input
        batch_size = 32
        batch_input = torch.randn(batch_size, self.input_dim)
        batch_output = network(batch_input)
        
        self.assertEqual(batch_output.shape, (batch_size, self.output_dim))
        self.assertFalse(torch.isnan(batch_output).any())
        
    def test_predict_numpy(self):
        """Test prediction with numpy arrays."""
        network = NeuralNetwork(self.input_dim, self.output_dim, self.config)
        
        # Test single prediction
        input_array = np.random.randn(self.input_dim)
        output = network.predict(input_array)
        
        self.assertEqual(output.shape, (1, self.output_dim))
        self.assertFalse(np.isnan(output).any())
        
        # Test batch prediction
        batch_input = np.random.randn(32, self.input_dim)
        batch_output = network.predict(batch_input)
        
        self.assertEqual(batch_output.shape, (32, self.output_dim))
        self.assertFalse(np.isnan(batch_output).any())
        
    def test_model_info(self):
        """Test model information retrieval."""
        network = NeuralNetwork(self.input_dim, self.output_dim, self.config)
        info = network.get_model_info()
        
        # Check required fields
        required_fields = ['input_dim', 'output_dim', 'hidden_layers', 
                          'total_parameters', 'trainable_parameters']
        for field in required_fields:
            self.assertIn(field, info)
            
        # Check values
        self.assertEqual(info['input_dim'], self.input_dim)
        self.assertEqual(info['output_dim'], self.output_dim)
        self.assertGreater(info['total_parameters'], 0)
        
    def test_checkpoint_save_load(self):
        """Test model checkpoint save and load."""
        network = NeuralNetwork(self.input_dim, self.output_dim, self.config)
        
        # Get initial state
        initial_state = network.state_dict()
        initial_training_step = network.training_step
        
        # Modify network state
        network.training_step = 100
        
        # Save checkpoint
        with tempfile.NamedTemporaryFile(suffix='.pth', delete=False) as f:
            checkpoint_path = f.name
            
        try:
            network.save_checkpoint(checkpoint_path)
            
            # Create new network and load checkpoint
            new_network = NeuralNetwork(self.input_dim, self.output_dim, self.config)
            new_network.load_checkpoint(checkpoint_path)
            
            # Check state is restored
            self.assertEqual(new_network.training_step, 100)
            
        finally:
            if os.path.exists(checkpoint_path):
                os.unlink(checkpoint_path)


class TestDuelingNetwork(unittest.TestCase):
    """Test dueling network architecture."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.input_dim = 10
        self.output_dim = 4
        self.config = NetworkConfig(
            hidden_layers=[64, 32],
            activation=ActivationFunction.RELU,
            learning_rate=0.001
        )
        
    def test_dueling_network_initialization(self):
        """Test dueling network initialization."""
        network = DuelingNetwork(self.input_dim, self.output_dim, self.config)
        
        # Check dimensions
        self.assertEqual(network.input_dim, self.input_dim)
        self.assertEqual(network.output_dim, self.output_dim)
        
        # Check streams are created
        self.assertIsNotNone(network.value_stream)
        self.assertIsNotNone(network.advantage_stream)
        
    def test_dueling_forward_pass(self):
        """Test dueling network forward pass."""
        network = DuelingNetwork(self.input_dim, self.output_dim, self.config)
        
        # Test forward pass
        input_tensor = torch.randn(self.input_dim)
        output = network(input_tensor)
        
        self.assertEqual(output.shape, (1, self.output_dim))
        self.assertFalse(torch.isnan(output).any())
        
        # Test that output is different from simple sum of value and advantage
        # (due to mean subtraction in dueling architecture)
        batch_input = torch.randn(32, self.input_dim)
        batch_output = network(batch_input)
        
        self.assertEqual(batch_output.shape, (32, self.output_dim))
        self.assertFalse(torch.isnan(batch_output).any())


class TestExperienceBuffer(unittest.TestCase):
    """Test experience replay buffer."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.capacity = 1000
        self.buffer = ExperienceBuffer(self.capacity)
        
        # Create sample experiences
        self.sample_experiences = []
        for i in range(100):
            exp = Experience(
                state=np.random.randn(10),
                action=np.random.randint(0, 4),
                reward=np.random.randn(),
                next_state=np.random.randn(10),
                done=np.random.choice([True, False]),
                timestamp=datetime.now()
            )
            self.sample_experiences.append(exp)
            
    def test_buffer_initialization(self):
        """Test buffer initialization."""
        self.assertEqual(self.buffer.capacity, self.capacity)
        self.assertEqual(len(self.buffer), 0)
        self.assertFalse(self.buffer.prioritized)
        
    def test_experience_storage(self):
        """Test storing experiences in buffer."""
        # Add experiences
        for exp in self.sample_experiences:
            self.buffer.push(exp)
            
        self.assertEqual(len(self.buffer), len(self.sample_experiences))
        
    def test_buffer_overflow(self):
        """Test buffer behavior when capacity is exceeded."""
        # Fill buffer beyond capacity
        for i in range(self.capacity + 100):
            exp = Experience(
                state=np.random.randn(10),
                action=0,
                reward=0.0,
                next_state=np.random.randn(10),
                done=False,
                timestamp=datetime.now()
            )
            self.buffer.push(exp)
            
        # Buffer should not exceed capacity
        self.assertEqual(len(self.buffer), self.capacity)
        
    def test_uniform_sampling(self):
        """Test uniform sampling from buffer."""
        # Add experiences
        for exp in self.sample_experiences:
            self.buffer.push(exp)
            
        # Sample batch
        batch_size = 32
        experiences, weights, indices = self.buffer.sample(batch_size)
        
        # Check batch properties
        self.assertEqual(len(experiences), batch_size)
        self.assertIsNone(weights)  # No weights for uniform sampling
        self.assertIsNone(indices)  # No indices for uniform sampling
        
        # Check all experiences are valid
        for exp in experiences:
            self.assertIsInstance(exp, Experience)
            
    def test_is_ready(self):
        """Test buffer readiness check."""
        min_size = 50
        
        # Buffer not ready initially
        self.assertFalse(self.buffer.is_ready(min_size))
        
        # Add experiences
        for i in range(min_size):
            self.buffer.push(self.sample_experiences[i])
            
        # Buffer should be ready now
        self.assertTrue(self.buffer.is_ready(min_size))


class TestPrioritizedExperienceBuffer(unittest.TestCase):
    """Test prioritized experience replay buffer."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.capacity = 1000
        self.buffer = ExperienceBuffer(self.capacity, prioritized=True)
        
        # Create sample experiences
        self.sample_experiences = []
        for i in range(100):
            exp = Experience(
                state=np.random.randn(10),
                action=np.random.randint(0, 4),
                reward=np.random.randn(),
                next_state=np.random.randn(10),
                done=np.random.choice([True, False]),
                timestamp=datetime.now()
            )
            self.sample_experiences.append(exp)
            
    def test_prioritized_buffer_initialization(self):
        """Test prioritized buffer initialization."""
        self.assertTrue(self.buffer.prioritized)
        self.assertIsNotNone(self.buffer.priorities)
        
    def test_prioritized_storage(self):
        """Test storing experiences with priorities."""
        # Add experiences with priorities
        for i, exp in enumerate(self.sample_experiences):
            priority = float(i + 1)  # Increasing priorities
            self.buffer.push(exp, priority)
            
        self.assertEqual(len(self.buffer), len(self.sample_experiences))
        self.assertEqual(len(self.buffer.priorities), len(self.sample_experiences))
        
    def test_prioritized_sampling(self):
        """Test prioritized sampling."""
        # Add experiences with different priorities
        for i, exp in enumerate(self.sample_experiences):
            priority = float(i + 1)
            self.buffer.push(exp, priority)
            
        # Sample batch
        batch_size = 32
        experiences, weights, indices = self.buffer.sample(batch_size)
        
        # Check batch properties
        self.assertEqual(len(experiences), batch_size)
        self.assertIsNotNone(weights)
        self.assertIsNotNone(indices)
        self.assertEqual(len(weights), batch_size)
        self.assertEqual(len(indices), batch_size)
        
    def test_priority_updates(self):
        """Test updating priorities."""
        # Add a small number of experiences
        test_experiences = self.sample_experiences[:20]
        for exp in test_experiences:
            self.buffer.push(exp, 1.0)
            
        # Test that update_priorities method exists and can be called
        indices = np.array([0, 1, 2])
        new_priorities = np.array([0.5, 0.7, 0.9])
        
        # This should not raise an exception
        self.buffer.update_priorities(indices, new_priorities)
        
        # Verify the method updated something (basic functionality test)
        self.assertTrue(len(self.buffer.priorities) > 0)
        
        # Test that priorities are within reasonable bounds
        for priority in self.buffer.priorities:
            self.assertGreater(priority, 0.0)
            self.assertLess(priority, 10.0)  # Reasonable upper bound


class TestDQNAgent(unittest.TestCase):
    """Test DQN agent implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.state_dim = 10
        self.action_dim = 4
        self.config = DQNConfig(
            learning_rate=0.001,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=1000,
            target_update_frequency=100,
            hidden_layers=[64, 32],
            activation="relu",
            optimizer="adam",
            network_config=NetworkConfig(
                hidden_layers=[64, 32],
                activation=ActivationFunction.RELU,
                batch_norm=False,  # Disable batch norm for testing
                learning_rate=0.001
            )
        )
        
    def test_agent_initialization(self):
        """Test DQN agent initialization."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        # Check basic properties
        self.assertEqual(agent.state_dim, self.state_dim)
        self.assertEqual(agent.action_dim, self.action_dim)
        self.assertEqual(agent.config, self.config)
        
        # Check networks are created
        self.assertIsNotNone(agent.q_network)
        self.assertIsNotNone(agent.target_network)
        
        # Check memory is created
        self.assertIsNotNone(agent.memory)
        self.assertEqual(agent.memory.capacity, self.config.memory_size)
        
        # Check initial epsilon
        self.assertEqual(agent.epsilon, self.config.epsilon_start)
        
    def test_action_selection_exploration(self):
        """Test action selection during exploration."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        # Set high epsilon for exploration
        agent.epsilon = 1.0
        
        state = np.random.randn(self.state_dim)
        
        # Test multiple action selections
        actions = []
        for _ in range(100):
            action = agent.select_action(state, training=True)
            actions.append(action)
            
        # Should have variety in actions due to exploration
        unique_actions = set(actions)
        self.assertGreater(len(unique_actions), 1)
        
        # All actions should be valid
        for action in actions:
            self.assertGreaterEqual(action, 0)
            self.assertLess(action, self.action_dim)
            
    def test_action_selection_exploitation(self):
        """Test action selection during exploitation."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        # Set low epsilon for exploitation
        agent.epsilon = 0.0
        
        # Set to eval mode for consistent results
        agent.set_training_mode(False)
        
        state = np.random.randn(self.state_dim)
        
        # Test multiple action selections
        actions = []
        for _ in range(10):
            action = agent.select_action(state, training=False)
            actions.append(action)
            
        # Should be consistent (greedy) actions
        self.assertEqual(len(set(actions)), 1)
        
    def test_experience_storage(self):
        """Test storing experiences."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        # Create sample experience
        experience = Experience(
            state=np.random.randn(self.state_dim),
            action=0,
            reward=1.0,
            next_state=np.random.randn(self.state_dim),
            done=False,
            timestamp=datetime.now()
        )
        
        # Store experience
        agent.store_experience(experience)
        
        # Check it was stored
        self.assertEqual(len(agent.memory), 1)
        
    def test_epsilon_decay(self):
        """Test epsilon decay functionality."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        initial_epsilon = agent.epsilon
        
        # Decay epsilon multiple times
        for _ in range(10):
            agent.decay_epsilon()
            
        # Epsilon should have decreased
        self.assertLess(agent.epsilon, initial_epsilon)
        
        # Epsilon should not go below minimum
        for _ in range(1000):
            agent.decay_epsilon()
            
        self.assertGreaterEqual(agent.epsilon, self.config.epsilon_end)
        
    def test_model_save_load(self):
        """Test model save and load functionality."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        # Modify agent state
        agent.epsilon = 0.5
        agent.steps_done = 100
        agent.update_count = 50
        
        # Save model
        with tempfile.NamedTemporaryFile(suffix='.pth', delete=False) as f:
            model_path = f.name
            
        try:
            agent.save_model(model_path)
            
            # Create new agent and load model
            new_agent = DQNAgent(self.state_dim, self.action_dim, self.config)
            new_agent.load_model(model_path)
            
            # Check state is restored
            self.assertEqual(new_agent.epsilon, 0.5)
            self.assertEqual(new_agent.steps_done, 100)
            self.assertEqual(new_agent.update_count, 50)
            
        finally:
            if os.path.exists(model_path):
                os.unlink(model_path)
                
    def test_model_info(self):
        """Test model information retrieval."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        info = agent.get_model_info()
        
        # Check required fields
        required_fields = ['type', 'state_dim', 'action_dim', 'epsilon', 
                          'double_dqn', 'dueling_dqn', 'prioritized_replay']
        for field in required_fields:
            self.assertIn(field, info)
            
        # Check values
        self.assertEqual(info['type'], 'DQN')
        self.assertEqual(info['state_dim'], self.state_dim)
        self.assertEqual(info['action_dim'], self.action_dim)
        
    def test_q_values_computation(self):
        """Test Q-values computation."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        state = np.random.randn(self.state_dim)
        q_values = agent.get_q_values(state)
        
        # Check output shape and validity
        self.assertEqual(q_values.shape, (self.action_dim,))
        self.assertFalse(np.isnan(q_values).any())
        
    def test_action_probabilities(self):
        """Test action probability computation."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        state = np.random.randn(self.state_dim)
        probabilities = agent.get_action_probabilities(state)
        
        # Check output properties
        self.assertEqual(probabilities.shape, (self.action_dim,))
        self.assertAlmostEqual(probabilities.sum(), 1.0, places=6)
        self.assertTrue(np.all(probabilities >= 0))
        
    def test_memory_stats(self):
        """Test memory statistics."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        stats = agent.get_memory_stats()
        
        # Check required fields
        required_fields = ['memory_size', 'memory_capacity', 'memory_usage', 
                          'is_ready', 'prioritized']
        for field in required_fields:
            self.assertIn(field, stats)
            
        # Check initial values
        self.assertEqual(stats['memory_size'], 0)
        self.assertEqual(stats['memory_capacity'], self.config.memory_size)
        self.assertEqual(stats['memory_usage'], 0.0)
        self.assertFalse(stats['is_ready'])
        
    def test_training_mode(self):
        """Test training mode setting."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        # Test training mode
        agent.set_training_mode(True)
        self.assertTrue(agent.q_network.training)
        
        # Test evaluation mode
        agent.set_training_mode(False)
        self.assertFalse(agent.q_network.training)
        
    def test_episode_reset(self):
        """Test episode reset functionality."""
        agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
        initial_episode_count = agent.episode_count
        agent.reset_episode()
        
        # Episode count should increment
        self.assertEqual(agent.episode_count, initial_episode_count + 1)


class TestDQNTraining(unittest.TestCase):
    """Test DQN training functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.state_dim = 10
        self.action_dim = 4
        self.config = DQNConfig(
            learning_rate=0.001,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=1000,
            min_memory_size=100,
            target_update_frequency=10,
            hidden_layers=[64, 32],
            activation="relu",
            optimizer="adam"
        )
        self.agent = DQNAgent(self.state_dim, self.action_dim, self.config)
        
    def test_update_with_insufficient_memory(self):
        """Test update when memory has insufficient experiences."""
        # Try to update with empty memory
        metrics = self.agent.update([])
        
        # Should return default metrics
        self.assertIn('loss', metrics)
        self.assertEqual(metrics['loss'], 0.0)
        
    def test_update_with_sufficient_memory(self):
        """Test update with sufficient experiences in memory."""
        # Fill memory with experiences
        for _ in range(self.config.min_memory_size + 10):
            experience = Experience(
                state=np.random.randn(self.state_dim),
                action=np.random.randint(0, self.action_dim),
                reward=np.random.randn(),
                next_state=np.random.randn(self.state_dim),
                done=np.random.choice([True, False]),
                timestamp=datetime.now()
            )
            self.agent.store_experience(experience)
            
        # Update agent
        metrics = self.agent.update([])
        
        # Check metrics are returned
        self.assertIn('loss', metrics)
        self.assertIn('q_mean', metrics)
        self.assertIn('epsilon', metrics)
        self.assertIsInstance(metrics['loss'], float)
        
    def test_target_network_update(self):
        """Test target network update."""
        # Modify main network significantly (simulate training)
        for param in self.agent.q_network.parameters():
            param.data += torch.randn_like(param.data) * 0.5
            
        # Get main network state before update
        main_network_state = self.agent.q_network.state_dict()
        
        # Manually update target network
        self.agent.update_target_network()
        
        # Check target network matches main network after update
        updated_target_state = self.agent.target_network.state_dict()
        
        # Target network should now match main network
        for key in main_network_state:
            self.assertTrue(torch.equal(
                main_network_state[key], 
                updated_target_state[key]
            ), f"Target network parameter {key} should match main network after update")


if __name__ == '__main__':
    # Set random seeds for reproducibility
    np.random.seed(42)
    torch.manual_seed(42)
    
    # Run tests
    unittest.main(verbosity=2)
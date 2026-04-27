"""
Unit tests for PPO policy and value networks.

Tests the basic functionality of PolicyNetwork and ValueNetwork classes
including forward passes, action probability computation, and value estimation.
"""

import pytest
import numpy as np
import torch
import torch.nn as nn
from unittest.mock import Mock, patch

from src.rl.agents.ppo import PolicyNetwork, ValueNetwork, PPOAgent, PPOConfig
from src.rl.agents.networks import NetworkConfig, ActivationFunction, OptimizerType


class TestPolicyNetwork:
    """Test cases for PolicyNetwork class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.state_dim = 10
        self.action_dim = 4
        self.config = NetworkConfig(
            hidden_layers=[64, 32],
            activation=ActivationFunction.TANH,
            dropout_rate=0.0,
            batch_norm=False,
            optimizer=OptimizerType.ADAM,
            learning_rate=0.001
        )
        self.network = PolicyNetwork(self.state_dim, self.action_dim, self.config)
        
    def test_initialization(self):
        """Test network initialization."""
        assert self.network.state_dim == self.state_dim
        assert self.network.action_dim == self.action_dim
        assert self.network.config == self.config
        assert isinstance(self.network.optimizer, torch.optim.Adam)
        
    def test_forward_pass(self):
        """Test forward pass through network."""
        batch_size = 5
        state = torch.randn(batch_size, self.state_dim)
        
        logits = self.network.forward(state)
        
        assert logits.shape == (batch_size, self.action_dim)
        assert not torch.isnan(logits).any()
        assert not torch.isinf(logits).any()
        
    def test_single_state_forward(self):
        """Test forward pass with single state."""
        state = torch.randn(self.state_dim)
        
        logits = self.network.forward(state.unsqueeze(0))
        
        assert logits.shape == (1, self.action_dim)
        
    def test_action_probabilities(self):
        """Test action probability computation."""
        batch_size = 3
        state = torch.randn(batch_size, self.state_dim)
        
        probs = self.network.get_action_probabilities(state)
        
        assert probs.shape == (batch_size, self.action_dim)
        assert torch.allclose(probs.sum(dim=-1), torch.ones(batch_size), atol=1e-6)
        assert (probs >= 0).all()
        assert (probs <= 1).all()
        
    def test_log_probabilities(self):
        """Test log probability computation."""
        batch_size = 3
        state = torch.randn(batch_size, self.state_dim)
        
        log_probs = self.network.get_log_probabilities(state)
        
        assert log_probs.shape == (batch_size, self.action_dim)
        assert (log_probs <= 0).all()  # Log probabilities should be <= 0
        
        # Check consistency with regular probabilities
        probs = self.network.get_action_probabilities(state)
        expected_log_probs = torch.log(probs)
        assert torch.allclose(log_probs, expected_log_probs, atol=1e-6)
        
    def test_different_activations(self):
        """Test network with different activation functions."""
        activations = [ActivationFunction.RELU, ActivationFunction.TANH, 
                      ActivationFunction.ELU, ActivationFunction.SWISH]
        
        for activation in activations:
            config = NetworkConfig(
                hidden_layers=[32],
                activation=activation,
                dropout_rate=0.0,
                batch_norm=False,
                optimizer=OptimizerType.ADAM,
                learning_rate=0.001
            )
            network = PolicyNetwork(self.state_dim, self.action_dim, config)
            
            state = torch.randn(2, self.state_dim)
            logits = network.forward(state)
            
            assert logits.shape == (2, self.action_dim)
            assert not torch.isnan(logits).any()
            
    def test_weight_initialization(self):
        """Test that weights are properly initialized."""
        # Check that policy head has smaller weights
        policy_head_weight_norm = torch.norm(self.network.policy_head.weight)
        
        # Find a backbone linear layer for comparison
        backbone_weight_norm = None
        for layer in self.network.backbone:
            if isinstance(layer, nn.Linear):
                backbone_weight_norm = torch.norm(layer.weight)
                break
                
        if backbone_weight_norm is not None:
            # Policy head should have smaller weights (due to gain=0.01)
            assert policy_head_weight_norm < backbone_weight_norm
            
    def test_gradient_flow(self):
        """Test that gradients flow through the network."""
        state = torch.randn(2, self.state_dim, requires_grad=True)
        logits = self.network.forward(state)
        loss = logits.sum()
        loss.backward()
        
        # Check that gradients exist
        assert state.grad is not None
        assert not torch.isnan(state.grad).any()
        
        # Check network parameter gradients
        for param in self.network.parameters():
            if param.requires_grad:
                assert param.grad is not None
                assert not torch.isnan(param.grad).any()


class TestValueNetwork:
    """Test cases for ValueNetwork class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.state_dim = 10
        self.config = NetworkConfig(
            hidden_layers=[64, 32],
            activation=ActivationFunction.TANH,
            dropout_rate=0.0,
            batch_norm=False,
            optimizer=OptimizerType.ADAM,
            learning_rate=0.001
        )
        self.network = ValueNetwork(self.state_dim, self.config)
        
    def test_initialization(self):
        """Test network initialization."""
        assert self.network.state_dim == self.state_dim
        assert self.network.config == self.config
        assert isinstance(self.network.optimizer, torch.optim.Adam)
        
    def test_forward_pass(self):
        """Test forward pass through network."""
        batch_size = 5
        state = torch.randn(batch_size, self.state_dim)
        
        values = self.network.forward(state)
        
        assert values.shape == (batch_size,)
        assert not torch.isnan(values).any()
        assert not torch.isinf(values).any()
        
    def test_single_state_forward(self):
        """Test forward pass with single state."""
        state = torch.randn(self.state_dim)
        
        value = self.network.forward(state.unsqueeze(0))
        
        assert value.shape == (1,)
        
    def test_value_range(self):
        """Test that values are reasonable (not extreme)."""
        batch_size = 10
        state = torch.randn(batch_size, self.state_dim)
        
        values = self.network.forward(state)
        
        # Values should be finite and not extremely large
        assert torch.isfinite(values).all()
        assert torch.abs(values).max() < 1000  # Reasonable upper bound
        
    def test_different_activations(self):
        """Test network with different activation functions."""
        activations = [ActivationFunction.RELU, ActivationFunction.TANH, 
                      ActivationFunction.ELU, ActivationFunction.SWISH]
        
        for activation in activations:
            config = NetworkConfig(
                hidden_layers=[32],
                activation=activation,
                dropout_rate=0.0,
                batch_norm=False,
                optimizer=OptimizerType.ADAM,
                learning_rate=0.001
            )
            network = ValueNetwork(self.state_dim, config)
            
            state = torch.randn(2, self.state_dim)
            values = network.forward(state)
            
            assert values.shape == (2,)
            assert not torch.isnan(values).any()
            
    def test_gradient_flow(self):
        """Test that gradients flow through the network."""
        state = torch.randn(2, self.state_dim, requires_grad=True)
        values = self.network.forward(state)
        loss = values.sum()
        loss.backward()
        
        # Check that gradients exist
        assert state.grad is not None
        assert not torch.isnan(state.grad).any()
        
        # Check network parameter gradients
        for param in self.network.parameters():
            if param.requires_grad:
                assert param.grad is not None
                assert not torch.isnan(param.grad).any()


class TestPPOAgent:
    """Test cases for PPOAgent class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.state_dim = 8
        self.action_dim = 3
        self.config = PPOConfig(
            learning_rate=0.001,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=10000,
            target_update_frequency=100,
            hidden_layers=[32, 16],
            activation="tanh",
            optimizer="adam",
            clip_ratio=0.2,
            entropy_coef=0.01,
            value_coef=0.5,
            ppo_epochs=2,
            gae_lambda=0.95
        )
        self.agent = PPOAgent(self.state_dim, self.action_dim, self.config)
        
    def test_initialization(self):
        """Test agent initialization."""
        assert self.agent.state_dim == self.state_dim
        assert self.agent.action_dim == self.action_dim
        assert isinstance(self.agent.policy_network, PolicyNetwork)
        assert isinstance(self.agent.value_network, ValueNetwork)
        assert len(self.agent.trajectory_buffer) == 0
        
    def test_select_action_training(self):
        """Test action selection in training mode."""
        state = np.random.randn(self.state_dim)
        
        action = self.agent.select_action(state, training=True)
        
        assert isinstance(action, int)
        assert 0 <= action < self.action_dim
        
    def test_select_action_inference(self):
        """Test action selection in inference mode."""
        state = np.random.randn(self.state_dim)
        
        action = self.agent.select_action(state, training=False)
        
        assert isinstance(action, int)
        assert 0 <= action < self.action_dim
        
    def test_get_action_and_value(self):
        """Test getting action, value, and log probability."""
        state = np.random.randn(self.state_dim)
        
        action, value, log_prob = self.agent.get_action_and_value(state)
        
        assert isinstance(action, int)
        assert 0 <= action < self.action_dim
        assert isinstance(value, float)
        assert isinstance(log_prob, float)
        assert log_prob <= 0  # Log probabilities should be <= 0
        
    def test_store_trajectory_step(self):
        """Test storing trajectory steps."""
        state = np.random.randn(self.state_dim)
        action = 1
        reward = 0.5
        value = 0.3
        log_prob = -1.2
        
        self.agent.store_trajectory_step(state, action, reward, value, log_prob)
        
        assert len(self.agent.trajectory_buffer) == 1
        step = self.agent.trajectory_buffer[0]
        assert np.array_equal(step['state'], state)
        assert step['action'] == action
        assert step['reward'] == reward
        assert step['value'] == value
        assert step['log_prob'] == log_prob
        
    def test_update_empty_trajectory(self):
        """Test update with empty trajectory."""
        metrics = self.agent.update([])
        
        assert metrics['policy_loss'] == 0.0
        assert metrics['value_loss'] == 0.0
        assert metrics['entropy'] == 0.0
        
    def test_update_with_trajectory(self):
        """Test update with trajectory data."""
        # Store some trajectory steps
        for i in range(5):
            state = np.random.randn(self.state_dim)
            action = i % self.action_dim
            reward = np.random.randn()
            value = np.random.randn()
            log_prob = -np.random.rand()
            
            self.agent.store_trajectory_step(state, action, reward, value, log_prob)
            
        metrics = self.agent.update([])
        
        assert isinstance(metrics['policy_loss'], float)
        assert isinstance(metrics['value_loss'], float)
        assert isinstance(metrics['entropy'], float)
        assert metrics['update_count'] == 1
        assert len(self.agent.trajectory_buffer) == 0  # Should be cleared
        
    def test_get_action_probabilities(self):
        """Test getting action probabilities."""
        state = np.random.randn(self.state_dim)
        
        probs = self.agent.get_action_probabilities(state)
        
        assert probs.shape == (self.action_dim,)
        assert np.allclose(probs.sum(), 1.0, atol=1e-6)
        assert (probs >= 0).all()
        assert (probs <= 1).all()
        
    def test_get_state_value(self):
        """Test getting state value."""
        state = np.random.randn(self.state_dim)
        
        value = self.agent.get_state_value(state)
        
        assert isinstance(value, float)
        assert np.isfinite(value)
        
    def test_model_info(self):
        """Test getting model information."""
        info = self.agent.get_model_info()
        
        assert info['type'] == 'PPO'
        assert info['state_dim'] == self.state_dim
        assert info['action_dim'] == self.action_dim
        assert 'policy_parameters' in info
        assert 'value_parameters' in info
        assert 'total_parameters' in info
        assert info['clip_ratio'] == self.config.clip_ratio
        
    def test_training_mode(self):
        """Test setting training mode."""
        # Test training mode
        self.agent.set_training_mode(True)
        assert self.agent.policy_network.training
        assert self.agent.value_network.training
        
        # Test evaluation mode
        self.agent.set_training_mode(False)
        assert not self.agent.policy_network.training
        assert not self.agent.value_network.training
        
    def test_reset_episode(self):
        """Test episode reset."""
        initial_episode_count = self.agent.episode_count
        
        self.agent.reset_episode()
        
        assert self.agent.episode_count == initial_episode_count + 1
        
    @patch('torch.save')
    def test_save_model(self, mock_save):
        """Test model saving."""
        filepath = "test_model.pth"
        
        self.agent.save_model(filepath)
        
        mock_save.assert_called_once()
        args, kwargs = mock_save.call_args
        assert args[1] == filepath
        
        # Check checkpoint contents
        checkpoint = args[0]
        assert 'policy_network_state_dict' in checkpoint
        assert 'value_network_state_dict' in checkpoint
        assert 'config' in checkpoint
        
    @patch('torch.load')
    def test_load_model(self, mock_load):
        """Test model loading."""
        filepath = "test_model.pth"
        
        # Get actual state dicts from the agent
        policy_state_dict = self.agent.policy_network.state_dict()
        value_state_dict = self.agent.value_network.state_dict()
        policy_optimizer_state_dict = self.agent.policy_network.optimizer.state_dict()
        value_optimizer_state_dict = self.agent.value_network.optimizer.state_dict()
        
        # Mock checkpoint data with actual state dicts
        mock_checkpoint = {
            'policy_network_state_dict': policy_state_dict,
            'value_network_state_dict': value_state_dict,
            'policy_optimizer_state_dict': policy_optimizer_state_dict,
            'value_optimizer_state_dict': value_optimizer_state_dict,
            'config': self.config,
            'update_count': 5,
            'training_step': 100,
            'episode_count': 10
        }
        mock_load.return_value = mock_checkpoint
        
        self.agent.load_model(filepath)
        
        mock_load.assert_called_once_with(filepath, map_location=self.agent.device, weights_only=False)
        assert self.agent.update_count == 5
        assert self.agent.training_step == 100
        assert self.agent.episode_count == 10


if __name__ == "__main__":
    pytest.main([__file__])
"""
Unit tests for PPO training algorithm components.

Tests the PPO training algorithm, GAE calculation, learning rate scheduling,
and other training optimizations.
"""

import pytest
import numpy as np
import torch
import math
from unittest.mock import Mock, patch

from src.rl.agents.ppo_trainer import (
    PPOTrainer, PPOTrainingConfig, LearningRateScheduler, 
    ClippingRatioScheduler, GAECalculator
)
from src.rl.agents.ppo import PPOAgent, PPOConfig
from src.rl.agents.networks import NetworkConfig, ActivationFunction, OptimizerType


class TestLearningRateScheduler:
    """Test cases for LearningRateScheduler."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.initial_lr = 0.001
        self.config = PPOTrainingConfig(
            lr_schedule="linear",
            lr_decay_steps=1000,
            min_lr_ratio=0.1
        )
        self.scheduler = LearningRateScheduler(self.initial_lr, self.config)
        
    def test_constant_schedule(self):
        """Test constant learning rate schedule."""
        config = PPOTrainingConfig(lr_schedule="constant")
        scheduler = LearningRateScheduler(self.initial_lr, config)
        
        for step in [0, 100, 1000, 10000]:
            lr = scheduler.get_lr(step)
            assert lr == self.initial_lr
            
    def test_linear_schedule(self):
        """Test linear learning rate decay."""
        # At step 0, should be initial LR
        lr_0 = self.scheduler.get_lr(0)
        assert lr_0 == self.initial_lr
        
        # At half decay steps, should be halfway between initial and min
        lr_half = self.scheduler.get_lr(500)
        expected_half = self.initial_lr * (1.0 - 0.5 * (1.0 - self.config.min_lr_ratio))
        assert abs(lr_half - expected_half) < 1e-6
        
        # At full decay steps, should be min LR
        lr_full = self.scheduler.get_lr(1000)
        expected_min = self.initial_lr * self.config.min_lr_ratio
        assert abs(lr_full - expected_min) < 1e-6
        
        # Beyond decay steps, should stay at min
        lr_beyond = self.scheduler.get_lr(2000)
        assert abs(lr_beyond - expected_min) < 1e-6
        
    def test_cosine_schedule(self):
        """Test cosine learning rate decay."""
        config = PPOTrainingConfig(
            lr_schedule="cosine",
            lr_decay_steps=1000,
            min_lr_ratio=0.1
        )
        scheduler = LearningRateScheduler(self.initial_lr, config)
        
        # At step 0, should be initial LR
        lr_0 = scheduler.get_lr(0)
        assert lr_0 == self.initial_lr
        
        # At half decay steps, should follow cosine curve
        lr_half = scheduler.get_lr(500)
        cosine_decay = 0.5 * (1 + math.cos(math.pi * 0.5))
        expected_half = self.initial_lr * (config.min_lr_ratio + (1.0 - config.min_lr_ratio) * cosine_decay)
        assert abs(lr_half - expected_half) < 1e-6
        
        # At full decay steps, should be min LR
        lr_full = scheduler.get_lr(1000)
        expected_min = self.initial_lr * config.min_lr_ratio
        assert abs(lr_full - expected_min) < 1e-6
        
    def test_exponential_schedule(self):
        """Test exponential learning rate decay."""
        config = PPOTrainingConfig(
            lr_schedule="exponential",
            lr_decay_rate=0.9,
            lr_decay_steps=100,
            min_lr_ratio=0.1
        )
        scheduler = LearningRateScheduler(self.initial_lr, config)
        
        # At step 0, should be initial LR
        lr_0 = scheduler.get_lr(0)
        assert lr_0 == self.initial_lr
        
        # At decay steps, should be decayed
        lr_decay = scheduler.get_lr(100)
        expected_decay = self.initial_lr * config.lr_decay_rate
        assert abs(lr_decay - expected_decay) < 1e-6
        
        # Should not go below minimum
        lr_min = scheduler.get_lr(10000)
        expected_min = self.initial_lr * config.min_lr_ratio
        assert lr_min >= expected_min - 1e-6
        
    def test_step_increment(self):
        """Test step counter increment."""
        initial_count = self.scheduler.step_count
        self.scheduler.step()
        assert self.scheduler.step_count == initial_count + 1


class TestClippingRatioScheduler:
    """Test cases for ClippingRatioScheduler."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.initial_clip = 0.2
        self.config = PPOTrainingConfig(
            clip_schedule="linear",
            lr_decay_steps=1000,
            min_clip_ratio=0.05
        )
        self.scheduler = ClippingRatioScheduler(self.initial_clip, self.config)
        
    def test_constant_schedule(self):
        """Test constant clipping ratio schedule."""
        config = PPOTrainingConfig(clip_schedule="constant")
        scheduler = ClippingRatioScheduler(self.initial_clip, config)
        
        for step in [0, 100, 1000, 10000]:
            clip_ratio = scheduler.get_clip_ratio(step)
            assert clip_ratio == self.initial_clip
            
    def test_linear_schedule(self):
        """Test linear clipping ratio decay."""
        # At step 0, should be initial clip ratio
        clip_0 = self.scheduler.get_clip_ratio(0)
        assert clip_0 == self.initial_clip
        
        # At full decay steps, should be closer to min
        clip_full = self.scheduler.get_clip_ratio(1000)
        assert clip_full < self.initial_clip
        assert clip_full >= self.config.min_clip_ratio
        
    def test_adaptive_schedule(self):
        """Test adaptive clipping ratio based on KL divergence."""
        config = PPOTrainingConfig(
            clip_schedule="adaptive",
            target_kl=0.01
        )
        scheduler = ClippingRatioScheduler(self.initial_clip, config)
        
        # High KL should reduce clipping ratio
        high_kl_clip = scheduler.get_clip_ratio(0, kl_divergence=0.05)
        assert high_kl_clip < self.initial_clip
        
        # Low KL should increase clipping ratio
        low_kl_clip = scheduler.get_clip_ratio(0, kl_divergence=0.001)
        assert low_kl_clip > self.initial_clip
        
        # No KL should return initial
        no_kl_clip = scheduler.get_clip_ratio(0, kl_divergence=None)
        assert no_kl_clip == self.initial_clip
        
    def test_step_increment(self):
        """Test step counter increment."""
        initial_count = self.scheduler.step_count
        self.scheduler.step()
        assert self.scheduler.step_count == initial_count + 1


class TestGAECalculator:
    """Test cases for GAECalculator."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.gamma = 0.99
        self.gae_lambda = 0.95
        self.calculator = GAECalculator(self.gamma, self.gae_lambda)
        
    def test_single_step_gae(self):
        """Test GAE calculation for single step."""
        rewards = torch.tensor([1.0])
        values = torch.tensor([0.5])
        dones = torch.tensor([True])
        
        advantages, returns = self.calculator.calculate_advantages_and_returns(
            rewards, values, dones
        )
        
        assert advantages.shape == (1,)
        assert returns.shape == (1,)
        
        # For terminal state, advantage should be reward - value
        expected_advantage = 1.0 - 0.5
        assert abs(advantages[0].item() - expected_advantage) < 1e-6
        
        # Return should be advantage + value
        expected_return = expected_advantage + 0.5
        assert abs(returns[0].item() - expected_return) < 1e-6
        
    def test_multi_step_gae(self):
        """Test GAE calculation for multiple steps."""
        rewards = torch.tensor([1.0, 0.5, 2.0])
        values = torch.tensor([0.3, 0.8, 1.2])
        dones = torch.tensor([False, False, True])
        
        advantages, returns = self.calculator.calculate_advantages_and_returns(
            rewards, values, dones
        )
        
        assert advantages.shape == (3,)
        assert returns.shape == (3,)
        
        # All values should be finite
        assert torch.isfinite(advantages).all()
        assert torch.isfinite(returns).all()
        
        # Returns should be advantages + values
        expected_returns = advantages + values
        assert torch.allclose(returns, expected_returns, atol=1e-6)
        
    def test_vectorized_vs_iterative(self):
        """Test that vectorized and iterative GAE give same results."""
        rewards = torch.tensor([1.0, 0.5, 2.0, -0.5, 1.5])
        values = torch.tensor([0.3, 0.8, 1.2, 0.9, 0.6])
        dones = torch.tensor([False, False, False, False, True])
        
        # Calculate using iterative method
        adv_iter, ret_iter = self.calculator.calculate_advantages_and_returns(
            rewards, values, dones
        )
        
        # Calculate using vectorized method
        adv_vec, ret_vec = self.calculator.calculate_advantages_and_returns_vectorized(
            rewards, values, dones
        )
        
        # Results should be very close
        assert torch.allclose(adv_iter, adv_vec, atol=1e-5)
        assert torch.allclose(ret_iter, ret_vec, atol=1e-5)
        
    def test_gae_properties(self):
        """Test mathematical properties of GAE."""
        rewards = torch.tensor([1.0, 0.5, 2.0])
        values = torch.tensor([0.3, 0.8, 1.2])
        dones = torch.tensor([False, False, True])
        
        advantages, returns = self.calculator.calculate_advantages_and_returns(
            rewards, values, dones
        )
        
        # Advantages should have reasonable magnitude
        assert torch.abs(advantages).max() < 100  # Sanity check
        
        # Returns should be positive for positive rewards and values
        # (This is a weak test but checks basic sanity)
        assert not torch.isnan(returns).any()
        assert not torch.isinf(returns).any()


class TestPPOTrainer:
    """Test cases for PPOTrainer."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.state_dim = 8
        self.action_dim = 3
        
        # Create PPO agent
        ppo_config = PPOConfig(
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
        self.agent = PPOAgent(self.state_dim, self.action_dim, ppo_config)
        
        # Create training config
        self.training_config = PPOTrainingConfig(
            gae_lambda=0.95,
            normalize_advantages=True,
            lr_schedule="constant",
            early_stopping=True,
            target_kl=0.01
        )
        
        self.trainer = PPOTrainer(self.agent, self.training_config)
        
    def test_initialization(self):
        """Test trainer initialization."""
        assert self.trainer.agent == self.agent
        assert self.trainer.config == self.training_config
        assert isinstance(self.trainer.lr_scheduler, LearningRateScheduler)
        assert isinstance(self.trainer.clip_scheduler, ClippingRatioScheduler)
        assert isinstance(self.trainer.gae_calculator, GAECalculator)
        assert self.trainer.training_step == 0
        
    def test_train_from_empty_trajectory(self):
        """Test training with empty trajectory buffer."""
        metrics = self.trainer.train_from_trajectory_buffer()
        
        assert metrics['policy_loss'] == 0.0
        assert metrics['value_loss'] == 0.0
        assert metrics['entropy'] == 0.0
        
    def test_train_from_trajectory_buffer(self):
        """Test training with trajectory data."""
        # Store some trajectory steps
        for i in range(5):
            state = np.random.randn(self.state_dim)
            action = i % self.action_dim
            reward = np.random.randn()
            value = np.random.randn()
            log_prob = -np.random.rand()
            
            self.agent.store_trajectory_step(state, action, reward, value, log_prob)
            
        metrics = self.trainer.train_from_trajectory_buffer()
        
        # Check that metrics are returned
        assert isinstance(metrics['policy_loss'], float)
        assert isinstance(metrics['value_loss'], float)
        assert isinstance(metrics['entropy'], float)
        assert isinstance(metrics['kl_divergence'], float)
        assert isinstance(metrics['learning_rate'], float)
        assert isinstance(metrics['clip_ratio'], float)
        
        # Check that trajectory buffer is cleared
        assert len(self.agent.trajectory_buffer) == 0
        
        # Check that training step is incremented
        assert self.trainer.training_step == 1
        
    def test_train_step_with_trajectory_data(self):
        """Test direct training step with trajectory data."""
        batch_size = 10
        
        # Create mock trajectory data
        trajectory_data = {
            'states': torch.randn(batch_size, self.state_dim),
            'actions': torch.randint(0, self.action_dim, (batch_size,)),
            'rewards': torch.randn(batch_size),
            'values': torch.randn(batch_size),
            'log_probs': -torch.rand(batch_size),  # Log probs should be negative
            'dones': torch.zeros(batch_size, dtype=torch.bool)
        }
        
        metrics = self.trainer.train_step(trajectory_data)
        
        # Check metrics
        assert isinstance(metrics['policy_loss'], float)
        assert isinstance(metrics['value_loss'], float)
        assert isinstance(metrics['entropy'], float)
        assert metrics['training_step'] == 1
        assert 'advantages_mean' in metrics
        assert 'advantages_std' in metrics
        assert 'returns_mean' in metrics
        assert 'returns_std' in metrics
        
    def test_advantage_normalization(self):
        """Test that advantages are properly normalized."""
        batch_size = 10
        
        # Create trajectory data with known rewards/values
        trajectory_data = {
            'states': torch.randn(batch_size, self.state_dim),
            'actions': torch.randint(0, self.action_dim, (batch_size,)),
            'rewards': torch.ones(batch_size) * 2.0,  # Constant rewards
            'values': torch.ones(batch_size) * 1.0,   # Constant values
            'log_probs': -torch.rand(batch_size),
            'dones': torch.zeros(batch_size, dtype=torch.bool)
        }
        
        # Enable advantage normalization
        self.trainer.config.normalize_advantages = True
        
        metrics = self.trainer.train_step(trajectory_data)
        
        # With normalization, advantages should have been normalized
        # (We can't directly check the advantages, but we can check that training completed)
        assert isinstance(metrics['advantages_mean'], float)
        assert isinstance(metrics['advantages_std'], float)
        
    def test_learning_rate_scheduling(self):
        """Test that learning rate is updated during training."""
        # Use linear decay schedule
        self.trainer.config.lr_schedule = "linear"
        self.trainer.config.lr_decay_steps = 10
        
        initial_lr = self.agent.policy_network.optimizer.param_groups[0]['lr']
        
        # Create dummy trajectory data
        batch_size = 5
        trajectory_data = {
            'states': torch.randn(batch_size, self.state_dim),
            'actions': torch.randint(0, self.action_dim, (batch_size,)),
            'rewards': torch.randn(batch_size),
            'values': torch.randn(batch_size),
            'log_probs': -torch.rand(batch_size),
            'dones': torch.zeros(batch_size, dtype=torch.bool)
        }
        
        # Train for several steps
        for _ in range(5):
            self.trainer.train_step(trajectory_data)
            
        # Learning rate should have changed
        final_lr = self.agent.policy_network.optimizer.param_groups[0]['lr']
        assert final_lr != initial_lr
        
    def test_early_stopping(self):
        """Test early stopping based on KL divergence."""
        # Enable early stopping with very low target KL
        self.trainer.config.early_stopping = True
        self.trainer.config.target_kl = 1e-6  # Very low threshold
        
        # Set high number of PPO epochs
        self.agent.config.ppo_epochs = 10
        
        batch_size = 5
        trajectory_data = {
            'states': torch.randn(batch_size, self.state_dim),
            'actions': torch.randint(0, self.action_dim, (batch_size,)),
            'rewards': torch.randn(batch_size),
            'values': torch.randn(batch_size),
            'log_probs': -torch.rand(batch_size),
            'dones': torch.zeros(batch_size, dtype=torch.bool)
        }
        
        metrics = self.trainer.train_step(trajectory_data)
        
        # Should have stopped early (fewer than 10 epochs)
        assert metrics['ppo_epochs'] < 10
        
    def test_get_training_stats(self):
        """Test getting training statistics."""
        # Initially should be empty
        stats = self.trainer.get_training_stats()
        assert stats == {}
        
        # After training, should have stats
        batch_size = 5
        trajectory_data = {
            'states': torch.randn(batch_size, self.state_dim),
            'actions': torch.randint(0, self.action_dim, (batch_size,)),
            'rewards': torch.randn(batch_size),
            'values': torch.randn(batch_size),
            'log_probs': -torch.rand(batch_size),
            'dones': torch.zeros(batch_size, dtype=torch.bool)
        }
        
        self.trainer.train_step(trajectory_data)
        
        stats = self.trainer.get_training_stats()
        assert 'total_training_steps' in stats
        assert 'avg_policy_loss' in stats
        assert 'avg_value_loss' in stats
        assert 'current_learning_rate' in stats
        assert stats['total_training_steps'] == 1
        
    def test_reset_training_state(self):
        """Test resetting training state."""
        # Train for a few steps
        batch_size = 5
        trajectory_data = {
            'states': torch.randn(batch_size, self.state_dim),
            'actions': torch.randint(0, self.action_dim, (batch_size,)),
            'rewards': torch.randn(batch_size),
            'values': torch.randn(batch_size),
            'log_probs': -torch.rand(batch_size),
            'dones': torch.zeros(batch_size, dtype=torch.bool)
        }
        
        for _ in range(3):
            self.trainer.train_step(trajectory_data)
            
        assert self.trainer.training_step == 3
        assert len(self.trainer.training_metrics) == 3
        
        # Reset state
        self.trainer.reset_training_state()
        
        assert self.trainer.training_step == 0
        assert len(self.trainer.training_metrics) == 0
        assert self.trainer.lr_scheduler.step_count == 0
        assert self.trainer.clip_scheduler.step_count == 0


if __name__ == "__main__":
    pytest.main([__file__])
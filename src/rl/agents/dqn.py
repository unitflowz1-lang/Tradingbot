"""
DQN Agent Implementation

This module will contain the DQN agent implementation with experience replay
and target networks for stable learning.

This is a placeholder file - implementation will be done in task 3.1.
"""

"""
Deep Q-Network (DQN) Agent Implementation

This module implements a DQN agent with experience replay, target networks,
and various DQN improvements like Double DQN and Dueling DQN.
"""

import numpy as np
import torch
import torch.nn as nn
import random
from collections import deque
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

from .base import RLAgent, AgentConfig, Experience
from .networks import NeuralNetwork, DuelingNetwork, NetworkConfig, ActivationFunction, OptimizerType


@dataclass
class DQNConfig(AgentConfig):
    """Configuration for DQN agent."""
    # DQN specific parameters (with defaults)
    min_memory_size: int = 1000
    double_dqn: bool = True
    dueling_dqn: bool = True
    prioritized_replay: bool = False
    noisy_networks: bool = False
    
    # Network configuration
    network_config: Optional[NetworkConfig] = None
    
    def __post_init__(self):
        """Initialize network configuration if not provided."""
        if self.network_config is None:
            self.network_config = NetworkConfig(
                hidden_layers=self.hidden_layers,
                activation=ActivationFunction.RELU,
                dropout_rate=0.1,
                batch_norm=True,
                optimizer=OptimizerType.ADAM,
                learning_rate=self.learning_rate,
                gradient_clip_norm=1.0
            )


class ExperienceBuffer:
    """
    Experience replay buffer for DQN.
    
    Stores and samples experiences for training with optional prioritization.
    """
    
    def __init__(self, capacity: int, prioritized: bool = False):
        """
        Initialize experience buffer.
        
        Args:
            capacity: Maximum number of experiences to store
            prioritized: Whether to use prioritized experience replay
        """
        self.capacity = capacity
        self.prioritized = prioritized
        self.buffer = deque(maxlen=capacity)
        
        if prioritized:
            self.priorities = deque(maxlen=capacity)
            self.alpha = 0.6  # Prioritization exponent
            self.beta = 0.4   # Importance sampling exponent
            self.beta_increment = 0.001
            self.epsilon = 1e-6  # Small constant to avoid zero priorities
            
    def push(self, experience: Experience, priority: Optional[float] = None) -> None:
        """Add experience to buffer."""
        self.buffer.append(experience)
        
        if self.prioritized:
            if priority is None:
                # If no priority given, use maximum priority
                max_priority = max(self.priorities) if self.priorities else 1.0
                priority = max_priority
            self.priorities.append(priority)
            
    def sample(self, batch_size: int) -> Tuple[List[Experience], Optional[np.ndarray], Optional[np.ndarray]]:
        """
        Sample batch of experiences.
        
        Returns:
            Tuple of (experiences, weights, indices) where weights and indices
            are None for uniform sampling or arrays for prioritized sampling
        """
        if self.prioritized:
            return self._sample_prioritized(batch_size)
        else:
            return self._sample_uniform(batch_size)
            
    def _sample_uniform(self, batch_size: int) -> Tuple[List[Experience], None, None]:
        """Sample uniformly from buffer."""
        experiences = random.sample(self.buffer, batch_size)
        return experiences, None, None
        
    def _sample_prioritized(self, batch_size: int) -> Tuple[List[Experience], np.ndarray, np.ndarray]:
        """Sample with prioritization."""
        priorities = np.array(self.priorities)
        probabilities = priorities ** self.alpha
        probabilities /= probabilities.sum()
        
        # Sample indices
        indices = np.random.choice(len(self.buffer), batch_size, p=probabilities)
        
        # Calculate importance sampling weights
        weights = (len(self.buffer) * probabilities[indices]) ** (-self.beta)
        weights /= weights.max()  # Normalize weights
        
        # Get experiences
        experiences = [self.buffer[i] for i in indices]
        
        # Update beta
        self.beta = min(1.0, self.beta + self.beta_increment)
        
        return experiences, weights, indices
        
    def update_priorities(self, indices: np.ndarray, priorities: np.ndarray) -> None:
        """Update priorities for prioritized replay."""
        if not self.prioritized:
            return
            
        for idx, priority in zip(indices, priorities):
            self.priorities[idx] = priority + self.epsilon
            
    def __len__(self) -> int:
        """Return buffer size."""
        return len(self.buffer)
        
    def is_ready(self, min_size: int) -> bool:
        """Check if buffer has enough experiences for training."""
        return len(self.buffer) >= min_size


class DQNAgent(RLAgent):
    """
    Deep Q-Network agent with experience replay and target networks.
    
    Implements DQN with various improvements including Double DQN, Dueling DQN,
    and optional prioritized experience replay.
    """
    
    def __init__(self, state_dim: int, action_dim: int, config: DQNConfig):
        """
        Initialize DQN agent.
        
        Args:
            state_dim: Dimension of state space
            action_dim: Number of actions
            config: DQN configuration
        """
        super().__init__(state_dim, action_dim, config)
        self.config = config
        
        # Initialize networks
        if config.dueling_dqn:
            self.q_network = DuelingNetwork(state_dim, action_dim, config.network_config)
            self.target_network = DuelingNetwork(state_dim, action_dim, config.network_config)
        else:
            self.q_network = NeuralNetwork(state_dim, action_dim, config.network_config)
            self.target_network = NeuralNetwork(state_dim, action_dim, config.network_config)
            
        # Copy weights to target network
        self.target_network.load_state_dict(self.q_network.state_dict())
        self.target_network.eval()
        
        # Experience buffer
        self.memory = ExperienceBuffer(
            capacity=config.memory_size,
            prioritized=config.prioritized_replay
        )
        
        # Training state
        self.epsilon = config.epsilon_start
        self.steps_done = 0
        self.update_count = 0
        
        # Device
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.q_network.to(self.device)
        self.target_network.to(self.device)
        
    def select_action(self, state: np.ndarray, training: bool = False) -> int:
        """
        Select action using epsilon-greedy policy.
        
        Args:
            state: Current state
            training: Whether in training mode
            
        Returns:
            Selected action
        """
        if training and random.random() < self.epsilon:
            # Random action for exploration
            return random.randrange(self.action_dim)
        else:
            # Greedy action
            with torch.no_grad():
                state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
                q_values = self.q_network(state_tensor)
                return q_values.argmax().item()
                
    def update(self, experiences: List[Experience]) -> Dict[str, float]:
        """
        Update Q-network using batch of experiences.
        
        Args:
            experiences: Batch of experiences
            
        Returns:
            Training metrics
        """
        if not self.memory.is_ready(self.config.min_memory_size):
            return {"loss": 0.0, "q_mean": 0.0}
            
        # Sample batch from memory
        batch_experiences, weights, indices = self.memory.sample(self.config.batch_size)
        
        # Convert to tensors
        states = torch.FloatTensor(np.array([e.state for e in batch_experiences])).to(self.device)
        actions = torch.LongTensor([e.action for e in batch_experiences]).to(self.device)
        rewards = torch.FloatTensor([e.reward for e in batch_experiences]).to(self.device)
        next_states = torch.FloatTensor(np.array([e.next_state for e in batch_experiences])).to(self.device)
        dones = torch.BoolTensor([bool(e.done) for e in batch_experiences]).to(self.device)
        
        # Current Q values
        current_q_values = self.q_network(states).gather(1, actions.unsqueeze(1))
        
        # Next Q values
        with torch.no_grad():
            if self.config.double_dqn:
                # Double DQN: use main network to select actions, target network to evaluate
                next_actions = self.q_network(next_states).argmax(1)
                next_q_values = self.target_network(next_states).gather(1, next_actions.unsqueeze(1))
            else:
                # Standard DQN: use target network for both selection and evaluation
                next_q_values = self.target_network(next_states).max(1)[0].unsqueeze(1)
                
            # Calculate target Q values
            target_q_values = rewards.unsqueeze(1) + (self.config.gamma * next_q_values * ~dones.unsqueeze(1))
            
        # Calculate loss
        if self.config.prioritized_replay and weights is not None:
            # Weighted loss for prioritized replay
            weights_tensor = torch.FloatTensor(weights).to(self.device)
            td_errors = target_q_values - current_q_values
            loss = (weights_tensor.unsqueeze(1) * td_errors.pow(2)).mean()
            
            # Update priorities
            priorities = td_errors.abs().detach().cpu().numpy().flatten()
            self.memory.update_priorities(indices, priorities)
        else:
            # Standard MSE loss
            loss = nn.MSELoss()(current_q_values, target_q_values)
            
        # Optimize
        self.q_network.optimizer.zero_grad()
        loss.backward()
        
        # Gradient clipping
        if self.config.network_config.use_gradient_clipping:
            torch.nn.utils.clip_grad_norm_(
                self.q_network.parameters(),
                self.config.network_config.gradient_clip_norm
            )
            
        self.q_network.optimizer.step()
        
        # Update target network
        self.update_count += 1
        if self.update_count % self.config.target_update_frequency == 0:
            self.target_network.load_state_dict(self.q_network.state_dict())
            
        # Decay epsilon
        self.decay_epsilon()
        
        # Return metrics
        return {
            "loss": loss.item(),
            "q_mean": current_q_values.mean().item(),
            "epsilon": self.epsilon,
            "update_count": self.update_count
        }
        
    def store_experience(self, experience: Experience) -> None:
        """Store experience in replay buffer."""
        self.memory.push(experience)
        
    def decay_epsilon(self) -> None:
        """Decay exploration rate."""
        self.epsilon = max(
            self.config.epsilon_end,
            self.epsilon * self.config.epsilon_decay
        )
        
    def save_model(self, filepath: str) -> None:
        """Save model checkpoint."""
        checkpoint = {
            'q_network_state_dict': self.q_network.state_dict(),
            'target_network_state_dict': self.target_network.state_dict(),
            'optimizer_state_dict': self.q_network.optimizer.state_dict(),
            'config': self.config,
            'epsilon': self.epsilon,
            'steps_done': self.steps_done,
            'update_count': self.update_count,
            'training_step': self.training_step,
            'episode_count': self.episode_count
        }
        torch.save(checkpoint, filepath)
        
    def load_model(self, filepath: str) -> None:
        """Load model checkpoint."""
        checkpoint = torch.load(filepath, map_location=self.device, weights_only=False)
        
        self.q_network.load_state_dict(checkpoint['q_network_state_dict'])
        self.target_network.load_state_dict(checkpoint['target_network_state_dict'])
        self.q_network.optimizer.load_state_dict(checkpoint['optimizer_state_dict'])
        
        self.epsilon = checkpoint.get('epsilon', self.config.epsilon_start)
        self.steps_done = checkpoint.get('steps_done', 0)
        self.update_count = checkpoint.get('update_count', 0)
        self.training_step = checkpoint.get('training_step', 0)
        self.episode_count = checkpoint.get('episode_count', 0)
        
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        base_info = {
            "type": "DQN",
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
            "epsilon": self.epsilon,
            "steps_done": self.steps_done,
            "update_count": self.update_count,
            "memory_size": len(self.memory),
            "double_dqn": self.config.double_dqn,
            "dueling_dqn": self.config.dueling_dqn,
            "prioritized_replay": self.config.prioritized_replay
        }
        
        # Add network info
        network_info = self.q_network.get_model_info()
        base_info.update(network_info)
        
        return base_info
        
    def reset_episode(self) -> None:
        """Reset agent state for new episode."""
        self.increment_episode()
        
        # Reset noisy networks if used
        if self.config.noisy_networks:
            if hasattr(self.q_network, 'reset_noise'):
                self.q_network.reset_noise()
            if hasattr(self.target_network, 'reset_noise'):
                self.target_network.reset_noise()
                
    def set_training_mode(self, training: bool) -> None:
        """Set training mode."""
        super().set_training_mode(training)
        if training:
            self.q_network.train()
        else:
            self.q_network.eval()
            
    def get_q_values(self, state: np.ndarray) -> np.ndarray:
        """Get Q-values for given state."""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.q_network(state_tensor)
            return q_values.cpu().numpy().flatten()
            
    def get_action_probabilities(self, state: np.ndarray, temperature: float = 1.0) -> np.ndarray:
        """Get action probabilities using softmax over Q-values."""
        q_values = self.get_q_values(state)
        
        # Apply temperature scaling
        if temperature > 0:
            q_values = q_values / temperature
            
        # Softmax
        exp_q = np.exp(q_values - np.max(q_values))  # Numerical stability
        probabilities = exp_q / np.sum(exp_q)
        
        return probabilities
        
    def update_target_network(self) -> None:
        """Manually update target network."""
        self.target_network.load_state_dict(self.q_network.state_dict())
        
    def get_memory_stats(self) -> Dict[str, Any]:
        """Get experience buffer statistics."""
        return {
            "memory_size": len(self.memory),
            "memory_capacity": self.memory.capacity,
            "memory_usage": len(self.memory) / self.memory.capacity,
            "is_ready": self.memory.is_ready(self.config.min_memory_size),
            "prioritized": self.memory.prioritized
        }
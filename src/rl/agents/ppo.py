"""
Proximal Policy Optimization (PPO) Agent Implementation

This module implements a PPO agent with separate policy and value networks,
clipped surrogate objective, and entropy regularization for stable learning.
"""

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from collections import deque

from .base import RLAgent, AgentConfig, Experience
from .networks import NeuralNetwork, NetworkConfig, ActivationFunction, OptimizerType


@dataclass
class PPOConfig(AgentConfig):
    """Configuration for PPO agent."""
    # PPO specific parameters
    clip_ratio: float = 0.2
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    max_grad_norm: float = 0.5
    ppo_epochs: int = 4
    gae_lambda: float = 0.95
    normalize_advantages: bool = True
    
    # Learning rate scheduling
    lr_schedule: str = "constant"  # "constant", "linear", "cosine"
    lr_decay_steps: int = 1000000
    
    # Early stopping
    target_kl: float = 0.01
    early_stopping: bool = True
    
    # Network configurations
    policy_network_config: Optional[NetworkConfig] = None
    value_network_config: Optional[NetworkConfig] = None
    
    def __post_init__(self):
        """Initialize network configurations if not provided."""
        if self.policy_network_config is None:
            self.policy_network_config = NetworkConfig(
                hidden_layers=self.hidden_layers,
                activation=ActivationFunction.TANH,
                dropout_rate=0.0,
                batch_norm=False,
                optimizer=OptimizerType.ADAM,
                learning_rate=self.learning_rate,
                gradient_clip_norm=self.max_grad_norm
            )
            
        if self.value_network_config is None:
            self.value_network_config = NetworkConfig(
                hidden_layers=self.hidden_layers,
                activation=ActivationFunction.TANH,
                dropout_rate=0.0,
                batch_norm=False,
                optimizer=OptimizerType.ADAM,
                learning_rate=self.learning_rate,
                gradient_clip_norm=self.max_grad_norm
            )


class PolicyNetwork(nn.Module):
    """
    Policy network for PPO that outputs action probabilities.
    
    Uses a neural network backbone with a softmax output layer
    for discrete action spaces.
    """
    
    def __init__(self, state_dim: int, action_dim: int, config: NetworkConfig):
        """
        Initialize policy network.
        
        Args:
            state_dim: Dimension of state space
            action_dim: Number of discrete actions
            config: Network configuration
        """
        super(PolicyNetwork, self).__init__()
        
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config
        
        # Build backbone network (without final layer)
        self.backbone = self._build_backbone()
        
        # Policy head
        final_hidden_dim = (config.hidden_layers[-1] 
                           if config.hidden_layers else state_dim)
        self.policy_head = nn.Linear(final_hidden_dim, action_dim)
        
        # Initialize weights
        self._initialize_weights()
        
        # Setup optimizer
        self.optimizer = self._create_optimizer()
        
    def _build_backbone(self) -> nn.ModuleList:
        """Build backbone network layers."""
        layers = nn.ModuleList()
        prev_dim = self.state_dim
        
        for hidden_dim in self.config.hidden_layers:
            # Linear layer
            layers.append(nn.Linear(prev_dim, hidden_dim))
            
            # Batch normalization (if enabled)
            if self.config.batch_norm:
                layers.append(nn.BatchNorm1d(hidden_dim))
            
            # Activation function
            layers.append(self._get_activation_function())
            
            # Dropout (if enabled)
            if self.config.dropout_rate > 0:
                layers.append(nn.Dropout(self.config.dropout_rate))
                
            prev_dim = hidden_dim
            
        return layers
        
    def _get_activation_function(self) -> nn.Module:
        """Get activation function based on configuration."""
        if self.config.activation == ActivationFunction.RELU:
            return nn.ReLU()
        elif self.config.activation == ActivationFunction.TANH:
            return nn.Tanh()
        elif self.config.activation == ActivationFunction.LEAKY_RELU:
            return nn.LeakyReLU(0.01)
        elif self.config.activation == ActivationFunction.ELU:
            return nn.ELU()
        elif self.config.activation == ActivationFunction.SWISH:
            return nn.SiLU()
        elif self.config.activation == ActivationFunction.GELU:
            return nn.GELU()
        else:
            return nn.Tanh()  # Default for policy networks
            
    def _initialize_weights(self) -> None:
        """Initialize network weights."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                # Xavier initialization for hidden layers
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
                    
        # Special initialization for policy head (smaller weights)
        nn.init.xavier_uniform_(self.policy_head.weight, gain=0.01)
        nn.init.zeros_(self.policy_head.bias)
        
    def _create_optimizer(self) -> torch.optim.Optimizer:
        """Create optimizer based on configuration."""
        if self.config.optimizer == OptimizerType.ADAM:
            return torch.optim.Adam(
                self.parameters(),
                lr=self.config.learning_rate,
                eps=1e-5
            )
        elif self.config.optimizer == OptimizerType.ADAMW:
            return torch.optim.AdamW(
                self.parameters(),
                lr=self.config.learning_rate,
                weight_decay=self.config.weight_decay
            )
        else:
            return torch.optim.Adam(self.parameters(), 
                                  lr=self.config.learning_rate)
            
    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """
        Forward pass through policy network.
        
        Args:
            state: Input state tensor
            
        Returns:
            Action logits (before softmax)
        """
        x = state
        
        # Pass through backbone
        for layer in self.backbone:
            x = layer(x)
            
        # Policy head
        logits = self.policy_head(x)
        
        return logits
        
    def get_action_probabilities(self, state: torch.Tensor) -> torch.Tensor:
        """
        Get action probabilities using softmax.
        
        Args:
            state: Input state tensor
            
        Returns:
            Action probabilities
        """
        logits = self.forward(state)
        return F.softmax(logits, dim=-1)
        
    def get_log_probabilities(self, state: torch.Tensor) -> torch.Tensor:
        """
        Get log action probabilities.
        
        Args:
            state: Input state tensor
            
        Returns:
            Log action probabilities
        """
        logits = self.forward(state)
        return F.log_softmax(logits, dim=-1)


class ValueNetwork(nn.Module):
    """
    Value network for PPO that estimates state values.
    
    Uses a neural network to approximate the value function V(s).
    """
    
    def __init__(self, state_dim: int, config: NetworkConfig):
        """
        Initialize value network.
        
        Args:
            state_dim: Dimension of state space
            config: Network configuration
        """
        super(ValueNetwork, self).__init__()
        
        self.state_dim = state_dim
        self.config = config
        
        # Build backbone network
        self.backbone = self._build_backbone()
        
        # Value head
        final_hidden_dim = (config.hidden_layers[-1] 
                           if config.hidden_layers else state_dim)
        self.value_head = nn.Linear(final_hidden_dim, 1)
        
        # Initialize weights
        self._initialize_weights()
        
        # Setup optimizer
        self.optimizer = self._create_optimizer()
        
    def _build_backbone(self) -> nn.ModuleList:
        """Build backbone network layers."""
        layers = nn.ModuleList()
        prev_dim = self.state_dim
        
        for hidden_dim in self.config.hidden_layers:
            # Linear layer
            layers.append(nn.Linear(prev_dim, hidden_dim))
            
            # Batch normalization (if enabled)
            if self.config.batch_norm:
                layers.append(nn.BatchNorm1d(hidden_dim))
            
            # Activation function
            layers.append(self._get_activation_function())
            
            # Dropout (if enabled)
            if self.config.dropout_rate > 0:
                layers.append(nn.Dropout(self.config.dropout_rate))
                
            prev_dim = hidden_dim
            
        return layers
        
    def _get_activation_function(self) -> nn.Module:
        """Get activation function based on configuration."""
        if self.config.activation == ActivationFunction.RELU:
            return nn.ReLU()
        elif self.config.activation == ActivationFunction.TANH:
            return nn.Tanh()
        elif self.config.activation == ActivationFunction.LEAKY_RELU:
            return nn.LeakyReLU(0.01)
        elif self.config.activation == ActivationFunction.ELU:
            return nn.ELU()
        elif self.config.activation == ActivationFunction.SWISH:
            return nn.SiLU()
        elif self.config.activation == ActivationFunction.GELU:
            return nn.GELU()
        else:
            return nn.Tanh()  # Default for value networks
            
    def _initialize_weights(self) -> None:
        """Initialize network weights."""
        for module in self.modules():
            if isinstance(module, nn.Linear):
                # Xavier initialization
                nn.init.xavier_uniform_(module.weight)
                if module.bias is not None:
                    nn.init.zeros_(module.bias)
                    
    def _create_optimizer(self) -> torch.optim.Optimizer:
        """Create optimizer based on configuration."""
        if self.config.optimizer == OptimizerType.ADAM:
            return torch.optim.Adam(
                self.parameters(),
                lr=self.config.learning_rate,
                eps=1e-5
            )
        elif self.config.optimizer == OptimizerType.ADAMW:
            return torch.optim.AdamW(
                self.parameters(),
                lr=self.config.learning_rate,
                weight_decay=self.config.weight_decay
            )
        else:
            return torch.optim.Adam(self.parameters(), 
                                  lr=self.config.learning_rate)
            
    def forward(self, state: torch.Tensor) -> torch.Tensor:
        """
        Forward pass through value network.
        
        Args:
            state: Input state tensor
            
        Returns:
            State value estimate
        """
        x = state
        
        # Pass through backbone
        for layer in self.backbone:
            x = layer(x)
            
        # Value head
        value = self.value_head(x)
        
        return value.squeeze(-1)  # Remove last dimension


class PPOAgent(RLAgent):
    """
    Proximal Policy Optimization agent with clipped surrogate objective.
    
    Implements PPO with separate policy and value networks, entropy
    regularization, and generalized advantage estimation.
    """
    
    def __init__(self, state_dim: int, action_dim: int, config: PPOConfig):
        """
        Initialize PPO agent.
        
        Args:
            state_dim: Dimension of state space
            action_dim: Number of discrete actions
            config: PPO configuration
        """
        super().__init__(state_dim, action_dim, config)
        self.config = config
        
        # Initialize networks
        self.policy_network = PolicyNetwork(
            state_dim, action_dim, config.policy_network_config
        )
        self.value_network = ValueNetwork(
            state_dim, config.value_network_config
        )
        
        # Experience buffer for trajectory collection
        self.trajectory_buffer = []
        
        # Training state
        self.update_count = 0
        
        # Device
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.policy_network.to(self.device)
        self.value_network.to(self.device)
        
    def select_action(self, state: np.ndarray, training: bool = False) -> int:
        """
        Select action using current policy.
        
        Args:
            state: Current state
            training: Whether in training mode (affects exploration)
            
        Returns:
            Selected action
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            
            if training:
                # Sample from policy distribution
                action_probs = self.policy_network.get_action_probabilities(state_tensor)
                action_dist = torch.distributions.Categorical(action_probs)
                action = action_dist.sample()
            else:
                # Use greedy action (highest probability)
                action_probs = self.policy_network.get_action_probabilities(state_tensor)
                action = action_probs.argmax()
                
            return action.item()
            
    def get_action_and_value(self, state: np.ndarray) -> Tuple[int, float, float]:
        """
        Get action, value, and log probability for training.
        
        Args:
            state: Current state
            
        Returns:
            Tuple of (action, value, log_prob)
        """
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            
            # Get action probabilities and sample
            action_probs = self.policy_network.get_action_probabilities(state_tensor)
            action_dist = torch.distributions.Categorical(action_probs)
            action = action_dist.sample()
            log_prob = action_dist.log_prob(action)
            
            # Get state value
            value = self.value_network(state_tensor)
            
            return action.item(), value.item(), log_prob.item()
            
    def store_trajectory_step(self, state: np.ndarray, action: int, 
                            reward: float, value: float, log_prob: float) -> None:
        """
        Store a single step of trajectory for PPO training.
        
        Args:
            state: Current state
            action: Action taken
            reward: Reward received
            value: Value estimate
            log_prob: Log probability of action
        """
        self.trajectory_buffer.append({
            'state': state,
            'action': action,
            'reward': reward,
            'value': value,
            'log_prob': log_prob
        })
        
    def update(self, experiences: List[Experience]) -> Dict[str, float]:
        """
        Update PPO agent using collected trajectory.
        
        Args:
            experiences: List of experiences (not used directly in PPO)
            
        Returns:
            Training metrics
        """
        if len(self.trajectory_buffer) == 0:
            return {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}
            
        # Convert trajectory to tensors
        states = torch.FloatTensor(np.array([step['state'] for step in self.trajectory_buffer])).to(self.device)
        actions = torch.LongTensor([step['action'] for step in self.trajectory_buffer]).to(self.device)
        rewards = torch.FloatTensor([step['reward'] for step in self.trajectory_buffer]).to(self.device)
        old_values = torch.FloatTensor([step['value'] for step in self.trajectory_buffer]).to(self.device)
        old_log_probs = torch.FloatTensor([step['log_prob'] for step in self.trajectory_buffer]).to(self.device)
        
        # Calculate advantages and returns
        advantages, returns = self._calculate_gae(rewards, old_values)
        
        # Normalize advantages
        if self.config.normalize_advantages:
            advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)
            
        # Store old policy for KL divergence calculation
        with torch.no_grad():
            old_action_probs = self.policy_network.get_action_probabilities(states)
            
        # PPO training loop
        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        
        for epoch in range(self.config.ppo_epochs):
            # Forward pass through networks
            current_log_probs = self.policy_network.get_log_probabilities(states)
            current_log_probs = current_log_probs.gather(1, actions.unsqueeze(1)).squeeze(1)
            current_values = self.value_network(states)
            
            # Calculate policy loss
            ratio = torch.exp(current_log_probs - old_log_probs)
            surr1 = ratio * advantages
            surr2 = torch.clamp(ratio, 1 - self.config.clip_ratio, 1 + self.config.clip_ratio) * advantages
            policy_loss = -torch.min(surr1, surr2).mean()
            
            # Calculate value loss
            value_loss = F.mse_loss(current_values, returns)
            
            # Calculate entropy for exploration
            action_probs = self.policy_network.get_action_probabilities(states)
            entropy = -(action_probs * torch.log(action_probs + 1e-8)).sum(dim=-1).mean()
            
            # Total loss
            total_loss = (policy_loss + 
                         self.config.value_coef * value_loss - 
                         self.config.entropy_coef * entropy)
            
            # Update policy network
            self.policy_network.optimizer.zero_grad()
            policy_loss_with_entropy = policy_loss - self.config.entropy_coef * entropy
            policy_loss_with_entropy.backward(retain_graph=True)
            torch.nn.utils.clip_grad_norm_(self.policy_network.parameters(), self.config.max_grad_norm)
            self.policy_network.optimizer.step()
            
            # Update value network
            self.value_network.optimizer.zero_grad()
            value_loss.backward()
            torch.nn.utils.clip_grad_norm_(self.value_network.parameters(), self.config.max_grad_norm)
            self.value_network.optimizer.step()
            
            # Accumulate losses
            total_policy_loss += policy_loss.item()
            total_value_loss += value_loss.item()
            total_entropy += entropy.item()
            
            # Early stopping based on KL divergence
            if self.config.early_stopping:
                with torch.no_grad():
                    current_action_probs = self.policy_network.get_action_probabilities(states)
                    kl_div = torch.sum(old_action_probs * torch.log(old_action_probs / (current_action_probs + 1e-8)), dim=-1).mean()
                    
                    if kl_div > self.config.target_kl:
                        break
                        
        # Clear trajectory buffer
        self.trajectory_buffer.clear()
        
        # Update counters
        self.update_count += 1
        self.increment_training_step()
        
        return {
            "policy_loss": total_policy_loss / (epoch + 1),
            "value_loss": total_value_loss / (epoch + 1),
            "entropy": total_entropy / (epoch + 1),
            "update_count": self.update_count,
            "ppo_epochs": epoch + 1
        }
        
    def _calculate_gae(self, rewards: torch.Tensor, 
                      values: torch.Tensor) -> Tuple[torch.Tensor, torch.Tensor]:
        """
        Calculate Generalized Advantage Estimation (GAE).
        
        Args:
            rewards: Tensor of rewards
            values: Tensor of value estimates
            
        Returns:
            Tuple of (advantages, returns)
        """
        advantages = torch.zeros_like(rewards)
        returns = torch.zeros_like(rewards)
        
        # Calculate advantages using GAE
        gae = 0
        for t in reversed(range(len(rewards))):
            if t == len(rewards) - 1:
                next_value = 0  # Terminal state
            else:
                next_value = values[t + 1]
                
            delta = rewards[t] + self.config.gamma * next_value - values[t]
            gae = delta + self.config.gamma * self.config.gae_lambda * gae
            advantages[t] = gae
            
        # Calculate returns
        returns = advantages + values
        
        return advantages, returns
        
    def save_model(self, filepath: str) -> None:
        """Save model checkpoint."""
        checkpoint = {
            'policy_network_state_dict': self.policy_network.state_dict(),
            'value_network_state_dict': self.value_network.state_dict(),
            'policy_optimizer_state_dict': self.policy_network.optimizer.state_dict(),
            'value_optimizer_state_dict': self.value_network.optimizer.state_dict(),
            'config': self.config,
            'update_count': self.update_count,
            'training_step': self.training_step,
            'episode_count': self.episode_count
        }
        torch.save(checkpoint, filepath)
        
    def load_model(self, filepath: str) -> None:
        """Load model checkpoint."""
        checkpoint = torch.load(filepath, map_location=self.device, weights_only=False)
        
        self.policy_network.load_state_dict(checkpoint['policy_network_state_dict'])
        self.value_network.load_state_dict(checkpoint['value_network_state_dict'])
        self.policy_network.optimizer.load_state_dict(checkpoint['policy_optimizer_state_dict'])
        self.value_network.optimizer.load_state_dict(checkpoint['value_optimizer_state_dict'])
        
        self.update_count = checkpoint.get('update_count', 0)
        self.training_step = checkpoint.get('training_step', 0)
        self.episode_count = checkpoint.get('episode_count', 0)
        
    def get_model_info(self) -> Dict[str, Any]:
        """Get model information."""
        policy_params = sum(p.numel() for p in self.policy_network.parameters())
        value_params = sum(p.numel() for p in self.value_network.parameters())
        
        return {
            "type": "PPO",
            "state_dim": self.state_dim,
            "action_dim": self.action_dim,
            "policy_parameters": policy_params,
            "value_parameters": value_params,
            "total_parameters": policy_params + value_params,
            "update_count": self.update_count,
            "training_step": self.training_step,
            "episode_count": self.episode_count,
            "clip_ratio": self.config.clip_ratio,
            "entropy_coef": self.config.entropy_coef,
            "value_coef": self.config.value_coef
        }
        
    def reset_episode(self) -> None:
        """Reset agent state for new episode."""
        self.increment_episode()
        # PPO doesn't need episode-specific resets
        
    def set_training_mode(self, training: bool) -> None:
        """Set training mode."""
        super().set_training_mode(training)
        if training:
            self.policy_network.train()
            self.value_network.train()
        else:
            self.policy_network.eval()
            self.value_network.eval()
            
    def get_action_probabilities(self, state: np.ndarray) -> np.ndarray:
        """Get action probabilities for given state."""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            action_probs = self.policy_network.get_action_probabilities(state_tensor)
            return action_probs.cpu().numpy().flatten()
            
    def get_state_value(self, state: np.ndarray) -> float:
        """Get state value estimate."""
        with torch.no_grad():
            state_tensor = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            value = self.value_network(state_tensor)
            return value.item()
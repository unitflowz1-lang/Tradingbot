"""
Base RL Agent Interface

This module defines the abstract base class for reinforcement learning agents
that learn trading strategies through environment interaction.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Union
import numpy as np
from dataclasses import dataclass
from datetime import datetime


@dataclass
class Experience:
    """Single experience tuple for RL training"""
    state: np.ndarray
    action: int
    reward: float
    next_state: np.ndarray
    done: bool
    timestamp: datetime


@dataclass
class AgentConfig:
    """Base configuration for RL agents"""
    learning_rate: float
    batch_size: int
    gamma: float  # Discount factor
    epsilon_start: float
    epsilon_end: float
    epsilon_decay: float
    memory_size: int
    target_update_frequency: int
    hidden_layers: List[int]
    activation: str
    optimizer: str


class RLAgent(ABC):
    """
    Abstract base class for reinforcement learning agents.
    
    Defines the interface that all RL agents must implement for
    action selection, learning, and model persistence.
    """
    
    def __init__(self, state_dim: int, action_dim: int, config: AgentConfig):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.config = config
        self.training_step = 0
        self.episode_count = 0
        
    @abstractmethod
    def select_action(self, state: np.ndarray, training: bool = False) -> int:
        """
        Select action based on current state.
        
        Args:
            state: Current environment state
            training: Whether agent is in training mode
            
        Returns:
            Selected action index
        """
        pass
        
    @abstractmethod
    def update(self, experiences: List[Experience]) -> Dict[str, float]:
        """
        Update agent parameters based on experiences.
        
        Args:
            experiences: List of experience tuples
            
        Returns:
            Dictionary of training metrics (loss, etc.)
        """
        pass
        
    @abstractmethod
    def save_model(self, filepath: str) -> None:
        """
        Save trained model to disk.
        
        Args:
            filepath: Path to save model
        """
        pass
        
    @abstractmethod
    def load_model(self, filepath: str) -> None:
        """
        Load trained model from disk.
        
        Args:
            filepath: Path to load model from
        """
        pass
        
    @abstractmethod
    def get_model_info(self) -> Dict[str, Any]:
        """
        Get information about the current model.
        
        Returns:
            Dictionary containing model metadata
        """
        pass
        
    def set_training_mode(self, training: bool) -> None:
        """
        Set agent training mode.
        
        Args:
            training: Whether to enable training mode
        """
        self.training = training
        
    def get_epsilon(self) -> float:
        """
        Get current exploration rate (epsilon).
        
        Returns:
            Current epsilon value
        """
        if hasattr(self, 'epsilon'):
            return self.epsilon
        return 0.0
        
    def decay_epsilon(self) -> None:
        """Decay exploration rate according to schedule."""
        if hasattr(self, 'epsilon'):
            self.epsilon = max(
                self.config.epsilon_end,
                self.epsilon * self.config.epsilon_decay
            )
            
    def increment_episode(self) -> None:
        """Increment episode counter."""
        self.episode_count += 1
        
    def increment_training_step(self) -> None:
        """Increment training step counter."""
        self.training_step += 1
        
    @property
    def is_ready_for_training(self) -> bool:
        """Check if agent has enough experiences for training."""
        return True  # Override in subclasses if needed
        
    @abstractmethod
    def reset_episode(self) -> None:
        """Reset agent state for new episode."""
        pass
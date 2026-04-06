"""
Base RL Configuration Classes

This module defines the core configuration structures for the RL trading system.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path


@dataclass
class TrainingConfig:
    """Configuration for RL training process"""
    num_episodes: int = 1000
    max_steps_per_episode: int = 1000
    batch_size: int = 32
    learning_rate: float = 0.001
    gamma: float = 0.99
    epsilon_start: float = 1.0
    epsilon_end: float = 0.01
    epsilon_decay: float = 0.995
    target_update_frequency: int = 100
    checkpoint_frequency: int = 100
    validation_frequency: int = 50
    early_stopping_patience: int = 20
    gradient_clip_norm: float = 1.0


@dataclass
class NetworkConfig:
    """Configuration for neural networks"""
    hidden_layers: List[int] = field(default_factory=lambda: [256, 128, 64])
    activation: str = "relu"
    dropout_rate: float = 0.1
    batch_norm: bool = True
    optimizer: str = "adam"
    weight_decay: float = 1e-4
    learning_rate_schedule: str = "cosine"


@dataclass
class EnvironmentConfig:
    """Configuration for trading environment"""
    lookback_window: int = 20
    transaction_cost: float = 0.0001
    max_position_size: float = 1.0
    initial_balance: float = 10000.0
    normalization_method: str = "minmax"
    reward_function: str = "sharpe_adjusted"
    state_features: List[str] = field(default_factory=lambda: [
        "price_features", "technical_indicators", "portfolio_state"
    ])
    action_space_type: str = "discrete"
    num_actions: int = 8


@dataclass
class DQNConfig:
    """Configuration specific to DQN agent"""
    memory_size: int = 100000
    min_memory_size: int = 1000
    double_dqn: bool = True
    dueling_dqn: bool = True
    prioritized_replay: bool = False
    noisy_networks: bool = False


@dataclass
class PPOConfig:
    """Configuration specific to PPO agent"""
    clip_ratio: float = 0.2
    entropy_coef: float = 0.01
    value_coef: float = 0.5
    gae_lambda: float = 0.95
    ppo_epochs: int = 4
    mini_batch_size: int = 64
    normalize_advantages: bool = True


@dataclass
class LoggingConfig:
    """Configuration for logging and monitoring"""
    log_level: str = "INFO"
    log_dir: str = "logs/rl"
    tensorboard_dir: str = "logs/tensorboard"
    model_save_dir: str = "models/rl"
    checkpoint_dir: str = "checkpoints/rl"
    log_training_metrics: bool = True
    log_inference_metrics: bool = True
    save_training_plots: bool = True


@dataclass
class RLConfig:
    """Main RL system configuration"""
    training: TrainingConfig = field(default_factory=TrainingConfig)
    network: NetworkConfig = field(default_factory=NetworkConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    dqn: DQNConfig = field(default_factory=DQNConfig)
    ppo: PPOConfig = field(default_factory=PPOConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    # System settings
    device: str = "auto"  # "cpu", "cuda", "auto"
    num_workers: int = 4
    seed: Optional[int] = None
    debug_mode: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "training": self.training.__dict__,
            "network": self.network.__dict__,
            "environment": self.environment.__dict__,
            "dqn": self.dqn.__dict__,
            "ppo": self.ppo.__dict__,
            "logging": self.logging.__dict__,
            "device": self.device,
            "num_workers": self.num_workers,
            "seed": self.seed,
            "debug_mode": self.debug_mode
        }
        
    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> 'RLConfig':
        """Create configuration from dictionary."""
        config = cls()
        
        if "training" in config_dict:
            config.training = TrainingConfig(**config_dict["training"])
        if "network" in config_dict:
            config.network = NetworkConfig(**config_dict["network"])
        if "environment" in config_dict:
            config.environment = EnvironmentConfig(**config_dict["environment"])
        if "dqn" in config_dict:
            config.dqn = DQNConfig(**config_dict["dqn"])
        if "ppo" in config_dict:
            config.ppo = PPOConfig(**config_dict["ppo"])
        if "logging" in config_dict:
            config.logging = LoggingConfig(**config_dict["logging"])
            
        # System settings
        config.device = config_dict.get("device", "auto")
        config.num_workers = config_dict.get("num_workers", 4)
        config.seed = config_dict.get("seed")
        config.debug_mode = config_dict.get("debug_mode", False)
        
        return config
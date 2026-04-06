"""
Training Configuration Management

This module provides configuration management for RL training with hyperparameter
optimization, configuration validation, and experiment tracking.
"""

import json
from typing import Dict, Any, List, Optional, Union, Type

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path
from datetime import datetime
import logging
from abc import ABC, abstractmethod

from .agent_trainer import TrainingConfig
from ..agents.base import AgentConfig
from ..agents.dqn import DQNConfig
from ..agents.ppo import PPOConfig


@dataclass
class HyperparameterRange:
    """Defines a range for hyperparameter optimization."""
    min_value: float
    max_value: float
    log_scale: bool = False
    discrete_values: Optional[List[Any]] = None
    
    def sample(self) -> Any:
        """Sample a value from the range."""
        import random
        
        if self.discrete_values:
            return random.choice(self.discrete_values)
            
        if self.log_scale:
            import math
            log_min = math.log(self.min_value)
            log_max = math.log(self.max_value)
            return math.exp(random.uniform(log_min, log_max))
        else:
            return random.uniform(self.min_value, self.max_value)


@dataclass
class ExperimentConfig:
    """Configuration for experiment tracking and management."""
    name: str
    description: str = ""
    tags: List[str] = field(default_factory=list)
    
    # Experiment metadata
    author: str = ""
    version: str = "1.0.0"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Tracking configuration
    track_metrics: List[str] = field(default_factory=lambda: [
        "total_reward", "episode_length", "average_reward", "loss"
    ])
    save_models: bool = True
    save_logs: bool = True
    
    # Comparison baselines
    baseline_configs: List[str] = field(default_factory=list)
    
    # Resource requirements
    estimated_runtime_hours: Optional[float] = None
    gpu_required: bool = False
    memory_gb: Optional[float] = None


class ConfigValidator:
    """Validates training configurations."""
    
    @staticmethod
    def validate_training_config(config: TrainingConfig) -> List[str]:
        """
        Validate training configuration.
        
        Args:
            config: Training configuration to validate
            
        Returns:
            List of validation errors
        """
        errors = []
        
        # Basic validation
        if config.total_episodes <= 0:
            errors.append("total_episodes must be positive")
            
        if config.max_steps_per_episode <= 0:
            errors.append("max_steps_per_episode must be positive")
            
        if config.evaluation_frequency <= 0:
            errors.append("evaluation_frequency must be positive")
            
        if config.save_frequency <= 0:
            errors.append("save_frequency must be positive")
            
        # Early stopping validation
        if config.early_stopping_patience < 0:
            errors.append("early_stopping_patience must be non-negative")
            
        if config.early_stopping_threshold < 0:
            errors.append("early_stopping_threshold must be non-negative")
            
        # Resource validation
        if config.num_workers < 1:
            errors.append("num_workers must be at least 1")
            
        # Directory validation
        if not config.checkpoint_dir:
            errors.append("checkpoint_dir cannot be empty")
            
        return errors
        
    @staticmethod
    def validate_agent_config(config: AgentConfig) -> List[str]:
        """
        Validate agent configuration.
        
        Args:
            config: Agent configuration to validate
            
        Returns:
            List of validation errors
        """
        errors = []
        
        # Basic validation
        if config.learning_rate <= 0:
            errors.append("learning_rate must be positive")
            
        if config.batch_size <= 0:
            errors.append("batch_size must be positive")
            
        if not (0 <= config.gamma <= 1):
            errors.append("gamma must be between 0 and 1")
            
        # DQN specific validation
        if isinstance(config, DQNConfig):
            if not (0 <= config.epsilon_start <= 1):
                errors.append("epsilon_start must be between 0 and 1")
            if not (0 <= config.epsilon_end <= 1):
                errors.append("epsilon_end must be between 0 and 1")
            if config.epsilon_start < config.epsilon_end:
                errors.append("epsilon_start should be >= epsilon_end")
            if config.memory_size <= 0:
                errors.append("memory_size must be positive")
                
        # PPO specific validation
        if isinstance(config, PPOConfig):
            if not (0 <= config.clip_ratio <= 1):
                errors.append("clip_ratio must be between 0 and 1")
            if config.entropy_coef < 0:
                errors.append("entropy_coef must be non-negative")
            if config.value_coef < 0:
                errors.append("value_coef must be non-negative")
                
        return errors


class ConfigManager:
    """
    Manages training configurations with support for hyperparameter optimization
    and experiment tracking.
    """
    
    def __init__(self, config_dir: str = "configs"):
        """
        Initialize configuration manager.
        
        Args:
            config_dir: Directory to store configurations
        """
        self.config_dir = Path(config_dir)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        # Configuration registry
        self.registered_configs: Dict[str, Dict[str, Any]] = {}
        
    def register_config(self, name: str, config: Union[TrainingConfig, AgentConfig, ExperimentConfig]) -> None:
        """
        Register a configuration.
        
        Args:
            name: Configuration name
            config: Configuration object
        """
        self.registered_configs[name] = {
            'config': config,
            'type': type(config).__name__,
            'registered_at': datetime.now().isoformat()
        }
        
        self.logger.info(f"Registered configuration: {name}")
        
    def get_config(self, name: str) -> Optional[Any]:
        """
        Get registered configuration.
        
        Args:
            name: Configuration name
            
        Returns:
            Configuration object or None
        """
        if name in self.registered_configs:
            return self.registered_configs[name]['config']
        return None
        
    def list_configs(self) -> List[str]:
        """List all registered configuration names."""
        return list(self.registered_configs.keys())
        
    def save_config(self, config: Any, filepath: str, format: str = "json") -> None:
        """
        Save configuration to file.
        
        Args:
            config: Configuration object
            filepath: Path to save configuration
            format: File format ("json" or "yaml")
        """
        config_dict = asdict(config) if hasattr(config, '__dataclass_fields__') else config
        
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        if format.lower() == "json":
            with open(filepath, 'w') as f:
                json.dump(config_dict, f, indent=2)
        elif format.lower() == "yaml":
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML is required for YAML format. Install with: pip install pyyaml")
            with open(filepath, 'w') as f:
                yaml.dump(config_dict, f, default_flow_style=False)
        else:
            raise ValueError(f"Unsupported format: {format}")
            
        self.logger.info(f"Saved configuration to {filepath}")
        
    def load_config(self, filepath: str, config_class: Type) -> Any:
        """
        Load configuration from file.
        
        Args:
            filepath: Path to configuration file
            config_class: Configuration class to instantiate
            
        Returns:
            Configuration object
        """
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"Configuration file not found: {filepath}")
            
        if filepath.suffix.lower() == ".json":
            with open(filepath, 'r') as f:
                config_dict = json.load(f)
        elif filepath.suffix.lower() in [".yaml", ".yml"]:
            if not YAML_AVAILABLE:
                raise ImportError("PyYAML is required for YAML format. Install with: pip install pyyaml")
            with open(filepath, 'r') as f:
                config_dict = yaml.safe_load(f)
        else:
            raise ValueError(f"Unsupported file format: {filepath.suffix}")
            
        # Create configuration object
        config = config_class(**config_dict)
        
        self.logger.info(f"Loaded configuration from {filepath}")
        return config
        
    def validate_config(self, config: Any) -> List[str]:
        """
        Validate configuration.
        
        Args:
            config: Configuration to validate
            
        Returns:
            List of validation errors
        """
        if isinstance(config, TrainingConfig):
            return ConfigValidator.validate_training_config(config)
        elif isinstance(config, AgentConfig):
            return ConfigValidator.validate_agent_config(config)
        else:
            return []  # No validation for unknown types
            
    def create_hyperparameter_search_space(self, base_config: Any, search_ranges: Dict[str, HyperparameterRange]) -> Dict[str, Any]:
        """
        Create hyperparameter search space.
        
        Args:
            base_config: Base configuration
            search_ranges: Dictionary mapping parameter names to ranges
            
        Returns:
            Search space configuration
        """
        search_space = {}
        
        for param_name, param_range in search_ranges.items():
            if param_range.discrete_values:
                search_space[param_name] = {
                    'type': 'categorical',
                    'choices': param_range.discrete_values
                }
            elif param_range.log_scale:
                search_space[param_name] = {
                    'type': 'loguniform',
                    'low': param_range.min_value,
                    'high': param_range.max_value
                }
            else:
                search_space[param_name] = {
                    'type': 'uniform',
                    'low': param_range.min_value,
                    'high': param_range.max_value
                }
                
        return search_space
        
    def sample_hyperparameters(self, base_config: Any, search_ranges: Dict[str, HyperparameterRange]) -> Any:
        """
        Sample hyperparameters from search ranges.
        
        Args:
            base_config: Base configuration
            search_ranges: Dictionary mapping parameter names to ranges
            
        Returns:
            Configuration with sampled hyperparameters
        """
        # Convert to dictionary
        config_dict = asdict(base_config) if hasattr(base_config, '__dataclass_fields__') else base_config
        
        # Sample new values
        for param_name, param_range in search_ranges.items():
            if param_name in config_dict:
                config_dict[param_name] = param_range.sample()
                
        # Create new configuration object
        config_class = type(base_config)
        return config_class(**config_dict)
        
    def create_experiment_suite(self, 
                              base_config: Any,
                              variations: Dict[str, List[Any]],
                              experiment_name: str) -> List[Dict[str, Any]]:
        """
        Create experiment suite with configuration variations.
        
        Args:
            base_config: Base configuration
            variations: Dictionary mapping parameter names to lists of values
            experiment_name: Base experiment name
            
        Returns:
            List of experiment configurations
        """
        import itertools
        
        # Get all combinations
        param_names = list(variations.keys())
        param_values = list(variations.values())
        combinations = list(itertools.product(*param_values))
        
        experiments = []
        
        for i, combination in enumerate(combinations):
            # Create configuration dictionary
            config_dict = asdict(base_config) if hasattr(base_config, '__dataclass_fields__') else base_config
            
            # Apply variations
            for param_name, value in zip(param_names, combination):
                config_dict[param_name] = value
                
            # Create experiment configuration
            experiment_config = {
                'name': f"{experiment_name}_variant_{i+1}",
                'config': type(base_config)(**config_dict),
                'variations': dict(zip(param_names, combination)),
                'experiment_id': i + 1
            }
            
            experiments.append(experiment_config)
            
        self.logger.info(f"Created experiment suite with {len(experiments)} configurations")
        return experiments
        
    def save_experiment_suite(self, experiments: List[Dict[str, Any]], filepath: str) -> None:
        """
        Save experiment suite to file.
        
        Args:
            experiments: List of experiment configurations
            filepath: Path to save experiments
        """
        # Convert to serializable format
        serializable_experiments = []
        
        for exp in experiments:
            serializable_exp = {
                'name': exp['name'],
                'config': asdict(exp['config']) if hasattr(exp['config'], '__dataclass_fields__') else exp['config'],
                'variations': exp['variations'],
                'experiment_id': exp['experiment_id']
            }
            serializable_experiments.append(serializable_exp)
            
        # Save to file
        with open(filepath, 'w') as f:
            json.dump({
                'experiments': serializable_experiments,
                'created_at': datetime.now().isoformat(),
                'total_experiments': len(experiments)
            }, f, indent=2)
            
        self.logger.info(f"Saved experiment suite to {filepath}")
        
    def load_experiment_suite(self, filepath: str, config_class: Type) -> List[Dict[str, Any]]:
        """
        Load experiment suite from file.
        
        Args:
            filepath: Path to experiment suite file
            config_class: Configuration class to instantiate
            
        Returns:
            List of experiment configurations
        """
        with open(filepath, 'r') as f:
            data = json.load(f)
            
        experiments = []
        
        for exp_data in data['experiments']:
            experiment = {
                'name': exp_data['name'],
                'config': config_class(**exp_data['config']),
                'variations': exp_data['variations'],
                'experiment_id': exp_data['experiment_id']
            }
            experiments.append(experiment)
            
        self.logger.info(f"Loaded experiment suite with {len(experiments)} configurations")
        return experiments
        
    def get_default_configs(self) -> Dict[str, Any]:
        """Get default configurations for common use cases."""
        return {
            'dqn_training': TrainingConfig(
                total_episodes=1000,
                max_steps_per_episode=1000,
                evaluation_frequency=100,
                save_frequency=200,
                early_stopping_patience=50,
                experiment_name="dqn_default"
            ),
            'ppo_training': TrainingConfig(
                total_episodes=2000,
                max_steps_per_episode=1000,
                evaluation_frequency=200,
                save_frequency=400,
                early_stopping_patience=100,
                experiment_name="ppo_default"
            ),
            'dqn_agent': DQNConfig(
                learning_rate=1e-3,
                batch_size=32,
                gamma=0.99,
                epsilon_start=1.0,
                epsilon_end=0.01,
                epsilon_decay=0.995,
                memory_size=10000,
                target_update_frequency=100,
                hidden_layers=[256, 256],
                activation="relu",
                optimizer="adam"
            ),
            'ppo_agent': PPOConfig(
                learning_rate=3e-4,
                batch_size=64,
                gamma=0.99,
                epsilon_start=1.0,  # Not used in PPO but required by base class
                epsilon_end=0.01,
                epsilon_decay=0.995,
                memory_size=10000,  # Not used in PPO but required by base class
                target_update_frequency=100,  # Not used in PPO but required by base class
                hidden_layers=[64, 64],
                activation="tanh",
                optimizer="adam",
                clip_ratio=0.2,
                entropy_coef=0.01,
                value_coef=0.5
            )
        }
        
    def get_hyperparameter_ranges(self) -> Dict[str, Dict[str, HyperparameterRange]]:
        """Get common hyperparameter search ranges."""
        return {
            'dqn': {
                'learning_rate': HyperparameterRange(1e-5, 1e-2, log_scale=True),
                'batch_size': HyperparameterRange(0, 0, discrete_values=[16, 32, 64, 128]),
                'epsilon_decay': HyperparameterRange(0.99, 0.999),
                'gamma': HyperparameterRange(0.9, 0.999),
                'target_update_frequency': HyperparameterRange(0, 0, discrete_values=[50, 100, 200, 500])
            },
            'ppo': {
                'learning_rate': HyperparameterRange(1e-5, 1e-2, log_scale=True),
                'batch_size': HyperparameterRange(0, 0, discrete_values=[32, 64, 128, 256]),
                'clip_ratio': HyperparameterRange(0.1, 0.3),
                'entropy_coef': HyperparameterRange(0.001, 0.1, log_scale=True),
                'value_coef': HyperparameterRange(0.1, 1.0),
                'gamma': HyperparameterRange(0.9, 0.999)
            },
            'training': {
                'early_stopping_patience': HyperparameterRange(0, 0, discrete_values=[20, 50, 100, 200]),
                'evaluation_frequency': HyperparameterRange(0, 0, discrete_values=[50, 100, 200, 500])
            }
        }
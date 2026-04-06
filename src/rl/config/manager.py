"""
Configuration Manager for RL System

This module provides centralized configuration management with support for
loading from files, environment variables, and runtime updates.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, Union
import logging

from .base import RLConfig


class ConfigManager:
    """
    Centralized configuration manager for RL system.
    
    Supports loading configurations from JSON files, environment variables,
    and provides runtime configuration updates with validation.
    """
    
    def __init__(self, config_path: Optional[Union[str, Path]] = None):
        self.config_path = Path(config_path) if config_path else None
        self.config = RLConfig()
        self.logger = logging.getLogger(__name__)
        
        # Load configuration if path provided
        if self.config_path and self.config_path.exists():
            self.load_from_file(self.config_path)
            
        # Override with environment variables
        self._load_from_env()
        
    def load_from_file(self, config_path: Union[str, Path]) -> None:
        """
        Load configuration from JSON file.
        
        Args:
            config_path: Path to configuration file
        """
        config_path = Path(config_path)
        
        if not config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {config_path}")
            
        try:
            with open(config_path, 'r') as f:
                config_dict = json.load(f)
                
            self.config = RLConfig.from_dict(config_dict)
            self.config_path = config_path
            self.logger.info(f"Loaded configuration from {config_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to load configuration from {config_path}: {e}")
            raise
            
    def save_to_file(self, config_path: Optional[Union[str, Path]] = None) -> None:
        """
        Save current configuration to JSON file.
        
        Args:
            config_path: Path to save configuration (uses current path if None)
        """
        if config_path:
            save_path = Path(config_path)
        elif self.config_path:
            save_path = self.config_path
        else:
            raise ValueError("No configuration path specified")
            
        # Create directory if it doesn't exist
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            with open(save_path, 'w') as f:
                json.dump(self.config.to_dict(), f, indent=2)
                
            self.logger.info(f"Saved configuration to {save_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save configuration to {save_path}: {e}")
            raise
            
    def _load_from_env(self) -> None:
        """Load configuration overrides from environment variables."""
        env_mappings = {
            'RL_LEARNING_RATE': ('training', 'learning_rate', float),
            'RL_BATCH_SIZE': ('training', 'batch_size', int),
            'RL_NUM_EPISODES': ('training', 'num_episodes', int),
            'RL_EPSILON_START': ('training', 'epsilon_start', float),
            'RL_EPSILON_END': ('training', 'epsilon_end', float),
            'RL_DEVICE': ('device', None, str),
            'RL_NUM_WORKERS': ('num_workers', None, int),
            'RL_DEBUG_MODE': ('debug_mode', None, lambda x: x.lower() == 'true'),
            'RL_LOG_LEVEL': ('logging', 'log_level', str),
            'RL_LOG_DIR': ('logging', 'log_dir', str),
        }
        
        for env_var, (section, key, converter) in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                try:
                    converted_value = converter(value)
                    if key is None:
                        # Direct attribute
                        setattr(self.config, section, converted_value)
                    else:
                        # Nested attribute
                        section_obj = getattr(self.config, section)
                        setattr(section_obj, key, converted_value)
                        
                    self.logger.debug(f"Set {env_var} = {converted_value}")
                    
                except (ValueError, TypeError) as e:
                    self.logger.warning(f"Invalid value for {env_var}: {value} ({e})")
                    
    def update_config(self, updates: Dict[str, Any]) -> None:
        """
        Update configuration with new values.
        
        Args:
            updates: Dictionary of configuration updates
        """
        try:
            # Create new config with updates
            current_dict = self.config.to_dict()
            self._deep_update(current_dict, updates)
            
            # Validate by creating new config
            new_config = RLConfig.from_dict(current_dict)
            self.config = new_config
            
            self.logger.info("Configuration updated successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to update configuration: {e}")
            raise
            
    def _deep_update(self, base_dict: Dict[str, Any], updates: Dict[str, Any]) -> None:
        """Recursively update nested dictionary."""
        for key, value in updates.items():
            if key in base_dict and isinstance(base_dict[key], dict) and isinstance(value, dict):
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value
                
    def get_config(self) -> RLConfig:
        """Get current configuration."""
        return self.config
        
    def get_training_config(self):
        """Get training configuration."""
        return self.config.training
        
    def get_network_config(self):
        """Get network configuration."""
        return self.config.network
        
    def get_environment_config(self):
        """Get environment configuration."""
        return self.config.environment
        
    def get_dqn_config(self):
        """Get DQN-specific configuration."""
        return self.config.dqn
        
    def get_ppo_config(self):
        """Get PPO-specific configuration."""
        return self.config.ppo
        
    def get_logging_config(self):
        """Get logging configuration."""
        return self.config.logging
        
    def validate_config(self) -> bool:
        """
        Validate current configuration.
        
        Returns:
            True if configuration is valid
        """
        try:
            # Basic validation checks
            assert self.config.training.learning_rate > 0
            assert self.config.training.batch_size > 0
            assert self.config.training.num_episodes > 0
            assert 0 <= self.config.training.epsilon_start <= 1
            assert 0 <= self.config.training.epsilon_end <= 1
            assert self.config.training.gamma > 0
            assert len(self.config.network.hidden_layers) > 0
            assert self.config.environment.initial_balance > 0
            
            return True
            
        except AssertionError as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False
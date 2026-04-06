"""
Hyperparameter Configuration for RL System

This module defines hyperparameter search spaces and optimization
configurations for different RL algorithms.
"""

from typing import Dict, Any, List, Tuple
from dataclasses import dataclass


@dataclass
class HyperparameterRange:
    """Defines a hyperparameter search range."""
    name: str
    type: str  # 'float', 'int', 'categorical'
    low: float = None
    high: float = None
    choices: List[Any] = None
    log: bool = False  # Use log scale for continuous parameters


class HyperparameterConfig:
    """
    Configuration for hyperparameter optimization.
    
    Defines search spaces for different RL algorithms and provides
    utilities for hyperparameter optimization frameworks.
    """
    
    # DQN hyperparameter search space
    DQN_SEARCH_SPACE = [
        HyperparameterRange('learning_rate', 'float', 1e-5, 1e-2, log=True),
        HyperparameterRange('batch_size', 'categorical', choices=[16, 32, 64, 128]),
        HyperparameterRange('gamma', 'float', 0.9, 0.999),
        HyperparameterRange('epsilon_decay', 'float', 0.99, 0.9999),
        HyperparameterRange('target_update_frequency', 'int', 50, 500),
        HyperparameterRange('memory_size', 'categorical', choices=[50000, 100000, 200000]),
        HyperparameterRange('hidden_layers', 'categorical', choices=[
            [128, 64], [256, 128], [256, 128, 64], [512, 256, 128]
        ]),
        HyperparameterRange('dropout_rate', 'float', 0.0, 0.3),
        HyperparameterRange('weight_decay', 'float', 1e-6, 1e-3, log=True)
    ]
    
    # PPO hyperparameter search space
    PPO_SEARCH_SPACE = [
        HyperparameterRange('learning_rate', 'float', 1e-5, 1e-2, log=True),
        HyperparameterRange('batch_size', 'categorical', choices=[32, 64, 128, 256]),
        HyperparameterRange('gamma', 'float', 0.9, 0.999),
        HyperparameterRange('clip_ratio', 'float', 0.1, 0.3),
        HyperparameterRange('entropy_coef', 'float', 0.001, 0.1, log=True),
        HyperparameterRange('value_coef', 'float', 0.1, 1.0),
        HyperparameterRange('gae_lambda', 'float', 0.9, 0.99),
        HyperparameterRange('ppo_epochs', 'int', 3, 10),
        HyperparameterRange('mini_batch_size', 'categorical', choices=[16, 32, 64]),
        HyperparameterRange('hidden_layers', 'categorical', choices=[
            [128, 64], [256, 128], [256, 128, 64], [512, 256, 128]
        ])
    ]
    
    # Environment hyperparameter search space
    ENVIRONMENT_SEARCH_SPACE = [
        HyperparameterRange('lookback_window', 'int', 10, 50),
        HyperparameterRange('transaction_cost', 'float', 0.0001, 0.001, log=True),
        HyperparameterRange('max_position_size', 'float', 0.5, 2.0),
        HyperparameterRange('reward_function', 'categorical', choices=[
            'simple_return', 'sharpe_adjusted', 'risk_adjusted', 'multi_objective'
        ]),
        HyperparameterRange('normalization_method', 'categorical', choices=[
            'minmax', 'zscore', 'robust'
        ])
    ]
    
    @classmethod
    def get_search_space(cls, algorithm: str) -> List[HyperparameterRange]:
        """
        Get hyperparameter search space for algorithm.
        
        Args:
            algorithm: Algorithm name ('dqn', 'ppo', 'environment')
            
        Returns:
            List of hyperparameter ranges
        """
        if algorithm.lower() == 'dqn':
            return cls.DQN_SEARCH_SPACE
        elif algorithm.lower() == 'ppo':
            return cls.PPO_SEARCH_SPACE
        elif algorithm.lower() == 'environment':
            return cls.ENVIRONMENT_SEARCH_SPACE
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")
            
    @classmethod
    def get_default_params(cls, algorithm: str) -> Dict[str, Any]:
        """
        Get default hyperparameters for algorithm.
        
        Args:
            algorithm: Algorithm name
            
        Returns:
            Dictionary of default parameters
        """
        defaults = {
            'dqn': {
                'learning_rate': 0.001,
                'batch_size': 32,
                'gamma': 0.99,
                'epsilon_decay': 0.995,
                'target_update_frequency': 100,
                'memory_size': 100000,
                'hidden_layers': [256, 128, 64],
                'dropout_rate': 0.1,
                'weight_decay': 1e-4
            },
            'ppo': {
                'learning_rate': 0.0003,
                'batch_size': 64,
                'gamma': 0.99,
                'clip_ratio': 0.2,
                'entropy_coef': 0.01,
                'value_coef': 0.5,
                'gae_lambda': 0.95,
                'ppo_epochs': 4,
                'mini_batch_size': 32,
                'hidden_layers': [256, 128, 64]
            },
            'environment': {
                'lookback_window': 20,
                'transaction_cost': 0.0001,
                'max_position_size': 1.0,
                'reward_function': 'sharpe_adjusted',
                'normalization_method': 'minmax'
            }
        }
        
        return defaults.get(algorithm.lower(), {})
        
    @classmethod
    def validate_params(cls, algorithm: str, params: Dict[str, Any]) -> bool:
        """
        Validate hyperparameters for algorithm.
        
        Args:
            algorithm: Algorithm name
            params: Parameters to validate
            
        Returns:
            True if parameters are valid
        """
        search_space = cls.get_search_space(algorithm)
        
        for param_range in search_space:
            param_name = param_range.name
            
            if param_name not in params:
                continue
                
            value = params[param_name]
            
            if param_range.type == 'float':
                if not isinstance(value, (int, float)):
                    return False
                if param_range.low is not None and value < param_range.low:
                    return False
                if param_range.high is not None and value > param_range.high:
                    return False
                    
            elif param_range.type == 'int':
                if not isinstance(value, int):
                    return False
                if param_range.low is not None and value < param_range.low:
                    return False
                if param_range.high is not None and value > param_range.high:
                    return False
                    
            elif param_range.type == 'categorical':
                if value not in param_range.choices:
                    return False
                    
        return True
        
    @classmethod
    def suggest_params(cls, algorithm: str, trial) -> Dict[str, Any]:
        """
        Suggest hyperparameters for Optuna trial.
        
        Args:
            algorithm: Algorithm name
            trial: Optuna trial object
            
        Returns:
            Dictionary of suggested parameters
        """
        search_space = cls.get_search_space(algorithm)
        params = {}
        
        for param_range in search_space:
            name = param_range.name
            
            if param_range.type == 'float':
                if param_range.log:
                    params[name] = trial.suggest_loguniform(
                        name, param_range.low, param_range.high
                    )
                else:
                    params[name] = trial.suggest_uniform(
                        name, param_range.low, param_range.high
                    )
                    
            elif param_range.type == 'int':
                params[name] = trial.suggest_int(
                    name, int(param_range.low), int(param_range.high)
                )
                
            elif param_range.type == 'categorical':
                params[name] = trial.suggest_categorical(name, param_range.choices)
                
        return params
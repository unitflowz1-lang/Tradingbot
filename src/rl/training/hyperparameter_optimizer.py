"""
Hyperparameter Optimization Framework

This module implements automated hyperparameter optimization for RL agents using
Optuna, with support for parallel search, resource management, and performance tracking.
"""

import numpy as np
import json
import time
import logging
from typing import Dict, Any, List, Optional, Callable, Union, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor, as_completed
import threading
from abc import ABC, abstractmethod

try:
    import optuna
    from optuna.samplers import TPESampler, RandomSampler, CmaEsSampler
    from optuna.pruners import MedianPruner, HyperbandPruner
    OPTUNA_AVAILABLE = True
except ImportError:
    OPTUNA_AVAILABLE = False

from .agent_trainer import AgentTrainer, TrainingConfig, TrainingMetrics
from .config_manager import ConfigManager, HyperparameterRange
from ..agents.base import RLAgent, AgentConfig
from ..agents.dqn import DQNAgent, DQNConfig
from ..agents.ppo import PPOAgent, PPOConfig


@dataclass
class OptimizationConfig:
    """Configuration for hyperparameter optimization."""
    # Study configuration
    study_name: str
    direction: str = "maximize"  # "maximize" or "minimize"
    n_trials: int = 100
    timeout: Optional[float] = None  # Timeout in seconds
    
    # Sampling and pruning
    sampler: str = "tpe"  # "tpe", "random", "cmaes"
    pruner: str = "median"  # "median", "hyperband", "none"
    
    # Parallel execution
    n_jobs: int = 1
    use_multiprocessing: bool = False
    
    # Resource management
    max_memory_per_trial: float = 4.0  # GB
    max_time_per_trial: float = 3600.0  # seconds
    
    # Early stopping
    early_stopping_rounds: int = 10
    min_trials_for_pruning: int = 5
    
    # Storage and persistence
    storage_url: Optional[str] = None  # For distributed optimization
    load_if_exists: bool = True
    
    # Logging and monitoring
    log_level: str = "INFO"
    save_intermediate_results: bool = True
    plot_optimization_history: bool = True


@dataclass
class TrialResult:
    """Result of a single optimization trial."""
    trial_number: int
    value: float
    params: Dict[str, Any]
    state: str  # "COMPLETE", "PRUNED", "FAIL"
    
    # Timing information
    start_time: datetime
    end_time: datetime
    duration: float
    
    # Training metrics
    training_metrics: List[TrainingMetrics]
    best_episode_reward: float
    convergence_episode: Optional[int]
    
    # Resource usage
    memory_usage: Optional[float] = None
    cpu_usage: Optional[float] = None
    
    # Additional metadata
    user_attrs: Dict[str, Any] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.user_attrs is None:
            self.user_attrs = {}


class ObjectiveFunction(ABC):
    """Abstract base class for optimization objective functions."""
    
    @abstractmethod
    def __call__(self, trial, agent_factory: Callable, environment_factory: Callable) -> float:
        """
        Evaluate objective function for a trial.
        
        Args:
            trial: Optuna trial object
            agent_factory: Factory function to create agent
            environment_factory: Factory function to create environment
            
        Returns:
            Objective value to optimize
        """
        pass
    
    @abstractmethod
    def suggest_hyperparameters(self, trial) -> Dict[str, Any]:
        """
        Suggest hyperparameters for the trial.
        
        Args:
            trial: Optuna trial object
            
        Returns:
            Dictionary of suggested hyperparameters
        """
        pass


class RLObjectiveFunction(ObjectiveFunction):
    """Objective function for RL agent optimization."""
    
    def __init__(self, 
                 base_training_config: TrainingConfig,
                 base_agent_config: AgentConfig,
                 agent_type: str = "dqn",
                 metric: str = "mean_reward",
                 evaluation_episodes: int = 10):
        """
        Initialize RL objective function.
        
        Args:
            base_training_config: Base training configuration
            base_agent_config: Base agent configuration
            agent_type: Type of agent ("dqn" or "ppo")
            metric: Metric to optimize ("mean_reward", "final_reward", "convergence_speed")
            evaluation_episodes: Number of episodes for evaluation
        """
        self.base_training_config = base_training_config
        self.base_agent_config = base_agent_config
        self.agent_type = agent_type.lower()
        self.metric = metric
        self.evaluation_episodes = evaluation_episodes
        
        self.logger = logging.getLogger(__name__)
        
    def __call__(self, trial, agent_factory: Callable, environment_factory: Callable) -> float:
        """Evaluate objective function for a trial."""
        try:
            # Suggest hyperparameters
            suggested_params = self.suggest_hyperparameters(trial)
            
            # Create modified configurations
            training_config = self._create_training_config(suggested_params)
            agent_config = self._create_agent_config(suggested_params)
            
            # Create agent and environment
            environment = environment_factory()
            agent = agent_factory(agent_config)
            
            # Create trainer
            trainer = AgentTrainer(agent, environment, training_config)
            
            # Add pruning callback
            pruning_callback = OptunaPruningCallback(trial, self.metric)
            trainer.add_callback(pruning_callback)
            
            # Run training
            training_history = trainer.train()
            
            # Calculate objective value
            objective_value = self._calculate_objective_value(training_history, trainer)
            
            # Store additional information
            trial.set_user_attr("training_episodes", len(training_history))
            trial.set_user_attr("convergence_episode", trainer._find_convergence_episode())
            trial.set_user_attr("best_reward", max(m.total_reward for m in training_history))
            
            return objective_value
            
        except Exception as e:
            self.logger.error(f"Trial {trial.number} failed: {e}")
            raise optuna.TrialPruned()
            
    def suggest_hyperparameters(self, trial) -> Dict[str, Any]:
        """Suggest hyperparameters for the trial."""
        params = {}
        
        # Common hyperparameters
        params['learning_rate'] = trial.suggest_float('learning_rate', 1e-5, 1e-2, log=True)
        params['batch_size'] = trial.suggest_categorical('batch_size', [16, 32, 64, 128, 256])
        params['gamma'] = trial.suggest_float('gamma', 0.9, 0.999)
        
        # Training hyperparameters
        params['total_episodes'] = trial.suggest_int('total_episodes', 500, 2000)
        params['early_stopping_patience'] = trial.suggest_int('early_stopping_patience', 20, 100)
        
        # Agent-specific hyperparameters
        if self.agent_type == "dqn":
            params['epsilon_decay'] = trial.suggest_float('epsilon_decay', 0.99, 0.999)
            params['target_update_frequency'] = trial.suggest_categorical(
                'target_update_frequency', [50, 100, 200, 500]
            )
            params['memory_size'] = trial.suggest_categorical(
                'memory_size', [5000, 10000, 20000, 50000]
            )
            
        elif self.agent_type == "ppo":
            params['clip_ratio'] = trial.suggest_float('clip_ratio', 0.1, 0.3)
            params['entropy_coef'] = trial.suggest_float('entropy_coef', 0.001, 0.1, log=True)
            params['value_coef'] = trial.suggest_float('value_coef', 0.1, 1.0)
            params['ppo_epochs'] = trial.suggest_int('ppo_epochs', 3, 10)
            
        # Network architecture
        n_layers = trial.suggest_int('n_layers', 2, 4)
        layer_sizes = []
        for i in range(n_layers):
            size = trial.suggest_categorical(f'layer_{i}_size', [32, 64, 128, 256, 512])
            layer_sizes.append(size)
        params['hidden_layers'] = layer_sizes
        
        params['activation'] = trial.suggest_categorical('activation', ['relu', 'tanh', 'leaky_relu'])
        params['optimizer'] = trial.suggest_categorical('optimizer', ['adam', 'rmsprop', 'sgd'])
        
        return params
        
    def _create_training_config(self, params: Dict[str, Any]) -> TrainingConfig:
        """Create training configuration from parameters."""
        config_dict = asdict(self.base_training_config)
        
        # Update with suggested parameters
        if 'total_episodes' in params:
            config_dict['total_episodes'] = params['total_episodes']
        if 'early_stopping_patience' in params:
            config_dict['early_stopping_patience'] = params['early_stopping_patience']
            
        return TrainingConfig(**config_dict)
        
    def _create_agent_config(self, params: Dict[str, Any]) -> AgentConfig:
        """Create agent configuration from parameters."""
        config_dict = asdict(self.base_agent_config)
        
        # Update with suggested parameters
        for key, value in params.items():
            if key in config_dict:
                config_dict[key] = value
                
        # Create appropriate config type
        if self.agent_type == "dqn":
            return DQNConfig(**config_dict)
        elif self.agent_type == "ppo":
            return PPOConfig(**config_dict)
        else:
            return AgentConfig(**config_dict)
            
    def _calculate_objective_value(self, training_history: List[TrainingMetrics], trainer: AgentTrainer) -> float:
        """Calculate objective value from training history."""
        if not training_history:
            return float('-inf')
            
        rewards = [m.total_reward for m in training_history]
        
        if self.metric == "mean_reward":
            # Use mean of last 20% of episodes
            last_episodes = max(1, len(rewards) // 5)
            return np.mean(rewards[-last_episodes:])
            
        elif self.metric == "final_reward":
            return rewards[-1]
            
        elif self.metric == "best_reward":
            return max(rewards)
            
        elif self.metric == "convergence_speed":
            # Reward faster convergence
            convergence_episode = trainer._find_convergence_episode()
            if convergence_episode is not None:
                # Higher score for faster convergence
                speed_score = 1.0 - (convergence_episode / len(rewards))
                final_performance = np.mean(rewards[-10:])
                return speed_score * final_performance
            else:
                return np.mean(rewards[-10:]) * 0.5  # Penalty for not converging
                
        elif self.metric == "sample_efficiency":
            # Reward achieving good performance with fewer samples
            final_performance = np.mean(rewards[-10:])
            efficiency_bonus = 1.0 - (len(rewards) / self.base_training_config.total_episodes)
            return final_performance * (1.0 + efficiency_bonus)
            
        else:
            return np.mean(rewards)


class OptunaPruningCallback:
    """Callback for Optuna pruning during training."""
    
    def __init__(self, trial, metric: str = "mean_reward"):
        """
        Initialize pruning callback.
        
        Args:
            trial: Optuna trial object
            metric: Metric to use for pruning decisions
        """
        self.trial = trial
        self.metric = metric
        
    def on_training_start(self, trainer): pass
    def on_training_end(self, trainer): pass
    def on_episode_start(self, trainer, episode): pass
    def on_evaluation_start(self, trainer, episode): pass
    def on_evaluation_end(self, trainer, episode, eval_metrics): pass
    
    def on_episode_end(self, trainer, episode, metrics):
        """Check for pruning after each episode."""
        # Report intermediate value
        if self.metric == "mean_reward":
            value = metrics.average_reward
        elif self.metric == "total_reward":
            value = metrics.total_reward
        else:
            value = metrics.total_reward
            
        self.trial.report(value, episode)
        
        # Check if trial should be pruned
        if self.trial.should_prune():
            raise optuna.TrialPruned()


class HyperparameterOptimizer:
    """
    Main hyperparameter optimization class using Optuna.
    
    Provides automated hyperparameter tuning with parallel execution,
    resource management, and comprehensive result tracking.
    """
    
    def __init__(self, config: OptimizationConfig):
        """
        Initialize hyperparameter optimizer.
        
        Args:
            config: Optimization configuration
        """
        if not OPTUNA_AVAILABLE:
            raise ImportError("Optuna is required for hyperparameter optimization. Install with: pip install optuna")
            
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Setup logging
        optuna.logging.set_verbosity(getattr(optuna.logging, config.log_level))
        
        # Initialize study
        self.study = None
        self._setup_study()
        
        # Results tracking
        self.trial_results: List[TrialResult] = []
        self.best_params: Optional[Dict[str, Any]] = None
        self.best_value: Optional[float] = None
        
    def _setup_study(self) -> None:
        """Setup Optuna study with specified configuration."""
        # Create sampler
        if self.config.sampler == "tpe":
            sampler = TPESampler()
        elif self.config.sampler == "random":
            sampler = RandomSampler()
        elif self.config.sampler == "cmaes":
            sampler = CmaEsSampler()
        else:
            sampler = TPESampler()
            
        # Create pruner
        if self.config.pruner == "median":
            pruner = MedianPruner(
                n_startup_trials=self.config.min_trials_for_pruning,
                n_warmup_steps=10
            )
        elif self.config.pruner == "hyperband":
            pruner = HyperbandPruner(
                min_resource=10,
                max_resource=1000,
                reduction_factor=3
            )
        else:
            pruner = optuna.pruners.NopPruner()
            
        # Create study
        self.study = optuna.create_study(
            study_name=self.config.study_name,
            direction=self.config.direction,
            sampler=sampler,
            pruner=pruner,
            storage=self.config.storage_url,
            load_if_exists=self.config.load_if_exists
        )
        
        self.logger.info(f"Created study: {self.config.study_name}")
        
    def optimize(self, 
                 objective_function: ObjectiveFunction,
                 agent_factory: Callable,
                 environment_factory: Callable) -> Dict[str, Any]:
        """
        Run hyperparameter optimization.
        
        Args:
            objective_function: Objective function to optimize
            agent_factory: Factory function to create agents
            environment_factory: Factory function to create environments
            
        Returns:
            Dictionary with optimization results
        """
        self.logger.info(f"Starting optimization with {self.config.n_trials} trials")
        
        start_time = time.time()
        
        try:
            if self.config.n_jobs == 1:
                # Sequential optimization
                self._optimize_sequential(objective_function, agent_factory, environment_factory)
            else:
                # Parallel optimization
                self._optimize_parallel(objective_function, agent_factory, environment_factory)
                
        except KeyboardInterrupt:
            self.logger.info("Optimization interrupted by user")
        except Exception as e:
            self.logger.error(f"Optimization failed: {e}")
            raise
            
        end_time = time.time()
        optimization_time = end_time - start_time
        
        # Get best results
        self.best_params = self.study.best_params
        self.best_value = self.study.best_value
        
        # Create results summary
        results = {
            'best_params': self.best_params,
            'best_value': self.best_value,
            'n_trials': len(self.study.trials),
            'optimization_time': optimization_time,
            'study_name': self.config.study_name,
            'completed_trials': len([t for t in self.study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
            'pruned_trials': len([t for t in self.study.trials if t.state == optuna.trial.TrialState.PRUNED]),
            'failed_trials': len([t for t in self.study.trials if t.state == optuna.trial.TrialState.FAIL])
        }
        
        self.logger.info(f"Optimization completed. Best value: {self.best_value}")
        return results
        
    def _optimize_sequential(self, objective_function: ObjectiveFunction, 
                           agent_factory: Callable, environment_factory: Callable) -> None:
        """Run sequential optimization."""
        def objective(trial):
            return objective_function(trial, agent_factory, environment_factory)
            
        self.study.optimize(
            objective,
            n_trials=self.config.n_trials,
            timeout=self.config.timeout
        )
        
    def _optimize_parallel(self, objective_function: ObjectiveFunction,
                          agent_factory: Callable, environment_factory: Callable) -> None:
        """Run parallel optimization."""
        def objective(trial):
            return objective_function(trial, agent_factory, environment_factory)
            
        # Use joblib for parallel execution
        try:
            from joblib import Parallel, delayed
            
            def run_trial(_):
                return self.study.optimize(objective, n_trials=1)
                
            Parallel(n_jobs=self.config.n_jobs)(
                delayed(run_trial)(i) for i in range(self.config.n_trials)
            )
            
        except ImportError:
            self.logger.warning("joblib not available, falling back to sequential optimization")
            self._optimize_sequential(objective_function, agent_factory, environment_factory)
            
    def get_optimization_history(self) -> List[Dict[str, Any]]:
        """Get optimization history."""
        history = []
        
        for trial in self.study.trials:
            trial_info = {
                'number': trial.number,
                'value': trial.value,
                'params': trial.params,
                'state': trial.state.name,
                'datetime_start': trial.datetime_start,
                'datetime_complete': trial.datetime_complete,
                'duration': trial.duration.total_seconds() if trial.duration else None,
                'user_attrs': trial.user_attrs
            }
            history.append(trial_info)
            
        return history
        
    def get_best_trials(self, n_trials: int = 10) -> List[Dict[str, Any]]:
        """Get best trials."""
        if self.config.direction == "maximize":
            best_trials = sorted(
                [t for t in self.study.trials if t.state == optuna.trial.TrialState.COMPLETE],
                key=lambda x: x.value,
                reverse=True
            )[:n_trials]
        else:
            best_trials = sorted(
                [t for t in self.study.trials if t.state == optuna.trial.TrialState.COMPLETE],
                key=lambda x: x.value
            )[:n_trials]
            
        return [
            {
                'number': trial.number,
                'value': trial.value,
                'params': trial.params,
                'user_attrs': trial.user_attrs
            }
            for trial in best_trials
        ]
        
    def plot_optimization_history(self, save_path: Optional[str] = None) -> None:
        """Plot optimization history."""
        try:
            import matplotlib.pyplot as plt
            
            # Plot optimization history
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
            
            # Plot 1: Optimization history
            optuna.visualization.matplotlib.plot_optimization_history(self.study, ax=ax1)
            ax1.set_title('Optimization History')
            
            # Plot 2: Parameter importances
            try:
                optuna.visualization.matplotlib.plot_param_importances(self.study, ax=ax2)
                ax2.set_title('Parameter Importances')
            except:
                ax2.text(0.5, 0.5, 'Parameter importances\nnot available', 
                        ha='center', va='center', transform=ax2.transAxes)
                ax2.set_title('Parameter Importances')
                
            plt.tight_layout()
            
            if save_path:
                plt.savefig(save_path, dpi=300, bbox_inches='tight')
                self.logger.info(f"Saved optimization plots to {save_path}")
                
            plt.show()
            
        except ImportError:
            self.logger.warning("Matplotlib not available for plotting")
            
    def save_results(self, filepath: str) -> None:
        """Save optimization results to file."""
        results = {
            'config': asdict(self.config),
            'best_params': self.best_params,
            'best_value': self.best_value,
            'optimization_history': self.get_optimization_history(),
            'best_trials': self.get_best_trials(),
            'study_summary': {
                'n_trials': len(self.study.trials),
                'completed_trials': len([t for t in self.study.trials if t.state == optuna.trial.TrialState.COMPLETE]),
                'pruned_trials': len([t for t in self.study.trials if t.state == optuna.trial.TrialState.PRUNED]),
                'failed_trials': len([t for t in self.study.trials if t.state == optuna.trial.TrialState.FAIL])
            },
            'timestamp': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2, default=str)
            
        self.logger.info(f"Saved optimization results to {filepath}")
        
    def load_results(self, filepath: str) -> Dict[str, Any]:
        """Load optimization results from file."""
        with open(filepath, 'r') as f:
            results = json.load(f)
            
        self.best_params = results.get('best_params')
        self.best_value = results.get('best_value')
        
        self.logger.info(f"Loaded optimization results from {filepath}")
        return results


class OptimizationManager:
    """
    High-level manager for hyperparameter optimization workflows.
    
    Provides convenient methods for common optimization scenarios
    and manages multiple optimization studies.
    """
    
    def __init__(self, base_dir: str = "optimization_results"):
        """
        Initialize optimization manager.
        
        Args:
            base_dir: Base directory for storing optimization results
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.optimizers: Dict[str, HyperparameterOptimizer] = {}
        self.logger = logging.getLogger(__name__)
        
    def create_optimizer(self, name: str, config: OptimizationConfig) -> HyperparameterOptimizer:
        """Create and register a new optimizer."""
        optimizer = HyperparameterOptimizer(config)
        self.optimizers[name] = optimizer
        
        self.logger.info(f"Created optimizer: {name}")
        return optimizer
        
    def optimize_agent(self,
                      name: str,
                      agent_type: str,
                      base_training_config: TrainingConfig,
                      base_agent_config: AgentConfig,
                      agent_factory: Callable,
                      environment_factory: Callable,
                      optimization_config: OptimizationConfig,
                      metric: str = "mean_reward") -> Dict[str, Any]:
        """
        Optimize agent hyperparameters.
        
        Args:
            name: Name for this optimization study
            agent_type: Type of agent ("dqn" or "ppo")
            base_training_config: Base training configuration
            base_agent_config: Base agent configuration
            agent_factory: Factory function to create agents
            environment_factory: Factory function to create environments
            optimization_config: Optimization configuration
            metric: Metric to optimize
            
        Returns:
            Optimization results
        """
        # Create optimizer
        optimizer = self.create_optimizer(name, optimization_config)
        
        # Create objective function
        objective_function = RLObjectiveFunction(
            base_training_config=base_training_config,
            base_agent_config=base_agent_config,
            agent_type=agent_type,
            metric=metric
        )
        
        # Run optimization
        results = optimizer.optimize(objective_function, agent_factory, environment_factory)
        
        # Save results
        results_path = self.base_dir / f"{name}_results.json"
        optimizer.save_results(str(results_path))
        
        # Plot results if requested
        if optimization_config.plot_optimization_history:
            plot_path = self.base_dir / f"{name}_plots.png"
            optimizer.plot_optimization_history(str(plot_path))
            
        return results
        
    def compare_optimizations(self, names: List[str]) -> Dict[str, Any]:
        """Compare results from multiple optimizations."""
        comparison = {
            'optimizations': {},
            'best_overall': None,
            'summary': {}
        }
        
        best_value = float('-inf')
        best_name = None
        
        for name in names:
            if name in self.optimizers:
                optimizer = self.optimizers[name]
                
                comparison['optimizations'][name] = {
                    'best_value': optimizer.best_value,
                    'best_params': optimizer.best_params,
                    'n_trials': len(optimizer.study.trials),
                    'completed_trials': len([t for t in optimizer.study.trials 
                                           if t.state == optuna.trial.TrialState.COMPLETE])
                }
                
                if optimizer.best_value and optimizer.best_value > best_value:
                    best_value = optimizer.best_value
                    best_name = name
                    
        comparison['best_overall'] = {
            'name': best_name,
            'value': best_value,
            'params': self.optimizers[best_name].best_params if best_name else None
        }
        
        return comparison
        
    def get_optimization_summary(self) -> Dict[str, Any]:
        """Get summary of all optimizations."""
        summary = {
            'total_optimizations': len(self.optimizers),
            'optimizations': {}
        }
        
        for name, optimizer in self.optimizers.items():
            summary['optimizations'][name] = {
                'study_name': optimizer.config.study_name,
                'n_trials': len(optimizer.study.trials),
                'best_value': optimizer.best_value,
                'status': 'completed' if optimizer.best_value is not None else 'running'
            }
            
        return summary
"""
Agent Trainer and Training Orchestration

This module implements the AgentTrainer class that manages the complete training
lifecycle for RL agents, including configuration management, progress tracking,
and training orchestration.
"""

import numpy as np
import torch
import json
import time
from typing import Dict, Any, List, Optional, Union, Callable
from dataclasses import dataclass, asdict
from pathlib import Path
from datetime import datetime
import logging
from abc import ABC, abstractmethod

from ..agents.base import RLAgent
from ..agents.dqn import DQNAgent
from ..agents.ppo import PPOAgent
# from ..environments.trading_env import TradingEnvironment  # Will be imported when available


@dataclass
class TrainingConfig:
    """Configuration for agent training."""
    # Training parameters
    total_episodes: int = 1000
    max_steps_per_episode: int = 1000
    evaluation_frequency: int = 100
    save_frequency: int = 200
    
    # Early stopping
    early_stopping_patience: int = 50
    early_stopping_threshold: float = 0.01
    
    # Logging and monitoring
    log_frequency: int = 10
    tensorboard_logging: bool = True
    save_training_data: bool = True
    
    # Checkpointing
    checkpoint_dir: str = "checkpoints"
    max_checkpoints: int = 5
    
    # Evaluation
    evaluation_episodes: int = 10
    evaluation_deterministic: bool = True
    
    # Resource management
    device: str = "auto"  # "auto", "cpu", "cuda"
    num_workers: int = 1
    
    # Experiment tracking
    experiment_name: Optional[str] = None
    experiment_tags: List[str] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.experiment_tags is None:
            self.experiment_tags = []
        
        if self.experiment_name is None:
            self.experiment_name = f"training_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class TrainingMetrics:
    """Training metrics and statistics."""
    episode: int
    total_reward: float
    episode_length: int
    average_reward: float
    loss: Optional[float] = None
    
    # Performance metrics
    win_rate: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    
    # Training statistics
    exploration_rate: Optional[float] = None
    learning_rate: Optional[float] = None
    
    # Timing
    episode_time: float = 0.0
    total_time: float = 0.0
    
    # Additional metrics
    custom_metrics: Dict[str, float] = None
    
    def __post_init__(self):
        """Initialize default values."""
        if self.custom_metrics is None:
            self.custom_metrics = {}


class TrainingCallback(ABC):
    """Abstract base class for training callbacks."""
    
    @abstractmethod
    def on_training_start(self, trainer: 'AgentTrainer') -> None:
        """Called when training starts."""
        pass
    
    @abstractmethod
    def on_training_end(self, trainer: 'AgentTrainer') -> None:
        """Called when training ends."""
        pass
    
    @abstractmethod
    def on_episode_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Called at the start of each episode."""
        pass
    
    @abstractmethod
    def on_episode_end(self, trainer: 'AgentTrainer', episode: int, metrics: TrainingMetrics) -> None:
        """Called at the end of each episode."""
        pass
    
    @abstractmethod
    def on_evaluation_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Called when evaluation starts."""
        pass
    
    @abstractmethod
    def on_evaluation_end(self, trainer: 'AgentTrainer', episode: int, eval_metrics: Dict[str, float]) -> None:
        """Called when evaluation ends."""
        pass


class LoggingCallback(TrainingCallback):
    """Callback for logging training progress."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        Initialize logging callback.
        
        Args:
            logger: Logger instance to use
        """
        self.logger = logger or logging.getLogger(__name__)
        self.start_time = None
        
    def on_training_start(self, trainer: 'AgentTrainer') -> None:
        """Log training start."""
        self.start_time = time.time()
        self.logger.info(f"Starting training for {trainer.config.total_episodes} episodes")
        self.logger.info(f"Agent: {type(trainer.agent).__name__}")
        self.logger.info(f"Environment: {type(trainer.environment).__name__}")
        
    def on_training_end(self, trainer: 'AgentTrainer') -> None:
        """Log training completion."""
        total_time = time.time() - self.start_time
        self.logger.info(f"Training completed in {total_time:.2f} seconds")
        
    def on_episode_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Log episode start."""
        if episode % trainer.config.log_frequency == 0:
            self.logger.debug(f"Starting episode {episode}")
            
    def on_episode_end(self, trainer: 'AgentTrainer', episode: int, metrics: TrainingMetrics) -> None:
        """Log episode completion."""
        if episode % trainer.config.log_frequency == 0:
            self.logger.info(
                f"Episode {episode}: Reward={metrics.total_reward:.2f}, "
                f"Length={metrics.episode_length}, "
                f"Avg Reward={metrics.average_reward:.2f}"
            )
            
    def on_evaluation_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Log evaluation start."""
        self.logger.info(f"Starting evaluation at episode {episode}")
        
    def on_evaluation_end(self, trainer: 'AgentTrainer', episode: int, eval_metrics: Dict[str, float]) -> None:
        """Log evaluation results."""
        self.logger.info(f"Evaluation results: {eval_metrics}")


class TensorBoardCallback(TrainingCallback):
    """Callback for TensorBoard logging."""
    
    def __init__(self, log_dir: str):
        """
        Initialize TensorBoard callback.
        
        Args:
            log_dir: Directory for TensorBoard logs
        """
        self.log_dir = Path(log_dir)
        self.writer = None
        
        try:
            from torch.utils.tensorboard import SummaryWriter
            self.writer = SummaryWriter(log_dir=str(self.log_dir))
        except ImportError:
            logging.warning("TensorBoard not available. Install tensorboard to enable logging.")
            self.writer = None
            
    def on_training_start(self, trainer: 'AgentTrainer') -> None:
        """Initialize TensorBoard logging."""
        if self.writer:
            # Log training configuration
            config_text = json.dumps(asdict(trainer.config), indent=2)
            self.writer.add_text("config", config_text, 0)
            
    def on_training_end(self, trainer: 'AgentTrainer') -> None:
        """Close TensorBoard writer."""
        if self.writer:
            self.writer.close()
            
    def on_episode_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Log episode start to TensorBoard."""
        pass
        
    def on_episode_end(self, trainer: 'AgentTrainer', episode: int, metrics: TrainingMetrics) -> None:
        """Log episode metrics to TensorBoard."""
        if not self.writer:
            return
            
        # Log basic metrics
        self.writer.add_scalar("reward/total", metrics.total_reward, episode)
        self.writer.add_scalar("reward/average", metrics.average_reward, episode)
        self.writer.add_scalar("episode/length", metrics.episode_length, episode)
        self.writer.add_scalar("episode/time", metrics.episode_time, episode)
        
        # Log optional metrics
        if metrics.loss is not None:
            self.writer.add_scalar("training/loss", metrics.loss, episode)
        if metrics.exploration_rate is not None:
            self.writer.add_scalar("training/exploration_rate", metrics.exploration_rate, episode)
        if metrics.learning_rate is not None:
            self.writer.add_scalar("training/learning_rate", metrics.learning_rate, episode)
            
        # Log performance metrics
        if metrics.win_rate is not None:
            self.writer.add_scalar("performance/win_rate", metrics.win_rate, episode)
        if metrics.sharpe_ratio is not None:
            self.writer.add_scalar("performance/sharpe_ratio", metrics.sharpe_ratio, episode)
        if metrics.max_drawdown is not None:
            self.writer.add_scalar("performance/max_drawdown", metrics.max_drawdown, episode)
            
        # Log custom metrics
        for key, value in metrics.custom_metrics.items():
            self.writer.add_scalar(f"custom/{key}", value, episode)
            
    def on_evaluation_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Log evaluation start."""
        pass
        
    def on_evaluation_end(self, trainer: 'AgentTrainer', episode: int, eval_metrics: Dict[str, float]) -> None:
        """Log evaluation metrics."""
        if not self.writer:
            return
            
        for key, value in eval_metrics.items():
            self.writer.add_scalar(f"evaluation/{key}", value, episode)


class CheckpointCallback(TrainingCallback):
    """Callback for model checkpointing."""
    
    def __init__(self, checkpoint_dir: str, max_checkpoints: int = 5):
        """
        Initialize checkpoint callback.
        
        Args:
            checkpoint_dir: Directory to save checkpoints
            max_checkpoints: Maximum number of checkpoints to keep
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        self.max_checkpoints = max_checkpoints
        self.checkpoints = []
        
    def on_training_start(self, trainer: 'AgentTrainer') -> None:
        """Initialize checkpointing."""
        pass
        
    def on_training_end(self, trainer: 'AgentTrainer') -> None:
        """Save final checkpoint."""
        self._save_checkpoint(trainer, "final")
        
    def on_episode_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Check if checkpoint should be saved."""
        pass
        
    def on_episode_end(self, trainer: 'AgentTrainer', episode: int, metrics: TrainingMetrics) -> None:
        """Save checkpoint if needed."""
        if episode % trainer.config.save_frequency == 0:
            self._save_checkpoint(trainer, f"episode_{episode}")
            
    def on_evaluation_start(self, trainer: 'AgentTrainer', episode: int) -> None:
        """Handle evaluation start."""
        pass
        
    def on_evaluation_end(self, trainer: 'AgentTrainer', episode: int, eval_metrics: Dict[str, float]) -> None:
        """Handle evaluation end."""
        pass
        
    def _save_checkpoint(self, trainer: 'AgentTrainer', name: str) -> None:
        """Save training checkpoint."""
        checkpoint_path = self.checkpoint_dir / f"{name}.pth"
        
        checkpoint_data = {
            'episode': trainer.current_episode,
            'agent_state_dict': trainer.agent.get_state(),
            'training_metrics': trainer.training_history,
            'config': asdict(trainer.config),
            'timestamp': datetime.now().isoformat()
        }
        
        torch.save(checkpoint_data, checkpoint_path)
        self.checkpoints.append(checkpoint_path)
        
        # Clean up old checkpoints
        if len(self.checkpoints) > self.max_checkpoints:
            old_checkpoint = self.checkpoints.pop(0)
            if old_checkpoint.exists():
                old_checkpoint.unlink()


class AgentTrainer:
    """
    Agent trainer for managing complete training lifecycle.
    
    Handles training orchestration, progress tracking, and model management
    for RL agents in trading environments.
    """
    
    def __init__(self, 
                 agent: RLAgent,
                 environment: Any,  # TradingEnvironment when available
                 config: TrainingConfig):
        """
        Initialize agent trainer.
        
        Args:
            agent: RL agent to train
            environment: Trading environment (any environment with gym-like interface)
            config: Training configuration
        """
        self.agent = agent
        self.environment = environment
        self.config = config
        
        # Logger (initialize first)
        self.logger = logging.getLogger(__name__)
        
        # Training state
        self.current_episode = 0
        self.training_history: List[TrainingMetrics] = []
        self.evaluation_history: List[Dict[str, float]] = []
        self.best_performance = float('-inf')
        self.episodes_without_improvement = 0
        
        # Callbacks
        self.callbacks: List[TrainingCallback] = []
        
        # Setup default callbacks
        self._setup_default_callbacks()
        
        # Device setup
        self.device = self._setup_device()
        
    def _setup_default_callbacks(self) -> None:
        """Setup default training callbacks."""
        # Logging callback
        self.add_callback(LoggingCallback())
        
        # TensorBoard callback
        if self.config.tensorboard_logging:
            log_dir = Path(self.config.checkpoint_dir) / "tensorboard"
            self.add_callback(TensorBoardCallback(str(log_dir)))
            
        # Checkpoint callback
        self.add_callback(CheckpointCallback(
            self.config.checkpoint_dir,
            self.config.max_checkpoints
        ))
        
    def _setup_device(self) -> torch.device:
        """Setup compute device."""
        if self.config.device == "auto":
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            device = torch.device(self.config.device)
            
        self.logger.info(f"Using device: {device}")
        return device
        
    def add_callback(self, callback: TrainingCallback) -> None:
        """Add training callback."""
        self.callbacks.append(callback)
        
    def remove_callback(self, callback: TrainingCallback) -> None:
        """Remove training callback."""
        if callback in self.callbacks:
            self.callbacks.remove(callback)
            
    def train(self) -> List[TrainingMetrics]:
        """
        Run complete training loop.
        
        Returns:
            List of training metrics for each episode
        """
        self.logger.info("Starting agent training")
        
        # Notify callbacks
        for callback in self.callbacks:
            callback.on_training_start(self)
            
        try:
            for episode in range(self.config.total_episodes):
                self.current_episode = episode
                
                # Train single episode
                metrics = self._train_episode(episode)
                self.training_history.append(metrics)
                
                # Check for early stopping
                if self._should_stop_early(metrics):
                    self.logger.info(f"Early stopping at episode {episode}")
                    break
                    
                # Evaluation
                if episode % self.config.evaluation_frequency == 0:
                    eval_metrics = self._evaluate(episode)
                    self.evaluation_history.append(eval_metrics)
                    
        except KeyboardInterrupt:
            self.logger.info("Training interrupted by user")
        except Exception as e:
            self.logger.error(f"Training failed with error: {e}")
            raise
        finally:
            # Notify callbacks
            for callback in self.callbacks:
                callback.on_training_end(self)
                
        self.logger.info("Training completed")
        return self.training_history
        
    def _train_episode(self, episode: int) -> TrainingMetrics:
        """
        Train single episode.
        
        Args:
            episode: Episode number
            
        Returns:
            Episode training metrics
        """
        start_time = time.time()
        
        # Notify callbacks
        for callback in self.callbacks:
            callback.on_episode_start(self, episode)
            
        # Reset environment
        state = self.environment.reset()
        total_reward = 0.0
        episode_length = 0
        losses = []
        
        for step in range(self.config.max_steps_per_episode):
            # Select action
            action = self.agent.select_action(state, training=True)
            
            # Take step
            next_state, reward, done, info = self.environment.step(action)
            
            # Store experience and train
            if hasattr(self.agent, 'store_experience'):
                self.agent.store_experience(state, action, reward, next_state, done)
                
            if hasattr(self.agent, 'train_step'):
                loss = self.agent.train_step()
                if loss is not None:
                    losses.append(loss)
                    
            # Update state
            state = next_state
            total_reward += reward
            episode_length += 1
            
            if done:
                break
                
        # Calculate metrics
        episode_time = time.time() - start_time
        average_reward = np.mean([m.total_reward for m in self.training_history[-100:]] + [total_reward])
        
        metrics = TrainingMetrics(
            episode=episode,
            total_reward=total_reward,
            episode_length=episode_length,
            average_reward=average_reward,
            loss=np.mean(losses) if losses else None,
            episode_time=episode_time,
            total_time=sum(m.episode_time for m in self.training_history) + episode_time
        )
        
        # Add agent-specific metrics
        if hasattr(self.agent, 'get_training_metrics'):
            agent_metrics = self.agent.get_training_metrics()
            if isinstance(agent_metrics, dict):
                metrics.custom_metrics.update(agent_metrics)
                
        # Add exploration rate for DQN
        if isinstance(self.agent, DQNAgent):
            metrics.exploration_rate = self.agent.epsilon
            
        # Notify callbacks
        for callback in self.callbacks:
            callback.on_episode_end(self, episode, metrics)
            
        return metrics
        
    def _evaluate(self, episode: int) -> Dict[str, float]:
        """
        Evaluate agent performance.
        
        Args:
            episode: Current episode number
            
        Returns:
            Evaluation metrics
        """
        # Notify callbacks
        for callback in self.callbacks:
            callback.on_evaluation_start(self, episode)
            
        eval_rewards = []
        eval_lengths = []
        
        for eval_episode in range(self.config.evaluation_episodes):
            state = self.environment.reset()
            total_reward = 0.0
            episode_length = 0
            
            for step in range(self.config.max_steps_per_episode):
                action = self.agent.select_action(
                    state, 
                    training=not self.config.evaluation_deterministic
                )
                
                next_state, reward, done, info = self.environment.step(action)
                
                state = next_state
                total_reward += reward
                episode_length += 1
                
                if done:
                    break
                    
            eval_rewards.append(total_reward)
            eval_lengths.append(episode_length)
            
        # Calculate evaluation metrics
        eval_metrics = {
            'mean_reward': np.mean(eval_rewards),
            'std_reward': np.std(eval_rewards),
            'mean_length': np.mean(eval_lengths),
            'std_length': np.std(eval_lengths),
            'min_reward': np.min(eval_rewards),
            'max_reward': np.max(eval_rewards)
        }
        
        # Notify callbacks
        for callback in self.callbacks:
            callback.on_evaluation_end(self, episode, eval_metrics)
            
        return eval_metrics
        
    def _should_stop_early(self, metrics: TrainingMetrics) -> bool:
        """
        Check if training should stop early.
        
        Args:
            metrics: Current episode metrics
            
        Returns:
            True if training should stop
        """
        if not hasattr(self.config, 'early_stopping_patience'):
            return False
            
        # Check if performance improved
        if metrics.average_reward > self.best_performance + self.config.early_stopping_threshold:
            self.best_performance = metrics.average_reward
            self.episodes_without_improvement = 0
        else:
            self.episodes_without_improvement += 1
            
        return self.episodes_without_improvement >= self.config.early_stopping_patience
        
    def save_training_data(self, filepath: str) -> None:
        """
        Save training data to file.
        
        Args:
            filepath: Path to save training data
        """
        training_data = {
            'config': asdict(self.config),
            'training_history': [asdict(m) for m in self.training_history],
            'evaluation_history': self.evaluation_history,
            'agent_type': type(self.agent).__name__,
            'environment_type': type(self.environment).__name__,
            'timestamp': datetime.now().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(training_data, f, indent=2)
            
    def load_training_data(self, filepath: str) -> None:
        """
        Load training data from file.
        
        Args:
            filepath: Path to load training data from
        """
        with open(filepath, 'r') as f:
            training_data = json.load(f)
            
        # Restore training history
        self.training_history = [
            TrainingMetrics(**m) for m in training_data['training_history']
        ]
        self.evaluation_history = training_data['evaluation_history']
        
    def get_training_summary(self) -> Dict[str, Any]:
        """
        Get training summary statistics.
        
        Returns:
            Dictionary with training summary
        """
        if not self.training_history:
            return {}
            
        rewards = [m.total_reward for m in self.training_history]
        lengths = [m.episode_length for m in self.training_history]
        times = [m.episode_time for m in self.training_history]
        
        summary = {
            'total_episodes': len(self.training_history),
            'total_time': sum(times),
            'average_episode_time': np.mean(times),
            'reward_statistics': {
                'mean': np.mean(rewards),
                'std': np.std(rewards),
                'min': np.min(rewards),
                'max': np.max(rewards),
                'final_100_mean': np.mean(rewards[-100:]) if len(rewards) >= 100 else np.mean(rewards)
            },
            'length_statistics': {
                'mean': np.mean(lengths),
                'std': np.std(lengths),
                'min': np.min(lengths),
                'max': np.max(lengths)
            },
            'best_performance': self.best_performance,
            'convergence_episode': self._find_convergence_episode()
        }
        
        return summary
        
    def _find_convergence_episode(self) -> Optional[int]:
        """Find episode where training converged."""
        if len(self.training_history) < 100:
            return None
            
        # Look for stable performance over last 100 episodes
        rewards = [m.total_reward for m in self.training_history]
        
        for i in range(100, len(rewards)):
            recent_mean = np.mean(rewards[i-100:i])
            if abs(recent_mean - self.best_performance) < self.config.early_stopping_threshold:
                return i
                
        return None
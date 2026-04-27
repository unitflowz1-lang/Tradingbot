"""
PPO-Specific Optimizations

This module implements advanced PPO optimizations including parallel environment
support, enhanced early stopping mechanisms, and specialized checkpointing.
"""

import numpy as np
import torch
import torch.multiprocessing as mp
from typing import List, Dict, Any, Optional, Tuple, Callable
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import queue
import time
import os
from pathlib import Path

from .ppo import PPOAgent, PPOConfig
from .ppo_trainer import PPOTrainer, PPOTrainingConfig
from .base import Experience


@dataclass
class ParallelTrainingConfig:
    """Configuration for parallel PPO training."""
    num_workers: int = 4
    steps_per_worker: int = 128
    batch_size: int = 512
    max_queue_size: int = 1000
    worker_timeout: float = 30.0
    
    # Synchronization settings
    sync_frequency: int = 10  # Steps between parameter synchronization
    gradient_accumulation: bool = True
    
    # Resource management
    max_memory_per_worker: float = 1.0  # GB
    cpu_affinity: bool = False


@dataclass
class EarlyStoppingConfig:
    """Configuration for enhanced early stopping."""
    # KL divergence based stopping
    target_kl: float = 0.01
    kl_tolerance: float = 2.0  # Multiple of target_kl before stopping
    kl_window_size: int = 10   # Window for KL averaging
    
    # Policy entropy based stopping
    min_entropy: float = 0.1
    entropy_window_size: int = 20
    
    # Value function based stopping
    value_loss_threshold: float = 1.0
    value_loss_patience: int = 5
    
    # Performance based stopping
    performance_plateau_threshold: float = 0.01
    performance_patience: int = 20
    
    # General settings
    min_training_steps: int = 100
    check_frequency: int = 1


@dataclass
class CheckpointConfig:
    """Configuration for PPO checkpointing."""
    save_frequency: int = 100
    max_checkpoints: int = 10
    save_best_only: bool = False
    metric_for_best: str = "episode_reward"  # "episode_reward", "policy_loss", "value_loss"
    
    # Checkpoint content
    save_optimizer_state: bool = True
    save_training_state: bool = True
    save_replay_buffer: bool = False
    
    # Compression and storage
    compress_checkpoints: bool = True
    checkpoint_format: str = "pytorch"  # "pytorch", "onnx"


class ParallelEnvironmentWorker:
    """Worker process for parallel environment interaction."""
    
    def __init__(self, worker_id: int, env_factory: Callable, agent_config: PPOConfig):
        """
        Initialize parallel worker.
        
        Args:
            worker_id: Unique worker identifier
            env_factory: Factory function to create environment
            agent_config: Agent configuration
        """
        self.worker_id = worker_id
        self.env_factory = env_factory
        self.agent_config = agent_config
        self.env = None
        self.agent = None
        
    def initialize(self):
        """Initialize worker environment and agent."""
        self.env = self.env_factory()
        self.agent = PPOAgent(
            self.env.observation_space.shape[0],
            self.env.action_space.n,
            self.agent_config
        )
        
    def collect_trajectory(self, steps: int, shared_params: Optional[Dict] = None) -> List[Dict]:
        """
        Collect trajectory data from environment.
        
        Args:
            steps: Number of steps to collect
            shared_params: Shared parameters from main agent
            
        Returns:
            List of trajectory steps
        """
        if shared_params is not None:
            self.agent.policy_network.load_state_dict(shared_params['policy'])
            self.agent.value_network.load_state_dict(shared_params['value'])
            
        trajectory = []
        state = self.env.reset()
        
        for _ in range(steps):
            # Get action and value from agent
            action, value, log_prob = self.agent.get_action_and_value(state)
            
            # Take step in environment
            next_state, reward, done, info = self.env.step(action)
            
            # Store trajectory step
            trajectory.append({
                'state': state.copy(),
                'action': action,
                'reward': reward,
                'value': value,
                'log_prob': log_prob,
                'done': done
            })
            
            state = next_state
            if done:
                state = self.env.reset()
                
        return trajectory


class ParallelPPOTrainer:
    """
    Parallel PPO trainer with multiple environment workers.
    
    Implements asynchronous advantage actor-critic (A3C) style parallelization
    for PPO with synchronized parameter updates.
    """
    
    def __init__(self, 
                 main_agent: PPOAgent,
                 env_factory: Callable,
                 config: ParallelTrainingConfig):
        """
        Initialize parallel PPO trainer.
        
        Args:
            main_agent: Main PPO agent
            env_factory: Factory function to create environments
            config: Parallel training configuration
        """
        self.main_agent = main_agent
        self.env_factory = env_factory
        self.config = config
        
        # Worker management
        self.workers = []
        self.worker_threads = []
        self.trajectory_queue = queue.Queue(maxsize=config.max_queue_size)
        self.parameter_lock = threading.Lock()
        
        # Training state
        self.global_step = 0
        self.is_training = False
        
        # Initialize workers
        self._initialize_workers()
        
    def _initialize_workers(self):
        """Initialize worker processes."""
        for worker_id in range(self.config.num_workers):
            worker = ParallelEnvironmentWorker(
                worker_id, self.env_factory, self.main_agent.config
            )
            self.workers.append(worker)
            
    def _worker_loop(self, worker: ParallelEnvironmentWorker):
        """Main loop for worker thread."""
        worker.initialize()
        
        while self.is_training:
            try:
                # Get shared parameters
                with self.parameter_lock:
                    shared_params = {
                        'policy': self.main_agent.policy_network.state_dict(),
                        'value': self.main_agent.value_network.state_dict()
                    }
                
                # Collect trajectory
                trajectory = worker.collect_trajectory(
                    self.config.steps_per_worker, shared_params
                )
                
                # Add to queue
                self.trajectory_queue.put({
                    'worker_id': worker.worker_id,
                    'trajectory': trajectory,
                    'timestamp': time.time()
                })
                
            except Exception as e:
                print(f"Worker {worker.worker_id} error: {e}")
                break
                
    def start_workers(self):
        """Start all worker threads."""
        self.is_training = True
        
        for worker in self.workers:
            thread = threading.Thread(
                target=self._worker_loop, 
                args=(worker,),
                daemon=True
            )
            thread.start()
            self.worker_threads.append(thread)
            
    def stop_workers(self):
        """Stop all worker threads."""
        self.is_training = False
        
        # Wait for threads to finish
        for thread in self.worker_threads:
            thread.join(timeout=self.config.worker_timeout)
            
        self.worker_threads.clear()
        
    def collect_parallel_trajectories(self, num_batches: int = 1) -> List[Dict]:
        """
        Collect trajectories from parallel workers.
        
        Args:
            num_batches: Number of trajectory batches to collect
            
        Returns:
            List of collected trajectories
        """
        trajectories = []
        collected_batches = 0
        
        while collected_batches < num_batches:
            try:
                # Get trajectory from queue
                trajectory_data = self.trajectory_queue.get(timeout=self.config.worker_timeout)
                trajectories.extend(trajectory_data['trajectory'])
                collected_batches += 1
                
            except queue.Empty:
                print("Warning: Timeout waiting for worker trajectories")
                break
                
        return trajectories
        
    def train_parallel_step(self, trainer: PPOTrainer) -> Dict[str, float]:
        """
        Perform parallel training step.
        
        Args:
            trainer: PPO trainer instance
            
        Returns:
            Training metrics
        """
        # Collect trajectories from workers
        trajectories = self.collect_parallel_trajectories(self.config.num_workers)
        
        if not trajectories:
            return {"policy_loss": 0.0, "value_loss": 0.0, "entropy": 0.0}
            
        # Convert to tensor format
        trajectory_data = self._convert_trajectories_to_tensors(trajectories)
        
        # Perform training step
        with self.parameter_lock:
            metrics = trainer.train_step(trajectory_data)
            
        self.global_step += 1
        return metrics
        
    def _convert_trajectories_to_tensors(self, trajectories: List[Dict]) -> Dict[str, torch.Tensor]:
        """Convert trajectory list to tensor format."""
        states = torch.FloatTensor(np.array([t['state'] for t in trajectories])).to(self.main_agent.device)
        actions = torch.LongTensor([t['action'] for t in trajectories]).to(self.main_agent.device)
        rewards = torch.FloatTensor([t['reward'] for t in trajectories]).to(self.main_agent.device)
        values = torch.FloatTensor([t['value'] for t in trajectories]).to(self.main_agent.device)
        log_probs = torch.FloatTensor([t['log_prob'] for t in trajectories]).to(self.main_agent.device)
        dones = torch.BoolTensor([t['done'] for t in trajectories]).to(self.main_agent.device)
        
        return {
            'states': states,
            'actions': actions,
            'rewards': rewards,
            'values': values,
            'log_probs': log_probs,
            'dones': dones
        }


class EnhancedEarlyStopping:
    """
    Enhanced early stopping mechanism for PPO training.
    
    Implements multiple criteria for early stopping including KL divergence,
    entropy, value loss, and performance plateaus.
    """
    
    def __init__(self, config: EarlyStoppingConfig):
        """
        Initialize early stopping mechanism.
        
        Args:
            config: Early stopping configuration
        """
        self.config = config
        
        # History tracking
        self.kl_history = []
        self.entropy_history = []
        self.value_loss_history = []
        self.performance_history = []
        
        # Patience counters
        self.value_loss_patience_counter = 0
        self.performance_patience_counter = 0
        
        # State
        self.training_steps = 0
        self.best_performance = float('-inf')
        
    def should_stop(self, metrics: Dict[str, float]) -> Tuple[bool, str]:
        """
        Check if training should stop early.
        
        Args:
            metrics: Current training metrics
            
        Returns:
            Tuple of (should_stop, reason)
        """
        self.training_steps += 1
        
        # Don't stop before minimum training steps
        if self.training_steps < self.config.min_training_steps:
            return False, ""
            
        # Check every N steps
        if self.training_steps % self.config.check_frequency != 0:
            return False, ""
            
        # Update histories
        self._update_histories(metrics)
        
        # Check KL divergence
        if self._check_kl_divergence():
            return True, "KL divergence exceeded threshold"
            
        # Check entropy
        if self._check_entropy():
            return True, "Policy entropy too low"
            
        # Check value loss
        if self._check_value_loss():
            return True, "Value loss plateau"
            
        # Check performance plateau
        if self._check_performance_plateau(metrics):
            return True, "Performance plateau"
            
        return False, ""
        
    def _update_histories(self, metrics: Dict[str, float]):
        """Update metric histories."""
        if 'kl_divergence' in metrics:
            self.kl_history.append(metrics['kl_divergence'])
            if len(self.kl_history) > self.config.kl_window_size:
                self.kl_history = self.kl_history[-self.config.kl_window_size:]
                
        if 'entropy' in metrics:
            self.entropy_history.append(metrics['entropy'])
            if len(self.entropy_history) > self.config.entropy_window_size:
                self.entropy_history = self.entropy_history[-self.config.entropy_window_size:]
                
        if 'value_loss' in metrics:
            self.value_loss_history.append(metrics['value_loss'])
            
    def _check_kl_divergence(self) -> bool:
        """Check if KL divergence is too high."""
        if len(self.kl_history) < self.config.kl_window_size:
            return False
            
        avg_kl = np.mean(self.kl_history)
        return avg_kl > self.config.target_kl * self.config.kl_tolerance
        
    def _check_entropy(self) -> bool:
        """Check if entropy is too low."""
        if len(self.entropy_history) < self.config.entropy_window_size:
            return False
            
        avg_entropy = np.mean(self.entropy_history)
        return avg_entropy < self.config.min_entropy
        
    def _check_value_loss(self) -> bool:
        """Check for value loss plateau."""
        if len(self.value_loss_history) < self.config.value_loss_patience:
            return False
            
        recent_losses = self.value_loss_history[-self.config.value_loss_patience:]
        
        # Check if all recent losses are above threshold
        if all(loss > self.config.value_loss_threshold for loss in recent_losses):
            self.value_loss_patience_counter += 1
        else:
            self.value_loss_patience_counter = 0
            
        return self.value_loss_patience_counter >= self.config.value_loss_patience
        
    def _check_performance_plateau(self, metrics: Dict[str, float]) -> bool:
        """Check for performance plateau."""
        # Use episode reward or other performance metric
        performance = metrics.get('episode_reward', metrics.get('policy_loss', 0))
        self.performance_history.append(performance)
        
        if len(self.performance_history) < self.config.performance_patience:
            return False
            
        # Check if performance has improved
        if performance > self.best_performance + self.config.performance_plateau_threshold:
            self.best_performance = performance
            self.performance_patience_counter = 0
        else:
            self.performance_patience_counter += 1
            
        return self.performance_patience_counter >= self.config.performance_patience
        
    def reset(self):
        """Reset early stopping state."""
        self.kl_history.clear()
        self.entropy_history.clear()
        self.value_loss_history.clear()
        self.performance_history.clear()
        self.value_loss_patience_counter = 0
        self.performance_patience_counter = 0
        self.training_steps = 0
        self.best_performance = float('-inf')


class PPOCheckpointManager:
    """
    Specialized checkpoint manager for PPO agents.
    
    Handles saving and loading of PPO models with training state,
    optimizer states, and performance tracking.
    """
    
    def __init__(self, checkpoint_dir: str, config: CheckpointConfig):
        """
        Initialize checkpoint manager.
        
        Args:
            checkpoint_dir: Directory to save checkpoints
            config: Checkpoint configuration
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.config = config
        
        # Create checkpoint directory
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # State tracking
        self.checkpoint_count = 0
        self.best_metric_value = float('-inf') if 'reward' in config.metric_for_best else float('inf')
        self.checkpoint_history = []
        
    def save_checkpoint(self, 
                       agent: PPOAgent, 
                       trainer: PPOTrainer,
                       metrics: Dict[str, float],
                       episode: int) -> str:
        """
        Save PPO checkpoint.
        
        Args:
            agent: PPO agent to save
            trainer: PPO trainer to save
            metrics: Current training metrics
            episode: Current episode number
            
        Returns:
            Path to saved checkpoint
        """
        # Check if we should save this checkpoint
        if not self._should_save_checkpoint(metrics):
            return ""
            
        # Create checkpoint data
        checkpoint_data = {
            'episode': episode,
            'metrics': metrics,
            'timestamp': time.time(),
            
            # Agent state
            'agent_config': agent.config,
            'policy_network_state_dict': agent.policy_network.state_dict(),
            'value_network_state_dict': agent.value_network.state_dict(),
            
            # Training state
            'training_step': trainer.training_step,
            'training_metrics_history': trainer.training_metrics[-100:],  # Last 100 steps
        }
        
        # Add optimizer states if requested
        if self.config.save_optimizer_state:
            checkpoint_data.update({
                'policy_optimizer_state_dict': agent.policy_network.optimizer.state_dict(),
                'value_optimizer_state_dict': agent.value_network.optimizer.state_dict(),
            })
            
        # Add training state if requested
        if self.config.save_training_state:
            checkpoint_data.update({
                'lr_scheduler_state': {
                    'step_count': trainer.lr_scheduler.step_count,
                    'initial_lr': trainer.lr_scheduler.initial_lr
                },
                'clip_scheduler_state': {
                    'step_count': trainer.clip_scheduler.step_count,
                    'kl_history': trainer.clip_scheduler.kl_history.copy()
                }
            })
            
        # Generate checkpoint filename
        checkpoint_filename = f"ppo_checkpoint_ep{episode:06d}_step{trainer.training_step:08d}.pth"
        checkpoint_path = self.checkpoint_dir / checkpoint_filename
        
        # Save checkpoint
        if self.config.compress_checkpoints:
            torch.save(checkpoint_data, checkpoint_path, _use_new_zipfile_serialization=True)
        else:
            torch.save(checkpoint_data, checkpoint_path)
            
        # Update tracking
        self.checkpoint_count += 1
        self.checkpoint_history.append({
            'path': checkpoint_path,
            'episode': episode,
            'metrics': metrics.copy(),
            'timestamp': time.time()
        })
        
        # Clean up old checkpoints
        self._cleanup_old_checkpoints()
        
        return str(checkpoint_path)
        
    def load_checkpoint(self, 
                       checkpoint_path: str, 
                       agent: PPOAgent, 
                       trainer: Optional[PPOTrainer] = None) -> Dict[str, Any]:
        """
        Load PPO checkpoint.
        
        Args:
            checkpoint_path: Path to checkpoint file
            agent: PPO agent to load into
            trainer: Optional PPO trainer to load into
            
        Returns:
            Checkpoint metadata
        """
        checkpoint_data = torch.load(checkpoint_path, map_location=agent.device, weights_only=False)
        
        # Load agent state
        agent.policy_network.load_state_dict(checkpoint_data['policy_network_state_dict'])
        agent.value_network.load_state_dict(checkpoint_data['value_network_state_dict'])
        
        # Load optimizer states if available
        if 'policy_optimizer_state_dict' in checkpoint_data:
            agent.policy_network.optimizer.load_state_dict(checkpoint_data['policy_optimizer_state_dict'])
        if 'value_optimizer_state_dict' in checkpoint_data:
            agent.value_network.optimizer.load_state_dict(checkpoint_data['value_optimizer_state_dict'])
            
        # Load trainer state if available and trainer provided
        if trainer is not None and 'training_step' in checkpoint_data:
            trainer.training_step = checkpoint_data['training_step']
            
            if 'training_metrics_history' in checkpoint_data:
                trainer.training_metrics = checkpoint_data['training_metrics_history']
                
            # Load scheduler states
            if 'lr_scheduler_state' in checkpoint_data:
                lr_state = checkpoint_data['lr_scheduler_state']
                trainer.lr_scheduler.step_count = lr_state['step_count']
                
            if 'clip_scheduler_state' in checkpoint_data:
                clip_state = checkpoint_data['clip_scheduler_state']
                trainer.clip_scheduler.step_count = clip_state['step_count']
                trainer.clip_scheduler.kl_history = clip_state['kl_history']
                
        return {
            'episode': checkpoint_data.get('episode', 0),
            'metrics': checkpoint_data.get('metrics', {}),
            'timestamp': checkpoint_data.get('timestamp', 0)
        }
        
    def _should_save_checkpoint(self, metrics: Dict[str, float]) -> bool:
        """Check if checkpoint should be saved."""
        # Always save based on frequency
        if self.checkpoint_count % self.config.save_frequency == 0:
            return True
            
        # Save if best performance (if enabled)
        if self.config.save_best_only:
            metric_value = metrics.get(self.config.metric_for_best, 0)
            
            if 'reward' in self.config.metric_for_best:
                # Higher is better for rewards
                if metric_value > self.best_metric_value:
                    self.best_metric_value = metric_value
                    return True
            else:
                # Lower is better for losses
                if metric_value < self.best_metric_value:
                    self.best_metric_value = metric_value
                    return True
                    
        return False
        
    def _cleanup_old_checkpoints(self):
        """Remove old checkpoints to stay within limit."""
        if len(self.checkpoint_history) <= self.config.max_checkpoints:
            return
            
        # Sort by timestamp and remove oldest
        self.checkpoint_history.sort(key=lambda x: x['timestamp'])
        
        while len(self.checkpoint_history) > self.config.max_checkpoints:
            old_checkpoint = self.checkpoint_history.pop(0)
            
            # Remove file if it exists
            if os.path.exists(old_checkpoint['path']):
                os.remove(old_checkpoint['path'])
                
    def get_best_checkpoint(self) -> Optional[str]:
        """Get path to best checkpoint."""
        if not self.checkpoint_history:
            return None
            
        # Find best checkpoint based on metric
        best_checkpoint = None
        best_value = float('-inf') if 'reward' in self.config.metric_for_best else float('inf')
        
        for checkpoint in self.checkpoint_history:
            metric_value = checkpoint['metrics'].get(self.config.metric_for_best, 0)
            
            if 'reward' in self.config.metric_for_best:
                if metric_value > best_value:
                    best_value = metric_value
                    best_checkpoint = checkpoint
            else:
                if metric_value < best_value:
                    best_value = metric_value
                    best_checkpoint = checkpoint
                    
        return str(best_checkpoint['path']) if best_checkpoint else None
        
    def get_latest_checkpoint(self) -> Optional[str]:
        """Get path to latest checkpoint."""
        if not self.checkpoint_history:
            return None
            
        latest = max(self.checkpoint_history, key=lambda x: x['timestamp'])
        return str(latest['path'])
        
    def list_checkpoints(self) -> List[Dict[str, Any]]:
        """List all available checkpoints."""
        return self.checkpoint_history.copy()
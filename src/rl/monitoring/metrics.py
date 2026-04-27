"""
RL Metrics Tracking System

This module provides comprehensive metrics tracking for RL training
and inference with support for real-time monitoring and analysis.
"""

from typing import Dict, List, Any, Optional
from collections import defaultdict, deque
import numpy as np
from datetime import datetime, timedelta
import json
from pathlib import Path


class MetricsTracker:
    """
    Comprehensive metrics tracking system for RL training and inference.
    
    Tracks training progress, performance metrics, and system statistics
    with support for real-time monitoring and historical analysis.
    """
    
    def __init__(self, window_size: int = 100, save_dir: Optional[str] = None):
        self.window_size = window_size
        self.save_dir = Path(save_dir) if save_dir else None
        
        # Training metrics
        self.training_metrics = defaultdict(list)
        self.episode_rewards = deque(maxlen=window_size)
        self.episode_losses = deque(maxlen=window_size)
        self.episode_lengths = deque(maxlen=window_size)
        self.epsilon_history = deque(maxlen=window_size)
        
        # Performance metrics
        self.performance_metrics = defaultdict(list)
        self.rolling_returns = deque(maxlen=window_size)
        self.rolling_sharpe = deque(maxlen=window_size)
        self.rolling_drawdown = deque(maxlen=window_size)
        
        # System metrics
        self.system_metrics = defaultdict(list)
        self.inference_times = deque(maxlen=window_size)
        self.memory_usage = deque(maxlen=window_size)
        
        # Timestamps
        self.start_time = datetime.now()
        self.last_update = datetime.now()
        
    def record_training_episode(self, episode: int, reward: float, loss: float,
                              epsilon: float, episode_length: int) -> None:
        """Record training episode metrics."""
        timestamp = datetime.now()
        
        # Store in history
        self.episode_rewards.append(reward)
        self.episode_losses.append(loss)
        self.episode_lengths.append(episode_length)
        self.epsilon_history.append(epsilon)
        
        # Store detailed metrics
        self.training_metrics['episodes'].append(episode)
        self.training_metrics['rewards'].append(reward)
        self.training_metrics['losses'].append(loss)
        self.training_metrics['epsilons'].append(epsilon)
        self.training_metrics['lengths'].append(episode_length)
        self.training_metrics['timestamps'].append(timestamp)
        
        self.last_update = timestamp
        
    def record_performance_metrics(self, returns: float, sharpe_ratio: float,
                                 max_drawdown: float, win_rate: float,
                                 profit_factor: float) -> None:
        """Record performance metrics."""
        timestamp = datetime.now()
        
        # Store in rolling windows
        self.rolling_returns.append(returns)
        self.rolling_sharpe.append(sharpe_ratio)
        self.rolling_drawdown.append(max_drawdown)
        
        # Store detailed metrics
        self.performance_metrics['returns'].append(returns)
        self.performance_metrics['sharpe_ratios'].append(sharpe_ratio)
        self.performance_metrics['max_drawdowns'].append(max_drawdown)
        self.performance_metrics['win_rates'].append(win_rate)
        self.performance_metrics['profit_factors'].append(profit_factor)
        self.performance_metrics['timestamps'].append(timestamp)
        
        self.last_update = timestamp
        
    def record_system_metrics(self, inference_time: float, memory_mb: float,
                            cpu_usage: float, gpu_usage: Optional[float] = None) -> None:
        """Record system performance metrics."""
        timestamp = datetime.now()
        
        # Store in rolling windows
        self.inference_times.append(inference_time)
        self.memory_usage.append(memory_mb)
        
        # Store detailed metrics
        self.system_metrics['inference_times'].append(inference_time)
        self.system_metrics['memory_usage'].append(memory_mb)
        self.system_metrics['cpu_usage'].append(cpu_usage)
        if gpu_usage is not None:
            self.system_metrics['gpu_usage'].append(gpu_usage)
        self.system_metrics['timestamps'].append(timestamp)
        
        self.last_update = timestamp
        
    def get_training_summary(self) -> Dict[str, Any]:
        """Get summary of training metrics."""
        if not self.episode_rewards:
            return {}
            
        return {
            'total_episodes': len(self.episode_rewards),
            'avg_reward': np.mean(self.episode_rewards),
            'std_reward': np.std(self.episode_rewards),
            'max_reward': np.max(self.episode_rewards),
            'min_reward': np.min(self.episode_rewards),
            'avg_loss': np.mean(self.episode_losses) if self.episode_losses else 0,
            'current_epsilon': self.epsilon_history[-1] if self.epsilon_history else 0,
            'avg_episode_length': np.mean(self.episode_lengths),
            'training_duration': (self.last_update - self.start_time).total_seconds()
        }
        
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get summary of performance metrics."""
        if not self.rolling_returns:
            return {}
            
        return {
            'avg_returns': np.mean(self.rolling_returns),
            'std_returns': np.std(self.rolling_returns),
            'avg_sharpe': np.mean(self.rolling_sharpe),
            'avg_drawdown': np.mean(self.rolling_drawdown),
            'best_sharpe': np.max(self.rolling_sharpe),
            'worst_drawdown': np.max(self.rolling_drawdown),
            'consistency_score': self._calculate_consistency_score()
        }
        
    def get_system_summary(self) -> Dict[str, Any]:
        """Get summary of system metrics."""
        if not self.inference_times:
            return {}
            
        return {
            'avg_inference_time': np.mean(self.inference_times),
            'max_inference_time': np.max(self.inference_times),
            'avg_memory_usage': np.mean(self.memory_usage),
            'max_memory_usage': np.max(self.memory_usage),
            'system_uptime': (self.last_update - self.start_time).total_seconds()
        }
        
    def get_recent_performance(self, minutes: int = 60) -> Dict[str, Any]:
        """Get performance metrics for recent time period."""
        cutoff_time = datetime.now() - timedelta(minutes=minutes)
        
        # Filter recent metrics
        recent_indices = [
            i for i, ts in enumerate(self.performance_metrics['timestamps'])
            if ts >= cutoff_time
        ]
        
        if not recent_indices:
            return {}
            
        recent_returns = [self.performance_metrics['returns'][i] for i in recent_indices]
        recent_sharpe = [self.performance_metrics['sharpe_ratios'][i] for i in recent_indices]
        
        return {
            'period_minutes': minutes,
            'num_updates': len(recent_indices),
            'avg_returns': np.mean(recent_returns),
            'avg_sharpe': np.mean(recent_sharpe),
            'volatility': np.std(recent_returns)
        }
        
    def _calculate_consistency_score(self) -> float:
        """Calculate consistency score based on reward stability."""
        if len(self.episode_rewards) < 10:
            return 0.0
            
        # Calculate rolling average stability
        rewards = list(self.episode_rewards)
        rolling_means = []
        window = min(10, len(rewards) // 2)
        
        for i in range(window, len(rewards)):
            rolling_means.append(np.mean(rewards[i-window:i]))
            
        if len(rolling_means) < 2:
            return 0.0
            
        # Lower coefficient of variation = higher consistency
        cv = np.std(rolling_means) / (np.mean(rolling_means) + 1e-8)
        consistency = max(0, 1 - cv)
        
        return consistency
        
    def save_metrics(self, filename: Optional[str] = None) -> None:
        """Save all metrics to file."""
        if not self.save_dir:
            return
            
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"rl_metrics_{timestamp}.json"
            
        filepath = self.save_dir / filename
        
        metrics_data = {
            'training_metrics': {k: v for k, v in self.training_metrics.items()},
            'performance_metrics': {k: v for k, v in self.performance_metrics.items()},
            'system_metrics': {k: v for k, v in self.system_metrics.items()},
            'summary': {
                'training': self.get_training_summary(),
                'performance': self.get_performance_summary(),
                'system': self.get_system_summary()
            },
            'metadata': {
                'start_time': self.start_time.isoformat(),
                'last_update': self.last_update.isoformat(),
                'window_size': self.window_size
            }
        }
        
        # Convert datetime objects to strings for JSON serialization
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
            
        with open(filepath, 'w') as f:
            json.dump(metrics_data, f, indent=2, default=convert_datetime)
            
    def load_metrics(self, filename: str) -> None:
        """Load metrics from file."""
        if not self.save_dir:
            return
            
        filepath = self.save_dir / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"Metrics file not found: {filepath}")
            
        with open(filepath, 'r') as f:
            metrics_data = json.load(f)
            
        # Restore metrics
        self.training_metrics = defaultdict(list, metrics_data.get('training_metrics', {}))
        self.performance_metrics = defaultdict(list, metrics_data.get('performance_metrics', {}))
        self.system_metrics = defaultdict(list, metrics_data.get('system_metrics', {}))
        
        # Restore metadata
        metadata = metrics_data.get('metadata', {})
        if 'start_time' in metadata:
            self.start_time = datetime.fromisoformat(metadata['start_time'])
        if 'last_update' in metadata:
            self.last_update = datetime.fromisoformat(metadata['last_update'])
            
    def reset(self) -> None:
        """Reset all metrics."""
        self.training_metrics.clear()
        self.performance_metrics.clear()
        self.system_metrics.clear()
        
        self.episode_rewards.clear()
        self.episode_losses.clear()
        self.episode_lengths.clear()
        self.epsilon_history.clear()
        
        self.rolling_returns.clear()
        self.rolling_sharpe.clear()
        self.rolling_drawdown.clear()
        
        self.inference_times.clear()
        self.memory_usage.clear()
        
        self.start_time = datetime.now()
        self.last_update = datetime.now()
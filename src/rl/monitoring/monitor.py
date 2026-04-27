"""
RL Training Monitor

This module provides real-time monitoring capabilities for RL training
with early stopping, performance tracking, and alert generation.
"""

from typing import Dict, Any, Optional, Callable, List
import numpy as np
from datetime import datetime, timedelta
from collections import deque
import threading
import time

from .logger import RLLogger
from .metrics import MetricsTracker


class TrainingMonitor:
    """
    Real-time training monitor with early stopping and performance tracking.
    
    Monitors training progress, detects performance issues, and provides
    automated stopping criteria based on configurable thresholds.
    """
    
    def __init__(self, 
                 patience: int = 20,
                 min_improvement: float = 0.01,
                 check_frequency: int = 10,
                 logger: Optional[RLLogger] = None,
                 metrics_tracker: Optional[MetricsTracker] = None):
        
        self.patience = patience
        self.min_improvement = min_improvement
        self.check_frequency = check_frequency
        
        self.logger = logger or RLLogger()
        self.metrics_tracker = metrics_tracker or MetricsTracker()
        
        # Monitoring state
        self.best_performance = float('-inf')
        self.episodes_without_improvement = 0
        self.should_stop = False
        self.monitoring_active = False
        
        # Performance tracking
        self.performance_history = deque(maxlen=100)
        self.loss_history = deque(maxlen=100)
        self.reward_history = deque(maxlen=100)
        
        # Alert thresholds
        self.alert_thresholds = {
            'loss_spike': 2.0,  # Loss increase multiplier
            'reward_drop': 0.5,  # Reward decrease multiplier
            'training_stall': 50,  # Episodes without any change
            'memory_usage': 90,  # Memory usage percentage
            'inference_time': 1.0  # Seconds
        }
        
        # Callbacks
        self.callbacks = {
            'early_stop': [],
            'performance_alert': [],
            'training_complete': []
        }
        
    def start_monitoring(self) -> None:
        """Start monitoring training process."""
        self.monitoring_active = True
        self.should_stop = False
        self.best_performance = float('-inf')
        self.episodes_without_improvement = 0
        
        self.logger.log_system_event(
            "monitoring_start",
            "Training monitoring started",
            {
                "patience": self.patience,
                "min_improvement": self.min_improvement,
                "check_frequency": self.check_frequency
            }
        )
        
    def stop_monitoring(self) -> None:
        """Stop monitoring training process."""
        self.monitoring_active = False
        
        self.logger.log_system_event(
            "monitoring_stop",
            "Training monitoring stopped"
        )
        
    def update(self, episode: int, reward: float, loss: float, 
              performance_metric: float, **kwargs) -> bool:
        """
        Update monitor with training metrics.
        
        Args:
            episode: Current episode number
            reward: Episode reward
            loss: Training loss
            performance_metric: Main performance metric for early stopping
            **kwargs: Additional metrics
            
        Returns:
            True if training should continue, False if should stop
        """
        if not self.monitoring_active:
            return True
            
        # Update history
        self.reward_history.append(reward)
        self.loss_history.append(loss)
        self.performance_history.append(performance_metric)
        
        # Record metrics
        self.metrics_tracker.record_training_episode(
            episode, reward, loss, kwargs.get('epsilon', 0), kwargs.get('episode_length', 0)
        )
        
        # Check for early stopping
        if episode % self.check_frequency == 0:
            should_continue = self._check_early_stopping(episode, performance_metric)
            if not should_continue:
                return False
                
        # Check for alerts
        self._check_alerts(episode, reward, loss, **kwargs)
        
        return True
        
    def _check_early_stopping(self, episode: int, performance_metric: float) -> bool:
        """Check if training should stop early."""
        # Check for improvement
        if performance_metric > self.best_performance + self.min_improvement:
            self.best_performance = performance_metric
            self.episodes_without_improvement = 0
            
            self.logger.log_system_event(
                "performance_improvement",
                f"New best performance: {performance_metric:.4f}",
                {"episode": episode, "improvement": performance_metric - self.best_performance}
            )
            
        else:
            self.episodes_without_improvement += self.check_frequency
            
        # Check patience
        if self.episodes_without_improvement >= self.patience:
            self.should_stop = True
            
            self.logger.log_system_event(
                "early_stopping",
                f"Early stopping triggered after {self.episodes_without_improvement} episodes without improvement",
                {
                    "episode": episode,
                    "best_performance": self.best_performance,
                    "current_performance": performance_metric
                }
            )
            
            # Trigger callbacks
            for callback in self.callbacks['early_stop']:
                callback(episode, self.best_performance, performance_metric)
                
            return False
            
        return True
        
    def _check_alerts(self, episode: int, reward: float, loss: float, **kwargs) -> None:
        """Check for performance alerts."""
        alerts = []
        
        # Loss spike detection
        if len(self.loss_history) >= 10:
            recent_loss = np.mean(list(self.loss_history)[-5:])
            baseline_loss = np.mean(list(self.loss_history)[-10:-5])
            
            if recent_loss > baseline_loss * self.alert_thresholds['loss_spike']:
                alerts.append({
                    'type': 'loss_spike',
                    'message': f"Loss spike detected: {recent_loss:.4f} vs {baseline_loss:.4f}",
                    'severity': 'warning'
                })
                
        # Reward drop detection
        if len(self.reward_history) >= 10:
            recent_reward = np.mean(list(self.reward_history)[-5:])
            baseline_reward = np.mean(list(self.reward_history)[-10:-5])
            
            if recent_reward < baseline_reward * self.alert_thresholds['reward_drop']:
                alerts.append({
                    'type': 'reward_drop',
                    'message': f"Reward drop detected: {recent_reward:.4f} vs {baseline_reward:.4f}",
                    'severity': 'warning'
                })
                
        # Training stall detection
        if len(self.performance_history) >= self.alert_thresholds['training_stall']:
            recent_performance = list(self.performance_history)[-self.alert_thresholds['training_stall']:]
            if np.std(recent_performance) < 1e-6:
                alerts.append({
                    'type': 'training_stall',
                    'message': f"Training appears stalled for {self.alert_thresholds['training_stall']} episodes",
                    'severity': 'error'
                })
                
        # System resource alerts
        memory_usage = kwargs.get('memory_usage_percent', 0)
        if memory_usage > self.alert_thresholds['memory_usage']:
            alerts.append({
                'type': 'high_memory',
                'message': f"High memory usage: {memory_usage:.1f}%",
                'severity': 'warning'
            })
            
        inference_time = kwargs.get('inference_time', 0)
        if inference_time > self.alert_thresholds['inference_time']:
            alerts.append({
                'type': 'slow_inference',
                'message': f"Slow inference time: {inference_time:.3f}s",
                'severity': 'warning'
            })
            
        # Log alerts
        for alert in alerts:
            self.logger.log_system_event(
                f"alert_{alert['type']}",
                alert['message'],
                {
                    "episode": episode,
                    "severity": alert['severity'],
                    "alert_type": alert['type']
                }
            )
            
            # Trigger callbacks
            for callback in self.callbacks['performance_alert']:
                callback(alert, episode)
                
    def add_callback(self, event_type: str, callback: Callable) -> None:
        """
        Add callback for monitoring events.
        
        Args:
            event_type: Type of event ('early_stop', 'performance_alert', 'training_complete')
            callback: Callback function
        """
        if event_type in self.callbacks:
            self.callbacks[event_type].append(callback)
            
    def remove_callback(self, event_type: str, callback: Callable) -> None:
        """Remove callback for monitoring events."""
        if event_type in self.callbacks and callback in self.callbacks[event_type]:
            self.callbacks[event_type].remove(callback)
            
    def get_monitoring_summary(self) -> Dict[str, Any]:
        """Get summary of monitoring state."""
        return {
            'monitoring_active': self.monitoring_active,
            'should_stop': self.should_stop,
            'best_performance': self.best_performance,
            'episodes_without_improvement': self.episodes_without_improvement,
            'patience_remaining': max(0, self.patience - self.episodes_without_improvement),
            'recent_performance': {
                'avg_reward': np.mean(self.reward_history) if self.reward_history else 0,
                'avg_loss': np.mean(self.loss_history) if self.loss_history else 0,
                'performance_trend': self._calculate_trend(self.performance_history)
            }
        }
        
    def _calculate_trend(self, values: deque) -> str:
        """Calculate trend direction for values."""
        if len(values) < 10:
            return "insufficient_data"
            
        recent = list(values)[-10:]
        first_half = np.mean(recent[:5])
        second_half = np.mean(recent[5:])
        
        if second_half > first_half * 1.05:
            return "improving"
        elif second_half < first_half * 0.95:
            return "declining"
        else:
            return "stable"
            
    def set_alert_threshold(self, alert_type: str, threshold: float) -> None:
        """Set custom alert threshold."""
        if alert_type in self.alert_thresholds:
            self.alert_thresholds[alert_type] = threshold
            self.logger.log_system_event(
                "threshold_update",
                f"Updated {alert_type} threshold to {threshold}"
            )
            
    def reset(self) -> None:
        """Reset monitoring state."""
        self.best_performance = float('-inf')
        self.episodes_without_improvement = 0
        self.should_stop = False
        
        self.performance_history.clear()
        self.loss_history.clear()
        self.reward_history.clear()
        
        self.logger.log_system_event("monitor_reset", "Training monitor reset")
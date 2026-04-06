"""
Model Checkpointing and Persistence Manager

This module provides comprehensive model checkpointing, versioning, and
validation capabilities for RL agents.
"""

import os
import json
import torch
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
import logging
from enum import Enum

from .base import RLAgent


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder for handling special types."""
    
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if hasattr(obj, '__dict__'):
            return obj.__dict__
        return super().default(obj)


@dataclass
class CheckpointMetadata:
    """Metadata for model checkpoints."""
    checkpoint_id: str
    agent_type: str
    timestamp: datetime
    episode: int
    training_step: int
    performance_metrics: Dict[str, float]
    config: Dict[str, Any]
    version: str = "1.0"
    description: str = ""
    tags: List[str] = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


@dataclass
class ValidationResult:
    """Result of model validation."""
    is_valid: bool
    validation_score: float
    metrics: Dict[str, float]
    errors: List[str]
    warnings: List[str]


class CheckpointManager:
    """
    Manages model checkpoints with versioning, validation, and metadata tracking.
    
    Features:
    - Automatic checkpoint versioning
    - Model validation before saving
    - Performance tracking and comparison
    - Checkpoint cleanup and retention policies
    - Resume training from checkpoints
    """
    
    def __init__(self, 
                 checkpoint_dir: str,
                 max_checkpoints: int = 10,
                 validation_threshold: float = 0.0,
                 auto_cleanup: bool = True):
        """
        Initialize checkpoint manager.
        
        Args:
            checkpoint_dir: Directory to store checkpoints
            max_checkpoints: Maximum number of checkpoints to keep
            validation_threshold: Minimum validation score to save checkpoint
            auto_cleanup: Whether to automatically clean up old checkpoints
        """
        self.checkpoint_dir = Path(checkpoint_dir)
        self.max_checkpoints = max_checkpoints
        self.validation_threshold = validation_threshold
        self.auto_cleanup = auto_cleanup
        
        # Create checkpoint directory
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        
        # Setup logging
        self.logger = logging.getLogger(__name__)
        
        # Load existing checkpoints
        self.checkpoints = self._load_checkpoint_registry()
        
    def save_checkpoint(self,
                       agent: RLAgent,
                       episode: int,
                       performance_metrics: Dict[str, float],
                       description: str = "",
                       tags: List[str] = None,
                       validate: bool = True) -> Optional[str]:
        """
        Save agent checkpoint with metadata.
        
        Args:
            agent: RL agent to save
            episode: Current episode number
            performance_metrics: Performance metrics for this checkpoint
            description: Optional description
            tags: Optional tags for categorization
            validate: Whether to validate model before saving
            
        Returns:
            Checkpoint ID if saved successfully, None otherwise
        """
        try:
            # Generate checkpoint ID
            timestamp = datetime.now()
            checkpoint_id = f"{agent.__class__.__name__}_{timestamp.strftime('%Y%m%d_%H%M%S')}_{episode}"
            
            # Validate model if requested
            if validate:
                validation_result = self._validate_model(agent, performance_metrics)
                if not validation_result.is_valid:
                    self.logger.warning(f"Model validation failed: {validation_result.errors}")
                    return None
                    
                if validation_result.validation_score < self.validation_threshold:
                    self.logger.info(f"Model validation score {validation_result.validation_score} "
                                   f"below threshold {self.validation_threshold}")
                    return None
            
            # Create checkpoint metadata
            metadata = CheckpointMetadata(
                checkpoint_id=checkpoint_id,
                agent_type=agent.__class__.__name__,
                timestamp=timestamp,
                episode=episode,
                training_step=agent.training_step,
                performance_metrics=performance_metrics,
                config=agent.config.__dict__ if hasattr(agent.config, '__dict__') else {},
                description=description,
                tags=tags or []
            )
            
            # Create checkpoint directory
            checkpoint_path = self.checkpoint_dir / checkpoint_id
            checkpoint_path.mkdir(exist_ok=True)
            
            # Save model
            model_path = checkpoint_path / "model.pth"
            agent.save_model(str(model_path))
            
            # Save metadata
            metadata_path = checkpoint_path / "metadata.json"
            with open(metadata_path, 'w') as f:
                # Convert datetime to string for JSON serialization
                metadata_dict = asdict(metadata)
                metadata_dict['timestamp'] = metadata.timestamp.isoformat()
                json.dump(metadata_dict, f, indent=2, cls=CustomJSONEncoder)
            
            # Update registry
            self.checkpoints[checkpoint_id] = metadata
            self._save_checkpoint_registry()
            
            # Cleanup old checkpoints if needed
            if self.auto_cleanup:
                self._cleanup_checkpoints()
            
            self.logger.info(f"Saved checkpoint: {checkpoint_id}")
            return checkpoint_id
            
        except Exception as e:
            self.logger.error(f"Failed to save checkpoint: {e}")
            return None
    
    def load_checkpoint(self, 
                       agent: RLAgent, 
                       checkpoint_id: str,
                       strict: bool = True) -> bool:
        """
        Load agent from checkpoint.
        
        Args:
            agent: RL agent to load into
            checkpoint_id: ID of checkpoint to load
            strict: Whether to enforce strict loading
            
        Returns:
            True if loaded successfully, False otherwise
        """
        try:
            if checkpoint_id not in self.checkpoints:
                self.logger.error(f"Checkpoint {checkpoint_id} not found")
                return False
            
            checkpoint_path = self.checkpoint_dir / checkpoint_id
            model_path = checkpoint_path / "model.pth"
            
            if not model_path.exists():
                self.logger.error(f"Model file not found: {model_path}")
                return False
            
            # Load model
            agent.load_model(str(model_path))
            
            # Load and validate metadata
            metadata = self.checkpoints[checkpoint_id]
            if strict and metadata.agent_type != agent.__class__.__name__:
                self.logger.error(f"Agent type mismatch: expected {metadata.agent_type}, "
                                f"got {agent.__class__.__name__}")
                return False
            
            self.logger.info(f"Loaded checkpoint: {checkpoint_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load checkpoint {checkpoint_id}: {e}")
            return False
    
    def get_best_checkpoint(self, 
                           metric: str = "total_return",
                           agent_type: Optional[str] = None) -> Optional[str]:
        """
        Get the checkpoint with the best performance for a given metric.
        
        Args:
            metric: Performance metric to optimize
            agent_type: Filter by agent type (optional)
            
        Returns:
            Checkpoint ID of best performing model
        """
        filtered_checkpoints = self.checkpoints
        
        if agent_type:
            filtered_checkpoints = {
                k: v for k, v in self.checkpoints.items() 
                if v.agent_type == agent_type
            }
        
        if not filtered_checkpoints:
            return None
        
        best_checkpoint = None
        best_score = float('-inf')
        
        for checkpoint_id, metadata in filtered_checkpoints.items():
            if metric in metadata.performance_metrics:
                score = metadata.performance_metrics[metric]
                if score > best_score:
                    best_score = score
                    best_checkpoint = checkpoint_id
        
        return best_checkpoint
    
    def get_latest_checkpoint(self, agent_type: Optional[str] = None) -> Optional[str]:
        """
        Get the most recent checkpoint.
        
        Args:
            agent_type: Filter by agent type (optional)
            
        Returns:
            Checkpoint ID of most recent model
        """
        filtered_checkpoints = self.checkpoints
        
        if agent_type:
            filtered_checkpoints = {
                k: v for k, v in self.checkpoints.items() 
                if v.agent_type == agent_type
            }
        
        if not filtered_checkpoints:
            return None
        
        latest_checkpoint = max(
            filtered_checkpoints.items(),
            key=lambda x: x[1].timestamp
        )
        
        return latest_checkpoint[0]
    
    def list_checkpoints(self, 
                        agent_type: Optional[str] = None,
                        tags: Optional[List[str]] = None) -> List[CheckpointMetadata]:
        """
        List available checkpoints with optional filtering.
        
        Args:
            agent_type: Filter by agent type
            tags: Filter by tags (must have all specified tags)
            
        Returns:
            List of checkpoint metadata
        """
        checkpoints = list(self.checkpoints.values())
        
        if agent_type:
            checkpoints = [c for c in checkpoints if c.agent_type == agent_type]
        
        if tags:
            checkpoints = [
                c for c in checkpoints 
                if all(tag in c.tags for tag in tags)
            ]
        
        # Sort by timestamp (newest first)
        checkpoints.sort(key=lambda x: x.timestamp, reverse=True)
        
        return checkpoints
    
    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Delete a checkpoint.
        
        Args:
            checkpoint_id: ID of checkpoint to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            if checkpoint_id not in self.checkpoints:
                self.logger.warning(f"Checkpoint {checkpoint_id} not found")
                return False
            
            # Remove checkpoint directory
            checkpoint_path = self.checkpoint_dir / checkpoint_id
            if checkpoint_path.exists():
                shutil.rmtree(checkpoint_path)
            
            # Remove from registry
            del self.checkpoints[checkpoint_id]
            self._save_checkpoint_registry()
            
            self.logger.info(f"Deleted checkpoint: {checkpoint_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to delete checkpoint {checkpoint_id}: {e}")
            return False
    
    def get_checkpoint_info(self, checkpoint_id: str) -> Optional[CheckpointMetadata]:
        """Get detailed information about a checkpoint."""
        return self.checkpoints.get(checkpoint_id)
    
    def compare_checkpoints(self, 
                           checkpoint_ids: List[str],
                           metrics: Optional[List[str]] = None) -> Dict[str, Dict[str, float]]:
        """
        Compare performance metrics across multiple checkpoints.
        
        Args:
            checkpoint_ids: List of checkpoint IDs to compare
            metrics: Specific metrics to compare (all if None)
            
        Returns:
            Dictionary mapping checkpoint IDs to their metrics
        """
        comparison = {}
        
        for checkpoint_id in checkpoint_ids:
            if checkpoint_id in self.checkpoints:
                metadata = self.checkpoints[checkpoint_id]
                if metrics:
                    comparison[checkpoint_id] = {
                        k: v for k, v in metadata.performance_metrics.items()
                        if k in metrics
                    }
                else:
                    comparison[checkpoint_id] = metadata.performance_metrics.copy()
        
        return comparison
    
    def _validate_model(self, 
                       agent: RLAgent, 
                       performance_metrics: Dict[str, float]) -> ValidationResult:
        """
        Validate model before saving checkpoint.
        
        Args:
            agent: Agent to validate
            performance_metrics: Current performance metrics
            
        Returns:
            Validation result
        """
        errors = []
        warnings = []
        validation_score = 0.0
        
        try:
            # Basic model validation
            model_info = agent.get_model_info()
            
            # Check if model has reasonable parameters
            if 'total_parameters' in model_info:
                param_count = model_info['total_parameters']
                if param_count == 0:
                    errors.append("Model has no parameters")
                elif param_count > 10_000_000:  # 10M parameters
                    warnings.append(f"Model has many parameters: {param_count}")
            
            # Check performance metrics
            if 'total_return' in performance_metrics:
                total_return = performance_metrics['total_return']
                validation_score = total_return
                
                if total_return < -1000:
                    warnings.append(f"Very low total return: {total_return}")
            
            # Check for NaN or infinite values in metrics
            for metric, value in performance_metrics.items():
                if not isinstance(value, (int, float)) or not (-1e10 < value < 1e10):
                    errors.append(f"Invalid metric value: {metric} = {value}")
            
            is_valid = len(errors) == 0
            
        except Exception as e:
            errors.append(f"Validation error: {e}")
            is_valid = False
        
        return ValidationResult(
            is_valid=is_valid,
            validation_score=validation_score,
            metrics=performance_metrics.copy(),
            errors=errors,
            warnings=warnings
        )
    
    def _cleanup_checkpoints(self) -> None:
        """Remove old checkpoints to maintain max_checkpoints limit."""
        if len(self.checkpoints) <= self.max_checkpoints:
            return
        
        # Sort checkpoints by timestamp (oldest first)
        sorted_checkpoints = sorted(
            self.checkpoints.items(),
            key=lambda x: x[1].timestamp
        )
        
        # Remove oldest checkpoints
        num_to_remove = len(self.checkpoints) - self.max_checkpoints
        for i in range(num_to_remove):
            checkpoint_id = sorted_checkpoints[i][0]
            self.delete_checkpoint(checkpoint_id)
    
    def _load_checkpoint_registry(self) -> Dict[str, CheckpointMetadata]:
        """Load checkpoint registry from disk."""
        registry_path = self.checkpoint_dir / "registry.json"
        
        if not registry_path.exists():
            return {}
        
        try:
            with open(registry_path, 'r') as f:
                registry_data = json.load(f)
            
            checkpoints = {}
            for checkpoint_id, data in registry_data.items():
                # Convert timestamp string back to datetime
                data['timestamp'] = datetime.fromisoformat(data['timestamp'])
                checkpoints[checkpoint_id] = CheckpointMetadata(**data)
            
            return checkpoints
            
        except Exception as e:
            self.logger.error(f"Failed to load checkpoint registry: {e}")
            return {}
    
    def _save_checkpoint_registry(self) -> None:
        """Save checkpoint registry to disk."""
        registry_path = self.checkpoint_dir / "registry.json"
        
        try:
            registry_data = {}
            for checkpoint_id, metadata in self.checkpoints.items():
                data = asdict(metadata)
                data['timestamp'] = metadata.timestamp.isoformat()
                registry_data[checkpoint_id] = data
            
            with open(registry_path, 'w') as f:
                json.dump(registry_data, f, indent=2, cls=CustomJSONEncoder)
                
        except Exception as e:
            self.logger.error(f"Failed to save checkpoint registry: {e}")


class PerformanceTracker:
    """
    Tracks training performance metrics over time.
    
    Features:
    - Real-time metric tracking
    - Performance trend analysis
    - Early stopping detection
    - Metric visualization data
    """
    
    def __init__(self, 
                 metrics_to_track: List[str] = None,
                 window_size: int = 100):
        """
        Initialize performance tracker.
        
        Args:
            metrics_to_track: List of metrics to track
            window_size: Window size for moving averages
        """
        self.metrics_to_track = metrics_to_track or [
            'episode_reward', 'episode_length', 'loss', 'epsilon'
        ]
        self.window_size = window_size
        
        # Storage for metrics
        self.metrics_history = {metric: [] for metric in self.metrics_to_track}
        self.episode_history = []
        self.timestamps = []
        
        # Performance statistics
        self.best_performance = {}
        self.worst_performance = {}
        self.moving_averages = {}
        
    def update(self, episode: int, metrics: Dict[str, float]) -> None:
        """
        Update performance metrics.
        
        Args:
            episode: Current episode number
            metrics: Dictionary of metric values
        """
        self.episode_history.append(episode)
        self.timestamps.append(datetime.now())
        
        for metric in self.metrics_to_track:
            if metric in metrics:
                value = metrics[metric]
                self.metrics_history[metric].append(value)
                
                # Update best/worst performance
                if metric not in self.best_performance or value > self.best_performance[metric]:
                    self.best_performance[metric] = value
                    
                if metric not in self.worst_performance or value < self.worst_performance[metric]:
                    self.worst_performance[metric] = value
                
                # Update moving average
                recent_values = self.metrics_history[metric][-self.window_size:]
                self.moving_averages[metric] = sum(recent_values) / len(recent_values)
            else:
                self.metrics_history[metric].append(None)
    
    def get_recent_performance(self, episodes: int = 10) -> Dict[str, float]:
        """Get average performance over recent episodes."""
        if len(self.episode_history) < episodes:
            episodes = len(self.episode_history)
        
        if episodes == 0:
            return {}
        
        recent_performance = {}
        for metric in self.metrics_to_track:
            recent_values = [
                v for v in self.metrics_history[metric][-episodes:] 
                if v is not None
            ]
            if recent_values:
                recent_performance[metric] = sum(recent_values) / len(recent_values)
        
        return recent_performance
    
    def is_improving(self, metric: str, episodes: int = 20) -> bool:
        """Check if a metric is improving over recent episodes."""
        if metric not in self.metrics_history:
            return False
        
        values = [
            v for v in self.metrics_history[metric][-episodes:] 
            if v is not None
        ]
        
        if len(values) < 2:
            return False
        
        # Simple trend analysis: compare first and second half
        mid = len(values) // 2
        first_half_avg = sum(values[:mid]) / mid
        second_half_avg = sum(values[mid:]) / (len(values) - mid)
        
        return second_half_avg > first_half_avg
    
    def should_stop_early(self, 
                         metric: str = 'episode_reward',
                         patience: int = 50,
                         min_improvement: float = 0.01) -> bool:
        """
        Determine if training should stop early due to lack of improvement.
        
        Args:
            metric: Metric to monitor for early stopping
            patience: Number of episodes to wait for improvement
            min_improvement: Minimum improvement threshold
            
        Returns:
            True if training should stop early
        """
        if metric not in self.metrics_history:
            return False
        
        values = [
            v for v in self.metrics_history[metric] 
            if v is not None
        ]
        
        if len(values) < patience:
            return False
        
        # Check if there's been improvement in the last 'patience' episodes
        recent_best = max(values[-patience:])
        overall_best = max(values[:-patience]) if len(values) > patience else float('-inf')
        
        improvement = recent_best - overall_best
        return improvement < min_improvement
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of performance tracking."""
        summary = {
            'total_episodes': len(self.episode_history),
            'metrics_tracked': self.metrics_to_track,
            'best_performance': self.best_performance.copy(),
            'worst_performance': self.worst_performance.copy(),
            'current_moving_averages': self.moving_averages.copy(),
            'recent_performance': self.get_recent_performance()
        }
        
        return summary
"""
RL-Specific Logging System

This module provides specialized logging capabilities for RL training,
inference, and system monitoring with structured logging support.
"""

import logging
import json
from pathlib import Path
from typing import Dict, Any, Optional
from datetime import datetime
import sys


class RLLogger:
    """
    Specialized logger for RL system with structured logging support.
    
    Provides separate loggers for training, inference, and system events
    with configurable output formats and destinations.
    """
    
    def __init__(self, log_dir: str = "logs/rl", log_level: str = "INFO"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Set up different loggers
        self.training_logger = self._setup_logger("rl.training", "training.log", log_level)
        self.inference_logger = self._setup_logger("rl.inference", "inference.log", log_level)
        self.system_logger = self._setup_logger("rl.system", "system.log", log_level)
        self.metrics_logger = self._setup_logger("rl.metrics", "metrics.log", log_level)
        
        # Main logger
        self.logger = self.system_logger
        
    def _setup_logger(self, name: str, filename: str, level: str) -> logging.Logger:
        """Set up individual logger with file and console handlers."""
        logger = logging.getLogger(name)
        logger.setLevel(getattr(logging, level.upper()))
        
        # Clear existing handlers
        logger.handlers.clear()
        
        # File handler
        file_handler = logging.FileHandler(self.log_dir / filename, encoding='utf-8')
        file_formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)
        
        # Console handler (only for system logger)
        if name == "rl.system":
            if hasattr(sys.stdout, 'reconfigure'):
                try:
                    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
                except Exception:
                    pass
            console_handler = logging.StreamHandler(sys.stdout)
            console_formatter = logging.Formatter(
                '%(asctime)s - RL - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            logger.addHandler(console_handler)
            
        return logger
        
    def log_training_start(self, agent_type: str, config: Dict[str, Any]) -> None:
        """Log training session start."""
        self.training_logger.info(f"Starting training for {agent_type} agent")
        self.training_logger.info(f"Training configuration: {json.dumps(config, indent=2)}")
        
    def log_training_episode(self, episode: int, reward: float, loss: float, 
                           epsilon: float, duration: float) -> None:
        """Log training episode metrics."""
        metrics = {
            "episode": episode,
            "reward": reward,
            "loss": loss,
            "epsilon": epsilon,
            "duration": duration,
            "timestamp": datetime.now().isoformat()
        }
        self.training_logger.info(f"Episode {episode}: {json.dumps(metrics)}")
        
    def log_training_checkpoint(self, episode: int, model_path: str, 
                              performance: Dict[str, float]) -> None:
        """Log training checkpoint save."""
        checkpoint_info = {
            "episode": episode,
            "model_path": model_path,
            "performance": performance,
            "timestamp": datetime.now().isoformat()
        }
        self.training_logger.info(f"Checkpoint saved: {json.dumps(checkpoint_info)}")
        
    def log_training_end(self, total_episodes: int, final_performance: Dict[str, float],
                        training_time: float) -> None:
        """Log training session end."""
        summary = {
            "total_episodes": total_episodes,
            "final_performance": final_performance,
            "training_time": training_time,
            "timestamp": datetime.now().isoformat()
        }
        self.training_logger.info(f"Training completed: {json.dumps(summary)}")
        
    def log_inference_start(self, agent_id: str, model_path: str) -> None:
        """Log inference session start."""
        self.inference_logger.info(f"Starting inference with agent {agent_id}")
        self.inference_logger.info(f"Model path: {model_path}")
        
    def log_inference_action(self, state: Dict[str, Any], action: int, 
                           confidence: float, timestamp: datetime) -> None:
        """Log inference action selection."""
        action_info = {
            "action": action,
            "confidence": confidence,
            "timestamp": timestamp.isoformat(),
            "state_summary": self._summarize_state(state)
        }
        self.inference_logger.debug(f"Action selected: {json.dumps(action_info)}")
        
    def log_inference_performance(self, period: str, metrics: Dict[str, float]) -> None:
        """Log inference performance metrics."""
        performance_info = {
            "period": period,
            "metrics": metrics,
            "timestamp": datetime.now().isoformat()
        }
        self.inference_logger.info(f"Performance update: {json.dumps(performance_info)}")
        
    def log_system_event(self, event_type: str, message: str, 
                        details: Optional[Dict[str, Any]] = None) -> None:
        """Log system events."""
        event_info = {
            "event_type": event_type,
            "message": message,
            "details": details or {},
            "timestamp": datetime.now().isoformat()
        }
        self.system_logger.info(f"System event: {json.dumps(event_info)}")
        
    def log_error(self, error_type: str, error_message: str, 
                 context: Optional[Dict[str, Any]] = None) -> None:
        """Log errors with context."""
        error_info = {
            "error_type": error_type,
            "error_message": error_message,
            "context": context or {},
            "timestamp": datetime.now().isoformat()
        }
        self.system_logger.error(f"Error occurred: {json.dumps(error_info)}")
        
    def log_metrics(self, metric_type: str, metrics: Dict[str, float], 
                   timestamp: Optional[datetime] = None) -> None:
        """Log structured metrics."""
        if timestamp is None:
            timestamp = datetime.now()
            
        metrics_info = {
            "metric_type": metric_type,
            "metrics": metrics,
            "timestamp": timestamp.isoformat()
        }
        self.metrics_logger.info(json.dumps(metrics_info))
        
    def _summarize_state(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Create summary of state for logging."""
        return {
            "num_features": len(state.get("features", [])),
            "portfolio_value": state.get("portfolio_value"),
            "current_position": state.get("current_position"),
            "market_session": state.get("market_session")
        }
        
    def info(self, message: str) -> None:
        """Log info message."""
        self.logger.info(message)
        
    def warning(self, message: str) -> None:
        """Log warning message."""
        self.logger.warning(message)
        
    def error(self, message: str) -> None:
        """Log error message."""
        self.logger.error(message)
        
    def debug(self, message: str) -> None:
        """Log debug message."""
        self.logger.debug(message)

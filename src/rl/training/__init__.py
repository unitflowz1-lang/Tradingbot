"""
RL Training Module

This module provides comprehensive training orchestration, configuration management,
and progress tracking for reinforcement learning agents.
"""

from .agent_trainer import (
    AgentTrainer,
    TrainingConfig,
    TrainingMetrics,
    TrainingCallback,
    LoggingCallback,
    TensorBoardCallback,
    CheckpointCallback
)

from .config_manager import (
    ConfigManager,
    HyperparameterRange,
    ExperimentConfig,
    ConfigValidator
)

from .progress_tracker import (
    ProgressTracker,
    PerformanceAnalyzer,
    ProgressSnapshot
)

from .hyperparameter_optimizer import (
    HyperparameterOptimizer,
    OptimizationConfig,
    RLObjectiveFunction,
    OptimizationManager,
    TrialResult
)

from .resource_manager import (
    ResourceManager,
    ResourceMonitor,
    ResourceAllocator,
    ResourceLimits,
    ResourceUsage,
    ResourceMetrics,
    ScalingDecision,
)

__all__ = [
    # Agent Trainer
    'AgentTrainer',
    'TrainingConfig',
    'TrainingMetrics',
    'TrainingCallback',
    'LoggingCallback',
    'TensorBoardCallback',
    'CheckpointCallback',
    
    # Configuration Management
    'ConfigManager',
    'HyperparameterRange',
    'ExperimentConfig',
    'ConfigValidator',
    
    # Progress Tracking
    'ProgressTracker',
    'PerformanceAnalyzer',
    'ProgressSnapshot',
    
    # Hyperparameter Optimization
    'HyperparameterOptimizer',
    'OptimizationConfig',
    'RLObjectiveFunction',
    'OptimizationManager',
    'TrialResult',
    
    # Resource Management
    'ResourceManager',
    'ResourceMonitor',
    'ResourceAllocator',
    'ResourceLimits',
    'ResourceUsage',
    'ResourceMetrics',
    'ScalingDecision',
]

# Version information
__version__ = "1.0.0"
__author__ = "AI Trading Bot Team"
__description__ = "Comprehensive RL training orchestration and management system"

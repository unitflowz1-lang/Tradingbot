"""
Reinforcement Learning Trading System

This module provides a comprehensive RL framework for forex trading,
including environments, agents, training pipelines, and strategy management.
"""

__version__ = "1.0.0"
__author__ = "RL Trading System"

# Core components
from .environments import TradingEnvironment, ForexTradingEnvironment, EnvironmentConfig, ActionType
from .agents import RLAgent, DQNAgent, PPOAgent
from .training import AgentTrainer
from .strategies import StrategyRegistry

__all__ = [
    "TradingEnvironment",
    "ForexTradingEnvironment",
    "EnvironmentConfig", 
    "ActionType",
    "RLAgent", 
    "DQNAgent",
    "PPOAgent",
    "AgentTrainer",
    "StrategyRegistry"
]
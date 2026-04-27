# RL Trading System Framework

This directory contains the Reinforcement Learning (RL) framework for the AI Forex Trading Bot. The framework provides a comprehensive solution for training, deploying, and managing RL agents that learn optimal trading strategies through market interaction.

## Architecture Overview

The RL framework is organized into the following main components:

### Core Components

- **`environments/`** - Trading environment implementations
  - `base.py` - Abstract base class for trading environments
  - `state_processor.py` - Market data to state vector conversion
  - `reward_calculator.py` - Multi-objective reward function implementations

- **`agents/`** - RL agent implementations
  - `base.py` - Abstract base class for RL agents
  - `dqn.py` - Deep Q-Network agent implementation
  - `ppo.py` - Proximal Policy Optimization agent implementation
  - `networks.py` - Neural network architectures

- **`training/`** - Training pipeline and optimization
  - `trainer.py` - Agent training orchestration
  - `optimizer.py` - Hyperparameter optimization
  - `validator.py` - Model validation and testing

- **`strategies/`** - Strategy management system
  - `registry.py` - Strategy registry and versioning
  - `allocator.py` - Dynamic capital allocation
  - `testing.py` - A/B testing framework

- **`config/`** - Configuration management
  - `base.py` - Core configuration classes
  - `manager.py` - Configuration loading and management
  - `hyperparameters.py` - Hyperparameter search spaces

- **`monitoring/`** - Logging and monitoring framework
  - `logger.py` - Specialized RL logging system
  - `metrics.py` - Comprehensive metrics tracking
  - `monitor.py` - Real-time training monitoring

## Key Features

### 1. Multiple RL Algorithms
- **DQN (Deep Q-Networks)**: Value-based learning with experience replay
- **PPO (Proximal Policy Optimization)**: Policy gradient method with stable updates

### 2. Comprehensive Environment Design
- OpenAI Gym compatible interface
- Multi-objective reward functions (profit, Sharpe ratio, drawdown)
- Configurable state spaces with market data, technical indicators, and portfolio features
- Support for discrete and continuous action spaces

### 3. Advanced Training Pipeline
- Automated hyperparameter optimization using Optuna
- Early stopping and performance monitoring
- Model checkpointing and versioning
- Distributed training support

### 4. Production-Ready Features
- Strategy registry with A/B testing
- Dynamic capital allocation across multiple agents
- Real-time performance monitoring
- Comprehensive logging and metrics tracking
- Integration with existing MT5 infrastructure

### 5. Configuration Management
- JSON-based configuration files
- Environment variable overrides
- Runtime configuration updates
- Hyperparameter search space definitions

## Getting Started

### 1. Configuration

The RL system uses a hierarchical configuration system. The main configuration file is located at `config/rl_config.json`. You can customize:

- Training parameters (learning rate, batch size, episodes)
- Network architecture (hidden layers, activation functions)
- Environment settings (lookback window, reward function)
- Algorithm-specific parameters (DQN memory size, PPO clip ratio)
- Logging and monitoring settings

### 2. Basic Usage

```python
from src.rl.config.manager import ConfigManager
from src.rl.agents import DQNAgent
from src.rl.environments import TradingEnvironment
from src.rl.training import AgentTrainer

# Load configuration
config_manager = ConfigManager("config/rl_config.json")
config = config_manager.get_config()

# Create environment and agent
environment = TradingEnvironment(config.environment)
agent = DQNAgent(
    state_dim=environment.get_observation_space_shape()[0],
    action_dim=environment.get_action_space_size(),
    config=config.dqn
)

# Train the agent
trainer = AgentTrainer(agent, environment, config.training)
results = trainer.train(num_episodes=1000)
```

### 3. Monitoring and Logging

The framework provides comprehensive monitoring capabilities:

```python
from src.rl.monitoring import RLLogger, MetricsTracker, TrainingMonitor

# Set up monitoring
logger = RLLogger(log_dir="logs/rl")
metrics = MetricsTracker(save_dir="logs/rl")
monitor = TrainingMonitor(patience=20, logger=logger, metrics_tracker=metrics)

# Use during training
monitor.start_monitoring()
for episode in range(num_episodes):
    # Training logic...
    should_continue = monitor.update(episode, reward, loss, performance_metric)
    if not should_continue:
        break
```

## Implementation Status

### ✅ Completed (Task 1)
- [x] Directory structure and core interfaces
- [x] Abstract base classes for environments and agents
- [x] Configuration management system
- [x] Logging and monitoring framework
- [x] Metrics tracking system
- [x] Training monitor with early stopping

### 🚧 In Progress
- [ ] Trading environment implementation (Task 2)
- [ ] DQN agent implementation (Task 3)
- [ ] PPO agent implementation (Task 4)
- [ ] Training pipeline (Task 5)
- [ ] Strategy management (Task 6)
- [ ] MT5 integration (Task 7)
- [ ] Performance analytics (Task 8)
- [ ] Multi-currency support (Task 9)
- [ ] Production deployment (Task 10)

## Testing

Run the foundation tests to verify the framework is working correctly:

```bash
python test_rl_foundation.py
```

This will test:
- Configuration management
- Logging system
- Metrics tracking
- Training monitoring
- Directory structure and imports

## Directory Structure

```
src/rl/
├── __init__.py                 # Main RL module
├── README.md                   # This file
├── environments/               # Trading environments
│   ├── __init__.py
│   ├── base.py                # Abstract environment base class
│   ├── state_processor.py     # State processing utilities
│   └── reward_calculator.py   # Reward function implementations
├── agents/                     # RL agents
│   ├── __init__.py
│   ├── base.py                # Abstract agent base class
│   ├── dqn.py                 # DQN implementation
│   ├── ppo.py                 # PPO implementation
│   └── networks.py            # Neural network architectures
├── training/                   # Training pipeline
│   ├── __init__.py
│   ├── trainer.py             # Training orchestration
│   ├── optimizer.py           # Hyperparameter optimization
│   └── validator.py           # Model validation
├── strategies/                 # Strategy management
│   ├── __init__.py
│   ├── registry.py            # Strategy registry
│   ├── allocator.py           # Capital allocation
│   └── testing.py             # A/B testing framework
├── config/                     # Configuration management
│   ├── __init__.py
│   ├── base.py                # Configuration classes
│   ├── manager.py             # Configuration manager
│   └── hyperparameters.py     # Hyperparameter definitions
└── monitoring/                 # Monitoring and logging
    ├── __init__.py
    ├── logger.py              # RL-specific logging
    ├── metrics.py             # Metrics tracking
    └── monitor.py             # Training monitoring
```

## Next Steps

1. **Task 2**: Implement trading environment and state processing
2. **Task 3**: Build DQN agent with experience replay
3. **Task 4**: Build PPO agent with policy gradients
4. **Task 5**: Create training pipeline and optimization
5. **Task 6**: Implement strategy management system
6. **Task 7**: Integrate with MT5 for live trading
7. **Task 8**: Build performance monitoring and analytics
8. **Task 9**: Add multi-currency pair support
9. **Task 10**: Prepare for production deployment

Each task builds incrementally on the foundation established in Task 1, ensuring a robust and scalable RL trading system.
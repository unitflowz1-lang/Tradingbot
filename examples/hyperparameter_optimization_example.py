"""
Hyperparameter Optimization Example

This example demonstrates how to use the hyperparameter optimization framework
to automatically tune RL agent parameters for optimal performance.
"""

import numpy as np
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from src.rl.training import (
    HyperparameterOptimizer, OptimizationConfig, RLObjectiveFunction,
    OptimizationManager, ResourceManager, ResourceLimits,
    AgentTrainer, TrainingConfig
)
from src.rl.agents.dqn import DQNAgent, DQNConfig


class SimpleEnvironment:
    """Simple environment for demonstration."""
    
    def __init__(self, state_dim=10, action_dim=4, max_steps=100):
        self.state_dim = state_dim
        self.action_dim = action_dim
        self.max_steps = max_steps
        self.current_step = 0
        
    def reset(self):
        """Reset environment."""
        self.current_step = 0
        return np.random.randn(self.state_dim)
        
    def step(self, action):
        """Take environment step."""
        self.current_step += 1
        
        # Simple reward function that favors certain actions
        next_state = np.random.randn(self.state_dim)
        reward = np.random.randn() + (action - 1) * 0.2  # Action 1 is slightly better
        done = self.current_step >= self.max_steps or np.random.random() < 0.05
        info = {}
        
        return next_state, reward, done, info


def create_agent(config):
    """Factory function to create DQN agent."""
    return DQNAgent(state_dim=10, action_dim=4, config=config)


def create_environment():
    """Factory function to create environment."""
    return SimpleEnvironment()


def basic_optimization_example():
    """Basic hyperparameter optimization example."""
    print("=== Basic Hyperparameter Optimization Example ===")
    
    # Check if Optuna is available
    try:
        import optuna
        print("Optuna is available - running optimization")
    except ImportError:
        print("Optuna not available - skipping optimization example")
        print("Install with: pip install optuna")
        return
    
    # Create base configurations
    base_training_config = TrainingConfig(
        total_episodes=50,  # Small for demo
        max_steps_per_episode=50,
        evaluation_frequency=20,
        early_stopping_patience=20,
        experiment_name="hyperopt_demo"
    )
    
    base_agent_config = DQNConfig(
        learning_rate=1e-3,
        batch_size=32,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_end=0.01,
        epsilon_decay=0.995,
        memory_size=1000,
        target_update_frequency=10,
        hidden_layers=[64, 64],
        activation="relu",
        optimizer="adam"
    )
    
    # Create optimization configuration
    optimization_config = OptimizationConfig(
        study_name="dqn_hyperopt_demo",
        direction="maximize",
        n_trials=5,  # Small number for demo
        n_jobs=1,
        sampler="random",  # Faster for demo
        pruner="none"  # Disable pruning for demo
    )
    
    # Create optimizer
    optimizer = HyperparameterOptimizer(optimization_config)
    
    # Create objective function
    objective_function = RLObjectiveFunction(
        base_training_config=base_training_config,
        base_agent_config=base_agent_config,
        agent_type="dqn",
        metric="mean_reward"
    )
    
    # Run optimization
    print("Starting optimization...")
    results = optimizer.optimize(
        objective_function=objective_function,
        agent_factory=create_agent,
        environment_factory=create_environment
    )
    
    # Print results
    print(f"\nOptimization completed!")
    print(f"Best value: {results['best_value']:.3f}")
    print(f"Best parameters: {results['best_params']}")
    print(f"Total trials: {results['n_trials']}")
    print(f"Completed trials: {results['completed_trials']}")
    
    # Get best trials
    best_trials = optimizer.get_best_trials(n_trials=3)
    print(f"\nTop 3 trials:")
    for i, trial in enumerate(best_trials, 1):
        print(f"{i}. Value: {trial['value']:.3f}, Params: {trial['params']}")


def resource_management_example():
    """Resource management example."""
    print("\n=== Resource Management Example ===")
    
    # Create resource limits
    limits = ResourceLimits(
        max_memory_gb=2.0,
        max_cpu_percent=80.0,
        max_time_seconds=300.0,
        max_concurrent_trials=2
    )
    
    # Create resource manager
    manager = ResourceManager(limits)
    
    print(f"Resource limits: {limits.max_memory_gb}GB memory, {limits.max_concurrent_trials} concurrent trials")
    
    # Start resource management
    manager.start()
    
    try:
        # Register some trials
        print("\nRegistering trials...")
        
        trial1_allocated = manager.register_trial(1, memory_gb=0.8, cpu_percent=30.0)
        print(f"Trial 1 allocated: {trial1_allocated}")
        
        trial2_allocated = manager.register_trial(2, memory_gb=0.8, cpu_percent=30.0)
        print(f"Trial 2 allocated: {trial2_allocated}")
        
        trial3_allocated = manager.register_trial(3, memory_gb=0.8, cpu_percent=30.0)
        print(f"Trial 3 allocated: {trial3_allocated} (should be False due to concurrent limit)")
        
        # Get status
        status = manager.get_status()
        print(f"\nResource status:")
        print(f"Active trials: {status['allocation']['active_trials']}")
        print(f"Allocated memory: {status['allocation']['allocated_memory_gb']:.1f}GB")
        print(f"Allocated CPU: {status['allocation']['allocated_cpu_percent']:.1f}%")
        
        # Unregister trial
        manager.unregister_trial(1)
        print(f"\nUnregistered trial 1")
        
        # Try to register trial 3 again
        trial3_retry = manager.register_trial(3, memory_gb=0.8, cpu_percent=30.0)
        print(f"Trial 3 retry allocated: {trial3_retry}")
        
        # Get recommendations
        recommendations = manager.get_resource_recommendations()
        print(f"\nResource recommendations:")
        print(f"Status: {recommendations['current_status']}")
        for suggestion in recommendations['suggestions']:
            print(f"- {suggestion}")
            
    finally:
        manager.stop()
        print("Resource management stopped")


def optimization_manager_example():
    """Optimization manager example."""
    print("\n=== Optimization Manager Example ===")
    
    # Create optimization manager
    results_dir = Path("optimization_results_demo")
    manager = OptimizationManager(str(results_dir))
    
    print(f"Created optimization manager with results directory: {results_dir}")
    
    # Create configurations (same as basic example)
    base_training_config = TrainingConfig(
        total_episodes=20,  # Very small for demo
        max_steps_per_episode=30,
        evaluation_frequency=10
    )
    
    base_agent_config = DQNConfig(
        learning_rate=1e-3,
        batch_size=32,
        gamma=0.99,
        epsilon_start=1.0,
        epsilon_end=0.01,
        epsilon_decay=0.995,
        memory_size=500,
        target_update_frequency=10,
        hidden_layers=[32, 32],
        activation="relu",
        optimizer="adam"
    )
    
    optimization_config = OptimizationConfig(
        study_name="manager_demo",
        n_trials=3,
        sampler="random"
    )
    
    # Check if Optuna is available
    try:
        import optuna
        
        # Run optimization using manager
        print("Running optimization through manager...")
        results = manager.optimize_agent(
            name="demo_optimization",
            agent_type="dqn",
            base_training_config=base_training_config,
            base_agent_config=base_agent_config,
            agent_factory=create_agent,
            environment_factory=create_environment,
            optimization_config=optimization_config,
            metric="mean_reward"
        )
        
        print(f"Optimization completed: {results['best_value']:.3f}")
        
        # Get summary
        summary = manager.get_optimization_summary()
        print(f"\nOptimization summary:")
        print(f"Total optimizations: {summary['total_optimizations']}")
        for name, info in summary['optimizations'].items():
            print(f"- {name}: {info['n_trials']} trials, status: {info['status']}")
            
    except ImportError:
        print("Optuna not available - skipping manager optimization example")
    
    # Cleanup
    import shutil
    if results_dir.exists():
        shutil.rmtree(results_dir)
        print(f"Cleaned up results directory")


def main():
    """Run all examples."""
    print("Hyperparameter Optimization Framework Examples")
    print("=" * 50)
    
    # Run examples
    basic_optimization_example()
    resource_management_example()
    optimization_manager_example()
    
    print("\n" + "=" * 50)
    print("Examples completed!")
    
    # Print usage tips
    print("\nUsage Tips:")
    print("1. Install Optuna for full optimization features: pip install optuna")
    print("2. Install additional packages for advanced features:")
    print("   - pip install matplotlib seaborn (for plotting)")
    print("   - pip install joblib (for parallel optimization)")
    print("   - pip install GPUtil (for GPU monitoring)")
    print("3. Adjust resource limits based on your system capabilities")
    print("4. Use larger n_trials for real optimization (100-1000+)")
    print("5. Consider using distributed optimization for large-scale tuning")


if __name__ == "__main__":
    main()
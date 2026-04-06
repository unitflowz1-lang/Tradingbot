"""
Unit tests for agent trainer and training orchestration.

Tests the AgentTrainer class, training configuration management,
and progress tracking capabilities.
"""

import pytest
import numpy as np
import tempfile
import shutil
import time
import json
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

# Import our cleanup utilities
from test_utils.cleanup import temporary_directory, safe_rmtree
from test_utils.tensorboard_manager import tensorboard_callback_for_testing

from src.rl.training.agent_trainer import (
    AgentTrainer,
    TrainingConfig,
    TrainingMetrics,
    TrainingCallback,
    LoggingCallback,
    TensorBoardCallback,
    CheckpointCallback,
)
from src.rl.training.config_manager import (
    ConfigManager,
    HyperparameterRange,
    ExperimentConfig,
    ConfigValidator,
)
from src.rl.training.progress_tracker import (
    ProgressTracker,
    PerformanceAnalyzer,
    ProgressSnapshot,
)
from src.rl.agents.base import RLAgent, AgentConfig
from src.rl.agents.dqn import DQNAgent, DQNConfig
from src.rl.agents.ppo import PPOAgent, PPOConfig

# from src.rl.environments.trading_env import TradingEnvironment  # Will be available later


class MockAgent(RLAgent):
    """Mock RL agent for testing."""

    def __init__(self, state_dim: int = 10, action_dim: int = 4):
        config = AgentConfig(
            learning_rate=1e-3,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=10000,
            target_update_frequency=100,
            hidden_layers=[64, 64],
            activation="relu",
            optimizer="adam",
        )
        super().__init__(state_dim, action_dim, config)

        self.training_step_count = 0
        self.last_loss = 0.5

    def select_action(self, state: np.ndarray, training: bool = False) -> int:
        """Select random action."""
        return np.random.randint(0, self.action_dim)

    def store_experience(
        self,
        state: np.ndarray,
        action: int,
        reward: float,
        next_state: np.ndarray,
        done: bool,
    ) -> None:
        """Store experience (mock)."""
        pass

    def train_step(self) -> float:
        """Perform training step (mock)."""
        self.training_step_count += 1
        self.last_loss = max(0.1, self.last_loss * 0.99)  # Decreasing loss
        return self.last_loss

    def get_state(self) -> dict:
        """Get agent state."""
        return {"training_step_count": self.training_step_count}

    def get_training_metrics(self) -> dict:
        """Get training metrics."""
        return {"training_steps": self.training_step_count, "last_loss": self.last_loss}

    def update(self, experience: dict) -> None:
        """Update agent with experience."""
        pass

    def reset_episode(self) -> None:
        """Reset agent for new episode."""
        pass

    def save_model(self, filepath: str) -> None:
        """Save agent model."""
        pass

    def load_model(self, filepath: str) -> None:
        """Load agent model."""
        pass

    def get_model_info(self) -> dict:
        """Get model information."""
        return {"type": "MockAgent", "parameters": 1000}


class MockEnvironment:
    """Mock trading environment for testing."""

    def __init__(self, max_steps: int = 100):
        self.max_steps = max_steps
        self.current_step = 0
        self.state_dim = 10

    def reset(self) -> np.ndarray:
        """Reset environment."""
        self.current_step = 0
        return np.random.randn(self.state_dim)

    def step(self, action: int) -> tuple:
        """Take environment step."""
        self.current_step += 1

        next_state = np.random.randn(self.state_dim)
        reward = np.random.randn() + (action * 0.1)  # Slight action bias
        done = self.current_step >= self.max_steps or np.random.random() < 0.05
        info = {}

        return next_state, reward, done, info


class TestTrainingConfig:
    """Test cases for TrainingConfig."""

    def test_training_config_initialization(self):
        """Test training config initialization."""
        config = TrainingConfig()

        assert config.total_episodes == 1000
        assert config.max_steps_per_episode == 1000
        assert config.evaluation_frequency == 100
        assert config.early_stopping_patience == 50
        assert config.experiment_name is not None
        assert isinstance(config.experiment_tags, list)

    def test_training_config_custom_values(self):
        """Test training config with custom values."""
        config = TrainingConfig(
            total_episodes=500,
            max_steps_per_episode=200,
            experiment_name="test_experiment",
            experiment_tags=["test", "dqn"],
        )

        assert config.total_episodes == 500
        assert config.max_steps_per_episode == 200
        assert config.experiment_name == "test_experiment"
        assert config.experiment_tags == ["test", "dqn"]


class TestTrainingMetrics:
    """Test cases for TrainingMetrics."""

    def test_training_metrics_initialization(self):
        """Test training metrics initialization."""
        metrics = TrainingMetrics(
            episode=10, total_reward=15.5, episode_length=100, average_reward=12.3
        )

        assert metrics.episode == 10
        assert metrics.total_reward == 15.5
        assert metrics.episode_length == 100
        assert metrics.average_reward == 12.3
        assert isinstance(metrics.custom_metrics, dict)

    def test_training_metrics_with_optional_fields(self):
        """Test training metrics with optional fields."""
        metrics = TrainingMetrics(
            episode=5,
            total_reward=8.2,
            episode_length=50,
            average_reward=7.1,
            loss=0.3,
            win_rate=0.6,
            custom_metrics={"test_metric": 1.5},
        )

        assert metrics.loss == 0.3
        assert metrics.win_rate == 0.6
        assert metrics.custom_metrics["test_metric"] == 1.5


class TestTrainingCallbacks:
    """Test cases for training callbacks."""

    def test_logging_callback(self):
        """Test logging callback functionality."""
        callback = LoggingCallback()

        # Mock trainer
        trainer = Mock()
        trainer.config = TrainingConfig(log_frequency=1)
        trainer.agent = MockAgent()
        trainer.environment = MockEnvironment()

        # Test callback methods
        callback.on_training_start(trainer)
        assert callback.start_time is not None

        callback.on_episode_start(trainer, 1)

        metrics = TrainingMetrics(
            episode=1, total_reward=10.0, episode_length=50, average_reward=8.0
        )
        callback.on_episode_end(trainer, 1, metrics)

        callback.on_evaluation_start(trainer, 10)
        callback.on_evaluation_end(trainer, 10, {"mean_reward": 12.0})

        callback.on_training_end(trainer)

    def test_tensorboard_callback(self):
        """Test TensorBoard callback functionality."""
        temp_dir = tempfile.mkdtemp()

        try:
            # Test with TensorBoard available
            try:
                callback = TensorBoardCallback(temp_dir)
                
                # Mock trainer
                trainer = Mock()
                trainer.config = TrainingConfig()

                # Test callback methods
                callback.on_training_start(trainer)
                callback.on_training_end(trainer)

                metrics = TrainingMetrics(
                    episode=1,
                    total_reward=10.0,
                    episode_length=50,
                    average_reward=8.0,
                    loss=0.5,
                    custom_metrics={"test": 1.0},
                )
                callback.on_episode_end(trainer, 1, metrics)

                callback.on_evaluation_end(trainer, 10, {"mean_reward": 12.0})
                
            except ImportError:
                # TensorBoard not available, test graceful handling
                callback = TensorBoardCallback(temp_dir)
                assert callback.writer is None
                
                # Test that methods don't crash when writer is None
                trainer = Mock()
                trainer.config = TrainingConfig()
                callback.on_training_start(trainer)
                callback.on_training_end(trainer)
                
                metrics = TrainingMetrics(
                    episode=1,
                    total_reward=10.0,
                    episode_length=50,
                    average_reward=8.0,
                )
                callback.on_episode_end(trainer, 1, metrics)
                callback.on_evaluation_end(trainer, 10, {"mean_reward": 12.0})

        finally:
            shutil.rmtree(temp_dir)

    def test_checkpoint_callback(self):
        """Test checkpoint callback functionality."""
        temp_dir = tempfile.mkdtemp()

        try:
            callback = CheckpointCallback(temp_dir, max_checkpoints=2)

            # Mock trainer
            trainer = Mock()
            trainer.config = TrainingConfig(save_frequency=1)
            trainer.current_episode = 1
            trainer.training_history = []
            trainer.agent = MockAgent()

            # Test callback methods
            callback.on_training_start(trainer)

            metrics = TrainingMetrics(
                episode=1, total_reward=10.0, episode_length=50, average_reward=8.0
            )
            callback.on_episode_end(trainer, 1, metrics)

            # Check that checkpoint was created
            assert len(callback.checkpoints) == 1
            assert callback.checkpoints[0].exists()

            callback.on_training_end(trainer)

            # Check that final checkpoint was created
            assert len(callback.checkpoints) == 2

        finally:
            shutil.rmtree(temp_dir)


class TestAgentTrainer:
    """Test cases for AgentTrainer."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing with robust cleanup."""
        with temporary_directory(cleanup_retries=5) as temp_dir:
            yield temp_dir

    @pytest.fixture
    def mock_agent(self):
        """Create mock agent for testing."""
        return MockAgent()

    @pytest.fixture
    def mock_environment(self):
        """Create mock environment for testing."""
        return MockEnvironment(max_steps=20)

    @pytest.fixture
    def training_config(self, temp_dir):
        """Create training configuration for testing."""
        return TrainingConfig(
            total_episodes=5,
            max_steps_per_episode=20,
            evaluation_frequency=2,
            save_frequency=2,
            early_stopping_patience=10,
            checkpoint_dir=temp_dir,
            log_frequency=1,
            tensorboard_logging=False,  # Disable TensorBoard to avoid file cleanup issues in tests
        )

    def test_agent_trainer_initialization(
        self, mock_agent, mock_environment, training_config
    ):
        """Test agent trainer initialization."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        assert trainer.agent == mock_agent
        assert trainer.environment == mock_environment
        assert trainer.config == training_config
        assert trainer.current_episode == 0
        assert len(trainer.training_history) == 0
        assert len(trainer.callbacks) > 0  # Default callbacks

    def test_agent_trainer_single_episode(
        self, mock_agent, mock_environment, training_config
    ):
        """Test single episode training."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        # Train single episode
        metrics = trainer._train_episode(0)

        assert isinstance(metrics, TrainingMetrics)
        assert metrics.episode == 0
        assert metrics.episode_length > 0
        assert metrics.episode_time >= 0  # Can be 0 for very fast mock environments
        assert "training_steps" in metrics.custom_metrics

    def test_agent_trainer_full_training(
        self, mock_agent, mock_environment, training_config
    ):
        """Test full training loop."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        # Run training
        history = trainer.train()

        assert len(history) == training_config.total_episodes
        assert all(isinstance(m, TrainingMetrics) for m in history)
        assert len(trainer.evaluation_history) > 0  # Should have evaluations

    def test_agent_trainer_evaluation(
        self, mock_agent, mock_environment, training_config
    ):
        """Test agent evaluation."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        # Run evaluation
        eval_metrics = trainer._evaluate(0)

        assert isinstance(eval_metrics, dict)
        assert "mean_reward" in eval_metrics
        assert "std_reward" in eval_metrics
        assert "mean_length" in eval_metrics

    def test_agent_trainer_early_stopping(self, mock_agent, mock_environment, temp_dir):
        """Test early stopping functionality."""
        config = TrainingConfig(
            total_episodes=100,
            early_stopping_patience=3,
            early_stopping_threshold=0.01,
            checkpoint_dir=temp_dir,
            tensorboard_logging=False,  # Disable TensorBoard to avoid file cleanup issues
        )

        trainer = AgentTrainer(mock_agent, mock_environment, config)

        # Simulate poor performance (should trigger early stopping)
        for i in range(5):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=-10.0,  # Consistently poor
                episode_length=10,
                average_reward=-10.0,
            )
            trainer.training_history.append(metrics)

            if trainer._should_stop_early(metrics):
                break

        assert trainer.episodes_without_improvement >= config.early_stopping_patience

    def test_agent_trainer_callbacks(
        self, mock_agent, mock_environment, training_config
    ):
        """Test callback management."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        # Add custom callback
        custom_callback = Mock(spec=TrainingCallback)
        trainer.add_callback(custom_callback)

        assert custom_callback in trainer.callbacks

        # Remove callback
        trainer.remove_callback(custom_callback)
        assert custom_callback not in trainer.callbacks

    def test_agent_trainer_training_summary(
        self, mock_agent, mock_environment, training_config
    ):
        """Test training summary generation."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        # Add some training history
        for i in range(10):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i),
                episode_length=50,
                average_reward=float(i / 2),
                episode_time=1.0,
            )
            trainer.training_history.append(metrics)

        summary = trainer.get_training_summary()

        assert "total_episodes" in summary
        assert "total_time" in summary
        assert "reward_statistics" in summary
        assert "length_statistics" in summary
        assert summary["total_episodes"] == 10

    def test_agent_trainer_save_load_data(
        self, mock_agent, mock_environment, training_config, temp_dir
    ):
        """Test saving and loading training data."""
        trainer = AgentTrainer(mock_agent, mock_environment, training_config)

        # Add some training history
        for i in range(3):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i),
                episode_length=50,
                average_reward=float(i / 2),
            )
            trainer.training_history.append(metrics)

        # Save data
        save_path = Path(temp_dir) / "training_data.json"
        trainer.save_training_data(str(save_path))

        assert save_path.exists()

        # Load data
        new_trainer = AgentTrainer(mock_agent, mock_environment, training_config)
        new_trainer.load_training_data(str(save_path))

        assert len(new_trainer.training_history) == 3
        assert new_trainer.training_history[0].episode == 0


class TestConfigManager:
    """Test cases for ConfigManager."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def config_manager(self, temp_dir):
        """Create config manager for testing."""
        return ConfigManager(temp_dir)

    def test_config_manager_initialization(self, config_manager, temp_dir):
        """Test config manager initialization."""
        assert config_manager.config_dir == Path(temp_dir)
        assert config_manager.config_dir.exists()
        assert len(config_manager.registered_configs) == 0

    def test_config_registration(self, config_manager):
        """Test configuration registration."""
        config = TrainingConfig(total_episodes=500)
        config_manager.register_config("test_config", config)

        assert "test_config" in config_manager.registered_configs
        assert config_manager.get_config("test_config") == config
        assert "test_config" in config_manager.list_configs()

    def test_config_save_load_json(self, config_manager, temp_dir):
        """Test saving and loading configuration in JSON format."""
        config = TrainingConfig(total_episodes=500, experiment_name="test")

        # Save config
        save_path = Path(temp_dir) / "test_config.json"
        config_manager.save_config(config, str(save_path), format="json")

        assert save_path.exists()

        # Load config
        loaded_config = config_manager.load_config(str(save_path), TrainingConfig)

        assert loaded_config.total_episodes == 500
        assert loaded_config.experiment_name == "test"

    def test_config_validation(self, config_manager):
        """Test configuration validation."""
        # Valid config
        valid_config = TrainingConfig(total_episodes=100)
        errors = config_manager.validate_config(valid_config)
        assert len(errors) == 0

        # Invalid config
        invalid_config = TrainingConfig(total_episodes=-1)
        errors = config_manager.validate_config(invalid_config)
        assert len(errors) > 0
        assert any("total_episodes must be positive" in error for error in errors)

    def test_hyperparameter_sampling(self, config_manager):
        """Test hyperparameter sampling."""
        base_config = TrainingConfig()

        search_ranges = {
            "total_episodes": HyperparameterRange(
                100, 1000, discrete_values=[100, 500, 1000]
            ),
            "early_stopping_patience": HyperparameterRange(10, 100),
        }

        sampled_config = config_manager.sample_hyperparameters(
            base_config, search_ranges
        )

        assert isinstance(sampled_config, TrainingConfig)
        assert sampled_config.total_episodes in [100, 500, 1000]
        assert 10 <= sampled_config.early_stopping_patience <= 100

    def test_experiment_suite_creation(self, config_manager):
        """Test experiment suite creation."""
        base_config = TrainingConfig()

        variations = {"total_episodes": [100, 200], "early_stopping_patience": [10, 20]}

        experiments = config_manager.create_experiment_suite(
            base_config, variations, "test_suite"
        )

        assert len(experiments) == 4  # 2 x 2 combinations
        assert all("name" in exp for exp in experiments)
        assert all("config" in exp for exp in experiments)
        assert all("variations" in exp for exp in experiments)

    def test_default_configs(self, config_manager):
        """Test default configuration retrieval."""
        defaults = config_manager.get_default_configs()

        assert "dqn_training" in defaults
        assert "ppo_training" in defaults
        assert "dqn_agent" in defaults
        assert "ppo_agent" in defaults

        assert isinstance(defaults["dqn_training"], TrainingConfig)
        assert isinstance(defaults["dqn_agent"], DQNConfig)


class TestProgressTracker:
    """Test cases for ProgressTracker."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for testing."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def progress_tracker(self, temp_dir):
        """Create progress tracker for testing."""
        return ProgressTracker(temp_dir)

    def test_progress_tracker_initialization(self, progress_tracker, temp_dir):
        """Test progress tracker initialization."""
        assert progress_tracker.save_dir == Path(temp_dir)
        assert progress_tracker.save_dir.exists()
        assert len(progress_tracker.metrics_history) == 0
        assert len(progress_tracker.snapshots) == 0

    def test_add_metrics(self, progress_tracker):
        """Test adding metrics to progress tracker."""
        metrics = TrainingMetrics(
            episode=1, total_reward=10.0, episode_length=50, average_reward=8.0
        )

        progress_tracker.add_metrics(metrics)

        assert len(progress_tracker.metrics_history) == 1
        assert len(progress_tracker.snapshots) == 1
        assert progress_tracker.metrics_history[0] == metrics

    def test_current_status(self, progress_tracker):
        """Test getting current training status."""
        # No data
        status = progress_tracker.get_current_status()
        assert status["status"] == "no_data"

        # Add some data
        for i in range(5):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i),
                episode_length=50,
                average_reward=float(i / 2),
            )
            progress_tracker.add_metrics(metrics)

        status = progress_tracker.get_current_status()

        assert "current_episode" in status
        assert "current_reward" in status
        assert "stability_score" in status
        assert status["current_episode"] == 4

    def test_progress_report(self, progress_tracker):
        """Test creating progress report."""
        # Add training data
        for i in range(10):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i),
                episode_length=50,
                average_reward=float(i / 2),
                episode_time=1.0,
            )
            progress_tracker.add_metrics(metrics)

        report = progress_tracker.create_progress_report()

        assert "summary" in report
        assert "convergence" in report
        assert "stability" in report
        assert "efficiency" in report
        assert "statistics" in report
        assert report["summary"]["total_episodes"] == 10

    def test_save_load_progress_data(self, progress_tracker, temp_dir):
        """Test saving and loading progress data."""
        # Add some data
        for i in range(3):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i),
                episode_length=50,
                average_reward=float(i / 2),
            )
            progress_tracker.add_metrics(metrics)

        # Save data
        save_path = Path(temp_dir) / "progress.json"
        progress_tracker.save_progress_data(str(save_path))

        assert save_path.exists()

        # Load data
        new_tracker = ProgressTracker(temp_dir)
        new_tracker.load_progress_data(str(save_path))

        assert len(new_tracker.metrics_history) == 3
        assert len(new_tracker.snapshots) == 3

    def test_plot_training_progress(self, progress_tracker, temp_dir):
        """Test plotting training progress."""
        # Add training data
        for i in range(20):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i) + np.random.randn() * 0.1,
                episode_length=50 + int(np.random.randn() * 5),
                average_reward=float(i / 2),
                loss=max(0.1, 1.0 - i * 0.05),
                episode_time=1.0,
            )
            progress_tracker.add_metrics(metrics)

        # Test plotting
        save_path = Path(temp_dir) / "progress_plot.png"
        
        try:
            # Try to plot - this will work if matplotlib is available
            progress_tracker.plot_training_progress(str(save_path), show=False)
            # If we get here, matplotlib is available and plotting worked
            # We can't easily mock matplotlib in this context, so we just verify
            # that the method doesn't crash
        except ImportError:
            # Matplotlib not available, which is expected in some test environments
            # The method should handle this gracefully
            pass

    def test_export_to_csv(self, progress_tracker, temp_dir):
        """Test exporting data to CSV."""
        # Add training data
        for i in range(5):
            metrics = TrainingMetrics(
                episode=i,
                total_reward=float(i),
                episode_length=50,
                average_reward=float(i / 2),
                custom_metrics={"test_metric": float(i * 2)},
            )
            progress_tracker.add_metrics(metrics)

        # Export to CSV
        csv_path = Path(temp_dir) / "training_data.csv"
        progress_tracker.export_to_csv(str(csv_path))

        assert csv_path.exists()

        # Verify CSV content
        import pandas as pd

        df = pd.read_csv(csv_path)

        assert len(df) == 5
        assert "episode" in df.columns
        assert "total_reward" in df.columns
        assert "custom_test_metric" in df.columns


class TestPerformanceAnalyzer:
    """Test cases for PerformanceAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        """Create performance analyzer for testing."""
        return PerformanceAnalyzer(window_size=10)

    @pytest.fixture
    def sample_metrics(self):
        """Create sample training metrics."""
        metrics = []
        for i in range(50):
            # Simulate improving performance with noise
            reward = i * 0.5 + np.random.randn() * 0.1
            metrics.append(
                TrainingMetrics(
                    episode=i,
                    total_reward=reward,
                    episode_length=50,
                    average_reward=reward,
                )
            )
        return metrics

    def test_convergence_analysis(self, analyzer, sample_metrics):
        """Test convergence analysis."""
        analysis = analyzer.analyze_convergence(sample_metrics)

        assert "status" in analysis
        assert analysis["status"] in ["converged", "not_converged"]

        if analysis["status"] == "converged":
            assert "convergence_episode" in analysis
            assert "converged_performance" in analysis
        else:
            assert "current_trend" in analysis
            assert "estimated_episodes_to_convergence" in analysis

    def test_stability_analysis(self, analyzer, sample_metrics):
        """Test stability analysis."""
        analysis = analyzer.analyze_stability(sample_metrics)

        assert "stability_score" in analysis
        assert "reward_std" in analysis
        assert "coefficient_of_variation" in analysis
        assert 0 <= analysis["stability_score"] <= 1

    def test_learning_efficiency_analysis(self, analyzer, sample_metrics):
        """Test learning efficiency analysis."""
        analysis = analyzer.analyze_learning_efficiency(sample_metrics)

        assert "efficiency_score" in analysis
        assert "learning_slope" in analysis
        assert "sample_efficiency" in analysis
        assert 0 <= analysis["efficiency_score"] <= 1

    def test_insufficient_data_handling(self, analyzer):
        """Test handling of insufficient data."""
        # Test with very few metrics
        few_metrics = [
            TrainingMetrics(
                episode=0, total_reward=1.0, episode_length=10, average_reward=1.0
            ),
            TrainingMetrics(
                episode=1, total_reward=2.0, episode_length=10, average_reward=1.5
            ),
        ]

        convergence = analyzer.analyze_convergence(few_metrics)
        assert convergence["status"] == "insufficient_data"

        stability = analyzer.analyze_stability(few_metrics)
        assert "stability_score" in stability

        efficiency = analyzer.analyze_learning_efficiency(few_metrics)
        assert efficiency["efficiency_score"] == 0.0


class TestIntegration:
    """Integration tests for training orchestration."""

    @pytest.fixture
    def complete_setup(self):
        """Complete setup for integration testing."""
        temp_dir = tempfile.mkdtemp()

        # Create components
        agent = MockAgent()
        environment = MockEnvironment(max_steps=10)
        config = TrainingConfig(
            total_episodes=3,
            max_steps_per_episode=10,
            evaluation_frequency=2,
            save_frequency=2,
            checkpoint_dir=temp_dir,
            tensorboard_logging=False,  # Disable for testing
        )

        trainer = AgentTrainer(agent, environment, config)
        config_manager = ConfigManager(temp_dir)
        progress_tracker = ProgressTracker(temp_dir)

        yield {
            "temp_dir": temp_dir,
            "agent": agent,
            "environment": environment,
            "config": config,
            "trainer": trainer,
            "config_manager": config_manager,
            "progress_tracker": progress_tracker,
        }

        # Cleanup
        shutil.rmtree(temp_dir)

    def test_full_training_pipeline(self, complete_setup):
        """Test complete training pipeline integration."""
        setup = complete_setup
        trainer = setup["trainer"]
        progress_tracker = setup["progress_tracker"]

        # Run training
        history = trainer.train()

        # Add metrics to progress tracker
        for metrics in history:
            progress_tracker.add_metrics(metrics)

        # Verify training completed
        assert len(history) == setup["config"].total_episodes
        assert len(progress_tracker.metrics_history) == setup["config"].total_episodes

        # Check that evaluations were performed
        assert len(trainer.evaluation_history) > 0

        # Generate progress report
        report = progress_tracker.create_progress_report()
        assert "summary" in report
        assert report["summary"]["total_episodes"] == setup["config"].total_episodes

    def test_config_management_integration(self, complete_setup):
        """Test configuration management integration."""
        setup = complete_setup
        config_manager = setup["config_manager"]

        # Register and save configuration
        config_manager.register_config("test_training", setup["config"])

        save_path = Path(setup["temp_dir"]) / "config.json"
        config_manager.save_config(setup["config"], str(save_path))

        # Load and verify configuration
        loaded_config = config_manager.load_config(str(save_path), TrainingConfig)
        assert loaded_config.total_episodes == setup["config"].total_episodes

        # Validate configuration
        errors = config_manager.validate_config(loaded_config)
        assert len(errors) == 0

    def test_hyperparameter_optimization_workflow(self, complete_setup):
        """Test hyperparameter optimization workflow."""
        setup = complete_setup
        config_manager = setup["config_manager"]

        # Create hyperparameter search space
        base_config = setup["config"]
        search_ranges = {
            "total_episodes": HyperparameterRange(2, 5, discrete_values=[2, 3, 4, 5]),
            "early_stopping_patience": HyperparameterRange(5, 15),
        }

        # Sample multiple configurations
        sampled_configs = []
        for _ in range(3):
            sampled_config = config_manager.sample_hyperparameters(
                base_config, search_ranges
            )
            sampled_configs.append(sampled_config)

        # Verify sampling worked
        assert len(sampled_configs) == 3
        assert all(isinstance(config, TrainingConfig) for config in sampled_configs)
        assert all(config.total_episodes in [2, 3, 4, 5] for config in sampled_configs)

    def test_training_with_progress_tracking(self, complete_setup):
        """Test training with comprehensive progress tracking."""
        setup = complete_setup
        trainer = setup["trainer"]
        progress_tracker = setup["progress_tracker"]

        # Custom callback to add metrics to progress tracker
        class ProgressTrackingCallback(TrainingCallback):
            def __init__(self, tracker):
                self.tracker = tracker

            def on_training_start(self, trainer):
                pass

            def on_training_end(self, trainer):
                pass

            def on_episode_start(self, trainer, episode):
                pass

            def on_evaluation_start(self, trainer, episode):
                pass

            def on_evaluation_end(self, trainer, episode, eval_metrics):
                pass

            def on_episode_end(self, trainer, episode, metrics):
                self.tracker.add_metrics(metrics)

        # Add progress tracking callback
        trainer.add_callback(ProgressTrackingCallback(progress_tracker))

        # Run training
        history = trainer.train()

        # Verify progress tracking
        assert len(progress_tracker.metrics_history) == len(history)
        assert len(progress_tracker.snapshots) == len(history)

        # Get current status
        status = progress_tracker.get_current_status()
        assert status["current_episode"] == len(history) - 1

        # Create comprehensive report
        report = progress_tracker.create_progress_report()
        assert "convergence" in report
        assert "stability" in report
        assert "efficiency" in report


if __name__ == "__main__":
    pytest.main([__file__])

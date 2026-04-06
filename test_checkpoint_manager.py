"""
Unit tests for Checkpoint Manager and Performance Tracker

This module tests the model persistence, checkpointing, and performance
tracking functionality for RL agents.
"""

import unittest
import tempfile
import shutil
import os
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import numpy as np

# Import the checkpoint manager components
from src.rl.agents.checkpoint_manager import (
    CheckpointManager, PerformanceTracker, CheckpointMetadata, ValidationResult
)
from src.rl.agents.dqn import DQNAgent, DQNConfig
from src.rl.agents.networks import NetworkConfig, ActivationFunction


class TestCheckpointMetadata(unittest.TestCase):
    """Test checkpoint metadata functionality."""
    
    def test_metadata_creation(self):
        """Test creating checkpoint metadata."""
        metadata = CheckpointMetadata(
            checkpoint_id="test_checkpoint_001",
            agent_type="DQNAgent",
            timestamp=datetime.now(),
            episode=100,
            training_step=5000,
            performance_metrics={"total_return": 150.5, "win_rate": 0.75},
            config={"learning_rate": 0.001},
            description="Test checkpoint",
            tags=["experiment_1", "baseline"]
        )
        
        self.assertEqual(metadata.checkpoint_id, "test_checkpoint_001")
        self.assertEqual(metadata.agent_type, "DQNAgent")
        self.assertEqual(metadata.episode, 100)
        self.assertEqual(metadata.training_step, 5000)
        self.assertIn("total_return", metadata.performance_metrics)
        self.assertEqual(len(metadata.tags), 2)
        
    def test_metadata_default_values(self):
        """Test metadata with default values."""
        metadata = CheckpointMetadata(
            checkpoint_id="test",
            agent_type="DQNAgent",
            timestamp=datetime.now(),
            episode=1,
            training_step=1,
            performance_metrics={},
            config={}
        )
        
        self.assertEqual(metadata.version, "1.0")
        self.assertEqual(metadata.description, "")
        self.assertEqual(metadata.tags, [])


class TestCheckpointManager(unittest.TestCase):
    """Test checkpoint manager functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create temporary directory for checkpoints
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_manager = CheckpointManager(
            checkpoint_dir=self.temp_dir,
            max_checkpoints=5,
            validation_threshold=0.0,
            auto_cleanup=True
        )
        
        # Create mock agent
        self.agent = self._create_mock_agent()
        
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
        
    def _create_mock_agent(self):
        """Create a mock DQN agent for testing."""
        config = DQNConfig(
            learning_rate=0.001,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=1000,
            target_update_frequency=100,
            hidden_layers=[64, 32],
            activation="relu",
            optimizer="adam",
            network_config=NetworkConfig(
                hidden_layers=[64, 32],
                activation=ActivationFunction.RELU,
                batch_norm=False,
                learning_rate=0.001
            )
        )
        
        agent = DQNAgent(state_dim=10, action_dim=4, config=config)
        agent.training_step = 1000
        return agent
        
    def test_checkpoint_manager_initialization(self):
        """Test checkpoint manager initialization."""
        self.assertTrue(os.path.exists(self.temp_dir))
        self.assertEqual(self.checkpoint_manager.max_checkpoints, 5)
        self.assertEqual(self.checkpoint_manager.validation_threshold, 0.0)
        self.assertTrue(self.checkpoint_manager.auto_cleanup)
        
    def test_save_checkpoint_basic(self):
        """Test basic checkpoint saving."""
        performance_metrics = {
            "total_return": 100.0,
            "episode_length": 200,
            "win_rate": 0.6
        }
        
        checkpoint_id = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=50,
            performance_metrics=performance_metrics,
            description="Test checkpoint",
            tags=["test"],
            validate=False  # Skip validation for basic test
        )
        
        self.assertIsNotNone(checkpoint_id)
        self.assertIn(checkpoint_id, self.checkpoint_manager.checkpoints)
        
        # Check that files were created
        checkpoint_path = self.checkpoint_manager.checkpoint_dir / checkpoint_id
        self.assertTrue(checkpoint_path.exists())
        self.assertTrue((checkpoint_path / "model.pth").exists())
        self.assertTrue((checkpoint_path / "metadata.json").exists())
        
    def test_load_checkpoint(self):
        """Test loading checkpoint."""
        # First save a checkpoint
        performance_metrics = {"total_return": 100.0}
        checkpoint_id = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=50,
            performance_metrics=performance_metrics,
            validate=False
        )
        
        # Create new agent and load checkpoint
        new_agent = self._create_mock_agent()
        original_training_step = new_agent.training_step
        
        success = self.checkpoint_manager.load_checkpoint(new_agent, checkpoint_id)
        
        self.assertTrue(success)
        # Training step should be restored from checkpoint
        self.assertEqual(new_agent.training_step, self.agent.training_step)
        
    def test_get_best_checkpoint(self):
        """Test getting best checkpoint by metric."""
        # Save multiple checkpoints with different performance
        checkpoints = []
        for i, return_value in enumerate([50.0, 150.0, 100.0]):
            checkpoint_id = self.checkpoint_manager.save_checkpoint(
                agent=self.agent,
                episode=i + 1,
                performance_metrics={"total_return": return_value},
                validate=False
            )
            checkpoints.append(checkpoint_id)
        
        best_checkpoint = self.checkpoint_manager.get_best_checkpoint("total_return")
        
        # Should be the checkpoint with return_value = 150.0
        self.assertEqual(best_checkpoint, checkpoints[1])
        
    def test_get_latest_checkpoint(self):
        """Test getting latest checkpoint."""
        checkpoints = []
        
        # Save checkpoints with small time delays
        for i in range(3):
            checkpoint_id = self.checkpoint_manager.save_checkpoint(
                agent=self.agent,
                episode=i + 1,
                performance_metrics={"total_return": 100.0},
                validate=False
            )
            checkpoints.append(checkpoint_id)
        
        latest_checkpoint = self.checkpoint_manager.get_latest_checkpoint()
        
        # Should be the last checkpoint saved
        self.assertEqual(latest_checkpoint, checkpoints[-1])
        
    def test_list_checkpoints(self):
        """Test listing checkpoints with filtering."""
        # Save checkpoints with different tags
        checkpoint1 = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=1,
            performance_metrics={"total_return": 100.0},
            tags=["experiment_1", "baseline"],
            validate=False
        )
        
        checkpoint2 = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=2,
            performance_metrics={"total_return": 120.0},
            tags=["experiment_1", "improved"],
            validate=False
        )
        
        # List all checkpoints
        all_checkpoints = self.checkpoint_manager.list_checkpoints()
        self.assertEqual(len(all_checkpoints), 2)
        
        # Filter by tag
        baseline_checkpoints = self.checkpoint_manager.list_checkpoints(tags=["baseline"])
        self.assertEqual(len(baseline_checkpoints), 1)
        self.assertEqual(baseline_checkpoints[0].checkpoint_id, checkpoint1)
        
    def test_delete_checkpoint(self):
        """Test deleting checkpoint."""
        checkpoint_id = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=1,
            performance_metrics={"total_return": 100.0},
            validate=False
        )
        
        # Verify checkpoint exists
        self.assertIn(checkpoint_id, self.checkpoint_manager.checkpoints)
        
        # Delete checkpoint
        success = self.checkpoint_manager.delete_checkpoint(checkpoint_id)
        
        self.assertTrue(success)
        self.assertNotIn(checkpoint_id, self.checkpoint_manager.checkpoints)
        
        # Verify files are deleted
        checkpoint_path = self.checkpoint_manager.checkpoint_dir / checkpoint_id
        self.assertFalse(checkpoint_path.exists())
        
    def test_compare_checkpoints(self):
        """Test comparing checkpoints."""
        checkpoint1 = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=1,
            performance_metrics={"total_return": 100.0, "win_rate": 0.6},
            validate=False
        )
        
        checkpoint2 = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=2,
            performance_metrics={"total_return": 120.0, "win_rate": 0.7},
            validate=False
        )
        
        comparison = self.checkpoint_manager.compare_checkpoints(
            [checkpoint1, checkpoint2],
            metrics=["total_return"]
        )
        
        self.assertEqual(len(comparison), 2)
        self.assertIn(checkpoint1, comparison)
        self.assertIn(checkpoint2, comparison)
        self.assertEqual(comparison[checkpoint1]["total_return"], 100.0)
        self.assertEqual(comparison[checkpoint2]["total_return"], 120.0)
        
    def test_checkpoint_cleanup(self):
        """Test automatic checkpoint cleanup."""
        # Save more checkpoints than max_checkpoints
        checkpoints = []
        for i in range(7):  # More than max_checkpoints (5)
            checkpoint_id = self.checkpoint_manager.save_checkpoint(
                agent=self.agent,
                episode=i + 1,
                performance_metrics={"total_return": float(i)},
                validate=False
            )
            checkpoints.append(checkpoint_id)
        
        # Should only have max_checkpoints remaining
        self.assertEqual(len(self.checkpoint_manager.checkpoints), 5)
        
        # Oldest checkpoints should be removed
        for checkpoint_id in checkpoints[:2]:
            self.assertNotIn(checkpoint_id, self.checkpoint_manager.checkpoints)
            
    def test_model_validation(self):
        """Test model validation during checkpoint saving."""
        # Test with good performance metrics
        good_metrics = {"total_return": 100.0, "win_rate": 0.7}
        checkpoint_id = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=1,
            performance_metrics=good_metrics,
            validate=True
        )
        self.assertIsNotNone(checkpoint_id)
        
        # Test with invalid metrics (should fail validation)
        bad_metrics = {"total_return": float('nan'), "win_rate": 0.7}
        checkpoint_id = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=2,
            performance_metrics=bad_metrics,
            validate=True
        )
        self.assertIsNone(checkpoint_id)
        
    def test_registry_persistence(self):
        """Test that checkpoint registry persists across manager instances."""
        # Save checkpoint with first manager
        checkpoint_id = self.checkpoint_manager.save_checkpoint(
            agent=self.agent,
            episode=1,
            performance_metrics={"total_return": 100.0},
            validate=False
        )
        
        # Create new manager with same directory
        new_manager = CheckpointManager(checkpoint_dir=self.temp_dir)
        
        # Should load existing checkpoints
        self.assertIn(checkpoint_id, new_manager.checkpoints)
        
        # Should be able to load the checkpoint
        new_agent = self._create_mock_agent()
        success = new_manager.load_checkpoint(new_agent, checkpoint_id)
        self.assertTrue(success)


class TestPerformanceTracker(unittest.TestCase):
    """Test performance tracker functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.tracker = PerformanceTracker(
            metrics_to_track=['episode_reward', 'episode_length', 'loss'],
            window_size=10
        )
        
    def test_tracker_initialization(self):
        """Test performance tracker initialization."""
        self.assertEqual(len(self.tracker.metrics_to_track), 3)
        self.assertEqual(self.tracker.window_size, 10)
        self.assertEqual(len(self.tracker.metrics_history), 3)
        
    def test_update_metrics(self):
        """Test updating performance metrics."""
        metrics = {
            'episode_reward': 100.0,
            'episode_length': 200,
            'loss': 0.5
        }
        
        self.tracker.update(episode=1, metrics=metrics)
        
        self.assertEqual(len(self.tracker.episode_history), 1)
        self.assertEqual(self.tracker.episode_history[0], 1)
        self.assertEqual(self.tracker.metrics_history['episode_reward'][0], 100.0)
        self.assertEqual(self.tracker.best_performance['episode_reward'], 100.0)
        
    def test_moving_averages(self):
        """Test moving average calculation."""
        # Add multiple episodes
        for i in range(5):
            metrics = {'episode_reward': float(i * 10)}
            self.tracker.update(episode=i, metrics=metrics)
        
        # Moving average should be calculated
        self.assertIn('episode_reward', self.tracker.moving_averages)
        expected_avg = sum(range(0, 50, 10)) / 5  # (0+10+20+30+40)/5 = 20
        self.assertEqual(self.tracker.moving_averages['episode_reward'], expected_avg)
        
    def test_recent_performance(self):
        """Test getting recent performance."""
        # Add episodes with increasing rewards
        for i in range(10):
            metrics = {'episode_reward': float(i * 10)}
            self.tracker.update(episode=i, metrics=metrics)
        
        # Get recent performance (last 5 episodes)
        recent = self.tracker.get_recent_performance(episodes=5)
        
        # Should average last 5 episodes: (50+60+70+80+90)/5 = 70
        expected_avg = sum(range(50, 100, 10)) / 5
        self.assertEqual(recent['episode_reward'], expected_avg)
        
    def test_improvement_detection(self):
        """Test improvement detection."""
        # Add episodes with improving trend
        for i in range(20):
            reward = 50.0 + i * 2  # Increasing reward
            metrics = {'episode_reward': reward}
            self.tracker.update(episode=i, metrics=metrics)
        
        # Should detect improvement
        self.assertTrue(self.tracker.is_improving('episode_reward'))
        
        # Add episodes with declining trend
        for i in range(20, 40):
            reward = 90.0 - (i - 20) * 2  # Decreasing reward
            metrics = {'episode_reward': reward}
            self.tracker.update(episode=i, metrics=metrics)
        
        # Should not detect improvement in recent episodes
        self.assertFalse(self.tracker.is_improving('episode_reward', episodes=15))
        
    def test_early_stopping(self):
        """Test early stopping detection."""
        # Add episodes with initial improvement
        for i in range(30):
            reward = 50.0 + i * 2
            metrics = {'episode_reward': reward}
            self.tracker.update(episode=i, metrics=metrics)
        
        # Add episodes with no improvement
        for i in range(30, 80):
            reward = 108.0 + np.random.normal(0, 1)  # Plateau with noise
            metrics = {'episode_reward': reward}
            self.tracker.update(episode=i, metrics=metrics)
        
        # Should suggest early stopping
        should_stop = self.tracker.should_stop_early(
            metric='episode_reward',
            patience=20,
            min_improvement=5.0
        )
        self.assertTrue(should_stop)
        
    def test_performance_summary(self):
        """Test getting performance summary."""
        # Add some episodes
        for i in range(10):
            metrics = {
                'episode_reward': float(i * 10),
                'episode_length': 200 + i * 5,
                'loss': 1.0 - i * 0.1
            }
            self.tracker.update(episode=i, metrics=metrics)
        
        summary = self.tracker.get_summary()
        
        # Check summary structure
        required_keys = [
            'total_episodes', 'metrics_tracked', 'best_performance',
            'worst_performance', 'current_moving_averages', 'recent_performance'
        ]
        for key in required_keys:
            self.assertIn(key, summary)
        
        self.assertEqual(summary['total_episodes'], 10)
        self.assertEqual(len(summary['metrics_tracked']), 3)
        self.assertEqual(summary['best_performance']['episode_reward'], 90.0)
        self.assertEqual(summary['worst_performance']['episode_reward'], 0.0)


class TestIntegration(unittest.TestCase):
    """Test integration between checkpoint manager and performance tracker."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_manager = CheckpointManager(checkpoint_dir=self.temp_dir)
        self.performance_tracker = PerformanceTracker()
        self.agent = self._create_mock_agent()
        
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
        
    def _create_mock_agent(self):
        """Create a mock DQN agent for testing."""
        config = DQNConfig(
            learning_rate=0.001,
            batch_size=32,
            gamma=0.99,
            epsilon_start=1.0,
            epsilon_end=0.01,
            epsilon_decay=0.995,
            memory_size=1000,
            target_update_frequency=100,
            hidden_layers=[64, 32],
            activation="relu",
            optimizer="adam",
            network_config=NetworkConfig(
                hidden_layers=[64, 32],
                activation=ActivationFunction.RELU,
                batch_norm=False,
                learning_rate=0.001
            )
        )
        
        return DQNAgent(state_dim=10, action_dim=4, config=config)
        
    def test_training_workflow(self):
        """Test complete training workflow with checkpointing and tracking."""
        best_performance = -float('inf')
        
        # Simulate training episodes
        for episode in range(50):
            # Simulate episode metrics
            episode_reward = 50.0 + episode * 2 + np.random.normal(0, 5)
            episode_length = 200 + np.random.randint(-20, 20)
            loss = max(0.1, 2.0 - episode * 0.03)
            
            metrics = {
                'episode_reward': episode_reward,
                'episode_length': episode_length,
                'loss': loss
            }
            
            # Update performance tracker
            self.performance_tracker.update(episode, metrics)
            
            # Save checkpoint every 10 episodes or if performance improved
            if episode % 10 == 0 or episode_reward > best_performance:
                checkpoint_id = self.checkpoint_manager.save_checkpoint(
                    agent=self.agent,
                    episode=episode,
                    performance_metrics=metrics,
                    description=f"Episode {episode} checkpoint",
                    validate=True
                )
                
                if checkpoint_id and episode_reward > best_performance:
                    best_performance = episode_reward
            
            # Check for early stopping
            if episode > 30:
                should_stop = self.performance_tracker.should_stop_early(
                    patience=15,
                    min_improvement=2.0
                )
                if should_stop:
                    break
        
        # Verify results
        self.assertGreater(len(self.checkpoint_manager.checkpoints), 0)
        
        # Get best checkpoint
        best_checkpoint = self.checkpoint_manager.get_best_checkpoint('episode_reward')
        self.assertIsNotNone(best_checkpoint)
        
        # Get performance summary
        summary = self.performance_tracker.get_summary()
        self.assertGreater(summary['total_episodes'], 0)
        
        # Test loading best checkpoint
        new_agent = self._create_mock_agent()
        success = self.checkpoint_manager.load_checkpoint(new_agent, best_checkpoint)
        self.assertTrue(success)


if __name__ == '__main__':
    # Set random seeds for reproducibility
    np.random.seed(42)
    
    # Run tests
    unittest.main(verbosity=2)
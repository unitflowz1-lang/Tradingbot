"""
Test script for RL framework foundation

This script tests the basic functionality of the RL framework
foundation including configuration, logging, and monitoring.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.rl.config.manager import ConfigManager
from src.rl.monitoring.logger import RLLogger
from src.rl.monitoring.metrics import MetricsTracker
from src.rl.monitoring.monitor import TrainingMonitor


def test_config_manager():
    """Test configuration manager functionality."""
    print("Testing ConfigManager...")
    
    # Test loading default config
    config_manager = ConfigManager("config/rl_config.json")
    config = config_manager.get_config()
    
    assert config.training.learning_rate == 0.001
    assert config.network.hidden_layers == [256, 128, 64]
    assert config.environment.lookback_window == 20
    
    print("✓ ConfigManager working correctly")


def test_rl_logger():
    """Test RL logging functionality."""
    print("Testing RLLogger...")
    
    logger = RLLogger(log_dir="logs/test_rl", log_level="INFO")
    
    # Test different logging methods
    logger.log_training_start("DQN", {"learning_rate": 0.001})
    logger.log_training_episode(1, 10.5, 0.1, 0.9, 1.2)
    logger.log_system_event("test_event", "Testing system event")
    logger.info("Test info message")
    
    print("✓ RLLogger working correctly")


def test_metrics_tracker():
    """Test metrics tracking functionality."""
    print("Testing MetricsTracker...")
    
    tracker = MetricsTracker(window_size=10)
    
    # Record some test metrics
    for i in range(5):
        tracker.record_training_episode(i, i * 2.0, 0.1 - i * 0.01, 0.9 - i * 0.1, 100)
        tracker.record_performance_metrics(i * 0.1, i * 0.2, i * 0.05, 0.6, 1.2)
        tracker.record_system_metrics(0.01, 50.0, 25.0)
    
    # Get summaries
    training_summary = tracker.get_training_summary()
    performance_summary = tracker.get_performance_summary()
    system_summary = tracker.get_system_summary()
    
    assert training_summary['total_episodes'] == 5
    assert performance_summary['avg_returns'] >= 0
    assert system_summary['avg_inference_time'] == 0.01
    
    print("✓ MetricsTracker working correctly")


def test_training_monitor():
    """Test training monitor functionality."""
    print("Testing TrainingMonitor...")
    
    logger = RLLogger(log_dir="logs/test_rl")
    tracker = MetricsTracker()
    monitor = TrainingMonitor(patience=5, logger=logger, metrics_tracker=tracker)
    
    monitor.start_monitoring()
    
    # Simulate training episodes
    for i in range(3):
        should_continue = monitor.update(i, i * 2.0, 0.1, i * 0.5)
        assert should_continue == True
    
    summary = monitor.get_monitoring_summary()
    assert summary['monitoring_active'] == True
    assert summary['best_performance'] >= 0
    
    monitor.stop_monitoring()
    
    print("✓ TrainingMonitor working correctly")


def test_directory_structure():
    """Test that all directories and files are created correctly."""
    print("Testing directory structure...")
    
    # Check main RL module
    import src.rl
    from src.rl.environments import TradingEnvironment
    from src.rl.agents import RLAgent
    from src.rl.config import ConfigManager
    from src.rl.monitoring import RLLogger, MetricsTracker, TrainingMonitor
    
    print("✓ All imports working correctly")


def main():
    """Run all foundation tests."""
    print("Running RL Framework Foundation Tests")
    print("=" * 50)
    
    try:
        test_directory_structure()
        test_config_manager()
        test_rl_logger()
        test_metrics_tracker()
        test_training_monitor()
        
        print("\n" + "=" * 50)
        print("✅ All foundation tests passed!")
        print("RL framework foundation is working correctly.")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
        
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
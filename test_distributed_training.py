"""
Unit tests for distributed training capabilities.
"""
import unittest
import tempfile
import shutil
import time
import threading
from unittest.mock import Mock, patch, MagicMock
import os
import sys

# Add src to path for imports
sys.path.append('src')

import torch
import torch.distributed as dist
import numpy as np
import redis

from src.rl.training.distributed_trainer import (
    DistributedTrainer, DistributedConfig, run_distributed_worker
)
from src.rl.training.resource_manager import (
    ResourceManager, ResourceMonitor, AutoScaler, ResourceMetrics, ScalingDecision
)
from src.rl.agents.dqn_agent import DQNAgent
from src.rl.environments.trading_environment import TradingEnvironment

class TestDistributedTrainer(unittest.TestCase):
    """Test distributed training functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        
        # Mock Redis
        self.mock_redis = Mock(spec=redis.Redis)
        self.mock_redis.ping.return_value = True
        self.mock_redis.sadd.return_value = 1
        self.mock_redis.scard.return_value = 1
        self.mock_redis.hset.return_value = True
        self.mock_redis.expire.return_value = True
        
        # Create test config
        self.config = DistributedConfig(
            world_size=2,
            rank=0,
            master_addr="localhost",
            master_port="12355",
            backend="gloo",  # Use gloo for CPU testing
            sync_frequency=5,
            gradient_compression=True,
            redis_host="localhost",
            redis_port=6379
        )
    
    def tearDown(self):
        """Clean up test environment."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    @patch('redis.Redis')
    def test_distributed_trainer_initialization(self, mock_redis_class):
        """Test distributed trainer initialization."""
        mock_redis_class.return_value = self.mock_redis
        
        trainer = DistributedTrainer(self.config)
        
        self.assertEqual(trainer.rank, 0)
        self.assertEqual(trainer.world_size, 2)
        self.assertTrue(trainer.is_master)
        self.assertEqual(trainer.global_step, 0)
    
    @patch('redis.Redis')
    @patch('torch.distributed.init_process_group')
    def test_distributed_setup(self, mock_init_pg, mock_redis_class):
        """Test distributed training setup."""
        mock_redis_class.return_value = self.mock_redis
        mock_init_pg.return_value = None
        
        trainer = DistributedTrainer(self.config)
        
        # Mock successful setup
        with patch('torch.cuda.is_available', return_value=False):
            trainer.setup()
        
        self.assertIsNotNone(trainer.device)
        self.assertIsNotNone(trainer.redis_client)
        mock_init_pg.assert_called_once()
    
    @patch('redis.Redis')
    def test_model_wrapping(self, mock_redis_class):
        """Test model wrapping for distributed training."""
        mock_redis_class.return_value = self.mock_redis
        
        trainer = DistributedTrainer(self.config)
        trainer.device = torch.device('cpu')
        
        # Create simple model
        model = torch.nn.Linear(10, 5)
        
        # Test single GPU case (world_size = 1)
        trainer.world_size = 1
        wrapped_model = trainer.wrap_model(model)
        self.assertIsInstance(wrapped_model, torch.nn.Linear)
        
        # Test multi-GPU case
        trainer.world_size = 2
        with patch('torch.nn.parallel.DistributedDataParallel') as mock_ddp:
            mock_ddp.return_value = model
            wrapped_model = trainer.wrap_model(model)
            mock_ddp.assert_called_once()
    
    @patch('redis.Redis')
    def test_gradient_compression(self, mock_redis_class):
        """Test gradient compression functionality."""
        mock_redis_class.return_value = self.mock_redis
        
        trainer = DistributedTrainer(self.config)
        
        # Create test gradient
        gradient = torch.randn(100, 50)
        
        # Test compression
        compressed = trainer._compress_gradient(gradient)
        
        # Check that compression reduces non-zero elements
        original_nonzero = torch.count_nonzero(gradient)
        compressed_nonzero = torch.count_nonzero(compressed)
        
        self.assertLessEqual(compressed_nonzero, original_nonzero)
        self.assertEqual(compressed.shape, gradient.shape)
    
    @patch('redis.Redis')
    def test_gradient_queuing(self, mock_redis_class):
        """Test gradient queuing for async updates."""
        mock_redis_class.return_value = self.mock_redis
        
        trainer = DistributedTrainer(self.config)
        
        # Create mock agent with networks
        mock_agent = Mock()
        mock_network = Mock()
        mock_param = Mock()
        mock_param.grad = torch.randn(10, 5)
        mock_network.named_parameters.return_value = [('param1', mock_param)]
        mock_agent.q_network = mock_network
        
        # Test gradient queuing
        trainer._queue_gradients(mock_agent)
        
        # Check that gradients were queued
        self.assertFalse(trainer.gradient_queue.empty())
    
    @patch('redis.Redis')
    def test_worker_synchronization(self, mock_redis_class):
        """Test worker synchronization."""
        mock_redis_class.return_value = self.mock_redis
        
        trainer = DistributedTrainer(self.config)
        trainer.redis_client = self.mock_redis
        
        # Mock distributed barrier
        with patch('torch.distributed.barrier') as mock_barrier:
            with patch('torch.distributed.is_initialized', return_value=True):
                trainer._synchronize_workers()
                
                mock_barrier.assert_called_once()
                self.mock_redis.sadd.assert_called()
                self.mock_redis.expire.assert_called()

class TestResourceManager(unittest.TestCase):
    """Test resource management functionality."""
    
    def setUp(self):
        """Set up test environment."""
        self.config = {
            'monitoring_interval': 1.0,  # Fast for testing
            'namespace': 'test-namespace',
            'deployment_name': 'test-deployment',
            'min_replicas': 1,
            'max_replicas': 5,
            'scale_up_threshold': 80.0,
            'scale_down_threshold': 30.0,
            'cooldown_minutes': 1,
            'redis_host': 'localhost',
            'redis_port': 6379
        }
    
    def test_resource_metrics_collection(self):
        """Test resource metrics collection."""
        monitor = ResourceMonitor(monitoring_interval=0.1)
        
        # Collect metrics
        metrics = monitor._collect_metrics()
        
        self.assertIsInstance(metrics, ResourceMetrics)
        self.assertGreaterEqual(metrics.cpu_percent, 0)
        self.assertGreaterEqual(metrics.memory_percent, 0)
        self.assertGreater(metrics.timestamp, 0)
    
    def test_resource_monitor_history(self):
        """Test resource monitor history management."""
        monitor = ResourceMonitor(monitoring_interval=0.1)
        
        # Add some metrics
        for i in range(5):
            metrics = ResourceMetrics(
                cpu_percent=50.0 + i,
                memory_percent=60.0 + i,
                gpu_percent=0.0,
                gpu_memory_percent=0.0,
                disk_io_percent=0.0,
                network_io_mbps=0.0,
                timestamp=time.time() + i
            )
            monitor._store_metrics(metrics)
        
        # Check history
        self.assertEqual(len(monitor.metrics_history), 5)
        
        # Test current metrics
        current = monitor.get_current_metrics()
        self.assertIsNotNone(current)
        self.assertEqual(current.cpu_percent, 54.0)
    
    def test_average_metrics_calculation(self):
        """Test average metrics calculation."""
        monitor = ResourceMonitor(monitoring_interval=0.1)
        
        # Add metrics with known values
        base_time = time.time()
        for i in range(3):
            metrics = ResourceMetrics(
                cpu_percent=50.0 + i * 10,  # 50, 60, 70
                memory_percent=40.0 + i * 5,  # 40, 45, 50
                gpu_percent=0.0,
                gpu_memory_percent=0.0,
                disk_io_percent=0.0,
                network_io_mbps=0.0,
                timestamp=base_time + i
            )
            monitor._store_metrics(metrics)
        
        # Calculate averages
        avg_metrics = monitor.get_average_metrics(window_minutes=1)
        
        self.assertIsNotNone(avg_metrics)
        self.assertAlmostEqual(avg_metrics.cpu_percent, 60.0, places=1)
        self.assertAlmostEqual(avg_metrics.memory_percent, 45.0, places=1)
    
    @patch('kubernetes.client.AppsV1Api')
    def test_autoscaler_scaling_decisions(self, mock_k8s_client):
        """Test autoscaler scaling decisions."""
        # Mock Kubernetes client
        mock_deployment = Mock()
        mock_deployment.spec.replicas = 2
        mock_k8s_client.return_value.read_namespaced_deployment.return_value = mock_deployment
        
        autoscaler = AutoScaler(
            namespace='test',
            deployment_name='test-deployment',
            min_replicas=1,
            max_replicas=5,
            scale_up_threshold=80.0,
            scale_down_threshold=30.0
        )
        autoscaler.k8s_apps_v1 = mock_k8s_client.return_value
        
        # Test scale up decision
        high_pressure_metrics = ResourceMetrics(
            cpu_percent=90.0,
            memory_percent=85.0,
            gpu_percent=80.0,
            gpu_memory_percent=0.0,
            disk_io_percent=0.0,
            network_io_mbps=0.0,
            timestamp=time.time()
        )
        
        autoscaler.resource_monitor.metrics_history = [high_pressure_metrics]
        decision = autoscaler._make_scaling_decision()
        
        self.assertEqual(decision.action, 'scale_up')
        self.assertGreater(decision.target_replicas, 2)
        self.assertGreater(decision.confidence, 0)
        
        # Test scale down decision
        low_pressure_metrics = ResourceMetrics(
            cpu_percent=20.0,
            memory_percent=25.0,
            gpu_percent=15.0,
            gpu_memory_percent=0.0,
            disk_io_percent=0.0,
            network_io_mbps=0.0,
            timestamp=time.time()
        )
        
        autoscaler.resource_monitor.metrics_history = [low_pressure_metrics]
        decision = autoscaler._make_scaling_decision()
        
        self.assertEqual(decision.action, 'scale_down')
        self.assertLess(decision.target_replicas, 2)
        self.assertGreater(decision.confidence, 0)
    
    @patch('redis.Redis')
    def test_resource_manager_initialization(self, mock_redis_class):
        """Test resource manager initialization."""
        mock_redis = Mock()
        mock_redis_class.return_value = mock_redis
        
        manager = ResourceManager(self.config)
        
        self.assertIsNotNone(manager.resource_monitor)
        self.assertIsNotNone(manager.autoscaler)
        self.assertIsNotNone(manager.redis_client)
    
    @patch('redis.Redis')
    def test_cluster_metrics_aggregation(self, mock_redis_class):
        """Test cluster metrics aggregation."""
        mock_redis = Mock()
        mock_redis_class.return_value = mock_redis
        
        # Mock Redis data
        worker_metrics = {
            'worker1': '{"cpu_percent": 50.0, "memory_percent": 60.0, "gpu_percent": 40.0, "timestamp": 1234567890}',
            'worker2': '{"cpu_percent": 70.0, "memory_percent": 80.0, "gpu_percent": 60.0, "timestamp": 1234567890}'
        }
        mock_redis.hgetall.return_value = worker_metrics
        
        manager = ResourceManager(self.config)
        cluster_metrics = manager.get_cluster_metrics()
        
        self.assertIn('average_cpu_percent', cluster_metrics)
        self.assertIn('average_memory_percent', cluster_metrics)
        self.assertIn('active_workers', cluster_metrics)
        
        # Check averages
        self.assertAlmostEqual(cluster_metrics['average_cpu_percent'], 60.0, places=1)
        self.assertAlmostEqual(cluster_metrics['average_memory_percent'], 70.0, places=1)
        self.assertEqual(cluster_metrics['active_workers'], 2)

class TestDistributedCoordination(unittest.TestCase):
    """Test distributed training coordination."""
    
    def setUp(self):
        """Set up test environment."""
        self.mock_redis = Mock(spec=redis.Redis)
        self.mock_redis.ping.return_value = True
    
    @patch('redis.Redis')
    def test_gradient_synchronization_coordination(self, mock_redis_class):
        """Test gradient synchronization coordination."""
        mock_redis_class.return_value = self.mock_redis
        
        config = DistributedConfig(
            world_size=2,
            rank=0,
            sync_frequency=1,
            gradient_compression=True
        )
        
        trainer = DistributedTrainer(config)
        trainer.redis_client = self.mock_redis
        
        # Create mock gradients
        test_gradients = {
            'q_network': {
                'layer1.weight': torch.randn(10, 5),
                'layer1.bias': torch.randn(10)
            }
        }
        
        # Test async gradient sync
        trainer._sync_gradients_async(test_gradients)
        
        # Verify Redis calls
        self.mock_redis.hset.assert_called()
        self.mock_redis.expire.assert_called()
        self.mock_redis.lpush.assert_called()
    
    @patch('redis.Redis')
    def test_worker_coordination(self, mock_redis_class):
        """Test worker coordination through Redis."""
        mock_redis_class.return_value = self.mock_redis
        
        # Simulate multiple workers checking in
        self.mock_redis.scard.side_effect = [1, 2, 2]  # Simulate workers joining
        
        config = DistributedConfig(world_size=2, rank=0)
        trainer = DistributedTrainer(config)
        trainer.redis_client = self.mock_redis
        
        # Test synchronization
        with patch('torch.distributed.barrier'):
            with patch('torch.distributed.is_initialized', return_value=True):
                trainer._synchronize_workers()
        
        # Verify coordination calls
        self.mock_redis.sadd.assert_called()
        self.mock_redis.scard.assert_called()

if __name__ == '__main__':
    # Set up logging
    import logging
    logging.basicConfig(level=logging.INFO)
    
    # Run tests
    unittest.main(verbosity=2)
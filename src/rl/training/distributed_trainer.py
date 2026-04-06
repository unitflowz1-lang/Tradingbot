"""
Distributed training framework for RL agents.
"""
import os
import time
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import threading
import queue

import torch
import torch.distributed as dist
import torch.multiprocessing as mp
from torch.nn.parallel import DistributedDataParallel as DDP
import redis
import numpy as np

from ..agents.base_agent import BaseAgent
from ..environments.trading_environment import TradingEnvironment
from .agent_trainer import TrainingConfig, TrainingResults
from ..data.loader import DataLoader
from ..monitoring.performance_tracker import PerformanceTracker

logger = logging.getLogger(__name__)

@dataclass
class DistributedConfig:
    """Configuration for distributed training."""
    world_size: int = 4
    rank: int = 0
    master_addr: str = "localhost"
    master_port: str = "12355"
    backend: str = "nccl"  # or "gloo" for CPU
    sync_frequency: int = 10
    gradient_compression: bool = True
    async_updates: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    worker_timeout: int = 300

class DistributedTrainer:
    """Distributed trainer for RL agents."""
    
    def __init__(self, config: DistributedConfig):
        self.config = config
        self.rank = config.rank
        self.world_size = config.world_size
        self.device = None
        self.redis_client = None
        self.is_master = (config.rank == 0)
        
        # Training state
        self.global_step = 0
        self.sync_step = 0
        self.gradient_buffer = {}
        self.performance_tracker = PerformanceTracker()
        
        # Synchronization
        self.sync_lock = threading.Lock()
        self.gradient_queue = queue.Queue()
        
    def setup(self):
        """Initialize distributed training environment."""
        try:
            # Set up distributed process group
            os.environ['MASTER_ADDR'] = self.config.master_addr
            os.environ['MASTER_PORT'] = self.config.master_port
            
            # Initialize process group
            dist.init_process_group(
                backend=self.config.backend,
                rank=self.rank,
                world_size=self.world_size,
                timeout=torch.distributed.default_pg_timeout
            )
            
            # Set device
            if torch.cuda.is_available() and self.config.backend == "nccl":
                self.device = torch.device(f"cuda:{self.rank}")
                torch.cuda.set_device(self.device)
            else:
                self.device = torch.device("cpu")
            
            # Initialize Redis for coordination
            self.redis_client = redis.Redis(
                host=self.config.redis_host,
                port=self.config.redis_port,
                decode_responses=True,
                socket_timeout=10
            )
            
            logger.info(f"Distributed training setup complete - Rank: {self.rank}, Device: {self.device}")
            
        except Exception as e:
            logger.error(f"Failed to setup distributed training: {e}")
            raise
    
    def cleanup(self):
        """Clean up distributed training environment."""
        try:
            if dist.is_initialized():
                dist.destroy_process_group()
            logger.info("Distributed training cleanup complete")
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
    
    def wrap_model(self, model: torch.nn.Module) -> torch.nn.Module:
        """Wrap model for distributed training."""
        model = model.to(self.device)
        
        if self.world_size > 1:
            # Use DistributedDataParallel for multi-GPU training
            model = DDP(
                model,
                device_ids=[self.device] if self.device.type == 'cuda' else None,
                find_unused_parameters=True
            )
        
        return model
    
    def train_distributed(
        self,
        agent: BaseAgent,
        environment: TradingEnvironment,
        training_config: TrainingConfig,
        data_loader: DataLoader
    ) -> TrainingResults:
        """Train agent using distributed training."""
        
        logger.info(f"Starting distributed training - Rank: {self.rank}")
        
        # Wrap agent's networks for distributed training
        if hasattr(agent, 'q_network'):
            agent.q_network = self.wrap_model(agent.q_network)
        if hasattr(agent, 'target_network'):
            agent.target_network = self.wrap_model(agent.target_network)
        if hasattr(agent, 'policy_network'):
            agent.policy_network = self.wrap_model(agent.policy_network)
        if hasattr(agent, 'value_network'):
            agent.value_network = self.wrap_model(agent.value_network)
        
        # Initialize training state
        episode_rewards = []
        episode_lengths = []
        loss_history = []
        
        # Start gradient synchronization thread
        if self.config.async_updates:
            sync_thread = threading.Thread(target=self._gradient_sync_worker)
            sync_thread.daemon = True
            sync_thread.start()
        
        try:
            for episode in range(training_config.num_episodes):
                episode_start_time = time.time()
                
                # Reset environment
                state = environment.reset()
                episode_reward = 0
                episode_length = 0
                episode_losses = []
                
                while True:
                    # Select action
                    action = agent.select_action(state, training=True)
                    
                    # Take step in environment
                    next_state, reward, done, info = environment.step(action)
                    
                    # Store experience
                    agent.store_experience(state, action, reward, next_state, done)
                    
                    # Update agent
                    if agent.can_update():
                        loss = agent.update()
                        if loss is not None:
                            episode_losses.append(loss)
                            
                            # Queue gradients for synchronization
                            if self.config.async_updates:
                                self._queue_gradients(agent)
                    
                    state = next_state
                    episode_reward += reward
                    episode_length += 1
                    self.global_step += 1
                    
                    # Synchronize gradients periodically
                    if (self.global_step % self.config.sync_frequency == 0 and 
                        not self.config.async_updates):
                        self._synchronize_gradients(agent)
                    
                    if done:
                        break
                
                # Record episode statistics
                episode_rewards.append(episode_reward)
                episode_lengths.append(episode_length)
                if episode_losses:
                    loss_history.append(np.mean(episode_losses))
                
                # Log progress (master only)
                if self.is_master and episode % 100 == 0:
                    avg_reward = np.mean(episode_rewards[-100:])
                    avg_loss = np.mean(loss_history[-100:]) if loss_history else 0
                    logger.info(
                        f"Episode {episode}: Avg Reward: {avg_reward:.2f}, "
                        f"Avg Loss: {avg_loss:.4f}, Episode Time: {time.time() - episode_start_time:.2f}s"
                    )
                
                # Checkpoint saving (master only)
                if (self.is_master and 
                    episode % training_config.checkpoint_frequency == 0 and 
                    episode > 0):
                    self._save_distributed_checkpoint(agent, episode)
                
                # Synchronize workers
                if episode % 50 == 0:
                    self._synchronize_workers()
        
        except Exception as e:
            logger.error(f"Error during distributed training: {e}")
            raise
        
        finally:
            # Final synchronization
            self._synchronize_gradients(agent)
            
        # Return training results
        return TrainingResults(
            episode_rewards=episode_rewards,
            episode_lengths=episode_lengths,
            loss_history=loss_history,
            training_time=time.time() - episode_start_time,
            final_performance=self.performance_tracker.get_current_metrics()
        )
    
    def _queue_gradients(self, agent: BaseAgent):
        """Queue gradients for asynchronous synchronization."""
        try:
            gradients = {}
            
            # Extract gradients from agent's networks
            for name, network in self._get_agent_networks(agent).items():
                if hasattr(network, 'parameters'):
                    net_gradients = {}
                    for param_name, param in network.named_parameters():
                        if param.grad is not None:
                            net_gradients[param_name] = param.grad.clone().detach()
                    gradients[name] = net_gradients
            
            # Queue for synchronization
            self.gradient_queue.put({
                'step': self.global_step,
                'gradients': gradients,
                'timestamp': time.time()
            })
            
        except Exception as e:
            logger.error(f"Error queuing gradients: {e}")
    
    def _gradient_sync_worker(self):
        """Background worker for gradient synchronization."""
        while True:
            try:
                # Get gradients from queue (blocking)
                gradient_data = self.gradient_queue.get(timeout=1.0)
                
                # Synchronize gradients
                self._sync_gradients_async(gradient_data['gradients'])
                
                self.gradient_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error in gradient sync worker: {e}")
    
    def _synchronize_gradients(self, agent: BaseAgent):
        """Synchronize gradients across all workers."""
        if self.world_size <= 1:
            return
        
        try:
            with self.sync_lock:
                # Get agent networks
                networks = self._get_agent_networks(agent)
                
                for name, network in networks.items():
                    if hasattr(network, 'parameters'):
                        for param in network.parameters():
                            if param.grad is not None:
                                # All-reduce gradients
                                if self.config.gradient_compression:
                                    # Simple gradient compression (top-k or quantization)
                                    compressed_grad = self._compress_gradient(param.grad)
                                    dist.all_reduce(compressed_grad, op=dist.ReduceOp.SUM)
                                    param.grad = self._decompress_gradient(compressed_grad)
                                else:
                                    dist.all_reduce(param.grad, op=dist.ReduceOp.SUM)
                                
                                # Average gradients
                                param.grad /= self.world_size
                
                self.sync_step += 1
                logger.debug(f"Synchronized gradients - Step: {self.sync_step}")
                
        except Exception as e:
            logger.error(f"Error synchronizing gradients: {e}")
    
    def _sync_gradients_async(self, gradients: Dict[str, Dict[str, torch.Tensor]]):
        """Asynchronously synchronize gradients using Redis."""
        try:
            # Serialize gradients
            serialized_gradients = {}
            for net_name, net_gradients in gradients.items():
                serialized_gradients[net_name] = {}
                for param_name, grad_tensor in net_gradients.items():
                    # Convert to numpy and compress
                    grad_np = grad_tensor.cpu().numpy()
                    if self.config.gradient_compression:
                        grad_np = self._compress_gradient_numpy(grad_np)
                    
                    serialized_gradients[net_name][param_name] = grad_np.tobytes()
            
            # Store in Redis with worker ID
            gradient_key = f"gradients:step:{self.global_step}:worker:{self.rank}"
            self.redis_client.hset(gradient_key, mapping=serialized_gradients)
            self.redis_client.expire(gradient_key, 300)  # 5 minute expiry
            
            # Signal gradient availability
            self.redis_client.lpush("gradient_queue", gradient_key)
            
        except Exception as e:
            logger.error(f"Error in async gradient sync: {e}")
    
    def _compress_gradient(self, gradient: torch.Tensor) -> torch.Tensor:
        """Compress gradient tensor (simple top-k compression)."""
        if not self.config.gradient_compression:
            return gradient
        
        # Top-k compression (keep top 10% of gradients by magnitude)
        flat_grad = gradient.flatten()
        k = max(1, int(0.1 * flat_grad.numel()))
        
        # Get top-k indices
        _, top_indices = torch.topk(torch.abs(flat_grad), k)
        
        # Create sparse gradient
        compressed = torch.zeros_like(flat_grad)
        compressed[top_indices] = flat_grad[top_indices]
        
        return compressed.reshape(gradient.shape)
    
    def _decompress_gradient(self, compressed_gradient: torch.Tensor) -> torch.Tensor:
        """Decompress gradient tensor."""
        return compressed_gradient  # Simple case - no decompression needed
    
    def _compress_gradient_numpy(self, gradient: np.ndarray) -> np.ndarray:
        """Compress gradient using numpy (for Redis storage)."""
        if not self.config.gradient_compression:
            return gradient
        
        # Simple quantization to reduce size
        return np.round(gradient * 1000).astype(np.int16)
    
    def _get_agent_networks(self, agent: BaseAgent) -> Dict[str, torch.nn.Module]:
        """Get all networks from agent."""
        networks = {}
        
        if hasattr(agent, 'q_network'):
            networks['q_network'] = agent.q_network
        if hasattr(agent, 'target_network'):
            networks['target_network'] = agent.target_network
        if hasattr(agent, 'policy_network'):
            networks['policy_network'] = agent.policy_network
        if hasattr(agent, 'value_network'):
            networks['value_network'] = agent.value_network
        
        return networks
    
    def _save_distributed_checkpoint(self, agent: BaseAgent, episode: int):
        """Save checkpoint in distributed training."""
        try:
            checkpoint_path = f"/app/checkpoints/distributed_checkpoint_ep_{episode}_rank_{self.rank}.pt"
            
            # Save agent state
            agent.save_checkpoint(checkpoint_path)
            
            # Master saves additional metadata
            if self.is_master:
                metadata = {
                    'episode': episode,
                    'global_step': self.global_step,
                    'world_size': self.world_size,
                    'sync_step': self.sync_step
                }
                
                metadata_path = f"/app/checkpoints/training_metadata_ep_{episode}.pt"
                torch.save(metadata, metadata_path)
            
            logger.info(f"Saved distributed checkpoint at episode {episode}")
            
        except Exception as e:
            logger.error(f"Error saving distributed checkpoint: {e}")
    
    def _synchronize_workers(self):
        """Synchronize all workers at a barrier."""
        if self.world_size > 1:
            try:
                # Use distributed barrier
                dist.barrier()
                
                # Additional Redis-based synchronization for robustness
                sync_key = f"worker_sync:{self.global_step}"
                self.redis_client.sadd(sync_key, str(self.rank))
                self.redis_client.expire(sync_key, 60)
                
                # Wait for all workers
                timeout = time.time() + self.config.worker_timeout
                while time.time() < timeout:
                    worker_count = self.redis_client.scard(sync_key)
                    if worker_count >= self.world_size:
                        break
                    time.sleep(1)
                
                logger.debug(f"Worker synchronization complete - Step: {self.global_step}")
                
            except Exception as e:
                logger.error(f"Error synchronizing workers: {e}")

def run_distributed_worker(rank: int, world_size: int, config_dict: Dict[str, Any]):
    """Run distributed training worker."""
    try:
        # Create distributed config
        dist_config = DistributedConfig(
            rank=rank,
            world_size=world_size,
            **config_dict
        )
        
        # Initialize trainer
        trainer = DistributedTrainer(dist_config)
        trainer.setup()
        
        # Load agent, environment, and data
        # This would be loaded from the main process or configuration
        agent = None  # Load from config
        environment = None  # Load from config
        training_config = None  # Load from config
        data_loader = None  # Load from config
        
        # Run training
        results = trainer.train_distributed(agent, environment, training_config, data_loader)
        
        # Cleanup
        trainer.cleanup()
        
        return results
        
    except Exception as e:
        logger.error(f"Error in distributed worker {rank}: {e}")
        raise

def launch_distributed_training(
    world_size: int,
    config: Dict[str, Any],
    spawn_method: str = "spawn"
) -> List[TrainingResults]:
    """Launch distributed training across multiple processes."""
    
    logger.info(f"Launching distributed training with {world_size} workers")
    
    try:
        # Set multiprocessing start method
        mp.set_start_method(spawn_method, force=True)
        
        # Spawn training processes
        processes = []
        results = mp.Manager().list()
        
        for rank in range(world_size):
            p = mp.Process(
                target=run_distributed_worker,
                args=(rank, world_size, config)
            )
            p.start()
            processes.append(p)
        
        # Wait for all processes to complete
        for p in processes:
            p.join()
        
        logger.info("Distributed training completed successfully")
        return list(results)
        
    except Exception as e:
        logger.error(f"Error launching distributed training: {e}")
        raise

if __name__ == "__main__":
    # Example usage
    config = {
        'master_addr': os.getenv('MASTER_ADDR', 'localhost'),
        'master_port': os.getenv('MASTER_PORT', '12355'),
        'redis_host': os.getenv('REDIS_HOST', 'localhost'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379)),
        'sync_frequency': 10,
        'gradient_compression': True
    }
    
    world_size = int(os.getenv('WORLD_SIZE', 4))
    
    results = launch_distributed_training(world_size, config)
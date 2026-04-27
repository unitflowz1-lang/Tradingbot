"""
Batch Manager for RL Training

Handles efficient batching of training data for RL agents,
including sequence generation and memory management.
"""

import numpy as np
from typing import List, Dict, Optional, Tuple, Iterator, Union, Any
from dataclasses import dataclass, field
import random
from collections import deque
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
import time

from ...models import MarketData
from .loader import HistoricalDataLoader
from .preprocessor import DataPreprocessor


@dataclass
class BatchConfig:
    """Configuration for batch manager."""
    
    # Batch settings
    batch_size: int = 32
    sequence_length: int = 100
    overlap_ratio: float = 0.1
    
    # Sampling strategy
    sampling_strategy: str = "random"  # "random", "sequential", "weighted"
    shuffle_batches: bool = True
    
    # Memory management
    max_batches_in_memory: int = 100
    prefetch_batches: int = 5
    use_multiprocessing: bool = True
    num_workers: int = 4
    
    # Data augmentation
    enable_augmentation: bool = False
    augmentation_probability: float = 0.3
    
    # Validation split
    validation_split: float = 0.2
    test_split: float = 0.1
    
    # Advanced batching
    enable_curriculum_learning: bool = False
    curriculum_stages: List[Dict[str, Any]] = field(default_factory=list)
    
    # Performance monitoring
    track_batch_stats: bool = True
    log_batch_creation: bool = False


class BatchManager:
    """
    Efficient batch manager for RL training data.
    
    Handles creation of training batches from historical market data,
    with support for sequence generation, data augmentation, and
    memory-efficient processing.
    """
    
    def __init__(self, 
                 config: BatchConfig,
                 data_loader: HistoricalDataLoader,
                 preprocessor: DataPreprocessor):
        """
        Initialize batch manager.
        
        Args:
            config: Batch manager configuration
            data_loader: Historical data loader
            preprocessor: Data preprocessor
        """
        self.config = config
        self.data_loader = data_loader
        self.preprocessor = preprocessor
        self.logger = logging.getLogger(__name__)
        
        # Batch cache
        self._batch_cache = deque(maxlen=self.config.max_batches_in_memory)
        self._cache_lock = threading.Lock()
        
        # Data splits
        self.train_data = []
        self.val_data = []
        self.test_data = []
        
        # Curriculum learning
        self.current_curriculum_stage = 0
        
        # Statistics
        self.batch_stats = {
            "total_batches_created": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "avg_batch_creation_time": 0.0,
            "total_sequences": 0
        }
        
        # Threading
        self.executor = None
        if self.config.use_multiprocessing:
            self.executor = ThreadPoolExecutor(max_workers=self.config.num_workers)
            
    def prepare_data(self, 
                    symbols: List[str],
                    timeframes: List[str],
                    start_date: Optional[str] = None,
                    end_date: Optional[str] = None) -> None:
        """
        Prepare and split data for training.
        
        Args:
            symbols: List of currency pair symbols
            timeframes: List of timeframes to load
            start_date: Start date for data loading
            end_date: End date for data loading
        """
        self.logger.info(f"Preparing data for {len(symbols)} symbols and {len(timeframes)} timeframes")
        
        # Load all data
        all_data = []
        for symbol in symbols:
            for timeframe in timeframes:
                try:
                    data = self.data_loader.load_data(symbol, timeframe, start_date, end_date)
                    all_data.extend(data)
                except Exception as e:
                    self.logger.error(f"Failed to load data for {symbol} {timeframe}: {e}")
                    
        # Sort by timestamp
        all_data.sort(key=lambda x: x.timestamp)
        
        # Split data
        self._split_data(all_data)
        
        # Fit preprocessor on training data
        if not self.preprocessor.is_fitted:
            self.preprocessor.fit(self.train_data)
            
        self.logger.info(f"Data prepared: {len(self.train_data)} train, {len(self.val_data)} val, {len(self.test_data)} test")
        
    def get_train_batches(self) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """
        Get iterator for training batches.
        
        Yields:
            Tuples of (states, next_states) for training
        """
        return self._get_batches(self.train_data, "train")
        
    def get_validation_batches(self) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """
        Get iterator for validation batches.
        
        Yields:
            Tuples of (states, next_states) for validation
        """
        return self._get_batches(self.val_data, "validation")
        
    def get_test_batches(self) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """
        Get iterator for test batches.
        
        Yields:
            Tuples of (states, next_states) for testing
        """
        return self._get_batches(self.test_data, "test")
        
    def create_single_batch(self, data: List[MarketData]) -> Tuple[np.ndarray, np.ndarray]:
        """
        Create a single batch from market data.
        
        Args:
            data: List of MarketData objects
            
        Returns:
            Tuple of (states, next_states) arrays
        """
        start_time = time.time()
        
        # Preprocess data
        features = self.preprocessor.transform(data)
        
        # Create sequences
        sequences = self._create_sequences(features)
        
        # Create batch
        states = []
        next_states = []
        
        for sequence in sequences:
            if len(sequence) >= self.config.sequence_length + 1:
                state_seq = sequence[:-1]  # All but last
                next_state_seq = sequence[1:]  # All but first
                
                states.append(state_seq)
                next_states.append(next_state_seq)
                
        if not states:
            # Return empty batch if no valid sequences
            feature_dim = features.shape[1] if len(features.shape) > 1 else 1
            return (np.zeros((0, self.config.sequence_length, feature_dim)),
                   np.zeros((0, self.config.sequence_length, feature_dim)))
            
        states_array = np.array(states)
        next_states_array = np.array(next_states)
        
        # Apply data augmentation if enabled
        if self.config.enable_augmentation:
            states_array, next_states_array = self._apply_augmentation(states_array, next_states_array)
            
        # Update statistics
        creation_time = time.time() - start_time
        self.batch_stats["total_batches_created"] += 1
        self.batch_stats["avg_batch_creation_time"] = (
            (self.batch_stats["avg_batch_creation_time"] * (self.batch_stats["total_batches_created"] - 1) + creation_time) /
            self.batch_stats["total_batches_created"]
        )
        self.batch_stats["total_sequences"] += len(states)
        
        if self.config.log_batch_creation:
            self.logger.debug(f"Created batch with {len(states)} sequences in {creation_time:.3f}s")
            
        return states_array, next_states_array
        
    def get_batch_statistics(self) -> Dict[str, Any]:
        """Get batch creation statistics."""
        stats = self.batch_stats.copy()
        
        # Add cache statistics
        total_requests = stats["cache_hits"] + stats["cache_misses"]
        if total_requests > 0:
            stats["cache_hit_rate"] = stats["cache_hits"] / total_requests
        else:
            stats["cache_hit_rate"] = 0.0
            
        # Add data split information
        stats["train_samples"] = len(self.train_data)
        stats["val_samples"] = len(self.val_data)
        stats["test_samples"] = len(self.test_data)
        
        return stats
        
    def clear_cache(self) -> None:
        """Clear batch cache."""
        with self._cache_lock:
            self._batch_cache.clear()
            
    def update_curriculum_stage(self) -> None:
        """Update curriculum learning stage."""
        if not self.config.enable_curriculum_learning:
            return
            
        if self.current_curriculum_stage < len(self.config.curriculum_stages) - 1:
            self.current_curriculum_stage += 1
            self.logger.info(f"Advanced to curriculum stage {self.current_curriculum_stage}")
            
    def _split_data(self, data: List[MarketData]) -> None:
        """Split data into train/validation/test sets."""
        total_samples = len(data)
        
        # Calculate split indices
        test_idx = int(total_samples * (1 - self.config.test_split))
        val_idx = int(test_idx * (1 - self.config.validation_split))
        
        # Split data chronologically (important for time series)
        self.train_data = data[:val_idx]
        self.val_data = data[val_idx:test_idx]
        self.test_data = data[test_idx:]
        
    def _get_batches(self, data: List[MarketData], split_name: str) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """Get batch iterator for specified data split."""
        if not data:
            return
            
        # Calculate number of batches
        min_sequence_length = self.config.sequence_length + 1
        if len(data) < min_sequence_length:
            self.logger.warning(f"Insufficient data for {split_name}: {len(data)} < {min_sequence_length}")
            return
            
        # Create batch indices
        batch_indices = self._create_batch_indices(len(data))
        
        if self.config.shuffle_batches and split_name == "train":
            random.shuffle(batch_indices)
            
        # Generate batches
        for start_idx, end_idx in batch_indices:
            batch_data = data[start_idx:end_idx]
            
            if len(batch_data) >= min_sequence_length:
                yield self.create_single_batch(batch_data)
                
    def _create_batch_indices(self, data_length: int) -> List[Tuple[int, int]]:
        """Create indices for batching data."""
        indices = []
        
        if self.config.sampling_strategy == "sequential":
            # Sequential batching with overlap
            step_size = int(self.config.sequence_length * (1 - self.config.overlap_ratio))
            
            for start in range(0, data_length - self.config.sequence_length, step_size):
                end = min(start + self.config.sequence_length * self.config.batch_size, data_length)
                indices.append((start, end))
                
        elif self.config.sampling_strategy == "random":
            # Random sampling
            min_batch_length = self.config.sequence_length * self.config.batch_size
            
            for _ in range(max(1, (data_length - min_batch_length) // min_batch_length)):
                start = random.randint(0, max(0, data_length - min_batch_length))
                end = min(start + min_batch_length, data_length)
                indices.append((start, end))
                
        else:  # weighted sampling
            indices = self._create_weighted_indices(data_length)
            
        return indices
        
    def _create_weighted_indices(self, data_length: int) -> List[Tuple[int, int]]:
        """Create weighted sampling indices (placeholder for advanced sampling)."""
        # This could implement more sophisticated sampling strategies
        # For now, fall back to sequential
        return self._create_batch_indices_sequential(data_length)
        
    def _create_batch_indices_sequential(self, data_length: int) -> List[Tuple[int, int]]:
        """Create sequential batch indices."""
        indices = []
        batch_length = self.config.sequence_length * self.config.batch_size
        step_size = int(batch_length * (1 - self.config.overlap_ratio))
        
        for start in range(0, data_length - batch_length, step_size):
            end = start + batch_length
            indices.append((start, end))
            
        return indices
        
    def _create_sequences(self, features: np.ndarray) -> List[np.ndarray]:
        """Create sequences from feature matrix."""
        sequences = []
        
        if len(features) < self.config.sequence_length + 1:
            return sequences
            
        # Apply curriculum learning if enabled
        sequence_length = self._get_current_sequence_length()
        
        # Create overlapping sequences
        step_size = max(1, int(sequence_length * (1 - self.config.overlap_ratio)))
        
        for i in range(0, len(features) - sequence_length, step_size):
            sequence = features[i:i + sequence_length + 1]  # +1 for next state
            sequences.append(sequence)
            
            if len(sequences) >= self.config.batch_size:
                break
                
        return sequences
        
    def _get_current_sequence_length(self) -> int:
        """Get current sequence length based on curriculum learning."""
        if not self.config.enable_curriculum_learning:
            return self.config.sequence_length
            
        if self.current_curriculum_stage < len(self.config.curriculum_stages):
            stage_config = self.config.curriculum_stages[self.current_curriculum_stage]
            return stage_config.get("sequence_length", self.config.sequence_length)
            
        return self.config.sequence_length
        
    def _apply_augmentation(self, 
                          states: np.ndarray, 
                          next_states: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Apply data augmentation to batch."""
        if not self.config.enable_augmentation:
            return states, next_states
            
        augmented_states = []
        augmented_next_states = []
        
        for i in range(len(states)):
            # Original sequence
            augmented_states.append(states[i])
            augmented_next_states.append(next_states[i])
            
            # Apply augmentation with probability
            if random.random() < self.config.augmentation_probability:
                # Add noise augmentation
                noise_factor = 0.01
                noisy_state = states[i] + np.random.normal(0, noise_factor, states[i].shape)
                noisy_next_state = next_states[i] + np.random.normal(0, noise_factor, next_states[i].shape)
                
                augmented_states.append(noisy_state)
                augmented_next_states.append(noisy_next_state)
                
        return np.array(augmented_states), np.array(augmented_next_states)
        
    def __del__(self):
        """Cleanup resources."""
        if self.executor:
            self.executor.shutdown(wait=True)


class SequenceBatch:
    """
    Container for a batch of sequences with metadata.
    """
    
    def __init__(self, 
                 states: np.ndarray,
                 next_states: np.ndarray,
                 metadata: Optional[Dict[str, Any]] = None):
        """
        Initialize sequence batch.
        
        Args:
            states: State sequences array
            next_states: Next state sequences array  
            metadata: Optional metadata dictionary
        """
        self.states = states
        self.next_states = next_states
        self.metadata = metadata or {}
        
        # Validate shapes
        if states.shape[0] != next_states.shape[0]:
            raise ValueError("States and next_states must have same batch size")
            
        if states.shape[1:] != next_states.shape[1:]:
            raise ValueError("States and next_states must have same sequence shape")
            
    @property
    def batch_size(self) -> int:
        """Get batch size."""
        return self.states.shape[0]
        
    @property
    def sequence_length(self) -> int:
        """Get sequence length."""
        return self.states.shape[1]
        
    @property
    def feature_dim(self) -> int:
        """Get feature dimension."""
        return self.states.shape[2] if len(self.states.shape) > 2 else 1
        
    def to_device(self, device: str) -> 'SequenceBatch':
        """Move batch to specified device (for PyTorch compatibility)."""
        try:
            import torch
            
            states_tensor = torch.tensor(self.states).to(device)
            next_states_tensor = torch.tensor(self.next_states).to(device)
            
            return SequenceBatch(
                states_tensor.numpy(),
                next_states_tensor.numpy(),
                self.metadata
            )
        except ImportError:
            # Return self if PyTorch not available
            return self
            
    def __len__(self) -> int:
        """Get batch size."""
        return self.batch_size
        
    def __getitem__(self, idx: int) -> Tuple[np.ndarray, np.ndarray]:
        """Get single sequence from batch."""
        return self.states[idx], self.next_states[idx]
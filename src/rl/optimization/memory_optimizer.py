"""
Memory Optimization Tools for RL System

Advanced memory management utilities including memory pools,
garbage collection optimization, and memory leak detection.
"""

import gc
import weakref
import threading
import psutil
import numpy as np
from typing import Dict, List, Any, Optional, Type, Union
from collections import defaultdict, deque
from dataclasses import dataclass
import time
import warnings


@dataclass
class MemoryStats:
    """Memory usage statistics."""
    total_allocated: int = 0
    peak_usage: int = 0
    current_usage: int = 0
    allocation_count: int = 0
    deallocation_count: int = 0
    fragmentation_ratio: float = 0.0


class MemoryPool:
    """High-performance memory pool for frequent allocations."""
    
    def __init__(self, block_size: int, pool_size: int = 1000):
        self.block_size = block_size
        self.pool_size = pool_size
        self.available_blocks = deque()
        self.allocated_blocks = set()
        self.stats = MemoryStats()
        self._lock = threading.Lock()
        
        # Pre-allocate blocks
        self._initialize_pool()
    
    def _initialize_pool(self):
        """Initialize the memory pool with pre-allocated blocks."""
        for _ in range(self.pool_size):
            block = np.empty(self.block_size, dtype=np.float32)
            self.available_blocks.append(block)
    
    def allocate(self) -> Optional[np.ndarray]:
        """Allocate a memory block from the pool."""
        with self._lock:
            if self.available_blocks:
                block = self.available_blocks.popleft()
                self.allocated_blocks.add(id(block))
                self.stats.allocation_count += 1
                self.stats.current_usage += self.block_size * 4  # float32 = 4 bytes
                self.stats.peak_usage = max(self.stats.peak_usage, self.stats.current_usage)
                return block
            else:
                # Pool exhausted, allocate new block
                warnings.warn(f"Memory pool exhausted, allocating new block of size {self.block_size}")
                block = np.empty(self.block_size, dtype=np.float32)
                self.allocated_blocks.add(id(block))
                self.stats.allocation_count += 1
                self.stats.current_usage += self.block_size * 4
                self.stats.peak_usage = max(self.stats.peak_usage, self.stats.current_usage)
                return block
    
    def deallocate(self, block: np.ndarray):
        """Return a memory block to the pool."""
        with self._lock:
            block_id = id(block)
            if block_id in self.allocated_blocks:
                self.allocated_blocks.remove(block_id)
                
                # Reset block data
                block.fill(0)
                
                # Return to pool if not full
                if len(self.available_blocks) < self.pool_size:
                    self.available_blocks.append(block)
                
                self.stats.deallocation_count += 1
                self.stats.current_usage -= self.block_size * 4
    
    def get_stats(self) -> MemoryStats:
        """Get memory pool statistics."""
        with self._lock:
            self.stats.fragmentation_ratio = (
                len(self.allocated_blocks) / (len(self.allocated_blocks) + len(self.available_blocks))
                if (len(self.allocated_blocks) + len(self.available_blocks)) > 0 else 0
            )
            return self.stats
    
    def clear(self):
        """Clear the memory pool."""
        with self._lock:
            self.available_blocks.clear()
            self.allocated_blocks.clear()
            self.stats = MemoryStats()
            gc.collect()


class MemoryOptimizer:
    """Advanced memory optimization and monitoring system."""
    
    def __init__(self):
        self.memory_pools: Dict[int, MemoryPool] = {}
        self.allocation_tracker: Dict[str, List[int]] = defaultdict(list)
        self.gc_stats = {'collections': 0, 'freed_objects': 0}
        self.process = psutil.Process()
        self._monitoring = False
        self._monitor_thread = None
        
    def create_memory_pool(self, block_size: int, pool_size: int = 1000) -> MemoryPool:
        """Create a new memory pool for specific block size."""
        if block_size in self.memory_pools:
            return self.memory_pools[block_size]
        
        pool = MemoryPool(block_size, pool_size)
        self.memory_pools[block_size] = pool
        return pool
    
    def get_memory_pool(self, block_size: int) -> Optional[MemoryPool]:
        """Get existing memory pool for block size."""
        return self.memory_pools.get(block_size)
    
    def allocate_optimized(self, size: int, dtype: Type = np.float32) -> np.ndarray:
        """Allocate memory using optimized pools when possible."""
        # Calculate block size in elements
        element_size = np.dtype(dtype).itemsize
        block_size = size
        
        # Try to use existing pool
        pool = self.get_memory_pool(block_size)
        if pool:
            block = pool.allocate()
            if block is not None:
                return block.astype(dtype)
        
        # Fallback to regular allocation
        return np.empty(size, dtype=dtype)
    
    def optimize_garbage_collection(self):
        """Optimize garbage collection settings."""
        # Get current GC stats
        initial_stats = gc.get_stats()
        
        # Force garbage collection
        collected = gc.collect()
        
        # Update stats
        self.gc_stats['collections'] += 1
        self.gc_stats['freed_objects'] += collected
        
        # Optimize GC thresholds based on current memory usage
        memory_mb = self.get_memory_usage()
        
        if memory_mb > 1000:  # High memory usage
            # More aggressive GC
            gc.set_threshold(500, 5, 5)
        elif memory_mb > 500:  # Medium memory usage
            # Balanced GC
            gc.set_threshold(700, 10, 10)
        else:  # Low memory usage
            # Less frequent GC
            gc.set_threshold(1000, 15, 15)
        
        return collected
    
    def get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            return self.process.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0
    
    def get_detailed_memory_info(self) -> Dict[str, Any]:
        """Get detailed memory information."""
        try:
            memory_info = self.process.memory_info()
            memory_percent = self.process.memory_percent()
            
            # System memory info
            system_memory = psutil.virtual_memory()
            
            return {
                'process_memory': {
                    'rss_mb': memory_info.rss / 1024 / 1024,
                    'vms_mb': memory_info.vms / 1024 / 1024,
                    'percent': memory_percent,
                    'available_mb': system_memory.available / 1024 / 1024,
                    'total_mb': system_memory.total / 1024 / 1024
                },
                'gc_stats': self.gc_stats.copy(),
                'pool_stats': {
                    size: pool.get_stats() for size, pool in self.memory_pools.items()
                }
            }
        except Exception as e:
            return {'error': str(e)}
    
    def detect_memory_leaks(self, threshold_mb: float = 100) -> Dict[str, Any]:
        """Detect potential memory leaks."""
        initial_memory = self.get_memory_usage()
        
        # Force garbage collection
        collected = self.optimize_garbage_collection()
        
        # Check memory after GC
        final_memory = self.get_memory_usage()
        memory_freed = initial_memory - final_memory
        
        # Analyze object counts
        object_counts = {}
        for obj_type in [list, dict, tuple, set]:
            count = len([obj for obj in gc.get_objects() if isinstance(obj, obj_type)])
            object_counts[obj_type.__name__] = count
        
        leak_detected = final_memory > threshold_mb and memory_freed < 10
        
        return {
            'leak_detected': leak_detected,
            'initial_memory_mb': initial_memory,
            'final_memory_mb': final_memory,
            'memory_freed_mb': memory_freed,
            'objects_collected': collected,
            'object_counts': object_counts,
            'recommendations': self._get_memory_recommendations(final_memory, object_counts)
        }
    
    def _get_memory_recommendations(self, memory_mb: float, object_counts: Dict[str, int]) -> List[str]:
        """Generate memory optimization recommendations."""
        recommendations = []
        
        if memory_mb > 500:
            recommendations.append("High memory usage detected. Consider using memory pools for frequent allocations.")
        
        if object_counts.get('list', 0) > 10000:
            recommendations.append("Large number of lists detected. Consider using numpy arrays for numerical data.")
        
        if object_counts.get('dict', 0) > 5000:
            recommendations.append("Large number of dictionaries detected. Consider using dataclasses or named tuples.")
        
        if not recommendations:
            recommendations.append("Memory usage appears optimal.")
        
        return recommendations
    
    def optimize_numpy_memory(self, array: np.ndarray, target_dtype: Optional[Type] = None) -> np.ndarray:
        """Optimize numpy array memory usage."""
        if target_dtype is None:
            # Auto-select optimal dtype
            if array.dtype == np.float64:
                # Check if we can safely downcast to float32
                if np.allclose(array, array.astype(np.float32), rtol=1e-6):
                    target_dtype = np.float32
            elif array.dtype == np.int64:
                # Check if we can safely downcast to int32
                if np.all(array >= np.iinfo(np.int32).min) and np.all(array <= np.iinfo(np.int32).max):
                    target_dtype = np.int32
        
        if target_dtype and array.dtype != target_dtype:
            return array.astype(target_dtype)
        
        return array
    
    def create_memory_mapped_array(self, shape: tuple, dtype: Type = np.float32, 
                                 filename: Optional[str] = None) -> np.ndarray:
        """Create memory-mapped array for large datasets."""
        if filename is None:
            # Create temporary memory-mapped array
            return np.memmap(None, dtype=dtype, mode='w+', shape=shape)
        else:
            # Create persistent memory-mapped array
            return np.memmap(filename, dtype=dtype, mode='w+', shape=shape)
    
    def clear_all_pools(self):
        """Clear all memory pools."""
        for pool in self.memory_pools.values():
            pool.clear()
        self.memory_pools.clear()
        gc.collect()


class MemoryLeakDetector:
    """Advanced memory leak detection system."""
    
    def __init__(self, sampling_interval: float = 60.0):
        self.sampling_interval = sampling_interval
        self.memory_samples = deque(maxlen=1000)
        self.object_samples = deque(maxlen=100)
        self.is_monitoring = False
        self.monitor_thread = None
        self.process = psutil.Process()
    
    def start_monitoring(self):
        """Start memory leak monitoring."""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop memory leak monitoring."""
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5.0)
    
    def _monitor_loop(self):
        """Main monitoring loop for leak detection."""
        while self.is_monitoring:
            try:
                timestamp = time.time()
                memory_mb = self.process.memory_info().rss / 1024 / 1024
                
                # Sample memory usage
                self.memory_samples.append((timestamp, memory_mb))
                
                # Sample object counts periodically
                if len(self.memory_samples) % 10 == 0:
                    object_counts = self._count_objects()
                    self.object_samples.append((timestamp, object_counts))
                
                time.sleep(self.sampling_interval)
                
            except Exception as e:
                print(f"Memory monitoring error: {e}")
                time.sleep(self.sampling_interval)
    
    def _count_objects(self) -> Dict[str, int]:
        """Count objects by type."""
        counts = defaultdict(int)
        
        for obj in gc.get_objects():
            obj_type = type(obj).__name__
            counts[obj_type] += 1
        
        return dict(counts)
    
    def analyze_memory_trend(self, window_minutes: int = 60) -> Dict[str, Any]:
        """Analyze memory usage trend for leak detection."""
        if len(self.memory_samples) < 10:
            return {'status': 'insufficient_data'}
        
        # Filter samples within time window
        current_time = time.time()
        cutoff_time = current_time - (window_minutes * 60)
        
        recent_samples = [
            (timestamp, memory) for timestamp, memory in self.memory_samples
            if timestamp >= cutoff_time
        ]
        
        if len(recent_samples) < 5:
            return {'status': 'insufficient_recent_data'}
        
        # Calculate trend
        timestamps = [t for t, _ in recent_samples]
        memory_values = [m for _, m in recent_samples]
        
        # Linear regression for trend analysis
        x = np.array(timestamps) - timestamps[0]  # Normalize timestamps
        y = np.array(memory_values)
        
        if len(x) > 1:
            slope = np.polyfit(x, y, 1)[0]  # MB per second
            slope_per_hour = slope * 3600  # MB per hour
        else:
            slope_per_hour = 0
        
        # Detect leak
        leak_threshold = 10  # MB per hour
        leak_detected = slope_per_hour > leak_threshold
        
        return {
            'status': 'analyzed',
            'leak_detected': leak_detected,
            'memory_trend_mb_per_hour': slope_per_hour,
            'current_memory_mb': memory_values[-1],
            'memory_change_mb': memory_values[-1] - memory_values[0],
            'sample_count': len(recent_samples),
            'time_window_minutes': window_minutes
        }
    
    def get_leak_report(self) -> Dict[str, Any]:
        """Generate comprehensive memory leak report."""
        memory_analysis = self.analyze_memory_trend()
        
        # Analyze object growth
        object_growth = {}
        if len(self.object_samples) >= 2:
            old_counts = self.object_samples[0][1]
            new_counts = self.object_samples[-1][1]
            
            for obj_type in set(old_counts.keys()) | set(new_counts.keys()):
                old_count = old_counts.get(obj_type, 0)
                new_count = new_counts.get(obj_type, 0)
                growth = new_count - old_count
                
                if growth > 100:  # Significant growth
                    object_growth[obj_type] = {
                        'old_count': old_count,
                        'new_count': new_count,
                        'growth': growth
                    }
        
        return {
            'memory_analysis': memory_analysis,
            'object_growth': object_growth,
            'recommendations': self._generate_leak_recommendations(memory_analysis, object_growth)
        }
    
    def _generate_leak_recommendations(self, memory_analysis: Dict[str, Any], 
                                     object_growth: Dict[str, Any]) -> List[str]:
        """Generate recommendations for memory leak prevention."""
        recommendations = []
        
        if memory_analysis.get('leak_detected'):
            recommendations.append("Memory leak detected. Review recent code changes and check for unclosed resources.")
        
        if object_growth:
            top_growing = sorted(object_growth.items(), key=lambda x: x[1]['growth'], reverse=True)[:3]
            for obj_type, growth_info in top_growing:
                recommendations.append(
                    f"High growth in {obj_type} objects (+{growth_info['growth']}). "
                    f"Check for proper cleanup and avoid circular references."
                )
        
        if not recommendations:
            recommendations.append("No significant memory leaks detected.")
        
        return recommendations


# Global memory optimizer instance
_global_optimizer = MemoryOptimizer()

def get_memory_optimizer() -> MemoryOptimizer:
    """Get global memory optimizer instance."""
    return _global_optimizer

def optimize_memory():
    """Perform global memory optimization."""
    return _global_optimizer.optimize_garbage_collection()

def create_optimized_array(size: int, dtype: Type = np.float32) -> np.ndarray:
    """Create optimized array using global optimizer."""
    return _global_optimizer.allocate_optimized(size, dtype)
"""
GPU Acceleration Support for RL System

CUDA and GPU acceleration utilities for neural network training
and inference optimization.
"""

import os
import warnings
from typing import Dict, List, Any, Optional, Union, Tuple
import numpy as np
from dataclasses import dataclass


# Try to import GPU libraries
try:
    import torch
    import torch.cuda as cuda
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    torch = None
    cuda = None

try:
    import cupy as cp
    CUPY_AVAILABLE = True
except ImportError:
    CUPY_AVAILABLE = False
    cp = None


@dataclass
class GPUInfo:
    """GPU device information."""
    device_id: int
    name: str
    memory_total: int  # MB
    memory_free: int   # MB
    memory_used: int   # MB
    compute_capability: Tuple[int, int]
    is_available: bool = True


class CUDAManager:
    """CUDA device management and optimization."""
    
    def __init__(self):
        self.torch_available = TORCH_AVAILABLE
        self.cupy_available = CUPY_AVAILABLE
        self.devices_info: List[GPUInfo] = []
        self.current_device = 0
        
        if self.torch_available:
            self._initialize_torch_cuda()
        elif self.cupy_available:
            self._initialize_cupy()
    
    def _initialize_torch_cuda(self):
        """Initialize PyTorch CUDA support."""
        if not torch.cuda.is_available():
            warnings.warn("CUDA is not available in PyTorch")
            return
        
        # Get device information
        for i in range(torch.cuda.device_count()):
            props = torch.cuda.get_device_properties(i)
            memory_info = torch.cuda.mem_get_info(i)
            
            device_info = GPUInfo(
                device_id=i,
                name=props.name,
                memory_total=props.total_memory // (1024 * 1024),
                memory_free=memory_info[0] // (1024 * 1024),
                memory_used=(props.total_memory - memory_info[0]) // (1024 * 1024),
                compute_capability=(props.major, props.minor)
            )
            self.devices_info.append(device_info)
    
    def _initialize_cupy(self):
        """Initialize CuPy CUDA support."""
        try:
            device_count = cp.cuda.runtime.getDeviceCount()
            
            for i in range(device_count):
                with cp.cuda.Device(i):
                    props = cp.cuda.runtime.getDeviceProperties(i)
                    memory_info = cp.cuda.runtime.memGetInfo()
                    
                    device_info = GPUInfo(
                        device_id=i,
                        name=props['name'].decode('utf-8'),
                        memory_total=props['totalGlobalMem'] // (1024 * 1024),
                        memory_free=memory_info[0] // (1024 * 1024),
                        memory_used=(props['totalGlobalMem'] - memory_info[0]) // (1024 * 1024),
                        compute_capability=(props['major'], props['minor'])
                    )
                    self.devices_info.append(device_info)
        except Exception as e:
            warnings.warn(f"Failed to initialize CuPy: {e}")
    
    def is_available(self) -> bool:
        """Check if GPU acceleration is available."""
        return len(self.devices_info) > 0
    
    def get_device_count(self) -> int:
        """Get number of available GPU devices."""
        return len(self.devices_info)
    
    def get_device_info(self, device_id: int = None) -> Optional[GPUInfo]:
        """Get information about specific GPU device."""
        if device_id is None:
            device_id = self.current_device
        
        if 0 <= device_id < len(self.devices_info):
            return self.devices_info[device_id]
        return None
    
    def get_all_devices_info(self) -> List[GPUInfo]:
        """Get information about all GPU devices."""
        return self.devices_info.copy()
    
    def select_best_device(self) -> int:
        """Select the best available GPU device."""
        if not self.devices_info:
            return -1
        
        # Select device with most free memory
        best_device = max(
            enumerate(self.devices_info),
            key=lambda x: x[1].memory_free
        )
        
        self.current_device = best_device[0]
        return self.current_device
    
    def set_device(self, device_id: int):
        """Set current GPU device."""
        if 0 <= device_id < len(self.devices_info):
            self.current_device = device_id
            
            if self.torch_available:
                torch.cuda.set_device(device_id)
            elif self.cupy_available:
                cp.cuda.Device(device_id).use()
        else:
            raise ValueError(f"Invalid device ID: {device_id}")
    
    def clear_cache(self, device_id: int = None):
        """Clear GPU memory cache."""
        if device_id is None:
            device_id = self.current_device
        
        if self.torch_available:
            with torch.cuda.device(device_id):
                torch.cuda.empty_cache()
        elif self.cupy_available:
            with cp.cuda.Device(device_id):
                cp.get_default_memory_pool().free_all_blocks()
    
    def get_memory_usage(self, device_id: int = None) -> Dict[str, int]:
        """Get current memory usage for device."""
        if device_id is None:
            device_id = self.current_device
        
        if self.torch_available:
            memory_allocated = torch.cuda.memory_allocated(device_id) // (1024 * 1024)
            memory_reserved = torch.cuda.memory_reserved(device_id) // (1024 * 1024)
            
            return {
                'allocated_mb': memory_allocated,
                'reserved_mb': memory_reserved,
                'free_mb': self.devices_info[device_id].memory_total - memory_reserved
            }
        elif self.cupy_available:
            with cp.cuda.Device(device_id):
                memory_pool = cp.get_default_memory_pool()
                used_bytes = memory_pool.used_bytes()
                total_bytes = memory_pool.total_bytes()
                
                return {
                    'allocated_mb': used_bytes // (1024 * 1024),
                    'reserved_mb': total_bytes // (1024 * 1024),
                    'free_mb': (self.devices_info[device_id].memory_total * 1024 * 1024 - total_bytes) // (1024 * 1024)
                }
        
        return {'allocated_mb': 0, 'reserved_mb': 0, 'free_mb': 0}


class GPUAccelerator:
    """High-level GPU acceleration interface for RL operations."""
    
    def __init__(self, auto_select_device: bool = True):
        self.cuda_manager = CUDAManager()
        self.device_id = -1
        
        if auto_select_device and self.cuda_manager.is_available():
            self.device_id = self.cuda_manager.select_best_device()
    
    def is_available(self) -> bool:
        """Check if GPU acceleration is available."""
        return self.cuda_manager.is_available() and self.device_id >= 0
    
    def to_gpu(self, array: np.ndarray) -> Union[np.ndarray, Any]:
        """Move numpy array to GPU."""
        if not self.is_available():
            return array
        
        if self.cuda_manager.torch_available:
            return torch.from_numpy(array).cuda(self.device_id)
        elif self.cuda_manager.cupy_available:
            with cp.cuda.Device(self.device_id):
                return cp.asarray(array)
        
        return array
    
    def to_cpu(self, gpu_array: Any) -> np.ndarray:
        """Move GPU array back to CPU."""
        if self.cuda_manager.torch_available and torch.is_tensor(gpu_array):
            return gpu_array.cpu().numpy()
        elif self.cuda_manager.cupy_available and hasattr(gpu_array, 'get'):
            return gpu_array.get()
        
        return gpu_array
    
    def accelerated_matmul(self, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Perform accelerated matrix multiplication."""
        if not self.is_available():
            return np.matmul(a, b)
        
        if self.cuda_manager.torch_available:
            a_gpu = torch.from_numpy(a).cuda(self.device_id)
            b_gpu = torch.from_numpy(b).cuda(self.device_id)
            result_gpu = torch.matmul(a_gpu, b_gpu)
            return result_gpu.cpu().numpy()
        elif self.cuda_manager.cupy_available:
            with cp.cuda.Device(self.device_id):
                a_gpu = cp.asarray(a)
                b_gpu = cp.asarray(b)
                result_gpu = cp.matmul(a_gpu, b_gpu)
                return result_gpu.get()
        
        return np.matmul(a, b)
    
    def accelerated_conv2d(self, input_array: np.ndarray, kernel: np.ndarray) -> np.ndarray:
        """Perform accelerated 2D convolution."""
        if not self.is_available():
            # Fallback to scipy or manual implementation
            from scipy import ndimage
            return ndimage.convolve(input_array, kernel)
        
        if self.cuda_manager.torch_available:
            # Convert to torch tensors and perform convolution
            input_tensor = torch.from_numpy(input_array).unsqueeze(0).unsqueeze(0).cuda(self.device_id)
            kernel_tensor = torch.from_numpy(kernel).unsqueeze(0).unsqueeze(0).cuda(self.device_id)
            
            result = torch.nn.functional.conv2d(input_tensor, kernel_tensor, padding='same')
            return result.squeeze().cpu().numpy()
        elif self.cuda_manager.cupy_available:
            with cp.cuda.Device(self.device_id):
                input_gpu = cp.asarray(input_array)
                kernel_gpu = cp.asarray(kernel)
                
                # Use CuPy's convolution
                from cupyx.scipy import ndimage as cp_ndimage
                result_gpu = cp_ndimage.convolve(input_gpu, kernel_gpu)
                return result_gpu.get()
        
        # Fallback
        from scipy import ndimage
        return ndimage.convolve(input_array, kernel)
    
    def accelerated_fft(self, array: np.ndarray) -> np.ndarray:
        """Perform accelerated FFT."""
        if not self.is_available():
            return np.fft.fft(array)
        
        if self.cuda_manager.torch_available:
            array_gpu = torch.from_numpy(array).cuda(self.device_id)
            result_gpu = torch.fft.fft(array_gpu)
            return result_gpu.cpu().numpy()
        elif self.cuda_manager.cupy_available:
            with cp.cuda.Device(self.device_id):
                array_gpu = cp.asarray(array)
                result_gpu = cp.fft.fft(array_gpu)
                return result_gpu.get()
        
        return np.fft.fft(array)
    
    def optimize_neural_network(self, model_config: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize neural network configuration for GPU."""
        if not self.is_available():
            return model_config
        
        optimized_config = model_config.copy()
        
        # Adjust batch size for GPU memory
        device_info = self.cuda_manager.get_device_info(self.device_id)
        if device_info:
            memory_gb = device_info.memory_free / 1024
            
            # Suggest optimal batch size based on available memory
            if memory_gb >= 8:
                optimized_config['batch_size'] = min(optimized_config.get('batch_size', 32) * 4, 512)
            elif memory_gb >= 4:
                optimized_config['batch_size'] = min(optimized_config.get('batch_size', 32) * 2, 256)
            
            # Enable mixed precision if supported
            if device_info.compute_capability[0] >= 7:  # Volta or newer
                optimized_config['use_mixed_precision'] = True
            
            # Optimize for tensor cores if available
            if device_info.compute_capability[0] >= 7:
                # Ensure dimensions are multiples of 8 for tensor core optimization
                for key in ['hidden_size', 'embedding_size']:
                    if key in optimized_config:
                        size = optimized_config[key]
                        optimized_config[key] = ((size + 7) // 8) * 8
        
        return optimized_config
    
    def benchmark_operations(self, array_size: int = 1000) -> Dict[str, float]:
        """Benchmark GPU vs CPU operations."""
        # Generate test data
        a = np.random.random((array_size, array_size)).astype(np.float32)
        b = np.random.random((array_size, array_size)).astype(np.float32)
        
        results = {}
        
        # CPU benchmark
        import time
        start_time = time.perf_counter()
        cpu_result = np.matmul(a, b)
        cpu_time = time.perf_counter() - start_time
        results['cpu_matmul_time'] = cpu_time
        
        # GPU benchmark
        if self.is_available():
            start_time = time.perf_counter()
            gpu_result = self.accelerated_matmul(a, b)
            gpu_time = time.perf_counter() - start_time
            results['gpu_matmul_time'] = gpu_time
            results['speedup'] = cpu_time / gpu_time if gpu_time > 0 else 0
            
            # Verify correctness
            results['results_match'] = np.allclose(cpu_result, gpu_result, rtol=1e-5)
        else:
            results['gpu_matmul_time'] = float('inf')
            results['speedup'] = 0
            results['results_match'] = False
        
        return results
    
    def get_optimization_recommendations(self) -> List[str]:
        """Get GPU optimization recommendations."""
        recommendations = []
        
        if not self.is_available():
            recommendations.append("GPU acceleration not available. Consider installing CUDA and PyTorch/CuPy.")
            return recommendations
        
        device_info = self.cuda_manager.get_device_info(self.device_id)
        memory_usage = self.cuda_manager.get_memory_usage(self.device_id)
        
        if device_info:
            # Memory recommendations
            memory_utilization = memory_usage['allocated_mb'] / device_info.memory_total
            if memory_utilization > 0.9:
                recommendations.append("High GPU memory usage. Consider reducing batch size or model size.")
            elif memory_utilization < 0.3:
                recommendations.append("Low GPU memory usage. Consider increasing batch size for better performance.")
            
            # Compute capability recommendations
            if device_info.compute_capability[0] >= 7:
                recommendations.append("Tensor Core support available. Use mixed precision training for better performance.")
            
            if device_info.compute_capability[0] < 6:
                recommendations.append("Older GPU architecture detected. Consider upgrading for better performance.")
        
        if not recommendations:
            recommendations.append("GPU configuration appears optimal.")
        
        return recommendations


# Global GPU accelerator instance
_global_accelerator = None

def get_gpu_accelerator() -> GPUAccelerator:
    """Get global GPU accelerator instance."""
    global _global_accelerator
    if _global_accelerator is None:
        _global_accelerator = GPUAccelerator()
    return _global_accelerator

def is_gpu_available() -> bool:
    """Check if GPU acceleration is available."""
    return get_gpu_accelerator().is_available()

def to_gpu(array: np.ndarray):
    """Move array to GPU using global accelerator."""
    return get_gpu_accelerator().to_gpu(array)

def to_cpu(gpu_array):
    """Move array to CPU using global accelerator."""
    return get_gpu_accelerator().to_cpu(gpu_array)
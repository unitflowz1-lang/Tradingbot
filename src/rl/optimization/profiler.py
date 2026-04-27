"""
Performance Profiling Tools for RL System

Comprehensive profiling utilities to identify performance bottlenecks
and optimize training and inference performance.
"""

import time
import psutil
import threading
import functools
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, field
from collections import defaultdict, deque
import numpy as np
import json
import os
from datetime import datetime
import cProfile
import pstats
import io


@dataclass
class ProfileMetrics:
    """Container for profiling metrics."""
    function_name: str
    call_count: int = 0
    total_time: float = 0.0
    avg_time: float = 0.0
    min_time: float = float('inf')
    max_time: float = 0.0
    memory_usage: List[float] = field(default_factory=list)
    cpu_usage: List[float] = field(default_factory=list)
    
    def update(self, execution_time: float, memory_mb: float = None, cpu_percent: float = None):
        """Update metrics with new measurement."""
        self.call_count += 1
        self.total_time += execution_time
        self.avg_time = self.total_time / self.call_count
        self.min_time = min(self.min_time, execution_time)
        self.max_time = max(self.max_time, execution_time)
        
        if memory_mb is not None:
            self.memory_usage.append(memory_mb)
        if cpu_percent is not None:
            self.cpu_usage.append(cpu_percent)


class RLSystemProfiler:
    """Comprehensive profiler for RL system components."""
    
    def __init__(self, enable_memory_tracking: bool = True, enable_cpu_tracking: bool = True):
        self.enable_memory_tracking = enable_memory_tracking
        self.enable_cpu_tracking = enable_cpu_tracking
        self.metrics: Dict[str, ProfileMetrics] = {}
        self.active_profiles: Dict[str, float] = {}
        self.process = psutil.Process()
        self._lock = threading.Lock()
        
    def profile_function(self, func_name: str = None):
        """Decorator to profile function execution."""
        def decorator(func: Callable):
            name = func_name or f"{func.__module__}.{func.__name__}"
            
            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                return self._execute_with_profiling(name, func, *args, **kwargs)
            return wrapper
        return decorator
    
    def _execute_with_profiling(self, name: str, func: Callable, *args, **kwargs):
        """Execute function with comprehensive profiling."""
        # Get initial measurements
        start_time = time.perf_counter()
        initial_memory = self._get_memory_usage() if self.enable_memory_tracking else None
        initial_cpu = self._get_cpu_usage() if self.enable_cpu_tracking else None
        
        try:
            # Execute function
            result = func(*args, **kwargs)
            
            # Calculate metrics
            execution_time = time.perf_counter() - start_time
            final_memory = self._get_memory_usage() if self.enable_memory_tracking else None
            final_cpu = self._get_cpu_usage() if self.enable_cpu_tracking else None
            
            # Update metrics
            with self._lock:
                if name not in self.metrics:
                    self.metrics[name] = ProfileMetrics(name)
                
                memory_delta = (final_memory - initial_memory) if initial_memory else None
                cpu_avg = (initial_cpu + final_cpu) / 2 if initial_cpu else None
                
                self.metrics[name].update(execution_time, memory_delta, cpu_avg)
            
            return result
            
        except Exception as e:
            # Record failed execution
            execution_time = time.perf_counter() - start_time
            with self._lock:
                if name not in self.metrics:
                    self.metrics[name] = ProfileMetrics(name)
                self.metrics[name].update(execution_time)
            raise e
    
    def start_profiling(self, name: str):
        """Start profiling a code block."""
        with self._lock:
            self.active_profiles[name] = time.perf_counter()
    
    def end_profiling(self, name: str):
        """End profiling a code block."""
        end_time = time.perf_counter()
        
        with self._lock:
            if name in self.active_profiles:
                start_time = self.active_profiles.pop(name)
                execution_time = end_time - start_time
                
                if name not in self.metrics:
                    self.metrics[name] = ProfileMetrics(name)
                
                memory_usage = self._get_memory_usage() if self.enable_memory_tracking else None
                cpu_usage = self._get_cpu_usage() if self.enable_cpu_tracking else None
                
                self.metrics[name].update(execution_time, memory_usage, cpu_usage)
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            return self.process.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0
    
    def _get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        try:
            return self.process.cpu_percent()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0
    
    def get_metrics(self) -> Dict[str, Dict[str, Any]]:
        """Get all profiling metrics."""
        with self._lock:
            result = {}
            for name, metrics in self.metrics.items():
                result[name] = {
                    'call_count': metrics.call_count,
                    'total_time': metrics.total_time,
                    'avg_time': metrics.avg_time,
                    'min_time': metrics.min_time if metrics.min_time != float('inf') else 0,
                    'max_time': metrics.max_time,
                    'avg_memory_usage': np.mean(metrics.memory_usage) if metrics.memory_usage else 0,
                    'max_memory_usage': np.max(metrics.memory_usage) if metrics.memory_usage else 0,
                    'avg_cpu_usage': np.mean(metrics.cpu_usage) if metrics.cpu_usage else 0,
                    'max_cpu_usage': np.max(metrics.cpu_usage) if metrics.cpu_usage else 0
                }
            return result
    
    def get_top_functions(self, metric: str = 'total_time', limit: int = 10) -> List[Dict[str, Any]]:
        """Get top functions by specified metric."""
        metrics = self.get_metrics()
        
        if metric not in ['total_time', 'avg_time', 'call_count', 'max_memory_usage']:
            raise ValueError(f"Invalid metric: {metric}")
        
        sorted_functions = sorted(
            metrics.items(),
            key=lambda x: x[1][metric],
            reverse=True
        )
        
        return [
            {'function': name, **data}
            for name, data in sorted_functions[:limit]
        ]
    
    def save_report(self, filepath: str):
        """Save profiling report to file."""
        report = {
            'timestamp': datetime.now().isoformat(),
            'system_info': {
                'cpu_count': psutil.cpu_count(),
                'memory_total': psutil.virtual_memory().total / 1024 / 1024 / 1024,  # GB
                'python_process_memory': self._get_memory_usage()
            },
            'metrics': self.get_metrics(),
            'top_by_time': self.get_top_functions('total_time'),
            'top_by_calls': self.get_top_functions('call_count'),
            'top_by_memory': self.get_top_functions('max_memory_usage')
        }
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2)
    
    def reset(self):
        """Reset all profiling metrics."""
        with self._lock:
            self.metrics.clear()
            self.active_profiles.clear()


class PerformanceProfiler:
    """Advanced performance profiler with cProfile integration."""
    
    def __init__(self, output_dir: str = "performance_reports"):
        self.output_dir = output_dir
        self.profiler = None
        self.is_profiling = False
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
    
    def start_detailed_profiling(self):
        """Start detailed cProfile profiling."""
        if self.is_profiling:
            return
        
        self.profiler = cProfile.Profile()
        self.profiler.enable()
        self.is_profiling = True
    
    def stop_detailed_profiling(self, report_name: str = None):
        """Stop detailed profiling and generate report."""
        if not self.is_profiling or not self.profiler:
            return None
        
        self.profiler.disable()
        self.is_profiling = False
        
        # Generate report
        if report_name is None:
            report_name = f"profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Save binary profile
        profile_path = os.path.join(self.output_dir, f"{report_name}.prof")
        self.profiler.dump_stats(profile_path)
        
        # Generate text report
        s = io.StringIO()
        ps = pstats.Stats(self.profiler, stream=s)
        ps.sort_stats('cumulative')
        ps.print_stats()
        
        report_path = os.path.join(self.output_dir, f"{report_name}.txt")
        with open(report_path, 'w') as f:
            f.write(s.getvalue())
        
        return {
            'profile_file': profile_path,
            'report_file': report_path,
            'stats': ps
        }
    
    def profile_code_block(self, code_block: Callable, *args, **kwargs):
        """Profile a specific code block."""
        profiler = cProfile.Profile()
        
        profiler.enable()
        try:
            result = code_block(*args, **kwargs)
        finally:
            profiler.disable()
        
        # Generate stats
        s = io.StringIO()
        ps = pstats.Stats(profiler, stream=s)
        ps.sort_stats('cumulative')
        
        return {
            'result': result,
            'stats': ps,
            'report': s.getvalue()
        }


class RealTimeProfiler:
    """Real-time performance monitoring for live systems."""
    
    def __init__(self, sampling_interval: float = 1.0, history_size: int = 1000):
        self.sampling_interval = sampling_interval
        self.history_size = history_size
        self.metrics_history = defaultdict(lambda: deque(maxlen=history_size))
        self.is_monitoring = False
        self.monitor_thread = None
        self.process = psutil.Process()
    
    def start_monitoring(self):
        """Start real-time monitoring."""
        if self.is_monitoring:
            return
        
        self.is_monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
    
    def stop_monitoring(self):
        """Stop real-time monitoring."""
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2.0)
    
    def _monitor_loop(self):
        """Main monitoring loop."""
        while self.is_monitoring:
            try:
                timestamp = time.time()
                
                # Collect system metrics
                memory_info = self.process.memory_info()
                cpu_percent = self.process.cpu_percent()
                
                # Store metrics
                self.metrics_history['timestamp'].append(timestamp)
                self.metrics_history['memory_rss'].append(memory_info.rss / 1024 / 1024)  # MB
                self.metrics_history['memory_vms'].append(memory_info.vms / 1024 / 1024)  # MB
                self.metrics_history['cpu_percent'].append(cpu_percent)
                
                # System-wide metrics
                system_memory = psutil.virtual_memory()
                self.metrics_history['system_memory_percent'].append(system_memory.percent)
                self.metrics_history['system_cpu_percent'].append(psutil.cpu_percent())
                
                time.sleep(self.sampling_interval)
                
            except Exception as e:
                print(f"Monitoring error: {e}")
                time.sleep(self.sampling_interval)
    
    def get_current_metrics(self) -> Dict[str, float]:
        """Get current performance metrics."""
        if not self.metrics_history['timestamp']:
            return {}
        
        return {
            'memory_rss_mb': self.metrics_history['memory_rss'][-1],
            'memory_vms_mb': self.metrics_history['memory_vms'][-1],
            'cpu_percent': self.metrics_history['cpu_percent'][-1],
            'system_memory_percent': self.metrics_history['system_memory_percent'][-1],
            'system_cpu_percent': self.metrics_history['system_cpu_percent'][-1]
        }
    
    def get_metrics_history(self, metric: str, duration_seconds: int = None) -> List[float]:
        """Get historical metrics for specified duration."""
        if metric not in self.metrics_history:
            return []
        
        if duration_seconds is None:
            return list(self.metrics_history[metric])
        
        current_time = time.time()
        cutoff_time = current_time - duration_seconds
        
        timestamps = list(self.metrics_history['timestamp'])
        values = list(self.metrics_history[metric])
        
        # Filter by time
        filtered_values = [
            value for timestamp, value in zip(timestamps, values)
            if timestamp >= cutoff_time
        ]
        
        return filtered_values
    
    def get_performance_summary(self, duration_seconds: int = 300) -> Dict[str, Any]:
        """Get performance summary for specified duration."""
        summary = {}
        
        for metric in ['memory_rss', 'cpu_percent', 'system_memory_percent', 'system_cpu_percent']:
            values = self.get_metrics_history(metric, duration_seconds)
            
            if values:
                summary[metric] = {
                    'current': values[-1],
                    'avg': np.mean(values),
                    'min': np.min(values),
                    'max': np.max(values),
                    'std': np.std(values)
                }
            else:
                summary[metric] = {
                    'current': 0, 'avg': 0, 'min': 0, 'max': 0, 'std': 0
                }
        
        return summary


# Global profiler instance
_global_profiler = RLSystemProfiler()

def profile(func_name: str = None):
    """Global profiling decorator."""
    return _global_profiler.profile_function(func_name)

def get_profiler() -> RLSystemProfiler:
    """Get global profiler instance."""
    return _global_profiler

def reset_profiler():
    """Reset global profiler."""
    _global_profiler.reset()
"""
Performance Benchmarking Suite for RL System

Comprehensive benchmarking tools to measure and validate
system performance across different components and configurations.
"""

import time
import statistics
import threading
import multiprocessing
from typing import Dict, List, Any, Optional, Callable, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, ProcessPoolExecutor
import numpy as np
import json
import os
from datetime import datetime
import psutil


@dataclass
class BenchmarkResult:
    """Container for benchmark results."""
    name: str
    iterations: int
    total_time: float
    avg_time: float
    min_time: float
    max_time: float
    std_time: float
    throughput: float  # operations per second
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    success_rate: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


class PerformanceBenchmark:
    """Individual performance benchmark runner."""
    
    def __init__(self, name: str, warmup_iterations: int = 5):
        self.name = name
        self.warmup_iterations = warmup_iterations
        self.process = psutil.Process()
    
    def run_benchmark(self, 
                     benchmark_func: Callable,
                     iterations: int = 100,
                     *args, **kwargs) -> BenchmarkResult:
        """Run a single benchmark function."""
        
        # Warmup phase
        for _ in range(self.warmup_iterations):
            try:
                benchmark_func(*args, **kwargs)
            except Exception:
                pass  # Ignore warmup errors
        
        # Actual benchmark
        times = []
        successes = 0
        initial_memory = self._get_memory_usage()
        initial_cpu = self.process.cpu_percent()
        
        for i in range(iterations):
            start_time = time.perf_counter()
            
            try:
                result = benchmark_func(*args, **kwargs)
                successes += 1
            except Exception as e:
                # Record failed execution
                pass
            
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        final_memory = self._get_memory_usage()
        final_cpu = self.process.cpu_percent()
        
        # Calculate statistics
        total_time = sum(times)
        avg_time = statistics.mean(times)
        min_time = min(times)
        max_time = max(times)
        std_time = statistics.stdev(times) if len(times) > 1 else 0.0
        throughput = iterations / total_time if total_time > 0 else 0.0
        success_rate = successes / iterations
        
        return BenchmarkResult(
            name=self.name,
            iterations=iterations,
            total_time=total_time,
            avg_time=avg_time,
            min_time=min_time,
            max_time=max_time,
            std_time=std_time,
            throughput=throughput,
            memory_usage_mb=final_memory - initial_memory,
            cpu_usage_percent=(initial_cpu + final_cpu) / 2,
            success_rate=success_rate
        )
    
    def run_concurrent_benchmark(self,
                               benchmark_func: Callable,
                               iterations: int = 100,
                               num_threads: int = 4,
                               *args, **kwargs) -> BenchmarkResult:
        """Run benchmark with concurrent execution."""
        
        def worker_func():
            return self.run_benchmark(benchmark_func, iterations // num_threads, *args, **kwargs)
        
        start_time = time.perf_counter()
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(worker_func) for _ in range(num_threads)]
            results = [future.result() for future in futures]
        
        total_time = time.perf_counter() - start_time
        
        # Aggregate results
        total_iterations = sum(r.iterations for r in results)
        avg_throughput = sum(r.throughput for r in results)
        avg_success_rate = statistics.mean([r.success_rate for r in results])
        
        return BenchmarkResult(
            name=f"{self.name}_concurrent_{num_threads}threads",
            iterations=total_iterations,
            total_time=total_time,
            avg_time=total_time / total_iterations if total_iterations > 0 else 0,
            min_time=min(r.min_time for r in results),
            max_time=max(r.max_time for r in results),
            std_time=statistics.stdev([r.avg_time for r in results]) if len(results) > 1 else 0,
            throughput=avg_throughput,
            success_rate=avg_success_rate,
            metadata={'num_threads': num_threads, 'worker_results': [r.__dict__ for r in results]}
        )
    
    def _get_memory_usage(self) -> float:
        """Get current memory usage in MB."""
        try:
            return self.process.memory_info().rss / 1024 / 1024
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0


class BenchmarkSuite:
    """Comprehensive benchmark suite for RL system components."""
    
    def __init__(self, output_dir: str = "benchmark_results"):
        self.output_dir = output_dir
        self.benchmarks: Dict[str, PerformanceBenchmark] = {}
        self.results: Dict[str, BenchmarkResult] = {}
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
    
    def add_benchmark(self, name: str, benchmark: PerformanceBenchmark):
        """Add a benchmark to the suite."""
        self.benchmarks[name] = benchmark
    
    def create_benchmark(self, name: str, warmup_iterations: int = 5) -> PerformanceBenchmark:
        """Create and add a new benchmark."""
        benchmark = PerformanceBenchmark(name, warmup_iterations)
        self.add_benchmark(name, benchmark)
        return benchmark
    
    def run_all_benchmarks(self, iterations: int = 100) -> Dict[str, BenchmarkResult]:
        """Run all benchmarks in the suite."""
        results = {}
        
        for name, benchmark in self.benchmarks.items():
            print(f"Running benchmark: {name}")
            try:
                # This would need to be customized for each benchmark
                # For now, we'll create placeholder results
                result = BenchmarkResult(
                    name=name,
                    iterations=iterations,
                    total_time=0.0,
                    avg_time=0.0,
                    min_time=0.0,
                    max_time=0.0,
                    std_time=0.0,
                    throughput=0.0
                )
                results[name] = result
                self.results[name] = result
            except Exception as e:
                print(f"Benchmark {name} failed: {e}")
        
        return results
    
    def benchmark_agent_inference(self, agent, state_dim: int, iterations: int = 1000) -> BenchmarkResult:
        """Benchmark RL agent inference performance."""
        benchmark = PerformanceBenchmark("agent_inference")
        
        def inference_func():
            state = np.random.random(state_dim).astype(np.float32)
            return agent.select_action(state, training=False)
        
        return benchmark.run_benchmark(inference_func, iterations)
    
    def benchmark_agent_training(self, agent, environment, iterations: int = 100) -> BenchmarkResult:
        """Benchmark RL agent training performance."""
        benchmark = PerformanceBenchmark("agent_training")
        
        def training_func():
            state = environment.reset()
            action = agent.select_action(state, training=True)
            next_state, reward, done, _ = environment.step(action)
            agent.store_experience(state, action, reward, next_state, done)
            
            if len(agent.memory) >= agent.batch_size:
                return agent.update()
            return 0.0
        
        return benchmark.run_benchmark(training_func, iterations)
    
    def benchmark_environment_step(self, environment, iterations: int = 1000) -> BenchmarkResult:
        """Benchmark environment step performance."""
        benchmark = PerformanceBenchmark("environment_step")
        
        def step_func():
            if hasattr(environment, 'action_space'):
                action = np.random.randint(0, environment.action_space.n)
            else:
                action = 0
            return environment.step(action)
        
        # Reset environment before benchmark
        environment.reset()
        
        return benchmark.run_benchmark(step_func, iterations)
    
    def benchmark_data_loading(self, data_loader, iterations: int = 100) -> BenchmarkResult:
        """Benchmark data loading performance."""
        benchmark = PerformanceBenchmark("data_loading")
        
        def load_func():
            return next(iter(data_loader))
        
        return benchmark.run_benchmark(load_func, iterations)
    
    def benchmark_memory_operations(self, array_size: int = 10000, iterations: int = 1000) -> Dict[str, BenchmarkResult]:
        """Benchmark memory-intensive operations."""
        results = {}
        
        # Array allocation benchmark
        alloc_benchmark = PerformanceBenchmark("memory_allocation")
        def alloc_func():
            return np.random.random(array_size).astype(np.float32)
        results['allocation'] = alloc_benchmark.run_benchmark(alloc_func, iterations)
        
        # Array copy benchmark
        test_array = np.random.random(array_size).astype(np.float32)
        copy_benchmark = PerformanceBenchmark("memory_copy")
        def copy_func():
            return test_array.copy()
        results['copy'] = copy_benchmark.run_benchmark(copy_func, iterations)
        
        # Matrix multiplication benchmark
        matrix_a = np.random.random((100, 100)).astype(np.float32)
        matrix_b = np.random.random((100, 100)).astype(np.float32)
        matmul_benchmark = PerformanceBenchmark("matrix_multiplication")
        def matmul_func():
            return np.matmul(matrix_a, matrix_b)
        results['matmul'] = matmul_benchmark.run_benchmark(matmul_func, iterations)
        
        return results
    
    def benchmark_concurrent_access(self, target_func: Callable, 
                                  num_threads: int = 4, iterations: int = 100) -> BenchmarkResult:
        """Benchmark concurrent access patterns."""
        benchmark = PerformanceBenchmark("concurrent_access")
        return benchmark.run_concurrent_benchmark(target_func, iterations, num_threads)
    
    def run_comprehensive_benchmark(self, components: Dict[str, Any]) -> Dict[str, Any]:
        """Run comprehensive benchmark across all system components."""
        results = {
            'timestamp': datetime.now().isoformat(),
            'system_info': self._get_system_info(),
            'benchmarks': {}
        }
        
        # Benchmark each component
        for component_name, component in components.items():
            print(f"Benchmarking {component_name}...")
            
            try:
                if hasattr(component, 'select_action'):  # Agent
                    state_dim = getattr(component, 'state_dim', 10)
                    result = self.benchmark_agent_inference(component, state_dim)
                    results['benchmarks'][f"{component_name}_inference"] = result.__dict__
                
                elif hasattr(component, 'step'):  # Environment
                    result = self.benchmark_environment_step(component)
                    results['benchmarks'][f"{component_name}_step"] = result.__dict__
                
                elif hasattr(component, '__iter__'):  # Data loader
                    result = self.benchmark_data_loading(component)
                    results['benchmarks'][f"{component_name}_loading"] = result.__dict__
                
            except Exception as e:
                print(f"Failed to benchmark {component_name}: {e}")
                results['benchmarks'][f"{component_name}_error"] = str(e)
        
        # Memory operations benchmark
        memory_results = self.benchmark_memory_operations()
        for name, result in memory_results.items():
            results['benchmarks'][f"memory_{name}"] = result.__dict__
        
        return results
    
    def _get_system_info(self) -> Dict[str, Any]:
        """Get system information for benchmark context."""
        return {
            'cpu_count': psutil.cpu_count(),
            'cpu_freq': psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {},
            'memory_total_gb': psutil.virtual_memory().total / (1024**3),
            'python_version': f"{psutil.Process().exe}",
            'platform': os.name
        }
    
    def save_results(self, results: Dict[str, Any], filename: str = None):
        """Save benchmark results to file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"benchmark_results_{timestamp}.json"
        
        filepath = os.path.join(self.output_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"Benchmark results saved to: {filepath}")
        return filepath
    
    def generate_performance_report(self, results: Dict[str, Any]) -> str:
        """Generate human-readable performance report."""
        report_lines = [
            "RL System Performance Benchmark Report",
            "=" * 50,
            f"Timestamp: {results.get('timestamp', 'Unknown')}",
            "",
            "System Information:",
            f"  CPU Count: {results.get('system_info', {}).get('cpu_count', 'Unknown')}",
            f"  Memory: {results.get('system_info', {}).get('memory_total_gb', 0):.1f} GB",
            "",
            "Benchmark Results:",
            "-" * 30
        ]
        
        benchmarks = results.get('benchmarks', {})
        
        # Sort benchmarks by throughput (descending)
        sorted_benchmarks = sorted(
            [(name, data) for name, data in benchmarks.items() if isinstance(data, dict)],
            key=lambda x: x[1].get('throughput', 0),
            reverse=True
        )
        
        for name, data in sorted_benchmarks:
            if isinstance(data, dict):
                throughput = data.get('throughput', 0)
                avg_time = data.get('avg_time', 0) * 1000  # Convert to ms
                success_rate = data.get('success_rate', 0) * 100
                
                report_lines.extend([
                    f"{name}:",
                    f"  Throughput: {throughput:.2f} ops/sec",
                    f"  Avg Time: {avg_time:.2f} ms",
                    f"  Success Rate: {success_rate:.1f}%",
                    ""
                ])
        
        # Performance recommendations
        report_lines.extend([
            "Performance Recommendations:",
            "-" * 30
        ])
        
        recommendations = self._generate_performance_recommendations(benchmarks)
        for rec in recommendations:
            report_lines.append(f"• {rec}")
        
        return "\n".join(report_lines)
    
    def _generate_performance_recommendations(self, benchmarks: Dict[str, Any]) -> List[str]:
        """Generate performance optimization recommendations."""
        recommendations = []
        
        # Analyze inference performance
        inference_benchmarks = {k: v for k, v in benchmarks.items() 
                              if 'inference' in k and isinstance(v, dict)}
        
        if inference_benchmarks:
            avg_throughput = statistics.mean([b.get('throughput', 0) for b in inference_benchmarks.values()])
            
            if avg_throughput < 100:
                recommendations.append("Low inference throughput detected. Consider GPU acceleration or model optimization.")
            elif avg_throughput > 1000:
                recommendations.append("Excellent inference performance. Current optimization is effective.")
        
        # Analyze memory operations
        memory_benchmarks = {k: v for k, v in benchmarks.items() 
                           if 'memory' in k and isinstance(v, dict)}
        
        if memory_benchmarks:
            memory_throughput = statistics.mean([b.get('throughput', 0) for b in memory_benchmarks.values()])
            
            if memory_throughput < 1000:
                recommendations.append("Memory operations are slow. Consider memory pooling or optimization.")
        
        # Analyze training performance
        training_benchmarks = {k: v for k, v in benchmarks.items() 
                             if 'training' in k and isinstance(v, dict)}
        
        if training_benchmarks:
            training_throughput = statistics.mean([b.get('throughput', 0) for b in training_benchmarks.values()])
            
            if training_throughput < 10:
                recommendations.append("Training is slow. Consider batch size optimization or distributed training.")
        
        if not recommendations:
            recommendations.append("Performance appears optimal across all benchmarks.")
        
        return recommendations


class StressBenchmark:
    """Stress testing benchmark for system limits."""
    
    def __init__(self):
        self.process = psutil.Process()
    
    def run_memory_stress_test(self, max_memory_mb: int = 1000, 
                             duration_seconds: int = 60) -> Dict[str, Any]:
        """Run memory stress test."""
        start_time = time.time()
        allocated_arrays = []
        peak_memory = 0
        
        try:
            while time.time() - start_time < duration_seconds:
                current_memory = self.process.memory_info().rss / 1024 / 1024
                peak_memory = max(peak_memory, current_memory)
                
                if current_memory < max_memory_mb:
                    # Allocate more memory
                    array = np.random.random(100000).astype(np.float32)
                    allocated_arrays.append(array)
                
                time.sleep(0.1)
        
        except MemoryError:
            pass  # Expected when reaching memory limits
        
        # Cleanup
        del allocated_arrays
        
        final_memory = self.process.memory_info().rss / 1024 / 1024
        
        return {
            'duration_seconds': time.time() - start_time,
            'peak_memory_mb': peak_memory,
            'final_memory_mb': final_memory,
            'arrays_allocated': len(allocated_arrays) if 'allocated_arrays' in locals() else 0,
            'memory_limit_reached': peak_memory >= max_memory_mb * 0.9
        }
    
    def run_cpu_stress_test(self, duration_seconds: int = 30, 
                          num_threads: int = None) -> Dict[str, Any]:
        """Run CPU stress test."""
        if num_threads is None:
            num_threads = psutil.cpu_count()
        
        def cpu_intensive_task():
            start_time = time.time()
            operations = 0
            
            while time.time() - start_time < duration_seconds:
                # CPU-intensive computation
                np.random.random(1000).sum()
                operations += 1
            
            return operations
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(cpu_intensive_task) for _ in range(num_threads)]
            results = [future.result() for future in futures]
        
        total_time = time.time() - start_time
        total_operations = sum(results)
        
        return {
            'duration_seconds': total_time,
            'num_threads': num_threads,
            'total_operations': total_operations,
            'operations_per_second': total_operations / total_time,
            'operations_per_thread': [r for r in results]
        }


# Global benchmark suite instance
_global_benchmark_suite = BenchmarkSuite()

def get_benchmark_suite() -> BenchmarkSuite:
    """Get global benchmark suite instance."""
    return _global_benchmark_suite

def run_quick_benchmark(component, component_type: str = 'auto') -> BenchmarkResult:
    """Run a quick benchmark on a component."""
    suite = get_benchmark_suite()
    
    if component_type == 'auto':
        if hasattr(component, 'select_action'):
            component_type = 'agent'
        elif hasattr(component, 'step'):
            component_type = 'environment'
        else:
            component_type = 'generic'
    
    if component_type == 'agent':
        return suite.benchmark_agent_inference(component, getattr(component, 'state_dim', 10))
    elif component_type == 'environment':
        return suite.benchmark_environment_step(component)
    else:
        # Generic benchmark
        benchmark = PerformanceBenchmark(f"{type(component).__name__}_benchmark")
        return benchmark.run_benchmark(lambda: component, 100)
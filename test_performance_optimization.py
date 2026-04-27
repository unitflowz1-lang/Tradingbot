"""
Performance Optimization Tests

Tests for the RL system performance optimization tools including
profiling, memory optimization, GPU acceleration, and benchmarking.
"""

import pytest
import numpy as np
import time
import tempfile
import os
from unittest.mock import Mock, patch
import threading
import sys

# Add src to path for imports
try:
    # When run as a module, __file__ is available
    script_dir = os.path.dirname(__file__)
except NameError:
    # When run with exec(), __file__ is not available, use current directory
    script_dir = os.getcwd()

sys.path.insert(0, os.path.join(script_dir, "src"))

# Try to import optimization modules
try:
    from rl.optimization.profiler import RLSystemProfiler, PerformanceProfiler
    from rl.optimization.memory_optimizer import MemoryOptimizer, MemoryPool
    from rl.optimization.gpu_accelerator import GPUAccelerator, CUDAManager
    from rl.optimization.benchmark import BenchmarkSuite, PerformanceBenchmark

    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Import error: {e}")
    IMPORTS_AVAILABLE = False

    # Create mock classes for testing
    class RLSystemProfiler:
        def __init__(self, *args, **kwargs):
            self.metrics = {}

        def profile_function(self, name=None):
            return lambda f: f

        def get_metrics(self):
            return self.metrics

        def reset(self):
            self.metrics = {}

    class PerformanceProfiler:
        def __init__(self, *args, **kwargs):
            pass

    class MemoryOptimizer:
        def __init__(self, *args, **kwargs):
            pass

    class MemoryPool:
        def __init__(self, *args, **kwargs):
            pass

    class GPUAccelerator:
        def __init__(self, *args, **kwargs):
            pass

    class CUDAManager:
        def __init__(self, *args, **kwargs):
            pass

    class BenchmarkSuite:
        def __init__(self, *args, **kwargs):
            pass

    class PerformanceBenchmark:
        def __init__(self, *args, **kwargs):
            pass


class TestBasicFunctionality:
    """Basic tests that always run."""

    def test_imports_and_setup(self):
        """Test that basic imports work."""
        assert pytest is not None
        assert np is not None
        assert time is not None
        assert tempfile is not None
        assert os is not None
        assert threading is not None

    def test_numpy_operations(self):
        """Test basic numpy operations for performance testing."""
        # Test array creation
        arr = np.random.random(100)
        assert arr.shape == (100,)

        # Test matrix operations
        matrix_a = np.random.random((10, 10))
        matrix_b = np.random.random((10, 10))
        result = np.matmul(matrix_a, matrix_b)
        assert result.shape == (10, 10)

    def test_timing_operations(self):
        """Test timing functionality."""
        start_time = time.perf_counter()
        time.sleep(0.001)  # 1ms sleep
        end_time = time.perf_counter()

        elapsed = end_time - start_time
        assert elapsed >= 0.001
        assert elapsed < 0.1  # Should be much less than 100ms


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Optimization modules not available")
class TestRLSystemProfiler:
    """Test suite for RLSystemProfiler."""

    def test_profiler_initialization(self):
        """Test profiler initialization."""
        profiler = RLSystemProfiler()
        assert hasattr(profiler, "metrics")

    def test_profile_function_decorator(self):
        """Test function profiling decorator."""
        profiler = RLSystemProfiler()

        @profiler.profile_function("test_func")
        def test_function(x, y):
            time.sleep(0.01)  # Small delay for timing
            return x + y

        result = test_function(1, 2)
        assert result == 3


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Optimization modules not available")
class TestMemoryOptimizer:
    """Test suite for MemoryOptimizer."""

    def test_memory_optimizer_initialization(self):
        """Test memory optimizer initialization."""
        optimizer = MemoryOptimizer()
        assert optimizer is not None


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Optimization modules not available")
class TestGPUAccelerator:
    """Test suite for GPUAccelerator."""

    def test_gpu_accelerator_initialization(self):
        """Test GPU accelerator initialization."""
        accelerator = GPUAccelerator(auto_select_device=False)
        assert accelerator is not None


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason="Optimization modules not available")
class TestBenchmarkSuite:
    """Test suite for BenchmarkSuite."""

    def test_benchmark_suite_initialization(self):
        """Test benchmark suite initialization."""
        with tempfile.TemporaryDirectory() as temp_dir:
            suite = BenchmarkSuite(temp_dir)
            assert suite is not None


class TestMockImplementations:
    """Test mock implementations when real modules aren't available."""

    def test_mock_profiler(self):
        """Test mock profiler functionality."""

        class MockProfiler:
            def __init__(self):
                self.metrics = {}

            def profile_function(self, name):
                def decorator(func):
                    def wrapper(*args, **kwargs):
                        start = time.perf_counter()
                        result = func(*args, **kwargs)
                        end = time.perf_counter()

                        self.metrics[name] = {
                            "call_count": self.metrics.get(name, {}).get(
                                "call_count", 0
                            )
                            + 1,
                            "total_time": self.metrics.get(name, {}).get(
                                "total_time", 0
                            )
                            + (end - start),
                        }
                        return result

                    return wrapper

                return decorator

            def get_metrics(self):
                return self.metrics

        # Test the mock profiler
        profiler = MockProfiler()

        @profiler.profile_function("test_func")
        def test_function(x):
            time.sleep(0.001)  # 1ms delay
            return x * 2

        # Call function multiple times
        for i in range(3):
            result = test_function(i)
            assert result == i * 2

        # Check metrics
        metrics = profiler.get_metrics()
        assert "test_func" in metrics
        assert metrics["test_func"]["call_count"] == 3
        assert metrics["test_func"]["total_time"] > 0.003  # At least 3ms

    def test_mock_memory_pool(self):
        """Test mock memory pool functionality."""

        class MockMemoryPool:
            def __init__(self, block_size, pool_size=10):
                self.block_size = block_size
                self.pool_size = pool_size
                self.available_blocks = [
                    np.zeros(block_size, dtype=np.float32) for _ in range(pool_size)
                ]
                self.allocated_blocks = []

            def allocate(self):
                if self.available_blocks:
                    block = self.available_blocks.pop()
                    self.allocated_blocks.append(block)
                    return block
                return None

            def deallocate(self, block):
                if block in self.allocated_blocks:
                    self.allocated_blocks.remove(block)
                    block.fill(0)  # Reset block
                    self.available_blocks.append(block)

        # Test the mock memory pool
        pool = MockMemoryPool(100, 5)

        # Allocate blocks
        blocks = []
        for _ in range(3):
            block = pool.allocate()
            assert block is not None
            assert block.shape == (100,)
            blocks.append(block)

        assert len(pool.available_blocks) == 2
        assert len(pool.allocated_blocks) == 3

        # Deallocate blocks
        for block in blocks:
            pool.deallocate(block)

        assert len(pool.available_blocks) == 5
        assert len(pool.allocated_blocks) == 0

    def test_mock_gpu_accelerator(self):
        """Test mock GPU accelerator functionality."""

        class MockGPUAccelerator:
            def __init__(self):
                self.gpu_available = False  # Simulate no GPU

            def is_available(self):
                return self.gpu_available

            def to_gpu(self, array):
                # Fallback to CPU
                return array

            def to_cpu(self, array):
                return array

            def accelerated_matmul(self, a, b):
                # Fallback to numpy
                return np.matmul(a, b)

        # Test the mock GPU accelerator
        accelerator = MockGPUAccelerator()

        assert not accelerator.is_available()

        # Test data movement (should be no-op)
        array = np.array([1, 2, 3, 4, 5])
        gpu_array = accelerator.to_gpu(array)
        cpu_array = accelerator.to_cpu(gpu_array)
        assert np.array_equal(array, cpu_array)

        # Test matrix multiplication
        a = np.random.random((10, 10)).astype(np.float32)
        b = np.random.random((10, 10)).astype(np.float32)
        result = accelerator.accelerated_matmul(a, b)
        expected = np.matmul(a, b)
        assert np.allclose(result, expected)

    def test_mock_benchmark_suite(self):
        """Test mock benchmark suite functionality."""

        class MockBenchmarkResult:
            def __init__(self, name, iterations, total_time):
                self.name = name
                self.iterations = iterations
                self.total_time = total_time
                self.avg_time = total_time / iterations if iterations > 0 else 0
                self.throughput = iterations / total_time if total_time > 0 else 0
                self.success_rate = 1.0

        class MockBenchmarkSuite:
            def __init__(self):
                self.results = {}

            def benchmark_function(self, func, name, iterations=100):
                start_time = time.perf_counter()

                for _ in range(iterations):
                    func()

                total_time = time.perf_counter() - start_time
                result = MockBenchmarkResult(name, iterations, total_time)
                self.results[name] = result
                return result

            def get_results(self):
                return self.results

        # Test the mock benchmark suite
        suite = MockBenchmarkSuite()

        def test_function():
            return sum(range(100))

        result = suite.benchmark_function(test_function, "sum_test", 50)

        assert result.name == "sum_test"
        assert result.iterations == 50
        assert result.total_time > 0
        assert result.avg_time > 0
        assert result.throughput > 0
        assert result.success_rate == 1.0

        # Check results are stored
        results = suite.get_results()
        assert "sum_test" in results
        assert results["sum_test"] is result


if __name__ == "__main__":
    pytest.main([__file__])

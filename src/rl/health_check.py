"""
Health check endpoints for RL system components.
"""
import os
import time
import psutil
import logging
from typing import Dict, Any, Optional
from pathlib import Path
import torch
import redis
from prometheus_client import Gauge, Counter, generate_latest

logger = logging.getLogger(__name__)

# Prometheus metrics
health_status = Gauge('rl_system_health_status', 'Health status of RL system', ['component'])
memory_usage = Gauge('rl_system_memory_usage_bytes', 'Memory usage in bytes')
cpu_usage = Gauge('rl_system_cpu_usage_percent', 'CPU usage percentage')
gpu_usage = Gauge('rl_system_gpu_usage_percent', 'GPU usage percentage')
model_load_time = Gauge('rl_model_load_time_seconds', 'Time to load model')
inference_requests = Counter('rl_inference_requests_total', 'Total inference requests')

class HealthChecker:
    """Health checker for RL system components."""
    
    def __init__(self):
        self.start_time = time.time()
        self.redis_client = None
        self._initialize_redis()
    
    def _initialize_redis(self):
        """Initialize Redis connection for health checks."""
        try:
            redis_host = os.getenv('REDIS_HOST', 'localhost')
            redis_port = int(os.getenv('REDIS_PORT', 6379))
            self.redis_client = redis.Redis(
                host=redis_host, 
                port=redis_port, 
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
        except Exception as e:
            logger.warning(f"Failed to initialize Redis client: {e}")
    
    def check_system_resources(self) -> Dict[str, Any]:
        """Check system resource usage."""
        try:
            # Memory usage
            memory = psutil.virtual_memory()
            memory_usage.set(memory.used)
            
            # CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            cpu_usage.set(cpu_percent)
            
            # GPU usage (if available)
            gpu_percent = 0
            if torch.cuda.is_available():
                try:
                    gpu_percent = torch.cuda.utilization()
                    gpu_usage.set(gpu_percent)
                except Exception:
                    pass
            
            return {
                'memory_used_gb': round(memory.used / (1024**3), 2),
                'memory_percent': memory.percent,
                'cpu_percent': cpu_percent,
                'gpu_percent': gpu_percent,
                'disk_usage': psutil.disk_usage('/').percent
            }
        except Exception as e:
            logger.error(f"Error checking system resources: {e}")
            return {'error': str(e)}
    
    def check_redis_connection(self) -> Dict[str, Any]:
        """Check Redis connection and performance."""
        if not self.redis_client:
            return {'status': 'unavailable', 'error': 'Redis client not initialized'}
        
        try:
            start_time = time.time()
            self.redis_client.ping()
            ping_time = time.time() - start_time
            
            info = self.redis_client.info()
            return {
                'status': 'healthy',
                'ping_time_ms': round(ping_time * 1000, 2),
                'connected_clients': info.get('connected_clients', 0),
                'used_memory_mb': round(info.get('used_memory', 0) / (1024**2), 2)
            }
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return {'status': 'unhealthy', 'error': str(e)}
    
    def check_model_availability(self, model_path: Optional[str] = None) -> Dict[str, Any]:
        """Check if required models are available and loadable."""
        if not model_path:
            model_path = os.getenv('MODEL_PATH', '/app/models')
        
        try:
            model_dir = Path(model_path)
            if not model_dir.exists():
                return {'status': 'unavailable', 'error': 'Model directory not found'}
            
            # Check for model files
            model_files = list(model_dir.glob('*.pt')) + list(model_dir.glob('*.pth'))
            if not model_files:
                return {'status': 'no_models', 'error': 'No model files found'}
            
            # Try to load a model (quick check)
            latest_model = max(model_files, key=lambda x: x.stat().st_mtime)
            start_time = time.time()
            
            try:
                # Quick model validation without full loading
                checkpoint = torch.load(latest_model, map_location='cpu')
                load_time = time.time() - start_time
                model_load_time.set(load_time)
                
                return {
                    'status': 'healthy',
                    'model_count': len(model_files),
                    'latest_model': latest_model.name,
                    'load_time_ms': round(load_time * 1000, 2)
                }
            except Exception as e:
                return {'status': 'corrupt', 'error': f'Model loading failed: {e}'}
                
        except Exception as e:
            logger.error(f"Model availability check failed: {e}")
            return {'status': 'error', 'error': str(e)}
    
    def get_uptime(self) -> float:
        """Get system uptime in seconds."""
        return time.time() - self.start_time

def check_training_health() -> Dict[str, Any]:
    """Comprehensive health check for training components."""
    checker = HealthChecker()
    
    health_data = {
        'timestamp': time.time(),
        'uptime_seconds': checker.get_uptime(),
        'component': 'training',
        'status': 'healthy'
    }
    
    # Check system resources
    resources = checker.check_system_resources()
    health_data['resources'] = resources
    
    # Check Redis connection
    redis_status = checker.check_redis_connection()
    health_data['redis'] = redis_status
    
    # Check model directory
    model_status = checker.check_model_availability()
    health_data['models'] = model_status
    
    # Determine overall health
    if (redis_status.get('status') != 'healthy' or 
        model_status.get('status') in ['error', 'corrupt'] or
        resources.get('memory_percent', 0) > 90 or
        resources.get('cpu_percent', 0) > 95):
        health_data['status'] = 'unhealthy'
        health_status.labels(component='training').set(0)
    else:
        health_status.labels(component='training').set(1)
    
    return health_data

def check_inference_health() -> Dict[str, Any]:
    """Comprehensive health check for inference components."""
    checker = HealthChecker()
    
    health_data = {
        'timestamp': time.time(),
        'uptime_seconds': checker.get_uptime(),
        'component': 'inference',
        'status': 'healthy'
    }
    
    # Check system resources
    resources = checker.check_system_resources()
    health_data['resources'] = resources
    
    # Check model availability
    model_status = checker.check_model_availability()
    health_data['models'] = model_status
    
    # Determine overall health
    if (model_status.get('status') not in ['healthy'] or
        resources.get('memory_percent', 0) > 85 or
        resources.get('cpu_percent', 0) > 90):
        health_data['status'] = 'unhealthy'
        health_status.labels(component='inference').set(0)
    else:
        health_status.labels(component='inference').set(1)
    
    return health_data

def get_metrics() -> str:
    """Get Prometheus metrics."""
    return generate_latest()

if __name__ == "__main__":
    # CLI health check
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == 'training':
        result = check_training_health()
    else:
        result = check_inference_health()
    
    print(f"Health Status: {result['status']}")
    if result['status'] != 'healthy':
        sys.exit(1)
"""
Resource management and dynamic scaling for distributed training.
"""
import os
import time
import logging
import psutil
import threading
from typing import Dict, Any, List, Optional, Tuple, Union
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import json

import torch
import redis
from kubernetes import client, config as k8s_config
from kubernetes.client.rest import ApiException

logger = logging.getLogger(__name__)

@dataclass
class ResourceMetrics:
    """Resource usage metrics."""
    cpu_percent: float
    memory_percent: float
    gpu_percent: float
    gpu_memory_percent: float
    disk_io_percent: float
    network_io_mbps: float
    timestamp: float


@dataclass
class ResourceUsage:
    """Compatibility snapshot used by older optimization code/tests."""
    memory_gb: float
    cpu_percent: float
    time_elapsed: float


@dataclass
class ResourceLimits:
    """Compatibility limits object used by optimization/resource tests."""
    max_memory_gb: float
    max_cpu_percent: float
    max_time_seconds: float = 3600.0
    max_concurrent_trials: int = 1

@dataclass
class ScalingDecision:
    """Scaling decision information."""
    action: str  # 'scale_up', 'scale_down', 'no_action'
    target_replicas: int
    reason: str
    confidence: float
    timestamp: float


class ResourceAllocator:
    """Simple in-process allocation guard used by optimization workflows."""

    def __init__(self, limits: ResourceLimits):
        self.limits = limits
        self.allocated_memory = 0.0
        self.allocated_cpu = 0.0
        self.active_allocations: Dict[int, Dict[str, float]] = {}

    def request_resources(self, trial_id: int, memory_gb: float, cpu_percent: float) -> bool:
        if len(self.active_allocations) >= int(self.limits.max_concurrent_trials):
            return False
        if (self.allocated_memory + float(memory_gb)) > float(self.limits.max_memory_gb):
            return False
        if (self.allocated_cpu + float(cpu_percent)) > float(self.limits.max_cpu_percent):
            return False

        self.active_allocations[int(trial_id)] = {
            "memory_gb": float(memory_gb),
            "cpu_percent": float(cpu_percent),
        }
        self.allocated_memory += float(memory_gb)
        self.allocated_cpu += float(cpu_percent)
        return True

    def release_resources(self, trial_id: int) -> None:
        allocation = self.active_allocations.pop(int(trial_id), None)
        if allocation is None:
            return
        self.allocated_memory = max(0.0, self.allocated_memory - float(allocation["memory_gb"]))
        self.allocated_cpu = max(0.0, self.allocated_cpu - float(allocation["cpu_percent"]))

    def get_allocation_summary(self) -> Dict[str, Any]:
        return {
            "allocated_memory_gb": self.allocated_memory,
            "allocated_cpu_percent": self.allocated_cpu,
            "active_trials": len(self.active_allocations),
            "utilization": {
                "memory_percent": (
                    (self.allocated_memory / float(self.limits.max_memory_gb)) * 100.0
                    if float(self.limits.max_memory_gb) > 0
                    else 0.0
                ),
                "cpu_percent": (
                    (self.allocated_cpu / float(self.limits.max_cpu_percent)) * 100.0
                    if float(self.limits.max_cpu_percent) > 0
                    else 0.0
                ),
            },
        }

class ResourceMonitor:
    """Monitor system resource usage."""
    
    def __init__(
        self,
        limits: Optional[ResourceLimits] = None,
        monitoring_interval: float = 30.0,
        check_interval: Optional[float] = None,
    ):
        self.limits = limits
        self.monitoring_interval = float(check_interval if check_interval is not None else monitoring_interval)
        self.check_interval = self.monitoring_interval
        self.metrics_history: List[ResourceMetrics] = []
        self.resource_history: List[ResourceUsage] = []
        self.max_history_size = 100
        self.monitoring_active = False
        self.is_monitoring = False
        self.monitor_thread = None
        self.active_trials: Dict[int, float] = {}
        self._started_at: Optional[float] = None
        
    def start_monitoring(self):
        """Start resource monitoring."""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.is_monitoring = True
        if self._started_at is None:
            self._started_at = time.time()
        self.monitor_thread = threading.Thread(target=self._monitoring_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        logger.info("Resource monitoring started")
    
    def stop_monitoring(self):
        """Stop resource monitoring."""
        self.monitoring_active = False
        self.is_monitoring = False
        if self.monitor_thread:
            self.monitor_thread.join(timeout=5)
        
        logger.info("Resource monitoring stopped")
    
    def _monitoring_loop(self):
        """Main monitoring loop."""
        while self.monitoring_active:
            try:
                metrics = self._collect_metrics()
                self._store_metrics(metrics)
                self.resource_history.append(self._get_current_usage())
                if len(self.resource_history) > self.max_history_size:
                    self.resource_history = self.resource_history[-self.max_history_size:]
                time.sleep(self.monitoring_interval)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(self.monitoring_interval)
    
    def _collect_metrics(self) -> ResourceMetrics:
        """Collect current resource metrics."""
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        
        # Memory usage
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        # GPU usage (if available)
        gpu_percent = 0
        gpu_memory_percent = 0
        if torch.cuda.is_available():
            try:
                gpu_percent = torch.cuda.utilization()
                gpu_memory = torch.cuda.memory_stats()
                gpu_memory_percent = (
                    gpu_memory['allocated_bytes.all.current'] / 
                    gpu_memory['reserved_bytes.all.current'] * 100
                    if gpu_memory['reserved_bytes.all.current'] > 0 else 0
                )
            except Exception:
                pass
        
        # Disk I/O
        disk_io = psutil.disk_io_counters()
        disk_io_percent = 0  # Simplified - would need baseline for percentage
        
        # Network I/O
        network_io = psutil.net_io_counters()
        network_io_mbps = (network_io.bytes_sent + network_io.bytes_recv) / (1024 * 1024)
        
        return ResourceMetrics(
            cpu_percent=cpu_percent,
            memory_percent=memory_percent,
            gpu_percent=gpu_percent,
            gpu_memory_percent=gpu_memory_percent,
            disk_io_percent=disk_io_percent,
            network_io_mbps=network_io_mbps,
            timestamp=time.time()
        )
    
    def _store_metrics(self, metrics: ResourceMetrics):
        """Store metrics in history."""
        self.metrics_history.append(metrics)
        
        # Keep only recent metrics
        if len(self.metrics_history) > self.max_history_size:
            self.metrics_history = self.metrics_history[-self.max_history_size:]

    def register_trial(self, trial_id: int) -> None:
        self.active_trials[int(trial_id)] = time.time()

    def unregister_trial(self, trial_id: int) -> None:
        self.active_trials.pop(int(trial_id), None)

    def _get_current_usage(self) -> ResourceUsage:
        process = psutil.Process(os.getpid())
        memory_gb = float(process.memory_info().rss) / (1024 ** 3)
        cpu_percent = float(psutil.cpu_percent(interval=None))
        time_elapsed = 0.0 if self._started_at is None else max(0.0, time.time() - self._started_at)
        return ResourceUsage(
            memory_gb=memory_gb,
            cpu_percent=cpu_percent,
            time_elapsed=time_elapsed,
        )

    def get_resource_summary(self) -> Dict[str, Any]:
        if self.resource_history:
            current = self.resource_history[-1]
            avg_memory = sum(item.memory_gb for item in self.resource_history) / len(self.resource_history)
            max_cpu = max(item.cpu_percent for item in self.resource_history)
        else:
            current = self._get_current_usage()
            avg_memory = current.memory_gb
            max_cpu = current.cpu_percent
        return {
            "current_memory_gb": current.memory_gb,
            "current_cpu_percent": current.cpu_percent,
            "avg_memory_gb": avg_memory,
            "max_cpu_percent": max_cpu,
            "monitoring_duration": current.time_elapsed,
            "active_trials": len(self.active_trials),
        }
    
    def get_current_metrics(self) -> Optional[ResourceMetrics]:
        """Get most recent metrics."""
        return self.metrics_history[-1] if self.metrics_history else None
    
    def get_average_metrics(self, window_minutes: int = 5) -> Optional[ResourceMetrics]:
        """Get average metrics over time window."""
        if not self.metrics_history:
            return None
        
        cutoff_time = time.time() - (window_minutes * 60)
        recent_metrics = [
            m for m in self.metrics_history 
            if m.timestamp >= cutoff_time
        ]
        
        if not recent_metrics:
            return None
        
        # Calculate averages
        avg_cpu = sum(m.cpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_memory = sum(m.memory_percent for m in recent_metrics) / len(recent_metrics)
        avg_gpu = sum(m.gpu_percent for m in recent_metrics) / len(recent_metrics)
        avg_gpu_memory = sum(m.gpu_memory_percent for m in recent_metrics) / len(recent_metrics)
        avg_disk_io = sum(m.disk_io_percent for m in recent_metrics) / len(recent_metrics)
        avg_network_io = sum(m.network_io_mbps for m in recent_metrics) / len(recent_metrics)
        
        return ResourceMetrics(
            cpu_percent=avg_cpu,
            memory_percent=avg_memory,
            gpu_percent=avg_gpu,
            gpu_memory_percent=avg_gpu_memory,
            disk_io_percent=avg_disk_io,
            network_io_mbps=avg_network_io,
            timestamp=time.time()
        )

class AutoScaler:
    """Automatic scaling for distributed training workloads."""
    
    def __init__(self, 
                 namespace: str = "rl-trading",
                 deployment_name: str = "rl-training",
                 min_replicas: int = 1,
                 max_replicas: int = 10,
                 scale_up_threshold: float = 80.0,
                 scale_down_threshold: float = 30.0,
                 cooldown_minutes: int = 5):
        
        self.namespace = namespace
        self.deployment_name = deployment_name
        self.min_replicas = min_replicas
        self.max_replicas = max_replicas
        self.scale_up_threshold = scale_up_threshold
        self.scale_down_threshold = scale_down_threshold
        self.cooldown_seconds = cooldown_minutes * 60
        
        # Kubernetes client
        self.k8s_apps_v1 = None
        self.k8s_metrics_v1 = None
        self._init_k8s_client()
        
        # Scaling state
        self.last_scale_time = 0
        self.scaling_history: List[ScalingDecision] = []
        
        # Resource monitor
        self.resource_monitor = ResourceMonitor()
        
    def _init_k8s_client(self):
        """Initialize Kubernetes client."""
        try:
            # Try in-cluster config first
            k8s_config.load_incluster_config()
        except k8s_config.ConfigException:
            try:
                # Fall back to local kubeconfig
                k8s_config.load_kube_config()
            except k8s_config.ConfigException:
                logger.warning("Could not load Kubernetes config - scaling disabled")
                return
        
        self.k8s_apps_v1 = client.AppsV1Api()
        try:
            from kubernetes import client as metrics_client
            self.k8s_metrics_v1 = metrics_client.CustomObjectsApi()
        except ImportError:
            logger.warning("Kubernetes metrics API not available")
    
    def start_autoscaling(self):
        """Start automatic scaling."""
        if not self.k8s_apps_v1:
            logger.warning("Kubernetes client not available - autoscaling disabled")
            return
        
        self.resource_monitor.start_monitoring()
        
        # Start scaling loop
        scaling_thread = threading.Thread(target=self._scaling_loop)
        scaling_thread.daemon = True
        scaling_thread.start()
        
        logger.info("Autoscaling started")
    
    def stop_autoscaling(self):
        """Stop automatic scaling."""
        self.resource_monitor.stop_monitoring()
        logger.info("Autoscaling stopped")
    
    def _scaling_loop(self):
        """Main scaling decision loop."""
        while True:
            try:
                # Check if we're in cooldown period
                if time.time() - self.last_scale_time < self.cooldown_seconds:
                    time.sleep(30)
                    continue
                
                # Make scaling decision
                decision = self._make_scaling_decision()
                
                if decision.action != 'no_action':
                    success = self._execute_scaling_decision(decision)
                    if success:
                        self.last_scale_time = time.time()
                        self.scaling_history.append(decision)
                
                time.sleep(60)  # Check every minute
                
            except Exception as e:
                logger.error(f"Error in scaling loop: {e}")
                time.sleep(60)
    
    def _make_scaling_decision(self) -> ScalingDecision:
        """Make scaling decision based on current metrics."""
        try:
            # Get current resource metrics
            current_metrics = self.resource_monitor.get_average_metrics(window_minutes=3)
            if not current_metrics:
                return ScalingDecision(
                    action='no_action',
                    target_replicas=0,
                    reason='No metrics available',
                    confidence=0.0,
                    timestamp=time.time()
                )
            
            # Get current replica count
            current_replicas = self._get_current_replicas()
            if current_replicas is None:
                return ScalingDecision(
                    action='no_action',
                    target_replicas=0,
                    reason='Could not get current replica count',
                    confidence=0.0,
                    timestamp=time.time()
                )
            
            # Calculate resource pressure
            resource_pressure = max(
                current_metrics.cpu_percent,
                current_metrics.memory_percent,
                current_metrics.gpu_percent
            )
            
            # Scale up decision
            if (resource_pressure > self.scale_up_threshold and 
                current_replicas < self.max_replicas):
                
                # Calculate target replicas based on pressure
                scale_factor = min(2.0, resource_pressure / self.scale_up_threshold)
                target_replicas = min(
                    self.max_replicas,
                    int(current_replicas * scale_factor)
                )
                
                return ScalingDecision(
                    action='scale_up',
                    target_replicas=target_replicas,
                    reason=f'High resource pressure: {resource_pressure:.1f}%',
                    confidence=min(1.0, (resource_pressure - self.scale_up_threshold) / 20.0),
                    timestamp=time.time()
                )
            
            # Scale down decision
            elif (resource_pressure < self.scale_down_threshold and 
                  current_replicas > self.min_replicas):
                
                # Calculate target replicas
                scale_factor = max(0.5, resource_pressure / self.scale_down_threshold)
                target_replicas = max(
                    self.min_replicas,
                    int(current_replicas * scale_factor)
                )
                
                return ScalingDecision(
                    action='scale_down',
                    target_replicas=target_replicas,
                    reason=f'Low resource pressure: {resource_pressure:.1f}%',
                    confidence=min(1.0, (self.scale_down_threshold - resource_pressure) / 20.0),
                    timestamp=time.time()
                )
            
            # No action needed
            return ScalingDecision(
                action='no_action',
                target_replicas=current_replicas,
                reason=f'Resource pressure within bounds: {resource_pressure:.1f}%',
                confidence=1.0,
                timestamp=time.time()
            )
            
        except Exception as e:
            logger.error(f"Error making scaling decision: {e}")
            return ScalingDecision(
                action='no_action',
                target_replicas=0,
                reason=f'Error: {str(e)}',
                confidence=0.0,
                timestamp=time.time()
            )
    
    def _get_current_replicas(self) -> Optional[int]:
        """Get current number of replicas."""
        try:
            deployment = self.k8s_apps_v1.read_namespaced_deployment(
                name=self.deployment_name,
                namespace=self.namespace
            )
            return deployment.spec.replicas
        except ApiException as e:
            logger.error(f"Error getting current replicas: {e}")
            return None
    
    def _execute_scaling_decision(self, decision: ScalingDecision) -> bool:
        """Execute scaling decision."""
        try:
            logger.info(
                f"Executing scaling decision: {decision.action} to {decision.target_replicas} replicas"
                f" (reason: {decision.reason})"
            )
            
            # Update deployment replica count
            body = {'spec': {'replicas': decision.target_replicas}}
            
            self.k8s_apps_v1.patch_namespaced_deployment(
                name=self.deployment_name,
                namespace=self.namespace,
                body=body
            )
            
            logger.info(f"Successfully scaled deployment to {decision.target_replicas} replicas")
            return True
            
        except ApiException as e:
            logger.error(f"Error executing scaling decision: {e}")
            return False

class ResourceManager:
    """Main resource manager coordinating monitoring and scaling."""
    
    def __init__(self, config: Union[Dict[str, Any], ResourceLimits]):
        if isinstance(config, ResourceLimits):
            self.limits = config
            self.config = {
                "monitoring_interval": 30.0,
                "max_memory_gb": config.max_memory_gb,
                "max_cpu_percent": config.max_cpu_percent,
                "max_time_seconds": config.max_time_seconds,
                "max_concurrent_trials": config.max_concurrent_trials,
            }
        else:
            self.config = config
            self.limits = ResourceLimits(
                max_memory_gb=float(config.get("max_memory_gb", config.get("max_memory_per_trial", 4.0))),
                max_cpu_percent=float(config.get("max_cpu_percent", 100.0)),
                max_time_seconds=float(config.get("max_time_seconds", config.get("max_time_per_trial", 3600.0))),
                max_concurrent_trials=int(config.get("max_concurrent_trials", max(1, int(config.get("n_jobs", 1))))),
            )
        self.is_running = False
        
        # Initialize components
        self.resource_monitor = ResourceMonitor(
            limits=self.limits,
            monitoring_interval=self.config.get('monitoring_interval', 30.0)
        )
        self.monitor = self.resource_monitor
        self.allocator = ResourceAllocator(self.limits)
        
        self.autoscaler = AutoScaler(
            namespace=self.config.get('namespace', 'rl-trading'),
            deployment_name=self.config.get('deployment_name', 'rl-training'),
            min_replicas=self.config.get('min_replicas', 1),
            max_replicas=self.config.get('max_replicas', 10),
            scale_up_threshold=self.config.get('scale_up_threshold', 80.0),
            scale_down_threshold=self.config.get('scale_down_threshold', 30.0),
            cooldown_minutes=self.config.get('cooldown_minutes', 5)
        )
        
        # Redis for coordination
        self.redis_client = redis.Redis(
            host=self.config.get('redis_host', 'localhost'),
            port=self.config.get('redis_port', 6379),
            decode_responses=True
        )
        
    def start(self):
        """Start resource management."""
        logger.info("Starting resource manager")
        self.is_running = True
        
        self.resource_monitor.start_monitoring()
        self.autoscaler.start_autoscaling()
        
        # Start metrics publishing
        metrics_thread = threading.Thread(target=self._publish_metrics_loop)
        metrics_thread.daemon = True
        metrics_thread.start()
    
    def stop(self):
        """Stop resource management."""
        logger.info("Stopping resource manager")
        self.is_running = False
        
        self.resource_monitor.stop_monitoring()
        self.autoscaler.stop_autoscaling()

    def register_trial(self, trial_id: int, memory_gb: float, cpu_percent: float) -> bool:
        allocated = self.allocator.request_resources(trial_id, memory_gb, cpu_percent)
        if allocated:
            self.monitor.register_trial(trial_id)
        return allocated

    def unregister_trial(self, trial_id: int) -> None:
        self.allocator.release_resources(trial_id)
        self.monitor.unregister_trial(trial_id)

    def get_status(self) -> Dict[str, Any]:
        return {
            "is_running": self.is_running,
            "limits": {
                "max_memory_gb": self.limits.max_memory_gb,
                "max_cpu_percent": self.limits.max_cpu_percent,
                "max_time_seconds": self.limits.max_time_seconds,
                "max_concurrent_trials": self.limits.max_concurrent_trials,
            },
            "monitoring": self.monitor.get_resource_summary(),
            "allocation": self.allocator.get_allocation_summary(),
        }
    
    def _publish_metrics_loop(self):
        """Publish metrics to Redis for coordination."""
        while True:
            try:
                metrics = self.resource_monitor.get_current_metrics()
                if metrics:
                    # Publish to Redis
                    metrics_data = {
                        'cpu_percent': metrics.cpu_percent,
                        'memory_percent': metrics.memory_percent,
                        'gpu_percent': metrics.gpu_percent,
                        'timestamp': metrics.timestamp,
                        'worker_id': os.getenv('WORKER_ID', 'unknown')
                    }
                    
                    self.redis_client.hset(
                        'resource_metrics',
                        os.getenv('WORKER_ID', 'unknown'),
                        json.dumps(metrics_data)
                    )
                    
                    # Set expiry
                    self.redis_client.expire('resource_metrics', 300)
                
                time.sleep(30)
                
            except Exception as e:
                logger.error(f"Error publishing metrics: {e}")
                time.sleep(30)
    
    def get_cluster_metrics(self) -> Dict[str, Any]:
        """Get aggregated cluster metrics."""
        try:
            # Get all worker metrics from Redis
            worker_metrics = self.redis_client.hgetall('resource_metrics')
            
            if not worker_metrics:
                return {}
            
            # Parse and aggregate
            total_cpu = 0
            total_memory = 0
            total_gpu = 0
            worker_count = 0
            
            for worker_id, metrics_json in worker_metrics.items():
                try:
                    metrics = json.loads(metrics_json)
                    total_cpu += metrics['cpu_percent']
                    total_memory += metrics['memory_percent']
                    total_gpu += metrics['gpu_percent']
                    worker_count += 1
                except Exception:
                    continue
            
            if worker_count == 0:
                return {}
            
            return {
                'average_cpu_percent': total_cpu / worker_count,
                'average_memory_percent': total_memory / worker_count,
                'average_gpu_percent': total_gpu / worker_count,
                'active_workers': worker_count,
                'timestamp': time.time()
            }
            
        except Exception as e:
            logger.error(f"Error getting cluster metrics: {e}")
            return {}

if __name__ == "__main__":
    # Example usage
    config = {
        'monitoring_interval': 30.0,
        'namespace': os.getenv('K8S_NAMESPACE', 'rl-trading'),
        'deployment_name': os.getenv('DEPLOYMENT_NAME', 'rl-training'),
        'min_replicas': int(os.getenv('MIN_REPLICAS', 1)),
        'max_replicas': int(os.getenv('MAX_REPLICAS', 10)),
        'scale_up_threshold': float(os.getenv('SCALE_UP_THRESHOLD', 80.0)),
        'scale_down_threshold': float(os.getenv('SCALE_DOWN_THRESHOLD', 30.0)),
        'redis_host': os.getenv('REDIS_HOST', 'localhost'),
        'redis_port': int(os.getenv('REDIS_PORT', 6379))
    }
    
    resource_manager = ResourceManager(config)
    resource_manager.start()
    
    try:
        # Keep running
        while True:
            time.sleep(60)
            cluster_metrics = resource_manager.get_cluster_metrics()
            if cluster_metrics:
                logger.info(f"Cluster metrics: {cluster_metrics}")
    except KeyboardInterrupt:
        resource_manager.stop()

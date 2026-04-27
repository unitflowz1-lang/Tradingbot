"""
Health check system for the AI Forex Trading Bot
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from enum import Enum
import aiohttp
from aiohttp import web
import psutil


class HealthStatus(Enum):
    """Health status enumeration"""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a system component"""
    name: str
    status: HealthStatus
    message: str
    last_check: datetime
    response_time_ms: Optional[float] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class SystemHealth:
    """Overall system health status"""
    status: HealthStatus
    timestamp: datetime
    uptime_seconds: float
    components: List[ComponentHealth]
    system_metrics: Dict[str, Any]


class HealthChecker:
    """Health check system for monitoring system components"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.start_time = time.time()
        self.components: Dict[str, ComponentHealth] = {}
        self.check_interval = 30  # seconds
        self.running = False
        self._check_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the health check system"""
        self.running = True
        self._check_task = asyncio.create_task(self._periodic_checks())
        self.logger.info("Health check system started")
    
    async def stop(self):
        """Stop the health check system"""
        self.running = False
        if self._check_task:
            self._check_task.cancel()
            try:
                await self._check_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Health check system stopped")
    
    async def _periodic_checks(self):
        """Run periodic health checks"""
        while self.running:
            try:
                await self._run_all_checks()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic health checks: {e}")
                await asyncio.sleep(5)  # Short delay before retry
    
    async def _run_all_checks(self):
        """Run all registered health checks"""
        tasks = [
            self._check_database(),
            self._check_broker_api(),
            self._check_llm_api(),
            self._check_system_resources(),
            self._check_trading_engine(),
        ]
        
        await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _check_database(self):
        """Check database connectivity"""
        start_time = time.time()
        try:
            # This would normally connect to the actual database
            # For now, we'll simulate a check
            await asyncio.sleep(0.1)  # Simulate DB query time
            
            response_time = (time.time() - start_time) * 1000
            
            self.components["database"] = ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                message="Database connection successful",
                last_check=datetime.now(),
                response_time_ms=response_time,
                details={"connection_pool": "active"}
            )
        except Exception as e:
            self.components["database"] = ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                message=f"Database connection failed: {str(e)}",
                last_check=datetime.now(),
                response_time_ms=(time.time() - start_time) * 1000
            )
    
    async def _check_broker_api(self):
        """Check broker API connectivity"""
        start_time = time.time()
        try:
            # Simulate broker API check
            await asyncio.sleep(0.2)  # Simulate API call time
            
            response_time = (time.time() - start_time) * 1000
            
            self.components["broker_api"] = ComponentHealth(
                name="broker_api",
                status=HealthStatus.HEALTHY,
                message="Broker API connection successful",
                last_check=datetime.now(),
                response_time_ms=response_time,
                details={"api_version": "v1", "rate_limit_remaining": 1000}
            )
        except Exception as e:
            self.components["broker_api"] = ComponentHealth(
                name="broker_api",
                status=HealthStatus.UNHEALTHY,
                message=f"Broker API connection failed: {str(e)}",
                last_check=datetime.now(),
                response_time_ms=(time.time() - start_time) * 1000
            )
    
    async def _check_llm_api(self):
        """Check LLM API connectivity"""
        start_time = time.time()
        try:
            # Simulate LLM API check
            await asyncio.sleep(0.3)  # Simulate API call time
            
            response_time = (time.time() - start_time) * 1000
            
            self.components["llm_api"] = ComponentHealth(
                name="llm_api",
                status=HealthStatus.HEALTHY,
                message="LLM API connection successful",
                last_check=datetime.now(),
                response_time_ms=response_time,
                details={"model": "gpt-4", "tokens_remaining": 50000}
            )
        except Exception as e:
            self.components["llm_api"] = ComponentHealth(
                name="llm_api",
                status=HealthStatus.UNHEALTHY,
                message=f"LLM API connection failed: {str(e)}",
                last_check=datetime.now(),
                response_time_ms=(time.time() - start_time) * 1000
            )
    
    async def _check_system_resources(self):
        """Check system resource usage"""
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # Determine status based on resource usage
            status = HealthStatus.HEALTHY
            message = "System resources normal"
            
            if cpu_percent > 90 or memory.percent > 90 or disk.percent > 90:
                status = HealthStatus.UNHEALTHY
                message = "System resources critical"
            elif cpu_percent > 70 or memory.percent > 70 or disk.percent > 80:
                status = HealthStatus.DEGRADED
                message = "System resources elevated"
            
            self.components["system_resources"] = ComponentHealth(
                name="system_resources",
                status=status,
                message=message,
                last_check=datetime.now(),
                details={
                    "cpu_percent": cpu_percent,
                    "memory_percent": memory.percent,
                    "disk_percent": disk.percent,
                    "memory_available_gb": round(memory.available / (1024**3), 2),
                    "disk_free_gb": round(disk.free / (1024**3), 2)
                }
            )
        except Exception as e:
            self.components["system_resources"] = ComponentHealth(
                name="system_resources",
                status=HealthStatus.UNHEALTHY,
                message=f"Failed to check system resources: {str(e)}",
                last_check=datetime.now()
            )
    
    async def _check_trading_engine(self):
        """Check trading engine status"""
        try:
            # This would check if the trading engine is running properly
            # For now, we'll simulate the check
            
            self.components["trading_engine"] = ComponentHealth(
                name="trading_engine",
                status=HealthStatus.HEALTHY,
                message="Trading engine operational",
                last_check=datetime.now(),
                details={
                    "active_positions": 2,
                    "pending_orders": 1,
                    "last_signal_time": datetime.now().isoformat()
                }
            )
        except Exception as e:
            self.components["trading_engine"] = ComponentHealth(
                name="trading_engine",
                status=HealthStatus.UNHEALTHY,
                message=f"Trading engine check failed: {str(e)}",
                last_check=datetime.now()
            )
    
    def get_system_health(self) -> SystemHealth:
        """Get overall system health status"""
        # Determine overall status
        if not self.components:
            overall_status = HealthStatus.UNHEALTHY
        else:
            unhealthy_count = sum(1 for c in self.components.values() if c.status == HealthStatus.UNHEALTHY)
            degraded_count = sum(1 for c in self.components.values() if c.status == HealthStatus.DEGRADED)
            
            if unhealthy_count > 0:
                overall_status = HealthStatus.UNHEALTHY
            elif degraded_count > 0:
                overall_status = HealthStatus.DEGRADED
            else:
                overall_status = HealthStatus.HEALTHY
        
        # Get system metrics
        try:
            system_metrics = {
                "cpu_count": psutil.cpu_count(),
                "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
                "disk_total_gb": round(psutil.disk_usage('/').total / (1024**3), 2),
                "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
                "python_version": f"{psutil.version_info.major}.{psutil.version_info.minor}.{psutil.version_info.micro}"
            }
        except Exception:
            system_metrics = {}
        
        return SystemHealth(
            status=overall_status,
            timestamp=datetime.now(),
            uptime_seconds=time.time() - self.start_time,
            components=list(self.components.values()),
            system_metrics=system_metrics
        )


class HealthCheckServer:
    """HTTP server for health check endpoints"""
    
    def __init__(self, health_checker: HealthChecker, port: int = 8080):
        self.health_checker = health_checker
        self.port = port
        self.app = web.Application()
        self.runner: Optional[web.AppRunner] = None
        self.site: Optional[web.TCPSite] = None
        self.logger = logging.getLogger(__name__)
        
        # Setup routes
        self.app.router.add_get('/health', self._health_endpoint)
        self.app.router.add_get('/health/detailed', self._detailed_health_endpoint)
        self.app.router.add_get('/health/ready', self._readiness_endpoint)
        self.app.router.add_get('/health/live', self._liveness_endpoint)
        self.app.router.add_get('/metrics', self._metrics_endpoint)
    
    async def start(self):
        """Start the health check server"""
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        
        self.logger.info(f"Health check server started on port {self.port}")
    
    async def stop(self):
        """Stop the health check server"""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        
        self.logger.info("Health check server stopped")
    
    async def _health_endpoint(self, request):
        """Basic health check endpoint"""
        health = self.health_checker.get_system_health()
        
        status_code = 200
        if health.status == HealthStatus.DEGRADED:
            status_code = 200  # Still considered healthy for load balancers
        elif health.status == HealthStatus.UNHEALTHY:
            status_code = 503  # Service unavailable
        
        return web.json_response(
            {
                "status": health.status.value,
                "timestamp": health.timestamp.isoformat(),
                "uptime_seconds": health.uptime_seconds
            },
            status=status_code
        )
    
    async def _detailed_health_endpoint(self, request):
        """Detailed health check endpoint"""
        health = self.health_checker.get_system_health()
        
        # Convert to dict for JSON serialization
        health_dict = asdict(health)
        
        # Convert datetime objects to ISO strings
        health_dict['timestamp'] = health.timestamp.isoformat()
        for component in health_dict['components']:
            component['last_check'] = component['last_check'].isoformat()
            component['status'] = component['status'].value
        health_dict['status'] = health.status.value
        
        status_code = 200
        if health.status == HealthStatus.UNHEALTHY:
            status_code = 503
        
        return web.json_response(health_dict, status=status_code)
    
    async def _readiness_endpoint(self, request):
        """Kubernetes readiness probe endpoint"""
        health = self.health_checker.get_system_health()
        
        # Check if critical components are healthy
        critical_components = ['database', 'broker_api']
        ready = all(
            self.health_checker.components.get(comp, ComponentHealth("", HealthStatus.UNHEALTHY, "", datetime.now())).status != HealthStatus.UNHEALTHY
            for comp in critical_components
        )
        
        if ready:
            return web.json_response({"status": "ready"}, status=200)
        else:
            return web.json_response({"status": "not ready"}, status=503)
    
    async def _liveness_endpoint(self, request):
        """Kubernetes liveness probe endpoint"""
        # Simple liveness check - if we can respond, we're alive
        return web.json_response({"status": "alive"}, status=200)
    
    async def _metrics_endpoint(self, request):
        """Prometheus-style metrics endpoint"""
        health = self.health_checker.get_system_health()
        
        metrics = []
        
        # System uptime
        metrics.append(f"forex_bot_uptime_seconds {health.uptime_seconds}")
        
        # Component status (1 = healthy, 0.5 = degraded, 0 = unhealthy)
        for component in health.components:
            status_value = 1 if component.status == HealthStatus.HEALTHY else (0.5 if component.status == HealthStatus.DEGRADED else 0)
            metrics.append(f'forex_bot_component_health{{component="{component.name}"}} {status_value}')
            
            if component.response_time_ms:
                metrics.append(f'forex_bot_component_response_time_ms{{component="{component.name}"}} {component.response_time_ms}')
        
        # System metrics
        if health.system_metrics:
            for key, value in health.system_metrics.items():
                if isinstance(value, (int, float)):
                    metrics.append(f"forex_bot_system_{key} {value}")
        
        return web.Response(text="\n".join(metrics), content_type="text/plain")


# Global health checker instance
_health_checker: Optional[HealthChecker] = None
_health_server: Optional[HealthCheckServer] = None


async def start_health_system(port: int = 8080) -> tuple[HealthChecker, HealthCheckServer]:
    """Start the health check system"""
    global _health_checker, _health_server
    
    _health_checker = HealthChecker()
    _health_server = HealthCheckServer(_health_checker, port)
    
    await _health_checker.start()
    await _health_server.start()
    
    return _health_checker, _health_server


async def stop_health_system():
    """Stop the health check system"""
    global _health_checker, _health_server
    
    if _health_server:
        await _health_server.stop()
    if _health_checker:
        await _health_checker.stop()
    
    _health_checker = None
    _health_server = None


def get_health_checker() -> Optional[HealthChecker]:
    """Get the global health checker instance"""
    return _health_checker
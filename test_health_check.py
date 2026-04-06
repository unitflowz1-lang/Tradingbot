"""
Unit tests for health check system
"""

import asyncio
import json
import pytest
from unittest.mock import Mock, patch, AsyncMock
from datetime import datetime
import aiohttp
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from src.health_check import (
    HealthChecker, HealthCheckServer, HealthStatus, ComponentHealth, SystemHealth,
    start_health_system, stop_health_system, get_health_checker
)


class TestHealthChecker:
    """Test cases for HealthChecker class"""
    
    @pytest.fixture
    def health_checker(self):
        """Create a HealthChecker instance for testing"""
        return HealthChecker()
    
    @pytest.mark.asyncio
    async def test_health_checker_initialization(self, health_checker):
        """Test HealthChecker initialization"""
        assert health_checker.components == {}
        assert health_checker.check_interval == 30
        assert not health_checker.running
        assert health_checker._check_task is None
    
    @pytest.mark.asyncio
    async def test_start_stop_health_checker(self, health_checker):
        """Test starting and stopping health checker"""
        # Start health checker
        await health_checker.start()
        assert health_checker.running
        assert health_checker._check_task is not None
        
        # Stop health checker
        await health_checker.stop()
        assert not health_checker.running
    
    @pytest.mark.asyncio
    async def test_database_health_check(self, health_checker):
        """Test database health check"""
        await health_checker._check_database()
        
        assert "database" in health_checker.components
        component = health_checker.components["database"]
        assert component.name == "database"
        assert component.status == HealthStatus.HEALTHY
        assert component.response_time_ms is not None
        assert component.response_time_ms > 0
    
    @pytest.mark.asyncio
    async def test_broker_api_health_check(self, health_checker):
        """Test broker API health check"""
        await health_checker._check_broker_api()
        
        assert "broker_api" in health_checker.components
        component = health_checker.components["broker_api"]
        assert component.name == "broker_api"
        assert component.status == HealthStatus.HEALTHY
        assert component.response_time_ms is not None
    
    @pytest.mark.asyncio
    async def test_llm_api_health_check(self, health_checker):
        """Test LLM API health check"""
        await health_checker._check_llm_api()
        
        assert "llm_api" in health_checker.components
        component = health_checker.components["llm_api"]
        assert component.name == "llm_api"
        assert component.status == HealthStatus.HEALTHY
        assert component.response_time_ms is not None
    
    @pytest.mark.asyncio
    async def test_system_resources_health_check(self, health_checker):
        """Test system resources health check"""
        await health_checker._check_system_resources()
        
        assert "system_resources" in health_checker.components
        component = health_checker.components["system_resources"]
        assert component.name == "system_resources"
        assert component.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY]
        assert component.details is not None
        assert "cpu_percent" in component.details
        assert "memory_percent" in component.details
        assert "disk_percent" in component.details
    
    @pytest.mark.asyncio
    async def test_trading_engine_health_check(self, health_checker):
        """Test trading engine health check"""
        await health_checker._check_trading_engine()
        
        assert "trading_engine" in health_checker.components
        component = health_checker.components["trading_engine"]
        assert component.name == "trading_engine"
        assert component.status == HealthStatus.HEALTHY
        assert component.details is not None
    
    def test_get_system_health_empty(self, health_checker):
        """Test getting system health with no components"""
        health = health_checker.get_system_health()
        
        assert isinstance(health, SystemHealth)
        assert health.status == HealthStatus.UNHEALTHY
        assert len(health.components) == 0
        assert health.uptime_seconds >= 0
    
    @pytest.mark.asyncio
    async def test_get_system_health_with_components(self, health_checker):
        """Test getting system health with components"""
        # Add some components
        await health_checker._check_database()
        await health_checker._check_broker_api()
        
        health = health_checker.get_system_health()
        
        assert isinstance(health, SystemHealth)
        assert health.status == HealthStatus.HEALTHY
        assert len(health.components) == 2
        assert health.uptime_seconds >= 0
        assert health.system_metrics is not None
    
    def test_system_health_status_determination(self, health_checker):
        """Test system health status determination logic"""
        # Add healthy component
        health_checker.components["test1"] = ComponentHealth(
            name="test1",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=datetime.now()
        )
        
        health = health_checker.get_system_health()
        assert health.status == HealthStatus.HEALTHY
        
        # Add degraded component
        health_checker.components["test2"] = ComponentHealth(
            name="test2",
            status=HealthStatus.DEGRADED,
            message="Degraded",
            last_check=datetime.now()
        )
        
        health = health_checker.get_system_health()
        assert health.status == HealthStatus.DEGRADED
        
        # Add unhealthy component
        health_checker.components["test3"] = ComponentHealth(
            name="test3",
            status=HealthStatus.UNHEALTHY,
            message="Unhealthy",
            last_check=datetime.now()
        )
        
        health = health_checker.get_system_health()
        assert health.status == HealthStatus.UNHEALTHY


class TestHealthCheckServer(AioHTTPTestCase):
    """Test cases for HealthCheckServer class"""
    
    async def get_application(self):
        """Create test application"""
        self.health_checker = HealthChecker()
        self.health_server = HealthCheckServer(self.health_checker, port=8080)
        return self.health_server.app
    
    async def test_health_endpoint_healthy(self):
        """Test basic health endpoint with healthy status"""
        # Add healthy component
        self.health_checker.components["test"] = ComponentHealth(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=datetime.now()
        )
        
        resp = await self.client.request("GET", "/health")
        assert resp.status == 200
        
        data = await resp.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert "uptime_seconds" in data
    
    async def test_health_endpoint_unhealthy(self):
        """Test basic health endpoint with unhealthy status"""
        # Add unhealthy component
        self.health_checker.components["test"] = ComponentHealth(
            name="test",
            status=HealthStatus.UNHEALTHY,
            message="Failed",
            last_check=datetime.now()
        )
        
        resp = await self.client.request("GET", "/health")
        assert resp.status == 503
        
        data = await resp.json()
        assert data["status"] == "unhealthy"
    
    async def test_detailed_health_endpoint(self):
        """Test detailed health endpoint"""
        # Add test component
        self.health_checker.components["test"] = ComponentHealth(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=datetime.now(),
            response_time_ms=100.0,
            details={"key": "value"}
        )
        
        resp = await self.client.request("GET", "/health/detailed")
        assert resp.status == 200
        
        data = await resp.json()
        assert data["status"] == "healthy"
        assert "components" in data
        assert len(data["components"]) == 1
        assert data["components"][0]["name"] == "test"
        assert data["components"][0]["response_time_ms"] == 100.0
    
    async def test_readiness_endpoint(self):
        """Test readiness probe endpoint"""
        # Add critical components
        self.health_checker.components["database"] = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=datetime.now()
        )
        self.health_checker.components["broker_api"] = ComponentHealth(
            name="broker_api",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=datetime.now()
        )
        
        resp = await self.client.request("GET", "/health/ready")
        assert resp.status == 200
        
        data = await resp.json()
        assert data["status"] == "ready"
    
    async def test_readiness_endpoint_not_ready(self):
        """Test readiness probe endpoint when not ready"""
        # Add unhealthy critical component
        self.health_checker.components["database"] = ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message="Failed",
            last_check=datetime.now()
        )
        
        resp = await self.client.request("GET", "/health/ready")
        assert resp.status == 503
        
        data = await resp.json()
        assert data["status"] == "not ready"
    
    async def test_liveness_endpoint(self):
        """Test liveness probe endpoint"""
        resp = await self.client.request("GET", "/health/live")
        assert resp.status == 200
        
        data = await resp.json()
        assert data["status"] == "alive"
    
    async def test_metrics_endpoint(self):
        """Test metrics endpoint"""
        # Add test component
        self.health_checker.components["test"] = ComponentHealth(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=datetime.now(),
            response_time_ms=150.0
        )
        
        resp = await self.client.request("GET", "/metrics")
        assert resp.status == 200
        assert resp.content_type == "text/plain"
        
        text = await resp.text()
        assert "forex_bot_uptime_seconds" in text
        assert "forex_bot_component_health" in text
        assert "forex_bot_component_response_time_ms" in text


class TestHealthSystemIntegration:
    """Integration tests for health system"""
    
    @pytest.mark.asyncio
    async def test_start_stop_health_system(self):
        """Test starting and stopping the complete health system"""
        # Start health system with a different port to avoid conflicts
        health_checker, health_server = await start_health_system(port=8082)
        
        assert health_checker is not None
        assert health_server is not None
        assert health_checker.running
        
        # Test that we can get the global instance
        global_checker = get_health_checker()
        assert global_checker is health_checker
        
        # Stop health system
        await stop_health_system()
        
        assert not health_checker.running
        assert get_health_checker() is None
    
    @pytest.mark.asyncio
    async def test_health_system_with_real_server(self):
        """Test health system with real HTTP server"""
        # Start health system
        health_checker, health_server = await start_health_system(port=8082)
        
        try:
            # Wait a moment for server to start
            await asyncio.sleep(0.1)
            
            # Test health endpoint
            async with aiohttp.ClientSession() as session:
                async with session.get("http://localhost:8082/health") as resp:
                    assert resp.status in [200, 503]  # Could be unhealthy initially
                    data = await resp.json()
                    assert "status" in data
                    assert "timestamp" in data
        
        finally:
            await stop_health_system()


class TestComponentHealth:
    """Test cases for ComponentHealth dataclass"""
    
    def test_component_health_creation(self):
        """Test ComponentHealth creation"""
        now = datetime.now()
        component = ComponentHealth(
            name="test",
            status=HealthStatus.HEALTHY,
            message="OK",
            last_check=now,
            response_time_ms=100.0,
            details={"key": "value"}
        )
        
        assert component.name == "test"
        assert component.status == HealthStatus.HEALTHY
        assert component.message == "OK"
        assert component.last_check == now
        assert component.response_time_ms == 100.0
        assert component.details == {"key": "value"}


class TestSystemHealth:
    """Test cases for SystemHealth dataclass"""
    
    def test_system_health_creation(self):
        """Test SystemHealth creation"""
        now = datetime.now()
        components = [
            ComponentHealth(
                name="test",
                status=HealthStatus.HEALTHY,
                message="OK",
                last_check=now
            )
        ]
        
        system_health = SystemHealth(
            status=HealthStatus.HEALTHY,
            timestamp=now,
            uptime_seconds=100.0,
            components=components,
            system_metrics={"cpu": 50.0}
        )
        
        assert system_health.status == HealthStatus.HEALTHY
        assert system_health.timestamp == now
        assert system_health.uptime_seconds == 100.0
        assert len(system_health.components) == 1
        assert system_health.system_metrics == {"cpu": 50.0}


if __name__ == "__main__":
    pytest.main([__file__])
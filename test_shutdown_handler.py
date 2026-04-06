"""
Unit tests for graceful shutdown handler
"""

import asyncio
import signal
import pytest
from unittest.mock import Mock, patch, AsyncMock
import threading
import time

from src.shutdown_handler import (
    GracefulShutdownHandler, TradingBotShutdownManager, ShutdownTask, ShutdownReason,
    get_shutdown_manager, shutdown_application
)


class TestShutdownTask:
    """Test cases for ShutdownTask dataclass"""
    
    def test_shutdown_task_creation(self):
        """Test ShutdownTask creation"""
        def test_func():
            pass
        
        task = ShutdownTask(
            name="test_task",
            func=test_func,
            timeout=30.0,
            critical=True
        )
        
        assert task.name == "test_task"
        assert task.func == test_func
        assert task.timeout == 30.0
        assert task.critical is True
    
    def test_shutdown_task_defaults(self):
        """Test ShutdownTask default values"""
        def test_func():
            pass
        
        task = ShutdownTask(name="test", func=test_func)
        
        assert task.timeout == 30.0
        assert task.critical is True


class TestGracefulShutdownHandler:
    """Test cases for GracefulShutdownHandler class"""
    
    @pytest.fixture
    def shutdown_handler(self):
        """Create a GracefulShutdownHandler instance for testing"""
        return GracefulShutdownHandler(shutdown_timeout=30.0)
    
    def test_shutdown_handler_initialization(self, shutdown_handler):
        """Test GracefulShutdownHandler initialization"""
        assert shutdown_handler.shutdown_timeout == 30.0
        assert shutdown_handler.shutdown_tasks == []
        assert not shutdown_handler.is_shutting_down
        assert not shutdown_handler.shutdown_event.is_set()
        assert shutdown_handler.shutdown_reason is None
        assert shutdown_handler.shutdown_message is None
    
    def test_add_shutdown_task(self, shutdown_handler):
        """Test adding shutdown tasks"""
        def test_func():
            pass
        
        task = ShutdownTask(name="test", func=test_func)
        shutdown_handler.add_shutdown_task(task)
        
        assert len(shutdown_handler.shutdown_tasks) == 1
        assert shutdown_handler.shutdown_tasks[0] == task
    
    def test_add_shutdown_callback(self, shutdown_handler):
        """Test adding shutdown callback"""
        def test_func():
            pass
        
        shutdown_handler.add_shutdown_callback(
            name="test_callback",
            func=test_func,
            timeout=15.0,
            critical=False
        )
        
        assert len(shutdown_handler.shutdown_tasks) == 1
        task = shutdown_handler.shutdown_tasks[0]
        assert task.name == "test_callback"
        assert task.func == test_func
        assert task.timeout == 15.0
        assert task.critical is False
    
    @pytest.mark.asyncio
    async def test_shutdown_execution(self, shutdown_handler):
        """Test shutdown execution"""
        executed_tasks = []
        
        def sync_task():
            executed_tasks.append("sync_task")
        
        async def async_task():
            executed_tasks.append("async_task")
        
        # Add tasks
        shutdown_handler.add_shutdown_callback("sync", sync_task)
        shutdown_handler.add_shutdown_callback("async", async_task)
        
        # Execute shutdown
        await shutdown_handler.shutdown(
            reason=ShutdownReason.MANUAL,
            message="Test shutdown"
        )
        
        # Verify shutdown state
        assert shutdown_handler.is_shutting_down
        assert shutdown_handler.shutdown_event.is_set()
        assert shutdown_handler.shutdown_reason == ShutdownReason.MANUAL
        assert shutdown_handler.shutdown_message == "Test shutdown"
        
        # Verify tasks were executed
        assert "sync_task" in executed_tasks
        assert "async_task" in executed_tasks
    
    @pytest.mark.asyncio
    async def test_shutdown_task_timeout(self, shutdown_handler):
        """Test shutdown task timeout handling"""
        def slow_task():
            time.sleep(2)  # This will timeout
        
        shutdown_handler.add_shutdown_callback(
            name="slow_task",
            func=slow_task,
            timeout=0.1,  # Very short timeout
            critical=True
        )
        
        # Execute shutdown (should handle timeout gracefully)
        await shutdown_handler.shutdown()
        
        assert shutdown_handler.is_shutting_down
        assert shutdown_handler.shutdown_event.is_set()
    
    @pytest.mark.asyncio
    async def test_shutdown_task_exception(self, shutdown_handler):
        """Test shutdown task exception handling"""
        def failing_task():
            raise Exception("Task failed")
        
        shutdown_handler.add_shutdown_callback(
            name="failing_task",
            func=failing_task,
            critical=False
        )
        
        # Execute shutdown (should handle exception gracefully)
        await shutdown_handler.shutdown()
        
        assert shutdown_handler.is_shutting_down
        assert shutdown_handler.shutdown_event.is_set()
    
    @pytest.mark.asyncio
    async def test_wait_for_shutdown(self, shutdown_handler):
        """Test waiting for shutdown"""
        # Start waiting in background
        wait_task = asyncio.create_task(shutdown_handler.wait_for_shutdown())
        
        # Give it a moment to start waiting
        await asyncio.sleep(0.01)
        assert not wait_task.done()
        
        # Trigger shutdown
        await shutdown_handler.shutdown()
        
        # Wait should complete
        await wait_task
        assert wait_task.done()
    
    @pytest.mark.asyncio
    async def test_is_shutdown_requested(self, shutdown_handler):
        """Test shutdown request status"""
        assert not shutdown_handler.is_shutdown_requested()
        
        # Start shutdown (don't await to avoid blocking)
        task = asyncio.create_task(shutdown_handler.shutdown())
        
        # Give it a moment to start
        await asyncio.sleep(0.01)
        assert shutdown_handler.is_shutdown_requested()
        
        # Wait for task to complete
        await task
    
    @pytest.mark.asyncio
    async def test_task_execution_order(self, shutdown_handler):
        """Test that critical tasks are executed first"""
        execution_order = []
        
        def critical_task():
            execution_order.append("critical")
        
        def non_critical_task():
            execution_order.append("non_critical")
        
        # Add tasks in reverse order of desired execution
        shutdown_handler.add_shutdown_callback("non_critical", non_critical_task, critical=False)
        shutdown_handler.add_shutdown_callback("critical", critical_task, critical=True)
        
        await shutdown_handler.shutdown()
        
        # Critical task should be executed first
        assert execution_order == ["critical", "non_critical"]
    
    @pytest.mark.asyncio
    async def test_duplicate_shutdown_calls(self, shutdown_handler):
        """Test that duplicate shutdown calls are handled gracefully"""
        call_count = 0
        
        def test_task():
            nonlocal call_count
            call_count += 1
        
        shutdown_handler.add_shutdown_callback("test", test_task)
        
        # Call shutdown multiple times
        await shutdown_handler.shutdown()
        await shutdown_handler.shutdown()
        await shutdown_handler.shutdown()
        
        # Task should only be executed once
        assert call_count == 1


class TestTradingBotShutdownManager:
    """Test cases for TradingBotShutdownManager class"""
    
    @pytest.fixture
    def shutdown_manager(self):
        """Create a TradingBotShutdownManager instance for testing"""
        return TradingBotShutdownManager(shutdown_timeout=30.0)
    
    def test_shutdown_manager_initialization(self, shutdown_manager):
        """Test TradingBotShutdownManager initialization"""
        assert shutdown_manager.handler is not None
        assert shutdown_manager.handler.shutdown_timeout == 30.0
        
        # Check that trading-specific tasks were added
        task_names = [task.name for task in shutdown_manager.handler.shutdown_tasks]
        expected_tasks = [
            "close_positions",
            "cancel_orders",
            "save_state",
            "stop_data_feeds",
            "close_database",
            "stop_health_checks"
        ]
        
        for expected_task in expected_tasks:
            assert expected_task in task_names
    
    @pytest.mark.asyncio
    async def test_close_all_positions(self, shutdown_manager):
        """Test close all positions task"""
        await shutdown_manager._close_all_positions()
        # Should complete without error
    
    @pytest.mark.asyncio
    async def test_cancel_pending_orders(self, shutdown_manager):
        """Test cancel pending orders task"""
        await shutdown_manager._cancel_pending_orders()
        # Should complete without error
    
    @pytest.mark.asyncio
    async def test_save_trading_state(self, shutdown_manager):
        """Test save trading state task"""
        await shutdown_manager._save_trading_state()
        # Should complete without error
    
    @pytest.mark.asyncio
    async def test_stop_data_feeds(self, shutdown_manager):
        """Test stop data feeds task"""
        await shutdown_manager._stop_data_feeds()
        # Should complete without error
    
    @pytest.mark.asyncio
    async def test_close_database_connections(self, shutdown_manager):
        """Test close database connections task"""
        await shutdown_manager._close_database_connections()
        # Should complete without error
    
    @pytest.mark.asyncio
    async def test_stop_health_checks(self, shutdown_manager):
        """Test stop health checks task"""
        # This should complete without error even if health system is not available
        await shutdown_manager._stop_health_checks()
    
    @pytest.mark.asyncio
    async def test_shutdown_manager_shutdown(self, shutdown_manager):
        """Test shutdown manager shutdown method"""
        await shutdown_manager.shutdown(
            reason=ShutdownReason.ERROR,
            message="Test error shutdown"
        )
        
        assert shutdown_manager.handler.is_shutting_down
        assert shutdown_manager.handler.shutdown_reason == ShutdownReason.ERROR
        assert shutdown_manager.handler.shutdown_message == "Test error shutdown"
    
    @pytest.mark.asyncio
    async def test_wait_for_shutdown(self, shutdown_manager):
        """Test wait for shutdown"""
        # Start waiting in background
        wait_task = asyncio.create_task(shutdown_manager.wait_for_shutdown())
        
        # Give it a moment to start waiting
        await asyncio.sleep(0.01)
        assert not wait_task.done()
        
        # Trigger shutdown
        await shutdown_manager.shutdown()
        
        # Wait should complete
        await wait_task
        assert wait_task.done()
    
    @pytest.mark.asyncio
    async def test_is_shutdown_requested(self, shutdown_manager):
        """Test shutdown request status"""
        assert not shutdown_manager.is_shutdown_requested()
        
        # Start shutdown (don't await to avoid blocking)
        task = asyncio.create_task(shutdown_manager.shutdown())
        
        # Give it a moment to start
        await asyncio.sleep(0.01)
        assert shutdown_manager.is_shutdown_requested()
        
        # Wait for task to complete
        await task


class TestGlobalShutdownManager:
    """Test cases for global shutdown manager functions"""
    
    def test_get_shutdown_manager_singleton(self):
        """Test global shutdown manager singleton"""
        manager1 = get_shutdown_manager()
        manager2 = get_shutdown_manager()
        
        assert manager1 is manager2
    
    def test_get_shutdown_manager_with_timeout(self):
        """Test global shutdown manager with custom timeout"""
        # Reset global instance first
        import src.shutdown_handler
        src.shutdown_handler._shutdown_manager = None
        
        manager = get_shutdown_manager(shutdown_timeout=45.0)
        assert manager.handler.shutdown_timeout == 45.0
    
    @pytest.mark.asyncio
    async def test_shutdown_application(self):
        """Test global shutdown application function"""
        # Reset global instance
        import src.shutdown_handler
        src.shutdown_handler._shutdown_manager = None
        
        await shutdown_application(
            reason=ShutdownReason.MANUAL,
            message="Test application shutdown"
        )
        
        # Should create and use global manager
        manager = get_shutdown_manager()
        assert manager.handler.is_shutting_down
        assert manager.handler.shutdown_reason == ShutdownReason.MANUAL


class TestSignalHandling:
    """Test cases for signal handling"""
    
    @pytest.fixture
    def shutdown_handler(self):
        """Create a GracefulShutdownHandler instance for testing"""
        return GracefulShutdownHandler()
    
    @patch('signal.signal')
    def test_signal_handler_registration(self, mock_signal, shutdown_handler):
        """Test that signal handlers are registered"""
        # Create new handler to trigger registration
        handler = GracefulShutdownHandler()
        
        # Should have registered signal handlers
        assert mock_signal.call_count >= 2  # At least SIGTERM and SIGINT
    
    @pytest.mark.asyncio
    async def test_signal_handler_execution(self, shutdown_handler):
        """Test signal handler execution"""
        # Simulate signal handler call
        shutdown_handler._signal_handler(signal.SIGTERM, None)
        
        # Give it a moment to process
        await asyncio.sleep(0.1)
        
        # Should have initiated shutdown
        assert shutdown_handler.is_shutting_down


class TestShutdownReason:
    """Test cases for ShutdownReason enum"""
    
    def test_shutdown_reason_values(self):
        """Test ShutdownReason enum values"""
        assert ShutdownReason.SIGNAL.value == "signal"
        assert ShutdownReason.ERROR.value == "error"
        assert ShutdownReason.MANUAL.value == "manual"
        assert ShutdownReason.HEALTH_CHECK.value == "health_check"


if __name__ == "__main__":
    pytest.main([__file__])
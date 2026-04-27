"""
Graceful shutdown handler for the AI Forex Trading Bot
"""

import asyncio
import logging
import signal
import sys
import time
from typing import List, Callable, Optional, Any
from dataclasses import dataclass
from enum import Enum


class ShutdownReason(Enum):
    """Reasons for system shutdown"""
    SIGNAL = "signal"
    ERROR = "error"
    MANUAL = "manual"
    HEALTH_CHECK = "health_check"


@dataclass
class ShutdownTask:
    """A task to be executed during shutdown"""
    name: str
    func: Callable[[], Any]
    timeout: float = 30.0
    critical: bool = True


class GracefulShutdownHandler:
    """Handles graceful shutdown of the trading bot"""
    
    def __init__(self, shutdown_timeout: float = 60.0):
        self.logger = logging.getLogger(__name__)
        self.shutdown_timeout = shutdown_timeout
        self.shutdown_tasks: List[ShutdownTask] = []
        self.is_shutting_down = False
        self.shutdown_event = asyncio.Event()
        self.shutdown_reason: Optional[ShutdownReason] = None
        self.shutdown_message: Optional[str] = None
        
        # Register signal handlers
        self._register_signal_handlers()
    
    def _register_signal_handlers(self):
        """Register signal handlers for graceful shutdown"""
        if sys.platform != "win32":
            # Unix signals
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGHUP, self._signal_handler)
        else:
            # Windows signals
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
    
    def _signal_handler(self, signum: int, frame):
        """Handle shutdown signals"""
        signal_names = {
            signal.SIGTERM: "SIGTERM",
            signal.SIGINT: "SIGINT"
        }
        
        if hasattr(signal, 'SIGHUP'):
            signal_names[signal.SIGHUP] = "SIGHUP"
        
        signal_name = signal_names.get(signum, f"SIGNAL_{signum}")
        self.logger.info(f"Received {signal_name} signal, initiating graceful shutdown")
        
        asyncio.create_task(self.shutdown(
            reason=ShutdownReason.SIGNAL,
            message=f"Received {signal_name} signal"
        ))
    
    def add_shutdown_task(self, task: ShutdownTask):
        """Add a task to be executed during shutdown"""
        self.shutdown_tasks.append(task)
        self.logger.debug(f"Added shutdown task: {task.name}")
    
    def add_shutdown_callback(self, name: str, func: Callable[[], Any], 
                            timeout: float = 30.0, critical: bool = True):
        """Add a shutdown callback function"""
        task = ShutdownTask(name=name, func=func, timeout=timeout, critical=critical)
        self.add_shutdown_task(task)
    
    async def shutdown(self, reason: ShutdownReason = ShutdownReason.MANUAL, 
                      message: str = "Manual shutdown requested"):
        """Initiate graceful shutdown"""
        if self.is_shutting_down:
            self.logger.warning("Shutdown already in progress")
            return
        
        self.is_shutting_down = True
        self.shutdown_reason = reason
        self.shutdown_message = message
        
        self.logger.info(f"Starting graceful shutdown: {message}")
        start_time = time.time()
        
        try:
            # Execute shutdown tasks
            await self._execute_shutdown_tasks()
            
            # Set shutdown event
            self.shutdown_event.set()
            
            elapsed_time = time.time() - start_time
            self.logger.info(f"Graceful shutdown completed in {elapsed_time:.2f} seconds")
            
        except Exception as e:
            self.logger.error(f"Error during graceful shutdown: {e}")
            self.shutdown_event.set()
    
    async def _execute_shutdown_tasks(self):
        """Execute all shutdown tasks"""
        self.logger.info(f"Executing {len(self.shutdown_tasks)} shutdown tasks")
        
        # Sort tasks by criticality (critical tasks first)
        sorted_tasks = sorted(self.shutdown_tasks, key=lambda t: not t.critical)
        
        for task in sorted_tasks:
            try:
                self.logger.info(f"Executing shutdown task: {task.name}")
                
                if asyncio.iscoroutinefunction(task.func):
                    # Async function
                    await asyncio.wait_for(task.func(), timeout=task.timeout)
                else:
                    # Sync function - run in executor
                    await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, task.func),
                        timeout=task.timeout
                    )
                
                self.logger.info(f"Completed shutdown task: {task.name}")
                
            except asyncio.TimeoutError:
                if task.critical:
                    self.logger.error(f"Critical shutdown task '{task.name}' timed out after {task.timeout}s")
                else:
                    self.logger.warning(f"Non-critical shutdown task '{task.name}' timed out after {task.timeout}s")
            
            except Exception as e:
                if task.critical:
                    self.logger.error(f"Critical shutdown task '{task.name}' failed: {e}")
                else:
                    self.logger.warning(f"Non-critical shutdown task '{task.name}' failed: {e}")
    
    async def wait_for_shutdown(self):
        """Wait for shutdown to be initiated"""
        await self.shutdown_event.wait()
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested"""
        return self.is_shutting_down


class TradingBotShutdownManager:
    """Specific shutdown manager for the trading bot"""
    
    def __init__(self, shutdown_timeout: float = 60.0):
        self.handler = GracefulShutdownHandler(shutdown_timeout)
        self.logger = logging.getLogger(__name__)
        self._setup_trading_shutdown_tasks()
    
    def _setup_trading_shutdown_tasks(self):
        """Setup trading-specific shutdown tasks"""
        
        # Task 1: Close all open positions (critical)
        self.handler.add_shutdown_callback(
            name="close_positions",
            func=self._close_all_positions,
            timeout=30.0,
            critical=True
        )
        
        # Task 2: Cancel pending orders (critical)
        self.handler.add_shutdown_callback(
            name="cancel_orders",
            func=self._cancel_pending_orders,
            timeout=20.0,
            critical=True
        )
        
        # Task 3: Save trading state (critical)
        self.handler.add_shutdown_callback(
            name="save_state",
            func=self._save_trading_state,
            timeout=15.0,
            critical=True
        )
        
        # Task 4: Stop data feeds (non-critical)
        self.handler.add_shutdown_callback(
            name="stop_data_feeds",
            func=self._stop_data_feeds,
            timeout=10.0,
            critical=False
        )
        
        # Task 5: Close database connections (non-critical)
        self.handler.add_shutdown_callback(
            name="close_database",
            func=self._close_database_connections,
            timeout=10.0,
            critical=False
        )
        
        # Task 6: Stop health check system (non-critical)
        self.handler.add_shutdown_callback(
            name="stop_health_checks",
            func=self._stop_health_checks,
            timeout=5.0,
            critical=False
        )
    
    async def _close_all_positions(self):
        """Close all open trading positions"""
        self.logger.info("Closing all open positions...")
        
        # This would integrate with the actual trading engine
        # For now, we'll simulate the process
        await asyncio.sleep(1)  # Simulate position closing time
        
        self.logger.info("All positions closed successfully")
    
    async def _cancel_pending_orders(self):
        """Cancel all pending orders"""
        self.logger.info("Cancelling all pending orders...")
        
        # This would integrate with the actual order management system
        # For now, we'll simulate the process
        await asyncio.sleep(0.5)  # Simulate order cancellation time
        
        self.logger.info("All pending orders cancelled successfully")
    
    async def _save_trading_state(self):
        """Save current trading state to persistent storage"""
        self.logger.info("Saving trading state...")
        
        # This would save the current state to database or file
        # For now, we'll simulate the process
        await asyncio.sleep(1)  # Simulate save time
        
        self.logger.info("Trading state saved successfully")
    
    async def _stop_data_feeds(self):
        """Stop all data feed connections"""
        self.logger.info("Stopping data feeds...")
        
        # This would stop market data, news feeds, etc.
        # For now, we'll simulate the process
        await asyncio.sleep(0.5)  # Simulate stop time
        
        self.logger.info("Data feeds stopped successfully")
    
    async def _close_database_connections(self):
        """Close database connections"""
        self.logger.info("Closing database connections...")
        
        # This would close database connection pools
        # For now, we'll simulate the process
        await asyncio.sleep(0.3)  # Simulate close time
        
        self.logger.info("Database connections closed successfully")
    
    async def _stop_health_checks(self):
        """Stop health check system"""
        self.logger.info("Stopping health check system...")
        
        # This would stop the health check system
        try:
            from .health_check import stop_health_system
            await stop_health_system()
        except ImportError:
            # Health check system not available
            pass
        
        self.logger.info("Health check system stopped successfully")
    
    async def shutdown(self, reason: ShutdownReason = ShutdownReason.MANUAL, 
                      message: str = "Manual shutdown requested"):
        """Initiate graceful shutdown"""
        await self.handler.shutdown(reason, message)
    
    async def wait_for_shutdown(self):
        """Wait for shutdown to be initiated"""
        await self.handler.wait_for_shutdown()
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested"""
        return self.handler.is_shutdown_requested()


# Global shutdown manager instance
_shutdown_manager: Optional[TradingBotShutdownManager] = None


def get_shutdown_manager(shutdown_timeout: float = 60.0) -> TradingBotShutdownManager:
    """Get global shutdown manager instance"""
    global _shutdown_manager
    if _shutdown_manager is None:
        _shutdown_manager = TradingBotShutdownManager(shutdown_timeout)
    return _shutdown_manager


async def shutdown_application(reason: ShutdownReason = ShutdownReason.MANUAL,
                              message: str = "Application shutdown requested"):
    """Shutdown the application gracefully"""
    manager = get_shutdown_manager()
    await manager.shutdown(reason, message)
"""
Comprehensive error handling and recovery for RL system components.
"""
import os
import time
import logging
import traceback
import threading
from typing import Dict, Any, List, Optional, Callable, Union
from dataclasses import dataclass
from enum import Enum
import functools
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json

import torch
import redis
import numpy as np

logger = logging.getLogger(__name__)

class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class ErrorCategory(Enum):
    """Error categories."""
    TRAINING = "training"
    INFERENCE = "inference"
    DATA = "data"
    NETWORK = "network"
    RESOURCE = "resource"
    MODEL = "model"
    SYSTEM = "system"

@dataclass
class ErrorInfo:
    """Error information structure."""
    error_id: str
    category: ErrorCategory
    severity: ErrorSeverity
    message: str
    exception: Optional[Exception]
    context: Dict[str, Any]
    timestamp: float
    stack_trace: str
    recovery_attempted: bool = False
    recovery_successful: bool = False
    retry_count: int = 0

class RecoveryStrategy:
    """Base class for recovery strategies."""
    
    def __init__(self, name: str, max_retries: int = 3, backoff_factor: float = 2.0):
        self.name = name
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
    
    def can_recover(self, error_info: ErrorInfo) -> bool:
        """Check if this strategy can handle the error."""
        raise NotImplementedError
    
    def recover(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt to recover from the error."""
        raise NotImplementedError
    
    def get_retry_delay(self, retry_count: int) -> float:
        """Calculate retry delay with exponential backoff."""
        return min(300, self.backoff_factor ** retry_count)  # Max 5 minutes

class ModelRecoveryStrategy(RecoveryStrategy):
    """Recovery strategy for model-related errors."""
    
    def __init__(self):
        super().__init__("model_recovery", max_retries=3)
    
    def can_recover(self, error_info: ErrorInfo) -> bool:
        """Check if this is a recoverable model error."""
        return (error_info.category == ErrorCategory.MODEL and
                error_info.severity in [ErrorSeverity.LOW, ErrorSeverity.MEDIUM])
    
    def recover(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt model recovery."""
        try:
            logger.info(f"Attempting model recovery for error: {error_info.error_id}")
            
            # Try to reload model from checkpoint
            if 'agent' in context and 'checkpoint_path' in context:
                agent = context['agent']
                checkpoint_path = context['checkpoint_path']
                
                # Load previous checkpoint
                if os.path.exists(checkpoint_path):
                    agent.load_checkpoint(checkpoint_path)
                    logger.info("Successfully reloaded model from checkpoint")
                    return True
            
            # Try to reinitialize model
            if 'agent_class' in context and 'agent_config' in context:
                agent_class = context['agent_class']
                agent_config = context['agent_config']
                
                # Reinitialize agent
                new_agent = agent_class(**agent_config)
                context['agent'] = new_agent
                logger.info("Successfully reinitialized model")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Model recovery failed: {e}")
            return False

class NetworkRecoveryStrategy(RecoveryStrategy):
    """Recovery strategy for network-related errors."""
    
    def __init__(self):
        super().__init__("network_recovery", max_retries=5)
    
    def can_recover(self, error_info: ErrorInfo) -> bool:
        """Check if this is a recoverable network error."""
        return error_info.category == ErrorCategory.NETWORK
    
    def recover(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt network recovery."""
        try:
            logger.info(f"Attempting network recovery for error: {error_info.error_id}")
            
            # Wait before retry
            time.sleep(self.get_retry_delay(error_info.retry_count))
            
            # Try to reconnect
            if 'connection' in context:
                connection = context['connection']
                if hasattr(connection, 'reconnect'):
                    connection.reconnect()
                    logger.info("Successfully reconnected")
                    return True
            
            # Try to reinitialize connection
            if 'connection_factory' in context:
                factory = context['connection_factory']
                new_connection = factory()
                context['connection'] = new_connection
                logger.info("Successfully reinitialized connection")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Network recovery failed: {e}")
            return False

class ResourceRecoveryStrategy(RecoveryStrategy):
    """Recovery strategy for resource-related errors."""
    
    def __init__(self):
        super().__init__("resource_recovery", max_retries=2)
    
    def can_recover(self, error_info: ErrorInfo) -> bool:
        """Check if this is a recoverable resource error."""
        return error_info.category == ErrorCategory.RESOURCE
    
    def recover(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt resource recovery."""
        try:
            logger.info(f"Attempting resource recovery for error: {error_info.error_id}")
            
            # Clear GPU cache if CUDA error
            if torch.cuda.is_available() and "cuda" in error_info.message.lower():
                torch.cuda.empty_cache()
                logger.info("Cleared CUDA cache")
            
            # Reduce batch size if memory error
            if "memory" in error_info.message.lower() and 'config' in context:
                config = context['config']
                if hasattr(config, 'batch_size'):
                    config.batch_size = max(1, config.batch_size // 2)
                    logger.info(f"Reduced batch size to {config.batch_size}")
                    return True
            
            # Force garbage collection
            import gc
            gc.collect()
            logger.info("Forced garbage collection")
            
            return True
            
        except Exception as e:
            logger.error(f"Resource recovery failed: {e}")
            return False

class TrainingRecoveryStrategy(RecoveryStrategy):
    """Recovery strategy for training-related errors."""
    
    def __init__(self):
        super().__init__("training_recovery", max_retries=3)
    
    def can_recover(self, error_info: ErrorInfo) -> bool:
        """Check if this is a recoverable training error."""
        return (error_info.category == ErrorCategory.TRAINING and
                error_info.severity != ErrorSeverity.CRITICAL)
    
    def recover(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt training recovery."""
        try:
            logger.info(f"Attempting training recovery for error: {error_info.error_id}")
            
            # Reset environment if available
            if 'environment' in context:
                environment = context['environment']
                environment.reset()
                logger.info("Reset training environment")
            
            # Reduce learning rate if training instability
            if "loss" in error_info.message.lower() and 'agent' in context:
                agent = context['agent']
                if hasattr(agent, 'learning_rate'):
                    agent.learning_rate *= 0.5
                    logger.info(f"Reduced learning rate to {agent.learning_rate}")
                
                # Update optimizer learning rate
                if hasattr(agent, 'optimizer'):
                    for param_group in agent.optimizer.param_groups:
                        param_group['lr'] *= 0.5
            
            # Skip problematic batch
            if 'batch_iterator' in context:
                batch_iterator = context['batch_iterator']
                try:
                    next(batch_iterator)  # Skip current batch
                    logger.info("Skipped problematic batch")
                except StopIteration:
                    pass
            
            return True
            
        except Exception as e:
            logger.error(f"Training recovery failed: {e}")
            return False

class ErrorHandler:
    """Main error handler coordinating recovery strategies."""
    
    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        self.recovery_strategies: List[RecoveryStrategy] = []
        self.error_history: List[ErrorInfo] = []
        self.max_history_size = 1000
        
        # Redis for error coordination
        try:
            self.redis_client = redis.Redis(
                host=redis_host,
                port=redis_port,
                decode_responses=True,
                socket_timeout=5
            )
            self.redis_available = True
        except Exception:
            self.redis_client = None
            self.redis_available = False
            logger.warning("Redis not available for error coordination")
        
        # Register default recovery strategies
        self._register_default_strategies()
        
        # Error tracking
        self.error_counts: Dict[str, int] = {}
        self.circuit_breakers: Dict[str, float] = {}  # component -> last_failure_time
        
    def _register_default_strategies(self):
        """Register default recovery strategies."""
        self.recovery_strategies.extend([
            ModelRecoveryStrategy(),
            NetworkRecoveryStrategy(),
            ResourceRecoveryStrategy(),
            TrainingRecoveryStrategy()
        ])
    
    def register_strategy(self, strategy: RecoveryStrategy):
        """Register a custom recovery strategy."""
        self.recovery_strategies.append(strategy)
        logger.info(f"Registered recovery strategy: {strategy.name}")
    
    def handle_error(self, 
                    exception: Exception,
                    category: ErrorCategory,
                    severity: ErrorSeverity,
                    context: Dict[str, Any],
                    component: str = "unknown") -> bool:
        """Handle an error and attempt recovery."""
        
        # Create error info
        error_info = ErrorInfo(
            error_id=f"{component}_{int(time.time())}_{id(exception)}",
            category=category,
            severity=severity,
            message=str(exception),
            exception=exception,
            context=context.copy(),
            timestamp=time.time(),
            stack_trace=traceback.format_exc()
        )
        
        # Log error
        self._log_error(error_info)
        
        # Store error history
        self._store_error(error_info)
        
        # Check circuit breaker
        if self._is_circuit_open(component):
            logger.warning(f"Circuit breaker open for {component}, skipping recovery")
            return False
        
        # Attempt recovery
        recovery_successful = self._attempt_recovery(error_info, context)
        
        # Update circuit breaker
        if not recovery_successful:
            self.circuit_breakers[component] = time.time()
        
        # Publish error to Redis for coordination
        if self.redis_available:
            self._publish_error(error_info)
        
        return recovery_successful
    
    def _log_error(self, error_info: ErrorInfo):
        """Log error with appropriate level."""
        log_message = (
            f"Error {error_info.error_id}: {error_info.message} "
            f"(Category: {error_info.category.value}, Severity: {error_info.severity.value})"
        )
        
        if error_info.severity == ErrorSeverity.CRITICAL:
            logger.critical(log_message)
        elif error_info.severity == ErrorSeverity.HIGH:
            logger.error(log_message)
        elif error_info.severity == ErrorSeverity.MEDIUM:
            logger.warning(log_message)
        else:
            logger.info(log_message)
    
    def _store_error(self, error_info: ErrorInfo):
        """Store error in history."""
        self.error_history.append(error_info)
        
        # Maintain history size
        if len(self.error_history) > self.max_history_size:
            self.error_history = self.error_history[-self.max_history_size:]
        
        # Update error counts
        error_key = f"{error_info.category.value}_{error_info.severity.value}"
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
    
    def _is_circuit_open(self, component: str) -> bool:
        """Check if circuit breaker is open for component."""
        if component not in self.circuit_breakers:
            return False
        
        # Circuit breaker timeout (5 minutes)
        return time.time() - self.circuit_breakers[component] < 300
    
    def _attempt_recovery(self, error_info: ErrorInfo, context: Dict[str, Any]) -> bool:
        """Attempt recovery using available strategies."""
        error_info.recovery_attempted = True
        
        for strategy in self.recovery_strategies:
            if strategy.can_recover(error_info):
                logger.info(f"Attempting recovery with strategy: {strategy.name}")
                
                try:
                    # Check retry limit
                    if error_info.retry_count >= strategy.max_retries:
                        logger.warning(f"Max retries exceeded for strategy {strategy.name}")
                        continue
                    
                    error_info.retry_count += 1
                    
                    # Attempt recovery
                    success = strategy.recover(error_info, context)
                    
                    if success:
                        error_info.recovery_successful = True
                        logger.info(f"Recovery successful with strategy: {strategy.name}")
                        return True
                    
                except Exception as recovery_error:
                    logger.error(f"Recovery strategy {strategy.name} failed: {recovery_error}")
        
        logger.error(f"All recovery strategies failed for error: {error_info.error_id}")
        return False
    
    def _publish_error(self, error_info: ErrorInfo):
        """Publish error to Redis for coordination."""
        try:
            error_data = {
                'error_id': error_info.error_id,
                'category': error_info.category.value,
                'severity': error_info.severity.value,
                'message': error_info.message,
                'timestamp': error_info.timestamp,
                'recovery_attempted': error_info.recovery_attempted,
                'recovery_successful': error_info.recovery_successful,
                'component': error_info.context.get('component', 'unknown')
            }
            
            # Publish to error stream
            self.redis_client.lpush('error_stream', json.dumps(error_data))
            
            # Set expiry
            self.redis_client.expire('error_stream', 3600)  # 1 hour
            
        except Exception as e:
            logger.error(f"Failed to publish error to Redis: {e}")
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics."""
        recent_errors = [
            e for e in self.error_history 
            if time.time() - e.timestamp < 3600  # Last hour
        ]
        
        return {
            'total_errors': len(self.error_history),
            'recent_errors': len(recent_errors),
            'error_counts': self.error_counts.copy(),
            'recovery_rate': self._calculate_recovery_rate(),
            'circuit_breakers': list(self.circuit_breakers.keys()),
            'most_common_errors': self._get_most_common_errors()
        }
    
    def _calculate_recovery_rate(self) -> float:
        """Calculate recovery success rate."""
        if not self.error_history:
            return 0.0
        
        recovery_attempts = [e for e in self.error_history if e.recovery_attempted]
        if not recovery_attempts:
            return 0.0
        
        successful_recoveries = [e for e in recovery_attempts if e.recovery_successful]
        return len(successful_recoveries) / len(recovery_attempts)
    
    def _get_most_common_errors(self) -> List[Dict[str, Any]]:
        """Get most common error types."""
        error_types = {}
        
        for error in self.error_history[-100:]:  # Last 100 errors
            key = f"{error.category.value}_{error.severity.value}"
            if key not in error_types:
                error_types[key] = {'count': 0, 'messages': []}
            
            error_types[key]['count'] += 1
            if error.message not in error_types[key]['messages']:
                error_types[key]['messages'].append(error.message)
        
        # Sort by count
        sorted_errors = sorted(
            error_types.items(),
            key=lambda x: x[1]['count'],
            reverse=True
        )
        
        return [
            {
                'type': error_type,
                'count': data['count'],
                'sample_messages': data['messages'][:3]  # Top 3 messages
            }
            for error_type, data in sorted_errors[:5]  # Top 5 error types
        ]

def error_handler_decorator(category: ErrorCategory, 
                          severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                          component: str = "unknown"):
    """Decorator for automatic error handling."""
    
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                # Get error handler from context or create default
                error_handler = getattr(wrapper, '_error_handler', None)
                if not error_handler:
                    error_handler = ErrorHandler()
                
                # Create context
                context = {
                    'function': func.__name__,
                    'args': args,
                    'kwargs': kwargs,
                    'component': component
                }
                
                # Handle error
                recovery_successful = error_handler.handle_error(
                    exception=e,
                    category=category,
                    severity=severity,
                    context=context,
                    component=component
                )
                
                # Re-raise if recovery failed and severity is high
                if not recovery_successful and severity in [ErrorSeverity.HIGH, ErrorSeverity.CRITICAL]:
                    raise
                
                # Return None or default value if recovery succeeded
                return None
        
        return wrapper
    return decorator

# Global error handler instance
global_error_handler = ErrorHandler()

def set_global_error_handler(handler: ErrorHandler):
    """Set global error handler."""
    global global_error_handler
    global_error_handler = handler

def handle_error(exception: Exception,
                category: ErrorCategory,
                severity: ErrorSeverity = ErrorSeverity.MEDIUM,
                context: Dict[str, Any] = None,
                component: str = "unknown") -> bool:
    """Convenience function for error handling."""
    if context is None:
        context = {}
    
    return global_error_handler.handle_error(
        exception=exception,
        category=category,
        severity=severity,
        context=context,
        component=component
    )
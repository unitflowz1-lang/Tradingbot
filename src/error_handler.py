"""Error handling utilities for the AI Forex Trading Bot"""

import asyncio
import logging
import time
from typing import Callable, Any, Optional, Type, Union
from functools import wraps
from src.exceptions import TradingBotException
from src.logging_config import get_error_logger


class RetryStrategy:
    """Base class for retry strategies"""
    
    def __init__(self, max_retries: int = 3):
        self.max_retries = max_retries
    
    def should_retry(self, attempt: int, exception: Exception) -> bool:
        """Determine if operation should be retried"""
        return attempt < self.max_retries
    
    def get_delay(self, attempt: int) -> float:
        """Get delay before next retry"""
        return 0.0


class ExponentialBackoffRetry(RetryStrategy):
    """Exponential backoff retry strategy"""
    
    def __init__(self, max_retries: int = 3, base_delay: float = 1.0, max_delay: float = 60.0):
        super().__init__(max_retries)
        self.base_delay = base_delay
        self.max_delay = max_delay
    
    def get_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay"""
        delay = self.base_delay * (2 ** attempt)
        return min(delay, self.max_delay)


class LinearBackoffRetry(RetryStrategy):
    """Linear backoff retry strategy"""
    
    def __init__(self, max_retries: int = 5, delay: float = 1.0):
        super().__init__(max_retries)
        self.delay = delay
    
    def get_delay(self, attempt: int) -> float:
        """Return fixed delay"""
        return self.delay


class NoRetry(RetryStrategy):
    """No retry strategy"""
    
    def __init__(self):
        super().__init__(0)
    
    def should_retry(self, attempt: int, exception: Exception) -> bool:
        return False


class ErrorHandler:
    """Central error handler with retry strategies"""
    
    def __init__(self):
        self.logger = get_error_logger()
        self.retry_strategies = {
            'network': ExponentialBackoffRetry(max_retries=3),
            'api_limit': LinearBackoffRetry(max_retries=5),
            'validation': NoRetry(),
            'default': ExponentialBackoffRetry(max_retries=2)
        }
    
    def get_retry_strategy(self, error: Exception) -> RetryStrategy:
        """Get appropriate retry strategy for error type"""
        error_name = type(error).__name__.lower()
        
        if 'network' in error_name or 'connection' in error_name or 'timeout' in error_name:
            return self.retry_strategies['network']
        elif 'rate' in error_name or 'limit' in error_name:
            return self.retry_strategies['api_limit']
        elif 'validation' in error_name or 'invalid' in error_name:
            return self.retry_strategies['validation']
        else:
            return self.retry_strategies['default']
    
    async def execute_with_retry(
        self,
        func: Callable,
        *args,
        error_context: Optional[str] = None,
        **kwargs
    ) -> Any:
        """Execute function with retry logic"""
        last_exception = None
        
        for attempt in range(10):  # Max attempts across all strategies
            try:
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)
            
            except Exception as e:
                last_exception = e
                strategy = self.get_retry_strategy(e)
                
                if not strategy.should_retry(attempt, e):
                    break
                
                delay = strategy.get_delay(attempt)
                
                self.logger.warning(
                    f"Attempt {attempt + 1} failed: {str(e)}. Retrying in {delay}s",
                    extra={
                        'error_context': error_context,
                        'attempt': attempt + 1,
                        'delay': delay,
                        'exception_type': type(e).__name__
                    }
                )
                
                if delay > 0:
                    await asyncio.sleep(delay)
        
        # All retries exhausted
        self.logger.error(
            f"All retry attempts exhausted: {str(last_exception)}",
            extra={
                'error_context': error_context,
                'exception_type': type(last_exception).__name__
            },
            exc_info=True
        )
        
        raise last_exception


def retry_on_error(
    strategy: Optional[Union[str, RetryStrategy]] = None,
    error_context: Optional[str] = None
):
    """Decorator for automatic error retry"""
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            error_handler = ErrorHandler()
            return await error_handler.execute_with_retry(
                func, *args, error_context=error_context, **kwargs
            )
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            error_handler = ErrorHandler()
            return asyncio.run(error_handler.execute_with_retry(
                func, *args, error_context=error_context, **kwargs
            ))
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator


def handle_trading_error(func: Callable) -> Callable:
    """Decorator for handling trading-specific errors"""
    
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        logger = get_error_logger()
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except TradingBotException as e:
            logger.error(
                f"Trading error in {func.__name__}: {str(e)}",
                extra={
                    'function': func.__name__,
                    'error_code': e.error_code,
                    'context': e.context
                },
                exc_info=True
            )
            raise
        except Exception as e:
            logger.error(
                f"Unexpected error in {func.__name__}: {str(e)}",
                extra={'function': func.__name__},
                exc_info=True
            )
            # Wrap unexpected errors in TradingBotException
            raise TradingBotException(
                f"Unexpected error in {func.__name__}: {str(e)}",
                error_code="UNEXPECTED_ERROR",
                context={'original_exception': type(e).__name__}
            )
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        return asyncio.run(async_wrapper(*args, **kwargs))
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    else:
        return sync_wrapper
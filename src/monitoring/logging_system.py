"""Comprehensive logging system for the AI Forex Trading Bot"""

import json
import logging
import logging.handlers
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Union
from dataclasses import dataclass, asdict

from ..models import Order, Position, TradingSignal


class LogLevel(Enum):
    """Log levels for the trading system"""
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class LogContext:
    """Context information for structured logging"""
    component: Optional[str] = None
    trade_id: Optional[str] = None
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    strategy: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values"""
        return {k: v for k, v in asdict(self).items() if v is not None}


class StructuredJSONFormatter(logging.Formatter):
    """Enhanced JSON formatter for structured logging"""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured JSON"""
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
            'thread': record.thread,
            'process': record.process
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = {
                'type': record.exc_info[0].__name__,
                'message': str(record.exc_info[1]),
                'traceback': self.formatException(record.exc_info)
            }
        
        # Add context information
        context_attrs = [
            'component', 'trade_id', 'order_id', 'symbol', 
            'session_id', 'user_id', 'strategy', 'execution_time',
            'api_endpoint', 'response_time', 'error_code'
        ]
        
        for attr in context_attrs:
            if hasattr(record, attr):
                log_entry[attr] = getattr(record, attr)
        
        # Add custom data if present
        if hasattr(record, 'data'):
            log_entry['data'] = record.data
            
        return json.dumps(log_entry, default=str)


class TradingLogger:
    """Enhanced logger for trading operations with structured logging"""
    
    def __init__(self, name: str, context: Optional[LogContext] = None):
        self.logger = logging.getLogger(name)
        self.context = context or LogContext()
        
    def _log_with_context(
        self, 
        level: LogLevel, 
        message: str, 
        context: Optional[LogContext] = None,
        data: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> None:
        """Log message with context information"""
        # Merge contexts
        final_context = LogContext()
        if self.context:
            final_context = LogContext(**asdict(self.context))
        if context:
            for key, value in asdict(context).items():
                if value is not None:
                    setattr(final_context, key, value)
        
        # Add context to log record
        extra = final_context.to_dict()
        if data:
            extra['data'] = data
        extra.update(kwargs)
        
        # Log the message
        getattr(self.logger, level.value.lower())(message, extra=extra)
    
    def debug(self, message: str, context: Optional[LogContext] = None, **kwargs) -> None:
        """Log debug message"""
        self._log_with_context(LogLevel.DEBUG, message, context, **kwargs)
    
    def info(self, message: str, context: Optional[LogContext] = None, **kwargs) -> None:
        """Log info message"""
        self._log_with_context(LogLevel.INFO, message, context, **kwargs)
    
    def warning(self, message: str, context: Optional[LogContext] = None, **kwargs) -> None:
        """Log warning message"""
        self._log_with_context(LogLevel.WARNING, message, context, **kwargs)
    
    def error(self, message: str, context: Optional[LogContext] = None, **kwargs) -> None:
        """Log error message"""
        self._log_with_context(LogLevel.ERROR, message, context, **kwargs)
    
    def critical(self, message: str, context: Optional[LogContext] = None, **kwargs) -> None:
        """Log critical message"""
        self._log_with_context(LogLevel.CRITICAL, message, context, **kwargs)
    
    def log_trade_decision(
        self, 
        signal: TradingSignal, 
        decision: str, 
        reasoning: str,
        context: Optional[LogContext] = None
    ) -> None:
        """Log trading decision with signal details"""
        trade_context = LogContext(
            component="TRADE_DECISION",
            symbol=signal.symbol,
            strategy=getattr(signal, 'strategy', None)
        )
        if context:
            for key, value in asdict(context).items():
                if value is not None:
                    setattr(trade_context, key, value)
        
        data = {
            'signal': {
                'direction': signal.direction.value,
                'entry_price': signal.entry_price,
                'stop_loss': signal.stop_loss,
                'take_profit': signal.take_profit,
                'confidence': signal.confidence
            },
            'decision': decision,
            'reasoning': reasoning
        }
        
        self.info(
            f"Trading decision made: {decision} for {signal.symbol}",
            context=trade_context,
            data=data
        )
    
    def log_order_event(
        self, 
        order: Order, 
        event: str, 
        details: Optional[Dict[str, Any]] = None,
        context: Optional[LogContext] = None
    ) -> None:
        """Log order-related events"""
        order_context = LogContext(
            component="ORDER_MANAGEMENT",
            order_id=order.order_id,
            symbol=order.symbol
        )
        if context:
            for key, value in asdict(context).items():
                if value is not None:
                    setattr(order_context, key, value)
        
        data = {
            'order': {
                'order_type': order.order_type.value,
                'direction': order.direction.value,
                'quantity': order.quantity,
                'price': order.price,
                'status': order.status.value
            },
            'event': event
        }
        if details:
            data['details'] = details
        
        self.info(
            f"Order event: {event} for order {order.order_id}",
            context=order_context,
            data=data
        )
    
    def log_position_update(
        self, 
        position: Position, 
        update_type: str,
        previous_values: Optional[Dict[str, Any]] = None,
        context: Optional[LogContext] = None
    ) -> None:
        """Log position updates"""
        position_context = LogContext(
            component="POSITION_TRACKING",
            symbol=position.symbol
        )
        if context:
            for key, value in asdict(context).items():
                if value is not None:
                    setattr(position_context, key, value)
        
        data = {
            'position': {
                'position_id': position.position_id,
                'direction': position.direction.value,
                'quantity': position.quantity,
                'entry_price': position.entry_price,
                'current_price': position.current_price,
                'unrealized_pnl': position.unrealized_pnl
            },
            'update_type': update_type
        }
        if previous_values:
            data['previous_values'] = previous_values
        
        self.info(
            f"Position update: {update_type} for {position.symbol}",
            context=position_context,
            data=data
        )
    
    def log_api_call(
        self, 
        endpoint: str, 
        method: str, 
        response_time: float,
        status_code: Optional[int] = None,
        error: Optional[str] = None,
        context: Optional[LogContext] = None
    ) -> None:
        """Log API calls with performance metrics"""
        api_context = LogContext(
            component="API_CLIENT"
        )
        if context:
            for key, value in asdict(context).items():
                if value is not None:
                    setattr(api_context, key, value)
        
        data = {
            'endpoint': endpoint,
            'method': method,
            'response_time': response_time,
            'status_code': status_code
        }
        if error:
            data['error'] = error
        
        level = LogLevel.ERROR if error else LogLevel.INFO
        message = f"API call to {endpoint} {'failed' if error else 'completed'} in {response_time:.3f}s"
        
        self._log_with_context(
            level, 
            message, 
            context=api_context,
            data=data,
            api_endpoint=endpoint,
            response_time=response_time
        )


class StructuredLogger:
    """Factory for creating structured loggers"""
    
    @staticmethod
    def get_logger(name: str, context: Optional[LogContext] = None) -> TradingLogger:
        """Get a trading logger with optional context"""
        return TradingLogger(name, context)
    
    @staticmethod
    def get_component_logger(component: str) -> TradingLogger:
        """Get a logger for a specific component"""
        context = LogContext(component=component)
        return TradingLogger(f"trading.{component.lower()}", context)


def setup_comprehensive_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    max_file_size: int = 50 * 1024 * 1024,  # 50MB
    backup_count: int = 10,
    enable_console: bool = True,
    enable_json: bool = True,
    retention_days: int = 30
) -> None:
    """Setup comprehensive logging configuration with rotation and retention"""
    
    # Create logs directory
    log_path = Path(log_dir)
    log_path.mkdir(exist_ok=True)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    if enable_console:
        if hasattr(sys.stdout, 'reconfigure'):
            try:
                sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
        if hasattr(sys.stderr, 'reconfigure'):
            try:
                sys.stderr.reconfigure(encoding='utf-8', errors='replace')
            except Exception:
                pass
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        if enable_json:
            console_handler.setFormatter(StructuredJSONFormatter())
        else:
            console_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            console_handler.setFormatter(console_formatter)
        
        root_logger.addHandler(console_handler)
    
    # Setup specialized log files
    log_configs = [
        {
            'name': 'general',
            'filename': 'forex_bot.log',
            'level': logging.DEBUG,
            'logger_name': None  # Root logger
        },
        {
            'name': 'trading',
            'filename': 'trading.log',
            'level': logging.INFO,
            'logger_name': 'trading'
        },
        {
            'name': 'errors',
            'filename': 'errors.log',
            'level': logging.ERROR,
            'logger_name': 'errors'
        },
        {
            'name': 'api',
            'filename': 'api_calls.log',
            'level': logging.INFO,
            'logger_name': 'api'
        },
        {
            'name': 'performance',
            'filename': 'performance.log',
            'level': logging.INFO,
            'logger_name': 'performance'
        }
    ]
    
    for config in log_configs:
        # Create rotating file handler
        handler = logging.handlers.RotatingFileHandler(
            filename=log_path / config['filename'],
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding='utf-8'
        )
        handler.setLevel(config['level'])
        handler.setFormatter(StructuredJSONFormatter())
        
        # Add to appropriate logger
        if config['logger_name']:
            logger = logging.getLogger(config['logger_name'])
            logger.addHandler(handler)
            logger.propagate = False
        else:
            root_logger.addHandler(handler)
    
    # Setup log cleanup (retention policy)
    _setup_log_retention(log_path, retention_days)


def _setup_log_retention(log_dir: Path, retention_days: int) -> None:
    """Setup log file retention policy"""
    import time
    import glob
    
    def cleanup_old_logs():
        """Remove log files older than retention_days"""
        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
        
        for log_file in glob.glob(str(log_dir / "*.log*")):
            try:
                if os.path.getmtime(log_file) < cutoff_time:
                    os.remove(log_file)
                    print(f"Removed old log file: {log_file}")
            except OSError:
                pass  # File might be in use or already deleted
    
    # Run cleanup on setup
    cleanup_old_logs()

"""
Structured logging system for the trading bot.
Supports JSON logging, file rotation, and structured output.
"""

import logging
import logging.handlers
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }
        
        # Add extra fields
        if hasattr(record, 'extra_data'):
            log_data.update(record.extra_data)
        
        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class StructuredLogger:
    """Wrapper around logging for structured logging with context."""
    
    def __init__(self, name: str, json_output: bool = True):
        """
        Initialize logger.
        
        Args:
            name: Logger name
            json_output: If True, use JSON formatting
        """
        self.logger = logging.getLogger(name)
        self._setup_handlers(json_output)
    
    def _setup_handlers(self, json_output: bool):
        """Setup logging handlers."""
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        
        if json_output:
            console_handler.setFormatter(JSONFormatter())
        
        # File handler with rotation
        log_dir = Path('logs')
        log_dir.mkdir(exist_ok=True)
        
        file_handler = logging.handlers.RotatingFileHandler(
            log_dir / 'trading_bot.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=10
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(JSONFormatter())
        
        self.logger.addHandler(console_handler)
        self.logger.addHandler(file_handler)
        self.logger.setLevel(logging.DEBUG)
    
    def info(self, message: str, **extras):
        """Log info level."""
        record = self.logger.makeRecord(
            self.logger.name, logging.INFO, '', 0, message, (), None
        )
        record.extra_data = extras
        self.logger.handle(record)
    
    def debug(self, message: str, **extras):
        """Log debug level."""
        record = self.logger.makeRecord(
            self.logger.name, logging.DEBUG, '', 0, message, (), None
        )
        record.extra_data = extras
        self.logger.handle(record)
    
    def error(self, message: str, **extras):
        """Log error level."""
        record = self.logger.makeRecord(
            self.logger.name, logging.ERROR, '', 0, message, (), None
        )
        record.extra_data = extras
        self.logger.handle(record)
    
    def warning(self, message: str, **extras):
        """Log warning level."""
        record = self.logger.makeRecord(
            self.logger.name, logging.WARNING, '', 0, message, (), None
        )
        record.extra_data = extras
        self.logger.handle(record)


def get_logger(name: str) -> StructuredLogger:
    """Get or create a structured logger."""
    return StructuredLogger(name)

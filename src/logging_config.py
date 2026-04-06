"""Logging configuration for the AI Forex Trading Bot"""

import json
import logging
import logging.handlers
import os
import re
import sys
from datetime import datetime, timezone
from typing import Optional


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text"""
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)


class SafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler with Windows-safe file rotation"""
    
    def doRollover(self):
        """Override doRollover to handle Windows file locking issues"""
        try:
            super().doRollover()
        except (OSError, PermissionError):
            # On Windows, file might be locked. Try to close and reopen
            if self.stream:
                self.stream.close()
                self.stream = None
            
            try:
                # Remove the backup file if it exists
                backup_name = f"{self.baseFilename}.1"
                if os.path.exists(backup_name):
                    try:
                        os.remove(backup_name)
                    except OSError:
                        pass
                
                # Attempt rotation again
                if os.path.exists(self.baseFilename):
                    try:
                        os.rename(self.baseFilename, backup_name)
                    except OSError:
                        # If still can't rename, just truncate
                        pass
            except Exception:
                pass
            
            # Reopen the file
            self.stream = self._open()
    
    def emit(self, record):
        """Override emit to catch rotation errors gracefully"""
        try:
            super().emit(record)
        except PermissionError:
            # Silently ignore permission errors during logging
            pass


class SimpleFormatter(logging.Formatter):
    """Minimal, low-noise formatter."""

    def format(self, record):
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        msg = strip_ansi_codes(record.getMessage())
        return f"{timestamp} | {record.levelname} | {msg}"

class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging"""
    
    def __init__(self, strip_ansi: bool = False):
        super().__init__()
        self.strip_ansi = strip_ansi
    
    def format(self, record):
        msg = record.getMessage()
        if self.strip_ansi:
            msg = strip_ansi_codes(msg)
            
        log_entry = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': msg,
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno
        }
        
        # Add exception info if present
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        
        # Add extra fields if present
        if hasattr(record, 'trade_id'):
            log_entry['trade_id'] = record.trade_id
        if hasattr(record, 'symbol'):
            log_entry['symbol'] = record.symbol
        if hasattr(record, 'order_id'):
            log_entry['order_id'] = record.order_id
        
        return json.dumps(log_entry)


class TradingLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter for trading-specific context"""
    
    def process(self, msg, kwargs):
        return '[%s] %s' % (self.extra.get('component', 'UNKNOWN'), msg), kwargs


def setup_logging(
    log_level: str = "INFO",
    log_dir: str = "logs",
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
    enable_console: bool = True,
    enable_json: bool = False,
) -> None:
    """Setup logging configuration"""
    
    # Create logs directory if it doesn't exist
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler
    if enable_console:
        # Force UTF-8 encoding for console to handle Unicode characters
        console_handler = logging.StreamHandler(sys.stdout)
        # Try to set UTF-8 encoding
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
        
        console_handler.setLevel(logging.INFO)
        
        console_handler.setFormatter(SimpleFormatter())
        
        root_logger.addHandler(console_handler)
    
    # File handler for general logs
    general_file_handler = SafeRotatingFileHandler(
        filename=os.path.join(log_dir, "forex_bot.log"),
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    general_file_handler.setLevel(logging.DEBUG)
    
    if enable_json:
        general_file_handler.setFormatter(JSONFormatter(strip_ansi=True))
    else:
        general_file_handler.setFormatter(SimpleFormatter())
    
    root_logger.addHandler(general_file_handler)
    
    # Separate file handler for trading activities
    trading_file_handler = SafeRotatingFileHandler(
        filename=os.path.join(log_dir, 'trading.log'),
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    trading_file_handler.setLevel(logging.INFO)
    trading_file_handler.setFormatter(JSONFormatter(strip_ansi=True) if enable_json else SimpleFormatter())
    
    # Create trading logger
    trading_logger = logging.getLogger('trading')
    trading_logger.addHandler(trading_file_handler)
    trading_logger.propagate = False
    
    # Separate file handler for errors
    error_file_handler = SafeRotatingFileHandler(
        filename=os.path.join(log_dir, 'errors.log'),
        maxBytes=max_file_size,
        backupCount=backup_count,
        encoding='utf-8'
    )
    error_file_handler.setLevel(logging.ERROR)
    error_file_handler.setFormatter(JSONFormatter(strip_ansi=True) if enable_json else SimpleFormatter())
    
    # Create error logger
    error_logger = logging.getLogger('errors')
    error_logger.addHandler(error_file_handler)
    error_logger.propagate = True


def get_logger(
    name: str, component: Optional[str] = None
) -> logging.Logger:
    """Get logger with optional component context"""
    logger = logging.getLogger(name)

    if component:
        return TradingLoggerAdapter(logger, {"component": component})

    return logger


def get_trading_logger() -> logging.Logger:
    """Get specialized trading logger"""
    return logging.getLogger('trading')


def get_error_logger() -> logging.Logger:
    """Get specialized error logger"""
    return logging.getLogger('errors')


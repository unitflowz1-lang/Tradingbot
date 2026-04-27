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


ANSI_RESET = "\033[0m"
ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"


def _supports_ansi() -> bool:
    """Best-effort ANSI capability detection for Windows terminals."""
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    if not bool(getattr(sys.stdout, "isatty", lambda: False)()):
        return False

    if os.name == "nt":
        # Conservative Windows detection:
        # classic cmd.exe often prints raw ANSI codes unless VT processing is enabled.
        # Only enable color automatically for terminals that reliably support it.
        if os.environ.get("WT_SESSION"):
            return True
        if os.environ.get("ANSICON"):
            return True
        if os.environ.get("ConEmuANSI", "").upper() == "ON":
            return True
        if os.environ.get("TERM_PROGRAM", "").lower() in {"vscode", "windows_terminal"}:
            return True
        term = os.environ.get("TERM", "").lower()
        if "xterm" in term or "ansi" in term or "color" in term:
            return True
        return False

    return True


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


class FuturisticConsoleFormatter(logging.Formatter):
    """Structured neon-style formatter for live terminal output."""

    LEVEL_STYLES = {
        "DEBUG": ("\033[38;5;245m", "DBG"),
        "INFO": ("\033[38;5;51m", "INF"),
        "WARNING": ("\033[38;5;226m", "WRN"),
        "ERROR": ("\033[38;5;203m", "ERR"),
        "CRITICAL": ("\033[48;5;196m\033[38;5;231m", "CRT"),
    }

    TAG_COLOR = "\033[38;5;87m"
    TIME_COLOR = "\033[38;5;110m"
    FRAME_COLOR = "\033[38;5;238m"
    BODY_COLOR = "\033[38;5;255m"

    def __init__(self, use_color: bool = True):
        super().__init__()
        self.use_color = bool(use_color)

    def _paint(self, value: str, style: str) -> str:
        if not self.use_color:
            return value
        return f"{style}{value}{ANSI_RESET}"

    def _level_badge(self, level_name: str) -> str:
        color, short = self.LEVEL_STYLES.get(level_name, ("\033[38;5;250m", level_name[:3].upper()))
        text = f" {short} "
        return self._paint(text, f"{ANSI_BOLD}{color}")

    def _highlight_tags(self, message: str) -> str:
        if not self.use_color:
            return message
        return re.sub(
            r"(\[[A-Z0-9_\-\/]+\])",
            lambda match: self._paint(match.group(1), f"{ANSI_BOLD}{self.TAG_COLOR}"),
            message,
        )

    def format(self, record):
        timestamp = datetime.now(timezone.utc).strftime('%H:%M:%S')
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{self.formatException(record.exc_info)}"

        time_block = self._paint(timestamp, f"{ANSI_DIM}{self.TIME_COLOR}")
        frame = self._paint("│", self.FRAME_COLOR)
        body = self._paint(self._highlight_tags(message), self.BODY_COLOR) if self.use_color else message
        return f"{time_block} {frame} {self._level_badge(record.levelname)} {frame} {body}"

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
        console_handler.setFormatter(FuturisticConsoleFormatter(use_color=_supports_ansi()))
        
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
    
    # PRODUCTION OPTIMIZATION: Reduce console noise for 24/7 monitoring
    # Set verbose diagnostic loggers to DEBUG level (only shown in log files, not console)
    # Console will only show: Signal Generation, Order Execution, Logic Vetoes, Cycle Summary
    logging.getLogger('src.analysis.quant_hybrid_strategy').setLevel(logging.DEBUG)  # LITE_ANALYZE
    logging.getLogger('src.strategies.quant_hybrid_strategy').setLevel(logging.DEBUG)  # LITE_ANALYZE
    logging.getLogger('src.data.quant_data_flow').setLevel(logging.DEBUG)  # QUANT_DATA_FLOW_TRACE
    logging.getLogger('src.data.cache_manager').setLevel(logging.DEBUG)  # CACHE_QUANT_FIELDS, CACHE_UPDATE


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


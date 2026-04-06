"""AI Forex Trading Bot - Main Package

This package provides a comprehensive AI-powered forex trading bot that combines
sentiment analysis from Large Language Models with technical indicators to make
informed trading decisions.

Key Components:
- Data acquisition and processing
- LLM-based sentiment analysis
- Technical analysis engine
- Signal generation and combination
- Risk management system
- Trade execution engine
- Performance monitoring and logging
"""

from src.config import ConfigManager
from src.logging_config import setup_logging, get_logger
from src.models import *
from src.interfaces import *
from src.exceptions import *
from src.error_handler import ErrorHandler, retry_on_error, handle_trading_error

__version__ = "1.0.0"
__author__ = "AI Forex Trading Bot Team"

# Initialize logging on import
setup_logging()

# Get main logger
logger = get_logger(__name__)

logger.info(f"AI Forex Trading Bot v{__version__} initialized")
"""Custom exceptions for the AI Forex Trading Bot"""

from typing import Optional, Dict, Any


class TradingBotException(Exception):
    """Base exception for trading bot"""
    
    def __init__(self, message: str, error_code: Optional[str] = None, context: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.error_code = error_code
        self.context = context or {}


class DataCollectionError(TradingBotException):
    """Exception raised during data collection"""
    pass


class DataValidationError(TradingBotException):
    """Exception raised during data validation"""
    pass


class SentimentAnalysisError(TradingBotException):
    """Exception raised during sentiment analysis"""
    pass


class TechnicalAnalysisError(TradingBotException):
    """Exception raised during technical analysis"""
    pass


class SignalGenerationError(TradingBotException):
    """Exception raised during signal generation"""
    pass


class RiskManagementError(TradingBotException):
    """Exception raised during risk management"""
    pass


class TradeExecutionError(TradingBotException):
    """Exception raised during trade execution"""
    pass


class BrokerAPIError(TradingBotException):
    """Exception raised during broker API interactions"""
    pass


class ConfigurationError(TradingBotException):
    """Exception raised for configuration issues"""
    pass


class LLMAPIError(TradingBotException):
    """Exception raised during LLM API interactions"""
    pass


class DatabaseError(TradingBotException):
    """Exception raised during database operations"""
    pass


class APIError(TradingBotException):
    """Exception raised during API interactions"""
    pass


class BacktestError(TradingBotException):
    """Exception raised during backtesting operations"""
    pass


class PaperTradingError(TradingBotException):
    """Exception raised during paper trading operations"""
    pass


class SignalAbortedException(TradingBotException):
    """Exception raised when a signal must be aborted before execution"""
    pass
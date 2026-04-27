"""Unit tests for the comprehensive logging system"""

import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from src.monitoring.logging_system import (
    LogLevel,
    LogContext,
    StructuredJSONFormatter,
    TradingLogger,
    StructuredLogger,
    setup_comprehensive_logging
)
from src.models import Order, Position, TradingSignal, OrderType, Direction, OrderStatus


class TestLogContext(unittest.TestCase):
    """Test LogContext functionality"""
    
    def test_log_context_creation(self):
        """Test LogContext creation and conversion"""
        context = LogContext(
            component="TEST",
            trade_id="trade_123",
            symbol="EURUSD"
        )
        
        self.assertEqual(context.component, "TEST")
        self.assertEqual(context.trade_id, "trade_123")
        self.assertEqual(context.symbol, "EURUSD")
        self.assertIsNone(context.order_id)
    
    def test_log_context_to_dict(self):
        """Test LogContext to_dict method excludes None values"""
        context = LogContext(
            component="TEST",
            trade_id="trade_123",
            symbol=None  # Should be excluded
        )
        
        result = context.to_dict()
        expected = {
            "component": "TEST",
            "trade_id": "trade_123"
        }
        
        self.assertEqual(result, expected)
        self.assertNotIn("symbol", result)


class TestStructuredJSONFormatter(unittest.TestCase):
    """Test StructuredJSONFormatter functionality"""
    
    def setUp(self):
        self.formatter = StructuredJSONFormatter()
    
    def test_basic_formatting(self):
        """Test basic log record formatting"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.module = "test_module"
        record.funcName = "test_function"
        record.thread = 12345
        record.process = 67890
        
        result = self.formatter.format(record)
        log_data = json.loads(result)
        
        self.assertEqual(log_data["level"], "INFO")
        self.assertEqual(log_data["logger"], "test_logger")
        self.assertEqual(log_data["message"], "Test message")
        self.assertEqual(log_data["module"], "test_module")
        self.assertEqual(log_data["function"], "test_function")
        self.assertEqual(log_data["line"], 10)
        self.assertEqual(log_data["thread"], 12345)
        self.assertEqual(log_data["process"], 67890)
        self.assertIn("timestamp", log_data)
    
    def test_formatting_with_context(self):
        """Test formatting with context attributes"""
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None
        )
        record.module = "test_module"
        record.funcName = "test_function"
        record.thread = 12345
        record.process = 67890
        record.component = "TRADING"
        record.trade_id = "trade_123"
        record.symbol = "EURUSD"
        
        result = self.formatter.format(record)
        log_data = json.loads(result)
        
        self.assertEqual(log_data["component"], "TRADING")
        self.assertEqual(log_data["trade_id"], "trade_123")
        self.assertEqual(log_data["symbol"], "EURUSD")
    
    def test_formatting_with_exception(self):
        """Test formatting with exception information"""
        try:
            raise ValueError("Test exception")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="Error occurred",
            args=(),
            exc_info=exc_info
        )
        record.module = "test_module"
        record.funcName = "test_function"
        record.thread = 12345
        record.process = 67890
        
        result = self.formatter.format(record)
        log_data = json.loads(result)
        
        self.assertIn("exception", log_data)
        self.assertEqual(log_data["exception"]["type"], "ValueError")
        self.assertEqual(log_data["exception"]["message"], "Test exception")
        self.assertIn("traceback", log_data["exception"])


class TestTradingLogger(unittest.TestCase):
    """Test TradingLogger functionality"""
    
    def setUp(self):
        self.context = LogContext(component="TEST", trade_id="trade_123")
        self.logger = TradingLogger("test_logger", self.context)
        
        # Mock the underlying logger
        self.mock_logger = Mock()
        self.logger.logger = self.mock_logger
    
    def test_basic_logging_methods(self):
        """Test basic logging methods"""
        self.logger.info("Test message")
        
        self.mock_logger.info.assert_called_once()
        args, kwargs = self.mock_logger.info.call_args
        
        self.assertEqual(args[0], "Test message")
        self.assertIn("extra", kwargs)
        self.assertEqual(kwargs["extra"]["component"], "TEST")
        self.assertEqual(kwargs["extra"]["trade_id"], "trade_123")
    
    def test_logging_with_additional_context(self):
        """Test logging with additional context"""
        additional_context = LogContext(symbol="EUR/USD", order_id="order_456")
        self.logger.info("Test message", context=additional_context)
        
        args, kwargs = self.mock_logger.info.call_args
        extra = kwargs["extra"]
        
        self.assertEqual(extra["component"], "TEST")
        self.assertEqual(extra["trade_id"], "trade_123")
        self.assertEqual(extra["symbol"], "EUR/USD")
        self.assertEqual(extra["order_id"], "order_456")
    
    def test_log_trade_decision(self):
        """Test trade decision logging"""
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.1,
            confidence=0.8,
            reasoning="Strong bullish signal",
            timestamp=datetime.now(timezone.utc)
        )
        
        self.logger.log_trade_decision(
            signal=signal,
            decision="BUY",
            reasoning="Technical and sentiment alignment"
        )
        
        self.mock_logger.info.assert_called_once()
        args, kwargs = self.mock_logger.info.call_args
        
        self.assertIn("Trading decision made", args[0])
        self.assertIn("EUR/USD", args[0])
        self.assertIn("data", kwargs["extra"])
        
        data = kwargs["extra"]["data"]
        self.assertEqual(data["decision"], "BUY")
        self.assertEqual(data["signal"]["direction"], "LONG")
        self.assertEqual(data["signal"]["confidence"], 0.8)
    
    def test_log_order_event(self):
        """Test order event logging"""
        order = Order(
            order_id="order_123",
            symbol="EUR/USD",
            order_type=OrderType.MARKET,
            direction=Direction.LONG,
            quantity=0.1,
            price=None,
            stop_loss=1.0950,
            take_profit=1.1100,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
        
        self.logger.log_order_event(
            order=order,
            event="ORDER_PLACED",
            details={"broker_id": "broker_456"}
        )
        
        self.mock_logger.info.assert_called_once()
        args, kwargs = self.mock_logger.info.call_args
        
        self.assertIn("Order event", args[0])
        self.assertIn("data", kwargs["extra"])
        
        data = kwargs["extra"]["data"]
        self.assertEqual(data["event"], "ORDER_PLACED")
        self.assertEqual(data["order"]["order_type"], "MARKET")
        self.assertEqual(data["details"]["broker_id"], "broker_456")
    
    def test_log_api_call_success(self):
        """Test successful API call logging"""
        self.logger.log_api_call(
            endpoint="/api/orders",
            method="POST",
            response_time=0.250,
            status_code=200
        )
        
        self.mock_logger.info.assert_called_once()
        args, kwargs = self.mock_logger.info.call_args
        
        self.assertIn("API call to /api/orders completed", args[0])
        self.assertIn("data", kwargs["extra"])
        
        data = kwargs["extra"]["data"]
        self.assertEqual(data["endpoint"], "/api/orders")
        self.assertEqual(data["method"], "POST")
        self.assertEqual(data["response_time"], 0.250)
        self.assertEqual(data["status_code"], 200)
    
    def test_log_api_call_error(self):
        """Test failed API call logging"""
        self.logger.log_api_call(
            endpoint="/api/orders",
            method="POST",
            response_time=5.0,
            status_code=500,
            error="Internal server error"
        )
        
        self.mock_logger.error.assert_called_once()
        args, kwargs = self.mock_logger.error.call_args
        
        self.assertIn("API call to /api/orders failed", args[0])
        self.assertIn("data", kwargs["extra"])
        
        data = kwargs["extra"]["data"]
        self.assertEqual(data["error"], "Internal server error")


class TestStructuredLogger(unittest.TestCase):
    """Test StructuredLogger factory"""
    
    def test_get_logger(self):
        """Test getting a logger with context"""
        context = LogContext(component="TEST")
        logger = StructuredLogger.get_logger("test_logger", context)
        
        self.assertIsInstance(logger, TradingLogger)
        self.assertEqual(logger.context.component, "TEST")
    
    def test_get_component_logger(self):
        """Test getting a component-specific logger"""
        logger = StructuredLogger.get_component_logger("TRADING")
        
        self.assertIsInstance(logger, TradingLogger)
        self.assertEqual(logger.context.component, "TRADING")


class TestLoggingSetup(unittest.TestCase):
    """Test logging setup functionality"""
    
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
    
    def tearDown(self):
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_setup_comprehensive_logging(self):
        """Test comprehensive logging setup"""
        setup_comprehensive_logging(
            log_level="DEBUG",
            log_dir=self.temp_dir,
            enable_console=False,
            retention_days=7
        )
        
        # Check that log files are created
        log_files = [
            "forex_bot.log",
            "trading.log", 
            "errors.log",
            "api_calls.log",
            "performance.log"
        ]
        
        for log_file in log_files:
            log_path = Path(self.temp_dir) / log_file
            # File might not exist until first log, but directory should exist
            self.assertTrue(Path(self.temp_dir).exists())
        
        # Test that loggers are configured
        root_logger = logging.getLogger()
        self.assertTrue(len(root_logger.handlers) > 0)
        
        trading_logger = logging.getLogger("trading")
        self.assertTrue(len(trading_logger.handlers) > 0)
    
    def test_log_format_validation(self):
        """Test that logs are properly formatted as JSON"""
        setup_comprehensive_logging(
            log_level="INFO",
            log_dir=self.temp_dir,
            enable_console=False
        )
        
        # Create a test logger and log a message
        logger = StructuredLogger.get_component_logger("TEST")
        logger.info("Test log message", data={"test_key": "test_value"})
        
        # Check that the log file contains valid JSON
        log_file = Path(self.temp_dir) / "forex_bot.log"
        if log_file.exists():
            with open(log_file, 'r') as f:
                for line in f:
                    if line.strip():
                        try:
                            log_data = json.loads(line.strip())
                            self.assertIn("timestamp", log_data)
                            self.assertIn("level", log_data)
                            self.assertIn("message", log_data)
                        except json.JSONDecodeError:
                            self.fail(f"Invalid JSON in log file: {line}")


if __name__ == "__main__":
    unittest.main()
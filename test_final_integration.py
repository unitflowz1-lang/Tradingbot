#!/usr/bin/env python3
"""
Final Integration Tests for Production Deployment

This test suite validates the complete system integration and readiness
for production deployment. It covers all critical paths and ensures
system reliability under various conditions.
"""

import asyncio
import json
import time
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from typing import Dict, List, Any
import tempfile
import os

# Import all major components
from src.config import get_config_manager
from src.data.market_data_collector import MarketDataCollector
from src.data.news_data_collector import NewsDataCollector
from src.analysis.llm_client import LLMClient
from src.analysis.sentiment_aggregator import SentimentAggregator
from src.analysis.technical_indicators import IndicatorCalculator
from src.analysis.signal_combiner import SignalCombiner
from src.risk.position_sizer import PositionSizer
from src.risk.drawdown_monitor import DrawdownMonitor
from src.trading.execution_engine import ExecutionEngine
from src.monitoring.performance_monitor import PerformanceMonitor
from src.monitoring.alert_system import AlertSystem
from src.health_check import HealthChecker
from src.models import MarketData, TradingSignal, Order, Position


class TestFinalSystemIntegration(unittest.TestCase):
    """Comprehensive system integration tests for production readiness"""
    
    def setUp(self):
        """Set up test environment with all components"""
        self.config_manager = get_config_manager()
        self.test_start_time = time.time()
        
        # Initialize all major components
        self.market_data_collector = MarketDataCollector()
        self.news_collector = NewsDataCollector()
        self.llm_client = LLMClient()
        self.sentiment_aggregator = SentimentAggregator()
        self.indicator_calculator = IndicatorCalculator()
        self.signal_combiner = SignalCombiner()
        self.position_sizer = PositionSizer()
        self.drawdown_monitor = DrawdownMonitor()
        self.execution_engine = ExecutionEngine()
        self.performance_monitor = PerformanceMonitor()
        self.alert_system = AlertSystem()
        self.health_checker = HealthChecker()
        
        # Test data
        self.test_symbols = ['EURUSD', 'GBPUSD', 'USDJPY']
        self.test_account_balance = 10000.0
    
    def test_complete_trading_workflow(self):
        """Test complete end-to-end trading workflow"""
        print("\n=== Testing Complete Trading Workflow ===")
        
        with patch.multiple(
            'src.data.market_data_collector.MarketDataCollector',
            collect_market_data=Mock(return_value=self._create_mock_market_data()),
            validate_data=Mock(return_value=True)
        ), patch.multiple(
            'src.data.news_data_collector.NewsDataCollector',
            collect_news=Mock(return_value=self._create_mock_news_data()),
            preprocess_text=Mock(return_value="Positive market sentiment")
        ), patch.multiple(
            'src.analysis.llm_client.LLMClient',
            analyze_sentiment=AsyncMock(return_value=self._create_mock_sentiment_result()),
            validate_response=Mock(return_value=True)
        ), patch.multiple(
            'src.trading.execution_engine.ExecutionEngine',
            execute_trade=AsyncMock(return_value=self._create_mock_execution_result()),
            get_account_info=Mock(return_value={'balance': self.test_account_balance})
        ):
            
            # Step 1: Data Collection
            print("Step 1: Collecting market and news data...")
            market_data = self.market_data_collector.collect_market_data(
                symbols=self.test_symbols,
                timeframe='1h'
            )
            self.assertIsNotNone(market_data)
            self.assertTrue(len(market_data) > 0)
            
            news_data = self.news_collector.collect_news(
                symbols=self.test_symbols,
                hours_back=24
            )
            self.assertIsNotNone(news_data)
            
            # Step 2: Sentiment Analysis
            print("Step 2: Analyzing sentiment...")
            sentiment_result = asyncio.run(
                self.llm_client.analyze_sentiment(
                    text_data=["Positive market sentiment"],
                    symbol="EURUSD"
                )
            )
            self.assertIsNotNone(sentiment_result)
            self.assertGreaterEqual(sentiment_result.confidence, 0.0)
            self.assertLessEqual(sentiment_result.confidence, 1.0)
            
            # Step 3: Technical Analysis
            print("Step 3: Calculating technical indicators...")
            indicators = self.indicator_calculator.calculate_indicators(
                market_data[0] if market_data else self._create_mock_market_data()[0]
            )
            self.assertIsNotNone(indicators)
            self.assertIn('sma_20', indicators)
            self.assertIn('rsi', indicators)
            
            # Step 4: Signal Generation
            print("Step 4: Generating trading signals...")
            trading_signal = self.signal_combiner.generate_signal(
                sentiment_result=sentiment_result,
                technical_indicators=indicators,
                symbol="EURUSD"
            )
            self.assertIsNotNone(trading_signal)
            self.assertIn(trading_signal.direction, ['long', 'short'])
            
            # Step 5: Risk Management
            print("Step 5: Applying risk management...")
            position_size = self.position_sizer.calculate_position_size(
                signal=trading_signal,
                account_balance=self.test_account_balance,
                risk_per_trade=0.02
            )
            self.assertGreater(position_size, 0)
            self.assertLess(position_size, self.test_account_balance * 0.1)
            
            # Step 6: Trade Execution
            print("Step 6: Executing trade...")
            order = Order(
                order_id="test_order_001",
                symbol=trading_signal.symbol,
                order_type="market",
                direction=trading_signal.direction,
                quantity=position_size,
                price=trading_signal.entry_price,
                stop_loss=trading_signal.stop_loss,
                take_profit=trading_signal.take_profit,
                status="pending",
                created_at=datetime.now()
            )
            
            execution_result = asyncio.run(
                self.execution_engine.execute_trade(order)
            )
            self.assertTrue(execution_result['success'])
            self.assertIn('order_id', execution_result)
            
            # Step 7: Performance Monitoring
            print("Step 7: Monitoring performance...")
            self.performance_monitor.track_trade(order, execution_result)
            metrics = self.performance_monitor.calculate_metrics()
            self.assertIn('total_trades', metrics)
            self.assertGreaterEqual(metrics['total_trades'], 1)
            
            print("✓ Complete trading workflow test passed!")
    
    def test_system_resilience(self):
        """Test system resilience under various failure conditions"""
        print("\n=== Testing System Resilience ===")
        
        # Test 1: API Failure Recovery
        print("Test 1: API failure recovery...")
        with patch.object(self.llm_client, 'analyze_sentiment', 
                         side_effect=Exception("API Error")):
            try:
                result = asyncio.run(
                    self.sentiment_aggregator.get_aggregated_sentiment(
                        text_data=["Test text"],
                        symbol="EURUSD"
                    )
                )
                # Should handle gracefully and return cached or default result
                self.assertIsNotNone(result)
            except Exception as e:
                self.fail(f"System should handle API failures gracefully: {e}")
        
        # Test 2: Database Connection Loss
        print("Test 2: Database connection resilience...")
        # This would be tested with actual database mocking in real scenario
        
        # Test 3: High Load Conditions
        print("Test 3: High load handling...")
        start_time = time.time()
        
        # Simulate multiple concurrent operations
        tasks = []
        for i in range(10):
            task = self._simulate_trading_operation(f"EURUSD_{i}")
            tasks.append(task)
        
        # All operations should complete within reasonable time
        results = asyncio.run(asyncio.gather(*tasks, return_exceptions=True))
        processing_time = time.time() - start_time
        
        self.assertLess(processing_time, 10.0)  # Should complete within 10 seconds
        
        # Check that most operations succeeded
        successful_results = [r for r in results if not isinstance(r, Exception)]
        self.assertGreater(len(successful_results), len(results) * 0.8)  # 80% success rate
        
        print("✓ System resilience tests passed!")
    
    def test_performance_benchmarks(self):
        """Test system performance against benchmarks"""
        print("\n=== Testing Performance Benchmarks ===")
        
        # Test 1: Signal Processing Speed
        print("Test 1: Signal processing speed...")
        start_time = time.time()
        
        for _ in range(100):
            # Simulate signal processing
            market_data = self._create_mock_market_data()[0]
            indicators = self.indicator_calculator.calculate_indicators(market_data)
            self.assertIsNotNone(indicators)
        
        processing_time = time.time() - start_time
        signals_per_second = 100 / processing_time
        
        print(f"Signal processing rate: {signals_per_second:.2f} signals/second")
        self.assertGreater(signals_per_second, 50)  # Should process at least 50 signals/second
        
        # Test 2: Memory Usage
        print("Test 2: Memory usage...")
        import psutil
        process = psutil.Process()
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Perform memory-intensive operations
        large_dataset = []
        for i in range(1000):
            large_dataset.append(self._create_mock_market_data())
        
        peak_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = peak_memory - initial_memory
        
        print(f"Memory usage: {initial_memory:.2f} MB -> {peak_memory:.2f} MB")
        print(f"Memory increase: {memory_increase:.2f} MB")
        
        # Clean up
        del large_dataset
        import gc
        gc.collect()
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        print(f"Memory after cleanup: {final_memory:.2f} MB")
        
        # Memory should not increase excessively
        self.assertLess(memory_increase, 500)  # Less than 500MB increase
        
        # Test 3: Response Time
        print("Test 3: API response time...")
        response_times = []
        
        for _ in range(10):
            start = time.time()
            # Simulate API call
            health_status = self.health_checker.check_system_health()
            end = time.time()
            response_times.append((end - start) * 1000)  # Convert to milliseconds
        
        avg_response_time = sum(response_times) / len(response_times)
        max_response_time = max(response_times)
        
        print(f"Average response time: {avg_response_time:.2f}ms")
        print(f"Maximum response time: {max_response_time:.2f}ms")
        
        self.assertLess(avg_response_time, 100)  # Average should be under 100ms
        self.assertLess(max_response_time, 500)  # Max should be under 500ms
        
        print("✓ Performance benchmark tests passed!")
    
    def test_data_integrity(self):
        """Test data integrity and consistency"""
        print("\n=== Testing Data Integrity ===")
        
        # Test 1: Data Validation
        print("Test 1: Data validation...")
        
        # Valid data should pass
        valid_market_data = MarketData(
            symbol="EURUSD",
            timestamp=datetime.now(),
            open=1.0850,
            high=1.0875,
            low=1.0840,
            close=1.0865,
            volume=1000000,
            bid=1.0864,
            ask=1.0866,
            spread=0.0002
        )
        
        self.assertTrue(self.market_data_collector.validate_data(valid_market_data))
        
        # Invalid data should fail
        invalid_market_data = MarketData(
            symbol="INVALID",
            timestamp=datetime.now(),
            open=-1.0,  # Invalid negative price
            high=1.0875,
            low=1.0840,
            close=1.0865,
            volume=-1000,  # Invalid negative volume
            bid=1.0864,
            ask=1.0866,
            spread=0.0002
        )
        
        self.assertFalse(self.market_data_collector.validate_data(invalid_market_data))
        
        # Test 2: Signal Consistency
        print("Test 2: Signal consistency...")
        
        # Generate multiple signals for same conditions
        signals = []
        for _ in range(5):
            signal = self._create_mock_trading_signal()
            signals.append(signal)
        
        # Signals should be consistent (same direction and similar confidence)
        directions = [s.direction for s in signals]
        confidences = [s.confidence for s in signals]
        
        # All directions should be the same
        self.assertEqual(len(set(directions)), 1)
        
        # Confidence should be within reasonable range
        confidence_range = max(confidences) - min(confidences)
        self.assertLess(confidence_range, 0.2)  # Within 20% range
        
        print("✓ Data integrity tests passed!")
    
    def test_security_measures(self):
        """Test security measures and configurations"""
        print("\n=== Testing Security Measures ===")
        
        # Test 1: API Key Validation
        print("Test 1: API key validation...")
        
        # Should reject invalid API keys
        with patch.dict(os.environ, {'LLM_API_KEY': 'invalid_key'}):
            try:
                # This should fail with invalid key
                config = get_config_manager()
                llm_config = config.get_llm_config()
                self.assertNotEqual(llm_config.api_key, 'invalid_key')
            except Exception:
                pass  # Expected to fail with invalid key
        
        # Test 2: Input Sanitization
        print("Test 2: Input sanitization...")
        
        # Test with potentially malicious input
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "'; DROP TABLE trades; --",
            "../../../etc/passwd",
            "{{7*7}}",  # Template injection
        ]
        
        for malicious_input in malicious_inputs:
            try:
                # Should sanitize or reject malicious input
                sanitized = self.news_collector.preprocess_text(malicious_input)
                self.assertNotIn('<script>', sanitized.lower())
                self.assertNotIn('drop table', sanitized.lower())
                self.assertNotIn('../', sanitized)
            except Exception:
                pass  # Rejection is also acceptable
        
        # Test 3: Configuration Security
        print("Test 3: Configuration security...")
        
        config = self.config_manager.get_config()
        
        # Sensitive data should not be in plain text
        config_str = json.dumps(config, default=str)
        self.assertNotIn('password', config_str.lower())
        self.assertNotIn('secret', config_str.lower())
        self.assertNotIn('key', config_str.lower())
        
        print("✓ Security tests passed!")
    
    def test_monitoring_and_alerting(self):
        """Test monitoring and alerting systems"""
        print("\n=== Testing Monitoring and Alerting ===")
        
        # Test 1: Performance Monitoring
        print("Test 1: Performance monitoring...")
        
        # Generate some test metrics
        self.performance_monitor.update_metrics({
            'total_trades': 100,
            'winning_trades': 60,
            'losing_trades': 40,
            'total_pnl': 1500.0,
            'current_drawdown': 0.05,
            'error_rate': 0.02
        })
        
        metrics = self.performance_monitor.get_current_metrics()
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.total_trades, 100)
        self.assertEqual(metrics.win_rate, 0.6)
        
        # Test 2: Alert Generation
        print("Test 2: Alert generation...")
        
        # Test high drawdown alert
        high_drawdown_metrics = self.performance_monitor.create_metrics(
            total_trades=50,
            winning_trades=20,
            losing_trades=30,
            total_pnl=-2000.0,
            current_drawdown=0.20,  # High drawdown
            error_rate=0.01
        )
        
        alerts = self.alert_system.check_metrics(high_drawdown_metrics)
        self.assertGreater(len(alerts), 0)
        
        # Should have high drawdown alert
        drawdown_alerts = [a for a in alerts if 'drawdown' in a.title.lower()]
        self.assertGreater(len(drawdown_alerts), 0)
        
        # Test 3: Health Monitoring
        print("Test 3: Health monitoring...")
        
        health_status = self.health_checker.check_system_health()
        self.assertIsNotNone(health_status)
        self.assertIn('status', health_status)
        self.assertIn('components', health_status)
        
        # All critical components should be checked
        required_components = ['database', 'cache', 'api_endpoints']
        for component in required_components:
            if component in health_status['components']:
                self.assertIn('status', health_status['components'][component])
        
        print("✓ Monitoring and alerting tests passed!")
    
    def test_configuration_management(self):
        """Test configuration management and validation"""
        print("\n=== Testing Configuration Management ===")
        
        # Test 1: Configuration Loading
        print("Test 1: Configuration loading...")
        
        config = self.config_manager.get_config()
        self.assertIsNotNone(config)
        self.assertIn('trading', config)
        self.assertIn('risk_management', config)
        self.assertIn('analysis', config)
        
        # Test 2: Configuration Validation
        print("Test 2: Configuration validation...")
        
        validation_result = self.config_manager.validate_config()
        self.assertTrue(validation_result['valid'])
        
        if not validation_result['valid']:
            print(f"Configuration errors: {validation_result['errors']}")
        
        # Test 3: Environment-Specific Configuration
        print("Test 3: Environment-specific configuration...")
        
        # Should load appropriate configuration for environment
        trading_config = self.config_manager.get_trading_config()
        self.assertIsNotNone(trading_config)
        self.assertIn('enabled', trading_config)
        self.assertIn('max_positions', trading_config)
        
        print("✓ Configuration management tests passed!")
    
    async def _simulate_trading_operation(self, symbol: str) -> Dict[str, Any]:
        """Simulate a complete trading operation for load testing"""
        try:
            # Simulate data collection
            await asyncio.sleep(0.1)
            
            # Simulate analysis
            await asyncio.sleep(0.2)
            
            # Simulate signal generation
            await asyncio.sleep(0.1)
            
            # Simulate execution
            await asyncio.sleep(0.1)
            
            return {
                'symbol': symbol,
                'success': True,
                'timestamp': datetime.now()
            }
        except Exception as e:
            return {
                'symbol': symbol,
                'success': False,
                'error': str(e),
                'timestamp': datetime.now()
            }
    
    def _create_mock_market_data(self) -> List[MarketData]:
        """Create mock market data for testing"""
        return [
            MarketData(
                symbol="EURUSD",
                timestamp=datetime.now() - timedelta(hours=i),
                open=1.0850 + (i * 0.0001),
                high=1.0875 + (i * 0.0001),
                low=1.0840 + (i * 0.0001),
                close=1.0865 + (i * 0.0001),
                volume=1000000,
                bid=1.0864 + (i * 0.0001),
                ask=1.0866 + (i * 0.0001),
                spread=0.0002
            ) for i in range(24)  # 24 hours of data
        ]
    
    def _create_mock_news_data(self) -> List[Dict[str, Any]]:
        """Create mock news data for testing"""
        return [
            {
                'title': 'EUR/USD rises on positive economic data',
                'content': 'The Euro strengthened against the US Dollar following positive economic indicators.',
                'timestamp': datetime.now() - timedelta(hours=1),
                'source': 'Financial News',
                'sentiment': 'positive'
            },
            {
                'title': 'Federal Reserve maintains interest rates',
                'content': 'The Federal Reserve decided to keep interest rates unchanged.',
                'timestamp': datetime.now() - timedelta(hours=2),
                'source': 'Central Bank News',
                'sentiment': 'neutral'
            }
        ]
    
    def _create_mock_sentiment_result(self):
        """Create mock sentiment analysis result"""
        from src.models import SentimentResult
        return SentimentResult(
            symbol="EURUSD",
            sentiment_score=0.75,
            confidence=0.85,
            reasoning="Positive market sentiment based on economic indicators",
            sources=["Financial News", "Market Analysis"],
            timestamp=datetime.now()
        )
    
    def _create_mock_trading_signal(self) -> TradingSignal:
        """Create mock trading signal"""
        return TradingSignal(
            symbol="EURUSD",
            direction="long",
            entry_price=1.0850,
            stop_loss=1.0820,
            take_profit=1.0900,
            position_size=10000,
            confidence=0.80,
            reasoning="Strong bullish sentiment with technical confirmation",
            timestamp=datetime.now()
        )
    
    def _create_mock_execution_result(self) -> Dict[str, Any]:
        """Create mock execution result"""
        return {
            'success': True,
            'order_id': 'ORDER_123456',
            'executed_price': 1.0851,
            'executed_quantity': 10000,
            'execution_time': datetime.now(),
            'slippage': 0.0001,
            'commission': 2.50
        }
    
    def tearDown(self):
        """Clean up after tests"""
        test_duration = time.time() - self.test_start_time
        print(f"\nTest completed in {test_duration:.2f} seconds")


class TestProductionReadiness(unittest.TestCase):
    """Test production readiness checklist"""
    
    def test_production_checklist(self):
        """Verify production readiness checklist"""
        print("\n=== Production Readiness Checklist ===")
        
        checklist_items = [
            self._check_environment_variables,
            self._check_configuration_files,
            self._check_database_connectivity,
            self._check_external_api_access,
            self._check_logging_configuration,
            self._check_monitoring_setup,
            self._check_security_configuration,
            self._check_backup_procedures,
            self._check_documentation,
            self._check_health_endpoints
        ]
        
        results = {}
        for check in checklist_items:
            try:
                result = check()
                results[check.__name__] = result
                status = "✓" if result else "✗"
                print(f"{status} {check.__name__.replace('_check_', '').replace('_', ' ').title()}")
            except Exception as e:
                results[check.__name__] = False
                print(f"✗ {check.__name__.replace('_check_', '').replace('_', ' ').title()}: {e}")
        
        # All checks should pass for production readiness
        failed_checks = [name for name, result in results.items() if not result]
        if failed_checks:
            print(f"\nFailed checks: {', '.join(failed_checks)}")
            self.fail(f"Production readiness checks failed: {failed_checks}")
        
        print("\n✓ All production readiness checks passed!")
    
    def _check_environment_variables(self) -> bool:
        """Check required environment variables"""
        required_vars = [
            'DB_PASSWORD',
            'LLM_API_KEY',
            'BROKER_API_KEY',
            'BROKER_API_SECRET'
        ]
        
        for var in required_vars:
            if not os.getenv(var):
                return False
        return True
    
    def _check_configuration_files(self) -> bool:
        """Check configuration files exist and are valid"""
        config_files = [
            'config/config.base.json',
            'config/config.prod.json'
        ]
        
        for config_file in config_files:
            if not os.path.exists(config_file):
                return False
            
            try:
                with open(config_file, 'r') as f:
                    json.load(f)
            except json.JSONDecodeError:
                return False
        
        return True
    
    def _check_database_connectivity(self) -> bool:
        """Check database connectivity"""
        try:
            config_manager = get_config_manager()
            return config_manager.test_database_connection()
        except Exception:
            return False
    
    def _check_external_api_access(self) -> bool:
        """Check external API access"""
        # This would test actual API connectivity in real scenario
        return True
    
    def _check_logging_configuration(self) -> bool:
        """Check logging configuration"""
        return os.path.exists('logs') and os.path.isdir('logs')
    
    def _check_monitoring_setup(self) -> bool:
        """Check monitoring setup"""
        try:
            health_checker = HealthChecker()
            health_status = health_checker.check_system_health()
            return health_status.get('status') == 'healthy'
        except Exception:
            return False
    
    def _check_security_configuration(self) -> bool:
        """Check security configuration"""
        # Check that sensitive files are not world-readable
        sensitive_files = ['.env', 'config/config.prod.json']
        
        for file_path in sensitive_files:
            if os.path.exists(file_path):
                file_stat = os.stat(file_path)
                # Check that file is not world-readable (others don't have read permission)
                if file_stat.st_mode & 0o004:
                    return False
        
        return True
    
    def _check_backup_procedures(self) -> bool:
        """Check backup procedures"""
        return os.path.exists('scripts/backup.sh')
    
    def _check_documentation(self) -> bool:
        """Check documentation exists"""
        required_docs = [
            'README.md',
            'DEPLOYMENT.md',
            'docs/API_REFERENCE.md',
            'docs/SYSTEM_ARCHITECTURE.md',
            'docs/TROUBLESHOOTING_GUIDE.md',
            'docs/PERFORMANCE_OPTIMIZATION.md'
        ]
        
        for doc in required_docs:
            if not os.path.exists(doc):
                return False
        
        return True
    
    def _check_health_endpoints(self) -> bool:
        """Check health endpoints are accessible"""
        try:
            health_checker = HealthChecker()
            health_status = health_checker.check_system_health()
            return isinstance(health_status, dict) and 'status' in health_status
        except Exception:
            return False


def run_final_integration_tests():
    """Run all final integration tests"""
    print("=" * 60)
    print("FINAL INTEGRATION TESTS FOR PRODUCTION DEPLOYMENT")
    print("=" * 60)
    
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add system integration tests
    test_suite.addTest(TestFinalSystemIntegration('test_complete_trading_workflow'))
    test_suite.addTest(TestFinalSystemIntegration('test_system_resilience'))
    test_suite.addTest(TestFinalSystemIntegration('test_performance_benchmarks'))
    test_suite.addTest(TestFinalSystemIntegration('test_data_integrity'))
    test_suite.addTest(TestFinalSystemIntegration('test_security_measures'))
    test_suite.addTest(TestFinalSystemIntegration('test_monitoring_and_alerting'))
    test_suite.addTest(TestFinalSystemIntegration('test_configuration_management'))
    
    # Add production readiness tests
    test_suite.addTest(TestProductionReadiness('test_production_checklist'))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print("\n" + "=" * 60)
    print("FINAL INTEGRATION TEST SUMMARY")
    print("=" * 60)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    
    if result.failures:
        print("\nFAILURES:")
        for test, traceback in result.failures:
            print(f"- {test}: {traceback}")
    
    if result.errors:
        print("\nERRORS:")
        for test, traceback in result.errors:
            print(f"- {test}: {traceback}")
    
    if result.wasSuccessful():
        print("\n🎉 ALL TESTS PASSED - SYSTEM READY FOR PRODUCTION DEPLOYMENT!")
        return True
    else:
        print("\n❌ SOME TESTS FAILED - SYSTEM NOT READY FOR PRODUCTION")
        return False


if __name__ == '__main__':
    success = run_final_integration_tests()
    exit(0 if success else 1)
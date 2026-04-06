"""Unit tests for the monitoring and alerting system"""

import asyncio
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, AsyncMock
import tempfile
import json

from src.monitoring.performance_monitor import (
    PerformanceMonitor,
    PerformanceMetrics,
    MetricType,
    MetricValue
)
from src.monitoring.alert_system import (
    AlertSystem,
    Alert,
    AlertLevel,
    AlertChannel,
    AlertRule
)


class TestPerformanceMetrics(unittest.TestCase):
    """Test PerformanceMetrics functionality"""
    
    def test_metrics_creation(self):
        """Test metrics creation with default values"""
        metrics = PerformanceMetrics()
        
        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.winning_trades, 0)
        self.assertEqual(metrics.total_pnl, 0.0)
        self.assertEqual(metrics.win_rate, 0.0)
    
    def test_metrics_to_dict(self):
        """Test metrics conversion to dictionary"""
        metrics = PerformanceMetrics(
            total_trades=10,
            winning_trades=6,
            total_pnl=150.0,
            win_rate=0.6
        )
        
        result = metrics.to_dict()
        
        self.assertIn('trading', result)
        self.assertIn('system', result)
        self.assertIn('signals', result)
        self.assertIn('risk', result)
        
        self.assertEqual(result['trading']['total_trades'], 10)
        self.assertEqual(result['trading']['winning_trades'], 6)
        self.assertEqual(result['trading']['total_pnl'], 150.0)
        self.assertEqual(result['trading']['win_rate'], 0.6)


class TestPerformanceMonitor(unittest.TestCase):
    """Test PerformanceMonitor functionality"""
    
    def setUp(self):
        self.monitor = PerformanceMonitor(
            update_interval=1,  # 1 second for testing
            history_size=100,
            enable_system_metrics=False  # Disable to avoid psutil dependency
        )
    
    def tearDown(self):
        if self.monitor._running:
            self.monitor.stop_monitoring()
    
    def test_monitor_initialization(self):
        """Test monitor initialization"""
        self.assertFalse(self.monitor._running)
        self.assertEqual(self.monitor.update_interval, 1)
        self.assertEqual(self.monitor.history_size, 100)
        self.assertFalse(self.monitor.enable_system_metrics)
    
    def test_record_metric(self):
        """Test recording metrics"""
        self.monitor.record_metric("test_metric", 42.0, MetricType.GAUGE)
        
        # Check that metric was recorded
        history = self.monitor.get_metric_history("test_metric")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].value, 42.0)
        self.assertIsInstance(history[0].timestamp, datetime)
    
    def test_record_trade_result_win(self):
        """Test recording winning trade"""
        self.monitor.record_trade_result(50.0, True)
        
        metrics = self.monitor.get_current_metrics()
        self.assertEqual(metrics.total_trades, 1)
        self.assertEqual(metrics.winning_trades, 1)
        self.assertEqual(metrics.losing_trades, 0)
        self.assertEqual(metrics.total_pnl, 50.0)
        self.assertEqual(metrics.average_win, 50.0)
        self.assertEqual(metrics.win_rate, 1.0)
    
    def test_record_trade_result_loss(self):
        """Test recording losing trade"""
        self.monitor.record_trade_result(-25.0, False)
        
        metrics = self.monitor.get_current_metrics()
        self.assertEqual(metrics.total_trades, 1)
        self.assertEqual(metrics.winning_trades, 0)
        self.assertEqual(metrics.losing_trades, 1)
        self.assertEqual(metrics.total_pnl, -25.0)
        self.assertEqual(metrics.average_loss, -25.0)
        self.assertEqual(metrics.win_rate, 0.0)
    
    def test_record_multiple_trades(self):
        """Test recording multiple trades and calculating averages"""
        # Record winning trades
        self.monitor.record_trade_result(100.0, True)
        self.monitor.record_trade_result(50.0, True)
        
        # Record losing trades
        self.monitor.record_trade_result(-30.0, False)
        self.monitor.record_trade_result(-20.0, False)
        
        metrics = self.monitor.get_current_metrics()
        self.assertEqual(metrics.total_trades, 4)
        self.assertEqual(metrics.winning_trades, 2)
        self.assertEqual(metrics.losing_trades, 2)
        self.assertEqual(metrics.total_pnl, 100.0)
        self.assertEqual(metrics.average_win, 75.0)  # (100 + 50) / 2
        self.assertEqual(metrics.average_loss, -25.0)  # (-30 + -20) / 2
        self.assertEqual(metrics.win_rate, 0.5)
    
    def test_record_signal_events(self):
        """Test recording signal generation and execution"""
        self.monitor.record_signal_generated(0.8)
        self.monitor.record_signal_generated(0.6)
        self.monitor.record_signal_executed()
        
        metrics = self.monitor.get_current_metrics()
        self.assertEqual(metrics.signals_generated, 2)
        self.assertEqual(metrics.signals_executed, 1)
        self.assertEqual(metrics.average_signal_confidence, 0.7)  # (0.8 + 0.6) / 2
        self.assertEqual(metrics.signal_accuracy, 0.5)  # 1 executed / 2 generated
    
    def test_record_api_call(self):
        """Test recording API calls"""
        self.monitor.record_api_call("/api/test", 0.5, True)
        self.monitor.record_api_call("/api/test", 1.0, True)
        self.monitor.record_api_call("/api/test", 2.0, False)  # Failed call
        
        metrics = self.monitor.get_current_metrics()
        self.assertEqual(metrics.average_response_time, 1.17, places=2)  # (0.5 + 1.0 + 2.0) / 3
        self.assertEqual(metrics.error_rate, 1/3, places=2)  # 1 error out of 3 calls
    
    def test_get_metric_history_with_duration(self):
        """Test getting metric history with time filter"""
        # Record metrics at different times
        self.monitor.record_metric("test_metric", 1.0)
        
        # Get history for last hour
        history = self.monitor.get_metric_history("test_metric", timedelta(hours=1))
        self.assertEqual(len(history), 1)
        
        # Get history for last second (should be empty if we wait)
        import time
        time.sleep(0.1)
        history = self.monitor.get_metric_history("test_metric", timedelta(seconds=0.05))
        self.assertEqual(len(history), 0)
    
    def test_get_system_health(self):
        """Test system health assessment"""
        # Set up some metrics
        self.monitor.record_trade_result(100.0, True)
        self.monitor.record_api_call("/api/test", 1.0, True)
        
        health = self.monitor.get_system_health()
        
        self.assertIn('status', health)
        self.assertIn('issues', health)
        self.assertIn('metrics', health)
        self.assertIn('timestamp', health)
        self.assertEqual(health['status'], 'healthy')
        self.assertEqual(len(health['issues']), 0)
    
    def test_get_system_health_with_issues(self):
        """Test system health with issues detected"""
        # Create high error rate
        for _ in range(10):
            self.monitor.record_api_call("/api/test", 1.0, False)  # All failed
        
        health = self.monitor.get_system_health()
        
        self.assertIn(health['status'], ['degraded', 'warning'])
        self.assertGreater(len(health['issues']), 0)
        self.assertTrue(any('error rate' in issue.lower() for issue in health['issues']))


class TestAlert(unittest.TestCase):
    """Test Alert functionality"""
    
    def test_alert_creation(self):
        """Test alert creation"""
        alert = Alert(
            id="test_alert_1",
            level=AlertLevel.WARNING,
            title="Test Alert",
            message="This is a test alert",
            component="TEST"
        )
        
        self.assertEqual(alert.id, "test_alert_1")
        self.assertEqual(alert.level, AlertLevel.WARNING)
        self.assertEqual(alert.title, "Test Alert")
        self.assertEqual(alert.message, "This is a test alert")
        self.assertEqual(alert.component, "TEST")
        self.assertFalse(alert.acknowledged)
        self.assertFalse(alert.resolved)
    
    def test_alert_to_dict(self):
        """Test alert conversion to dictionary"""
        alert = Alert(
            id="test_alert_1",
            level=AlertLevel.ERROR,
            title="Test Alert",
            message="This is a test alert",
            component="TEST",
            channels=[AlertChannel.LOG, AlertChannel.EMAIL]
        )
        
        result = alert.to_dict()
        
        self.assertEqual(result['id'], "test_alert_1")
        self.assertEqual(result['level'], "error")
        self.assertEqual(result['title'], "Test Alert")
        self.assertEqual(result['channels'], ["log", "email"])
        self.assertFalse(result['acknowledged'])
        self.assertFalse(result['resolved'])


class TestAlertRule(unittest.TestCase):
    """Test AlertRule functionality"""
    
    def test_alert_rule_creation(self):
        """Test alert rule creation"""
        rule = AlertRule(
            name="test_rule",
            condition=lambda m: m.error_rate > 0.1,
            level=AlertLevel.ERROR,
            message_template="Error rate too high: {error_rate}",
            channels=[AlertChannel.LOG]
        )
        
        self.assertEqual(rule.name, "test_rule")
        self.assertEqual(rule.level, AlertLevel.ERROR)
        self.assertTrue(rule.enabled)
        self.assertEqual(rule.cooldown_minutes, 5)
        self.assertEqual(rule.max_alerts_per_hour, 10)
    
    def test_alert_rule_condition(self):
        """Test alert rule condition evaluation"""
        rule = AlertRule(
            name="high_error_rate",
            condition=lambda m: m.error_rate > 0.1,
            level=AlertLevel.ERROR,
            message_template="Error rate: {error_rate}",
            channels=[AlertChannel.LOG]
        )
        
        # Test with low error rate
        metrics_low = PerformanceMetrics(error_rate=0.05)
        self.assertFalse(rule.condition(metrics_low))
        
        # Test with high error rate
        metrics_high = PerformanceMetrics(error_rate=0.15)
        self.assertTrue(rule.condition(metrics_high))


class TestAlertSystem(unittest.TestCase):
    """Test AlertSystem functionality"""
    
    def setUp(self):
        self.alert_system = AlertSystem()
        
        # Disable email and webhook channels in default rules for testing
        for rule in self.alert_system._alert_rules.values():
            rule.channels = [AlertChannel.LOG]  # Only use LOG channel for testing
    
    def test_alert_system_initialization(self):
        """Test alert system initialization"""
        self.assertIsInstance(self.alert_system._alert_rules, dict)
        self.assertGreater(len(self.alert_system._alert_rules), 0)  # Should have default rules
        
        # Check that default rules exist
        self.assertIn("high_error_rate", self.alert_system._alert_rules)
        self.assertIn("high_drawdown", self.alert_system._alert_rules)
    
    def test_add_alert_rule(self):
        """Test adding custom alert rule"""
        rule = AlertRule(
            name="custom_rule",
            condition=lambda m: m.total_trades > 100,
            level=AlertLevel.INFO,
            message_template="Many trades: {total_trades}",
            channels=[AlertChannel.LOG]
        )
        
        self.alert_system.add_alert_rule(rule)
        
        self.assertIn("custom_rule", self.alert_system._alert_rules)
        self.assertEqual(self.alert_system._alert_rules["custom_rule"], rule)
    
    def test_remove_alert_rule(self):
        """Test removing alert rule"""
        # Add a rule first
        rule = AlertRule(
            name="temp_rule",
            condition=lambda m: False,
            level=AlertLevel.INFO,
            message_template="Test",
            channels=[AlertChannel.LOG]
        )
        self.alert_system.add_alert_rule(rule)
        
        # Remove the rule
        result = self.alert_system.remove_alert_rule("temp_rule")
        
        self.assertTrue(result)
        self.assertNotIn("temp_rule", self.alert_system._alert_rules)
        
        # Try to remove non-existent rule
        result = self.alert_system.remove_alert_rule("non_existent")
        self.assertFalse(result)
    
    def test_check_metrics_no_alerts(self):
        """Test checking metrics with no alerts triggered"""
        metrics = PerformanceMetrics(
            error_rate=0.01,  # Low error rate
            current_drawdown=0.05,  # Low drawdown
            average_response_time=1.0  # Fast response
        )
        
        alerts = self.alert_system.check_metrics(metrics)
        
        self.assertEqual(len(alerts), 0)
    
    def test_check_metrics_with_alerts(self):
        """Test checking metrics with alerts triggered"""
        metrics = PerformanceMetrics(
            error_rate=0.15,  # High error rate (> 0.1)
            current_drawdown=0.20,  # High drawdown (> 0.15)
            average_response_time=15.0  # Slow response (> 10.0)
        )
        
        alerts = self.alert_system.check_metrics(metrics)
        
        # Should trigger multiple alerts
        self.assertGreater(len(alerts), 0)
        
        # Check that alerts were created for the right conditions
        alert_names = [alert.title for alert in alerts]
        self.assertTrue(any("error rate" in name.lower() for name in alert_names))
        self.assertTrue(any("drawdown" in name.lower() for name in alert_names))
    
    def test_rate_limiting(self):
        """Test alert rate limiting"""
        # Create metrics that will trigger an alert
        metrics = PerformanceMetrics(error_rate=0.15)
        
        # First check should create alert
        alerts1 = self.alert_system.check_metrics(metrics)
        self.assertGreater(len(alerts1), 0)
        
        # Immediate second check should not create alert (cooldown)
        alerts2 = self.alert_system.check_metrics(metrics)
        self.assertEqual(len(alerts2), 0)
    
    def test_create_manual_alert(self):
        """Test creating manual alerts"""
        alert = self.alert_system.create_manual_alert(
            level=AlertLevel.WARNING,
            title="Manual Test Alert",
            message="This is a manual test alert",
            component="TEST",
            channels=[AlertChannel.LOG]
        )
        
        self.assertEqual(alert.level, AlertLevel.WARNING)
        self.assertEqual(alert.title, "Manual Test Alert")
        self.assertEqual(alert.component, "TEST")
        self.assertIn(alert.id, self.alert_system._active_alerts)
    
    def test_acknowledge_alert(self):
        """Test acknowledging alerts"""
        # Create a manual alert
        alert = self.alert_system.create_manual_alert(
            level=AlertLevel.INFO,
            title="Test Alert",
            message="Test message",
            channels=[AlertChannel.LOG]  # Use LOG only to avoid email/webhook issues
        )
        
        # Acknowledge the alert
        result = self.alert_system.acknowledge_alert(alert.id)
        
        self.assertTrue(result)
        self.assertTrue(self.alert_system._active_alerts[alert.id].acknowledged)
        
        # Try to acknowledge non-existent alert
        result = self.alert_system.acknowledge_alert("non_existent")
        self.assertFalse(result)
    
    def test_resolve_alert(self):
        """Test resolving alerts"""
        # Create a manual alert
        alert = self.alert_system.create_manual_alert(
            level=AlertLevel.INFO,
            title="Test Alert",
            message="Test message",
            channels=[AlertChannel.LOG]  # Use LOG only to avoid email/webhook issues
        )
        
        # Resolve the alert
        result = self.alert_system.resolve_alert(alert.id)
        
        self.assertTrue(result)
        self.assertNotIn(alert.id, self.alert_system._active_alerts)
        
        # Check that it's marked as resolved in history
        history = self.alert_system.get_alert_history()
        resolved_alert = next((a for a in history if a.id == alert.id), None)
        self.assertIsNotNone(resolved_alert)
        self.assertTrue(resolved_alert.resolved)
        self.assertTrue(resolved_alert.acknowledged)
    
    def test_get_active_alerts(self):
        """Test getting active alerts"""
        # Initially no active alerts
        active = self.alert_system.get_active_alerts()
        initial_count = len(active)
        
        # Create some alerts
        alert1 = self.alert_system.create_manual_alert(
            level=AlertLevel.INFO,
            title="Alert 1",
            message="Message 1",
            channels=[AlertChannel.LOG]  # Use LOG only to avoid email/webhook issues
        )
        alert2 = self.alert_system.create_manual_alert(
            level=AlertLevel.WARNING,
            title="Alert 2",
            message="Message 2",
            channels=[AlertChannel.LOG]  # Use LOG only to avoid email/webhook issues
        )
        
        # Check active alerts
        active = self.alert_system.get_active_alerts()
        self.assertEqual(len(active), initial_count + 2)
        
        alert_ids = [alert.id for alert in active]
        self.assertIn(alert1.id, alert_ids)
        self.assertIn(alert2.id, alert_ids)
    
    def test_get_alert_history(self):
        """Test getting alert history"""
        # Create some alerts
        alert1 = self.alert_system.create_manual_alert(
            level=AlertLevel.INFO,
            title="Alert 1",
            message="Message 1",
            channels=[AlertChannel.LOG]  # Use LOG only to avoid email/webhook issues
        )
        alert2 = self.alert_system.create_manual_alert(
            level=AlertLevel.ERROR,
            title="Alert 2",
            message="Message 2",
            channels=[AlertChannel.LOG]  # Use LOG only to avoid email/webhook issues
        )
        
        # Get all history
        history = self.alert_system.get_alert_history()
        self.assertGreaterEqual(len(history), 2)
        
        # Get only error level alerts
        error_history = self.alert_system.get_alert_history(level=AlertLevel.ERROR)
        error_ids = [alert.id for alert in error_history]
        self.assertIn(alert2.id, error_ids)
        self.assertNotIn(alert1.id, error_ids)
    
    def test_get_alert_summary(self):
        """Test getting alert summary"""
        # Create some alerts with LOG channel only to avoid email/webhook issues
        self.alert_system.create_manual_alert(
            level=AlertLevel.INFO,
            title="Info Alert",
            message="Info message",
            channels=[AlertChannel.LOG]  # Explicitly use LOG only
        )
        self.alert_system.create_manual_alert(
            level=AlertLevel.ERROR,
            title="Error Alert",
            message="Error message",
            channels=[AlertChannel.LOG]  # Explicitly use LOG only
        )
        
        summary = self.alert_system.get_alert_summary()
        
        self.assertIn('active_alerts', summary)
        self.assertIn('active_by_level', summary)
        self.assertIn('total_rules', summary)
        self.assertIn('enabled_rules', summary)
        self.assertIn('recent_alerts_24h', summary)
        self.assertIn('timestamp', summary)
        
        self.assertGreaterEqual(summary['active_alerts'], 2)
        self.assertGreater(summary['total_rules'], 0)


if __name__ == "__main__":
    unittest.main()
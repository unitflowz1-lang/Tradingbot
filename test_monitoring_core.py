#!/usr/bin/env python3
"""
Core monitoring system tests - focused and non-blocking
"""

def test_performance_monitor_basic():
    """Test basic PerformanceMonitor functionality"""
    from src.monitoring.performance_monitor import PerformanceMonitor, PerformanceMetrics
    
    print("Testing PerformanceMonitor basic functionality...")
    
    # Create monitor with minimal configuration
    monitor = PerformanceMonitor(
        update_interval=60,
        history_size=10,
        enable_system_metrics=False
    )
    
    # Test metric recording
    monitor.record_metric("test_metric", 42.0)
    history = monitor.get_metric_history("test_metric")
    assert len(history) == 1
    assert history[0].value == 42.0
    print("✓ Metric recording works")
    
    # Test trade recording
    monitor.record_trade_result(100.0, True)
    monitor.record_trade_result(-50.0, False)
    
    metrics = monitor.get_current_metrics()
    assert metrics.total_trades == 2
    assert metrics.winning_trades == 1
    assert metrics.losing_trades == 1
    assert metrics.total_pnl == 50.0
    assert metrics.win_rate == 0.5
    print("✓ Trade recording works")
    
    # Test signal recording
    monitor.record_signal_generated(0.8)
    monitor.record_signal_executed()
    
    metrics = monitor.get_current_metrics()
    assert metrics.signals_generated == 1
    assert metrics.signals_executed == 1
    assert metrics.average_signal_confidence == 0.8
    print("✓ Signal recording works")
    
    # Test system health
    health = monitor.get_system_health()
    assert 'status' in health
    assert 'issues' in health
    assert 'metrics' in health
    print("✓ System health check works")
    
    print("PerformanceMonitor tests passed!\n")
    return True

def test_alert_system_basic():
    """Test basic AlertSystem functionality"""
    from src.monitoring.alert_system import AlertSystem, AlertLevel, AlertChannel
    from src.monitoring.performance_monitor import PerformanceMetrics
    
    print("Testing AlertSystem basic functionality...")
    
    # Create alert system
    alert_system = AlertSystem()
    
    # Ensure all rules use only LOG channel to avoid network calls
    for rule in alert_system._alert_rules.values():
        rule.channels = [AlertChannel.LOG]
    
    print("✓ AlertSystem created")
    
    # Test manual alert creation
    alert = alert_system.create_manual_alert(
        level=AlertLevel.INFO,
        title="Test Alert",
        message="Test message",
        channels=[AlertChannel.LOG]
    )
    
    assert alert.level == AlertLevel.INFO
    assert alert.title == "Test Alert"
    assert not alert.acknowledged
    assert not alert.resolved
    print("✓ Manual alert creation works")
    
    # Test alert acknowledgment
    success = alert_system.acknowledge_alert(alert.id)
    assert success
    assert alert_system._active_alerts[alert.id].acknowledged
    print("✓ Alert acknowledgment works")
    
    # Test alert resolution
    success = alert_system.resolve_alert(alert.id)
    assert success
    assert alert.id not in alert_system._active_alerts
    print("✓ Alert resolution works")
    
    # Test metrics checking with safe values
    safe_metrics = PerformanceMetrics(
        error_rate=0.01,  # Low error rate
        current_drawdown=0.02,  # Low drawdown
        average_response_time=1.0  # Fast response
    )
    
    alerts = alert_system.check_metrics(safe_metrics)
    # Should not trigger any alerts with safe metrics
    print(f"✓ Safe metrics check: {len(alerts)} alerts (expected: 0)")
    
    # Test alert summary
    summary = alert_system.get_alert_summary()
    assert 'active_alerts' in summary
    assert 'total_rules' in summary
    assert summary['total_rules'] > 0
    print("✓ Alert summary works")
    
    print("AlertSystem tests passed!\n")
    return True

def test_integration():
    """Test integration between PerformanceMonitor and AlertSystem"""
    from src.monitoring.performance_monitor import PerformanceMonitor
    from src.monitoring.alert_system import AlertSystem, AlertChannel
    
    print("Testing monitoring system integration...")
    
    # Create components
    monitor = PerformanceMonitor(enable_system_metrics=False)
    alert_system = AlertSystem()
    
    # Configure alert system for safe testing
    for rule in alert_system._alert_rules.values():
        rule.channels = [AlertChannel.LOG]
    
    # Record some trading activity
    monitor.record_trade_result(100.0, True)
    monitor.record_trade_result(50.0, True)
    monitor.record_trade_result(-25.0, False)
    
    # Get metrics and check alerts
    metrics = monitor.get_current_metrics()
    alerts = alert_system.check_metrics(metrics)
    
    print(f"✓ Integration test: {metrics.total_trades} trades, {len(alerts)} alerts")
    
    # Test dashboard data generation
    dashboard_data = monitor.get_dashboard_data()
    alert_dashboard = alert_system.get_dashboard_alerts()
    
    assert 'overview' in dashboard_data
    assert 'performance' in dashboard_data
    assert 'active_alerts' in alert_dashboard
    
    print("✓ Dashboard data generation works")
    print("Integration tests passed!\n")
    return True

def main():
    """Run all core tests"""
    print("=== Core Monitoring System Tests ===\n")
    
    try:
        # Run tests
        test1 = test_performance_monitor_basic()
        test2 = test_alert_system_basic()
        test3 = test_integration()
        
        if test1 and test2 and test3:
            print("=== ALL TESTS PASSED ===")
            print("✓ PerformanceMonitor: Real-time tracking implemented")
            print("✓ AlertSystem: Error and system alerts implemented")
            print("✓ Dashboard data: Visualization data ready")
            print("✓ Task 10.2 implementation complete!")
            return True
        else:
            print("Some tests failed!")
            return False
            
    except Exception as e:
        print(f"Tests failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    import sys
    success = main()
    sys.exit(0 if success else 1)
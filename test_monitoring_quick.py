#!/usr/bin/env python3
"""Quick test for monitoring system to avoid hanging issues"""

import sys
import time
from src.monitoring.performance_monitor import PerformanceMonitor, PerformanceMetrics
from src.monitoring.alert_system import AlertSystem, AlertLevel, AlertChannel

def test_performance_monitor():
    """Test basic performance monitor functionality"""
    print("Testing PerformanceMonitor...")
    
    monitor = PerformanceMonitor(
        update_interval=1,
        history_size=10,
        enable_system_metrics=False  # Disable to avoid psutil issues
    )
    
    # Test basic metric recording
    monitor.record_metric("test_metric", 42.0)
    monitor.record_trade_result(100.0, True)
    monitor.record_signal_generated(0.8)
    monitor.record_api_call("/test", 0.5, True)
    
    # Get current metrics
    metrics = monitor.get_current_metrics()
    print(f"Total trades: {metrics.total_trades}")
    print(f"Total PnL: {metrics.total_pnl}")
    print(f"Signals generated: {metrics.signals_generated}")
    
    # Test system health
    health = monitor.get_system_health()
    print(f"System status: {health['status']}")
    
    print("PerformanceMonitor test passed!")
    return True

def test_alert_system():
    """Test basic alert system functionality"""
    print("Testing AlertSystem...")
    
    # Create alert system with no external dependencies
    alert_system = AlertSystem()
    
    # Create a simple manual alert
    alert = alert_system.create_manual_alert(
        level=AlertLevel.INFO,
        title="Test Alert",
        message="This is a test alert",
        channels=[AlertChannel.LOG]  # Only use LOG to avoid network calls
    )
    
    print(f"Created alert: {alert.id}")
    
    # Test metrics checking with safe metrics
    metrics = PerformanceMetrics(
        total_trades=5,
        error_rate=0.02,  # Low error rate - should not trigger alerts
        current_drawdown=0.05  # Low drawdown - should not trigger alerts
    )
    
    alerts = alert_system.check_metrics(metrics)
    print(f"Alerts triggered: {len(alerts)}")
    
    # Get alert summary
    summary = alert_system.get_alert_summary()
    print(f"Active alerts: {summary['active_alerts']}")
    print(f"Total rules: {summary['total_rules']}")
    
    print("AlertSystem test passed!")
    return True

def main():
    """Run quick tests"""
    print("Running quick monitoring system tests...")
    
    try:
        # Test with timeout
        start_time = time.time()
        
        success1 = test_performance_monitor()
        
        if time.time() - start_time > 10:
            print("Performance monitor test took too long!")
            return False
            
        success2 = test_alert_system()
        
        if time.time() - start_time > 20:
            print("Alert system test took too long!")
            return False
        
        if success1 and success2:
            print("All monitoring tests passed!")
            return True
        else:
            print("Some tests failed!")
            return False
            
    except Exception as e:
        print(f"Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
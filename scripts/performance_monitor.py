#!/usr/bin/env python3
"""
Performance Monitoring Script

Monitors system performance and generates reports.
"""

import time
import psutil
import json
from datetime import datetime

def collect_metrics():
    """Collect system performance metrics"""
    return {
        'timestamp': datetime.now().isoformat(),
        'cpu_percent': psutil.cpu_percent(interval=1),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage('.').percent,
        'network_io': dict(psutil.net_io_counters()._asdict()),
        'process_count': len(psutil.pids())
    }

def main():
    """Main monitoring loop"""
    print("Starting performance monitoring...")
    
    while True:
        metrics = collect_metrics()
        
        # Log metrics
        with open('logs/performance_metrics.json', 'a') as f:
            f.write(json.dumps(metrics) + '\n')
        
        # Check for alerts
        if metrics['cpu_percent'] > 80:
            print(f"WARNING: High CPU usage: {metrics['cpu_percent']:.1f}%")
        
        if metrics['memory_percent'] > 90:
            print(f"WARNING: High memory usage: {metrics['memory_percent']:.1f}%")
        
        time.sleep(60)  # Monitor every minute

if __name__ == '__main__':
    main()

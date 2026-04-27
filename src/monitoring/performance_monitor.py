"""Real-time performance monitoring for the AI Forex Trading Bot"""

import asyncio
import json
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Deque
from threading import Lock
import statistics

import psutil
from .logging_system import StructuredLogger, LogContext


class MetricType(Enum):
    """Types of metrics that can be monitored"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    TIMER = "timer"


@dataclass
class MetricValue:
    """A single metric value with timestamp"""
    value: float
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)


@dataclass
class PerformanceMetrics:
    """Container for performance metrics"""
    # Trading metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    win_rate: float = 0.0
    average_win: float = 0.0
    average_loss: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    
    # System metrics
    api_calls_per_minute: float = 0.0
    average_response_time: float = 0.0
    error_rate: float = 0.0
    memory_usage_mb: float = 0.0
    cpu_usage_percent: float = 0.0
    
    # Signal metrics
    signals_generated: int = 0
    signals_executed: int = 0
    signal_accuracy: float = 0.0
    average_signal_confidence: float = 0.0
    
    # Risk metrics
    current_exposure: float = 0.0
    max_position_size: float = 0.0
    risk_per_trade: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary"""
        return {
            'trading': {
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'total_pnl': self.total_pnl,
                'unrealized_pnl': self.unrealized_pnl,
                'win_rate': self.win_rate,
                'average_win': self.average_win,
                'average_loss': self.average_loss,
                'profit_factor': self.profit_factor,
                'sharpe_ratio': self.sharpe_ratio,
                'max_drawdown': self.max_drawdown,
                'current_drawdown': self.current_drawdown
            },
            'system': {
                'api_calls_per_minute': self.api_calls_per_minute,
                'average_response_time': self.average_response_time,
                'error_rate': self.error_rate,
                'memory_usage_mb': self.memory_usage_mb,
                'cpu_usage_percent': self.cpu_usage_percent
            },
            'signals': {
                'signals_generated': self.signals_generated,
                'signals_executed': self.signals_executed,
                'signal_accuracy': self.signal_accuracy,
                'average_signal_confidence': self.average_signal_confidence
            },
            'risk': {
                'current_exposure': self.current_exposure,
                'max_position_size': self.max_position_size,
                'risk_per_trade': self.risk_per_trade
            }
        }


class PerformanceMonitor:
    """Real-time performance monitoring system"""
    
    def __init__(self, 
                 update_interval: int = 60,  # seconds
                 history_size: int = 1000,
                 enable_system_metrics: bool = True):
        self.update_interval = update_interval
        self.history_size = history_size
        self.enable_system_metrics = enable_system_metrics
        
        # Metrics storage
        self._metrics: Dict[str, Deque[MetricValue]] = defaultdict(
            lambda: deque(maxlen=history_size)
        )
        self._counters: Dict[str, float] = defaultdict(float)
        self._gauges: Dict[str, float] = defaultdict(float)
        self._timers: Dict[str, List[float]] = defaultdict(list)
        
        # Thread safety
        self._lock = Lock()
        
        # Current metrics snapshot
        self._current_metrics = PerformanceMetrics()
        
        # FIX: Counter for periodic logging (reduces console spam)
        self._metric_update_count = 0
        
        # Monitoring state
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        # Logger - use simple logging to avoid potential issues
        import logging
        self.logger = logging.getLogger("PERFORMANCE_MONITOR")
        
        # Callbacks for metric updates
        self._metric_callbacks: Dict[str, List[Callable]] = defaultdict(list)
    
    def start_monitoring(self) -> None:
        """Start the performance monitoring loop"""
        if self._running:
            return
        
        self._running = True
        self.logger.info("Starting performance monitoring")
        
        # Start monitoring loop in background
        loop = asyncio.get_event_loop()
        self._monitor_task = loop.create_task(self._monitoring_loop())
    
    def stop_monitoring(self) -> None:
        """Stop the performance monitoring loop"""
        if not self._running:
            return
        
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
        
        self.logger.info("Stopped performance monitoring")
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop"""
        while self._running:
            try:
                await self._update_metrics()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.update_interval)
    
    async def _update_metrics(self) -> None:
        """Update all metrics"""
        with self._lock:
            # Update system metrics if enabled
            if self.enable_system_metrics:
                self._update_system_metrics()
            
            # Calculate derived metrics
            self._calculate_trading_metrics()
            self._calculate_signal_metrics()
            self._calculate_risk_metrics()
            
            # FIX: Log at DEBUG level instead of INFO to reduce console spam
            # Only log at INFO level every 10 cycles or if there's a major change
            self._metric_update_count += 1
            if self._metric_update_count % 10 == 0:
                self.logger.info(
                    "[PERF_METRICS] Performance metrics updated (cycle %d) | "
                    "WinRate: %.1f%% | Total Trades: %d | Avg RR: %.2f",
                    self._metric_update_count,
                    getattr(self, 'current_metrics', {}).get('win_rate', 0.0) * 100,
                    getattr(self, 'current_metrics', {}).get('total_trades', 0),
                    getattr(self, 'current_metrics', {}).get('avg_rr', 0.0),
                )
            else:
                self.logger.debug("Performance metrics updated (cycle %d)", self._metric_update_count)
            
            # Trigger callbacks
            self._trigger_metric_callbacks()
    
    def _update_system_metrics(self) -> None:
        """Update system performance metrics"""
        try:
            # Memory usage: Track current process instead of system total
            process = psutil.Process()
            memory_info = process.memory_info()
            self._current_metrics.memory_usage_mb = memory_info.rss / (1024 * 1024)
            
            # CPU usage (non-blocking for this process)
            self._current_metrics.cpu_usage_percent = process.cpu_percent(interval=None)
            
        except ImportError:
            # psutil not available, skip system metrics
            pass
        except Exception as e:
            # Handle any psutil errors gracefully
            self.logger.debug(f"Error updating system metrics: {e}")
            pass
    
    def _calculate_trading_metrics(self) -> None:
        """Calculate trading performance metrics"""
        # Win rate
        total_trades = self._current_metrics.total_trades
        if total_trades > 0:
            self._current_metrics.win_rate = (
                self._current_metrics.winning_trades / total_trades
            )
        
        # Profit factor
        total_wins = self._current_metrics.winning_trades * self._current_metrics.average_win
        total_losses = abs(self._current_metrics.losing_trades * self._current_metrics.average_loss)
        
        if total_losses > 0:
            self._current_metrics.profit_factor = total_wins / total_losses
    
    def _calculate_signal_metrics(self) -> None:
        """Calculate signal performance metrics"""
        if self._current_metrics.signals_generated > 0:
            self._current_metrics.signal_accuracy = (
                self._current_metrics.signals_executed / 
                self._current_metrics.signals_generated
            )
    
    def _calculate_risk_metrics(self) -> None:
        """Calculate risk metrics"""
        # Current drawdown calculation would need historical equity data
        # This is a simplified version
        if self._current_metrics.total_pnl < 0:
            self._current_metrics.current_drawdown = abs(self._current_metrics.total_pnl)
            if self._current_metrics.current_drawdown > self._current_metrics.max_drawdown:
                self._current_metrics.max_drawdown = self._current_metrics.current_drawdown
    
    def _trigger_metric_callbacks(self) -> None:
        """Trigger registered metric callbacks"""
        for metric_name, callbacks in self._metric_callbacks.items():
            for callback in callbacks:
                try:
                    callback(self._current_metrics)
                except Exception as e:
                    self.logger.error(f"Error in metric callback for {metric_name}: {e}")
    
    def record_metric(self, 
                     name: str, 
                     value: float, 
                     metric_type: MetricType = MetricType.GAUGE,
                     labels: Optional[Dict[str, str]] = None) -> None:
        """Record a metric value"""
        timestamp = datetime.now(timezone.utc)
        labels = labels or {}
        
        with self._lock:
            metric_value = MetricValue(value, timestamp, labels)
            self._metrics[name].append(metric_value)
            
            # Update appropriate storage based on type
            if metric_type == MetricType.COUNTER:
                self._counters[name] += value
            elif metric_type == MetricType.GAUGE:
                self._gauges[name] = value
            elif metric_type == MetricType.TIMER:
                self._timers[name].append(value)
                # Keep only recent timer values
                if len(self._timers[name]) > 100:
                    self._timers[name] = self._timers[name][-100:]
        
        self.logger.debug(f"Recorded metric: {name} = {value}")
    
    def record_trade_result(self, pnl: float, is_win: bool) -> None:
        """Record a trade result"""
        with self._lock:
            self._current_metrics.total_trades += 1
            self._current_metrics.total_pnl += pnl
            
            if is_win:
                self._current_metrics.winning_trades += 1
                # Update average win
                if self._current_metrics.winning_trades == 1:
                    self._current_metrics.average_win = pnl
                else:
                    self._current_metrics.average_win = (
                        (self._current_metrics.average_win * (self._current_metrics.winning_trades - 1) + pnl) /
                        self._current_metrics.winning_trades
                    )
            else:
                self._current_metrics.losing_trades += 1
                # Update average loss
                if self._current_metrics.losing_trades == 1:
                    self._current_metrics.average_loss = pnl
                else:
                    self._current_metrics.average_loss = (
                        (self._current_metrics.average_loss * (self._current_metrics.losing_trades - 1) + pnl) /
                        self._current_metrics.losing_trades
                    )
            
            # Update calculated metrics
            self._calculate_trading_metrics()
        
        self.logger.info(f"Trade result recorded: PnL={pnl}, Win={is_win}")
    
    def record_signal_generated(self, confidence: float) -> None:
        """Record a signal generation event"""
        with self._lock:
            self._current_metrics.signals_generated += 1
            
            # Update average confidence
            if self._current_metrics.signals_generated == 1:
                self._current_metrics.average_signal_confidence = confidence
            else:
                self._current_metrics.average_signal_confidence = (
                    (self._current_metrics.average_signal_confidence * 
                     (self._current_metrics.signals_generated - 1) + confidence) /
                    self._current_metrics.signals_generated
                )
            
            # Update calculated metrics
            self._calculate_signal_metrics()
        
        self.logger.debug(f"Signal generated with confidence: {confidence}")
    
    def record_signal_executed(self) -> None:
        """Record a signal execution event"""
        with self._lock:
            self._current_metrics.signals_executed += 1
            
            # Update calculated metrics
            self._calculate_signal_metrics()
        
        self.logger.debug("Signal executed")
    
    def record_api_call(self, endpoint: str, response_time: float, success: bool) -> None:
        """Record an API call for performance tracking"""
        self.record_metric(f"api_response_time_{endpoint}", response_time, MetricType.TIMER)
        self.record_metric("api_calls_total", 1, MetricType.COUNTER)
        
        if not success:
            self.record_metric("api_errors_total", 1, MetricType.COUNTER)
        
        # Update average response time
        with self._lock:
            if endpoint in self._timers:
                times = self._timers[endpoint]
                if times:
                    self._current_metrics.average_response_time = statistics.mean(times)
            
            # Calculate error rate
            total_calls = self._counters.get("api_calls_total", 0)
            total_errors = self._counters.get("api_errors_total", 0)
            if total_calls > 0:
                self._current_metrics.error_rate = total_errors / total_calls
    
    def get_current_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics snapshot"""
        with self._lock:
            return PerformanceMetrics(**self._current_metrics.__dict__)
    
    def get_metric_history(self, name: str, 
                          duration: Optional[timedelta] = None) -> List[MetricValue]:
        """Get historical values for a specific metric"""
        with self._lock:
            if name not in self._metrics:
                return []
            
            values = list(self._metrics[name])
            
            if duration:
                cutoff_time = datetime.now(timezone.utc) - duration
                values = [v for v in values if v.timestamp >= cutoff_time]
            
            return values
    
    def register_metric_callback(self, metric_name: str, callback: Callable) -> None:
        """Register a callback to be called when metrics are updated"""
        self._metric_callbacks[metric_name].append(callback)
        
        self.logger.debug(f"Registered callback for metric: {metric_name}")
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get overall system health status"""
        metrics = self.get_current_metrics()
        
        health_status = {
            'status': 'healthy',
            'issues': [],
            'metrics': metrics.to_dict(),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
        
        # Check for issues
        if metrics.error_rate > 0.05:  # 5% error rate threshold
            health_status['status'] = 'degraded'
            health_status['issues'].append(f"High error rate: {metrics.error_rate:.2%}")
        
        if metrics.average_response_time > 5.0:  # 5 second threshold
            health_status['status'] = 'degraded'
            health_status['issues'].append(f"Slow API responses: {metrics.average_response_time:.2f}s")
        
        if metrics.current_drawdown > 0.1:  # 10% drawdown threshold
            health_status['status'] = 'warning'
            health_status['issues'].append(f"High drawdown: {metrics.current_drawdown:.2%}")
        
        if metrics.memory_usage_mb > 1000:  # 1GB memory threshold
            health_status['status'] = 'warning'
            health_status['issues'].append(f"High memory usage: {metrics.memory_usage_mb:.0f}MB")
        
        if not health_status['issues']:
            health_status['status'] = 'healthy'
        
        return health_status
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive data for dashboard visualization"""
        metrics = self.get_current_metrics()
        
        # Get recent metric history for charts
        recent_pnl = []
        recent_trades = []
        recent_api_calls = []
        
        # Get PnL history (last 24 hours)
        pnl_history = self.get_metric_history("total_pnl", timedelta(hours=24))
        for metric in pnl_history[-50:]:  # Last 50 data points
            recent_pnl.append({
                'timestamp': metric.timestamp.isoformat(),
                'value': metric.value
            })
        
        # Get trade history (last 100 trades)
        trade_history = self.get_metric_history("trade_result", timedelta(hours=24))
        for metric in trade_history[-100:]:
            recent_trades.append({
                'timestamp': metric.timestamp.isoformat(),
                'pnl': metric.value,
                'is_win': metric.labels.get('is_win', False)
            })
        
        # Get API response time history
        api_history = self.get_metric_history("api_response_time", timedelta(hours=1))
        for metric in api_history[-50:]:
            recent_api_calls.append({
                'timestamp': metric.timestamp.isoformat(),
                'response_time': metric.value,
                'endpoint': metric.labels.get('endpoint', 'unknown')
            })
        
        dashboard_data = {
            'overview': {
                'total_pnl': metrics.total_pnl,
                'total_trades': metrics.total_trades,
                'win_rate': metrics.win_rate,
                'current_drawdown': metrics.current_drawdown,
                'signals_generated': metrics.signals_generated,
                'signals_executed': metrics.signals_executed,
                'system_status': self.get_system_health()['status']
            },
            'performance': {
                'profit_factor': metrics.profit_factor,
                'sharpe_ratio': metrics.sharpe_ratio,
                'max_drawdown': metrics.max_drawdown,
                'average_win': metrics.average_win,
                'average_loss': metrics.average_loss,
                'signal_accuracy': metrics.signal_accuracy,
                'average_signal_confidence': metrics.average_signal_confidence
            },
            'system_metrics': {
                'api_calls_per_minute': metrics.api_calls_per_minute,
                'average_response_time': metrics.average_response_time,
                'error_rate': metrics.error_rate,
                'memory_usage_mb': metrics.memory_usage_mb,
                'cpu_usage_percent': metrics.cpu_usage_percent
            },
            'risk_metrics': {
                'current_exposure': metrics.current_exposure,
                'max_position_size': metrics.max_position_size,
                'risk_per_trade': metrics.risk_per_trade
            },
            'charts': {
                'pnl_history': recent_pnl,
                'trade_history': recent_trades,
                'api_response_times': recent_api_calls
            },
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'update_interval': self.update_interval
        }
        
        return dashboard_data
    
    def export_metrics_csv(self, filepath: str, duration: timedelta = timedelta(days=7)) -> bool:
        """Export metrics to CSV file for external analysis"""
        try:
            import csv
            
            # Get all metrics for the specified duration
            all_metrics = {}
            for metric_name in self._metrics.keys():
                all_metrics[metric_name] = self.get_metric_history(metric_name, duration)
            
            # Write to CSV
            with open(filepath, 'w', newline='') as csvfile:
                fieldnames = ['timestamp', 'metric_name', 'value', 'labels']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for metric_name, values in all_metrics.items():
                    for value in values:
                        writer.writerow({
                            'timestamp': value.timestamp.isoformat(),
                            'metric_name': metric_name,
                            'value': value.value,
                            'labels': json.dumps(value.labels) if value.labels else '{}'
                        })
            
            self.logger.info(f"Metrics exported to CSV: {filepath}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export metrics to CSV: {e}")
            return False
    
    def export_metrics_json(self, filepath: str, duration: timedelta = timedelta(days=7)) -> bool:
        """Export metrics to JSON file for external analysis"""
        try:
            # Get current metrics and history
            export_data = {
                'current_metrics': self.get_current_metrics().to_dict(),
                'system_health': self.get_system_health(),
                'dashboard_data': self.get_dashboard_data(),
                'metric_history': {},
                'export_timestamp': datetime.now(timezone.utc).isoformat(),
                'duration_hours': duration.total_seconds() / 3600
            }
            
            # Add historical data
            for metric_name in self._metrics.keys():
                history = self.get_metric_history(metric_name, duration)
                export_data['metric_history'][metric_name] = [
                    {
                        'timestamp': value.timestamp.isoformat(),
                        'value': value.value,
                        'labels': value.labels
                    }
                    for value in history
                ]
            
            # Write to JSON file
            with open(filepath, 'w') as jsonfile:
                json.dump(export_data, jsonfile, indent=2, default=str)
            
            self.logger.info(f"Metrics exported to JSON: {filepath}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export metrics to JSON: {e}")
            return False
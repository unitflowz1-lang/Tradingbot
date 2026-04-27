"""Alert system for the AI Forex Trading Bot"""

import asyncio
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from enum import Enum
from typing import Dict, List, Optional, Callable, Any, Set
from threading import Lock
import json

from .logging_system import StructuredLogger, LogContext
from .performance_monitor import PerformanceMetrics


class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertChannel(Enum):
    """Alert delivery channels"""
    LOG = "log"
    EMAIL = "email"
    WEBHOOK = "webhook"
    CONSOLE = "console"


@dataclass
class Alert:
    """Alert message container"""
    id: str
    level: AlertLevel
    title: str
    message: str
    component: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data: Dict[str, Any] = field(default_factory=dict)
    channels: List[AlertChannel] = field(default_factory=list)
    acknowledged: bool = False
    resolved: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary"""
        return {
            'id': self.id,
            'level': self.level.value,
            'title': self.title,
            'message': self.message,
            'component': self.component,
            'timestamp': self.timestamp.isoformat(),
            'data': self.data,
            'channels': [c.value for c in self.channels],
            'acknowledged': self.acknowledged,
            'resolved': self.resolved
        }


@dataclass
class AlertRule:
    """Alert rule configuration"""
    name: str
    condition: Callable[[PerformanceMetrics], bool]
    level: AlertLevel
    message_template: str
    channels: List[AlertChannel]
    cooldown_minutes: int = 5
    max_alerts_per_hour: int = 10
    enabled: bool = True


class AlertSystem:
    """Comprehensive alert system for monitoring and notifications"""
    
    def __init__(self, 
                 email_config: Optional[Dict[str, str]] = None,
                 webhook_config: Optional[Dict[str, str]] = None):
        self.email_config = email_config or {}
        self.webhook_config = webhook_config or {}
        
        # Alert storage
        self._active_alerts: Dict[str, Alert] = {}
        self._alert_history: List[Alert] = []
        self._alert_rules: Dict[str, AlertRule] = {}
        
        # Rate limiting
        self._alert_counts: Dict[str, List[datetime]] = {}
        self._last_alert_time: Dict[str, datetime] = {}
        
        # Thread safety
        self._lock = Lock()
        
        # Logger - use simple logging to avoid potential issues
        import logging
        self.logger = logging.getLogger("ALERT_SYSTEM")
        
        # Alert handlers
        self._alert_handlers: Dict[AlertChannel, Callable] = {
            AlertChannel.LOG: self._handle_log_alert,
            AlertChannel.EMAIL: self._handle_email_alert,
            AlertChannel.WEBHOOK: self._handle_webhook_alert,
            AlertChannel.CONSOLE: self._handle_console_alert
        }
        
        # Setup default alert rules
        self._setup_default_rules()
    
    def _setup_default_rules(self) -> None:
        """Setup default alert rules"""
        default_rules = [
            AlertRule(
                name="high_error_rate",
                condition=lambda m: m.error_rate > 0.1,  # 10% error rate
                level=AlertLevel.ERROR,
                message_template="High error rate detected: {error_rate:.2%}",
                channels=[AlertChannel.LOG, AlertChannel.EMAIL],
                cooldown_minutes=10
            ),
            AlertRule(
                name="high_drawdown",
                condition=lambda m: m.current_drawdown > 0.15,  # 15% drawdown
                level=AlertLevel.CRITICAL,
                message_template="Critical drawdown reached: {current_drawdown:.2%}",
                channels=[AlertChannel.LOG, AlertChannel.EMAIL, AlertChannel.WEBHOOK],
                cooldown_minutes=5
            ),
            AlertRule(
                name="slow_api_response",
                condition=lambda m: m.average_response_time > 10.0,  # 10 seconds
                level=AlertLevel.WARNING,
                message_template="Slow API responses: {average_response_time:.2f}s average",
                channels=[AlertChannel.LOG],
                cooldown_minutes=15
            ),
            AlertRule(
                name="high_memory_usage",
                condition=lambda m: m.memory_usage_mb > 2000,  # 2GB
                level=AlertLevel.WARNING,
                message_template="High memory usage: {memory_usage_mb:.0f}MB",
                channels=[AlertChannel.LOG],
                cooldown_minutes=30
            ),
            AlertRule(
                name="low_win_rate",
                condition=lambda m: m.total_trades > 10 and m.win_rate < 0.3,  # 30% win rate
                level=AlertLevel.WARNING,
                message_template="Low win rate: {win_rate:.2%} over {total_trades} trades",
                channels=[AlertChannel.LOG, AlertChannel.EMAIL],
                cooldown_minutes=60
            ),
            AlertRule(
                name="no_trades_executed",
                condition=lambda m: m.signals_generated > 5 and m.signals_executed == 0,
                level=AlertLevel.ERROR,
                message_template="No trades executed despite {signals_generated} signals generated",
                channels=[AlertChannel.LOG, AlertChannel.EMAIL],
                cooldown_minutes=30
            )
        ]
        
        for rule in default_rules:
            self._alert_rules[rule.name] = rule
    
    def add_alert_rule(self, rule: AlertRule) -> None:
        """Add a custom alert rule"""
        with self._lock:
            self._alert_rules[rule.name] = rule
        
        self.logger.info(f"Added alert rule: {rule.name}")
    
    def remove_alert_rule(self, rule_name: str) -> bool:
        """Remove an alert rule"""
        with self._lock:
            if rule_name in self._alert_rules:
                del self._alert_rules[rule_name]
                self.logger.info(f"Removed alert rule: {rule_name}")
                return True
            return False
    
    def check_metrics(self, metrics: PerformanceMetrics) -> List[Alert]:
        """Check metrics against all alert rules and generate alerts"""
        triggered_alerts = []
        
        with self._lock:
            for rule_name, rule in self._alert_rules.items():
                if not rule.enabled:
                    continue
                
                try:
                    # Check if rule condition is met
                    if rule.condition(metrics):
                        # Check rate limiting
                        if self._should_send_alert(rule_name, rule):
                            alert = self._create_alert(rule, metrics)
                            triggered_alerts.append(alert)
                            self._active_alerts[alert.id] = alert
                            self._alert_history.append(alert)
                            
                            # Update rate limiting
                            self._update_rate_limiting(rule_name)
                            
                            # Send alert through configured channels
                            self._send_alert(alert)
                
                except Exception as e:
                    self.logger.error(f"Error checking alert rule {rule_name}: {e}")
        
        return triggered_alerts
    
    def _should_send_alert(self, rule_name: str, rule: AlertRule) -> bool:
        """Check if alert should be sent based on rate limiting"""
        now = datetime.now(timezone.utc)
        
        # Check cooldown
        if rule_name in self._last_alert_time:
            time_since_last = now - self._last_alert_time[rule_name]
            if time_since_last < timedelta(minutes=rule.cooldown_minutes):
                return False
        
        # Check hourly limit
        if rule_name not in self._alert_counts:
            self._alert_counts[rule_name] = []
        
        # Clean old entries (older than 1 hour)
        hour_ago = now - timedelta(hours=1)
        self._alert_counts[rule_name] = [
            t for t in self._alert_counts[rule_name] if t > hour_ago
        ]
        
        if len(self._alert_counts[rule_name]) >= rule.max_alerts_per_hour:
            return False
        
        return True
    
    def _update_rate_limiting(self, rule_name: str) -> None:
        """Update rate limiting counters"""
        now = datetime.now(timezone.utc)
        self._last_alert_time[rule_name] = now
        
        if rule_name not in self._alert_counts:
            self._alert_counts[rule_name] = []
        self._alert_counts[rule_name].append(now)
    
    def _create_alert(self, rule: AlertRule, metrics: PerformanceMetrics) -> Alert:
        """Create an alert from a rule and metrics"""
        # Generate unique alert ID
        alert_id = f"{rule.name}_{int(datetime.now(timezone.utc).timestamp())}"
        
        # Create a flattened dictionary of all metrics for formatting
        metrics_dict = metrics.to_dict()
        format_dict = {}
        for category, values in metrics_dict.items():
            format_dict.update(values)
        
        # Format message with metrics data, handling missing keys gracefully
        try:
            message = rule.message_template.format(**format_dict)
        except KeyError as e:
            # If formatting fails, use the template as-is and log the error
            message = rule.message_template
            self.logger.warning(f"Failed to format alert message template: {e}")
        
        return Alert(
            id=alert_id,
            level=rule.level,
            title=f"Alert: {rule.name.replace('_', ' ').title()}",
            message=message,
            component="MONITORING",
            channels=rule.channels,
            data=metrics.to_dict()
        )
    
    def _send_alert(self, alert: Alert) -> None:
        """Send alert through configured channels"""
        for channel in alert.channels:
            try:
                handler = self._alert_handlers.get(channel)
                if handler:
                    handler(alert)
                else:
                    self.logger.warning(f"No handler for alert channel: {channel.value}")
            except Exception as e:
                self.logger.error(f"Failed to send alert via {channel.value}: {e}")
    
    def _handle_log_alert(self, alert: Alert) -> None:
        """Handle log-based alerts"""
        log_level = {
            AlertLevel.INFO: self.logger.info,
            AlertLevel.WARNING: self.logger.warning,
            AlertLevel.ERROR: self.logger.error,
            AlertLevel.CRITICAL: self.logger.critical
        }.get(alert.level, self.logger.info)
        
        log_level(f"ALERT: {alert.title} - {alert.message}")
    
    def _handle_console_alert(self, alert: Alert) -> None:
        """Handle console-based alerts"""
        color_codes = {
            AlertLevel.INFO: '\033[94m',      # Blue
            AlertLevel.WARNING: '\033[93m',   # Yellow
            AlertLevel.ERROR: '\033[91m',     # Red
            AlertLevel.CRITICAL: '\033[95m'   # Magenta
        }
        reset_code = '\033[0m'
        
        color = color_codes.get(alert.level, '')
        print(f"{color}[{alert.level.value.upper()}] {alert.title}: {alert.message}{reset_code}")
    
    def _handle_email_alert(self, alert: Alert) -> None:
        """Handle email-based alerts"""
        if not self.email_config:
            self.logger.warning("Email alert requested but no email configuration provided")
            return
        
        try:
            # Create email message
            msg = MIMEMultipart()
            msg['From'] = self.email_config.get('from_email', '')
            msg['To'] = self.email_config.get('to_email', '')
            msg['Subject'] = f"[{alert.level.value.upper()}] {alert.title}"
            
            # Email body
            body = f"""
Alert Details:
- Level: {alert.level.value.upper()}
- Component: {alert.component}
- Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
- Message: {alert.message}

Additional Data:
{json.dumps(alert.data, indent=2)}

This is an automated alert from the AI Forex Trading Bot monitoring system.
"""
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Send email with short timeout to avoid hanging
            server = smtplib.SMTP(
                self.email_config.get('smtp_server', 'localhost'),
                int(self.email_config.get('smtp_port', 587)),
                timeout=3  # Reduced timeout
            )
            
            if self.email_config.get('use_tls', True):
                server.starttls()
            
            if 'username' in self.email_config and 'password' in self.email_config:
                server.login(
                    self.email_config['username'],
                    self.email_config['password']
                )
            
            server.send_message(msg)
            server.quit()
            
            self.logger.info(f"Email alert sent for: {alert.id}")
            
        except Exception as e:
            self.logger.error(f"Failed to send email alert: {e}")
    
    def _handle_webhook_alert(self, alert: Alert) -> None:
        """Handle webhook-based alerts"""
        if not self.webhook_config:
            self.logger.warning("Webhook alert requested but no webhook configuration provided")
            return
        
        try:
            import requests
            
            webhook_url = self.webhook_config.get('url')
            if not webhook_url:
                self.logger.warning("Webhook URL not configured")
                return
            
            # Prepare webhook payload
            payload = {
                'alert': alert.to_dict(),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'source': 'ai_forex_trading_bot'
            }
            
            # Add custom headers if configured
            headers = {'Content-Type': 'application/json'}
            if 'headers' in self.webhook_config:
                headers.update(self.webhook_config['headers'])
            
            # Send webhook with reduced timeout
            response = requests.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=3  # Reduced timeout to avoid hanging
            )
            response.raise_for_status()
            
            self.logger.info(f"Webhook alert sent for: {alert.id}")
            
        except Exception as e:
            self.logger.error(f"Failed to send webhook alert: {e}")
    
    def create_manual_alert(self, 
                           level: AlertLevel,
                           title: str,
                           message: str,
                           component: str = "MANUAL",
                           channels: Optional[List[AlertChannel]] = None,
                           data: Optional[Dict[str, Any]] = None) -> Alert:
        """Create and send a manual alert"""
        channels = channels or [AlertChannel.LOG]
        data = data or {}
        
        alert = Alert(
            id=f"manual_{int(datetime.now(timezone.utc).timestamp())}",
            level=level,
            title=title,
            message=message,
            component=component,
            channels=channels,
            data=data
        )
        
        with self._lock:
            self._active_alerts[alert.id] = alert
            self._alert_history.append(alert)
        
        self._send_alert(alert)
        
        self.logger.info(f"Manual alert created: {alert.id}")
        
        return alert
    
    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an active alert"""
        with self._lock:
            if alert_id in self._active_alerts:
                self._active_alerts[alert_id].acknowledged = True
                self.logger.info(f"Alert acknowledged: {alert_id}")
                return True
            return False
    
    def resolve_alert(self, alert_id: str) -> bool:
        """Resolve an active alert"""
        with self._lock:
            if alert_id in self._active_alerts:
                alert = self._active_alerts[alert_id]
                alert.resolved = True
                alert.acknowledged = True
                del self._active_alerts[alert_id]
                
                self.logger.info(f"Alert resolved: {alert_id}")
                return True
            return False
    
    def get_active_alerts(self) -> List[Alert]:
        """Get all active alerts"""
        with self._lock:
            return list(self._active_alerts.values())
    
    def get_alert_history(self, 
                         hours: int = 24,
                         level: Optional[AlertLevel] = None) -> List[Alert]:
        """Get alert history for specified time period"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        with self._lock:
            alerts = [
                alert for alert in self._alert_history
                if alert.timestamp >= cutoff_time
            ]
            
            if level:
                alerts = [alert for alert in alerts if alert.level == level]
            
            return sorted(alerts, key=lambda a: a.timestamp, reverse=True)
    
    def get_alert_summary(self) -> Dict[str, Any]:
        """Get summary of alert system status"""
        with self._lock:
            active_by_level = {}
            for alert in self._active_alerts.values():
                level = alert.level.value
                active_by_level[level] = active_by_level.get(level, 0) + 1
            
            recent_history = self.get_alert_history(hours=24)
            history_by_level = {}
            for alert in recent_history:
                level = alert.level.value
                history_by_level[level] = history_by_level.get(level, 0) + 1
            
            return {
                'active_alerts': len(self._active_alerts),
                'active_by_level': active_by_level,
                'total_rules': len(self._alert_rules),
                'enabled_rules': sum(1 for r in self._alert_rules.values() if r.enabled),
                'recent_alerts_24h': len(recent_history),
                'recent_by_level': history_by_level,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
    
    def get_dashboard_alerts(self) -> Dict[str, Any]:
        """Get alert data formatted for dashboard display"""
        active_alerts = self.get_active_alerts()
        recent_alerts = self.get_alert_history(hours=24)
        
        # Sort alerts by severity and timestamp
        severity_order = {
            AlertLevel.CRITICAL: 0,
            AlertLevel.ERROR: 1,
            AlertLevel.WARNING: 2,
            AlertLevel.INFO: 3
        }
        
        active_sorted = sorted(
            active_alerts,
            key=lambda a: (severity_order.get(a.level, 4), a.timestamp),
            reverse=True
        )
        
        recent_sorted = sorted(
            recent_alerts,
            key=lambda a: a.timestamp,
            reverse=True
        )
        
        # Create timeline data for charts
        alert_timeline = []
        for alert in recent_sorted[:50]:  # Last 50 alerts
            alert_timeline.append({
                'timestamp': alert.timestamp.isoformat(),
                'level': alert.level.value,
                'title': alert.title,
                'component': alert.component,
                'resolved': alert.resolved
            })
        
        # Count alerts by hour for the last 24 hours
        hourly_counts = {}
        now = datetime.now(timezone.utc)
        for i in range(24):
            hour_start = now - timedelta(hours=i+1)
            hour_end = now - timedelta(hours=i)
            hour_key = hour_start.strftime('%H:00')
            
            count = sum(1 for alert in recent_alerts 
                       if hour_start <= alert.timestamp < hour_end)
            hourly_counts[hour_key] = count
        
        return {
            'active_alerts': [alert.to_dict() for alert in active_sorted[:10]],  # Top 10 active
            'recent_alerts': [alert.to_dict() for alert in recent_sorted[:20]],  # Last 20 alerts
            'alert_timeline': alert_timeline,
            'hourly_counts': hourly_counts,
            'summary': self.get_alert_summary(),
            'critical_count': sum(1 for a in active_alerts if a.level == AlertLevel.CRITICAL),
            'error_count': sum(1 for a in active_alerts if a.level == AlertLevel.ERROR),
            'warning_count': sum(1 for a in active_alerts if a.level == AlertLevel.WARNING),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def enable_rule(self, rule_name: str) -> bool:
        """Enable an alert rule"""
        with self._lock:
            if rule_name in self._alert_rules:
                self._alert_rules[rule_name].enabled = True
                self.logger.info(f"Enabled alert rule: {rule_name}")
                return True
            return False
    
    def disable_rule(self, rule_name: str) -> bool:
        """Disable an alert rule"""
        with self._lock:
            if rule_name in self._alert_rules:
                self._alert_rules[rule_name].enabled = False
                self.logger.info(f"Disabled alert rule: {rule_name}")
                return True
            return False
    
    def update_rule_config(self, rule_name: str, **kwargs) -> bool:
        """Update alert rule configuration"""
        with self._lock:
            if rule_name not in self._alert_rules:
                return False
            
            rule = self._alert_rules[rule_name]
            
            # Update allowed fields
            if 'cooldown_minutes' in kwargs:
                rule.cooldown_minutes = kwargs['cooldown_minutes']
            if 'max_alerts_per_hour' in kwargs:
                rule.max_alerts_per_hour = kwargs['max_alerts_per_hour']
            if 'enabled' in kwargs:
                rule.enabled = kwargs['enabled']
            if 'channels' in kwargs:
                rule.channels = kwargs['channels']
            if 'level' in kwargs:
                rule.level = kwargs['level']
            
            self.logger.info(f"Updated alert rule configuration: {rule_name}")
            return True
    
    def test_alert_channels(self) -> Dict[str, bool]:
        """Test all configured alert channels"""
        test_results = {}
        
        test_alert = Alert(
            id="test_alert_channels",
            level=AlertLevel.INFO,
            title="Alert Channel Test",
            message="This is a test alert to verify channel functionality",
            component="ALERT_SYSTEM_TEST",
            channels=list(AlertChannel)
        )
        
        for channel in AlertChannel:
            try:
                handler = self._alert_handlers.get(channel)
                if handler:
                    handler(test_alert)
                    test_results[channel.value] = True
                    self.logger.info(f"Alert channel test passed: {channel.value}")
                else:
                    test_results[channel.value] = False
                    self.logger.warning(f"No handler for alert channel: {channel.value}")
            except Exception as e:
                test_results[channel.value] = False
                self.logger.error(f"Alert channel test failed: {channel.value} - {e}")
        
        return test_results
    
    def export_alerts_json(self, filepath: str, hours: int = 24) -> bool:
        """Export alert history to JSON file"""
        try:
            alerts = self.get_alert_history(hours=hours)
            
            export_data = {
                'alerts': [alert.to_dict() for alert in alerts],
                'summary': self.get_alert_summary(),
                'export_timestamp': datetime.now(timezone.utc).isoformat(),
                'duration_hours': hours,
                'total_alerts': len(alerts)
            }
            
            with open(filepath, 'w') as jsonfile:
                json.dump(export_data, jsonfile, indent=2, default=str)
            
            self.logger.info(f"Alerts exported to JSON: {filepath}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export alerts to JSON: {e}")
            return False
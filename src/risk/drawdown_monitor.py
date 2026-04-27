"""Drawdown monitoring and circuit breaker system"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set
from enum import Enum

from src.models import Portfolio, Position
from src.exceptions import DataValidationError
from .risk_calculator import EquityPoint


class CircuitBreakerState(Enum):
    """Circuit breaker states"""
    CLOSED = "CLOSED"      # Normal operation
    OPEN = "OPEN"          # Trading halted
    HALF_OPEN = "HALF_OPEN"  # Limited trading allowed


@dataclass
class DrawdownConfig:
    """Configuration for drawdown monitoring"""
    max_drawdown_percent: float = 10.0  # Maximum allowed drawdown percentage
    max_daily_drawdown_percent: float = 5.0  # Maximum daily drawdown
    correlation_threshold: float = 0.7  # Maximum correlation between positions
    recovery_threshold_percent: float = 2.0  # Recovery needed to reset circuit breaker
    monitoring_window_hours: int = 24  # Hours to track for daily drawdown
    
    def __post_init__(self):
        """Validate configuration"""
        self.validate()
    
    def validate(self) -> None:
        """Validate drawdown configuration"""
        if not 0.0 < self.max_drawdown_percent <= 100.0:
            raise DataValidationError(
                f"Max drawdown percent must be between 0 and 100: {self.max_drawdown_percent}",
                error_code="INVALID_MAX_DRAWDOWN",
                context={"max_drawdown_percent": self.max_drawdown_percent}
            )
        
        if not 0.0 < self.max_daily_drawdown_percent <= 100.0:
            raise DataValidationError(
                f"Max daily drawdown percent must be between 0 and 100: {self.max_daily_drawdown_percent}",
                error_code="INVALID_DAILY_DRAWDOWN",
                context={"max_daily_drawdown_percent": self.max_daily_drawdown_percent}
            )
        
        if not 0.0 <= self.correlation_threshold <= 1.0:
            raise DataValidationError(
                f"Correlation threshold must be between 0 and 1: {self.correlation_threshold}",
                error_code="INVALID_CORRELATION_THRESHOLD",
                context={"correlation_threshold": self.correlation_threshold}
            )
        
        if not 0.0 < self.recovery_threshold_percent <= 100.0:
            raise DataValidationError(
                f"Recovery threshold must be between 0 and 100: {self.recovery_threshold_percent}",
                error_code="INVALID_RECOVERY_THRESHOLD",
                context={"recovery_threshold_percent": self.recovery_threshold_percent}
            )
        
        if self.monitoring_window_hours <= 0:
            raise DataValidationError(
                f"Monitoring window must be positive: {self.monitoring_window_hours}",
                error_code="INVALID_MONITORING_WINDOW",
                context={"monitoring_window_hours": self.monitoring_window_hours}
            )



@dataclass
class DrawdownAlert:
    """Drawdown alert information"""
    alert_type: str
    current_drawdown_percent: float
    threshold_percent: float
    message: str
    timestamp: datetime
    severity: str  # INFO, WARNING, CRITICAL


@dataclass
class CorrelationRisk:
    """Currency pair correlation risk assessment"""
    pair1: str
    pair2: str
    correlation: float
    combined_exposure: float
    risk_level: str  # LOW, MEDIUM, HIGH


class DrawdownMonitor:
    """Monitor account drawdown and implement circuit breakers"""
    
    def __init__(self, config: DrawdownConfig):
        """Initialize drawdown monitor"""
        self.config = config
        self.equity_history: List[EquityPoint] = []
        self.peak_equity: float = 0.0
        self.peak_timestamp: datetime = datetime.now(timezone.utc)
        self.circuit_breaker_state = CircuitBreakerState.CLOSED
        self.circuit_breaker_triggered_at: Optional[datetime] = None
        self.alerts: List[DrawdownAlert] = []
        self.logger = logging.getLogger(__name__)
        
        # Currency correlation matrix (simplified for major pairs)
        self.correlation_matrix = {
            ("EUR/USD", "GBP/USD"): 0.85,
            ("EUR/USD", "USD/JPY"): -0.65,
            ("EUR/USD", "USD/CHF"): -0.90,
            ("GBP/USD", "USD/JPY"): -0.55,
            ("GBP/USD", "USD/CHF"): -0.80,
            ("USD/JPY", "USD/CHF"): 0.70,
            ("EUR/GBP", "EUR/USD"): 0.60,
            ("EUR/GBP", "GBP/USD"): -0.40,
        }
    
    def update_equity(self, portfolio: Portfolio) -> None:
        """Update equity tracking with current portfolio state"""
        current_time = datetime.now(timezone.utc)
        
        # Create equity point
        equity_point = EquityPoint(
            timestamp=current_time,
            balance=portfolio.balance,
            equity=portfolio.equity,
            drawdown=0.0  # Will be calculated after adding to history
        )
        
        # Add to history
        self.equity_history.append(equity_point)
        
        # Update peak equity
        if portfolio.equity > self.peak_equity:
            self.peak_equity = portfolio.equity
            self.peak_timestamp = current_time
        
        # Update drawdown in the equity point
        equity_point.drawdown = self.get_current_drawdown_percent()
        
        # Clean old history (keep only monitoring window)
        cutoff_time = current_time.timestamp() - (self.config.monitoring_window_hours * 3600)
        self.equity_history = [
            point for point in self.equity_history
            if point.timestamp.timestamp() > cutoff_time
        ]
        
        # Check drawdown levels
        self._check_drawdown_levels(portfolio)
        
        # Update circuit breaker state
        self._update_circuit_breaker_state(portfolio)
    
    def get_current_drawdown_percent(self) -> float:
        """Calculate current drawdown percentage from peak"""
        if not self.equity_history or self.peak_equity == 0:
            return 0.0
        
        current_equity = self.equity_history[-1].equity
        return ((self.peak_equity - current_equity) / self.peak_equity) * 100.0
    
    def get_daily_drawdown_percent(self) -> float:
        """Calculate drawdown percentage for the current day"""
        if len(self.equity_history) < 2:
            return 0.0
        
        current_time = datetime.now(timezone.utc)
        day_start = current_time.replace(hour=0, minute=0, second=0, microsecond=0)
        
        # Find equity at start of day
        day_start_equity = None
        for point in self.equity_history:
            if point.timestamp >= day_start:
                day_start_equity = point.equity
                break
        
        if day_start_equity is None:
            # Use first available point if no data from start of day
            day_start_equity = self.equity_history[0].equity
        
        current_equity = self.equity_history[-1].equity
        
        if day_start_equity == 0:
            return 0.0
        
        return ((day_start_equity - current_equity) / day_start_equity) * 100.0
    
    def is_trading_allowed(self) -> bool:
        """Check if trading is currently allowed"""
        return self.circuit_breaker_state != CircuitBreakerState.OPEN
    
    def should_halt_trading(self, portfolio: Portfolio) -> bool:
        """Determine if trading should be halted"""
        current_drawdown = self.get_current_drawdown_percent()
        daily_drawdown = self.get_daily_drawdown_percent()
        
        # Check maximum drawdown threshold
        if current_drawdown >= self.config.max_drawdown_percent:
            self._trigger_circuit_breaker("Maximum drawdown exceeded", current_drawdown)
            return True
        
        # Check daily drawdown threshold
        if daily_drawdown >= self.config.max_daily_drawdown_percent:
            self._trigger_circuit_breaker("Daily drawdown limit exceeded", daily_drawdown)
            return True
        
        # Check correlation risk
        correlation_risks = self.assess_correlation_risk(portfolio.positions)
        high_risk_correlations = [risk for risk in correlation_risks if risk.risk_level == "HIGH"]
        
        if high_risk_correlations:
            self._trigger_circuit_breaker("High correlation risk detected", current_drawdown)
            return True
        
        return False
    
    def assess_correlation_risk(self, positions: List[Position]) -> List[CorrelationRisk]:
        """Assess correlation risk between currency pairs"""
        risks = []
        
        # Group positions by symbol
        position_map = {}
        for pos in positions:
            if pos.symbol not in position_map:
                position_map[pos.symbol] = []
            position_map[pos.symbol].append(pos)
        
        symbols = list(position_map.keys())
        
        # Check correlations between all pairs
        for i, symbol1 in enumerate(symbols):
            for symbol2 in symbols[i+1:]:
                correlation = self._get_correlation(symbol1, symbol2)
                
                if abs(correlation) >= self.config.correlation_threshold:
                    # Calculate combined exposure
                    exposure1 = sum(pos.quantity * pos.current_price for pos in position_map[symbol1])
                    exposure2 = sum(pos.quantity * pos.current_price for pos in position_map[symbol2])
                    combined_exposure = exposure1 + exposure2
                    
                    # Determine risk level
                    risk_level = "HIGH" if abs(correlation) >= 0.8 else "MEDIUM"
                    
                    risks.append(CorrelationRisk(
                        pair1=symbol1,
                        pair2=symbol2,
                        correlation=correlation,
                        combined_exposure=combined_exposure,
                        risk_level=risk_level
                    ))
        
        return risks
    
    def get_circuit_breaker_state(self) -> CircuitBreakerState:
        """Get current circuit breaker state"""
        return self.circuit_breaker_state
    
    def reset_circuit_breaker(self) -> bool:
        """Manually reset circuit breaker (admin function)"""
        if self.circuit_breaker_state == CircuitBreakerState.OPEN:
            self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
            self.logger.info("Circuit breaker manually reset to HALF_OPEN state")
            return True
        return False
    
    def get_recent_alerts(self, hours: int = 24) -> List[DrawdownAlert]:
        """Get recent drawdown alerts"""
        cutoff_time = datetime.now(timezone.utc).timestamp() - (hours * 3600)
        return [
            alert for alert in self.alerts
            if alert.timestamp.timestamp() > cutoff_time
        ]
    
    def _check_drawdown_levels(self, portfolio: Portfolio) -> None:
        """Check current drawdown levels and generate alerts"""
        current_drawdown = self.get_current_drawdown_percent()
        daily_drawdown = self.get_daily_drawdown_percent()
        
        # Check for warning levels (50% of max thresholds)
        warning_threshold = self.config.max_drawdown_percent * 0.5
        daily_warning_threshold = self.config.max_daily_drawdown_percent * 0.5
        
        if current_drawdown >= warning_threshold:
            self._create_alert(
                "DRAWDOWN_WARNING",
                current_drawdown,
                self.config.max_drawdown_percent,
                f"Drawdown approaching limit: {current_drawdown:.2f}%",
                "WARNING"
            )
        
        if daily_drawdown >= daily_warning_threshold:
            self._create_alert(
                "DAILY_DRAWDOWN_WARNING",
                daily_drawdown,
                self.config.max_daily_drawdown_percent,
                f"Daily drawdown approaching limit: {daily_drawdown:.2f}%",
                "WARNING"
            )
    
    def _update_circuit_breaker_state(self, portfolio: Portfolio) -> None:
        """Update circuit breaker state based on current conditions"""
        current_drawdown = self.get_current_drawdown_percent()
        
        if self.circuit_breaker_state == CircuitBreakerState.OPEN:
            # Check if we can move to half-open (some recovery)
            if current_drawdown <= (self.config.max_drawdown_percent - self.config.recovery_threshold_percent):
                self.circuit_breaker_state = CircuitBreakerState.HALF_OPEN
                self.logger.info(f"Circuit breaker moved to HALF_OPEN: drawdown recovered to {current_drawdown:.2f}%")
        
        elif self.circuit_breaker_state == CircuitBreakerState.HALF_OPEN:
            # Check if we can fully close (significant recovery)
            recovery_target = self.config.max_drawdown_percent - (2 * self.config.recovery_threshold_percent)
            if current_drawdown <= recovery_target:
                self.circuit_breaker_state = CircuitBreakerState.CLOSED
                self.circuit_breaker_triggered_at = None
                self.logger.info(f"Circuit breaker CLOSED: drawdown recovered to {current_drawdown:.2f}%")
    
    def _trigger_circuit_breaker(self, reason: str, current_drawdown: float) -> None:
        """Trigger circuit breaker and halt trading"""
        if self.circuit_breaker_state != CircuitBreakerState.OPEN:
            self.circuit_breaker_state = CircuitBreakerState.OPEN
            self.circuit_breaker_triggered_at = datetime.now(timezone.utc)
            
            self._create_alert(
                "CIRCUIT_BREAKER_TRIGGERED",
                current_drawdown,
                self.config.max_drawdown_percent,
                f"Trading halted: {reason}",
                "CRITICAL"
            )
            
            self.logger.critical(f"Circuit breaker TRIGGERED: {reason} (drawdown: {current_drawdown:.2f}%)")
    
    def _get_correlation(self, symbol1: str, symbol2: str) -> float:
        """Get correlation between two currency pairs"""
        # Check both directions in correlation matrix
        key1 = (symbol1, symbol2)
        key2 = (symbol2, symbol1)
        
        if key1 in self.correlation_matrix:
            return self.correlation_matrix[key1]
        elif key2 in self.correlation_matrix:
            return self.correlation_matrix[key2]
        else:
            # Default correlation for unknown pairs
            return 0.0
    
    def _create_alert(self, alert_type: str, current_value: float, threshold: float, 
                     message: str, severity: str) -> None:
        """Create and store a drawdown alert"""
        alert = DrawdownAlert(
            alert_type=alert_type,
            current_drawdown_percent=current_value,
            threshold_percent=threshold,
            message=message,
            timestamp=datetime.now(timezone.utc),
            severity=severity
        )
        
        self.alerts.append(alert)
        
        # Keep only recent alerts (last 7 days)
        cutoff_time = datetime.now(timezone.utc).timestamp() - (7 * 24 * 3600)
        self.alerts = [
            alert for alert in self.alerts
            if alert.timestamp.timestamp() > cutoff_time
        ]


class CircuitBreakerManager:
    """Manage multiple circuit breakers and trading halt decisions"""
    
    def __init__(self):
        """Initialize circuit breaker manager"""
        self.monitors: Dict[str, DrawdownMonitor] = {}
        self.global_halt = False
        self.halt_reasons: Set[str] = set()
        self.logger = logging.getLogger(__name__)
    
    def add_monitor(self, name: str, monitor: DrawdownMonitor) -> None:
        """Add a drawdown monitor"""
        self.monitors[name] = monitor
    
    def remove_monitor(self, name: str) -> bool:
        """Remove a drawdown monitor"""
        if name in self.monitors:
            del self.monitors[name]
            return True
        return False
    
    def update_all_monitors(self, portfolio: Portfolio) -> None:
        """Update all registered monitors"""
        for name, monitor in self.monitors.items():
            try:
                monitor.update_equity(portfolio)
            except Exception as e:
                self.logger.error(f"Error updating monitor {name}: {e}")
    
    def is_trading_allowed(self) -> bool:
        """Check if trading is allowed across all monitors"""
        if self.global_halt:
            return False
        
        for monitor in self.monitors.values():
            if not monitor.is_trading_allowed():
                return False
        
        return True
    
    def should_halt_trading(self, portfolio: Portfolio) -> bool:
        """Check if any monitor requires trading halt"""
        halt_required = False
        self.halt_reasons.clear()
        
        for name, monitor in self.monitors.items():
            if monitor.should_halt_trading(portfolio):
                halt_required = True
                self.halt_reasons.add(f"{name}: {monitor.circuit_breaker_state.value}")
        
        return halt_required
    
    def get_halt_reasons(self) -> List[str]:
        """Get reasons for trading halt"""
        return list(self.halt_reasons)
    
    def emergency_halt(self, reason: str) -> None:
        """Emergency halt all trading"""
        self.global_halt = True
        self.halt_reasons.add(f"EMERGENCY: {reason}")
        self.logger.critical(f"Emergency trading halt: {reason}")
    
    def reset_emergency_halt(self) -> None:
        """Reset emergency halt"""
        self.global_halt = False
        # Remove all emergency reasons
        self.halt_reasons = {reason for reason in self.halt_reasons if not reason.startswith("EMERGENCY")}
        self.logger.info("Emergency halt reset")
    
    def get_system_status(self) -> Dict[str, any]:
        """Get overall system status"""
        status = {
            "trading_allowed": self.is_trading_allowed(),
            "global_halt": self.global_halt,
            "halt_reasons": list(self.halt_reasons),
            "monitors": {}
        }
        
        for name, monitor in self.monitors.items():
            status["monitors"][name] = {
                "state": monitor.circuit_breaker_state.value,
                "current_drawdown": monitor.get_current_drawdown_percent(),
                "daily_drawdown": monitor.get_daily_drawdown_percent(),
                "peak_equity": monitor.peak_equity,
                "recent_alerts": len(monitor.get_recent_alerts(1))  # Last hour
            }
        
        return status
"""Unit tests for drawdown monitoring and circuit breaker system"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from src.risk.drawdown_monitor import (
    DrawdownConfig, DrawdownAlert, CorrelationRisk, CircuitBreakerState,
    DrawdownMonitor, CircuitBreakerManager
)
from src.risk.risk_calculator import EquityPoint
from src.models import Portfolio, Position, Direction
from src.exceptions import DataValidationError


class TestDrawdownConfig:
    """Test DrawdownConfig validation and functionality"""
    
    def test_valid_config(self):
        """Test valid configuration creation"""
        config = DrawdownConfig(
            max_drawdown_percent=15.0,
            max_daily_drawdown_percent=7.5,
            correlation_threshold=0.8,
            recovery_threshold_percent=3.0,
            monitoring_window_hours=48
        )
        
        assert config.max_drawdown_percent == 15.0
        assert config.max_daily_drawdown_percent == 7.5
        assert config.correlation_threshold == 0.8
        assert config.recovery_threshold_percent == 3.0
        assert config.monitoring_window_hours == 48
    
    def test_default_config(self):
        """Test default configuration values"""
        config = DrawdownConfig()
        
        assert config.max_drawdown_percent == 10.0
        assert config.max_daily_drawdown_percent == 5.0
        assert config.correlation_threshold == 0.7
        assert config.recovery_threshold_percent == 2.0
        assert config.monitoring_window_hours == 24
    
    def test_invalid_max_drawdown(self):
        """Test invalid max drawdown percentage"""
        with pytest.raises(DataValidationError) as exc_info:
            DrawdownConfig(max_drawdown_percent=0.0)
        assert exc_info.value.error_code == "INVALID_MAX_DRAWDOWN"
        
        with pytest.raises(DataValidationError) as exc_info:
            DrawdownConfig(max_drawdown_percent=150.0)
        assert exc_info.value.error_code == "INVALID_MAX_DRAWDOWN"
    
    def test_invalid_daily_drawdown(self):
        """Test invalid daily drawdown percentage"""
        with pytest.raises(DataValidationError) as exc_info:
            DrawdownConfig(max_daily_drawdown_percent=-5.0)
        assert exc_info.value.error_code == "INVALID_DAILY_DRAWDOWN"
    
    def test_invalid_correlation_threshold(self):
        """Test invalid correlation threshold"""
        with pytest.raises(DataValidationError) as exc_info:
            DrawdownConfig(correlation_threshold=1.5)
        assert exc_info.value.error_code == "INVALID_CORRELATION_THRESHOLD"
    
    def test_invalid_recovery_threshold(self):
        """Test invalid recovery threshold"""
        with pytest.raises(DataValidationError) as exc_info:
            DrawdownConfig(recovery_threshold_percent=0.0)
        assert exc_info.value.error_code == "INVALID_RECOVERY_THRESHOLD"
    
    def test_invalid_monitoring_window(self):
        """Test invalid monitoring window"""
        with pytest.raises(DataValidationError) as exc_info:
            DrawdownConfig(monitoring_window_hours=-1)
        assert exc_info.value.error_code == "INVALID_MONITORING_WINDOW"


class TestDrawdownMonitor:
    """Test DrawdownMonitor functionality"""
    
    @pytest.fixture
    def config(self):
        """Create test configuration"""
        return DrawdownConfig(
            max_drawdown_percent=10.0,
            max_daily_drawdown_percent=5.0,
            correlation_threshold=0.7,
            recovery_threshold_percent=2.0,
            monitoring_window_hours=24
        )
    
    @pytest.fixture
    def monitor(self, config):
        """Create test monitor"""
        return DrawdownMonitor(config)
    
    @pytest.fixture
    def sample_portfolio(self):
        """Create sample portfolio"""
        positions = [
            Position(
                position_id="pos1",
                symbol="EUR/USD",
                direction=Direction.LONG,
                quantity=10000.0,
                entry_price=1.1000,
                current_price=1.1050,
                unrealized_pnl=50.0,
                stop_loss=1.0950,
                take_profit=1.1150,
                opened_at=datetime.now(timezone.utc) - timedelta(hours=1)
            ),
            Position(
                position_id="pos2",
                symbol="GBP/USD",
                direction=Direction.SHORT,
                quantity=5000.0,
                entry_price=1.3000,
                current_price=1.2980,
                unrealized_pnl=10.0,
                stop_loss=1.3050,
                take_profit=1.2900,
                opened_at=datetime.now(timezone.utc) - timedelta(minutes=30)
            )
        ]
        
        return Portfolio(
            account_id="test_account",
            balance=10000.0,
            equity=10060.0,
            margin_used=1500.0,
            margin_available=8560.0,
            positions=positions,
            updated_at=datetime.now(timezone.utc)
        )
    
    def test_initial_state(self, monitor):
        """Test initial monitor state"""
        assert monitor.peak_equity == 0.0
        assert monitor.circuit_breaker_state == CircuitBreakerState.CLOSED
        assert monitor.circuit_breaker_triggered_at is None
        assert len(monitor.equity_history) == 0
        assert len(monitor.alerts) == 0
    
    def test_update_equity_first_time(self, monitor, sample_portfolio):
        """Test first equity update"""
        monitor.update_equity(sample_portfolio)
        
        assert len(monitor.equity_history) == 1
        assert monitor.peak_equity == sample_portfolio.equity
        assert monitor.equity_history[0].equity == sample_portfolio.equity
        assert monitor.equity_history[0].balance == sample_portfolio.balance
        assert monitor.equity_history[0].drawdown == 0.0  # No drawdown on first update
    
    def test_update_equity_new_peak(self, monitor, sample_portfolio):
        """Test equity update with new peak"""
        # First update
        monitor.update_equity(sample_portfolio)
        initial_peak = monitor.peak_equity
        
        # Update with higher equity
        sample_portfolio.equity = 11000.0
        monitor.update_equity(sample_portfolio)
        
        assert monitor.peak_equity == 11000.0
        assert monitor.peak_equity > initial_peak
        assert len(monitor.equity_history) == 2
    
    def test_get_current_drawdown_percent(self, monitor, sample_portfolio):
        """Test current drawdown calculation"""
        # Set peak
        sample_portfolio.equity = 10000.0
        monitor.update_equity(sample_portfolio)
        
        # Create drawdown
        sample_portfolio.equity = 9000.0
        monitor.update_equity(sample_portfolio)
        
        drawdown = monitor.get_current_drawdown_percent()
        assert abs(drawdown - 10.0) < 0.01  # 10% drawdown
    
    def test_get_daily_drawdown_percent(self, monitor, sample_portfolio):
        """Test daily drawdown calculation"""
        # Start of day equity
        sample_portfolio.equity = 10000.0
        monitor.update_equity(sample_portfolio)
        
        # Current equity (lower)
        sample_portfolio.equity = 9500.0
        monitor.update_equity(sample_portfolio)
        
        daily_drawdown = monitor.get_daily_drawdown_percent()
        assert abs(daily_drawdown - 5.0) < 0.01  # 5% daily drawdown
    
    def test_is_trading_allowed_normal(self, monitor):
        """Test trading allowed in normal state"""
        assert monitor.is_trading_allowed() is True
    
    def test_is_trading_allowed_circuit_breaker_open(self, monitor):
        """Test trading not allowed when circuit breaker is open"""
        monitor.circuit_breaker_state = CircuitBreakerState.OPEN
        assert monitor.is_trading_allowed() is False
    
    def test_should_halt_trading_max_drawdown(self, monitor, sample_portfolio):
        """Test trading halt due to maximum drawdown"""
        # Set peak
        sample_portfolio.equity = 10000.0
        monitor.update_equity(sample_portfolio)
        
        # Create excessive drawdown (>10%)
        sample_portfolio.equity = 8500.0  # 15% drawdown
        monitor.update_equity(sample_portfolio)
        
        # Explicitly check if trading should be halted (this triggers the circuit breaker)
        should_halt = monitor.should_halt_trading(sample_portfolio)
        assert should_halt is True
        assert monitor.circuit_breaker_state == CircuitBreakerState.OPEN
    
    def test_should_halt_trading_daily_drawdown(self, monitor, sample_portfolio):
        """Test trading halt due to daily drawdown"""
        # Start of day
        sample_portfolio.equity = 10000.0
        monitor.update_equity(sample_portfolio)
        
        # Excessive daily drawdown (>5%)
        sample_portfolio.equity = 9000.0  # 10% daily drawdown
        monitor.update_equity(sample_portfolio)
        
        # Explicitly check if trading should be halted
        should_halt = monitor.should_halt_trading(sample_portfolio)
        assert should_halt is True
        assert monitor.circuit_breaker_state == CircuitBreakerState.OPEN
    
    def test_assess_correlation_risk_high(self, monitor, sample_portfolio):
        """Test high correlation risk assessment"""
        # EUR/USD and GBP/USD have high correlation (0.85)
        risks = monitor.assess_correlation_risk(sample_portfolio.positions)
        
        # Should find high correlation between EUR/USD and GBP/USD
        high_risk = [risk for risk in risks if risk.risk_level == "HIGH"]
        assert len(high_risk) > 0
        
        eur_gbp_risk = next((risk for risk in risks 
                           if (risk.pair1 == "EUR/USD" and risk.pair2 == "GBP/USD") or
                              (risk.pair1 == "GBP/USD" and risk.pair2 == "EUR/USD")), None)
        assert eur_gbp_risk is not None
        assert abs(eur_gbp_risk.correlation) >= 0.7
    
    def test_assess_correlation_risk_low(self, monitor):
        """Test low correlation risk with uncorrelated pairs"""
        positions = [
            Position(
                position_id="pos1",
                symbol="EUR/USD",
                direction=Direction.LONG,
                quantity=1000.0,
                entry_price=1.1000,
                current_price=1.1050,
                unrealized_pnl=5.0,  # (1.1050 - 1.1000) * 1000 = 5.0 (rounded)
                stop_loss=1.0950,
                take_profit=1.1150,
                opened_at=datetime.now(timezone.utc)
            ),
            Position(
                position_id="pos2",
                symbol="AUD/CAD",  # Not in correlation matrix
                direction=Direction.SHORT,
                quantity=1000.0,
                entry_price=0.9000,
                current_price=0.8980,
                unrealized_pnl=2.0,  # (0.9000 - 0.8980) * 1000 = 2.0 (rounded)
                stop_loss=0.9050,
                take_profit=0.8900,
                opened_at=datetime.now(timezone.utc)
            )
        ]
        
        risks = monitor.assess_correlation_risk(positions)
        # Should have low/no correlation risk
        high_risk = [risk for risk in risks if risk.risk_level == "HIGH"]
        assert len(high_risk) == 0
    
    def test_circuit_breaker_recovery(self, monitor, sample_portfolio):
        """Test circuit breaker recovery process"""
        # Trigger circuit breaker
        sample_portfolio.equity = 10000.0
        monitor.update_equity(sample_portfolio)
        
        sample_portfolio.equity = 8500.0  # 15% drawdown
        monitor.update_equity(sample_portfolio)
        
        # Trigger circuit breaker by checking if trading should be halted
        should_halt = monitor.should_halt_trading(sample_portfolio)
        assert should_halt is True
        assert monitor.circuit_breaker_state == CircuitBreakerState.OPEN
        
        # Partial recovery to half-open
        sample_portfolio.equity = 9200.0  # 8% drawdown (below 10% - 2% = 8%)
        monitor.update_equity(sample_portfolio)
        
        assert monitor.circuit_breaker_state == CircuitBreakerState.HALF_OPEN
        
        # Full recovery to closed
        sample_portfolio.equity = 9700.0  # 3% drawdown (below 10% - 4% = 6%)
        monitor.update_equity(sample_portfolio)
        
        assert monitor.circuit_breaker_state == CircuitBreakerState.CLOSED
    
    def test_reset_circuit_breaker(self, monitor):
        """Test manual circuit breaker reset"""
        # Set to open state
        monitor.circuit_breaker_state = CircuitBreakerState.OPEN
        
        # Reset should move to half-open
        result = monitor.reset_circuit_breaker()
        assert result is True
        assert monitor.circuit_breaker_state == CircuitBreakerState.HALF_OPEN
        
        # Reset when not open should return False
        result = monitor.reset_circuit_breaker()
        assert result is False
    
    def test_get_recent_alerts(self, monitor, sample_portfolio):
        """Test getting recent alerts"""
        # Trigger some alerts
        sample_portfolio.equity = 10000.0
        monitor.update_equity(sample_portfolio)
        
        # Create warning level drawdown
        sample_portfolio.equity = 9400.0  # 6% drawdown (above 5% warning)
        monitor.update_equity(sample_portfolio)
        
        alerts = monitor.get_recent_alerts(24)
        assert len(alerts) > 0
        
        # Check alert properties
        warning_alerts = [alert for alert in alerts if alert.severity == "WARNING"]
        assert len(warning_alerts) > 0
    
    def test_equity_history_cleanup(self, monitor, sample_portfolio):
        """Test equity history cleanup after monitoring window"""
        # Mock datetime to control time
        with patch('src.risk.drawdown_monitor.datetime') as mock_datetime:
            base_time = datetime.now(timezone.utc)
            mock_datetime.now.return_value = base_time
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)
            
            # Add old equity point
            old_time = base_time - timedelta(hours=25)  # Older than 24h window
            monitor.equity_history.append(EquityPoint(
                timestamp=old_time,
                balance=10000.0,
                equity=10000.0,
                drawdown=0.0
            ))
            
            # Update with current time
            monitor.update_equity(sample_portfolio)
            
            # Old history should be cleaned up
            assert len(monitor.equity_history) == 1
            assert monitor.equity_history[0].timestamp >= base_time - timedelta(hours=24)


class TestCircuitBreakerManager:
    """Test CircuitBreakerManager functionality"""
    
    @pytest.fixture
    def manager(self):
        """Create test manager"""
        return CircuitBreakerManager()
    
    @pytest.fixture
    def monitor1(self):
        """Create first test monitor"""
        config = DrawdownConfig(max_drawdown_percent=10.0)
        return DrawdownMonitor(config)
    
    @pytest.fixture
    def monitor2(self):
        """Create second test monitor"""
        config = DrawdownConfig(max_drawdown_percent=15.0)
        return DrawdownMonitor(config)
    
    @pytest.fixture
    def sample_portfolio(self):
        """Create sample portfolio"""
        return Portfolio(
            account_id="test_account",
            balance=10000.0,
            equity=10000.0,
            margin_used=1000.0,
            margin_available=9000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
    
    def test_add_remove_monitor(self, manager, monitor1):
        """Test adding and removing monitors"""
        # Add monitor
        manager.add_monitor("test_monitor", monitor1)
        assert "test_monitor" in manager.monitors
        assert manager.monitors["test_monitor"] is monitor1
        
        # Remove monitor
        result = manager.remove_monitor("test_monitor")
        assert result is True
        assert "test_monitor" not in manager.monitors
        
        # Remove non-existent monitor
        result = manager.remove_monitor("non_existent")
        assert result is False
    
    def test_update_all_monitors(self, manager, monitor1, monitor2, sample_portfolio):
        """Test updating all monitors"""
        manager.add_monitor("monitor1", monitor1)
        manager.add_monitor("monitor2", monitor2)
        
        # Update all monitors
        manager.update_all_monitors(sample_portfolio)
        
        # Both monitors should have equity history
        assert len(monitor1.equity_history) == 1
        assert len(monitor2.equity_history) == 1
    
    def test_is_trading_allowed_all_ok(self, manager, monitor1, monitor2):
        """Test trading allowed when all monitors are OK"""
        manager.add_monitor("monitor1", monitor1)
        manager.add_monitor("monitor2", monitor2)
        
        assert manager.is_trading_allowed() is True
    
    def test_is_trading_allowed_one_halted(self, manager, monitor1, monitor2):
        """Test trading not allowed when one monitor is halted"""
        monitor1.circuit_breaker_state = CircuitBreakerState.OPEN
        
        manager.add_monitor("monitor1", monitor1)
        manager.add_monitor("monitor2", monitor2)
        
        assert manager.is_trading_allowed() is False
    
    def test_is_trading_allowed_global_halt(self, manager, monitor1):
        """Test trading not allowed during global halt"""
        manager.add_monitor("monitor1", monitor1)
        manager.global_halt = True
        
        assert manager.is_trading_allowed() is False
    
    def test_should_halt_trading(self, manager, monitor1, monitor2, sample_portfolio):
        """Test should halt trading decision"""
        manager.add_monitor("monitor1", monitor1)
        manager.add_monitor("monitor2", monitor2)
        
        # Set up one monitor to require halt
        sample_portfolio.equity = 10000.0
        monitor1.update_equity(sample_portfolio)
        
        sample_portfolio.equity = 8500.0  # 15% drawdown
        monitor1.update_equity(sample_portfolio)
        
        # Should halt due to monitor1
        assert manager.should_halt_trading(sample_portfolio) is True
        assert len(manager.halt_reasons) > 0
    
    def test_emergency_halt(self, manager):
        """Test emergency halt functionality"""
        manager.emergency_halt("System error detected")
        
        assert manager.global_halt is True
        assert "EMERGENCY: System error detected" in manager.halt_reasons
        assert manager.is_trading_allowed() is False
    
    def test_reset_emergency_halt(self, manager):
        """Test resetting emergency halt"""
        manager.emergency_halt("Test emergency")
        assert manager.global_halt is True
        
        manager.reset_emergency_halt()
        assert manager.global_halt is False
        assert "EMERGENCY" not in str(manager.halt_reasons)
    
    def test_get_system_status(self, manager, monitor1, monitor2, sample_portfolio):
        """Test getting system status"""
        manager.add_monitor("monitor1", monitor1)
        manager.add_monitor("monitor2", monitor2)
        
        # Update monitors
        manager.update_all_monitors(sample_portfolio)
        
        status = manager.get_system_status()
        
        assert "trading_allowed" in status
        assert "global_halt" in status
        assert "halt_reasons" in status
        assert "monitors" in status
        
        assert "monitor1" in status["monitors"]
        assert "monitor2" in status["monitors"]
        
        # Check monitor status details
        monitor1_status = status["monitors"]["monitor1"]
        assert "state" in monitor1_status
        assert "current_drawdown" in monitor1_status
        assert "daily_drawdown" in monitor1_status
        assert "peak_equity" in monitor1_status
        assert "recent_alerts" in monitor1_status
    
    def test_get_halt_reasons(self, manager, monitor1):
        """Test getting halt reasons"""
        manager.add_monitor("monitor1", monitor1)
        
        # Create sample portfolio to trigger halt check
        sample_portfolio = Portfolio(
            account_id="test",
            balance=10000.0,
            equity=10000.0,  # Start with high equity
            margin_used=1000.0,
            margin_available=9000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        # First update to establish peak
        monitor1.update_equity(sample_portfolio)
        
        # Create drawdown condition
        sample_portfolio.equity = 8000.0  # 20% drawdown
        monitor1.update_equity(sample_portfolio)
        
        # Check if trading should be halted
        should_halt = manager.should_halt_trading(sample_portfolio)
        reasons = manager.get_halt_reasons()
        
        assert should_halt is True
        assert len(reasons) > 0
        assert any("monitor1" in reason for reason in reasons)


if __name__ == "__main__":
    pytest.main([__file__])
"""Unit tests for risk calculator"""

import pytest
from datetime import datetime, timedelta, timezone
from src.risk.risk_calculator import RiskCalculator, RiskConfig, EquityPoint
from src.models import (
    TradingSignal, Portfolio, Position, Direction, MarketData, RiskAssessment
)
from src.exceptions import DataValidationError


class TestRiskConfig:
    """Test risk configuration"""
    
    def test_valid_config(self):
        """Test valid configuration creation"""
        config = RiskConfig(
            max_portfolio_risk=0.02,
            max_correlation=0.7,
            max_drawdown=0.15,
            max_positions=5,
            max_exposure_per_currency=0.3
        )
        assert config.max_portfolio_risk == 0.02
        assert config.max_correlation == 0.7
    
    def test_invalid_portfolio_risk(self):
        """Test invalid portfolio risk"""
        with pytest.raises(DataValidationError) as exc_info:
            RiskConfig(max_portfolio_risk=0.15)  # Too high
        assert exc_info.value.error_code == "INVALID_MAX_PORTFOLIO_RISK"
    
    def test_invalid_correlation(self):
        """Test invalid correlation limit"""
        with pytest.raises(DataValidationError) as exc_info:
            RiskConfig(max_correlation=1.5)  # Too high
        assert exc_info.value.error_code == "INVALID_MAX_CORRELATION"
    
    def test_invalid_drawdown(self):
        """Test invalid drawdown limit"""
        with pytest.raises(DataValidationError) as exc_info:
            RiskConfig(max_drawdown=0.8)  # Too high
        assert exc_info.value.error_code == "INVALID_MAX_DRAWDOWN"
    
    def test_invalid_max_positions(self):
        """Test invalid max positions"""
        with pytest.raises(DataValidationError) as exc_info:
            RiskConfig(max_positions=0)  # Too low
        assert exc_info.value.error_code == "INVALID_MAX_POSITIONS"


class TestEquityPoint:
    """Test equity point data structure"""
    
    def test_valid_equity_point(self):
        """Test valid equity point creation"""
        point = EquityPoint(
            timestamp=datetime.now(timezone.utc),
            balance=10000.0,
            equity=10500.0,
            drawdown=0.05
        )
        assert point.balance == 10000.0
        assert point.equity == 10500.0
    
    def test_negative_balance(self):
        """Test negative balance validation"""
        with pytest.raises(DataValidationError) as exc_info:
            EquityPoint(
                timestamp=datetime.now(timezone.utc),
                balance=-1000.0,
                equity=9000.0,
                drawdown=0.0
            )
        assert exc_info.value.error_code == "NEGATIVE_BALANCE"
    
    def test_invalid_drawdown(self):
        """Test invalid drawdown value"""
        with pytest.raises(DataValidationError) as exc_info:
            EquityPoint(
                timestamp=datetime.now(timezone.utc),
                balance=10000.0,
                equity=10000.0,
                drawdown=1.5  # Too high
            )
        assert exc_info.value.error_code == "INVALID_DRAWDOWN"
    
    def test_future_timestamp(self):
        """Test future timestamp validation"""
        with pytest.raises(DataValidationError) as exc_info:
            EquityPoint(
                timestamp=datetime.now(timezone.utc) + timedelta(days=1),
                balance=10000.0,
                equity=10000.0,
                drawdown=0.0
            )
        assert exc_info.value.error_code == "FUTURE_TIMESTAMP"


class TestRiskCalculator:
    """Test risk calculator functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = RiskConfig(
            max_portfolio_risk=0.02,
            max_correlation=0.7,
            max_drawdown=0.15,
            max_positions=3,
            max_exposure_per_currency=0.3
        )
        self.calculator = RiskCalculator(self.config)
        
        self.signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.8,
            reasoning="Test signal",
            timestamp=datetime.now(timezone.utc)
        )
        
        self.portfolio = Portfolio(
            account_id="TEST123",
            balance=10000.0,
            equity=10500.0,
            margin_used=500.0,
            margin_available=10000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
    
    def test_assess_trade_risk_valid(self):
        """Test risk assessment for valid trade"""
        assessment = self.calculator.assess_trade_risk(self.signal, self.portfolio)
        
        assert isinstance(assessment, RiskAssessment)
        assert assessment.is_valid is True
        assert 0.0 <= assessment.risk_score <= 1.0
        assert assessment.position_size > 0
    
    def test_assess_trade_risk_max_positions(self):
        """Test risk assessment when max positions reached"""
        # Add positions to reach limit
        positions = []
        for i in range(self.config.max_positions):
            symbol = "EUR/USD" if i % 2 == 0 else "GBP/USD"
            entry = 1.1000 if symbol == "EUR/USD" else 1.3000
            curr = 1.1050 if symbol == "EUR/USD" else 1.2950
            pnl = (curr - entry) * 1000.0
            position = Position(
                position_id=f"POS{i}",
                symbol=symbol,
                direction=Direction.LONG,
                quantity=1000.0,
                entry_price=entry,
                current_price=curr,
                unrealized_pnl=pnl,
                stop_loss=entry - 0.01,
                take_profit=entry + 0.02,
                opened_at=datetime.now(timezone.utc)
            )
            positions.append(position)
        
        portfolio_full = Portfolio(
            account_id="TEST123",
            balance=10000.0,
            equity=10500.0,
            margin_used=3000.0,
            margin_available=7500.0,
            positions=positions,
            updated_at=datetime.now(timezone.utc)
        )
        
        assessment = self.calculator.assess_trade_risk(self.signal, portfolio_full)
        
        assert assessment.risk_score > 0.15  # Should have higher risk (0.17 from position limits)
        assert any("Maximum number of positions" in warning for warning in assessment.warnings)
    
    def test_assess_trade_risk_high_correlation(self):
        """Test risk assessment with high correlation"""
        # Add position in same symbol
        existing_position = Position(
            position_id="POS1",
            symbol="EUR/USD",  # Same as signal
            direction=Direction.LONG,
            quantity=1000.0,
            entry_price=1.0950,
            current_price=1.1000,
            unrealized_pnl=(1.1000 - 1.0950) * 1000.0,  # 5.0
            stop_loss=1.0850,
            take_profit=1.1150,
            opened_at=datetime.now(timezone.utc)
        )
        
        portfolio_with_position = Portfolio(
            account_id="TEST123",
            balance=10000.0,
            equity=10500.0,
            margin_used=1000.0,
            margin_available=9500.0,
            positions=[existing_position],
            updated_at=datetime.now(timezone.utc)
        )
        
        assessment = self.calculator.assess_trade_risk(self.signal, portfolio_with_position)
        
        assert assessment.risk_score > 0.01  # Should have higher risk (0.02 from correlation warning)
        assert any("Already have position" in warning for warning in assessment.warnings)
    
    def test_calculate_portfolio_exposure(self):
        """Test portfolio exposure calculation"""
        # Create positions in different currency pairs
        positions = [
            Position(
                position_id="POS1",
                symbol="EUR/USD",
                direction=Direction.LONG,
                quantity=1000.0,
                entry_price=1.1000,
                current_price=1.1050,
                unrealized_pnl=(1.1050 - 1.1000) * 1000.0,  # 5.0
                stop_loss=1.0900,
                take_profit=1.1200,
                opened_at=datetime.now(timezone.utc)
            ),
            Position(
                position_id="POS2",
                symbol="GBP/USD",
                direction=Direction.SHORT,
                quantity=800.0,
                entry_price=1.3000,
                current_price=1.2950,
                unrealized_pnl=(1.3000 - 1.2950) * 800.0,  # 4.0
                stop_loss=1.3100,
                take_profit=1.2800,
                opened_at=datetime.now(timezone.utc)
            )
        ]
        
        portfolio_with_positions = Portfolio(
            account_id="TEST123",
            balance=10000.0,
            equity=10500.0,
            margin_used=2000.0,
            margin_available=8500.0,
            positions=positions,
            updated_at=datetime.now(timezone.utc)
        )
        
        exposures = self.calculator.calculate_portfolio_exposure(portfolio_with_positions)
        
        assert "EUR" in exposures
        assert "USD" in exposures
        assert "GBP" in exposures
        assert all(exposure >= 0 for exposure in exposures.values())
    
    def test_update_equity_curve(self):
        """Test equity curve updating"""
        # Initial update
        self.calculator.update_equity_curve(self.portfolio)
        assert len(self.calculator.equity_curve) == 1
        assert self.calculator.peak_equity == self.portfolio.equity
        
        # Update with higher equity
        higher_portfolio = Portfolio(
            account_id="TEST123",
            balance=11000.0,
            equity=11500.0,
            margin_used=500.0,
            margin_available=11000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        self.calculator.update_equity_curve(higher_portfolio)
        assert len(self.calculator.equity_curve) == 2
        assert self.calculator.peak_equity == 11500.0
        
        # Update with lower equity (drawdown)
        lower_portfolio = Portfolio(
            account_id="TEST123",
            balance=9500.0,
            equity=10000.0,
            margin_used=500.0,
            margin_available=9500.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        self.calculator.update_equity_curve(lower_portfolio)
        assert len(self.calculator.equity_curve) == 3
        
        # Check drawdown calculation
        current_drawdown = self.calculator.get_current_drawdown()
        expected_drawdown = (11500.0 - 10000.0) / 11500.0
        assert abs(current_drawdown - expected_drawdown) < 0.01
    
    def test_get_max_drawdown(self):
        """Test maximum drawdown calculation"""
        # Create equity curve with drawdown
        equity_values = [10000, 11000, 10500, 9500, 9000, 9500, 10000]
        
        for i, equity in enumerate(equity_values):
            portfolio = Portfolio(
                account_id="TEST123",
                balance=equity - 500,
                equity=equity,
                margin_used=500.0,
                margin_available=equity - 500,
                positions=[],
                updated_at=datetime.now(timezone.utc) - timedelta(days=len(equity_values)-i)
            )
            self.calculator.update_equity_curve(portfolio)
        
        max_drawdown = self.calculator.get_max_drawdown(days=30)
        
        # Max drawdown should be from peak (11000) to trough (9000)
        expected_max_dd = (11000 - 9000) / 11000
        assert abs(max_drawdown - expected_max_dd) < 0.01
    
    def test_assess_drawdown_risk(self):
        """Test drawdown risk assessment"""
        # Create high drawdown scenario
        high_dd_portfolio = Portfolio(
            account_id="TEST123",
            balance=8500.0,
            equity=8500.0,
            margin_used=0.0,
            margin_available=8500.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        # Set peak equity high to create large drawdown
        self.calculator.peak_equity = 10000.0
        self.calculator.update_equity_curve(high_dd_portfolio)
        
        assessment = self.calculator.assess_trade_risk(self.signal, high_dd_portfolio)
        
        # Should have high risk due to drawdown
        assert assessment.risk_score > 0.3  # Should have higher risk (0.32 from drawdown)
        assert any("drawdown" in warning.lower() for warning in assessment.warnings)
    
    def test_currency_correlation_estimation(self):
        """Test currency correlation estimation"""
        # Same pair should have high correlation
        corr_same = self.calculator._estimate_currency_correlation("EUR/USD", "EUR/USD")
        assert corr_same == 1.0
        
        # Inverse pairs should have high correlation
        corr_inverse = self.calculator._estimate_currency_correlation("EUR/USD", "USD/EUR")
        assert corr_inverse == 0.9
        
        # Pairs sharing one currency should have medium correlation
        corr_shared = self.calculator._estimate_currency_correlation("EUR/USD", "EUR/GBP")
        assert corr_shared == 0.6
        
        # Unrelated pairs should have low correlation
        corr_unrelated = self.calculator._estimate_currency_correlation("EUR/USD", "GBP/JPY")
        assert corr_unrelated == 0.1
    
    def test_assess_exposure_risk(self):
        """Test exposure risk assessment"""
        # Create signal that would cause high EUR exposure
        high_eur_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.8,  # Very high position size to trigger exposure warning
            confidence=0.8,
            reasoning="High EUR exposure test",
            timestamp=datetime.now(timezone.utc)
        )
        
        # Portfolio already has EUR exposure
        eur_position = Position(
            position_id="POS1",
            symbol="EUR/GBP",
            direction=Direction.LONG,
            quantity=5000.0,  # Increase quantity to create more EUR exposure
            entry_price=0.8500,
            current_price=0.8550,
            unrealized_pnl=(0.8550 - 0.8500) * 5000.0,  # 25.0
            stop_loss=0.8400,
            take_profit=0.8700,
            opened_at=datetime.now(timezone.utc)
        )
        
        portfolio_with_eur = Portfolio(
            account_id="TEST123",
            balance=10000.0,
            equity=10500.0,
            margin_used=4275.0,  # Updated margin used
            margin_available=6225.0,  # Updated margin available
            positions=[eur_position],
            updated_at=datetime.now(timezone.utc)
        )
        
        assessment = self.calculator.assess_trade_risk(high_eur_signal, portfolio_with_eur)
        
        # Should detect high exposure risk
        assert assessment.risk_score > 0.01  # Should have higher risk (0.02 from correlation warning)
        assert any("exposure" in warning.lower() for warning in assessment.warnings)
    
    def test_invalid_inputs(self):
        """Test handling of invalid inputs"""
        # Invalid signal type
        assessment = self.calculator.assess_trade_risk("invalid", self.portfolio)
        assert assessment.is_valid is False
        assert assessment.risk_score == 1.0
        assert any("CRITICAL" in warning for warning in assessment.warnings)
        
        # Invalid portfolio type
        assessment = self.calculator.assess_trade_risk(self.signal, "invalid")
        assert assessment.is_valid is False
        assert assessment.risk_score == 1.0
        assert any("CRITICAL" in warning for warning in assessment.warnings)
    
    def test_account_performance_metrics(self):
        """Test account performance metrics calculation"""
        # Update equity curve with some data points
        portfolios = []
        for i in range(10):
            equity = 10000 + (i * 100) + ((-1) ** i * 50)  # Varying equity
            portfolio = Portfolio(
                account_id="test_account",
                balance=10000.0,
                equity=equity,
                margin_used=1000.0,
                margin_available=equity - 1000.0,
                positions=[],
                updated_at=datetime.now(timezone.utc)
            )
            portfolios.append(portfolio)
            self.calculator.update_equity_curve(portfolio)
        
        metrics = self.calculator.get_account_performance_metrics()
        
        assert isinstance(metrics, dict)
        assert 'total_return' in metrics
        assert 'max_drawdown' in metrics
        assert 'current_drawdown' in metrics
        assert 'peak_equity' in metrics
        assert 'volatility' in metrics
        assert 'sharpe_ratio' in metrics
        
        # Check that metrics are reasonable
        assert -1.0 <= metrics['total_return'] <= 10.0  # Reasonable return range
        assert 0.0 <= metrics['max_drawdown'] <= 1.0
        assert 0.0 <= metrics['current_drawdown'] <= 1.0
        assert metrics['peak_equity'] >= 10000.0
        assert metrics['volatility'] >= 0.0
    
    def test_balance_history(self):
        """Test balance history tracking"""
        # Update equity curve with some data points
        for i in range(5):
            portfolio = Portfolio(
                account_id="test_account",
                balance=10000.0 + (i * 100),
                equity=10000.0 + (i * 150),
                margin_used=1000.0,
                margin_available=9000.0 + (i * 150),
                positions=[],
                updated_at=datetime.now(timezone.utc)
            )
            self.calculator.update_equity_curve(portfolio)
        
        # Get balance history
        history = self.calculator.get_balance_history(days=1)
        
        assert len(history) == 5
        assert all('balance' in snapshot for snapshot in history)
        assert all('equity' in snapshot for snapshot in history)
        assert all('timestamp' in snapshot for snapshot in history)
        assert all('total_return' in snapshot for snapshot in history)
        
        # Check that balances are increasing
        balances = [snapshot['balance'] for snapshot in history]
        assert balances == sorted(balances)  # Should be in ascending order
    
    def test_kelly_position_sizing_integration(self):
        """Test Kelly criterion position sizing with risk management overlay"""
        # Create some trade history
        from src.risk.position_sizer import TradeHistory
        
        trade_history = []
        for i in range(20):
            # 60% winners
            if i < 12:
                exit_price = 1.1000 + 0.0030
                pnl = (exit_price - 1.1000) * 1000
                win = True
            else:
                exit_price = 1.1000 - 0.0020
                pnl = (exit_price - 1.1000) * 1000
                win = False
            
            trade = TradeHistory(
                symbol="EUR/USD",
                direction=Direction.LONG,
                entry_price=1.1000,
                exit_price=exit_price,
                quantity=1000,
                pnl=pnl,
                win=win,
                timestamp=datetime.now(timezone.utc) - timedelta(days=i)
            )
            trade_history.append(trade)
        
        # Calculate position size with Kelly
        position_size = self.calculator.calculate_position_size_with_kelly(
            self.signal, self.portfolio, trade_history
        )
        
        assert position_size >= 0.0
        assert position_size <= 0.1  # Should not exceed 10%
    
    def test_empty_performance_metrics(self):
        """Test performance metrics with no equity curve data"""
        empty_calculator = RiskCalculator(self.config)
        metrics = empty_calculator.get_account_performance_metrics()
        
        assert metrics['total_return'] == 0.0
        assert metrics['max_drawdown'] == 0.0
        assert metrics['current_drawdown'] == 0.0
        assert metrics['peak_equity'] == 0.0
        assert metrics['volatility'] == 0.0
        assert metrics['sharpe_ratio'] == 0.0


if __name__ == "__main__":
    pytest.main([__file__])
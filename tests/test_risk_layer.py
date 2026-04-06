import unittest
from datetime import datetime, timezone
import logging

from src.risk.risk_calculator import RiskCalculator, RiskConfig
from src.models import TradingSignal, Portfolio, Position, Direction, MarketData, OrderStatus

class TestRiskLayer(unittest.TestCase):
    def setUp(self):
        self.config = RiskConfig(
            max_portfolio_risk=0.01,
            max_exposure_per_currency=0.05,
            max_drawdown=0.10,
            max_total_positions=5
        )
        self.risk_calculator = RiskCalculator(self.config)
        
        # Test Portfolio
        self.portfolio = Portfolio(
            account_id="12345678",
            balance=100000.0,
            equity=100000.0,
            margin_used=0.0,
            margin_available=100000.0,
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )

    def test_risk_assessment_no_market_data(self):
        """Test risk assessment works even when market_data is None (should not raise NameError)"""
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.0850,
            stop_loss=1.0800,
            take_profit=1.1000,
            position_size=0.01,
            confidence=0.8,
            reasoning="Test",
            timestamp=datetime.now(timezone.utc),
            rr_ratio=3.0
        )
        
        # This used to raise NameError in v10
        assessment = self.risk_calculator.assess_trade_risk(
            signal=signal,
            portfolio=self.portfolio,
            market_data=None
        )
        
        self.assertTrue(hasattr(assessment, 'is_valid'))
        self.assertIsInstance(assessment.risk_score, float)

    def test_risk_assessment_with_market_data(self):
        """Test risk assessment with explicit market data"""
        signal = TradingSignal(
            symbol="GBP/USD",
            direction=Direction.LONG,
            entry_price=1.2650,
            stop_loss=1.2600,
            take_profit=1.2800,
            position_size=0.01,
            confidence=0.8,
            reasoning="Test",
            timestamp=datetime.now(timezone.utc),
            rr_ratio=3.0
        )
        
        market_data = {
            "GBP/USD": MarketData(
                symbol="GBP/USD", 
                timestamp=datetime.now(timezone.utc),
                open=1.2650, high=1.2660, low=1.2640, close=1.2650, 
                volume=100, bid=1.2650, ask=1.2651, 
                spread=0.0001
            ),
            "EUR/USD": MarketData(
                symbol="EUR/USD", 
                timestamp=datetime.now(timezone.utc),
                open=1.0850, high=1.0860, low=1.0840, close=1.0850, 
                volume=100, bid=1.0850, ask=1.0851, 
                spread=0.0001
            )
        }
        
        assessment = self.risk_calculator.assess_trade_risk(
            signal=signal,
            portfolio=self.portfolio,
            market_data=market_data
        )
        
        # With 0.01 lots, exposure is ~1.26%, which is below 5% limit
        self.assertTrue(assessment.is_valid)
        self.assertLess(assessment.risk_score, 0.7)

    def test_exposure_calculation_fallbacks(self):
        """Test that exposure calculation handles missing conversion prices gracefully"""
        position = Position(
            position_id="123",
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.0800,
            current_price=1.0810,
            stop_loss=1.0750,
            take_profit=1.1000,
            quantity=0.1,
            unrealized_pnl=10.0, 
            opened_at=datetime.now(timezone.utc),
            magic=12345
        )
        self.portfolio.positions.append(position)
        
        exposure = self.risk_calculator.calculate_portfolio_exposure(self.portfolio, market_data={})
        
        self.assertIn("EUR", exposure)
        self.assertIn("USD", exposure)

if __name__ == "__main__":
    unittest.main()

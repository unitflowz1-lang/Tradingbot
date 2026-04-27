"""Unit tests for position sizing algorithms"""

import pytest
from datetime import datetime, timedelta, timezone
from src.risk.position_sizer import (
    PositionSizer, FixedFractionalSizer, KellyCriterionSizer, AdaptivePositionSizer,
    PositionSizingConfig, TradeHistory
)
from src.models import TradingSignal, Direction
from src.exceptions import DataValidationError


class TestPositionSizingConfig:
    """Test position sizing configuration"""
    
    def test_valid_config(self):
        """Test valid configuration creation"""
        config = PositionSizingConfig(
            max_risk_per_trade=0.02,
            max_position_size=0.1,
            kelly_lookback_periods=100,
            fixed_fraction=0.02,
            min_position_size=0.001
        )
        assert config.max_risk_per_trade == 0.02
        assert config.max_position_size == 0.1
    
    def test_invalid_max_risk(self):
        """Test invalid max risk per trade"""
        with pytest.raises(DataValidationError) as exc_info:
            PositionSizingConfig(max_risk_per_trade=0.15)  # Too high
        assert exc_info.value.error_code == "INVALID_MAX_RISK"
        
        with pytest.raises(DataValidationError) as exc_info:
            PositionSizingConfig(max_risk_per_trade=0.0)  # Too low
        assert exc_info.value.error_code == "INVALID_MAX_RISK"
    
    def test_invalid_max_position_size(self):
        """Test invalid max position size"""
        with pytest.raises(DataValidationError) as exc_info:
            PositionSizingConfig(max_position_size=1.5)  # Too high
        assert exc_info.value.error_code == "INVALID_MAX_POSITION_SIZE"
    
    def test_invalid_kelly_lookback(self):
        """Test invalid Kelly lookback periods"""
        with pytest.raises(DataValidationError) as exc_info:
            PositionSizingConfig(kelly_lookback_periods=5)  # Too low
        assert exc_info.value.error_code == "INVALID_KELLY_LOOKBACK"
        
        with pytest.raises(DataValidationError) as exc_info:
            PositionSizingConfig(kelly_lookback_periods=2000)  # Too high
        assert exc_info.value.error_code == "INVALID_KELLY_LOOKBACK"


class TestTradeHistory:
    """Test trade history data structure"""
    
    def test_valid_long_trade(self):
        """Test valid long trade history"""
        trade = TradeHistory(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            exit_price=1.1100,
            quantity=10000,
            pnl=100.0,  # (1.1100 - 1.1000) * 10000 = 0.01 * 10000 = 100
            win=True,
            timestamp=datetime.now(timezone.utc)
        )
        assert trade.symbol == "EUR/USD"
        assert trade.win is True
    
    def test_valid_short_trade(self):
        """Test valid short trade history"""
        trade = TradeHistory(
            symbol="GBP/USD",
            direction=Direction.SHORT,
            entry_price=1.3000,
            exit_price=1.2900,
            quantity=5000,
            pnl=50.0,  # (1.3000 - 1.2900) * 5000 = 0.01 * 5000 = 50
            win=True,
            timestamp=datetime.now(timezone.utc)
        )
        assert trade.direction == Direction.SHORT
        assert trade.pnl == 50.0
    
    def test_invalid_pnl_calculation(self):
        """Test invalid PnL calculation"""
        with pytest.raises(DataValidationError) as exc_info:
            TradeHistory(
                symbol="EUR/USD",
                direction=Direction.LONG,
                entry_price=1.1000,
                exit_price=1.1100,
                quantity=10000,
                pnl=50.0,  # Wrong PnL, should be 100.0
                win=True,
                timestamp=datetime.now(timezone.utc)
            )
        assert exc_info.value.error_code == "INVALID_PNL"
    
    def test_invalid_win_flag(self):
        """Test invalid win flag"""
        with pytest.raises(DataValidationError) as exc_info:
            TradeHistory(
                symbol="EUR/USD",
                direction=Direction.LONG,
                entry_price=1.1000,
                exit_price=1.0900,  # Loss
                quantity=10000,
                pnl=-100.0,  # Correct PnL: (1.0900 - 1.1000) * 10000 = -100
                win=True,  # Should be False for loss
                timestamp=datetime.now(timezone.utc)
            )
        assert exc_info.value.error_code == "INVALID_WIN_FLAG"
    
    def test_empty_symbol(self):
        """Test empty symbol validation"""
        with pytest.raises(DataValidationError) as exc_info:
            TradeHistory(
                symbol="",
                direction=Direction.LONG,
                entry_price=1.1000,
                exit_price=1.1100,
                quantity=10000,
                pnl=100.0,
                win=True,
                timestamp=datetime.now(timezone.utc)
            )
        assert exc_info.value.error_code == "EMPTY_SYMBOL"


class TestFixedFractionalSizer:
    """Test fixed fractional position sizing"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = PositionSizingConfig(
            max_risk_per_trade=0.02,
            max_position_size=0.1,
            min_position_size=0.001
        )
        self.sizer = FixedFractionalSizer(self.config)
        
        self.signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,  # 100 pips stop
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.8,
            reasoning="Test signal",
            timestamp=datetime.now(timezone.utc)
        )
    
    def test_basic_position_sizing(self):
        """Test basic position size calculation"""
        account_balance = 10000.0
        
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance
        )
        
        # Risk amount = 10000 * 0.02 = 200
        # Stop distance = 1.1000 - 1.0900 = 0.01
        # Position units = 200 / 0.01 = 20000 units
        # Position value = 20000 * 1.1000 = 22000
        # Position fraction = 22000 / 10000 = 2.2, but limited by max_position_size
        # With confidence 0.8: 0.1 * 0.8 = 0.08 (after limits applied)
        
        assert position_size > 0
        assert position_size <= self.config.max_position_size
    
    def test_confidence_adjustment(self):
        """Test confidence adjustment in position sizing"""
        account_balance = 100.0  # Very small balance to see confidence effect
        
        # High confidence signal with wider stop to reduce position size
        high_conf_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0000,  # 1000 pips stop
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.9,
            reasoning="High confidence test",
            timestamp=datetime.now(timezone.utc)
        )
        
        # Low confidence signal with wider stop to reduce position size
        low_conf_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0000,  # 1000 pips stop
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.3,
            reasoning="Low confidence test",
            timestamp=datetime.now(timezone.utc)
        )
        
        high_size = self.sizer.calculate_position_size(high_conf_signal, account_balance)
        low_size = self.sizer.calculate_position_size(low_conf_signal, account_balance)
        
        assert high_size > low_size
    
    def test_invalid_stop_distance(self):
        """Test invalid stop loss distance"""
        # Create a signal with invalid stop loss (this should fail at TradingSignal validation)
        with pytest.raises(DataValidationError) as exc_info:
            TradingSignal(
                symbol="EUR/USD",
                direction=Direction.LONG,
                entry_price=1.1000,
                stop_loss=1.1100,  # Above entry price
                take_profit=1.1200,
                position_size=0.05,
                confidence=0.8,
                reasoning="Invalid stop test",
                timestamp=datetime.now(timezone.utc)
            )
        assert exc_info.value.error_code == "INVALID_STOP_LOSS"
    
    def test_position_size_limits(self):
        """Test position size limits are applied"""
        account_balance = 1000.0  # Small balance
        
        # Signal with very tight stop (would result in large position)
        tight_stop_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0999,  # Very tight stop
            take_profit=1.1200,
            position_size=0.05,
            confidence=1.0,
            reasoning="Tight stop test",
            timestamp=datetime.now(timezone.utc)
        )
        
        position_size = self.sizer.calculate_position_size(tight_stop_signal, account_balance)
        
        # Should be limited by max_position_size
        assert position_size <= self.config.max_position_size
        assert position_size >= self.config.min_position_size


class TestKellyCriterionSizer:
    """Test Kelly Criterion position sizing"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = PositionSizingConfig(
            max_risk_per_trade=0.02,
            kelly_lookback_periods=50
        )
        self.sizer = KellyCriterionSizer(self.config)
        
        self.signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.8,
            reasoning="Kelly test signal",
            timestamp=datetime.now(timezone.utc)
        )
    
    def test_insufficient_history_fallback(self):
        """Test fallback to fixed fractional with insufficient history"""
        account_balance = 10000.0
        
        # No history
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance, trade_history=[]
        )
        
        # Should fall back to fixed fractional
        assert position_size > 0
        
        # Insufficient history (less than 10 trades)
        short_history = []
        for i in range(5):
            pnl = (1.1100 - 1.1000) * 1000  # Correct PnL calculation
            trade = TradeHistory(
                symbol="EUR/USD",
                direction=Direction.LONG,
                entry_price=1.1000,
                exit_price=1.1100,
                quantity=1000,
                pnl=pnl,
                win=True,
                timestamp=datetime.now(timezone.utc) - timedelta(days=i)
            )
            short_history.append(trade)
        
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance, trade_history=short_history
        )
        
        assert position_size > 0
    
    def test_kelly_calculation_with_history(self):
        """Test Kelly calculation with sufficient history"""
        account_balance = 10000.0
        
        # Create profitable trade history
        profitable_history = []
        for i in range(20):
            # 70% winners
            if i < 14:
                exit_price = 1.1000 + (i % 3 + 1) * 0.0050  # Varying profits
                pnl = (exit_price - 1.1000) * 1000
                win = True
            else:
                exit_price = 1.1000 - (i % 2 + 1) * 0.0030  # Varying losses
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
            profitable_history.append(trade)
        
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance, trade_history=profitable_history
        )
        
        assert position_size > 0
        assert position_size <= self.config.max_position_size
    
    def test_kelly_with_losing_history(self):
        """Test Kelly calculation with losing history"""
        account_balance = 10000.0
        
        # Create losing trade history
        losing_history = []
        for i in range(20):
            # 30% winners, 70% losers
            if i < 6:
                exit_price = 1.1000 + 0.0020  # Small wins
                pnl = (exit_price - 1.1000) * 1000
                win = True
            else:
                exit_price = 1.1000 - 0.0050  # Larger losses
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
            losing_history.append(trade)
        
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance, trade_history=losing_history
        )
        
        # Should result in very small or zero position size
        assert position_size >= 0
        assert position_size <= 0.01  # Very small position for losing strategy


class TestAdaptivePositionSizer:
    """Test adaptive position sizing"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = PositionSizingConfig()
        self.sizer = AdaptivePositionSizer(self.config)
        
        self.signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.8,
            reasoning="Adaptive test signal",
            timestamp=datetime.now(timezone.utc)
        )
    
    def test_adaptive_with_no_history(self):
        """Test adaptive sizing with no history"""
        account_balance = 10000.0
        
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance, trade_history=[]
        )
        
        # Should favor fixed fractional with no history
        assert position_size > 0
    
    def test_adaptive_with_extensive_history(self):
        """Test adaptive sizing with extensive history"""
        account_balance = 10000.0
        
        # Create extensive trade history
        extensive_history = []
        for i in range(100):
            # 60% winners
            if i < 60:
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
            extensive_history.append(trade)
        
        position_size = self.sizer.calculate_position_size(
            self.signal, account_balance, trade_history=extensive_history
        )
        
        # Should favor Kelly with extensive history
        assert position_size > 0
    
    def test_confidence_adjustment(self):
        """Test confidence adjustment in adaptive sizing"""
        account_balance = 10000.0
        
        # High confidence signal
        high_conf_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.95,
            reasoning="High confidence adaptive test",
            timestamp=datetime.now(timezone.utc)
        )
        
        # Low confidence signal
        low_conf_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.3,
            reasoning="Low confidence adaptive test",
            timestamp=datetime.now(timezone.utc)
        )
        
        high_size = self.sizer.calculate_position_size(high_conf_signal, account_balance)
        low_size = self.sizer.calculate_position_size(low_conf_signal, account_balance)
        
        assert high_size > low_size


class TestPositionSizingRiskScenarios:
    """Test position sizing under various risk scenarios"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.config = PositionSizingConfig(
            max_risk_per_trade=0.02,
            max_position_size=0.1,
            min_position_size=0.001
        )
        self.fixed_sizer = FixedFractionalSizer(self.config)
        self.kelly_sizer = KellyCriterionSizer(self.config)
        self.adaptive_sizer = AdaptivePositionSizer(self.config)
    
    def test_position_size_limits_applied(self):
        """Test that position size limits are properly applied"""
        account_balance = 10000.0
        
        # Create a signal that would result in a very large position without limits
        extreme_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0999,  # 1 pip stop (would result in huge position)
            take_profit=1.1010,
            position_size=0.05,
            confidence=1.0,
            reasoning="Extreme position size test",
            timestamp=datetime.now(timezone.utc)
        )
        
        # Calculate position size
        position_size = self.fixed_sizer.calculate_position_size(extreme_signal, account_balance)
        
        # Should be limited by max position size
        assert position_size <= self.config.max_position_size
        assert position_size >= self.config.min_position_size
        assert position_size > 0
        
        # Test with very wide stop that would result in tiny position
        wide_stop_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0000,  # 1000 pips stop (would result in tiny position)
            take_profit=1.2000,
            position_size=0.05,
            confidence=1.0,
            reasoning="Wide stop test",
            timestamp=datetime.now(timezone.utc)
        )
        
        wide_stop_size = self.fixed_sizer.calculate_position_size(wide_stop_signal, account_balance)
        
        # Should be limited by minimum position size
        assert wide_stop_size >= self.config.min_position_size
        assert wide_stop_size <= self.config.max_position_size
    
    def test_low_confidence_scenario(self):
        """Test position sizing with low confidence signals"""
        low_conf_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.05,
            confidence=0.2,  # Very low confidence
            reasoning="Low confidence test",
            timestamp=datetime.now(timezone.utc)
        )
        
        high_conf_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.05,
            confidence=0.9,  # High confidence
            reasoning="High confidence test",
            timestamp=datetime.now(timezone.utc)
        )
        
        account_balance = 10000.0
        
        low_conf_size = self.adaptive_sizer.calculate_position_size(low_conf_signal, account_balance)
        high_conf_size = self.adaptive_sizer.calculate_position_size(high_conf_signal, account_balance)
        
        # Low confidence should result in smaller position size
        assert low_conf_size < high_conf_size
        assert low_conf_size >= self.config.min_position_size
    
    def test_small_account_scenario(self):
        """Test position sizing with small account balance"""
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.05,
            confidence=0.8,
            reasoning="Small account test",
            timestamp=datetime.now(timezone.utc)
        )
        
        small_balance = 100.0  # Very small account
        large_balance = 100000.0  # Large account
        
        small_size = self.fixed_sizer.calculate_position_size(signal, small_balance)
        large_size = self.fixed_sizer.calculate_position_size(signal, large_balance)
        
        # Both should respect minimum position size
        assert small_size >= self.config.min_position_size
        assert large_size >= self.config.min_position_size
        
        # Large account should allow for larger position (as fraction)
        assert large_size >= small_size
    
    def test_losing_streak_scenario(self):
        """Test Kelly sizing after a losing streak"""
        # Create losing trade history
        losing_history = []
        for i in range(30):
            # 20% winners, 80% losers (bad streak)
            if i < 6:
                exit_price = 1.1000 + 0.0010  # Small wins
                pnl = (exit_price - 1.1000) * 1000
                win = True
            else:
                exit_price = 1.1000 - 0.0030  # Larger losses
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
            losing_history.append(trade)
        
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.05,
            confidence=0.8,
            reasoning="Losing streak test",
            timestamp=datetime.now(timezone.utc)
        )
        
        account_balance = 10000.0
        
        # Kelly should recommend very small or zero position after losing streak
        kelly_size = self.kelly_sizer.calculate_position_size(signal, account_balance, losing_history)
        
        # Should be very conservative
        assert kelly_size <= 0.01  # Less than 1%
    
    def test_winning_streak_scenario(self):
        """Test Kelly sizing after a winning streak"""
        # Create winning trade history
        winning_history = []
        for i in range(30):
            # 80% winners, 20% losers (good streak)
            if i < 24:
                exit_price = 1.1000 + 0.0040  # Good wins
                pnl = (exit_price - 1.1000) * 1000
                win = True
            else:
                exit_price = 1.1000 - 0.0020  # Small losses
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
            winning_history.append(trade)
        
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.05,
            confidence=0.8,
            reasoning="Winning streak test",
            timestamp=datetime.now(timezone.utc)
        )
        
        account_balance = 10000.0
        
        # Kelly should recommend larger position after winning streak
        kelly_size = self.kelly_sizer.calculate_position_size(signal, account_balance, winning_history)
        
        # Should be more aggressive but still within limits
        assert kelly_size > 0.01
        assert kelly_size <= self.config.max_position_size
    
    def test_extreme_risk_scenario(self):
        """Test position sizing with extreme risk parameters"""
        # Signal with very tight stop (extreme risk)
        extreme_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0999,  # 1 pip stop (extreme)
            take_profit=1.1010,
            position_size=0.05,
            confidence=0.5,
            reasoning="Extreme risk test",
            timestamp=datetime.now(timezone.utc)
        )
        
        account_balance = 10000.0
        
        # Should be limited by max position size
        extreme_size = self.fixed_sizer.calculate_position_size(extreme_signal, account_balance)
        
        assert extreme_size <= self.config.max_position_size
        assert extreme_size >= self.config.min_position_size
    
    def test_adaptive_sizer_risk_scenarios(self):
        """Test adaptive sizer under various risk scenarios"""
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,
            take_profit=1.1100,
            position_size=0.05,
            confidence=0.8,
            reasoning="Adaptive risk test",
            timestamp=datetime.now(timezone.utc)
        )
        
        account_balance = 10000.0
        
        # Test with no history (should favor fixed fractional)
        no_history_size = self.adaptive_sizer.calculate_position_size(signal, account_balance, [])
        
        # Test with moderate history
        moderate_history = []
        for i in range(25):
            # 60% winners
            if i < 15:
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
            moderate_history.append(trade)
        
        moderate_history_size = self.adaptive_sizer.calculate_position_size(
            signal, account_balance, moderate_history
        )
        
        # Both should be reasonable
        assert no_history_size > 0
        assert moderate_history_size > 0
        assert no_history_size <= self.config.max_position_size
        assert moderate_history_size <= self.config.max_position_size


if __name__ == "__main__":
    pytest.main([__file__])
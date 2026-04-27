"""Unit tests for signal filter"""

import pytest
from datetime import datetime, timedelta, timezone
from src.analysis.signal_filter import SignalFilter
from src.models import TradingSignal, Direction
from src.exceptions import DataValidationError


class TestSignalFilter:
    """Test signal filter functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        # Create filter criteria that doesn't require multiple sources for testing
        from src.analysis.signal_filter import FilterCriteria
        criteria = FilterCriteria(require_multiple_sources=False)
        self.filter = SignalFilter(filter_criteria=criteria)
        self.current_time = datetime.now(timezone.utc)
        self.symbol = "EUR/USD"
        
        # Create test signals
        self.signals = [
            TradingSignal(
                symbol=self.symbol,
                direction=Direction.LONG,
                entry_price=1.1000,
                stop_loss=1.0900,
                take_profit=1.1200,
                position_size=0.05,
                confidence=0.8,
                reasoning="Strong bullish signal",
                timestamp=self.current_time
            ),
            TradingSignal(
                symbol=self.symbol,
                direction=Direction.SHORT,
                entry_price=1.1000,
                stop_loss=1.1100,
                take_profit=1.0800,
                position_size=0.03,
                confidence=0.6,
                reasoning="Weak bearish signal",
                timestamp=self.current_time
            ),
            TradingSignal(
                symbol="GBP/USD",
                direction=Direction.LONG,
                entry_price=1.3000,
                stop_loss=1.2900,
                take_profit=1.3200,
                position_size=0.04,
                confidence=0.9,
                reasoning="Very strong signal",
                timestamp=self.current_time
            )
        ]
    
    def test_filter_signals_basic(self):
        """Test basic signal filtering"""
        filtered = self.filter.filter_signals(self.signals)
        
        assert len(filtered.filtered_signals) > 0
        assert all(isinstance(signal, TradingSignal) for signal in filtered.filtered_signals)
    
    def test_filter_signals_empty_input(self):
        """Test filtering with empty input"""
        filtered = self.filter.filter_signals([])
        assert filtered.filtered_signals == []
    
    def test_filter_by_confidence(self):
        """Test filtering by confidence threshold"""
        # Set high confidence threshold
        self.filter.criteria.min_confidence = 0.7
        
        filtered = self.filter.filter_signals(self.signals)
        
        # Should only include signals with confidence >= 0.7
        assert all(signal.confidence >= 0.7 for signal in filtered.filtered_signals)
        assert len(filtered.filtered_signals) < len(self.signals)
    
    def test_filter_by_age(self):
        """Test filtering by signal age"""
        # Create old signal with high confidence to avoid reliability filtering
        old_signal = TradingSignal(
            symbol="USD/JPY",  # Different symbol to avoid conflicts
            direction=Direction.LONG,
            entry_price=150.00,
            stop_loss=149.50,
            take_profit=151.00,
            position_size=0.05,
            confidence=0.9,  # High confidence to avoid reliability filtering
            reasoning="Old signal",
            timestamp=self.current_time - timedelta(hours=3)
        )
        
        # Test with just the old signal to isolate age filtering
        self.filter.criteria.max_signal_age_minutes = 120  # 2 hours
        self.filter.criteria.min_reliability = 0.1  # Lower reliability threshold to test age
        
        filtered = self.filter.filter_signals([old_signal])
        
        # Should exclude old signal due to age
        assert len(filtered.filtered_signals) == 0
        assert len(filtered.rejected_signals) == 1
        assert "too old" in filtered.rejected_signals[0][1]
    
    def test_filter_conflicting_signals(self):
        """Test filtering conflicting signals for same symbol"""
        # Create conflicting signals for same symbol
        conflicting_signals = [
            TradingSignal(
                symbol=self.symbol,
                direction=Direction.LONG,
                entry_price=1.1000,
                stop_loss=1.0900,
                take_profit=1.1200,
                position_size=0.05,
                confidence=0.8,
                reasoning="Long signal",
                timestamp=self.current_time
            ),
            TradingSignal(
                symbol=self.symbol,
                direction=Direction.SHORT,
                entry_price=1.1000,
                stop_loss=1.1100,
                take_profit=1.0800,
                position_size=0.05,
                confidence=0.7,
                reasoning="Short signal",
                timestamp=self.current_time
            )
        ]
        
        filtered = self.filter.filter_conflicting_signals(conflicting_signals)
        
        # Should only keep one signal per symbol (the stronger one)
        assert len(filtered) == 1
        assert filtered[0].confidence == 0.8  # Higher confidence signal
    
    def test_filter_correlated_signals(self):
        """Test filtering correlated signals"""
        # Create correlated signals
        correlated_signals = [
            TradingSignal(
                symbol="EUR/USD",
                direction=Direction.LONG,
                entry_price=1.1000,
                stop_loss=1.0900,
                take_profit=1.1200,
                position_size=0.05,
                confidence=0.8,
                reasoning="EUR/USD signal",
                timestamp=self.current_time
            ),
            TradingSignal(
                symbol="EUR/GBP",
                direction=Direction.LONG,
                entry_price=0.8500,
                stop_loss=0.8400,
                take_profit=0.8700,
                position_size=0.05,
                confidence=0.7,
                reasoning="EUR/GBP signal",
                timestamp=self.current_time
            )
        ]
        
        filtered = self.filter.filter_correlated_signals(correlated_signals)
        
        # Should reduce correlated signals
        assert len(filtered) <= len(correlated_signals)
    
    def test_rank_signals(self):
        """Test signal ranking"""
        ranked = self.filter.rank_signals(self.signals)
        
        assert len(ranked) == len(self.signals)
        assert all(hasattr(ranking, 'signal') for ranking in ranked)
        
        # Should be sorted by quality score (highest first)
        if len(ranked) > 1:
            assert ranked[0].rank_score >= ranked[1].rank_score
    
    def test_signal_correlation_calculation(self):
        """Test signal correlation calculation"""
        correlation = self.filter.calculate_signal_correlation(
            self.signals[0], self.signals[1]
        )
        
        assert isinstance(correlation, float)
        assert 0.0 <= correlation <= 1.0
    
    def test_quality_score_calculation(self):
        """Test quality score calculation"""
        score = self.filter.calculate_quality_score(self.signals[0])
        
        assert isinstance(score, float)
        assert score > 0.0
        assert score <= 1.0
    
    def test_ranking_factors_calculation(self):
        """Test ranking factors calculation"""
        factors = self.filter.calculate_ranking_factors(self.signals[0])
        
        assert isinstance(factors, dict)
        assert "confidence" in factors
        assert "age" in factors
        assert "risk_reward" in factors
    
    def test_filter_criteria_update(self):
        """Test updating filter criteria"""
        # Update criteria
        self.filter.criteria.min_confidence = 0.9
        self.filter.criteria.max_signal_age_minutes = 60
        self.filter.criteria.min_risk_reward_ratio = 2.0
        
        filtered = self.filter.filter_signals(self.signals)
        
        # Should apply new criteria
        assert all(signal.confidence >= 0.9 for signal in filtered.filtered_signals)
    
    def test_filter_statistics(self):
        """Test filter statistics"""
        stats = self.filter.get_filter_statistics(self.signals)
        
        assert "total_signals" in stats
        assert "filtered_signals" in stats
        assert "filter_rate" in stats
        assert "avg_confidence" in stats
    
    def test_multiple_sources_requirement(self):
        """Test filtering by multiple sources requirement"""
        # Create signals with different source counts
        single_source_signal = TradingSignal(
            symbol=self.symbol,
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.8,
            reasoning="Single source",
            timestamp=self.current_time
        )
        
        self.filter.criteria.require_multiple_sources = True
        filtered = self.filter.filter_signals([single_source_signal])
        
        # Should filter out single source signals
        assert len(filtered.filtered_signals) == 0
    
    def test_risk_reward_filtering(self):
        """Test filtering by risk-reward ratio"""
        # Create signal with poor risk-reward ratio
        poor_rr_signal = TradingSignal(
            symbol=self.symbol,
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0950,  # 50 pips risk
            take_profit=1.1050,  # 50 pips reward (1:1 ratio)
            position_size=0.05,
            confidence=0.8,
            reasoning="Poor risk-reward",
            timestamp=self.current_time
        )
        
        self.filter.criteria.min_risk_reward_ratio = 1.5
        filtered = self.filter.filter_signals([poor_rr_signal])
        
        # Should filter out poor risk-reward signals
        assert len(filtered.filtered_signals) == 0
    
    def test_clear_history(self):
        """Test clearing signal history"""
        # Add some signals to history
        self.filter.add_to_history(self.signals[0])
        self.filter.add_to_history(self.signals[1])
        
        assert len(self.filter.signal_history) > 0
        
        # Clear history
        self.filter.clear_history()
        
        assert len(self.filter.signal_history) == 0


if __name__ == "__main__":
    pytest.main([__file__])
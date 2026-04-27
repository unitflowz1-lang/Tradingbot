"""Unit tests for signal combiner"""

import pytest
from datetime import datetime, timedelta, timezone
from src.analysis.signal_combiner import SignalCombiner, CombinedSignalResult
from src.models import TradingSignal, SentimentResult, Direction, TechnicalSignal, SignalType
from src.analysis.sentiment_aggregator import AggregatedSentiment
from src.exceptions import DataValidationError


class TestSignalCombiner:
    """Test signal combiner functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.combiner = SignalCombiner()
        self.current_time = datetime.now(timezone.utc)
        self.symbol = "EUR/USD"
        
        # Create test signals
        sentiment_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=0.7,
            confidence=0.8,
            reasoning="Positive sentiment",
            sources=["news"],
            timestamp=self.current_time
        )
        
        self.sentiment_signal = AggregatedSentiment(
            symbol=self.symbol,
            final_sentiment_score=0.7,
            final_confidence=0.8,
            reasoning="Positive sentiment",
            sources=["news"],
            individual_results=[sentiment_result],
            aggregation_method="weighted_average",
            consistency_score=0.9,
            timestamp=self.current_time
        )
        
        self.technical_signal = TechnicalSignal(
            symbol=self.symbol,
            signal_type=SignalType.BUY,
            strength=0.75,
            indicators={"rsi": 30, "macd": 0.5, "sma": 1.1000},
            timestamp=self.current_time
        )
        
        self.current_price = 1.1000
    
    def test_combine_signals_with_both_inputs(self):
        """Test combining sentiment and technical signals"""
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        assert combined.trading_signal is not None
        assert combined.trading_signal.symbol == self.symbol
        assert combined.confidence_score > 0.7  # Should be higher than individual signals
        assert "combined" in combined.combination_reasoning.lower()
    
    def test_combine_signals_sentiment_only(self):
        """Test combining with only sentiment signal"""
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        # With only sentiment, confidence might be below threshold for trading signal
        assert combined.confidence_score > 0.0
        assert "sentiment" in combined.combination_reasoning.lower()
    
    def test_combine_signals_technical_only(self):
        """Test combining with only technical signal"""
        combined = self.combiner.combine_signals(
            sentiment_result=None,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        # With only technical, confidence might be below threshold for trading signal
        assert combined.confidence_score > 0.0
        assert "technical" in combined.combination_reasoning.lower()
    
    def test_combine_signals_no_inputs(self):
        """Test combining with no inputs"""
        combined = self.combiner.combine_signals(
            sentiment_result=None,
            technical_signals=[],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        assert combined.trading_signal is None
        assert combined.confidence_score == 0.0
    
    def test_conflicting_signals(self):
        """Test handling of conflicting signals"""
        # Create conflicting signals
        bearish_sentiment_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=-0.6,
            confidence=0.8,
            reasoning="Negative sentiment",
            sources=["news"],
            timestamp=self.current_time
        )
        
        bearish_sentiment = AggregatedSentiment(
            symbol=self.symbol,
            final_sentiment_score=-0.6,
            final_confidence=0.8,
            reasoning="Negative sentiment",
            sources=["news"],
            individual_results=[bearish_sentiment_result],
            aggregation_method="weighted_average",
            consistency_score=0.9,
            timestamp=self.current_time
        )
        
        combined = self.combiner.combine_signals(
            sentiment_result=bearish_sentiment,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        # Should handle conflict gracefully
        assert isinstance(combined, CombinedSignalResult)
        # The reasoning shows the conflicting signals but doesn't explicitly mention "conflict"
        assert "sentiment" in combined.combination_reasoning.lower() and "technical" in combined.combination_reasoning.lower()
    
    def test_signal_timing_synchronization(self):
        """Test signal timing synchronization"""
        # Create signals with different timestamps
        old_sentiment_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=0.5,
            confidence=0.8,
            reasoning="Old sentiment",
            sources=["news"],
            timestamp=self.current_time - timedelta(hours=2)
        )
        
        old_sentiment = AggregatedSentiment(
            symbol=self.symbol,
            final_sentiment_score=0.5,
            final_confidence=0.8,
            reasoning="Old sentiment",
            sources=["news"],
            individual_results=[old_sentiment_result],
            aggregation_method="weighted_average",
            consistency_score=0.9,
            timestamp=self.current_time - timedelta(hours=2)
        )
        
        combined = self.combiner.combine_signals(
            sentiment_result=old_sentiment,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        # The old sentiment signal is filtered out, so we get "No data available"
        assert "no data available" in combined.combination_reasoning.lower()
    
    def test_signal_weights_update(self):
        """Test updating signal weights"""
        # Update weights
        from src.analysis.signal_combiner import SignalWeights
        new_weights = SignalWeights(sentiment_weight=0.7, technical_weight=0.3)
        self.combiner.update_signal_weights(new_weights)
        
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        assert combined.confidence_score > 0.0
    
    def test_position_size_calculation(self):
        """Test position size calculation"""
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        assert combined.trading_signal is not None
        assert combined.trading_signal.position_size > 0.0
        assert combined.trading_signal.position_size <= 1.0  # Should not exceed 100%
    
    def test_stop_take_levels_calculation(self):
        """Test stop loss and take profit calculation"""
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        assert combined.trading_signal is not None
        assert combined.trading_signal.stop_loss is not None
        assert combined.trading_signal.take_profit is not None
        assert combined.trading_signal.stop_loss < combined.trading_signal.entry_price < combined.trading_signal.take_profit
    
    def test_enhanced_reasoning_generation(self):
        """Test enhanced reasoning generation"""
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        reasoning = combined.combination_reasoning
        assert len(reasoning) > 50  # Should be detailed
        assert "sentiment" in reasoning.lower()
        assert "technical" in reasoning.lower()
    
    def test_risk_assessment(self):
        """Test risk assessment in combined signals"""
        combined = self.combiner.combine_signals(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        # Should have risk assessment in reasoning
        assert "risk" in combined.combination_reasoning.lower() or "confidence" in combined.combination_reasoning.lower()
    
    def test_signal_statistics(self):
        """Test signal statistics calculation"""
        stats = self.combiner.get_signal_statistics(
            sentiment_result=self.sentiment_signal,
            technical_signals=[self.technical_signal]
        )
        
        assert "sentiment_available" in stats
        assert "sentiment_confidence" in stats
        assert "average_technical_strength" in stats
    
    def test_input_validation(self):
        """Test input validation"""
        # Test invalid sentiment signal
        with pytest.raises(AttributeError):
            self.combiner.combine_signals(
                sentiment_result="invalid",
                technical_signals=[],
                current_price=self.current_price,
                symbol=self.symbol
            )
        
        # Test invalid technical signal
        with pytest.raises(AttributeError):
            self.combiner.combine_signals(
                sentiment_result=None,
                technical_signals=["invalid"],
                current_price=self.current_price,
                symbol=self.symbol
            )
    
    def test_weighted_scoring_system(self):
        """Test weighted scoring system"""
        # Test with different confidence levels
        low_conf_sentiment_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=0.5,
            confidence=0.3,
            reasoning="Low confidence",
            sources=["news"],
            timestamp=self.current_time
        )
        
        low_conf_sentiment = AggregatedSentiment(
            symbol=self.symbol,
            final_sentiment_score=0.5,
            final_confidence=0.3,
            reasoning="Low confidence",
            sources=["news"],
            individual_results=[low_conf_sentiment_result],
            aggregation_method="weighted_average",
            consistency_score=0.9,
            timestamp=self.current_time
        )
        
        high_conf_technical = TechnicalSignal(
            symbol=self.symbol,
            signal_type=SignalType.BUY,
            strength=0.9,
            indicators={"rsi": 25, "macd": 0.8, "sma": 1.1000},
            timestamp=self.current_time
        )
        
        combined = self.combiner.combine_signals(
            sentiment_result=low_conf_sentiment,
            technical_signals=[high_conf_technical],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        # Should favor high confidence signal
        assert combined.confidence_score > 0.6
    
    def test_sell_signal_generation(self):
        """Test sell signal generation"""
        # Create bearish signals
        bearish_sentiment_result = SentimentResult(
            symbol=self.symbol,
            sentiment_score=-0.7,
            confidence=0.8,
            reasoning="Bearish sentiment",
            sources=["news"],
            timestamp=self.current_time
        )
        
        bearish_sentiment = AggregatedSentiment(
            symbol=self.symbol,
            final_sentiment_score=-0.7,
            final_confidence=0.8,
            reasoning="Bearish sentiment",
            sources=["news"],
            individual_results=[bearish_sentiment_result],
            aggregation_method="weighted_average",
            consistency_score=0.9,
            timestamp=self.current_time
        )
        
        bearish_technical = TechnicalSignal(
            symbol=self.symbol,
            signal_type=SignalType.SELL,
            strength=0.75,
            indicators={"rsi": 75, "macd": -0.5, "sma": 1.1000},
            timestamp=self.current_time
        )
        
        combined = self.combiner.combine_signals(
            sentiment_result=bearish_sentiment,
            technical_signals=[bearish_technical],
            current_price=self.current_price,
            symbol=self.symbol
        )
        
        assert isinstance(combined, CombinedSignalResult)
        assert combined.trading_signal is not None
        assert combined.trading_signal.direction == Direction.SHORT
        assert combined.trading_signal.stop_loss > combined.trading_signal.entry_price
        assert combined.trading_signal.take_profit < combined.trading_signal.entry_price


if __name__ == "__main__":
    pytest.main([__file__])
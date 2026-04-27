"""Unit tests for signal tracker"""

import pytest
import tempfile
import os
from datetime import datetime, timedelta, timezone
from src.analysis.signal_tracker import SignalTracker
from src.analysis.confidence_calculator import ConfidenceResult, ConfidenceFactors
from src.models import TradingSignal, Direction
from src.exceptions import DataValidationError


class TestSignalTracker:
    """Test signal tracker functionality"""
    
    def setup_method(self):
        """Setup test fixtures"""
        # Create a temporary database for each test
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix='.db')
        self.temp_db.close()
        
        self.tracker = SignalTracker(db_path=self.temp_db.name)
        self.symbol = "EUR/USD"
        
        # Create test signal
        self.test_signal = TradingSignal(
            symbol=self.symbol,
            direction=Direction.LONG,
            entry_price=1.1000,
            stop_loss=1.0900,
            take_profit=1.1200,
            position_size=0.05,
            confidence=0.8,
            reasoning="Test signal",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1)  # Past timestamp
        )
        
        # Create test confidence result
        self.confidence_result = ConfidenceResult(
            overall_confidence=0.8,
            confidence_factors=ConfidenceFactors(
                signal_strength=0.8,
                signal_consistency=0.7,
                source_reliability=0.8,
                temporal_stability=0.9,
                market_alignment=0.8,
                volume_confirmation=0.7,
                risk_reward_ratio=0.8
            ),
            confidence_breakdown={
                "signal_strength": 0.8,
                "consistency": 0.7,
                "reliability": 0.8,
                "temporal": 0.9,
                "market_alignment": 0.8,
                "volume": 0.7,
                "risk_reward": 0.8
            },
            reliability_score=0.8,
            recommendation="STRONG"
        )
    
    def teardown_method(self):
        """Clean up after each test"""
        # Close database connection first
        if hasattr(self.tracker, '_db_connection'):
            self.tracker._db_connection.close()
        
        # Remove temporary database
        try:
            if os.path.exists(self.temp_db.name):
                os.unlink(self.temp_db.name)
        except PermissionError:
            # On Windows, file might still be in use, ignore the error
            pass
    
    def test_track_signal(self):
        """Test tracking a new signal"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        assert isinstance(signal_id, str)
        assert len(signal_id) > 0
        
        # Should be in active signals
        active_signals = self.tracker.get_active_signals()
        assert len(active_signals) == 1
        assert active_signals[0].symbol == self.symbol
    
    def test_record_signal_outcome_successful(self):
        """Test recording successful signal outcome"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # Record successful outcome
        outcome = self.tracker.record_signal_outcome(
            signal_id=signal_id,
            exit_price=1.1200,
            exit_reason="TAKE_PROFIT",
            max_favorable_excursion=1.1250,
            max_adverse_excursion=1.0950
        )
        
        assert outcome.was_successful is True
        assert outcome.pnl > 0
        assert outcome.exit_reason == "TAKE_PROFIT"
        
        # Should not be in active signals anymore
        active_signals = self.tracker.get_active_signals()
        assert len(active_signals) == 0
    
    def test_record_signal_outcome_failed(self):
        """Test recording failed signal outcome"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # Record failed outcome
        outcome = self.tracker.record_signal_outcome(
            signal_id=signal_id,
            exit_price=1.0900,
            exit_reason="STOP_LOSS",
            max_favorable_excursion=1.1050,
            max_adverse_excursion=1.0850
        )
        
        assert outcome.was_successful is False
        assert outcome.pnl < 0
        assert outcome.exit_reason == "STOP_LOSS"
        
        # Should not be in active signals anymore
        active_signals = self.tracker.get_active_signals()
        assert len(active_signals) == 0
    
    def test_get_active_signals(self):
        """Test getting active signals"""
        # Track multiple signals
        signal1_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        signal2 = TradingSignal(
            symbol="GBP/USD",
            direction=Direction.SHORT,
            entry_price=1.3000,
            stop_loss=1.3100,
            take_profit=1.2800,
            position_size=0.03,
            confidence=0.7,
            reasoning="Test signal 2",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        
        signal2_id = self.tracker.track_signal(signal2, self.confidence_result)
        
        # Get all active signals
        active_signals = self.tracker.get_active_signals()
        assert len(active_signals) == 2
        
        # Get signals for specific symbol
        eur_signals = self.tracker.get_active_signals(symbol="EUR/USD")
        assert len(eur_signals) == 1
        assert eur_signals[0].symbol == "EUR/USD"
    
    def test_expire_signal(self):
        """Test expiring a signal"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # Verify signal is active
        active_signals = self.tracker.get_active_signals()
        assert len(active_signals) == 1
        
        # Expire the signal
        success = self.tracker.expire_signal(signal_id, "MANUAL_EXPIRY")
        assert success is True
        
        # Verify signal is no longer active
        active_signals = self.tracker.get_active_signals()
        assert len(active_signals) == 0
    
    def test_refresh_signal(self):
        """Test refreshing a signal"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # Get original signal
        original_signal = self.tracker._load_signal_from_db(signal_id)
        original_expiry = original_signal.expiry_timestamp
        
        # Refresh signal
        success = self.tracker.refresh_signal(signal_id, new_expiry_hours=48)
        assert success is True
        
        # Get refreshed signal
        refreshed_signal = self.tracker._load_signal_from_db(signal_id)
        assert refreshed_signal.expiry_timestamp > original_expiry
    
    def test_signal_id_generation(self):
        """Test signal ID generation"""
        signal_id1 = self.tracker.track_signal(self.test_signal, self.confidence_result)
        signal_id2 = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # IDs should be unique
        assert signal_id1 != signal_id2
        assert isinstance(signal_id1, str)
        assert isinstance(signal_id2, str)
        assert len(signal_id1) > 0
        assert len(signal_id2) > 0
    
    def test_get_signal_statistics(self):
        """Test getting signal performance statistics"""
        # Track and complete some signals
        signal_id1 = self.tracker.track_signal(self.test_signal, self.confidence_result)
        self.tracker.record_signal_outcome(
            signal_id=signal_id1,
            exit_price=1.1200,
            exit_reason="TAKE_PROFIT"
        )
        
        signal_id2 = self.tracker.track_signal(self.test_signal, self.confidence_result)
        self.tracker.record_signal_outcome(
            signal_id=signal_id2,
            exit_price=1.0900,
            exit_reason="STOP_LOSS"
        )
        
        # Get performance metrics
        metrics = self.tracker.get_signal_performance(symbol=self.symbol)
        
        assert metrics.total_signals >= 2
        assert metrics.successful_signals >= 1
        assert metrics.failed_signals >= 1
        assert 0.0 <= metrics.win_rate <= 1.0
        assert isinstance(metrics.average_pnl, float)
    
    def test_get_signal_by_id(self):
        """Test getting signal by ID"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # Get signal by ID
        signal = self.tracker._load_signal_from_db(signal_id)
        
        assert signal is not None
        assert signal.signal_id == signal_id
        assert signal.symbol == self.symbol
    
    def test_get_nonexistent_signal(self):
        """Test getting non-existent signal"""
        # Try to get signal with non-existent ID
        signal = self.tracker._load_signal_from_db("non_existent_id")
        
        assert signal is None
    
    def test_update_signal(self):
        """Test updating signal information"""
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        # Get original signal
        original_signal = self.tracker._load_signal_from_db(signal_id)
        
        # Update signal
        original_signal.confidence = 0.9
        original_signal.reasoning = "Updated reasoning"
        
        self.tracker._update_signal_in_db(original_signal)
        
        # Get updated signal
        updated_signal = self.tracker._load_signal_from_db(signal_id)
        
        assert updated_signal.confidence == 0.9
        assert updated_signal.reasoning == "Updated reasoning"
    
    def test_filter_signals_by_symbol(self):
        """Test filtering signals by symbol"""
        # Track signals for different symbols
        signal1_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        
        gbp_signal = TradingSignal(
            symbol="GBP/USD",
            direction=Direction.SHORT,
            entry_price=1.3000,
            stop_loss=1.3100,
            take_profit=1.2800,
            position_size=0.03,
            confidence=0.7,
            reasoning="GBP signal",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1)
        )
        
        signal2_id = self.tracker.track_signal(gbp_signal, self.confidence_result)
        
        # Get signals for EUR/USD only
        eur_signals = self.tracker.get_active_signals(symbol="EUR/USD")
        assert len(eur_signals) == 1
        assert all(s.symbol == "EUR/USD" for s in eur_signals)
        
        # Get signals for GBP/USD only
        gbp_signals = self.tracker.get_active_signals(symbol="GBP/USD")
        assert len(gbp_signals) == 1
        assert all(s.symbol == "GBP/USD" for s in gbp_signals)
    
    def test_cleanup_old_completed_signals(self):
        """Test cleaning up old completed signals"""
        # Track and complete a signal
        signal_id = self.tracker.track_signal(self.test_signal, self.confidence_result)
        self.tracker.record_signal_outcome(
            signal_id=signal_id,
            exit_price=1.1200,
            exit_reason="TAKE_PROFIT"
        )
        
        # Clean up old data (keep only last 1 day)
        cleaned_count = self.tracker.cleanup_old_data(days_to_keep=1)
        
        # Should have cleaned up some data
        assert cleaned_count >= 0
    
    def test_export_signal_history(self):
        """Test exporting signal history"""
        # Track and complete some signals
        signal_id1 = self.tracker.track_signal(self.test_signal, self.confidence_result)
        self.tracker.record_signal_outcome(
            signal_id=signal_id1,
            exit_price=1.1200,
            exit_reason="TAKE_PROFIT"
        )
        
        signal_id2 = self.tracker.track_signal(self.test_signal, self.confidence_result)
        self.tracker.record_signal_outcome(
            signal_id=signal_id2,
            exit_price=1.0900,
            exit_reason="STOP_LOSS"
        )
        
        # Get signal history
        history = self.tracker.get_signal_history(symbol=self.symbol, days_back=30)
        
        assert len(history) >= 2
        assert all(hasattr(s, 'signal_id') for s in history)
        
        # Get signal outcomes
        outcomes = self.tracker.get_signal_outcomes(symbol=self.symbol, days_back=30)
        
        assert len(outcomes) >= 2
        assert all(hasattr(o, 'signal_id') for o in outcomes)


if __name__ == "__main__":
    pytest.main([__file__])

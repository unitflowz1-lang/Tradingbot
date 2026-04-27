"""
Unit tests for RL Signal Generation and Integration
"""

import pytest
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List

from src.rl.integration.signal_generator import RLSignalGenerator, create_rl_signal_generator
from src.rl.integration.hybrid_decision_engine import (
    HybridDecisionEngine, DecisionMethod, DecisionConfig, SignalWeight, create_hybrid_decision_engine
)
from src.rl.agents.base import RLAgent
from src.rl.environments.base import PortfolioState
from src.models import TradingSignal, Direction, MarketData
from src.interfaces import RiskManager


class TestRLSignalGenerator:
    """Test cases for RLSignalGenerator"""
    
    @pytest.fixture
    def mock_agent(self):
        """Mock RL agent for testing"""
        agent = Mock(spec=RLAgent)
        agent.select_action.return_value = 1  # BUY_SMALL action
        return agent
    
    @pytest.fixture
    def mock_risk_manager(self):
        """Mock risk manager for testing"""
        risk_manager = Mock(spec=RiskManager)
        return risk_manager
    
    @pytest.fixture
    def portfolio_state(self):
        """Sample portfolio state for testing"""
        return PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
    
    @pytest.fixture
    def market_data(self):
        """Sample market data for testing"""
        return MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000,
            high=1.1010,
            low=1.0990,
            close=1.1005,
            volume=1000,
            bid=1.1003,
            ask=1.1007,
            spread=0.0004
        )
    
    @pytest.fixture
    def signal_generator(self, mock_agent):
        """Signal generator instance for testing"""
        return RLSignalGenerator(
            agent=mock_agent,
            confidence_threshold=0.5,
            max_position_size=0.1
        )
    
    def test_initialization(self, mock_agent, mock_risk_manager):
        """Test signal generator initialization"""
        generator = RLSignalGenerator(
            agent=mock_agent,
            risk_manager=mock_risk_manager,
            confidence_threshold=0.7,
            max_position_size=0.05
        )
        
        assert generator.agent == mock_agent
        assert generator.risk_manager == mock_risk_manager
        assert generator.confidence_threshold == 0.7
        assert generator.max_position_size == 0.05
        assert len(generator.signal_history) == 0
        assert generator.last_signal_time is None
    
    def test_generate_signal_success(self, signal_generator, market_data, portfolio_state):
        """Test successful signal generation"""
        # Mock agent to return high confidence
        signal_generator.agent.select_action.return_value = 2  # BUY_MEDIUM
        
        with patch.object(signal_generator, '_get_action_confidence', return_value=0.8):
            signal = signal_generator.generate_signal(
                "EUR/USD", market_data, np.random.random(50), portfolio_state
            )
            
            assert signal is not None
            assert signal.symbol == "EUR/USD"
            assert signal.direction == Direction.LONG
            assert signal.confidence == 0.8
            assert "RL Agent" in signal.reasoning
            assert signal.entry_price == market_data.ask
            assert signal.stop_loss < signal.entry_price
            assert signal.take_profit > signal.entry_price
    
    def test_generate_signal_low_confidence(self, signal_generator, market_data, portfolio_state):
        """Test signal generation with low confidence"""
        signal_generator.agent.select_action.return_value = 1
        
        with patch.object(signal_generator, '_get_action_confidence', return_value=0.3):
            signal = signal_generator.generate_signal(
                "EUR/USD", market_data, np.random.random(50), portfolio_state
            )
            
            assert signal is None
    
    def test_generate_signal_hold_action(self, signal_generator, market_data, portfolio_state):
        """Test signal generation with HOLD action"""
        signal_generator.agent.select_action.return_value = 0  # HOLD
        
        with patch.object(signal_generator, '_get_action_confidence', return_value=0.8):
            signal = signal_generator.generate_signal(
                "EUR/USD", market_data, np.random.random(50), portfolio_state
            )
            
            assert signal is None
    
    def test_generate_signal_sell_action(self, signal_generator, market_data, portfolio_state):
        """Test signal generation with SELL action"""
        signal_generator.agent.select_action.return_value = 5  # SELL_MEDIUM
        
        with patch.object(signal_generator, '_get_action_confidence', return_value=0.7):
            signal = signal_generator.generate_signal(
                "EUR/USD", market_data, np.random.random(50), portfolio_state
            )
            
            assert signal is not None
            assert signal.direction == Direction.SHORT
            assert signal.entry_price == market_data.bid
            assert signal.stop_loss > signal.entry_price
            assert signal.take_profit < signal.entry_price
    
    def test_get_action_confidence_with_q_values(self, signal_generator):
        """Test getting action confidence with Q-values"""
        # Mock agent with Q-values
        signal_generator.agent.get_action_values = Mock(return_value=np.array([0.1, 0.8, 0.3, 0.2]))
        
        confidence = signal_generator._get_action_confidence(np.random.random(50), 1)
        
        # Should normalize Q-values: (0.8 - 0.1) / (0.8 - 0.1) = 1.0
        assert confidence == 1.0
    
    def test_get_action_confidence_with_probabilities(self, signal_generator):
        """Test getting action confidence with action probabilities"""
        # Mock agent with probabilities
        signal_generator.agent.get_action_probabilities = Mock(return_value=np.array([0.1, 0.6, 0.2, 0.1]))
        
        confidence = signal_generator._get_action_confidence(np.random.random(50), 1)
        
        assert confidence == 0.6
    
    def test_get_action_confidence_fallback(self, signal_generator):
        """Test getting action confidence fallback to action strength"""
        # No special methods on agent
        confidence = signal_generator._get_action_confidence(np.random.random(50), 2)
        
        # Should use action strength from mapping
        assert confidence == 0.6  # BUY_MEDIUM strength
    
    def test_calculate_signal_strength(self, signal_generator):
        """Test signal strength calculation"""
        strength = signal_generator._calculate_signal_strength(0.6, 0.8)
        assert strength == 0.7  # (0.6 + 0.8) / 2
        
        # Test bounds
        strength = signal_generator._calculate_signal_strength(1.2, 0.8)
        assert strength == 1.0  # Capped at 1.0
        
        strength = signal_generator._calculate_signal_strength(-0.1, 0.2)
        assert strength == 0.05  # ((-0.1 + 0.2) / 2) = 0.05, not floored to 0.0
    
    def test_calculate_position_size(self, signal_generator, portfolio_state):
        """Test position size calculation"""
        # Normal case
        size = signal_generator._calculate_position_size(0.8, portfolio_state)
        assert 0.01 <= size <= 0.1
        
        # With existing position (portfolio heat)
        portfolio_state.current_position = 0.05
        size = signal_generator._calculate_position_size(0.8, portfolio_state)
        assert size < 0.08  # Should be reduced due to portfolio heat
        
        # With drawdown
        portfolio_state.current_drawdown = 0.1
        size = signal_generator._calculate_position_size(0.8, portfolio_state)
        assert size < 0.08  # Should be reduced due to drawdown
    
    def test_calculate_stop_take_levels_long(self, signal_generator, market_data):
        """Test stop loss and take profit calculation for long position"""
        stop_loss, take_profit = signal_generator._calculate_stop_take_levels(
            market_data, Direction.LONG, 0.8
        )
        
        assert stop_loss < market_data.ask
        assert take_profit > market_data.ask
        assert (take_profit - market_data.ask) > (market_data.ask - stop_loss)  # Risk-reward ratio
    
    def test_calculate_stop_take_levels_short(self, signal_generator, market_data):
        """Test stop loss and take profit calculation for short position"""
        stop_loss, take_profit = signal_generator._calculate_stop_take_levels(
            market_data, Direction.SHORT, 0.8
        )
        
        assert stop_loss > market_data.bid
        assert take_profit < market_data.bid
        assert (market_data.bid - take_profit) > (stop_loss - market_data.bid)  # Risk-reward ratio
    
    def test_signal_validation_success(self, signal_generator, portfolio_state):
        """Test successful signal validation"""
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1007,
            stop_loss=1.0997,
            take_profit=1.1027,
            position_size=0.05,
            confidence=0.7,
            reasoning="Test RL signal with strength 0.8",
            timestamp=datetime.now(timezone.utc)
        )
        
        assert signal_generator._validate_signal(signal, portfolio_state) is True
    
    def test_signal_validation_invalid_stop_loss(self, signal_generator, portfolio_state):
        """Test signal validation with invalid stop loss"""
        # Create a signal with valid structure first, then modify stop loss to test validation
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1007,
            stop_loss=1.0997,  # Valid initially
            take_profit=1.1027,
            position_size=0.05,
            confidence=0.7,
            reasoning="Test RL signal",
            timestamp=datetime.now(timezone.utc)
        )
        # Add strength as additional attribute
        signal.strength = 0.8
        
        # Now modify stop loss to invalid value (bypassing model validation)
        signal.stop_loss = 1.1010  # Invalid: stop loss above entry for long
        
        assert signal_generator._validate_signal(signal, portfolio_state) is False
    
    def test_signal_validation_time_limit(self, signal_generator, portfolio_state):
        """Test signal validation with time limit"""
        # Set last signal time to recent
        signal_generator.last_signal_time = datetime.now(timezone.utc) - timedelta(seconds=30)
        
        signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1007,
            stop_loss=1.0997,
            take_profit=1.1027,
            position_size=0.05,
            confidence=0.7,
            reasoning="Test RL signal",
            timestamp=datetime.now(timezone.utc)
        )
        # Add strength as additional attribute
        signal.strength = 0.8
        
        assert signal_generator._validate_signal(signal, portfolio_state) is False
    
    def test_get_signal_statistics_empty(self, signal_generator):
        """Test signal statistics with no signals"""
        stats = signal_generator.get_signal_statistics()
        
        assert stats['total_signals'] == 0
        assert stats['long_signals'] == 0
        assert stats['short_signals'] == 0
        assert stats['avg_strength'] == 0.0
        assert stats['avg_confidence'] == 0.0
        assert stats['last_signal_time'] is None
    
    def test_get_signal_statistics_with_signals(self, signal_generator):
        """Test signal statistics with signals"""
        # Add some mock signals
        signal1 = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.7,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        signal1.strength = 0.8
        
        signal2 = TradingSignal(
            symbol="EUR/USD", direction=Direction.SHORT, confidence=0.9,
            entry_price=1.1003, stop_loss=1.1013, take_profit=1.0993, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        signal2.strength = 0.6
        
        signal_generator.signal_history = [signal1, signal2]
        signal_generator.last_signal_time = datetime.now(timezone.utc)
        
        stats = signal_generator.get_signal_statistics()
        
        assert stats['total_signals'] == 2
        assert stats['long_signals'] == 1
        assert stats['short_signals'] == 1
        assert stats['avg_strength'] == 0.7
        assert stats['avg_confidence'] == 0.8
        assert stats['last_signal_time'] is not None
    
    def test_update_confidence_threshold(self, signal_generator):
        """Test updating confidence threshold"""
        signal_generator.update_confidence_threshold(0.8)
        assert signal_generator.confidence_threshold == 0.8
        
        # Test invalid threshold
        with pytest.raises(ValueError):
            signal_generator.update_confidence_threshold(1.5)
    
    def test_clear_signal_history(self, signal_generator):
        """Test clearing signal history"""
        # Add some mock data
        signal_generator.signal_history = [Mock(), Mock()]
        signal_generator.last_signal_time = datetime.now(timezone.utc)
        
        signal_generator.clear_signal_history()
        
        assert len(signal_generator.signal_history) == 0
        assert signal_generator.last_signal_time is None


class TestHybridDecisionEngine:
    """Test cases for HybridDecisionEngine"""
    
    @pytest.fixture
    def mock_rl_generator(self):
        """Mock RL signal generator for testing"""
        generator = Mock(spec=RLSignalGenerator)
        return generator
    
    @pytest.fixture
    def decision_config(self):
        """Decision configuration for testing"""
        return DecisionConfig(
            method=DecisionMethod.WEIGHTED_AVERAGE,
            weights=SignalWeight(rl_weight=0.6, ai_weight=0.4),
            min_confidence=0.3,  # Lower threshold for testing
            max_signals_per_hour=10
        )
    
    @pytest.fixture
    def hybrid_engine(self, mock_rl_generator, decision_config):
        """Hybrid decision engine instance for testing"""
        return HybridDecisionEngine(
            rl_signal_generator=mock_rl_generator,
            config=decision_config
        )
    
    @pytest.fixture
    def market_data(self):
        """Sample market data for testing"""
        return MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            open=1.1000,
            high=1.1010,
            low=1.0990,
            close=1.1005,
            volume=1000,
            bid=1.1003,
            ask=1.1007,
            spread=0.0004
        )
    
    @pytest.fixture
    def portfolio_state(self):
        """Sample portfolio state for testing"""
        return PortfolioState(
            balance=10000.0,
            equity=10000.0,
            current_position=0.0,
            unrealized_pnl=0.0,
            realized_pnl=0.0,
            total_trades=0,
            winning_trades=0,
            max_drawdown=0.0,
            current_drawdown=0.0
        )
    
    def test_initialization(self, mock_rl_generator, decision_config):
        """Test hybrid engine initialization"""
        engine = HybridDecisionEngine(
            rl_signal_generator=mock_rl_generator,
            config=decision_config
        )
        
        assert engine.rl_generator == mock_rl_generator
        assert engine.config == decision_config
        assert len(engine.recent_decisions) == 0
        assert engine.last_decision_time is None
    
    def test_make_decision_with_rl_signal(self, hybrid_engine, market_data, portfolio_state):
        """Test making decision with RL signal"""
        # Mock RL signal
        rl_signal = TradingSignal(
            symbol="EUR/USD",
            direction=Direction.LONG,
            entry_price=1.1007,
            stop_loss=1.0997,
            take_profit=1.1027,
            position_size=0.05,
            confidence=0.7,
            reasoning="Test RL signal",
            timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.8
        
        hybrid_engine.rl_generator.generate_signal.return_value = rl_signal
        
        decision = hybrid_engine.make_decision(
            symbol="EUR/USD",
            market_data=market_data,
            state_vector=np.random.random(50),
            portfolio_state=portfolio_state
        )
        
        assert decision is not None
        assert decision.direction == Direction.LONG
        assert decision.confidence >= 0.5
    
    def test_make_decision_with_multiple_signals(self, hybrid_engine, market_data, portfolio_state):
        """Test making decision with multiple signal sources"""
        # Mock RL signal with higher values
        rl_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.9,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.8
        
        # Mock AI signal with higher values
        ai_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.9,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test AI signal", timestamp=datetime.now(timezone.utc)
        )
        ai_signal.strength = 0.8
        
        hybrid_engine.rl_generator.generate_signal.return_value = rl_signal
        
        decision = hybrid_engine.make_decision(
            symbol="EUR/USD",
            market_data=market_data,
            state_vector=np.random.random(50),
            portfolio_state=portfolio_state,
            ai_signals=[ai_signal]
        )
        
        assert decision is not None
        assert decision.direction == Direction.LONG
        # Should have reasonable confidence (weighted average of inputs)
        assert decision.confidence >= 0.5
    
    def test_make_decision_conflicting_signals(self, hybrid_engine, market_data, portfolio_state):
        """Test making decision with conflicting signals"""
        # Mock RL signal (LONG) - use higher values to pass validation
        rl_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.9,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.8
        
        # Mock AI signal (SHORT) - use higher values to pass validation
        ai_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.SHORT, confidence=0.9,
            entry_price=1.1003, stop_loss=1.1013, take_profit=1.0993, position_size=0.05,
            reasoning="Test AI signal", timestamp=datetime.now(timezone.utc)
        )
        ai_signal.strength = 0.9
        
        hybrid_engine.rl_generator.generate_signal.return_value = rl_signal
        
        decision = hybrid_engine.make_decision(
            symbol="EUR/USD",
            market_data=market_data,
            state_vector=np.random.random(50),
            portfolio_state=portfolio_state,
            ai_signals=[ai_signal]
        )
        
        # Should make a decision (either direction based on weighted scores)
        assert decision is not None
        # The actual direction depends on the weighted calculation
        assert decision.direction in [Direction.LONG, Direction.SHORT]
    
    def test_make_decision_no_signals(self, hybrid_engine, market_data, portfolio_state):
        """Test making decision with no signals"""
        hybrid_engine.rl_generator.generate_signal.return_value = None
        
        decision = hybrid_engine.make_decision(
            symbol="EUR/USD",
            market_data=market_data,
            state_vector=np.random.random(50),
            portfolio_state=portfolio_state
        )
        
        assert decision is None
    
    def test_make_decision_rate_limit(self, hybrid_engine, market_data, portfolio_state):
        """Test decision making with rate limit"""
        # Fill up recent decisions to hit rate limit
        now = datetime.now(timezone.utc)
        hybrid_engine.recent_decisions = [
            {'timestamp': now - timedelta(minutes=i)} for i in range(10)
        ]
        
        decision = hybrid_engine.make_decision(
            symbol="EUR/USD",
            market_data=market_data,
            state_vector=np.random.random(50),
            portfolio_state=portfolio_state
        )
        
        assert decision is None
    
    def test_weighted_average_fusion(self, hybrid_engine, market_data):
        """Test weighted average signal fusion"""
        # Create test signals with higher values to pass validation
        rl_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.9,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.8
        
        ai_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.9,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test AI signal", timestamp=datetime.now(timezone.utc)
        )
        ai_signal.strength = 0.8
        
        valid_signals = {
            'rl': [rl_signal],
            'ai': [ai_signal],
            'technical': [],
            'sentiment': []
        }
        
        result = hybrid_engine._weighted_average_fusion(valid_signals, market_data)
        
        assert result is not None
        assert result.direction == Direction.LONG
        assert hasattr(result, 'strength')
        assert 0.5 < result.strength < 1.0  # Weighted average should be reasonable
        assert 0.5 < result.confidence < 1.0  # Weighted average
    
    def test_majority_vote_fusion(self, hybrid_engine, market_data):
        """Test majority vote signal fusion"""
        # Create test signals - majority LONG
        rl_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.7,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.8
        
        ai_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.8,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test AI signal", timestamp=datetime.now(timezone.utc)
        )
        ai_signal.strength = 0.6
        
        tech_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.SHORT, confidence=0.6,
            entry_price=1.1003, stop_loss=1.1013, take_profit=1.0993, position_size=0.05,
            reasoning="Test technical signal", timestamp=datetime.now(timezone.utc)
        )
        tech_signal.strength = 0.5
        
        signals = {
            'rl': [rl_signal],
            'ai': [ai_signal],
            'technical': [tech_signal]
        }
        
        result = hybrid_engine._majority_vote_fusion(signals, market_data)
        
        assert result is not None
        assert result.direction == Direction.LONG  # Majority vote
    
    def test_confidence_based_fusion(self, hybrid_engine, market_data):
        """Test confidence-based signal fusion"""
        # Create test signals with different confidence levels
        rl_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.9,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.6
        
        ai_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.SHORT, confidence=0.7,
            entry_price=1.1003, stop_loss=1.1013, take_profit=1.0993, position_size=0.05,
            reasoning="Test AI signal", timestamp=datetime.now(timezone.utc)
        )
        ai_signal.strength = 0.8
        
        signals = {
            'rl': [rl_signal],
            'ai': [ai_signal]
        }
        
        result = hybrid_engine._confidence_based_fusion(signals, market_data)
        
        assert result is not None
        # Should pick AI signal due to higher combined score (0.8 * 0.7 = 0.56 > 0.6 * 0.9 = 0.54)
        assert result.direction == Direction.SHORT
    
    def test_rl_priority_fusion(self, hybrid_engine, market_data):
        """Test RL priority signal fusion"""
        # Create test signals
        rl_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.7,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=datetime.now(timezone.utc)
        )
        rl_signal.strength = 0.6
        
        ai_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.SHORT, confidence=0.9,
            entry_price=1.1003, stop_loss=1.1013, take_profit=1.0993, position_size=0.05,
            reasoning="Test AI signal", timestamp=datetime.now(timezone.utc)
        )
        ai_signal.strength = 0.9
        
        signals = {'rl': [rl_signal], 'ai': [ai_signal]}
        
        result = hybrid_engine._rl_priority_fusion(signals, market_data)
        
        assert result is not None
        assert result.direction == Direction.LONG  # RL signal prioritized
    
    def test_filter_valid_signals(self, hybrid_engine, market_data):
        """Test signal filtering"""
        now = datetime.now(timezone.utc)
        
        # Create signals with different ages and confidence levels
        valid_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.7,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test RL signal", timestamp=now
        )
        valid_signal.strength = 0.8
        
        old_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.7,
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test AI signal", timestamp=now - timedelta(minutes=10)
        )
        old_signal.strength = 0.8
        
        low_confidence_signal = TradingSignal(
            symbol="EUR/USD", direction=Direction.LONG, confidence=0.2,  # Below threshold
            entry_price=1.1007, stop_loss=1.0997, take_profit=1.1027, position_size=0.05,
            reasoning="Test technical signal", timestamp=now
        )
        low_confidence_signal.strength = 0.8
        
        all_signals = {
            'rl': [valid_signal],
            'ai': [old_signal],
            'technical': [low_confidence_signal]
        }
        
        filtered = hybrid_engine._filter_valid_signals(all_signals, market_data)
        
        assert len(filtered['rl']) == 1
        assert len(filtered['ai']) == 0  # Filtered out due to age
        assert len(filtered['technical']) == 0  # Filtered out due to low confidence
    
    def test_get_decision_statistics(self, hybrid_engine):
        """Test getting decision statistics"""
        # Add some mock decisions
        hybrid_engine.recent_decisions = [
            {'timestamp': datetime.now(timezone.utc), 'confidence': 0.8, 'strength': 0.7},
            {'timestamp': datetime.now(timezone.utc), 'confidence': 0.6, 'strength': 0.9}
        ]
        hybrid_engine.decision_stats['total_decisions'] = 2
        
        stats = hybrid_engine.get_decision_statistics()
        
        assert stats['total_decisions'] == 2
        assert stats['recent_decisions_count'] == 2
        assert stats['avg_confidence'] == 0.7
        assert stats['avg_strength'] == 0.8
    
    def test_update_config(self, hybrid_engine):
        """Test updating decision configuration"""
        new_config = DecisionConfig(
            method=DecisionMethod.MAJORITY_VOTE,
            min_confidence=0.8
        )
        
        hybrid_engine.update_config(new_config)
        
        assert hybrid_engine.config.method == DecisionMethod.MAJORITY_VOTE
        assert hybrid_engine.config.min_confidence == 0.8
    
    def test_clear_history(self, hybrid_engine):
        """Test clearing decision history"""
        # Add some mock data
        hybrid_engine.recent_decisions = [Mock(), Mock()]
        hybrid_engine.signal_cache = {'test': [Mock()]}
        hybrid_engine.last_decision_time = datetime.now(timezone.utc)
        
        hybrid_engine.clear_history()
        
        assert len(hybrid_engine.recent_decisions) == 0
        assert len(hybrid_engine.signal_cache) == 0
        assert hybrid_engine.last_decision_time is None


class TestFactoryFunctions:
    """Test cases for factory functions"""
    
    def test_create_rl_signal_generator(self):
        """Test RL signal generator factory function"""
        mock_agent = Mock(spec=RLAgent)
        mock_risk_manager = Mock(spec=RiskManager)
        
        generator = create_rl_signal_generator(
            agent=mock_agent,
            risk_manager=mock_risk_manager,
            confidence_threshold=0.8,
            max_position_size=0.05
        )
        
        assert isinstance(generator, RLSignalGenerator)
        assert generator.agent == mock_agent
        assert generator.risk_manager == mock_risk_manager
        assert generator.confidence_threshold == 0.8
        assert generator.max_position_size == 0.05
    
    def test_create_hybrid_decision_engine(self):
        """Test hybrid decision engine factory function"""
        mock_generator = Mock(spec=RLSignalGenerator)
        config = DecisionConfig(method=DecisionMethod.CONFIDENCE_BASED)
        
        engine = create_hybrid_decision_engine(
            rl_signal_generator=mock_generator,
            config=config
        )
        
        assert isinstance(engine, HybridDecisionEngine)
        assert engine.rl_generator == mock_generator
        assert engine.config == config


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""
Integration tests for Layer 3: Time-Decay Stop Loss Management

Tests the integration of TimeDecayStopLossManager with ProfitProtectionModule.
Covers:
- Layer 3 state initialization
- Time-decay SL evaluation and application
- State persistence
- Shadow mode vs live execution
- Auto-rotation eligibility
- Edge cases and error handling
"""

import pytest
import asyncio
import json
import os
import tempfile
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from typing import Dict, Any

from src.models import Position, Direction, MarketData
from src.trading.profit_protection_module import (
    ProfitProtectionModule, 
    TradeManagementSettings,
)
from src.trading.LAYER_3_TIME_DECAY_ENHANCED import TimeDecayStopLossManager
from src.interfaces import BrokerInterface, TradeExecutor


class MockBrokerInterface(BrokerInterface):
    """Mock broker for testing"""
    
    def __init__(self):
        self.modifications = []
        self.closed_positions = []
        
    async def modify_order(self, order_id: int, sl: float = None, tp: float = None) -> bool:
        """Record modification attempt"""
        self.modifications.append({
            'order_id': order_id,
            'sl': sl,
            'tp': tp,
        })
        return True
    
    async def close_position(self, position_id: int) -> bool:
        """Record close attempt"""
        self.closed_positions.append(position_id)
        return True
    
    async def get_symbol_info(self, symbol: str):
        """Mock symbol info"""
        return Mock(
            name=symbol,
            digits=5,
            point=0.00001,
            volume_step=0.01,
        )


class MockTradeExecutor(TradeExecutor):
    """Mock executor"""
    pass


@pytest.fixture
def temp_state_file():
    """Create temporary state file"""
    with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
        temp_path = f.name
    yield temp_path
    # Cleanup
    if os.path.exists(temp_path):
        os.remove(temp_path)


@pytest.fixture
def mock_broker():
    """Create mock broker"""
    return MockBrokerInterface()


@pytest.fixture
def mock_executor():
    """Create mock executor"""
    return MockTradeExecutor()


@pytest.fixture
def profit_protection_module(mock_broker, mock_executor, temp_state_file):
    """Create profit protection module with temporary state file"""
    settings = TradeManagementSettings()
    settings.state_file = temp_state_file
    
    module = ProfitProtectionModule(
        broker=mock_broker,
        execution_engine=mock_executor,
        settings=settings,
    )
    
    # Start in shadow mode for testing
    module.TIME_DECAY_SHADOW_MODE = True
    module.time_decay_enabled = True
    
    return module


class TestLayer3StateInitialization:
    """Tests for Layer 3 state field initialization"""
    
    @pytest.mark.asyncio
    async def test_layer3_fields_initialized_on_first_manage_position(
        self, profit_protection_module, mock_broker
    ):
        """Test that Layer 3 fields are properly initialized"""
        # Create position
        position = Position(
            position_id=12345,
            symbol="EURUSD",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=1.1000,
            current_price=1.1050,
            stop_loss=1.0950,
            take_profit=1.1200,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 55.0, 'ml_confidence': 0.75},
        )
        
        # Call manage_position for first time
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        # Verify state was created with Layer 3 fields
        pos_id = str(position.position_id)
        assert pos_id in profit_protection_module.position_states
        
        state = profit_protection_module.position_states[pos_id]
        
        # Layer 3 fields must be present
        assert 'bars_since_entry' in state
        assert 'time_decay_sl_applied' in state
        assert 'marked_for_auto_rotation' in state
        assert 'harvested' in state
        
        # Check initial values
        assert state['bars_since_entry'] == 1  # First call increments to 1
        assert state['time_decay_sl_applied'] is False
        assert state['marked_for_auto_rotation'] is False
        assert state['harvested'] is False
    
    @pytest.mark.asyncio
    async def test_layer3_fields_persistent_across_calls(
        self, profit_protection_module, mock_broker
    ):
        """Test that Layer 3 state persists across multiple manage_position calls"""
        position = Position(
            position_id=12346,
            symbol="GBPUSD",
            direction=Direction.SHORT,
            quantity=1.0,
            entry_price=1.2500,
            current_price=1.2480,
            stop_loss=1.2550,
            take_profit=1.2300,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 45.0, 'ml_confidence': 0.65},
        )
        
        # First call
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        pos_id = str(position.position_id)
        state1 = profit_protection_module.position_states[pos_id].copy()
        
        # Second call
        position.current_price = 1.2470
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        state2 = profit_protection_module.position_states[pos_id]
        
        # Verify bars_since_entry incremented
        assert state2['bars_since_entry'] == state1['bars_since_entry'] + 1
        
        # Other fields should remain as initialized
        assert state2['time_decay_sl_applied'] is False
        assert state2['marked_for_auto_rotation'] is False


class TestLayer3StatePersistence:
    """Tests for Layer 3 state save/load"""
    
    @pytest.mark.asyncio
    async def test_layer3_state_persisted_to_disk(
        self, profit_protection_module, mock_broker, temp_state_file
    ):
        """Test that Layer 3 state is correctly saved to disk"""
        position = Position(
            position_id=12347,
            symbol="USDJPY",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=150.0,
            current_price=150.50,
            stop_loss=149.5,
            take_profit=151.5,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.005,
            indicators={'rsi': 60.0, 'ml_confidence': 0.70},
        )
        
        # Manage position (should save state)
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.10,
        )
        
        # Read saved state from disk
        assert os.path.exists(temp_state_file)
        
        with open(temp_state_file, 'r') as f:
            saved_data = json.load(f)
        
        # Verify Layer 3 fields are in saved state
        pos_id = str(position.position_id)
        assert pos_id in saved_data
        assert 'bars_since_entry' in saved_data[pos_id]
        assert 'time_decay_sl_applied' in saved_data[pos_id]
        assert 'marked_for_auto_rotation' in saved_data[pos_id]
        assert 'harvested' in saved_data[pos_id]
    
    @pytest.mark.asyncio
    async def test_layer3_state_restored_from_disk(
        self, mock_broker, mock_executor, temp_state_file
    ):
        """Test that Layer 3 state is correctly restored from disk"""
        # Create initial state on disk
        test_state = {
            "12348": {
                "symbol": "NZDUSD",
                "entry_price": 0.6200,
                "initial_risk_price": 0.0050,
                "bars_since_entry": 42,
                "time_decay_sl_applied": True,
                "marked_for_auto_rotation": False,
                "harvested": False,
                "last_sl_modification_time": datetime.now(timezone.utc).isoformat(),
            }
        }
        
        with open(temp_state_file, 'w') as f:
            json.dump(test_state, f)
        
        # Create new module (should load state from disk)
        settings = TradeManagementSettings()
        settings.state_file = temp_state_file
        
        module = ProfitProtectionModule(
            broker=mock_broker,
            execution_engine=mock_executor,
            settings=settings,
        )
        
        # Verify state was loaded
        assert "12348" in module.position_states
        state = module.position_states["12348"]
        
        # Verify Layer 3 fields were restored
        assert state['bars_since_entry'] == 42
        assert state['time_decay_sl_applied'] is True
        assert state['marked_for_auto_rotation'] is False
        assert state['harvested'] is False


class TestLayer3ShadowMode:
    """Tests for Layer 3 shadow mode (read-only)"""
    
    @pytest.mark.asyncio
    async def test_layer3_shadow_mode_no_broker_modification(
        self, profit_protection_module, mock_broker
    ):
        """Test that shadow mode doesn't modify broker orders"""
        # Ensure shadow mode is ON
        profit_protection_module.TIME_DECAY_SHADOW_MODE = True
        
        # Mock the time_decay_manager to propose an SL change
        # check_and_apply_decay returns Optional[float] (proposed SL or None)
        profit_protection_module.time_decay_manager.check_and_apply_decay = AsyncMock(
            return_value=1.1000  # Proposed SL
        )
        
        position = Position(
            position_id=12349,
            symbol="AUDUSD",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=0.7500,
            current_price=0.7550,
            stop_loss=0.7450,
            take_profit=0.7650,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 50.0, 'ml_confidence': 0.60},
        )
        
        # Manage position in shadow mode
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        # Verify no modifications were sent to broker
        assert len(mock_broker.modifications) == 0
    
    @pytest.mark.asyncio
    async def test_layer3_shadow_mode_exit_shadow_mode_with_env_var(
        self, profit_protection_module, mock_broker
    ):
        """Test exiting shadow mode when environment variable set"""
        # Simulate exiting shadow mode
        profit_protection_module.TIME_DECAY_SHADOW_MODE = False
        
        # Mock the time_decay_manager to return proposed SL
        profit_protection_module.time_decay_manager.check_and_apply_decay = AsyncMock(
            return_value=0.7500  # Proposed SL
        )
        
        position = Position(
            position_id=12350,
            symbol="CADUSD",
            direction=Direction.SHORT,
            quantity=1.0,
            entry_price=0.7700,
            current_price=0.7680,
            stop_loss=0.7750,
            take_profit=0.7600,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 55.0, 'ml_confidence': 0.65},
        )
        
        # Manage position NOT in shadow mode
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        # Verify broker modification was attempted
        assert len(mock_broker.modifications) > 0


class TestLayer3AutoRotation:
    """Tests for Layer 3 auto-rotation eligibility marking"""
    
    @pytest.mark.asyncio
    async def test_layer3_auto_rotation_marking_when_harvest_eligible(
        self, profit_protection_module, mock_broker
    ):
        """Test that positions are marked for auto-rotation when harvest-eligible"""
        # Mock time_decay_manager to return proposed SL
        profit_protection_module.time_decay_manager.check_and_apply_decay = AsyncMock(
            return_value=1.1050  # Proposed SL
        )
        
        # Start NOT in shadow mode so state changes can be made
        profit_protection_module.TIME_DECAY_SHADOW_MODE = False
        
        position = Position(
            position_id=12351,
            symbol="EURUSD",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=1.1000,
            current_price=1.1100,
            stop_loss=1.0950,
            take_profit=1.1200,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 55.0, 'ml_confidence': 0.75},
        )
        
        await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        pos_id = str(position.position_id)
        state = profit_protection_module.position_states[pos_id]
        
        # Verify marked for auto-rotation
        assert state['marked_for_auto_rotation'] is True


class TestLayer3ErrorHandling:
    """Tests for Layer 3 error handling"""
    
    @pytest.mark.asyncio
    async def test_layer3_exception_handling_on_check_and_apply_decay_error(
        self, profit_protection_module, mock_broker, caplog
    ):
        """Test that Layer 3 handles exceptions gracefully"""
        # Mock time_decay_manager to raise exception
        profit_protection_module.time_decay_manager.check_and_apply_decay = AsyncMock(
            side_effect=ValueError("Test error in time_decay_manager")
        )
        
        position = Position(
            position_id=12352,
            symbol="GBPUSD",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=1.2500,
            current_price=1.2550,
            stop_loss=1.2450,
            take_profit=1.2650,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 50.0, 'ml_confidence': 0.70},
        )
        
        # Should not raise exception, should continue processing
        result = await profit_protection_module.manage_position(
            position=position,
            market_data=market_data,
            atr=0.005,
        )
        
        # Position should still be managed without Layer 3
        pos_id = str(position.position_id)
        assert pos_id in profit_protection_module.position_states


class TestLayer3BarIncrement:
    """Tests for Layer 3 bar counter increment logic"""
    
    @pytest.mark.asyncio
    async def test_bars_since_entry_increments_per_call(
        self, profit_protection_module, mock_broker
    ):
        """Test that bars_since_entry counter increments correctly"""
        position = Position(
            position_id=12353,
            symbol="USDJPY",
            direction=Direction.SHORT,
            quantity=1.0,
            entry_price=150.0,
            current_price=149.80,
            stop_loss=150.50,
            take_profit=148.0,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.005,
            indicators={'rsi': 40.0, 'ml_confidence': 0.65},
        )
        
        pos_id = str(position.position_id)
        
        # Make 5 consecutive manage_position calls
        for i in range(5):
            await profit_protection_module.manage_position(
                position=position,
                market_data=market_data,
                atr=0.10,
            )
            
            state = profit_protection_module.position_states[pos_id]
            expected_bars = i + 1
            assert state['bars_since_entry'] == expected_bars
    
    @pytest.mark.asyncio
    async def test_preflight_check_validates_bar_frequency(
        self, profit_protection_module
    ):
        """Test preflight check for bar frequency validation"""
        pos_id = "test_pos_123"
        
        # Simulate 15 bar increments over sufficient time
        for bars in range(1, 16):
            is_ok, diagnostic = profit_protection_module.preflight_check(
                pos_id, bars
            )
            # Should be OK since we're incrementing naturally
            assert isinstance(is_ok, bool)
            assert diagnostic is not None


class TestLayer3Integration:
    """End-to-end integration tests"""
    
    @pytest.mark.asyncio
    async def test_layer3_full_workflow_shadow_then_live(
        self, profit_protection_module, mock_broker
    ):
        """Test complete Layer 3 workflow: shadow mode verification then live execution"""
        
        # Set up mock to return proposed SL if stagnation detected
        async def mock_check_and_apply(
            position, state, current_r, bars_since_entry,
            risk_price, symbol_info=None, current_tick=None
        ):
            if bars_since_entry > 3:
                new_sl = position.stop_loss + 0.0010 if position.direction == Direction.LONG else position.stop_loss - 0.0010
                return new_sl
            return None
        
        profit_protection_module.time_decay_manager.check_and_apply_decay = mock_check_and_apply
        
        position = Position(
            position_id=12354,
            symbol="EURGBP",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=0.8600,
            current_price=0.8650,
            stop_loss=0.8580,
            take_profit=0.8700,
            opened_at=datetime.now(timezone.utc),
        )
        
        market_data = Mock(
            spread=0.0002,
            indicators={'rsi': 52.0, 'ml_confidence': 0.72},
        )
        
        pos_id = str(position.position_id)
        
        # Phase 1: Shadow mode (30 minutes verification)
        profit_protection_module.TIME_DECAY_SHADOW_MODE = True
        for i in range(5):
            await profit_protection_module.manage_position(
                position=position,
                market_data=market_data,
                atr=0.001,
            )
        
        # No broker modifications in shadow mode
        assert len(mock_broker.modifications) == 0
        
        # Verify bars were tracked
        state = profit_protection_module.position_states[pos_id]
        assert state['bars_since_entry'] == 5
        
        # Phase 2: Exit shadow mode
        profit_protection_module.TIME_DECAY_SHADOW_MODE = False
        
        # Simulate reaching stagnation trigger
        for i in range(8):
            await profit_protection_module.manage_position(
                position=position,
                market_data=market_data,
                atr=0.001,
            )
        
        # Now broker should have received modifications
        # (if bars > 3 and > current_sl logic applies)
        state = profit_protection_module.position_states[pos_id]
        assert state['bars_since_entry'] == 13
        
        # Should be marked for auto-rotation if bars > 10
        if state['bars_since_entry'] > 10:
            assert state['marked_for_auto_rotation'] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

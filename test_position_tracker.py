"""Unit tests for PositionTracker"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from src.trading.position_tracker import PositionTracker
from src.data.mock_broker import MockBrokerInterface
from src.models import (
    Position, Direction, ExecutionResult, Order, OrderType, OrderStatus,
    MarketData
)
from src.exceptions import DataValidationError, BrokerAPIError


@pytest.fixture
def mock_broker():
    """Create mock broker interface"""
    broker = MockBrokerInterface()
    return broker


@pytest.fixture
def position_tracker(mock_broker):
    """Create position tracker with mock broker"""
    return PositionTracker(mock_broker, update_interval=0.1)


@pytest.fixture
def sample_execution_result():
    """Create sample execution result"""
    return ExecutionResult(
        success=True,
        order_id="ORDER_001",
        executed_price=1.0850,
        executed_quantity=10000.0,
        error_message=None,
        timestamp=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_order():
    """Create sample order"""
    return Order(
        order_id="ORDER_001",
        symbol="EUR/USD",
        order_type=OrderType.MARKET,
        direction=Direction.LONG,
        quantity=10000.0,
        price=None,
        stop_loss=1.0800,
        take_profit=1.0900,
        status=OrderStatus.PENDING,
        created_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_position():
    """Create sample position"""
    return Position(
        position_id="POS_001",
        symbol="EUR/USD",
        direction=Direction.LONG,
        quantity=10000.0,
        entry_price=1.0850,
        current_price=1.0850,
        unrealized_pnl=0.0,
        stop_loss=1.0800,
        take_profit=1.0900,
        opened_at=datetime.now(timezone.utc)
    )


class TestPositionTracker:
    """Test cases for PositionTracker"""
    
    def test_initialization(self, mock_broker):
        """Test position tracker initialization"""
        tracker = PositionTracker(mock_broker, update_interval=0.5)
        
        assert tracker.broker == mock_broker
        assert tracker.update_interval == 0.5
        assert len(tracker.positions) == 0
        assert tracker.is_monitoring is False
        assert tracker.metrics['total_positions'] == 0
    
    @pytest.mark.asyncio
    async def test_add_position_success(self, position_tracker, sample_execution_result, sample_order):
        """Test successful position addition"""
        position_id = await position_tracker.add_position(sample_execution_result, sample_order)
        
        # Verify position was added
        assert position_id in position_tracker.positions
        position = position_tracker.positions[position_id]
        
        assert position.symbol == sample_order.symbol
        assert position.direction == sample_order.direction
        assert position.quantity == sample_execution_result.executed_quantity
        assert position.entry_price == sample_execution_result.executed_price
        assert position.stop_loss == sample_order.stop_loss
        assert position.take_profit == sample_order.take_profit
        
        # Check metrics
        assert position_tracker.metrics['total_positions'] == 1
        assert position_tracker.metrics['open_positions'] == 1
    
    @pytest.mark.asyncio
    async def test_add_position_failed_execution(self, position_tracker, sample_order):
        """Test adding position from failed execution"""
        failed_result = ExecutionResult(
            success=False,
            order_id="ORDER_001",
            executed_price=None,
            executed_quantity=None,
            error_message="Execution failed",
            timestamp=datetime.now(timezone.utc)
        )
        
        with pytest.raises(DataValidationError, match="Cannot create position from failed execution"):
            await position_tracker.add_position(failed_result, sample_order)
    
    @pytest.mark.asyncio
    async def test_add_position_incomplete_execution(self, position_tracker, sample_order):
        """Test adding position from incomplete execution result"""
        # ExecutionResult validation prevents creating incomplete results
        # So we test this by creating a successful result but then modifying it
        complete_result = ExecutionResult(
            success=True,
            order_id="ORDER_001",
            executed_price=1.0850,
            executed_quantity=10000.0,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Manually set price to None to simulate incomplete result
        complete_result.executed_price = None
        
        with pytest.raises(DataValidationError, match="Execution result missing price or quantity"):
            await position_tracker.add_position(complete_result, sample_order)
    
    @pytest.mark.asyncio
    async def test_close_position_success(self, position_tracker, sample_execution_result, sample_order):
        """Test successful position closure"""
        # Add position first
        position_id = await position_tracker.add_position(sample_execution_result, sample_order)
        
        # Create closing execution result
        close_result = ExecutionResult(
            success=True,
            order_id="CLOSE_ORDER_001",
            executed_price=1.0870,  # Profitable close
            executed_quantity=10000.0,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Close position
        realized_pnl = await position_tracker.close_position(position_id, close_result)
        
        # Verify
        expected_pnl = (1.0870 - 1.0850) * 10000.0  # Long position profit
        assert abs(realized_pnl - expected_pnl) < 0.01
        assert position_id not in position_tracker.positions
        
        # Check metrics
        assert position_tracker.metrics['open_positions'] == 0
        assert position_tracker.metrics['closed_positions'] == 1
        assert position_tracker.metrics['winning_positions'] == 1
        assert position_tracker.metrics['realized_pnl'] == realized_pnl
    
    @pytest.mark.asyncio
    async def test_close_position_loss(self, position_tracker, sample_execution_result, sample_order):
        """Test closing position at a loss"""
        # Add position first
        position_id = await position_tracker.add_position(sample_execution_result, sample_order)
        
        # Create losing close result
        close_result = ExecutionResult(
            success=True,
            order_id="CLOSE_ORDER_001",
            executed_price=1.0830,  # Loss
            executed_quantity=10000.0,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
        
        # Close position
        realized_pnl = await position_tracker.close_position(position_id, close_result)
        
        # Verify
        expected_pnl = (1.0830 - 1.0850) * 10000.0  # Long position loss
        assert abs(realized_pnl - expected_pnl) < 0.01
        assert realized_pnl < 0
        
        # Check metrics
        assert position_tracker.metrics['losing_positions'] == 1
        assert position_tracker.metrics['largest_loss'] == realized_pnl
    
    @pytest.mark.asyncio
    async def test_close_position_short_profit(self, position_tracker, sample_order):
        """Test closing short position at profit"""
        # Create short position
        short_result = ExecutionResult(
            success=True,
            order_id="SHORT_ORDER",
            executed_price=1.0850,
            executed_quantity=10000.0,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
        
        sample_order.direction = Direction.SHORT
        position_id = await position_tracker.add_position(short_result, sample_order)
        
        # Close at lower price (profit for short)
        close_result = ExecutionResult(
            success=True,
            order_id="CLOSE_SHORT",
            executed_price=1.0830,
            executed_quantity=10000.0,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
        
        realized_pnl = await position_tracker.close_position(position_id, close_result)
        
        # Verify short position profit calculation
        expected_pnl = (1.0850 - 1.0830) * 10000.0
        assert abs(realized_pnl - expected_pnl) < 0.01
        assert realized_pnl > 0
    
    @pytest.mark.asyncio
    async def test_close_position_not_found(self, position_tracker):
        """Test closing non-existent position"""
        close_result = ExecutionResult(
            success=True,
            order_id="CLOSE_ORDER",
            executed_price=1.0870,
            executed_quantity=10000.0,
            error_message=None,
            timestamp=datetime.now(timezone.utc)
        )
        
        with pytest.raises(DataValidationError, match="Position .* not found"):
            await position_tracker.close_position("NON_EXISTENT", close_result)
    
    @pytest.mark.asyncio
    async def test_close_position_failed_execution(self, position_tracker, sample_execution_result, sample_order):
        """Test closing position with failed execution"""
        # Add position first
        position_id = await position_tracker.add_position(sample_execution_result, sample_order)
        
        # Create failed close result
        failed_close = ExecutionResult(
            success=False,
            order_id="FAILED_CLOSE",
            executed_price=None,
            executed_quantity=None,
            error_message="Close failed",
            timestamp=datetime.now(timezone.utc)
        )
        
        with pytest.raises(DataValidationError, match="Cannot close position with failed execution"):
            await position_tracker.close_position(position_id, failed_close)
    
    @pytest.mark.asyncio
    async def test_update_position_prices(self, position_tracker, sample_execution_result, sample_order, mock_broker):
        """Test position price updates"""
        # Setup
        await mock_broker.connect()
        position_id = await position_tracker.add_position(sample_execution_result, sample_order)
        
        # Update prices
        await position_tracker.update_position_prices()
        
        # Verify position was updated
        position = position_tracker.positions[position_id]
        assert position.current_price != position.entry_price  # Should have changed
        
        # Check unrealized P&L was updated
        assert position_tracker.metrics['unrealized_pnl'] != 0
    
    @pytest.mark.asyncio
    async def test_update_position_prices_broker_error(self, position_tracker, sample_execution_result, sample_order, mock_broker):
        """Test position price updates with broker error"""
        # Setup
        await mock_broker.connect()
        position_id = await position_tracker.add_position(sample_execution_result, sample_order)
        
        # Mock broker to raise error
        with patch.object(mock_broker, 'get_market_data', side_effect=BrokerAPIError("API Error")):
            # Should not raise exception, just log error
            await position_tracker.update_position_prices()
            
            # Position should remain unchanged
            position = position_tracker.positions[position_id]
            assert position.current_price == position.entry_price
    
    def test_get_position(self, position_tracker, sample_position):
        """Test getting position by ID"""
        # Add position manually
        position_tracker.positions["POS_001"] = sample_position
        
        # Test existing position
        retrieved = position_tracker.get_position("POS_001")
        assert retrieved == sample_position
        
        # Test non-existent position
        assert position_tracker.get_position("NON_EXISTENT") is None
    
    def test_get_positions_by_symbol(self, position_tracker):
        """Test getting positions by symbol"""
        # Add positions for different symbols
        pos1 = Position(
            position_id="POS_EUR_1",
            symbol="EUR/USD",
            direction=Direction.LONG,
            quantity=10000.0,
            entry_price=1.0850,
            current_price=1.0850,
            unrealized_pnl=0.0,
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        
        pos2 = Position(
            position_id="POS_GBP_1",
            symbol="GBP/USD",
            direction=Direction.SHORT,
            quantity=5000.0,
            entry_price=1.2650,
            current_price=1.2650,
            unrealized_pnl=0.0,
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        
        pos3 = Position(
            position_id="POS_EUR_2",
            symbol="EUR/USD",
            direction=Direction.SHORT,
            quantity=8000.0,
            entry_price=1.0860,
            current_price=1.0860,
            unrealized_pnl=0.0,
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        
        position_tracker.positions["POS_EUR_1"] = pos1
        position_tracker.positions["POS_GBP_1"] = pos2
        position_tracker.positions["POS_EUR_2"] = pos3
        
        # Test getting EUR/USD positions
        eur_positions = position_tracker.get_positions_by_symbol("EUR/USD")
        assert len(eur_positions) == 2
        assert pos1 in eur_positions
        assert pos3 in eur_positions
        
        # Test getting GBP/USD positions
        gbp_positions = position_tracker.get_positions_by_symbol("GBP/USD")
        assert len(gbp_positions) == 1
        assert pos2 in gbp_positions
        
        # Test non-existent symbol
        assert len(position_tracker.get_positions_by_symbol("USD/JPY")) == 0
    
    def test_get_all_positions(self, position_tracker, sample_position):
        """Test getting all positions"""
        # Empty initially
        assert len(position_tracker.get_all_positions()) == 0
        
        # Add position
        position_tracker.positions["POS_001"] = sample_position
        
        all_positions = position_tracker.get_all_positions()
        assert len(all_positions) == 1
        assert sample_position in all_positions
    
    def test_get_portfolio_summary(self, position_tracker):
        """Test portfolio summary generation"""
        # Add positions with correct P&L calculations
        pos1 = Position(
            position_id="POS_1",
            symbol="EUR/USD",
            direction=Direction.LONG,
            quantity=10000.0,
            entry_price=1.0850,
            current_price=1.0870,  # Profit
            unrealized_pnl=(1.0870 - 1.0850) * 10000.0,  # Correct calculation
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        
        pos2 = Position(
            position_id="POS_2",
            symbol="EUR/USD",
            direction=Direction.SHORT,
            quantity=5000.0,
            entry_price=1.0860,
            current_price=1.0850,  # Profit for short
            unrealized_pnl=(1.0860 - 1.0850) * 5000.0,  # Correct calculation
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        
        position_tracker.positions["POS_1"] = pos1
        position_tracker.positions["POS_2"] = pos2
        
        summary = position_tracker.get_portfolio_summary()
        
        expected_pnl = pos1.unrealized_pnl + pos2.unrealized_pnl
        
        assert summary['total_positions'] == 2
        assert abs(summary['total_unrealized_pnl'] - expected_pnl) < 0.01
        assert 'EUR/USD' in summary['positions_by_symbol']
        
        eur_summary = summary['positions_by_symbol']['EUR/USD']
        assert eur_summary['positions'] == 2
        assert eur_summary['total_quantity'] == 15000.0
        assert abs(eur_summary['unrealized_pnl'] - expected_pnl) < 0.01
        assert eur_summary['net_exposure'] == 5000.0  # 10000 long - 5000 short
    
    @pytest.mark.asyncio
    async def test_start_stop_monitoring(self, position_tracker):
        """Test starting and stopping monitoring"""
        # Initially not monitoring
        assert position_tracker.is_monitoring is False
        
        # Start monitoring
        await position_tracker.start_monitoring()
        assert position_tracker.is_monitoring is True
        assert position_tracker.monitoring_task is not None
        
        # Wait a bit to let monitoring run
        await asyncio.sleep(0.2)
        
        # Stop monitoring
        await position_tracker.stop_monitoring()
        assert position_tracker.is_monitoring is False
        assert position_tracker.monitoring_task is None
    
    @pytest.mark.asyncio
    async def test_start_monitoring_already_running(self, position_tracker):
        """Test starting monitoring when already running"""
        await position_tracker.start_monitoring()
        
        # Try to start again - should not create new task
        old_task = position_tracker.monitoring_task
        await position_tracker.start_monitoring()
        
        assert position_tracker.monitoring_task == old_task
        
        await position_tracker.stop_monitoring()
    
    @pytest.mark.asyncio
    async def test_stop_monitoring_not_running(self, position_tracker):
        """Test stopping monitoring when not running"""
        # Should not raise exception
        await position_tracker.stop_monitoring()
        assert position_tracker.is_monitoring is False
    
    def test_add_callbacks(self, position_tracker):
        """Test adding position and P&L callbacks"""
        position_callback = Mock()
        pnl_callback = Mock()
        
        position_tracker.add_position_callback(position_callback)
        position_tracker.add_pnl_callback(pnl_callback)
        
        assert position_callback in position_tracker.position_callbacks
        assert pnl_callback in position_tracker.pnl_callbacks
    
    @pytest.mark.asyncio
    async def test_position_callback_triggered(self, position_tracker, sample_execution_result, sample_order):
        """Test that position callbacks are triggered"""
        callback = Mock()
        position_tracker.add_position_callback(callback)
        
        # Add position - should trigger callback
        await position_tracker.add_position(sample_execution_result, sample_order)
        
        callback.assert_called_once()
    
    def test_get_position_history(self, position_tracker):
        """Test getting position history"""
        # Initially empty
        assert len(position_tracker.get_position_history()) == 0
        
        # Add some history manually
        event = {
            'timestamp': datetime.now(timezone.utc),
            'position_id': 'POS_001',
            'event_type': 'OPENED'
        }
        position_tracker.position_history.append(event)
        
        history = position_tracker.get_position_history()
        assert len(history) == 1
        assert history[0] == event
        
        # Test with limit
        limited_history = position_tracker.get_position_history(limit=0)
        assert len(limited_history) == 0  # Should return empty list when limit is 0
    
    def test_get_pnl_history(self, position_tracker):
        """Test getting P&L history"""
        # Initially empty
        assert len(position_tracker.get_pnl_history()) == 0
        
        # Add some history manually
        snapshot = {
            'timestamp': datetime.now(timezone.utc),
            'total_positions': 1,
            'unrealized_pnl': 100.0
        }
        position_tracker.pnl_history.append(snapshot)
        
        history = position_tracker.get_pnl_history()
        assert len(history) == 1
        assert history[0] == snapshot
        
        # Test with limit
        limited_history = position_tracker.get_pnl_history(limit=0)
        assert len(limited_history) == 0  # Should return empty list when limit is 0
    
    @pytest.mark.asyncio
    async def test_check_exit_conditions_stop_loss_long(self, position_tracker):
        """Test stop loss trigger for long position"""
        # Create position with stop loss
        position = Position(
            position_id="POS_SL",
            symbol="EUR/USD",
            direction=Direction.LONG,
            quantity=10000.0,
            entry_price=1.0850,
            current_price=1.0800,  # Below stop loss
            unrealized_pnl=(1.0800 - 1.0850) * 10000.0,  # Correct calculation
            stop_loss=1.0820,
            take_profit=1.0900,
            opened_at=datetime.now(timezone.utc)
        )
        
        # This is a private method, so we test it indirectly
        await position_tracker._check_exit_conditions(position)
        
        # Check that event was recorded
        assert len(position_tracker.position_history) > 0
        last_event = position_tracker.position_history[-1]
        assert last_event['event_type'] == 'TRIGGER_STOP_LOSS'
    
    @pytest.mark.asyncio
    async def test_check_exit_conditions_take_profit_short(self, position_tracker):
        """Test take profit trigger for short position"""
        # Create short position with take profit
        position = Position(
            position_id="POS_TP",
            symbol="EUR/USD",
            direction=Direction.SHORT,
            quantity=10000.0,
            entry_price=1.0850,
            current_price=1.0820,  # Below take profit for short
            unrealized_pnl=(1.0850 - 1.0820) * 10000.0,  # Correct calculation
            stop_loss=1.0880,
            take_profit=1.0830,
            opened_at=datetime.now(timezone.utc)
        )
        
        await position_tracker._check_exit_conditions(position)
        
        # Check that event was recorded
        assert len(position_tracker.position_history) > 0
        last_event = position_tracker.position_history[-1]
        assert last_event['event_type'] == 'TRIGGER_TAKE_PROFIT'


if __name__ == "__main__":
    pytest.main([__file__])
"""Unit tests for ExecutionEngine"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from src.trading.execution_engine import ExecutionEngine
from src.data.mock_broker import MockBrokerInterface
from src.models import (
    Order, OrderType, OrderStatus, Direction, MarketData, Portfolio, Position,
    ExecutionResult
)
from src.exceptions import TradeExecutionError, BrokerAPIError, DataValidationError
from src.config import BrokerConfig


@pytest.fixture
def mock_broker():
    """Create mock broker interface"""
    broker = MockBrokerInterface()
    return broker


@pytest.fixture
def broker_config():
    """Create broker configuration"""
    return BrokerConfig(
        broker_name="test_broker",
        api_key="test_key",
        api_secret="test_secret",
        base_url="https://api.test.com",
        timeout=30
    )


@pytest.fixture
def execution_engine(mock_broker, broker_config):
    """Create execution engine with mock broker"""
    return ExecutionEngine(mock_broker, broker_config)


@pytest.fixture
def sample_market_order():
    """Create sample market order"""
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
def sample_limit_order():
    """Create sample limit order"""
    return Order(
        order_id="ORDER_002",
        symbol="GBP/USD",
        order_type=OrderType.LIMIT,
        direction=Direction.SHORT,
        quantity=5000.0,
        price=1.2600,
        stop_loss=1.2700,
        take_profit=1.2500,
        status=OrderStatus.PENDING,
        created_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_market_data():
    """Create sample market data"""
    return MarketData(
        symbol="EUR/USD",
        timestamp=datetime.now(timezone.utc),
        open=1.0850,
        high=1.0860,
        low=1.0840,
        close=1.0855,
        volume=1000,
        bid=1.0854,
        ask=1.0856,
        spread=0.0002
    )


class TestExecutionEngine:
    """Test cases for ExecutionEngine"""
    
    @pytest.mark.asyncio
    async def test_initialization(self, mock_broker, broker_config):
        """Test execution engine initialization"""
        engine = ExecutionEngine(mock_broker, broker_config)
        
        assert engine.broker == mock_broker
        assert engine.config == broker_config
        assert engine.execution_metrics['total_executions'] == 0
        assert engine.execution_metrics['successful_executions'] == 0
        assert engine.execution_metrics['failed_executions'] == 0
    
    @pytest.mark.asyncio
    async def test_execute_market_order_long_success(self, execution_engine, sample_market_order, mock_broker):
        """Test successful execution of long market order"""
        # Setup
        await mock_broker.connect()
        
        # Execute
        result = await execution_engine.execute_trade(sample_market_order)
        
        # Verify
        assert result.success is True
        assert result.order_id == sample_market_order.order_id
        assert result.executed_price is not None
        assert result.executed_quantity == sample_market_order.quantity
        assert result.error_message is None
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['total_executions'] == 1
        assert metrics['successful_executions'] == 1
        assert metrics['failed_executions'] == 0
    
    @pytest.mark.asyncio
    async def test_execute_market_order_short_success(self, execution_engine, mock_broker):
        """Test successful execution of short market order"""
        # Setup
        await mock_broker.connect()
        
        order = Order(
            order_id="ORDER_SHORT",
            symbol="EUR/USD",
            order_type=OrderType.MARKET,
            direction=Direction.SHORT,
            quantity=10000.0,
            price=None,
            stop_loss=1.0900,
            take_profit=1.0800,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
        
        # Execute
        result = await execution_engine.execute_trade(order)
        
        # Verify
        assert result.success is True
        assert result.order_id == order.order_id
        assert result.executed_price is not None
        assert result.executed_quantity == order.quantity
    
    @pytest.mark.asyncio
    async def test_execute_limit_order_fillable(self, execution_engine, sample_limit_order, mock_broker):
        """Test execution of fillable limit order"""
        # Setup
        await mock_broker.connect()
        
        # Create limit order that can be filled
        order = Order(
            order_id="LIMIT_FILLABLE",
            symbol="EUR/USD",
            order_type=OrderType.LIMIT,
            direction=Direction.LONG,
            quantity=10000.0,
            price=1.0900,  # High limit price that should be fillable
            stop_loss=1.0800,
            take_profit=1.0950,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
        
        # Execute
        result = await execution_engine.execute_trade(order)
        
        # Verify
        assert result.success is True
        assert result.executed_price is not None
        assert result.executed_price <= order.price  # Should get better or equal price
    
    @pytest.mark.asyncio
    async def test_execute_limit_order_not_fillable(self, execution_engine, mock_broker):
        """Test execution of non-fillable limit order"""
        # Setup
        await mock_broker.connect()
        
        # Create limit order that cannot be filled
        order = Order(
            order_id="LIMIT_NOT_FILLABLE",
            symbol="EUR/USD",
            order_type=OrderType.LIMIT,
            direction=Direction.LONG,
            quantity=10000.0,
            price=1.0700,  # Very low limit price that won't be fillable
            stop_loss=1.0650,
            take_profit=1.0750,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
        
        # Execute
        result = await execution_engine.execute_trade(order)
        
        # Verify
        assert result.success is False
        assert result.executed_price is None
        assert result.executed_quantity is None
        assert "cannot be filled" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_execute_order_invalid_status(self, execution_engine, sample_market_order):
        """Test execution of order with invalid status"""
        # Setup - change order status to filled
        sample_market_order.status = OrderStatus.FILLED
        
        # Execute
        result = await execution_engine.execute_trade(sample_market_order)
        
        # Verify
        assert result.success is False
        assert "not in pending status" in result.error_message.lower()
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['failed_executions'] == 1
    
    @pytest.mark.asyncio
    async def test_execute_order_insufficient_margin(self, execution_engine, sample_market_order, mock_broker):
        """Test execution with insufficient margin"""
        # Setup
        await mock_broker.connect()
        
        # Mock broker to return insufficient margin
        mock_portfolio = Portfolio(
            account_id="TEST_ACCOUNT",
            balance=1000.0,
            equity=1000.0,
            margin_used=999.0,
            margin_available=1.0,  # Very low available margin
            positions=[],
            updated_at=datetime.now(timezone.utc)
        )
        
        with patch.object(mock_broker, 'get_account_info', return_value=mock_portfolio):
            # Execute
            result = await execution_engine.execute_trade(sample_market_order)
            
            # Verify
            assert result.success is False
            assert "insufficient margin" in result.error_message.lower()
    
    @pytest.mark.asyncio
    async def test_execute_order_broker_error(self, execution_engine, sample_market_order, mock_broker):
        """Test execution with broker API error"""
        # Setup
        await mock_broker.connect()
        
        # Mock broker to raise error
        with patch.object(mock_broker, 'get_market_data', side_effect=BrokerAPIError("API Error")):
            # Execute
            result = await execution_engine.execute_trade(sample_market_order)
            
            # Verify
            assert result.success is False
            assert "API Error" in result.error_message
    
    @pytest.mark.asyncio
    async def test_modify_order_success(self, execution_engine):
        """Test successful order modification"""
        modifications = {
            'price': 1.0850,
            'quantity': 15000.0,
            'stop_loss': 1.0800
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_modify_order_invalid_keys(self, execution_engine):
        """Test order modification with invalid keys"""
        modifications = {
            'invalid_key': 123,
            'price': 1.0850
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_modify_order_invalid_values(self, execution_engine):
        """Test order modification with invalid values"""
        modifications = {
            'price': -1.0850,  # Negative price
            'quantity': 15000.0
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_cancel_order_success(self, execution_engine):
        """Test successful order cancellation"""
        result = await execution_engine.cancel_order("ORDER_001")
        
        assert result is True
    
    def test_calculate_slippage_factor(self, execution_engine, sample_market_data):
        """Test slippage factor calculation"""
        # Test with small order
        small_slippage = execution_engine._calculate_slippage_factor(1000.0, sample_market_data)
        
        # Test with large order
        large_slippage = execution_engine._calculate_slippage_factor(100000.0, sample_market_data)
        
        # Large orders should have higher slippage
        assert large_slippage > small_slippage
        assert small_slippage > 0
        assert large_slippage <= 0.001  # Should be capped
    
    @pytest.mark.asyncio
    async def test_execution_metrics_tracking(self, execution_engine, sample_market_order, mock_broker):
        """Test execution metrics tracking"""
        # Setup
        await mock_broker.connect()
        
        # Execute successful order
        await execution_engine.execute_trade(sample_market_order)
        
        # Execute failed order
        sample_market_order.status = OrderStatus.FILLED  # Invalid status
        await execution_engine.execute_trade(sample_market_order)
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['total_executions'] == 2
        assert metrics['successful_executions'] == 1
        assert metrics['failed_executions'] == 1
        assert metrics['average_slippage'] >= 0
    
    def test_reset_metrics(self, execution_engine):
        """Test metrics reset functionality"""
        # Modify metrics
        execution_engine.execution_metrics['total_executions'] = 10
        execution_engine.execution_metrics['successful_executions'] = 8
        
        # Reset
        execution_engine.reset_metrics()
        
        # Verify reset
        metrics = execution_engine.get_execution_metrics()
        assert metrics['total_executions'] == 0
        assert metrics['successful_executions'] == 0
        assert metrics['failed_executions'] == 0
    
    @pytest.mark.asyncio
    async def test_limit_order_missing_price(self, execution_engine, mock_broker):
        """Test limit order creation without price (should fail at model validation)"""
        # Setup
        await mock_broker.connect()
        
        # Creating a limit order without price should raise DataValidationError
        with pytest.raises(DataValidationError, match="Limit orders must have a positive price"):
            Order(
                order_id="LIMIT_NO_PRICE",
                symbol="EUR/USD",
                order_type=OrderType.LIMIT,
                direction=Direction.LONG,
                quantity=10000.0,
                price=None,  # Missing price for limit order
                stop_loss=1.0800,
                take_profit=1.0900,
                status=OrderStatus.PENDING,
                created_at=datetime.now(timezone.utc)
            )
    
    @pytest.mark.asyncio
    async def test_unsupported_order_type(self, execution_engine, mock_broker):
        """Test execution with unsupported order type"""
        # Setup
        await mock_broker.connect()
        
        order = Order(
            order_id="STOP_ORDER",
            symbol="EUR/USD",
            order_type=OrderType.STOP,  # Not implemented in execution engine
            direction=Direction.LONG,
            quantity=10000.0,
            price=1.0850,
            stop_loss=1.0800,
            take_profit=1.0900,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
        
        # Execute
        result = await execution_engine.execute_trade(order)
        
        # Verify
        assert result.success is False
        assert "unsupported order type" in result.error_message.lower()


if __name__ == "__main__":
    pytest.main([__file__])
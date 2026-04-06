"""Unit tests for order modification and error handling in ExecutionEngine"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import Mock, AsyncMock, patch

from src.trading.execution_engine import ExecutionEngine
from src.data.mock_broker import MockBrokerInterface
from src.models import (
    Order, OrderType, OrderStatus, Direction, MarketData, ExecutionResult
)
from src.exceptions import TradeExecutionError, BrokerAPIError
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
def sample_order():
    """Create sample order for testing"""
    return Order(
        order_id="ORDER_001",
        symbol="EUR/USD",
        order_type=OrderType.MARKET,
        direction=Direction.LONG,
        quantity=10000.0,
        price=None,  # Market orders don't need a price
        stop_loss=1.0800,
        take_profit=1.0900,
        status=OrderStatus.PENDING,
        created_at=datetime.now(timezone.utc)
    )


class TestOrderModification:
    """Test cases for order modification functionality"""
    
    @pytest.mark.asyncio
    async def test_modify_order_success(self, execution_engine):
        """Test successful order modification"""
        modifications = {
            'price': 1.0860,
            'quantity': 15000.0,
            'stop_loss': 1.0810
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is True
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['modification_attempts'] == 1
        assert metrics['successful_modifications'] == 1
        assert metrics['failed_modifications'] == 0
    
    @pytest.mark.asyncio
    async def test_modify_order_invalid_key(self, execution_engine):
        """Test order modification with invalid key"""
        modifications = {
            'invalid_key': 123,
            'price': 1.0850
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is False
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['modification_attempts'] == 1
        assert metrics['successful_modifications'] == 0
        assert metrics['failed_modifications'] == 1
    
    @pytest.mark.asyncio
    async def test_modify_order_invalid_price(self, execution_engine):
        """Test order modification with invalid price"""
        modifications = {
            'price': -1.0850,  # Negative price
            'quantity': 15000.0
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is False
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['failed_modifications'] == 1
    
    @pytest.mark.asyncio
    async def test_modify_order_invalid_quantity(self, execution_engine):
        """Test order modification with invalid quantity"""
        modifications = {
            'quantity': -5000.0,  # Negative quantity
            'price': 1.0850
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_modify_order_invalid_order_type(self, execution_engine):
        """Test order modification with invalid order type"""
        modifications = {
            'order_type': 'INVALID_TYPE',
            'price': 1.0850
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_modify_order_valid_order_type(self, execution_engine):
        """Test order modification with valid order type"""
        modifications = {
            'order_type': OrderType.MARKET,
            'quantity': 15000.0
        }
        
        result = await execution_engine.modify_order("ORDER_001", modifications)
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_modify_order_broker_failure(self, execution_engine):
        """Test order modification with broker API failure"""
        modifications = {
            'price': 1.0860,
            'quantity': 15000.0
        }
        
        # Use order ID that triggers failure in mock
        result = await execution_engine.modify_order("ORDER_FAIL", modifications)
        
        assert result is False
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['failed_modifications'] == 1
    
    @pytest.mark.asyncio
    async def test_modification_history_tracking(self, execution_engine):
        """Test modification history tracking"""
        order_id = "ORDER_001"
        modifications = {
            'price': 1.0860,
            'quantity': 15000.0
        }
        
        # Perform modification
        await execution_engine.modify_order(order_id, modifications)
        
        # Check history
        history = execution_engine.get_modification_history(order_id)
        assert len(history) == 1
        assert history[0]['modifications'] == modifications
        assert history[0]['status'] in ['attempted', 'verified']
        assert 'timestamp' in history[0]
    
    @pytest.mark.asyncio
    async def test_multiple_modifications_same_order(self, execution_engine):
        """Test multiple modifications on same order"""
        order_id = "ORDER_001"
        
        # First modification
        modifications1 = {'price': 1.0860}
        await execution_engine.modify_order(order_id, modifications1)
        
        # Second modification
        modifications2 = {'quantity': 15000.0}
        await execution_engine.modify_order(order_id, modifications2)
        
        # Check history
        history = execution_engine.get_modification_history(order_id)
        assert len(history) == 2
        assert history[0]['modifications'] == modifications1
        assert history[1]['modifications'] == modifications2


class TestOrderCancellation:
    """Test cases for order cancellation with error handling"""
    
    @pytest.mark.asyncio
    async def test_cancel_order_success(self, execution_engine, sample_order):
        """Test successful order cancellation"""
        # Add order to tracking
        execution_engine.pending_orders[sample_order.order_id] = sample_order
        
        result = await execution_engine.cancel_order(sample_order.order_id)
        
        assert result is True
        # Order should be removed from tracking
        assert sample_order.order_id not in execution_engine.pending_orders
    
    @pytest.mark.asyncio
    async def test_cancel_order_broker_failure(self, execution_engine):
        """Test order cancellation with broker failure"""
        order_id = "ORDER_FAIL"
        execution_engine.pending_orders[order_id] = Mock()
        
        result = await execution_engine.cancel_order(order_id)
        
        assert result is False
        # Order should still be in tracking since cancellation failed
        assert order_id in execution_engine.pending_orders
    
    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order(self, execution_engine):
        """Test cancellation of non-existent order"""
        result = await execution_engine.cancel_order("NONEXISTENT")
        
        # Should still return True for idempotency
        assert result is True
    
    @pytest.mark.asyncio
    async def test_emergency_cancel_all_orders(self, execution_engine):
        """Test emergency cancellation of all orders"""
        # Add multiple orders to tracking
        orders = {
            "ORDER_001": Mock(),
            "ORDER_002": Mock(),
            "ORDER_FAIL": Mock()  # This one will fail
        }
        execution_engine.pending_orders.update(orders)
        
        results = await execution_engine.emergency_cancel_all_orders()
        
        assert len(results) == 3
        assert results["ORDER_001"] is True
        assert results["ORDER_002"] is True
        assert results["ORDER_FAIL"] is False
        
        # Only failed order should remain in tracking
        assert "ORDER_FAIL" in execution_engine.pending_orders
        assert "ORDER_001" not in execution_engine.pending_orders
        assert "ORDER_002" not in execution_engine.pending_orders


class TestOrderReconciliation:
    """Test cases for order reconciliation functionality"""
    
    @pytest.mark.asyncio
    async def test_reconcile_single_order(self, execution_engine, sample_order):
        """Test reconciliation of single order"""
        # Add order to tracking
        execution_engine.pending_orders[sample_order.order_id] = sample_order
        
        # This should not raise an exception
        await execution_engine._reconcile_order_state(sample_order.order_id)
    
    @pytest.mark.asyncio
    async def test_reconcile_all_orders(self, execution_engine):
        """Test reconciliation of all orders"""
        # Add multiple orders to tracking
        orders = {
            "ORDER_001": Mock(),
            "ORDER_002": Mock(),
            "ORDER_003": Mock()
        }
        execution_engine.pending_orders.update(orders)
        
        results = await execution_engine.reconcile_all_orders()
        
        assert results['total_orders'] == 3
        assert results['reconciled'] == 3
        assert results['errors'] == 0
        assert len(results['discrepancies']) == 0
    
    @pytest.mark.asyncio
    async def test_reconcile_with_errors(self, execution_engine):
        """Test reconciliation with some errors"""
        # Add orders to tracking
        execution_engine.pending_orders["ORDER_001"] = Mock()
        
        # Mock reconciliation to raise error
        with patch.object(
            execution_engine, 
            '_reconcile_order_state', 
            side_effect=Exception("Reconciliation error")
        ):
            results = await execution_engine.reconcile_all_orders()
            
            assert results['total_orders'] == 1
            assert results['reconciled'] == 0
            assert results['errors'] == 1
            assert len(results['discrepancies']) == 1
            assert results['discrepancies'][0]['order_id'] == "ORDER_001"


class TestErrorHandling:
    """Test cases for comprehensive error handling"""
    
    @pytest.mark.asyncio
    async def test_validation_error_handling(self, execution_engine):
        """Test handling of validation errors"""
        # Test with empty modifications
        result = await execution_engine.modify_order("ORDER_001", {})
        assert result is True  # Empty modifications should be allowed
        
        # Test with None modifications
        with pytest.raises(AttributeError):
            await execution_engine.modify_order("ORDER_001", None)
    
    @pytest.mark.asyncio
    async def test_broker_api_error_retry(self, execution_engine):
        """Test retry logic for broker API errors"""
        modifications = {'price': 1.0860}
        
        # Mock broker method to fail first time, succeed second time
        call_count = 0
        
        async def mock_broker_modify(order_id, mods):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise BrokerAPIError("Temporary failure")
            return True
        
        with patch.object(
            execution_engine, 
            '_broker_modify_order', 
            side_effect=mock_broker_modify
        ):
            result = await execution_engine.modify_order("ORDER_001", modifications)
            
            assert result is True
            assert call_count == 2  # Should have retried once
    
    @pytest.mark.asyncio
    async def test_modification_error_reconciliation(self, execution_engine):
        """Test reconciliation after modification error"""
        modifications = {'price': 1.0860}
        
        # Mock modification to fail
        with patch.object(
            execution_engine, 
            '_execute_order_modification', 
            return_value=False
        ):
            # Mock reconciliation
            reconcile_mock = AsyncMock()
            with patch.object(
                execution_engine, 
                '_reconcile_order_state', 
                reconcile_mock
            ):
                result = await execution_engine.modify_order("ORDER_001", modifications)
                
                assert result is False
                # Should have attempted reconciliation
                reconcile_mock.assert_called_once_with("ORDER_001")
    
    @pytest.mark.asyncio
    async def test_metrics_tracking_with_errors(self, execution_engine):
        """Test metrics tracking with various error scenarios"""
        # Reset metrics
        execution_engine.reset_metrics()
        
        # Successful modification
        await execution_engine.modify_order("ORDER_001", {'price': 1.0860})
        
        # Failed modification (invalid key)
        await execution_engine.modify_order("ORDER_002", {'invalid': 123})
        
        # Failed modification (broker error)
        await execution_engine.modify_order("ORDER_FAIL", {'price': 1.0870})
        
        metrics = execution_engine.get_execution_metrics()
        assert metrics['modification_attempts'] == 3
        assert metrics['successful_modifications'] == 1
        assert metrics['failed_modifications'] == 2
    
    def test_get_pending_orders(self, execution_engine, sample_order):
        """Test getting pending orders"""
        # Add order to tracking
        execution_engine.pending_orders[sample_order.order_id] = sample_order
        
        pending = execution_engine.get_pending_orders()
        
        assert len(pending) == 1
        assert sample_order.order_id in pending
        assert pending[sample_order.order_id] == sample_order
        
        # Should return a copy, not the original
        assert pending is not execution_engine.pending_orders
    
    def test_modification_history_empty(self, execution_engine):
        """Test getting modification history for order with no modifications"""
        history = execution_engine.get_modification_history("NONEXISTENT")
        assert history == []


class TestIntegrationScenarios:
    """Integration test scenarios combining multiple features"""
    
    @pytest.mark.asyncio
    async def test_execute_modify_cancel_workflow(self, execution_engine, mock_broker, sample_order):
        """Test complete workflow: execute -> modify -> cancel"""
        # Setup
        await mock_broker.connect()
        
        # Execute order
        result = await execution_engine.execute_trade(sample_order)
        assert result.success is True
        assert sample_order.order_id in execution_engine.pending_orders
        
        # Modify order
        modifications = {'price': 1.0870, 'quantity': 15000.0}
        modify_result = await execution_engine.modify_order(
            sample_order.order_id, modifications
        )
        assert modify_result is True
        
        # Check modification history
        history = execution_engine.get_modification_history(sample_order.order_id)
        assert len(history) == 1
        
        # Cancel order
        cancel_result = await execution_engine.cancel_order(sample_order.order_id)
        assert cancel_result is True
        assert sample_order.order_id not in execution_engine.pending_orders
    
    @pytest.mark.asyncio
    async def test_multiple_orders_with_mixed_operations(self, execution_engine, mock_broker):
        """Test handling multiple orders with mixed success/failure"""
        await mock_broker.connect()
        
        # Create multiple orders
        orders = []
        for i in range(3):
            order = Order(
                order_id=f"ORDER_{i:03d}",
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
            orders.append(order)
        
        # Execute all orders
        for order in orders:
            result = await execution_engine.execute_trade(order)
            assert result.success is True
        
        # Modify some orders (mix of success and failure)
        await execution_engine.modify_order("ORDER_000", {'price': 1.0860})  # Success
        await execution_engine.modify_order("ORDER_001", {'invalid': 123})   # Failure
        await execution_engine.modify_order("ORDER_002", {'quantity': 15000}) # Success
        
        # Check metrics
        metrics = execution_engine.get_execution_metrics()
        assert metrics['total_executions'] == 3
        assert metrics['successful_executions'] == 3
        assert metrics['modification_attempts'] == 3
        assert metrics['successful_modifications'] == 2
        assert metrics['failed_modifications'] == 1
        
        # Reconcile all orders
        reconcile_results = await execution_engine.reconcile_all_orders()
        assert reconcile_results['total_orders'] == 3
        assert reconcile_results['reconciled'] == 3
        assert reconcile_results['errors'] == 0


if __name__ == "__main__":
    pytest.main([__file__])
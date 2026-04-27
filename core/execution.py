"""
Execution module for order submission and management.
Broker-agnostic interface supporting MT5, OANDA, and other brokers.
"""

from dataclasses import dataclass
from typing import Dict, Optional, List
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from utils.logger import get_logger


logger = get_logger(__name__)


class OrderType(str, Enum):
    """Order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"


class OrderStatus(str, Enum):
    """Order statuses."""
    PENDING = "pending"
    OPEN = "open"
    FILLED = "filled"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


@dataclass
class OrderRequest:
    """Order request parameters."""
    symbol: str
    order_type: OrderType
    direction: str  # BUY or SELL
    quantity: float
    price: Optional[float] = None  # For limit orders
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    comment: str = ""


@dataclass
class Order:
    """Order representation."""
    order_id: str
    symbol: str
    direction: str
    quantity: float
    order_type: OrderType
    status: OrderStatus
    
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    
    comment: str = ""
    
    def __hash__(self):
        return hash(self.order_id)
    
    def __eq__(self, other):
        if isinstance(other, Order):
            return self.order_id == other.order_id
        return False


class Broker(ABC):
    """Abstract broker interface."""
    
    @abstractmethod
    async def connect(self) -> bool:
        """Connect to broker."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> bool:
        """Disconnect from broker."""
        pass
    
    @abstractmethod
    async def submit_order(self, request: OrderRequest) -> Optional[str]:
        """Submit order and return order ID."""
        pass
    
    @abstractmethod
    async def modify_order(self, order_id: str, stop_loss: float, take_profit: float) -> bool:
        """Modify stop loss and take profit."""
        pass
    
    @abstractmethod
    async def close_order(self, order_id: str) -> bool:
        """Close/cancel an order."""
        pass
    
    @abstractmethod
    async def get_account_info(self) -> Dict:
        """Get account information."""
        pass
    
    @abstractmethod
    async def get_positions(self) -> List[Order]:
        """Get all open positions."""
        pass
    
    @abstractmethod
    async def get_order_info(self, order_id: str) -> Optional[Order]:
        """Get specific order information."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check connection status."""
        pass


class ExecutionEngine:
    """
    Order execution engine.
    Handles order submissions, modifications, and market impact.
    """
    
    def __init__(self, broker: Broker):
        """
        Initialize ExecutionEngine.
        
        Args:
            broker: Broker instance (MT5, OANDA, etc.)
        """
        self.broker = broker
        self.pending_orders: Dict[str, Order] = {}
        self.executed_orders: List[Order] = []
        self.failed_orders: List[Order] = []
    
    async def submit_market_order(self, symbol: str, direction: str, quantity: float,
                                 stop_loss: float, take_profit: float,
                                 comment: str = "") -> Optional[str]:
        """
        Submit a market order.
        
        Args:
            symbol: Trading symbol
            direction: BUY or SELL
            quantity: Order quantity
            stop_loss: Stop loss price
            take_profit: Take profit price
            comment: Order comment
        
        Returns:
            Order ID if successful, None otherwise
        """
        request = OrderRequest(
            symbol=symbol,
            order_type=OrderType.MARKET,
            direction=direction,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            comment=comment
        )
        
        try:
            order_id = await self.broker.submit_order(request)
            
            if order_id:
                order = Order(
                    order_id=order_id,
                    symbol=symbol,
                    direction=direction,
                    quantity=quantity,
                    order_type=OrderType.MARKET,
                    status=OrderStatus.PENDING,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    submitted_at=datetime.now(),
                    comment=comment
                )
                
                self.pending_orders[order_id] = order
                logger.info("Market order submitted",
                           order_id=order_id,
                           symbol=symbol,
                           direction=direction,
                           quantity=quantity)
                
                return order_id
            
            else:
                logger.error("Failed to submit market order",
                           symbol=symbol,
                           direction=direction)
                return None
        
        except Exception as e:
            logger.error(f"Error submitting market order: {e}",
                        symbol=symbol,
                        direction=direction)
            return None
    
    async def modify_order(self, order_id: str, stop_loss: float, take_profit: float) -> bool:
        """
        Modify stop loss and take profit for an order.
        
        Args:
            order_id: Order ID to modify
            stop_loss: New stop loss price
            take_profit: New take profit price
        
        Returns:
            True if successful
        """
        try:
            if await self.broker.modify_order(order_id, stop_loss, take_profit):
                
                if order_id in self.pending_orders:
                    self.pending_orders[order_id].stop_loss = stop_loss
                    self.pending_orders[order_id].take_profit = take_profit
                
                logger.info("Order modified",
                           order_id=order_id,
                           stop_loss=stop_loss,
                           take_profit=take_profit)
                
                return True
            
            else:
                logger.error("Failed to modify order", order_id=order_id)
                return False
        
        except Exception as e:
            logger.error(f"Error modifying order: {e}", order_id=order_id)
            return False
    
    async def close_position(self, order_id: str) -> bool:
        """
        Close a position.
        
        Args:
            order_id: Order ID to close
        
        Returns:
            True if successful
        """
        try:
            if await self.broker.close_order(order_id):
                
                if order_id in self.pending_orders:
                    order = self.pending_orders.pop(order_id)
                    order.status = OrderStatus.CLOSED
                    order.closed_at = datetime.now()
                    self.executed_orders.append(order)
                
                logger.info("Position closed", order_id=order_id)
                return True
            
            else:
                logger.error("Failed to close position", order_id=order_id)
                return False
        
        except Exception as e:
            logger.error(f"Error closing position: {e}", order_id=order_id)
            return False
    
    async def sync_orders(self):
        """Synchronize order status with broker."""
        try:
            open_positions = await self.broker.get_positions()
            
            # Update pending orders
            for order_id in list(self.pending_orders.keys()):
                info = await self.broker.get_order_info(order_id)
                
                if info:
                    self.pending_orders[order_id] = info
                else:
                    # Order might be closed
                    order = self.pending_orders.pop(order_id)
                    order.status = OrderStatus.CLOSED
                    self.executed_orders.append(order)
        
        except Exception as e:
            logger.error(f"Error syncing orders: {e}")
    
    def get_pending_orders(self) -> List[Order]:
        """Get all pending orders."""
        return list(self.pending_orders.values())
    
    def get_executed_orders(self) -> List[Order]:
        """Get all executed orders."""
        return self.executed_orders
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get specific order."""
        return self.pending_orders.get(order_id)


class MockBroker(Broker):
    """Mock broker for testing without real connection."""
    
    def __init__(self):
        """Initialize mock broker."""
        self.connected = False
        self.orders: Dict[str, Order] = {}
        self.account_balance = 10000.0
        self.next_order_id = 1
    
    async def connect(self) -> bool:
        """Connect to mock broker."""
        self.connected = True
        logger.info("Connected to mock broker")
        return True
    
    async def disconnect(self) -> bool:
        """Disconnect from mock broker."""
        self.connected = False
        logger.info("Disconnected from mock broker")
        return True
    
    async def submit_order(self, request: OrderRequest) -> Optional[str]:
        """Submit order to mock broker."""
        order_id = f"MOCK_ORDER_{self.next_order_id}"
        self.next_order_id += 1
        
        order = Order(
            order_id=order_id,
            symbol=request.symbol,
            direction=request.direction,
            quantity=request.quantity,
            order_type=request.order_type,
            status=OrderStatus.FILLED,
            entry_price=100.0,  # Mock price
            stop_loss=request.stop_loss,
            take_profit=request.take_profit,
            submitted_at=datetime.now(),
            filled_at=datetime.now(),
            comment=request.comment
        )
        
        self.orders[order_id] = order
        return order_id
    
    async def modify_order(self, order_id: str, stop_loss: float, take_profit: float) -> bool:
        """Modify order in mock broker."""
        if order_id in self.orders:
            self.orders[order_id].stop_loss = stop_loss
            self.orders[order_id].take_profit = take_profit
            return True
        return False
    
    async def close_order(self, order_id: str) -> bool:
        """Close order in mock broker."""
        if order_id in self.orders:
            self.orders[order_id].status = OrderStatus.CLOSED
            self.orders[order_id].closed_at = datetime.now()
            return True
        return False
    
    async def get_account_info(self) -> Dict:
        """Get account info from mock broker."""
        return {
            'balance': self.account_balance,
            'equity': self.account_balance,
            'used_margin': 0.0,
            'free_margin': self.account_balance
        }
    
    async def get_positions(self) -> List[Order]:
        """Get positions from mock broker."""
        return [o for o in self.orders.values() if o.status == OrderStatus.FILLED]
    
    async def get_order_info(self, order_id: str) -> Optional[Order]:
        """Get order info from mock broker."""
        return self.orders.get(order_id)
    
    def is_connected(self) -> bool:
        """Check if mock broker is connected."""
        return self.connected

"""Mock broker interface for testing and development"""

import asyncio
import random
from datetime import datetime, timezone
from typing import Dict, Any
from src.interfaces import BrokerInterface
from src.models import MarketData, Portfolio, Position, Direction, OrderStatus
from src.exceptions import BrokerAPIError


class MockBrokerInterface(BrokerInterface):
    """Mock broker interface for testing"""
    
    def __init__(self):
        self.connected = False
        self.account_balance = 10000.0
        self.positions = []
        
        # Mock price data for major pairs
        self.base_prices = {
            'EUR/USD': 1.0850,
            'GBP/USD': 1.2650,
            'USD/JPY': 149.50,
            'USD/CHF': 0.8950,
            'AUD/USD': 0.6750,
            'USD/CAD': 1.3650,
            'NZD/USD': 0.6150
        }
    
    async def connect(self) -> bool:
        """Connect to mock broker"""
        await asyncio.sleep(0.1)  # Simulate connection delay
        self.connected = True
        return True
    
    async def disconnect(self) -> bool:
        """Disconnect from mock broker"""
        await asyncio.sleep(0.1)  # Simulate disconnection delay
        self.connected = False
        return True
    
    async def get_account_info(self) -> Portfolio:
        """Get mock account information"""
        if not self.connected:
            raise BrokerAPIError(
                "Not connected to broker",
                error_code="NOT_CONNECTED"
            )
        
        # Calculate equity based on positions
        equity = self.account_balance
        margin_used = 0.0
        
        for position in self.positions:
            equity += position.unrealized_pnl
            margin_used += position.quantity * position.entry_price * 0.01  # 1% margin
        
        margin_available = equity - margin_used
        
        return Portfolio(
            account_id="MOCK_ACCOUNT_123",
            balance=self.account_balance,
            equity=equity,
            margin_used=margin_used,
            margin_available=margin_available,
            positions=self.positions.copy(),
            updated_at=datetime.now(timezone.utc)
        )
    
    async def get_market_data(self, symbol: str) -> MarketData:
        """Get mock market data"""
        if not self.connected:
            raise BrokerAPIError(
                "Not connected to broker",
                error_code="NOT_CONNECTED"
            )
        
        if symbol not in self.base_prices:
            raise BrokerAPIError(
                f"Unsupported symbol: {symbol}",
                error_code="UNSUPPORTED_SYMBOL",
                context={"symbol": symbol}
            )
        
        # Generate realistic mock data with small random variations
        base_price = self.base_prices[symbol]
        
        # Add small random variation (±0.1%)
        variation = random.uniform(-0.001, 0.001)
        current_price = base_price * (1 + variation)
        
        # Generate OHLC data
        high = current_price * random.uniform(1.0001, 1.002)
        low = current_price * random.uniform(0.998, 0.9999)
        open_price = random.uniform(low, high)
        close_price = current_price
        
        # Generate bid/ask with realistic spread
        spread_raw = base_price * random.uniform(0.00001, 0.0001)  # 0.1-10 pips
        bid = current_price - spread_raw / 2
        ask = current_price + spread_raw / 2
        
        # Round to 5 decimal places to avoid floating point precision issues
        bid = round(bid, 5)
        ask = round(ask, 5)
        
        # Calculate exact spread after rounding
        spread = round(ask - bid, 5)
        
        # Generate volume
        volume = random.randint(1000, 10000)
        
        return MarketData(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            open=round(open_price, 5),
            high=round(high, 5),
            low=round(low, 5),
            close=round(close_price, 5),
            volume=volume,
            bid=bid,
            ask=ask,
            spread=spread
        )
    
    def add_position(self, symbol: str, direction: Direction, quantity: float, entry_price: float) -> str:
        """Add a mock position for testing"""
        position_id = f"POS_{len(self.positions) + 1:03d}"
        
        position = Position(
            position_id=position_id,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            current_price=entry_price,
            unrealized_pnl=0.0,
            stop_loss=None,
            take_profit=None,
            opened_at=datetime.now(timezone.utc)
        )
        
        self.positions.append(position)
        return position_id
    
    def update_position_prices(self) -> None:
        """Update position prices with current market data"""
        for position in self.positions:
            if position.symbol in self.base_prices:
                # Add small random variation
                base_price = self.base_prices[position.symbol]
                variation = random.uniform(-0.001, 0.001)
                new_price = base_price * (1 + variation)
                position.update_current_price(round(new_price, 5))
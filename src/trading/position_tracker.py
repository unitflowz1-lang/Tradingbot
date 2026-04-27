"""Position tracker for real-time position and P&L monitoring"""

import asyncio
import logging
from datetime import datetime, timezone
import time
from typing import Dict, List, Optional, Callable
from src.interfaces import BrokerInterface
from src.models import Position, Portfolio, MarketData, Direction, ExecutionResult, Order
from src.exceptions import BrokerAPIError, DataValidationError


class PositionTracker:
    """Real-time position and P&L monitoring system"""
    
    def __init__(self, broker: BrokerInterface, update_interval: float = 1.0):
        """Initialize position tracker
        
        Args:
            broker: Broker interface for market data
            update_interval: Seconds between position updates
        """
        self.broker = broker
        self.update_interval = update_interval
        self.logger = logging.getLogger(__name__)
        
        # Position tracking data
        self.positions: Dict[str, Position] = {}
        self.position_history: List[Dict] = []
        self.pnl_history: List[Dict] = []
        
        # Position ID counter to ensure uniqueness
        self.position_counter = 0
        
        # Monitoring state
        self.is_monitoring = False
        self.monitoring_task: Optional[asyncio.Task] = None
        
        # Callbacks for position events
        self.position_callbacks: List[Callable[[Position], None]] = []
        self.pnl_callbacks: List[Callable[[Dict], None]] = []
        
        # Performance metrics
        self.metrics = {
            'total_positions': 0,
            'open_positions': 0,
            'closed_positions': 0,
            'total_pnl': 0.0,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'winning_positions': 0,
            'losing_positions': 0,
            'largest_win': 0.0,
            'largest_loss': 0.0,
            'average_win': 0.0,
            'average_loss': 0.0
        }
    
    async def start_monitoring(self) -> None:
        """Start real-time position monitoring"""
        if self.is_monitoring:
            self.logger.warning("Position monitoring is already running")
            return
        
        self.logger.info("Starting position monitoring")
        self.is_monitoring = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
    
    async def verify_ticket(self, ticket_id: str) -> Optional[Position]:
        """=== FIX #3: Verify_Ticket sub-routine ===
        Query HistorySelect immediately if a ticket is missing from the active pool.
        Prevent hard resets by confirming actual ticket state with broker.
        """
        import MetaTrader5 as mt5
        
        try:
            # First check active positions
            pos = mt5.positions_get(ticket=int(ticket_id))
            if pos:
                self.logger.info(f"[VERIFY_TICKET] Ticket {ticket_id} found in active positions")
                return pos[0]
            
            # If not in active, check history
            if mt5.history_select(0, int(time.time() * 1000)):
                hist = mt5.history_deals_get(ticket=int(ticket_id))
                if hist:
                    self.logger.info(f"[VERIFY_TICKET] Ticket {ticket_id} found in history. Position closed.")
                    # Mark as closed in internal tracker
                    if ticket_id in self.positions:
                        self.positions[ticket_id].closed_at = datetime.now(timezone.utc)
                    return None
            
            # Ticket not found anywhere - truly ghost
            self.logger.warning(f"[VERIFY_TICKET] Ticket {ticket_id} NOT found in active or history")
            return None
        except Exception as e:
            self.logger.error(f"[VERIFY_TICKET] Error verifying ticket {ticket_id}: {e}")
            return None
    
    async def stop_monitoring(self) -> None:
        """Stop real-time position monitoring"""
        if not self.is_monitoring:
            self.logger.warning("Position monitoring is not running")
            return
        
        self.logger.info("Stopping position monitoring")
        self.is_monitoring = False
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
            self.monitoring_task = None
    
    async def add_position(self, execution_result: ExecutionResult, order: Order) -> str:
        """Add new position from execution result
        
        Args:
            execution_result: Result of order execution
            order: Original order that was executed
            
        Returns:
            Position ID
            
        Raises:
            DataValidationError: If execution result is invalid
        """
        if not execution_result.success:
            raise DataValidationError(
                "Cannot create position from failed execution",
                error_code="FAILED_EXECUTION",
                context={"order_id": order.order_id}
            )
        
        if execution_result.executed_price is None or execution_result.executed_quantity is None:
            raise DataValidationError(
                "Execution result missing price or quantity",
                error_code="INCOMPLETE_EXECUTION",
                context={
                    "executed_price": execution_result.executed_price,
                    "executed_quantity": execution_result.executed_quantity
                }
            )
        
        # Generate unique position ID using counter
        self.position_counter += 1
        position_id = f"POS_{order.symbol}_{self.position_counter}"
        
        # Create position
        position = Position(
            position_id=position_id,
            symbol=order.symbol,
            direction=order.direction,
            quantity=execution_result.executed_quantity,
            entry_price=execution_result.executed_price,
            current_price=execution_result.executed_price,
            unrealized_pnl=0.0,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=execution_result.timestamp
        )
        
        # Add to tracking
        self.positions[position_id] = position
        self.metrics['total_positions'] += 1
        self.metrics['open_positions'] += 1
        
        # Log position creation
        self.logger.info(
            f"Added position {position_id}: {order.symbol} "
            f"{order.direction.value} {execution_result.executed_quantity} "
            f"@ {execution_result.executed_price}"
        )
        
        # Record in history
        self._record_position_event(position, "OPENED")
        
        # Notify callbacks
        for callback in self.position_callbacks:
            try:
                callback(position)
            except Exception as e:
                self.logger.error(f"Position callback error: {e}")
        
        return position_id
    
    async def close_position(self, position_id: str, execution_result: ExecutionResult) -> float:
        """Close position and calculate realized P&L
        
        Args:
            position_id: ID of position to close
            execution_result: Result of closing order execution
            
        Returns:
            Realized P&L
            
        Raises:
            DataValidationError: If position not found or execution invalid
        """
        if position_id not in self.positions:
            raise DataValidationError(
                f"Position {position_id} not found",
                error_code="POSITION_NOT_FOUND",
                context={"position_id": position_id}
            )
        
        if not execution_result.success:
            raise DataValidationError(
                "Cannot close position with failed execution",
                error_code="FAILED_EXECUTION",
                context={"position_id": position_id}
            )
        
        position = self.positions[position_id]
        
        # Calculate realized P&L
        if execution_result.executed_price is None:
            raise DataValidationError(
                "Execution result missing price",
                error_code="MISSING_EXECUTION_PRICE",
                context={"position_id": position_id}
            )
        
        if position.direction == Direction.LONG:
            realized_pnl = (execution_result.executed_price - position.entry_price) * position.quantity
        else:  # SHORT
            realized_pnl = (position.entry_price - execution_result.executed_price) * position.quantity
        
        # Update metrics
        self.metrics['open_positions'] -= 1
        self.metrics['closed_positions'] += 1
        self.metrics['realized_pnl'] += realized_pnl
        self.metrics['total_pnl'] += realized_pnl
        
        if realized_pnl > 0:
            self.metrics['winning_positions'] += 1
            self.metrics['largest_win'] = max(self.metrics['largest_win'], realized_pnl)
            
            # Update average win
            if self.metrics['winning_positions'] > 0:
                total_wins = sum(
                    pnl for pnl in [p.get('realized_pnl', 0) for p in self.position_history]
                    if pnl > 0
                )
                self.metrics['average_win'] = total_wins / self.metrics['winning_positions']
        else:
            self.metrics['losing_positions'] += 1
            self.metrics['largest_loss'] = min(self.metrics['largest_loss'], realized_pnl)
            
            # Update average loss
            if self.metrics['losing_positions'] > 0:
                total_losses = sum(
                    pnl for pnl in [p.get('realized_pnl', 0) for p in self.position_history]
                    if pnl < 0
                )
                self.metrics['average_loss'] = total_losses / self.metrics['losing_positions']
        
        # Record in history before removing
        self._record_position_event(position, "CLOSED", {
            'close_price': execution_result.executed_price,
            'realized_pnl': realized_pnl,
            'closed_at': execution_result.timestamp
        })
        
        # Remove from active positions
        del self.positions[position_id]
        
        self.logger.info(
            f"Closed position {position_id}: "
            f"realized P&L = {realized_pnl:.2f}"
        )
        
        return realized_pnl
    
    async def update_position_prices(self) -> None:
        """Update all position prices with current market data"""
        if not self.positions:
            return
        
        # Get unique symbols
        symbols = set(pos.symbol for pos in self.positions.values())
        
        # Update prices for each symbol
        for symbol in symbols:
            try:
                market_data = await self.broker.get_market_data(symbol)
                current_price = market_data.get_mid_price()
                
                # Update all positions for this symbol
                for position in self.positions.values():
                    if position.symbol == symbol:
                        old_pnl = position.unrealized_pnl
                        position.update_current_price(current_price)
                        
                        # Check for stop loss or take profit triggers
                        await self._check_exit_conditions(position)
                        
                        # Log significant P&L changes
                        pnl_change = position.unrealized_pnl - old_pnl
                        if abs(pnl_change) > 10.0:  # Log changes > $10
                            self.logger.debug(
                                f"Position {position.position_id} P&L change: "
                                f"{pnl_change:+.2f} (total: {position.unrealized_pnl:.2f})"
                            )
                
            except BrokerAPIError as e:
                self.logger.error(f"Failed to update prices for {symbol}: {e}")
            except Exception as e:
                self.logger.error(f"Unexpected error updating {symbol}: {e}")
        
        # Update unrealized P&L metric
        self.metrics['unrealized_pnl'] = sum(pos.unrealized_pnl for pos in self.positions.values())
        
        # Record P&L snapshot
        self._record_pnl_snapshot()
    
    def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID
        
        Args:
            position_id: Position ID
            
        Returns:
            Position object or None if not found
        """
        return self.positions.get(position_id)
    
    def get_positions_by_symbol(self, symbol: str) -> List[Position]:
        """Get all positions for a symbol
        
        Args:
            symbol: Currency pair symbol
            
        Returns:
            List of positions for the symbol
        """
        return [pos for pos in self.positions.values() if pos.symbol == symbol]
    
    def get_all_positions(self) -> List[Position]:
        """Get all active positions
        
        Returns:
            List of all active positions
        """
        return list(self.positions.values())
    
    def get_portfolio_summary(self) -> Dict:
        """Get portfolio summary with P&L breakdown
        
        Returns:
            Dictionary with portfolio summary
        """
        total_unrealized = sum(pos.unrealized_pnl for pos in self.positions.values())
        
        # Group positions by symbol
        by_symbol = {}
        for pos in self.positions.values():
            if pos.symbol not in by_symbol:
                by_symbol[pos.symbol] = {
                    'positions': 0,
                    'total_quantity': 0.0,
                    'unrealized_pnl': 0.0,
                    'net_exposure': 0.0
                }
            
            by_symbol[pos.symbol]['positions'] += 1
            by_symbol[pos.symbol]['total_quantity'] += pos.quantity
            by_symbol[pos.symbol]['unrealized_pnl'] += pos.unrealized_pnl
            
            # Calculate net exposure (long - short)
            if pos.direction == Direction.LONG:
                by_symbol[pos.symbol]['net_exposure'] += pos.quantity
            else:
                by_symbol[pos.symbol]['net_exposure'] -= pos.quantity
        
        return {
            'total_positions': len(self.positions),
            'total_unrealized_pnl': total_unrealized,
            'positions_by_symbol': by_symbol,
            'metrics': self.metrics.copy()
        }
    
    def add_position_callback(self, callback: Callable[[Position], None]) -> None:
        """Add callback for position events
        
        Args:
            callback: Function to call when position events occur
        """
        self.position_callbacks.append(callback)
    
    def add_pnl_callback(self, callback: Callable[[Dict], None]) -> None:
        """Add callback for P&L updates
        
        Args:
            callback: Function to call when P&L is updated
        """
        self.pnl_callbacks.append(callback)
    
    async def _monitoring_loop(self) -> None:
        """Main monitoring loop for position updates"""
        self.logger.info("Position monitoring loop started")
        
        while self.is_monitoring:
            try:
                await self.update_position_prices()
                await asyncio.sleep(self.update_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.update_interval)
        
        self.logger.info("Position monitoring loop stopped")
    
    async def _check_exit_conditions(self, position: Position) -> None:
        """Check if position should be closed due to stop loss or take profit
        
        Args:
            position: Position to check
        """
        should_close = False
        reason = ""
        
        if position.direction == Direction.LONG:
            # Long position: close if price <= stop loss or price >= take profit
            if position.stop_loss and position.current_price <= position.stop_loss:
                should_close = True
                reason = "stop_loss"
            elif position.take_profit and position.current_price >= position.take_profit:
                should_close = True
                reason = "take_profit"
        else:  # SHORT position
            # Short position: close if price >= stop loss or price <= take profit
            if position.stop_loss and position.current_price >= position.stop_loss:
                should_close = True
                reason = "stop_loss"
            elif position.take_profit and position.current_price <= position.take_profit:
                should_close = True
                reason = "take_profit"
        
        if should_close:
            self.logger.warning(
                f"Position {position.position_id} triggered {reason} at "
                f"{position.current_price} (entry: {position.entry_price})"
            )
            
            # In a real implementation, this would trigger an order to close the position
            # For now, we just log the event
            self._record_position_event(position, f"TRIGGER_{reason.upper()}")
    
    def _record_position_event(self, position: Position, event_type: str, extra_data: Optional[Dict] = None) -> None:
        """Record position event in history
        
        Args:
            position: Position involved in event
            event_type: Type of event (OPENED, CLOSED, etc.)
            extra_data: Additional event data
        """
        event = {
            'timestamp': datetime.now(timezone.utc),
            'position_id': position.position_id,
            'symbol': position.symbol,
            'event_type': event_type,
            'direction': position.direction.value,
            'quantity': position.quantity,
            'entry_price': position.entry_price,
            'current_price': position.current_price,
            'unrealized_pnl': position.unrealized_pnl
        }
        
        if extra_data:
            event.update(extra_data)
        
        self.position_history.append(event)
        
        # Keep only last 1000 events
        if len(self.position_history) > 1000:
            self.position_history = self.position_history[-1000:]
    
    def _record_pnl_snapshot(self) -> None:
        """Record current P&L snapshot"""
        snapshot = {
            'timestamp': datetime.now(timezone.utc),
            'total_positions': len(self.positions),
            'unrealized_pnl': sum(pos.unrealized_pnl for pos in self.positions.values()),
            'realized_pnl': self.metrics['realized_pnl'],
            'total_pnl': self.metrics['total_pnl']
        }
        
        self.pnl_history.append(snapshot)
        
        # Keep only last 1000 snapshots
        if len(self.pnl_history) > 1000:
            self.pnl_history = self.pnl_history[-1000:]
        
        # Notify P&L callbacks
        for callback in self.pnl_callbacks:
            try:
                callback(snapshot)
            except Exception as e:
                self.logger.error(f"P&L callback error: {e}")
    
    def get_position_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get position event history
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of position events
        """
        if limit is not None:
            if limit == 0:
                return []
            return self.position_history[-limit:]
        return self.position_history.copy()
    
    def get_pnl_history(self, limit: Optional[int] = None) -> List[Dict]:
        """Get P&L history
        
        Args:
            limit: Maximum number of snapshots to return
            
        Returns:
            List of P&L snapshots
        """
        if limit is not None:
            if limit == 0:
                return []
            return self.pnl_history[-limit:]
        return self.pnl_history.copy()
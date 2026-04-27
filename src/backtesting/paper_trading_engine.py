"""Paper trading engine for real-time simulation without real money"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, field

from src.interfaces import BrokerInterface, DataCollector
from src.models import (
    MarketData, TradingSignal, Order, Position, Portfolio, 
    Direction, OrderType, OrderStatus, ExecutionResult
)
from src.trading.execution_engine import ExecutionEngine
from src.trading.position_tracker import PositionTracker
from src.backtesting.performance_analyzer import PerformanceAnalyzer, PerformanceMetrics
from src.backtesting.backtest_engine import BacktestResult, MarketSimulator, BacktestConfig
from src.exceptions import PaperTradingError, DataValidationError


@dataclass
class PaperTradingConfig:
    """Configuration for paper trading"""
    initial_balance: float = 10000.0
    leverage: float = 1.0
    spread_multiplier: float = 1.0
    slippage_pips: float = 0.5
    commission_per_lot: float = 0.0
    max_positions: int = 10
    data_update_interval: float = 1.0  # seconds
    performance_update_interval: float = 60.0  # seconds
    enable_real_time_logging: bool = True
    save_trade_history: bool = True


@dataclass
class PaperTradingState:
    """Current state of paper trading session"""
    session_id: str
    start_time: datetime
    current_balance: float
    current_equity: float
    positions: Dict[str, Position] = field(default_factory=dict)
    closed_trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[tuple] = field(default_factory=list)
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    is_active: bool = True


class PaperTradingEngine:
    """Real-time paper trading engine for simulation without real money"""
    
    def __init__(
        self, 
        broker: BrokerInterface,
        data_collector: DataCollector,
        config: Optional[PaperTradingConfig] = None
    ):
        """Initialize paper trading engine
        
        Args:
            broker: Broker interface for market data
            data_collector: Data collector for real-time feeds
            config: Paper trading configuration
        """
        self.broker = broker
        self.data_collector = data_collector
        self.config = config or PaperTradingConfig()
        self.logger = logging.getLogger(__name__)
        
        # Initialize components
        self.market_simulator = MarketSimulator(
            BacktestConfig(
                initial_balance=self.config.initial_balance,
                leverage=self.config.leverage,
                spread_multiplier=self.config.spread_multiplier,
                slippage_pips=self.config.slippage_pips,
                commission_per_lot=self.config.commission_per_lot,
                max_positions=self.config.max_positions
            )
        )
        
        self.position_tracker = PositionTracker(
            broker=broker,
            update_interval=self.config.data_update_interval
        )
        
        self.performance_analyzer = PerformanceAnalyzer(
            initial_balance=self.config.initial_balance
        )
        
        # Paper trading state
        self.state: Optional[PaperTradingState] = None
        self.subscribed_symbols: List[str] = []
        self.current_market_data: Dict[str, MarketData] = {}
        
        # Async tasks
        self.data_feed_task: Optional[asyncio.Task] = None
        self.performance_task: Optional[asyncio.Task] = None
        self.monitoring_tasks: List[asyncio.Task] = []
        
        # Event callbacks
        self.trade_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        self.performance_callbacks: List[Callable[[PerformanceMetrics], None]] = []
        self.position_callbacks: List[Callable[[Position], None]] = []
        
        # Performance tracking
        self.performance_history: List[PerformanceMetrics] = []
        self.last_performance_update = datetime.now(timezone.utc)
        
        # Order management
        self.order_counter = 0
        self.pending_orders: Dict[str, Order] = {}
    
    async def start_session(self, symbols: List[str]) -> str:
        """Start a new paper trading session
        
        Args:
            symbols: List of currency pairs to trade
            
        Returns:
            Session ID
            
        Raises:
            PaperTradingError: If session cannot be started
        """
        if self.state and self.state.is_active:
            raise PaperTradingError(
                "Paper trading session already active",
                error_code="SESSION_ALREADY_ACTIVE",
                context={"current_session": self.state.session_id}
            )
        
        # Validate symbols
        if not symbols:
            raise PaperTradingError(
                "Symbols list cannot be empty",
                error_code="EMPTY_SYMBOLS",
                context={"symbols": symbols}
            )
        
        # Create new session
        session_id = f"paper_{int(datetime.now().timestamp())}"
        self.state = PaperTradingState(
            session_id=session_id,
            start_time=datetime.now(timezone.utc),
            current_balance=self.config.initial_balance,
            current_equity=self.config.initial_balance
        )
        
        self.subscribed_symbols = symbols.copy()
        self.logger.info(f"Starting paper trading session {session_id} with symbols: {symbols}")
        
        try:
            # Start data feeds
            await self._start_data_feeds()
            
            # Start position monitoring
            await self.position_tracker.start_monitoring()
            
            # Start performance monitoring
            await self._start_performance_monitoring()
            
            # Record initial equity point
            self.state.equity_curve.append((
                self.state.start_time, 
                self.state.current_equity
            ))
            
            self.logger.info(f"Paper trading session {session_id} started successfully")
            return session_id
            
        except Exception as e:
            self.logger.error(f"Failed to start paper trading session: {e}")
            self.state = None
            raise PaperTradingError(
                f"Failed to start paper trading session: {e}",
                error_code="SESSION_START_FAILED",
                context={"error": str(e)}
            )
    
    async def stop_session(self) -> Dict[str, Any]:
        """Stop current paper trading session
        
        Returns:
            Session summary with final performance metrics
            
        Raises:
            PaperTradingError: If no active session
        """
        if not self.state or not self.state.is_active:
            raise PaperTradingError(
                "No active paper trading session",
                error_code="NO_ACTIVE_SESSION"
            )
        
        self.logger.info(f"Stopping paper trading session {self.state.session_id}")
        
        try:
            # Stop all monitoring tasks
            await self._stop_all_tasks()
            
            # Stop position tracker
            await self.position_tracker.stop_monitoring()
            
            # Close all open positions
            await self._close_all_positions("Session End")
            
            # Calculate final performance
            final_performance = await self._calculate_final_performance()
            
            # Mark session as inactive
            self.state.is_active = False
            
            # Create session summary
            session_summary = {
                'session_id': self.state.session_id,
                'start_time': self.state.start_time,
                'end_time': datetime.now(timezone.utc),
                'duration_hours': (datetime.now(timezone.utc) - self.state.start_time).total_seconds() / 3600,
                'initial_balance': self.config.initial_balance,
                'final_balance': self.state.current_balance,
                'final_equity': self.state.current_equity,
                'total_return': (self.state.current_equity - self.config.initial_balance) / self.config.initial_balance,
                'total_trades': self.state.total_trades,
                'winning_trades': self.state.winning_trades,
                'losing_trades': self.state.losing_trades,
                'win_rate': self.state.winning_trades / max(self.state.total_trades, 1),
                'performance_metrics': final_performance,
                'symbols_traded': self.subscribed_symbols
            }
            
            self.logger.info(
                f"Paper trading session {self.state.session_id} stopped. "
                f"Total return: {session_summary['total_return']:.2%}"
            )
            
            return session_summary
            
        except Exception as e:
            self.logger.error(f"Error stopping paper trading session: {e}")
            raise PaperTradingError(
                f"Error stopping session: {e}",
                error_code="SESSION_STOP_FAILED",
                context={"error": str(e)}
            )
    
    async def execute_signal(self, signal: TradingSignal) -> ExecutionResult:
        """Execute trading signal in paper trading environment
        
        Args:
            signal: Trading signal to execute
            
        Returns:
            ExecutionResult with execution details
            
        Raises:
            PaperTradingError: If signal cannot be executed
        """
        if not self.state or not self.state.is_active:
            raise PaperTradingError(
                "No active paper trading session",
                error_code="NO_ACTIVE_SESSION"
            )
        
        if signal.symbol not in self.subscribed_symbols:
            raise PaperTradingError(
                f"Symbol {signal.symbol} not subscribed in current session",
                error_code="SYMBOL_NOT_SUBSCRIBED",
                context={"symbol": signal.symbol, "subscribed": self.subscribed_symbols}
            )
        
        try:
            # Get current market data
            if signal.symbol not in self.current_market_data:
                # Fetch fresh market data
                market_data_dict = await self.data_collector.collect_data([signal.symbol])
                if signal.symbol in market_data_dict:
                    self.current_market_data[signal.symbol] = market_data_dict[signal.symbol]
                else:
                    raise PaperTradingError(
                        f"No market data available for {signal.symbol}",
                        error_code="NO_MARKET_DATA",
                        context={"symbol": signal.symbol}
                    )
            
            market_data = self.current_market_data[signal.symbol]
            
            # Check position limits - use position tracker's count
            current_positions = len(self.position_tracker.get_all_positions())
            self.logger.debug(f"Current positions: {current_positions}, Max: {self.config.max_positions}")
            if current_positions >= self.config.max_positions:
                self.logger.info(f"Maximum positions limit reached: {current_positions}/{self.config.max_positions}")
                return ExecutionResult(
                    success=False,
                    order_id="rejected_max_positions",
                    executed_price=None,
                    executed_quantity=None,
                    error_message="Maximum positions limit reached",
                    timestamp=datetime.now(timezone.utc)
                )
            
            # Create order from signal
            order = self._create_order_from_signal(signal)
            
            # Simulate execution
            execution_result = await self._simulate_execution(order, market_data)
            
            if execution_result.success:
                # Create position
                position = await self._create_position_from_execution(
                    execution_result, order, market_data.timestamp
                )
                
                # Add to position tracker
                position_id = await self.position_tracker.add_position(execution_result, order)
                self.state.positions[position_id] = position
                
                # Update balance
                execution_cost = self._calculate_execution_cost(execution_result, order)
                self.state.current_balance -= execution_cost
                
                # Update trade count
                self.state.total_trades += 1
                
                # Log execution
                if self.config.enable_real_time_logging:
                    self.logger.info(
                        f"Executed {signal.direction.value} {signal.symbol} "
                        f"@ {execution_result.executed_price}, "
                        f"size: {execution_result.executed_quantity}"
                    )
                
                # Notify callbacks
                await self._notify_trade_callbacks({
                    'type': 'execution',
                    'signal': signal,
                    'execution_result': execution_result,
                    'position': position
                })
            
            return execution_result
            
        except Exception as e:
            self.logger.error(f"Error executing signal for {signal.symbol}: {e}")
            return ExecutionResult(
                success=False,
                order_id=None,
                executed_price=None,
                executed_quantity=None,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc)
            )
    
    async def get_current_performance(self) -> PerformanceMetrics:
        """Get current performance metrics
        
        Returns:
            Current performance metrics
        """
        if not self.state:
            return PerformanceMetrics()
        
        # Create backtest result from current state
        backtest_result = self._create_backtest_result_from_state()
        
        # Calculate performance metrics
        performance = self.performance_analyzer.analyze_performance(backtest_result)
        
        return performance
    
    async def compare_to_backtest(
        self, 
        backtest_result: BacktestResult
    ) -> Dict[str, Any]:
        """Compare paper trading performance to backtest results
        
        Args:
            backtest_result: Backtest results to compare against
            
        Returns:
            Comparison analysis
        """
        if not self.state:
            raise PaperTradingError(
                "No active paper trading session",
                error_code="NO_ACTIVE_SESSION"
            )
        
        # Get current paper trading performance
        paper_performance = await self.get_current_performance()
        
        # Get backtest performance
        backtest_performance = self.performance_analyzer.analyze_performance(backtest_result)
        
        # Calculate comparison metrics
        comparison = {
            'paper_trading': {
                'total_return': paper_performance.total_return,
                'sharpe_ratio': paper_performance.sharpe_ratio,
                'max_drawdown': paper_performance.max_drawdown,
                'win_rate': paper_performance.win_rate,
                'total_trades': paper_performance.total_trades
            },
            'backtest': {
                'total_return': backtest_performance.total_return,
                'sharpe_ratio': backtest_performance.sharpe_ratio,
                'max_drawdown': backtest_performance.max_drawdown,
                'win_rate': backtest_performance.win_rate,
                'total_trades': backtest_performance.total_trades
            },
            'differences': {
                'return_diff': paper_performance.total_return - backtest_performance.total_return,
                'sharpe_diff': paper_performance.sharpe_ratio - backtest_performance.sharpe_ratio,
                'drawdown_diff': paper_performance.max_drawdown - backtest_performance.max_drawdown,
                'win_rate_diff': paper_performance.win_rate - backtest_performance.win_rate,
                'trade_count_diff': paper_performance.total_trades - backtest_performance.total_trades
            },
            'analysis': {
                'performance_correlation': self._calculate_performance_correlation(
                    paper_performance, backtest_performance
                ),
                'implementation_gap': self._analyze_implementation_gap(
                    paper_performance, backtest_performance
                )
            }
        }
        
        return comparison
    
    def add_trade_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Add callback for trade events"""
        self.trade_callbacks.append(callback)
    
    def add_performance_callback(self, callback: Callable[[PerformanceMetrics], None]) -> None:
        """Add callback for performance updates"""
        self.performance_callbacks.append(callback)
    
    def add_position_callback(self, callback: Callable[[Position], None]) -> None:
        """Add callback for position events"""
        self.position_callbacks.append(callback)
    
    def get_session_state(self) -> Optional[PaperTradingState]:
        """Get current session state"""
        return self.state
    
    def get_performance_history(self) -> List[PerformanceMetrics]:
        """Get performance history"""
        return self.performance_history.copy()
    
    async def _start_data_feeds(self) -> None:
        """Start real-time data feeds"""
        self.data_feed_task = asyncio.create_task(self._data_feed_loop())
    
    async def _start_performance_monitoring(self) -> None:
        """Start performance monitoring"""
        self.performance_task = asyncio.create_task(self._performance_monitoring_loop())
    
    async def _stop_all_tasks(self) -> None:
        """Stop all async tasks"""
        tasks_to_cancel = []
        
        if self.data_feed_task:
            tasks_to_cancel.append(self.data_feed_task)
        
        if self.performance_task:
            tasks_to_cancel.append(self.performance_task)
        
        tasks_to_cancel.extend(self.monitoring_tasks)
        
        for task in tasks_to_cancel:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        self.data_feed_task = None
        self.performance_task = None
        self.monitoring_tasks.clear()
    
    async def _data_feed_loop(self) -> None:
        """Main data feed loop with enhanced error handling and reconnection logic"""
        self.logger.info("Starting data feed loop")
        consecutive_errors = 0
        max_consecutive_errors = 5
        
        while self.state and self.state.is_active:
            try:
                # Collect market data for all subscribed symbols
                market_data_dict = await self.data_collector.collect_data(
                    self.subscribed_symbols
                )
                
                # Validate data quality
                if not await self._validate_market_data_quality(market_data_dict):
                    self.logger.warning("Market data quality check failed, using cached data")
                    market_data_dict = self._get_cached_market_data()
                
                # Update current market data
                self.current_market_data.update(market_data_dict)
                
                # Update positions with new prices
                await self._update_positions_with_market_data(market_data_dict)
                
                # Update equity curve
                current_equity = self._calculate_current_equity()
                self.state.current_equity = current_equity
                self.state.equity_curve.append((
                    datetime.now(timezone.utc), 
                    current_equity
                ))
                
                # Reset error counter on successful iteration
                consecutive_errors = 0
                
                # Sleep until next update
                await asyncio.sleep(self.config.data_update_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                consecutive_errors += 1
                self.logger.error(f"Error in data feed loop (attempt {consecutive_errors}): {e}")
                
                # If too many consecutive errors, increase sleep time
                if consecutive_errors >= max_consecutive_errors:
                    self.logger.error(
                        f"Too many consecutive errors ({consecutive_errors}), "
                        f"increasing sleep interval"
                    )
                    await asyncio.sleep(self.config.data_update_interval * 5)
                    consecutive_errors = 0  # Reset counter after extended sleep
                else:
                    await asyncio.sleep(self.config.data_update_interval)
        
        self.logger.info("Data feed loop stopped")
    
    async def _performance_monitoring_loop(self) -> None:
        """Performance monitoring loop"""
        self.logger.info("Starting performance monitoring loop")
        
        while self.state and self.state.is_active:
            try:
                # Calculate current performance
                performance = await self.get_current_performance()
                
                # Add to history
                self.performance_history.append(performance)
                
                # Keep only last 1000 entries
                if len(self.performance_history) > 1000:
                    self.performance_history = self.performance_history[-1000:]
                
                # Notify callbacks
                for callback in self.performance_callbacks:
                    try:
                        callback(performance)
                    except Exception as e:
                        self.logger.error(f"Performance callback error: {e}")
                
                # Update timestamp
                self.last_performance_update = datetime.now(timezone.utc)
                
                # Sleep until next update
                await asyncio.sleep(self.config.performance_update_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in performance monitoring loop: {e}")
                await asyncio.sleep(self.config.performance_update_interval)
        
        self.logger.info("Performance monitoring loop stopped")
    
    def _create_order_from_signal(self, signal: TradingSignal) -> Order:
        """Create order from trading signal"""
        self.order_counter += 1
        order_id = f"paper_order_{self.order_counter}"
        
        return Order(
            order_id=order_id,
            symbol=signal.symbol,
            order_type=OrderType.MARKET,  # Paper trading uses market orders
            direction=signal.direction,
            quantity=self._calculate_position_size(signal),
            price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            status=OrderStatus.PENDING,
            created_at=datetime.now(timezone.utc)
        )
    
    def _calculate_position_size(self, signal: TradingSignal) -> float:
        """Calculate position size based on signal and available balance"""
        available_balance = self.state.current_balance
        risk_amount = available_balance * signal.position_size
        
        # For forex, assume standard lot size of 100,000 units
        if signal.stop_loss:
            # Calculate position size based on risk
            pip_value = 0.01 if 'JPY' in signal.symbol else 0.0001
            stop_loss_distance = abs(signal.entry_price - signal.stop_loss)
            stop_loss_pips = stop_loss_distance / pip_value
            
            if stop_loss_pips > 0:
                position_size_lots = risk_amount / (stop_loss_distance * 100000)
                position_size_lots *= self.config.leverage
                return max(0.01, position_size_lots)  # Minimum 0.01 lots
        
        # Fallback calculation
        return available_balance * 0.02 / 100000  # 2% risk
    
    async def _simulate_execution(self, order: Order, market_data: MarketData) -> ExecutionResult:
        """Simulate order execution"""
        try:
            # Use market simulator for realistic execution
            execution_result = self.market_simulator.calculate_execution_price(
                market_data, order.direction, order.order_type, order.price
            )
            
            if execution_result[0] is None:
                return ExecutionResult(
                    success=False,
                    order_id=order.order_id,
                    executed_price=None,
                    executed_quantity=None,
                    error_message="Order could not be filled",
                    timestamp=datetime.now(timezone.utc)
                )
            
            execution_price, execution_cost = execution_result
            
            return ExecutionResult(
                success=True,
                order_id=order.order_id,
                executed_price=execution_price,
                executed_quantity=order.quantity,
                error_message=None,
                timestamp=datetime.now(timezone.utc)
            )
            
        except Exception as e:
            return ExecutionResult(
                success=False,
                order_id=order.order_id,
                executed_price=None,
                executed_quantity=None,
                error_message=str(e),
                timestamp=datetime.now(timezone.utc)
            )
    
    async def _create_position_from_execution(
        self, 
        execution_result: ExecutionResult, 
        order: Order,
        timestamp: datetime
    ) -> Position:
        """Create position from execution result"""
        position_id = f"paper_pos_{len(self.state.positions) + 1}"
        
        return Position(
            position_id=position_id,
            symbol=order.symbol,
            direction=order.direction,
            quantity=execution_result.executed_quantity,
            entry_price=execution_result.executed_price,
            current_price=execution_result.executed_price,
            unrealized_pnl=0.0,
            stop_loss=order.stop_loss,
            take_profit=order.take_profit,
            opened_at=timestamp
        )
    
    def _calculate_execution_cost(self, execution_result: ExecutionResult, order: Order) -> float:
        """Calculate execution cost including commission"""
        commission = self.config.commission_per_lot * execution_result.executed_quantity
        return commission
    
    async def _update_positions_with_market_data(self, market_data_dict: Dict[str, MarketData]) -> None:
        """Update positions with new market data"""
        positions_to_close = []
        
        for position_id, position in self.state.positions.items():
            if position.symbol in market_data_dict:
                market_data = market_data_dict[position.symbol]
                
                # Check for stop loss or take profit triggers
                if self.market_simulator.should_stop_loss_trigger(position, market_data):
                    positions_to_close.append((position_id, position, "Stop Loss"))
                elif self.market_simulator.should_take_profit_trigger(position, market_data):
                    positions_to_close.append((position_id, position, "Take Profit"))
                else:
                    # Update position price
                    if position.direction == Direction.LONG:
                        current_price = market_data.bid
                    else:
                        current_price = market_data.ask
                    
                    position.update_current_price(current_price)
        
        # Close triggered positions
        for position_id, position, reason in positions_to_close:
            await self._close_position(position_id, position, reason)
    
    async def _close_position(self, position_id: str, position: Position, reason: str) -> None:
        """Close a position"""
        try:
            # Calculate final P&L
            if position.direction == Direction.LONG:
                pnl = (position.current_price - position.entry_price) * position.quantity
            else:
                pnl = (position.entry_price - position.current_price) * position.quantity
            
            # Deduct commission
            commission = self.config.commission_per_lot * position.quantity
            net_pnl = pnl - commission
            
            # Update balance
            self.state.current_balance += net_pnl
            
            # Update trade statistics
            if net_pnl > 0:
                self.state.winning_trades += 1
            else:
                self.state.losing_trades += 1
            
            # Record trade
            trade_record = {
                'position_id': position_id,
                'symbol': position.symbol,
                'direction': position.direction.value,
                'quantity': position.quantity,
                'entry_price': position.entry_price,
                'exit_price': position.current_price,
                'entry_time': position.opened_at,
                'exit_time': datetime.now(timezone.utc),
                'pnl': net_pnl,
                'commission': commission,
                'reason': reason,
                'duration_hours': (datetime.now(timezone.utc) - position.opened_at).total_seconds() / 3600
            }
            
            if self.config.save_trade_history:
                self.state.closed_trades.append(trade_record)
            
            # Remove from active positions
            del self.state.positions[position_id]
            
            # Close position in tracker
            execution_result = ExecutionResult(
                success=True,
                order_id=f"close_{position_id}",
                executed_price=position.current_price,
                executed_quantity=position.quantity,
                error_message=None,
                timestamp=datetime.now(timezone.utc)
            )
            
            await self.position_tracker.close_position(position_id, execution_result)
            
            if self.config.enable_real_time_logging:
                self.logger.info(
                    f"Closed position {position_id}: {reason}, "
                    f"P&L: {net_pnl:.2f}"
                )
            
            # Notify callbacks
            await self._notify_trade_callbacks({
                'type': 'close',
                'position_id': position_id,
                'position': position,
                'reason': reason,
                'pnl': net_pnl,
                'trade_record': trade_record
            })
            
        except Exception as e:
            self.logger.error(f"Error closing position {position_id}: {e}")
    
    async def _close_all_positions(self, reason: str) -> None:
        """Close all open positions"""
        for position_id, position in list(self.state.positions.items()):
            await self._close_position(position_id, position, reason)
    
    def _calculate_current_equity(self) -> float:
        """Calculate current equity including unrealized P&L"""
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self.state.positions.values())
        return self.state.current_balance + unrealized_pnl
    
    def _create_backtest_result_from_state(self) -> BacktestResult:
        """Create BacktestResult from current paper trading state"""
        from src.backtesting.backtest_engine import BacktestResult
        
        return BacktestResult(
            total_trades=self.state.total_trades,
            winning_trades=self.state.winning_trades,
            losing_trades=self.state.losing_trades,
            total_pnl=self.state.current_equity - self.config.initial_balance,
            max_drawdown=self._calculate_max_drawdown(),
            max_drawdown_duration=0,  # Would need more complex calculation
            sharpe_ratio=0.0,  # Calculated by performance analyzer
            win_rate=self.state.winning_trades / max(self.state.total_trades, 1),
            avg_win=self._calculate_avg_win(),
            avg_loss=self._calculate_avg_loss(),
            profit_factor=self._calculate_profit_factor(),
            trades=self.state.closed_trades.copy(),
            equity_curve=self.state.equity_curve.copy(),
            daily_returns=self._calculate_daily_returns()
        )
    
    def _calculate_max_drawdown(self) -> float:
        """Calculate maximum drawdown from equity curve"""
        if len(self.state.equity_curve) < 2:
            return 0.0
        
        peak = self.state.equity_curve[0][1]
        max_drawdown = 0.0
        
        for timestamp, equity in self.state.equity_curve:
            if equity > peak:
                peak = equity
            else:
                drawdown = (peak - equity) / peak
                max_drawdown = max(max_drawdown, drawdown)
        
        return max_drawdown
    
    def _calculate_avg_win(self) -> float:
        """Calculate average winning trade"""
        wins = [trade['pnl'] for trade in self.state.closed_trades if trade['pnl'] > 0]
        return sum(wins) / len(wins) if wins else 0.0
    
    def _calculate_avg_loss(self) -> float:
        """Calculate average losing trade"""
        losses = [trade['pnl'] for trade in self.state.closed_trades if trade['pnl'] < 0]
        return sum(losses) / len(losses) if losses else 0.0
    
    def _calculate_profit_factor(self) -> float:
        """Calculate profit factor"""
        gross_profit = sum(trade['pnl'] for trade in self.state.closed_trades if trade['pnl'] > 0)
        gross_loss = abs(sum(trade['pnl'] for trade in self.state.closed_trades if trade['pnl'] < 0))
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    def _calculate_daily_returns(self) -> List[float]:
        """Calculate daily returns from equity curve"""
        if len(self.state.equity_curve) < 2:
            return []
        
        daily_returns = []
        prev_equity = self.state.equity_curve[0][1]
        
        for timestamp, equity in self.state.equity_curve[1:]:
            if prev_equity > 0:
                daily_return = (equity - prev_equity) / prev_equity
                daily_returns.append(daily_return)
            prev_equity = equity
        
        return daily_returns
    
    async def _calculate_final_performance(self) -> PerformanceMetrics:
        """Calculate final performance metrics"""
        backtest_result = self._create_backtest_result_from_state()
        return self.performance_analyzer.analyze_performance(backtest_result)
    
    def _calculate_performance_correlation(
        self, 
        paper_performance: PerformanceMetrics, 
        backtest_performance: PerformanceMetrics
    ) -> float:
        """Calculate correlation between paper trading and backtest performance"""
        # Simplified correlation calculation
        # In practice, you'd compare equity curves or daily returns
        
        metrics_paper = [
            paper_performance.total_return,
            paper_performance.sharpe_ratio,
            paper_performance.max_drawdown,
            paper_performance.win_rate
        ]
        
        metrics_backtest = [
            backtest_performance.total_return,
            backtest_performance.sharpe_ratio,
            backtest_performance.max_drawdown,
            backtest_performance.win_rate
        ]
        
        try:
            import statistics
            if len(metrics_paper) >= 2 and len(metrics_backtest) >= 2:
                return statistics.correlation(metrics_paper, metrics_backtest)
        except:
            pass
        
        return 0.0
    
    def _analyze_implementation_gap(
        self, 
        paper_performance: PerformanceMetrics, 
        backtest_performance: PerformanceMetrics
    ) -> Dict[str, str]:
        """Analyze implementation gap between paper trading and backtest"""
        gap_analysis = {}
        
        # Return gap
        return_diff = paper_performance.total_return - backtest_performance.total_return
        if abs(return_diff) > 0.05:  # 5% threshold
            gap_analysis['return_gap'] = (
                "Significant return difference detected. "
                f"Paper trading {'outperformed' if return_diff > 0 else 'underperformed'} "
                f"backtest by {abs(return_diff):.2%}"
            )
        
        # Sharpe ratio gap
        sharpe_diff = paper_performance.sharpe_ratio - backtest_performance.sharpe_ratio
        if abs(sharpe_diff) > 0.5:
            gap_analysis['sharpe_gap'] = (
                f"Sharpe ratio difference of {sharpe_diff:.2f} suggests "
                "different risk-adjusted performance"
            )
        
        # Trade count gap
        trade_diff = paper_performance.total_trades - backtest_performance.total_trades
        if abs(trade_diff) > backtest_performance.total_trades * 0.2:  # 20% threshold
            gap_analysis['execution_gap'] = (
                f"Trade count difference of {trade_diff} suggests "
                "execution or signal timing differences"
            )
        
        return gap_analysis
    
    async def _notify_trade_callbacks(self, event_data: Dict[str, Any]) -> None:
        """Notify trade event callbacks"""
        for callback in self.trade_callbacks:
            try:
                callback(event_data)
            except Exception as e:
                self.logger.error(f"Trade callback error: {e}")
    
    async def _validate_market_data_quality(self, market_data_dict: Dict[str, MarketData]) -> bool:
        """Validate quality of market data"""
        if not market_data_dict:
            return False
        
        current_time = datetime.now(timezone.utc)
        
        for symbol, market_data in market_data_dict.items():
            # Check if data is too stale (older than 5 minutes)
            if market_data.is_stale(max_age_seconds=300):
                self.logger.warning(f"Stale market data for {symbol}")
                return False
            
            # Check for reasonable price movements (not more than 10% change)
            if symbol in self.current_market_data:
                old_price = self.current_market_data[symbol].close
                new_price = market_data.close
                price_change = abs(new_price - old_price) / old_price
                
                if price_change > 0.10:  # 10% change threshold
                    self.logger.warning(
                        f"Suspicious price movement for {symbol}: "
                        f"{price_change:.2%} change"
                    )
                    return False
        
        return True
    
    def _get_cached_market_data(self) -> Dict[str, MarketData]:
        """Get cached market data as fallback"""
        cached_data = {}
        current_time = datetime.now(timezone.utc)
        
        for symbol in self.subscribed_symbols:
            if symbol in self.current_market_data:
                # Use existing data but update timestamp
                cached_market_data = self.current_market_data[symbol]
                cached_data[symbol] = MarketData(
                    symbol=cached_market_data.symbol,
                    timestamp=current_time,
                    open=cached_market_data.open,
                    high=cached_market_data.high,
                    low=cached_market_data.low,
                    close=cached_market_data.close,
                    volume=cached_market_data.volume,
                    bid=cached_market_data.bid,
                    ask=cached_market_data.ask,
                    spread=cached_market_data.spread
                )
        
        return cached_data
    
    async def get_detailed_session_metrics(self) -> Dict[str, Any]:
        """Get detailed session metrics for comprehensive analysis"""
        if not self.state:
            return {}
        
        current_time = datetime.now(timezone.utc)
        session_duration = (current_time - self.state.start_time).total_seconds() / 3600
        
        # Calculate position metrics
        open_positions = len(self.state.positions)
        total_exposure = sum(
            pos.quantity * pos.current_price 
            for pos in self.state.positions.values()
        )
        
        # Calculate trade frequency
        trades_per_hour = self.state.total_trades / max(session_duration, 0.01)
        
        # Calculate equity curve statistics
        equity_values = [equity for _, equity in self.state.equity_curve]
        if len(equity_values) >= 2:
            equity_volatility = statistics.stdev(equity_values) if len(equity_values) > 1 else 0.0
            max_equity = max(equity_values)
            min_equity = min(equity_values)
            current_drawdown = (max_equity - equity_values[-1]) / max_equity if max_equity > 0 else 0.0
        else:
            equity_volatility = 0.0
            max_equity = self.config.initial_balance
            min_equity = self.config.initial_balance
            current_drawdown = 0.0
        
        # Calculate win/loss streaks
        win_streak, loss_streak = self._calculate_win_loss_streaks()
        
        return {
            'session_info': {
                'session_id': self.state.session_id,
                'duration_hours': session_duration,
                'start_time': self.state.start_time.isoformat(),
                'current_time': current_time.isoformat(),
                'symbols_traded': self.subscribed_symbols
            },
            'account_metrics': {
                'initial_balance': self.config.initial_balance,
                'current_balance': self.state.current_balance,
                'current_equity': self.state.current_equity,
                'total_return': (self.state.current_equity - self.config.initial_balance) / self.config.initial_balance,
                'max_equity': max_equity,
                'min_equity': min_equity,
                'current_drawdown': current_drawdown,
                'equity_volatility': equity_volatility
            },
            'position_metrics': {
                'open_positions': open_positions,
                'max_positions_allowed': self.config.max_positions,
                'total_exposure': total_exposure,
                'average_position_size': total_exposure / max(open_positions, 1)
            },
            'trading_metrics': {
                'total_trades': self.state.total_trades,
                'winning_trades': self.state.winning_trades,
                'losing_trades': self.state.losing_trades,
                'win_rate': self.state.winning_trades / max(self.state.total_trades, 1),
                'trades_per_hour': trades_per_hour,
                'current_win_streak': win_streak,
                'current_loss_streak': loss_streak
            },
            'data_quality': {
                'data_update_interval': self.config.data_update_interval,
                'last_data_update': max(
                    [data.timestamp for data in self.current_market_data.values()],
                    default=current_time
                ).isoformat(),
                'symbols_with_data': list(self.current_market_data.keys())
            }
        }
    
    def _calculate_win_loss_streaks(self) -> tuple[int, int]:
        """Calculate current win and loss streaks"""
        if not self.state.closed_trades:
            return 0, 0
        
        # Sort trades by exit time
        sorted_trades = sorted(
            self.state.closed_trades, 
            key=lambda x: x.get('exit_time', datetime.min)
        )
        
        current_win_streak = 0
        current_loss_streak = 0
        
        # Count from the most recent trades
        for trade in reversed(sorted_trades):
            pnl = trade.get('pnl', 0)
            if pnl > 0:
                if current_loss_streak == 0:
                    current_win_streak += 1
                else:
                    break
            elif pnl < 0:
                if current_win_streak == 0:
                    current_loss_streak += 1
                else:
                    break
            # Skip break-even trades
        
        return current_win_streak, current_loss_streak
    
    async def export_session_data(self, file_path: str) -> bool:
        """Export session data to JSON file for analysis"""
        try:
            import json
            
            if not self.state:
                self.logger.error("No active session to export")
                return False
            
            # Get detailed metrics
            session_data = await self.get_detailed_session_metrics()
            
            # Add trade history
            session_data['trade_history'] = self.state.closed_trades
            
            # Add equity curve
            session_data['equity_curve'] = [
                {
                    'timestamp': timestamp.isoformat(),
                    'equity': equity
                }
                for timestamp, equity in self.state.equity_curve
            ]
            
            # Add current positions
            session_data['current_positions'] = [
                {
                    'position_id': pos.position_id,
                    'symbol': pos.symbol,
                    'direction': pos.direction.value,
                    'quantity': pos.quantity,
                    'entry_price': pos.entry_price,
                    'current_price': pos.current_price,
                    'unrealized_pnl': pos.unrealized_pnl,
                    'opened_at': pos.opened_at.isoformat()
                }
                for pos in self.state.positions.values()
            ]
            
            # Write to file
            with open(file_path, 'w') as f:
                json.dump(session_data, f, indent=2, default=str)
            
            self.logger.info(f"Session data exported to {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to export session data: {e}")
            return False
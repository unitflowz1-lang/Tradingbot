"""Historical data backtesting engine for the AI Forex Trading Bot"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from src.models import (
    MarketData, TradingSignal, Order, Position, Portfolio, 
    Direction, OrderType, OrderStatus
)
from src.exceptions import BacktestError
from src.trading.advanced_exit_handler import AdvancedExitHandler


@dataclass
class BacktestConfig:
    """Configuration for backtesting"""
    initial_balance: float = 10000.0
    leverage: float = 1.0
    spread_multiplier: float = 2.0  # 2× amplification = ~2 pips realistic spread
    slippage_pips: float = 1.5  # Realistic slippage in pips (typical 1-3 range)
    commission_per_lot: float = 7.0  # Realistic ECN commission (~$5-10 per lot)
    max_positions: int = 3  # Reduced from 10 - realistic max concurrent positions
    max_per_symbol: int = 1  # NEW: Max 1 position per currency pair (no stacking)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


@dataclass
class BacktestResult:
    """Results from a backtest run"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0  # in days
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[Tuple[datetime, float]] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)


class MarketSimulator:
    """Simulates realistic market conditions for backtesting"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.advanced_exit_handler = AdvancedExitHandler(logger=self.logger)
    
    def calculate_execution_price(
        self, 
        market_data: MarketData, 
        direction: Direction, 
        order_type: OrderType,
        signal_entry_price: Optional[float] = None
    ) -> Tuple[float, float]:
        """
        Calculate realistic execution price with spread and slippage
        Returns: (execution_price, total_cost)
        """
        base_spread = market_data.spread * self.config.spread_multiplier
        
        # Convert slippage from pips to price units
        # For most forex pairs, 1 pip = 0.0001, except JPY pairs where 1 pip = 0.01
        pip_value = 0.01 if 'JPY' in market_data.symbol else 0.0001
        slippage_cost = self.config.slippage_pips * pip_value
        
        if order_type == OrderType.MARKET:
            if signal_entry_price is not None:
                # Use signal's entry price as the base (it's from the strategy analysis)
                # Add minimal slippage for realism
                execution_price = signal_entry_price + (slippage_cost if direction == Direction.LONG else -slippage_cost)
            else:
                # Fallback to market data if no signal entry price provided
                if direction == Direction.LONG:
                    # Buy at ask + slippage
                    execution_price = market_data.ask + slippage_cost
                else:
                    # Sell at bid - slippage  
                    execution_price = market_data.bid - slippage_cost
        
        elif order_type == OrderType.LIMIT:
            if limit_price is None:
                raise BacktestError("Limit price required for limit orders")
            
            # For limit orders, check if they would be filled
            if direction == Direction.LONG:
                # Buy limit: only fill if market ask <= limit price
                if market_data.ask <= limit_price:
                    execution_price = min(limit_price, market_data.ask)
                else:
                    return None, 0.0  # Order not filled
            else:
                # Sell limit: only fill if market bid >= limit price
                if market_data.bid >= limit_price:
                    execution_price = max(limit_price, market_data.bid)
                else:
                    return None, 0.0  # Order not filled
        
        else:
            raise BacktestError(f"Unsupported order type: {order_type}")
        
        # Calculate total cost including spread
        total_cost = base_spread + slippage_cost
        
        return execution_price, total_cost
    
    def should_stop_loss_trigger(
        self, 
        position: Position, 
        market_data: MarketData
    ) -> bool:
        """Check if stop loss should trigger based on market data"""
        if position.stop_loss is None:
            return False
        
        if position.direction == Direction.LONG:
            # Long position: stop loss triggers if bid <= stop loss
            return market_data.bid <= position.stop_loss
        else:
            # Short position: stop loss triggers if ask >= stop loss
            return market_data.ask >= position.stop_loss
    
    def should_take_profit_trigger(
        self, 
        position: Position, 
        market_data: MarketData
    ) -> bool:
        """Check if take profit should trigger based on market data"""
        if position.take_profit is None:
            return False
        
        if position.direction == Direction.LONG:
            # Long position: take profit triggers if bid >= take profit
            return market_data.bid >= position.take_profit
        else:
            # Short position: take profit triggers if ask <= take profit
            return market_data.ask <= position.take_profit


class BacktestEngine:
    """Engine for running backtests on historical data"""
    
    def __init__(self, config: BacktestConfig):
        self.config = config
        self.simulator = MarketSimulator(config)
        self.logger = logging.getLogger(__name__)
        
        # Backtest state
        self.current_balance = config.initial_balance
        self.current_equity = config.initial_balance
        self.positions: Dict[str, Position] = {}
        self.closed_trades: List[Dict[str, Any]] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.peak_equity = config.initial_balance
        self.max_drawdown = 0.0
        self.order_counter = 0
        self.exit_statistics: Dict[str, Dict[str, Any]] = {} # Initialize exit statistics
    
    def run_backtest(
        self, 
        historical_data: Dict[str, List[MarketData]], 
        signals: List[TradingSignal]
    ) -> BacktestResult:
        """
        Run backtest with historical data and trading signals
        
        Args:
            historical_data: Dict mapping symbol to list of MarketData
            signals: List of TradingSignal objects
            
        Returns:
            BacktestResult with performance metrics
        """
        self.logger.info("Starting backtest...")
        
        # Reset state
        self._reset_state()
        
        # Create timeline of all market data points
        timeline = self._create_timeline(historical_data)
        
        # Sort signals by timestamp
        signals_by_time = sorted(signals, key=lambda s: s.timestamp)
        signal_index = 0
        
        # Process each time point
        for timestamp, market_data_dict in timeline:
            # Update positions with current market data
            self._update_positions(market_data_dict, timestamp)
            
            # Process any signals at this timestamp
            while (signal_index < len(signals_by_time) and 
                   signals_by_time[signal_index].timestamp <= timestamp):
                
                signal = signals_by_time[signal_index]
                if signal.symbol in market_data_dict:
                    self._process_signal(
                        signal, 
                        market_data_dict[signal.symbol], 
                        timestamp
                    )
                signal_index += 1
            
            # Record equity curve
            self.equity_curve.append((timestamp, self.current_equity))
            
            # Update peak and drawdown
            if self.current_equity > self.peak_equity:
                self.peak_equity = self.current_equity
            else:
                drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
                self.max_drawdown = max(self.max_drawdown, drawdown)
        
        # Close any remaining positions at the end
        final_market_data = timeline[-1][1] if timeline else {}
        self._close_all_positions(final_market_data, timeline[-1][0] if timeline else datetime.now())
        
        # Calculate and return results
        return self._calculate_results()
    
    def _reset_state(self) -> None:
        """Reset backtest state"""
        self.current_balance = self.config.initial_balance
        self.current_equity = self.config.initial_balance
        self.positions.clear()
        self.closed_trades.clear()
        self.equity_curve.clear()
        self.peak_equity = self.config.initial_balance
        self.max_drawdown = 0.0
        self.order_counter = 0
        self.exit_statistics.clear()
    
    def _create_timeline(
        self, 
        historical_data: Dict[str, List[MarketData]]
    ) -> List[Tuple[datetime, Dict[str, MarketData]]]:
        """Create chronological timeline of all market data"""
        timeline_dict: Dict[datetime, Dict[str, MarketData]] = {}
        
        for symbol, data_list in historical_data.items():
            for market_data in data_list:
                timestamp = market_data.timestamp
                if timestamp not in timeline_dict:
                    timeline_dict[timestamp] = {}
                timeline_dict[timestamp][symbol] = market_data
        
        # Sort by timestamp
        return sorted(timeline_dict.items())
    
    def _update_positions(
        self, 
        market_data_dict: Dict[str, MarketData], 
        timestamp: datetime
    ) -> None:
        """Update all positions with current market data and check advanced exit conditions"""
        positions_to_close = []
        
        for position_id, position in self.positions.items():
            if position.symbol not in market_data_dict:
                continue
            
            market_data = market_data_dict[position.symbol]
            
            # Get current exit price based on direction
            if position.direction == Direction.LONG:
                current_price = market_data.bid  # Exit price for long
            else:
                current_price = market_data.ask  # Exit price for short
            
            # Update position_high for trailing stop logic
            if not hasattr(position, 'position_high'):
                position.position_high = current_price
            else:
                if position.direction == Direction.LONG:
                    position.position_high = max(position.position_high, current_price)
                else:
                    position.position_high = min(position.position_high, current_price)
            
            # Update position current price and PnL
            position.update_current_price(current_price)
            
            # Check advanced exit conditions
            exit_result = self.simulator.advanced_exit_handler.evaluate_exit_conditions(
                symbol=position.symbol,
                entry_price=position.entry_price,
                current_price=current_price,
                current_pnl=position.unrealized_pnl,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                direction=position.direction,
                position_open_time=position.opened_at,
                position_high=position.position_high
            )
            
            exit_level, _ = exit_result  # Unpack (exit_level, pnl_pips) tuple
            
            if exit_level:
                # Close position at the exit level price
                self._close_position(position, market_data, timestamp, exit_level.exit_type.value, 
                                   exit_price=exit_level.price)
                positions_to_close.append(position_id)
        
        # Remove closed positions
        for position_id in positions_to_close:
            del self.positions[position_id]
        
        # Update current equity
        self._update_equity()
    
    def _process_signal(
        self, 
        signal: TradingSignal, 
        market_data: MarketData, 
        timestamp: datetime
    ) -> None:
        """Process a trading signal"""
        try:
            # Log the signal received
            self.logger.info(
                f"[SIGNAL] {signal.symbol} | {signal.direction.value} | Entry={signal.entry_price:.5f} | "
                f"SL={signal.stop_loss:.5f} | TP={signal.take_profit:.5f} | PosSize={signal.position_size:.4f}"
            )
            
            # Check if we can open new positions
            if len(self.positions) >= self.config.max_positions:
                self.logger.warning(f"Max positions reached ({len(self.positions)}/{self.config.max_positions})")
                return  # Silent skip to reduce noise
            
            # NEW: Check if we already have a position in this symbol (avoid stacking)
            positions_per_symbol = sum(1 for pos in self.positions.values() if pos.symbol == signal.symbol)
            if positions_per_symbol >= self.config.max_per_symbol:
                self.logger.warning(
                    f"Max positions for {signal.symbol} reached ({positions_per_symbol}/{self.config.max_per_symbol})"
                )
                return  # Skip signal to prevent stacking
            
            # Calculate position size in lots
            position_size_lots = self._calculate_position_size(signal)
            if position_size_lots <= 0:
                self.logger.warning(f"Invalid position size for {signal.symbol}: {position_size_lots} lots")
                return
            
            # Calculate execution price using the signal's suggested entry price
            execution_result = self.simulator.calculate_execution_price(
                market_data, signal.direction, OrderType.MARKET, signal.entry_price

            )
            
            if execution_result[0] is None:
                self.logger.warning(f"Could not execute signal for {signal.symbol}")
                return
            
            execution_price, execution_cost = execution_result
            
            # Create position
            position_id = f"pos_{self.order_counter}"
            self.order_counter += 1
            
            position = Position(
                position_id=position_id,
                symbol=signal.symbol,
                direction=signal.direction,
                quantity=position_size_lots,
                entry_price=execution_price,
                current_price=execution_price,
                unrealized_pnl=0.0,
                stop_loss=signal.stop_loss,
                take_profit=signal.take_profit,
                opened_at=timestamp
            )
            
            self.positions[position_id] = position
            
            # Deduct commission and costs
            total_cost = execution_cost + (self.config.commission_per_lot * position_size_lots)
            self.current_balance -= total_cost
            
            # Log position opened
            self.logger.info(
                f"[OPEN] {position.symbol} | {position.direction.value} | "
                f"Qty={position_size_lots:.3f} lots | Entry={execution_price:.5f} | "
                f"SL={position.stop_loss:.5f} | TP={position.take_profit:.5f}"
            )
            
        except Exception as e:
            self.logger.error(f"Error processing signal: {e}")
    
    def _close_position(
        self, 
        position: Position, 
        market_data: MarketData, 
        timestamp: datetime,
        reason: str,
        exit_price: Optional[float] = None
    ) -> None:
        """Close a position"""
        try:
            # Calculate exit price - use provided exit_price for advanced exits, otherwise determine from reason
            if exit_price is None:
                if reason == "Take Profit":
                    exit_price = position.take_profit
                elif reason == "Stop Loss":
                    exit_price = position.stop_loss
                else:
                    # For other closes (manual, EOD, etc), use current market price
                    if position.direction == Direction.LONG:
                        exit_price = market_data.bid
                    else:
                        exit_price = market_data.ask
            
            # Calculate final PnL
            if position.direction == Direction.LONG:
                pnl = (exit_price - position.entry_price) * position.quantity * position.contract_size
            else:
                pnl = (position.entry_price - exit_price) * position.quantity * position.contract_size
            
            # If JPY pair and quote is JPY (like USD/JPY), we need to convert JPY profit to USD
            if 'JPY' in position.symbol.upper():
                pnl = pnl / exit_price
            
            # Deduct commission
            commission = self.config.commission_per_lot * position.quantity
            net_pnl = pnl - commission
            
            # Update balance
            self.current_balance += net_pnl
            
            # Record trade
            trade_record = {
                'position_id': position.position_id,
                'symbol': position.symbol,
                'direction': position.direction.value,
                'quantity': position.quantity,
                'entry_price': position.entry_price,
                'exit_price': exit_price,
                'entry_time': position.opened_at,
                'exit_time': timestamp,
                'pnl': net_pnl,
                'commission': commission,
                'reason': reason,
                'duration_hours': (timestamp - position.opened_at).total_seconds() / 3600
            }
            
            self.closed_trades.append(trade_record)
        
            # Track exit statistics
            if reason not in self.exit_statistics:
                self.exit_statistics[reason] = {'count': 0, 'total_pnl': 0.0}
            self.exit_statistics[reason]['count'] += 1
            self.exit_statistics[reason]['total_pnl'] += net_pnl
        
            # Visual PnL indicator
            pnl_color = "\033[92m" if net_pnl >= 0 else "\033[91m"
            pnl_str = f"{pnl_color}{net_pnl:+.2f}\033[0m"
            
            self.logger.info(
                f"[CLOSE] {position.symbol} | {position.direction.value} | PnL: {pnl_str} | {reason}"
            )
            
        except Exception as e:
            self.logger.error(f"Error closing position: {e}")
    
    def _close_all_positions(
        self, 
        market_data_dict: Dict[str, MarketData], 
        timestamp: datetime
    ) -> None:
        """Close all remaining positions at the end of backtest"""
        for position in list(self.positions.values()):
            if position.symbol in market_data_dict:
                self._close_position(
                    position, 
                    market_data_dict[position.symbol], 
                    timestamp, 
                    "End of Backtest"
                )
        self.positions.clear()
    
    def _calculate_position_size(self, signal: TradingSignal) -> float:
        """Calculate position size in lots based on signal and risk management
        
        FIXED SIZING: Always use 0.01 lots per signal for realistic backtesting.
        This prevents unrealistic compounding and matches typical demo account sizing.
        """
        # FIXED: Always 0.01 lots per signal (realistic sizing)
        # This eliminates dynamic scaling that causes unrealistic equity curves
        # and matches what you would use in live trading on a $10k account
        return 0.01  # Fixed 0.01 lots per trade
    
    def _update_equity(self) -> None:
        """Update current equity based on open positions"""
        unrealized_pnl = sum(pos.unrealized_pnl for pos in self.positions.values())
        self.current_equity = self.current_balance + unrealized_pnl
    
    def _calculate_results(self) -> BacktestResult:
        """Calculate final backtest results"""
        if not self.closed_trades:
            return BacktestResult()
        
        # Basic statistics
        total_trades = len(self.closed_trades)
        winning_trades = sum(1 for trade in self.closed_trades if trade['pnl'] > 0)
        losing_trades = total_trades - winning_trades
        
        total_pnl = sum(trade['pnl'] for trade in self.closed_trades)
        
        # Win/loss statistics
        wins = [trade['pnl'] for trade in self.closed_trades if trade['pnl'] > 0]
        losses = [trade['pnl'] for trade in self.closed_trades if trade['pnl'] < 0]
        
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        avg_win = sum(wins) / len(wins) if wins else 0.0
        avg_loss = sum(losses) / len(losses) if losses else 0.0
        
        # Profit factor
        gross_profit = sum(wins) if wins else 0.0
        gross_loss = abs(sum(losses)) if losses else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Calculate daily returns for Sharpe ratio
        daily_returns = self._calculate_daily_returns()
        sharpe_ratio = self._calculate_sharpe_ratio(daily_returns)
        
        # Calculate maximum drawdown duration
        max_dd_duration = self._calculate_max_drawdown_duration()
        
        return BacktestResult(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            total_pnl=total_pnl,
            max_drawdown=self.max_drawdown,
            max_drawdown_duration=max_dd_duration,
            sharpe_ratio=sharpe_ratio,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            trades=self.closed_trades.copy(),
            equity_curve=self.equity_curve.copy(),
            daily_returns=daily_returns
        )
    
    def _calculate_daily_returns(self) -> List[float]:
        """Calculate daily returns from equity curve"""
        if len(self.equity_curve) < 2:
            return []
        
        daily_returns = []
        prev_equity = self.equity_curve[0][1]
        
        for timestamp, equity in self.equity_curve[1:]:
            if prev_equity > 0:
                daily_return = (equity - prev_equity) / prev_equity
                daily_returns.append(daily_return)
            prev_equity = equity
        
        return daily_returns
    
    def _calculate_sharpe_ratio(self, daily_returns: List[float]) -> float:
        """Calculate Sharpe ratio from daily returns"""
        if not daily_returns:
            return 0.0
        
        import statistics
        
        mean_return = statistics.mean(daily_returns)
        if len(daily_returns) < 2:
            return 0.0
        
        std_return = statistics.stdev(daily_returns)
        if std_return == 0:
            return 0.0
        
        # Annualized Sharpe ratio (assuming 252 trading days)
        return (mean_return * 252) / (std_return * (252 ** 0.5))
    
    def _calculate_max_drawdown_duration(self) -> int:
        """Calculate maximum drawdown duration in days"""
        if not self.equity_curve:
            return 0
            
        peak = self.equity_curve[0][1]
        peak_date = self.equity_curve[0][0]
        max_duration = 0
        
        for timestamp, equity in self.equity_curve:
            if equity >= peak:
                peak = equity
                peak_date = timestamp
            else:
                current_duration = (timestamp - peak_date).days
                max_duration = max(max_duration, current_duration)
        
        return max_duration

    def get_exit_statistics(self) -> Dict[str, Dict[str, Any]]:
        """Return statistics on exit reasons"""
        return self.exit_statistics
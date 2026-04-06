"""
Fixed Enhanced Backtest Engine with Proper Price Tracking

Improves upon the standard enhanced backtest engine by:
- Using proper OHLC price data to detect exits
- Implementing intra-candle price simulation
- Tracking realistic exit prices
- Properly monitoring price movements
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from src.backtesting.backtest_engine import (
    BacktestEngine,
    BacktestConfig,
    BacktestResult,
    MarketSimulator
)
from src.backtesting.exit_condition_generator import ExitConditionGenerator
from src.models import MarketData, TradingSignal, Direction, Position


logger = logging.getLogger(__name__)


class FixedEnhancedBacktestEngine(BacktestEngine):
    """Enhanced backtest engine with proper price tracking and exits"""

    def __init__(
        self,
        config: BacktestConfig,
        exit_generator: Optional[ExitConditionGenerator] = None
    ):
        """
        Initialize fixed enhanced backtest engine.

        Args:
            config: Backtest configuration
            exit_generator: Exit condition generator with strategies
        """
        super().__init__(config)
        self.exit_generator = exit_generator
        
        # Multiple position support - list-based tracking
        self.positions_list = []  # List[Position] - all active positions
        self.position_meta = {}  # Dict[position_id, {'entry_price', 'entry_time', 'highest', 'lowest'}]
        
        self.exit_logs = []
        self.processed_signals = set()  # Track which signals we've processed

    def run_backtest(
        self,
        market_data: Dict[str, List[MarketData]],
        signals: List[TradingSignal]
    ) -> 'BacktestResult':
        """
        Run backtest with exit conditions and proper price tracking.

        Args:
            market_data: Dict of symbol -> market data list
            signals: List of trading signals

        Returns:
            BacktestResult with trade details
        """
        self.logger.info("Starting fixed backtest with proper price tracking")
        self.logger.info(
            f"Exit strategy: {self.exit_generator.get_summary() if self.exit_generator else 'None'}"
        )

        # Initialize tracking variables
        self.current_balance = self.config.initial_balance
        self.current_equity = self.config.initial_balance
        self.positions_list = []  # Reset to empty list
        self.position_meta = {}  # Reset metadata
        self.exit_logs = []
        self.result = BacktestResult()

        # Combine all market data chronologically
        all_candles = []
        for symbol, candles in market_data.items():
            for candle in candles:
                all_candles.append((symbol, candle))

        # Sort by timestamp
        all_candles.sort(key=lambda x: x[1].timestamp)

        # Process each candle
        for symbol, candle in all_candles:
            # 1. Update all positions with current candle data
            self._update_all_positions_from_candle(symbol, candle)

            # 2. Check and execute exit conditions on all positions
            self._check_exit_conditions_for_all(symbol, candle)

            # 3. Check entry signals
            self._process_entry_signals(symbol, candle, signals)

            # 4. Update equity curve
            self._update_equity_curve(candle)

        # Close any remaining positions
        self._close_remaining_positions()

        # Calculate results
        return self._calculate_results()

    def _update_all_positions_from_candle(
        self,
        symbol: str,
        candle: MarketData
    ) -> None:
        """Update all open positions with current candle data."""
        for position in self.positions_list:
            if position.symbol != symbol:
                continue
            
            meta = self.position_meta[position.position_id]
            
            # Track highest and lowest prices
            meta['highest'] = max(meta['highest'], candle.high)
            meta['lowest'] = min(meta['lowest'], candle.low)
            
            # Calculate unrealized P&L at close price
            entry_price = meta['entry_price']
            
            if position.direction == Direction.LONG:
                # Long position P&L
                pnl_pips = (candle.close - entry_price) * 10000
                position.unrealized_pnl = pnl_pips * position.quantity * 0.0001
            else:
                # Short position P&L
                pnl_pips = (entry_price - candle.close) * 10000
                position.unrealized_pnl = pnl_pips * position.quantity * 0.0001
            
            # Update current price
            position.current_price = candle.close
        
        # Update total equity
        total_unrealized = sum(p.unrealized_pnl for p in self.positions_list)
        self.current_equity = self.current_balance + total_unrealized

    def _check_exit_conditions_for_all(
        self,
        symbol: str,
        candle: MarketData
    ) -> None:
        """Check exit conditions for all positions on this symbol."""
        # Check all positions that match this symbol
        positions_to_close = []
        
        for position in self.positions_list:
            if position.symbol != symbol:
                continue
            
            if not self.exit_generator:
                continue
            
            meta = self.position_meta[position.position_id]
            entry_price = meta['entry_price']
            entry_time = meta['entry_time']
            
            # Check if any exit conditions are triggered
            exit_triggered, reason, condition_type = (
                self.exit_generator.check_all_conditions(
                    position,
                    candle,
                    entry_price,
                    entry_time
                )
            )
            
            if exit_triggered:
                exit_price = self._get_realistic_exit_price(
                    position,
                    candle,
                    entry_price,
                    condition_type,
                    meta
                )
                positions_to_close.append((position, exit_price, reason, condition_type, candle.timestamp))
        
        # Close positions (do it after iteration to avoid modifying list during iteration)
        for position, exit_price, reason, condition_type, timestamp in positions_to_close:
            self._close_position_fixed_v2(position, timestamp, exit_price, reason, condition_type)

    def _get_realistic_exit_price(
        self,
        position,
        candle: MarketData,
        entry_price: float,
        condition_type: str,
        meta: dict
    ) -> float:
        """
        Get realistic exit price based on condition and OHLC data.

        Args:
            position: The position being exited
            candle: Current candle data
            entry_price: Position entry price
            condition_type: Type of exit condition triggered
            meta: Metadata dict with highest/lowest prices

        Returns:
            Realistic exit price
        """
        if condition_type == 'take_profit':
            # Exit at take profit level if it was touched
            if position.direction == Direction.LONG:
                # For long, if high >= TP, exit at TP or high
                if position.take_profit:
                    if candle.high >= position.take_profit:
                        return position.take_profit
                return candle.high
            else:
                # For short, if low <= TP, exit at TP or low
                if position.take_profit:
                    if candle.low <= position.take_profit:
                        return position.take_profit
                return candle.low

        elif condition_type == 'stop_loss':
            # Exit at stop loss level if it was touched
            if position.direction == Direction.LONG:
                # For long, if low <= SL, exit at SL or low
                if position.stop_loss:
                    if candle.low <= position.stop_loss:
                        return position.stop_loss
                return candle.low
            else:
                # For short, if high >= SL, exit at SL or high
                if position.stop_loss:
                    if candle.high >= position.stop_loss:
                        return position.stop_loss
                return candle.high

        elif condition_type == 'trailing_stop':
            # Exit at current extreme price
            if position.direction == Direction.LONG:
                return meta['lowest']
            else:
                return meta['highest']

        # Default: close at current price
        return candle.close

    def _close_position_fixed_v2(
        self,
        position,
        exit_time: datetime,
        exit_price: float,
        reason: str,
        condition_type: str
    ) -> None:
        """Close a position with detailed logging (version 2 for list-based positions)."""
        meta = self.position_meta[position.position_id]
        entry_price = meta['entry_price']
        entry_time = meta['entry_time']

        # Calculate realized P&L
        if position.direction == Direction.LONG:
            pnl = (exit_price - entry_price) * position.quantity
        else:
            pnl = (entry_price - exit_price) * position.quantity

        # Update balance
        self.current_balance += pnl
        
        # Update equity with remaining positions
        total_unrealized = sum(
            p.unrealized_pnl for p in self.positions_list 
            if p.position_id != position.position_id
        )
        self.current_equity = self.current_balance + total_unrealized

        # Log exit
        exit_log = {
            'symbol': position.symbol,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'entry_time': entry_time,
            'exit_time': exit_time,
            'pnl': pnl,
            'direction': position.direction.value,
            'quantity': position.quantity,
            'reason': reason,
            'condition_type': condition_type,
            'duration': exit_time - entry_time
        }
        self.exit_logs.append(exit_log)

        self.logger.info(
            f"[CLOSE] {position.symbol}: {position.direction.value} @ {exit_price:.5f} | "
            f"PnL: {pnl:+.2f} | Reason: {reason}"
        )

        # Remove from active positions list and metadata
        self.positions_list.remove(position)
        del self.position_meta[position.position_id]

    def _process_entry_signals(
        self,
        symbol: str,
        market_data: MarketData,
        signals: List[TradingSignal]
    ) -> None:
        """Process entry signals and open new positions."""
        # Find matching signals
        matching_signals = [
            s for s in signals
            if s.symbol.replace('/', '') == symbol.replace('/', '')
            and s.timestamp <= market_data.timestamp
        ]

        if not matching_signals:
            return

        # Use the most recent signal
        signal = matching_signals[-1]

        # Skip if we already processed this signal
        signal_key = f"{symbol}_{signal.timestamp}"
        
        if signal_key in self.processed_signals:
            return
        
        self.processed_signals.add(signal_key)
        self._enter_position(symbol, market_data, signal)

    def _enter_position(
        self,
        symbol: str,
        market_data: MarketData,
        signal: TradingSignal
    ) -> None:
        """Enter a new position with risk-based position sizing."""
        entry_price = signal.entry_price

        # Calculate position size using risk-based approach
        # Risk per trade: 2% of balance (allows for multiple concurrent positions)
        risk_per_trade = self.current_balance * 0.02
        
        # Calculate risk distance (in currency terms, not pips)
        if signal.direction == Direction.LONG:
            risk_distance = entry_price - signal.stop_loss
        else:  # SHORT
            risk_distance = signal.stop_loss - entry_price
        
        # Position size = Risk Amount / Risk Distance per unit
        if risk_distance > 0:
            position_size = risk_distance / risk_distance  # Simplified: risk_per_trade / risk_distance
            # More aggressive sizing: multiply by leverage factor
            position_size = (risk_per_trade / risk_distance) * 1.5  # 1.5x leverage for good win rate
        else:
            position_size = self.current_balance * 0.01 / entry_price  # Fallback to 1%
        
        if position_size <= 0:
            return

        # Create position object with TP/SL from signal
        position_id = f"{symbol}_{market_data.timestamp.timestamp()}"
        position = Position(
            position_id=position_id,
            symbol=symbol,
            direction=signal.direction,
            quantity=position_size,
            entry_price=entry_price,
            current_price=entry_price,
            unrealized_pnl=0.0,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            opened_at=market_data.timestamp
        )

        # Add to list and metadata
        self.positions_list.append(position)
        self.position_meta[position_id] = {
            'entry_price': entry_price,
            'entry_time': market_data.timestamp,
            'highest': market_data.high,
            'lowest': market_data.low
        }

        self.logger.info(
            f"[ENTRY] {symbol}: {signal.direction.value} @ "
            f"{entry_price:.5f} | Size: {position_size:.4f} | "
            f"TP: {signal.take_profit:.5f} | SL: {signal.stop_loss:.5f} | "
            f"Risk: {risk_per_trade:.2f}"
        )

    def _update_equity_curve(self, candle: MarketData) -> None:
        """Update equity curve with current equity."""
        self.result.equity_curve.append(
            (candle.timestamp, self.current_equity)
        )

    def _close_remaining_positions(self) -> None:
        """Close any remaining open positions at market."""
        # Work with a copy since we'll be removing from the list
        positions_to_close = list(self.positions_list)

        for position in positions_to_close:
            meta = self.position_meta[position.position_id]
            entry_price = meta['entry_price']
            entry_time = meta['entry_time']

            # Use entry price as exit (no better data available)
            exit_price = entry_price

            # Calculate P&L
            if position.direction == Direction.LONG:
                pnl = (exit_price - entry_price) * position.quantity
            else:
                pnl = (entry_price - exit_price) * position.quantity

            self.current_balance += pnl

            self.logger.info(
                f"[CLOSE_REMAINING] {position.symbol}: @ {exit_price:.5f} | "
                f"PnL: {pnl:+.2f}"
            )

            # Log the exit
            exit_log = {
                'symbol': position.symbol,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'entry_time': entry_time,
                'exit_time': entry_time,  # Use entry_time for remaining positions
                'pnl': pnl,
                'direction': position.direction.value,
                'quantity': position.quantity,
                'reason': 'CLOSE_REMAINING',
                'condition_type': 'close_remaining',
                'duration': entry_time - entry_time  # Zero duration
            }
            self.exit_logs.append(exit_log)

            # Remove from list
            self.positions_list.remove(position)
            del self.position_meta[position.position_id]

    def _calculate_results(self) -> 'BacktestResult':
        """Calculate and return backtest results."""
        self.result.total_trades = len(self.exit_logs)
        self.result.trades = self.exit_logs

        # Calculate win rate
        wins = sum(1 for log in self.exit_logs if log['pnl'] > 0)
        self.result.winning_trades = wins
        self.result.losing_trades = self.result.total_trades - wins

        if self.result.total_trades > 0:
            self.result.win_rate = wins / self.result.total_trades

        # Calculate P&L
        self.result.total_pnl = sum(log['pnl'] for log in self.exit_logs)

        # Calculate profit factor
        gross_profit = sum(
            log['pnl'] for log in self.exit_logs
            if log['pnl'] > 0
        )
        gross_loss = abs(sum(
            log['pnl'] for log in self.exit_logs
            if log['pnl'] < 0
        ))

        if gross_loss > 0:
            self.result.profit_factor = gross_profit / gross_loss
        else:
            self.result.profit_factor = (
                float('inf') if gross_profit > 0 else 0.0
            )

        # Calculate max drawdown
        max_balance = self.current_balance
        max_drawdown = 0.0
        for _, equity in self.result.equity_curve:
            max_balance = max(max_balance, equity)
            if max_balance > 0:
                drawdown = (max_balance - equity) / max_balance
                max_drawdown = max(max_drawdown, drawdown)

        self.result.max_drawdown = max_drawdown
        self.result.final_balance = self.current_balance

        # Calculate exit statistics
        exit_stats = {}
        for log in self.exit_logs:
            condition_type = log['condition_type']
            if condition_type not in exit_stats:
                exit_stats[condition_type] = {
                    'count': 0,
                    'pnl': 0.0
                }
            exit_stats[condition_type]['count'] += 1
            exit_stats[condition_type]['pnl'] += log['pnl']

        self.result.exit_statistics = exit_stats

        return self.result

    def get_exit_statistics(self) -> Dict:
        """Get exit condition statistics."""
        stats = {}
        for log in self.exit_logs:
            condition_type = log['condition_type']
            if condition_type not in stats:
                stats[condition_type] = {
                    'count': 0,
                    'total_pnl': 0.0,
                    'avg_pnl': 0.0
                }
            stats[condition_type]['count'] += 1
            stats[condition_type]['total_pnl'] += log['pnl']

        # Calculate averages
        for condition_type in stats:
            if stats[condition_type]['count'] > 0:
                stats[condition_type]['avg_pnl'] = (
                    stats[condition_type]['total_pnl'] /
                    stats[condition_type]['count']
                )

        return stats


# Imports at top for clarity

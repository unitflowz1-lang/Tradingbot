"""
Enhanced Backtest Engine with Exit Condition Support
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

from src.backtesting.backtest_engine import (
    BacktestEngine as BaseBacktestEngine,
    BacktestConfig,
    BacktestResult,
    MarketSimulator
)
from src.backtesting.exit_condition_generator import (
    ExitConditionGenerator,
    ExitConditionType
)
from src.models import (
    MarketData,
    TradingSignal,
    Position,
    Direction,
    OrderType,
    OrderStatus
)


class EnhancedBacktestEngine(BaseBacktestEngine):
    """
    Enhanced backtest engine with exit condition support.
    Extends the base engine to include configurable exit strategies.
    """

    def __init__(
        self,
        config: BacktestConfig,
        exit_condition_generator: Optional[
            ExitConditionGenerator] = None
    ):
        super().__init__(config)
        self.exit_generator = (
            exit_condition_generator or
            ExitConditionGenerator())
        self.position_entry_times: Dict[str, datetime] = {}
        self.position_entry_prices: Dict[str, float] = {}
        self.position_history: Dict[str, List[MarketData]] = {}
        self.exit_logs: List[Dict[str, Any]] = []

        self.logger = logging.getLogger(__name__)

    def add_exit_strategy(
        self,
        generator: ExitConditionGenerator
    ) -> 'EnhancedBacktestEngine':
        """Set the exit condition generator"""
        self.exit_generator = generator
        return self

    def run_backtest(
        self,
        market_data: Dict[str, List[MarketData]],
        signals: List[TradingSignal]
    ) -> BacktestResult:
        """
        Run backtest with exit conditions.

        Args:
            market_data: Dict of symbol -> market data list
            signals: List of trading signals

        Returns:
            BacktestResult with trade details
        """
        self.logger.info("Starting enhanced backtest with exit conditions")
        self.logger.info(
            f"Exit strategy: {self.exit_generator.get_summary()}")

        # Initialize
        self.current_balance = self.config.initial_balance
        self.current_equity = self.config.initial_balance
        self.active_positions = {}
        self.closed_positions = []
        self.exit_logs = []
        self.result = BacktestResult()  # Initialize result early for equity_curve access

        # Combine all market data chronologically
        all_candles = []
        for symbol, candles in market_data.items():
            for candle in candles:
                all_candles.append((symbol, candle))

        # Sort by timestamp
        all_candles.sort(key=lambda x: x[1].timestamp)

        # Process each candle
        for symbol, candle in all_candles:
            # 1. Check exit conditions for existing positions
            self._check_exit_conditions(symbol, candle)

            # 2. Check entry signals
            self._process_entry_signals(symbol, candle, signals)

            # 3. Update portfolio
            self._update_portfolio_from_candle(candle)

        # Close any remaining positions at market
        self._close_remaining_positions()

        # Calculate results
        return self._calculate_results()

    def _check_exit_conditions(
        self,
        symbol: str,
        market_data: MarketData
    ) -> None:
        """Check if any positions should be exited"""
        if symbol not in self.active_positions:
            return

        position = self.active_positions[symbol]

        # Get position data
        entry_price = self.position_entry_prices.get(symbol)
        entry_time = self.position_entry_times.get(symbol)
        position_hist = self.position_history.get(
            symbol, [])

        if not entry_price or not entry_time:
            return

        # Check all exit conditions
        should_exit, reason, condition_type = (
            self.exit_generator.check_all_conditions(
                position, market_data, entry_price,
                entry_time, position_hist))

        if should_exit:
            self._exit_position(
                symbol, market_data, reason, condition_type)

        # Update position history
        if symbol not in self.position_history:
            self.position_history[symbol] = []
        self.position_history[symbol].append(market_data)

    def _exit_position(
        self,
        symbol: str,
        market_data: MarketData,
        reason: str,
        condition_type: Optional[ExitConditionType]
    ) -> None:
        """Exit a position"""
        if symbol not in self.active_positions:
            return

        position = self.active_positions[symbol]
        entry_price = self.position_entry_prices[symbol]
        entry_time = self.position_entry_times[symbol]

        # Calculate exit price with slippage
        simulator = MarketSimulator(self.config)
        exit_price, _ = simulator.calculate_execution_price(
            market_data, position.direction, OrderType.MARKET)

        # Calculate P&L
        if position.direction == Direction.LONG:
            pnl = (exit_price - entry_price) * position.quantity
        else:
            pnl = (entry_price - exit_price) * position.quantity

        # Log exit
        exit_log = {
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'entry_time': entry_time,
            'exit_time': market_data.timestamp,
            'pnl': pnl,
            'direction': position.direction.value,
            'quantity': position.quantity,
            'reason': reason,
            'condition_type': (
                condition_type.value if condition_type else 'unknown'),
            'duration': market_data.timestamp - entry_time
        }
        self.exit_logs.append(exit_log)

        # Update portfolio
        self.current_balance += pnl
        self.current_equity = self.current_balance

        # Log exit
        self.logger.info(
            f"[EXIT] {symbol}: {position.direction.value} @ "
            f"{exit_price:.5f} | PnL: {pnl:+.2f} | "
            f"Reason: {reason}")

        # Remove position
        del self.active_positions[symbol]
        del self.position_entry_prices[symbol]
        del self.position_entry_times[symbol]
        if symbol in self.position_history:
            del self.position_history[symbol]

        # Record closed position
        self.closed_positions.append({
            'symbol': symbol,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'pnl': pnl,
            'direction': position.direction.value,
            'duration': market_data.timestamp - entry_time
        })

    def _process_entry_signals(
        self,
        symbol: str,
        market_data: MarketData,
        signals: List[TradingSignal]
    ) -> None:
        """Process entry signals (from base class)"""
        if symbol in self.active_positions:
            return  # Already have position

        # Find matching signal
        matching_signal = None
        for signal in signals:
            if (signal.symbol == symbol and
                signal.timestamp <= market_data.timestamp):
                matching_signal = signal

        if not matching_signal:
            return

        # Enter position
        self._enter_position(symbol, market_data, matching_signal)

    def _enter_position(
        self,
        symbol: str,
        market_data: MarketData,
        signal: TradingSignal
    ) -> None:
        """Enter a new position"""
        simulator = MarketSimulator(self.config)
        entry_price, total_cost = simulator.calculate_execution_price(
            market_data, signal.direction, OrderType.MARKET)

        # Calculate position size
        position_size = (
            self.current_balance * 0.01 /
            (signal.position_size or 0.01))

        if position_size <= 0:
            return

        # Create position
        # At entry, current_price = entry_price, so unrealized_pnl = 0
        position = Position(
            position_id=f"{symbol}_{market_data.timestamp.timestamp()}",
            symbol=symbol,
            direction=signal.direction,
            quantity=position_size,
            entry_price=entry_price,
            current_price=entry_price,  # At entry, current equals entry
            unrealized_pnl=0.0,  # This will be 0 since current_price == entry_price
            stop_loss=None,
            take_profit=None,
            opened_at=market_data.timestamp
        )

        self.active_positions[symbol] = position
        self.position_entry_prices[symbol] = entry_price
        self.position_entry_times[symbol] = market_data.timestamp
        self.position_history[symbol] = [market_data]

        self.logger.info(
            f"[ENTRY] {symbol}: {signal.direction.value} @ "
            f"{entry_price:.5f} | Size: {position_size:.4f}")

    def _update_portfolio_from_candle(
        self,
        market_data: MarketData
    ) -> None:
        """Update portfolio values from candle data"""
        # Update active position P&L
        total_pnl = 0.0
        for symbol, position in self.active_positions.items():
            if position.symbol == market_data.symbol:
                entry_price = self.position_entry_prices[symbol]
                if position.direction == Direction.LONG:
                    position_pnl = (
                        (market_data.close - entry_price) *
                        position.quantity)
                else:
                    position_pnl = (
                        (entry_price - market_data.close) *
                        position.quantity)
                total_pnl += position_pnl

        self.current_equity = (
            self.current_balance + total_pnl)

        # Track equity curve
        self.result.equity_curve.append(
            (market_data.timestamp, self.current_equity))

    def _close_remaining_positions(self) -> None:
        """Close any remaining open positions at market"""
        symbols_to_close = list(self.active_positions.keys())

        for symbol in symbols_to_close:
            position = self.active_positions[symbol]
            entry_price = self.position_entry_prices[symbol]

            # Use last available price
            if symbol in self.result.trades:
                last_trade = self.result.trades[-1]
                exit_price = last_trade.get('exit_price', entry_price)
            else:
                exit_price = entry_price

            # Calculate final P&L
            if position.direction == Direction.LONG:
                pnl = (exit_price - entry_price) * position.quantity
            else:
                pnl = (entry_price - exit_price) * position.quantity

            self.current_balance += pnl

            # Log
            self.logger.info(
                f"[CLOSE_REMAINING] {symbol}: @ {exit_price:.5f} | "
                f"PnL: {pnl:+.2f}")

            del self.active_positions[symbol]

    def _calculate_results(self) -> BacktestResult:
        """Calculate backtest results"""
        # Create result from exit logs
        self.result = BacktestResult()
        self.result.total_trades = len(self.exit_logs)
        self.result.trades = self.exit_logs

        # Calculate win rate
        wins = sum(1 for log in self.exit_logs if log['pnl'] > 0)
        self.result.winning_trades = wins
        self.result.losing_trades = self.result.total_trades - wins

        if self.result.total_trades > 0:
            self.result.win_rate = (
                wins / self.result.total_trades)

        # Calculate P&L
        self.result.total_pnl = sum(
            log['pnl'] for log in self.exit_logs)

        # Calculate profit factor
        gross_profit = sum(
            log['pnl'] for log in self.exit_logs
            if log['pnl'] > 0)
        gross_loss = abs(sum(
            log['pnl'] for log in self.exit_logs
            if log['pnl'] < 0))

        if gross_loss > 0:
            self.result.profit_factor = gross_profit / gross_loss
        else:
            self.result.profit_factor = (
                float('inf') if gross_profit > 0 else 0.0)

        # Calculate max drawdown
        max_balance = self.current_balance
        max_drawdown = 0.0
        for _, equity in self.result.equity_curve:
            max_balance = max(max_balance, equity)
            drawdown = (max_balance - equity) / max_balance
            max_drawdown = max(max_drawdown, drawdown)

        self.result.max_drawdown = max_drawdown

        # Calculate averages
        if wins > 0:
            self.result.avg_win = (
                sum(log['pnl'] for log in self.exit_logs
                    if log['pnl'] > 0) / wins)

        if self.result.losing_trades > 0:
            self.result.avg_loss = (
                sum(log['pnl'] for log in self.exit_logs
                    if log['pnl'] < 0) /
                self.result.losing_trades)

        self.logger.info(f"Backtest results: {self.result}")

        return self.result

    def get_exit_statistics(self) -> Dict[str, Any]:
        """Get statistics about exit conditions"""
        exit_counts = {}
        exit_pnl = {}

        for log in self.exit_logs:
            exit_type = log['condition_type']
            exit_counts[exit_type] = exit_counts.get(exit_type, 0) + 1
            exit_pnl[exit_type] = (
                exit_pnl.get(exit_type, 0.0) + log['pnl'])

        return {
            'total_exits': len(self.exit_logs),
            'exit_counts': exit_counts,
            'exit_pnl': exit_pnl,
            'exit_logs': self.exit_logs
        }

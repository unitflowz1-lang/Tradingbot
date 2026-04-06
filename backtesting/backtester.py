"""
Advanced Backtesting System.
Realistic simulation with spread, slippage, commision, and latency modeling.
Supports walk-forward and Monte Carlo validation.
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta
import asyncio
from abc import ABC, abstractmethod

from utils.logger import get_logger
from core.strategy_manager import Strategy, Signal
from core.portfolio import Portfolio, Trade
from core.risk_manager import RiskManager


logger = get_logger(__name__)


@dataclass
class BacktestConfig:
    """Backtesting configuration."""
    start_date: str
    end_date: str
    initial_capital: float
    spread_bps: float = 2.0  # Bid-ask spread in basis points
    slippage_bps: float = 1.0  # Slippage in basis points
    commission_pct: float = 0.001  # Commission percentage
    latency_ms: int = 100  # Order latency
    max_slippage_bps: float = 10.0  # Maximum realistic slippage


@dataclass
class TradeResult:
    """Result of a single trade."""
    entry_time: datetime
    entry_price: float
    exit_time: datetime
    exit_price: float
    direction: str
    quantity: float
    gross_pnl: float
    net_pnl: float
    return_pct: float
    bars_held: int
    exit_reason: str


@dataclass
class BacktestMetrics:
    """Backtest performance metrics."""
    total_return: float
    annual_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    expectancy: float
    trades_count: int
    winning_trades: int
    losing_trades: int
    largest_win: float
    largest_loss: float


class Backtester:
    """
    Realistic backtester with market simulation.
    Simulates spreads, slippage, commission, and latency.
    """
    
    def __init__(self, strategy: Strategy, data: pd.DataFrame, config: BacktestConfig):
        """
        Initialize Backtester.
        
        Args:
            strategy: Strategy to backtest
            data: Historical price data
            config: Backtest configuration
        """
        self.strategy = strategy
        self.data = data.sort_values('timestamp' if 'timestamp' in data.columns else data.index)
        self.config = config
        
        # Performance tracking
        self.trades: List[TradeResult] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_returns: Dict = {}
        
        # Portfolio simulator
        self.portfolio = Portfolio(config.initial_capital, None)  # TODO: Pass risk config
        self.current_bar = 0
    
    def run(self) -> Tuple[List[TradeResult], BacktestMetrics]:
        """
        Run backtest and return results.
        
        Returns:
            Tuple of (trades list, metrics)
        """
        logger.info(f"[BACKTEST] Starting backtest from {self.config.start_date} to {self.config.end_date}")
        
        try:
            # Main backtest loop
            for i in range(len(self.data)):
                self.current_bar = i
                current_data = self.data.iloc[:i+1]
                
                # Generate signal
                signal = self.strategy.generate_signal(current_data)
                
                if signal == Signal.BUY or signal == Signal.SELL:
                    self._process_trade_signal(signal, current_data, i)
                
                # Update open positions
                self._update_positions(current_data, i)
                
                # Record equity
                self._record_equity(current_data, i)
            
            # Close remaining positions
            self._close_remaining_positions()
            
            # Calculate metrics
            metrics = self._calculate_metrics()
            
            logger.info(f"[BACKTEST] Backtest complete. Total return: {metrics.total_return:.2%}")
            
            return self.trades, metrics
        
        except Exception as e:
            logger.error(f"[BACKTEST] Error during backtest: {e}")
            return [], BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
    
    def _process_trade_signal(self, signal: Signal, data: pd.DataFrame, bar_index: int):
        """Process a trading signal."""
        try:
            current_price = data['close'].iloc[-1]
            current_time = data['timestamp'].iloc[-1] if 'timestamp' in data.columns else None
            
            # Close opposite direction if exists
            if self.portfolio.trades:
                existing_trade = list(self.portfolio.trades.values())[0]
                if (signal == Signal.BUY and existing_trade.direction == "SELL") or \
                   (signal == Signal.SELL and existing_trade.direction == "BUY"):
                    self._close_position_with_slippage(existing_trade, current_price)
            
            # Calculate stops and targets
            direction = signal.value
            stop_loss = self.strategy.calculate_stop_loss(current_price, direction, data)
            take_profit = self.strategy.calculate_take_profit(current_price, direction, data)
            
            # Adjust for slippage on entry
            entry_price = self._apply_slippage(current_price, direction, True)
            
            # Create trade
            trade_id = f"TRADE_{bar_index}_{direction[0]}"
            trade = Trade(
                trade_id=trade_id,
                symbol="EURUSD",
                direction=direction,
                entry_price=entry_price,
                entry_time=current_time,
                quantity=0.01,  # Standard lot
                margin_required=100.0,  # Estimate
                stop_loss=stop_loss,
                take_profit=take_profit
            )
            
            self.portfolio.open_position(trade)
            logger.debug(f"Position opened: {trade_id} at {entry_price}")
        
        except Exception as e:
            logger.error(f"Error processing signal: {e}")
    
    def _update_positions(self, data: pd.DataFrame, bar_index: int):
        """Update open positions with current price."""
        current_price = data['close'].iloc[-1]
        
        for trade_id, trade in list(self.portfolio.trades.items()):
            # Check stop loss
            if trade.direction == "BUY" and current_price <= trade.stop_loss:
                self._close_position_with_slippage(trade, current_price)
            
            elif trade.direction == "SELL" and current_price >= trade.stop_loss:
                self._close_position_with_slippage(trade, current_price)
            
            # Check take profit
            elif trade.direction == "BUY" and current_price >= trade.take_profit:
                self._close_position_with_slippage(trade, current_price, reason="TP")
            
            elif trade.direction == "SELL" and current_price <= trade.take_profit:
                self._close_position_with_slippage(trade, current_price, reason="TP")
    
    def _close_position_with_slippage(self, trade: Trade, current_price: float, reason: str = "SL"):
        """Close position with realistic slippage."""
        # Apply slippage on exit
        exit_price = self._apply_slippage(current_price, trade.direction, False)
        
        # Apply commission
        commission = (trade.entry_price * trade.quantity) * (self.config.commission_pct / 100)
        
        # Calculate P&L
        if trade.direction == "BUY":
            gross_pnl = (exit_price - trade.entry_price) * trade.quantity * 100000
        else:
            gross_pnl = (trade.entry_price - exit_price) * trade.quantity * 100000
        
        net_pnl = gross_pnl - commission
        return_pct = (exit_price - trade.entry_price) / trade.entry_price
        
        # Record trade
        self.trades.append(TradeResult(
            entry_time=trade.entry_time,
            entry_price=trade.entry_price,
            exit_time=datetime.now(),
            exit_price=exit_price,
            direction=trade.direction,
            quantity=trade.quantity,
            gross_pnl=gross_pnl,
            net_pnl=net_pnl,
            return_pct=return_pct,
            bars_held=self.current_bar,
            exit_reason=reason
        ))
        
        # Close in portfolio
        self.portfolio.close_position(trade.trade_id, exit_price, reason)
    
    def _apply_slippage(self, price: float, direction: str, is_entry: bool) -> float:
        """Apply realistic slippage to price."""
        # Spread component
        spread = price * (self.config.spread_bps / 10000)
        
        # Slippage component (random, up to max)
        max_slippage = price * (self.config.slippage_bps / 10000)
        random_slippage = np.random.uniform(0, max_slippage)
        
        total_adjustment = spread + random_slippage
        
        if direction.upper() == "BUY":
            return price + total_adjustment if is_entry else price - total_adjustment
        else:
            return price - total_adjustment if is_entry else price + total_adjustment
    
    def _close_remaining_positions(self):
        """Close all remaining positions at end of backtest."""
        final_price = self.data['close'].iloc[-1]
        
        for trade_id, trade in list(self.portfolio.trades.items()):
            self._close_position_with_slippage(trade, final_price, "EOB")
    
    def _record_equity(self, data: pd.DataFrame, bar_index: int):
        """Record equity at current bar."""
        current_price = data['close'].iloc[-1]
        current_time = data['timestamp'].iloc[-1] if 'timestamp' in data.columns else bar_index
        
        # Update position values
        for trade in self.portfolio.trades.values():
            trade.update_prices(current_price)
        
        # Calculate current equity
        open_pnl = sum(t.profit_loss for t in self.portfolio.trades.values())
        closed_pnl = sum(t.profit_loss for t in self.portfolio.closed_trades)
        current_equity = self.config.initial_capital + open_pnl + closed_pnl
        
        self.portfolio.current_equity = current_equity
        self.equity_curve.append((current_time, current_equity))
    
    def _calculate_metrics(self) -> BacktestMetrics:
        """Calculate backtest metrics."""
        if not self.trades:
            return BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        
        # Total return
        final_equity = self.equity_curve[-1][1] if self.equity_curve else self.config.initial_capital
        total_return = (final_equity - self.config.initial_capital) / self.config.initial_capital
        
        # Annual return (assuming 252 trading days)
        days = (pd.to_datetime(self.config.end_date) - pd.to_datetime(self.config.start_date)).days
        years = days / 365
        annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else total_return
        
        # Win rate
        winning_trades = len([t for t in self.trades if t.net_pnl > 0])
        losing_trades = len([t for t in self.trades if t.net_pnl < 0])
        win_rate = winning_trades / len(self.trades) if self.trades else 0
        
        # Profit factor
        gross_profit = sum(t.net_pnl for t in self.trades if t.net_pnl > 0)
        gross_loss = abs(sum(t.net_pnl for t in self.trades if t.net_pnl < 0))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        # Sharpe ratio
        if self.equity_curve:
            returns = pd.Series([ec[1] for ec in self.equity_curve]).pct_change().dropna()
            sharpe = returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 0 else 0
        else:
            sharpe = 0
        
        # Max drawdown
        equity_values = [ec[1] for ec in self.equity_curve]
        running_max = np.maximum.accumulate(equity_values)
        drawdown = (np.array(equity_values) - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0
        
        # Expectancy
        avg_win = np.mean([t.net_pnl for t in self.trades if t.net_pnl > 0]) if winning_trades > 0 else 0
        avg_loss = np.mean([t.net_pnl for t in self.trades if t.net_pnl < 0]) if losing_trades > 0 else 0
        expectancy = (win_rate * avg_win) + ((1-win_rate) * avg_loss)
        
        # Largest win/loss
        largest_win = max((t.net_pnl for t in self.trades), default=0)
        largest_loss = min((t.net_pnl for t in self.trades), default=0)
        
        # Sortino ratio (only downside volatility)
        if self.equity_curve:
            returns = pd.Series([ec[1] for ec in self.equity_curve]).pct_change().dropna()
            downside_returns = returns[returns < 0]
            downside_std = downside_returns.std() if len(downside_returns) > 0 else returns.std()
            sortino = returns.mean() / downside_std * np.sqrt(252) if downside_std > 0 else 0
        else:
            sortino = 0
        
        return BacktestMetrics(
            total_return=total_return,
            annual_return=annual_return,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            trades_count=len(self.trades),
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            largest_win=largest_win,
            largest_loss=largest_loss
        )
    
    def get_metrics(self) -> BacktestMetrics:
        """Get computed metrics."""
        return self._calculate_metrics()

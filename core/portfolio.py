"""
Portfolio management module.
Tracks positions, capital allocation, correlation exposure, and metrics.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
from utils.logger import get_logger


logger = get_logger(__name__)


@dataclass
class Trade:
    """Represents a trade/position."""
    trade_id: str
    symbol: str
    direction: str  # BUY or SELL
    entry_price: float
    entry_time: datetime
    quantity: float
    margin_required: float
    
    stop_loss: float = 0.0
    take_profit: float = 0.0
    
    trailing_stop: bool = False
    trailing_distance: float = 0.0
    highest_price: float = 0.0
    lowest_price: float = 0.0
    
    profit_loss: float = 0.0
    profit_loss_pct: float = 0.0
    
    status: str = "open"  # open, pending, closed
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    
    def update_prices(self, current_price: float):
        """Update trade prices and profit/loss."""
        if self.direction == "BUY":
            self.profit_loss = (current_price - self.entry_price) * self.quantity
            self.highest_price = max(self.highest_price or current_price, current_price)
        else:
            self.profit_loss = (self.entry_price - current_price) * self.quantity
            self.lowest_price = min(self.lowest_price or current_price, current_price)
        
        self.profit_loss_pct = (self.profit_loss / (self.entry_price * self.quantity)) * 100 \
            if self.entry_price * self.quantity != 0 else 0


@dataclass
class PortfolioMetrics:
    """Portfolio performance metrics."""
    total_equity: float = 0.0
    available_margin: float = 0.0
    used_margin: float = 0.0
    margin_utilization: float = 0.0
    
    total_profit_loss: float = 0.0
    total_return: float = 0.0
    
    open_trades: int = 0
    closed_trades: int = 0
    
    win_rate: float = 0.0
    profit_factor: float = 0.0
    
    largest_win: float = 0.0
    largest_loss: float = 0.0
    
    max_drawdown: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0


class Portfolio:
    """
    Portfolio manager.
    Tracks positions, capital allocation, and correlation exposure.
    """
    
    def __init__(self, initial_capital: float, risk_config):
        """
        Initialize Portfolio.
        
        Args:
            initial_capital: Starting account balance
            risk_config: Risk configuration
        """
        self.initial_capital = initial_capital
        self.current_equity = initial_capital
        self.risk_config = risk_config
        
        # Positions and trades
        self.trades: Dict[str, Trade] = {}
        self.closed_trades: List[Trade] = []
        
        # Metrics
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.daily_pnl: Dict[datetime, float] = {}
        
        # Correlation matrix (pairs to correlations)
        self.correlation_matrix: Dict[str, Dict[str, float]] = {}
    
    def open_position(self, trade: Trade) -> bool:
        """
        Open a new position.
        
        Args:
            trade: Trade object
        
        Returns:
            True if position opened, False if rejected
        """
        # Check max positions
        if len(self.trades) >= self.risk_config.max_open_trades:
            logger.warning("Max positions reached", max_positions=self.risk_config.max_open_trades)
            return False
        
        # Check margin
        if trade.margin_required > self.available_margin():
            logger.warning("Insufficient margin", required=trade.margin_required, 
                          available=self.available_margin())
            return False
        
        # Check correlation if configured
        if not self._check_correlation(trade.symbol):
            logger.warning("Correlation limit exceeded", symbol=trade.symbol)
            return False
        
        # Open position
        self.trades[trade.trade_id] = trade
        logger.info("Position opened", trade_id=trade.trade_id, symbol=trade.symbol,
                   direction=trade.direction, price=trade.entry_price)
        
        return True
    
    def close_position(self, trade_id: str, exit_price: float, exit_reason: str = "") -> bool:
        """
        Close a position.
        
        Args:
            trade_id: Trade ID to close
            exit_price: Exit price
            exit_reason: Reason for exit
        
        Returns:
            True if closed successfully
        """
        if trade_id not in self.trades:
            logger.error("Trade not found", trade_id=trade_id)
            return False
        
        trade = self.trades[trade_id]
        trade.status = "closed"
        trade.exit_price = exit_price
        trade.exit_time = datetime.now()
        trade.exit_reason = exit_reason
        
        # Calculate final P&L
        if trade.direction == "BUY":
            trade.profit_loss = (exit_price - trade.entry_price) * trade.quantity
        else:
            trade.profit_loss = (trade.entry_price - exit_price) * trade.quantity
        
        trade.profit_loss_pct = (trade.profit_loss / (trade.entry_price * trade.quantity)) * 100 \
            if trade.entry_price * trade.quantity != 0 else 0
        
        # Move to closed trades
        self.closed_trades.append(trade)
        del self.trades[trade_id]
        
        logger.info("Position closed", trade_id=trade_id, symbol=trade.symbol,
                   exit_price=exit_price, profit_loss=trade.profit_loss)
        
        return True
    
    def update_position(self, trade_id: str, current_price: float):
        """Update position prices and metrics."""
        if trade_id not in self.trades:
            return
        
        trade = self.trades[trade_id]
        trade.update_prices(current_price)
    
    def available_margin(self) -> float:
        """Get available margin for new positions."""
        used_margin = sum(t.margin_required for t in self.trades.values())
        max_margin = self.current_equity * (self.risk_config.max_position_size or 0.8)
        return max_margin - used_margin
    
    def margin_utilization(self) -> float:
        """Get current margin utilization percentage."""
        used_margin = sum(t.margin_required for t in self.trades.values())
        if self.current_equity == 0:
            return 0.0
        return (used_margin / self.current_equity) * 100
    
    def current_drawdown(self) -> float:
        """Calculate current drawdown from peak equity."""
        if not self.equity_curve:
            return 0.0
        
        max_equity = max(eq for _, eq in self.equity_curve)
        return ((self.current_equity - max_equity) / max_equity) * 100 \
            if max_equity != 0 else 0
    
    def get_metrics(self) -> PortfolioMetrics:
        """Get current portfolio metrics."""
        metrics = PortfolioMetrics()
        metrics.total_equity = self.current_equity
        metrics.used_margin = sum(t.margin_required for t in self.trades.values())
        metrics.available_margin = self.available_margin()
        metrics.margin_utilization = self.margin_utilization()
        
        metrics.open_trades = len(self.trades)
        metrics.closed_trades = len(self.closed_trades)
        
        # Calculate returns
        metrics.total_profit_loss = sum(t.profit_loss for t in self.trades.values()) + \
                                    sum(t.profit_loss for t in self.closed_trades)
        metrics.total_return = (metrics.total_profit_loss / self.initial_capital) * 100
        
        # Win rate
        if self.closed_trades:
            winning_trades = len([t for t in self.closed_trades if t.profit_loss > 0])
            metrics.win_rate = (winning_trades / len(self.closed_trades)) * 100
        
        # Profit factor
        gross_profit = sum(t.profit_loss for t in self.closed_trades if t.profit_loss > 0)
        gross_loss = abs(sum(t.profit_loss for t in self.closed_trades if t.profit_loss < 0))
        metrics.profit_factor = gross_profit / gross_loss if gross_loss != 0 else 0
        
        # Max/Min
        if self.closed_trades:
            metrics.largest_win = max(
                (t.profit_loss for t in self.closed_trades),
                default=0
            )
            metrics.largest_loss = min(
                (t.profit_loss for t in self.closed_trades),
                default=0
            )
        
        metrics.max_drawdown = self.current_drawdown()
        
        return metrics
    
    def _check_correlation(self, new_symbol: str) -> bool:
        """
        Check if adding position in new_symbol violates correlation limits.
        
        Args:
            new_symbol: Symbol to check correlation for
        
        Returns:
            True if correlation check passes
        """
        if not self.risk_config.max_correlated_exposure:
            return True
        
        # Count existing correlated positions
        if new_symbol not in self.correlation_matrix:
            return True
        
        correlated_count = 0
        for open_symbol in [t.symbol for t in self.trades.values()]:
            if open_symbol in self.correlation_matrix.get(new_symbol, {}):
                corr = self.correlation_matrix[new_symbol][open_symbol]
                if abs(corr) > 0.7:  # High correlation threshold
                    correlated_count += 1
        
        return correlated_count < self.risk_config.max_correlated_exposure
    
    def update_correlation_matrix(self, price_data: Dict[str, pd.DataFrame]):
        """Update correlation matrix between pairs."""
        symbols = list(price_data.keys())
        
        for i, symbol1 in enumerate(symbols):
            if symbol1 not in self.correlation_matrix:
                self.correlation_matrix[symbol1] = {}
            
            for symbol2 in symbols[i+1:]:
                try:
                    df1 = price_data[symbol1]['close']
                    df2 = price_data[symbol2]['close']
                    
                    # Align indices and calculate correlation
                    aligned = pd.concat([df1, df2], axis=1, join='inner')
                    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
                    
                    self.correlation_matrix[symbol1][symbol2] = corr
                    self.correlation_matrix[symbol2][symbol1] = corr
                except Exception as e:
                    logger.error(f"Error calculating correlation: {e}",
                               symbol1=symbol1, symbol2=symbol2)

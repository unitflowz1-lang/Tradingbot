"""
Comprehensive Performance Tracking System

This module provides real-time performance metrics calculation for RL agents,
performance dashboard data collection, and comparative analysis capabilities.
"""

from typing import Dict, List, Any, Optional, Tuple, Union
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict, deque
import json
from pathlib import Path
from dataclasses import dataclass, asdict
import threading
import time

from .metrics import MetricsTracker
from .logger import RLLogger


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics for RL agents."""
    # Return metrics
    total_return: float
    annualized_return: float
    cumulative_return: float
    
    # Risk metrics
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    calmar_ratio: float
    max_drawdown: float
    current_drawdown: float
    
    # Trade metrics
    win_rate: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    num_trades: int
    avg_trade_duration: float
    
    # Advanced metrics
    information_ratio: float
    treynor_ratio: float
    jensen_alpha: float
    beta: float
    
    # Timestamp
    timestamp: datetime
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class TradeRecord:
    """Individual trade record for analysis."""
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    position_size: float
    pnl: Optional[float]
    duration: Optional[float]
    currency_pair: str
    agent_id: str
    strategy_id: str
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class PerformanceTracker:
    """
    Comprehensive performance tracking system for RL agents.
    
    Provides real-time performance metrics calculation, comparative analysis,
    and dashboard data collection for monitoring RL agent performance.
    """
    
    def __init__(self, 
                 agent_id: str,
                 benchmark_return: float = 0.02,  # 2% annual risk-free rate
                 update_frequency: int = 100,  # Update every N trades
                 save_dir: Optional[str] = None,
                 logger: Optional[RLLogger] = None):
        
        self.agent_id = agent_id
        self.benchmark_return = benchmark_return
        self.update_frequency = update_frequency
        self.save_dir = Path(save_dir) if save_dir else Path("data/performance")
        self.logger = logger or RLLogger()
        
        # Performance data
        self.trades: List[TradeRecord] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.returns_series: List[Tuple[datetime, float]] = []
        self.drawdown_series: List[Tuple[datetime, float]] = []
        
        # Real-time metrics
        self.current_metrics: Optional[PerformanceMetrics] = None
        self.metrics_history: List[PerformanceMetrics] = []
        
        # Portfolio state
        self.initial_capital: float = 100000.0  # Default $100k
        self.current_equity: float = self.initial_capital
        self.peak_equity: float = self.initial_capital
        self.open_positions: Dict[str, TradeRecord] = {}
        
        # Comparative data
        self.benchmark_data: List[Tuple[datetime, float]] = []
        self.strategy_comparisons: Dict[str, List[PerformanceMetrics]] = {}
        
        # Threading for real-time updates
        self._lock = threading.Lock()
        self._update_counter = 0
        
        # Create save directory
        self.save_dir.mkdir(parents=True, exist_ok=True)
        
    def record_trade_entry(self, 
                          entry_time: datetime,
                          entry_price: float,
                          position_size: float,
                          currency_pair: str,
                          strategy_id: str = "default") -> str:
        """
        Record trade entry.
        
        Returns:
            Trade ID for tracking
        """
        with self._lock:
            trade_id = f"{self.agent_id}_{entry_time.timestamp()}_{currency_pair}"
            
            trade = TradeRecord(
                entry_time=entry_time,
                exit_time=None,
                entry_price=entry_price,
                exit_price=None,
                position_size=position_size,
                pnl=None,
                duration=None,
                currency_pair=currency_pair,
                agent_id=self.agent_id,
                strategy_id=strategy_id
            )
            
            self.open_positions[trade_id] = trade
            
            self.logger.log_system_event(
                "trade_entry",
                f"Trade opened: {currency_pair}",
                {
                    "trade_id": trade_id,
                    "entry_price": entry_price,
                    "position_size": position_size,
                    "strategy_id": strategy_id
                }
            )
            
            return trade_id
    
    def record_trade_exit(self, 
                         trade_id: str,
                         exit_time: datetime,
                         exit_price: float) -> Optional[TradeRecord]:
        """
        Record trade exit and calculate P&L.
        
        Returns:
            Completed trade record
        """
        with self._lock:
            if trade_id not in self.open_positions:
                self.logger.log_error(
                    "trade_exit_error",
                    f"Trade ID not found: {trade_id}"
                )
                return None
                
            trade = self.open_positions.pop(trade_id)
            trade.exit_time = exit_time
            trade.exit_price = exit_price
            
            # Calculate P&L 
            # For forex: P&L = (exit_price - entry_price) * position_size
            # Position size should be in base currency units
            price_change = exit_price - trade.entry_price
            trade.pnl = price_change * trade.position_size
            
            # Calculate duration
            trade.duration = (exit_time - trade.entry_time).total_seconds() / 3600  # Hours
            
            # Update equity
            self.current_equity += trade.pnl
            self.peak_equity = max(self.peak_equity, self.current_equity)
            
            # Add to completed trades
            self.trades.append(trade)
            
            # Update equity curve
            self.equity_curve.append((exit_time, self.current_equity))
            
            # Calculate return
            if len(self.equity_curve) > 1:
                prev_equity = self.equity_curve[-2][1]
                period_return = (self.current_equity - prev_equity) / prev_equity
                self.returns_series.append((exit_time, period_return))
            
            # Update drawdown
            current_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity
            self.drawdown_series.append((exit_time, current_drawdown))
            
            self.logger.log_system_event(
                "trade_exit",
                f"Trade closed: {trade.currency_pair}",
                {
                    "trade_id": trade_id,
                    "exit_price": exit_price,
                    "pnl": trade.pnl,
                    "duration": trade.duration,
                    "current_equity": self.current_equity
                }
            )
            
            # Update metrics if needed
            self._update_counter += 1
            if self._update_counter % self.update_frequency == 0:
                self._calculate_metrics()
                
            return trade
    
    def update_equity(self, timestamp: datetime, equity: float) -> None:
        """Update equity value (for mark-to-market)."""
        with self._lock:
            self.current_equity = equity
            self.peak_equity = max(self.peak_equity, equity)
            
            # Update curves
            self.equity_curve.append((timestamp, equity))
            
            # Calculate return
            if len(self.equity_curve) > 1:
                prev_equity = self.equity_curve[-2][1]
                period_return = (equity - prev_equity) / prev_equity
                self.returns_series.append((timestamp, period_return))
            
            # Update drawdown
            current_drawdown = (self.peak_equity - equity) / self.peak_equity
            self.drawdown_series.append((timestamp, current_drawdown))
    
    def _calculate_metrics(self) -> PerformanceMetrics:
        """Calculate comprehensive performance metrics."""
        if not self.trades and not self.returns_series:
            return self._create_empty_metrics()
            
        timestamp = datetime.now()
        
        # Basic return metrics
        total_return = (self.current_equity - self.initial_capital) / self.initial_capital
        
        # Time-based calculations
        if self.equity_curve:
            start_time = self.equity_curve[0][0]
            end_time = self.equity_curve[-1][0]
            time_diff = (end_time - start_time).days / 365.25  # Years
            
            if time_diff > 0:
                annualized_return = (1 + total_return) ** (1 / time_diff) - 1
            else:
                annualized_return = 0.0
        else:
            annualized_return = 0.0
            
        cumulative_return = total_return
        
        # Risk metrics
        returns = [r[1] for r in self.returns_series] if self.returns_series else [0]
        volatility = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0.0  # Annualized
        
        # Sharpe ratio
        excess_return = annualized_return - self.benchmark_return
        sharpe_ratio = excess_return / volatility if volatility > 0 else 0.0
        
        # Sortino ratio (downside deviation)
        negative_returns = [r for r in returns if r < 0]
        downside_deviation = np.std(negative_returns) * np.sqrt(252) if negative_returns else 0.0
        sortino_ratio = excess_return / downside_deviation if downside_deviation > 0 else 0.0
        
        # Drawdown metrics
        drawdowns = [d[1] for d in self.drawdown_series] if self.drawdown_series else [0]
        max_drawdown = max(drawdowns) if drawdowns else 0.0
        current_drawdown = drawdowns[-1] if drawdowns else 0.0
        
        # Calmar ratio
        calmar_ratio = annualized_return / max_drawdown if max_drawdown > 0 else 0.0
        
        # Trade metrics
        if self.trades:
            winning_trades = [t for t in self.trades if t.pnl and t.pnl > 0]
            losing_trades = [t for t in self.trades if t.pnl and t.pnl < 0]
            
            win_rate = len(winning_trades) / len(self.trades)
            
            avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0.0
            avg_loss = np.mean([abs(t.pnl) for t in losing_trades]) if losing_trades else 0.0
            
            profit_factor = abs(avg_win * len(winning_trades)) / abs(avg_loss * len(losing_trades)) if losing_trades else float('inf')
            
            avg_trade_duration = np.mean([t.duration for t in self.trades if t.duration]) if self.trades else 0.0
        else:
            win_rate = 0.0
            avg_win = 0.0
            avg_loss = 0.0
            profit_factor = 0.0
            avg_trade_duration = 0.0
        
        # Advanced metrics (simplified calculations)
        information_ratio = sharpe_ratio  # Simplified
        treynor_ratio = excess_return / 1.0  # Assuming beta = 1
        jensen_alpha = annualized_return - self.benchmark_return  # Simplified
        beta = 1.0  # Simplified assumption
        
        metrics = PerformanceMetrics(
            total_return=total_return,
            annualized_return=annualized_return,
            cumulative_return=cumulative_return,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            win_rate=win_rate,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            num_trades=len(self.trades),
            avg_trade_duration=avg_trade_duration,
            information_ratio=information_ratio,
            treynor_ratio=treynor_ratio,
            jensen_alpha=jensen_alpha,
            beta=beta,
            timestamp=timestamp
        )
        
        self.current_metrics = metrics
        self.metrics_history.append(metrics)
        
        # Log metrics update
        self.logger.log_metrics("performance_update", metrics.to_dict(), timestamp)
        
        return metrics
    
    def _create_empty_metrics(self) -> PerformanceMetrics:
        """Create empty metrics for initialization."""
        return PerformanceMetrics(
            total_return=0.0,
            annualized_return=0.0,
            cumulative_return=0.0,
            volatility=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            calmar_ratio=0.0,
            max_drawdown=0.0,
            current_drawdown=0.0,
            win_rate=0.0,
            profit_factor=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            num_trades=0,
            avg_trade_duration=0.0,
            information_ratio=0.0,
            treynor_ratio=0.0,
            jensen_alpha=0.0,
            beta=1.0,
            timestamp=datetime.now()
        )
    
    def get_current_metrics(self) -> PerformanceMetrics:
        """Get current performance metrics."""
        if self.current_metrics is None:
            return self._calculate_metrics()
        return self.current_metrics
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for performance dashboard."""
        metrics = self.get_current_metrics()
        
        return {
            "agent_id": self.agent_id,
            "current_metrics": metrics.to_dict(),
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": equity}
                for ts, equity in self.equity_curve[-100:]  # Last 100 points
            ],
            "returns_series": [
                {"timestamp": ts.isoformat(), "return": ret}
                for ts, ret in self.returns_series[-100:]
            ],
            "drawdown_series": [
                {"timestamp": ts.isoformat(), "drawdown": dd}
                for ts, dd in self.drawdown_series[-100:]
            ],
            "recent_trades": [
                trade.to_dict() for trade in self.trades[-10:]  # Last 10 trades
            ],
            "open_positions": len(self.open_positions),
            "last_update": datetime.now().isoformat()
        }
    
    def compare_with_strategy(self, strategy_id: str, other_metrics: PerformanceMetrics) -> Dict[str, Any]:
        """Compare performance with another strategy."""
        current = self.get_current_metrics()
        
        comparison = {
            "agent_id": self.agent_id,
            "strategy_id": strategy_id,
            "comparison_timestamp": datetime.now().isoformat(),
            "metrics_comparison": {
                "total_return": {
                    "current": current.total_return,
                    "other": other_metrics.total_return,
                    "difference": current.total_return - other_metrics.total_return
                },
                "sharpe_ratio": {
                    "current": current.sharpe_ratio,
                    "other": other_metrics.sharpe_ratio,
                    "difference": current.sharpe_ratio - other_metrics.sharpe_ratio
                },
                "max_drawdown": {
                    "current": current.max_drawdown,
                    "other": other_metrics.max_drawdown,
                    "difference": current.max_drawdown - other_metrics.max_drawdown
                },
                "win_rate": {
                    "current": current.win_rate,
                    "other": other_metrics.win_rate,
                    "difference": current.win_rate - other_metrics.win_rate
                }
            },
            "performance_score": self._calculate_performance_score(current, other_metrics)
        }
        
        return comparison
    
    def _calculate_performance_score(self, current: PerformanceMetrics, other: PerformanceMetrics) -> float:
        """Calculate relative performance score."""
        # Weighted scoring system
        weights = {
            "return": 0.3,
            "sharpe": 0.3,
            "drawdown": 0.2,  # Lower is better
            "win_rate": 0.2
        }
        
        score = 0.0
        
        # Return comparison
        if other.total_return != 0:
            return_ratio = current.total_return / other.total_return
            score += weights["return"] * min(return_ratio, 2.0)  # Cap at 2x
        
        # Sharpe comparison
        if other.sharpe_ratio != 0:
            sharpe_ratio = current.sharpe_ratio / other.sharpe_ratio
            score += weights["sharpe"] * min(sharpe_ratio, 2.0)
        
        # Drawdown comparison (inverted - lower is better)
        if other.max_drawdown != 0:
            drawdown_ratio = other.max_drawdown / max(current.max_drawdown, 0.001)
            score += weights["drawdown"] * min(drawdown_ratio, 2.0)
        
        # Win rate comparison
        if other.win_rate != 0:
            win_rate_ratio = current.win_rate / other.win_rate
            score += weights["win_rate"] * min(win_rate_ratio, 2.0)
        
        return score
    
    def save_performance_data(self, filename: Optional[str] = None) -> str:
        """Save performance data to file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"performance_{self.agent_id}_{timestamp}.json"
        
        filepath = self.save_dir / filename
        
        data = {
            "agent_id": self.agent_id,
            "initial_capital": self.initial_capital,
            "current_equity": self.current_equity,
            "peak_equity": self.peak_equity,
            "trades": [trade.to_dict() for trade in self.trades],
            "equity_curve": [
                {"timestamp": ts.isoformat(), "equity": equity}
                for ts, equity in self.equity_curve
            ],
            "returns_series": [
                {"timestamp": ts.isoformat(), "return": ret}
                for ts, ret in self.returns_series
            ],
            "metrics_history": [metrics.to_dict() for metrics in self.metrics_history],
            "current_metrics": self.current_metrics.to_dict() if self.current_metrics else None,
            "save_timestamp": datetime.now().isoformat()
        }
        
        # Convert datetime objects to strings for JSON serialization
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
            
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=convert_datetime)
        
        self.logger.log_system_event(
            "performance_data_saved",
            f"Performance data saved to {filepath}",
            {"filename": filename, "num_trades": len(self.trades)}
        )
        
        return str(filepath)
    
    def load_performance_data(self, filename: str) -> None:
        """Load performance data from file."""
        filepath = self.save_dir / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"Performance data file not found: {filepath}")
        
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Restore data
        self.initial_capital = data.get("initial_capital", 100000.0)
        self.current_equity = data.get("current_equity", self.initial_capital)
        self.peak_equity = data.get("peak_equity", self.initial_capital)
        
        # Restore trades
        self.trades = []
        for trade_data in data.get("trades", []):
            trade = TradeRecord(**trade_data)
            # Convert string timestamps back to datetime
            trade.entry_time = datetime.fromisoformat(trade_data["entry_time"])
            if trade_data.get("exit_time"):
                trade.exit_time = datetime.fromisoformat(trade_data["exit_time"])
            self.trades.append(trade)
        
        # Restore curves
        self.equity_curve = [
            (datetime.fromisoformat(item["timestamp"]), item["equity"])
            for item in data.get("equity_curve", [])
        ]
        
        self.returns_series = [
            (datetime.fromisoformat(item["timestamp"]), item["return"])
            for item in data.get("returns_series", [])
        ]
        
        # Restore metrics
        if data.get("current_metrics"):
            metrics_data = data["current_metrics"]
            metrics_data["timestamp"] = datetime.fromisoformat(metrics_data["timestamp"])
            self.current_metrics = PerformanceMetrics(**metrics_data)
        
        self.logger.log_system_event(
            "performance_data_loaded",
            f"Performance data loaded from {filepath}",
            {"num_trades": len(self.trades)}
        )
    
    def reset(self) -> None:
        """Reset all performance data."""
        with self._lock:
            self.trades.clear()
            self.equity_curve.clear()
            self.returns_series.clear()
            self.drawdown_series.clear()
            self.open_positions.clear()
            self.metrics_history.clear()
            
            self.current_equity = self.initial_capital
            self.peak_equity = self.initial_capital
            self.current_metrics = None
            self._update_counter = 0
        
        self.logger.log_system_event("performance_tracker_reset", "Performance tracker reset")
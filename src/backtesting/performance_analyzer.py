"""Performance metrics and analysis for backtesting results"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from src.backtesting.backtest_engine import BacktestResult


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics"""
    # Basic metrics
    total_return: float = 0.0
    annualized_return: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    # Risk metrics
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    volatility: float = 0.0
    
    # Trade analysis
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0
    
    # Advanced metrics
    var_95: float = 0.0  # Value at Risk (95%)
    var_99: float = 0.0  # Value at Risk (99%)
    beta: float = 0.0  # Beta vs benchmark
    alpha: float = 0.0  # Alpha vs benchmark
    information_ratio: float = 0.0
    
    # Time-based analysis
    avg_trade_duration: float = 0.0  # in hours
    avg_time_in_market: float = 0.0  # percentage
    monthly_returns: Dict[str, float] = field(default_factory=dict)
    
    # Risk-adjusted returns
    return_over_max_dd: float = 0.0
    sterling_ratio: float = 0.0
    burke_ratio: float = 0.0


@dataclass
class TradeAnalysis:
    """Detailed trade-by-trade analysis"""
    trade_id: str
    symbol: str
    direction: str
    entry_time: datetime
    exit_time: datetime
    duration_hours: float
    entry_price: float
    exit_price: float
    quantity: float
    pnl: float
    pnl_percentage: float
    commission: float
    net_pnl: float
    reason: str
    
    # Performance attribution
    market_return: float = 0.0  # Market movement during trade
    alpha_return: float = 0.0   # Excess return vs market
    timing_score: float = 0.0   # Entry/exit timing quality


class PerformanceAnalyzer:
    """Analyzer for calculating comprehensive performance metrics"""
    
    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.logger = logging.getLogger(__name__)
    
    def analyze_performance(
        self, 
        backtest_result: BacktestResult,
        benchmark_returns: Optional[List[float]] = None,
        risk_free_rate: float = 0.02  # 2% annual risk-free rate
    ) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics
        
        Args:
            backtest_result: Results from backtest
            benchmark_returns: Optional benchmark returns for comparison
            risk_free_rate: Annual risk-free rate for Sharpe calculation
            
        Returns:
            PerformanceMetrics object with all calculated metrics
        """
        if not backtest_result.trades:
            return PerformanceMetrics()
        
        metrics = PerformanceMetrics()
        
        # Basic metrics
        metrics.total_trades = backtest_result.total_trades
        metrics.winning_trades = backtest_result.winning_trades
        metrics.losing_trades = backtest_result.losing_trades
        metrics.win_rate = backtest_result.win_rate
        metrics.avg_win = backtest_result.avg_win
        metrics.avg_loss = backtest_result.avg_loss
        metrics.profit_factor = backtest_result.profit_factor
        
        # Calculate returns
        final_balance = self.initial_balance + backtest_result.total_pnl
        metrics.total_return = (final_balance - self.initial_balance) / self.initial_balance
        
        # Calculate time-based metrics
        start_date = min(trade['entry_time'] for trade in backtest_result.trades)
        end_date = max(trade['exit_time'] for trade in backtest_result.trades)
        total_days = (end_date - start_date).days
        
        if total_days > 0:
            metrics.annualized_return = (
                (1 + metrics.total_return) ** (365.25 / total_days) - 1
            )
        
        # Risk metrics
        metrics.max_drawdown = backtest_result.max_drawdown
        metrics.max_drawdown_duration = backtest_result.max_drawdown_duration
        metrics.sharpe_ratio = self._calculate_sharpe_ratio(
            backtest_result.daily_returns, risk_free_rate
        )
        metrics.sortino_ratio = self._calculate_sortino_ratio(
            backtest_result.daily_returns, risk_free_rate
        )
        metrics.calmar_ratio = self._calculate_calmar_ratio(
            metrics.annualized_return, metrics.max_drawdown
        )
        
        # Volatility
        if backtest_result.daily_returns:
            metrics.volatility = statistics.stdev(backtest_result.daily_returns) * (252 ** 0.5)
        
        # Trade analysis
        pnls = [trade['pnl'] for trade in backtest_result.trades]
        if pnls:
            metrics.largest_win = max(pnls)
            metrics.largest_loss = min(pnls)
            metrics.expectancy = statistics.mean(pnls)
        
        # Value at Risk
        if backtest_result.daily_returns:
            sorted_returns = sorted(backtest_result.daily_returns)
            if len(sorted_returns) >= 20:  # Need sufficient data
                metrics.var_95 = sorted_returns[int(len(sorted_returns) * 0.05)]
                metrics.var_99 = sorted_returns[int(len(sorted_returns) * 0.01)]
        
        # Trade duration analysis
        durations = [trade['duration_hours'] for trade in backtest_result.trades]
        if durations:
            metrics.avg_trade_duration = statistics.mean(durations)
        
        # Time in market
        total_time_in_market = sum(durations)
        total_period_hours = total_days * 24
        if total_period_hours > 0:
            metrics.avg_time_in_market = total_time_in_market / total_period_hours
        
        # Monthly returns
        metrics.monthly_returns = self._calculate_monthly_returns(backtest_result.equity_curve)
        
        # Risk-adjusted metrics
        if metrics.max_drawdown > 0:
            metrics.return_over_max_dd = metrics.total_return / metrics.max_drawdown
            metrics.sterling_ratio = metrics.annualized_return / metrics.max_drawdown
        
        # Benchmark comparison
        if benchmark_returns:
            metrics.beta, metrics.alpha = self._calculate_beta_alpha(
                backtest_result.daily_returns, benchmark_returns, risk_free_rate
            )
            metrics.information_ratio = self._calculate_information_ratio(
                backtest_result.daily_returns, benchmark_returns
            )
        
        return metrics
    
    def analyze_trades(
        self, 
        backtest_result: BacktestResult,
        market_data: Optional[Dict[str, List[Any]]] = None
    ) -> List[TradeAnalysis]:
        """
        Perform detailed trade-by-trade analysis
        
        Args:
            backtest_result: Results from backtest
            market_data: Optional market data for performance attribution
            
        Returns:
            List of TradeAnalysis objects
        """
        trade_analyses = []
        
        for i, trade in enumerate(backtest_result.trades):
            analysis = TradeAnalysis(
                trade_id=f"trade_{i}",
                symbol=trade['symbol'],
                direction=trade['direction'],
                entry_time=trade['entry_time'],
                exit_time=trade['exit_time'],
                duration_hours=trade['duration_hours'],
                entry_price=trade['entry_price'],
                exit_price=trade['exit_price'],
                quantity=trade['quantity'],
                pnl=trade['pnl'],
                pnl_percentage=self._calculate_pnl_percentage(trade),
                commission=trade.get('commission', 0.0),
                net_pnl=trade['pnl'],
                reason=trade.get('reason', 'Unknown')
            )
            
            # Performance attribution if market data available
            if market_data and trade['symbol'] in market_data:
                analysis.market_return = self._calculate_market_return(
                    trade, market_data[trade['symbol']]
                )
                analysis.alpha_return = analysis.pnl_percentage - analysis.market_return
                analysis.timing_score = self._calculate_timing_score(trade)
            
            trade_analyses.append(analysis)
        
        return trade_analyses
    
    def generate_performance_report(
        self, 
        metrics: PerformanceMetrics,
        trade_analyses: Optional[List[TradeAnalysis]] = None
    ) -> Dict[str, Any]:
        """
        Generate comprehensive performance report
        
        Args:
            metrics: Performance metrics
            trade_analyses: Optional detailed trade analysis
            
        Returns:
            Dictionary containing formatted performance report
        """
        report = {
            'summary': {
                'total_return': f"{metrics.total_return:.2%}",
                'annualized_return': f"{metrics.annualized_return:.2%}",
                'sharpe_ratio': f"{metrics.sharpe_ratio:.2f}",
                'max_drawdown': f"{metrics.max_drawdown:.2%}",
                'win_rate': f"{metrics.win_rate:.2%}",
                'profit_factor': f"{metrics.profit_factor:.2f}"
            },
            'risk_metrics': {
                'volatility': f"{metrics.volatility:.2%}",
                'sortino_ratio': f"{metrics.sortino_ratio:.2f}",
                'calmar_ratio': f"{metrics.calmar_ratio:.2f}",
                'var_95': f"{metrics.var_95:.2%}",
                'var_99': f"{metrics.var_99:.2%}",
                'max_drawdown_duration': f"{metrics.max_drawdown_duration} days"
            },
            'trade_analysis': {
                'total_trades': metrics.total_trades,
                'winning_trades': metrics.winning_trades,
                'losing_trades': metrics.losing_trades,
                'avg_win': f"${metrics.avg_win:.2f}",
                'avg_loss': f"${metrics.avg_loss:.2f}",
                'largest_win': f"${metrics.largest_win:.2f}",
                'largest_loss': f"${metrics.largest_loss:.2f}",
                'expectancy': f"${metrics.expectancy:.2f}",
                'avg_trade_duration': f"{metrics.avg_trade_duration:.1f} hours"
            },
            'advanced_metrics': {
                'beta': f"{metrics.beta:.2f}",
                'alpha': f"{metrics.alpha:.2%}",
                'information_ratio': f"{metrics.information_ratio:.2f}",
                'return_over_max_dd': f"{metrics.return_over_max_dd:.2f}",
                'sterling_ratio': f"{metrics.sterling_ratio:.2f}",
                'avg_time_in_market': f"{metrics.avg_time_in_market:.2%}"
            }
        }
        
        # Add monthly returns
        if metrics.monthly_returns:
            report['monthly_returns'] = {
                month: f"{return_val:.2%}" 
                for month, return_val in metrics.monthly_returns.items()
            }
        
        # Add trade details if available
        if trade_analyses:
            report['top_trades'] = {
                'best_trades': [
                    {
                        'symbol': trade.symbol,
                        'direction': trade.direction,
                        'pnl': f"${trade.pnl:.2f}",
                        'pnl_percentage': f"{trade.pnl_percentage:.2%}",
                        'duration': f"{trade.duration_hours:.1f}h"
                    }
                    for trade in sorted(trade_analyses, key=lambda x: x.pnl, reverse=True)[:5]
                ],
                'worst_trades': [
                    {
                        'symbol': trade.symbol,
                        'direction': trade.direction,
                        'pnl': f"${trade.pnl:.2f}",
                        'pnl_percentage': f"{trade.pnl_percentage:.2%}",
                        'duration': f"{trade.duration_hours:.1f}h"
                    }
                    for trade in sorted(trade_analyses, key=lambda x: x.pnl)[:5]
                ]
            }
        
        return report
    
    def _calculate_sharpe_ratio(
        self, 
        daily_returns: List[float], 
        risk_free_rate: float
    ) -> float:
        """Calculate Sharpe ratio"""
        if not daily_returns or len(daily_returns) < 2:
            return 0.0
        
        mean_return = statistics.mean(daily_returns)
        std_return = statistics.stdev(daily_returns)
        
        if std_return == 0:
            return 0.0
        
        # Convert annual risk-free rate to daily
        daily_rf_rate = risk_free_rate / 252
        
        # Annualized Sharpe ratio
        return (mean_return - daily_rf_rate) * (252 ** 0.5) / (std_return * (252 ** 0.5))
    
    def _calculate_sortino_ratio(
        self, 
        daily_returns: List[float], 
        risk_free_rate: float
    ) -> float:
        """Calculate Sortino ratio (uses downside deviation)"""
        if not daily_returns:
            return 0.0
        
        mean_return = statistics.mean(daily_returns)
        daily_rf_rate = risk_free_rate / 252
        
        # Calculate downside deviation
        negative_returns = [r for r in daily_returns if r < daily_rf_rate]
        if not negative_returns:
            return float('inf') if mean_return > daily_rf_rate else 0.0
        
        if len(negative_returns) < 2:
            # If only one negative return, use it as the downside deviation
            downside_deviation = abs(negative_returns[0] - daily_rf_rate)
        else:
            downside_deviation = statistics.stdev(negative_returns)
        
        if downside_deviation == 0:
            return 0.0
        
        return (mean_return - daily_rf_rate) * (252 ** 0.5) / (downside_deviation * (252 ** 0.5))
    
    def _calculate_calmar_ratio(self, annualized_return: float, max_drawdown: float) -> float:
        """Calculate Calmar ratio"""
        if max_drawdown == 0:
            return float('inf') if annualized_return > 0 else 0.0
        return annualized_return / max_drawdown
    
    def _calculate_beta_alpha(
        self, 
        strategy_returns: List[float], 
        benchmark_returns: List[float],
        risk_free_rate: float
    ) -> Tuple[float, float]:
        """Calculate beta and alpha vs benchmark"""
        if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 2:
            return 0.0, 0.0
        
        # Calculate excess returns
        daily_rf_rate = risk_free_rate / 252
        strategy_excess = [r - daily_rf_rate for r in strategy_returns]
        benchmark_excess = [r - daily_rf_rate for r in benchmark_returns]
        
        # Calculate beta using covariance and variance
        if len(strategy_excess) < 2:
            return 0.0, 0.0
        
        try:
            covariance = statistics.covariance(strategy_excess, benchmark_excess)
            benchmark_variance = statistics.variance(benchmark_excess)
            
            if benchmark_variance == 0:
                return 0.0, 0.0
            
            beta = covariance / benchmark_variance
            
            # Calculate alpha
            strategy_mean = statistics.mean(strategy_excess)
            benchmark_mean = statistics.mean(benchmark_excess)
            alpha = strategy_mean - (beta * benchmark_mean)
            
            # Annualize alpha
            alpha_annualized = alpha * 252
            
            return beta, alpha_annualized
            
        except statistics.StatisticsError:
            return 0.0, 0.0
    
    def _calculate_information_ratio(
        self, 
        strategy_returns: List[float], 
        benchmark_returns: List[float]
    ) -> float:
        """Calculate information ratio"""
        if len(strategy_returns) != len(benchmark_returns) or len(strategy_returns) < 2:
            return 0.0
        
        # Calculate excess returns
        excess_returns = [s - b for s, b in zip(strategy_returns, benchmark_returns)]
        
        if not excess_returns:
            return 0.0
        
        mean_excess = statistics.mean(excess_returns)
        
        if len(excess_returns) < 2:
            return 0.0
        
        std_excess = statistics.stdev(excess_returns)
        
        if std_excess == 0:
            return 0.0
        
        return (mean_excess * (252 ** 0.5)) / (std_excess * (252 ** 0.5))
    
    def _calculate_monthly_returns(
        self, 
        equity_curve: List[Tuple[datetime, float]]
    ) -> Dict[str, float]:
        """Calculate monthly returns from equity curve"""
        if not equity_curve:
            return {}
        
        monthly_returns = {}
        monthly_equity = {}
        
        # Group equity by month
        for timestamp, equity in equity_curve:
            month_key = timestamp.strftime("%Y-%m")
            if month_key not in monthly_equity:
                monthly_equity[month_key] = []
            monthly_equity[month_key].append(equity)
        
        # Calculate monthly returns
        prev_month_end = None
        for month_key in sorted(monthly_equity.keys()):
            month_start = monthly_equity[month_key][0]
            month_end = monthly_equity[month_key][-1]
            
            if prev_month_end is not None:
                monthly_return = (month_end - prev_month_end) / prev_month_end
                monthly_returns[month_key] = monthly_return
            
            prev_month_end = month_end
        
        return monthly_returns
    
    def _calculate_pnl_percentage(self, trade: Dict[str, Any]) -> float:
        """Calculate PnL as percentage of trade value"""
        entry_value = abs(trade['entry_price'] * trade['quantity'])
        if entry_value == 0:
            return 0.0
        return trade['pnl'] / entry_value
    
    def _calculate_market_return(
        self, 
        trade: Dict[str, Any], 
        market_data: List[Any]
    ) -> float:
        """Calculate market return during trade period"""
        # This is a simplified implementation
        # In practice, you'd match the exact timestamps
        entry_time = trade['entry_time']
        exit_time = trade['exit_time']
        
        # Find market data points closest to trade times
        entry_price = trade['entry_price']  # Fallback
        exit_price = trade['exit_price']    # Fallback
        
        # Calculate market return
        if entry_price != 0:
            return (exit_price - entry_price) / entry_price
        return 0.0
    
    def _calculate_timing_score(self, trade: Dict[str, Any]) -> float:
        """Calculate timing quality score (simplified)"""
        # This is a placeholder for more sophisticated timing analysis
        # Could include factors like:
        # - Entry timing relative to trend
        # - Exit timing relative to reversal points
        # - Volatility at entry/exit
        
        duration_hours = trade['duration_hours']
        pnl_percentage = self._calculate_pnl_percentage(trade)
        
        # Simple score based on PnL per hour
        if duration_hours > 0:
            return pnl_percentage / duration_hours
        return 0.0
"""Report generation system for comprehensive performance and strategy analysis"""

import json
import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path

from src.models import Position, Order, TradingSignal, MarketData
from src.backtesting.performance_analyzer import PerformanceMetrics, TradeAnalysis
from src.monitoring.performance_monitor import PerformanceMonitor


class ReportType(Enum):
    """Types of reports that can be generated"""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"
    CUSTOM = "custom"


class ReportFormat(Enum):
    """Output formats for reports"""
    JSON = "json"
    HTML = "html"
    PDF = "pdf"
    CSV = "csv"
    MARKDOWN = "md"


@dataclass
class PerformanceReport:
    """Performance report data structure"""
    report_id: str
    report_type: ReportType
    period_start: datetime
    period_end: datetime
    generated_at: datetime
    
    # Summary metrics
    total_return: float = 0.0
    annualized_return: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    
    # Detailed metrics
    metrics: Optional[PerformanceMetrics] = None
    trade_analysis: List[TradeAnalysis] = field(default_factory=list)
    
    # Risk analysis
    var_95: float = 0.0
    var_99: float = 0.0
    beta: float = 0.0
    alpha: float = 0.0
    
    # Period comparisons
    previous_period_return: Optional[float] = None
    return_change: Optional[float] = None
    
    # Additional data
    top_performing_pairs: List[Dict[str, Any]] = field(default_factory=list)
    worst_performing_pairs: List[Dict[str, Any]] = field(default_factory=list)
    monthly_breakdown: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary"""
        return {
            'report_id': self.report_id,
            'report_type': self.report_type.value,
            'period_start': self.period_start.isoformat(),
            'period_end': self.period_end.isoformat(),
            'generated_at': self.generated_at.isoformat(),
            'summary': {
                'total_return': self.total_return,
                'annualized_return': self.annualized_return,
                'total_trades': self.total_trades,
                'winning_trades': self.winning_trades,
                'losing_trades': self.losing_trades,
                'win_rate': self.win_rate,
                'profit_factor': self.profit_factor,
                'sharpe_ratio': self.sharpe_ratio,
                'max_drawdown': self.max_drawdown
            },
            'risk_metrics': {
                'var_95': self.var_95,
                'var_99': self.var_99,
                'beta': self.beta,
                'alpha': self.alpha
            },
            'period_comparison': {
                'previous_period_return': self.previous_period_return,
                'return_change': self.return_change
            },
            'analysis': {
                'top_performing_pairs': self.top_performing_pairs,
                'worst_performing_pairs': self.worst_performing_pairs,
                'monthly_breakdown': self.monthly_breakdown
            },
            'trade_details': [
                {
                    'trade_id': trade.trade_id,
                    'symbol': trade.symbol,
                    'direction': trade.direction,
                    'pnl': trade.pnl,
                    'pnl_percentage': trade.pnl_percentage,
                    'duration_hours': trade.duration_hours,
                    'entry_time': trade.entry_time.isoformat(),
                    'exit_time': trade.exit_time.isoformat()
                }
                for trade in self.trade_analysis
            ]
        }


@dataclass
class StrategyReport:
    """Strategy performance and analysis report"""
    strategy_name: str
    report_period: Tuple[datetime, datetime]
    generated_at: datetime
    
    # Strategy metrics
    signal_accuracy: float = 0.0
    signal_frequency: float = 0.0  # signals per day
    execution_rate: float = 0.0    # executed / generated
    avg_confidence: float = 0.0
    
    # Performance by signal type
    sentiment_performance: Dict[str, float] = field(default_factory=dict)
    technical_performance: Dict[str, float] = field(default_factory=dict)
    combined_performance: Dict[str, float] = field(default_factory=dict)
    
    # Market condition analysis
    trending_market_performance: float = 0.0
    ranging_market_performance: float = 0.0
    volatile_market_performance: float = 0.0
    
    # Time-based analysis
    hourly_performance: Dict[int, float] = field(default_factory=dict)
    daily_performance: Dict[str, float] = field(default_factory=dict)
    
    # Recommendations
    recommendations: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert strategy report to dictionary"""
        return {
            'strategy_name': self.strategy_name,
            'report_period': [
                self.report_period[0].isoformat(),
                self.report_period[1].isoformat()
            ],
            'generated_at': self.generated_at.isoformat(),
            'signal_metrics': {
                'accuracy': self.signal_accuracy,
                'frequency': self.signal_frequency,
                'execution_rate': self.execution_rate,
                'avg_confidence': self.avg_confidence
            },
            'performance_by_type': {
                'sentiment': self.sentiment_performance,
                'technical': self.technical_performance,
                'combined': self.combined_performance
            },
            'market_conditions': {
                'trending': self.trending_market_performance,
                'ranging': self.ranging_market_performance,
                'volatile': self.volatile_market_performance
            },
            'time_analysis': {
                'hourly': self.hourly_performance,
                'daily': self.daily_performance
            },
            'recommendations': self.recommendations
        }


@dataclass
class RiskReport:
    """Risk analysis and monitoring report"""
    report_period: Tuple[datetime, datetime]
    generated_at: datetime
    
    # Risk metrics
    current_exposure: float = 0.0
    max_exposure_reached: float = 0.0
    avg_position_size: float = 0.0
    max_position_size: float = 0.0
    
    # Drawdown analysis
    current_drawdown: float = 0.0
    max_drawdown: float = 0.0
    drawdown_periods: List[Dict[str, Any]] = field(default_factory=list)
    
    # Risk violations
    risk_violations: List[Dict[str, Any]] = field(default_factory=list)
    stop_loss_effectiveness: float = 0.0
    take_profit_effectiveness: float = 0.0
    
    # Correlation analysis
    pair_correlations: Dict[str, float] = field(default_factory=dict)
    concentration_risk: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert risk report to dictionary"""
        return {
            'report_period': [
                self.report_period[0].isoformat(),
                self.report_period[1].isoformat()
            ],
            'generated_at': self.generated_at.isoformat(),
            'exposure_metrics': {
                'current_exposure': self.current_exposure,
                'max_exposure_reached': self.max_exposure_reached,
                'avg_position_size': self.avg_position_size,
                'max_position_size': self.max_position_size
            },
            'drawdown_analysis': {
                'current_drawdown': self.current_drawdown,
                'max_drawdown': self.max_drawdown,
                'drawdown_periods': self.drawdown_periods
            },
            'risk_management': {
                'risk_violations': self.risk_violations,
                'stop_loss_effectiveness': self.stop_loss_effectiveness,
                'take_profit_effectiveness': self.take_profit_effectiveness
            },
            'correlation_analysis': {
                'pair_correlations': self.pair_correlations,
                'concentration_risk': self.concentration_risk
            }
        }


class ReportGenerator:
    """Comprehensive report generation system"""
    
    def __init__(self, 
                 performance_monitor: Optional[PerformanceMonitor] = None,
                 output_directory: str = "reports"):
        self.performance_monitor = performance_monitor
        self.output_directory = Path(output_directory)
        self.output_directory.mkdir(exist_ok=True)
        
        self.logger = logging.getLogger(__name__)
        
        # Report templates and configurations
        self._report_configs = {
            ReportType.DAILY: {'lookback_days': 1, 'comparison_days': 1},
            ReportType.WEEKLY: {'lookback_days': 7, 'comparison_days': 7},
            ReportType.MONTHLY: {'lookback_days': 30, 'comparison_days': 30},
            ReportType.QUARTERLY: {'lookback_days': 90, 'comparison_days': 90},
            ReportType.ANNUAL: {'lookback_days': 365, 'comparison_days': 365}
        }
    
    def generate_performance_report(
        self,
        report_type: ReportType,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        trades_data: Optional[List[Dict[str, Any]]] = None,
        metrics: Optional[PerformanceMetrics] = None
    ) -> PerformanceReport:
        """
        Generate comprehensive performance report
        
        Args:
            report_type: Type of report to generate
            start_date: Start date for report period
            end_date: End date for report period
            trades_data: Historical trades data
            metrics: Performance metrics
            
        Returns:
            PerformanceReport object
        """
        # Determine report period
        if not end_date:
            end_date = datetime.now(timezone.utc)
        
        if not start_date:
            config = self._report_configs.get(report_type, {'lookback_days': 30})
            start_date = end_date - timedelta(days=config['lookback_days'])
        
        # Generate unique report ID
        report_id = f"{report_type.value}_{start_date.strftime('%Y%m%d')}_{end_date.strftime('%Y%m%d')}"
        
        # Create report structure
        report = PerformanceReport(
            report_id=report_id,
            report_type=report_type,
            period_start=start_date,
            period_end=end_date,
            generated_at=datetime.now(timezone.utc)
        )
        
        # Get current metrics from performance monitor if available
        if self.performance_monitor:
            current_metrics = self.performance_monitor.get_current_metrics()
            report.total_trades = current_metrics.total_trades
            report.winning_trades = current_metrics.winning_trades
            report.losing_trades = current_metrics.losing_trades
            report.win_rate = current_metrics.win_rate
            report.profit_factor = current_metrics.profit_factor
            report.sharpe_ratio = current_metrics.sharpe_ratio
            report.max_drawdown = current_metrics.max_drawdown
            report.total_return = current_metrics.total_pnl / 10000.0  # Assuming 10k initial balance
        
        # Use provided metrics if available
        if metrics:
            report.metrics = metrics
            report.total_return = metrics.total_return
            report.annualized_return = metrics.annualized_return
            report.sharpe_ratio = metrics.sharpe_ratio
            report.max_drawdown = metrics.max_drawdown
            report.var_95 = metrics.var_95
            report.var_99 = metrics.var_99
            report.beta = metrics.beta
            report.alpha = metrics.alpha
        
        # Analyze trades data if provided
        if trades_data:
            report.trade_analysis = self._analyze_trades_for_report(trades_data, start_date, end_date)
            report.top_performing_pairs = self._get_top_performing_pairs(trades_data)
            report.worst_performing_pairs = self._get_worst_performing_pairs(trades_data)
            report.monthly_breakdown = self._calculate_monthly_breakdown(trades_data)
            
            # Calculate metrics from trades data
            filtered_trades = [t for t in trades_data if self._is_trade_in_period(t, start_date, end_date)]
            report.total_trades = len(filtered_trades)
            winning_trades = [t for t in filtered_trades if t.get('pnl', 0) > 0]
            losing_trades = [t for t in filtered_trades if t.get('pnl', 0) < 0]
            report.winning_trades = len(winning_trades)
            report.losing_trades = len(losing_trades)
            report.win_rate = len(winning_trades) / len(filtered_trades) if filtered_trades else 0.0
            
            total_pnl = sum(t.get('pnl', 0) for t in filtered_trades)
            report.total_return = total_pnl / 10000.0  # Assuming 10k initial balance
        
        # Calculate period comparison
        report.previous_period_return = self._get_previous_period_return(
            report_type, start_date, trades_data
        )
        if report.previous_period_return is not None:
            report.return_change = report.total_return - report.previous_period_return
        
        self.logger.info(f"Generated performance report: {report_id}")
        return report
    
    def generate_strategy_report(
        self,
        strategy_name: str,
        start_date: datetime,
        end_date: datetime,
        signals_data: Optional[List[Dict[str, Any]]] = None,
        trades_data: Optional[List[Dict[str, Any]]] = None
    ) -> StrategyReport:
        """
        Generate strategy analysis report
        
        Args:
            strategy_name: Name of the strategy
            start_date: Start date for analysis
            end_date: End date for analysis
            signals_data: Historical signals data
            trades_data: Historical trades data
            
        Returns:
            StrategyReport object
        """
        report = StrategyReport(
            strategy_name=strategy_name,
            report_period=(start_date, end_date),
            generated_at=datetime.now(timezone.utc)
        )
        
        # Analyze signals if data provided
        if signals_data:
            report.signal_accuracy = self._calculate_signal_accuracy(signals_data, trades_data)
            report.signal_frequency = self._calculate_signal_frequency(signals_data, start_date, end_date)
            report.execution_rate = self._calculate_execution_rate(signals_data, trades_data)
            report.avg_confidence = self._calculate_avg_confidence(signals_data)
            
            # Performance by signal type
            report.sentiment_performance = self._analyze_sentiment_performance(signals_data, trades_data)
            report.technical_performance = self._analyze_technical_performance(signals_data, trades_data)
            report.combined_performance = self._analyze_combined_performance(signals_data, trades_data)
        
        # Market condition analysis
        if trades_data:
            report.trending_market_performance = self._analyze_trending_performance(trades_data)
            report.ranging_market_performance = self._analyze_ranging_performance(trades_data)
            report.volatile_market_performance = self._analyze_volatile_performance(trades_data)
            
            # Time-based analysis
            report.hourly_performance = self._analyze_hourly_performance(trades_data)
            report.daily_performance = self._analyze_daily_performance(trades_data)
        
        # Generate recommendations
        report.recommendations = self._generate_strategy_recommendations(report)
        
        self.logger.info(f"Generated strategy report for: {strategy_name}")
        return report
    
    def generate_risk_report(
        self,
        start_date: datetime,
        end_date: datetime,
        positions_data: Optional[List[Position]] = None,
        trades_data: Optional[List[Dict[str, Any]]] = None
    ) -> RiskReport:
        """
        Generate risk analysis report
        
        Args:
            start_date: Start date for analysis
            end_date: End date for analysis
            positions_data: Historical positions data
            trades_data: Historical trades data
            
        Returns:
            RiskReport object
        """
        report = RiskReport(
            report_period=(start_date, end_date),
            generated_at=datetime.now(timezone.utc)
        )
        
        # Get current risk metrics from performance monitor
        if self.performance_monitor:
            current_metrics = self.performance_monitor.get_current_metrics()
            report.current_exposure = current_metrics.current_exposure
            report.current_drawdown = current_metrics.current_drawdown
            report.max_drawdown = current_metrics.max_drawdown
        
        # Analyze positions data
        if positions_data:
            report.avg_position_size = self._calculate_avg_position_size(positions_data)
            report.max_position_size = self._calculate_max_position_size(positions_data)
            report.max_exposure_reached = self._calculate_max_exposure(positions_data)
            report.pair_correlations = self._calculate_pair_correlations(positions_data)
            report.concentration_risk = self._calculate_concentration_risk(positions_data)
        
        # Analyze trades for risk management effectiveness
        if trades_data:
            report.drawdown_periods = self._analyze_drawdown_periods(trades_data)
            report.risk_violations = self._identify_risk_violations(trades_data)
            report.stop_loss_effectiveness = self._calculate_stop_loss_effectiveness(trades_data)
            report.take_profit_effectiveness = self._calculate_take_profit_effectiveness(trades_data)
        
        self.logger.info(f"Generated risk report for period: {start_date} to {end_date}")
        return report
    
    def save_report(
        self,
        report: Any,  # PerformanceReport, StrategyReport, or RiskReport
        format_type: ReportFormat = ReportFormat.JSON,
        filename: Optional[str] = None
    ) -> str:
        """
        Save report to file
        
        Args:
            report: Report object to save
            format_type: Output format
            filename: Optional custom filename
            
        Returns:
            Path to saved file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            if hasattr(report, 'report_id'):
                filename = f"{report.report_id}_{timestamp}.{format_type.value}"
            elif hasattr(report, 'strategy_name'):
                filename = f"strategy_{report.strategy_name}_{timestamp}.{format_type.value}"
            else:
                filename = f"risk_report_{timestamp}.{format_type.value}"
        
        filepath = self.output_directory / filename
        
        if format_type == ReportFormat.JSON:
            with open(filepath, 'w') as f:
                json.dump(report.to_dict(), f, indent=2, default=str)
        
        elif format_type == ReportFormat.HTML:
            html_content = self._generate_html_report(report)
            with open(filepath, 'w') as f:
                f.write(html_content)
        
        elif format_type == ReportFormat.MARKDOWN:
            md_content = self._generate_markdown_report(report)
            with open(filepath, 'w') as f:
                f.write(md_content)
        
        elif format_type == ReportFormat.CSV:
            csv_content = self._generate_csv_report(report)
            with open(filepath, 'w') as f:
                f.write(csv_content)
        
        else:
            raise ValueError(f"Unsupported format: {format_type}")
        
        self.logger.info(f"Report saved to: {filepath}")
        return str(filepath)
    
    def generate_daily_report(self, date: Optional[datetime] = None) -> PerformanceReport:
        """Generate daily performance report"""
        if not date:
            date = datetime.now(timezone.utc)
        
        start_date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = start_date + timedelta(days=1)
        
        return self.generate_performance_report(
            ReportType.DAILY, start_date, end_date
        )
    
    def generate_weekly_report(self, week_start: Optional[datetime] = None) -> PerformanceReport:
        """Generate weekly performance report"""
        if not week_start:
            now = datetime.now(timezone.utc)
            week_start = now - timedelta(days=now.weekday())
        
        week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        week_end = week_start + timedelta(days=7)
        
        return self.generate_performance_report(
            ReportType.WEEKLY, week_start, week_end
        )
    
    def generate_monthly_report(self, month_start: Optional[datetime] = None) -> PerformanceReport:
        """Generate monthly performance report"""
        if not month_start:
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        # Calculate month end
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1)
        
        return self.generate_performance_report(
            ReportType.MONTHLY, month_start, month_end
        )
    
    # Helper methods for report analysis
    def _analyze_trades_for_report(
        self, 
        trades_data: List[Dict[str, Any]], 
        start_date: datetime, 
        end_date: datetime
    ) -> List[TradeAnalysis]:
        """Analyze trades data for report"""
        trade_analyses = []
        
        for i, trade in enumerate(trades_data):
            # Filter trades within report period
            trade_time = trade.get('entry_time', datetime.now(timezone.utc))
            if isinstance(trade_time, str):
                trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
            
            if start_date <= trade_time <= end_date:
                analysis = TradeAnalysis(
                    trade_id=f"trade_{i}",
                    symbol=trade.get('symbol', 'UNKNOWN'),
                    direction=trade.get('direction', 'UNKNOWN'),
                    entry_time=trade_time,
                    exit_time=trade.get('exit_time', trade_time),
                    duration_hours=trade.get('duration_hours', 0),
                    entry_price=trade.get('entry_price', 0),
                    exit_price=trade.get('exit_price', 0),
                    quantity=trade.get('quantity', 0),
                    pnl=trade.get('pnl', 0),
                    pnl_percentage=trade.get('pnl_percentage', 0),
                    commission=trade.get('commission', 0),
                    net_pnl=trade.get('pnl', 0),
                    reason=trade.get('reason', 'Unknown')
                )
                trade_analyses.append(analysis)
        
        return trade_analyses
    
    def _is_trade_in_period(self, trade: Dict[str, Any], start_date: datetime, end_date: datetime) -> bool:
        """Check if trade is within the specified period"""
        trade_time = trade.get('entry_time', datetime.now(timezone.utc))
        if isinstance(trade_time, str):
            trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
        return start_date <= trade_time <= end_date
    
    def _get_top_performing_pairs(self, trades_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get top performing currency pairs"""
        pair_performance = {}
        
        for trade in trades_data:
            symbol = trade.get('symbol', 'UNKNOWN')
            pnl = trade.get('pnl', 0)
            
            if symbol not in pair_performance:
                pair_performance[symbol] = {'total_pnl': 0, 'trade_count': 0}
            
            pair_performance[symbol]['total_pnl'] += pnl
            pair_performance[symbol]['trade_count'] += 1
        
        # Sort by total PnL and return top 5
        sorted_pairs = sorted(
            pair_performance.items(),
            key=lambda x: x[1]['total_pnl'],
            reverse=True
        )
        
        return [
            {
                'symbol': symbol,
                'total_pnl': data['total_pnl'],
                'trade_count': data['trade_count'],
                'avg_pnl': data['total_pnl'] / data['trade_count'] if data['trade_count'] > 0 else 0
            }
            for symbol, data in sorted_pairs[:5]
        ]
    
    def _get_worst_performing_pairs(self, trades_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get worst performing currency pairs"""
        pair_performance = {}
        
        for trade in trades_data:
            symbol = trade.get('symbol', 'UNKNOWN')
            pnl = trade.get('pnl', 0)
            
            if symbol not in pair_performance:
                pair_performance[symbol] = {'total_pnl': 0, 'trade_count': 0}
            
            pair_performance[symbol]['total_pnl'] += pnl
            pair_performance[symbol]['trade_count'] += 1
        
        # Sort by total PnL (ascending) and return bottom 5
        sorted_pairs = sorted(
            pair_performance.items(),
            key=lambda x: x[1]['total_pnl']
        )
        
        return [
            {
                'symbol': symbol,
                'total_pnl': data['total_pnl'],
                'trade_count': data['trade_count'],
                'avg_pnl': data['total_pnl'] / data['trade_count'] if data['trade_count'] > 0 else 0
            }
            for symbol, data in sorted_pairs[:5]
        ]
    
    def _calculate_monthly_breakdown(self, trades_data: List[Dict[str, Any]]) -> Dict[str, float]:
        """Calculate monthly performance breakdown"""
        monthly_pnl = {}
        
        for trade in trades_data:
            trade_time = trade.get('entry_time', datetime.now(timezone.utc))
            if isinstance(trade_time, str):
                trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
            
            month_key = trade_time.strftime('%Y-%m')
            pnl = trade.get('pnl', 0)
            
            if month_key not in monthly_pnl:
                monthly_pnl[month_key] = 0
            
            monthly_pnl[month_key] += pnl
        
        return monthly_pnl
    
    def _get_previous_period_return(
        self, 
        report_type: ReportType, 
        current_start: datetime,
        trades_data: Optional[List[Dict[str, Any]]]
    ) -> Optional[float]:
        """Calculate return for previous period for comparison"""
        if not trades_data:
            return None
        
        config = self._report_configs.get(report_type, {'lookback_days': 30})
        lookback_days = config['lookback_days']
        
        prev_end = current_start
        prev_start = prev_end - timedelta(days=lookback_days)
        
        prev_pnl = 0
        for trade in trades_data:
            trade_time = trade.get('entry_time', datetime.now(timezone.utc))
            if isinstance(trade_time, str):
                trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
            
            if prev_start <= trade_time < prev_end:
                prev_pnl += trade.get('pnl', 0)
        
        # Convert to return percentage (assuming 10k initial balance)
        return prev_pnl / 10000.0
    
    # Strategy analysis helper methods
    def _calculate_signal_accuracy(
        self, 
        signals_data: List[Dict[str, Any]], 
        trades_data: Optional[List[Dict[str, Any]]]
    ) -> float:
        """Calculate signal accuracy rate"""
        if not signals_data or not trades_data:
            return 0.0
        
        successful_signals = 0
        total_signals = len(signals_data)
        
        for signal in signals_data:
            # Find corresponding trade
            signal_time = signal.get('timestamp', datetime.now(timezone.utc))
            if isinstance(signal_time, str):
                signal_time = datetime.fromisoformat(signal_time.replace('Z', '+00:00'))
            
            # Look for trade within 1 hour of signal
            for trade in trades_data:
                trade_time = trade.get('entry_time', datetime.now(timezone.utc))
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                
                time_diff = abs((trade_time - signal_time).total_seconds())
                if time_diff <= 3600 and trade.get('pnl', 0) > 0:  # Within 1 hour and profitable
                    successful_signals += 1
                    break
        
        return successful_signals / total_signals if total_signals > 0 else 0.0
    
    def _calculate_signal_frequency(
        self, 
        signals_data: List[Dict[str, Any]], 
        start_date: datetime, 
        end_date: datetime
    ) -> float:
        """Calculate signals per day"""
        total_days = (end_date - start_date).days
        if total_days <= 0:
            return 0.0
        
        return len(signals_data) / total_days
    
    def _calculate_execution_rate(
        self, 
        signals_data: List[Dict[str, Any]], 
        trades_data: Optional[List[Dict[str, Any]]]
    ) -> float:
        """Calculate execution rate (executed signals / total signals)"""
        if not signals_data or not trades_data:
            return 0.0
        
        executed_signals = 0
        
        for signal in signals_data:
            signal_time = signal.get('timestamp', datetime.now(timezone.utc))
            if isinstance(signal_time, str):
                signal_time = datetime.fromisoformat(signal_time.replace('Z', '+00:00'))
            
            # Look for corresponding trade
            for trade in trades_data:
                trade_time = trade.get('entry_time', datetime.now(timezone.utc))
                if isinstance(trade_time, str):
                    trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
                
                time_diff = abs((trade_time - signal_time).total_seconds())
                if time_diff <= 3600:  # Within 1 hour
                    executed_signals += 1
                    break
        
        return executed_signals / len(signals_data)
    
    def _calculate_avg_confidence(self, signals_data: List[Dict[str, Any]]) -> float:
        """Calculate average signal confidence"""
        if not signals_data:
            return 0.0
        
        confidences = [signal.get('confidence', 0) for signal in signals_data]
        return statistics.mean(confidences) if confidences else 0.0
    
    def _analyze_sentiment_performance(
        self, 
        signals_data: List[Dict[str, Any]], 
        trades_data: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, float]:
        """Analyze performance of sentiment-based signals"""
        # Simplified implementation - would need more detailed signal type tracking
        return {
            'total_return': 0.0,
            'win_rate': 0.0,
            'avg_confidence': 0.0,
            'signal_count': 0
        }
    
    def _analyze_technical_performance(
        self, 
        signals_data: List[Dict[str, Any]], 
        trades_data: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, float]:
        """Analyze performance of technical analysis signals"""
        # Simplified implementation - would need more detailed signal type tracking
        return {
            'total_return': 0.0,
            'win_rate': 0.0,
            'avg_confidence': 0.0,
            'signal_count': 0
        }
    
    def _analyze_combined_performance(
        self, 
        signals_data: List[Dict[str, Any]], 
        trades_data: Optional[List[Dict[str, Any]]]
    ) -> Dict[str, float]:
        """Analyze performance of combined signals"""
        # Simplified implementation - would need more detailed signal type tracking
        return {
            'total_return': 0.0,
            'win_rate': 0.0,
            'avg_confidence': 0.0,
            'signal_count': 0
        }
    
    def _analyze_trending_performance(self, trades_data: List[Dict[str, Any]]) -> float:
        """Analyze performance in trending market conditions"""
        # Simplified implementation - would need market condition classification
        trending_trades = [t for t in trades_data if t.get('market_condition') == 'trending']
        if not trending_trades:
            return 0.0
        
        total_pnl = sum(t.get('pnl', 0) for t in trending_trades)
        return total_pnl / 10000.0  # Convert to return percentage
    
    def _analyze_ranging_performance(self, trades_data: List[Dict[str, Any]]) -> float:
        """Analyze performance in ranging market conditions"""
        # Simplified implementation - would need market condition classification
        ranging_trades = [t for t in trades_data if t.get('market_condition') == 'ranging']
        if not ranging_trades:
            return 0.0
        
        total_pnl = sum(t.get('pnl', 0) for t in ranging_trades)
        return total_pnl / 10000.0  # Convert to return percentage
    
    def _analyze_volatile_performance(self, trades_data: List[Dict[str, Any]]) -> float:
        """Analyze performance in volatile market conditions"""
        # Simplified implementation - would need market condition classification
        volatile_trades = [t for t in trades_data if t.get('market_condition') == 'volatile']
        if not volatile_trades:
            return 0.0
        
        total_pnl = sum(t.get('pnl', 0) for t in volatile_trades)
        return total_pnl / 10000.0  # Convert to return percentage
    
    def _analyze_hourly_performance(self, trades_data: List[Dict[str, Any]]) -> Dict[int, float]:
        """Analyze performance by hour of day"""
        hourly_pnl = {hour: 0 for hour in range(24)}
        
        for trade in trades_data:
            trade_time = trade.get('entry_time', datetime.now(timezone.utc))
            if isinstance(trade_time, str):
                trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
            
            hour = trade_time.hour
            hourly_pnl[hour] += trade.get('pnl', 0)
        
        # Convert to return percentages
        return {hour: pnl / 10000.0 for hour, pnl in hourly_pnl.items()}
    
    def _analyze_daily_performance(self, trades_data: List[Dict[str, Any]]) -> Dict[str, float]:
        """Analyze performance by day of week"""
        daily_pnl = {day: 0 for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']}
        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        
        for trade in trades_data:
            trade_time = trade.get('entry_time', datetime.now(timezone.utc))
            if isinstance(trade_time, str):
                trade_time = datetime.fromisoformat(trade_time.replace('Z', '+00:00'))
            
            day_name = day_names[trade_time.weekday()]
            daily_pnl[day_name] += trade.get('pnl', 0)
        
        # Convert to return percentages
        return {day: pnl / 10000.0 for day, pnl in daily_pnl.items()}
    
    def _generate_strategy_recommendations(self, report: StrategyReport) -> List[str]:
        """Generate strategy improvement recommendations"""
        recommendations = []
        
        if report.signal_accuracy < 0.6:
            recommendations.append("Consider improving signal filtering to increase accuracy")
        
        if report.execution_rate < 0.8:
            recommendations.append("Review execution logic to capture more valid signals")
        
        if report.avg_confidence < 0.7:
            recommendations.append("Focus on higher confidence signals to improve performance")
        
        # Analyze time-based performance
        best_hour = max(report.hourly_performance.items(), key=lambda x: x[1])
        worst_hour = min(report.hourly_performance.items(), key=lambda x: x[1])
        
        if best_hour[1] > 0 and worst_hour[1] < 0:
            recommendations.append(f"Consider focusing trading during hour {best_hour[0]} and avoiding hour {worst_hour[0]}")
        
        best_day = max(report.daily_performance.items(), key=lambda x: x[1])
        worst_day = min(report.daily_performance.items(), key=lambda x: x[1])
        
        if best_day[1] > 0 and worst_day[1] < 0:
            recommendations.append(f"Consider focusing trading on {best_day[0]} and reducing activity on {worst_day[0]}")
        
        return recommendations
    
    # Risk analysis helper methods
    def _calculate_avg_position_size(self, positions_data: List[Position]) -> float:
        """Calculate average position size"""
        if not positions_data:
            return 0.0
        
        sizes = [pos.quantity for pos in positions_data]
        return statistics.mean(sizes)
    
    def _calculate_max_position_size(self, positions_data: List[Position]) -> float:
        """Calculate maximum position size"""
        if not positions_data:
            return 0.0
        
        return max(pos.quantity for pos in positions_data)
    
    def _calculate_max_exposure(self, positions_data: List[Position]) -> float:
        """Calculate maximum exposure reached"""
        if not positions_data:
            return 0.0
        
        # Group positions by timestamp and calculate total exposure
        exposure_by_time = {}
        
        for pos in positions_data:
            time_key = pos.opened_at.strftime('%Y-%m-%d %H:%M')
            if time_key not in exposure_by_time:
                exposure_by_time[time_key] = 0
            
            exposure_by_time[time_key] += pos.quantity * pos.entry_price
        
        return max(exposure_by_time.values()) if exposure_by_time else 0.0
    
    def _calculate_pair_correlations(self, positions_data: List[Position]) -> Dict[str, float]:
        """Calculate correlations between currency pairs"""
        # Simplified implementation - would need historical price data for proper correlation
        pair_counts = {}
        
        for pos in positions_data:
            if pos.symbol not in pair_counts:
                pair_counts[pos.symbol] = 0
            pair_counts[pos.symbol] += 1
        
        # Return normalized counts as proxy for correlation risk
        total_positions = sum(pair_counts.values())
        return {
            pair: count / total_positions 
            for pair, count in pair_counts.items()
        }
    
    def _calculate_concentration_risk(self, positions_data: List[Position]) -> float:
        """Calculate concentration risk (Herfindahl index)"""
        if not positions_data:
            return 0.0
        
        pair_weights = {}
        total_exposure = 0
        
        for pos in positions_data:
            exposure = pos.quantity * pos.entry_price
            total_exposure += exposure
            
            if pos.symbol not in pair_weights:
                pair_weights[pos.symbol] = 0
            pair_weights[pos.symbol] += exposure
        
        if total_exposure == 0:
            return 0.0
        
        # Calculate Herfindahl index
        herfindahl = sum(
            (weight / total_exposure) ** 2 
            for weight in pair_weights.values()
        )
        
        return herfindahl
    
    def _analyze_drawdown_periods(self, trades_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Analyze drawdown periods"""
        drawdown_periods = []
        
        # Calculate running PnL
        running_pnl = 0
        peak_pnl = 0
        drawdown_start = None
        
        for trade in sorted(trades_data, key=lambda x: x.get('entry_time', datetime.now())):
            running_pnl += trade.get('pnl', 0)
            
            if running_pnl > peak_pnl:
                # New peak, end any current drawdown
                if drawdown_start:
                    drawdown_periods.append({
                        'start': drawdown_start,
                        'end': trade.get('entry_time'),
                        'depth': peak_pnl - running_pnl,
                        'duration_days': 0  # Would need proper calculation
                    })
                    drawdown_start = None
                
                peak_pnl = running_pnl
            
            elif running_pnl < peak_pnl and not drawdown_start:
                # Start of new drawdown
                drawdown_start = trade.get('entry_time')
        
        return drawdown_periods
    
    def _identify_risk_violations(self, trades_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Identify risk management violations"""
        violations = []
        
        for trade in trades_data:
            # Check for excessive position size (simplified)
            position_size = trade.get('position_size', 0)
            if position_size > 0.1:  # 10% max position size
                violations.append({
                    'type': 'excessive_position_size',
                    'trade_id': trade.get('trade_id', 'unknown'),
                    'value': position_size,
                    'threshold': 0.1,
                    'timestamp': trade.get('entry_time')
                })
            
            # Check for excessive loss
            pnl_percentage = trade.get('pnl_percentage', 0)
            if pnl_percentage < -0.05:  # 5% max loss per trade
                violations.append({
                    'type': 'excessive_loss',
                    'trade_id': trade.get('trade_id', 'unknown'),
                    'value': pnl_percentage,
                    'threshold': -0.05,
                    'timestamp': trade.get('entry_time')
                })
        
        return violations
    
    def _calculate_stop_loss_effectiveness(self, trades_data: List[Dict[str, Any]]) -> float:
        """Calculate stop loss effectiveness"""
        stop_loss_trades = [t for t in trades_data if t.get('exit_reason') == 'stop_loss']
        if not stop_loss_trades:
            return 0.0
        
        # Calculate how often stop loss prevented larger losses
        effective_stops = 0
        for trade in stop_loss_trades:
            # Simplified: assume stop loss was effective if loss was limited
            if trade.get('pnl_percentage', 0) > -0.05:  # Loss less than 5%
                effective_stops += 1
        
        return effective_stops / len(stop_loss_trades)
    
    def _calculate_take_profit_effectiveness(self, trades_data: List[Dict[str, Any]]) -> float:
        """Calculate take profit effectiveness"""
        take_profit_trades = [t for t in trades_data if t.get('exit_reason') == 'take_profit']
        if not take_profit_trades:
            return 0.0
        
        # Calculate how often take profit captured good moves
        effective_profits = 0
        for trade in take_profit_trades:
            # Simplified: assume take profit was effective if profit was captured
            if trade.get('pnl_percentage', 0) > 0.02:  # Profit more than 2%
                effective_profits += 1
        
        return effective_profits / len(take_profit_trades)
    
    # Report formatting methods
    def _generate_html_report(self, report: Any) -> str:
        """Generate HTML formatted report"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Trading Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 20px; }}
                .header {{ background-color: #f0f0f0; padding: 10px; }}
                .metric {{ margin: 10px 0; }}
                .positive {{ color: green; }}
                .negative {{ color: red; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Trading Performance Report</h1>
                <p>Generated: {generated_at}</p>
            </div>
            <div class="content">
                {content}
            </div>
        </body>
        </html>
        """
        
        # Generate content based on report type
        content = self._format_report_content(report)
        
        return html_template.format(
            generated_at=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            content=content
        )
    
    def _generate_markdown_report(self, report: Any) -> str:
        """Generate Markdown formatted report"""
        md_content = f"# Trading Report\n\n"
        md_content += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        
        if hasattr(report, 'report_type'):
            md_content += f"## {report.report_type.value.title()} Performance Report\n\n"
            md_content += f"**Period:** {report.period_start.strftime('%Y-%m-%d')} to {report.period_end.strftime('%Y-%m-%d')}\n\n"
            
            md_content += "### Summary Metrics\n\n"
            md_content += f"- Total Return: {report.total_return:.2%}\n"
            md_content += f"- Total Trades: {report.total_trades}\n"
            md_content += f"- Win Rate: {report.win_rate:.2%}\n"
            md_content += f"- Profit Factor: {report.profit_factor:.2f}\n"
            md_content += f"- Sharpe Ratio: {report.sharpe_ratio:.2f}\n"
            md_content += f"- Max Drawdown: {report.max_drawdown:.2%}\n\n"
        
        return md_content
    
    def _generate_csv_report(self, report: Any) -> str:
        """Generate CSV formatted report"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Write headers and data based on report type
        if hasattr(report, 'trade_analysis'):
            writer.writerow(['Trade ID', 'Symbol', 'Direction', 'PnL', 'PnL %', 'Duration Hours'])
            for trade in report.trade_analysis:
                writer.writerow([
                    trade.trade_id,
                    trade.symbol,
                    trade.direction,
                    trade.pnl,
                    trade.pnl_percentage,
                    trade.duration_hours
                ])
        
        return output.getvalue()
    
    def _format_report_content(self, report: Any) -> str:
        """Format report content for HTML"""
        content = ""
        
        if hasattr(report, 'total_return'):
            css_class = 'positive' if report.total_return > 0 else 'negative'
            content += f"<div class='metric'>Total Return: <span class='{css_class}'>{report.total_return:.2%}</span></div>"
        
        if hasattr(report, 'win_rate'):
            content += f"<div class='metric'>Win Rate: {report.win_rate:.2%}</div>"
        
        if hasattr(report, 'sharpe_ratio'):
            content += f"<div class='metric'>Sharpe Ratio: {report.sharpe_ratio:.2f}</div>"
        
        return content
"""
Weekly Distribution Report Generator

Advanced statistical analysis of trading performance:
- R-multiple distribution (profit/risk ratio)
- Tail loss percentiles (worst-case scenarios)
- Volatility vs return correlation
- Rejection accuracy (filter quality validation)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import defaultdict
import statistics

logger = logging.getLogger(__name__)


@dataclass
class TradeMetrics:
    """Metrics for an executed trade"""
    symbol: str
    direction: str  # "BUY" or "SELL"
    entry_price: float
    exit_price: float
    risk_amount: float  # Risk in points/pips
    entry_time: datetime
    exit_time: datetime
    volatility_at_entry: float
    
    @property
    def pnl(self) -> float:
        """Calculate P&L"""
        if self.direction == "BUY":
            return self.exit_price - self.entry_price
        else:
            return self.entry_price - self.exit_price
    
    @property
    def r_multiple(self) -> float:
        """Calculate R-multiple (profit/risk)"""
        if self.risk_amount == 0:
            return 0
        return self.pnl / self.risk_amount
    
    @property
    def return_pct(self) -> float:
        """Calculate return as percentage"""
        if self.entry_price == 0:
            return 0
        return (self.pnl / self.entry_price) * 100
    
    @property
    def won(self) -> bool:
        """Did this trade win?"""
        return self.pnl > 0
    
    @property
    def hold_time_minutes(self) -> float:
        """How long was trade held (minutes)"""
        delta = self.exit_time - self.entry_time
        return delta.total_seconds() / 60


@dataclass
class RejectedTradeAnalysis:
    """Analysis of a rejected trade's hypothetical performance"""
    symbol: str
    direction: str  # "BUY" or "SELL"
    signal_price: float
    rejection_reason: str
    rejection_time: datetime
    signal_confidence: float
    
    # Tracking fields (filled later)
    price_samples: List[float] = field(default_factory=list)
    time_samples: List[datetime] = field(default_factory=list)
    final_checked_price: float = 0.0
    lookback_bars: int = 100  # How many bars to track
    bars_observed: int = 0
    
    @property
    def would_have_won(self) -> bool:
        """Would this rejected trade have been profitable?"""
        if not self.price_samples or self.final_checked_price == 0:
            return False
        
        if self.direction == "BUY":
            # Would win if price went up
            return self.final_checked_price > self.signal_price
        else:
            # Would win if price went down
            return self.final_checked_price < self.signal_price
    
    @property
    def hypothetical_pnl(self) -> float:
        """What would the P&L have been?"""
        if self.direction == "BUY":
            return self.final_checked_price - self.signal_price
        else:
            return self.signal_price - self.final_checked_price


@dataclass
class WeeklyMetrics:
    """Aggregated weekly trading metrics"""
    week_start: datetime
    week_end: datetime
    
    # Trade execution metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    
    # R-multiple distribution
    r_multiples: List[float] = field(default_factory=list)
    mean_r_multiple: float = 0.0
    median_r_multiple: float = 0.0
    std_dev_r_multiple: float = 0.0
    r_distribution_histogram: Dict[str, int] = field(default_factory=dict)
    
    # Return distribution
    returns: List[float] = field(default_factory=list)
    mean_return: float = 0.0
    volatilities: List[float] = field(default_factory=list)
    
    # Tail risk analysis
    tail_loss_95: float = 0.0  # 95th percentile loss
    tail_loss_99: float = 0.0  # 99th percentile loss
    best_trade: float = 0.0
    worst_trade: float = 0.0
    
    # Correlation analysis
    volatility_return_correlation: float = 0.0
    
    # Rejection analysis
    total_rejected: int = 0
    rejected_would_have_won: int = 0
    accepted_won: int = 0
    rejection_win_rate: float = 0.0
    acceptance_win_rate: float = 0.0
    rejection_accuracy: str = "UNKNOWN"  # "GOOD", "BROKEN", "NEUTRAL"
    
    # Sharpe ratio
    sharpe_ratio: float = 0.0
    total_pnl: float = 0.0


class WeeklyDistributionReportGenerator:
    """Generates weekly statistical distribution reports"""

    _shared_instance: Optional["WeeklyDistributionReportGenerator"] = None
    
    def __new__(cls, output_dir: str = "reports/weekly_distribution"):
        if cls._shared_instance is None:
            cls._shared_instance = super().__new__(cls)
        return cls._shared_instance

    def __init__(self, output_dir: str = "reports/weekly_distribution"):
        if getattr(self, "_initialized", False):
            return
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.trades: List[TradeMetrics] = []
        self.rejected_trades: List[RejectedTradeAnalysis] = []
        self.volatility_samples: List[float] = []
        
        self.last_report_time = datetime.now(timezone.utc)
        self.current_week_start = self._get_week_start()
        self._initialized = True
        
        logger.info(f"[OK] Weekly Distribution Report Generator initialized - Reports every 7 days")
    
    def _get_week_start(self) -> datetime:
        """Get start of current week (Monday UTC)"""
        now = datetime.now(timezone.utc)
        monday = now - timedelta(days=now.weekday())
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    
    def record_executed_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        risk_amount: float,
        entry_time: datetime,
        exit_time: datetime,
        volatility_at_entry: float
    ) -> None:
        """Record an executed trade"""
        trade = TradeMetrics(
            symbol=symbol,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            risk_amount=risk_amount,
            entry_time=entry_time,
            exit_time=exit_time,
            volatility_at_entry=volatility_at_entry
        )
        self.trades.append(trade)
        logger.debug(f"[TRADE_METRICS] {symbol} {direction} | R-multiple: {trade.r_multiple:.2f} | "
                    f"Return: {trade.return_pct:.3f}% | Won: {trade.won}")
    
    def record_rejected_trade(
        self,
        symbol: str,
        direction: str,
        signal_price: float,
        rejection_reason: str,
        signal_confidence: float,
        lookback_bars: int = 100
    ) -> None:
        """Record a rejected trade for hypothetical analysis"""
        rejected = RejectedTradeAnalysis(
            symbol=symbol,
            direction=direction,
            signal_price=signal_price,
            rejection_reason=rejection_reason,
            rejection_time=datetime.now(timezone.utc),
            signal_confidence=signal_confidence,
            lookback_bars=lookback_bars
        )
        self.rejected_trades.append(rejected)
        logger.debug(f"[REJECTED_TRACKING] {symbol} {direction} | Reason: {rejection_reason} | "
                    f"Confidence: {signal_confidence:.3f}")
    
    def update_rejected_trade_price(self, symbol: str, direction: str, current_price: float) -> None:
        """Update price tracking for rejected trades"""
        for rejected in self.rejected_trades:
            if rejected.symbol == symbol and rejected.direction == direction:
                rejected.price_samples.append(current_price)
                rejected.time_samples.append(datetime.now(timezone.utc))
                rejected.bars_observed += 1
                
                # Update final price
                if rejected.bars_observed % 10 == 0:  # Update every 10 bars
                    rejected.final_checked_price = current_price
                
                # Stop tracking after lookback period
                if rejected.bars_observed >= rejected.lookback_bars:
                    rejected.final_checked_price = current_price
    
    def record_volatility_sample(self, volatility: float) -> None:
        """Record volatility sample for correlation analysis"""
        self.volatility_samples.append(volatility)
    
    def _calculate_r_distribution_histogram(self) -> Dict[str, int]:
        """Create R-multiple distribution histogram"""
        histogram = defaultdict(int)
        
        for r_multiple in self._get_r_multiples():
            # Bucket: -2R to +3R in 0.5R increments
            if r_multiple < -2:
                bucket = "< -2R"
            elif r_multiple < -1.5:
                bucket = "-2R to -1.5R"
            elif r_multiple < -1:
                bucket = "-1.5R to -1R"
            elif r_multiple < -0.5:
                bucket = "-1R to -0.5R"
            elif r_multiple < 0:
                bucket = "-0.5R to 0R"
            elif r_multiple < 0.5:
                bucket = "0R to +0.5R"
            elif r_multiple < 1:
                bucket = "+0.5R to +1R"
            elif r_multiple < 1.5:
                bucket = "+1R to +1.5R"
            elif r_multiple < 2:
                bucket = "+1.5R to +2R"
            elif r_multiple < 3:
                bucket = "+2R to +3R"
            else:
                bucket = "> +3R"
            
            histogram[bucket] += 1
        
        return dict(sorted(histogram.items()))
    
    def _get_r_multiples(self) -> List[float]:
        """Get list of R-multiples from trades"""
        return [trade.r_multiple for trade in self.trades if self.trades]
    
    def _get_returns(self) -> List[float]:
        """Get list of returns from trades"""
        return [trade.return_pct for trade in self.trades if self.trades]
    
    def _calculate_tail_loss_percentile(self, values: List[float], percentile: int) -> float:
        """Calculate tail loss at given percentile (e.g., 95th percentile worst loss)"""
        if not values:
            return 0.0
        
        sorted_values = sorted(values)
        index = int(len(sorted_values) * (percentile / 100.0))
        index = max(0, min(index, len(sorted_values) - 1))
        
        return sorted_values[index]
    
    def _calculate_volatility_return_correlation(self) -> float:
        """Calculate correlation between volatility and returns"""
        if len(self.trades) < 2 or not self.volatility_samples:
            return 0.0
        
        # Match volatility samples with trade returns
        # Use volatility from trade entry time
        correlations = []
        
        for trade in self.trades:
            if trade.volatility_at_entry > 0:
                # Correlation between volatility at entry and return
                correlation_pair = (trade.volatility_at_entry, trade.return_pct)
                correlations.append(correlation_pair)
        
        if len(correlations) < 2:
            return 0.0
        
        # Calculate Pearson correlation
        volatilities = [c[0] for c in correlations]
        returns = [c[1] for c in correlations]
        
        try:
            mean_vol = statistics.mean(volatilities)
            mean_ret = statistics.mean(returns)
            
            numerator = sum((v - mean_vol) * (r - mean_ret) for v, r in zip(volatilities, returns))
            denom_vol = sum((v - mean_vol) ** 2 for v in volatilities) ** 0.5
            denom_ret = sum((r - mean_ret) ** 2 for r in returns) ** 0.5
            
            if denom_vol == 0 or denom_ret == 0:
                return 0.0
            
            correlation = numerator / (denom_vol * denom_ret)
            return min(1.0, max(-1.0, correlation))  # Clamp to [-1, 1]
        except:
            return 0.0
    
    def _calculate_rejection_accuracy(self) -> Dict[str, any]:
        """Calculate how many rejected trades would have won"""
        if not self.rejected_trades and not self.trades:
            return {
                "rejected_would_have_won": 0,
                "rejected_analyzed": 0,
                "rejection_win_rate": 0.0,
                "acceptance_win_rate": self._calculate_win_rate(),
                "filter_assessment": "NO_DATA"
            }
        
        rejected_wins = sum(1 for r in self.rejected_trades if r.would_have_won and r.final_checked_price > 0)
        rejected_with_data = sum(1 for r in self.rejected_trades if r.final_checked_price > 0)
        
        accepted_wins = sum(1 for t in self.trades if t.won)
        accepted_total = len(self.trades)
        
        rejection_win_rate = (rejected_wins / rejected_with_data * 100) if rejected_with_data > 0 else 0.0
        acceptance_win_rate = (accepted_wins / accepted_total * 100) if accepted_total > 0 else 0.0
        
        # Filter assessment
        if rejection_win_rate > acceptance_win_rate + 10:
            filter_assessment = "⚠️  BROKEN - Rejecting winners!"
        elif rejection_win_rate > acceptance_win_rate + 5:
            filter_assessment = "⚠️  DEGRADED - Rejecting too many winners"
        elif acceptance_win_rate > rejection_win_rate + 10:
            filter_assessment = "✅ GOOD - Filter is protecting capital"
        elif acceptance_win_rate > rejection_win_rate + 5:
            filter_assessment = "✅ SOLID - Filter improving results"
        else:
            filter_assessment = "➖ NEUTRAL - Similar performance"
        
        return {
            "rejected_would_have_won": rejected_wins,
            "rejected_analyzed": rejected_with_data,
            "rejection_win_rate": rejection_win_rate,
            "acceptance_win_rate": acceptance_win_rate,
            "filter_assessment": filter_assessment,
            "accepted_wins_count": accepted_wins
        }
    
    def _calculate_win_rate(self) -> float:
        """Calculate win rate of executed trades"""
        if not self.trades:
            return 0.0
        
        wins = sum(1 for t in self.trades if t.won)
        return (wins / len(self.trades)) * 100
    
    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio (simplified)"""
        if not self.trades or len(self.trades) < 2:
            return 0.0
        
        try:
            returns = [t.return_pct for t in self.trades]
            mean_return = statistics.mean(returns)
            std_dev = statistics.stdev(returns)
            
            if std_dev == 0:
                return 0.0
            
            # Sharpe = (mean_return - risk_free_rate) / std_dev
            # Assuming 0% risk-free rate
            sharpe = mean_return / std_dev
            return sharpe
        except:
            return 0.0
    
    def calculate_metrics(self) -> WeeklyMetrics:
        """Calculate all weekly metrics"""
        r_multiples = self._get_r_multiples()
        returns = self._get_returns()
        rejection_analysis = self._calculate_rejection_accuracy()
        
        # Pre-calculate trade counts
        trades_count = len(self.trades)
        winning_trades_count = sum(1 for t in self.trades if t.won)
        losing_trades_count = sum(1 for t in self.trades if not t.won)
        
        metrics = WeeklyMetrics(
            week_start=self.current_week_start,
            week_end=datetime.now(timezone.utc),
            
            # Trade metrics
            total_trades=trades_count,
            winning_trades=winning_trades_count,
            losing_trades=losing_trades_count,
            win_rate=self._calculate_win_rate(),
            
            # R-multiple metrics
            r_multiples=r_multiples,
            mean_r_multiple=statistics.mean(r_multiples) if r_multiples else 0.0,
            median_r_multiple=statistics.median(r_multiples) if r_multiples else 0.0,
            std_dev_r_multiple=statistics.stdev(r_multiples) if len(r_multiples) > 1 else 0.0,
            r_distribution_histogram=self._calculate_r_distribution_histogram(),
            
            # Return metrics
            returns=returns,
            mean_return=statistics.mean(returns) if returns else 0.0,
            volatilities=self.volatility_samples,
            
            # Tail risk
            tail_loss_95=self._calculate_tail_loss_percentile(returns, 5),  # 5th percentile = worst 5%
            tail_loss_99=self._calculate_tail_loss_percentile(returns, 1),  # 1st percentile = worst 1%
            best_trade=max(returns) if returns else 0.0,
            worst_trade=min(returns) if returns else 0.0,
            
            # Correlation
            volatility_return_correlation=self._calculate_volatility_return_correlation(),
            
            # Rejection analysis
            total_rejected=len(self.rejected_trades),
            rejected_would_have_won=rejection_analysis["rejected_would_have_won"],
            accepted_won=winning_trades_count,  # Use count, not rate
            rejection_win_rate=rejection_analysis["rejection_win_rate"],
            acceptance_win_rate=rejection_analysis["acceptance_win_rate"],
            rejection_accuracy=rejection_analysis["filter_assessment"],
            
            # Sharpe
            sharpe_ratio=self._calculate_sharpe_ratio(),
            total_pnl=sum(t.pnl for t in self.trades)
        )
        
        return metrics
    
    def format_report(self, metrics: WeeklyMetrics) -> str:
        """Format metrics into a professional report"""
        report = []
        report.append("=" * 80)
        report.append("WEEKLY DISTRIBUTION REPORT - ADVANCED STATISTICAL ANALYSIS")
        report.append("=" * 80)
        report.append("")
        report.append(f"Report Period: {metrics.week_start.strftime('%Y-%m-%d %H:%M')} to {metrics.week_end.strftime('%Y-%m-%d %H:%M')} UTC")
        report.append("")
        
        # Section 1: Trade Summary
        report.append("┌─ TRADE EXECUTION SUMMARY")
        report.append(f"├─ Total Trades:                  {metrics.total_trades}")
        report.append(f"├─ Winning Trades:                {metrics.winning_trades}")
        report.append(f"├─ Losing Trades:                 {metrics.losing_trades}")
        report.append(f"├─ Win Rate:                      {metrics.win_rate:.1f}%")
        report.append(f"├─ Total P&L:                     ${metrics.total_pnl:,.2f}")
        report.append(f"└─ Sharpe Ratio:                  {metrics.sharpe_ratio:.3f}")
        report.append("")
        
        # Section 2: R-Multiple Distribution
        report.append("┌─ R-MULTIPLE DISTRIBUTION (Profit/Risk)")
        report.append(f"├─ Mean R:                        {metrics.mean_r_multiple:.2f}R")
        report.append(f"├─ Median R:                      {metrics.median_r_multiple:.2f}R")
        report.append(f"├─ Std Dev R:                     {metrics.std_dev_r_multiple:.2f}R")
        report.append(f"├─")
        report.append(f"├─ Distribution Histogram:")
        for bucket, count in metrics.r_distribution_histogram.items():
            pct = (count / metrics.total_trades * 100) if metrics.total_trades > 0 else 0
            bar = "█" * int(pct / 2)
            report.append(f"│  {bucket:20s} {count:3d} trades ({pct:5.1f}%) {bar}")
        report.append(f"└─")
        report.append("")
        
        # Section 3: Return Metrics
        report.append("┌─ RETURN ANALYSIS")
        report.append(f"├─ Best Trade:                    {metrics.best_trade:+.3f}%")
        report.append(f"├─ Worst Trade:                   {metrics.worst_trade:+.3f}%")
        report.append(f"├─ Mean Return:                   {metrics.mean_return:+.3f}%")
        report.append(f"└─ Return Std Dev:                {statistics.stdev(metrics.returns) if len(metrics.returns) > 1 else 0:.3f}%")
        report.append("")
        
        # Section 4: Tail Risk (95% and 99% loss scenarios)
        report.append("┌─ TAIL LOSS ANALYSIS (Worst-Case Scenarios)")
        report.append(f"├─ 95th Percentile Loss:          {metrics.tail_loss_95:.3f}%")
        report.append(f"│  (Worst 5% of trades average to this loss)")
        report.append(f"├─ 99th Percentile Loss:          {metrics.tail_loss_99:.3f}%")
        report.append(f"│  (Worst 1% of trades average to this loss)")
        report.append(f"└─ Risk Assessment:               {'🔴 EXTREME' if metrics.tail_loss_99 < -10 else '🟠 HIGH' if metrics.tail_loss_99 < -5 else '🟡 MODERATE' if metrics.tail_loss_99 < -2 else '🟢 ACCEPTABLE'}")
        report.append("")
        
        # Section 5: Volatility vs Return Correlation
        report.append("┌─ VOLATILITY vs RETURN CORRELATION")
        correlation = metrics.volatility_return_correlation
        if abs(correlation) < 0.3:
            corr_assessment = "LOW - Returns independent of volatility"
        elif abs(correlation) < 0.6:
            corr_assessment = "MODERATE - Some volatility impact"
        else:
            corr_assessment = "HIGH - Strong volatility impact"
        
        report.append(f"├─ Pearson Correlation:           {correlation:+.3f}")
        report.append(f"├─ Assessment:                    {corr_assessment}")
        if correlation > 0:
            report.append(f"├─ Interpretation:               Higher volatility = Higher returns (Good in bullish bias)")
        elif correlation < 0:
            report.append(f"├─ Interpretation:               Higher volatility = Lower returns (Volatility hurts performance)")
        else:
            report.append(f"├─ Interpretation:               Volatility doesn't impact returns (Neutral)")
        report.append(f"└─")
        report.append("")
        
        # Section 6: Rejection Accuracy Analysis (MOST IMPORTANT)
        report.append("┌─ FILTER QUALITY ANALYSIS (Rejection Accuracy)")
        report.append(f"├─ Rejected Signals Analyzed:     {metrics.total_rejected}")
        report.append(f"├─ Rejected That Would Have Won:  {metrics.rejected_would_have_won}")
        report.append(f"│  ({metrics.rejection_win_rate:.1f}% of rejected trades would have been profitable)")
        report.append(f"├─")
        report.append(f"├─ Executed Trades Won:          {metrics.winning_trades}/{metrics.total_trades} ({metrics.acceptance_win_rate:.1f}%)")
        report.append(f"├─")
        report.append(f"├─ FILTER ASSESSMENT:            {metrics.rejection_accuracy}")
        report.append(f"│")
        
        if "BROKEN" in metrics.rejection_accuracy:
            report.append(f"│  ⚠️  WARNING: Filter is rejecting profitable trades!")
            report.append(f"│     - Review filter parameters")
            report.append(f"│     - Rejected win rate ({metrics.rejection_win_rate:.1f}%) > Accepted ({metrics.acceptance_win_rate:.1f}%)")
            report.append(f"│     - This indicates the filter is too strict or misconfigured")
        elif "DEGRADED" in metrics.rejection_accuracy:
            report.append(f"│  ⚠️  Caution: Filter may be rejecting some winners")
            report.append(f"│     - Monitor closely: Rejected ({metrics.rejection_win_rate:.1f}%) ≈ Accepted ({metrics.acceptance_win_rate:.1f}%)")
            report.append(f"│     - Consider relaxing restrictions slightly")
        elif "SOLID" in metrics.rejection_accuracy or "GOOD" in metrics.rejection_accuracy:
            report.append(f"│  ✅ Filter is working correctly!")
            report.append(f"│     - Accepted trades ({metrics.acceptance_win_rate:.1f}%) > Rejected ({metrics.rejection_win_rate:.1f}%)")
            report.append(f"│     - Filter is protecting capital from poor-quality signals")
        else:
            report.append(f"│  ➖ Filter performance is neutral")
            report.append(f"│     - Accepted ({metrics.acceptance_win_rate:.1f}%) ≈ Rejected ({metrics.rejection_win_rate:.1f}%)")
            report.append(f"│     - Monitor for improvements")
        
        report.append(f"└─")
        report.append("")
        
        # Summary
        report.append("=" * 80)
        report.append("END OF WEEKLY DISTRIBUTION REPORT")
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def should_generate_report(self) -> bool:
        """Check if 7 days have passed since last report"""
        now = datetime.now(timezone.utc)
        elapsed = now - self.last_report_time
        return elapsed >= timedelta(days=7)
    
    def generate_weekly_report(self) -> str:
        """Generate and save weekly report"""
        metrics = self.calculate_metrics()
        report = self.format_report(metrics)
        
        # Save to file
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        report_file = self.output_dir / f"weekly_distribution_report_{timestamp}.txt"
        
        with open(report_file, "a", encoding="utf-8") as f:
            f.write(report)
            f.write("\n\n")
        
        logger.info(f"[WEEKLY_DISTRIBUTION_REPORT] Report saved to: {report_file}")
        logger.info(f"[WEEKLY_DISTRIBUTION_REPORT] Weekly data reset for new period")
        
        # Reset for next week
        self.reset_weekly_data()
        
        return report
    
    def reset_weekly_data(self) -> None:
        """Reset tracking data for new week"""
        self.trades.clear()
        self.rejected_trades.clear()
        self.volatility_samples.clear()
        self.last_report_time = datetime.now(timezone.utc)
        self.current_week_start = self._get_week_start()
    
    def get_quick_summary(self) -> Dict[str, any]:
        """Get quick summary for logging"""
        metrics = self.calculate_metrics()
        
        return {
            "trades": metrics.total_trades,
            "wins": metrics.winning_trades,
            "win_rate": f"{metrics.win_rate:.1f}%",
            "mean_r": f"{metrics.mean_r_multiple:.2f}R",
            "sharpe": f"{metrics.sharpe_ratio:.3f}",
            "tail_loss_99": f"{metrics.tail_loss_99:.2f}%",
            "vol_corr": f"{metrics.volatility_return_correlation:+.3f}",
            "filter_accuracy": metrics.rejection_accuracy
        }

"""
Daily Risk Report Generator - Institutional Monitoring
Automatically tracks and reports key metrics every 24 hours
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class TradeStatus(Enum):
    """Trade status enumeration"""
    OPEN = "OPEN"
    WON = "WON"
    LOST = "LOST"
    BREAK_EVEN = "BREAK_EVEN"


@dataclass
class TradeRecord:
    """Individual trade record"""
    symbol: str
    direction: str  # BUY/SELL
    entry_price: float
    entry_time: datetime
    exit_price: Optional[float] = None
    exit_time: Optional[datetime] = None
    size: float = 0.0
    pnl: float = 0.0
    status: TradeStatus = TradeStatus.OPEN
    volatility_at_entry: float = 0.0
    position_multiplier: float = 1.0
    regime: str = "UNKNOWN"
    notes: str = ""
    strategy_meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RejectionRecord:
    """Trade rejection record"""
    symbol: str
    direction: str
    reason: str  # e.g., "LOW_LIQUIDITY", "POOR_SIGNAL_QUALITY", "RISK_LIMIT"
    timestamp: datetime
    signal_confidence: float = 0.0
    quality_score: float = 0.0


@dataclass
class DailyMetrics:
    """Daily aggregated metrics"""
    date: str
    trades_taken: int = 0
    trades_won: int = 0
    trades_lost: int = 0
    trades_breakeven: int = 0
    trades_rejected: int = 0
    
    total_pnl: float = 0.0
    win_rate: float = 0.0
    loss_rate: float = 0.0
    breakeven_rate: float = 0.0
    rejection_rate: float = 0.0
    
    avg_volatility: float = 0.0
    volatility_min: float = 0.0
    volatility_max: float = 0.0
    
    avg_position_multiplier: float = 1.0
    
    worst_trade: Optional[TradeRecord] = None
    best_trade: Optional[TradeRecord] = None
    largest_drawdown_streak: float = 0.0
    consecutive_losses: int = 0
    max_consecutive_losses: int = 0
    
    regime_breakdown: Dict[str, Dict] = field(default_factory=dict)  # {regime: {trades, pnl, win_rate}}
    rejection_breakdown: Dict[str, int] = field(default_factory=dict)  # {reason: count}


class DailyRiskReportGenerator:
    """Generates institutional-grade daily risk reports"""
    
    def __init__(self, output_dir: str = "reports/daily_risk"):
        self.logger = logging.getLogger(__name__)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # Current day's data
        self.trades: List[TradeRecord] = []
        self.rejections: List[RejectionRecord] = []
        self.volatilities: List[float] = []
        self.position_multipliers: List[float] = []
        self.rotation_events: List[Dict] = []  # Track position rotations for elite signals
        
        # Last report time
        self.last_report_time = datetime.now(datetime.now().astimezone().tzinfo)
        
        self.logger.info("[DAILY_RISK_REPORT] Initialized - Reports directory: %s", self.output_dir)
    
    def record_trade(self, trade: TradeRecord):
        """Record a completed trade"""
        self.trades.append(trade)
        if trade.volatility_at_entry > 0:
            self.volatilities.append(trade.volatility_at_entry)
        if trade.position_multiplier > 0:
            self.position_multipliers.append(trade.position_multiplier)
        
        self.logger.debug(
            "[TRADE_RECORD] %s %s | Entry=%.5f | Exit=%.5f | PnL=%.2f | Vol=%.3f%% | Mult=%.2f",
            trade.symbol, trade.direction, trade.entry_price, 
            trade.exit_price or 0, trade.pnl, trade.volatility_at_entry, trade.position_multiplier
        )
    
    def record_rejection(self, rejection: RejectionRecord):
        """Record a rejected trade"""
        self.rejections.append(rejection)
        self.logger.debug(
            "[REJECTION_RECORD] %s %s | Reason=%s | Confidence=%.0f%% | Quality=%.0f%%",
            rejection.symbol, rejection.direction, rejection.reason,
            rejection.signal_confidence * 100, rejection.quality_score * 100
        )
    
    def record_volatility_sample(self, volatility: float):
        """Record volatility sample"""
        if volatility > 0:
            self.volatilities.append(volatility)
    
    def record_position_multiplier(self, multiplier: float):
        """Record position multiplier used"""
        if multiplier > 0:
            self.position_multipliers.append(multiplier)
    
    def record_rotation_event(self, rotation_data: Dict):
        """Record an auto-rotation event (sacrificial trade closed for elite signal)"""
        self.rotation_events.append(rotation_data)
        self.logger.critical(
            "[ROTATION_RECORDED] Elite: %s (Score: %.1f) | Sacrificed: %s (PnL: $%.2f) | Success: %s",
            rotation_data.get('elite_signal', 'N/A'),
            rotation_data.get('elite_score', 0.0),
            rotation_data.get('sacrificed', 'N/A'),
            rotation_data.get('sacrificed_pnl', 0.0),
            rotation_data.get('success', False)
        )
    
    def should_generate_report(self) -> bool:
        """Check if 24 hours have passed since last report"""
        time_since_last_report = datetime.now(datetime.now().astimezone().tzinfo) - self.last_report_time
        return time_since_last_report >= timedelta(hours=24)
    
    def calculate_metrics(self) -> DailyMetrics:
        """Calculate all daily metrics from collected data"""
        metrics = DailyMetrics(date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        
        # Trade counts
        metrics.trades_taken = len(self.trades)
        metrics.trades_rejected = len(self.rejections)
        
        # Trade breakdown
        for trade in self.trades:
            if trade.status == TradeStatus.WON:
                metrics.trades_won += 1
            elif trade.status == TradeStatus.LOST:
                metrics.trades_lost += 1
            elif trade.status == TradeStatus.BREAK_EVEN:
                metrics.trades_breakeven += 1
            
            metrics.total_pnl += trade.pnl
        
        # Win rates
        if metrics.trades_taken > 0:
            metrics.win_rate = metrics.trades_won / metrics.trades_taken * 100
            metrics.loss_rate = metrics.trades_lost / metrics.trades_taken * 100
            metrics.breakeven_rate = metrics.trades_breakeven / metrics.trades_taken * 100
            metrics.rejection_rate = metrics.trades_rejected / (metrics.trades_taken + metrics.trades_rejected) * 100
        
        # Volatility stats
        if self.volatilities:
            metrics.avg_volatility = sum(self.volatilities) / len(self.volatilities)
            metrics.volatility_min = min(self.volatilities)
            metrics.volatility_max = max(self.volatilities)
        
        # Position sizing stats
        if self.position_multipliers:
            metrics.avg_position_multiplier = sum(self.position_multipliers) / len(self.position_multipliers)
        
        # Worst and best trades
        if self.trades:
            metrics.worst_trade = min(self.trades, key=lambda t: t.pnl)
            metrics.best_trade = max(self.trades, key=lambda t: t.pnl)
        
        # Drawdown streak
        consecutive_loss_streak = 0
        for trade in sorted(self.trades, key=lambda t: t.exit_time or t.entry_time):
            if trade.status == TradeStatus.LOST:
                consecutive_loss_streak += 1
                metrics.max_consecutive_losses = max(metrics.max_consecutive_losses, consecutive_loss_streak)
                metrics.consecutive_losses = consecutive_loss_streak
            else:
                consecutive_loss_streak = 0
            
            # Largest drawdown streak is cumulative PnL during losses
            metrics.largest_drawdown_streak = min(metrics.largest_drawdown_streak, metrics.total_pnl)
        
        # Regime breakdown
        regime_stats: Dict[str, Dict] = {}
        for trade in self.trades:
            regime = trade.regime
            if regime not in regime_stats:
                regime_stats[regime] = {
                    'trades': 0,
                    'pnl': 0.0,
                    'won': 0,
                    'lost': 0
                }
            
            regime_stats[regime]['trades'] += 1
            regime_stats[regime]['pnl'] += trade.pnl
            
            if trade.status == TradeStatus.WON:
                regime_stats[regime]['won'] += 1
            elif trade.status == TradeStatus.LOST:
                regime_stats[regime]['lost'] += 1
        
        # Calculate win rates per regime
        for regime, stats in regime_stats.items():
            if stats['trades'] > 0:
                stats['win_rate'] = stats['won'] / stats['trades'] * 100
            else:
                stats['win_rate'] = 0.0
        
        metrics.regime_breakdown = regime_stats
        
        # Rejection breakdown
        rejection_stats: Dict[str, int] = {}
        for rejection in self.rejections:
            reason = rejection.reason
            rejection_stats[reason] = rejection_stats.get(reason, 0) + 1
        
        metrics.rejection_breakdown = rejection_stats
        
        return metrics
    
    def format_report(self, metrics: DailyMetrics) -> str:
        """Format metrics into a professional report"""
        lines = [
            "=" * 80,
            "DAILY RISK REPORT - INSTITUTIONAL MONITORING",
            "=" * 80,
            f"\nReport Date: {metrics.date}\n",
            
            # TRADES SECTION
            "┌─ TRADES OVERVIEW",
            "├─ Executed Trades:        {:>6}".format(metrics.trades_taken),
            "├─ Won:                    {:>6} ({:>5.1f}%)".format(
                metrics.trades_won, metrics.win_rate
            ),
            "├─ Lost:                   {:>6} ({:>5.1f}%)".format(
                metrics.trades_lost, metrics.loss_rate
            ),
            "├─ Break-even:             {:>6} ({:>5.1f}%)".format(
                metrics.trades_breakeven, metrics.breakeven_rate
            ),
            "├─ Max Consecutive Losses: {:>6}".format(metrics.max_consecutive_losses),
            "└─ Total P&L:              ${:>10,.2f}".format(metrics.total_pnl),
            
            # REJECTION SECTION
            f"\n┌─ TRADE REJECTIONS",
            f"├─ Total Rejected:         {metrics.trades_rejected:>6}",
            f"├─ Rejection Rate:         {metrics.rejection_rate:>5.1f}%",
        ]
        
        # Rejection breakdown
        if metrics.rejection_breakdown:
            for reason, count in sorted(metrics.rejection_breakdown.items(), key=lambda x: x[1], reverse=True):
                pct = (count / metrics.trades_rejected * 100) if metrics.trades_rejected > 0 else 0
                lines.append(f"├─ {reason:.<30} {count:>4} ({pct:>5.1f}%)")
        
        lines.append("└─")
        
        # VOLATILITY SECTION
        lines.extend([
            f"\n┌─ MARKET VOLATILITY",
            f"├─ Average:                {metrics.avg_volatility:>6.3f}%",
            f"├─ Minimum:                {metrics.volatility_min:>6.3f}%",
            f"├─ Maximum:                {metrics.volatility_max:>6.3f}%",
            f"└─ Samples:                {len(self.volatilities):>6}",
        ])
        
        # POSITION SIZING SECTION
        lines.extend([
            f"\n┌─ POSITION SIZING",
            f"├─ Average Multiplier:     {metrics.avg_position_multiplier:>6.2f}x",
            f"├─ Multiplier Range:       0.50x - 1.00x (volatility adjusted)",
            f"└─ Trades Affected:        {len(self.position_multipliers):>6}",
        ])
        
        # WORST TRADE SECTION
        if metrics.worst_trade:
            wt = metrics.worst_trade
            lines.extend([
                f"\n┌─ WORST TRADE",
                f"├─ Pair:                   {wt.symbol}",
                f"├─ Direction:              {wt.direction}",
                f"├─ Entry:                  {wt.entry_price:.5f}",
                f"├─ Exit:                   {wt.exit_price:.5f}" if wt.exit_price else f"├─ Exit:                   OPEN",
                f"├─ P&L:                    ${wt.pnl:>10,.2f}",
                f"├─ Volatility at Entry:    {wt.volatility_at_entry:.3f}%",
                f"├─ Position Multiplier:    {wt.position_multiplier:.2f}x",
                f"├─ Regime:                 {wt.regime}",
                f"└─ Entry Time:             {wt.entry_time.strftime('%Y-%m-%d %H:%M:%S')}",
            ])
        
        # BEST TRADE SECTION
        if metrics.best_trade:
            bt = metrics.best_trade
            lines.extend([
                f"\n┌─ BEST TRADE",
                f"├─ Pair:                   {bt.symbol}",
                f"├─ Direction:              {bt.direction}",
                f"├─ Entry:                  {bt.entry_price:.5f}",
                f"├─ Exit:                   {bt.exit_price:.5f}" if bt.exit_price else f"├─ Exit:                   OPEN",
                f"├─ P&L:                    ${bt.pnl:>10,.2f}",
                f"├─ Volatility at Entry:    {bt.volatility_at_entry:.3f}%",
                f"├─ Position Multiplier:    {bt.position_multiplier:.2f}x",
                f"├─ Regime:                 {bt.regime}",
                f"└─ Entry Time:             {bt.entry_time.strftime('%Y-%m-%d %H:%M:%S')}",
            ])
        
        # REGIME BREAKDOWN SECTION
        if metrics.regime_breakdown:
            lines.extend(["\n┌─ P&L BY REGIME"])
            for regime in sorted(metrics.regime_breakdown.keys()):
                stats = metrics.regime_breakdown[regime]
                lines.extend([
                    f"├─ {regime}",
                    f"│  ├─ Trades:    {stats['trades']:>3}",
                    f"│  ├─ Won:       {stats['won']:>3} ({stats['win_rate']:>5.1f}%)",
                    f"│  ├─ Lost:      {stats['lost']:>3}",
                    f"│  └─ P&L:       ${stats['pnl']:>10,.2f}",
                ])
            lines.append("└─")
        
        # AUTO-ROTATION ENGINE ACTIVITY SECTION
        if hasattr(self, 'rotation_events') and self.rotation_events:
            total_rotations = len(self.rotation_events)
            successful_rotations = sum(1 for r in self.rotation_events if r.get('success', False))
            total_sacrificial_pnl = sum(r.get('sacrificed_pnl', 0.0) for r in self.rotation_events)
            
            lines.extend([
                f"\n┌─ AUTO-ROTATION ENGINE (Elite Signal Priority)",
                f"├─ Total Rotations Initiated: {total_rotations}",
                f"├─ Successful Rotations:      {successful_rotations}",
                f"├─ Success Rate:              {(successful_rotations/total_rotations*100 if total_rotations > 0 else 0):>5.1f}%",
                f"├─ Cumulative Sacrificial PnL: ${total_sacrificial_pnl:>10,.2f}",
                f"├─",
                f"├─ Recent Rotation Events (last 5):",
            ])
            
            # List recent rotation events
            for i, event in enumerate(self.rotation_events[-5:], 1):
                lines.extend([
                    f"│  ├─ #{i}: Elite {event.get('elite_signal', 'N/A')} Score={event.get('elite_score', 0):.1f}",
                    f"│  │  ├─ Sacrificed: {event.get('sacrificed', 'N/A')} "
                    f"(PnL: ${event.get('sacrificed_pnl', 0):.2f}, Age: {event.get('sacrificed_hold_minutes', 0):.1f}min)",
                    f"│  │  └─ Status: {'✓ SUCCESS' if event.get('success', False) else '✗ FAILED'}",
                ])
            
            lines.append("└─")
        
        # SUMMARY SECTION
        lines.extend([
            f"\n┌─ DRAWDOWN ANALYSIS",
            f"├─ Largest Drawdown Streak: ${abs(metrics.largest_drawdown_streak):>10,.2f}",
            f"├─ Max Consecutive Losses:  {metrics.max_consecutive_losses:>6} trades",
            f"└─",
            
            "\n" + "=" * 80,
        ])
        
        return "\n".join(lines)
    
    def generate_daily_report(self) -> str:
        """Generate complete daily report"""
        metrics = self.calculate_metrics()
        report = self.format_report(metrics)
        
        # Log report
        self.logger.info(report)
        
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d")
        report_file = self.output_dir / f"daily_risk_report_{timestamp}.txt"
        
        try:
            with open(report_file, 'a', encoding='utf-8') as f:
                f.write(f"\n\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n")
                f.write(report)
                f.write(f"\n\n")
            
            self.logger.info("[DAILY_RISK_REPORT] Report saved to: %s", report_file)
        except Exception as e:
            self.logger.error("[DAILY_RISK_REPORT] Failed to save report: %s", e)
        
        # Reset for next day
        self.reset_daily_data()
        self.last_report_time = datetime.now(datetime.now().astimezone().tzinfo)
        
        return report
    
    def reset_daily_data(self):
        """Reset daily data for next period"""
        self.trades.clear()
        self.rejections.clear()
        self.volatilities.clear()
        self.position_multipliers.clear()
        self.rotation_events.clear()  # Also reset rotation events
        
        self.logger.info("[DAILY_RISK_REPORT] Daily data reset for new period")
    
    def get_quick_stats(self) -> Dict:
        """Get current day's quick statistics (for logging)"""
        metrics = self.calculate_metrics()
        return {
            'trades_taken': metrics.trades_taken,
            'trades_rejected': metrics.trades_rejected,
            'win_rate': metrics.win_rate,
            'total_pnl': metrics.total_pnl,
            'avg_volatility': metrics.avg_volatility,
            'avg_position_multiplier': metrics.avg_position_multiplier,
            'max_consecutive_losses': metrics.max_consecutive_losses,
        }

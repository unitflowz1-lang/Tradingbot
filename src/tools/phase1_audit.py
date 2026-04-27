"""
PHASE 1: DETAILED PERFORMANCE AUDIT
Extract current metrics from trade history and generate baseline report
for the $100 account running v8.5 logic
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Tuple, Optional
import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics"""
    period_name: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    expectancy_usd: float
    total_pnl_usd: float
    max_drawdown_usd: float
    max_drawdown_pct: float
    sharpe_ratio: float
    calmar_ratio: float
    avg_rr_ratio: float
    avg_winning_trade: float
    avg_losing_trade: float
    consecutive_wins: int
    consecutive_losses: int
    
    def __str__(self):
        period_label = f"  {self.period_name}  ".center(73)
        return f"""
+═══════════════════════════════════════════════════════════════════════════+
|                    PHASE 1: PERFORMANCE AUDIT REPORT                      |
+═══════════════════════════════════════════════════════════════════════════+
| {period_label} |
+═══════════════════════════════════════════════════════════════════════════+

TRADE STATISTICS:
  Total Trades:                 {self.total_trades}
  Winning Trades:               {self.winning_trades} ({self.win_rate_pct:.2f}%)
  Losing Trades:                {self.losing_trades}
  Avg Consecutive Wins:         {self.consecutive_wins}
  Avg Consecutive Losses:       {self.consecutive_losses}

PROFITABILITY:
  Total P&L:                    ${self.total_pnl_usd:+.2f}
  Expectancy ($/trade):         ${self.expectancy_usd:+.2f}
  Avg Winning Trade:            ${self.avg_winning_trade:.2f}
  Avg Losing Trade:             ${self.avg_losing_trade:.2f}
  Profit Factor:                {self.profit_factor:.2f}x
  R:R Ratio:                    {self.avg_rr_ratio:.2f}

RISK METRICS:
  Max Drawdown ($):             ${abs(self.max_drawdown_usd):.2f}
  Max Drawdown (%):             {self.max_drawdown_pct:.2f}% (of $100)
  Sharpe Ratio:                 {self.sharpe_ratio:.2f}
  Calmar Ratio:                 {self.calmar_ratio:.2f}

TARGET ASSESSMENT:
  ✓ Win Rate (55-65%):          {self._check_target(self.win_rate_pct, 55, 65)}
  ✓ Profit Factor (>1.3):       {self._check_gt(self.profit_factor, 1.3)}
  ✓ Max DD (<15%):              {self._check_lt(self.max_drawdown_pct, 15.0)}

+═══════════════════════════════════════════════════════════════════════════+
"""
    
    def _check_target(self, value, min_val, max_val):
        if min_val <= value <= max_val:
            return f"✅ {value:.2f}% (In Target)"
        elif value < min_val:
            return f"⚠️  {value:.2f}% (Below {min_val}%)"
        else:
            return f"⚠️  {value:.2f}% (Above {max_val}%)"
    
    def _check_gt(self, value, threshold):
        if value >= threshold:
            return f"✅ {value:.2f} (Meets Target)"
        else:
            return f"⚠️  {value:.2f} (Below {threshold})"
    
    def _check_lt(self, value, threshold):
        if value <= threshold:
            return f"✅ {value:.2f}% (Within Target)"
        else:
            return f"⚠️  {value:.2f}% (Exceeds {threshold}%)"


class PerformanceAuditor:
    """Audits current trading performance"""
    
    def __init__(self, initial_balance: float = 100.0):
        self.workspace_root = Path(__file__).parent.parent.parent
        self.initial_balance = initial_balance
        self.logger = logger
    
    def load_trade_history(self) -> List[Dict]:
        """Load trade history from transactional registry or performance matrix"""
        trades = []
        
        # Try transactional registry first
        registry_path = self.workspace_root / "data" / "transactional_registry.json"
        if registry_path.exists():
            try:
                with open(registry_path, 'r') as f:
                    registry = json.load(f)
                    if isinstance(registry, dict) and 'tickets' in registry:
                        for ticket_id, ticket_data in registry['tickets'].items():
                            if isinstance(ticket_data, dict) and ticket_data.get('closed'):
                                trades.append({
                                    'ticket': ticket_id,
                                    'symbol': ticket_data.get('symbol', 'UNKNOWN'),
                                    'direction': ticket_data.get('direction', 'UNKNOWN'),
                                    'entry_price': float(ticket_data.get('entry_price', 0)),
                                    'exit_price': float(ticket_data.get('exit_price', 0)),
                                    'volume': float(ticket_data.get('volume', 0)),
                                    'pnl': float(ticket_data.get('pnl', 0)),
                                    'pnl_pips': float(ticket_data.get('pnl_pips', 0)),
                                    'open_time': ticket_data.get('open_time', ''),
                                    'close_time': ticket_data.get('close_time', ''),
                                    'rr_ratio': float(ticket_data.get('rr_ratio', 1.0)),
                                })
            except Exception as e:
                self.logger.warning(f"Could not load transactional registry: {e}")
        
        # Try performance matrix as fallback
        if not trades:
            perf_path = self.workspace_root / "data" / "performance_matrix.json"
            if perf_path.exists():
                try:
                    with open(perf_path, 'r') as f:
                        perf_data = json.load(f)
                        if isinstance(perf_data, dict) and 'exit_records' in perf_data:
                            for record in perf_data['exit_records']:
                                trades.append({
                                    'ticket': record.get('ticket', 'UNKNOWN'),
                                    'symbol': record.get('symbol', 'UNKNOWN'),
                                    'direction': record.get('direction', 'UNKNOWN'),
                                    'entry_price': float(record.get('entry_price', 0)),
                                    'exit_price': float(record.get('exit_price', 0)),
                                    'volume': float(record.get('volume', 0)),
                                    'pnl': float(record.get('pnl', 0)),
                                    'pnl_pips': float(record.get('pnl_pips', 0)),
                                    'open_time': record.get('open_time', ''),
                                    'close_time': record.get('close_time', ''),
                                    'rr_ratio': float(record.get('rr_ratio', 1.0)),
                                })
                except Exception as e:
                    self.logger.warning(f"Could not load performance matrix: {e}")
        
        self.logger.info(f"[AUDIT] Loaded {len(trades)} closed trades")
        return trades
    
    def calculate_metrics(self, trades: List[Dict], period_name: str = "Current") -> PerformanceMetrics:
        """Calculate comprehensive performance metrics"""
        
        if not trades:
            self.logger.warning("[AUDIT] No trades available for metrics calculation")
            return self._create_empty_metrics(period_name)
        
        pnls = np.array([t['pnl'] for t in trades])
        
        # Basic counts
        winning_trades = len([p for p in pnls if p > 0.0])
        losing_trades = len([p for p in pnls if p < 0.0])
        total_trades = len(trades)
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Profitability
        total_pnl = float(np.sum(pnls))
        wins_sum = float(np.sum([p for p in pnls if p > 0]))
        losses_sum = float(np.sum([p for p in pnls if p < 0]))
        profit_factor = wins_sum / abs(losses_sum) if losses_sum != 0 else (1.0 if wins_sum > 0 else 0.0)
        
        # Expectancy
        expectancy = total_pnl / total_trades if total_trades > 0 else 0
        
        # Drawdown
        cumulative_pnl = np.cumsum(pnls)
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdowns = cumulative_pnl - running_max
        max_drawdown = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0
        max_drawdown_pct = (abs(max_drawdown) / self.initial_balance * 100) if self.initial_balance > 0 else 0
        
        # Sharpe Ratio (annualized)
        if len(pnls) > 1 and np.std(pnls) > 0:
            daily_returns = pnls / self.initial_balance
            sharpe = np.sqrt(252) * (np.mean(daily_returns) / np.std(daily_returns))
        else:
            sharpe = 0
        
        # Calmar Ratio = annual return / max drawdown
        if max_drawdown != 0:
            annual_return = (total_pnl / self.initial_balance) * (252 / len(trades)) if len(trades) > 0 else 0
            calmar = annual_return / abs(max_drawdown / self.initial_balance) if max_drawdown != 0 else 0
        else:
            calmar = 0
        
        # R:R Ratio
        rr_ratios = [t['rr_ratio'] for t in trades if t.get('rr_ratio', 0) > 0]
        avg_rr = np.mean(rr_ratios) if rr_ratios else 0
        
        # Avg trades
        avg_winning = np.mean([p for p in pnls if p > 0]) if winning_trades > 0 else 0
        avg_losing = np.mean([p for p in pnls if p < 0]) if losing_trades > 0 else 0
        
        # Consecutive
        consec_wins = self._max_consecutive(pnls > 0)
        consec_losses = self._max_consecutive(pnls < 0)
        
        return PerformanceMetrics(
            period_name=period_name,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=float(win_rate),
            profit_factor=float(profit_factor),
            expectancy_usd=float(expectancy),
            total_pnl_usd=float(total_pnl),
            max_drawdown_usd=float(max_drawdown),
            max_drawdown_pct=float(max_drawdown_pct),
            sharpe_ratio=float(sharpe),
            calmar_ratio=float(calmar),
            avg_rr_ratio=float(avg_rr),
            avg_winning_trade=float(avg_winning),
            avg_losing_trade=float(avg_losing),
            consecutive_wins=int(consec_wins),
            consecutive_losses=int(consec_losses),
        )
    
    def _create_empty_metrics(self, period_name: str) -> PerformanceMetrics:
        """Create empty metrics for when no trades exist"""
        return PerformanceMetrics(
            period_name=period_name,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            expectancy_usd=0.0,
            total_pnl_usd=0.0,
            max_drawdown_usd=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            calmar_ratio=0.0,
            avg_rr_ratio=0.0,
            avg_winning_trade=0.0,
            avg_losing_trade=0.0,
            consecutive_wins=0,
            consecutive_losses=0,
        )
    
    def _max_consecutive(self, condition: np.ndarray) -> int:
        """Find max consecutive True values"""
        if len(condition) == 0:
            return 0
        
        max_consec = 0
        current_consec = 0
        
        for val in condition:
            if val:
                current_consec += 1
                max_consec = max(max_consec, current_consec)
            else:
                current_consec = 0
        
        return max_consec
    
    def save_audit_report(self, metrics: PerformanceMetrics) -> Path:
        """Save audit report to file"""
        report_path = self.workspace_root / "phase1_performance_audit.json"
        
        report = {
            "timestamp": datetime.now().isoformat(),
            "account_balance": self.initial_balance,
            "metrics": asdict(metrics),
            "assessment": {
                "win_rate_target": "55-65%",
                "profit_factor_target": ">1.3",
                "max_drawdown_target": "<15%",
            }
        }
        
        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        self.logger.info(f"[AUDIT] ✅ Report saved to {report_path}")
        return report_path
    
    async def run_audit(self) -> PerformanceMetrics:
        """Run complete performance audit"""
        self.logger.info("\n" + "="*80)
        self.logger.info("PHASE 1: DETAILED PERFORMANCE AUDIT")
        self.logger.info("="*80)
        
        # Load trades
        trades = self.load_trade_history()
        
        # Calculate metrics
        metrics = self.calculate_metrics(trades, "Current v8.5 Configuration")
        
        # Save report
        self.save_audit_report(metrics)
        
        # Print report
        print(str(metrics))
        self.logger.info(str(metrics))
        
        return metrics


async def main():
    """Execute Phase 1"""
    auditor = PerformanceAuditor(initial_balance=100.0)
    await auditor.run_audit()
    
    logger.info("\n" + "="*80)
    logger.info("✅ PHASE 1 COMPLETE: Performance audit finished")
    logger.info("="*80)
    logger.info("\n📊 Ready for Phase 2: Multi-Timeframe Walk-Forward Optimization")
    logger.info("Run: python src/tools/phase2_deepanalysis.py\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

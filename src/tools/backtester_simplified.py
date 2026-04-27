"""
Simplified Phase 1: Baseline Metrics from Existing Trade Data
Analyzes historical trades to establish baseline performance metrics
without requiring live MT5 connection
"""

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Tuple
import numpy as np

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


@dataclass
class BaselineMetrics:
    """Baseline metrics from current 0.30/0.70 configuration"""
    start_date: str
    end_date: str
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    total_pnl: float
    avg_trade_pnl: float
    max_drawdown_pct: float
    sharpe_ratio: float
    avg_rr_ratio: float
    
    def __str__(self):
        return f"""
╔══════════════════════════════════════════════════════╗
║            BASELINE METRICS (0.30 / 0.70)            ║
╚══════════════════════════════════════════════════════╝
Period:               {self.start_date} → {self.end_date}
Total Trades:        {self.total_trades}
Winning Trades:      {self.winning_trades} ({self.win_rate_pct:.1f}%)
Losing Trades:       {self.losing_trades}
Profit Factor:       {self.profit_factor:.2f}x
Total P&L:           ${self.total_pnl:,.2f}
Avg P&L per Trade:   ${self.avg_trade_pnl:,.2f}
Max Drawdown:        {self.max_drawdown_pct:.2f}%
Sharpe Ratio:        {self.sharpe_ratio:.2f}
Avg R:R Ratio:       {self.avg_rr_ratio:.2f}
"""


def load_trade_history() -> List[Dict]:
    """Load trade history from bot's transactional registry or trade logs"""
    trade_dir = Path(__file__).parent.parent.parent / "data" / "trades"
    
    trades = []
    
    # Try to load from transactional registry
    registry_path = Path(__file__).parent.parent.parent / "data" / "transactional_registry.json"
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
                                'entry_price': ticket_data.get('entry_price', 0),
                                'exit_price': ticket_data.get('exit_price', 0),
                                'volume': ticket_data.get('volume', 0),
                                'pnl': ticket_data.get('pnl', 0),
                                'pnl_pips': ticket_data.get('pnl_pips', 0),
                                'open_time': ticket_data.get('open_time', ''),
                                'close_time': ticket_data.get('close_time', ''),
                                'rr_ratio': ticket_data.get('rr_ratio', 0),
                            })
        except Exception as e:
            logger.warning(f"Could not load transactional registry: {e}")
    
    # Try to load from performance matrix
    perf_path = Path(__file__).parent.parent.parent / "data" / "performance_matrix.json"
    if perf_path.exists() and not trades:
        try:
            with open(perf_path, 'r') as f:
                perf_data = json.load(f)
                if isinstance(perf_data, dict) and 'exit_records' in perf_data:
                    for record in perf_data['exit_records']:
                        trades.append({
                            'ticket': record.get('ticket', 'UNKNOWN'),
                            'symbol': record.get('symbol', 'UNKNOWN'),
                            'direction': record.get('direction', 'UNKNOWN'),
                            'entry_price': record.get('entry_price', 0),
                            'exit_price': record.get('exit_price', 0),
                            'volume': record.get('volume', 0),
                            'pnl': record.get('pnl', 0),
                            'pnl_pips': record.get('pnl_pips', 0),
                            'open_time': record.get('open_time', ''),
                            'close_time': record.get('close_time', ''),
                            'rr_ratio': record.get('rr_ratio', 0),
                        })
        except Exception as e:
            logger.warning(f"Could not load performance matrix: {e}")
    
    logger.info(f"[PHASE 1] Loaded {len(trades)} historical closed trades")
    return trades


def calculate_baseline_metrics(trades: List[Dict]) -> BaselineMetrics:
    """Calculate baseline metrics from trade history"""
    
    if not trades:
        logger.warning("[PHASE 1] No trades found - creating default baseline")
        return BaselineMetrics(
            start_date="N/A",
            end_date="N/A",
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            win_rate_pct=0.0,
            profit_factor=0.0,
            total_pnl=0.0,
            avg_trade_pnl=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            avg_rr_ratio=0.0,
        )
    
    # Extract P&L data
    pnls = [float(t.get('pnl', 0)) for t in trades]
    winning_trades = len([p for p in pnls if p > 0])
    losing_trades = len([p for p in pnls if p < 0])
    total_trades = len(trades)
    
    # Calculate metrics
    total_pnl = sum(pnls)
    avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else 0
    win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0
    
    # Profit factor
    wins = sum([p for p in pnls if p > 0])
    losses = abs(sum([p for p in pnls if p < 0]))
    profit_factor = wins / losses if losses > 0 else (1.0 if wins > 0 else 0.0)
    
    # Sharpe ratio (assuming 252 trading days/year, 6.5 hours/day)
    pnl_array = np.array(pnls)
    if len(pnl_array) > 1:
        daily_returns = pnl_array / 100  # Normalize
        sharpe_ratio = np.sqrt(252) * (np.mean(daily_returns) / np.std(daily_returns)) if np.std(daily_returns) > 0 else 0
    else:
        sharpe_ratio = 0
    
    # Max drawdown
    cumulative_pnl = np.cumsum(pnl_array)
    running_max = np.maximum.accumulate(cumulative_pnl)
    drawdown = (cumulative_pnl - running_max) / (running_max + 1)  # Avoid division by zero
    max_drawdown_pct = abs(np.min(drawdown)) * 100 if len(drawdown) > 0 else 0
    
    # Average R:R ratio
    rr_ratios = [float(t.get('rr_ratio', 0)) for t in trades if t.get('rr_ratio', 0) > 0]
    avg_rr_ratio = np.mean(rr_ratios) if rr_ratios else 0
    
    # Date range
    close_times = [t.get('close_time', '') for t in trades if t.get('close_time')]
    start_date = min(close_times) if close_times else "Unknown"
    end_date = max(close_times) if close_times else "Unknown"
    
    return BaselineMetrics(
        start_date=str(start_date)[:10],
        end_date=str(end_date)[:10],
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate_pct=win_rate_pct,
        profit_factor=profit_factor,
        total_pnl=total_pnl,
        avg_trade_pnl=avg_trade_pnl,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        avg_rr_ratio=avg_rr_ratio,
    )


async def main():
    """Main baseline calculation"""
    logger.info("\n" + "="*60)
    logger.info("PHASE 1: BASELINE METRICS CALCULATION")
    logger.info("="*60)
    
    # Load historical trades
    trades = load_trade_history()
    
    # Calculate baseline metrics
    metrics = calculate_baseline_metrics(trades)
    
    # Save to file
    report_path = Path(__file__).parent.parent.parent / "backtest_baseline_report.json"
    report = {
        'optimization_method': 'BASELINE_CURRENT_CONFIG',
        'ml_weight': 0.70,
        'technical_weight': 0.30,
        'baseline_metrics': asdict(metrics),
        'generated_at': datetime.now().isoformat(),
    }
    
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    logger.info(f"[PHASE 1] ✅ Baseline report saved to {report_path}")
    logger.info(str(metrics))
    
    logger.info("\n" + "="*60)
    logger.info("PHASE 1 COMPLETE: Baseline established")
    logger.info("="*60)
    logger.info("\n✅ Ready for Phase 2: Grid Search Optimization")
    logger.info("Run: python src/tools/walkforward_optimizer.py\n")


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
DRY RUN RESULTS ANALYZER
=========================
Analyzes dry run logs and generates comprehensive performance report.

Usage:
    python scripts/analyze_dry_run_results.py [--log-file logs/dry_run_*.log]
"""

import re
import sys
import json
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DryRunAnalyzer:
    """Analyze dry run performance from log files"""
    
    def __init__(self, log_file: str):
        self.log_file = Path(log_file)
        self.trades = []
        self.signals = []
        self.events = defaultdict(list)
        
    def parse_log(self):
        """Parse log file and extract all relevant data"""
        if not self.log_file.exists():
            logger.error(f"Log file not found: {self.log_file}")
            return False
        
        logger.info(f"Parsing log file: {self.log_file}")
        
        with open(self.log_file, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
        
        for line in lines:
            self._parse_line(line.strip())
        
        logger.info(f"Parsed {len(self.trades)} trades, {len(self.signals)} signals")
        return True
    
    def _parse_line(self, line: str):
        """Parse single log line"""
        # Extract trades
        if any(kw in line for kw in ['Trade closed', 'Position closed', 'EXIT']):
            trade = self._extract_trade(line)
            if trade:
                self.trades.append(trade)
        
        # Extract signals
        if 'SIGNAL_ADMITTED' in line or 'Signal quality:' in line:
            signal = self._extract_signal(line)
            if signal:
                self.signals.append(signal)
        
        # Extract events
        if 'SPREAD_TRAP' in line:
            self.events['spread_trap'].append(line)
        if 'AGGRESSIVE_COMPOUND' in line:
            self.events['compounding'].append(line)
        if 'DRAWDOWN' in line or 'MAX_DD' in line:
            self.events['drawdown'].append(line)
    
    def _extract_trade(self, line: str) -> dict:
        """Extract trade data from log line"""
        trade = {}
        
        # Extract PnL
        pnl_match = re.search(r'(?:PnL|profit)[\s:]*\$?([-\d.]+)', line, re.IGNORECASE)
        if pnl_match:
            trade['pnl'] = float(pnl_match.group(1))
        
        # Extract symbol
        symbol_match = re.search(r'\[([A-Z]+)\]', line)
        if symbol_match:
            trade['symbol'] = symbol_match.group(1)
        
        # Extract timestamp
        time_match = re.search(r'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', line)
        if time_match:
            trade['timestamp'] = time_match.group(1)
        
        return trade if 'pnl' in trade else None
    
    def _extract_signal(self, line: str) -> dict:
        """Extract signal data from log line"""
        signal = {}
        
        # Extract quality score
        quality_match = re.search(r'quality[\s:]*([\d.]+)%?', line, re.IGNORECASE)
        if quality_match:
            signal['quality'] = float(quality_match.group(1))
        
        # Extract symbol
        symbol_match = re.search(r'\[([A-Z]+)\]', line)
        if symbol_match:
            signal['symbol'] = symbol_match.group(1)
        
        return signal
    
    def calculate_metrics(self) -> dict:
        """Calculate comprehensive metrics"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'total_pnl': 0.0,
                'status': 'NO_TRADES'
            }
        
        # Basic metrics
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        losing_trades = [t for t in self.trades if t['pnl'] <= 0]
        
        win_rate = len(winning_trades) / total_trades
        total_pnl = sum(t['pnl'] for t in self.trades)
        
        gross_profit = sum(t['pnl'] for t in winning_trades)
        gross_loss = abs(sum(t['pnl'] for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Equity and drawdown
        equity = 10000.0
        peak_equity = equity
        max_drawdown = 0.0
        
        for trade in self.trades:
            equity += trade['pnl']
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        # Consecutive streaks
        max_win_streak = 0
        max_loss_streak = 0
        current_streak = 0
        
        for trade in self.trades:
            if trade['pnl'] > 0:
                current_streak = max(1, current_streak) if current_streak >= 0 else 1
                max_win_streak = max(max_win_streak, current_streak)
            else:
                current_streak = min(-1, current_streak) if current_streak <= 0 else -1
                max_loss_streak = max(max_loss_streak, abs(current_streak))
        
        # Signal quality
        avg_signal_quality = 0.0
        if self.signals:
            qualities = [s.get('quality', 0) for s in self.signals if 'quality' in s]
            avg_signal_quality = sum(qualities) / len(qualities) if qualities else 0.0
        
        # Events count
        spread_trap_count = len(self.events['spread_trap'])
        compounding_count = len(self.events['compounding'])
        
        # Determine status
        if win_rate >= 0.52 and profit_factor >= 1.3 and max_drawdown <= 12:
            status = 'PASS'
        elif win_rate >= 0.48 and profit_factor >= 1.0 and max_drawdown <= 15:
            status = 'CAUTION'
        else:
            status = 'FAIL'
        
        return {
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': win_rate,
            'profit_factor': profit_factor if profit_factor != float('inf') else 999.99,
            'total_pnl': total_pnl,
            'final_equity': equity,
            'max_drawdown': max_drawdown,
            'max_win_streak': max_win_streak,
            'max_loss_streak': max_loss_streak,
            'avg_signal_quality': avg_signal_quality,
            'spread_trap_blocks': spread_trap_count,
            'compounding_triggers': compounding_count,
            'status': status
        }
    
    def generate_report(self, output_file: str = None):
        """Generate comprehensive report"""
        metrics = self.calculate_metrics()
        
        # Print report
        print("\n" + "="*80)
        print("  DRY RUN PERFORMANCE REPORT")
        print("="*80)
        print()
        print(f"  Log File: {self.log_file}")
        print(f"  Analysis Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Core metrics
        print("─"*80)
        print("  CORE METRICS")
        print("─"*80)
        print(f"  Total Trades:        {metrics['total_trades']}")
        print(f"  Winning Trades:      {metrics['winning_trades']}")
        print(f"  Losing Trades:       {metrics['losing_trades']}")
        print(f"  Win Rate:            {metrics['win_rate']*100:.2f}%")
        print(f"  Profit Factor:       {metrics['profit_factor']:.2f}")
        print(f"  Total PnL:           ${metrics['total_pnl']:.2f}")
        print(f"  Final Equity:        ${metrics['final_equity']:.2f}")
        print(f"  Max Drawdown:        {metrics['max_drawdown']:.2f}%")
        print()
        
        # Streak analysis
        print("─"*80)
        print("  STREAK ANALYSIS")
        print("─"*80)
        print(f"  Max Win Streak:      {metrics['max_win_streak']}")
        print(f"  Max Loss Streak:     {metrics['max_loss_streak']}")
        print()
        
        # Signal quality
        print("─"*80)
        print("  SIGNAL QUALITY")
        print("─"*80)
        print(f"  Total Signals:       {len(self.signals)}")
        print(f"  Avg Quality Score:   {metrics['avg_signal_quality']:.2f}%")
        print(f"  Spread Trap Blocks:  {metrics['spread_trap_blocks']}")
        print(f"  Compounding Triggers:{metrics['compounding_triggers']}")
        print()
        
        # Success criteria
        print("─"*80)
        print("  SUCCESS CRITERIA")
        print("─"*80)
        
        criteria = [
            ("Win Rate ≥ 52%", metrics['win_rate'] >= 0.52, metrics['win_rate']*100),
            ("Profit Factor ≥ 1.3", metrics['profit_factor'] >= 1.3, metrics['profit_factor']),
            ("Max Drawdown ≤ 12%", metrics['max_drawdown'] <= 12, metrics['max_drawdown']),
            ("Trade Count ≥ 20", metrics['total_trades'] >= 20, metrics['total_trades']),
        ]
        
        all_pass = True
        for name, passed, value in criteria:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {name:<25} {status}")
            if not passed:
                all_pass = False
        
        print()
        
        # Final verdict
        print("─"*80)
        print("  FINAL VERDICT")
        print("─"*80)
        
        if metrics['status'] == 'PASS':
            print("  ✅ RECOMMENDATION: GO LIVE")
            print()
            print("  Your strategy has passed the dry run test with acceptable metrics.")
            print("  You can proceed to live trading with confidence.")
            print()
            print("  Next Steps:")
            print("  1. Set DRY_RUN=0 in .env")
            print("  2. Start with smaller position sizes (50% of normal)")
            print("  3. Monitor closely for first 24 hours")
            print("  4. Gradually increase to full position sizes")
        elif metrics['status'] == 'CAUTION':
            print("  ⚠️  RECOMMENDATION: ADJUST & RETEST")
            print()
            print("  Your strategy shows marginal performance.")
            print("  Consider the following adjustments:")
            print("  - Increase quality floor (reduce false signals)")
            print("  - Widen ATR stop loss (reduce premature exits)")
            print("  - Reduce position size (lower drawdown)")
            print()
            print("  Retest for another 2-3 days before going live.")
        else:
            print("  ❌ RECOMMENDATION: DO NOT GO LIVE")
            print()
            print("  Your strategy is not ready for live trading.")
            print("  The metrics indicate significant issues:")
            if metrics['win_rate'] < 0.48:
                print(f"  - Win rate too low ({metrics['win_rate']*100:.2f}%)")
            if metrics['profit_factor'] < 1.0:
                print(f"  - Losing money (PF={metrics['profit_factor']:.2f})")
            if metrics['max_drawdown'] > 15:
                print(f"  - Excessive drawdown ({metrics['max_drawdown']:.2f}%)")
            print()
            print("  Next Steps:")
            print("  1. Review strategy logic")
            print("  2. Analyze losing trades for patterns")
            print("  3. Adjust parameters")
            print("  4. Run another dry test")
        
        print()
        print("="*80)
        
        # Save to JSON
        if output_file:
            output_path = Path(output_file)
            report_data = {
                'timestamp': datetime.now().isoformat(),
                'log_file': str(self.log_file),
                'metrics': metrics,
                'criteria': {name: passed for name, passed, _ in criteria}
            }
            
            with open(output_path, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            print(f"\n  Report saved to: {output_path}")
        
        return metrics


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Analyze Dry Run Results')
    parser.add_argument('--log-file', help='Path to log file (auto-detects latest if not specified)')
    parser.add_argument('--output', default='dry_run_report.json', help='Output JSON file')
    
    args = parser.parse_args()
    
    # Auto-detect latest log file
    if not args.log_file:
        log_dir = Path("logs")
        if not log_dir.exists():
            logger.error("Logs directory not found")
            sys.exit(1)
        
        log_files = list(log_dir.glob("dry_run_*.log")) + list(log_dir.glob("bot_*.log"))
        
        if not log_files:
            logger.error("No log files found in logs/")
            sys.exit(1)
        
        latest_log = max(log_files, key=lambda f: f.stat().st_mtime)
        args.log_file = str(latest_log)
        logger.info(f"Using latest log file: {latest_log}")
    
    # Analyze
    analyzer = DryRunAnalyzer(args.log_file)
    
    if not analyzer.parse_log():
        sys.exit(1)
    
    analyzer.generate_report(output_file=args.output)


if __name__ == "__main__":
    main()

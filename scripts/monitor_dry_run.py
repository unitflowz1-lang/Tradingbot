#!/usr/bin/env python3
"""
DRY RUN REAL-TIME MONITOR
==========================
Monitors dry run performance and provides live metrics.

Usage:
    python scripts/monitor_dry_run.py

This script:
1. Reads bot logs in real-time
2. Extracts trade data
3. Calculates live metrics (win rate, profit factor, drawdown)
4. Displays dashboard with color-coded status
5. Alerts on warning conditions
"""

import re
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DryRunMonitor:
    """Monitor dry run performance in real-time"""
    
    def __init__(self, log_dir: str = "logs"):
        self.log_dir = Path(log_dir)
        self.trades = []
        self.signals_admitted = 0
        self.signals_rejected = 0
        self.spread_trap_blocks = 0
        self.compounding_triggers = 0
        self.compounding_resets = 0
        
        # Metrics
        self.total_pnl = 0.0
        self.peak_equity = 10000.0
        self.current_equity = 10000.0
        self.max_drawdown = 0.0
        
        # Trade tracking
        self.winning_trades = 0
        self.losing_trades = 0
        self.consecutive_wins = 0
        self.consecutive_losses = 0
        self.max_consecutive_wins = 0
        self.max_consecutive_losses = 0
        
    def parse_latest_log(self) -> Path:
        """Find and return the latest log file"""
        if not self.log_dir.exists():
            logger.error(f"Log directory not found: {self.log_dir}")
            return None
        
        log_files = list(self.log_dir.glob("dry_run_*.log")) + \
                    list(self.log_dir.glob("bot_*.log"))
        
        if not log_files:
            logger.warning("No log files found")
            return None
        
        # Get most recent file
        latest = max(log_files, key=lambda f: f.stat().st_mtime)
        return latest
    
    def extract_trades(self, log_file: Path):
        """Extract trade data from log file"""
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            # Reset counters
            self.trades = []
            self.winning_trades = 0
            self.losing_trades = 0
            
            # Extract trade closures
            # Pattern: Trade closed with PnL: $XXX.XX
            pnl_pattern = r'(?:PnL|profit)[\s:]*\$?([-\d.]+)'
            
            for line in content.split('\n'):
                # Count signals
                if 'SIGNAL_ADMITTED' in line or 'Signal quality:' in line:
                    if 'above floor' in line.lower():
                        self.signals_admitted += 1
                
                if 'SIGNAL_REJECTED' in line or 'quality below' in line.lower():
                    self.signals_rejected += 1
                
                # Count spread trap blocks
                if 'SPREAD_TRAP' in line and 'BLOCKING' in line:
                    self.spread_trap_blocks += 1
                
                # Count compounding events
                if 'AGGRESSIVE_COMPOUND]' in line and 'Scaling' in line:
                    self.compounding_triggers += 1
                
                if 'AGGRESSIVE_COMPOUND_RESET' in line:
                    self.compounding_resets += 1
                
                # Extract trade PnL
                if any(keyword in line for keyword in ['Trade closed', 'Position closed', 'EXIT']):
                    pnl_match = re.search(pnl_pattern, line, re.IGNORECASE)
                    if pnl_match:
                        try:
                            pnl = float(pnl_match.group(1))
                            self.trades.append({
                                'pnl': pnl,
                                'timestamp': datetime.now()
                            })
                            
                            if pnl > 0:
                                self.winning_trades += 1
                            else:
                                self.losing_trades += 1
                        except ValueError:
                            pass
            
            # Calculate metrics
            self.calculate_metrics()
            
        except Exception as e:
            logger.error(f"Error parsing log file: {e}")
    
    def calculate_metrics(self):
        """Calculate performance metrics"""
        total_trades = len(self.trades)
        
        if total_trades == 0:
            self.win_rate = 0.0
            self.profit_factor = 0.0
            self.total_pnl = 0.0
            return
        
        # Win rate
        self.win_rate = self.winning_trades / total_trades if total_trades > 0 else 0.0
        
        # Total PnL
        self.total_pnl = sum(t['pnl'] for t in self.trades)
        
        # Profit factor
        gross_profit = sum(t['pnl'] for t in self.trades if t['pnl'] > 0)
        gross_loss = abs(sum(t['pnl'] for t in self.trades if t['pnl'] < 0))
        self.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # Equity curve and drawdown
        self.current_equity = 10000.0 + self.total_pnl
        self.peak_equity = max(self.peak_equity, self.current_equity)
        self.max_drawdown = (self.peak_equity - self.current_equity) / self.peak_equity * 100
        
        # Consecutive wins/losses
        self.calculate_streaks()
    
    def calculate_streaks(self):
        """Calculate consecutive win/loss streaks"""
        if not self.trades:
            return
        
        current_streak = 0
        max_wins = 0
        max_losses = 0
        
        for trade in self.trades:
            if trade['pnl'] > 0:
                current_streak = max(1, current_streak) if current_streak >= 0 else 1
                max_wins = max(max_wins, current_streak)
            else:
                current_streak = min(-1, current_streak) if current_streak <= 0 else -1
                max_losses = max(max_losses, abs(current_streak))
        
        self.max_consecutive_wins = max_wins
        self.max_consecutive_losses = max_losses
    
    def display_dashboard(self):
        """Display real-time dashboard"""
        # Clear screen (works on Windows and Unix)
        print('\033c' if sys.platform != 'win32' else '')
        
        print("="*80)
        print("  DRY RUN MONITOR - REAL-TIME DASHBOARD")
        print("="*80)
        print()
        print(f"  Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Core metrics
        print("─"*80)
        print("  CORE METRICS")
        print("─"*80)
        print(f"  Total Trades:        {len(self.trades)}")
        print(f"  Win Rate:            {self.win_rate*100:.2f}%")
        print(f"  Profit Factor:       {self.profit_factor:.2f}")
        print(f"  Total PnL:           ${self.total_pnl:.2f}")
        print(f"  Current Equity:      ${self.current_equity:.2f}")
        print(f"  Max Drawdown:        {self.max_drawdown:.2f}%")
        print()
        
        # Trade breakdown
        print("─"*80)
        print("  TRADE BREAKDOWN")
        print("─"*80)
        print(f"  Winning Trades:      {self.winning_trades}")
        print(f"  Losing Trades:       {self.losing_trades}")
        print(f"  Max Win Streak:      {self.max_consecutive_wins}")
        print(f"  Max Loss Streak:     {self.max_consecutive_losses}")
        print()
        
        # Signal quality
        print("─"*80)
        print("  SIGNAL QUALITY")
        print("─"*80)
        print(f"  Signals Admitted:    {self.signals_admitted}")
        print(f"  Signals Rejected:    {self.signals_rejected}")
        total_signals = self.signals_admitted + self.signals_rejected
        admission_rate = (self.signals_admitted / total_signals * 100) if total_signals > 0 else 0
        print(f"  Admission Rate:      {admission_rate:.1f}%")
        print()
        
        # Safety features
        print("─"*80)
        print("  SAFETY FEATURES")
        print("─"*80)
        print(f"  Spread Trap Blocks:  {self.spread_trap_blocks}")
        print(f"  Compounding Triggers:{self.compounding_triggers}")
        print(f"  Compounding Resets:  {self.compounding_resets}")
        print()
        
        # Status indicators
        print("─"*80)
        print("  STATUS INDICATORS")
        print("─"*80)
        
        # Win rate status
        if self.win_rate >= 0.54:
            wr_status = "✅ EXCELLENT"
            wr_color = "green"
        elif self.win_rate >= 0.50:
            wr_status = "✅ GOOD"
            wr_color = "green"
        elif self.win_rate >= 0.45:
            wr_status = "⚠️  MARGINAL"
            wr_color = "yellow"
        else:
            wr_status = "❌ POOR"
            wr_color = "red"
        
        print(f"  Win Rate:            {wr_status}")
        
        # Drawdown status
        if self.max_drawdown <= 5:
            dd_status = "✅ SAFE"
        elif self.max_drawdown <= 10:
            dd_status = "⚠️  MODERATE"
        elif self.max_drawdown <= 15:
            dd_status = "❌ HIGH"
        else:
            dd_status = "🚨 CRITICAL"
        
        print(f"  Drawdown:            {dd_status}")
        
        # Trade frequency status
        trades_per_day = len(self.trades) / max(1, 1)  # Assuming 1 day so far
        if trades_per_day >= 8:
            tf_status = "✅ HIGH"
        elif trades_per_day >= 5:
            tf_status = "✅ MODERATE"
        elif trades_per_day >= 2:
            tf_status = "⚠️  LOW"
        else:
            tf_status = "❌ VERY LOW"
        
        print(f"  Trade Frequency:     {tf_status} ({trades_per_day:.1f}/day)")
        print()
        
        # Warnings
        if self.max_drawdown > 10:
            print("🚨 WARNING: Drawdown exceeds 10% - Consider stopping!")
        if self.consecutive_losses >= 5:
            print("🚨 WARNING: 5+ consecutive losses - Strategy may be failing!")
        if len(self.trades) == 0:
            print("⚠️  No trades yet - Bot may not be trading or market is closed")
        
        print()
        print("="*80)
        print("  Press Ctrl+C to exit monitoring")
        print("="*80)
    
    def run(self, interval: int = 10):
        """Run monitor loop"""
        logger.info(f"Starting dry run monitor (update interval: {interval}s)")
        logger.info(f"Watching log directory: {self.log_dir}")
        print()
        
        try:
            while True:
                log_file = self.parse_latest_log()
                
                if log_file:
                    self.extract_trades(log_file)
                    self.display_dashboard()
                else:
                    print("⏳ Waiting for log files...")
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\nMonitor stopped by user")
            logger.info("Monitor stopped")
        except Exception as e:
            logger.error(f"Monitor error: {e}")
            raise


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Dry Run Real-Time Monitor')
    parser.add_argument('--log-dir', default='logs', help='Log directory path')
    parser.add_argument('--interval', type=int, default=10, help='Update interval in seconds')
    
    args = parser.parse_args()
    
    monitor = DryRunMonitor(log_dir=args.log_dir)
    monitor.run(interval=args.interval)


if __name__ == "__main__":
    main()

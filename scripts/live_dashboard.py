#!/usr/bin/env python3
"""
LIVE TRADING DASHBOARD
======================
Real-time monitoring dashboard for dry run and live trading.
Displays key metrics in a clean terminal interface.

Usage:
    python scripts/live_dashboard.py [--interval 5] [--log-dir logs]

Features:
    - Real-time Win Rate, Profit Factor, Total PnL
    - Trade history with PnL breakdown
    - Drawdown monitoring
    - Compounding status
    - Spread trap activity
    - Color-coded status indicators
    - Auto-refresh every N seconds
"""

import sys
import os
import re
import time
import json
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Optional
import logging

# Setup logging
logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TradeRecord:
    """Represents a single trade"""
    def __init__(self, symbol: str, direction: str, entry_price: float, 
                 exit_price: float, pnl: float, exit_reason: str, 
                 timestamp: datetime, lots: float = 0.01):
        self.symbol = symbol
        self.direction = direction
        self.entry_price = entry_price
        self.exit_price = exit_price
        self.pnl = pnl
        self.exit_reason = exit_reason
        self.timestamp = timestamp
        self.lots = lots


class LiveDashboard:
    """Real-time trading dashboard"""
    
    def __init__(self, log_dir: str = "logs", update_interval: int = 5):
        self.log_dir = Path(log_dir)
        self.update_interval = update_interval
        self.trades: List[TradeRecord] = []
        self.signals_admitted = 0
        self.signals_rejected = 0
        self.spread_trap_blocks = 0
        self.compounding_triggers = 0
        self.compounding_resets = 0
        self.current_streak = 0
        self.max_win_streak = 0
        self.max_loss_streak = 0
        self.peak_equity = 10000.0
        self.current_equity = 10000.0
        self.max_drawdown = 0.0
        self.last_update = None
        
    def clear_screen(self):
        """Clear terminal screen"""
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def find_latest_log(self) -> Optional[Path]:
        """Find the most recent log file"""
        if not self.log_dir.exists():
            return None
        
        # Look for dry run or bot logs
        patterns = ["dry_run_*.log", "bot_*.log", "*.log"]
        
        for pattern in patterns:
            log_files = list(self.log_dir.glob(pattern))
            if log_files:
                # Return most recently modified
                return max(log_files, key=lambda f: f.stat().st_mtime)
        
        return None
    
    def parse_trades_from_log(self, log_file: Path) -> List[TradeRecord]:
        """Parse trade records from log file"""
        trades = []
        
        try:
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            for line in lines:
                # Match trade closure patterns
                if any(kw in line for kw in ['Trade closed', 'Position closed', 'EXIT COMPLETE']):
                    trade = self._parse_trade_line(line)
                    if trade:
                        trades.append(trade)
                
                # Count signals
                if 'SIGNAL_ADMITTED' in line or 'Signal quality:' in line:
                    if 'above floor' in line.lower() or 'ADMITTED' in line:
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
            
        except Exception as e:
            logger.error(f"Error parsing log file: {e}")
        
        return trades
    
    def _parse_trade_line(self, line: str) -> Optional[TradeRecord]:
        """Parse single trade line"""
        try:
            # Extract symbol
            symbol_match = re.search(r'\[([A-Z]{3}/[A-Z]{3}|[A-Z]{6})\]', line)
            symbol = symbol_match.group(1) if symbol_match else "UNKNOWN"
            
            # Extract PnL
            pnl_match = re.search(r'(?:PnL|profit|PL)[\s:]*\$?([-\d.]+)', line, re.IGNORECASE)
            pnl = float(pnl_match.group(1)) if pnl_match else 0.0
            
            # Extract direction
            direction = "UNKNOWN"
            if 'LONG' in line.upper() or 'BUY' in line.upper():
                direction = "LONG"
            elif 'SHORT' in line.upper() or 'SELL' in line.upper():
                direction = "SHORT"
            
            # Extract exit reason
            exit_reason = "UNKNOWN"
            if 'TP' in line or 'TAKE PROFIT' in line.upper():
                exit_reason = "TP"
            elif 'SL' in line or 'STOP LOSS' in line.upper():
                exit_reason = "SL"
            
            # Extract timestamp
            time_match = re.search(r'(\d{2}:\d{2}:\d{2})', line)
            timestamp = datetime.now()
            if time_match:
                try:
                    time_str = time_match.group(1)
                    timestamp = timestamp.replace(
                        hour=int(time_str.split(':')[0]),
                        minute=int(time_str.split(':')[1]),
                        second=int(time_str.split(':')[2])
                    )
                except:
                    pass
            
            # Extract entry/exit prices (if available)
            entry_match = re.search(r'entry[\s:]*([\d.]+)', line, re.IGNORECASE)
            exit_match = re.search(r'exit[\s:]*([\d.]+)', line, re.IGNORECASE)
            entry_price = float(entry_match.group(1)) if entry_match else 0.0
            exit_price = float(exit_match.group(1)) if exit_match else 0.0
            
            # Extract lots
            lots_match = re.search(r'(?:lots|qty|size)[\s:]*([\d.]+)', line, re.IGNORECASE)
            lots = float(lots_match.group(1)) if lots_match else 0.01
            
            return TradeRecord(
                symbol=symbol,
                direction=direction,
                entry_price=entry_price,
                exit_price=exit_price,
                pnl=pnl,
                exit_reason=exit_reason,
                timestamp=timestamp,
                lots=lots
            )
            
        except Exception as e:
            logger.debug(f"Failed to parse trade line: {e}")
            return None
    
    def calculate_metrics(self) -> Dict:
        """Calculate all dashboard metrics"""
        if not self.trades:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'profit_factor': 0.0,
                'total_pnl': 0.0,
                'avg_pnl': 0.0,
                'max_drawdown': 0.0,
                'current_equity': 10000.0,
                'win_streak': 0,
                'loss_streak': 0,
                'current_streak': 0,
                'status': 'NO_TRADES'
            }
        
        # Basic metrics
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
        total_pnl = sum(t.pnl for t in self.trades)
        avg_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
        
        # Profit factor
        gross_profit = sum(t.pnl for t in winning_trades)
        gross_loss = abs(sum(t.pnl for t in losing_trades))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (999.99 if gross_profit > 0 else 0.0)
        
        # Equity curve and drawdown
        equity = 10000.0
        peak_equity = equity
        max_drawdown = 0.0
        
        for trade in self.trades:
            equity += trade.pnl
            peak_equity = max(peak_equity, equity)
            drawdown = (peak_equity - equity) / peak_equity * 100
            max_drawdown = max(max_drawdown, drawdown)
        
        current_equity = equity
        
        # Streaks
        current_streak = 0
        max_win_streak = 0
        max_loss_streak = 0
        
        for trade in self.trades:
            if trade.pnl > 0:
                current_streak = max(1, current_streak) if current_streak >= 0 else 1
                max_win_streak = max(max_win_streak, current_streak)
            else:
                current_streak = min(-1, current_streak) if current_streak <= 0 else -1
                max_loss_streak = max(max_loss_streak, abs(current_streak))
        
        # Status determination
        if win_rate >= 0.55 and profit_factor >= 1.5:
            status = 'EXCELLENT'
        elif win_rate >= 0.50 and profit_factor >= 1.2:
            status = 'GOOD'
        elif win_rate >= 0.45 and profit_factor >= 1.0:
            status = 'MARGINAL'
        else:
            status = 'POOR'
        
        return {
            'total_trades': total_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'total_pnl': total_pnl,
            'avg_pnl': avg_pnl,
            'max_drawdown': max_drawdown,
            'current_equity': current_equity,
            'win_streak': max_win_streak,
            'loss_streak': max_loss_streak,
            'current_streak': current_streak,
            'status': status
        }
    
    def display_dashboard(self):
        """Display the full dashboard"""
        self.clear_screen()
        
        # Parse latest trades
        log_file = self.find_latest_log()
        if log_file:
            self.trades = self.parse_trades_from_log(log_file)
        
        # Calculate metrics
        metrics = self.calculate_metrics()
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # Header
        print("=" * 80)
        print("  🚀 LIVE TRADING DASHBOARD - DRY RUN MODE")
        print("=" * 80)
        print(f"  Updated: {now} | Log: {log_file.name if log_file else 'N/A'}")
        print()
        
        # Core Metrics
        print("─" * 80)
        print("  📊 CORE METRICS")
        print("─" * 80)
        
        # Color code based on performance
        wr = metrics['win_rate'] * 100
        pf = metrics['profit_factor']
        pnl = metrics['total_pnl']
        dd = metrics['max_drawdown']
        
        # Win Rate
        if wr >= 55:
            wr_color = "✅"
        elif wr >= 50:
            wr_color = "🟡"
        else:
            wr_color = "❌"
        
        print(f"  Win Rate:          {wr_color} {wr:6.2f}%  ({metrics['total_trades']} trades)")
        
        # Profit Factor
        if pf >= 1.5:
            pf_color = "✅"
        elif pf >= 1.2:
            pf_color = "🟡"
        else:
            pf_color = "❌"
        
        print(f"  Profit Factor:     {pf_color} {pf:6.2f}")
        
        # Total PnL
        if pnl > 0:
            pnl_color = "✅"
            pnl_str = f"+${pnl:,.2f}"
        else:
            pnl_color = "❌"
            pnl_str = f"-${abs(pnl):,.2f}"
        
        print(f"  Total PnL:         {pnl_color} {pnl_str}")
        print(f"  Avg PnL/Trade:     ${metrics['avg_pnl']:,.2f}")
        print(f"  Current Equity:    ${metrics['current_equity']:,.2f}")
        print()
        
        # Risk Metrics
        print("─" * 80)
        print("  ⚠️  RISK METRICS")
        print("─" * 80)
        
        # Drawdown
        if dd <= 5:
            dd_color = "✅"
        elif dd <= 10:
            dd_color = "🟡"
        elif dd <= 15:
            dd_color = "❌"
        else:
            dd_color = "🚨"
        
        print(f"  Max Drawdown:      {dd_color} {dd:6.2f}%")
        print(f"  Max Win Streak:    {metrics['win_streak']} trades")
        print(f"  Max Loss Streak:   {metrics['loss_streak']} trades")
        
        # Current streak
        if metrics['current_streak'] > 0:
            streak_text = f"🔥 {metrics['current_streak']} wins in a row"
        elif metrics['current_streak'] < 0:
            streak_text = f"❄️ {abs(metrics['current_streak'])} losses in a row"
        else:
            streak_text = "Even"
        
        print(f"  Current Streak:    {streak_text}")
        print()
        
        # Signal Quality
        print("─" * 80)
        print("  🎯 SIGNAL QUALITY")
        print("─" * 80)
        
        total_signals = self.signals_admitted + self.signals_rejected
        admission_rate = (self.signals_admitted / total_signals * 100) if total_signals > 0 else 0
        
        print(f"  Signals Admitted:  {self.signals_admitted}")
        print(f"  Signals Rejected:  {self.signals_rejected}")
        print(f"  Admission Rate:    {admission_rate:.1f}%")
        print(f"  Spread Traps:      {self.spread_trap_blocks} blocks")
        print(f"  Compounding:       {self.compounding_triggers} triggers, {self.compounding_resets} resets")
        print()
        
        # Recent Trades
        print("─" * 80)
        print("  📝 RECENT TRADES (Last 10)")
        print("─" * 80)
        
        if self.trades:
            recent = self.trades[-10:]
            for i, trade in enumerate(reversed(recent), 1):
                pnl_str = f"+${trade.pnl:.2f}" if trade.pnl > 0 else f"-${abs(trade.pnl)::.2f}"
                pnl_icon = "✅" if trade.pnl > 0 else "❌"
                time_str = trade.timestamp.strftime('%H:%M:%S')
                
                print(f"  {i:2d}. {pnl_icon} {trade.symbol:<8} {trade.direction:<6} | "
                      f"PnL: {pnl_str:>10} | Exit: {trade.exit_reason:<4} | {time_str}")
        else:
            print("  No trades yet - Waiting for market open...")
        
        print()
        
        # Status Banner
        print("─" * 80)
        status = metrics['status']
        
        if status == 'EXCELLENT':
            banner = "🎉 EXCELLENT - Strategy performing above targets!"
        elif status == 'GOOD':
            banner = "✅ GOOD - Strategy on track, keep monitoring"
        elif status == 'MARGINAL':
            banner = "⚠️  MARGINAL - Strategy needs improvement"
        elif status == 'POOR':
            banner = "❌ POOR - Consider stopping and reviewing"
        else:
            banner = "⏳ WAITING - No trades yet"
        
        print(f"  {banner}")
        print("─" * 80)
        print()
        print(f"  Refreshing in {self.update_interval}s... (Ctrl+C to stop)")
        print()
    
    def run(self):
        """Run the dashboard loop"""
        logger.info(f"Starting live dashboard (update interval: {self.update_interval}s)")
        print("🚀 Live Dashboard starting...")
        print(f"📁 Watching: {self.log_dir}")
        print()
        
        try:
            while True:
                self.display_dashboard()
                time.sleep(self.update_interval)
                
        except KeyboardInterrupt:
            print("\n\n👋 Dashboard stopped by user")
            logger.info("Dashboard stopped")
        except Exception as e:
            logger.error(f"Dashboard error: {e}")
            print(f"\n❌ Error: {e}")
            raise


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Live Trading Dashboard')
    parser.add_argument('--interval', type=int, default=5, 
                       help='Update interval in seconds (default: 5)')
    parser.add_argument('--log-dir', default='logs',
                       help='Log directory path (default: logs)')
    
    args = parser.parse_args()
    
    dashboard = LiveDashboard(
        log_dir=args.log_dir,
        update_interval=args.interval
    )
    
    dashboard.run()


if __name__ == "__main__":
    main()

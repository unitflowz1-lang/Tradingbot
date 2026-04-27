"""
Paper Trading Dashboard Monitor
================================
Monitors live paper trading with hourly summaries:
- Current Unrealized PnL
- LOT_SIZE_MISMATCH_ABORT events count
- ML_ACCURACY_GUARD rejections count
- Model Accuracy for EUR/USD and GBP/USD
- Consecutive loss guardrail (3 losses = CRITICAL alert)

Usage:
    python scripts/dashboard_monitor.py
"""

import json
import logging
import time
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, List, Any
from collections import deque

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/dashboard_monitor.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)


class PaperTradingDashboard:
    """
    Real-time monitoring dashboard for paper trading
    """
    
    def __init__(self, log_file: str = "logs/forex_bot.log", trade_history_file: str = "trade_history.json"):
        self.log_file = log_file
        self.trade_history_file = trade_history_file
        
        # Metrics tracking
        self.metrics = {
            'start_time': datetime.now(timezone.utc),
            'last_summary_time': datetime.now(timezone.utc),
            'lot_size_abort_count': 0,
            'ml_accuracy_guard_count': 0,
            'consecutive_losses': 0,
            'max_consecutive_losses': 0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,
            'model_accuracy_eurusd': 0.0,
            'model_accuracy_gbpusd': 0.0,
        }
        
        # Trade history for consecutive loss tracking
        self.recent_trades = deque(maxlen=100)
        
        # Alert thresholds
        self.CONSECUTIVE_LOSS_THRESHOLD = 3
        self.SUMMARY_INTERVAL_SECONDS = 3600  # 1 hour
        
        logger.critical("[DASHBOARD] Paper Trading Dashboard initialized")
        logger.critical(f"[DASHBOARD] Monitoring log file: {log_file}")
        logger.critical(f"[DASHBOARD] Trade history: {trade_history_file}")
        logger.critical(f"[DASHBOARD] Summary interval: 1 hour")
        logger.critical(f"[DASHBOARD] Consecutive loss alert threshold: {self.CONSECUTIVE_LOSS_THRESHOLD}")
    
    def parse_log_file(self) -> Dict[str, int]:
        """
        Parse log file for key events
        Returns: Dict with counts of various events
        """
        counts = {
            'lot_size_abort': 0,
            'ml_accuracy_guard': 0,
            'consecutive_loss_alert': 0,
        }
        
        try:
            log_path = Path(self.log_file)
            if not log_path.exists():
                return counts
            
            # Read last 1000 lines to avoid processing huge files
            with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                recent_lines = lines[-1000:] if len(lines) > 1000 else lines
            
            for line in recent_lines:
                if 'LOT_SIZE_MISMATCH_ABORT' in line:
                    counts['lot_size_abort'] += 1
                elif 'ML_ACCURACY_GUARD' in line:
                    counts['ml_accuracy_guard'] += 1
                elif 'CONSECUTIVE_LOSS_ALERT' in line:
                    counts['consecutive_loss_alert'] += 1
        
        except Exception as e:
            logger.error(f"[DASHBOARD] Error parsing log file: {e}")
        
        return counts
    
    def load_trade_history(self) -> List[Dict]:
        """
        Load trade history from JSON file
        Returns: List of trade records
        """
        try:
            trade_path = Path(self.trade_history_file)
            if not trade_path.exists():
                return []
            
            with open(trade_path, 'r') as f:
                trades = json.load(f)
            
            return trades if isinstance(trades, list) else []
        
        except Exception as e:
            logger.error(f"[DASHBOARD] Error loading trade history: {e}")
            return []
    
    def calculate_unrealized_pnl(self) -> float:
        """
        Calculate current unrealized PnL from open positions
        This would normally read from MT5 or broker API
        For now, returns 0 (will be updated when positions are open)
        """
        # TODO: Integrate with MT5BrokerInterface to get real-time position PnL
        # Example:
        # positions = broker.get_open_positions()
        # unrealized_pnl = sum(pos.profit for pos in positions)
        return 0.0
    
    def calculate_model_accuracy(self, symbol: str) -> float:
        """
        Calculate model accuracy for a specific symbol
        Based on recent trade history
        """
        trades = self.load_trade_history()
        
        if not trades:
            return 0.0
        
        # Filter trades for this symbol
        symbol_trades = [t for t in trades if t.get('symbol', '') == symbol]
        
        if not symbol_trades:
            return 0.0
        
        # Calculate accuracy (win rate)
        wins = sum(1 for t in symbol_trades if t.get('pnl', 0) > 0)
        accuracy = wins / len(symbol_trades) if symbol_trades else 0.0
        
        return accuracy
    
    def check_consecutive_losses(self) -> bool:
        """
        Check if consecutive losses exceed threshold
        Returns: True if alert should be triggered
        """
        trades = self.load_trade_history()
        
        if not trades:
            return False
        
        # Get last 10 trades
        recent = trades[-10:] if len(trades) >= 10 else trades
        
        # Count consecutive losses from most recent
        consecutive = 0
        for trade in reversed(recent):
            if trade.get('pnl', 0) < 0:
                consecutive += 1
            else:
                break
        
        self.metrics['consecutive_losses'] = consecutive
        self.metrics['max_consecutive_losses'] = max(
            self.metrics['max_consecutive_losses'],
            consecutive
        )
        
        if consecutive >= self.CONSECUTIVE_LOSS_THRESHOLD:
            return True
        
        return False
    
    def generate_hourly_summary(self) -> str:
        """
        Generate comprehensive hourly summary
        """
        # Update metrics from logs
        log_counts = self.parse_log_file()
        self.metrics['lot_size_abort_count'] = log_counts['lot_size_abort']
        self.metrics['ml_accuracy_guard_count'] = log_counts['ml_accuracy_guard']
        
        # Update metrics from trade history
        trades = self.load_trade_history()
        self.metrics['total_trades'] = len(trades)
        self.metrics['winning_trades'] = sum(1 for t in trades if t.get('pnl', 0) > 0)
        self.metrics['losing_trades'] = sum(1 for t in trades if t.get('pnl', 0) < 0)
        self.metrics['realized_pnl'] = sum(t.get('pnl', 0) for t in trades)
        
        # Calculate unrealized PnL
        self.metrics['unrealized_pnl'] = self.calculate_unrealized_pnl()
        
        # Calculate model accuracies
        self.metrics['model_accuracy_eurusd'] = self.calculate_model_accuracy('EUR/USD')
        self.metrics['model_accuracy_gbpusd'] = self.calculate_model_accuracy('GBP/USD')
        
        # Check consecutive losses
        consecutive_loss_alert = self.check_consecutive_losses()
        
        # Generate summary string
        now = datetime.now(timezone.utc)
        runtime = now - self.metrics['start_time']
        hours_running = runtime.total_seconds() / 3600
        
        summary = f"""
{'='*80}
📊 PAPER TRADING DASHBOARD - HOURLY SUMMARY
{'='*80}
🕐 Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}
⏱️  Runtime: {hours_running:.2f} hours

💰 PERFORMANCE:
   ├─ Realized P&L: ${self.metrics['realized_pnl']:,.2f}
   ├─ Unrealized P&L: ${self.metrics['unrealized_pnl']:,.2f}
   ├─ Total P&L: ${self.metrics['realized_pnl'] + self.metrics['unrealized_pnl']:,.2f}
   └─ Win Rate: {self.metrics['winning_trades']}/{self.metrics['total_trades']} ({self.metrics['winning_trades']/self.metrics['total_trades']*100 if self.metrics['total_trades'] > 0 else 0:.1f}%)

🎯 MODEL ACCURACY:
   ├─ EUR/USD: {self.metrics['model_accuracy_eurusd']:.1%}
   └─ GBP/USD: {self.metrics['model_accuracy_gbpusd']:.1%}

🛡️  RISK METRICS:
   ├─ LOT_SIZE_MISMATCH_ABORT Events: {self.metrics['lot_size_abort_count']}
   ├─ ML_ACCURACY_GUARD Rejections: {self.metrics['ml_accuracy_guard_count']}
   ├─ Consecutive Losses: {self.metrics['consecutive_losses']}
   └─ Max Consecutive Losses: {self.metrics['max_consecutive_losses']}

📈 TRADE STATISTICS:
   ├─ Total Trades: {self.metrics['total_trades']}
   ├─ Winning: {self.metrics['winning_trades']}
   ├─ Losing: {self.metrics['losing_trades']}
   └─ Avg Trade: ${self.metrics['realized_pnl']/self.metrics['total_trades'] if self.metrics['total_trades'] > 0 else 0:,.2f}
{'='*80}
"""
        
        # Add CRITICAL alert if needed
        if consecutive_loss_alert:
            alert_msg = f"""
🔴🔴🔴 CRITICAL ALERT 🔴🔴🔴
CONSECUTIVE LOSS THRESHOLD REACHED!
Consecutive Losses: {self.metrics['consecutive_losses']}
Threshold: {self.CONSECUTIVE_LOSS_THRESHOLD}
Recommendation: Consider reducing position sizes or pausing trading
{'='*80}
"""
            summary += alert_msg
        
        return summary
    
    def print_summary(self):
        """
        Print hourly summary to console and log
        """
        summary = self.generate_hourly_summary()
        logger.critical(summary)
        
        # Save summary to file
        summary_file = Path("logs/dashboard_summary_latest.txt")
        with open(summary_file, 'w') as f:
            f.write(summary)
    
    def check_and_alert(self):
        """
        Check for critical conditions and send alerts
        """
        # Check consecutive losses
        if self.check_consecutive_losses():
            alert_msg = (
                f"🔴 CRITICAL: Consecutive loss threshold reached! "
                f"{self.metrics['consecutive_losses']} consecutive losses. "
                f"Threshold: {self.CONSECUTIVE_LOSS_THRESHOLD}. "
                f"Consider reducing position sizes or pausing trading."
            )
            logger.critical(f"[CONSECUTIVE_LOSS_ALERT] {alert_msg}")
            
            # Save alert to separate file for easy monitoring
            alert_file = Path("logs/critical_alerts.log")
            with open(alert_file, 'a') as f:
                f.write(f"{datetime.now(timezone.utc).isoformat()} | {alert_msg}\n")
    
    def run_monitoring_loop(self):
        """
        Main monitoring loop - runs indefinitely
        """
        logger.critical("[DASHBOARD] Starting monitoring loop...")
        logger.critical(f"[DASHBOARD] Press Ctrl+C to stop")
        
        last_summary_time = time.time()
        
        try:
            while True:
                current_time = time.time()
                time_since_summary = current_time - last_summary_time
                
                # Check for critical conditions every 5 minutes
                if time_since_summary % 300 < 60:  # Every 5 minutes
                    self.check_and_alert()
                
                # Print hourly summary
                if time_since_summary >= self.SUMMARY_INTERVAL_SECONDS:
                    self.print_summary()
                    last_summary_time = current_time
                
                # Sleep for 60 seconds
                time.sleep(60)
        
        except KeyboardInterrupt:
            logger.info("[DASHBOARD] Monitoring stopped by user")
            # Print final summary
            self.print_summary()
        
        except Exception as e:
            logger.error(f"[DASHBOARD] Error in monitoring loop: {e}")
            # Print final summary before exiting
            self.print_summary()


def main():
    """
    Main entry point for dashboard monitor
    """
    # Check if log file exists
    log_file = "logs/forex_bot.log"
    if not Path(log_file).exists():
        logger.warning(f"[DASHBOARD] Log file not found: {log_file}")
        logger.info("[DASHBOARD] Will monitor once bot starts logging")
    
    # Initialize dashboard
    dashboard = PaperTradingDashboard(
        log_file=log_file,
        trade_history_file="trade_history.json"
    )
    
    # Print initial summary
    dashboard.print_summary()
    
    # Start monitoring loop
    dashboard.run_monitoring_loop()


if __name__ == "__main__":
    main()

"""
Walk-Forward Analysis.
Out-of-sample validation using walk-forward methodology.
"""

import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from dataclasses import dataclass
from utils.logger import get_logger
from backtesting.backtester import Backtester, BacktestConfig, BacktestMetrics


logger = get_logger(__name__)


@dataclass
class WalkForwardWindow:
    """A single walk-forward window."""
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    train_data: pd.DataFrame
    test_data: pd.DataFrame
    train_metrics: BacktestMetrics
    test_metrics: BacktestMetrics
    overfitting_ratio: float  # Ratio of train to test performance


class WalkForwardAnalyzer:
    """
    Walk-forward optimization and analysis.
    Tests strategy on out-of-sample periods.
    Detects overfitting by comparing in-sample to out-of-sample performance.
    """
    
    def __init__(self, strategy, data: pd.DataFrame, config: BacktestConfig):
        """
        Initialize WalkForwardAnalyzer.
        
        Args:
            strategy: Strategy to analyze
            data: Historical data
            config: Backtest configuration
        """
        self.strategy = strategy
        self.data = data
        self.config = config
        self.windows: List[WalkForwardWindow] = []
    
    def run_analysis(self, train_period_days: int = 252, test_period_days: int = 63,
                    step_days: int = 63) -> Dict:
        """
        Run walk-forward analysis.
        
        Args:
            train_period_days: Days for training period
            test_period_days: Days for test period
            step_days: Days to shift window forward
        
        Returns:
            Dictionary with overfitting analysis
        """
        logger.info(f"Running walk-forward analysis with {train_period_days} train, {test_period_days} test periods")
        
        try:
            # Create windows
            self._create_windows(train_period_days, test_period_days, step_days)
            
            # Test each window
            for i, window in enumerate(self.windows):
                logger.info(f"Window {i+1}/{len(self.windows)}: Train {window.train_start} to {window.train_end}")
                
                # Backtest on training data
                backtester_train = Backtester(self.strategy, window.train_data, self.config)
                trades_train, metrics_train = backtester_train.run()
                window.train_metrics = metrics_train
                
                # Backtest on test data
                backtester_test = Backtester(self.strategy, window.test_data, self.config)
                trades_test, metrics_test = backtester_test.run()
                window.test_metrics = metrics_test
                
                # Calculate overfitting ratio
                if metrics_test.sharpe_ratio != 0:
                    window.overfitting_ratio = metrics_train.sharpe_ratio / metrics_test.sharpe_ratio
                else:
                    window.overfitting_ratio = np.inf
            
            # Aggregate results
            return self._aggregate_results()
        
        except Exception as e:
            logger.error(f"Error in walk-forward analysis: {e}")
            return {}
    
    def _create_windows(self, train_days: int, test_days: int, step_days: int):
        """Create walk-forward windows."""
        start_date = pd.to_datetime(self.config.start_date)
        end_date = pd.to_datetime(self.config.end_date)
        
        current = start_date
        
        while current + pd.Timedelta(days=train_days + test_days) <= end_date:
            train_end = current + pd.Timedelta(days=train_days)
            test_end = train_end + pd.Timedelta(days=test_days)
            
            # Filter data for window
            train_mask = (self.data['timestamp'] >= current) & (self.data['timestamp'] < train_end)
            test_mask = (self.data['timestamp'] >= train_end) & (self.data['timestamp'] < test_end)
            
            train_data = self.data[train_mask].copy()
            test_data = self.data[test_mask].copy()
            
            if len(train_data) > 0 and len(test_data) > 0:
                window = WalkForwardWindow(
                    train_start=str(current.date()),
                    train_end=str(train_end.date()),
                    test_start=str(train_end.date()),
                    test_end=str(test_end.date()),
                    train_data=train_data,
                    test_data=test_data,
                    train_metrics=BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
                    test_metrics=BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
                    overfitting_ratio=0
                )
                
                self.windows.append(window)
            
            current += pd.Timedelta(days=step_days)
    
    def _aggregate_results(self) -> Dict:
        """Aggregate walk-forward results."""
        if not self.windows:
            return {}
        
        test_metrics = [w.test_metrics for w in self.windows]
        overfitting_ratios = [w.overfitting_ratio for w in self.windows if w.overfitting_ratio < 100]
        
        return {
            'num_windows': len(self.windows),
            'avg_test_return': np.mean([m.total_return for m in test_metrics]),
            'avg_test_sharpe': np.mean([m.sharpe_ratio for m in test_metrics]),
            'avg_max_drawdown': np.mean([m.max_drawdown for m in test_metrics]),
            'avg_win_rate': np.mean([m.win_rate for m in test_metrics]),
            'avg_overfitting_ratio': np.mean(overfitting_ratios) if overfitting_ratios else np.inf,
            'is_robust': np.mean(overfitting_ratios) < 1.5 if overfitting_ratios else False
        }
    
    def get_overfitting_report(self) -> str:
        """Get human-readable overfitting report."""
        if not self.windows:
            return "No walk-forward windows generated"
        
        report = "Walk-Forward Analysis Report:\n"
        report += f"{'Window':<15} {'Train Sharpe':<15} {'Test Sharpe':<15} {'Overfit Ratio':<15}\n"
        report += "-" * 60 + "\n"
        
        for i, window in enumerate(self.windows):
            train_sharpe = window.train_metrics.sharpe_ratio
            test_sharpe = window.test_metrics.sharpe_ratio
            ratio = window .overfitting_ratio
            
            report += f"{i+1:<15} {train_sharpe:<15.4f} {test_sharpe:<15.4f} {ratio:<15.4f}\n"
        
        report += "\nInterpretation:\n"
        avg_ratio = np.mean([w.overfitting_ratio for w in self.windows if w.overfitting_ratio < 100])
        if avg_ratio < 1.2:
            report += "✓ Low overfitting - Strategy is robust\n"
        elif avg_ratio < 1.5:
            report += "⚠ Moderate overfitting - Be cautious\n"
        else:
            report += "✗ High overfitting - Strategy is not robust\n"
        
        return report

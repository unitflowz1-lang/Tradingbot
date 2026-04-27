"""
Monte Carlo Simulation for Strategy Validation.
Tests strategy robustness using synthetic price paths.
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Dict
from dataclasses import dataclass
from utils.logger import get_logger
from backtesting.backtester import BacktestMetrics


logger = get_logger(__name__)


@dataclass
class MonteCarloResult:
    """Result of a single Monte Carlo simulation."""
    final_equity: float
    total_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float


class MonteCarloSimulator:
    """
    Monte Carlo analysis for strategy validation.
    Tests robustness by reshuffling returns and testing various scenarios.
    """
    
    def __init__(self, traded_results: List, equity_curve: List[Tuple], num_simulations: int = 1000):
        """
        Initialize MonteCarloSimulator.
        
        Args:
            traded_results: List of completed trades
            equity_curve: List of equity values over time
            num_simulations: Number of simulations to run
        """
        self.trades = traded_results
        self.equity_curve = equity_curve
        self.num_simulations = num_simulations
        self.results: List[MonteCarloResult] = []
    
    def run_simulations(self, initial_capital: float) -> Dict:
        """
        Run Monte Carlo simulations.
        
        Args:
            initial_capital: Starting capital
        
        Returns:
            Dictionary with simulation statistics
        """
        logger.info(f"Running {self.num_simulations} Monte Carlo simulations")
        
        try:
            # Extract trade returns
            trade_returns = np.array([t.return_pct for t in self.trades])
            
            if len(trade_returns) == 0:
                logger.warning("No trades to simulate")
                return {}
            
            # Run simulations
            for i in range(self.num_simulations):
                # Randomly shuffle returns
                shuffled_returns = np.random.permutation(trade_returns)
                
                # Simulate equity curve
                equity = [initial_capital]
                for ret in shuffled_returns:
                    new_equity = equity[-1] * (1 + ret)
                    equity.append(new_equity)
                
                # Calculate metrics
                result = self._calculate_mc_metrics(equity, shuffled_returns)
                self.results.append(result)
            
            # Aggregate results
            return self._aggregate_simulations()
        
        except Exception as e:
            logger.error(f"Error in Monte Carlo simulations: {e}")
            return {}
    
    def run_equity_curve_resampling(self, resample_method: str = 'block') -> Dict:
        """
        Resample equity curve to test robustness.
        
        Args:
            resample_method: 'block' for block resampling, 'random' for random resampling
        
        Returns:
            Simulation statistics
        """
        logger.info(f"Running equity curve resampling with {resample_method} method")
        
        try:
            equity_values = np.array([ec[1] for ec in self.equity_curve])
            returns = np.diff(equity_values) / equity_values[:-1]
            
            if resample_method == 'block':
                block_size = int(np.sqrt(len(returns)))
                for _ in range(self.num_simulations):
                    resampled = self._block_resample(returns, block_size)
                    equity = [equity_values[0]]
                    for ret in resampled:
                        equity.append(equity[-1] * (1 + ret))
                    
                    result = self._calculate_mc_metrics(equity, resampled)
                    self.results.append(result)
            
            elif resample_method == 'random':
                for _ in range(self.num_simulations):
                    resampled_indices = np.random.choice(len(returns), len(returns), replace=True)
                    resampled = returns[resampled_indices]
                    
                    equity = [equity_values[0]]
                    for ret in resampled:
                        equity.append(equity[-1] * (1 + ret))
                    
                    result = self._calculate_mc_metrics(equity, resampled)
                    self.results.append(result)
            
            return self._aggregate_simulations()
        
        except Exception as e:
            logger.error(f"Error in equity curve resampling: {e}")
            return {}
    
    def _block_resample(self, data: np.ndarray, block_size: int) -> np.ndarray:
        """Resample data in blocks to preserve autocorrelation."""
        num_blocks = len(data) // block_size
        resampled = []
        
        for _ in range(num_blocks):
            start = np.random.randint(0, len(data) - block_size)
            block = data[start:start + block_size]
            resampled.extend(block)
        
        # Add remainder
        remainder = len(data) % block_size
        if remainder > 0:
            start = np.random.randint(0, len(data) - remainder)
            resampled.extend(data[start:start + remainder])
        
        return np.array(resampled)
    
    def _calculate_mc_metrics(self, equity: List[float], returns: np.ndarray) -> MonteCarloResult:
        """Calculate metrics for a simulation."""
        equity_array = np.array(equity)
        final_equity = equity_array[-1]
        initial_equity = equity_array[0]
        
        # Total return
        total_return = (final_equity - initial_equity) / initial_equity
        
        # Max drawdown
        running_max = np.maximum.accumulate(equity_array)
        drawdown = (equity_array - running_max) / running_max
        max_drawdown = np.min(drawdown)
        
        # Sharpe ratio
        if len(returns) > 1:
            sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252)
        else:
            sharpe = 0
        
        # Win rate
        wins = len(returns[returns > 0])
        win_rate = wins / len(returns) if len(returns) > 0 else 0
        
        return MonteCarloResult(
            final_equity=final_equity,
            total_return=total_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate
        )
    
    def _aggregate_simulations(self) -> Dict:
        """Aggregate Monte Carlo results."""
        if not self.results:
            return {}
        
        returns = np.array([r.total_return for r in self.results])
        max_drawdowns = np.array([r.max_drawdown for r in self.results])
        sharpes = np.array([r.sharpe_ratio for r in self.results])
        win_rates = np.array([r.win_rate for r in self.results])
        
        return {
            'num_simulations': len(self.results),
            'avg_return': np.mean(returns),
            'std_return': np.std(returns),
            'return_5th_percentile': np.percentile(returns, 5),
            'return_95th_percentile': np.percentile(returns, 95),
            'avg_max_drawdown': np.mean(max_drawdowns),
            'worst_case_dd': np.min(max_drawdowns),
            'avg_sharpe': np.mean(sharpes),
            'avg_win_rate': np.mean(win_rates),
            'probability_profit': len(returns[returns > 0]) / len(returns)
        }
    
    def get_distribution_stats(self) -> Dict:
        """Get statistical distribution of simulation results."""
        if not self.results:
            return {}
        
        returns = np.array([r.total_return for r in self.results])
        
        return {
            'mean': np.mean(returns),
            'median': np.median(returns),
            'std_dev': np.std(returns),
            'skewness': self._calculate_skewness(returns),
            'kurtosis': self._calculate_kurtosis(returns),
            'percentile_1': np.percentile(returns, 1),
            'percentile_5': np.percentile(returns, 5),
            'percentile_25': np.percentile(returns, 25),
            'percentile_75': np.percentile(returns, 75),
            'percentile_95': np.percentile(returns, 95),
            'percentile_99': np.percentile(returns, 99)
        }
    
    def _calculate_skewness(self, data: np.ndarray) -> float:
        """Calculate skewness."""
        mean = np.mean(data)
        std = np.std(data)
        skew = np.mean(((data - mean) / std) ** 3) if std > 0 else 0
        return skew
    
    def _calculate_kurtosis(self, data: np.ndarray) -> float:
        """Calculate kurtosis."""
        mean = np.mean(data)
        std = np.std(data)
        kurt = np.mean(((data - mean) / std) ** 4) if std > 0 else 0
        return kurt

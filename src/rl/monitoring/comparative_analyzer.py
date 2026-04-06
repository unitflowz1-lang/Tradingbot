"""
Comparative Analysis System

This module provides comparative analysis between RL agents and existing strategies,
including benchmark comparisons and strategy performance evaluation.
"""

from typing import Dict, List, Any, Optional, Tuple
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
from dataclasses import dataclass, asdict
import json
from pathlib import Path

from .performance_tracker import PerformanceTracker, PerformanceMetrics
from .logger import RLLogger


@dataclass
class ComparisonResult:
    """Result of strategy comparison analysis."""
    strategy_a_id: str
    strategy_b_id: str
    comparison_type: str
    
    # Performance comparison
    return_difference: float
    sharpe_difference: float
    drawdown_difference: float
    win_rate_difference: float
    
    # Statistical significance
    t_statistic: float
    p_value: float
    is_significant: bool
    
    # Overall score
    performance_score: float
    confidence_level: float
    
    # Metadata
    comparison_timestamp: datetime
    sample_size: int
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class ComparativeAnalyzer:
    """
    Comparative analysis system for RL agents and trading strategies.
    
    Provides statistical comparison, benchmark analysis, and performance
    evaluation across different strategies and time periods.
    """
    
    def __init__(self, 
                 save_dir: Optional[str] = None,
                 logger: Optional[RLLogger] = None):
        
        self.save_dir = Path(save_dir) if save_dir else Path("data/analysis")
        self.logger = logger or RLLogger()
        
        # Strategy trackers
        self.strategy_trackers: Dict[str, PerformanceTracker] = {}
        
        # Benchmark data
        self.benchmark_returns: Dict[str, List[Tuple[datetime, float]]] = {}
        
        # Comparison history
        self.comparison_history: List[ComparisonResult] = []
        
        # Create save directory
        self.save_dir.mkdir(parents=True, exist_ok=True)
    
    def register_strategy(self, strategy_id: str, tracker: PerformanceTracker) -> None:
        """Register a strategy for comparative analysis."""
        self.strategy_trackers[strategy_id] = tracker
        
        self.logger.log_system_event(
            "strategy_registered",
            f"Strategy registered for analysis: {strategy_id}",
            {"agent_id": tracker.agent_id}
        )
    
    def add_benchmark_data(self, 
                          benchmark_id: str, 
                          returns_data: List[Tuple[datetime, float]]) -> None:
        """Add benchmark return data for comparison."""
        self.benchmark_returns[benchmark_id] = returns_data
        
        self.logger.log_system_event(
            "benchmark_added",
            f"Benchmark data added: {benchmark_id}",
            {"data_points": len(returns_data)}
        )
    
    def compare_strategies(self, 
                          strategy_a_id: str, 
                          strategy_b_id: str,
                          comparison_period: Optional[timedelta] = None) -> ComparisonResult:
        """
        Compare two strategies statistically.
        
        Args:
            strategy_a_id: First strategy ID
            strategy_b_id: Second strategy ID
            comparison_period: Time period for comparison (None for all data)
            
        Returns:
            Comparison result with statistical analysis
        """
        if strategy_a_id not in self.strategy_trackers:
            raise ValueError(f"Strategy not found: {strategy_a_id}")
        if strategy_b_id not in self.strategy_trackers:
            raise ValueError(f"Strategy not found: {strategy_b_id}")
        
        tracker_a = self.strategy_trackers[strategy_a_id]
        tracker_b = self.strategy_trackers[strategy_b_id]
        
        # Get metrics for comparison period
        metrics_a = self._get_period_metrics(tracker_a, comparison_period)
        metrics_b = self._get_period_metrics(tracker_b, comparison_period)
        
        # Get returns for statistical analysis
        returns_a = self._get_period_returns(tracker_a, comparison_period)
        returns_b = self._get_period_returns(tracker_b, comparison_period)
        
        # Calculate differences
        return_diff = metrics_a.total_return - metrics_b.total_return
        sharpe_diff = metrics_a.sharpe_ratio - metrics_b.sharpe_ratio
        drawdown_diff = metrics_a.max_drawdown - metrics_b.max_drawdown
        win_rate_diff = metrics_a.win_rate - metrics_b.win_rate
        
        # Statistical significance test (t-test)
        t_stat, p_value = self._perform_t_test(returns_a, returns_b)
        is_significant = p_value < 0.05
        
        # Performance score
        performance_score = self._calculate_relative_performance_score(metrics_a, metrics_b)
        
        # Confidence level based on sample size and significance
        confidence_level = self._calculate_confidence_level(
            len(returns_a), len(returns_b), p_value
        )
        
        result = ComparisonResult(
            strategy_a_id=strategy_a_id,
            strategy_b_id=strategy_b_id,
            comparison_type="strategy_vs_strategy",
            return_difference=return_diff,
            sharpe_difference=sharpe_diff,
            drawdown_difference=drawdown_diff,
            win_rate_difference=win_rate_diff,
            t_statistic=t_stat,
            p_value=p_value,
            is_significant=is_significant,
            performance_score=performance_score,
            confidence_level=confidence_level,
            comparison_timestamp=datetime.now(),
            sample_size=min(len(returns_a), len(returns_b))
        )
        
        self.comparison_history.append(result)
        
        self.logger.log_system_event(
            "strategy_comparison",
            f"Compared {strategy_a_id} vs {strategy_b_id}",
            result.to_dict()
        )
        
        return result
    
    def compare_with_benchmark(self, 
                              strategy_id: str, 
                              benchmark_id: str,
                              comparison_period: Optional[timedelta] = None) -> ComparisonResult:
        """
        Compare strategy with benchmark.
        
        Args:
            strategy_id: Strategy to compare
            benchmark_id: Benchmark ID
            comparison_period: Time period for comparison
            
        Returns:
            Comparison result
        """
        if strategy_id not in self.strategy_trackers:
            raise ValueError(f"Strategy not found: {strategy_id}")
        if benchmark_id not in self.benchmark_returns:
            raise ValueError(f"Benchmark not found: {benchmark_id}")
        
        tracker = self.strategy_trackers[strategy_id]
        benchmark_data = self.benchmark_returns[benchmark_id]
        
        # Get strategy metrics and returns
        strategy_metrics = self._get_period_metrics(tracker, comparison_period)
        strategy_returns = self._get_period_returns(tracker, comparison_period)
        
        # Calculate benchmark metrics
        benchmark_returns = self._filter_benchmark_data(benchmark_data, comparison_period)
        benchmark_metrics = self._calculate_benchmark_metrics(benchmark_returns)
        
        # Calculate differences
        return_diff = strategy_metrics.total_return - benchmark_metrics["total_return"]
        sharpe_diff = strategy_metrics.sharpe_ratio - benchmark_metrics["sharpe_ratio"]
        
        # Statistical test
        benchmark_return_values = [r[1] for r in benchmark_returns]
        t_stat, p_value = self._perform_t_test(strategy_returns, benchmark_return_values)
        is_significant = p_value < 0.05
        
        # Performance score
        performance_score = self._calculate_benchmark_performance_score(
            strategy_metrics, benchmark_metrics
        )
        
        confidence_level = self._calculate_confidence_level(
            len(strategy_returns), len(benchmark_return_values), p_value
        )
        
        result = ComparisonResult(
            strategy_a_id=strategy_id,
            strategy_b_id=benchmark_id,
            comparison_type="strategy_vs_benchmark",
            return_difference=return_diff,
            sharpe_difference=sharpe_diff,
            drawdown_difference=0.0,  # Benchmark may not have drawdown data
            win_rate_difference=0.0,  # Benchmark doesn't have win rate
            t_statistic=t_stat,
            p_value=p_value,
            is_significant=is_significant,
            performance_score=performance_score,
            confidence_level=confidence_level,
            comparison_timestamp=datetime.now(),
            sample_size=min(len(strategy_returns), len(benchmark_return_values))
        )
        
        self.comparison_history.append(result)
        
        self.logger.log_system_event(
            "benchmark_comparison",
            f"Compared {strategy_id} vs benchmark {benchmark_id}",
            result.to_dict()
        )
        
        return result
    
    def generate_performance_ranking(self, 
                                   strategy_ids: Optional[List[str]] = None,
                                   ranking_metric: str = "sharpe_ratio") -> List[Dict[str, Any]]:
        """
        Generate performance ranking of strategies.
        
        Args:
            strategy_ids: List of strategies to rank (None for all)
            ranking_metric: Metric to use for ranking
            
        Returns:
            Ranked list of strategies with metrics
        """
        if strategy_ids is None:
            strategy_ids = list(self.strategy_trackers.keys())
        
        rankings = []
        
        for strategy_id in strategy_ids:
            if strategy_id not in self.strategy_trackers:
                continue
                
            tracker = self.strategy_trackers[strategy_id]
            metrics = tracker.get_current_metrics()
            
            ranking_value = getattr(metrics, ranking_metric, 0.0)
            
            rankings.append({
                "strategy_id": strategy_id,
                "agent_id": tracker.agent_id,
                "ranking_metric": ranking_metric,
                "ranking_value": ranking_value,
                "total_return": metrics.total_return,
                "sharpe_ratio": metrics.sharpe_ratio,
                "max_drawdown": metrics.max_drawdown,
                "win_rate": metrics.win_rate,
                "num_trades": metrics.num_trades,
                "last_update": metrics.timestamp.isoformat()
            })
        
        # Sort by ranking metric (descending for most metrics, ascending for drawdown)
        reverse_sort = ranking_metric not in ["max_drawdown", "current_drawdown"]
        rankings.sort(key=lambda x: x["ranking_value"], reverse=reverse_sort)
        
        # Add rank numbers
        for i, ranking in enumerate(rankings):
            ranking["rank"] = i + 1
        
        self.logger.log_system_event(
            "performance_ranking",
            f"Generated ranking by {ranking_metric}",
            {"num_strategies": len(rankings), "top_strategy": rankings[0]["strategy_id"] if rankings else None}
        )
        
        return rankings
    
    def analyze_correlation(self, 
                           strategy_ids: Optional[List[str]] = None,
                           correlation_period: Optional[timedelta] = None) -> Dict[str, Any]:
        """
        Analyze correlation between strategy returns.
        
        Args:
            strategy_ids: Strategies to analyze (None for all)
            correlation_period: Time period for analysis
            
        Returns:
            Correlation matrix and analysis
        """
        if strategy_ids is None:
            strategy_ids = list(self.strategy_trackers.keys())
        
        if len(strategy_ids) < 2:
            return {"error": "Need at least 2 strategies for correlation analysis"}
        
        # Collect returns data
        returns_data = {}
        for strategy_id in strategy_ids:
            if strategy_id in self.strategy_trackers:
                returns = self._get_period_returns(
                    self.strategy_trackers[strategy_id], 
                    correlation_period
                )
                returns_data[strategy_id] = returns
        
        if len(returns_data) < 2:
            return {"error": "Insufficient data for correlation analysis"}
        
        # Create correlation matrix
        correlation_matrix = {}
        for strategy_a in returns_data:
            correlation_matrix[strategy_a] = {}
            for strategy_b in returns_data:
                if strategy_a == strategy_b:
                    correlation_matrix[strategy_a][strategy_b] = 1.0
                else:
                    corr = self._calculate_correlation(
                        returns_data[strategy_a], 
                        returns_data[strategy_b]
                    )
                    correlation_matrix[strategy_a][strategy_b] = corr
        
        # Find highest and lowest correlations
        correlations = []
        for strategy_a in correlation_matrix:
            for strategy_b in correlation_matrix[strategy_a]:
                if strategy_a < strategy_b:  # Avoid duplicates
                    correlations.append({
                        "strategy_a": strategy_a,
                        "strategy_b": strategy_b,
                        "correlation": correlation_matrix[strategy_a][strategy_b]
                    })
        
        correlations.sort(key=lambda x: abs(x["correlation"]), reverse=True)
        
        analysis = {
            "correlation_matrix": correlation_matrix,
            "highest_correlation": correlations[0] if correlations else None,
            "lowest_correlation": correlations[-1] if correlations else None,
            "average_correlation": np.mean([c["correlation"] for c in correlations]) if correlations else 0.0,
            "analysis_timestamp": datetime.now().isoformat(),
            "sample_period": correlation_period.days if correlation_period else "all_data"
        }
        
        self.logger.log_system_event(
            "correlation_analysis",
            f"Analyzed correlation for {len(strategy_ids)} strategies",
            {"average_correlation": analysis["average_correlation"]}
        )
        
        return analysis
    
    def _get_period_metrics(self, 
                           tracker: PerformanceTracker, 
                           period: Optional[timedelta]) -> PerformanceMetrics:
        """Get metrics for specific time period."""
        if period is None:
            return tracker.get_current_metrics()
        
        # For simplicity, return current metrics
        # In a full implementation, this would filter by time period
        return tracker.get_current_metrics()
    
    def _get_period_returns(self, 
                           tracker: PerformanceTracker, 
                           period: Optional[timedelta]) -> List[float]:
        """Get returns for specific time period."""
        if period is None:
            return [r[1] for r in tracker.returns_series]
        
        cutoff_time = datetime.now() - period
        filtered_returns = [
            r[1] for r in tracker.returns_series 
            if r[0] >= cutoff_time
        ]
        
        return filtered_returns
    
    def _filter_benchmark_data(self, 
                              benchmark_data: List[Tuple[datetime, float]], 
                              period: Optional[timedelta]) -> List[Tuple[datetime, float]]:
        """Filter benchmark data by time period."""
        if period is None:
            return benchmark_data
        
        cutoff_time = datetime.now() - period
        return [(ts, ret) for ts, ret in benchmark_data if ts >= cutoff_time]
    
    def _calculate_benchmark_metrics(self, 
                                   benchmark_returns: List[Tuple[datetime, float]]) -> Dict[str, float]:
        """Calculate metrics for benchmark data."""
        if not benchmark_returns:
            return {"total_return": 0.0, "sharpe_ratio": 0.0, "volatility": 0.0}
        
        returns = [r[1] for r in benchmark_returns]
        
        total_return = np.sum(returns)
        volatility = np.std(returns) * np.sqrt(252) if len(returns) > 1 else 0.0
        sharpe_ratio = (np.mean(returns) * 252) / volatility if volatility > 0 else 0.0
        
        return {
            "total_return": total_return,
            "sharpe_ratio": sharpe_ratio,
            "volatility": volatility
        }
    
    def _perform_t_test(self, returns_a: List[float], returns_b: List[float]) -> Tuple[float, float]:
        """Perform t-test for statistical significance."""
        if len(returns_a) < 2 or len(returns_b) < 2:
            return 0.0, 1.0
        
        # Simple t-test implementation
        mean_a = np.mean(returns_a)
        mean_b = np.mean(returns_b)
        
        var_a = np.var(returns_a, ddof=1)
        var_b = np.var(returns_b, ddof=1)
        
        n_a = len(returns_a)
        n_b = len(returns_b)
        
        # Pooled standard error
        pooled_se = np.sqrt(var_a / n_a + var_b / n_b)
        
        if pooled_se == 0:
            return 0.0, 1.0
        
        t_stat = (mean_a - mean_b) / pooled_se
        
        # Degrees of freedom (Welch's t-test approximation)
        df = (var_a / n_a + var_b / n_b) ** 2 / (
            (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (n_b - 1)
        )
        
        # Simplified p-value calculation (would use scipy.stats in practice)
        p_value = 2 * (1 - self._t_cdf(abs(t_stat), df))
        
        return t_stat, p_value
    
    def _t_cdf(self, t: float, df: float) -> float:
        """Simplified t-distribution CDF approximation."""
        # Very simplified approximation - would use scipy.stats.t.cdf in practice
        if df > 30:
            # Approximate as normal distribution for large df
            return 0.5 * (1 + np.tanh(t / np.sqrt(2)))
        else:
            # Rough approximation for small df
            return 0.5 * (1 + t / np.sqrt(df + t**2))
    
    def _calculate_relative_performance_score(self, 
                                            metrics_a: PerformanceMetrics, 
                                            metrics_b: PerformanceMetrics) -> float:
        """Calculate relative performance score between two strategies."""
        weights = {
            "return": 0.3,
            "sharpe": 0.3,
            "drawdown": 0.2,
            "win_rate": 0.2
        }
        
        score = 0.0
        
        # Return comparison
        if metrics_b.total_return != 0:
            return_ratio = metrics_a.total_return / metrics_b.total_return
            score += weights["return"] * min(max(return_ratio, 0), 2.0)
        
        # Sharpe comparison
        if metrics_b.sharpe_ratio != 0:
            sharpe_ratio = metrics_a.sharpe_ratio / metrics_b.sharpe_ratio
            score += weights["sharpe"] * min(max(sharpe_ratio, 0), 2.0)
        
        # Drawdown comparison (inverted)
        if metrics_b.max_drawdown != 0:
            drawdown_ratio = metrics_b.max_drawdown / max(metrics_a.max_drawdown, 0.001)
            score += weights["drawdown"] * min(max(drawdown_ratio, 0), 2.0)
        
        # Win rate comparison
        if metrics_b.win_rate != 0:
            win_rate_ratio = metrics_a.win_rate / metrics_b.win_rate
            score += weights["win_rate"] * min(max(win_rate_ratio, 0), 2.0)
        
        return score
    
    def _calculate_benchmark_performance_score(self, 
                                             strategy_metrics: PerformanceMetrics, 
                                             benchmark_metrics: Dict[str, float]) -> float:
        """Calculate performance score vs benchmark."""
        score = 0.0
        
        # Return comparison
        if benchmark_metrics["total_return"] != 0:
            return_ratio = strategy_metrics.total_return / benchmark_metrics["total_return"]
            score += 0.5 * min(max(return_ratio, 0), 2.0)
        
        # Sharpe comparison
        if benchmark_metrics["sharpe_ratio"] != 0:
            sharpe_ratio = strategy_metrics.sharpe_ratio / benchmark_metrics["sharpe_ratio"]
            score += 0.5 * min(max(sharpe_ratio, 0), 2.0)
        
        return score
    
    def _calculate_confidence_level(self, 
                                   sample_size_a: int, 
                                   sample_size_b: int, 
                                   p_value: float) -> float:
        """Calculate confidence level for comparison."""
        min_sample_size = min(sample_size_a, sample_size_b)
        
        # Base confidence on sample size and p-value
        size_factor = min(min_sample_size / 100.0, 1.0)  # Max 1.0 for 100+ samples
        significance_factor = max(0, 1 - p_value)  # Higher for lower p-value
        
        confidence = (size_factor + significance_factor) / 2
        
        return confidence
    
    def _calculate_correlation(self, returns_a: List[float], returns_b: List[float]) -> float:
        """Calculate correlation between two return series."""
        if len(returns_a) != len(returns_b) or len(returns_a) < 2:
            return 0.0
        
        # Align series by taking minimum length
        min_len = min(len(returns_a), len(returns_b))
        returns_a = returns_a[-min_len:]
        returns_b = returns_b[-min_len:]
        
        return np.corrcoef(returns_a, returns_b)[0, 1]
    
    def save_analysis_results(self, filename: Optional[str] = None) -> str:
        """Save analysis results to file."""
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"comparative_analysis_{timestamp}.json"
        
        filepath = self.save_dir / filename
        
        data = {
            "comparison_history": [result.to_dict() for result in self.comparison_history],
            "registered_strategies": list(self.strategy_trackers.keys()),
            "available_benchmarks": list(self.benchmark_returns.keys()),
            "analysis_timestamp": datetime.now().isoformat()
        }
        
        # Convert datetime objects to strings for JSON serialization
        def convert_datetime(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            return obj
            
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2, default=convert_datetime)
        
        self.logger.log_system_event(
            "analysis_results_saved",
            f"Analysis results saved to {filepath}",
            {"num_comparisons": len(self.comparison_history)}
        )
        
        return str(filepath)
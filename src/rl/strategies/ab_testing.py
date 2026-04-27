"""
A/B Testing Framework for RL Strategy Comparison

This module provides comprehensive A/B testing capabilities for comparing
RL trading strategies with statistical significance testing and automated
strategy switching based on performance metrics.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any, Callable
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from enum import Enum
import logging
from scipy import stats
import warnings

from .models import RLStrategy, PerformanceMetrics
from .registry import StrategyRegistry


logger = logging.getLogger(__name__)


class ABTestStatus(Enum):
    """A/B test status."""

    SETUP = "SETUP"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


class SignificanceTest(Enum):
    """Statistical significance test types."""

    T_TEST = "t_test"
    WELCH_T_TEST = "welch_t_test"
    MANN_WHITNEY = "mann_whitney"
    BOOTSTRAP = "bootstrap"
    BAYESIAN = "bayesian"


@dataclass
class ABTestConfiguration:
    """Configuration for A/B test."""

    test_name: str
    strategy_a_id: str
    strategy_b_id: str
    allocation_split: Tuple[float, float] = (0.5, 0.5)  # (A, B) allocation
    primary_metric: str = "sharpe_ratio"
    secondary_metrics: List[str] = field(
        default_factory=lambda: ["total_return", "max_drawdown"]
    )
    significance_level: float = 0.05
    minimum_sample_size: int = 100
    maximum_duration_days: int = 30
    early_stopping_enabled: bool = True
    significance_test: SignificanceTest = SignificanceTest.WELCH_T_TEST

    def __post_init__(self):
        """Validate configuration."""
        if not 0 < self.allocation_split[0] < 1:
            raise ValueError(f"Invalid allocation split: {self.allocation_split}")
        if abs(sum(self.allocation_split) - 1.0) > 1e-6:
            raise ValueError(
                f"Allocation split must sum to 1.0: {self.allocation_split}"
            )
        if not 0 < self.significance_level < 1:
            raise ValueError(
                f"Significance level must be between 0 and 1: {self.significance_level}"
            )
        if self.minimum_sample_size < 10:
            raise ValueError(
                f"Minimum sample size too small: {self.minimum_sample_size}"
            )


@dataclass
class StatisticalTestResult:
    """Result of statistical significance test."""

    test_type: SignificanceTest
    statistic: float
    p_value: float
    is_significant: bool
    confidence_interval: Tuple[float, float]
    effect_size: float
    power: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "test_type": self.test_type.value,
            "statistic": self.statistic,
            "p_value": self.p_value,
            "is_significant": self.is_significant,
            "confidence_interval": list(self.confidence_interval),
            "effect_size": self.effect_size,
            "power": self.power,
        }


@dataclass
class ABTestSnapshot:
    """Snapshot of A/B test state at a point in time."""

    timestamp: datetime
    strategy_a_metrics: Dict[str, float]
    strategy_b_metrics: Dict[str, float]
    sample_sizes: Tuple[int, int]  # (A, B)
    test_results: Dict[str, StatisticalTestResult]
    cumulative_performance: Dict[str, List[float]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp.isoformat(),
            "strategy_a_metrics": self.strategy_a_metrics,
            "strategy_b_metrics": self.strategy_b_metrics,
            "sample_sizes": list(self.sample_sizes),
            "test_results": {k: v.to_dict() for k, v in self.test_results.items()},
            "cumulative_performance": self.cumulative_performance,
        }


class ABTestingFramework:
    """
    Comprehensive A/B testing framework for strategy comparison.

    Provides controlled strategy evaluation with statistical significance testing,
    automated strategy switching, and comprehensive performance tracking.
    """

    def __init__(
        self,
        strategy_registry: StrategyRegistry,
        min_confidence_level: float = 0.95,
        auto_switch_enabled: bool = True,
    ):
        """
        Initialize A/B testing framework.

        Args:
            strategy_registry: Strategy registry for accessing strategies
            min_confidence_level: Minimum confidence level for significance
            auto_switch_enabled: Whether to enable automatic strategy switching
        """
        self.strategy_registry = strategy_registry
        self.min_confidence_level = min_confidence_level
        self.auto_switch_enabled = auto_switch_enabled

        # Active tests
        self.active_tests: Dict[str, "ABTest"] = {}
        self.completed_tests: Dict[str, "ABTest"] = {}

        # Performance tracking
        self.performance_data: Dict[str, List[Dict[str, Any]]] = {}

        # Callbacks for test events
        self.test_callbacks: Dict[str, List[Callable]] = {
            "test_started": [],
            "test_completed": [],
            "significance_achieved": [],
            "strategy_switched": [],
        }

    def create_test(
        self, config: ABTestConfiguration, start_immediately: bool = True
    ) -> str:
        """
        Create new A/B test.

        Args:
            config: Test configuration
            start_immediately: Whether to start test immediately

        Returns:
            Test ID

        Raises:
            ValueError: If strategies not found or invalid configuration
        """
        # Validate strategies exist
        strategy_a = self.strategy_registry.get_strategy(config.strategy_a_id)
        strategy_b = self.strategy_registry.get_strategy(config.strategy_b_id)

        if not strategy_a:
            raise ValueError(f"Strategy A not found: {config.strategy_a_id}")
        if not strategy_b:
            raise ValueError(f"Strategy B not found: {config.strategy_b_id}")

        # Create test instance
        test = ABTest(config, strategy_a, strategy_b)
        test_id = test.test_id

        # Check for conflicts with existing tests
        if self._has_conflicting_test(config):
            raise ValueError(
                f"Conflicting test already running for strategies {config.strategy_a_id} or {config.strategy_b_id}"
            )

        self.active_tests[test_id] = test

        if start_immediately:
            self.start_test(test_id)

        logger.info(f"Created A/B test: {test_id} ({config.test_name})")
        return test_id

    def start_test(self, test_id: str) -> bool:
        """
        Start A/B test.

        Args:
            test_id: Test identifier

        Returns:
            True if started successfully
        """
        test = self.active_tests.get(test_id)
        if not test:
            logger.error(f"Test not found: {test_id}")
            return False

        if test.status != ABTestStatus.SETUP:
            logger.warning(f"Test {test_id} already started or completed")
            return False

        test.start()
        self._trigger_callbacks("test_started", test)

        logger.info(f"Started A/B test: {test_id}")
        return True

    def stop_test(self, test_id: str, reason: str = "Manual stop") -> bool:
        """
        Stop running A/B test.

        Args:
            test_id: Test identifier
            reason: Reason for stopping

        Returns:
            True if stopped successfully
        """
        test = self.active_tests.get(test_id)
        if not test:
            logger.error(f"Test not found: {test_id}")
            return False

        test.stop(reason)
        self._move_to_completed(test_id)

        logger.info(f"Stopped A/B test: {test_id} - {reason}")
        return True

    def update_performance(
        self, strategy_id: str, performance_data: Dict[str, Any]
    ) -> None:
        """
        Update performance data for strategy in active tests.

        Args:
            strategy_id: Strategy identifier
            performance_data: Performance metrics and data
        """
        # Store performance data
        if strategy_id not in self.performance_data:
            self.performance_data[strategy_id] = []

        performance_data["timestamp"] = datetime.now()
        self.performance_data[strategy_id].append(performance_data)

        # Update active tests involving this strategy
        for test in self.active_tests.values():
            if test.status == ABTestStatus.RUNNING:
                if strategy_id in [
                    test.strategy_a.strategy_id,
                    test.strategy_b.strategy_id,
                ]:
                    test.add_performance_data(strategy_id, performance_data)

                    # Check for significance and early stopping
                    if test.config.early_stopping_enabled:
                        self._check_early_stopping(test)

    def get_test_status(self, test_id: str) -> Optional[Dict[str, Any]]:
        """
        Get current status of A/B test.

        Args:
            test_id: Test identifier

        Returns:
            Test status information or None if not found
        """
        test = self.active_tests.get(test_id) or self.completed_tests.get(test_id)
        if not test:
            return None

        return test.get_status_summary()

    def get_test_results(self, test_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed results of A/B test.

        Args:
            test_id: Test identifier

        Returns:
            Detailed test results or None if not found
        """
        test = self.active_tests.get(test_id) or self.completed_tests.get(test_id)
        if not test:
            return None

        return test.get_detailed_results()

    def list_active_tests(self) -> List[Dict[str, Any]]:
        """Get list of active tests."""
        return [
            {
                "test_id": test_id,
                "test_name": test.config.test_name,
                "status": test.status.value,
                "strategy_a": test.strategy_a.name,
                "strategy_b": test.strategy_b.name,
                "started_at": test.started_at.isoformat() if test.started_at else None,
                "duration_days": test.get_duration_days(),
            }
            for test_id, test in self.active_tests.items()
        ]

    def get_winner_recommendation(self, test_id: str) -> Optional[Dict[str, Any]]:
        """
        Get winner recommendation based on test results.

        Args:
            test_id: Test identifier

        Returns:
            Winner recommendation with confidence metrics
        """
        test = self.active_tests.get(test_id) or self.completed_tests.get(test_id)
        if not test:
            return None

        return test.get_winner_recommendation()

    def register_callback(self, event: str, callback: Callable) -> None:
        """
        Register callback for test events.

        Args:
            event: Event type ('test_started', 'test_completed', etc.)
            callback: Callback function
        """
        if event in self.test_callbacks:
            self.test_callbacks[event].append(callback)
        else:
            raise ValueError(f"Unknown event type: {event}")

    def calculate_required_sample_size(
        self, effect_size: float, power: float = 0.8, significance_level: float = 0.05
    ) -> int:
        """
        Calculate required sample size for detecting effect.

        Args:
            effect_size: Minimum effect size to detect
            power: Statistical power (1 - Type II error rate)
            significance_level: Type I error rate

        Returns:
            Required sample size per group
        """
        # Using Cohen's formula for two-sample t-test
        z_alpha = stats.norm.ppf(1 - significance_level / 2)
        z_beta = stats.norm.ppf(power)

        n = 2 * ((z_alpha + z_beta) / effect_size) ** 2
        return int(np.ceil(n))

    def _has_conflicting_test(self, config: ABTestConfiguration) -> bool:
        """Check if there's a conflicting test already running."""
        for test in self.active_tests.values():
            if test.status in [ABTestStatus.RUNNING, ABTestStatus.SETUP]:
                if config.strategy_a_id in [
                    test.strategy_a.strategy_id,
                    test.strategy_b.strategy_id,
                ] or config.strategy_b_id in [
                    test.strategy_a.strategy_id,
                    test.strategy_b.strategy_id,
                ]:
                    return True
        return False

    def _check_early_stopping(self, test: "ABTest") -> None:
        """Check if test should be stopped early due to significance."""
        if test.get_duration_days() < 7:  # Minimum 7 days before early stopping
            return

        # Check if primary metric shows significance
        primary_result = test.get_latest_significance_test(test.config.primary_metric)
        if primary_result and primary_result.is_significant:
            # Check if we have minimum sample size
            sample_sizes = test.get_sample_sizes()
            if min(sample_sizes) >= test.config.minimum_sample_size:
                test.stop("Early stopping - significance achieved")
                self._move_to_completed(test.test_id)
                self._trigger_callbacks("significance_achieved", test)

                # Auto-switch if enabled
                if self.auto_switch_enabled:
                    self._handle_auto_switch(test)

    def _handle_auto_switch(self, test: "ABTest") -> None:
        """Handle automatic strategy switching based on test results."""
        winner = test.get_winner_recommendation()
        if winner and winner["confidence"] >= self.min_confidence_level:
            winner_strategy_id = winner["winner_strategy_id"]
            logger.info(f"Auto-switching to winning strategy: {winner_strategy_id}")
            self._trigger_callbacks("strategy_switched", test)

    def _move_to_completed(self, test_id: str) -> None:
        """Move test from active to completed."""
        if test_id in self.active_tests:
            test = self.active_tests.pop(test_id)
            self.completed_tests[test_id] = test
            self._trigger_callbacks("test_completed", test)

    def _trigger_callbacks(self, event: str, test: "ABTest") -> None:
        """Trigger callbacks for test event."""
        for callback in self.test_callbacks.get(event, []):
            try:
                callback(test)
            except Exception as e:
                logger.error(f"Callback error for {event}: {e}")


class ABTest:
    """Individual A/B test instance."""

    def __init__(
        self, config: ABTestConfiguration, strategy_a: RLStrategy, strategy_b: RLStrategy
    ):
        """Initialize A/B test."""
        self.config = config
        self.strategy_a = strategy_a
        self.strategy_b = strategy_b

        # Generate unique test ID
        self.test_id = f"ab_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{config.test_name.replace(' ', '_')}"

        # Test state
        self.status = ABTestStatus.SETUP
        self.created_at = datetime.now()
        self.started_at: Optional[datetime] = None
        self.completed_at: Optional[datetime] = None
        self.stop_reason: Optional[str] = None

        # Performance data
        self.performance_history: Dict[str, List[Dict[str, Any]]] = {
            strategy_a.strategy_id: [],
            strategy_b.strategy_id: [],
        }

        # Test snapshots
        self.snapshots: List[ABTestSnapshot] = []

        # Statistical test results
        self.significance_results: Dict[str, List[StatisticalTestResult]] = {}

    def start(self) -> None:
        """Start the A/B test."""
        self.status = ABTestStatus.RUNNING
        self.started_at = datetime.now()

    def stop(self, reason: str) -> None:
        """Stop the A/B test."""
        self.status = (
            ABTestStatus.STOPPED
            if self.status == ABTestStatus.RUNNING
            else ABTestStatus.COMPLETED
        )
        self.completed_at = datetime.now()
        self.stop_reason = reason

    def add_performance_data(
        self, strategy_id: str, performance_data: Dict[str, Any]
    ) -> None:
        """Add performance data for strategy."""
        if strategy_id in self.performance_history:
            self.performance_history[strategy_id].append(performance_data)

            # Create snapshot if enough data
            if self._should_create_snapshot():
                self._create_snapshot()

    def get_sample_sizes(self) -> Tuple[int, int]:
        """Get current sample sizes for both strategies."""
        return (
            len(self.performance_history[self.strategy_a.strategy_id]),
            len(self.performance_history[self.strategy_b.strategy_id]),
        )

    def get_duration_days(self) -> float:
        """Get test duration in days."""
        if not self.started_at:
            return 0.0

        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds() / 86400

    def get_latest_significance_test(self, metric: str) -> Optional[StatisticalTestResult]:
        """Get latest significance test result for metric."""
        if metric not in self.significance_results:
            return None

        results = self.significance_results[metric]
        return results[-1] if results else None

    def get_status_summary(self) -> Dict[str, Any]:
        """Get test status summary."""
        sample_sizes = self.get_sample_sizes()

        return {
            "test_id": self.test_id,
            "test_name": self.config.test_name,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": (
                self.completed_at.isoformat() if self.completed_at else None
            ),
            "duration_days": self.get_duration_days(),
            "strategy_a": {
                "id": self.strategy_a.strategy_id,
                "name": self.strategy_a.name,
                "sample_size": sample_sizes[0],
            },
            "strategy_b": {
                "id": self.strategy_b.strategy_id,
                "name": self.strategy_b.name,
                "sample_size": sample_sizes[1],
            },
            "primary_metric": self.config.primary_metric,
            "stop_reason": self.stop_reason,
        }

    def get_detailed_results(self) -> Dict[str, Any]:
        """Get detailed test results."""
        # Calculate current metrics
        current_metrics = self._calculate_current_metrics()

        # Get latest significance tests
        significance_tests = {}
        for metric in [self.config.primary_metric] + self.config.secondary_metrics:
            latest_result = self.get_latest_significance_test(metric)
            if latest_result:
                significance_tests[metric] = latest_result.to_dict()

        return {
            **self.get_status_summary(),
            "configuration": {
                "allocation_split": self.config.allocation_split,
                "primary_metric": self.config.primary_metric,
                "secondary_metrics": self.config.secondary_metrics,
                "significance_level": self.config.significance_level,
                "minimum_sample_size": self.config.minimum_sample_size,
                "maximum_duration_days": self.config.maximum_duration_days,
                "significance_test": self.config.significance_test.value,
            },
            "current_metrics": current_metrics,
            "significance_tests": significance_tests,
            "winner_recommendation": self.get_winner_recommendation(),
            "snapshots_count": len(self.snapshots),
        }

    def get_winner_recommendation(self) -> Optional[Dict[str, Any]]:
        """Get winner recommendation based on current results."""
        primary_result = self.get_latest_significance_test(self.config.primary_metric)
        if not primary_result:
            return None

        current_metrics = self._calculate_current_metrics()
        if not current_metrics:
            return None

        strategy_a_metric = current_metrics["strategy_a"].get(
            self.config.primary_metric
        )
        strategy_b_metric = current_metrics["strategy_b"].get(
            self.config.primary_metric
        )

        if strategy_a_metric is None or strategy_b_metric is None:
            return None

        # Determine winner
        winner_is_a = strategy_a_metric > strategy_b_metric
        winner_strategy = self.strategy_a if winner_is_a else self.strategy_b
        winner_metric = strategy_a_metric if winner_is_a else strategy_b_metric
        loser_metric = strategy_b_metric if winner_is_a else strategy_a_metric

        # Calculate confidence
        confidence = (1 - primary_result.p_value) * 100

        return {
            "winner_strategy_id": winner_strategy.strategy_id,
            "winner_strategy_name": winner_strategy.name,
            "is_significant": primary_result.is_significant,
            "confidence": confidence,
            "p_value": primary_result.p_value,
            "effect_size": primary_result.effect_size,
            "winner_metric_value": winner_metric,
            "loser_metric_value": loser_metric,
            "improvement": (
                ((winner_metric - loser_metric) / abs(loser_metric)) * 100
                if loser_metric != 0
                else 0
            ),
        }

    def _should_create_snapshot(self) -> bool:
        """Check if snapshot should be created."""
        if not self.snapshots:
            return True

        # Create snapshot every 24 hours or every 100 data points
        last_snapshot = self.snapshots[-1]
        # Handle both naive and aware datetimes
        now = datetime.now(timezone.utc) if last_snapshot.timestamp.tzinfo else datetime.now()
        time_since_last = now - last_snapshot.timestamp

        return (
            time_since_last.total_seconds() > 86400  # 24 hours
            or sum(len(data) for data in self.performance_history.values()) % 100 == 0
        )

    def _create_snapshot(self) -> None:
        """Create test snapshot."""
        current_metrics = self._calculate_current_metrics()
        if not current_metrics:
            return

        # Run significance tests
        test_results = {}
        for metric in [self.config.primary_metric] + self.config.secondary_metrics:
            result = self._run_significance_test(metric)
            if result:
                test_results[metric] = result

                # Store in history
                if metric not in self.significance_results:
                    self.significance_results[metric] = []
                self.significance_results[metric].append(result)

        # Create snapshot
        snapshot = ABTestSnapshot(
            timestamp=datetime.now(),
            strategy_a_metrics=current_metrics["strategy_a"],
            strategy_b_metrics=current_metrics["strategy_b"],
            sample_sizes=self.get_sample_sizes(),
            test_results=test_results,
            cumulative_performance=self._get_cumulative_performance(),
        )

        self.snapshots.append(snapshot)

    def _calculate_current_metrics(self) -> Optional[Dict[str, Dict[str, float]]]:
        """Calculate current average metrics for both strategies."""
        metrics_a = self._calculate_strategy_metrics(self.strategy_a.strategy_id)
        metrics_b = self._calculate_strategy_metrics(self.strategy_b.strategy_id)

        if not metrics_a or not metrics_b:
            return None

        return {"strategy_a": metrics_a, "strategy_b": metrics_b}

    def _calculate_strategy_metrics(
        self, strategy_id: str
    ) -> Optional[Dict[str, float]]:
        """Calculate average metrics for strategy."""
        data = self.performance_history.get(strategy_id, [])
        if not data:
            return None

        metrics = {}
        metric_names = [self.config.primary_metric] + self.config.secondary_metrics

        for metric in metric_names:
            values = [d.get(metric) for d in data if metric in d]
            if values:
                metrics[metric] = np.mean(values)

        return metrics

    def _run_significance_test(self, metric: str) -> Optional[StatisticalTestResult]:
        """Run significance test for metric."""
        # Get metric values for both strategies
        data_a = [
            d.get(metric)
            for d in self.performance_history[self.strategy_a.strategy_id]
            if metric in d
        ]
        data_b = [
            d.get(metric)
            for d in self.performance_history[self.strategy_b.strategy_id]
            if metric in d
        ]

        if len(data_a) < 10 or len(data_b) < 10:
            return None

        data_a = np.array(data_a)
        data_b = np.array(data_b)

        # Choose test based on configuration
        if self.config.significance_test == SignificanceTest.T_TEST:
            return self._t_test(data_a, data_b)
        elif self.config.significance_test == SignificanceTest.WELCH_T_TEST:
            return self._welch_t_test(data_a, data_b)
        elif self.config.significance_test == SignificanceTest.MANN_WHITNEY:
            return self._mann_whitney_test(data_a, data_b)
        elif self.config.significance_test == SignificanceTest.BOOTSTRAP:
            return self._bootstrap_test(data_a, data_b)
        else:
            return self._welch_t_test(data_a, data_b)  # Default

    def _t_test(self, data_a: np.ndarray, data_b: np.ndarray) -> StatisticalTestResult:
        """Perform two-sample t-test."""
        statistic, p_value = stats.ttest_ind(data_a, data_b, equal_var=True)

        # Calculate effect size (Cohen's d)
        pooled_std = np.sqrt(
            (
                (len(data_a) - 1) * np.var(data_a, ddof=1)
                + (len(data_b) - 1) * np.var(data_b, ddof=1)
            )
            / (len(data_a) + len(data_b) - 2)
        )
        effect_size = (
            (np.mean(data_a) - np.mean(data_b)) / pooled_std if pooled_std > 0 else 0
        )

        # Confidence interval
        se = pooled_std * np.sqrt(1 / len(data_a) + 1 / len(data_b))
        df = len(data_a) + len(data_b) - 2
        t_critical = stats.t.ppf(1 - self.config.significance_level / 2, df)
        mean_diff = np.mean(data_a) - np.mean(data_b)
        ci = (mean_diff - t_critical * se, mean_diff + t_critical * se)

        return StatisticalTestResult(
            test_type=SignificanceTest.T_TEST,
            statistic=float(statistic),
            p_value=float(p_value),
            is_significant=bool(p_value < self.config.significance_level),
            confidence_interval=(float(ci[0]), float(ci[1])),
            effect_size=float(effect_size),
        )

    def _welch_t_test(self, data_a: np.ndarray, data_b: np.ndarray) -> StatisticalTestResult:
        """Perform Welch's t-test (unequal variances)."""
        statistic, p_value = stats.ttest_ind(data_a, data_b, equal_var=False)

        # Calculate effect size
        pooled_std = np.sqrt((np.var(data_a, ddof=1) + np.var(data_b, ddof=1)) / 2)
        effect_size = (
            (np.mean(data_a) - np.mean(data_b)) / pooled_std if pooled_std > 0 else 0
        )

        # Confidence interval (approximate)
        se_a = np.std(data_a, ddof=1) / np.sqrt(len(data_a))
        se_b = np.std(data_b, ddof=1) / np.sqrt(len(data_b))
        se_diff = np.sqrt(se_a**2 + se_b**2)

        # Welch-Satterthwaite degrees of freedom
        df = (se_a**2 + se_b**2) ** 2 / (
            se_a**4 / (len(data_a) - 1) + se_b**4 / (len(data_b) - 1)
        )
        t_critical = stats.t.ppf(1 - self.config.significance_level / 2, df)
        mean_diff = np.mean(data_a) - np.mean(data_b)
        ci = (mean_diff - t_critical * se_diff, mean_diff + t_critical * se_diff)

        return StatisticalTestResult(
            test_type=SignificanceTest.WELCH_T_TEST,
            statistic=float(statistic),
            p_value=float(p_value),
            is_significant=bool(p_value < self.config.significance_level),
            confidence_interval=(float(ci[0]), float(ci[1])),
            effect_size=float(effect_size),
        )

    def _mann_whitney_test(self, data_a: np.ndarray, data_b: np.ndarray) -> StatisticalTestResult:
        """Perform Mann-Whitney U test."""
        statistic, p_value = stats.mannwhitneyu(data_a, data_b, alternative="two-sided")

        # Effect size (rank-biserial correlation)
        n_a, n_b = len(data_a), len(data_b)
        effect_size = 2 * statistic / (n_a * n_b) - 1

        # Confidence interval (approximate)
        mean_diff = np.mean(data_a) - np.mean(data_b)
        se_diff = np.sqrt(
            np.var(data_a, ddof=1) / len(data_a) + np.var(data_b, ddof=1) / len(data_b)
        )
        z_critical = stats.norm.ppf(1 - self.config.significance_level / 2)
        ci = (mean_diff - z_critical * se_diff, mean_diff + z_critical * se_diff)

        return StatisticalTestResult(
            test_type=SignificanceTest.MANN_WHITNEY,
            statistic=float(statistic),
            p_value=float(p_value),
            is_significant=bool(p_value < self.config.significance_level),
            confidence_interval=(float(ci[0]), float(ci[1])),
            effect_size=float(effect_size),
        )

    def _bootstrap_test(
        self, data_a: np.ndarray, data_b: np.ndarray, n_bootstrap: int = 10000
    ) -> StatisticalTestResult:
        """Perform bootstrap test."""
        # Original difference
        original_diff = np.mean(data_a) - np.mean(data_b)

        # Bootstrap resampling
        combined_data = np.concatenate([data_a, data_b])
        n_a = len(data_a)

        bootstrap_diffs = []
        for _ in range(n_bootstrap):
            resampled = np.random.choice(
                combined_data, size=len(combined_data), replace=True
            )
            bootstrap_a = resampled[:n_a]
            bootstrap_b = resampled[n_a:]
            bootstrap_diffs.append(np.mean(bootstrap_a) - np.mean(bootstrap_b))

        bootstrap_diffs = np.array(bootstrap_diffs)

        # P-value (two-tailed)
        p_value = 2 * min(
            np.mean(bootstrap_diffs >= abs(original_diff)),
            np.mean(bootstrap_diffs <= -abs(original_diff)),
        )

        # Confidence interval
        alpha = self.config.significance_level
        ci_lower = np.percentile(bootstrap_diffs, 100 * alpha / 2)
        ci_upper = np.percentile(bootstrap_diffs, 100 * (1 - alpha / 2))

        # Effect size
        pooled_std = np.sqrt((np.var(data_a, ddof=1) + np.var(data_b, ddof=1)) / 2)
        effect_size = original_diff / pooled_std if pooled_std > 0 else 0

        return StatisticalTestResult(
            test_type=SignificanceTest.BOOTSTRAP,
            statistic=float(original_diff),
            p_value=float(p_value),
            is_significant=bool(p_value < self.config.significance_level),
            confidence_interval=(float(ci_lower), float(ci_upper)),
            effect_size=float(effect_size),
        )

    def _get_cumulative_performance(self) -> Dict[str, List[float]]:
        """Get cumulative performance for both strategies."""
        cumulative = {}

        for strategy_id in [self.strategy_a.strategy_id, self.strategy_b.strategy_id]:
            data = self.performance_history[strategy_id]
            if data and self.config.primary_metric in data[0]:
                values = [
                    d[self.config.primary_metric]
                    for d in data
                    if self.config.primary_metric in d
                ]
                cumulative[strategy_id] = np.cumsum(values).tolist()
            else:
                cumulative[strategy_id] = []

        return cumulative

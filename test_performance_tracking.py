"""
Unit tests for RL performance tracking system.

Tests comprehensive performance tracking, dashboard data collection,
and comparative analysis functionality.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import numpy as np
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import json

from src.rl.monitoring.performance_tracker import (
    PerformanceTracker, PerformanceMetrics, TradeRecord
)
from src.rl.monitoring.comparative_analyzer import (
    ComparativeAnalyzer, ComparisonResult
)
from src.rl.monitoring.logger import RLLogger


class TestPerformanceTracker(unittest.TestCase):
    """Test cases for PerformanceTracker class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.logger = Mock(spec=RLLogger)
        
        self.tracker = PerformanceTracker(
            agent_id="test_agent",
            save_dir=self.temp_dir,
            logger=self.logger
        )
        
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
        
    def test_initialization(self):
        """Test tracker initialization."""
        self.assertEqual(self.tracker.agent_id, "test_agent")
        self.assertEqual(self.tracker.initial_capital, 100000.0)
        self.assertEqual(self.tracker.current_equity, 100000.0)
        self.assertEqual(len(self.tracker.trades), 0)
        self.assertIsNone(self.tracker.current_metrics)
        
    def test_record_trade_entry(self):
        """Test recording trade entry."""
        entry_time = datetime.now()
        trade_id = self.tracker.record_trade_entry(
            entry_time=entry_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD",
            strategy_id="test_strategy"
        )
        
        self.assertIn(trade_id, self.tracker.open_positions)
        trade = self.tracker.open_positions[trade_id]
        
        self.assertEqual(trade.entry_time, entry_time)
        self.assertEqual(trade.entry_price, 1.2000)
        self.assertEqual(trade.position_size, 10000)
        self.assertEqual(trade.currency_pair, "EURUSD")
        self.assertEqual(trade.strategy_id, "test_strategy")
        self.assertIsNone(trade.exit_time)
        self.assertIsNone(trade.pnl)
        
        # Verify logging
        self.logger.log_system_event.assert_called()
        
    def test_record_trade_exit_profitable(self):
        """Test recording profitable trade exit."""
        # Enter trade
        entry_time = datetime.now()
        trade_id = self.tracker.record_trade_entry(
            entry_time=entry_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        
        # Exit trade
        exit_time = entry_time + timedelta(hours=2)
        completed_trade = self.tracker.record_trade_exit(
            trade_id=trade_id,
            exit_time=exit_time,
            exit_price=1.2050
        )
        
        self.assertIsNotNone(completed_trade)
        self.assertEqual(completed_trade.exit_price, 1.2050)
        self.assertAlmostEqual(completed_trade.pnl, 50.0, places=1)  # (1.2050 - 1.2000) * 10000
        self.assertEqual(completed_trade.duration, 2.0)  # 2 hours
        
        # Check equity update
        self.assertAlmostEqual(self.tracker.current_equity, 100050.0, places=1)
        self.assertEqual(len(self.tracker.trades), 1)
        self.assertNotIn(trade_id, self.tracker.open_positions)
        
    def test_record_trade_exit_losing(self):
        """Test recording losing trade exit."""
        # Enter trade
        entry_time = datetime.now()
        trade_id = self.tracker.record_trade_entry(
            entry_time=entry_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        
        # Exit trade at loss
        exit_time = entry_time + timedelta(hours=1)
        completed_trade = self.tracker.record_trade_exit(
            trade_id=trade_id,
            exit_time=exit_time,
            exit_price=1.1950
        )
        
        self.assertAlmostEqual(completed_trade.pnl, -50.0, places=1)  # (1.1950 - 1.2000) * 10000
        self.assertAlmostEqual(self.tracker.current_equity, 99950.0, places=1)
        
    def test_record_trade_exit_invalid_id(self):
        """Test recording trade exit with invalid ID."""
        exit_time = datetime.now()
        result = self.tracker.record_trade_exit(
            trade_id="invalid_id",
            exit_time=exit_time,
            exit_price=1.2000
        )
        
        self.assertIsNone(result)
        self.logger.log_error.assert_called()
        
    def test_update_equity(self):
        """Test equity update functionality."""
        timestamp = datetime.now()
        new_equity = 105000.0
        
        self.tracker.update_equity(timestamp, new_equity)
        
        self.assertEqual(self.tracker.current_equity, new_equity)
        self.assertEqual(self.tracker.peak_equity, new_equity)
        self.assertEqual(len(self.tracker.equity_curve), 1)
        self.assertEqual(self.tracker.equity_curve[0], (timestamp, new_equity))
        
    def test_calculate_metrics_empty(self):
        """Test metrics calculation with no data."""
        metrics = self.tracker._calculate_metrics()
        
        self.assertEqual(metrics.total_return, 0.0)
        self.assertEqual(metrics.num_trades, 0)
        self.assertEqual(metrics.win_rate, 0.0)
        
    def test_calculate_metrics_with_trades(self):
        """Test metrics calculation with trade data."""
        # Create some test trades
        base_time = datetime.now()
        
        # Winning trade
        trade_id_1 = self.tracker.record_trade_entry(
            entry_time=base_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        self.tracker.record_trade_exit(
            trade_id=trade_id_1,
            exit_time=base_time + timedelta(hours=1),
            exit_price=1.2050
        )
        
        # Losing trade
        trade_id_2 = self.tracker.record_trade_entry(
            entry_time=base_time + timedelta(hours=2),
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        self.tracker.record_trade_exit(
            trade_id=trade_id_2,
            exit_time=base_time + timedelta(hours=3),
            exit_price=1.1980
        )
        
        metrics = self.tracker.get_current_metrics()
        
        self.assertEqual(metrics.num_trades, 2)
        self.assertEqual(metrics.win_rate, 0.5)  # 1 win out of 2 trades
        self.assertAlmostEqual(metrics.avg_win, 50.0, places=1)
        self.assertAlmostEqual(metrics.avg_loss, 20.0, places=1)
        self.assertGreater(metrics.profit_factor, 0)
        
    def test_get_dashboard_data(self):
        """Test dashboard data generation."""
        # Add some test data
        timestamp = datetime.now()
        self.tracker.update_equity(timestamp, 105000.0)
        
        dashboard_data = self.tracker.get_dashboard_data()
        
        self.assertEqual(dashboard_data["agent_id"], "test_agent")
        self.assertIn("current_metrics", dashboard_data)
        self.assertIn("equity_curve", dashboard_data)
        self.assertIn("returns_series", dashboard_data)
        self.assertIn("recent_trades", dashboard_data)
        self.assertIn("last_update", dashboard_data)
        
    def test_save_and_load_performance_data(self):
        """Test saving and loading performance data."""
        # Create test data
        base_time = datetime.now()
        trade_id = self.tracker.record_trade_entry(
            entry_time=base_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        self.tracker.record_trade_exit(
            trade_id=trade_id,
            exit_time=base_time + timedelta(hours=1),
            exit_price=1.2050
        )
        
        # Save data
        filename = self.tracker.save_performance_data()
        self.assertTrue(Path(filename).exists())
        
        # Create new tracker and load data
        new_tracker = PerformanceTracker(
            agent_id="test_agent",
            save_dir=self.temp_dir,
            logger=self.logger
        )
        
        new_tracker.load_performance_data(Path(filename).name)
        
        # Verify loaded data
        self.assertEqual(len(new_tracker.trades), 1)
        self.assertAlmostEqual(new_tracker.current_equity, 100050.0, places=1)
        self.assertAlmostEqual(new_tracker.trades[0].pnl, 50.0, places=1)
        
    def test_reset(self):
        """Test tracker reset functionality."""
        # Add some data
        base_time = datetime.now()
        trade_id = self.tracker.record_trade_entry(
            entry_time=base_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        
        # Reset
        self.tracker.reset()
        
        # Verify reset
        self.assertEqual(len(self.tracker.trades), 0)
        self.assertEqual(len(self.tracker.open_positions), 0)
        self.assertEqual(self.tracker.current_equity, self.tracker.initial_capital)
        self.assertEqual(len(self.tracker.equity_curve), 0)


class TestComparativeAnalyzer(unittest.TestCase):
    """Test cases for ComparativeAnalyzer class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.logger = Mock(spec=RLLogger)
        
        self.analyzer = ComparativeAnalyzer(
            save_dir=self.temp_dir,
            logger=self.logger
        )
        
        # Create test trackers
        self.tracker_a = PerformanceTracker(
            agent_id="agent_a",
            save_dir=self.temp_dir,
            logger=self.logger
        )
        
        self.tracker_b = PerformanceTracker(
            agent_id="agent_b",
            save_dir=self.temp_dir,
            logger=self.logger
        )
        
    def tearDown(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir)
        
    def test_register_strategy(self):
        """Test strategy registration."""
        self.analyzer.register_strategy("strategy_a", self.tracker_a)
        
        self.assertIn("strategy_a", self.analyzer.strategy_trackers)
        self.assertEqual(self.analyzer.strategy_trackers["strategy_a"], self.tracker_a)
        self.logger.log_system_event.assert_called()
        
    def test_add_benchmark_data(self):
        """Test adding benchmark data."""
        benchmark_data = [
            (datetime.now() - timedelta(days=i), 0.001 * i)
            for i in range(10)
        ]
        
        self.analyzer.add_benchmark_data("sp500", benchmark_data)
        
        self.assertIn("sp500", self.analyzer.benchmark_returns)
        self.assertEqual(len(self.analyzer.benchmark_returns["sp500"]), 10)
        
    def test_compare_strategies(self):
        """Test strategy comparison."""
        # Register strategies
        self.analyzer.register_strategy("strategy_a", self.tracker_a)
        self.analyzer.register_strategy("strategy_b", self.tracker_b)
        
        # Add some performance data
        base_time = datetime.now()
        
        # Strategy A - better performance
        for i in range(5):
            trade_id = self.tracker_a.record_trade_entry(
                entry_time=base_time + timedelta(hours=i*2),
                entry_price=1.2000,
                position_size=10000,
                currency_pair="EURUSD"
            )
            self.tracker_a.record_trade_exit(
                trade_id=trade_id,
                exit_time=base_time + timedelta(hours=i*2+1),
                exit_price=1.2020  # Consistent small wins
            )
        
        # Strategy B - worse performance
        for i in range(3):
            trade_id = self.tracker_b.record_trade_entry(
                entry_time=base_time + timedelta(hours=i*2),
                entry_price=1.2000,
                position_size=10000,
                currency_pair="EURUSD"
            )
            self.tracker_b.record_trade_exit(
                trade_id=trade_id,
                exit_time=base_time + timedelta(hours=i*2+1),
                exit_price=1.1990  # Consistent small losses
            )
        
        # Compare strategies
        result = self.analyzer.compare_strategies("strategy_a", "strategy_b")
        
        self.assertIsInstance(result, ComparisonResult)
        self.assertEqual(result.strategy_a_id, "strategy_a")
        self.assertEqual(result.strategy_b_id, "strategy_b")
        self.assertGreater(result.return_difference, 0)  # A should outperform B
        self.assertGreater(result.performance_score, 0.0)  # A should score higher than 0
        
    def test_compare_with_benchmark(self):
        """Test benchmark comparison."""
        # Register strategy
        self.analyzer.register_strategy("strategy_a", self.tracker_a)
        
        # Add benchmark data
        benchmark_data = [
            (datetime.now() - timedelta(days=i), 0.001)  # 0.1% daily return
            for i in range(30)
        ]
        self.analyzer.add_benchmark_data("market", benchmark_data)
        
        # Add strategy performance
        base_time = datetime.now()
        trade_id = self.tracker_a.record_trade_entry(
            entry_time=base_time,
            entry_price=1.2000,
            position_size=10000,
            currency_pair="EURUSD"
        )
        self.tracker_a.record_trade_exit(
            trade_id=trade_id,
            exit_time=base_time + timedelta(hours=1),
            exit_price=1.2100  # Large win
        )
        
        # Compare with benchmark
        result = self.analyzer.compare_with_benchmark("strategy_a", "market")
        
        self.assertIsInstance(result, ComparisonResult)
        self.assertEqual(result.strategy_a_id, "strategy_a")
        self.assertEqual(result.strategy_b_id, "market")
        self.assertEqual(result.comparison_type, "strategy_vs_benchmark")
        
    def test_generate_performance_ranking(self):
        """Test performance ranking generation."""
        # Register multiple strategies
        trackers = {}
        for i in range(3):
            tracker = PerformanceTracker(
                agent_id=f"agent_{i}",
                save_dir=self.temp_dir,
                logger=self.logger
            )
            
            # Add different performance levels
            base_time = datetime.now()
            trade_id = tracker.record_trade_entry(
                entry_time=base_time,
                entry_price=1.2000,
                position_size=10000,
                currency_pair="EURUSD"
            )
            
            # Different exit prices for different performance
            exit_price = 1.2000 + (i + 1) * 0.0020  # Better performance for higher i
            tracker.record_trade_exit(
                trade_id=trade_id,
                exit_time=base_time + timedelta(hours=1),
                exit_price=exit_price
            )
            
            self.analyzer.register_strategy(f"strategy_{i}", tracker)
        
        # Generate ranking
        rankings = self.analyzer.generate_performance_ranking()
        
        self.assertEqual(len(rankings), 3)
        
        # Check ranking order (should be descending by Sharpe ratio)
        for i in range(len(rankings) - 1):
            current_sharpe = rankings[i]["sharpe_ratio"]
            next_sharpe = rankings[i + 1]["sharpe_ratio"]
            self.assertGreaterEqual(current_sharpe, next_sharpe)
        
        # Check rank numbers
        for i, ranking in enumerate(rankings):
            self.assertEqual(ranking["rank"], i + 1)
            
    def test_analyze_correlation(self):
        """Test correlation analysis."""
        # Register strategies with correlated returns
        self.analyzer.register_strategy("strategy_a", self.tracker_a)
        self.analyzer.register_strategy("strategy_b", self.tracker_b)
        
        # Add correlated performance data
        base_time = datetime.now()
        
        for i in range(10):
            # Strategy A
            trade_id_a = self.tracker_a.record_trade_entry(
                entry_time=base_time + timedelta(hours=i*2),
                entry_price=1.2000,
                position_size=10000,
                currency_pair="EURUSD"
            )
            
            # Strategy B with similar but slightly different performance
            trade_id_b = self.tracker_b.record_trade_entry(
                entry_time=base_time + timedelta(hours=i*2),
                entry_price=1.2000,
                position_size=10000,
                currency_pair="EURUSD"
            )
            
            # Similar exit prices (high correlation)
            exit_price_a = 1.2000 + i * 0.0010
            exit_price_b = 1.2000 + i * 0.0012  # Slightly different
            
            self.tracker_a.record_trade_exit(
                trade_id=trade_id_a,
                exit_time=base_time + timedelta(hours=i*2+1),
                exit_price=exit_price_a
            )
            
            self.tracker_b.record_trade_exit(
                trade_id=trade_id_b,
                exit_time=base_time + timedelta(hours=i*2+1),
                exit_price=exit_price_b
            )
        
        # Analyze correlation
        analysis = self.analyzer.analyze_correlation()
        
        self.assertIn("correlation_matrix", analysis)
        self.assertIn("highest_correlation", analysis)
        self.assertIn("average_correlation", analysis)
        
        # Should have high correlation
        correlation = analysis["correlation_matrix"]["strategy_a"]["strategy_b"]
        self.assertGreater(correlation, 0.5)
        
    def test_save_analysis_results(self):
        """Test saving analysis results."""
        # Add some comparison data
        self.analyzer.register_strategy("strategy_a", self.tracker_a)
        self.analyzer.register_strategy("strategy_b", self.tracker_b)
        
        # Perform comparison to generate results
        result = self.analyzer.compare_strategies("strategy_a", "strategy_b")
        
        # Save results
        filename = self.analyzer.save_analysis_results()
        
        # Verify file exists and contains data
        self.assertTrue(Path(filename).exists())
        
        with open(filename, 'r') as f:
            data = json.load(f)
        
        self.assertIn("comparison_history", data)
        self.assertIn("registered_strategies", data)
        self.assertEqual(len(data["comparison_history"]), 1)


class TestPerformanceMetrics(unittest.TestCase):
    """Test cases for PerformanceMetrics dataclass."""
    
    def test_metrics_creation(self):
        """Test metrics creation and conversion."""
        timestamp = datetime.now()
        
        metrics = PerformanceMetrics(
            total_return=0.15,
            annualized_return=0.12,
            cumulative_return=0.15,
            volatility=0.20,
            sharpe_ratio=0.60,
            sortino_ratio=0.75,
            calmar_ratio=0.50,
            max_drawdown=0.08,
            current_drawdown=0.02,
            win_rate=0.65,
            profit_factor=1.8,
            avg_win=150.0,
            avg_loss=85.0,
            num_trades=50,
            avg_trade_duration=2.5,
            information_ratio=0.55,
            treynor_ratio=0.08,
            jensen_alpha=0.03,
            beta=1.2,
            timestamp=timestamp
        )
        
        # Test to_dict conversion
        metrics_dict = metrics.to_dict()
        
        self.assertEqual(metrics_dict["total_return"], 0.15)
        self.assertEqual(metrics_dict["sharpe_ratio"], 0.60)
        self.assertEqual(metrics_dict["num_trades"], 50)
        self.assertEqual(metrics_dict["timestamp"], timestamp)


if __name__ == '__main__':
    unittest.main()
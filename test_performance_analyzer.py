"""Unit tests for PerformanceAnalyzer"""

import pytest
from datetime import datetime, timezone, timedelta
from src.backtesting.performance_analyzer import PerformanceAnalyzer, PerformanceMetrics, TradeAnalysis
from src.backtesting.backtest_engine import BacktestResult


class TestPerformanceAnalyzer:
    """Test PerformanceAnalyzer functionality"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.analyzer = PerformanceAnalyzer(initial_balance=10000.0)
        
        # Create sample backtest result with known data
        self.sample_trades = [
            {
                'position_id': 'pos_1',
                'symbol': 'EURUSD',
                'direction': 'LONG',
                'quantity': 1.0,
                'entry_price': 1.1000,
                'exit_price': 1.1050,
                'entry_time': datetime(2023, 1, 1, 10, 0, tzinfo=timezone.utc),
                'exit_time': datetime(2023, 1, 1, 14, 0, tzinfo=timezone.utc),
                'pnl': 500.0,
                'commission': 10.0,
                'reason': 'Take Profit',
                'duration_hours': 4.0
            },
            {
                'position_id': 'pos_2',
                'symbol': 'GBPUSD',
                'direction': 'SHORT',
                'quantity': 1.0,
                'entry_price': 1.2500,
                'exit_price': 1.2450,
                'entry_time': datetime(2023, 1, 2, 9, 0, tzinfo=timezone.utc),
                'exit_time': datetime(2023, 1, 2, 15, 0, tzinfo=timezone.utc),
                'pnl': 500.0,
                'commission': 10.0,
                'reason': 'Take Profit',
                'duration_hours': 6.0
            },
            {
                'position_id': 'pos_3',
                'symbol': 'USDJPY',
                'direction': 'LONG',
                'quantity': 1.0,
                'entry_price': 110.00,
                'exit_price': 109.50,
                'entry_time': datetime(2023, 1, 3, 8, 0, tzinfo=timezone.utc),
                'exit_time': datetime(2023, 1, 3, 12, 0, tzinfo=timezone.utc),
                'pnl': -500.0,
                'commission': 10.0,
                'reason': 'Stop Loss',
                'duration_hours': 4.0
            }
        ]
        
        # Create equity curve
        self.sample_equity_curve = [
            (datetime(2023, 1, 1, 9, 0, tzinfo=timezone.utc), 10000.0),
            (datetime(2023, 1, 1, 14, 0, tzinfo=timezone.utc), 10500.0),
            (datetime(2023, 1, 2, 15, 0, tzinfo=timezone.utc), 11000.0),
            (datetime(2023, 1, 3, 12, 0, tzinfo=timezone.utc), 10500.0)
        ]
        
        # Create daily returns
        self.sample_daily_returns = [0.05, 0.05, -0.045]  # 5%, 5%, -4.5%
        
        self.sample_backtest_result = BacktestResult(
            total_trades=3,
            winning_trades=2,
            losing_trades=1,
            total_pnl=500.0,
            max_drawdown=0.045,
            max_drawdown_duration=1,
            sharpe_ratio=1.5,
            win_rate=0.667,
            avg_win=500.0,
            avg_loss=-500.0,
            profit_factor=2.0,
            trades=self.sample_trades,
            equity_curve=self.sample_equity_curve,
            daily_returns=self.sample_daily_returns
        )
    
    def test_analyze_performance_basic_metrics(self):
        """Test basic performance metrics calculation"""
        metrics = self.analyzer.analyze_performance(self.sample_backtest_result)
        
        # Test basic metrics
        assert metrics.total_trades == 3
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 1
        assert metrics.win_rate == 0.667
        assert metrics.avg_win == 500.0
        assert metrics.avg_loss == -500.0
        assert metrics.profit_factor == 2.0
        
        # Test calculated metrics
        assert metrics.total_return == 0.05  # 500/10000
        assert metrics.max_drawdown == 0.045
        assert abs(metrics.sharpe_ratio - 1.5) < 0.1  # Allow some calculation variance
    
    def test_analyze_performance_risk_metrics(self):
        """Test risk-adjusted performance metrics"""
        metrics = self.analyzer.analyze_performance(
            self.sample_backtest_result,
            risk_free_rate=0.02
        )
        
        # Test risk metrics
        assert metrics.sortino_ratio > 0
        assert metrics.calmar_ratio > 0
        assert metrics.volatility > 0
        
        # Test VaR calculations
        assert metrics.var_95 != 0.0
        assert metrics.var_99 != 0.0
        assert metrics.var_99 <= metrics.var_95  # 99% VaR should be worse than 95%
    
    def test_analyze_performance_with_benchmark(self):
        """Test performance analysis with benchmark comparison"""
        benchmark_returns = [0.02, 0.03, -0.01]  # 2%, 3%, -1%
        
        metrics = self.analyzer.analyze_performance(
            self.sample_backtest_result,
            benchmark_returns=benchmark_returns,
            risk_free_rate=0.02
        )
        
        # Test benchmark comparison metrics
        assert metrics.beta != 0.0
        assert metrics.alpha != 0.0
        assert metrics.information_ratio != 0.0
    
    def test_analyze_performance_empty_trades(self):
        """Test performance analysis with no trades"""
        empty_result = BacktestResult()
        metrics = self.analyzer.analyze_performance(empty_result)
        
        # All metrics should be zero or default values
        assert metrics.total_trades == 0
        assert metrics.total_return == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.max_drawdown == 0.0
    
    def test_analyze_trades_detailed(self):
        """Test detailed trade-by-trade analysis"""
        trade_analyses = self.analyzer.analyze_trades(self.sample_backtest_result)
        
        assert len(trade_analyses) == 3
        
        # Test first trade analysis
        first_trade = trade_analyses[0]
        assert first_trade.trade_id == "trade_0"
        assert first_trade.symbol == "EURUSD"
        assert first_trade.direction == "LONG"
        assert first_trade.pnl == 500.0
        assert first_trade.duration_hours == 4.0
        assert first_trade.pnl_percentage > 0  # Should be positive for winning trade
    
    def test_analyze_trades_with_market_data(self):
        """Test trade analysis with market data for performance attribution"""
        # Mock market data
        market_data = {
            'EURUSD': [
                {'timestamp': datetime(2023, 1, 1, 10, 0, tzinfo=timezone.utc), 'close': 1.1000},
                {'timestamp': datetime(2023, 1, 1, 14, 0, tzinfo=timezone.utc), 'close': 1.1030}
            ]
        }
        
        trade_analyses = self.analyzer.analyze_trades(
            self.sample_backtest_result,
            market_data=market_data
        )
        
        # Test performance attribution
        first_trade = trade_analyses[0]
        assert first_trade.market_return != 0.0
        assert first_trade.alpha_return != 0.0
        assert first_trade.timing_score != 0.0
    
    def test_generate_performance_report(self):
        """Test performance report generation"""
        metrics = self.analyzer.analyze_performance(self.sample_backtest_result)
        trade_analyses = self.analyzer.analyze_trades(self.sample_backtest_result)
        
        report = self.analyzer.generate_performance_report(metrics, trade_analyses)
        
        # Test report structure
        assert 'summary' in report
        assert 'risk_metrics' in report
        assert 'trade_analysis' in report
        assert 'advanced_metrics' in report
        assert 'top_trades' in report
        
        # Test summary section
        summary = report['summary']
        assert 'total_return' in summary
        assert 'sharpe_ratio' in summary
        assert 'win_rate' in summary
        
        # Test top trades section
        top_trades = report['top_trades']
        assert 'best_trades' in top_trades
        assert 'worst_trades' in top_trades
        assert len(top_trades['best_trades']) <= 5
        assert len(top_trades['worst_trades']) <= 5
    
    def test_sharpe_ratio_calculation(self):
        """Test Sharpe ratio calculation with known values"""
        # Test with known daily returns
        daily_returns = [0.01, 0.02, -0.01, 0.015, -0.005]  # 1%, 2%, -1%, 1.5%, -0.5%
        risk_free_rate = 0.02  # 2% annual
        
        sharpe = self.analyzer._calculate_sharpe_ratio(daily_returns, risk_free_rate)
        
        # Sharpe should be positive for these returns
        assert sharpe > 0
        
        # Test with empty returns
        empty_sharpe = self.analyzer._calculate_sharpe_ratio([], risk_free_rate)
        assert empty_sharpe == 0.0
        
        # Test with single return
        single_sharpe = self.analyzer._calculate_sharpe_ratio([0.01], risk_free_rate)
        assert single_sharpe == 0.0
    
    def test_sortino_ratio_calculation(self):
        """Test Sortino ratio calculation"""
        daily_returns = [0.01, 0.02, -0.01, 0.015, -0.005]
        risk_free_rate = 0.02
        
        sortino = self.analyzer._calculate_sortino_ratio(daily_returns, risk_free_rate)
        
        # Sortino should be positive and typically higher than Sharpe
        assert sortino > 0
        
        # Test with no negative returns
        positive_returns = [0.01, 0.02, 0.015, 0.01]
        sortino_positive = self.analyzer._calculate_sortino_ratio(positive_returns, risk_free_rate)
        assert sortino_positive > 0
    
    def test_calmar_ratio_calculation(self):
        """Test Calmar ratio calculation"""
        annualized_return = 0.15  # 15%
        max_drawdown = 0.05  # 5%
        
        calmar = self.analyzer._calculate_calmar_ratio(annualized_return, max_drawdown)
        assert calmar == 3.0  # 15% / 5%
        
        # Test with zero drawdown
        calmar_zero_dd = self.analyzer._calculate_calmar_ratio(annualized_return, 0.0)
        assert calmar_zero_dd == float('inf')
        
        # Test with negative return and zero drawdown
        calmar_neg = self.analyzer._calculate_calmar_ratio(-0.05, 0.0)
        assert calmar_neg == 0.0
    
    def test_beta_alpha_calculation(self):
        """Test beta and alpha calculation vs benchmark"""
        strategy_returns = [0.02, 0.03, -0.01, 0.025]
        benchmark_returns = [0.015, 0.02, -0.005, 0.02]
        risk_free_rate = 0.02
        
        beta, alpha = self.analyzer._calculate_beta_alpha(
            strategy_returns, benchmark_returns, risk_free_rate
        )
        
        # Beta should be reasonable (typically between 0.5 and 2.0 for most strategies)
        assert -5.0 < beta < 5.0
        
        # Alpha can be positive or negative
        assert -1.0 < alpha < 1.0
        
        # Test with mismatched lengths
        beta_mismatch, alpha_mismatch = self.analyzer._calculate_beta_alpha(
            [0.01, 0.02], [0.01], risk_free_rate
        )
        assert beta_mismatch == 0.0
        assert alpha_mismatch == 0.0
    
    def test_information_ratio_calculation(self):
        """Test information ratio calculation"""
        strategy_returns = [0.02, 0.03, -0.01, 0.025]
        benchmark_returns = [0.015, 0.02, -0.005, 0.02]
        
        info_ratio = self.analyzer._calculate_information_ratio(
            strategy_returns, benchmark_returns
        )
        
        # Information ratio should be finite
        assert abs(info_ratio) < 10.0
        
        # Test with identical returns (should be 0)
        identical_returns = [0.01, 0.02, 0.015]
        info_ratio_zero = self.analyzer._calculate_information_ratio(
            identical_returns, identical_returns
        )
        assert info_ratio_zero == 0.0
    
    def test_monthly_returns_calculation(self):
        """Test monthly returns calculation from equity curve"""
        # Create equity curve spanning multiple months
        equity_curve = [
            (datetime(2023, 1, 1), 10000.0),
            (datetime(2023, 1, 31), 10500.0),
            (datetime(2023, 2, 28), 11000.0),
            (datetime(2023, 3, 31), 10800.0)
        ]
        
        monthly_returns = self.analyzer._calculate_monthly_returns(equity_curve)
        
        # Should have returns for Feb and Mar (not Jan since no previous month)
        assert len(monthly_returns) == 2
        assert '2023-02' in monthly_returns
        assert '2023-03' in monthly_returns
        
        # Check calculation: Feb return = (11000 - 10500) / 10500 = 0.0476
        assert abs(monthly_returns['2023-02'] - 0.0476) < 0.001
        
        # Check calculation: Mar return = (10800 - 11000) / 11000 = -0.0182
        assert abs(monthly_returns['2023-03'] - (-0.0182)) < 0.001
    
    def test_pnl_percentage_calculation(self):
        """Test PnL percentage calculation"""
        trade = {
            'entry_price': 1.1000,
            'quantity': 1.0,
            'pnl': 500.0
        }
        
        pnl_pct = self.analyzer._calculate_pnl_percentage(trade)
        
        # PnL% = 500 / (1.1000 * 1.0) = 500 / 1.1 = 454.55%
        expected_pnl_pct = 500.0 / 1.1000
        assert abs(pnl_pct - expected_pnl_pct) < 0.01
        
        # Test with zero entry value
        zero_trade = {'entry_price': 0.0, 'quantity': 1.0, 'pnl': 100.0}
        zero_pnl_pct = self.analyzer._calculate_pnl_percentage(zero_trade)
        assert zero_pnl_pct == 0.0
    
    def test_timing_score_calculation(self):
        """Test timing score calculation"""
        trade = {
            'entry_price': 1.1000,
            'quantity': 1.0,
            'pnl': 500.0,
            'duration_hours': 4.0
        }
        
        timing_score = self.analyzer._calculate_timing_score(trade)
        
        # Should be PnL percentage per hour
        pnl_pct = 500.0 / 1.1000  # PnL percentage
        expected_score = pnl_pct / 4.0  # Per hour
        assert abs(timing_score - expected_score) < 0.01
        
        # Test with zero duration
        zero_duration_trade = {
            'entry_price': 1.1000,
            'quantity': 1.0,
            'pnl': 500.0,
            'duration_hours': 0.0
        }
        zero_score = self.analyzer._calculate_timing_score(zero_duration_trade)
        assert zero_score == 0.0
    
    def test_performance_metrics_dataclass(self):
        """Test PerformanceMetrics dataclass initialization and defaults"""
        metrics = PerformanceMetrics()
        
        # Test default values
        assert metrics.total_return == 0.0
        assert metrics.sharpe_ratio == 0.0
        assert metrics.total_trades == 0
        assert metrics.monthly_returns == {}
        
        # Test with custom values
        custom_metrics = PerformanceMetrics(
            total_return=0.15,
            sharpe_ratio=1.5,
            total_trades=10
        )
        assert custom_metrics.total_return == 0.15
        assert custom_metrics.sharpe_ratio == 1.5
        assert custom_metrics.total_trades == 10
    
    def test_trade_analysis_dataclass(self):
        """Test TradeAnalysis dataclass initialization"""
        trade_analysis = TradeAnalysis(
            trade_id="test_1",
            symbol="EURUSD",
            direction="LONG",
            entry_time=datetime(2023, 1, 1),
            exit_time=datetime(2023, 1, 2),
            duration_hours=24.0,
            entry_price=1.1000,
            exit_price=1.1050,
            quantity=1.0,
            pnl=500.0,
            pnl_percentage=0.045,
            commission=10.0,
            net_pnl=490.0,
            reason="Take Profit"
        )
        
        assert trade_analysis.trade_id == "test_1"
        assert trade_analysis.symbol == "EURUSD"
        assert trade_analysis.pnl == 500.0
        assert trade_analysis.market_return == 0.0  # Default value
        assert trade_analysis.alpha_return == 0.0   # Default value
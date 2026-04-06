"""Backtesting and paper trading framework for the AI Forex Trading Bot"""

from .backtest_engine import BacktestEngine, BacktestResult
from .performance_analyzer import PerformanceAnalyzer, PerformanceMetrics, TradeAnalysis

__all__ = [
    'BacktestEngine',
    'BacktestResult',
    'PerformanceAnalyzer',
    'PerformanceMetrics',
    'TradeAnalysis'
]
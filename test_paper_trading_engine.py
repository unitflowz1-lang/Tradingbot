"""Unit tests for paper trading engine"""

import asyncio
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, List

from src.backtesting.paper_trading_engine import (
    PaperTradingEngine, PaperTradingConfig, PaperTradingState
)
from src.backtesting.backtest_engine import BacktestResult
from src.models import (
    MarketData, TradingSignal, Direction, ExecutionResult, Position
)
from src.exceptions import PaperTradingError


class MockBrokerInterface:
    """Mock broker interface for testing"""
    
    def __init__(self):
        self.connected = False
        self.market_data = {}
    
    async def connect(self) -> bool:
        self.connected = True
        return True
    
    async def disconnect(self) -> bool:
        self.connected = False
        return True
    
    async def get_market_data(self, symbol: str) -> MarketData:
        if symbol in self.market_data:
            return self.market_data[symbol]
        
        # Return default market data
        return MarketData(
            symbol=symbol,
            timestamp=datetime.now(timezone.utc),
            open=1.1000,
            high=1.1020,
            low=1.0980,
            close=1.1010,
            volume=1000,
            bid=1.1008,
            ask=1.1012,
            spread=0.0004
        )
    
    def set_market_data(self, symbol: str, market_data: MarketData):
        """Set market data for testing"""
        self.market_data[symbol] = market_data


class MockDataCollector:
    """Mock data collector for testing"""
    
    def __init__(self):
        self.market_data = {}
    
    async def collect_data(self, symbols: List[str], timeframe: str = "1m") -> Dict[str, MarketData]:
        result = {}
        for symbol in symbols:
            if symbol in self.market_data:
                result[symbol] = self.market_data[symbol]
            else:
                # Return default market data
                result[symbol] = MarketData(
                    symbol=symbol,
                    timestamp=datetime.now(timezone.utc),
                    open=1.1000,
                    high=1.1020,
                    low=1.0980,
                    close=1.1010,
                    volume=1000,
                    bid=1.1008,
                    ask=1.1012,
                    spread=0.0004
                )
        return result
    
    async def validate_data(self, data: Dict[str, MarketData]) -> bool:
        return True
    
    def set_market_data(self, symbol: str, market_data: MarketData):
        """Set market data for testing"""
        self.market_data[symbol] = market_data


@pytest.fixture
def mock_broker():
    """Create mock broker interface"""
    return MockBrokerInterface()


@pytest.fixture
def mock_data_collector():
    """Create mock data collector"""
    return MockDataCollector()


@pytest.fixture
def paper_trading_config():
    """Create paper trading configuration"""
    return PaperTradingConfig(
        initial_balance=10000.0,
        leverage=1.0,
        spread_multiplier=1.0,
        slippage_pips=0.5,
        commission_per_lot=0.0,
        max_positions=5,
        data_update_interval=0.1,  # Fast for testing
        performance_update_interval=0.2,  # Fast for testing
        enable_real_time_logging=False,  # Disable for testing
        save_trade_history=True
    )


@pytest.fixture
def paper_trading_engine(mock_broker, mock_data_collector, paper_trading_config):
    """Create paper trading engine"""
    return PaperTradingEngine(
        broker=mock_broker,
        data_collector=mock_data_collector,
        config=paper_trading_config
    )


@pytest.fixture
def sample_trading_signal():
    """Create sample trading signal"""
    return TradingSignal(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry_price=1.1010,
        stop_loss=1.0950,
        take_profit=1.1100,
        position_size=0.02,  # 2% risk
        confidence=0.8,
        reasoning="Strong bullish sentiment and technical breakout",
        timestamp=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_market_data():
    """Create sample market data"""
    return MarketData(
        symbol="EUR/USD",
        timestamp=datetime.now(timezone.utc),
        open=1.1000,
        high=1.1020,
        low=1.0980,
        close=1.1010,
        volume=1000,
        bid=1.1008,
        ask=1.1012,
        spread=0.0004
    )


class TestPaperTradingEngine:
    """Test cases for PaperTradingEngine"""
    
    @pytest.mark.asyncio
    async def test_start_session_success(self, paper_trading_engine):
        """Test successful session start"""
        symbols = ["EUR/USD", "GBP/USD"]
        
        session_id = await paper_trading_engine.start_session(symbols)
        
        assert session_id is not None
        assert session_id.startswith("paper_")
        assert paper_trading_engine.state is not None
        assert paper_trading_engine.state.is_active
        assert paper_trading_engine.subscribed_symbols == symbols
        assert paper_trading_engine.state.current_balance == 10000.0
        
        # Clean up
        await paper_trading_engine.stop_session()
    
    @pytest.mark.asyncio
    async def test_execute_signal_success(
        self, 
        paper_trading_engine, 
        sample_trading_signal, 
        sample_market_data
    ):
        """Test successful signal execution"""
        # Set up market data
        paper_trading_engine.data_collector.set_market_data(
            "EUR/USD", sample_market_data
        )
        
        # Start session
        await paper_trading_engine.start_session(["EUR/USD"])
        
        # Execute signal
        result = await paper_trading_engine.execute_signal(sample_trading_signal)
        
        assert result.success
        assert result.executed_price is not None
        assert result.executed_quantity is not None
        assert len(paper_trading_engine.state.positions) == 1
        assert paper_trading_engine.state.total_trades == 1
        
        # Clean up
        await paper_trading_engine.stop_session()
    
    @pytest.mark.asyncio
    async def test_get_current_performance(
        self, 
        paper_trading_engine, 
        sample_trading_signal, 
        sample_market_data
    ):
        """Test getting current performance metrics"""
        # Set up market data
        paper_trading_engine.data_collector.set_market_data(
            "EUR/USD", sample_market_data
        )
        
        # Start session
        await paper_trading_engine.start_session(["EUR/USD"])
        
        # Execute a signal
        result = await paper_trading_engine.execute_signal(sample_trading_signal)
        assert result.success
        
        # Get performance
        performance = await paper_trading_engine.get_current_performance()
        
        assert performance is not None
        assert hasattr(performance, 'total_trades')
        assert hasattr(performance, 'total_return')
        
        # Clean up
        await paper_trading_engine.stop_session()
    
    @pytest.mark.asyncio
    async def test_compare_to_backtest(
        self, 
        paper_trading_engine, 
        sample_trading_signal, 
        sample_market_data
    ):
        """Test comparison to backtest results"""
        # Create mock backtest result
        backtest_result = BacktestResult(
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            total_pnl=500.0,
            max_drawdown=0.05,
            max_drawdown_duration=5,
            sharpe_ratio=1.2,
            win_rate=0.6,
            avg_win=100.0,
            avg_loss=-50.0,
            profit_factor=2.0,
            trades=[],
            equity_curve=[],
            daily_returns=[]
        )
        
        # Set up market data
        paper_trading_engine.data_collector.set_market_data(
            "EUR/USD", sample_market_data
        )
        
        # Start session
        await paper_trading_engine.start_session(["EUR/USD"])
        
        # Execute a signal
        await paper_trading_engine.execute_signal(sample_trading_signal)
        
        # Compare to backtest
        comparison = await paper_trading_engine.compare_to_backtest(backtest_result)
        
        assert comparison is not None
        assert 'paper_trading' in comparison
        assert 'backtest' in comparison
        assert 'differences' in comparison
        assert 'analysis' in comparison
        
        # Clean up
        await paper_trading_engine.stop_session()
    
    @pytest.mark.asyncio
    async def test_data_quality_validation(
        self, 
        paper_trading_engine, 
        sample_market_data
    ):
        """Test market data quality validation"""
        # Test with good data
        good_data = {"EUR/USD": sample_market_data}
        is_valid = await paper_trading_engine._validate_market_data_quality(good_data)
        assert is_valid
        
        # Test with stale data
        stale_data = MarketData(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc) - timedelta(minutes=10),  # 10 minutes old
            open=1.1000,
            high=1.1020,
            low=1.0980,
            close=1.1010,
            volume=1000,
            bid=1.1008,
            ask=1.1012,
            spread=0.0004
        )
        bad_data = {"EUR/USD": stale_data}
        is_valid = await paper_trading_engine._validate_market_data_quality(bad_data)
        assert not is_valid
        
        # Test with empty data
        is_valid = await paper_trading_engine._validate_market_data_quality({})
        assert not is_valid

    @pytest.mark.asyncio
    async def test_detailed_session_metrics(
        self, 
        paper_trading_engine, 
        sample_trading_signal, 
        sample_market_data
    ):
        """Test detailed session metrics"""
        # Set up market data
        paper_trading_engine.data_collector.set_market_data(
            "EUR/USD", sample_market_data
        )
        
        # Start session
        await paper_trading_engine.start_session(["EUR/USD"])
        
        # Execute a signal
        await paper_trading_engine.execute_signal(sample_trading_signal)
        
        # Get detailed metrics
        metrics = await paper_trading_engine.get_detailed_session_metrics()
        
        assert 'session_info' in metrics
        assert 'account_metrics' in metrics
        assert 'position_metrics' in metrics
        assert 'trading_metrics' in metrics
        assert 'data_quality' in metrics
        
        # Check specific values
        assert metrics['session_info']['symbols_traded'] == ["EUR/USD"]
        assert metrics['account_metrics']['initial_balance'] == 10000.0
        assert metrics['position_metrics']['open_positions'] == 1
        assert metrics['trading_metrics']['total_trades'] == 1
        
        # Clean up
        await paper_trading_engine.stop_session()

    @pytest.mark.asyncio
    async def test_export_session_data(
        self, 
        paper_trading_engine, 
        sample_trading_signal, 
        sample_market_data,
        tmp_path
    ):
        """Test session data export"""
        # Set up market data
        paper_trading_engine.data_collector.set_market_data(
            "EUR/USD", sample_market_data
        )
        
        # Start session
        await paper_trading_engine.start_session(["EUR/USD"])
        
        # Execute a signal
        await paper_trading_engine.execute_signal(sample_trading_signal)
        
        # Export data
        export_file = tmp_path / "session_export.json"
        success = await paper_trading_engine.export_session_data(str(export_file))
        
        assert success
        assert export_file.exists()
        
        # Verify exported data
        import json
        with open(export_file, 'r') as f:
            exported_data = json.load(f)
        
        assert 'session_info' in exported_data
        assert 'trade_history' in exported_data
        assert 'equity_curve' in exported_data
        assert 'current_positions' in exported_data
        
        # Clean up
        await paper_trading_engine.stop_session()


if __name__ == "__main__":
    pytest.main([__file__])
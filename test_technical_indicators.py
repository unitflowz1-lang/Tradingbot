"""Unit tests for technical indicators"""

import pytest
import numpy as np
from datetime import datetime, timedelta, timezone
from src.analysis.technical_indicators import TechnicalIndicators, IndicatorCalculator
from src.models import MarketData
from src.exceptions import DataValidationError


class TestTechnicalIndicators:
    """Test TechnicalIndicators dataclass"""
    
    def test_technical_indicators_creation(self):
        """Test creating TechnicalIndicators object"""
        indicators = TechnicalIndicators(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            sma_20=1.1050,
            sma_50=1.1020,
            rsi=65.5,
            macd=0.0010,
            macd_signal=0.0005
        )
        
        assert indicators.symbol == "EUR/USD"
        assert indicators.sma_20 == 1.1050
        assert indicators.sma_50 == 1.1020
        assert indicators.rsi == 65.5
        assert indicators.macd == 0.0010
        assert indicators.macd_signal == 0.0005
    
    def test_to_dict_method(self):
        """Test converting indicators to dictionary"""
        indicators = TechnicalIndicators(
            symbol="EUR/USD",
            timestamp=datetime.now(timezone.utc),
            sma_20=1.1050,
            sma_50=1.1020,
            rsi=65.5,
            macd=0.0010,
            macd_signal=0.0005
        )
        
        result = indicators.to_dict()
        
        assert "sma_20" in result
        assert "sma_50" in result
        assert "rsi" in result
        assert "macd" in result
        assert "macd_signal" in result
        assert "symbol" not in result  # Should be excluded
        assert "timestamp" not in result  # Should be excluded


class TestIndicatorCalculator:
    """Test technical indicator calculations"""
    
    def setup_method(self):
        """Setup test fixtures"""
        self.calculator = IndicatorCalculator()
        self.symbol = "EUR/USD"
        
        # Create sample market data
        self.sample_data = [
            MarketData(
                symbol=self.symbol,
                timestamp=datetime.now(timezone.utc) - timedelta(hours=1),  # Past timestamp
                open=1.1000,
                high=1.1050,
                low=1.0980,
                close=1.1020,
                volume=1000,
                bid=1.1018,
                ask=1.1022,
                spread=0.0004
            ),
            MarketData(
                symbol=self.symbol,
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=30),  # Past timestamp
                open=1.1020,
                high=1.1070,
                low=1.1000,
                close=1.1040,
                volume=1200,
                bid=1.1038,
                ask=1.1042,
                spread=0.0004
            )
        ]
    
    def test_add_market_data(self):
        """Test adding market data"""
        # Add data
        self.calculator.add_market_data(self.sample_data[0])
        
        # Check if data was added to cache
        data_key = f"{self.symbol}_1h"  # Default timeframe
        assert data_key in self.calculator.data_cache
        assert len(self.calculator.data_cache[data_key]) == 1
        assert self.calculator.data_cache[data_key][0].close == 1.1020
    
    def test_calculate_indicators_success(self):
        """Test successful indicator calculation"""
        # Add enough data for calculations
        base_time = datetime.now(timezone.utc) - timedelta(hours=100)  # Past timestamp
        
        for i in range(50):  # Add 50 data points
            data = MarketData(
                symbol=self.symbol,
                timestamp=base_time + timedelta(hours=i),
                open=1.1000 + i * 0.0001,
                high=1.1050 + i * 0.0001,
                low=1.0980 + i * 0.0001,
                close=1.1020 + i * 0.0001,
                volume=1000 + i * 10,
                bid=1.1018 + i * 0.0001,
                ask=1.1022 + i * 0.0001,
                spread=0.0004
            )
            self.calculator.add_market_data(data)
        
        # Calculate indicators
        indicators = self.calculator.calculate_indicators(self.symbol)
        
        assert isinstance(indicators, TechnicalIndicators)
        assert indicators.symbol == self.symbol
        assert indicators.sma_20 is not None
        assert indicators.ema_12 is not None
        assert indicators.rsi is not None
        assert indicators.macd is not None
        assert indicators.bollinger_upper is not None
        assert indicators.atr is not None
    
    def test_calculate_indicators_insufficient_data(self):
        """Test indicator calculation with insufficient data"""
        # Add only 5 data points (not enough for most indicators)
        base_time = datetime.now(timezone.utc) - timedelta(hours=5)  # Use past time
        
        for i in range(5):
            data = MarketData(
                symbol=self.symbol,
                timestamp=base_time + timedelta(hours=i),
                open=1.1000 + i * 0.0001,
                high=1.1050 + i * 0.0001,
                low=1.0980 + i * 0.0001,
                close=1.1020 + i * 0.0001,
                volume=1000 + i * 10,
                bid=1.1018 + i * 0.0001,
                ask=1.1022 + i * 0.0001,
                spread=0.0004
            )
            self.calculator.add_market_data(data)
        
        # Should raise error for insufficient data
        with pytest.raises(DataValidationError, match="Need at least 20 periods"):
            self.calculator.calculate_indicators(self.symbol)
    
    def test_calculate_sma(self):
        """Test SMA calculation"""
        # Create test data
        prices = np.array([1.1000, 1.1010, 1.1020, 1.1030, 1.1040])
        
        # Calculate SMA with period 3
        sma = self.calculator._calculate_sma(prices, 3)
        
        # Expected: (1.1020 + 1.1030 + 1.1040) / 3 = 1.1030
        expected_sma = (1.1020 + 1.1030 + 1.1040) / 3
        assert abs(sma - expected_sma) < 0.0001
    
    def test_calculate_ema(self):
        """Test EMA calculation"""
        # Create test data
        prices = np.array([1.1000, 1.1010, 1.1020, 1.1030, 1.1040])
        
        # Calculate EMA with period 3
        ema = self.calculator._calculate_ema(prices, 3)
        
        # EMA should be a weighted average, so it should be close to recent prices
        assert ema > 1.1000
        assert ema <= 1.1040
        assert isinstance(ema, float)
    
    def test_calculate_rsi(self):
        """Test RSI calculation"""
        # Create test data with clear trend
        prices = np.array([1.1000, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050, 1.1060])
        
        # Calculate RSI
        rsi = self.calculator._calculate_rsi(prices, period=5)
        
        # RSI should be between 0 and 100
        assert 0 <= rsi <= 100
        assert isinstance(rsi, float)
    
    def test_calculate_macd(self):
        """Test MACD calculation"""
        # Create test data with enough periods for MACD (needs at least 26)
        prices = np.array([
            1.1000, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050, 1.1060, 1.1070, 1.1080, 1.1090,
            1.1100, 1.1110, 1.1120, 1.1130, 1.1140, 1.1150, 1.1160, 1.1170, 1.1180, 1.1190,
            1.1200, 1.1210, 1.1220, 1.1230, 1.1240, 1.1250, 1.1260, 1.1270, 1.1280, 1.1290
        ])
        
        # Calculate MACD
        macd_result = self.calculator._calculate_macd(prices)
        
        # Check structure
        assert "macd" in macd_result
        assert "signal" in macd_result
        assert "histogram" in macd_result
        
        # Check values are floats
        assert isinstance(macd_result["macd"], float)
        assert isinstance(macd_result["signal"], float)
        assert isinstance(macd_result["histogram"], float)
    
    def test_calculate_bollinger_bands(self):
        """Test Bollinger Bands calculation"""
        # Create test data with enough periods for Bollinger Bands (needs at least 20)
        prices = np.array([
            1.1000, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050, 1.1060, 1.1070, 1.1080, 1.1090,
            1.1100, 1.1110, 1.1120, 1.1130, 1.1140, 1.1150, 1.1160, 1.1170, 1.1180, 1.1190,
            1.1200, 1.1210, 1.1220, 1.1230, 1.1240, 1.1250, 1.1260, 1.1270, 1.1280, 1.1290
        ])
        
        # Calculate Bollinger Bands
        bb_result = self.calculator._calculate_bollinger_bands(prices)
        
        # Check structure
        assert "upper" in bb_result
        assert "middle" in bb_result
        assert "lower" in bb_result
        
        # Check values
        assert bb_result["upper"] > bb_result["middle"]
        assert bb_result["middle"] > bb_result["lower"]
        assert isinstance(bb_result["upper"], float)
        assert isinstance(bb_result["middle"], float)
        assert isinstance(bb_result["lower"], float)
    
    def test_calculate_atr(self):
        """Test ATR calculation"""
        # Create test data with enough periods for ATR (needs at least 15)
        highs = np.array([
            1.1050, 1.1060, 1.1070, 1.1080, 1.1090, 1.1100, 1.1110, 1.1120, 1.1130, 1.1140,
            1.1150, 1.1160, 1.1170, 1.1180, 1.1190, 1.1200, 1.1210, 1.1220, 1.1230, 1.1240
        ])
        lows = np.array([
            1.0980, 1.0990, 1.1000, 1.1010, 1.1020, 1.1030, 1.1040, 1.1050, 1.1060, 1.1070,
            1.1080, 1.1090, 1.1100, 1.1110, 1.1120, 1.1130, 1.1140, 1.1150, 1.1160, 1.1170
        ])
        closes = np.array([
            1.1020, 1.1030, 1.1040, 1.1050, 1.1060, 1.1070, 1.1080, 1.1090, 1.1100, 1.1110,
            1.1120, 1.1130, 1.1140, 1.1150, 1.1160, 1.1170, 1.1180, 1.1190, 1.1200, 1.1210
        ])
        
        # Calculate ATR
        atr = self.calculator._calculate_atr(highs, lows, closes)
        
        # ATR should be positive
        assert atr > 0
        assert isinstance(atr, float)
    
    def test_clear_cache(self):
        """Test clearing cache"""
        # Add some data
        self.calculator.add_market_data(self.sample_data[0])
        
        # Verify data is in cache
        data_key = f"{self.symbol}_1h"
        assert data_key in self.calculator.data_cache
        
        # Clear cache
        self.calculator.clear_cache()
        
        # Verify cache is empty
        assert len(self.calculator.data_cache) == 0
    
    def test_get_available_indicators(self):
        """Test getting available indicators"""
        # Add enough data for calculations
        base_time = datetime.now(timezone.utc) - timedelta(hours=100)
        
        for i in range(30):  # Add 30 data points
            data = MarketData(
                symbol=self.symbol,
                timestamp=base_time + timedelta(hours=i),
                open=1.1000 + i * 0.0001,
                high=1.1050 + i * 0.0001,
                low=1.0980 + i * 0.0001,
                close=1.1020 + i * 0.0001,
                volume=1000 + i * 10,
                bid=1.1018 + i * 0.0001,
                ask=1.1022 + i * 0.0001,
                spread=0.0004
            )
            self.calculator.add_market_data(data)
        
        # Calculate indicators
        indicators = self.calculator.calculate_indicators(self.symbol)
        
        # Get available indicators
        available = indicators.to_dict()
        
        # Should have several indicators available
        assert len(available) > 0
        assert "sma_20" in available
        assert "rsi" in available
    
    def test_calculate_all_indicators(self):
        """Test calculating all indicators"""
        # Add enough data for all indicators
        base_time = datetime.now(timezone.utc) - timedelta(hours=100)
        
        for i in range(50):  # Add 50 data points
            data = MarketData(
                symbol=self.symbol,
                timestamp=base_time + timedelta(hours=i),
                open=1.1000 + i * 0.0001,
                high=1.1050 + i * 0.0001,
                low=1.0980 + i * 0.0001,
                close=1.1020 + i * 0.0001,
                volume=1000 + i * 10,
                bid=1.1018 + i * 0.0001,
                ask=1.1022 + i * 0.0001,
                spread=0.0004
            )
            self.calculator.add_market_data(data)
        
        # Calculate all indicators
        indicators = self.calculator.calculate_indicators(self.symbol)
        
        # Check that all major indicators are calculated
        assert indicators.sma_20 is not None
        assert indicators.sma_50 is not None
        assert indicators.ema_12 is not None
        assert indicators.ema_26 is not None
        assert indicators.rsi is not None
        assert indicators.macd is not None
        assert indicators.macd_signal is not None
        assert indicators.bollinger_upper is not None
        assert indicators.bollinger_middle is not None
        assert indicators.bollinger_lower is not None
        assert indicators.atr is not None


if __name__ == "__main__":
    pytest.main([__file__])
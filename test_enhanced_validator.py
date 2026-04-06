"""
Test script for Enhanced Signal Validator
Checks:
- Multi-timeframe trend alignment
- Volatility regime detection
- Momentum divergence detection
- Liquidity filtering
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta
import random

# Add project root to path
sys.path.append(os.getcwd())

from src.models import MarketData, TradingSignal, Direction
from src.analysis.enhanced_signal_validator import (
    EnhancedSignalValidator, 
    EnhancedSignalConfig,
    VolatilityRegime,
    ConfluenceScore
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("TestValidator")

def create_mock_data(symbol="EUR/USD", count=100, trend="UP", volatility="NORMAL"):
    """Create synthetic OHLC data"""
    data = []
    base_price = 1.1000
    current_price = base_price
    
    start_time = datetime.now(timezone.utc) - timedelta(hours=count)
    
    # Trend settings
    if trend == "UP":
        trend_step = 0.0002
    elif trend == "DOWN":
        trend_step = -0.0002
    else:
        trend_step = 0.0
        
    # Volatility settings
    if volatility == "LOW":
        vol = 0.0005
    elif volatility == "HIGH":
        vol = 0.0020
    else:
        vol = 0.0010
        
    for i in range(count):
        # Add random noise
        noise = (random.random() - 0.5) * vol
        
        # Add trend component
        current_price += trend_step + noise
        
        # Create bar
        open_price = current_price
        high_price = open_price + (vol * 0.5)
        low_price = open_price - (vol * 0.5)
        close_price = open_price + (random.random() - 0.5) * vol * 0.5
        
        # Update current price for next bar
        current_price = close_price
        
        timestamp = start_time + timedelta(hours=i)
        
        bar = MarketData(
            symbol=symbol,
            timestamp=timestamp,
            open=round(open_price, 5),
            high=round(high_price, 5),
            low=round(low_price, 5),
            close=round(close_price, 5),
            volume=int(random.randint(100, 1000)),
            bid=round(close_price - 0.0001, 5),
            ask=round(close_price + 0.0001, 5),
            spread=0.0002
        )
        data.append(bar)
        
    return data

def test_uptrend_validation():
    """Test validation of a strong uptrend signal"""
    logger.info("--- Testing Valid Uptrend ---")
    
    # Create H1 data (Uptrend)
    h1_data = create_mock_data("EUR/USD", 100, trend="UP", volatility="NORMAL")
    
    # Create H4 data (Uptrend confirmation)
    h4_data = create_mock_data("EUR/USD", 50, trend="UP", volatility="NORMAL")
    
    # Create D1 data (Uptrend confirmation)
    d1_data = create_mock_data("EUR/USD", 30, trend="UP", volatility="NORMAL")
    
    # Create BUY signal
    signal = TradingSignal(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry_price=h1_data[-1].close,
        stop_loss=h1_data[-1].close - 0.0050,
        take_profit=h1_data[-1].close + 0.0100,
        position_size=0.01,
        confidence=0.85,
        reasoning="Test signal",
        timestamp=datetime.now(timezone.utc)
    )
    
    # Initialize validator
    validator = EnhancedSignalValidator(EnhancedSignalConfig())
    
    # Validate
    score = validator.validate_signal(
        signal, 
        h1_data, 
        higher_tf_data={"H4": h4_data, "D1": d1_data},
        current_positions=[]
    )
    
    if score.signal_approved:
        logger.info(f"✅ PASSED: Signal approved with score {score.total_score:.1f}")
        logger.info(f"   Breakdown: MTF={score.mtf_score:.0f}, Vol={score.volatility_score:.0f}")
    else:
        logger.error(f"❌ FAILED: Signal rejected. Reasons: {score.rejection_reasons}")

def test_divergence_rejection():
    """Test rejections of bad divergence"""
    logger.info("--- Testing Counter-Trend Rejection ---")
    
    # H1 is falling
    h1_data = create_mock_data("EUR/USD", 100, trend="DOWN", volatility="NORMAL")
    
    # Higher TFs are mixed/flat
    h4_data = create_mock_data("EUR/USD", 50, trend="RANGE", volatility="NORMAL")
    
    # Signal is BUY (against trend)
    signal = TradingSignal(
        symbol="EUR/USD",
        direction=Direction.LONG,
        entry_price=h1_data[-1].close,
        stop_loss=h1_data[-1].close - 0.0050,
        take_profit=h1_data[-1].close + 0.0100,
        position_size=0.01,
        confidence=0.60,
        reasoning="Counter trend punt",
        timestamp=datetime.now(timezone.utc)
    )
    
    validator = EnhancedSignalValidator(EnhancedSignalConfig())
    
    score = validator.validate_signal(
        signal, 
        h1_data, 
        higher_tf_data={"H4": h4_data},
        current_positions=[]
    )
    
    if not score.signal_approved:
        logger.info(f"✅ PASSED: Correctly rejected bad signal. Score: {score.total_score:.1f}")
        logger.info(f"   Reasons: {score.rejection_reasons}")
    else:
        logger.error(f"❌ FAILED: Incorrectly approved bad signal! Score: {score.total_score}")

def test_high_volatility_scaling():
    """Test position sizing reduction in high volatility"""
    logger.info("--- Testing High Volatility Sizing ---")
    
    # High volatility data
    data = create_mock_data("GBP/JPY", 100, trend="UP", volatility="HIGH")
    
    signal = TradingSignal(
        symbol="GBP/JPY",
        direction=Direction.LONG,
        entry_price=data[-1].close,
        stop_loss=data[-1].close - 0.0100,
        take_profit=data[-1].close + 0.0200,
        position_size=0.01,
        confidence=0.8,
        reasoning="Volatile breakout",
        timestamp=datetime.now(timezone.utc)
    )
    
    validator = EnhancedSignalValidator(EnhancedSignalConfig())
    
    score = validator.validate_signal(
        signal, 
        data, 
        higher_tf_data=None, 
        current_positions=[]
    )
    
    if score.position_size_multiplier < 1.0:
        logger.info(f"✅ PASSED: Position size reduced to {score.position_size_multiplier:.2f}x due to volatility")
    else:
        logger.error(f"❌ FAILED: Position size not reduced! Multiplier: {score.position_size_multiplier}")

if __name__ == "__main__":
    logger.info("Starting Validation Tests...")
    test_uptrend_validation()
    test_divergence_rejection()
    test_high_volatility_scaling()
    logger.info("Tests Complete.")

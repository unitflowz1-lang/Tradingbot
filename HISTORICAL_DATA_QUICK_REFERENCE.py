"""
QUICK REFERENCE: Historical Data Access
========================================
"""

# ============================================================================
# LOAD DATA
# ============================================================================

from src.data.historical_data_loader import HistoricalDataLoader
from src.data.hybrid_data_provider import HybridDataProvider
from datetime import datetime, timezone

# Method 1: Direct loader
loader = HistoricalDataLoader()
data = loader.load_eurusd_data()  # All EURUSD data
data = loader.load_data_by_symbol('EUR/USD')  # By symbol
data = loader._load_csv_file('DAT_MT_EURUSD_M1_202512.csv')  # Specific file

# Method 2: Hybrid provider (recommended)
provider = HybridDataProvider()
data = provider.get_historical_data('EUR/USD', count=100)


# ============================================================================
# GET DATA FOR DATE RANGE
# ============================================================================

start = datetime(2025, 12, 1, 0, 0, tzinfo=timezone.utc)
end = datetime(2025, 12, 5, 0, 0, tzinfo=timezone.utc)

# Using loader
data = loader.get_data_for_period('DAT_MT_EURUSD_M1_202512.csv', start, end)

# Using provider
data = provider.get_data_for_period('EUR/USD', start, end)


# ============================================================================
# BACKTEST ITERATION
# ============================================================================

for candle in provider.backtest_data_iterator('EUR/USD', start, end):
    price = candle.close
    timestamp = candle.timestamp
    # Your trading logic here...


# ============================================================================
# GET FILE/SYMBOL INFO
# ============================================================================

# List files
files = loader.list_available_files()

# Get file info
info = loader.get_file_info('DAT_MT_EURUSD_M1_202512.csv')

# Available symbols
symbols = provider.list_available_symbols()

# Symbol info
info = provider.get_symbol_info('EUR/USD')


# ============================================================================
# ANALYZE DATA
# ============================================================================

# Last 20 candles
recent = data[-20:]

# Prices
closes = [d.close for d in data]
opens = [d.open for d in data]
highs = [d.high for d in data]
lows = [d.low for d in data]

# Simple Moving Average
ma20 = sum(closes[-20:]) / 20

# Price range
min_price = min(lows)
max_price = max(highs)

# High/Low
latest_high = data[-1].high
latest_low = data[-1].low
latest_close = data[-1].close


# ============================================================================
# ERROR HANDLING
# ============================================================================

try:
    data = provider.get_historical_data('EUR/USD')
except FileNotFoundError:
    print("Data file not found")
except Exception as e:
    print(f"Error: {e}")


# ============================================================================
# CONFIGURATION
# ============================================================================

from src.data.historical_data_config import (
    HISTORICAL_DATA_DIR,
    AVAILABLE_SYMBOLS,
    BACKTEST_CONFIG,
    CSV_FORMAT
)

print(HISTORICAL_DATA_DIR)  # 'EURUSD Data'
print(BACKTEST_CONFIG)  # Default backtest settings
print(CSV_FORMAT)  # CSV column specification


# ============================================================================
# INTEGRATION WITH TRADING BOT
# ============================================================================

# In main.py
provider = HybridDataProvider()

for symbol in symbols:
    # Get market data
    historical_data = provider.get_historical_data(symbol, count=100)
    
    # Use with strategy
    signal = await strategy.analyze(historical_data)


# ============================================================================
# DATA PROPERTIES (Per Candle)
# ============================================================================

candle = data[0]

# Access candle data
timestamp = candle.timestamp  # datetime (UTC)
symbol = candle.symbol  # 'EUR/USD'
open_price = candle.open  # float
high = candle.high  # float
low = candle.low  # float
close = candle.close  # float
volume = candle.volume  # int
bid = candle.bid  # float
ask = candle.ask  # float
spread = candle.spread  # float


# ============================================================================
# USEFUL PATTERNS
# ============================================================================

# Get last N candles
last_n = data[-50:]

# Get candles from last hour
one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
recent = [d for d in data if d.timestamp >= one_hour_ago]

# Find highest price in period
highest = max(d.high for d in data)

# Find lowest price in period
lowest = min(d.low for d in data)

# Count candles in period
count = len(data)

# Get time range
start_time = data[0].timestamp
end_time = data[-1].timestamp
duration = end_time - start_time

# Check if data is complete
expected_candles = 1440  # 24 hours * 60 minutes
if len(data) == expected_candles:
    print("Data complete for 1 day")


# ============================================================================
# PERFORMANCE TIPS
# ============================================================================

# Cache data to avoid reloading
data_cache = {}
def get_data(symbol):
    if symbol not in data_cache:
        data_cache[symbol] = provider.get_historical_data(symbol)
    return data_cache[symbol]

# Process in batches for large datasets
batch_size = 1000
for i in range(0, len(data), batch_size):
    batch = data[i:i+batch_size]
    # Process batch...

# Use iterator for memory efficiency
for candle in provider.backtest_data_iterator(symbol, start, end):
    # Process one candle at a time
    pass


# ============================================================================
# COMMON ISSUES & SOLUTIONS
# ============================================================================

"""
Issue: FileNotFoundError
Solution: Check EURUSD Data folder exists in project root

Issue: No data returned
Solution: Verify filename format (DAT_MT_EURUSD_M1_*.csv)

Issue: DataValidationError
Solution: Check OHLC integrity (High >= Open/Close, Low <= Open/Close)

Issue: Wrong date range
Solution: Verify datetime objects have timezone (UTC)

Issue: Memory issues with large dataset
Solution: Use iterator instead of loading all at once
"""


# ============================================================================
# DATA AVAILABILITY
# ============================================================================

"""
Available Data:
  - Symbol: EUR/USD (EURUSD)
  - File: DAT_MT_EURUSD_M1_202512.csv
  - Timeframe: 1-minute bars
  - Start: 2025-12-01 00:00:00 UTC
  - End: 2025-12-26 16:58:00 UTC
  - Total Candles: 27,059

To add more data:
  1. Place CSV files in EURUSD Data folder
  2. Use format: Date,Time,Open,High,Low,Close,Volume
  3. Run test_historical_data_integration.py to verify
"""


# ============================================================================
# EXAMPLE: Complete Trading Loop
# ============================================================================

def example_trading_loop():
    from src.strategies.trend_strategy import SimpleTrendStrategy
    from src.risk.risk_calculator import RiskCalculator, RiskConfig
    
    provider = HybridDataProvider()
    symbol = 'EUR/USD'
    
    # Get data
    data = provider.get_historical_data(symbol, count=100)
    
    # Initialize strategy and risk calculator
    strategy = SimpleTrendStrategy(symbol)
    risk_config = RiskConfig(max_portfolio_risk=0.02)
    risk_calc = RiskCalculator(risk_config)
    
    # Analyze
    signal = strategy.analyze(data)
    
    if signal:
        # Check risk
        assessment = risk_calc.assess_trade_risk(signal, portfolio)
        
        if assessment.is_valid:
            # Execute trade
            print(f"Trade: {signal.direction} {symbol} @ {signal.entry_price}")


# ============================================================================
# TEST EVERYTHING
# ============================================================================

# Run integration tests
# python test_historical_data_integration.py

# Run examples
# python example_historical_data.py


# ============================================================================
# DOCUMENTATION
# ============================================================================

"""
Files:
  - src/data/historical_data_loader.py (Main loader)
  - src/data/hybrid_data_provider.py (Hybrid MT5/Historical)
  - src/data/historical_data_config.py (Configuration)
  - example_historical_data.py (Usage examples)
  - test_historical_data_integration.py (Tests)
  - HISTORICAL_DATA_INTEGRATION.md (Full guide)
  - EURUSD_DATA_INTEGRATION_SUMMARY.md (Summary)

References:
  - https://github.com/mql5/mql5-docs/blob/master/docs/OHLC.md
  - CSV format specifications in historical_data_config.py
  - MarketData model in src/models.py
"""

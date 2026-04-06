"""
Configuration for historical data access and backtesting
"""

from pathlib import Path


# Data directory configuration
HISTORICAL_DATA_DIR = "EURUSD Data"
HISTORICAL_DATA_FULL_PATH = Path(__file__).parent / HISTORICAL_DATA_DIR

# Available symbols and their data files
AVAILABLE_SYMBOLS = {
    'EUR/USD': {
        'mt5_symbol': 'EURUSD',
        'file_pattern': '*EURUSD*.csv',
        'timeframe': 'M1',  # 1-minute bars
    },
    'GBP/USD': {
        'mt5_symbol': 'GBPUSD',
        'file_pattern': '*GBPUSD*.csv',
        'timeframe': 'M1',
    },
    'USD/JPY': {
        'mt5_symbol': 'USDJPY',
        'file_pattern': '*USDJPY*.csv',
        'timeframe': 'M1',
    },
}

# Backtesting configuration
BACKTEST_CONFIG = {
    'default_symbol': 'EUR/USD',
    'default_start_date': '2025-12-01',
    'default_end_date': '2025-12-31',
    'default_candle_count': 100,
    'max_candle_count': 10000,
}

# Data validation settings
DATA_VALIDATION = {
    'min_candles_for_analysis': 10,
    'min_ohlc_values': 4,
    'allow_zero_volume': True,
}

# CSV format specification
CSV_FORMAT = {
    'delimiter': ',',
    'date_format': '%Y.%m.%d',
    'time_format': '%H:%M',
    'columns': {
        0: 'date',
        1: 'time',
        2: 'open',
        3: 'high',
        4: 'low',
        5: 'close',
        6: 'volume',
    },
}

# Caching configuration
CACHE_CONFIG = {
    'enable_cache': True,
    'cache_max_age_seconds': 300,  # 5 minutes
    'cache_max_entries': 10,
}

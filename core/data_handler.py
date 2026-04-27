"""
Data handling and caching layer.
Supports multiple data sources, normalization, and caching.
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from abc import ABC, abstractmethod
import pickle
import json
from utils.logger import get_logger


logger = get_logger(__name__)


class DataHandler(ABC):
    """Abstract base class for data handling."""
    
    @abstractmethod
    def get_historical_data(self, symbol: str, start: datetime, end: datetime, 
                           granularity: str) -> pd.DataFrame:
        """Get historical OHLCV data."""
        pass
    
    @abstractmethod
    def get_latest_bar(self, symbol: str, granularity: str) -> Dict:
        """Get latest bar data for a symbol."""
        pass
    
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if data source is connected."""
        pass


class CachedDataHandler(DataHandler):
    """
    Data handler with caching support.
    Caches historical data locally to reduce API calls.
    """
    
    def __init__(self, cache_dir: str = "data/cache", max_cache_age_days: int = 7):
        """
        Initialize CachedDataHandler.
        
        Args:
            cache_dir: Directory to store cached data
            max_cache_age_days: Maximum age of cached data
        """
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.max_cache_age = timedelta(days=max_cache_age_days)
    
    def _get_cache_key(self, symbol: str, start: datetime, end: datetime, 
                      granularity: str) -> str:
        """Generate cache key for data."""
        return f"{symbol}_{granularity}_{start.date()}_{end.date()}"
    
    def _get_cache_path(self, cache_key: str) -> Path:
        """Get cache file path."""
        return self.cache_dir / f"{cache_key}.pkl"
    
    def _is_cache_valid(self, cache_path: Path) -> bool:
        """Check if cached data is still valid."""
        if not cache_path.exists():
            return False
        
        file_age = datetime.now() - datetime.fromtimestamp(cache_path.stat().st_mtime)
        return file_age < self.max_cache_age
    
    def get_cached_data(self, symbol: str, start: datetime, end: datetime,
                       granularity: str) -> Optional[pd.DataFrame]:
        """Get cached data if available."""
        cache_key = self._get_cache_key(symbol, start, end, granularity)
        cache_path = self._get_cache_path(cache_key)
        
        if self._is_cache_valid(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    data = pickle.load(f)
                logger.info("Using cached data", symbol=symbol, cache_key=cache_key)
                return data
            except Exception as e:
                logger.error(f"Error loading cache: {e}", cache_key=cache_key)
                return None
        
        return None
    
    def cache_data(self, symbol: str, start: datetime, end: datetime,
                  granularity: str, data: pd.DataFrame):
        """Cache historical data."""
        cache_key = self._get_cache_key(symbol, start, end, granularity)
        cache_path = self._get_cache_path(cache_key)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(data, f)
            logger.info("Data cached", symbol=symbol, cache_key=cache_key)
        except Exception as e:
            logger.error(f"Error caching data: {e}", cache_key=cache_key)


class NormalizingDataHandler(CachedDataHandler):
    """
    Data handler that normalizes data from different sources.
    Handles timezone conversion, missing candles, bid/ask prices.
    """
    
    def __init__(self, cache_dir: str = "data/cache", timezone: str = "UTC"):
        """Initialize normalizing handler."""
        super().__init__(cache_dir)
        self.timezone = timezone
    
    def normalize_ohlcv(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Normalize OHLCV data.
        
        Ensures consistent format:
        - timestamp (datetime)
        - open, high, low, close (float)
        - volume (int)
        """
        # Standardize column names
        df.columns = df.columns.str.lower()
        
        # Ensure timestamp is datetime
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
        elif 'date' in df.columns:
            df['timestamp'] = pd.to_datetime(df['date'])
        else:
            df['timestamp'] = pd.to_datetime(df.index)
        
        # Set timezone
        if df['timestamp'].dt.tz is None:
            df['timestamp'] = df['timestamp'].dt.tz_localize(self.timezone)
        else:
            df['timestamp'] = df['timestamp'].dt.tz_convert(self.timezone)
        
        # Standardize OHLCV columns
        required_cols = ['open', 'high', 'low', 'close', 'volume']
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")
        
        # Convert to float/int
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df['volume'] = pd.to_numeric(df['volume'], errors='coerce', downcast='integer')
        
        # Remove rows with NaN values
        df = df.dropna()
        
        # Sort by timestamp
        df = df.sort_values('timestamp').reset_index(drop=True)
        
        return df
    
    def fill_missing_candles(self, df: pd.DataFrame, granularity: str) -> pd.DataFrame:
        """
        Fill missing candles with forward fill.
        
        Args:
            df: OHLCV DataFrame
            granularity: Candle granularity (e.g., 'H1', 'D1')
        """
        # Parse granularity to frequency
        granularity_map = {
            'M1': '1min', 'M5': '5min', 'M15': '15min', 'M30': '30min',
            'H1': 'H', 'H4': '4H', 'D1': 'D', 'W1': 'W'
        }
        freq = granularity_map.get(granularity, 'H')
        
        # Create complete date range
        date_range = pd.date_range(
            start=df['timestamp'].min(),
            end=df['timestamp'].max(),
            freq=freq
        )
        
        # Reindex to fill gaps
        df_complete = df.set_index('timestamp').reindex(date_range)
        df_complete.index.name = 'timestamp'
        
        # Forward fill OHLCV
        df_complete[['open', 'high', 'low', 'close', 'volume']] = \
            df_complete[['open', 'high', 'low', 'close', 'volume']].ffill()
        
        return df_complete.reset_index()
    
    def get_realistic_bid_ask(self, close_price: float, spread_bps: float) -> Tuple[float, float]:
        """
        Get realistic bid/ask prices given close price and spread.
        
        Args:
            close_price: Closing price
            spread_bps: Spread in basis points
        
        Returns:
            Tuple of (bid, ask) prices
        """
        spread = close_price * (spread_bps / 10000)
        bid = close_price - spread / 2
        ask = close_price + spread / 2
        return bid, ask
    
    def get_historical_data(self, symbol: str, start: datetime, end: datetime,
                           granularity: str) -> pd.DataFrame:
        """Get normalized historical data with caching."""
        # Check cache first
        cached_data = self.get_cached_data(symbol, start, end, granularity)
        if cached_data is not None:
            return cached_data
        
        # This would be overridden by subclass with actual data source
        return pd.DataFrame()
    
    def get_latest_bar(self, symbol: str, granularity: str) -> Dict:
        """Get latest bar data."""
        # To be implemented by subclass
        return {}
    
    def is_connected(self) -> bool:
        """Check connection status."""
        # To be implemented by subclass
        return True


class MT5DataHandler(NormalizingDataHandler):
    """Data handler for MT5 broker."""
    
    def __init__(self, broker_connection, cache_dir: str = "data/cache"):
        """Initialize MT5 data handler."""
        super().__init__(cache_dir)
        self.broker = broker_connection
    
    def get_historical_data(self, symbol: str, start: datetime, end: datetime,
                           granularity: str) -> pd.DataFrame:
        """Get historical data from MT5."""
        # Check cache first
        cached = self.get_cached_data(symbol, start, end, granularity)
        if cached is not None:
            return cached
        
        # Get from MT5 (requires MT5 API implementation)
        try:
            # Placeholder - actual implementation would call MT5 API
            data = self.broker.get_candles(symbol, granularity, start, end)
            if data is not None:
                data = self.normalize_ohlcv(data)
                self.cache_data(symbol, start, end, granularity, data)
                return data
        except Exception as e:
            logger.error(f"Error fetching MT5 data: {e}", symbol=symbol)
        
        return pd.DataFrame()
    
    def get_latest_bar(self, symbol: str, granularity: str) -> Dict:
        """Get latest bar from MT5."""
        try:
            return self.broker.get_latest_bar(symbol, granularity)
        except Exception as e:
            logger.error(f"Error getting latest bar: {e}", symbol=symbol)
            return {}
    
    def is_connected(self) -> bool:
        """Check if MT5 is connected."""
        return self.broker.is_connected() if self.broker else False

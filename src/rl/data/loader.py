"""
Historical Data Loader for RL Training

Provides efficient loading and caching of historical market data
for training RL agents across multiple years of data.
"""

import os
import pickle
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Iterator, Union
from dataclasses import dataclass, field
from pathlib import Path
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib

from ...models import MarketData
from ...exceptions import DataValidationError


@dataclass
class DataLoaderConfig:
    """Configuration for historical data loader."""
    
    # Data source settings
    data_directory: str = "data"
    cache_directory: str = "data/cache"
    database_path: Optional[str] = None
    
    # Time range settings
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    
    # Symbol settings
    symbols: List[str] = field(default_factory=lambda: ["EUR/USD"])
    timeframes: List[str] = field(default_factory=lambda: ["1H"])
    
    # Performance settings
    chunk_size: int = 10000
    max_workers: int = 4
    enable_caching: bool = True
    cache_compression: bool = True
    
    # Validation settings
    validate_data: bool = True
    fill_missing_data: bool = True
    max_gap_minutes: int = 60
    
    # Memory management
    max_memory_usage_gb: float = 4.0
    lazy_loading: bool = True


class HistoricalDataLoader:
    """
    Efficient loader for historical market data with caching and validation.
    
    Supports loading from multiple sources including CSV files, databases,
    and cached pickle files for fast access.
    """
    
    def __init__(self, config: DataLoaderConfig):
        """
        Initialize data loader.
        
        Args:
            config: Data loader configuration
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Create directories
        os.makedirs(self.config.data_directory, exist_ok=True)
        if self.config.enable_caching:
            os.makedirs(self.config.cache_directory, exist_ok=True)
            
        # Initialize cache
        self._cache = {}
        self._cache_stats = {"hits": 0, "misses": 0}
        
        # Data validation
        self._validate_config()
        
    def load_data(self, 
                  symbol: str,
                  timeframe: str,
                  start_date: Optional[datetime] = None,
                  end_date: Optional[datetime] = None) -> List[MarketData]:
        """
        Load historical market data for specified parameters.
        
        Args:
            symbol: Currency pair symbol (e.g., "EUR/USD")
            timeframe: Data timeframe (e.g., "1H", "1D")
            start_date: Start date for data (optional)
            end_date: End date for data (optional)
            
        Returns:
            List of MarketData objects sorted by timestamp
            
        Raises:
            DataValidationError: If data validation fails
            FileNotFoundError: If data files not found
        """
        # Use config defaults if not specified
        start_date = start_date or self.config.start_date
        end_date = end_date or self.config.end_date
        
        # Generate cache key
        cache_key = self._generate_cache_key(symbol, timeframe, start_date, end_date)
        
        # Check cache first
        if self.config.enable_caching and cache_key in self._cache:
            self._cache_stats["hits"] += 1
            self.logger.debug(f"Cache hit for {symbol} {timeframe}")
            return self._cache[cache_key]
            
        self._cache_stats["misses"] += 1
        
        # Load from source
        data = self._load_from_source(symbol, timeframe, start_date, end_date)
        
        # Validate and clean data
        if self.config.validate_data:
            data = self._validate_and_clean_data(data)
            
        # Fill missing data if enabled
        if self.config.fill_missing_data:
            data = self._fill_missing_data(data, timeframe)
            
        # Cache the result
        if self.config.enable_caching:
            self._cache[cache_key] = data
            self._save_to_cache(cache_key, data)
            
        self.logger.info(f"Loaded {len(data)} data points for {symbol} {timeframe}")
        return data
        
    def load_multiple_symbols(self,
                            symbols: Optional[List[str]] = None,
                            timeframes: Optional[List[str]] = None,
                            start_date: Optional[datetime] = None,
                            end_date: Optional[datetime] = None) -> Dict[str, Dict[str, List[MarketData]]]:
        """
        Load data for multiple symbols and timeframes in parallel.
        
        Args:
            symbols: List of symbols to load (uses config default if None)
            timeframes: List of timeframes to load (uses config default if None)
            start_date: Start date for data
            end_date: End date for data
            
        Returns:
            Nested dictionary: {symbol: {timeframe: [MarketData]}}
        """
        symbols = symbols or self.config.symbols
        timeframes = timeframes or self.config.timeframes
        
        result = {}
        
        # Create tasks for parallel loading
        tasks = []
        with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
            for symbol in symbols:
                for timeframe in timeframes:
                    future = executor.submit(
                        self.load_data, symbol, timeframe, start_date, end_date
                    )
                    tasks.append((future, symbol, timeframe))
                    
            # Collect results
            for future, symbol, timeframe in tasks:
                try:
                    data = future.result()
                    if symbol not in result:
                        result[symbol] = {}
                    result[symbol][timeframe] = data
                except Exception as e:
                    self.logger.error(f"Failed to load {symbol} {timeframe}: {e}")
                    raise
                    
        return result
        
    def get_data_iterator(self,
                         symbol: str,
                         timeframe: str,
                         start_date: Optional[datetime] = None,
                         end_date: Optional[datetime] = None,
                         chunk_size: Optional[int] = None) -> Iterator[List[MarketData]]:
        """
        Get iterator for streaming large datasets in chunks.
        
        Args:
            symbol: Currency pair symbol
            timeframe: Data timeframe
            start_date: Start date for data
            end_date: End date for data
            chunk_size: Size of each chunk (uses config default if None)
            
        Yields:
            Chunks of MarketData objects
        """
        chunk_size = chunk_size or self.config.chunk_size
        
        # Load data in chunks if lazy loading is enabled
        if self.config.lazy_loading:
            yield from self._lazy_load_chunks(symbol, timeframe, start_date, end_date, chunk_size)
        else:
            # Load all data and yield in chunks
            data = self.load_data(symbol, timeframe, start_date, end_date)
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]
                
    def get_cache_stats(self) -> Dict[str, Union[int, float]]:
        """Get cache performance statistics."""
        total_requests = self._cache_stats["hits"] + self._cache_stats["misses"]
        hit_rate = self._cache_stats["hits"] / max(1, total_requests)
        
        return {
            "cache_hits": self._cache_stats["hits"],
            "cache_misses": self._cache_stats["misses"],
            "hit_rate": hit_rate,
            "cached_items": len(self._cache)
        }
        
    def clear_cache(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        self._cache_stats = {"hits": 0, "misses": 0}
        
        # Clear disk cache
        if self.config.enable_caching:
            cache_dir = Path(self.config.cache_directory)
            for cache_file in cache_dir.glob("*.pkl"):
                cache_file.unlink()
                
    def _validate_config(self) -> None:
        """Validate configuration parameters."""
        if not self.config.symbols:
            raise ValueError("At least one symbol must be specified")
            
        if not self.config.timeframes:
            raise ValueError("At least one timeframe must be specified")
            
        if self.config.chunk_size <= 0:
            raise ValueError("Chunk size must be positive")
            
        if self.config.max_workers <= 0:
            raise ValueError("Max workers must be positive")
            
    def _generate_cache_key(self,
                          symbol: str,
                          timeframe: str,
                          start_date: Optional[datetime],
                          end_date: Optional[datetime]) -> str:
        """Generate unique cache key for data request."""
        key_parts = [symbol, timeframe]
        
        if start_date:
            key_parts.append(start_date.isoformat())
        if end_date:
            key_parts.append(end_date.isoformat())
            
        key_string = "|".join(key_parts)
        return hashlib.md5(key_string.encode()).hexdigest()
        
    def _load_from_source(self,
                         symbol: str,
                         timeframe: str,
                         start_date: Optional[datetime],
                         end_date: Optional[datetime]) -> List[MarketData]:
        """Load data from the configured source."""
        # Try cache first
        cache_key = self._generate_cache_key(symbol, timeframe, start_date, end_date)
        cached_data = self._load_from_cache(cache_key)
        if cached_data is not None:
            return cached_data
            
        # Try database if configured
        if self.config.database_path:
            try:
                return self._load_from_database(symbol, timeframe, start_date, end_date)
            except Exception as e:
                self.logger.warning(f"Database load failed: {e}")
                
        # Fall back to CSV files
        return self._load_from_csv(symbol, timeframe, start_date, end_date)
        
    def _load_from_database(self,
                           symbol: str,
                           timeframe: str,
                           start_date: Optional[datetime],
                           end_date: Optional[datetime]) -> List[MarketData]:
        """Load data from SQLite database."""
        conn = sqlite3.connect(self.config.database_path)
        
        try:
            query = """
                SELECT symbol, timestamp, open, high, low, close, volume, bid, ask, spread
                FROM market_data 
                WHERE symbol = ? AND timeframe = ?
            """
            params = [symbol, timeframe]
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date.isoformat())
                
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date.isoformat())
                
            query += " ORDER BY timestamp"
            
            df = pd.read_sql_query(query, conn, params=params)
            
            # Convert to MarketData objects
            data = []
            for _, row in df.iterrows():
                market_data = MarketData(
                    symbol=row['symbol'],
                    timestamp=datetime.fromisoformat(row['timestamp']),
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=int(row['volume']),
                    bid=float(row['bid']),
                    ask=float(row['ask']),
                    spread=float(row['spread'])
                )
                data.append(market_data)
                
            return data
            
        finally:
            conn.close()
            
    def _load_from_csv(self,
                      symbol: str,
                      timeframe: str,
                      start_date: Optional[datetime],
                      end_date: Optional[datetime]) -> List[MarketData]:
        """Load data from CSV files."""
        # Construct file path
        filename = f"{symbol.replace('/', '_')}_{timeframe}.csv"
        filepath = Path(self.config.data_directory) / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"Data file not found: {filepath}")
            
        # Load CSV
        df = pd.read_csv(filepath)
        
        # Convert timestamp column
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        # Filter by date range
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]
            
        # Convert to MarketData objects
        data = []
        for _, row in df.iterrows():
            market_data = MarketData(
                symbol=row['symbol'],
                timestamp=row['timestamp'].to_pydatetime(),
                open=float(row['open']),
                high=float(row['high']),
                low=float(row['low']),
                close=float(row['close']),
                volume=int(row['volume']),
                bid=float(row['bid']),
                ask=float(row['ask']),
                spread=float(row['spread'])
            )
            data.append(market_data)
            
        return data
        
    def _validate_and_clean_data(self, data: List[MarketData]) -> List[MarketData]:
        """Validate and clean market data."""
        cleaned_data = []
        
        for i, market_data in enumerate(data):
            try:
                market_data.validate()
                cleaned_data.append(market_data)
            except DataValidationError as e:
                self.logger.warning(f"Invalid data at index {i}: {e}")
                # Skip invalid data points
                continue
                
        return cleaned_data
        
    def _fill_missing_data(self, data: List[MarketData], timeframe: str) -> List[MarketData]:
        """Fill missing data points using interpolation."""
        if len(data) < 2:
            return data
            
        # Parse timeframe to get interval
        interval_minutes = self._parse_timeframe_minutes(timeframe)
        
        filled_data = []
        
        for i in range(len(data) - 1):
            current = data[i]
            next_data = data[i + 1]
            
            filled_data.append(current)
            
            # Check for gap
            expected_next_time = current.timestamp + timedelta(minutes=interval_minutes)
            gap_minutes = (next_data.timestamp - expected_next_time).total_seconds() / 60
            
            # Fill gap if it's within acceptable range
            if 0 < gap_minutes <= self.config.max_gap_minutes:
                filled_data.extend(self._interpolate_data(current, next_data, interval_minutes))
                
        # Add the last data point
        filled_data.append(data[-1])
        
        return filled_data
        
    def _interpolate_data(self, 
                         start_data: MarketData, 
                         end_data: MarketData, 
                         interval_minutes: int) -> List[MarketData]:
        """Interpolate missing data points between two data points."""
        interpolated = []
        
        current_time = start_data.timestamp + timedelta(minutes=interval_minutes)
        
        while current_time < end_data.timestamp:
            # Linear interpolation for prices
            time_ratio = (current_time - start_data.timestamp).total_seconds() / \
                        (end_data.timestamp - start_data.timestamp).total_seconds()
                        
            interpolated_data = MarketData(
                symbol=start_data.symbol,
                timestamp=current_time,
                open=start_data.close,  # Use previous close as open
                high=start_data.close + time_ratio * (end_data.high - start_data.close),
                low=start_data.close + time_ratio * (end_data.low - start_data.close),
                close=start_data.close + time_ratio * (end_data.close - start_data.close),
                volume=int(start_data.volume * (1 - time_ratio) + end_data.volume * time_ratio),
                bid=start_data.bid + time_ratio * (end_data.bid - start_data.bid),
                ask=start_data.ask + time_ratio * (end_data.ask - start_data.ask),
                spread=start_data.spread + time_ratio * (end_data.spread - start_data.spread)
            )
            
            interpolated.append(interpolated_data)
            current_time += timedelta(minutes=interval_minutes)
            
        return interpolated
        
    def _parse_timeframe_minutes(self, timeframe: str) -> int:
        """Parse timeframe string to minutes."""
        timeframe = timeframe.upper()
        
        if timeframe.endswith('M'):
            return int(timeframe[:-1])
        elif timeframe.endswith('H'):
            return int(timeframe[:-1]) * 60
        elif timeframe.endswith('D'):
            return int(timeframe[:-1]) * 24 * 60
        else:
            raise ValueError(f"Unsupported timeframe format: {timeframe}")
            
    def _save_to_cache(self, cache_key: str, data: List[MarketData]) -> None:
        """Save data to disk cache."""
        if not self.config.enable_caching:
            return
            
        cache_file = Path(self.config.cache_directory) / f"{cache_key}.pkl"
        
        try:
            with open(cache_file, 'wb') as f:
                if self.config.cache_compression:
                    import gzip
                    with gzip.open(f, 'wb') as gz_f:
                        pickle.dump(data, gz_f)
                else:
                    pickle.dump(data, f)
        except Exception as e:
            self.logger.warning(f"Failed to save cache: {e}")
            
    def _load_from_cache(self, cache_key: str) -> Optional[List[MarketData]]:
        """Load data from disk cache."""
        if not self.config.enable_caching:
            return None
            
        cache_file = Path(self.config.cache_directory) / f"{cache_key}.pkl"
        
        if not cache_file.exists():
            return None
            
        try:
            with open(cache_file, 'rb') as f:
                if self.config.cache_compression:
                    import gzip
                    with gzip.open(f, 'rb') as gz_f:
                        return pickle.load(gz_f)
                else:
                    return pickle.load(f)
        except Exception as e:
            self.logger.warning(f"Failed to load cache: {e}")
            return None
            
    def _lazy_load_chunks(self,
                         symbol: str,
                         timeframe: str,
                         start_date: Optional[datetime],
                         end_date: Optional[datetime],
                         chunk_size: int) -> Iterator[List[MarketData]]:
        """Lazy load data in chunks to manage memory usage."""
        # This is a simplified implementation
        # In practice, you might implement more sophisticated chunking
        # based on date ranges or file segments
        
        data = self._load_from_source(symbol, timeframe, start_date, end_date)
        
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]
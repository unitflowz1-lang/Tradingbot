"""
Hybrid data provider combining MT5 live data with historical fallback
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional

from src.models import MarketData
from src.data.historical_data_loader import HistoricalDataLoader


class HybridDataProvider:
    """
    Provides market data from both MT5 and historical sources.
    Falls back to historical data when MT5 is unavailable.
    """

    def __init__(
            self,
            mt5_broker=None,
            historical_data_dir: str = "EURUSD Data"):
        """
        Initialize hybrid data provider.

        Args:
            mt5_broker: Optional MT5 broker instance
            historical_data_dir: Directory with historical data files
        """
        self.mt5_broker = mt5_broker
        self.historical_loader = HistoricalDataLoader(
            historical_data_dir)
        self.logger = logging.getLogger(__name__)
        self._cached_data: Dict[str, List[MarketData]] = {}
        self._cache_timestamp: Dict[str, datetime] = {}

    def get_historical_data(
            self,
            symbol: str,
            timeframe: int = 1,
            count: int = 100) -> List[MarketData]:
        """
        Get historical data with MT5 fallback.

        Args:
            symbol: Trading symbol (e.g., 'EUR/USD')
            timeframe: Timeframe in minutes (default 1)
            count: Number of candles to return

        Returns:
            List of MarketData objects
        """
        # Try MT5 first if broker is available
        if self.mt5_broker and self.mt5_broker.connected:
            try:
                data = self.mt5_broker.get_historical_data(
                    symbol, timeframe, count)
                if data:
                    self.logger.debug(
                        "Retrieved %d candles for %s from MT5",
                        len(data), symbol)
                    return data
            except Exception as e:
                self.logger.warning(
                    "MT5 data retrieval failed for %s: %s",
                    symbol, e)

        # Fallback to historical data
        self.logger.info(
            "Using historical data for %s (MT5 unavailable)",
            symbol)
        return self._get_historical_fallback(symbol, count)

    def _get_historical_fallback(
            self,
            symbol: str,
            count: int = 100) -> List[MarketData]:
        """
        Get historical data from CSV files.

        Args:
            symbol: Trading symbol
            count: Number of recent candles to return

        Returns:
            List of MarketData objects
        """
        # Load all available data for the symbol
        all_data = self.historical_loader.load_data_by_symbol(symbol)

        if not all_data:
            self.logger.warning(
                "No historical data found for %s", symbol)
            return []

        # Return the last 'count' candles
        return all_data[-count:] if len(all_data) > count else all_data

    def get_data_for_period(
            self,
            symbol: str,
            start_date: datetime,
            end_date: datetime) -> List[MarketData]:
        """
        Get data for a specific time period.

        Args:
            symbol: Trading symbol
            start_date: Start of period (UTC)
            end_date: End of period (UTC)

        Returns:
            List of MarketData objects in the period
        """
        # For now, load from historical data
        all_data = self.historical_loader.load_data_by_symbol(symbol)

        # Filter by date range
        filtered = [
            d for d in all_data
            if start_date <= d.timestamp <= end_date
        ]

        return filtered

    def backtest_data_iterator(
            self,
            symbol: str,
            start_date: datetime,
            end_date: datetime):
        """
        Generator for backtesting that yields market data points.

        Args:
            symbol: Trading symbol
            start_date: Start of backtest period
            end_date: End of backtest period

        Yields:
            MarketData objects in chronological order
        """
        data = self.get_data_for_period(symbol, start_date, end_date)

        for candle in sorted(data, key=lambda x: x.timestamp):
            yield candle

    def list_available_symbols(self) -> List[str]:
        """List available symbols with historical data."""
        files = self.historical_loader.list_available_files()
        symbols = set()

        for filename in files:
            # Extract symbol from filename (e.g., DAT_MT_EURUSD_M1_...)
            parts = filename.split('_')
            for part in parts:
                if part in ['EURUSD', 'GBPUSD', 'USDJPY']:
                    # Convert to standard format
                    if part == 'EURUSD':
                        symbols.add('EUR/USD')
                    elif part == 'GBPUSD':
                        symbols.add('GBP/USD')
                    elif part == 'USDJPY':
                        symbols.add('USD/JPY')

        return sorted(list(symbols))

    def get_symbol_info(self, symbol: str) -> Dict[str, any]:
        """
        Get information about available data for a symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Dict with symbol info
        """
        files = self.historical_loader.list_available_files()

        # Normalize symbol
        normalized = symbol.replace('/', '').upper()

        matching_files = [
            f for f in files
            if normalized in f.upper()
        ]

        if not matching_files:
            return {
                'symbol': symbol,
                'available': False
            }

        # Get info from first matching file
        file_info = self.historical_loader.get_file_info(
            matching_files[0])

        return {
            'symbol': symbol,
            'available': True,
            **file_info
        }

"""
Historical Data Loader for EURUSD and other forex pairs
Loads historical OHLCV data from CSV files
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Tuple

from src.models import MarketData


class HistoricalDataLoader:
    """Load historical market data from CSV files"""

    def __init__(self, data_dir: str = "EURUSD Data"):
        """
        Initialize data loader.

        Args:
            data_dir: Directory containing historical data files
        """
        self.data_dir = Path(data_dir)
        self.logger = logging.getLogger(__name__)

        if not self.data_dir.exists():
            self.logger.warning(
                "Data directory not found: %s", self.data_dir)

    def load_eurusd_data(
            self, filename: Optional[str] = None) -> List[MarketData]:
        """
        Load EURUSD historical data from CSV.

        Args:
            filename: Optional specific filename. If None, uses latest
                     available file.

        Returns:
            List of MarketData objects
        """
        if filename is None:
            # Find the most recent EURUSD data file
            filename = self._find_latest_eurusd_file()

        if not filename:
            self.logger.error("No EURUSD data file found")
            return []

        return self._load_csv_file(filename)

    def load_data_by_symbol(
            self, symbol: str) -> List[MarketData]:
        """
        Load historical data for a specific symbol.

        Args:
            symbol: Trading symbol (e.g., 'EURUSD', 'EUR/USD')

        Returns:
            List of MarketData objects
        """
        # Normalize symbol format
        normalized_symbol = symbol.replace('/', '').upper()

        # Find matching file
        matching_files = list(
            self.data_dir.glob(f"*{normalized_symbol}*.csv"))

        if not matching_files:
            self.logger.warning(
                "No data file found for symbol: %s", symbol)
            return []

        # Use the most recent file
        latest_file = max(matching_files, key=lambda p: p.stat().st_mtime)

        return self._load_csv_file(latest_file.name)

    def _find_latest_eurusd_file(self) -> Optional[str]:
        """Find the most recent EURUSD CSV file."""
        if not self.data_dir.exists():
            return None

        eurusd_files = list(self.data_dir.glob("*EURUSD*.csv"))

        if not eurusd_files:
            return None

        # Return the most recently modified file
        latest = max(eurusd_files, key=lambda p: p.stat().st_mtime)
        return latest.name

    def _load_csv_file(self, filename: str) -> List[MarketData]:
        """
        Load market data from CSV file.

        CSV format expected:
        Date, Time, Open, High, Low, Close, Volume

        Args:
            filename: Name of the CSV file

        Returns:
            List of MarketData objects
        """
        filepath = self.data_dir / filename
        market_data: List[MarketData] = []

        if not filepath.exists():
            self.logger.error("File not found: %s", filepath)
            return []

        try:
            with open(filepath, 'r') as f:
                reader = csv.reader(f)

                for row_num, row in enumerate(reader, 1):
                    try:
                        if len(row) < 7:
                            continue

                        # Parse date and time
                        date_str = row[0]
                        time_str = row[1]
                        timestamp_str = (
                            f"{date_str.replace('.', '-')} {time_str}")
                        timestamp = datetime.strptime(
                            timestamp_str, "%Y-%m-%d %H:%M")
                        timestamp = timestamp.replace(tzinfo=timezone.utc)

                        # Parse OHLCV data
                        close_price = float(row[5])
                        spread = 0.00001  # 1 pip spread
                        market_data.append(
                            MarketData(
                                timestamp=timestamp,
                                symbol='EUR/USD',
                                open=float(row[2]),
                                high=float(row[3]),
                                low=float(row[4]),
                                close=close_price,
                                volume=int(float(row[6]))
                                if row[6] else 0,
                                bid=close_price - spread / 2,
                                ask=close_price + spread / 2,
                                spread=spread
                            )
                        )

                    except (ValueError, IndexError) as e:
                        self.logger.warning(
                            "Error parsing row %d: %s", row_num, e)
                        continue

            self.logger.info(
                "Loaded %d market data points from %s",
                len(market_data), filename)

            return market_data

        except IOError as e:
            self.logger.error("Error reading file %s: %s", filepath, e)
            return []

    def get_data_for_period(
            self,
            filename: str,
            start_date: Optional[datetime] = None,
            end_date: Optional[datetime] = None) -> List[MarketData]:
        """
        Load historical data for a specific time period.

        Args:
            filename: CSV filename
            start_date: Optional start date (UTC)
            end_date: Optional end date (UTC)

        Returns:
            Filtered list of MarketData objects
        """
        all_data = self._load_csv_file(filename)

        if not start_date and not end_date:
            return all_data

        filtered_data = []
        for candle in all_data:
            if start_date and candle.timestamp < start_date:
                continue
            if end_date and candle.timestamp > end_date:
                continue
            filtered_data.append(candle)

        return filtered_data

    def list_available_files(self) -> List[str]:
        """List all available historical data CSV files."""
        if not self.data_dir.exists():
            return []

        csv_files = [f.name for f in self.data_dir.glob("*.csv")]
        return sorted(csv_files)

    def get_file_info(self, filename: str) -> Dict[str, any]:
        """Get information about a data file."""
        filepath = self.data_dir / filename

        if not filepath.exists():
            return {}

        data = self._load_csv_file(filename)

        if not data:
            return {}

        return {
            'filename': filename,
            'symbol': data[0].symbol if data else None,
            'candle_count': len(data),
            'start_time': data[0].timestamp if data else None,
            'end_time': data[-1].timestamp if data else None,
            'timeframe_minutes': 1
        }

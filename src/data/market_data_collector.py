"""Market data collector implementation"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
import aiohttp
from src.interfaces import DataCollector, BrokerInterface
from src.models import MarketData
from src.exceptions import DataValidationError, APIError
from src.config import Config


logger = logging.getLogger(__name__)


class MarketDataCollector(DataCollector):
    """Collects real-time market data from broker APIs"""
    
    def __init__(self, broker_interface: BrokerInterface, config: Config):
        self.broker_interface = broker_interface
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.cache: Dict[str, MarketData] = {}
        self.cache_ttl = timedelta(seconds=config.market_data_cache_ttl)
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=self.config.api_timeout)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    async def collect_data(self, symbols: List[str], timeframe: str = "1m") -> Dict[str, Any]:
        """
        Collect market data for given symbols and timeframe
        
        Args:
            symbols: List of currency pairs (e.g., ['EUR/USD', 'GBP/USD'])
            timeframe: Data timeframe (1m, 5m, 1h, 1d)
            
        Returns:
            Dictionary with symbol as key and MarketData as value
        """
        logger.info(f"Collecting market data for symbols: {symbols}, timeframe: {timeframe}")
        
        if not symbols:
            raise DataValidationError(
                "Symbols list cannot be empty",
                error_code="EMPTY_SYMBOLS",
                context={"symbols": symbols}
            )
        
        results = {}
        
        for symbol in symbols:
            try:
                # Check cache first
                cached_data = self._get_cached_data(symbol)
                if cached_data:
                    logger.debug(f"Using cached data for {symbol}")
                    results[symbol] = cached_data
                    continue
                
                # Fetch fresh data
                market_data = await self._fetch_market_data(symbol, timeframe)
                if market_data:
                    # Cache the data
                    self.cache[symbol] = market_data
                    results[symbol] = market_data
                    logger.debug(f"Fetched fresh data for {symbol}")
                else:
                    logger.warning(f"No data received for {symbol}")
                    
            except Exception as e:
                logger.error(f"Error collecting data for {symbol}: {e}")
                # Try to use stale cached data as fallback
                if symbol in self.cache:
                    logger.info(f"Using stale cached data for {symbol}")
                    results[symbol] = self.cache[symbol]
                else:
                    raise APIError(
                        f"Failed to collect data for {symbol}: {e}",
                        error_code="DATA_COLLECTION_FAILED",
                        context={"symbol": symbol, "error": str(e)}
                    )
        
        return results
    
    async def validate_data(self, data: Dict[str, Any]) -> bool:
        """
        Validate collected market data
        
        Args:
            data: Dictionary of market data to validate
            
        Returns:
            True if all data is valid, False otherwise
        """
        if not data:
            logger.warning("No data to validate")
            return False
        
        for symbol, market_data in data.items():
            try:
                if not isinstance(market_data, MarketData):
                    logger.error(f"Invalid data type for {symbol}: {type(market_data)}")
                    return False
                
                # MarketData validation is handled in __post_init__
                # Additional business logic validation can be added here
                
                # Check if data is too stale
                if market_data.is_stale(max_age_seconds=self.config.max_data_age_seconds):
                    logger.warning(f"Data for {symbol} is stale: {market_data.timestamp}")
                    return False
                
                # Validate spread is reasonable
                if market_data.spread > self.config.max_spread_threshold:
                    logger.warning(f"Spread too wide for {symbol}: {market_data.spread}")
                    return False
                    
            except DataValidationError as e:
                logger.error(f"Validation error for {symbol}: {e}")
                return False
            except Exception as e:
                logger.error(f"Unexpected validation error for {symbol}: {e}")
                return False
        
        logger.info(f"Successfully validated data for {len(data)} symbols")
        return True
    
    async def _fetch_market_data(self, symbol: str, timeframe: str) -> Optional[MarketData]:
        """
        Fetch market data from broker API with retry logic
        
        Args:
            symbol: Currency pair symbol
            timeframe: Data timeframe
            
        Returns:
            MarketData object or None if failed
        """
        max_retries = self.config.api_max_retries
        retry_delay = self.config.api_retry_delay
        
        for attempt in range(max_retries):
            try:
                # Use broker interface to get market data
                market_data = await self.broker_interface.get_market_data(symbol)
                
                if market_data:
                    # Normalize and validate the data
                    normalized_data = self._normalize_market_data(market_data, symbol)
                    return normalized_data
                    
            except Exception as e:
                logger.warning(f"Attempt {attempt + 1} failed for {symbol}: {e}")
                
                if attempt < max_retries - 1:
                    # Exponential backoff
                    delay = retry_delay * (2 ** attempt)
                    logger.info(f"Retrying in {delay} seconds...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All retry attempts failed for {symbol}")
                    raise APIError(
                        f"Failed to fetch market data for {symbol} after {max_retries} attempts",
                        error_code="API_FETCH_FAILED",
                        context={"symbol": symbol, "attempts": max_retries}
                    )
        
        return None
    
    def _normalize_market_data(self, raw_data: Any, symbol: str) -> MarketData:
        """
        Normalize raw market data into MarketData object
        
        Args:
            raw_data: Raw data from broker API
            symbol: Currency pair symbol
            
        Returns:
            Normalized MarketData object
        """
        try:
            # Handle different data formats from various brokers
            if isinstance(raw_data, dict):
                return MarketData(
                    symbol=symbol,
                    timestamp=datetime.now(timezone.utc),
                    open=float(raw_data.get('open', 0)),
                    high=float(raw_data.get('high', 0)),
                    low=float(raw_data.get('low', 0)),
                    close=float(raw_data.get('close', 0)),
                    volume=int(raw_data.get('volume', 0)),
                    bid=float(raw_data.get('bid', 0)),
                    ask=float(raw_data.get('ask', 0)),
                    spread=float(raw_data.get('ask', 0)) - float(raw_data.get('bid', 0))
                )
            elif isinstance(raw_data, MarketData):
                # Already normalized
                return raw_data
            else:
                raise DataValidationError(
                    f"Unsupported data format: {type(raw_data)}",
                    error_code="UNSUPPORTED_DATA_FORMAT",
                    context={"data_type": type(raw_data), "symbol": symbol}
                )
                
        except (ValueError, KeyError, TypeError) as e:
            raise DataValidationError(
                f"Failed to normalize market data for {symbol}: {e}",
                error_code="DATA_NORMALIZATION_FAILED",
                context={"symbol": symbol, "raw_data": str(raw_data), "error": str(e)}
            )
    
    def _get_cached_data(self, symbol: str) -> Optional[MarketData]:
        """
        Get cached market data if still valid
        
        Args:
            symbol: Currency pair symbol
            
        Returns:
            Cached MarketData or None if not available/expired
        """
        if symbol not in self.cache:
            return None
        
        cached_data = self.cache[symbol]
        
        # Check if cache is still valid
        cache_age = datetime.now(timezone.utc) - cached_data.timestamp
        if cache_age <= self.cache_ttl:
            return cached_data
        
        # Remove expired cache entry
        del self.cache[symbol]
        return None
    
    def clear_cache(self) -> None:
        """Clear all cached data"""
        self.cache.clear()
        logger.info("Market data cache cleared")
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        return {
            "cached_symbols": list(self.cache.keys()),
            "cache_size": len(self.cache),
            "cache_ttl_seconds": self.cache_ttl.total_seconds()
        }
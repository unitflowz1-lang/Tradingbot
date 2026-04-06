"""
DataCoordinator: Singleton cache manager to prevent API fetch storms.

PROBLEM: Bot fetches MT5 data 100+ times per cycle (dozens per symbol), 
causing 6+ second latency.

SOLUTION: Central coordinator manages refresh frequency (one fetch per symbol 
per 10 seconds), caches results, and gates all MT5.copy_rates_from_pos() calls.

CRITICAL: Use DataCoordinator.get_latest(symbol) instead of raw MT5 calls.
"""

import time
import threading
import logging
from typing import Dict, Optional, Any, Tuple
from datetime import datetime, timezone
import MetaTrader5 as mt5

logger = logging.getLogger(__name__)


class DataCoordinator:
    """
    Singleton manager for market data caching.
    
    Prevents fetch storms by maintaining a single source of truth for OHLCV data.
    Only refreshes if:
    1. Cache is empty (first request)
    2. Cache is > 10 seconds old (TTL expired)
    3. Explicitly invalidated via clear()
    
    Thread-safe via RLock.
    """
    
    _instance: Optional["DataCoordinator"] = None
    _lock = threading.RLock()
    
    def __init__(self, refresh_interval_seconds: int = 10):
        """
        Initialize DataCoordinator.
        
        Args:
            refresh_interval_seconds: How long to keep cached data (default 10s)
        """
        self.refresh_interval_seconds = refresh_interval_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._last_update: Dict[str, float] = {}
        self._fetch_count: Dict[str, int] = {}
        self._call_count: Dict[str, int] = {}  # Track get_latest() calls
        self._lock = threading.RLock()
        self._fetch_errors: Dict[str, str] = {}
        self._last_error_time: Dict[str, float] = {}
        logger.info(
            "[DATA_COORDINATOR_INIT] Refresh interval: %d seconds | "
            "Cache will skip fetches if data < %d seconds old",
            refresh_interval_seconds,
            refresh_interval_seconds
        )
    
    @classmethod
    def get_instance(cls, refresh_interval_seconds: int = 10) -> "DataCoordinator":
        """Get or create singleton instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(refresh_interval_seconds)
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton (testing only)."""
        with cls._lock:
            cls._instance = None
    
    def should_fetch(self, symbol: str) -> Tuple[bool, str]:
        """
        Determine if a fetch is needed.
        
        Returns:
            (should_fetch: bool, reason: str)
            - (True, "cache_empty") if never fetched
            - (True, "cache_expired") if > refresh_interval_seconds old
            - (False, "cache_fresh") if recently fetched
        """
        with self._lock:
            if symbol not in self._last_update:
                return True, "cache_empty"
            
            age_seconds = time.time() - self._last_update[symbol]
            if age_seconds > self.refresh_interval_seconds:
                return True, "cache_expired"
            
            return False, "cache_fresh"
    
    def get_latest(
        self,
        symbol: str,
        timeframe: int = mt5.TIMEFRAME_M1,
        bars: int = 600,
        force_refresh: bool = False
    ) -> Optional[Any]:
        """
        Get latest OHLCV data for symbol.
        
        Uses cache if fresh, fetches from MT5 if stale/empty.
        
        Args:
            symbol: Trading symbol (e.g., "EUR/USD")
            timeframe: MT5 timeframe constant (default M1)
            bars: Number of bars to fetch (default 600)
            force_refresh: If True, always fetch (bypass cache)
        
        Returns:
            OHLCV data or None if fetch failed
        """
        with self._lock:
            # Track call frequency for diagnostics
            self._call_count[symbol] = self._call_count.get(symbol, 0) + 1
            
            # Check cache
            should_fetch, reason = self.should_fetch(symbol)
            
            if not force_refresh and not should_fetch:
                # Cache is fresh, return cached data
                logger.debug(
                    "[DATA_COORDINATOR_HIT] %s | Cache fresh (%.1f seconds old) | "
                    "Call #%d this cycle",
                    symbol,
                    time.time() - self._last_update.get(symbol, 0.0),
                    self._call_count[symbol]
                )
                return self._cache.get(symbol)
            
            # Cache is stale or empty, fetch fresh data
            try:
                logger.debug(
                    "[DATA_COORDINATOR_FETCH] %s | Reason: %s | "
                    "Previous fetch #%d | Call #%d this cycle",
                    symbol,
                    reason,
                    self._fetch_count.get(symbol, 0),
                    self._call_count[symbol]
                )
                
                rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, bars)
                
                if rates is None or len(rates) == 0:
                    error_msg = f"MT5 returned empty data (session/symbol not available)"
                    self._fetch_errors[symbol] = error_msg
                    self._last_error_time[symbol] = time.time()
                    logger.warning(
                        "[DATA_COORDINATOR_ERROR] %s | %s",
                        symbol,
                        error_msg
                    )
                    return None
                
                # Cache data
                self._cache[symbol] = rates
                self._last_update[symbol] = time.time()
                self._fetch_count[symbol] = self._fetch_count.get(symbol, 0) + 1
                self._fetch_errors.pop(symbol, None)  # Clear any prior errors
                
                logger.info(
                    "[DATA_COORDINATOR_STORED] %s | Bars: %d | "
                    "Fetch #%d | Next refresh in %d seconds",
                    symbol,
                    len(rates),
                    self._fetch_count[symbol],
                    self.refresh_interval_seconds
                )
                return rates
                
            except Exception as e:
                error_msg = str(e)
                self._fetch_errors[symbol] = error_msg
                self._last_error_time[symbol] = time.time()
                logger.error(
                    "[DATA_COORDINATOR_EXCEPTION] %s | %s",
                    symbol,
                    error_msg
                )
                return None
    
    def get_cache_status(self, symbol: str) -> Dict[str, Any]:
        """
        Get diagnostic info about cache state for a symbol.
        
        Returns:
            Dict with keys: age_seconds, cache_size, fetch_count, is_fresh, error
        """
        with self._lock:
            now = time.time()
            last_fetch = self._last_update.get(symbol)
            
            if last_fetch is None:
                age_sec = None
                is_fresh = False
            else:
                age_sec = now - last_fetch
                is_fresh = age_sec <= self.refresh_interval_seconds
            
            cached_data = self._cache.get(symbol)
            cache_size = len(cached_data) if cached_data is not None else 0
            
            return {
                "symbol": symbol,
                "age_seconds": age_sec,
                "cache_size_bars": cache_size,
                "fetch_count": self._fetch_count.get(symbol, 0),
                "call_count": self._call_count.get(symbol, 0),
                "is_fresh": is_fresh,
                "last_error": self._fetch_errors.get(symbol),
                "refresh_interval_seconds": self.refresh_interval_seconds,
            }
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get aggregate cache statistics.
        
        Returns:
            Dict with overall performance metrics
        """
        with self._lock:
            total_fetches = sum(self._fetch_count.values())
            total_calls = sum(self._call_count.values())
            total_bars = sum(
                len(data) if data is not None else 0
                for data in self._cache.values()
            )
            
            cache_hit_ratio = 1.0
            if total_calls > 0:
                cache_hit_ratio = 1.0 - (total_fetches / total_calls) if total_fetches > 0 else 1.0
            
            return {
                "total_symbols": len(self._cache),
                "total_bars_cached": total_bars,
                "total_fetches": total_fetches,
                "total_get_latest_calls": total_calls,
                "cache_hit_ratio": cache_hit_ratio,
                "symbols_with_errors": list(self._fetch_errors.keys()),
                "refresh_interval_seconds": self.refresh_interval_seconds,
            }
    
    def clear(self, symbol: Optional[str] = None) -> None:
        """
        Clear cache.
        
        Args:
            symbol: If provided, clear only this symbol. If None, clear all.
        """
        with self._lock:
            if symbol is None:
                self._cache.clear()
                self._last_update.clear()
                logger.info("[DATA_COORDINATOR_CLEAR] All cache cleared")
            else:
                self._cache.pop(symbol, None)
                self._last_update.pop(symbol, None)
                logger.info("[DATA_COORDINATOR_CLEAR] %s cache cleared", symbol)
    
    def invalidate(self, symbol: str) -> None:
        """Force cache invalidation for a symbol (will fetch on next get_latest)."""
        with self._lock:
            self._last_update.pop(symbol, None)
            logger.debug("[DATA_COORDINATOR_INVALIDATE] %s cache invalidated", symbol)


def get_data_coordinator(refresh_interval_seconds: int = 10) -> DataCoordinator:
    """Convenience function to get singleton DataCoordinator instance."""
    return DataCoordinator.get_instance(refresh_interval_seconds)


# ===== USAGE PATTERN =====
# Instead of:
#     for symbol in symbols:
#         rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 600)
#         # ... do something ...
#         rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M1, 0, 600)  # WRONG: 2x fetch!
#
# Use:
#     coordinator = get_data_coordinator(refresh_interval_seconds=10)
#     for symbol in symbols:
#         rates = coordinator.get_latest(symbol)  # Fetches once, caches rest
#         # ... do something ...
#         rates = coordinator.get_latest(symbol)  # Uses cache, no fetch
#
# Expected: 2-3 fetches per symbol per cycle (vs 50+ without coordinator)
